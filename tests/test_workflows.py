import json,tempfile,unittest
from hub.core import Hub,HubError
from hub.codex_runtime import CodexRuntime
from hub.antigravity import AntigravityRuntime
from hub.workflows import Workflows,proposal
class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.h=Hub(self.tmp.name);self.c=CodexRuntime(self.h);self.a=AntigravityRuntime(self.h)
        for r in (self.c,self.a):r.configure('user',self.tmp.name,'full',10,60,True,True)
        self.w=Workflows(self.h,[self.c,self.a])
    def tearDown(self):self.h.db.close();self.tmp.cleanup()
    def start(self,**kw):return self.w.start('user','计算2+2并验收',['sol-2'],confirmed=True,**kw)
    def finish(self,s,value,status='completed'):self.h.db.execute('UPDATE executions SET status=?,result=? WHERE id=?',(status,value,s['run_id']))
    def plan(self,agents=['sol-2'],**kw):
        w=self.start(**kw);self.w.patrol();s=self.w.steps(w['id'])[0];self.finish(s,json.dumps({'done':False,'report':'分工并核实','tasks':[{'agent':a,'instruction':'计算2+2并回复结果'} for a in agents]}));self.w.patrol();return w
    def test_closed_loop_and_restart_no_duplicate_dispatch(self):
        w=self.plan();self.w=Workflows(self.h,[self.c,self.a]);self.w.patrol();steps=self.w.steps(w['id']);self.assertEqual(len(steps),2);self.assertEqual(steps[-1]['status'],'queued')
        self.finish(steps[-1],'测试完成：2+2=4');self.w.patrol();self.w.patrol();steps=self.w.steps(w['id']);self.assertEqual(steps[-1]['kind'],'review')
        self.finish(steps[-1],json.dumps({'done':True,'report':'核实通过：2+2=4','tasks':[]}));self.w.patrol();self.w.patrol();self.assertEqual(self.w.snapshot('user')[0]['status'],'completed');self.assertEqual(len(self.w.steps(w['id'])),3);self.assertEqual(self.h.snapshot('user')['project']['progress'],100)
    def test_unauthorized_model_and_invalid_output_block(self):
        w=self.plan(['astra']);self.assertEqual(self.w.snapshot('user')[0]['status'],'blocked');self.assertEqual(len(self.w.steps(w['id'])),1)
        with self.assertRaises(HubError):proposal('pretend completed')
    def test_budget_expiry_stop_and_permission_change(self):
        w=self.plan(['sol-2','sol-2'],max_calls=3);self.assertEqual(self.w.snapshot('user')[0]['status'],'blocked');self.assertEqual(len(self.w.steps(w['id'])),1)
        w=self.start();w['expires']=0;self.w.save(w);self.w.patrol();self.assertEqual(self.w.snapshot('user')[0]['status'],'blocked')
        w=self.start();self.w.patrol();self.w.stop('user',w['id']);self.assertEqual(self.w.steps(w['id'])[0]['status'],'cancelled')
        w=self.start();cfg=self.a.config();cfg['grant_id']='changed';self.h.db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(cfg),self.a.config_key));self.w.patrol();self.assertEqual(self.w.snapshot('user')[0]['status'],'blocked')
    def test_uncertain_never_replayed(self):
        w=self.plan();self.w.patrol();s=self.w.steps(w['id'])[-1];self.finish(s,'lost','uncertain');self.w.patrol();self.assertEqual(self.w.snapshot('user')[0]['status'],'active');steps=self.w.steps(w['id']);self.assertEqual(len(steps),3);self.assertEqual(steps[-1]['kind'],'check');self.assertEqual(steps[1]['status'],'uncertain');self.assertIn('禁止修改文件或重放执行',self.h.db.execute('SELECT title FROM tasks WHERE id=?',(steps[-1]['task'],)).fetchone()[0])
    def test_manager_dispatches_before_slow_worker_finishes(self):
        w=self.w.start('user','parallel work',['sol-1','sol-2'],max_calls=12,confirmed=True,max_parallel=3)
        self.w.patrol();first=self.w.steps(w['id'])[0]
        self.finish(first,json.dumps({'done':False,'report':'start','tasks':[{'agent':a,'instruction':'own separate file'} for a in ['sol-1','sol-2']]}))
        self.w.patrol();self.w.patrol();self.w.patrol()
        steps=self.w.steps(w['id']);self.finish(steps[1],'finished')
        self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(steps[2]['run_id'],))
        self.w.patrol();self.w.patrol();review=self.w.steps(w['id'])[-1]
        self.assertEqual(review['kind'],'review');self.assertEqual(self.w.steps(w['id'])[2]['status'],'running')
        self.finish(review,json.dumps({'done':False,'report':'fill idle slot','tasks':[{'agent':'sol-1','instruction':'independent followup'}]}))
        self.w.patrol();self.w.patrol();steps=self.w.steps(w['id'])
        self.assertEqual(steps[-1]['agent'],'sol-1');self.assertEqual(steps[-1]['status'],'queued')
        self.assertEqual(steps[2]['status'],'running')

    def test_uncertain_manager_gets_recovery_not_worker_replay(self):
        w=self.plan(max_calls=10);self.w.patrol();self.finish(self.w.steps(w['id'])[-1],'done')
        self.w.patrol();self.w.patrol();review=self.w.steps(w['id'])[-1]
        self.finish(review,'CLI cleanup timeout','uncertain');self.w.patrol()
        steps=self.w.steps(w['id']);self.assertEqual(steps[-1]['kind'],'review')
        self.assertEqual(len([s for s in steps if s['kind']=='work']),1)
        self.assertEqual(self.w.snapshot('user')[0]['status'],'active')

    def test_message_reuses_original_and_duplicate_is_rejected(self):
        mid=self.h.send('sol-1','sol-2','计算2+2')[0]
        with self.assertRaises(HubError):self.c.submit('user','sol-2','changed',True,source_message_id=mid)
        self.c.submit('user','sol-2','计算2+2',True,source_message_id=mid);self.assertEqual(self.c.snapshot('user')['runs'][0]['message_id'],mid)
        with self.assertRaises(HubError):self.c.submit('user','sol-2','计算2+2',True,source_message_id=mid)
    def test_completed_execution_sends_deduplicated_receipt_to_original_sender(self):
        mid=self.h.send('sol-1','sol-2','计算2+2')[0]
        r=self.c.submit('user','sol-2','计算2+2',True,source_message_id=mid)
        run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(r['id'],)).fetchone())
        self.c.deliver_result(run,'completed','测试完成：2+2=4');self.c.deliver_result(run,'completed','测试完成：2+2=4')
        receipts=self.h.db.execute("SELECT * FROM messages WHERE sender='sol-2' AND recipient='sol-1'").fetchall()
        self.assertEqual(len(receipts),1);self.assertIn('2+2=4',receipts[0]['body'])
    def test_expired_project_cannot_start_previously_queued_execution(self):
        import time
        called=[]
        self.a.factory=lambda *args:called.append(args)
        w=self.start();self.w.patrol();w['expires']=0;self.w.save(w)
        self.a.start();time.sleep(.35);self.a.close()
        self.assertFalse(called);self.assertEqual(self.w.steps(w['id'])[0]['status'],'cancelled')
    def test_grant_required_and_api_model_cannot_join(self):
        with self.assertRaises(HubError):self.w.start('user','task',['sol-2'])
        with self.assertRaises(HubError):self.w.start('user','task',['deepseek'],confirmed=True)
        self.assertFalse(self.w.snapshot('user'))
if __name__=='__main__':unittest.main()
