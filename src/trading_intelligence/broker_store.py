"""Persistent, account-scoped offline drafts. Not a broker/risk/order gateway."""

from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
import hashlib
import json

from .brokers import (
    AdapterRegistry, BrokerAccount, BrokerCapabilities, BrokerCheckFailed, Environment,
    InstrumentTarget, NativeBinding, OrderIntent, OrderRule, PreparedDraft, TargetKind,
    client_order_id, on_grid,
)
from .contracts import AssetKind, ContractError, EvidenceIntegrityError, RecordConflict, utc
from .futures import Settlement, PriceKind, contracts
from .futures_store import FuturesStore
from .references import ReferenceRepository, _encode, _key


BROKER_SCHEMA = """
CREATE TABLE IF NOT EXISTS broker_accounts (
 account_key TEXT PRIMARY KEY, broker_id TEXT NOT NULL, connection_id TEXT NOT NULL,
 account_id TEXT NOT NULL, environment TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS broker_snapshots (
 snapshot_id TEXT PRIMARY KEY, kind TEXT NOT NULL, target_id TEXT NOT NULL,
 valid_from TEXT NOT NULL, valid_to TEXT NOT NULL, known_at TEXT NOT NULL,
 evidence_id TEXT NOT NULL REFERENCES evidence_versions, body TEXT NOT NULL,
 UNIQUE(kind,target_id,valid_from,known_at));
CREATE INDEX IF NOT EXISTS broker_snapshot_lookup ON broker_snapshots(kind,target_id,valid_from,known_at);
CREATE TABLE IF NOT EXISTS broker_drafts (
 account_key TEXT NOT NULL REFERENCES broker_accounts, intent_id TEXT NOT NULL,
 intent_json TEXT NOT NULL, draft_json TEXT NOT NULL, draft_hash TEXT NOT NULL,
 PRIMARY KEY(account_key,intent_id));
"""


def _json(value) -> str:
    return json.dumps(value, default=_encode, sort_keys=True, separators=(",", ":"), allow_nan=False)


class BrokerStore(FuturesStore):
    def __init__(self, database):
        super().__init__(database)
        self.db.executescript(BROKER_SCHEMA)
        self._broker_references = ReferenceRepository(self, "broker_snapshots")

    def register_account(self, account: BrokerAccount):
        with self.db:
            self._immutable("broker_accounts", {"account_key": account.key},
                            {"account_key": account.key, **asdict(account)})

    def _account(self, account: BrokerAccount):
        row = self.db.execute("SELECT * FROM broker_accounts WHERE account_key=?", (account.key,)).fetchone()
        if row is None or dict(row) != {"account_key": account.key, **asdict(account)}:
            raise BrokerCheckFailed("Account was not registered with this exact route")

    def _target(self, target: InstrumentTarget) -> tuple[AssetKind, str, str]:
        if target.kind == TargetKind.FUTURE:
            row = self.db.execute(
                "SELECT p.quote_currency, p.venue_mic FROM future_contracts c "
                "JOIN future_products p USING(product_id) WHERE c.contract_id=?", (target.internal_id,)).fetchone()
            kind = AssetKind.FUTURE
        else:
            row = self.db.execute(
                "SELECT i.kind, l.trading_currency AS quote_currency, l.mic AS venue_mic "
                "FROM listings l JOIN instruments i USING(instrument_id) WHERE listing_id=?", (target.internal_id,)).fetchone()
            kind = AssetKind(row["kind"]) if row else None
        if row is None:
            raise BrokerCheckFailed("Unknown canonical listing or explicit futures expiry")
        return kind, row["quote_currency"], row["venue_mic"]

    def put_capabilities(self, account: BrokerAccount, capabilities: BrokerCapabilities, **times):
        self._account(account)
        return self._broker_references.put("capabilities", account.key, asdict(capabilities), **times)

    def put_binding(self, account: BrokerAccount, binding: NativeBinding, **times):
        self._account(account)
        kind, currency, venue = self._target(binding.target)
        if binding.currency != currency or binding.venue_mic != venue:
            raise BrokerCheckFailed("Broker mapping cannot substitute a different currency or venue")
        if kind == AssetKind.FUTURE and any(
                value != value.to_integral_value() for value in (binding.quantity_step, binding.minimum_quantity)):
            raise BrokerCheckFailed("Futures bindings cannot declare fractional lots")
        return self._broker_references.put("instrument", _key(account.key, binding.target.kind.value,
                                                              binding.target.internal_id), asdict(binding), **times)

    def _saved(self, row, intent_json: str) -> PreparedDraft:
        if row["intent_json"] != intent_json:
            raise RecordConflict("This account/intent key already has different canonical inputs")
        if hashlib.sha256(row["draft_json"].encode()).hexdigest() != row["draft_hash"]:
            raise EvidenceIntegrityError("Prepared broker draft failed integrity verification")
        body = json.loads(row["draft_json"])
        expected = dict(account_key=row["account_key"], intent_id=row["intent_id"],
                        intent_hash=hashlib.sha256(intent_json.encode()).hexdigest(),
                        client_order_id=client_order_id(row["account_key"], row["intent_id"]),
                        draft_id=hashlib.sha256(_key(row["account_key"], row["intent_id"]).encode()).hexdigest())
        if any(body.get(name) != value for name, value in expected.items()):
            raise EvidenceIntegrityError("Saved draft envelope does not belong to this account/intent")
        body["snapshot_ids"] = tuple(body["snapshot_ids"])
        return PreparedDraft(**body, replayed=True)

    def _check_native_identity(self, account, binding, at, when):
        # Small offline catalogue: fail closed if two canonical targets could
        # become the same native contract or symbol/venue/currency request.
        rows = self.db.execute(
            "SELECT DISTINCT v.target_id FROM broker_snapshots v WHERE kind='instrument' AND known_at<=? "
            "AND known_at=(SELECT MAX(x.known_at) FROM broker_snapshots x "
            "WHERE x.kind=v.kind AND x.target_id=v.target_id AND x.valid_from=v.valid_from AND x.known_at<=?) "
            "AND valid_from<=? AND valid_to>?", (at, at, at, at)).fetchall()
        own_key = _key(account.key, binding.target.kind.value, binding.target.internal_id)
        for row in rows:
            if row["target_id"] == own_key or json.loads(row["target_id"])[0] != account.key:
                continue
            other = self._broker_references.get("instrument", row["target_id"], **when).body
            if (other["native_id"] == binding.native_id or
                    (other["symbol"], other["venue_mic"], other["currency"]) ==
                    (binding.symbol, binding.venue_mic, binding.currency)):
                raise BrokerCheckFailed("Ambiguous native identity across canonical instruments")

    def prepare(self, account: BrokerAccount, intent: OrderIntent, *, prepared_at: datetime,
                adapters: AdapterRegistry) -> PreparedDraft:
        """Persist a serialization draft only. No order ID allocation at a broker.

        Retries return the saved draft before revalidation: this is audit retrieval,
        not permission to send it now. Live transports and risk gates do not exist.
        """
        self._account(account)
        if account.environment != Environment.PAPER:
            raise BrokerCheckFailed("Live preparation is disabled in this offline build")
        encoded_intent = _json(asdict(intent))
        old = self.db.execute("SELECT * FROM broker_drafts WHERE account_key=? AND intent_id=?",
                              (account.key, intent.intent_id)).fetchone()
        if old:
            return self._saved(old, encoded_intent)
        at = utc(prepared_at)
        if not utc(intent.decision_at) <= at < utc(intent.valid_until):
            raise BrokerCheckFailed("Intent is not yet known or is expired")
        if intent.price_kind != PriceKind.RAW_CONTRACT:
            raise BrokerCheckFailed("Adjusted series cannot supply a broker draft price")
        adapter = adapters.get(account)
        when = dict(effective_at=prepared_at, as_of=prepared_at)
        caps_ref = self._broker_references.get("capabilities", account.key, **when)
        caps = BrokerCapabilities(tuple(OrderRule(**rule) for rule in caps_ref.body["rules"]),
                                   caps_ref.body["prepare_enabled"])
        if not caps.prepare_enabled:
            raise BrokerCheckFailed("Account capability snapshot disables preparation")
        kind, _, _ = self._target(intent.target)
        rule = next((x for x in caps.rules if x.asset_kind == kind and x.time_in_force == intent.time_in_force
                     and x.session == intent.session), None)
        if rule is None:
            raise BrokerCheckFailed("Unsupported asset/limit-order/TIF/session combination")
        binding_ref = self._broker_references.get("instrument", _key(account.key, intent.target.kind.value,
                                                                      intent.target.internal_id), **when)
        body = binding_ref.body
        binding = NativeBinding(InstrumentTarget(**body["target"]), body["native_id"], body["symbol"],
                                body["venue_mic"], body["currency"], Decimal(body["price_tick"]),
                                Decimal(body["quantity_step"]), Decimal(body["minimum_quantity"]))
        self._check_native_identity(account, binding, at, when)
        if (intent.quantity < binding.minimum_quantity or not on_grid(intent.quantity, binding.quantity_step)
                or (not rule.fractional_quantity and intent.quantity != intent.quantity.to_integral_value())):
            raise BrokerCheckFailed("Quantity violates broker lot/fractional capability")
        if not on_grid(intent.limit_price, binding.price_tick):
            raise BrokerCheckFailed("Price violates broker tick grid; no silent rounding")
        snapshots = [caps_ref.snapshot_id, binding_ref.snapshot_id]
        if kind == AssetKind.FUTURE:
            contracts(int(intent.quantity))
            if intent.quantity != intent.quantity.to_integral_value():
                raise BrokerCheckFailed("Futures require whole contracts")
            terms, terms_id = self.terms_as_of(intent.target.internal_id, **when)
            terms.check_price(intent.limit_price)
            if terms.settlement != Settlement.CASH or at >= utc(terms.entry_cutoff_at) or at >= utc(terms.last_trade_at):
                raise BrokerCheckFailed("Futures settlement/entry boundary is outside the draft pilot")
            snapshots.append(terms_id)
        elif intent.limit_price <= 0:
            raise BrokerCheckFailed("Cash-security limit price must be positive")
        client_id = client_order_id(account.key, intent.intent_id)
        body = dict(draft_id=hashlib.sha256(_key(account.key, intent.intent_id).encode()).hexdigest(),
                    account_key=account.key, intent_id=intent.intent_id, adapter_id=adapter.adapter_id,
                    adapter_version=adapter.version, client_order_id=client_id,
                    prepared_at=at, intent_hash=hashlib.sha256(encoded_intent.encode()).hexdigest(),
                    payload=adapter.encode_limit(binding, intent, client_id), snapshot_ids=tuple(snapshots),
                    state="prepared_offline")
        encoded_draft = _json(body)
        with self.db:
            self._immutable("broker_drafts", {"account_key": account.key, "intent_id": intent.intent_id},
                            dict(account_key=account.key, intent_id=intent.intent_id, intent_json=encoded_intent,
                                 draft_json=encoded_draft, draft_hash=hashlib.sha256(encoded_draft.encode()).hexdigest()))
        return PreparedDraft(**body, replayed=False)
