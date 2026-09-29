"""Offline authorization diagnostics using synthetic responses only."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from trading_intelligence.cli import main
from trading_intelligence.collective2 import Response, HTTPSGetTransport
from trading_intelligence.common import DataError
from trading_intelligence.diagnostics import diagnose_access


KEY = "synthetic-diagnostic-key"


def response(rows=None, code="200"):
    body = {"Results": rows if rows is not None else [],
            "ResponseStatus": {"ErrorCode": code}}
    return Response(200, {"content-type": "application/json"}, json.dumps(body).encode())


def key_response(**overrides):
    return response([{"AccessKey": KEY, "Role": "Developer", "Email": "PRIVATE_EMAIL",
                      "PersonId": 987654, "Comment": "PRIVATE_COMMENT",
                      "Message": "PRIVATE_MESSAGE", "DeleteDate": None, **overrides}])


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, headers):
        self.calls.append((url, headers.copy()))
        return self.responses.pop(0)


class DiagnosticsTests(unittest.TestCase):
    def run_probe(self, responses, **kwargs):
        transport = FakeTransport(responses)
        result = diagnose_access(KEY, 123, transport=transport, **kwargs)
        return result, transport

    def test_three_documented_gets_and_no_saved_data(self):
        result, transport = self.run_probe([key_response(), response([{"Id": 1}]), response()])
        self.assertTrue(result["access_checks_passed"])
        self.assertFalse(result["data_saved"])
        self.assertFalse(result["training_ready"])
        self.assertFalse(result["full_history_verified"])
        self.assertEqual(result["scope"], "access_probes_not_full_history")
        paths = [urlsplit(url).path for url, _ in transport.calls]
        self.assertEqual(paths, ["/General/GetAccessKey",
                                 "/Strategies/GetStrategyHistoricalClosedTrades",
                                 "/Strategies/GetStrategyHistoricalOrders"])
        for url, headers in transport.calls:
            self.assertEqual(urlsplit(url).netloc, "api4-general.collective2.com")
            self.assertNotIn(KEY, url)
            self.assertEqual(headers["Authorization"], "Bearer " + KEY)
            self.assertEqual(headers["Content-Type"], "application/json")
            self.assertEqual(headers["Accept"], "application/json")
        self.assertEqual(parse_qs(urlsplit(transport.calls[0][0]).query), {})
        self.assertEqual(parse_qs(urlsplit(transport.calls[1][0]).query),
                         {"StrategyId": ["123"], "CommissionPlan": ["0"]})
        self.assertEqual(parse_qs(urlsplit(transport.calls[2][0]).query),
                         {"StrategyId": ["123"], "Limit": ["1"], "AscendingOrder": ["true"]})
        self.assertEqual(result["checks"][0]["key_role"], "Developer")

    def test_no_credentials_personal_fields_or_trade_rows_in_report(self):
        result, _ = self.run_probe([key_response(), response([{"Symbol": "PRIVATE_TRADE"}]), response()])
        rendered = json.dumps(result)
        for secret in [KEY, "PRIVATE_EMAIL", "987654", "PRIVATE_COMMENT", "PRIVATE_MESSAGE", "PRIVATE_TRADE", "AccessKey"]:
            self.assertNotIn(secret, rendered.replace("GetAccessKey", ""))

    def test_each_403_is_reported_per_endpoint_without_retry_or_body(self):
        result, transport = self.run_probe([key_response(),
            Response(403, {"x-private": KEY}, KEY.encode()),
            Response(403, {}, b"PRIVATE_BODY")])
        self.assertFalse(result["access_checks_passed"])
        self.assertEqual([check["status"] for check in result["checks"]], ["ok", "error", "error"])
        self.assertEqual(result["checks"][1]["error"], "HTTP_403")
        self.assertEqual(result["checks"][1]["http_status"], 403)
        self.assertEqual(len(transport.calls), 3)
        self.assertNotIn(KEY, json.dumps(result))
        self.assertNotIn("PRIVATE_BODY", json.dumps(result))

    def test_key_failure_does_not_skip_independent_history_probes(self):
        result, _ = self.run_probe([Response(403, {}, b"private"), response(), response()])
        self.assertEqual(result["checks"][0]["error"], "HTTP_403")
        self.assertEqual([check["status"] for check in result["checks"]], ["error", "ok", "ok"])

    def test_key_metadata_projection_rejects_secret_reflection_and_free_text(self):
        result, _ = self.run_probe([key_response(Role=KEY, DeleteDate=KEY), response(), response()])
        self.assertIsNone(result["checks"][0]["key_role"])
        self.assertIsNone(result["checks"][0]["key_delete_date"])
        self.assertNotIn(KEY, json.dumps(result))

    def test_camel_case_and_valid_delete_date_are_preserved_without_expiry_claim(self):
        result, _ = self.run_probe([response([{"accessKey": KEY, "role": "Developer", "deleteDate": "2026-10-01T00:00:00Z"}]), response(), response()])
        self.assertEqual(result["checks"][0]["key_delete_date"], "2026-10-01T00:00:00Z")
        self.assertNotIn("expires", json.dumps(result))

    def test_provider_error_inside_http_200_is_not_success(self):
        result, _ = self.run_probe([response(code="1002"), response(code="1002"), response()])
        self.assertEqual(result["checks"][0]["error"], "API_RESPONSE_ERROR")
        self.assertEqual(result["checks"][0]["http_status"], 200)
        self.assertEqual(result["checks"][1]["error"], "API_RESPONSE_ERROR")
        self.assertFalse(result["access_checks_passed"])

    def test_orders_probe_does_not_follow_a_history_cursor(self):
        orders = Response(200, {"content-type": "application/json"},
                          b'{"Results":[],"Pagination":{"next_cursor":"next-page"}}')
        result, transport = self.run_probe([key_response(), response(), orders])
        self.assertTrue(result["checks"][2]["has_next_cursor"])
        self.assertEqual(len(transport.calls), 3)

    def test_untrusted_transport_error_never_echoes_the_key(self):
        class FailingTransport(FakeTransport):
            def get(self, url, headers):
                if not self.calls:
                    self.calls.append((url, headers))
                    raise DataError(KEY)
                return super().get(url, headers)
        transport = FailingTransport([response(), response()])
        result = diagnose_access(KEY, 123, transport=transport)
        self.assertEqual(result["checks"][0]["error"], "DIAGNOSTIC_REQUEST_FAILED")
        self.assertNotIn(KEY, json.dumps(result))

    def test_invalid_arguments_are_rejected_before_network(self):
        for key, strategy, plan in [("bad\nkey", 123, "0"), (KEY, 0, "0"), (KEY, 123, "999")]:
            transport = FakeTransport([])
            with self.assertRaises(DataError):
                diagnose_access(key, strategy, commission_plan=plan, transport=transport)
            self.assertEqual(transport.calls, [])

    def test_transport_allows_only_the_documented_key_probe_and_existing_reads(self):
        transport = HTTPSGetTransport()
        for url in ["https://api4-general.collective2.com/General/GetAccessKeyExtra",
                    "https://api4-general.collective2.com/Strategies/SendOrder",
                    "https://other.example/General/GetAccessKey"]:
            with self.assertRaisesRegex(DataError, "URL_NOT_ALLOWED"):
                transport.get(url, {})

    def test_key_probe_uses_an_actual_get_request_with_bounded_response(self):
        transport = HTTPSGetTransport()
        with patch.object(transport.opener, 'open') as open_request:
            http = open_request.return_value.__enter__.return_value
            http.status = 200
            http.headers = {"content-type": "application/json"}
            http.read.return_value = b'{"Results":[]}'
            transport.get('https://api4-general.collective2.com/General/GetAccessKey', {})
        request = open_request.call_args.args[0]
        self.assertEqual(request.get_method(), 'GET')
        self.assertEqual(request.full_url, 'https://api4-general.collective2.com/General/GetAccessKey')
        http.read.assert_called_once_with(32 * 1024 * 1024 + 1)

    def test_diagnose_cli_prompts_locally_and_outputs_only_safe_checks(self):
        transport = FakeTransport([key_response(), Response(403, {}, KEY.encode()), response()])
        with tempfile.TemporaryDirectory() as tmp, contextlib.chdir(tmp):
            with patch.dict(os.environ, {}, clear=True), patch('sys.stdin.isatty', return_value=True), \
                    patch('trading_intelligence.cli.getpass.getpass', return_value=KEY) as prompt, \
                    patch('trading_intelligence.diagnostics.HTTPSGetTransport', return_value=transport), \
                    patch('trading_intelligence.pipeline.DatasetStore', side_effect=AssertionError("must not save")):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = main(['diagnose', '--strategy-id', '123', '--acknowledge-authorized-access'])
            self.assertEqual(code, 2)
            prompt.assert_called_once()
            report = json.loads(out.getvalue())
            self.assertFalse(report['access_checks_passed'])
            self.assertNotIn(KEY, out.getvalue() + err.getvalue())
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_diagnose_cli_requires_acknowledgement_before_reading_key(self):
        out, err = io.StringIO(), io.StringIO()
        with patch('trading_intelligence.cli._read_api_key', side_effect=AssertionError('must not read key')), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(['diagnose', '--strategy-id', '123'])
        self.assertEqual(code, 2)
        self.assertIn('AUTHORIZED_ACCESS_ACK_REQUIRED', err.getvalue())

    def test_diagnose_cli_returns_zero_when_all_probes_pass(self):
        transport = FakeTransport([key_response(), response(), response()])
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {'C2_API_KEY': KEY}, clear=True), \
                patch('trading_intelligence.diagnostics.HTTPSGetTransport', return_value=transport), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(['diagnose', '--strategy-id', '123', '--acknowledge-authorized-access'])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out.getvalue())['access_checks_passed'])
        self.assertNotIn(KEY, out.getvalue() + err.getvalue())


if __name__ == '__main__':
    unittest.main()
