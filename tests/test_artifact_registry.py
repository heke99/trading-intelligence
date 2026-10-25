"""Synthetic artifact lineage and append-only incident regression cases."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from trading_intelligence import DataOrigin, Use
from trading_intelligence.artifact_registry import ArtifactRegistryStore, digest
from trading_intelligence.contracts import ContractError, EvidenceIntegrityError, RecordConflict, UseNotAllowed

T=datetime(2026,1,1,tzinfo=timezone.utc)

class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'artifacts.db';self.now=T
        self.s=ArtifactRegistryStore(self.path,clock=lambda:self.now);self.addCleanup(lambda:self.s.close())
        self.s.register_source('fixture',DataOrigin.SYNTHETIC)
        self.s.set_permissions('fixture',known_at=T,uses={Use.STORAGE,Use.RESEARCH})
        self.ev=self.evidence('one')

    def evidence(self,name):
        return self.s.ingest(source_id='fixture',record_id=name,revision_id='1',payload=name.encode(),published_at=T,received_at=T)

    def artifact(self,identity='a',deps=None,**changes):
        args=dict(artifact_id=identity,kind='features',payload=identity.encode(),known_at=self.now,dependencies=deps or [{'kind':'evidence','id':self.ev}]);args.update(changes)
        return self.s.register_artifact(**args)

    def incident(self,identity='incident',**changes):
        args=dict(incident_id=identity,category='data',known_at=self.now,description='Synthetic source issue',affected=[{'kind':'evidence','id':self.ev}],confirmed=True);args.update(changes)
        return self.s.record_incident(**args)

    def test_immutable_hashes_and_restart_retry(self):
        a=self.artifact();self.s.close();self.s=ArtifactRegistryStore(self.path,clock=lambda:self.now)
        self.assertEqual(a,self.artifact())
        self.assertEqual(a,self.s.get_artifact('a',as_of=T))
        self.assertEqual(a['content_sha256'],hashlib.sha256(b'a').hexdigest())
        with self.assertRaises(RecordConflict):self.artifact(payload=b'changed')

    def test_actual_registration_prevents_backdating(self):
        self.now=T+timedelta(days=2);a=self.artifact(known_at=T)
        self.assertEqual(a['available_at'],self.now.isoformat(timespec='microseconds').replace('+00:00','Z'))
        with self.assertRaises(ContractError):self.s.get_artifact('a',as_of=T)
        with self.assertRaises(ContractError):self.artifact('future',known_at=self.now+timedelta(days=1))

    def test_missing_future_self_and_duplicate_dependencies(self):
        for dep in ([{'kind':'artifact','id':'absent'}],[{'kind':'artifact','id':'a'}],[{'kind':'evidence','id':'missing'}],[{'kind':'bogus','id':'x'}]):
            with self.subTest(dep=dep),self.assertRaises(ContractError):self.artifact(deps=dep)
        dep={'kind':'evidence','id':self.ev}
        with self.assertRaises(ContractError):self.artifact(deps=[dep,dep])
        with self.assertRaises(ContractError):self.artifact(dependencies=[])

    def test_raw_dependency_requires_matching_available_evidence(self):
        sha=hashlib.sha256(b'one').hexdigest()
        a=self.artifact(deps=[{'kind':'raw','id':sha,'evidence_id':self.ev}])
        self.assertEqual(a['dependencies'][0]['sha256'],sha)
        with self.assertRaises(ContractError):self.artifact('other',deps=[{'kind':'raw','id':'0'*64,'evidence_id':self.ev}])

    def test_cycle_detected_after_direct_database_corruption(self):
        self.artifact();self.artifact('b',[{'kind':'artifact','id':'a'}])
        row=self.s.db.execute("SELECT * FROM research_artifacts WHERE artifact_id='a'").fetchone()
        dep={'kind':'artifact','id':'b','sha256':'irrelevant','available_at':row['available_at']}
        fields={k:row[k] for k in row.keys() if k!='artifact_sha256'};fields['dependencies_json']=json.dumps([dep])
        self.s.db.execute("UPDATE research_artifacts SET dependencies_json=?,artifact_sha256=? WHERE artifact_id='a'",(fields['dependencies_json'],digest(fields)));self.s.db.commit()
        with self.assertRaises(EvidenceIntegrityError):self.s.get_artifact('a',as_of=T)

    def test_raw_artifact_manifest_and_dependency_corruption_block(self):
        self.artifact()
        sha=hashlib.sha256(b'a').hexdigest()
        self.s.db.execute('UPDATE raw_objects SET payload=? WHERE sha256=?',(b'bad',sha));self.s.db.commit()
        with self.assertRaises(EvidenceIntegrityError):self.s.get_artifact('a',as_of=T)

    def test_backing_evidence_corruption_blocks(self):
        self.artifact();sha=hashlib.sha256(b'one').hexdigest()
        self.s.db.execute('UPDATE raw_objects SET payload=? WHERE sha256=?',(b'bad',sha));self.s.db.commit()
        with self.assertRaises(EvidenceIntegrityError):self.s.get_artifact('a',as_of=T)

    def test_current_revocation_blocks_historical_read(self):
        self.artifact();self.now=T+timedelta(days=1)
        self.s.set_permissions('fixture',known_at=self.now,uses={Use.STORAGE})
        with self.assertRaises(UseNotAllowed):self.s.get_artifact('a',as_of=T)

    def test_incident_transitive_impact_and_observations(self):
        self.artifact();self.artifact('b',[{'kind':'artifact','id':'a'}]);self.artifact('clean',deps=[{'kind':'evidence','id':self.evidence('clean')}])
        self.incident(confirmed=False)
        r=self.s.impact_as_of(as_of=T)
        self.assertEqual(r['incidents'][0]['affected_artifact_ids'],['a','b']);self.assertEqual(r['invalidated_artifact_ids'],[])
        self.incident('confirmed')
        self.assertEqual(self.s.impact_as_of(as_of=T)['invalidated_artifact_ids'],['a','b'])

    def test_forecast_loss_is_not_an_automatic_error(self):
        self.artifact();self.incident(category='forecast_loss')
        self.assertEqual(self.s.impact_as_of(as_of=T)['invalidated_artifact_ids'],[])

    def test_later_incident_does_not_change_earlier_report(self):
        self.artifact();before=self.s.impact_as_of(as_of=T)
        self.now=T+timedelta(days=1);self.incident(known_at=T)
        self.assertEqual(before,self.s.impact_as_of(as_of=T))
        self.assertEqual(self.s.impact_as_of(as_of=self.now)['invalidated_artifact_ids'],['a'])

    def test_correction_appends_and_does_not_rewrite_original(self):
        original=self.artifact();self.incident()
        ev=self.evidence('corrected');self.artifact('replacement',[{'kind':'evidence','id':ev}])
        self.now=T+timedelta(days=1)
        args=dict(correction_id='fix',incident_id='incident',replacement_artifact_id='replacement',known_at=self.now,description='Corrected source and rebuilt')
        result=self.s.record_correction(**args)
        self.assertEqual(result,self.s.record_correction(**args))
        self.assertEqual(self.s.corrections_as_of(as_of=T),[])
        self.assertEqual(len(self.s.corrections_as_of(as_of=self.now)),1)
        self.assertEqual(original,self.s.get_artifact('a',as_of=T))
        self.assertEqual(self.s.impact_as_of(as_of=self.now)['invalidated_artifact_ids'],['a'])
        with self.assertRaises(ContractError):self.s.record_correction(**(args|dict(correction_id='bad',replacement_artifact_id='a')))
        with self.assertRaises(RecordConflict):self.s.record_correction(**(args|dict(description='changed')))

    def test_event_manifest_corruption_detected(self):
        self.artifact();self.incident()
        self.s.db.execute("UPDATE artifact_incidents SET body='{}'");self.s.db.commit()
        with self.assertRaises(EvidenceIntegrityError):self.s.impact_as_of(as_of=T)

    def test_writes_reject_caller_transaction_and_reads_preserve_it(self):
        self.artifact();self.s.db.execute("INSERT INTO entities VALUES ('pending','Pending')")
        with self.assertRaises(ContractError):self.artifact('b')
        with self.assertRaises(ContractError):self.incident()
        self.s.get_artifact('a',as_of=T);self.s.impact_as_of(as_of=T)
        self.assertTrue(self.s.db.in_transaction);self.s.db.rollback()
        self.assertIsNone(self.s.db.execute("SELECT 1 FROM entities WHERE entity_id='pending'").fetchone())

    def test_declared_knowledge_cannot_precede_dependency_availability(self):
        self.artifact();self.now=T+timedelta(days=1);self.artifact('b',[{'kind':'artifact','id':'a'}])
        with self.assertRaises(ContractError):self.artifact('c',[{'kind':'artifact','id':'b'}],known_at=T)

    def test_clock_override_cannot_restore_revoked_research(self):
        self.artifact();self.now=T+timedelta(days=1)
        self.s.set_permissions('fixture',known_at=self.now,uses={Use.STORAGE})
        with self.assertRaises(ContractError):self.s.get_artifact('a',as_of=T,current_at=T)
        with self.assertRaises(ContractError):self.s.get_artifact('a',as_of=T,current_at=self.now+timedelta(days=1))

    def test_evidence_incident_propagates_through_raw_dependency(self):
        sha=hashlib.sha256(b'one').hexdigest()
        self.artifact(deps=[{'kind':'raw','id':sha,'evidence_id':self.ev}]);self.incident()
        self.assertEqual(self.s.impact_as_of(as_of=T)['invalidated_artifact_ids'],['a'])

    def test_audit_read_is_preserved_but_current_invalidity_blocks_usage(self):
        self.artifact();self.now=T+timedelta(days=1);self.incident()
        self.assertEqual(self.s.get_artifact('a',as_of=T)['artifact_id'],'a')
        with self.assertRaises(ContractError):self.s.require_usable_artifact('a',as_of=T)

    def test_correction_reads_preserve_caller_transaction(self):
        self.s.db.execute("INSERT INTO entities VALUES ('pending','Pending')")
        self.assertEqual(self.s.corrections_as_of(as_of=T),[])
        self.assertTrue(self.s.db.in_transaction);self.s.db.rollback()

    def test_demo_repeatable_transitive_impact_and_new_version(self):
        from trading_intelligence.artifacts_demo import artifacts_demo
        root=Path(self.tmp.name)/'demo'
        first=artifacts_demo(root)
        self.assertEqual(first,artifacts_demo(root))
        self.assertEqual(first['before']['invalidated_artifact_ids'],[])
        self.assertEqual(first['after']['invalidated_artifact_ids'],['dataset-v1','features-v1'])
        self.assertEqual(first['corrections'][0]['replacement_artifact_id'],'dataset-v2')
        self.assertFalse(first['training_implemented'])
