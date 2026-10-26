"""Actual LEAN yesterday-cap regression without changing observation timestamps."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from trading_intelligence.contracts import ContractError
from trading_intelligence.lean_smoke import prepare, run_prepared
from trading_intelligence.lean_smoke_templates import backtest_window


class BacktestWindowTests(unittest.TestCase):
    def test_same_day_is_blocked_until_exact_next_utc_midnight(self):
        rows=['2026-10-26T16:00:00Z']
        blocked=backtest_window(rows,now=datetime(2026,10,26,23,59,59,tzinfo=timezone.utc))
        self.assertFalse(blocked['replayable'])
        self.assertEqual(blocked['earliest_eligible_utc'],'2026-10-27T00:00:00+00:00')
        ready=backtest_window(rows,now=datetime(2026,10,27,tzinfo=timezone.utc))
        self.assertTrue(ready['replayable'])
        self.assertEqual(ready['requested_end_date'],'2026-10-26')

    def test_wall_clock_offset_is_normalized_and_future_arrivals_stay_blocked(self):
        now=datetime.fromisoformat('2026-10-27T01:00:00+01:00')
        self.assertTrue(backtest_window(['2026-10-26T23:59:59Z'],now=now)['replayable'])
        future=backtest_window(['2026-10-28T01:00:00Z'],now=now)
        self.assertFalse(future['replayable'])
        self.assertEqual(future['earliest_eligible_utc'],'2026-10-29T00:00:00+00:00')

    def test_host_does_not_launch_docker_for_unclosed_observation_day(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'blocked';prepare(root)
            def runner(*args,**kwargs):raise AssertionError('Docker must not launch')
            with self.assertRaisesRegex(ContractError,'NOT_YET_REPLAYABLE'):
                run_prepared(root,runner=runner,clock=lambda:datetime(2026,1,6,23,tzinfo=timezone.utc))
            result=json.loads((root/'run-result.json').read_text())
            self.assertEqual(result['status'],'not_yet_replayable')
            self.assertFalse(result['container_started']);self.assertFalse(result['engine_observation_verified'])
            self.assertEqual(result['backtest_window']['earliest_eligible_utc'],'2026-01-07T00:00:00+00:00')
            self.assertEqual(list((root/'output').iterdir()),[])

    def load_algorithm(self,root,engine_today):
        from trading_intelligence import lean_smoke_templates
        path=Path(lean_smoke_templates.__file__).parent/'observer_algorithm.py'
        fake=SimpleNamespace(PythonData=object,QCAlgorithm=object,TimeZones=SimpleNamespace(UTC='UTC'),Resolution=SimpleNamespace(MINUTE='Minute'))
        with patch.dict(sys.modules,{'AlgorithmImports':fake}):
            spec=importlib.util.spec_from_file_location('window_algorithm_test',path)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        algorithm=module.ObservedFixtureSmoke();algorithm.live_mode=False
        params=dict(bundle_path=str(root/'input'/'bundle'),observer_output=str(root/'output'/'observer.json'),inspection_bundle='false')
        algorithm.get_parameter=lambda key:params[key]
        algorithm.set_time_zone=lambda zone:None
        algorithm.set_start_date=lambda *args:None
        def set_end(year,month,day):
            requested=datetime(year,month,day,tzinfo=timezone.utc)
            yesterday=datetime.combine(engine_today.date()-timedelta(days=1),datetime.min.time(),timezone.utc)
            algorithm.end_date=min(requested,yesterday)+timedelta(days=1,microseconds=-1)
        algorithm.set_end_date=set_end
        algorithm.set_cash=lambda amount:None;algorithm.set_benchmark=lambda function:None
        algorithm.add_data=lambda *args:SimpleNamespace(symbol='fixture',is_tradable=True)
        return module,algorithm

    def test_template_detects_real_set_end_date_clamp_before_subscription(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'clamp';prepare(root)
            module,algorithm=self.load_algorithm(root,datetime(2026,1,6,tzinfo=timezone.utc))
            real=backtest_window
            # Host/container clock mismatch: helper sees eligible day, but the
            # public engine setter applies yesterday relative to its own clock.
            module.backtest_window=lambda values:real(values,now=datetime(2026,1,7,tzinfo=timezone.utc))
            with self.assertRaisesRegex(ValueError,'UNSUPPORTED_BACKTEST_WINDOW'):algorithm.initialize()
            window=json.loads((root/'output'/'window-evidence.json').read_text())
            self.assertFalse(window['covers_observations'])
            self.assertTrue(window['actual_engine_end_utc'].startswith('2026-01-05'))

    def test_template_allows_unchanged_arrivals_after_the_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'ready';prepare(root)
            module,algorithm=self.load_algorithm(root,datetime(2026,1,7,tzinfo=timezone.utc))
            real=backtest_window
            module.backtest_window=lambda values:real(values,now=datetime(2026,1,7,tzinfo=timezone.utc))
            algorithm.initialize()
            window=json.loads((root/'output'/'window-evidence.json').read_text())
            self.assertTrue(window['covers_observations'])
            self.assertEqual(window['requested_end_date'],'2026-01-06')
            self.assertEqual(algorithm._expected[1]['available_at'],'2026-01-06T21:00:01.000000Z')
