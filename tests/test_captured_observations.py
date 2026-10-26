from datetime import datetime,timedelta,timezone
from pathlib import Path
import json,tempfile,unittest
from urllib.parse import urlencode
from trading_intelligence import DataOrigin,Use,Entity,Instrument,Listing,AssetKind
from trading_intelligence.alpaca_calendar import AlpacaCalendarStore
from trading_intelligence.alpaca_price_reader import PriceRead,PRICE_URL,price_query
from trading_intelligence.brokers import BrokerAccount,Environment
from trading_intelligence.price_sync import sync_prices
from trading_intelligence.captured_observations import inspect_captures,verify_inspection
from trading_intelligence.contracts import ContractError,EvidenceIntegrityError,UseNotAllowed
T=datetime(2026,1,10,tzinfo=timezone.utc)
R=BrokerAccount('alpaca','c','a',Environment.PAPER)
class Reader:
    def read(self,symbols,start,end,**kw):
        q=price_query(symbols,start,end,feed=kw['feed'],page_token=kw['page_token'],limit=kw['limit'])
        payload=json.dumps(dict(bars={'DEMO':[dict(t=d+'T05:00:00Z',o=100,h=105,l=95,c=102,v=50) for d in ['2026-01-05','2026-01-06']]},next_page_token=None)).encode()
        return PriceRead(payload,T,PRICE_URL+'?'+urlencode(q),R,tuple(symbols),start,end,kw['feed'],kw['page_token'],kw['limit'])
class InspectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)/'e.db'
        self.s=AlpacaCalendarStore(self.path);self.addCleanup(lambda:self.s.close())
        for source in ['prices','calendar']:
            self.s.register_source(source,DataOrigin.PROVIDER);self.s.set_permissions(source,known_at=T-timedelta(days=1),uses={Use.STORAGE,Use.RESEARCH})
        self.s.register_entity(Entity('e','Invented'));self.s.register_instrument(Instrument('i','e',AssetKind.EQUITY));self.s.register_listing(Listing('l','i','XNAS','USD'))
        sync_prices(self.s,source_id='prices',import_id='job',route=R,symbol_listings={'DEMO':'l'},start_date='2026-01-05',end_date='2026-01-06',feed='iex',reader=Reader(),clock=lambda:T)
        self.calendar()
    def calendar(self,import_id='cal',rows=None,route=None):
        rows=rows if rows is not None else [dict(date=d,open='09:30',close='16:00') for d in ['2026-01-05','2026-01-06']]
        provenance=dict(endpoint='https://paper-api.alpaca.markets/v2/calendar',method='GET',query=dict(start='2026-01-05',end='2026-01-06',date_type='TRADING'),route=route or dict(broker_id='alpaca',connection_id='c',account_id='a',environment='paper'))
        return self.s.import_calendar(source_id='calendar',import_id=import_id,payload=json.dumps(rows).encode(),received_at=T,processed_at=T+timedelta(seconds=1),start_date='2026-01-05',end_date='2026-01-06',provenance=provenance)
    def inspect(self,**changes):
        args=dict(price_source_id='prices',price_import_id='job',calendar_source_id='calendar',calendar_import_id='cal',listing_id='l',clock=lambda:T+timedelta(seconds=2));args.update(changes);return inspect_captures(self.s,**args)
    def test_distinct_sources_ties_and_mismatched_venue_remain_inspection(self):
        r=self.inspect();self.assertEqual(len(r['observations']),2);self.assertEqual(r['observation_groups'],[dict(available_at='2026-01-10T00:00:01.000000Z',indices=[0,1])]);self.assertFalse(r['calendar_venue_matches_listing']);self.assertFalse(r['dataset_admitted']);self.assertIsNone(r['observations'][0]['published_at']);self.assertEqual(verify_inspection(r),r)
    def test_current_rights_revocation(self):
        self.s.set_permissions('calendar',known_at=T+timedelta(seconds=2),uses={Use.STORAGE})
        with self.assertRaises(UseNotAllowed):self.inspect()
    def test_raw_corruption_blocks(self):
        self.s.db.execute("UPDATE raw_objects SET payload=X'00'");self.s.db.commit()
        with self.assertRaises(EvidenceIntegrityError):self.inspect()
    def test_calendar_quarantine_and_date_gap(self):
        for key,rows in [('bad',[dict(date='2026-01-05',open='bad',close='16:00')]),('gap',[dict(date='2026-01-05',open='09:30',close='16:00')])]:
            self.calendar(key,rows)
            with self.assertRaises(ContractError):self.inspect(calendar_import_id=key)
    def test_wrong_route_and_same_source_and_direct_capture_rejected(self):
        self.calendar('other',route=dict(broker_id='alpaca',connection_id='other',account_id='a',environment='paper'))
        for changes in [dict(calendar_import_id='other'),dict(calendar_source_id='prices'),dict(price_import_id='missing')]:
            with self.assertRaises(ContractError):self.inspect(**changes)
    def test_restart_and_explicit_scope(self):
        before=self.inspect();self.s.close();self.s=AlpacaCalendarStore(self.path);self.assertEqual(before,self.inspect());self.assertEqual(before,self.inspect(expected_dates=['2026-01-05','2026-01-06']))
        with self.assertRaises(ContractError):self.inspect(expected_dates=['2026-01-05'])
    def test_future_capture_and_altered_report(self):
        with self.assertRaises(ContractError):self.inspect(clock=lambda:T)
        r=self.inspect();r['observations'][0]['published_at']='invented'
        with self.assertRaises(EvidenceIntegrityError):verify_inspection(r)
    def test_read_preserves_caller_transaction(self):
        self.s.db.execute("INSERT INTO entities VALUES ('pending','Pending')");self.inspect();self.assertTrue(self.s.db.in_transaction);self.s.db.rollback()
    def test_daily_bar_received_before_calendar_close_rejected(self):
        # Inject inconsistent capture metadata to exercise the semantic guard
        # independently from archive-corruption detection.
        rows=[dict(date=d,open='09:30',close='16:00') for d in ['2026-01-05','2026-01-06']]
        self.calendar('future-clock',rows)
        # Move fixture receipt/known clock earlier by constructing a separate price job.
        import trading_intelligence.captured_observations as module
        from unittest.mock import patch
        original=self.s.capture_as_of
        def altered(*a,**kw):
            value=original(*a,**kw);value['received_at']='2026-01-05T01:00:00.000000Z';return value
        with patch.object(self.s,'capture_as_of',side_effect=altered),self.assertRaises(ContractError):self.inspect()

    def test_nonascending_source_rows_not_silently_reordered(self):
        from unittest.mock import patch
        original=self.s.capture_as_of
        def altered(*a,**kw):
            value=original(*a,**kw);value['candidates'].reverse();return value
        with patch.object(self.s,'capture_as_of',side_effect=altered),self.assertRaises(ContractError):self.inspect()
