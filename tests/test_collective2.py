"""Synthetic, offline contract tests. No real provider/account data."""
import json
import unittest
from urllib.parse import parse_qs, urlsplit

from trading_intelligence.collective2 import C2Client, Response
from trading_intelligence.common import DataError


def payload(rows=None, cursor=None, status="200", camel=False):
    p = {"Results": rows if rows is not None else [],
         "ResponseStatus": {"ErrorCode": status},
         "Pagination": {"next_cursor": cursor}}
    if camel:
        p = {k[0].lower() + k[1:]: v for k, v in p.items()}
    return Response(200, {"content-type": "application/json"}, json.dumps(p).encode())


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, headers):
        self.calls.append((url, headers.copy()))
        return self.responses.pop(0)


class ClientTests(unittest.TestCase):
    def client(self, responses, **kwargs):
        transport = FakeTransport(responses)
        self.sleeps = []
        return C2Client("not-a-real-api-key", transport=transport,
                        sleep=self.sleeps.append, **kwargs), transport

    def test_closed_trades_request_is_read_only_and_explicit(self):
        c, t = self.client([payload([{"Id": 1}])])
        pages = list(c.pages("closed_trades", 123))
        self.assertEqual(len(pages), 1)
        url, headers = t.calls[0]
        self.assertEqual(urlsplit(url).netloc, "api4-general.collective2.com")
        self.assertEqual(urlsplit(url).path, "/Strategies/GetStrategyHistoricalClosedTrades")
        self.assertEqual(parse_qs(urlsplit(url).query), {"StrategyId": ["123"], "CommissionPlan": ["0"]})
        self.assertEqual(headers["Authorization"], "Bearer not-a-real-api-key")
        self.assertEqual(headers["Accept"], "application/json")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertNotIn("not-a-real", url)

    def test_orders_follows_cursor_even_on_short_page(self):
        c, t = self.client([payload([{"Id": 1}], "a%2Bb%2Fc%3D"), payload([{"Id": 2}])])
        self.assertEqual(len(list(c.pages("orders", 123))), 2)
        q = parse_qs(urlsplit(t.calls[1][0]).query)
        self.assertEqual(q["Cursor"], ["a+b/c="])
        self.assertEqual(q["AscendingOrder"], ["true"])
        self.assertNotIn("OrderStatus", q)  # canceled and expired must not be silently excluded

    def test_camel_case_envelope_supported(self):
        c, _ = self.client([payload(camel=True)])
        self.assertEqual(len(list(c.pages("closed_trades", 123))), 1)

    def test_empty_null_or_absent_pagination_is_terminal(self):
        for p in [{}, {"Pagination": None}, {"Pagination": {}}, {"Pagination": {"next_cursor": ""}}]:
            body = {"Results": [], "ResponseStatus": {"ErrorCode": "200"}, **p}
            c, _ = self.client([Response(200, {"content-type": "application/json"}, json.dumps(body).encode())])
            self.assertEqual(len(list(c.pages("orders", 123))), 1)

    def test_cursor_loop_is_not_success(self):
        c, _ = self.client([payload([{"Id": 1}], "same"), payload([{"Id": 2}], "same")])
        with self.assertRaisesRegex(DataError, "CURSOR_LOOP"):
            list(c.pages("orders", 123))

    def test_page_limit_is_not_success(self):
        c, _ = self.client([payload([], "more")], max_pages=1)
        with self.assertRaisesRegex(DataError, "PAGE_LIMIT"):
            list(c.pages("orders", 123))

    def test_closed_trades_cannot_silently_ignore_cursor(self):
        c, _ = self.client([payload([], "more")])
        with self.assertRaisesRegex(DataError, "UNEXPECTED_PAGINATION"):
            list(c.pages("closed_trades", 123))

    def test_api_permission_error_in_http_200(self):
        c, _ = self.client([payload(status="1002")])
        with self.assertRaisesRegex(DataError, "API_RESPONSE_ERROR"):
            list(c.pages("orders", 123))

    def test_http_authentication_and_access_fail_without_retry(self):
        for status in (401, 403):
            c, t = self.client([Response(status, {}, b'potential private error body')])
            with self.assertRaises(DataError) as ctx:
                list(c.pages("orders", 123))
            self.assertNotIn("private", str(ctx.exception))
            self.assertEqual(len(t.calls), 1)

    def test_redirect_never_followed_by_client(self):
        c, t = self.client([Response(302, {"location": "https://example.org"}, b'')])
        with self.assertRaisesRegex(DataError, "HTTP_302"):
            list(c.pages("orders", 123))
        self.assertEqual(len(t.calls), 1)

    def test_retry_429_then_success(self):
        c, _ = self.client([Response(429, {"retry-after": "1"}, b''), payload()])
        list(c.pages("orders", 123))
        self.assertEqual(self.sleeps, [1.0])

    def test_long_retry_after_fails_instead_of_retrying_early(self):
        c, t = self.client([Response(429, {"retry-after": "3600"}, b'')])
        with self.assertRaisesRegex(DataError, "RETRY_LATER"):
            list(c.pages("orders", 123))
        self.assertEqual(len(t.calls), 1)

    def test_bounded_retries(self):
        c, t = self.client([Response(503, {}, b'')] * 3)
        with self.assertRaisesRegex(DataError, "HTTP_503"):
            list(c.pages("orders", 123))
        self.assertEqual(len(t.calls), 3)

    def test_secret_cannot_be_archived_if_server_reflects_it(self):
        c, _ = self.client([payload([{"Info": "not-a-real-api-key"}])])
        with self.assertRaisesRegex(DataError, "SECRET_IN_RESPONSE"):
            list(c.pages("orders", 123))

    def test_json_escaped_reflected_key_is_rejected_before_page_is_returned(self):
        # A JSON string may encode the same secret without containing its literal bytes.
        body = b'{"Results":[{"Info":"not-a-real-api-\\u006bey"}]}'
        self.assertNotIn(b'not-a-real-api-key', body)
        c, _ = self.client([Response(200, {"content-type": "application/json"}, body)])
        with self.assertRaisesRegex(DataError, "SECRET_IN_RESPONSE"):
            list(c.pages("orders", 123))

    def test_missing_results_is_schema_error(self):
        c, _ = self.client([Response(200, {"content-type": "application/json"}, b'{}')])
        with self.assertRaisesRegex(DataError, "RESULTS_SCHEMA"):
            list(c.pages("orders", 123))

    def test_invalid_json_duplicate_keys_and_nonfinite_numbers_fail(self):
        for body in (b'<html>Login</html>', b'{"Results":[],"Results":[]}', b'{"Results":[{"x":NaN}]}'):
            c, _ = self.client([Response(200, {"content-type": "application/json"}, body)])
            with self.assertRaises(DataError):
                list(c.pages("orders", 123))

    def test_result_key_case_collision_fails(self):
        c, _ = self.client([Response(200, {"content-type": "application/json"}, b'{"Results":[],"results":[]}')])
        with self.assertRaisesRegex(DataError, "AMBIGUOUS_FIELD"):
            list(c.pages("orders", 123))

    def test_unknown_endpoint_strategy_or_commission_rejected_before_network(self):
        for kind, strategy, plan in [("send_order",123,"0"), ("orders",0,"0"), ("orders",True,"0"), ("closed_trades",123,"999")]:
            c, t = self.client([])
            with self.assertRaises(DataError):
                list(c.pages(kind, strategy, commission_plan=plan))
            self.assertEqual(t.calls, [])

    def test_bad_key_fails_without_logging_key(self):
        with self.assertRaisesRegex(DataError, "API_KEY_INVALID"):
            C2Client("bad\nheader")


if __name__ == "__main__":
    unittest.main()
