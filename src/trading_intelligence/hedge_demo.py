"""Synthetic event -> protected holdings -> futures hedge comparison -> monitoring."""
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path

from .contracts import AssetKind, Entity, Instrument
from .event_opportunity_demo import opportunity_demo
from .futures import FutureContract, FutureProduct, FutureTerms, FuturesMargin, Session, Settlement, TradingSchedule
from .hedge_research import HedgeResearchStore


def hedge_demo(directory):
    root=Path(directory)
    original=opportunity_demo(root/'opportunity')['assessment']
    cutoff=datetime.fromisoformat(original['available_at'].replace('Z','+00:00'))
    clock=[cutoff]
    with HedgeResearchStore(root/'opportunity'/'analysis'/'event-intake'/'events.sqlite3',clock=lambda:clock[0]) as store:
        start,end=cutoff-timedelta(seconds=1),cutoff+timedelta(days=60)
        ref=store.ingest(source_id='synthetic-facilities',record_id='invented-hedge-reference',revision_id='1',
            payload=b'{"synthetic":"cash index futures terms and account margin"}',published_at=start,received_at=start)
        store.register_entity(Entity('invented-index-publisher','Invented index publisher'))
        store.register_instrument(Instrument('invented-index','invented-index-publisher',AssetKind.INDEX))
        store.register_product(FutureProduct('hedge-demo-product','DEMO','XOFF','invented-index','USD','index_points'))
        store.register_contract(FutureContract('hedge-demo-expiry','hedge-demo-product','2026-03'))
        times=dict(valid_from=start,valid_to=end,known_at=start,evidence_id=ref)
        store.put_terms('hedge-demo-expiry',FutureTerms(Decimal('.25'),Decimal('4'),Settlement.CASH,
            cutoff+timedelta(days=30),cutoff+timedelta(days=29)),**times)
        store.put_schedule('hedge-demo-product',TradingSchedule('UTC',(Session(start,end),)),**times)
        store.put_broker_binding('invented','DEMOH26','hedge-demo-expiry','invented-native',**times)
        store.put_margin('invented','synthetic','hedge-demo-expiry',FuturesMargin(Decimal('20'),Decimal('16'),'USD'),**times)
        route=dict(broker='invented',connection='offline',account='synthetic',environment='paper')
        listing=original['result']['listing_id']
        horizon=(cutoff+timedelta(days=7)).isoformat()
        scenarios=[]
        for identity,pnl,hedge,lc,sc,basis in [('crash','-200','-40','50','0',False),
                ('basis-break','-40','20','0','30',True),('rally','200','40','0','60',False)]:
            scenarios.append(dict(scenario_id=identity,horizon_at=horizon,portfolio_pnl=pnl,basis_break=basis,
                hedges={'index':dict(long_pnl_per_contract=hedge,long_adverse_cash_per_contract=lc,short_adverse_cash_per_contract=sc)}))
        raw=dict(inputs=dict(book=dict(book_id='invented-held-book-v1',route=route,currency='USD',market_value='2000',
            gross_notional='2000',risk_factor_id='market:demo',factor_exposure='2000',pending_orders_known=True,pending_orders_clear=True,long_only=True),
            hedge_accounts=[dict(route=route,currency='USD',available_cash='400')],
            candidates=[dict(candidate_id='index',contract_id='hedge-demo-expiry',route=route,currency='USD',
                notional_per_contract='400',risk_factor_id='market:demo',factor_per_contract='400',roundtrip_cost_per_contract='2',
                initial_margin_per_contract='20',stressed_margin_per_contract='40')],scenarios=scenarios),
            policy=dict(policy_id='invented-index-protection',version='1',max_contracts=5,max_gross_notional='4000',
                max_hedge_notional_ratio='1',max_abs_residual_factor='1200',max_worst_loss='140',min_loss_improvement='20',
                max_upside_sacrifice='140',cash_buffer='20',reduction_fractions=['0','.5','1'],reduction_cost_full_book='4'),
            controls=dict(state_observed_at=cutoff.isoformat(),valid_until=(cutoff+timedelta(seconds=60)).isoformat(),
                policy_known_at=cutoff.isoformat(),order_mode='active',hedge_mandate=True,min_rebalance_seconds=30,
                rebalance_band=0,exit_rule='revalidate_then_unwind',protected_listing_ids=[listing],
                holdings=[dict(listing_id=listing,units='20',mid='100',factor_loading='1')],
                hedge_positions={'index':0},hedge_pending_state={'index':'clear'}),
            market_references={'index':dict(broker_identifier='DEMOH26',entry_price='100',price_kind='raw_contract',
                observed_at=cutoff.isoformat(),valid_until=(cutoff+timedelta(seconds=60)).isoformat(),
                exit_prices={'crash':'90','basis-break':'105','rally':'110'})})
        def evidence(identity,body):
            return store.ingest(source_id='synthetic-facilities',record_id=identity,revision_id='1',payload=json.dumps(body,sort_keys=True).encode(),published_at=cutoff,received_at=cutoff)
        inputs_id=evidence('invented-hedge-inputs',raw)
        clock[0]=cutoff+timedelta(seconds=1)
        search=store.search('invented-hedge-search',original['assessment_id'],inputs_id,as_of=cutoff)
        chosen=next(x for x in search['result']['alternatives'] if x['alternative_id']==search['result']['best_feasible_hedge_id'])
        state=dict(snapshot=dict(book_id=raw['inputs']['book']['book_id'],policy_id=raw['policy']['policy_id'],
            protected_units='20',allocated_hedge_contracts=-1,target_contracts=int(chosen['size']),pending_state='clear',
            order_mode='active',observed_at=cutoff.isoformat(),expires_at=(cutoff+timedelta(seconds=60)).isoformat(),
            policy_expires_at=raw['controls']['valid_until'],exit_rule='revalidate_then_unwind',min_rebalance_seconds=30,
            last_rebalance_at=None,rebalance_band=0),route=route,alternative_id=chosen['alternative_id'],policy_version='1')
        state_id=evidence('invented-partial-hedge',state)
        clock[0]=cutoff+timedelta(seconds=2)
        partial=store.monitor('invented-partial-monitor',search['search_id'],state_id,as_of=clock[0])
        orphan=deepcopy(state)
        orphan['snapshot'].update(protected_units='0',allocated_hedge_contracts=-2,order_mode='hard_stop')
        orphan_id=evidence('invented-orphan-hedge',orphan)
        clock[0]=cutoff+timedelta(seconds=3)
        stopped=store.monitor('invented-orphan-monitor',search['search_id'],orphan_id,as_of=clock[0])
        result=dict(origin='synthetic_fixture',search=search,partial_fill_review=partial,orphan_stop_review=stopped,
                    network_requests=0,orders_sent=0,live_trading=False)
    (root/'report.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    return result
