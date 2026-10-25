"""Bounded daily replay over an explicitly supplied expected-date scope.

This does not infer exchange holidays or certify the supplied calendar.
Missing records are reported; ambiguity, rights and integrity errors fail closed.
"""
from datetime import date
import hashlib
import json

from .contracts import ContractError, Use, required, utc
from .references import _key, _time


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def replay_dates(store, source_id, listing_id, expected_dates, *, as_of):
    """Return reproducible data/gaps and a manifest for the declared date list.

    Dates must be unique, increasing canonical ISO dates. ``complete_scope``
    only means each supplied date had a known session and raw daily bar. It
    says nothing about missing dates omitted by the caller, authoritative
    calendars, vendor coverage, corporate-action completeness or training use.
    Reads use one SQLite savepoint for a consistent snapshot; caller writes
    are neither committed nor rolled back by this function.
    """
    required(source_id, 'source_id')
    required(listing_id, 'listing_id')
    at = utc(as_of)
    if not isinstance(expected_dates, (list, tuple)) or not expected_dates:
        raise ContractError('Explicit nonempty list/tuple of expected dates required')
    dates = list(expected_dates)
    for day in dates:
        if not isinstance(day, str):
            raise ContractError('Canonical ISO dates required')
        try:
            parsed = date.fromisoformat(day).isoformat()
        except ValueError as exc:
            raise ContractError('Canonical ISO dates required') from exc
        if parsed != day:
            raise ContractError('Canonical ISO dates required')
    if dates != sorted(set(dates)):
        raise ContractError('Expected dates must be unique and increasing')

    # A read savepoint does not commit an existing caller transaction.
    store.db.execute('SAVEPOINT market_replay_read')
    try:
        store.require_use(source_id, Use.RESEARCH, as_of=as_of)
        if store.db.execute('SELECT 1 FROM listings WHERE listing_id=?', (listing_id,)).fetchone() is None:
            raise ContractError('Unknown explicit listing')
        manifest = {'version': 1, 'source_id': source_id, 'listing_id': listing_id,
                    'as_of': at, 'expected_dates': dates, 'records': [], 'gaps': []}
        days = []
        for day in dates:
            target = _key(source_id, listing_id, day)
            missing = []
            # Check every known kind, even when another required kind is absent.
            # This prevents a missing session from concealing corrupt price data.
            for kind in ('session', 'bar', 'split', 'cash_dividend'):
                rows = store.db.execute(
                    'SELECT valid_from FROM market_snapshots '
                    'WHERE kind=? AND target_id=? AND known_at<=?', (kind, target, at)).fetchall()
                starts = {r['valid_from'] for r in rows}
                if not starts:
                    if kind in ('session', 'bar'):
                        missing.append(kind)
                    continue
                if len(starts) != 1:
                    raise ContractError('Ambiguous effective starts in replay scope')
                snap = store.market.get(kind, target, effective_at=_time(starts.pop()), as_of=as_of)
                row = store.db.execute(
                    'SELECT m.known_at,m.evidence_id,e.source_id,e.sha256 FROM market_snapshots m '
                    'JOIN evidence_versions e USING(evidence_id) WHERE m.snapshot_id=?',
                    (snap.snapshot_id,)).fetchone()
                if row is None or row['source_id'] != source_id:
                    raise ContractError('Replay evidence source does not match scope')
                manifest['records'].append({
                    'date': day, 'kind': kind, 'snapshot_id': snap.snapshot_id,
                    'evidence_id': row['evidence_id'], 'raw_sha256': row['sha256'],
                    'known_at': row['known_at'],
                    'normalized_sha256': hashlib.sha256(_canonical(snap.body).encode()).hexdigest()})
            if missing:
                manifest['gaps'].append({'date': day, 'missing': missing,
                                         'reason': 'not_available_at_cutoff'})
                continue
            result = store.replay_day(source_id, listing_id, day, as_of=as_of)
            days.append({'date': day, 'session': result['session'].body,
                         'bar': result['bar'].body,
                         'actions': [x.body for x in result['actions']]})
        manifest['complete_scope'] = not manifest['gaps']
        encoded = _canonical(manifest).encode()
        answer = {'manifest': manifest, 'manifest_sha256': hashlib.sha256(encoded).hexdigest(),
                  'days': days, 'gaps': manifest['gaps'],
                  'complete_scope': manifest['complete_scope'],
                  'training_ready': False, 'full_history_verified': False, 'live_trading': False}
    except BaseException:
        store.db.execute('ROLLBACK TO market_replay_read')
        store.db.execute('RELEASE market_replay_read')
        raise
    else:
        store.db.execute('RELEASE market_replay_read')
        return answer
