import asyncio
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from bridge import BridgeError
from codex_adapter import TASK_ID
from demo import LocalCodex, demo, expected_content, main, verify_workspace


class Stream:
    def __init__(self, data):
        self.data = data

    async def read(self, size):
        result, self.data = self.data[:size], self.data[size:]
        return result


class Process:
    def __init__(self, data=b'{"status":"complete","findings":["documentation"]}', code=0):
        self.stdout = Stream(data)
        self.code = code
        self.returncode = None
        self.killed = False

    async def wait(self):
        self.returncode = self.code
        return self.code

    def kill(self):
        self.killed = True


class DemoTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name) / 'nexus-test'
        self.workspace.mkdir()
        (self.workspace / '.git').mkdir()
        self.expected = b'fixture'
        (self.workspace / 'README.md').write_bytes(self.expected)
        self.win = patch('demo.platform.system', return_value='Windows')
        self.win.start()
        self.addCleanup(self.win.stop)
        self.binary = patch('demo.codex_binary', return_value=Path('mock-codex.exe'))
        self.binary.start()
        self.addCleanup(self.binary.stop)

    async def test_refusal_never_launches_codex(self):
        with patch('demo.asyncio.create_subprocess_exec', new_callable=AsyncMock) as spawn:
            self.assertEqual(await demo(self.workspace, self.expected, lambda _: 'non'), 1)
            spawn.assert_not_awaited()

    async def test_fixture_digest_matches_bundled_file(self):
        self.assertTrue(expected_content())

    async def test_help_presents_dobby(self):
        output = io.StringIO()
        with patch('sys.argv', ['demo.py', '--help']), contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as result:
                main()
        self.assertEqual(result.exception.code, 0)
        self.assertIn('DOBBY V1', output.getvalue())

    async def test_approved_demo_runs_fixed_safe_command(self):
        with patch('demo.asyncio.create_subprocess_exec', new=AsyncMock(return_value=Process())) as spawn:
            self.assertEqual(await demo(self.workspace, self.expected, lambda _: 'oui'), 0)
        args, kwargs = spawn.call_args
        self.assertEqual(args[args.index('--sandbox') + 1], 'read-only')
        self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', args)
        self.assertNotIn('--skip-git-repo-check', args)
        self.assertEqual(args[args.index('--cd') + 1], str(self.workspace))
        for name in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'CODEX_ACCESS_TOKEN'):
            self.assertNotIn(name, kwargs['env'])

    async def test_bad_response_and_process_error_are_rejected(self):
        for proc, reason in ((Process(b'{"secret":"synthetic"}'), 'codex_output_refused'),
                             (Process(code=1), 'codex_process_failed')):
            with patch('demo.asyncio.create_subprocess_exec', new=AsyncMock(return_value=proc)):
                with self.assertRaisesRegex(BridgeError, reason):
                    await LocalCodex(self.workspace, self.expected).execute(TASK_ID, [])

    async def test_changed_workspace_refused_before_launch(self):
        (self.workspace / 'README.md').write_text('unexpected')
        with patch('demo.asyncio.create_subprocess_exec', new_callable=AsyncMock) as spawn:
            with self.assertRaisesRegex(BridgeError, 'workspace_changed'):
                await LocalCodex(self.workspace, self.expected).execute(TASK_ID, [])
            spawn.assert_not_awaited()

    async def test_unexpected_file_is_refused(self):
        (self.workspace / 'unexpected.txt').write_text('unexpected')
        with self.assertRaisesRegex(BridgeError, 'workspace_changed'):
            verify_workspace(self.workspace, self.expected)

    async def test_timeout_terminates_process(self):
        class SlowStream:
            async def read(self, size):
                await asyncio.sleep(3)
        proc = Process()
        proc.stdout = SlowStream()
        with patch('demo.TIMEOUT', .02), patch('demo.asyncio.create_subprocess_exec', new=AsyncMock(return_value=proc)):
            with self.assertRaisesRegex(BridgeError, 'codex_timeout'):
                await LocalCodex(self.workspace, self.expected).execute(TASK_ID, [])
        self.assertTrue(proc.killed)
