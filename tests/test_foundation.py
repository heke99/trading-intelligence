"""Offline regression tests with invented data. No provider credentials or network."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from trading_intelligence import AssetKind, DataOrigin, Entity, Instrument, Listing, Use, EvidenceStore
from trading_intelligence.cli import demo
from trading_intelligence.contracts import (
    AmbiguousIdentifier, ContractError, EvidenceIntegrityError, RecordConflict,
    UnknownIdentifier, UseNotAllowed, utc,
)


T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
T1 = T0 + timedelta(days=1)
T2 = T0 + timedelta(days=2)
T3 = T0 + timedelta(days=3)


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.store = EvidenceStore(":memory:")
        self.addCleanup(self.store.close)
        self.store.register_source("fixture", DataOrigin.SYNTHETIC)
        self.store.set_permissions("fixture", known_at=T0, uses={Use.STORAGE, Use.RESEARCH})
        self.store.register_entity(Entity("issuer", "Invented issuer"))
        self.store.register_instrument(Instrument("common", "issuer", AssetKind.EQUITY, "common", "USD"))
        self.store.register_listing(Listing("nasdaq", "common", "XNAS", "USD"))
        self.store.register_listing(Listing("nyse", "common", "XNYS", "USD"))

    def ingest(self, **changes):
        args = dict(source_id="fixture", record_id="record", revision_id="v1",
                    payload=b"original", published_at=T0, received_at=T1)
        args.update(changes)
        return self.store.ingest(**args)

    def mapping(self, evidence_id, **changes):
        args = dict(mapping_id="map", provider="fixture-provider", value="DEMO",
                    listing_id="nasdaq", valid_from=T0, known_at=T1, evidence_id=evidence_id)
        args.update(changes)
        self.store.put_identifier(**args)

    def resolve(self, **changes):
        args = dict(provider="fixture-provider", value="DEMO", effective_at=T1, as_of=T1)
        args.update(changes)
        return self.store.resolve_identifier(**args)

    def test_naive_timestamp_rejected(self):
        with self.assertRaises(ContractError):
            self.ingest(received_at=datetime(2026, 1, 2))

    def test_timezones_normalize_to_same_instant(self):
        offset = timezone(timedelta(hours=2))
        self.assertEqual(utc(T1), utc(T1.astimezone(offset)))

    def test_missing_identity_and_bad_venue_rejected(self):
        for operation in (lambda: Entity(" ", "Name"),
                          lambda: Listing("l", "common", "nasdaq", "USD"),
                          lambda: Listing("l", "common", "XNAS", "usd")):
            with self.subTest(operation=operation), self.assertRaises(ContractError):
                operation()

    def test_entities_instruments_and_listings_are_distinct(self):
        self.store.register_instrument(Instrument("preferred", "issuer", AssetKind.EQUITY, "preferred"))
        self.assertEqual(self.store.counts()["entities"], 1)
        self.assertEqual(self.store.counts()["instruments"], 2)
        self.assertEqual(self.store.counts()["listings"], 2)

    def test_identity_cannot_be_overwritten(self):
        with self.assertRaises(RecordConflict):
            self.store.register_entity(Entity("issuer", "Another name"))

    def test_instrument_requires_existing_entity(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.register_instrument(Instrument("bad", "unknown", AssetKind.EQUITY))

    def test_fund_and_index_cannot_receive_exchange_listing(self):
        for kind in (AssetKind.MUTUAL_FUND, AssetKind.INDEX):
            item = Instrument(kind.value, "issuer", kind)
            self.store.register_instrument(item)
            with self.subTest(kind=kind), self.assertRaises(ContractError):
                self.store.register_listing(Listing("invalid", item.instrument_id, "XNAS", "USD"))
        self.assertEqual(Instrument("f", "issuer", AssetKind.MUTUAL_FUND).execution_model,
                         "nav_subscription_redemption")

    def test_source_origin_cannot_change_to_verified(self):
        with self.assertRaises(RecordConflict):
            self.store.register_source("fixture", DataOrigin.BROKER)

    def test_storage_is_denied_without_permission(self):
        self.store.register_source("unlicensed", DataOrigin.PROVIDER)
        with self.assertRaises(UseNotAllowed):
            self.ingest(source_id="unlicensed")

    def test_permission_grant_does_not_backdate_itself(self):
        self.store.register_source("later", DataOrigin.PROVIDER)
        self.store.set_permissions("later", known_at=T2, uses={Use.STORAGE})
        with self.assertRaises(UseNotAllowed):
            self.ingest(source_id="later", received_at=T1)

    def test_training_is_denied_by_default(self):
        self.ingest()
        with self.assertRaises(UseNotAllowed):
            self.store.evidence_as_of("fixture", "record", as_of=T1, use=Use.TRAINING)

    def test_revocation_blocks_later_research(self):
        self.ingest()
        self.store.set_permissions("fixture", known_at=T2, uses={Use.STORAGE})
        self.assertIsNotNone(self.store.evidence_as_of("fixture", "record", as_of=T1))
        with self.assertRaises(UseNotAllowed):
            self.store.evidence_as_of("fixture", "record", as_of=T2)

    def test_permission_version_cannot_be_overwritten(self):
        with self.assertRaises(RecordConflict):
            self.store.set_permissions("fixture", known_at=T0, uses={Use.TRAINING})

    def test_old_publication_is_unknown_before_first_receipt(self):
        self.ingest(published_at=T0, received_at=T2)
        self.assertIsNone(self.store.evidence_as_of("fixture", "record", as_of=T1))
        self.assertEqual(self.store.evidence_as_of("fixture", "record", as_of=T2)["payload"], b"original")

    def test_publication_after_receipt_is_rejected(self):
        with self.assertRaises(ContractError):
            self.ingest(published_at=T2, received_at=T1)

    def test_only_nonempty_original_bytes_are_accepted(self):
        for payload in (b"", "text", {"value": 1}):
            with self.subTest(payload=payload), self.assertRaises(ContractError):
                self.ingest(payload=payload)

    def test_duplicate_receipts_preserve_one_version_and_two_observations(self):
        first = self.ingest()
        self.assertEqual(first, self.ingest())
        self.assertEqual(first, self.ingest(received_at=T2))
        counts = self.store.counts()
        self.assertEqual((counts["evidence_versions"], counts["raw_objects"], counts["observations"]), (1, 1, 2))

    def test_revision_cannot_change_or_backdate_first_receipt(self):
        self.ingest()
        for changes in (dict(payload=b"modified"), dict(received_at=T0), dict(published_at=T1)):
            with self.subTest(changes=changes), self.assertRaises(RecordConflict):
                self.ingest(**changes)

    def test_two_revisions_at_same_observation_time_are_rejected(self):
        self.ingest()
        with self.assertRaises(RecordConflict):
            self.ingest(revision_id="v2", payload=b"modified")
        self.assertEqual(self.store.counts()["raw_objects"], 1)

    def test_corrected_evidence_preserves_historical_view(self):
        original = self.ingest()
        correction = self.ingest(revision_id="v2", payload=b"corrected", received_at=T2, correction_of=original)
        before = self.store.evidence_as_of("fixture", "record", as_of=T1)
        after = self.store.evidence_as_of("fixture", "record", as_of=T2)
        self.assertEqual(before["payload"], b"original")
        self.assertEqual(after["evidence_id"], correction)
        self.assertEqual(after["correction_of"], original)
        self.assertEqual(after["origin"], "synthetic_fixture")

    def test_correction_requires_same_record_and_source(self):
        original = self.ingest()
        self.store.register_source("other", DataOrigin.SYNTHETIC)
        self.store.set_permissions("other", known_at=T0, uses={Use.STORAGE})
        for changes in (dict(record_id="other"), dict(source_id="other"), dict(correction_of="missing")):
            args = dict(revision_id="v2", received_at=T2, correction_of=original)
            args.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ContractError):
                self.ingest(**args)

    def test_raw_payload_corruption_is_detected_on_read(self):
        self.ingest()
        with self.store.db:
            self.store.db.execute("UPDATE raw_objects SET payload=?", (b"tampered",))
        with self.assertRaises(EvidenceIntegrityError):
            self.store.evidence_as_of("fixture", "record", as_of=T1)

    def test_unknown_or_fuzzy_symbol_is_not_resolved(self):
        self.mapping(self.ingest())
        for value in ("demo", "DEM", " DEMO", "DEMO' OR 1=1 --"):
            with self.subTest(value=value), self.assertRaises(UnknownIdentifier):
                self.resolve(value=value)

    def test_identifier_cannot_use_future_or_missing_evidence(self):
        evidence = self.ingest()
        for changes in (dict(known_at=T0), dict(evidence_id="missing")):
            args = dict(evidence_id=evidence)
            args.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ContractError):
                self.mapping(**args)

    def test_identifier_requires_research_permission(self):
        evidence = self.ingest()
        self.store.set_permissions("fixture", known_at=T2, uses={Use.STORAGE})
        with self.assertRaises(UseNotAllowed):
            self.mapping(evidence, known_at=T2)

    def test_identifier_ambiguity_blocks_resolution(self):
        evidence = self.ingest()
        self.mapping(evidence)
        self.mapping(evidence, mapping_id="second", listing_id="nyse")
        with self.assertRaises(AmbiguousIdentifier):
            self.resolve()

    def test_identifier_validity_is_half_open(self):
        self.mapping(self.ingest(), valid_to=T2)
        self.assertEqual(self.resolve(effective_at=T1), "nasdaq")
        with self.assertRaises(UnknownIdentifier):
            self.resolve(effective_at=T2)
        with self.assertRaises(ContractError):
            self.mapping(self.ingest(), mapping_id="empty", valid_to=T0)

    def test_mapping_correction_changes_knowledge_without_rewriting_past(self):
        old = self.ingest()
        new = self.ingest(revision_id="v2", received_at=T2, payload=b"new mapping", correction_of=old)
        self.mapping(old)
        self.mapping(new, known_at=T2, listing_id="nyse")
        self.assertEqual(self.resolve(as_of=T1), "nasdaq")
        self.assertEqual(self.resolve(as_of=T2), "nyse")

    def test_changed_symbol_replaces_old_symbol_only_after_known_time(self):
        evidence = self.ingest()
        self.mapping(evidence)
        self.mapping(evidence, known_at=T2, value="RENAMED")
        self.assertEqual(self.resolve(as_of=T1), "nasdaq")
        with self.assertRaises(UnknownIdentifier):
            self.resolve(as_of=T2)
        self.assertEqual(self.resolve(value="RENAMED", as_of=T2), "nasdaq")

    def test_mapping_cannot_be_silently_overwritten(self):
        evidence = self.ingest()
        self.mapping(evidence)
        with self.assertRaises(RecordConflict):
            self.mapping(evidence, listing_id="nyse")

    def test_identifier_resolution_respects_revocation(self):
        self.mapping(self.ingest())
        self.store.set_permissions("fixture", known_at=T2, uses=set())
        with self.assertRaises(UseNotAllowed):
            self.resolve(as_of=T2)


class OfflineDemoTests(unittest.TestCase):
    def test_demo_reopens_persistent_database_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = demo(Path(temporary))
            second = demo(Path(temporary))
            self.assertEqual(first, second)
            self.assertEqual(first["before_correction"], "demo-old-listing")
            self.assertEqual(first["after_correction"], "demo-new-listing")
            self.assertEqual(first["counts"]["evidence_versions"], 2)
            self.assertFalse(first["training_implemented"])
            self.assertFalse(first["live_trading"])


if __name__ == "__main__":
    unittest.main()
