import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from web_server import App, Server, handler_for
from bridge import BridgeError
from memory import Memory


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = App(Path(self.tmp.name))
        recipes = Path(self.tmp.name) / 'vault' / 'Cuisine' / 'Recettes'
        recipes.mkdir(parents=True)
        (recipes / 'Chili con carne.md').write_text('# Chili con carne\nIngrédients : non renseignés.\n', encoding='utf-8')
        self.app.memory = Memory(Path(self.tmp.name) / 'vault')
        self.app.pin.configure('258036')
        self.server = Server(('127.0.0.1', 0), handler_for(self.app, 'http://127.0.0.1:1'))
        self.origin = 'http://127.0.0.1:' + str(self.server.server_port)
        self.server.RequestHandlerClass = handler_for(self.app, self.origin)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, data=None, cookie=None, origin=None, host=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        headers = {'Host': host or self.origin.removeprefix('http://')}
        if method == 'POST':
            headers.update({'Origin': origin or self.origin, 'Content-Type': 'application/json'})
        if cookie:
            headers['Cookie'] = cookie
        body = None if data is None else json.dumps(data)
        try:
            conn.request(method, path, body, headers)
            result = conn.getresponse()
            content = result.read()
            return result.status, dict(result.getheaders()), json.loads(content) if content.startswith(b'{') else content
        finally:
            conn.close()

    def login(self):
        status, headers, _ = self.request('POST', '/api/login', {'password': '258036'})
        self.assertEqual(status, 200)
        return headers['Set-Cookie'].split(';')[0]

    def wait_for_state(self, mid, state):
        for _ in range(100):
            row = self.app.detail(mid)
            if row['state'] == state:
                return row
            time.sleep(.02)
        self.fail('mission did not reach ' + state)

    def test_login_host_origin_and_authentication(self):
        self.assertEqual(self.request('GET', '/api/missions')[0], 401)
        self.assertEqual(self.request('POST', '/api/login', {'password': 'bad'})[0], 403)
        self.assertEqual(self.request('POST', '/api/login', {'password': '258036'}, origin='https://attacker.example')[0], 403)
        self.assertEqual(self.request('GET', '/', host='attacker.example')[0], 403)
        cookie = self.login()
        self.assertEqual(self.request('GET', '/api/session', cookie=cookie)[0], 200)

    def test_calendar_requires_session_and_returns_safe_errors(self):
        self.assertEqual(self.request('GET', '/api/calendar/upcoming')[0], 401)
        cookie = self.login()
        with patch('web_server.calendar_upcoming', return_value=[{'title':'Test','start':'2026-11-17'}]):
            self.assertEqual(self.request('GET', '/api/calendar/upcoming', cookie=cookie)[2]['events'][0]['title'], 'Test')
        with patch('web_server.calendar_interpret', return_value='Agenda principal : Test'):
            status, _, response = self.request('POST', '/api/voice', {'question':'Quel est mon agenda ?'}, cookie=cookie)
            self.assertEqual(status, 200)
            self.assertIn('Test', response['reply'])
        from calendar_reader import CalendarUnavailable
        with patch('web_server.calendar_upcoming', side_effect=CalendarUnavailable()):
            self.assertEqual(self.request('GET', '/api/calendar/upcoming', cookie=cookie)[0], 503)

    def test_speech_endpoint_requires_auth_and_bounds_input(self):
        self.assertEqual(self.request('POST', '/api/speech', {'text':'test','language':'fr'})[0], 401)
        cookie = self.login()
        with patch('web_server.synthesize', return_value=b'RIFF\x04\x00\x00\x00WAVE'):
            status, headers, body = self.request('POST', '/api/speech', {'text':'test','language':'fr'}, cookie=cookie)
            self.assertEqual(status, 200)
            self.assertEqual(headers['Content-Type'], 'audio/wav')
            self.assertEqual(body[:4], b'RIFF')
        self.assertEqual(self.request('POST', '/api/speech', {'text':'x'*501,'language':'fr'}, cookie=cookie)[0], 400)

    def test_calendar_plan_and_phone_data_require_auth_and_validate_fields(self):
        self.assertEqual(self.request('POST', '/api/calendar/plan', {'question':'agenda demain'})[0], 401)
        cookie = self.login()
        status, _, plan = self.request('POST', '/api/calendar/plan', {'question':'agenda demain'}, cookie=cookie)
        self.assertEqual(status, 200)
        self.assertTrue(plan['calendar'])
        bad = {'title':'Test','start':'bad','end':'bad','all_day':False,'busy':True}
        self.assertEqual(self.request('POST', '/api/voice', {'question':'agenda demain','android_events':[bad]}, cookie=cookie)[0], 400)

    def test_memory_endpoint_requires_auth_and_live_answer_is_disabled(self):
        self.assertEqual(self.request('POST', '/api/memory/search', {'query':'chili'})[0], 401)
        cookie = self.login()
        status, _, body = self.request('POST', '/api/memory/search', {'query':'chili'}, cookie=cookie)
        self.assertEqual(status, 200)
        self.assertTrue(body['results'])
        self.assertEqual(self.request('POST', '/api/memory/answer', {'question':'chili','billing_confirmed':True}, cookie=cookie)[0], 400)
        status, _, voice = self.request('POST', '/api/voice', {'question':'retrouve ma recette de chili'}, cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn('Chili', voice['reply'])
        self.assertIn('non renseign', voice['reply'])
        self.app.allow_live = True
        with patch('web_server.memory_answer', return_value='Fiche Chili : quantités non renseignées.') as fake:
            status, _, result = self.request('POST', '/api/memory/answer', {'question':'chili','billing_confirmed':True}, cookie=cookie)
            self.assertEqual(status, 200)
            self.assertIn('Chili', result['reply'])
            fake.assert_called_once()

    def test_voice_is_authenticated_bounded_and_read_only(self):
        self.assertEqual(self.request('POST', '/api/voice', {'question':'état des missions'})[0], 401)
        cookie = self.login()
        self.assertEqual(self.request('POST', '/api/voice', {'question':'x' * 501}, cookie=cookie)[0], 400)
        self.assertEqual(self.request('POST', '/api/voice', {'question':'état des missions', 'command':'whoami'}, cookie=cookie)[0], 400)
        status, _, body = self.request('POST', '/api/voice', {'question':'état des missions'}, cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn('mission', body['reply'])
        self.assertEqual(self.app.listing(), [])

    def test_first_use_bootstrap_requires_new_pin_and_is_one_time(self):
        fresh = App(Path(self.tmp.name) / 'fresh')
        server = Server(('127.0.0.1', 0), handler_for(fresh, 'http://127.0.0.1:1'))
        origin = 'http://127.0.0.1:' + str(server.server_port)
        server.RequestHandlerClass = handler_for(fresh, origin)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        def request(method, path, data):
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            try:
                conn.request(method, path, json.dumps(data), {'Host': origin.removeprefix('http://'), 'Origin': origin, 'Content-Type': 'application/json'})
                response = conn.getresponse(); return response.status, dict(response.getheaders()), response.read()
            finally: conn.close()
        self.assertEqual(request('POST', '/api/login', {'password':'000000'})[0], 428)
        self.assertEqual(request('POST', '/api/setup', {'bootstrap':'000000','pin':'000000','confirmation':'000000'})[0], 403)
        self.assertEqual(request('POST', '/api/setup', {'bootstrap':'000000','pin':'731904','confirmation':'731905'})[0], 403)
        status, headers, body = request('POST', '/api/setup', {'bootstrap':'000000','pin':'731904','confirmation':'731904'})
        self.assertEqual(status, 200, body)
        cookie = headers['Set-Cookie'].split(';')[0]
        self.assertTrue(fresh.authorized(cookie.split('=', 1)[1]))
        self.assertEqual(request('POST', '/api/setup', {'bootstrap':'000000','pin':'123456','confirmation':'123456'})[0], 403)
        database = Path(self.tmp.name) / 'fresh' / 'missions.sqlite3'
        contents = database.read_bytes()
        self.assertNotIn(b'000000', contents)
        self.assertNotIn(b'731904', contents)

    def test_pin_changes_invalidate_existing_sessions(self):
        cookie = self.login()
        self.app.pin.configure('731904')
        self.assertEqual(self.request('GET', '/api/session', cookie=cookie)[0], 401)
        self.assertEqual(self.request('POST', '/api/login', {'password': '258036'})[0], 403)
        self.assertEqual(self.request('POST', '/api/login', {'password': '731904'})[0], 200)

    def test_pin_attempts_are_limited_across_restart(self):
        for _ in range(5):
            self.assertEqual(self.request('POST', '/api/login', {'password': '000000'})[0], 403)
        self.assertEqual(self.request('POST', '/api/login', {'password': '258036'})[0], 403)
        from pin_auth import PinAuth
        self.assertIsNone(PinAuth(Path(self.tmp.name) / 'missions.sqlite3').verify('258036'))
        with patch('pin_auth.time.time', return_value=time.time() + 901):
            self.assertEqual(self.request('POST', '/api/login', {'password': '258036'})[0], 200)

    def test_pin_format_and_no_plaintext_storage(self):
        from pin_auth import PinAuth
        for value in ('12345', '1234567', '１２３４５６', 'abc123', None):
            self.assertFalse(PinAuth.valid(value))
        with self.assertRaises(ValueError):
            self.app.pin.configure('000000')
        self.assertNotIn(b'258036', (Path(self.tmp.name) / 'missions.sqlite3').read_bytes())

    def test_simulated_mission_and_approval(self):
        cookie = self.login()
        status, _, body = self.request('POST', '/api/missions', {'mode':'simulation'}, cookie=cookie)
        self.assertEqual(status, 201)
        mid = body['id']
        self.wait_for_state(mid, 'awaiting_approval')
        self.assertEqual(self.request('POST', '/api/missions/' + mid + '/approve', {'approve':True})[0], 401)
        self.assertEqual(self.request('POST', '/api/missions/' + mid + '/approve', {'approve':True}, cookie=cookie)[0], 200)
        result = self.wait_for_state(mid, 'completed')
        self.assertEqual([m['body']['type'] for m in result['messages']], ['proposal', 'result', 'review'])
        self.assertEqual(result['api_calls'], 0)

    def test_rejects_arbitrary_commands_and_live_default(self):
        cookie = self.login()
        self.assertEqual(self.request('POST', '/api/missions', {'mode':'simulation','command':'whoami'}, cookie=cookie)[0], 400)
        self.assertEqual(self.request('POST', '/api/missions', {'mode':'live','billing_confirmed':True}, cookie=cookie)[0], 400)
        self.assertEqual(self.request('GET', '/')[0], 200)

    def test_live_mode_requires_billing_and_approval_with_mocked_agents(self):
        calls = []
        class FakeArchitect:
            def __init__(self): self.calls = 0
            async def plan(self, task, history):
                self.calls += 1
                return {'type': 'proposal', 'summary': 'Plan de test', 'task': task}
            async def review(self, task, history):
                self.calls += 1
                return {'type': 'review', 'decision': 'accept', 'summary': 'Conclusion de test'}
        class FakeExecutor:
            def __init__(self, *args): pass
            async def execute(self, task, history):
                calls.append(task)
                return {'type': 'result', 'summary': 'Résultat de test'}
        self.app.allow_live = True
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'synthetic'}), \
             patch('web_server.OpenAIArchitect', FakeArchitect), patch('web_server.LocalCodex', FakeExecutor), \
             patch('web_server.expected_content', return_value=b'fixture'), \
             patch('web_server.require_chatgpt_login'), patch('web_server.codex_binary'), \
             patch('web_server.subprocess.run'):
            with self.assertRaises(BridgeError):
                self.app.create('live', False)
            mid = self.app.create('live', True)
            self.wait_for_state(mid, 'awaiting_approval')
            self.assertEqual(calls, [])
            for _ in range(100):
                with self.app.lock:
                    busy = self.app.workers[mid]['busy']
                if not busy: break
                time.sleep(.01)
            self.app.approve(mid)
            self.wait_for_state(mid, 'completed')
            self.assertEqual(len(calls), 1)
