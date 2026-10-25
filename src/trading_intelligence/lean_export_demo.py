"""Repeatable invented bundle example; no market or LEAN connection."""
from datetime import datetime,timezone
import json
from pathlib import Path
from . import Entity,Instrument,Listing,AssetKind,DataOrigin,Use
from .market_data import MarketDataStore
from .lean_export import export_bundle

def lean_export_demo(directory):
    out=Path(directory);out.mkdir(parents=True,exist_ok=True)
    at=datetime(2026,1,10,tzinfo=timezone.utc)
    with MarketDataStore(out/'export.sqlite') as store:
        store.register_source('fixture',DataOrigin.SYNTHETIC);store.set_permissions('fixture',known_at=at,uses={Use.STORAGE,Use.RESEARCH})
        store.register_entity(Entity('e','Invented'));store.register_instrument(Instrument('i','e',AssetKind.EQUITY));store.register_listing(Listing('l','i','XNAS','USD'))
        dates=['2026-01-05','2026-01-06']
        for day in dates:
            for kind in ['session','bar']:
                body=dict(kind=kind,listing_id='l',date=day,start=day+'T14:30:00Z',end=day+'T21:00:00Z',currency='USD',values=dict(timezone='America/New_York') if kind=='session' else dict(open='100',high='105',low='95',close='102',volume='50',price_kind='raw'))
                store.import_record(source_id='fixture',record_id=kind+day,revision_id='1',payload=json.dumps(body).encode(),published_at=at,received_at=at,processed_at=at)
        return export_bundle(store,'fixture','l',dates,as_of=at,directory=out/'bundle')
