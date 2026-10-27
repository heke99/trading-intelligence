"""Supplied synthetic execution-event audit. Never submits or invents fills."""
import json
import sqlite3
from decimal import Decimal
from .brokers import BrokerAccount, Environment
from .contracts import ContractError, required
from .futures import number


class ExecutionAudit:
    """Durable deduplication scoped to exact paper account and supplied order.

    Event IDs must identify executions (not repeated order-status callbacks).
    Late fills remain admissible after an unknown/cancel status. No automatic
    retry/failover decision or claim of external broker reconciliation.
    """
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS synthetic_execution_events '
                        '(route TEXT, order_id TEXT, event_id TEXT, payload TEXT, '
                        'PRIMARY KEY(route, order_id, event_id))')

    def close(self):
        self.db.close()

    def record(self, account, order_id, event_id, *, quantity, price, fee):
        if not isinstance(account, BrokerAccount) or account.environment != Environment.PAPER:
            raise ContractError('Exact paper account required')
        required(order_id, 'order_id')
        required(event_id, 'event_id')
        for name, value in (('quantity', quantity), ('price', price), ('fee', fee)):
            number(value, name, positive=name == 'quantity')
        if fee < 0:
            raise ContractError('Negative fee unsupported')
        # Decimal equality must survive alternate textual representations.
        payload = json.dumps([str(x.normalize()) for x in (quantity, price, fee)])
        with self.db:
            row = self.db.execute('SELECT payload FROM synthetic_execution_events '
                                  'WHERE route=? AND order_id=? AND event_id=?',
                                  (account.key, order_id, event_id)).fetchone()
            if row:
                if row[0] != payload:
                    raise ContractError('Conflicting execution ID; review required')
                return False
            self.db.execute('INSERT INTO synthetic_execution_events VALUES (?,?,?,?)',
                            (account.key, order_id, event_id, payload))
        return True

    def reconcile_quantity(self, account, order_id, *, expected_quantity):
        if not isinstance(account, BrokerAccount) or account.environment != Environment.PAPER:
            raise ContractError('Exact paper account required')
        required(order_id, 'order_id')
        number(expected_quantity, 'expected_quantity', positive=True)
        rows = self.db.execute('SELECT payload FROM synthetic_execution_events '
                               'WHERE route=? AND order_id=?', (account.key, order_id))
        filled = sum((Decimal(json.loads(row[0])[0]) for row in rows), Decimal(0))
        if filled > expected_quantity:
            raise ContractError('Overfill requires review')
        return dict(synthetic=True, filled=filled, remaining=expected_quantity - filled,
                    complete=filled == expected_quantity, resubmit_authorized=False)
