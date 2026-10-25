"""The four public synthetic demos remain runnable together and after restart."""
import json
from pathlib import Path
import tempfile
import unittest

from trading_intelligence.research_foundations_demo import research_foundations_demo


class ResearchFoundationsDemoTests(unittest.TestCase):
    def test_four_distinct_examples_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = research_foundations_demo(root)
            again = research_foundations_demo(root)
            self.assertEqual(first, again)
            self.assertEqual(set(first['parts']), {
                'price_capture', 'sec_submissions', 'artifact_incident_lineage',
                'locked_predictions_outcomes'})
            self.assertEqual(json.loads((root / 'report.json').read_text()), first)
            self.assertEqual(first['origin'], 'synthetic')
            for flag in ('training_implemented', 'training_ready',
                         'authenticated_access_verified', 'lean_replay_implemented', 'live_trading'):
                self.assertFalse(first[flag])
            self.assertEqual(first['orders_sent'], 0)
