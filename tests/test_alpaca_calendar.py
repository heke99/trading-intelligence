"""Synthetic legacy calendar captures, not exchange/authentication verification."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from trading_intelligence import DataOrigin,Use
from trading_intelligence.alpaca_calendar import AlpacaCalendarStore, FORMAT
from trading_intelligence.contracts import ContractError,RecordConflict,EvidenceIntegrityError,UseNotAllowed

T=datetime(2026,10,25,22,tzinfo=timezone.utc)

class AlpacaCalendarTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'calendar.db'
        self.s=AlpacaCalendarStore(self.path);self.addCleanup(lambda:self.s.close())
        self.s.register_source('fixture',DataOrigin.SYNTHETIC)
        self.s.set_permissions('fixture',known_at=T-timedelta(days=500),uses={Use.STORAGE,Use.RESEARCH})

    def row(self,day='2026-01-05',opened='09:30',closed='16:00'):
        return dict(date=day,open=opened,close=closed)

    def put(self,rows=None,**changes):
        args=dict(source_id='fixture',import_id='calendar',payload=json.dumps([self.row()] if rows is None else rows).encode(),received_at=T,processed_at=T+timedelta(seconds=1),start_date='2026-01-01',end_date='2026-12-31')
        args.update(changes);return self.s.import_calendar(**args)

    def read(self,import_id='calendar',**changes):
        args=dict(as_of=T+timedelta(seconds=2));args.update(changes)
        return self.s.calendar_as_of('fixture',import_id,**args)

    def test_winter_utc_and_no_fabricated_publication(self):
        r=self.put();c=r['candidates'][0]
        self.assertEqual(r['calendar_format'],FORMAT)
        self.assertEqual(c['start'],'2026-01-05T14:30:00.000000Z')
        self.assertEqual(c['end'],'2026-01-05T21:00:00.000000Z')
        self.assertEqual(c['known_at'],r['available_at']);self.assertIsNone(c['published_at'])
        self.assertFalse(r['calendar_complete']);self.assertFalse(r['training_ready'])
        self.assertEqual(self.s.db.execute('SELECT count(*) FROM market_snapshots').fetchone()[0],0)

    def test_summer_and_early_close_preserved(self):
        r=self.put([self.row('2026-07-06',closed='13:00')]);c=r['candidates'][0]
        self.assertEqual(c['start'],'2026-07-06T13:30:00.000000Z')
        self.assertEqual(c['end'],'2026-07-06T17:00:00.000000Z')
        self.assertEqual(c['raw_local_close'],'13:00')

    def test_processing_availability(self):
        self.put();self.assertIsNone(self.read(as_of=T));self.assertIsNotNone(self.read())

    def test_reopen_and_retry(self):
        first=self.put();self.s.close();self.s=AlpacaCalendarStore(self.path)
        self.assertEqual(first,self.put());self.assertEqual(first,self.read())
        self.assertEqual(self.s.db.execute('SELECT count(*) FROM alpaca_calendar_captures').fetchone()[0],1)

    def test_changed_input_cannot_reuse_id(self):
        self.put()
        for changes in [dict(start_date='2026-01-02'),dict(venue='XNAS'),dict(processed_at=T+timedelta(seconds=3)),dict(payload=b'[]')]:
            with self.subTest(changes=changes),self.assertRaises(RecordConflict):self.put(**changes)

    def test_settlement_other_timezone_and_unknown_venue_rejected(self):
        for changes in [dict(calendar_kind='SETTLEMENT'),dict(calendar_kind='trading'),dict(market_timezone='UTC'),dict(venue='XETR')]:
            with self.subTest(changes=changes),self.assertRaises(ContractError):self.put(**changes)

    def test_invalid_request_bounds(self):
        for changes in [dict(start_date='20261231'),dict(start_date='2027-01-01'),dict(end_date=None),dict(start_date='2026-01-00')]:
            with self.subTest(changes=changes),self.assertRaises(ContractError):self.put(**changes)

    def test_outside_bounds_quarantined(self):
        r=self.put([self.row('2025-12-31')]);self.assertFalse(r['candidates'])
        self.assertEqual(r['quarantined'][0]['reason'],'date_outside_requested_range')

    def test_duplicate_dates_all_quarantined(self):
        r=self.put([self.row(),self.row()]);self.assertFalse(r['candidates'])
        self.assertEqual(len(r['quarantined']),2)

    def test_invalid_row_does_not_create_holiday_or_complete_calendar(self):
        r=self.put([self.row(),self.row('2026-01-06',closed='bad')])
        self.assertEqual(len(r['candidates']),1);self.assertEqual(len(r['quarantined']),1)
        self.assertFalse(r['response_rows_valid']);self.assertFalse(r['calendar_complete'])
        self.assertTrue(r['unreported_dates_not_classified'])

    def test_empty_list_is_not_closed_date_certification(self):
        r=self.put([]);self.assertEqual(r['candidates'],[])
        self.assertTrue(r['response_rows_valid']);self.assertFalse(r['calendar_complete'])
        self.assertTrue(r['unreported_dates_not_classified'])

    def test_new_calendar_response_shape_is_quarantined(self):
        for index,rows in enumerate([{'calendar':[self.row()]},[dict(date='2026-01-05',open='2026-01-05T14:30:00Z',close='2026-01-05T21:00:00Z')],[dict(date='2026-01-05',open='09:30',close='16:00',market='NYSE')]]):
            r=self.put(rows,import_id=str(index));self.assertFalse(r['candidates']);self.assertTrue(r['quarantined'])

    def test_invalid_json_and_duplicate_keys_are_durable(self):
        for index,payload in enumerate([b'bad',b'[{"date":"2026-01-05","date":"2026-01-06","open":"09:30","close":"16:00"}]',b'[NaN]']):
            r=self.put(import_id=str(index),payload=payload)
            self.assertTrue(r['quarantined']);self.assertEqual(r,self.read(str(index)))

    def test_optional_extended_fields_not_used_as_regular_session(self):
        row=dict(self.row(),session_open='0400',session_close='2000',settlement_date='2026-01-06')
        r=self.put([row]);self.assertEqual(r['candidates'][0]['raw_local_open'],'09:30')
        self.assertEqual(r['candidates'][0]['raw_local_close'],'16:00')

    def test_bad_times_noncanonical_dates_and_nonobjects(self):
        for index,row in enumerate([self.row(opened='24:00'),self.row(opened='09:60'),self.row(opened='16:00',closed='09:30'),self.row(day='20260105'),None,self.row(opened='0930')]):
            r=self.put([row],import_id=str(index));self.assertFalse(r['candidates']);self.assertTrue(r['quarantined'])

    def test_dst_nonexistent_and_ambiguous_times_rejected(self):
        for index,row in enumerate([self.row('2026-03-08',opened='02:30'),self.row('2026-11-01',opened='01:30')]):
            r=self.put([row],import_id=str(index));self.assertFalse(r['candidates']);self.assertTrue(r['quarantined'])

    def test_permissions_are_enforced(self):
        self.put();self.s.set_permissions('fixture',known_at=T+timedelta(seconds=2),uses={Use.STORAGE})
        with self.assertRaises(UseNotAllowed):self.read()
        self.assertIsNotNone(self.read(as_of=T+timedelta(seconds=1)))
        with self.assertRaises(UseNotAllowed):self.put(import_id='new',processed_at=T+timedelta(seconds=3))

    def test_invalid_processing_and_naive_timestamps(self):
        for changes in [dict(processed_at=T-timedelta(seconds=1)),dict(received_at=T.replace(tzinfo=None))]:
            with self.subTest(changes=changes),self.assertRaises(ContractError):self.put(**changes)

    def test_raw_manifest_and_quarantine_integrity(self):
        for index,(table,change) in enumerate([('raw_objects',"payload=X'00'"),('alpaca_calendar_captures',"result_json='{}'"),('alpaca_calendar_quarantine',"reason='changed'")]):
            key=str(index);result=self.put(payload=b'bad',import_id=key)
            if table=='raw_objects':self.s.db.execute(f'UPDATE {table} SET {change} WHERE sha256=?',(result['raw_sha'],))
            else:self.s.db.execute(f'UPDATE {table} SET {change} WHERE import_id=?',(key,))
            self.s.db.commit()
            with self.assertRaises(EvidenceIntegrityError):self.read(key)
            if table=='raw_objects':self.s.db.execute('UPDATE raw_objects SET payload=? WHERE sha256=?',(b'bad',result['raw_sha']));self.s.db.commit()

    def test_import_guard_preserves_caller_transaction(self):
        self.s.db.execute('INSERT INTO entities VALUES (?,?)',('pending','Pending'))
        with self.assertRaises(ContractError):self.put()
        self.assertTrue(self.s.db.in_transaction);self.s.db.rollback()
        self.assertEqual(self.s.db.execute("SELECT count(*) FROM entities WHERE entity_id='pending'").fetchone()[0],0)

    def test_read_preserves_caller_transaction_on_success_and_failure(self):
        self.put();self.s.db.execute('INSERT INTO entities VALUES (?,?)',('pending','Pending'))
        self.read();self.assertTrue(self.s.db.in_transaction)
        self.s.db.execute("UPDATE alpaca_calendar_captures SET result_json='{}'")
        with self.assertRaises(EvidenceIntegrityError):self.read()
        self.assertTrue(self.s.db.in_transaction);self.s.db.rollback();self.assertIsNotNone(self.read())

    def test_capture_raw_bytes_and_request_boundaries_preserved(self):
        payload=b' [ { "date":"2026-01-05", "open":"09:30", "close":"16:00" } ] '
        result=self.put(payload=payload)
        self.assertEqual(self.s.db.execute('SELECT payload FROM raw_objects WHERE sha256=?',(result['raw_sha'],)).fetchone()[0],payload)
        self.assertEqual(result['start_date'],'2026-01-01');self.assertEqual(result['end_date'],'2026-12-31')

    def test_declared_http_provenance_preserves_request_without_auth_claim(self):
        provenance=dict(endpoint='https://paper-api.alpaca.markets/v2/calendar',method='GET',query=dict(start='2026-01-01',end='2026-12-31',date_type='TRADING'),route=dict(broker_id='alpaca',connection_id='paper-connection',account_id='paper-account',environment='paper'))
        result=self.put(provenance=provenance)
        self.assertEqual(result['provenance'],provenance)
        self.assertEqual(result['capture_origin'],'declared_http_get')
        self.assertFalse(result['authenticated_account_verified'])
        self.assertEqual(result,self.put(provenance=provenance))
        with self.assertRaises(RecordConflict):self.put()

    def test_unsafe_or_mismatched_provenance_rejected(self):
        base=dict(endpoint='https://paper-api.alpaca.markets/v2/calendar',method='GET',query=dict(start='2026-01-01',end='2026-12-31',date_type='TRADING'),route=dict(broker_id='alpaca',connection_id='paper-connection',account_id='paper-account',environment='paper'))
        cases=[dict(base,method='POST'),dict(base,endpoint='https://evil.invalid/v2/calendar'),dict(base,route='live'),dict(base,secret='forbidden'),dict(base,query=dict(start='2026-01-02',end='2026-12-31')),dict(base,query=dict(start='2026-01-01',end='2026-12-31',token='forbidden'))]
        for case in cases:
            with self.subTest(case=case),self.assertRaises(ContractError):self.put(provenance=case)
