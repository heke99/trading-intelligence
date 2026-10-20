"""Synthetic futures regression cases. No vendor data, broker or network."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D, localcontext
from pathlib import Path
import sqlite3
import tempfile
import unittest
from zoneinfo import ZoneInfo

from trading_intelligence import AssetKind, DataOrigin, Entity, Instrument, Use
from trading_intelligence.contracts import ContractError, EvidenceIntegrityError, RecordConflict, UseNotAllowed
from trading_intelligence.futures import (
    CollateralSnapshot, FutureContract, FutureProduct, FutureTerms, FuturesCheckFailed,
    FuturesMargin, FuturesResearchLimits, FuturesUnavailable, PriceKind, Session,
    Settlement, TradingSchedule,
)
from trading_intelligence.futures_demo import futures_demo
from trading_intelligence.futures_store import FuturesStore


START = datetime(2026, 1, 1, tzinfo=timezone.utc)
NOW = START + timedelta(days=1, hours=12)
END = START + timedelta(days=5)
LATER = NOW + timedelta(hours=1)


class FuturesTests(unittest.TestCase):
    def setUp(self):
        self.store = FuturesStore(":memory:")
        self.addCleanup(self.store.close)
        self.store.register_source("synthetic", DataOrigin.SYNTHETIC)
        self.store.set_permissions("synthetic", known_at=START, uses={Use.STORAGE, Use.RESEARCH})
        self.evidence = self.store.ingest(source_id="synthetic", record_id="ref", revision_id="1",
                                          payload=b"invented reference data", published_at=START, received_at=START)
        self.store.register_entity(Entity("publisher", "Invented publisher"))
        self.store.register_instrument(Instrument("index", "publisher", AssetKind.INDEX))
        self.product = FutureProduct("micro", "DEMO", "XOFF", "index", "USD", "index_points")
        self.contract = FutureContract("march", "micro", "2026-03")
        self.store.register_product(self.product)
        self.store.register_contract(self.contract)
        self.terms = FutureTerms(D("0.25"), D("2"), Settlement.CASH, END, END - timedelta(days=1))
        self.times = dict(valid_from=START, valid_to=END, known_at=START, evidence_id=self.evidence)
        self.store.put_terms("march", self.terms, **self.times)
        self.schedule = TradingSchedule("America/Chicago", (
            Session(START, START + timedelta(days=2)),
            Session(START + timedelta(days=2, hours=1), END),
        ))
        self.store.put_schedule("micro", self.schedule, **self.times)
        self.store.put_broker_binding("broker", "DEMOH26", "march", "broker-123", **self.times)
        self.store.put_margin("broker", "account", "march", FuturesMargin(D("1500"), D("1200"), "USD"), **self.times)
        self.collateral = CollateralSnapshot("broker", "account", D("10000"), "USD", START, END)
        self.limits = FuturesResearchLimits(3, D("100000"), D("1.2"))

    def preview(self, **changes):
        args = dict(broker="broker", account_id="account", identifier="DEMOH26", decision_at=NOW,
                    quantity=2, price=D("100.25"), price_kind=PriceKind.RAW_CONTRACT,
                    collateral=self.collateral, limits=self.limits)
        return self.store.preview_opening_intent(**(args | changes))

    def update_terms(self, terms, **changes):
        return self.store.put_terms("march", terms, **(self.times | dict(known_at=LATER) | changes))

    def test_future_is_not_an_issuer_share_class(self):
        self.assertEqual(self.contract.kind, AssetKind.FUTURE)
        with self.assertRaises(ContractError):
            Instrument("not-an-equity", "publisher", AssetKind.FUTURE)

    def test_contract_requires_existing_product(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.register_contract(FutureContract("unknown", "missing", "2026-03"))

    def test_product_requires_existing_underlying(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.register_product(replace(self.product, product_id="other", underlying_instrument_id="unknown"))

    def test_root_and_contract_identities_cannot_change(self):
        with self.assertRaises(RecordConflict):
            self.store.register_product(replace(self.product, root="OTHER"))
        with self.assertRaises(RecordConflict):
            self.store.register_contract(replace(self.contract, contract_month="2026-06"))

    def test_invalid_month_is_rejected(self):
        for month in ("2026-13", "2026-3", "continuous", "0000-01", None):
            with self.subTest(month=month), self.assertRaises(ContractError):
                FutureContract("test", "micro", month)

    def test_exact_tick_pnl_and_notional(self):
        result = self.preview()
        self.assertEqual(result.tick_value, D("0.50"))
        self.assertEqual(result.abs_notional, D("401.00"))
        self.assertEqual(result.initial_margin_required, D("3600.0"))
        self.assertEqual(result.maintenance_margin_required, D("2400"))
        self.assertEqual(self.terms.gross_pnl(D("100.25"), D("101.25"), 2), D("4.00"))
        self.assertEqual(self.terms.gross_pnl(D("100.25"), D("101.25"), -2), D("-4.00"))
        self.assertFalse(result.live_trading)
        self.assertEqual(len(set(result.snapshot_ids)), 4)

    def test_decimal_arithmetic_does_not_depend_on_callers_precision(self):
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(self.preview().abs_notional, D("401.00"))
            self.assertEqual(self.terms.gross_pnl(D("100.25"), D("101.25"), 2), D("4.00"))

    def test_micro_and_standard_multipliers_are_not_interchangeable(self):
        standard = replace(self.terms, multiplier=D("20"))
        self.assertEqual(standard.tick_value, D("5.00"))
        self.assertEqual(standard.gross_pnl(D("100"), D("101"), 2), D("40"))

    def test_float_and_nonfinite_money_rejected(self):
        for price in (100.25, D("NaN"), D("Infinity"), D("1e100")):
            with self.subTest(price=price), self.assertRaises(ContractError):
                self.preview(price=price)

    def test_off_tick_price_is_not_rounded_into_order(self):
        for price in (D("100.26"), D("100.250000000001")):
            with self.subTest(price=price), self.assertRaises(FuturesCheckFailed):
                self.preview(price=price)

    def test_fractional_zero_boolean_and_oversize_quantities_rejected(self):
        for quantity in (D("0.5"), 1.0, 0, True, 2_147_483_648):
            with self.subTest(quantity=quantity), self.assertRaises(ContractError):
                self.preview(quantity=quantity)

    def test_unknown_and_continuous_symbols_have_no_implicit_mapping(self):
        for symbol in ("DEMO", "DEMO1!", "demoH26", "NASDAQ", "DEMOH26' OR 1=1 --"):
            with self.subTest(symbol=symbol), self.assertRaises(FuturesUnavailable):
                self.preview(identifier=symbol)

    def test_continuous_or_unknown_contract_cannot_be_bound(self):
        with self.assertRaises(FuturesUnavailable):
            self.store.put_broker_binding("broker", "DEMO1!", "continuous", "123", **self.times)

    def test_adjusted_series_price_is_rejected(self):
        with self.assertRaises(FuturesCheckFailed):
            self.preview(price_kind=PriceKind.ADJUSTED_SERIES)

    def test_short_needs_explicit_research_permission(self):
        with self.assertRaises(FuturesCheckFailed):
            self.preview(quantity=-1)
        self.assertEqual(self.preview(quantity=-1, limits=replace(self.limits, allow_short=True)).quantity, -1)

    def test_per_intent_quantity_notional_and_collateral_limits(self):
        changes = (dict(quantity=4), dict(limits=replace(self.limits, max_abs_notional_per_intent=D("400"))),
                   dict(collateral=replace(self.collateral, available=D("3599.99"))))
        for change in changes:
            with self.subTest(change=change), self.assertRaises(FuturesCheckFailed):
                self.preview(**change)

    def test_margin_buffer_cannot_reduce_margin(self):
        with self.assertRaises(ContractError):
            replace(self.limits, margin_buffer=D("0.5"))

    def test_collateral_requires_matching_account_currency_and_freshness(self):
        bad = (replace(self.collateral, broker="other"), replace(self.collateral, account_id="other"),
               replace(self.collateral, currency="EUR"), replace(self.collateral, expires_at=NOW),
               replace(self.collateral, observed_at=LATER))
        for collateral in bad:
            with self.subTest(collateral=collateral), self.assertRaises(FuturesCheckFailed):
                self.preview(collateral=collateral)

    def test_cross_currency_margin_is_not_assumed(self):
        with self.assertRaises(ContractError):
            self.store.put_margin("broker", "account", "march", FuturesMargin(D("100"), D("90"), "EUR"), **self.times)

    def test_intraday_discount_is_not_treated_as_full_initial_margin(self):
        with self.assertRaises(ContractError):
            FuturesMargin(D("50"), D("1200"), "USD")

    def test_missing_or_other_account_margin_is_blocked(self):
        other = replace(self.collateral, account_id="other")
        with self.assertRaises(FuturesUnavailable):
            self.preview(account_id="other", collateral=other)

    def test_expired_margin_is_not_reused(self):
        self.store.put_margin("broker", "account", "march", FuturesMargin(D("1500"), D("1200"), "USD"),
                              **(self.times | dict(known_at=LATER, valid_to=LATER + timedelta(minutes=5))))
        with self.assertRaises(FuturesUnavailable):
            self.preview(decision_at=LATER + timedelta(minutes=5))

    def test_future_margin_is_unavailable_until_known(self):
        self.store.put_margin("broker", "account", "march", FuturesMargin(D("6000"), D("5000"), "USD"),
                              **(self.times | dict(known_at=LATER)))
        self.assertEqual(self.preview().initial_margin_required, D("3600"))
        with self.assertRaises(FuturesCheckFailed):
            self.preview(decision_at=LATER)

    def test_margin_snapshots_do_not_overwrite_history(self):
        self.store.put_margin("broker", "account", "march", FuturesMargin(D("2000"), D("1600"), "USD"),
                              **(self.times | dict(known_at=LATER)))
        self.assertEqual(self.preview().initial_margin_required, D("3600"))
        self.assertEqual(self.preview(decision_at=LATER).initial_margin_required, D("4800"))

    def test_snapshot_same_version_is_idempotent_and_conflict_is_blocked(self):
        first = self.store.put_terms("march", self.terms, **self.times)
        self.assertEqual(first, self.store.put_terms("march", self.terms, **self.times))
        with self.assertRaises(RecordConflict):
            self.store.put_terms("march", replace(self.terms, multiplier=D("20")), **self.times)

    def test_future_evidence_cannot_backdate_terms(self):
        later = self.store.ingest(source_id="synthetic", record_id="later", revision_id="1",
                                  payload=b"late observation", published_at=START, received_at=LATER)
        with self.assertRaises(FuturesUnavailable):
            self.update_terms(self.terms, known_at=NOW, evidence_id=later)

    def test_reference_use_is_revoked_even_for_existing_snapshots(self):
        self.store.set_permissions("synthetic", known_at=LATER, uses={Use.STORAGE})
        with self.assertRaises(UseNotAllowed):
            self.preview(decision_at=LATER)

    def test_terms_correction_preserves_old_known_values(self):
        self.update_terms(replace(self.terms, multiplier=D("20")))
        self.assertEqual(self.preview().tick_value, D("0.5"))
        self.assertEqual(self.preview(decision_at=LATER).tick_value, D("5"))

    def test_overlapping_effective_snapshots_are_ambiguous(self):
        self.update_terms(self.terms, valid_from=NOW)
        with self.assertRaises(FuturesUnavailable):
            self.preview(decision_at=LATER)

    def test_missing_or_expired_contract_reference_is_blocked(self):
        self.store.register_contract(FutureContract("june", "micro", "2026-06"))
        self.store.put_broker_binding("broker", "DEMOJUNE", "june", "june-123", **self.times)
        with self.assertRaises(FuturesUnavailable):
            self.preview(identifier="DEMOJUNE")
        self.update_terms(self.terms, valid_to=LATER)
        with self.assertRaises(FuturesUnavailable):
            self.preview(decision_at=LATER)

    def test_overlapping_broker_bindings_are_blocked(self):
        self.store.put_broker_binding("broker", "DEMOH26", "march", "different-123",
                                     **(self.times | dict(known_at=LATER, valid_from=NOW)))
        with self.assertRaises(FuturesUnavailable):
            self.preview(decision_at=LATER)

    def test_no_calendar_fallback_outside_valid_coverage(self):
        self.store.put_schedule("micro", self.schedule,
                                **(self.times | dict(known_at=LATER, valid_from=START)))
        # Corrected snapshot contains no session at the intended time.
        self.store.put_schedule("micro", TradingSchedule("UTC", ()),
                                **(self.times | dict(known_at=LATER + timedelta(minutes=1))))
        with self.assertRaises(FuturesCheckFailed):
            self.preview(decision_at=LATER + timedelta(minutes=1))

    def test_empty_reference_interval_is_rejected(self):
        with self.assertRaises(ContractError):
            self.update_terms(self.terms, valid_to=START)

    def test_nonoverlapping_future_effective_terms_do_not_replace_present(self):
        self.update_terms(self.terms, valid_to=START + timedelta(days=3), known_at=NOW)
        self.update_terms(replace(self.terms, multiplier=D("20")),
                          valid_from=START + timedelta(days=3), known_at=NOW)
        self.assertEqual(self.preview(decision_at=LATER).tick_value, D("0.5"))
        self.assertEqual(self.preview(decision_at=START + timedelta(days=3)).tick_value, D("5"))

    def test_entry_cutoff_and_last_trade_boundaries_block_new_openings(self):
        for at in (self.terms.entry_cutoff_at, self.terms.last_trade_at):
            with self.subTest(at=at), self.assertRaises(ContractError):
                self.preview(decision_at=at)

    def test_entry_cutoff_cannot_be_after_last_trade(self):
        with self.assertRaises(ContractError):
            replace(self.terms, entry_cutoff_at=END + timedelta(seconds=1))

    def test_physical_delivery_requires_notice_and_is_excluded_from_pilot(self):
        with self.assertRaises(ContractError):
            replace(self.terms, settlement=Settlement.PHYSICAL)
        physical = replace(self.terms, settlement=Settlement.PHYSICAL,
                           first_notice_at=END - timedelta(hours=1))
        self.update_terms(physical)
        with self.assertRaises(FuturesCheckFailed):
            self.preview(decision_at=LATER)
        with self.assertRaises(ContractError):
            replace(physical, entry_cutoff_at=physical.first_notice_at)

    def test_negative_prices_need_explicit_terms_and_math_stays_signed(self):
        with self.assertRaises(FuturesCheckFailed):
            self.preview(price=D("-1"))
        negative = replace(self.terms, allows_negative_prices=True)
        self.update_terms(negative)
        self.assertEqual(self.preview(price=D("-1.25"), decision_at=LATER).abs_notional, D("5.00"))
        self.assertEqual(negative.gross_pnl(D("-2"), D("-1"), 2), D("4"))

    def test_session_close_maintenance_and_reopen_are_half_open(self):
        for at in (START + timedelta(days=2), START + timedelta(days=2, minutes=30)):
            with self.subTest(at=at), self.assertRaises(FuturesCheckFailed):
                self.preview(decision_at=at)
        self.assertEqual(self.preview(decision_at=START + timedelta(days=2, hours=1)).quantity, 2)

    def test_holiday_snapshot_is_explicitly_closed(self):
        self.store.put_schedule("micro", TradingSchedule("America/Chicago", ()),
                                **(self.times | dict(known_at=LATER)))
        with self.assertRaises(FuturesCheckFailed):
            self.preview(decision_at=LATER)
        self.assertEqual(self.preview().quantity, 2)

    def test_session_coverage_and_order_are_validated(self):
        with self.assertRaises(ContractError):
            TradingSchedule("UTC", (Session(START, END), Session(NOW, END)))
        with self.assertRaises(ContractError):
            self.store.put_schedule("micro", TradingSchedule("UTC", (Session(START - timedelta(hours=1), END),)), **self.times)
        with self.assertRaises(ContractError):
            TradingSchedule("Not/AZone", ())

    def test_overnight_session_crosses_civil_day(self):
        schedule = TradingSchedule("UTC", (Session(START + timedelta(hours=22), START + timedelta(days=1, hours=3)),))
        self.assertTrue(schedule.is_open(START + timedelta(days=1, hours=1)))
        self.assertFalse(schedule.is_open(START + timedelta(days=1, hours=3)))

    def test_dst_uses_real_instants_not_civil_clock_comparison(self):
        zone = ZoneInfo("America/Chicago")
        # Fall-back: 01:30 occurs twice and the two folds must remain distinct.
        first = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
        second = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1)
        session = TradingSchedule("America/Chicago", (Session(first, second),))
        self.assertTrue(session.is_open(first))
        self.assertFalse(session.is_open(second))

    def test_naive_times_rejected(self):
        with self.assertRaises(ContractError):
            self.preview(decision_at=datetime(2026, 1, 2))

    def test_tampered_raw_evidence_blocks_futures_preview(self):
        with self.store.db:
            self.store.db.execute("UPDATE raw_objects SET payload=?", (b"corrupted",))
        with self.assertRaises(EvidenceIntegrityError):
            self.preview()

    def test_tampered_snapshot_body_is_detected(self):
        with self.store.db:
            self.store.db.execute("UPDATE futures_snapshots SET body='{}' WHERE kind='terms'")
        with self.assertRaises(EvidenceIntegrityError):
            self.preview()

    def test_broker_mapping_is_temporal_and_not_cross_broker(self):
        self.store.put_broker_binding("broker", "DEMOH26", "march", "corrected-123",
                                     **(self.times | dict(known_at=LATER)))
        self.assertEqual(self.preview().broker_contract_id, "broker-123")
        self.assertEqual(self.preview(decision_at=LATER).broker_contract_id, "corrected-123")
        with self.assertRaises(FuturesUnavailable):
            self.preview(broker="other", collateral=replace(self.collateral, broker="other"))


class FuturesPersistenceTests(unittest.TestCase):
    def test_demo_reopens_and_reruns_without_duplicate_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            first = futures_demo(Path(directory))
            second = futures_demo(Path(directory))
            self.assertEqual(first, second)
            self.assertEqual(first["preview"]["initial_margin_required"], D("3600"))
            self.assertEqual(len(first["blocked_cases"]), 3)
            with FuturesStore(Path(directory) / "futures.sqlite3") as store:
                self.assertEqual(store.db.execute("SELECT count(*) FROM futures_snapshots").fetchone()[0], 4)

    def test_new_tables_preserve_existing_cash_foundation(self):
        from trading_intelligence.cli import demo
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            before = demo(path)
            with FuturesStore(path / "evidence.sqlite3") as store:
                self.assertEqual(store.counts(), before["counts"])
            self.assertEqual(demo(path), before)


if __name__ == "__main__":
    unittest.main()
