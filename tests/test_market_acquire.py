"""Synthetic byte streams and mocked HTTP only; no provider files or network."""
import hashlib
import http.client
import io
import json
import os
import ssl
import tempfile
import unittest
from dataclasses import asdict, replace
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from scalper_research import acquire
from trading_intelligence.common import DataError, json_bytes


class Response:
    def __init__(self, chunks, *, url=acquire.WSE_DATA_URL, status=200, headers=None):
        self.chunks = list(chunks)
        self.url, self.status = url, status
        self.headers = Message()
        for name, value in headers or []:
            self.headers[name] = value
        self.read_sizes, self.closed = [], False

    def geturl(self):
        return self.url

    def read(self, size):
        self.read_sizes.append(size)
        if not self.chunks:
            return b""
        value = self.chunks.pop(0)
        if isinstance(value, BaseException):
            raise value
        if len(value) > size:
            self.chunks.insert(0, value[size:])
            value = value[:size]
        return value

    def close(self):
        self.closed = True


class MarketAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.raw = b"fictional byte fixture; never market history\n"
        self.contract = replace(acquire._WSE_CONTRACT, expected_bytes=len(self.raw),
                                expected_sha256=hashlib.sha256(self.raw).hexdigest(),
                                source_id="synthetic_acquisition_fixture", synthetic_fixture=True,
                                license="synthetic_only", attribution="Synthetic test generator.")

    def tearDown(self):
        self.tmp.cleanup()

    def run_stream(self, chunks=None, **kwargs):
        response = Response(chunks if chunks is not None else [self.raw], **kwargs)
        opener = Mock(return_value=response)
        result = acquire._acquire(self.root / "out", self.contract, opener)
        self.assertEqual(json.loads(Path(result["manifest_path"]).read_text()), result)
        self.assertFalse(result["training_ready"])
        self.assertFalse(result["full_history_verified"])
        self.assertFalse(result["actual_market_binary_downloaded"])
        self.assertTrue(response.closed)
        opener.assert_called_once_with(acquire.WSE_DATA_URL)
        return result, response

    def assert_failure(self, result, code):
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["errors"], [code])
        self.assertIsNone(result["data_path"])
        self.assertIsNone(result["data_sha256"])
        self.assertIsNone(result["verified_data_sha256"])
        self.assertIsNone(result["data_bytes"])
        if result["partial_path"]:
            partial = Path(result["partial_path"]).read_bytes()
            self.assertEqual(result["partial_sha256"], hashlib.sha256(partial).hexdigest())
            self.assertEqual(result["stored_partial_bytes"], len(partial))

    def target(self):
        path = self.root / "out" / "raw" / "wse" / (self.contract.expected_sha256 + ".h5")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def test_default_source_contract_is_fixed_and_hash_bound(self):
        self.assertEqual(acquire.WSE_EXPECTED_BYTES, 152759953)
        self.assertEqual(acquire.WSE_EXPECTED_SHA256,
                         "3c418a55a492ebe2e39c8513cd7fc7e3e6827dc1a176af09fdcaad9f3485bae6")
        self.assertEqual(acquire.WSE_SOURCE_CONTRACT_SHA256,
                         "199031aeafdf75181d5e5ff0fc7e222debda866fce8b8cafd713543d29a53bb7")
        self.assertEqual(acquire.WSE_SOURCE_CONTRACT_SHA256,
                         hashlib.sha256(json_bytes(asdict(acquire._WSE_CONTRACT))).hexdigest())
        with patch.object(acquire, "_acquire", return_value={"status": "offline_stub"}) as call:
            self.assertEqual(acquire.acquire_wse(self.root), {"status": "offline_stub"})
            self.assertEqual(call.call_args.args, (self.root, acquire._WSE_CONTRACT, acquire._open_source))

    def test_success_preserves_exact_bytes_license_receipt_and_read_only_raw(self):
        result, response = self.run_stream([self.raw[:2], self.raw[2:9], self.raw[9:]])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(Path(result["data_path"]).read_bytes(), self.raw)
        self.assertEqual(result["data_sha256"], self.contract.expected_sha256)
        self.assertEqual(result["data_bytes"], len(self.raw))
        self.assertEqual(result["downloaded_bytes"], len(self.raw))
        self.assertEqual(Path(result["data_path"]).stat().st_mode & 0o777, 0o400)
        self.assertTrue(result["response_eof_observed"])
        self.assertIsNone(result["partial_path"])
        self.assertEqual(result["source_contract_sha256"],
                         hashlib.sha256(Path(result["source_contract_path"]).read_bytes()).hexdigest())
        self.assertTrue(all(0 < n <= 64 * 1024 for n in response.read_sizes))

    def test_synthetic_large_stream_is_read_in_64k_chunks(self):
        self.raw = b"synthetic" * 20000
        self.contract = replace(self.contract, expected_bytes=len(self.raw),
                                expected_sha256=hashlib.sha256(self.raw).hexdigest())
        result, response = self.run_stream()
        self.assertEqual(result["status"], "completed")
        self.assertGreater(len(response.read_sizes), 3)
        self.assertEqual(max(response.read_sizes), 65536)

    def test_short_eof_and_wrong_hash_never_claim_complete_data(self):
        for chunks, code in (([self.raw[:-1]], "ACQUIRE_DOWNLOADED_SIZE_MISMATCH"),
                             ([b"x" * len(self.raw)], "ACQUIRE_DOWNLOADED_HASH_MISMATCH")):
            with self.subTest(code=code):
                result, _ = self.run_stream(chunks)
                self.assert_failure(result, code)

    def test_matching_size_and_hash_without_eof_still_fails(self):
        result, _ = self.run_stream([self.raw, TimeoutError("do not log secret")])
        self.assert_failure(result, "ACQUIRE_TIMEOUT")
        self.assertFalse(result["response_eof_observed"])
        self.assertEqual(result["partial_sha256"], self.contract.expected_sha256)
        self.assertNotIn("do not log secret", json.dumps(result))

    def test_interruption_preserves_only_actual_prefix(self):
        result, _ = self.run_stream([self.raw[:7], KeyboardInterrupt()])
        self.assert_failure(result, "ACQUIRE_INTERRUPTED")
        self.assertEqual(Path(result["partial_path"]).read_bytes(), self.raw[:7])

    def test_incomplete_read_retains_exception_prefix_but_no_complete_hash(self):
        result, _ = self.run_stream([self.raw[:5], http.client.IncompleteRead(self.raw[5:10], 10)])
        self.assert_failure(result, "ACQUIRE_RESPONSE_INCOMPLETE")
        self.assertEqual(Path(result["partial_path"]).read_bytes(), self.raw[:10])

    def test_http_errors_and_redirects_close_and_never_retry(self):
        for status in (301, 302, 303, 307, 308, 401, 403, 429, 500):
            with self.subTest(status=status):
                body = io.BytesIO(b"remote error details must not appear")
                error = HTTPError(acquire.WSE_DATA_URL, status, "private token", Message(), body)
                opener = Mock(side_effect=error)
                result = acquire._acquire(self.root / "out", self.contract, opener)
                code = "ACQUIRE_REDIRECT_REJECTED" if status < 400 else f"ACQUIRE_HTTP_{status}"
                self.assert_failure(result, code)
                self.assertEqual(opener.call_count, 1)
                self.assertTrue(body.closed)
                self.assertNotIn("private token", json.dumps(result))
                self.assertEqual(result["received_bytes"], 0)

    def test_blocked_network_failure_is_audited_without_error_detail(self):
        opener = Mock(side_effect=URLError("sensitive environment detail"))
        result = acquire._acquire(self.root / "out", self.contract, opener)
        self.assert_failure(result, "ACQUIRE_NETWORK_BLOCKED_OR_UNAVAILABLE")
        self.assertTrue(result["network_attempted"])
        self.assertNotIn("sensitive environment", json.dumps(result))
        self.assertEqual(opener.call_count, 1)

    def test_tls_failure_never_claims_verified_transport(self):
        result = acquire._acquire(self.root / "out", self.contract,
                                  Mock(side_effect=ssl.SSLError("sensitive cert detail")))
        self.assert_failure(result, "ACQUIRE_TLS_FAILED")
        self.assertFalse(result["transport_tls_verified"])

    def test_invalid_length_encoding_and_ambiguous_transfer_fail_before_read(self):
        cases = [
            ([("Content-Length", "-1")], "ACQUIRE_CONTENT_LENGTH_INVALID"),
            ([("Content-Length", "1e2")], "ACQUIRE_CONTENT_LENGTH_INVALID"),
            ([("Content-Length", str(len(self.raw))), ("Content-Length", str(len(self.raw)))],
             "ACQUIRE_CONTENT_LENGTH_INVALID"),
            ([("Content-Length", str(acquire.MAX_ACQUISITION_BYTES + 1))], "ACQUIRE_RESPONSE_TOO_LARGE"),
            ([("Content-Length", str(len(self.raw) - 1))], "ACQUIRE_CONTENT_LENGTH_MISMATCH"),
            ([("Content-Encoding", "gzip")], "ACQUIRE_CONTENT_ENCODING_UNSUPPORTED"),
            ([("Content-Length", str(len(self.raw))), ("Transfer-Encoding", "chunked")],
             "ACQUIRE_TRANSFER_ENCODING_CONFLICT"),
        ]
        for headers, code in cases:
            with self.subTest(headers=headers):
                result, response = self.run_stream(headers=headers)
                self.assert_failure(result, code)
                self.assertEqual(response.read_sizes, [])

    def test_matching_content_length_and_chunked_without_length_are_accepted(self):
        for headers in ([("Content-Length", str(len(self.raw)))], [("Transfer-Encoding", "chunked")]):
            with self.subTest(headers=headers):
                result, _ = self.run_stream(headers=headers)
                self.assertEqual(result["status"], "completed")
                # A later case must exercise its own response, not cache reuse.
                Path(result["data_path"]).unlink()

    def test_forged_final_url_and_partial_status_are_rejected_before_body(self):
        result, response = self.run_stream(url="https://unvetted.invalid/private?secret=value")
        self.assert_failure(result, "ACQUIRE_REDIRECT_REJECTED")
        self.assertEqual(response.read_sizes, [])
        self.assertNotIn("unvetted", json.dumps(result))
        result, response = self.run_stream(status=206)
        self.assert_failure(result, "ACQUIRE_HTTP_STATUS_INVALID")
        self.assertEqual(response.read_sizes, [])

    def test_cap_preserves_bounded_prefix_and_labels_discarded_byte(self):
        self.raw = b"abcde"
        self.contract = replace(self.contract, expected_bytes=5,
                                expected_sha256=hashlib.sha256(self.raw).hexdigest())
        with patch.object(acquire, "MAX_ACQUISITION_BYTES", 5):
            result, _ = self.run_stream([self.raw + b"x"])
        self.assert_failure(result, "ACQUIRE_RESPONSE_TOO_LARGE")
        self.assertEqual(result["received_bytes"], 6)
        self.assertEqual(result["stored_partial_bytes"], 5)
        self.assertEqual(result["discarded_received_bytes"], 1)

    def test_existing_archive_is_rehashed_without_network_and_kept_immutable(self):
        target = self.target()
        target.write_bytes(self.raw)
        opener = Mock(side_effect=AssertionError("network must not run"))
        result = acquire._acquire(self.root / "out", self.contract, opener)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["acquisition_action"], "verified_existing_archive")
        self.assertEqual(result["data_bytes"], len(self.raw))
        self.assertEqual(result["downloaded_bytes"], 0)
        self.assertFalse(result["network_attempted"])
        opener.assert_not_called()

    def test_conflicting_archive_and_symlink_never_refetch_or_overwrite(self):
        target = self.target()
        target.write_bytes(b"x" * len(self.raw))
        opener = Mock(side_effect=AssertionError("network must not run"))
        result = acquire._acquire(self.root / "out", self.contract, opener)
        self.assert_failure(result, "ACQUIRE_RAW_ARCHIVE_CONFLICT")
        self.assertEqual(target.read_bytes(), b"x" * len(self.raw))
        opener.assert_not_called()
        target.unlink()
        outside = self.root / "outside"
        outside.write_bytes(self.raw)
        target.symlink_to(outside)
        result = acquire._acquire(self.root / "out", self.contract, opener)
        self.assert_failure(result, "ACQUIRE_RAW_ARCHIVE_CONFLICT")
        self.assertTrue(target.is_symlink())
        self.assertEqual(outside.read_bytes(), self.raw)

    def test_fresh_attempt_never_resumes_partial_and_preserves_earlier_receipt(self):
        failed, _ = self.run_stream([self.raw[:8], TimeoutError()])
        previous_receipt = Path(failed["manifest_path"]).read_bytes()
        success, _ = self.run_stream()
        self.assertEqual(success["status"], "completed")
        self.assertEqual(success["received_bytes"], len(self.raw))
        self.assertNotEqual(success["manifest_path"], failed["manifest_path"])
        self.assertEqual(Path(failed["manifest_path"]).read_bytes(), previous_receipt)
        self.assertEqual(Path(failed["partial_path"]).read_bytes(), self.raw[:8])

    def test_concurrent_good_archive_reuses_bytes_and_bad_archive_is_preserved(self):
        original_link = acquire.os.link
        for other in (self.raw, b"x" * len(self.raw)):
            with self.subTest(other_matches=other == self.raw):
                def raced_link(source, target):
                    Path(target).write_bytes(other)
                    return original_link(source, target)
                with patch.object(acquire.os, "link", side_effect=raced_link):
                    result, _ = self.run_stream()
                if other == self.raw:
                    self.assertEqual(result["status"], "completed")
                else:
                    self.assert_failure(result, "ACQUIRE_RAW_ARCHIVE_CONFLICT")
                self.assertEqual(self.target().read_bytes(), other)
                self.target().unlink()

    def test_fixed_contract_rejects_alternate_url_or_unbounded_expected_size(self):
        for contract, code in (
            (replace(self.contract, source_url="https://unvetted.invalid/data"), "ACQUIRE_FIXED_SOURCE_REQUIRED"),
            (replace(self.contract, expected_bytes=acquire.MAX_ACQUISITION_BYTES + 1), "ACQUIRE_EXPECTED_SIZE_INVALID"),
            (replace(self.contract, expected_sha256="bad"), "ACQUIRE_EXPECTED_HASH_INVALID"),
        ):
            with self.subTest(code=code):
                opener = Mock()
                result = acquire._acquire(self.root / "out", contract, opener)
                self.assert_failure(result, code)
                opener.assert_not_called()

    def test_transport_uses_verified_tls_and_no_proxy_auth_cookie_or_redirect_handler(self):
        opener = Mock()
        with patch.object(acquire, "build_opener", return_value=opener) as build:
            acquire._open_source(acquire.WSE_DATA_URL)
        proxy, https, redirects = build.call_args.args
        self.assertEqual(proxy.proxies, {})
        self.assertEqual(https._context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(https._context.check_hostname)
        self.assertIsNone(redirects.redirect_request(None, None, 302, None, None, "https://other.invalid"))
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, acquire.WSE_DATA_URL)
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 20)
        self.assertEqual(opener.addheaders, [])
        for header in ("Authorization", "Proxy-authorization", "Cookie"):
            self.assertIsNone(request.get_header(header))

    def test_http_protocol_errors_are_failed_receipts_before_and_after_prefix(self):
        opener = Mock(side_effect=http.client.BadStatusLine("private server data"))
        result = acquire._acquire(self.root / "out", self.contract, opener)
        self.assert_failure(result, "ACQUIRE_HTTP_PROTOCOL_ERROR")
        result, _ = self.run_stream([self.raw[:8], http.client.HTTPException("private server data")])
        self.assert_failure(result, "ACQUIRE_HTTP_PROTOCOL_ERROR")
        self.assertEqual(Path(result["partial_path"]).read_bytes(), self.raw[:8])

    def test_nonregular_cached_fifo_is_rejected_before_open(self):
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        with patch.object(acquire.os, "open", side_effect=AssertionError("must not open FIFO")):
            with self.assertRaisesRegex(DataError, "ACQUIRE_RAW_ARCHIVE_CONFLICT"):
                acquire._file_receipt(fifo)

    def test_local_sync_failure_is_not_reported_as_network_failure(self):
        real_fsync = acquire.os.fsync
        def fail_download_sync(descriptor):
            target = os.readlink(f"/proc/self/fd/{descriptor}")
            if target.endswith("download.partial"):
                raise OSError("disk full; sensitive path")
            return real_fsync(descriptor)
        with patch.object(acquire.os, "fsync", side_effect=fail_download_sync):
            result, _ = self.run_stream()
        self.assert_failure(result, "ACQUIRE_LOCAL_SYNC_FAILED")
        self.assertEqual(Path(result["partial_path"]).read_bytes(), self.raw)


if __name__ == "__main__":
    unittest.main()
