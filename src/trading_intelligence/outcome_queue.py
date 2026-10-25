"""Locked predictions and delayed, versioned reviewer-validated outcomes.

This is an offline evaluation queue, not model training or brokerage accounting.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json

from .artifact_registry import ArtifactRegistryStore
from .contracts import ContractError, DataOrigin, EvidenceIntegrityError, RecordConflict, Use, required, utc

SCHEMA = '''
CREATE TABLE IF NOT EXISTS outcome_definitions (
 definition_id TEXT NOT NULL, version_id TEXT NOT NULL, known_at TEXT NOT NULL,
 payload TEXT NOT NULL, sha256 TEXT NOT NULL, PRIMARY KEY(definition_id,version_id));
CREATE TABLE IF NOT EXISTS locked_predictions (
 prediction_id TEXT PRIMARY KEY, known_at TEXT NOT NULL, input_json TEXT NOT NULL,
 payload TEXT NOT NULL, sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS queued_outcomes (
 outcome_id TEXT PRIMARY KEY, prediction_id TEXT NOT NULL REFERENCES locked_predictions,
 known_at TEXT NOT NULL, correction_of TEXT REFERENCES queued_outcomes,
 input_json TEXT NOT NULL, payload TEXT NOT NULL, sha256 TEXT NOT NULL,
 UNIQUE(prediction_id,known_at));
'''


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)


def number(value):
    if not isinstance(value,Decimal) or not value.is_finite():
        raise ContractError('A finite Decimal is required; unknown outcome is not zero')
    return str(value)


class OutcomeQueueStore(ArtifactRegistryStore):
    def __init__(self,database,*,clock=None):
        super().__init__(database,clock=clock)
        self._queue_clock=clock or (lambda:datetime.now(timezone.utc))
        self.db.executescript(SCHEMA)

    def _now(self):
        return utc(self._queue_clock())

    def _idle(self):
        if self.db.in_transaction:
            raise ContractError('Queue writes require an idle connection')

    def _artifact(self,artifact_id,digest,at):
        required(artifact_id,'artifact_id');required(digest,'artifact_sha256')
        artifact=self.require_usable_artifact(artifact_id,as_of=datetime.fromisoformat(at.replace('Z','+00:00')))
        if artifact['artifact_sha256'] != digest:
            raise EvidenceIntegrityError('Queue artifact hash does not match its immutable identity')
        return artifact

    def _validate_origin(self,artifact,origin,at):
        allowed = ({DataOrigin.PROVIDER.value,DataOrigin.HYPOTHETICAL.value}
                   if origin==DataOrigin.HYPOTHETICAL.value else {DataOrigin(origin).value})
        def origins(node,seen):
            identity=node['artifact_id']
            if identity in seen:
                raise EvidenceIntegrityError('Cyclic validation artifact lineage')
            found=set()
            for dependency in node['dependencies']:
                if dependency['kind']=='artifact':
                    child=self.get_artifact(dependency['id'],as_of=datetime.fromisoformat(at.replace('Z','+00:00')))
                    found.update(origins(child,seen|{identity}))
                else:
                    found.add(dependency['origin'])
            return found
        actual=origins(artifact,set())
        if not actual or not actual<=allowed:
            raise ContractError('Validation lineage origin cannot be promoted to requested outcome origin')
        return sorted(actual)

    def _verified(self,row):
        if row is None:
            raise ContractError('Queue record is unknown or not available at cutoff')
        if hashlib.sha256(row['payload'].encode()).hexdigest()!=row['sha256']:
            raise EvidenceIntegrityError('Queue payload hash mismatch')
        body=json.loads(row['payload'])
        if body['known_at']!=row['known_at']:
            raise EvidenceIntegrityError('Queue availability index mismatch')
        for key in ('definition_id','version_id','prediction_id','outcome_id','correction_of'):
            if key in row.keys() and body.get(key)!=row[key]:
                raise EvidenceIntegrityError('Queue identity index mismatch')
        return body

    def record_definition(self,*,definition_id,version_id,horizon_seconds,target,unit,
                          benchmark,price_convention,cost_convention,outcome_origin):
        self._idle()
        for name,value in [('definition_id',definition_id),('version_id',version_id),('target',target),
                           ('unit',unit),('benchmark',benchmark),('price_convention',price_convention),
                           ('cost_convention',cost_convention)]:required(value,name)
        if type(horizon_seconds) is not int or not 0<horizon_seconds<=315360000:
            raise ContractError('Explicit positive elapsed-second horizon up to ten years required')
        origin=DataOrigin(outcome_origin).value
        inputs=dict(definition_id=definition_id,version_id=version_id,horizon_seconds=horizon_seconds,
                    target=target,unit=unit,benchmark=benchmark,price_convention=price_convention,
                    cost_convention=cost_convention,outcome_origin=origin)
        old=self.db.execute('SELECT * FROM outcome_definitions WHERE definition_id=? AND version_id=?',
                            (definition_id,version_id)).fetchone()
        if old:
            body=self._verified(old)
            if {k:v for k,v in body.items() if k!='known_at'}!=inputs:
                raise RecordConflict('Outcome definition versions are immutable')
            return body
        body=dict(inputs,known_at=self._now());payload=canonical(body)
        with self.db:
            self.db.execute('INSERT INTO outcome_definitions VALUES (?,?,?,?,?)',
                            (definition_id,version_id,body['known_at'],payload,hashlib.sha256(payload.encode()).hexdigest()))
        return body

    def _prediction(self,prediction_id,at):
        row=self.db.execute('SELECT * FROM locked_predictions WHERE prediction_id=? AND known_at<=?',
                            (prediction_id,at)).fetchone()
        body=self._verified(row)
        if row['input_json']!=canonical(body['inputs']):
            raise EvidenceIntegrityError('Prediction input index mismatch')
        self._artifact(body['inputs']['feature_artifact_id'],body['inputs']['feature_artifact_sha256'],body['known_at'])
        return body

    def record_prediction(self,*,prediction_id,definition_id,definition_version,strategy_version,
                          policy_version,feature_artifact_id,feature_artifact_sha256,value,action='forecast'):
        self._idle()
        for name,v in [('prediction_id',prediction_id),('strategy_version',strategy_version),('policy_version',policy_version)]:required(v,name)
        required(action,'action')
        if action not in {'forecast','abstain'} or (action=='abstain' and value is not None):
            raise ContractError('Use forecast with Decimal or explicit abstain with None')
        inputs=dict(definition_id=definition_id,definition_version=definition_version,
                    strategy_version=strategy_version,policy_version=policy_version,
                    feature_artifact_id=feature_artifact_id,feature_artifact_sha256=feature_artifact_sha256,
                    value=number(value) if action=='forecast' else None,action=action)
        now=self._now()
        old=self.db.execute('SELECT * FROM locked_predictions WHERE prediction_id=?',(prediction_id,)).fetchone()
        if old:
            body=self._prediction(prediction_id,now)
            if inputs!=body['inputs']:
                raise RecordConflict('Prediction is locked; retry inputs differ')
            return body
        definition=self._verified(self.db.execute('SELECT * FROM outcome_definitions WHERE definition_id=? '
                                  'AND version_id=? AND known_at<=?',(definition_id,definition_version,now)).fetchone())
        self._artifact(feature_artifact_id,feature_artifact_sha256,now)
        decision=datetime.fromisoformat(now.replace('Z','+00:00'))
        end=utc(decision+timedelta(seconds=definition['horizon_seconds']))
        body=dict(prediction_id=prediction_id,known_at=now,decision_at=now,label_end=end,inputs=inputs,
                  definition=definition)
        payload=canonical(body)
        with self.db:
            self.db.execute('INSERT INTO locked_predictions VALUES (?,?,?,?,?)',
                            (prediction_id,now,canonical(inputs),payload,hashlib.sha256(payload.encode()).hexdigest()))
        return body

    def record_outcome(self,*,outcome_id,prediction_id,status,value,origin,validation_artifact_id,
                       validation_artifact_sha256,reviewer,reason,correction_of=None):
        self._idle()
        for name,v in [('outcome_id',outcome_id),('prediction_id',prediction_id),('reviewer',reviewer),('reason',reason)]:required(v,name)
        required(status,'status')
        if status not in {'validated','unavailable','quarantined'}:
            raise ContractError('Explicit validated/unavailable/quarantined status required')
        if status!='validated' and value is not None:
            raise ContractError('Unavailable/quarantined outcomes have no numeric label')
        inputs=dict(prediction_id=prediction_id,status=status,value=number(value) if status=='validated' else None,
                    origin=DataOrigin(origin).value,validation_artifact_id=validation_artifact_id,
                    validation_artifact_sha256=validation_artifact_sha256,reviewer=reviewer,reason=reason,
                    correction_of=correction_of)
        now=self._now();prediction=self._prediction(prediction_id,now)
        validation=self._artifact(validation_artifact_id,validation_artifact_sha256,now)
        self._validate_origin(validation,inputs['origin'],now)
        if inputs['origin']!=prediction['definition']['outcome_origin']:
            raise ContractError('Outcome origin differs from its frozen target definition')
        old=self.db.execute('SELECT * FROM queued_outcomes WHERE outcome_id=?',(outcome_id,)).fetchone()
        if old:
            body=self._outcome(old)
            if body['inputs']!=inputs:
                raise RecordConflict('Outcome revision is immutable')
            return body
        if status=='validated' and now<prediction['label_end']:
            raise ContractError('The outcome horizon has not matured')
        previous=self.db.execute('SELECT * FROM queued_outcomes WHERE prediction_id=? ORDER BY known_at DESC LIMIT 1',
                                 (prediction_id,)).fetchone()
        if previous:
            prior=self._outcome_record(previous)
            if correction_of!=prior['outcome_id'] or prior['known_at']>=now:
                raise RecordConflict('A correction must supersede the latest label at a later time')
        elif correction_of is not None:
            raise ContractError('First outcome cannot refer to a missing predecessor')
        body=dict(outcome_id=outcome_id,prediction_id=prediction_id,known_at=now,
                  outcome_available_at=now,label_end=prediction['label_end'],correction_of=correction_of,inputs=inputs)
        payload=canonical(body)
        with self.db:
            self.db.execute('INSERT INTO queued_outcomes VALUES (?,?,?,?,?,?,?)',
                            (outcome_id,prediction_id,now,correction_of,canonical(inputs),payload,hashlib.sha256(payload.encode()).hexdigest()))
        return body

    def _outcome_record(self,row):
        body=self._verified(row)
        if row['input_json']!=canonical(body['inputs']):
            raise EvidenceIntegrityError('Outcome input index mismatch')
        return body

    def _outcome(self,row):
        body=self._outcome_record(row)
        validation=self._artifact(body['inputs']['validation_artifact_id'],body['inputs']['validation_artifact_sha256'],body['known_at'])
        self._validate_origin(validation,body['inputs']['origin'],body['known_at'])
        return body

    def queue_as_of(self,*,as_of):
        at=utc(as_of)
        if at>self._now():raise ContractError('Future evaluation cutoff is not allowed')
        self.db.execute('SAVEPOINT outcome_queue_read')
        try:
            result=[]
            for row in self.db.execute('SELECT prediction_id FROM locked_predictions WHERE known_at<=? ORDER BY prediction_id',(at,)):
                p=self._prediction(row['prediction_id'],at)
                label_row=self.db.execute('SELECT * FROM queued_outcomes WHERE prediction_id=? AND known_at<=? '
                                          'ORDER BY known_at DESC LIMIT 1',(row['prediction_id'],at)).fetchone()
                label=self._outcome(label_row) if label_row else None
                state=('pending' if at<p['label_end'] else 'awaiting_outcome') if label is None else label['inputs']['status']
                eligible=label is not None and label['inputs']['status']=='validated' and at>=p['label_end']
                result.append(dict(prediction=p,outcome=label,state=state,eligible_for_evaluation=eligible,
                                   training_ready=False))
        except BaseException:
            self.db.execute('ROLLBACK TO outcome_queue_read');self.db.execute('RELEASE outcome_queue_read');raise
        else:
            self.db.execute('RELEASE outcome_queue_read');return result

    def evaluation_labels(self,*,as_of):
        """At most one matured latest revision per prediction; no training permission."""
        return [x for x in self.queue_as_of(as_of=as_of) if x['eligible_for_evaluation']]


def outcomes_demo(directory):
    """Repeatable synthetic prediction -> delayed label -> correction example."""
    from pathlib import Path
    path=Path(directory);path.mkdir(parents=True,exist_ok=True)
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    clock=[start]
    with OutcomeQueueStore(path/'outcomes.sqlite',clock=lambda:clock[0]) as store:
        store.register_source('outcome-fixture',DataOrigin.SYNTHETIC)
        store.set_permissions('outcome-fixture',known_at=start,uses={Use.STORAGE,Use.RESEARCH})
        def artifact(identity):
            evidence=store.ingest(source_id='outcome-fixture',record_id=identity,revision_id='1',
                                  payload=('invented '+identity).encode(),published_at=clock[0],received_at=clock[0])
            return store.register_artifact(artifact_id=identity,kind='synthetic_fixture',
                                          payload=('artifact '+identity).encode(),known_at=clock[0],
                                          dependencies=[{'kind':'evidence','id':evidence}])
        feature=artifact('demo-features')
        store.record_definition(definition_id='demo-return',version_id='v1',horizon_seconds=5*86400,
            target='invented five elapsed-calendar-day return',unit='fraction',benchmark='none fixture',
            price_convention='invented raw close',cost_convention='zero fixture costs',outcome_origin=DataOrigin.SYNTHETIC)
        prediction=store.record_prediction(prediction_id='demo-prediction',definition_id='demo-return',
            definition_version='v1',strategy_version='fixture-rule-v1',policy_version='fixture-policy-v1',
            feature_artifact_id=feature['artifact_id'],feature_artifact_sha256=feature['artifact_sha256'],value=Decimal('0.02'))
        clock[0]=start+timedelta(days=1)
        immature=store.evaluation_labels(as_of=clock[0])
        clock[0]=start+timedelta(days=5)
        validation=artifact('demo-validation')
        store.record_outcome(outcome_id='demo-label-v1',prediction_id='demo-prediction',status='validated',
            value=Decimal('0.03'),origin=DataOrigin.SYNTHETIC,validation_artifact_id=validation['artifact_id'],
            validation_artifact_sha256=validation['artifact_sha256'],reviewer='fixture-validator',reason='invented outcome')
        first=store.evaluation_labels(as_of=clock[0])
        old_cutoff=clock[0]
        clock[0]=start+timedelta(days=6)
        correction=artifact('demo-correction-validation')
        store.record_outcome(outcome_id='demo-label-v2',prediction_id='demo-prediction',status='validated',
            value=Decimal('0.04'),origin=DataOrigin.SYNTHETIC,validation_artifact_id=correction['artifact_id'],
            validation_artifact_sha256=correction['artifact_sha256'],reviewer='fixture-validator',
            reason='invented corrected outcome',correction_of='demo-label-v1')
        latest=store.evaluation_labels(as_of=clock[0])
        old=store.evaluation_labels(as_of=old_cutoff)
        report=dict(synthetic=True,prediction_id=prediction['prediction_id'],immature_eligible_count=len(immature),
                    matured_eligible_count=len(first),corrected_eligible_count=len(latest),
                    old_cutoff_value=old[0]['outcome']['inputs']['value'],
                    corrected_value=latest[0]['outcome']['inputs']['value'],
                    training_implemented=False,training_ready=False,live_trading=False)
    (path/'outcomes-report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report
