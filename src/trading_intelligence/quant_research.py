"""Optional numerical research diagnostics. No execution or promotion authority.

Original integration code; uses scikit-learn's BSD-licensed LedoitWolf API.
All input rows must be aligned equal-period simple returns in one base currency.
"""
import hashlib
import json
import math
import random
from datetime import datetime
from .contracts import ContractError, utc


def _series(values):
    result = tuple(values)
    if not result or any(type(x) not in (int, float) or not math.isfinite(x) for x in result):
        raise ContractError('Nonempty finite numeric observations required')
    return result


def risk_snapshot(returns, *, available_at, cutoff, asset_ids, weights):
    """Fit covariance only on rows known strictly before cutoff.

    Caller must pass training data, not an evaluation period. No annualization,
    leverage, margin or expected-return optimization is inferred.
    """
    import numpy as np
    import sklearn
    from sklearn.covariance import LedoitWolf
    rows = tuple(_series(row) for row in returns)
    ids, known, w = tuple(asset_ids), tuple(available_at), _series(weights)
    if (not ids or any(not isinstance(x, str) or not x.strip() for x in ids)
            or len(set(ids)) != len(ids) or len(w) != len(ids)
            or len(rows) != len(known) or any(len(row) != len(ids) for row in rows)):
        raise ContractError('Explicit aligned asset identities, rows and availability required')
    if any(x < 0 for x in w) or not math.isclose(sum(w), 1, abs_tol=1e-10):
        raise ContractError('This diagnostic supports fully invested long-only weights')
    times = tuple(datetime.fromisoformat(utc(x)) for x in known)
    boundary = datetime.fromisoformat(utc(cutoff))
    if any(a >= b for a, b in zip(times, times[1:])):
        raise ContractError('Strict chronological row availability required')
    selected = [row for row, time in zip(rows, times) if time < boundary]
    if len(selected) < max(3, len(ids) + 1):
        raise ContractError('Insufficient pre-cutoff observations')
    if any(x <= -1 for row in selected for x in row):
        raise ContractError('Simple returns must exceed minus one')
    data = np.asarray(selected, dtype=float)
    estimator = LedoitWolf().fit(data)
    covariance = estimator.covariance_
    weighted = covariance @ np.asarray(w)
    variance = float(np.dot(w, weighted))
    if not math.isfinite(variance) or variance <= 0:
        raise ContractError('Degenerate portfolio variance')
    volatility = math.sqrt(variance)
    contributions = [float(x * y / volatility) for x, y in zip(w, weighted)]
    payload = dict(asset_ids=ids, returns=selected, cutoff=utc(cutoff), weights=w,
                   selected_available_at=[utc(x) for x, time in zip(known, times) if time < boundary])
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return dict(research_only=True, observations=len(selected), input_sha256=digest,
                method='sklearn.LedoitWolf', sklearn_version=sklearn.__version__,
                numpy_version=np.__version__, shrinkage=float(estimator.shrinkage_),
                covariance=covariance.tolist(), period_volatility=volatility,
                component_volatility=contributions, promotion_authorized=False)


def paired_block_interval(candidate, benchmark, *, block_size, repetitions, seed, confidence):
    """Paired circular-block percentile interval for mean return difference.

    Not a p-value, SPA, DSR or a multiple-testing correction. Block length must
    be preregistered; stationarity and representative history are assumptions.
    """
    c, b = _series(candidate), _series(benchmark)
    n = len(c)
    if len(b) != n or n < 4:
        raise ContractError('At least four aligned periods required')
    if (type(block_size) is not int or not 1 <= block_size <= n // 2
            or type(repetitions) is not int or not 100 <= repetitions <= 100000
            or type(seed) is not int or type(confidence) not in (float, int)
            or not math.isfinite(confidence) or not 0 < confidence < 1
            or n * repetitions > 10000000):
        raise ContractError('Invalid or excessive bootstrap configuration')
    delta = [x - y for x, y in zip(c, b)]
    rng = random.Random(seed)
    means = []
    for _ in range(repetitions):
        sampled = []
        while len(sampled) < n:
            start = rng.randrange(n)
            sampled.extend(delta[(start + j) % n] for j in range(block_size))
        means.append(math.fsum(sampled[:n]) / n)
    means.sort()
    tail = (1 - confidence) / 2
    def quantile(p):
        position = (repetitions - 1) * p
        lo = math.floor(position)
        hi = math.ceil(position)
        return means[lo] + (means[hi] - means[lo]) * (position - lo)
    return dict(mean_difference=math.fsum(delta) / n, lower=quantile(tail), upper=quantile(1-tail),
                confidence=confidence, block_size=block_size, repetitions=repetitions, seed=seed,
                method='paired_circular_block_percentile', multiple_testing_corrected=False,
                promotion_authorized=False)


def cost_stress(gross_returns, turnover, *, cost_bps):
    """One-way traded notional/equity turnover × all-in cost per unit notional.

    Input returns are gross: passing already net returns double-counts costs.
    Costs are a sensitivity assumption, not a model of actual broker fills.
    """
    r, t = _series(gross_returns), _series(turnover)
    if len(r) != len(t) or any(x < 0 for x in t):
        raise ContractError('Aligned nonnegative turnover required')
    cost = _series([cost_bps])[0]
    if cost < 0:
        raise ContractError('Nonnegative cost required')
    net = tuple(x - y * cost / 10000 for x, y in zip(r, t))
    if any(x <= -1 for x in net):
        raise ContractError('Bankruptcy or unsupported gross return path')
    wealth = peak = 1.0
    drawdown = 0.0
    for x in net:
        wealth *= 1 + x
        if not math.isfinite(wealth):
            raise ContractError('Return path overflow')
        peak = max(peak, wealth)
        drawdown = max(drawdown, 1 - wealth / peak)
    return dict(net_returns=net, compounded_return=wealth-1, max_drawdown=drawdown,
                assumed_cost_bps=cost, promotion_authorized=False)


def superior_predictive_ability(benchmark_losses, model_losses, *, model_ids,
                                block_size, repetitions, seed):
    """Use arch's actual Hansen SPA implementation across ALL declared trials.

    Lower loss is better. Supply aligned out-of-sample losses for the complete
    attempted family, including failed candidates; do not omit trials after
    seeing outcomes. This function cannot audit completeness or authorize use
    of a final test. Finite-sample validity and block selection need review.
    """
    import arch
    import numpy as np
    from arch.bootstrap import SPA
    benchmark = _series(benchmark_losses)
    rows = tuple(_series(row) for row in model_losses)
    ids = tuple(model_ids)
    n = len(benchmark)
    if (n < 8 or len(rows) != n or not ids or len(set(ids)) != len(ids)
            or any(not isinstance(x, str) or not x.strip() for x in ids)
            or any(len(row) != len(ids) for row in rows)):
        raise ContractError('Aligned full-family losses and unique trial IDs required')
    if (type(block_size) is not int or not 1 <= block_size <= n//2
            or type(repetitions) is not int or not 100 <= repetitions <= 10000
            or type(seed) is not int or n * repetitions * len(ids) > 10000000):
        raise ContractError('Invalid or excessive SPA configuration')
    b, m = np.asarray(benchmark), np.asarray(rows)
    if np.any(np.var(b[:, None]-m, axis=0) <= 1e-24):
        raise ContractError('Degenerate loss differential; SPA unavailable')
    test = SPA(b, m, block_size=block_size, reps=repetitions,
               bootstrap='stationary', studentize=True, seed=seed)
    test.compute()
    pvalues = {str(k): float(v) for k, v in test.pvalues.items()}
    if any(not math.isfinite(x) or not 0 <= x <= 1 for x in pvalues.values()):
        raise ContractError('Invalid SPA result')
    return dict(method='arch.bootstrap.SPA', arch_version=arch.__version__,
                model_ids=ids, observations=n, pvalues=pvalues,
                block_size=block_size, repetitions=repetitions, seed=seed,
                family_completeness_verified=False, promotion_authorized=False)
