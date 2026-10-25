"""Synthetic append-only artifact, incident and correction example."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .artifact_registry import ArtifactRegistryStore
from .contracts import DataOrigin, Use


def artifacts_demo(directory: Path) -> dict:
    directory.mkdir(parents=True,exist_ok=True)
    first=datetime(2026,1,1,tzinfo=timezone.utc)
    later=first+timedelta(days=1)
    clock=[first]
    with ArtifactRegistryStore(directory/'artifacts.sqlite3',clock=lambda:clock[0]) as store:
        store.register_source('synthetic-artifacts',DataOrigin.SYNTHETIC)
        store.set_permissions('synthetic-artifacts',known_at=first,uses={Use.STORAGE,Use.RESEARCH})
        original=store.ingest(source_id='synthetic-artifacts',record_id='source',revision_id='1',
            payload=b'{"invented_value":1}',published_at=first,received_at=first)
        dataset=store.register_artifact(artifact_id='dataset-v1',kind='dataset',payload=b'{"invented_dataset":1}',
            known_at=first,dependencies=[{'kind':'evidence','id':original}])
        features=store.register_artifact(artifact_id='features-v1',kind='features',payload=b'{"invented_features":1}',
            known_at=first,dependencies=[{'kind':'artifact','id':'dataset-v1'}])
        before=store.impact_as_of(as_of=first)
        clock[0]=later
        corrected=store.ingest(source_id='synthetic-artifacts',record_id='source',revision_id='2',
            payload=b'{"invented_value":2}',published_at=later,received_at=later,correction_of=original)
        rebuilt=store.register_artifact(artifact_id='dataset-v2',kind='dataset',payload=b'{"invented_dataset":2}',
            known_at=later,dependencies=[{'kind':'evidence','id':corrected}])
        store.record_incident(incident_id='source-correction',category='data',known_at=later,
            description='Invented source correction',affected=[{'kind':'evidence','id':original}],confirmed=True)
        store.record_correction(correction_id='rebuilt-v2',incident_id='source-correction',
            replacement_artifact_id='dataset-v2',known_at=later,description='New immutable dataset from corrected source')
        after=store.impact_as_of(as_of=later)
        return {'origin':DataOrigin.SYNTHETIC.value,
            'artifact_hashes':{x['artifact_id']:x['artifact_sha256'] for x in (dataset,features,rebuilt)},
            'before':before,'after':after,'corrections':store.corrections_as_of(as_of=later),
            'training_implemented':False,'live_trading':False,'orders_sent':0}
