"""DOBBY local web interface. Simulation by default; binds loopback only."""
import argparse
import asyncio
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from bridge import BridgeError, Limits, Orchestrator, SimulatedExecutor, Store
from codex_adapter import TASK_ID
from demo import DemoArchitect, LocalCodex, expected_content, require_chatgpt_login, codex_binary
from openai_architect import MAX_CALLS, OpenAIArchitect
from pin_auth import PinAuth
from memory import Memory
from memory_architect import answer as memory_answer
from calendar_reader import CalendarUnavailable, upcoming as calendar_upcoming
from calendar_reader import interpret as calendar_interpret
from calendar_reader import plan as calendar_plan
from speech_provider import synthesize, SpeechUnavailable
import datetime

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / 'web'
DATA = ROOT / '.dobby-local'
MAX_BODY = 8192
PORT = 8765


class WebSimulatedExecutor(SimulatedExecutor):
    async def execute(self, task, history):
        return {'type': 'result', 'summary': 'Analysis categories: documentation'}


class App:
    def __init__(self, directory, allow_live=False):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.directory / 'missions.sqlite3')
        self.pin = PinAuth(self.directory / 'missions.sqlite3')
        self.memory = Memory()
        self.allow_live = allow_live
        self.memory_calls = 0
        self.sessions = {}
        self.workers = {}
        self.lock = threading.RLock()
        with self.store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS web_missions (id TEXT PRIMARY KEY, mode TEXT NOT NULL, created REAL NOT NULL, api_calls INTEGER NOT NULL DEFAULT 0)')
            # Unknown in-flight operations are never repeated after a restart.
            db.execute("UPDATE missions SET state='failed',error='interrupted_unknown_outcome' WHERE state='running'")
            db.execute("UPDATE missions SET state='failed',error='restart_requires_new_mission' WHERE id IN (SELECT id FROM web_missions) AND state='ready'")
            db.execute("UPDATE missions SET state='failed',error='restart_requires_new_mission' WHERE id IN (SELECT id FROM web_missions WHERE mode='live') AND state='awaiting_approval'")
            waiting = db.execute("SELECT m.id FROM missions m JOIN web_missions w ON m.id=w.id WHERE m.state='awaiting_approval' AND w.mode='simulation'").fetchall()
        for row in waiting:
            architect = DemoArchitect()
            self.workers[row['id']] = {'orchestrator': Orchestrator(self.store, architect, WebSimulatedExecutor()), 'busy': False, 'architect': architect}

    def login(self, password):
        with self.lock:
            now = time.monotonic()
            generation = self.pin.verify(password)
            if generation is None:
                return None
            token = secrets.token_urlsafe(32)
            self.sessions[token] = (now + 3600 * 8, generation)
            return token

    def setup(self, bootstrap, pin, confirmation):
        if not self.pin.configure_from_bootstrap(bootstrap, pin, confirmation):
            return None
        return self.login(pin)

    def authorized(self, token):
        with self.lock:
            session = self.sessions.get(token)
            return bool(session and session[0] > time.monotonic() and session[1] == self.pin.generation())

    def listing(self):
        with self.store.connect() as db:
            rows = db.execute('SELECT m.id,m.state,m.stage,m.turns,m.error,w.mode,w.created,w.api_calls FROM missions m JOIN web_missions w ON m.id=w.id ORDER BY w.created DESC LIMIT 100').fetchall()
        return [dict(r) for r in rows]

    def detail(self, mid):
        with self.store.connect() as db:
            meta = db.execute('SELECT mode,created,api_calls FROM web_missions WHERE id=?', (mid,)).fetchone()
        if meta is None:
            raise BridgeError('unknown_mission')
        row = self.store.get(mid)
        return {'id': mid, 'state': row['state'], 'stage': row['stage'], 'turns': row['turns'],
                'error': row['error'], 'mode': meta['mode'], 'created': meta['created'],
                'api_calls': meta['api_calls'], 'messages': self.store.messages(mid)}

    def create(self, mode, billing_confirmed=False):
        if mode not in ('simulation', 'live'):
            raise BridgeError('invalid_mode')
        if mode == 'live' and (not self.allow_live or billing_confirmed is not True or not os.environ.get('OPENAI_API_KEY')):
            raise BridgeError('live_not_authorized')
        data = None
        if mode == 'live':
            data = expected_content()
            require_chatgpt_login(codex_binary())
        with self.lock:
            if len(self.workers) >= 20:
                raise BridgeError('capacity')
            mid = self.store.create(TASK_ID, Limits(max_turns=9, max_seconds=540))
            with self.store.connect() as db:
                db.execute('INSERT INTO web_missions(id,mode,created) VALUES(?,?,?)', (mid, mode, time.time()))
            architect = OpenAIArchitect() if mode == 'live' else DemoArchitect()
            if mode == 'live':
                # Fixed test fixture, no user-supplied path or executable.
                workspace = self.directory / ('mission-' + mid)
                try:
                    workspace.mkdir(mode=0o700)
                    (workspace / 'README.md').write_bytes(data)
                    subprocess.run(['git', 'init', '--quiet', str(workspace)], check=True,
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
                except (OSError, subprocess.SubprocessError):
                    Orchestrator(self.store)._fail(mid, 'workspace_preparation_failed')
                    raise
                executor = LocalCodex(workspace, data)
            else:
                executor = WebSimulatedExecutor()
            self.workers[mid] = {'orchestrator': Orchestrator(self.store, architect, executor), 'busy': False, 'architect': architect}
            self._schedule(mid)
        return mid

    def approve(self, mid):
        with self.lock:
            item = self.workers.get(mid)
            if not item or item['busy']:
                raise BridgeError('mission_unavailable')
            self.store.approve(mid)
            self._schedule(mid)

    def _schedule(self, mid):
        item = self.workers[mid]
        item['busy'] = True
        def run():
            try:
                asyncio.run(item['orchestrator'].run(mid))
            except Exception:
                item['orchestrator']._fail(mid, 'worker_failed')
            finally:
                calls = getattr(item['architect'], 'calls', 0)
                with self.store.connect() as db:
                    db.execute('UPDATE web_missions SET api_calls=? WHERE id=?', (calls, mid))
                with self.lock:
                    item['busy'] = False
                    if self.store.get(mid)['state'] in ('completed', 'failed'):
                        self.workers.pop(mid, None)
        threading.Thread(target=run, daemon=True).start()


class Server(ThreadingHTTPServer):
    daemon_threads = True


def handler_for(app, allowed_origin):
    allowed_origins = (allowed_origin,) if isinstance(allowed_origin, str) else tuple(allowed_origin)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def valid_host(self):
            return any(self.headers.get('Host', '') == urllib.parse.urlsplit(value).netloc for value in allowed_origins)

        def send_bytes(self, code, body, content_type, extra=None):
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            self.send_header('Referrer-Policy', 'no-referrer')
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def json(self, code, data, extra=None):
            self.send_bytes(code, json.dumps(data, ensure_ascii=False).encode(), 'application/json; charset=utf-8', extra)

        def token(self):
            from http.cookies import SimpleCookie
            try:
                cookie = SimpleCookie(self.headers.get('Cookie', ''))
                return cookie['dobby_session'].value if 'dobby_session' in cookie else None
            except Exception:
                return None

        def do_GET(self):
            if not self.valid_host():
                return self.json(403, {'error': 'host_refused'})
            path = urllib.parse.urlsplit(self.path).path
            static = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css; charset=utf-8'), '/manifest.webmanifest': ('manifest.webmanifest', 'application/manifest+json'), '/icon.svg': ('icon.svg', 'image/svg+xml'), '/icon-192.png': ('icon-192.png', 'image/png'), '/icon-512.png': ('icon-512.png', 'image/png')}
            if path in static:
                filename, mime = static[path]
                return self.send_bytes(200, (ASSETS / filename).read_bytes(), mime)
            if not app.authorized(self.token()):
                return self.json(401, {'error': 'authentication_required'})
            if path == '/api/session':
                return self.json(200, {'authenticated': True, 'live_enabled': app.allow_live, 'limits': {'cycles': 3, 'api_calls': MAX_CALLS, 'software_budget_usd': '0.12'}})
            if path == '/api/calendar/upcoming':
                try:
                    return self.json(200, {'events': calendar_upcoming()})
                except CalendarUnavailable:
                    return self.json(503, {'error': 'agenda_indisponible'})
            if path == '/api/missions':
                return self.json(200, {'missions': app.listing()})
            if path.startswith('/api/missions/'):
                try:
                    return self.json(200, app.detail(path.removeprefix('/api/missions/')))
                except BridgeError:
                    return self.json(404, {'error': 'mission_inconnue'})
            return self.json(404, {'error': 'not_found'})

        def do_POST(self):
            try:
                size = int(self.headers.get('Content-Length', '-1'))
                if size < 0 or size > MAX_BODY or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    return self.json(400, {'error': 'invalid_request'})
                data = json.loads(self.rfile.read(size))
                if type(data) is not dict:
                    raise ValueError()
            except (ValueError, UnicodeError):
                return self.json(400, {'error': 'invalid_request'})
            origin = self.headers.get('Origin', '')
            if origin not in allowed_origins or self.headers.get('Host', '') != urllib.parse.urlsplit(origin).netloc:
                return self.json(403, {'error': 'origin_refused'})
            path = urllib.parse.urlsplit(self.path).path
            if path == '/api/login':
                if not app.pin.configured() and data.get('password') == '000000':
                    return self.json(428, {'error': 'setup_required'})
                token = app.login(data.get('password'))
                if not token:
                    return self.json(403, {'error': 'identification_refusee'})
                secure = '; Secure' if origin.startswith('https://') else ''
                return self.json(200, {'ok': True}, {'Set-Cookie': 'dobby_session=' + token + '; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800' + secure})
            if path == '/api/setup':
                if set(data) != {'bootstrap', 'pin', 'confirmation'}:
                    return self.json(400, {'error': 'invalid_request'})
                token = app.setup(data.get('bootstrap'), data.get('pin'), data.get('confirmation'))
                if not token:
                    return self.json(403, {'error': 'setup_refused'})
                secure = '; Secure' if origin.startswith('https://') else ''
                return self.json(200, {'ok': True}, {'Set-Cookie': 'dobby_session=' + token + '; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800' + secure})
            if not app.authorized(self.token()):
                return self.json(401, {'error': 'authentication_required'})
            try:
                if path == '/api/speech':
                    if set(data) != {'text', 'language'}:
                        raise BridgeError('invalid_request')
                    try:
                        audio = synthesize(data['text'], data['language'])
                    except SpeechUnavailable:
                        return self.json(503, {'error': 'voix_indisponible'})
                    return self.send_bytes(200, audio, 'audio/wav')
                if path == '/api/calendar/plan':
                    if set(data) != {'question'} or not isinstance(data['question'], str) or not 1 <= len(data['question']) <= 500:
                        raise BridgeError('invalid_request')
                    return self.json(200, calendar_plan(data['question']))
                if path == '/api/memory/search':
                    if set(data) != {'query'}:
                        raise BridgeError('invalid_request')
                    return self.json(200, {'results': app.memory.search(data['query'])})
                if path == '/api/memory/answer':
                    if set(data) != {'question', 'billing_confirmed'} or data.get('billing_confirmed') is not True or not app.allow_live:
                        raise BridgeError('live_not_authorized')
                    question = data['question']
                    sources = app.memory.search(question)
                    if not sources:
                        return self.json(200, {'reply': 'Aucune fiche correspondante trouvée.', 'sources': []})
                    with app.lock:
                        if app.memory_calls >= MAX_CALLS:
                            raise BridgeError('architect_budget_exhausted')
                        app.memory_calls += 1
                    return self.json(200, {'reply': memory_answer(question, sources), 'sources': [item['source'] for item in sources]})
                if path == '/api/voice':
                    if set(data) - {'question', 'android_events'} or not isinstance(data.get('question'), str) or not 1 <= len(data['question'].strip()) <= 500:
                        raise BridgeError('invalid_request')
                    supplied = data.get('android_events', [])
                    if not isinstance(supplied, list) or len(supplied) > 20: raise BridgeError('invalid_request')
                    extra = []
                    for item in supplied:
                        if not isinstance(item, dict) or set(item) != {'title','start','end','all_day','busy'} or not isinstance(item['title'], str) or len(item['title']) > 120 or not isinstance(item['start'], str) or not isinstance(item['end'], str) or len(item['start']) > 64 or len(item['end']) > 64 or type(item['all_day']) is not bool or type(item['busy']) is not bool:
                            raise BridgeError('invalid_request')
                        start = datetime.datetime.fromisoformat(item['start']); end = datetime.datetime.fromisoformat(item['end'])
                        if start.tzinfo is None or end.tzinfo is None or end <= start: raise BridgeError('invalid_request')
                        extra.append({**item, 'start':start, 'end':end})
                    question = data['question'].casefold()
                    try:
                        agenda_response = calendar_interpret(data['question'], extra_events=extra) if extra else calendar_interpret(data['question'])
                    except CalendarUnavailable:
                        agenda_response = 'Agenda indisponible. Vérifiez la connexion Google sur votre ordinateur.'
                    if agenda_response is not None:
                        response = agenda_response
                    elif 'mission' in question or 'statut' in question:
                        missions = app.listing()
                        response = 'Aucune mission pour le moment.' if not missions else 'Dernière mission : ' + missions[0]['state'] + '. En attente : ' + str(sum(m['state'] == 'awaiting_approval' for m in missions)) + '.'
                    else:
                        found = app.memory.search(data['question'])
                        response = ('Fiche ' + found[0]['title'] + ' : ' + found[0]['excerpt'].replace('\n', '. ')[:350]) if found else 'Je ne trouve pas de fiche correspondante dans la mémoire Cuisine.'
                    return self.json(200, {'reply': response})
                if path == '/api/missions':
                    if set(data) - {'mode', 'billing_confirmed'}:
                        raise BridgeError('invalid_request')
                    mid = app.create(data.get('mode'), data.get('billing_confirmed', False))
                    return self.json(201, {'id': mid})
                if path.startswith('/api/missions/') and path.endswith('/approve'):
                    if data != {'approve': True}:
                        raise BridgeError('invalid_request')
                    mid = path[len('/api/missions/'):-len('/approve')]
                    app.approve(mid)
                    return self.json(200, {'ok': True})
            except (BridgeError, ValueError, OSError, subprocess.SubprocessError):
                return self.json(400, {'error': 'action_impossible'})
            return self.json(404, {'error': 'not_found'})

    return Handler


def main():
    parser = argparse.ArgumentParser(description='DOBBY local web server')
    parser.add_argument('--allow-live', action='store_true', help='Autoriser les missions réelles après confirmation de facturation')
    parser.add_argument('--origin', default='http://127.0.0.1:8765', help='Origine exacte autorisée pour un proxy HTTPS privé')
    args = parser.parse_args()
    origin = urllib.parse.urlsplit(args.origin)
    if args.origin != 'http://127.0.0.1:8765' and (origin.scheme != 'https' or not origin.hostname or origin.path or origin.query or origin.fragment or origin.username):
        parser.error('origine privée HTTPS exacte requise')
    DATA.mkdir(exist_ok=True)
    app = App(DATA, args.allow_live)
    origins = ('http://127.0.0.1:8765',) if args.origin == 'http://127.0.0.1:8765' else ('http://127.0.0.1:8765', args.origin)
    server = Server(('127.0.0.1', PORT), handler_for(app, origins))
    print('DOBBY : http://127.0.0.1:8765/ — configurer le PIN avec python set_pin.py', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
