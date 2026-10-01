"""Hand-calculated replay scenarios using only invented quotes/signals."""

from dataclasses import dataclass, replace
from decimal import Context, Decimal, localcontext
import unittest

from scalper_research.engine import EngineConfig, replay


D = Decimal


@dataclass(frozen=True)
class Quote:
    time_msc: int
    bid: Decimal
    ask: Decimal
    source_row: int = 1


def q(clock, bid, ask, row=None):
    return Quote(clock, D(str(bid)), D(str(ask)), row if row is not None else clock + 1)


class ScriptStrategy:
    stop_distance = D("100")
    target_distance = D("100")
    max_hold_ms = 10000

    def __init__(self, signals=None, closed_after=None):
        self.signals = signals or {0: "long"}
        self.closed_after = closed_after
        self.seen = []
        self.resets = 0

    def reset(self):
        self.resets += 1

    def on_quote(self, quote, position):
        self.seen.append((quote.time_msc, position["side"] if position else None))
        return self.signals.get(quote.time_msc)

    def session_open(self, clock):
        return self.closed_after is None or clock < self.closed_after


def config(**changes):
    base = EngineConfig(
        symbol="SYNTHETIC", quantity=D("1"), contract_multiplier=D("1"),
        price_currency="USD", commission_per_unit_per_side=D("0"),
        slippage_price=D("0"), latency_ms=1, max_quote_gap_ms=1000,
        max_entry_spread=D("2"), max_loss_currency=D("1000"), max_trades=10,
    )
    return replace(base, **changes)


class ReplayEngineTests(unittest.TestCase):
    def test_long_costs_multiplier_and_exit_quote_are_hand_calculated(self):
        strategy = ScriptStrategy()
        strategy.target_distance = D("1")
        result = replay([q(0, 100, 101), q(1, 100, 101), q(2, 103, 104),
                         q(3, "102.5", "103.5")], strategy,
                        config(quantity=D("2"), contract_multiplier=D("10"),
                               commission_per_unit_per_side=D("0.5"), slippage_price=D("0.25")))
        trade = result["closed_trades"][0]
        self.assertEqual(trade["entry_price"], "101.25")
        self.assertEqual(trade["exit_price"], "102.25")
        self.assertEqual(D(trade["gross_pnl_currency"]), D("20"))
        self.assertEqual(D(trade["commission_currency"]), D("2"))
        self.assertEqual(D(trade["net_pnl_currency"]), D("18"))
        self.assertEqual(trade["exit_trigger_time_msc"], 2)
        self.assertEqual(trade["exit_time_msc"], 3)
        self.assertTrue(trade["hypothetical"])

    def test_short_costs_are_symmetric_and_use_ask_on_exit(self):
        strategy = ScriptStrategy({0: "short"})
        strategy.target_distance = D("1")
        result = replay([q(0, 100, 101), q(1, 100, 101), q(2, 97, 98),
                         q(3, "97.5", "98.5")], strategy,
                        config(quantity=D("2"), contract_multiplier=D("10"),
                               commission_per_unit_per_side=D("0.5"), slippage_price=D("0.25")))
        trade = result["closed_trades"][0]
        self.assertEqual(trade["entry_price"], "99.75")
        self.assertEqual(trade["exit_price"], "98.75")
        self.assertEqual(D(trade["net_pnl_currency"]), D("18"))

    def test_latency_waits_for_first_eligible_future_quote(self):
        strategy = ScriptStrategy()
        strategy.max_hold_ms = 1
        result = replay([q(t, 100 + t, 101 + t) for t in (0, 1, 4, 5, 6, 10, 11)],
                        strategy, config(latency_ms=5))
        trade = result["closed_trades"][0]
        self.assertEqual(trade["entry_time_msc"], 5)
        self.assertEqual(trade["entry_price"], "106")
        self.assertEqual(trade["exit_trigger_time_msc"], 6)
        self.assertEqual(trade["exit_time_msc"], 11)
        for event in result["events"]:
            if event["event"] in ("entry_filled", "exit_filled"):
                self.assertGreater(event["time_msc"], event["decision_time_msc"])
                self.assertGreaterEqual(event["time_msc"], event["eligible_time_msc"])

    def test_stop_crossing_fills_later_quote_not_requested_stop_price(self):
        strategy = ScriptStrategy()
        strategy.stop_distance = D("2")
        result = replay([q(0, 100, 101), q(1, 100, 101), q(2, 98, 99), q(3, 95, 96)],
                        strategy, config())
        trade = result["closed_trades"][0]
        self.assertEqual(trade["stop_price"], "99")
        self.assertEqual(trade["exit_price"], "95")
        self.assertEqual(trade["exit_reason"], "stop")
        self.assertEqual(D(trade["net_pnl_currency"]), D("-6"))

    def test_gap_cancels_pending_entry_and_resets_history(self):
        strategy = ScriptStrategy()
        result = replay([q(0, 100, 101), q(100, 100, 101), q(101, 100, 101)],
                        strategy, config(latency_ms=5, max_quote_gap_ms=10))
        self.assertEqual(result["entered_trade_count"], 0)
        self.assertEqual(strategy.resets, 2)
        self.assertIn("GAP_PRICE_PATH_UNKNOWN", result["quality_flags"])
        self.assertEqual([e["reason"] for e in result["events"]
                          if e["event"] == "pending_cancelled"], ["data_gap"])

    def test_new_gap_exit_is_delayed_and_remains_open_at_eof(self):
        data = [q(0, 100, 101), q(1, 100, 101), q(100, 90, 91)]
        result = replay(data, ScriptStrategy(), config(max_quote_gap_ms=10))
        self.assertEqual(result["closed_trade_count"], 0)
        self.assertEqual(result["open_position"]["pending_exit"]["reason"], "data_gap")
        self.assertEqual(result["open_position"]["pending_exit"]["eligible_time_msc"], 101)
        finished = replay(data + [q(101, 89, 90)], ScriptStrategy(), config(max_quote_gap_ms=10))
        trade = finished["closed_trades"][0]
        self.assertEqual(trade["exit_time_msc"], 101)
        self.assertEqual(trade["exit_price"], "89")
        self.assertIn("GAP_PRICE_PATH_UNKNOWN", trade["quality_flags"])

    def test_gap_keeps_existing_exit_deadline_and_flags_unknown_path(self):
        strategy = ScriptStrategy()
        strategy.stop_distance = D("2")
        result = replay([q(0, 100, 101), q(1, 100, 101), q(2, 98, 99), q(100, 89, 90)],
                        strategy, config(max_quote_gap_ms=10))
        trade = result["closed_trades"][0]
        self.assertEqual(trade["exit_trigger_time_msc"], 2)
        self.assertEqual(trade["exit_eligible_time_msc"], 3)
        self.assertEqual(trade["exit_time_msc"], 100)
        self.assertEqual(trade["exit_reason"], "stop")
        self.assertIn("GAP_DURING_PENDING_EXIT", trade["quality_flags"])

    def test_eof_liquidation_mark_costs_are_unrealized_and_no_exit_is_fabricated(self):
        result = replay([q(0, 100, 101), q(1, 100, 101)], ScriptStrategy(),
                        config(quantity=D("2"), contract_multiplier=D("10"),
                               commission_per_unit_per_side=D("0.5"), slippage_price=D("0.25")))
        self.assertEqual(result["closed_trade_count"], 0)
        self.assertEqual(D(result["realized_net_pnl_currency"]), D("0"))
        self.assertEqual(result["open_position"]["liquidation_mark_price"], "99.75")
        self.assertEqual(D(result["open_position"]["unrealized_gross_pnl_currency"]), D("-30"))
        self.assertEqual(D(result["open_position"]["net_liquidation_pnl_currency"]), D("-32"))
        self.assertEqual(D(result["ending_net_equity_currency"]), D("-32"))
        self.assertEqual(D(result["maximum_drawdown_currency"]), D("32"))
        self.assertFalse(any(e["event"] == "exit_filled" for e in result["events"]))

    def test_eof_pending_exit_remains_open_and_entry_is_cancelled(self):
        strategy = ScriptStrategy()
        strategy.stop_distance = D("2")
        result = replay([q(0, 100, 101), q(1, 100, 101), q(2, 98, 99)], strategy, config())
        self.assertEqual(result["closed_trade_count"], 0)
        self.assertEqual(result["open_position"]["pending_exit"]["reason"], "stop")
        self.assertIn("pending_exit_unfilled_at_end", [e["event"] for e in result["events"]])
        no_fill = replay([q(0, 100, 101)], ScriptStrategy(), config())
        self.assertEqual(no_fill["entered_trade_count"], 0)
        self.assertEqual(no_fill["events"][-1]["reason"], "end_of_data")

    def test_loss_limit_uses_marked_equity_and_latency_does_not_guarantee_maximum_loss(self):
        strategy = ScriptStrategy({0: "long", 4: "long", 5: "long"})
        result = replay([q(0, 100, 101), q(1, 100, 101), q(2, 98, 99),
                         q(3, 95, 96), q(4, 100, 101), q(5, 100, 101)],
                        strategy, config(max_loss_currency=D("3")))
        self.assertTrue(result["risk_halted"])
        self.assertEqual(result["entered_trade_count"], 1)
        self.assertEqual(result["closed_trades"][0]["exit_reason"], "loss_limit")
        self.assertEqual(D(result["realized_net_pnl_currency"]), D("-6"))
        self.assertEqual(D(result["maximum_drawdown_currency"]), D("6"))

    def test_projected_entry_cost_breach_rejects_before_position(self):
        result = replay([q(0, 100, 101), q(1, 100, 101)], ScriptStrategy(),
                        config(quantity=D("2"), contract_multiplier=D("10"),
                               commission_per_unit_per_side=D("0.5"), slippage_price=D("0.25"),
                               max_loss_currency=D("30")))
        self.assertEqual(result["entered_trade_count"], 0)
        self.assertTrue(result["risk_halted"])
        self.assertEqual(result["events"][-1]["reason"], "projected_entry_cost_loss_limit")

    def test_trade_limit_counts_entries_and_no_reentry_after_closed_limit(self):
        strategy = ScriptStrategy({0: "long", 3: "long", 4: "short", 5: "long"})
        strategy.max_hold_ms = 1
        result = replay([q(t, 100, 101) for t in range(6)], strategy, config(max_trades=1))
        self.assertEqual(result["entered_trade_count"], 1)
        self.assertEqual(result["closed_trade_count"], 1)
        self.assertTrue(result["trade_limit_reached"])
        self.assertEqual(len(strategy.seen), 6)

    def test_spread_and_session_reject_pending_entry_at_fill_quote(self):
        spread = replay([q(0, 100, 101), q(1, 100, 110)], ScriptStrategy(), config())
        self.assertEqual(spread["entered_trade_count"], 0)
        self.assertEqual(spread["events"][-1]["reason"], "entry_spread_limit")
        session = replay([q(0, 100, 101), q(1, 100, 101)],
                         ScriptStrategy(closed_after=1), config())
        self.assertEqual(session["entered_trade_count"], 0)
        self.assertIn("session_closed", [e.get("reason") for e in session["events"]])

    def test_session_exit_is_delayed_even_when_session_has_closed(self):
        result = replay([q(t, 100, 101) for t in range(4)],
                        ScriptStrategy(closed_after=2), config())
        self.assertEqual(result["closed_trades"][0]["exit_reason"], "session_closed")
        self.assertEqual(result["closed_trades"][0]["exit_trigger_time_msc"], 2)
        self.assertEqual(result["closed_trades"][0]["exit_time_msc"], 3)

    def test_future_suffix_does_not_change_prior_decisions_or_marks(self):
        prefix = [q(0, 100, 101), q(1, 100, 101), q(2, 102, 103)]
        left = replay(prefix, ScriptStrategy(), config())
        right = replay(prefix + [q(3, 90, 91), q(4, 95, 96)], ScriptStrategy(), config())
        prior_right = [e for e in right["events"] if e["time_msc"] <= 2]
        prior_left = [e for e in left["events"] if e["event"] != "pending_exit_unfilled_at_end"]
        self.assertEqual(prior_left, prior_right)
        self.assertEqual(left["equity_points"], right["equity_points"][:3])

    def test_invalid_configs_quotes_and_strategy_outputs_are_rejected(self):
        for changes in ({"latency_ms": 0}, {"latency_ms": True}, {"latency_ms": 1.0},
                        {"quantity": D("0")}, {"quantity": 1.0},
                        {"slippage_price": D("-1")}, {"max_loss_currency": D("Infinity")},
                        {"max_trades": False}, {"price_currency": ""}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                config(**changes)
        for data in ([q(0, 100, 101), q(0, 100, 101)], [q(1, 100, 101), q(0, 100, 101)],
                     [q(0, 101, 100)], [q(0, 0, 1)], [q(0, "NaN", 101)]):
            with self.subTest(data=data), self.assertRaises(ValueError):
                replay(data, ScriptStrategy(), config())
        with self.assertRaises(ValueError):
            replay([q(0, 100, 101)], ScriptStrategy({0: "buy"}), config())

    def test_empty_data_retains_false_readiness_and_no_fabricated_metrics(self):
        result = replay([], ScriptStrategy(), config())
        self.assertEqual(result["closed_trades"], [])
        self.assertEqual(result["events"], [])
        self.assertIsNone(result["open_position"])
        for flag in ("model_trained", "training_ready", "trading_enabled", "full_history_verified"):
            self.assertFalse(result[flag])
        self.assertEqual(D(result["maximum_drawdown_currency"]), D("0"))

    def test_ambient_decimal_context_does_not_change_prices_or_report_serialization(self):
        data = [q(0, 10000, 10001), q(1, 10000, 10001)]
        settings = config(contract_multiplier=D("1E+2"))
        expected = replay(data, ScriptStrategy(), settings)
        unusual = Context(prec=3, Emax=2, Emin=-2, capitals=0)
        with localcontext(unusual) as caller_context:
            actual = replay(data, ScriptStrategy(), settings)
            self.assertEqual(caller_context.prec, 3)
            self.assertEqual(caller_context.Emax, 2)
            self.assertEqual(caller_context.capitals, 0)
        self.assertEqual(actual, expected)

    def test_explicit_finalize_defaults_match_existing_replay(self):
        data = [q(0, 100, 101), q(1, 100, 101)]
        default = replay(data, ScriptStrategy(), config())
        explicit = replay(data, ScriptStrategy(), config(), finalize=True,
                          entry_halt_from_time_msc=None)
        self.assertEqual(default, explicit)
        self.assertTrue(default["finalized"])
        self.assertFalse(default["entry_halted"])
        self.assertIn("OPEN_POSITION_AT_END", default["open_position"]["quality_flags"])

    def test_observation_boundary_preserves_pending_entry_without_eof_cancellation(self):
        result = replay([q(0, 100, 101)], ScriptStrategy(), config(), finalize=False)
        self.assertEqual(result["pending_decision"]["kind"], "entry")
        self.assertEqual(result["pending_decision"]["eligible_time_msc"], 1)
        self.assertFalse(result["finalized"])
        self.assertIsNone(result["open_position"])
        self.assertEqual([event["event"] for event in result["events"]], ["entry_decision"])

    def test_observation_boundary_preserves_pending_exit_and_marks_open(self):
        strategy = ScriptStrategy()
        strategy.stop_distance = D("2")
        result = replay([q(0, 100, 101), q(1, 100, 101), q(2, 98, 99)],
                        strategy, config(), finalize=False)
        self.assertEqual(result["pending_decision"]["kind"], "exit")
        self.assertEqual(result["open_position"]["pending_exit"], result["pending_decision"])
        self.assertIn("OPEN_POSITION_AT_OBSERVATION_BOUNDARY", result["open_position"]["quality_flags"])
        self.assertNotIn("OPEN_POSITION_AT_END", result["open_position"]["quality_flags"])
        self.assertNotIn("pending_exit_unfilled_at_end", [e["event"] for e in result["events"]])

    def test_longer_prefix_preserves_all_observed_events_with_pending_decisions(self):
        data = [q(0, 100, 101), q(1, 100, 101), q(2, 98, 99), q(3, 97, 98)]
        results = []
        for length in range(1, len(data) + 1):
            strategy = ScriptStrategy()
            strategy.stop_distance = D("2")
            results.append(replay(data[:length], strategy, config(), finalize=False))
        for previous, current in zip(results, results[1:]):
            self.assertEqual(previous["events"], current["events"][:len(previous["events"])])
            self.assertEqual(previous["equity_points"], current["equity_points"][:len(previous["equity_points"])])

    def test_paper_stop_cancels_entry_before_first_eligible_fill(self):
        strategy = ScriptStrategy({0: "long", 1: "short", 2: "long"})
        result = replay([q(t, 100, 101) for t in range(3)], strategy, config(),
                        finalize=False, entry_halt_from_time_msc=1)
        self.assertEqual(result["entered_trade_count"], 0)
        self.assertTrue(result["entry_halted"])
        self.assertIsNone(result["pending_decision"])
        stops = [e for e in result["events"] if e["event"] == "paper_stop_observed"]
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0]["time_msc"], 1)
        self.assertEqual(result["events"][-1]["reason"], "paper_stop")

    def test_paper_stop_position_exit_waits_for_later_quote_and_can_remain_open(self):
        data = [q(0, 100, 101), q(1, 100, 101), q(2, 99, 100)]
        boundary = replay(data, ScriptStrategy(), config(), finalize=False,
                          entry_halt_from_time_msc=2)
        self.assertEqual(boundary["closed_trade_count"], 0)
        self.assertEqual(boundary["pending_decision"]["reason"], "paper_stop")
        self.assertEqual(boundary["pending_decision"]["eligible_time_msc"], 3)
        self.assertEqual(boundary["open_position"]["entry_time_msc"], 1)
        finished = replay(data + [q(3, 98, 99)], ScriptStrategy(), config(),
                          finalize=False, entry_halt_from_time_msc=2)
        trade = finished["closed_trades"][0]
        self.assertEqual(trade["exit_reason"], "paper_stop")
        self.assertEqual(trade["exit_trigger_time_msc"], 2)
        self.assertEqual(trade["exit_time_msc"], 3)
        self.assertEqual(boundary["events"], finished["events"][:len(boundary["events"])])
        finalized = replay(data, ScriptStrategy(), config(), entry_halt_from_time_msc=2)
        self.assertEqual(finalized["closed_trade_count"], 0)
        self.assertIsNotNone(finalized["open_position"])

    def test_paper_stop_keeps_existing_exit_deadline_and_observes_only_future_quote(self):
        strategy = ScriptStrategy()
        strategy.stop_distance = D("2")
        data = [q(0, 100, 101), q(1, 100, 101), q(2, 98, 99), q(3, 97, 98)]
        result = replay(data, strategy, config(), finalize=False, entry_halt_from_time_msc=3)
        self.assertEqual(result["closed_trades"][0]["exit_reason"], "stop")
        self.assertEqual(result["closed_trades"][0]["exit_trigger_time_msc"], 2)
        self.assertEqual(result["closed_trades"][0]["exit_time_msc"], 3)
        future = replay(data[:2], ScriptStrategy(), config(), finalize=False,
                        entry_halt_from_time_msc=10)
        self.assertFalse(future["entry_halted"])
        self.assertFalse(any(e["event"] == "paper_stop_observed" for e in future["events"]))
        stopped = replay(data, ScriptStrategy(), config(), finalize=False,
                         entry_halt_from_time_msc=0)
        self.assertEqual(stopped["entered_trade_count"], 0)
        self.assertEqual(stopped["events"][0]["event"], "paper_stop_observed")

    def test_paper_boundary_and_control_inputs_are_strictly_typed(self):
        for finalize in (None, 0, 1, "false"):
            with self.subTest(finalize=finalize), self.assertRaises(ValueError):
                replay([], ScriptStrategy(), config(), finalize=finalize)
        for halt in (True, False, -1, 0.0, "0"):
            with self.subTest(halt=halt), self.assertRaises(ValueError):
                replay([], ScriptStrategy(), config(), entry_halt_from_time_msc=halt)


if __name__ == "__main__":
    unittest.main()
