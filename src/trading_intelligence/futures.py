"""Linear, fixed-tick futures contracts and offline calculations. No orders are sent."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, localcontext
from enum import StrEnum
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .contracts import AssetKind, ContractError, currency, required, utc


class FuturesUnavailable(ContractError):
    """Missing or ambiguous reference data: no guessed fallback."""


class FuturesCheckFailed(ContractError):
    """An offline opening-intent check failed. This is not an execution API."""


class Settlement(StrEnum):
    CASH = "cash"
    PHYSICAL = "physical"


class PriceKind(StrEnum):
    RAW_CONTRACT = "raw_contract"
    ADJUSTED_SERIES = "adjusted_series"


def number(value: Decimal, name: str, *, positive: bool = False) -> Decimal:
    # Reject float conversion, non-finite inputs and values beyond the bounded
    # precision used below. Monetary serialization always uses strings.
    if (not isinstance(value, Decimal) or not value.is_finite()
            or len(value.as_tuple().digits) > 24 or abs(value.as_tuple().exponent) > 18):
        raise ContractError(f"{name} must be a finite bounded Decimal, never a float")
    if positive and value <= 0:
        raise ContractError(f"{name} must be positive")
    return value


def contracts(value: int, *, signed: bool = True) -> int:
    if type(value) is not int or value == 0 or abs(value) > 2_147_483_647 or (not signed and value < 0):
        raise ContractError("A nonzero whole contract quantity within the supported range is required")
    return value


@dataclass(frozen=True)
class FutureProduct:
    product_id: str
    root: str
    venue_mic: str
    underlying_instrument_id: str
    quote_currency: str
    price_unit: str

    def __post_init__(self):
        for name in ("product_id", "root", "underlying_instrument_id", "quote_currency", "price_unit"):
            required(getattr(self, name), name)
        if not isinstance(self.venue_mic, str) or not re.fullmatch(r"[A-Z0-9]{4}", self.venue_mic):
            raise ContractError("An explicit venue MIC is required")
        currency(self.quote_currency)


@dataclass(frozen=True)
class FutureContract:
    contract_id: str
    product_id: str
    contract_month: str

    def __post_init__(self):
        required(self.contract_id, "contract_id")
        required(self.product_id, "product_id")
        try:
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", self.contract_month):
                raise ValueError
            date.fromisoformat(self.contract_month + "-01")
        except (TypeError, ValueError):
            raise ContractError("Contract month must be YYYY-MM") from None

    @property
    def kind(self) -> AssetKind:
        return AssetKind.FUTURE


@dataclass(frozen=True)
class FutureTerms:
    tick_size: Decimal
    multiplier: Decimal
    settlement: Settlement
    last_trade_at: datetime
    entry_cutoff_at: datetime
    first_notice_at: datetime | None = None
    allows_negative_prices: bool = False

    def __post_init__(self):
        number(self.tick_size, "tick_size", positive=True)
        number(self.multiplier, "multiplier", positive=True)
        object.__setattr__(self, "settlement", Settlement(self.settlement))
        if utc(self.entry_cutoff_at) > utc(self.last_trade_at):
            raise ContractError("Entry cutoff cannot be later than last trading time")
        if self.first_notice_at is not None:
            if utc(self.entry_cutoff_at) >= utc(self.first_notice_at):
                raise ContractError("Entry cutoff must precede first notice")
        if self.settlement == Settlement.PHYSICAL and self.first_notice_at is None:
            raise ContractError("Physical contracts need an explicit delivery-risk notice boundary")
        if type(self.allows_negative_prices) is not bool:
            raise ContractError("Negative-price support must be explicit")

    @property
    def tick_value(self) -> Decimal:
        with localcontext() as context:
            context.prec = 128
            return self.tick_size * self.multiplier

    def check_price(self, price: Decimal):
        number(price, "price")
        if price < 0 and not self.allows_negative_prices:
            raise FuturesCheckFailed("Negative price is not supported by these terms")
        # Integer ratios avoid rounding a near-grid price into a valid tick.
        numerator, denominator = price.as_integer_ratio()
        tick_numerator, tick_denominator = self.tick_size.as_integer_ratio()
        if (numerator * tick_denominator) % (denominator * tick_numerator):
            raise FuturesCheckFailed("Price is off the contract tick grid")

    def gross_pnl(self, entry: Decimal, exit: Decimal, signed_quantity: int) -> Decimal:
        self.check_price(entry)
        self.check_price(exit)
        contracts(signed_quantity)
        with localcontext() as context:
            context.prec = 128
            return (exit - entry) * self.multiplier * signed_quantity


@dataclass(frozen=True)
class Session:
    opens_at: datetime
    closes_at: datetime

    def __post_init__(self):
        if utc(self.opens_at) >= utc(self.closes_at):
            raise ContractError("Session must have a positive duration")


@dataclass(frozen=True)
class TradingSchedule:
    timezone: str
    sessions: tuple[Session, ...]

    def __post_init__(self):
        required(self.timezone, "timezone")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            raise ContractError("An installed IANA timezone is required") from None
        if not isinstance(self.sessions, tuple) or any(not isinstance(x, Session) for x in self.sessions):
            raise ContractError("Sessions must be an immutable tuple of Session values")
        previous = None
        for item in self.sessions:
            if previous is not None and utc(item.opens_at) < previous:
                raise ContractError("Sessions must be ordered without overlaps")
            previous = utc(item.closes_at)

    def is_open(self, at: datetime) -> bool:
        instant = utc(at)
        return any(utc(x.opens_at) <= instant < utc(x.closes_at) for x in self.sessions)


@dataclass(frozen=True)
class FuturesMargin:
    initial: Decimal
    maintenance: Decimal
    currency: str

    def __post_init__(self):
        number(self.initial, "initial", positive=True)
        number(self.maintenance, "maintenance", positive=True)
        if self.initial < self.maintenance:
            raise ContractError("Use full initial/maintenance requirements, not a discounted intraday estimate")
        required(self.currency, "currency")
        currency(self.currency)


@dataclass(frozen=True)
class CollateralSnapshot:
    broker: str
    account_id: str
    available: Decimal
    currency: str
    observed_at: datetime
    expires_at: datetime

    def __post_init__(self):
        required(self.broker, "broker")
        required(self.account_id, "account_id")
        number(self.available, "available")
        required(self.currency, "currency")
        currency(self.currency)
        if utc(self.observed_at) >= utc(self.expires_at):
            raise ContractError("Collateral observation needs a bounded freshness interval")


@dataclass(frozen=True)
class FuturesResearchLimits:
    max_contracts_per_intent: int
    max_abs_notional_per_intent: Decimal
    margin_buffer: Decimal = Decimal("1")
    allow_short: bool = False

    def __post_init__(self):
        contracts(self.max_contracts_per_intent, signed=False)
        number(self.max_abs_notional_per_intent, "max_abs_notional_per_intent", positive=True)
        number(self.margin_buffer, "margin_buffer", positive=True)
        if self.margin_buffer < 1 or type(self.allow_short) is not bool:
            raise ContractError("Margin buffer cannot reduce requirements; short permission is explicit")


@dataclass(frozen=True)
class FuturesPreview:
    contract_id: str
    broker_contract_id: str
    quantity: int
    currency: str
    price: Decimal
    tick_value: Decimal
    abs_notional: Decimal
    initial_margin_required: Decimal
    maintenance_margin_required: Decimal
    snapshot_ids: tuple[str, ...]
    live_trading: bool = False
