import json
import unittest
from hub.memory_notices import attach, notify


class PlanNotices(unittest.TestCase):
    def setUp(self):
        from test_manager_owned_plan import ManagerOwnedPlan
        self.fixture=ManagerOwnedPlan();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        self.h=self.fixture.h;self.p=self.fixture.p;self.w=self.fixture.w

    def approve(self, mode='skip'):
        s=self.fixture.plan(mode=mode)
        s=self.p.approve(s,s['revision'],None)
        workflow_id=s.get('workflow_id') or self.h.designs.get(s['design_id'])['workflow_id']
        w=next(w for w in self.w.snapshot('user') if w['id']==workflow_id)
        return s,w

    def test_notification_is_idempotent_platform_message_not_a_new_execution(self):
        s,w=self.approve()
        before=self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0]
        a=notify(self.h,w,'plan','plan:'+s['id']+':'+str(s['revision']))
        b=notify(self.h,w,'plan','plan:'+s['id']+':'+str(s['revision']))
        self.assertEqual(a['id'],b['id'])
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM memory_review_notices').fetchone()[0],1)
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0],before)
        row=self.h.db.execute('SELECT * FROM messages WHERE id=?',(a['id'],)).fetchone()
        self.assertEqual(row['sender'],'平台');self.assertEqual(row['recipient'],self.fixture.manager)
        self.assertIn('仅与本项目有关',row['body']);self.assertIn('没有值得保存的内容就不写',row['body'])

    def test_deliver_once_only_to_manager_and_preserve_original_task(self):
        _,w=self.approve();task=self.w.steps(w['id'])[0]
        run={'id':'notice-test','agent':self.fixture.manager,'task_id':task['task'],'prompt':'Original approved instruction'}
        other={**run,'agent':next(a for a in self.fixture.f.d.models if a!=self.fixture.manager)}
        self.assertEqual(attach(self.h,other),other)
        delivered=attach(self.h,run)
        self.assertTrue(delivered['prompt'].startswith(run['prompt']))
        self.assertIn('[长期记忆通知]',delivered['prompt'])
        self.assertEqual(run['prompt'],'Original approved instruction')
        self.assertEqual(attach(self.h,delivered),delivered)
        self.assertEqual(attach(self.h,{**run,'id':'another-turn'}),{**run,'id':'another-turn'})
        count=self.h.db.execute('SELECT count(*) FROM long_term_memory_versions').fetchone()[0]
        self.assertEqual(count,1) # Notification itself never writes memory.

    def test_real_module_turn_receives_notice_in_actual_input(self):
        _,w=self.approve();task=self.w.steps(w['id'])[0]
        instruction=self.h.db.execute('SELECT title FROM tasks WHERE id=?',(task['task'],)).fetchone()[0]
        job=self.fixture.f.d.submit('user',self.fixture.manager,instruction,True,task['task'])
        import test_harness as harness
        self.h.url='http://127.0.0.1:8765'
        from unittest.mock import patch
        from module_fixture import implementation
        self.fixture.f.d.key=lambda:'fixture-key-not-real'
        cfg=self.fixture.f.d.config();cfg['engine']='harness'
        with self.h.tx():self.h.db.execute("UPDATE settings SET value=? WHERE key='deepseek_runtime'",(json.dumps(cfg),))
        runtime=implementation(self.h,'deepseek-harness')
        harness.FakeACP.calls=[];harness.FakeACP.stop='end_turn';harness.FakeACP.model='["deepseek-official","deepseek-flash"]';harness.FakeACP.missing=False;harness.FakeACP.bad_permission=False;harness.FakeACP.bad_root=False
        with patch.object(runtime,'ACP',harness.FakeACP),patch.object(runtime,'installation',return_value=('fixture.exe','cli.js')),patch.object(__import__(runtime.__package__+'.account',fromlist=['auth']),'auth',return_value=('deepseek-official',None,{'DEEPSEEK_API_KEY':'fixture-key-not-real'})):
            self.fixture.f.d.execute(self.fixture.f.running(job['id']))
        run=self.h.db.execute('SELECT status,actual_input,result FROM executions WHERE id=?',(job['id'],)).fetchone()
        self.assertEqual(run['status'],'completed',run['result'])
        self.assertIn('[长期记忆通知]',run['actual_input'])
        self.assertEqual(run['actual_input'].count('[长期记忆通知]'),1)

    def test_first_approved_demo_plan_also_notifies(self):
        from hub.designs import Designs
        Designs(self.h,self.p,self.w)
        s,w=self.approve(mode='demo')
        row=self.h.db.execute('SELECT workflow,phase FROM memory_review_notices').fetchone()
        self.assertEqual(row['workflow'],w['id']);self.assertEqual(row['phase'],'plan')


class CompletionNotices(unittest.TestCase):
    def setUp(self):
        from test_required_folder_link import RequiredFolder
        self.fixture=RequiredFolder();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        self.h=self.fixture.h;self.w=self.fixture.w

    def test_completion_delivers_in_tool_result_without_reopening_project(self):
        self.fixture.share()
        first=self.w.project_complete('deepseek-4',self.fixture.job['id'],'Ready',['verified'])
        self.assertFalse(first['completed'])
        self.assertEqual(len(first['notifications']),1)
        self.assertEqual(first['notifications'][0]['topic'],'long_term_memory')
        repeated_first=self.w.project_complete('deepseek-4',self.fixture.job['id'],'Ready',['verified'])
        self.assertEqual(repeated_first['notifications'],[])
        before=self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0]
        result=self.fixture.complete()
        self.assertTrue(result['completed']);self.assertNotIn('notifications',result)
        self.assertEqual(self.w.snapshot('user')[0]['status'],'completed')
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0],before)
        repeated=self.fixture.complete()
        self.assertTrue(repeated['deduplicated']);self.assertNotIn('notifications',repeated)
        self.assertEqual(self.h.db.execute("SELECT count(*) FROM memory_review_notices WHERE phase='completed'").fetchone()[0],1)

    def test_completion_notice_can_still_be_followed_by_a_memory_write(self):
        from hub.long_term_memory import action
        self.fixture.share();self.fixture.complete()
        state=action(self.h,'deepseek-4',operation='read',run_id=self.fixture.job['id'])
        saved=action(self.h,'deepseek-4',operation='add',run_id=self.fixture.job['id'],target='user',content='User explicitly prefers concise replies across projects.',expected_revision=state['revision'])
        self.assertIn('concise replies',saved['user'])
        self.assertEqual(self.w.snapshot('user')[0]['status'],'completed')
