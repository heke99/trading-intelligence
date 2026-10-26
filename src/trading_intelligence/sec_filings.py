"""Bounded public SEC submissions reader and immutable supplied-response staging."""
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import hashlib
from http.client import HTTPException
import json
import re
import ssl
from threading import Lock
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPRedirectHandler, HTTPSHandler, build_opener

from .alpaca_market import canonical
from .alpaca_normalizer import decode, NormalizationError
from .contracts import ContractError, DataOrigin, EvidenceIntegrityError, RecordConflict, Use, required, utc
from .market_data import timestamp
from .store import EvidenceStore

MAX_BYTES = 10_000_000
VERSION = 'sec-submissions-recent-2'
SUPPORTED_VERSIONS = {'sec-submissions-recent-1', VERSION}
_LOCK = Lock()
_LAST = 0.0
SCHEMA = '''CREATE TABLE IF NOT EXISTS sec_submission_captures (
 source_id TEXT NOT NULL REFERENCES sources, import_id TEXT NOT NULL,
 input_json TEXT NOT NULL, raw_sha TEXT NOT NULL REFERENCES raw_objects,
 available_at TEXT NOT NULL, result_json TEXT NOT NULL, integrity_sha TEXT NOT NULL,
 PRIMARY KEY(source_id,import_id));'''


class SecReadError(ContractError):
    pass


def endpoint(cik):
    if not isinstance(cik, str) or not re.fullmatch(r'[0-9]{10}', cik) or int(cik) == 0:
        raise SecReadError('Explicit nonzero 10-digit CIK required')
    return f'https://data.sec.gov/submissions/CIK{cik}.json'


def _limit():
    # Process-wide ceiling of five request starts/second, below SEC's published
    # ten/second ceiling. Separate processes still need an external shared limit.
    global _LAST
    with _LOCK:
        delay = .2 - (time.monotonic() - _LAST)
        if delay > 0:
            time.sleep(delay)
        _LAST = time.monotonic()


@dataclass(frozen=True)
class SecRead:
    payload: bytes = field(repr=False)
    received_at: datetime
    source_url: str
    cik: str
    transport: str = 'supplied_bytes'

    def __post_init__(self):
        required(self.transport,'capture transport')
        if self.transport not in {'supplied_bytes','declared_http_get'}:
            raise SecReadError('Unsupported SEC capture provenance')
        if self.source_url != endpoint(self.cik):
            raise SecReadError('Unexpected SEC endpoint')
        if not isinstance(self.payload, bytes) or not 0 < len(self.payload) <= MAX_BYTES:
            raise SecReadError('Nonempty bounded original SEC response required')
        utc(self.received_at)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


class SecSubmissionsReader:
    def __init__(self, user_agent, *, timeout=10, clock=None, opener=None, limiter=None):
        required(user_agent, 'identified SEC user agent')
        if (not re.search(r'[^\s@]+@[^\s@]+\.[^\s@]+', user_agent)
                or any(not 32 <= ord(c) <= 126 for c in user_agent) or len(user_agent) > 256):
            raise SecReadError('SEC user agent must identify the requester with a contact email')
        if type(timeout) not in (int, float) or not 0 < timeout <= 30:
            raise SecReadError('Bounded positive timeout required')
        self._agent, self._timeout = user_agent, timeout
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._opener = opener or build_opener(_NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))
        self._limiter = limiter or _limit

    def __repr__(self):
        return '<SecSubmissionsReader public GET submissions>'

    def read(self, cik):
        url = endpoint(cik)
        self._limiter()
        request = Request(url, method='GET', headers={'User-Agent':self._agent,
                          'Accept':'application/json', 'Accept-Encoding':'identity'})
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                if response.status != 200 or response.geturl() != url:
                    raise SecReadError('Unexpected SEC response status or endpoint')
                media = response.headers.get('Content-Type','').split(';',1)[0].strip().lower()
                encoding = response.headers.get('Content-Encoding','identity').strip().lower()
                if media != 'application/json' or encoding not in ('','identity'):
                    raise SecReadError('Expected uncompressed JSON SEC response')
                payload = response.read(MAX_BYTES+1)
        except SecReadError:
            raise
        except HTTPError as exc:
            status = str(exc.code) if type(exc.code) is int and 100 <= exc.code <= 599 else 'unknown'
            exc.close()
            raise SecReadError(f'SEC HTTP failure ({status}); details omitted; no retry') from None
        except (URLError, OSError, HTTPException, UnicodeError, ValueError):
            raise SecReadError('SEC connection failed; no retry or fallback') from None
        return SecRead(payload, self._clock(), url, cik, transport='declared_http_get')


def _day(value, *, optional=False):
    if optional and value == '':
        return None
    if not isinstance(value,str):
        raise ContractError('Invalid filing date')
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ContractError('Invalid filing date') from exc
    if parsed.isoformat() != value:
        raise ContractError('Canonical filing date required')
    return value



def valid_primary_document(value):
    """Bounded relative ASCII path, preserved verbatim; never a URL or fetch."""
    if not isinstance(value, str) or not 1 <= len(value) <= 1024:
        return False
    segments = value.split('/')
    return len(segments) <= 16 and all(
        segment not in {'', '.', '..'} and len(segment) <= 255
        and re.fullmatch(r'[A-Za-z0-9_.-]+', segment) is not None
        for segment in segments)


def _normalize_recent_row(row, received, index):
    issues = []
    def issue(field, reason):
        issues.append(dict(field=field, reason=reason))
    accession = row['accessionNumber']
    if not isinstance(accession, str) or not re.fullmatch(r'[0-9]{10}-[0-9]{2}-[0-9]{6}', accession):
        issue('accessionNumber', 'invalid_accession')
    try:
        required(row['form'], 'form')
    except ContractError:
        issue('form', 'invalid_form')
    if not valid_primary_document(row['primaryDocument']):
        issue('primaryDocument', 'invalid_primary_document_path')
    accepted = None
    try:
        accepted = utc(timestamp(row['acceptanceDateTime']))
        if accepted > received:
            issue('acceptanceDateTime', 'acceptance_after_receipt')
    except (ContractError, TypeError, ValueError):
        issue('acceptanceDateTime', 'invalid_acceptance_datetime')
    dates = {}
    for field, optional in [('filingDate', False), ('reportDate', True)]:
        try:
            dates[field] = _day(row[field], optional=optional)
        except (ContractError, TypeError, ValueError):
            issue(field, 'invalid_filing_date' if field == 'filingDate' else 'invalid_report_date')
    if issues:
        return None, dict(row_index=index, reason=issues[0]['reason'],
                          field=issues[0]['field'], issues=issues)
    return dict(accession_number=accession, form=row['form'],
                filing_date=dates['filingDate'], report_date=dates['reportDate'],
                acceptance_datetime_raw=row['acceptanceDateTime'], accepted_at=accepted,
                published_at=None, primary_document=row['primaryDocument'],
                state='staged_unknown_dissemination', row_index=index), None


def normalize_submissions(payload, cik, received_at):
    rows, quarantine, files = [], [], []
    received = utc(received_at)
    try:
        body = decode(payload)
        if not isinstance(body,dict):
            raise ContractError('submissions_object_required')
        declared = body.get('cik')
        if isinstance(declared,bool) or not isinstance(declared,(str,int)) or not re.fullmatch(r'[0-9]{1,10}',str(declared)) or str(declared).zfill(10) != cik:
            raise ContractError('response_cik_mismatch')
        filings = body.get('filings')
        if not isinstance(filings,dict) or not isinstance(filings.get('recent'),dict):
            raise ContractError('recent_column_arrays_required')
        recent = filings['recent']
        names = ('accessionNumber','filingDate','reportDate','acceptanceDateTime','form','primaryDocument')
        if not set(names) <= recent.keys() or any(not isinstance(v,list) for v in recent.values()):
            raise ContractError('recent_column_arrays_required')
        length = len(recent['accessionNumber'])
        if any(len(v) != length for v in recent.values()):
            raise ContractError('unaligned_recent_columns')
        archives = filings.get('files')
        if not isinstance(archives,list):
            raise ContractError('archive_inventory_required')
        # Inventory only. Never follow provider-selected links or claim history complete.
        for item in archives:
            if not isinstance(item,dict) or not isinstance(item.get('name'),str) or not re.fullmatch(r'CIK[0-9]{10}-submissions-[0-9]+\.json',item['name']):
                raise ContractError('invalid_archive_inventory')
            if not item['name'].startswith('CIK'+cik+'-submissions-'):
                raise ContractError('archive_cik_mismatch')
            start, end = _day(item.get('filingFrom')), _day(item.get('filingTo'))
            if start > end:
                raise ContractError('reversed_archive_range')
            files.append(dict(name=item['name'],filingFrom=start,filingTo=end))
        for index in range(length):
            row = {key:recent[key][index] for key in names}
            normalized, rejected = _normalize_recent_row(row, received, index)
            if rejected:
                quarantine.append(rejected)
            else:
                rows.append(normalized)
    except (ContractError,NormalizationError):
        return dict(cik=cik,filings=[],quarantined=[dict(row_index=None,reason='invalid_submissions_envelope')],
                    archive_files=[],recent_rows_valid=False,publication_verified=False,full_history_verified=False,
                    training_ready=False,live_trading=False)
    counts = Counter(x['accession_number'] for x in rows)
    accepted = []
    for row in rows:
        if counts[row['accession_number']] > 1:
            quarantine.append(dict(row_index=row['row_index'], reason='duplicate_accession',
                                   field='accessionNumber', issues=[dict(field='accessionNumber', reason='duplicate_accession')]))
        else:
            accepted.append(row)
    return dict(cik=cik,filings=accepted,quarantined=quarantine,archive_files=files,
                recent_rows_valid=not quarantine,publication_verified=False,full_history_verified=False,
                training_ready=False,live_trading=False)


class SecFilingsStore(EvidenceStore):
    def __init__(self,database):
        super().__init__(database)
        self.db.executescript(SCHEMA)

    def import_submissions(self, *, source_id, import_id, captured, processed_at):
        if self.db.in_transaction:
            raise ContractError('SEC import requires an idle connection')
        required(source_id,'source_id');required(import_id,'import_id')
        if not isinstance(captured,SecRead):
            raise ContractError('Explicit SEC response required')
        known = utc(processed_at)
        received = utc(captured.received_at)
        if known < received:
            raise ContractError('Processing precedes SEC receipt')
        for at in (received,known):
            self._require_use(source_id,Use.STORAGE,at)
        self._require_use(source_id,Use.RESEARCH,known)
        raw_sha = hashlib.sha256(captured.payload).hexdigest()
        inputs = canonical(dict(version=VERSION,cik=captured.cik,endpoint=captured.source_url,
                                received_at=received,processed_at=known,raw_sha=raw_sha,transport=captured.transport))
        old = self.db.execute('SELECT input_json FROM sec_submission_captures WHERE source_id=? AND import_id=?',(source_id,import_id)).fetchone()
        if old:
            # Retry the archived normalizer version; never silently reprocess it.
            original = self.submissions_as_of(source_id,import_id,as_of=processed_at)
            if original is None or original['version'] not in SUPPORTED_VERSIONS:
                raise EvidenceIntegrityError('Unsupported archived SEC normalizer version')
            expected = json.loads(inputs)
            expected['version'] = original['version']
            if old[0] != canonical(expected):
                raise RecordConflict('SEC import ID belongs to changed input')
            return original
        report = normalize_submissions(captured.payload,captured.cik,captured.received_at)
        result = dict(version=VERSION,source_id=source_id,import_id=import_id,cik=captured.cik,
                      source_url=captured.source_url,raw_sha=raw_sha,received_at=received,available_at=known,
                      capture_origin=captured.transport,report=report)
        encoded = canonical(result)
        fields = dict(source_id=source_id,import_id=import_id,input_json=inputs,raw_sha=raw_sha,
                      available_at=known,result_json=encoded)
        digest = hashlib.sha256(canonical(fields).encode()).hexdigest()
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO raw_objects VALUES (?,?)',(raw_sha,captured.payload))
            raw = self.db.execute('SELECT payload FROM raw_objects WHERE sha256=?',(raw_sha,)).fetchone()
            if raw is None or raw[0] != captured.payload:
                raise EvidenceIntegrityError('SEC raw archive hash mismatch')
            self._immutable('sec_submission_captures',{'source_id':source_id,'import_id':import_id},dict(**fields,integrity_sha=digest))
        return result

    def submissions_as_of(self,source_id,import_id,*,as_of):
        required(source_id,'source_id');required(import_id,'import_id')
        at = utc(as_of)
        self.db.execute('SAVEPOINT sec_submissions_read')
        try:
            self._require_use(source_id,Use.RESEARCH,at)
            row = self.db.execute('SELECT * FROM sec_submission_captures WHERE source_id=? AND import_id=? AND available_at<=?',(source_id,import_id,at)).fetchone()
            result = None
            if row:
                fields = {key:row[key] for key in ('source_id','import_id','input_json','raw_sha','available_at','result_json')}
                if hashlib.sha256(canonical(fields).encode()).hexdigest() != row['integrity_sha']:
                    raise EvidenceIntegrityError('SEC capture integrity mismatch')
                raw = self.db.execute('SELECT payload FROM raw_objects WHERE sha256=?',(row['raw_sha'],)).fetchone()
                if raw is None or hashlib.sha256(raw[0]).hexdigest() != row['raw_sha']:
                    raise EvidenceIntegrityError('SEC raw integrity mismatch')
                result = json.loads(row['result_json'])
        except BaseException:
            self.db.execute('ROLLBACK TO sec_submissions_read');self.db.execute('RELEASE sec_submissions_read');raise
        else:
            self.db.execute('RELEASE sec_submissions_read');return result


def sync_sec(store, *, source_id, import_id, cik, reader, clock=None):
    if store.db.in_transaction:
        raise ContractError('SEC sync requires an idle connection')
    required(source_id,'source_id');required(import_id,'import_id');endpoint(cik)
    now = clock or (lambda: datetime.now(timezone.utc))
    checked = now()
    for use in (Use.STORAGE,Use.RESEARCH):
        store.require_use(source_id,use,as_of=checked)
    origin = store.db.execute('SELECT origin FROM sources WHERE source_id=?',(source_id,)).fetchone()
    if origin is None or origin[0] != DataOrigin.PROVIDER.value:
        raise ContractError('SEC network sync needs an explicitly declared provider source')
    old = store.db.execute('SELECT 1 FROM sec_submission_captures WHERE source_id=? AND import_id=?',(source_id,import_id)).fetchone()
    if old:
        result = store.submissions_as_of(source_id,import_id,as_of=checked)
        if result is None or result['cik'] != cik or result['capture_origin'] != 'declared_http_get':
            raise RecordConflict('SEC import ID belongs to another CIK or unavailable capture')
        return result
    captured = reader.read(cik)
    if not isinstance(captured,SecRead) or captured.cik != cik or captured.transport != 'declared_http_get':
        raise ContractError('SEC response CIK does not match request')
    return store.import_submissions(source_id=source_id,import_id=import_id,captured=captured,processed_at=now())


def sec_demo(directory):
    """Repeatable synthetic SEC capture; never issues a network request."""
    from pathlib import Path
    from datetime import timedelta
    directory = Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    received = datetime(2026,1,10,22,tzinfo=timezone.utc)
    processed = received+timedelta(seconds=1)
    cik = '0000000001'
    payload = canonical({'cik':1,'filings':{'recent':{
        'accessionNumber':['0000000001-26-000001'],'filingDate':['2026-01-05'],
        'reportDate':['2025-12-31'],'acceptanceDateTime':['2026-01-05T21:00:00Z'],
        'form':['10-K'],'primaryDocument':['invented.htm']},'files':[]}}).encode()
    with SecFilingsStore(directory/'sec.sqlite3') as store:
        store.register_source('synthetic-sec',DataOrigin.SYNTHETIC)
        store.set_permissions('synthetic-sec',known_at=received-timedelta(days=30),uses={Use.STORAGE,Use.RESEARCH})
        capture = store.import_submissions(source_id='synthetic-sec',import_id='invented-submissions',
            captured=SecRead(payload,received,endpoint(cik),cik),processed_at=processed)
        result = dict(origin=DataOrigin.SYNTHETIC.value,capture=capture,
                      evidence_publications_created=store.counts()['evidence_versions'],
                      network_requests=0,training_ready=False,live_trading=False)
    (directory/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result
