"""Four-part synthetic intent/control/callback/restart integration."""
import json
from datetime import timedelta
from copy import deepcopy
import concurrent.futures
import unittest
import test_hedge_reservations as fixtures
from trading_intelligence.hedge_simulation import HedgeSimulationStore
from trading_intelligence.hedge_reservations import HedgeReservationStore
from trading_intelligence.contracts import ContractError,RecordConflict,EvidenceIntegrityError,Use

class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.ReservationTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.reserve();self.clock=self.f.f.f
        self.f.store.close()
        self.store=HedgeSimulationStore(self.clock.path,clock=lambda:self.clock.now)
        self.f.store=self.f.f.store=self.clock.store=self.f.f.origin.store=self.store
        self.intent=self.store.create_intent('intent','one')
        self.controls=dict(route=self.intent['route'],mode='active',observed_at=self.clock.now.isoformat(),
            expires_at=(self.clock.now+timedelta(seconds=45)).isoformat(),max_contracts=3,
            allowed_contract_ids=[self.intent['contract_id']],policy_version='synthetic-risk-1')

    def control(self,identity='controls',**updates):
        self.controls.update(updates)
        evidence=self.store.ingest(source_id='facility',record_id=identity,revision_id='1',
            payload=json.dumps(self.controls).encode(),published_at=self.clock.now,received_at=self.clock.now)
        return self.store.record_controls(identity,evidence)

    def dispatch(self):self.control();return self.store.claim_dispatch('intent')

    def test_intent_reuses_canonical_identity_and_is_idempotent(self):
        self.assertEqual(self.intent,self.store.create_intent('intent','one'))
        self.assertEqual(self.intent['signed_quantity'],-3)
        self.assertEqual(self.intent['contract_id'],'invented-expiry')
        self.assertEqual(self.intent['broker_orders_sent'],0)
        with self.assertRaises(RecordConflict):self.store.create_intent('second','one')

    def test_missing_controls_and_new_stop_block_dispatch(self):
        with self.assertRaises(ContractError):self.store.claim_dispatch('intent')
        self.control();self.clock.now+=timedelta(seconds=1)
        self.control('stop',mode='hard_stop')
        with self.assertRaises(ContractError):self.store.claim_dispatch('intent')
        self.assertEqual(self.store.simulation_state('intent')['event_count'],0)

    def test_quantity_contract_expiry_controls_block(self):
        for identity,changes in [('limit',dict(max_contracts=2)),('contract',dict(allowed_contract_ids=['other'])),('pause',dict(mode='paused'))]:
            self.clock.now+=timedelta(seconds=1);self.control(identity,**changes)
            self.assertFalse(self.store.dispatch_check('intent')['synthetic_dispatch_eligible'])
        self.clock.now+=timedelta(minutes=2)
        self.assertIn('intent_expired',self.store.dispatch_check('intent')['blockers'])

    def test_claim_unknown_restart_cannot_dispatch_twice(self):
        claimed=self.dispatch()
        with HedgeSimulationStore(self.clock.path,clock=lambda:self.clock.now) as other:
            self.assertEqual(claimed,other.claim_dispatch('intent'))
            state=other.simulation_state('intent')
            self.assertEqual((state['state'],state['simulated_dispatch_count']),('unknown',1))
        with self.assertRaises(ContractError):self.store.release('one',reason='abandoned_research')
        with HedgeReservationStore(self.clock.path,clock=lambda:self.clock.now) as base:
            with self.assertRaises(ContractError):base.release('one',reason='abandoned_research')

    def test_partial_unknown_late_fill_after_stop_and_revocation(self):
        self.dispatch()
        self.store.inject('intent','accepted','accepted')
        first=self.store.inject('intent','fill1','fill',cumulative_filled=1,fill_price='100')
        self.assertEqual(first,self.store.inject('intent','fill1','fill',cumulative_filled=1,fill_price='100'))
        self.store.inject('intent','lost','unknown')
        self.clock.now+=timedelta(seconds=1);self.control('stop',mode='hard_stop')
        self.store.set_permissions('facility',known_at=self.clock.now,uses={Use.STORAGE})
        self.store.inject('intent','fill2','fill',cumulative_filled=2,fill_price='100.25')
        self.assertEqual(self.store.simulation_state('intent')['signed_filled'],-2)
        self.store.inject('intent','cancel','cancelled')
        self.store.inject('intent','fill3','fill',cumulative_filled=3,fill_price='100')
        state=self.store.simulation_state('intent')
        self.assertEqual((state['state'],state['remaining']),('filled',0))
        self.assertEqual(state['broker_orders_sent'],0)

    def test_partial_late_after_cancel_does_not_reopen_order(self):
        self.dispatch();self.store.inject('intent','cancel','cancelled')
        self.store.inject('intent','late','fill',cumulative_filled=1,fill_price='100')
        self.assertEqual(self.store.simulation_state('intent')['state'],'cancelled_with_late_fill')
        self.store.inject('intent','delayed_ack','accepted')
        self.assertEqual(self.store.simulation_state('intent')['state'],'cancelled_with_late_fill')

    def test_invalid_fills_and_duplicate_conflicts(self):
        self.dispatch()
        for qty,price in [(0,'100'),(4,'100'),(1,'99'),(1,'100.1'),(True,'100')]:
            with self.assertRaises(ContractError):self.store.inject('intent','bad','fill',cumulative_filled=qty,fill_price=price)
        self.store.inject('intent','fill','fill',cumulative_filled=1,fill_price='100')
        with self.assertRaises(RecordConflict):self.store.inject('intent','fill','fill',cumulative_filled=2,fill_price='100')

    def test_abandon_before_dispatch_releases_only_local_draft(self):
        with self.assertRaises(ContractError):self.store.release('one',reason='abandoned_research')
        self.store.abandon('intent');self.store.release('one',reason='abandoned_research')
        with self.assertRaises(ContractError):self.store.claim_dispatch('intent')

    def test_cannot_abandon_dispatched_unknown(self):
        self.dispatch()
        with self.assertRaises(ContractError):self.store.abandon('intent')

    def test_concurrent_claims_leave_one_dispatch(self):
        self.control();path=self.clock.path;now=self.clock.now
        def claim(_):
            with HedgeSimulationStore(path,clock=lambda:now) as other:return other.claim_dispatch('intent')
        with concurrent.futures.ThreadPoolExecutor(2) as executor:
            a,b=executor.map(claim,range(2))
        self.assertEqual(a,b);self.assertEqual(self.store.simulation_state('intent')['simulated_dispatch_count'],1)

    def test_journal_corruption_and_clock_rollback(self):
        self.dispatch();self.clock.now-=timedelta(seconds=1)
        with self.assertRaises(EvidenceIntegrityError):self.store.simulation_state('intent')
        self.clock.now+=timedelta(seconds=1)
        with self.store.db:self.store.db.execute("UPDATE hedge_sim_events SET sha256='bad'")
        with self.assertRaises(EvidenceIntegrityError):self.store.simulation_state('intent')

    def test_current_margin_revision_invalidates_old_draft(self):
        from decimal import Decimal
        from trading_intelligence.futures import FuturesMargin
        self.control();self.clock.now+=timedelta(seconds=1)
        self.store.put_margin('invented','a','invented-expiry',FuturesMargin(Decimal('150'),Decimal('100'),'USD'),
            **{**self.f.f.times,'known_at':self.clock.now})
        check=self.store.dispatch_check('intent')
        self.assertIn('current_futures_reference_changed',check['blockers'])
        with self.assertRaises(ContractError):self.store.claim_dispatch('intent')

    def test_rejected_callback_preserves_late_allocated_quantity(self):
        self.dispatch();self.store.inject('intent','rejected','rejected')
        self.store.inject('intent','late','fill',cumulative_filled=1,fill_price='100')
        self.assertEqual(self.store.simulation_state('intent')['state'],'rejected_with_late_fill')
        self.assertEqual(self.store.simulation_state('intent')['signed_filled'],-1)

    def test_callbacks_before_dispatch_and_invalid_control_versions_rejected(self):
        with self.assertRaises(ContractError):self.store.inject('intent','premature','accepted')
        self.control()
        with self.assertRaises(ContractError):self.control('same-time',mode='paused')

    def test_final_validity_is_checked_at_claim_commit(self):
        from unittest.mock import patch
        self.control()
        original=self.store.dispatch_check
        def delayed(identity):
            result=original(identity);self.clock.now+=timedelta(minutes=1);return result
        with patch.object(self.store,'dispatch_check',side_effect=delayed):
            with self.assertRaises(ContractError):self.store.claim_dispatch('intent')
        self.assertEqual(self.store.simulation_state('intent')['event_count'],0)

    def test_demo_survives_a_fresh_process_and_replays_the_exact_report(self):
        from trading_intelligence.hedge_simulation_demo import hedge_simulation_demo
        import subprocess,sys,os
        from pathlib import Path
        root=Path(self.f.f.f.tmp.name)/'four-part-proof'
        first=hedge_simulation_demo(root)
        result=subprocess.run([sys.executable,'-m','trading_intelligence','hedge-simulation-demo','--out',str(root)],
            env={**os.environ,'PYTHONPATH':'src'},capture_output=True,text=True,check=True)
        self.assertEqual(first,json.loads(result.stdout))
        self.assertEqual(first['final_state']['simulated_dispatch_count'],1)
        self.assertEqual(first['broker_orders_sent'],0)

    def test_callback_cannot_consume_internal_claim_identifiers(self):
        self.dispatch()
        for event_id in ('dispatch:future-intent','abandon:other'):
            with self.assertRaises(ContractError):self.store.inject('intent',event_id,'accepted')
