"""Research-only monitoring of supplied hedge snapshots; no fill or order transport."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from .contracts import ContractError, required, utc

VERSION = 'hedge-monitor-1'
_FIELDS = {'book_id', 'policy_id', 'protected_units', 'allocated_hedge_contracts',
           'target_contracts', 'pending_state', 'order_mode', 'observed_at',
           'expires_at', 'policy_expires_at', 'exit_rule', 'min_rebalance_seconds',
           'last_rebalance_at', 'rebalance_band'}


def _instant(value):
    try:
        instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
        utc(instant)
        return instant.astimezone(timezone.utc)
    except (TypeError, AttributeError, ValueError, OverflowError):
        raise ContractError('A timezone-aware snapshot timestamp is required') from None


def _integer(value, name, *, nonnegative=False):
    if type(value) is not int or abs(value) > 1_000_000 or (nonnegative and value < 0):
        raise ContractError(name + ' must be a bounded whole integer')
    return value


def evaluate_hedge(snapshot, *, now):
    """Suggest review states from supplied reconciled quantities, never orders.

    None last_rebalance_at means the supplier asserts no previous rebalance.
    IDs identify immutable book/policy versions supplied by the caller. A changed
    snapshot is evaluated afresh: earlier requested quantities never become fills.
    """
    utc(now)
    if not isinstance(snapshot, dict) or set(snapshot) != _FIELDS:
        raise ContractError('Exact supplied hedge-monitor snapshot fields required')
    for key in ('book_id', 'policy_id'):
        required(snapshot[key], key)
    value = snapshot['protected_units']
    if not isinstance(value, str) or len(value) > 60:
        raise ContractError('Protected units must be a bounded decimal string')
    try:
        units = Decimal(value)
    except InvalidOperation:
        raise ContractError('Invalid protected units') from None
    if (not units.is_finite() or units < 0 or units > Decimal('1e15')
            or units.as_tuple().exponent < -12):
        raise ContractError('Protected units must be finite, nonnegative and bounded')
    allocated = _integer(snapshot['allocated_hedge_contracts'], 'allocated contracts')
    target = _integer(snapshot['target_contracts'], 'target contracts')
    band = _integer(snapshot['rebalance_band'], 'rebalance band', nonnegative=True)
    cooldown = _integer(snapshot['min_rebalance_seconds'], 'rebalance wait', nonnegative=True)
    for key, allowed in (('pending_state', ('clear', 'pending', 'unknown')),
                         ('order_mode', ('active', 'paused', 'hard_stop'))):
        if snapshot[key] not in allowed:
            raise ContractError('Unknown ' + key)
    if snapshot['exit_rule'] != 'revalidate_then_unwind':
        raise ContractError('An explicit revalidation/unwind rule is required')
    observed, expires, policy_expires = (_instant(snapshot[key]) for key in
                                        ('observed_at', 'expires_at', 'policy_expires_at'))
    last = None if snapshot['last_rebalance_at'] is None else _instant(snapshot['last_rebalance_at'])
    if observed > now or expires <= observed or (last is not None and last > observed):
        raise ContractError('Snapshot/rebalance times are inconsistent')
    stale, policy_expired = now >= expires, now >= policy_expires
    orphan = units == 0 and allocated != 0
    effective_target = 0 if units == 0 else target
    difference = effective_target - allocated
    alerts = []
    if orphan:
        alerts.append('hedge_without_protected_exposure')
    if stale:
        alerts.append('snapshot_stale')
    if policy_expired:
        alerts.append('policy_expired')
    delta = None
    # Unknown external status always needs reconciliation, even under a stop.
    # The hard-stop flag below remains explicit and cannot be bypassed by this.
    if snapshot['pending_state'] == 'unknown':
        state = 'reconcile'
    elif snapshot['pending_state'] == 'pending':
        state = 'wait_for_pending'
    elif snapshot['order_mode'] == 'hard_stop':
        state = 'blocked_hard_stop'
    elif stale:
        state = 'review_stale_snapshot'
    elif policy_expired:
        state = 'review_expired_policy'
    elif snapshot['order_mode'] == 'paused':
        state = 'blocked_paused'
    elif orphan:
        state, delta = 'orphan_unwind_review', difference
    elif abs(difference) <= band:
        state = 'within_band'
    elif last is not None and (now - last).total_seconds() < cooldown:
        state = 'wait_rebalance_cooldown'
    else:
        state, delta = 'rebalance_review', difference
    return dict(version=VERSION, book_id=snapshot['book_id'], policy_id=snapshot['policy_id'],
        evaluated_at=utc(now), state=state, alerts=alerts, protected_units=str(units),
        allocated_hedge_contracts=allocated, declared_target_contracts=target,
        effective_target_contracts=effective_target, research_delta_contracts=delta,
        snapshot_stale=stale, policy_expired=policy_expired,
        hard_stop_active=snapshot['order_mode'] == 'hard_stop',
        orphan_hedge=orphan, exit_rule=snapshot['exit_rule'],
        next_step_requires_revalidation=delta is not None,
        is_supplied_snapshot=True, reconciled_broker_fills_verified=False,
        order_submission_allowed=False, orders_sent=0, live_trading=False)
