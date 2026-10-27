"""Offline smoke configuration/templates; actual LEAN run required for verification."""
from pathlib import PurePosixPath
from datetime import datetime, timezone, timedelta

REFERENCE_COMMIT='f3d841e60dfd010ee5fc293ea893e56952484108'

def make_config(input_root='/Smoke/input',output_root='/Smoke/output',data_folder='/Lean/Data'):
    for value in (input_root,output_root,data_folder):
        p=PurePosixPath(value)
        if not p.is_absolute() or '..' in p.parts:raise ValueError('Explicit absolute container paths required')
    return {'environment':'backtesting','live-mode':False,'algorithm-type-name':'ObservedFixtureSmoke',
        'algorithm-language':'Python','algorithm-location':input_root+'/algorithm.py',
        'data-folder':data_folder,'results-destination-folder':output_root,
        'python-additional-paths':[input_root+'/python','/Lean/Launcher/bin/Debug'],
        'composer-dll-directory':'/Lean/Launcher/bin/Debug',
        'object-store-root':output_root+'/storage','log-file':output_root+'/lean.log',
        'environments':{'backtesting':{'live-mode':False}},
        'debugging':False,'close-automatically':True,'show-missing-data-logs':True,
        'job-user-id':'0','api-access-token':'','job-organization-id':'',
        'parameters':{'bundle_path':input_root+'/bundle','observer_output':output_root+'/observer-evidence.json','inspection_bundle':'false'},
        'log-handler':'QuantConnect.Logging.CompositeLogHandler',
        'messaging-handler':'QuantConnect.Messaging.Messaging','job-queue-handler':'QuantConnect.Queues.JobQueue',
        'api-handler':'QuantConnect.Api.Api','map-file-provider':'QuantConnect.Data.Auxiliary.LocalDiskMapFileProvider',
        'factor-file-provider':'QuantConnect.Data.Auxiliary.LocalDiskFactorFileProvider',
        'data-provider':'QuantConnect.Lean.Engine.DataFeeds.DefaultDataProvider',
        'data-channel-provider':'DataChannelProvider','object-store':'QuantConnect.Lean.Engine.Storage.LocalObjectStore',
        'data-aggregator':'QuantConnect.Lean.Engine.DataFeeds.AggregationManager',
        'setup-handler':'QuantConnect.Lean.Engine.Setup.BacktestingSetupHandler',
        'result-handler':'QuantConnect.Lean.Engine.Results.BacktestingResultHandler',
        'data-feed-handler':'QuantConnect.Lean.Engine.DataFeeds.FileSystemDataFeed',
        'real-time-handler':'QuantConnect.Lean.Engine.RealTime.BacktestingRealTimeHandler',
        'history-provider':['QuantConnect.Lean.Engine.HistoricalData.SubscriptionDataReaderHistoryProvider'],
        'transaction-handler':'QuantConnect.Lean.Engine.TransactionHandlers.BacktestingTransactionHandler'}


def engine_utc(value):
    """Materialize a native Python UTC datetime before comparing CLR wrappers.

    LEAN utc_time's naive representation explicitly denotes UTC. An aware
    representation retains its instant; an offset is converted, never dropped.
    """
    parsed = datetime.fromisoformat(str(value.isoformat()).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def delivery_utc(value):
    """Ceil transport time to the Python.NET millisecond boundary.

    Python -> CLR DateTime conversion discards sub-millisecond microseconds.
    Rounding upward prevents early delivery; source availability stays exact.
    """
    parsed=engine_utc(datetime.fromisoformat(value.replace('Z','+00:00')) if isinstance(value,str) else value)
    remainder=parsed.microsecond % 1000
    return parsed+timedelta(microseconds=1000-remainder) if remainder else parsed


def delivery_schedule(availability):
    """Reject distinct instants that the transport could otherwise collapse."""
    original=[engine_utc(datetime.fromisoformat(v.replace('Z','+00:00')) if isinstance(v,str) else v) for v in availability]
    delivered=[delivery_utc(v) for v in original]
    if len(set(delivered))!=len(set(original)):
        raise ValueError('UNSUPPORTED_TIME_PRECISION: distinct availability groups share a LEAN delivery millisecond')
    return delivered


def backtest_window(availability, *, now=None):
    """LEAN's public SetEndDate caps UTC backtests at the previous UTC day."""
    times=[engine_utc(datetime.fromisoformat(value.replace('Z','+00:00'))) if isinstance(value,str)
           else engine_utc(value) for value in availability]
    if not times:
        raise ValueError('Observation availability is required')
    delivery=delivery_schedule(times)
    current=engine_utc(now if now is not None else datetime.now(timezone.utc))
    latest=max(delivery)
    earliest=datetime.combine(latest.date()+timedelta(days=1),datetime.min.time(),timezone.utc)
    return dict(replayable=latest.date()<current.date(),
        code='ready' if latest.date()<current.date() else 'observation_day_not_closed',
        checked_at_utc=current.isoformat(),latest_available_at=max(times).isoformat(),
        latest_delivery_at=latest.isoformat(),delivery_time_policy='ceil_millisecond',
        earliest_eligible_utc=earliest.isoformat(),
        requested_start_date=(min(times).date()-timedelta(days=1)).isoformat(),
        requested_end_date=latest.date().isoformat(),
        engine_contract='SetEndDate_previous_algorithm_day',time_zone='UTC')
