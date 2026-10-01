"""Offline publisher imports; original evidence stays outside version control."""
from __future__ import annotations

import collections
from datetime import datetime, timezone
from pathlib import Path
import re

from .common import DataError, json_bytes, load_json, read_limited, sha256
from .publisher_store import PublisherStore


def source_identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", value):
        raise DataError("PUBLISHER_SOURCE_ID_INVALID")
    return value


def _failure(error: BaseException) -> str:
    return str(error) if isinstance(error, DataError) else (
        "INTERRUPTED" if isinstance(error, KeyboardInterrupt) else "PUBLISHER_IMPORT_IO_OR_INTERNAL_ERROR")


def _catalog(raw: bytes) -> list[dict]:
    document = load_json(raw)
    if not isinstance(document, dict) or not isinstance(document.get("downloadable_sources"), list):
        raise DataError("TRADER_CATALOG_SCHEMA_INVALID")
    sources = document["downloadable_sources"]
    seen = set()
    for source in sources:
        if not isinstance(source, dict):
            raise DataError("TRADER_CATALOG_SCHEMA_INVALID")
        source_id = source_identifier(source.get("id"))
        if source_id in seen:
            raise DataError("TRADER_CATALOG_DUPLICATE_SOURCE")
        seen.add(source_id)
        filename = source.get("local_filename")
        if (not isinstance(filename, str) or Path(filename).name != filename
                or "\\" in filename or not filename.endswith(".xlsx")):
            raise DataError("TRADER_SOURCE_FILENAME_INVALID")
    if not sources:
        raise DataError("TRADER_CATALOG_EMPTY")
    return sources


def _receipt_clock(receipts_dir: Path | None, source_id: str, digest: str) -> str | None:
    """Only a supplied, hash-matched receipt can identify a download clock."""
    if receipts_dir is None:
        return None
    clocks = set()
    for path in receipts_dir.glob("download_manifest_*.json"):
        document = load_json(read_limited(path))
        if not isinstance(document, list):
            raise DataError("DOWNLOAD_RECEIPT_SCHEMA_INVALID")
        for receipt in document:
            if not isinstance(receipt, dict):
                raise DataError("DOWNLOAD_RECEIPT_SCHEMA_INVALID")
            if receipt.get("id") != source_id or receipt.get("sha256") != digest:
                continue
            value = receipt.get("retrieved_at_utc")
            if value:
                try:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    raise DataError("DOWNLOAD_RECEIPT_CLOCK_INVALID") from None
                if parsed.tzinfo is None:
                    raise DataError("DOWNLOAD_RECEIPT_CLOCK_INVALID")
                clocks.add(parsed.astimezone(timezone.utc).isoformat())
    # Multiple retrievals are different events. Do not guess which belongs to this import.
    return next(iter(clocks)) if len(clocks) == 1 else None


def _entry_groups(records: list[dict]) -> tuple[int, list[dict]]:
    groups = collections.defaultdict(list)
    for row in records:
        if row["record_kind"] != "reported_day_exit_leg":
            continue
        link = row["mapped_raw_fields"].get("entry_post")
        if link:
            groups[link].append(row)
    conflicts = []
    for link, rows in groups.items():
        signatures = {tuple(row["mapped_raw_fields"].get(key) for key in
                            ("instrument", "position_side", "entry_date", "entry_time", "entry_price"))
                      for row in rows}
        if len(signatures) > 1:
            conflicts.append({"entry_link": link, "source_row_refs": [
                {"source_id": row["source_id"], "sheet": row["sheet"], "source_row": row["source_row"]}
                for row in rows]})
    return len(groups), conflicts


def import_trader_xlsx(catalog_path: Path, raw_dir: Path, out: Path, *,
                       source_ids: list[str] | None = None, include_swing: bool = True,
                       synthetic: bool = False, receipts_dir: Path | None = None) -> dict:
    from .trader_xlsx import ADAPTER_VERSION, normalize_workbook

    with PublisherStore(out) as store:
        manifest = store.start_publisher_run("trader_xlsx", synthetic=synthetic)
        manifest["include_swing"] = include_swing
        all_records = []
        try:
            catalog_raw = read_limited(Path(catalog_path))
            store.archive_publisher_bytes(catalog_raw, manifest, kind="source_catalog", suffix="json")
            sources = _catalog(catalog_raw)
            if receipts_dir is not None:
                for receipt_path in sorted(receipts_dir.glob("download_manifest_*.json")):
                    store.archive_publisher_bytes(read_limited(receipt_path), manifest,
                                                   kind="supplied_download_receipt", suffix="json")
            if source_ids:
                selected = {source_identifier(value) for value in source_ids}
                if selected - {s["id"] for s in sources}:
                    raise DataError("TRADER_SOURCE_NOT_IN_CATALOG")
                sources = [source for source in sources if source["id"] in selected]
            manifest["requested_source_ids"] = [source["id"] for source in sources]
            store.save_publisher_manifest(manifest)
            for source in sources:
                path = Path(raw_dir) / source["local_filename"]
                raw = read_limited(path)
                digest = store.archive_publisher_bytes(raw, manifest, kind="trader_workbook",
                                                       suffix="xlsx", source_id=source["id"])
                # Parse the immutable archived copy, so path mutation cannot race the byte receipt.
                parsed = normalize_workbook(store.root / "raw" / f"{digest}.xlsx", source,
                                            include_swing=include_swing)
                metadata = parsed["source_meta"]
                if metadata["raw_sha256"] != digest:
                    raise DataError("RAW_HASH_MISMATCH")
                snapshot_id, _ = store.add_snapshot(
                    manifest, source, digest, metadata["semantic_sha256"], str(ADAPTER_VERSION),
                    f"raw/{digest}.xlsx")
                before = {name: manifest[name] for name in (
                    "source_rows", "inserted_versions", "duplicate_observations", "revision_observations",
                    "temporal_quarantined_rows")}
                context = {"date_system": metadata["date_system"],
                           **{name: source.get(name) for name in (
                               "trader", "columns", "swing_columns", "sheet_name", "month")}}
                for row in parsed["observations"]:
                    store.add_publisher_record(manifest, row, snapshot_id=snapshot_id,
                                               adapter_version=str(ADAPTER_VERSION), normalization_context=context)
                    all_records.append(row)
                clock = _receipt_clock(receipts_dir, source["id"], digest)
                manifest["source_summaries"].append({
                    "source_id": source["id"], "trader": source["trader"],
                    "raw_sha256": digest, "semantic_sha256": metadata["semantic_sha256"],
                    "snapshot_id": snapshot_id, "adapter_version": str(ADAPTER_VERSION),
                    "original_retrieved_at_utc": clock,
                    "retrieval_clock_basis": "supplied hash-matched receipt" if clock else "unknown",
                    "publisher_url": source.get("publisher_url"), "source_url": source.get("xlsx_url"),
                    "mapped_sheets": metadata.get("mapped_sheets"),
                    "unmapped_sheets": metadata.get("unmapped_sheets"),
                    "selection_policy": metadata.get("selection_policy"),
                    "physical_row_selection_by_sheet": metadata.get("physical_row_selection_by_sheet"),
                    "counts": {name: manifest[name] - value for name, value in before.items()},
                    "record_type_counts": dict(collections.Counter(r["record_kind"] for r in parsed["observations"]))})
                store.save_publisher_manifest(manifest)
            manifest["entry_link_groups"], manifest["ambiguous_entry_link_groups"] = _entry_groups(all_records)
            if manifest["ambiguous_entry_link_groups"]:
                manifest["blockers"].append("ENTRY_LINK_GROUPS_REQUIRE_REVIEW")
            return store.finish_publisher_run(manifest)
        except BaseException as error:
            store.finish_publisher_run(manifest, _failure(error))
            raise


def import_publisher_evidence(path: Path, out: Path, *, kind: str, source_id: str,
                              synthetic: bool = False, assets_root: Path | None = None) -> dict:
    from .publisher_evidence import ADAPTER_VERSION, normalize_evidence

    source_id = source_identifier(source_id)
    with PublisherStore(out) as store:
        manifest = store.start_publisher_run("publisher_evidence", synthetic=synthetic)
        manifest["evidence_kind"] = kind
        manifest["requested_source_ids"] = [source_id]
        try:
            raw = read_limited(Path(path))
            suffix = "json" if kind == "strategy_cards" else "jsonl"
            digest = store.archive_publisher_bytes(raw, manifest, kind=kind,
                                                   suffix=suffix, source_id=source_id)
            rows = normalize_evidence(raw, kind=kind, source_id=source_id)
            if assets_root is not None and kind != "image_transactions":
                raise DataError("ASSET_ROOT_ONLY_FOR_IMAGE_TRANSACTIONS")
            checked_assets = {}
            if kind == "image_transactions" and assets_root is not None:
                root = assets_root.resolve()
                # Acquisition proof is retained separately from mapped financial fields.
                for row in rows:
                    evidence = row["provenance"]
                    relative = evidence.get("source_asset_path_reported")
                    expected = evidence.get("source_asset_sha256")
                    if not isinstance(relative, str) or Path(relative).is_absolute():
                        raise DataError("IMAGE_ASSET_PATH_INVALID")
                    candidate = (root / relative).resolve()
                    if not candidate.is_relative_to(root):
                        raise DataError("IMAGE_ASSET_PATH_INVALID")
                    if candidate in checked_assets and checked_assets[candidate] != expected:
                        raise DataError("IMAGE_ASSET_HASH_OR_FORMAT_MISMATCH")
                    if candidate not in checked_assets:
                        content = read_limited(candidate)
                        if not content.startswith(b"\x89PNG\r\n\x1a\n") or sha256(content) != expected:
                            raise DataError("IMAGE_ASSET_HASH_OR_FORMAT_MISMATCH")
                        checked_assets[candidate] = store.archive_publisher_bytes(
                            content, manifest, kind="original_image_asset", suffix="png", source_id=source_id)
            semantic = sha256(json_bytes([r["row_semantic_sha256"] for r in rows]))
            metadata = {"id": source_id, "evidence_kind": kind, "source_format": "reviewed_publisher_evidence"}
            snapshot_id, _ = store.add_snapshot(manifest, metadata, digest, semantic,
                                                str(ADAPTER_VERSION), f"raw/{digest}.{suffix}")
            for row in rows:
                if kind == "image_transactions" and not checked_assets:
                    row["quality_flags"].append("ORIGINAL_IMAGE_BYTES_NOT_VERIFIED_IN_THIS_IMPORT")
                store.add_publisher_record(manifest, row, snapshot_id=snapshot_id,
                                           adapter_version=str(ADAPTER_VERSION), normalization_context={"kind": kind})
            manifest["source_summaries"].append({"source_id": source_id, "raw_sha256": digest,
                                                 "semantic_sha256": semantic, "source_rows": len(rows),
                                                 "original_assets_hash_verified": len(checked_assets)})
            return store.finish_publisher_run(manifest)
        except BaseException as error:
            store.finish_publisher_run(manifest, _failure(error))
            raise


def publisher_status(out: Path) -> dict:
    paths = list((Path(out) / "publisher-runs").glob("*/manifest.json"))
    if not paths:
        raise DataError("NO_PUBLISHER_RUNS_FOUND")
    manifests = [load_json(read_limited(path)) for path in paths]
    with PublisherStore(out) as store:
        counts = {name: store.conn.execute("SELECT count(*) FROM " + name).fetchone()[0]
                  for name in ("publisher_snapshots", "publisher_record_versions", "publisher_occurrences",
                               "completed_publisher_records")}
    latest = max(manifests, key=lambda m: m["started_at_utc"])
    return {"latest_run": latest, "database_counts": counts, "training_ready": False,
            "full_history_verified": False, "trading_enabled": False}
