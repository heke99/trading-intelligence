"""Synthetic temporal rename/lineage cases; no real registry assertion."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from trading_intelligence import DataOrigin, Entity, Instrument, Listing, AssetKind, Use, EvidenceStore
from trading_intelligence.contracts import ContractError, UnknownIdentifier, AmbiguousIdentifier, UseNotAllowed, EvidenceIntegrityError
from trading_intelligence.identity_replay import resolve_schedule

T=datetime(2026,1,1,tzinfo=timezone.utc)

class IdentityReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'identity.db'
        self.s=EvidenceStore(self.path);self.addCleanup(lambda:self.s.close())
        self.s.register_source('fixture',DataOrigin.SYNTHETIC)
        self.s.set_permissions('fixture',known_at=T,uses={Use.STORAGE,Use.RESEARCH})
        self.s.register_entity(Entity('issuer','Invented'))
        self.s.register_instrument(Instrument('stock','issuer',AssetKind.EQUITY))
        for listing in ('one','two'):self.s.register_listing(Listing(listing,'stock','XNAS','USD'))
        self.ev=self.evidence('rename',T)
        self.mapping('old','OLD',T,T+timedelta(days=5))
        self.mapping('new','NEW',T+timedelta(days=5),None)

    def evidence(self,name,at):
        return self.s.ingest(source_id='fixture',record_id=name,revision_id='1',payload=name.encode(),published_at=at,received_at=at)

    def mapping(self,mapping,value,start,end,**changes):
        args=dict(mapping_id=mapping,provider='vendor',value=value,listing_id='one',valid_from=start,valid_to=end,known_at=T,evidence_id=self.ev)
        args.update(changes);self.s.put_identifier(**args)

    def request(self,day=4,identifier='OLD',**changes):
        at=T+timedelta(days=day,hours=15)
        r=dict(date=at.date().isoformat(),identifier=identifier,effective_at=at);r.update(changes);return r

    def run_schedule(self,requests=None,**changes):
        args=dict(provider='vendor',as_of=T+timedelta(days=10));args.update(changes)
        return resolve_schedule(self.s,requests or [self.request()],**args)

    def test_rename_retains_instrument_and_listing(self):
        r=self.run_schedule([self.request(),self.request(5,'NEW')])
        self.assertEqual([x['identity']['listing_id'] for x in r['records']],['one','one'])
        self.assertEqual([x['identity']['instrument_id'] for x in r['records']],['stock','stock'])
        self.assertEqual([x['lineage'][0]['mapping_id'] for x in r['records']],['old','new'])
        self.assertFalse(r['training_ready']);self.assertFalse(r['full_history_verified']);self.assertFalse(r['broker_routing_authorized'])

    def test_exclusive_boundary_and_unknown_exact_symbol(self):
        for req in [self.request(5,'OLD'),self.request(4,'NEW'),self.request(4,'old')]:
            with self.subTest(req=req),self.assertRaises(UnknownIdentifier):self.run_schedule([req])

    def test_later_correction_preserves_earlier_cutoff(self):
        before=self.run_schedule(as_of=T+timedelta(days=6))
        ev=self.evidence('correction',T+timedelta(days=7))
        self.mapping('old','OLD',T,T+timedelta(days=5),known_at=T+timedelta(days=7),evidence_id=ev,listing_id='two')
        self.assertEqual(before,self.run_schedule(as_of=T+timedelta(days=6)))
        self.assertEqual(self.run_schedule()['records'][0]['identity']['listing_id'],'two')

    def test_per_decision_cutoff_never_sees_later_mapping(self):
        ev=self.evidence('correction',T+timedelta(days=7))
        self.mapping('old','OLD',T,T+timedelta(days=5),known_at=T+timedelta(days=7),evidence_id=ev,listing_id='two')
        req=self.request(decision_at=T+timedelta(days=4,hours=16))
        r=self.run_schedule([req])
        self.assertEqual(r['records'][0]['identity']['listing_id'],'one')
        self.assertEqual(r['records'][0]['knowledge_mode'],'per_decision')

    def test_ambiguity_is_not_auto_selected(self):
        self.mapping('conflict','OLD',T,T+timedelta(days=5),listing_id='two')
        with self.assertRaises(AmbiguousIdentifier):self.run_schedule()

    def test_duplicate_evidence_for_same_listing_is_audited(self):
        self.mapping('second','OLD',T,T+timedelta(days=5))
        r=self.run_schedule();self.assertEqual(len(r['records'][0]['lineage']),2)

    def test_unknown_provider(self):
        with self.assertRaises(UnknownIdentifier):self.run_schedule(provider='unknown')

    def test_permission_cutoff_and_revocation(self):
        self.s.set_permissions('fixture',known_at=T+timedelta(days=8),uses={Use.STORAGE})
        with self.assertRaises(UseNotAllowed):self.run_schedule()
        self.assertTrue(self.run_schedule(as_of=T+timedelta(days=6))['records'])

    def test_raw_corruption_not_ignored_by_resolver(self):
        self.s.db.execute('UPDATE raw_objects SET payload=?',(b'corrupt',));self.s.db.commit()
        with self.assertRaises(EvidenceIntegrityError):self.run_schedule()

    def test_temporal_corruption_detected(self):
        self.s.db.execute('UPDATE evidence_versions SET received_at=?',( '2026-01-20T00:00:00.000000Z',));self.s.db.commit()
        with self.assertRaises(EvidenceIntegrityError):self.run_schedule()

    def test_restart_manifest_is_stable(self):
        before=self.run_schedule();self.s.close();self.s=EvidenceStore(self.path)
        self.assertEqual(before,self.run_schedule())

    def test_timezone_equivalent_effective_and_cutoff(self):
        req=self.request();offset=timezone(timedelta(hours=-5))
        shifted=dict(req,effective_at=req['effective_at'].astimezone(offset))
        self.assertEqual(self.run_schedule([req]),self.run_schedule([shifted],as_of=(T+timedelta(days=10)).astimezone(offset)))

    def test_naive_wrong_date_and_future_effective_rejected(self):
        for req in [self.request(effective_at=datetime(2026,1,5)),self.request(date='2026-01-06'),self.request(decision_at=T+timedelta(days=3)),self.request(decision_at=T+timedelta(days=11))]:
            with self.subTest(req=req),self.assertRaises(ContractError):self.run_schedule([req])

    def test_noncanonical_duplicates_and_unordered_rejected(self):
        for reqs in [[self.request(date='20260105')],[self.request(),self.request()],[self.request(5,'NEW'),self.request()]]:
            with self.subTest(reqs=reqs),self.assertRaises(ContractError):self.run_schedule(reqs)
        with self.assertRaises(ContractError):resolve_schedule(self.s,[],provider='vendor',as_of=T)

    def test_success_and_failure_preserve_caller_transaction(self):
        self.s.db.execute('INSERT INTO entities VALUES (?,?)',('pending','Pending'))
        self.run_schedule()
        self.assertTrue(self.s.db.in_transaction)
        with self.assertRaises(UnknownIdentifier):self.run_schedule(provider='missing')
        self.assertTrue(self.s.db.in_transaction)
        self.s.db.rollback()
        self.assertEqual(self.s.db.execute("SELECT count(*) FROM entities WHERE entity_id='pending'").fetchone()[0],0)

    def test_no_new_tables_or_order_state(self):
        before=self.s.counts();self.run_schedule();self.assertEqual(before,self.s.counts())
