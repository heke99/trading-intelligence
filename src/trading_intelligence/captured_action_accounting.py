"""Evidence-bound conditional holdings preview; never applies provider actions."""
from datetime import datetime
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import json
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError

from .alpaca_actions import CorporateActionStore
from .contracts import ContractError,EvidenceIntegrityError,RecordConflict,Use,required,utc
from .event_analysis import canonical,digest
from .event_opportunity import fields,instant,number

SCHEMA='''CREATE TABLE IF NOT EXISTS captured_action_previews (
 preview_id TEXT PRIMARY KEY,available_at TEXT NOT NULL,body TEXT NOT NULL,sha256 TEXT NOT NULL);'''

class CapturedActionAccountingStore(CorporateActionStore):
    def __init__(self,database,*,clock=None):
        super().__init__(database)
        from datetime import timezone
        self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.db.executescript(SCHEMA)

    def _proof(self,evidence_id,at,current):
        row=self.db.execute('SELECT e.*,r.payload FROM evidence_versions e JOIN raw_objects r USING(sha256) WHERE evidence_id=?',(evidence_id,)).fetchone()
        if row is None or row['received_at']>at or row['published_at']>row['received_at']:
            raise ContractError('Available original accounting evidence required')
        for cutoff in (at,current):
            for use in (Use.STORAGE,Use.RESEARCH):self._require_use(row['source_id'],use,cutoff)
        if hashlib.sha256(row['payload']).hexdigest()!=row['sha256']:
            raise EvidenceIntegrityError('Accounting backing evidence corrupt')
        if len(row['payload'])>200000:raise ContractError('Accounting evidence exceeds bound')
        def pairs(items):
            result={}
            for key,value in items:
                if key in result:raise ContractError('Duplicate accounting JSON key')
                result[key]=value
            return result
        raw=json.loads(row['payload'],object_pairs_hook=pairs)
        return raw,{k:row[k] for k in ('evidence_id','source_id','sha256','published_at','received_at')}

    def _evaluate(self,source_id,import_id,opening_id,policy_id,at,current,valuation):
        captured=self.inspect_job(source_id,import_id,as_of=datetime.fromisoformat(at.replace('Z','+00:00')),clock=self.clock)
        if captured is None:raise ContractError('Available corporate-action capture required')
        opening,ob=self._proof(opening_id,at,current);policy,pb=self._proof(policy_id,at,current)
        fields(opening,('route','listing_id','currency','units','cash','at','unchanged_holdings_through','opening_receivables_clear'))
        fields(policy,('version','timezone','rules','dividend_treatment','fractional_policy'))
        required(policy['version'],'policy version')
        try:zone=ZoneInfo(policy['timezone'])
        except (ZoneInfoNotFoundError,TypeError):raise ContractError('Explicit market timezone required') from None
        if policy['dividend_treatment']!='gross_no_tax_or_fees' or policy['fractional_policy']!='block':
            raise ContractError('Unsupported supplied accounting policy')
        start=instant(opening['at'])
        if not start<=valuation<=at:raise ContractError('Opening/valuation/cutoff ordering invalid')
        if type(opening['opening_receivables_clear']) is not bool:raise ContractError('Explicit opening receivable assertion required')
        units=number(opening['units'],positive=True);cash=number(opening['cash'])
        if cash<0 or units!=units.to_integral_value():raise ContractError('Nonnegative cash and whole long shares required')
        listing=captured['job']['request']['listing']
        if opening['route']!=captured['job']['request']['route'] or opening['listing_id']!=listing['listing_id'] or opening['currency']!=listing['trading_currency']:
            raise ContractError('Opening identity/currency differs from exact capture')
        candidates=captured['candidates'];rules=policy['rules']
        if not isinstance(rules,list) or len(rules)>5000 or len(rules)!=len(candidates):
            raise ContractError('One explicit reviewed rule per captured candidate required')
        by_id={r.get('provider_id'):r for r in rules if isinstance(r,dict)}
        if len(by_id)!=len(rules) or set(by_id)!={c['provider_id'] for c in candidates}:
            raise ContractError('Rule identities must match captured candidates exactly')
        steps=[];blockers=[];sequences=set()
        if captured['result']['state']!='complete_pages':blockers.append('capture_incomplete_or_quarantined')
        if instant(opening['unchanged_holdings_through'])<valuation:blockers.append('intervening_holdings_unknown')
        if not opening['opening_receivables_clear']:blockers.append('opening_entitlements_unknown')
        for candidate in candidates:
            rule=by_id[candidate['provider_id']]
            fields(rule,('provider_id','provider_row_sha256','listing_id','currency','identity_reviewed','terms_reviewed','effective_at','payment_at','sequence'))
            if (rule['provider_row_sha256']!=candidate['provider_row_sha256'] or rule['listing_id']!=opening['listing_id']
                    or rule['currency']!=opening['currency'] or (candidate['currency'] is not None and candidate['currency']!=rule['currency'])):
                raise ContractError('Reviewed rule must bind exact provider revision/identity/currency')
            if type(rule['sequence']) is not int or rule['sequence']<0 or rule['sequence'] in sequences:
                raise ContractError('Unique explicit action sequence required')
            sequences.add(rule['sequence'])
            for flag in ('identity_reviewed','terms_reviewed'):
                if type(rule[flag]) is not bool:raise ContractError('Explicit review assertions required')
                if not rule[flag]:blockers.append('action_'+flag+'_missing')
            if any(v is not None for v in candidate['due_bill_dates'].values()):blockers.append('due_bill_terms_unsupported')
            effective=instant(rule['effective_at'])
            local=lambda stamp:datetime.fromisoformat(stamp.replace('Z','+00:00')).astimezone(zone).date().isoformat()
            if local(effective)!=candidate['ex_date']:raise ContractError('Supplied effective instant must match source ex-date in market timezone')
            payment=None
            if candidate['provider_kind']=='cash_dividends':
                if rule['payment_at'] is None:blockers.append('payment_instant_unknown')
                else:
                    payment=instant(rule['payment_at'])
                    if local(payment)!=candidate['payable_date'] or payment<effective:raise ContractError('Payment instant/date ordering invalid')
                if effective<=start and (payment is None or payment>start):blockers.append('preopening_dividend_entitlement_unknown')
            elif rule['payment_at'] is not None:raise ContractError('Split has no cash-payment instant in this scope')
            steps.append((effective,rule['sequence'],candidate,payment))
        steps.sort(key=lambda x:(x[0],x[1]))
        receivables={};journal=[]
        with localcontext() as context:
            context.prec=100
            for effective,sequence,candidate,payment in steps:
                if not start<effective<=valuation:continue
                if candidate['provider_kind'] in ('forward_splits','reverse_splits'):
                    ratio=Fraction(number(candidate['values']['new_shares']))/Fraction(number(candidate['values']['old_shares']))
                    exact=Fraction(units)*ratio
                    if exact.denominator!=1:
                        blockers.append('fractional_split_requires_cash_in_lieu_policy');continue
                    units=Decimal(exact.numerator)
                    if units>Decimal('1e15'):raise ContractError('Resulting holding exceeds preview bound')
                    journal.append(dict(provider_id=candidate['provider_id'],kind='split',at=effective,units_after=str(units),sequence=sequence))
                else:
                    amount=units*number(candidate['values']['amount'],positive=True)
                    paid=payment is not None and payment<=valuation
                    if paid:cash+=amount
                    else:receivables[candidate['provider_id']]=str(amount)
                    journal.append(dict(provider_id=candidate['provider_id'],kind='dividend',ex_at=effective,
                        payment_at=payment,eligible_units=str(units),gross_amount=str(amount),paid=paid,sequence=sequence))
        result=dict(route=opening['route'],listing_id=opening['listing_id'],currency=opening['currency'],status='blocked' if blockers else 'conditional_preview',blockers=sorted(set(blockers)),
            closing=None if blockers else dict(units=str(units),cash=str(cash),dividend_receivables=receivables),
            illustrative_steps=journal,coverage_verified=False,accounting_ready=False,dataset_admitted=False,
            source_review_assertions_are_supplied=True,historical_predictive_evaluation_valid=False,
            holdings_or_cash_written=False,orders_sent=0,live_trading=False)
        return captured,ob,pb,result

    def preview(self,preview_id,source_id,import_id,opening_id,policy_id,*,as_of,valuation_at):
        required(preview_id,'preview_id')
        if self.db.in_transaction:raise ContractError('Idle connection required')
        at,current,valuation=utc(as_of),utc(self.clock()),utc(valuation_at)
        if at>current:raise ContractError('Future knowledge cutoff rejected')
        self.db.execute('BEGIN IMMEDIATE')
        try:
            old=self.db.execute('SELECT * FROM captured_action_previews WHERE preview_id=?',(preview_id,)).fetchone()
            config=dict(source_id=source_id,import_id=import_id,opening_id=opening_id,policy_id=policy_id,as_of=at,valuation_at=valuation)
            if old:
                body=self.get_preview(preview_id,as_of=self.clock())
                if body['configuration']!=config:raise RecordConflict('Preview ID already bound to other inputs')
            else:
                captured,ob,pb,result=self._evaluate(source_id,import_id,opening_id,policy_id,at,current,valuation)
                completed=utc(self.clock())
                if completed<current:raise ContractError('Operational clock moved backwards')
                self._evaluate(source_id,import_id,opening_id,policy_id,at,completed,valuation)
                body=dict(preview_id=preview_id,configuration=config,available_at=completed,action_manifest_sha256=captured['manifest_sha256'],
                    opening_evidence=ob,policy_evidence=pb,result=result,version='captured-actions-preview-1')
                self.db.execute('INSERT INTO captured_action_previews VALUES (?,?,?,?)',(preview_id,completed,canonical(body),digest(body)))
            self.db.commit();return body
        except BaseException:self.db.rollback();raise

    def get_preview(self,preview_id,*,as_of):
        at,current=utc(as_of),utc(self.clock())
        if at>current:raise ContractError('Future knowledge cutoff rejected')
        self.db.execute('SAVEPOINT accounting_preview_read')
        try:
            row=self.db.execute('SELECT * FROM captured_action_previews WHERE preview_id=? AND available_at<=?',(preview_id,at)).fetchone()
            if row is None:return None
            body=json.loads(row['body'])
            if digest(body)!=row['sha256'] or body['preview_id']!=preview_id or body['available_at']!=row['available_at']:
                raise EvidenceIntegrityError('Accounting preview manifest corrupt')
            c=body['configuration']
            captured,ob,pb,_=self._evaluate(c['source_id'],c['import_id'],c['opening_id'],c['policy_id'],c['as_of'],current,c['valuation_at'])
            if (captured['manifest_sha256']!=body['action_manifest_sha256'] or ob!=body['opening_evidence'] or pb!=body['policy_evidence']):
                raise EvidenceIntegrityError('Accounting preview dependencies changed')
            return body
        finally:self.db.execute('ROLLBACK TO accounting_preview_read');self.db.execute('RELEASE accounting_preview_read')


def main():
    import argparse
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    for option in ('database','preview-id','source-id','import-id','opening-evidence-id','policy-evidence-id','as-of','valuation-at'):
        parser.add_argument('--'+option,required=True)
    args=parser.parse_args()
    try:
        if not Path(args.database).is_file():raise ContractError('Existing source-configured database required')
        with CapturedActionAccountingStore(args.database) as store:
            result=store.preview(args.preview_id,args.source_id,args.import_id,args.opening_evidence_id,args.policy_evidence_id,
                as_of=datetime.fromisoformat(args.as_of.replace('Z','+00:00')),
                valuation_at=datetime.fromisoformat(args.valuation_at.replace('Z','+00:00')))
    except (ContractError,ValueError,OSError) as error:
        parser.exit(2,'Captured accounting preview rejected: '+str(error)+'\n')
    print(json.dumps(result,sort_keys=True,indent=2))


if __name__=='__main__':main()
