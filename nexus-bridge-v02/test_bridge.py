import asyncio
import tempfile
import unittest
from pathlib import Path

from bridge import BridgeError, Limits, LiveAdapterDisabled, Orchestrator, SimulatedArchitect, Store


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'test.sqlite3'
        self.store = Store(self.db)

    async def test_full_simulation_and_resume_after_approval(self):
        mid = self.store.create('Improve documentation', Limits())
        row = await Orchestrator(self.store).run(mid)
        self.assertEqual(row['state'], 'awaiting_approval')
        self.assertEqual(len(self.store.messages(mid)), 1)
        store = Store(self.db)
        store.approve(mid)
        row = await Orchestrator(store).run(mid)
        self.assertEqual(row['state'], 'completed')
        self.assertEqual([m['body']['type'] for m in store.messages(mid)], ['proposal', 'result', 'review'])
        self.assertEqual(row['cost'], 3)

    async def test_unknown_fields_and_direct_command_refused(self):
        class Bad:
            async def plan(self, task, history):
                return {'type': 'proposal', 'summary': 'x', 'task': 'x', 'command': 'rm -rf /'}
        mid = self.store.create('x', Limits())
        self.assertEqual((await Orchestrator(self.store, architect=Bad()).run(mid))['error'], 'invalid_proposal')
        self.assertEqual(self.store.messages(mid), [])

    async def test_review_revision_requires_fresh_approval(self):
        class Reviewer(SimulatedArchitect):
            async def review(self, task, history):
                return {'type': 'review', 'decision': 'revise', 'summary': 'Revise'}
        mid = self.store.create('x', Limits())
        o = Orchestrator(self.store, architect=Reviewer())
        await o.run(mid)
        self.store.approve(mid)
        row = await o.run(mid)
        self.assertEqual(row['state'], 'awaiting_approval')
        self.assertEqual(row['turns'], 4)

    async def test_limits(self):
        mid = self.store.create('x', Limits(max_turns=1))
        await Orchestrator(self.store).run(mid)
        self.store.approve(mid)
        self.assertEqual((await Orchestrator(self.store).run(mid))['error'], 'limit_exceeded')
        mid = self.store.create('x', Limits(max_cost_units=1))
        await Orchestrator(self.store).run(mid)
        self.store.approve(mid)
        self.assertEqual((await Orchestrator(self.store).run(mid))['error'], 'limit_exceeded')
        with self.assertRaises(BridgeError):
            self.store.create('x' * 20, Limits(max_message_bytes=10))
        mid = self.store.create('x', Limits(max_total_bytes=10))
        self.assertEqual((await Orchestrator(self.store).run(mid))['error'], 'output_limit')

    async def test_timeout(self):
        class Slow:
            async def plan(self, task, history):
                await asyncio.sleep(1)
        mid = self.store.create('x', Limits(max_seconds=0.02))
        self.assertEqual((await Orchestrator(self.store, architect=Slow()).run(mid))['error'], 'timeout')

    async def test_cancellation_and_crash_recovery_do_not_replay(self):
        entered = asyncio.Event()
        class Slow:
            async def plan(self, task, history):
                entered.set()
                await asyncio.sleep(10)
        mid = self.store.create('x', Limits())
        task = asyncio.create_task(Orchestrator(self.store, architect=Slow()).run(mid))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.store.get(mid)['error'], 'interrupted_unknown_outcome')
        other = self.store.create('x', Limits())
        with self.store.connect() as db:
            db.execute("UPDATE missions SET state='running' WHERE id=?", (other,))
        self.assertTrue(self.store.recover_interrupted(other))
        self.assertEqual((await Orchestrator(self.store).run(other))['state'], 'failed')

    async def test_live_adapters_fail_closed(self):
        for kind in ('openai', 'codex'):
            with self.assertRaisesRegex(BridgeError, 'live_adapter_not_implemented'):
                await LiveAdapterDisabled(kind, {'enabled': True}).plan('x', [])

    async def test_approval_state_and_unknown_mission(self):
        mid = self.store.create('x', Limits())
        with self.assertRaises(BridgeError):
            self.store.approve(mid)
        with self.assertRaises(BridgeError):
            self.store.get('missing')

    async def test_executor_receives_approved_task(self):
        class Architect(SimulatedArchitect):
            async def plan(self, task, history):
                return {'type': 'proposal', 'summary': 'x', 'task': 'approved task'}
        class Executor:
            async def execute(self, task, history):
                self.task = task
                return {'type': 'result', 'summary': 'x'}
        executor = Executor()
        mid = self.store.create('original', Limits())
        o = Orchestrator(self.store, Architect(), executor)
        await o.run(mid)
        self.store.approve(mid)
        self.assertEqual((await o.run(mid))['state'], 'completed')
        self.assertEqual(executor.task, 'approved task')
