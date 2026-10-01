"""Acquisition safety tests; all responses and workbooks are synthetic/offline."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

from trading_intelligence.common import MAX_BYTES, DataError, sha256
from trading_intelligence.trader_acquisition import (
    _PublicExportRedirects, _export_url, download_trader_sources,
)
from trading_intelligence.trader_xlsx import _TIM_MAPS, _TOM_MONTHS
from test_trader_xlsx import day_row, source, tim_rows, write_xlsx

URL = "https://docs.google.com/spreadsheets/d/synthetic_fixture_document_0001/export?format=xlsx"


class Response(io.BytesIO):
    def __init__(self, raw, *, status=200, url=URL, headers=None):
        super().__init__(raw)
        self.status, self.url = status, url
        self.headers = headers or {}

    def geturl(self):
        return self.url


class TraderAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.catalog = self.root / "catalog.json"
        self.out = self.root / "downloads"
        self.spec = self.spec_for("hougaard_2021_08")
        self.catalog_for([self.spec])
        self.raw = self.book(self.spec)
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def spec_for(self, ident):
        spec = source(ident)
        spec.update(local_filename=f"{ident}.xlsx", xlsx_url=URL)
        return spec

    def catalog_for(self, sources):
        self.catalog.write_text(json.dumps({"downloadable_sources": sources}))

    def book(self, spec, rows=None):
        path = self.root / f"fixture_{spec['id']}.xlsx"
        if rows is None:
            rows = tim_rows(spec["id"]) if spec["id"] in _TIM_MAPS else {9: day_row()}
        write_xlsx(path, {spec["sheet_name"]: rows})
        return path.read_bytes()

    def transport(self, raw=None, **response_kwargs):
        def get(url, timeout):
            self.calls.append((url, timeout))
            return Response(self.raw if raw is None else raw, **response_kwargs)
        return get

    def run_download(self, **kwargs):
        return download_trader_sources(self.catalog, self.out, **kwargs)

    def assert_failure(self, result, reason):
        self.assertEqual(result["status"], "failed")
        self.assertIn(reason, result["errors"])
        self.assertFalse(result["training_ready"])
        self.assertFalse(result["full_history_verified"])
        self.assertFalse(result["trading_enabled"])
        self.assertEqual(json.loads(Path(result["receipt_path"]).read_text()), result["entries"])

    def test_download_exact_bytes_parse_and_hash_receipt(self):
        result = self.run_download(transport=self.transport())
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.calls, [(URL, 20)])
        entry = result["entries"][0]
        self.assertEqual((self.out / self.spec["local_filename"]).read_bytes(), self.raw)
        self.assertEqual(entry["sha256"], sha256(self.raw))
        self.assertEqual(entry["size_bytes"], len(self.raw))
        self.assertEqual(entry["source_rows"], 1)
        self.assertEqual(entry["acquisition_mode"], "public_http_download")
        self.assertTrue(entry["retrieved_at_utc"].endswith("+00:00"))
        self.assertEqual(json.loads(Path(result["receipt_path"]).read_text()), result["entries"])
        self.assertFalse(entry["broker_fill_verified"])
        self.assertFalse(result["training_ready"])

    def test_all_eight_reviewed_mapping_formats_are_supported(self):
        specs = [self.spec_for(ident) for ident in (*_TIM_MAPS, *_TOM_MONTHS)]
        self.catalog_for(specs)
        books = [self.book(spec) for spec in specs]
        def get(url, timeout):
            self.calls.append((url, timeout))
            return Response(books[len(self.calls) - 1])
        result = self.run_download(transport=get)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["entries"]), 8)
        self.assertEqual(len(self.calls), 8)
        self.assertTrue(all(entry["source_rows"] == 1 for entry in result["entries"]))

    def test_existing_original_is_revalidated_without_network_or_mtime_clock(self):
        self.out.mkdir()
        (self.out / self.spec["local_filename"]).write_bytes(self.raw)
        with patch("trading_intelligence.trader_acquisition._default_transport", side_effect=AssertionError("network")):
            result = self.run_download()
        entry = result["entries"][0]
        self.assertEqual(result["status"], "completed")
        self.assertIsNone(entry["retrieved_at_utc"])
        self.assertEqual(entry["acquisition_mode"], "existing_file_revalidated")

    def test_invalid_existing_file_preserved_and_never_refetched(self):
        self.out.mkdir()
        path = self.out / self.spec["local_filename"]
        path.write_bytes(b"original invalid evidence")
        result = self.run_download(transport=self.transport())
        self.assertEqual(result["status"], "failed")
        self.assertEqual(path.read_bytes(), b"original invalid evidence")
        self.assertEqual(self.calls, [])

    def test_200_html_stub_is_failure_without_final_file(self):
        result = self.run_download(transport=self.transport(b"<html>Site Unavailable</html>"))
        self.assert_failure(result, "SOURCE_RESPONSE_NOT_XLSX")
        self.assertFalse((self.out / self.spec["local_filename"]).exists())

    def test_html_mime_and_zip_magic_alone_do_not_pass(self):
        for raw, headers, reason in (
            (self.raw, {"Content-Type": "text/html; charset=UTF-8"}, "SOURCE_RESPONSE_NOT_XLSX"),
            (b"PK\x03\x04not a workbook", {}, "XLSX_PACKAGE_INVALID"),
        ):
            with self.subTest(reason=reason):
                result = self.run_download(transport=self.transport(raw, headers=headers))
                self.assert_failure(result, reason)
                self.assertFalse((self.out / self.spec["local_filename"]).exists())

    def test_oversized_content_length_and_body_are_rejected(self):
        result = self.run_download(transport=self.transport(headers={"Content-Length": str(MAX_BYTES + 1)}))
        self.assert_failure(result, "SOURCE_RESPONSE_TOO_LARGE")
        result = self.run_download(transport=self.transport(b"x" * (MAX_BYTES + 1)))
        self.assert_failure(result, "SOURCE_RESPONSE_TOO_LARGE")
        self.assertFalse((self.out / self.spec["local_filename"]).exists())

    def test_unauthorized_forbidden_and_rate_limit_stop_without_retry(self):
        second = self.spec_for("hougaard_2021_09")
        self.catalog_for([self.spec, second])
        for status in (401, 403, 429):
            with self.subTest(status=status):
                self.calls.clear()
                result = self.run_download(transport=self.transport(status=status))
                self.assert_failure(result, f"SOURCE_HTTP_{status}")
                self.assertEqual(len(self.calls), 1)
                self.assertEqual(result["entries"][1]["status"], "not_attempted")

    def test_http_error_object_and_network_failure_are_safe_codes(self):
        for error, code in (
            (HTTPError(URL, 403, "sensitive response", {}, None), "SOURCE_HTTP_403"),
            (URLError("sensitive endpoint or credentials"), "SOURCE_NETWORK_ERROR"),
            (TimeoutError("private diagnostic"), "SOURCE_NETWORK_TIMEOUT"),
        ):
            with self.subTest(code=code):
                def get(url, timeout):
                    raise error
                result = self.run_download(transport=get)
                self.assert_failure(result, code)
                self.assertNotIn("sensitive", Path(result["receipt_path"]).read_text())

    def test_partial_success_is_preserved_then_batch_stops(self):
        second = self.spec_for("hougaard_2021_09")
        third = self.spec_for("hougaard_2021_10")
        self.catalog_for([self.spec, second, third])
        def get(url, timeout):
            self.calls.append(url)
            return Response(self.raw, status=200 if len(self.calls) == 1 else 403)
        result = self.run_download(transport=get)
        self.assert_failure(result, "SOURCE_HTTP_403")
        self.assertEqual(len(self.calls), 2)
        self.assertEqual((self.out / self.spec["local_filename"]).read_bytes(), self.raw)
        self.assertEqual([entry["status"] for entry in result["entries"]],
                         ["succeeded", "failed", "not_attempted"])

    def test_bad_catalog_urls_are_rejected_before_any_network(self):
        for url in (
            URL.replace("https:", "http:"), URL.replace("docs.google.com", "evil.example"),
            URL + "&authuser=1", URL + "#fragment", URL.replace("format=xlsx", "format=csv"),
            URL.replace("docs.google.com", "user:password@docs.google.com"),
            URL.replace("docs.google.com", "docs.google.com:443"),
            URL.replace("/export?", "/edit?"),
        ):
            with self.subTest(url=url):
                self.spec["xlsx_url"] = url
                self.catalog_for([self.spec])
                result = self.run_download(transport=self.transport())
                self.assert_failure(result, "TRADER_SOURCE_URL_INVALID")
                self.assertEqual(self.calls, [])

    def test_mapping_and_filename_conflicts_fail_before_network(self):
        self.spec["columns"]["entry_price"] = "A"
        self.catalog_for([self.spec])
        result = self.run_download(transport=self.transport())
        self.assert_failure(result, "TRADER_COLUMN_MAPPING_MISMATCH")
        self.assertEqual(self.calls, [])
        self.spec = self.spec_for("hougaard_2021_08")
        second = self.spec_for("hougaard_2021_09")
        second["local_filename"] = self.spec["local_filename"]
        self.catalog_for([self.spec, second])
        result = self.run_download(transport=self.transport())
        self.assert_failure(result, "TRADER_SOURCE_FILENAME_DUPLICATE")

    def test_selection_is_explicit_and_unknown_or_duplicate_ids_fail(self):
        second = self.spec_for("hougaard_2021_09")
        self.catalog_for([self.spec, second])
        result = self.run_download(source_ids=[self.spec["id"]], transport=self.transport())
        self.assertEqual([entry["id"] for entry in result["entries"]], [self.spec["id"]])
        for ids, code in (([], "TRADER_SOURCE_SELECTION_EMPTY"),
                          (["unknown"], "TRADER_SOURCE_NOT_IN_CATALOG"),
                          ([self.spec["id"], self.spec["id"]], "TRADER_SOURCE_SELECTION_DUPLICATE")):
            with self.subTest(ids=ids):
                self.calls.clear()
                result = self.run_download(source_ids=ids, transport=self.transport())
                self.assert_failure(result, code)
                self.assertEqual(self.calls, [])

    def test_redirect_rejects_login_and_arbitrary_hosts_before_following(self):
        req = Request(URL)
        for url in (
            "https://accounts.google.com/ServiceLogin", "https://evil.example/export/data",
            "https://doc-abc-sheets.googleusercontent.com.evil.example/export/data",
            "http://doc-abc-sheets.googleusercontent.com/export/data",
            "https://user:password@doc-abc-sheets.googleusercontent.com/export/data",
            "https://doc-abc-sheets.googleusercontent.com/ServiceLogin",
            "https://doc-abc-sheets.googleusercontent.com/export/%2e%2e/ServiceLogin",
        ):
            with self.subTest(url=url):
                with self.assertRaisesRegex(DataError, "SOURCE_REDIRECT_NOT_PUBLIC_EXPORT"):
                    _PublicExportRedirects().redirect_request(req, None, 302, "Found", {}, url)
        public = "https://doc-0a-xyz-sheets.googleusercontent.com/export/public-id?format=xlsx"
        self.assertEqual(_PublicExportRedirects().redirect_request(req, None, 302, "Found", {}, public).full_url,
                         public)
        self.assertEqual(_export_url(URL), URL)

    def test_final_destination_is_checked_even_for_injected_transport(self):
        result = self.run_download(transport=self.transport(url="https://accounts.google.com/ServiceLogin"))
        self.assert_failure(result, "SOURCE_REDIRECT_NOT_PUBLIC_EXPORT")
        self.assertFalse((self.out / self.spec["local_filename"]).exists())

    def test_symlink_is_not_followed_and_conflicting_race_never_overwrites(self):
        self.out.mkdir()
        outside = self.root / "outside.xlsx"
        outside.write_bytes(self.raw)
        path = self.out / self.spec["local_filename"]
        path.symlink_to(outside)
        result = self.run_download(transport=self.transport())
        self.assert_failure(result, "SOURCE_FILE_CONFLICT")
        self.assertEqual(self.calls, [])
        path.unlink()
        real_link = os.link
        def conflict_link(src, dst):
            Path(dst).write_bytes(b"another original")
            return real_link(src, dst)
        with patch("trading_intelligence.trader_acquisition.os.link", side_effect=conflict_link):
            result = self.run_download(transport=self.transport())
        self.assert_failure(result, "SOURCE_FILE_CONFLICT")
        self.assertEqual(path.read_bytes(), b"another original")
        self.assertFalse(list(self.out.glob(".source-*")))

    def test_wrong_workbook_schema_never_becomes_completed_download(self):
        path = self.root / "wrong.xlsx"
        write_xlsx(path, {"Unrelated": {9: day_row()}})
        result = self.run_download(transport=self.transport(path.read_bytes()))
        self.assert_failure(result, "TRADER_EXPECTED_SHEET_MISSING")
        self.assertFalse((self.out / self.spec["local_filename"]).exists())
        self.assertFalse(list(self.out.glob(".source-*")))


if __name__ == "__main__":
    unittest.main()
