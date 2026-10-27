import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from trading_intelligence.brokers import BrokerAccount, Environment
from trading_intelligence.contracts import ContractError
from trading_intelligence.execution_checks import ExecutionAudit
from trading_intelligence.quant_checks import risk_quantity, hedge_ratio, eligible_training_indices


class Checks(unittest.TestCase):
    def test_risk_floor(self):
        args = dict(budget=D('100'), stop_distance=D('3'), multiplier=D('2'),
                    round_trip_cost=D('1'), step=D('1'))
        self.assertEqual(risk_quantity(**args), D('14'))
        with self.assertRaises(ContractError):
            risk_quantity(**{**args, 'round_trip_cost': D('-1')})
        with self.assertRaises(ContractError):
            risk_quantity(**{**args, 'budget': D('NaN')})

    def test_hedge(self):
        self.assertEqual(hedge_ratio(map(D, ['2', '4', '6']), map(D, ['1', '2', '3'])), D(2))
        with self.assertRaises(ContractError):
            hedge_ratio([D(1)] * 3, [D(1)] * 3)

    def test_purge_overlap_and_unavailable_labels(self):
        t = datetime(2026, 1, 1, tzinfo=timezone.utc)
        days = lambda ns: [t + timedelta(days=n) for n in ns]
        self.assertEqual(eligible_training_indices(days([0, 1, 2]), days([1, 4, 3]),
                         days([2, 4, 6]), test_start=days([5])[0], gap=timedelta(days=1)), (0,))

    def test_restart_duplicates_late_fill_and_routes(self):
        a = BrokerAccount('synthetic-a', 'connection', 'same', Environment.PAPER)
        b = BrokerAccount('synthetic-b', 'connection', 'same', Environment.PAPER)
        with tempfile.TemporaryDirectory() as tmp:
            path = tmp + '/events.db'
            audit = ExecutionAudit(path)
            fill = dict(quantity=D(2), price=D(100), fee=D(1))
            self.assertTrue(audit.record(a, 'o', 'e1', **fill))
            audit.close()
            audit = ExecutionAudit(path)
            self.assertFalse(audit.record(a, 'o', 'e1', **fill))
            with self.assertRaises(ContractError):
                audit.record(a, 'o', 'e1', **{**fill, 'quantity': D(3)})
            self.assertFalse(audit.reconcile_quantity(a, 'o', expected_quantity=D(4))['complete'])
            self.assertTrue(audit.record(b, 'o', 'e1', **fill))
            self.assertTrue(audit.record(a, 'o', 'late-e2', **fill))
            report = audit.reconcile_quantity(a, 'o', expected_quantity=D(4))
            self.assertTrue(report['complete'])
            self.assertFalse(report['resubmit_authorized'])
            with self.assertRaises(ContractError):
                audit.reconcile_quantity(a, 'o', expected_quantity=D(3))
            audit.close()
