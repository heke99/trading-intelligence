"""Offline cost-stress checks; every quote/model is generated in this test."""
from decimal import Decimal, localcontext
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from trading_intelligence.common import DataError, json_bytes, load_json, sha256
from scalper_research.engine import replay
from scalper_research.evaluation import _scenario_documents, run_cost_stress
from scalper_research.learning import FilteredStrategy
from scalper_research.learning_pipeline import run_learning
from tests.test_learning_pipeline import fictional_inputs


class CostStressTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.paths = fictional_inputs(self.root/"inputs")
        self.learned = run_learning(*self.paths, self.root/"learning")
        self.assertEqual(self.learned["status"], "completed", self.learned["errors"])
        self.model = Path(self.learned["model"])
        self.threshold = self.learned["selected_threshold"]
        self.out = self.root/"stress"

    def tearDown(self):
        self.temporary.cleanup()

    def stress(self, *, model=None, threshold=None):
        with patch("urllib.request.urlopen", side_effect=AssertionError("offline synthetic test")):
            return run_cost_stress(*self.paths, model or self.model,
                                   self.threshold if threshold is None else threshold, self.out)

    def report(self, result, name):
        return load_json((Path(result["manifest"]).parent/(name+".json")).read_bytes())

    def test_five_fixed_scenarios_and_two_benchmarks_reuse_frozen_model_without_fitting(self):
        original = self.model.read_bytes()
        development = Path(self.learned["development_model"]).read_bytes()
        with patch("scalper_research.learning.fit", side_effect=AssertionError("never fit during stress")), \
             patch("scalper_research.learning_pipeline.fit", side_effect=AssertionError("never refit during stress")):
            result = self.stress()
        self.assertEqual(result["status"], "completed", result["errors"])
        self.assertEqual(list(result["scenario_results"]), ["base", "fee_2x", "slippage_2x", "latency_2x", "combined_2x"])
        self.assertEqual(set(result["benchmarks"]), {"no_model", "reject_all"})
        self.assertEqual(self.model.read_bytes(), original)
        self.assertEqual(Path(self.learned["development_model"]).read_bytes(), development)
        for name in result["scenario_results"]:
            report = self.report(result, name)
            self.assertEqual(report["model_content_sha256"], result["model_content_sha256"])
            self.assertEqual(report["actual_filter_threshold"], str(float(self.threshold)))
            self.assertFalse(report["training_performed"])
            self.assertEqual(report["source_quality_flags"], result["source_quality_flags"])
        self.assertEqual(result["quote_currency"], "USD")
        self.assertFalse(result["cash_balance_or_fx_conversion_applied"])

    def test_cost_units_scale_exactly_and_fee_increase_matches_per_side_per_unit_cost(self):
        result = self.stress()
        self.assertEqual(result["status"], "completed", result["errors"])
        base = result["scenario_results"]["base"]
        fee = result["scenario_results"]["fee_2x"]
        self.assertEqual(base["closed_trade_count"], fee["closed_trade_count"])
        quantity = Decimal(base["execution"]["quantity"])
        commission = Decimal(base["execution"]["commission_per_unit_per_side"])
        expected_extra = Decimal(base["closed_trade_count"])*quantity*commission*2
        self.assertEqual(Decimal(base["realized_net_pnl_currency"])-Decimal(fee["realized_net_pnl_currency"]), expected_extra)
        combined = result["scenario_results"]["combined_2x"]["execution"]
        self.assertEqual(Decimal(combined["slippage_price"]), Decimal(base["execution"]["slippage_price"])*2)
        self.assertEqual(combined["latency_ms"], base["execution"]["latency_ms"]*2)

    def test_prior_quotes_are_excluded_without_warmup_and_each_run_has_independent_state(self):
        calls = []
        config = json.loads(self.paths[2].read_text())
        cutoff = config["evaluation"]["validation_end_msc"]
        def traced(quotes, strategy, execution):
            calls.append((quotes, strategy))
            self.assertGreaterEqual(quotes[0].time_msc, cutoff)
            self.assertTrue(all(quote.time_msc >= cutoff for quote in quotes))
            if isinstance(strategy, FilteredStrategy):
                self.assertEqual(strategy.snapshots, {})
            return replay(quotes, strategy, execution)
        with patch("scalper_research.engine.replay", side_effect=traced):
            result = self.stress()
        self.assertEqual(result["status"], "completed", result["errors"])
        self.assertEqual(result["quote_count"], 603)
        self.assertEqual(result["excluded_earlier_quote_count"], 1206)
        self.assertEqual(len(calls), 7)
        self.assertEqual(len({id(strategy) for _, strategy in calls}), 7)
        self.assertTrue(result["threshold_selection_verified"])

    def test_reject_all_is_zero_trade_control_and_baseline_does_not_use_model(self):
        result = self.stress()
        rejected = self.report(result, "benchmark_reject_all")
        self.assertEqual(rejected["entered_trade_count"], 0)
        self.assertEqual(rejected["closed_trade_count"], 0)
        self.assertEqual(Decimal(rejected["ending_net_equity_currency"]), 0)
        self.assertEqual(rejected["actual_filter_threshold"], "1.0")
        self.assertTrue(rejected["filter_decisions"])
        self.assertTrue(all(decision["accepted"] is False for decision in rejected["filter_decisions"]))
        baseline = self.report(result, "benchmark_no_model")
        self.assertFalse(baseline["model_used"])
        self.assertIsNone(baseline["actual_filter_threshold"])

    def test_synthetic_stress_never_accepts_market_or_broker_readiness(self):
        result = self.stress()
        self.assertEqual(result["evaluation_status"], "synthetic_behavior_check")
        summary = load_json(Path(result["summary"]).read_bytes())
        for document in (result, summary):
            for key in ("training_ready", "full_history_verified", "trading_enabled", "replay_accepted",
                        "forward_verified", "broker_connected", "broker_demo_verified", "market_history_verified",
                        "model_trained_on_real_market", "training_performed"):
                self.assertIs(document[key], False)
        self.assertEqual(summary["acceptance"], "unaccepted")
        self.assertFalse(summary["parameter_selection_performed"])

    def test_unbound_threshold_and_config_fail_before_replay(self):
        bad_threshold = self.stress(threshold=self.threshold+0.01)
        self.assertEqual(bad_threshold["errors"], ["STRESS_MODEL_THRESHOLD_SELECTION_MISMATCH"])
        config = json.loads(self.paths[2].read_text())
        config["execution"]["quantity"] = "2000"
        self.paths[2].write_bytes(json_bytes(config))
        mismatch = self.stress()
        self.assertEqual(mismatch["errors"], ["STRESS_MODEL_CONFIG_MISMATCH"])
        self.assertIsNone(mismatch["summary"])
        self.assertEqual(len(mismatch["raw_files"]), 4)

    def test_selected_model_requires_unchanged_receipt_and_original_fitted_weights(self):
        receipt = self.model.parent/"selection.json"
        original_receipt = receipt.read_bytes()
        receipt.write_bytes(original_receipt+b" ")
        changed = self.stress()
        self.assertEqual(changed["errors"], ["STRESS_MODEL_SELECTION_RECEIPT_MISMATCH"])
        receipt.write_bytes(original_receipt)
        model = load_json(self.model.read_bytes())
        model["coefficients"][0] = str(Decimal(model["coefficients"][0])+1)
        model["model_sha256"] = sha256(json_bytes({key: value for key, value in model.items() if key != "model_sha256"}))
        self.model.write_bytes(json_bytes(model))
        tampered = self.stress()
        self.assertEqual(tampered["errors"], ["STRESS_MODEL_SELECTION_WEIGHT_MISMATCH"])

    def test_selected_model_without_receipt_fails_with_archived_inputs(self):
        (self.model.parent/"selection.json").unlink()
        result = self.stress()
        self.assertEqual(result["errors"], ["STRESS_MODEL_SELECTION_RECEIPT_REQUIRED"])
        self.assertEqual(result["status"], "failed")
        for item in result["raw_files"]:
            self.assertEqual(sha256((self.out/item["path"]).read_bytes()), item["sha256"])

    def test_pre_fit_or_pre_selection_quotes_cannot_be_evaluated_as_holdout(self):
        lines = self.paths[0].read_bytes().splitlines(keepends=True)
        self.paths[0].write_bytes(b"".join(lines[:604]))
        result = self.stress()
        self.assertEqual(result["errors"], ["STRESS_HOLDOUT_TOO_SHORT_OR_PRECEDES_FIT_OR_SELECTION"])
        self.assertEqual(result["status"], "failed")

    def test_explicit_development_model_threshold_is_unverified_and_uses_fit_cutoff(self):
        result = self.stress(model=Path(self.learned["development_model"]), threshold=0.5)
        self.assertEqual(result["status"], "completed", result["errors"])
        self.assertFalse(result["threshold_selection_verified"])
        self.assertEqual(result["excluded_earlier_quote_count"], 603)
        self.assertIn("MANUAL_THRESHOLD_SELECTION_NOT_VERIFIED", result["blockers"])
        self.assertEqual(result["scenario_results"]["base"]["quality_flags"], ["GAP_PRICE_PATH_UNKNOWN"])

    def test_unasserted_replay_rights_fail_without_inventing_permission(self):
        metadata = json.loads(self.paths[1].read_text())
        metadata.update(data_origin="user_supplied_unverified", usage_rights="not_verified")
        self.paths[1].write_bytes(json_bytes(metadata))
        result = self.stress()
        self.assertEqual(result["errors"], ["STRESS_USAGE_RIGHTS_NOT_ASSERTED"])

    def test_reconstructed_quote_gap_ceiling_cannot_be_widened_by_execution_config(self):
        metadata = json.loads(self.paths[1].read_text())
        metadata["wse_required_max_quote_gap_ms"] = 500
        self.paths[1].write_bytes(json_bytes(metadata))
        result = self.stress()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["errors"], ["RECONSTRUCTED_QUOTE_GAP_POLICY_MISMATCH"])

    def test_scenario_bounds_raise_instead_of_capping_and_precision_is_not_ambient(self):
        config = json.loads(self.paths[2].read_text())
        config["execution"]["latency_ms"] = 30001
        with self.assertRaisesRegex(DataError, "RESEARCH_INTEGER_RANGE:latency_ms"):
            _scenario_documents(config)
        config["execution"]["latency_ms"] = 100
        config["execution"]["commission_per_unit_per_side"] = "0.123456789012"
        with localcontext() as context:
            context.prec = 3
            scenarios = dict(_scenario_documents(config))
        self.assertEqual(scenarios["fee_2x"]["execution"]["commission_per_unit_per_side"], "0.246913578024")

    def test_summary_has_same_nonnull_completion_clock_as_manifest(self):
        result = self.stress()
        summary = load_json(Path(result["summary"]).read_bytes())
        self.assertIsNotNone(summary["finished_at_utc"])
        self.assertEqual(summary["finished_at_utc"], result["finished_at_utc"])


if __name__ == "__main__":
    unittest.main()
