"""Account-matched corporate-action capture bound to an existing forward pilot."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3

from .alpaca_actions import CorporateActionStore, sync_actions, fingerprint
from .alpaca_actions_reader import AlpacaActionsReader
from .alpaca_reader import AlpacaReferenceReader
from .brokers import BrokerAccount
from .captured_admission import assess_captured
from .captured_smoke import readonly_captures
from .contracts import ContractError, DataOrigin, Use, utc
from .data_admission import DataAdmissionStore
from .forward_pilot import ForwardStore, status, private_json


def assess_binding(packet,actions):
    scope=packet['assessment']['scope'];request=actions['job']['request']
    if request['binding']!=scope or request['listing']!=packet['inspection']['listing']:
        raise ContractError('Corporate action job belongs to a different exact price/calendar scope')
    result=actions['result']
    reasons=list(packet['assessment']['baseline_blockers'])
    if result['state']!='complete_pages':reasons.append('corporate_action_capture_incomplete_failed_or_quarantined')
    reasons+=['corporate_action_effective_date_coverage_unverified','corporate_action_source_reviews_missing',
              'corporate_action_identity_and_accounting_policy_unverified']
    report=dict(schema='captured-actions-binding-1',price_calendar_scope=scope,
        price_calendar_scope_sha256=packet['assessment']['scope_sha256'],
        action_source_id=actions['job']['source_id'],action_import_id=actions['job']['import_id'],
        action_manifest_sha256=actions['manifest_sha256'],process_query=request['query'],
        process_pages_complete=result['process_pages_complete'],state=result['state'],
        account_match_verified=result['account_match_verified'],candidate_count=result['candidate_count'],
        quarantine_count=result['quarantine_count'],quarantine_reasons=result['quarantine_reasons'],
        effective_date_coverage_verified=False,publication_verified=False,dataset_admitted=False,
        accounting_ready=False,training_ready=False,live_trading=False,orders_sent=0,
        reasons=sorted(set(reasons)))
    report['binding_sha256']=fingerprint(report);return report


def sync_pilot(*,database,pilot_directory,pilot_id,source_id,import_id,directory,
               declare_storage_research=False,process_start=None,process_end=None,clock=None,readers=None):
    now=clock or (lambda:datetime.now(timezone.utc))
    current=status(pilot_directory,pilot_id=pilot_id,clock=now)
    latest=current['latest_collection']
    if latest is None or latest['type']!='collection_recorded':
        raise ContractError('A latest successful forward capture is required')
    with ForwardStore(Path(pilot_directory)/'protocol.sqlite3',clock=now) as protocol:
        plan=protocol.pilot(pilot_id)
    settings=plan['semantic'];seed=settings['seed_scope'];route=BrokerAccount(**settings['route'])
    with readonly_captures(database) as captured:
        review=DataAdmissionStore.__new__(DataAdmissionStore);review.db=captured.db
        packet=assess_captured(review,intended_use='forward_observation',price_source_id=seed['price_source_id'],
            price_import_id=latest['price_import_id'],calendar_source_id=seed['calendar_source_id'],
            calendar_import_id=latest['calendar_import_id'],listing_id=seed['listing_id'],clock=now)
    archived=json.loads((Path(pilot_directory)/latest['packet_file']).read_bytes())
    if packet['assessment']['scope']!=archived['assessment']['scope']:
        raise ContractError('Evidence database differs from the exact archived forward capture')
    if (packet['inspection']['listing']!=settings['listing']
            or packet['inspection']['calendar_lineage']['provenance']['route']!=settings['route']):
        raise ContractError('Current captures differ from frozen pilot identity/route')
    start=process_start or packet['assessment']['scope']['start_date']
    end=process_end or packet['assessment']['scope']['end_date']
    root=Path(directory);root.mkdir(mode=0o700,parents=True,exist_ok=False)
    with CorporateActionStore(database) as store:
        known=store.db.execute('SELECT origin FROM sources WHERE source_id=?',(source_id,)).fetchone()
        if known is None and declare_storage_research:
            store.register_source(source_id,DataOrigin.PROVIDER)
            store.set_permissions(source_id,known_at=now(),uses={Use.STORAGE,Use.RESEARCH})
        # Existing denials are never reset by the declaration flag.
        for use in (Use.STORAGE,Use.RESEARCH):store.require_use(source_id,use,as_of=now())
        if readers is None:
            key=os.environ.get('ALPACA_PAPER_API_KEY','');secret=os.environ.get('ALPACA_PAPER_SECRET_KEY','')
            readers=(AlpacaReferenceReader(key,secret),AlpacaActionsReader(route,key,secret))
        actions=sync_actions(store,source_id=source_id,import_id=import_id,route=route,
            binding=packet['assessment']['scope'],listing=settings['listing'],symbol=settings['symbol'],
            process_start=start,process_end=end,account_reader=readers[0],action_reader=readers[1],clock=now)
    bound=assess_binding(packet,actions)
    for name,body in {'price-calendar-inspection.json':packet['inspection'],
                      'corporate-actions.json':actions,'binding-report.json':bound}.items():
        private_json(root/name,body)
    result=actions['result']
    return dict(status=result['state'],source_id=source_id,import_id=import_id,directory=str(root.resolve()),
        account_match_verified=result['account_match_verified'],action_pages=result['page_count'],
        candidate_count=result['candidate_count'],quarantine_count=result['quarantine_count'],
        quarantine_reasons=result['quarantine_reasons'],process_pages_complete=result['process_pages_complete'],
        stage=result['stage'],error_code=result['error_code'],reason=result['reason'],
        binding_sha256=bound['binding_sha256'],action_manifest_sha256=actions['manifest_sha256'],
        effective_date_coverage_verified=False,dataset_admitted=False,accounting_ready=False,
        orders_sent=0,training_ready=False,live_trading=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['sync-pilot'])
    for name in ('database','pilot-dir','pilot','source','import-id','out'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--declare-storage-research',action='store_true')
    parser.add_argument('--process-start');parser.add_argument('--process-end')
    args=parser.parse_args()
    try:
        result=sync_pilot(database=args.database,pilot_directory=args.pilot_dir,pilot_id=args.pilot,
            source_id=args.source,import_id=args.import_id,directory=args.out,
            declare_storage_research=args.declare_storage_research,process_start=args.process_start,process_end=args.process_end)
    except (ContractError,OSError,ValueError,KeyError,TypeError,sqlite3.Error) as error:
        parser.exit(2,'Corporate action capture rejected: '+str(error)+'\n')
    print(json.dumps(result,sort_keys=True,indent=2))
    if result['status']!='complete_pages':raise SystemExit(2)


if __name__=='__main__':main()
