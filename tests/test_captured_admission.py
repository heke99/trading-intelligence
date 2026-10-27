"""Invented two-source capture/review fixtures; no provider approval."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import sqlite3
import stat
import unittest
from urllib.parse import urlencode

import test_captured_observations as fixtures
from trading_intelligence.captured_admission import assess_captured, prepare_assessment
from trading_intelligence.contracts import ContractError, EvidenceIntegrityError, Use, UseNotAllowed
from trading_intelligence.data_admission import DataAdmissionStore
from trading_intelligence.alpaca_price_reader import PriceRead, PRICE_URL, price_query
from trading_intelligence.price_sync import sync_prices

T=fixtures.T
timedelta=fixtures.timedelta


class CapturedAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.InspectionTests('test_restart_and_explicit_scope')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.now=T+timedelta(seconds=2)
        self.store=DataAdmissionStore(self.fixture.path,clock=lambda:self.now)
        self.addCleanup(self.store.close)
        calendar=self.store.calendar_as_of('calendar','cal',as_of=self.now)
        self.payload=self.store.db.execute('SELECT payload FROM raw_objects WHERE sha256=?',(calendar['raw_sha'],)).fetchone()[0]
        self.provenance=calendar['provenance']
        self.store.import_calendar(source_id='calendar',import_id='matched',payload=self.payload,
            received_at=T,processed_at=T+timedelta(seconds=1),start_date='2026-01-05',
            end_date='2026-01-06',venue='XNAS',provenance=self.provenance)
        self.proofs={source:self.store.ingest(source_id=source,record_id='invented-review-material',
            revision_id='1',payload=('Invented '+source+' review proof').encode(),published_at=T,received_at=T)
            for source in ('prices','calendar')}

    def args(self,**changes):
        values=dict(intended_use='forward_observation',price_source_id='prices',price_import_id='job',
            calendar_source_id='calendar',calendar_import_id='matched',listing_id='l',clock=lambda:self.now)
        values.update(changes);return values

    def assess(self,**changes):return assess_captured(self.store,**self.args(**changes))

    def allow(self,purpose='forward_observation'):
        packet=self.assess(intended_use=purpose)
        for template in packet['review_templates']:
            values=dict(template,review_id=template['source_id']+'-'+template['axis']+'-'+purpose,
                reviewer='synthetic-reviewer',evidence_refs=[self.proofs[template['source_id']]],
                decision='allow',expires_at=T+timedelta(days=1))
            if template['axis']=='rights':values['declared_rights']=['storage','research']
            self.store.record_review(**values)
        return packet

    def test_two_sources_need_their_own_four_reviews_and_no_default_approval(self):
        packet=self.assess();r=packet['assessment']
        self.assertEqual(len(r['reasons']),8)
        self.assertFalse(r['eligible_for_declared_purpose'])
        self.assertEqual(set(r['source_reviews']),{'prices','calendar'})
        self.assertTrue(all(t['decision'] is None and not t['evidence_refs'] for t in packet['review_templates']))
        self.assertEqual(r['temporal_diagnostics']['rows_available_by_session_close'],0)
        self.assertEqual(r['temporal_diagnostics']['later_captured_sessions'],[])

    def test_clock_changes_do_not_reset_the_exact_review_scope(self):
        first=self.assess()
        self.now+=timedelta(hours=1)
        later=self.assess()
        self.assertEqual(first['assessment']['scope_sha256'],later['assessment']['scope_sha256'])
        self.assertNotEqual(first['assessment']['inspection_sha256'],later['assessment']['inspection_sha256'])

    def test_forward_declared_eligibility_never_promotes_or_authorizes_baseline(self):
        self.allow();r=self.assess()['assessment']
        self.assertTrue(r['eligible_for_declared_purpose'])
        self.assertFalse(r['reasons'])
        for field in ('dataset_admitted','promotion_performed','publication_verified','training_ready',
                      'full_history_verified','live_trading','strategy_profitability_verified'):
            self.assertFalse(r[field])
        self.assertIn('corporate_action_coverage_unverified',r['baseline_blockers'])
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM market_snapshots').fetchone()[0],0)

    def test_publication_unknown_cannot_be_approved_away(self):
        self.allow('historical_replay');r=self.assess(intended_use='historical_replay')['assessment']
        self.assertEqual(r['reasons'],['historical_publication_or_vintage_unknown'])
        self.assertFalse(r['eligible_for_declared_purpose'])

    def test_calendar_venue_mismatch_is_a_hard_block(self):
        packet=self.assess(calendar_import_id='cal')
        for template in packet['review_templates']:
            values=dict(template,review_id=template['source_id']+template['axis'],decision='allow',
                reviewer='invented',evidence_refs=[self.proofs[template['source_id']]],expires_at=T+timedelta(days=1))
            if template['axis']=='rights':values['declared_rights']=['storage','research']
            self.store.record_review(**values)
        self.assertEqual(self.assess(calendar_import_id='cal')['assessment']['reasons'],['calendar_listing_venue_mismatch'])

    def test_expiry_and_current_denial_take_effect(self):
        self.allow();self.now+=timedelta(hours=1)
        template=self.assess()['review_templates'][0]
        self.store.record_review(**dict(template,review_id='later-denial',reviewer='invented',
            evidence_refs=[self.proofs['prices']],decision='deny',declared_rights=[],expires_at=T+timedelta(days=1)))
        self.assertFalse(self.assess()['assessment']['source_reviews']['prices']['rights']['declared_review_allows'])
        self.now=T+timedelta(days=1)
        self.assertFalse(self.assess()['assessment']['eligible_for_declared_purpose'])

    def test_revoked_current_permissions_fail_even_with_saved_reviews(self):
        self.allow();self.now+=timedelta(seconds=1)
        self.store.set_permissions('calendar',known_at=self.now,uses={Use.STORAGE})
        with self.assertRaises(UseNotAllowed):self.assess()

    def test_unrelated_source_and_wrong_source_evidence_cannot_record_review(self):
        template=self.assess()['review_templates'][0]
        values=dict(template,review_id='bad',reviewer='invented',decision='allow',
            declared_rights=['storage','research'],evidence_refs=[self.proofs['calendar']],expires_at=T+timedelta(days=1))
        with self.assertRaises(ContractError):self.store.record_review(**values)
        with self.assertRaises(ContractError):self.store.record_review(**dict(values,source_id='unrelated'))

    def test_different_calendar_source_cannot_reuse_a_review(self):
        self.allow()
        self.store.register_source('other-calendar',fixtures.DataOrigin.PROVIDER)
        self.store.set_permissions('other-calendar',known_at=T,uses={Use.STORAGE,Use.RESEARCH})
        self.store.import_calendar(source_id='other-calendar',import_id='matched',payload=self.payload,
            received_at=T,processed_at=T+timedelta(seconds=1),start_date='2026-01-05',
            end_date='2026-01-06',venue='XNAS',provenance=self.provenance)
        old=self.assess()['assessment'];new=self.assess(calendar_source_id='other-calendar')['assessment']
        self.assertNotEqual(old['scope_sha256'],new['scope_sha256'])
        self.assertFalse(new['eligible_for_declared_purpose'])
        self.assertFalse(new['source_reviews']['prices']['rights']['declared_review_allows'])

    def test_all_price_pages_are_bound_and_old_job_reviews_cannot_transfer(self):
        self.allow()
        class TwoPages:
            def read(self,symbols,start,end,**kw):
                first=kw['page_token'] is None
                query=price_query(symbols,start,end,feed=kw['feed'],page_token=kw['page_token'],limit=kw['limit'])
                payload=json.dumps(dict(bars={'DEMO':[dict(t=('2026-01-05' if first else '2026-01-06')+'T05:00:00Z',o=100,h=105,l=95,c=102,v=50)]},next_page_token='page2' if first else None)).encode()
                return PriceRead(payload,T,PRICE_URL+'?'+urlencode(query),fixtures.R,tuple(symbols),start,end,kw['feed'],kw['page_token'],kw['limit'])
        sync_prices(self.store,source_id='prices',import_id='two-pages',route=fixtures.R,
            symbol_listings={'DEMO':'l'},start_date='2026-01-05',end_date='2026-01-06',feed='iex',reader=TwoPages(),clock=lambda:T)
        packet=self.assess(price_import_id='two-pages')
        self.assertEqual(len(packet['inspection']['price_lineage']),2)
        self.assertNotEqual(packet['assessment']['scope_sha256'],self.assess()['assessment']['scope_sha256'])
        self.assertFalse(packet['assessment']['eligible_for_declared_purpose'])
        page=packet['inspection']['price_lineage'][1]
        self.store.db.execute("UPDATE raw_objects SET payload=X'00' WHERE sha256=?",(page['raw_sha'],));self.store.db.commit()
        with self.assertRaises(EvidenceIntegrityError):self.assess(price_import_id='two-pages')

    def test_assessment_keeps_a_callers_pending_transaction(self):
        self.store.db.execute("INSERT INTO entities VALUES ('pending','Pending')")
        self.assess();self.assertTrue(self.store.db.in_transaction)
        self.store.db.rollback()

    def test_readonly_packet_needs_no_review_table_and_preserves_database(self):
        # Remove the optional table in this isolated fixture before exercising
        # the same read-only path as an existing Mac capture-only database.
        self.store.db.execute('DROP TABLE data_admission_reviews');self.store.db.commit()
        before=self.fixture.path.read_bytes();out=Path(self.fixture.tmp.name)/'packet'
        result=prepare_assessment(out,database=self.fixture.path,**self.args())
        self.assertEqual(result['status'],'blocked')
        self.assertEqual(before,self.fixture.path.read_bytes())
        self.assertEqual(len(result['evidence_files']),4)
        self.assertEqual(stat.S_IMODE(out.stat().st_mode),0o700)
        for name,digest in result['evidence_files'].items():
            self.assertEqual(hashlib.sha256((out/name).read_bytes()).hexdigest(),digest)
            self.assertEqual(stat.S_IMODE((out/name).stat().st_mode),0o600)
        with self.assertRaises(FileExistsError):prepare_assessment(out,database=self.fixture.path,**self.args())
        self.assertEqual(before,self.fixture.path.read_bytes())

    def test_missing_database_is_not_created(self):
        missing=Path(self.fixture.tmp.name)/'absent.sqlite'
        with self.assertRaises(sqlite3.OperationalError):prepare_assessment(Path(self.fixture.tmp.name)/'none',database=missing,**self.args())
        self.assertFalse(missing.exists())

    def test_legacy_single_source_assessor_cannot_misinterpret_two_source_scope(self):
        scope=self.assess()['assessment']['scope']
        with self.assertRaisesRegex(ContractError,'assess_captured'):
            self.store.assess(source_id='prices',scope=scope,intended_use='forward_observation',as_of=self.now)

    def test_cli_reads_existing_capture_database_without_docker_or_keys(self):
        out=Path(self.fixture.tmp.name)/'cli'
        process=subprocess.run([sys.executable,'-m','trading_intelligence.captured_admission','assess',
            '--database',str(self.fixture.path),'--price-source','prices','--price-import','job',
            '--calendar-source','calendar','--calendar-import','matched','--listing','l',
            '--purpose','historical_replay','--out',str(out)],capture_output=True,text=True)
        self.assertEqual(process.returncode,0,process.stderr)
        result=json.loads(process.stdout)
        self.assertIn('historical_publication_or_vintage_unknown',result['reasons'])
        self.assertEqual(result['network_requests'],0)
