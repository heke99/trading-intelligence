"""Offline synthetic tick projection checks; never acquire or train on data."""
from decimal import Decimal, localcontext
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from trading_intelligence.common import DataError, json_bytes, load_json, sha256
from scalper_research.market import load_quotes, validate_quote_execution
from scalper_research.tick_projection import project_ticks


class TickProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.csv = self.root/"native.synthetic.csv"
        self.metadata = self.root/"metadata.synthetic.json"
        self.out = self.root/"out"
        self.write()

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, rows=None, **changes):
        rows = rows if rows is not None else [
            (1000, "1", "1.2"), (1000, "1.1", "1.3"),
            (1001, "1.4", "1.6"), (1002, "1.5", "1.7")]
        self.csv.write_text("time_msc,bid,ask\n"+"".join(f"{clock},{bid},{ask}\n" for clock, bid, ask in rows))
        metadata = {"schema_version": 1, "source_id": "fictional_tick_fixture", "symbol": "EURUSD",
                    "price_currency": "USD", "timestamp_basis": "utc_epoch_milliseconds",
                    "timezone_evidence": "Fictional generator explicitly defines UTC milliseconds.",
                    "data_origin": "synthetic_fixture", "usage_rights": "synthetic_only",
                    "training_usage_rights": "synthetic_only", "attribution": "fictional local fixture"}
        metadata.update(changes)
        self.metadata.write_bytes(json_bytes(metadata))

    def project(self, period=1, gap=10):
        with patch("urllib.request.urlopen", side_effect=AssertionError("offline only")):
            return project_ticks(self.csv, self.metadata, self.out,
                                 sample_period_ms=period, max_native_gap_ms=gap)

    def dataset(self, result):
        self.assertEqual(result["status"], "completed", result["errors"])
        return load_quotes(Path(result["output_csv"]), Path(result["output_metadata"]))

    def evidence(self, result, key):
        return [json.loads(line) for line in Path(result[key]).read_text().splitlines()]

    def assert_failed(self, result, code):
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["errors"], [code])
        for key in ("output_csv", "output_metadata", "raw_rows_path", "bucket_evidence_path"):
            self.assertIsNone(result[key])
        self.assertIsNotNone(result["finished_at_utc"])
        self.assertFalse(result["training_ready"])
        self.assertFalse(result["trading_enabled"])

    def test_equal_millisecond_ticks_keep_raw_clocks_and_select_last_source_row_at_next_boundary(self):
        original_csv, original_metadata = self.csv.read_bytes(), self.metadata.read_bytes()
        result = self.project()
        dataset = self.dataset(result)
        self.assertEqual([quote.time_msc for quote in dataset.quotes], [1001, 1002])
        self.assertEqual([quote.bid for quote in dataset.quotes], [Decimal("1.1"), Decimal("1.4")])
        self.assertEqual(result["input_quote_count"], 4)
        self.assertEqual(result["raw_rows_written"], 4)
        self.assertEqual(result["duplicate_native_timestamp_rows"], 1)
        self.assertEqual(Path(result["raw_csv_path"]).read_bytes(), original_csv)
        self.assertEqual(Path(result["raw_metadata_path"]).read_bytes(), original_metadata)
        raw = self.evidence(result, "raw_rows_path")
        self.assertEqual([row["native_time_msc"] for row in raw], [1000, 1000, 1001, 1002])
        self.assertEqual([row["source_row"] for row in raw], [2, 3, 4, 5])
        self.assertEqual([row["source_record_index"] for row in raw], [1, 2, 3, 4])
        self.assertTrue(all(row["source_row_is_exchange_sequence"] is False for row in raw))
        buckets = self.evidence(result, "bucket_evidence_path")
        self.assertEqual([row["selected_source_row"] for row in buckets if row["emitted"]], [3, 4])
        self.assertTrue(all(row["native_time_last_msc"] < row["bucket_end_msc"]
                            <= row["completion_witness_time_msc"] for row in buckets if row["emitted"]))
        self.assertTrue(all(row["witness_prices_incorporated"] is False for row in buckets))
        self.assertIn("EQUAL_TIMESTAMP_ORDER_UNVERIFIED", dataset.metadata["source_tick_quality_flags"])
        self.assertNotIn("EQUAL_TIMESTAMP_ORDER_UNVERIFIED", dataset.quality_flags)
        self.assertIn("SOURCE_EQUAL_MILLISECOND_ORDER_UNVERIFIED", dataset.quality_flags)
        self.assertIn("DERIVED_BUCKET_END_QUOTE_NOT_NATIVE_TICK", dataset.quality_flags)
        self.assertIn("EVENT_TIME_TIMER_ASSUMED", dataset.quality_flags)
        self.assertTrue(dataset.metadata["event_time_timer_assumed"])
        self.assertIn("virtual event-time", result["timer_assumption"])
        self.assertEqual(dataset.metadata["timer_assumption"], result["timer_assumption"])
        self.assertTrue(all(bucket["event_time_timer_assumed"] is True for bucket in buckets))
        for bucket in buckets:
            expected_delay = (bucket["completion_witness_time_msc"] - bucket["bucket_end_msc"]
                              if bucket["completed"] else None)
            self.assertEqual(bucket["witness_delay_ms"], expected_delay)
        for raw_path in (result["raw_csv_path"], result["raw_metadata_path"]):
            self.assertEqual(Path(raw_path).stat().st_mode & 0o222, 0)

    def test_boundary_witness_price_is_not_incorporated_into_the_previous_bucket(self):
        rows = [(1001, "1", "1.2"), (1049, "1.1", "1.3"), (1099, "1.2", "1.4"),
                (1100, "9", "9.2"), (1199, "9.1", "9.3"), (1200, "12", "12.2")]
        self.write(rows)
        first = self.project(period=100, gap=200)
        first_dataset = self.dataset(first)
        self.assertEqual([quote.time_msc for quote in first_dataset.quotes], [1100, 1200])
        self.assertEqual(first_dataset.quotes[0].bid, Decimal("1.2"))
        changed = [(clock, "999", "999.2") if clock >= 1100 else (clock, bid, ask)
                   for clock, bid, ask in rows]
        self.write(changed)
        second = self.project(period=100, gap=200)
        second_dataset = self.dataset(second)
        self.assertEqual(first_dataset.quotes[0], second_dataset.quotes[0])
        self.assertNotEqual(first_dataset.quotes[1].bid, second_dataset.quotes[1].bid)
        self.assertNotEqual(first["source_csv_sha256"], second["source_csv_sha256"])

    def test_later_gap_does_not_retroactively_taint_completed_old_bucket_and_empty_buckets_are_not_filled(self):
        self.write([(1001, "1", "1.2"), (1010, "2", "2.2"), (2000, "8", "8.2"),
                    (2010, "8.1", "8.3"), (2020, "8.2", "8.4")])
        result = self.project(period=10, gap=20)
        dataset = self.dataset(result)
        self.assertEqual([quote.time_msc for quote in dataset.quotes], [1010, 1020, 2020])
        self.assertEqual([quote.bid for quote in dataset.quotes], [Decimal("1"), Decimal("2"), Decimal("8.1")])
        self.assertEqual(result["native_gap_count"], 1)
        self.assertEqual(result["dirty_bucket_count"], 1)
        self.assertEqual(result["empty_bucket_count_not_filled"], 98)
        buckets = self.evidence(result, "bucket_evidence_path")
        dropped = [row for row in buckets if "NATIVE_CLOCK_GAP" in row["excluded_reasons"]]
        self.assertEqual([row["bucket_start_msc"] for row in dropped], [2000])
        self.assertFalse(dropped[0]["emitted"])
        self.assertEqual([row["segment_id"] for row in self.evidence(result, "raw_rows_path")], [1, 1, 2, 2, 2])
        self.assertEqual(dataset.metadata["projection_required_max_quote_gap_ms"], 10)

    def test_late_completion_witness_is_explicit_timer_evidence_without_receive_or_fill_verification(self):
        self.write([(1001, "1", "1.2"), (1010, "2", "2.2"), (2000, "8", "8.2"),
                    (2010, "8.1", "8.3"), (2020, "8.2", "8.4")])
        result = self.project(period=10, gap=20)
        metadata = self.dataset(result).metadata
        buckets = self.evidence(result, "bucket_evidence_path")
        previous = next(bucket for bucket in buckets if bucket["bucket_start_msc"] == 1010)
        self.assertTrue(previous["emitted"])
        self.assertEqual(previous["bucket_end_msc"], 1020)
        self.assertEqual(previous["completion_witness_time_msc"], 2000)
        self.assertEqual(previous["witness_delay_ms"], 980)
        self.assertFalse(previous["witness_prices_incorporated"])
        self.assertEqual(previous["selected_bid"], "2")
        self.assertIsNone(buckets[-1]["witness_delay_ms"])
        self.assertIsNone(buckets[-1]["completion_witness_time_msc"])
        self.assertEqual(result["maximum_witness_delay_ms"], 980)
        self.assertEqual(metadata["tick_projection"]["maximum_witness_delay_ms"], 980)
        self.assertEqual(metadata["tick_projection"]["timer_assumption"], result["timer_assumption"])
        self.assertFalse(metadata["tick_projection"]["receive_clock_verified"])
        self.assertFalse(metadata["tick_projection"]["fills_verified"])
        self.assertIn("EVENT_TIME_TIMER_ASSUMED", metadata["quality_flags"])

    def test_native_gap_inside_observed_bucket_dirties_that_entire_bucket(self):
        self.write([(901, "1", "1.2"), (902, "1.1", "1.3"), (1000, "2", "2.2"),
                    (1001, "2.1", "2.3"), (1050, "5", "5.2"), (1100, "6", "6.2"), (1101, "6.1", "6.3")])
        result = self.project(period=100, gap=10)
        dataset = self.dataset(result)
        self.assertEqual([quote.time_msc for quote in dataset.quotes], [1000])
        self.assertEqual(dataset.quotes[0].bid, Decimal("1.1"))
        buckets = self.evidence(result, "bucket_evidence_path")
        dirty = next(row for row in buckets if row["bucket_start_msc"] == 1000)
        self.assertTrue(dirty["completed"])
        self.assertFalse(dirty["emitted"])
        self.assertEqual(dirty["native_row_count"], 3)
        self.assertEqual(dirty["excluded_reasons"], ["NATIVE_CLOCK_GAP"])

    def test_final_incomplete_bucket_is_excluded_and_single_clock_only_input_is_failed(self):
        result = self.project()
        self.dataset(result)
        buckets = self.evidence(result, "bucket_evidence_path")
        self.assertEqual(result["incomplete_final_bucket_count"], 1)
        self.assertFalse(buckets[-1]["completed"])
        self.assertFalse(buckets[-1]["emitted"])
        self.assertEqual(buckets[-1]["excluded_reasons"], ["FINAL_INCOMPLETE_BUCKET"])
        self.write([(1000, "1", "1.2"), (1000, "2", "2.2")])
        failed = self.project()
        self.assert_failed(failed, "TICK_PROJECTION_NO_COMPLETE_CLEAN_BUCKETS")
        self.assertEqual(failed["raw_rows_written"], 2)
        self.assertEqual(failed["quote_count"], 0)
        self.assertTrue(failed["partial_outputs"])

    def test_reversing_same_clock_physical_rows_changes_assumed_observation_without_claiming_exchange_order(self):
        one = self.project()
        first = self.dataset(one).quotes[0].bid
        self.write([(1000, "1.1", "1.3"), (1000, "1", "1.2"), (1001, "1.4", "1.6"), (1002, "1.5", "1.7")])
        two = self.project()
        second = self.dataset(two).quotes[0].bid
        self.assertEqual((first, second), (Decimal("1.1"), Decimal("1")))
        self.assertIn("as-file observation-order assumption", two["equal_clock_policy"])
        self.assertFalse(self.dataset(two).metadata["tick_projection"]["exchange_sequence_verified"])

    def test_archive_byte_copies_are_loaded_even_if_original_input_is_mutated(self):
        original_csv, original_metadata = self.csv.read_bytes(), self.metadata.read_bytes()
        def mutate_original_then_load(archived_csv, archived_metadata):
            self.assertNotEqual(archived_csv, self.csv)
            self.assertNotEqual(archived_metadata, self.metadata)
            self.csv.write_text("caller changed the original after archiving")
            self.metadata.write_text("caller changed the original after archiving")
            return load_quotes(archived_csv, archived_metadata)
        with patch("scalper_research.tick_projection.load_quotes", side_effect=mutate_original_then_load):
            result = self.project()
        self.dataset(result)
        self.assertEqual(Path(result["raw_csv_path"]).read_bytes(), original_csv)
        self.assertEqual(Path(result["raw_metadata_path"]).read_bytes(), original_metadata)

    def test_price_precision_and_original_lexical_csv_survive_without_floating_point_conversion(self):
        original = ("time_msc,bid,ask\n0001000,01.000000000000000000000000000001,1.100000000000000000000000000001\n"
                    "0001001,01.000000000000000000000000000002,1.100000000000000000000000000002\n")
        self.csv.write_text(original)
        with localcontext() as context:
            context.prec = 3
            result = self.project()
            dataset = self.dataset(result)
        self.assertEqual(dataset.quotes[0].bid, Decimal("1.000000000000000000000000000001"))
        self.assertEqual(Path(result["raw_csv_path"]).read_bytes(), original.encode())

    def test_origin_rights_attribution_are_retained_and_no_model_or_broker_claim_is_enabled(self):
        self.write(data_origin="user_supplied_unverified", usage_rights="not_verified",
                   training_usage_rights="not_verified", model_fitted=True, model_trained=True,
                   trading_enabled=True, broker_connected=True, forward_verified=True, market_history_verified=True)
        result = self.project()
        metadata = self.dataset(result).metadata
        self.assertEqual(metadata["data_origin"], "user_supplied_unverified")
        self.assertEqual(metadata["usage_rights"], "not_verified")
        self.assertEqual(metadata["training_usage_rights"], "not_verified")
        self.assertEqual(metadata["attribution"], "fictional local fixture")
        for document in (result, metadata):
            for key in ("training_ready", "full_history_verified", "broker_verified", "model_trained", "model_fitted",
                        "model_trained_on_real_market", "trading_enabled", "broker_connected", "broker_demo_verified",
                        "market_history_verified", "forward_verified"):
                self.assertIs(document[key], False)
        self.assertFalse(result["training_performed"])
        self.assertFalse(result["network_used"])

    def test_provider_symbol_and_quote_currency_are_opaque_and_preserved(self):
        for symbol, currency in (("EURUSD", "USD"), ("SOURCE_NASDAQ_CONTRACT", "USD"), ("XAUUSD", "USD"),
                                 ("GBPJPY", "JPY"), ("EURJPY", "JPY")):
            with self.subTest(symbol=symbol):
                self.write(symbol=symbol, price_currency=currency)
                result = self.project()
                metadata = self.dataset(result).metadata
                self.assertEqual((metadata["symbol"], metadata["price_currency"]), (symbol, currency))

    def test_execution_gap_guard_cannot_bridge_an_omitted_projected_bucket(self):
        result = self.project(period=1, gap=10)
        metadata = self.dataset(result).metadata
        validate_quote_execution(metadata, SimpleNamespace(max_quote_gap_ms=1))
        with self.assertRaisesRegex(DataError, "RECONSTRUCTED_QUOTE_GAP_POLICY_MISMATCH"):
            validate_quote_execution(metadata, SimpleNamespace(max_quote_gap_ms=2))

    def test_stream_and_derived_caps_never_broaden_an_inherited_policy(self):
        self.write([(1000, "1", "1.2"), (1010, "1.1", "1.3"), (1020, "1.2", "1.4"), (1100, "2", "2.2")],
                   wse_required_max_quote_gap_ms=50, projection_required_max_quote_gap_ms=40)
        result = self.project(period=100, gap=40)
        metadata = self.dataset(result).metadata
        self.assertEqual(metadata["wse_required_max_quote_gap_ms"], 50)
        self.assertEqual(metadata["projection_required_max_quote_gap_ms"], 40)
        self.assertEqual(result["inherited_quote_gap_caps"], {"wse_required_max_quote_gap_ms": 50,
                                                            "projection_required_max_quote_gap_ms": 40})
        failed = self.project(period=100, gap=41)
        self.assert_failed(failed, "TICK_PROJECTION_NATIVE_GAP_WOULD_BROADEN_SOURCE_POLICY")

    def test_source_caveats_and_prior_native_duplicate_provenance_are_not_erased(self):
        self.write(quality_flags=["CONTINUOUS_MATCHING_PHASE_UNVERIFIED", "CUSTOM_PROVIDER_CAVEAT"],
                   source_tick_quality_flags=["EQUAL_TIMESTAMP_ORDER_UNVERIFIED", "PRIOR_CAVEAT"],
                   wse_required_max_quote_gap_ms=20)
        result = self.project(period=1, gap=10)
        metadata = self.dataset(result).metadata
        self.assertIn("CONTINUOUS_MATCHING_PHASE_UNVERIFIED", metadata["quality_flags"])
        self.assertIn("CUSTOM_PROVIDER_CAVEAT", metadata["source_tick_quality_flags"])
        self.assertIn("PRIOR_CAVEAT", metadata["source_tick_quality_flags"])
        self.assertIn("EQUAL_TIMESTAMP_ORDER_UNVERIFIED", metadata["source_tick_quality_flags"])
        self.assertNotIn("EQUAL_TIMESTAMP_ORDER_UNVERIFIED", self.dataset(result).quality_flags)

    def test_parameter_types_and_unsupported_source_schema_fail_before_publication(self):
        for period, gap, code in ((True, 10, "TICK_PROJECTION_PERIOD_RANGE"),
                                  (0, 10, "TICK_PROJECTION_PERIOD_RANGE"),
                                  (1001, 10, "TICK_PROJECTION_PERIOD_RANGE"),
                                  (1, True, "TICK_PROJECTION_NATIVE_GAP_RANGE"),
                                  (1, 0, "TICK_PROJECTION_NATIVE_GAP_RANGE")):
            with self.subTest(period=period, gap=gap):
                result = self.project(period=period, gap=gap)
                self.assert_failed(result, code)
                self.assertEqual(len(result["raw_files"]), 2)
        self.write(tick_projection={"schema_version": 2})
        self.assert_failed(self.project(), "TICK_PROJECTION_PARENT_SCHEMA_INVALID")
        self.write(quality_flags="untyped provider text")
        self.assert_failed(self.project(), "TICK_PROJECTION_SOURCE_FLAGS_INVALID")

    def test_reversed_native_clock_is_rejected_without_sorting_and_originals_are_retained(self):
        self.write([(1001, "1", "1.2"), (1000, "2", "2.2")])
        original = self.csv.read_bytes()
        failed = self.project()
        self.assert_failed(failed, "MARKET_CLOCK_NOT_NONDECREASING")
        csv_archive = next(item for item in failed["raw_files"] if item["kind"] == "native_csv")
        self.assertEqual(Path(csv_archive["path"]).read_bytes(), original)

    def test_incomplete_source_export_and_raw_row_quota_are_not_bypassed(self):
        self.write(source_export_status="failed")
        self.assert_failed(self.project(), "MARKET_SOURCE_EXPORT_INCOMPLETE")
        self.write()
        with patch("scalper_research.market.MAX_ROWS", 3):
            self.assert_failed(self.project(), "MARKET_ROW_LIMIT")

    def test_csv_and_evidence_output_quotas_preserve_partial_receipts_not_complete_outputs(self):
        with patch("scalper_research.tick_projection.MAX_BYTES", 20):
            csv_failed = self.project()
        self.assert_failed(csv_failed, "TICK_PROJECTION_OUTPUT_SIZE_LIMIT:output_csv")
        self.assertTrue(csv_failed["partial_outputs"])
        self.assertEqual(len(csv_failed["raw_files"]), 2)
        with patch("scalper_research.tick_projection.MAX_EVIDENCE_BYTES", 20):
            evidence_failed = self.project()
        self.assert_failed(evidence_failed, "TICK_PROJECTION_OUTPUT_SIZE_LIMIT:raw_rows_path")
        self.assertTrue(evidence_failed["partial_outputs"])

    def test_repeat_outputs_have_same_bytes_hashes_and_reuse_immutable_input_archives(self):
        one = self.project()
        two = self.project()
        self.dataset(one)
        self.dataset(two)
        self.assertNotEqual(one["run_id"], two["run_id"])
        for key in ("output_csv", "output_metadata", "raw_rows_path", "bucket_evidence_path"):
            self.assertEqual(Path(one[key]).read_bytes(), Path(two[key]).read_bytes())
            self.assertEqual(sha256(Path(one[key]).read_bytes()), one[key+"_sha256"])
        self.assertEqual(len(list((self.out/"raw").iterdir())), 2)

    def test_unexpected_internal_error_preserves_failed_manifest_before_reraising(self):
        with patch("scalper_research.tick_projection.load_quotes", side_effect=RuntimeError("fictional internal failure")):
            with self.assertRaises(RuntimeError):
                self.project()
        manifests = list((self.out/"tick-projection-runs").glob("*/manifest.json"))
        self.assertEqual(len(manifests), 1)
        result = load_json(manifests[0].read_bytes())
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["errors"], ["TICK_PROJECTION_INTERNAL_ERROR"])
        self.assertEqual(len(result["raw_files"]), 2)
        self.assertIsNotNone(result["finished_at_utc"])


if __name__ == "__main__":
    unittest.main()
