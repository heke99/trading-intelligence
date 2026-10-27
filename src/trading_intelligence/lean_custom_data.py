"""Own-written optional LEAN PythonData bridge; engine execution remains unverified."""
import csv
from decimal import Decimal
from pathlib import Path
from .contracts import ContractError,EvidenceIntegrityError
from .lean_export import FIELDS,verify_bundle
from .market_data import timestamp
from .lean_smoke_templates import delivery_utc, delivery_schedule

# Documentation/API compatibility checkpoint, not an installed runtime version.
LEAN_REFERENCE_COMMIT='f3d841e60dfd010ee5fc293ea893e56952484108'


def parse_bundle_line(line,verified_bundle):
    """Only accept exact rows present in a previously verified immutable bundle."""
    cells=next(csv.reader([line]))
    if cells==FIELDS:return None
    if len(cells)!=len(FIELDS):raise EvidenceIntegrityError('Unexpected custom-data CSV fields')
    row=dict(zip(FIELDS,cells))
    if row not in verified_bundle['bars']:raise EvidenceIntegrityError('CSV row not present in verified bundle')
    available=timestamp(row['available_at'])
    if available<timestamp(row['end']):raise EvidenceIntegrityError('Availability precedes economic bar end')
    return dict(row=row,event_time=available,economic_start=timestamp(row['start']),economic_end=timestamp(row['end']),value=Decimal(row['close']))


def lean_data_type(directory):
    """Create a PythonData subclass only inside an installed LEAN environment.

    Subscribe with UTC data timezone, fill_forward=False, and no live mode.
    Time and EndTime conservatively ceil availability to transport milliseconds;
    economic times are fields and original bundle availability remains exact.
    This custom stream must not be used as executable equity prices or fills.
    """
    verified=verify_bundle(directory)
    availability=[timestamp(row['available_at']) for row in verified['bars']]
    if availability!=sorted(availability):raise ContractError('LEAN input rows must be ordered by information availability')
    delivery_schedule(availability)
    from AlgorithmImports import PythonData,SubscriptionDataSource,SubscriptionTransportMedium
    source=str((Path(directory)/'bars.csv').resolve())
    class ObservedBundleBar(PythonData):
        def get_source(self,config,date,is_live_mode):
            if is_live_mode:raise ContractError('Live custom-data mode is not authorized')
            if str(config.data_time_zone) not in {'UTC','Etc/UTC'}:raise ContractError('Explicit UTC data timezone required')
            if verify_bundle(directory)!=verified:raise EvidenceIntegrityError('Bundle changed after adapter initialization')
            return SubscriptionDataSource(source,SubscriptionTransportMedium.LOCAL_FILE)
        def reader(self,config,line,date,is_live_mode):
            if is_live_mode:raise ContractError('Live custom-data mode is not authorized')
            parsed=parse_bundle_line(line,verified)
            if parsed is None:return None
            datum=ObservedBundleBar();datum.symbol=config.symbol
            datum.time=delivery_utc(parsed['event_time']).replace(tzinfo=None);datum.end_time=datum.time
            datum.value=parsed['value']
            datum['economic_start']=parsed['economic_start'].isoformat()
            datum['economic_end']=parsed['economic_end'].isoformat()
            datum['economic_date']=parsed['row']['date']
            datum['currency']=parsed['row']['currency']
            return datum
    return ObservedBundleBar
