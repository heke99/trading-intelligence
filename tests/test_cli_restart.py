"""Canonical command output stays reproducible across a process restart."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class CliRestartTests(unittest.TestCase):
    def test_previous_four_part_demo_output_is_byte_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            command = [sys.executable, '-m', 'trading_intelligence',
                       'research-foundations-demo', '--out', directory]
            first = subprocess.check_output(command, text=True)
            again = subprocess.check_output(command, text=True)
            self.assertEqual(first, again)
            result = json.loads(first)
            self.assertEqual(len(result['parts']), 4)
            self.assertFalse(result['authenticated_access_verified'])
            self.assertFalse(result['training_ready'])

    def test_missing_provider_configuration_fails_without_network(self):
        env = dict(os.environ)
        for key in ('SEC_USER_AGENT','ALPACA_PAPER_API_KEY','ALPACA_PAPER_SECRET_KEY'):
            env.pop(key, None)
        command = [sys.executable, '-m', 'trading_intelligence', 'sec-sync',
                   '--database', '/does-not-exist/research.sqlite', '--source-id', 'example',
                   '--import-id', 'example', '--cik', '0000000001']
        result = subprocess.run(command, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('Configure SEC_USER_AGENT', result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertNotIn('Traceback', result.stderr)
