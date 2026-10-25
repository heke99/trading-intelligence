"""Deterministic synthetic-only daily bundles; not a LEAN runtime integration."""
import csv
import hashlib
import io
import json
from pathlib import Path
from datetime import date,datetime,timezone
from decimal import Decimal
from .contracts import ContractError,DataOrigin,EvidenceIntegrityError,Use,utc
from .market_data import timestamp,decimal_text
from .market_replay import replay_dates

FIELDS=['date','start','end','currency','open','high','low','close','volume','available_at']
NUMBERS=['open','high','low','close','volume']
def _bars(replay):
    return [dict(date=d['date'],start=d['bar']['start'],end=d['bar']['end'],currency=d['bar']['currency'],available_at=max(r['known_at'] for r in replay['manifest']['records'] if r['date']==d['date'] and r['kind'] in {'session','bar'}),**{k:d['bar']['values'][k] for k in NUMBERS}) for d in replay['days']]
def encoded(x):return (json.dumps(x,sort_keys=True,separators=(',',':'))+'\n').encode()
def sha(x):return hashlib.sha256(x).hexdigest()
def csv_bytes(bars):
    stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=FIELDS,lineterminator='\n');writer.writeheader();writer.writerows(bars);return stream.getvalue().encode()

def export_bundle(store,source_id,listing_id,expected_dates,*,as_of,directory,clock=None):
    now=(clock or (lambda:datetime.now(timezone.utc)))()
    if utc(as_of)>utc(now):raise ContractError('Export cutoff cannot be in the operational future')
    for use in (Use.STORAGE,Use.RESEARCH):store.require_use(source_id,use,as_of=now)
    origin=store.db.execute('SELECT origin FROM sources WHERE source_id=?',(source_id,)).fetchone()
    if origin is None or origin[0]!=DataOrigin.SYNTHETIC.value:
        raise ContractError('Only synthetic bundles supported until real admission/export binding is implemented')
    replay=replay_dates(store,source_id,listing_id,expected_dates,as_of=as_of)
    if not replay['complete_scope']:raise ContractError('A complete explicit replay scope is required')
    listing=dict(store.db.execute('SELECT * FROM listings WHERE listing_id=?',(listing_id,)).fetchone())
    bars=_bars(replay)
    raw={'bars.csv':csv_bytes(bars),'replay.json':encoded(replay)}
    manifest=dict(version=1,synthetic=True,listing=listing,replay=replay['manifest'],replay_sha256=replay['manifest_sha256'],files={k:sha(v) for k,v in raw.items()},training_ready=False,live_trading=False,lean_runtime_verified=False)
    path=Path(directory);path.mkdir(parents=True,exist_ok=True)
    raw['manifest.json']=encoded(manifest)
    for name,payload in raw.items():
        target=path/name
        if target.exists() and target.read_bytes()!=payload:raise ContractError('Export destination contains another immutable bundle')
    for name,payload in raw.items():(path/name).write_bytes(payload)
    return verify_bundle(path)

def verify_bundle(directory):
    path=Path(directory)
    try:
        manifest=json.loads((path/'manifest.json').read_bytes())
        if manifest['version']!=1 or manifest['synthetic'] is not True or manifest['training_ready'] is not False or manifest['live_trading'] is not False or manifest['lean_runtime_verified'] is not False:raise ValueError()
        if set(manifest['files'])!={'bars.csv','replay.json'}:raise ValueError()
        for name,digest in manifest['files'].items():
            if sha((path/name).read_bytes())!=digest:raise ValueError()
        replay=json.loads((path/'replay.json').read_bytes())
        if not replay['complete_scope'] or replay['gaps'] or replay['manifest']!=manifest['replay']:raise ValueError()
        # Replay hash uses canonical JSON without the export newline.
        actual=sha(encoded(replay['manifest'])[:-1])
        if actual!=manifest['replay_sha256'] or actual!=replay['manifest_sha256']:raise ValueError()
        if replay['manifest']['listing_id']!=manifest['listing']['listing_id']:raise ValueError()
        text=(path/'bars.csv').read_text();reader=csv.DictReader(io.StringIO(text))
        if reader.fieldnames!=FIELDS:raise ValueError()
        bars=list(reader)
        if [b['date'] for b in bars]!=replay['manifest']['expected_dates']:raise ValueError()
        expected=_bars(replay)
        if bars!=expected:raise ValueError()
        for b in bars:
            if date.fromisoformat(b['date']).isoformat()!=b['date'] or b['currency']!=manifest['listing']['trading_currency'] or timestamp(b['start'])>=timestamp(b['end']) or timestamp(b['available_at'])<timestamp(b['end']):raise ValueError()
            for key in NUMBERS:decimal_text(b[key],positive=key!='volume')
            if not Decimal(b['low'])<=min(Decimal(b['open']),Decimal(b['close']))<=max(Decimal(b['open']),Decimal(b['close']))<=Decimal(b['high']):raise ValueError()
    except (OSError,ValueError,KeyError,TypeError,csv.Error) as exc:
        raise EvidenceIntegrityError('Invalid or modified export bundle') from exc
    return dict(manifest=manifest,bars=bars,synthetic=True,lean_runtime_verified=False)
