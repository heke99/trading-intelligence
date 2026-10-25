"""Two-page injected GET and staging example using only invented synthetic data."""
from datetime import datetime,timezone
import json
from pathlib import Path

from . import AssetKind,DataOrigin,Entity,Instrument,Listing,Use
from .alpaca_market import AlpacaMarketStore
from .alpaca_price_reader import AlpacaPriceReader
from .brokers import BrokerAccount,Environment

T=datetime(2026,1,10,tzinfo=timezone.utc)

class _FixtureResponse:
    status=200
    headers={'Content-Type':'application/json'}
    def __init__(self,url,payload):self.url=url;self.payload=payload
    def geturl(self):return self.url
    def read(self,size):return self.payload[:size]
    def __enter__(self):return self
    def __exit__(self,*_):pass

class _FixtureOpener:
    def __init__(self):self.index=0
    def open(self,request,timeout):
        day='2026-01-05' if self.index==0 else '2026-01-06'
        token='fixture-next' if self.index==0 else None
        self.index+=1
        payload=json.dumps(dict(bars={'DEMO':[dict(t=day+'T05:00:00Z',o=100,h=105,l=95,c=102,v=50)]},next_page_token=token)).encode()
        return _FixtureResponse(request.full_url,payload)


def price_demo(directory):
    """Demonstrate reader and import, without labelling synthetic data provider data."""
    out=Path(directory);out.mkdir(parents=True,exist_ok=True)
    route=BrokerAccount('alpaca','invented-paper-connection','invented-paper-account',Environment.PAPER)
    reader=AlpacaPriceReader(route,'fixture-key','fixture-secret',opener=_FixtureOpener(),clock=lambda:T)
    with AlpacaMarketStore(out/'price-demo.sqlite') as store:
        store.register_source('price-demo',DataOrigin.SYNTHETIC)
        store.set_permissions('price-demo',known_at=T,uses={Use.STORAGE,Use.RESEARCH})
        store.register_entity(Entity('price-demo-issuer','Invented demo issuer'))
        store.register_instrument(Instrument('price-demo-stock','price-demo-issuer',AssetKind.EQUITY))
        store.register_listing(Listing('price-demo-listing','price-demo-stock','XNAS','USD'))
        captures=[];token=None
        for index in range(2):
            read=reader.read(['DEMO'],'2026-01-05','2026-01-06',page_token=token)
            captured=store.import_bars(source_id='price-demo',import_id=f'page-{index}',payload=read.payload,
                received_at=read.received_at,processed_at=T,symbol_listings={'DEMO':'price-demo-listing'},
                feed='iex',timeframe='1Day',adjustment='raw',market_timezone='America/New_York')
            captures.append(dict(import_id=captured['import_id'],raw_sha=captured['raw_sha'],candidate_count=len(captured['candidates']),published_at=captured['candidates'][0]['published_at']))
            token=captured['next_page_token']
        report=dict(origin='synthetic_fixture',injected_get_pages=len(captures),captures=captures,
                    terminal_page_seen=token is None,real_network_access=False,
                    market_admitted=False,training_ready=False,live_trading=False)
        (out/'price-report.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
        return report
