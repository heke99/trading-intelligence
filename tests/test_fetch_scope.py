"""Selected API4 imports, exercised only with synthetic offline transports."""
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
from trading_intelligence.collective2 import C2Client, Response
from trading_intelligence.common import DataError
from trading_intelligence.pipeline import fetch_history
from trading_intelligence.store import DatasetStore
from test_collective2 import FakeTransport, payload
from test_pipeline import order, trade


KEY = "synthetic-fetch-scope-key"


class FetchScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "data"

    def tearDown(self):
        self.tmp.cleanup()

    def client(self, responses):
        transport = FakeTransport(responses)
        return C2Client(KEY, transport=transport, sleep=lambda _: None), transport

    def manifest(self):
        return json.loads(next((self.out / "runs").glob("*/manifest.json")).read_text())

    def test_closed_scope_saves_raw_and_records_and_marks_orders_missing(self):
        page = payload([trade(), trade(TradeId=21,
            C2Symbol={"FullSymbol": "SYNTHETIC_STOCK", "SymbolType": "stock"})])
        client, transport = self.client([page])
        result = fetch_history(client, self.out, strategy_id=123, kind="closed_trades")
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(urlsplit(transport.calls[0][0]).path,
                         "/Strategies/GetStrategyHistoricalClosedTrades")
        self.assertEqual(result["requested_kinds"], ["closed_trades"])
        self.assertEqual(result["endpoint_traversal"],
                         {"closed_trades": "complete", "orders": "not_requested"})
        self.assertIn("ORDERS_NOT_REQUESTED", result["blockers"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["inserted_versions"], 2)
        self.assertFalse(result["training_ready"])
        self.assertFalse(result["full_history_verified"])
        self.assertEqual(next((self.out / "raw").glob("*.json")).read_bytes(), page.body)
        with DatasetStore(self.out) as store:
            self.assertEqual(store.count_completed_run_records(), 2)

    def test_orders_scope_traverses_cursor_and_keeps_cancelled_orders(self):
        client, transport = self.client([payload([order()], "next%2Bpage"),
            payload([order(Id=12, SignalId=12, OrderStatus="4",
                           FilledQuantity="0", AvgFillPrice=None)])])
        result = fetch_history(client, self.out, strategy_id=123, kind="orders")
        self.assertEqual(len(transport.calls), 2)
        for url, _ in transport.calls:
            self.assertEqual(urlsplit(url).path, "/Strategies/GetStrategyHistoricalOrders")
            self.assertNotIn("OrderStatus", parse_qs(urlsplit(url).query))
        self.assertEqual(parse_qs(urlsplit(transport.calls[1][0]).query)["Cursor"], ["next+page"])
        self.assertEqual(result["endpoint_traversal"],
                         {"closed_trades": "not_requested", "orders": "complete"})
        self.assertIn("CLOSED_TRADES_NOT_REQUESTED", result["blockers"])
        self.assertEqual(result["inserted_versions"], 2)
        self.assertFalse(result["training_ready"])
        self.assertFalse(result["full_history_verified"])

    def test_default_orders_denial_still_fails_and_retains_closed_evidence(self):
        client, transport = self.client([payload([trade()]), Response(403, {}, b"private")])
        with self.assertRaisesRegex(DataError, "HTTP_403"):
            fetch_history(client, self.out, strategy_id=123)
        self.assertEqual(len(transport.calls), 2)
        result = self.manifest()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["endpoint_traversal"],
                         {"closed_trades": "complete", "orders": "incomplete"})
        self.assertEqual(len(list((self.out / "raw").glob("*.json"))), 1)
        with DatasetStore(self.out) as store:
            self.assertEqual(store.count_completed_run_records(), 0)

    def test_closed_scope_after_failed_fetch_reuses_business_versions(self):
        page = payload([trade()])
        client, _ = self.client([page, Response(403, {}, b"")])
        with self.assertRaises(DataError):
            fetch_history(client, self.out, strategy_id=123)
        client, _ = self.client([page])
        result = fetch_history(client, self.out, strategy_id=123, kind="closed_trades")
        self.assertEqual(result["inserted_versions"], 0)
        self.assertEqual(result["duplicate_observations"], 1)
        self.assertEqual(len(list((self.out / "raw").glob("*.json"))), 1)
        with DatasetStore(self.out) as store:
            self.assertEqual(store.count_versions(), 1)
            self.assertEqual(store.count_completed_run_records(), 1)

    def test_invalid_scope_fails_before_request_or_store_creation(self):
        for kind in ("", "closed_trade", "send_order", None):
            with self.subTest(kind=kind):
                client, transport = self.client([])
                with self.assertRaisesRegex(DataError, "FETCH_KIND_INVALID"):
                    fetch_history(client, self.out, strategy_id=123, kind=kind)
                self.assertEqual(transport.calls, [])
                self.assertFalse(self.out.exists())

    def test_selected_endpoint_denial_still_fails_without_fallback(self):
        client, transport = self.client([Response(403, {}, b"private")])
        with self.assertRaisesRegex(DataError, "HTTP_403"):
            fetch_history(client, self.out, strategy_id=123, kind="closed_trades")
        self.assertEqual(len(transport.calls), 1)
        result = self.manifest()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["endpoint_traversal"],
                         {"closed_trades": "incomplete", "orders": "not_requested"})
        self.assertEqual(list((self.out / "raw").iterdir()), [])

    def test_selected_scope_preserves_reflected_secret_rejection(self):
        client, _ = self.client([payload([trade(Info=KEY)])])
        with self.assertRaisesRegex(DataError, "SECRET_IN_RESPONSE"):
            fetch_history(client, self.out, strategy_id=123, kind="closed_trades")
        self.assertEqual(self.manifest()["status"], "failed")
        self.assertEqual(list((self.out / "raw").iterdir()), [])

    def test_selected_scope_quarantines_bad_rows_and_preserves_raw_evidence(self):
        page = payload([trade(), trade(TradeId=21, OpenSide="bad")])
        client, _ = self.client([page])
        result = fetch_history(client, self.out, strategy_id=123, kind="closed_trades")
        self.assertEqual(result["status"], "completed_with_quarantine")
        self.assertEqual(result["source_rows"], 2)
        self.assertEqual(result["quarantined_rows"], 1)
        self.assertEqual(result["inserted_versions"], 1)
        self.assertFalse(result["training_ready"])
        self.assertFalse(result["full_history_verified"])
        self.assertEqual(next((self.out / "raw").glob("*.json")).read_bytes(), page.body)

    def test_cli_selected_scope_uses_hidden_prompt_and_status_retains_scope(self):
        transport = FakeTransport([payload([trade()])])
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, {}, clear=True), patch("sys.stdin.isatty", return_value=True), \
                patch("trading_intelligence.cli.getpass.getpass", return_value=KEY) as prompt, \
                patch("trading_intelligence.collective2.HTTPSGetTransport", return_value=transport), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["fetch", "--strategy-id", "123", "--kind", "closed_trades",
                         "--out", str(self.out), "--acknowledge-authorized-access"])
        self.assertEqual(code, 0)
        prompt.assert_called_once()
        result = json.loads(out.getvalue())
        self.assertEqual(result["requested_kinds"], ["closed_trades"])
        self.assertEqual(result["endpoint_traversal"]["orders"], "not_requested")
        self.assertFalse(result["training_ready"])
        self.assertNotIn(KEY, out.getvalue() + err.getvalue())
        self.assertNotIn("EUR/USD", out.getvalue() + err.getvalue())
        status_out = io.StringIO()
        with contextlib.redirect_stdout(status_out):
            self.assertEqual(main(["status", "--out", str(self.out)]), 0)
        self.assertEqual(json.loads(status_out.getvalue())["requested_kinds"], ["closed_trades"])


if __name__ == "__main__":
    unittest.main()
