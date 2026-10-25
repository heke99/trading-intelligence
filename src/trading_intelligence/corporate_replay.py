"""Pure hypothetical corporate-action accounting proof for a fixed holding.

No real cash, position or order is written. Supplied actions do not establish
complete action coverage or independently verified dividend eligibility.
"""
from datetime import date, datetime, time
from decimal import (Context, Decimal, DecimalException, DivisionByZero, Inexact,
                     InvalidOperation, Overflow, ROUND_HALF_EVEN, localcontext)
import hashlib
import json
from zoneinfo import ZoneInfo

from .contracts import ContractError, utc
from .market_data import timestamp
from .market_replay import replay_dates
from .references import _time

POLICY_VERSION = 'fixed-long-holding-split-then-cash-v1'


def _amount(value, name):
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise ContractError(f'{name} must be a finite nonnegative Decimal')
    return value


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def _corporate_action_replay(store, source_id, listing_id, expected_dates, *, as_of,
                            opening_at, initial_cash, initial_shares, currency,
                            dividend_share_basis, dividend_policy):
    """Value a supplied opening long holding through known raw/action records.

    Caller must explicitly assert post-split-per-share dividend amounts and
    ordinary cash distributions without withholding. Other bases, special
    distributions/due bills, cash-in-lieu and withholding are unsupported.
    ``opening_at`` must precede the first declared local trading date. Existing
    receivables from before opening, trading, fees, FX and rounding are excluded.
    Known actions between opening and first valuation block the proof rather
    than silently changing the meaning of the supplied opening shares/cash.
    No returns/performance series or actual brokerage ledger is produced.
    """
    _amount(initial_cash, 'initial_cash')
    _amount(initial_shares, 'initial_shares')
    opened = utc(opening_at)
    if dividend_share_basis != 'post_split':
        raise ContractError('Explicit post_split dividend share basis required')
    if dividend_policy != 'ordinary_cash_no_withholding':
        raise ContractError('Only explicitly asserted ordinary cash without withholding is supported')
    replay = replay_dates(store, source_id, listing_id, expected_dates, as_of=as_of)
    if not replay['complete_scope']:
        raise ContractError('Price/session gaps block corporate-action valuation')
    # A supplied date list cannot omit known sessions or corporate actions
    # inside the valuation range. Unknown calendar/action coverage stays unknown.
    declared = set(replay['manifest']['expected_dates'])
    lower, upper = min(declared), max(declared)
    rows = store.db.execute(
        "SELECT m.kind,m.target_id,m.valid_from FROM market_snapshots m "
        "JOIN evidence_versions e USING(evidence_id) "
        "WHERE m.known_at<=? AND e.source_id=? AND m.kind IN ('session','split','cash_dividend')",
        (utc(as_of), source_id)).fetchall()
    for item in rows:
        target = json.loads(item['target_id'])
        if not isinstance(target, list) or len(target) != 3 or target[0] != source_id:
            raise ContractError('Invalid market record source identity')
        if target[1] != listing_id:
            continue
        event_date = target[2]
        omitted_in_range = lower <= event_date <= upper and event_date not in declared
        omitted_since_opening = (item['kind'] in {'split', 'cash_dividend'}
                                 and event_date < lower and item['valid_from'] >= opened)
        if omitted_in_range or omitted_since_opening:
            # Verify the record before reporting it as a known omitted event.
            store.market.get(item['kind'], item['target_id'],
                             effective_at=_time(item['valid_from']), as_of=as_of)
            raise ContractError('Scope omits a known session or action since the opening holding')
    first = replay['days'][0]
    zone = ZoneInfo(first['session']['values']['timezone'])
    boundary = datetime.combine(date.fromisoformat(first['date']), time.min, tzinfo=zone)
    if opened >= utc(boundary):
        raise ContractError('Opening holding must predate first local scope date')
    if any(day['bar']['currency'] != currency for day in replay['days']):
        raise ContractError('Opening currency must match the listing; no FX conversion')
    for day in replay['days']:
        session_open = timestamp(day['session']['start'])
        if any(timestamp(action['start']) > session_open for action in day['actions']):
            raise ContractError('Daily corporate-action policy requires effectiveness at or before session open')
    # Snapshot IDs bind observed actions; the proof never treats absent actions
    # as evidence of a complete corporate-action inventory.
    actions_by_id = {(x['date'], x['kind']): x['snapshot_id']
                     for x in replay['manifest']['records'] if x['kind'] in {'split', 'cash_dividend'}}
    inputs = {'opening_at': opened, 'initial_cash': str(initial_cash),
              'initial_shares': str(initial_shares), 'currency': currency,
              'dividend_share_basis': dividend_share_basis, 'dividend_policy': dividend_policy}
    manifest = {'policy_version': POLICY_VERSION, 'inputs': inputs,
                'input_sha256': hashlib.sha256(_json(inputs).encode()).hexdigest(),
                'market_manifest_sha256': replay['manifest_sha256'],
                'market_manifest': replay['manifest'],
                'interpretation': 'hypothetical_restatement_not_actual_money',
                'arithmetic': {'precision':50, 'rounding':'ROUND_HALF_EVEN',
                               'inexact':'reject', 'fractional_shares':'exact_only_no_cash_in_lieu'},
                'opening_receivables':'excluded_assumed_zero',
                'opening_to_first_valuation':'reject_known_actions',
                'action_effectiveness':'same_local_day_at_or_before_session_open'}
    rows, events, receivables = [], [], []
    shares, cash = initial_shares, initial_cash
    try:
        with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN,
                                  traps=[Inexact, InvalidOperation, DivisionByZero, Overflow])):
            for day in replay['days']:
                trading_date = day['date']
                actions = {x['kind']: x for x in day['actions']}
                if 'split' in actions:
                    action = actions['split']
                    new = Decimal(action['values']['new_shares'])
                    old = Decimal(action['values']['old_shares'])
                    before = shares
                    shares = shares * new / old
                    events.append({'kind':'split', 'date':trading_date,
                                   'snapshot_id':actions_by_id[(trading_date,'split')],
                                   'shares_before':str(before), 'shares_after':str(shares)})
                if 'cash_dividend' in actions:
                    action = actions['cash_dividend']
                    amount = shares * Decimal(action['values']['amount'])
                    snapshot_id = actions_by_id[(trading_date,'cash_dividend')]
                    receivables.append({'snapshot_id':snapshot_id, 'ex_date':trading_date,
                                        'payment_date':action['values']['payment_date'],
                                        'eligible_shares':str(shares), 'amount':str(amount), 'paid':False})
                    events.append({'kind':'dividend_entitlement','date':trading_date,
                                   'snapshot_id':snapshot_id,'amount':str(amount)})
                paid_today = Decimal(0)
                for item in receivables:
                    if not item['paid'] and item['payment_date'] <= trading_date:
                        paid = Decimal(item['amount'])
                        cash += paid
                        paid_today += paid
                        item['paid'] = True
                        events.append({'kind':'hypothetical_dividend_payment',
                                       'date':item['payment_date'], 'valued_on':trading_date,
                                       'snapshot_id':item['snapshot_id'],'amount':str(paid)})
                pending = sum((Decimal(x['amount']) for x in receivables if not x['paid']), Decimal(0))
                close = Decimal(day['bar']['values']['close'])
                market_value = shares * close
                rows.append({'date':trading_date, 'shares':str(shares), 'raw_close':str(close),
                             'market_value':str(market_value), 'cash':str(cash),
                             'dividend_cash_received':str(paid_today), 'receivable':str(pending),
                             'wealth':str(cash + pending + market_value)})
    except DecimalException as exc:
        raise ContractError('Exact proof arithmetic failed; rounding/cash-in-lieu is unsupported') from exc
    return {'manifest': manifest, 'manifest_sha256':hashlib.sha256(_json(manifest).encode()).hexdigest(),
            'days':rows, 'events':events, 'receivables':receivables,
            'final':rows[-1], 'action_coverage_verified':False, 'admitted_for_strategy':False,
            'training_ready':False, 'full_history_verified':False, 'live_trading':False}


def corporate_action_replay(store, source_id, listing_id, expected_dates, *, as_of,
                            opening_at, initial_cash, initial_shares, currency,
                            dividend_share_basis, dividend_policy):
    """Consistent read-snapshot wrapper; see the bounded proof's policy above."""
    store.db.execute('SAVEPOINT corporate_proof_read')
    try:
        answer = _corporate_action_replay(
            store, source_id, listing_id, expected_dates, as_of=as_of,
            opening_at=opening_at, initial_cash=initial_cash, initial_shares=initial_shares,
            currency=currency, dividend_share_basis=dividend_share_basis,
            dividend_policy=dividend_policy)
    except BaseException:
        store.db.execute('ROLLBACK TO corporate_proof_read')
        store.db.execute('RELEASE corporate_proof_read')
        raise
    else:
        store.db.execute('RELEASE corporate_proof_read')
        return answer
