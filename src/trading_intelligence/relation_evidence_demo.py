"""Invented-data relation proof; no source access or order generation."""
from datetime import datetime, timedelta, timezone
import json
from .contracts import DataOrigin, Entity, Use
from .relation_evidence import RelationEvidenceStore


def run():
    t=datetime(2026,1,1,tzinfo=timezone.utc); clock=[t]
    with RelationEvidenceStore(':memory:',clock=lambda:clock[0]) as s:
        s.register_source('invented',DataOrigin.SYNTHETIC)
        s.set_permissions('invented',known_at=t,uses={Use.STORAGE,Use.RESEARCH})
        for identity in ('invented-A','invented-B'): s.register_entity(Entity(identity,identity))
        text='Invented A supplies invented B.'
        ev=s.ingest(source_id='invented',record_id='document',revision_id='1',payload=text.encode(),published_at=t,received_at=t)
        args=dict(relation_id='supply-1',source_entity_id='invented-A',target_entity_id='invented-B',
            relation_type='supplies_to',evidence_id=ev,span_start=0,span_end=len(text),quote=text,
            valid_from=t,valid_until=None,reviewer='invented-reviewer')
        s.record_relation(version_id='v1',known_at=t,**args)
        clock[0]=t+timedelta(days=2)
        s.record_relation(version_id='v2',known_at=clock[0],replaces='v1',
                          **{**args,'valid_until':t+timedelta(days=1)})
        def summary(at):
            report=s.relations_as_of(as_of=at,effective_at=t+timedelta(days=1))
            # Evidence UUIDs differ between fresh stores; compare semantic output.
            report['relations']=[{k:v for k,v in row.items() if k not in {'evidence_id','artifact_sha256'}} for row in report['relations']]
            return report
        return dict(synthetic=True, old_knowledge=summary(t),
                    corrected_knowledge=summary(clock[0]),
                    orders=0, llm_extraction_implemented=False)


if __name__=='__main__':
    print(json.dumps(run(),sort_keys=True,indent=2))
