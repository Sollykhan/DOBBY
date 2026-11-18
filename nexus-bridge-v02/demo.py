"""Démonstration locale interactive : architecte simulé et Codex CLI réel."""
import asyncio
import argparse
import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

from bridge import BridgeError, Limits, Orchestrator, SimulatedArchitect, Store
from codex_adapter import PROMPT, SCHEMA, TASK_ID, safe_result
from openai_architect import DEFAULT_MODEL, MODELS, OpenAIArchitect

ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / 'nexus-test' / 'README.md'
FIXTURE_SHA256 = 'eb29b4e6e6e6903603fa3752aa351baf9a8e08116c7a2a3ce05f2787b679c17b'
MAX_OUTPUT = 4096
TIMEOUT = 120
EXCLUDED_ENV = {'OPENAI_API_KEY', 'CODEX_API_KEY', 'CODEX_ACCESS_TOKEN'}


def child_environment():
    # Never inspect or pass API/access-token variables; retain local login discovery.
    return {key: os.environ[key] for key in os.environ if key.upper() not in EXCLUDED_ENV}


def require_chatgpt_login(executable):
    result = subprocess.run([str(executable), 'login', 'status'], env=child_environment(),
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    if result.returncode != 0 or b'chatgpt' not in (result.stdout + result.stderr).lower():
        raise BridgeError('chatgpt_login_unconfirmed')


def expected_content():
    if FIXTURE.is_symlink() or not FIXTURE.is_file():
        raise BridgeError('fixture_invalid')
    data = FIXTURE.read_bytes()
    if hashlib.sha256(data).hexdigest() != FIXTURE_SHA256:
        raise BridgeError('fixture_changed')
    return data


def verify_workspace(path, expected):
    # Ignore Git metadata, but refuse unanticipated worktree files or links.
    files = [p for p in path.iterdir() if p.name != '.git']
    if len(files) != 1 or files[0].name != 'README.md' or files[0].is_symlink():
        raise BridgeError('workspace_changed')
    if files[0].read_bytes() != expected:
        raise BridgeError('workspace_changed')


def codex_binary():
    appdata = os.environ.get('APPDATA')
    if not appdata:
        raise BridgeError('codex_unavailable')
    path = Path(appdata) / 'npm/node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe'
    if not path.is_file():
        raise BridgeError('codex_unavailable')
    return path


class DemoArchitect(SimulatedArchitect):
    async def plan(self, task, history):
        return {'type': 'proposal', 'summary': 'Demander à Codex une analyse en lecture seule du dépôt témoin', 'task': TASK_ID}

    async def review(self, task, history):
        if not history or history[-1]['role'] != 'executor' or not history[-1]['body']['summary'].startswith('Analysis categories: '):
            raise BridgeError('invalid_codex_result')
        return {'type': 'review', 'decision': 'accept',
                'summary': 'Évaluation simulée : réponse structurée acceptée. ' + history[-1]['body']['summary']}


class LocalCodex:
    def __init__(self, workspace, expected, executable=None):
        self.workspace, self.expected, self.executable = workspace, expected, executable

    async def execute(self, task, history):
        if task != TASK_ID:
            raise BridgeError('codex_task_refused')
        if platform.system() != 'Windows':
            raise BridgeError('windows_required')
        verify_workspace(self.workspace, self.expected)
        executable = self.executable or codex_binary()
        args = [str(executable), 'exec', '--sandbox', 'read-only', '--ephemeral',
                '--color', 'never', '--cd', str(self.workspace), '--output-schema', str(SCHEMA), PROMPT]
        proc = None
        try:
            async with asyncio.timeout(TIMEOUT):
                # Preserve local login discovery and managed configuration, without API key variables.
                proc = await asyncio.create_subprocess_exec(*args, cwd=str(self.workspace),
                    stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL, env=child_environment())
                output = bytearray()
                while True:
                    block = await proc.stdout.read(min(1024, MAX_OUTPUT + 1 - len(output)))
                    if not block:
                        break
                    output.extend(block)
                    if len(output) > MAX_OUTPUT:
                        raise BridgeError('codex_output_limit')
                if await proc.wait():
                    raise BridgeError('codex_process_failed')
                return safe_result(bytes(output))
        except TimeoutError:
            raise BridgeError('codex_timeout') from None
        except OSError:
            raise BridgeError('codex_start_failed') from None
        finally:
            if proc is not None and proc.returncode is None:
                proc.kill()
                await proc.wait()
            verify_workspace(self.workspace, self.expected)


async def demo(workspace, expected, approve=input, architect=None):
    store = Store(workspace.parent / 'demo.sqlite3')
    mid = store.create(TASK_ID, Limits(max_turns=9, max_seconds=540))
    orchestrator = Orchestrator(store, architect or DemoArchitect(), LocalCodex(workspace, expected))
    shown = 0
    while True:
        row = await orchestrator.run(mid)
        messages = store.messages(mid)
        for message in messages[shown:]:
            kind = message['body']['type']
            label = 'Codex' if kind == 'result' else 'Architecte'
            print(label + ' :', message['body']['summary'])
        shown = len(messages)
        if row['state'] == 'completed':
            print('Conclusion :', messages[-1]['body']['summary'])
            return 0
        if row['state'] != 'awaiting_approval':
            print('Échec de la démonstration :', row['error'])
            return 1
        if approve('Autoriser cet appel Codex réel avec votre session ChatGPT ? [oui/N] ').strip().lower() != 'oui':
            print('Démonstration arrêtée avant cet appel Codex.')
            return 1
        store.approve(mid)


def main():
    parser = argparse.ArgumentParser(description='DOBBY V1 — assistant personnel')
    parser.add_argument('--architect', choices=('simulated', 'openai'), default='simulated')
    parser.add_argument('--model', choices=MODELS, default=DEFAULT_MODEL)
    args = parser.parse_args()
    print('DOBBY V1 — assistant personnel')
    if platform.system() != 'Windows':
        print('Cette démonstration locale exige Windows.', file=sys.stderr)
        return 1
    try:
        data = expected_content()
        executable = codex_binary()
        require_chatgpt_login(executable)
        architect = DemoArchitect()
        if args.architect == 'openai':
            if not os.environ.get('OPENAI_API_KEY'):
                raise BridgeError('architect_api_key_missing')
            print('API OpenAI facturable : modèle', args.model,
                  '; maximum 6 appels, réservation logicielle 0,12 USD (pas un plafond garanti).')
            if input('Confirmez-vous la clé, la facturation et cet essai API ? [oui/N] ').strip().lower() != 'oui':
                print('Arrêt avant tout appel API.')
                return 1
            architect = OpenAIArchitect(args.model)
        with tempfile.TemporaryDirectory(prefix='dobby-demo-', dir=ROOT) as directory:
            workspace = Path(directory) / 'nexus-test'
            workspace.mkdir()
            (workspace / 'README.md').write_bytes(data)
            subprocess.run(['git', 'init', '--quiet', str(workspace)], check=True,
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            verify_workspace(workspace, data)
            return asyncio.run(demo(workspace, data, architect=architect))
    except (BridgeError, OSError, subprocess.SubprocessError) as exc:
        print('Démonstration impossible :', str(exc) if isinstance(exc, BridgeError) else 'préparation locale échouée', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
