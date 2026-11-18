import asyncio
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from bridge import BridgeError, Limits, Orchestrator, Store
from codex_adapter import CodexConfig, CodexReadOnly, TASK_ID, open_verified_binary, safe_result


class Stream:
    def __init__(self, data):
        self.data = data

    async def read(self, n):
        chunk, self.data = self.data[:n], self.data[n:]
        return chunk


class Process:
    def __init__(self, data=b'{"status":"complete","findings":["tests"]}', code=0):
        self.stdout = Stream(data)
        self.returncode = None
        self.code = code
        self.pid = 54321

    async def wait(self):
        self.returncode = self.code
        return self.code


class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.linux = patch('codex_adapter.platform.system', return_value='Linux')
        self.linux.start()
        self.addCleanup(self.linux.stop)
        self.sigkill = patch('codex_adapter.signal.SIGKILL', 9, create=True)
        self.sigkill.start()
        self.addCleanup(self.sigkill.stop)
        self.binary = patch('codex_adapter.open_verified_binary', side_effect=lambda *_: os.open(__file__, os.O_RDONLY))
        self.binary.start()
        self.addCleanup(self.binary.stop)

    async def test_defaults_and_task_restriction(self):
        with patch('codex_adapter.asyncio.create_subprocess_exec', new_callable=AsyncMock) as spawn:
            with self.assertRaisesRegex(BridgeError, 'codex_disabled'):
                await CodexReadOnly().execute(TASK_ID, [])
            for task in ('analyze:other', '/etc', 'analyze:nexus-test; whoami', ''):
                with self.assertRaisesRegex(BridgeError, 'codex_task_refused'):
                    await CodexReadOnly(CodexConfig(enabled=True)).execute(task, [])
            spawn.assert_not_called()

    async def test_fixed_arguments_minimal_environment_and_readonly_mounts(self):
        proc = Process()
        with patch('codex_adapter.asyncio.create_subprocess_exec', new=AsyncMock(return_value=proc)) as spawn:
            result = await CodexReadOnly(CodexConfig(enabled=True)).execute(TASK_ID, [{'secret': 'never forwarded'}])
        args, kwargs = spawn.call_args
        self.assertEqual(result, {'type': 'result', 'summary': 'Analysis categories: tests'})
        self.assertIn('--ro-bind', args)
        self.assertNotIn('--bind', args)
        self.assertEqual(args[args.index('--sandbox') + 1], 'read-only')
        self.assertEqual(args[args.index('--chdir') + 1], '/workspace')
        self.assertNotIn('never forwarded', repr(args))
        self.assertEqual(set(kwargs['env']), {'PATH', 'HOME', 'CODEX_HOME', 'LANG'})
        self.assertTrue(kwargs['start_new_session'])
        self.assertEqual(len(kwargs['pass_fds']), 1)
        self.assertIn('--unshare-net', args)
        self.assertEqual(kwargs['stderr'], asyncio.subprocess.DEVNULL)

    async def test_spawn_error_and_nonzero_exit_are_sanitized(self):
        adapter = CodexReadOnly(CodexConfig(enabled=True))
        with patch('codex_adapter.asyncio.create_subprocess_exec', new=AsyncMock(side_effect=OSError('secret-token'))):
            with self.assertRaisesRegex(BridgeError, '^codex_start_failed$'):
                await adapter.execute(TASK_ID, [])
        with patch('codex_adapter.asyncio.create_subprocess_exec', new=AsyncMock(return_value=Process(code=2))):
            with self.assertRaisesRegex(BridgeError, '^codex_process_failed$'):
                await adapter.execute(TASK_ID, [])

    async def test_output_limit_kills_process(self):
        proc = Process(b'x' * 40)
        with patch('codex_adapter.asyncio.create_subprocess_exec', new=AsyncMock(return_value=proc)), patch('codex_adapter.os.killpg', create=True) as kill:
            with self.assertRaisesRegex(BridgeError, 'codex_output_limit'):
                await CodexReadOnly(CodexConfig(enabled=True, output_bytes=12)).execute(TASK_ID, [])
            kill.assert_called_once()

    async def test_timeout_and_cancellation_kill_process(self):
        class SlowStream:
            async def read(self, n):
                await asyncio.sleep(10)
        proc = Process()
        proc.stdout = SlowStream()
        with patch('codex_adapter.asyncio.create_subprocess_exec', new=AsyncMock(return_value=proc)), patch('codex_adapter.os.killpg', create=True) as kill:
            with self.assertRaisesRegex(BridgeError, 'codex_timeout'):
                await CodexReadOnly(CodexConfig(enabled=True, timeout_seconds=.02)).execute(TASK_ID, [])
            kill.assert_called_once()
        proc = Process()
        proc.stdout = SlowStream()
        with patch('codex_adapter.asyncio.create_subprocess_exec', new=AsyncMock(return_value=proc)), patch('codex_adapter.os.killpg', create=True) as kill:
            job = asyncio.create_task(CodexReadOnly(CodexConfig(enabled=True)).execute(TASK_ID, []))
            await asyncio.sleep(.01)
            job.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await job
            kill.assert_called_once()

    async def test_platform_and_configuration_fail_closed(self):
        with patch('codex_adapter.platform.system', return_value='Windows'):
            with self.assertRaisesRegex(BridgeError, 'codex_platform_unsupported'):
                await CodexReadOnly(CodexConfig(enabled=True)).execute(TASK_ID, [])
        for kwargs in ({'timeout_seconds': 31}, {'output_bytes': 4097}, {'enabled': 1}, {'timeout_seconds': float('nan')}):
            with self.assertRaises(ValueError):
                CodexConfig(**kwargs)

    async def test_empty_and_invalid_output_refused(self):
        for data, error in ((b'', 'codex_output_refused'), (b'\xff', 'codex_output_refused')):
            with patch('codex_adapter.asyncio.create_subprocess_exec', new=AsyncMock(return_value=Process(data))):
                with self.assertRaisesRegex(BridgeError, error):
                    await CodexReadOnly(CodexConfig(enabled=True)).execute(TASK_ID, [])

    async def test_orchestrator_approval_then_fixed_codex(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'test.sqlite3')
            mid = store.create(TASK_ID, Limits())
            adapter = CodexReadOnly(CodexConfig(enabled=True))
            orchestrator = Orchestrator(store, executor=adapter)
            with patch('codex_adapter.asyncio.create_subprocess_exec', new=AsyncMock(return_value=Process())) as spawn:
                self.assertEqual((await orchestrator.run(mid))['state'], 'awaiting_approval')
                spawn.assert_not_called()
                store.approve(mid)
                self.assertEqual((await orchestrator.run(mid))['state'], 'completed')
                spawn.assert_awaited_once()

    async def test_synthetic_sensitive_output_is_refused_and_not_persisted(self):
        marker = 'SYNTHETIC_CREDENTIAL_MARKER'
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'test.sqlite3')
            mid = store.create(TASK_ID, Limits())
            orchestrator = Orchestrator(store, executor=CodexReadOnly(CodexConfig(enabled=True)))
            await orchestrator.run(mid)
            store.approve(mid)
            with patch('codex_adapter.asyncio.create_subprocess_exec', new=AsyncMock(return_value=Process(marker.encode()))):
                self.assertEqual((await orchestrator.run(mid))['error'], 'codex_output_refused')
            self.assertNotIn(marker, repr(store.messages(mid)))
            self.assertNotIn(marker, repr(store.get(mid)))

    async def test_output_schema_refuses_secrets_and_ambiguous_data(self):
        for payload in (b'{"status":"complete","findings":["sk-synthetic-secret"]}',
                        b'{"status":"complete","findings":[],"token":"synthetic"}',
                        b'{"status":"complete","status":"complete","findings":[]}',
                        b'{"status":"complete","findings":["tests","tests"]}',
                        b'{"status":"complete","findings":[{"token":"synthetic"}]}'):
            with self.assertRaisesRegex(BridgeError, 'codex_output_refused'):
                safe_result(payload)
        self.assertEqual(safe_result(b'{"status":"complete","findings":[]}')['summary'], 'Analysis categories: none')

    async def test_explicit_online_policy(self):
        with patch('codex_adapter.asyncio.create_subprocess_exec', new=AsyncMock(return_value=Process())) as spawn:
            await CodexReadOnly(CodexConfig(enabled=True, network='online')).execute(TASK_ID, [])
        self.assertNotIn('--unshare-net', spawn.call_args.args)


class BinaryValidationTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'posix', 'requires Linux file descriptor flags')
    def test_binary_paths_digest_permissions_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'codex'
            binary.write_bytes(b'synthetic executable')
            binary.chmod(0o700)
            digest = hashlib.sha256(binary.read_bytes()).hexdigest()
            fd = open_verified_binary(str(binary), digest)
            os.close(fd)
            for path, sha in [('relative', digest), (str(binary), 'x' * 64), (str(binary), '0' * 64)]:
                with self.assertRaises(BridgeError):
                    open_verified_binary(path, sha)
            link = Path(directory) / 'link'
            link.symlink_to(binary)
            with self.assertRaises(BridgeError):
                open_verified_binary(str(link), digest)
            binary.chmod(0o722)
            with self.assertRaises(BridgeError):
                open_verified_binary(str(binary), digest)


class SandboxIntegrationTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(os.name == 'posix' and os.environ.get('NEXUS_RUN_OFFLINE_BWRAP_TEST') == '1',
                         'requires explicitly requested Linux bubblewrap integration')
    async def test_fixed_fake_executable_inside_offline_sandbox(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / 'fake-executable'
            fake.write_bytes(b'#!/bin/sh\nprintf \'{"status":"complete","findings":["tests"]}\\n\'\n')
            fake.chmod(0o700)
            digest = hashlib.sha256(fake.read_bytes()).hexdigest()
            adapter = CodexReadOnly(CodexConfig(enabled=True, binary_path=str(fake), binary_sha256=digest))
            result = await adapter.execute(TASK_ID, [])
            self.assertEqual(result['summary'], 'Analysis categories: tests')
