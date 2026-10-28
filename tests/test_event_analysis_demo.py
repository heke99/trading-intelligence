"""Offline wire-to-archive event scenario demonstration using invented fixtures."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from trading_intelligence.event_analysis_demo import event_analysis_demo


class EventAnalysisDemoTests(unittest.TestCase):
    def test_scenarios_correction_and_restart_preserve_the_original_card(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch('socket.create_connection', side_effect=AssertionError('No network allowed')):
                report = event_analysis_demo(root)
                self.assertEqual(report, event_analysis_demo(root))
            self.assertEqual(json.loads((root / 'report.json').read_text()), report)
            self.assertEqual(report['origin'], 'synthetic_fixture')
            self.assertEqual(report['initial_analysis']['output']['status'], 'investigate')
            self.assertEqual(report['corrected_analysis']['output']['status'], 'abstain')
            self.assertEqual(report['corrected_analysis']['output']['scenarios'], [])
            self.assertNotEqual(report['initial_event_version_id'], report['corrected_event_version_id'])
            self.assertTrue(report['old_analysis_preserved'])
            self.assertTrue(report['unavailable_before_completion'])
            scenarios = report['initial_analysis']['output']['scenarios']
            self.assertEqual({row['economic_direction'] for row in scenarios}, {'none', 'adverse'})
            self.assertTrue(all(row['supporting_fact_ids'] for row in scenarios))
            self.assertTrue(all(row['invalidation_conditions'] for row in scenarios))
            self.assertFalse(report['real_model_called'])
            self.assertFalse(report['predictive_accuracy_assessed'])
            self.assertFalse(report['market_pricing_assessed'])
            self.assertFalse(report['training_ready'])
            self.assertFalse(report['live_trading'])
            self.assertEqual(report['orders_sent'], 0)
            self.assertEqual(report['network_requests'], 0)
            repository = Path(__file__).resolve().parents[1]
            environment = dict(os.environ, PYTHONPATH=str(repository / 'src'))
            program = ('from trading_intelligence.event_analysis_demo import event_analysis_demo; '
                       'import sys; event_analysis_demo(sys.argv[1])')
            subprocess.run([sys.executable, '-c', program, str(root)], cwd=repository,
                           env=environment, check=True, capture_output=True, text=True)
            self.assertEqual(json.loads((root / 'report.json').read_text()), report)
