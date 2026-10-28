"""Synthetic-only LEAN execution/ledger engineering trial. No broker transport."""
from AlgorithmImports import *
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path

from trading_intelligence.baseline import close_above_mean
from trading_intelligence.baseline_fixture import verify_fixture
from trading_intelligence.lean_smoke_templates import engine_utc, delivery_utc, backtest_window
from trading_intelligence.market_data import timestamp

FIXTURE=None
DIRECTORY=None


class SyntheticPrice(PythonData):
    def get_source(self,config,date,is_live_mode):
        if is_live_mode:raise ValueError('Synthetic backtest only')
        if str(config.data_time_zone) not in ('UTC','Etc/UTC'):raise ValueError('UTC data required')
        return SubscriptionDataSource(str(Path(DIRECTORY)/'prices.jsonl'),SubscriptionTransportMedium.LOCAL_FILE)

    def reader(self,config,line,date,is_live_mode):
        if is_live_mode:raise ValueError('Synthetic backtest only')
        row=json.loads(line)
        if row not in FIXTURE['events']:raise ValueError('Unknown synthetic price event')
        point=SyntheticPrice();point.symbol=config.symbol
        point.time=delivery_utc(row['available_at']).replace(tzinfo=None);point.end_time=point.time
        point.value=float(row['price'])
        point['event_json']=line
        return point


class BaselineFixtureSmoke(QCAlgorithm):
    def initialize(self):
        global FIXTURE,DIRECTORY
        if self.live_mode:raise ValueError('Live mode forbidden')
        path=Path(self.get_parameter('fixture_path'));DIRECTORY=str(path.parent)
        FIXTURE=json.loads(path.read_text());verify_fixture(path.parent,FIXTURE)
        self.set_time_zone(TimeZones.UTC)
        window=backtest_window([e['available_at'] for e in FIXTURE['events']])
        if not window['replayable']:raise ValueError('Synthetic observation day is not closed')
        self.set_start_date(*map(int,window['requested_start_date'].split('-')))
        self.set_end_date(*map(int,window['requested_end_date'].split('-')))
        if engine_utc(self.end_date)<max(timestamp(e['available_at']) for e in FIXTURE['events']):
            raise ValueError('Actual engine window excludes fixture')
        self.set_cash(float(FIXTURE['initial_cash']));self.set_benchmark(lambda _:1)
        security=self.add_data(SyntheticPrice,'SYNTHETIC_BASELINE',Resolution.MINUTE,TimeZones.UTC,False,1)
        security.is_tradable=True
        security.set_fill_model(ImmediateFillModel())
        costs=FIXTURE['baseline']['semantic']['costs']
        security.set_fee_model(ConstantFeeModel(float(costs['commission_per_order']),'USD'))
        rate=(Decimal(costs['spread_bps'])/2+Decimal(costs['slippage_bps']))/10000
        security.set_slippage_model(ConstantSlippageModel(float(rate)))
        self._symbol=security.symbol;self._history=[];self._seen=[];self._decisions=[]
        self._fills=[];self._submissions=[];self._pending=None;self._active=None

    def on_data(self,data):
        if not data.contains_key(self._symbol):return
        row=json.loads(str(data[self._symbol]['event_json']))
        now=engine_utc(self.utc_time)
        if now<timestamp(row['available_at']):raise ValueError('Early synthetic event')
        if len(self._seen)>=len(FIXTURE['events']) or row!=FIXTURE['events'][len(self._seen)]:
            raise ValueError('Synthetic stream ordering mismatch')
        self._seen.append(row)
        if row['kind']=='open':
            if self._pending is None:return
            intent=self._pending['intent']
            if row['date']!=intent['session_date'] or now!=timestamp(intent['intended_at']) or now<timestamp(intent['not_before']):
                raise ValueError('Order would miss its exact next-session intention')
            target=int(self._pending['target_weight'])*FIXTURE['max_position_units']
            current=Decimal(str(self.portfolio[self._symbol].quantity))
            if current!=int(current):raise ValueError('Fractional fixture position unsupported')
            delta=target-int(current)
            if delta:
                if self._active is not None:raise ValueError('Prior order unresolved')
                self._active=dict(decision_date=self._pending['date'],occurred_at=intent['intended_at'],quantity=str(delta))
                self._submissions.append(dict(self._active))
                ticket=self.market_order(self._symbol,delta,tag='synthetic-baseline-fixture')
                if ticket.status!=OrderStatus.FILLED or self._active is not None:
                    raise ValueError('Fixture requires one immediate complete engine fill')
            self._pending=None
            return
        self._history.append(dict(date=row['date'],close=row['price'],available_at=row['available_at']))
        bounds=FIXTURE['experiment']['semantic']['partitions']['validation']
        if not bounds['start']<=row['date']<=bounds['end']:return
        contract=FIXTURE['baseline']['semantic'];lookback=contract['lookback']
        reason=None;intent=None;target=None
        if len(self._history)<lookback:reason='warmup'
        else:
            ready=timestamp(row['available_at'])+timedelta(seconds=contract['costs']['latency_seconds'])
            sessions=FIXTURE['sessions'];index=next(i for i,s in enumerate(sessions) if s['date']==row['date'])
            following=sessions[index+1] if index+1<len(sessions) else None
            if following is None:reason='no_next_declared_session'
            elif timestamp(following['known_at'])>now:reason='next_session_calendar_unavailable'
            elif timestamp(following['start'])<ready:reason='missed_next_session_open'
            elif following['date']>bounds['end']:reason='outside_evaluation_partition'
            else:
                target=close_above_mean([r['close'] for r in self._history[-lookback:]])
                from trading_intelligence.contracts import utc
                intent=dict(type='next_session_open_target',session_date=following['date'],not_before=utc(ready),
                    intended_at=following['start'],target_weight=target,is_fill=False,is_order_authorization=False)
        decision=dict(date=row['date'],decision_at=row['available_at'],action='abstain' if reason else 'target',
            target_weight=target,reason=reason,intent=intent)
        self._decisions.append(decision)
        if intent is not None:self._pending=decision

    def on_order_event(self,event):
        if event.symbol!=self._symbol:raise ValueError('Unexpected fixture symbol')
        if event.status in (OrderStatus.INVALID,OrderStatus.CANCELED,OrderStatus.PARTIALLY_FILLED):
            raise ValueError('Unexpected incomplete/rejected fixture order')
        if event.status!=OrderStatus.FILLED:return
        if self._active is None:raise ValueError('Unrequested engine fill')
        occurred=engine_utc(event.utc_time);observed=engine_utc(self.utc_time)
        if occurred!=timestamp(self._active['occurred_at']) or observed!=occurred:
            raise ValueError('Engine fill time differs from exact intended session')
        if Decimal(str(event.fill_quantity))!=Decimal(self._active['quantity']):
            raise ValueError('Unexpected engine fill quantity')
        self._fills.append(dict(self._active,order_id=int(event.order_id),
            occurred_at=occurred.isoformat(),observed_at=observed.isoformat(),
            quantity=str(event.fill_quantity),price=str(event.fill_price),
            fee=str(event.order_fee.value.amount),currency=str(event.order_fee.value.currency)))
        self._active=None

    def on_end_of_algorithm(self):
        summary=dict(schema='synthetic-lean-baseline-result-1',synthetic=True,
            status='completed',decisions=self._decisions,fills=self._fills,submissions=self._submissions,
            seen_events=self._seen,engine_order_count=int(self.transactions.orders_count),
            engine_cash=str(self.portfolio.cash),engine_position=str(self.portfolio[self._symbol].quantity),
            unresolved_intent=self._pending,unresolved_order=self._active,
            real_dataset_admitted=False,training_ready=False,live_trading=False)
        path=Path(self.get_parameter('result_path'));path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(summary,sort_keys=True,indent=2)+'\n')
