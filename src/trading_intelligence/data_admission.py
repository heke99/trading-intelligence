"""Audited, caller-declared capture review gate. Never promotes market records.

Review identities and conclusions remain assertions requiring independent human
verification/access control in production, not automatic legal certification.
"""
from datetime import date, datetime, timezone
import hashlib
import json

from .alpaca_calendar import AlpacaCalendarStore
from .alpaca_market import canonical
from .contracts import ContractError, DataOrigin, EvidenceIntegrityError, Use, required, utc

AXES = ('rights', 'provenance', 'temporal', 'coverage')
PURPOSES = {'synthetic_validation', 'forward_observation', 'historical_replay'}
SCOPE_KEYS = {'bar_import_id', 'calendar_import_id', 'bar_raw_sha', 'calendar_raw_sha',
              'listing_id', 'venue', 'start_date', 'end_date', 'feed'}
CAPTURED_SCOPE_KEYS = {'schema', 'price_source_id', 'price_import_id', 'calendar_source_id',
                       'calendar_import_id', 'listing_id', 'start_date', 'end_date', 'feed',
                       'capture_snapshot_sha256'}
SCHEMA = '''CREATE TABLE IF NOT EXISTS data_admission_reviews (
 review_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources,
 axis TEXT NOT NULL, purpose TEXT NOT NULL, scope_sha TEXT NOT NULL,
 known_at TEXT NOT NULL, expires_at TEXT NOT NULL,
 review_json TEXT NOT NULL, raw_sha TEXT NOT NULL REFERENCES raw_objects,
 UNIQUE(source_id,axis,purpose,scope_sha,known_at));'''


def _scope(scope):
    if not isinstance(scope, dict) or set(scope) not in (SCOPE_KEYS, CAPTURED_SCOPE_KEYS):
        raise ContractError('Exact capture/identity/date/feed review scope required')
    captured = set(scope) == CAPTURED_SCOPE_KEYS
    for key, value in scope.items():
        required(value, key)
    if captured and (scope['schema'] != 'captured-admission-scope-2'
                     or scope['price_source_id'] == scope['calendar_source_id']):
        raise ContractError('Distinct explicit sources and captured scope schema required')
    for key in ('start_date', 'end_date'):
        try:
            if date.fromisoformat(scope[key]).isoformat() != scope[key]:
                raise ValueError()
        except ValueError as exc:
            raise ContractError('Canonical scope dates required') from exc
    if scope['start_date'] > scope['end_date'] or scope['feed'] not in {'iex', 'sip'}:
        raise ContractError('Invalid scope interval/feed')
    for key in (('capture_snapshot_sha256',) if captured else ('bar_raw_sha', 'calendar_raw_sha')):
        if len(scope[key]) != 64 or any(c not in '0123456789abcdef' for c in scope[key]):
            raise ContractError('Exact SHA256 capture hashes required')
    return hashlib.sha256(canonical(scope).encode()).hexdigest()


class DataAdmissionStore(AlpacaCalendarStore):
    def __init__(self, database, *, clock=None):
        super().__init__(database)
        self.db.executescript(SCHEMA)
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _evidence(self, source_id, refs, at):
        if (not isinstance(refs, list) or not refs or not all(isinstance(x, str) for x in refs)
                or len(set(refs)) != len(refs)):
            raise ContractError('Unique nonempty evidence ID list required')
        for reference in refs:
            required(reference, 'evidence reference')
            row = self.db.execute('SELECT e.source_id,e.received_at,e.sha256,r.payload '
                                  'FROM evidence_versions e JOIN raw_objects r USING(sha256) '
                                  'WHERE evidence_id=?', (reference,)).fetchone()
            if row is None or row['source_id'] != source_id or row['received_at'] > at:
                raise ContractError('Review evidence must already exist for this source')
            if hashlib.sha256(row['payload']).hexdigest() != row['sha256']:
                raise EvidenceIntegrityError('Review evidence failed hash verification')

    def record_review(self, *, review_id, source_id, axis, purpose, scope, known_at=None,
                      expires_at, reviewer, evidence_refs, decision, temporal_basis=None, declared_rights=None):
        """Append immutable scoped assertions; amend with a new ID and later time."""
        if self.db.in_transaction:
            raise ContractError('Review write requires an idle connection')
        for name, value in [('review_id',review_id),('source_id',source_id),('reviewer',reviewer)]:
            required(value, name)
        for name,value in [('axis',axis),('purpose',purpose),('decision',decision)]:
            required(value,name)
        if axis not in AXES or purpose not in PURPOSES or decision not in {'allow','deny'}:
            raise ContractError('Unknown review axis/purpose/decision')
        if axis == 'rights':
            if (not isinstance(declared_rights,list) or not all(isinstance(x,str) for x in declared_rights)
                    or len(set(declared_rights)) != len(declared_rights)
                    or set(declared_rights)-{x.value for x in Use}):
                raise ContractError('Explicit declared rights list required')
        elif declared_rights is not None:
            raise ContractError('Declared rights belong only to rights review')
        scope_sha = _scope(scope)
        if set(scope) == CAPTURED_SCOPE_KEYS and source_id not in (scope['price_source_id'], scope['calendar_source_id']):
            raise ContractError('Review source must belong to captured scope')
        recorded = utc(self._clock())
        known = recorded if known_at is None else utc(known_at)
        if known != recorded:
            raise ContractError('Review availability must equal operational recording time')
        expiry = utc(expires_at)
        if known >= expiry:
            raise ContractError('Review expiry must follow availability')
        if axis == 'temporal':
            if temporal_basis not in {'synthetic_fixture_only','observed_receipt_and_processing','documented_publication_vintage'}:
                raise ContractError('Explicit supported temporal basis required')
        elif temporal_basis is not None:
            raise ContractError('Temporal basis belongs only to temporal review')
        self._require_use(source_id, Use.STORAGE, known)
        self._require_use(source_id, Use.RESEARCH, known)
        self._evidence(source_id, evidence_refs, known)
        payload = canonical(dict(review_id=review_id, source_id=source_id, axis=axis, purpose=purpose,
                                 scope=scope, scope_sha=scope_sha, known_at=known, expires_at=expiry,
                                 reviewer=reviewer, evidence_refs=sorted(evidence_refs), decision=decision,
                                 temporal_basis=temporal_basis, declared_rights=sorted(declared_rights) if declared_rights is not None else None))
        digest = hashlib.sha256(payload.encode()).hexdigest()
        fields = dict(review_id=review_id, source_id=source_id, axis=axis, purpose=purpose,
                      scope_sha=scope_sha, known_at=known, expires_at=expiry, review_json=payload, raw_sha=digest)
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO raw_objects VALUES (?,?)', (digest,payload.encode()))
            raw = self.db.execute('SELECT payload FROM raw_objects WHERE sha256=?',(digest,)).fetchone()[0]
            if raw != payload.encode():
                raise EvidenceIntegrityError('Review raw assertion archive failed integrity')
            self._immutable('data_admission_reviews', {'review_id':review_id}, fields)
        return digest

    def _review(self, source_id, axis, purpose, scope_sha, at):
        row = self.db.execute('SELECT * FROM data_admission_reviews WHERE source_id=? '
                              'AND axis=? AND purpose=? AND scope_sha=? AND known_at<=? '
                              'ORDER BY known_at DESC LIMIT 1',(source_id,axis,purpose,scope_sha,at)).fetchone()
        if row is None:
            return None
        raw = self.db.execute('SELECT payload FROM raw_objects WHERE sha256=?',(row['raw_sha'],)).fetchone()
        encoded = row['review_json'].encode()
        if raw is None or raw['payload'] != encoded or hashlib.sha256(encoded).hexdigest() != row['raw_sha']:
            raise EvidenceIntegrityError('Review assertion failed integrity')
        body = json.loads(row['review_json'])
        for key in ('review_id','source_id','axis','purpose','scope_sha','known_at','expires_at'):
            if body[key] != row[key]:
                raise EvidenceIntegrityError('Review index does not match archived assertion')
        if _scope(body['scope']) != scope_sha:
            raise EvidenceIntegrityError('Review scope hash mismatch')
        self._evidence(source_id, body['evidence_refs'], at)
        return body

    def assess(self, *, source_id, scope, intended_use, as_of):
        """Eligibility report only. Current rights cannot be bypassed by old as_of."""
        if isinstance(scope,dict) and set(scope)==CAPTURED_SCOPE_KEYS:
            raise ContractError('Use captured_admission.assess_captured for a two-source job scope')
        required(intended_use, 'intended_use')
        if intended_use not in PURPOSES:
            raise ContractError('Unsupported intended use')
        scope_sha = _scope(scope)
        at, now = utc(as_of), utc(self._clock())
        if now < at:
            raise ContractError('Current cutoff cannot precede historical cutoff')
        self.db.execute('SAVEPOINT admission_read')
        try:
            # Both historical and current declarations are necessary, even if
            # callers query an old snapshot before a later revocation.
            for cutoff in (at,now):
                self._require_use(source_id, Use.STORAGE, cutoff)
                self._require_use(source_id, Use.RESEARCH, cutoff)
            origin_row = self.db.execute('SELECT origin FROM sources WHERE source_id=?',(source_id,)).fetchone()
            origin = origin_row['origin'] if origin_row else None
            reasons, axes = [], {}
            for axis in AXES:
                past = self._review(source_id,axis,intended_use,scope_sha,at)
                current = self._review(source_id,axis,intended_use,scope_sha,now)
                allowed = all(x is not None and x['decision']=='allow' and x['expires_at']>cutoff
                              for x,cutoff in ((past,at),(current,now)))
                if axis == 'rights' and allowed:
                    allowed = all({'storage','research'} <= set(x['declared_rights']) for x in (past,current))
                axes[axis] = {'declared_review_allows':allowed,
                              'historical_review_id':past['review_id'] if past else None,
                              'current_review_id':current['review_id'] if current else None,
                              'independently_verified':False}
                if not allowed:
                    reasons.append(axis+'_review_missing_denied_or_expired')
            bars = self.capture_as_of(source_id,scope['bar_import_id'],as_of=as_of)
            calendar = self.calendar_as_of(source_id,scope['calendar_import_id'],as_of=as_of)
            if bars is None or calendar is None:
                reasons.append('capture_unavailable_at_cutoff')
            else:
                if bars['raw_sha'] != scope['bar_raw_sha'] or calendar['raw_sha'] != scope['calendar_raw_sha']:
                    reasons.append('capture_hash_mismatch')
                if bars['quarantined'] or calendar['quarantined']:
                    reasons.append('quarantined_capture_rows')
                if not bars['page_complete'] or bars['pagination_state'] != 'terminal_page':
                    reasons.append('unresolved_price_pages')
                inputs_row = self.db.execute('SELECT input_json FROM alpaca_market_captures '
                                             'WHERE source_id=? AND import_id=?',(source_id,scope['bar_import_id'])).fetchone()
                inputs = json.loads(inputs_row['input_json'])
                listing = self.db.execute('SELECT mic FROM listings WHERE listing_id=?',(scope['listing_id'],)).fetchone()
                if (listing is None or listing['mic'] != scope['venue'] or inputs['feed'] != scope['feed']
                        or inputs['adjustment'] != 'raw' or inputs['timeframe'] != '1Day'):
                    reasons.append('identity_or_feed_scope_mismatch')
                if (calendar['calendar_kind'] != 'TRADING' or calendar['venue'] != scope['venue']
                        or calendar['start_date'] != scope['start_date'] or calendar['end_date'] != scope['end_date']
                        or calendar['market_timezone'] != inputs['market_timezone']):
                    reasons.append('calendar_request_scope_mismatch')
                sessions = {x['date'] for x in calendar['candidates']}
                session_ends = {x['date']: x['end'] for x in calendar['candidates']}
                selected = [x for x in bars['candidates'] if x['listing_id']==scope['listing_id']]
                days = [x['date'] for x in selected]
                if (not sessions or set(days)!=sessions or len(days)!=len(set(days))
                        or any(not scope['start_date']<=d<=scope['end_date'] for d in sessions)):
                    reasons.append('price_calendar_date_coverage_mismatch')
                if any(x['date'] in session_ends and bars['received_at'] < session_ends[x['date']]
                       for x in selected):
                    reasons.append('daily_bar_not_complete_at_observation')
                if any(x['published_at'] is None for x in selected+calendar['candidates']):
                    if intended_use == 'historical_replay':
                        reasons.append('historical_publication_or_vintage_unknown')
                expected_basis = {'synthetic_validation':'synthetic_fixture_only',
                                  'forward_observation':'observed_receipt_and_processing',
                                  'historical_replay':'documented_publication_vintage'}[intended_use]
                temporal = self._review(source_id,'temporal',intended_use,scope_sha,at)
                current_temporal = self._review(source_id,'temporal',intended_use,scope_sha,now)
                if any(x is None or x['temporal_basis']!=expected_basis for x in (temporal,current_temporal)):
                    reasons.append('temporal_review_basis_mismatch')
            if intended_use != 'synthetic_validation' and origin != DataOrigin.PROVIDER.value:
                reasons.append('provider_origin_required_for_real_use')
            if intended_use == 'synthetic_validation' and origin != DataOrigin.SYNTHETIC.value:
                reasons.append('synthetic_origin_required_for_fixture_validation')
            report = dict(version=1, source_id=source_id, scope=scope, scope_sha=scope_sha,
                          intended_use=intended_use, as_of=at, current_at=now, axes=axes,
                          eligible_for_declared_purpose=not reasons, reasons=sorted(set(reasons)),
                          assertion_status='caller_declared_reviews_not_independent_certification',
                          promotion_performed=False, training_ready=False, live_trading=False,
                          full_history_verified=False)
            report['report_sha256'] = hashlib.sha256(canonical(report).encode()).hexdigest()
        except BaseException:
            self.db.execute('ROLLBACK TO admission_read'); self.db.execute('RELEASE admission_read')
            raise
        else:
            self.db.execute('RELEASE admission_read')
            return report
