"""Single-dispatch event scenario analysis; no retries, training or order routing."""
import hashlib
import os
from pathlib import Path

from .contracts import ContractError, RecordConflict
from .event_analysis import PROMPT_VERSION
from .openai_event_reader import EventAnalysisReadError


def analysis_code_version():
    """Hash the package source actually executing, without touching credentials."""
    root = Path(__file__).parent
    digest = hashlib.sha256()
    for source in sorted(root.glob('*.py')):
        digest.update(source.name.encode() + b'\0' + source.read_bytes() + b'\0')
    return 'package-sha256:' + digest.hexdigest()


def openai_credential(env_file=None):
    """Read only the named credential; no shell evaluation or environment export."""
    if env_file is None:
        key = os.environ.get('OPENAI_API_KEY')
    else:
        try:
            lines = Path(env_file).read_text(encoding='utf-8').splitlines()
        except (OSError, UnicodeError):
            raise ContractError('Cannot read the selected local credential file') from None
        values = [line.split('=', 1)[1].strip() for line in lines
                  if line.startswith('OPENAI_API_KEY=')]
        if len(values) != 1:
            raise ContractError('Credential file must contain exactly one OPENAI_API_KEY assignment')
        key = values[0]
        if len(key) >= 2 and key[0] == key[-1] and key[0] in {'"', "'"}:
            key = key[1:-1]
    if not isinstance(key, str) or not key or not all(32 < ord(x) < 127 for x in key):
        raise ContractError('A valid OPENAI_API_KEY is required')
    return key


def analyze_event(store, *, request_id, analysis_id, source_id, event_id, as_of,
                  radius_km, model, code_version, expires_at, reader,
                  max_output_tokens=4096, external_processing_reviewed=False):
    """Freeze, claim, infer and validate one source-backed investigation card.

    The operator must review external processing rights before sending a packet.
    A pending/failed request requires investigation and a NEW explicit request ID;
    an ambiguous timeout is never an instruction to repeat a paid API operation.
    """
    if external_processing_reviewed is not True:
        raise ContractError('External processing rights must be reviewed before API dispatch')
    if type(max_output_tokens) is not int or not 512 <= max_output_tokens <= 16384:
        raise ContractError('max_output_tokens must be an integer from 512 to 16384')
    existing = store.analysis_as_of(analysis_id, as_of=store._event_clock())
    if existing is not None and existing['request_id'] != request_id:
        raise RecordConflict('Analysis ID already belongs to a different request')
    request = store.prepare_analysis(request_id, source_id, event_id, as_of=as_of,
        radius_km=radius_km, model=model, prompt_version=PROMPT_VERSION,
        code_version=code_version, expires_at=expires_at,
        api_parameters={'max_output_tokens': max_output_tokens})
    state = store.attempt_state(request_id)
    if state is not None:
        if state['state'] == 'completed' and state['analysis_id'] == analysis_id:
            return store.analysis_as_of(analysis_id, as_of=store._event_clock())
        raise RecordConflict('Request already dispatched; inspect its archived state before a new request')
    store.start_analysis(request_id)
    try:
        response = reader.read(request)
    except EventAnalysisReadError as exc:
        store.record_failure(request_id, exc.reason_code)
        raise
    # Programming errors/crashes intentionally leave the durable pending claim.
    # Re-running the command cannot silently dispatch the same request twice.
    try:
        return store.record_analysis(analysis_id, request_id, response['output'],
            response_id=response['response_id'], returned_model=response['returned_model'],
            raw_response=response['raw_response'])
    except ContractError:
        store.record_failure(request_id, 'validation')
        raise
