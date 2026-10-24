import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from hub.core import Hub,HubError
from hub.codex_runtime import CodexRuntime
from hub.antigravity import AntigravityRuntime
from hub.deepseek_runtime import DeepSeekRuntime,protect
from hub.workflows import Workflows
from hub.coordination import Coordination
from hub.quota_monitor import QuotaMonitor


class FakeAPI:
    def __init__(self):self.requests=[];self.answers=[]
    def request(self,path,payload=None):
        self.requests.append((path,payload))
        if path=='/models':return {'data':[{'id':'deepseek-flash'}]}
        if self.answers:return self.answers.pop(0)
        return {'choices':[{'message':{'role':'assistant','content':json.dumps({'summary':'verified','risk':'low','evidence':['fixture']}),'tool_calls':[]},'finish_reason':'stop'}],'usage':{'prompt_tokens':10,'completion_tokens':10}}


class DeepSeekTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.h=Hub(self.tmp.name)
        self.c=CodexRuntime(self.h);self.a=AntigravityRuntime(self.h);self.api=FakeAPI();self.d=DeepSeekRuntime(self.h,self.api)
        for rt in (self.c,self.a):rt.configure('user',self.tmp.name,'full',100,600,True,True)
        self.d.validate('user');self.configure()
        self.w=Workflows(self.h,[self.c,self.a,self.d]);self.h.workflows=self.w
        self.co=Coordination(self.h,[self.c,self.a,self.d],self.w)
        self.q=QuotaMonitor(self.h,self.w,self.c,self.a,self.d);self.h.quota_monitor=self.q
    def configure(self,**kwargs):
        args=dict(cwd=self.tmp.name,permission='workspace',max_runs=100,max_seconds=600,budget_cents=100,input_rate=10,output_rate=20,max_requests=8,max_output=256,enabled=True,takeover=True,confirmed=True);args.update(kwargs)
        return self.d.configure_api('user',**args)
    def tearDown(self):self.q.close();self.d.close();self.h.db.close();self.tmp.cleanup()
    def start(self,agent='deepseek'):
        plan={'done':False,'report':'approved','tasks':[{'agent':agent,'instruction':'small scoped task'}]}
        return self.w.start('user','approved scope',['deepseek','sol-1','flash-3'],max_calls=30,confirmed=True,reviewer='flash-3',approved_proposal=plan)
    def prepare_run(self):
        w=self.start();self.w.patrol();s=self.w.steps(w['id'])[0]
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='running',started=? WHERE id=?",(time.time(),s['run_id']))
        return w,dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(s['run_id'],)).fetchone())
    def tool_answer(self,name,args):
        return {'choices':[{'message':{'role':'assistant','content':None,'tool_calls':[{'id':'tool-1','type':'function','function':{'name':name,'arguments':json.dumps(args)}}]},'finish_reason':'tool_calls'}]}
    def test_direct_chat_uses_existing_budget_without_active_project_or_tools(self):
        mid=self.co.send('user','deepseek','你好')[0]
        run=dict(self.h.db.execute('SELECT * FROM executions WHERE message_id=?',(mid,)).fetchone())
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='running',started=? WHERE id=?",(time.time(),run['id']))
        self.d.execute(run)
        stored=self.h.db.execute('SELECT status FROM executions WHERE id=?',(run['id'],)).fetchone()[0]
        self.assertEqual(stored,'completed')
        payload=self.api.requests[-1][1]
        self.assertEqual(payload['messages'][-1]['content'],'你好');self.assertEqual(payload['tools'],[])
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM deepseek_spend').fetchone()[0],1)

    def test_existing_deepseek_http_history_survives_project_key_upgrade(self):
        import hashlib
        w,run=self.prepare_run()
        raw='project:'+w['id']
        legacy=hashlib.sha256(json.dumps([raw,run['provider'],run['agent'],run['model'],run['cwd'],run['permission'],run['grant_id']],ensure_ascii=False).encode()).hexdigest()
        history=[{'role':'user','content':'remember DS memory'},{'role':'assistant','content':'ack'}]
        with self.h.tx():self.h.db.execute('INSERT INTO deepseek_context VALUES(?,?)',(legacy,json.dumps(history)))
        self.d.execute(run)
        sent=self.api.requests[-1][1]['messages']
        self.assertTrue(any(m.get('content')=='remember DS memory' for m in sent))

    def test_connection_validation_sends_no_inference(self):
        self.assertEqual([r[0] for r in self.api.requests],['/models'])
        self.assertFalse(self.d.saved_validation()['inference_sent'])
    def test_enable_requires_validation_and_explicit_budget(self):
        with self.assertRaises(HubError):self.configure(confirmed=False)
        with self.assertRaises(HubError):self.configure(budget_cents=0)
        self.h.db.execute("DELETE FROM settings WHERE key='deepseek_validation'");self.h.db.commit()
        with self.assertRaises(HubError):self.configure()
    def test_model_mismatch_stays_disabled(self):
        self.api.request=lambda *args:{'data':[{'id':'different-model'}]}
        self.assertFalse(self.d.validate('user')['supported'])
        with self.assertRaises(HubError):self.configure()
    @unittest.skipUnless(os.name=='nt','Windows DPAPI')
    def test_key_is_encrypted_persistent_and_never_returned(self):
        secret='fixture-only-key-123456789'
        self.d.save_key('user',secret)
        self.assertEqual(self.d.key(),secret)
        self.assertNotIn(secret.encode(),(Path(self.tmp.name)/'deepseek-key.dpapi').read_bytes())
        self.assertNotIn(secret,json.dumps(self.d.status('user')))
        self.assertNotIn(secret,str(self.h.db.execute('SELECT detail FROM audit').fetchall()))
    def test_worker_tool_loop_writes_file_and_reports_once(self):
        w,r=self.prepare_run();self.api.answers=[self.tool_answer('write_file',{'path':'answer.txt','content':'4'}),self.tool_answer('report_result',{'summary':'done','risk':'low','evidence':['answer.txt']} )]
        self.d.execute(r)
        self.assertEqual((Path(self.tmp.name)/'answer.txt').read_text(),'4')
        self.assertEqual(self.h.db.execute('SELECT status FROM executions WHERE id=?',(r['id'],)).fetchone()[0],'completed')
        self.co.patrol();self.co.patrol()
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM worker_reports WHERE run=?',(r['id'],)).fetchone()[0],1)
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM deepseek_spend').fetchone()[0],3)
    def test_file_escape_and_workspace_shell_are_rejected(self):
        w,r=self.prepare_run();r['started']=time.time()
        with self.assertRaises(HubError):self.d.tool(r,'write_file',{'path':'../escape.txt','content':'bad'},{'write_file'})
        names={t['function']['name'] for t in self.d.definitions(r)}
        self.assertNotIn('run_command',names);self.assertNotIn('project_assign',names)
    def test_readonly_check_has_no_write_or_command_tools(self):
        w,r=self.prepare_run();r['_read_only']=True
        names={t['function']['name'] for t in self.d.definitions(r)}
        self.assertNotIn('write_file',names);self.assertNotIn('run_command',names)
    def test_budget_reserved_before_request_and_blocks_next_request(self):
        self.configure(budget_cents=1)
        w,r=self.prepare_run();self.api.answers=[self.tool_answer('read_file',{'path':'missing.txt'})]
        self.d.execute(r)
        self.assertEqual(len([p for p,d in self.api.requests if p=='/chat/completions']),1)
        self.assertEqual(self.d.status('user')['remaining_cents'],0)
        self.assertEqual(self.h.db.execute('SELECT status FROM executions WHERE id=?',(r['id'],)).fetchone()[0],'uncertain')
    def test_stop_latch_prevents_paid_request(self):
        w,r=self.prepare_run();self.co.halt('user','deepseek','stop')
        self.d.execute(r)
        self.assertEqual(len(self.api.requests),1)
    def test_tool_request_cap_prevents_unbounded_loop(self):
        self.configure(max_requests=1);w,r=self.prepare_run();self.api.answers=[self.tool_answer('read_file',{'path':'missing.txt'})]
        self.d.execute(r)
        self.assertEqual(len([p for p,d in self.api.requests if p=='/chat/completions']),1)
        self.assertIn('请求上限',self.h.db.execute('SELECT result FROM executions WHERE id=?',(r['id'],)).fetchone()[0])
    def test_paid_plan_approval_preserves_grant_and_money(self):
        old=self.d.config();new=self.d.configure('user',self.tmp.name,'workspace',30,300,True,True)
        self.assertEqual(old['grant_id'],new['grant_id']);self.assertEqual(new['budget_cents'],100)
        with self.assertRaises(HubError):self.d.configure('user',self.tmp.name,'full',30,300,True,True)
    def sample(self,n):return {'id':'test:weekly','label':'Argon weekly','provider':'antigravity','remaining':n,'resets_at':time.time()+1000,'agents':['argon']}
    def test_low_and_exhausted_notify_once_then_rearm_on_recovery(self):
        def count():return self.h.db.execute("SELECT count(*) FROM messages WHERE body LIKE '[平台额度通知]%' AND recipient='user'").fetchone()[0]
        for n in (10,9,8,0,0,2):self.q.observe(self.sample(n))
        self.assertEqual(count(),3) # low, exhausted, partial recovery
        self.q=QuotaMonitor(self.h,self.w,self.c,self.a,self.d)
        self.q.observe(self.sample(0));self.assertEqual(count(),4) # second exhaustion
        self.q.observe(self.sample(50));self.assertEqual(count(),5) # full recovery
        self.q.observe(self.sample(9));self.assertEqual(count(),6) # second low
        self.q.observe(self.sample(8));self.assertEqual(count(),6)
        self.q.observe(self.sample(0));self.assertEqual(count(),7)
    def test_member_low_wakes_argon_without_raw_quota_payload(self):
        w=self.start('sol-1');self.q.observe({**self.sample(9),'agents':['sol-1']});self.w.patrol();self.w.patrol()
        self.assertEqual(self.w.steps(w['id'])[-1]['agent'],'argon')
        self.assertIn('低于10%',self.h.db.execute('SELECT title FROM tasks WHERE id=?',(self.w.steps(w['id'])[-1]['task'],)).fetchone()[0])
    def test_authorized_takeover_single_manager_privilege_and_dispatch(self):
        w=self.start('sol-1');self.w.patrol();self.q.takeover(w)
        current=self.w.snapshot('user')[0];self.assertEqual(current['manager'],'deepseek')
        self.w.patrol();s=self.w.steps(w['id'])[-1]
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(s['run_id'],))
        assigned=self.w.project_assign('deepseek',s['run_id'],'sol-1','next task','key')
        self.assertIn('task_id',assigned)
        before=len(self.w.steps(w['id']));self.q.takeover(current);self.assertEqual(before,len(self.w.steps(w['id'])))
    def test_takeover_not_allowed_when_paused_stopped_or_no_authorization(self):
        w=self.start('sol-1');w['status']='paused';self.w.save(w);self.q.takeover(w)
        self.assertEqual(self.w.snapshot('user')[0].get('manager'),'argon')
        w['status']='active';w['backup_manager']=None;self.w.save(w);self.q.takeover(w)
        self.assertEqual(self.w.snapshot('user')[0].get('manager'),'argon')
    def test_busy_manager_is_not_interrupted_by_takeover(self):
        w=self.start('sol-1');self.w.prepare_manager(w,self.w.steps(w['id']));self.w.patrol();self.w.patrol()
        s=self.w.steps(w['id'])[-1]
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(s['run_id'],))
        self.q.takeover(w);self.assertEqual(self.w.snapshot('user')[0]['manager'],'argon')
    def test_official_stale_snapshot_is_unknown_not_exhaustion(self):
        with self.h.tx():self.h.db.execute("INSERT OR REPLACE INTO settings VALUES('antigravity_limits',?)",(json.dumps({'observed_at':time.time()-1000,'windows':[{'group':'Gemini 4 Argon','window':'weekly','remaining':0}]}),))
        self.assertEqual(self.q.samples(),[])

    def test_network_failure_keeps_reservation_and_never_retries(self):
        w,r=self.prepare_run()
        def fail(*args):raise HubError('DeepSeek HTTP 429；未自动重试')
        self.api.request=fail;self.d.execute(r)
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM deepseek_spend').fetchone()[0],1)
        self.assertEqual(self.h.db.execute('SELECT status FROM executions WHERE id=?',(r['id'],)).fetchone()[0],'uncertain')
        self.assertGreater(self.d.status('user')['reserved_cents'],0)

    def test_persistent_context_continues_across_new_tasks(self):
        w,r=self.prepare_run();self.d.execute(r)
        self.w.dispatch(w,'deepseek','followup only','next')
        self.w.patrol();step=self.w.steps(w['id'])[-1]
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(step['run_id'],))
        second=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(step['run_id'],)).fetchone());self.d.execute(second)
        sent=[v for k,v in self.api.requests if k=='/chat/completions']
        self.assertEqual([m['content'] for m in sent[-1]['messages'] if m['role']=='user'],['small scoped task','followup only'])

    def test_worker_cannot_gain_manager_tools_by_identity_alone(self):
        w,r=self.prepare_run();w['manager']='deepseek';self.w.save(w)
        names={t['function']['name'] for t in self.d.definitions(r)}
        self.assertNotIn('project_assign',names)
        with self.assertRaises(HubError):self.w.project_assign('deepseek',r['id'],'sol-1','unauthorized','bad')

    def test_takeover_cancels_waiting_manager_and_preserves_queued_worker(self):
        w=self.start('sol-1');self.w.patrol();self.w.prepare_manager(w,self.w.steps(w['id']));self.w.patrol()
        old=self.w.steps(w['id'])[-1]
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='waiting_quota',retry_after=? WHERE id=?",(time.time()+1000,old['run_id']))
        self.q.takeover(w)
        self.assertEqual(self.h.db.execute('SELECT status FROM executions WHERE id=?',(old['run_id'],)).fetchone()[0],'cancelled')
        self.assertEqual(self.w.steps(w['id'])[0]['status'],'queued')
        self.assertEqual(self.w.steps(w['id'])[-1]['agent'],'deepseek')

    def test_takeover_cannot_bypass_stop_or_expired_grant(self):
        w=self.start('sol-1');w['expires']=time.time()-1;self.w.save(w);self.q.takeover(w)
        self.assertEqual(self.w.snapshot('user')[0]['manager'],'argon')
        w['expires']=time.time()+100;self.w.save(w);self.co.halt('user','deepseek','stop');self.q.takeover(w)
        self.assertEqual(self.w.snapshot('user')[0]['manager'],'argon')

    def test_api_key_changes_are_refused_while_work_is_queued(self):
        w,r=self.prepare_run()
        with self.assertRaises(HubError):self.d.save_key('user','fixture-key-123456789')

    def test_shell_runs_only_after_full_access_authorization(self):
        self.configure(permission='full');w,r=self.prepare_run();r['started']=time.time()
        cmd='Write-Output HUB_TOOL_OK' if os.name=='nt' else 'echo HUB_TOOL_OK'
        result=self.d.tool(r,'run_command',{'command':cmd},{'run_command'})
        self.assertEqual(result['exit_code'],0);self.assertIn('HUB_TOOL_OK',result['output'])

    def test_backup_manager_can_complete_only_after_independent_check(self):
        w=self.start('sol-1');self.w.patrol();work=self.w.steps(w['id'])[0]
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='completed',result=? WHERE id=?",(json.dumps({'summary':'done','risk':'low','evidence':['fixture']}),work['run_id']))
        task=self.w.add_step(w,'flash-3','check','independent check')
        self.a.submit('user','flash-3','independent check',True,task)
        check=self.w.steps(w['id'])[-1]
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='completed',result=? WHERE id=?",(json.dumps({'summary':'checked','risk':'low','evidence':['test passed']}),check['run_id']))
        self.co.patrol();self.w.ingest(w,self.w.steps(w['id']));self.q.takeover(w);self.w.patrol()
        manager=self.w.steps(w['id'])[-1]
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(manager['run_id'],))
        r=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(manager['run_id'],)).fetchone())
        self.api.answers=[self.tool_answer('project_complete',{'summary':'accepted','evidence':['independent check passed']})]
        self.d.execute(r)
        self.assertEqual(self.w.snapshot('user')[0]['status'],'completed')
        self.assertEqual(self.h.db.execute('SELECT status FROM executions WHERE id=?',(r['id'],)).fetchone()[0],'completed')

    def test_argon_can_dispatch_deepseek_as_worker_before_takeover(self):
        w=self.start('sol-1');self.w.patrol();self.w.prepare_manager(w,self.w.steps(w['id']));self.w.patrol()
        manager=self.w.steps(w['id'])[-1]
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(manager['run_id'],))
        task=self.w.project_assign('argon',manager['run_id'],'deepseek','small backup engineering task','ds-work')
        self.w.patrol();step=next(s for s in self.w.steps(w['id']) if s['task']==task['task_id'])
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(step['run_id'],))
        run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(step['run_id'],)).fetchone());self.d.execute(run)
        self.assertEqual(self.w.snapshot('user')[0]['manager'],'argon')
        self.assertEqual(self.h.db.execute('SELECT status FROM executions WHERE id=?',(run['id'],)).fetchone()[0],'completed')

    def test_notification_routing_uses_current_manager_and_argon_headroom(self):
        w=self.start('sol-1')
        with patch.object(self.q,'argon_headroom',return_value=80):self.q.observe({**self.sample(9),'agents':['sol-1']})
        event=json.loads(self.h.db.execute('SELECT body FROM workflow_events ORDER BY created DESC LIMIT 1').fetchone()[0])
        self.assertEqual(event['recipients'],['argon'])
        w['manager']='deepseek';self.w.save(w)
        with patch.object(self.q,'argon_headroom',return_value=80):self.q.observe({**self.sample(0),'agents':['sol-1']})
        event=json.loads(self.h.db.execute('SELECT body FROM workflow_events ORDER BY created DESC LIMIT 1').fetchone()[0])
        self.assertEqual(event['recipients'],['argon','deepseek'])
        self.assertEqual(self.h.db.execute('SELECT recipient FROM messages WHERE id=?',(event['message_id'],)).fetchone()[0],'deepseek')
        with patch.object(self.q,'argon_headroom',return_value=5):self.assertEqual(self.q.recipients({**w,'manager':'argon'}),['argon','deepseek'])
        with patch.object(self.q,'argon_headroom',return_value=None):self.assertEqual(self.q.recipients({**w,'manager':'argon'}),['argon','deepseek'])

    def manager_run(self):
        w=self.start('sol-1');self.w.patrol();self.q.takeover(w);self.w.patrol()
        step=self.w.steps(w['id'])[-1]
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(step['run_id'],))
        return self.w.snapshot('user')[0],step

    def test_return_manager_waits_for_provider_end_then_transfers_once(self):
        w,step=self.manager_run()
        with patch.object(self.q,'argon_headroom',return_value=80):
            self.assertTrue(self.w.project_return_manager('deepseek',step['run_id'],'return management')['saved'])
            self.q.return_manager(self.w.snapshot('user')[0]);self.assertEqual(self.w.snapshot('user')[0]['manager'],'deepseek')
            with self.assertRaises(HubError):self.w.project_assign('deepseek',step['run_id'],'sol-1','extra work','denied')
            with self.h.tx():self.h.db.execute("UPDATE executions SET status='completed',result=? WHERE id=?",(json.dumps({'done':False,'report':'handoff ready','tasks':[]}),step['run_id']))
            self.w.patrol();self.q.return_manager(self.w.snapshot('user')[0])
            self.assertEqual(self.w.snapshot('user')[0]['manager'],'argon')
            self.assertEqual(self.w.steps(w['id'])[-1]['agent'],'argon')
            count=len(self.w.steps(w['id']));self.q.return_manager(self.w.snapshot('user')[0]);self.assertEqual(count,len(self.w.steps(w['id'])))

    def test_return_manager_refuses_low_or_unknown_quota(self):
        w,step=self.manager_run()
        for remaining in (None,0,19):
            with patch.object(self.q,'argon_headroom',return_value=remaining):
                with self.assertRaises(HubError):self.w.project_return_manager('deepseek',step['run_id'],'return')

    def test_quota_drop_after_return_request_cancels_request_without_deadlock(self):
        w,step=self.manager_run()
        with patch.object(self.q,'argon_headroom',return_value=80):self.w.project_return_manager('deepseek',step['run_id'],'return')
        with patch.object(self.q,'argon_headroom',return_value=5):self.q.return_manager(self.w.snapshot('user')[0])
        current=self.w.snapshot('user')[0];self.assertEqual(current['manager'],'deepseek');self.assertNotIn('return_manager',current)

    def test_argon_recovery_encourages_safe_handoff(self):
        w,step=self.manager_run()
        with patch.object(self.q,'argon_headroom',return_value=80):
            self.q.observe(self.sample(0));self.q.observe(self.sample(80))
        event=json.loads(self.h.db.execute('SELECT body FROM workflow_events ORDER BY created DESC LIMIT 1').fetchone()[0])
        self.assertEqual(event['transition'],'recovered');self.assertIn('project_return_manager',event['body'])
        self.assertEqual(event['recipients'],['argon','deepseek'])
        self.assertEqual(self.w.snapshot('user')[0]['manager'],'deepseek')

    def test_return_tool_ends_round_without_extra_paid_request(self):
        self.configure(budget_cents=1);w,step=self.manager_run()
        run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(step['run_id'],)).fetchone())
        self.api.answers=[self.tool_answer('project_return_manager',{'summary':'Argon restored, return management'})]
        with patch.object(self.q,'argon_headroom',return_value=80):
            self.d.execute(run)
            self.assertEqual(self.h.db.execute('SELECT status FROM executions WHERE id=?',(run['id'],)).fetchone()[0],'completed')
            self.assertEqual(len([p for p,d in self.api.requests if p=='/chat/completions']),1)
            self.w.patrol();self.q.return_manager(self.w.snapshot('user')[0])
        self.assertEqual(self.w.snapshot('user')[0]['manager'],'argon')

    def test_project_child_scope_keeps_independent_paid_limits(self):
        old=self.configure(budget_cents=20,max_seconds=1200)
        child=Path(self.tmp.name)/'child';child.mkdir()
        with self.h.tx():self.h.db.execute('INSERT INTO deepseek_spend VALUES(?,?,?,?,?,?,?)',('prior',old['grant_id'],'prior-run',3,'returned',None,time.time()))
        cfg=self.d.configure('user',str(child),'workspace',2000,7200,True,True)
        self.assertEqual(cfg['cwd'],str(child.resolve()));self.assertEqual(cfg['max_runs'],100)
        self.assertEqual(cfg['max_seconds'],1200);self.assertEqual(cfg['budget_cents'],20)
        self.assertEqual(cfg['grant_id'],old['grant_id']);self.assertEqual(self.d.status('user')['reserved_cents'],3)
        with tempfile.TemporaryDirectory() as outside:
            with self.assertRaises(HubError):self.d.configure('user',outside,'workspace',2000,7200,True,True)

    def test_plan_approval_allows_project_totals_above_deepseek_grant(self):
        from hub.planning import Planning
        self.configure(budget_cents=20,max_seconds=1200)
        child=Path(self.tmp.name)/'child';child.mkdir()
        p=Planning(self.h,self.a,self.w)
        opts={'cwd':str(child),'agents':['sol-1','deepseek'],'max_calls':2000,'expires_minutes':60,'max_parallel':3,'max_seconds':7200,'reviewer':'argon','auto_wake':True,'delegate_stop':False,'max_hops':4,'max_messages':100}
        s=p.message('user','build',opts,confirmed=True)
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='completed',result=? WHERE id=?",(json.dumps({'done':False,'report':'approved','tasks':[{'agent':'sol-1','instruction':'build'}]}),s['pending']))
        p.patrol();s=p.get(s['id']);p.message('user','按计划执行',opts,s['id'],s['revision'])
        self.assertEqual(self.w.snapshot('user')[0]['max_calls'],2000)
        self.assertEqual(self.d.config()['max_runs'],100);self.assertEqual(self.d.config()['max_seconds'],1200)
        self.assertEqual(self.d.config()['budget_cents'],20)


if __name__=='__main__':unittest.main()
