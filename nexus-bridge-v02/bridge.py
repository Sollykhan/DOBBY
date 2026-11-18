"""DOBBY Bridge: bounded, approval-gated agent collaboration."""
import asyncio
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path


class BridgeError(Exception):
    pass


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


@dataclass(frozen=True)
class Limits:
    max_turns: int = 8
    max_seconds: float = 30
    max_message_bytes: int = 8192
    max_total_bytes: int = 65536
    max_cost_units: int = 100
    call_cost_units: int = 1

    def __post_init__(self):
        import math
        if (any(type(x) is not int or x <= 0 for x in (self.max_turns, self.max_message_bytes,
                self.max_total_bytes, self.max_cost_units, self.call_cost_units))
                or type(self.max_seconds) not in (int, float) or not math.isfinite(self.max_seconds)
                or self.max_seconds <= 0):
            raise ValueError('invalid limits')


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS missions(
              id TEXT PRIMARY KEY, state TEXT NOT NULL, stage TEXT NOT NULL,
              task TEXT NOT NULL, limits TEXT NOT NULL, turns INTEGER NOT NULL DEFAULT 0,
              bytes INTEGER NOT NULL DEFAULT 0, cost INTEGER NOT NULL DEFAULT 0,
              elapsed REAL NOT NULL DEFAULT 0, result TEXT, error TEXT);
            CREATE TABLE IF NOT EXISTS messages(
              mission_id TEXT NOT NULL, seq INTEGER NOT NULL, role TEXT NOT NULL,
              body TEXT NOT NULL, PRIMARY KEY(mission_id, seq),
              FOREIGN KEY(mission_id) REFERENCES missions(id));
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, task, limits):
        if not isinstance(task, str) or not task.strip():
            raise BridgeError('invalid_task')
        size = len(task.encode('utf-8'))
        if size > limits.max_message_bytes or size > limits.max_total_bytes:
            raise BridgeError('input_limit')
        mid = str(uuid.uuid4())
        with self.connect() as db:
            db.execute('INSERT INTO missions(id,state,stage,task,limits,bytes) VALUES(?,?,?,?,?,?)',
                       (mid, 'ready', 'plan', task, encoded(asdict(limits)), size))
        return mid

    def get(self, mid):
        with self.connect() as db:
            row = db.execute('SELECT * FROM missions WHERE id=?', (mid,)).fetchone()
        if row is None:
            raise BridgeError('unknown_mission')
        return dict(row)

    def messages(self, mid):
        with self.connect() as db:
            rows = db.execute('SELECT role,body FROM messages WHERE mission_id=? ORDER BY seq', (mid,)).fetchall()
        return [{'role': row['role'], 'body': json.loads(row['body'])} for row in rows]

    def approve(self, mid):
        with self.connect() as db:
            cur = db.execute("UPDATE missions SET state='ready', stage='execute' WHERE id=? AND state='awaiting_approval'", (mid,))
            if cur.rowcount != 1:
                raise BridgeError('not_awaiting_approval')

    def recover_interrupted(self, mid):
        # Never replay an operation with an unknown outcome automatically.
        with self.connect() as db:
            cur = db.execute("UPDATE missions SET state='failed', error='interrupted_unknown_outcome' WHERE id=? AND state='running'", (mid,))
            return bool(cur.rowcount)


def validate_message(stage, value):
    if type(value) is not dict:
        raise BridgeError('invalid_message')
    if stage == 'plan':
        keys = {'type', 'summary', 'task'}
        if set(value) != keys or value['type'] != 'proposal':
            raise BridgeError('invalid_proposal')
        fields = ('summary', 'task')
    elif stage == 'execute':
        if set(value) != {'type', 'summary'} or value['type'] != 'result':
            raise BridgeError('invalid_result')
        fields = ('summary',)
    else:
        if set(value) != {'type', 'decision', 'summary'} or value['type'] != 'review' or value['decision'] not in ('accept', 'revise'):
            raise BridgeError('invalid_review')
        fields = ('summary',)
    if any(type(value[f]) is not str or not value[f].strip() for f in fields):
        raise BridgeError('invalid_message')
    return value


class SimulatedArchitect:
    async def plan(self, task, history):
        return {'type': 'proposal', 'summary': 'Prepare a simulated change', 'task': task}

    async def review(self, task, history):
        return {'type': 'review', 'decision': 'accept', 'summary': 'Simulated review passed'}


class SimulatedExecutor:
    async def execute(self, task, history):
        return {'type': 'result', 'summary': 'Simulated implementation; no code executed'}


class LiveAdapterDisabled:
    """Explicit boundary for OpenAI API / Codex CLI, never launches a process or request."""
    def __init__(self, kind, configuration=None):
        if kind not in ('openai', 'codex'):
            raise ValueError('unknown adapter')
        self.kind, self.configuration = kind, configuration or {}

    async def plan(self, task, history):
        raise BridgeError('live_adapter_not_implemented')
    review = plan
    execute = plan


class Orchestrator:
    def __init__(self, store, architect=None, executor=None):
        self.store = store
        self.architect = architect or SimulatedArchitect()
        self.executor = executor or SimulatedExecutor()

    async def run(self, mid):
        while True:
            row = self.store.get(mid)
            if row['state'] != 'ready':
                return row
            limits = Limits(**json.loads(row['limits']))
            remaining = limits.max_seconds - row['elapsed']
            if remaining <= 0 or row['turns'] >= limits.max_turns or row['cost'] + limits.call_cost_units > limits.max_cost_units:
                self._fail(mid, 'limit_exceeded')
                return self.store.get(mid)
            stage = row['stage']
            # Claim and reserve a complete call before invocation, including on failure.
            with self.store.connect() as db:
                cur = db.execute("UPDATE missions SET state='running', turns=turns+1, cost=cost+? WHERE id=? AND state='ready' AND turns=?", (limits.call_cost_units, mid, row['turns']))
                if cur.rowcount != 1:
                    raise BridgeError('mission_busy')
            tick = time.monotonic()
            try:
                history = self.store.messages(mid)
                adapter = self.executor if stage == 'execute' else self.architect
                method = getattr(adapter, stage)
                task = history[-1]['body']['task'] if stage == 'execute' else row['task']
                value = validate_message(stage, await asyncio.wait_for(method(task, history), remaining))
                body = encoded(value)
                size = len(body.encode('utf-8'))
                if size > limits.max_message_bytes or row['bytes'] + size > limits.max_total_bytes:
                    raise BridgeError('output_limit')
                elapsed = time.monotonic() - tick
                if elapsed >= remaining:
                    raise BridgeError('timeout')
                if stage == 'plan':
                    state, next_stage = 'awaiting_approval', 'execute'
                elif stage == 'execute':
                    state, next_stage = 'ready', 'review'
                elif value['decision'] == 'accept':
                    state, next_stage = 'completed', 'done'
                else:
                    state, next_stage = 'ready', 'plan'
                with self.store.connect() as db:
                    db.execute('INSERT INTO messages VALUES(?,?,?,?)', (mid, row['turns'] + 1, 'executor' if stage == 'execute' else 'architect', body))
                    db.execute('UPDATE missions SET state=?,stage=?,bytes=bytes+?,elapsed=elapsed+?,result=? WHERE id=? AND state=\'running\'',
                               (state, next_stage, size, elapsed, body if state == 'completed' else None, mid))
            except asyncio.CancelledError:
                self._fail(mid, 'interrupted_unknown_outcome', time.monotonic() - tick)
                raise
            except (Exception, asyncio.TimeoutError) as exc:
                reason = 'timeout' if isinstance(exc, asyncio.TimeoutError) else str(exc) if isinstance(exc, BridgeError) else 'adapter_error'
                self._fail(mid, reason, time.monotonic() - tick)
                return self.store.get(mid)

    def _fail(self, mid, reason, elapsed=0):
        with self.store.connect() as db:
            db.execute("UPDATE missions SET state='failed',error=?,elapsed=elapsed+? WHERE id=? AND state IN ('ready','running')", (reason, elapsed, mid))
