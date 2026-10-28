"""Synthetic event-to-canonical-futures hedge provenance and reference checks."""
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext
import json
import unittest

import test_event_opportunity as opportunities
import test_hedge_math as maths
from trading_intelligence.contracts import (
    AssetKind, ContractError, DataOrigin, Entity, EvidenceIntegrityError, Instrument,
    RecordConflict, Use, UseNotAllowed,
)
from trading_intelligence.futures import (
    FutureContract, FutureProduct, FutureTerms, FuturesMargin, Session, Settlement, TradingSchedule,
)
from trading_intelligence.hedge_research import HedgeResearchStore


class HedgeResearchTests(unittest.TestCase):
    def setUp(self):
        self.origin = opportunities.OpportunityTests()
        self.origin.setUp()
        self.addCleanup(self.origin.doCleanups)
        self.origin.data['portfolio']['position_units']='100'
        self.opportunity = self.origin.assess()
        self.f = self.origin.fixture
        self.f.store.close()
        self.store = HedgeResearchStore(self.f.path, clock=lambda: self.f.now)
        self.f.store = self.origin.store = self.store
        self.cutoff = self.f.now
        start, end = self.cutoff-timedelta(days=1), self.cutoff+timedelta(days=60)
        self.store.register_source('hedge-refs', DataOrigin.SYNTHETIC)
        self.store.set_permissions('hedge-refs', known_at=start, uses={Use.STORAGE, Use.RESEARCH})
        self.ref_evidence = self.store.ingest(source_id='hedge-refs', record_id='reference', revision_id='1',
            payload=b'{"origin":"synthetic reference"}',published_at=start,received_at=start)
        self.store.register_entity(Entity('index-publisher','Invented index publisher'))
        self.store.register_instrument(Instrument('index','index-publisher',AssetKind.INDEX))
        self.store.register_product(FutureProduct('index-future','DEMO','XOFF','index','USD','index_points'))
        self.store.register_contract(FutureContract('invented-expiry','index-future','2026-03'))
        self.times = dict(valid_from=start,valid_to=end,known_at=start,evidence_id=self.ref_evidence)
        self.terms = FutureTerms(Decimal('0.25'),Decimal('20'),Settlement.CASH,
            self.cutoff+timedelta(days=30),self.cutoff+timedelta(days=29))
        self.store.put_terms('invented-expiry',self.terms,**self.times)
        self.store.put_schedule('index-future',TradingSchedule('UTC',(
            Session(start,self.cutoff+timedelta(days=2)),)),**self.times)
        self.store.put_broker_binding('invented','DEMOH26','invented-expiry','native-123',**self.times)
        self.store.put_margin('invented','a','invented-expiry',FuturesMargin(Decimal('100'),Decimal('80'),'USD'),**self.times)
        inputs, policy = maths.fixture()
        route = dict(broker='invented',connection='one',account='a',environment='paper')
        inputs['book']['route'] = deepcopy(route)
        for account in inputs['hedge_accounts']: account['route'] = deepcopy(route)
        for candidate in inputs['candidates']: candidate['route'] = deepcopy(route)
        for scenario in inputs['scenarios']:
            scenario['horizon_at']=(self.cutoff+timedelta(days=7)).isoformat()
        self.raw = dict(inputs=inputs, policy=policy, controls=dict(
            state_observed_at=self.cutoff.isoformat(),valid_until=(self.cutoff+timedelta(minutes=1)).isoformat(),
            policy_known_at=(self.cutoff-timedelta(seconds=1)).isoformat(),order_mode='active',hedge_mandate=True,
            min_rebalance_seconds=60,rebalance_band=0,exit_rule='revalidate_then_unwind',
            protected_listing_ids=['listing'],holdings=[dict(listing_id='listing',units='100',mid='100',factor_loading='1')],hedge_positions={'future':0},hedge_pending_state={'future':'clear'}),
            market_references={'future':dict(broker_identifier='DEMOH26',entry_price='100',price_kind='raw_contract',
                observed_at=self.cutoff.isoformat(),valid_until=(self.cutoff+timedelta(minutes=1)).isoformat(),
                exit_prices={'crash':'90','basis-break':'105','rally':'110'})})

    def evidence(self, identity='hedge-input'):
        return self.store.ingest(source_id='facility',record_id=identity,revision_id='1',
            payload=json.dumps(self.raw).encode(),published_at=self.f.now,received_at=self.f.now)

    def search(self, **changes):
        args=dict(search_id='search',opportunity_id='preview',evidence_id=self.evidence(),as_of=self.f.now)
        args.update(changes)
        return self.store.search(**args)

    def update_terms(self, **changes):
        self.f.now += timedelta(seconds=1)
        self.store.put_terms('invented-expiry',replace(self.terms,**changes),
            **{**self.times,'known_at':self.f.now})

    def test_reference_bound_search_never_authorizes_execution(self):
        x=self.search()
        self.assertEqual(len(x['futures_references']),5)
        self.assertEqual(x['result']['best_feasible_hedge_id'],'hedge:future:-3')
        self.assertFalse(x['execution_authorized'])
        self.assertFalse(x['supplied_state_verified'])
        self.assertEqual(x['orders_sent'],0)
        self.assertEqual(x['operational_blockers'],[])

    def test_idempotent_restart_and_input_cutoff_availability(self):
        evidence=self.evidence()
        original=self.f.now
        self.f.now += timedelta(seconds=1)
        x=self.store.search('search','preview',evidence,as_of=original)
        self.assertIsNone(self.store.get_search('search',as_of=original))
        self.assertEqual(x,self.store.search('search','preview',evidence,as_of=original))
        with HedgeResearchStore(self.f.path,clock=lambda:self.f.now) as other:
            self.assertEqual(x,other.get_search('search',as_of=self.f.now))
        with self.assertRaises(RecordConflict):
            self.store.search('search','preview',evidence,as_of=self.f.now)

    def test_future_inputs_and_unknown_opportunity_reject(self):
        original=self.f.now
        self.f.now += timedelta(seconds=1)
        evidence=self.evidence()
        with self.assertRaises(ContractError):self.store.search('future','preview',evidence,as_of=original)
        with self.assertRaises(ContractError):self.store.search('missing','missing',evidence,as_of=self.f.now)

    def test_current_reference_revocation_cannot_be_bypassed_with_old_cutoff(self):
        x=self.search()
        self.f.now += timedelta(seconds=1)
        self.store.set_permissions('hedge-refs',known_at=self.f.now,uses={Use.STORAGE})
        with self.assertRaises(UseNotAllowed):
            self.store.get_search('search',as_of=self.cutoff)

    def test_futures_backing_raw_corruption_blocks_archived_result(self):
        x=self.search()
        raw_hash=next(ref['evidence']['sha256'] for ref in x['futures_references'] if 'evidence' in ref)
        with self.store.db:
            self.store.db.execute('UPDATE raw_objects SET payload=? WHERE sha256=?',(b'corrupt',raw_hash))
        with self.assertRaises(EvidenceIntegrityError):self.store.get_search('search',as_of=self.f.now)

    def test_canonical_term_correction_preserves_earlier_knowledge(self):
        x=self.search()
        self.update_terms(multiplier=Decimal('40'))
        self.assertEqual(x,self.store.get_search('search',as_of=self.cutoff))

    def test_physical_delivery_expiry_and_late_entry_cutoff_reject(self):
        cases=[dict(settlement=Settlement.PHYSICAL,first_notice_at=self.cutoff+timedelta(days=29,hours=1)),
            dict(last_trade_at=self.cutoff+timedelta(days=1),entry_cutoff_at=self.cutoff),
            dict(entry_cutoff_at=self.cutoff)]
        for index, change in enumerate(cases):
            self.update_terms(**change)
            with self.subTest(change=change),self.assertRaises(ContractError):
                self.store.search('bad-'+str(index),'preview',self.evidence('bad-'+str(index)),as_of=self.f.now)

    def test_wrong_expiry_binding_rejects_even_known_broker_symbol(self):
        self.store.register_contract(FutureContract('other-expiry','index-future','2026-06'))
        self.store.put_broker_binding('invented','OTHER','other-expiry','native-456',**self.times)
        self.raw['market_references']['future']['broker_identifier']='OTHER'
        with self.assertRaises(ContractError):self.search()

    def test_closed_schedule_cannot_open_hedge(self):
        self.f.now += timedelta(seconds=1)
        self.store.put_schedule('index-future',TradingSchedule('UTC',(
            Session(self.cutoff+timedelta(hours=1),self.cutoff+timedelta(hours=2)),)),
            **{**self.times,'known_at':self.f.now})
        with self.assertRaises(ContractError):self.search()

    def test_offtick_continuous_stale_future_and_unsynchronized_quotes_reject(self):
        original=deepcopy(self.raw)
        cases=[('entry_price','100.1'),('price_kind','adjusted_series'),
            ('observed_at',(self.cutoff+timedelta(seconds=1)).isoformat()),
            ('observed_at',(self.cutoff-timedelta(seconds=61)).isoformat()),
            ('valid_until',self.cutoff.isoformat())]
        for index,(key,value) in enumerate(cases):
            self.raw=deepcopy(original)
            self.raw['market_references']['future'][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ContractError):
                self.store.search('bad-'+str(index),'preview',self.evidence('bad-'+str(index)),as_of=self.f.now)
        self.raw=deepcopy(original)
        self.raw['controls']['state_observed_at']=(self.cutoff-timedelta(seconds=31)).isoformat()
        with self.assertRaises(ContractError):self.store.search('skew','preview',self.evidence('skew'),as_of=self.f.now)

    def test_scenario_pnl_exit_tick_notional_margin_and_currency_are_bound(self):
        original=deepcopy(self.raw)
        mutations=[lambda x:x['inputs']['candidates'][0].update(notional_per_contract='2001'),
            lambda x:x['inputs']['candidates'][0].update(initial_margin_per_contract='101'),
            lambda x:x['inputs']['candidates'][0].update(currency='EUR'),
            lambda x:x['market_references']['future']['exit_prices'].update(crash='90.1'),
            lambda x:x['inputs']['scenarios'][0]['hedges']['future'].update(long_pnl_per_contract='-199')]
        for index, mutate in enumerate(mutations):
            self.raw=deepcopy(original);mutate(self.raw)
            with self.subTest(index=index),self.assertRaises(ContractError):
                self.store.search('bad-'+str(index),'preview',self.evidence('bad-'+str(index)),as_of=self.f.now)

    def test_protected_route_and_listing_must_match_linked_opportunity(self):
        original=deepcopy(self.raw)
        self.raw['inputs']['book']['route']['account']='other-account'
        with self.assertRaises(ContractError):self.search()
        self.raw=deepcopy(original)
        self.raw['controls']['protected_listing_ids']=['not-known']
        with self.assertRaises(ContractError):self.store.search('other','preview',self.evidence('other'),as_of=self.f.now)

    def test_controls_report_stops_and_missing_hedge_mandate(self):
        self.raw['controls']['order_mode']='hard_stop'
        self.raw['controls']['hedge_mandate']=False
        x=self.search()
        self.assertIn('order_mode_blocks_new_hedge',x['operational_blockers'])
        self.assertIn('hedge_mandate_missing',x['operational_blockers'])
        self.assertFalse(x['execution_authorized'])

    def test_holdings_aggregate_and_linked_quantity_quote_bind_exposure(self):
        original=deepcopy(self.raw)
        changes=[lambda x:x['controls']['holdings'][0].update(units='99'),
            lambda x:x['controls']['holdings'][0].update(mid='99'),
            lambda x:x['controls']['holdings'][0].update(factor_loading='0.5'),
            lambda x:x['inputs']['book'].update(market_value='9999'),
            lambda x:x['inputs']['book'].update(gross_notional='10001')]
        for index,change in enumerate(changes):
            self.raw=deepcopy(original);change(self.raw)
            with self.subTest(index=index),self.assertRaises(ContractError):
                self.store.search('holding-'+str(index),'preview',self.evidence('holding-'+str(index)),as_of=self.f.now)

    def test_existing_hedge_or_unknown_hedge_pending_requires_review(self):
        original=deepcopy(self.raw)
        for index, change in enumerate((dict(hedge_positions={'future':-1}),
                                      dict(hedge_pending_state={'future':'unknown'}))):
            self.raw=deepcopy(original);self.raw['controls'].update(change)
            x=self.store.search('existing-'+str(index),'preview',self.evidence('existing-'+str(index)),as_of=self.f.now)
            self.assertTrue(x['operational_blockers'])
            self.assertFalse(x['execution_authorized'])

    def test_caller_decimal_context_cannot_change_canonical_reference_checks(self):
        self.raw['market_references']['future']['entry_price']='100.25'
        self.raw['inputs']['candidates'][0]['notional_per_contract']='2005'
        for scenario, pnl in zip(self.raw['inputs']['scenarios'], ('-205','95','195')):
            scenario['hedges']['future']['long_pnl_per_contract']=pnl
        with localcontext() as context:
            context.prec=2
            x=self.search()
        self.assertEqual(x['result']['best_feasible_hedge_id'],'hedge:future:-3')

    def monitor_input(self, **changes):
        now=self.f.now
        snap=dict(book_id=self.raw['inputs']['book']['book_id'],policy_id=self.raw['policy']['policy_id'],
            protected_units='100',allocated_hedge_contracts=-1,target_contracts=-3,pending_state='clear',
            order_mode='active',observed_at=now.isoformat(),expires_at=(now+timedelta(seconds=30)).isoformat(),
            policy_expires_at=self.raw['controls']['valid_until'],exit_rule='revalidate_then_unwind',
            min_rebalance_seconds=60,last_rebalance_at=None,rebalance_band=0)
        snap.update(changes)
        return dict(snapshot=snap,route=deepcopy(self.raw['inputs']['candidates'][0]['route']),
                    alternative_id='hedge:future:-3',policy_version=self.raw['policy']['version'])

    def monitor_evidence(self, value, identity='monitor-input'):
        return self.store.ingest(source_id='facility',record_id=identity,revision_id='1',
            payload=json.dumps(value).encode(),published_at=self.f.now,received_at=self.f.now)

    def test_monitor_bound_route_policy_target_and_restart(self):
        self.search()
        self.f.now+=timedelta(seconds=1)
        raw=self.monitor_input()
        evidence=self.monitor_evidence(raw)
        cutoff=self.f.now
        self.f.now+=timedelta(seconds=1)
        x=self.store.monitor('monitor','search',evidence,as_of=cutoff)
        self.assertEqual(x['result']['research_delta_contracts'],-2)
        self.assertIsNone(self.store.get_monitor('monitor',as_of=cutoff))
        self.assertEqual(x,self.store.monitor('monitor','search',evidence,as_of=cutoff))
        with HedgeResearchStore(self.f.path,clock=lambda:self.f.now) as other:
            self.assertEqual(x,other.get_monitor('monitor',as_of=self.f.now))
        self.assertEqual(x['orders_sent'],0)

    def test_monitor_cannot_rewrite_policy_or_switch_route(self):
        self.search()
        self.f.now+=timedelta(seconds=1)
        original=self.monitor_input()
        mutations=[lambda x:x['snapshot'].update(target_contracts=-4),
            lambda x:x['snapshot'].update(policy_expires_at=(self.f.now+timedelta(days=1)).isoformat()),
            lambda x:x['snapshot'].update(rebalance_band=1),
            lambda x:x['route'].update(connection='other-connection'),
            lambda x:x.update(policy_version='2')]
        for index,mutation in enumerate(mutations):
            raw=deepcopy(original);mutation(raw)
            with self.subTest(index=index),self.assertRaises(ContractError):
                self.store.monitor('bad-'+str(index),'search',self.monitor_evidence(raw,'bad-monitor-'+str(index)),as_of=self.f.now)

    def test_monitor_late_fill_updates_delta_without_duplicate_hedge(self):
        self.search()
        self.f.now+=timedelta(seconds=1)
        raw=self.monitor_input(pending_state='unknown')
        x=self.store.monitor('unknown','search',self.monitor_evidence(raw),as_of=self.f.now)
        self.assertEqual(x['result']['state'],'reconcile')
        self.assertIsNone(x['result']['research_delta_contracts'])
        self.f.now+=timedelta(seconds=1)
        raw=self.monitor_input(allocated_hedge_contracts=-2)
        later=self.store.monitor('late','search',self.monitor_evidence(raw,'late-fill'),as_of=self.f.now)
        self.assertEqual(later['result']['research_delta_contracts'],-1)
        self.assertEqual(x,self.store.get_monitor('unknown',as_of=self.f.now))

    def test_monitor_orphan_hard_stop_keeps_exposure_alert(self):
        self.search()
        self.f.now+=timedelta(seconds=1)
        raw=self.monitor_input(protected_units='0',order_mode='hard_stop')
        x=self.store.monitor('orphan','search',self.monitor_evidence(raw),as_of=self.f.now)
        self.assertEqual(x['result']['state'],'blocked_hard_stop')
        self.assertTrue(x['result']['orphan_hedge'])
        self.assertIsNone(x['result']['research_delta_contracts'])

    def test_monitor_policy_expiry_during_processing_is_flagged(self):
        from unittest.mock import patch
        from trading_intelligence.hedge_monitor import evaluate_hedge
        self.search()
        self.f.now+=timedelta(seconds=1)
        raw=self.monitor_input(expires_at=(self.cutoff+timedelta(minutes=2)).isoformat())
        evidence=self.monitor_evidence(raw)
        cutoff=self.f.now
        def delayed(snapshot, *, now):
            result=evaluate_hedge(snapshot,now=now)
            self.f.now=self.cutoff+timedelta(seconds=61)
            return result
        with patch('trading_intelligence.hedge_monitor.evaluate_hedge',side_effect=delayed):
            x=self.store.monitor('slow','search',evidence,as_of=cutoff)
        self.assertTrue(x['expired_on_arrival'])

    def test_underlying_and_futures_prices_must_be_synchronized(self):
        self.origin.data['quote_at']=(self.f.now-timedelta(seconds=59)).isoformat()
        exposure=self.origin.evidence('older-exposure-quote')
        self.store.assess('older-exposure','analysis',exposure,as_of=self.f.now)
        with self.assertRaises(ContractError):
            self.store.search('skewed','older-exposure',self.evidence(),as_of=self.f.now)

    def test_hedge_demo_repeatable_across_fresh_process(self):
        import os,subprocess,sys
        from pathlib import Path
        from trading_intelligence.hedge_demo import hedge_demo
        root=Path(self.f.tmp.name)/'hedge-demo'
        one=hedge_demo(root)
        completed=subprocess.run([sys.executable,'-m','trading_intelligence','hedge-research-demo','--out',str(root)],
            env={**os.environ,'PYTHONPATH':'src'},capture_output=True,text=True,check=True)
        self.assertEqual(one,json.loads(completed.stdout))
        self.assertEqual(one['orders_sent'],0)

    def test_nonzero_protected_quantity_change_requires_resizing_search(self):
        self.search()
        self.f.now+=timedelta(seconds=1)
        raw=self.monitor_input(protected_units='50',allocated_hedge_contracts=-3)
        x=self.store.monitor('changed-book','search',self.monitor_evidence(raw),as_of=self.f.now)
        self.assertEqual(x['result']['state'],'review_changed_protected_exposure')
        self.assertIsNone(x['result']['research_delta_contracts'])

    def test_linked_policy_block_does_not_hide_unknown_external_status(self):
        self.raw['controls']['hedge_mandate']=False
        self.search()
        self.f.now+=timedelta(seconds=1)
        raw=self.monitor_input(pending_state='unknown')
        x=self.store.monitor('unknown-blocked-policy','search',self.monitor_evidence(raw),as_of=self.f.now)
        self.assertEqual(x['result']['state'],'reconcile')
        self.assertIsNone(x['result']['research_delta_contracts'])
        self.assertFalse(x['result']['order_submission_allowed'])

    def test_changed_canonical_underlying_identity_invalidates_archived_search(self):
        self.search()
        self.store.register_entity(Entity('other-index-publisher','Other invented publisher'))
        self.store.register_instrument(Instrument('other-index','other-index-publisher',AssetKind.INDEX))
        with self.store.db:
            self.store.db.execute('UPDATE future_products SET underlying_instrument_id=? WHERE product_id=?',
                                  ('other-index','index-future'))
        with self.assertRaises(EvidenceIntegrityError):
            self.store.get_search('search',as_of=self.f.now)

    def test_cash_settled_nonindex_future_is_outside_hedge_pilot(self):
        self.store.register_product(FutureProduct('stock-future','STOCK','XOFF','equity','USD','share_units'))
        self.store.register_contract(FutureContract('stock-expiry','stock-future','2026-03'))
        self.store.put_terms('stock-expiry',self.terms,**self.times)
        self.store.put_schedule('stock-future',TradingSchedule('UTC',(
            Session(self.cutoff-timedelta(days=1),self.cutoff+timedelta(days=2)),)),**self.times)
        self.store.put_broker_binding('invented','STOCKH26','stock-expiry','native-stock',**self.times)
        self.store.put_margin('invented','a','stock-expiry',FuturesMargin(Decimal('100'),Decimal('80'),'USD'),**self.times)
        self.raw['inputs']['candidates'][0]['contract_id']='stock-expiry'
        self.raw['market_references']['future']['broker_identifier']='STOCKH26'
        with self.assertRaises(ContractError):self.search()

    def test_quote_expiry_during_processing_blocks_reviewable_hedge(self):
        from unittest.mock import patch
        self.raw['controls']['valid_until']=(self.cutoff+timedelta(minutes=2)).isoformat()
        original=self.store._validate
        calls=[0]
        def delayed(*args,**kwargs):
            result=original(*args,**kwargs)
            calls[0]+=1
            if calls[0]==1:self.f.now=self.cutoff+timedelta(seconds=61)
            return result
        with patch.object(self.store,'_validate',side_effect=delayed):
            x=self.search()
        self.assertIn('futures_quote_or_entry_window_expired_at_processing',x['operational_blockers'])
        self.assertIsNone(x['reviewable_hedge_id'])
