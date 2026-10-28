"""Independent arithmetic and route-isolation checks for supplied-case hedges."""
from copy import deepcopy
from decimal import Decimal, localcontext
import unittest

from trading_intelligence.contracts import ContractError
from trading_intelligence.hedge_math import search_hedges


def fixture():
    route = dict(broker='synthetic', connection='one', account='a', environment='paper')
    candidate = dict(candidate_id='index', contract_id='synthetic-index-expiry', route=route,
        currency='USD', notional_per_contract='2000', factor_per_contract='2000', risk_factor_id='market:demo',
        roundtrip_cost_per_contract='10', initial_margin_per_contract='200',
        stressed_margin_per_contract='300')
    inputs = dict(book=dict(book_id='long-equities', route=route, currency='USD',
        market_value='10000', gross_notional='10000', factor_exposure='10000', risk_factor_id='market:demo',
        pending_orders_known=True,pending_orders_clear=True,long_only=True),
        hedge_accounts=[dict(route=route,currency='USD',available_cash='10000')],
        candidates=[candidate],scenarios=[])
    for identity,pnl,hedge,basis in (
            ('selloff','-1000','-200',False),('rally','1000','200',False),
            ('basis-break','-100','50',True)):
        value=Decimal(hedge)
        inputs['scenarios'].append(dict(scenario_id=identity,horizon_at='2026-11-01T00:00:00Z',
            portfolio_pnl=pnl,basis_break=basis,hedges={'index':dict(long_pnl_per_contract=hedge,
            long_adverse_cash_per_contract=str(max(Decimal(0),-value)),
            short_adverse_cash_per_contract=str(max(Decimal(0),value)))}))
    policy = dict(policy_id='synthetic-policy',version='1',max_contracts=5,
        max_gross_notional='25000',max_hedge_notional_ratio='1',max_abs_residual_factor='10000',
        max_worst_loss='1000',min_loss_improvement='100',max_upside_sacrifice='1000',
        cash_buffer='100',reduction_fractions=['0'],reduction_cost_full_book='100')
    return inputs,policy


def get_alternative(result, identity):
    return next(row for row in result['alternatives'] if row['alternative_id']==identity)


class HedgeMathIndependentReviewTests(unittest.TestCase):
    def test_minimax_does_not_choose_full_zero_beta_blindly(self):
        inputs,policy=fixture()
        result=search_hedges(inputs,policy)
        self.assertEqual(result['best_feasible_hedge_id'],'hedge:index:-4')
        best=get_alternative(result,result['best_feasible_hedge_id'])
        self.assertEqual(Decimal(best['worst_loss']),Decimal('340'))
        self.assertEqual(best['simultaneous_loss_scenario_ids'],['basis-break'])
        self.assertEqual(Decimal(best['factor_exposure_after']),Decimal('2000'))
        # Full beta neutralisation q=-5 worsens the declared basis-break loss.
        self.assertEqual(Decimal(get_alternative(result,'hedge:index:-5')['worst_loss']),Decimal('400'))

    def test_cash_stress_is_not_deducted_again_from_the_hedge_pnl(self):
        inputs,policy=fixture()
        best=get_alternative(search_hedges(inputs,policy),'hedge:index:-4')
        # Margin 1200 + peak VM debit 800 + round-trip costs 40 + buffer 100.
        self.assertEqual(Decimal(best['stressed_cash_required']),Decimal('2140'))
        self.assertEqual(Decimal(best['scenario_pnl']['selloff']),Decimal('-240'))
        self.assertEqual(Decimal(best['scenario_pnl']['rally']),Decimal('160'))
        self.assertEqual(Decimal(best['scenario_pnl']['basis-break']),Decimal('-340'))
        self.assertEqual(Decimal(best['hedge_or_reduction_scenario_pnl']['rally']),Decimal('-840'))

    def test_large_cash_balance_at_another_account_cannot_finance_the_hedge(self):
        inputs,policy=fixture()
        inputs['hedge_accounts'][0]['available_cash']='100'
        other=deepcopy(inputs['hedge_accounts'][0])
        other['route']['account']='rich-other-account'
        other['available_cash']='1000000'
        inputs['hedge_accounts'].append(other)
        result=search_hedges(inputs,policy)
        self.assertIsNone(result['best_feasible_hedge_id'])
        self.assertIn('hedge_account_cash_insufficient',get_alternative(result,'hedge:index:-4')['blockers'])

    def test_upside_budget_changes_the_feasible_hedge_size(self):
        inputs,policy=fixture()
        policy['max_upside_sacrifice']='700'
        result=search_hedges(inputs,policy)
        self.assertEqual(result['best_feasible_hedge_id'],'hedge:index:-3')
        self.assertIn('upside_sacrifice_limit',get_alternative(result,'hedge:index:-4')['blockers'])

    def test_absence_of_basis_break_stress_leaves_hedges_blocked(self):
        inputs,policy=fixture()
        for scenario in inputs['scenarios']:
            scenario['basis_break']=False
        result=search_hedges(inputs,policy)
        self.assertIsNone(result['best_feasible_hedge_id'])
        self.assertIn('simultaneous_loss_basis_stress_missing',get_alternative(result,'hedge:index:-4')['blockers'])

    def test_terminal_variation_loss_cannot_disappear_from_cash_stress(self):
        inputs,policy=fixture()
        inputs['scenarios'][1]['hedges']['index']['short_adverse_cash_per_contract']='199'
        with self.assertRaises(ContractError):
            search_hedges(inputs,policy)

    def test_reduction_is_only_immediate_cost_not_a_second_roundtrip(self):
        inputs,policy=fixture()
        policy['reduction_fractions']=['0','0.25']
        row=get_alternative(search_hedges(inputs,policy),'reduce:0.25')
        self.assertEqual(Decimal(row['total_cost']),Decimal('25'))
        self.assertEqual({k:Decimal(v) for k,v in row['scenario_pnl'].items()},
            {'selloff':Decimal('-775'),'rally':Decimal('725'),'basis-break':Decimal('-100')})

    def test_caller_decimal_precision_does_not_change_the_choice(self):
        inputs,policy=fixture()
        expected=search_hedges(inputs,policy)
        with localcontext() as ctx:
            ctx.prec=3
            actual=search_hedges(inputs,policy)
        self.assertEqual(expected,actual)

    def test_long_short_book_does_not_invent_cash_sale_proceeds(self):
        inputs,policy=fixture()
        inputs['book']['long_only']=False
        policy['reduction_fractions']=['0','0.25']
        row=get_alternative(search_hedges(inputs,policy),'reduce:0.25')
        self.assertFalse(row['feasible'])

    def test_reduction_cost_is_prefunded_without_cross_account_sale_proceeds(self):
        inputs,policy=fixture()
        policy['reduction_fractions']=['0','0.25']
        inputs['hedge_accounts'][0]['available_cash']='24'
        row=get_alternative(search_hedges(inputs,policy),'reduce:0.25')
        self.assertFalse(row['feasible'])

    def test_cross_currency_payoffs_are_not_added_without_fx_conversion(self):
        inputs,policy=fixture()
        inputs['candidates'][0]['currency']='EUR'
        with self.assertRaises(ContractError):
            search_hedges(inputs,policy)
