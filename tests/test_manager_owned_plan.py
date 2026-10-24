import json
import unittest
import test_nine_deepseek as base
from hub.core import HubError
from hub.manager_identity import resolve


class ManagerOwnedPlan(unittest.TestCase):
    def setUp(self):
        self.f=base.NineDeepSeek();self.f.setUp()
        self.h=self.f.h;self.p=self.f.p;self.w=self.f.w
        self.manager=resolve(self.h)

    def tearDown(self):self.f.tearDown()

    def plan(self,agents=None,tasks=None,mode='skip'):
        opts={'agents':agents or [],'cwd':self.f.t.name,'preview_mode':mode}
        session=self.p.message('user','Build hello page',options=opts,confirmed=True,project_id='solo')
        result={'done':False,'report':'Readable approved scope','tasks':tasks if tasks is not None else [{'agent':self.manager,'instruction':'Build the hello page yourself'}]}
        self.f.api.answers.append(json.dumps(result))
        self.f.d.execute(self.f.running(session['pending']));self.p.patrol()
        return self.p.get(session['id'])

    def test_manager_only_plan_waits_for_approval_then_runs_with_manager_authority(self):
        s=self.plan()
        self.assertEqual(s['state'],'awaiting_approval')
        self.assertEqual(self.w.snapshot('user'),[])
        requests=len(self.f.api.requests)
        s=self.p.approve(s,s['revision'],None)
        self.assertEqual(s['state'],'executing')
        self.assertNotIn('roster_replan',s)
        workflow=next(w for w in self.w.snapshot('user') if w['id']==s['workflow_id'])
        self.assertEqual(workflow['agents'],[])
        self.assertEqual(workflow['approved_plan']['tasks'][0]['agent'],self.manager)
        steps=self.w.steps(workflow['id'])
        self.assertEqual([(x['agent'],x['kind']) for x in steps],[(self.manager,'plan')])
        self.assertEqual(len(self.f.api.requests),requests)
        self.w.advance(workflow)
        run=dict(self.h.db.execute('SELECT * FROM executions WHERE task_id=?',(steps[0]['task'],)).fetchone())
        self.assertEqual(run['purpose'],'task')
        self.assertIn('approved_plan',run['prompt'])
        self.f.running(run['id'])
        self.w.run_context(self.manager,run['id'],manager=True)

    def test_unknown_or_unselected_member_still_rejected_and_report_preserved(self):
        outsider=next(a for a in self.f.d.models if a!=self.manager)
        s=self.plan(tasks=[{'agent':outsider,'instruction':'Not authorized'}])
        self.assertEqual(s['state'],'error')
        self.assertEqual(s['error'],'计划包含未选择的 Agent')
        self.assertEqual(s['history'][-1]['text'],'Readable approved scope')
        self.assertEqual(self.w.snapshot('user'),[])

    def test_recover_existing_completed_response_without_new_model_request(self):
        s=self.plan()
        s.update(state='error',error='计划包含未选择的 Agent',plan=None)
        s['history']=[x for x in s['history'] if x.get('run_id')!=s['last_run']]
        self.p.save(s)
        requests=len(self.f.api.requests)
        executions=self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0]
        recovered=self.p.recover_result('user',s['id'])
        self.assertEqual(recovered['state'],'awaiting_approval')
        self.assertNotIn('error',recovered)
        self.assertEqual(len(self.f.api.requests),requests)
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0],executions)
        self.assertEqual(sum(x.get('run_id')==s['last_run'] for x in recovered['history']),1)
        self.assertEqual(self.w.snapshot('user'),[])

    def test_mixed_manager_and_member_plan_preserves_authorized_roster(self):
        member=next(a for a in self.f.d.models if a!=self.manager)
        tasks=[{'agent':self.manager,'instruction':'Integrate and verify'},{'agent':member,'instruction':'Build page'}]
        s=self.plan([member],tasks)
        self.assertEqual(s['state'],'awaiting_approval')
        s=self.p.approve(s,s['revision'],None)
        workflow=next(w for w in self.w.snapshot('user') if w['id']==s['workflow_id'])
        self.assertEqual(workflow['agents'],[member])
        self.assertEqual(workflow['approved_plan']['tasks'],tasks)
        self.assertEqual(len(self.w.steps(workflow['id'])),1)

    def test_single_manager_can_start_demo_after_explicit_approval(self):
        from hub.designs import Designs
        designs=Designs(self.h,self.p,self.w)
        s=self.plan(mode='demo')
        self.assertEqual(s['state'],'awaiting_approval')
        s=self.p.approve(s,s['revision'],None)
        self.assertEqual(s['state'],'designing')
        review=designs.get(s['design_id'])
        workflow=next(w for w in self.w.snapshot('user') if w['id']==review['workflow_id'])
        self.assertEqual(workflow['agents'],[])
        self.assertEqual(self.w.steps(workflow['id'])[0]['agent'],self.manager)
