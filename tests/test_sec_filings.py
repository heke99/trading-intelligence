"""Invented SEC-shaped data and mocked transport; no live requests."""
from datetime import datetime,timedelta,timezone
from email.message import Message
from pathlib import Path
import json
import tempfile
import unittest
from urllib.error import HTTPError,URLError

from trading_intelligence import DataOrigin,Use
from trading_intelligence.contracts import ContractError,EvidenceIntegrityError,RecordConflict,UseNotAllowed
from trading_intelligence.sec_filings import (SecRead,SecReadError,SecSubmissionsReader,SecFilingsStore,
                                             endpoint,normalize_submissions,sync_sec,MAX_BYTES)
T=datetime(2026,1,10,22,tzinfo=timezone.utc)
CIK='0000000001'


def fixture():
    return {'cik':1,'filings':{'recent':{'accessionNumber':['0000000001-26-000001'],
        'filingDate':['2026-01-05'],'reportDate':['2025-12-31'],
        'acceptanceDateTime':['2026-01-05T21:00:00Z'],'form':['10-K'],
        'primaryDocument':['invented.htm']},'files':[]}}


class Response:
    def __init__(self,payload=None,status=200,url=None,media='application/json',encoding='identity'):
        self.payload=json.dumps(fixture()).encode() if payload is None else payload
        self.status=status;self.url=url or endpoint(CIK)
        self.headers=Message();self.headers['Content-Type']=media;self.headers['Content-Encoding']=encoding
    def __enter__(self):return self
    def __exit__(self,*_):pass
    def geturl(self):return self.url
    def read(self,size):return self.payload[:size]


class Opener:
    def __init__(self,response=None,error=None):self.response=response or Response();self.error=error;self.calls=[]
    def open(self,request,timeout):
        self.calls.append((request,timeout))
        if self.error:raise self.error
        return self.response


class SecTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'sec.db';self.s=SecFilingsStore(self.path)
        self.addCleanup(lambda:self.s.close())
        self.s.register_source('fixture',DataOrigin.SYNTHETIC)
        self.s.set_permissions('fixture',known_at=T-timedelta(days=30),uses={Use.STORAGE,Use.RESEARCH})

    def put(self,body=None,**changes):
        payload=json.dumps(fixture() if body is None else body).encode()
        args=dict(source_id='fixture',import_id='one',captured=SecRead(payload,T,endpoint(CIK),CIK),processed_at=T+timedelta(seconds=1))
        args.update(changes);return self.s.import_submissions(**args)

    def test_distinct_acceptance_report_date_and_unknown_publication(self):
        result=self.put();row=result['report']['filings'][0]
        self.assertEqual(row['accepted_at'],'2026-01-05T21:00:00.000000Z')
        self.assertEqual(row['report_date'],'2025-12-31');self.assertIsNone(row['published_at'])
        self.assertFalse(result['report']['training_ready']);self.assertFalse(result['report']['full_history_verified'])
        self.assertEqual(self.s.counts()['evidence_versions'],0)

    def test_availability_and_original_bytes(self):
        r=self.put();self.assertIsNone(self.s.submissions_as_of('fixture','one',as_of=T))
        self.assertEqual(self.s.submissions_as_of('fixture','one',as_of=T+timedelta(seconds=1)),r)
        raw=self.s.db.execute('SELECT payload FROM raw_objects WHERE sha256=?',(r['raw_sha'],)).fetchone()[0]
        self.assertEqual(json.loads(raw),fixture())

    def test_restart_idempotence(self):
        first=self.put();self.s.close();self.s=SecFilingsStore(self.path)
        self.assertEqual(first,self.put())
        self.assertEqual(self.s.db.execute('SELECT count(*) FROM sec_submission_captures').fetchone()[0],1)

    def test_changed_input_conflict(self):
        self.put();b=fixture();b['filings']['recent']['form']=['10-Q']
        with self.assertRaises(RecordConflict):self.put(b)
        with self.assertRaises(RecordConflict):self.put(processed_at=T+timedelta(seconds=2))

    def test_cik_shape_and_response_identity(self):
        for cik in ('1','0000000000','0000000001/evil',1,None):
            with self.subTest(cik=cik),self.assertRaises(ContractError):endpoint(cik)
        b=fixture();b['cik']=2;self.assertTrue(self.put(b)['report']['quarantined'])

    def test_malformed_and_duplicate_json_keys_quarantined_durably(self):
        for idx,payload in enumerate((b'bad',b'{"cik":1,"cik":2}',b'{"x":NaN}')):
            r=self.put(import_id=str(idx),captured=SecRead(payload,T,endpoint(CIK),CIK))
            self.assertTrue(r['report']['quarantined'])
            self.assertEqual(r,self.s.submissions_as_of('fixture',str(idx),as_of=T+timedelta(seconds=1)))

    def test_naive_or_future_acceptance_quarantined(self):
        for idx,value in enumerate(('2026-01-05T21:00:00','2027-01-05T21:00:00Z')):
            b=fixture();b['filings']['recent']['acceptanceDateTime']=[value]
            self.assertTrue(self.put(b,import_id=str(idx))['report']['quarantined'])

    def test_explicit_offset_normalizes_without_publication_inference(self):
        b=fixture();b['filings']['recent']['acceptanceDateTime']=['2026-01-05T16:00:00-05:00']
        row=self.put(b)['report']['filings'][0]
        self.assertEqual(row['accepted_at'],'2026-01-05T21:00:00.000000Z');self.assertIsNone(row['published_at'])

    def test_column_alignment_and_document_path(self):
        b=fixture();b['filings']['recent']['form']=[]
        self.assertTrue(self.put(b)['report']['quarantined'])
        b=fixture();b['filings']['recent']['primaryDocument']=['../secret.htm']
        self.assertTrue(self.put(b,import_id='path')['report']['quarantined'])

    def test_duplicate_accessions_all_quarantined(self):
        b=fixture()
        for key,values in b['filings']['recent'].items():values.append(values[0])
        r=self.put(b)['report'];self.assertEqual(r['filings'],[]);self.assertEqual(len(r['quarantined']),2)

    def test_archives_are_inventory_not_fetched_or_complete(self):
        b=fixture();b['filings']['files']=[dict(name='CIK0000000001-submissions-001.json',filingFrom='1994-01-01',filingTo='2024-01-01')]
        r=self.put(b)['report'];self.assertEqual(len(r['archive_files']),1);self.assertFalse(r['full_history_verified'])

    def test_permission_and_processing_order(self):
        with self.assertRaises(ContractError):self.put(processed_at=T-timedelta(seconds=1))
        self.put();self.s.set_permissions('fixture',known_at=T+timedelta(seconds=2),uses={Use.STORAGE})
        with self.assertRaises(UseNotAllowed):self.s.submissions_as_of('fixture','one',as_of=T+timedelta(seconds=2))

    def test_hash_corruption_rejected(self):
        r=self.put();self.s.db.execute('UPDATE raw_objects SET payload=?',(b'corrupt',));self.s.db.commit()
        with self.assertRaises(EvidenceIntegrityError):self.s.submissions_as_of('fixture','one',as_of=T+timedelta(seconds=1))

    def test_import_rejects_caller_transaction(self):
        self.s.db.execute("INSERT INTO entities VALUES ('pending','Pending')")
        with self.assertRaises(ContractError):self.put()
        self.assertTrue(self.s.db.in_transaction);self.s.db.rollback()

    def test_reader_bounded_exact_get_identified_headers_and_limiter(self):
        opener=Opener();calls=[]
        reader=SecSubmissionsReader('Research contact@example.invalid',opener=opener,clock=lambda:T,limiter=lambda:calls.append(1))
        r=reader.read(CIK);request=opener.calls[0][0]
        self.assertEqual(r.source_url,endpoint(CIK));self.assertEqual(request.get_method(),'GET')
        self.assertEqual(r.transport,'declared_http_get')
        self.assertIn('contact@example.invalid',request.get_header('User-agent'));self.assertEqual(calls,[1])
        self.assertNotIn('contact@example.invalid',repr(reader))

    def test_reader_rejects_unidentified_or_injected_header(self):
        for agent in ('Research','bad\ncontact@example.com',''):
            with self.subTest(agent=agent),self.assertRaises(ContractError):SecSubmissionsReader(agent)

    def test_reader_rejects_redirect_status_media_encoding_and_size(self):
        for response in (Response(url='https://evil.invalid'),Response(status=302),Response(media='text/html'),Response(encoding='gzip'),Response(payload=b'x'*(MAX_BYTES+1))):
            with self.assertRaises(SecReadError):SecSubmissionsReader('Research contact@example.invalid',opener=Opener(response),limiter=lambda:None).read(CIK)

    def test_reader_http_rate_limit_and_connection_errors_not_retried(self):
        for error in (HTTPError(endpoint(CIK),429,'private secret details',{},None),URLError('private secret details')):
            opener=Opener(error=error)
            with self.assertRaises(SecReadError) as exc:
                SecSubmissionsReader('Research contact@example.invalid',opener=opener,limiter=lambda:None).read(CIK)
            self.assertNotIn('private secret',str(exc.exception));self.assertEqual(len(opener.calls),1)

    def test_sync_requires_provider_source_and_reuses_capture(self):
        with self.assertRaises(ContractError):sync_sec(self.s,source_id='fixture',import_id='network',cik=CIK,reader=None,clock=lambda:T)
        self.s.register_source('provider',DataOrigin.PROVIDER)
        self.s.set_permissions('provider',known_at=T-timedelta(days=1),uses={Use.STORAGE,Use.RESEARCH})
        opener=Opener();reader=SecSubmissionsReader('Research contact@example.invalid',opener=opener,limiter=lambda:None,clock=lambda:T)
        a=sync_sec(self.s,source_id='provider',import_id='network',cik=CIK,reader=reader,clock=lambda:T+timedelta(seconds=1))
        b=sync_sec(self.s,source_id='provider',import_id='network',cik=CIK,reader=reader,clock=lambda:T+timedelta(seconds=2))
        self.assertEqual(a,b);self.assertEqual(len(opener.calls),1)

    def test_supplied_bytes_cannot_be_reused_as_network_sync(self):
        self.s.register_source('provider',DataOrigin.PROVIDER)
        self.s.set_permissions('provider',known_at=T-timedelta(days=1),uses={Use.STORAGE,Use.RESEARCH})
        self.put(source_id='provider',import_id='supplied')
        with self.assertRaises(RecordConflict):
            sync_sec(self.s,source_id='provider',import_id='supplied',cik=CIK,reader=None,clock=lambda:T+timedelta(seconds=2))
        with self.assertRaises(SecReadError):
            SecRead(b'{}',T,endpoint(CIK),CIK,transport='authenticated')

    def test_archive_inventory_rejects_different_issuer(self):
        b=fixture();b['filings']['files']=[dict(name='CIK0000000002-submissions-001.json',filingFrom='1994-01-01',filingTo='2024-01-01')]
        r=self.put(b)['report'];self.assertTrue(r['quarantined']);self.assertEqual(r['archive_files'],[])

    def test_archive_inventory_rejects_reversed_range(self):
        b=fixture();b['filings']['files']=[dict(name='CIK0000000001-submissions-001.json',filingFrom='2024-01-01',filingTo='1994-01-01')]
        r=self.put(b)['report'];self.assertTrue(r['quarantined']);self.assertEqual(r['archive_files'],[])


class RelativeDocumentTests(unittest.TestCase):
    def normalize(self, path='xslF345X06/form4.xml', **changes):
        body = fixture()
        body['filings']['recent']['primaryDocument'] = [path]
        for field, value in changes.items():
            body['filings']['recent'][field] = [value]
        return normalize_submissions(json.dumps(body).encode(), CIK, T)

    def test_nested_sec_ownership_paths_are_preserved_verbatim(self):
        for path in ('xslF345X05/ownership.xml', 'xslF345X06/form4.xml',
                     'folder/sub-folder/file_1.xml', 'invented.htm'):
            with self.subTest(path=path):
                result = self.normalize(path)
                self.assertEqual(result['quarantined'], [])
                self.assertEqual(result['filings'][0]['primary_document'], path)
                self.assertIsNone(result['filings'][0]['published_at'])

    def test_unsafe_paths_stay_quarantined_with_field_reason(self):
        for path in ('', '/', '/form4.xml', '//host/form4.xml', '../form4.xml',
                     'x/../form4.xml', 'x/./form4.xml', 'x//form4.xml', 'x/',
                     'https://sec.gov/form4.xml', 'C:/form4.xml', 'x\\form4.xml',
                     'x/%2e%2e/form4.xml', '%252e%252e/form4.xml', 'x%2fform4.xml',
                     'x/form4.xml?query=1', 'x/form4.xml#fragment', 'x/@file.xml',
                     'x/file\n.xml', 'x/filé.xml', './file.xml', '.', '..',
                     'x/' + 'a'*256, '/'.join(['x']*17), 'x'*1025, None, 3):
            with self.subTest(path=path):
                result = self.normalize(path)
                self.assertEqual(result['filings'], [])
                issue = result['quarantined'][0]
                self.assertEqual(issue['reason'], 'invalid_primary_document_path')
                self.assertEqual(issue['field'], 'primaryDocument')
                self.assertEqual(issue['row_index'], 0)

    def test_multiple_independent_errors_remain_visible_for_one_row(self):
        result = self.normalize('../bad', accessionNumber='invalid',
                                acceptanceDateTime='naive', filingDate='bad', reportDate='bad', form='')
        issues = result['quarantined'][0]['issues']
        self.assertEqual({x['field'] for x in issues}, {
            'accessionNumber','primaryDocument','acceptanceDateTime','filingDate','reportDate','form'})
        self.assertNotIn('../bad', json.dumps(issues))

    def test_future_acceptance_is_not_hidden_by_valid_document_path(self):
        result = self.normalize(acceptanceDateTime='2027-01-01T00:00:00Z')
        self.assertEqual(result['quarantined'][0]['reason'], 'acceptance_after_receipt')
        self.assertEqual(result['quarantined'][0]['field'], 'acceptanceDateTime')

    def test_legacy_import_retry_preserves_archived_normalization(self):
        from unittest.mock import patch
        import trading_intelligence.sec_filings as sec
        with tempfile.TemporaryDirectory() as directory:
            with SecFilingsStore(Path(directory)/'legacy.sqlite') as store:
                store.register_source('fixture', DataOrigin.SYNTHETIC)
                store.set_permissions('fixture', known_at=T-timedelta(days=1), uses={Use.STORAGE,Use.RESEARCH})
                body=fixture();body['filings']['recent']['primaryDocument']=['xslF345X05/ownership.xml']
                payload=json.dumps(body).encode();capture=SecRead(payload,T,endpoint(CIK),CIK)
                legacy=normalize_submissions(payload,CIK,T)
                legacy['filings']=[];legacy['quarantined']=[dict(row_index=0,reason='invalid_recent_filing')]
                legacy['recent_rows_valid']=False
                with patch.object(sec,'VERSION','sec-submissions-recent-1'), patch.object(sec,'normalize_submissions',return_value=legacy):
                    first=store.import_submissions(source_id='fixture',import_id='old',captured=capture,processed_at=T)
                archived=dict(store.db.execute('SELECT * FROM sec_submission_captures WHERE import_id=?',('old',)).fetchone())
                self.assertEqual(first,store.import_submissions(source_id='fixture',import_id='old',captured=capture,processed_at=T))
                second=store.import_submissions(source_id='fixture',import_id='new-v2',captured=capture,processed_at=T)
                self.assertEqual(second['version'],'sec-submissions-recent-2')
                self.assertEqual(len(second['report']['filings']),1)
                self.assertEqual(archived,dict(store.db.execute('SELECT * FROM sec_submission_captures WHERE import_id=?',('old',)).fetchone()))
                self.assertEqual(first['raw_sha'],second['raw_sha'])
                with self.assertRaises(RecordConflict):
                    store.import_submissions(source_id='fixture',import_id='old',captured=capture,processed_at=T+timedelta(seconds=1))
