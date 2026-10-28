"""Synthetic economic sensitivity and immutable event/price/account lineage."""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
import json
import unittest

import test_event_analysis as fixtures
from trading_intelligence.contracts import ContractError, EvidenceIntegrityError, RecordConflict, Use, UseNotAllowed
from trading_intelligence.event_opportunity import EventOpportunityStore, number


class OpportunityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.EventAnalysisTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        f.store.close()
        f.store = EventOpportunityStore(f.path, clock=lambda: f.now)
        self.store = f.store
        f.prepare()
        f.store.start_analysis('request')
        f.now += timedelta(seconds=1)
        f.record()
        self.data = dict(listing_id='listing', currency='USD', quote_at=f.now.isoformat(),
            valid_until=(f.now+timedelta(minutes=1)).isoformat(), bid='99', ask='101', quantity='10',
            entry_fee_per_unit='0.1', exit_fee_per_unit='0.1', slippage_per_unit_per_leg='0.2',
            exit_half_spread='0.4', borrow_cost_per_unit='0.5',
            scenario_exit_mids={'adverse':'90','none':'100'},
            scenario_exit_at={k:(f.now+timedelta(days=7)).isoformat() for k in ('adverse','none')},
            pre_event_reference=dict(mid='110',observed_at=(fixtures.T+timedelta(hours=1)).isoformat()),
            portfolio=dict(broker='invented',connection='one',account='a',environment='paper',
                observed_at=f.now.isoformat(),valid_until=(f.now+timedelta(minutes=5)).isoformat(),
                position_units='20', pending_buy_units='0',pending_sell_units='0'))

    def assess(self, **changes):
        args = dict(assessment_id='preview', analysis_id='analysis', evidence_id=self.evidence(),as_of=self.fixture.now)
        args.update(changes)
        return self.store.assess(**args)

    def evidence(self, identity='inputs'):
        f=self.fixture
        return self.store.ingest(source_id='facility',record_id=identity,revision_id='1',
            payload=json.dumps(self.data).encode(),published_at=f.now,received_at=f.now)

    def test_arithmetic_uses_ask_bid_two_fees_two_slippage_and_exit_spread(self):
        x=self.assess()['result']
        self.assertEqual(x['long']['scenario_pnl'],{'adverse':'-120.0','none':'-20.0'})
        self.assertEqual(x['short']['scenario_pnl'],{'adverse':'75.0','none':'-25.0'})
        self.assertEqual(Decimal(x['long']['break_even_exit_mid']),Decimal('102'))
        self.assertEqual(Decimal(x['short']['break_even_exit_mid']),Decimal('97.5'))
        self.assertEqual(x['reduce_existing']['resulting_units'],'10')
        self.assertFalse(x['reduce_existing']['risk_reduction_verified'])
        self.assertEqual(x['recommended_action'],'abstain')
        self.assertIsNone(x['expected_return'])
        self.assertEqual(x['orders_sent'],0)

    def test_changed_price_does_not_become_causal_attribution(self):
        x=self.assess()['result']
        self.assertLess(Decimal(x['price_change_since_reference_percent']),0)
        self.assertFalse(x['reaction_is_causal_estimate'])

    def test_missing_borrow_cost_blocks_short_calculation(self):
        self.data['borrow_cost_per_unit']=None
        x=self.assess()['result']
        self.assertIsNone(x['short']['scenario_pnl'])
        self.assertEqual(x['short']['blockers'],['borrow_cost_unknown'])

    def test_pending_unknown_prevents_usable_comparison_and_reduction(self):
        self.data['portfolio']['pending_buy_units']=None
        x=self.assess()['result']
        self.assertEqual(x['status'],'blocked')
        self.assertIn('pending_orders_unknown',x['blockers'])
        self.assertIn('pending_orders_not_clear',x['reduce_existing']['blockers'])

    def test_reduction_never_crosses_zero_or_ignores_pending_orders(self):
        self.data['quantity']='21'
        self.data['portfolio']['pending_sell_units']='1'
        x=self.assess()['result']
        self.assertIsNone(x['reduce_existing']['resulting_units'])
        self.assertEqual(len(x['reduce_existing']['blockers']),2)

    def test_short_position_reduction_is_a_buy(self):
        self.data['portfolio']['position_units']='-20'
        x=self.assess()['result']['reduce_existing']
        self.assertEqual((x['side'],x['resulting_units']),('buy','-10'))

    def test_quote_and_portfolio_age_cannot_be_hidden_by_distant_expiry(self):
        self.data['valid_until']=(self.fixture.now+timedelta(days=1)).isoformat()
        self.fixture.now+=timedelta(minutes=6)
        x=self.assess()['result']
        self.assertIn('quote_too_old',x['blockers'])
        self.assertIn('portfolio_too_old',x['blockers'])

    def test_future_quotes_crossed_quotes_invalid_numbers_and_wrong_currency(self):
        original=deepcopy(self.data)
        cases=[('quote_at',(self.fixture.now+timedelta(seconds=1)).isoformat()),
               ('bid','102'),('ask','NaN'),('ask',101),('currency','EUR'),('quantity','0')]
        for key,value in cases:
            with self.subTest(key=key,value=value):
                self.data=deepcopy(original);self.data[key]=value
                evidence=self.evidence('bad-'+key+str(value))
                with self.assertRaises(ContractError):
                    self.store.assess('bad', 'analysis', evidence, as_of=self.fixture.now)

    def test_target_ids_and_pre_event_time_must_match_evidence(self):
        self.data['scenario_exit_mids']['invented']='500'
        with self.assertRaises(ContractError):self.assess()
        del self.data['scenario_exit_mids']['invented']
        self.data['pre_event_reference']['observed_at']=self.fixture.now.isoformat()
        with self.assertRaises(ContractError):
            self.store.assess('bad','analysis',self.evidence('bad-reference'),as_of=self.fixture.now)

    def test_expiry_and_absent_analysis_block_or_reject(self):
        self.fixture.now+=timedelta(hours=2)
        x=self.assess()['result']
        self.assertIn('analysis_expired',x['blockers'])
        with self.assertRaises(ContractError):
            self.store.assess('missing','no-analysis',self.evidence(),as_of=self.fixture.now)

    def test_immutable_restart_available_only_at_completion_and_current_rights(self):
        evidence=self.evidence()
        old=self.fixture.now
        self.fixture.now+=timedelta(seconds=1)
        x=self.store.assess('preview','analysis',evidence,as_of=old)
        self.assertIsNone(self.store.get_assessment('preview',as_of=old))
        self.assertEqual(x,self.store.assess('preview','analysis',evidence,as_of=old))
        with EventOpportunityStore(self.fixture.path,clock=lambda:self.fixture.now) as other:
            self.assertEqual(x,other.get_assessment('preview',as_of=self.fixture.now))
        self.fixture.now+=timedelta(seconds=1)
        self.store.set_permissions('facility',known_at=self.fixture.now,uses={Use.STORAGE})
        with self.assertRaises(UseNotAllowed):self.store.get_assessment('preview',as_of=old+timedelta(seconds=1))

    def test_same_id_changes_and_raw_corruption_rejected(self):
        x=self.assess()
        with self.assertRaises(RecordConflict):
            self.store.assess('preview','analysis',x['evidence_id'],as_of=self.fixture.now-timedelta(microseconds=1))
        with self.store.db:
            self.store.db.execute('UPDATE raw_objects SET payload=? WHERE sha256=?',(b'corrupt',x['evidence']['sha256']))
        with self.assertRaises(EvidenceIntegrityError):
            self.store.get_assessment('preview',as_of=self.fixture.now)

    def test_decimal_context_does_not_change_results(self):
        from decimal import localcontext
        with localcontext() as ctx:
            ctx.prec=5
            x=self.assess()
        self.assertEqual(x['result']['long']['scenario_pnl']['adverse'],'-120.0')
        for value in ('1e9999','1e-9999','Infinity','-Infinity'):
            with self.assertRaises(ContractError):number(value)

    def test_demo_cli_is_repeatable_across_process_restart(self):
        import os,subprocess,sys
        from pathlib import Path
        from trading_intelligence.event_opportunity_demo import opportunity_demo
        root=Path(self.fixture.tmp.name)/'opportunity-demo'
        one=opportunity_demo(root)
        env={**os.environ,'PYTHONPATH':'src'}
        completed=subprocess.run([sys.executable,'-m','trading_intelligence','event-opportunity-demo','--out',str(root)],env=env,capture_output=True,text=True,check=True)
        self.assertEqual(one,json.loads(completed.stdout))
        self.assertEqual(one['assessment']['result']['status'],'sensitivity_only')
        self.assertEqual(one['network_requests'],0)

    def test_ordinary_fund_is_not_treated_as_an_intraday_equity(self):
        from trading_intelligence.contracts import Instrument,Listing,AssetKind
        self.store.register_instrument(Instrument('fund','issuer',AssetKind.MUTUAL_FUND))
        with self.assertRaises(ContractError):
            self.store.register_listing(Listing('fund-listing','fund','XNAS','USD'))
        self.data['listing_id']='fund-listing'
        with self.assertRaises(ContractError):self.assess()

    def test_snapshot_unavailable_at_cutoff_cannot_be_used(self):
        cutoff=self.fixture.now
        self.fixture.now+=timedelta(seconds=1)
        evidence=self.evidence()
        with self.assertRaises(ContractError):
            self.store.assess('future','analysis',evidence,as_of=cutoff)

    def test_reduction_value_compares_incremental_pnl_against_holding(self):
        x=self.assess()['result']['reduce_existing']
        self.assertEqual(x['incremental_pnl_vs_hold'],{'adverse':'87.0','none':'-13.0'})

    def test_boundary_expiry_is_blocked(self):
        self.data['quote_at']=(self.fixture.now-timedelta(seconds=1)).isoformat()
        self.data['valid_until']=self.fixture.now.isoformat()
        self.assertIn('quote_expired',self.assess()['result']['blockers'])

    def test_bankruptcy_stress_supports_zero_but_not_negative_exit_bid(self):
        self.data['scenario_exit_mids']['adverse']='0'
        self.data['exit_half_spread']='0'
        x=self.assess()['result']
        self.assertLess(Decimal(x['long']['scenario_pnl']['adverse']),Decimal('-1000'))

    def test_exit_assumptions_need_future_time_and_nonnegative_exit_bid(self):
        self.data['scenario_exit_at']['adverse']=self.fixture.now.isoformat()
        with self.assertRaises(ContractError):self.assess()
        self.data['scenario_exit_at']['adverse']=(self.fixture.now+timedelta(days=1)).isoformat()
        self.data['scenario_exit_mids']['adverse']='0.1'
        with self.assertRaises(ContractError):
            self.store.assess('bad','analysis',self.evidence('negative-exit'),as_of=self.fixture.now)
