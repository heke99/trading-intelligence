"""Synthetic vendor-shaped responses and fake HTTP only; no broker credentials."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request

from trading_intelligence.alpaca_reader import (
    AlpacaReferenceReader, BrokerRead, BrokerReadError, MAX_RESPONSE_BYTES, PAPER_HOST, _NoRedirect,
)
from trading_intelligence.alpaca_normalizer import NormalizationError, decode, normalize_bundle
from trading_intelligence.broker_imports import BrokerImportStore
from trading_intelligence.brokers import BrokerAccount, Environment
from trading_intelligence.contracts import (
    ContractError, DataOrigin, EvidenceIntegrityError, RecordConflict, Use, UseNotAllowed,
)


START = datetime(2026, 1, 1, tzinfo=timezone.utc)
RECEIVED = START + timedelta(hours=1)
AVAILABLE = RECEIVED + timedelta(minutes=1)
LATER = AVAILABLE + timedelta(minutes=1)
ACCOUNT_UUID = "00000000-0000-4000-8000-000000000001"
ASSET_UUID = "00000000-0000-4000-8000-000000000002"
OTHER_UUID = "00000000-0000-4000-8000-000000000003"
ROUTE = BrokerAccount("alpaca", "fixture-connection", "FIXTURE-ACCOUNT", Environment.PAPER)


def account_record(**changes):
    return dict(id=ACCOUNT_UUID, account_number="FIXTURE-ACCOUNT", status="ACTIVE", currency="USD",
                cash="1234.56", buying_power="2000.00", equity="1234.56", trading_blocked=False,
                account_blocked=False, trade_suspended_by_user=False, shorting_enabled=False) | changes


def asset_record(**changes):
    return dict(id=ASSET_UUID, symbol="INVENTED", exchange="NASDAQ", status="active",
                tradable=True, fractionable=False, marginable=False, shortable=False,
                easy_to_borrow=False, **{"class": "us_equity"}) | changes


def raw(value):
    return json.dumps(value).encode()


def reads(account=None, assets=None, *, received=RECEIVED):
    return (BrokerRead("account", raw(account_record() if account is None else account), received, None),
            BrokerRead("assets", raw([asset_record()] if assets is None else assets), received, None))


class NormalizerTests(unittest.TestCase):
    def report(self, account=None, assets=None):
        a, b = reads(account, assets)
        return normalize_bundle(a.payload, b.payload, ROUTE, ACCOUNT_UUID)

    def test_documented_wire_fields_are_normalized_without_trading_admission(self):
        result = self.report()
        self.assertEqual(result["account"]["reported_cash"], "1234.56")
        asset = result["assets"][0]
        self.assertEqual(asset["provider_asset_class"], "us_equity")
        self.assertIsNone(asset["canonical_target"])
        self.assertIsNone(asset["price_increment"])
        self.assertFalse(result["training_ready"])
        self.assertFalse(result["trading_authorized"])

    def test_missing_flags_and_money_stay_unknown(self):
        account = account_record()
        for key in ("trading_blocked", "cash", "buying_power"):
            del account[key]
        result = self.report(account)
        self.assertIsNone(result["account"]["reported_cash"])
        self.assertIsNone(result["account"]["flags"]["trading_blocked"])
        self.assertIn("trading_blocked_unknown", result["account"]["review_reasons"])
        self.assertEqual(result["state"], "review_required")

    def test_wrong_account_number_or_native_id_quarantines_entire_bundle(self):
        for change in (dict(account_number="OTHER"), dict(id=OTHER_UUID), dict(id="bad-uuid")):
            with self.subTest(change=change):
                result = self.report(account_record(**change))
                self.assertEqual(result["state"], "quarantined")
                self.assertEqual(result["assets"], [])

    def test_account_block_and_inactive_status_need_review(self):
        for change in (dict(status="CLOSED"), dict(trading_blocked=True), dict(account_blocked=True),
                       dict(trade_suspended_by_user=True)):
            with self.subTest(change=change):
                self.assertEqual(self.report(account_record(**change))["state"], "review_required")

    def test_boolean_strings_are_not_treated_as_true_or_false(self):
        self.assertEqual(self.report(account_record(trading_blocked="false"))["state"], "quarantined")
        result = self.report(assets=[asset_record(tradable="true")])
        self.assertEqual(result["assets"], [])
        self.assertEqual(result["quarantined"][0]["reason"], "invalid_boolean")

    def test_bad_money_currency_and_nonfinite_values_are_rejected(self):
        for change in (dict(cash=100), dict(cash="NaN"), dict(cash="Infinity"), dict(currency="usd"), dict(equity="1e100")):
            with self.subTest(change=change):
                self.assertEqual(self.report(account_record(**change))["state"], "quarantined")

    def test_negative_cash_is_preserved_as_reported_not_a_zero_balance(self):
        self.assertEqual(self.report(account_record(cash="-12.50"))["account"]["reported_cash"], "-12.50")

    def test_duplicate_keys_invalid_utf8_and_nonfinite_json_are_rejected(self):
        for payload in (b'{"id":1,"id":2}', b'\xff', b'{"cash":NaN}', b'{'):
            with self.subTest(payload=payload), self.assertRaises(NormalizationError):
                decode(payload)

    def test_crypto_or_unknown_class_is_quarantined_without_substitution(self):
        result = self.report(assets=[asset_record(**{"class": "crypto"}), asset_record(id=OTHER_UUID, symbol="OTHER")])
        self.assertEqual(len(result["assets"]), 1)
        self.assertEqual(result["quarantined"][0]["reason"], "unsupported_asset_class")

    def test_sdk_alias_and_conflicting_class(self):
        item = asset_record()
        del item["class"]
        item["asset_class"] = "us_equity"
        self.assertEqual(len(self.report(assets=[item])["assets"]), 1)
        result = self.report(assets=[asset_record(asset_class="crypto")])
        self.assertEqual(result["quarantined"][0]["reason"], "conflicting_asset_class")

    def test_duplicate_ids_or_symbols_quarantine_every_ambiguous_member(self):
        for second in (asset_record(symbol="DIFFERENT"), asset_record(id=OTHER_UUID)):
            with self.subTest(second=second):
                result = self.report(assets=[asset_record(), second])
                self.assertEqual(result["assets"], [])
                self.assertEqual(len(result["quarantined"]), 2)

    def test_inactive_or_untradable_asset_is_kept_as_restricted_reference(self):
        self.assertEqual(self.report(assets=[asset_record(tradable=False)])["assets"][0]["state"], "restricted_reference")

    def test_nonpositive_or_invalid_increments_are_quarantined(self):
        for change in (dict(price_increment=0), dict(min_trade_increment="NaN"), dict(min_order_size=-1)):
            with self.subTest(change=change):
                self.assertEqual(self.report(assets=[asset_record(**change)])["assets"], [])

    def test_empty_asset_catalogue_is_preserved_as_empty(self):
        self.assertEqual(self.report(assets=[])["assets"], [])

    def test_wrong_top_level_shapes_are_quarantined(self):
        self.assertEqual(self.report(account=[])["state"], "quarantined")
        self.assertEqual(self.report(assets={})["state"], "quarantined")


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.store = BrokerImportStore(":memory:", clock=lambda: AVAILABLE)
        self.addCleanup(self.store.close)
        self.store.register_source("fixture-source", DataOrigin.SYNTHETIC)
        self.store.set_permissions("fixture-source", known_at=START, uses={Use.STORAGE, Use.RESEARCH})
        self.store.register_account(ROUTE)

    def ingest(self, **changes):
        a, b = reads()
        args = dict(import_id="batch-1", source_id="fixture-source", expected_native_id=ACCOUNT_UUID, account=a, assets=b)
        return self.store.import_alpaca(ROUTE, **(args | changes))

    def test_receipt_does_not_backdate_normalized_availability(self):
        result = self.ingest()
        self.assertIsNone(self.store.reference_import_as_of(ROUTE, "batch-1", as_of=RECEIVED))
        self.assertEqual(self.store.reference_import_as_of(ROUTE, "batch-1", as_of=AVAILABLE), result)
        self.assertEqual(result["receipts"][0]["received_at"], "2026-01-01T01:00:00.000000Z")
        self.assertIsNone(result["receipts"][0]["provider_published_at"])

    def test_retry_is_idempotent_and_writes_no_bindings_or_capabilities(self):
        first = self.ingest()
        self.assertEqual(first, self.ingest())
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM broker_reference_imports").fetchone()[0], 1)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM broker_snapshots").fetchone()[0], 0)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM evidence_versions").fetchone()[0], 0)

    def test_same_batch_cannot_change_bytes_receipt_source_or_expected_account(self):
        self.ingest()
        changed_account = reads(account_record(cash="2"))[0]
        for change in (dict(account=changed_account), dict(account=replace(reads()[0], received_at=LATER)),
                       dict(expected_native_id=OTHER_UUID), dict(source_id="other")):
            with self.subTest(change=change), self.assertRaises(RecordConflict):
                self.ingest(**change)

    def test_raw_invalid_response_is_archived_with_quarantine(self):
        invalid = replace(reads()[1], payload=b'not-json')
        result = self.ingest(assets=invalid)
        self.assertEqual(result["report"]["state"], "quarantined")
        rows = self.store.db.execute("SELECT payload FROM raw_objects").fetchall()
        self.assertIn(b'not-json', [row["payload"] for row in rows])

    def test_processing_completion_before_receipt_is_rejected(self):
        with self.assertRaises(ContractError):
            self.ingest(account=replace(reads()[0], received_at=LATER))
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM raw_objects").fetchone()[0], 0)

    def test_storage_and_research_permissions_are_separate_requirements(self):
        self.store.register_source("storage-only", DataOrigin.PROVIDER)
        self.store.set_permissions("storage-only", known_at=START, uses={Use.STORAGE})
        with self.assertRaises(UseNotAllowed):
            self.ingest(source_id="storage-only")
        self.store.register_source("research-only", DataOrigin.PROVIDER)
        self.store.set_permissions("research-only", known_at=START, uses={Use.RESEARCH})
        with self.assertRaises(UseNotAllowed):
            self.ingest(source_id="research-only")

    def test_revoked_research_blocks_reading_an_existing_import(self):
        self.ingest()
        self.store.set_permissions("fixture-source", known_at=LATER, uses=set())
        with self.assertRaises(UseNotAllowed):
            self.store.reference_import_as_of(ROUTE, "batch-1", as_of=LATER)

    def test_live_and_wrong_response_environments_are_rejected(self):
        with self.assertRaises(ContractError):
            self.ingest(account=replace(reads()[0], environment=Environment.LIVE))
        live = replace(ROUTE, environment=Environment.LIVE)
        self.store.register_account(live)
        with self.assertRaises(ContractError):
            self.store.import_alpaca(live, import_id="test", source_id="fixture-source", expected_native_id=ACCOUNT_UUID,
                                     account=reads()[0], assets=reads()[1])

    def test_response_resources_cannot_be_swapped(self):
        with self.assertRaises(ContractError):
            self.ingest(account=reads()[1], assets=reads()[0])

    def test_other_account_route_cannot_read_this_import(self):
        self.ingest()
        other = replace(ROUTE, connection_id="other")
        self.store.register_account(other)
        self.assertIsNone(self.store.reference_import_as_of(other, "batch-1", as_of=LATER))

    def test_result_or_raw_corruption_is_detected(self):
        self.ingest()
        with self.store.db:
            self.store.db.execute("UPDATE raw_objects SET payload=?", (b"bad",))
        with self.assertRaises(EvidenceIntegrityError):
            self.store.reference_import_as_of(ROUTE, "batch-1", as_of=LATER)

    def test_result_hash_is_verified(self):
        self.ingest()
        with self.store.db:
            self.store.db.execute("UPDATE broker_reference_imports SET result_json='{}'")
        with self.assertRaises(EvidenceIntegrityError):
            self.store.reference_import_as_of(ROUTE, "batch-1", as_of=LATER)

    def test_input_envelope_corruption_is_detected(self):
        self.ingest()
        with self.store.db:
            self.store.db.execute("UPDATE broker_reference_imports SET input_json=input_json || ' '")
        with self.assertRaises(EvidenceIntegrityError):
            self.store.reference_import_as_of(ROUTE, "batch-1", as_of=LATER)

    def test_clock_rollback_does_not_backdate_a_completed_import(self):
        self.ingest()
        self.store._clock = lambda: RECEIVED
        with self.assertRaises(ContractError):
            self.ingest()

    def test_sync_fetches_only_account_and_assets_then_reuses_completed_batch(self):
        class SequenceOpener:
            def __init__(inner):
                inner.calls = []
            def open(inner, request, timeout):
                inner.calls.append(request.full_url)
                payload = raw(account_record()) if request.full_url.endswith('/account') else raw([asset_record()])
                return FakeResponse(payload, url=request.full_url)
        opener = SequenceOpener()
        reader = AlpacaReferenceReader("fixture-key", "fixture-secret", opener=opener, clock=lambda: RECEIVED)
        args = dict(import_id="sync", source_id="fixture-source", expected_native_id=ACCOUNT_UUID, reader=reader)
        result = self.store.sync_alpaca(ROUTE, **args)
        self.assertEqual(result["report"]["account"]["native_id"], ACCOUNT_UUID)
        self.assertEqual(result, self.store.sync_alpaca(ROUTE, **args))
        self.assertEqual(opener.calls, [PAPER_HOST + "/v2/account", PAPER_HOST + "/v2/assets"])
        with self.assertRaises(RecordConflict):
            self.store.sync_alpaca(ROUTE, **(args | dict(expected_native_id=OTHER_UUID)))
        self.assertEqual(len(opener.calls), 2)

    def test_sync_requires_source_permissions_before_network_reads(self):
        opener = FakeOpener()
        reader = AlpacaReferenceReader("fixture-key", "fixture-secret", opener=opener)
        with self.assertRaises(UseNotAllowed):
            self.store.sync_alpaca(ROUTE, import_id="sync", source_id="unknown", expected_native_id=ACCOUNT_UUID, reader=reader)
        self.assertEqual(opener.requests, [])

    def test_partial_http_failure_does_not_publish_a_complete_batch(self):
        class PartialFailure:
            def open(inner, request, timeout):
                if request.full_url.endswith("/assets"):
                    raise URLError("failure")
                return FakeResponse(raw(account_record()))
        reader = AlpacaReferenceReader("fixture-key", "fixture-secret", opener=PartialFailure(), clock=lambda: RECEIVED)
        with self.assertRaises(BrokerReadError):
            self.store.sync_alpaca(ROUTE, import_id="sync", source_id="fixture-source", expected_native_id=ACCOUNT_UUID, reader=reader)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM broker_reference_imports").fetchone()[0], 0)

    def test_batch_envelope_cannot_be_replayed_for_another_account(self):
        self.ingest()
        other = replace(ROUTE, connection_id="different")
        self.store.register_account(other)
        row = self.store.db.execute("SELECT * FROM broker_reference_imports").fetchone()
        fields = dict(row)
        fields["account_key"] = other.key
        with self.store.db:
            self.store._immutable("broker_reference_imports", {"account_key": other.key, "import_id": "batch-1"}, fields)
        with self.assertRaises(EvidenceIntegrityError):
            self.store.reference_import_as_of(other, "batch-1", as_of=LATER)


class FakeResponse(io.BytesIO):
    def __init__(self, payload, *, url=PAPER_HOST + "/v2/account", status=200, content_type="application/json"):
        super().__init__(payload)
        self.url, self.status = url, status
        self.headers = {"Content-Type": content_type}

    def geturl(self):
        return self.url


class FakeOpener:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.requests = response, error, []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if self.error is not None:
            raise self.error
        return self.response


class ReaderTests(unittest.TestCase):
    def reader(self, opener, **options):
        return AlpacaReferenceReader("fixture-key", "fixture-secret", opener=opener, clock=lambda: RECEIVED, **options)

    def test_exact_get_endpoint_headers_and_receipt_after_read(self):
        opener = FakeOpener(FakeResponse(raw(account_record())))
        result = self.reader(opener).read("account")
        request, timeout = opener.requests[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.full_url, PAPER_HOST + "/v2/account")
        self.assertEqual(result.received_at, RECEIVED)
        self.assertEqual(timeout, 10)
        self.assertIsNone(request.data)

    def test_assets_path_has_no_account_or_order_operations(self):
        opener = FakeOpener(FakeResponse(b"[]", url=PAPER_HOST + "/v2/assets"))
        self.reader(opener).read("assets")
        self.assertEqual(opener.requests[0][0].full_url, PAPER_HOST + "/v2/assets")

    def test_arbitrary_paths_and_order_requests_are_rejected_before_http(self):
        opener = FakeOpener()
        for resource in ("orders", "/v2/account", "https://other.test", "../orders"):
            with self.subTest(resource=resource), self.assertRaises(BrokerReadError):
                self.reader(opener).read(resource)
        self.assertEqual(opener.requests, [])

    def test_redirect_handler_never_forwards_credentials(self):
        self.assertIsNone(_NoRedirect().redirect_request(Request(PAPER_HOST), None, 302, "", {}, "https://other.test"))
        with self.assertRaises(BrokerReadError):
            self.reader(FakeOpener(FakeResponse(b"{}", url="https://other.test"))).read("account")

    def test_http_errors_and_connection_errors_do_not_leak_response_bodies(self):
        for error in (HTTPError(PAPER_HOST, 401, "fixture-secret", {}, io.BytesIO(b"private-response")),
                      URLError("fixture-secret"), TimeoutError("fixture-secret")):
            with self.subTest(error=type(error)), self.assertRaises(BrokerReadError) as raised:
                self.reader(FakeOpener(error=error)).read("account")
            self.assertNotIn("fixture-secret", str(raised.exception))
            self.assertNotIn("private-response", str(raised.exception))

    def test_wrong_content_type_status_empty_or_oversize_body_is_rejected(self):
        responses = (FakeResponse(b"{}", content_type="text/html"), FakeResponse(b"{}", status=201),
                     FakeResponse(b""), FakeResponse(b"x" * (MAX_RESPONSE_BYTES + 1)))
        for response in responses:
            with self.subTest(size=len(response.getvalue())), self.assertRaises(BrokerReadError):
                self.reader(FakeOpener(response)).read("account")

    def test_header_injection_and_unbounded_timeouts_are_rejected(self):
        with self.assertRaises(BrokerReadError):
            AlpacaReferenceReader("bad\nkey", "fixture-secret")
        for timeout in (0, 31, True, float("inf")):
            with self.subTest(timeout=timeout), self.assertRaises(BrokerReadError):
                self.reader(FakeOpener(), timeout=timeout)


class ImportPersistenceTests(unittest.TestCase):
    def test_reopening_preserves_processed_result_and_original_raw_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "import.sqlite3"
            with BrokerImportStore(path, clock=lambda: AVAILABLE) as store:
                store.register_source("source", DataOrigin.SYNTHETIC)
                store.set_permissions("source", known_at=START, uses={Use.STORAGE, Use.RESEARCH})
                store.register_account(ROUTE)
                first = store.import_alpaca(ROUTE, import_id="batch", source_id="source", expected_native_id=ACCOUNT_UUID,
                                            account=reads()[0], assets=reads()[1])
            with BrokerImportStore(path, clock=lambda: LATER) as store:
                self.assertEqual(store.reference_import_as_of(ROUTE, "batch", as_of=LATER), first)

    def test_offline_import_demo_reopens_without_duplication(self):
        from trading_intelligence.import_demo import reference_import_demo
        with tempfile.TemporaryDirectory() as temporary:
            first = reference_import_demo(Path(temporary))
            self.assertEqual(first, reference_import_demo(Path(temporary)))
            self.assertEqual(first["normalized_assets"], 1)
            self.assertEqual(first["quarantined_rows"], 1)
            self.assertTrue(first["unavailable_before_processing"])

    def test_cli_missing_keys_does_not_attempt_network_or_print_credentials(self):
        import contextlib
        from unittest.mock import patch
        from trading_intelligence.cli import main
        args = ["trading-intelligence", "alpaca-sync", "--database", "unused.sqlite3", "--connection-id", "fixture",
                "--account-number", "fixture-account", "--expected-account-id", ACCOUNT_UUID,
                "--source-id", "source", "--import-id", "job"]
        output = io.StringIO()
        with patch("sys.argv", args), patch.dict("os.environ", {}, clear=True), contextlib.redirect_stderr(output):
            with self.assertRaises(SystemExit) as raised:
                main()
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("ALPACA_PAPER_API_KEY", output.getvalue())


if __name__ == "__main__":
    unittest.main()
