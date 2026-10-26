"""Python/CLR-boundary regressions from the actual Mac observer failure."""
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from trading_intelligence.lean_smoke_templates import engine_utc


class EngineDateWrapper:
    def __init__(self,text):self.text=text
    def isoformat(self):return self.text
    def __lt__(self,other):raise AssertionError('CLR wrapper comparison must never run')


class EngineUtcTests(unittest.TestCase):
    def test_native_utc_materialization_preserves_naive_and_aware_instants(self):
        expected=datetime(2026,1,5,21,0,1,tzinfo=timezone.utc)
        for value in (expected, expected.replace(tzinfo=None),
                      expected.astimezone(timezone(timedelta(hours=2))),
                      EngineDateWrapper('2026-01-05T23:00:01+02:00'),
                      EngineDateWrapper('2026-01-05T21:00:01Z'),
                      EngineDateWrapper('2026-01-05T21:00:01')):
            with self.subTest(value=value):
                actual=engine_utc(value)
                self.assertIs(type(actual),datetime)
                self.assertEqual(actual,expected)
                self.assertIs(actual.tzinfo,timezone.utc)

    def algorithm(self,time):
        from trading_intelligence import lean_smoke_templates
        path=Path(lean_smoke_templates.__file__).parent/'observer_algorithm.py'
        with patch.dict(sys.modules,{'AlgorithmImports':SimpleNamespace(PythonData=object,QCAlgorithm=object)}):
            spec=importlib.util.spec_from_file_location('observer_for_utc_test',path)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        algorithm=module.ObservedFixtureSmoke()
        algorithm._symbol='fixture';algorithm._observed=[];algorithm.utc_time=time
        return algorithm

    def data(self):
        class Slice:
            def contains_key(self,symbol):return symbol=='fixture'
            def __getitem__(self,symbol):return dict(available_at='2026-01-05T21:00:01.000000Z',economic_date='2026-01-05',raw_close='102',currency='USD')
        return Slice()

    def test_actual_on_data_uses_native_time_for_comparison_and_serialization(self):
        algorithm=self.algorithm(EngineDateWrapper('2026-01-05T23:00:01+02:00'))
        algorithm.on_data(self.data())
        self.assertEqual(algorithm._observed[0]['observed_engine_utc'],'2026-01-05T21:00:01+00:00')
        self.assertNotIn('Z+',algorithm._observed[0]['observed_engine_utc'])

    def test_actual_on_data_still_rejects_early_information(self):
        algorithm=self.algorithm(EngineDateWrapper('2026-01-05T23:00:00+02:00'))
        with self.assertRaisesRegex(ValueError,'Future information emitted early'):
            algorithm.on_data(self.data())
        self.assertEqual(algorithm._observed,[])
