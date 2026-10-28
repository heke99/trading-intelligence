"""Supplied-scenario hedge sizing, factor bounds, liquidity and opportunity cost."""
from copy import deepcopy
from decimal import Decimal, localcontext
import unittest

from trading_intelligence.contracts import ContractError
from trading_intelligence.hedge_math import search_hedges


def fixture():
    route = dict(broker='invented', connection='c', account='a', environment='paper')
    inputs = dict(book=dict(book_id='equity-book', route=route, currency='USD',
        market_value='10000', gross_notional='10000', factor_exposure='10000', risk_factor_id='market:demo',
        pending_orders_known=True, pending_orders_clear=True, long_only=True),
        hedge_accounts=[dict(route=deepcopy(route), currency='USD', available_cash='2000')],
        candidates=[dict(candidate_id='future', contract_id='invented-expiry', route=deepcopy(route),
            currency='USD', notional_per_contract='2000', factor_per_contract='2000', risk_factor_id='market:demo',
            roundtrip_cost_per_contract='10', initial_margin_per_contract='100',
            stressed_margin_per_contract='200')], scenarios=[])
    values = [('crash','-1000','-200','250','0',False),
              ('basis-break','-200','100','0','150',True),
              ('rally','1000','200','0','300',False)]
    for identity, portfolio, pnl, long_cash, short_cash, basis in values:
        inputs['scenarios'].append(dict(scenario_id=identity, horizon_at='2026-11-01T16:00:00Z',
            portfolio_pnl=portfolio, basis_break=basis, hedges={'future':dict(
                long_pnl_per_contract=pnl, long_adverse_cash_per_contract=long_cash,
                short_adverse_cash_per_contract=short_cash)}))
    policy=dict(policy_id='frozen-policy',version='1',max_contracts=5,max_gross_notional='20000',
        max_hedge_notional_ratio='1',max_abs_residual_factor='6000',max_worst_loss='700',
        min_loss_improvement='100',max_upside_sacrifice='700',cash_buffer='100',
        reduction_fractions=['0','0.5','1'],reduction_cost_full_book='20')
    return inputs,policy


def alternative(result, identity):
    return next(x for x in result['alternatives'] if x['alternative_id']==identity)


class HedgeMathTests(unittest.TestCase):
    def setUp(self):
        self.inputs,self.policy=fixture()

    def search(self):
        return search_hedges(self.inputs,self.policy)

    def test_minimax_integer_search_and_cash_reduction_tradeoff(self):
        x=self.search()
        self.assertEqual(x['best_feasible_hedge_id'],'hedge:future:-3')
        self.assertEqual(x['best_feasible_alternative_id'],'reduce:0.5')
        hedge=alternative(x,'hedge:future:-3')
        self.assertEqual(hedge['scenario_pnl'],{'crash':'-430','basis-break':'-530','rally':'370'})
        self.assertEqual(hedge['worst_loss'],'530')
        self.assertEqual(hedge['max_upside_sacrifice'],'630')
        self.assertEqual(hedge['factor_exposure_after'],'4000')
        self.assertEqual(hedge['gross_notional_after'],'16000')
        self.assertEqual(hedge['simultaneous_loss_scenario_ids'],['basis-break'])
        self.assertFalse(x['execution_approved'])
        self.assertEqual(x['orders_sent'],0)

    def test_vm_cash_is_not_charged_twice_to_pnl(self):
        hedge=alternative(self.search(),'hedge:future:-3')
        self.assertEqual(hedge['adverse_path_vm_cash'],'900')
        self.assertEqual(hedge['stressed_margin'],'600')
        self.assertEqual(hedge['initial_margin'],'300')
        self.assertEqual(hedge['total_cost'],'30')
        self.assertEqual(hedge['stressed_cash_required'],'1630')
        self.assertEqual(hedge['scenario_pnl']['crash'],'-430')

    def test_full_reduction_can_sacrifice_too_much_upside(self):
        reduction=alternative(self.search(),'reduce:1')
        self.assertEqual(reduction['scenario_pnl'],{'crash':'-20','basis-break':'-20','rally':'-20'})
        self.assertIn('upside_sacrifice_limit',reduction['blockers'])
        self.assertFalse(reduction['feasible'])

    def test_hedge_rounding_never_crosses_factor_sign(self):
        self.policy['max_contracts']=6
        hedge=alternative(self.search(),'hedge:future:-6')
        self.assertIn('factor_sign_reversal',hedge['blockers'])

    def test_cash_on_other_account_or_currency_is_not_pooled(self):
        self.inputs['hedge_accounts'][0]['route']['account']='elsewhere'
        self.inputs['hedge_accounts'][0]['available_cash']='1000000'
        x=self.search()
        self.assertIsNone(x['best_feasible_hedge_id'])
        self.assertIn('hedge_account_cash_missing',alternative(x,'hedge:future:-3')['blockers'])

    def test_cash_shortfall_and_stress_margin_are_respected(self):
        self.inputs['hedge_accounts'][0]['available_cash']='1629'
        self.assertIn('hedge_account_cash_insufficient',alternative(self.search(),'hedge:future:-3')['blockers'])
        self.inputs['hedge_accounts'][0]['available_cash']='1630'
        self.assertTrue(alternative(self.search(),'hedge:future:-3')['feasible'])

    def test_missing_basis_break_keeps_cash_reduction_but_no_accepted_hedge(self):
        for scenario in self.inputs['scenarios']:
            scenario['basis_break']=False
        x=self.search()
        self.assertIsNone(x['best_feasible_hedge_id'])
        self.assertEqual(x['best_feasible_alternative_id'],'reduce:0.5')
        self.assertIn('simultaneous_loss_basis_stress_missing',alternative(x,'hedge:future:-3')['blockers'])

    def test_tag_alone_does_not_substitute_for_both_legs_losing(self):
        self.inputs['scenarios'][0]['basis_break']=True
        self.inputs['scenarios'][1]['basis_break']=False
        x=self.search()
        self.assertIsNone(x['best_feasible_hedge_id'])

    def test_increasing_factor_risk_is_not_a_hedge(self):
        x=alternative(self.search(),'hedge:future:1')
        self.assertIn('factor_risk_not_reduced',x['blockers'])
        self.assertFalse(x['instrument_reduce_only'])

    def test_pending_order_unknown_blocks_both_new_hedge_and_reduction(self):
        self.inputs['book']['pending_orders_known']=False
        self.inputs['book']['pending_orders_clear']=False
        x=self.search()
        self.assertIsNone(x['best_feasible_alternative_id'])
        self.assertIn('pending_orders_unknown',alternative(x,'reduce:0.5')['blockers'])

    def test_minimum_loss_improvement_is_not_optional_at_zero_threshold(self):
        self.policy['min_loss_improvement']='0'
        self.inputs['candidates'][0]['roundtrip_cost_per_contract']='10000'
        x=self.search()
        self.assertIn('insufficient_loss_improvement',alternative(x,'hedge:future:-3')['blockers'])

    def test_inconsistent_path_stress_cannot_hide_terminal_vm_debit(self):
        self.inputs['scenarios'][0]['hedges']['future']['long_adverse_cash_per_contract']='199'
        with self.assertRaises(ContractError):self.search()

    def test_no_candidates_still_compares_reduction_and_hold(self):
        self.inputs['candidates']=[]
        for s in self.inputs['scenarios']:s['hedges']={}
        x=self.search()
        self.assertIsNone(x['best_feasible_hedge_id'])
        self.assertEqual(x['best_feasible_alternative_id'],'reduce:0.5')
        self.assertEqual(len(x['alternatives']),3)

    def test_scenarios_need_matching_candidate_keys_common_horizon_unique_ids(self):
        original=deepcopy(self.inputs)
        mutations=[lambda x:x['scenarios'][0]['hedges'].clear(),
                   lambda x:x['scenarios'][0].update(horizon_at='2026-11-02T16:00:00Z'),
                   lambda x:x['scenarios'][1].update(scenario_id='crash')]
        for mutate in mutations:
            self.inputs=deepcopy(original);mutate(self.inputs)
            with self.assertRaises(ContractError):self.search()

    def test_strict_bounded_policy_and_nonfinite_inputs(self):
        for key,value in [('max_contracts',True),('max_contracts',101),
                          ('max_worst_loss','NaN'),('max_gross_notional','1e99999999'),
                          ('reduction_fractions',['0','1.1']),('reduction_fractions',['0','0.0'])]:
            with self.subTest(key=key,value=value):
                _,self.policy=fixture();self.policy[key]=value
                with self.assertRaises(ContractError):self.search()

    def test_decimal_context_does_not_change_results_and_inputs_not_mutated(self):
        original=deepcopy(self.inputs)
        x=self.search()
        with localcontext() as context:
            context.prec=4
            self.assertEqual(x,self.search())
        self.assertEqual(original,self.inputs)

    def test_known_but_nonclear_pending_orders_block_new_actions(self):
        self.inputs['book']['pending_orders_clear']=False
        result=self.search()
        self.assertIsNone(result['best_feasible_alternative_id'])
        self.assertIn('pending_orders_not_clear',alternative(result,'reduce:0.5')['blockers'])

    def test_mixed_book_cannot_assume_sale_proceeds_for_reduction(self):
        self.inputs['book']['long_only']=False
        self.inputs['book']['market_value']='5000'
        result=self.search()
        reduction=alternative(result,'reduce:0.5')
        self.assertIn('cash_reduction_long_only_scope_required',reduction['blockers'])
        self.assertTrue(reduction['immediate_cash_proceeds_unassessed'])
        self.assertNotIn('immediate_sale_proceeds',reduction)

    def test_reduction_costs_need_funding_on_protected_account_without_netting_proceeds(self):
        self.inputs['hedge_accounts'][0]['available_cash']='9'
        result=self.search()
        self.assertIn('protected_account_cash_insufficient',alternative(result,'reduce:0.5')['blockers'])

    def test_long_only_value_and_gross_must_match(self):
        self.inputs['book']['market_value']='9000'
        with self.assertRaises(ContractError):self.search()

    def test_cross_currency_values_cannot_be_added_even_for_blocked_hedges(self):
        self.inputs['candidates'][0]['currency']='EUR'
        with self.assertRaises(ContractError):self.search()

    def test_book_and_hedge_factor_namespaces_must_match(self):
        self.inputs['candidates'][0]['risk_factor_id']='fx:delta'
        with self.assertRaises(ContractError):self.search()
