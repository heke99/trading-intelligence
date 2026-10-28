"""Event collection, continuous context and CLI proofs using invented observations."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from trading_intelligence.contracts import ContractError, DataOrigin, RecordConflict, Use, UseNotAllowed
from trading_intelligence.event_context import EventContextStore
from trading_intelligence.event_demo import _payload, event_demo
from trading_intelligence.event_sources import EventCapture, EventReadError, USGS_FEEDS
from trading_intelligence.event_sync import sync_events, watch_events

T = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)


def capture(*, feed='all_hour', transport='declared_http_get', payload=None):
    return EventCapture(payload if payload is not None else _payload(T, longitude=139,
        latitude=35, magnitude=6.2, status='automatic', tsunami=1), T,
        USGS_FEEDS[feed], transport=transport)


class Reader:
    def __init__(self, values):
        self.values = iter(values)
        self.calls = 0

    def read(self):
        self.calls += 1
        value = next(self.values)
        if isinstance(value, Exception):
            raise value
        return value


class EventPipelineTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)/'evidence.sqlite3'
        self.now = T+timedelta(seconds=30)
        self.store = EventContextStore(self.path, clock=lambda: self.now)
        self.addCleanup(self.store.close)
        self.store.register_source('events', DataOrigin.PROVIDER)
        self.store.set_permissions('events', known_at=T-timedelta(days=1),
                                   uses={Use.STORAGE, Use.RESEARCH})

    def sync(self, reader, **changes):
        args = dict(source_id='events', import_id='capture', feed='all_hour', reader=reader,
                    clock=lambda: self.now)
        args.update(changes)
        return sync_events(self.store, **args)

    def watch(self, reader, **changes):
        args = dict(source_id='events', feed='all_hour', reader=reader, radius_km=100,
                    iterations=2, poll_seconds=60, clock=lambda: self.now,
                    sleeper=lambda _: None, run_id='synthetic-run')
        args.update(changes)
        return list(watch_events(self.store, **args))

    def test_retry_returns_original_without_network_and_changed_feed_conflicts(self):
        reader = Reader([capture()])
        first = self.sync(reader)
        self.assertEqual(first, self.sync(reader))
        self.assertEqual(reader.calls, 1)
        with self.assertRaises(RecordConflict):
            self.sync(reader, feed='all_day')
        self.assertEqual(reader.calls, 1)

    def test_preflight_requires_explicit_research_and_provider_origin(self):
        reader = Reader([])
        self.store.set_permissions('events', known_at=self.now, uses={Use.STORAGE})
        with self.assertRaises(UseNotAllowed):
            self.sync(reader)
        self.store.register_source('synthetic', DataOrigin.SYNTHETIC)
        self.store.set_permissions('synthetic', known_at=T-timedelta(days=1),
                                   uses={Use.STORAGE, Use.RESEARCH})
        with self.assertRaises(ContractError):
            self.sync(reader, source_id='synthetic')
        self.assertEqual(reader.calls, 0)

    def test_wrong_endpoint_or_supplied_capture_cannot_claim_a_network_sync(self):
        for value in (capture(feed='all_day'), capture(transport='supplied_bytes')):
            with self.subTest(value=value), self.assertRaises(ContractError):
                self.sync(Reader([value]))
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM event_captures').fetchone()[0], 0)

    def test_watch_deduplicates_versions_and_only_waits_between_polls(self):
        sleeps = []
        reports = self.watch(Reader([capture(), capture()]), sleeper=sleeps.append)
        self.assertEqual(sleeps, [60])
        self.assertEqual([r['status'] for r in reports], ['captured', 'captured'])
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM event_versions').fetchone()[0], 1)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM event_captures').fetchone()[0], 2)
        for report in reports:
            self.assertEqual(len(report['contexts']), 1)
            self.assertEqual(report['contexts'][0]['action'], 'observe')
            self.assertFalse(report['live_trading'])
            self.assertEqual(report['orders_sent'], 0)

    def test_watch_recovers_after_network_failure_without_provider_message_leak(self):
        reports = self.watch(Reader([EventReadError('untrusted provider text'), capture()]))
        self.assertEqual(reports[0]['status'], 'collection_or_context_unavailable')
        self.assertEqual(reports[0]['contexts'], [])
        self.assertNotIn('untrusted provider text', json.dumps(reports))
        self.assertEqual(reports[1]['status'], 'captured')

    def test_quarantined_feed_does_not_republish_cached_context_as_fresh(self):
        reports = self.watch(Reader([capture(), capture(payload=b'broken json')]))
        self.assertEqual(reports[1]['status'], 'captured_with_quarantine')
        self.assertEqual(reports[1]['contexts'], [])
        self.assertEqual(reports[1]['observations'], 0)
        self.assertGreater(reports[1]['quarantined'], 0)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM event_versions').fetchone()[0], 1)

    def test_invalid_loop_arguments_fail_before_any_read(self):
        reader = Reader([])
        for changes in ({'iterations': 0}, {'iterations': True}, {'poll_seconds': 0},
                        {'poll_seconds': float('nan')}, {'radius_km': float('inf')},
                        {'feed': []}):
            with self.subTest(changes=changes), self.assertRaises(ContractError):
                self.watch(reader, **changes)
        self.assertEqual(reader.calls, 0)

    def test_watch_reports_known_revision_conflict_as_explicit_ambiguity(self):
        original = capture()
        changed = capture(payload=_payload(T, longitude=139, latitude=35,
                          magnitude=8.1, status='automatic', tsunami=1))
        reports = self.watch(Reader([original, changed]))
        second = reports[1]
        self.assertEqual(second['status'], 'captured_with_quarantine')
        self.assertEqual(second['fresh_event_ids'], [])
        self.assertEqual(second['ambiguity_event_ids'], ['invented-earthquake'])
        self.assertEqual(len(second['contexts']), 1)
        self.assertTrue(second['contexts'][0]['event_ambiguity'])
        self.assertEqual(second['contexts'][0]['action'], 'investigate')

    def test_watch_surfaces_identifiable_invalid_update_as_ambiguity(self):
        body = json.loads(capture().payload)
        body['features'][0]['geometry']['coordinates'][0] = 300
        reports = self.watch(Reader([capture(), capture(payload=json.dumps(body).encode())]))
        self.assertEqual(reports[1]['observations'], 0)
        self.assertEqual(reports[1]['ambiguity_event_ids'], ['invented-earthquake'])
        self.assertTrue(reports[1]['contexts'][0]['event_ambiguity'])

    def test_demo_replays_correction_and_preserves_original_understanding(self):
        result = event_demo(self.path.parent/'demo')
        self.assertEqual(result['initial_context']['action'], 'investigate')
        self.assertEqual(result['initial_context']['candidates'][0]['listing_id'], 'event-demo-listing')
        self.assertEqual(result['corrected_context']['action'], 'observe')
        self.assertTrue(result['historical_event_preserved'])
        self.assertIsNone(result['first_capture']['observations'][0]['published_at'])
        self.assertIsNone(result['first_capture']['observations'][0]['tsunami_confirmed'])
        self.assertFalse(result['predictive_model_implemented'])
        self.assertEqual(result['network_requests'], 0)

    def test_demo_output_is_stable_across_process_restart(self):
        command = [sys.executable, '-m', 'trading_intelligence', 'event-intelligence-demo',
                   '--out', str(self.path.parent/'restart')]
        env = dict(os.environ, PYTHONPATH='src')
        one = subprocess.check_output(command, text=True, env=env)
        two = subprocess.check_output(command, text=True, env=env)
        self.assertEqual(one, two)

    def test_cli_missing_database_returns_clean_error_without_creating_one(self):
        missing = self.path.parent/'missing.sqlite3'
        command = [sys.executable, '-m', 'trading_intelligence', 'event-sync', '--database',
                   str(missing), '--source-id', 'events', '--import-id', 'test', '--feed', 'all_hour']
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('Traceback', result.stderr)
        self.assertFalse(missing.exists())
