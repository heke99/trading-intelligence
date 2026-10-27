from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from trading_intelligence.contracts import ContractError, DataOrigin, Entity, Use, UseNotAllowed
from trading_intelligence.relation_evidence import RelationEvidenceStore

T = datetime(2026,1,1,tzinfo=timezone.utc)

class Relations(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'relations.db'; self.now=T
        self.s=RelationEvidenceStore(self.path,clock=lambda:self.now)
        self.addCleanup(lambda:self.s.close())
        self.s.register_source('fixture',DataOrigin.SYNTHETIC)
        self.s.set_permissions('fixture',known_at=T,uses={Use.STORAGE,Use.RESEARCH})
        for entity in ('A','B','C'): self.s.register_entity(Entity(entity,entity))
        self.text='Å: A supplies B. Exposure unknown.'
        self.ev=self.s.ingest(source_id='fixture',record_id='doc',revision_id='1',payload=self.text.encode(),published_at=T,received_at=T)

    def record(self,**changes):
        args=dict(version_id='v1',relation_id='r1',source_entity_id='A',target_entity_id='B',
          relation_type='supplies_to',evidence_id=self.ev,span_start=3,span_end=16,
          quote='A supplies B.',valid_from=T,valid_until=None,known_at=self.now,
          reviewer='synthetic-reviewer')
        return self.s.record_relation(**{**args,**changes})

    def query(self,**changes):
        return self.s.relations_as_of(**{**dict(as_of=self.now,effective_at=T),**changes})['relations']

    def test_exact_span_and_restart(self):
        original=self.record(); self.s.close()
        self.s=RelationEvidenceStore(self.path,clock=lambda:self.now)
        self.assertEqual(self.record(),original)
        self.assertEqual(self.query()[0]['quote'],'A supplies B.')

    def test_missing_mismatched_and_byte_offsets_block(self):
        for change in ({'span_start':None},{'span_start':4},{'quote':'A owns B.'},{'span_end':True}):
            with self.subTest(change=change),self.assertRaises(ContractError): self.record(**change)

    def test_no_backdating(self):
        self.now=T+timedelta(days=2); self.record(known_at=T)
        self.assertEqual(self.query(as_of=T),[])
        self.assertEqual(len(self.query()),1)

    def test_correction_preserves_old_knowledge_and_closes_interval(self):
        self.record(); self.now=T+timedelta(days=2)
        self.record(version_id='v2',replaces='v1',valid_until=T+timedelta(days=1))
        self.assertEqual(len(self.query(as_of=T,effective_at=T+timedelta(days=1))),1)
        self.assertEqual(self.query(effective_at=T+timedelta(days=1)),[])
        self.assertEqual(self.query()[0]['version_id'],'v2')

    def test_denial_and_branch_rejected(self):
        self.record(); self.now=T+timedelta(days=1)
        self.record(version_id='v2',replaces='v1',affirmed=False)
        self.assertEqual(self.query(),[])
        self.now+=timedelta(days=1)
        with self.assertRaises(ContractError): self.record(version_id='branch',replaces='v1')

    def test_identity_and_unknown_entities(self):
        with self.assertRaises(ContractError): self.record(target_entity_id='unknown')
        self.record(); self.now+=timedelta(days=1)
        with self.assertRaises(ContractError): self.record(version_id='v2',replaces='v1',target_entity_id='C')

    def test_current_rights_and_incidents(self):
        self.record(); self.now+=timedelta(days=1)
        self.s.set_permissions('fixture',known_at=self.now,uses={Use.STORAGE})
        with self.assertRaises(UseNotAllowed): self.query(as_of=T)

    def test_confirmed_incident_blocks_query(self):
        self.record(); self.now+=timedelta(days=1)
        self.s.record_incident(incident_id='bad',category='extraction',known_at=self.now,
            description='Synthetic wrong entity',affected=[{'kind':'evidence','id':self.ev}],confirmed=True)
        with self.assertRaises(ContractError): self.query(as_of=T)

    def test_provider_source_is_not_silently_admitted(self):
        self.s.register_source('provider',DataOrigin.PROVIDER)
        self.s.set_permissions('provider',known_at=T,uses={Use.STORAGE,Use.RESEARCH})
        ev=self.s.ingest(source_id='provider',record_id='doc',revision_id='1',payload=self.text.encode(),published_at=T,received_at=T)
        with self.assertRaises(ContractError): self.record(evidence_id=ev)

    def test_conflicting_retry_and_corrupt_bytes(self):
        self.record()
        with self.assertRaises(ContractError): self.record(reviewer='different-reviewer')
        with self.s.db:
            self.s.db.execute('UPDATE raw_objects SET payload=? WHERE sha256=(SELECT content_sha256 FROM research_artifacts WHERE artifact_id=?)',(b'corrupt','v1'))
        with self.assertRaises(ContractError): self.query()

    def test_future_knowledge_and_same_time_replacement_block(self):
        with self.assertRaises(ContractError): self.record(known_at=T+timedelta(days=1))
        self.record()
        with self.assertRaises(ContractError): self.record(version_id='v2',replaces='v1')
