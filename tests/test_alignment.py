import unittest
from unittest.mock import patch
from types import SimpleNamespace
import test_nine_deepseek as fixtures
from hub import execution_policy, module_tools
from hub.core import HubError

class Alignment(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.NineDeepSeek();self.fixture.setUp()
        self.p=self.fixture.p;self.h=self.fixture.h
    def tearDown(self):self.fixture.tearDown()
    def run_row(self,s):
        return dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(s['pending'],)).fetchone())
    def finish(self,s,result):
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='completed',result=? WHERE id=?",(result,s['pending']))
        self.p.patrol();return self.p.get(s['id'])
    def test_alignment_raw_prompt_and_no_automatic_plan(self):
        s=self.p.message('user','hello',{'agents':[]})
        r=self.run_row(s)
        self.assertEqual(r['purpose'],'alignment');self.assertEqual(r['prompt'],'hello')
        s=self.finish(s,'{"done":false,"report":"hello","tasks":[]}')
        self.assertEqual(s['state'],'chatting');self.assertIsNone(s['plan'])
        self.assertEqual(s['history'][-1]['text'],'{"done":false,"report":"hello","tasks":[]}')
        s=self.p.message('user','按计划执行',session_id=s['id'])
        self.assertEqual(self.run_row(s)['purpose'],'alignment')
    def test_explicit_start_preserves_session_scope_and_history(self):
        s=self.p.message('user','hello',{'agents':[]});r=self.run_row(s)
        s=self.finish(s,'What would you like?')
        planned=self.p.message('user','make a plan',session_id=s['id'],start_planning=True)
        new=self.run_row(planned)
        self.assertEqual(planned['id'],s['id']);self.assertEqual(new['session_scope'],r['session_scope'])
        self.assertEqual(new['purpose'],'discussion');self.assertIn('只输出 JSON',new['prompt'])
        self.assertEqual(len(planned['history']),3)
    def test_direct_planning_and_empty_policy(self):
        s=self.p.message('user','make a plan',{'agents':[]},start_planning=True)
        self.assertEqual(self.run_row(s)['purpose'],'discussion')
        run={'purpose':'alignment'}
        host=SimpleNamespace(hub=self.h)
        with patch('hub.long_term_memory.user_context',return_value='user preferences'):
            self.assertEqual(execution_policy.execution_instructions(host,run),'user preferences')
            self.assertEqual(execution_policy.tool_agent_instructions(host,run,None,False,False),'user preferences')
            self.assertEqual(execution_policy.api_instructions(host,run,None,False),'user preferences')
        self.assertEqual(execution_policy.report_instructions(host,run),'')
    def test_platform_tool_is_rejected_even_if_visible(self):
        class Runtime:
            def guard(self,run):pass
        with self.assertRaisesRegex(HubError,'开始计划'):
            module_tools.tool(Runtime(),{'purpose':'alignment'},'project_assign',{},['project_assign'])

    def test_alignment_memory_contains_user_only(self):
        from hub.long_term_memory import user_context
        with patch('hub.long_term_memory.is_manager',return_value=True), patch('hub.long_term_memory.current',return_value={'user':'prefer small buttons','memory':'private experience','revision':7,'locked':False}):
            result=user_context(self.h,{'purpose':'alignment'})
        self.assertIn('prefer small buttons',result)
        self.assertNotIn('private experience',result)
        self.assertNotIn('revision',result)
    def test_vm_works_before_any_workflow_and_is_bound_to_project(self):
        from hub.projects import Projects
        from hub.automation import Automation
        projects=Projects(self.h);project=projects.create('user','alignment VM')
        s=self.p.message('user','hello',{'agents':[]},project_id=project['id'])
        run=self.fixture.running(s['pending'])
        host=SimpleNamespace(hub=self.h,projects=projects,workflows=self.fixture.w)
        automation=Automation(host)
        with patch('hub.vm_bridge.VmBridge.call',return_value={'connected':True}) as call:
            self.assertTrue(automation.project_vm(run['agent'],run['id'],action='status')['connected'])
            self.assertEqual(call.call_args.args,(project['id'],run['agent'],project['cwd']))
        with patch('hub.vm_bridge.VmBridge.call') as call:
            with self.assertRaises(HubError):automation.project_vm('user',run['id'],action='status')
            call.assert_not_called()

    def test_new_planning_round_has_its_own_approval_and_workflow(self):
        old=self.p.message('user','first plan',{'agents':[]},start_planning=True)
        old=self.finish(old,'{"done":false,"report":"first","tasks":[]}')
        old.update(state='executing',workflow_id='previous-completed-workflow',design_approved={'version':1})
        self.p.save(old)
        new=self.p.message('user','new plan',{'agents':[]},start_planning=True)
        self.assertNotEqual(new['id'],old['id'])
        self.assertIsNone(new['workflow_id']);self.assertNotIn('design_approved',new)
        self.assertEqual(self.run_row(new)['purpose'],'discussion')
        self.assertEqual(new['mode'],'planning')
        self.assertEqual(self.p.get(old['id'])['workflow_id'],'previous-completed-workflow')

    def planned_project(self,project,body):
        import json
        s=self.p.message('user',body,{'agents':[],'preview_mode':'skip'},project_id=project['id'],start_planning=True)
        return self.finish(s,json.dumps({'done':False,'report':body,'tasks':[{'agent':s['manager'],'instruction':'implement and verify'}]}))
    def test_approval_stops_old_run_and_starts_another_round(self):
        from hub.projects import Projects
        projects=Projects(self.h);project=projects.create('user','rounds')
        old=self.planned_project(project,'first plan')
        old=self.p.approve(old,old['revision'],None)
        old_workflow=old['workflow_id']
        step=self.fixture.w.steps(old_workflow)[0]
        job=self.fixture.d.submit('user',step['agent'],self.h.db.execute('SELECT title FROM tasks WHERE id=?',(step['task'],)).fetchone()[0],True,task_id=step['task'],session_scope='project:'+old_workflow)
        old_run=job['id']
        self.fixture.running(old_run)
        new=self.planned_project(project,'second plan')
        self.assertEqual(next(w for w in self.fixture.w.snapshot('user') if w['id']==old_workflow)['status'],'active')
        self.assertEqual(self.h.db.execute('SELECT stop_requested FROM executions WHERE id=?',(old_run,)).fetchone()[0],0)
        approved=self.p.approve(new,new['revision'],None)
        self.assertNotEqual(approved['workflow_id'],old_workflow)
        previous=next(w for w in self.fixture.w.snapshot('user') if w['id']==old_workflow)
        self.assertEqual(previous['status'],'stopped');self.assertEqual(previous['superseded_by'],new['id'])
        self.assertTrue(self.h.db.execute('SELECT stop_requested FROM executions WHERE id=?',(old_run,)).fetchone()[0])
        self.assertEqual(self.p.get(old['id'])['state'],'archived')
        with self.assertRaisesRegex(HubError,'替代'):self.fixture.w.resume('user',old_workflow)
        with self.assertRaisesRegex(HubError,'替代'):self.p.approve(self.p.get(old['id']),old['revision'],None)
    def test_stale_approval_does_not_stop_old_work(self):
        from hub.projects import Projects
        project=Projects(self.h).create('user','stale approval')
        old=self.planned_project(project,'first');old=self.p.approve(old,old['revision'],None)
        new=self.planned_project(project,'second')
        with self.assertRaises(HubError):self.p.approve(new,new['revision']-1,None)
        previous=next(w for w in self.fixture.w.snapshot('user') if w['id']==old['workflow_id'])
        self.assertEqual(previous['status'],'active')

    def test_new_approval_supersedes_demo_under_construction(self):
        from hub.projects import Projects
        from hub.designs import Designs
        project=Projects(self.h).create('user','demo rounds')
        designs=Designs(self.h,self.p,self.fixture.w)
        old=self.planned_project(project,'first demo')
        old['options']['preview_mode']='demo';self.p.save(old)
        old=self.p.approve(old,old['revision'],None)
        design=designs.get(old['design_id'])
        self.assertEqual(design['state'],'building')
        new=self.planned_project(project,'new production plan')
        approved=self.p.approve(new,new['revision'],None)
        self.assertEqual(approved['state'],'executing')
        self.assertEqual(designs.get(design['id'])['state'],'superseded')
        previous=next(w for w in self.fixture.w.snapshot('user') if w['id']==design['workflow_id'])
        self.assertEqual(previous['status'],'stopped')
