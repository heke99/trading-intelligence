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
