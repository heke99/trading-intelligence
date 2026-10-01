"""Offline orchestration checks using an explicitly fictional quote generator."""
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from trading_intelligence.common import DataError, json_bytes, load_json, sha256
from scalper_research.engine import replay
from scalper_research.learning import CaptureStrategy, FilteredStrategy, fit, validate_model
from scalper_research.learning_pipeline import learning_status, run_learning


def fictional_inputs(directory):
    """Three generated UTC sessions; source assertions below are test fixtures."""
    directory.mkdir()
    base = 1704186000000
    lines = ["time_msc,bid,ask"]
    for day in range(3):
        seed = 147 + day * 23
        offset = 0
        for tick in range(603):
            seed = (1664525 * seed + 1013904223) % (2 ** 32)
            if tick < 600:
                regime = (tick // 75) % 4
                offset += int(seed % 11) - 5 + (2 if regime == 0 else -2 if regime == 1 else 0)
            mid = Decimal("1.1") + Decimal(offset) * Decimal("0.00001")
            lines.append(f"{base+day*86400000+tick*1000},{mid-Decimal('0.00001')},{mid+Decimal('0.00001')}")
    metadata = {"schema_version": 1, "source_id": "fictional_orchestration_fixture", "symbol": "EURUSD",
                "price_currency": "USD", "timestamp_basis": "utc_epoch_milliseconds",
                "timezone_evidence": "fictional generator explicitly uses UTC epoch milliseconds",
                "data_origin": "synthetic_fixture", "usage_rights": "synthetic_only"}
    config = {"schema_version": 1, "basis": "independent_rule_hypothesis",
              "strategy": {"lookback_quotes": 3, "breakout_buffer": "0.000005", "stop_distance": "0.00004",
                           "target_distance": "0.00006", "max_hold_ms": 5000,
                           "session_start_minute_utc": 540, "session_end_minute_utc": 550, "cooldown_ms": 1000},
              "execution": {"symbol": "EURUSD", "quantity": "1000", "contract_multiplier": "1", "price_currency": "USD",
                            "commission_per_unit_per_side": "0.000001", "slippage_price": "0.000001", "latency_ms": 100,
                            "max_quote_gap_ms": 1000, "max_entry_spread": "0.00004", "max_loss_currency": "1000", "max_trades": 1000},
              "evaluation": {"development_end_msc": base+86400000, "validation_end_msc": base+2*86400000}}
    paths = (directory/"quotes.synthetic.csv", directory/"metadata.synthetic.json", directory/"config.synthetic.json")
    paths[0].write_text("\n".join(lines)+"\n")
    paths[1].write_bytes(json_bytes(metadata))
    paths[2].write_bytes(json_bytes(config))
    return paths


class LearningPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.paths = fictional_inputs(self.root/"inputs")
        self.out = self.root/"out"

    def tearDown(self):
        self.temporary.cleanup()

    def run_learning(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("offline synthetic test")):
            return run_learning(*self.paths, self.out)

    def metadata(self, **changes):
        value = json.loads(self.paths[1].read_text())
        value.update(changes)
        self.paths[1].write_bytes(json_bytes(value))

    def config(self):
        return json.loads(self.paths[2].read_text())

    def read_model(self, result, key="development_model"):
        return load_json(Path(result[key]).read_bytes())

    def test_fit_synthetic_closed_outcomes_and_preserve_false_acceptance_gates(self):
        result = self.run_learning()
        self.assertEqual(result["status"], "completed", result["errors"])
        self.assertTrue(result["model_fitted"])
        self.assertEqual(result["evaluation_status"], "synthetic_behavior_check")
        self.assertGreaterEqual(result["training_row_count"], 20)
        self.assertGreaterEqual(result["training_positive_count"], 5)
        self.assertGreaterEqual(result["training_negative_count"], 5)
        summary = load_json(Path(result["summary"]).read_bytes())
        for document in (result, summary):
            for key in ("training_ready", "full_history_verified", "trading_enabled", "replay_accepted",
                        "forward_verified", "market_history_verified", "model_trained_on_real_market"):
                self.assertIs(document[key], False)
        original = self.read_model(result)
        selected = self.read_model(result, "model")
        validate_model(original)
        validate_model(selected)
        self.assertNotEqual(original["model_sha256"], selected["model_sha256"])
        for key in ("coefficients", "bias", "fit_summary", "fit_parameters"):
            self.assertEqual(original[key], selected[key])
        for candidate in result["validation_candidates"]:
            report = load_json((Path(result["manifest"]).parent/candidate["report"]).read_bytes())
            self.assertEqual(report["model_sha256"], original["model_sha256"])
        self.assertEqual(summary["selected_test"]["model_sha256"], selected["model_sha256"])
        self.assertEqual(original["provenance"]["training_partition"], "development_only")
        self.assertEqual(learning_status(self.out)["run_id"], result["run_id"])

    def test_future_price_mutation_cannot_change_fitted_parameters_or_training_rows(self):
        first = self.run_learning()
        first_model = self.read_model(first)
        first_rows = (Path(first["manifest"]).parent/"training_rows.jsonl").read_bytes()
        dev_end = self.config()["evaluation"]["development_end_msc"]
        lines = self.paths[0].read_text().splitlines()
        for index in range(1, len(lines)):
            when, bid, ask = lines[index].split(",")
            if int(when) >= dev_end:
                price = Decimal("2") + Decimal((index*31)%17)*Decimal("0.00001")
                lines[index] = f"{when},{price},{price+Decimal('0.00002')}"
        self.paths[0].write_text("\n".join(lines)+"\n")
        second = self.run_learning()
        self.assertEqual(second["status"], "completed", second["errors"])
        second_model = self.read_model(second)
        for key in ("coefficients", "bias", "fit_summary"):
            self.assertEqual(first_model[key], second_model[key])
        self.assertEqual(first_rows, (Path(second["manifest"]).parent/"training_rows.jsonl").read_bytes())
        self.assertNotEqual(first_model["provenance"]["raw_quotes_sha256"], second_model["provenance"]["raw_quotes_sha256"])

    def test_test_price_mutation_cannot_change_validation_selection(self):
        first = self.run_learning()
        boundary = self.config()["evaluation"]["validation_end_msc"]
        lines = self.paths[0].read_text().splitlines()
        for index in range(1, len(lines)):
            when, _, _ = lines[index].split(",")
            if int(when) >= boundary:
                price = Decimal("5") + Decimal(index%2)*Decimal("0.0002")
                lines[index] = f"{when},{price},{price+Decimal('0.00002')}"
        self.paths[0].write_text("\n".join(lines)+"\n")
        second = self.run_learning()
        self.assertEqual(first["selected_threshold"], second["selected_threshold"])
        self.assertEqual(first["validation_candidates"], second["validation_candidates"])

    def test_replay_rights_alone_do_not_admit_training_and_inputs_remain_archived(self):
        self.metadata(data_origin="user_supplied_unverified", usage_rights="user_asserted_permitted",
                      rights_evidence="fictional replay assertion for admission test")
        result = self.run_learning()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["errors"], ["LEARNING_TRAINING_USAGE_RIGHTS_NOT_ASSERTED"])
        self.assertFalse(result["model_fitted"])
        self.assertEqual(len(result["raw_files"]), 3)
        for item in result["raw_files"]:
            self.assertEqual(sha256((self.out/item["path"]).read_bytes()), item["sha256"])

    def test_training_assertion_requires_separate_evidence_and_never_verifies_market(self):
        self.metadata(data_origin="user_supplied_unverified", usage_rights="user_asserted_permitted",
                      rights_evidence="fictional replay permission", training_usage_rights="user_asserted_permitted",
                      training_rights_evidence=" ")
        bad = self.run_learning()
        self.assertEqual(bad["errors"], ["LEARNING_TRAINING_RIGHTS_EVIDENCE_REQUIRED"])
        self.metadata(training_rights_evidence="fictional training assertion; all quote values remain generated")
        good = self.run_learning()
        self.assertEqual(good["status"], "completed", good["errors"])
        self.assertTrue(good["model_fitted_on_user_supplied_quotes"])
        self.assertFalse(good["model_trained_on_real_market"])
        self.assertFalse(good["market_history_verified"])
        self.assertEqual(good["evaluation_status"], "unaccepted_market_research")

    def test_deficient_labels_fail_without_fabricating_or_fitting_examples(self):
        config = self.config()
        config["execution"]["max_trades"] = 2
        self.paths[2].write_bytes(json_bytes(config))
        result = self.run_learning()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["errors"], ["LEARNING_TRAINING_ROW_COUNT_INVALID"])
        self.assertEqual(result["training_row_count"], 2)
        self.assertFalse(result["model_fitted"])
        self.assertIsNone(result["model"])
        self.assertTrue((Path(result["manifest"]).parent/"training_audit.json").exists())

    def test_no_eligible_validation_candidate_does_not_touch_or_replay_test(self):
        config = self.config()
        lower = config["evaluation"]["development_end_msc"]
        upper = config["evaluation"]["validation_end_msc"]
        lines = self.paths[0].read_text().splitlines()
        for index in range(1, len(lines)):
            when, _, _ = lines[index].split(",")
            if lower <= int(when) < upper:
                lines[index] = f"{when},1.10000,1.10002"
        self.paths[0].write_text("\n".join(lines)+"\n")
        calls = []
        def traced(rows, strategy, execution):
            calls.append(rows[0].time_msc)
            return replay(rows, strategy, execution)
        with patch("scalper_research.engine.replay", side_effect=traced):
            result = self.run_learning()
        self.assertEqual(result["status"], "completed", result["errors"])
        self.assertTrue(result["model_fitted"])
        self.assertIsNone(result["model"])
        self.assertIsNone(result["selected_threshold"])
        self.assertEqual(result["selection_status"], "blocked_no_eligible_validation_candidate")
        self.assertTrue(all(time < upper for time in calls))
        directory = Path(result["manifest"]).parent
        self.assertFalse((directory/"selected_test.json").exists())
        self.assertFalse((directory/"baseline_test.json").exists())

    def test_each_candidate_replays_independent_state_and_selection_is_frozen_before_test(self):
        calls = []
        upper = self.config()["evaluation"]["validation_end_msc"]
        def traced(rows, strategy, execution):
            if rows[0].time_msc >= upper:
                manifests = list((self.out/"learning-runs").glob("*/manifest.json"))
                document = load_json(manifests[0].read_bytes())
                self.assertEqual(document["selection_status"], "selected_for_unaccepted_test_research")
                selected_model = load_json((manifests[0].parent/"selected_model.json").read_bytes())
                validate_model(selected_model)
                if isinstance(strategy, FilteredStrategy):
                    self.assertEqual(strategy.model["model_sha256"], selected_model["model_sha256"])
                    self.assertEqual(strategy.threshold, float(document["selected_threshold"]))
            calls.append((rows[0].time_msc, strategy))
            return replay(rows, strategy, execution)
        with patch("scalper_research.engine.replay", side_effect=traced), patch("scalper_research.learning_pipeline.fit", wraps=fit) as fitting:
            result = self.run_learning()
        self.assertEqual(result["status"], "completed", result["errors"])
        self.assertEqual(fitting.call_count, 1)
        self.assertEqual(len(calls), 9)
        self.assertEqual(len({id(strategy) for _, strategy in calls}), 9)
        self.assertIsInstance(calls[0][1], CaptureStrategy)
        self.assertFalse(isinstance(calls[0][1], FilteredStrategy))
        self.assertEqual([strategy.threshold for _, strategy in calls[2:7]], [0.0, 0.4, 0.5, 0.6, 0.7])
        self.assertEqual(sum(time >= upper for time, _ in calls), 2)

    def test_equal_clock_and_instrument_conflicts_fail_admission(self):
        self.metadata(symbol="OTHER")
        mismatch = self.run_learning()
        self.assertEqual(mismatch["errors"], ["LEARNING_INSTRUMENT_OR_CURRENCY_MISMATCH"])
        self.metadata(symbol="EURUSD")
        lines = self.paths[0].read_text().splitlines()
        lines.insert(2, lines[1])
        self.paths[0].write_text("\n".join(lines)+"\n")
        duplicate = self.run_learning()
        self.assertEqual(duplicate["errors"], ["LEARNING_EQUAL_TIMESTAMP_ORDER_UNVERIFIED"])
        self.assertEqual(learning_status(self.out)["run_id"], duplicate["run_id"])

    def test_repeat_retains_identical_model_parameters_hashes_and_immutable_raw_files(self):
        one = self.run_learning()
        two = self.run_learning()
        self.assertNotEqual(one["run_id"], two["run_id"])
        self.assertEqual(Path(one["model"]).read_bytes(), Path(two["model"]).read_bytes())
        self.assertEqual(Path(one["development_model"]).read_bytes(), Path(two["development_model"]).read_bytes())
        self.assertEqual(len(list((self.out/"raw").iterdir())), 3)

    def test_unexpected_internal_failure_persists_failed_manifest_and_raises(self):
        with patch("scalper_research.learning_pipeline.fit", side_effect=RuntimeError("fictional failure")):
            with self.assertRaises(RuntimeError):
                self.run_learning()
        result = learning_status(self.out)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["errors"], ["LEARNING_INTERNAL_ERROR"])
        self.assertFalse(result["model_fitted"])
        self.assertIsNotNone(result["finished_at_utc"])

    def test_status_before_any_run_is_explicitly_missing(self):
        with self.assertRaisesRegex(DataError, "NO_LEARNING_RUNS_FOUND"):
            learning_status(self.out)


if __name__ == "__main__":
    unittest.main()
