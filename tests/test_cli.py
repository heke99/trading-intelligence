import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

from trading_intelligence.cli import main
from trading_intelligence.collective2 import NoRedirects, HTTPSGetTransport
from trading_intelligence.common import DataError
from trading_intelligence.normalize import normalize_record
from test_pipeline import order, trade


class CliTests(unittest.TestCase):
    def call(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(args)
        return code, out.getvalue(), err.getvalue()

    def test_demo_runs_entirely_offline_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory, patch('trading_intelligence.collective2.HTTPSGetTransport.get', side_effect=AssertionError('network forbidden')):
            first = self.call(['demo','--out',directory])
            second = self.call(['demo','--out',directory])
            self.assertEqual(first[0],0)
            self.assertTrue(json.loads(first[1])['synthetic_only'])
            self.assertEqual(sum(r['inserted_versions'] for r in json.loads(second[1])['runs']),0)
            self.assertTrue(all(not r['training_ready'] for r in json.loads(first[1])['runs']))

    def test_status_after_demo(self):
        with tempfile.TemporaryDirectory() as directory:
            self.call(['demo','--out',directory])
            code, out, _ = self.call(['status','--out',directory])
            self.assertEqual(code,0)
            self.assertFalse(json.loads(out)['training_ready'])

    def test_fetch_needs_explicit_access_acknowledgement(self):
        code, _, err = self.call(['fetch','--strategy-id','123','--out','unused'])
        self.assertEqual(code,2)
        self.assertIn('AUTHORIZED_ACCESS_ACK_REQUIRED',err)

    def test_missing_api_key_is_safe_noninteractive_failure(self):
        with patch.dict(os.environ,{},clear=True),patch('sys.stdin.isatty',return_value=False):
            code, _, err = self.call(['fetch','--strategy-id','123','--out','unused','--acknowledge-authorized-access'])
        self.assertEqual(code,2)
        self.assertIn('API_KEY_REQUIRED',err)

    def test_csv_inspect_does_not_print_trade_values(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'input.csv';p.write_text('id,symbol\n123,PRIVATE_SYMBOL\n')
            code,out,err=self.call(['inspect-csv',str(p)])
            self.assertEqual(code,0)
            self.assertNotIn('PRIVATE_SYMBOL',out+err)

    def test_redirect_handler_does_not_forward_authentication(self):
        request=Request('https://api4-general.collective2.com/Strategies/GetStrategyHistoricalOrders',headers={'Authorization':'Bearer test-only'})
        with self.assertRaises(HTTPError):
            NoRedirects().redirect_request(request,None,302,'',{},'https://other.example')

    def test_real_transport_rejects_arbitrary_hosts_before_network(self):
        t=HTTPSGetTransport()
        with self.assertRaisesRegex(DataError,'URL_NOT_ALLOWED'):
            t.get('https://other.example/Strategies/GetStrategyHistoricalOrders?StrategyId=123',{})

    def test_csv_posted_timestamp_does_not_inherit_api_utc_assumption(self):
        result=normalize_record(order(), 'orders',123,posted_utc_documented=False)
        self.assertIsNone(result['posted_at_utc'])
        self.assertIn('TIMEZONE_UNVERIFIED',result['quality_flags'])

    def test_literal_zero_pnl_is_not_treated_as_missing(self):
        row=normalize_record(trade(ProfitLoss=0,Commission=0),'closed_trades',123)
        self.assertEqual(row['profit_loss_reported'],'0')
        self.assertEqual(row['commission_reported'],'0')

    def test_options_identity_preserved_not_flattened_to_stock(self):
        source=trade(C2Symbol={'FullSymbol':'XYZ240119P50','SymbolType':'option','Expiry':'20240119','PutOrCall':'P','StrikePrice':'50'})
        row=normalize_record(source,'closed_trades',123)
        self.assertEqual(row['instrument_type_raw'],'option')
        self.assertEqual(row['instrument_identity_raw']['C2Symbol']['StrikePrice'],'50')

    def test_unsupported_mapping_does_not_succeed(self):
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'input.csv';file.write_text('id,symbol\n123,EURUSD\n')
            mapping=Path(directory)/'mapping.json';mapping.write_text('{"version":99}')
            code,_,err=self.call(['import-csv',str(file),'--mapping',str(mapping),'--strategy-id','123','--out',str(Path(directory)/'data')])
            self.assertEqual(code,2)
            self.assertIn('CSV_MAPPING_VERSION_INVALID',err)


if __name__ == '__main__':
    unittest.main()
