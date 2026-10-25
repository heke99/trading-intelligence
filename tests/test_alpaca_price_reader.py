"""Injected GET reader tests; no real Alpaca access."""
from datetime import datetime,timezone
from http.client import IncompleteRead
from io import BytesIO
from urllib.error import HTTPError,URLError
import unittest

from trading_intelligence.alpaca_price_reader import AlpacaPriceReader,PriceReadError,PriceRead,PRICE_URL,price_query
from trading_intelligence.brokers import BrokerAccount,Environment

T=datetime(2026,1,10,tzinfo=timezone.utc)
ROUTE=BrokerAccount('alpaca','paper-connection','paper-account',Environment.PAPER)

class Response:
    status=200
    def __init__(self,url,payload=b'{"bars":{},"next_page_token":null}',headers=None):self.url=url;self.payload=payload;self.headers=headers or {'Content-Type':'application/json'}
    def __enter__(self):return self
    def __exit__(self,*_):pass
    def geturl(self):return self.url
    def read(self,size):return self.payload[:size]

class Opener:
    def __init__(self,mutate=None,error=None):self.requests=[];self.mutate=mutate;self.error=error
    def open(self,request,timeout):
        self.requests.append(request)
        if self.error:raise self.error
        r=Response(request.full_url)
        if self.mutate:self.mutate(r)
        return r

class PriceReaderTests(unittest.TestCase):
    def test_fixed_get_query_and_paper_context(self):
        o=Opener();r=AlpacaPriceReader(ROUTE,'KEY','SECRET',opener=o,clock=lambda:T).read(['DEMO'],'2026-01-05','2026-01-06')
        self.assertEqual(o.requests[0].method,'GET');self.assertEqual(r.query['asof'],'-');self.assertEqual(r.query['adjustment'],'raw')
        self.assertEqual(r.query['start'],'2026-01-05T05:00:00.000000Z');self.assertEqual(r.query['end'],'2026-01-07T04:59:59.999999Z')
        self.assertEqual(r.route,ROUTE);self.assertNotIn('SECRET',repr(r))

    def test_dst_and_token_encoding(self):
        q=price_query(['Z','A'],'2026-07-01','2026-07-01',page_token='a+b/=')
        self.assertEqual(q['symbols'],'A,Z');self.assertEqual(q['start'],'2026-07-01T04:00:00.000000Z')
        self.assertEqual(q['page_token'],'a+b/=')

    def test_invalid_request_input(self):
        for args in [([], '2026-01-01','2026-01-01'),(['a'],'2026-01-01','2026-01-01'),(['A','A'],'2026-01-01','2026-01-01'),(['A'],'20260101','2026-01-01'),(['A'],'2026-01-02','2026-01-01'),(['A'],'2025-01-01','2026-01-02')]:
            with self.subTest(args=args),self.assertRaises(PriceReadError):price_query(*args)
        for kw in [dict(feed='boats'),dict(limit=True),dict(limit=10001),dict(page_token='bad\n'),dict(page_token='x'*2049)]:
            with self.subTest(kw=kw),self.assertRaises(PriceReadError):price_query(['A'],'2026-01-01','2026-01-01',**kw)

    def test_route_credentials_timeout_validation(self):
        for route,key,secret,kw in [(BrokerAccount('alpaca','c','a',Environment.LIVE),'K','S',{}),(ROUTE,'K\n','S',{}),(ROUTE,'K','S',dict(timeout=float('nan'))),(ROUTE,'K','S',dict(timeout=True))]:
            with self.assertRaises(ContractError):AlpacaPriceReader(route,key,secret,**kw)

    def test_wrong_redirect_status_encoding_media(self):
        mutations=[lambda r:setattr(r,'url','https://evil.invalid/'),lambda r:setattr(r,'status',302),lambda r:setattr(r,'headers',{'Content-Type':'text/html'}),lambda r:setattr(r,'headers',{'Content-Type':'application/json','Content-Encoding':'gzip'})]
        for mutate in mutations:
            with self.assertRaises(PriceReadError):AlpacaPriceReader(ROUTE,'K','S',opener=Opener(mutate)).read(['A'],'2026-01-01','2026-01-01')

    def test_http_and_network_error_details_hidden(self):
        for error in [HTTPError(PRICE_URL,403,'SECRET',{},BytesIO(b'SECRET')),URLError('SECRET'),IncompleteRead(b'SECRET',100)]:
            with self.assertRaises(PriceReadError) as caught:AlpacaPriceReader(ROUTE,'K','S',opener=Opener(error=error)).read(['A'],'2026-01-01','2026-01-01')
            self.assertNotIn('SECRET',str(caught.exception))

    def test_byte_limit_and_empty_body(self):
        for payload,max_bytes in [(b'x'*11,10),(b'',10)]:
            with self.assertRaises(PriceReadError):AlpacaPriceReader(ROUTE,'K','S',opener=Opener(lambda r:setattr(r,'payload',payload))).read(['A'],'2026-01-01','2026-01-01',max_bytes=max_bytes)
        with self.assertRaises(PriceReadError):AlpacaPriceReader(ROUTE,'K','S').read(['A'],'2026-01-01','2026-01-01',max_bytes=True)

from trading_intelligence.contracts import ContractError
