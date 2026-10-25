"""Supplied legacy Alpaca /v2/calendar captures; no authenticated calendar claim."""
from collections import Counter
from datetime import date, datetime, time, timezone
import hashlib
import json
import re
from zoneinfo import ZoneInfo

from .alpaca_market import AlpacaMarketStore, canonical
from .alpaca_normalizer import decode, NormalizationError
from .brokers import BrokerAccount, Environment
from .contracts import ContractError, EvidenceIntegrityError, RecordConflict, Use, required, utc

FORMAT = 'alpaca-trading-v2-calendar-local-hhmm-1'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS alpaca_calendar_captures (
 source_id TEXT NOT NULL REFERENCES sources, import_id TEXT NOT NULL,
 input_json TEXT NOT NULL, raw_sha TEXT NOT NULL REFERENCES raw_objects,
 available_at TEXT NOT NULL, result_json TEXT NOT NULL, integrity_sha TEXT NOT NULL,
 PRIMARY KEY(source_id,import_id));
CREATE TABLE IF NOT EXISTS alpaca_calendar_quarantine (
 source_id TEXT NOT NULL, import_id TEXT NOT NULL, row_path TEXT NOT NULL,
 reason TEXT NOT NULL, PRIMARY KEY(source_id,import_id,row_path),
 FOREIGN KEY(source_id,import_id) REFERENCES alpaca_calendar_captures);
'''


def iso_day(value):
    if not isinstance(value, str):
        raise ContractError('Canonical ISO date required')
    try:
        parsed=date.fromisoformat(value)
    except ValueError as exc:
        raise ContractError('Canonical ISO date required') from exc
    if parsed.isoformat() != value:
        raise ContractError('Canonical ISO date required')
    return parsed


def local_instant(day, value, zone):
    if not isinstance(value,str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',value):
        raise NormalizationError('legacy_hhmm_time_required')
    local=datetime.combine(day,time.fromisoformat(value),zone)
    if local.replace(fold=0).utcoffset() != local.replace(fold=1).utcoffset():
        raise NormalizationError('ambiguous_or_nonexistent_local_time')
    if local.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != local.replace(tzinfo=None):
        raise NormalizationError('nonexistent_local_time')
    return utc(local)


class AlpacaCalendarStore(AlpacaMarketStore):
    def __init__(self,database):
        super().__init__(database)
        self.db.executescript(SCHEMA)

    def import_calendar(self, *, source_id, import_id, payload, received_at, processed_at,
                        start_date, end_date, market_timezone='America/New_York',
                        calendar_kind='TRADING', venue='XNYS', provenance=None):
        """Stage one caller-supplied legacy regular-session response.

        start/end are explicit inclusive request bounds, not certified coverage.
        Legacy HH:MM is interpreted in New York; newer UTC/datetime response
        shapes must use a separately implemented normalizer.
        """
        if self.db.in_transaction:
            raise ContractError('Import requires an idle connection')
        required(source_id,'source_id');required(import_id,'import_id')
        start,end=iso_day(start_date),iso_day(end_date)
        if start > end:
            raise ContractError('Request start must not follow end')
        if calendar_kind != 'TRADING':
            raise ContractError('Only explicit TRADING calendar mode is supported')
        if market_timezone != 'America/New_York':
            raise ContractError('Legacy calendar fields require explicit America/New_York semantics')
        if venue not in {'XNYS','XNAS','IEXG'}:
            raise ContractError('Explicit supported US equity venue required')
        provenance_fields=None
        if provenance is not None:
            if not isinstance(provenance,dict) or set(provenance) != {'endpoint','method','query','route'}:
                raise ContractError('Calendar provenance has unexpected fields')
            route=provenance['route']
            if not isinstance(route,dict) or set(route) != {'broker_id','connection_id','account_id','environment'}:
                raise ContractError('Explicit broker connection/account/environment route required')
            try:
                account=BrokerAccount(**route)
            except (TypeError,ValueError) as exc:
                raise ContractError('Invalid calendar route') from exc
            if account.broker_id != 'alpaca' or account.environment != Environment.PAPER or provenance['endpoint'] != 'https://paper-api.alpaca.markets/v2/calendar' or provenance['method'] != 'GET':
                raise ContractError('Only declared paper GET calendar provenance is supported')
            query=provenance['query']
            if not isinstance(query,dict) or set(query) != {'start','end','date_type'}:
                raise ContractError('Unsupported calendar request query')
            if query['start'] != start_date or query['end'] != end_date or query['date_type'] != calendar_kind:
                raise ContractError('Calendar request provenance scope does not match import')
            provenance_fields=dict(endpoint=provenance['endpoint'],method='GET',query=dict(query),route=dict(route))
        zone=ZoneInfo(market_timezone)
        received,known=utc(received_at),utc(processed_at)
        if received > known:
            raise ContractError('Receipt must precede processing completion')
        if not isinstance(payload,bytes) or not payload:
            raise ContractError('Original nonempty response bytes required')
        for at in (received,known):
            self._require_use(source_id,Use.STORAGE,at)
        self._require_use(source_id,Use.RESEARCH,known)
        raw_sha=hashlib.sha256(payload).hexdigest()
        fields=dict(calendar_format=FORMAT,raw_sha=raw_sha,received_at=received,processed_at=known,
                    start_date=start_date,end_date=end_date,market_timezone=market_timezone,
                    calendar_kind=calendar_kind,venue=venue,provenance=provenance_fields)
        inputs=canonical(fields)
        old=self.db.execute('SELECT input_json FROM alpaca_calendar_captures WHERE source_id=? AND import_id=?',(source_id,import_id)).fetchone()
        if old:
            if old[0] != inputs:
                raise RecordConflict('Calendar import ID belongs to different input')
            return self.calendar_as_of(source_id,import_id,as_of=processed_at)
        parsed=[];quarantine=[];dates=[]
        try:
            rows=decode(payload)
            if not isinstance(rows,list):
                raise NormalizationError('legacy_calendar_array_required')
            for index,row in enumerate(rows):
                path=f'/{index}'
                try:
                    if not isinstance(row,dict) or not {'date','open','close'} <= row.keys() or row.keys()-{'date','open','close','session_open','session_close','settlement_date'}:
                        raise NormalizationError('unsupported_legacy_calendar_fields')
                    day=iso_day(row['date']);dates.append(row['date'])
                    if not start <= day <= end:
                        raise NormalizationError('date_outside_requested_range')
                    opened=local_instant(day,row['open'],zone);closed=local_instant(day,row['close'],zone)
                    if opened >= closed:
                        raise NormalizationError('regular_session_must_open_before_close')
                    parsed.append(dict(row_path=path,date=day.isoformat(),start=opened,end=closed,
                                       timezone=market_timezone,venue=venue,known_at=known,published_at=None,
                                       raw_local_open=row['open'],raw_local_close=row['close'],
                                       state='staged_unknown_publication'))
                except (ContractError,ValueError,TypeError) as exc:
                    quarantine.append(dict(row_path=path,reason=str(exc) if isinstance(exc,NormalizationError) else 'invalid_calendar_record'))
        except NormalizationError as exc:
            quarantine.append(dict(row_path='$',reason=str(exc)))
        counts=Counter(dates);accepted=[]
        for row in parsed:
            if counts[row['date']] != 1:
                quarantine.append(dict(row_path=row['row_path'],reason='duplicate_calendar_date'))
            else:
                accepted.append(row)
        result=dict(calendar_format=FORMAT,source_id=source_id,import_id=import_id,raw_sha=raw_sha,
                    received_at=received,available_at=known,start_date=start_date,end_date=end_date,
                    calendar_kind=calendar_kind,venue=venue,market_timezone=market_timezone,
                    time_semantics='legacy_open_close_local_hhmm',
                    capture_origin='supplied_bytes' if provenance_fields is None else 'declared_http_get',
                    provenance=provenance_fields,authenticated_account_verified=False,
                    candidates=sorted(accepted,key=lambda x:x['date']),
                    quarantined=sorted(quarantine,key=lambda x:x['row_path']),
                    response_rows_valid=not quarantine,calendar_complete=False,
                    unreported_dates_not_classified=True,full_history_verified=False,
                    training_ready=False,live_trading=False)
        encoded=canonical(result)
        digest_fields=dict(source_id=source_id,import_id=import_id,input_json=inputs,
                           raw_sha=raw_sha,available_at=known,result_json=encoded)
        digest=hashlib.sha256(canonical(digest_fields).encode()).hexdigest()
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO raw_objects VALUES (?,?)',(raw_sha,payload))
            raw=self.db.execute('SELECT payload FROM raw_objects WHERE sha256=?',(raw_sha,)).fetchone()
            if raw[0] != payload:
                raise EvidenceIntegrityError('Calendar raw archive integrity failed')
            self.db.execute('INSERT INTO alpaca_calendar_captures VALUES (?,?,?,?,?,?,?)',(source_id,import_id,inputs,raw_sha,known,encoded,digest))
            self.db.executemany('INSERT INTO alpaca_calendar_quarantine VALUES (?,?,?,?)',[(source_id,import_id,r['row_path'],r['reason']) for r in result['quarantined']])
        return result

    def calendar_as_of(self,source_id,import_id,*,as_of):
        at=utc(as_of)
        required(source_id,'source_id');required(import_id,'import_id')
        # A savepoint keeps raw/manifest/journal reads consistent and caller writes untouched.
        self.db.execute('SAVEPOINT calendar_capture_read')
        try:
            self._require_use(source_id,Use.RESEARCH,at)
            row=self.db.execute('SELECT * FROM alpaca_calendar_captures WHERE source_id=? AND import_id=? AND available_at<=?',(source_id,import_id,at)).fetchone()
            result=None
            if row is not None:
                fields={key:row[key] for key in ('source_id','import_id','input_json','raw_sha','available_at','result_json')}
                if hashlib.sha256(canonical(fields).encode()).hexdigest() != row['integrity_sha']:
                    raise EvidenceIntegrityError('Calendar manifest integrity failed')
                raw=self.db.execute('SELECT payload FROM raw_objects WHERE sha256=?',(row['raw_sha'],)).fetchone()
                if raw is None or hashlib.sha256(raw[0]).hexdigest() != row['raw_sha']:
                    raise EvidenceIntegrityError('Calendar raw archive integrity failed')
                result=json.loads(row['result_json'])
                journal=[dict(row_path=x[0],reason=x[1]) for x in self.db.execute('SELECT row_path,reason FROM alpaca_calendar_quarantine WHERE source_id=? AND import_id=? ORDER BY row_path',(source_id,import_id))]
                if journal != result['quarantined']:
                    raise EvidenceIntegrityError('Calendar quarantine journal integrity failed')
        except BaseException:
            self.db.execute('ROLLBACK TO calendar_capture_read');self.db.execute('RELEASE calendar_capture_read');raise
        else:
            self.db.execute('RELEASE calendar_capture_read');return result
