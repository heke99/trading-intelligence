"""Synthetic pure corporate-action proof; no account or trading data."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext, ROUND_DOWN, Rounded
import json
import unittest

from trading_intelligence import AssetKind, DataOrigin, Entity, Instrument, Listing, Use
from trading_intelligence.contracts import ContractError
from trading_intelligence.corporate_replay import corporate_action_replay
from trading_intelligence.market_data import MarketDataStore

T = datetime(2026, 1, 10, tzinfo=timezone.utc)
DATES = ['2026-01-05','2026-01-06','2026-01-07']


class CorporateProofTests(unittest.TestCase):
    def setUp(self):
        self.s=MarketDataStore(':memory:'); self.addCleanup(self.s.close)
        self.s.register_source('fixture',DataOrigin.SYNTHETIC)
        self.s.set_permissions('fixture',known_at=T-timedelta(days=30),uses={Use.STORAGE,Use.RESEARCH})
        self.s.register_entity(Entity('e','Invented'))
        self.s.register_instrument(Instrument('i','e',AssetKind.EQUITY))
        self.s.register_listing(Listing('l','i','XNAS','USD'))
        for day in DATES:
            self.put(day,'session',{'timezone':'America/New_York'})
            close='100' if day==DATES[0] else '50'
            self.put(day,'bar',{'open':close,'high':close,'low':close,'close':close,'volume':'20','price_kind':'raw'})

    def put(self,day,kind,values,**changes):
        body=dict(kind=kind,listing_id='l',date=day,start=day+'T14:30:00Z',end=day+'T21:00:00Z',currency='USD',values=values)
        args=dict(source_id='fixture',record_id=kind+day,revision_id='1',payload=json.dumps(body).encode(),
                  published_at=T,received_at=T,processed_at=T+timedelta(seconds=1))
        args.update(changes)
        return self.s.import_record(**args)

    def proof(self,**changes):
        args=dict(as_of=T+timedelta(seconds=2),opening_at=T-timedelta(days=10),
                  initial_cash=Decimal('0'),initial_shares=Decimal('10'),currency='USD',
                  dividend_share_basis='post_split',dividend_policy='ordinary_cash_no_withholding')
        args.update(changes)
        return corporate_action_replay(self.s,'fixture','l',DATES,**args)

    def split(self):
        self.put(DATES[1],'split',{'new_shares':'2','old_shares':'1'})

    def dividend(self,day=DATES[1],pay=DATES[2],amount='1'):
        self.put(day,'cash_dividend',{'amount':amount,'payment_date':pay})

    def test_split_preserves_wealth_when_raw_price_rebases(self):
        self.split(); r=self.proof()
        self.assertEqual([Decimal(x['wealth']) for x in r['days']],[Decimal('1000')]*3)
        self.assertEqual(Decimal(r['days'][1]['shares']),Decimal('20'))
        self.assertEqual(r['days'][1]['cash'],'0')

    def test_dividend_receivable_then_cash_no_double_count(self):
        self.split(); self.dividend(); r=self.proof()
        self.assertEqual(Decimal(r['days'][1]['receivable']),Decimal('20'))
        self.assertEqual(Decimal(r['days'][1]['cash']),Decimal('0'))
        self.assertEqual(Decimal(r['final']['receivable']),Decimal('0'))
        self.assertEqual(Decimal(r['final']['cash']),Decimal('20'))
        self.assertEqual(Decimal(r['days'][1]['wealth']),Decimal(r['final']['wealth']))
        self.assertEqual(Decimal(r['final']['wealth']),Decimal('1020'))

    def test_payment_after_scope_keeps_receivable(self):
        self.split(); self.dividend(pay='2026-01-20'); r=self.proof()
        self.assertEqual(Decimal(r['final']['receivable']),Decimal('20'))
        self.assertEqual(Decimal(r['final']['cash']),Decimal('0'))
        self.assertFalse(r['receivables'][0]['paid'])

    def test_repeated_proof_does_not_accumulate_entitlement(self):
        self.split(); self.dividend(); before=self.s.db.total_changes
        a=self.proof(); b=self.proof()
        self.assertEqual(a,b); self.assertEqual(before,self.s.db.total_changes)
        self.assertEqual(len([x for x in a['events'] if x['kind']=='hypothetical_dividend_payment']),1)

    def test_initial_cash_and_zero_shares_are_respected(self):
        self.split(); self.dividend(); r=self.proof(initial_cash=Decimal('5'),initial_shares=Decimal('0'))
        self.assertEqual(Decimal(r['final']['wealth']),Decimal('5'))

    def test_invalid_opening_amounts_and_currency(self):
        for value in (-1,1.0,'1',Decimal('-1'),Decimal('NaN'),Decimal('Infinity')):
            for key in ('initial_cash','initial_shares'):
                with self.subTest(key=key,value=value),self.assertRaises(ContractError):
                    self.proof(**{key:value})
        with self.assertRaises(ContractError): self.proof(currency='EUR')

    def test_opening_must_precede_local_day_not_just_session(self):
        with self.assertRaises(ContractError):
            self.proof(opening_at=datetime(2026,1,5,12,tzinfo=timezone.utc))
        with self.assertRaises(ContractError): self.proof(opening_at=datetime(2026,1,1))

    def test_explicit_share_basis_and_distribution_policy(self):
        self.split(); self.dividend()
        for basis in ('pre_split',None):
            with self.assertRaises(ContractError): self.proof(dividend_share_basis=basis)
        for policy in ('special_distribution','due_bill','cash_in_lieu','withholding',None):
            with self.assertRaises(ContractError): self.proof(dividend_policy=policy)

    def test_missing_price_blocks_all_values(self):
        with self.assertRaises(ContractError):
            corporate_action_replay(self.s,'fixture','l',DATES+['2026-01-08'],
                as_of=T+timedelta(seconds=2),opening_at=T-timedelta(days=10),initial_cash=Decimal(0),
                initial_shares=Decimal(10),currency='USD',dividend_share_basis='post_split',
                dividend_policy='ordinary_cash_no_withholding')

    def test_late_correction_is_separate_hypothetical_proof(self):
        self.split(); self.dividend(); old=self.proof()
        ev=self.s.db.execute('SELECT evidence_id FROM evidence_versions WHERE record_id=?',('cash_dividend'+DATES[1],)).fetchone()[0]
        self.put(DATES[1],'cash_dividend',{'amount':'2','payment_date':DATES[2]},revision_id='2',
                 received_at=T+timedelta(days=1),processed_at=T+timedelta(days=1,seconds=1),correction_of=ev)
        self.assertEqual(old,self.proof())
        new=self.proof(as_of=T+timedelta(days=2))
        self.assertNotEqual(old['manifest_sha256'],new['manifest_sha256'])
        self.assertEqual(Decimal(new['final']['cash']),Decimal('40'))

    def test_unvalued_payment_day_is_recorded_separately(self):
        self.split(); self.dividend(pay='2026-01-08')
        # Explicit date scope skips the payment date; next supplied valuation books it.
        day='2026-01-09'
        self.put(day,'session',{'timezone':'America/New_York'})
        self.put(day,'bar',{'open':'50','high':'50','low':'50','close':'50','volume':'20','price_kind':'raw'})
        args=dict(as_of=T+timedelta(seconds=2),opening_at=T-timedelta(days=10),initial_cash=Decimal(0),
                  initial_shares=Decimal(10),currency='USD',dividend_share_basis='post_split',
                  dividend_policy='ordinary_cash_no_withholding')
        r=corporate_action_replay(self.s,'fixture','l',DATES+[day],**args)
        payment=[x for x in r['events'] if x['kind']=='hypothetical_dividend_payment'][0]
        self.assertEqual(payment['date'],'2026-01-08'); self.assertEqual(payment['valued_on'],day)

    def test_decimal_context_is_frozen_and_manifest_binds_inputs(self):
        self.split(); self.dividend(); a=self.proof()
        with localcontext() as ctx:
            ctx.prec=2; ctx.rounding=ROUND_DOWN; ctx.traps[Rounded]=True
            self.assertEqual(a,self.proof())
        self.assertNotEqual(a['manifest_sha256'],self.proof(initial_cash=Decimal(1))['manifest_sha256'])
        self.assertFalse(a['action_coverage_verified']); self.assertFalse(a['admitted_for_strategy'])

    def test_nonterminating_split_rejects_unspecified_rounding(self):
        self.put(DATES[1],'split',{'new_shares':'1','old_shares':'3'})
        with self.assertRaises(ContractError): self.proof(initial_shares=Decimal('1'))

    def test_known_omitted_session_and_action_block_proof(self):
        self.split()
        args=dict(as_of=T+timedelta(seconds=2),opening_at=T-timedelta(days=10),initial_cash=Decimal(0),
                  initial_shares=Decimal(10),currency='USD',dividend_share_basis='post_split',
                  dividend_policy='ordinary_cash_no_withholding')
        with self.assertRaises(ContractError):
            corporate_action_replay(self.s,'fixture','l',[DATES[0],DATES[2]],**args)
        # Even an action on a date lacking a known session cannot be skipped.
        self.s.db.execute("DELETE FROM market_snapshots WHERE kind='session' AND target_id LIKE '%2026-01-06%'")
        self.s.db.commit()
        with self.assertRaises(ContractError):
            corporate_action_replay(self.s,'fixture','l',[DATES[0],DATES[2]],**args)

    def test_read_savepoint_does_not_commit_open_transaction(self):
        self.s.db.execute('BEGIN')
        self.s.db.execute("INSERT INTO entities VALUES ('pending','Pending')")
        self.proof()
        self.assertTrue(self.s.db.in_transaction)
        self.s.db.rollback()
        self.assertIsNone(self.s.db.execute("SELECT 1 FROM entities WHERE entity_id='pending'").fetchone())

    def test_known_split_between_opening_and_scope_blocks_proof(self):
        self.put('2026-01-04','split',{'new_shares':'2','old_shares':'1'})
        with self.assertRaises(ContractError):
            self.proof(opening_at=datetime(2026,1,3,tzinfo=timezone.utc))

    def test_known_dividend_between_opening_and_scope_blocks_proof(self):
        self.put('2026-01-04','cash_dividend',{'amount':'1','payment_date':'2026-01-07'})
        with self.assertRaises(ContractError):
            self.proof(opening_at=datetime(2026,1,3,tzinfo=timezone.utc))

    def test_actions_before_opening_are_excluded_from_opening_balances(self):
        self.put('2026-01-04','split',{'new_shares':'2','old_shares':'1'})
        self.put('2026-01-04','cash_dividend',{'amount':'1','payment_date':'2026-01-07'})
        # Explicit balances are already as of after those events; prior
        # receivables remain excluded/assumed zero by this bounded proof.
        r=self.proof(opening_at=datetime(2026,1,4,20,tzinfo=timezone.utc))
        self.assertEqual(r['events'],[])
        self.assertEqual(Decimal(r['final']['shares']),Decimal('10'))
        self.assertEqual(Decimal(r['final']['cash']),Decimal('0'))

    def test_action_effective_exactly_at_opening_is_not_silently_skipped(self):
        self.put('2026-01-04','split',{'new_shares':'2','old_shares':'1'})
        with self.assertRaises(ContractError):
            self.proof(opening_at=datetime(2026,1,4,14,30,tzinfo=timezone.utc))

    def test_after_close_split_cannot_apply_to_earlier_raw_close(self):
        day=DATES[1]
        body=dict(kind='split',listing_id='l',date=day,start=day+'T22:00:00Z',
                  end=day+'T23:00:00Z',currency='USD',values={'new_shares':'2','old_shares':'1'})
        self.put(day,'split',body['values'],payload=json.dumps(body).encode())
        with self.assertRaises(ContractError): self.proof()

    def test_intraday_dividend_cannot_be_treated_as_opening_entitlement(self):
        day=DATES[1]
        body=dict(kind='cash_dividend',listing_id='l',date=day,start=day+'T15:00:00Z',
                  end=day+'T16:00:00Z',currency='USD',values={'amount':'1','payment_date':DATES[2]})
        self.put(day,'cash_dividend',body['values'],payload=json.dumps(body).encode())
        with self.assertRaises(ContractError): self.proof()
