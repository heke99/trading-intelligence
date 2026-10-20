"""Canonical identities. Identifiers are asserted explicitly, never guessed."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import re


class ContractError(ValueError):
    pass


class RecordConflict(ContractError):
    pass


class UnknownIdentifier(ContractError):
    pass


class AmbiguousIdentifier(ContractError):
    pass


class UseNotAllowed(ContractError):
    pass


class EvidenceIntegrityError(ContractError):
    pass


class AssetKind(StrEnum):
    EQUITY = "equity"
    ETF = "etf"
    MUTUAL_FUND = "mutual_fund"
    INDEX = "index"
    FUTURE = "future"


class DataOrigin(StrEnum):
    SYNTHETIC = "synthetic_fixture"
    PROVIDER = "provider_reported"
    BROKER = "verified_broker_fills"
    HYPOTHETICAL = "hypothetical_strategy"
    PAPER = "paper_fills"


class Use(StrEnum):
    STORAGE = "storage"
    RESEARCH = "research"
    TRAINING = "training"


def required(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ContractError(f"{name} must be a non-empty string without surrounding whitespace")
    return value


def utc(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError("An explicit timezone-aware datetime is required")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def currency(value: str | None) -> None:
    if value is not None and not re.fullmatch(r"[A-Z]{3}", value):
        raise ContractError("Currency must be an uppercase three-letter code")


@dataclass(frozen=True)
class Entity:
    entity_id: str
    name: str

    def __post_init__(self):
        required(self.entity_id, "entity_id")
        required(self.name, "name")


@dataclass(frozen=True)
class Instrument:
    instrument_id: str
    entity_id: str
    kind: AssetKind
    share_class: str | None = None
    base_currency: str | None = None

    def __post_init__(self):
        required(self.instrument_id, "instrument_id")
        required(self.entity_id, "entity_id")
        object.__setattr__(self, "kind", AssetKind(self.kind))
        if self.kind == AssetKind.FUTURE:
            raise ContractError("Futures use FutureProduct and FutureContract, not an issuer/share-class identity")
        if self.share_class is not None:
            required(self.share_class, "share_class")
        currency(self.base_currency)

    @property
    def execution_model(self) -> str:
        if self.kind == AssetKind.MUTUAL_FUND:
            return "nav_subscription_redemption"
        if self.kind == AssetKind.INDEX:
            return "reference_only"
        return "exchange_orderbook"


@dataclass(frozen=True)
class Listing:
    listing_id: str
    instrument_id: str
    mic: str
    trading_currency: str

    def __post_init__(self):
        required(self.listing_id, "listing_id")
        required(self.instrument_id, "instrument_id")
        if not re.fullmatch(r"[A-Z0-9]{4}", self.mic):
            raise ContractError("MIC must be an explicit four-character venue code")
        required(self.trading_currency, "trading_currency")
        currency(self.trading_currency)
