"""Hand-calculated fixtures for local HistData clock and provenance conversion."""
from __future__ import annotations

import hashlib
import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scalper_research import histdata
from scalper_research.market import load_quotes
from trading_intelligence.common import json_bytes


class HistDataImportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.csv = self.root / "ticks.csv"
        self.spec = self.root / "spec.json"
        self.out = self.root / "out"

    def make_spec(self, raw: bytes) -> dict:
        return {
            "schema_version": 1,
            "format": "histdata_generic_ascii_tick_v1",
            "source_file_sha256": hashlib.sha256(raw).hexdigest(),
            "symbol": "EURUSD",
            "native_timestamp_basis": "fixed_est_milliseconds",
            "native_timezone_utc_offset_minutes": -300,
            "source_clock_evidence": (
                "Synthetic fixture follows HistData fixed EST without DST: "
                "https://www.histdata.com/f-a-q/"
            ),
            "source": {
                "schema_version": 1,
                "source_id": "histdata.synthetic",
                "symbol": "EURUSD",
                "price_currency": "USD",
                "timestamp_basis": "utc_epoch_milliseconds",
                "timezone_evidence": "Synthetic fixed UTC-05 fixture",
                "data_origin": "synthetic_fixture",
                "usage_rights": "synthetic_only",
            },
        }

    def convert(self, raw: bytes, *, specification: dict | None = None) -> dict:
        self.csv.write_bytes(raw)
        # ASCII escapes deliberately let malformed surrogate strings reach
        # the converter's decoder; json_bytes cannot serialize those fixtures.
        document = specification if specification is not None else self.make_spec(raw)
        self.spec.write_bytes(
            (json.dumps(document, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode("ascii")
        )
        return histdata.import_histdata(self.csv, self.spec, self.out)

    def failed(self, manifest: dict, error: str) -> None:
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(manifest["errors"], [error])
        self.assertEqual(manifest["quote_count"], 0)
        self.assertEqual(manifest["source_count"], 0)
        for field in ("quotes_csv_path", "quotes_metadata_path", "native_ticks_path"):
            self.assertIsNone(manifest[field])
        run = Path(manifest["manifest_path"]).parent
        self.assertFalse((run / "dataset").exists())
        self.assertFalse(any(run.glob(".histdata-*")))
        self.assertEqual(json.loads(Path(manifest["manifest_path"]).read_text()), manifest)

    def test_fixed_est_is_plus_five_hours_in_winter_and_summer(self):
        for native, expected in (
            ("20250115 090000007", "2025-01-15T14:00:00.007Z"),
            ("20250715 090000007", "2025-07-15T14:00:00.007Z"),
        ):
            with self.subTest(native=native):
                result = self.convert(f"{native},1.100000,1.100200,0\n".encode())
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["first_time_utc"], expected)
                self.assertEqual(result["last_time_utc"], expected)
                self.assertEqual(result["native_timezone_utc_offset_minutes"], -300)

    def test_rollover_equal_clocks_and_decimal_spelling_are_preserved(self):
        raw = (
            b"20170101 235959999,1.100000,1.100200,0.000\n"
            b"20170102 000000000,1.100010,1.100210,0\n"
            b"20170102 000000000,1.100020,1.100220,0\n"
        )
        result = self.convert(raw)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["first_time_utc"], "2017-01-02T04:59:59.999Z")
        self.assertEqual(result["last_time_utc"], "2017-01-02T05:00:00.000Z")
        self.assertEqual(result["quote_count"], 3)
        self.assertEqual(result["duplicate_timestamp_rows"], 1)
        self.assertEqual(result["max_gap_ms"], 1)
        native = [json.loads(line) for line in Path(result["native_ticks_path"]).read_text().splitlines()]
        self.assertEqual([row["source_row"] for row in native], [1, 2, 3])
        self.assertEqual([row["native_time_text"] for row in native], [
            "20170101 235959999", "20170102 000000000", "20170102 000000000",
        ])
        self.assertEqual(native[0]["raw_bid"], "1.100000")
        self.assertEqual(native[0]["raw_volume"], "0.000")
        self.assertEqual(native[1]["time_msc"], native[2]["time_msc"])
        quote_text = Path(result["quotes_csv_path"]).read_text()
        self.assertIn(",1.100000,1.100200\n", quote_text)
        dataset = load_quotes(
            Path(result["quotes_csv_path"]), Path(result["quotes_metadata_path"])
        )
        self.assertEqual([quote.source_row for quote in dataset.quotes], [2, 3, 4])
        self.assertIn("physical line - 1", dataset.metadata["derived_csv_source_row_rule"])
        self.assertIn("EQUAL_TIMESTAMP_ORDER_UNVERIFIED", result["quality_flags"])

    def test_original_bytes_spec_and_all_output_hashes_are_exact(self):
        raw = b"20170101 000000001,1.100000,1.100200,0\r\n"
        result = self.convert(raw)
        self.assertEqual(result["status"], "completed")
        for path_field, digest_field in (
            ("raw_csv_path", "source_file_sha256"),
            ("raw_spec_path", "spec_sha256"),
            ("quotes_csv_path", "quotes_csv_sha256"),
            ("quotes_metadata_path", "quotes_metadata_sha256"),
            ("native_ticks_path", "native_ticks_sha256"),
        ):
            path = Path(result[path_field])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), result[digest_field])
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o400)
        self.assertEqual(Path(result["raw_csv_path"]).read_bytes(), raw)
        self.assertEqual(Path(result["raw_spec_path"]).read_bytes(), self.spec.read_bytes())
        again = histdata.import_histdata(self.csv, self.spec, self.out)
        self.assertEqual(again["raw_csv_path"], result["raw_csv_path"])
        self.assertNotEqual(again["manifest_path"], result["manifest_path"])

    def test_unsupported_source_claims_never_reach_derived_metadata_or_receipt(self):
        raw = b"20170101 000000001,1.1,1.2,0\n"
        spec = self.make_spec(raw)
        claims = {
            "model_trained": True, "real_market_model_trained": True,
            "trading_enabled": True, "training_ready": True,
            "broker_verified": True, "full_history_verified": True,
            "expert_trade_history": True, "forward_verified": True,
            "broker_orders_sent": True, "automated_download_permitted": True,
            "rights_verified": True,
        }
        spec["source"].update(claims)
        spec["source"]["secret_extra_claim"] = "must stay only in original spec"
        result = self.convert(raw, specification=spec)
        self.assertEqual(result["status"], "completed")
        metadata = json.loads(Path(result["quotes_metadata_path"]).read_text())
        original = json.loads(Path(result["raw_spec_path"]).read_text())
        for field in claims:
            self.assertIs(result[field], False)
            self.assertIs(metadata[field], False)
            self.assertIs(original["source"][field], True)
        self.assertNotIn("secret_extra_claim", metadata)
        self.assertEqual(result["network_requests"], 0)
        self.assertEqual(result["downloaded_bytes"], 0)

    def test_user_supplied_rights_remain_unverified(self):
        raw = b"20170101 000000001,1.1,1.2,0\n"
        spec = self.make_spec(raw)
        spec["source"].update(data_origin="user_supplied_unverified", usage_rights="not_verified")
        result = self.convert(raw, specification=spec)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["usage_rights"], "not_verified")
        self.assertIs(result["rights_verified"], False)
        self.assertIn("USAGE_RIGHTS_NOT_VERIFIED", result["quality_flags"])

    def test_source_hash_mismatch_preserves_inputs_but_publishes_no_dataset(self):
        raw = b"20170101 000000001,1.1,1.2,0\n"
        spec = self.make_spec(raw)
        spec["source_file_sha256"] = "0" * 64
        result = self.convert(raw, specification=spec)
        self.failed(result, "HISTDATA_SOURCE_HASH_MISMATCH")
        self.assertEqual(Path(result["raw_csv_path"]).read_bytes(), raw)
        self.assertTrue(Path(result["raw_spec_path"]).is_file())
        self.assertIs(result["source_hash_matches_spec"], False)

    def test_crossed_later_row_leaves_no_partial_publication(self):
        raw = (
            b"20170101 000000001,1.1,1.2,0\n"
            b"20170101 000000002,1.3,1.2,0\n"
        )
        self.failed(self.convert(raw), "MARKET_CROSSED_QUOTE")

    def test_decreasing_native_clock_is_rejected_without_sorting(self):
        raw = (
            b"20170101 000000002,1.1,1.2,0\n"
            b"20170101 000000001,1.1,1.2,0\n"
        )
        self.failed(self.convert(raw), "MARKET_CLOCK_NOT_NONDECREASING")

    def test_headers_wrong_precision_and_invalid_calendar_dates_are_rejected(self):
        for raw in (
            b"DateTime,Bid,Ask,Volume\n",
            b"20170101 000000000001,1.1,1.2,0\n",
            b"20170231 000000001,1.1,1.2,0\n",
        ):
            with self.subTest(raw=raw):
                self.failed(self.convert(raw), "HISTDATA_TIMESTAMP_INVALID")

    def test_zip_and_non_ascii_are_rejected_without_extraction(self):
        for raw, error in (
            (b"PK\x03\x04not-a-local-csv", "HISTDATA_CSV_REQUIRED"),
            (b"\xef\xbb\xbf20170101 000000001,1.1,1.2,0\n", "HISTDATA_CSV_ENCODING"),
        ):
            with self.subTest(error=error):
                self.failed(self.convert(raw), error)

    def test_unsupported_rows_numbers_and_multiline_records_fail(self):
        cases = (
            (b"20170101 000000001,1.1,1.2\n", "HISTDATA_CSV_ROW_SCHEMA"),
            (b"20170101 000000001,NaN,1.2,0\n", "HISTDATA_NUMBER_INVALID"),
            (b"20170101 000000001,1.1,1.2,-1\n", "HISTDATA_NUMBER_INVALID"),
            (b'"20170101\n000000001",1.1,1.2,0\n', "HISTDATA_CSV_ROW_SCHEMA"),
        )
        for raw, error in cases:
            with self.subTest(error=error):
                self.failed(self.convert(raw), error)

    def test_nonzero_volume_is_archived_but_never_used_as_trade_volume(self):
        raw = b"20170101 000000001,1.1,1.2,4.2500\n"
        result = self.convert(raw)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["nonzero_native_volume_rows"], 1)
        record = json.loads(Path(result["native_ticks_path"]).read_text())
        self.assertEqual(record["raw_volume"], "4.2500")
        self.assertIs(record["volume_feature_present"], False)
        metadata = json.loads(Path(result["quotes_metadata_path"]).read_text())
        self.assertIs(metadata["volume_feature_present"], False)
        self.assertIs(metadata["orderflow_feature_present"], False)
        self.assertNotIn("volume", Path(result["quotes_csv_path"]).read_text().splitlines()[0])
        self.assertIn("NONZERO_NATIVE_VOLUME_UNVERIFIED_NOT_USED", result["quality_flags"])

    def test_local_input_and_derived_evidence_limits_fail_cleanly(self):
        raw = b"20170101 000000001,1,2,0\n"
        for attribute, limit, error in (
            ("MAX_BYTES", len(raw) - 1, "INPUT_TOO_LARGE"),
            ("MAX_BYTES", len(raw), "HISTDATA_DERIVED_CSV_TOO_LARGE"),
            ("MAX_NATIVE_BYTES", 10, "HISTDATA_NATIVE_EVIDENCE_TOO_LARGE"),
        ):
            with self.subTest(attribute=attribute, limit=limit):
                with patch.object(histdata, attribute, limit):
                    self.failed(self.convert(raw), error)
        self.assertEqual(histdata.MAX_BYTES, 32 * 1024 * 1024)
        self.assertEqual(histdata.MAX_ROWS, 500_000)

    def test_row_limit_is_enforced_before_publishing(self):
        raw = (
            b"20170101 000000001,1.1,1.2,0\n"
            b"20170101 000000002,1.1,1.2,0\n"
        )
        with patch.object(histdata, "MAX_ROWS", 1):
            self.failed(self.convert(raw), "HISTDATA_ROW_LIMIT")

    def test_explicit_clock_and_symbol_contract_rejects_wrong_types(self):
        raw = b"20170101 000000001,1.1,1.2,0\n"
        for key, value, error in (
            ("schema_version", True, "HISTDATA_SPEC_VERSION"),
            ("symbol", [], "HISTDATA_SYMBOL_UNSUPPORTED"),
            ("native_timestamp_basis", "America/New_York", "HISTDATA_CLOCK_BASIS_REQUIRED"),
            ("native_timezone_utc_offset_minutes", -240, "HISTDATA_FIXED_EST_REQUIRED"),
            ("native_timezone_utc_offset_minutes", False, "HISTDATA_FIXED_EST_REQUIRED"),
            ("source_clock_evidence", "", "HISTDATA_CLOCK_EVIDENCE_REQUIRED"),
            ("source_clock_evidence", "\x00malformed", "HISTDATA_CLOCK_EVIDENCE_REQUIRED"),
            ("source_clock_evidence", "\x7f", "HISTDATA_CLOCK_EVIDENCE_REQUIRED"),
            ("source_clock_evidence", "\x85", "HISTDATA_CLOCK_EVIDENCE_REQUIRED"),
            ("source_clock_evidence", "\ud800", "HISTDATA_CLOCK_EVIDENCE_REQUIRED"),
            ("source", [], "HISTDATA_SOURCE_SCHEMA"),
        ):
            with self.subTest(key=key, value=value):
                spec = self.make_spec(raw)
                spec[key] = value
                self.failed(self.convert(raw, specification=spec), error)

    def test_explicit_price_currency_must_match_instrument(self):
        raw = b"20170101 000000001,1.1,1.2,0\n"
        spec = self.make_spec(raw)
        spec["source"]["price_currency"] = "JPY"
        self.failed(self.convert(raw, specification=spec), "HISTDATA_PRICE_CURRENCY_MISMATCH")

    def test_empty_csv_produces_failure_receipt_without_a_quote_file(self):
        self.failed(self.convert(b""), "MARKET_NO_QUOTES")


    def test_explicit_replay_training_assertions_and_provenance_are_retained(self):
        raw = b"20170101 000000001,1.1,1.2,0\n"
        spec = self.make_spec(raw)
        explicit = {
            "data_origin": "user_supplied_unverified",
            "usage_rights": "user_asserted_permitted",
            "rights_evidence": "Synthetic test assertion: local replay is permitted.",
            "training_usage_rights": "user_asserted_permitted",
            "training_rights_evidence": "Synthetic test assertion: local training is permitted.",
            "attribution": "HistData.com; publisher/file authenticity is not verified.",
            "source_url": "https://www.histdata.com/",
            "source_record_url": "https://www.histdata.com/f-a-q/data-files-detailed-specification/",
            "source_download_url": "https://example.invalid/synthetic-fixture.csv",
            "license": "not_verified",
            "license_url": "https://www.histdata.com/f-a-q/",
            "license_evidence": "No open raw-data license has been established.",
        }
        spec["source"].update(explicit)
        result = self.convert(raw, specification=spec)
        self.assertEqual(result["status"], "completed")
        metadata = json.loads(Path(result["quotes_metadata_path"]).read_text())
        for key, value in explicit.items():
            self.assertEqual(metadata.get(key), value)
        for field in ("training_ready", "model_trained", "trading_enabled", "rights_verified"):
            self.assertIs(result[field], False)
            self.assertIs(metadata[field], False)

    def test_interrupt_after_archive_finishes_failed_receipt(self):
        raw = b"20170101 000000001,1.1,1.2,0\n"
        with patch.object(histdata, "_convert", side_effect=KeyboardInterrupt):
            try:
                result = self.convert(raw)
            except KeyboardInterrupt:
                manifests = list((self.out / "histdata-runs").glob("*/manifest.json"))
                self.assertEqual(len(manifests), 1)
                result = json.loads(manifests[0].read_text())
        self.failed(result, "INTERRUPTED")
        self.assertIsNotNone(result["completed_at_utc"])
        self.assertEqual(Path(result["raw_csv_path"]).read_bytes(), raw)
        self.assertTrue(Path(result["raw_spec_path"]).is_file())



    def test_absent_training_assertion_stays_absent(self):
        result = self.convert(b"20170101 000000001,1.1,1.2,0\n")
        self.assertEqual(result["status"], "completed")
        metadata = json.loads(Path(result["quotes_metadata_path"]).read_text())
        self.assertNotIn("training_usage_rights", metadata)
        self.assertNotIn("training_rights_evidence", metadata)

    def test_explicit_training_assertions_reject_invalid_enum_origin_or_evidence(self):
        raw = b"20170101 000000001,1.1,1.2,0\n"
        cases = (
            ({"training_usage_rights": True}, "HISTDATA_TRAINING_RIGHTS_INVALID"),
            ({"training_usage_rights": []}, "HISTDATA_TRAINING_RIGHTS_INVALID"),
            ({"training_usage_rights": "open_by_default"}, "HISTDATA_TRAINING_RIGHTS_INVALID"),
            ({"training_usage_rights": "user_asserted_permitted"},
             "HISTDATA_TRAINING_RIGHTS_EVIDENCE_REQUIRED"),
            ({"training_usage_rights": "user_asserted_permitted", "training_rights_evidence": " "},
             "HISTDATA_TRAINING_RIGHTS_EVIDENCE_REQUIRED"),
            ({"training_usage_rights": "user_asserted_permitted", "training_rights_evidence": "\x00"},
             "HISTDATA_TRAINING_RIGHTS_EVIDENCE_REQUIRED"),
            ({"training_usage_rights": "user_asserted_permitted", "training_rights_evidence": "x" * 4097},
             "HISTDATA_TRAINING_RIGHTS_EVIDENCE_REQUIRED"),
            ({"data_origin": "user_supplied_unverified", "usage_rights": "not_verified",
              "training_usage_rights": "synthetic_only"},
             "HISTDATA_TRAINING_RIGHTS_ORIGIN_CONFLICT"),
        )
        for source_change, error in cases:
            with self.subTest(source_change=source_change):
                spec = self.make_spec(raw)
                spec["source"].update(source_change)
                self.failed(self.convert(raw, specification=spec), error)

    def test_provenance_is_bounded_text_and_never_implies_automatic_access(self):
        raw = b"20170101 000000001,1.1,1.2,0\n"
        for field, value in (
            ("attribution", 123), ("source_url", "\x00"),
            ("source_record_url", " "), ("source_download_url", []),
            ("license", "x" * 4097), ("license_url", "\x1f"),
            ("license_evidence", ""),
            ("attribution", "\x7f"), ("source_url", "\x85"),
            ("source_record_url", "\ud800"),
        ):
            with self.subTest(field=field):
                spec = self.make_spec(raw)
                spec["source"][field] = value
                self.failed(
                    self.convert(raw, specification=spec), "HISTDATA_SOURCE_PROVENANCE_INVALID"
                )
        spec = self.make_spec(raw)
        spec["source"]["attribution"] = "Synthetic test attribution.\nTab\tallowed."
        spec["source"]["training_usage_rights"] = "not_verified"
        result = self.convert(raw, specification=spec)
        self.assertEqual(result["status"], "completed")
        metadata = json.loads(Path(result["quotes_metadata_path"]).read_text())
        self.assertEqual(metadata["attribution"], spec["source"]["attribution"])
        self.assertEqual(metadata["training_usage_rights"], "not_verified")
        self.assertIs(metadata["automated_download_permitted"], False)
        self.assertIs(metadata["rights_verified"], False)



    def test_escaped_surrogate_in_required_source_metadata_finishes_receipt(self):
        raw = b"20170101 000000001,1.1,1.2,0\n"
        for field in ("source_id", "rights_evidence"):
            with self.subTest(field=field):
                spec = self.make_spec(raw)
                spec["source"][field] = "\ud800"
                if field == "rights_evidence":
                    spec["source"].update(
                        data_origin="user_supplied_unverified",
                        usage_rights="user_asserted_permitted",
                    )
                self.failed(self.convert(raw, specification=spec), "HISTDATA_SOURCE_SCHEMA")


if __name__ == "__main__":
    unittest.main()
