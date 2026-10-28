"""Invented corporate-action GET responses and pilot binding; no real entitlements."""
from copy import deepcopy
from datetime import timedelta
from io import BytesIO
import json
from pathlib import Path
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode

import test_forward_pilot as pilots
from trading_intelligence.alpaca_actions import normalize_page, sync_actions, CorporateActionStore, fingerprint
from trading_intelligence.alpaca_actions_reader import ACTION_URL, ActionRead, ActionReadError, AlpacaActionsReader, action_query
from trading_intelligence.alpaca_reader import BrokerRead, PAPER_HOST
from trading_intelligence.corporate_actions import sync_pilot, assess_binding
from trading_intelligence.contracts import ContractError, EvidenceIntegrityError, RecordConflict, Use, UseNotAllowed
from trading_intelligence.contracts import DataOrigin
from trading_intelligence.captured_admission import assess_captured
from trading_intelligence.captured_smoke import readonly_captures
from trading_intelligence.data_admission import DataAdmissionStore


def split(**changes):
    row=dict(id='00000000-0000-4000-8000-000000000001',symbol='DEMO',process_date='2026-01-13',
        ex_date='2026-01-06',new_rate=2,old_rate=1,cusip='123456789',currency='USD')
    row.update(changes);return row


def dividend(**changes):
    row=dict(id='00000000-0000-4000-8000-000000000002',symbol='DEMO',process_date='2026-01-13',
        ex_date='2026-01-06',payable_date='2026-01-13',rate=.125,special=False,foreign=False,currency='USD')
    row.update(changes);return row


def page(groups=None,token=None):
    return json.dumps(dict(corporate_actions={} if groups is None else groups,next_page_token=token)).encode()


class CorporateCaptureTests(unittest.TestCase):
    def setUp(self):
        self.forward=pilots.ForwardTests('test_collection_checks_account_then_captures_and_abstains')
        self.forward.setUp();self.addCleanup(self.forward.doCleanups)
        self.forward.advance();self.forward.run_collection()
        self.path=self.forward.fixture.path;self.root=self.forward.root
        self.calls=[];self.responses=[page(dict(forward_splits=[split()],cash_dividends=[dividend()]))]
        self.out_number=0

    def readers(self,wrong_account=False,fail_at=None):
        outer=self
        class Account:
            def read(self,resource):
                outer.calls.append('account')
                return BrokerRead('account',json.dumps(dict(account_number='wrong' if wrong_account else 'a')).encode(),
                    outer.forward.now,PAPER_HOST+'/v2/account')
        class Actions:
            def read(self,symbol,start,end,**kw):
                index=sum(isinstance(c,dict) for c in outer.calls)
                query=action_query(symbol,start,end,page_token=kw['page_token'],limit=kw['limit'])
                outer.calls.append(query)
                if index==fail_at:raise ActionReadError('http_403')
                payload=outer.responses[min(index,len(outer.responses)-1)]
                return ActionRead(payload,outer.forward.now,pilots.fixtures.R,query,ACTION_URL+'?'+urlencode(query))
        return Account(),Actions()

    def run_capture(self,**changes):
        self.out_number+=1
        args=dict(database=self.path,pilot_directory=self.root,pilot_id='pilot',source_id='actions',import_id='actions-1',
            directory=self.root.parent/('actions-'+str(self.out_number)),declare_storage_research=True,
            clock=lambda:self.forward.now,readers=self.readers())
        args.update(changes);return sync_pilot(**args)

    def inspect(self,import_id='actions-1',as_of=None):
        with CorporateActionStore(self.path) as store:
            return store.inspect_job('actions',import_id,as_of=as_of or self.forward.now,clock=lambda:self.forward.now)

    def test_raw_capture_binds_split_dividend_and_distinct_dates_without_publication(self):
        result=self.run_capture();self.assertEqual(result['status'],'complete_pages')
        self.assertEqual(result['candidate_count'],2);self.assertTrue(result['account_match_verified'])
        self.assertTrue(result['process_pages_complete']);self.assertFalse(result['effective_date_coverage_verified'])
        captured=self.inspect()
        for row in captured['candidates']:
            self.assertEqual(row['process_date'],'2026-01-13');self.assertEqual(row['ex_date'],'2026-01-06')
            self.assertIsNone(row['published_at']);self.assertFalse(row['identity_verified'])
        cash=next(r for r in captured['candidates'] if r['provider_kind']=='cash_dividends')
        self.assertEqual(cash['values']['amount'],'0.125')
        query=next(c for c in self.calls if isinstance(c,dict))
        self.assertNotIn('types',query);self.assertEqual(query['data_quality'],'all')
        self.assertEqual(self.forward.fixture.s.db.execute('SELECT count(*) FROM market_snapshots').fetchone()[0],0)

    def test_empty_terminal_response_never_certifies_no_effective_actions(self):
        self.responses=[page()];result=self.run_capture()
        self.assertEqual(result['status'],'complete_pages');self.assertEqual(result['candidate_count'],0)
        self.assertTrue(result['process_pages_complete'])
        self.assertFalse(result['effective_date_coverage_verified']);self.assertFalse(result['dataset_admitted'])
        self.assertFalse(result['accounting_ready'])

    def test_unsupported_events_and_special_dividends_are_not_silently_dropped(self):
        self.responses=[page(dict(stock_dividends=[dict(id='unsupported')],cash_dividends=[dividend(special=True)]))]
        result=self.run_capture()
        self.assertEqual(result['status'],'quarantined');self.assertEqual(result['quarantine_count'],2)
        self.assertIn('unsupported_action_type',result['quarantine_reasons'])

    def test_missing_currency_stays_unknown_and_blocks_accounting(self):
        value=dividend();value.pop('currency');self.responses=[page(dict(cash_dividends=[value]))]
        self.run_capture();candidate=self.inspect()['candidates'][0]
        self.assertIsNone(candidate['currency']);self.assertIn('provider_currency_unknown',candidate['accounting_blockers'])

    def test_due_bill_is_preserved_for_separate_review(self):
        self.responses=[page(dict(forward_splits=[split(due_bill_redemption_date='2026-01-08')]))]
        self.run_capture();candidate=self.inspect()['candidates'][0]
        self.assertEqual(candidate['due_bill_dates']['due_bill_redemption_date'],'2026-01-08')
        self.assertIn('due_bill_terms_unreviewed',candidate['accounting_blockers'])

    def test_missing_pagination_token_is_not_a_terminal_page(self):
        self.responses=[b'{"corporate_actions":{}}'];result=self.run_capture()
        self.assertEqual(result['status'],'quarantined');self.assertFalse(result['process_pages_complete'])

    def test_all_pages_are_archived_and_duplicate_ids_block_normalized_use(self):
        self.responses=[page(dict(forward_splits=[split()]),token='next'),page(dict(forward_splits=[split()]))]
        result=self.run_capture()
        self.assertEqual(result['action_pages'],2);self.assertEqual(result['status'],'quarantined')
        self.assertEqual(result['quarantine_reasons']['duplicate_action_id'],1)
        self.assertEqual(len(self.inspect()['raw_hashes']),2)

    def test_token_cycle_cannot_become_complete(self):
        self.responses=[page(token='repeat'),page(token='repeat')];result=self.run_capture()
        self.assertEqual(result['status'],'incomplete');self.assertEqual(result['reason'],'token_cycle')
        self.assertFalse(result['process_pages_complete'])

    def test_failed_later_page_keeps_first_page_and_terminal_retry_does_not_fetch(self):
        self.responses=[page(dict(forward_splits=[split()]),token='next')]
        result=self.run_capture(readers=self.readers(fail_at=1))
        self.assertEqual(result['status'],'failed');self.assertEqual(result['error_code'],'http_403')
        self.assertEqual(result['action_pages'],1);self.assertEqual(len(self.inspect()['candidates']),1)
        self.calls.clear();again=self.run_capture()
        self.assertEqual(again['status'],'failed');self.assertFalse(self.calls)

    def test_wrong_account_stops_before_the_data_endpoint(self):
        result=self.run_capture(readers=self.readers(wrong_account=True))
        self.assertEqual(result['status'],'failed');self.assertFalse(result['account_match_verified'])
        self.assertEqual(self.calls,['account'])

    def test_process_bounds_and_symbol_mismatch_are_quarantined(self):
        self.responses=[page(dict(forward_splits=[split(symbol='OTHER'),split(process_date='2025-01-01')]))]
        result=self.run_capture();self.assertEqual(result['quarantine_count'],2)
        self.assertIn('process_date_outside_request',result['quarantine_reasons'])

    def test_malformed_and_duplicate_key_json_are_archived_not_accepted(self):
        self.responses=[b'{"corporate_actions":{},"corporate_actions":{},"next_page_token":null}']
        result=self.run_capture();self.assertEqual(result['status'],'quarantined')
        self.assertEqual(len(self.inspect()['raw_hashes']),1)

    def test_changed_job_scope_requires_a_new_import_id(self):
        self.run_capture();self.calls.clear()
        with self.assertRaises(RecordConflict):self.run_capture(process_start='2026-01-01')
        self.assertFalse(self.calls)

    def test_native_id_revisions_are_separate_snapshots_not_rewrites(self):
        self.run_capture();before=self.inspect();old_time=self.forward.now
        self.forward.now+=timedelta(days=1)
        self.responses=[page(dict(forward_splits=[split(new_rate=3)],cash_dividends=[dividend()]))]
        self.calls.clear();self.run_capture(import_id='actions-2')
        after=self.inspect('actions-2')
        self.assertEqual(before,self.inspect(as_of=old_time))
        self.assertNotEqual(before['candidates'][0]['provider_row_sha256'],after['candidates'][0]['provider_row_sha256'])
        self.assertNotEqual(before['candidates'][0]['known_at'],after['candidates'][0]['known_at'])

    def test_forged_admission_flags_are_rejected_even_if_rehashed(self):
        self.run_capture()
        with CorporateActionStore(self.path) as store:
            row=store.db.execute("SELECT * FROM alpaca_action_results WHERE source_id='actions'").fetchone()
            body=json.loads(row['body_json']);body['dataset_admitted']=True
            store.db.execute('UPDATE alpaca_action_results SET body_json=?,sha256=?',(json.dumps(body,sort_keys=True,separators=(',',':')),fingerprint(body)))
            store.db.commit()
        with self.assertRaises(EvidenceIntegrityError):self.inspect()

    def test_corrupt_original_action_bytes_are_rejected(self):
        self.run_capture();raw_sha=self.inspect()['raw_hashes'][0]
        with CorporateActionStore(self.path) as store:
            store.db.execute("UPDATE raw_objects SET payload=X'00' WHERE sha256=?",(raw_sha,));store.db.commit()
        with self.assertRaises(EvidenceIntegrityError):self.inspect()

    def test_future_ex_date_is_not_confused_with_the_process_query_window(self):
        self.responses=[page(dict(cash_dividends=[dividend(ex_date='2026-02-01',payable_date='2026-02-13')]))]
        result=self.run_capture();candidate=self.inspect()['candidates'][0]
        self.assertEqual(candidate['process_date'],'2026-01-13');self.assertEqual(candidate['ex_date'],'2026-02-01')
        self.assertFalse(result['effective_date_coverage_verified']);self.assertFalse(candidate['accounting_ready'])

    def test_job_cannot_be_read_before_its_capture_availability(self):
        with CorporateActionStore(self.path) as store:
            store.register_source('actions',DataOrigin.PROVIDER)
            store.set_permissions('actions',known_at=self.forward.now-timedelta(hours=1),uses={Use.STORAGE,Use.RESEARCH})
        self.run_capture()
        self.assertIsNone(self.inspect(as_of=self.forward.now-timedelta(seconds=1)))

    def test_source_revocation_cannot_be_undone_by_declaration_or_old_cutoff(self):
        self.run_capture();old=self.forward.now;self.forward.now+=timedelta(hours=1)
        with CorporateActionStore(self.path) as store:
            store.set_permissions('actions',known_at=self.forward.now,uses={Use.STORAGE})
        self.calls.clear()
        with self.assertRaises(UseNotAllowed):self.run_capture(import_id='other')
        with self.assertRaises(UseNotAllowed):self.inspect(as_of=old)
        self.assertFalse(self.calls)

    def test_unknown_source_without_explicit_local_use_declaration_does_not_fetch(self):
        with self.assertRaises(UseNotAllowed):self.run_capture(declare_storage_research=False)
        self.assertFalse(self.calls)

    def test_binding_cannot_transfer_to_another_price_import(self):
        self.run_capture();actions=self.inspect()
        scope=actions['job']['request']['binding']
        with readonly_captures(self.path) as captured:
            store=DataAdmissionStore.__new__(DataAdmissionStore);store.db=captured.db
            packet=assess_captured(store,intended_use='forward_observation',price_source_id='prices',
                price_import_id=scope['price_import_id'],calendar_source_id='calendar',
                calendar_import_id=scope['calendar_import_id'],listing_id='l',clock=lambda:self.forward.now)
        self.assertEqual(assess_binding(packet,actions)['action_manifest_sha256'],actions['manifest_sha256'])
        packet=deepcopy(packet);packet['assessment']['scope']['price_import_id']='other'
        with self.assertRaises(ContractError):assess_binding(packet,actions)

    def test_mutual_funds_and_futures_cannot_use_the_equity_action_flow(self):
        for kind in ('mutual_fund','future'):
            self.forward.fixture.s.db.execute('UPDATE instruments SET kind=?',(kind,));self.forward.fixture.s.db.commit()
            with self.assertRaisesRegex(ContractError,'equity/ETF'):self.run_capture(import_id='not-'+kind)
        self.assertFalse(self.calls)


class ActionsReaderTests(unittest.TestCase):
    def test_reader_is_fixed_get_and_does_not_expose_credentials(self):
        calls=[];payload=page()
        class Response:
            status=200;headers={'Content-Type':'application/json'}
            def __init__(self,url):self.url=url
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def geturl(self):return self.url
            def read(self,limit):return payload
        class Opener:
            def open(self,request,**kwargs):calls.append(request);return Response(request.full_url)
        reader=AlpacaActionsReader(pilots.fixtures.R,'test-key','test-secret',opener=Opener(),clock=lambda:pilots.T)
        result=reader.read('DEMO','2026-01-01','2026-01-31')
        self.assertEqual(calls[0].get_method(),'GET');self.assertTrue(calls[0].full_url.startswith(ACTION_URL+'?'))
        self.assertEqual(result.payload,payload);self.assertNotIn('test-secret',repr(reader))

    def test_403_body_is_redacted_without_retry(self):
        calls=[]
        class Opener:
            def open(self,request,**kwargs):
                calls.append(request);raise HTTPError(request.full_url,403,'secret-body',{},BytesIO(b'secret-body'))
        reader=AlpacaActionsReader(pilots.fixtures.R,'test-key','test-secret',opener=Opener())
        with self.assertRaises(ActionReadError) as error:reader.read('DEMO','2026-01-01','2026-01-31')
        self.assertEqual(error.exception.code,'http_403');self.assertNotIn('secret',str(error.exception));self.assertEqual(len(calls),1)

    def test_invalid_queries_cannot_change_endpoint_scope_or_insert_header_characters(self):
        for args in [('aapl','2026-01-01','2026-01-31'),('DEMO','2026-01-31','2026-01-01')]:
            with self.assertRaises((ContractError,ValueError)):action_query(*args)
        with self.assertRaises(ContractError):action_query('DEMO','2026-01-01','2026-01-31',page_token='bad\ntoken')
