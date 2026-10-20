"""Additive offline futures store. Reference checks never authorize live orders."""

from dataclasses import asdict
from datetime import datetime
from decimal import Decimal, localcontext

from .contracts import ContractError, required, utc
from .futures import (
    CollateralSnapshot, FutureContract, FutureProduct, FutureTerms, FuturesCheckFailed,
    FuturesMargin, FuturesPreview, FuturesResearchLimits, FuturesUnavailable,
    PriceKind, Session, Settlement, TradingSchedule, contracts,
)
from .store import EvidenceStore
from .references import ReferenceRepository, ReferenceUnavailable, _key, _time


FUTURES_SCHEMA = """
CREATE TABLE IF NOT EXISTS future_products (
 product_id TEXT PRIMARY KEY, root TEXT NOT NULL, venue_mic TEXT NOT NULL,
 underlying_instrument_id TEXT NOT NULL REFERENCES instruments,
 quote_currency TEXT NOT NULL, price_unit TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS future_contracts (
 contract_id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES future_products,
 contract_month TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS futures_snapshots (
 snapshot_id TEXT PRIMARY KEY, kind TEXT NOT NULL, target_id TEXT NOT NULL,
 valid_from TEXT NOT NULL, valid_to TEXT NOT NULL, known_at TEXT NOT NULL,
 evidence_id TEXT NOT NULL REFERENCES evidence_versions, body TEXT NOT NULL,
 UNIQUE(kind,target_id,valid_from,known_at));
CREATE INDEX IF NOT EXISTS futures_snapshot_lookup
 ON futures_snapshots(kind,target_id,valid_from,known_at);
"""


class FuturesStore(EvidenceStore):
    def __init__(self, database):
        super().__init__(database)
        self.db.executescript(FUTURES_SCHEMA)
        self._references = ReferenceRepository(self, "futures_snapshots")

    def register_product(self, product: FutureProduct):
        with self.db:
            self._immutable("future_products", {"product_id": product.product_id}, asdict(product))

    def register_contract(self, contract: FutureContract):
        # Products, continuous series and expiring contracts are different keys.
        with self.db:
            self._immutable("future_contracts", {"contract_id": contract.contract_id}, asdict(contract))

    def _contract(self, contract_id: str):
        row = self.db.execute(
            "SELECT c.*, p.quote_currency FROM future_contracts c "
            "JOIN future_products p USING(product_id) WHERE c.contract_id=?", (contract_id,)).fetchone()
        if row is None:
            raise FuturesUnavailable("An explicit registered expiry contract is required")
        return row

    def _put(self, kind, target_id, body, **times):
        try:
            return self._references.put(kind, target_id, body, **times)
        except ReferenceUnavailable as error:
            raise FuturesUnavailable(str(error)) from error

    def _get(self, kind, target_id, **times):
        try:
            return self._references.get(kind, target_id, **times)
        except ReferenceUnavailable as error:
            raise FuturesUnavailable(str(error)) from error

    def put_terms(self, contract_id: str, terms: FutureTerms, **times) -> str:
        self._contract(contract_id)
        return self._put("terms", contract_id, asdict(terms), **times)

    def put_schedule(self, product_id: str, schedule: TradingSchedule, **times) -> str:
        if self.db.execute("SELECT 1 FROM future_products WHERE product_id=?", (product_id,)).fetchone() is None:
            raise FuturesUnavailable("Unknown futures product")
        start, end = utc(times["valid_from"]), utc(times["valid_to"])
        if any(utc(x.opens_at) < start or utc(x.closes_at) > end for x in schedule.sessions):
            raise ContractError("Sessions must lie within the snapshot coverage interval")
        return self._put("schedule", product_id, asdict(schedule), **times)

    def put_margin(self, broker: str, account_id: str, contract_id: str,
                   margin: FuturesMargin, **times) -> str:
        row = self._contract(contract_id)
        if margin.currency != row["quote_currency"]:
            raise ContractError("Margin currency conversion is not implemented")
        return self._put("margin", _key(broker, account_id, contract_id), asdict(margin), **times)

    def put_broker_binding(self, broker: str, identifier: str, contract_id: str,
                           broker_contract_id: str, **times) -> str:
        self._contract(contract_id)
        required(broker_contract_id, "broker_contract_id")
        return self._put("binding", _key(broker, identifier),
                         dict(contract_id=contract_id, broker_contract_id=broker_contract_id), **times)

    def terms_as_of(self, contract_id: str, *, effective_at: datetime, as_of: datetime) -> tuple[FutureTerms, str]:
        self._contract(contract_id)
        record = self._get("terms", contract_id, effective_at=effective_at, as_of=as_of)
        body = record.body
        result = FutureTerms(Decimal(body["tick_size"]), Decimal(body["multiplier"]),
                             Settlement(body["settlement"]), _time(body["last_trade_at"]),
                             _time(body["entry_cutoff_at"]),
                             _time(body["first_notice_at"]) if body["first_notice_at"] is not None else None,
                             body["allows_negative_prices"])
        return result, record.snapshot_id

    def preview_opening_intent(self, *, broker: str, account_id: str, identifier: str,
                               decision_at: datetime, quantity: int, price: Decimal,
                               price_kind: PriceKind, collateral: CollateralSnapshot,
                               limits: FuturesResearchLimits) -> FuturesPreview:
        """Offline single-intent scenario. No reservations, fills or broker access.

        This does not validate account eligibility, aggregate positions or pending
        orders. A successful preview is never live-order authorization.
        """
        at = utc(decision_at)
        contracts(quantity)
        if PriceKind(price_kind) != PriceKind.RAW_CONTRACT:
            raise FuturesCheckFailed("Adjusted/continuous-series prices cannot be execution prices")
        if collateral.broker != broker or collateral.account_id != account_id:
            raise FuturesCheckFailed("Collateral observation belongs to another account")
        if not utc(collateral.observed_at) <= at < utc(collateral.expires_at):
            raise FuturesCheckFailed("Collateral observation is stale or from the future")
        when = dict(effective_at=decision_at, as_of=decision_at)
        binding = self._get("binding", _key(broker, identifier), **when)
        contract_id = binding.body["contract_id"]
        contract = self._contract(contract_id)
        terms, terms_id = self.terms_as_of(contract_id, **when)
        if at >= utc(terms.entry_cutoff_at) or at >= utc(terms.last_trade_at):
            raise FuturesCheckFailed("Contract is expired or past the configured entry cutoff")
        if terms.settlement == Settlement.PHYSICAL:
            raise FuturesCheckFailed("Physical delivery is excluded from the first opening-intent pilot")
        terms.check_price(price)
        calendar = self._get("schedule", contract["product_id"], **when)
        schedule = TradingSchedule(calendar.body["timezone"], tuple(
            Session(_time(x["opens_at"]), _time(x["closes_at"])) for x in calendar.body["sessions"]))
        if not schedule.is_open(decision_at):
            raise FuturesCheckFailed("Session is closed or in a maintenance break")
        margin_ref = self._get("margin", _key(broker, account_id, contract_id), **when)
        margin = FuturesMargin(Decimal(margin_ref.body["initial"]),
                               Decimal(margin_ref.body["maintenance"]), margin_ref.body["currency"])
        if collateral.currency != contract["quote_currency"] or margin.currency != collateral.currency:
            raise FuturesCheckFailed("Cross-currency collateral requires a verified FX model")
        if abs(quantity) > limits.max_contracts_per_intent or (quantity < 0 and not limits.allow_short):
            raise FuturesCheckFailed("Quantity or direction exceeds the research intent limits")
        with localcontext() as context:
            context.prec = 128
            notional = abs(price * terms.multiplier * quantity)
            initial = margin.initial * abs(quantity) * limits.margin_buffer
            maintenance = margin.maintenance * abs(quantity)
        if notional > limits.max_abs_notional_per_intent or initial > collateral.available:
            raise FuturesCheckFailed("Notional limit or available collateral is insufficient")
        return FuturesPreview(contract_id, binding.body["broker_contract_id"], quantity,
                              contract["quote_currency"], price, terms.tick_value, notional,
                              initial, maintenance, (binding.snapshot_id, terms_id,
                                                     calendar.snapshot_id, margin_ref.snapshot_id))
