"""Invented earthquake revisions and a documented fictional facility; no network."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from .contracts import AssetKind, DataOrigin, Entity, Instrument, Listing, Use
from .event_context import EventContextStore
from .event_sources import EventCapture, USGS_FEEDS


def _payload(when, *, longitude, latitude, magnitude, status, tsunami):
    milliseconds = lambda value: int(value.timestamp() * 1000)
    return json.dumps(dict(type='FeatureCollection', metadata=dict(generated=milliseconds(when), count=1),
        features=[dict(type='Feature', id='invented-earthquake',
            properties=dict(time=milliseconds(when-timedelta(minutes=5)),
                updated=milliseconds(when), type='earthquake', mag=magnitude,
                magType='mw', status=status, tsunami=tsunami,
                place='Invented test region', title='Synthetic event only'),
            geometry=dict(type='Point', coordinates=[longitude, latitude, 12]))]),
        sort_keys=True, separators=(',', ':')).encode()


def event_demo(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    start = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)
    clock = [start]
    first = start + timedelta(minutes=1)
    corrected = start + timedelta(minutes=2)
    with EventContextStore(directory/'events.sqlite3', clock=lambda: clock[0]) as store:
        for source in ('synthetic-events', 'synthetic-facilities'):
            store.register_source(source, DataOrigin.SYNTHETIC)
            store.set_permissions(source, known_at=start-timedelta(days=30),
                                  uses={Use.STORAGE, Use.RESEARCH})
        store.register_entity(Entity('event-demo-company', 'Invented manufacturing company'))
        store.register_instrument(Instrument('event-demo-equity', 'event-demo-company', AssetKind.EQUITY))
        store.register_listing(Listing('event-demo-listing', 'event-demo-equity', 'XNAS', 'USD'))
        evidence = store.ingest(source_id='synthetic-facilities', record_id='invented-facility',
            revision_id='1', payload=b'{"fictional_facility":{"latitude":35,"longitude":139}}',
            published_at=start-timedelta(days=1), received_at=start-timedelta(hours=1))
        store.put_facility(assertion_id='event-demo-facility-v1', facility_id='invented-facility',
            entity_id='event-demo-company', latitude=35.0, longitude=139.0,
            evidence_id=evidence, valid_from=start-timedelta(days=30), known_at=start,
            relationship='operator', listing_id='event-demo-listing')
        clock[0] = first
        one = store.stage(source_id='synthetic-events', import_id='event-demo-initial',
            capture=EventCapture(_payload(first, longitude=139.05, latitude=35.0,
                magnitude=6.8, status='automatic', tsunami=1), first, USGS_FEEDS['all_hour']),
            processed_at=first)
        before = store.context('synthetic-events', 'invented-earthquake', as_of=first, radius_km=50)
        clock[0] = corrected
        two = store.stage(source_id='synthetic-events', import_id='event-demo-corrected',
            capture=EventCapture(_payload(corrected, longitude=10.0, latitude=10.0,
                magnitude=6.1, status='reviewed', tsunami=0), corrected, USGS_FEEDS['all_hour']),
            processed_at=corrected)
        after = store.context('synthetic-events', 'invented-earthquake', as_of=corrected, radius_km=50)
        historical = store.context('synthetic-events', 'invented-earthquake', as_of=first, radius_km=50)
        result = dict(origin=DataOrigin.SYNTHETIC.value, first_capture=one,
            corrected_capture=two, initial_context=before, corrected_context=after,
            historical_context=historical, historical_event_preserved=(
                before['event']['event_version_id'] == historical['event']['event_version_id']),
            network_requests=0, predictive_model_implemented=False, training_ready=False,
            orders_sent=0, live_trading=False)
    (directory/'report.json').write_text(json.dumps(result, indent=2, sort_keys=True)+'\n', encoding='utf-8')
    return result
