import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from bridge import BridgeError
from codex_adapter import TASK_ID
from demo import demo
from openai_architect import MAX_CALLS, OpenAIArchitect, request_api
from test_demo import Process


def response(value):
    return json.dumps({'status': 'completed', 'output': [{'type': 'message', 'content': [
        {'type': 'output_text', 'text': json.dumps(value)}]}]}).encode()


def proposal(summary='Analyse du témoin'):
    return {'type': 'proposal', 'summary': summary, 'task': TASK_ID}


def review(decision='accept'):
    return {'type': 'review', 'summary': 'Conclusion du modèle', 'decision': decision}


class ArchitectTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.key = patch.dict(os.environ, {'OPENAI_API_KEY': 'synthetic-key-do-not-store'})
        self.key.start()
        self.addCleanup(self.key.stop)

    async def test_strict_payload_and_model_configuration(self):
        seen = []
        def transport(key, payload):
            seen.append((key, payload))
            return response(proposal())
        architect = OpenAIArchitect(model='gpt-6.1-terra', transport=transport)
        value = await architect.plan(TASK_ID, [])
        self.assertEqual(value['task'], TASK_ID)
        key, payload = seen[0]
        self.assertEqual(key, 'synthetic-key-do-not-store')
        self.assertNotIn(key, json.dumps(payload))
        self.assertEqual(payload['model'], 'gpt-6.1-terra')
        self.assertEqual(payload['text']['format']['name'], 'dobby_plan')
        self.assertIn('DOBBY architect', payload['instructions'])
        self.assertFalse(payload['store'])
        self.assertTrue(payload['text']['format']['strict'])
        self.assertEqual(payload['max_output_tokens'], 256)
        with self.assertRaises(ValueError):
            OpenAIArchitect(model='unbounded-model', transport=transport)

    async def test_invalid_response_and_secret_are_never_returned(self):
        values = [b'not json', response({'type': 'proposal', 'summary': 'x', 'task': '/tmp'}),
                  response(proposal('synthetic-key-do-not-store')),
                  response({'type': 'proposal', 'summary': 'x', 'task': TASK_ID, 'command': 'x'}),
                  json.dumps({'status': 'incomplete', 'output': []}).encode()]
        for raw in values:
            architect = OpenAIArchitect(transport=lambda key, payload: raw)
            with self.assertRaises(BridgeError) as caught:
                await architect.plan(TASK_ID, [])
            self.assertNotIn('synthetic-key-do-not-store', str(caught.exception))

    async def test_missing_key_and_software_budget_fail_closed(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': ''}):
            with self.assertRaisesRegex(BridgeError, 'architect_api_key_missing'):
                await OpenAIArchitect(transport=lambda *_: response(proposal())).plan(TASK_ID, [])
        architect = OpenAIArchitect(transport=lambda *_: response(proposal()))
        for _ in range(MAX_CALLS):
            await architect.plan(TASK_ID, [])
        with self.assertRaisesRegex(BridgeError, 'architect_budget_exhausted'):
            await architect.plan(TASK_ID, [])

    async def test_transport_errors_and_request_size_are_sanitized(self):
        with patch('openai_architect.urllib.request.build_opener') as build:
            build.return_value.open.side_effect = urllib.error.URLError('synthetic-key-do-not-store')
            with self.assertRaises(BridgeError) as caught:
                request_api('synthetic-key-do-not-store', {'input': 'x'})
            self.assertEqual(str(caught.exception), 'architect_request_failed')
        with self.assertRaisesRegex(BridgeError, 'architect_input_limit'):
            request_api('synthetic-key-do-not-store', {'input': 'x' * 13000})
    async def test_full_dialogue_revision_requires_new_approval(self):
        answers = iter([proposal('Premier plan'), review('revise'), proposal('Plan corrigé'), review()])
        architect = OpenAIArchitect(transport=lambda *_: response(next(answers)))
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / 'nexus-test'
            workspace.mkdir()
            (workspace / '.git').mkdir()
            (workspace / 'README.md').write_bytes(b'fixture')
            approvals = []
            def approve(prompt):
                approvals.append(prompt)
                return 'oui'
            with patch('demo.platform.system', return_value='Windows'), \
                 patch('demo.codex_binary', return_value=Path('fake.exe')), \
                 patch('demo.asyncio.create_subprocess_exec', new=AsyncMock(side_effect=lambda *a, **k: Process())) as spawn:
                result = await demo(workspace, b'fixture', approve, architect)
            self.assertEqual(result, 0)
            self.assertEqual(len(approvals), 2)
            self.assertEqual(spawn.await_count, 2)
            self.assertEqual(architect.calls, 4)
            self.assertNotIn('synthetic-key-do-not-store', (Path(directory) / 'demo.sqlite3').read_bytes().decode('latin1'))

    async def test_second_approval_refused_prevents_second_codex_call(self):
        answers = iter([proposal(), review('revise'), proposal('Nouvelle proposition')])
        architect = OpenAIArchitect(transport=lambda *_: response(next(answers)))
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / 'nexus-test'
            workspace.mkdir()
            (workspace / '.git').mkdir()
            (workspace / 'README.md').write_bytes(b'fixture')
            approvals = iter(['oui', 'non'])
            with patch('demo.platform.system', return_value='Windows'), \
                 patch('demo.codex_binary', return_value=Path('fake.exe')), \
                 patch('demo.asyncio.create_subprocess_exec', new=AsyncMock(return_value=Process())) as spawn:
                self.assertEqual(await demo(workspace, b'fixture', lambda _: next(approvals), architect), 1)
            self.assertEqual(spawn.await_count, 1)
