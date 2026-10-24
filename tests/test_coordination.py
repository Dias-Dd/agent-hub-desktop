import json,tempfile,unittest,time
from hub.core import Hub,HubError
from hub.codex_runtime import CodexRuntime
from hub.antigravity import AntigravityRuntime
from hub.workflows import Workflows
from hub.coordination import Coordination
class CoordinationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.h=Hub(self.tmp.name);self.c=CodexRuntime(self.h);self.a=AntigravityRuntime(self.h)
        for r in (self.c,self.a):r.configure('user',self.tmp.name,'full',20,60,True,True)
        self.w=Workflows(self.h,[self.c,self.a]);self.co=Coordination(self.h,[self.c,self.a],self.w)
    def tearDown(self):self.h.db.close();self.tmp.cleanup()
    def start(self,**kw):return self.w.start('user','test work and inspect',['sol-1','sol-2','flash-3','astra'],max_calls=12,confirmed=True,**kw)
    def finish(self,s,value,status='completed'):
        self.h.db.execute('UPDATE executions SET status=?,result=? WHERE id=?',(status,value,s['run_id']))
    def tick(self):self.co.patrol();self.w.patrol()
    def plan(self,**kw):
        w=self.start(**kw);self.tick();s=self.w.steps(w['id'])[0]
        self.finish(s,json.dumps({'done':False,'report':'work','tasks':[{'agent':'sol-2','instruction':'do work with evidence'}]}));self.tick();self.tick();return w
    def test_direct_messages_wake_reuse_message_and_are_idempotent(self):
        w=self.plan();s=self.w.steps(w['id'])[-1];self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(s['run_id'],))
        mid=self.co.send('sol-2','sol-1','please inspect',request_key='dedup')[0];self.co.send('sol-2','sol-1','please inspect',request_key='dedup');self.tick()
        wake=dict(self.h.db.execute('SELECT * FROM wakeups WHERE message=?',(mid,)).fetchone());self.assertEqual(wake['status'],'queued')
        run=self.h.db.execute('SELECT * FROM executions WHERE task_id=?',(wake['task'],)).fetchone();self.assertEqual(run['message_id'],mid);self.assertEqual(len(self.w.steps(w['id'])),3)
    def test_worker_active_report_and_independent_check_then_manager_brief(self):
        w=self.plan(reviewer='flash-3');s=self.w.steps(w['id'])[-1]
        self.finish(s,json.dumps({'summary':'implemented','risk':'low','evidence':['test passed'],'messages':[]}));self.tick();self.tick()
        steps=self.w.steps(w['id']);self.assertEqual(steps[-1]['kind'],'check');self.assertEqual(steps[-1]['agent'],'flash-3')
        self.assertTrue(self.h.db.execute("SELECT 1 FROM messages WHERE sender='sol-2' AND recipient='argon' AND body LIKE '[主动汇报]%' ").fetchone())
        self.finish(steps[-1],json.dumps({'summary':'verified','risk':'low','evidence':['independently passed']}));self.tick();self.tick();s=self.w.steps(w['id'])[-1]
        self.assertEqual(s['kind'],'review');self.assertIn('verified',s['prompt']);self.assertIn('implemented',s['prompt'])
        self.finish(s,json.dumps({'done':True,'report':'accepted','tasks':[]}));self.tick();self.assertEqual(self.w.snapshot('user')[0]['status'],'completed')
    def test_high_risk_inspector_prevents_false_acceptance(self):
        w=self.plan(reviewer='flash-3');self.finish(self.w.steps(w['id'])[-1],json.dumps({'summary':'done','risk':'low'}));self.tick();self.tick()
        self.finish(self.w.steps(w['id'])[-1],json.dumps({'summary':'serious defect','risk':'high'}));self.tick();self.tick()
        self.finish(self.w.steps(w['id'])[-1],json.dumps({'done':True,'report':'ignore defect','tasks':[]}));self.tick();self.assertEqual(self.w.snapshot('user')[0]['status'],'active');self.assertEqual(self.w.steps(w['id'])[-1]['kind'],'review');self.assertIn('退回 Argon',self.w.snapshot('user')[0]['report'])
    def test_chain_hops_budget_and_unauthorized_messages_do_not_loop(self):
        w=self.plan(max_hops=1);s=self.w.steps(w['id'])[-1]
        self.finish(s,json.dumps({'summary':'a','risk':'low','messages':[{'recipient':'sol-1','body':'question'}]}));self.tick();self.tick();s=next(s for s in self.w.steps(w['id']) if s['kind']=='message')
        self.assertEqual(s['kind'],'message');self.finish(s,json.dumps({'summary':'b','risk':'low','messages':[{'recipient':'sol-2','body':'echo'}]}));self.tick()
        held=self.h.db.execute("SELECT * FROM wakeups WHERE status='held' AND depth=1").fetchall();self.assertEqual(len(held),1)
        mid=self.co.send('deepseek','sol-2','unauthorized')[0];self.assertEqual(self.h.db.execute('SELECT status FROM wakeups WHERE message=?',(mid,)).fetchone()[0],'held')
    def test_user_emergency_stop_is_latched_survives_restart_and_no_auto_replay(self):
        w=self.plan();self.co.halt('user','*','stop now');self.assertTrue(self.co.is_stopped('sol-2'));self.assertEqual(self.w.snapshot('user')[0]['status'],'stopped')
        self.assertFalse(self.h.db.execute("SELECT 1 FROM executions WHERE status='queued'").fetchone())
        with self.assertRaises(HubError):self.c.submit('user','sol-1','new work',True)
        restored=Hub(self.tmp.name,recover=False);self.assertIsNotNone(restored.db.execute("SELECT 1 FROM agent_stops WHERE agent='*'").fetchone());restored.db.close()
        with self.assertRaises(HubError):self.co.resume('astra','*')
        self.co.resume('user','*');self.assertFalse(self.co.is_stopped('sol-2'));self.tick();self.assertEqual(self.w.snapshot('user')[0]['status'],'stopped')
    def test_user_messages_wake_without_active_project_and_preserve_body(self):
        for agent in ('argon','sol-1','flash-1'):
            mid=self.co.send('user',agent,'检查一下吧')[0]
            self.co.route(mid);self.co.patrol()
            rows=self.h.db.execute('SELECT * FROM executions WHERE message_id=?',(mid,)).fetchall()
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['prompt'],'检查一下吧')
            self.assertEqual(rows[0]['purpose'],'question')
            self.assertEqual(self.h.db.execute('SELECT status FROM wakeups WHERE message=?',(mid,)).fetchone()[0],'queued')

    def test_blocked_project_message_wakes_real_manager_without_replaying_workers(self):
        w=self.plan();w['status']='blocked';self.w.save(w)
        mid=self.co.send('user','argon','请继续处理')[0]
        current=self.w.snapshot('user')[0];self.assertEqual(current['status'],'active')
        manager=self.w.steps(w['id'])[-1]
        self.assertEqual(manager['kind'],'review');self.assertIn('请继续处理',self.h.db.execute('SELECT title FROM tasks WHERE id=?',(manager['task'],)).fetchone()[0])
        self.assertEqual(self.h.db.execute('SELECT status FROM wakeups WHERE message=?',(mid,)).fetchone()[0],'batched')
        self.assertIsNone(self.h.db.execute('SELECT 1 FROM executions WHERE message_id=?',(mid,)).fetchone())

    def test_held_user_message_retries_after_configuration_but_stop_lock_holds(self):
        cfg=self.a.config();self.a.configure('user',self.tmp.name,'full',20,60,False,True)
        mid=self.co.send('user','argon','消息仍应保留')[0]
        self.assertEqual(self.h.db.execute('SELECT status FROM wakeups WHERE message=?',(mid,)).fetchone()[0],'held')
        self.a.configure('user',self.tmp.name,'full',20,60,True,True)
        self.co.patrol();self.co.patrol()
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM executions WHERE message_id=?',(mid,)).fetchone()[0],1)
        self.co.halt('user','argon','stop')
        stopped=self.co.send('user','argon','停止锁期间')[0];self.co.patrol()
        self.assertIsNone(self.h.db.execute('SELECT 1 FROM executions WHERE message_id=?',(stopped,)).fetchone())

    def test_standalone_dialogue_keeps_own_session_not_manager_tool_context(self):
        w=self.start();w['status']='paused';self.w.save(w)
        mid=self.co.send('user','argon','解释一下')[0]
        run=dict(self.h.db.execute('SELECT * FROM executions WHERE message_id=?',(mid,)).fetchone())
        self.assertEqual(self.a.sessions.scope(run),'hub-project:'+w['id'])
        self.a.sessions.bind(run,'chat-session')
        again=dict(run,id='new-run')
        self.assertEqual(self.a.sessions.get(again)['session_id'],'chat-session')
        manager=dict(run,purpose='task')
        self.assertEqual(self.a.sessions.key(manager),self.a.sessions.key(run))
        instructions=self.a.execution_instructions(run)
        self.assertIn('不调用任何工具',instructions);self.assertIn('paused',instructions)

    def test_explicit_user_wake_recovers_blocked_manager_without_replaying_workers(self):
        w=self.plan();before=self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0]
        w=self.w.snapshot('user')[0];w['status']='blocked';w['manager_recoveries']=2;self.w.save(w)
        result=self.w.wake('user',w['id'],'检查第一阶段现场，启动第二阶段，不重放旧任务')
        self.assertTrue(result['activated'])
        current=self.w.snapshot('user')[0]
        self.assertEqual(current['status'],'active');self.assertEqual(current['manager_recoveries'],0)
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0],before)
        self.assertEqual(self.w.steps(w['id'])[-1]['kind'],'review')

    def test_current_malformed_tool_error_does_not_trigger_manager_retry_loop(self):
        w=self.plan();current=self.w.snapshot('user')[0]
        task=self.w.prepare_manager(current,self.w.steps(w['id']));self.w.patrol()
        step=self.w.steps(w['id'])[-1];self.finish(step,'tool malformed',status='failed')
        with self.h.tx():self.h.db.execute('INSERT INTO execution_events(run_id,ts,kind,data) VALUES(?,?,?,?)',(step['run_id'],time.time(),'antigravity.failure',json.dumps({'code':'malformed_function_call'})))
        count=len(self.w.steps(w['id']));self.w.patrol();self.w.patrol()
        self.assertEqual(self.w.snapshot('user')[0]['status'],'blocked');self.assertEqual(len(self.w.steps(w['id'])),count)

    def test_delegate_default_off_and_scoped_when_opted_in(self):
        w=self.plan()
        with self.assertRaises(HubError):self.co.halt('argon','sol-2','risk')
        self.co.halt('user','sol-2','stop');self.co.resume('user','sol-2');w=self.plan(delegate_stop=True)
        with self.assertRaises(HubError):self.co.halt('astra','*','risk')
        with self.assertRaises(HubError):self.co.halt('astra','opus','risk')
        self.co.halt('astra','sol-2','risk');self.assertTrue(self.co.is_stopped('sol-2'))
    def test_hard_stop_kills_only_active_owned_process(self):
        w=self.plan();s=self.w.steps(w['id'])[-1];self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(s['run_id'],))
        class Job:
            killed=False
            def close(self):self.killed=True
        class Client:job=Job();proc=None
        self.c.active_client=Client();self.c.active_run=s['run_id'];self.co.halt('user','sol-2','stop');self.assertTrue(self.c.active_client.job.killed)
        self.assertEqual(self.h.db.execute('SELECT stop_requested FROM executions WHERE id=?',(s['run_id'],)).fetchone()[0],1)
    def test_receipt_does_not_reply_again_and_simulated_agents_obey_latch(self):
        mid=self.h.send('sol-1','sol-2','receipt',request_key='execution:example:reply')[0]
        run=self.c.submit('user','sol-2','receipt',True,source_message_id=mid);run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(run['id'],)).fetchone())
        self.c.deliver_result(run,'completed','read');self.assertFalse(self.h.db.execute("SELECT 1 FROM messages WHERE sender='sol-2' AND recipient='sol-1'").fetchone())
        self.co.halt('user','flash-1','stop');mid=self.h.send('user','flash-1','test')[0];self.h.tick(True)
        self.assertEqual(self.h.db.execute('SELECT status FROM messages WHERE id=?',(mid,)).fetchone()[0],'pending')
if __name__=='__main__':unittest.main()
