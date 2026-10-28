"""Part 1: frozen synthetic hedge intents, reusing canonical broker contracts."""
from datetime import datetime,timedelta
from decimal import Decimal
import json

from .contracts import ContractError, RecordConflict, EvidenceIntegrityError, required, utc
from .event_analysis import canonical, digest, _write_locked, _read_snapshot
from .hedge_reservations import HedgeReservationStore
from .event_opportunity import instant
from .brokers import BrokerAccount, Environment, InstrumentTarget, TargetKind, OrderIntent, Side, client_order_id

SCHEMA='''CREATE TABLE IF NOT EXISTS hedge_sim_intents (
 intent_id TEXT PRIMARY KEY,reservation_id TEXT NOT NULL UNIQUE,body TEXT NOT NULL,sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS hedge_sim_controls (
 control_id TEXT PRIMARY KEY,route_key TEXT NOT NULL,available_at TEXT NOT NULL,body TEXT NOT NULL,sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS hedge_sim_events (
 event_id TEXT PRIMARY KEY,intent_id TEXT NOT NULL,sequence INTEGER NOT NULL,body TEXT NOT NULL,sha256 TEXT NOT NULL,
 UNIQUE(intent_id,sequence));'''

class HedgeIntentStore(HedgeReservationStore):
    def __init__(self,database,*,clock=None):
        super().__init__(database,clock=clock);self.db.executescript(SCHEMA)

    @_read_snapshot
    def intent(self,intent_id):
        row=self.db.execute('SELECT * FROM hedge_sim_intents WHERE intent_id=?',(intent_id,)).fetchone()
        if row is None:return None
        body=json.loads(row['body'])
        if (digest(body)!=row['sha256'] or body['intent_id']!=row['intent_id']
                or body['reservation_id']!=row['reservation_id'] or body['available_at']>utc(self._event_clock())):
            raise EvidenceIntegrityError('Synthetic intent manifest integrity failed')
        return body

    @_write_locked
    def create_intent(self,intent_id,reservation_id):
        required(intent_id,'intent_id')
        old=self.intent(intent_id)
        if old:
            if old['reservation_id']!=reservation_id:raise RecordConflict('Intent ID already bound')
            return old
        if self.db.execute('SELECT 1 FROM hedge_sim_intents WHERE reservation_id=?',(reservation_id,)).fetchone():
            raise RecordConflict('Reservation already bound to one synthetic intent')
        check=self.reservation_readiness(reservation_id)
        if check['status']!='inputs_current_for_research':raise ContractError('Current reservation research inputs required')
        reserved=self.reservation(reservation_id)
        search=self.get_search(reserved['search_id'],as_of=self._event_clock())
        if digest(search)!=reserved['search_sha256']:raise EvidenceIntegrityError('Search binding changed')
        if search['evidence']['origin']!='synthetic_fixture':raise ContractError('Synthetic input evidence required')
        raw,_=self._inputs(search['evidence_id'],search['as_of'],utc(self._event_clock()))
        alternative=next(x for x in search['result']['alternatives'] if x['alternative_id']==reserved['alternative_id'])
        route=alternative['route']
        if route['environment']!='paper':raise ContractError('Only synthetic paper routes supported')
        account=BrokerAccount(route['broker'],route['connection'],route['account'],Environment.PAPER)
        candidate=alternative['candidate_id'];ref=raw['market_references'][candidate]
        terms,terms_id=self.terms_as_of(alternative['contract_id'],effective_at=self._event_clock(),as_of=self._event_clock())
        if terms_id not in {x.get('snapshot_id') for x in search['futures_references']}:
            raise ContractError('Current contract terms changed; create new research inputs')
        now=utc(self._event_clock());quantity=int(alternative['size'])
        original=self.get_assessment(search['opportunity_id'],as_of=self._event_clock())
        exposure,_=self._inputs(original['evidence_id'],original['as_of'],now)
        analysis=self.analysis_as_of(original['analysis_id'],as_of=self._event_clock())
        age_limit=lambda value:utc(datetime.fromisoformat(instant(value).replace('Z','+00:00'))+timedelta(seconds=60))
        expiry=min(instant(raw['controls']['valid_until']),instant(ref['valid_until']),utc(terms.entry_cutoff_at),
            instant(exposure['valid_until']),instant(exposure['portfolio']['valid_until']),analysis['expires_at'],
            age_limit(ref['observed_at']),age_limit(exposure['quote_at']),age_limit(raw['controls']['state_observed_at']))
        until=datetime.fromisoformat(expiry.replace('Z','+00:00'))
        intent=OrderIntent(intent_id,search['result']['policy_id'],InstrumentTarget(TargetKind.FUTURE,alternative['contract_id']),
            Side.BUY if quantity>0 else Side.SELL,Decimal(abs(quantity)),Decimal(ref['entry_price']),self._event_clock(),until)
        body=dict(intent_id=intent_id,reservation_id=reservation_id,reservation_sha256=digest(reserved),
            search_id=search['search_id'],search_sha256=digest(search),route=route,contract_id=intent.target.internal_id,
            signed_quantity=quantity,limit_price=str(intent.limit_price),tick_size=str(terms.tick_size),
            strategy_id=intent.strategy_id,side=intent.side.value,time_in_force=intent.time_in_force.value,
            session=intent.session.value,price_kind=intent.price_kind.value,decision_at=utc(intent.decision_at),
            multiplier=str(terms.multiplier),terms_snapshot_id=terms_id,available_at=now,valid_until=utc(until),
            client_order_id=client_order_id(account.key,intent_id),origin='synthetic_fixture',
            broker_orders_sent=0,execution_authorized=False)
        if utc(self._event_clock())>=body['valid_until'] or self.reservation_readiness(reservation_id)['blockers']:
            raise ContractError('Intent inputs expired during preparation')
        body['available_at']=utc(self._event_clock())
        if body['available_at']>=body['valid_until']:raise ContractError('Intent expired during preparation')
        self.db.execute('INSERT INTO hedge_sim_intents VALUES (?,?,?,?)',(intent_id,reservation_id,canonical(body),digest(body)))
        return body
