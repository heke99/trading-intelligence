"""Offline, single-currency journal of supplied hypothetical accounting events."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction
import hashlib
import json
import re
import sqlite3

from .contracts import ContractError, EvidenceIntegrityError, RecordConflict, utc


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def number(value, *, positive=False):
    if not isinstance(value, str) or not value or len(value) > 80 or re.fullmatch(r'(?:0|[1-9][0-9]*)(?:\.[0-9]+)?', value) is None:
        raise ContractError('Decimal amounts must be bounded strings')
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ContractError('Invalid decimal amount') from None
    if not result.is_finite() or result < 0 or (positive and result <= 0):
        raise ContractError('Finite nonnegative decimal required')
    if result.adjusted() > 24 or result.as_tuple().exponent < -18:
        raise ContractError('Decimal precision outside pilot bounds')
    return result


def instant(value):
    if not isinstance(value, str):
        raise ContractError('Explicit timestamp string required')
    try:
        return utc(datetime.fromisoformat(value.replace('Z', '+00:00')))
    except (ValueError, TypeError):
        raise ContractError('Timezone-aware timestamp required') from None


class CashLedgerStore:
    """SQLite audit journal, not broker positions, a fill model or an order API."""
    def __init__(self, database, *, clock=None):
        self.db = sqlite3.connect(database)
        self.db.row_factory = sqlite3.Row
        self.db.execute('CREATE TABLE IF NOT EXISTS cash_events (sequence INTEGER PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, body TEXT NOT NULL, recorded_at TEXT NOT NULL, sha256 TEXT NOT NULL)')
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def close(self):
        self.db.close()

    def _validate(self, event):
        if not isinstance(event, dict):
            raise ContractError('Event object required')
        common = {'event_id','kind','occurred_at','observed_at','currency','origin','source_ref'}
        extras = {'opening_cash':{'amount'}, 'buy':{'instrument_id','quantity','price','fee'}, 'sell':{'instrument_id','quantity','price','fee'}, 'split':{'instrument_id','numerator','denominator'}, 'dividend':{'instrument_id','amount'}}
        kind = event.get('kind')
        if not isinstance(kind, str) or kind not in extras or set(event) != common | extras[kind]:
            raise ContractError('Unsupported event kind/fields; corrections require a new reviewed ledger')
        for field in ('event_id','source_ref'):
            if not isinstance(event[field], str) or not event[field].strip():
                raise ContractError('Event ID and explicit source reference required')
        if event['origin'] not in ('synthetic_fixture', 'externally_supplied_simulation'):
            raise ContractError('Only explicit offline simulated origins supported')
        currency = event['currency']
        if not isinstance(currency, str) or len(currency) != 3 or not currency.isascii() or not currency.isalpha() or currency != currency.upper():
            raise ContractError('Explicit three-letter currency required')
        occurred = instant(event['occurred_at']); observed = instant(event['observed_at'])
        if occurred > observed:
            raise ContractError('Observation cannot precede its declared event')
        if 'instrument_id' in event:
            if not isinstance(event['instrument_id'], str) or not event['instrument_id'].strip():
                raise ContractError('Explicit instrument identity required')
        for field in extras[kind] - {'instrument_id'}:
            number(event[field], positive=field in {'quantity','price','numerator','denominator'})
        return {**event, 'occurred_at':occurred, 'observed_at':observed}

    def _events(self, cutoff):
        records = []
        previous_recorded = None
        for expected_sequence, row in enumerate(self.db.execute('SELECT * FROM cash_events ORDER BY sequence'), start=1):
            if row['sequence'] != expected_sequence or (previous_recorded is not None and row['recorded_at'] < previous_recorded):
                raise EvidenceIntegrityError('Cash journal ordering integrity failure')
            previous_recorded = row['recorded_at']
            try:
                body = json.loads(row['body'])
            except (ValueError, TypeError):
                raise EvidenceIntegrityError('Cash journal body is corrupt') from None
            if not isinstance(body, dict):
                raise EvidenceIntegrityError('Cash journal body is corrupt')
            manifest = {'event':body,'recorded_at':row['recorded_at'],'sequence':row['sequence']}
            if hashlib.sha256(canonical(manifest).encode()).hexdigest() != row['sha256'] or body.get('event_id') != row['event_id']:
                raise EvidenceIntegrityError('Cash journal integrity failure')
            if row['recorded_at'] <= cutoff:
                records.append(self._validate(body))
        return records

    def _calculate(self, events):
        cash = Decimal('0'); positions = {}; currency = origin = previous = None
        with localcontext() as context:
            context.prec = 100
            for event in events:
                kind = event['kind']
                if currency is None:
                    if kind != 'opening_cash':
                        raise ContractError('First event must declare opening cash')
                    currency, origin = event['currency'], event['origin']
                elif kind == 'opening_cash' or event['currency'] != currency or event['origin'] != origin:
                    raise ContractError('One opening cash, currency and simulation origin per ledger')
                if previous is not None and event['occurred_at'] < previous:
                    raise ContractError('Economic events must be appended in chronological order')
                previous = event['occurred_at']
                instrument = event.get('instrument_id')
                if kind == 'opening_cash':
                    cash = number(event['amount'])
                elif kind in ('buy','sell'):
                    quantity = number(event['quantity'], positive=True)
                    gross = quantity * number(event['price'], positive=True)
                    fee = number(event['fee'])
                    old = positions.get(instrument, Decimal('0'))
                    if kind == 'buy':
                        cash -= gross + fee; positions[instrument] = old + quantity
                    else:
                        if quantity > old:
                            raise ContractError('Short positions unsupported')
                        cash += gross - fee; positions[instrument] = old - quantity
                elif kind == 'split':
                    if positions.get(instrument, Decimal('0')) <= 0:
                        raise ContractError('Split requires held position')
                    numerator = number(event['numerator'], positive=True); denominator = number(event['denominator'], positive=True)
                    exact = Fraction(positions[instrument]) * Fraction(numerator) / Fraction(denominator)
                    remaining = exact.denominator
                    for factor in (2,5):
                        while remaining % factor == 0:
                            remaining //= factor
                    if remaining != 1:
                        raise ContractError('Nonterminating split quantity unsupported')
                    quantity = Decimal(exact.numerator) / Decimal(exact.denominator)
                    number(format(quantity, 'f'))
                    positions[instrument] = quantity
                else:
                    if positions.get(instrument, Decimal('0')) <= 0:
                        raise ContractError('Dividend requires held position; amount is supplied total cash')
                    cash += number(event['amount'])
                if cash < 0:
                    raise ContractError('Negative cash unsupported')
        return {'currency':currency,'origin':origin,'cash':str(cash),'positions':{k:str(v) for k,v in sorted(positions.items()) if v},'event_count':len(events),'authoritative_broker_state':False,'orders_sent':0}

    def state(self, *, as_of=None):
        current = utc(self._clock()); cutoff = utc(as_of) if as_of is not None else current
        if cutoff > current:
            raise ContractError('Future cutoff unsupported')
        self.db.execute('SAVEPOINT cash_read')
        try:
            return {**self._calculate(self._events(cutoff)), 'as_of':cutoff}
        finally:
            self.db.execute('ROLLBACK TO cash_read'); self.db.execute('RELEASE cash_read')

    def append_event(self, event):
        if self.db.in_transaction:
            raise ContractError('Cash writes require idle connection')
        return self._append_batch([event])[0]

    def _append_batch(self, events):
        now = utc(self._clock())
        try:
            self.db.execute('BEGIN IMMEDIATE')
            latest = self.db.execute('SELECT MAX(recorded_at) FROM cash_events').fetchone()[0]
            if latest is not None and now < latest:
                raise ContractError('Registration clock cannot move backwards')
            existing = self._events(now); result = []
            for supplied in events:
                event = self._validate(supplied)
                if event['observed_at'] > now:
                    raise ContractError('Observation cannot exceed registration clock')
                body = canonical(event)
                old = self.db.execute('SELECT * FROM cash_events WHERE event_id=?',(event['event_id'],)).fetchone()
                if old:
                    if old['body'] != body:
                        raise RecordConflict('Event ID identifies different immutable content')
                    result.append(dict(old)); continue
                self._calculate(existing + [event])
                sequence = len(existing) + 1
                manifest = {'event':event,'recorded_at':now,'sequence':sequence}
                sha = hashlib.sha256(canonical(manifest).encode()).hexdigest()
                self.db.execute('INSERT INTO cash_events(sequence,event_id,body,recorded_at,sha256) VALUES (?,?,?,?,?)',(sequence,event['event_id'],body,now,sha))
                existing.append(event)
                result.append({'event_id':event['event_id'],'body':body,'recorded_at':now,'sha256':sha})
            self.db.commit(); return result
        except Exception:
            self.db.rollback(); raise

    def import_declared_report(self, payload):
        """Import our declared JSON contract, not an inferred native LEAN schema."""
        if self.db.in_transaction:
            raise ContractError('Cash writes require idle connection')
        if not isinstance(payload, bytes) or len(payload) > 2_000_000:
            raise ContractError('Bounded JSON bytes required')
        def unique(pairs):
            result = {}
            for key,value in pairs:
                if key in result:
                    raise ContractError('Duplicate JSON field')
                result[key] = value
            return result
        try:
            report = json.loads(payload, object_pairs_hook=unique)
        except (ValueError, UnicodeError):
            raise ContractError('Invalid declared report JSON') from None
        if not isinstance(report,dict) or set(report) != {'format','events'} or report['format'] != 'offline-cash-events-v1' or not isinstance(report['events'],list) or not 1 <= len(report['events']) <= 10000:
            raise ContractError('Declared offline-cash-events-v1 format required')
        return self._append_batch(report['events'])

    def reconcile(self, *, expected_currency, expected_cash, expected_positions, cash_tolerance, quantity_tolerance):
        cash = number(expected_cash); ct = number(cash_tolerance); qt = number(quantity_tolerance)
        if not isinstance(expected_positions,dict) or any(not isinstance(k,str) or not k.strip() for k in expected_positions):
            raise ContractError('Explicit instrument quantities required')
        expected = {k:number(v) for k,v in expected_positions.items()}
        state = self.state()
        if state['currency'] is None or expected_currency != state['currency']:
            raise ContractError('Expected snapshot currency must match opened ledger')
        actual = {k:Decimal(v) for k,v in state['positions'].items()}
        with localcontext() as context:
            context.prec = 100
            cash_difference = Decimal(state['cash']) - cash
            differences = {k:str(actual.get(k,Decimal('0')) - expected.get(k,Decimal('0'))) for k in sorted(actual.keys() | expected.keys())}
        matches = cash_difference.copy_abs() <= ct and all(Decimal(v).copy_abs() <= qt for v in differences.values())
        report = {'matches':matches,'cash_difference':str(cash_difference),'quantity_differences':differences,'cash_tolerance':cash_tolerance,'quantity_tolerance':quantity_tolerance,'snapshot_origin':'externally_declared_comparison','broker_verified':False}
        if not matches:
            raise ContractError('Cash/position reconciliation mismatch: ' + canonical(report))
        return report
