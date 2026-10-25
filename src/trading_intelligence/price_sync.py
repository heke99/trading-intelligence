"""Read-only bounded price pagination with durable raw pages and terminal reports."""
from dataclasses import asdict
from datetime import datetime,timezone
import hashlib
import json

from .alpaca_market import canonical
from .alpaca_price_reader import price_query,PriceRead,PriceReadError,MAX_PRICE_BYTES
from .brokers import BrokerAccount,Environment
from .contracts import ContractError,DataOrigin,EvidenceIntegrityError,RecordConflict,Use,required,utc

SCHEMA='''
CREATE TABLE IF NOT EXISTS price_sync_jobs (
 source_id TEXT NOT NULL REFERENCES sources,import_id TEXT NOT NULL,input_json TEXT NOT NULL,
 created_at TEXT NOT NULL,integrity_sha TEXT NOT NULL,PRIMARY KEY(source_id,import_id));
CREATE TABLE IF NOT EXISTS price_sync_pages (
 source_id TEXT NOT NULL,import_id TEXT NOT NULL,page_index INTEGER NOT NULL,
 body_json TEXT NOT NULL,integrity_sha TEXT NOT NULL,PRIMARY KEY(source_id,import_id,page_index),
 FOREIGN KEY(source_id,import_id) REFERENCES price_sync_jobs);
CREATE TABLE IF NOT EXISTS price_sync_results (
 source_id TEXT NOT NULL,import_id TEXT NOT NULL,available_at TEXT NOT NULL,
 body_json TEXT NOT NULL,integrity_sha TEXT NOT NULL,PRIMARY KEY(source_id,import_id),
 FOREIGN KEY(source_id,import_id) REFERENCES price_sync_jobs);
'''


def _hash(value):return hashlib.sha256(canonical(value).encode()).hexdigest()


def _pages(store,source_id,import_id,as_of):
    pages=[]
    for row in store.db.execute('SELECT * FROM price_sync_pages WHERE source_id=? AND import_id=? ORDER BY page_index',(source_id,import_id)):
        fields={k:row[k] for k in ('source_id','import_id','page_index','body_json')}
        if _hash(fields)!=row['integrity_sha']:raise EvidenceIntegrityError('Price page journal integrity failed')
        page=json.loads(row['body_json'])
        capture=store.capture_as_of(source_id,page['capture_id'],as_of=as_of)
        if capture is None or capture['raw_sha']!=page['raw_sha']:raise EvidenceIntegrityError('Price page capture is unavailable or inconsistent')
        if page['page_index']!=len(pages):raise EvidenceIntegrityError('Price page journal is not contiguous')
        pages.append(page)
    return pages


def sync_prices(store,*,source_id,import_id,route,symbol_listings,start_date,end_date,
                feed,reader,clock=None,max_pages=10,max_total_bytes=20_000_000,page_limit=1000):
    """Fetch explicit daily raw bars into staging, never research admission.

    Terminal retries reuse their original report without refetching. A job
    interrupted before its terminal report is marked incomplete on retry; a
    new explicit import ID is required to retry the bounded request. Prior raw
    pages remain inspectable. Keys and provider response errors are never logged.
    """
    if store.db.in_transaction:raise ContractError('Price synchronization requires an idle connection')
    required(source_id,'source_id');required(import_id,'import_id')
    if not isinstance(route,BrokerAccount) or route.broker_id!='alpaca' or route.environment!=Environment.PAPER:raise ContractError('Explicit Alpaca paper route required')
    if not isinstance(symbol_listings,dict) or not symbol_listings:raise ContractError('Explicit symbol listing map required')
    query=price_query(list(symbol_listings),start_date,end_date,feed=feed,limit=page_limit)
    if type(max_pages) is not int or not 1<=max_pages<=100 or type(max_total_bytes) is not int or not 1<=max_total_bytes<=200_000_000:
        raise ContractError('Bounded integer pages and total bytes required')
    for symbol,listing in symbol_listings.items():
        required(listing,'listing_id')
        row=store.db.execute('SELECT trading_currency FROM listings WHERE listing_id=?',(listing,)).fetchone()
        if row is None or row[0]!='USD':raise ContractError('Explicit USD listing required')
    if len(set(symbol_listings.values()))!=len(symbol_listings):raise ContractError('Duplicate listing bindings')
    now=clock or (lambda:datetime.now(timezone.utc));checked=now();utc(checked)
    for use in (Use.STORAGE,Use.RESEARCH):store.require_use(source_id,use,as_of=checked)
    origin=store.db.execute('SELECT origin FROM sources WHERE source_id=?',(source_id,)).fetchone()
    if origin is None or origin[0]!=DataOrigin.PROVIDER.value:raise ContractError('Network synchronization requires a declared provider source')
    store.db.executescript(SCHEMA)
    inputs=canonical(dict(version='price-sync-1',route=asdict(route),symbol_listings=symbol_listings,query=query,max_pages=max_pages,max_total_bytes=max_total_bytes))
    old=store.db.execute('SELECT * FROM price_sync_jobs WHERE source_id=? AND import_id=?',(source_id,import_id)).fetchone()
    if old:
        fields={k:old[k] for k in ('source_id','import_id','input_json','created_at')}
        if _hash(fields)!=old['integrity_sha']:raise EvidenceIntegrityError('Price request journal integrity failed')
        if old['input_json']!=inputs:raise RecordConflict('Price import ID belongs to another request')
        if old['created_at']>utc(checked):raise ContractError('Request journal is not yet available')
        result=store.db.execute('SELECT * FROM price_sync_results WHERE source_id=? AND import_id=?',(source_id,import_id)).fetchone()
        if result:
            fields={k:result[k] for k in ('source_id','import_id','available_at','body_json')}
            if _hash(fields)!=result['integrity_sha']:raise EvidenceIntegrityError('Price result journal integrity failed')
            if result['available_at']>utc(checked):raise ContractError('Price result not yet available')
            pages=_pages(store,source_id,import_id,checked)
            answer=json.loads(result['body_json'])
            if answer['pages']!=pages:raise EvidenceIntegrityError('Price result and page journal disagree')
            return answer
        pages=_pages(store,source_id,import_id,checked)
        state,reason='incomplete','interrupted_previous_run'
    else:
        fields=dict(source_id=source_id,import_id=import_id,input_json=inputs,created_at=utc(checked))
        with store.db:store.db.execute('INSERT INTO price_sync_jobs VALUES (?,?,?,?,?)',(source_id,import_id,inputs,fields['created_at'],_hash(fields)))
        pages=[];token=None;tokens=set();used=0;identities=set();state,reason='incomplete','page_limit'
        for index in range(max_pages):
            if used>=max_total_bytes:reason='byte_limit';break
            # Permissions are rechecked before every external request.
            for use in (Use.STORAGE,Use.RESEARCH):store.require_use(source_id,use,as_of=now())
            try:
                read=reader.read(list(symbol_listings),start_date,end_date,feed=feed,page_token=token,limit=page_limit,max_bytes=min(MAX_PRICE_BYTES,max_total_bytes-used))
            except PriceReadError:
                reason='read_failed';break
            expected=price_query(list(symbol_listings),start_date,end_date,feed=feed,page_token=token,limit=page_limit)
            if not isinstance(read,PriceRead) or read.route!=route or read.query!=expected:
                raise ContractError('Price response route or query mismatch')
            if utc(read.received_at)<utc(checked):raise ContractError('Price receipt precedes synchronization request')
            if used+len(read.payload)>max_total_bytes:reason='byte_limit';break
            capture_id=canonical([import_id,'price-page',index])
            capture=store.import_bars(source_id=source_id,import_id=capture_id,payload=read.payload,received_at=read.received_at,processed_at=now(),symbol_listings=symbol_listings,feed=feed,timeframe='1Day',adjustment='raw',market_timezone='America/New_York',request_currency='USD')
            page=dict(page_index=index,capture_id=capture_id,raw_sha=capture['raw_sha'],available_at=capture['available_at'],provenance=read.provenance,byte_count=len(read.payload),next_page_token=capture['next_page_token'])
            encoded=canonical(page);fields=dict(source_id=source_id,import_id=import_id,page_index=index,body_json=encoded)
            with store.db:store.db.execute('INSERT INTO price_sync_pages VALUES (?,?,?,?,?)',(source_id,import_id,index,encoded,_hash(fields)))
            pages.append(page);used+=len(read.payload)
            if any(not start_date<=candidate['date']<=end_date for candidate in capture['candidates']):
                state,reason='quarantined','response_outside_request';break
            keys={(candidate['listing_id'],candidate['date']) for candidate in capture['candidates']}
            if keys & identities:
                state,reason='quarantined','duplicate_cross_page_bar';break
            identities.update(keys)
            if capture['quarantined']:state,reason='quarantined','invalid_page_records';break
            if capture['pagination_state']=='unknown':reason='pagination_unknown';break
            next_token=capture['next_page_token']
            if next_token is None:state,reason='complete_pages','terminal_page';break
            if next_token in tokens or next_token==token:reason='pagination_cycle';break
            tokens.add(next_token);token=next_token
    available=utc(now())
    if available<utc(checked) or (pages and available<max(p['available_at'] for p in pages)):raise ContractError('Processing clock moved backwards')
    answer=dict(version='price-sync-1',source_id=source_id,import_id=import_id,state=state,reason=reason,available_at=available,
                pages=pages,request=json.loads(inputs),pages_complete=state=='complete_pages',
                published_at=None,authenticated_account_verified=False,market_admitted=False,
                training_ready=False,full_history_verified=False,live_trading=False)
    encoded=canonical(answer);fields=dict(source_id=source_id,import_id=import_id,available_at=available,body_json=encoded)
    with store.db:store.db.execute('INSERT INTO price_sync_results VALUES (?,?,?,?,?)',(source_id,import_id,available,encoded,_hash(fields)))
    return answer
