"""Evidence-backed normalized daily market records. Offline, no vendor/feed claims."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import json
from zoneinfo import ZoneInfo

from .contracts import ContractError, Use, currency, required, utc
from .references import ReferenceRepository, ReferenceUnavailable, _key, _time
from .store import EvidenceStore

SCHEMA = '''CREATE TABLE IF NOT EXISTS market_snapshots (
 snapshot_id TEXT PRIMARY KEY, kind TEXT NOT NULL, target_id TEXT NOT NULL,
 valid_from TEXT NOT NULL, valid_to TEXT NOT NULL, known_at TEXT NOT NULL,
 evidence_id TEXT NOT NULL REFERENCES evidence_versions, body TEXT NOT NULL,
 UNIQUE(kind,target_id,valid_from,known_at));'''


def decimal_text(value, *, positive=False):
    if not isinstance(value, str):
        raise ContractError('Numbers must be explicit decimal strings')
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ContractError('Invalid decimal') from exc
    if not number.is_finite() or number < 0 or (positive and number == 0):
        raise ContractError('Invalid numeric range')
    return value


def timestamp(value):
    if not isinstance(value, str):
        raise ContractError('Explicit timestamp string required')
    try:
        return _time(utc(datetime.fromisoformat(value.replace('Z', '+00:00'))))
    except (ValueError, TypeError) as exc:
        raise ContractError('Invalid timestamp') from exc


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError('Duplicate JSON key')
        result[key] = value
    return result


class MarketDataStore(EvidenceStore):
    def __init__(self, database):
        super().__init__(database)
        self.db.executescript(SCHEMA)
        self.market = ReferenceRepository(self, 'market_snapshots')

    def import_record(self, *, source_id, record_id, revision_id, payload,
                      published_at, received_at, processed_at, correction_of=None):
        """One normalized record per raw payload; timestamps are caller assertions.

        A source must keep record_id stable for revisions of the same record.
        Raw evidence may survive a failed snapshot write; no batch completeness is implied.
        """
        published, received, known = map(utc, (published_at, received_at, processed_at))
        if not published <= received <= known:
            raise ContractError('Require publication <= receipt <= processing completion')
        self._require_use(source_id, Use.STORAGE, known)
        self._require_use(source_id, Use.RESEARCH, known)
        if not isinstance(payload, bytes) or not payload:
            raise ContractError('Original bytes required')
        try:
            body = json.loads(payload, object_pairs_hook=unique_object)
        except (ValueError, UnicodeError) as exc:
            raise ContractError('Invalid normalized JSON') from exc
        if not isinstance(body, dict):
            raise ContractError('A normalized object is required')
        expected = {'kind', 'listing_id', 'date', 'start', 'end', 'currency', 'values'}
        if set(body) != expected or not isinstance(body['values'], dict):
            raise ContractError('Unexpected normalized fields')
        kind = body['kind']
        if kind not in {'session', 'bar', 'split', 'cash_dividend'}:
            raise ContractError('Unsupported record kind')
        listing = self.db.execute('SELECT * FROM listings WHERE listing_id=?',
                                  (body['listing_id'],)).fetchone()
        if listing is None or body['currency'] != listing['trading_currency']:
            raise ContractError('Explicit listing and matching currency required')
        required(body['currency'], 'currency')
        currency(body['currency'])
        try:
            day = date.fromisoformat(body['date']).isoformat()
        except (ValueError, TypeError) as exc:
            raise ContractError('Invalid trading date') from exc
        if day != body['date']:
            raise ContractError('Canonical trading date required')
        start, end = timestamp(body['start']), timestamp(body['end'])
        if start >= end:
            raise ContractError('Nonempty effective interval required')
        values = body['values']
        if kind == 'session':
            if set(values) != {'timezone'}:
                raise ContractError('Session timezone required')
            try:
                zone = ZoneInfo(values['timezone'])
            except (ValueError, TypeError, KeyError) as exc:
                raise ContractError('Unknown IANA timezone') from exc
            if start.astimezone(zone).date().isoformat() != day:
                raise ContractError('Session start must match local trading date')
            # Only one contiguous daytime daily-equity session is supported here.
            if end.astimezone(zone).date().isoformat() != day:
                raise ContractError('Overnight sessions require the futures model')
        elif kind == 'bar':
            if set(values) != {'open', 'high', 'low', 'close', 'volume', 'price_kind'}:
                raise ContractError('Raw OHLCV fields required')
            if values['price_kind'] != 'raw':
                raise ContractError('Adjusted prices cannot be imported as raw bars')
            prices = {k: Decimal(decimal_text(values[k], positive=True))
                      for k in ('open', 'high', 'low', 'close')}
            decimal_text(values['volume'])
            if not prices['low'] <= min(prices['open'], prices['close']) <= max(prices['open'], prices['close']) <= prices['high']:
                raise ContractError('Invalid OHLC bounds')
            if utc(end) > published:
                raise ContractError('A completed bar cannot be published before its end')
        elif kind == 'split':
            if set(values) != {'new_shares', 'old_shares'}:
                raise ContractError('Explicit split ratio required')
            for key in values:
                decimal_text(values[key], positive=True)
        else:
            if set(values) != {'amount', 'payment_date'}:
                raise ContractError('Dividend amount and payment date required')
            decimal_text(values['amount'])
            try:
                payment = date.fromisoformat(values['payment_date'])
            except (ValueError, TypeError) as exc:
                raise ContractError('Invalid payment date') from exc
            if payment < date.fromisoformat(day):
                raise ContractError('Payment precedes ex-date')
        target = _key(source_id, body['listing_id'], day)
        if correction_of:
            previous = self.db.execute('SELECT kind,target_id,valid_from,known_at FROM market_snapshots WHERE evidence_id=?',
                                       (correction_of,)).fetchone()
            if previous is None or tuple(previous)[:3] != (kind, target, utc(start)):
                raise ContractError('Correction must retain record identity and start')
            if known <= previous['known_at']:
                raise ContractError('Correction processing must follow its predecessor')
        # Requiring explicit correction lineage prevents unlinked replacement records.
        prior = self.db.execute('SELECT evidence_id FROM market_snapshots WHERE kind=? AND target_id=? AND valid_from=?',
                                (kind, target, utc(start))).fetchall()
        same = self.db.execute('SELECT evidence_id FROM evidence_versions WHERE source_id=? AND record_id=? AND revision_id=?',
                               (source_id, record_id, revision_id)).fetchone()
        if prior and same is None and not correction_of:
            raise ContractError('Replacement requires correction lineage')
        evidence = self.ingest(source_id=source_id, record_id=record_id, revision_id=revision_id,
                               payload=payload, published_at=published_at, received_at=received_at,
                               correction_of=correction_of)
        existing = self.db.execute('SELECT snapshot_id,known_at FROM market_snapshots WHERE evidence_id=?', (evidence,)).fetchone()
        if existing:
            if existing['known_at'] != known:
                raise ContractError('Processing availability cannot change on retry')
            verified = self.market.get(kind, target, effective_at=start, as_of=processed_at)
            if verified.snapshot_id != existing['snapshot_id']:
                raise ContractError('Retry does not resolve to its original snapshot')
            return existing['snapshot_id']
        return self.market.put(kind, target, body, valid_from=start, valid_to=end,
                               known_at=processed_at, evidence_id=evidence)

    def replay_day(self, source_id, listing_id, trading_date, *, as_of):
        """Require both session and completed raw bar; never invent a missing day."""
        at = utc(as_of)
        target = _key(source_id, listing_id, trading_date)
        def get(kind, required_record=True):
            rows = self.db.execute('SELECT valid_from FROM market_snapshots WHERE kind=? AND target_id=? AND known_at<=?',
                                   (kind, target, at)).fetchall()
            starts = {r['valid_from'] for r in rows}
            if not starts and not required_record:
                return None
            if len(starts) != 1:
                raise ReferenceUnavailable('Missing or ambiguous daily record')
            return self.market.get(kind, target, effective_at=_time(starts.pop()), as_of=as_of)
        session, bar = get('session'), get('bar')
        if any(session.body[k] != bar.body[k] for k in ('start', 'end')):
            # Compare instants, not provider formatting/timezone offsets.
            if any(timestamp(session.body[k]) != timestamp(bar.body[k]) for k in ('start', 'end')):
                raise ContractError('Daily bar must match the supplied session')
        actions = [x for x in (get('split', False), get('cash_dividend', False)) if x]
        zone = ZoneInfo(session.body['values']['timezone'])
        if any(timestamp(x.body['start']).astimezone(zone).date().isoformat() != trading_date for x in actions):
            raise ContractError('Action effective start does not match the local trading date')
        return {'session': session, 'bar': bar, 'actions': actions,
                'training_ready': False, 'live_trading': False}
