"""Local immutable raw files, versioned SQLite records and per-run manifests.

SQLite is an ingestion/audit store, not a real-time trading database. Real data
must stay outside version control. Atomic manifests and failed-run state make
partial acquisition visible; failed runs are excluded from the completed view.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from uuid import uuid4

from . import __version__
from .common import DataError, json_bytes, now_utc, sha256


class DatasetStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for sub in ("raw", "runs"):
            (self.root / sub).mkdir(exist_ok=True, mode=0o700)
        self.db_path = self.root / "history.sqlite3"
        self.conn = sqlite3.connect(self.db_path, timeout=30)
        self.db_path.chmod(0o600)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript("""
          CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY, status TEXT NOT NULL, manifest_json TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS record_versions (
            id INTEGER PRIMARY KEY, strategy_id TEXT NOT NULL, kind TEXT NOT NULL,
            source_id TEXT NOT NULL, data_origin TEXT NOT NULL, version_hash TEXT NOT NULL,
            normalized_json TEXT NOT NULL, source_record_json TEXT NOT NULL,
            first_observed_at TEXT NOT NULL,
            UNIQUE(strategy_id, kind, source_id, data_origin, version_hash));
          CREATE TABLE IF NOT EXISTS observations (
            run_id TEXT NOT NULL REFERENCES runs(run_id),
            record_version_id INTEGER NOT NULL REFERENCES record_versions(id),
            raw_hash TEXT NOT NULL, kind TEXT NOT NULL, row_number INTEGER NOT NULL,
            UNIQUE(run_id, raw_hash, kind, row_number));
          CREATE VIEW IF NOT EXISTS completed_run_records AS
            SELECT DISTINCT v.* FROM record_versions v
            JOIN observations o ON o.record_version_id=v.id
            JOIN runs r ON r.run_id=o.run_id
            WHERE r.status IN ('completed', 'completed_with_quarantine');
        """)
        self.conn.commit()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.conn.close()

    def start_run(self, strategy_id: int, mode: str, *, synthetic: bool = False) -> dict:
        run_id = uuid4().hex
        (self.root / "runs" / run_id).mkdir(mode=0o700)
        m = {
            "schema_version": 1, "software_version": __version__, "run_id": run_id,
            "strategy_id": str(strategy_id), "source": "collective2", "mode": mode,
            "data_origin": "synthetic_fixture" if synthetic else "c2_strategy_hypothetical",
            "started_at_utc": now_utc(), "finished_at_utc": None, "status": "in_progress",
            "endpoint_traversal": {"closed_trades": "not_requested", "orders": "not_requested"},
            "source_rows": 0, "inserted_versions": 0, "duplicate_observations": 0,
            "revision_observations": 0, "quarantined_rows": 0, "quality_flag_counts": {},
            "observed_timestamp_ranges": {}, "symbol_observations": {},
            "raw_files": [], "errors": [], "training_ready": False,
            "full_history_verified": False, "market_history_joined": False,
            "training_rights": "not_verified",
            "blockers": ["TRAINING_NOT_IMPLEMENTED", "MARKET_HISTORY_NOT_JOINED",
                         "TRAINING_RIGHTS_NOT_VERIFIED", "COVERAGE_NOT_INDEPENDENTLY_RECONCILED",
                         "EXECUTION_AND_COST_SEMANTICS_NOT_VERIFIED",
                         "POINT_IN_TIME_DATASET_NOT_BUILT", "NO_OUT_OF_SAMPLE_VALIDATION"],
        }
        if synthetic:
            m["blockers"].append("SYNTHETIC_TEST_DATA_ONLY")
        self.save_manifest(m)
        return m

    def save_manifest(self, manifest: dict) -> None:
        raw = json_bytes(manifest)
        with self.conn:
            self.conn.execute("INSERT INTO runs VALUES (?, ?, ?) ON CONFLICT(run_id) DO UPDATE SET status=excluded.status, manifest_json=excluded.manifest_json",
                              (manifest["run_id"], manifest["status"], raw.decode()))
        directory = self.root / "runs" / manifest["run_id"]
        temp = directory / (uuid4().hex + ".tmp")
        try:
            with temp.open("xb") as f:
                os.chmod(temp, 0o600)
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            temp.replace(directory / "manifest.json")
        finally:
            temp.unlink(missing_ok=True)

    def archive(self, raw: bytes, manifest: dict, kind: str, *, suffix: str = "json") -> str:
        if suffix not in ("json", "csv"):
            raise DataError("RAW_SUFFIX_INVALID")
        digest = sha256(raw)
        path = self.root / "raw" / (digest + "." + suffix)
        # Atomic, no-overwrite publication. Check existing content rather than trusting its filename.
        temp = self.root / "raw" / (uuid4().hex + ".tmp")
        try:
            with temp.open("xb") as f:
                os.chmod(temp, 0o600)
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.link(temp, path)
            except FileExistsError:
                if sha256(path.read_bytes()) != digest:
                    raise DataError("RAW_HASH_MISMATCH")
        finally:
            temp.unlink(missing_ok=True)
        manifest["raw_files"].append({"kind": kind, "sha256": digest,
                                      "path": "raw/" + path.name, "bytes": len(raw),
                                      "observed_at_utc": now_utc()})
        self.save_manifest(manifest)
        return digest

    def add_record(self, manifest: dict, normalized: dict, source: dict, raw_hash: str,
                   row_number: int, *, context: dict) -> None:
        source_json = json_bytes(source).decode()
        # Changes to the normalization policy create reviewable versions too.
        version_hash = sha256(json_bytes({"source": source, "context": context,
                                         "normalizer_version": normalized["normalizer_version"]}))
        key = (normalized["strategy_id"], normalized["kind"], normalized["source_id"], normalized["data_origin"])
        with self.conn:
            existing = self.conn.execute("SELECT id FROM record_versions WHERE strategy_id=? AND kind=? AND source_id=? AND data_origin=? AND version_hash=?", (*key, version_hash)).fetchone()
            if existing:
                version_id = existing[0]
                manifest["duplicate_observations"] += 1
            else:
                revised = self.conn.execute("SELECT 1 FROM record_versions WHERE strategy_id=? AND kind=? AND source_id=? AND data_origin=? LIMIT 1", key).fetchone()
                if revised:
                    manifest["revision_observations"] += 1
                    if "SOURCE_REVISION_REQUIRES_REVIEW" not in manifest["blockers"]:
                        manifest["blockers"].append("SOURCE_REVISION_REQUIRES_REVIEW")
                cursor = self.conn.execute("INSERT INTO record_versions(strategy_id,kind,source_id,data_origin,version_hash,normalized_json,source_record_json,first_observed_at) VALUES (?,?,?,?,?,?,?,?)",
                                           (*key, version_hash, json_bytes(normalized).decode(), source_json, now_utc()))
                version_id = cursor.lastrowid
                manifest["inserted_versions"] += 1
            self.conn.execute("INSERT OR IGNORE INTO observations VALUES(?,?,?,?,?)",
                              (manifest["run_id"], version_id, raw_hash, normalized["kind"], row_number))
        symbol_key = normalized["kind"] + ":" + normalized["symbol_raw"]
        manifest["symbol_observations"][symbol_key] = manifest["symbol_observations"].get(symbol_key, 0) + 1
        for name in ("opened_at_utc", "closed_at_utc", "posted_at_utc"):
            value = normalized.get(name)
            if value:
                coverage_key = normalized["kind"] + ":" + name
                bounds = manifest["observed_timestamp_ranges"].setdefault(coverage_key, {"min": value, "max": value})
                bounds["min"], bounds["max"] = min(value, bounds["min"]), max(value, bounds["max"])
        for flag in normalized["quality_flags"]:
            manifest["quality_flag_counts"][flag] = manifest["quality_flag_counts"].get(flag, 0) + 1

    def quarantine(self, manifest: dict, raw_hash: str, kind: str, row_number: int, error_code: str) -> None:
        manifest["quarantined_rows"] += 1
        path = self.root / "runs" / manifest["run_id"] / "quarantine.jsonl"
        with path.open("ab") as f:
            os.chmod(path, 0o600)
            # Only references and stable codes: full rows remain in the immutable raw file.
            import json
            f.write((json.dumps({"raw_hash": raw_hash, "kind": kind,
                                 "row_number": row_number, "error": error_code}) + "\n").encode())

    def finish(self, manifest: dict, error: str | None = None) -> dict:
        if error:
            manifest["status"] = "failed"
            manifest["errors"].append(error)
        else:
            manifest["status"] = "completed_with_quarantine" if manifest["quarantined_rows"] else "completed"
        manifest["finished_at_utc"] = now_utc()
        path = self.root / "runs" / manifest["run_id"] / "normalized.jsonl"
        with path.open("wb") as f:
            os.chmod(path, 0o600)
            import json
            for (value,) in self.conn.execute("SELECT DISTINCT v.normalized_json FROM record_versions v JOIN observations o ON o.record_version_id=v.id WHERE o.run_id=? ORDER BY v.normalized_json", (manifest["run_id"],)):
                f.write((json.dumps(json.loads(value), ensure_ascii=False, separators=(",", ":")) + "\n").encode())
        self.save_manifest(manifest)
        return manifest

    def count_versions(self) -> int:
        return self.conn.execute("SELECT count(*) FROM record_versions").fetchone()[0]

    def count_completed_run_records(self) -> int:
        return self.conn.execute("SELECT count(*) FROM completed_run_records").fetchone()[0]
