"""Bounded supplied-scenario hedge search, not a forecast or order approval.

The position being protected and ONE new linear futures hedge are compared with
pro-rata reduction of the protected book. Scenario cash stress is a liquidity
constraint, never a second deduction of the same variation-margin price loss.
"""
from decimal import Decimal, localcontext

from .contracts import ContractError, required
from .event_opportunity import fields, instant, number

VERSION = 'scenario-hedge-search-1'
_ROUTE = ('broker', 'connection', 'account', 'environment')


def route_key(route):
    fields(route, _ROUTE)
    for key in _ROUTE:
        required(route[key], key)
    if route['environment'] not in {'paper', 'live'}:
        raise ContractError('Explicit paper/live hedge account required')
    return tuple(route[key] for key in _ROUTE)


def amount(value, *, positive=False):
    result = number(value, positive=positive)
    if result < 0:
        raise ContractError('A nonnegative amount is required')
    return result


def _currency(value):
    if not isinstance(value, str) or len(value) != 3 or not value.isascii() or not value.isupper() or not value.isalpha():
        raise ContractError('Explicit three-letter currency required')


def _validate(inputs, policy):
    fields(inputs, ('book', 'hedge_accounts', 'candidates', 'scenarios'))
    fields(policy, ('policy_id', 'version', 'max_contracts', 'max_gross_notional',
                    'max_hedge_notional_ratio', 'max_abs_residual_factor',
                    'max_worst_loss', 'min_loss_improvement', 'max_upside_sacrifice', 'cash_buffer',
                    'reduction_fractions', 'reduction_cost_full_book'))
    for key in ('policy_id', 'version'):
        required(policy[key], key)
    if type(policy['max_contracts']) is not int or not 0 <= policy['max_contracts'] <= 100:
        raise ContractError('max_contracts must be an integer from zero to 100')
    values = {key: amount(policy[key]) for key in ('max_gross_notional',
        'max_hedge_notional_ratio', 'max_abs_residual_factor', 'max_worst_loss',
        'min_loss_improvement', 'max_upside_sacrifice', 'cash_buffer', 'reduction_cost_full_book')}
    fractions = policy['reduction_fractions']
    if not isinstance(fractions, list) or not 1 <= len(fractions) <= 21:
        raise ContractError('One to 21 supplied reduction fractions required')
    fractions = [amount(value) for value in fractions]
    if any(value > 1 for value in fractions) or len(set(fractions)) != len(fractions):
        raise ContractError('Unique reduction fractions within zero and one required')
    if Decimal(0) not in fractions:
        raise ContractError('The unchanged zero reduction must be included')
    book = inputs['book']
    fields(book, ('book_id', 'route', 'currency', 'market_value', 'gross_notional',
                  'factor_exposure', 'risk_factor_id', 'pending_orders_known', 'pending_orders_clear', 'long_only'))
    required(book['book_id'], 'book_id')
    required(book['risk_factor_id'], 'risk_factor_id')
    book_route = route_key(book['route'])
    _currency(book['currency'])
    if any(type(book[key]) is not bool for key in ('pending_orders_known','pending_orders_clear','long_only')):
        raise ContractError('Explicit book scope and pending-order state required')
    if not book['pending_orders_known'] and book['pending_orders_clear']:
        raise ContractError('Unknown pending orders cannot be declared clear')
    market_value = amount(book['market_value'], positive=True)
    gross = amount(book['gross_notional'], positive=True)
    # Market value represents marked absolute protected capital, not cash NAV.
    if market_value > gross or (book['long_only'] and market_value != gross):
        raise ContractError('Protected marked capital/gross inconsistent with book scope')
    factor = number(book['factor_exposure'])
    accounts = inputs['hedge_accounts']
    if not isinstance(accounts, list) or len(accounts) > 20:
        raise ContractError('A bounded hedge-account list is required')
    cash = {}
    for account in accounts:
        fields(account, ('route', 'currency', 'available_cash'))
        _currency(account['currency'])
        key = (route_key(account['route']), account['currency'])
        if key in cash:
            raise ContractError('Ambiguous duplicate hedge account/currency')
        cash[key] = amount(account['available_cash'])
    candidates = inputs['candidates']
    if not isinstance(candidates, list) or len(candidates) > 10:
        raise ContractError('At most ten hedge alternatives are supported')
    prepared = {}
    for candidate in candidates:
        fields(candidate, ('candidate_id', 'contract_id', 'route', 'currency',
            'notional_per_contract', 'factor_per_contract', 'risk_factor_id', 'roundtrip_cost_per_contract',
            'initial_margin_per_contract', 'stressed_margin_per_contract'))
        identity = required(candidate['candidate_id'], 'candidate_id')
        required(candidate['contract_id'], 'contract_id')
        required(candidate['risk_factor_id'], 'risk_factor_id')
        if candidate['risk_factor_id'] != book['risk_factor_id']:
            raise ContractError('Book and hedge must use the same explicitly identified risk factor')
        if identity in prepared:
            raise ContractError('Candidate IDs must be unique')
        route = route_key(candidate['route'])
        _currency(candidate['currency'])
        if candidate['currency'] != book['currency']:
            raise ContractError('Cross-currency hedge arithmetic requires an implemented FX model')
        numeric = {key: amount(candidate[key], positive=key in {
            'notional_per_contract', 'factor_per_contract', 'initial_margin_per_contract',
            'stressed_margin_per_contract'}) for key in ('notional_per_contract',
            'factor_per_contract', 'roundtrip_cost_per_contract',
            'initial_margin_per_contract', 'stressed_margin_per_contract')}
        if numeric['stressed_margin_per_contract'] < numeric['initial_margin_per_contract']:
            raise ContractError('Stressed margin cannot be lower than initial margin')
        prepared[identity] = {**candidate, **numeric, 'route_key': route}
    scenarios = inputs['scenarios']
    if not isinstance(scenarios, list) or not 2 <= len(scenarios) <= 50:
        raise ContractError('Two to 50 aligned scenarios are required')
    ids = set()
    prepared_scenarios = []
    for scenario in scenarios:
        fields(scenario, ('scenario_id', 'horizon_at', 'portfolio_pnl', 'basis_break', 'hedges'))
        identity = required(scenario['scenario_id'], 'scenario_id')
        if identity in ids:
            raise ContractError('Scenario IDs must be unique')
        ids.add(identity)
        horizon = instant(scenario['horizon_at'])
        if type(scenario['basis_break']) is not bool:
            raise ContractError('Explicit basis-break scenario tag required')
        if not isinstance(scenario['hedges'], dict) or set(scenario['hedges']) != set(prepared):
            raise ContractError('Every scenario must align with all hedge candidates')
        hedge_values = {}
        for key, legs in scenario['hedges'].items():
            fields(legs, ('long_pnl_per_contract', 'long_adverse_cash_per_contract',
                          'short_adverse_cash_per_contract'))
            pnl = number(legs['long_pnl_per_contract'])
            long_cash = amount(legs['long_adverse_cash_per_contract'])
            short_cash = amount(legs['short_adverse_cash_per_contract'])
            if long_cash < max(Decimal(0), -pnl) or short_cash < max(Decimal(0), pnl):
                raise ContractError('Path cash stress cannot omit the terminal VM loss')
            hedge_values[key] = dict(pnl=pnl, long_cash=long_cash, short_cash=short_cash)
        prepared_scenarios.append(dict(scenario_id=identity, horizon_at=horizon,
            pnl=number(scenario['portfolio_pnl']), basis_break=scenario['basis_break'], hedges=hedge_values))
    if len({s['horizon_at'] for s in prepared_scenarios}) != 1:
        raise ContractError('Scenario comparison requires one common horizon')
    if not any(s['pnl'] < 0 for s in prepared_scenarios):
        raise ContractError('At least one downside scenario is required')
    return values, sorted(fractions), book, book_route, market_value, gross, factor, cash, prepared, prepared_scenarios


def search_hedges(inputs, policy):
    """Rank supplied-case loss reduction under an immutable caller-owned policy.

    Signed contracts denote a single new hedge: positive long, negative short.
    Rank is worst loss, then smaller cost, margin/cash and absolute size; supplied
    scenarios have no probability and do not establish real risk improvement.
    """
    with localcontext() as context:
        context.prec = 80
        return _search(inputs, policy)


def _search(inputs, policy):
    limits, fractions, book, book_route, value, gross, factor, cash, candidates, scenarios = _validate(inputs, policy)
    baseline_pnl = {s['scenario_id']: s['pnl'] for s in scenarios}
    baseline_loss = max(Decimal(0), -min(baseline_pnl.values()))
    alternatives = []

    def record(kind, identity, size, pnl, hedge_pnl, cost, required_cash, gross_after,
               factor_after, blockers, **extra):
        worst = max(Decimal(0), -min(pnl.values()))
        improvement = baseline_loss - worst
        if worst > limits['max_worst_loss']:
            blockers.append('worst_loss_limit')
        if abs(factor_after) > limits['max_abs_residual_factor']:
            blockers.append('residual_factor_target')
        if gross_after > limits['max_gross_notional']:
            blockers.append('gross_notional_limit')
        if kind != 'unhedged' and (improvement <= 0 or improvement < limits['min_loss_improvement']):
            blockers.append('insufficient_loss_improvement')
        upside_sacrifice = max([Decimal(0)] + [p-pnl[key] for key,p in baseline_pnl.items() if p>0])
        if upside_sacrifice > limits['max_upside_sacrifice']:
            blockers.append('upside_sacrifice_limit')
        body = dict(alternative_id=identity, kind=kind, size=str(size),
            feasible=not blockers, blockers=sorted(set(blockers)),
            scenario_pnl={k: str(v) for k, v in pnl.items()},
            protected_book_scenario_pnl={k: str(v) for k, v in baseline_pnl.items()},
            hedge_or_reduction_scenario_pnl={k: str(v) for k, v in hedge_pnl.items()},
            total_cost=str(cost), stressed_cash_required=str(required_cash),
            worst_loss=str(worst), worst_loss_improvement=str(improvement),
            max_upside_sacrifice=str(upside_sacrifice),
            gross_notional_after=str(gross_after), factor_exposure_after=str(factor_after),
            **extra)
        alternatives.append(body)
        return body

    baseline = record('unhedged', 'unhedged', Decimal(0), baseline_pnl,
        {k: Decimal(0) for k in baseline_pnl}, Decimal(0), Decimal(0), gross, factor, [])
    for fraction in fractions:
        if fraction == 0:
            continue
        cost = fraction * limits['reduction_cost_full_book']
        pnl = {key: (1-fraction)*p-cost for key, p in baseline_pnl.items()}
        delta = {key: pnl[key]-p for key, p in baseline_pnl.items()}
        blockers = [] if book['pending_orders_known'] else ['pending_orders_unknown']
        if not book['pending_orders_clear']:
            blockers.append('pending_orders_not_clear')
        if not book['long_only']:
            blockers.append('cash_reduction_long_only_scope_required')
        protected_cash = cash.get((book_route,book['currency']))
        if protected_cash is None:
            blockers.append('protected_account_cash_missing')
        elif cost > protected_cash:
            blockers.append('protected_account_cash_insufficient')
        record('reduce_book', 'reduce:' + str(fraction), fraction, pnl, delta,
            cost, cost, gross*(1-fraction), factor*(1-fraction), blockers,
            marked_notional_reduced=str(value*fraction), immediate_cash_proceeds_unassessed=True,
            cash_available=None if protected_cash is None else str(protected_cash), new_hedge_notional='0',
            instrument_reduce_only=False, reduction_is_pro_rata_whole_book=True,
            cost_basis='immediate_close_only_vs_hold_marked_to_terminal_mid')
    for identity in sorted(candidates):
        candidate = candidates[identity]
        for contracts in range(-policy['max_contracts'], policy['max_contracts']+1):
            if contracts == 0:
                continue
            q = Decimal(contracts)
            quantity = abs(q)
            cost = quantity*candidate['roundtrip_cost_per_contract']
            hedge = {s['scenario_id']: q*s['hedges'][identity]['pnl']-cost for s in scenarios}
            combined = {key: baseline_pnl[key]+p for key, p in hedge.items()}
            notional = quantity*candidate['notional_per_contract']
            factor_after = factor+q*candidate['factor_per_contract']
            adverse_cash = max(s['hedges'][identity]['long_cash' if contracts>0 else 'short_cash'] for s in scenarios)
            liquidity = quantity*(candidate['stressed_margin_per_contract']+adverse_cash)+cost+limits['cash_buffer']
            available = cash.get((candidate['route_key'], candidate['currency']))
            blockers = []
            if available is None:
                blockers.append('hedge_account_cash_missing')
            elif liquidity > available:
                blockers.append('hedge_account_cash_insufficient')
            if not book['pending_orders_known']:
                blockers.append('pending_orders_unknown')
            if not book['pending_orders_clear']:
                blockers.append('pending_orders_not_clear')
            if notional/gross > limits['max_hedge_notional_ratio']:
                blockers.append('hedge_ratio_limit')
            if abs(factor_after) >= abs(factor):
                blockers.append('factor_risk_not_reduced')
            if factor*factor_after < 0:
                blockers.append('factor_sign_reversal')
            joint_losses = [s['scenario_id'] for s in scenarios if s['pnl'] < 0 and
                q*s['hedges'][identity]['pnl'] < 0]
            if not any(s['basis_break'] and s['scenario_id'] in joint_losses for s in scenarios):
                blockers.append('simultaneous_loss_basis_stress_missing')
            record('futures_hedge', 'hedge:'+identity+':'+str(contracts), q, combined, hedge,
                cost, liquidity, gross+notional, factor_after, blockers,
                candidate_id=identity, contract_id=candidate['contract_id'],
                route=candidate['route'], cash_available=None if available is None else str(available),
                initial_margin=str(quantity*candidate['initial_margin_per_contract']),
                stressed_margin=str(quantity*candidate['stressed_margin_per_contract']),
                adverse_path_vm_cash=str(quantity*adverse_cash),
                new_hedge_notional=str(notional), simultaneous_loss_scenario_ids=joint_losses,
                instrument_reduce_only=False, cross_account_cash_pooled=False)
    def rank(alternative):
        return (Decimal(alternative['worst_loss']), Decimal(alternative['total_cost']),
                Decimal(alternative['stressed_cash_required']), abs(Decimal(alternative['size'])),
                alternative['alternative_id'])
    feasible = sorted((a for a in alternatives if a['feasible']), key=rank)
    hedges = sorted((a for a in feasible if a['kind']=='futures_hedge'), key=rank)
    return dict(version=VERSION, policy_id=policy['policy_id'], policy_version=policy['version'],
        status='research_comparison' if feasible else 'no_feasible_alternative',
        protected_book_id=book['book_id'], baseline=baseline, alternatives=alternatives,
        best_feasible_alternative_id=feasible[0]['alternative_id'] if feasible else None,
        best_feasible_hedge_id=hedges[0]['alternative_id'] if hedges else None,
        scenario_probabilities_available=False, expected_return=None,
        actual_risk_reduction_verified=False, available_cash_is_supplied=True,
        execution_approved=False, orders_sent=0, live_trading=False, training_ready=False,
        search_includes_at_most_one_new_hedge_instrument=True,
        vm_cash_is_liquidity_constraint_not_duplicate_pnl_charge=True)
