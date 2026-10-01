"""Fictional quote paths and rule configurations only; no source-trader histories."""
import contextlib
from decimal import Decimal
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from trading_intelligence.common import DataError, json_bytes
from scalper_research.cli import demo_inputs, main
from scalper_research.market import Quote, load_quotes
from scalper_research.pipeline import parse_config, run_research, research_status
from scalper_research.strategy import RollingBreakout, StrategyConfig


class StrategyTests(unittest.TestCase):
    def setUp(self):
        self.settings = {"lookback_quotes": 2, "breakout_buffer": "0.1", "stop_distance": "1", "target_distance": "2",
                         "max_hold_ms": 1000, "session_start_minute_utc": 0, "session_end_minute_utc": 1440, "cooldown_ms": 500}

    def strategy(self):
        return RollingBreakout(StrategyConfig.from_dict(self.settings))

    def q(self, time, mid):
        return Quote(time, Decimal(mid) - Decimal("0.05"), Decimal(mid) + Decimal("0.05"), 2)

    def test_prior_channel_excludes_signal_quote(self):
        s = self.strategy()
        self.assertIsNone(s.on_quote(self.q(1000, "100"), None))
        self.assertIsNone(s.on_quote(self.q(1100, "101"), None))
        self.assertEqual(s.on_quote(self.q(1200, "101.2"), None), "long")
        self.assertIsNone(s.on_quote(self.q(1300, "102"), None))  # cooldown
        self.assertEqual(s.on_quote(self.q(1800, "99"), None), "short")

    def test_position_and_history_reset_do_not_generate_entries(self):
        s = self.strategy()
        s.on_quote(self.q(1000, "100"), None)
        s.on_quote(self.q(1100, "101"), None)
        self.assertIsNone(s.on_quote(self.q(1200, "103"), {"side": "long"}))
        s.reset()
        self.assertIsNone(s.on_quote(self.q(2000, "200"), None))

    def test_utc_session_boundary_and_new_day_reset(self):
        self.settings.update(session_start_minute_utc=60, session_end_minute_utc=120)
        s = self.strategy()
        self.assertFalse(s.session_open(59 * 60000))
        self.assertTrue(s.session_open(60 * 60000))
        self.assertFalse(s.session_open(120 * 60000))
        s.on_quote(self.q(60 * 60000, "100"), None)
        s.on_quote(self.q(60 * 60000 + 100, "101"), None)
        self.assertIsNone(s.on_quote(self.q(86400000 + 60 * 60000, "200"), None))

    def test_strategy_config_refuses_nonfinite_unknown_fields_and_overnight(self):
        for key, value in (("stop_distance", "NaN"), ("lookback_quotes", True), ("session_end_minute_utc", 0),
                           ("breakout_buffer", 0.1), ("stop_distance", "1_0"), ("breakout_buffer", "0e99999999")):
            with self.subTest(key=key), self.assertRaises(DataError):
                StrategyConfig.from_dict({**self.settings, key: value})
        with self.assertRaises(DataError):
            StrategyConfig.from_dict({**self.settings, "unknown_rule": 1})

    def test_direct_strategy_midpoint_preserves_imported_precision(self):
        s = self.strategy()
        price = Decimal("100.000000000000000000000000000001")
        s.on_quote(Quote(1000, price, price, 2), None)
        self.assertEqual(s._history[0], price)


class ResearchPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = demo_inputs(self.root / "fictional-inputs")
        self.out = self.root / "out"

    def tearDown(self):
        self.temp.cleanup()

    def read_config(self):
        return json.loads(self.paths[2].read_text())

    def write_config(self, document):
        self.paths[2].write_bytes(json_bytes(document))

    def run_research(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("offline only")):
            return run_research(*self.paths, self.out)

    def test_synthetic_end_to_end_flat_partitions_frozen_config_and_false_gates(self):
        result = self.run_research()
        self.assertEqual(result["status"], "completed", result["errors"])
        self.assertEqual(result["evaluation_status"], "synthetic_behavior_check")
        summary = json.loads(Path(result["summary"]).read_text())
        for field in ("training_ready", "model_trained", "replay_accepted", "trading_enabled"):
            self.assertIs(result[field], False)
            self.assertIs(summary[field], False)
        self.assertEqual([p["quote_count"] for p in result["partitions"].values()], [24, 24, 24])
        for name, report in summary["partitions"].items():
            self.assertEqual(report["config_sha256"], result["config_sha256"])
            start = result["partitions"][name]["first_time_msc"]
            self.assertTrue(all(t["entry_time_msc"] >= start for t in report["closed_trades"]))
        self.assertEqual(research_status(self.out)["run_id"], result["run_id"])

    def test_repeat_has_same_simulation_outputs_and_immutable_inputs(self):
        one = self.run_research()
        two = self.run_research()
        self.assertNotEqual(one["run_id"], two["run_id"])
        self.assertEqual(Path(one["summary"]).read_bytes(), Path(two["summary"]).read_bytes())
        self.assertEqual(len(list((self.out / "raw").iterdir())), 3)

    def test_future_test_quotes_cannot_change_development_results(self):
        first = self.run_research()
        original = json.loads(Path(first["summary"]).read_text())["partitions"]["development"]
        boundary = self.read_config()["evaluation"]["validation_end_msc"]
        lines = self.paths[0].read_text().splitlines()
        for i, line in enumerate(lines[1:], 1):
            when, bid, ask = line.split(",")
            if int(when) >= boundary:
                lines[i] = f"{when},{Decimal(bid)+1},{Decimal(ask)+1}"
        self.paths[0].write_text("\n".join(lines)+"\n")
        second = self.run_research()
        changed = json.loads(Path(second["summary"]).read_text())["partitions"]["development"]
        self.assertEqual(original, changed)

    def test_unknown_rights_block_replay_but_originals_retained(self):
        metadata = json.loads(self.paths[1].read_text())
        metadata.update(data_origin="user_supplied_unverified", usage_rights="not_verified")
        self.paths[1].write_bytes(json_bytes(metadata))
        result = self.run_research()
        self.assertEqual(result["status"], "failed")
        self.assertIn("REPLAY_USAGE_RIGHTS_NOT_ASSERTED", result["errors"])
        self.assertEqual(len(result["raw_files"]), 3)
        self.assertIsNone(result["summary"])

    def test_equal_timestamp_rows_preserved_on_load_but_replay_blocked(self):
        lines = self.paths[0].read_text().splitlines()
        lines.insert(2, lines[1])
        self.paths[0].write_text("\n".join(lines)+"\n")
        self.assertEqual(len(load_quotes(self.paths[0],self.paths[1]).quotes),73)
        result = self.run_research()
        self.assertEqual(result["errors"], ["REPLAY_EQUAL_TIMESTAMP_ORDER_UNVERIFIED"])

    def test_instrument_mismatch_and_short_partition_fail_closed(self):
        config = self.read_config()
        config["execution"]["symbol"] = "DIFFERENT"
        self.write_config(config)
        self.assertIn("REPLAY_INSTRUMENT_OR_CURRENCY_MISMATCH", self.run_research()["errors"])
        config["execution"]["symbol"] = "EURUSD"
        config["evaluation"]["development_end_msc"] = 1704186000001
        self.write_config(config)
        self.assertIn("REPLAY_PARTITION_TOO_SHORT", self.run_research()["errors"])

    def test_config_rejects_same_tick_latency_and_bad_boundaries(self):
        config = self.read_config()
        config["execution"]["latency_ms"] = 0
        with self.assertRaises(DataError):
            parse_config(json_bytes(config))
        config = self.read_config()
        config["evaluation"]["validation_end_msc"] = config["evaluation"]["development_end_msc"]
        with self.assertRaises(DataError):
            parse_config(json_bytes(config))

    def test_cli_returns_failed_status_and_no_new_c2_runs(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["demo", "--out", str(self.out)])
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(output.getvalue())["network_used"])
        self.assertFalse((self.out / "runs").exists())
        self.assertFalse((self.out / "history.sqlite3").exists())
        config = self.read_config()
        config["execution"]["latency_ms"] = 0
        self.write_config(config)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["replay",str(self.paths[0]),"--metadata",str(self.paths[1]),"--config",str(self.paths[2]),"--out",str(self.out)]),2)


if __name__ == "__main__":
    unittest.main()
