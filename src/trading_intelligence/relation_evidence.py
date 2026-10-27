"""Synthetic-only, reviewer-declared temporal relation evidence.

No LLM, graph database, inferred causality, forecasts or trading authority.
Reuses the existing immutable artifact, rights and incident implementation.
"""
import json
from .artifact_registry import ArtifactRegistryStore, canonical
from .contracts import ContractError, DataOrigin, required, utc

KIND = 'synthetic_reviewed_relation_v1'
RELATIONS = {'supplies_to', 'customer_of', 'consolidated_by', 'competitor_of'}


class RelationEvidenceStore(ArtifactRegistryStore):
    def _body(self, identity, at):
        artifact = self.require_usable_artifact(identity, as_of=at)
        if artifact['kind'] != KIND:
            raise ContractError('Not a relation artifact')
        return artifact, json.loads(artifact['payload'])

    def record_relation(self, *, version_id, relation_id, source_entity_id,
                        target_entity_id, relation_type, evidence_id, span_start,
                        span_end, quote, valid_from, valid_until, known_at,
                        reviewer, affirmed=True, replaces=None):
        self._idle()
        for key, value in (('relation_id', relation_id), ('reviewer', reviewer),
                           ('source_entity_id', source_entity_id), ('target_entity_id', target_entity_id)):
            required(value, key)
        if relation_type not in RELATIONS or type(affirmed) is not bool:
            raise ContractError('Explicit supported relation and review status required')
        if source_entity_id == target_entity_id:
            raise ContractError('Self relation unsupported')
        for entity in (source_entity_id, target_entity_id):
            if not self.db.execute('SELECT 1 FROM entities WHERE entity_id=?', (entity,)).fetchone():
                raise ContractError('Registered entity identity required')
        start, end = utc(valid_from), None if valid_until is None else utc(valid_until)
        if end is not None and end <= start:
            raise ContractError('Positive half-open validity interval required')
        known = utc(known_at)
        now = self._artifact_clock()
        # Resolve through the existing archive/rights validator before decoding.
        dep = self._dependency({'kind': 'evidence', 'id': evidence_id}, known, utc(now), set())
        if dep['origin'] != DataOrigin.SYNTHETIC.value:
            raise ContractError('This bounded relation proof supports synthetic evidence only')
        raw = self.db.execute('SELECT payload FROM raw_objects WHERE sha256=?', (dep['sha256'],)).fetchone()[0]
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise ContractError('Strict UTF-8 source text required') from exc
        if (type(span_start) is not int or type(span_end) is not int
                or not 0 <= span_start < span_end <= len(text)
                or not isinstance(quote, str) or not quote.strip()
                or text[span_start:span_end] != quote):
            raise ContractError('Exact nonempty source span required; no ungrounded extraction')
        identity = (relation_id, source_entity_id, target_entity_id, relation_type)
        # Check the entire version family; do not hide conflicting future records.
        family = []
        for row in self.db.execute('SELECT artifact_id FROM research_artifacts WHERE kind=?', (KIND,)).fetchall():
            a, body = self._body(row[0], now)
            if body['relation_id'] == relation_id:
                if tuple(body[k] for k in ('relation_id','source_entity_id','target_entity_id','relation_type')) != identity:
                    raise ContractError('Relation identity changed')
                family.append((a, body))
        existing = next(((a,b) for a,b in family if a['artifact_id'] == version_id), None)
        if replaces is not None:
            previous, old = self._body(replaces, now)
            if old['relation_id'] != relation_id or known <= previous['known_at']:
                raise ContractError('Replacement needs earlier knowledge in same relation')
        elif family and existing is None:
            raise ContractError('Existing relation needs explicit replacement')
        if existing is None and family:
            referenced = {b['replaces'] for _,b in family if b['replaces']}
            heads = [a for a,_ in family if a['artifact_id'] not in referenced]
            if len(heads) != 1 or replaces != heads[0]['artifact_id']:
                raise ContractError('Replacement must extend the unique current version')
        body = dict(relation_id=relation_id, source_entity_id=source_entity_id,
                    target_entity_id=target_entity_id, relation_type=relation_type,
                    evidence_id=evidence_id, span_start=span_start, span_end=span_end,
                    quote=quote, valid_from=start, valid_until=end, reviewer=reviewer,
                    affirmed=affirmed, replaces=replaces, semantic_review='declared_not_verified')
        return self.register_artifact(artifact_id=version_id, kind=KIND,
                    payload=canonical(body).encode(), known_at=known_at,
                    dependencies=[{'kind':'evidence','id':evidence_id}])

    def relations_as_of(self, *, as_of, effective_at):
        at, _ = self._times(as_of)
        effective = utc(effective_at)
        families = {}
        # Future records are excluded before lineage selection, not before validity.
        for row in self.db.execute('SELECT artifact_id FROM research_artifacts WHERE kind=? AND available_at<=?',
                                   (KIND, at)).fetchall():
            artifact, body = self._body(row[0], as_of)
            families.setdefault(body['relation_id'], []).append((artifact, body))
        result = []
        for versions in families.values():
            replaced = {b['replaces'] for _,b in versions if b['replaces']}
            heads = [(a,b) for a,b in versions if a['artifact_id'] not in replaced]
            if len(heads) != 1:
                raise ContractError('Ambiguous relation lineage')
            artifact, body = heads[0]
            if (body['affirmed'] and body['valid_from'] <= effective
                    and (body['valid_until'] is None or effective < body['valid_until'])):
                result.append({**body, 'version_id':artifact['artifact_id'],
                               'available_at':artifact['available_at'],
                               'artifact_sha256':artifact['artifact_sha256']})
        return dict(synthetic=True, relations=sorted(result, key=lambda x:x['relation_id']),
                    research_admitted=False, forecast_implemented=False, orders=0)
