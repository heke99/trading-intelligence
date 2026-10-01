"""Synthetic regressions found during the independent publisher review."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from trading_intelligence.common import DataError
from trading_intelligence.publisher_pipeline import import_publisher_evidence, import_trader_xlsx
from trading_intelligence.publisher_store import PublisherStore
from trading_intelligence.trader_acquisition import download_trader_sources
from test_trader_acquisition import Response, URL
from test_publisher_evidence import artifact, image_row
from test_trader_xlsx import day_row, source, write_xlsx


class PublisherReviewRegressions(unittest.TestCase):
    def test_interrupt_preserves_partial_download_receipt_and_stops_batch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            specifications = [source(identifier) for identifier in (
                "hougaard_2021_08", "hougaard_2021_09", "hougaard_2021_10")]
            for specification in specifications:
                specification.update(local_filename=specification["id"] + ".xlsx", xlsx_url=URL)
            catalog = root / "catalog.json"
            catalog.write_text(json.dumps({"downloadable_sources": specifications}))
            workbook = root / "synthetic.xlsx"
            write_xlsx(workbook, {"Aug 2021 Day": {9: day_row()}})
            content = workbook.read_bytes()
            calls = []

            def transport(url, timeout):
                calls.append(url)
                if len(calls) > 1:
                    raise KeyboardInterrupt()
                return Response(content)

            try:
                result = download_trader_sources(catalog, root / "out", transport=transport)
            except KeyboardInterrupt:
                self.fail("Interruption escaped before the partial receipt was written")

            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["errors"], ["INTERRUPTED"])
            self.assertEqual(len(calls), 2)
            receipts = list((root / "out").glob("download_manifest_*.json"))
            self.assertEqual(len(receipts), 1)
            entries = json.loads(receipts[0].read_text())
            self.assertEqual(entries, result["entries"])
            self.assertEqual([entry["status"] for entry in entries],
                             ["succeeded", "failed", "not_attempted"])
            self.assertEqual(entries[1]["reason"], "INTERRUPTED")
            self.assertIsNotNone(entries[0]["retrieved_at_utc"])
            self.assertEqual((root / "out" / specifications[0]["local_filename"]).read_bytes(), content)

    def test_cell_type_change_creates_reviewable_semantic_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            specification = source()
            specification["local_filename"] = "synthetic.xlsx"
            catalog = root / "catalog.json"
            catalog.write_text(json.dumps({"downloadable_sources": [specification]}))
            workbook = root / "synthetic.xlsx"
            rows = {"Aug 2021 Day": {9: day_row(I="1")}}
            write_xlsx(workbook, rows)
            first = import_trader_xlsx(catalog, root, root / "out", synthetic=True)

            # Boolean true has the same visible raw text as the preceding
            # numeric-looking string, but the adapter must refuse it as a price.
            write_xlsx(workbook, rows, types={("Aug 2021 Day", "I9"): "b"})
            changed = import_trader_xlsx(catalog, root, root / "out", synthetic=True)

            self.assertNotEqual(first["source_summaries"][0]["semantic_sha256"],
                                changed["source_summaries"][0]["semantic_sha256"])
            self.assertEqual(changed["inserted_versions"], 1)
            self.assertEqual(changed["revision_observations"], 1)
            self.assertIn("SOURCE_REVISION_REQUIRES_REVIEW", changed["blockers"])
            with PublisherStore(root / "out") as store:
                versions = [json.loads(value) for (value,) in store.conn.execute(
                    "SELECT normalized_json FROM publisher_record_versions ORDER BY id")]
                completed = store.conn.execute(
                    "SELECT count(*) FROM completed_publisher_records").fetchone()[0]
            self.assertEqual([version["entry_price"] for version in versions], ["1", None])
            self.assertIn("ENTRY_PRICE_CELL_TYPE_UNSUPPORTED", versions[1]["quality_flags"])
            self.assertEqual(completed, 2)

    def test_each_row_receipt_hash_checked_when_asset_path_is_reused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = root / "fixture-only" / "image01.png"
            asset.parent.mkdir()
            content = b"\x89PNG\r\n\x1a\nsynthetic review fixture"
            asset.write_bytes(content)
            digest = hashlib.sha256(content).hexdigest()
            first = image_row(source_asset_sha256=digest)
            first["physical_row_ref"] = first["physical_row_ref"].replace("a" * 64, digest)
            second = copy.deepcopy(first)
            second["source_row"] = 2
            second["source_asset_sha256"] = "b" * 64
            second["physical_row_ref"] = second["physical_row_ref"].replace(
                digest, "b" * 64).replace("image-data-row=1", "image-data-row=2")
            source = root / "fixture.jsonl"
            source.write_bytes(artifact([first, second]))

            with self.assertRaisesRegex(DataError, "IMAGE_ASSET_HASH_OR_FORMAT_MISMATCH"):
                import_publisher_evidence(
                    source, root / "out", kind="image_transactions",
                    source_id="fictional_review_image", synthetic=True, assets_root=root)


if __name__ == "__main__":
    unittest.main()
