"""Local research store with append-only APIs and as-of evidence queries.

SQLite is the offline prototype, not the production market-data warehouse.
Declared source permissions are metadata, not independent legal verification.
"""

from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from .contracts import (
    AmbiguousIdentifier, ContractError, DataOrigin, Entity, EvidenceIntegrityError,
    Instrument, Listing, RecordConflict, UnknownIdentifier, Use, UseNotAllowed,
    required, utc,
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
 source_id TEXT PRIMARY KEY, origin TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source_permissions (
 source_id TEXT NOT NULL REFERENCES sources, known_at TEXT NOT NULL,
 uses_json TEXT NOT NULL, PRIMARY KEY(source_id,known_at));
CREATE TABLE IF NOT EXISTS entities (
 entity_id TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS instruments (
 instrument_id TEXT PRIMARY KEY, entity_id TEXT NOT NULL REFERENCES entities,
 kind TEXT NOT NULL, share_class TEXT, base_currency TEXT);
CREATE TABLE IF NOT EXISTS listings (
 listing_id TEXT PRIMARY KEY, instrument_id TEXT NOT NULL REFERENCES instruments,
 mic TEXT NOT NULL, trading_currency TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS raw_objects (
 sha256 TEXT PRIMARY KEY, payload BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS evidence_versions (
 evidence_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources,
 record_id TEXT NOT NULL, revision_id TEXT NOT NULL,
 sha256 TEXT NOT NULL REFERENCES raw_objects,
 published_at TEXT NOT NULL, received_at TEXT NOT NULL,
 correction_of TEXT REFERENCES evidence_versions,
 UNIQUE(source_id,record_id,revision_id), UNIQUE(source_id,record_id,received_at));
CREATE TABLE IF NOT EXISTS observations (
 evidence_id TEXT NOT NULL REFERENCES evidence_versions, observed_at TEXT NOT NULL,
 PRIMARY KEY(evidence_id,observed_at));
CREATE TABLE IF NOT EXISTS identifier_versions (
 mapping_id TEXT NOT NULL, known_at TEXT NOT NULL,
 provider TEXT NOT NULL, value TEXT NOT NULL,
 listing_id TEXT NOT NULL REFERENCES listings,
 valid_from TEXT NOT NULL, valid_to TEXT,
 evidence_id TEXT NOT NULL REFERENCES evidence_versions,
 PRIMARY KEY(mapping_id,known_at));
CREATE INDEX IF NOT EXISTS evidence_as_of
 ON evidence_versions(source_id,record_id,received_at);
CREATE INDEX IF NOT EXISTS identifier_as_of
 ON identifier_versions(provider,value,known_at);
"""


class EvidenceStore:
    def __init__(self, database: str | Path):
        self.db = sqlite3.connect(database)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self.db.close()

    def _immutable(self, table: str, key: dict, fields: dict):
        # table/field names are internal constants, never provider input.
        where = " AND ".join(f"{name}=?" for name in key)
        row = self.db.execute(f"SELECT * FROM {table} WHERE {where}", tuple(key.values())).fetchone()
        if row:
            if dict(row) != fields:
                raise RecordConflict("Existing record cannot be silently overwritten")
            return
        names = ",".join(fields)
        marks = ",".join("?" for _ in fields)
        self.db.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})", tuple(fields.values()))

    def register_source(self, source_id: str, origin: DataOrigin):
        fields = {"source_id": required(source_id, "source_id"), "origin": DataOrigin(origin).value}
        with self.db:
            self._immutable("sources", {"source_id": source_id}, fields)

    def set_permissions(self, source_id: str, *, known_at: datetime, uses: set[Use]):
        at = utc(known_at)
        fields = {"source_id": source_id, "known_at": at,
                  "uses_json": json.dumps(sorted({Use(x).value for x in uses}))}
        with self.db:
            self._immutable("source_permissions", {"source_id": source_id, "known_at": at}, fields)

    def require_use(self, source_id: str, use: Use, *, as_of: datetime):
        self._require_use(source_id, Use(use), utc(as_of))

    def _require_use(self, source_id: str, use: Use, as_of: str):
        row = self.db.execute(
            "SELECT uses_json FROM source_permissions WHERE source_id=? AND known_at<=? "
            "ORDER BY known_at DESC LIMIT 1", (source_id, as_of)).fetchone()
        if row is None or use.value not in json.loads(row["uses_json"]):
            raise UseNotAllowed("Source use is not explicitly permitted at this time")

    def register_entity(self, entity: Entity):
        with self.db:
            self._immutable("entities", {"entity_id": entity.entity_id}, asdict(entity))

    def register_instrument(self, instrument: Instrument):
        fields = asdict(instrument)
        fields["kind"] = instrument.kind.value
        with self.db:
            self._immutable("instruments", {"instrument_id": instrument.instrument_id}, fields)

    def register_listing(self, listing: Listing):
        row = self.db.execute("SELECT kind FROM instruments WHERE instrument_id=?",
                              (listing.instrument_id,)).fetchone()
        if row is None or row["kind"] not in {"equity", "etf"}:
            raise ContractError("Only equities and ETFs have exchange listings in this foundation")
        with self.db:
            self._immutable("listings", {"listing_id": listing.listing_id}, asdict(listing))

    def ingest(self, *, source_id: str, record_id: str, revision_id: str, payload: bytes,
               published_at: datetime, received_at: datetime, correction_of: str | None = None) -> str:
        required(record_id, "record_id")
        required(revision_id, "revision_id")
        if not isinstance(payload, bytes) or not payload:
            raise ContractError("Non-empty original bytes are required")
        published, received = utc(published_at), utc(received_at)
        if published > received:
            raise ContractError("Publication after receipt needs investigation, not a guessed timestamp")
        self._require_use(source_id, Use.STORAGE, received)
        digest = hashlib.sha256(payload).hexdigest()
        with self.db:
            old = self.db.execute(
                "SELECT * FROM evidence_versions WHERE source_id=? AND record_id=? AND revision_id=?",
                (source_id, record_id, revision_id)).fetchone()
            if old:
                if (old["sha256"] != digest or old["published_at"] != published
                        or old["correction_of"] != correction_of or received < old["received_at"]):
                    raise RecordConflict("Revision changed or its first observation would be backdated")
                evidence_id = old["evidence_id"]
            else:
                if correction_of is not None:
                    previous = self.db.execute("SELECT * FROM evidence_versions WHERE evidence_id=?",
                                               (correction_of,)).fetchone()
                    if (previous is None or previous["source_id"] != source_id
                            or previous["record_id"] != record_id or previous["received_at"] >= received):
                        raise ContractError("Correction must refer to an earlier version of the same record")
                if self.db.execute(
                    "SELECT 1 FROM evidence_versions WHERE source_id=? AND record_id=? AND received_at=?",
                    (source_id, record_id, received)).fetchone():
                    raise RecordConflict("Two revisions have an indistinguishable observation time")
                self.db.execute("INSERT OR IGNORE INTO raw_objects VALUES (?,?)", (digest, payload))
                saved = self.db.execute("SELECT payload FROM raw_objects WHERE sha256=?", (digest,)).fetchone()
                if saved["payload"] != payload:
                    raise EvidenceIntegrityError("Archived payload failed integrity verification")
                evidence_id = uuid4().hex
                self.db.execute("INSERT INTO evidence_versions VALUES (?,?,?,?,?,?,?,?)",
                                (evidence_id, source_id, record_id, revision_id, digest,
                                 published, received, correction_of))
            self.db.execute("INSERT OR IGNORE INTO observations VALUES (?,?)", (evidence_id, received))
        return evidence_id

    def evidence_as_of(self, source_id: str, record_id: str, *, as_of: datetime,
                       use: Use = Use.RESEARCH) -> dict | None:
        at = utc(as_of)
        self._require_use(source_id, Use(use), at)
        row = self.db.execute(
            "SELECT e.*, s.origin, r.payload FROM evidence_versions e "
            "JOIN sources s USING(source_id) JOIN raw_objects r USING(sha256) "
            "WHERE e.source_id=? AND e.record_id=? AND e.received_at<=? "
            "ORDER BY e.received_at DESC LIMIT 1", (source_id, record_id, at)).fetchone()
        if row is None:
            return None
        if hashlib.sha256(row["payload"]).hexdigest() != row["sha256"]:
            raise EvidenceIntegrityError("Archived payload failed integrity verification")
        return dict(row)

    def put_identifier(self, *, mapping_id: str, provider: str, value: str, listing_id: str,
                       valid_from: datetime, known_at: datetime, evidence_id: str,
                       valid_to: datetime | None = None):
        fields = {"mapping_id": required(mapping_id, "mapping_id"), "known_at": utc(known_at),
                  "provider": required(provider, "provider"), "value": required(value, "value"),
                  "listing_id": required(listing_id, "listing_id"), "valid_from": utc(valid_from),
                  "valid_to": utc(valid_to) if valid_to is not None else None,
                  "evidence_id": evidence_id}
        if fields["valid_to"] is not None and fields["valid_to"] <= fields["valid_from"]:
            raise ContractError("Identifier validity interval must be non-empty")
        ev = self.db.execute("SELECT * FROM evidence_versions WHERE evidence_id=?", (evidence_id,)).fetchone()
        if ev is None or ev["received_at"] > fields["known_at"]:
            raise ContractError("Identifier evidence was not known at the asserted knowledge time")
        self._require_use(ev["source_id"], Use.RESEARCH, fields["known_at"])
        with self.db:
            self._immutable("identifier_versions",
                            {"mapping_id": mapping_id, "known_at": fields["known_at"]}, fields)

    def resolve_identifier(self, provider: str, value: str, *, effective_at: datetime,
                           as_of: datetime) -> str:
        effective, at = utc(effective_at), utc(as_of)
        rows = self.db.execute(
            "SELECT v.*, e.source_id FROM identifier_versions v "
            "JOIN evidence_versions e USING(evidence_id) "
            "WHERE v.provider=? AND v.value=? AND v.known_at<=? "
            "AND v.known_at=(SELECT MAX(x.known_at) FROM identifier_versions x "
            "WHERE x.mapping_id=v.mapping_id AND x.known_at<=?) "
            "AND v.valid_from<=? AND (v.valid_to IS NULL OR v.valid_to>?)",
            (provider, value, at, at, effective, effective)).fetchall()
        for row in rows:
            self._require_use(row["source_id"], Use.RESEARCH, at)
        listings = {row["listing_id"] for row in rows}
        if not listings:
            raise UnknownIdentifier("No exact identifier match at the requested times")
        if len(listings) != 1:
            raise AmbiguousIdentifier("Multiple listings match; explicit resolution is required")
        return next(iter(listings))

    def counts(self) -> dict[str, int]:
        tables = ("sources", "entities", "instruments", "listings", "raw_objects",
                  "evidence_versions", "observations", "identifier_versions")
        return {name: self.db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in tables}
