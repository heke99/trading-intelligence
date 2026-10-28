"""Synthetic point-in-time facility context, identity and integrity checks."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from trading_intelligence.contracts import (
    AssetKind, ContractError, DataOrigin, Entity, EvidenceIntegrityError,
    Instrument, Listing, RecordConflict, Use, UseNotAllowed,
)
from trading_intelligence.event_context import EventContextStore, haversine_km
from trading_intelligence.event_sources import EventCapture, endpoint


T = datetime(2026, 1, 1, tzinfo=timezone.utc)


def millis(at):
    return int(at.timestamp() * 1000)


class EventContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'events.sqlite3'
        self.now = T
        self.store = EventContextStore(self.path, clock=lambda: self.now)
        self.addCleanup(lambda: self.store.close())
        for source in ('events', 'facility'):
            self.store.register_source(source, DataOrigin.SYNTHETIC)
            self.store.set_permissions(source, known_at=T, uses={Use.STORAGE, Use.RESEARCH})
        for identity in ('a', 'b'):
            self.store.register_entity(Entity(identity, f'Invented {identity}'))
            self.store.register_instrument(Instrument(f'{identity}-equity', identity, AssetKind.EQUITY))
            self.store.register_listing(Listing(f'{identity}-listing', f'{identity}-equity', 'XNAS', 'USD'))
        self.evidence_id = self.evidence('facility-evidence', T)

    def evidence(self, identity, at):
        return self.store.ingest(source_id='facility', record_id=identity, revision_id='1',
                                 payload=identity.encode(), published_at=at, received_at=at)

    def facility(self, **changes):
        values = dict(assertion_id='fa-1', facility_id='factory', entity_id='a',
                      latitude=0, longitude=0.1, evidence_id=self.evidence_id,
                      valid_from=T, known_at=T, relationship='operator', listing_id='a-listing')
        values.update(changes)
        return self.store.put_facility(**values)

    def event(self):
        self.now = T + timedelta(days=1)
        occurred = self.now - timedelta(hours=1)
        payload = json.dumps(dict(type='FeatureCollection',
            metadata=dict(generated=millis(self.now), count=1, status=200),
            features=[dict(type='Feature', id='synthetic-earthquake',
                properties=dict(time=millis(occurred), updated=millis(occurred),
                    type='earthquake', mag=6.5, tsunami=1),
                geometry=dict(type='Point', coordinates=[0, 0, 10]))])).encode()
        capture = EventCapture(payload, self.now, endpoint())
        return self.store.stage(source_id='events', import_id='one', capture=capture)

    def context(self, **changes):
        values = dict(source_id='events', event_id='synthetic-earthquake',
                      as_of=self.now, radius_km=50)
        values.update(changes)
        return self.store.context(**values)

    def test_near_facility_is_investigation_without_damage_or_trade_inference(self):
        self.facility()
        self.event()
        result = self.context()
        self.assertEqual(result['action'], 'investigate')
        self.assertEqual(len(result['candidates']), 1)
        candidate = result['candidates'][0]
        self.assertEqual(candidate['listing_id'], 'a-listing')
        self.assertAlmostEqual(candidate['distance_km'], 11.119508, places=5)
        self.assertFalse(candidate['damage_confirmed'])
        self.assertIsNone(candidate['economic_exposure_share'])
        self.assertEqual(candidate['current_operating_status'], 'unknown')
        self.assertFalse(result['radius_is_damage_estimate'])
        self.assertFalse(result['market_impact_assessed'])
        self.assertEqual(result['orders_sent'], 0)
        self.assertFalse(result['live_trading'])
        self.assertIsNone(result['event']['tsunami_confirmed'])

    def test_far_facility_only_observes(self):
        self.facility(longitude=40)
        self.event()
        self.assertEqual(self.context()['action'], 'observe')
        self.assertEqual(self.context()['candidates'], [])

    def test_conflicting_revision_surfaces_critical_investigation(self):
        self.event()
        historical = self.now
        row = self.store.db.execute("SELECT r.payload FROM event_captures c JOIN raw_objects r ON r.sha256=c.raw_sha WHERE c.import_id='one'").fetchone()
        body = json.loads(row['payload'])
        body['features'][0]['properties']['mag'] = 7.1
        self.now += timedelta(hours=1)
        capture = EventCapture(json.dumps(body).encode(), self.now, endpoint())
        self.store.stage(source_id='events', import_id='conflict', capture=capture)
        result = self.context()
        self.assertEqual(result['action'], 'investigate')
        self.assertEqual(result['candidates'], [])
        self.assertTrue(result['event_ambiguity'])
        self.assertTrue(result['critical_uncertainties'])
        self.assertTrue(result['event']['revision_conflicts'])
        self.assertFalse(self.context(as_of=historical)['event_ambiguity'])

    def test_radius_is_caller_declared_investigation_area(self):
        self.facility()
        self.event()
        self.assertEqual(self.context(radius_km=5)['action'], 'observe')
        self.assertEqual(self.context(radius_km=20)['action'], 'investigate')
        for invalid in (0, -1, True, float('nan'), float('inf'), '50', 10 ** 1000):
            with self.subTest(invalid=invalid), self.assertRaises(ContractError):
                self.context(radius_km=invalid)

    def test_historical_declared_knowledge_does_not_backdate_registration(self):
        self.event()
        historical = self.now
        self.now += timedelta(days=1)
        self.facility(known_at=T)
        self.assertEqual(self.context(as_of=historical)['candidates'], [])
        self.assertEqual(self.context()['action'], 'investigate')

    def test_future_or_expired_economic_validity_is_excluded(self):
        for which, changes in (
                ('future', dict(valid_from=T + timedelta(days=2))),
                ('expired', dict(valid_to=T + timedelta(hours=12)))):
            self.facility(assertion_id=which, facility_id=which, **changes)
        self.event()
        self.assertEqual(self.context()['candidates'], [])

    def test_wrong_entity_listing_cannot_be_linked(self):
        with self.assertRaises(ContractError):
            self.facility(listing_id='b-listing')
        with self.assertRaises(ContractError):
            self.facility(entity_id='missing', listing_id=None)

    def test_optional_listing_stays_unknown(self):
        self.facility(listing_id=None)
        self.event()
        self.assertIsNone(self.context()['candidates'][0]['listing_id'])

    def test_owner_and_operator_relations_remain_distinct(self):
        self.facility()
        self.facility(assertion_id='owner', entity_id='b', relationship='owner', listing_id='b-listing')
        self.event()
        result = self.context()
        self.assertEqual({x['relationship'] for x in result['candidates']}, {'operator', 'owner'})
        self.assertEqual({x['entity_id'] for x in result['candidates']}, {'a', 'b'})

    def test_current_revocation_blocks_historical_context(self):
        self.facility()
        self.event()
        historical = self.now
        self.now += timedelta(days=1)
        self.store.set_permissions('facility', known_at=self.now, uses={Use.STORAGE})
        with self.assertRaises(UseNotAllowed):
            self.context(as_of=historical)

    def test_historical_revocation_is_not_bypassed_by_current_regrant(self):
        self.facility()
        self.event()
        historical = self.now
        self.store.set_permissions('facility', known_at=historical, uses={Use.STORAGE})
        self.now += timedelta(days=1)
        self.store.set_permissions('facility', known_at=self.now, uses={Use.STORAGE, Use.RESEARCH})
        with self.assertRaises(UseNotAllowed):
            self.context(as_of=historical)

    def test_backing_raw_corruption_blocks_context(self):
        self.facility()
        self.event()
        sha = hashlib.sha256(b'facility-evidence').hexdigest()
        with self.store.db:
            self.store.db.execute('UPDATE raw_objects SET payload=? WHERE sha256=?', (b'bad', sha))
        with self.assertRaises(EvidenceIntegrityError):
            self.context()

    def test_facility_manifest_corruption_blocks_context(self):
        self.facility()
        self.event()
        with self.store.db:
            self.store.db.execute("UPDATE event_facility_assertions SET body_json='{}'")
        with self.assertRaises(EvidenceIntegrityError):
            self.context()

    def test_facility_retry_immutable_across_restart(self):
        original = self.facility()
        self.store.close()
        self.store = EventContextStore(self.path, clock=lambda: self.now)
        self.assertEqual(self.facility(), original)
        with self.assertRaises(RecordConflict):
            self.facility(longitude=1)

    def test_replacement_is_known_only_after_actual_registration(self):
        original = self.facility()
        self.event()
        historical = self.now
        self.now += timedelta(days=1)
        second = self.evidence('second', self.now)
        self.facility(assertion_id='fa-2', longitude=40, evidence_id=second,
                      known_at=self.now, supersedes=original['assertion_id'])
        self.assertEqual(self.context(as_of=historical)['candidates'][0]['assertion_id'], 'fa-1')
        self.assertEqual(self.context()['candidates'], [])

    def test_expired_replacement_does_not_resurrect_older_assertion(self):
        self.facility()
        self.event()
        self.now += timedelta(days=1)
        self.facility(assertion_id='fa-2', valid_to=T + timedelta(hours=12),
                      known_at=self.now, supersedes='fa-1')
        self.assertEqual(self.context()['candidates'], [])

    def test_replacement_needs_latest_parent_and_later_availability(self):
        self.facility()
        with self.assertRaises(ContractError):
            self.facility(assertion_id='same-time', supersedes='fa-1')
        self.now += timedelta(days=1)
        with self.assertRaises(ContractError):
            self.facility(assertion_id='unlinked', supersedes=None)
        with self.assertRaises(ContractError):
            self.facility(assertion_id='wrong-parent', supersedes='missing')

    def test_missing_future_evidence_and_invalid_inputs_are_rejected(self):
        with self.assertRaises(ContractError):
            self.facility(evidence_id='missing')
        for changes in (dict(latitude=float('nan')), dict(longitude=181),
                        dict(latitude=True), dict(latitude=10 ** 1000),
                        dict(relationship='guessed'), dict(relationship=[]),
                        dict(valid_to=T), dict(known_at=T + timedelta(days=1)),
                        dict(valid_from=datetime(2026, 1, 1))):
            with self.subTest(changes=changes), self.assertRaises(ContractError):
                self.facility(**changes)

    def test_missing_event_is_explicitly_unavailable(self):
        result = self.context()
        self.assertEqual(result['action'], 'unavailable')
        self.assertIsNone(result['event'])

    def test_evidence_age_is_reported_without_claiming_fresh_operations(self):
        self.facility()
        self.event()
        candidate = self.context()['candidates'][0]
        self.assertEqual(candidate['evidence_age_seconds'], 86400)
        self.assertFalse(candidate['freshness_assessed'])

    def test_distance_handles_date_line_and_poles(self):
        self.assertAlmostEqual(haversine_km(0, 179.9, 0, -179.9), 22.239016, places=5)
        self.assertAlmostEqual(haversine_km(90, -120, 90, 120), 0, places=7)


if __name__ == '__main__':
    unittest.main()
