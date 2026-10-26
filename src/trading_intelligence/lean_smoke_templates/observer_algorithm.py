"""Observation-only synthetic custom-data smoke. No market/broker subscriptions."""
from AlgorithmImports import *
from datetime import timedelta
from pathlib import Path
import json
from trading_intelligence.lean_export import verify_bundle
from trading_intelligence.lean_custom_data import parse_bundle_line
from trading_intelligence.market_data import timestamp
from trading_intelligence.lean_smoke_templates import engine_utc

BUNDLE=None
DIRECTORY=None
INSPECTION=False
GROUPS=[]

class ObservedFixture(PythonData):
    def get_source(self,config,date,is_live_mode):
        if is_live_mode:raise ValueError('Live mode forbidden')
        if str(config.data_time_zone) not in ('UTC','Etc/UTC'):raise ValueError('UTC data timezone required')
        if INSPECTION:
            from trading_intelligence.captured_observations import verify_inspection
            current=json.loads((Path(DIRECTORY)/'inspection.json').read_text())
            verify_inspection(current)
            if current!=BUNDLE:raise ValueError('Inspection bundle changed')
        elif verify_bundle(DIRECTORY)!=BUNDLE:raise ValueError('Bundle changed')
        return SubscriptionDataSource(str(Path(DIRECTORY)/('groups.jsonl' if INSPECTION else 'bars.csv')),SubscriptionTransportMedium.LOCAL_FILE)

    def reader(self,config,line,date,is_live_mode):
        if is_live_mode:raise ValueError('Live mode forbidden')
        if INSPECTION:
            group=json.loads(line)
            if group not in GROUPS:raise ValueError('Unknown captured observation group')
            point=ObservedFixture();point.symbol=config.symbol
            point.time=timestamp(group['available_at']).replace(tzinfo=None);point.end_time=point.time
            point.value=1.0
            point['available_at']=group['available_at'];point['group_json']=line
            return point
        parsed=parse_bundle_line(line,BUNDLE)
        if parsed is None:return None
        point=ObservedFixture();point.symbol=config.symbol
        point.time=parsed['event_time'].replace(tzinfo=None);point.end_time=point.time
        # LEAN's documented PythonData Value conversion uses Python float.
        # Exact original prices remain immutable CSV strings, never executable fills.
        point.value=float(parsed['value'])
        point['economic_date']=parsed['row']['date'];point['available_at']=parsed['row']['available_at']
        point['raw_close']=parsed['row']['close'];point['currency']=parsed['row']['currency']
        return point

class ObservedFixtureSmoke(QCAlgorithm):
    def initialize(self):
        global BUNDLE,DIRECTORY,INSPECTION,GROUPS
        if self.live_mode:raise ValueError('Backtest observation only')
        DIRECTORY=self.get_parameter('bundle_path')
        INSPECTION=self.get_parameter('inspection_bundle')=='true'
        if INSPECTION:
            from trading_intelligence.captured_observations import verify_inspection
            BUNDLE=json.loads((Path(DIRECTORY)/'inspection.json').read_text());verify_inspection(BUNDLE)
            GROUPS=[dict(available_at=g['available_at'],observations=[BUNDLE['observations'][i] for i in g['indices']]) for g in BUNDLE['observation_groups']]
            expected=[row for group in GROUPS for row in group['observations']]
            times=[timestamp(group['available_at']) for group in GROUPS]
        else:
            BUNDLE=verify_bundle(DIRECTORY)
            expected=[{'economic_date':row['date'],'available_at':row['available_at'],'close':row['close'],'currency':row['currency']} for row in BUNDLE['bars']]
            times=[timestamp(row['available_at']) for row in BUNDLE['bars']]
        self._expected=expected;self._inspection_mode=INSPECTION;self._group_count=0
        if not times or times!=sorted(times) or len(set(times))!=len(times):raise ValueError('Smoke requires unique increasing availability times')
        self.set_time_zone(TimeZones.UTC)
        start=(min(times)-timedelta(days=1)).date();end=(max(times)+timedelta(days=1)).date()
        self.set_start_date(start.year,start.month,start.day);self.set_end_date(end.year,end.month,end.day)
        self.set_cash(100000)
        self.set_benchmark(lambda _time:1)
        security=self.add_data(ObservedFixture,'OBSERVED_FIXTURE',Resolution.MINUTE,TimeZones.UTC,False,1)
        security.is_tradable=False
        self._symbol=security.symbol;self._observed=[];self._events=0

    def on_data(self,data):
        if not data.contains_key(self._symbol):return
        point=data[self._symbol]
        available=str(point['available_at'])
        observed_at=engine_utc(self.utc_time)
        if observed_at<timestamp(available):raise ValueError('Future information emitted early')
        if getattr(self,'_inspection_mode',False):
            group=json.loads(str(point['group_json']))
            if group['available_at']!=available:raise ValueError('Group availability mismatch')
            for row in group['observations']:
                if row['available_at']!=available:raise ValueError('Row availability differs from group')
                self._observed.append(dict(row,observed_engine_utc=observed_at.isoformat()))
        else:
            self._observed.append({'economic_date':str(point['economic_date']),'available_at':available,'close':str(point['raw_close']),'currency':str(point['currency']),'observed_engine_utc':observed_at.isoformat()})
        self._group_count=getattr(self,'_group_count',0)+1

    def on_order_event(self,event):
        self._events+=1
        raise ValueError('Order event forbidden in observer smoke')

    def on_end_of_algorithm(self):
        orders=int(self.transactions.orders_count)
        expected=self._expected
        actual=[{k:r[k] for k in expected[0]} for r in self._observed]
        summary={'status':'completed' if actual==expected and orders==0 and self._events==0 else 'failed','lean_observer_ran':True,'schema':'lean-observer-smoke-1','origin':'captured_inspection' if self._inspection_mode else 'synthetic_fixture','observed':self._observed,'observed_group_count':self._group_count,
                 'expected_count':len(expected),'observed_count':len(actual),'orders_count':orders,'order_events':self._events,
                 'verdict':actual==expected and orders==0 and self._events==0,'exact_observations_match':actual==expected,'live_trading':False,'strategy_profitability_verified':False}
        path=Path(self.get_parameter('observer_output'));path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(summary,sort_keys=True,indent=2)+'\n')
        if actual!=expected or orders!=0 or self._events!=0:raise ValueError('Smoke acceptance failed')
