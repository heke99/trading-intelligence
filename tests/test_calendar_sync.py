from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
import unittest
from trading_intelligence.alpaca_calendar import AlpacaCalendarStore
from trading_intelligence.alpaca_calendar_reader import CalendarRead, PAPER_CALENDAR_URL, calendar_query
from trading_intelligence.brokers import BrokerAccount, Environment
from trading_intelligence.calendar_sync import sync_calendar
from trading_intelligence.contracts import DataOrigin, Use, ContractError, RecordConflict, UseNotAllowed

T=datetime(2026,1,7,tzinfo=timezone.utc)

class Reader:
    def __init__(self, route): self.route=route;self.calls=0
    def read(self,start,end):
        self.calls+=1
        return CalendarRead(b'[{"date":"2026-01-06","open":"09:30","close":"16:00"}]',T,
            PAPER_CALENDAR_URL+'?'+urlencode(calendar_query(start,end)),self.route,start,end)

class CalendarSyncTests(unittest.TestCase):
    def setUp(self):
        self.s=AlpacaCalendarStore(':memory:');self.addCleanup(self.s.close)
        self.s.register_source('provider',DataOrigin.PROVIDER)
        self.s.set_permissions('provider',known_at=T-timedelta(days=1),uses={Use.STORAGE,Use.RESEARCH})
        self.route=BrokerAccount('alpaca','connection','declared-account',Environment.PAPER)
        self.reader=Reader(self.route)
    def sync(self,**changes):
        args=dict(source_id='provider',import_id='calendar',route=self.route,start_date='2026-01-06',
                  end_date='2026-01-06',venue='XNYS',reader=self.reader,clock=lambda:T+timedelta(seconds=1))
        args.update(changes);return sync_calendar(self.s,**args)
    def test_sync_and_retry_preserve_declared_get_without_refetch(self):
        result=self.sync();self.assertEqual(result,self.sync());self.assertEqual(self.reader.calls,1)
        self.assertEqual(result['capture_origin'],'declared_http_get')
        self.assertFalse(result['authenticated_account_verified'])
        self.assertIsNone(result['candidates'][0]['published_at'])
    def test_mismatched_route_or_retry_scope_is_blocked(self):
        other=BrokerAccount('alpaca','other','other-account',Environment.PAPER)
        with self.assertRaises(ContractError):self.sync(reader=Reader(other))
        self.sync()
        with self.assertRaises(RecordConflict):self.sync(route=other)
        with self.assertRaises(RecordConflict):self.sync(venue='XNAS')
    def test_missing_permissions_and_synthetic_source_do_not_fetch(self):
        with self.assertRaises(UseNotAllowed):self.sync(source_id='unknown')
        self.s.register_source('fixture',DataOrigin.SYNTHETIC)
        self.s.set_permissions('fixture',known_at=T-timedelta(days=1),uses={Use.STORAGE,Use.RESEARCH})
        with self.assertRaises(ContractError):self.sync(source_id='fixture')
        self.assertEqual(self.reader.calls,0)
    def test_pending_transaction_is_preserved(self):
        self.s.db.execute("INSERT INTO entities VALUES ('pending','Pending')")
        with self.assertRaises(ContractError):self.sync()
        self.assertTrue(self.s.db.in_transaction);self.assertEqual(self.reader.calls,0)
        self.s.db.rollback()
