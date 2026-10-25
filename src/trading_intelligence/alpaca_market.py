"""Offline Alpaca daily-bar capture staging. No fabricated publication/session times."""
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from zoneinfo import ZoneInfo

from .alpaca_normalizer import decode, NormalizationError
from .contracts import ContractError, EvidenceIntegrityError, RecordConflict, Use, currency, required, utc
from .market_data import MarketDataStore, timestamp

VERSION = 'alpaca-market-capture-1'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS alpaca_market_captures (
 source_id TEXT NOT NULL REFERENCES sources, import_id TEXT NOT NULL,
 input_json TEXT NOT NULL, raw_sha TEXT NOT NULL REFERENCES raw_objects,
 available_at TEXT NOT NULL, result_json TEXT NOT NULL, integrity_sha TEXT NOT NULL,
 PRIMARY KEY(source_id,import_id));
CREATE TABLE IF NOT EXISTS alpaca_market_quarantine (
 source_id TEXT NOT NULL, import_id TEXT NOT NULL, row_path TEXT NOT NULL,
 reason TEXT NOT NULL, PRIMARY KEY(source_id,import_id,row_path),
 FOREIGN KEY(source_id,import_id) REFERENCES alpaca_market_captures);
'''


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def amount(value, *, positive=False):
    if isinstance(value, (bool, float)) or not isinstance(value, (int, Decimal)):
        raise NormalizationError('invalid_provider_number')
    try:
        value = Decimal(value)
    except (InvalidOperation, TypeError):
        raise NormalizationError('invalid_provider_number') from None
    if not value.is_finite() or value < 0 or (positive and value == 0):
        raise NormalizationError('invalid_provider_number')
    return str(value)


class AlpacaMarketStore(MarketDataStore):
    def __init__(self, database):
        super().__init__(database)
        self.db.executescript(SCHEMA)

    def import_bars(self, *, source_id, import_id, payload, received_at, processed_at,
                    symbol_listings, feed, timeframe, adjustment, market_timezone, request_currency="USD"):
        """Archive one supplied multi-symbol response page and stage its candidates.

        Request configuration is caller-declared, not authenticated provenance.
        No candidates are promoted into market_snapshots or evidence_versions.
        """
        if self.db.in_transaction:
            raise ContractError('Import requires an idle connection; caller transactions are not committed')
        required(source_id, 'source_id'); required(import_id, 'import_id')
        required(feed, 'feed'); required(timeframe, 'timeframe'); required(adjustment, 'adjustment')
        if feed not in {'iex', 'sip'}:
            raise ContractError('Only declared IEX or SIP daily equity feeds are supported')
        required(request_currency, 'request_currency'); currency(request_currency)
        received, known = utc(received_at), utc(processed_at)
        if received > known:
            raise ContractError('Receipt must precede processing completion')
        if not isinstance(payload, bytes) or not payload:
            raise ContractError('Original nonempty response bytes required')
        if timeframe != '1Day' or adjustment != 'raw':
            raise ContractError('Only explicitly raw daily bars are supported')
        if not isinstance(symbol_listings, dict) or not symbol_listings:
            raise ContractError('Explicit symbol to listing mapping required')
        required(market_timezone, 'market_timezone')
        try:
            zone = ZoneInfo(market_timezone)
        except (ValueError, KeyError) as exc:
            raise ContractError('Invalid market timezone') from exc
        bindings = {}
        for symbol, listing_id in symbol_listings.items():
            required(symbol, 'symbol'); required(listing_id, 'listing_id')
            row = self.db.execute('SELECT trading_currency FROM listings WHERE listing_id=?', (listing_id,)).fetchone()
            if row is None:
                raise ContractError('Unknown explicit listing')
            if row[0] != request_currency:
                raise ContractError('Request currency does not match listing')
            bindings[symbol] = dict(listing_id=listing_id, currency=row[0])
        if len({b['listing_id'] for b in bindings.values()}) != len(bindings):
            raise ContractError('Ambiguous symbols map to the same listing')
        for at in (received, known):
            self._require_use(source_id, Use.STORAGE, at)
        self._require_use(source_id, Use.RESEARCH, known)
        raw_sha = hashlib.sha256(payload).hexdigest()
        inputs = canonical(dict(version=VERSION, raw_sha=raw_sha, received_at=received,
                                processed_at=known, bindings=bindings, feed=feed,
                                timeframe=timeframe, adjustment=adjustment, market_timezone=market_timezone, request_currency=request_currency))
        old = self.db.execute('SELECT * FROM alpaca_market_captures WHERE source_id=? AND import_id=?', (source_id,import_id)).fetchone()
        if old:
            if old['input_json'] != inputs:
                raise RecordConflict('Import ID already belongs to different input')
            return self.capture_as_of(source_id, import_id, as_of=processed_at)
        quarantined, parsed = [], []
        try:
            response = decode(payload)
            if not isinstance(response, dict) or not isinstance(response.get('bars'), dict):
                raise NormalizationError('bars_object_required')
            token_present = 'next_page_token' in response
            token = response.get('next_page_token')
            if token is not None and (not isinstance(token, str) or not token.strip()):
                raise NormalizationError('invalid_page_token')
            for symbol, rows in response['bars'].items():
                if symbol not in bindings:
                    quarantined.append(dict(row_path=f'bars/{symbol.replace("~","~0").replace("/","~1")}', reason='unmapped_symbol'))
                    continue
                if not isinstance(rows, list):
                    quarantined.append(dict(row_path=f'bars/{symbol.replace("~","~0").replace("/","~1")}', reason='bar_array_required'))
                    continue
                for index, row in enumerate(rows):
                    path = f'bars/{symbol.replace("~","~0").replace("/","~1")}/{index}'
                    try:
                        if not isinstance(row, dict) or not {'t','o','h','l','c','v'} <= row.keys():
                            raise NormalizationError('required_bar_fields_missing')
                        at = timestamp(row['t'])
                        if utc(at) > received:
                            raise NormalizationError('bar_timestamp_after_receipt')
                        values = {name: amount(row[key], positive=True) for name,key in [('open','o'),('high','h'),('low','l'),('close','c')]}
                        values['volume'] = amount(row['v'])
                        if Decimal(values['volume']) != Decimal(values['volume']).to_integral_value():
                            raise NormalizationError('nonintegral_share_volume')
                        prices = {k: Decimal(values[k]) for k in ('open','high','low','close')}
                        if not prices['low'] <= min(prices['open'],prices['close']) <= max(prices['open'],prices['close']) <= prices['high']:
                            raise NormalizationError('invalid_ohlc_bounds')
                        parsed.append(dict(row_path=path, symbol=symbol, **bindings[symbol],
                                           provider_timestamp_raw=row['t'], provider_timestamp=utc(at), date=at.astimezone(zone).date().isoformat(),
                                           values=values, price_kind='raw', published_at=None,
                                           session_start=None, session_end=None, state='staged_unknown_publication'))
                    except (ContractError, TypeError, ValueError) as exc:
                        reason = str(exc) if isinstance(exc, NormalizationError) else 'invalid_bar_record'
                        quarantined.append(dict(row_path=path, reason=reason))
        except NormalizationError as exc:
            token_present, token = False, None
            quarantined.append(dict(row_path='$', reason=str(exc)))
        identities = Counter((r['listing_id'], r['date']) for r in parsed)
        accepted = []
        for row in parsed:
            if identities[(row['listing_id'], row['date'])] != 1:
                quarantined.append(dict(row_path=row['row_path'], reason='ambiguous_daily_bar'))
            else:
                accepted.append(row)
        result = dict(version=VERSION, source_id=source_id, import_id=import_id,
                      capture_origin='supplied_bytes', raw_sha=raw_sha, received_at=received, available_at=known,
                      candidates=accepted, quarantined=sorted(quarantined, key=lambda x:x['row_path']),
                      pagination_state=('terminal_page' if token is None else 'more_pages') if token_present else 'unknown',
                      next_page_token=token, page_complete=token_present and token is None and not quarantined,
                      full_history_verified=False, training_ready=False, live_trading=False)
        encoded = canonical(result)
        integrity = hashlib.sha256(canonical(dict(source_id=source_id, import_id=import_id, input_json=inputs,
                                                raw_sha=raw_sha, available_at=known, result_json=encoded)).encode()).hexdigest()
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO raw_objects VALUES (?,?)',(raw_sha,payload))
            saved = self.db.execute('SELECT payload FROM raw_objects WHERE sha256=?',(raw_sha,)).fetchone()
            if saved[0] != payload:
                raise EvidenceIntegrityError('Raw capture integrity failed')
            self.db.execute('INSERT INTO alpaca_market_captures VALUES (?,?,?,?,?,?,?)', (source_id,import_id,inputs,raw_sha,known,encoded,integrity))
            self.db.executemany('INSERT INTO alpaca_market_quarantine VALUES (?,?,?,?)',
                                [(source_id,import_id,q['row_path'],q['reason']) for q in result['quarantined']])
        return result

    def capture_as_of(self, source_id, import_id, *, as_of):
        at = utc(as_of)
        self._require_use(source_id, Use.RESEARCH, at)
        row = self.db.execute('SELECT * FROM alpaca_market_captures WHERE source_id=? AND import_id=? AND available_at<=?', (source_id,import_id,at)).fetchone()
        if row is None:
            return None
        fields = {key:row[key] for key in ('source_id','import_id','input_json','raw_sha','available_at','result_json')}
        if hashlib.sha256(canonical(fields).encode()).hexdigest() != row['integrity_sha']:
            raise EvidenceIntegrityError('Capture manifest integrity failed')
        raw = self.db.execute('SELECT payload FROM raw_objects WHERE sha256=?',(row['raw_sha'],)).fetchone()
        if raw is None or hashlib.sha256(raw[0]).hexdigest() != row['raw_sha']:
            raise EvidenceIntegrityError('Raw capture integrity failed')
        result = json.loads(row['result_json'])
        quarantine = [dict(row_path=x[0],reason=x[1]) for x in self.db.execute('SELECT row_path,reason FROM alpaca_market_quarantine WHERE source_id=? AND import_id=? ORDER BY row_path',(source_id,import_id))]
        if quarantine != result['quarantined']:
            raise EvidenceIntegrityError('Quarantine journal integrity failed')
        return result
