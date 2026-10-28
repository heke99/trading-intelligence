"""Part 2: latest supplied synthetic route controls; never broker risk approval."""
import json
from .contracts import ContractError,EvidenceIntegrityError,RecordConflict,required,utc
from .event_analysis import canonical,digest,_write_locked,_read_snapshot
from .event_opportunity import fields,instant
from .hedge_math import route_key
from .hedge_intents import HedgeIntentStore

class HedgeControlStore(HedgeIntentStore):
    @_write_locked
    def record_controls(self,control_id,evidence_id):
        required(control_id,'control_id');now=utc(self._event_clock())
        raw,binding=self._inputs(evidence_id,now,now)
        if binding['origin']!='synthetic_fixture':raise ContractError('Synthetic control evidence required')
        fields(raw,('route','mode','observed_at','expires_at','max_contracts','allowed_contract_ids','policy_version'))
        route=canonical(route_key(raw['route']))
        if raw['route']['environment']!='paper' or raw['mode'] not in ('active','paused','hard_stop'):
            raise ContractError('Explicit synthetic paper route/mode required')
        required(raw['policy_version'],'policy_version')
        if type(raw['max_contracts']) is not int or not 0<=raw['max_contracts']<=100:
            raise ContractError('Bounded contract limit required')
        ids=raw['allowed_contract_ids']
        if not isinstance(ids,list) or not ids or any(not isinstance(x,str) or not x for x in ids) or len(set(ids))!=len(ids):
            raise ContractError('Exact contract identities required')
        if instant(raw['observed_at'])>now or instant(raw['expires_at'])<=now:
            raise ContractError('Current control validity required')
        old=self.db.execute('SELECT * FROM hedge_sim_controls WHERE control_id=?',(control_id,)).fetchone()
        if old:
            body=self._control(old)
            if body['evidence_id']!=evidence_id:raise RecordConflict('Control ID already bound')
            return body
        latest=self.db.execute('SELECT available_at FROM hedge_sim_controls WHERE route_key=? ORDER BY available_at DESC LIMIT 1',(route,)).fetchone()
        if latest and latest[0]>=now:raise ContractError('New route control needs a later processing time')
        now=utc(self._event_clock())
        if instant(raw['expires_at'])<=now:raise ContractError('Controls expired during processing')
        self._inputs(evidence_id,now,now)
        body=dict(control_id=control_id,evidence_id=evidence_id,evidence=binding,route_key=route,
            available_at=now,controls=raw,origin='synthetic_fixture')
        self.db.execute('INSERT INTO hedge_sim_controls VALUES (?,?,?,?,?)',(control_id,route,now,canonical(body),digest(body)))
        return body

    def _control(self,row):
        body=json.loads(row['body'])
        if digest(body)!=row['sha256'] or any(body[k]!=row[k] for k in ('control_id','route_key','available_at')):
            raise EvidenceIntegrityError('Control manifest integrity failed')
        _,binding=self._inputs(body['evidence_id'],body['available_at'],utc(self._event_clock()))
        if binding!=body['evidence']:raise EvidenceIntegrityError('Control evidence changed')
        return body

    @_read_snapshot
    def dispatch_check(self,intent_id):
        intent=self.intent(intent_id)
        if intent is None:raise ContractError('Unknown synthetic intent')
        now=utc(self._event_clock());blockers=[]
        readiness=self.reservation_readiness(intent['reservation_id'])
        blockers.extend(readiness['blockers'])
        now=utc(self._event_clock())
        search=self.get_search(intent['search_id'],as_of=self._event_clock())
        for ref in search['futures_references']:
            if 'snapshot_id' not in ref:continue
            prior=self.db.execute('SELECT kind,target_id FROM futures_snapshots WHERE snapshot_id=?',(ref['snapshot_id'],)).fetchone()
            current=self._get(prior['kind'],prior['target_id'],effective_at=self._event_clock(),as_of=self._event_clock())
            if current.snapshot_id!=ref['snapshot_id']:blockers.append('current_futures_reference_changed')
        if now>=intent['valid_until']:blockers.append('intent_expired')
        route=canonical(route_key(intent['route']))
        row=self.db.execute('SELECT * FROM hedge_sim_controls WHERE route_key=? ORDER BY available_at DESC LIMIT 1',(route,)).fetchone()
        control=None
        if row is None:blockers.append('route_controls_missing')
        else:
            control=self._control(row);policy=control['controls']
            if control['available_at']>now or instant(policy['observed_at'])>now or instant(policy['expires_at'])<=now:
                blockers.append('route_controls_unavailable_or_expired')
            if policy['mode']!='active':blockers.append('route_controls_stop')
            if abs(intent['signed_quantity'])>policy['max_contracts']:blockers.append('route_quantity_limit')
            if intent['contract_id'] not in policy['allowed_contract_ids']:blockers.append('route_contract_not_allowed')
        return dict(intent_id=intent_id,intent_sha256=digest(intent),evaluated_at=now,
            control_sha256=None if control is None else digest(control),
            valid_until=min(intent['valid_until'],instant(control['controls']['expires_at'])) if control else intent['valid_until'],blockers=sorted(set(blockers)),
            synthetic_dispatch_eligible=not blockers,execution_authorized=False,broker_orders_sent=0)
