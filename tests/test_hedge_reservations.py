"""Local draft exclusivity, conservative cash budgets and restart journal."""
from copy import deepcopy
from datetime import timedelta
import concurrent.futures
import json
import unittest
import test_hedge_research as fixtures
from trading_intelligence.hedge_reservations import HedgeReservationStore
from trading_intelligence.contracts import ContractError,RecordConflict,EvidenceIntegrityError,Entity,Instrument,Listing,AssetKind

class ReservationTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.HedgeResearchTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.search()
        self.f.store.close()
        self.store=HedgeReservationStore(self.f.f.path,clock=lambda:self.f.f.now)
        self.f.store=self.f.f.store=self.f.origin.store=self.store

    def reserve(self,identity='one',search='search'):
        return self.store.reserve(identity,search,'hedge:future:-3')

    def test_shared_exposure_blocks_even_with_another_book_label(self):
        self.reserve()
        self.f.raw['inputs']['book']['book_id']='alias'
        self.store.search('alias','preview',self.f.evidence('alias'),as_of=self.f.f.now)
        with self.assertRaises(ContractError):self.reserve('two','alias')

    def test_retry_release_and_restart(self):
        x=self.reserve();self.assertEqual(x,self.reserve())
        with HedgeReservationStore(self.f.f.path,clock=lambda:self.f.f.now) as other:
            self.assertEqual(x,other.reservation('one'))
        released=self.store.release('one',reason='abandoned_research')
        self.assertEqual(released,self.store.release('one',reason='abandoned_research'))
        self.assertEqual(released,self.reserve())
        self.assertEqual(self.reserve('new')['state'],'reserved')
        with self.assertRaises(RecordConflict):self.store.release('one',reason='superseded_research')

    def second_book(self):
        self.f.origin.data['portfolio']['account']='b'
        evidence=self.f.origin.evidence('book-b-opportunity')
        self.store.assess('book-b-opportunity','analysis',evidence,as_of=self.f.f.now)
        self.f.raw['inputs']['book']['route']['account']='b'
        self.store.search('book-b-search','book-b-opportunity',self.f.evidence('book-b-search'),as_of=self.f.f.now)

    def test_separate_exposures_still_share_the_hedge_account_cash_budget(self):
        self.reserve()
        self.second_book()
        with self.assertRaisesRegex(ContractError,'exceed free cash'):
            self.reserve('book-b','book-b-search')
        self.store.release('one',reason='abandoned_research')
        self.assertEqual(self.reserve('book-b','book-b-search')['state'],'reserved')

    def test_cash_vintage_changes_cannot_hide_active_budget(self):
        self.reserve()
        self.f.raw['inputs']['hedge_accounts'][0]['available_cash']='4000'
        self.second_book()
        with self.assertRaisesRegex(ContractError,'same cash snapshot'):
            self.reserve('book-b','book-b-search')

    def test_expiry_does_not_automatically_free_unknown_draft(self):
        self.reserve();self.f.f.now+=timedelta(hours=1)
        self.assertEqual(self.store.reservation('one')['state'],'reserved')
        self.store.release('one',reason='abandoned_research')
        self.assertEqual(self.store.reservation('one')['state'],'released')

    def test_simultaneous_connections_only_one_claims_exposure(self):
        path=self.f.f.path;now=self.f.f.now
        def attempt(identity):
            with HedgeReservationStore(path,clock=lambda:now) as store:
                try:store.reserve(identity,'search','hedge:future:-3');return True
                except ContractError:return False
        with concurrent.futures.ThreadPoolExecutor(2) as executor:
            self.assertEqual(sum(executor.map(attempt,['a','b'])),1)

    def test_invalid_alternative_and_stop_do_not_reserve(self):
        with self.assertRaises(ContractError):self.store.reserve('bad','search','reduce:0.5')
        self.f.raw['controls']['order_mode']='hard_stop'
        self.store.search('stopped','preview',self.f.evidence('stop'),as_of=self.f.f.now)
        with self.assertRaises(ContractError):self.reserve('stopped','stopped')
        self.assertIsNone(self.store.reservation('stopped'))

    def test_corruption_and_clock_rollback_fail_closed(self):
        self.reserve();self.f.f.now-=timedelta(seconds=1)
        with self.assertRaises(EvidenceIntegrityError):self.store.reservation('one')
        self.f.f.now+=timedelta(seconds=1)
        with self.store.db:self.store.db.execute("UPDATE hedge_research_reservations SET sha256='bad'")
        with self.assertRaises(EvidenceIntegrityError):self.reserve('two')

    def test_historical_read_never_exposes_later_release(self):
        before=self.f.f.now-timedelta(microseconds=1)
        original=self.reserve()
        at=self.f.f.now
        self.f.f.now+=timedelta(seconds=1)
        released=self.store.release('one',reason='abandoned_research')
        self.assertIsNone(self.store.reservation_as_of('one',as_of=before))
        self.assertEqual(original,self.store.reservation_as_of('one',as_of=at))
        self.assertEqual(released,self.store.reservation_as_of('one',as_of=self.f.f.now))

    def test_historical_cutoff_cannot_be_future(self):
        with self.assertRaises(ContractError):
            self.store.reservation_as_of('unknown',as_of=self.f.f.now+timedelta(seconds=1))

    def test_fresh_readiness_does_not_reuse_old_positive_result(self):
        original=self.reserve()
        x=self.store.reservation_readiness('one')
        self.assertEqual(x['status'],'inputs_current_for_research')
        self.assertFalse(x['execution_authorized'])
        self.f.f.now+=timedelta(minutes=2)
        self.assertEqual(original,self.reserve())
        x=self.store.reservation_readiness('one')
        self.assertEqual(x['status'],'blocked')
        self.assertIn('expired_at_processing',x['blockers'])
        self.assertEqual(self.store.reservation('one')['state'],'reserved')

    def test_release_is_not_a_ready_reservation(self):
        self.reserve();self.store.release('one',reason='abandoned_research')
        self.assertEqual(self.store.reservation_readiness('one')['blockers'],['reservation_released'])

    def test_revocation_blocks_readiness_but_preserves_metadata_history(self):
        from trading_intelligence.contracts import Use
        original=self.reserve();at=self.f.f.now
        self.f.f.now+=timedelta(seconds=1)
        self.store.set_permissions('hedge-refs',known_at=self.f.f.now,uses={Use.STORAGE})
        x=self.store.reservation_readiness('one')
        self.assertEqual(x['blockers'],['dependency_unavailable_or_not_permitted'])
        self.assertEqual(original,self.store.reservation_as_of('one',as_of=at))

    def test_dependency_corruption_is_a_blocked_check(self):
        self.reserve()
        with self.store.db:
            self.store.db.execute("UPDATE futures_snapshots SET body='{}' WHERE kind='margin'")
        x=self.store.reservation_readiness('one')
        self.assertEqual(x['blockers'],['dependency_integrity_failure'])

    def test_new_check_after_restart_uses_current_clock(self):
        self.reserve();self.f.f.now+=timedelta(hours=1)
        with HedgeReservationStore(self.f.f.path,clock=lambda:self.f.f.now) as other:
            self.assertEqual(other.reservation_readiness('one')['status'],'blocked')

    def test_later_corruption_is_not_hidden_by_historical_cutoff(self):
        self.reserve();at=self.f.f.now
        self.f.f.now+=timedelta(seconds=1)
        self.store.release('one',reason='abandoned_research')
        with self.store.db:
            self.store.db.execute("UPDATE hedge_research_reservations SET sha256='bad' WHERE sequence=1")
        with self.assertRaises(EvidenceIntegrityError):self.store.reservation_as_of('one',as_of=at)

    def test_malformed_dependency_json_returns_blocked_metadata(self):
        self.reserve()
        with self.store.db:
            self.store.db.execute("UPDATE hedge_research SET body_json='{' WHERE search_id='search'")
        self.assertEqual(self.store.reservation_readiness('one')['blockers'],['dependency_integrity_failure'])
