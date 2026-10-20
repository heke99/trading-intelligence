"""Shared evidence-backed, bitemporal reference storage for offline modules."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import hashlib
import json

from .contracts import ContractError, EvidenceIntegrityError, Use, required, utc


class ReferenceUnavailable(ContractError):
    pass


def _encode(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return utc(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _key(*parts: str) -> str:
    for part in parts:
        required(part, "namespace component")
    return json.dumps(parts, separators=(",", ":"))


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True)
class ReferenceSnapshot:
    snapshot_id: str
    body: dict


class ReferenceRepository:
    def __init__(self, store, table: str):
        if table not in {"futures_snapshots", "broker_snapshots"}:
            raise ContractError("Reference table must be an internal constant")
        self.store = store
        self.table = table

    def evidence(self, evidence_id: str, at: str):
        row = self.store.db.execute(
            "SELECT e.*, r.payload FROM evidence_versions e JOIN raw_objects r USING(sha256) "
            "WHERE evidence_id=? AND received_at<=?", (evidence_id, at)).fetchone()
        if row is None:
            raise ReferenceUnavailable("Backing evidence was not available by the knowledge cutoff")
        self.store._require_use(row["source_id"], Use.RESEARCH, at)
        if hashlib.sha256(row["payload"]).hexdigest() != row["sha256"]:
            raise EvidenceIntegrityError("Backing reference evidence failed integrity verification")

    def put(self, kind: str, target_id: str, body: dict, *, valid_from: datetime,
             valid_to: datetime, known_at: datetime, evidence_id: str) -> str:
        start, end, known = utc(valid_from), utc(valid_to), utc(known_at)
        if start >= end:
            raise ContractError("Reference snapshots need a non-empty bounded validity interval")
        self.evidence(evidence_id, known)
        fields = dict(kind=kind, target_id=target_id, valid_from=start, valid_to=end,
                      known_at=known, evidence_id=evidence_id,
                      body=json.dumps(body, default=_encode, sort_keys=True, separators=(",", ":")))
        identity = json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()
        fields = {"snapshot_id": hashlib.sha256(identity).hexdigest(), **fields}
        key = {name: fields[name] for name in ("kind", "target_id", "valid_from", "known_at")}
        with self.store.db:
            self.store._immutable(self.table, key, fields)
        return fields["snapshot_id"]

    def get(self, kind: str, target_id: str, *, effective_at: datetime, as_of: datetime) -> ReferenceSnapshot:
        effective, known = utc(effective_at), utc(as_of)
        rows = self.store.db.execute(
            f"SELECT v.* FROM {self.table} v WHERE kind=? AND target_id=? AND known_at<=? "
            f"AND v.known_at=(SELECT MAX(x.known_at) FROM {self.table} x "
            "WHERE x.kind=v.kind AND x.target_id=v.target_id AND x.valid_from=v.valid_from AND x.known_at<=?) "
            "AND v.valid_from<=? AND v.valid_to>?",
            (kind, target_id, known, known, effective, effective)).fetchall()
        if len(rows) != 1:
            raise ReferenceUnavailable(f"Missing, expired or ambiguous {kind} snapshot")
        row = rows[0]
        self.evidence(row["evidence_id"], known)
        fields = {name: row[name] for name in ("kind", "target_id", "valid_from", "valid_to", "known_at", "evidence_id", "body")}
        if hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()).hexdigest() != row["snapshot_id"]:
            raise EvidenceIntegrityError("Reference snapshot failed integrity verification")
        return ReferenceSnapshot(row["snapshot_id"], json.loads(row["body"]))

