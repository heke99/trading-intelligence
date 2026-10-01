"""Independent offline regressions for the standalone quote replay.

Every market row and instrument in this module is fictional.
"""
import json
import tempfile
import unittest
from decimal import Decimal, localcontext
from pathlib import Path

from scalper_research.engine import EngineConfig, replay
from scalper_research.market import Quote
from scalper_research.pipeline import run_research


class OneSignal:
    stop_distance = Decimal("4")
    target_distance = Decimal("20")
    max_hold_ms = 100000

    def reset(self):
        pass

    def session_open(self, time_msc):
        return True

    def on_quote(self, quote, position):
        return "long" if quote.time_msc == 1000 else None


def engine_config(**changes):
    values = dict(symbol="FICTIONAL", quantity=Decimal("2"),
                  contract_multiplier=Decimal("10"), price_currency="USD",
                  commission_per_unit_per_side=Decimal("0.1"),
                  slippage_price=Decimal("0.25"), latency_ms=1,
                  max_quote_gap_ms=100000, max_entry_spread=Decimal("5"),
                  max_loss_currency=Decimal("100000"), max_trades=100)
    values.update(changes)
    return EngineConfig(**values)


def write_inputs(root, *, execution_changes=None, csv_rows=None):
    quotes = root / "fictional.csv"
    rows = csv_rows or [(1000 * index, "100", "101") for index in range(1, 13)]
    quotes.write_text("time_msc,bid,ask\n" + "".join(
        f"{clock},{bid},{ask}\n" for clock, bid, ask in rows))
    metadata = root / "fictional_metadata.json"
    metadata.write_text(json.dumps({
        "schema_version": 1, "source_id": "independent_synthetic_review",
        "symbol": "FICTIONAL", "price_currency": "USD",
        "timestamp_basis": "utc_epoch_milliseconds",
        "timezone_evidence": "Fictional epoch-millisecond clock for offline tests",
        "data_origin": "synthetic_fixture", "usage_rights": "synthetic_only",
        "training_ready": False, "broker_verified": False,
        "full_history_verified": False,
    }))
    execution = {key: str(value) if isinstance(value, Decimal) else value
                 for key, value in engine_config().__dict__.items()}
    execution.update(execution_changes or {})
    config = root / "fictional_config.json"
    config.write_text(json.dumps({
        "schema_version": 1, "basis": "independent_rule_hypothesis",
        "strategy": {"lookback_quotes": 2, "breakout_buffer": "0",
                     "stop_distance": "4", "target_distance": "5",
                     "max_hold_ms": 100000, "session_start_minute_utc": 0,
                     "session_end_minute_utc": 1440, "cooldown_ms": 0},
        "execution": execution,
        "evaluation": {"development_end_msc": 5000, "validation_end_msc": 9000},
    }))
    return quotes, metadata, config


class ReplayReviewRegressions(unittest.TestCase):
    def test_zero_slippage_preserves_exact_admitted_quote_price(self):
        price = Decimal("100.000000000000000000000000000001")
        quotes = [Quote(clock, price, price, index + 2)
                  for index, clock in enumerate((1000, 2000, 3000))]
        report = replay(quotes, OneSignal(), engine_config(slippage_price=Decimal("0")))
        self.assertIsNotNone(report["open_position"])
        self.assertEqual(Decimal(report["open_position"]["entry_price"]), price)
        self.assertEqual(Decimal(report["open_position"]["liquidation_mark_price"]), price)

    def test_replay_result_does_not_depend_on_callers_exponent_context(self):
        price = Decimal("100")
        quotes = [Quote(clock, price, price, index + 2)
                  for index, clock in enumerate((1000, 2000, 3000))]
        config = engine_config(quantity=Decimal("1000"), slippage_price=Decimal("0"))
        reference = replay(quotes, OneSignal(), config)
        with localcontext() as caller_context:
            caller_context.Emax = 2
            caller_context.Emin = -2
            result = replay(quotes, OneSignal(), config)
            self.assertEqual(caller_context.Emax, 2)
            self.assertEqual(caller_context.Emin, -2)
        self.assertEqual(reference, result)

    def test_adverse_slippage_cannot_create_nonpositive_execution_price(self):
        quotes = [Quote(clock, Decimal(bid), Decimal(ask), index + 2)
                  for index, (clock, bid, ask) in enumerate([
                      (1000, "10", "11"), (2000, "10", "11"),
                      (3000, "1", "2"), (4000, "1", "2")])]
        try:
            report = replay(quotes, OneSignal(), engine_config(slippage_price=Decimal("2")))
        except ValueError:
            # A deterministic admission error is also preferable to an
            # impossible fill outside the engine's positive-price domain.
            return
        for event in report["events"]:
            if event["event"] in ("entry_filled", "exit_filled"):
                self.assertGreater(Decimal(event["price"]), 0)
        if report["open_position"] is not None:
            self.assertGreater(Decimal(report["open_position"]["liquidation_mark_price"]), 0)

    def test_bad_execution_text_returns_a_failed_input_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = write_inputs(root, execution_changes={"symbol": 1})
            result = run_research(*inputs, root / "out")
            self.assertEqual(result["status"], "failed")
            self.assertTrue(result["errors"])
            self.assertNotIn("REPLAY_INTERNAL_ERROR", result["errors"])
            self.assertFalse(result["training_ready"])
            self.assertFalse(result["replay_accepted"])

    def test_incompatible_slippage_returns_a_failed_simulation_input_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = write_inputs(root, execution_changes={"slippage_price": "100"})
            result = run_research(*inputs, root / "out")
            self.assertEqual(result["status"], "failed")
            self.assertTrue(result["errors"])
            self.assertNotIn("REPLAY_INTERNAL_ERROR", result["errors"])
            self.assertFalse(result["replay_accepted"])

    def test_development_mutation_cannot_change_test_position_or_signal_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first"
            changed = root / "changed"
            first.mkdir()
            changed.mkdir()
            original = write_inputs(first)
            changed_rows = [(1000 * index, str(100 + index * 5), str(101 + index * 5))
                            if index < 5 else (1000 * index, "100", "101")
                            for index in range(1, 13)]
            mutated = write_inputs(changed, csv_rows=changed_rows)
            original_run = run_research(*original, first / "out")
            changed_run = run_research(*mutated, changed / "out")
            self.assertEqual(original_run["status"], "completed")
            self.assertEqual(changed_run["status"], "completed")
            summaries = [json.loads(Path(run["summary"]).read_text())
                         for run in (original_run, changed_run)]
            self.assertNotEqual(summaries[0]["partitions"]["development"],
                                summaries[1]["partitions"]["development"])
            self.assertEqual(summaries[0]["partitions"]["test"],
                             summaries[1]["partitions"]["test"])
            test = summaries[1]["partitions"]["test"]
            self.assertEqual(test["first_time_msc"], 9000)
            self.assertEqual(test["entered_trade_count"], 0)
            self.assertIsNone(test["open_position"])

    def test_positive_synthetic_profit_cannot_admit_training_or_trading(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prices = [100, 100, 102, 103, 105, 106, 108, 109] * 3
            rows = [(1000 * index, str(price), str(price + 1))
                    for index, price in enumerate(prices, start=1)]
            inputs = write_inputs(root, csv_rows=rows)
            config = json.loads(inputs[2].read_text())
            config["strategy"]["target_distance"] = "1"
            config["evaluation"] = {"development_end_msc": 9000,
                                    "validation_end_msc": 17000}
            inputs[2].write_text(json.dumps(config))
            run = run_research(*inputs, root / "out")
            self.assertEqual(run["status"], "completed")
            summary = json.loads(Path(run["summary"]).read_text())
            self.assertGreater(Decimal(summary["partitions"]["test"]["realized_net_pnl_currency"]), 0)
            self.assertEqual(run["evaluation_status"], "synthetic_behavior_check")
            self.assertIn("SYNTHETIC_ONLY_NOT_MARKET_EVIDENCE", run["blockers"])
            for report in (run, summary, *summary["partitions"].values()):
                for field in ("model_trained", "training_ready", "replay_accepted", "trading_enabled"):
                    self.assertIs(report[field], False)


if __name__ == "__main__":
    unittest.main()
