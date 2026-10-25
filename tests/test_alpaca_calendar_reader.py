"""Fake calendar HTTP transport only; no credentials or authenticated claims."""
from dataclasses import replace
from datetime import datetime, timezone
import io
import unittest
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

from trading_intelligence.alpaca_calendar_reader import (
    AlpacaCalendarReader, CalendarRead, CalendarReadError, MAX_CALENDAR_BYTES,
    PAPER_CALENDAR_URL, _NoCalendarRedirect, calendar_query)
from trading_intelligence.brokers import BrokerAccount, Environment
from trading_intelligence.contracts import ContractError

ROUTE=BrokerAccount('alpaca','fixture-connection','fixture-account',Environment.PAPER)
NOW=datetime(2026,1,8,22,tzinfo=timezone.utc)
KEY='fixture-key-sensitive'; SECRET='fixture-secret-sensitive'


class Response:
    status=200
    headers={'Content-Type':'application/json'}
    def __init__(self,payload=b'[]',url=None):self.payload=payload;self.url=url
    def __enter__(self):return self
    def __exit__(self,*_):pass
    def geturl(self):return self.url
    def read(self,limit):return self.payload[:limit]

class Opener:
    def __init__(self,response=None,error=None):self.response=response or Response();self.error=error;self.calls=[]
    def open(self,request,*,timeout):
        self.calls.append((request,timeout))
        if self.error:raise self.error
        if self.response.url is None:self.response.url=request.full_url
        return self.response


class CalendarReaderTests(unittest.TestCase):
    def reader(self,opener=None,**changes):
        args=dict(route=ROUTE,key_id=KEY,secret_key=SECRET,clock=lambda:NOW,opener=opener or Opener())
        args.update(changes);return AlpacaCalendarReader(**args)

    def test_exact_get_query_headers_and_raw_capture(self):
        raw=b'[ {"date":"2026-01-05","open":"09:30","close":"16:00"} ]'
        opener=Opener(Response(raw));r=self.reader(opener).read('2026-01-05','2026-01-08')
        request,timeout=opener.calls[0]
        self.assertEqual(request.get_method(),'GET');self.assertIsNone(request.data)
        self.assertEqual(urlsplit(request.full_url).path,'/v2/calendar')
        self.assertEqual(parse_qs(urlsplit(request.full_url).query),{'start':['2026-01-05'],'end':['2026-01-08'],'date_type':['TRADING']})
        self.assertEqual(request.get_header('Apca-api-key-id'),KEY)
        self.assertEqual(request.get_header('Apca-api-secret-key'),SECRET)
        self.assertEqual(r.payload,raw);self.assertEqual(r.received_at,NOW);self.assertEqual(r.route,ROUTE)
        self.assertEqual(r.request_query,calendar_query('2026-01-05','2026-01-08'))
        self.assertEqual(timeout,10)
        self.assertEqual(r.endpoint,PAPER_CALENDAR_URL)
        self.assertEqual(r.provenance,{'endpoint':PAPER_CALENDAR_URL,'method':'GET','query':r.query,'route':{'broker_id':'alpaca','connection_id':ROUTE.connection_id,'account_id':ROUTE.account_id,'environment':'paper'}})
        changed=r.query;changed['date_type']='SETTLEMENT'
        self.assertEqual(r.query['date_type'],'TRADING')

    def test_receipt_clock_runs_after_response_read(self):
        seen=[]
        class OrderedResponse(Response):
            def read(self,limit):seen.append('read');return super().read(limit)
        def clock():seen.append('clock');return NOW
        self.reader(Opener(OrderedResponse()),clock=clock).read('2026-01-05','2026-01-05')
        self.assertEqual(seen,['read','clock'])

    def test_no_route_substitution_or_live(self):
        for route in (replace(ROUTE,broker_id='other'),replace(ROUTE,environment=Environment.LIVE),None):
            with self.subTest(route=route),self.assertRaises(CalendarReadError):self.reader(route=route)

    def test_canonical_bounded_dates_before_network(self):
        opener=Opener();reader=self.reader(opener)
        for start,end in [('20260105','2026-01-06'),('2026-01-06','2026-01-05'),('2026-01-01','2027-01-02'),('1969-12-31','1970-01-01'),('2029-12-31','2030-01-01'),(None,'2026-01-01'),('https://other.test','2026-01-01')]:
            with self.subTest(start=start,end=end),self.assertRaises(CalendarReadError):reader.read(start,end)
        self.assertFalse(opener.calls)
        self.assertEqual(calendar_query('2026-01-01','2027-01-01')['date_type'],'TRADING')

    def test_invalid_credentials_and_timeouts(self):
        for value in ('','x\r\ny','unicode-å','x\x7f','with space'):
            with self.subTest(value=value),self.assertRaises(ContractError):self.reader(key_id=value)
        for value in (True,0,-1,float('inf'),float('nan'),31,'10'):
            with self.subTest(value=value),self.assertRaises(CalendarReadError):self.reader(timeout=value)

    def test_redirect_handler_and_unexpected_location(self):
        self.assertIsNone(_NoCalendarRedirect().redirect_request(Request(PAPER_CALENDAR_URL),None,302,'m',{},'https://other.test'))
        for url in ('https://other.test/calendar',PAPER_CALENDAR_URL, 'https://api.alpaca.markets/v2/calendar'):
            with self.subTest(url=url),self.assertRaises(CalendarReadError):self.reader(Opener(Response(url=url))).read('2026-01-05','2026-01-05')

    def test_status_media_and_encoding_fail_closed(self):
        for status,headers in [(302,{'Content-Type':'application/json'}),(500,{'Content-Type':'application/json'}),(200,{'Content-Type':'text/html'}),(200,{'Content-Type':'application/json','Content-Encoding':'gzip'})]:
            response=Response();response.status=status;response.headers=headers
            with self.subTest(status=status,headers=headers),self.assertRaises(CalendarReadError):self.reader(Opener(response)).read('2026-01-05','2026-01-05')

    def test_payload_size_and_naive_clock(self):
        for payload in (b'',b'x'*(MAX_CALENDAR_BYTES+1)):
            with self.subTest(size=len(payload)),self.assertRaises(CalendarReadError):self.reader(Opener(Response(payload))).read('2026-01-05','2026-01-05')
        with self.assertRaises(ContractError):self.reader(clock=lambda:datetime(2026,1,1)).read('2026-01-05','2026-01-05')

    def test_http_and_network_errors_hide_credentials(self):
        for error in (HTTPError(PAPER_CALENDAR_URL,401,KEY+SECRET,{'secret':SECRET},io.BytesIO(SECRET.encode())), URLError(KEY+SECRET),TimeoutError(KEY+SECRET),OSError(KEY+SECRET)):
            opener=Opener(error=error)
            with self.subTest(error=type(error)),self.assertRaises(CalendarReadError) as caught:
                self.reader(opener).read('2026-01-05','2026-01-05')
            self.assertNotIn(KEY,str(caught.exception));self.assertNotIn(SECRET,str(caught.exception))
            self.assertEqual(len(opener.calls),1)

    def test_repr_and_result_endpoint_validation(self):
        reader=self.reader();self.assertNotIn(KEY,repr(reader));self.assertNotIn(SECRET,repr(reader))
        result=reader.read('2026-01-05','2026-01-05')
        self.assertNotIn('payload=',repr(result))
        with self.assertRaises(CalendarReadError):replace(result,source_url='https://other.test')
        with self.assertRaises(CalendarReadError):replace(result,end_date='2026-01-04')
