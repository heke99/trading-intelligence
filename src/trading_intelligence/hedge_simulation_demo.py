"""Part 4: deterministic end-to-end synthetic lifecycle/restart proof."""
from datetime import datetime,timedelta
import json
from pathlib import Path
from .hedge_demo import hedge_demo
from .hedge_simulation import HedgeSimulationStore


def hedge_simulation_demo(directory):
    root=Path(directory)
    seed=hedge_demo(root/'research')
    search=seed['search']
    when=datetime.fromisoformat(search['available_at'].replace('Z','+00:00'))+timedelta(seconds=10)
    database=root/'research'/'opportunity'/'analysis'/'event-intake'/'events.sqlite3'
    with HedgeSimulationStore(database,clock=lambda:when) as store:
        reservation=store.reserve('synthetic-reservation',search['search_id'],search['result']['best_feasible_hedge_id'])
        intent=store.create_intent('synthetic-intent',reservation['reservation_id'])
        controls=dict(route=intent['route'],mode='active',observed_at=when.isoformat(),
            expires_at=(when+timedelta(seconds=20)).isoformat(),max_contracts=3,
            allowed_contract_ids=[intent['contract_id']],policy_version='synthetic-controls-v1')
        evidence=store.ingest(source_id='synthetic-facilities',record_id='synthetic-simulation-controls',revision_id='1',
            payload=json.dumps(controls,sort_keys=True).encode(),published_at=when,received_at=when)
        store.record_controls('synthetic-controls',evidence)
        claim=store.claim_dispatch(intent['intent_id'])
        accepted=store.inject(intent['intent_id'],'accepted','accepted')
        partial=store.inject(intent['intent_id'],'partial','fill',cumulative_filled=1,fill_price=intent['limit_price'])
        unknown=store.inject(intent['intent_id'],'unknown','unknown')
    # Fresh connection is required before retry; it must return the exact claim.
    with HedgeSimulationStore(database,clock=lambda:when) as store:
        retry=store.claim_dispatch(intent['intent_id'])
        cancelled=store.inject(intent['intent_id'],'cancelled','cancelled')
        late=store.inject(intent['intent_id'],'late','fill',cumulative_filled=3,fill_price=intent['limit_price'])
        state=store.simulation_state(intent['intent_id'])
        if claim!=retry or state['simulated_dispatch_count']!=1 or state['signed_filled']!=-3:
            raise RuntimeError('Synthetic lifecycle proof failed')
        result=dict(origin='synthetic_fixture',intent=intent,dispatch_claim=claim,accepted=accepted,
            partial_fill=partial,unknown_status=unknown,cancelled=cancelled,late_fill=late,
            final_state=state,restart_preserved_claim=retry==claim,network_requests=0,
            broker_orders_sent=0,strategy_performance_assessed=False,live_trading=False)
    (root/'report.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    return result
