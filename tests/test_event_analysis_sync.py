"""Synthetic integration coverage for single-dispatch event analysis."""
from contextlib import redirect_stdout
from datetime import timedelta
from io import BytesIO, StringIO
import json
import os
from pathlib import Path
import tempfile
import traceback
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from trading_intelligence.contracts import ContractError, RecordConflict, Use, UseNotAllowed
from trading_intelligence.event_analysis import EventAnalysisStore, PROMPT_VERSION
from trading_intelligence.event_analysis_sync import (
    analysis_code_version, analyze_event, openai_credential)
from trading_intelligence.openai_event_reader import EventAnalysisReadError, OpenAIEventReader
from tests import test_event_analysis as core_tests

raw_response = core_tests.raw_response


class SyntheticReader:
    def __init__(self, output=None, error=None):
        self.output = output
        self.error = error
        self.calls = []

    def read(self, request):
        self.calls.append(request)
        if self.error:
            raise self.error
        return dict(output=self.output, response_id='response-one',
                    returned_model='synthetic-model', raw_response=raw_response(self.output))


class EventAnalysisSyncTests(unittest.TestCase):
    # Reuse the supplied synthetic source/facility setup without inheriting its
    # test methods (and accidentally running the full core suite twice).
    setUp = core_tests.EventAnalysisTests.setUp
    event = core_tests.EventAnalysisTests.event
    output = core_tests.EventAnalysisTests.output

    def arguments(self, **changes):
        args = dict(request_id='request', analysis_id='analysis', source_id='events',
                    event_id='event', as_of=self.now, radius_km=50, model='synthetic-model',
                    code_version='test-code', expires_at=self.now + timedelta(hours=1),
                    reader=SyntheticReader(self.output()), external_processing_reviewed=True)
        args.update(changes)
        return args

    def count_requests(self):
        return self.store.db.execute('SELECT COUNT(*) FROM event_analysis_requests').fetchone()[0]

    def test_completed_request_is_idempotent_and_never_calls_twice(self):
        args = self.arguments()
        first = analyze_event(self.store, **args)
        self.now += timedelta(minutes=1)
        second = analyze_event(self.store, **args)
        self.assertEqual(first, second)
        self.assertEqual(len(args['reader'].calls), 1)
        self.assertEqual(self.count_requests(), 1)
        request = args['reader'].calls[0]
        self.assertEqual(request['api_parameters'], {'max_output_tokens': 4096})
        self.assertEqual(request['prompt_version'], PROMPT_VERSION)
        self.assertEqual(first['orders_sent'], 0)

    def test_reused_analysis_id_is_rejected_before_a_second_paid_call(self):
        first = self.arguments()
        analyze_event(self.store, **first)
        second = self.arguments(request_id='other-request')
        with self.assertRaises(RecordConflict):
            analyze_event(self.store, **second)
        self.assertEqual(second['reader'].calls, [])
        self.assertEqual(self.count_requests(), 1)

    def test_cli_freezes_dispatches_and_prints_validated_card(self):
        from trading_intelligence.cli import main
        reader = SyntheticReader(self.output())
        args = ['trading-intelligence', 'event-analyze', '--database', str(self.path),
                '--request-id', 'cli-request', '--analysis-id', 'cli-analysis',
                '--source-id', 'events', '--event-id', 'event',
                '--as-of', self.now.isoformat(),
                '--expires-at', (self.now + timedelta(hours=1)).isoformat(),
                '--radius-km', '50', '--model', 'synthetic-model',
                '--external-processing-reviewed']
        output = StringIO()
        with patch('sys.argv', args), patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-cli-secret'}), \
                patch('trading_intelligence.openai_event_reader.OpenAIEventReader', return_value=reader) as factory, \
                patch('trading_intelligence.event_analysis.EventAnalysisStore',
                      side_effect=lambda database: EventAnalysisStore(database, clock=lambda: self.now)), \
                redirect_stdout(output):
            main()
        result = json.loads(output.getvalue())
        factory.assert_called_once_with('synthetic-cli-secret')
        self.assertEqual(result['analysis_id'], 'cli-analysis')
        self.assertEqual(result['output']['status'], 'investigate')
        self.assertEqual(result['orders_sent'], 0)
        self.assertNotIn('synthetic-cli-secret', output.getvalue())
        self.assertEqual(len(reader.calls), 1)
        persisted = self.store.analysis_as_of('cli-analysis', as_of=self.now)
        self.assertEqual(persisted, result)
        self.assertEqual(self.store.attempt_state('cli-request')['state'], 'completed')

    def test_pending_programming_failure_cannot_silently_redispatch(self):
        reader = SyntheticReader(error=RuntimeError('simulated process crash'))
        args = self.arguments(reader=reader)
        with self.assertRaises(RuntimeError):
            analyze_event(self.store, **args)
        self.assertEqual(self.store.attempt_state('request')['state'], 'pending')
        with self.assertRaises(RecordConflict):
            analyze_event(self.store, **args)
        self.assertEqual(len(reader.calls), 1)

    def test_known_api_failure_is_terminal_and_cannot_redispatch(self):
        reader = SyntheticReader(error=EventAnalysisReadError('network', 'Safe transport failure'))
        args = self.arguments(reader=reader)
        with self.assertRaises(EventAnalysisReadError):
            analyze_event(self.store, **args)
        state = self.store.attempt_state('request')
        self.assertEqual((state['state'], state['reason_code']), ('failed', 'network'))
        with self.assertRaises(RecordConflict):
            analyze_event(self.store, **args)
        self.assertEqual(len(reader.calls), 1)

    def test_external_processing_review_is_required_before_any_request(self):
        for reviewed in (False, None, 1, 'yes'):
            args = self.arguments(external_processing_reviewed=reviewed)
            with self.subTest(reviewed=reviewed), self.assertRaises(ContractError):
                analyze_event(self.store, **args)
            self.assertEqual(self.count_requests(), 0)
            self.assertEqual(args['reader'].calls, [])

    def test_current_revoked_rights_prevent_dispatch_of_frozen_request(self):
        args = self.arguments()
        self.store.prepare_analysis(args['request_id'], args['source_id'], args['event_id'],
            as_of=args['as_of'], radius_km=args['radius_km'], model=args['model'],
            prompt_version=PROMPT_VERSION, code_version=args['code_version'],
            expires_at=args['expires_at'], api_parameters={'max_output_tokens': 4096})
        self.now += timedelta(minutes=1)
        self.store.set_permissions('facility', known_at=self.now, uses={Use.STORAGE})
        with self.assertRaises(UseNotAllowed):
            analyze_event(self.store, **args)
        self.assertEqual(args['reader'].calls, [])
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM event_analysis_attempts').fetchone()[0], 0)

    def test_invalid_model_output_is_terminal_validation_failure(self):
        output = self.output()
        output['cited_fact_ids'].append('invented-citation')
        args = self.arguments(reader=SyntheticReader(output))
        with self.assertRaises(ContractError):
            analyze_event(self.store, **args)
        state = self.store.attempt_state('request')
        self.assertEqual((state['state'], state['reason_code']), ('failed', 'validation'))
        self.assertIsNone(self.store.analysis_as_of('analysis', as_of=self.now))
        with self.assertRaises(RecordConflict):
            analyze_event(self.store, **args)
        self.assertEqual(len(args['reader'].calls), 1)

    def test_invalid_budget_blocks_prepare_and_dispatch(self):
        for budget in (True, 511, 16385, '4096', None):
            args = self.arguments(max_output_tokens=budget)
            with self.subTest(budget=budget), self.assertRaises(ContractError):
                analyze_event(self.store, **args)
            self.assertEqual(self.count_requests(), 0)
            self.assertEqual(args['reader'].calls, [])

    def test_api_unavailable_does_not_expose_credential_or_provider_body(self):
        private_text = 'synthetic-secret-never-log'

        class Unavailable:
            calls = 0

            def open(self, request, *, timeout):
                self.calls += 1
                raise HTTPError('https://private.invalid', 401, private_text, {}, BytesIO(private_text.encode()))

        opener = Unavailable()
        args = self.arguments(reader=OpenAIEventReader(private_text, opener=opener))
        with self.assertRaises(EventAnalysisReadError) as raised:
            analyze_event(self.store, **args)
        state = self.store.attempt_state('request')
        self.assertEqual(state['reason_code'], 'authentication')
        self.assertNotIn(private_text, repr(state))
        self.assertNotIn(private_text, ''.join(traceback.format_exception(raised.exception)))
        self.assertEqual(opener.calls, 1)


class CredentialAndCodeVersionTests(unittest.TestCase):
    def test_only_explicit_env_file_is_read_and_never_evaluated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'credential.env'
            sentinel = Path(directory) / 'must-not-exist'
            literal = '$(touch ' + str(sentinel) + ')'
            # A shell expression with spaces is rejected as a key; it must never
            # execute and neither its content nor another secret is displayed.
            path.write_text('OTHER_SECRET=do-not-log\nOPENAI_API_KEY=' + literal + '\n')
            with patch.dict(os.environ, {'OPENAI_API_KEY': 'environment-secret'}):
                with self.assertRaises(ContractError) as raised:
                    openai_credential(path)
                self.assertNotIn('do-not-log', str(raised.exception))
                self.assertNotIn(literal, str(raised.exception))
                path.write_text('OTHER_SECRET=do-not-log\nOPENAI_API_KEY="synthetic-file-key"\n')
                self.assertEqual(openai_credential(path), 'synthetic-file-key')
                self.assertEqual(openai_credential(), 'environment-secret')
                self.assertEqual(os.environ['OPENAI_API_KEY'], 'environment-secret')
            self.assertFalse(sentinel.exists())

    def test_env_parser_rejects_ambiguous_missing_or_invalid_credentials_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'credential.env'
            for data in ('', 'OTHER_SECRET=private\n',
                         'OPENAI_API_KEY=secret-one\nOPENAI_API_KEY=secret-two\n',
                         'OPENAI_API_KEY=\n', 'OPENAI_API_KEY="key with spaces"\n'):
                path.write_text(data)
                with self.subTest(case=data[:20]), self.assertRaises(ContractError) as raised:
                    openai_credential(path)
                self.assertNotIn('secret-one', str(raised.exception))
                self.assertNotIn('secret-two', str(raised.exception))
                self.assertNotIn('private', str(raised.exception))
            path.write_bytes(b'\xff')
            with self.assertRaises(ContractError):
                openai_credential(path)
            path.unlink()
            with self.assertRaises(ContractError):
                openai_credential(path)
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ContractError):
            openai_credential()

    def test_code_version_stable_without_credential_or_data_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'a.py').write_text('value = 1\n')
            (root / 'b.py').write_text('value = 2\n')
            with patch('trading_intelligence.event_analysis_sync.__file__', str(root / 'a.py')):
                first = analysis_code_version()
                self.assertEqual(first, analysis_code_version())
                self.assertRegex(first, r'^package-sha256:[a-f0-9]{64}$')
                (root / '.env.local').write_text('OPENAI_API_KEY=synthetic-secret\n')
                (root / 'data.json').write_text('{"synthetic":true}')
                self.assertEqual(first, analysis_code_version())
                (root / 'a.py').write_text('value = 3\n')
                self.assertNotEqual(first, analysis_code_version())


if __name__ == '__main__':
    unittest.main()
