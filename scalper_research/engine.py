"""Offline, delayed bid/ask replay. Every fill is a simulation assumption.

No broker interface, order submission, training, capital balance, or foreign
exchange conversion is part of this engine. A loss limit controls subsequent
decisions; quote gaps and execution delay can make the eventual loss larger.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Context, Decimal, localcontext
from typing import Any


def _decimal(name: str, value: Any, *, positive: bool = False) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{name} must be a finite Decimal")
    if len(value.as_tuple().digits) > 100 or abs(value.adjusted()) > 100:
        raise ValueError(f"{name} exceeds the bounded decimal precision or magnitude")
    if value < 0 or (positive and value == 0):
        raise ValueError(f"{name} must be {'positive' if positive else 'nonnegative'}")
    return value


def _integer(name: str, value: Any, *, positive: bool = False) -> int:
    if type(value) is not int or value < 0 or (positive and value == 0):
        raise ValueError(f"{name} must be a {'positive' if positive else 'nonnegative'} integer")
    return value


def _serializable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serializable(item) for item in value]
    return value


@dataclass(frozen=True)
class EngineConfig:
    symbol: str
    quantity: Decimal
    contract_multiplier: Decimal
    price_currency: str
    commission_per_unit_per_side: Decimal
    slippage_price: Decimal
    latency_ms: int
    max_quote_gap_ms: int
    max_entry_spread: Decimal
    max_loss_currency: Decimal
    max_trades: int

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol must be explicit")
        if not isinstance(self.price_currency, str) or not self.price_currency.strip():
            raise ValueError("price_currency must be explicit")
        for name in ("quantity", "contract_multiplier", "max_loss_currency"):
            _decimal(name, getattr(self, name), positive=True)
        for name in ("commission_per_unit_per_side", "slippage_price", "max_entry_spread"):
            _decimal(name, getattr(self, name))
        for name in ("latency_ms", "max_quote_gap_ms", "max_trades"):
            _integer(name, getattr(self, name), positive=True)


def replay(quotes: list[Any], strategy: Any, config: EngineConfig, *,
           finalize: bool = True,
           entry_halt_from_time_msc: int | None = None) -> dict[str, Any]:
    """Return auditable hypothetical fills and marked PnL for offline quotes."""
    # Explicit admission bounds permit exact aligned additions and products of
    # prices, quantity and multiplier without ambient Decimal28 rounding.
    # Keep the caller's global decimal context unchanged.
    with localcontext(Context(prec=1024)):
        return _replay(quotes, strategy, config, finalize=finalize,
                       entry_halt_from_time_msc=entry_halt_from_time_msc)


def _replay(quotes: list[Any], strategy: Any, config: EngineConfig, *,
            finalize: bool,
            entry_halt_from_time_msc: int | None) -> dict[str, Any]:
    """Replay increasing quote clocks through an entry-only strategy.

    ``strategy.on_quote(quote, position)`` returns ``long``, ``short`` or None.
    Its positive Decimal stop/target distances are price units, not currency.
    ``max_hold_ms`` is a positive integer. ``session_open(time_msc)`` and
    ``reset()`` define the strategy's explicit session and history boundary.

    Normal entry/exit decisions fill only on a *later* quote at or after their
    latency deadline. A data gap cancels a pending entry and requests an exit
    after the same latency. An exit already requested keeps its old deadline.
    Gap flags cannot establish the actual price path, availability, or maximum
    loss inside the gap.
    At finalized EOF, an open position remains open; its mark is unrealized.
    An observation boundary (finalize=False) preserves outstanding decisions
    and emits no fabricated EOF cancellation. Replaying a longer prefix can
    therefore preserve the already observed event prefix exactly.

    A requested paper stop is observed only at the first quote at/after its
    timestamp. It permanently halts new entries, cancels a pending entry before
    any fill, and requests a delayed position exit. It is a local simulation
    control, not an order or a fill at the time the control was requested.
    """
    if not isinstance(config, EngineConfig):
        raise ValueError("config must be EngineConfig")
    if type(finalize) is not bool:
        raise ValueError("finalize must be bool")
    if entry_halt_from_time_msc is not None:
        _integer("entry_halt_from_time_msc", entry_halt_from_time_msc)
    stop_distance = _decimal("stop_distance", strategy.stop_distance, positive=True)
    target_distance = _decimal("target_distance", strategy.target_distance, positive=True)
    max_hold_ms = _integer("max_hold_ms", strategy.max_hold_ms, positive=True)
    previous_time: int | None = None
    for quote in quotes:
        clock = _integer("quote.time_msc", quote.time_msc)
        bid = _decimal("quote.bid", quote.bid, positive=True)
        ask = _decimal("quote.ask", quote.ask, positive=True)
        if ask < bid:
            raise ValueError("quote ask must not be below bid")
        if bid <= config.slippage_price:
            raise ValueError("slippage would create a nonpositive simulated price")
        if previous_time is not None and clock <= previous_time:
            raise ValueError("quote clocks must be strictly increasing")
        previous_time = clock

    events: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    equity_points: list[dict[str, Any]] = []
    position: dict[str, Any] | None = None
    pending: dict[str, Any] | None = None
    entered_count = 0
    realized = Decimal(0)
    peak = Decimal(0)
    maximum_drawdown = Decimal(0)
    risk_halted = False
    entry_halted = False
    previous_quote: Any | None = None
    previous_session: bool | None = None
    fee_per_side = config.quantity * config.commission_per_unit_per_side
    scale = config.quantity * config.contract_multiplier

    def emit(event: str, quote: Any, **details: Any) -> None:
        events.append({"event_index": len(events), "event": event,
                       "time_msc": quote.time_msc,
                       "source_row": getattr(quote, "source_row", None), **details})

    def entry_price(side: str, quote: Any) -> Decimal:
        return (quote.ask + config.slippage_price if side == "long"
                else quote.bid - config.slippage_price)

    def exit_price(side: str, quote: Any) -> Decimal:
        return (quote.bid - config.slippage_price if side == "long"
                else quote.ask + config.slippage_price)

    def mark(quote: Any) -> tuple[Decimal, Decimal, Decimal]:
        if position is None:
            return Decimal(0), Decimal(0), Decimal(0)
        marked_price = exit_price(position["side"], quote)
        direction = Decimal(1) if position["side"] == "long" else Decimal(-1)
        gross = (marked_price - position["entry_price"]) * direction * scale
        return marked_price, gross, gross - fee_per_side * 2

    def close(quote: Any, decision: dict[str, Any]) -> None:
        nonlocal position, realized, pending
        assert position is not None
        price, gross, net = mark(quote)
        trade = {**position,
                 "exit_price": price, "exit_time_msc": quote.time_msc,
                 "exit_source_row": getattr(quote, "source_row", None),
                 "exit_reason": decision["reason"],
                 "exit_trigger_time_msc": decision["decision_time_msc"],
                 "exit_eligible_time_msc": decision["eligible_time_msc"],
                 "gross_pnl_currency": gross, "commission_currency": fee_per_side * 2,
                 "net_pnl_currency": net,
                 "holding_ms": quote.time_msc - position["entry_time_msc"],
                 "hypothetical": True,
                 "quality_flags": list(position["quality_flags"])}
        trades.append(trade)
        realized += net
        emit("exit_filled", quote, trade_id=position["trade_id"], side=position["side"],
             price=price, reason=decision["reason"],
             decision_time_msc=decision["decision_time_msc"],
             eligible_time_msc=decision["eligible_time_msc"],
             hypothetical=True)
        position = None
        pending = None

    def request_exit(quote: Any, reason: str) -> None:
        nonlocal pending
        assert position is not None
        pending = {"kind": "exit", "reason": reason,
                   "decision_time_msc": quote.time_msc,
                   "eligible_time_msc": quote.time_msc + config.latency_ms}
        emit("exit_decision", quote, trade_id=position["trade_id"], **pending)

    strategy.reset()
    for quote in quotes:
        session_open = strategy.session_open(quote.time_msc)
        if type(session_open) is not bool:
            raise ValueError("session_open must return bool")
        if (not entry_halted and entry_halt_from_time_msc is not None
                and quote.time_msc >= entry_halt_from_time_msc):
            entry_halted = True
            emit("paper_stop_observed", quote,
                 requested_time_msc=entry_halt_from_time_msc)
            if pending is not None and pending["kind"] == "entry":
                emit("pending_cancelled", quote, reason="paper_stop", pending=pending)
                pending = None
            if position is not None and pending is None:
                request_exit(quote, "paper_stop")
        gap_ms = (quote.time_msc - previous_quote.time_msc
                  if previous_quote is not None else 0)
        gap = previous_quote is not None and gap_ms > config.max_quote_gap_ms
        if gap:
            emit("data_gap", quote, previous_time_msc=previous_quote.time_msc,
                 gap_ms=gap_ms, quality_flags=["GAP_PRICE_PATH_UNKNOWN"])
            if pending is not None and pending["kind"] == "entry":
                emit("pending_cancelled", quote, reason="data_gap", pending=pending)
                pending = None
            if position is not None:
                position["quality_flags"] = sorted(set(position["quality_flags"])
                                                   | {"GAP_PRICE_PATH_UNKNOWN"})
                if pending is not None:
                    position["quality_flags"] = sorted(set(position["quality_flags"])
                                                       | {"GAP_DURING_PENDING_EXIT"})
                    emit("gap_during_pending_exit", quote, trade_id=position["trade_id"],
                         pending=pending, quality_flags=["GAP_DURING_PENDING_EXIT"])
                else:
                    request_exit(quote, "data_gap")
            strategy.reset()
        if previous_session is not None and previous_session != session_open:
            strategy.reset()
            emit("session_boundary", quote, session_open=session_open)
        if not session_open and pending is not None and pending["kind"] == "entry":
            emit("pending_cancelled", quote, reason="session_closed", pending=pending)
            pending = None

        if pending is not None and quote.time_msc >= pending["eligible_time_msc"]:
            if pending["kind"] == "exit":
                close(quote, pending)
            else:
                rejection = None
                side = pending["side"]
                price = entry_price(side, quote)
                if not session_open:
                    rejection = "session_closed"
                elif entry_halted:
                    rejection = "paper_stop"
                elif quote.ask - quote.bid > config.max_entry_spread:
                    rejection = "entry_spread_limit"
                elif risk_halted or realized <= -config.max_loss_currency:
                    rejection = "loss_limit"
                elif entered_count >= config.max_trades:
                    rejection = "trade_limit"
                elif price <= 0 or exit_price(side, quote) <= 0:
                    rejection = "nonpositive_simulated_price"
                else:
                    direction = Decimal(1) if side == "long" else Decimal(-1)
                    immediate_net = ((exit_price(side, quote) - price) * direction * scale
                                     - fee_per_side * 2)
                    if realized + immediate_net <= -config.max_loss_currency:
                        rejection = "projected_entry_cost_loss_limit"
                        risk_halted = True
                if rejection is not None:
                    emit("entry_rejected", quote, reason=rejection, pending=pending)
                else:
                    entered_count += 1
                    position = {"trade_id": entered_count, "side": side,
                                "quantity": config.quantity, "contract_multiplier": config.contract_multiplier,
                                "symbol": config.symbol, "price_currency": config.price_currency,
                                "entry_price": price, "entry_time_msc": quote.time_msc,
                                "entry_source_row": getattr(quote, "source_row", None),
                                "entry_decision_time_msc": pending["decision_time_msc"],
                                "entry_eligible_time_msc": pending["eligible_time_msc"],
                                "entry_signal_source_row": pending["signal_source_row"],
                                "stop_price": price - stop_distance if side == "long" else price + stop_distance,
                                "target_price": price + target_distance if side == "long" else price - target_distance,
                                "entry_commission_currency": fee_per_side,
                                "quality_flags": [],
                                "hypothetical": True}
                    emit("entry_filled", quote, trade_id=entered_count, side=side, price=price,
                         decision_time_msc=pending["decision_time_msc"],
                         eligible_time_msc=pending["eligible_time_msc"], hypothetical=True)
                pending = None

        _, _, open_net = mark(quote)
        net_equity = realized + open_net
        if net_equity <= -config.max_loss_currency and not risk_halted:
            risk_halted = True
            emit("loss_limit_reached", quote, net_equity_currency=net_equity,
                 loss_limit_currency=config.max_loss_currency)
        if position is not None and pending is None:
            observed_exit = quote.bid if position["side"] == "long" else quote.ask
            is_long = position["side"] == "long"
            stop_hit = (observed_exit <= position["stop_price"] if is_long
                        else observed_exit >= position["stop_price"])
            target_hit = (observed_exit >= position["target_price"] if is_long
                          else observed_exit <= position["target_price"])
            if risk_halted:
                request_exit(quote, "loss_limit")
            elif stop_hit:
                request_exit(quote, "stop")
            elif target_hit:
                request_exit(quote, "target")
            elif quote.time_msc - position["entry_time_msc"] >= max_hold_ms:
                request_exit(quote, "max_hold")
            elif not session_open:
                request_exit(quote, "session_closed")

        signal = strategy.on_quote(quote, dict(position) if position is not None else None)
        if signal not in (None, "long", "short"):
            raise ValueError("strategy signal must be long, short, or None")
        if (signal is not None and position is None and pending is None and session_open
                and not gap and not risk_halted and not entry_halted
                and entered_count < config.max_trades
                and quote.ask - quote.bid <= config.max_entry_spread):
            pending = {"kind": "entry", "side": signal,
                       "decision_time_msc": quote.time_msc,
                       "eligible_time_msc": quote.time_msc + config.latency_ms,
                       "signal_source_row": getattr(quote, "source_row", None)}
            emit("entry_decision", quote, **pending)
        peak = max(peak, net_equity)
        drawdown = peak - net_equity
        maximum_drawdown = max(maximum_drawdown, drawdown)
        equity_points.append({"time_msc": quote.time_msc,
                              "realized_net_pnl_currency": realized,
                              "open_liquidation_net_pnl_currency": open_net,
                              "net_equity_currency": net_equity,
                              "peak_net_equity_currency": peak,
                              "drawdown_currency": drawdown})
        previous_quote = quote
        previous_session = session_open

    open_report = None
    if previous_quote is not None:
        if finalize and pending is not None and pending["kind"] == "entry":
            emit("pending_cancelled", previous_quote, reason="end_of_data", pending=pending)
            pending = None
        if position is not None:
            marked_price, gross, net = mark(previous_quote)
            open_report = {**position, "mark_time_msc": previous_quote.time_msc,
                           "mark_source_row": getattr(previous_quote, "source_row", None),
                           "liquidation_mark_price": marked_price,
                           "unrealized_gross_pnl_currency": gross,
                           "estimated_exit_commission_currency": fee_per_side,
                           "net_liquidation_pnl_currency": net,
                           "pending_exit": pending,
                           "quality_flags": sorted(set(position["quality_flags"])
                                                   | {("OPEN_POSITION_AT_END" if finalize
                                                       else "OPEN_POSITION_AT_OBSERVATION_BOUNDARY"),
                                                      "UNREALIZED_EXIT_COST_ESTIMATE"})}
            if finalize and pending is not None:
                emit("pending_exit_unfilled_at_end", previous_quote, pending=pending,
                     trade_id=position["trade_id"])
    report = {
        "schema_version": 1, "execution_model": "delayed_quote_simulation",
        "gap_liquidation_model": "delayed_exit_preserving_existing_exit_deadline",
        "hypothetical": True, "model_trained": False, "training_ready": False,
        "trading_enabled": False, "full_history_verified": False,
        "config": asdict(config), "quote_count": len(quotes),
        "entered_trade_count": entered_count, "closed_trade_count": len(trades),
        "closed_trades": trades, "open_position": open_report,
        "pending_decision": pending, "finalized": finalize,
        "entry_halted": entry_halted,
        "entry_halt_from_time_msc": entry_halt_from_time_msc,
        "events": events, "equity_points": equity_points,
        "realized_gross_pnl_currency": sum((t["gross_pnl_currency"] for t in trades), Decimal(0)),
        "realized_commission_currency": sum((t["commission_currency"] for t in trades), Decimal(0)),
        "realized_net_pnl_currency": realized,
        "ending_net_equity_currency": equity_points[-1]["net_equity_currency"] if equity_points else Decimal(0),
        "maximum_drawdown_currency": maximum_drawdown,
        "risk_halted": risk_halted, "trade_limit_reached": entered_count >= config.max_trades,
        "pnl_currency": config.price_currency,
        "quality_flags": ["GAP_PRICE_PATH_UNKNOWN"] if any(e["event"] == "data_gap" for e in events) else [],
        "assumptions": ["NO_ORDER_BOOK_OR_LIQUIDITY_MODEL", "CONSTANT_ADVERSE_SLIPPAGE",
                        "COMMISSION_IN_EXPLICIT_PRICE_CURRENCY", "NO_FX_CONVERSION",
                        "LOSS_LIMIT_CANNOT_GUARANTEE_EXECUTED_MAXIMUM_LOSS",
                        "NO_INITIAL_CAPITAL_OR_PERCENT_RETURN_ASSUMED"],
    }
    return _serializable(report)
