"""Conservative, versioned normalization; not a point-in-time feature builder."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .common import DataError, decimal_text, field, positive_id

NORMALIZER_VERSION = 1


def timestamp(raw, flags: list[str], *, naive_timezone: str | None = None,
              evidence: str | None = None, date_format: str | None = None) -> str | None:
    if not isinstance(raw, str) or len(raw) > 100 or len(raw.strip()) < 16:
        raise DataError("TIMESTAMP_MISSING_OR_INVALID")
    try:
        dt = datetime.strptime(raw, date_format) if date_format else datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise DataError("TIMESTAMP_FORMAT_INVALID") from None
    if dt.tzinfo is None:
        if naive_timezone is None:
            flags.append("TIMEZONE_UNVERIFIED")
            return None
        if not evidence or not evidence.strip():
            raise DataError("TIMEZONE_EVIDENCE_REQUIRED")
        try:
            zone = timezone.utc if naive_timezone == "UTC" else ZoneInfo(naive_timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise DataError("TIMEZONE_INVALID") from None
        candidates = set()
        for fold in (0, 1):
            candidate = dt.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
            if candidate.astimezone(zone).replace(tzinfo=None) == dt:
                candidates.add(candidate)
        if len(candidates) != 1:
            raise DataError("LOCAL_TIME_AMBIGUOUS_OR_NONEXISTENT")
        dt = candidates.pop()
    return dt.astimezone(timezone.utc).isoformat()


def normalize_record(raw: dict, kind: str, strategy_id: int, *, naive_timezone: str | None = None,
                     timezone_evidence: str | None = None, date_format: str | None = None,
                     synthetic: bool = False, posted_utc_documented: bool = True) -> dict:
    strategy_id = positive_id(strategy_id)
    if naive_timezone and not timezone_evidence:
        raise DataError("TIMEZONE_EVIDENCE_REQUIRED")
    if positive_id(field(raw, "StrategyId")) != strategy_id:
        raise DataError("STRATEGY_MISMATCH")
    if kind not in ("closed_trades", "orders"):
        raise DataError("KIND_NOT_ALLOWED")
    symbol = field(raw, "C2Symbol")
    if not isinstance(symbol, dict):
        raise DataError("SYMBOL_MISSING")
    full_symbol = field(symbol, "FullSymbol")
    if not isinstance(full_symbol, str) or not full_symbol.strip() or len(full_symbol) > 200:
        raise DataError("SYMBOL_INVALID")
    exchange = field(raw, "ExchangeSymbol") or {}
    if not isinstance(exchange, dict):
        raise DataError("EXCHANGE_SYMBOL_INVALID")
    flags: list[str] = []
    if field(symbol, "SymbolType") not in ("forex", "stock", "future", "option", "crypto"):
        flags.append("INSTRUMENT_TYPE_REQUIRES_REVIEW")
    record_id = field(raw, "TradeId") if kind == "closed_trades" else field(raw, "Id")
    if record_id is None:
        record_id = field(raw, "Id") if kind == "closed_trades" else field(raw, "SignalId")
        flags.append("FALLBACK_SOURCE_ID")
    out = {
        "normalizer_version": NORMALIZER_VERSION,
        "source": "collective2", "strategy_id": str(strategy_id), "kind": kind,
        "source_id": str(positive_id(record_id)),
        "data_origin": "synthetic_fixture" if synthetic else "c2_strategy_hypothetical",
        "symbol_raw": full_symbol, "instrument_type_raw": field(symbol, "SymbolType"),
        "instrument_currency": field(exchange, "Currency"),
        "instrument_identity_raw": {"C2Symbol": symbol, "ExchangeSymbol": exchange},
        "pnl_currency": None, "net_pnl": None,
        "naive_timezone_policy": naive_timezone, "timezone_evidence": timezone_evidence,
    }
    options = dict(naive_timezone=naive_timezone, evidence=timezone_evidence, date_format=date_format)
    if kind == "closed_trades":
        side = field(raw, "OpenSide")
        if side not in ("1", "2"):
            raise DataError("OPEN_SIDE_INVALID")
        closing_side = field(raw, "CloseSide")
        if closing_side not in (None, "", "1", "2") or closing_side == side:
            raise DataError("CLOSE_SIDE_INVALID")
        out.update(side="buy" if side == "1" else "sell",
                   usage_role="outcome_only_not_features",
                   opened_at_raw=field(raw, "OpenDate"), closed_at_raw=field(raw, "CloseDate"))
        out["opened_at_utc"] = timestamp(out["opened_at_raw"], flags, **options)
        out["closed_at_utc"] = timestamp(out["closed_at_raw"], flags, **options)
        if out["opened_at_utc"] and out["closed_at_utc"]:
            if datetime.fromisoformat(out["closed_at_utc"]) < datetime.fromisoformat(out["opened_at_utc"]):
                raise DataError("CLOSE_BEFORE_OPEN")
        out["entry_price"] = decimal_text(field(raw, "AvgOpenFillPrice"), required=True)
        out["exit_price"] = decimal_text(field(raw, "AvgCloseFillPrice"), required=True)
        out["opened_quantity"] = decimal_text(field(raw, "OpenedQuantity"), required=True, positive=True)
        out["closed_quantity"] = decimal_text(field(raw, "ClosedQuantity"), required=True, positive=True)
        if Decimal(out["opened_quantity"]) != Decimal(out["closed_quantity"]):
            flags.append("OPEN_CLOSE_QUANTITY_MISMATCH")
        out["profit_loss_reported"] = decimal_text(field(raw, "ProfitLoss"))
        out["commission_reported"] = decimal_text(field(raw, "Commission"))
        flags.extend(["AGGREGATED_ENTRY_EXIT_VWAP", "COST_SEMANTICS_UNVERIFIED", "PNL_CURRENCY_UNKNOWN"])
    else:
        side = field(raw, "Side")
        if side not in ("1", "2"):
            raise DataError("ORDER_SIDE_INVALID")
        status = field(raw, "OrderStatus")
        if status not in {"A", "0", "1", "2", "4", "5", "6", "8", "C", "E"}:
            raise DataError("ORDER_STATUS_INVALID")
        open_close = field(raw, "OpenClose")
        if open_close not in (None, "", "O", "C"):
            raise DataError("OPEN_CLOSE_INVALID")
        out.update(side="buy" if side == "1" else "sell", order_status=status,
                   open_close=open_close, signal_id=field(raw, "SignalId"),
                   usage_role="historical_snapshot_not_point_in_time_features",
                   posted_at_raw=field(raw, "PostedDate"), filled_at_utc=None)
        # C2 explicitly documents PostedDate as UTC. This is NOT the fill time.
        if posted_utc_documented:
            out["posted_at_utc"] = timestamp(out["posted_at_raw"], flags, naive_timezone="UTC",
                                             evidence="C2 OrderStatusDTO PostedDate UTC schema", date_format=date_format)
            out["posted_time_basis"] = "C2_SCHEMA_UTC_NOT_FILL_TIME"
        else:
            out["posted_at_utc"] = timestamp(out["posted_at_raw"], flags, **options)
            out["posted_time_basis"] = "CSV_EXPLICIT_POLICY_NOT_FILL_TIME"
        out["order_quantity"] = decimal_text(field(raw, "OrderQuantity"), required=True, positive=True)
        out["filled_quantity"] = decimal_text(field(raw, "FilledQuantity"), nonnegative=True)
        filled = Decimal(out["filled_quantity"]) if out["filled_quantity"] is not None else None
        if filled is not None and filled > Decimal(out["order_quantity"]):
            raise DataError("FILLED_EXCEEDS_ORDER_QUANTITY")
        out["fill_price"] = decimal_text(field(raw, "AvgFillPrice"), required=filled is not None and filled > 0)
        for src, dst in [("OrderType", "order_type"), ("TIF", "time_in_force")]:
            out[dst] = field(raw, src)
        for src, dst in [("Limit", "limit_price"), ("Stop", "stop_price"),
                         ("StopLoss", "stop_loss_reported"), ("ProfitTarget", "profit_target_reported")]:
            out[dst] = decimal_text(field(raw, src))
        flags.extend(["ORDER_SNAPSHOT_NOT_EVENT_LOG", "FILL_TIME_NOT_PROVIDED"])
    out["quality_flags"] = sorted(set(flags))
    return out
