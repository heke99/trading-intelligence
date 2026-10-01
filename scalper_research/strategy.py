"""A causal rolling quote-channel hypothesis, not a named trader's policy."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Context, Decimal, InvalidOperation, localcontext
import re

from trading_intelligence.common import DataError

_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z", re.ASCII)


def positive_decimal(value: object, field: str, *, allow_zero: bool = False) -> Decimal:
    if not isinstance(value, str) or len(value) > 80 or not _NUMBER.fullmatch(value):
        raise DataError("RESEARCH_DECIMAL_STRING_REQUIRED:" + field)
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise DataError("RESEARCH_DECIMAL_INVALID:" + field) from None
    if not number.is_finite() or number < 0 or (number == 0 and not allow_zero):
        raise DataError("RESEARCH_DECIMAL_RANGE:" + field)
    if number.adjusted() > 12 or not -12 <= number.as_tuple().exponent <= 12:
        raise DataError("RESEARCH_DECIMAL_PRECISION:" + field)
    return number


def bounded_integer(value: object, field: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise DataError("RESEARCH_INTEGER_RANGE:" + field)
    return value


@dataclass(frozen=True)
class StrategyConfig:
    lookback_quotes: int
    breakout_buffer: Decimal
    stop_distance: Decimal
    target_distance: Decimal
    max_hold_ms: int
    session_start_minute_utc: int
    session_end_minute_utc: int
    cooldown_ms: int

    @classmethod
    def from_dict(cls, values: dict) -> "StrategyConfig":
        names = set(cls.__dataclass_fields__)
        if not isinstance(values, dict) or set(values) != names:
            raise DataError("STRATEGY_CONFIG_FIELDS_INVALID")
        result = cls(
            lookback_quotes=bounded_integer(values["lookback_quotes"], "lookback_quotes", 2, 10000),
            breakout_buffer=positive_decimal(values["breakout_buffer"], "breakout_buffer", allow_zero=True),
            stop_distance=positive_decimal(values["stop_distance"], "stop_distance"),
            target_distance=positive_decimal(values["target_distance"], "target_distance"),
            max_hold_ms=bounded_integer(values["max_hold_ms"], "max_hold_ms", 1, 86400000),
            session_start_minute_utc=bounded_integer(values["session_start_minute_utc"], "session_start_minute_utc", 0, 1439),
            session_end_minute_utc=bounded_integer(values["session_end_minute_utc"], "session_end_minute_utc", 1, 1440),
            cooldown_ms=bounded_integer(values["cooldown_ms"], "cooldown_ms", 0, 86400000),
        )
        if result.session_end_minute_utc <= result.session_start_minute_utc:
            raise DataError("STRATEGY_OVERNIGHT_SESSION_UNSUPPORTED")
        return result


class RollingBreakout:
    """Observe current mid only after comparing it with the preceding N mids.

    Sessions are explicit UTC windows, not assumed London/NY local sessions.
    Cooldown starts at signal time; the execution simulator can reject a signal.
    """
    name = "rolling_quote_breakout_v1"
    attribution = "independent_research_hypothesis_not_trader_replication"

    def __init__(self, config: StrategyConfig):
        self.config = config
        self.stop_distance = config.stop_distance
        self.target_distance = config.target_distance
        self.max_hold_ms = config.max_hold_ms
        self._history = deque(maxlen=config.lookback_quotes)
        self._last_signal = None
        self._day = None

    def session_open(self, time_msc: int) -> bool:
        minute = (time_msc // 60000) % 1440
        return self.config.session_start_minute_utc <= minute < self.config.session_end_minute_utc

    def reset(self) -> None:
        self._history.clear()
        self._last_signal = None
        self._day = None

    def on_quote(self, quote, position) -> str | None:
        with localcontext(Context(prec=1024)):
            return self._on_quote(quote, position)

    def _on_quote(self, quote, position) -> str | None:
        day = quote.time_msc // 86400000
        if day != self._day:
            self.reset()
            self._day = day
        if not self.session_open(quote.time_msc):
            self._history.clear()
            return None
        mid = (quote.bid + quote.ask) / Decimal(2)
        signal = None
        cooled = self._last_signal is None or quote.time_msc - self._last_signal >= self.config.cooldown_ms
        if position is None and cooled and len(self._history) == self.config.lookback_quotes:
            if mid > max(self._history) + self.config.breakout_buffer:
                signal = "long"
            elif mid < min(self._history) - self.config.breakout_buffer:
                signal = "short"
        self._history.append(mid)
        if signal:
            self._last_signal = quote.time_msc
        return signal
