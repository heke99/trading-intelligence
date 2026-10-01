"""Publisher evidence storage, deliberately separate from C2 trade records.

Raw snapshots identify bytes; semantic record versions identify source content
and adapter policy. Completed views retain historical versions, never select an
unreviewed revision as the latest truth. Source row locators are not trade IDs.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

from .common import DataError, json_bytes, now_utc, sha256
from .store import DatasetStore
from . import __version__

PUBLISHER_POLICY_VERSION = 1


class PublisherStore(DatasetStore):
    def __init__(self, root: Path):
        super().__init__(root)
        (self.root / "publisher-runs").mkdir(exist_ok=True, mode=0o700)
        self.conn.executescript("""
          CREATE TABLE IF NOT EXISTS publisher_imports (
            run_id TEXT PRIMARY KEY, status TEXT NOT NULL, manifest_json TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS publisher_sources (
            source_id TEXT NOT NULL, data_origin TEXT NOT NULL, config_hash TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            PRIMARY KEY(source_id, data_origin, config_hash));
          CREATE TABLE IF NOT EXISTS publisher_snapshots (
            id INTEGER PRIMARY KEY, source_id TEXT NOT NULL, data_origin TEXT NOT NULL,
            raw_hash TEXT NOT NULL, semantic_hash TEXT NOT NULL,
            config_hash TEXT NOT NULL, adapter_version TEXT NOT NULL,
            raw_path TEXT NOT NULL, first_imported_at_utc TEXT NOT NULL,
            UNIQUE(source_id, data_origin, raw_hash, config_hash, adapter_version));
          CREATE TABLE IF NOT EXISTS publisher_record_versions (
            id INTEGER PRIMARY KEY, source_id TEXT NOT NULL, data_origin TEXT NOT NULL,
            record_kind TEXT NOT NULL, row_identity TEXT NOT NULL,
            row_semantic_hash TEXT NOT NULL, version_hash TEXT NOT NULL,
            normalized_json TEXT NOT NULL, first_imported_at_utc TEXT NOT NULL,
            UNIQUE(source_id, data_origin, record_kind, row_identity, version_hash));
          CREATE TABLE IF NOT EXISTS publisher_occurrences (
            run_id TEXT NOT NULL REFERENCES publisher_imports(run_id),
            snapshot_id INTEGER NOT NULL REFERENCES publisher_snapshots(id),
            record_version_id INTEGER NOT NULL REFERENCES publisher_record_versions(id),
            sheet TEXT NOT NULL, physical_row INTEGER NOT NULL,
            observation_json TEXT NOT NULL,
            UNIQUE(run_id, snapshot_id, sheet, physical_row));
          CREATE VIEW IF NOT EXISTS completed_publisher_records AS
            SELECT DISTINCT v.* FROM publisher_record_versions v
            JOIN publisher_occurrences o ON o.record_version_id=v.id
            JOIN publisher_imports r ON r.run_id=o.run_id
            WHERE r.status IN ('completed', 'completed_with_quarantine');
        """)
        self.conn.commit()

    def start_publisher_run(self, mode: str, *, synthetic: bool = False) -> dict:
        run_id = uuid4().hex
        (self.root / "publisher-runs" / run_id).mkdir(mode=0o700)
        manifest = {
            "schema_version": 1, "publisher_policy_version": PUBLISHER_POLICY_VERSION,
            "software_version": __version__,
            "run_id": run_id, "source": "publisher_evidence", "mode": mode,
            "data_origin": "synthetic_fixture" if synthetic else "publisher_reported_unverified",
            "started_at_utc": now_utc(), "finished_at_utc": None, "status": "in_progress",
            "source_rows": 0, "inserted_versions": 0, "duplicate_observations": 0,
            "revision_observations": 0, "inserted_snapshots": 0,
            "temporal_quarantined_rows": 0, "source_summaries": [],
            "record_type_counts": {}, "quality_flag_counts": {},
            "date_ranges": {}, "instrument_labels": {}, "raw_files": [], "errors": [],
            "entry_link_groups": 0, "ambiguous_entry_link_groups": [],
            "training_ready": False, "full_history_verified": False,
            "broker_authenticated": False, "market_history_joined": False,
            "training_rights": "not_verified", "trading_enabled": False,
            "identity_basis": "source_locator_not_independently_verified_trade_id",
            "accepted_view_policy": "completed historical versions; no automatic latest winner",
            "blockers": ["TRAINING_NOT_IMPLEMENTED", "MARKET_HISTORY_NOT_JOINED",
                         "TRAINING_RIGHTS_NOT_VERIFIED", "FULL_HISTORY_NOT_VERIFIED",
                         "BROKER_EXECUTIONS_NOT_AUTHENTICATED", "DECISION_CONTEXT_NOT_VERIFIED"],
        }
        if synthetic:
            manifest["blockers"].append("SYNTHETIC_TEST_DATA_ONLY")
        self.save_publisher_manifest(manifest)
        return manifest

    def save_publisher_manifest(self, manifest: dict) -> None:
        raw = json_bytes(manifest)
        with self.conn:
            self.conn.execute("INSERT INTO publisher_imports VALUES (?,?,?) ON CONFLICT(run_id) "
                              "DO UPDATE SET status=excluded.status, manifest_json=excluded.manifest_json",
                              (manifest["run_id"], manifest["status"], raw.decode()))
        directory = self.root / "publisher-runs" / manifest["run_id"]
        temporary = directory / (uuid4().hex + ".tmp")
        try:
            with temporary.open("xb") as handle:
                os.chmod(temporary, 0o600)
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(directory / "manifest.json")
        finally:
            temporary.unlink(missing_ok=True)

    def archive_publisher_bytes(self, raw: bytes, manifest: dict, *, kind: str,
                                suffix: str, source_id: str | None = None) -> str:
        if suffix not in {"xlsx", "json", "jsonl", "png"}:
            raise DataError("PUBLISHER_RAW_SUFFIX_INVALID")
        digest = sha256(raw)
        path = self.root / "raw" / f"{digest}.{suffix}"
        temporary = self.root / "raw" / (uuid4().hex + ".tmp")
        try:
            with temporary.open("xb") as handle:
                os.chmod(temporary, 0o600)
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if sha256(path.read_bytes()) != digest:
                    raise DataError("RAW_HASH_MISMATCH")
        finally:
            temporary.unlink(missing_ok=True)
        manifest["raw_files"].append({
            "kind": kind, "source_id": source_id, "sha256": digest,
            "path": "raw/" + path.name, "bytes": len(raw),
            "imported_at_utc": now_utc(), "original_retrieved_at_utc": None,
            "clock_basis": "local import clock; not original download or execution time"})
        self.save_publisher_manifest(manifest)
        return digest

    def add_snapshot(self, manifest: dict, source: dict, raw_hash: str, semantic_hash: str,
                     adapter_version: str, raw_path: str) -> tuple[int, str]:
        source_id = source["id"]
        origin = manifest["data_origin"]
        config_hash = sha256(json_bytes(source))
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO publisher_sources VALUES (?,?,?,?)",
                              (source_id, origin, config_hash, json_bytes(source).decode()))
            key = (source_id, origin, raw_hash, config_hash, adapter_version)
            existing = self.conn.execute("SELECT id FROM publisher_snapshots WHERE source_id=? "
                                         "AND data_origin=? AND raw_hash=? AND config_hash=? "
                                         "AND adapter_version=?", key).fetchone()
            if existing:
                return existing[0], config_hash
            cursor = self.conn.execute("INSERT INTO publisher_snapshots(source_id,data_origin,raw_hash,"
                                       "semantic_hash,config_hash,adapter_version,raw_path,first_imported_at_utc) "
                                       "VALUES(?,?,?,?,?,?,?,?)", (*key[:3], semantic_hash, *key[3:], raw_path, now_utc()))
            manifest["inserted_snapshots"] += 1
            return cursor.lastrowid, config_hash

    def add_publisher_record(self, manifest: dict, record: dict, *, snapshot_id: int,
                             adapter_version: str, normalization_context: dict) -> None:
        record = dict(record)
        record.update(data_origin=manifest["data_origin"], training_ready=False,
                      full_history_verified=False, broker_fill_verified=False)
        record.setdefault("usage_role", "publisher_observation_not_decision_time_features")
        identity = record["source_row_identity"]
        row_identity = identity if isinstance(identity, str) else json_bytes(identity).decode()
        semantic_hash = record["row_semantic_sha256"]
        key = (record["source_id"], manifest["data_origin"], record["record_kind"], row_identity)
        fingerprint = sha256(json_bytes({"row_semantic_hash": semantic_hash,
                                        "adapter_version": adapter_version,
                                        "publisher_policy_version": PUBLISHER_POLICY_VERSION,
                                        "normalization_context": normalization_context}))
        flags = list(dict.fromkeys(record["quality_flags"]))
        with self.conn:
            other_version = self.conn.execute("SELECT 1 FROM publisher_record_versions WHERE source_id=? "
                                              "AND data_origin=? AND record_kind=? AND row_identity=? "
                                              "AND version_hash<>? LIMIT 1", (*key, fingerprint)).fetchone()
            if other_version:
                flags.append("SOURCE_REVISION_REQUIRES_REVIEW")
                if "SOURCE_REVISION_REQUIRES_REVIEW" not in manifest["blockers"]:
                    manifest["blockers"].append("SOURCE_REVISION_REQUIRES_REVIEW")
            found = self.conn.execute("SELECT id FROM publisher_record_versions WHERE source_id=? "
                                      "AND data_origin=? AND record_kind=? AND row_identity=? AND version_hash=?",
                                      (*key, fingerprint)).fetchone()
            if found:
                version_id = found[0]
                manifest["duplicate_observations"] += 1
            else:
                prior = self.conn.execute("SELECT id FROM publisher_record_versions WHERE source_id=? "
                                          "AND data_origin=? AND record_kind=? AND row_identity=? LIMIT 1", key).fetchone()
                if prior:
                    manifest["revision_observations"] += 1
                    flags.append("SOURCE_REVISION_REQUIRES_REVIEW")
                    if "SOURCE_REVISION_REQUIRES_REVIEW" not in manifest["blockers"]:
                        manifest["blockers"].append("SOURCE_REVISION_REQUIRES_REVIEW")
                record["quality_flags"] = sorted(set(flags))
                cursor = self.conn.execute("INSERT INTO publisher_record_versions(source_id,data_origin,"
                                           "record_kind,row_identity,row_semantic_hash,version_hash,normalized_json,"
                                           "first_imported_at_utc) VALUES(?,?,?,?,?,?,?,?)",
                                           (*key, semantic_hash, fingerprint, json_bytes(record).decode(), now_utc()))
                version_id = cursor.lastrowid
                manifest["inserted_versions"] += 1
            record["quality_flags"] = sorted(set(flags))
            self.conn.execute("INSERT INTO publisher_occurrences VALUES(?,?,?,?,?,?)",
                              (manifest["run_id"], snapshot_id, version_id, record["sheet"],
                               record["source_row"], json_bytes(record).decode()))
        manifest["source_rows"] += 1
        kind = record["record_kind"]
        manifest["record_type_counts"][kind] = manifest["record_type_counts"].get(kind, 0) + 1
        manifest["temporal_quarantined_rows"] += int(bool(record.get("temporal_quarantined")))
        for flag in record["quality_flags"]:
            manifest["quality_flag_counts"][flag] = manifest["quality_flag_counts"].get(flag, 0) + 1
        symbol = record.get("instrument") or record.get("ticker")
        if symbol:
            manifest["instrument_labels"][symbol] = manifest["instrument_labels"].get(symbol, 0) + 1
        for field in ("transaction_date_local", "entry_date_local", "exit_date_local", "date_local",
                      "entry_date", "exit_date"):
            value = record.get(field)
            if value:
                bounds = manifest["date_ranges"].setdefault(f"{kind}:{field}", {"min": value, "max": value})
                bounds["min"], bounds["max"] = min(bounds["min"], value), max(bounds["max"], value)

    def finish_publisher_run(self, manifest: dict, error: str | None = None) -> dict:
        if error:
            manifest["status"] = "failed"
            manifest["errors"].append(error)
        else:
            manifest["status"] = ("completed_with_quarantine" if manifest["temporal_quarantined_rows"]
                                  else "completed")
        manifest["finished_at_utc"] = now_utc()
        path = self.root / "publisher-runs" / manifest["run_id"] / "observations.jsonl"
        with path.open("wb") as handle:
            os.chmod(path, 0o600)
            for (value,) in self.conn.execute("SELECT observation_json FROM publisher_occurrences WHERE run_id=? "
                                             "ORDER BY snapshot_id,sheet,physical_row", (manifest["run_id"],)):
                handle.write((json.dumps(json.loads(value), ensure_ascii=False, separators=(",", ":")) + "\n").encode())
        self.save_publisher_manifest(manifest)
        return manifest
