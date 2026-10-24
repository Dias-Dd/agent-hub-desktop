import json,tempfile,unittest,time
from hub.core import Hub,HubError
from hub.projects import Projects
from hub.planning import Planning
from hub.codex_runtime import CodexRuntime
from hub.antigravity import AntigravityRuntime
from hub.workflows import Workflows
from hub.coordination import Coordination
import test_sessions_inbox as support
from test_codex_runtime import FakeAppServer

class ProjectQueueRoleTests(unittest.TestCase):
    setUp=support.InboxTests.setUp
    tearDown=support.InboxTests.tearDown
    start=support.InboxTests.start
    tick=support.InboxTests.tick
    finish=support.InboxTests.finish
    waiting=support.InboxTests.waiting
    def manager(self):
        w=self.start();steps=self.w.steps(w['id']);self.finish(steps[0]);self.tick(2)
        manager=self.w.steps(w['id'])[-1];self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(manager['run_id'],));return w,manager
    def test_busy_assignment_queues_with_dependency_and_can_cancel_without_losing_sequence(self):
        w,m=self.manager();prior=self.w.steps(w['id'])[1]
        q=self.w.project_assign('argon',m['run_id'],'sol-2','after prior success','queued')
        self.assertEqual(q['after_task'],prior['task']);self.tick()
        step=next(s for s in self.w.steps(w['id']) if s['task']==q['task_id'])
        self.assertEqual(step['depends_on'],prior['task'])
        blocked=self.h.db.execute("SELECT 1 FROM workflow_dependencies d LEFT JOIN executions e ON e.task_id=d.depends_on WHERE d.task=? AND e.status!='completed'",(q['task_id'],)).fetchone();self.assertTrue(blocked)
        self.w.project_cancel_task('argon',m['run_id'],q['task_id'],'not needed')
        self.assertEqual(next(s for s in self.w.steps(w['id']) if s['task']==q['task_id'])['status'],'cancelled')
        fresh=self.w.project_assign('argon',m['run_id'],'sol-1','new safe work','new')
        self.assertTrue(fresh['task_id']);self.assertEqual(len({s['seq'] for s in self.w.steps(w['id'])}),len(self.w.steps(w['id'])))
    def test_roles_are_dynamic_and_only_manager_can_change_them(self):
        w,m=self.manager();result=self.w.project_set_role('argon',m['run_id'],'flash-3','implementation engineer')
        self.assertEqual(result['role'],'implementation engineer')
        result=self.w.project_set_role('argon',m['run_id'],'sol-1','independent reviewer',True)
        self.assertEqual(result['reviewer'],'sol-1')
        states=self.w.project_status('argon',m['run_id'])['agents'];self.assertTrue(any(a['agent']=='sol-1' and a['role']=='independent reviewer' for a in states))
        peer=self.w.steps(w['id'])[1];self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(peer['run_id'],))
        with self.assertRaises(HubError):self.w.project_set_role('sol-2',peer['run_id'],'sol-1','leader')
    def test_mailbox_preserves_senders_and_worker_sees_only_own_conversations(self):
        w,m=self.manager();peer=self.w.steps(w['id'])[1];self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(peer['run_id'],))
        self.co.send('sol-2','argon','question from sol2','queue','question-id');self.co.send('argon','flash-3','manager private detail','queue','private')
        all_mail=self.w.project_mailbox('argon',m['run_id'])['messages'];self.assertTrue(any(x['from']=='sol-2' and x['body']=='question from sol2' for x in all_mail))
        own=self.w.project_mailbox('sol-2',peer['run_id'])['messages'];self.assertFalse(any(x['body']=='manager private detail' for x in own))
    def test_peer_question_is_readonly_and_cannot_form_third_party_work_chain(self):
        w=self.start();s=self.w.steps(w['id'])[0];self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(s['run_id'],))
        mid=self.co.send('sol-1','sol-2','explain your current interface','queue','q')[0];self.tick()
        run=dict(self.h.db.execute('SELECT * FROM executions WHERE message_id=?',(mid,)).fetchone());self.assertEqual(run['purpose'],'question')
        self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(run['id'],))
        self.c.factory=FakeAppServer;FakeAppServer.instances=[];self.c.execute(run)
        calls=dict(FakeAppServer.instances[-1].calls);self.assertEqual(calls['thread/start']['sandbox'],'read-only');self.assertEqual(calls['turn/start']['sandboxPolicy'],{'type':'readOnly'})
        self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(run['id'],))
        blocked=self.co.send('sol-2','flash-3','start unrelated work','queue','third')[0]
        self.assertEqual(self.h.db.execute('SELECT status FROM wakeups WHERE message=?',(blocked,)).fetchone()[0],'held')

class ProjectGroupingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.h=Hub(self.tmp.name);self.c=CodexRuntime(self.h);self.a=AntigravityRuntime(self.h)
        for rt in (self.c,self.a):rt.configure('user',self.tmp.name,'full',100,60,True,True)
        self.w=Workflows(self.h,[self.c,self.a]);self.co=Coordination(self.h,[self.c,self.a],self.w);self.p=Planning(self.h,self.a,self.w);self.projects=Projects(self.h)
    def tearDown(self):self.h.db.close();self.tmp.cleanup()
    def state(self,ident):
        state=self.h.snapshot('user');state.update(workflows=self.w.snapshot('user'),planning=self.p.snapshot('user'),coordination=self.co.snapshot('user'),codex=self.c.snapshot('user'),antigravity=self.a.snapshot('user'))
        return self.projects.state(state,ident)
    def test_create_does_not_start_models_and_project_histories_are_separate(self):
        one=self.projects.create('user','One');two=self.projects.create('user','Two')
        self.assertNotEqual(one['cwd'],two['cwd']);self.assertEqual(self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0],0)
        self.co.send('user','argon','first project only',project_id=one['id']);self.co.send('user','argon','second project only',project_id=two['id'])
        first=self.state(one['id']);second=self.state(two['id'])
        self.assertEqual([x['body'] for x in first['messages']],['first project only']);self.assertEqual([x['body'] for x in second['messages']],['second project only'])
        self.assertEqual(first['project']['progress'],0)
    def test_workflows_and_tasks_are_tagged_and_other_project_chat_cannot_wake_them(self):
        one=self.projects.create('user','One');two=self.projects.create('user','Two')
        p={'done':False,'report':'approved','tasks':[{'agent':'sol-1','instruction':'work one'}]}
        w=self.w.start('user','only project one',['sol-1'],max_calls=10,confirmed=True,approved_proposal=p,project_id=one['id']);self.projects.tag()
        self.co.send('user','argon','belongs to project two',project_id=two['id'])
        self.assertEqual(len(self.state(one['id'])['tasks']),1);self.assertEqual(len(self.state(two['id'])['tasks']),0)
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM workflow_events').fetchone()[0],0)
        self.assertEqual(len(self.state(one['id'])['workflows']),1);self.assertEqual(len(self.state(two['id'])['workflows']),0)

if __name__=='__main__':unittest.main()
