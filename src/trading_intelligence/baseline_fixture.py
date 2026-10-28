"""Authored synthetic engineering fixture, never a market-data admission path."""
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from pathlib import Path
import tempfile

from .baseline import BaselineStore, canonical, digest
from .contracts import AssetKind, ContractError, DataOrigin, Entity, Instrument, Listing, Use
from .lean_export import export_bundle, verify_bundle
from .market_data import MarketDataStore

DAYS=['2026-01-05','2026-01-06','2026-01-07','2026-01-08','2026-01-09',
      '2026-01-12','2026-01-13','2026-01-14','2026-01-15','2026-01-16']
OPENS=['100','101','104','102','95','96','105','104','100','99']
CLOSES=['100','102','104','98','96','103','101','105','99','100']
COSTS=dict(commission_per_order='1',spread_bps='2',slippage_bps='1',latency_seconds=1)
LISTING='synthetic-baseline-listing'
INSTRUMENT='synthetic-baseline-instrument'


def price_events():
    return [dict(date=day,kind=kind,available_at=day+at,price=price)
            for day,op,cl in zip(DAYS,OPENS,CLOSES)
            for kind,at,price in [('open','T14:30:00.000000Z',op),('close','T21:00:01.000000Z',cl)]]


def create_fixture(directory):
    directory=Path(directory);calendar_at=datetime(2026,1,1,tzinfo=timezone.utc)
    cutoff=datetime(2026,1,20,tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as temp:
        with MarketDataStore(Path(temp)/'market.sqlite3') as market:
            market.register_source('synthetic-baseline',DataOrigin.SYNTHETIC)
            market.set_permissions('synthetic-baseline',known_at=calendar_at,uses={Use.STORAGE,Use.RESEARCH})
            market.register_entity(Entity('synthetic-issuer','Invented baseline issuer'))
            market.register_instrument(Instrument(INSTRUMENT,'synthetic-issuer',AssetKind.EQUITY))
            market.register_listing(Listing(LISTING,INSTRUMENT,'XNAS','USD'))
            for day,op,cl in zip(DAYS,OPENS,CLOSES):
                common=dict(listing_id=LISTING,date=day,start=day+'T14:30:00Z',end=day+'T21:00:00Z',currency='USD')
                session=dict(common,kind='session',values=dict(timezone='America/New_York'))
                market.import_record(source_id='synthetic-baseline',record_id='session:'+day,revision_id='1',
                    payload=canonical(session).encode(),published_at=calendar_at,received_at=calendar_at,processed_at=calendar_at)
                observed=datetime.fromisoformat(day+'T21:00:01+00:00')
                bar=dict(common,kind='bar',values=dict(open=op,high=str(max(Decimal(op),Decimal(cl))+1),
                    low=str(min(Decimal(op),Decimal(cl))-1),close=cl,volume='1000',price_kind='raw'))
                market.import_record(source_id='synthetic-baseline',record_id='bar:'+day,revision_id='1',
                    payload=canonical(bar).encode(),published_at=observed,received_at=observed,processed_at=observed)
            bundle=export_bundle(market,'synthetic-baseline',LISTING,DAYS,as_of=cutoff,
                                 directory=directory/'bundle',clock=lambda:cutoff)
        with BaselineStore(Path(temp)/'protocol.sqlite3',clock=lambda:cutoff) as protocol:
            baseline=protocol.freeze_baseline(baseline_id='fixture-baseline',universe=[LISTING],lookback=2,costs=COSTS)
            experiment=protocol.register_experiment(experiment_id='fixture-experiment',baseline_id='fixture-baseline',
                bundle_directory=directory/'bundle',partitions=dict(train=dict(start=DAYS[0],end=DAYS[1]),
                    validation=dict(start=DAYS[2],end=DAYS[7]),final_test=dict(start=DAYS[8],end=DAYS[9])),
                primary_metric='synthetic_engine_accounting_agreement_only')
            trial=protocol.register_trial(trial_id='fixture-trial',experiment_id='fixture-experiment',candidate_id='frozen-fixture')
            evaluation=protocol.evaluate_trial(trial_id='fixture-trial',bundle_directory=directory/'bundle',partition='validation')
    return dict(schema='synthetic-lean-baseline-1',synthetic=True,real_dataset_admitted=False,
        registration_is_synthetic=True,initial_cash='1000',max_position_units=2,currency='USD',
        instrument_id=INSTRUMENT,listing_id=LISTING,events=price_events(),
        sessions=[dict(date=d,start=d+'T14:30:00Z',known_at='2026-01-01T00:00:00.000000Z') for d in DAYS],
        baseline=baseline,experiment=experiment,trial=trial,evaluation=evaluation,
        bundle_manifest_sha256=digest(bundle['manifest']),corporate_actions='authored_fixture_none',
        allocation_policy='binary_target_clipped_to_two_whole_units',training_ready=False,live_trading=False)


def verify_fixture(directory,fixture):
    bundle=verify_bundle(Path(directory)/'bundle')
    if (not isinstance(fixture,dict) or fixture.get('schema')!='synthetic-lean-baseline-1' or fixture.get('synthetic') is not True
            or fixture.get('registration_is_synthetic') is not True
            or any(fixture.get(k) is not False for k in ('real_dataset_admitted','training_ready','live_trading'))
            or fixture.get('events')!=price_events() or fixture.get('max_position_units')!=2
            or fixture.get('initial_cash')!='1000' or fixture.get('instrument_id')!=INSTRUMENT
            or fixture.get('listing_id')!=LISTING
            or fixture.get('currency')!='USD' or fixture.get('allocation_policy')!='binary_target_clipped_to_two_whole_units'
            or fixture.get('corporate_actions')!='authored_fixture_none'
            or fixture.get('bundle_manifest_sha256')!=digest(bundle['manifest'])):
        raise ContractError('Only the exact authored synthetic baseline fixture is supported')
    if ([b['date'] for b in bundle['bars']]!=DAYS or fixture.get('sessions')!=
            [dict(date=d,start=d+'T14:30:00Z',known_at='2026-01-01T00:00:00.000000Z') for d in DAYS]):
        raise ContractError('Authored fixture session scope changed')
    for row,day,op,cl in zip(bundle['bars'],DAYS,OPENS,CLOSES):
        if (row['date'],row['open'],row['close'])!=(day,op,cl):raise ContractError('Synthetic bar fixture changed')
    base=fixture['baseline'];exp=fixture['experiment'];trial=fixture['trial'];evaluation=fixture['evaluation']
    if (base['semantic']['lookback']!=2 or base['semantic']['costs']!=COSTS
            or base['semantic']['rule']!='close_gt_sma' or base['semantic']['universe']!=[LISTING]
            or exp['semantic']['partitions']!=dict(train=dict(start=DAYS[0],end=DAYS[1]),
                validation=dict(start=DAYS[2],end=DAYS[7]),final_test=dict(start=DAYS[8],end=DAYS[9]))
            or exp['semantic']['baseline_sha256']!=digest(base)
            or exp['semantic']['dataset_sha256']!=digest(bundle['manifest'])
            or trial['semantic']['experiment_sha256']!=digest(exp)
            or evaluation['baseline_sha256']!=digest(base) or evaluation['experiment_sha256']!=digest(exp)
            or evaluation['dataset_sha256']!=digest(bundle['manifest'])
            or evaluation['partition']!='validation' or evaluation['final_test_consumed'] is not False):
        raise ContractError('Frozen baseline/experiment binding mismatch')
    decisions=BaselineStore._decisions(None,bundle,base['semantic'],exp['semantic']['partitions']['validation'])
    if evaluation['decisions']!=decisions:raise ContractError('Expected decisions differ from frozen protocol')
    return fixture


def expected_fills(fixture):
    """Independent deterministic check, not a substitute for actual engine fills."""
    result=[];position=0
    for decision in fixture['evaluation']['decisions']:
        if decision['intent'] is None:continue
        target=int(decision['target_weight'])*fixture['max_position_units'];quantity=target-position
        if not quantity:continue
        intent=decision['intent'];op=Decimal(OPENS[DAYS.index(intent['session_date'])])
        with localcontext() as ctx:
            ctx.prec=80
            adverse=op*(Decimal(COSTS['spread_bps'])/2+Decimal(COSTS['slippage_bps']))/10000
            price=op+adverse if quantity>0 else op-adverse
        result.append(dict(decision_date=decision['date'],occurred_at=intent['intended_at'],
            quantity=str(quantity),price=format(price,'f'),fee=COSTS['commission_per_order'],currency='USD'))
        position=target
    return result
