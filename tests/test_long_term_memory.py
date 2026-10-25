import json
import time
import unittest
from hub.core import HubError
from hub.long_term_memory import action, context, current


class LongTermMemory(unittest.TestCase):
    def setUp(self):
        from test_unified_modules import UnifiedModules
        from hub.projects import Projects
        self.fixture = UnifiedModules();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        self.h = self.fixture.h;self.registry = self.fixture.registry
        self.fixture.module('memory-test', "def execute(ctx,run): return 'ok'")
        self.agent, self.runtime = self.fixture.connect('memory-test')
        from hub.planning import Planning
        self.h.planning = Planning(self.h, self.fixture.f.server.deepseek, self.fixture.f.server.workflows)
        self.project = Projects(self.h).create('user', 'Memory project')
        self.registry.set_manager('user', self.project['id'], self.agent['id'])
        job = self.runtime.submit('user', self.agent['id'], 'remember', True, purpose='discussion', session_scope='hub-project:' + self.project['id'])
        with self.h.tx():
            self.h.db.execute("UPDATE executions SET status='running',started=? WHERE id=?", (time.time(), job['id']))
        self.run = dict(self.h.db.execute('SELECT * FROM executions WHERE id=?', (job['id'],)).fetchone())

    def manager(self, **kwargs):
        return action(self.h, self.agent['id'], run_id=self.run['id'], **kwargs)

    def test_manager_tool_persists_into_new_project_and_frozen_turn(self):
        before = context(self.h, self.run)
        result = self.manager(operation='add', target='user', content='Prefer concise Chinese replies.', expected_revision=0)
        self.assertEqual(result['revision'], 1)
        self.assertEqual(before, context(self.h, self.run))
        from hub.projects import Projects
        new = Projects(self.h).create('user', 'New project')
        self.registry.set_manager('user', new['id'], self.agent['id'])
        another = {**self.run, 'session_scope': 'hub-project:' + new['id']};another.pop('_long_term_memory')
        self.assertIn('Prefer concise Chinese replies.', context(self.h, another))
        self.assertEqual(self.manager()['user'], result['user'])
        from hub.module_tools import definitions
        self.assertEqual([x['function']['name'] for x in definitions(self.runtime, self.run)], ['memory'])

    def test_conflict_never_overwrites_and_limits_never_truncate(self):
        action(self.h, 'user', operation='save', user='user edit', memory='', expected_revision=0)
        with self.assertRaises(HubError):
            self.manager(operation='add', content='stale', expected_revision=0)
        with self.assertRaises(HubError):
            self.manager(operation='add', content='x'*6001, expected_revision=1)
        self.assertEqual(current(self.h)['revision'], 1)
        self.assertEqual(current(self.h)['user'], 'user edit')

    def test_lock_blocks_manager_but_user_can_edit_and_rollback_keeps_lock(self):
        self.manager(operation='add', content='old', expected_revision=0)
        action(self.h, 'user', operation='lock', locked=True, expected_revision=1)
        with self.assertRaises(HubError):
            self.manager(operation='add', content='blocked', expected_revision=2)
        with self.assertRaises(HubError):
            self.manager(operation='lock', locked=False, expected_revision=2)
        action(self.h, 'user', operation='save', user='new', memory='new', expected_revision=2)
        state = action(self.h, 'user', operation='rollback', revision=1, expected_revision=3)
        self.assertEqual(state['memory'], 'old');self.assertTrue(state['locked'])
        self.assertEqual(state['revision'], 4)
        self.assertEqual(action(self.h, 'user', operation='version', revision=3)['memory'], 'new')

    def test_patch_requires_unique_exact_match(self):
        self.manager(operation='add', content='one one', expected_revision=0)
        with self.assertRaises(HubError):
            self.manager(operation='patch', old_text='one', content='two', expected_revision=1)
        self.manager(operation='patch', old_text='one one', content='two', expected_revision=1)
        state = self.manager(operation='remove', old_text='two', expected_revision=2)
        self.assertEqual(state['memory'], '')

    def test_stopped_or_replaced_manager_cannot_write(self):
        with self.h.tx():self.h.db.execute("UPDATE executions SET stop_requested=1 WHERE id=?", (self.run['id'],))
        with self.assertRaises(HubError):self.manager()
        with self.h.tx():
            self.h.db.execute("UPDATE executions SET stop_requested=0 WHERE id=?", (self.run['id'],))
            self.h.db.execute('UPDATE settings SET value=? WHERE key=?', ('not-this-manager', 'project_manager:' + self.project['id']))
            self.h.db.execute('UPDATE agents SET enabled=0 WHERE id=?', (self.agent['id'],))
        with self.assertRaises(HubError):self.manager(operation='add', content='not allowed', expected_revision=0)

    def test_persisted_versions_survive_reopen(self):
        self.manager(operation='add', content='durable note', expected_revision=0)
        from hub.core import Hub
        reopened = Hub(self.h.directory, recover=False)
        try:self.assertEqual(current(reopened)['memory'], 'durable note')
        finally:reopened.db.close()

    def test_history_pagination(self):
        for i in range(52):action(self.h, 'user', operation='lock', locked=bool(i % 2), expected_revision=i)
        page = action(self.h, 'user', operation='history')
        self.assertEqual(page['total'], 53);self.assertEqual(len(page['versions']), 50)
        self.assertEqual(len(action(self.h, 'user', operation='history', offset=50)['versions']), 3)

    def test_first_save_can_be_rolled_back_to_empty(self):
        self.manager(operation='add', content='undo me', expected_revision=0)
        result=action(self.h, 'user', operation='rollback', revision=0, expected_revision=1)
        self.assertEqual(result['memory'], '');self.assertEqual(result['revision'], 2)

    def test_shared_tool_dispatch_and_non_manager_denial(self):
        from hub.module_tools import tool
        result=tool(self.runtime,self.run,'memory',{'operation':'add','content':'via tool','expected_revision':0},{'memory'})
        self.assertEqual(result['memory'],'via tool')
        with self.assertRaises(HubError):action(self.h,'deepseek-9',operation='read',run_id=self.run['id'])
        with self.assertRaises(HubError):self.manager(operation='history')
