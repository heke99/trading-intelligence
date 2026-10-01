"""Every quote consumer must honour omitted reconstruction buckets."""
from pathlib import Path
import tempfile
import unittest

from trading_intelligence.common import DataError, json_bytes, load_json
from scalper_research.cli import demo_inputs
from scalper_research.learning_pipeline import run_learning
from scalper_research.market import load_quotes
from scalper_research.paper import start_paper
from scalper_research.pipeline import run_research


class ReconstructionGuardTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.paths = demo_inputs(self.root / "inputs")
        metadata = load_json(self.paths[1].read_bytes())
        # Fictional declaration: a source projector omitted invalid100ms buckets.
        metadata["wse_required_max_quote_gap_ms"] = 100
        self.paths[1].write_bytes(json_bytes(metadata))

    def test_replay_cannot_bridge_declared_segment_boundaries(self):
        result = run_research(*self.paths, self.root / "replay")
        self.assertEqual(result["status"], "failed")
        self.assertIn("RECONSTRUCTED_QUOTE_GAP_POLICY_MISMATCH", result["errors"])

    def test_learning_cannot_fit_over_declared_segment_boundaries(self):
        result = run_learning(*self.paths, self.root / "learning")
        self.assertEqual(result["status"], "failed")
        self.assertIn("RECONSTRUCTED_QUOTE_GAP_POLICY_MISMATCH", result["errors"])
        self.assertFalse(result["model_fitted"])

    def test_paper_cannot_resume_with_overwide_gap_tolerance(self):
        with self.assertRaisesRegex(DataError, "RECONSTRUCTED_QUOTE_GAP_POLICY_MISMATCH"):
            start_paper(*self.paths, self.root / "paper")

    def test_noninteger_or_unbounded_reconstruction_policy_is_not_accepted(self):
        metadata = load_json(self.paths[1].read_bytes())
        for value in (True, "100", 0, 60001):
            metadata["wse_required_max_quote_gap_ms"] = value
            self.paths[1].write_bytes(json_bytes(metadata))
            with self.subTest(value=value), self.assertRaisesRegex(DataError, "MARKET_RECONSTRUCTION_GAP_POLICY_INVALID"):
                load_quotes(self.paths[0], self.paths[1])

    def test_reconstruction_caveats_survive_quote_loading(self):
        metadata = load_json(self.paths[1].read_bytes())
        metadata["quality_flags"] = [
            "NATIVE_MESSAGE_CLOCK_NOT_RECEIVE_CLOCK",
            "BOOTSTRAP_COMPLETION_ASSUMED",
            "DERIVED_SAMPLED_VISIBLE_BIDASK_NOT_EXECUTABLE_LIQUIDITY",
            "UNREVIEWED_SOURCE_LABEL",
        ]
        self.paths[1].write_bytes(json_bytes(metadata))
        dataset = load_quotes(self.paths[0], self.paths[1])
        for flag in metadata["quality_flags"][:3]:
            self.assertIn(flag, dataset.quality_flags)
        self.assertNotIn("UNREVIEWED_SOURCE_LABEL", dataset.quality_flags)

    def test_failed_or_partial_terminal_exports_cannot_be_imported(self):
        metadata = load_json(self.paths[1].read_bytes())
        for status in ("failed", "in_progress", "partial", True, None):
            metadata["source_export_status"] = status
            self.paths[1].write_bytes(json_bytes(metadata))
            with self.subTest(status=status), self.assertRaisesRegex(DataError, "MARKET_SOURCE_EXPORT_INCOMPLETE"):
                load_quotes(self.paths[0], self.paths[1])
        metadata["source_export_status"] = "completed"
        self.paths[1].write_bytes(json_bytes(metadata))
        self.assertGreater(len(load_quotes(self.paths[0], self.paths[1]).quotes), 0)


if __name__ == "__main__":
    unittest.main()
