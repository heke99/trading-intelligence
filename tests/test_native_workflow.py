"""Native HDF workflow tests; only explicitly generated fictional order data."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from trading_intelligence.common import DataError, json_bytes, load_json, sha256
from scalper_research.learning import fit, validate_model
from scalper_research.market import load_quotes, validate_quote_execution
from scalper_research.native_workflow import _fictional_hdf, run_native_demo, run_wse_benchmark, write_wse_plan
from scalper_research.pipeline import parse_config

_HDF_AVAILABLE = importlib.util.find_spec("h5py") is not None


class NativePlanTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_fixed_instrument_license_hash_units_and_preregistered_clocks(self):
        with patch("scalper_research.acquire._open_source", side_effect=AssertionError("plan never acquires")):
            plan = write_wse_plan(self.root)
        self.assertEqual(plan["status"], "completed")
        self.assertFalse(plan["network_used"])
        self.assertFalse(plan["actual_source_acquired"])
        self.assertFalse(plan["model_fitted"])
        spec = load_json(Path(plan["spec_path"]).read_bytes())
        contract = load_json(Path(plan["source_contract_path"]).read_bytes())
        config_raw = Path(plan["config_path"]).read_bytes()
        config, _, execution, cutoffs = parse_config(config_raw)
        self.assertEqual(contract["expected_bytes"], 152759953)
        self.assertEqual(spec["expected_sha256"], contract["expected_sha256"])
        self.assertEqual(plan["expected_source_sha256"], contract["expected_sha256"])
        self.assertEqual(contract["license"], "CC-BY-4.0")
        self.assertIn("Marszałek", contract["attribution"])
        self.assertIn("10.17632/3g4mhdp899.1", spec["source"]["attribution"])
        self.assertEqual(spec["source"]["training_usage_rights"], "user_asserted_permitted")
        self.assertIn(contract["source_record_url"], spec["source"]["training_rights_evidence"])
        self.assertEqual(spec["symbol_idx"], 11322)
        self.assertEqual(execution.symbol, "PEKAO")
        self.assertEqual(execution.price_currency, "PLN")
        self.assertEqual(config["execution"]["quantity"], "1")
        self.assertEqual(config["execution"]["contract_multiplier"], "1")
        self.assertEqual(config["execution"]["commission_per_unit_per_side"], "0.02")
        self.assertEqual(config["strategy"]["stop_distance"], "0.10")
        self.assertEqual(config["strategy"]["target_distance"], "0.20")
        self.assertEqual(cutoffs, (1483401600000, 1483488000000))
        self.assertEqual(spec["days"], ["20170102", "20170103", "20170104"])
        self.assertEqual(spec["sample_period_ms"], execution.max_quote_gap_ms)
        for key in ("training_ready", "full_history_verified", "trading_enabled", "broker_connected",
                    "forward_verified", "market_history_verified", "model_trained_on_real_market", "expert_trade_history"):
            self.assertIs(plan[key], False)

    def test_plan_repeats_identically_and_does_not_overwrite_changed_research_config(self):
        first = write_wse_plan(self.root)
        original = Path(first["config_path"]).read_bytes()
        second = write_wse_plan(self.root)
        self.assertEqual(first["file_sha256"], second["file_sha256"])
        self.assertEqual(Path(first["config_path"]).read_bytes(), original)
        modified = json.loads(original)
        modified["execution"]["quantity"] = "3"
        Path(first["config_path"]).write_bytes(json_bytes(modified))
        with self.assertRaisesRegex(DataError, "WSE_PLAN_EXISTING_FILE_CONFLICT"):
            write_wse_plan(self.root)
        self.assertEqual(json.loads(Path(first["config_path"]).read_text())["execution"]["quantity"], "3")

    def test_plan_does_not_claim_to_precede_unknown_acquisition_or_external_visibility(self):
        plan = write_wse_plan(self.root)
        self.assertIsNot(plan.get("research_config_frozen_before_acquisition"), True)
        self.assertIsNot(plan["plan_before_any_successful_data_import"], True)
        self.assertIs(plan["frozen_current_plan_for_future_run"], True)
        self.assertEqual(plan["external_data_visibility"], "unknown")

    def test_missing_optional_hdf_parser_has_finished_failed_receipt(self):
        out = self.root/"native"
        with patch.dict("sys.modules", {"h5py": None}):
            result = run_native_demo(out)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["errors"], ["NATIVE_DEMO_OPTIONAL_H5PY_REQUIRED"])
        self.assertIsNotNone(result["finished_at_utc"])
        self.assertFalse(result["actual_source_acquired"])
        self.assertFalse(result["model_fitted"])
        self.assertEqual(load_json(Path(result["manifest"]).read_bytes())["status"], "failed")

    def test_benchmark_requires_local_original_and_preserves_finished_failure_summary(self):
        plan = write_wse_plan(self.root/"plan")
        result = run_wse_benchmark(Path("https://example.invalid/source.h5"), Path(plan["spec_path"]),
                                   Path(plan["config_path"]), self.root/"benchmark")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["errors"], ["WSE_BENCHMARK_LOCAL_FILE_REQUIRED"])
        self.assertEqual(len(result["raw_files"]), 2)
        self.assertIsNotNone(result["finished_at_utc"])
        self.assertFalse(result["acquisition_performed"])
        self.assertFalse(result["network_used"])
        self.assertEqual(load_json(Path(result["summary"]).read_bytes()), load_json(Path(result["manifest"]).read_bytes()))

    def test_failed_native_import_preserves_child_reason_and_does_not_fit(self):
        paths = (self.root/"fixture.h5", self.root/"spec.json", self.root/"config.json")
        for path in paths:
            path.write_bytes(b"fictional-stage-fixture")
        child = {"status": "failed", "errors": ["FICTIONAL_NATIVE_FAILURE"], "manifest_path": "fictional-stage"}
        with patch("scalper_research.native_workflow._fictional_hdf", return_value=paths), \
             patch("scalper_research.wse.import_wse", return_value=child), \
             patch("scalper_research.learning_pipeline.run_learning", side_effect=AssertionError("failed source must not fit")):
            result = run_native_demo(self.root/"out")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["errors"], ["NATIVE_DEMO_IMPORT_FAILED"])
        self.assertEqual(result["stages"]["native_import"]["errors"], ["FICTIONAL_NATIVE_FAILURE"])
        self.assertFalse(result["model_fitted"])
        self.assertIsNotNone(result["finished_at_utc"])


@unittest.skipUnless(_HDF_AVAILABLE, "optional h5py is absent; native parser integration is covered when installed")
class NativeDemoTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.out = self.root/"native"

    def tearDown(self):
        self.temporary.cleanup()

    def run_demo(self):
        with patch("scalper_research.acquire._open_source", side_effect=AssertionError("fictional demo never downloads")), \
             patch("urllib.request.urlopen", side_effect=AssertionError("offline synthetic test")):
            result = run_native_demo(self.out)
        self.assertEqual(result["status"], "completed", result["errors"])
        return result

    def test_actual_hdf_parser_generates_causal_quotes_and_preserves_raw_nanoseconds(self):
        result = self.run_demo()
        imported = result["stages"]["native_import"]
        dataset = load_quotes(Path(imported["output_csv"]), Path(imported["output_metadata"]))
        self.assertEqual(imported["native_event_count"], 3*(3+603*2))
        self.assertEqual(imported["quote_count"], 3*602)
        self.assertEqual(dataset.metadata["symbol"], "PEKAO")
        self.assertEqual(dataset.metadata["price_currency"], "PLN")
        self.assertEqual(dataset.metadata["data_origin"], "synthetic_fixture")
        self.assertEqual(dataset.metadata["source_native_timestamp_basis"], "utc_epoch_nanoseconds")
        self.assertEqual(dataset.metadata["source_hdf_sha256"], result["fixture"]["hdf_sha256"])
        self.assertEqual(dataset.metadata["source_hdf_sha256"], sha256(Path(result["fixture"]["hdf"]).read_bytes()))
        evidence = [json.loads(line) for line in Path(imported["quote_evidence_path"]).read_text().splitlines()]
        self.assertEqual(len(evidence), len(dataset.quotes))
        self.assertTrue(all(row["latest_event_time_ns"] < row["boundary_time_ns"] for row in evidence))
        self.assertTrue(all(row["boundary_time_ns"] == row["time_msc"]*1000000 for row in evidence))
        self.assertTrue(all(row["fill_evidence"] is False for row in evidence))
        native = [json.loads(line) for line in Path(imported["native_events_path"]).read_text().splitlines()]
        self.assertTrue(all(row["expert_trade"] is False and row["execution_label"] is False for row in native))
        self.assertTrue(all(row["time_ns"] == row["native_fields"]["time"] for row in native))
        self.assertFalse(dataset.metadata["matching_phase_verified"])
        self.assertFalse(dataset.metadata["fills_or_queue_priority_identified"])

    def test_native_learning_fits_once_and_stress_preserves_frozen_development_weights(self):
        with patch("scalper_research.learning_pipeline.fit", wraps=fit) as fitting:
            result = self.run_demo()
        self.assertEqual(fitting.call_count, 1)
        learned, stressed = result["stages"]["learning"], result["stages"]["cost_stress"]
        development = load_json(Path(learned["development_model"]).read_bytes())
        selected = load_json(Path(learned["model"]).read_bytes())
        validate_model(development)
        validate_model(selected)
        self.assertEqual(development["coefficients"], selected["coefficients"])
        self.assertEqual(development["bias"], selected["bias"])
        self.assertGreaterEqual(learned["training_positive_count"], 5)
        self.assertGreaterEqual(learned["training_negative_count"], 5)
        self.assertTrue(result["model_fitted"])
        self.assertEqual(stressed["model_content_sha256"], selected["model_sha256"])
        self.assertTrue(stressed["threshold_selection_verified"])
        self.assertEqual(stressed["quote_count"], 602)
        self.assertEqual(stressed["excluded_earlier_quote_count"], 1204)
        self.assertFalse(stressed["training_performed"])
        self.assertEqual(len(stressed["scenario_results"]), 5)
        for document in (result, learned, stressed):
            for key in ("training_ready", "full_history_verified", "trading_enabled", "forward_verified", "model_trained_on_real_market"):
                self.assertIs(document[key], False)

    def test_derived_gap_ceiling_and_no_bridge_to_invalid_buckets(self):
        result = self.run_demo()
        imported = result["stages"]["native_import"]
        metadata = load_json(Path(imported["output_metadata"]).read_bytes())
        config_raw = Path(result["fixture"]["config"]).read_bytes()
        _, _, execution, _ = parse_config(config_raw)
        validate_quote_execution(metadata, execution)
        self.assertEqual(metadata["wse_required_max_quote_gap_ms"], 1000)
        changed = load_json(config_raw)
        changed["execution"]["max_quote_gap_ms"] = 2000
        _, _, widened, _ = parse_config(json_bytes(changed))
        with self.assertRaisesRegex(DataError, "RECONSTRUCTED_QUOTE_GAP_POLICY_MISMATCH"):
            validate_quote_execution(metadata, widened)

    def test_existing_demo_evidence_is_not_overwritten_by_repeat(self):
        first = self.run_demo()
        original = Path(first["manifest"]).read_bytes()
        with self.assertRaisesRegex(DataError, "NATIVE_DEMO_REQUIRES_FRESH_OUTPUT_DIRECTORY"):
            run_native_demo(self.out)
        self.assertEqual(Path(first["manifest"]).read_bytes(), original)


@unittest.skipUnless(_HDF_AVAILABLE, "optional h5py is absent; native benchmark integration is covered when installed")
class NativeBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.paths = _fictional_hdf(self.root/"inputs")
        self.out = self.root/"benchmark"

    def tearDown(self):
        self.temporary.cleanup()

    def benchmark(self):
        with patch("scalper_research.acquire._open_source", side_effect=AssertionError("local benchmark never acquires")), \
             patch("urllib.request.urlopen", side_effect=AssertionError("offline synthetic test")):
            return run_wse_benchmark(*self.paths, self.out)

    def test_local_native_benchmark_uses_selected_model_only_and_fits_once(self):
        from scalper_research.evaluation import run_cost_stress
        with patch("scalper_research.learning_pipeline.fit", wraps=fit) as fitting, \
             patch("scalper_research.evaluation.run_cost_stress", wraps=run_cost_stress) as stressing:
            result = self.benchmark()
        self.assertEqual(result["status"], "completed", result["errors"])
        self.assertEqual(fitting.call_count, 1)
        self.assertEqual(stressing.call_count, 1)
        learned = result["stages"]["learning"]
        self.assertEqual(stressing.call_args.args[3], Path(learned["model"]))
        self.assertNotEqual(stressing.call_args.args[3], Path(learned["development_model"]))
        self.assertEqual(stressing.call_args.args[4], learned["selected_threshold"])
        self.assertTrue(result["source_history_imported"])
        self.assertTrue(result["source_hash_verified_against_supplied_spec"])
        self.assertTrue(result["model_fitted"])
        self.assertEqual(result["source_data_origin"], "synthetic_fixture")
        self.assertEqual(result["evaluation_status"], "synthetic_behavior_check")
        self.assertEqual(result["source_refs"]["source_hdf_sha256"], sha256(self.paths[0].read_bytes()))
        self.assertEqual(result["source_refs"]["selected_model_path"], learned["model"])
        summary = load_json(Path(result["summary"]).read_bytes())
        self.assertEqual(summary["finished_at_utc"], result["finished_at_utc"])
        self.assertEqual(summary, load_json(Path(result["manifest"]).read_bytes()))
        for key in ("training_ready", "full_history_verified", "trading_enabled", "broker_connected",
                    "forward_verified", "market_history_verified", "model_trained_on_real_market", "expert_trade_history"):
            self.assertIs(result[key], False)

    def test_config_and_spec_are_frozen_before_native_import_even_if_original_files_change(self):
        from scalper_research.wse import import_wse
        initial_config = self.paths[2].read_bytes()
        initial_spec = self.paths[1].read_bytes()
        def import_and_modify(file, archived_spec, out):
            self.assertNotEqual(archived_spec, self.paths[1])
            self.assertEqual(Path(archived_spec).read_bytes(), initial_spec)
            result = import_wse(file, archived_spec, out)
            changed_config = load_json(initial_config)
            changed_config["execution"]["quantity"] = "7"
            self.paths[2].write_bytes(json_bytes(changed_config))
            changed_spec = load_json(initial_spec)
            changed_spec["expected_sha256"] = "0"*64
            self.paths[1].write_bytes(json_bytes(changed_spec))
            return result
        with patch("scalper_research.wse.import_wse", side_effect=import_and_modify):
            result = self.benchmark()
        self.assertEqual(result["status"], "completed", result["errors"])
        self.assertEqual(result["source_refs"]["config_sha256"], sha256(initial_config))
        self.assertEqual(Path(result["source_refs"]["frozen_config_path"]).read_bytes(), initial_config)
        self.assertEqual(Path(result["source_refs"]["frozen_spec_path"]).read_bytes(), initial_spec)
        self.assertNotEqual(self.paths[2].read_bytes(), initial_config)
        self.assertEqual(result["stages"]["cost_stress"]["config_sha256"], sha256(initial_config))

    def test_failed_native_hash_stage_stops_before_learning_and_stress(self):
        spec = load_json(self.paths[1].read_bytes())
        spec["expected_sha256"] = "0"*64
        self.paths[1].write_bytes(json_bytes(spec))
        with patch("scalper_research.learning_pipeline.run_learning", side_effect=AssertionError("failed import must stop")), \
             patch("scalper_research.evaluation.run_cost_stress", side_effect=AssertionError("failed import must stop")):
            result = self.benchmark()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["errors"], ["WSE_BENCHMARK_IMPORT_FAILED"])
        self.assertEqual(result["stages"]["native_import"]["errors"], ["WSE_SOURCE_SHA256_MISMATCH"])
        self.assertFalse(result["source_history_imported"])
        self.assertFalse(result["model_fitted"])
        self.assertEqual(set(result["stages"]), {"native_import"})
        self.assertIsNotNone(result["finished_at_utc"])
        self.assertEqual(load_json(Path(result["summary"]).read_bytes())["status"], "failed")

    def test_completed_fit_without_eligible_frozen_selection_does_not_run_cost_stress(self):
        blocked = {"status": "completed", "model_fitted": True, "selected_threshold": None, "model": None,
                   "selection_status": "blocked_no_eligible_validation_candidate", "errors": []}
        with patch("scalper_research.learning_pipeline.run_learning", return_value=blocked), \
             patch("scalper_research.evaluation.run_cost_stress", side_effect=AssertionError("no selected policy")):
            result = self.benchmark()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["errors"], ["WSE_BENCHMARK_FROZEN_SELECTION_UNAVAILABLE"])
        self.assertTrue(result["model_fitted"])
        self.assertNotIn("cost_stress", result["stages"])
        self.assertEqual(result["stages"]["learning"]["selection_status"], "blocked_no_eligible_validation_candidate")


if __name__ == "__main__":
    unittest.main()
