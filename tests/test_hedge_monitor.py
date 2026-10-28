"""Supplied hedge monitoring: partial/late fills, orphans, stops and expiry."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

from trading_intelligence.contracts import ContractError
from trading_intelligence.hedge_monitor import evaluate_hedge

T = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)


def supplied(**changes):
    result = dict(book_id='book-snapshot-v1', policy_id='hedge-policy-v1',
        protected_units='100', allocated_hedge_contracts=-1, target_contracts=-3,
        pending_state='clear', order_mode='active', observed_at=T.isoformat(),
        expires_at=(T + timedelta(minutes=5)).isoformat(),
        policy_expires_at=(T + timedelta(hours=1)).isoformat(),
        exit_rule='revalidate_then_unwind', min_rebalance_seconds=60,
        last_rebalance_at=None, rebalance_band=0)
    result.update(changes)
    return result


class HedgeMonitorTests(unittest.TestCase):
    def test_partial_filled_hedge_uses_allocated_quantity(self):
        x = evaluate_hedge(supplied(), now=T)
        self.assertEqual((x['state'], x['research_delta_contracts']), ('rebalance_review', -2))
        self.assertTrue(x['next_step_requires_revalidation'])
        self.assertFalse(x['order_submission_allowed'])
        self.assertEqual(x['orders_sent'], 0)

    def test_unknown_and_pending_status_never_duplicate_a_requested_hedge(self):
        for pending, state in [('unknown', 'reconcile'), ('pending', 'wait_for_pending')]:
            x = evaluate_hedge(supplied(pending_state=pending), now=T)
            self.assertEqual(x['state'], state)
            self.assertIsNone(x['research_delta_contracts'])

    def test_late_fill_is_a_new_snapshot_and_changes_only_remaining_delta(self):
        first = supplied(pending_state='unknown')
        old = deepcopy(first)
        self.assertEqual(evaluate_hedge(first, now=T)['state'], 'reconcile')
        later = T + timedelta(seconds=30)
        updated = {**first, 'pending_state':'clear', 'allocated_hedge_contracts':-2,
                   'observed_at':later.isoformat()}
        x = evaluate_hedge(updated, now=later)
        self.assertEqual(x['research_delta_contracts'], -1)
        self.assertEqual(first, old)

    def test_orphan_revalidates_unwind_and_does_not_become_an_independent_short(self):
        x = evaluate_hedge(supplied(protected_units='0'), now=T)
        self.assertEqual(x['state'], 'orphan_unwind_review')
        self.assertEqual(x['effective_target_contracts'], 0)
        self.assertEqual(x['research_delta_contracts'], 1)
        self.assertIn('hedge_without_protected_exposure', x['alerts'])

    def test_hard_stop_blocks_orphan_unwind_but_keeps_alert(self):
        x = evaluate_hedge(supplied(protected_units='0', order_mode='hard_stop'), now=T)
        self.assertEqual(x['state'], 'blocked_hard_stop')
        self.assertTrue(x['orphan_hedge'])
        self.assertTrue(x['hard_stop_active'])
        self.assertIsNone(x['research_delta_contracts'])

    def test_unknown_status_reconciles_during_stop_without_submission(self):
        x = evaluate_hedge(supplied(protected_units='0', order_mode='hard_stop', pending_state='unknown'), now=T)
        self.assertEqual(x['state'], 'reconcile')
        self.assertTrue(x['hard_stop_active'])
        self.assertTrue(x['orphan_hedge'])
        self.assertFalse(x['order_submission_allowed'])

    def test_pause_never_opens_a_new_hedge_under_reduce_only_label(self):
        x = evaluate_hedge(supplied(order_mode='paused'), now=T)
        self.assertEqual(x['state'], 'blocked_paused')
        self.assertIsNone(x['research_delta_contracts'])

    def test_expiry_and_stale_snapshot_request_review_not_an_automatic_exit(self):
        cases = [(supplied(policy_expires_at=T.isoformat()), 'review_expired_policy', T),
                 (supplied(), 'review_stale_snapshot', T + timedelta(minutes=5))]
        for snap, state, now in cases:
            x = evaluate_hedge(snap, now=now)
            self.assertEqual(x['state'], state)
            self.assertIsNone(x['research_delta_contracts'])

    def test_pending_stale_orphan_keeps_all_alerts(self):
        x = evaluate_hedge(supplied(protected_units='0', pending_state='pending',
            policy_expires_at=T.isoformat()), now=T + timedelta(minutes=5))
        self.assertEqual(x['state'], 'wait_for_pending')
        self.assertEqual(len(x['alerts']), 3)
        self.assertIsNone(x['research_delta_contracts'])

    def test_rebalance_band_and_minimum_wait_prevent_churn(self):
        x = evaluate_hedge(supplied(rebalance_band=2), now=T)
        self.assertEqual(x['state'], 'within_band')
        snap = supplied(last_rebalance_at=T.isoformat())
        self.assertEqual(evaluate_hedge(snap, now=T+timedelta(seconds=59))['state'], 'wait_rebalance_cooldown')
        self.assertEqual(evaluate_hedge(snap, now=T+timedelta(seconds=60))['state'], 'rebalance_review')

    def test_zero_book_without_hedge_ignores_stale_nonzero_target(self):
        x = evaluate_hedge(supplied(protected_units='0', allocated_hedge_contracts=0), now=T)
        self.assertEqual(x['state'], 'within_band')
        self.assertEqual(x['effective_target_contracts'], 0)

    def test_invalid_types_and_inconsistent_times_reject(self):
        cases = [dict(protected_units='NaN'), dict(protected_units='-1'), dict(protected_units=100),
            dict(allocated_hedge_contracts=True), dict(target_contracts=1.5),
            dict(rebalance_band=-1), dict(min_rebalance_seconds=True),
            dict(pending_state='guessed'), dict(order_mode='automatic'),
            dict(exit_rule='ignore'), dict(observed_at=(T+timedelta(seconds=1)).isoformat()),
            dict(expires_at=T.isoformat()), dict(observed_at='2026-01-01T12:00:00'),
            dict(last_rebalance_at=(T+timedelta(seconds=1)).isoformat())]
        for change in cases:
            with self.subTest(change=change), self.assertRaises(ContractError):
                evaluate_hedge(supplied(**change), now=T)
        with self.assertRaises(ContractError):
            evaluate_hedge({**supplied(), 'unexpected':True}, now=T)
        with self.assertRaises(ContractError):
            evaluate_hedge(supplied(), now=T.replace(tzinfo=None))
