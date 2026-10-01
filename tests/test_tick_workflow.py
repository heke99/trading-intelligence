"""Fictional basket behavior and fail-closed local workflow contracts."""
from decimal import Context, getcontext, localcontext
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from trading_intelligence.common import DataError, json_bytes, load_json, sha256
from scalper_research.cli import main
from scalper_research.tick_workflow import ASSETS, run_tick_benchmark, run_tick_demo, write_tick_plan
from scalper_research.workflow import learning_demo_inputs


class TickWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_plan_writes_all_targets_but_no_data_or_execution_defaults(self):
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            result = write_tick_plan(self.root/"plan")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(tuple(x["requested_asset"] for x in result["assets"]), ASSETS)
        self.assertFalse(result["acquisition_performed"])
        for asset in result["assets"]:
            self.assertEqual(asset["received_tick_rows"], 0)
            self.assertIsNone(asset["contract_multiplier"])
            self.assertIsNone(asset["exact_broker_symbol"])
        self.assertEqual(result["catalog_probe"]["received_bytes"], 0)
        self.assertFalse(result["training_ready"])

    def test_config_and_source_are_archived_before_gap_policy_failure(self):
        paths = learning_demo_inputs(self.root/"inputs")
        result = run_tick_benchmark(*paths, self.root/"run", sample_period_ms=100, max_native_gap_ms=1000)
        self.assertEqual(result["status"], "failed")
        self.assertIn("RECONSTRUCTED_QUOTE_GAP_POLICY_MISMATCH", result["errors"])
        self.assertEqual(len(result["raw_files"]), 3)
        self.assertEqual(result["raw_files"][2]["sha256"], sha256(paths[2].read_bytes()))
        self.assertFalse(result["model_fitted"])
        self.assertTrue(result["finished_at_utc"])
        self.assertNotIn("learning", result["stages"])

    def test_unasserted_real_training_rights_cannot_fit(self):
        paths = learning_demo_inputs(self.root/"inputs")
        metadata = load_json(paths[1].read_bytes())
        metadata.update(data_origin="user_supplied_unverified", usage_rights="not_verified",
                        training_usage_rights="not_verified")
        paths[1].write_bytes(json_bytes(metadata))
        result = run_tick_benchmark(*paths, self.root/"run", sample_period_ms=1000, max_native_gap_ms=1000)
        self.assertEqual(result["status"], "failed")
        self.assertIn("LEARNING_REPLAY_USAGE_RIGHTS_NOT_ASSERTED", result["stages"]["learning"]["errors"])
        self.assertFalse(result["model_fitted"])
        self.assertNotIn("cost_stress", result["stages"])

    def test_failed_projection_does_not_start_learning(self):
        paths = learning_demo_inputs(self.root/"inputs")
        with patch("scalper_research.tick_projection.project_ticks", return_value={"status":"failed","errors":["SOURCE_INVALID"]}), \
             patch("scalper_research.learning_pipeline.run_learning") as learn:
            result = run_tick_benchmark(*paths, self.root/"run", sample_period_ms=1000, max_native_gap_ms=1000)
        self.assertEqual(result["status"], "failed")
        self.assertIn("TICK_BENCHMARK_PROJECTION_FAILED", result["errors"])
        learn.assert_not_called()

    def test_synthetic_basket_freezes_five_models_and_separates_currency_results(self):
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            result = run_tick_demo(self.root/"demo")
        self.assertEqual(result["status"], "completed", result["errors"])
        self.assertEqual(tuple(result["assets"]), ASSETS)
        self.assertFalse(result["cross_currency_pnl_aggregated"])
        for asset, run in result["assets"].items():
            with self.subTest(asset=asset):
                self.assertEqual(run["status"], "completed", run["errors"])
                self.assertTrue(run["model_fitted"])
                self.assertFalse(run["training_ready"])
                self.assertFalse(run["model_trained_on_real_market"])
                self.assertFalse(run["trading_enabled"])
                projected = run["stages"]["projection"]
                self.assertGreater(projected["duplicate_native_timestamp_rows"], 0)
                self.assertEqual(projected["raw_rows_written"], projected["input_quote_count"])
                self.assertTrue(run["stages"]["cost_stress"]["status"] == "completed")

    def test_synthetic_prices_and_configs_are_independent_of_ambient_decimal_context(self):
        # Verified review regression: fixture transforms used the caller's
        # precision/exponent range, rounding FX and overflowing the Nasdaq pivot.
        outputs = []
        original_context = getcontext().copy()
        for name, context in (("normal", Context(prec=28)),
                              ("restricted", Context(prec=2, Emax=2, Emin=-2))):
            directory = self.root/name
            with localcontext(context), \
                 patch("scalper_research.tick_workflow.run_tick_benchmark", return_value={"status":"completed"}):
                result = run_tick_demo(directory)
            self.assertEqual(result["status"], "completed", result["errors"])
            outputs.append({str(path.relative_to(directory/"synthetic-inputs")): sha256(path.read_bytes())
                            for path in (directory/"synthetic-inputs").rglob("*") if path.is_file()})
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(getcontext().prec, original_context.prec)

    def test_reusing_demo_output_does_not_overwrite_receipt(self):
        directory = self.root/"demo"
        directory.mkdir()
        receipt = directory/"tick-demo.json"
        receipt.write_bytes(b"original evidence")
        with self.assertRaisesRegex(DataError, "TICK_DEMO_REQUIRES_FRESH_OUTPUT_DIRECTORY"):
            run_tick_demo(directory)
        self.assertEqual(receipt.read_bytes(), b"original evidence")

    def test_tick_plan_cli_is_available_without_optional_reader(self):
        from contextlib import redirect_stdout
        from io import StringIO
        with redirect_stdout(StringIO()) as output:
            code = main(["tick-plan", "--out", str(self.root/"cli")])
        self.assertEqual(code, 0)
        result = load_json(output.getvalue().encode())
        self.assertEqual(len(result["assets"]), 5)
        self.assertFalse(result["training_ready"])


if __name__ == "__main__":
    unittest.main()
