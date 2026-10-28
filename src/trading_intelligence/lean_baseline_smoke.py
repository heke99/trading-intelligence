"""Pinned synthetic-only LEAN fills -> independent cash-ledger engineering proof."""
import argparse
from decimal import Decimal, localcontext
import json
from pathlib import Path
from uuid import uuid4

from .baseline_fixture import create_fixture, verify_fixture, expected_fills, COSTS, INSTRUMENT, OPENS, DAYS
from .cash_ledger import CashLedgerStore, number
from .contracts import ContractError, utc
from .lean_smoke import IMAGE, PLATFORM, LAUNCHER, _input_hashes, digest, encoded, docker_command, verify_engine_completion
from .lean_smoke import run_prepared as execute_prepared
from .lean_smoke_templates import make_config
from .market_data import timestamp


def baseline_config():
    config=make_config();config['algorithm-type-name']='BaselineFixtureSmoke'
    config['parameters']=dict(fixture_path='/Smoke/input/fixture.json',result_path='/Smoke/output/baseline-evidence.json')
    return config


def prepare(directory):
    root=Path(directory).resolve();name='ti-lean-smoke-'+uuid4().hex
    command=docker_command(root,name)
    if root.exists():raise ContractError('Fresh dedicated baseline directory required')
    (root/'input').mkdir(parents=True);(root/'output').mkdir()
    source=Path(__file__).parent
    for file in source.rglob('*.py'):
        if file.is_symlink():raise ContractError('Source symlinks are forbidden')
        target=root/'input'/'python'/'trading_intelligence'/file.relative_to(source)
        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(file.read_bytes())
    (root/'input'/'algorithm.py').write_bytes((source/'lean_smoke_templates'/'baseline_algorithm.py').read_bytes())
    fixture=create_fixture(root/'input')
    (root/'input'/'fixture.json').write_bytes(encoded(fixture))
    (root/'input'/'prices.jsonl').write_bytes(b''.join((json.dumps(r,sort_keys=True)+'\n').encode() for r in fixture['events']))
    (root/'input'/'config.json').write_bytes(encoded(baseline_config()))
    manifest=dict(schema='lean-synthetic-baseline-input-1',image=IMAGE,platform=PLATFORM,launcher=LAUNCHER,
        container_name=name,origin='synthetic_fixture',synthetic=True,real_dataset_admitted=False,
        expected_observations=fixture['events'],expected_fills=expected_fills(fixture),files=_input_hashes(root/'input'),
        engine_execution_verified=False,training_ready=False,live_trading=False)
    (root/'input-manifest.json').write_bytes(encoded(manifest))
    (root/'docker-command.json').write_bytes(encoded(command))
    verify_inputs(root)
    return dict(status='prepared',scope='synthetic_engine_accounting_only',directory=str(root),
        image=IMAGE,platform=PLATFORM,input_manifest_sha256=digest(encoded(manifest)),
        expected_simulated_orders=len(manifest['expected_fills']),engine_execution_verified=False,
        real_dataset_admitted=False,orders_sent_to_broker=0,live_trading=False)


def verify_inputs(directory):
    root=Path(directory);manifest=json.loads((root/'input-manifest.json').read_bytes())
    if (not isinstance(manifest,dict) or manifest.get('schema')!='lean-synthetic-baseline-input-1' or manifest.get('image')!=IMAGE
            or manifest.get('platform')!=PLATFORM or manifest.get('origin')!='synthetic_fixture'
            or manifest.get('synthetic') is not True
            or any(manifest.get(k) is not False for k in ('real_dataset_admitted','training_ready','live_trading'))
            or manifest.get('files')!=_input_hashes(root/'input')):
        raise ContractError('Invalid or modified synthetic baseline inputs')
    fixture=verify_fixture(root/'input',json.loads((root/'input'/'fixture.json').read_bytes()))
    if json.loads((root/'input'/'config.json').read_bytes())!=baseline_config():
        raise ContractError('Backtest-only keyless configuration changed')
    rows=b''.join((json.dumps(r,sort_keys=True)+'\n').encode() for r in fixture['events'])
    if ((root/'input'/'prices.jsonl').read_bytes()!=rows or manifest['expected_observations']!=fixture['events']
            or manifest['expected_fills']!=expected_fills(fixture)):
        raise ContractError('Fixture event/fill binding changed')
    return manifest


def validate_result(directory,returncode):
    root=Path(directory);manifest=verify_inputs(root);expected=manifest['expected_fills']
    verify_engine_completion(root,returncode,expected_orders=len(expected))
    fixture=json.loads((root/'input'/'fixture.json').read_bytes())
    report=json.loads((root/'output'/'baseline-evidence.json').read_bytes())
    keys={'schema','synthetic','status','decisions','fills','submissions','seen_events','engine_order_count',
          'engine_cash','engine_position','unresolved_intent','unresolved_order','real_dataset_admitted','training_ready','live_trading'}
    if (not isinstance(report,dict) or set(report)!=keys
            or report.get('schema')!='synthetic-lean-baseline-result-1' or report.get('synthetic') is not True
            or report.get('status')!='completed' or report.get('engine_order_count')!=len(expected)
            or report.get('seen_events')!=fixture['events']
            or report.get('decisions')!=fixture['evaluation']['decisions']
            or report.get('unresolved_intent') is not None or report.get('unresolved_order') is not None
            or any(report.get(k) is not False for k in ('real_dataset_admitted','training_ready','live_trading'))):
        raise ContractError('Engine fixture/rule/order acceptance failed')
    fills=report.get('fills');submissions=report.get('submissions')
    if not isinstance(fills,list) or len(fills)!=len(expected) or not isinstance(submissions,list) or len(submissions)!=len(expected):
        raise ContractError('Exact engine fills and submissions required')
    order_ids=set();events=[];commissions=Decimal(0);spread=Decimal(0);slippage=Decimal(0)
    ref=digest(encoded(manifest));at=fixture['events'][0]['available_at']
    events.append(dict(event_id='opening',kind='opening_cash',amount=fixture['initial_cash'],occurred_at=at,
        observed_at=at,currency='USD',origin='synthetic_fixture',source_ref=ref))
    with localcontext() as context:
        context.prec=80
        for fill,expected_fill,submission in zip(fills,expected,submissions):
            if (not isinstance(fill,dict) or set(fill)!={'decision_date','occurred_at','observed_at','order_id','quantity','price','fee','currency'}
                    or type(fill.get('order_id')) is not int or fill['order_id']<=0 or fill['order_id'] in order_ids
                    or fill.get('currency')!='USD' or fill.get('decision_date')!=expected_fill['decision_date']
                    or timestamp(fill['occurred_at'])!=timestamp(expected_fill['occurred_at'])
                    or timestamp(fill['observed_at'])!=timestamp(fill['occurred_at'])
                    or submission!=dict(decision_date=expected_fill['decision_date'],
                        occurred_at=expected_fill['occurred_at'],quantity=expected_fill['quantity'])
                    or Decimal(fill['quantity'])!=Decimal(expected_fill['quantity'])
                    or abs(number(fill['price'],positive=True)-Decimal(expected_fill['price']))>Decimal('0.00000001')
                    or number(fill['fee'])!=Decimal(expected_fill['fee'])):
                raise ContractError('Engine fill differs from independently expected time/quantity/cost')
            order_ids.add(fill['order_id']);quantity=Decimal(fill['quantity'])
            occurred=utc(timestamp(fill['occurred_at']));observed=utc(timestamp(fill['observed_at']))
            events.append(dict(event_id='lean:'+str(fill['order_id']),kind='buy' if quantity>0 else 'sell',
                instrument_id=INSTRUMENT,quantity=format(abs(quantity),'f'),price=fill['price'],fee=fill['fee'],
                occurred_at=occurred,observed_at=observed,currency='USD',origin='synthetic_fixture',source_ref=ref))
            op=Decimal(OPENS[DAYS.index(timestamp(occurred).date().isoformat())])
            commissions+=Decimal(fill['fee'])
            spread+=abs(quantity)*op*Decimal(COSTS['spread_bps'])/2/10000
            slippage+=abs(quantity)*op*Decimal(COSTS['slippage_bps'])/10000
    if Decimal(report['engine_position'])!=0:raise ContractError('Fixture did not close its position')
    ledger_path=root/'output'/'cash-ledger.sqlite3'
    if ledger_path.exists():raise ContractError('Unexpected preexisting accounting ledger')
    ledger=CashLedgerStore(ledger_path)
    try:
        ledger.import_declared_report(encoded(dict(format='offline-cash-events-v1',events=events)))
        state=ledger.state()
        reconciliation=ledger.reconcile(expected_currency='USD',expected_cash=report['engine_cash'],
            expected_positions={},cash_tolerance='0.000001',quantity_tolerance='0')
        # Golden arithmetic is independent of both LEAN's portfolio and the importer.
        if abs(Decimal(state['cash'])-Decimal('979.8376'))>Decimal('0.000001'):
            raise ContractError('Synthetic cash disagrees with hand-checked golden result')
    finally:ledger.close()
    (root/'output'/'cash-events.json').write_bytes(encoded(dict(format='offline-cash-events-v1',events=events)))
    accounting=dict(schema='synthetic-lean-accounting-1',origin='synthetic_fixture',state=state,
        reconciliation=reconciliation,commissions=str(commissions),spread_cost=str(spread),
        slippage_cost=str(slippage),cash_tolerance='0.000001',broker_verified=False)
    (root/'output'/'accounting-evidence.json').write_bytes(encoded(accounting))
    return dict(status='passed',scope='synthetic_engine_accounting_only',image=IMAGE,platform=PLATFORM,
        input_manifest_sha256=ref,engine_execution_verified=True,rule_decisions_verified=True,
        simulated_order_count=len(fills),simulated_round_trips=2,cash_and_positions_reconciled=True,
        synthetic_final_cash=state['cash'],commissions=str(commissions),spread_cost=str(spread),slippage_cost=str(slippage),
        orders_sent_to_broker=0,real_dataset_admitted=False,training_ready=False,live_trading=False,
        strategy_profitability_verified=False,statistical_evaluation=False,
        evidence_files={str(p.relative_to(root)):digest(p.read_bytes()) for p in sorted((root/'output').rglob('*')) if p.is_file()})


def run_prepared(directory,*,timeout=300,runner=None,clock=None):
    return execute_prepared(directory,timeout=timeout,runner=runner,clock=clock,
        input_verifier=verify_inputs,result_validator=validate_result)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare-run']);parser.add_argument('--out',required=True)
    parser.add_argument('--prepare-only',action='store_true');parser.add_argument('--timeout',type=int,default=300)
    args=parser.parse_args()
    try:
        result=prepare(args.out)
        if not args.prepare_only:result=run_prepared(args.out,timeout=args.timeout)
    except (ContractError,OSError,ValueError,KeyError,TypeError) as error:
        parser.exit(2,'Synthetic baseline trial rejected: '+str(error)+'\n')
    print(json.dumps(result,sort_keys=True,indent=2))


if __name__=='__main__':main()
