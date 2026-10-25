"""Bounded GET-only daily raw equity bars, with explicit symbol mapping disabled."""
from dataclasses import dataclass, field
from datetime import date,datetime,time,timezone
from http.client import HTTPException
import re
import ssl
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
from urllib.request import Request,HTTPRedirectHandler,HTTPSHandler,build_opener
from zoneinfo import ZoneInfo

from .brokers import BrokerAccount,Environment
from .contracts import ContractError,required,utc

PRICE_URL='https://data.alpaca.markets/v2/stocks/bars'
MAX_PRICE_BYTES=2_000_000

class PriceReadError(ContractError):
    pass


def price_query(symbols,start_date,end_date,*,feed='iex',page_token=None,limit=1000):
    if not isinstance(symbols,(list,tuple)) or not 1<=len(symbols)<=50:
        raise PriceReadError('Explicit list of 1 to 50 symbols required')
    for symbol in symbols:
        if not isinstance(symbol,str) or not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,14}',symbol):
            raise PriceReadError('Unsupported exact symbol')
    if len(set(symbols)) != len(symbols):
        raise PriceReadError('Duplicate symbols are not permitted')
    days=[]
    for value in (start_date,end_date):
        if not isinstance(value,str):raise PriceReadError('Canonical date strings required')
        try: day=date.fromisoformat(value)
        except ValueError:raise PriceReadError('Invalid date') from None
        if day.isoformat()!=value:raise PriceReadError('Canonical date strings required')
        days.append(day)
    if not 0<=(days[1]-days[0]).days<=365:
        raise PriceReadError('Require at most 366 ordered inclusive dates')
    if feed not in {'iex','sip'} or type(limit) is not int or not 1<=limit<=10000:
        raise PriceReadError('Explicit IEX/SIP and bounded integer page limit required')
    zone=ZoneInfo('America/New_York')
    query=dict(symbols=','.join(sorted(symbols)),timeframe='1Day',start=utc(datetime.combine(days[0],time.min,zone)),
               end=utc(datetime.combine(days[1],time.max,zone)),feed=feed,adjustment='raw',asof='-',currency='USD',sort='asc',limit=str(limit))
    if page_token is not None:
        if not isinstance(page_token,str) or not 1<=len(page_token)<=2048 or any(not 33<=ord(c)<=126 for c in page_token):
            raise PriceReadError('Invalid bounded pagination token')
        query['page_token']=page_token
    return query


@dataclass(frozen=True)
class PriceRead:
    payload:bytes=field(repr=False)
    received_at:datetime
    source_url:str=field(repr=False)
    route:BrokerAccount
    symbols:tuple
    start_date:str
    end_date:str
    feed:str
    page_token:str|None=None
    limit:int=1000

    def __post_init__(self):
        if not isinstance(self.route,BrokerAccount) or self.route.broker_id!='alpaca' or self.route.environment!=Environment.PAPER:
            raise PriceReadError('Explicit Alpaca paper route required')
        if self.source_url!=PRICE_URL+'?'+urlencode(self.query):raise PriceReadError('Unexpected bars endpoint/query')
        if not isinstance(self.payload,bytes) or not 0<len(self.payload)<=MAX_PRICE_BYTES:raise PriceReadError('Bounded nonempty original payload required')
        utc(self.received_at)

    @property
    def query(self):
        return price_query(self.symbols,self.start_date,self.end_date,feed=self.feed,page_token=self.page_token,limit=self.limit)

    @property
    def provenance(self):
        return dict(endpoint=PRICE_URL,method='GET',query=self.query,route=dict(broker_id=self.route.broker_id,connection_id=self.route.connection_id,account_id=self.route.account_id,environment=self.route.environment.value))

class _NoPriceRedirect(HTTPRedirectHandler):
    def redirect_request(self,*_args,**_kwargs):return None

class AlpacaPriceReader:
    def __init__(self,route,key_id,secret_key,*,timeout=10,clock=None,opener=None):
        if not isinstance(route,BrokerAccount) or route.broker_id!='alpaca' or route.environment!=Environment.PAPER:
            raise PriceReadError('Explicit Alpaca paper route required')
        for credential in (key_id,secret_key):
            required(credential,'credential')
            if any(not 33<=ord(c)<=126 for c in credential):raise PriceReadError('Invalid credential header characters')
        if type(timeout) not in (int,float) or not 0<timeout<=30:raise PriceReadError('Bounded positive timeout required')
        self._route=route;self._key_id=key_id;self._secret_key=secret_key;self._timeout=timeout
        self._clock=clock or (lambda:datetime.now(timezone.utc))
        self._opener=opener or build_opener(_NoPriceRedirect(),HTTPSHandler(context=ssl.create_default_context()))

    def __repr__(self):return '<AlpacaPriceReader GET daily raw bars>'

    def read(self,symbols,start_date,end_date,*,feed='iex',page_token=None,limit=1000,max_bytes=MAX_PRICE_BYTES):
        if type(max_bytes) is not int or not 1<=max_bytes<=MAX_PRICE_BYTES:raise PriceReadError('Bounded response byte limit required')
        query=price_query(symbols,start_date,end_date,feed=feed,page_token=page_token,limit=limit)
        url=PRICE_URL+'?'+urlencode(query)
        request=Request(url,method='GET',headers={'APCA-API-KEY-ID':self._key_id,'APCA-API-SECRET-KEY':self._secret_key,'Accept':'application/json','Accept-Encoding':'identity'})
        try:
            with self._opener.open(request,timeout=self._timeout) as response:
                if response.status!=200 or response.geturl()!=url:raise PriceReadError('Unexpected bars response endpoint or status')
                if response.headers.get('Content-Type','').split(';',1)[0].strip().lower()!='application/json' or response.headers.get('Content-Encoding','identity').strip().lower() not in ('','identity'):
                    raise PriceReadError('Uncompressed JSON bars response required')
                payload=response.read(max_bytes+1)
                if len(payload)>max_bytes:raise PriceReadError('Bars response exceeds bounded byte limit')
        except PriceReadError:raise
        except HTTPError as exc:
            code=exc.code if type(exc.code) is int and 100<=exc.code<=599 else 'unknown';exc.close()
            raise PriceReadError(f'Bars HTTP failure ({code}); response details omitted') from None
        except (URLError,TimeoutError,OSError,HTTPException,UnicodeError,ValueError):
            raise PriceReadError('Bars connection failed; no automatic retry or failover') from None
        return PriceRead(payload,self._clock(),url,self._route,tuple(sorted(symbols)),start_date,end_date,feed,page_token,limit)
