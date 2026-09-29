"""Local revision review with synthetic data and no authenticated requests."""
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from trading_intelligence.cli import main
from trading_intelligence.common import DataError, json_bytes
from trading_intelligence.normalize import normalize_record
from trading_intelligence.pipeline import import_json
from trading_intelligence.review import review_dataset
from trading_intelligence.store import DatasetStore
from test_pipeline import order, trade


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.out = self.root / "data"

    def tearDown(self):
        self.tmp.cleanup()

    def ingest(self, row=None, **kwargs):
        path = self.root / "input.json"
        path.write_bytes(json_bytes({"Results": [row if row is not None else trade()]}))
        return import_json(path, self.out, kind="closed_trades", strategy_id=123, **kwargs)

    def files(self):
        return {str(path.relative_to(self.out)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.out.rglob("*") if path.is_file()}

    def test_source_change_is_reported_by_field_without_private_values(self):
        self.ingest()
        run = self.ingest(trade(ProfitLoss="734.29", PRIVATE_FIELD="PRIVATE_VALUE"))
        report = review_dataset(self.out, run_id=run["run_id"])
        self.assertEqual(report["import_counts"]["revision_observations"], 1)
        comparison = report["version_comparison"]
        self.assertEqual(comparison["source_changed_pairs"], 1)
        self.assertEqual(comparison["source_unchanged_normalized_changed_pairs"], 0)
        self.assertEqual(comparison["changed_source_field_counts"],
                         {"ProfitLoss": 1, "other_source_fields": 1})
        rendered = json.dumps(report)
        for value in ("734.29", "PRIVATE_FIELD", "PRIVATE_VALUE", "EUR/USD"):
            self.assertNotIn(value, rendered)

    def test_normalization_change_is_not_claimed_to_be_a_source_change(self):
        row = trade(OpenDate="2024-01-02T09:00:00", CloseDate="2024-01-02T10:00:00")
        self.ingest(row)
        run = self.ingest(row, naive_timezone="UTC", timezone_evidence="synthetic evidence")
        report = review_dataset(self.out, run_id=run["run_id"])
        comparison = report["version_comparison"]
        self.assertEqual(comparison["source_changed_pairs"], 0)
        self.assertEqual(comparison["source_unchanged_normalized_changed_pairs"], 1)
        self.assertEqual(comparison["changed_source_field_counts"], {})
        self.assertNotIn("synthetic evidence", json.dumps(report))
        self.assertEqual(report["observed_timestamp_ranges"]["closed_trades:opened_at_utc"]["min"],
                         "2024-01-02T09:00:00+00:00")

    def test_case_only_source_layout_change_is_labelled_without_value_changes(self):
        row = trade()
        self.ingest(row)
        run = self.ingest({key[0].lower() + key[1:]: value for key, value in row.items()})
        report = review_dataset(self.out, run_id=run["run_id"])
        comparison = report["version_comparison"]
        self.assertEqual(comparison["source_changed_pairs"], 1)
        self.assertEqual(comparison["changed_source_field_counts"], {"source_field_layout": 1})

    def test_unrecognized_flag_and_range_names_are_not_echoed(self):
        run = self.ingest()
        run["quality_flag_counts"]["PRIVATE_FLAG_NAME"] = 2
        run["observed_timestamp_ranges"]["PRIVATE_RANGE_NAME"] = {"min": "PRIVATE_VALUE"}
        with DatasetStore(self.out) as store:
            store.save_manifest(run)
        report = review_dataset(self.out, run_id=run["run_id"])
        self.assertEqual(report["unrecognized_quality_flag_observations"], 2)
        for private in ("PRIVATE_FLAG_NAME", "PRIVATE_RANGE_NAME", "PRIVATE_VALUE"):
            self.assertNotIn(private, json.dumps(report))

    def test_context_only_change_keeps_an_unresolved_version_pair(self):
        row = trade()
        with DatasetStore(self.out) as store:
            for policy in ("old", "new"):
                run = store.start_run(123, "synthetic_review_test")
                run["source_rows"] = 1
                digest = store.archive(json_bytes({"Results": [row]}), run, "closed_trades")
                store.add_record(run, normalize_record(row, "closed_trades", 123), row,
                                 digest, 1, context={"policy_tag": policy})
                store.finish(run)
        report = review_dataset(self.out, run_id=run["run_id"])
        self.assertEqual(report["version_comparison"]["source_and_normalized_unchanged_pairs"], 1)
        self.assertFalse(report["training_ready"])
        self.assertFalse(report["full_history_verified"])
        self.assertTrue(report["review_does_not_clear_blockers"])

    def test_duplicate_import_is_separate_from_persistent_version_history(self):
        self.ingest()
        self.ingest(trade(ProfitLoss="2.00"))
        run = self.ingest(trade(ProfitLoss="2.00"))
        report = review_dataset(self.out, run_id=run["run_id"])
        self.assertEqual(report["import_counts"]["duplicate_observations"], 1)
        self.assertEqual(report["import_counts"]["revision_observations"], 0)
        self.assertEqual(report["version_comparison"]["pairs_compared"], 1)
        self.assertEqual(report["version_comparison"]["source_changed_pairs"], 1)
        self.assertEqual(report["version_comparison"]["comparison_basis"],
                         "observed_versions_vs_immediate_insertion_predecessor")

    def test_predecessor_matching_preserves_strategy_kind_and_origin(self):
        self.ingest()
        run = self.ingest(trade(ProfitLoss="2.00"), synthetic=True)
        report = review_dataset(self.out, run_id=run["run_id"])
        self.assertEqual(report["version_comparison"]["pairs_compared"], 0)
        other = self.root / "other.json"
        other.write_bytes(json_bytes({"Results": [order(Id=20, SignalId=20)]}))
        run = import_json(other, self.out, kind="orders", strategy_id=123)
        report = review_dataset(self.out, run_id=run["run_id"])
        self.assertEqual(report["version_comparison"]["pairs_compared"], 0)
        self.assertEqual(report["version_comparison"]["versions_without_predecessor"], 1)
        other.write_bytes(json_bytes({"Results": [trade(StrategyId=456)]}))
        run = import_json(other, self.out, kind="closed_trades", strategy_id=456)
        report = review_dataset(self.out, run_id=run["run_id"])
        self.assertEqual(report["version_comparison"]["pairs_compared"], 0)

    def test_cli_review_uses_no_key_or_network_and_changes_no_saved_files(self):
        run = self.ingest()
        before = self.files()
        out, err = io.StringIO(), io.StringIO()
        with patch("trading_intelligence.cli._read_api_key", side_effect=AssertionError("no key")), \
                patch("trading_intelligence.collective2.HTTPSGetTransport.get",
                      side_effect=AssertionError("no network")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["review", "--out", str(self.out), "--run-id", run["run_id"]])
        self.assertEqual(code, 0)
        report = json.loads(out.getvalue())
        self.assertEqual(report["record_versions_observed"], 1)
        self.assertEqual(report["distinct_source_ids_observed"], 1)
        self.assertFalse(report["network_used"])
        self.assertFalse(report["data_saved"])
        self.assertFalse(report["training_ready"])
        self.assertEqual(self.files(), before)

    def test_latest_run_is_used_and_quality_flags_are_preserved(self):
        self.ingest()
        run = self.ingest(trade(OpenDate="2024-01-02T09:00:00"))
        report = review_dataset(self.out)
        self.assertEqual(report["run_id"], run["run_id"])
        self.assertEqual(report["quality_flag_counts"]["TIMEZONE_UNVERIFIED"], 1)
        self.assertEqual(report["distinct_symbols_observed"], 1)

    def test_missing_database_or_run_does_not_create_anything(self):
        with self.assertRaisesRegex(DataError, "REVIEW_DATABASE_NOT_FOUND"):
            review_dataset(self.out)
        self.assertFalse(self.out.exists())
        self.ingest()
        before = self.files()
        with self.assertRaisesRegex(DataError, "REVIEW_RUN_NOT_FOUND"):
            review_dataset(self.out, run_id="0" * 32)
        with self.assertRaisesRegex(DataError, "REVIEW_RUN_ID_INVALID"):
            review_dataset(self.out, run_id="../../PRIVATE")
        self.assertEqual(self.files(), before)

    def test_failed_run_stays_failed_and_readable_without_training_clearance(self):
        path = self.root / "bad.json"
        path.write_text('{"error":"PRIVATE_ERROR_BODY"}')
        with self.assertRaises(DataError):
            import_json(path, self.out, kind="closed_trades", strategy_id=123)
        report = review_dataset(self.out)
        self.assertEqual(report["run_status"], "failed")
        self.assertEqual(report["record_versions_observed"], 0)
        self.assertNotIn("PRIVATE_ERROR_BODY", json.dumps(report))
        self.assertFalse(report["training_ready"])


if __name__ == "__main__":
    unittest.main()
