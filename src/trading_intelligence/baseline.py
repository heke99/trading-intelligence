"""Frozen offline rule/protocol registry. Targets are not fills or LEAN runs."""
from datetime import date, datetime, timedelta, timezone
from decimal import Context, Decimal, DecimalException, DivisionByZero, Inexact, InvalidOperation, Overflow, ROUND_HALF_EVEN, localcontext
import hashlib
import json

from .contracts import ContractError, EvidenceIntegrityError, RecordConflict, required, utc
from .store import EvidenceStore
from .lean_export import verify_bundle

SCHEMA='''
CREATE TABLE IF NOT EXISTS frozen_baselines (
 baseline_id TEXT PRIMARY KEY, registered_at TEXT NOT NULL, semantic_json TEXT NOT NULL,
 payload TEXT NOT NULL, sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS baseline_experiments (
 experiment_id TEXT PRIMARY KEY, registered_at TEXT NOT NULL, semantic_json TEXT NOT NULL,
 payload TEXT NOT NULL, sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS baseline_trials (
 trial_id TEXT PRIMARY KEY, registered_at TEXT NOT NULL, semantic_json TEXT NOT NULL,
 payload TEXT NOT NULL, sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS baseline_evaluations (
 trial_id TEXT NOT NULL, partition TEXT NOT NULL, payload TEXT NOT NULL, sha256 TEXT NOT NULL,
 PRIMARY KEY(trial_id,partition));
CREATE TABLE IF NOT EXISTS consumed_final_scopes (
 instrument_id TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
 trial_id TEXT NOT NULL, consumed_at TEXT NOT NULL, payload TEXT NOT NULL, sha256 TEXT NOT NULL,
 PRIMARY KEY(instrument_id,start_date,end_date,trial_id));
'''
PARTITIONS=('train','validation','final_test')


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def instant(text):return datetime.fromisoformat(text.replace('Z','+00:00'))


def iso_day(text):
    if not isinstance(text,str):raise ContractError('Canonical ISO date required')
    try:day=date.fromisoformat(text)
    except ValueError as exc:raise ContractError('Canonical ISO date required') from exc
    if day.isoformat()!=text:raise ContractError('Canonical ISO date required')
    return day


def amount(text):
    if not isinstance(text,str):raise ContractError('Cost parameters must be decimal strings')
    try:value=Decimal(text)
    except DecimalException as exc:raise ContractError('Invalid cost parameter') from exc
    if not value.is_finite() or value<0:raise ContractError('Finite nonnegative costs required')
    return text


def close_above_mean(closes):
    """Shared exact numerical rule; callers own data/time/admission checks."""
    if not isinstance(closes,list) or not 2<=len(closes)<=252 or any(not isinstance(v,str) for v in closes):
        raise ContractError('Explicit bounded close-price window required')
    try:
        values=[Decimal(v) for v in closes]
        if any(not v.is_finite() or v<=0 for v in values):raise ContractError('Positive finite close prices required')
        with localcontext(Context(prec=80,rounding=ROUND_HALF_EVEN,traps=[Inexact,Overflow,InvalidOperation,DivisionByZero])):
            return '1' if values[-1]*len(values)>sum(values,Decimal(0)) else '0'
    except DecimalException as exc:
        raise ContractError('Baseline exact arithmetic limit exceeded') from exc


class BaselineStore(EvidenceStore):
    def __init__(self,database,*,clock=None):
        super().__init__(database);self.db.executescript(SCHEMA)
        self._baseline_clock=clock or (lambda:datetime.now(timezone.utc))

    def _now(self):return utc(self._baseline_clock())
    def _idle(self):
        if self.db.in_transaction:raise ContractError('Protocol writes require an idle connection')

    def _record(self,table,id_name,identity,semantic):
        self._idle();required(identity,id_name)
        row=self.db.execute(f'SELECT * FROM {table} WHERE {id_name}=?',(identity,)).fetchone()
        if row:
            body=self._verified(row)
            if row['semantic_json']!=canonical(semantic):raise RecordConflict('Frozen registry input differs')
            return body
        body={id_name:identity,'registered_at':self._now(),'semantic':semantic}
        with self.db:
            self.db.execute(f'INSERT INTO {table} VALUES (?,?,?,?,?)',
                            (identity,body['registered_at'],canonical(semantic),canonical(body),digest(body)))
        return body

    def _verified(self,row):
        if row is None:raise ContractError('Unknown protocol record')
        body=json.loads(row['payload'])
        if digest(body)!=row['sha256']:raise EvidenceIntegrityError('Protocol record integrity failed')
        for key in row.keys():
            if key in body and row[key]!=body[key]:raise EvidenceIntegrityError('Protocol index mismatch')
        if 'semantic_json' in row.keys() and canonical(body['semantic'])!=row['semantic_json']:
            raise EvidenceIntegrityError('Frozen protocol index mismatch')
        return body

    def _get(self,table,key,identity):
        body=self._verified(self.db.execute(f'SELECT * FROM {table} WHERE {key}=?',(identity,)).fetchone())
        if body['registered_at']>self._now():raise ContractError('Protocol unavailable at current clock')
        return body

    def freeze_baseline(self,*,baseline_id,universe,lookback,costs,
                        rule='close_gt_sma',decision_timing='after_bar_available',
                        exit_policy='target_zero_when_not_above',benchmark='cash_and_buy_hold',
                        corporate_action_policy='reset_window_on_known_action'):
        if not isinstance(universe,list) or len(universe)!=1:
            raise ContractError('This bounded pilot freezes exactly one explicit listing')
        required(universe[0],'listing_id')
        if type(lookback) is not int or not 2<=lookback<=252:
            raise ContractError('Lookback must be an integer between 2 and 252')
        if (rule,decision_timing,exit_policy,benchmark,corporate_action_policy)!=('close_gt_sma','after_bar_available',
              'target_zero_when_not_above','cash_and_buy_hold','reset_window_on_known_action'):
            raise ContractError('Unsupported rule/policy in this bounded baseline')
        if not isinstance(costs,dict) or set(costs)!={'commission_per_order','spread_bps','slippage_bps','latency_seconds'}:
            raise ContractError('Explicit commission/spread/slippage/latency assumptions required')
        for k in ('commission_per_order','spread_bps','slippage_bps'):amount(costs[k])
        if type(costs['latency_seconds']) is not int or not 0<=costs['latency_seconds']<=86400:
            raise ContractError('Explicit bounded nonnegative latency seconds required')
        return self._record('frozen_baselines','baseline_id',baseline_id,
            dict(universe=universe,rule=rule,lookback=lookback,decision_timing=decision_timing,
                 exit_policy=exit_policy,costs=costs,benchmark=benchmark,corporate_action_policy=corporate_action_policy,
                 arithmetic={'precision':80,'rounding':'ROUND_HALF_EVEN','inexact':'reject'},
                 session_policy='next_explicit_bundle_session_no_skip'))

    def register_experiment(self,*,experiment_id,baseline_id,bundle_directory,partitions,primary_metric,label_horizon_days=0):
        self._idle();required(primary_metric,'primary_metric')
        baseline=self._get('frozen_baselines','baseline_id',baseline_id)
        if not isinstance(partitions,dict) or set(partitions)!=set(PARTITIONS):raise ContractError('Three explicit chronological partitions required')
        if type(label_horizon_days) is not int or not 0<=label_horizon_days<=3650:raise ContractError('Explicit nonnegative calendar label horizon required')
        previous=None
        for name in PARTITIONS:
            bounds=partitions[name]
            if not isinstance(bounds,dict) or set(bounds)!={'start','end'}:raise ContractError('Partition start/end required')
            start,end=iso_day(bounds['start']),iso_day(bounds['end'])
            if start>end or (previous is not None and previous+timedelta(days=label_horizon_days)>=start):
                raise ContractError('Partitions overlap chronologically or by label horizon')
            previous=end
        bundle=verify_bundle(bundle_directory);manifest=bundle['manifest']
        listing=manifest['listing']
        if baseline['semantic']['universe']!=[listing['listing_id']]:raise ContractError('Bundle differs from frozen universe')
        dates={x['date'] for x in bundle['bars']}
        for bounds in partitions.values():
            if not any(bounds['start']<=d<=bounds['end'] for d in dates):raise ContractError('Each partition needs explicit bundled observations')
        return self._record('baseline_experiments','experiment_id',experiment_id,
            dict(baseline_id=baseline_id,baseline_sha256=digest(baseline),dataset_sha256=digest(manifest),
                 listing=listing,partitions=partitions,primary_metric=primary_metric,label_horizon_days=label_horizon_days,
                 evaluation_policy='targets_only_no_fills_or_performance'))

    def register_trial(self,*,trial_id,experiment_id,candidate_id):
        required(candidate_id,'candidate_id');experiment=self._get('baseline_experiments','experiment_id',experiment_id)
        return self._record('baseline_trials','trial_id',trial_id,
            dict(experiment_id=experiment_id,experiment_sha256=digest(experiment),candidate_id=candidate_id))

    def _decisions(self,bundle,contract,bounds):
        bars=bundle['bars'];records=bundle['manifest']['replay']['records']
        sessions={r['date']:r['known_at'] for r in records if r['kind']=='session'}
        actions=[r for r in records if r['kind'] in {'split','cash_dividend'}]
        if [x['date'] for x in bars]!=sorted({x['date'] for x in bars}):
            raise ContractError('Bundle bars must have unique chronological dates')
        result=[];window=[]
        for index,bar in enumerate(bars):
            at=bar['available_at']
            window.append(bar);window=window[-contract['lookback']:]
            known_action_dates=[a['date'] for a in actions if window[0]['date']<a['date']<=bar['date'] and a['known_at']<=at]
            if known_action_dates:
                window=[x for x in window if x['date']>=max(known_action_dates)]
            if not bounds['start']<=bar['date']<=bounds['end']:continue
            reason=None;intent=None;target=None
            if len(window)<contract['lookback']:reason='warmup'
            elif any(x['available_at']>at for x in window):reason='lookback_unavailable_at_decision'
            elif any(x['date']>bar['date'] and x['available_at']<=at for x in bars):reason='superseded_by_newer_available_bar'
            else:
                ready=instant(at)+timedelta(seconds=contract['costs']['latency_seconds'])
                next_session=bars[index+1] if index+1<len(bars) else None
                if next_session is None:reason='no_next_declared_session'
                elif sessions.get(next_session['date'],'~')>at:reason='next_session_calendar_unavailable'
                elif instant(next_session['start'])<ready:reason='missed_next_session_open'
                elif next_session['date']>bounds['end']:reason='outside_evaluation_partition'
                else:
                    target=close_above_mean([x['close'] for x in window])
                    intent=dict(type='next_session_open_target',session_date=next_session['date'],
                                not_before=utc(ready),intended_at=next_session['start'],target_weight=target,
                                is_fill=False,is_order_authorization=False)
            result.append(dict(date=bar['date'],decision_at=at,action='abstain' if reason else 'target',
                               target_weight=target,reason=reason,intent=intent))
        return result

    def evaluate_trial(self,*,trial_id,bundle_directory,partition):
        self._idle()
        if partition not in PARTITIONS:raise ContractError('Unknown evaluation partition')
        trial=self._get('baseline_trials','trial_id',trial_id)
        exp=self._get('baseline_experiments','experiment_id',trial['semantic']['experiment_id'])
        baseline=self._get('frozen_baselines','baseline_id',exp['semantic']['baseline_id'])
        if digest(exp)!=trial['semantic']['experiment_sha256'] or digest(baseline)!=exp['semantic']['baseline_sha256']:
            raise EvidenceIntegrityError('Frozen protocol binding changed')
        bundle=verify_bundle(bundle_directory)
        if digest(bundle['manifest'])!=exp['semantic']['dataset_sha256']:raise RecordConflict('Trial bundle differs from registered dataset')
        old=self.db.execute('SELECT * FROM baseline_evaluations WHERE trial_id=? AND partition=?',(trial_id,partition)).fetchone()
        if old:return self._verified(old)
        bounds=exp['semantic']['partitions'][partition];now=self._now()
        if partition=='final_test':
            instrument=exp['semantic']['listing']['instrument_id']
            # Global canonical instrument/time overlap survives new baseline,
            # experiment, trial, candidate, source and bundle identifiers.
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                previous=self.db.execute('SELECT * FROM consumed_final_scopes WHERE instrument_id=? '
                    'AND start_date<=? AND end_date>=?',(instrument,bounds['end'],bounds['start'])).fetchall()
                for row in previous:self._verified(row)
                if previous:raise ContractError('Final-test period already consumed for this instrument')
                consumed=dict(instrument_id=instrument,start_date=bounds['start'],end_date=bounds['end'],trial_id=trial_id,consumed_at=now)
                # Consume before strategy outputs; a failed evaluation still
                # cannot claim this period as an untouched final test again.
                self.db.execute('INSERT INTO consumed_final_scopes VALUES (?,?,?,?,?,?,?)',
                    (instrument,bounds['start'],bounds['end'],trial_id,now,canonical(consumed),digest(consumed)))
        try:
            decisions=self._decisions(bundle,baseline['semantic'],bounds)
        except DecimalException as exc:
            raise ContractError('Baseline exact arithmetic limit exceeded') from exc
        report=dict(trial_id=trial_id,partition=partition,evaluated_at=now,experiment_sha256=digest(exp),
                    baseline_sha256=digest(baseline),dataset_sha256=exp['semantic']['dataset_sha256'],
                    decisions=decisions,final_test_consumed=partition=='final_test',
                    costs_applied=False,performance_computed=False,lean_runtime_verified=False,
                    training_implemented=False,live_trading=False,synthetic=True)
        with self.db:
            self.db.execute('INSERT INTO baseline_evaluations VALUES (?,?,?,?)',(trial_id,partition,canonical(report),digest(report)))
        return report


def baseline_demo(directory):
    """Repeatable synthetic-only frozen rule/trial protocol demonstration."""
    from pathlib import Path
    from .contracts import AssetKind,DataOrigin,Entity,Instrument,Listing,Use
    from .market_data import MarketDataStore
    from .lean_export import export_bundle
    path=Path(directory);path.mkdir(parents=True,exist_ok=True)
    days=['2026-01-05','2026-01-06','2026-01-07','2026-01-08','2026-01-09','2026-01-12','2026-01-13']
    known=datetime(2026,1,1,tzinfo=timezone.utc);now=datetime(2026,1,20,tzinfo=timezone.utc)
    with MarketDataStore(path/'market.sqlite') as market:
        market.register_source('baseline-fixture',DataOrigin.SYNTHETIC)
        market.set_permissions('baseline-fixture',known_at=known,uses={Use.STORAGE,Use.RESEARCH})
        market.register_entity(Entity('baseline-issuer','Invented baseline issuer'))
        market.register_instrument(Instrument('baseline-instrument','baseline-issuer',AssetKind.EQUITY))
        market.register_listing(Listing('baseline-listing','baseline-instrument','XNYS','USD'))
        for index,day in enumerate(days):
            common=dict(listing_id='baseline-listing',date=day,start=day+'T14:30:00Z',end=day+'T21:00:00Z',currency='USD')
            session=dict(common,kind='session',values={'timezone':'America/New_York'})
            market.import_record(source_id='baseline-fixture',record_id='session-'+day,revision_id='1',
                payload=canonical(session).encode(),published_at=known,received_at=known,processed_at=known)
            close=str(100+index)
            bar=dict(common,kind='bar',values=dict(open=close,high=close,low=close,close=close,volume='20',price_kind='raw'))
            end=instant(common['end'])
            market.import_record(source_id='baseline-fixture',record_id='bar-'+day,revision_id='1',
                payload=canonical(bar).encode(),published_at=end,received_at=end+timedelta(seconds=1),processed_at=end+timedelta(seconds=2))
        export_bundle(market,'baseline-fixture','baseline-listing',days,as_of=now,directory=path/'bundle',clock=lambda:now)
    with BaselineStore(path/'protocol.sqlite',clock=lambda:now) as protocol:
        protocol.freeze_baseline(baseline_id='demo-baseline',universe=['baseline-listing'],lookback=2,
            costs={'commission_per_order':'1','spread_bps':'2','slippage_bps':'1','latency_seconds':1})
        protocol.register_experiment(experiment_id='demo-experiment',baseline_id='demo-baseline',bundle_directory=path/'bundle',
            partitions={'train':{'start':days[0],'end':days[1]},'validation':{'start':days[2],'end':days[4]},
                        'final_test':{'start':days[5],'end':days[6]}},primary_metric='future_LEAN_net_result_not_yet_computed')
        protocol.register_trial(trial_id='demo-trial',experiment_id='demo-experiment',candidate_id='demo-fixed-rule')
        validation=protocol.evaluate_trial(trial_id='demo-trial',bundle_directory=path/'bundle',partition='validation')
        final=protocol.evaluate_trial(trial_id='demo-trial',bundle_directory=path/'bundle',partition='final_test')
        protocol.register_trial(trial_id='demo-new-trial-id',experiment_id='demo-experiment',candidate_id='demo-new-candidate-id')
        reuse_blocked=False
        try:protocol.evaluate_trial(trial_id='demo-new-trial-id',bundle_directory=path/'bundle',partition='final_test')
        except ContractError:reuse_blocked=True
        report=dict(synthetic=True,validation_decisions=len(validation['decisions']),
                    validation_intents=sum(x['intent'] is not None for x in validation['decisions']),
                    final_test_consumed=final['final_test_consumed'],renamed_trial_cannot_reset_final_test=reuse_blocked,
                    costs_applied=False,performance_computed=False,lean_runtime_verified=False,
                    training_implemented=False,live_trading=False)
    (path/'baseline-report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report
