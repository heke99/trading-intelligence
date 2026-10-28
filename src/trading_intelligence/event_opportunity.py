"""Evidence-bound event price sensitivity, not a forecast or order approval."""
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext
import json

from .contracts import ContractError, EvidenceIntegrityError, RecordConflict, Use, utc, required
from .event_analysis import EventAnalysisStore, canonical, digest, _write_locked, _read_snapshot

VERSION = 'event-opportunity-1'
SCHEMA = '''
CREATE TABLE IF NOT EXISTS event_opportunities (
 assessment_id TEXT PRIMARY KEY, available_at TEXT NOT NULL,
 body_json TEXT NOT NULL, sha256 TEXT NOT NULL);
'''


def number(value, *, positive=False):
    if not isinstance(value, str) or len(value) > 60:
        raise ContractError('Explicit bounded decimal strings are required')
    try:
        result = Decimal(value)
    except InvalidOperation:
        raise ContractError('Invalid decimal') from None
    if not result.is_finite() or result.copy_abs() > Decimal('1e15') or result.as_tuple().exponent < -12:
        raise ContractError('Decimal outside supported precision/range')
    if positive and result <= 0:
        raise ContractError('A positive decimal is required')
    return result


def instant(value):
    try:
        return utc(datetime.fromisoformat(value.replace('Z', '+00:00')))
    except (ValueError, TypeError, AttributeError):
        raise ContractError('Explicit timezone-aware timestamp required') from None


def fields(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ContractError('Missing or unexpected input fields')


def calculate(inputs, analysis, request, at):
    """Pure exact-decimal sensitivity on supplied assumptions, no probabilities."""
    fields(inputs, ('listing_id', 'currency', 'quote_at', 'valid_until', 'bid', 'ask',
                    'quantity', 'entry_fee_per_unit', 'exit_fee_per_unit',
                    'slippage_per_unit_per_leg', 'exit_half_spread', 'borrow_cost_per_unit',
                    'scenario_exit_mids', 'scenario_exit_at', 'portfolio', 'pre_event_reference'))
    for key in ('listing_id', 'currency'):
        required(inputs[key], key)
    quote, valid = instant(inputs['quote_at']), instant(inputs['valid_until'])
    if quote > at or valid <= quote:
        raise ContractError('Quote timing is inconsistent')
    bid, ask = number(inputs['bid'], positive=True), number(inputs['ask'], positive=True)
    quantity = number(inputs['quantity'], positive=True)
    if bid > ask:
        raise ContractError('Crossed quote rejected')
    costs = [number(inputs[k]) for k in ('entry_fee_per_unit', 'exit_fee_per_unit',
                                        'slippage_per_unit_per_leg', 'exit_half_spread')]
    if any(x < 0 for x in costs):
        raise ContractError('Costs cannot be negative')
    borrow = None if inputs['borrow_cost_per_unit'] is None else number(inputs['borrow_cost_per_unit'])
    if borrow is not None and borrow < 0:
        raise ContractError('Borrow cost cannot be negative')
    portfolio = inputs['portfolio']
    fields(portfolio, ('broker', 'connection', 'account', 'environment', 'observed_at',
                       'valid_until', 'position_units', 'pending_buy_units', 'pending_sell_units'))
    for key in ('broker', 'connection', 'account'):
        required(portfolio[key], key)
    if portfolio['environment'] not in ('paper', 'live'):
        raise ContractError('Explicit account environment required')
    position = number(portfolio['position_units'])
    pending = [None if portfolio[k] is None else number(portfolio[k])
               for k in ('pending_buy_units', 'pending_sell_units')]
    if any(x is not None and x < 0 for x in pending):
        raise ContractError('Pending quantities cannot be negative')
    observed, port_valid = instant(portfolio['observed_at']), instant(portfolio['valid_until'])
    if observed > at or port_valid <= observed:
        raise ContractError('Portfolio timing is inconsistent')
    scenarios = analysis['output']['scenarios']
    selected = [s for s in scenarios if s['listing_id'] == inputs['listing_id']]
    targets = inputs['scenario_exit_mids']
    if not isinstance(targets, dict) or set(targets) != {s['scenario_id'] for s in selected}:
        raise ContractError('Exit assumptions must match the selected listing scenarios exactly')
    prices = {key: number(value) for key, value in targets.items()}
    if any(value < costs[3] for value in prices.values()):
        raise ContractError('Terminal midpoint cannot imply a negative exit bid')
    exit_times = inputs['scenario_exit_at']
    if not isinstance(exit_times, dict) or set(exit_times) != set(prices):
        raise ContractError('Each price assumption needs an explicit matching exit time')
    exit_times = {key: instant(value) for key, value in exit_times.items()}
    if any(value <= at for value in exit_times.values()):
        raise ContractError('Scenario exit time must follow the input cutoff')
    pre = inputs['pre_event_reference']
    reaction = None
    if pre is not None:
        fields(pre, ('mid', 'observed_at'))
        occurred = request['input']['context']['event']['occurred_at']
        if occurred is None or instant(pre['observed_at']) >= occurred:
            raise ContractError('Reaction reference must precede event occurrence')
        base = number(pre['mid'], positive=True)
        reaction = str(((bid + ask) / 2 / base - 1) * 100)
    reasons = []
    if analysis['output']['status'] != 'investigate' or not selected:
        reasons.append('no_listing_scenarios')
    if analysis['expired_on_arrival'] or at >= analysis['expires_at']:
        reasons.append('analysis_expired')
    elapsed = lambda stamp: (datetime.fromisoformat(at.replace('Z', '+00:00')) - datetime.fromisoformat(stamp.replace('Z', '+00:00'))).total_seconds()
    if elapsed(quote) > 60:
        reasons.append('quote_too_old')
    if elapsed(observed) > 300:
        reasons.append('portfolio_too_old')
    if at >= valid:
        reasons.append('quote_expired')
    if at >= port_valid:
        reasons.append('portfolio_expired')
    if any(x is None for x in pending):
        reasons.append('pending_orders_unknown')
    # The exit is a hypothetical mid; account for exit spread, two fees and two
    # slippage legs. Entry spread is already represented by buying ask/selling bid.
    friction = costs[0] + costs[1] + 2 * costs[2] + costs[3]
    long = {k: str((v - ask - friction) * quantity) for k, v in prices.items()}
    short = None if borrow is None else {k: str((bid - v - friction - borrow) * quantity)
                                        for k, v in prices.items()}
    reduction_blockers = []
    if not position or quantity > abs(position):
        reduction_blockers.append('would_cross_or_exceed_existing_position')
    if any(x != 0 for x in pending):
        reduction_blockers.append('pending_orders_not_clear')
    result = dict(version=VERSION, status='blocked' if reasons else 'sensitivity_only',
        blockers=reasons, listing_id=inputs['listing_id'], currency=inputs['currency'],
        price_change_since_reference_percent=reaction, reaction_is_causal_estimate=False,
        entry_bid=str(bid), entry_ask=str(ask), quantity=str(quantity),
        position_units=str(position), pending_buy_units=None if pending[0] is None else str(pending[0]),
        pending_sell_units=None if pending[1] is None else str(pending[1]),
        position_after_hypothetical_fill_excludes_pending_orders=True,
        long=dict(scenario_pnl=long, break_even_exit_mid=str(ask + friction),
                  resulting_units=str(position + quantity)),
        short=dict(scenario_pnl=short, break_even_exit_mid=None if borrow is None else str(bid-friction-borrow),
                   blockers=['borrow_cost_unknown'] if borrow is None else [],
                   resulting_units=str(position - quantity), borrow_availability_verified=False),
        reduce_existing=dict(blockers=reduction_blockers,
            side='sell' if position > 0 else 'buy' if position < 0 else None,
            resulting_units=None if reduction_blockers else str(position-quantity if position > 0 else position+quantity),
            incremental_pnl_vs_hold=None if reduction_blockers else {k: str(((bid-v) if position > 0 else (v-ask)) * quantity - (costs[0] + costs[2]) * quantity) for k,v in prices.items()},
            comparison_baseline='hold_marked_to_terminal_mid_without_liquidation',
            future_borrow_savings_assessed=False, risk_reduction_verified=False),
        hold=dict(incremental_trade_pnl='0', existing_position_risk_unchanged=True),
        scenario_prices_are_supplied_unvalidated_assumptions=True,
        scenario_exit_at=exit_times, probabilities_available=False, expected_return=None, recommended_action='abstain',
        abstention_reason='No validated forecast or portfolio risk approval; sensitivity is not an edge.',
        full_account_risk_assessed=False, orders_sent=0, live_trading=False, training_ready=False)
    return result


class EventOpportunityStore(EventAnalysisStore):
    def __init__(self, database, *, clock=None):
        super().__init__(database, clock=clock)
        self.db.executescript(SCHEMA)

    def _inputs(self, evidence_id, cutoff, current):
        binding = self._facility_evidence(evidence_id, cutoff, current)
        self._require_use(binding['source_id'], Use.STORAGE, current)
        raw = self.db.execute('SELECT payload FROM raw_objects WHERE sha256=?',
                              (binding['sha256'],)).fetchone()['payload']
        # Reject duplicate keys rather than allowing silent replacement.
        def pairs(items):
            obj = {}
            for k, v in items:
                if k in obj:
                    raise ContractError('Duplicate input JSON key')
                obj[k] = v
            return obj
        try:
            body = json.loads(raw, object_pairs_hook=pairs)
        except (ValueError, UnicodeError):
            raise ContractError('Invalid opportunity input JSON') from None
        return body, binding

    @_write_locked
    def assess(self, assessment_id, analysis_id, evidence_id, *, as_of):
        required(assessment_id, 'assessment_id')
        at, now = self._times(as_of)
        old = self.db.execute('SELECT * FROM event_opportunities WHERE assessment_id=?', (assessment_id,)).fetchone()
        if old:
            body = self.get_assessment(assessment_id, as_of=self._event_clock())
            if (body['analysis_id'], body['evidence_id'], body['as_of']) != (analysis_id, evidence_id, at):
                raise RecordConflict('Assessment ID already identifies different inputs')
            return body
        analysis = self.analysis_as_of(analysis_id, as_of=as_of)
        if analysis is None:
            raise ContractError('Analysis must be available at assessment cutoff')
        request = self.get_request(analysis['request_id'])
        inputs, binding = self._inputs(evidence_id, at, now)
        listing = self.db.execute('SELECT l.trading_currency,i.kind FROM listings l JOIN instruments i USING(instrument_id) WHERE listing_id=?',
                                  (inputs.get('listing_id'),)).fetchone() if isinstance(inputs, dict) else None
        if listing is None or listing['kind'] not in ('equity', 'etf') or inputs.get('currency') != listing['trading_currency']:
            raise ContractError('Explicit equity/ETF listing and matching currency required')
        with localcontext() as ctx:
            ctx.prec = 80
            result = calculate(inputs, analysis, request, at)
        completed = utc(self._event_clock())
        if completed < now:
            raise ContractError('Operational clock moved backwards')
        self._inputs(evidence_id, at, completed)
        self.analysis_as_of(analysis_id, as_of=as_of)
        body = dict(assessment_id=assessment_id, analysis_id=analysis_id, evidence_id=evidence_id,
            analysis_sha256=digest(analysis), evidence=binding, as_of=at, available_at=completed,
            result=result, engine_version=VERSION)
        self.db.execute('INSERT INTO event_opportunities VALUES (?,?,?,?)',
                         (assessment_id, completed, canonical(body), digest(body)))
        return body

    @_read_snapshot
    def get_assessment(self, assessment_id, *, as_of):
        at, current = self._times(as_of)
        row = self.db.execute('SELECT * FROM event_opportunities WHERE assessment_id=? AND available_at<=?',
                              (assessment_id, at)).fetchone()
        if row is None:
            return None
        body = json.loads(row['body_json'])
        if (digest(body) != row['sha256'] or body['assessment_id'] != assessment_id
                or body['available_at'] != row['available_at']):
            raise EvidenceIntegrityError('Opportunity manifest integrity failed')
        _, binding = self._inputs(body['evidence_id'], body['as_of'], current)
        analysis = self.analysis_as_of(body['analysis_id'], as_of=datetime.fromisoformat(body['as_of'].replace('Z', '+00:00')))
        if binding != body['evidence'] or analysis is None or digest(analysis) != body['analysis_sha256']:
            raise EvidenceIntegrityError('Opportunity dependency binding changed')
        return body
