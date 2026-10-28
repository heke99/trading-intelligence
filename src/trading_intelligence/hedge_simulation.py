"""Part 3: durable synthetic callback fault harness, NOT an order engine.

No sockets, broker adapters or external submissions. Quantities are authored test
observations, not brokerage fills. LEAN remains the strategy engine boundary.
"""
from decimal import Decimal
import json
from .contracts import ContractError,RecordConflict,EvidenceIntegrityError,required,utc
from .event_analysis import canonical,digest,_write_locked,_read_snapshot
from .hedge_controls import HedgeControlStore
from .event_opportunity import number

class HedgeSimulationStore(HedgeControlStore):
    def _events(self,intent):
        events=[];previous=None
        for row in self.db.execute('SELECT * FROM hedge_sim_events WHERE intent_id=? ORDER BY sequence',(intent['intent_id'],)):
            body=json.loads(row['body'])
            if (digest(body)!=row['sha256'] or body['event_id']!=row['event_id']
                    or body['sequence']!=row['sequence'] or body['sequence']!=len(events)
                    or body['intent_id']!=intent['intent_id'] or body['intent_sha256']!=digest(intent)
                    or body['previous_sha256']!=previous or body['available_at']>utc(self._event_clock())
                    or body['available_at']<(events[-1]['available_at'] if events else intent['available_at'])):
                raise EvidenceIntegrityError('Synthetic callback journal integrity failed')
            events.append(body);previous=digest(body)
        return events

    @_read_snapshot
    def simulation_state(self,intent_id):
        intent=self.intent(intent_id)
        if intent is None:raise ContractError('Unknown synthetic intent')
        events=self._events(intent)
        filled=events[-1]['cumulative_filled'] if events else 0
        return dict(intent_id=intent_id,state=events[-1]['state'] if events else 'draft',
            cumulative_filled=filled,signed_filled=filled*(1 if intent['signed_quantity']>0 else -1),
            remaining=abs(intent['signed_quantity'])-filled,event_count=len(events),
            simulated_dispatch_count=sum(x['kind']=='dispatch_claimed' for x in events),
            broker_orders_sent=0,origin='synthetic_fixture',live_trading=False)

    def _append(self,intent,event_id,kind,cumulative,state,price=None,check=None):
        events=self._events(intent)
        body=dict(event_id=event_id,intent_id=intent['intent_id'],intent_sha256=digest(intent),
            sequence=len(events),kind=kind,cumulative_filled=cumulative,state=state,fill_price=price,
            dispatch_check=check,available_at=utc(self._event_clock()),previous_sha256=digest(events[-1]) if events else None,
            origin='synthetic_fixture',broker_orders_sent=0)
        self.db.execute('INSERT INTO hedge_sim_events VALUES (?,?,?,?,?)',(event_id,intent['intent_id'],len(events),canonical(body),digest(body)))
        return body

    @_write_locked
    def claim_dispatch(self,intent_id):
        intent=self.intent(intent_id)
        if intent is None:raise ContractError('Unknown synthetic intent')
        events=self._events(intent)
        if events:
            if events[0]['kind']=='dispatch_claimed':return events[0]
            raise ContractError('Abandoned synthetic intent cannot be sent')
        check=self.dispatch_check(intent_id)
        if utc(self._event_clock())>=check['valid_until']:raise ContractError('Synthetic dispatch validity elapsed during checking')
        if not check['synthetic_dispatch_eligible']:raise ContractError('Current synthetic dispatch check blocked')
        # Durable claim and unknown status are atomic. Restart cannot resubmit.
        return self._append(intent,'dispatch:'+intent_id,'dispatch_claimed',0,'unknown',check=check)

    @_write_locked
    def inject(self,intent_id,event_id,kind,*,cumulative_filled=None,fill_price=None):
        required(event_id,'event_id')
        if event_id.startswith(('dispatch:','abandon:')):raise ContractError('Callback ID uses an internal journal namespace')
        if kind not in ('accepted','fill','unknown','cancelled','rejected'):raise ContractError('Unknown synthetic callback kind')
        intent=self.intent(intent_id)
        if intent is None:raise ContractError('Unknown synthetic intent')
        events=self._events(intent)
        if not events or events[0]['kind']!='dispatch_claimed':raise ContractError('Durable synthetic dispatch claim required')
        old=self.db.execute('SELECT * FROM hedge_sim_events WHERE event_id=?',(event_id,)).fetchone()
        if old:
            body=json.loads(old['body'])
            if digest(body)!=old['sha256']:raise EvidenceIntegrityError('Callback integrity failed')
            if (body['intent_id'],body['kind'],body['cumulative_filled'] if kind=='fill' else None,body['fill_price'])!=(intent_id,kind,cumulative_filled,fill_price):
                raise RecordConflict('Callback ID already identifies different data')
            return body
        previous=events[-1];filled=previous['cumulative_filled'];total=abs(intent['signed_quantity'])
        terminal=previous['state'] in ('filled','cancelled','rejected','cancelled_with_late_fill','rejected_with_late_fill')
        if kind=='fill':
            if type(cumulative_filled) is not int or not filled<cumulative_filled<=total:
                raise ContractError('New cumulative fill must increase within the requested quantity')
            price=number(fill_price,positive=True);tick=Decimal(intent['tick_size'])
            a,b=price.as_integer_ratio();c,d=tick.as_integer_ratio()
            if (a*d)%(b*c):raise ContractError('Synthetic fill is off tick')
            limit=Decimal(intent['limit_price'])
            if (intent['signed_quantity']>0 and price>limit) or (intent['signed_quantity']<0 and price<limit):
                raise ContractError('Synthetic fill violates limit price')
            filled=cumulative_filled
            state='filled' if filled==total else ('rejected_with_late_fill' if previous['state'].startswith('rejected') else 'cancelled_with_late_fill') if terminal else 'partial'
        else:
            if cumulative_filled is not None or fill_price is not None:raise ContractError('Only fill callbacks carry fill data')
            state=previous['state'] if terminal else ('partial' if filled else 'open') if kind=='accepted' else kind
        # Stops/expired source rights never discard a late callback observation.
        return self._append(intent,event_id,kind,filled,state,price=fill_price)

    @_write_locked
    def abandon(self,intent_id):
        intent=self.intent(intent_id)
        if intent is None:raise ContractError('Unknown synthetic intent')
        events=self._events(intent)
        if events:
            if events[0]['kind']=='draft_abandoned':return events[0]
            raise ContractError('Dispatched/unknown/filled intents cannot be abandoned as drafts')
        return self._append(intent,'abandon:'+intent_id,'draft_abandoned',0,'abandoned')

    def _research_release_allowed(self,intent_id):
        return self.simulation_state(intent_id)['state']=='abandoned'
