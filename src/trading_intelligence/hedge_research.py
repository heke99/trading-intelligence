"""Evidence-bound hedge comparison. No verified account state or order authority."""
from datetime import datetime
from functools import wraps
from decimal import Decimal, localcontext
import json

from .contracts import ContractError, EvidenceIntegrityError, RecordConflict, Use, utc, required
from .event_analysis import canonical, digest, _write_locked, _read_snapshot
from .event_opportunity import EventOpportunityStore, fields, instant, number
from .futures import Settlement, Session, TradingSchedule
from .futures_store import FuturesStore
from .references import _key, _time
from .hedge_math import search_hedges

VERSION = 'hedge-research-1'
SCHEMA = '''CREATE TABLE IF NOT EXISTS hedge_research (
 search_id TEXT PRIMARY KEY, available_at TEXT NOT NULL,
 body_json TEXT NOT NULL, sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS hedge_monitor_runs (
 monitor_id TEXT PRIMARY KEY, available_at TEXT NOT NULL,
 body_json TEXT NOT NULL, sha256 TEXT NOT NULL);'''


def _precision(method):
    @wraps(method)
    def call(*args, **kwargs):
        with localcontext() as context:
            context.prec = 128
            return method(*args, **kwargs)
    return call


def _dt(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


class HedgeResearchStore(EventOpportunityStore, FuturesStore):
    def __init__(self, database, *, clock=None):
        super().__init__(database, clock=clock)
        self.db.executescript(SCHEMA)

    def _reference_binding(self, snapshot_id, at, current):
        row = self.db.execute('SELECT * FROM futures_snapshots WHERE snapshot_id=?', (snapshot_id,)).fetchone()
        if row is None or row['known_at'] > at:
            raise EvidenceIntegrityError('Futures reference is missing or unavailable')
        binding = self._facility_evidence(row['evidence_id'], at, current)
        self._require_use(binding['source_id'], Use.STORAGE, current)
        return dict(snapshot_id=snapshot_id, manifest_sha256=digest(dict(row)), evidence=binding)

    @_precision
    def _validate(self, opportunity_id, evidence_id, at, current):
        opportunity = self.get_assessment(opportunity_id, as_of=_dt(at))
        if opportunity is None:
            raise ContractError('An available event opportunity assessment is required')
        raw, binding = self._inputs(evidence_id, at, current)
        fields(raw, ('inputs', 'policy', 'controls', 'market_references'))
        inputs, policy, controls = raw['inputs'], raw['policy'], raw['controls']
        # Validate bounded primitive schema before indexing any supplied structures.
        result = search_hedges(inputs, policy)
        fields(controls, ('state_observed_at', 'valid_until', 'policy_known_at', 'order_mode',
                          'hedge_mandate', 'min_rebalance_seconds', 'rebalance_band',
                          'exit_rule', 'protected_listing_ids', 'holdings',
                          'hedge_positions', 'hedge_pending_state'))
        if (controls['order_mode'] not in ('active', 'paused', 'hard_stop')
                or type(controls['hedge_mandate']) is not bool
                or controls['exit_rule'] != 'revalidate_then_unwind'
                or type(controls['min_rebalance_seconds']) is not int
                or not 0 <= controls['min_rebalance_seconds'] <= 86400
                or type(controls['rebalance_band']) is not int
                or not 0 <= controls['rebalance_band'] <= 100):
            raise ContractError('Explicit bounded hedge controls required')
        observed, expiry = instant(controls['state_observed_at']), instant(controls['valid_until'])
        if instant(controls['policy_known_at']) > at or observed > at or expiry <= observed:
            raise ContractError('Hedge policy/state timestamps are inconsistent')
        listing_ids = controls['protected_listing_ids']
        if (not isinstance(listing_ids, list) or not listing_ids or len(listing_ids) > 50
                or any(not isinstance(x,str) for x in listing_ids) or len(set(listing_ids)) != len(listing_ids)
                or opportunity['result']['listing_id'] not in listing_ids):
            raise ContractError('Protected book must include the linked canonical event listing')
        book = inputs['book']
        for identity in listing_ids:
            row = self.db.execute('SELECT l.trading_currency,i.kind FROM listings l JOIN instruments i USING(instrument_id) WHERE listing_id=?', (identity,)).fetchone()
            if row is None or row['kind'] not in ('equity','etf') or row['trading_currency'] != book['currency']:
                raise ContractError('Protected book requires known same-currency equity/ETF listings')
        original_inputs, _ = self._inputs(opportunity['evidence_id'], opportunity['as_of'], current)
        expected_route = {key: original_inputs['portfolio'][key] for key in ('broker','connection','account','environment')}
        if book['route'] != expected_route:
            raise ContractError('Protected book route must match linked exposure evidence')
        if number(original_inputs['portfolio']['position_units']) == 0:
            raise ContractError('A zero protected holding cannot seed a hedge')
        if (_dt(at)-_dt(instant(original_inputs['quote_at']))).total_seconds() > 60:
            raise ContractError('Linked exposure quote is stale at hedge cutoff')
        holdings = controls['holdings']
        if not isinstance(holdings,list) or len(holdings) != len(listing_ids):
            raise ContractError('Exact protected holding allocations required')
        marked, factor, seen, all_long = Decimal(0), Decimal(0), set(), True
        for holding in holdings:
            fields(holding, ('listing_id','units','mid','factor_loading'))
            identity = holding['listing_id']
            if identity not in listing_ids or identity in seen:
                raise ContractError('Holding allocations must match protected listings exactly')
            seen.add(identity)
            units, mid = number(holding['units']), number(holding['mid'],positive=True)
            marked += units.copy_abs()*mid
            factor += units*mid*number(holding['factor_loading'])
            all_long = all_long and units >= 0
            if identity == opportunity['result']['listing_id']:
                expected_mid = (number(original_inputs['bid'])+number(original_inputs['ask']))/2
                if units != number(original_inputs['portfolio']['position_units']) or mid != expected_mid:
                    raise ContractError('Linked holding quantity/mark differs from original exposure evidence')
        if (marked != number(book['market_value']) or marked != number(book['gross_notional'])
                or factor != number(book['factor_exposure']) or all_long != book['long_only']):
            raise ContractError('Protected marked capital/factor must reconcile to supplied holding allocations')
        horizons = {instant(s['horizon_at']) for s in inputs['scenarios']}
        if len(horizons) != 1 or next(iter(horizons)) <= at:
            raise ContractError('Comparable scenarios require one explicit future horizon')
        horizon = next(iter(horizons))
        candidates, refs = inputs['candidates'], raw['market_references']
        if not isinstance(refs,dict) or set(refs) != {c['candidate_id'] for c in candidates}:
            raise ContractError('Market references must match candidate IDs exactly')
        positions, pending = controls['hedge_positions'], controls['hedge_pending_state']
        if (not isinstance(positions,dict) or not isinstance(pending,dict)
                or set(positions) != set(refs) or set(pending) != set(refs)
                or any(type(x) is not int or abs(x)>1000000 for x in positions.values())
                or any(x not in ('clear','pending','unknown') for x in pending.values())):
            raise ContractError('Explicit per-candidate filled position and pending state required')
        bindings, processing_blockers = [], []
        for candidate in candidates:
            ref = refs[candidate['candidate_id']]
            fields(ref, ('broker_identifier','entry_price','price_kind','observed_at','valid_until','exit_prices'))
            quote = instant(ref['observed_at'])
            if quote > at or instant(ref['valid_until']) <= at or (_dt(at)-_dt(quote)).total_seconds() > 60 or abs((_dt(quote)-_dt(observed)).total_seconds()) > 30 or abs((_dt(quote)-_dt(instant(original_inputs['quote_at']))).total_seconds()) > 30:
                raise ContractError('Fresh synchronized raw futures quote required')
            if ref['price_kind'] != 'raw_contract':
                raise ContractError('Continuous/adjusted prices cannot size a hedge')
            contract_id, route = candidate['contract_id'], candidate['route']
            contract = self._contract(contract_id)
            product = self.db.execute('SELECT p.*,i.kind AS underlying_kind FROM future_products p JOIN instruments i ON i.instrument_id=p.underlying_instrument_id WHERE product_id=?',(contract['product_id'],)).fetchone()
            if product is None or product['underlying_kind']!='index':
                raise ContractError('First hedge research slice requires index futures')
            bindings.append(dict(contract_identity=dict(contract),product_identity=dict(product)))
            when = dict(effective_at=_dt(at), as_of=_dt(at))
            terms, terms_id = self.terms_as_of(contract_id, **when)
            if terms.settlement != Settlement.CASH or at >= utc(terms.entry_cutoff_at) or horizon >= utc(terms.last_trade_at):
                raise ContractError('Cash-settled unexpired contract covering horizon required; rolling not implemented')
            if (current >= instant(ref['valid_until']) or (_dt(current)-_dt(quote)).total_seconds()>60
                    or current >= utc(terms.entry_cutoff_at)):
                processing_blockers.append('futures_quote_or_entry_window_expired_at_processing')
            price = number(ref['entry_price'], positive=True)
            terms.check_price(price)
            if candidate['currency'] != contract['quote_currency'] or candidate['currency'] != book['currency']:
                raise ContractError('FX hedges/cross-currency funding are not implemented')
            binding_ref = self._get('binding',_key(route['broker'],ref['broker_identifier']),**when)
            if binding_ref.body['contract_id'] != contract_id:
                raise ContractError('Broker identifier resolves to another expiry')
            schedule_ref = self._get('schedule',contract['product_id'],**when)
            schedule = TradingSchedule(schedule_ref.body['timezone'],tuple(Session(_time(s['opens_at']),_time(s['closes_at'])) for s in schedule_ref.body['sessions']))
            if not schedule.is_open(_dt(at)):
                raise ContractError('Futures session is closed')
            margin_ref = self._get('margin',_key(route['broker'],route['account'],contract_id),**when)
            if number(candidate['notional_per_contract']) != price * terms.multiplier or number(candidate['initial_margin_per_contract']) != Decimal(margin_ref.body['initial']) or margin_ref.body['currency'] != candidate['currency']:
                raise ContractError('Candidate notional/margin disagrees with canonical references')
            exits = ref['exit_prices']
            if not isinstance(exits,dict) or set(exits) != {s['scenario_id'] for s in inputs['scenarios']}:
                raise ContractError('Each stress case needs an explicit raw exit price')
            for scenario in inputs['scenarios']:
                exit_price = number(exits[scenario['scenario_id']], positive=True)
                if number(scenario['hedges'][candidate['candidate_id']]['long_pnl_per_contract']) != terms.gross_pnl(price,exit_price,1):
                    raise ContractError('Stress PnL disagrees with expiry tick/multiplier arithmetic')
            for snapshot in (terms_id,binding_ref.snapshot_id,schedule_ref.snapshot_id,margin_ref.snapshot_id):
                bindings.append(self._reference_binding(snapshot,at,current))
        blockers = list(processing_blockers)
        if (current >= instant(original_inputs['valid_until'])
                or current >= instant(original_inputs['portfolio']['valid_until'])):
            blockers.append('linked_exposure_expired_at_processing')
        analysis=self.analysis_as_of(opportunity['analysis_id'],as_of=_dt(at))
        if current>=analysis['expires_at']:blockers.append('linked_analysis_expired_at_processing')
        if any(positions.values()): blockers.append('existing_hedge_requires_updated_sizing')
        if any(value != 'clear' for value in pending.values()): blockers.append('hedge_pending_requires_reconciliation')
        if opportunity['result']['status'] != 'sensitivity_only': blockers.append('linked_opportunity_blocked')
        if (_dt(at)-_dt(observed)).total_seconds() > 60 or at >= expiry: blockers.append('state_or_policy_stale')
        if controls['order_mode'] != 'active': blockers.append('order_mode_blocks_new_hedge')
        if not controls['hedge_mandate']: blockers.append('hedge_mandate_missing')
        if current >= expiry: blockers.append('expired_at_processing')
        return raw, binding, opportunity, bindings, blockers, result

    @_write_locked
    def search(self, search_id, opportunity_id, evidence_id, *, as_of):
        required(search_id,'search_id')
        at, now = self._times(as_of)
        old = self.db.execute('SELECT * FROM hedge_research WHERE search_id=?',(search_id,)).fetchone()
        if old:
            body = self.get_search(search_id,as_of=self._event_clock())
            if (body['opportunity_id'],body['evidence_id'],body['as_of']) != (opportunity_id,evidence_id,at):
                raise RecordConflict('Hedge search ID already identifies different immutable inputs')
            return body
        with localcontext() as context:
            context.prec = 128
            raw, binding, opportunity, refs, blockers, result = self._validate(opportunity_id,evidence_id,at,now)
        completed = utc(self._event_clock())
        if completed < now: raise ContractError('Operational clock moved backwards')
        _,_,_,_,final_blockers,_ = self._validate(opportunity_id,evidence_id,at,completed)
        blockers = sorted(set(blockers+final_blockers))
        body = dict(search_id=search_id,opportunity_id=opportunity_id,evidence_id=evidence_id,
            as_of=at,available_at=completed,evidence=binding,opportunity_sha256=digest(opportunity),
            futures_references=refs,result=result,operational_blockers=blockers,
            policy_controls=raw['controls'],version=VERSION,
            reviewable_hedge_id=None if blockers else result['best_feasible_hedge_id'],supplied_state_verified=False,
            full_route_eligibility_verified=False,execution_authorized=False,
            orders_sent=0,live_trading=False,training_ready=False)
        self.db.execute('INSERT INTO hedge_research VALUES (?,?,?,?)',(search_id,completed,canonical(body),digest(body)))
        return body

    @_read_snapshot
    def get_search(self, search_id, *, as_of):
        at,current = self._times(as_of)
        row = self.db.execute('SELECT * FROM hedge_research WHERE search_id=? AND available_at<=?',(search_id,at)).fetchone()
        if row is None:return None
        body = json.loads(row['body_json'])
        if digest(body) != row['sha256'] or body['search_id'] != search_id or body['available_at'] != row['available_at']:
            raise EvidenceIntegrityError('Hedge research manifest integrity failed')
        with localcontext() as context:
            context.prec=128
            _,binding,opportunity,refs,_,_ = self._validate(body['opportunity_id'],body['evidence_id'],body['as_of'],current)
        if binding != body['evidence'] or digest(opportunity) != body['opportunity_sha256'] or refs != body['futures_references']:
            raise EvidenceIntegrityError('Hedge research dependencies changed')
        return body

    @_write_locked
    def monitor(self, monitor_id, search_id, evidence_id, *, as_of):
        from .hedge_monitor import evaluate_hedge
        required(monitor_id,'monitor_id')
        at, current = self._times(as_of)
        old = self.db.execute('SELECT * FROM hedge_monitor_runs WHERE monitor_id=?',(monitor_id,)).fetchone()
        if old:
            body = self.get_monitor(monitor_id,as_of=self._event_clock())
            if (body['search_id'],body['evidence_id'],body['as_of']) != (search_id,evidence_id,at):
                raise RecordConflict('Monitor ID already identifies another snapshot')
            return body
        search = self.get_search(search_id,as_of=as_of)
        if search is None: raise ContractError('Available hedge search required')
        raw,binding = self._inputs(evidence_id,at,current)
        fields(raw,('snapshot','route','alternative_id','policy_version'))
        alternatives = [x for x in search['result']['alternatives'] if x['alternative_id']==raw['alternative_id']]
        if len(alternatives)!=1 or alternatives[0]['kind']!='futures_hedge' or not alternatives[0]['feasible']:
            raise ContractError('A feasible linked futures research alternative required')
        alternative=alternatives[0]
        if raw['route'] != alternative['route'] or raw['policy_version'] != search['result']['policy_version']:
            raise ContractError('Monitor route/policy version differs from linked search')
        snapshot=raw['snapshot']
        if len(search['policy_controls']['holdings'])!=1:
            raise ContractError('First monitor slice requires one protected listing; re-search multi-asset books')
        result=evaluate_hedge(snapshot,now=as_of)
        if (snapshot['book_id'] != search['result']['protected_book_id']
                or snapshot['policy_id'] != search['result']['policy_id']
                or snapshot['target_contracts'] != int(alternative['size'])):
            raise ContractError('Monitor book/policy/target differs from linked alternative')
        controls=search['policy_controls']
        original_units=number(controls['holdings'][0]['units']).copy_abs()
        protected=number(snapshot['protected_units'])
        if protected!=0 and protected!=original_units:
            result['alerts'].append('protected_exposure_changed_requires_new_search')
            result['research_delta_contracts']=None
            result['next_step_requires_revalidation']=False
            if result['state'] in ('rebalance_review','within_band','wait_rebalance_cooldown'):
                result['state']='review_changed_protected_exposure'
        for key in ('min_rebalance_seconds','rebalance_band','exit_rule'):
            if snapshot[key] != controls[key]: raise ContractError('Monitor cannot rewrite frozen rebalance/exit policy')
        if instant(snapshot['policy_expires_at']) != instant(controls['valid_until']):
            raise ContractError('Monitor cannot extend frozen policy validity')
        if ((controls['order_mode']!='active' and snapshot['order_mode']=='active')
                or not controls['hedge_mandate']):
            result['research_delta_contracts']=None
            result['alerts'].append('linked_policy_blocks_hedge_actions')
            if result['state'] not in ('reconcile','wait_for_pending','blocked_hard_stop'):
                result['state']='blocked_by_linked_policy'
            result['next_step_requires_revalidation']=False
        completed=utc(self._event_clock())
        if completed<current:raise ContractError('Operational clock moved backwards')
        self._inputs(evidence_id,at,completed)
        self.get_search(search_id,as_of=as_of)
        expired = completed >= min(instant(snapshot['expires_at']),instant(snapshot['policy_expires_at']))
        if expired:
            result['research_delta_contracts']=None
            result['next_step_requires_revalidation']=False
            result['alerts'].append('policy_or_snapshot_expired_during_processing')
            if result['state'] in ('rebalance_review','orphan_unwind_review'):
                result['state']='review_expired_on_arrival'
        body=dict(monitor_id=monitor_id,search_id=search_id,evidence_id=evidence_id,as_of=at,
            available_at=completed,search_sha256=digest(search),evidence=binding,result=result,
            expired_on_arrival=expired,orders_sent=0,live_trading=False)
        self.db.execute('INSERT INTO hedge_monitor_runs VALUES (?,?,?,?)',(monitor_id,completed,canonical(body),digest(body)))
        return body

    @_read_snapshot
    def get_monitor(self, monitor_id, *, as_of):
        at,current=self._times(as_of)
        row=self.db.execute('SELECT * FROM hedge_monitor_runs WHERE monitor_id=? AND available_at<=?',(monitor_id,at)).fetchone()
        if row is None:return None
        body=json.loads(row['body_json'])
        if digest(body)!=row['sha256'] or body['monitor_id']!=monitor_id or body['available_at']!=row['available_at']:
            raise EvidenceIntegrityError('Hedge monitor manifest integrity failed')
        _,binding=self._inputs(body['evidence_id'],body['as_of'],current)
        search=self.get_search(body['search_id'],as_of=_dt(body['as_of']))
        if binding!=body['evidence'] or search is None or digest(search)!=body['search_sha256']:
            raise EvidenceIntegrityError('Hedge monitor dependency binding changed')
        return body
