"""Canonical offline broker contracts. No credentials, network or submit method."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
import hashlib
import re
from typing import Protocol

from .contracts import AssetKind, ContractError, currency, required, utc
from .futures import PriceKind, number
from .references import _key


class BrokerCheckFailed(ContractError):
    pass


class Environment(StrEnum):
    PAPER = "paper"
    LIVE = "live"


class TargetKind(StrEnum):
    LISTING = "listing"
    FUTURE = "future_contract"


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class TimeInForce(StrEnum):
    DAY = "day"
    GTC = "gtc"


class SessionMode(StrEnum):
    REGULAR = "regular"
    EXTENDED = "extended"


@dataclass(frozen=True)
class BrokerAccount:
    broker_id: str
    connection_id: str
    account_id: str
    environment: Environment

    def __post_init__(self):
        for name in ("broker_id", "connection_id", "account_id"):
            required(getattr(self, name), name)
        object.__setattr__(self, "environment", Environment(self.environment))

    @property
    def key(self) -> str:
        return _key(self.broker_id, self.connection_id, self.account_id, self.environment.value)


@dataclass(frozen=True)
class InstrumentTarget:
    kind: TargetKind
    internal_id: str

    def __post_init__(self):
        object.__setattr__(self, "kind", TargetKind(self.kind))
        required(self.internal_id, "internal_id")


@dataclass(frozen=True)
class NativeBinding:
    target: InstrumentTarget
    native_id: str
    symbol: str
    venue_mic: str
    currency: str
    price_tick: Decimal
    quantity_step: Decimal
    minimum_quantity: Decimal

    def __post_init__(self):
        if not isinstance(self.target, InstrumentTarget):
            raise ContractError("An explicit canonical target is required")
        required(self.native_id, "native_id")
        required(self.symbol, "symbol")
        required(self.currency, "currency")
        currency(self.currency)
        if not isinstance(self.venue_mic, str) or not re.fullmatch(r"[A-Z0-9]{4}", self.venue_mic):
            raise ContractError("An explicit venue MIC is required")
        for name in ("price_tick", "quantity_step", "minimum_quantity"):
            number(getattr(self, name), name, positive=True)
        if not on_grid(self.minimum_quantity, self.quantity_step):
            raise ContractError("Minimum quantity must be on the quantity grid")


def on_grid(value: Decimal, step: Decimal) -> bool:
    a, b = value.as_integer_ratio()
    c, d = step.as_integer_ratio()
    return (a * d) % (b * c) == 0


@dataclass(frozen=True)
class OrderRule:
    asset_kind: AssetKind
    time_in_force: TimeInForce
    session: SessionMode
    fractional_quantity: bool = False

    def __post_init__(self):
        object.__setattr__(self, "asset_kind", AssetKind(self.asset_kind))
        object.__setattr__(self, "time_in_force", TimeInForce(self.time_in_force))
        object.__setattr__(self, "session", SessionMode(self.session))
        if self.asset_kind not in {AssetKind.EQUITY, AssetKind.ETF, AssetKind.FUTURE}:
            raise ContractError("This broker draft path supports equities, ETFs and futures only")
        if type(self.fractional_quantity) is not bool:
            raise ContractError("Fractional support must be explicit")
        if self.asset_kind == AssetKind.FUTURE and self.fractional_quantity:
            raise ContractError("Futures quantities must be whole contracts")


@dataclass(frozen=True)
class BrokerCapabilities:
    rules: tuple[OrderRule, ...]
    prepare_enabled: bool = False

    def __post_init__(self):
        if type(self.prepare_enabled) is not bool or not isinstance(self.rules, tuple):
            raise ContractError("Capabilities need immutable rules and an explicit enabled flag")
        seen = set()
        for rule in self.rules:
            if not isinstance(rule, OrderRule):
                raise ContractError("Capabilities require OrderRule values")
            key = (rule.asset_kind, rule.time_in_force, rule.session)
            if key in seen:
                raise ContractError("Duplicate/contradictory order capability combination")
            seen.add(key)


@dataclass(frozen=True)
class OrderIntent:
    intent_id: str
    strategy_id: str
    target: InstrumentTarget
    side: Side
    quantity: Decimal
    limit_price: Decimal
    decision_at: datetime
    valid_until: datetime
    time_in_force: TimeInForce = TimeInForce.DAY
    session: SessionMode = SessionMode.REGULAR
    price_kind: PriceKind = PriceKind.RAW_CONTRACT

    def __post_init__(self):
        required(self.intent_id, "intent_id")
        required(self.strategy_id, "strategy_id")
        if not isinstance(self.target, InstrumentTarget):
            raise ContractError("An explicit target is required")
        object.__setattr__(self, "side", Side(self.side))
        object.__setattr__(self, "time_in_force", TimeInForce(self.time_in_force))
        object.__setattr__(self, "session", SessionMode(self.session))
        object.__setattr__(self, "price_kind", PriceKind(self.price_kind))
        number(self.quantity, "quantity", positive=True)
        number(self.limit_price, "limit_price")
        if utc(self.decision_at) >= utc(self.valid_until):
            raise ContractError("Intent needs a positive validity interval")


class BrokerAdapter(Protocol):
    account: BrokerAccount
    adapter_id: str
    version: str

    def encode_limit(self, binding: NativeBinding, intent: OrderIntent, client_id: str) -> dict: ...


@dataclass(frozen=True)
class SymbolPaperAdapter:
    """Invented symbol-based format, not an implementation of a vendor API."""
    account: BrokerAccount
    adapter_id: str = "synthetic-symbol-paper"
    version: str = "1"

    def encode_limit(self, binding, intent, client_id):
        return dict(account=self.account.account_id, symbol=binding.symbol, venue=binding.venue_mic,
                    side=intent.side.value, quantity=str(intent.quantity), limit=str(intent.limit_price),
                    order_type="limit", time_in_force=intent.time_in_force.value,
                    session=intent.session.value, client_order_id=client_id)


@dataclass(frozen=True)
class ContractPaperAdapter:
    """Invented contract-ID format; no TWS/API connection or order submission."""
    account: BrokerAccount
    adapter_id: str = "synthetic-contract-paper"
    version: str = "1"

    def encode_limit(self, binding, intent, client_id):
        return dict(account=self.account.account_id, contract_id=binding.native_id,
                    exchange=binding.venue_mic, action=intent.side.value.upper(),
                    units=str(intent.quantity), limit_price=str(intent.limit_price),
                    order_type="LIMIT", duration=intent.time_in_force.value.upper(),
                    session=intent.session.value, reference=client_id)


class AdapterRegistry:
    def __init__(self):
        self._adapters: dict[str, BrokerAdapter] = {}

    def register(self, adapter: BrokerAdapter):
        required(adapter.adapter_id, "adapter_id")
        required(adapter.version, "adapter version")
        if adapter.account.environment != Environment.PAPER:
            raise BrokerCheckFailed("Only offline paper adapters can be registered in this build")
        if adapter.account.key in self._adapters:
            raise BrokerCheckFailed("Account already has an adapter; no implicit replacement")
        self._adapters[adapter.account.key] = adapter

    def get(self, account: BrokerAccount) -> BrokerAdapter:
        adapter = self._adapters.get(account.key)
        if adapter is None or adapter.account != account:
            raise BrokerCheckFailed("No adapter for this exact broker/connection/account/environment")
        return adapter


@dataclass(frozen=True)
class PreparedDraft:
    draft_id: str
    account_key: str
    intent_id: str
    adapter_id: str
    adapter_version: str
    client_order_id: str
    prepared_at: str
    intent_hash: str
    payload: dict
    snapshot_ids: tuple[str, ...]
    replayed: bool
    state: str = "prepared_offline"


def client_order_id(account_key: str, intent_id: str) -> str:
    return hashlib.sha256(_key(account_key, intent_id).encode()).hexdigest()[:32]
