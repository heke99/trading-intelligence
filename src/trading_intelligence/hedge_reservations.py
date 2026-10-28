"""Atomic LOCAL RESEARCH reservations. Never broker margin or live allocations."""
import json
from decimal import Decimal, localcontext

from .contracts import ContractError, EvidenceIntegrityError, RecordConflict, required, utc
from .event_analysis import canonical, digest, _write_locked, _read_snapshot
from .hedge_research import HedgeResearchStore

SCHEMA = '''CREATE TABLE IF NOT EXISTS hedge_research_reservations (
 reservation_id TEXT NOT NULL, sequence INTEGER NOT NULL,
 body_json TEXT NOT NULL, sha256 TEXT NOT NULL,
 PRIMARY KEY(reservation_id,sequence));'''


class HedgeReservationStore(HedgeResearchStore):
    def __init__(self, database, *, clock=None):
        super().__init__(database,clock=clock)
        self.db.executescript(SCHEMA)

    def _ledger(self, cutoff=None):
        current=utc(self._event_clock())
        states={}
        visible={}
        for row in self.db.execute('SELECT * FROM hedge_research_reservations ORDER BY reservation_id,sequence'):
            body=json.loads(row['body_json'])
            identity=row['reservation_id']
            prior=states.get(identity)
            if (digest(body)!=row['sha256'] or body['reservation_id']!=identity
                    or body['sequence']!=row['sequence'] or body['available_at']>current
                    or body['sequence']!=(0 if prior is None else 1)
                    or body['state']!=('reserved' if prior is None else 'released')
                    or (prior and (prior['state']!='reserved'
                        or body['previous_sha256']!=digest(prior)
                        or body['available_at']<prior['available_at']))):
                raise EvidenceIntegrityError('Local reservation journal integrity failed')
            states[identity]=body
            if cutoff is None or body['available_at']<=cutoff:
                visible[identity]=body
        return visible

    @_write_locked
    def reserve(self,reservation_id,search_id,alternative_id):
        required(reservation_id,'reservation_id')
        states=self._ledger()
        if reservation_id in states:
            old=states[reservation_id]
            if (old['search_id'],old['alternative_id'])!=(search_id,alternative_id):
                raise RecordConflict('Reservation ID already identifies another draft')
            return old
        now=utc(self._event_clock())
        search=self.get_search(search_id,as_of=self._event_clock())
        if search is None:raise ContractError('Available hedge research required')
        raw,_,_,_,blockers,_=self._validate(search['opportunity_id'],search['evidence_id'],search['as_of'],now)
        if blockers:raise ContractError('Current hedge evidence/policy blocks reservation')
        rows=[x for x in search['result']['alternatives'] if x['alternative_id']==alternative_id]
        if len(rows)!=1 or not rows[0]['feasible'] or rows[0]['kind']!='futures_hedge':
            raise ContractError('Feasible futures research alternative required')
        alternative=rows[0]
        route=alternative['route']
        currency=raw['inputs']['book']['currency']
        cash=next((x for x in raw['inputs']['hedge_accounts'] if x['route']==route and x['currency']==currency),None)
        if cash is None:raise ContractError('Exact-account free cash required')
        # Reject mixed vintages: this is a shared conservative draft budget, not
        # an account reconciliation engine able to infer net available funds.
        cash_basis=dict(route=route,currency=currency,available_cash=cash['available_cash'],
                        observed_at=raw['controls']['state_observed_at'])
        exposure_keys=[dict(route=raw['inputs']['book']['route'],listing_id=x)
                       for x in sorted(raw['controls']['protected_listing_ids'])]
        active=[x for x in states.values() if x['state']=='reserved']
        with localcontext() as context:
            context.prec=128
            used=Decimal(0)
            for old in active:
                if any(key in old['exposure_keys'] for key in exposure_keys):
                    raise ContractError('Protected listing already reserved by another research draft')
                if old['cash_basis']['route']==route and old['cash_basis']['currency']==currency:
                    if old['cash_basis']!=cash_basis:
                        raise ContractError('Active drafts require the same cash snapshot; reconcile local drafts first')
                    used+=Decimal(old['reserved_cash'])
            amount=Decimal(alternative['stressed_cash_required'])
            if used+amount>Decimal(cash['available_cash']):
                raise ContractError('Combined local hedge reservations exceed free cash')
        completed=utc(self._event_clock())
        if completed<now:raise ContractError('Operational clock moved backwards')
        if self._validate(search['opportunity_id'],search['evidence_id'],search['as_of'],completed)[4]:
            raise ContractError('Evidence expired during local reservation')
        body=dict(reservation_id=reservation_id,sequence=0,state='reserved',search_id=search_id,
            alternative_id=alternative_id,search_sha256=digest(search),available_at=completed,
            cash_basis=cash_basis,reserved_cash=str(amount),exposure_keys=exposure_keys,
            previous_sha256=None,local_research_only=True,orders_sent=0,execution_authorized=False)
        self.db.execute('INSERT INTO hedge_research_reservations VALUES (?,?,?,?)',
            (reservation_id,0,canonical(body),digest(body)))
        return body

    @_write_locked
    def release(self,reservation_id,*,reason):
        if reason not in ('abandoned_research','superseded_research'):
            raise ContractError('Explicit local research release reason required')
        old=self._ledger().get(reservation_id)
        if old is None:raise ContractError('Unknown reservation')
        if old['state']=='released':
            if old['release_reason']!=reason:raise RecordConflict('Release reason already fixed')
            return old
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='hedge_sim_intents'").fetchone():
            linked=self.db.execute('SELECT intent_id FROM hedge_sim_intents WHERE reservation_id=?',(reservation_id,)).fetchone()
            allowed=getattr(self,'_research_release_allowed',lambda _identity:False)
            if linked and not allowed(linked['intent_id']):
                raise ContractError('Bound synthetic intent must be abandoned before local research release; dispatched exposure remains locked')
        body={**old,'sequence':1,'state':'released','available_at':utc(self._event_clock()),
              'previous_sha256':digest(old),'release_reason':reason}
        self.db.execute('INSERT INTO hedge_research_reservations VALUES (?,?,?,?)',
            (reservation_id,1,canonical(body),digest(body)))
        return body

    @_read_snapshot
    def reservation(self,reservation_id):
        return self._ledger().get(reservation_id)

    @_read_snapshot
    def reservation_as_of(self,reservation_id,*,as_of):
        """Return only knowledge available at cutoff; still verify the full journal."""
        required(reservation_id,'reservation_id')
        at,_=self._times(as_of)
        return self._ledger(at).get(reservation_id)

    @_read_snapshot
    def reservation_readiness(self,reservation_id):
        """Fresh RESEARCH-input check, never permission to dispatch an order.

        Unlike idempotent reserve(), this operation always uses the current clock.
        It does not renew evidence, release a claim or rewrite historical checks.
        """
        required(reservation_id,'reservation_id')
        now=utc(self._event_clock())
        reservation=self._ledger().get(reservation_id)
        if reservation is None:raise ContractError('Unknown research reservation')
        blockers=[]
        if reservation['state']!='reserved':
            blockers.append('reservation_released')
        else:
            try:
                search=self.get_search(reservation['search_id'],as_of=self._event_clock())
                if search is None or digest(search)!=reservation['search_sha256']:
                    raise EvidenceIntegrityError('Reservation search dependency changed')
                blockers.extend(self._validate(search['opportunity_id'],search['evidence_id'],
                                               search['as_of'],now)[4])
            except EvidenceIntegrityError:
                blockers.append('dependency_integrity_failure')
            except ContractError:
                # Current revocations/missing references never revive old approval.
                # Keep provider evidence and error bodies out of this metadata check.
                blockers.append('dependency_unavailable_or_not_permitted')
            except (ValueError,TypeError,KeyError):
                blockers.append('dependency_integrity_failure')
        completed=utc(self._event_clock())
        if completed<now:raise ContractError('Operational clock moved backwards')
        # Validity can elapse while dependency verification is running.
        if reservation['state']=='reserved' and not blockers:
            try:
                blockers.extend(self._validate(search['opportunity_id'],search['evidence_id'],
                                               search['as_of'],completed)[4])
            except EvidenceIntegrityError:
                blockers.append('dependency_integrity_failure')
            except ContractError:
                blockers.append('dependency_unavailable_or_not_permitted')
            except (ValueError,TypeError,KeyError):
                blockers.append('dependency_integrity_failure')
        return dict(reservation_id=reservation_id,reservation_sha256=digest(reservation),
            evaluated_at=completed,reservation_state=reservation['state'],
            status='blocked' if blockers else 'inputs_current_for_research',
            blockers=sorted(set(blockers)),check_is_not_a_risk_approval=True,
            live_account_state_verified=False,execution_authorized=False,orders_sent=0)
