"""New projection ceilings apply to every quote consumer."""
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from trading_intelligence.common import DataError, json_bytes, load_json
from scalper_research.cli import demo_inputs
from scalper_research.learning_pipeline import run_learning
from scalper_research.market import load_quotes, validate_quote_execution
from scalper_research.paper import start_paper
from scalper_research.pipeline import run_research


class TickExecutionGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.paths = demo_inputs(self.root/"inputs")
        self.metadata = load_json(self.paths[1].read_bytes())
        self.metadata["projection_required_max_quote_gap_ms"] = 100
        self.paths[1].write_bytes(json_bytes(self.metadata))

    def test_every_consumer_rejects_wider_projection_gap(self):
        for name, operation in (("replay", run_research), ("learning", run_learning)):
            with self.subTest(consumer=name):
                result = operation(*self.paths, self.root/name)
                self.assertEqual(result["status"], "failed")
                self.assertIn("RECONSTRUCTED_QUOTE_GAP_POLICY_MISMATCH", result["errors"])
                if name == "learning":
                    self.assertFalse(result["model_fitted"])
        with self.assertRaisesRegex(DataError, "RECONSTRUCTED_QUOTE_GAP_POLICY_MISMATCH"):
            start_paper(*self.paths, self.root/"paper")

    def test_minimum_of_every_inherited_policy_controls_execution(self):
        for metadata in ({"wse_required_max_quote_gap_ms": 1000, "projection_required_max_quote_gap_ms": 100},
                         {"wse_required_max_quote_gap_ms": 50, "projection_required_max_quote_gap_ms": 100}):
            with self.subTest(metadata=metadata):
                cap = min(metadata.values())
                validate_quote_execution(metadata, SimpleNamespace(max_quote_gap_ms=cap))
                with self.assertRaisesRegex(DataError, "RECONSTRUCTED_QUOTE_GAP_POLICY_MISMATCH"):
                    validate_quote_execution(metadata, SimpleNamespace(max_quote_gap_ms=cap+1))

    def test_projection_policy_is_bounded_exact_integer(self):
        for value in (True, "100", None, 0, 1001):
            with self.subTest(value=value):
                self.metadata["projection_required_max_quote_gap_ms"] = value
                self.paths[1].write_bytes(json_bytes(self.metadata))
                with self.assertRaisesRegex(DataError, "MARKET_RECONSTRUCTION_GAP_POLICY_INVALID"):
                    load_quotes(self.paths[0], self.paths[1])
                with self.assertRaisesRegex(DataError, "MARKET_RECONSTRUCTION_GAP_POLICY_INVALID"):
                    validate_quote_execution(self.metadata, SimpleNamespace(max_quote_gap_ms=100))

    def test_derived_assumptions_survive_loading_without_unreviewed_labels(self):
        caveats = ["SOURCE_EQUAL_MILLISECOND_ORDER_UNVERIFIED", "NATIVE_TIMESTAMP_NOT_RECEIVE_CLOCK",
                   "DERIVED_BUCKET_END_QUOTE_NOT_NATIVE_TICK", "NO_EMPTY_BUCKET_FORWARD_FILL",
                   "EVENT_TIME_TIMER_ASSUMED"]
        self.metadata["quality_flags"] = [*caveats, "UNREVIEWED_LABEL"]
        self.paths[1].write_bytes(json_bytes(self.metadata))
        flags = load_quotes(self.paths[0], self.paths[1]).quality_flags
        for caveat in caveats:
            self.assertIn(caveat, flags)
        self.assertNotIn("UNREVIEWED_LABEL", flags)
        self.assertNotIn("EQUAL_TIMESTAMP_ORDER_UNVERIFIED", flags)


if __name__ == "__main__":
    unittest.main()
