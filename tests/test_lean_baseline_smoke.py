"""Mocked engine artifacts and callback doubles, never actual LEAN evidence."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from trading_intelligence.baseline import close_above_mean
from trading_intelligence.contracts import ContractError
from trading_intelligence.lean_baseline_smoke import prepare, verify_inputs, run_prepared, validate_result
from trading_intelligence.baseline_fixture import verify_fixture, expected_fills
from trading_intelligence.market_data import timestamp
from trading_intelligence.lean_smoke import _input_hashes, encoded


GOLDEN=[('2026-01-07','2026-01-08','2','102.0204'),('2026-01-08','2026-01-09','-2','94.981'),
        ('2026-01-12','2026-01-13','2','105.021'),('2026-01-13','2026-01-14','-2','103.9792')]


class BaselineSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'trial';self.prepared=prepare(self.root)
        self.fixture=json.loads((self.root/'input'/'fixture.json').read_bytes())
        self.change=lambda report:None

    def report(self):
        fills=[dict(order_id=i,decision_date=decision,occurred_at=day+'T14:30:00Z',
            observed_at=day+'T14:30:00Z',quantity=quantity,price=price,fee='1',currency='USD')
            for i,(decision,day,quantity,price) in enumerate(GOLDEN,start=1)]
        return dict(schema='synthetic-lean-baseline-result-1',synthetic=True,status='completed',
            decisions=self.fixture['evaluation']['decisions'],seen_events=self.fixture['events'],
            fills=fills,submissions=[dict(decision_date=d,occurred_at=day+'T14:30:00Z',quantity=q) for d,day,q,p in GOLDEN],
            engine_order_count=4,engine_cash='979.8376',engine_position='0',unresolved_intent=None,
            unresolved_order=None,real_dataset_admitted=False,training_ready=False,live_trading=False)

    def final(self,orders='4'):
        (self.root/'output'/'BaselineFixtureSmoke-summary.json').write_text(json.dumps(dict(
            state=dict(Status='Completed',RuntimeError='',StackTrace='',OrderCount=orders,EndTime='done'))))

    def runner(self,command,*,stdout,stderr,timeout,check):
        report=self.report();self.change(report)
        (self.root/'output'/'baseline-evidence.json').write_text(json.dumps(report));self.final()
        return SimpleNamespace(returncode=0)

    def test_fixture_produces_hand_checked_next_open_costs_and_two_round_trips(self):
        expected=expected_fills(self.fixture)
        self.assertEqual([(x['decision_date'],timestamp(x['occurred_at']).date().isoformat(),x['quantity'],x['price']) for x in expected],GOLDEN)
        self.assertEqual([d['target_weight'] for d in self.fixture['evaluation']['decisions']],['1','0','0','1','0',None])
        self.assertEqual(self.prepared['expected_simulated_orders'],4)
        self.assertFalse(self.prepared['engine_execution_verified'])

    def test_mocked_engine_callbacks_reconcile_with_cash_ledger_and_golden_cash(self):
        result=run_prepared(self.root,runner=self.runner)
        self.assertEqual(result['status'],'passed')
        self.assertEqual(Decimal(result['synthetic_final_cash']),Decimal('979.8376'))
        self.assertEqual(Decimal(result['commissions']),4)
        self.assertEqual(Decimal(result['spread_cost']),Decimal('.0812'))
        self.assertEqual(Decimal(result['slippage_cost']),Decimal('.0812'))
        self.assertEqual(result['simulated_order_count'],4)
        self.assertEqual(result['orders_sent_to_broker'],0)
        self.assertFalse(result['strategy_profitability_verified']);self.assertFalse(result['statistical_evaluation'])
        self.assertFalse(result['real_dataset_admitted']);self.assertFalse(result['training_ready'])
        evidence=json.loads((self.root/'output'/'accounting-evidence.json').read_bytes())
        self.assertEqual(evidence['state']['positions'],{})
        self.assertTrue(evidence['reconciliation']['matches'])

    def rejected(self,change):
        self.change=change
        with self.assertRaises(ContractError):run_prepared(self.root,runner=self.runner)
        result=json.loads((self.root/'run-result.json').read_bytes())
        self.assertEqual(result['status'],'failed')
        self.assertFalse(result['engine_observation_verified'])

    def test_wrong_fill_price_is_rejected(self):self.rejected(lambda r:r['fills'][0].update(price='102'))
    def test_wrong_fee_is_rejected(self):self.rejected(lambda r:r['fills'][0].update(fee='0'))
    def test_wrong_quantity_is_rejected(self):self.rejected(lambda r:r['fills'][0].update(quantity='1'))
    def test_duplicate_order_id_is_rejected(self):self.rejected(lambda r:r['fills'][1].update(order_id=1))
    def test_early_fill_is_rejected(self):self.rejected(lambda r:r['fills'][0].update(occurred_at='2026-01-07T21:00:01Z'))
    def test_observation_before_fill_is_rejected(self):self.rejected(lambda r:r['fills'][0].update(observed_at='2026-01-07T21:00:01Z'))
    def test_delayed_callback_is_rejected_by_the_immediate_fixture_contract(self):self.rejected(lambda r:r['fills'][0].update(observed_at='2026-01-08T14:30:01Z'))
    def test_missing_completion_field_is_not_assumed_resolved(self):self.rejected(lambda r:r.pop('unresolved_order'))
    def test_missing_fill_is_rejected(self):self.rejected(lambda r:r['fills'].pop())
    def test_open_position_is_rejected(self):self.rejected(lambda r:r.update(engine_position='2'))
    def test_wrong_engine_cash_is_rejected(self):self.rejected(lambda r:r.update(engine_cash='1000'))
    def test_wrong_rule_decision_is_rejected(self):self.rejected(lambda r:r['decisions'][0].update(target_weight='0'))
    def test_real_dataset_claim_is_rejected(self):self.rejected(lambda r:r.update(real_dataset_admitted=True))

    def test_stale_output_is_never_reused(self):
        run_prepared(self.root,runner=self.runner)
        with self.assertRaisesRegex(ContractError,'empty'):run_prepared(self.root,runner=self.runner)

    def test_engine_failure_precedes_missing_callback_artifact(self):
        def failure(command,**kwargs):
            kwargs['stdout'].write('ERROR:: fixture failure\n');return SimpleNamespace(returncode=1)
        with self.assertRaises(ContractError):run_prepared(self.root,runner=failure)
        result=json.loads((self.root/'run-result.json').read_bytes())
        self.assertEqual(result['error_code'],'engine_log_error')

    def test_input_mutation_and_real_source_relabelling_are_blocked(self):
        (self.root/'input'/'prices.jsonl').write_text('{}\n')
        with self.assertRaises(ContractError):verify_inputs(self.root)
        self.fixture['synthetic']=False
        with self.assertRaises(ContractError):verify_fixture(self.root/'input',self.fixture)

    def test_rehashed_live_configuration_is_still_rejected_before_docker(self):
        config_path=self.root/'input'/'config.json';config=json.loads(config_path.read_bytes())
        config['live-mode']=True;config_path.write_bytes(encoded(config))
        path=self.root/'input-manifest.json';manifest=json.loads(path.read_bytes())
        manifest['files']=_input_hashes(self.root/'input');path.write_bytes(encoded(manifest))
        with self.assertRaisesRegex(ContractError,'configuration changed'):verify_inputs(self.root)

    def test_exact_rule_is_independent_of_external_decimal_context(self):
        with localcontext() as ctx:
            ctx.prec=2
            self.assertEqual(close_above_mean(['100.0123456789','100.0123456790']),'1')
        for values in (['1'],['1','NaN'],['1','-2'],[1,2]):
            with self.assertRaises(ContractError):close_above_mean(values)

    def algorithm(self):
        from trading_intelligence import lean_smoke_templates
        states=SimpleNamespace(FILLED='filled',INVALID='invalid',CANCELED='canceled',PARTIALLY_FILLED='partial')
        class Price(dict):pass
        class Holding:
            quantity=Decimal(0)
        class Portfolio:
            def __init__(self):self.cash=Decimal(0);self.holding=Holding()
            def __getitem__(self,key):return self.holding
        class Security:
            symbol='fixture';is_tradable=False
            def set_fill_model(self,model):pass
            def set_fee_model(self,model):self.fee=model
            def set_slippage_model(self,model):self.slippage=model
        class Algorithm:
            live_mode=False
            def __init__(self):
                self.portfolio=Portfolio();self.transactions=SimpleNamespace(orders_count=0)
            def set_time_zone(self,*args):pass
            def set_start_date(self,*args):pass
            def set_end_date(self,*args):self.end_date=datetime(*args,tzinfo=timezone.utc)+timedelta(days=1,microseconds=-1)
            def set_cash(self,value):self.portfolio.cash=Decimal(str(value))
            def set_benchmark(self,*args):pass
            def add_data(self,*args):self.security=Security();return self.security
            def market_order(self,symbol,quantity,**kwargs):
                self.transactions.orders_count+=1
                op=Decimal(self.current['price']);shift=op*Decimal(str(self.security.slippage))
                price=op+shift if quantity>0 else op-shift
                fee=Decimal(str(self.security.fee))
                self.portfolio.cash-=Decimal(quantity)*price+fee
                self.portfolio.holding.quantity+=quantity
                event=SimpleNamespace(symbol='fixture',status=states.FILLED,utc_time=self.utc_time,
                    order_id=self.transactions.orders_count,fill_quantity=Decimal(quantity),fill_price=price,
                    order_fee=SimpleNamespace(value=SimpleNamespace(amount=fee,currency='USD')))
                self.on_order_event(event)
                return SimpleNamespace(status=states.FILLED)
        fake=SimpleNamespace(PythonData=Price,QCAlgorithm=Algorithm,TimeZones=SimpleNamespace(UTC='UTC'),
            Resolution=SimpleNamespace(MINUTE='minute'),OrderStatus=states,ImmediateFillModel=lambda:None,
            ConstantFeeModel=lambda fee,currency:fee,ConstantSlippageModel=lambda rate:rate)
        path=Path(lean_smoke_templates.__file__).parent/'baseline_algorithm.py'
        with patch.dict(sys.modules,{'AlgorithmImports':fake}):
            spec=importlib.util.spec_from_file_location('baseline_algorithm_test',path)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        algorithm=module.BaselineFixtureSmoke()
        parameters=dict(fixture_path=str(self.root/'input'/'fixture.json'),result_path=str(self.root/'output'/'baseline-evidence.json'))
        algorithm.get_parameter=lambda key:parameters[key];algorithm.initialize()
        return module,algorithm

    def test_actual_template_callbacks_follow_rule_and_export_reconcilable_fills(self):
        module,algorithm=self.algorithm()
        for row in self.fixture['events']:
            algorithm.current=row;algorithm.utc_time=timestamp(row['available_at'])
            point=module.SyntheticPrice().reader(SimpleNamespace(symbol='fixture'),json.dumps(row),None,False)
            class Slice:
                def contains_key(self,key):return True
                def __getitem__(self,key):return point
            algorithm.on_data(Slice())
        algorithm.on_end_of_algorithm()
        (self.root/'output'/'engine.log').write_text('');self.final()
        result=validate_result(self.root,0)
        self.assertEqual(result['status'],'passed')
        self.assertEqual(Decimal(result['synthetic_final_cash']),Decimal('979.8376'))

    def test_actual_template_rejects_an_early_event_before_any_order(self):
        module,algorithm=self.algorithm();row=self.fixture['events'][0]
        algorithm.utc_time=timestamp(row['available_at'])-timedelta(seconds=1)
        class Slice:
            def contains_key(self,key):return True
            def __getitem__(self,key):return dict(event_json=json.dumps(row))
        with self.assertRaisesRegex(ValueError,'Early'):algorithm.on_data(Slice())
        self.assertEqual(algorithm.transactions.orders_count,0)

    def test_cli_preparation_does_not_claim_an_engine_run(self):
        other=Path(self.tmp.name)/'cli'
        process=subprocess.run([sys.executable,'-m','trading_intelligence.lean_baseline_smoke','prepare-run',
            '--out',str(other),'--prepare-only'],capture_output=True,text=True)
        self.assertEqual(process.returncode,0,process.stderr)
        self.assertFalse(json.loads(process.stdout)['engine_execution_verified'])
