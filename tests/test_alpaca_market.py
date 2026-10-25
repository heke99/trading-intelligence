"""Invented vendor-shaped capture tests; no authenticated market access."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from trading_intelligence import DataOrigin, Use, Entity, Instrument, Listing, AssetKind
from trading_intelligence.alpaca_market import AlpacaMarketStore
from trading_intelligence.contracts import ContractError, RecordConflict, EvidenceIntegrityError, UseNotAllowed

T = datetime(2026,1,6,22,tzinfo=timezone.utc)


class AlpacaMarketTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'capture.db'
        self.s=AlpacaMarketStore(self.path); self.addCleanup(lambda:self.s.close())
        self.s.register_source('fixture',DataOrigin.SYNTHETIC)
        self.s.set_permissions('fixture',known_at=T-timedelta(days=1),uses={Use.STORAGE,Use.RESEARCH})
        self.s.register_entity(Entity('e','Invented issuer'))
        self.s.register_instrument(Instrument('i','e',AssetKind.EQUITY))
        self.s.register_listing(Listing('l','i','XNAS','USD'))

    def bar(self):
        return dict(t='2026-01-06T05:00:00Z',o=100,h=105,l=95,c=102,v=50,n=1,vw=101)

    def put(self, response=None, **changes):
        args=dict(source_id='fixture',import_id='capture',payload=json.dumps(response or {'bars':{'DEMO':[self.bar()]},'next_page_token':None}).encode(),received_at=T,processed_at=T+timedelta(seconds=1),symbol_listings={'DEMO':'l'},feed='iex',timeframe='1Day',adjustment='raw',market_timezone='America/New_York')
        args.update(changes); return self.s.import_bars(**args)

    def test_staged_without_fabricated_publication_or_session(self):
        r=self.put(); c=r['candidates'][0]
        self.assertEqual(c['values']['close'],'102');self.assertEqual(c['date'],'2026-01-06')
        self.assertIsNone(c['published_at']);self.assertIsNone(c['session_start']);self.assertIsNone(c['session_end'])
        self.assertFalse(r['training_ready']);self.assertFalse(r['full_history_verified'])
        self.assertEqual(self.s.db.execute('SELECT count(*) FROM market_snapshots').fetchone()[0],0)
        self.assertEqual(self.s.db.execute('SELECT count(*) FROM evidence_versions').fetchone()[0],0)

    def test_original_bytes_preserved(self):
        payload=b'{"bars":{"DEMO":[{"t":"2026-01-06T05:00:00Z","o":100.10,"h":105,"l":95,"c":102,"v":50}]},"next_page_token":null}'
        r=self.put(payload=payload)
        self.assertEqual(r['candidates'][0]['values']['open'],'100.10')
        self.assertEqual(self.s.db.execute('SELECT payload FROM raw_objects WHERE sha256=?',(r['raw_sha'],)).fetchone()[0],payload)

    def test_processing_availability(self):
        self.put();self.assertIsNone(self.s.capture_as_of('fixture','capture',as_of=T))
        self.assertIsNotNone(self.s.capture_as_of('fixture','capture',as_of=T+timedelta(seconds=1)))

    def test_retry_after_reopen(self):
        original=self.put();self.s.close();self.s=AlpacaMarketStore(self.path)
        self.assertEqual(self.put(),original)
        self.assertEqual(self.s.db.execute('SELECT count(*) FROM alpaca_market_captures').fetchone()[0],1)

    def test_changed_input_rejected(self):
        self.put()
        for changed in [dict(feed='sip'),dict(processed_at=T+timedelta(seconds=2)),dict(payload=b'{}')]:
            with self.subTest(changed=changed),self.assertRaises(RecordConflict):self.put(**changed)

    def test_missing_and_more_pages_never_complete(self):
        for idx,response in enumerate([{'bars':{}},{'bars':{},'next_page_token':'another'}]):
            r=self.put(response,import_id=str(idx));self.assertFalse(r['page_complete'])
            self.assertEqual(r['pagination_state'],'unknown' if idx==0 else 'more_pages')

    def test_invalid_page_token_durable(self):
        r=self.put({'bars':{},'next_page_token':False});self.assertEqual(r['quarantined'][0]['reason'],'invalid_page_token')
        self.assertEqual(self.s.db.execute('SELECT count(*) FROM alpaca_market_quarantine').fetchone()[0],1)

    def test_malformed_json_and_duplicate_key_durable(self):
        for idx,payload in enumerate([b'not json',b'{"bars":{},"bars":{}}',b'{"bars":{},"x":NaN}']):
            r=self.put(payload=payload,import_id=str(idx));self.assertEqual(len(r['quarantined']),1)
            self.assertEqual(self.s.capture_as_of('fixture',str(idx),as_of=T+timedelta(seconds=1)),r)

    def test_invalid_rows_preserve_valid_candidates(self):
        invalid=self.bar();invalid['l']=110
        r=self.put({'bars':{'DEMO':[self.bar(),invalid]},'next_page_token':None})
        self.assertEqual(len(r['candidates']),1);self.assertEqual(len(r['quarantined']),1)
        self.assertFalse(r['page_complete'])

    def test_ambiguous_daily_rows_quarantined(self):
        r=self.put({'bars':{'DEMO':[self.bar(),self.bar()]},'next_page_token':None})
        self.assertEqual(len(r['candidates']),0);self.assertEqual(len(r['quarantined']),2)

    def test_unmapped_symbol_and_wrong_array_quarantined(self):
        r=self.put({'bars':{'OTHER':[self.bar()],'DEMO':None},'next_page_token':None})
        self.assertEqual(len(r['quarantined']),2)

    def test_bad_numeric_boolean_nan_and_bounds(self):
        for idx,(key,value) in enumerate([('o',True),('v',-1),('v',1.5),('h',90),('c','102'),('o',float('inf'))]):
            b=self.bar();b[key]=value
            r=self.put({'bars':{'DEMO':[b]},'next_page_token':None},import_id=str(idx))
            self.assertTrue(r['quarantined']);self.assertFalse(r['candidates'])

    def test_naive_or_future_timestamp_quarantined(self):
        for idx,value in enumerate(['2026-01-06T05:00:00','2027-01-06T05:00:00Z']):
            b=self.bar();b['t']=value
            self.assertTrue(self.put({'bars':{'DEMO':[b]},'next_page_token':None},import_id=str(idx))['quarantined'])

    def test_no_adjusted_or_intraday_or_unknown_mapping(self):
        for changes in [dict(request_currency='EUR'),dict(feed='unknown'),dict(adjustment='split'),dict(timeframe='1Min'),dict(symbol_listings={'DEMO':'unknown'}),dict(market_timezone='Unknown/Zone')]:
            with self.subTest(changes=changes),self.assertRaises(ContractError):self.put(**changes)

    def test_permissions_and_receipt_processing_order(self):
        with self.assertRaises(ContractError):self.put(processed_at=T-timedelta(seconds=1))
        self.s.set_permissions('fixture',known_at=T,uses={Use.STORAGE})
        with self.assertRaises(UseNotAllowed):self.put()

    def test_raw_manifest_and_quarantine_corruption(self):
        for table,change in [('raw_objects',"payload=X'00'"),('alpaca_market_captures',"result_json='{}'"),('alpaca_market_quarantine',"reason='changed'")]:
            with self.subTest(table=table):
                key=table;self.put(payload=b'invalid json',import_id=key)
                if table=='raw_objects':
                    sha=self.s.db.execute('SELECT raw_sha FROM alpaca_market_captures WHERE import_id=?',(key,)).fetchone()[0]
                    self.s.db.execute(f'UPDATE {table} SET {change} WHERE sha256=?',(sha,))
                else:self.s.db.execute(f'UPDATE {table} SET {change} WHERE import_id=?',(key,))
                self.s.db.commit()
                with self.assertRaises(EvidenceIntegrityError):self.s.capture_as_of('fixture',key,as_of=T+timedelta(seconds=1))
                if table=='raw_objects':self.s.db.execute('UPDATE raw_objects SET payload=? WHERE sha256=?',(b'invalid json',sha));self.s.db.commit()

    def test_quarantine_paths_escape_symbols(self):
        bad=self.bar();bad['o']=False
        r=self.put({'bars':{'DEMO':[bad],'DEMO/0':[]},'next_page_token':None})
        self.assertEqual(len(r['quarantined']),2)

    def test_import_does_not_commit_caller_transaction(self):
        self.s.db.execute("INSERT INTO entities VALUES (?,?)", ('pending','Pending caller data'))
        self.assertTrue(self.s.db.in_transaction)
        with self.assertRaises(ContractError):
            self.put()
        self.assertTrue(self.s.db.in_transaction)
        self.assertEqual(self.s.db.execute("SELECT count(*) FROM entities WHERE entity_id='pending'").fetchone()[0],1)
        self.assertEqual(self.s.db.execute('SELECT count(*) FROM alpaca_market_captures').fetchone()[0],0)
        self.s.db.rollback()
        self.assertEqual(self.s.db.execute("SELECT count(*) FROM entities WHERE entity_id='pending'").fetchone()[0],0)
        self.assertFalse(self.s.db.in_transaction)
