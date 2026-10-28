"""Bounded OpenAI Responses reader for frozen event-analysis requests.

The reader has one fixed HTTPS destination, no tools, retries or broker access.
Transport errors deliberately omit provider bodies, URLs and credential details.
"""

from http.client import HTTPException
import json
import math
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from .contracts import ContractError


RESPONSES_URL = 'https://api.openai.com/v1/responses'
MAX_REQUEST_BYTES = 2_000_000
MAX_RESPONSE_BYTES = 2_000_000
DEFAULT_MAX_OUTPUT_TOKENS = 4096
MAX_OUTPUT_TOKENS = 32768


class EventAnalysisReadError(ContractError):
    def __init__(self, reason_code, message):
        super().__init__(message)
        self.reason_code = reason_code


def _invalid():
    return EventAnalysisReadError('invalid_response', 'OpenAI returned an invalid structured response')


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


def _constant(_value):
    raise ValueError('nonfinite constant')


def _float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('nonfinite number')
    return number


def _decode(payload):
    try:
        value = json.loads(payload, object_pairs_hook=_pairs,
                           parse_constant=_constant, parse_float=_float)
        # Reject unpaired escaped Unicode surrogates before downstream journals
        # encode the structured result as original UTF-8 bytes.
        json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise _invalid() from None


def _identifier(value):
    return (isinstance(value, str) and 0 < len(value) <= 256
            and value.strip() == value and all(32 < ord(x) < 127 for x in value))


def parse_response(payload):
    """Validate the completed Responses envelope and decode exactly one JSON object.

    Schema/citation validation belongs to EventAnalysisStore. The raw bytes are
    returned unchanged so that the caller can retain an immutable response.
    """
    if not isinstance(payload, bytes) or not 0 < len(payload) <= MAX_RESPONSE_BYTES:
        raise _invalid()
    envelope = _decode(payload)
    if not isinstance(envelope, dict):
        raise _invalid()
    status = envelope.get('status')
    if status == 'incomplete':
        raise EventAnalysisReadError('incomplete', 'OpenAI response was incomplete; no analysis accepted')
    if status != 'completed' or envelope.get('error') is not None:
        raise EventAnalysisReadError('failed_response', 'OpenAI response did not complete successfully')
    response_id, model = envelope.get('id'), envelope.get('model')
    if not _identifier(response_id) or not _identifier(model):
        raise _invalid()
    items = envelope.get('output')
    if not isinstance(items, list):
        raise _invalid()
    texts = []
    for item in items:
        if not isinstance(item, dict):
            raise _invalid()
        # Reasoning metadata is not an additional answer, and is never used as
        # evidence or a rationale. Function/tool calls are not accepted.
        if item.get('type') == 'reasoning':
            continue
        if (item.get('type') != 'message' or item.get('role') != 'assistant'
                or item.get('status') != 'completed'):
            raise _invalid()
        content = item.get('content')
        if not isinstance(content, list) or not content:
            raise _invalid()
        for part in content:
            if not isinstance(part, dict):
                raise _invalid()
            if part.get('type') == 'refusal':
                raise EventAnalysisReadError('refused', 'OpenAI declined the analysis; no analysis accepted')
            if part.get('type') != 'output_text' or not isinstance(part.get('text'), str):
                raise _invalid()
            texts.append(part['text'])
    if len(texts) != 1:
        raise _invalid()
    output = _decode(texts[0])
    if not isinstance(output, dict):
        raise _invalid()
    usage = envelope.get('usage')
    if usage is not None:
        if not isinstance(usage, dict):
            raise _invalid()
        names = ('input_tokens', 'output_tokens', 'total_tokens')
        if any(type(usage.get(name)) is not int or usage[name] < 0 for name in names):
            raise _invalid()
        if usage['input_tokens'] + usage['output_tokens'] != usage['total_tokens']:
            raise _invalid()
        # Do not forward arbitrary provider metadata into the accepted result.
        usage = {name: usage[name] for name in names}
    return dict(output=output, raw_response=payload, response_id=response_id,
                returned_model=model, usage=usage)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


class OpenAIEventReader:
    """One structured-output POST; caller supplies only its OpenAI credential."""

    def __init__(self, api_key, *, timeout=60, opener=None):
        if (not isinstance(api_key, str) or not api_key
                or not all(32 < ord(x) < 127 for x in api_key)):
            raise EventAnalysisReadError('configuration', 'A valid OpenAI API credential is required')
        if type(timeout) not in (int, float) or not 0 < timeout <= 120:
            raise EventAnalysisReadError('configuration', 'A positive timeout of at most 120 seconds is required')
        self._api_key = api_key
        self._timeout = timeout
        self._opener = opener or build_opener(
            _NoRedirect(), HTTPSHandler(context=ssl.create_default_context()))

    def __repr__(self):
        return '<OpenAIEventReader fixed Responses endpoint; no tools or orders>'

    def read(self, prepared_request):
        if not isinstance(prepared_request, dict):
            raise EventAnalysisReadError('configuration', 'A frozen analysis request is required')
        model = prepared_request.get('model')
        instructions = prepared_request.get('system_prompt')
        schema = prepared_request.get('output_schema')
        analysis_input = prepared_request.get('input')
        parameters = prepared_request.get('api_parameters', {})
        if (not _identifier(model) or not isinstance(instructions, str) or not instructions.strip()
                or not isinstance(schema, dict) or not isinstance(analysis_input, dict)
                or not isinstance(parameters, dict) or set(parameters) - {'max_output_tokens'}):
            raise EventAnalysisReadError('configuration', 'Invalid frozen analysis request')
        max_tokens = parameters.get('max_output_tokens', DEFAULT_MAX_OUTPUT_TOKENS)
        if type(max_tokens) is not int or not 256 <= max_tokens <= MAX_OUTPUT_TOKENS:
            raise EventAnalysisReadError('configuration', 'A bounded integer output-token limit is required')
        try:
            data = json.dumps(dict(
                model=model, instructions=instructions,
                input=json.dumps(analysis_input, sort_keys=True, separators=(',', ':'),
                                 ensure_ascii=False, allow_nan=False),
                text={'format': {'type': 'json_schema', 'name': 'event_analysis',
                                 'strict': True, 'schema': schema}},
                store=False, max_output_tokens=max_tokens),
                sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')
        except (ValueError, TypeError, RecursionError, UnicodeError):
            raise EventAnalysisReadError('configuration', 'Analysis request is not valid JSON') from None
        if len(data) > MAX_REQUEST_BYTES:
            raise EventAnalysisReadError('configuration', 'Analysis request exceeds the size limit')
        request = Request(RESPONSES_URL, data=data, method='POST', headers={
            'Authorization': 'Bearer ' + self._api_key,
            'Content-Type': 'application/json', 'Accept': 'application/json',
            'Accept-Encoding': 'identity', 'User-Agent': 'TradingIntelligence-event-analysis/1'})
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                if response.status != 200 or response.geturl() != RESPONSES_URL:
                    raise EventAnalysisReadError('http', 'Unexpected OpenAI response status or endpoint')
                media = response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
                encoding = response.headers.get('Content-Encoding', 'identity').strip().lower()
                if media != 'application/json' or encoding != 'identity':
                    raise EventAnalysisReadError('http', 'Unexpected OpenAI response content type or encoding')
                payload = response.read(MAX_RESPONSE_BYTES + 1)
        except EventAnalysisReadError:
            raise
        except HTTPError as error:
            status = error.code
            reason = 'authentication' if status in (401, 403) else 'rate_limit' if status == 429 else 'http'
            raise EventAnalysisReadError(reason, 'OpenAI request failed; no analysis accepted') from None
        except (URLError, OSError, HTTPException, ValueError):
            raise EventAnalysisReadError('network', 'OpenAI transport failed; no analysis accepted') from None
        return parse_response(payload)
