"""Prepare and optionally run one isolated, pinned, synthetic LEAN observer smoke."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
from uuid import uuid4

from .contracts import AssetKind, ContractError, DataOrigin, Entity, Instrument, Listing, Use
from .lean_export import export_bundle, verify_bundle
from .lean_smoke_templates import make_config, REFERENCE_COMMIT
from .market_data import MarketDataStore

IMAGE = 'quantconnect/lean@sha256:afc3a126d3ba294784a3f11dff38cdfed020672f021e02df7b24f7e2335ba0ca'
PLATFORM = 'linux/arm64'
LAUNCHER = '/Lean/Launcher/bin/Debug/QuantConnect.Lean.Launcher.dll'


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2)+'\n').encode()


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def _input_hashes(directory):
    result = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ContractError('Smoke inputs must not contain symbolic links')
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = digest(path.read_bytes())
    return result


def _fixture(directory):
    cutoff = datetime(2026,1,10,tzinfo=timezone.utc)
    calendar_at = datetime(2026,1,1,tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as temporary:
        with MarketDataStore(Path(temporary)/'synthetic.sqlite') as store:
            store.register_source('smoke-fixture', DataOrigin.SYNTHETIC)
            store.set_permissions('smoke-fixture', known_at=calendar_at, uses={Use.STORAGE,Use.RESEARCH})
            store.register_entity(Entity('smoke-issuer','Invented observer fixture'))
            store.register_instrument(Instrument('smoke-stock','smoke-issuer',AssetKind.EQUITY))
            store.register_listing(Listing('smoke-listing','smoke-stock','XNAS','USD'))
            days = ['2026-01-05','2026-01-06']
            for index,day in enumerate(days):
                for kind in ('session','bar'):
                    observed = calendar_at if kind=='session' else datetime.fromisoformat(day+'T21:00:01+00:00')
                    body = dict(kind=kind,listing_id='smoke-listing',date=day,start=day+'T14:30:00Z',
                        end=day+'T21:00:00Z',currency='USD',values=(dict(timezone='America/New_York') if kind=='session'
                        else dict(open=str(100+index),high=str(105+index),low=str(95+index),close=str(102+index),volume='50',price_kind='raw')))
                    store.import_record(source_id='smoke-fixture',record_id=kind+day,revision_id='1',
                        payload=json.dumps(body).encode(),published_at=observed,received_at=observed,processed_at=observed)
            return export_bundle(store,'smoke-fixture','smoke-listing',days,as_of=cutoff,directory=directory,clock=lambda:cutoff)


def docker_command(directory, container_name=None):
    root = Path(directory).resolve()
    if ',' in str(root) or '\n' in str(root):
        raise ContractError('Smoke path cannot contain Docker mount delimiters')
    if container_name is None:
        container_name=json.loads((root/'input-manifest.json').read_bytes())['container_name']
    if not isinstance(container_name,str) or not re.fullmatch(r'ti-lean-smoke-[0-9a-f]{32}',container_name):
        raise ContractError('Unexpected scoped container name')
    return ['docker','run','--name',container_name,'--rm','--pull','never','--network','none','--platform',PLATFORM,
        '--cap-drop','ALL','--security-opt','no-new-privileges',
        '--mount',f'type=bind,src={root / "input"},dst=/Smoke/input,readonly',
        '--mount',f'type=bind,src={root / "output"},dst=/Smoke/output',
        '--workdir','/Lean/Launcher/bin/Debug','--entrypoint','dotnet',IMAGE,LAUNCHER,
        '--config','/Smoke/input/config.json']


def prepare(directory):
    root = Path(directory).resolve()
    container_name="ti-lean-smoke-"+uuid4().hex
    command = docker_command(root,container_name)
    if root.exists():
        raise ContractError('Use a new dedicated smoke directory; existing runs are never overwritten')
    (root/'input').mkdir(parents=True)
    (root/'output').mkdir()
    source = Path(__file__).parent
    for path in source.rglob('*.py'):
        if path.is_symlink():
            raise ContractError('Source package must not contain symbolic links')
        target = root/'input'/'python'/'trading_intelligence'/path.relative_to(source)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(path.read_bytes())
    algorithm = source/'lean_smoke_templates'/'observer_algorithm.py'
    (root/'input'/'algorithm.py').write_bytes(algorithm.read_bytes())
    (root/'input'/'config.json').write_bytes(encoded(make_config()))
    bundle = _fixture(root/'input'/'bundle')
    manifest = dict(schema='lean-observer-input-1',image=IMAGE,platform=PLATFORM,container_name=container_name,
        launcher=LAUNCHER,api_reference_commit=REFERENCE_COMMIT,origin='synthetic_fixture',
        expected_observations=[dict(economic_date=b['date'],available_at=b['available_at'],close=b['close'],currency=b['currency']) for b in bundle['bars']],
        files=_input_hashes(root/'input'),engine_execution_verified=False,live_trading=False)
    (root/'input-manifest.json').write_bytes(encoded(manifest))
    (root/'docker-command.json').write_bytes(encoded(command))
    (root/'docker-command.sh').write_text('#!/bin/sh\nset -eu\nexec '+shlex.join(command)+'\n')
    return dict(status='prepared',directory=str(root),image=IMAGE,platform=PLATFORM,
        input_manifest_sha256=digest(encoded(manifest)),expected_count=len(bundle['bars']),
        docker_command=command,engine_execution_verified=False,live_trading=False)


def verify_inputs(directory):
    root=Path(directory).resolve()
    manifest=json.loads((root/'input-manifest.json').read_bytes())
    if manifest.get('schema')!='lean-observer-input-1' or manifest.get('image')!=IMAGE or manifest.get('platform')!=PLATFORM:
        raise ContractError('Unexpected smoke input manifest')
    if _input_hashes(root/'input')!=manifest['files']:
        raise ContractError('Smoke inputs changed after preparation')
    bundle=verify_bundle(root/'input'/'bundle')
    expected=[dict(economic_date=b['date'],available_at=b['available_at'],close=b['close'],currency=b['currency']) for b in bundle['bars']]
    if manifest['expected_observations']!=expected:
        raise ContractError('Smoke observations differ from input bundle')
    return manifest


def validate_result(directory,returncode):
    root=Path(directory).resolve();manifest=verify_inputs(root)
    log=(root/'output'/'engine.log').read_text(errors='replace')
    summary=json.loads((root/'output'/'observer-evidence.json').read_bytes())
    if returncode!=0:
        raise ContractError('LEAN container did not exit successfully; inspect output/engine.log')
    if re.search(r'ERROR::|Runtime Error|Unhandled exception|Traceback \(most recent call last\)',log,re.I):
        raise ContractError('LEAN log contains an error; inspect output/engine.log')
    result_paths=list((root/'output').glob('*-summary.json'))
    if len(result_paths)!=1:
        raise ContractError('Exactly one final LEAN summary is required')
    final=json.loads(result_paths[0].read_bytes())
    if not isinstance(summary,dict) or not isinstance(final,dict):
        raise ContractError('Observer and LEAN results must be JSON objects')
    state=final.get('state',{})
    if not isinstance(state,dict):
        raise ContractError('LEAN final state must be an object')
    if (state.get('Status')!='Completed' or state.get('RuntimeError')!=''
            or state.get('StackTrace')!='' or str(state.get('OrderCount'))!='0'
            or not state.get('EndTime')):
        raise ContractError('LEAN final state was not clean Completed with zero orders')
    observed=summary.get('observed',[])
    if not isinstance(observed,list) or any(not isinstance(row,dict) for row in observed):
        raise ContractError('Observer rows must be a list of objects')
    actual=[];previous=None
    for row in observed:
        actual.append({key:row[key] for key in ('economic_date','available_at','close','currency')})
        engine=datetime.fromisoformat(row['observed_engine_utc'].replace('Z','+00:00'))
        if engine.tzinfo is None:engine=engine.replace(tzinfo=timezone.utc)
        available=datetime.fromisoformat(row['available_at'].replace('Z','+00:00'))
        if engine<available or (previous is not None and engine<=previous):
            raise ContractError('Engine observation time is early or not increasing')
        previous=engine
    if summary.get('schema')!='lean-observer-smoke-1' or summary.get('origin')!='synthetic_fixture':
        raise ContractError('Unexpected observer evidence schema')
    if (summary.get('status')!='completed' or summary.get('verdict') is not True
            or summary.get('lean_observer_ran') is not True or summary.get('exact_observations_match') is not True
            or actual!=manifest['expected_observations']
            or summary.get('expected_count')!=len(manifest['expected_observations'])
            or summary.get('observed_count')!=len(manifest['expected_observations'])
            or summary.get('orders_count')!=0 or summary.get('order_events')!=0):
        raise ContractError('Observer count/time/value/order checks failed')
    return dict(status='passed',scope='synthetic_custom_data_observation_only',
        image=IMAGE,platform=PLATFORM,input_manifest_sha256=digest(encoded(manifest)),
        observed_count=summary['observed_count'],orders_sent=0,engine_observation_verified=True,
        real_dataset_admitted=False,strategy_profitability_verified=False,live_trading=False,
        evidence_files={str(p.relative_to(root)):digest(p.read_bytes()) for p in sorted((root/'output').rglob('*')) if p.is_file()})


def run_prepared(directory,*,timeout=180,runner=None):
    if type(timeout) is not int or not 30<=timeout<=900:
        raise ContractError('Timeout must be 30 to 900 seconds')
    root=Path(directory).resolve();verify_inputs(root)
    if any((root/'output').iterdir()):
        raise ContractError('Smoke output must be empty; stale evidence cannot be reused')
    command=docker_command(root)
    if runner is None and shutil.which('docker') is None:
        (root/'run-result.json').write_bytes(encoded(dict(status='blocked',reason='docker_unavailable',engine_observation_verified=False,live_trading=False)))
        raise ContractError('Docker is unavailable; prepared inputs are not engine evidence')
    try:
        with (root/'output'/'engine.log').open('w') as log:
            process=(runner or subprocess.run)(command,stdout=log,stderr=subprocess.STDOUT,timeout=timeout,check=False)
        result=validate_result(root,process.returncode)
    except (ContractError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        # Killing the Docker client alone does not stop the daemon-owned job.
        # This random name belongs only to this fresh dedicated smoke run.
        cleanup_ok=False
        try:
            with (root/'output'/'engine.log').open('a') as cleanup_log:
                cleanup=(runner or subprocess.run)(['docker','rm','--force',command[3]],
                    stdout=cleanup_log,stderr=subprocess.STDOUT,timeout=30,check=False)
            cleanup_ok=cleanup.returncode==0
        except (OSError,subprocess.SubprocessError):
            pass
        result=dict(status='failed',engine_observation_verified=False,reason=str(error),live_trading=False,container_cleanup_succeeded=cleanup_ok,
                    log_file=str(root/'output'/'engine.log'))
        (root/'run-result.json').write_bytes(encoded(result))
        raise ContractError('Smoke did not pass; inspect run-result.json and output/engine.log') from error
    (root/'run-result.json').write_bytes(encoded(result))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare-run'])
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--prepare-only',action='store_true',help='Prepare files without Docker; never engine verification')
    parser.add_argument('--timeout',type=int,default=180)
    args=parser.parse_args()
    try:
        result=prepare(args.out)
        if not args.prepare_only:result=run_prepared(args.out,timeout=args.timeout)
    except (ContractError,OSError,ValueError) as error:
        parser.exit(2,f'{error}\n')
    print(json.dumps(result,sort_keys=True,indent=2))


if __name__=='__main__':main()
