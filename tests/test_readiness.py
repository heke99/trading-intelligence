import json
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from trading_intelligence.contracts import ContractError, DataOrigin, Use
from trading_intelligence.readiness import diagnostic, readiness_demo, ENV_KEYS
from trading_intelligence.store import EvidenceStore

NOW = datetime(2026, 10, 26, tzinfo=timezone.utc)


class ReadinessTests(unittest.TestCase):
    def test_missing_config_is_not_access(self):
        result = diagnostic(environment={}, clock=lambda: NOW)
        self.assertFalse(any(result['configuration_present'].values()))
        self.assertFalse(result['credentials_verified'])
        self.assertFalse(result['real_admission_verified'])
        self.assertFalse(result['training_ready'])
        self.assertEqual(result['network_requests'], 0)
        self.assertEqual(set(result['capabilities']), {'price', 'calendar', 'sec', 'export', 'lean'})
        self.assertTrue(all(x['blockers'] for x in result['capabilities'].values()))

    def test_no_secret_values_and_no_host_fallback(self):
        secrets = {key: 'SENSITIVE_VALUE_123' for key in ENV_KEYS}
        result = diagnostic(environment=secrets, clock=lambda: NOW)
        self.assertTrue(all(result['configuration_present'].values()))
        self.assertNotIn('SENSITIVE_VALUE', json.dumps(result))
        self.assertFalse(result['credentials_verified'])
        with patch.dict(os.environ, secrets):
            self.assertFalse(any(diagnostic(environment={}, clock=lambda: NOW)['configuration_present'].values()))

    def test_database_not_created(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'absent.sqlite'
            result = diagnostic(path, ['chosen'], environment={}, clock=lambda: NOW)
            self.assertEqual(result['database_status'], 'unreadable_or_invalid')
            self.assertFalse(path.exists())

    def test_selected_sources_and_current_revoke(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'evidence.sqlite'
            store = EvidenceStore(path)
            store.register_source('selected', DataOrigin.SYNTHETIC)
            store.register_source('hidden', DataOrigin.PROVIDER)
            store.set_permissions('selected', known_at=NOW-timedelta(days=1), uses={Use.STORAGE, Use.RESEARCH})
            store.set_permissions('selected', known_at=NOW, uses=set())
            store.set_permissions('selected', known_at=NOW+timedelta(days=1), uses={Use.RESEARCH})
            store.db.execute('CREATE TABLE alpaca_market_captures(source_id TEXT)')
            store.db.executemany('INSERT INTO alpaca_market_captures VALUES (?)', [('selected',), ('hidden',), ('hidden',)])
            store.db.commit()
            store.db.close()
            before = path.read_bytes()
            result = diagnostic(path, ['selected', 'absent'], environment={}, clock=lambda: NOW)
            self.assertEqual(before, path.read_bytes())
            self.assertEqual(result['capture_counts']['price'], 1)
            selected = next(x for x in result['sources'] if x['source_id']=='selected')
            self.assertEqual(selected['current_permissions'], [])
            self.assertEqual(selected['origin'], 'synthetic_fixture')
            self.assertNotIn('hidden', json.dumps(result))
            self.assertFalse(result['real_admission_verified'])
            self.assertTrue(any('permissions' in x for x in result['capabilities']['price']['blockers']))

    def test_schema_is_not_migrated(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'old.sqlite'
            sqlite3.connect(path).close()
            before=path.read_bytes()
            self.assertEqual(diagnostic(path, environment={}, clock=lambda: NOW)['database_status'], 'unsupported_schema')
            self.assertEqual(before,path.read_bytes())

    def test_invalid_database_permissions_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'bad.sqlite'
            db=sqlite3.connect(path)
            db.executescript('CREATE TABLE sources(source_id TEXT, origin TEXT); CREATE TABLE source_permissions(source_id TEXT, known_at TEXT, uses_json TEXT);')
            db.execute('INSERT INTO sources VALUES (?,?)', ('a','provider_reported'))
            db.execute('INSERT INTO source_permissions VALUES (?,?,?)',('a','2000','"research"'))
            db.commit();db.close()
            result=diagnostic(path,['a'],environment={},clock=lambda: NOW)
            self.assertEqual(result['database_status'],'unreadable_or_invalid')
            self.assertEqual(result['sources'],[])

    def test_runtime_presence_does_not_execute(self):
        with tempfile.TemporaryDirectory() as d:
            marker=Path(d)/'EXECUTED'
            lean=Path(d)/'lean'
            lean.write_text('#!/bin/sh\ntouch '+str(marker)+'\n')
            lean.chmod(0o700)
            for env in ({'LEAN_EXECUTABLE':str(lean)}, {'PATH':d}):
                result=diagnostic(environment=env,clock=lambda: NOW)
                self.assertTrue(result['lean_executable_available'])
                self.assertFalse(result['lean_identity_verified'])
            self.assertFalse(marker.exists())
            self.assertFalse(diagnostic(environment={'LEAN_EXECUTABLE':str(marker),'PATH':d},clock=lambda: NOW)['lean_executable_available'])

    def test_input_validation(self):
        for ids in ('source', ['a','a'], [' ']):
            with self.assertRaises(ContractError): diagnostic(source_ids=ids,environment={},clock=lambda: NOW)
        with self.assertRaises(ContractError): diagnostic(environment={},clock=lambda: datetime(2026,1,1))

    def test_repeatable_demo_and_secret_flags_only(self):
        with tempfile.TemporaryDirectory() as d:
            result=readiness_demo(d)
            before=(Path(d)/'report.json').read_bytes()
            self.assertEqual(result,readiness_demo(d))
            self.assertEqual(before,(Path(d)/'report.json').read_bytes())
            self.assertNotIn('invented-presence-only',before.decode())
            self.assertTrue(all(result['configured']['configuration_present'].values()))
            self.assertFalse(result['configured']['credentials_verified'])
