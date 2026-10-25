from pathlib import Path
import tempfile
import unittest
from trading_intelligence.lean_export_demo import lean_export_demo
from trading_intelligence.lean_export import verify_bundle,export_bundle
from trading_intelligence.market_data import MarketDataStore
from trading_intelligence import DataOrigin
from trading_intelligence.contracts import ContractError,EvidenceIntegrityError

class ExportTests(unittest.TestCase):
    def test_demo_and_repeat(self):
        with tempfile.TemporaryDirectory() as directory:
            r=lean_export_demo(directory);self.assertEqual(r,lean_export_demo(directory));self.assertEqual(len(r['bars']),2);self.assertFalse(r['lean_runtime_verified'])
    def test_tamper_each_file(self):
        for name in ['bars.csv','replay.json','manifest.json']:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as directory:
                lean_export_demo(directory);p=Path(directory)/'bundle'/name;p.write_bytes(b'corrupt')
                with self.assertRaises(EvidenceIntegrityError):verify_bundle(p.parent)
    def test_real_source_without_admission_binding_rejected(self):
        with MarketDataStore(':memory:') as s,tempfile.TemporaryDirectory() as directory:
            s.register_source('real',DataOrigin.PROVIDER)
            with self.assertRaises(ContractError):export_bundle(s,'real','l',[],as_of=None,directory=directory)
    def test_modified_currency_or_dates_even_rehashed_rejected(self):
        import json,hashlib
        for old,new in [('USD','EUR'),('2026-01-05','2026-01-04')]:
            with self.subTest(old=old),tempfile.TemporaryDirectory() as directory:
                lean_export_demo(directory);p=Path(directory)/'bundle';raw=(p/'bars.csv').read_bytes().replace(old.encode(),new.encode());(p/'bars.csv').write_bytes(raw)
                m=json.loads((p/'manifest.json').read_bytes());m['files']['bars.csv']=hashlib.sha256(raw).hexdigest();(p/'manifest.json').write_text(json.dumps(m))
                with self.assertRaises(EvidenceIntegrityError):verify_bundle(p)

    def test_missing_scope_refused(self):
        from datetime import datetime,timezone
        from trading_intelligence import Use
        with tempfile.TemporaryDirectory() as directory:
            lean_export_demo(directory)
            with MarketDataStore(Path(directory)/'export.sqlite') as s:
                with self.assertRaises(ContractError):export_bundle(s,'fixture','l',['2026-01-05','2026-01-07'],as_of=datetime(2026,1,10,tzinfo=timezone.utc),directory=Path(directory)/'missing')

    def test_actions_preserved_without_auto_adjustment(self):
        import json
        from datetime import datetime,timezone
        with tempfile.TemporaryDirectory() as directory:
            lean_export_demo(directory)
            with MarketDataStore(Path(directory)/'export.sqlite') as s:
                at=datetime(2026,1,10,tzinfo=timezone.utc)
                body=dict(kind='split',listing_id='l',date='2026-01-05',start='2026-01-05T14:30:00Z',end='2026-01-05T21:00:00Z',currency='USD',values=dict(new_shares='2',old_shares='1'))
                s.import_record(source_id='fixture',record_id='split',revision_id='1',payload=json.dumps(body).encode(),published_at=at,received_at=at,processed_at=at)
                r=export_bundle(s,'fixture','l',['2026-01-05','2026-01-06'],as_of=at,directory=Path(directory)/'actions')
                self.assertEqual(r['bars'][0]['close'],'102')
                self.assertTrue(any(row['kind']=='split' for row in r['manifest']['replay']['records']))

    def test_unknown_source_and_immutable_target(self):
        from datetime import datetime,timezone
        with tempfile.TemporaryDirectory() as directory:
            lean_export_demo(directory)
            with MarketDataStore(Path(directory)/'export.sqlite') as s:
                with self.assertRaises(ContractError):export_bundle(s,'unknown','l',['2026-01-05'],as_of=datetime(2026,1,10,tzinfo=timezone.utc),directory=Path(directory)/'unknown')
                with self.assertRaises(ContractError):export_bundle(s,'fixture','l',['2026-01-05'],as_of=datetime(2026,1,10,tzinfo=timezone.utc),directory=Path(directory)/'bundle')

    def test_pure_custom_reader_uses_availability_not_economic_close(self):
        from trading_intelligence.lean_custom_data import parse_bundle_line
        from trading_intelligence.lean_export import FIELDS
        with tempfile.TemporaryDirectory() as directory:
            r=lean_export_demo(directory);rows=(Path(directory)/'bundle'/'bars.csv').read_text().splitlines()
            self.assertIsNone(parse_bundle_line(rows[0],r))
            parsed=parse_bundle_line(rows[1],r)
            self.assertGreater(parsed['event_time'],parsed['economic_end'])
            with self.assertRaises(EvidenceIntegrityError):parse_bundle_line(rows[1].replace('102','999'),r)

    def test_optional_pythondata_adapter_with_test_double(self):
        import sys,types
        from unittest.mock import patch
        from trading_intelligence.lean_custom_data import lean_data_type
        class FakeData(dict):pass
        fake=types.SimpleNamespace(PythonData=FakeData,SubscriptionDataSource=lambda *args:args,SubscriptionTransportMedium=types.SimpleNamespace(LOCAL_FILE='local'))
        with tempfile.TemporaryDirectory() as directory,patch.dict(sys.modules,{'AlgorithmImports':fake}):
            lean_export_demo(directory);kind=lean_data_type(Path(directory)/'bundle');datum=kind()
            config=types.SimpleNamespace(symbol='fixture',data_time_zone='UTC')
            self.assertEqual(datum.get_source(config,None,False)[1],'local')
            line=(Path(directory)/'bundle'/'bars.csv').read_text().splitlines()[1]
            point=datum.reader(config,line,None,False)
            self.assertEqual(point.time,point.end_time);self.assertEqual(point.time.day,10);self.assertEqual(point['economic_date'],'2026-01-05')
            with self.assertRaises(ContractError):datum.get_source(config,None,True)

    def test_current_revocation_blocks_historical_export(self):
        from datetime import datetime,timezone,timedelta
        from trading_intelligence import Use
        with tempfile.TemporaryDirectory() as directory:
            lean_export_demo(directory)
            with MarketDataStore(Path(directory)/'export.sqlite') as s:
                at=datetime(2026,1,10,tzinfo=timezone.utc);now=at+timedelta(days=1)
                s.set_permissions('fixture',known_at=now,uses={Use.STORAGE})
                with self.assertRaises(ContractError):export_bundle(s,'fixture','l',['2026-01-05'],as_of=at,directory=Path(directory)/'revoked',clock=lambda:now)
                with self.assertRaises(ContractError):export_bundle(s,'fixture','l',['2026-01-05'],as_of=now,directory=Path(directory)/'future',clock=lambda:at)
