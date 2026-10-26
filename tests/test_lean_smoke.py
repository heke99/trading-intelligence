"""Harness mechanics with fake subprocess artifacts; these do not execute LEAN."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from trading_intelligence.contracts import ContractError
from trading_intelligence.lean_smoke import prepare, run_prepared, verify_inputs, IMAGE


class SmokeHarnessTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)/'dedicated smoke'
        self.prepared=prepare(self.root);self.calls=[]

    def runner(self,command,*,stdout,stderr,timeout,check):
        self.calls.append(command)
        if command[1]=='rm':return SimpleNamespace(returncode=0)
        manifest=verify_inputs(self.root)
        observed=[dict(row,observed_engine_utc=row['available_at']) for row in manifest['expected_observations']]
        summary=dict(schema='lean-observer-smoke-1',origin='synthetic_fixture',status='completed',
            lean_observer_ran=True,verdict=True,exact_observations_match=True,observed=observed,
            expected_count=2,observed_count=2,orders_count=0,order_events=0)
        final=dict(state=dict(Status='Completed',RuntimeError='',StackTrace='',OrderCount='0',EndTime='2026-01-07T00:00:00Z'))
        self.mutate(summary,final,stdout)
        (self.root/'output'/'observer-evidence.json').write_text(json.dumps(summary))
        (self.root/'output'/'test-summary.json').write_text(json.dumps(final))
        return SimpleNamespace(returncode=self.returncode)

    returncode=0
    def mutate(self,summary,final,log):log.write('Backtest finished\n')

    def test_prepare_isolated_mounts_pinned_image_and_no_verified_engine(self):
        command=self.prepared['docker_command']
        self.assertIn(IMAGE,command);self.assertIn('none',command);self.assertIn('never',command)
        self.assertEqual(command.count('--mount'),2)
        mounts=[command[i+1] for i,x in enumerate(command) if x=='--mount']
        self.assertTrue(mounts[0].endswith('dst=/Smoke/input,readonly'))
        self.assertTrue(mounts[1].endswith('dst=/Smoke/output'))
        self.assertNotIn('--env',command);self.assertNotIn('-v',command)
        self.assertFalse(self.prepared['engine_execution_verified'])
        self.assertEqual(self.prepared['expected_count'],2)
        self.assertFalse(list((self.root/'input').rglob('*.sqlite*')))
        self.assertFalse(list((self.root/'input').rglob('.env')))

    def test_existing_directory_cannot_reuse_old_outputs(self):
        with self.assertRaises(ContractError):prepare(self.root)

    def test_success_requires_actual_shape_and_final_state_not_just_observer(self):
        result=run_prepared(self.root,runner=self.runner)
        self.assertEqual(result['status'],'passed');self.assertEqual(result['observed_count'],2)
        self.assertEqual(result['orders_sent'],0)
        self.assertTrue(result['engine_observation_verified']) # mocked mechanics only
        self.assertFalse(result['real_dataset_admitted'])
        self.assertIn('output/test-summary.json',result['evidence_files'])

    def test_nonzero_container_exit_fails_even_with_valid_observer(self):
        self.returncode=1
        with self.assertRaises(ContractError):run_prepared(self.root,runner=self.runner)
        result=json.loads((self.root/'run-result.json').read_text())
        self.assertFalse(result['engine_observation_verified'])
        self.assertEqual(len(self.calls),1)
        self.assertEqual(result['container_cleanup_status'],'not_needed_no_timeout')
        self.assertEqual(result['error_code'],'container_exit_nonzero')

    def test_runtime_error_in_final_engine_state_is_rejected(self):
        def mutate(summary,final,log):final['state']['Status']='RuntimeError'
        self.mutate=mutate
        with self.assertRaises(ContractError):run_prepared(self.root,runner=self.runner)

    def test_error_log_is_rejected(self):
        self.mutate=lambda s,f,log:log.write('ERROR:: invented engine failure')
        with self.assertRaises(ContractError):run_prepared(self.root,runner=self.runner)

    def test_early_engine_observation_is_rejected(self):
        def mutate(summary,final,log):
            t=datetime.fromisoformat(summary['observed'][0]['available_at'].replace('Z','+00:00'))
            summary['observed'][0]['observed_engine_utc']=(t-timedelta(seconds=1)).isoformat()
        self.mutate=mutate
        with self.assertRaises(ContractError):run_prepared(self.root,runner=self.runner)

    def test_order_count_and_wrong_input_observation_are_rejected(self):
        self.mutate=lambda s,f,log:s.update(orders_count=1)
        with self.assertRaises(ContractError):run_prepared(self.root,runner=self.runner)

    def test_changed_input_prevents_launch(self):
        (self.root/'input'/'config.json').write_text('{}')
        with self.assertRaises(ContractError):run_prepared(self.root,runner=self.runner)
        self.assertEqual(self.calls,[])

    def test_stale_output_prevents_launch(self):
        (self.root/'output'/'observer-evidence.json').write_text('{}')
        with self.assertRaises(ContractError):run_prepared(self.root,runner=self.runner)
        self.assertEqual(self.calls,[])

    def test_timeout_removes_only_scoped_container(self):
        def runner(command,**kwargs):
            self.calls.append(command)
            if command[1]=='rm':return SimpleNamespace(returncode=0)
            raise subprocess.TimeoutExpired(command,30)
        with self.assertRaises(ContractError):run_prepared(self.root,runner=runner,timeout=30)
        self.assertEqual(self.calls[-1],['docker','rm','--force',self.prepared['docker_command'][3]])
        self.assertEqual(json.loads((self.root/'run-result.json').read_text())['container_cleanup_status'],'removed')

    def test_invalid_result_shape_is_reported_as_failure(self):
        def runner(command,**kwargs):
            self.calls.append(command)
            if command[1]=='rm':return SimpleNamespace(returncode=0)
            (self.root/'output'/'observer-evidence.json').write_text('null')
            (self.root/'output'/'test-summary.json').write_text('[]')
            return SimpleNamespace(returncode=0)
        with self.assertRaises(ContractError):run_prepared(self.root,runner=runner)
        self.assertFalse(json.loads((self.root/'run-result.json').read_text())['engine_observation_verified'])

    def test_missing_docker_never_claims_engine_execution(self):
        with patch('trading_intelligence.lean_smoke.shutil.which',return_value=None):
            with self.assertRaises(ContractError):run_prepared(self.root)
        result=json.loads((self.root/'run-result.json').read_text())
        self.assertEqual(result['status'],'blocked')
        self.assertFalse(result['engine_observation_verified'])

    def test_engine_log_error_precedes_missing_observer_artifact(self):
        def runner(command,**kwargs):
            self.calls.append(command)
            kwargs['stdout'].write("ERROR:: TypeError: can't compare offset-naive and offset-aware datetimes\n")
            return SimpleNamespace(returncode=0)
        with self.assertRaises(ContractError):run_prepared(self.root,runner=runner)
        result=json.loads((self.root/'run-result.json').read_text())
        self.assertEqual(result['error_code'],'engine_log_error')
        self.assertIn('offset-naive',result['reason'])
        self.assertNotIn('No such container',(self.root/'output'/'engine.log').read_text())
        self.assertEqual(len(self.calls),1)

    def test_nonzero_exit_precedes_missing_observer_artifact(self):
        def runner(command,**kwargs):return SimpleNamespace(returncode=7)
        with self.assertRaises(ContractError):run_prepared(self.root,runner=runner)
        result=json.loads((self.root/'run-result.json').read_text())
        self.assertEqual(result['error_code'],'container_exit_nonzero')
        self.assertEqual(result['container_returncode'],7)

    def test_timeout_already_removed_is_not_a_cleanup_failure_or_log_error(self):
        def runner(command,**kwargs):
            if command[1]=='rm':return SimpleNamespace(returncode=1,stdout=b'Error: No such container: scoped-name')
            kwargs['stdout'].write('original engine output\n')
            raise subprocess.TimeoutExpired(command,30)
        with self.assertRaises(ContractError):run_prepared(self.root,runner=runner,timeout=30)
        result=json.loads((self.root/'run-result.json').read_text())
        self.assertEqual(result['container_cleanup_status'],'already_removed')
        self.assertEqual(result['error_code'],'container_timeout')
        self.assertEqual((self.root/'output'/'engine.log').read_text(),'original engine output\n')
