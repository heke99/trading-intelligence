"""Invented split/dividend and exact symbol-rename replay, not investment results."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path

from .contracts import AssetKind, DataOrigin, Entity, Instrument, Listing, Use
from .corporate_replay import corporate_action_replay
from .identity_replay import resolve_schedule
from .market_data import MarketDataStore


def corporate_demo(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    known = datetime(2026, 1, 10, 22, tzinfo=timezone.utc)
    processed = known + timedelta(seconds=1)
    opened = datetime(2026, 1, 1, tzinfo=timezone.utc)
    dates = ['2026-01-05','2026-01-06','2026-01-07','2026-01-08']
    with MarketDataStore(directory / 'corporate.sqlite3') as store:
        store.register_source('synthetic-corporate', DataOrigin.SYNTHETIC)
        store.set_permissions('synthetic-corporate', known_at=opened, uses={Use.STORAGE, Use.RESEARCH})
        store.register_entity(Entity('demo-issuer','Invented corporate example'))
        store.register_instrument(Instrument('demo-share','demo-issuer',AssetKind.EQUITY))
        store.register_listing(Listing('demo-listing','demo-share','XNAS','USD'))
        for day, price in zip(dates, ('100','50','49','49')):
            records = [('session', {'timezone':'America/New_York'}),
                ('bar', dict(open=price,high=price,low=price,close=price,volume='100',price_kind='raw'))]
            if day == dates[1]: records.append(('split', {'new_shares':'2','old_shares':'1'}))
            if day == dates[2]: records.append(('cash_dividend', {'amount':'1','payment_date':dates[3]}))
            for kind, values in records:
                body=dict(kind=kind,listing_id='demo-listing',date=day,start=day+'T14:30:00Z',
                          end=day+'T21:00:00Z',currency='USD',values=values)
                store.import_record(source_id='synthetic-corporate',record_id=kind+day,revision_id='1',
                    payload=json.dumps(body).encode(),published_at=known,received_at=known,processed_at=processed)
        evidence=store.ingest(source_id='synthetic-corporate',record_id='rename',revision_id='1',
            payload=b'{"fixture":"OLD changes to NEW, same listing"}',published_at=known,received_at=known)
        boundary=datetime(2026,1,6,tzinfo=timezone.utc)
        for name,start,end in [('OLD',opened,boundary),('NEW',boundary,None)]:
            store.put_identifier(mapping_id='demo-'+name,provider='synthetic',value=name,
                listing_id='demo-listing',valid_from=start,valid_to=end,known_at=processed,evidence_id=evidence)
        identities=resolve_schedule(store,[dict(date=day,identifier='OLD' if i==0 else 'NEW',
            effective_at=datetime.fromisoformat(day+'T14:30:00+00:00')) for i,day in enumerate(dates)],
            provider='synthetic',as_of=processed)
        ledger=corporate_action_replay(store,'synthetic-corporate','demo-listing',dates,as_of=processed,
            opening_at=opened,initial_cash=Decimal('100'),initial_shares=Decimal('10'),currency='USD',
            dividend_share_basis='post_split',dividend_policy='ordinary_cash_no_withholding')
        answer=dict(origin=DataOrigin.SYNTHETIC.value,identity=identities,valuation=ledger,
                    training_ready=False,live_trading=False,orders_sent=0)
    (directory/'report.json').write_text(json.dumps(answer,indent=2),encoding='utf-8')
    return answer
