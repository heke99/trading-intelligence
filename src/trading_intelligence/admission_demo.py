"""Synthetic calendar and review-gate demo; no real source approval or requests."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from .contracts import AssetKind, DataOrigin, Entity, Instrument, Listing, Use
from .data_admission import AXES, DataAdmissionStore


def admission_demo(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    received = datetime(2026, 1, 10, tzinfo=timezone.utc)
    available = received + timedelta(seconds=1)
    reviewed = received + timedelta(seconds=2)
    clock = [reviewed]
    with DataAdmissionStore(directory/'admission.sqlite3', clock=lambda: clock[0]) as store:
        source='synthetic-admission'
        store.register_source(source, DataOrigin.SYNTHETIC)
        store.set_permissions(source, known_at=received-timedelta(days=30),uses={Use.STORAGE,Use.RESEARCH})
        store.register_entity(Entity('demo-issuer','Invented admission fixture'))
        store.register_instrument(Instrument('demo-share','demo-issuer',AssetKind.EQUITY))
        store.register_listing(Listing('demo-listing','demo-share','XNYS','USD'))
        bars=store.import_bars(source_id=source,import_id='bars',
            payload=b'{"bars":{"DEMO":[{"t":"2026-01-05T05:00:00Z","o":100,"h":101,"l":99,"c":100,"v":10}]},"next_page_token":null}',
            received_at=received,processed_at=available,symbol_listings={'DEMO':'demo-listing'},
            feed='iex',timeframe='1Day',adjustment='raw',market_timezone='America/New_York')
        calendar=store.import_calendar(source_id=source,import_id='calendar',
            payload=b'[{"date":"2026-01-05","open":"09:30","close":"13:00"}]',
            received_at=received,processed_at=available,start_date='2026-01-05',end_date='2026-01-05')
        scope=dict(bar_import_id='bars',calendar_import_id='calendar',bar_raw_sha=bars['raw_sha'],
                   calendar_raw_sha=calendar['raw_sha'],listing_id='demo-listing',venue='XNYS',
                   start_date='2026-01-05',end_date='2026-01-05',feed='iex')
        evidence=store.ingest(source_id=source,record_id='review-fixture',revision_id='1',
            payload=b'Invented review assertions for a synthetic validation test only',
            published_at=received,received_at=received)
        missing=store.assess(source_id=source,scope=scope,intended_use='forward_observation',as_of=reviewed)
        for purpose,basis in [('synthetic_validation','synthetic_fixture_only'),
                              ('historical_replay','documented_publication_vintage')]:
            for axis in AXES:
                kwargs=dict(temporal_basis=basis) if axis=='temporal' else {}
                if axis=='rights': kwargs['declared_rights']=['storage','research']
                store.record_review(review_id=purpose+'-'+axis,source_id=source,axis=axis,purpose=purpose,
                    scope=scope,expires_at=received+timedelta(days=1),reviewer='synthetic-reviewer',
                    evidence_refs=[evidence],decision='allow',**kwargs)
        fixture=store.assess(source_id=source,scope=scope,intended_use='synthetic_validation',as_of=reviewed)
        historical=store.assess(source_id=source,scope=scope,intended_use='historical_replay',as_of=reviewed)
        clock[0]=received+timedelta(seconds=3)
        store.record_review(review_id='fixture-rights-revoked',source_id=source,axis='rights',
            purpose='synthetic_validation',scope=scope,expires_at=received+timedelta(days=1),
            reviewer='synthetic-reviewer',evidence_refs=[evidence],decision='deny',declared_rights=['storage','research'])
        revoked=store.assess(source_id=source,scope=scope,intended_use='synthetic_validation',as_of=reviewed)
        result=dict(origin=DataOrigin.SYNTHETIC.value,calendar=calendar,
                    missing_reviews=missing,synthetic_validation=fixture,historical_replay=historical,
                    current_denial=revoked,market_snapshots=store.db.execute('SELECT count(*) FROM market_snapshots').fetchone()[0],
                    training_ready=False,live_trading=False,orders_sent=0)
    (directory/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result
