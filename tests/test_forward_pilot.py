"""Forward pilot with invented captures and fake GET readers, never real orders."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
from threading import Barrier
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

import test_captured_observations as fixtures
from trading_intelligence.alpaca_reader import BrokerRead, PAPER_HOST
from trading_intelligence.alpaca_calendar_reader import CalendarRead, PAPER_CALENDAR_URL, calendar_query
from trading_intelligence.alpaca_price_reader import PriceRead, PRICE_URL, price_query
from trading_intelligence.baseline import digest
from trading_intelligence.contracts import ContractError, EvidenceIntegrityError, RecordConflict, Use, UseNotAllowed
from trading_intelligence.forward_pilot import prepare, collect, status, ForwardStore

T=fixtures.T


class ForwardTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.InspectionTests('test_restart_and_explicit_scope')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.now=T+timedelta(seconds=2)
        self.root=Path(self.fixture.tmp.name)/'forward'
        self.args=dict(database=self.fixture.path,pilot_id='pilot',price_source_id='prices',price_import_id='job',
            calendar_source_id='calendar',calendar_import_id='cal',listing_id='l',clock=lambda:self.now)
        prepare(self.root,**self.args)
        self.calls=[]

    def readers(self,account_number='a',failure=None):
        outer=self
        class Account:
            def read(self,resource):
                outer.calls.append(('account',resource))
                if failure=='account':raise RuntimeError('SECRET must not be echoed')
                return BrokerRead('account',json.dumps(dict(account_number=account_number)).encode(),outer.now,PAPER_HOST+'/v2/account')
        class Calendar:
            def read(self,start,end):
                outer.calls.append(('calendar',start,end))
                rows=[dict(date=d,open='09:30',close='16:00') for d in ['2026-01-05','2026-01-06','2026-01-13','2026-01-14','2026-01-15'] if start<=d<=end]
                return CalendarRead(json.dumps(rows).encode(),outer.now,
                    PAPER_CALENDAR_URL+'?'+urlencode(calendar_query(start,end)),fixtures.R,start,end)
        class Prices:
            def read(self,symbols,start,end,**kw):
                outer.calls.append(('prices',kw['feed']))
                if failure=='prices':raise RuntimeError('SECRET must not be echoed')
                query=price_query(symbols,start,end,feed=kw['feed'],page_token=kw['page_token'],limit=kw['limit'])
                # Jan 14 is the current New York date and must be excluded.
                days=[d for d in ['2026-01-05','2026-01-06','2026-01-13','2026-01-14','2026-01-15'] if start<=d<=end]
                payload=json.dumps(dict(bars={'DEMO':[dict(t=d+'T05:00:00Z',o=100,h=105,l=95,c=102,v=50) for d in days]},next_page_token=None)).encode()
                return PriceRead(payload,outer.now,PRICE_URL+'?'+urlencode(query),fixtures.R,tuple(symbols),start,end,kw['feed'],kw['page_token'],kw['limit'])
        return Account(),Calendar(),Prices()

    def run_collection(self,**changes):
        args=dict(database=self.fixture.path,pilot_id='pilot',collection_id='day1',clock=lambda:self.now,readers=self.readers())
        args.update(changes);return collect(self.root,**args)

    def advance(self):self.now=T+timedelta(days=4,hours=12)

    def test_prepare_freezes_rule_and_seed_without_changing_source_database(self):
        before=self.fixture.path.read_bytes()
        other=self.root.parent/'other';result=prepare(other,**dict(self.args,pilot_id='other'))
        self.assertEqual(before,self.fixture.path.read_bytes())
        self.assertFalse(result['strategy_execution_enabled'])
        self.assertEqual(result['orders_sent'],0)
        with ForwardStore(other/'protocol.sqlite3',clock=lambda:self.now) as store:
            plan=store.pilot('other');baseline=store._get('frozen_baselines','baseline_id','other:baseline')
            self.assertEqual(baseline['semantic']['lookback'],5)
            self.assertEqual(baseline['semantic']['rule'],'close_gt_sma')
            self.assertTrue(plan['semantic']['seed_is_warmup_only'])
        self.assertEqual(stat.S_IMODE(other.stat().st_mode),0o700)
        for path in other.iterdir():self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)

    def test_rule_and_costs_cannot_change_after_preparation(self):
        with ForwardStore(self.root/'protocol.sqlite3',clock=lambda:self.now) as store:
            with self.assertRaises(RecordConflict):
                store.freeze_baseline(baseline_id='pilot:baseline',universe=['l'],lookback=6,
                    costs=dict(commission_per_order='1',spread_bps='2',slippage_bps='1',latency_seconds=1))
        with self.assertRaises(FileExistsError):prepare(self.root,**self.args)

    def test_collection_checks_account_then_captures_and_abstains(self):
        self.advance();result=self.run_collection()
        self.assertEqual(result['type'],'collection_recorded')
        self.assertEqual(result['through_date'],'2026-01-13')
        self.assertEqual(result['observation_count'],3)
        self.assertEqual(result['post_registration_rows'],1)
        self.assertTrue(result['account_match_verified'])
        self.assertEqual(result['decision']['action'],'abstain')
        self.assertIsNone(result['decision']['target_weight'])
        self.assertEqual(self.calls[0],('account','account'))
        self.assertEqual(self.calls[-1],('prices','iex'))
        self.assertEqual(status(self.root,pilot_id='pilot',clock=lambda:self.now)['completed_collections'],1)
        self.assertEqual(self.fixture.s.db.execute('SELECT count(*) FROM market_snapshots').fetchone()[0],0)

    def test_successful_retry_reuses_terminal_record_without_a_request(self):
        self.advance();first=self.run_collection();self.calls.clear()
        self.assertEqual(self.run_collection(),first);self.assertFalse(self.calls)

    def test_old_seed_and_new_receipt_are_not_counted_as_prospective_outcomes(self):
        result=self.run_collection()
        self.assertEqual(result['type'],'collection_recorded')
        self.assertEqual(result['post_registration_rows'],0)
        self.assertEqual(result['decision']['action'],'abstain')

    def test_current_new_york_day_is_excluded_even_after_regular_close(self):
        self.advance();self.now+=timedelta(hours=11)
        result=self.run_collection()
        self.assertEqual(result['through_date'],'2026-01-13')

    def test_stale_account_response_cannot_verify_a_new_attempt(self):
        self.advance();readers=self.readers()
        class Stale:
            def read(self,resource):return BrokerRead('account',b'{"account_number":"a"}',T,PAPER_HOST+'/v2/account')
        result=self.run_collection(readers=(Stale(),readers[1],readers[2]))
        self.assertEqual(result['type'],'collection_failed')
        self.assertEqual(result['stage'],'paper_account_match')
        self.assertFalse(self.calls)

    def test_wrong_account_fails_before_any_price_or_calendar_request(self):
        self.advance();result=self.run_collection(readers=self.readers(account_number='wrong'))
        self.assertEqual(result['type'],'collection_failed');self.assertEqual(result['stage'],'paper_account_match')
        self.assertEqual(self.calls,[('account','account')])
        self.assertFalse(list(self.root.glob('account-*')))

    def test_failure_preserves_attempt_and_never_echoes_secrets_or_retries(self):
        self.advance();result=self.run_collection(readers=self.readers(failure='prices'))
        self.assertEqual(result['stage'],'price_capture')
        self.assertNotIn('SECRET',json.dumps(result))
        self.calls.clear();self.assertEqual(self.run_collection(),result);self.assertFalse(self.calls)
        current=status(self.root,pilot_id='pilot',clock=lambda:self.now)
        self.assertEqual(current['failed_collections'],1)
        self.assertEqual(current['incomplete_collections'],[])
        # The successful calendar preceding the price failure is preserved.
        self.assertIsNotNone(self.fixture.s.calendar_as_of('calendar','pilot:day1:calendar',as_of=self.now))

    def test_an_interrupted_attempt_requires_new_id(self):
        self.advance()
        with ForwardStore(self.root/'protocol.sqlite3',clock=lambda:self.now) as store:
            store.append('pilot','day1:started',dict(type='collection_started',collection_id='day1'))
        with self.assertRaisesRegex(ContractError,'incomplete'):self.run_collection()
        self.assertFalse(self.calls)
        self.assertEqual(status(self.root,pilot_id='pilot',clock=lambda:self.now)['incomplete_collections'],['day1'])

    def test_current_source_revocation_blocks_before_network(self):
        self.advance();self.fixture.s.set_permissions('prices',known_at=self.now,uses={Use.STORAGE})
        with self.assertRaises(UseNotAllowed):self.run_collection()
        self.assertFalse(self.calls)

    def test_expired_or_backward_clock_cannot_start_new_capture(self):
        self.now=T+timedelta(days=61)
        with self.assertRaisesRegex(ContractError,'expired'):self.run_collection()
        self.now=T
        with self.assertRaises(ContractError):self.run_collection()
        self.assertFalse(self.calls)

    def test_account_proof_and_capture_packet_are_hash_checked(self):
        self.advance();result=self.run_collection()
        for key in ('account_raw_file','packet_file'):
            file=self.root/result[key];original=file.read_bytes();file.write_bytes(b'changed')
            with self.assertRaises(EvidenceIntegrityError):status(self.root,pilot_id='pilot',clock=lambda:self.now)
            with self.assertRaises(EvidenceIntegrityError):self.run_collection()
            file.write_bytes(original)

    def test_baseline_plan_and_journal_corruption_are_rejected(self):
        file=self.root/'plan.json';original=file.read_bytes();file.write_bytes(b'{}')
        with self.assertRaises(EvidenceIntegrityError):status(self.root,pilot_id='pilot',clock=lambda:self.now)
        file.write_bytes(original)
        with sqlite3.connect(self.root/'protocol.sqlite3') as db:
            db.execute("UPDATE forward_events SET payload='{}'")
        with self.assertRaises(EvidenceIntegrityError):status(self.root,pilot_id='pilot',clock=lambda:self.now)

    def test_missing_pilot_database_is_not_created(self):
        missing=self.root.parent/'absent';missing.mkdir()
        with self.assertRaises(sqlite3.OperationalError):status(missing,pilot_id='pilot')
        self.assertFalse((missing/'protocol.sqlite3').exists())

    def test_default_readers_use_only_the_existing_local_paper_credentials(self):
        import trading_intelligence.forward_pilot as module
        self.advance();readers=self.readers()
        with (patch.dict('os.environ',dict(ALPACA_PAPER_API_KEY='local-key',ALPACA_PAPER_SECRET_KEY='local-secret')),
             patch.object(module,'AlpacaReferenceReader',return_value=readers[0]) as account,
             patch.object(module,'AlpacaCalendarReader',return_value=readers[1]) as calendar,
             patch.object(module,'AlpacaPriceReader',return_value=readers[2]) as price):
            result=self.run_collection(readers=None)
        self.assertEqual(result['type'],'collection_recorded')
        account.assert_called_once_with('local-key','local-secret')
        for factory in (calendar,price):factory.assert_called_once_with(fixtures.R,'local-key','local-secret')
        self.assertNotIn('local-secret',json.dumps(result))

    def test_source_raw_corruption_is_detected_before_any_network_request(self):
        self.advance()
        self.fixture.s.db.execute("UPDATE raw_objects SET payload=X'00'");self.fixture.s.db.commit()
        with self.assertRaises(EvidenceIntegrityError):self.run_collection()
        self.assertFalse(self.calls)

    def test_actual_cli_prepares_and_reads_a_persistent_pilot(self):
        other=self.root.parent/'cli'
        common=['--out',str(other),'--pilot','cli-pilot']
        process=subprocess.run([sys.executable,'-m','trading_intelligence.forward_pilot','prepare',*common,
            '--database',str(self.fixture.path),'--price-source','prices','--price-import','job',
            '--calendar-source','calendar','--calendar-import','cal','--listing','l'],capture_output=True,text=True)
        self.assertEqual(process.returncode,0,process.stderr)
        prepared=json.loads(process.stdout)
        read=subprocess.run([sys.executable,'-m','trading_intelligence.forward_pilot','status',*common],capture_output=True,text=True)
        self.assertEqual(read.returncode,0,read.stderr)
        self.assertEqual(prepared,json.loads(read.stdout))

    def test_same_collection_cannot_fetch_twice_during_reservation_race(self):
        self.advance();barrier=Barrier(2);original=ForwardStore.append
        def concurrent_append(store,pilot,event,semantic,**kwargs):
            if semantic['type']=='collection_started':barrier.wait(timeout=10)
            return original(store,pilot,event,semantic,**kwargs)
        def worker():
            try:return self.run_collection()['type']
            except RecordConflict:return 'reserved_elsewhere'
        with patch.object(ForwardStore,'append',concurrent_append),ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:worker(),range(2)))
        self.assertEqual(sorted(results),['collection_recorded','reserved_elsewhere'])
        self.assertEqual(sum(call[0]=='account' for call in self.calls),1)

    def test_journal_retry_is_immutable_and_late_clock_cannot_rewrite_it(self):
        with ForwardStore(self.root/'protocol.sqlite3',clock=lambda:self.now) as store:
            event=store.append('pilot','test',dict(type='diagnostic',value=1))
            self.now+=timedelta(hours=1)
            self.assertEqual(store.append('pilot','test',dict(type='diagnostic',value=1)),event)
            with self.assertRaises(RecordConflict):store.append('pilot','test',dict(type='diagnostic',value=2))
