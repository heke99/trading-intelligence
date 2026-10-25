import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trading_intelligence.cash_ledger import CashLedgerStore
from trading_intelligence.contracts import ContractError, RecordConflict, EvidenceIntegrityError

NOW = datetime(2026,1,2,tzinfo=timezone.utc)

def event(identity, kind, **fields):
    return dict(event_id=identity,kind=kind,occurred_at='2026-01-01T00:00:00Z',observed_at='2026-01-01T01:00:00Z',currency='USD',origin='synthetic_fixture',source_ref='fixture:explicit',**fields)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.path = Path(self.temp.name)/'cash.sqlite3'
        self.store = CashLedgerStore(self.path,clock=lambda:NOW)
        self.opening = event('open','opening_cash',amount='1000')
        self.store.append_event(self.opening)
    def tearDown(self):
        self.store.close(); self.temp.cleanup()
    def buy(self):
        return event('buy','buy',instrument_id='listing:A',quantity='2',price='100',fee='1')
    def test_restart_idempotence_and_conflict(self):
        first = self.store.append_event(self.buy()); self.store.close()
        self.store = CashLedgerStore(self.path,clock=lambda:NOW)
        self.assertEqual(first['sha256'], self.store.append_event(self.buy())['sha256'])
        self.assertEqual(self.store.state()['cash'],'799')
        with self.assertRaises(RecordConflict): self.store.append_event({**self.buy(),'fee':'2'})
    def test_fee_dividend_split_sell(self):
        self.store.append_event(self.buy())
        self.store.append_event(event('split','split',instrument_id='listing:A',numerator='2',denominator='1'))
        self.store.append_event(event('div','dividend',instrument_id='listing:A',amount='4'))
        self.store.append_event(event('sell','sell',instrument_id='listing:A',quantity='1',price='60',fee='1'))
        self.assertEqual(self.store.state()['cash'],'862')
        self.assertTrue(self.store.reconcile(expected_currency='USD',expected_cash='862',expected_positions={'listing:A':'3'},cash_tolerance='0',quantity_tolerance='0')['matches'])
    def test_reconciliation_failure_and_explicit_tolerance(self):
        with self.assertRaises(ContractError): self.store.reconcile(expected_currency='USD',expected_cash='999',expected_positions={},cash_tolerance='0',quantity_tolerance='0')
        self.assertTrue(self.store.reconcile(expected_currency='USD',expected_cash='999',expected_positions={},cash_tolerance='1',quantity_tolerance='0')['matches'])
    def test_no_short_or_negative_cash(self):
        for value in (event('short','sell',instrument_id='A',quantity='1',price='1',fee='0'),{**self.buy(),'quantity':'20'}):
            with self.assertRaises(ContractError): self.store.append_event(value)
        self.assertEqual(self.store.state()['event_count'],1)
    def test_strict_decimal(self):
        for value in (1,1.0,'NaN','Infinity','-1','1e100','0.0000000000000000001','1_0',' 1','+1','01','1e1'):
            with self.assertRaises(ContractError): self.store.append_event({**self.buy(),'fee':value})
    def test_origin_currency_and_corrections_rejected(self):
        for extra in ({'origin':'broker_verified'},{'origin':'externally_supplied_simulation'},{'currency':'EUR'},{'correction_of':'open'},{'kind':'correction'}):
            with self.assertRaises(ContractError): self.store.append_event({**self.buy(),**extra})
    def test_chronological_and_observation_bounds(self):
        for extra in ({'occurred_at':'2025-12-01T00:00:00Z','observed_at':'2025-12-02T00:00:00Z'}, {'observed_at':'2027-01-01T00:00:00Z'}, {'occurred_at':'2026-01-02T00:00:00Z'}, {'observed_at':'2026-01-01T00:00:00'}):
            with self.assertRaises((ContractError,ValueError)): self.store.append_event({**self.buy(),**extra})
    def test_asof_registration_not_backdated(self):
        self.assertEqual(self.store.state(as_of=NOW-timedelta(hours=1))['event_count'],0)
    def test_report_atomic_and_duplicate_json(self):
        bad = {**self.buy(),'quantity':'100'}
        with self.assertRaises(ContractError): self.store.import_declared_report(json.dumps({'format':'offline-cash-events-v1','events':[self.buy(),{**bad,'event_id':'bad'}]}).encode())
        self.assertEqual(self.store.state()['event_count'],1)
        with self.assertRaises(ContractError): self.store.import_declared_report(b'{"format":"x","format":"offline-cash-events-v1","events":[]}')
    def test_import_declared_only(self):
        payload = json.dumps({'format':'offline-cash-events-v1','events':[self.buy()]}).encode()
        self.store.import_declared_report(payload); self.store.import_declared_report(payload)
        self.assertEqual(self.store.state()['event_count'],2)
        with self.assertRaises(ContractError): self.store.import_declared_report(b'{"Orders":[]}')
    def test_corrupt_payload_detected(self):
        self.store.db.execute("UPDATE cash_events SET body='{}'"); self.store.db.commit()
        with self.assertRaises(EvidenceIntegrityError): self.store.state()
    def test_transaction_preserved(self):
        self.store.db.execute('BEGIN')
        self.store.state(); self.assertTrue(self.store.db.in_transaction)
        with self.assertRaises(ContractError): self.store.append_event(self.buy())
        self.store.db.rollback()
    def test_nonterminating_split_rejected(self):
        self.store.append_event(self.buy())
        with self.assertRaises(ContractError): self.store.append_event(event('s','split',instrument_id='listing:A',numerator='1',denominator='3'))
    def test_reconciliation_currency_required(self):
        with self.assertRaises(ContractError): self.store.reconcile(expected_currency='EUR',expected_cash='1000',expected_positions={},cash_tolerance='0',quantity_tolerance='0')
    def test_demo_restart(self):
        from trading_intelligence.cash_ledger_demo import cash_ledger_demo
        first = cash_ledger_demo(Path(self.temp.name)/'demo')
        self.assertEqual(first,cash_ledger_demo(Path(self.temp.name)/'demo'))
        self.assertEqual(first['state']['cash'],'803')
        self.assertEqual(first['state']['positions'],{'synthetic:listing':'4'})
        self.assertEqual(len(first['expected_errors']),2)
    def test_backwards_clock_cannot_append_second_opening(self):
        self.store._clock = lambda:NOW-timedelta(hours=2)
        with self.assertRaises(ContractError): self.store.append_event({**self.opening,'event_id':'second'})
        self.store._clock = lambda:NOW
        self.assertEqual(self.store.state()['event_count'],1)
    def test_sequence_tamper_detected(self):
        self.store.append_event(self.buy())
        self.store.append_event(event('sell','sell',instrument_id='listing:A',quantity='1',price='100',fee='0'))
        self.store.db.execute('UPDATE cash_events SET sequence=99 WHERE event_id=?',('buy',))
        self.store.db.execute('UPDATE cash_events SET sequence=2 WHERE event_id=?',('sell',))
        self.store.db.execute('UPDATE cash_events SET sequence=3 WHERE event_id=?',('buy',))
        self.store.db.commit()
        with self.assertRaises(EvidenceIntegrityError): self.store.state()
