"""Repeatable synthetic vendor-staging and bounded replay demonstration."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from .alpaca_market import AlpacaMarketStore
from .contracts import AssetKind, DataOrigin, Entity, Instrument, Listing, Use
from .market_replay import replay_dates


def market_pipeline_demo(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    received = datetime(2026, 1, 10, 22, tzinfo=timezone.utc)
    processed = received + timedelta(seconds=1)
    dates = ['2026-01-05', '2026-01-06', '2026-01-07']
    with AlpacaMarketStore(directory / 'market.sqlite3') as store:
        for source in ('synthetic-vendor', 'synthetic-normalized'):
            store.register_source(source, DataOrigin.SYNTHETIC)
            store.set_permissions(source, known_at=received-timedelta(days=30), uses={Use.STORAGE, Use.RESEARCH})
        store.register_entity(Entity('demo-issuer', 'Invented market example'))
        store.register_instrument(Instrument('demo-share', 'demo-issuer', AssetKind.EQUITY))
        store.register_listing(Listing('demo-listing', 'demo-share', 'XNAS', 'USD'))
        vendor = {'bars': {'DEMO': [
            {'t':'2026-01-06T05:00:00Z','o':100,'h':105,'l':95,'c':102,'v':50},
            {'t':'2026-01-06T05:00:00Z','o':100,'h':105,'l':110,'c':102,'v':50}]},
            'next_page_token': None}
        capture = store.import_bars(source_id='synthetic-vendor', import_id='demo-capture',
            payload=json.dumps(vendor).encode(), received_at=received, processed_at=processed,
            symbol_listings={'DEMO':'demo-listing'}, feed='iex', timeframe='1Day',
            adjustment='raw', market_timezone='America/New_York')
        # Independent invented normalized records. Staged vendor candidates are
        # never promoted by inventing their missing publication or session data.
        for day in (dates[0], dates[2]):
            for kind in ('session', 'bar'):
                body = dict(kind=kind, listing_id='demo-listing', date=day,
                    start=day+'T14:30:00Z', end=day+'T21:00:00Z', currency='USD',
                    values=({'timezone':'America/New_York'} if kind == 'session' else
                            {'open':'100','high':'105','low':'95','close':'102','volume':'50','price_kind':'raw'}))
                store.import_record(source_id='synthetic-normalized', record_id=kind+day,
                    revision_id='1', payload=json.dumps(body).encode(), published_at=received,
                    received_at=received, processed_at=processed)
        replay = replay_dates(store, 'synthetic-normalized', 'demo-listing', dates, as_of=processed)
        answer = dict(origin=DataOrigin.SYNTHETIC.value, vendor_candidates=len(capture['candidates']),
            quarantined_rows=len(capture['quarantined']), publication_unknown=True,
            vendor_candidates_admitted=0, replay=replay, training_ready=False,
            full_history_verified=False, live_trading=False, orders_sent=0)
    (directory / 'report.json').write_text(json.dumps(answer, indent=2), encoding='utf-8')
    return answer
