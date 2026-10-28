"""Synthetic event revisions, operational knowledge and immutable lineage."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from trading_intelligence.contracts import (
    ContractError, DataOrigin, EvidenceIntegrityError, RecordConflict, Use, UseNotAllowed,
)
from trading_intelligence.event_sources import EventCapture, endpoint
from trading_intelligence.event_store import EventStore


T = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)


def ms(at):
    return int(at.timestamp() * 1000)


def event(identity='invented-earthquake', *, updated=None, occurred=None, mag=5):
    return dict(type='Feature', id=identity,
                properties=dict(type='earthquake', time=ms(occurred or T-timedelta(minutes=5)),
                                updated=ms(updated or T-timedelta(minutes=1)), mag=mag,
                                magType='mw', place='Invented region', title='Invented event',
                                status='automatic', tsunami=1),
                geometry=dict(type='Point', coordinates=[24.5, 61.2, 8]))


def capture(*events, received=T, generated=None, transport='supplied_bytes'):
    rows = list(events) if events else [event()]
    body = dict(type='FeatureCollection', metadata=dict(count=len(rows), status=200,
                generated=ms(generated or received)), features=rows)
    return EventCapture(json.dumps(body).encode(), received, endpoint(), transport=transport)


class EventStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'events.sqlite3'
        self.now = T + timedelta(minutes=1)
        self.store = EventStore(self.path, clock=lambda: self.now)
        self.addCleanup(self.store.close)
        self.store.register_source('events', DataOrigin.SYNTHETIC)
        self.store.set_permissions('events', known_at=T-timedelta(days=1),
                                   uses={Use.STORAGE, Use.RESEARCH})

    def stage(self, cap=None, import_id='first', **kwargs):
        return self.store.stage(source_id='events', import_id=import_id,
                                capture=cap or capture(), **kwargs)

    def latest(self, at=None):
        return self.store.event_as_of('events', 'invented-earthquake', as_of=at or self.now)

    def test_unknown_publication_is_preserved_without_old_evidence_contract(self):
        report = self.stage()
        value = self.latest()
        self.assertIsNone(value['published_at'])
        self.assertIsNone(value['tsunami_confirmed'])
        self.assertEqual(value['tsunami_flag'], 1)
        self.assertEqual(value['origin'], DataOrigin.SYNTHETIC.value)
        self.assertEqual(value['raw_sha'], report['raw_sha'])
        self.assertEqual(self.store.counts()['evidence_versions'], 0)
        self.assertEqual(self.store.counts()['raw_objects'], 1)
        self.assertFalse(report['training_ready'])
        self.assertFalse(report['live_trading'])
        self.assertEqual(report['orders_sent'], 0)

    def test_operational_registration_cannot_be_backdated_to_receipt_or_processing(self):
        report = self.stage(processed_at=T)
        self.assertEqual(report['received_at'], '2026-01-10T12:00:00.000000Z')
        self.assertEqual(report['declared_processed_at'], report['received_at'])
        self.assertEqual(report['processed_at'], report['available_at'])
        self.assertEqual(report['available_at'], '2026-01-10T12:01:00.000000Z')
        self.assertIsNone(self.latest(T))
        self.assertIsNone(self.store.capture_as_of('events', 'first', as_of=T))
        self.assertIsNotNone(self.latest())

    def test_slow_normalization_is_unavailable_until_actual_completion(self):
        from trading_intelligence.event_sources import normalize_capture
        started = self.now

        def delayed(cap):
            normalized = normalize_capture(cap)
            self.now += timedelta(minutes=1)
            return normalized

        with patch('trading_intelligence.event_sources.normalize_capture', side_effect=delayed):
            report = self.stage(processed_at=T)
        halfway = started + timedelta(seconds=30)
        self.assertIsNone(self.latest(halfway))
        self.assertIsNone(self.store.capture_as_of('events', 'first', as_of=halfway))
        self.assertEqual(report['available_at'], '2026-01-10T12:02:00.000000Z')
        self.assertEqual(report['processed_at'], report['available_at'])
        self.assertEqual(self.latest()['available_at'], report['available_at'])

    def test_same_provider_update_cannot_lexically_order_distinct_revisions(self):
        from trading_intelligence.event_sources import normalize_capture
        self.stage()
        before = self.now
        self.now += timedelta(minutes=2)
        cap = capture(event(mag=8), received=T+timedelta(minutes=2))
        normalized = normalize_capture(cap)
        normalized['observations'][0]['revision_id'] = 'other-native-revision'
        with patch('trading_intelligence.event_sources.normalize_capture', return_value=normalized):
            report = self.stage(cap, import_id='tied-update')
        self.assertEqual(report['observations'], [])
        self.assertEqual(report['quarantined'][0]['reason'], 'revision_order_ambiguous')
        self.assertEqual(self.latest()['magnitude'], 5)
        self.assertTrue(self.latest()['unresolved_revision_conflict'])
        self.assertFalse(self.latest(before)['unresolved_revision_conflict'])
        self.assertEqual(self.latest()['revision_conflicts'][0]['observed_revision_id'], 'other-native-revision')
        self.now += timedelta(minutes=2)
        self.stage(capture(event(updated=T+timedelta(minutes=3), mag=6),
                           received=T+timedelta(minutes=4)), import_id='later-update')
        self.assertFalse(self.latest()['unresolved_revision_conflict'])

    def test_multi_event_query_verifies_shared_capture_once_per_read(self):
        rows = [event(f'invented-{index}') for index in range(50)]
        self.stage(capture(*rows))
        with patch.object(self.store, '_source_origin', wraps=self.store._source_origin) as origin:
            self.assertEqual(len(self.store.events_as_of('events', as_of=self.now)), 50)
            self.assertEqual(origin.call_count, 1)
        # Cache lifetime is one read: a later corruption must still be detected.
        with self.store.db:
            self.store.db.execute("UPDATE raw_objects SET payload=?", (b'changed',))
        with self.assertRaises(EvidenceIntegrityError):
            self.store.events_as_of('events', as_of=self.now)

    def test_targeted_query_does_not_verify_every_event_or_obsolete_revision(self):
        self.stage()
        self.now += timedelta(minutes=2)
        self.stage(capture(event(updated=T+timedelta(minutes=1)), event('another'),
                           received=T+timedelta(minutes=2)), import_id='newest')
        with patch.object(self.store, 'events_as_of', side_effect=AssertionError('untargeted read')):
            with patch.object(self.store, '_verify_version', wraps=self.store._verify_version) as verify:
                self.assertIsNotNone(self.latest())
                self.assertEqual(verify.call_count, 1)

    def test_import_retry_and_restart_keep_exact_first_result(self):
        first = self.stage()
        self.now += timedelta(minutes=2)
        self.assertEqual(first, self.stage(processed_at=self.now))
        with EventStore(self.path, clock=lambda: self.now) as reopened:
            self.assertEqual(first, reopened.capture_as_of('events', 'first', as_of=self.now))
            self.assertEqual(len(reopened.events_as_of('events', as_of=self.now)), 1)

    def test_changed_import_payload_or_receipt_conflicts(self):
        self.stage()
        for cap in (capture(event(mag=6)), capture(received=T-timedelta(seconds=1))):
            with self.subTest(cap=cap), self.assertRaises(RecordConflict):
                self.stage(cap)

    def test_repeated_observation_new_capture_keeps_version_and_first_availability(self):
        self.stage()
        first = self.latest()
        self.now += timedelta(minutes=2)
        report = self.stage(capture(received=T+timedelta(minutes=2)), import_id='second')
        self.assertEqual(self.latest(), first)
        self.assertEqual(report['observations'][0]['first_available_at'], first['available_at'])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM event_versions').fetchone()[0], 1)

    def test_revision_changes_only_future_knowledge_snapshots(self):
        self.stage()
        before = self.now
        original = self.latest()
        self.now += timedelta(minutes=2)
        self.stage(capture(event(updated=T+timedelta(minutes=1), mag=6),
                           received=T+timedelta(minutes=2)), import_id='revised')
        self.assertEqual(self.latest(before), original)
        self.assertEqual(self.latest()['magnitude'], 6)
        self.assertNotEqual(self.latest()['event_version_id'], original['event_version_id'])

    def test_late_old_provider_revision_does_not_regress_latest_state(self):
        self.stage(capture(event(updated=T-timedelta(seconds=1), mag=6)))
        self.now += timedelta(minutes=2)
        self.stage(capture(event(updated=T-timedelta(minutes=2), mag=4),
                           received=T+timedelta(minutes=2)), import_id='late-old')
        self.assertEqual(self.latest()['magnitude'], 6)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM event_versions').fetchone()[0], 2)

    def test_same_native_revision_changed_content_is_quarantined_durably(self):
        self.stage()
        original_cutoff = self.now
        self.now += timedelta(minutes=2)
        report = self.stage(capture(event(mag=8), received=T+timedelta(minutes=2)), import_id='conflict')
        self.assertEqual(report['state'], 'quarantined')
        self.assertEqual(report['observations'], [])
        self.assertEqual(report['quarantined'][0]['reason'], 'revision_content_conflict')
        self.assertEqual(self.latest()['magnitude'], 5)
        self.assertFalse(self.latest(original_cutoff)['unresolved_revision_conflict'])
        self.assertTrue(self.latest()['unresolved_revision_conflict'])
        conflict = self.latest()['revision_conflicts'][0]
        self.assertEqual(conflict['capture_id'], report['capture_id'])
        self.assertEqual(conflict['raw_sha'], report['raw_sha'])
        self.assertEqual(report, self.store.capture_as_of('events', 'conflict', as_of=self.now))

    def test_newer_native_revision_excludes_older_revision_ambiguity(self):
        self.stage()
        self.now += timedelta(minutes=2)
        self.stage(capture(event(mag=8), received=T+timedelta(minutes=2)), import_id='conflict')
        conflict_cutoff = self.now
        self.now += timedelta(minutes=2)
        self.stage(capture(event(updated=T+timedelta(minutes=3), mag=6),
                           received=T+timedelta(minutes=4)), import_id='new-version')
        self.assertTrue(self.latest(conflict_cutoff)['unresolved_revision_conflict'])
        self.assertFalse(self.latest()['unresolved_revision_conflict'])
        self.assertEqual(self.latest()['revision_conflicts'], [])

    def test_ambiguous_feed_rows_flag_previous_event_until_new_valid_version(self):
        self.stage()
        self.now += timedelta(minutes=2)
        report = self.stage(capture(event(), event(mag=8), received=T+timedelta(minutes=2)),
                            import_id='ambiguous-feed')
        self.assertEqual(report['state'], 'quarantined')
        self.assertTrue(self.latest()['unresolved_revision_conflict'])
        self.assertTrue(all(row['revision_id'] is None for row in self.latest()['revision_conflicts']))

    def test_deleted_conflict_index_does_not_hide_original_capture_ambiguity(self):
        self.stage()
        self.now += timedelta(minutes=2)
        self.stage(capture(event(mag=8), received=T+timedelta(minutes=2)), import_id='conflict')
        with self.store.db:
            self.store.db.execute('DELETE FROM event_revision_conflicts')
        with self.assertRaises(EvidenceIntegrityError):
            self.latest()

    def test_corrupted_conflict_index_is_rejected(self):
        self.stage()
        self.now += timedelta(minutes=2)
        self.stage(capture(event(mag=8), received=T+timedelta(minutes=2)), import_id='conflict')
        with self.store.db:
            self.store.db.execute("UPDATE event_revision_conflicts SET revision_id='other'")
        with self.assertRaises(EvidenceIntegrityError):
            self.latest()

    def test_corrupted_conflict_capture_cannot_hide_event_from_targeted_lookup(self):
        self.stage()
        self.now += timedelta(minutes=2)
        self.stage(capture(event(mag=8), received=T+timedelta(minutes=2)), import_id='conflict')
        with self.store.db:
            self.store.db.execute("UPDATE event_captures SET result_json='{}' WHERE import_id='conflict'")
        with self.assertRaises(EvidenceIntegrityError):
            self.latest()

    def test_native_ids_are_scoped_by_source(self):
        self.stage()
        self.store.register_source('other', DataOrigin.SYNTHETIC)
        self.store.set_permissions('other', known_at=T-timedelta(days=1), uses={Use.STORAGE,Use.RESEARCH})
        self.store.stage(source_id='other', import_id='first', capture=capture(event(mag=8)))
        other = self.store.event_as_of('other', 'invented-earthquake', as_of=self.now)
        self.assertEqual(other['magnitude'], 8)
        self.assertNotEqual(other['event_version_id'], self.latest()['event_version_id'])

    def test_malformed_originals_survive_quarantine(self):
        report = self.stage(EventCapture(b'{bad json', T, endpoint()))
        self.assertEqual(report['state'], 'quarantined')
        self.assertEqual(len(report['quarantined']), 1)
        self.assertEqual(self.store.counts()['raw_objects'], 1)
        self.assertEqual(self.store.events_as_of('events', as_of=self.now), [])

    def test_future_generation_and_future_rows_do_not_enter_query(self):
        report = self.stage(capture(generated=T+timedelta(seconds=1)))
        self.assertEqual(report['quarantined'][0]['reason'], 'feed_generated_after_receipt')
        future = event(occurred=T+timedelta(seconds=1), updated=T+timedelta(seconds=2))
        report = self.stage(capture(future), import_id='future-row')
        self.assertEqual(report['state'], 'quarantined')
        self.assertEqual(self.store.events_as_of('events', as_of=self.now), [])

    def test_mixed_invalid_rows_preserve_valid_candidates(self):
        bad = event('bad'); bad['geometry']['coordinates'][0] = 999
        report = self.stage(capture(event(), bad))
        self.assertEqual(report['state'], 'partial')
        self.assertEqual(len(report['observations']), 1)
        self.assertEqual(len(report['quarantined']), 1)
        self.assertEqual(len(self.store.events_as_of('events', as_of=self.now)), 1)

    def test_current_research_revocation_blocks_old_cutoff(self):
        self.stage(); previous = self.now
        self.now += timedelta(minutes=2)
        self.store.set_permissions('events', known_at=self.now, uses={Use.STORAGE})
        with self.assertRaises(UseNotAllowed):
            self.latest(previous)
        with self.assertRaises(UseNotAllowed):
            self.store.capture_as_of('events', 'first', as_of=previous)

    def test_permission_at_historical_cutoff_is_still_required(self):
        self.store.register_source('later', DataOrigin.SYNTHETIC)
        self.store.set_permissions('later', known_at=self.now, uses={Use.STORAGE,Use.RESEARCH})
        with self.assertRaises(UseNotAllowed):
            self.store.events_as_of('later', as_of=T)

    def test_missing_rights_block_before_raw_storage(self):
        self.store.register_source('denied', DataOrigin.SYNTHETIC)
        with self.assertRaises(UseNotAllowed):
            self.store.stage(source_id='denied', import_id='first', capture=capture())
        self.assertEqual(self.store.counts()['raw_objects'], 0)

    def test_future_and_inconsistent_clocks_rejected(self):
        with self.assertRaises(ContractError):
            self.stage(processed_at=self.now+timedelta(seconds=1))
        with self.assertRaises(ContractError):
            self.stage(processed_at=T-timedelta(seconds=1))
        with self.assertRaises(ContractError):
            self.latest(self.now+timedelta(seconds=1))
        with self.assertRaises(ContractError):
            self.store.events_as_of('events', as_of=T, current_at=T)

    def test_caller_transaction_is_not_committed(self):
        self.store.db.execute('BEGIN')
        with self.assertRaises(ContractError):
            self.stage()
        self.assertTrue(self.store.db.in_transaction)
        self.store.db.rollback()

    def test_corrupted_raw_bytes_block_query(self):
        report = self.stage()
        with self.store.db:
            self.store.db.execute('UPDATE raw_objects SET payload=? WHERE sha256=?', (b'corrupt',report['raw_sha']))
        with self.assertRaises(EvidenceIntegrityError):
            self.latest()

    def test_corrupted_capture_manifest_blocks_query(self):
        self.stage()
        with self.store.db:
            self.store.db.execute("UPDATE event_captures SET result_json='{}'")
        with self.assertRaises(EvidenceIntegrityError):
            self.latest()

    def test_corrupted_version_blocks_query(self):
        self.stage()
        with self.store.db:
            self.store.db.execute("UPDATE event_versions SET provider_updated_at='2026-01-01'")
        with self.assertRaises(EvidenceIntegrityError):
            self.latest()

    def test_corrupted_quarantine_blocks_readback(self):
        self.stage(EventCapture(b'{bad', T, endpoint()))
        with self.store.db:
            self.store.db.execute('DELETE FROM event_capture_quarantine')
        with self.assertRaises(EvidenceIntegrityError):
            self.store.capture_as_of('events', 'first', as_of=self.now)


if __name__ == '__main__':
    unittest.main()
