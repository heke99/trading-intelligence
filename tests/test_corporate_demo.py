from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from trading_intelligence.corporate_demo import corporate_demo

class CorporateDemoTests(unittest.TestCase):
    def test_repeatable_split_dividend_and_rename_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)
            result=corporate_demo(path)
            self.assertEqual(result,corporate_demo(path))
            rows=result['valuation']['days']
            self.assertEqual([Decimal(x['wealth']) for x in rows],[Decimal('1100')]*4)
            self.assertEqual([Decimal(x['shares']) for x in rows],[Decimal('10'),Decimal('20'),Decimal('20'),Decimal('20')])
            self.assertEqual(Decimal(rows[2]['receivable']),Decimal('20'))
            self.assertEqual(Decimal(rows[3]['cash']),Decimal('120'))
            self.assertEqual(Decimal(rows[3]['receivable']),Decimal('0'))
            self.assertEqual({x['identity']['listing_id'] for x in result['identity']['records']},{'demo-listing'})
            self.assertEqual([x['identifier'] for x in result['identity']['records']],['OLD','NEW','NEW','NEW'])
            self.assertEqual(result['orders_sent'],0)
            self.assertFalse(result['training_ready'])
