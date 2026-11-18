"""Optional fixed read-only Codex boundary; never enabled by default."""
import asyncio
import hashlib
import json
import os
import platform
import re
import signal
import stat
from dataclasses import dataclass
from pathlib import Path

from bridge import BridgeError

ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / 'nexus-test'
TASK_ID = 'analyze:nexus-test'
PROMPT = ('Analyze the repository read-only. Return only the required JSON schema; '
          'select applicable finding categories. Never include text, secrets, paths, '
          'commands, or identifiers. Do not modify files or execute commands.')
BWRAP = '/usr/bin/bwrap'
SCHEMA = ROOT / 'codex_output_schema.json'
MAX_SECONDS = 30.0
MAX_BYTES = 4096


@dataclass(frozen=True)
class CodexConfig:
    enabled: bool = False
    timeout_seconds: float = MAX_SECONDS
    output_bytes: int = MAX_BYTES
    binary_path: str = ''
    binary_sha256: str = ''
    network: str = 'offline'

    def __post_init__(self):
        import math
        if type(self.enabled) is not bool:
            raise ValueError('invalid enabled flag')
        if (type(self.timeout_seconds) not in (float, int) or not math.isfinite(self.timeout_seconds)
                or not 0 < self.timeout_seconds <= MAX_SECONDS):
            raise ValueError('invalid timeout')
        if type(self.output_bytes) is not int or not 0 < self.output_bytes <= MAX_BYTES:
            raise ValueError('invalid output limit')
        if self.network not in ('offline', 'online'):
            raise ValueError('invalid network policy')
        if type(self.binary_path) is not str or type(self.binary_sha256) is not str:
            raise ValueError('invalid binary configuration')


def open_verified_binary(path, digest):
    """Open a configured regular executable and verify its pinned digest."""
    if not path or not os.path.isabs(path) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise BridgeError('codex_binary_config_invalid')
    fd = None
    try:
        if os.path.realpath(path) != path:
            raise BridgeError('codex_binary_path_invalid')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or not info.st_mode & 0o111
                or info.st_mode & 0o022 or info.st_uid not in (0, os.geteuid())):
            raise BridgeError('codex_binary_permissions_invalid')
        with os.fdopen(os.dup(fd), 'rb') as source:
            actual = hashlib.file_digest(source, 'sha256').hexdigest()
        if actual != digest:
            raise BridgeError('codex_binary_digest_mismatch')
        os.lseek(fd, 0, os.SEEK_SET)
        return fd
    except OSError:
        if fd is not None:
            os.close(fd)
        raise BridgeError('codex_binary_unavailable') from None
    except BaseException:
        if fd is not None:
            os.close(fd)
        raise


def safe_result(raw):
    """Accept only a closed, finite vocabulary; never propagate raw output."""
    def unique_pairs(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('duplicate')
            value[key] = item
        return value
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_pairs)
        if type(value) is not dict or set(value) != {'status', 'findings'}:
            raise ValueError('shape')
        if value['status'] != 'complete' or type(value['findings']) is not list:
            raise ValueError('fields')
        items = value['findings']
        allowed = {'documentation', 'configuration', 'tests', 'other'}
        if len(items) > 4 or any(type(x) is not str or x not in allowed for x in items) or len(items) != len(set(items)):
            raise ValueError('findings')
    except (UnicodeDecodeError, ValueError, TypeError, RecursionError):
        raise BridgeError('codex_output_refused') from None
    return {'type': 'result', 'summary': 'Analysis categories: ' + (', '.join(sorted(items)) if items else 'none')}


class CodexReadOnly:
    def __init__(self, config=None):
        self.config = config or CodexConfig()

    async def execute(self, task, history):
        if not self.config.enabled:
            raise BridgeError('codex_disabled')
        if task != TASK_ID:
            raise BridgeError('codex_task_refused')
        if platform.system() != 'Linux':
            raise BridgeError('codex_platform_unsupported')
        if FIXTURE.is_symlink() or not FIXTURE.is_dir():
            raise BridgeError('codex_fixture_unavailable')
        if SCHEMA.is_symlink() or not SCHEMA.is_file():
            raise BridgeError('codex_schema_unavailable')
        binary_fd = open_verified_binary(self.config.binary_path, self.config.binary_sha256)
        # Expose only system binaries and the fixed fixture, mounted read-only.
        # Network isolation and provider spending controls are separate concerns.
        argv = (BWRAP, '--die-with-parent', '--new-session', '--unshare-pid',
                '--unshare-ipc', '--unshare-uts') + (('--unshare-net',) if self.config.network == 'offline' else ()) + (
                '--dir', '/opt', '--ro-bind', f'/proc/self/fd/{binary_fd}', '/opt/codex',
                '--ro-bind', '/usr', '/usr',
                '--ro-bind', '/lib', '/lib', '--ro-bind', '/lib64', '/lib64',
                '--symlink', 'usr/bin', '/bin', '--proc', '/proc', '--dev', '/dev',
                '--tmpfs', '/tmp', '--ro-bind', str(FIXTURE), '/workspace',
                '--dir', '/policy', '--ro-bind', str(SCHEMA), '/policy/schema.json',
                '--setenv', 'HOME', '/tmp', '--setenv', 'CODEX_HOME', '/tmp/codex',
                '--chdir', '/workspace',
                '/opt/codex', 'exec', '--ignore-user-config', '--ephemeral',
                '--skip-git-repo-check', '--sandbox', 'read-only',
                '--output-schema', '/policy/schema.json', PROMPT)
        env = {'PATH': '/usr/bin:/bin', 'HOME': '/tmp', 'CODEX_HOME': '/tmp/codex',
               'LANG': 'C.UTF-8'}
        proc = None
        try:
            async with asyncio.timeout(self.config.timeout_seconds):
                proc = await asyncio.create_subprocess_exec(
                    *argv, stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                    env=env, start_new_session=True, pass_fds=(binary_fd,))
                chunks = bytearray()
                while True:
                    chunk = await proc.stdout.read(min(1024, self.config.output_bytes + 1 - len(chunks)))
                    if not chunk:
                        break
                    chunks.extend(chunk)
                    if len(chunks) > self.config.output_bytes:
                        raise BridgeError('codex_output_limit')
                if await proc.wait() != 0:
                    raise BridgeError('codex_process_failed')
                return safe_result(bytes(chunks))
        except TimeoutError:
            raise BridgeError('codex_timeout') from None
        except OSError:
            raise BridgeError('codex_start_failed') from None
        finally:
            os.close(binary_fd)
            if proc is not None and proc.returncode is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await proc.wait()
