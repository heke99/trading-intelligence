"""Frozen forward observation pilot: GET capture and abstention journal, no orders."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from .alpaca_calendar import AlpacaCalendarStore
from .alpaca_calendar_reader import AlpacaCalendarReader
from .alpaca_price_reader import AlpacaPriceReader
from .alpaca_reader import AlpacaReferenceReader, PAPER_HOST
from .baseline import BaselineStore, canonical, digest
from .brokers import BrokerAccount, Environment
from .calendar_sync import sync_calendar
from .captured_admission import assess_captured, capture_scope
from .captured_observations import inspect_captures
from .captured_smoke import readonly_captures
from .contracts import ContractError, EvidenceIntegrityError, RecordConflict, Use, required, utc
from .data_admission import DataAdmissionStore
from .market_data import timestamp
from .price_sync import sync_prices

SCHEMA='''CREATE TABLE forward_pilots (
 pilot_id TEXT PRIMARY KEY, registered_at TEXT NOT NULL, semantic_json TEXT NOT NULL,
 payload TEXT NOT NULL, sha256 TEXT NOT NULL);
CREATE TABLE forward_events (
 pilot_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL,
 known_at TEXT NOT NULL, previous_sha TEXT, payload TEXT NOT NULL, sha256 TEXT NOT NULL,
 PRIMARY KEY(pilot_id,sequence), UNIQUE(pilot_id,event_id));'''
DEFAULT_COSTS=dict(commission_per_order='1',spread_bps='2',slippage_bps='1',latency_seconds=1)


def private_json(path,body):
    with open(path,'x',opener=lambda name,flags:os.open(name,flags,0o600)) as stream:
        json.dump(body,stream,sort_keys=True,indent=2);stream.write('\n')


class ForwardStore(BaselineStore):
    def __init__(self,database,*,clock=None,create=False):
        path=Path(database)
        if create:
            path.touch(mode=0o600,exist_ok=False)
            super().__init__(path,clock=clock);self.db.executescript(SCHEMA)
        else:
            self.db=sqlite3.connect(path.resolve().as_uri()+'?mode=rw',uri=True)
            self.db.row_factory=sqlite3.Row
            self._baseline_clock=clock or (lambda:datetime.now(timezone.utc))

    def pilot(self,pilot_id):
        plan=self._get('forward_pilots','pilot_id',pilot_id)
        baseline=self._get('frozen_baselines','baseline_id',plan['semantic']['baseline_id'])
        if digest(baseline)!=plan['semantic']['baseline_sha256']:
            raise EvidenceIntegrityError('Forward baseline binding changed')
        return plan

    def journal(self,pilot_id):
        self.pilot(pilot_id);events=[];previous=None;last=None;now=self._now()
        for index,row in enumerate(self.db.execute('SELECT * FROM forward_events WHERE pilot_id=? ORDER BY sequence',(pilot_id,))):
            event=self._verified(row)
            if event['sequence']!=index or event['previous_sha']!=previous or event['known_at']>now or (last and event['known_at']<last):
                raise EvidenceIntegrityError('Forward journal chain or clock mismatch')
            events.append(event);previous=digest(event);last=event['known_at']
        return events

    def append(self,pilot_id,event_id,semantic,*,require_new=False):
        self._idle();required(event_id,'event_id');plan=self.pilot(pilot_id)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            events=self.journal(pilot_id)
            for old in events:
                if old['event_id']==event_id:
                    if require_new:raise RecordConflict('Forward event is already reserved')
                    if old['semantic']!=semantic:raise RecordConflict('Forward event ID belongs to different input')
                    return old
            at=self._now()
            if at<plan['registered_at'] or (events and at<events[-1]['known_at']):
                raise ContractError('Forward operational clock moved backwards')
            body=dict(pilot_id=pilot_id,sequence=len(events),event_id=event_id,known_at=at,
                previous_sha=digest(events[-1]) if events else None,semantic=semantic)
            self.db.execute('INSERT INTO forward_events VALUES (?,?,?,?,?,?,?)',
                (pilot_id,len(events),event_id,at,body['previous_sha'],canonical(body),digest(body)))
        return body


def prepare(directory,*,database,pilot_id,price_source_id,price_import_id,calendar_source_id,
            calendar_import_id,listing_id,lookback=5,costs=None,clock=None):
    now=clock or (lambda:datetime.now(timezone.utc));checked=now()
    with readonly_captures(database) as captured:
        review=DataAdmissionStore.__new__(DataAdmissionStore);review.db=captured.db
        packet=assess_captured(review,intended_use='forward_observation',price_source_id=price_source_id,
            price_import_id=price_import_id,calendar_source_id=calendar_source_id,
            calendar_import_id=calendar_import_id,listing_id=listing_id,clock=lambda:checked)
    seed=packet['inspection'];route=seed['calendar_lineage']['provenance']['route']
    if route['environment']!='paper':raise ContractError('Paper observation route required')
    root=Path(directory);root.mkdir(mode=0o700,parents=True,exist_ok=False)
    with ForwardStore(root/'protocol.sqlite3',clock=now,create=True) as store:
        baseline=store.freeze_baseline(baseline_id=pilot_id+':baseline',universe=[listing_id],
            lookback=lookback,costs=DEFAULT_COSTS if costs is None else costs)
        plan=store._record('forward_pilots','pilot_id',pilot_id,dict(baseline_id=baseline['baseline_id'],
            baseline_sha256=digest(baseline),seed_scope=capture_scope(seed),route=route,
            symbol=seed['query']['symbols'],listing=seed['listing'],
            calendar_venue=seed['observations'][0]['calendar_venue'],
            start_date=seed['observations'][0]['economic_date'],
            expires_at=utc(checked+timedelta(days=60)),
            collection_policy='previous_new_york_date_after_declared_session_close',
            mode='observe_only',costs_are_assumptions=True,
            seed_is_warmup_only=True,seed_dataset_admitted=False,
            strategy_execution_enabled=False,live_trading=False))
        store.append(pilot_id,'prepared',dict(type='prepared',seed_inspection_sha256=seed['inspection_sha256'],
            seed_observation_count=len(seed['observations']),admission_reasons=packet['assessment']['reasons'],
            initial_assessment_sha256=digest(packet['assessment']),
            decision=dict(action='abstain',reason='real_dataset_admission_not_established',target_weight=None)))
    private_json(root/'seed-inspection.json',seed)
    private_json(root/'initial-assessment.json',packet['assessment'])
    private_json(root/'plan.json',plan)
    return status(root,pilot_id=pilot_id,clock=now)


def status(directory,*,pilot_id,clock=None):
    root=Path(directory)
    with ForwardStore(root/'protocol.sqlite3',clock=clock) as store:
        plan=store.pilot(pilot_id);events=store.journal(pilot_id)
    # Check the separate frozen plan/seed artifacts as well as the database.
    if json.loads((root/'plan.json').read_bytes())!=plan:
        raise EvidenceIntegrityError('Forward plan file differs from frozen protocol')
    seed=json.loads((root/'seed-inspection.json').read_bytes())
    if capture_scope(seed)!=plan['semantic']['seed_scope']:
        raise EvidenceIntegrityError('Forward seed scope changed')
    prepared=[e for e in events if e['semantic']['type']=='prepared']
    if len(prepared)!=1 or prepared[0]['semantic']['seed_inspection_sha256']!=seed['inspection_sha256']:
        raise EvidenceIntegrityError('Forward seed differs from preparation journal')
    if digest(json.loads((root/'initial-assessment.json').read_bytes()))!=prepared[0]['semantic']['initial_assessment_sha256']:
        raise EvidenceIntegrityError('Initial assessment differs from preparation journal')
    terminal=[e for e in events if e['semantic']['type'] in ('collection_recorded','collection_failed')]
    for event in terminal:
        body=event['semantic']
        if body['type']=='collection_recorded':
            for field,prefix,hash_field in (('account_raw_file','account-','account_raw_sha256'),
                                            ('packet_file','observation-','packet_sha256')):
                expected=prefix+digest(body['collection_id'])+'.json'
                file=root/expected
                if body[field]!=expected or file.is_symlink() or digest_bytes(file.read_bytes())!=body[hash_field]:
                    raise EvidenceIntegrityError('Forward collection proof changed')
    started={e['semantic']['collection_id'] for e in events if e['semantic']['type']=='collection_started'}
    ended={e['semantic']['collection_id'] for e in terminal}
    return dict(status='prepared_observe_only',pilot_id=pilot_id,registered_at=plan['registered_at'],
        directory=str(root.resolve()),frozen_plan_sha256=digest(plan),journal_events=len(events),
        completed_collections=sum(e['semantic']['type']=='collection_recorded' for e in terminal),
        failed_collections=sum(e['semantic']['type']=='collection_failed' for e in terminal),
        incomplete_collections=sorted(started-ended),
        latest_collection=terminal[-1]['semantic'] if terminal else None,
        costs_are_assumptions=True,dataset_admitted=False,strategy_execution_enabled=False,
        training_ready=False,live_trading=False,orders_sent=0,
        remaining=['source_rights_and_scoped_reviews','corporate_action_coverage',
            'admitted_forward_dataset','frozen_rule_engine_and_cash_cost_reconciliation'])


def collect(directory,*,database,pilot_id,collection_id,clock=None,readers=None):
    """One bounded GET capture attempt. Never retries an ambiguous attempt."""
    required(collection_id,'collection_id')
    root=Path(directory);now=clock or (lambda:datetime.now(timezone.utc))
    with ForwardStore(root/'protocol.sqlite3',clock=now) as protocol:
        plan=protocol.pilot(pilot_id);events=protocol.journal(pilot_id);settings=plan['semantic']
        status(root,pilot_id=pilot_id,clock=now)
        related=[e for e in events if e['semantic'].get('collection_id')==collection_id]
        if related:
            if related[-1]['semantic']['type'] in ('collection_recorded','collection_failed'):
                return related[-1]['semantic']
            raise ContractError('Prior collection outcome is incomplete; inspect status and use a new collection ID')
        if utc(now())>=settings['expires_at']:raise ContractError('Forward pilot expired; freeze a new protocol')
        # Verify local artifacts and current permissions before any network request.
        source=settings['seed_scope'];route=BrokerAccount(**settings['route'])
        with readonly_captures(database) as store:
            for source_id in (source['price_source_id'],source['calendar_source_id']):
                for use in (Use.STORAGE,Use.RESEARCH):store.require_use(source_id,use,as_of=now())
            listing=store.db.execute('SELECT * FROM listings WHERE listing_id=?',(source['listing_id'],)).fetchone()
            if listing is None or dict(listing)!=settings['listing']:
                raise ContractError('Forward listing identity changed')
            original=inspect_captures(store,price_source_id=source['price_source_id'],
                price_import_id=source['price_import_id'],calendar_source_id=source['calendar_source_id'],
                calendar_import_id=source['calendar_import_id'],listing_id=source['listing_id'],clock=now)
            if capture_scope(original)!=source:
                raise EvidenceIntegrityError('Evidence database differs from frozen seed scope')
        started=protocol.append(pilot_id,collection_id+':started',dict(type='collection_started',collection_id=collection_id),require_new=True)
        stage='reader_configuration'
        try:
            if readers is None:
                key=os.environ.get('ALPACA_PAPER_API_KEY','');secret=os.environ.get('ALPACA_PAPER_SECRET_KEY','')
                readers=(AlpacaReferenceReader(key,secret),AlpacaCalendarReader(route,key,secret),AlpacaPriceReader(route,key,secret))
            reference,calendar_reader,price_reader=readers
            stage='paper_account_match'
            account=reference.read('account')
            if (account.source_url!=PAPER_HOST+'/v2/account' or account.environment!=Environment.PAPER
                    or not timestamp(started['known_at'])<=account.received_at<=now()
                    or json.loads(account.payload).get('account_number')!=route.account_id):
                raise ContractError('Paper credential account does not match frozen route')
            stage='account_proof_archive'
            proof_name='account-'+digest(collection_id)+'.json'
            with open(root/proof_name,'xb',opener=lambda name,flags:os.open(name,flags,0o600)) as stream:
                stream.write(account.payload)
            local_today=now().astimezone(ZoneInfo('America/New_York')).date()
            end=(local_today+timedelta(days=14)).isoformat()
            cal_id=pilot_id+':'+collection_id+':calendar';price_id=pilot_id+':'+collection_id+':prices'
            # Existing database only; capture writes are an explicit part of collect.
            if not Path(database).is_file():raise ContractError('Existing evidence database required')
            with AlpacaCalendarStore(database) as store:
                stage='calendar_capture'
                calendar=sync_calendar(store,source_id=source['calendar_source_id'],import_id=cal_id,
                    route=route,start_date=settings['start_date'],end_date=end,venue=settings['calendar_venue'],
                    reader=calendar_reader,clock=now)
                if not timestamp(started['known_at'])<=timestamp(calendar['received_at'])<=now():
                    raise ContractError('Calendar receipt is outside collection attempt')
                closed=[r for r in calendar['candidates'] if r['date']<local_today.isoformat()
                        and timestamp(r['end'])<=now()]
                if calendar['quarantined'] or not closed:raise ContractError('No valid completed calendar day available')
                through=max(r['date'] for r in closed)
                stage='price_capture'
                prices=sync_prices(store,source_id=source['price_source_id'],import_id=price_id,route=route,
                    symbol_listings={settings['symbol']:source['listing_id']},start_date=settings['start_date'],
                    end_date=through,feed=source['feed'],reader=price_reader,clock=now)
                if prices['state']!='complete_pages':raise ContractError('Price capture did not complete')
            with readonly_captures(database) as store:
                stage='capture_assessment'
                review=DataAdmissionStore.__new__(DataAdmissionStore);review.db=store.db
                packet=assess_captured(review,intended_use='forward_observation',price_source_id=source['price_source_id'],
                    price_import_id=price_id,calendar_source_id=source['calendar_source_id'],calendar_import_id=cal_id,
                    listing_id=source['listing_id'],clock=now)
            file_name='observation-'+digest(collection_id)+'.json'
            stage='packet_archive'
            private_json(root/file_name,packet)
            post_registration=sum(timestamp(r['calendar_end'])>timestamp(plan['registered_at']) for r in packet['inspection']['observations'])
            semantic=dict(type='collection_recorded',collection_id=collection_id,price_import_id=price_id,
                calendar_import_id=cal_id,through_date=through,observation_count=len(packet['inspection']['observations']),
                post_registration_rows=post_registration,recorded_at=utc(now()),
                account_match_verified=True,account_raw_file=proof_name,account_raw_sha256=digest_bytes(account.payload),
                packet_file=file_name,packet_sha256=digest_bytes((root/file_name).read_bytes()),
                dataset_admitted=False,decision=dict(action='abstain',target_weight=None,
                    reason='real_dataset_admission_not_established'),admission_reasons=packet['assessment']['reasons'],
                orders_sent=0,live_trading=False)
            protocol.append(pilot_id,collection_id+':finished',semantic)
            return semantic
        except Exception as error:
            # Reader/JSON exceptions must never echo credential headers or raw account data.
            semantic=dict(type='collection_failed',collection_id=collection_id,error_type=type(error).__name__,
                stage=stage,reason='capture_failed_no_automatic_retry',orders_sent=0,live_trading=False)
            protocol.append(pilot_id,collection_id+':finished',semantic)
            return semantic


def digest_bytes(payload):
    import hashlib
    return hashlib.sha256(payload).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','collect','status'])
    parser.add_argument('--out',required=True);parser.add_argument('--pilot',required=True)
    parser.add_argument('--database')
    for name in ('price-source','price-import','calendar-source','calendar-import','listing','collection'):
        parser.add_argument('--'+name)
    parser.add_argument('--lookback',type=int,default=5)
    args=parser.parse_args()
    try:
        if args.action=='prepare':
            result=prepare(args.out,database=args.database,pilot_id=args.pilot,price_source_id=args.price_source,
                price_import_id=args.price_import,calendar_source_id=args.calendar_source,
                calendar_import_id=args.calendar_import,listing_id=args.listing,lookback=args.lookback)
        elif args.action=='collect':
            result=collect(args.out,database=args.database,pilot_id=args.pilot,collection_id=args.collection)
        else:result=status(args.out,pilot_id=args.pilot)
    except (ContractError,OSError,ValueError,TypeError,sqlite3.Error) as error:
        parser.exit(2,'Forward pilot rejected: '+str(error)+'\n')
    print(json.dumps(result,sort_keys=True,indent=2))
    if result.get('type')=='collection_failed':raise SystemExit(2)


if __name__=='__main__':main()
