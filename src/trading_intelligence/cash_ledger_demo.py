"""Synthetic cash journal walkthrough; no fill generation or dispatch."""
import json
from datetime import datetime, timezone
from pathlib import Path
from .cash_ledger import CashLedgerStore
from .contracts import ContractError


def cash_ledger_demo(directory):
    path = Path(directory) / 'cash-ledger.sqlite3'
    path.parent.mkdir(parents=True, exist_ok=True)
    clock = lambda: datetime(2026,1,2,tzinfo=timezone.utc)
    common = dict(occurred_at='2026-01-01T00:00:00Z',observed_at='2026-01-01T01:00:00Z',currency='USD',origin='synthetic_fixture',source_ref='synthetic:cash-ledger-demo')
    events = [dict(common,event_id='open',kind='opening_cash',amount='1000'),dict(common,event_id='buy',kind='buy',instrument_id='synthetic:listing',quantity='2',price='100',fee='1'),dict(common,event_id='split',kind='split',instrument_id='synthetic:listing',numerator='2',denominator='1'),dict(common,event_id='dividend',kind='dividend',instrument_id='synthetic:listing',amount='4')]
    store = CashLedgerStore(path,clock=clock)
    try:
        first = store.import_declared_report(json.dumps({'format':'offline-cash-events-v1','events':events}).encode())
    finally:
        store.close()
    store = CashLedgerStore(path,clock=clock)
    try:
        retry = store.import_declared_report(json.dumps({'format':'offline-cash-events-v1','events':events}).encode())
        failures = {}
        try:
            store.append_event({**events[1],'fee':'2'})
        except ContractError as exc:
            failures['immutable_duplicate'] = str(exc)
        try:
            store.reconcile(expected_currency='USD',expected_cash='999',expected_positions={'synthetic:listing':'4'},cash_tolerance='0',quantity_tolerance='0')
        except ContractError as exc:
            failures['reconciliation_mismatch'] = str(exc)
        return {'origin':'synthetic_fixture','state':store.state(),'restart_idempotent': [x['sha256'] for x in first] == [x['sha256'] for x in retry], 'reconciliation':store.reconcile(expected_currency='USD',expected_cash='803',expected_positions={'synthetic:listing':'4'},cash_tolerance='0',quantity_tolerance='0'),'expected_errors':failures,'orders_sent':0,'lean_executed':False,'broker_verified':False}
    finally:
        store.close()
