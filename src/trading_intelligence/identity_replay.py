"""Exact temporal identifier replay with auditable lineage, never broker routing."""
from datetime import date, datetime
import hashlib
import json

from .contracts import ContractError, EvidenceIntegrityError, Use, required, utc

VERSION = 'identity-replay-1'


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def resolve_schedule(store, requests, *, provider, as_of):
    """Resolve one explicit identifier per declared day in a consistent read.

    Each request has date, identifier and aware datetime effective_at, plus an
    optional aware decision_at <= as_of. Without decision_at the fixed as_of is
    an explicit knowledge snapshot, not proof of what a past live decision knew.
    The date must match effective_at in its supplied timezone; no calendar or
    timezone is inferred. This verifies raw hashes and temporal metadata, not
    historical access, source correctness or a tamper-proof identifier registry.
    """
    required(provider, 'provider')
    cutoff = utc(as_of)
    if not isinstance(requests, (list, tuple)) or not requests:
        raise ContractError('Explicit nonempty request list/tuple required')
    normalized = []
    for request in requests:
        if not isinstance(request, dict) or not {'date','identifier','effective_at'} <= request.keys() or request.keys() - {'date','identifier','effective_at','decision_at'}:
            raise ContractError('Unexpected schedule request fields')
        day = request['date']
        if not isinstance(day, str):
            raise ContractError('Canonical ISO date required')
        try:
            if date.fromisoformat(day).isoformat() != day:
                raise ValueError('Noncanonical date')
        except ValueError as exc:
            raise ContractError('Canonical ISO date required') from exc
        identifier = required(request['identifier'], 'identifier')
        effective = utc(request['effective_at'])
        if request['effective_at'].date().isoformat() != day:
            raise ContractError('Date must match effective_at in its supplied timezone')
        decision_at = request.get('decision_at', as_of)
        decision = utc(decision_at)
        if decision > cutoff or effective > decision:
            raise ContractError('Require effective_at <= decision_at <= as_of')
        normalized.append(dict(date=day, identifier=identifier, effective_at=effective,
                               decision_at=decision, knowledge_mode='per_decision' if 'decision_at' in request else 'fixed_snapshot'))
    days = [r['date'] for r in normalized]
    if days != sorted(set(days)):
        raise ContractError('Schedule dates must be unique and increasing')

    store.db.execute('SAVEPOINT identity_replay_read')
    try:
        records = []
        for request in normalized:
            # Existing resolver remains authority for exact matching and ambiguity.
            effective_at = datetime.fromisoformat(request['effective_at'].replace('Z','+00:00'))
            decision_at = datetime.fromisoformat(request['decision_at'].replace('Z','+00:00'))
            listing_id = store.resolve_identifier(provider, request['identifier'], effective_at=effective_at, as_of=decision_at)
            rows = store.db.execute(
                'SELECT v.*,e.source_id,e.sha256,e.received_at,e.published_at,r.payload '
                'FROM identifier_versions v JOIN evidence_versions e USING(evidence_id) '
                'JOIN raw_objects r USING(sha256) '
                'WHERE v.provider=? AND v.value=? AND v.known_at<=? '
                'AND v.known_at=(SELECT MAX(x.known_at) FROM identifier_versions x '
                'WHERE x.mapping_id=v.mapping_id AND x.known_at<=?) '
                'AND v.valid_from<=? AND (v.valid_to IS NULL OR v.valid_to>?) '
                'ORDER BY v.mapping_id,v.known_at',
                (provider,request['identifier'],request['decision_at'],request['decision_at'],request['effective_at'],request['effective_at'])).fetchall()
            if not rows or any(r['listing_id'] != listing_id for r in rows):
                raise EvidenceIntegrityError('Resolved identifier and lineage disagree')
            lineage=[]
            for row in rows:
                store.require_use(row['source_id'], Use.RESEARCH, as_of=decision_at)
                if row['received_at'] > row['known_at'] or row['published_at'] > row['received_at']:
                    raise EvidenceIntegrityError('Identifier evidence temporal metadata is inconsistent')
                if hashlib.sha256(row['payload']).hexdigest() != row['sha256']:
                    raise EvidenceIntegrityError('Identifier evidence hash verification failed')
                fields = {key:row[key] for key in ('mapping_id','provider','value','listing_id','valid_from','valid_to','known_at','evidence_id')}
                lineage.append(dict(**fields, source_id=row['source_id'], raw_sha256=row['sha256'],
                                    received_at=row['received_at'], published_at=row['published_at'],
                                    mapping_sha256=hashlib.sha256(_canonical(fields).encode()).hexdigest()))
            listing = store.db.execute(
                'SELECT l.*,i.entity_id,i.kind,i.share_class,i.base_currency FROM listings l '
                'JOIN instruments i USING(instrument_id) WHERE l.listing_id=?', (listing_id,)).fetchone()
            if listing is None or listing['kind'] not in {'equity','etf'}:
                raise EvidenceIntegrityError('Resolved listing has no supported instrument identity')
            records.append(dict(**request, identity=dict(listing), lineage=lineage))
        manifest=dict(version=VERSION,provider=provider,as_of=cutoff,requests=normalized,records=records)
        result=dict(manifest=manifest,manifest_sha256=hashlib.sha256(_canonical(manifest).encode()).hexdigest(),
                    records=records,training_ready=False,full_history_verified=False,live_trading=False,
                    broker_routing_authorized=False)
    except BaseException:
        store.db.execute('ROLLBACK TO identity_replay_read')
        store.db.execute('RELEASE identity_replay_read')
        raise
    else:
        store.db.execute('RELEASE identity_replay_read')
        return result
