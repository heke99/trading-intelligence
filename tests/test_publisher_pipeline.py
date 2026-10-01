"""Offline behavior tests with entirely synthetic spreadsheets/evidence."""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_DEFLATED

from trading_intelligence.cli import main
from trading_intelligence.common import DataError
from trading_intelligence.publisher_pipeline import import_trader_xlsx, import_publisher_evidence, publisher_status
from trading_intelligence.publisher_store import PublisherStore
from test_trader_xlsx import day_row, source, write_xlsx
from test_publisher_evidence import artifact, journal_row, teaching_card, image_row


class PublisherPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.out = self.root / "data"
        self.raw = self.root / "input"
        self.raw.mkdir()
        self.spec = source()
        self.spec["local_filename"] = "fixture.xlsx"
        self.catalog = self.root / "catalog.json"
        self.catalog.write_text(json.dumps({"downloadable_sources": [self.spec]}))
        self.file = self.raw / self.spec["local_filename"]
        self.rows = {9: day_row()}
        self.write()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, compression=0):
        write_xlsx(self.file, {"Aug 2021 Day": self.rows}, compression=compression)

    def import_book(self, **kwargs):
        return import_trader_xlsx(self.catalog, self.raw, self.out, synthetic=True, **kwargs)

    def versions(self):
        with PublisherStore(self.out) as store:
            return store.conn.execute("SELECT count(*) FROM publisher_record_versions").fetchone()[0]

    def test_reimport_and_byte_only_repack_preserve_one_semantic_version(self):
        first = self.import_book()
        second = self.import_book()
        self.write(ZIP_DEFLATED)
        third = self.import_book()
        self.assertEqual(first["inserted_versions"], 1)
        self.assertEqual(second["inserted_versions"], 0)
        self.assertEqual(second["duplicate_observations"], 1)
        self.assertEqual(third["inserted_versions"], 0)
        self.assertEqual(third["inserted_snapshots"], 1)
        self.assertEqual(self.versions(), 1)
        counts = publisher_status(self.out)["database_counts"]
        self.assertEqual(counts["publisher_snapshots"], 2)
        self.assertEqual(counts["publisher_occurrences"], 3)

    def test_revision_keeps_old_values_and_review_flag_on_reimport(self):
        self.import_book()
        self.rows[9]["I"] = "101"
        self.write()
        changed = self.import_book()
        repeated = self.import_book()
        self.assertEqual(changed["revision_observations"], 1)
        self.assertEqual(self.versions(), 2)
        self.assertIn("SOURCE_REVISION_REQUIRES_REVIEW", repeated["blockers"])
        self.assertEqual(repeated["quality_flag_counts"]["SOURCE_REVISION_REQUIRES_REVIEW"], 1)
        with PublisherStore(self.out) as store:
            values = [json.loads(value)["entry_price"] for (value,) in store.conn.execute(
                "SELECT normalized_json FROM publisher_record_versions ORDER BY id")]
        self.assertEqual(values, ["100.00", "101"])

    def test_identical_physical_rows_and_multiple_exit_legs_are_preserved(self):
        self.rows[10] = copy.deepcopy(self.rows[9])
        self.rows[11] = day_row(T="110", U="0.75")
        self.write()
        result = self.import_book()
        self.assertEqual(result["source_rows"], 3)
        self.assertEqual(result["inserted_versions"], 3)
        self.assertEqual(result["entry_link_groups"], 1)
        self.assertEqual(result["ambiguous_entry_link_groups"], [])

    def test_same_entry_link_with_changed_entry_is_flagged_not_merged(self):
        self.rows[10] = day_row(I="102")
        self.write()
        result = self.import_book()
        self.assertEqual(result["source_rows"], 2)
        self.assertEqual(len(result["ambiguous_entry_link_groups"]), 1)
        self.assertEqual(self.versions(), 2)

    def test_missing_later_source_keeps_failed_evidence_out_of_completed_view(self):
        extra = source("hougaard_2021_09")
        extra["local_filename"] = "missing.xlsx"
        self.catalog.write_text(json.dumps({"downloadable_sources": [self.spec, extra]}))
        with self.assertRaises(FileNotFoundError):
            self.import_book()
        report = publisher_status(self.out)
        self.assertEqual(report["latest_run"]["status"], "failed")
        self.assertEqual(report["database_counts"]["publisher_record_versions"], 1)
        self.assertEqual(report["database_counts"]["completed_publisher_records"], 0)
        write_xlsx(self.raw / "missing.xlsx", {"Sep 2021 Day": {9: day_row()}})
        completed = self.import_book()
        self.assertEqual(completed["duplicate_observations"], 1)
        self.assertEqual(publisher_status(self.out)["database_counts"]["completed_publisher_records"], 2)

    def test_corrupt_archived_bytes_rejected_without_overwriting(self):
        self.import_book()
        archived = next((self.out / "raw").glob("*.xlsx"))
        archived.write_bytes(b"corrupt fixture")
        with self.assertRaisesRegex(DataError, "RAW_HASH_MISMATCH"):
            self.import_book()
        self.assertEqual(archived.read_bytes(), b"corrupt fixture")
        self.assertEqual(publisher_status(self.out)["latest_run"]["status"], "failed")

    def test_synthetic_origin_separate_from_unverified_source_origin(self):
        self.import_book()
        other = import_trader_xlsx(self.catalog, self.raw, self.out)
        self.assertEqual(other["inserted_versions"], 1)
        self.assertEqual(self.versions(), 2)
        with PublisherStore(self.out) as store:
            origins = {value for (value,) in store.conn.execute("SELECT data_origin FROM publisher_record_versions")}
        self.assertEqual(origins, {"synthetic_fixture", "publisher_reported_unverified"})

    def test_temporal_quarantine_retains_negative_raw_not_overwritten(self):
        self.rows[9]["U"] = "0.25"
        self.write()
        result = self.import_book()
        self.assertEqual(result["temporal_quarantined_rows"], 1)
        self.assertEqual(result["status"], "completed_with_quarantine")
        values = json.loads((self.out / "publisher-runs" / result["run_id"] / "observations.jsonl").read_text())
        self.assertEqual(values["mapped_raw_fields"]["exit_time"], "0.25")
        self.assertIsNone(values["exit_at_utc"])
        self.assertFalse(values["training_ready"])

    def test_publisher_records_never_enter_c2_completed_view(self):
        self.import_book()
        with PublisherStore(self.out) as store:
            self.assertEqual(store.count_completed_run_records(), 0)
            self.assertEqual(store.count_versions(), 0)
        self.assertFalse(publisher_status(self.out)["training_ready"])

    def test_catalog_path_and_selection_fail_closed(self):
        with self.assertRaisesRegex(DataError, "TRADER_SOURCE_NOT_IN_CATALOG"):
            self.import_book(source_ids=["absent"])
        self.spec["local_filename"] = "../outside.xlsx"
        self.catalog.write_text(json.dumps({"downloadable_sources": [self.spec]}))
        with self.assertRaisesRegex(DataError, "TRADER_SOURCE_FILENAME_INVALID"):
            self.import_book()

    def test_download_clock_not_filled_from_import_or_file_mtime(self):
        result = self.import_book()
        self.assertIsNone(result["source_summaries"][0]["original_retrieved_at_utc"])
        self.assertTrue(result["started_at_utc"])

    def test_journal_and_education_import_do_not_become_c2_trades(self):
        path = self.root / "journal.jsonl"
        path.write_bytes(artifact([journal_row()]))
        first = import_publisher_evidence(path, self.out, kind="journal_summaries", source_id="fictional_journal", synthetic=True)
        second = import_publisher_evidence(path, self.out, kind="journal_summaries", source_id="fictional_journal", synthetic=True)
        self.assertEqual(first["source_rows"], 1)
        self.assertEqual(second["inserted_versions"], 0)
        path = self.root / "cards.json"
        path.write_text(json.dumps({"schema_version": "1.0", "training_ready": False, "cards": [teaching_card()]}))
        cards = import_publisher_evidence(path, self.out, kind="strategy_cards", source_id="fictional_teaching", synthetic=True)
        self.assertEqual(cards["source_rows"], 1)
        self.assertFalse(cards["training_ready"])
        with PublisherStore(self.out) as store:
            self.assertEqual(store.count_versions(), 0)

    def test_image_asset_hash_verified_and_bad_hash_rejected(self):
        import hashlib
        asset = self.root / "fixture-only" / "image01.png"
        asset.parent.mkdir()
        # Deliberately synthetic PNG signature bytes; pixel meaning is never inferred here.
        content = b"\x89PNG\r\n\x1a\nsynthetic fixture"
        asset.write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        row = image_row(source_asset_sha256=digest)
        row["physical_row_ref"] = row["physical_row_ref"].replace("a" * 64, digest)
        path = self.root / "image.jsonl"
        path.write_bytes(artifact([row]))
        report = import_publisher_evidence(path, self.out, kind="image_transactions", source_id="fictional_image", synthetic=True, assets_root=self.root)
        self.assertEqual(report["source_summaries"][0]["original_assets_hash_verified"], 1)
        asset.write_bytes(b"\x89PNG\r\n\x1a\nchanged")
        with self.assertRaisesRegex(DataError, "IMAGE_ASSET_HASH_OR_FORMAT_MISMATCH"):
            import_publisher_evidence(path, self.out, kind="image_transactions", source_id="fictional_image", synthetic=True, assets_root=self.root)

    def test_new_cli_is_offline_and_c2_status_namespace_is_unchanged(self):
        output = io.StringIO()
        with patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")), contextlib.redirect_stdout(output):
            code = main(["import-trader-xlsx", "--catalog", str(self.catalog), "--raw-dir", str(self.raw),
                         "--out", str(self.out), "--synthetic-fixture"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["source_rows"], 1)
        self.assertFalse(list((self.out / "runs").glob("*/manifest.json")))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["publisher-status", "--out", str(self.out)]), 0)

    def test_download_cli_reports_partial_failure_without_network(self):
        result = {"status": "failed", "errors": ["SOURCE_HTTP_403"], "entries": [],
                  "receipt_path": "fictional-receipt.json", "training_ready": False}
        with patch("trading_intelligence.cli.download_trader_sources", return_value=result), contextlib.redirect_stdout(io.StringIO()) as output:
            code = main(["download-trader-sources", "--catalog", str(self.catalog), "--out", str(self.raw)])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["errors"], ["SOURCE_HTTP_403"])

    def test_download_cli_interruption_keeps_receipt_and_returns_130(self):
        result = {"status": "failed", "errors": ["INTERRUPTED"], "entries": [],
                  "receipt_path": "fictional-receipt.json", "training_ready": False}
        with patch("trading_intelligence.cli.download_trader_sources", return_value=result), contextlib.redirect_stdout(io.StringIO()) as output:
            code = main(["download-trader-sources", "--catalog", str(self.catalog), "--out", str(self.raw)])
        self.assertEqual(code, 130)
        self.assertEqual(json.loads(output.getvalue())["receipt_path"], "fictional-receipt.json")


if __name__ == "__main__":
    unittest.main()
