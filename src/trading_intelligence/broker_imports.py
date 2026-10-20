"""Immutable raw responses and processed availability for read-only broker imports."""

from datetime import datetime, timezone
import hashlib
import json

from .alpaca_normalizer import NORMALIZER_VERSION, normalize_bundle
from .alpaca_reader import AlpacaReferenceReader, BrokerRead
from .brokers import BrokerAccount, Environment
from .broker_store import BrokerStore, _json
from .contracts import ContractError, EvidenceIntegrityError, RecordConflict, Use, required, utc


IMPORT_SCHEMA = """
CREATE TABLE IF NOT EXISTS broker_reference_imports (
 account_key TEXT NOT NULL REFERENCES broker_accounts, import_id TEXT NOT NULL,
 source_id TEXT NOT NULL REFERENCES sources, input_json TEXT NOT NULL,
 account_sha TEXT NOT NULL REFERENCES raw_objects(sha256),
 assets_sha TEXT NOT NULL REFERENCES raw_objects(sha256),
 available_at TEXT NOT NULL, result_json TEXT NOT NULL, result_hash TEXT NOT NULL,
 PRIMARY KEY(account_key,import_id));
"""


class BrokerImportStore(BrokerStore):
    def __init__(self, database, *, clock=None):
        super().__init__(database)
        self.db.executescript(IMPORT_SCHEMA)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def sync_alpaca(self, route: BrokerAccount, *, import_id: str, source_id: str,
                    expected_native_id: str, reader: AlpacaReferenceReader) -> dict:
        """Fetch only the two paper reference endpoints into one immutable batch.

        A failed fetch commits no batch. Retrying a completed job retrieves its
        original result; use a new import ID for a new observation.
        """
        self._account(route)
        if route.broker_id != "alpaca" or route.environment != Environment.PAPER:
            raise ContractError("Only Alpaca paper reference synchronization is implemented")
        required(import_id, "import_id")
        required(expected_native_id, "expected_native_id")
        now = self._clock()
        for use in (Use.STORAGE, Use.RESEARCH):
            self.require_use(source_id, use, as_of=now)
        existing = self.db.execute("SELECT * FROM broker_reference_imports WHERE account_key=? AND import_id=?",
                                   (route.key, import_id)).fetchone()
        if existing:
            inputs = json.loads(existing["input_json"])
            if existing["source_id"] != source_id or inputs["expected_native_id"] != expected_native_id:
                raise RecordConflict("Completed import belongs to another source or expected account")
            result = self.reference_import_as_of(route, import_id, as_of=now)
            if result is None:
                raise ContractError("Completed import is not available at this clock time")
            return result
        account = reader.read("account")
        assets = reader.read("assets")
        return self.import_alpaca(route, import_id=import_id, source_id=source_id,
                                  expected_native_id=expected_native_id, account=account, assets=assets)

    def _archive(self, raw: bytes) -> str:
        digest = hashlib.sha256(raw).hexdigest()
        self.db.execute("INSERT OR IGNORE INTO raw_objects VALUES (?,?)", (digest, raw))
        saved = self.db.execute("SELECT payload FROM raw_objects WHERE sha256=?", (digest,)).fetchone()
        if saved is None or saved["payload"] != raw:
            raise EvidenceIntegrityError("Imported raw bytes failed integrity verification")
        return digest

    def import_alpaca(self, route: BrokerAccount, *, import_id: str, source_id: str,
                      expected_native_id: str, account: BrokerRead, assets: BrokerRead) -> dict:
        self._account(route)
        required(import_id, "import_id")
        required(source_id, "source_id")
        required(expected_native_id, "expected_native_id")
        if route.broker_id != "alpaca" or route.environment != Environment.PAPER:
            raise ContractError("Only Alpaca paper reference imports are implemented")
        if account.resource != "account" or assets.resource != "assets":
            raise ContractError("Expected distinct account and asset responses")
        if account.environment != route.environment or assets.environment != route.environment:
            raise ContractError("Response environment does not match the account route")
        digests = {x.resource: hashlib.sha256(x.payload).hexdigest() for x in (account, assets)}
        identity = _json(dict(route=route.key, source_id=source_id, expected_native_id=expected_native_id,
                              normalizer=NORMALIZER_VERSION, responses=[
                                  dict(resource=x.resource, sha256=digests[x.resource],
                                       received_at=utc(x.received_at), source_url=x.source_url,
                                       provider_published_at=None, provider_effective_at=None) for x in (account, assets)]))
        existing = self.db.execute("SELECT * FROM broker_reference_imports WHERE account_key=? AND import_id=?",
                                   (route.key, import_id)).fetchone()
        if existing:
            if existing["input_json"] != identity:
                raise RecordConflict("Import key already refers to different bytes, receipt or source")
            saved = self.reference_import_as_of(route, import_id, as_of=self._clock())
            if saved is None:
                raise ContractError("Completed import is not available at this clock time")
            return saved
        for receipt in (account, assets):
            self.require_use(source_id, Use.STORAGE, as_of=receipt.received_at)
        report = normalize_bundle(account.payload, assets.payload, route, expected_native_id)
        completed = utc(self._clock())
        if any(completed < utc(x.received_at) for x in (account, assets)):
            raise ContractError("Processing cannot complete before raw response receipt")
        self._require_use(source_id, Use.RESEARCH, completed)
        result = dict(account_key=route.key, import_id=import_id, source_id=source_id,
                      input_sha256=hashlib.sha256(identity.encode()).hexdigest(),
                      normalizer_version=NORMALIZER_VERSION, available_at=completed,
                      receipts=json.loads(identity)["responses"], report=report)
        encoded = _json(result)
        with self.db:
            for receipt in (account, assets):
                self._archive(receipt.payload)
            self._immutable("broker_reference_imports", {"account_key": route.key, "import_id": import_id},
                            dict(account_key=route.key, import_id=import_id, source_id=source_id,
                                 input_json=identity, account_sha=digests["account"], assets_sha=digests["assets"],
                                 available_at=completed, result_json=encoded,
                                 result_hash=hashlib.sha256(encoded.encode()).hexdigest()))
        return result

    def reference_import_as_of(self, route: BrokerAccount, import_id: str, *, as_of: datetime) -> dict | None:
        self._account(route)
        at = utc(as_of)
        row = self.db.execute("SELECT * FROM broker_reference_imports WHERE account_key=? AND import_id=?",
                              (route.key, import_id)).fetchone()
        if row is None or row["available_at"] > at:
            return None
        self._require_use(row["source_id"], Use.RESEARCH, at)
        if hashlib.sha256(row["result_json"].encode()).hexdigest() != row["result_hash"]:
            raise EvidenceIntegrityError("Normalized import failed integrity verification")
        result = json.loads(row["result_json"])
        if result.get("input_sha256") != hashlib.sha256(row["input_json"].encode()).hexdigest():
            raise EvidenceIntegrityError("Import input envelope failed integrity verification")
        if any(result.get(name) != row[name] for name in ("account_key", "import_id", "source_id", "available_at")):
            raise EvidenceIntegrityError("Import envelope does not match its account and batch")
        inputs = json.loads(row["input_json"])
        if (result["receipts"] != inputs["responses"] or result["normalizer_version"] != inputs["normalizer"]
                or inputs["route"] != route.key or inputs["source_id"] != row["source_id"]):
            raise EvidenceIntegrityError("Import input lineage does not match its result")
        for receipt in result["receipts"]:
            if receipt["sha256"] != row[receipt["resource"] + "_sha"]:
                raise EvidenceIntegrityError("Import raw reference does not match its envelope")
            raw = self.db.execute("SELECT payload FROM raw_objects WHERE sha256=?", (receipt["sha256"],)).fetchone()
            if raw is None or hashlib.sha256(raw["payload"]).hexdigest() != receipt["sha256"]:
                raise EvidenceIntegrityError("Imported raw bytes failed integrity verification")
        return result
