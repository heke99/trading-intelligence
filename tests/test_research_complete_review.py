"""Independent regressions; all files, prices and model inputs are fictional."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from trading_intelligence.common import DataError, json_bytes, sha256
from scalper_research.learning import FEATURE_NAMES, FIT_PARAMETERS
from scalper_research.paper import paper_status, start_paper
from scalper_research.workflow import run_all_demo
from test_replay_review import write_inputs


class CompleteResearchReview(unittest.TestCase):
    def test_validation_receipt_must_bind_actual_selected_model_coefficients(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = write_inputs(root)
            inputs[0].write_bytes(b"time_msc,bid,ask\n")
            # Entirely fictional model artifact: no fitting or market history.
            model = {"schema_version": 1,
                     "model_type": "deterministic_logistic_signal_filter_v1",
                     "feature_version": 1, "feature_names": list(FEATURE_NAMES),
                     "coefficients": ["0"] * len(FEATURE_NAMES), "bias": "0",
                     "fit_parameters": dict(FIT_PARAMETERS),
                     "fit_summary": {"row_count": 20, "positive_count": 10, "negative_count": 10},
                     "data_origin": "synthetic_fixture",
                     "provenance": {"source_id": "fictional_receipt_review",
                                    "config_sha256": sha256(inputs[2].read_bytes()),
                                    "training_partition": "development_only",
                                    "development_end_msc": 5000,
                                    "validation_end_msc": 9000}}
            model["model_sha256"] = sha256(json_bytes(model))
            development_digest = model["model_sha256"]
            receipt = {"selected": {"eligible": True, "threshold": 0.5},
                       "config_sha256": sha256(inputs[2].read_bytes()),
                       "model_sha256": development_digest}
            receipt_raw = json_bytes(receipt)
            (root / "selection.json").write_bytes(receipt_raw)
            model["provenance"]["filter_selection"] = {
                "selected_threshold": "0.5", "selection_partition": "validation",
                "validation_selection_sha256": sha256(receipt_raw),
                "development_model_sha256": development_digest}
            # A different model can have a valid content hash; that does not
            # make the old model's threshold validation apply to its weights.
            model["coefficients"][0] = "0.25"
            model["model_sha256"] = sha256(json_bytes({
                key: value for key, value in model.items() if key != "model_sha256"}))
            model_path = root / "fictional_selected_model.json"
            model_path.write_bytes(json_bytes(model))
            with self.assertRaises(DataError):
                start_paper(*inputs, root / "paper", model_path=model_path, threshold=0.5)

    def test_failed_workflow_preserves_a_finished_failed_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "demo"
            # Isolate orchestration durability from fitting and paper mechanics;
            # these simulated stage responses do not claim market evidence.
            with (patch("scalper_research.market.import_quotes", return_value={
                    "status": "completed", "manifest_path": "fictional-import"}),
                  patch("scalper_research.learning_pipeline.run_learning", return_value={
                    "status": "completed", "selected_threshold": 0.4,
                    "model": "fictional-model.json"}),
                  patch("scalper_research.paper.start_paper", return_value={
                    "status": "waiting_for_quotes"}),
                  patch("scalper_research.paper.step_paper", side_effect=DataError(
                    "FICTIONAL_STAGE_INPUT_REJECTED"))):
                try:
                    run_all_demo(out)
                except DataError:
                    pass
            manifest = json.loads((out / "workflow.json").read_text())
            self.assertEqual(manifest["status"], "failed")
            self.assertIsNotNone(manifest.get("finished_at_utc"))
            self.assertIn("FICTIONAL_STAGE_INPUT_REJECTED", manifest["errors"])
            self.assertFalse(manifest["trading_enabled"])

    def test_corrupted_paper_cursor_is_rejected_on_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = write_inputs(root)
            out = root / "paper"
            initial = start_paper(*inputs, out)
            self.assertEqual(initial["accepted_quote_count"], 12)
            with sqlite3.connect(out / "paper.sqlite3") as connection:
                raw = connection.execute("SELECT state_json FROM paper_session").fetchone()[0]
                state = json.loads(raw)
                state["accepted_quote_count"] += 1
                connection.execute("UPDATE paper_session SET state_json=?",
                                   (json.dumps(state).encode(),))
            with self.assertRaises(DataError):
                paper_status(out)


if __name__ == "__main__":
    unittest.main()
