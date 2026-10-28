"""Supplied facility assertions and geographic investigation context.

Proximity identifies a question to investigate, not damage, economic exposure,
return direction or permission to trade. This module does not submit orders.
"""

from datetime import datetime
import hashlib
import json
import math

from .contracts import ContractError, EvidenceIntegrityError, RecordConflict, Use, required, utc
from .event_store import EventStore


CONTEXT_VERSION = 'facility-context-1'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS event_facility_assertions (
 assertion_id TEXT PRIMARY KEY, facility_id TEXT NOT NULL,
 entity_id TEXT NOT NULL REFERENCES entities, relationship TEXT NOT NULL,
 available_at TEXT NOT NULL, body_json TEXT NOT NULL, sha256 TEXT NOT NULL,
 UNIQUE(facility_id,entity_id,relationship,available_at));
CREATE INDEX IF NOT EXISTS event_facility_series
 ON event_facility_assertions(facility_id,entity_id,relationship,available_at);
'''


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _number(value, name, low=None, high=None):
    if type(value) not in (int, float):
        raise ContractError(f'{name} must be a finite number')
    try:
        number = float(value)
    except OverflowError as exc:
        raise ContractError(f'{name} must be a finite number') from exc
    if not math.isfinite(number):
        raise ContractError(f'{name} must be a finite number')
    if (low is not None and value < low) or (high is not None and value > high):
        raise ContractError(f'{name} is outside its valid range')
    return number


def haversine_km(latitude_a, longitude_a, latitude_b, longitude_b):
    """Great-circle distance on a sphere, not a hazard propagation model."""
    a = math.radians(_number(latitude_a, 'latitude', -90, 90))
    b = math.radians(_number(latitude_b, 'latitude', -90, 90))
    delta_latitude = b - a
    delta_longitude = math.radians(
        _number(longitude_b, 'longitude', -180, 180)
        - _number(longitude_a, 'longitude', -180, 180))
    term = math.sin(delta_latitude / 2) ** 2 + math.cos(a) * math.cos(b) * math.sin(delta_longitude / 2) ** 2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, term))))


class EventContextStore(EventStore):
    def __init__(self, database, *, clock=None):
        super().__init__(database, clock=clock)
        self.db.executescript(SCHEMA)

    def _facility_evidence(self, evidence_id, at, current):
        row = self.db.execute(
            'SELECT e.*,r.payload,s.origin FROM evidence_versions e '
            'JOIN raw_objects r USING(sha256) JOIN sources s USING(source_id) '
            'WHERE evidence_id=?', (evidence_id,)).fetchone()
        if row is None or row['received_at'] > at:
            raise ContractError('Facility evidence is missing or not yet available')
        if row['published_at'] > row['received_at']:
            raise EvidenceIntegrityError('Facility evidence has inconsistent timestamps')
        for cutoff in (at, current):
            self._require_use(row['source_id'], Use.RESEARCH, cutoff)
        if hashlib.sha256(row['payload']).hexdigest() != row['sha256']:
            raise EvidenceIntegrityError('Facility backing evidence failed integrity verification')
        return {key: row[key] for key in (
            'evidence_id', 'source_id', 'record_id', 'revision_id', 'sha256',
            'published_at', 'received_at', 'origin')}

    def _facility(self, row, current):
        try:
            body = json.loads(row['body_json'])
            if (_digest(body) != row['sha256']
                    or any(body[key] != row[key] for key in (
                        'assertion_id', 'facility_id', 'entity_id', 'relationship', 'available_at'))
                    or body['known_at'] > body['available_at']):
                raise EvidenceIntegrityError('Facility assertion manifest failed integrity verification')
            evidence = self._facility_evidence(body['evidence_id'], body['known_at'], current)
            if body['evidence'] != evidence:
                raise EvidenceIntegrityError('Facility assertion evidence binding changed')
            self._identity(body['entity_id'], body['listing_id'])
            return body
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ContractError):
                raise
            raise EvidenceIntegrityError('Facility assertion manifest is invalid') from exc

    def _identity(self, entity_id, listing_id):
        if self.db.execute('SELECT 1 FROM entities WHERE entity_id=?', (entity_id,)).fetchone() is None:
            raise ContractError('A registered canonical entity is required')
        if listing_id is not None:
            row = self.db.execute(
                'SELECT i.entity_id FROM listings l JOIN instruments i USING(instrument_id) '
                'WHERE l.listing_id=?', (listing_id,)).fetchone()
            if row is None or row['entity_id'] != entity_id:
                raise ContractError('Explicit listing must belong to the facility entity')

    def put_facility(self, *, assertion_id, facility_id, entity_id, latitude, longitude,
                     evidence_id, valid_from, known_at, relationship, valid_to=None,
                     listing_id=None, supersedes=None):
        """Register one supplied relation version; replacements supersede a whole assertion.

        The declared knowledge time cannot backdate operational availability. A new
        version replaces the previous assertion's complete validity interval; it is
        not an inferred schedule of future ownership or operation.
        """
        if self.db.in_transaction:
            raise ContractError('Facility writes require an idle connection')
        for name, value in (('assertion_id', assertion_id), ('facility_id', facility_id),
                            ('entity_id', entity_id), ('evidence_id', evidence_id)):
            required(value, name)
        if not isinstance(relationship, str) or relationship not in {'operator', 'owner'}:
            raise ContractError('Explicit operator or owner relationship required')
        if listing_id is not None:
            required(listing_id, 'listing_id')
        if supersedes is not None:
            required(supersedes, 'supersedes')
        lat = _number(latitude, 'latitude', -90, 90)
        lon = _number(longitude, 'longitude', -180, 180)
        now = utc(self._event_clock())
        known, start = utc(known_at), utc(valid_from)
        end = utc(valid_to) if valid_to is not None else None
        if known > now or (end is not None and end <= start):
            raise ContractError('Valid facility knowledge and a nonempty validity interval required')
        self._identity(entity_id, listing_id)
        evidence = self._facility_evidence(evidence_id, known, now)
        self._require_use(evidence['source_id'], Use.STORAGE, now)
        semantic = dict(assertion_id=assertion_id, facility_id=facility_id, entity_id=entity_id,
                        relationship=relationship, latitude=lat, longitude=lon,
                        evidence_id=evidence_id, evidence=evidence, valid_from=start,
                        valid_to=end, known_at=known, listing_id=listing_id, supersedes=supersedes)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            return self._save_facility(semantic, now)

    def _save_facility(self, semantic, now):
        assertion_id = semantic['assertion_id']
        facility_id, entity_id = semantic['facility_id'], semantic['entity_id']
        relationship, supersedes = semantic['relationship'], semantic['supersedes']
        known = semantic['known_at']
        self._identity(entity_id, semantic['listing_id'])
        evidence = self._facility_evidence(semantic['evidence_id'], known, now)
        if evidence != semantic['evidence']:
            raise EvidenceIntegrityError('Facility evidence changed before registration')
        self._require_use(evidence['source_id'], Use.STORAGE, now)
        old = self.db.execute('SELECT * FROM event_facility_assertions WHERE assertion_id=?',
                              (assertion_id,)).fetchone()
        if old is not None:
            body = self._facility(old, now)
            if any(body.get(key) != value for key, value in semantic.items()):
                raise RecordConflict('Facility assertion ID already identifies another version')
            if body['available_at'] > now:
                raise ContractError('Facility assertion is unavailable at the operational clock')
            return body
        previous = self.db.execute(
            'SELECT * FROM event_facility_assertions WHERE facility_id=? AND entity_id=? '
            'AND relationship=? ORDER BY available_at DESC LIMIT 1',
            (facility_id, entity_id, relationship)).fetchone()
        if previous is None:
            if supersedes is not None:
                raise ContractError('Initial facility assertion cannot supersede a missing version')
        else:
            prior = self._facility(previous, now)
            if (supersedes != prior['assertion_id'] or now <= prior['available_at']
                    or known < prior['known_at']):
                raise ContractError('Replacement must supersede the latest version at a later availability')
        body = {**semantic, 'available_at': now}
        self.db.execute('INSERT INTO event_facility_assertions VALUES (?,?,?,?,?,?,?)',
                        (assertion_id, facility_id, entity_id, relationship, now,
                         _canonical(body), _digest(body)))
        return body

    def context(self, source_id, event_id, *, as_of, radius_km, current_at=None):
        """Find supplied facility relations in a caller-declared investigation area."""
        radius = _number(radius_km, 'investigation radius')
        if radius <= 0:
            raise ContractError('A positive investigation radius is required')
        at, current = self._times(as_of, current_at)
        self.db.execute('SAVEPOINT event_context_read')
        try:
            result = self._context(source_id, event_id, as_of, at, current, current_at, radius)
        except BaseException:
            self.db.execute('ROLLBACK TO event_context_read')
            self.db.execute('RELEASE event_context_read')
            raise
        else:
            self.db.execute('RELEASE event_context_read')
            return result

    def _context(self, source_id, event_id, as_of, at, current, current_at, radius):
        event = self.event_as_of(source_id, event_id, as_of=as_of, current_at=current_at)
        result = dict(version=CONTEXT_VERSION, source_id=source_id, event_id=event_id, as_of=at, current_at=current,
                      investigation_radius_km=radius, radius_is_damage_estimate=False,
                      event=event, candidates=[], action='unavailable' if event is None else 'observe',
                      uncertainties=['Geographic proximity does not establish damage or economic exposure.',
                                     'Current operating status, production share and market impact are unknown.'],
                      market_impact_assessed=False, model_implemented=False,
                      orders_sent=0, training_ready=False, live_trading=False)
        result['event_ambiguity'] = bool(event and event.get('unresolved_revision_conflict') is True)
        result['critical_uncertainties'] = []
        if result['event_ambiguity']:
            message = ('Conflicting source content for the selected native event revision is unresolved; '
                       'the archived observation does not establish a single trusted event state.')
            result['critical_uncertainties'].append(message)
            result['uncertainties'].append(message)
            result['action'] = 'investigate'
        if event is None:
            result['context_sha256'] = _digest(result)
            return result
        occurred = event['occurred_at']
        if occurred is None:
            result['uncertainties'].append('Unknown event occurrence time prevents facility validity matching.')
            result['context_sha256'] = _digest(result)
            return result
        rows = self.db.execute(
            'SELECT f.* FROM event_facility_assertions f WHERE f.available_at<=? '
            'AND f.available_at=(SELECT MAX(v.available_at) FROM event_facility_assertions v '
            'WHERE v.facility_id=f.facility_id AND v.entity_id=f.entity_id '
            'AND v.relationship=f.relationship AND v.available_at<=?) '
            'ORDER BY f.facility_id,f.entity_id,f.relationship', (at, at)).fetchall()
        for row in rows:
            body = self._facility(row, current)
            self._require_use(body['evidence']['source_id'], Use.RESEARCH, at)
            if body['known_at'] > at or body['valid_from'] > occurred:
                continue
            if body['valid_to'] is not None and body['valid_to'] <= occurred:
                continue
            distance = haversine_km(event['latitude'], event['longitude'],
                                    body['latitude'], body['longitude'])
            if distance <= radius:
                evidence_received = datetime.fromisoformat(body['evidence']['received_at'].replace('Z', '+00:00'))
                decision_time = datetime.fromisoformat(at.replace('Z', '+00:00'))
                result['candidates'].append(dict(
                    **body, distance_km=round(distance, 6), relationship_is_supplied=True,
                    evidence_age_seconds=(decision_time - evidence_received).total_seconds(),
                    freshness_assessed=False, current_operating_status='unknown',
                    economic_exposure_share=None, damage_confirmed=False))
        if result['candidates']:
            result['action'] = 'investigate'
        result['context_sha256'] = _digest(result)
        return result
