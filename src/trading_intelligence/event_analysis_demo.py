"""Invented event scenarios through the real reader/validator with no network.

The Responses envelopes and all scenario text are supplied synthetic fixtures.
This demonstrates provenance and correction handling, not model intelligence.
"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from .contracts import DataOrigin
from .event_analysis import EventAnalysisStore, PROMPT_VERSION
from .event_demo import _payload, event_demo
from .event_sources import EventCapture, USGS_FEEDS
from .openai_event_reader import OpenAIEventReader, RESPONSES_URL


MODEL = 'synthetic-model-snapshot-1'


def synthetic_output(request):
    """Build an explicitly invented response from a frozen demo packet."""
    context = request['input']['context']
    facts = request['input']['evidence_facts']
    citations = [item['fact_id'] for item in facts if item['fact_id'] == 'event.event_type']
    result = dict(status='abstain', summary='Synthetic fixture: exposure is not established.',
                  cited_fact_ids=citations, scenarios=[],
                  unknowns=['Actual operating status is unknown.',
                            'Facility coverage is incomplete.',
                            'No executable prices or trading costs were supplied.'],
                  market_pricing=dict(status='not_assessed', missing_inputs=[
                      'Executable market prices after analysis completion.',
                      'Costs, liquidity and existing portfolio exposure.']))
    if context['event'] is None or context['event_ambiguity'] or not context['candidates']:
        return result
    candidate = context['candidates'][0]
    facility_ref = 'facility.' + candidate['assertion_id'] + '.relationship'
    citations.append(facility_ref)
    result.update(status='investigate',
                  summary='Synthetic fixture: investigate conditional disruption and continuity cases.')
    common = dict(entity_id=candidate['entity_id'], listing_id=candidate['listing_id'],
                  supporting_fact_ids=citations, horizon='Next several operating days',
                  assumptions=['The supplied facility relationship remains economically relevant.'],
                  counterarguments=['Proximity alone does not establish damage or financial materiality.'],
                  next_checks=['Obtain a dated operating-status statement and production-share evidence.'])
    result['scenarios'] = [dict(**common, scenario_id='synthetic-disruption',
        name='Conditional production disruption',
        condition='If a subsequent independent operating-status report confirms an outage.',
        mechanism='An actual outage could reduce production; its extent remains unknown.',
        economic_direction='adverse',
        invalidation_conditions=['A dated statement confirms uninterrupted production.']),
        dict(**common, scenario_id='synthetic-continuity', name='No material disruption',
        condition='If operations continue or backup capacity offsets the disruption.',
        mechanism='Continued production could leave operating cash flows unchanged.',
        economic_direction='none',
        invalidation_conditions=['A dated statement confirms a material uncompensated outage.'])]
    return result


class _SyntheticResponse:
    status = 200
    headers = {'Content-Type': 'application/json'}

    def __init__(self, payload):
        self.payload = payload

    def geturl(self):
        return RESPONSES_URL

    def read(self, size):
        return self.payload[:size]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class SyntheticResponsesOpener:
    """Local wire-format fixture; never opens a URL or reads credentials."""
    def __init__(self, response_id):
        self.response_id = response_id
        self.calls = 0

    def open(self, request, *, timeout):
        self.calls += 1
        wire = json.loads(request.data)
        packet = dict(input=json.loads(wire['input']))
        output = synthetic_output(packet)
        envelope = dict(id=self.response_id, model=wire['model'], status='completed', error=None,
            output=[dict(type='message', role='assistant', status='completed',
                content=[dict(type='output_text', text=json.dumps(output, sort_keys=True))])],
            usage=dict(input_tokens=0, output_tokens=0, total_tokens=0))
        return _SyntheticResponse(json.dumps(envelope, sort_keys=True).encode())


def _analyse(store, *, suffix, at, clock):
    request_id, analysis_id = 'demo-request-' + suffix, 'demo-analysis-' + suffix
    request = store.prepare_analysis(request_id, 'synthetic-events', 'invented-earthquake',
        as_of=at, radius_km=50, model=MODEL, prompt_version=PROMPT_VERSION,
        code_version='synthetic-analysis-demo-1', expires_at=at + timedelta(hours=1),
        api_parameters={'max_output_tokens': 4096})
    # The replay reads any existing terminal attempt at its recorded completion
    # time. Reading it with a clock rewound to preparation is an integrity error.
    clock[0] = at + timedelta(seconds=1)
    state = store.attempt_state(request_id)
    if state is None:
        store.start_analysis(request_id)
        result = OpenAIEventReader('synthetic-demo-credential',
            opener=SyntheticResponsesOpener('resp_synthetic_' + suffix)).read(request)
        clock[0] = at + timedelta(seconds=1)
        analysis = store.record_analysis(analysis_id, request_id, result['output'],
            response_id=result['response_id'], returned_model=result['returned_model'],
            raw_response=result['raw_response'])
    elif state['state'] == 'completed':
        clock[0] = at + timedelta(seconds=1)
        analysis = store.analysis_as_of(analysis_id, as_of=clock[0])
    else:
        raise RuntimeError('Synthetic demo request has an incomplete prior attempt')
    return request, analysis


def event_analysis_demo(directory):
    """Replay invented event changes, scenario cards and immutable old knowledge."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    event_demo(directory / 'event-intake')
    database = directory / 'event-intake' / 'events.sqlite3'
    start = datetime(2026, 1, 10, 12, tzinfo=timezone.utc)
    near, far = start + timedelta(minutes=3), start + timedelta(minutes=5)
    clock = [near]
    with EventAnalysisStore(database, clock=lambda: clock[0]) as store:
        store.stage(source_id='synthetic-events', import_id='analysis-demo-near',
            capture=EventCapture(_payload(near, longitude=139.05, latitude=35.0,
                magnitude=6.4, status='reviewed', tsunami=0), near, USGS_FEEDS['all_hour']),
            processed_at=near)
        request, first = _analyse(store, suffix='near', at=near, clock=clock)
        unavailable_before_completion = store.analysis_as_of('demo-analysis-near', as_of=near) is None
        clock[0] = far
        store.stage(source_id='synthetic-events', import_id='analysis-demo-far',
            capture=EventCapture(_payload(far, longitude=10.0, latitude=10.0,
                magnitude=6.0, status='reviewed', tsunami=0), far, USGS_FEEDS['all_hour']),
            processed_at=far)
        corrected_request, second = _analyse(store, suffix='far', at=far, clock=clock)
        reread = store.analysis_as_of('demo-analysis-near', as_of=clock[0])
        result = dict(origin=DataOrigin.SYNTHETIC.value, response_origin='injected_synthetic_fixture',
            initial_analysis=first, corrected_analysis=second,
            initial_request_sha256=request['request_sha256'],
            corrected_request_sha256=corrected_request['request_sha256'],
            initial_event_version_id=request['input']['context']['event']['event_version_id'],
            corrected_event_version_id=corrected_request['input']['context']['event']['event_version_id'],
            old_analysis_preserved=first == reread,
            unavailable_before_completion=unavailable_before_completion,
            network_requests=0, real_model_called=False, predictive_accuracy_assessed=False,
            model_prose_verified=False, market_pricing_assessed=False,
            training_ready=False, orders_sent=0, live_trading=False)
    (directory / 'report.json').write_text(json.dumps(result, sort_keys=True, indent=2) + '\n',
                                          encoding='utf-8')
    return result
