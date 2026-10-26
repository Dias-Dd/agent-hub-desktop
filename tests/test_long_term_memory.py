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

    def test_save_receipts_are_metadata_only_project_scoped_and_success_only(self):
        from hub.long_term_memory import updates
        self.assertEqual(updates(self.h,self.project['id']),[])
        saved=self.manager(operation='add',target='user',content='Private preference text',expected_revision=0)
        items=updates(self.h,self.project['id'])
        self.assertEqual(len(items),1);self.assertEqual(items[0]['revision'],saved['revision'])
        self.assertEqual(set(items[0]),{'revision','actor','reason','created'})
        self.assertNotIn('Private preference text',json.dumps(items))
        self.assertEqual(updates(self.h,'another-project'),[]);self.assertEqual(updates(self.h,None),[])
        with self.assertRaisesRegex(HubError,'超过容量'):
            self.manager(operation='add',content='x'*6001,expected_revision=1)
        self.assertEqual(updates(self.h,self.project['id']),items)

    def test_completed_project_followup_still_exposes_and_executes_memory(self):
        from hub.module_tools import definitions
        from hub.long_term_memory import is_manager
        cfg=self.runtime.config()
        workflow={'id':'completed-memory-project','project_id':self.project['id'],'manager':self.agent['id'],'status':'completed','grants':{self.runtime.provider:cfg['grant_id']}}
        with self.h.tx():
            self.h.db.execute('INSERT INTO workflows VALUES(?,?)',(workflow['id'],json.dumps(workflow)))
            self.h.db.execute("UPDATE executions SET purpose='task',session_scope=? WHERE id=?",('project:'+workflow['id'],self.run['id']))
            self.h.db.execute("UPDATE messages SET sender='user',body='Can you save a long-term preference?' WHERE id=?",(self.run['message_id'],))
        run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(self.run['id'],)).fetchone())
        self.assertTrue(is_manager(self.h,run))
        self.assertIn('memory',[x['function']['name'] for x in definitions(self.runtime,run)])
        state=self.manager(operation='read')
        saved=self.manager(operation='add',target='user',content='Use concise explanations across projects.',expected_revision=state['revision'])
        self.assertIn('concise explanations',saved['user'])
        with self.h.tx():
            self.h.db.execute('UPDATE settings SET value=? WHERE key=?',('replacement-manager','project_manager:'+self.project['id']))
            self.h.db.execute('UPDATE agents SET enabled=0 WHERE id=?',(self.agent['id'],))
        self.assertFalse(is_manager(self.h,run))
        with self.assertRaises(HubError):self.manager(operation='read')

    def test_unknown_followup_scope_and_members_do_not_gain_memory(self):
        from hub.long_term_memory import is_manager
        self.assertFalse(is_manager(self.h,{**self.run,'session_scope':'project:missing'}))
        self.assertFalse(is_manager(self.h,{**self.run,'session_scope':'chat:missing'}))
        self.assertTrue(is_manager(self.h,{**self.run,'session_scope':'chat:'+self.project['id']}))
        self.assertFalse(is_manager(self.h,{**self.run,'agent':'other-member'}))

    def test_followup_reply_and_legacy_receipt_keep_source_project(self):
        from hub.projects import Projects
        with self.h.tx():
            self.h.db.execute('UPDATE messages SET project_id=? WHERE id=?',(self.project['id'],self.run['message_id']))
        self.runtime.deliver_result(self.run,'completed','Normal manager reply after saving memory')
        key='execution:'+self.run['id']+':user'
        receipt=self.h.db.execute('SELECT * FROM messages WHERE sender=? AND request_key=?',(self.agent['id'],key)).fetchone()
        self.assertEqual(receipt['project_id'],self.project['id'])
        self.assertIn('Normal manager reply',receipt['body'])
        unrelated=self.h.send('unrelated-agent','user','Unrelated receipt',request_key=key)[0]
        with self.h.tx():
            self.h.db.execute('UPDATE messages SET project_id=NULL WHERE id=?',(receipt['id'],))
            self.h.db.execute('UPDATE tasks SET project_id=NULL WHERE id=?',(self.run['task_id'],))
        self.h.projects.tag()
        self.assertEqual(self.h.db.execute('SELECT project_id FROM messages WHERE id=?',(receipt['id'],)).fetchone()[0],self.project['id'])
        self.assertEqual(self.h.db.execute('SELECT project_id FROM tasks WHERE id=?',(self.run['task_id'],)).fetchone()[0],self.project['id'])
        self.assertIsNone(self.h.db.execute('SELECT project_id FROM messages WHERE id=?',(unrelated,)).fetchone()[0])
