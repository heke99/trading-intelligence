"""Invented quotes/outcomes/account state applied to an invented event card."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from .event_analysis_demo import event_analysis_demo
from .event_opportunity import EventOpportunityStore


def opportunity_demo(directory):
    root=Path(directory)
    event_analysis_demo(root/'analysis')
    # The scenario demo's initial card predates its correction and remains an
    # immutable sensitivity input. This is a declared historical synthetic proof.
    with EventOpportunityStore(root/'analysis'/'event-intake'/'events.sqlite3') as store:
        row=store.db.execute('SELECT analysis_id,body_json FROM event_analyses ORDER BY available_at LIMIT 1').fetchone()
        analysis=json.loads(row['body_json'])
        cutoff=datetime.fromisoformat(analysis['available_at'].replace('Z','+00:00'))
        now=[cutoff]
        store._event_clock=lambda:now[0]
        listing=analysis['output']['scenarios'][0]['listing_id']
        inputs=dict(listing_id=listing,currency='USD',quote_at=cutoff.isoformat(),
            valid_until=(cutoff+timedelta(seconds=60)).isoformat(),bid='99',ask='101',quantity='10',
            entry_fee_per_unit='0.1',exit_fee_per_unit='0.1',slippage_per_unit_per_leg='0.2',
            exit_half_spread='0.4',borrow_cost_per_unit='0.5',pre_event_reference=None,
            scenario_exit_mids={s['scenario_id']:('90' if s['economic_direction']=='adverse' else '100') for s in analysis['output']['scenarios']},
            scenario_exit_at={s['scenario_id']:(cutoff+timedelta(days=7)).isoformat() for s in analysis['output']['scenarios']},
            portfolio=dict(broker='invented',connection='offline',account='synthetic',environment='paper',
                observed_at=cutoff.isoformat(),valid_until=(cutoff+timedelta(minutes=5)).isoformat(),
                position_units='20',pending_buy_units='0',pending_sell_units='0'))
        evidence=store.ingest(source_id='synthetic-facilities',record_id='invented-price-sensitivity',
            revision_id='1',payload=json.dumps(inputs,sort_keys=True).encode(),published_at=cutoff,received_at=cutoff)
        now[0]+=timedelta(seconds=1)
        card=store.assess('invented-opportunity',analysis['analysis_id'],evidence,as_of=cutoff)
        result=dict(origin='synthetic_fixture',assessment=card,network_requests=0,orders_sent=0,live_trading=False)
    (root/'report.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    return result
