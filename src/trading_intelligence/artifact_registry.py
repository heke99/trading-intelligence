"""Append-only local artifact lineage and incident observations; no model execution."""
from datetime import datetime, timezone
import hashlib
import json

from .contracts import ContractError, EvidenceIntegrityError, RecordConflict, Use, required, utc
from .store import EvidenceStore

SCHEMA = '''
CREATE TABLE IF NOT EXISTS research_artifacts (
 artifact_id TEXT PRIMARY KEY, kind TEXT NOT NULL, content_sha256 TEXT NOT NULL REFERENCES raw_objects,
 known_at TEXT NOT NULL, recorded_at TEXT NOT NULL, available_at TEXT NOT NULL,
 dependencies_json TEXT NOT NULL, artifact_sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS artifact_incidents (
 incident_id TEXT PRIMARY KEY, body TEXT NOT NULL, available_at TEXT NOT NULL, sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS artifact_corrections (
 correction_id TEXT PRIMARY KEY, body TEXT NOT NULL, available_at TEXT NOT NULL, sha256 TEXT NOT NULL);
'''
CATEGORIES = {'data','extraction','execution','policy','forecast_loss'}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class ArtifactRegistryStore(EvidenceStore):
    def __init__(self, database, *, clock=None):
        super().__init__(database)
        self.db.executescript(SCHEMA)
        self._artifact_clock = clock or (lambda: datetime.now(timezone.utc))

    def _idle(self):
        if self.db.in_transaction:
            raise ContractError('Registry writes require an idle connection')

    def _times(self, as_of, current_at=None):
        at = utc(as_of)
        current = utc(self._artifact_clock())
        if current_at is not None and utc(current_at) != current:
            raise ContractError('Explicit current cutoff must match the operational clock')
        if at > current:
            raise ContractError('As-of cutoff cannot exceed current clock')
        return at, current

    def _dependency(self, dep, at, current, seen):
        if not isinstance(dep, dict) or not isinstance(dep.get('kind'), str) or dep['kind'] not in {'evidence','raw','artifact'}:
            raise ContractError('Typed evidence/raw/artifact dependency required')
        kind = dep['kind']; identity = required(dep.get('id'), 'dependency id')
        expected = {'kind','id','evidence_id'} if kind == 'raw' else {'kind','id'}
        if set(dep) != expected:
            raise ContractError('Unexpected dependency fields')
        if kind == 'artifact':
            artifact = self._get(identity, at, current, seen)
            return {**dep, 'sha256':artifact['artifact_sha256'], 'available_at':artifact['available_at']}
        evidence_id = identity if kind == 'evidence' else required(dep['evidence_id'], 'evidence_id')
        row = self.db.execute('SELECT e.*,r.payload,s.origin FROM evidence_versions e JOIN raw_objects r USING(sha256) JOIN sources s USING(source_id) WHERE evidence_id=?', (evidence_id,)).fetchone()
        if row is None or row['received_at'] > at:
            raise ContractError('Backing evidence is missing or unavailable')
        if row['published_at'] > row['received_at']:
            raise EvidenceIntegrityError('Inconsistent evidence times')
        for cutoff in (at,current):
            self._require_use(row['source_id'], Use.RESEARCH, cutoff)
        if hashlib.sha256(row['payload']).hexdigest() != row['sha256']:
            raise EvidenceIntegrityError('Artifact backing raw evidence is corrupt')
        if kind == 'raw' and identity != row['sha256']:
            raise ContractError('Raw dependency does not match its evidence')
        return {**dep, **{k:row[k] for k in ('source_id','origin','record_id','revision_id','received_at','published_at','correction_of')}, 'sha256':row['sha256']}

    def register_artifact(self, *, artifact_id, kind, payload, known_at, dependencies):
        self._idle(); required(artifact_id,'artifact_id'); required(kind,'kind')
        if not isinstance(payload,bytes) or not payload:
            raise ContractError('Nonempty original artifact bytes required')
        if not isinstance(dependencies,list) or not dependencies:
            raise ContractError('At least one typed dependency required')
        recorded = utc(self._artifact_clock()); known = utc(known_at)
        if known > recorded:
            raise ContractError('Declared artifact knowledge cannot be in the future')
        # Dependency knowledge cannot exceed the declared artifact knowledge.
        resolved = [self._dependency(x,known,recorded,{artifact_id}) for x in dependencies]
        resolved.sort(key=canonical)
        if len({canonical(x) for x in resolved}) != len(resolved):
            raise ContractError('Duplicate dependencies are not allowed')
        sha = hashlib.sha256(payload).hexdigest()
        semantic = dict(artifact_id=artifact_id,kind=kind,content_sha256=sha,known_at=known,dependencies_json=canonical(resolved))
        old = self.db.execute('SELECT * FROM research_artifacts WHERE artifact_id=?',(artifact_id,)).fetchone()
        if old:
            if any(old[k] != v for k,v in semantic.items()):
                raise RecordConflict('Artifact ID already identifies another immutable version')
            return self.get_artifact(artifact_id,as_of=self._artifact_clock())
        fields = {**semantic,'recorded_at':recorded,'available_at':recorded}
        fields['artifact_sha256'] = digest(fields)
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO raw_objects VALUES (?,?)',(sha,payload))
            if self.db.execute('SELECT payload FROM raw_objects WHERE sha256=?',(sha,)).fetchone()[0] != payload:
                raise EvidenceIntegrityError('Stored artifact bytes are corrupt')
            self._immutable('research_artifacts',{'artifact_id':artifact_id},fields)
        return self.get_artifact(artifact_id,as_of=self._artifact_clock())

    def _get(self, artifact_id, at, current, seen):
        if artifact_id in seen:
            raise EvidenceIntegrityError('Artifact dependency cycle detected')
        row = self.db.execute('SELECT * FROM research_artifacts WHERE artifact_id=?',(artifact_id,)).fetchone()
        if row is None or row['available_at'] > at:
            raise ContractError('Artifact missing or unavailable at cutoff')
        fields = {k:row[k] for k in row.keys() if k != 'artifact_sha256'}
        if digest(fields) != row['artifact_sha256'] or row['known_at'] > row['recorded_at'] or row['available_at'] != row['recorded_at']:
            raise EvidenceIntegrityError('Artifact manifest integrity failed')
        raw = self.db.execute('SELECT payload FROM raw_objects WHERE sha256=?',(row['content_sha256'],)).fetchone()
        if raw is None or hashlib.sha256(raw[0]).hexdigest() != row['content_sha256']:
            raise EvidenceIntegrityError('Artifact bytes integrity failed')
        deps = json.loads(row['dependencies_json'])
        for dep in deps:
            reference = {k:dep[k] for k in ('kind','id','evidence_id') if k in dep}
            actual = self._dependency(reference,row['known_at'],current,seen|{artifact_id})
            if actual != dep:
                raise EvidenceIntegrityError('Artifact dependency binding changed')
        return {**fields,'artifact_sha256':row['artifact_sha256'],'dependencies':deps,'payload':raw[0]}

    def get_artifact(self, artifact_id, *, as_of, current_at=None):
        required(artifact_id,'artifact_id'); at,current=self._times(as_of,current_at)
        self.db.execute('SAVEPOINT artifact_registry_read')
        try:
            result=self._get(artifact_id,at,current,set())
        except BaseException:
            self.db.execute('ROLLBACK TO artifact_registry_read');self.db.execute('RELEASE artifact_registry_read');raise
        else:
            self.db.execute('RELEASE artifact_registry_read');return result

    def _event(self,table,key,identity,semantic,now):
        old=self.db.execute(f'SELECT * FROM {table} WHERE {key}=?',(identity,)).fetchone()
        if old:
            body=json.loads(old['body'])
            if any(body.get(k)!=v for k,v in semantic.items()):
                raise RecordConflict('Event ID already identifies another event')
            self._verify_event(old)
            if old['available_at']>now:raise ContractError('Event is not available at current clock')
            return body
        body={**semantic,'recorded_at':now,'available_at':now}
        with self.db:
            self.db.execute(f'INSERT INTO {table} VALUES (?,?,?,?)',(identity,canonical(body),now,digest(body)))
        return body

    def _verify_event(self,row):
        body=json.loads(row['body'])
        if digest(body)!=row['sha256'] or body['available_at']!=row['available_at']:
            raise EvidenceIntegrityError('Incident/correction journal integrity failed')
        return body

    def record_incident(self, *, incident_id, category, known_at, description, affected, confirmed=False):
        self._idle();required(incident_id,'incident_id');required(description,'description')
        if not isinstance(category,str) or category not in CATEGORIES or type(confirmed) is not bool:
            raise ContractError('Explicit incident category and confirmation flag required')
        now=utc(self._artifact_clock());known=utc(known_at)
        if known>now:raise ContractError('Incident knowledge is in the future')
        if not isinstance(affected,list) or not affected:raise ContractError('Affected references required')
        refs=[self._dependency(x,known,now,set()) for x in affected];refs.sort(key=canonical)
        if len({canonical(x) for x in refs})!=len(refs):raise ContractError('Duplicate affected reference')
        semantic=dict(incident_id=incident_id,category=category,known_at=known,description=description,
                      affected=refs,confirmed=confirmed,invalidates=confirmed and category!='forecast_loss')
        return self._event('artifact_incidents','incident_id',incident_id,semantic,now)

    def impact_as_of(self, *, as_of, current_at=None):
        at,current=self._times(as_of,current_at)
        self.db.execute('SAVEPOINT artifact_impact_read')
        try:
            incidents=[self._verify_event(r) for r in self.db.execute('SELECT * FROM artifact_incidents WHERE available_at<=? ORDER BY incident_id',(at,))]
            artifacts={r[0]:self._get(r[0],at,current,set()) for r in self.db.execute('SELECT artifact_id FROM research_artifacts WHERE available_at<=? ORDER BY artifact_id',(at,))}
            impacts=[]
            for incident in incidents:
                roots=incident['affected'];affected=set()
                for ref in roots:
                    request={k:ref[k] for k in ('kind','id','evidence_id') if k in ref}
                    if self._dependency(request,incident['known_at'],current,set())!=ref:
                        raise EvidenceIntegrityError('Incident dependency changed')
                    if ref['kind']=='artifact':affected.add(ref['id'])
                changed=True
                while changed:
                    changed=False
                    for identity,artifact in artifacts.items():
                        if identity in affected:continue
                        for dep in artifact['dependencies']:
                            direct=any((dep['kind']==r['kind'] and dep['id']==r['id']) or
                                       (r['kind']=='raw' and dep['kind'] in {'raw','evidence'} and dep['sha256']==r['id']) or
                                       (r['kind']=='evidence' and dep['kind']=='raw' and dep.get('evidence_id')==r['id']) for r in roots)
                            if direct or (dep['kind']=='artifact' and dep['id'] in affected):
                                affected.add(identity);changed=True;break
                impacts.append(dict(incident_id=incident['incident_id'],category=incident['category'],
                                    invalidates=incident['invalidates'],affected_artifact_ids=sorted(affected)))
            result=dict(as_of=at,incidents=impacts,invalidated_artifact_ids=sorted({x for i in impacts if i['invalidates'] for x in i['affected_artifact_ids']}),training_implemented=False,live_trading=False)
        except BaseException:
            self.db.execute('ROLLBACK TO artifact_impact_read');self.db.execute('RELEASE artifact_impact_read');raise
        else:
            self.db.execute('RELEASE artifact_impact_read');return result

    def record_correction(self, *, correction_id, incident_id, replacement_artifact_id, known_at, description):
        self._idle();required(correction_id,'correction_id');required(description,'description')
        now=utc(self._artifact_clock());known=utc(known_at)
        if known>now:raise ContractError('Correction knowledge is in the future')
        row=self.db.execute('SELECT * FROM artifact_incidents WHERE incident_id=? AND available_at<=?',(incident_id,known)).fetchone()
        if row is None:raise ContractError('Correction needs an available original incident')
        self._verify_event(row)
        replacement=self.get_artifact(replacement_artifact_id,as_of=known_at)
        impacts=self.impact_as_of(as_of=known_at)
        impacted=next(x['affected_artifact_ids'] for x in impacts['incidents'] if x['incident_id']==incident_id)
        if replacement_artifact_id in impacted:raise ContractError('Replacement still depends on affected lineage')
        semantic=dict(correction_id=correction_id,incident_id=incident_id,replacement_artifact_id=replacement_artifact_id,
                      replacement_sha256=replacement['artifact_sha256'],known_at=known,description=description)
        return self._event('artifact_corrections','correction_id',correction_id,semantic,now)

    def require_usable_artifact(self, artifact_id, *, as_of):
        """Block confirmed current invalidation; still not data/model admission."""
        artifact=self.get_artifact(artifact_id,as_of=as_of)
        impact=self.impact_as_of(as_of=self._artifact_clock())
        if artifact_id in impact['invalidated_artifact_ids']:
            raise ContractError('Artifact has confirmed affected lineage')
        return artifact

    def corrections_as_of(self, *, as_of, current_at=None):
        at,current=self._times(as_of,current_at)
        self.db.execute('SAVEPOINT artifact_corrections_read')
        try:
            result=[]
            for row in self.db.execute('SELECT * FROM artifact_corrections WHERE available_at<=? ORDER BY correction_id',(at,)):
                body=self._verify_event(row)
                incident=self.db.execute('SELECT * FROM artifact_incidents WHERE incident_id=? AND available_at<=?',(body['incident_id'],body['known_at'])).fetchone()
                if incident is None:
                    raise EvidenceIntegrityError('Correction lost original incident')
                self._verify_event(incident)
                replacement=self._get(body['replacement_artifact_id'],body['known_at'],current,set())
                if replacement['artifact_sha256']!=body['replacement_sha256']:
                    raise EvidenceIntegrityError('Correction replacement binding changed')
                result.append(body)
        except BaseException:
            self.db.execute('ROLLBACK TO artifact_corrections_read');self.db.execute('RELEASE artifact_corrections_read');raise
        else:
            self.db.execute('RELEASE artifact_corrections_read');return result
