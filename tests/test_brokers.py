"""Synthetic multi-broker contract tests; never connect to a broker."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path
import tempfile
import unittest

from trading_intelligence.brokers import (
    AdapterRegistry, BrokerAccount, BrokerCapabilities, BrokerCheckFailed, ContractPaperAdapter,
    Environment, InstrumentTarget, NativeBinding, OrderIntent, OrderRule, SessionMode,
    Side, SymbolPaperAdapter, TargetKind, TimeInForce,
)
from trading_intelligence.broker_store import BrokerStore
from trading_intelligence.contracts import (
    AssetKind, ContractError, DataOrigin, Entity, EvidenceIntegrityError, Instrument,
    Listing, RecordConflict, Use, UseNotAllowed,
)
from trading_intelligence.futures import FutureContract, FutureProduct, FutureTerms, PriceKind, Settlement
from trading_intelligence.references import ReferenceRepository, ReferenceUnavailable


START = datetime(2026, 1, 1, tzinfo=timezone.utc)
NOW = START + timedelta(days=1)
LATER = NOW + timedelta(hours=1)
END = START + timedelta(days=5)


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.store = BrokerStore(":memory:")
        self.addCleanup(self.store.close)
        self.store.register_source("fixture", DataOrigin.SYNTHETIC)
        self.store.set_permissions("fixture", known_at=START, uses={Use.STORAGE, Use.RESEARCH})
        evidence = self.store.ingest(source_id="fixture", record_id="refs", revision_id="1", payload=b"invented broker records",
                                     published_at=START, received_at=START)
        self.times = dict(valid_from=START, valid_to=END, known_at=START, evidence_id=evidence)
        self.store.register_entity(Entity("issuer", "Invented issuer"))
        self.store.register_instrument(Instrument("equity", "issuer", AssetKind.EQUITY))
        self.store.register_listing(Listing("listing", "equity", "XNAS", "USD"))
        self.target = InstrumentTarget(TargetKind.LISTING, "listing")
        self.a = BrokerAccount("symbol-broker", "connection", "same-account", Environment.PAPER)
        self.b = BrokerAccount("contract-broker", "connection", "same-account", Environment.PAPER)
        self.rule = OrderRule(AssetKind.EQUITY, TimeInForce.DAY, SessionMode.REGULAR)
        self.caps = BrokerCapabilities((self.rule,), prepare_enabled=True)
        self.binding = NativeBinding(self.target, "native-id-a", "DEMO.A", "XNAS", "USD", D("0.01"), D("1"), D("1"))
        self.adapters = AdapterRegistry()
        for account, adapter, native_id, symbol in (
            (self.a, SymbolPaperAdapter(self.a), "native-id-a", "DEMO.A"),
            (self.b, ContractPaperAdapter(self.b), "native-id-b", "OTHER-DEMO"),
        ):
            self.store.register_account(account)
            self.adapters.register(adapter)
            self.store.put_capabilities(account, self.caps, **self.times)
            self.store.put_binding(account, replace(self.binding, native_id=native_id, symbol=symbol), **self.times)
        self.intent = OrderIntent("intent-1", "strategy-1", self.target, Side.BUY, D("2"), D("100.25"), NOW, END)

    def prepare(self, account=None, intent=None, **changes):
        return self.store.prepare(account or self.a, intent or self.intent,
                                  **(dict(prepared_at=NOW, adapters=self.adapters) | changes))

    def new_intent(self, **changes):
        return replace(self.intent, intent_id="new-intent", **changes)

    def test_same_intent_is_encoded_differently_for_two_brokers(self):
        a, b = self.prepare(self.a), self.prepare(self.b)
        self.assertEqual(a.payload["symbol"], "DEMO.A")
        self.assertEqual(b.payload["contract_id"], "native-id-b")
        self.assertEqual(b.payload["units"], "2")
        self.assertNotIn("symbol", b.payload)
        self.assertNotEqual(a.client_order_id, b.client_order_id)
        self.assertNotEqual(a.account_key, b.account_key)
        self.assertEqual(a.state, "prepared_offline")

    def test_retry_returns_same_persisted_client_id_and_payload(self):
        first = self.prepare()
        second = self.prepare(prepared_at=LATER)
        self.assertFalse(first.replayed)
        self.assertTrue(second.replayed)
        self.assertEqual(first.client_order_id, second.client_order_id)
        self.assertEqual(first.payload, second.payload)
        self.assertEqual(first.prepared_at, second.prepared_at)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM broker_drafts").fetchone()[0], 1)

    def test_changed_inputs_cannot_reuse_an_existing_intent_key(self):
        self.prepare()
        for changes in (dict(quantity=D("3")), dict(strategy_id="other"), dict(side=Side.SELL), dict(limit_price=D("101"))):
            with self.subTest(changes=changes), self.assertRaises(RecordConflict):
                self.prepare(intent=replace(self.intent, **changes))

    def test_saved_draft_is_an_audit_record_not_a_refreshed_order(self):
        original = self.prepare()
        self.store.put_binding(self.a, replace(self.binding, symbol="CORRECTED"),
                               **(self.times | dict(known_at=LATER)))
        self.assertEqual(self.prepare(prepared_at=END + timedelta(days=1), adapters=AdapterRegistry()).payload, original.payload)
        new = self.prepare(intent=self.new_intent(), prepared_at=LATER)
        self.assertEqual(new.payload["symbol"], "CORRECTED")
        self.assertNotEqual(new.snapshot_ids, original.snapshot_ids)

    def test_account_namespace_contains_broker_connection_account_and_environment(self):
        variants = (replace(self.a, broker_id="other"), replace(self.a, connection_id="other"),
                    replace(self.a, account_id="other"), replace(self.a, environment=Environment.LIVE))
        self.assertEqual(len({self.a.key, *(x.key for x in variants)}), 5)
        for account in variants:
            with self.subTest(account=account), self.assertRaises(BrokerCheckFailed):
                self.prepare(account)

    def test_missing_adapter_does_not_fallback_to_another_broker(self):
        registry = AdapterRegistry()
        registry.register(ContractPaperAdapter(self.b))
        with self.assertRaises(BrokerCheckFailed):
            self.prepare(adapters=registry)

    def test_adapter_cannot_be_silently_replaced(self):
        with self.assertRaises(BrokerCheckFailed):
            self.adapters.register(ContractPaperAdapter(self.a))

    def test_live_account_and_adapter_are_blocked(self):
        live = replace(self.a, environment=Environment.LIVE)
        self.store.register_account(live)
        with self.assertRaises(BrokerCheckFailed):
            self.prepare(live)
        with self.assertRaises(BrokerCheckFailed):
            self.adapters.register(SymbolPaperAdapter(live))

    def test_missing_mapping_on_another_connection_is_not_shared(self):
        account = replace(self.a, connection_id="second-connection")
        self.store.register_account(account)
        self.store.put_capabilities(account, self.caps, **self.times)
        self.adapters.register(SymbolPaperAdapter(account))
        with self.assertRaises(ReferenceUnavailable):
            self.prepare(account)

    def test_missing_capability_blocks_even_if_mapping_exists(self):
        account = replace(self.a, account_id="different-account")
        self.store.register_account(account)
        self.store.put_binding(account, self.binding, **self.times)
        self.adapters.register(SymbolPaperAdapter(account))
        with self.assertRaises(ReferenceUnavailable):
            self.prepare(account)

    def test_capability_disabled_by_default(self):
        self.store.put_capabilities(self.a, BrokerCapabilities((self.rule,)), **(self.times | dict(known_at=LATER)))
        with self.assertRaises(BrokerCheckFailed):
            self.prepare(prepared_at=LATER)

    def test_order_combinations_are_not_inferred_from_independent_flags(self):
        caps = BrokerCapabilities((self.rule, OrderRule(AssetKind.EQUITY, TimeInForce.GTC, SessionMode.EXTENDED)), True)
        self.store.put_capabilities(self.a, caps, **(self.times | dict(known_at=LATER)))
        with self.assertRaises(BrokerCheckFailed):
            self.prepare(intent=self.new_intent(time_in_force=TimeInForce.DAY, session=SessionMode.EXTENDED), prepared_at=LATER)

    def test_duplicate_capability_combinations_are_rejected(self):
        with self.assertRaises(ContractError):
            BrokerCapabilities((self.rule, replace(self.rule, fractional_quantity=True)), True)

    def test_stale_capability_and_binding_block_new_drafts(self):
        for field in ("capabilities", "binding"):
            with self.subTest(field=field):
                if field == "capabilities":
                    self.store.put_capabilities(self.a, self.caps, **(self.times | dict(known_at=LATER, valid_to=LATER)))
                else:
                    self.store.put_binding(self.b, replace(self.binding, native_id="native-id-b"),
                                           **(self.times | dict(known_at=LATER, valid_to=LATER)))
                with self.assertRaises(ReferenceUnavailable):
                    self.prepare(self.a if field == "capabilities" else self.b, prepared_at=LATER)

    def test_future_capability_change_does_not_rewrite_old_knowledge(self):
        self.store.put_capabilities(self.a, BrokerCapabilities((), False), **(self.times | dict(known_at=LATER)))
        self.assertEqual(self.prepare().payload["symbol"], "DEMO.A")
        with self.assertRaises(BrokerCheckFailed):
            self.prepare(intent=self.new_intent(), prepared_at=LATER)

    def test_overlapping_account_bindings_are_rejected(self):
        self.store.put_binding(self.a, self.binding, **(self.times | dict(known_at=LATER, valid_from=NOW)))
        with self.assertRaises(ReferenceUnavailable):
            self.prepare(prepared_at=LATER)

    def test_tick_and_quantity_not_silently_rounded(self):
        for changes in (dict(limit_price=D("100.251")), dict(quantity=D("0.5"))):
            with self.subTest(changes=changes), self.assertRaises(BrokerCheckFailed):
                self.prepare(intent=self.new_intent(**changes))

    def test_fractional_shares_need_both_capability_and_lot_support(self):
        rule = replace(self.rule, fractional_quantity=True)
        self.store.put_capabilities(self.a, BrokerCapabilities((rule,), True), **(self.times | dict(known_at=LATER)))
        with self.assertRaises(BrokerCheckFailed):
            self.prepare(intent=self.new_intent(quantity=D("0.5")), prepared_at=LATER)
        self.store.put_binding(self.a, replace(self.binding, quantity_step=D("0.1"), minimum_quantity=D("0.1")),
                               **(self.times | dict(known_at=LATER)))
        self.assertEqual(self.prepare(intent=self.new_intent(quantity=D("0.5")), prepared_at=LATER).payload["quantity"], "0.5")

    def test_mapping_cannot_substitute_currency_venue_or_unknown_target(self):
        for change in (dict(currency="EUR"), dict(venue_mic="XNYS"),
                       dict(target=InstrumentTarget(TargetKind.LISTING, "unknown"))):
            with self.subTest(change=change), self.assertRaises(BrokerCheckFailed):
                self.store.put_binding(self.a, replace(self.binding, **change), **self.times)

    def test_two_canonical_instruments_cannot_route_to_one_native_identity(self):
        self.store.register_instrument(Instrument("other-equity", "issuer", AssetKind.EQUITY))
        self.store.register_listing(Listing("other-listing", "other-equity", "XNAS", "USD"))
        other = replace(self.binding, target=InstrumentTarget(TargetKind.LISTING, "other-listing"), symbol="DIFFERENT")
        self.store.put_binding(self.a, other, **self.times)
        with self.assertRaises(BrokerCheckFailed):
            self.prepare()

    def test_symbol_collision_is_blocked_even_when_native_ids_differ(self):
        self.store.register_listing(Listing("second-listing", "equity", "XNAS", "USD"))
        other = replace(self.binding, target=InstrumentTarget(TargetKind.LISTING, "second-listing"), native_id="different-id")
        self.store.put_binding(self.a, other, **self.times)
        with self.assertRaises(BrokerCheckFailed):
            self.prepare()

    def test_float_nan_zero_and_invalid_time_inputs_are_rejected(self):
        for change in (dict(quantity=D("0")), dict(quantity=1.0), dict(limit_price=D("NaN")),
                       dict(valid_until=NOW), dict(decision_at=datetime(2026, 1, 2))):
            with self.subTest(change=change), self.assertRaises(ContractError):
                self.new_intent(**change)

    def test_expired_or_future_intent_is_not_prepared(self):
        for at in (START, END):
            with self.subTest(at=at), self.assertRaises(BrokerCheckFailed):
                self.prepare(prepared_at=at)

    def test_adjusted_and_nonpositive_equity_prices_are_rejected(self):
        for changes in (dict(price_kind=PriceKind.ADJUSTED_SERIES), dict(limit_price=D("0")), dict(limit_price=D("-1"))):
            with self.subTest(changes=changes), self.assertRaises(BrokerCheckFailed):
                self.prepare(intent=self.new_intent(**changes))

    def test_raw_and_snapshot_corruption_are_detected(self):
        with self.store.db:
            self.store.db.execute("UPDATE broker_snapshots SET body='{}' WHERE kind='capabilities'")
        with self.assertRaises(EvidenceIntegrityError):
            self.prepare()

    def test_raw_evidence_corruption_is_detected(self):
        with self.store.db:
            self.store.db.execute("UPDATE raw_objects SET payload=?", (b"tampered",))
        with self.assertRaises(EvidenceIntegrityError):
            self.prepare()

    def test_journal_corruption_is_detected(self):
        self.prepare()
        with self.store.db:
            self.store.db.execute("UPDATE broker_drafts SET draft_json='{}'")
        with self.assertRaises(EvidenceIntegrityError):
            self.prepare()

    def test_revoked_source_cannot_prepare_new_draft(self):
        self.store.set_permissions("fixture", known_at=LATER, uses={Use.STORAGE})
        with self.assertRaises(UseNotAllowed):
            self.prepare(prepared_at=LATER)

    def test_reference_tables_cannot_be_selected_from_external_input(self):
        with self.assertRaises(ContractError):
            ReferenceRepository(self.store, "broker_snapshots; DROP TABLE broker_accounts")

    def test_ordinary_funds_cannot_enter_the_equity_order_path(self):
        with self.assertRaises(ContractError):
            OrderRule(AssetKind.MUTUAL_FUND, TimeInForce.DAY, SessionMode.REGULAR)

    def test_target_types_are_distinct_even_with_the_same_text_identifier(self):
        with self.assertRaises(BrokerCheckFailed):
            self.prepare(intent=self.new_intent(target=InstrumentTarget(TargetKind.FUTURE, "listing")))

    def test_futures_expiry_uses_exact_binding_and_terms(self):
        self.store.register_product(FutureProduct("micro", "DEMO", "XOFF", "equity", "USD", "points"))
        self.store.register_contract(FutureContract("march", "micro", "2026-03"))
        target = InstrumentTarget(TargetKind.FUTURE, "march")
        self.store.put_terms("march", FutureTerms(D("0.25"), D("2"), Settlement.CASH, END, END), **self.times)
        self.store.put_capabilities(self.b, BrokerCapabilities((OrderRule(AssetKind.FUTURE, TimeInForce.DAY, SessionMode.REGULAR),), True),
                                    **(self.times | dict(known_at=LATER)))
        binding = NativeBinding(target, "future-987", "DEMOH26", "XOFF", "USD", D("0.01"), D("1"), D("1"))
        self.store.put_binding(self.b, binding, **self.times)
        intent = self.new_intent(target=target)
        draft = self.prepare(self.b, intent, prepared_at=LATER)
        self.assertEqual(draft.payload["contract_id"], "future-987")
        self.assertEqual(len(draft.snapshot_ids), 3)
        with self.assertRaises(ContractError):
            self.prepare(self.b, replace(intent, intent_id="off-exchange-tick", limit_price=D("100.26")), prepared_at=LATER)
        with self.assertRaises(BrokerCheckFailed):
            self.store.put_binding(self.b, replace(binding, quantity_step=D("0.5")), **self.times)


class BrokerPersistenceTests(unittest.TestCase):
    def test_drafts_survive_restart_and_adapters_are_not_stored_as_code(self):
        from trading_intelligence.broker_demo import broker_demo
        with tempfile.TemporaryDirectory() as directory:
            first = broker_demo(Path(directory))
            second = broker_demo(Path(directory))
            self.assertEqual(first["persisted_draft_count"], 2)
            self.assertEqual(second["persisted_draft_count"], 2)
            self.assertEqual([x["client_order_id"] for x in first["drafts"]], [x["client_order_id"] for x in second["drafts"]])
            self.assertTrue(all(x["replayed"] for x in second["drafts"]))
            self.assertTrue(second["retry_reused_original"])
            self.assertEqual(second["orders_sent"], 0)
            with BrokerStore(Path(directory) / "brokers.sqlite3") as store:
                self.assertEqual(store.db.execute("SELECT count(*) FROM broker_accounts").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
