"""Injected price sync tests over durable provider-shaped fixtures."""
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlencode

from trading_intelligence import DataOrigin,Use,Entity,Instrument,Listing,AssetKind
from trading_intelligence.alpaca_market import AlpacaMarketStore
from trading_intelligence.alpaca_price_reader import PriceRead,PriceReadError,PRICE_URL,price_query
from trading_intelligence.brokers import BrokerAccount,Environment
from trading_intelligence.contracts import ContractError,RecordConflict,EvidenceIntegrityError
from trading_intelligence.price_sync import sync_prices

T=datetime(2026,1,10,tzinfo=timezone.utc)
ROUTE=BrokerAccount('alpaca','c','a',Environment.PAPER)

def body(day,token=None):return json.dumps(dict(bars={'DEMO':[dict(t=day+'T05:00:00Z',o=100,h=105,l=95,c=102,v=50)]},next_page_token=token)).encode()

class Reader:
    def __init__(self,pages):self.pages=list(pages);self.calls=[]
    def read(self,symbols,start,end,**kw):
        self.calls.append(kw)
        item=self.pages.pop(0)
        if isinstance(item,Exception):raise item
        q=price_query(symbols,start,end,feed=kw['feed'],page_token=kw['page_token'],limit=kw['limit'])
        return PriceRead(item,T,PRICE_URL+'?'+urlencode(q),ROUTE,tuple(sorted(symbols)),start,end,kw['feed'],kw['page_token'],kw['limit'])

class PriceSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'sync.db';self.s=AlpacaMarketStore(self.path);self.addCleanup(lambda:self.s.close())
        # Explicit provider declaration tests orchestration only, not real access.
        self.s.register_source('provider',DataOrigin.PROVIDER)
        self.s.set_permissions('provider',known_at=T-timedelta(days=5),uses={Use.STORAGE,Use.RESEARCH})
        self.s.register_entity(Entity('e','Invented'));self.s.register_instrument(Instrument('i','e',AssetKind.EQUITY));self.s.register_listing(Listing('l','i','XNAS','USD'))

    def sync(self,reader,**changes):
        args=dict(source_id='provider',import_id='job',route=ROUTE,symbol_listings={'DEMO':'l'},start_date='2026-01-05',end_date='2026-01-06',feed='iex',reader=reader,clock=lambda:T);args.update(changes)
        return sync_prices(self.s,**args)

    def test_two_pages_have_durable_provenance_and_unknown_publication(self):
        reader=Reader([body('2026-01-05','next'),body('2026-01-06')]);r=self.sync(reader)
        self.assertTrue(r['pages_complete']);self.assertEqual(len(r['pages']),2);self.assertFalse(r['market_admitted'])
        self.assertIsNone(r['published_at']);self.assertEqual(reader.calls[1]['page_token'],'next')
        for page in r['pages']:
            self.assertEqual(page['provenance']['route']['account_id'],'a')
            c=self.s.capture_as_of('provider',page['capture_id'],as_of=T+timedelta(seconds=1));self.assertIsNone(c['candidates'][0]['published_at'])

    def test_restart_retry_does_not_refetch(self):
        r=self.sync(Reader([body('2026-01-05')]))
        self.s.close();self.s=AlpacaMarketStore(self.path)
        reader=Reader([]);self.assertEqual(r,self.sync(reader));self.assertEqual(reader.calls,[])
        with self.assertRaises(RecordConflict):self.sync(reader,feed='sip')

    def test_partial_http_failure_retains_first_page(self):
        r=self.sync(Reader([body('2026-01-05','next'),PriceReadError('hidden')]))
        self.assertEqual(r['reason'],'read_failed');self.assertFalse(r['pages_complete']);self.assertEqual(len(r['pages']),1)
        self.assertIsNotNone(self.s.capture_as_of('provider',r['pages'][0]['capture_id'],as_of=T+timedelta(seconds=1)))
        self.assertEqual(r,self.sync(Reader([])))

    def test_cycle_and_page_limit(self):
        for key,pages,limit,reason in [('cycle',[body('2026-01-05','n'),body('2026-01-06','n')],10,'pagination_cycle'),('limit',[body('2026-01-05','n')],1,'page_limit')]:
            r=self.sync(Reader(pages),import_id=key,max_pages=limit);self.assertEqual(r['reason'],reason);self.assertFalse(r['pages_complete'])

    def test_missing_token_malformed_and_quarantined_pages_retained(self):
        for index,(payload,reason) in enumerate([(b'{"bars":{}}','pagination_unknown'),(b'invalid','invalid_page_records')]):
            r=self.sync(Reader([payload]),import_id=str(index));self.assertEqual(r['reason'],reason);self.assertEqual(len(r['pages']),1)

    def test_outside_request_and_cross_page_duplicate_not_complete(self):
        for index,(pages,reason) in enumerate([([body('2026-01-07')],'response_outside_request'),([body('2026-01-05','n'),body('2026-01-05')],'duplicate_cross_page_bar')]):
            r=self.sync(Reader(pages),import_id=str(index));self.assertEqual(r['reason'],reason);self.assertFalse(r['pages_complete'])

    def test_bounds_transactions_and_synthetic_source(self):
        for changes in [dict(max_pages=101),dict(max_pages=True),dict(max_total_bytes=0),dict(page_limit=True)]:
            with self.assertRaises(ContractError):self.sync(Reader([]),**changes)
        self.s.db.execute('INSERT INTO entities VALUES (?,?)',('pending','Pending'))
        with self.assertRaises(ContractError):self.sync(Reader([]))
        self.assertTrue(self.s.db.in_transaction);self.s.db.rollback()
        self.s.register_source('fixture',DataOrigin.SYNTHETIC);self.s.set_permissions('fixture',known_at=T,uses={Use.STORAGE,Use.RESEARCH})
        with self.assertRaises(ContractError):self.sync(Reader([]),source_id='fixture')

    def test_result_and_raw_page_corruption_fail_closed(self):
        r=self.sync(Reader([body('2026-01-05')]))
        self.s.db.execute("UPDATE price_sync_results SET body_json='{}'");self.s.db.commit()
        with self.assertRaises(EvidenceIntegrityError):self.sync(Reader([]))

    def test_total_byte_limit_stops_before_another_request(self):
        payload=body('2026-01-05','next');reader=Reader([payload])
        r=self.sync(reader,max_total_bytes=len(payload))
        self.assertEqual(r['reason'],'byte_limit');self.assertEqual(len(reader.calls),1)

    def test_interrupted_job_is_reported_without_automatic_refetch(self):
        r=self.sync(Reader([body('2026-01-05')]))
        self.s.db.execute('DELETE FROM price_sync_results');self.s.db.commit()
        reader=Reader([]);r=self.sync(reader)
        self.assertEqual(r['reason'],'interrupted_previous_run');self.assertEqual(reader.calls,[])
        self.assertEqual(len(r['pages']),1)

    def test_page_journal_corruption_and_source_archive_corruption(self):
        r=self.sync(Reader([body('2026-01-05')]))
        self.s.db.execute("UPDATE price_sync_pages SET body_json='{}'");self.s.db.commit()
        with self.assertRaises(EvidenceIntegrityError):self.sync(Reader([]))

    def test_clock_must_not_backdate_a_request_or_receipt(self):
        self.sync(Reader([body('2026-01-05')]))
        with self.assertRaises(ContractError):self.sync(Reader([]),clock=lambda:T-timedelta(seconds=1))
        with self.assertRaises(ContractError):self.sync(Reader([body('2026-01-05')]),import_id='later',clock=lambda:T+timedelta(seconds=1))

    def test_synthetic_demo_two_pages_and_repeat(self):
        from trading_intelligence.price_demo import price_demo
        directory=Path(self.tmp.name)/'demo'
        r=price_demo(directory)
        self.assertEqual(r['injected_get_pages'],2);self.assertEqual(r['origin'],'synthetic_fixture')
        self.assertFalse(r['real_network_access']);self.assertFalse(r['market_admitted'])
        self.assertEqual(r,price_demo(directory))
