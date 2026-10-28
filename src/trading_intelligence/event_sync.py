"""Read-only event collection and a restartable polling loop; never submits orders."""
from datetime import datetime, timezone
import math
import time
from uuid import uuid4

from .contracts import (ContractError, DataOrigin, EvidenceIntegrityError, RecordConflict,
                        Use, UseNotAllowed, required, utc)
from .event_sources import EventCapture, EventReadError, EVENT_FEEDS


def _finite_positive(value, name):
    if type(value) not in (int, float):
        raise ContractError(f'{name} must be a finite positive number')
    try:
        valid = math.isfinite(value) and value > 0
    except OverflowError:
        valid = False
    if not valid:
        raise ContractError(f'{name} must be a finite positive number')


def _preflight(store, source_id, checked):
    for use in (Use.STORAGE, Use.RESEARCH):
        store.require_use(source_id, use, as_of=checked)
    origin = store.db.execute('SELECT origin FROM sources WHERE source_id=?',
                              (source_id,)).fetchone()
    if origin is None or origin[0] != DataOrigin.PROVIDER.value:
        raise ContractError('Network collection requires an explicitly declared provider source')


def sync_events(store, *, source_id, import_id, feed, reader, clock=None):
    """One explicit feed capture, with replay of an existing import before transport."""
    required(source_id, 'source_id')
    required(import_id, 'import_id')
    if not isinstance(feed, str) or feed not in EVENT_FEEDS:
        raise ContractError('An explicit supported event feed is required')
    if store.db.in_transaction:
        raise ContractError('Event sync requires an idle connection')
    now = clock or (lambda: datetime.now(timezone.utc))
    checked = now()
    _preflight(store, source_id, checked)
    old = store.capture_as_of(source_id, import_id, as_of=checked)
    if old is not None:
        if (old['source_url'] != EVENT_FEEDS[feed]
                or old['transport'] != 'declared_http_get'):
            raise RecordConflict('Import ID belongs to another feed or capture provenance')
        return old
    captured = reader.read()
    if (not isinstance(captured, EventCapture)
            or captured.source_url != EVENT_FEEDS[feed]
            or captured.transport != 'declared_http_get'):
        raise ContractError('Event response does not match the requested feed and transport')
    return store.stage(source_id=source_id, import_id=import_id,
                       capture=captured, processed_at=now())


def watch_events(store, *, source_id, feed, reader, radius_km, poll_seconds=60,
                 iterations=None, clock=None, sleeper=None, run_id=None):
    """Yield capture/context reports. The caller persists reports; captures persist in SQLite.

    Each poll has its own import identity. Event versions are deduplicated by the
    store. A network failure yields no context or position proposal and can be
    retried on the next poll. KeyboardInterrupt and unexpected defects propagate.
    """
    _finite_positive(poll_seconds, 'Polling interval')
    if iterations is not None and (type(iterations) is not int or iterations <= 0):
        raise ContractError('Iterations must be a positive integer or omitted for continuous collection')
    _finite_positive(radius_km, 'Investigation radius')
    if not isinstance(feed, str) or feed not in EVENT_FEEDS:
        raise ContractError('An explicit supported event feed is required')
    required(source_id, 'source_id')
    identity = required(run_id, 'run_id') if run_id is not None else uuid4().hex
    now = clock or (lambda: datetime.now(timezone.utc))
    sleep = sleeper or time.sleep
    _preflight(store, source_id, now())
    index = 0
    while iterations is None or index < iterations:
        index += 1
        import_id = f'{identity}:{index}'
        attempted = utc(now())
        try:
            capture = sync_events(store, source_id=source_id, import_id=import_id,
                                  feed=feed, reader=reader, clock=now)
            cutoff = now()
            fresh_ids = {event['event_id'] for event in capture['observations']}
            ambiguous_ids = {entry['event_id'] for entry in capture.get('revision_conflicts', [])}
            event_ids = sorted(fresh_ids | ambiguous_ids)
            contexts = [store.context(source_id, event_id, as_of=cutoff,
                                      radius_km=radius_km) for event_id in event_ids]
            report = dict(status='captured' if not capture['quarantined'] else 'captured_with_quarantine',
                          run_id=identity, iteration=index,
                          import_id=import_id, attempted_at=attempted,
                          available_at=capture['available_at'], capture_id=capture['capture_id'],
                          raw_sha=capture['raw_sha'], source_url=capture['source_url'],
                          capture_state=capture['state'], fresh_event_ids=sorted(fresh_ids),
                          ambiguity_event_ids=sorted(ambiguous_ids),
                          observations=len(capture['observations']),
                          quarantined=len(capture['quarantined']), contexts=contexts)
        except (ContractError, OSError) as error:
            # Provider bodies, arbitrary exception messages and article text are
            # deliberately excluded from the operational report.
            reason = ('source_use_not_allowed' if isinstance(error, UseNotAllowed) else
                      'event_integrity_failure' if isinstance(error, EvidenceIntegrityError) else
                      'event_read_unavailable' if isinstance(error, EventReadError) else
                      'event_contract_rejected' if isinstance(error, ContractError) else
                      'event_io_failed')
            report = dict(status='collection_or_context_unavailable', run_id=identity,
                          iteration=index, import_id=import_id, attempted_at=attempted,
                          contexts=[], reason=reason)
        report.update(source_id=source_id, feed=feed, training_ready=False,
                      predictive_model_implemented=False, orders_sent=0, live_trading=False)
        yield report
        if iterations is None or index < iterations:
            sleep(poll_seconds)
