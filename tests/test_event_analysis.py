"""Synthetic scenario cards preserve cutoffs, references and immutable inference lineage."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import concurrent.futures
import threading
import unittest

from trading_intelligence.contracts import (
    AssetKind, ContractError, DataOrigin, Entity, EvidenceIntegrityError, Instrument,
    Listing, RecordConflict, Use, UseNotAllowed,
)
from trading_intelligence.event_analysis import EventAnalysisStore, PROMPT_VERSION, canonical, validate_output
from trading_intelligence.event_sources import EventCapture, endpoint

T = datetime(2026, 1, 1, tzinfo=timezone.utc)


def raw_response(output, response_id='response-one', model='synthetic-model'):
    return json.dumps(dict(id=response_id, model=model, status='completed', error=None,
        output=[dict(type='message', role='assistant', status='completed',
                     content=[dict(type='output_text', text=json.dumps(output))])])).encode()


class EventAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'events.sqlite3'
        self.now = T
        self.store = EventAnalysisStore(self.path, clock=lambda: self.now)
        self.addCleanup(lambda: self.store.close())
        for source in ('events', 'facility'):
            self.store.register_source(source, DataOrigin.SYNTHETIC)
            self.store.set_permissions(source, known_at=T, uses={Use.STORAGE, Use.RESEARCH})
        self.store.register_entity(Entity('issuer', 'Synthetic company'))
        self.store.register_instrument(Instrument('equity', 'issuer', AssetKind.EQUITY))
        self.store.register_listing(Listing('listing', 'equity', 'XNAS', 'USD'))
        evidence_id = self.store.ingest(source_id='facility', record_id='document', revision_id='1',
            payload=b'Synthetic facility evidence', published_at=T, received_at=T)
        self.store.put_facility(assertion_id='relation-1', facility_id='factory', entity_id='issuer',
            latitude=0, longitude=0.1, evidence_id=evidence_id, valid_from=T, known_at=T,
            relationship='operator', listing_id='listing')
        self.now += timedelta(days=1)
        self.event(longitude=0, import_id='one')

    def event(self, longitude, import_id):
        millis = lambda at: int(at.timestamp() * 1000)
        occurred = T + timedelta(hours=12)
        payload = json.dumps(dict(type='FeatureCollection',
            metadata=dict(generated=millis(self.now), count=1, status=200),
            features=[dict(type='Feature', id='event',
                properties=dict(time=millis(occurred), updated=millis(self.now),
                                type='earthquake', mag=6.5, tsunami=1),
                geometry=dict(type='Point', coordinates=[longitude, 0, 10]))])).encode()
        return self.store.stage(source_id='events', import_id=import_id,
                                capture=EventCapture(payload, self.now, endpoint()))

    def prepare(self, **changes):
        args = dict(request_id='request', source_id='events', event_id='event', as_of=self.now,
                    radius_km=50, model='synthetic-model', prompt_version=PROMPT_VERSION,
                    code_version='test-code', expires_at=self.now + timedelta(hours=1))
        args.update(changes)
        return self.store.prepare_analysis(**args)

    def output(self):
        case = dict(scenario_id='adverse', entity_id='issuer', listing_id='listing',
            name='Conditional interruption', condition='If the site has damage',
            mechanism='An outage could interrupt output', economic_direction='adverse',
            horizon='days to weeks', supporting_fact_ids=['facility.relation-1.relationship'],
            assumptions=['Actual damage has not been established'],
            counterarguments=['Backup capacity may offset a temporary outage'],
            invalidation_conditions=['Verified uninterrupted operations'],
            next_checks=['Obtain an operating status report'])
        unchanged = {**deepcopy(case), 'scenario_id': 'none', 'name': 'No disruption',
                     'economic_direction': 'none', 'condition': 'If operations remain normal',
                     'mechanism': 'No facility-level interruption'}
        return dict(status='investigate', summary='Investigate operating status',
                    cited_fact_ids=['event.event_type', 'facility.relation-1.relationship'],
                    scenarios=[case, unchanged], unknowns=['Actual operating status'],
                    market_pricing=dict(status='not_assessed', missing_inputs=['Executable market prices']))

    def record(self, output=None, **changes):
        output = self.output() if output is None else output
        args = dict(analysis_id='analysis', request_id='request', output=output,
                    response_id='response-one', returned_model='synthetic-model',
                    raw_response=raw_response(output))
        args.update(changes)
        return self.store.record_analysis(**args)

    def test_freezes_before_inference_and_records_only_at_completion(self):
        request = self.prepare()
        prepared_at = self.now
        self.assertTrue(request['pretrained_knowledge_contamination_possible'])
        self.assertFalse(request['historical_predictive_evaluation_valid'])
        self.store.start_analysis('request')
        self.now += timedelta(minutes=1)
        result = self.record()
        self.assertIsNone(self.store.analysis_as_of('analysis', as_of=prepared_at))
        self.assertEqual(self.store.analysis_as_of('analysis', as_of=self.now), result)
        self.assertFalse(result['model_prose_verified'])
        self.assertFalse(result['market_pricing_assessed'])
        self.assertEqual(result['orders_sent'], 0)
        self.assertEqual(self.store.attempt_state('request')['state'], 'completed')

    def test_restart_preserves_original_card_after_correction(self):
        request = self.prepare()
        self.store.start_analysis('request')
        result = self.record()
        self.now += timedelta(minutes=2)
        self.event(longitude=40, import_id='corrected')
        self.store.close()
        self.store = EventAnalysisStore(self.path, clock=lambda: self.now)
        self.assertEqual(self.store.get_request('request'), request)
        self.assertEqual(self.store.analysis_as_of('analysis', as_of=self.now), result)
        self.assertEqual(self.store.context('events', 'event', as_of=self.now, radius_km=50)['candidates'], [])

    def test_request_id_cannot_mutate_and_retry_preserves_original_time(self):
        request = self.prepare()
        original = self.now
        self.now += timedelta(minutes=2)
        self.assertEqual(self.prepare(as_of=original, expires_at=original+timedelta(hours=1)), request)
        with self.assertRaises(RecordConflict):
            self.prepare(as_of=original, expires_at=original+timedelta(hours=1), model='other')

    def test_future_cutoffs_and_expired_input_rejected(self):
        for changes in (dict(as_of=self.now+timedelta(seconds=1)), dict(expires_at=self.now),
                        dict(prompt_version='unregistered-prompt')):
            with self.subTest(changes=changes), self.assertRaises(ContractError):
                self.prepare(**changes)

    def test_unknown_citations_and_identity_mismatches_rejected(self):
        request = self.prepare()
        for mutate in (lambda o: o['cited_fact_ids'].append('fabricated'),
                       lambda o: o['scenarios'][0].update(entity_id='other'),
                       lambda o: o['scenarios'][0].update(listing_id='other'),
                       lambda o: o['scenarios'][0].update(supporting_fact_ids=['event.event_type']),
                       lambda o: o.update(win_probability=0.99),
                       lambda o: o['scenarios'][0].update(order='short'),
                       lambda o: o['market_pricing'].update(status='priced_in')):
            output = self.output()
            mutate(output)
            with self.subTest(output=output), self.assertRaises(ContractError):
                validate_output(output, request)

    def test_no_disruption_counterargument_and_next_checks_are_required(self):
        request = self.prepare()
        for mutate in (lambda o: o['scenarios'].pop(),
                       lambda o: o['scenarios'][1].update(economic_direction='adverse'),
                       lambda o: o['scenarios'][0].update(counterarguments=[]),
                       lambda o: o['scenarios'][0].update(next_checks=[]),
                       lambda o: o.update(unknowns=[])):
            output = self.output()
            mutate(output)
            with self.subTest(output=output), self.assertRaises(ContractError):
                validate_output(output, request)

    def test_missing_exposure_requires_abstain(self):
        request = self.prepare(radius_km=1)
        with self.assertRaises(ContractError):
            validate_output(self.output(), request)
        output = self.output()
        output.update(status='abstain', scenarios=[], cited_fact_ids=['event.event_type'])
        self.assertEqual(validate_output(output, request), output)

    def test_conflicting_event_requires_abstain(self):
        row = self.store.db.execute("SELECT r.payload FROM event_captures c JOIN raw_objects r ON r.sha256=c.raw_sha WHERE c.import_id='one'").fetchone()
        payload = json.loads(row['payload'])
        payload['features'][0]['properties']['mag'] = 7
        self.now += timedelta(minutes=1)
        self.store.stage(source_id='events', import_id='conflict',
                         capture=EventCapture(json.dumps(payload).encode(), self.now, endpoint()))
        request = self.prepare()
        with self.assertRaises(ContractError):
            validate_output(self.output(), request)
        self.assertTrue(request['input']['context']['event_ambiguity'])

    def test_mutable_caller_inputs_cannot_rewrite_saved_request(self):
        request = self.prepare()
        request['input']['context']['candidates'][0]['entity_id'] = 'changed'
        self.assertEqual(self.store.get_request('request')['input']['context']['candidates'][0]['entity_id'], 'issuer')

    def test_record_requires_dispatch_and_raw_response_binding(self):
        self.prepare()
        with self.assertRaises(RecordConflict):
            self.record()
        self.store.start_analysis('request')
        for changes in (dict(response_id='other'), dict(returned_model='other'),
                        dict(raw_response=raw_response({**self.output(), 'summary': 'Other output'}))):
            with self.subTest(changes=changes), self.assertRaises(EvidenceIntegrityError):
                self.record(**changes)

    def test_duplicate_dispatch_and_timeout_are_durable(self):
        self.prepare()
        self.store.start_analysis('request')
        with self.assertRaises(RecordConflict):
            self.store.start_analysis('request')
        self.store.record_failure('request', 'network')
        self.assertEqual(self.store.attempt_state('request')['state'], 'failed')
        with self.assertRaises(RecordConflict):
            self.store.start_analysis('request')
        with self.assertRaises(RecordConflict):
            self.record()
        with self.assertRaises(ContractError):
            self.store.record_failure('request', 'Provider echoed a secret')

    def test_record_is_idempotent_and_each_request_gets_one_card(self):
        self.prepare()
        self.store.start_analysis('request')
        result = self.record()
        self.assertEqual(self.record(), result)
        with self.assertRaises(RecordConflict):
            self.record(analysis_id='another')
        output = self.output()
        output['summary'] = 'Changed'
        with self.assertRaises(RecordConflict):
            self.record(output)

    def test_late_response_is_preserved_but_marked_expired(self):
        self.prepare()
        self.store.start_analysis('request')
        self.now += timedelta(hours=2)
        self.assertTrue(self.record()['expired_on_arrival'])

    def test_current_rights_revocation_blocks_historical_read(self):
        self.prepare()
        self.store.start_analysis('request')
        self.record()
        cutoff = self.now
        self.now += timedelta(minutes=1)
        self.store.set_permissions('facility', known_at=self.now, uses={Use.STORAGE})
        with self.assertRaises(UseNotAllowed):
            self.store.analysis_as_of('analysis', as_of=cutoff)

    def test_tampered_raw_or_manifest_is_detected(self):
        self.prepare()
        self.store.start_analysis('request')
        result = self.record()
        with self.store.db:
            self.store.db.execute('UPDATE raw_objects SET payload=? WHERE sha256=?',
                                  (b'changed', result['response_sha256']))
        with self.assertRaises(EvidenceIntegrityError):
            self.store.analysis_as_of('analysis', as_of=self.now)

    def test_attempt_journal_mutation_is_detected(self):
        self.prepare()
        self.store.start_analysis('request')
        with self.store.db:
            self.store.db.execute("UPDATE event_analysis_attempts SET body_json='{}'")
        with self.assertRaises(EvidenceIntegrityError):
            self.store.attempt_state('request')

    def test_dotted_assertion_id_cannot_reference_another_issuer(self):
        request = self.prepare()
        other = {**request['input']['context']['candidates'][0],
                 'assertion_id': 'relation-1.other', 'entity_id': 'other', 'listing_id': 'other-listing'}
        request['input']['context']['candidates'].append(other)
        request['input']['evidence_facts'].append(dict(fact_id='facility.relation-1.other.relationship',
            value='operator', assertion_id='relation-1.other'))
        output = self.output()
        output['scenarios'][0]['supporting_fact_ids'] = ['facility.relation-1.other.relationship']
        with self.assertRaises(ContractError):
            validate_output(output, request)

    def test_attempt_state_rejects_future_terminal_after_clock_rollback(self):
        self.prepare()
        self.store.start_analysis('request')
        self.now += timedelta(minutes=1)
        self.store.record_failure('request', 'network')
        self.now -= timedelta(seconds=30)
        with self.assertRaises(EvidenceIntegrityError):
            self.store.attempt_state('request')

    def test_failure_audit_survives_inflight_rights_revocation(self):
        self.prepare()
        self.store.start_analysis('request')
        self.now += timedelta(minutes=1)
        self.store.set_permissions('facility', known_at=self.now, uses={Use.STORAGE})
        failure = self.store.record_failure('request', 'validation')
        self.assertEqual(failure['state'], 'failed')
        self.assertEqual(failure['reason_code'], 'validation')
        with self.assertRaises(UseNotAllowed):
            self.store.get_request('request')

    def test_concurrent_dispatch_claims_only_once(self):
        self.prepare()
        barrier = threading.Barrier(2)
        now = self.now
        def claim():
            with EventAnalysisStore(self.path, clock=lambda: now) as store:
                barrier.wait(timeout=10)
                try:
                    store.start_analysis('request')
                    return 'claimed'
                except RecordConflict:
                    return 'blocked'
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: claim(), range(2)))
        self.assertEqual(sorted(results), ['blocked', 'claimed'])

    def test_completion_rechecks_source_rights_at_completion_clock(self):
        request = self.prepare()
        self.store.start_analysis('request')
        future = self.now + timedelta(minutes=1)
        self.store.set_permissions('facility', known_at=future, uses={Use.STORAGE})
        original = self.store._request_row
        def advance(row, current):
            result = original(row, current)
            self.now = future
            return result
        self.store._request_row = advance
        with self.assertRaises(UseNotAllowed):
            self.record()
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM event_analyses').fetchone()[0], 0)



if __name__ == '__main__':
    unittest.main()
