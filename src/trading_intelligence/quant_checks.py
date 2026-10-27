"""Offline research arithmetic; no pilot changes, fitting or order authority."""
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_FLOOR
from .contracts import ContractError, utc
from .futures import number


def risk_quantity(*, budget, stop_distance, multiplier, round_trip_cost, step):
    """Floor quantity so declared stop loss plus costs fits a monetary budget.

    Inputs must share one currency. Gaps can exceed the declared stop loss;
    this is not margin, liquidity or portfolio-risk approval.
    """
    for name, value in locals().copy().items():
        number(value, name, positive=name != 'round_trip_cost')
    if round_trip_cost < 0:
        raise ContractError('Costs cannot be negative')
    loss = stop_distance * multiplier + round_trip_cost
    return (budget / loss / step).to_integral_value(rounding=ROUND_FLOOR) * step


def hedge_ratio(portfolio_returns, hedge_returns):
    """Sample minimum-variance hedge ratio cov(P,H)/var(H), no sizing mandate.

    Caller supplies aligned same-period returns from a training-only snapshot.
    No intercept, causal claim, confidence interval or contract conversion.
    """
    p, h = tuple(portfolio_returns), tuple(hedge_returns)
    if len(p) != len(h) or len(p) < 3:
        raise ContractError('At least three aligned observations required')
    for value in p + h:
        number(value, 'return')
    pm, hm = sum(p) / len(p), sum(h) / len(h)
    variance = sum((x - hm) ** 2 for x in h)
    if variance == 0:
        raise ContractError('Zero hedge variance')
    return sum((x - pm) * (y - hm) for x, y in zip(p, h)) / variance


def eligible_training_indices(decisions, label_ends, label_available, *, test_start, gap):
    """Purge labels overlapping the test and exclude labels unavailable at fit.

    Inclusive label end requires strict separation. This is one fold's selector,
    not a complete experiment registry or replacement for final-test locking.
    """
    if not isinstance(gap, timedelta) or gap < timedelta(0):
        raise ContractError('Nonnegative time gap required')
    cutoff = datetime.fromisoformat(utc(test_start)) - gap
    d, e, a = tuple(decisions), tuple(label_ends), tuple(label_available)
    if not (len(d) == len(e) == len(a)):
        raise ContractError('Aligned label metadata required')
    result = []
    previous = None
    for i, (start, end, known) in enumerate(zip(d, e, a)):
        start, end, known = (datetime.fromisoformat(utc(x)) for x in (start, end, known))
        if end < start or known < end or (previous is not None and start < previous):
            raise ContractError('Invalid chronological label metadata')
        previous = start
        if start < cutoff and end < cutoff and known < cutoff:
            result.append(i)
    return tuple(result)
