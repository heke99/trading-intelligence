"""Read-only local quality and version review. No source values are displayed."""
from __future__ import annotations

import re
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .common import DataError, MAX_ROWS, field, json_bytes, load_json, positive_id
from .pipeline import CSV_FIELDS

SOURCE_FIELDS = sorted({name.split(".")[0] for name in CSV_FIELDS})
SOURCE_FIELD_NAMES = {name.casefold() for name in SOURCE_FIELDS}
QUALITY_FLAGS = {
    "TIMEZONE_UNVERIFIED", "INSTRUMENT_TYPE_REQUIRES_REVIEW", "FALLBACK_SOURCE_ID",
    "OPEN_CLOSE_QUANTITY_MISMATCH", "AGGREGATED_ENTRY_EXIT_VWAP",
    "COST_SEMANTICS_UNVERIFIED", "PNL_CURRENCY_UNKNOWN",
    "ORDER_SNAPSHOT_NOT_EVENT_LOG", "FILL_TIME_NOT_PROVIDED",
}
COUNT_FIELDS = ("source_rows", "inserted_versions", "duplicate_observations",
                "revision_observations", "quarantined_rows")


def _object(raw: str) -> dict:
    value = load_json(raw.encode())
    if not isinstance(value, dict):
        raise DataError("REVIEW_OBJECT_SCHEMA")
    return value


def _count(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_ROWS:
        raise DataError("REVIEW_COUNT_SCHEMA")
    return value


def _changed_fields(before: dict, after: dict) -> list[str]:
    changed = []
    for name in SOURCE_FIELDS:
        before_present = any(key.casefold() == name.casefold() for key in before)
        after_present = any(key.casefold() == name.casefold() for key in after)
        if (before_present != after_present
                or json_bytes(field(before, name)) != json_bytes(field(after, name))):
            changed.append(name)
    before_other = {key: value for key, value in before.items() if key.casefold() not in SOURCE_FIELD_NAMES}
    after_other = {key: value for key, value in after.items() if key.casefold() not in SOURCE_FIELD_NAMES}
    if json_bytes(before_other) != json_bytes(after_other):
        changed.append("other_source_fields")
    if not changed:
        changed.append("source_field_layout")
    return changed


def _timestamp_ranges(manifest: dict) -> dict:
    saved = manifest.get("observed_timestamp_ranges", {})
    if not isinstance(saved, dict):
        raise DataError("REVIEW_TIMESTAMP_SCHEMA")
    ranges = {}
    for name in ("closed_trades:opened_at_utc", "closed_trades:closed_at_utc", "orders:posted_at_utc"):
        bounds = saved.get(name)
        if bounds is None:
            continue
        if not isinstance(bounds, dict):
            raise DataError("REVIEW_TIMESTAMP_SCHEMA")
        parsed = {}
        for key in ("min", "max"):
            raw = bounds.get(key)
            if not isinstance(raw, str) or len(raw) > 40:
                raise DataError("REVIEW_TIMESTAMP_SCHEMA")
            try:
                date = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                raise DataError("REVIEW_TIMESTAMP_SCHEMA") from None
            if date.tzinfo is None:
                raise DataError("REVIEW_TIMESTAMP_SCHEMA")
            parsed[key] = date.astimezone(timezone.utc).isoformat()
        ranges[name] = parsed
    return ranges


def review_dataset(out: Path, *, run_id: str | None = None) -> dict:
    if run_id is not None and not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise DataError("REVIEW_RUN_ID_INVALID")
    database = Path(out) / "history.sqlite3"
    if not database.is_file():
        raise DataError("REVIEW_DATABASE_NOT_FOUND")
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only = ON")
        conn.execute("BEGIN")  # Keep the manifest and all comparisons in one read snapshot.
        if run_id is None:
            saved = conn.execute("SELECT run_id, manifest_json FROM runs ORDER BY rowid DESC LIMIT 1").fetchone()
        else:
            saved = conn.execute("SELECT run_id, manifest_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if saved is None:
            raise DataError("REVIEW_RUN_NOT_FOUND")
        run_id = saved["run_id"]
        manifest = _object(saved["manifest_json"])
        if manifest.get("run_id") != run_id or not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise DataError("REVIEW_MANIFEST_SCHEMA")
        if manifest.get("status") not in ("in_progress", "completed", "completed_with_quarantine", "failed"):
            raise DataError("REVIEW_MANIFEST_SCHEMA")
        strategy = str(positive_id(manifest.get("strategy_id")))
        flags = manifest.get("quality_flag_counts", {})
        if not isinstance(flags, dict):
            raise DataError("REVIEW_MANIFEST_SCHEMA")
        comparison = {
            "comparison_basis": "observed_versions_vs_immediate_insertion_predecessor",
            "pairs_compared": 0, "versions_without_predecessor": 0,
            "source_changed_pairs": 0, "source_unchanged_normalized_changed_pairs": 0,
            "source_and_normalized_unchanged_pairs": 0,
        }
        field_counts = Counter()
        identities, symbols = set(), set()
        versions = 0
        records = conn.execute("""
            SELECT DISTINCT v.* FROM record_versions v
            JOIN observations o ON o.record_version_id=v.id
            WHERE o.run_id=? ORDER BY v.id
        """, (run_id,))
        for record in records:
            versions += 1
            if versions > MAX_ROWS:
                raise DataError("REVIEW_ROW_LIMIT")
            if record["strategy_id"] != strategy:
                raise DataError("REVIEW_RECORD_STRATEGY_MISMATCH")
            identity = tuple(record[key] for key in ("strategy_id", "kind", "source_id", "data_origin"))
            identities.add(identity)
            normalized = _object(record["normalized_json"])
            if not isinstance(normalized.get("symbol_raw"), str):
                raise DataError("REVIEW_NORMALIZED_SCHEMA")
            symbols.add(normalized["symbol_raw"])
            previous = conn.execute("""
                SELECT source_record_json, normalized_json FROM record_versions
                WHERE strategy_id=? AND kind=? AND source_id=? AND data_origin=? AND id<?
                ORDER BY id DESC LIMIT 1
            """, (*identity, record["id"])).fetchone()
            if previous is None:
                comparison["versions_without_predecessor"] += 1
                continue
            comparison["pairs_compared"] += 1
            before, after = _object(previous["source_record_json"]), _object(record["source_record_json"])
            if json_bytes(before) != json_bytes(after):
                comparison["source_changed_pairs"] += 1
                field_counts.update(_changed_fields(before, after))
            elif json_bytes(_object(previous["normalized_json"])) != json_bytes(normalized):
                comparison["source_unchanged_normalized_changed_pairs"] += 1
            else:
                # Context is part of the hash but is not fully stored in old versions.
                comparison["source_and_normalized_unchanged_pairs"] += 1
        comparison["changed_source_field_counts"] = dict(sorted(field_counts.items()))
        traversal = manifest.get("endpoint_traversal", {})
        if not isinstance(traversal, dict):
            raise DataError("REVIEW_MANIFEST_SCHEMA")
        states = {"complete", "incomplete", "not_requested", "unverified_local_file"}
        return {
            "run_id": run_id, "strategy_id": strategy, "run_status": manifest["status"],
            "import_counts": {name: _count(manifest.get(name, 0)) for name in COUNT_FIELDS},
            "record_versions_observed": versions, "distinct_source_ids_observed": len(identities),
            "distinct_symbols_observed": len(symbols),
            "quality_flag_counts": {name: _count(flags[name]) for name in sorted(QUALITY_FLAGS) if name in flags},
            "unrecognized_quality_flag_observations": sum(_count(value) for name, value in flags.items()
                                                         if name not in QUALITY_FLAGS),
            "observed_timestamp_ranges": _timestamp_ranges(manifest),
            "endpoint_traversal": {kind: traversal.get(kind) if traversal.get(kind) in states else "unknown"
                                   for kind in ("closed_trades", "orders")},
            "version_comparison": comparison,
            "scope": "local_quality_and_version_history_review", "review_does_not_clear_blockers": True,
            "network_used": False, "data_saved": False, "training_ready": False,
            "full_history_verified": False,
        }
