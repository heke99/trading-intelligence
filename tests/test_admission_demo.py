from pathlib import Path
import tempfile
import unittest
from trading_intelligence.admission_demo import admission_demo

class AdmissionDemoTests(unittest.TestCase):
    def test_repeatable_calendar_and_denial_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            result=admission_demo(Path(directory))
            self.assertEqual(result,admission_demo(Path(directory)))
            self.assertFalse(result['missing_reviews']['eligible_for_declared_purpose'])
            self.assertTrue(result['synthetic_validation']['eligible_for_declared_purpose'])
            self.assertFalse(result['historical_replay']['eligible_for_declared_purpose'])
            self.assertIn('historical_publication_or_vintage_unknown',result['historical_replay']['reasons'])
            self.assertFalse(result['current_denial']['eligible_for_declared_purpose'])
            self.assertEqual(result['market_snapshots'],0)
            self.assertEqual(result['calendar']['candidates'][0]['end'],'2026-01-05T18:00:00.000000Z')
            self.assertFalse(result['training_ready']);self.assertEqual(result['orders_sent'],0)
