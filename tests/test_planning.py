import json,tempfile,unittest
from hub.core import Hub,HubError
from hub.codex_runtime import CodexRuntime
from hub.antigravity import AntigravityRuntime
from hub.workflows import Workflows
from hub.planning import Planning
class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.h=Hub(self.tmp.name);self.c=CodexRuntime(self.h);self.a=AntigravityRuntime(self.h)
        for rt in (self.c,self.a):rt.configure('user',self.tmp.name,'full',100,600,True,True)
        self.w=Workflows(self.h,[self.c,self.a]);self.p=Planning(self.h,self.a,self.w)
        self.opts={'cwd':self.tmp.name,'agents':['sol-2'],'max_calls':10,'expires_minutes':10080,'max_parallel':3,'max_seconds':7200,'reviewer':'argon','auto_wake':True,'delegate_stop':False,'max_hops':4,'max_messages':12}
    def tearDown(self):self.h.db.close();self.tmp.cleanup()
    def start(self):return self.p.message('user','build a project',self.opts,confirmed=True)
    def answer(self,s,report='human readable plan',tasks=None):
        value={'done':False,'report':report,'tasks':tasks if tasks is not None else [{'agent':'sol-2','instruction':'approved exact task'}]}
        self.h.db.execute("UPDATE executions SET status='completed',result=? WHERE id=?",(json.dumps(value),s['pending']));self.p.patrol();return self.p.get(s['id'])
    def test_new_discussion_and_workflow_share_visible_project_memory(self):
        first=self.p.message('user','记住当前项目的信息',self.opts,confirmed=True,project_id='same-project')
        run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(first['pending'],)).fetchone())
        self.a.sessions.bind(run,'remembered-argon-conversation')
        first=self.answer(first)
        second=self.p.message('user','开启新一轮讨论',self.opts,confirmed=True,project_id='same-project')
        second_run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(second['pending'],)).fetchone())
        self.assertNotEqual(first['id'],second['id'])
        self.assertEqual(self.a.sessions.get(second_run)['session_id'],'remembered-argon-conversation')
        self.assertEqual(self.a.sessions.key(run),self.a.sessions.key(second_run))
        other=self.p.message('user','另一个项目',self.opts,confirmed=True,project_id='other-project')
        other_run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(other['pending'],)).fetchone())
        self.assertIsNone(self.a.sessions.get(other_run))
        workflow=self.w.start('user','执行同一项目',['sol-2'],max_calls=10,confirmed=True,project_id='same-project',approved_proposal={'done':False,'report':'approved','tasks':[{'agent':'sol-2','instruction':'own task'}]})
        cfg=self.a.config()
        manager={**run,'id':'manager-run','task_id':'manager-task','purpose':'task','session_scope':'project:'+workflow['id'],**{k:cfg[k] for k in ('grant_id','cwd','permission')}}
        self.assertEqual(self.a.sessions.get(manager)['session_id'],'remembered-argon-conversation')
        self.assertEqual(self.a.sessions.key(manager),self.a.sessions.key(run))

    def test_legacy_workflow_session_is_adopted_by_new_discussion(self):
        workflow=self.w.start('user','existing project',['sol-2'],max_calls=10,confirmed=True,project_id='existing-project',approved_proposal={'done':False,'report':'approved','tasks':[{'agent':'sol-2','instruction':'own task'}]})
        with self.h.tx():self.h.db.execute('INSERT INTO agent_sessions VALUES(?,?,?,?,?,?,?)',('old-format-key','project:'+workflow['id'],'antigravity','argon','legacy-context','completed',10))
        discussion=self.p.message('user','继续此前内容',self.opts,confirmed=True,project_id='existing-project')
        run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(discussion['pending'],)).fetchone())
        self.assertEqual(self.a.sessions.get(run)['session_id'],'legacy-context')

    def test_new_discussion_actually_resumes_provider_memory_without_reinjecting_history(self):
        from test_antigravity import FakeStream,FakeProbe
        memory={};seen=[]
        class Memory(FakeStream):
            def __init__(self,run,instructions):
                super().__init__(run,instructions)
                prior=run.get('_conversation');seen.append(prior)
                ident=prior or 'context-'+str(len(memory))
                history=memory.setdefault(ident,[]);history.append(run['prompt'])
                answer={'done':False,'report':'REMEMBERED' if any('PROJECT_MEMORY_MARKER' in h for h in history) else 'OTHER_PROJECT','tasks':[]}
                self.events=[{'event':'init','conversation_id':ident,'init':{'model':run['model'],'cwd':run['cwd'],'permission_mode':'request-review'}},{'event':'result','result':{'status':'SUCCESS','response':json.dumps(answer)}}]
        self.a.stream_factory=Memory;self.a.probe=FakeProbe()
        first=self.p.message('user','PROJECT_MEMORY_MARKER',self.opts,confirmed=True,project_id='one')
        def execute(session):
            run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(session['pending'],)).fetchone())
            self.a.execute(run);self.p.patrol();return self.p.get(session['id'])
        execute(first)
        second=self.p.message('user','新一轮：此前说过什么',self.opts,confirmed=True,project_id='one')
        raw=self.h.db.execute('SELECT prompt FROM executions WHERE id=?',(second['pending'],)).fetchone()[0]
        self.assertNotIn('PROJECT_MEMORY_MARKER',raw)
        second=execute(second);self.assertEqual(second['history'][-1]['text'],'REMEMBERED')
        from hub.manager_input import POLICY
        second_run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(second['last_run'],)).fetchone())
        self.a.sessions.remember_policy(second_run,POLICY)
        self.assertTrue(self.a.sessions.policy_needed({**second_run,'id':'manager-mode-probe','purpose':'task'},POLICY))
        third=execute(self.p.message('user','另一个项目',self.opts,confirmed=True,project_id='two'))
        self.assertEqual(third['history'][-1]['text'],'OTHER_PROJECT')
        self.assertEqual(seen,[None,'context-0',None])

    def test_twenty_thousand_character_requirement_can_be_approved(self):
        requirement='需求'*10000
        s=self.p.message('user',requirement,self.opts,confirmed=True)
        prompt=self.h.db.execute('SELECT prompt FROM executions WHERE id=?',(s['pending'],)).fetchone()[0]
        self.assertIn(requirement,prompt);self.assertGreater(len(prompt),20000)
        s=self.answer(s,report='计划'*2500)
        self.p.message('user','按计划执行',self.opts,s['id'],s['revision'])
        self.assertGreater(len(self.w.snapshot('user')[0]['requirement']),20000)

    def test_long_followup_and_escaped_input_fit_without_truncation(self):
        s=self.answer(self.start())
        body='"\\'*10000
        s=self.p.message('user',body,self.opts,s['id'])
        self.assertEqual(s['history'][-1]['text'],body)
        self.assertEqual(len(body),20000)
        with self.assertRaises(HubError):self.p.message('user','长'*20001,self.opts,confirmed=True)

    def test_long_plan_report_can_be_approved_with_long_requirement(self):
        s=self.p.message('user','需求'*10000,self.opts,confirmed=True)
        s=self.answer(s,report='计划'*10000)
        self.assertEqual(s['state'],'awaiting_approval')
        self.p.message('user','按计划执行',self.opts,s['id'],s['revision'])
        self.assertGreater(len(self.w.snapshot('user')[0]['requirement']),40000)

    def test_recover_old_report_length_error_without_new_model_call(self):
        s=self.start();raw=json.dumps({'done':False,'report':'方案'*3000,'tasks':[{'agent':'sol-2','instruction':'approved exact task'}]})
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='completed',result=? WHERE id=?",(raw,s['pending']))
        s.update(last_run=s['pending'],pending=None,state='error',error='nonempty text required, max 5000');self.p.save(s)
        before=self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0]
        recovered=self.p.recover_result('user',s['id'])
        self.assertEqual(recovered['state'],'awaiting_approval');self.assertEqual(recovered['revision'],s['revision'])
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0],before)
        self.assertFalse(self.w.snapshot('user'))
        with self.assertRaises(HubError):self.p.recover_result('user',s['id'])

    def test_too_long_report_has_specific_error(self):
        s=self.answer(self.start(),report='长'*20001)
        self.assertEqual(s['state'],'error');self.assertIn('20001',s['error']);self.assertIn('20000',s['error'])

    def test_discussion_never_dispatches_and_model_confirmation_is_not_authority(self):
        s=self.start();s=self.answer(s,'按计划执行')
        self.assertEqual(s['state'],'awaiting_approval');self.assertFalse(self.w.snapshot('user'))
        self.w.patrol();self.assertFalse(self.h.db.execute('SELECT 1 FROM workflow_steps').fetchone())
        run=self.h.db.execute('SELECT * FROM executions').fetchone();self.assertEqual(run['purpose'],'discussion');self.assertEqual(run['agent'],'argon')
    def test_only_explicit_human_confirmation_executes_exact_reviewed_tasks_once(self):
        s=self.answer(self.start());approved=self.p.message('user','按计划执行',self.opts,s['id'],s['revision'])
        w=self.w.snapshot('user')[0];steps=w['steps'];self.assertEqual(len(steps),1);self.assertEqual(steps[0]['kind'],'work')
        task=self.h.db.execute('SELECT title FROM tasks WHERE id=?',(steps[0]['task'],)).fetchone()[0];self.assertEqual(task,'approved exact task')
        self.p.message('user','按计划执行',self.opts,s['id'],s['revision']);self.assertEqual(len(self.w.snapshot('user')),1)
        self.assertEqual(approved['workflow_id'],w['id'])
    def test_revisions_and_settings_invalidate_confirmation(self):
        s=self.answer(self.start());old=s['revision'];s=self.p.message('user','change scope',self.opts,s['id'])
        with self.assertRaises(HubError):self.p.message('user','按计划执行',self.opts,s['id'],old)
        s=self.answer(s)
        with self.assertRaises(HubError):self.p.message('user','按计划执行',self.opts,s['id'],old)
        changed={**self.opts,'max_parallel':4}
        with self.assertRaises(HubError):self.p.message('user','按计划执行',changed,s['id'],s['revision'])
        self.assertFalse(self.w.snapshot('user'))
    def test_long_task_descriptions_remain_reviewable_and_exact_at_execution(self):
        long_text='detailed task '*110
        s=self.answer(self.start(),tasks=[{'agent':'sol-2','instruction':long_text}]);self.assertEqual(s['state'],'awaiting_approval')
        self.p.message('user','按计划执行',self.opts,s['id'],s['revision']);step=self.w.snapshot('user')[0]['steps'][0]
        self.assertEqual(self.h.db.execute('SELECT title FROM tasks WHERE id=?',(step['task'],)).fetchone()[0],long_text)
    def test_oversized_or_empty_task_has_specific_readable_error(self):
        s=self.answer(self.start(),tasks=[{'agent':'sol-2','instruction':'a'*6001}]);self.assertEqual(s['state'],'error');self.assertIn('6001',s['error']);self.assertIn('6000',s['error'])
        s=self.p.message('user','revise',self.opts,s['id']);s=self.answer(s,tasks=[{'agent':'sol-2','instruction':''}]);self.assertIn('不能为空',s['error']);self.assertFalse(self.w.snapshot('user'))
    def test_permission_changes_require_a_revised_plan(self):
        s=self.answer(self.start());self.c.configure('user',self.tmp.name,'workspace',100,600,True,True)
        with self.assertRaises(HubError):self.p.message('user','按计划执行',self.opts,s['id'],s['revision'])
        self.assertFalse(self.w.snapshot('user'))
    def test_question_or_invalid_plan_cannot_be_approved(self):
        s=self.answer(self.start(),'Which platform?',[]);self.assertEqual(s['state'],'draft')
        with self.assertRaises(HubError):self.p.message('user','按计划执行',self.opts,s['id'],s['revision'])
        s=self.p.message('user','Windows',self.opts,s['id']);s=self.answer(s,tasks=[{'agent':'astra','instruction':'not allowed'}]);self.assertEqual(s['state'],'error');self.assertFalse(self.w.snapshot('user'))
    def test_restart_preserves_pending_plan_and_uncertain_does_not_execute(self):
        s=self.start();self.p=Planning(self.h,self.a,self.w);self.assertEqual(self.p.get(s['id'])['pending'],s['pending'])
        self.h.db.execute("UPDATE executions SET status='uncertain',result='disconnected' WHERE id=?",(s['pending'],));self.p.patrol();self.assertEqual(self.p.get(s['id'])['state'],'error');self.assertFalse(self.w.snapshot('user'))
    def test_discussion_command_removes_full_permissions_and_uses_plan_mode(self):
        from unittest.mock import patch
        from hub.antigravity import AntigravityStream
        captured=[]
        def spawn(args,**kwargs):captured.extend(args);raise OSError('fixture')
        with patch('hub.antigravity.executable',return_value='official-agy'),patch('hub.antigravity.subprocess.Popen',side_effect=spawn):
            with self.assertRaises(OSError):AntigravityStream({'model':'gemini-4-argon-medium','max_seconds':60,'cwd':self.tmp.name,'purpose':'discussion'},'discussion')
        self.assertEqual(captured[captured.index('--mode')+1],'plan');self.assertIn('--sandbox',captured);self.assertNotIn('--dangerously-skip-permissions',captured)
    def test_actor_confirmation_and_duplicate_inflight_guards(self):
        with self.assertRaises(HubError):self.p.message('user','request',self.opts)
        with self.assertRaises(HubError):self.p.message('argon','按计划执行',self.opts)
        s=self.start()
        with self.assertRaises(HubError):self.p.message('user','another message',self.opts,s['id'])
if __name__=='__main__':unittest.main()
