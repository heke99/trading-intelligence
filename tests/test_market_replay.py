"""Invented date scopes and market records, not real exchange calendars."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from trading_intelligence import AssetKind, DataOrigin, Entity, Instrument, Listing, Use
from trading_intelligence.contracts import ContractError, EvidenceIntegrityError, UseNotAllowed
from trading_intelligence.market_data import MarketDataStore
from trading_intelligence.market_replay import replay_dates

T = datetime(2026, 1, 10, tzinfo=timezone.utc)
DATES = ['2026-01-05', '2026-01-06', '2026-01-07']


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'replay.db'
        self.s = MarketDataStore(self.path)
        self.addCleanup(lambda: self.s.close())
        self.s.register_source('fixture', DataOrigin.SYNTHETIC)
        self.s.set_permissions('fixture', known_at=T-timedelta(days=30), uses={Use.STORAGE, Use.RESEARCH})
        self.s.register_entity(Entity('e', 'Invented'))
        self.s.register_instrument(Instrument('i', 'e', AssetKind.EQUITY))
        self.s.register_listing(Listing('l', 'i', 'XNAS', 'USD'))

    def put(self, day, kind, **changes):
        values = {'open':'100','high':'105','low':'95','close':'102','volume':'50','price_kind':'raw'}
        if kind == 'session':
            values = {'timezone':'America/New_York'}
        if kind == 'split':
            values = {'new_shares':'2','old_shares':'1'}
        body = dict(kind=kind, listing_id='l', date=day, start=day+'T14:30:00Z',
                    end=day+'T21:00:00Z', currency='USD', values=values)
        body.update(changes.pop('body_changes', {}))
        args = dict(source_id='fixture', record_id=kind+day, revision_id='1',
                    payload=json.dumps(body).encode(), published_at=T, received_at=T,
                    processed_at=T+timedelta(seconds=1))
        args.update(changes)
        return self.s.import_record(**args)

    def fill(self, dates=DATES):
        for day in dates:
            for kind in ('session', 'bar'):
                self.put(day, kind)

    def replay(self, **changes):
        args = dict(as_of=T+timedelta(seconds=2)); args.update(changes)
        return replay_dates(self.s, 'fixture', 'l', DATES, **args)

    def test_multiday_complete_and_raw_actions(self):
        self.fill(); self.put(DATES[1], 'split')
        r=self.replay()
        self.assertTrue(r['complete_scope']); self.assertEqual(len(r['days']),3)
        self.assertEqual(len(r['manifest']['records']),7)
        self.assertEqual(r['days'][1]['bar']['values']['close'],'102')
        self.assertEqual(len(r['days'][1]['actions']),1)
        for flag in ('training_ready','full_history_verified','live_trading'):
            self.assertFalse(r[flag])

    def test_gap_lists_missing_kind_without_zero_return(self):
        self.fill(DATES[:1]); self.put(DATES[1], 'session')
        r=self.replay()
        self.assertFalse(r['complete_scope']); self.assertEqual(len(r['days']),1)
        self.assertEqual(r['gaps'],[
            {'date':DATES[1],'missing':['bar'],'reason':'not_available_at_cutoff'},
            {'date':DATES[2],'missing':['session','bar'],'reason':'not_available_at_cutoff'}])

    def test_future_processing_is_gap_without_future_knowledge(self):
        self.fill()
        r=self.replay(as_of=T)
        self.assertEqual(len(r['days']),0)
        self.assertEqual(len(r['gaps']),3)

    def test_late_correction_preserves_earlier_manifest(self):
        self.fill(); before=self.replay()
        evidence=self.s.db.execute("SELECT evidence_id FROM evidence_versions WHERE record_id=?",('bar'+DATES[0],)).fetchone()[0]
        values={'open':'100','high':'105','low':'95','close':'103','volume':'50','price_kind':'raw'}
        self.put(DATES[0],'bar',body_changes={'values':values},revision_id='2',
                 received_at=T+timedelta(days=1),processed_at=T+timedelta(days=1,seconds=1),correction_of=evidence)
        self.assertEqual(before,self.replay())
        after=self.replay(as_of=T+timedelta(days=2))
        self.assertNotEqual(before['manifest_sha256'],after['manifest_sha256'])
        self.assertEqual(after['days'][0]['bar']['values']['close'],'103')

    def test_manifest_survives_restart(self):
        self.fill(); before=self.replay(); self.s.close(); self.s=MarketDataStore(self.path)
        self.assertEqual(before,self.replay())

    def test_bad_scope_rejected(self):
        for dates in ([],DATES[::-1],DATES+[DATES[0]],'2026-01-05',['20260105'],[None]):
            with self.subTest(dates=dates),self.assertRaises(ContractError):
                replay_dates(self.s,'fixture','l',dates,as_of=T)
        with self.assertRaises(ContractError):
            replay_dates(self.s,'fixture','l',DATES,as_of=datetime(2026,1,10))

    def test_no_calendar_inference(self):
        self.fill(DATES[:1])
        r=replay_dates(self.s,'fixture','l',[DATES[0]],as_of=T+timedelta(days=1))
        self.assertTrue(r['complete_scope'])
        self.assertEqual(r['manifest']['expected_dates'],[DATES[0]])

    def test_revoked_permission_and_unknown_listing_fail_even_empty(self):
        with self.assertRaises(ContractError):
            replay_dates(self.s,'fixture','unknown',DATES,as_of=T)
        self.s.set_permissions('fixture',known_at=T,uses={Use.STORAGE})
        with self.assertRaises(UseNotAllowed): self.replay()
        with self.assertRaises(UseNotAllowed):
            replay_dates(self.s,'unknown','l',DATES,as_of=T)

    def test_missing_session_cannot_hide_corrupt_bar(self):
        self.put(DATES[0],'bar')
        self.s.db.execute('UPDATE raw_objects SET payload=?',(b'corrupt',)); self.s.db.commit()
        with self.assertRaises(EvidenceIntegrityError): self.replay()

    def test_mismatch_and_ambiguity_not_reported_as_gap(self):
        self.fill()
        snap=self.s.db.execute("SELECT evidence_id FROM evidence_versions WHERE record_id=?",('session'+DATES[0],)).fetchone()[0]
        self.put(DATES[0],'session',body_changes={'end':DATES[0]+'T20:00:00Z'},revision_id='2',
                 received_at=T+timedelta(days=1),processed_at=T+timedelta(days=1,seconds=1),correction_of=snap)
        with self.assertRaises(ContractError): self.replay(as_of=T+timedelta(days=2))
        self.put(DATES[0],'bar',body_changes={'start':DATES[0]+'T15:00:00Z'},record_id='other')
        with self.assertRaises(ContractError): self.replay()

    def test_savepoint_does_not_commit_caller_transaction(self):
        self.fill()
        self.s.db.execute('BEGIN')
        self.s.db.execute("INSERT INTO entities VALUES ('pending','Pending')")
        self.replay()
        self.assertTrue(self.s.db.in_transaction)
        self.s.db.rollback()
        self.assertIsNone(self.s.db.execute("SELECT 1 FROM entities WHERE entity_id='pending'").fetchone())
