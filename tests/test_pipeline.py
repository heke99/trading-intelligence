import json
import tempfile
import unittest
from pathlib import Path

from trading_intelligence.common import DataError
from trading_intelligence.normalize import normalize_record
from trading_intelligence.pipeline import import_json, import_csv, inspect_csv, fetch_history
from trading_intelligence.store import DatasetStore
from trading_intelligence.collective2 import C2Client, Response
from test_collective2 import FakeTransport, payload


def trade(**updates):
    row = {"Id": 10, "TradeId": 20, "StrategyId": 123,
           "OpenDate": "2024-01-02T09:00:00Z", "CloseDate": "2024-01-02T10:00:00Z",
           "AvgOpenFillPrice": "1.10000", "AvgCloseFillPrice": "1.10100",
           "OpenedQuantity": "1000", "ClosedQuantity": "1000", "OpenSide": "1", "CloseSide": "2",
           "ProfitLoss": "1.00", "Commission": "0.10",
           "C2Symbol": {"FullSymbol": "EUR/USD", "SymbolType": "forex"},
           "ExchangeSymbol": {"Currency": "USD"}}
    row.update(updates)
    return row


def order(**updates):
    row = {"Id": 11, "SignalId": 11, "StrategyId": 123, "Side": "1", "OpenClose": "O",
           "OrderStatus": "2", "PostedDate": "2024-01-02T08:59:58", "OrderQuantity": "1000",
           "FilledQuantity": "1000", "AvgFillPrice": "1.1000",
           "C2Symbol": {"FullSymbol": "EUR/USD", "SymbolType": "forex"}}
    row.update(updates)
    return row


class NormalizeTests(unittest.TestCase):
    def test_decimal_strings_and_hypothetical_provenance(self):
        row = normalize_record(trade(), "closed_trades", 123)
        self.assertEqual(row["entry_price"], "1.10000")
        self.assertEqual(row["data_origin"], "c2_strategy_hypothetical")
        self.assertIsNone(row["net_pnl"])
        self.assertIsNone(row["pnl_currency"])
        self.assertEqual(row["instrument_currency"], "USD")
        self.assertEqual(row["usage_role"], "outcome_only_not_features")

    def test_naive_closed_times_not_silently_utc(self):
        row = normalize_record(trade(OpenDate="2024-01-02T09:00:00"), "closed_trades", 123)
        self.assertIsNone(row["opened_at_utc"])
        self.assertIn("TIMEZONE_UNVERIFIED", row["quality_flags"])
        self.assertEqual(row["opened_at_raw"], "2024-01-02T09:00:00")

    def test_timezone_requires_evidence(self):
        with self.assertRaisesRegex(DataError, "TIMEZONE_EVIDENCE_REQUIRED"):
            normalize_record(trade(OpenDate="2024-01-02T09:00:00"), "closed_trades", 123, naive_timezone="UTC")

    def test_verified_timezone_converts(self):
        row = normalize_record(trade(OpenDate="2024-01-02T09:00:00"), "closed_trades", 123,
                               naive_timezone="Europe/Stockholm", timezone_evidence="test-only reference")
        self.assertEqual(row["opened_at_utc"], "2024-01-02T08:00:00+00:00")

    def test_ambiguous_and_nonexistent_dst_times_quarantined(self):
        for t in ["2024-10-27T02:30:00", "2024-03-31T02:30:00"]:
            with self.assertRaisesRegex(DataError, "LOCAL_TIME_AMBIGUOUS_OR_NONEXISTENT"):
                normalize_record(trade(OpenDate=t), "closed_trades", 123,
                                 naive_timezone="Europe/Stockholm", timezone_evidence="test")

    def test_wrong_strategy_rejected(self):
        with self.assertRaisesRegex(DataError, "STRATEGY_MISMATCH"):
            normalize_record(trade(), "closed_trades", 456)

    def test_closing_before_opening_rejected(self):
        with self.assertRaisesRegex(DataError, "CLOSE_BEFORE_OPEN"):
            normalize_record(trade(CloseDate="2024-01-01T00:00:00Z"), "closed_trades", 123)

    def test_missing_side_price_and_nonfinite_quantity_fail(self):
        for change in [{"OpenSide": "LONG"}, {"AvgOpenFillPrice": None}, {"OpenedQuantity": "NaN"}, {"OpenedQuantity": 0}]:
            with self.assertRaises(DataError):
                normalize_record(trade(**change), "closed_trades", 123)

    def test_nonfinite_optional_pnl_fails(self):
        with self.assertRaises(DataError):
            normalize_record(trade(ProfitLoss="Infinity"), "closed_trades", 123)

    def test_partial_quantity_not_falsely_complete(self):
        row = normalize_record(trade(ClosedQuantity="500"), "closed_trades", 123)
        self.assertIn("OPEN_CLOSE_QUANTITY_MISMATCH", row["quality_flags"])

    def test_no_price_positivity_rule_for_all_futures(self):
        row = normalize_record(trade(AvgOpenFillPrice="-20", AvgCloseFillPrice="-10"), "closed_trades", 123)
        self.assertEqual(row["entry_price"], "-20")

    def test_order_posted_time_not_filled_time_or_known_feature(self):
        row = normalize_record(order(), "orders", 123)
        self.assertEqual(row["posted_at_utc"], "2024-01-02T08:59:58+00:00")
        self.assertIsNone(row["filled_at_utc"])
        self.assertEqual(row["usage_role"], "historical_snapshot_not_point_in_time_features")

    def test_cancelled_order_without_fill_is_preserved(self):
        row = normalize_record(order(OrderStatus="4", FilledQuantity="0", AvgFillPrice=None), "orders", 123)
        self.assertEqual(row["order_status"], "4")
        self.assertIsNone(row["fill_price"])

    def test_camel_row_supported(self):
        raw = {k[0].lower()+k[1:]: v for k,v in trade().items()}
        self.assertEqual(normalize_record(raw, "closed_trades", 123)["source_id"], "20")

    def test_synthetic_origin_is_explicit(self):
        self.assertEqual(normalize_record(trade(), "closed_trades", 123, synthetic=True)["data_origin"], "synthetic_fixture")


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.out = self.root / "data"
        self.source = self.root / "input.json"

    def tearDown(self):
        self.tmp.cleanup()

    def write_json(self, rows):
        self.source.write_text(json.dumps({"Results": rows, "ResponseStatus": {"ErrorCode": "200"}}))

    def run_import(self):
        return import_json(self.source, self.out, kind="closed_trades", strategy_id=123)

    def test_idempotent_import_and_always_blocked_for_training(self):
        self.write_json([trade(), trade()])
        first = self.run_import()
        second = self.run_import()
        self.assertEqual(first["inserted_versions"], 1)
        self.assertEqual(first["duplicate_observations"], 1)
        self.assertEqual(second["inserted_versions"], 0)
        self.assertFalse(first["training_ready"])
        self.assertFalse(first["full_history_verified"])
        with DatasetStore(self.out) as s:
            self.assertEqual(s.count_versions(), 1)

    def test_changed_record_is_versioned_not_overwritten(self):
        self.write_json([trade()]); self.run_import()
        self.write_json([trade(ProfitLoss="2.00")]); result = self.run_import()
        self.assertEqual(result["revision_observations"], 1)
        with DatasetStore(self.out) as s:
            self.assertEqual(s.count_versions(), 2)

    def test_malformed_rows_quarantined_and_raw_preserved(self):
        self.write_json([trade(), trade(TradeId=21, OpenSide="bad")])
        result = self.run_import()
        self.assertEqual(result["quarantined_rows"], 1)
        self.assertEqual(result["status"], "completed_with_quarantine")
        raw_files = list((self.out / "raw").glob("*.json"))
        self.assertEqual(len(raw_files), 1)
        self.assertEqual(raw_files[0].read_bytes(), self.source.read_bytes())

    def test_invalid_envelope_marks_run_failed(self):
        self.source.write_text('{"error":"not allowed"}')
        with self.assertRaises(DataError):
            self.run_import()
        manifests = list((self.out / "runs").glob("*/manifest.json"))
        self.assertEqual(json.loads(manifests[0].read_text())["status"], "failed")

    def test_partial_api_fetch_remains_failed_with_successful_raw_pages(self):
        responses = [payload([trade()]), payload([order()], "next"), Response(403, {}, b'private error')]
        c = C2Client("test-only", transport=FakeTransport(responses), sleep=lambda _: None)
        with self.assertRaises(DataError):
            fetch_history(c, self.out, strategy_id=123)
        m = json.loads(next((self.out / "runs").glob("*/manifest.json")).read_text())
        self.assertEqual(m["status"], "failed")
        self.assertEqual(m["endpoint_traversal"]["closed_trades"], "complete")
        self.assertEqual(m["endpoint_traversal"]["orders"], "incomplete")
        self.assertFalse(m["training_ready"])
        self.assertEqual(len(list((self.out / "raw").glob("*.json"))), 2)
        with DatasetStore(self.out) as s:
            self.assertEqual(s.count_completed_run_records(), 0)

    def test_local_order_page_with_next_cursor_is_incomplete(self):
        self.source.write_bytes(payload([order()], "more").body)
        result = import_json(self.source, self.out, kind="orders", strategy_id=123)
        self.assertEqual(result["endpoint_traversal"]["orders"], "incomplete")
        self.assertFalse(result["full_history_verified"])

    def test_output_raw_hash_checked_on_reuse(self):
        self.write_json([trade()]); self.run_import()
        raw = next((self.out / "raw").glob("*.json")); raw.write_text('corrupted')
        with self.assertRaisesRegex(DataError, "RAW_HASH_MISMATCH"):
            self.run_import()

    def test_raw_account_export_never_interpreted_as_python(self):
        self.write_json([trade(Info="__import__('os').system('exit 1')")])
        self.assertEqual(self.run_import()["inserted_versions"], 1)

    def test_csv_explicit_mapping(self):
        f=self.root/'sample.csv'
        f.write_text('id,symbol,type,opened,closed,side,entry,exit,qty\n'
                     '20,EUR/USD,forex,2024-01-02T09:00:00Z,2024-01-02T10:00:00Z,LONG,1.1,1.2,100\n')
        fields={"TradeId":"id", "C2Symbol.FullSymbol":"symbol", "C2Symbol.SymbolType":"type",
                "OpenDate":"opened", "CloseDate":"closed", "OpenSide":"side",
                "AvgOpenFillPrice":"entry", "AvgCloseFillPrice":"exit", "OpenedQuantity":"qty", "ClosedQuantity":"qty"}
        mapping={"version":1,"kind":"closed_trades","delimiter":",", "fields":fields,"side_values":{"LONG":"1"}}
        m=self.root/'mapping.json';m.write_text(json.dumps(mapping))
        report=import_csv(f,m,self.out,strategy_id=123)
        self.assertEqual(report["inserted_versions"],1)
        self.assertFalse(report["full_history_verified"])
        self.assertEqual(inspect_csv(f)["columns"][0], "id")

    def test_unrecognized_csv_does_not_guess(self):
        f=self.root/'sample.csv';f.write_text('Profit,Date\n100,02/03/24\n')
        m=self.root/'mapping.json';m.write_text(json.dumps({"version":1,"kind":"closed_trades","fields":{"TradeId":"missing"}}))
        with self.assertRaises(DataError):
            import_csv(f,m,self.out,strategy_id=123)

    def test_duplicate_csv_headers_rejected(self):
        f=self.root/'sample.csv';f.write_text('a,a\n1,2\n')
        with self.assertRaisesRegex(DataError,"CSV_DUPLICATE_HEADER"):
            inspect_csv(f)

    def test_synthetic_and_provider_records_do_not_deduplicate_together(self):
        self.write_json([trade()])
        import_json(self.source,self.out,kind="closed_trades",strategy_id=123,synthetic=True)
        self.run_import()
        with DatasetStore(self.out) as s:
            self.assertEqual(s.count_versions(),2)

class AdditionalAcceptanceTests(unittest.TestCase):
    setUp = PipelineTests.setUp
    tearDown = PipelineTests.tearDown
    write_json = PipelineTests.write_json
    run_import = PipelineTests.run_import
    def test_full_api_traversal_is_not_full_history_verification(self):
        transport=FakeTransport([payload([trade()]),payload([order()])])
        c=C2Client('test-only-secret',transport=transport,sleep=lambda _:None)
        report=fetch_history(c,self.out,strategy_id=123)
        self.assertEqual(report['status'],'completed')
        self.assertEqual(set(report['endpoint_traversal'].values()),{'complete'})
        self.assertFalse(report['full_history_verified'])
        self.assertFalse(report['training_ready'])
        self.assertEqual(report['source_rows'],2)
        with DatasetStore(self.out) as s:
            self.assertEqual(s.count_completed_run_records(),2)

    def test_observed_ranges_not_claimed_as_coverage(self):
        self.write_json([trade()]);report=self.run_import()
        self.assertEqual(report['observed_timestamp_ranges']['closed_trades:opened_at_utc']['min'],'2024-01-02T09:00:00+00:00')
        self.assertFalse(report['full_history_verified'])

    def test_empty_api_results_are_not_evidence_of_no_trading(self):
        c=C2Client('test-only-secret',transport=FakeTransport([payload(),payload()]))
        report=fetch_history(c,self.out,strategy_id=123)
        self.assertEqual(report['source_rows'],0)
        self.assertFalse(report['training_ready'])
        self.assertFalse(report['full_history_verified'])


if __name__ == "__main__":
    unittest.main()
