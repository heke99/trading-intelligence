"""Synthetic local BI5 regressions; no provider data or network requests."""
import csv
import hashlib
import json
import lzma
import struct
import tempfile
import unittest
from decimal import Decimal, localcontext
from pathlib import Path
from unittest.mock import patch

from scalper_research.bi5 import convert_bi5
from scalper_research.market import load_quotes
from tests.test_market_ticks import quote_metadata


def bi5_spec(**overrides):
    """Fictional instrument, source and rights evidence, never actual market data."""
    return {
        "schema_version": 1,
        "format": "dukascopy_bi5_20byte_be",
        "time_base": "utc_hour",
        "base_time_msc": 1_704_067_200_000,
        "price_divisor": 100_000,
        "price_scale_evidence": "Fictional binary generator multiplied price by 100000.",
        "source_metadata": quote_metadata(),
        **overrides,
    }


def fictional_bi5(rows=None, *, compression_format=lzma.FORMAT_ALONE):
    rows = rows if rows is not None else [
        (1, 100_003, 100_001, 0.75, 0.5),
        (123, 100_004, 100_002, 1.25, 0.0),
        (456, 100_004, 100_004, 2.5, 0.125),
    ]
    return lzma.compress(b"".join(struct.pack(">IIIff", *row) for row in rows),
                         format=compression_format)


class Bi5Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # This filename deliberately suggests the wrong clock and instrument.
        self.file = self.root / "OTHER_1990_23h_ticks.bi5"
        self.spec = self.root / "spec.json"
        self.out = self.root / "converted"
        self.write()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, raw=None, specification=None):
        self.file.write_bytes(raw if raw is not None else fictional_bi5())
        self.spec.write_text(json.dumps(specification if specification is not None else bi5_spec()),
                             encoding="utf-8")

    def run_conversion(self):
        return convert_bi5(self.file, self.spec, self.out)

    def assert_failed(self, code):
        manifest = self.run_conversion()
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(manifest["errors"], [code])
        self.assertIsNone(manifest["output_csv"])
        self.assertIsNone(manifest["output_metadata"])
        self.assertEqual(Path(manifest["raw_bi5_path"]).read_bytes(), self.file.read_bytes())
        self.assertEqual(Path(manifest["raw_spec_path"]).read_bytes(), self.spec.read_bytes())
        self.assertEqual(json.loads(Path(manifest["manifest_path"]).read_text()), manifest)
        self.assertFalse(manifest["training_ready"])
        return manifest

    def test_hourly_exact_quotes_and_binary_evidence_survive_conversion(self):
        result = self.run_conversion()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["quote_count"], 3)
        dataset = load_quotes(Path(result["output_csv"]), Path(result["output_metadata"]))
        self.assertEqual([q.time_msc for q in dataset.quotes], [
            1_704_067_200_001, 1_704_067_200_123, 1_704_067_200_456])
        self.assertEqual([q.bid for q in dataset.quotes], [Decimal("1.00001"),
            Decimal("1.00002"), Decimal("1.00004")])
        self.assertEqual([q.ask for q in dataset.quotes], [Decimal("1.00003"),
            Decimal("1.00004"), Decimal("1.00004")])
        self.assertEqual(result["first_time_utc"], "2024-01-01T00:00:00.001Z")
        self.assertEqual(result["max_gap_ms"], 333)
        self.assertEqual(Path(result["raw_bi5_path"]).read_bytes(), self.file.read_bytes())
        evidence = [json.loads(row) for row in Path(result["row_evidence_path"]).read_text().splitlines()]
        self.assertEqual([row["source_record_index"] for row in evidence], [1, 2, 3])
        self.assertEqual([row["decompressed_byte_offset"] for row in evidence], [0, 20, 40])
        self.assertEqual(evidence[0]["ask_integer"], 100_003)
        self.assertEqual(evidence[0]["ask_volume_float32"], "0.75")
        self.assertEqual(evidence[0]["ask_volume_float32_bytes_hex"], "3f400000")
        self.assertEqual(evidence[0]["volume_interpretation"], "source_float32_not_executable_liquidity")
        self.assertEqual(result["output_csv_sha256"],
                         hashlib.sha256(Path(result["output_csv"]).read_bytes()).hexdigest())

    def test_daily_clock_uses_explicit_base_and_not_hourly_filename(self):
        self.write(fictional_bi5([(86_399_999, 2_000_100, 2_000_000, 0.25, 0.25)]),
                   bi5_spec(time_base="utc_day", price_divisor=1000))
        result = self.run_conversion()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["first_time_utc"], "2024-01-01T23:59:59.999Z")
        dataset = load_quotes(Path(result["output_csv"]), Path(result["output_metadata"]))
        self.assertEqual(dataset.quotes[0].ask, Decimal("2000.1"))

    def test_equal_clocks_and_identical_rows_preserve_physical_order(self):
        self.write(fictional_bi5([(1, 110, 100, 0.5, 0.25), (1, 110, 100, 0.5, 0.25),
                                (1, 130, 120, 0.25, 0.5)]))
        result = self.run_conversion()
        self.assertEqual(result["quote_count"], 3)
        self.assertEqual(result["duplicate_timestamp_rows"], 2)
        self.assertIn("EQUAL_TIMESTAMP_ORDER_UNVERIFIED", result["quality_flags"])
        dataset = load_quotes(Path(result["output_csv"]), Path(result["output_metadata"]))
        self.assertEqual([q.bid for q in dataset.quotes], [Decimal("0.001"),
                         Decimal("0.001"), Decimal("0.0012")])

    def test_prices_are_exact_under_low_ambient_decimal_precision(self):
        self.write(fictional_bi5([(1, 4_294_967_295, 4_294_967_294, 0.25, 0.25)]),
                   bi5_spec(price_divisor=1_000_000_000))
        with localcontext() as context:
            context.prec = 2
            context.Emax, context.Emin = 2, -2
            result = self.run_conversion()
        self.assertEqual(result["status"], "completed")
        with Path(result["output_csv"]).open(newline="") as source:
            row = next(csv.DictReader(source))
        self.assertEqual(row["ask"], "4.294967295")
        self.assertEqual(row["bid"], "4.294967294")

    def test_clock_base_and_price_scale_are_never_inferred(self):
        for field, value, code in (
            ("format", None, "BI5_FORMAT_REQUIRED"),
            ("time_base", None, "BI5_TIME_BASE_REQUIRED"),
            ("time_base", "local_hour", "BI5_TIME_BASE_REQUIRED"),
            ("price_divisor", 0, "BI5_PRICE_DIVISOR_INVALID"),
            ("price_divisor", 3, "BI5_PRICE_DIVISOR_INVALID"),
            ("price_divisor", True, "BI5_PRICE_DIVISOR_INVALID"),
            ("price_divisor", 10_000_000_000, "BI5_PRICE_DIVISOR_INVALID"),
            ("price_scale_evidence", "", "BI5_PRICE_SCALE_EVIDENCE_REQUIRED"),
            ("base_time_msc", 1_704_067_200_001, "BI5_UTC_BASE_BOUNDARY_INVALID"),
            ("base_time_msc", True, "BI5_UTC_BASE_BOUNDARY_INVALID"),
            ("base_time_msc", -3_600_000, "BI5_UTC_BASE_BOUNDARY_INVALID"),
            ("schema_version", True, "BI5_SPECIFICATION_VERSION"),
            ("source_metadata", None, "BI5_SOURCE_METADATA_REQUIRED"),
        ):
            with self.subTest(field=field, value=value):
                self.write(specification=bi5_spec(**{field: value}))
                self.assert_failed(code)

    def test_day_start_must_be_day_boundary(self):
        self.write(specification=bi5_spec(time_base="utc_day", base_time_msc=1_704_070_800_000))
        self.assert_failed("BI5_UTC_BASE_BOUNDARY_INVALID")

    def test_metadata_clock_evidence_and_unearned_verification_claims_rejected(self):
        for override in ({"timestamp_basis": "broker_local"}, {"timezone_evidence": ""},
                         {"training_ready": True}, {"broker_verified": True},
                         {"full_history_verified": True}, {"data_origin": "broker_verified"}):
            with self.subTest(override=override):
                self.write(specification=bi5_spec(source_metadata=quote_metadata(**override)))
                result = self.run_conversion()
                self.assertEqual(result["status"], "failed")
                self.assertIsNone(result["output_csv"])

    def test_unverified_rights_remain_unverified_without_becoming_training_permission(self):
        self.write(specification=bi5_spec(source_metadata=quote_metadata(
            data_origin="user_supplied_unverified", usage_rights="not_verified")))
        result = self.run_conversion()
        self.assertEqual(result["status"], "completed")
        self.assertIn("USAGE_RIGHTS_NOT_VERIFIED", result["quality_flags"])
        metadata = json.loads(Path(result["output_metadata"]).read_text())
        self.assertEqual(metadata["usage_rights"], "not_verified")
        self.assertEqual(metadata["data_origin"], "user_supplied_unverified")
        self.assertEqual(metadata["training_rights"], "not_verified")
        self.assertFalse(metadata["training_ready"])
        self.assertIsNone(metadata["bi5_conversion"]["original_retrieved_at_utc"])

    def test_explicit_user_usage_assertion_is_preserved_with_training_still_unverified(self):
        self.write(specification=bi5_spec(source_metadata=quote_metadata(
            data_origin="user_supplied_unverified", usage_rights="user_asserted_permitted",
            rights_evidence="Fictional user permission statement for local replay only.")))
        result = self.run_conversion()
        metadata = json.loads(Path(result["output_metadata"]).read_text())
        self.assertEqual(metadata["usage_rights"], "user_asserted_permitted")
        self.assertEqual(metadata["rights_evidence"],
                         "Fictional user permission statement for local replay only.")
        self.assertEqual(result["training_rights"], "not_verified")

    def test_derived_metadata_cannot_echo_training_or_trading_claims(self):
        self.write(specification=bi5_spec(source_metadata=quote_metadata(
            model_trained=True, trading_enabled=True, training_rights="permitted")))
        result = self.run_conversion()
        metadata = json.loads(Path(result["output_metadata"]).read_text())
        self.assertFalse(metadata["model_trained"])
        self.assertFalse(metadata["trading_enabled"])
        self.assertEqual(metadata["training_rights"], "not_verified")

    def test_bad_record_clock_price_or_volume_fails_with_no_partial_quote_publication(self):
        for row, code in (
            ((3_600_000, 110, 100, 0.5, 0.5), "BI5_OFFSET_OUTSIDE_TIME_BASE"),
            ((0, 110, 100, 0.5, 0.5), "BI5_CLOCK_NOT_NONDECREASING"),
            ((2, 0, 100, 0.5, 0.5), "BI5_PRICE_NONPOSITIVE"),
            ((2, 100, 110, 0.5, 0.5), "BI5_CROSSED_QUOTE"),
            ((2, 110, 100, float("nan"), 0.5), "BI5_VOLUME_INVALID"),
            ((2, 110, 100, 0.5, float("inf")), "BI5_VOLUME_INVALID"),
            ((2, 110, 100, -0.5, 0.5), "BI5_VOLUME_INVALID"),
        ):
            with self.subTest(row=row):
                self.write(fictional_bi5([(1, 110, 100, 0.5, 0.5), row]))
                result = self.assert_failed(code)
                run_dir = Path(result["manifest_path"]).parent
                self.assertFalse((run_dir / "quotes.csv").exists())
                self.assertFalse((run_dir / "row_evidence.jsonl").exists())
                self.assertEqual(list(run_dir.glob(".quotes-*")), [])

    def test_malformed_incomplete_and_empty_compressed_inputs_fail(self):
        for raw, code in (
            (b"", "BI5_COMPRESSED_EMPTY"),
            (b"not-lzma", "BI5_LZMA_INVALID_OR_MEMORY_LIMIT"),
            (fictional_bi5()[:-1], "BI5_LZMA_TRUNCATED"),
            (lzma.compress(b"bad record", format=lzma.FORMAT_ALONE), "BI5_RECORD_SIZE_INVALID"),
            (fictional_bi5([]), "BI5_NO_QUOTES"),
        ):
            with self.subTest(code=code):
                self.write(raw)
                self.assert_failed(code)

    def test_concatenated_streams_and_trailing_bytes_cannot_hide_extra_records(self):
        for suffix in (fictional_bi5(), b"extra bytes", b"\x00\x00\x00\x00"):
            with self.subTest(suffix_length=len(suffix)):
                self.write(fictional_bi5() + suffix)
                self.assert_failed("BI5_COMPRESSED_TRAILING_DATA")

    def test_controlled_xz_container_is_accepted_without_guessing_raw_lzma_filters(self):
        self.write(fictional_bi5(compression_format=lzma.FORMAT_XZ))
        result = self.run_conversion()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["quote_count"], 3)
        raw_stream = lzma.compress(b"x" * 20, format=lzma.FORMAT_RAW,
                                  filters=[{"id": lzma.FILTER_LZMA1, "dict_size": 4096}])
        self.write(raw_stream)
        self.assert_failed("BI5_LZMA_INVALID_OR_MEMORY_LIMIT")

    def test_decompressed_record_and_input_bounds_are_enforced(self):
        with patch("scalper_research.bi5.MAX_DECOMPRESSED_BYTES", 40):
            self.assert_failed("BI5_DECOMPRESSED_SIZE_LIMIT")
        with patch("scalper_research.bi5.MAX_RECORDS", 2):
            self.assert_failed("BI5_RECORD_LIMIT")
        with patch("scalper_research.bi5.MAX_INPUT_BYTES", 8):
            result = self.run_conversion()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["errors"], ["BI5_INPUT_TOO_LARGE"])
        self.assertIsNone(result["source_bi5_sha256"])

    def test_lzma_dictionary_memory_limit_prevents_large_allocations(self):
        compressed = bytearray(fictional_bi5())
        compressed[1:5] = struct.pack("<I", 128 * 1024 * 1024)
        self.write(bytes(compressed))
        self.assert_failed("BI5_LZMA_INVALID_OR_MEMORY_LIMIT")

    def test_immutable_archive_is_reused_and_corruption_never_overwritten(self):
        first = self.run_conversion()
        second = self.run_conversion()
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertEqual(first["raw_bi5_path"], second["raw_bi5_path"])
        self.assertEqual(first["raw_spec_path"], second["raw_spec_path"])
        self.assertEqual(first["output_csv_sha256"], second["output_csv_sha256"])
        archived = Path(first["raw_bi5_path"])
        archived.write_bytes(b"tampered")
        result = self.run_conversion()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["errors"], ["MARKET_RAW_ARCHIVE_CONFLICT"])
        self.assertEqual(archived.read_bytes(), b"tampered")

    def test_missing_spec_retains_original_binary_with_failed_receipt(self):
        self.spec.unlink()
        result = self.run_conversion()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["errors"], ["BI5_INPUT_READ_FAILED"])
        self.assertEqual(Path(result["raw_bi5_path"]).read_bytes(), self.file.read_bytes())
        self.assertIsNone(result["raw_spec_path"])

    def test_spec_duplicate_keys_rejects_interpretation_but_retains_bytes(self):
        self.spec.write_bytes(b'{"schema_version":1,"schema_version":1}')
        self.assert_failed("JSON_DUPLICATE_KEY")


if __name__ == "__main__":
    unittest.main()
