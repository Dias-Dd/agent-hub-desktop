"""Persistent sessions and out-of-order, message-driven manager scheduling."""
import json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from hub.core import Hub,HubError
from hub.codex_runtime import CodexRuntime
from hub.antigravity import AntigravityRuntime,AntigravityStream
from hub.workflows import Workflows
from hub.coordination import Coordination
from test_codex_runtime import FakeAppServer
from test_antigravity import FakeStream,FakeProbe

class MemoryServer(FakeAppServer):
    conversations={};next_id=0;log=[]
    def rpc(self,method,params,timeout=25):
        self.__class__.log.append((method,params.copy()))
        if method=='thread/start':
            self.__class__.next_id+=1;self.ident='persistent-'+str(self.__class__.next_id);self.conversations[self.ident]=[]
        if method=='thread/resume':
            self.ident=params['threadId'];assert self.ident in self.conversations
        if method in ('thread/start','thread/resume'):
            return {'thread':{'id':self.ident},'model':params['model'],'modelProvider':'openai','approvalPolicy':'never','sandbox':{'type':'dangerFullAccess'}}
        if method=='turn/start':
            self.conversations[self.ident].append(params['input'][0]['text'])
            answer=' | '.join(self.conversations[self.ident])
            self.events=[{'method':'item/completed','params':{'threadId':self.ident,'item':{'type':'agentMessage','text':answer}}},{'method':'turn/completed','params':{'threadId':self.ident,'turn':{'id':'turn-test','status':'completed'}}}]
            return {'turn':{'id':'turn-test','status':'inProgress'}}
        return super().rpc(method,params,timeout)

class SessionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.h=Hub(self.tmp.name);MemoryServer.log=[];MemoryServer.conversations={};MemoryServer.next_id=0
        self.r=CodexRuntime(self.h,MemoryServer);self.r.configure('user',self.tmp.name,'full',20,60,True,True)
    def tearDown(self):self.r.close();self.h.db.close();self.tmp.cleanup()
    def execute(self,agent,prompt):
        job=self.r.submit('user',agent,prompt,True)
        run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone());self.r.execute(run)
        return dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone())
    def test_codex_resumes_same_context_after_runtime_restart_and_isolates_agents(self):
        first=self.execute('sol-1','remember ALPHA')
        self.r.close();self.r=CodexRuntime(self.h,MemoryServer)
        second=self.execute('sol-1','new message only')
        self.assertEqual(first['thread_id'],second['thread_id']);self.assertIn('ALPHA',second['result'])
        self.assertEqual([p['input'][0]['text'] for m,p in MemoryServer.log if m=='turn/start'],['remember ALPHA','new message only'])
        other=self.execute('sol-2','separate identity')
        self.assertNotEqual(first['thread_id'],other['thread_id']);self.assertNotIn('ALPHA',other['result'])
        self.assertEqual(len([x for x in MemoryServer.log if x[0]=='thread/resume']),1)
    def test_resumption_failure_does_not_silently_start_fresh_or_replay(self):
        self.execute('sol-1','original')
        class Refuse(MemoryServer):
            def rpc(self,method,params,timeout=25):
                if method=='thread/resume':raise HubError('stored session unavailable')
                return super().rpc(method,params,timeout)
        self.r.factory=Refuse;failed=self.execute('sol-1','followup')
        self.assertEqual(failed['status'],'failed');self.assertEqual(len(MemoryServer.conversations),1)
        self.assertEqual(list(MemoryServer.conversations.values()),[['original']])
    def test_antigravity_reuses_conversation_and_official_flag(self):
        seen=[]
        class Continuing(FakeStream):
            def __init__(self,run,instructions):seen.append(run.get('_conversation'));super().__init__(run,instructions)
        ag=AntigravityRuntime(self.h,Continuing,FakeProbe());ag.configure('user',self.tmp.name,'full',20,60,True,True)
        try:
            for prompt in ['first','only new task']:
                job=ag.submit('user','flash-1',prompt,True);run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone());ag.execute(run)
            self.assertEqual(seen,[None,'agy-conversation'])
            captured=[]
            def spawn(args,**kwargs):captured.extend(args);raise OSError('fixture')
            with patch('hub.antigravity.executable',return_value='official-agy'),patch('hub.antigravity.subprocess.Popen',side_effect=spawn):
                with self.assertRaises(OSError):AntigravityStream({**run,'_conversation':'agy-conversation'},'policy')
            self.assertEqual(captured[captured.index('--conversation')+1],'agy-conversation')
        finally:ag.close()
    def test_project_scopes_are_separate_and_grant_changes_preserve_memory(self):
        run={'id':'x','task_id':'x','provider':'codex','agent':'sol-1','model':'gpt-6.1-sol','cwd':self.tmp.name,'permission':'full','grant_id':'a','session_scope':'project:A'}
        self.r.sessions.bind(run,'id-A')
        self.assertIsNone(self.r.sessions.get({**run,'session_scope':'project:B'}))
        self.assertEqual(self.r.sessions.get({**run,'grant_id':'b'})['session_id'],'id-A')
        self.assertEqual(self.r.sessions.get({**run,'permission':'workspace'})['session_id'],'id-A')

class InboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.h=Hub(self.tmp.name)
        self.c=CodexRuntime(self.h);self.a=AntigravityRuntime(self.h)
        for rt in (self.c,self.a):rt.configure('user',self.tmp.name,'full',100,60,True,True)
        self.w=Workflows(self.h,[self.c,self.a]);self.co=Coordination(self.h,[self.c,self.a],self.w)
    def tearDown(self):self.h.db.close();self.tmp.cleanup()
    def start(self,reviewer='argon'):
        plan={'done':False,'report':'approved scope','tasks':[{'agent':'sol-1','instruction':'own file A'},{'agent':'sol-2','instruction':'own file B'}]}
        w=self.w.start('user','persistent project',['sol-1','sol-2','flash-3'],max_calls=30,confirmed=True,reviewer=reviewer,approved_proposal=plan)
        self.tick(2);return w
    def tick(self,n=1):
        for _ in range(n):self.co.patrol();self.w.patrol()
    def finish(self,s,value=None,status='completed'):
        self.h.db.execute('UPDATE executions SET status=?,result=?,finished=? WHERE id=?',(status,json.dumps(value or {'summary':'verified','risk':'low','evidence':['test passed']}),time.time(),s['run_id']))
    def waiting(self,s):self.finish(s,{'done':False,'report':'waiting for remaining member','tasks':[]})
    def test_late_old_worker_and_checker_wake_new_manager_and_finish(self):
        w=self.start('flash-3');steps=self.w.steps(w['id']);self.finish(steps[0]);self.tick(2)
        manager=self.w.steps(w['id'])[-1];self.assertEqual(manager['kind'],'review')
        self.waiting(manager);self.tick();self.finish(steps[1]);self.tick(2)
        check=self.w.steps(w['id'])[-1];self.assertEqual(check['kind'],'check');self.finish(check);self.tick(2)
        final=self.w.steps(w['id'])[-1];self.assertEqual(final['kind'],'review');self.assertGreater(final['seq'],manager['seq'])
        self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(final['run_id'],))
        done=self.w.project_complete('argon',final['run_id'],'validated project',['independent check passed'])
        self.assertTrue(done['completed']);self.assertEqual(self.w.snapshot('user')[0]['status'],'completed')
        self.assertTrue(self.w.project_complete('argon',final['run_id'],'validated project',['independent check passed'])['deduplicated'])
        before=len(self.w.steps(w['id']));self.tick(5);self.assertEqual(before,len(self.w.steps(w['id'])))
    def test_new_message_during_busy_manager_is_retained_and_claimed_afterwards(self):
        w=self.start();steps=self.w.steps(w['id']);self.finish(steps[0]);self.tick(2)
        manager=self.w.steps(w['id'])[-1];self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(manager['run_id'],))
        self.finish(steps[1]);self.tick(3);self.assertEqual(self.w.steps(w['id'])[-1]['seq'],manager['seq'])
        self.waiting(manager);self.tick();self.assertEqual(self.w.steps(w['id'])[-1]['kind'],'review');self.assertGreater(self.w.steps(w['id'])[-1]['seq'],manager['seq'])
        self.assertEqual(self.h.db.execute("SELECT count(*) FROM workflow_events WHERE status='pending'").fetchone()[0],0)
    def test_checker_created_before_manager_finishes_late_still_wakes_it(self):
        w=self.start('flash-3');self.w.add_step(w,'flash-3','check','read all artifacts');self.tick()
        original=self.w.steps(w['id']);check=original[-1]
        self.finish(original[0]);self.tick(2);manager=self.w.steps(w['id'])[-1]
        self.assertGreater(manager['seq'],check['seq']);self.waiting(manager);self.tick()
        self.finish(original[1]);self.tick(2);manager=self.w.steps(w['id'])[-1];self.waiting(manager);self.tick()
        self.finish(check);self.tick(2)
        after=self.w.steps(w['id'])[-1];self.assertEqual(after['kind'],'review');self.assertGreater(after['seq'],manager['seq'])
        self.assertIn('verified',after['prompt'])

    def test_queue_message_to_argon_is_inbox_event_not_worker_task(self):
        w=self.start();s=self.w.steps(w['id'])[0];self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(s['run_id'],))
        mid=self.co.send('sol-1','argon','short independent question','queue','q1')[0]
        self.tick(2);review=self.w.steps(w['id'])[-1]
        self.assertEqual(review['kind'],'review');self.assertIn('short independent question',review['prompt'])
        self.assertFalse(any(s['kind']=='message' and s['agent']=='argon' for s in self.w.steps(w['id'])))
        self.assertTrue(self.h.db.execute('SELECT 1 FROM workflow_events WHERE id=?',('message:'+mid,)).fetchone())
    def test_mcp_model_report_is_delivered_only_after_provider_finishes(self):
        w=self.start();s=self.w.steps(w['id'])[0];self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(s['run_id'],))
        self.w.report_result('sol-1',s['run_id'],'short model authored report','low',['unit test passed']);self.tick()
        self.assertFalse(self.h.db.execute('SELECT 1 FROM workflow_events WHERE source_run=?',(s['run_id'],)).fetchone())
        self.finish(s,{'summary':'verbose fallback','risk':'unknown'});self.tick()
        event=json.loads(self.h.db.execute('SELECT body FROM workflow_events WHERE source_run=?',(s['run_id'],)).fetchone()[0]);self.assertEqual(event['summary'],'short model authored report')
    def test_worker_and_premature_completion_are_rejected(self):
        w=self.start();s=self.w.steps(w['id'])[0];self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(s['run_id'],))
        with self.assertRaises(HubError):self.w.project_complete('sol-1',s['run_id'],'pretend',['no evidence'])
        self.finish(s);self.tick(2);manager=self.w.steps(w['id'])[-1];self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(manager['run_id'],))
        with self.assertRaises(HubError):self.w.project_complete('argon',manager['run_id'],'premature',['test'])
        self.co.halt('user','*','stop')
        with self.assertRaises(HubError):self.w.project_assign('argon',manager['run_id'],'sol-1','more work','new')
    def test_periodic_busy_only_inspection_and_pause(self):
        w=self.start();steps=self.w.steps(w['id']);self.finish(steps[0]);self.finish(steps[1]);self.tick(2)
        manager=self.w.steps(w['id'])[-1];self.waiting(manager);self.tick(3)
        count=len(self.w.steps(w['id']));self.assertEqual(count,3)
        current=self.w.snapshot('user')[0];current.pop('steps');current['next_inspection']=time.time()-1;self.w.save(current)
        self.tick(2);probe=self.w.steps(w['id'])[-1]
        self.assertEqual(len(self.w.steps(w['id'])),count+1)
        self.assertTrue(probe['prompt'].startswith('成员忙闲：'))
        for forbidden in ('persistent project','verified','quota','own file'):self.assertNotIn(forbidden,probe['prompt'])
        self.tick(4);self.assertEqual(len(self.w.steps(w['id'])),count+1)
        self.waiting(probe);self.tick()
        current=self.w.snapshot('user')[0];current.pop('steps');current.update(status='paused',next_inspection=0);self.w.save(current)
        self.tick(4);self.assertEqual(len(self.w.steps(w['id'])),count+1)

    def test_project_report_excludes_raw_trace_and_preserves_local_result(self):
        w=self.start();step=self.w.steps(w['id'])[0]
        run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(step['run_id'],)).fetchone())
        raw='PRIVATE_FULL_TRACE '*1000
        self.finish(step,{'summary':'short result','risk':'low','evidence':['passed']})
        self.c.deliver_result(run,'completed',raw);self.tick()
        self.assertFalse(self.h.db.execute("SELECT 1 FROM messages WHERE request_key LIKE ?",('execution:'+run['id']+'%',)).fetchone())
        report=self.h.db.execute('SELECT body FROM messages WHERE request_key=?',('report:'+run['id'],)).fetchone()[0]
        self.assertIn('short result',report);self.assertNotIn('PRIVATE_FULL_TRACE',report)
        self.assertTrue(self.h.db.execute('SELECT result FROM executions WHERE id=?',(run['id'],)).fetchone()[0])

    def test_paused_project_chat_wakes_once_and_resume_does_not_duplicate(self):
        w=self.start();w.update(status='paused');self.w.save(w)
        mid=self.co.send('user','argon','continue','queue')[0]
        self.h.db.execute('ALTER TABLE messages ADD COLUMN project_id TEXT')
        self.h.db.execute('UPDATE messages SET project_id=? WHERE id=?',(w.get('project_id'),mid))
        self.assertEqual(self.h.db.execute('SELECT status FROM wakeups WHERE message=?',(mid,)).fetchone()[0],'queued')
        self.assertEqual(self.w.snapshot('user')[0]['status'],'paused')
        self.h.db.commit()
        self.assertTrue(self.w.resume('user',w['id'],mid)['resumed'])
        self.assertEqual(self.h.db.execute('SELECT status FROM wakeups WHERE message=?',(mid,)).fetchone()[0],'queued')
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM executions WHERE message_id=?',(mid,)).fetchone()[0],1)
        self.assertEqual(self.w.steps(w['id'])[-1]['kind'],'review')
        with self.assertRaises(HubError):self.w.resume('user',w['id'],mid)

    def test_completed_project_user_feedback_reopens_and_wakes(self):
        w=self.start();self.h.db.execute('ALTER TABLE messages ADD COLUMN project_id TEXT');self.h.db.commit()
        w.update(project_id='logical-project',status='completed',completion={'summary':'previous acceptance'})
        self.w.save(w)
        mid=self.h.send('user','argon','screen is black')[0]
        self.h.db.execute('UPDATE messages SET project_id=? WHERE id=?',('logical-project',mid));self.h.db.commit()
        self.h.db.execute("INSERT INTO wakeups VALUES(?,?,?,?,?,?,?)",(mid,None,None,mid,0,'held','old rejection'));self.h.db.commit()
        self.co.route(mid);self.tick(2)
        current=self.w.snapshot('user')[0]
        self.assertEqual(current['status'],'active');self.assertEqual(len(current['completion_history']),1)
        self.assertEqual(self.w.steps(w['id'])[-1]['kind'],'review')
        self.assertIn('screen is black',self.w.steps(w['id'])[-1]['prompt'])
        count=len(self.w.steps(w['id']));self.co.route(mid);self.tick();self.assertEqual(len(self.w.steps(w['id'])),count)

    def test_new_mail_during_completion_does_not_exhaust_acceptance_retries(self):
        w=self.start()
        for step in self.w.steps(w['id']):self.finish(step)
        self.tick(2);manager=self.w.steps(w['id'])[-1]
        self.assertEqual(manager['kind'],'review')
        mid=self.co.send('user','argon','还有新的需求，请继续')[0]
        current=self.w.snapshot('user')[0];current['acceptance_corrections']=2;self.w.save(current)
        self.finish(manager,{'done':True,'report':'准备验收','tasks':[]});self.tick(2)
        current=self.w.snapshot('user')[0]
        self.assertEqual(current['status'],'active');self.assertEqual(current['acceptance_corrections'],0)
        latest=self.w.steps(w['id'])[-1]
        self.assertGreater(latest['seq'],manager['seq']);self.assertIn('还有新的需求',latest['prompt'])
        self.assertEqual(self.h.db.execute('SELECT status FROM messages WHERE id=?',(mid,)).fetchone()[0],'acknowledged')

    def test_previously_batched_user_mail_is_recovered_from_blocked_workflow_once(self):
        w=self.start()
        for step in self.w.steps(w['id']):self.finish(step)
        self.tick(2);manager=self.w.steps(w['id'])[-1]
        mid=self.co.send('user','argon','入队后仍应唤醒')[0]
        self.waiting(manager)
        current=self.w.snapshot('user')[0];current['status']='blocked';self.w.save(current)
        self.tick(2)
        current=self.w.snapshot('user')[0];self.assertEqual(current['status'],'active')
        latest=self.w.steps(w['id'])[-1]
        self.assertIn('入队后仍应唤醒',latest['prompt']);count=len(self.w.steps(w['id']))
        self.tick(3);self.assertEqual(len(self.w.steps(w['id'])),count)

    def test_dispatch_idempotency_and_busy_agent_guard(self):
        w=self.start();s=self.w.steps(w['id'])[0];self.finish(s);self.tick(2);manager=self.w.steps(w['id'])[-1]
        self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(manager['run_id'],))
        one=self.w.project_assign('argon',manager['run_id'],'sol-1','new independent work','stable')
        two=self.w.project_assign('argon',manager['run_id'],'sol-1','new independent work','stable');self.assertEqual(one['task_id'],two['task_id']);self.assertTrue(two['deduplicated'])
        queued=self.w.project_assign('argon',manager['run_id'],'sol-2','later queued work','other');self.assertEqual(queued['status'],'queued');self.assertTrue(queued['after_task'])

class ApiSessionTests(unittest.TestCase):
    def test_deepseek_keeps_approved_history_and_rejects_stale_prepared_context(self):
        import os
        from hub.connectors import Calls,DeepSeek
        class Fake(DeepSeek):
            seen=[]
            def models(self):return {'data':[{'id':'deepseek-flash'}]}
            def complete(self,prompt,history=None):
                self.seen.append((prompt,history));return {'choices':[{'message':{'content':'remembered'}}]}
        with tempfile.TemporaryDirectory() as directory:
            h=Hub(directory);fake=Fake();calls=Calls(h,fake);calls.budget('user',100)
            try:
                first=calls.prepare('user','remember A')['id'];calls.approve('user',first,1,100,100,True)
                with patch.dict(os.environ,{'HUB_ALLOW_REAL':'1','DEEPSEEK_API_KEY':'fixture'}):calls.execute('user',first)
                second=calls.prepare('user','followup')['id'];stale=calls.prepare('user','stale')['id']
                for ident in (second,stale):calls.approve('user',ident,1,100,100,True)
                with patch.dict(os.environ,{'HUB_ALLOW_REAL':'1','DEEPSEEK_API_KEY':'fixture'}):
                    calls.execute('user',second)
                    with self.assertRaises(HubError):calls.execute('user',stale)
                self.assertEqual(fake.seen[0][1],[]);self.assertEqual(fake.seen[1][1][0]['content'],'remember A')
                self.assertEqual(len(fake.seen),2)
            finally:h.db.close()

if __name__=='__main__':unittest.main()
