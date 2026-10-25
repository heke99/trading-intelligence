"""Synthetic review assertions and supplied vendor bytes, never real approval."""
from datetime import datetime,timedelta,timezone
import unittest

from trading_intelligence import AssetKind,DataOrigin,Entity,Instrument,Listing,Use
from trading_intelligence.contracts import ContractError,EvidenceIntegrityError,RecordConflict,UseNotAllowed
from trading_intelligence.data_admission import DataAdmissionStore,AXES

T=datetime(2026,1,10,tzinfo=timezone.utc)

class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.now=T+timedelta(seconds=2)
        self.s=DataAdmissionStore(':memory:',clock=lambda:self.now)
        self.addCleanup(self.s.close)
        self.setup_source('source',DataOrigin.PROVIDER)
        self.s.register_entity(Entity('e','Invented'))
        self.s.register_instrument(Instrument('i','e',AssetKind.EQUITY))
        self.s.register_listing(Listing('l','i','XNYS','USD'))
        bars=self.s.import_bars(source_id='source',import_id='bars',
            payload=b'{"bars":{"DEMO":[{"t":"2026-01-05T05:00:00Z","o":100,"h":101,"l":99,"c":100,"v":10}]},"next_page_token":null}',
            received_at=T,processed_at=T+timedelta(seconds=1),symbol_listings={'DEMO':'l'},
            feed='iex',timeframe='1Day',adjustment='raw',market_timezone='America/New_York')
        calendar=self.s.import_calendar(source_id='source',import_id='calendar',
            payload=b'[{"date":"2026-01-05","open":"09:30","close":"16:00"}]',received_at=T,
            processed_at=T+timedelta(seconds=1),start_date='2026-01-05',end_date='2026-01-05')
        self.scope=dict(bar_import_id='bars',calendar_import_id='calendar',bar_raw_sha=bars['raw_sha'],
                        calendar_raw_sha=calendar['raw_sha'],listing_id='l',venue='XNYS',
                        start_date='2026-01-05',end_date='2026-01-05',feed='iex')
        self.evidence=self.s.ingest(source_id='source',record_id='review-material',revision_id='1',
                                   payload=b'invented review materials',published_at=T,received_at=T)

    def setup_source(self,source,origin):
        self.s.register_source(source,origin)
        self.s.set_permissions(source,known_at=T-timedelta(days=30),uses={Use.STORAGE,Use.RESEARCH})

    def review(self,axis='rights',**changes):
        args=dict(review_id=axis+'1',source_id='source',axis=axis,purpose='forward_observation',
                  scope=self.scope,expires_at=T+timedelta(days=1),reviewer='declared-reviewer',
                  evidence_refs=[self.evidence],decision='allow')
        if axis=='rights':args['declared_rights']=['storage','research']
        if axis=='temporal':args['temporal_basis']='observed_receipt_and_processing'
        args.update(changes)
        return self.s.record_review(**args)

    def allow(self,**changes):
        for axis in AXES:self.review(axis,**changes)

    def assess(self,**changes):
        args=dict(source_id='source',scope=self.scope,intended_use='forward_observation',as_of=T+timedelta(seconds=2))
        args.update(changes)
        return self.s.assess(**args)

    def test_missing_reviews_deny_and_keep_axes_separate(self):
        self.review();r=self.assess()
        self.assertFalse(r['eligible_for_declared_purpose'])
        self.assertTrue(r['axes']['rights']['declared_review_allows'])
        self.assertFalse(r['axes']['coverage']['declared_review_allows'])

    def test_forward_report_requires_all_explicit_reviews_not_promotion(self):
        self.allow();r=self.assess()
        self.assertTrue(r['eligible_for_declared_purpose'])
        self.assertEqual(r,self.assess())
        self.assertEqual(self.s.db.execute('SELECT count(*) FROM market_snapshots').fetchone()[0],0)
        for flag in ('promotion_performed','training_ready','live_trading','full_history_verified'):
            self.assertFalse(r[flag])
        self.assertTrue(all(not a['independently_verified'] for a in r['axes'].values()))

    def test_current_revocation_blocks_old_cutoff(self):
        self.allow();self.now=T+timedelta(hours=1)
        self.review(review_id='rights2',decision='deny')
        r=self.assess()
        self.assertFalse(r['eligible_for_declared_purpose'])
        self.assertEqual(r['axes']['rights']['historical_review_id'],'rights1')
        self.assertEqual(r['axes']['rights']['current_review_id'],'rights2')

    def test_current_expiry_blocks_old_cutoff(self):
        self.allow();self.now=T+timedelta(days=2)
        self.assertFalse(self.assess()['eligible_for_declared_purpose'])

    def test_source_permission_revocation_cannot_use_old_cutoff(self):
        self.allow();self.now=T+timedelta(hours=1)
        self.s.set_permissions('source',known_at=self.now,uses={Use.STORAGE})
        with self.assertRaises(UseNotAllowed):self.assess()

    def test_review_backdating_or_future_availability_rejected(self):
        for known in (T,T+timedelta(days=1)):
            with self.assertRaises(ContractError):self.review(known_at=known)
        with self.assertRaises(ContractError):self.assess(as_of=T+timedelta(days=1))

    def test_review_immutable_and_raw_archived(self):
        digest=self.review();self.assertEqual(digest,self.review())
        with self.assertRaises(RecordConflict):self.review(decision='deny')
        self.assertIsNotNone(self.s.db.execute('SELECT payload FROM raw_objects WHERE sha256=?',(digest,)).fetchone())

    def test_changed_scope_and_capture_hash_do_not_inherit_reviews(self):
        self.allow();scope=dict(self.scope,bar_raw_sha='0'*64)
        r=self.assess(scope=scope)
        self.assertFalse(r['eligible_for_declared_purpose']);self.assertIn('capture_hash_mismatch',r['reasons'])
        r=self.assess(scope=dict(self.scope,venue='XNAS'))
        self.assertIn('identity_or_feed_scope_mismatch',r['reasons'])
        self.assertIn('calendar_request_scope_mismatch',r['reasons'])

    def test_historical_unknown_publication_cannot_be_reviewed_away(self):
        for axis in AXES:
            kw=dict(purpose='historical_replay')
            if axis=='temporal':kw['temporal_basis']='documented_publication_vintage'
            self.review(axis,**kw)
        r=self.assess(intended_use='historical_replay')
        self.assertFalse(r['eligible_for_declared_purpose'])
        self.assertIn('historical_publication_or_vintage_unknown',r['reasons'])

    def test_synthetic_origin_never_real_observation(self):
        self.allow()
        # Explicit direct fixture mutation tests origin gating only; no real
        # source is relabelled by the production API.
        self.s.db.execute("UPDATE sources SET origin=? WHERE source_id='source'",(DataOrigin.SYNTHETIC.value,));self.s.db.commit()
        self.assertIn('provider_origin_required_for_real_use',self.assess()['reasons'])
        self.now+=timedelta(seconds=1)
        for axis in AXES:
            kw=dict(purpose='synthetic_validation',review_id=axis+'fixture')
            if axis=='temporal':kw['temporal_basis']='synthetic_fixture_only'
            self.review(axis,**kw)
        r=self.assess(intended_use='synthetic_validation',as_of=self.now)
        self.assertTrue(r['eligible_for_declared_purpose'])

    def test_review_and_evidence_corruption_fail_closed(self):
        self.allow()
        self.s.db.execute("UPDATE data_admission_reviews SET review_json='{}' WHERE axis='rights'");self.s.db.commit()
        with self.assertRaises(EvidenceIntegrityError):self.assess()

    def test_capture_not_available_yet_is_not_eligible(self):
        r=self.assess(as_of=T)
        self.assertIn('capture_unavailable_at_cutoff',r['reasons'])

    def test_unknown_evidence_and_wrong_temporal_basis(self):
        with self.assertRaises(ContractError):self.review(evidence_refs=['missing'])
        for axis in AXES:
            self.review(axis,**({'temporal_basis':'synthetic_fixture_only'} if axis=='temporal' else {}))
        self.assertIn('temporal_review_basis_mismatch',self.assess()['reasons'])

    def test_read_does_not_commit_caller_transaction(self):
        self.allow();self.s.db.execute('BEGIN');self.s.db.execute("INSERT INTO entities VALUES ('pending','Pending')")
        self.assess();self.assertTrue(self.s.db.in_transaction)
        self.s.db.rollback()
        self.assertIsNone(self.s.db.execute("SELECT 1 FROM entities WHERE entity_id='pending'").fetchone())

    def test_declared_rights_and_quarantine_cannot_be_ignored(self):
        for axis in AXES:
            self.review(axis,**({'declared_rights':['storage']} if axis=='rights' else {}))
        self.assertFalse(self.assess()['axes']['rights']['declared_review_allows'])

    def test_corrupted_linked_evidence_blocks_assessment(self):
        self.allow()
        self.s.db.execute("UPDATE raw_objects SET payload=? WHERE sha256=(SELECT sha256 FROM evidence_versions WHERE evidence_id=?)",(b'corrupt',self.evidence))
        self.s.db.commit()
        with self.assertRaises(EvidenceIntegrityError):self.assess()

    def test_review_cannot_override_unresolved_pages(self):
        capture=self.s.import_bars(source_id='source',import_id='more-pages',
            payload=b'{"bars":{"DEMO":[{"t":"2026-01-05T05:00:00Z","o":100,"h":101,"l":99,"c":100,"v":10}]},"next_page_token":"next"}',
            received_at=T,processed_at=T+timedelta(seconds=1),symbol_listings={'DEMO':'l'},
            feed='iex',timeframe='1Day',adjustment='raw',market_timezone='America/New_York')
        self.scope.update(bar_import_id='more-pages',bar_raw_sha=capture['raw_sha'])
        self.allow();r=self.assess()
        self.assertFalse(r['eligible_for_declared_purpose'])
        self.assertIn('unresolved_price_pages',r['reasons'])

    def test_review_cannot_override_invalid_calendar_or_date_coverage(self):
        capture=self.s.import_calendar(source_id='source',import_id='invalid-cal',
            payload=b'[{"date":"2026-01-05","open":"16:00","close":"09:30"}]',received_at=T,
            processed_at=T+timedelta(seconds=1),start_date='2026-01-05',end_date='2026-01-05')
        self.scope.update(calendar_import_id='invalid-cal',calendar_raw_sha=capture['raw_sha'])
        self.allow();r=self.assess()
        self.assertFalse(r['eligible_for_declared_purpose'])
        self.assertIn('quarantined_capture_rows',r['reasons'])
        self.assertIn('price_calendar_date_coverage_mismatch',r['reasons'])

    def test_early_daily_capture_stays_partial_even_after_close_and_allow_reviews(self):
        early=datetime(2026,1,5,15,tzinfo=timezone.utc)
        capture=self.s.import_bars(source_id='source',import_id='early',
            payload=b'{"bars":{"DEMO":[{"t":"2026-01-05T05:00:00Z","o":100,"h":101,"l":99,"c":100,"v":10}]},"next_page_token":null}',
            received_at=early,processed_at=early+timedelta(seconds=1),symbol_listings={'DEMO':'l'},
            feed='iex',timeframe='1Day',adjustment='raw',market_timezone='America/New_York')
        self.scope.update(bar_import_id='early',bar_raw_sha=capture['raw_sha'])
        self.allow()
        report=self.assess()
        self.assertFalse(report['eligible_for_declared_purpose'])
        self.assertIn('daily_bar_not_complete_at_observation',report['reasons'])
        self.now+=timedelta(hours=1)
        self.assertIn('daily_bar_not_complete_at_observation',self.assess()['reasons'])
