"""Immutable corporate-action staging; no publication, coverage or accounting admission."""
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from uuid import UUID

from .alpaca_actions_reader import ACTION_URL, MAX_BYTES, action_query
from .alpaca_normalizer import decode, NormalizationError
from .alpaca_market import canonical
from .brokers import Environment
from .contracts import ContractError, DataOrigin, EvidenceIntegrityError, RecordConflict, Use, required, utc
from .market_data import timestamp
from .store import EvidenceStore

VERSION='alpaca-corporate-actions-1'
SCHEMA='''CREATE TABLE IF NOT EXISTS alpaca_action_jobs (
 source_id TEXT NOT NULL REFERENCES sources,import_id TEXT NOT NULL,body_json TEXT NOT NULL,sha256 TEXT NOT NULL,
 PRIMARY KEY(source_id,import_id));
CREATE TABLE IF NOT EXISTS alpaca_action_pages (
 source_id TEXT NOT NULL,import_id TEXT NOT NULL,page_index INTEGER NOT NULL,body_json TEXT NOT NULL,sha256 TEXT NOT NULL,
 PRIMARY KEY(source_id,import_id,page_index));
CREATE TABLE IF NOT EXISTS alpaca_action_results (
 source_id TEXT NOT NULL,import_id TEXT NOT NULL,body_json TEXT NOT NULL,sha256 TEXT NOT NULL,
 PRIMARY KEY(source_id,import_id));'''


def sha(payload):return hashlib.sha256(payload).hexdigest()
def fingerprint(body):return sha(canonical(body).encode())


def safe_json(value):
    if isinstance(value,Decimal):return str(value)
    if isinstance(value,dict):return {k:safe_json(v) for k,v in value.items()}
    if isinstance(value,list):return [safe_json(v) for v in value]
    return value


def day(value,*,optional=False):
    if value is None and optional:return None
    if not isinstance(value,str) or date.fromisoformat(value).isoformat()!=value:
        raise ContractError('invalid_date')
    return value


def amount(value):
    if isinstance(value,(bool,float)) or not isinstance(value,(int,Decimal,str)):
        raise ContractError('invalid_exact_amount')
    result=Decimal(value)
    if not result.is_finite() or result<=0 or result.adjusted()>24 or result.as_tuple().exponent < -18:
        raise ContractError('invalid_exact_amount')
    return str(result)


def normalize_page(payload,query,listing_id):
    """Keep process/ex/payment dates distinct; unknown publication stays None."""
    candidates=[];quarantine=[];token=None;pagination='unknown'
    try:
        if not isinstance(payload,bytes) or not 0<len(payload)<=MAX_BYTES:raise ContractError('invalid_action_payload')
        root=decode(payload)
        if not isinstance(root,dict) or set(root)-{'corporate_actions','next_page_token'} or not isinstance(root.get('corporate_actions'),dict):
            raise ContractError('invalid_action_envelope')
        if 'next_page_token' in root:
            token=root['next_page_token']
            if token is not None:
                action_query(query['symbols'],query['start'],query['end'],page_token=token,limit=int(query['limit']))
            pagination='terminal_page' if token is None else 'next_page'
        for kind,rows in root['corporate_actions'].items():
            if not isinstance(rows,list):
                quarantine.append(dict(path=kind,reason='invalid_action_group'));continue
            for index,row in enumerate(rows):
                path=kind+'['+str(index)+']'
                try:
                    if kind not in {'forward_splits','reverse_splits','cash_dividends'}:
                        raise ContractError('unsupported_action_type')
                    if not isinstance(row,dict):raise ContractError('invalid_action_row')
                    native_id=str(UUID(required(row.get('id'),'native_id')))
                    if row.get('symbol')!=query['symbols']:raise ContractError('symbol_binding_mismatch')
                    process=day(row.get('process_date'));ex=day(row.get('ex_date'))
                    if not query['start']<=process<=query['end']:raise ContractError('process_date_outside_request')
                    payable=day(row.get('payable_date'),optional=True)
                    record=day(row.get('record_date'),optional=True)
                    currency=row.get('currency')
                    if currency is not None and currency!='USD':raise ContractError('unsupported_action_currency')
                    blockers=[] if currency else ['provider_currency_unknown']
                    due={k:day(v,optional=True) for k,v in row.items() if k.startswith('due_bill_')}
                    if any(v is not None for v in due.values()):blockers.append('due_bill_terms_unreviewed')
                    if kind=='cash_dividends':
                        if row.get('special') is not False or row.get('foreign') is not False:
                            raise ContractError('special_foreign_or_incomplete_dividend_unsupported')
                        if payable is None or payable<ex:raise ContractError('unsupported_dividend_payment_date')
                        values=dict(amount=amount(row.get('rate')))
                    else:
                        new,old=amount(row.get('new_rate')),amount(row.get('old_rate'))
                        if (kind=='forward_splits' and Decimal(new)<=Decimal(old)) or (kind=='reverse_splits' and Decimal(new)>=Decimal(old)):
                            raise ContractError('split_direction_ratio_mismatch')
                        values=dict(new_shares=new,old_shares=old)
                    candidates.append(dict(provider_id=native_id,provider_kind=kind,listing_id=listing_id,
                        symbol=row['symbol'],process_date=process,ex_date=ex,payable_date=payable,record_date=record,
                        currency=currency,values=values,due_bill_dates=due,
                        identity={k:row.get(k) for k in ('cusip','old_cusip','new_cusip','isin')},
                        identity_verified=False,published_at=None,accounting_ready=False,accounting_blockers=blockers,
                        source_path=path,provider_row_sha256=fingerprint(safe_json(row))))
                except (ContractError,ValueError,TypeError,ArithmeticError) as error:
                    # Stable field diagnostics, never stringify a provider row.
                    reason=str(error) if isinstance(error,ContractError) else 'invalid_action_field'
                    quarantine.append(dict(path=path,reason=reason))
    except (ContractError,NormalizationError,ValueError,TypeError,ArithmeticError,RecursionError):
        candidates=[];quarantine=[dict(path='$',reason='invalid_action_envelope')];pagination='unknown';token=None
    return dict(normalizer_version=VERSION,candidates=candidates,quarantine=quarantine,
        next_page_token=token,pagination_state=pagination,published_at=None,
        effective_date_coverage_verified=False,accounting_ready=False)


class CorporateActionStore(EvidenceStore):
    def __init__(self,database):
        super().__init__(database);self.db.executescript(SCHEMA)

    def _write(self,table,body,*,index=None):
        fields=dict(source_id=body['source_id'],import_id=body['import_id'])
        if index is not None:fields['page_index']=index
        key=dict(fields);fields.update(body_json=canonical(body),sha256=fingerprint(body))
        self._immutable(table,key,fields)

    def _verified(self,row):
        body=json.loads(row['body_json'])
        if fingerprint(body)!=row['sha256'] or any(body[k]!=row[k] for k in ('source_id','import_id')):
            raise EvidenceIntegrityError('Corporate action journal integrity failed')
        if 'page_index' in row.keys() and body['page_index']!=row['page_index']:
            raise EvidenceIntegrityError('Corporate action page index mismatch')
        return body

    def _raw(self,digest):
        row=self.db.execute('SELECT payload FROM raw_objects WHERE sha256=?',(digest,)).fetchone()
        if row is None or sha(row[0])!=digest:raise EvidenceIntegrityError('Corporate action raw hash failed')
        return row[0]

    def _archive(self,payload):
        digest=sha(payload)
        self.db.execute('INSERT OR IGNORE INTO raw_objects VALUES (?,?)',(digest,payload))
        if self._raw(digest)!=payload:raise EvidenceIntegrityError('Corporate action archive mismatch')
        return digest

    def pages(self,job):
        result=[];token=None
        for index,row in enumerate(self.db.execute('SELECT * FROM alpaca_action_pages WHERE source_id=? AND import_id=? ORDER BY page_index',
                                                  (job['source_id'],job['import_id']))):
            page=self._verified(row);query=dict(job['request']['query'])
            if index and token is None:raise EvidenceIntegrityError('Action pages after terminal token')
            if token is not None:query['page_token']=token
            if (page['page_index']!=index or page['provenance']!=dict(method='GET',endpoint=ACTION_URL,query=query,route=job['request']['route'])
                    or page['available_at']<page['received_at'] or page['received_at']<job['known_at']):
                raise EvidenceIntegrityError('Corporate action page provenance/clock mismatch')
            raw=self._raw(page['raw_sha256'])
            if len(raw)>MAX_BYTES:raise EvidenceIntegrityError('Corporate action page exceeds bound')
            if page['normalized']!=normalize_page(raw,query,job['request']['listing']['listing_id']):
                raise EvidenceIntegrityError('Corporate action normalization mismatch')
            result.append(page);token=page['normalized']['next_page_token']
        return result

    def inspect_job(self,source_id,import_id,*,as_of,clock=None):
        now=(clock or (lambda:datetime.now(timezone.utc)))();at=utc(as_of)
        if at>utc(now):raise ContractError('Future corporate action cutoff unsupported')
        for cutoff in (as_of,now):
            for use in (Use.STORAGE,Use.RESEARCH):self.require_use(source_id,use,as_of=cutoff)
        self.db.execute('SAVEPOINT action_read')
        try:
            row=self.db.execute('SELECT * FROM alpaca_action_jobs WHERE source_id=? AND import_id=?',(source_id,import_id)).fetchone()
            if row is None:return None
            job=self._verified(row)
            terminal=self.db.execute('SELECT * FROM alpaca_action_results WHERE source_id=? AND import_id=?',(source_id,import_id)).fetchone()
            if terminal is None:return None
            report=self._verified(terminal);pages=self.pages(job)
            if job['known_at']>at or report['available_at']>at or any(p['available_at']>at for p in pages):return None
            if report['page_hashes']!=[fingerprint(p) for p in pages]:raise EvidenceIntegrityError('Corporate action result/page mismatch')
            account=report.get('account_proof')
            if account is not None:
                raw=self._raw(account['raw_sha256'])
                from .alpaca_reader import PAPER_HOST
                if (account['endpoint']!=PAPER_HOST+'/v2/account' or not job['known_at']<=account['received_at']<=report['available_at']
                        or json.loads(raw).get('account_number')!=job['request']['route']['account_id']):
                    raise EvidenceIntegrityError('Archived paper account differs from action route')
            candidates=[dict(c,known_at=p['available_at'],received_at=p['received_at'],raw_sha256=p['raw_sha256'])
                        for p in pages for c in p['normalized']['candidates']]
            if report['candidate_count']!=len(candidates) or report['page_count']!=len(pages):
                raise EvidenceIntegrityError('Corporate action result counts differ')
            issues=[];seen=set()
            for page in pages:
                for candidate in page['normalized']['candidates']:
                    if candidate['provider_id'] in seen:
                        issues.append(dict(reason='duplicate_action_id',provider_id=candidate['provider_id'],page_index=page['page_index']))
                    seen.add(candidate['provider_id'])
            counts=Counter(q['reason'] for p in pages for q in p['normalized']['quarantine'])
            counts.update(q['reason'] for q in issues)
            terminal=bool(pages and pages[-1]['normalized']['pagination_state']=='terminal_page')
            if (report['issues']!=issues or report['quarantine_reasons']!=dict(counts)
                    or report['quarantine_count']!=sum(counts.values()) or report['process_pages_complete']!=terminal
                    or report['account_match_verified']!=(account is not None)
                    or (report['state']=='complete_pages' and (not terminal or counts))
                    or any(report[k] is not False for k in ('effective_date_coverage_verified','publication_verified','accounting_ready','dataset_admitted','live_trading'))):
                raise EvidenceIntegrityError('Corporate action result status/coverage integrity failed')
            body=dict(job=job,result=report,candidates=candidates,raw_hashes=[p['raw_sha256'] for p in pages],
                      dataset_admitted=False,coverage_verified=False,publication_verified=False,live_trading=False)
            body['manifest_sha256']=fingerprint(body);return body
        finally:
            self.db.execute('ROLLBACK TO action_read');self.db.execute('RELEASE action_read')


def sync_actions(store,*,source_id,import_id,route,binding,listing,symbol,process_start,process_end,
                 account_reader,action_reader,clock=None,max_pages=10,max_bytes=20_000_000):
    if store.db.in_transaction:raise ContractError('Action sync requires idle connection')
    now=clock or (lambda:datetime.now(timezone.utc));checked=now()
    required(import_id,'import_id');required(source_id,'source_id')
    query=action_query(symbol,process_start,process_end)
    from .data_admission import _scope
    _scope(binding)
    found=store.db.execute('SELECT * FROM listings WHERE listing_id=?',(listing['listing_id'],)).fetchone()
    if found is None or dict(found)!=listing or listing['listing_id']!=binding['listing_id']:
        raise ContractError('Explicit matching canonical listing binding required')
    kind=store.db.execute('SELECT kind FROM instruments WHERE instrument_id=?',(listing['instrument_id'],)).fetchone()
    if kind is None or kind[0] not in {'equity','etf'}:
        raise ContractError('Corporate action pilot supports equity/ETF listings only')
    if source_id in (binding['price_source_id'],binding['calendar_source_id']):
        raise ContractError('Separate corporate action source required')
    if route.broker_id!='alpaca' or route.environment!=Environment.PAPER:raise ContractError('Paper route required')
    if type(max_pages) is not int or not 1<=max_pages<=100 or type(max_bytes) is not int or not 1<=max_bytes<=100_000_000:
        raise ContractError('Bounded action collection limits required')
    for use in (Use.STORAGE,Use.RESEARCH):store.require_use(source_id,use,as_of=checked)
    origin=store.db.execute('SELECT origin FROM sources WHERE source_id=?',(source_id,)).fetchone()
    if origin is None or origin[0]!=DataOrigin.PROVIDER.value:raise ContractError('Declared provider action source required')
    request=dict(version=VERSION,query=query,route=asdict(route),binding=binding,listing=listing,max_pages=max_pages,max_bytes=max_bytes)
    with store.db:
        store.db.execute('BEGIN IMMEDIATE')
        old=store.db.execute('SELECT * FROM alpaca_action_jobs WHERE source_id=? AND import_id=?',(source_id,import_id)).fetchone()
        if old is not None:
            job=store._verified(old)
            if job['request']!=request:raise RecordConflict('Action import ID belongs to a different immutable scope')
        else:
            job=dict(source_id=source_id,import_id=import_id,known_at=utc(checked),request=request)
            store._write('alpaca_action_jobs',job)
    if old is not None:
        result=store.inspect_job(source_id,import_id,as_of=now(),clock=now)
        if result is not None:return result
        raise ContractError('Prior action attempt is incomplete; inspect and use a new import ID')
    token=None;tokens=set();pages=[];issues=[];seen=set();used=0;account_proof=None
    state='incomplete';reason='page_limit';stage='account_match';error_code=None
    try:
        from .alpaca_reader import PAPER_HOST
        account=account_reader.read('account')
        if (account.source_url!=PAPER_HOST+'/v2/account' or account.environment!=Environment.PAPER
                or not checked<=account.received_at<=now() or json.loads(account.payload).get('account_number')!=route.account_id):
            raise ContractError('Paper account does not match action route')
        with store.db:
            account_proof=dict(endpoint=account.source_url,received_at=utc(account.received_at),raw_sha256=store._archive(account.payload))
        stage='actions_get'
        for index in range(max_pages):
            before=now();response=action_reader.read(symbol,process_start,process_end,page_token=token,limit=1000)
            expected=action_query(symbol,process_start,process_end,page_token=token)
            from .alpaca_actions_reader import ActionRead
            if not isinstance(response,ActionRead) or response.route!=route or response.query!=expected or not before<=response.received_at<=now():
                raise ContractError('Action response query/route/receipt mismatch')
            if used+len(response.payload)>max_bytes:reason='byte_limit';break
            normalized=normalize_page(response.payload,expected,listing['listing_id'])
            page=dict(source_id=source_id,import_id=import_id,page_index=index,raw_sha256=sha(response.payload),
                received_at=utc(response.received_at),available_at=utc(now()),provenance=response.provenance,normalized=normalized)
            with store.db:
                store._archive(response.payload);store._write('alpaca_action_pages',page,index=index)
            pages.append(page);used+=len(response.payload)
            for candidate in normalized['candidates']:
                identity=candidate['provider_id']
                if identity in seen:issues.append(dict(reason='duplicate_action_id',provider_id=identity,page_index=index))
                seen.add(identity)
            if normalized['pagination_state']=='unknown':state='quarantined';reason='pagination_unknown';break
            token=normalized['next_page_token']
            if token is None:
                state='quarantined' if issues or any(p['normalized']['quarantine'] for p in pages) else 'complete_pages'
                reason='terminal_page';break
            if token in tokens:reason='token_cycle';break
            tokens.add(token)
    except Exception as error:
        state='failed';reason='capture_failed_no_retry'
        from .alpaca_actions_reader import ActionReadError
        error_code=error.code if isinstance(error,ActionReadError) else type(error).__name__
    available=utc(now())
    if available<job['known_at'] or any(p['available_at']>available for p in pages):raise ContractError('Action sync clock moved backwards')
    counts=Counter(q['reason'] for p in pages for q in p['normalized']['quarantine'])
    counts.update(q['reason'] for q in issues)
    report=dict(source_id=source_id,import_id=import_id,available_at=available,state=state,reason=reason,stage=stage,
        error_code=error_code,account_proof=account_proof,account_match_verified=account_proof is not None,
        page_count=len(pages),page_hashes=[fingerprint(p) for p in pages],
        candidate_count=sum(len(p['normalized']['candidates']) for p in pages),
        quarantine_count=sum(counts.values()),quarantine_reasons=dict(counts),issues=issues,
        process_pages_complete=reason=='terminal_page',effective_date_coverage_verified=False,
        publication_verified=False,accounting_ready=False,dataset_admitted=False,live_trading=False)
    with store.db:store._write('alpaca_action_results',report)
    return store.inspect_job(source_id,import_id,as_of=now(),clock=now)
