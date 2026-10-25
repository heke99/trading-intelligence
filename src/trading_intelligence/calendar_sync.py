"""Read-only calendar capture orchestration with explicit provider source/route."""
from dataclasses import asdict
from datetime import datetime, timezone

from .alpaca_calendar_reader import calendar_query
from .brokers import BrokerAccount, Environment
from .contracts import ContractError, DataOrigin, RecordConflict, Use, required, utc


def sync_calendar(store, *, source_id, import_id, route, start_date, end_date,
                  venue, reader, clock=None):
    required(source_id, 'source_id')
    required(import_id, 'import_id')
    required(venue, 'venue')
    if store.db.in_transaction:
        raise ContractError('Calendar synchronization requires an idle connection')
    if not isinstance(route, BrokerAccount) or route.broker_id != 'alpaca' or route.environment != Environment.PAPER:
        raise ContractError('Explicit Alpaca paper route required')
    query = calendar_query(start_date, end_date)
    if venue not in {'XNYS','XNAS','IEXG'}:
        raise ContractError('Unsupported US equity venue')
    now = clock or (lambda: datetime.now(timezone.utc))
    checked_at = now()
    utc(checked_at)
    for use in (Use.STORAGE, Use.RESEARCH):
        store.require_use(source_id, use, as_of=checked_at)
    origin = store.db.execute('SELECT origin FROM sources WHERE source_id=?',(source_id,)).fetchone()
    if origin is None or origin[0] != DataOrigin.PROVIDER.value:
        raise ContractError('Network synchronization requires an explicitly declared provider source')
    old = store.db.execute('SELECT 1 FROM alpaca_calendar_captures WHERE source_id=? AND import_id=?',
                           (source_id,import_id)).fetchone()
    if old:
        result = store.calendar_as_of(source_id, import_id, as_of=checked_at)
        if result is None:
            raise ContractError('Existing calendar capture is not yet available')
        provenance = result.get('provenance')
        if (provenance is None or provenance['route'] != asdict(route)
                or provenance['query'] != query or result['venue'] != venue):
            raise RecordConflict('Calendar import ID belongs to different request provenance')
        return result
    captured = reader.read(start_date, end_date)
    if captured.route != route or captured.query != query:
        raise ContractError('Calendar read does not match explicit request route')
    return store.import_calendar(source_id=source_id, import_id=import_id,
        payload=captured.payload, received_at=captured.received_at, processed_at=now(),
        start_date=start_date, end_date=end_date, venue=venue,
        provenance=captured.provenance)
