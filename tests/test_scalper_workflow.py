"""Offline full-path and failure durability checks, with fictional prices only."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from trading_intelligence.common import DataError
from scalper_research.cli import main
from scalper_research.workflow import run_all_demo


class WorkflowTests(unittest.TestCase):
    def test_instantiable_frozen_model_runs_after_selection_and_stops_flat(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "all"
            with patch("urllib.request.urlopen", side_effect=AssertionError("must remain offline")):
                result = run_all_demo(out)
            self.assertEqual(result["status"], "completed")
            learning = result["stages"]["learning"]
            self.assertTrue(learning["model_fitted"])
            self.assertGreater(learning["training_positive_count"], 4)
            self.assertGreater(learning["training_negative_count"], 4)
            proof = json.loads((out / "paper-proof.json").read_text())
            self.assertEqual(proof["status"], "stopped_flat")
            self.assertTrue(proof["report"]["model_used"])
            self.assertTrue(proof["report"]["threshold_selection_verified"])
            self.assertIsNone(proof["report"]["open_position"])
            self.assertIsNone(proof["report"]["pending_decision"])
            self.assertFalse(proof["forward_verified"])
            receipt = (out / "workflow.json").read_bytes()
            with self.assertRaisesRegex(DataError, "FRESH_OUTPUT"):
                run_all_demo(out)
            self.assertEqual((out / "workflow.json").read_bytes(), receipt)

    def test_interrupt_leaves_failure_receipt_and_no_success_or_ready_claim(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            with patch("scalper_research.market.import_quotes", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    run_all_demo(out)
            receipt = json.loads((out / "workflow.json").read_text())
            self.assertEqual(receipt["status"], "failed")
            self.assertIn("INTERRUPTED", receipt["errors"])
            self.assertTrue(receipt["finished_at_utc"])
            self.assertFalse(receipt["training_ready"])

    def test_strategy_cli_exposes_missing_expert_data_without_execution_claim(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(["strategy-audit"]), 0)
        result = json.loads(output.getvalue())
        self.assertFalse(result["implemented_hypothesis"]["implements_named_trader_strategy"])
        self.assertEqual(len(result["traders"]), 2)
        self.assertTrue(all(not trader["quote_only_input_sufficient"] for trader in result["traders"]))
        self.assertFalse(result["training_ready"])


if __name__ == "__main__":
    unittest.main()
