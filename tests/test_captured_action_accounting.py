"""Captured revisions -> reviewed hypothetical split/dividend preview, no ledger writes."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from decimal import localcontext
import json
import unittest
import test_corporate_actions_capture as fixtures
from trading_intelligence.captured_action_accounting import CapturedActionAccountingStore
from trading_intelligence.contracts import ContractError,EvidenceIntegrityError,RecordConflict,Use

class CapturedAccountingTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.CorporateCaptureTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.run_capture();self.captured=self.f.inspect()
        self.store=CapturedActionAccountingStore(self.f.path,clock=lambda:self.f.forward.now)
        self.addCleanup(self.store.close)
        self.opening=dict(route=deepcopy(self.captured['job']['request']['route']),listing_id='l',currency='USD',units='100',cash='50',at='2026-01-05T14:30:00Z',
            unchanged_holdings_through='2026-01-14T14:30:00Z',opening_receivables_clear=True)
        self.policy=dict(version='supplied-reviewed-v1',timezone='America/New_York',
            dividend_treatment='gross_no_tax_or_fees',fractional_policy='block',rules=[])
        for i,c in enumerate(self.captured['candidates']):
            self.policy['rules'].append(dict(provider_id=c['provider_id'],provider_row_sha256=c['provider_row_sha256'],
                listing_id='l',currency='USD',identity_reviewed=True,terms_reviewed=True,
                effective_at='2026-01-06T14:30:00Z',payment_at='2026-01-13T14:30:00Z' if c['provider_kind']=='cash_dividends' else None,sequence=i))
        self.value=datetime(2026,1,14,11,tzinfo=timezone.utc)

    def evidence(self,identity,body):
        now=self.f.forward.now
        return self.store.ingest(source_id='actions',record_id=identity,revision_id='1',payload=json.dumps(body).encode(),published_at=now,received_at=now)

    def preview(self,identity='preview',opening=None,policy=None,valuation=None):
        return self.store.preview(identity,'actions','actions-1',opening or self.evidence(identity+'-opening',self.opening),
            policy or self.evidence(identity+'-policy',self.policy),as_of=self.f.forward.now,valuation_at=valuation or self.value)

    def test_paid_dividend_uses_split_units_but_never_applies_to_holdings(self):
        x=self.preview()['result']
        self.assertEqual(x['closing'],dict(units='200',cash='75.000',dividend_receivables={}))
        self.assertFalse(x['accounting_ready']);self.assertFalse(x['dataset_admitted']);self.assertFalse(x['holdings_or_cash_written'])
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM market_snapshots').fetchone()[0],0)

    def test_receivable_precedes_cash_payment_and_payment_boundary_is_exact(self):
        earlier=datetime(2026,1,7,tzinfo=timezone.utc)
        x=self.preview(valuation=earlier)['result']['closing']
        self.assertEqual(x['cash'],'50');self.assertEqual(list(x['dividend_receivables'].values()),['25.000'])
        paid=datetime(2026,1,13,14,30,tzinfo=timezone.utc)
        self.assertEqual(self.preview('paid',valuation=paid)['result']['closing']['cash'],'75.000')

    def test_explicit_same_instant_order_changes_declared_dividend_basis(self):
        self.policy['rules'][0]['sequence']=1;self.policy['rules'][1]['sequence']=0
        self.assertEqual(self.preview()['result']['closing']['cash'],'62.500')

    def test_missing_review_holdings_and_opening_entitlements_block(self):
        self.policy['rules'][0]['terms_reviewed']=False
        self.opening['opening_receivables_clear']=False
        self.opening['unchanged_holdings_through']='2026-01-05T15:00:00Z'
        x=self.preview()['result']
        self.assertIsNone(x['closing']);self.assertEqual(x['status'],'blocked');self.assertEqual(len(x['blockers']),3)

    def test_missing_payment_instant_does_not_guess_cash(self):
        self.policy['rules'][1]['payment_at']=None
        x=self.preview()['result'];self.assertIn('payment_instant_unknown',x['blockers']);self.assertIsNone(x['closing'])

    def test_wrong_currency_revision_date_and_duplicate_order_rejected(self):
        original=deepcopy(self.policy)
        changes=[('currency','EUR'),('provider_row_sha256','wrong'),('effective_at','2026-01-07T14:30:00Z'),('sequence',1)]
        for i,(key,value) in enumerate(changes):
            self.policy=deepcopy(original);self.policy['rules'][0][key]=value
            with self.subTest(key=key),self.assertRaises(ContractError):self.preview('bad'+str(i))

    def test_no_preopening_dividend_entitlement_is_invented(self):
        self.opening['at']='2026-01-07T14:30:00Z'
        x=self.preview()['result'];self.assertIn('preopening_dividend_entitlement_unknown',x['blockers'])

    def test_historical_result_completion_and_restart_are_immutable(self):
        opening=self.evidence('open',self.opening);policy=self.evidence('pol',self.policy)
        cutoff=self.f.forward.now;self.f.forward.now+=timedelta(seconds=1)
        x=self.store.preview('preview','actions','actions-1',opening,policy,as_of=cutoff,valuation_at=self.value)
        self.assertIsNone(self.store.get_preview('preview',as_of=cutoff))
        self.assertEqual(x,self.store.preview('preview','actions','actions-1',opening,policy,as_of=cutoff,valuation_at=self.value))
        with CapturedActionAccountingStore(self.f.path,clock=lambda:self.f.forward.now) as other:
            self.assertEqual(x,other.get_preview('preview',as_of=self.f.forward.now))
        with self.assertRaises(RecordConflict):self.preview('preview')

    def test_current_revocation_and_raw_integrity_block_old_reads(self):
        x=self.preview();cutoff=self.f.forward.now;self.f.forward.now+=timedelta(seconds=1)
        self.store.set_permissions('actions',known_at=self.f.forward.now,uses={Use.STORAGE})
        with self.assertRaises(ContractError):self.store.get_preview('preview',as_of=cutoff)

    def test_corrupt_policy_raw_is_detected(self):
        x=self.preview()
        with self.store.db:self.store.db.execute('UPDATE raw_objects SET payload=? WHERE sha256=?',(b'bad',x['policy_evidence']['sha256']))
        with self.assertRaises(EvidenceIntegrityError):self.store.get_preview('preview',as_of=self.f.forward.now)

    def test_future_knowledge_and_valuation_rejected(self):
        with self.assertRaises(ContractError):self.preview(valuation=self.f.forward.now+timedelta(seconds=1))
        self.opening['at']='2026-01-15T00:00:00Z'
        with self.assertRaises(ContractError):self.preview('future')

    def test_decimal_precision_independent(self):
        with localcontext() as context:
            context.prec=3
            x=self.preview()
        self.assertEqual(x['result']['closing']['cash'],'75.000')

    def test_fractional_reverse_split_does_not_invent_cash_in_lieu(self):
        self.f.responses=[fixtures.page(dict(reverse_splits=[fixtures.split(new_rate=1,old_rate=2)]))]
        self.f.run_capture(import_id='reverse')
        captured=self.store.inspect_job('actions','reverse',as_of=self.f.forward.now,clock=self.store.clock)
        rule=deepcopy(self.policy['rules'][0]);rule['provider_row_sha256']=captured['candidates'][0]['provider_row_sha256']
        self.policy['rules']=[rule];self.opening['units']='1'
        x=self.store.preview('reverse','actions','reverse',self.evidence('reverse-open',self.opening),self.evidence('reverse-policy',self.policy),
            as_of=self.f.forward.now,valuation_at=self.value)['result']
        self.assertIn('fractional_split_requires_cash_in_lieu_policy',x['blockers']);self.assertIsNone(x['closing'])

    def test_complete_empty_capture_still_does_not_certify_coverage(self):
        self.f.responses=[fixtures.page()];self.f.run_capture(import_id='empty')
        self.policy['rules']=[]
        x=self.store.preview('empty','actions','empty',self.evidence('empty-open',self.opening),self.evidence('empty-policy',self.policy),
            as_of=self.f.forward.now,valuation_at=self.value)['result']
        self.assertFalse(x['coverage_verified']);self.assertFalse(x['accounting_ready'])

    def test_module_cli_connects_existing_capture_and_policy(self):
        import subprocess,sys,os
        opening=self.evidence('cli-open',self.opening);policy=self.evidence('cli-policy',self.policy)
        result=subprocess.run([sys.executable,'-m','trading_intelligence.captured_action_accounting','--database',str(self.f.path),
            '--preview-id','cli','--source-id','actions','--import-id','actions-1','--opening-evidence-id',opening,
            '--policy-evidence-id',policy,'--as-of',self.f.forward.now.isoformat(),'--valuation-at',self.value.isoformat()],
            env={**os.environ,'PYTHONPATH':'src'},capture_output=True,text=True,check=True)
        x=json.loads(result.stdout)
        self.assertEqual(x['result']['closing']['units'],'200');self.assertFalse(x['result']['holdings_or_cash_written'])

    def test_opening_from_another_account_cannot_use_capture(self):
        self.opening['route']['account_id']='another-account'
        with self.assertRaises(ContractError):self.preview()

    def test_new_provider_revision_cannot_reuse_old_review_rules(self):
        self.f.responses=[fixtures.page(dict(forward_splits=[fixtures.split(new_rate=3)],cash_dividends=[fixtures.dividend()]))]
        self.f.run_capture(import_id='corrected')
        with self.assertRaises(ContractError):
            self.store.preview('corrected','actions','corrected',self.evidence('corrected-open',self.opening),
                self.evidence('old-rules',self.policy),as_of=self.f.forward.now,valuation_at=self.value)
