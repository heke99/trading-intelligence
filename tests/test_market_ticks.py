"""Synthetic, offline quote-import regressions; no trader or market exports."""
import hashlib
import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from scalper_research.market import Quote, import_quotes, load_quotes
from trading_intelligence.common import DataError


def quote_metadata(**overrides):
    """Entirely fictional input provenance for offline tests."""
    return {
        "schema_version": 1,
        "source_id": "fictional_quotes_v1",
        "symbol": "FIXTURE",
        "timestamp_basis": "utc_epoch_milliseconds",
        "timezone_evidence": "Fictional fixture generator used UTC epoch milliseconds.",
        "data_origin": "synthetic_fixture",
        "price_currency": "USD",
        "usage_rights": "synthetic_only",
        **overrides,
    }


class MarketTicksTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.csv = self.root / "quotes.csv"
        self.meta = self.root / "metadata.json"
        self.out = self.root / "result"
        self.write()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, csv_text=None, metadata=None):
        self.csv.write_text(csv_text or (
            "time_msc,bid,ask\n"
            "1700000000000,100.0100,100.0300\n"
            "1700000000123,100.0150,100.0400\n"
            "1700000000456,100.0200,100.0200\n"), encoding="utf-8")
        self.meta.write_text(json.dumps(metadata or quote_metadata()), encoding="utf-8")

    def assert_invalid_csv(self, text, code):
        self.write(text)
        with self.assertRaisesRegex(DataError, "^" + code + "$"):
            load_quotes(self.csv, self.meta)

    def test_exact_prices_source_rows_and_hashes_are_preserved(self):
        dataset = load_quotes(self.csv, self.meta)
        self.assertEqual(dataset.quotes, [
            Quote(1700000000000, Decimal("100.0100"), Decimal("100.0300"), 2),
            Quote(1700000000123, Decimal("100.0150"), Decimal("100.0400"), 3),
            Quote(1700000000456, Decimal("100.0200"), Decimal("100.0200"), 4),
        ])
        self.assertEqual(str(dataset.quotes[0].bid), "100.0100")
        self.assertEqual(dataset.raw_sha256, hashlib.sha256(self.csv.read_bytes()).hexdigest())
        self.assertEqual(dataset.metadata_sha256, hashlib.sha256(self.meta.read_bytes()).hexdigest())
        self.assertIn("SYNTHETIC_FIXTURE_NOT_MARKET_HISTORY", dataset.quality_flags)
        with self.assertRaises(FrozenInstanceError):
            dataset.quotes[0].bid = Decimal("1")

    def test_identical_and_equal_timestamp_rows_remain_in_physical_order(self):
        self.write("time_msc,bid,ask\n1,100,101\n1,100,101\n1,102,103\n2,104,105\n")
        dataset = load_quotes(self.csv, self.meta)
        self.assertEqual([quote.source_row for quote in dataset.quotes], [2, 3, 4, 5])
        self.assertEqual([quote.bid for quote in dataset.quotes], [
            Decimal("100"), Decimal("100"), Decimal("102"), Decimal("104")])
        self.assertIn("EQUAL_TIMESTAMP_ORDER_UNVERIFIED", dataset.quality_flags)
        manifest = import_quotes(self.csv, self.meta, self.out)
        self.assertEqual(manifest["duplicate_timestamp_rows"], 2)
        self.assertEqual(manifest["quote_count"], 4)

    def test_clock_order_is_rejected_without_sorting_input(self):
        raw = "time_msc,bid,ask\n2,100,101\n1,102,103\n"
        self.assert_invalid_csv(raw, "MARKET_CLOCK_NOT_NONDECREASING")
        result = import_quotes(self.csv, self.meta, self.out)
        self.assertEqual(Path(result["raw_csv_path"]).read_text(), raw)
        self.assertIsNone(result["normalized_quotes_path"])

    def test_crossed_quote_is_rejected(self):
        self.assert_invalid_csv("time_msc,bid,ask\n1,101,100\n", "MARKET_CROSSED_QUOTE")

    def test_nonfinite_nonpositive_invalid_and_extreme_prices_fail(self):
        for value in ("NaN", "sNaN", "Infinity", "-Infinity", "0", "-1", "bad", "1e101", " 1"):
            with self.subTest(value=value):
                self.assert_invalid_csv(f"time_msc,bid,ask\n1,{value},2\n", "MARKET_PRICE_INVALID")

    def test_prices_reject_non_csv_numeric_syntax_without_reinterpreting_it(self):
        for value in ("1_0", "١", "１２"):
            with self.subTest(value=value):
                self.assert_invalid_csv(f"time_msc,bid,ask\n1,{value},20\n", "MARKET_PRICE_INVALID")

    def test_timestamps_are_integer_positive_utc_milliseconds_in_datetime_range(self):
        for value in ("0", "-1", "1.0", "1e3", "+1", " 1", "١", "253402300800000"):
            with self.subTest(value=value):
                self.assert_invalid_csv(f"time_msc,bid,ask\n{value},1,2\n", "MARKET_TIMESTAMP_INVALID")
        self.write("time_msc,bid,ask\n253402300799999,1,2\n")
        manifest = import_quotes(self.csv, self.meta, self.out)
        self.assertEqual(manifest["status"], "completed")
        self.assertEqual(manifest["last_time_utc"], "9999-12-31T23:59:59.999Z")

    def test_clock_basis_and_timezone_evidence_must_be_explicit(self):
        for metadata in (quote_metadata(timestamp_basis="broker_local"),
                         quote_metadata(timezone_evidence="")):
            with self.subTest(metadata=metadata):
                self.write(metadata=metadata)
                with self.assertRaises(DataError):
                    load_quotes(self.csv, self.meta)

    def test_optional_symbol_and_utf8_bom_with_column_order(self):
        text = "\ufeffsymbol,ask,time_msc,bid\nFIXTURE,2.00,1,1.00\n"
        self.write(text)
        dataset = load_quotes(self.csv, self.meta)
        self.assertEqual(dataset.quotes[0], Quote(1, Decimal("1.00"), Decimal("2.00"), 2))
        self.write(text.replace("FIXTURE,", "OTHER,"))
        with self.assertRaisesRegex(DataError, "MARKET_SYMBOL_MISMATCH"):
            load_quotes(self.csv, self.meta)

    def test_unknown_duplicate_and_missing_headers_fail(self):
        for text in ("time_msc,bid,ask,volume\n1,1,2,100\n",
                     "time_msc,bid,bid\n1,1,2\n",
                     "time_msc,bid\n1,1\n",
                     "time_msc;bid;ask\n1;1;2\n"):
            with self.subTest(text=text):
                self.assert_invalid_csv(text, "MARKET_CSV_HEADER_SCHEMA")

    def test_blank_missing_and_extra_rows_never_disappear_silently(self):
        for row in ("", "1,1", "1,1,2,3"):
            with self.subTest(row=row):
                self.assert_invalid_csv("time_msc,bid,ask\n1,1,2\n" + row + "\n", "MARKET_CSV_ROW_SCHEMA")

    def test_empty_and_header_only_files_fail(self):
        self.csv.write_bytes(b"")
        with self.assertRaisesRegex(DataError, "MARKET_CSV_EMPTY"):
            load_quotes(self.csv, self.meta)
        self.assert_invalid_csv("time_msc,bid,ask\n", "MARKET_NO_QUOTES")

    def test_malformed_csv_and_encoding_fail(self):
        self.assert_invalid_csv('time_msc,bid,ask\n1,"1,2\n', "MARKET_CSV_INVALID")
        self.csv.write_bytes(b"time_msc,bid,ask\n1,\xff,2\n")
        with self.assertRaisesRegex(DataError, "MARKET_CSV_ENCODING"):
            load_quotes(self.csv, self.meta)

    def test_metadata_identity_origin_rights_and_verification_claims(self):
        cases = [
            quote_metadata(source_id="../../input"),
            quote_metadata(schema_version=True),
            quote_metadata(schema_version=2),
            quote_metadata(symbol=""),
            quote_metadata(price_currency=" USD"),
            quote_metadata(data_origin="broker_verified"),
            quote_metadata(data_origin="user_supplied_unverified", usage_rights="synthetic_only"),
            quote_metadata(usage_rights="licensed"),
            quote_metadata(usage_rights="user_asserted_permitted"),
            quote_metadata(broker_verified=True),
            quote_metadata(training_ready=True),
            quote_metadata(full_history_verified="true"),
        ]
        for metadata in cases:
            with self.subTest(metadata=metadata):
                self.write(metadata=metadata)
                with self.assertRaises(DataError):
                    load_quotes(self.csv, self.meta)
        permitted = quote_metadata(data_origin="user_supplied_unverified",
                                   usage_rights="user_asserted_permitted",
                                   rights_evidence="Fictional user assertion; no broker authentication.")
        self.write(metadata=permitted)
        self.assertEqual(load_quotes(self.csv, self.meta).metadata, permitted)

    def test_metadata_duplicate_keys_and_nonfinite_json_are_rejected(self):
        for raw in (b'{"schema_version":1,"schema_version":1}', b'{"schema_version":NaN}', b'{broken'):
            with self.subTest(raw=raw):
                self.meta.write_bytes(raw)
                with self.assertRaises(DataError):
                    load_quotes(self.csv, self.meta)

    def test_successful_manifest_reports_clock_gaps_and_never_readiness(self):
        manifest = import_quotes(self.csv, self.meta, self.out)
        self.assertEqual(manifest["status"], "completed")
        self.assertEqual(manifest["source_count"], 1)
        self.assertEqual(manifest["quote_count"], 3)
        self.assertEqual(manifest["max_gap_ms"], 333)
        self.assertEqual(manifest["duplicate_timestamp_rows"], 0)
        self.assertEqual(manifest["first_time_msc"], 1700000000000)
        self.assertEqual(manifest["last_time_msc"], 1700000000456)
        self.assertEqual(manifest["first_time_utc"], "2023-11-14T22:13:20.000Z")
        self.assertFalse(manifest["training_ready"])
        self.assertFalse(manifest["full_history_verified"])
        self.assertFalse(manifest["broker_verified"])
        self.assertFalse(manifest["trading_enabled"])
        self.assertEqual(json.loads(Path(manifest["manifest_path"]).read_text()), manifest)
        normalized = [json.loads(line) for line in Path(manifest["normalized_quotes_path"]).read_text().splitlines()]
        self.assertEqual([row["source_row"] for row in normalized], [2, 3, 4])
        self.assertEqual(normalized[0]["bid"], "100.0100")

    def test_reimport_reuses_immutable_raw_bytes_with_separate_audit_runs(self):
        first = import_quotes(self.csv, self.meta, self.out)
        second = import_quotes(self.csv, self.meta, self.out)
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertEqual(first["csv_raw_sha256"], second["csv_raw_sha256"])
        self.assertEqual(first["raw_csv_path"], second["raw_csv_path"])
        self.assertEqual(first["raw_metadata_path"], second["raw_metadata_path"])
        self.assertEqual(len(list((self.out / "raw" / "market").iterdir())), 2)
        self.assertEqual(Path(first["raw_csv_path"]).read_bytes(), self.csv.read_bytes())
        self.assertEqual(Path(first["raw_metadata_path"]).read_bytes(), self.meta.read_bytes())
        self.assertEqual(first["normalized_quotes_sha256"], second["normalized_quotes_sha256"])

    def test_failed_validation_preserves_raw_and_final_failed_manifest(self):
        self.write("time_msc,bid,ask\n1,101,100\n")
        manifest = import_quotes(self.csv, self.meta, self.out)
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(manifest["errors"], ["MARKET_CROSSED_QUOTE"])
        self.assertEqual(Path(manifest["raw_csv_path"]).read_bytes(), self.csv.read_bytes())
        self.assertEqual(Path(manifest["raw_metadata_path"]).read_bytes(), self.meta.read_bytes())
        self.assertIsNone(manifest["normalized_quotes_path"])
        self.assertFalse((Path(manifest["manifest_path"]).parent / "quotes.jsonl").exists())
        self.assertEqual(json.loads(Path(manifest["manifest_path"]).read_text()), manifest)
        self.assertIsNotNone(manifest["completed_at_utc"])

    def test_missing_metadata_preserves_archived_csv_without_claiming_success(self):
        self.meta.unlink()
        manifest = import_quotes(self.csv, self.meta, self.out)
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(manifest["errors"], ["INPUT_READ_FAILED"])
        self.assertEqual(Path(manifest["raw_csv_path"]).read_bytes(), self.csv.read_bytes())
        self.assertIsNone(manifest["metadata_raw_sha256"])

    def test_corrupted_existing_archive_is_not_overwritten(self):
        first = import_quotes(self.csv, self.meta, self.out)
        archived = Path(first["raw_csv_path"])
        archived.write_bytes(b"corrupt archive")
        second = import_quotes(self.csv, self.meta, self.out)
        self.assertEqual(second["status"], "failed")
        self.assertEqual(second["errors"], ["MARKET_RAW_ARCHIVE_CONFLICT"])
        self.assertEqual(archived.read_bytes(), b"corrupt archive")

    def test_input_byte_and_quote_row_bounds(self):
        with patch("scalper_research.market.MAX_ROWS", 2):
            with self.assertRaisesRegex(DataError, "MARKET_ROW_LIMIT"):
                load_quotes(self.csv, self.meta)
        with patch("scalper_research.market.MAX_BYTES", 8):
            with self.assertRaisesRegex(DataError, "INPUT_TOO_LARGE"):
                load_quotes(self.csv, self.meta)

    def test_user_unverified_origin_gets_explicit_rights_flag(self):
        self.write(metadata=quote_metadata(data_origin="user_supplied_unverified", usage_rights="not_verified"))
        dataset = load_quotes(self.csv, self.meta)
        self.assertIn("USAGE_RIGHTS_NOT_VERIFIED", dataset.quality_flags)
        self.assertNotIn("SYNTHETIC_FIXTURE_NOT_MARKET_HISTORY", dataset.quality_flags)


if __name__ == "__main__":
    unittest.main()
