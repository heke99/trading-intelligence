import json
from pathlib import Path
import tempfile
import unittest

from trading_intelligence.lean_readiness_demo import lean_readiness_demo


class LeanReadinessDemoTests(unittest.TestCase):
    def test_four_new_capabilities_repeat_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = lean_readiness_demo(root)
            self.assertEqual(report, lean_readiness_demo(root))
            self.assertEqual(json.loads((root / 'report.json').read_text()), report)
            self.assertEqual(set(report['parts']), {
                'verified_data_bundle', 'frozen_baseline_experiment',
                'cash_position_reconciliation', 'configuration_diagnostic'})
            for key in ('external_access_verified','real_dataset_admitted',
                        'lean_runtime_executed','training_implemented','live_trading'):
                self.assertFalse(report[key])
            self.assertEqual(report['orders_sent'], 0)
