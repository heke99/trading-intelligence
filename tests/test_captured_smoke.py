"""Captured-path mechanics with invented captures and fake engine results."""
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_captured_observations as fixtures
from trading_intelligence.captured_smoke import prepare_captured
from trading_intelligence.contracts import ContractError
from trading_intelligence.lean_smoke import prepare, run_prepared, verify_inputs


class CapturedSmokeTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.InspectionTests('test_restart_and_explicit_scope')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=Path(self.fixture.tmp.name)/'inspection-run'
        self.report=self.fixture.inspect()
        self.result=prepare(self.root,inspection_report=self.report)

    def test_same_time_rows_are_one_group_without_fabricated_timestamps(self):
        manifest=verify_inputs(self.root)
        self.assertEqual(manifest['expected_group_count'],1)
        self.assertEqual(len(manifest['expected_observations']),2)
        lines=(self.root/'input'/'bundle'/'groups.jsonl').read_text().splitlines()
        self.assertEqual(len(lines),1)
        group=json.loads(lines[0])
        self.assertEqual([r['index'] for r in group['observations']],[0,1])
        self.assertTrue(all(r['available_at']==group['available_at'] for r in group['observations']))
        self.assertTrue(all(r['published_at'] is None for r in group['observations']))
        self.assertFalse(manifest['dataset_admitted'])

    def test_readonly_capture_prepare_keeps_original_database_bytes(self):
        before=self.fixture.path.read_bytes()
        other=self.root.parent/'readonly-run'
        result=prepare_captured(other,database=self.fixture.path,price_source_id='prices',price_import_id='job',
            calendar_source_id='calendar',calendar_import_id='cal',listing_id='l',clock=lambda:fixtures.T+fixtures.timedelta(seconds=2))
        self.assertTrue(result['inspection_only']);self.assertFalse(result['dataset_admitted'])
        self.assertEqual(before,self.fixture.path.read_bytes())
        self.assertFalse(list((other/'input').rglob('*.db')))

    def runner(self,command,*,stdout,stderr,timeout,check):
        manifest=verify_inputs(self.root)
        summary=dict(schema='lean-observer-smoke-1',origin='captured_inspection',status='completed',
            lean_observer_ran=True,verdict=True,exact_observations_match=True,
            observed=[dict(r,observed_engine_utc=r['available_at']) for r in manifest['expected_observations']],
            expected_count=2,observed_count=2,orders_count=0,order_events=0,observed_group_count=1)
        self.mutate(summary)
        (self.root/'output'/'observer-evidence.json').write_text(json.dumps(summary))
        (self.root/'output'/'capture-summary.json').write_text(json.dumps(dict(state=dict(Status='Completed',RuntimeError='',StackTrace='',OrderCount='0',EndTime='done'))))
        return SimpleNamespace(returncode=0)

    def mutate(self,summary):pass

    def test_host_accepts_tied_group_rows_but_never_admits_the_dataset(self):
        result=run_prepared(self.root,runner=self.runner)
        self.assertEqual(result['observed_count'],2);self.assertEqual(result['observed_group_count'],1)
        self.assertEqual(result['scope'],'captured_data_inspection_only')
        self.assertFalse(result['dataset_admitted']);self.assertFalse(result['publication_verified'])
        self.assertFalse(result['training_ready']);self.assertEqual(result['orders_sent'],0)

    def test_missing_or_duplicate_expanded_rows_fail(self):
        self.mutate=lambda summary:summary.update(observed=[summary['observed'][0]]*2)
        with self.assertRaises(ContractError):run_prepared(self.root,runner=self.runner)

    def test_wrong_group_count_fails(self):
        self.mutate=lambda summary:summary.update(observed_group_count=2)
        with self.assertRaises(ContractError):run_prepared(self.root,runner=self.runner)

    def test_actual_template_group_callback_preserves_every_original_row(self):
        from trading_intelligence import lean_smoke_templates
        path=Path(lean_smoke_templates.__file__).parent/'observer_algorithm.py'
        with patch.dict(sys.modules,{'AlgorithmImports':SimpleNamespace(PythonData=object,QCAlgorithm=object)}):
            spec=importlib.util.spec_from_file_location('group_callback_test',path)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        group=json.loads((self.root/'input'/'bundle'/'groups.jsonl').read_text())
        algorithm=module.ObservedFixtureSmoke();algorithm._symbol='fixture';algorithm._inspection_mode=True
        algorithm._observed=[];algorithm._group_count=0
        from datetime import datetime
        algorithm.utc_time=datetime.fromisoformat(group['available_at'].replace('Z','+00:00'))
        class Slice:
            def contains_key(self,key):return True
            def __getitem__(self,key):return dict(available_at=group['available_at'],group_json=json.dumps(group))
        algorithm.on_data(Slice())
        self.assertEqual(algorithm._group_count,1)
        self.assertEqual([{k:v for k,v in r.items() if k!='observed_engine_utc'} for r in algorithm._observed],group['observations'])
