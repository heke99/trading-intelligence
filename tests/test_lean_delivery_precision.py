"""Model Python.NET's microsecond // 1000 CLR DateTime conversion.

These are synthetic boundary regressions, not an actual LEAN runtime run.
"""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from trading_intelligence.lean_smoke_templates import delivery_utc, delivery_schedule, backtest_window


class MillisecondData(dict):
    @property
    def time(self):return self._time
    @time.setter
    def time(self,value):
        self._time=value.replace(microsecond=value.microsecond//1000*1000)


class DeliveryPrecisionTests(unittest.TestCase):
    def test_transport_never_precedes_source_at_every_microsecond_remainder(self):
        for remainder in range(1000):
            source=datetime(2026,10,26,13,37,46,321000+remainder,tzinfo=timezone.utc)
            delivered=delivery_utc(source)
            self.assertGreaterEqual(delivered,source)
            self.assertLess((delivered-source).total_seconds(),.001)
            self.assertEqual(delivered.microsecond%1000,0)
            self.assertEqual(delivery_utc(delivered),delivered)

    def test_offset_normalization_and_rollover(self):
        self.assertEqual(delivery_utc('2026-10-26T14:37:46.123456+01:00').isoformat(),
                         '2026-10-26T13:37:46.124000+00:00')
        self.assertEqual(delivery_utc('2026-10-26T23:59:59.999999Z').isoformat(),
                         '2026-10-27T00:00:00+00:00')

    def test_day_preflight_covers_delivery_rollover_without_backdating_source(self):
        source='2026-10-26T23:59:59.999999Z'
        window=backtest_window([source],now=datetime(2026,10,27,tzinfo=timezone.utc))
        self.assertFalse(window['replayable'])
        self.assertEqual(window['latest_available_at'],'2026-10-26T23:59:59.999999+00:00')
        self.assertEqual(window['latest_delivery_at'],'2026-10-27T00:00:00+00:00')
        self.assertEqual(window['earliest_eligible_utc'],'2026-10-28T00:00:00+00:00')

    def test_colliding_distinct_groups_fail_but_original_ties_are_allowed(self):
        values=['2026-10-26T13:37:46.123001Z','2026-10-26T13:37:46.123999Z']
        with self.assertRaisesRegex(ValueError,'UNSUPPORTED_TIME_PRECISION'):
            delivery_schedule(values)
        self.assertEqual(len(delivery_schedule([values[0],values[0]])),2)

    def module(self):
        from trading_intelligence import lean_smoke_templates
        path=Path(lean_smoke_templates.__file__).parent/'observer_algorithm.py'
        with patch.dict(sys.modules,{'AlgorithmImports':SimpleNamespace(PythonData=MillisecondData,QCAlgorithm=object)}):
            spec=importlib.util.spec_from_file_location('precision_observer_test',path)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module

    def test_captured_reader_through_lossy_boundary_preserves_rows_and_strict_gate(self):
        for source in ['2026-10-26T13:37:46.123456Z','2026-10-26T13:37:46.999999Z']:
            with self.subTest(source=source):
                module=self.module();module.INSPECTION=True
                rows=[dict(index=i,available_at=source,close='102.15') for i in range(17)]
                group=dict(available_at=source,observations=rows)
                line=json.dumps(group);module.GROUPS=[group]
                point=module.ObservedFixture().reader(SimpleNamespace(symbol='fixture'),line,None,False)
                self.assertEqual(point['group_json'],line)
                self.assertEqual(point['available_at'],source)
                class Slice:
                    def contains_key(self,key):return key=='fixture'
                    def __getitem__(self,key):return point
                algorithm=module.ObservedFixtureSmoke();algorithm._symbol='fixture'
                algorithm._inspection_mode=True;algorithm._observed=[];algorithm._group_count=0
                # Reproduce the old truncated instant: the unchanged gate must fail.
                exact=datetime.fromisoformat(source.replace('Z','+00:00'))
                algorithm.utc_time=exact.replace(microsecond=exact.microsecond//1000*1000)
                with self.assertRaisesRegex(ValueError,'Future information emitted early: observed_engine_utc='):
                    algorithm.on_data(Slice())
                self.assertEqual(algorithm._observed,[])
                algorithm.utc_time=point.end_time
                algorithm.on_data(Slice())
                self.assertEqual(algorithm._group_count,1)
                self.assertEqual(len(algorithm._observed),17)
                for original,observed in zip(rows,algorithm._observed):
                    self.assertEqual({k:observed[k] for k in original},original)
                    self.assertGreaterEqual(datetime.fromisoformat(observed['observed_engine_utc']),exact)

    def test_synthetic_csv_reader_uses_same_non_early_transport_rule(self):
        module=self.module();module.INSPECTION=False
        row=dict(date='2026-10-23',available_at='2026-10-26T13:37:46.123456Z',close='102',currency='USD')
        parsed=dict(event_time=datetime.fromisoformat(row['available_at'].replace('Z','+00:00')),value=102,row=row)
        with patch.object(module,'parse_bundle_line',return_value=parsed):
            point=module.ObservedFixture().reader(SimpleNamespace(symbol='fixture'),'ignored',None,False)
        self.assertEqual(point.time.isoformat(),'2026-10-26T13:37:46.124000')
        self.assertEqual(point['available_at'],row['available_at'])
