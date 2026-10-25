"""Read-only local configuration inventory, never access or data certification."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3

from .contracts import ContractError, DataOrigin, required, utc

ENV_KEYS = ('ALPACA_PAPER_API_KEY', 'ALPACA_PAPER_SECRET_KEY', 'SEC_USER_AGENT')
CAPTURE_TABLES = {'price': 'alpaca_market_captures', 'calendar': 'alpaca_calendar_captures',
                  'sec': 'sec_submission_captures'}


def diagnostic(database=None, source_ids=(), *, environment=None, clock=None):
    """Inventory only explicit sources. Environment values never enter the report.

    An injected environment is the whole environment, including PATH; it does not
    fall back to host secrets or executables. No executable or network is run.
    """
    if not isinstance(source_ids, (list, tuple)):
        raise ContractError('Explicit source ID list required')
    ids = sorted(required(x, 'source_id') for x in source_ids)
    if len(ids) != len(set(ids)):
        raise ContractError('Duplicate source IDs')
    now = utc((clock or (lambda: datetime.now(timezone.utc)))())
    env = os.environ if environment is None else environment
    present = {key: bool(env.get(key)) for key in ENV_KEYS}
    # A path is configuration, not proof of LEAN identity/version/readiness.
    explicit = env.get('LEAN_EXECUTABLE')
    runtime = False
    if isinstance(explicit, str) and explicit:
        runtime = Path(explicit).is_file() and os.access(explicit, os.X_OK)
    elif not explicit and env.get('PATH'):
        runtime = shutil.which('lean', path=env['PATH']) is not None
    report = dict(checked_at=now, configuration_present=present,
                  credentials_verified=False, network_requests=0,
                  database_status='not_supplied', sources=[],
                  capture_counts={key: 0 for key in CAPTURE_TABLES},
                  lean_executable_available=runtime, lean_identity_verified=False,
                  real_admission_verified=False, training_ready=False, live_trading=False)
    db = None
    if database is not None:
        try:
            # URI mode=ro must never create/migrate the caller's database.
            uri = Path(database).resolve().as_uri() + '?mode=ro'
            db = sqlite3.connect(uri, uri=True)
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'sources', 'source_permissions'} <= tables:
                report['database_status'] = 'unsupported_schema'
            else:
                report['database_status'] = 'readable'
                for source_id in ids:
                    row = db.execute('SELECT origin FROM sources WHERE source_id=?', (source_id,)).fetchone()
                    item = dict(source_id=source_id, declared=row is not None,
                                origin=None, current_permissions=[], permissions_valid=False,
                                capture_counts={key: 0 for key in CAPTURE_TABLES})
                    if row:
                        item['origin'] = DataOrigin(row[0]).value
                        rights = db.execute('SELECT uses_json FROM source_permissions WHERE source_id=? AND known_at<=? ORDER BY known_at DESC LIMIT 1', (source_id, now)).fetchone()
                        if rights:
                            uses = json.loads(rights[0])
                            if not isinstance(uses, list) or any(x not in ('storage', 'research', 'training') for x in uses):
                                raise ValueError('Malformed declared permissions')
                            item['current_permissions'] = sorted(set(uses))
                            item['permissions_valid'] = True
                        for key, table in CAPTURE_TABLES.items():
                            if table in tables:
                                count = db.execute(f'SELECT COUNT(*) FROM {table} WHERE source_id=?', (source_id,)).fetchone()[0]
                                item['capture_counts'][key] = count
                                report['capture_counts'][key] += count
                    report['sources'].append(item)
        except (sqlite3.Error, ValueError, TypeError, OSError):
            # Partial inventories must not look complete. Do not expose DB/path contents.
            report['database_status'] = 'unreadable_or_invalid'
            report['sources'] = []
            report['capture_counts'] = {key: 0 for key in CAPTURE_TABLES}
        finally:
            if db is not None:
                db.close()
    source_blockers = []
    if report['database_status'] != 'readable':
        source_blockers.append('Supply an existing readable evidence database; no database was created.')
    if not ids:
        source_blockers.append('Select explicit source IDs for declared-permission checks.')
    for item in report['sources']:
        if not item['declared']:
            source_blockers.append(f"Declare selected source {item['source_id']} before capture.")
        elif not {'storage', 'research'} <= set(item['current_permissions']):
            source_blockers.append(f"Review current storage/research permissions for {item['source_id']}.")
        if item['declared'] and item['origin'] != DataOrigin.PROVIDER.value:
            source_blockers.append(f"Selected source {item['source_id']} is not provider-reported; preserve its declared origin.")
    alpaca = [] if all(present[k] for k in ENV_KEYS[:2]) else ['Configure both Alpaca paper credential variables locally.']
    common = ['Verify permitted source access explicitly; presence and captures do not verify credentials, account identity or entitlements.']
    report['capabilities'] = {
        'price': {'blockers': alpaca + source_blockers + common + ['Select route/listings/date/feed and resolve publication, coverage and admission reviews.']},
        'calendar': {'blockers': alpaca + source_blockers + common + ['Select paper route/date scope and verify calendar provenance and coverage.']},
        'sec': {'blockers': ([] if present['SEC_USER_AGENT'] else ['Configure an identified SEC_USER_AGENT with contact locally.']) + source_blockers + ['Select an explicit CIK and source; acceptance time does not establish publication.']},
        'export': {'blockers': source_blockers + ['Supply a verified admitted slice and exact replay/export scope; capture counts and review rows are not admission.']},
        'lean': {'blockers': ([] if runtime else ['Configure LEAN_EXECUTABLE or install/configure LEAN separately; this doctor does not install or execute it.']) + ['Verify runtime identity/version and run the frozen baseline only after an admitted export.']}}
    return report


def readiness_demo(directory):
    """Deterministic invented config-presence examples, without live access."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    clock = lambda: datetime(2026, 10, 26, tzinfo=timezone.utc)
    result = dict(origin=DataOrigin.SYNTHETIC.value, network_requests=0,
                  missing=diagnostic(environment={}, clock=clock),
                  configured=diagnostic(environment={key: 'invented-presence-only' for key in ENV_KEYS}, clock=clock))
    (directory / 'report.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    return result
