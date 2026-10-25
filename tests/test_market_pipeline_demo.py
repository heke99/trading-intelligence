from pathlib import Path
import tempfile
import unittest
from trading_intelligence.market_pipeline_demo import market_pipeline_demo


class MarketPipelineDemoTests(unittest.TestCase):
    def test_repeatable_staging_and_gap_report_without_false_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            first = market_pipeline_demo(path)
            self.assertEqual(first, market_pipeline_demo(path))
            self.assertEqual(first['vendor_candidates'], 1)
            self.assertEqual(first['quarantined_rows'], 1)
            self.assertEqual(first['vendor_candidates_admitted'], 0)
            self.assertEqual(len(first['replay']['days']), 2)
            self.assertEqual(first['replay']['gaps'][0]['date'], '2026-01-06')
            self.assertFalse(first['replay']['complete_scope'])
            self.assertFalse(first['training_ready'])
            self.assertFalse(first['live_trading'])
            self.assertTrue((path / 'report.json').is_file())
