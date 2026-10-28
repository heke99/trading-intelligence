"""Immutable event capture and point-in-time observations; never order authority.

Publication may be unknown. New observations become usable only at operational
registration; an old provider timestamp never backdates their availability.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math

from .contracts import ContractError, EvidenceIntegrityError, RecordConflict, Use, required, utc
from .market_data import timestamp
from .store import EvidenceStore


VERSION = 'event-capture-1'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS event_captures (
 source_id TEXT NOT NULL REFERENCES sources, import_id TEXT NOT NULL,
 input_json TEXT NOT NULL, raw_sha TEXT NOT NULL REFERENCES raw_objects,
 available_at TEXT NOT NULL, result_json TEXT NOT NULL, integrity_sha TEXT NOT NULL,
 PRIMARY KEY(source_id,import_id));
CREATE TABLE IF NOT EXISTS event_versions (
 event_version_id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources,
 event_id TEXT NOT NULL, revision_id TEXT NOT NULL, provider_updated_at TEXT NOT NULL,
 normalized_json TEXT NOT NULL, first_import_id TEXT NOT NULL,
 available_at TEXT NOT NULL, integrity_sha TEXT NOT NULL,
 UNIQUE(source_id,event_id,revision_id),
 FOREIGN KEY(source_id,first_import_id) REFERENCES event_captures(source_id,import_id));
CREATE TABLE IF NOT EXISTS event_capture_quarantine (
 source_id TEXT NOT NULL, import_id TEXT NOT NULL, row_path TEXT NOT NULL,
 reason TEXT NOT NULL, PRIMARY KEY(source_id,import_id,row_path,reason),
 FOREIGN KEY(source_id,import_id) REFERENCES event_captures(source_id,import_id));
CREATE TABLE IF NOT EXISTS event_revision_conflicts (
 conflict_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, event_id TEXT NOT NULL,
 revision_id TEXT, import_id TEXT NOT NULL, available_at TEXT NOT NULL,
 body_json TEXT NOT NULL, integrity_sha TEXT NOT NULL,
 FOREIGN KEY(source_id,import_id) REFERENCES event_captures(source_id,import_id));
CREATE INDEX IF NOT EXISTS event_versions_as_of
 ON event_versions(source_id,event_id,available_at,provider_updated_at);
CREATE INDEX IF NOT EXISTS event_conflicts_as_of
 ON event_revision_conflicts(source_id,event_id,available_at,import_id);
'''


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class EventStore(EvidenceStore):
    def __init__(self, database, *, clock=None):
        super().__init__(database)
        self.db.executescript(SCHEMA)
        self._event_clock = clock or (lambda: datetime.now(timezone.utc))

    def _times(self, as_of, current_at=None):
        at, current = utc(as_of), utc(self._event_clock())
        if current_at is not None and utc(current_at) != current:
            raise ContractError('Explicit current cutoff must match operational clock')
        if at > current:
            raise ContractError('As-of cutoff cannot exceed operational clock')
        return at, current

    def _idle(self):
        if self.db.in_transaction:
            raise ContractError('Event writes require an idle connection')

    def _source_origin(self, source_id):
        row = self.db.execute('SELECT origin FROM sources WHERE source_id=?', (source_id,)).fetchone()
        if row is None:
            raise ContractError('Explicit registered event source required')
        return row['origin']

    def _research(self, source_id, at, current):
        for cutoff in (at, current):
            self._require_use(source_id, Use.RESEARCH, cutoff)

    def stage(self, *, source_id, import_id, capture, processed_at=None):
        """Archive a capture and stage normalized observations, including quarantine.

        Same import ID with identical source bytes/receipt/provenance is a retry.
        Provider revisions are scoped by source and never replaced in place.
        """
        self._idle()
        # Serialize the import identity and provider-version checks across
        # connections before either can observe an uncommitted reservation.
        self.db.execute('BEGIN IMMEDIATE')
        try:
            result = self._stage(source_id=source_id, import_id=import_id,
                                 capture=capture, processed_at=processed_at)
            self.db.commit()
            return result
        except BaseException:
            self.db.rollback()
            raise

    def _stage(self, *, source_id, import_id, capture, processed_at):
        from .event_sources import EventCapture, normalize_capture

        required(source_id, 'source_id'); required(import_id, 'import_id')
        if not isinstance(capture, EventCapture):
            raise ContractError('Explicit EventCapture required')
        now = utc(self._event_clock())
        received = utc(capture.received_at)
        processed = utc(processed_at) if processed_at is not None else now
        if not received <= processed <= now:
            raise ContractError('Receipt and processing must precede operational registration')
        origin = self._source_origin(source_id)
        for cutoff in (received, processed, now):
            self._require_use(source_id, Use.STORAGE, cutoff)
        self._research(source_id, processed, now)
        raw_sha = hashlib.sha256(capture.payload).hexdigest()
        capture_id = digest(dict(source_id=source_id, import_id=import_id))
        inputs = canonical(dict(version=VERSION, raw_sha=raw_sha, source_url=capture.source_url,
                                transport=capture.transport, format=capture.format,
                                received_at=received, origin=origin))
        old = self.db.execute('SELECT * FROM event_captures WHERE source_id=? AND import_id=?',
                              (source_id, import_id)).fetchone()
        if old:
            if old['input_json'] != inputs:
                raise RecordConflict('Event import ID already identifies different input')
            return self.capture_as_of(source_id, import_id, as_of=self._event_clock())

        normalized = normalize_capture(capture)
        row_prefix = 'features' if capture.format == 'usgs_geojson_v1' else 'items'
        conflicts = {}

        def conflict(event_id, revision_id, path, reason, **details):
            # A malformed row can identify the event without establishing a
            # usable revision. Such ambiguity is scoped to the event until a
            # later valid version becomes available.
            if not isinstance(event_id, str) or not event_id.strip() or event_id != event_id.strip():
                return
            identity = dict(source_id=source_id, import_id=import_id, event_id=event_id,
                            revision_id=revision_id, row_path=path, reason=reason)
            body = dict(**identity, conflict_id=digest(identity), capture_id=capture_id,
                        available_at=now, raw_sha=raw_sha, **details)
            conflicts[body['conflict_id']] = body

        metadata = normalized['metadata']
        quarantined = [dict(row_path=(f"{row_prefix}/{q['row_index']}" if q.get('row_index') is not None else '$'),
                            reason=q['reason']) for q in normalized['quarantined']]
        for native_quarantine, quarantine in zip(normalized['quarantined'], quarantined):
            if native_quarantine.get('event_id') is not None:
                conflict(native_quarantine['event_id'], None, quarantine['row_path'], quarantine['reason'])
        candidates = normalized['observations']
        generated = metadata.get('generated_at')
        if generated is not None and utc(timestamp(generated)) > received:
            for candidate in candidates:
                conflict(candidate.get('event_id'), None, 'metadata/generated', 'feed_generated_after_receipt')
            candidates = []
            quarantined.append(dict(row_path='metadata/generated', reason='feed_generated_after_receipt'))
        accepted, pending = [], []
        capture_cache = {}
        for candidate in candidates:
            path = f"{row_prefix}/{candidate['row_index']}"
            try:
                event = self._validate_observation(candidate, received)
            except ContractError as exc:
                quarantined.append(dict(row_path=path, reason=str(exc)))
                conflict(candidate.get('event_id'), None, path, str(exc))
                continue
            event_version_id = digest(dict(source_id=source_id, event_id=event['event_id'],
                                           revision_id=event['revision_id']))
            body = canonical(event)
            previous = self.db.execute('SELECT * FROM event_versions WHERE event_version_id=?',
                                       (event_version_id,)).fetchone()
            if previous:
                self._verify_version(previous, capture_cache)
                if previous['normalized_json'] != body:
                    quarantined.append(dict(row_path=path, reason='revision_content_conflict'))
                    conflict(event['event_id'], event['revision_id'], path, 'revision_content_conflict',
                             event_version_id=event_version_id,
                             recorded_content_sha256=hashlib.sha256(previous['normalized_json'].encode()).hexdigest(),
                             observed_content_sha256=hashlib.sha256(body.encode()).hexdigest())
                    continue
                first_available = previous['available_at']
            else:
                indistinguishable = self.db.execute(
                    'SELECT * FROM event_versions WHERE source_id=? AND event_id=? '
                    'AND provider_updated_at=? AND revision_id<>? LIMIT 1',
                    (source_id, event['event_id'], event['provider_updated_at'], event['revision_id'])).fetchone()
                if indistinguishable is not None:
                    self._verify_version(indistinguishable, capture_cache)
                    quarantined.append(dict(row_path=path, reason='revision_order_ambiguous'))
                    conflict(event['event_id'], None, path, 'revision_order_ambiguous',
                             provider_updated_at=event['provider_updated_at'],
                             recorded_revision_id=indistinguishable['revision_id'],
                             observed_revision_id=event['revision_id'])
                    continue
                first_available = now
                fields = dict(event_version_id=event_version_id, source_id=source_id,
                              event_id=event['event_id'], revision_id=event['revision_id'],
                              provider_updated_at=event['provider_updated_at'], normalized_json=body,
                              first_import_id=import_id, available_at=now)
                pending.append({**fields, 'integrity_sha': digest(fields)})
            accepted.append({**event, 'row_index': candidate['row_index'],
                             'event_version_id': event_version_id,
                             'first_available_at': first_available})
        quarantined = sorted({(q['row_path'], q['reason']) for q in quarantined})
        quarantine = [dict(row_path=path, reason=reason) for path, reason in quarantined]
        # Availability belongs to completion of normalization/validation, not
        # the time at which the operation started. Keep caller timing separate.
        completed = utc(self._event_clock())
        if completed < now:
            raise ContractError('Operational clock moved backwards during event processing')
        for use in (Use.STORAGE, Use.RESEARCH):
            self._require_use(source_id, use, completed)
        pending_ids = {row['event_version_id'] for row in pending}
        for row in pending:
            row['available_at'] = completed
            row['integrity_sha'] = digest({key: value for key, value in row.items() if key != 'integrity_sha'})
        for row in accepted:
            if row['event_version_id'] in pending_ids:
                row['first_available_at'] = completed
        for row in conflicts.values():
            row['available_at'] = completed
        now = completed
        conflict_list = [conflicts[key] for key in sorted(conflicts)]
        result = dict(version=VERSION, source_id=source_id, import_id=import_id,
                      capture_id=capture_id,
                      source_url=capture.source_url, transport=capture.transport,
                      capture_origin=capture.transport, format=capture.format,
                      normalizer_version=normalized['normalizer_version'], origin=origin,
                      raw_sha=raw_sha, received_at=received, processed_at=completed,
                      declared_processed_at=processed,
                      recorded_at=now, available_at=now, observations=accepted,
                      metadata=metadata, quarantined=quarantine, revision_conflicts=conflict_list,
                      state='staged' if not quarantine else ('partial' if accepted else 'quarantined'),
                      source_complete=False, full_history_verified=False,
                      training_ready=False, live_trading=False, orders_sent=0)
        fields = dict(source_id=source_id, import_id=import_id, input_json=inputs,
                      raw_sha=raw_sha, available_at=now, result_json=canonical(result))
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO raw_objects VALUES (?,?)', (raw_sha, capture.payload))
            raw = self.db.execute('SELECT payload FROM raw_objects WHERE sha256=?', (raw_sha,)).fetchone()
            if raw is None or raw['payload'] != capture.payload:
                raise EvidenceIntegrityError('Event raw capture integrity failed')
            self.db.execute('INSERT INTO event_captures VALUES (?,?,?,?,?,?,?)',
                            (*fields.values(), digest(fields)))
            for row in pending:
                self.db.execute('INSERT INTO event_versions VALUES (?,?,?,?,?,?,?,?,?)', tuple(row.values()))
            self.db.executemany('INSERT INTO event_capture_quarantine VALUES (?,?,?,?)',
                               [(source_id, import_id, q['row_path'], q['reason']) for q in quarantine])
            for body in conflict_list:
                self.db.execute('INSERT INTO event_revision_conflicts VALUES (?,?,?,?,?,?,?,?)',
                                (body['conflict_id'], source_id, body['event_id'], body['revision_id'],
                                 import_id, now, canonical(body), digest(body)))
        return result

    def _validate_observation(self, candidate, received):
        event = {k: v for k, v in candidate.items() if k != 'row_index'}
        for key in ('event_id', 'revision_id', 'event_type'):
            required(event.get(key), key)
        for key in ('occurred_at', 'provider_updated_at'):
            event[key] = utc(timestamp(event[key]))
            if event[key] > received:
                raise ContractError(key + '_after_receipt')
        if event['provider_updated_at'] < event['occurred_at']:
            raise ContractError('provider_update_before_occurrence')
        if event.get('published_at') is not None:
            event['published_at'] = utc(timestamp(event['published_at']))
            if event['published_at'] > received:
                raise ContractError('publication_after_receipt')
        for key, low, high in (('longitude', -180, 180), ('latitude', -90, 90)):
            value = event.get(key)
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ContractError('invalid_' + key)
        canonical(event)
        return event

    def _verify_capture(self, row, cache=None):
        cache_key = (row['source_id'], row['import_id'], row['integrity_sha'])
        if cache is not None and cache_key in cache:
            return cache[cache_key]
        fields = {k: row[k] for k in ('source_id', 'import_id', 'input_json', 'raw_sha',
                                     'available_at', 'result_json')}
        if digest(fields) != row['integrity_sha']:
            raise EvidenceIntegrityError('Event capture manifest integrity failed')
        raw = self.db.execute('SELECT payload FROM raw_objects WHERE sha256=?', (row['raw_sha'],)).fetchone()
        if raw is None or hashlib.sha256(raw['payload']).hexdigest() != row['raw_sha']:
            raise EvidenceIntegrityError('Event raw capture integrity failed')
        result = json.loads(row['result_json'])
        if result['origin'] != self._source_origin(row['source_id']):
            raise EvidenceIntegrityError('Event source origin changed')
        quarantine = [dict(row_path=q['row_path'], reason=q['reason']) for q in self.db.execute(
            'SELECT row_path,reason FROM event_capture_quarantine WHERE source_id=? AND import_id=? '
            'ORDER BY row_path,reason', (row['source_id'], row['import_id']))]
        if result['quarantined'] != quarantine:
            raise EvidenceIntegrityError('Event quarantine journal integrity failed')
        conflict_rows = self.db.execute('SELECT * FROM event_revision_conflicts WHERE source_id=? '
                                       'AND import_id=? ORDER BY conflict_id',
                                       (row['source_id'], row['import_id'])).fetchall()
        conflicts = [self._conflict_body(conflict_row) for conflict_row in conflict_rows]
        if conflicts != result.get('revision_conflicts', []):
            raise EvidenceIntegrityError('Event conflict journal integrity failed')
        if cache is not None:
            cache[cache_key] = result
        return result

    @contextmanager
    def _event_snapshot(self):
        self.db.execute('SAVEPOINT event_store_read')
        try:
            yield
        except BaseException:
            self.db.execute('ROLLBACK TO event_store_read')
            self.db.execute('RELEASE event_store_read')
            raise
        else:
            self.db.execute('RELEASE event_store_read')

    def _conflict_reports(self, source_id, at, cache, event_id=None):
        # Canonical report JSON always contains the empty array marker when
        # there are no conflicts. Filtering in SQLite avoids decoding/hashing
        # every full feed for each event, while the capture-side manifest still
        # exposes a deleted conflict index row.
        query = ('SELECT * FROM event_captures WHERE source_id=? AND available_at<=? '
                 'AND instr(result_json,?)=0')
        values = [source_id, at, '"revision_conflicts":[]']
        if event_id is not None:
            query += (' AND (instr(result_json,?)>0 OR EXISTS '
                      '(SELECT 1 FROM event_revision_conflicts conflict '
                      'WHERE conflict.source_id=event_captures.source_id '
                      'AND conflict.import_id=event_captures.import_id AND conflict.event_id=?))')
            values.extend(['"event_id":' + canonical(event_id), event_id])
        query += ' ORDER BY import_id'
        return [self._verify_capture(row, cache) for row in self.db.execute(query, values).fetchall()]

    def _conflict_body(self, row):
        body = json.loads(row['body_json'])
        if digest(body) != row['integrity_sha'] or any(body.get(key) != row[key] for key in
                ('conflict_id', 'source_id', 'event_id', 'revision_id', 'import_id', 'available_at')):
            raise EvidenceIntegrityError('Event revision conflict integrity failed')
        return body

    def _revision_conflicts(self, event, at, reports):
        conflicts = []
        for report in reports:
            for body in report.get('revision_conflicts', []):
                if body['event_id'] != event['event_id']:
                    continue
                if not (body['revision_id'] == event['revision_id'] or
                        (body['revision_id'] is None and body['available_at'] >= event['available_at'])):
                    continue
                if (body['raw_sha'] != report['raw_sha'] or body['source_id'] != event['source_id']
                        or body['capture_id'] != report['capture_id'] or body['available_at'] != report['available_at']):
                    raise EvidenceIntegrityError('Revision conflict capture binding changed')
                conflicts.append(body)
        return sorted(conflicts, key=lambda value: value['conflict_id'])

    def capture_as_of(self, source_id, import_id, *, as_of, current_at=None):
        at, current = self._times(as_of, current_at)
        with self._event_snapshot():
            self._research(source_id, at, current)
            row = self.db.execute('SELECT * FROM event_captures WHERE source_id=? AND import_id=? '
                                  'AND available_at<=?', (source_id, import_id, at)).fetchone()
            return None if row is None else self._verify_capture(row)

    def _verify_version(self, row, cache=None):
        fields = {k: row[k] for k in row.keys() if k != 'integrity_sha'}
        if digest(fields) != row['integrity_sha']:
            raise EvidenceIntegrityError('Event version integrity failed')
        capture = self.db.execute('SELECT * FROM event_captures WHERE source_id=? AND import_id=?',
                                  (row['source_id'], row['first_import_id'])).fetchone()
        if capture is None:
            raise EvidenceIntegrityError('Event backing capture is missing')
        report = self._verify_capture(capture, cache)
        event = json.loads(row['normalized_json'])
        bindings = [x for x in report['observations'] if x['event_version_id'] == row['event_version_id']]
        if len(bindings) != 1:
            raise EvidenceIntegrityError('Event version lacks unique capture binding')
        bound = {k: v for k, v in bindings[0].items()
                 if k not in {'row_index', 'event_version_id', 'first_available_at'}}
        if bound != event or bindings[0]['first_available_at'] != row['available_at']:
            raise EvidenceIntegrityError('Event capture binding changed')
        if report['available_at'] != row['available_at']:
            raise EvidenceIntegrityError('Event version was backdated relative to its capture')
        return {**event, 'source_id': row['source_id'], 'event_version_id': row['event_version_id'],
                'capture_id': report['capture_id'], 'import_id': row['first_import_id'],
                'raw_sha': report['raw_sha'], 'available_at': row['available_at'],
                'received_at': report['received_at'], 'source_url': report['source_url'],
                'origin': report['origin'], 'normalizer_version': report['normalizer_version']}

    def events_as_of(self, source_id, *, as_of, current_at=None):
        at, current = self._times(as_of, current_at)
        with self._event_snapshot():
            self._research(source_id, at, current)
            cache = {}
            reports = self._conflict_reports(source_id, at, cache)
            # Sort by provider update, not arrival: delayed old revisions cannot
            # regress the currently known state. Skip older versions before
            # verification; the selected version retains its exact backing.
            rows = self.db.execute('SELECT * FROM event_versions WHERE source_id=? AND available_at<=? '
                                   'ORDER BY event_id,provider_updated_at DESC,revision_id DESC',
                                   (source_id, at)).fetchall()
            selected = {}
            for row in rows:
                if row['event_id'] not in selected:
                    selected[row['event_id']] = self._verify_version(row, cache)
            for event in selected.values():
                self._bind_conflicts(event, at, reports)
            return [selected[key] for key in sorted(selected)]

    def _bind_conflicts(self, event, at, reports):
        conflicts = self._revision_conflicts(event, at, reports)
        event.update(unresolved_revision_conflict=bool(conflicts), revision_conflicts=conflicts,
                     conflict_capture_ids=sorted({conflict['capture_id'] for conflict in conflicts}))
        return event

    def event_as_of(self, source_id, event_id, *, as_of, current_at=None):
        required(event_id, 'event_id')
        at, current = self._times(as_of, current_at)
        with self._event_snapshot():
            self._research(source_id, at, current)
            row = self.db.execute('SELECT * FROM event_versions WHERE source_id=? AND event_id=? '
                                   'AND available_at<=? ORDER BY provider_updated_at DESC,revision_id DESC LIMIT 1',
                                   (source_id, event_id, at)).fetchone()
            if row is None:
                return None
            cache = {}
            event = self._verify_version(row, cache)
            reports = self._conflict_reports(source_id, at, cache, event_id)
            return self._bind_conflicts(event, at, reports)
