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


class SmokeFailure(ContractError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


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


def prepare(directory, *, inspection_report=None):
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
    if inspection_report is None:
        bundle = _fixture(root/'input'/'bundle')
        expected=[dict(economic_date=b['date'],available_at=b['available_at'],close=b['close'],currency=b['currency']) for b in bundle['bars']]
        origin='synthetic_fixture';groups_count=len(expected)
    else:
        from .captured_observations import verify_inspection
        verify_inspection(inspection_report)
        folder=root/'input'/'bundle';folder.mkdir()
        (folder/'inspection.json').write_bytes(encoded(inspection_report))
        groups=[dict(available_at=g['available_at'],observations=[inspection_report['observations'][i] for i in g['indices']]) for g in inspection_report['observation_groups']]
        (folder/'groups.jsonl').write_bytes(b''.join(encoded(g).replace(b'\n',b'')+b'\n' for g in groups))
        expected=[row for group in groups for row in group['observations']]
        origin='captured_inspection';groups_count=len(groups)
        config=make_config();config['parameters']['inspection_bundle']='true'
        (root/'input'/'config.json').write_bytes(encoded(config))
    manifest = dict(schema='lean-observer-input-1',image=IMAGE,platform=PLATFORM,container_name=container_name,
        launcher=LAUNCHER,api_reference_commit=REFERENCE_COMMIT,origin=origin,
        inspection_only=inspection_report is not None,dataset_admitted=False,expected_group_count=groups_count,
        inspection_report_sha256=inspection_report['inspection_sha256'] if inspection_report is not None else None,
        observation_fields=sorted(expected[0]),expected_observations=expected,
        files=_input_hashes(root/'input'),engine_execution_verified=False,live_trading=False)
    (root/'input-manifest.json').write_bytes(encoded(manifest))
    (root/'docker-command.json').write_bytes(encoded(command))
    (root/'docker-command.sh').write_text('#!/bin/sh\nset -eu\nexec '+shlex.join(command)+'\n')
    return dict(status='prepared',directory=str(root),image=IMAGE,platform=PLATFORM,
        input_manifest_sha256=digest(encoded(manifest)),expected_count=len(expected),
        docker_command=command,engine_execution_verified=False,live_trading=False)


def verify_inputs(directory):
    root=Path(directory).resolve()
    manifest=json.loads((root/'input-manifest.json').read_bytes())
    if manifest.get('schema')!='lean-observer-input-1' or manifest.get('image')!=IMAGE or manifest.get('platform')!=PLATFORM:
        raise ContractError('Unexpected smoke input manifest')
    if _input_hashes(root/'input')!=manifest['files']:
        raise ContractError('Smoke inputs changed after preparation')
    if manifest.get('origin')=='captured_inspection':
        from .captured_observations import verify_inspection
        report=json.loads((root/'input'/'bundle'/'inspection.json').read_bytes())
        verify_inspection(report)
        groups=[dict(available_at=g['available_at'],observations=[report['observations'][i] for i in g['indices']]) for g in report['observation_groups']]
        data=b''.join(encoded(g).replace(b'\n',b'')+b'\n' for g in groups)
        if (root/'input'/'bundle'/'groups.jsonl').read_bytes()!=data:
            raise ContractError('Captured group data differs from inspection report')
        expected=[row for group in groups for row in group['observations']]
        if manifest.get('inspection_only') is not True or manifest.get('dataset_admitted') is not False:
            raise ContractError('Capture propagation cannot promote dataset admission')
    elif manifest.get('origin')=='synthetic_fixture':
        bundle=verify_bundle(root/'input'/'bundle')
        expected=[dict(economic_date=b['date'],available_at=b['available_at'],close=b['close'],currency=b['currency']) for b in bundle['bars']]
    else:
        raise ContractError('Unknown smoke observation mode')
    if manifest['expected_observations']!=expected:
        raise ContractError('Smoke observations differ from input bundle')
    return manifest


def validate_result(directory,returncode):
    root=Path(directory).resolve();manifest=verify_inputs(root)
    log=(root/'output'/'engine.log').read_text(errors='replace')
    error_line=next((line.strip()[:1000] for line in log.splitlines()
        if re.search(r'ERROR::|Runtime Error|Unhandled exception|Traceback \(most recent call last\)',line,re.I)),None)
    if error_line:
        raise SmokeFailure('engine_log_error','LEAN engine failure: '+error_line)
    if returncode!=0:
        raise SmokeFailure('container_exit_nonzero',f'LEAN container exit {returncode}; inspect output/engine.log')
    result_paths=list((root/'output').glob('*-summary.json'))
    if len(result_paths)!=1:
        raise ContractError('Exactly one final LEAN summary is required')
    final=json.loads(result_paths[0].read_bytes())
    if not isinstance(final,dict):
        raise SmokeFailure('invalid_final_summary','LEAN final result must be a JSON object')
    state=final.get('state',{})
    if not isinstance(state,dict):
        raise ContractError('LEAN final state must be an object')
    if (state.get('Status')!='Completed' or state.get('RuntimeError')!=''
            or state.get('StackTrace')!='' or str(state.get('OrderCount'))!='0'
            or not state.get('EndTime')):
        raise SmokeFailure('engine_final_state_failed','LEAN final state failed: '+str(state.get('Status'))+'; '+str(state.get('RuntimeError',''))[:1000])
    observer_path=root/'output'/'observer-evidence.json'
    if not observer_path.is_file():
        raise SmokeFailure('observer_evidence_missing','LEAN completed without observer-evidence.json')
    summary=json.loads(observer_path.read_bytes())
    if not isinstance(summary,dict):
        raise SmokeFailure('invalid_observer_evidence','Observer evidence must be a JSON object')
    observed=summary.get('observed',[])
    if not isinstance(observed,list) or any(not isinstance(row,dict) for row in observed):
        raise ContractError('Observer rows must be a list of objects')
    actual=[];previous=None;previous_available=None
    for row in observed:
        actual.append({key:row[key] for key in manifest.get('observation_fields',('economic_date','available_at','close','currency'))})
        engine=datetime.fromisoformat(row['observed_engine_utc'].replace('Z','+00:00'))
        if engine.tzinfo is None:engine=engine.replace(tzinfo=timezone.utc)
        available=datetime.fromisoformat(row['available_at'].replace('Z','+00:00'))
        if engine<available:
            raise ContractError('Engine observation time is early')
        if previous is not None:
            valid=(engine==previous if manifest.get('inspection_only') and available==previous_available else engine>previous)
            if not valid:raise ContractError('Engine group observation time is not consistent/increasing')
        previous=engine;previous_available=available
    if summary.get('schema')!='lean-observer-smoke-1' or summary.get('origin')!=manifest.get('origin'):
        raise ContractError('Unexpected observer evidence schema')
    if (summary.get('status')!='completed' or summary.get('verdict') is not True
            or summary.get('lean_observer_ran') is not True or summary.get('exact_observations_match') is not True
            or actual!=manifest['expected_observations']
            or summary.get('expected_count')!=len(manifest['expected_observations'])
            or summary.get('observed_count')!=len(manifest['expected_observations'])
            or summary.get('orders_count')!=0 or summary.get('order_events')!=0):
        raise ContractError('Observer count/time/value/order checks failed')
    if manifest.get('inspection_only') and summary.get('observed_group_count')!=manifest['expected_group_count']:
        raise ContractError('Captured observation group count differs')
    return dict(status='passed',scope='captured_data_inspection_only' if manifest.get('inspection_only') else 'synthetic_custom_data_observation_only',
        image=IMAGE,platform=PLATFORM,input_manifest_sha256=digest(encoded(manifest)),
        observed_count=summary['observed_count'],observed_group_count=summary.get('observed_group_count'),orders_sent=0,engine_observation_verified=True,
        inspection_only=manifest.get('inspection_only',False),dataset_admitted=False,training_ready=False,publication_verified=False,
        inspection_report_sha256=manifest.get('inspection_report_sha256'),
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
    returncode=None
    try:
        with (root/'output'/'engine.log').open('w') as log:
            process=(runner or subprocess.run)(command,stdout=log,stderr=subprocess.STDOUT,timeout=timeout,check=False)
        returncode=process.returncode
        result=validate_result(root,returncode)
    except (ContractError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        cleanup_status='not_needed_no_timeout'
        if isinstance(error,subprocess.TimeoutExpired):
            # A timed-out Docker client can leave its daemon-owned job running.
            # Keep cleanup diagnostics separate from the actual engine log.
            cleanup_status='failed'
            try:
                cleanup=(runner or subprocess.run)(['docker','rm','--force',command[3]],
                    stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30,check=False)
                message=getattr(cleanup,'stdout',b'') or b''
                if isinstance(message,bytes):message=message.decode(errors='replace')
                if cleanup.returncode==0:cleanup_status='removed'
                elif 'no such container' in message.lower():cleanup_status='already_removed'
            except (OSError,subprocess.SubprocessError):
                pass
        result=dict(status='failed',engine_observation_verified=False,reason=str(error),
                    error_code=getattr(error,'code','container_timeout' if isinstance(error,subprocess.TimeoutExpired) else 'artifact_or_process_error'),
                    container_returncode=returncode,live_trading=False,container_cleanup_status=cleanup_status,
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
