"""Synthetic daily replay regressions; no exchange/source authentication."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from trading_intelligence import AssetKind, DataOrigin, Entity, Instrument, Listing, Use
from trading_intelligence.contracts import ContractError, EvidenceIntegrityError, UseNotAllowed
from trading_intelligence.market_data import MarketDataStore
from trading_intelligence.references import ReferenceUnavailable

T = datetime(2026, 1, 5, 22, tzinfo=timezone.utc)

class MarketTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'market.db'
        self.s = MarketDataStore(self.path)
        self.addCleanup(lambda: self.s.close())
        self.s.register_source('fixture', DataOrigin.SYNTHETIC)
        self.s.set_permissions('fixture', known_at=T-timedelta(days=2), uses={Use.STORAGE, Use.RESEARCH})
        self.s.register_entity(Entity('e', 'Invented'))
        self.s.register_instrument(Instrument('i', 'e', AssetKind.EQUITY))
        self.s.register_listing(Listing('l', 'i', 'XNAS', 'USD'))

    def body(self, kind='bar'):
        values = {'open':'100','high':'105','low':'95','close':'102','volume':'50','price_kind':'raw'}
        if kind == 'session': values = {'timezone':'America/New_York'}
        if kind == 'split': values = {'new_shares':'2','old_shares':'1'}
        if kind == 'cash_dividend': values = {'amount':'1','payment_date':'2026-01-20'}
        return dict(kind=kind, listing_id='l', date='2026-01-05', start='2026-01-05T14:30:00Z', end='2026-01-05T21:00:00Z', currency='USD', values=values)

    def put(self, kind='bar', body=None, **kw):
        args = dict(source_id='fixture', record_id=kind, revision_id='1', payload=json.dumps(body or self.body(kind)).encode(), published_at=T, received_at=T, processed_at=T+timedelta(seconds=1))
        args.update(kw)
        return self.s.import_record(**args)

    def replay(self, **kw):
        args = dict(as_of=T+timedelta(seconds=2)); args.update(kw)
        return self.s.replay_day('fixture','l','2026-01-05',**args)

    def test_processing_availability(self):
        self.put('session'); self.put()
        with self.assertRaises(ReferenceUnavailable): self.replay(as_of=T)
        self.assertEqual(self.replay()['bar'].body['values']['close'],'102')

    def test_correction_preserves_original_replay(self):
        self.put('session'); self.put()
        evidence=self.s.db.execute("SELECT evidence_id FROM market_snapshots WHERE kind='bar'").fetchone()[0]
        b=self.body(); b['values']['close']='103'
        self.put(body=b, revision_id='2', published_at=T+timedelta(days=1), received_at=T+timedelta(days=1), processed_at=T+timedelta(days=1,seconds=1), correction_of=evidence)
        self.assertEqual(self.replay()['bar'].body['values']['close'],'102')
        self.assertEqual(self.replay(as_of=T+timedelta(days=2))['bar'].body['values']['close'],'103')

    def test_restart_idempotence(self):
        self.put('session'); first=self.put(); self.s.close(); self.s=MarketDataStore(self.path)
        self.assertEqual(first,self.put())
        self.assertEqual(self.s.db.execute('SELECT count(*) FROM market_snapshots').fetchone()[0],2)

    def test_split_and_dividend_do_not_adjust_raw_price(self):
        for kind in ('session','bar','split','cash_dividend'): self.put(kind)
        r=self.replay(); self.assertEqual(len(r['actions']),2)
        self.assertEqual(r['bar'].body['values']['close'],'102')
        self.assertFalse(r['training_ready']); self.assertFalse(r['live_trading'])

    def test_missing_day_or_session_is_not_zero(self):
        self.put()
        with self.assertRaises(ReferenceUnavailable): self.replay()
        with self.assertRaises(ReferenceUnavailable): self.s.replay_day('fixture','l','2026-01-06',as_of=T)

    def test_session_mismatch(self):
        self.put('session'); b=self.body(); b['end']='2026-01-05T20:00:00Z'; self.put(body=b)
        with self.assertRaises(ContractError): self.replay()

    def test_adjusted_float_nan_bad_bounds_rejected(self):
        for key,value in [('price_kind','adjusted'),('open',100.0),('open','NaN'),('low','103'),('volume','-1')]:
            b=self.body(); b['values'][key]=value
            with self.subTest(key=key,value=value), self.assertRaises(ContractError): self.put(body=b)
        self.assertEqual(self.s.db.execute('SELECT count(*) FROM market_snapshots').fetchone()[0],0)

    def test_premature_publication_and_processing(self):
        with self.assertRaises(ContractError): self.put(published_at=T-timedelta(hours=2))
        with self.assertRaises(ContractError): self.put(processed_at=T-timedelta(seconds=1))

    def test_duplicate_keys(self):
        with self.assertRaises(ContractError): self.put(payload=b'{"kind":"bar","kind":"split"}')

    def test_identity_currency_and_timezone(self):
        for key,value in [('listing_id','unknown'),('currency','EUR'),('start','2026-01-05T14:30:00')]:
            b=self.body(); b[key]=value
            with self.subTest(key=key), self.assertRaises(ContractError): self.put(body=b)
        b=self.body('session'); b['values']['timezone']='Invalid/Zone'
        with self.assertRaises(ContractError): self.put('session',body=b)

    def test_permission_revocation_blocks_replay(self):
        self.put('session'); self.put()
        self.s.set_permissions('fixture',known_at=T+timedelta(seconds=2),uses={Use.STORAGE})
        with self.assertRaises(UseNotAllowed): self.replay()

    def test_corrupt_payload_detected(self):
        self.put('session'); self.put()
        self.s.db.execute("UPDATE raw_objects SET payload=?",(b'corrupt',)); self.s.db.commit()
        with self.assertRaises(EvidenceIntegrityError): self.replay()

    def test_unlinked_replacement_and_changed_retry_rejected(self):
        self.put()
        with self.assertRaises(ContractError): self.put(revision_id='2')
        with self.assertRaises(ContractError): self.put(processed_at=T+timedelta(seconds=5))

    def test_dst_uses_explicit_session_not_fixed_utc_hours(self):
        b=self.body('session'); b.update(date='2026-07-06',start='2026-07-06T13:30:00Z',end='2026-07-06T20:00:00Z')
        self.put('session',body=b)
        b['values']['timezone']='UTC'; b['date']='2026-07-07'
        with self.assertRaises(ContractError): self.put('session',body=b,record_id='other')

    def test_correction_cannot_reverse_processing_order(self):
        self.put(processed_at=T+timedelta(days=3))
        evidence=self.s.db.execute("SELECT evidence_id FROM market_snapshots").fetchone()[0]
        with self.assertRaises(ContractError):
            self.put(revision_id='2',received_at=T+timedelta(days=1),processed_at=T+timedelta(days=2),correction_of=evidence)

    def test_snapshot_corruption_detected(self):
        self.put('session'); self.put()
        self.s.db.execute("UPDATE market_snapshots SET body='{}' WHERE kind='bar'"); self.s.db.commit()
        with self.assertRaises(EvidenceIntegrityError): self.replay()

    def test_action_wrong_local_date_blocks_replay(self):
        self.put('session'); self.put()
        b=self.body('split'); b['start']='2026-01-06T14:30:00Z'; b['end']='2026-01-06T21:00:00Z'
        self.put('split',body=b)
        with self.assertRaises(ContractError): self.replay()

    def test_retry_verifies_archived_snapshot(self):
        self.put()
        self.s.db.execute("UPDATE market_snapshots SET body='{}'"); self.s.db.commit()
        with self.assertRaises(EvidenceIntegrityError): self.put()

    def test_structured_kind_and_identity_are_contract_errors(self):
        for field in ('kind', 'listing_id'):
            for value in ({}, [], None, True):
                body = self.body(); body[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ContractError):
                    self.put(body=body)
