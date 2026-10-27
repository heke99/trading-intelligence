"""Read-only two-source capture admission assessment; never admits a dataset."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from .alpaca_market import canonical
from .captured_observations import inspect_captures, verify_inspection
from .captured_smoke import readonly_captures
from .contracts import ContractError, DataOrigin, utc
from .data_admission import AXES, DataAdmissionStore, _scope
from .market_data import timestamp

PURPOSES = ('forward_observation', 'historical_replay')
BASES = dict(forward_observation='observed_receipt_and_processing',
             historical_replay='documented_publication_vintage')


def capture_scope(inspection):
    """Stable across assessment clocks, bound to every page/route/row/source."""
    verify_inspection(inspection)
    frozen={k:v for k,v in inspection.items() if k not in ('checked_at','inspection_sha256')}
    rows=inspection['observations']
    return dict(schema='captured-admission-scope-2',
                price_source_id=inspection['price_source_id'],price_import_id=inspection['price_import_id'],
                calendar_source_id=inspection['calendar_source_id'],calendar_import_id=inspection['calendar_import_id'],
                listing_id=inspection['listing']['listing_id'],start_date=rows[0]['economic_date'],
                end_date=rows[-1]['economic_date'],feed=inspection['query']['feed'],
                capture_snapshot_sha256=hashlib.sha256(canonical(frozen).encode()).hexdigest())


def assess_captured(store, *, intended_use, price_source_id, price_import_id,
                    calendar_source_id, calendar_import_id, listing_id, clock=None):
    """Current declared review gate, separate from historical trading readiness.

    Runs against an existing DataAdmissionStore interface, including a read-only
    connection without its optional reviews table. No constructors/migrations,
    declarations, approvals, market promotion or network calls occur here.
    """
    if intended_use not in PURPOSES:
        raise ContractError('Explicit supported capture admission purpose required')
    now=(clock or (lambda:datetime.now(timezone.utc)))()
    at=utc(now)
    store.db.execute('SAVEPOINT captured_admission_read')
    try:
        inspection=inspect_captures(store,price_source_id=price_source_id,price_import_id=price_import_id,
            calendar_source_id=calendar_source_id,calendar_import_id=calendar_import_id,
            listing_id=listing_id,clock=lambda:now)
        scope=capture_scope(inspection);scope_sha=_scope(scope)
        has_reviews=store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='data_admission_reviews'").fetchone() is not None
        reasons=[];reviews={};templates=[]
        for source in (price_source_id,calendar_source_id):
            if inspection['source_origins'][source]!=DataOrigin.PROVIDER.value:
                reasons.append(source+':provider_origin_required')
            reviews[source]={}
            for axis in AXES:
                review=store._review(source,axis,intended_use,scope_sha,at) if has_reviews else None
                allowed=review is not None and review['decision']=='allow' and review['expires_at']>at
                if allowed and axis=='rights':
                    allowed={'storage','research'}<=set(review['declared_rights'])
                if allowed and axis=='temporal':
                    allowed=review['temporal_basis']==BASES[intended_use]
                reviews[source][axis]=dict(declared_review_allows=allowed,
                    review_id=review['review_id'] if review else None,independently_verified=False)
                if not allowed:reasons.append(source+':'+axis+'_review_missing_denied_expired_or_inapplicable')
                templates.append(dict(review_id=None,source_id=source,axis=axis,purpose=intended_use,
                    scope=scope,expires_at=None,reviewer=None,evidence_refs=[],decision=None,
                    temporal_basis=BASES[intended_use] if axis=='temporal' else None,
                    declared_rights=[] if axis=='rights' else None))
        if not inspection['calendar_venue_matches_listing']:
            reasons.append('calendar_listing_venue_mismatch')
        if intended_use=='historical_replay':
            # Captured inspection deliberately preserves unknown publication.
            # No caller review can promote receipt into historical publication.
            reasons.append('historical_publication_or_vintage_unknown')
        rows=inspection['observations']
        latest=max(timestamp(row['available_at']) for row in rows)
        historical_ready=sum(timestamp(row['available_at'])<=timestamp(row['calendar_end']) for row in rows)
        # Existing inspected sessions can be in the past by the time of receipt.
        # Never silently roll a missed next-session baseline intention forward.
        future_sessions=sorted({(r['economic_date'],r['calendar_start']) for r in rows
                                if timestamp(r['calendar_start'])>latest})
        report=dict(schema='captured-admission-assessment-2',checked_at=at,intended_use=intended_use,
            scope=scope,scope_sha256=scope_sha,inspection_sha256=inspection['inspection_sha256'],
            source_reviews=reviews,reasons=sorted(set(reasons)),
            eligible_for_declared_purpose=not reasons,
            assertion_status='caller_declared_reviews_not_independent_certification',
            temporal_diagnostics=dict(observation_count=len(rows),
                earliest_available_at=min(r['available_at'] for r in rows),latest_available_at=utc(latest),
                rows_available_by_session_close=historical_ready,
                later_captured_sessions=future_sessions,
                next_session_calendar_verified=False),
            baseline_blockers=sorted(set(reasons+['real_dataset_admission_not_established',
                'corporate_action_coverage_unverified','executable_price_and_cost_model_unverified',
                'frozen_baseline_not_bound_to_admitted_slice'])),
            dataset_admitted=False,promotion_performed=False,publication_verified=False,
            training_ready=False,full_history_verified=False,live_trading=False,
            strategy_profitability_verified=False,network_requests=0)
        report['report_sha256']=hashlib.sha256(canonical(report).encode()).hexdigest()
        return dict(assessment=report,inspection=inspection,review_templates=templates)
    finally:
        store.db.execute('ROLLBACK TO captured_admission_read')
        store.db.execute('RELEASE captured_admission_read')


def prepare_assessment(directory, *, database, clock=None, **scope):
    """Create a fresh private packet, preserving all existing database bytes."""
    with readonly_captures(database) as captured:
        store=DataAdmissionStore.__new__(DataAdmissionStore)
        store.db=captured.db
        packet=assess_captured(store,clock=clock,**scope)
    root=Path(directory)
    root.mkdir(mode=0o700,parents=True,exist_ok=False)
    files={'inspection.json':packet['inspection'],'scope.json':packet['assessment']['scope'],
           'assessment.json':packet['assessment'],
           'review-template.json':dict(status='unreviewed_do_not_auto_approve',reviews=packet['review_templates'])}
    hashes={}
    for name,body in files.items():
        payload=(json.dumps(body,sort_keys=True,indent=2)+'\n').encode()
        path=root/name
        with path.open('xb') as stream:stream.write(payload)
        path.chmod(0o600)
        hashes[name]=hashlib.sha256(payload).hexdigest()
    report=packet['assessment']
    return dict(status='declared_review_eligible' if report['eligible_for_declared_purpose'] else 'blocked',
        directory=str(root.resolve()),intended_use=report['intended_use'],
        scope_sha256=report['scope_sha256'],observation_count=len(packet['inspection']['observations']),
        source_reviews=report['source_reviews'],reasons=report['reasons'],
        temporal_diagnostics=report['temporal_diagnostics'],baseline_blockers=report['baseline_blockers'],
        dataset_admitted=False,training_ready=False,live_trading=False,network_requests=0,evidence_files=hashes)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['assess'])
    for name in ('database','price-source','price-import','calendar-source','calendar-import','listing','out'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--purpose',choices=PURPOSES,required=True)
    args=parser.parse_args()
    try:
        result=prepare_assessment(args.out,database=args.database,intended_use=args.purpose,
            price_source_id=args.price_source,price_import_id=args.price_import,
            calendar_source_id=args.calendar_source,calendar_import_id=args.calendar_import,listing_id=args.listing)
    except (ContractError,OSError,ValueError,sqlite3.Error) as error:
        parser.exit(2,'Captured admission assessment rejected: '+str(error)+'\n')
    print(json.dumps(result,sort_keys=True,indent=2))


if __name__=='__main__':main()
