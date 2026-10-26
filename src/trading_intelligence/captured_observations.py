"""Current-rights inspection of declared captured prices/calendar, never admission."""
from datetime import datetime,timezone,date
import hashlib
import json
from zoneinfo import ZoneInfo
from .alpaca_market import canonical
from .alpaca_price_reader import PRICE_URL
from .contracts import ContractError,EvidenceIntegrityError,Use,required,utc
from .market_data import timestamp,decimal_text
from decimal import Decimal
from .price_sync import _pages


def inspect_captures(store,*,price_source_id,price_import_id,calendar_source_id,calendar_import_id,listing_id,expected_dates=None,clock=None):
    for value in (price_source_id,price_import_id,calendar_source_id,calendar_import_id,listing_id):required(value,'explicit capture identifier')
    if price_source_id==calendar_source_id:raise ContractError('Distinct explicit price and calendar sources required')
    now=(clock or (lambda:datetime.now(timezone.utc)))();at=utc(now)
    store.db.execute('SAVEPOINT captured_observation_read')
    try:
        sources={}
        for source in (price_source_id,calendar_source_id):
            for use in (Use.STORAGE,Use.RESEARCH):store.require_use(source,use,as_of=now)
            row=store.db.execute('SELECT origin FROM sources WHERE source_id=?',(source,)).fetchone()
            if row is None:raise ContractError('Unknown explicit source')
            sources[source]=row[0]
        job=store.db.execute('SELECT * FROM price_sync_jobs WHERE source_id=? AND import_id=?',(price_source_id,price_import_id)).fetchone()
        terminal=store.db.execute('SELECT * FROM price_sync_results WHERE source_id=? AND import_id=?',(price_source_id,price_import_id)).fetchone()
        if job is None or terminal is None:raise ContractError('Explicit terminal price job required; no direct-capture fallback')
        for row,keys in [(job,('source_id','import_id','input_json','created_at')),(terminal,('source_id','import_id','available_at','body_json'))]:
            if hashlib.sha256(canonical({key:row[key] for key in keys}).encode()).hexdigest()!=row['integrity_sha']:raise EvidenceIntegrityError('Price job manifest integrity failed')
        if job['created_at']>at or terminal['available_at']>at:raise ContractError('Price job is not yet available')
        request=json.loads(job['input_json']);result=json.loads(terminal['body_json'])
        if result['request']!=request or result['state']!='complete_pages' or result['pages_complete'] is not True:raise ContractError('Price job is incomplete or quarantined')
        query=request['query'];route=request['route'];bindings=request['symbol_listings']
        if len(bindings)!=1 or list(bindings.values())!=[listing_id] or query.get('symbols')!=next(iter(bindings)):raise ContractError('Exact single-listing price job required')
        if any(query.get(key)!=value for key,value in {'timeframe':'1Day','adjustment':'raw','asof':'-','currency':'USD','sort':'asc'}.items()) or query.get('feed') not in {'iex','sip'}:raise ContractError('Unsupported price request semantics')
        listing=store.db.execute('SELECT * FROM listings WHERE listing_id=?',(listing_id,)).fetchone()
        if listing is None or listing['trading_currency']!='USD':raise ContractError('Explicit USD listing required')
        pages=_pages(store,price_source_id,price_import_id,now)
        if pages!=result['pages'] or not pages:raise EvidenceIntegrityError('Price report/page journal mismatch')
        calendar=store.calendar_as_of(calendar_source_id,calendar_import_id,as_of=now)
        if calendar is None or calendar['quarantined'] or not calendar['response_rows_valid'] or calendar['calendar_kind']!='TRADING':raise ContractError('Calendar capture missing or quarantined')
        provenance=calendar['provenance']
        if not provenance or provenance['route']!=route or provenance['method']!='GET' or provenance['endpoint']!='https://paper-api.alpaca.markets/v2/calendar':raise ContractError('Calendar and price routes/provenance differ')
        if route.get('broker_id')!='alpaca' or route.get('environment')!='paper':raise ContractError('Explicit paper route required')
        zone=ZoneInfo('America/New_York')
        start=timestamp(query['start']).astimezone(zone).date().isoformat();end=timestamp(query['end']).astimezone(zone).date().isoformat()
        if not calendar['start_date']<=start<=end<=calendar['end_date']:raise ContractError('Calendar declared range does not cover price query')
        cal={row['date']:row for row in calendar['candidates'] if start<=row['date']<=end}
        if len(cal)!=len([r for r in calendar['candidates'] if start<=r['date']<=end]):raise ContractError('Duplicate calendar dates')
        prices={};lineage=[];token=None;source_dates=[]
        for index,page in enumerate(pages):
            p=page['provenance'];expected=dict(query)
            if token is not None:expected['page_token']=token
            if p['route']!=route or p['endpoint']!=PRICE_URL or p['method']!='GET' or p['query']!=expected:raise ContractError('Price page provenance differs from declared job')
            captured=store.capture_as_of(price_source_id,page['capture_id'],as_of=now)
            if captured['quarantined'] or captured['pagination_state']=='unknown':raise ContractError('Price capture is quarantined or pagination unknown')
            for row in captured['candidates']:
                if row['listing_id']!=listing_id or row['currency']!='USD' or row['date'] in prices or not start<=row['date']<=end:raise ContractError('Price row identity/date mismatch')
                prices[row['date']]=(row,captured['available_at'],page['capture_id'],captured['received_at'])
                source_dates.append(row['date'])
            token=captured['next_page_token']
            if token!=page['next_page_token'] or (index<len(pages)-1 and token is None):raise EvidenceIntegrityError('Price pagination chain inconsistent')
            lineage.append({'capture_id':page['capture_id'],'raw_sha':page['raw_sha'],'available_at':captured['available_at'],'received_at':captured['received_at'],'processed_at':captured['available_at'],'provenance':p})
        if token is not None:raise ContractError('Price job has no terminal page')
        if source_dates!=sorted(set(source_dates)):raise ContractError('Price source rows violate ascending chronological order')
        if expected_dates is not None and not isinstance(expected_dates,(list,tuple)):raise ContractError('Explicit dates must be a list or tuple')
        dates=sorted(cal) if expected_dates is None else list(expected_dates)
        if not dates or dates!=sorted(set(dates)):raise ContractError('Nonempty unique increasing inspection dates required')
        for day in dates:
            if not isinstance(day,str) or date.fromisoformat(day).isoformat()!=day:raise ContractError('Canonical dates required')
        if set(dates)!=set(prices) or set(dates)!=set(cal):raise ContractError('Exact price/calendar/date join has gaps')
        observations=[]
        for index,day in enumerate(dates):
            price,available,capture_id,received=prices[day];session=cal[day]
            if timestamp(received)<timestamp(session['end']):raise ContractError('Price daily aggregate was received before declared calendar close')
            observations.append(dict(index=index,economic_date=day,listing_id=listing_id,currency=price['currency'],price_kind='raw',values=price['values'],
                provider_timestamp=price['provider_timestamp'],calendar_start=session['start'],calendar_end=session['end'],
                calendar_venue=calendar['venue'],listing_mic=listing['mic'],published_at=None,
                available_at=max(available,calendar['available_at']),price_received_at=received,price_processed_at=available,
                calendar_received_at=calendar['received_at'],calendar_processed_at=calendar['available_at'],price_capture_id=capture_id))
        groups={}
        for row in observations:groups.setdefault(row['available_at'],[]).append(row['index'])
        report=dict(version=1,inspection_only=True,dataset_admitted=False,training_ready=False,full_history_verified=False,live_trading=False,
                    checked_at=at,source_origins=sources,price_source_id=price_source_id,price_import_id=price_import_id,
                    calendar_source_id=calendar_source_id,calendar_import_id=calendar_import_id,
                    listing=dict(listing),calendar_venue_matches_listing=calendar['venue']==listing['mic'],
                    calendar_applies_to_listing_verified=False,policy='observed_dates_only',query=query,
                    observations=observations,observation_groups=[dict(available_at=k,indices=v) for k,v in sorted(groups.items())],
                    price_lineage=lineage,calendar_lineage=dict(raw_sha=calendar['raw_sha'],available_at=calendar['available_at'],received_at=calendar['received_at'],processed_at=calendar['available_at'],provenance=provenance),
                    historical_availability_verified=False,publication_verified=False,authenticated_account_verified=False)
        report['inspection_sha256']=hashlib.sha256(canonical(report).encode()).hexdigest()
    except BaseException:
        store.db.execute('ROLLBACK TO captured_observation_read');store.db.execute('RELEASE captured_observation_read');raise
    else:
        store.db.execute('RELEASE captured_observation_read');return report


def verify_inspection(report):
    """Frozen-report integrity/shape check, not current DB rights or source certification."""
    try:
        body={k:v for k,v in report.items() if k!='inspection_sha256'}
        if hashlib.sha256(canonical(body).encode()).hexdigest()!=report['inspection_sha256']:raise ValueError()
        if report['inspection_only'] is not True or any(report[k] is not False for k in ('dataset_admitted','training_ready','full_history_verified','live_trading','historical_availability_verified','publication_verified','calendar_applies_to_listing_verified','authenticated_account_verified')):raise ValueError()
        rows=report['observations']
        if not rows or [r['index'] for r in rows]!=list(range(len(rows))):raise ValueError()
        dates=[r['economic_date'] for r in rows]
        if dates!=sorted(set(dates)):raise ValueError()
        groups={}
        for row in rows:
            if date.fromisoformat(row['economic_date']).isoformat()!=row['economic_date'] or row['published_at'] is not None:raise ValueError()
            if row['listing_id']!=report['listing']['listing_id'] or row['currency']!=report['listing']['trading_currency']:raise ValueError()
            if timestamp(row['calendar_start'])>=timestamp(row['calendar_end']) or timestamp(row['price_received_at'])<timestamp(row['calendar_end']) or timestamp(row['available_at'])>timestamp(report['checked_at']):raise ValueError()
            for key in ('open','high','low','close','volume'):decimal_text(row['values'][key],positive=key!='volume')
            values={k:Decimal(row['values'][k]) for k in ('open','high','low','close')}
            if not values['low']<=min(values['open'],values['close'])<=max(values['open'],values['close'])<=values['high']:raise ValueError()
            if row['available_at']!=max(row['price_processed_at'],row['calendar_processed_at']):raise ValueError()
            if timestamp(row['price_received_at'])>timestamp(row['price_processed_at']) or timestamp(row['calendar_received_at'])>timestamp(row['calendar_processed_at']):raise ValueError()
            groups.setdefault(row['available_at'],[]).append(row['index'])
        if report['observation_groups']!=[dict(available_at=k,indices=v) for k,v in sorted(groups.items())]:raise ValueError()
    except (ValueError,KeyError,TypeError,AttributeError) as exc:
        raise EvidenceIntegrityError('Invalid captured inspection report') from exc
    return report
