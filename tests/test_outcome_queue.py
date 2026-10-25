"""Synthetic delayed-outcome queue regressions; no trained model or real trades."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from trading_intelligence.contracts import ContractError,DataOrigin,EvidenceIntegrityError,RecordConflict,Use,UseNotAllowed
from trading_intelligence.outcome_queue import OutcomeQueueStore, outcomes_demo

T=datetime(2026,1,1,tzinfo=timezone.utc)

class OutcomeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'queue.db'
        self.now=T
        self.s=OutcomeQueueStore(self.path,clock=lambda:self.now)
        self.addCleanup(lambda:self.s.close())
        self.s.register_source('fixture',DataOrigin.SYNTHETIC)
        self.s.set_permissions('fixture',known_at=T-timedelta(days=1),uses={Use.STORAGE,Use.RESEARCH})
        self.feature=self.artifact('features')
        self.definition()

    def artifact(self,name):
        evidence=self.s.ingest(source_id='fixture',record_id=name,revision_id='1',payload=('invented-'+name).encode(),
                               published_at=self.now,received_at=self.now)
        return self.s.register_artifact(artifact_id=name,kind='synthetic_fixture',payload=('artifact-'+name).encode(),
                                        known_at=self.now,dependencies=[{'kind':'evidence','id':evidence}])

    def definition(self,**changes):
        args=dict(definition_id='return',version_id='v1',horizon_seconds=5*86400,target='invented five-day net return',
                  unit='fraction',benchmark='none fixture',price_convention='fixture raw close',
                  cost_convention='fixture zero costs',outcome_origin=DataOrigin.SYNTHETIC)
        args.update(changes);return self.s.record_definition(**args)

    def predict(self,**changes):
        args=dict(prediction_id='p1',definition_id='return',definition_version='v1',strategy_version='rule-v1',
                  policy_version='policy-v1',feature_artifact_id='features',
                  feature_artifact_sha256=self.feature['artifact_sha256'],value=Decimal('0.02'))
        args.update(changes);return self.s.record_prediction(**args)

    def outcome(self,**changes):
        if self.s.db.execute("SELECT 1 FROM sources WHERE source_id='fixture'").fetchone() is None:raise AssertionError()
        validation=self.artifact('validation-'+self.now.isoformat())
        args=dict(outcome_id='o1',prediction_id='p1',status='validated',value=Decimal('0.03'),origin=DataOrigin.SYNTHETIC,
                  validation_artifact_id=validation['artifact_id'],validation_artifact_sha256=validation['artifact_sha256'],
                  reviewer='fixture validator',reason='synthetic verified expected value')
        args.update(changes);return self.s.record_outcome(**args)

    def test_five_day_outcome_cannot_mature_after_one_day(self):
        self.predict();self.now=T+timedelta(days=1)
        with self.assertRaises(ContractError):self.outcome()
        self.assertEqual(self.s.evaluation_labels(as_of=self.now),[])
        self.assertEqual(self.s.queue_as_of(as_of=self.now)[0]['state'],'pending')

    def test_exact_maturity_and_availability_cutoff(self):
        p=self.predict();self.now=T+timedelta(days=5)
        self.outcome()
        self.assertEqual(self.s.evaluation_labels(as_of=self.now-timedelta(microseconds=1)),[])
        labels=self.s.evaluation_labels(as_of=self.now)
        self.assertEqual(len(labels),1);self.assertEqual(labels[0]['outcome']['inputs']['value'],'0.03')
        self.assertFalse(labels[0]['training_ready'])
        self.assertEqual(p['decision_at'],p['known_at'])

    def test_correction_replaces_latest_without_rewriting_old_cutoff(self):
        self.predict();self.now=T+timedelta(days=5);old=self.outcome()
        self.now+=timedelta(days=1)
        self.outcome(outcome_id='o2',value=Decimal('0.04'),correction_of='o1')
        self.assertEqual(len(self.s.evaluation_labels(as_of=self.now)),1)
        self.assertEqual(self.s.evaluation_labels(as_of=self.now)[0]['outcome']['outcome_id'],'o2')
        self.assertEqual(self.s.evaluation_labels(as_of=T+timedelta(days=5))[0]['outcome'],old)

    def test_quarantined_correction_does_not_fall_back_to_old_validated(self):
        self.predict();self.now=T+timedelta(days=5);self.outcome()
        self.now+=timedelta(days=1)
        self.outcome(outcome_id='o2',status='quarantined',value=None,correction_of='o1')
        self.assertEqual(self.s.evaluation_labels(as_of=self.now),[])
        self.assertEqual(self.s.queue_as_of(as_of=self.now)[0]['state'],'quarantined')

    def test_prediction_and_definition_versions_are_locked(self):
        first=self.predict();self.now+=timedelta(hours=1)
        self.assertEqual(first,self.predict())
        with self.assertRaises(RecordConflict):self.predict(value=Decimal('0.8'))
        with self.assertRaises(RecordConflict):self.definition(horizon_seconds=1)
        self.definition(version_id='v2',horizon_seconds=86400)
        self.assertEqual(first['definition']['horizon_seconds'],5*86400)

    def test_restart_preserves_prediction_and_single_label(self):
        self.predict();self.now=T+timedelta(days=5);o=self.outcome()
        self.s.close();self.s=OutcomeQueueStore(self.path,clock=lambda:self.now)
        self.assertEqual(o,self.outcome())
        self.assertEqual(len(self.s.evaluation_labels(as_of=self.now)),1)

    def test_branching_correction_or_replacement_without_lineage_rejected(self):
        self.predict();self.now=T+timedelta(days=5);self.outcome()
        self.now+=timedelta(days=1)
        with self.assertRaises(RecordConflict):self.outcome(outcome_id='o2')
        self.outcome(outcome_id='o2',correction_of='o1')
        self.now+=timedelta(days=1)
        with self.assertRaises(RecordConflict):self.outcome(outcome_id='o3',correction_of='o1')

    def test_unknown_outcome_is_not_zero_and_abstain_is_explicit(self):
        self.predict(action='abstain',value=None)
        self.assertEqual(self.s.queue_as_of(as_of=T)[0]['prediction']['inputs']['action'],'abstain')
        self.now+=timedelta(days=6)
        self.assertEqual(self.s.queue_as_of(as_of=self.now)[0]['state'],'awaiting_outcome')
        self.outcome(status='unavailable',value=None)
        self.assertEqual(self.s.evaluation_labels(as_of=self.now),[])
        with self.assertRaises(ContractError):self.outcome(outcome_id='o2',status='unavailable',value=Decimal(0),correction_of='o1')

    def test_bad_horizons_numbers_and_origin(self):
        for seconds in (0,-1,True,1.5):
            with self.assertRaises(ContractError):self.definition(version_id='bad',horizon_seconds=seconds)
        for value in (0,1.0,'0.1',Decimal('NaN'),Decimal('Infinity')):
            with self.assertRaises(ContractError):self.predict(value=value)
        self.predict();self.now+=timedelta(days=5)
        with self.assertRaises(ContractError):self.outcome(origin=DataOrigin.BROKER)

    def test_future_feature_definition_or_evaluation_cutoff_blocked(self):
        self.now=T+timedelta(days=1);future=self.artifact('future')
        self.definition(version_id='future')
        self.now=T
        with self.assertRaises(ContractError):self.predict(feature_artifact_id='future',feature_artifact_sha256=future['artifact_sha256'])
        with self.assertRaises(ContractError):self.predict(definition_version='future')
        with self.assertRaises(ContractError):self.s.queue_as_of(as_of=T+timedelta(days=1))

    def test_corrupted_payload_or_wrong_artifact_hash_blocks(self):
        with self.assertRaises(EvidenceIntegrityError):self.predict(feature_artifact_sha256='0'*64)
        self.predict()
        self.s.db.execute("UPDATE locked_predictions SET payload='{}'");self.s.db.commit()
        with self.assertRaises(EvidenceIntegrityError):self.s.queue_as_of(as_of=T)

    def test_current_permission_revocation_blocks_old_label_cutoff(self):
        self.predict();self.now+=timedelta(days=5);self.outcome();old=self.now
        self.now+=timedelta(days=1)
        self.s.set_permissions('fixture',known_at=self.now,uses={Use.STORAGE})
        with self.assertRaises(UseNotAllowed):self.s.evaluation_labels(as_of=old)

    def test_read_does_not_commit_open_transaction(self):
        self.predict();self.s.db.execute('BEGIN')
        self.s.db.execute("INSERT INTO entities VALUES ('pending','Pending')")
        self.s.queue_as_of(as_of=T);self.assertTrue(self.s.db.in_transaction)
        self.s.db.rollback()
        self.assertIsNone(self.s.db.execute("SELECT 1 FROM entities WHERE entity_id='pending'").fetchone())

    def test_confirmed_feature_incident_blocks_old_cutoff_and_new_prediction(self):
        self.predict();self.now+=timedelta(days=6)
        self.s.record_incident(incident_id='bad-feature',category='data',known_at=self.now,
            description='invented confirmed feature defect',affected=[{'kind':'artifact','id':'features'}],confirmed=True)
        with self.assertRaises(ContractError):self.s.queue_as_of(as_of=T)
        with self.assertRaises(ContractError):self.predict(prediction_id='p2')

    def test_confirmed_label_artifact_incident_blocks_old_label(self):
        self.predict();self.now+=timedelta(days=5);outcome=self.outcome();cutoff=self.now
        self.now+=timedelta(days=1)
        self.s.record_incident(incident_id='bad-label',category='data',known_at=self.now,
            description='invented confirmed label defect',
            affected=[{'kind':'artifact','id':outcome['inputs']['validation_artifact_id']}],confirmed=True)
        with self.assertRaises(ContractError):self.s.evaluation_labels(as_of=cutoff)

    def test_ordinary_forecast_loss_and_unconfirmed_hypothesis_do_not_invalidate(self):
        self.predict();self.now+=timedelta(days=5);self.outcome()
        for identity,category,confirmed in [('loss','forecast_loss',True),('guess','data',False)]:
            self.s.record_incident(incident_id=identity,category=category,known_at=self.now,
                description='invented outcome investigation',affected=[{'kind':'artifact','id':'features'}],confirmed=confirmed)
        self.assertEqual(len(self.s.evaluation_labels(as_of=self.now)),1)

    def test_repeatable_synthetic_demo(self):
        out=Path(self.tmp.name)/'demo'
        first=outcomes_demo(out)
        self.assertEqual(first,outcomes_demo(out))
        self.assertEqual(first['immature_eligible_count'],0)
        self.assertEqual(first['corrected_eligible_count'],1)
        self.assertEqual(first['old_cutoff_value'],'0.03')
        self.assertEqual(first['corrected_value'],'0.04')

    def test_synthetic_validation_cannot_escalate_to_broker_provider_or_paper_origin(self):
        for index,origin in enumerate((DataOrigin.BROKER,DataOrigin.PROVIDER,DataOrigin.PAPER,DataOrigin.HYPOTHETICAL)):
            self.now=T
            version='origin-'+str(index)
            self.definition(version_id=version,outcome_origin=origin)
            self.predict(prediction_id=version,definition_version=version)
            self.now=T+timedelta(days=5)
            with self.assertRaises(ContractError):
                self.outcome(outcome_id=version,prediction_id=version,origin=origin)

    def test_nested_artifact_cannot_hide_synthetic_outcome_lineage(self):
        self.definition(version_id='broker',outcome_origin=DataOrigin.BROKER)
        self.predict(definition_version='broker')
        self.now=T+timedelta(days=5)
        nested=self.s.register_artifact(artifact_id='nested',kind='claimed_broker',payload=b'invented wrapper',
            known_at=self.now,dependencies=[{'kind':'artifact','id':'features'}])
        with self.assertRaises(ContractError):
            self.outcome(origin=DataOrigin.BROKER,validation_artifact_id='nested',validation_artifact_sha256=nested['artifact_sha256'])

    def test_invalidated_label_can_be_superseded_by_clean_later_material(self):
        self.predict();self.now+=timedelta(days=5);old=self.outcome()
        self.now+=timedelta(days=1)
        self.s.record_incident(incident_id='bad-material',category='data',known_at=self.now,
            description='invented confirmed outcome-material defect',
            affected=[{'kind':'artifact','id':old['inputs']['validation_artifact_id']}],confirmed=True)
        self.now+=timedelta(days=1)
        self.outcome(outcome_id='clean-label',correction_of='o1',value=Decimal('0.05'))
        labels=self.s.evaluation_labels(as_of=self.now)
        self.assertEqual(len(labels),1)
        self.assertEqual(labels[0]['outcome']['outcome_id'],'clean-label')
