"""Bounded GET /v1/corporate-actions transport, with declared paper context."""
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from http.client import HTTPException
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, HTTPRedirectHandler, HTTPSHandler, build_opener

from .brokers import BrokerAccount, Environment
from .contracts import ContractError, required, utc

ACTION_URL='https://data.alpaca.markets/v1/corporate-actions'
MAX_BYTES=2_000_000


class ActionReadError(ContractError):
    def __init__(self,code):
        self.code=code
        super().__init__('Corporate action GET failed: '+code+'; response body omitted')


def action_query(symbol,start,end,*,page_token=None,limit=1000):
    import re
    if not isinstance(symbol,str) or not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}',symbol):
        raise ContractError('Explicit supported single symbol required')
    days=[]
    for value in (start,end):
        if not isinstance(value,str):raise ContractError('Canonical process dates required')
        day=date.fromisoformat(value)
        if day.isoformat()!=value:raise ContractError('Canonical process dates required')
        days.append(day)
    if not 0<=(days[1]-days[0]).days<=365 or type(limit) is not int or not 1<=limit<=1000:
        raise ContractError('Bounded process range and page limit required')
    query=dict(symbols=symbol,start=start,end=end,region='us',data_quality='all',sort='asc',limit=str(limit))
    # Deliberately no type filter: unsupported actions must remain visible.
    if page_token is not None:
        if not isinstance(page_token,str) or not 1<=len(page_token)<=2048 or any(not 33<=ord(c)<=126 for c in page_token):
            raise ContractError('Invalid bounded action pagination token')
        query['page_token']=page_token
    return query


@dataclass(frozen=True)
class ActionRead:
    payload:bytes=field(repr=False)
    received_at:datetime
    route:BrokerAccount
    query:dict
    source_url:str=field(repr=False)

    def __post_init__(self):
        if not isinstance(self.route,BrokerAccount) or self.route.broker_id!='alpaca' or self.route.environment!=Environment.PAPER:
            raise ContractError('Explicit paper action context required')
        q=action_query(self.query['symbols'],self.query['start'],self.query['end'],
            page_token=self.query.get('page_token'),limit=int(self.query['limit']))
        if q!=self.query or self.source_url!=ACTION_URL+'?'+urlencode(q):raise ContractError('Action endpoint/query mismatch')
        if not isinstance(self.payload,bytes) or not 0<len(self.payload)<=MAX_BYTES:raise ContractError('Bounded original action response required')
        utc(self.received_at)

    @property
    def provenance(self):return dict(method='GET',endpoint=ACTION_URL,query=self.query,route=asdict(self.route))


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class AlpacaActionsReader:
    def __init__(self,route,key,secret,*,clock=None,opener=None,timeout=10):
        if not isinstance(route,BrokerAccount) or route.broker_id!='alpaca' or route.environment!=Environment.PAPER:
            raise ContractError('Explicit paper route required')
        for value in (key,secret):
            required(value,'credential')
            if any(not 33<=ord(c)<=126 for c in value):raise ContractError('Invalid credential header characters')
        if type(timeout) not in (int,float) or not 0<timeout<=30:raise ContractError('Bounded positive timeout required')
        self._route=route;self._key=key;self._secret=secret;self._clock=clock or (lambda:datetime.now(timezone.utc))
        self._opener=opener or build_opener(_NoRedirect(),HTTPSHandler(context=ssl.create_default_context()))
        self._timeout=timeout

    def __repr__(self):return '<AlpacaActionsReader GET /v1/corporate-actions>'

    def read(self,symbol,start,end,*,page_token=None,limit=1000):
        query=action_query(symbol,start,end,page_token=page_token,limit=limit);url=ACTION_URL+'?'+urlencode(query)
        request=Request(url,method='GET',headers={'APCA-API-KEY-ID':self._key,'APCA-API-SECRET-KEY':self._secret,
            'Accept':'application/json','Accept-Encoding':'identity'})
        try:
            with self._opener.open(request,timeout=self._timeout) as response:
                if response.status!=200 or response.geturl()!=url:raise ActionReadError('unexpected_response')
                if response.headers.get('Content-Type','').split(';',1)[0].strip().lower()!='application/json' or response.headers.get('Content-Encoding','identity').lower() not in ('','identity'):
                    raise ActionReadError('unexpected_media_or_encoding')
                payload=response.read(MAX_BYTES+1)
                if len(payload)>MAX_BYTES:raise ActionReadError('response_size_limit')
        except ActionReadError:raise
        except HTTPError as error:
            code='http_'+str(error.code) if type(error.code) is int and 100<=error.code<=599 else 'http_unknown'
            error.close();raise ActionReadError(code) from None
        except (URLError,TimeoutError,OSError,HTTPException,UnicodeError,ValueError):
            raise ActionReadError('transport_error') from None
        return ActionRead(payload,self._clock(),self._route,query,url)
