import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch
from hub.core import Hub, HubError
from hub.connectors import Calls, DeepSeek
from hub.server import build

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.h=Hub(self.temp.name)
    def tearDown(self):self.h.db.close();self.temp.cleanup()
    def msg(self,ident):return dict(self.h.db.execute('SELECT * FROM messages WHERE id=?',(ident,)).fetchone())

    def test_fixed_identities_and_prompts(self):
        state=self.h.snapshot('user');self.assertEqual(len(state['agents']),9)
        self.assertEqual(sum(a['model']=='Gemini 3.8 Flash' for a in state['agents']),3)
        self.assertTrue(all('MCP' in a['prompt'] for a in state['agents']))

    def test_queue_waits_immediate_preempts_and_resumes_without_pingpong(self):
        h=self.h;h.heartbeat('sol-1','idle')
        first=h.send('user','sol-1','first','immediate')[0];self.assertEqual(h.poll('sol-1')['id'],first);h.ack('sol-1',first)
        queued=h.send('user','sol-1','queued')[0];self.assertIsNone(h.poll('sol-1'))
        urgent=h.send('astra','sol-1','urgent','immediate')[0];self.assertEqual(h.poll('sol-1')['id'],urgent)
        self.assertEqual(self.msg(first)['status'],'paused');self.assertIsNone(h.poll('sol-1'))
        with self.assertRaises(HubError):h.ack('sol-1',first,True)
        h.ack('sol-1',urgent,True)
        self.assertEqual(h.poll('sol-1')['id'],queued);h.ack('sol-1',queued,True)
        self.assertEqual(h.poll('sol-1')['id'],first);h.ack('sol-1',first,True)
        self.assertEqual(h.ack('sol-1',first,True)['status'],'completed')

    def test_idempotency_and_atomic_broadcast(self):
        ids=self.h.send('user','*','hello',request_key='broadcast-1')
        self.assertEqual(len(ids),9);self.assertEqual(ids,self.h.send('user','*','hello',request_key='broadcast-1'))
        with self.assertRaises(HubError):self.h.send('user','*','different',request_key='broadcast-1')
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM messages').fetchone()[0],9)

    def test_concurrent_send_and_single_claim(self):
        h=self.h;h.heartbeat('flash-1','idle')
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            ids=list(pool.map(lambda _:h.send('user','flash-1','one',request_key='same')[0],range(30)))
        self.assertEqual(len(set(ids)),1)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda _:h.poll('flash-1'),range(12)))
        self.assertEqual(sum(r is not None for r in results),1)

    def test_permissions_and_private_messages(self):
        h=self.h
        with self.assertRaises(HubError):h.assign('flash-1','opus','bad')
        with self.assertRaises(HubError):h.project('user',10,'bad')
        with self.assertRaises(HubError):h.quota('astra','opus',10)
        h.send('user','opus','private')
        self.assertFalse(h.snapshot('flash-1')['messages'])
        self.assertEqual(h.snapshot('flash-1')['agents'][4]['quota']['source'],'restricted')
        self.assertEqual(h.snapshot('astra')['agents'][4]['quota']['source'],'unknown')
        with self.assertRaises(HubError):h.auth('bad')

    def test_assignment_own_progress_and_manager_report(self):
        h=self.h;task=h.assign('argon','opus','review')['id']
        self.assertEqual(len(h.snapshot('opus')['messages']),1)
        with self.assertRaises(HubError):h.progress('flash-1',task,20,'bad')
        with self.assertRaises(HubError):h.progress('opus',task,20,'bad','done')
        h.progress('opus',task,30,'reviewing');h.project('argon',15,'review underway')
        self.assertEqual(h.snapshot('user')['project']['progress'],15)

    def test_lease_expiry_and_heartbeat_renewal(self):
        h=self.h;h.heartbeat('opus','idle');ident=h.send('user','opus','test')[0];h.poll('opus');h.ack('opus',ident)
        h.db.execute('UPDATE messages SET lease=0 WHERE id=?',(ident,));h.heartbeat('opus','busy')
        h.tick(False);self.assertEqual(self.msg(ident)['status'],'acknowledged')
        h.db.execute('UPDATE messages SET lease=0 WHERE id=?',(ident,));h.tick(False)
        self.assertEqual(self.msg(ident)['status'],'pending');self.assertEqual(h.agent('opus')['status'],'offline')
        h.heartbeat('opus','idle');self.assertEqual(h.poll('opus')['id'],ident)

    def test_recovery_and_credentials_stability(self):
        h=self.h;h.heartbeat('opus','idle');ident=h.send('user','opus','recover')[0];h.poll('opus');h.ack('opus',ident)
        tokens=h.tokens.copy();h.db.close();self.h=Hub(self.temp.name)
        self.assertEqual(self.h.tokens,tokens);self.assertEqual(self.msg(ident)['status'],'pending')
        self.assertEqual(self.h.agent('opus')['status'],'offline')

    def test_manual_quota_never_assumes_reset(self):
        h=self.h;h.quota('user','opus',0,time.time()-1);h.tick(False)
        q=h.snapshot('user')['agents'][4]['quota'];self.assertEqual(q['remaining'],0);self.assertIn('尚未核实',q['recovery'])
        with self.assertRaises(HubError):h.quota('user','opus',float('nan'))

    def test_simulation_all_agents_wake_without_manager(self):
        h=self.h;h.send('user','*','offline end to end');h.tick()
        self.assertEqual(h.db.execute("SELECT count(*) FROM messages WHERE status='acknowledged'").fetchone()[0],9)
        h.db.execute('UPDATE messages SET delivered=0');h.tick()
        self.assertEqual(h.db.execute("SELECT count(*) FROM messages WHERE status='completed'").fetchone()[0],9)
        self.assertEqual(len([m for m in h.snapshot('user')['messages'] if m['recipient']=='user']),9)

class FakeDeepSeek:
    calls=0
    def models(self):return {'data':[{'id':'deepseek-flash'}]}
    def complete(self,prompt):self.calls+=1;return {'choices':[{'message':{'content':'test'}}],'usage':{'total_tokens':10}}

class BudgetTests(unittest.TestCase):
    setUp=CoreTests.setUp
    tearDown=CoreTests.tearDown
    def test_budget_approval_single_execution_and_uncertain_recovery(self):
        h=self.h;fake=FakeDeepSeek();calls=Calls(h,fake)
        ident=calls.prepare('deepseek','hello')['id']
        with self.assertRaises(HubError):calls.approve('deepseek',ident,1,100,100,True)
        with self.assertRaises(HubError):calls.approve('user',ident,1,100,100,True)
        calls.budget('user',2)
        with self.assertRaises(HubError):calls.approve('user',ident,1,100,100,False)
        calls.approve('user',ident,1,100,100,True)
        with patch.dict(os.environ,{'HUB_ALLOW_REAL':'0','DEEPSEEK_API_KEY':'fake'}):
            with self.assertRaises(HubError):calls.execute('user',ident)
        with patch.dict(os.environ,{'HUB_ALLOW_REAL':'1','DEEPSEEK_API_KEY':'fake'}):
            self.assertEqual(calls.execute('user',ident)['status'],'completed')
            with self.assertRaises(HubError):calls.execute('user',ident)
        self.assertEqual(fake.calls,1)
        two=calls.prepare('user','second')['id'];calls.approve('user',two,1,100,100,True)
        three=calls.prepare('user','third')['id']
        with self.assertRaises(HubError):calls.approve('user',three,1,100,100,True)
        h.db.execute("UPDATE calls SET status='running' WHERE id=?",(two,));h.db.close();self.h=Hub(self.temp.name)
        self.assertEqual(self.h.db.execute('SELECT status FROM calls WHERE id=?',(two,)).fetchone()[0],'uncertain')

    def test_parallel_approvals_cannot_overspend_and_expired_cannot_execute(self):
        calls=Calls(self.h,FakeDeepSeek());calls.budget('user',1)
        ids=[calls.prepare('user','hello')['id'] for _ in range(2)]
        def approve(ident):
            try:calls.approve('user',ident,1,100,100,True);return True
            except HubError:return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:out=list(pool.map(approve,ids))
        self.assertEqual(sum(out),1)
        approved=ids[out.index(True)]
        self.h.db.execute('UPDATE calls SET expires=0 WHERE id=?',(approved,))
        with patch.dict(os.environ,{'HUB_ALLOW_REAL':'1','DEEPSEEK_API_KEY':'fake'}):
            with self.assertRaises(HubError):calls.execute('user',approved)
        calls.cancel('user',approved)
        other=ids[out.index(False)];calls.approve('user',other,1,100,100,True)

    def test_network_failure_keeps_reservation_and_never_retries(self):
        fake=FakeDeepSeek();fake.complete=lambda _:(_ for _ in ()).throw(OSError('connection lost'))
        calls=Calls(self.h,fake);calls.budget('user',1);ident=calls.prepare('user','hello')['id'];calls.approve('user',ident,1,100,100,True)
        with patch.dict(os.environ,{'HUB_ALLOW_REAL':'1','DEEPSEEK_API_KEY':'fake'}):
            self.assertEqual(calls.execute('user',ident)['status'],'uncertain')
            with self.assertRaises(HubError):calls.execute('user',ident)
        another=calls.prepare('user','other')['id']
        with self.assertRaises(HubError):calls.approve('user',another,1,100,100,True)

    def test_official_deepseek_wire_payload_is_bounded(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*_):pass
            def read(self):return b'{"choices":[]}'
        seen=[]
        def open_request(req,timeout):seen.append(req);return Response()
        with patch.dict(os.environ,{'DEEPSEEK_API_KEY':'test-only'}),patch('urllib.request.urlopen',open_request):
            DeepSeek().complete('wire test')
        self.assertEqual(seen[0].full_url,'https://api.deepseek.com/chat/completions')
        payload=json.loads(seen[0].data);self.assertEqual(payload['model'],'deepseek-flash')
        self.assertEqual(payload['max_tokens'],256);self.assertEqual(payload['thinking']['type'],'disabled');self.assertNotIn('tools',payload)

class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.s=build(self.temp.name,0)
        self.thread=threading.Thread(target=self.s.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.s.server_address[1]);self.token=self.s.hub.tokens['user']
    def tearDown(self):
        self.s.shutdown();self.s.stop_event.set();self.s.worker.join(5);self.s.quota_monitor.close();self.s.deepseek.close();self.s.codex.close();self.s.antigravity.close();self.s.server_close();self.s.hub.db.close();self.s.guard.close();self.temp.cleanup()
    def request(self,path,body=None,headers=None):
        req=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body else None,headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json',**(headers or {})})
        return urllib.request.urlopen(req,timeout=5)
    def test_http_long_chinese_requirement_survives_json_escaping(self):
        self.s.stop_event.set();self.s.worker.join(5)
        self.s.quota_monitor.close();self.s.deepseek.close();self.s.codex.close();self.s.antigravity.close()
        for rt in (self.s.codex,self.s.antigravity):rt.configure('user',self.temp.name,'full',20,600,True,True)
        opts={'cwd':self.temp.name,'agents':['sol-1'],'max_calls':10,'expires_minutes':60,'max_parallel':1,'max_seconds':600,'reviewer':'argon','auto_wake':True,'delegate_stop':False,'max_hops':4,'max_messages':12}
        with self.request('/api/action',{'action':'plan_chat','args':{'body':'需求'*10000,'options':opts,'confirmed':True}}) as response:
            session=json.load(response)['result']
        self.assertEqual(session['history'][0]['text'],'需求'*10000)
        self.assertFalse(self.s.workflows.snapshot('user'))

    def test_http_simulated_assignment_dashboard_and_security(self):
        with self.request('/') as r:self.assertIn('Deskfellows',r.read().decode())
        with self.request('/api/action',{'action':'assign','args':{'agent':'flash-1','title':'HTTP E2E'}}) as r:task=json.load(r)['result']['id']
        deadline=time.monotonic()+6
        while time.monotonic()<deadline:
            with self.request('/api/state') as r:state=json.load(r)
            if next(t for t in state['tasks'] if t['id']==task)['status']=='done' and state['project']['progress']==100:break
            time.sleep(.1)
        self.assertEqual(state['tasks'][0]['status'],'done');self.assertEqual(state['project']['progress'],100)
        for headers in ({'Authorization':'Bearer wrong'},{'Origin':'https://evil.example'},{'Host':'evil.example'}):
            with self.assertRaises(urllib.error.HTTPError):self.request('/api/state',headers=headers)
        before=len(state['tasks'])
        with self.assertRaises(urllib.error.HTTPError):self.request('/wrong',{'action':'assign','args':{'agent':'opus','title':'should not mutate'}})
        self.assertEqual(len(self.s.hub.snapshot('user')['tasks']),before)
    def test_emergency_http_latch_resume_and_agent_permissions(self):
        with self.request('/api/action',{'action':'agent_halt','args':{'agent':'flash-1','reason':'HTTP test stop'}}) as r:self.assertTrue(json.load(r)['result']['latched'])
        with self.request('/api/state') as r:state=json.load(r)
        self.assertEqual(state['coordination']['stops'][0]['agent'],'flash-1')
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/action',{'action':'agent_halt','args':{'agent':'*','reason':'not allowed'}},{'Authorization':'Bearer '+self.s.hub.tokens['astra']})
        with self.request('/api/action',{'action':'agent_resume','args':{'agent':'flash-1'}}):pass
        self.assertFalse(self.s.coordination.is_stopped('flash-1'))
    def test_workflow_http_explicit_collaboration_options_are_persisted(self):
        self.s.quota_monitor.close();self.s.deepseek.close();self.s.codex.close();self.s.antigravity.close()
        for rt in (self.s.codex,self.s.antigravity):rt.configure('user',self.temp.name,'full',8,60,True,True)
        args={'requirement':'test project','agents':['sol-2','flash-3'],'max_calls':2000,'expires_minutes':10080,'max_parallel':3,'confirmed':True,'auto_wake':True,'reviewer':'flash-3','max_hops':2,'max_messages':5,'delegate_stop':False}
        with self.request('/api/action',{'action':'workflow_start','args':args}) as r:w=json.load(r)['result']
        self.assertEqual(w['reviewer'],'flash-3');self.assertEqual(w['max_hops'],2);self.assertFalse(w['delegate_stop'])
        with self.request('/api/action',{'action':'agent_halt','args':{'agent':'*','reason':'end test'}}):pass
        self.assertEqual(self.s.workflows.snapshot('user')[0]['status'],'stopped')
    def test_plan_chat_http_requires_user_approval_before_workflow_dispatch(self):
        self.s.quota_monitor.close();self.s.deepseek.close();self.s.codex.close();self.s.antigravity.close()
        for rt in (self.s.codex,self.s.antigravity):rt.configure('user',self.temp.name,'full',20,60,True,True)
        options={'cwd':self.temp.name,'agents':['sol-2'],'max_calls':5,'expires_minutes':100,'max_parallel':2,'max_seconds':60,'reviewer':'argon','auto_wake':True,'delegate_stop':False,'max_hops':4,'max_messages':12}
        with self.request('/api/action',{'action':'plan_chat','args':{'body':'build test','options':options,'confirmed':True}}) as r:s=json.load(r)['result']
        self.assertFalse(self.s.workflows.snapshot('user'))
        self.s.hub.db.execute("UPDATE executions SET status='completed',result=? WHERE id=?",(json.dumps({'done':False,'report':'reviewed plan','tasks':[{'agent':'sol-2','instruction':'approved work'}]}),s['pending']))
        self.s.planning.patrol();s=self.s.planning.get(s['id'])
        with self.request('/api/action',{'action':'plan_chat','args':{'body':'按计划执行','session_id':s['id'],'revision':s['revision'],'options':options}}) as r:self.assertEqual(json.load(r)['result']['state'],'executing')
        self.assertEqual(self.s.workflows.snapshot('user')[0]['steps'][0]['kind'],'work')
        with self.request('/api/action',{'action':'agent_halt','args':{'agent':'*','reason':'test complete'}}):pass
    def test_mcp_real_stdio_client(self):
        env={**os.environ,'HUB_URL':self.url,'HUB_TOKEN':self.s.hub.tokens['astra'],'PYTHONIOENCODING':'utf-8'}
        messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'test','version':'1'}}},{'jsonrpc':'2.0','method':'notifications/initialized'}, {'jsonrpc':'2.0','id':2,'method':'tools/list'}, {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'snapshot','arguments':{}}},{'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'assign','arguments':{'agent':'opus','title':'unauthorized'}}}]
        result=subprocess.run([sys.executable,'-m','hub.mcp'],input='\n'.join(json.dumps(m) for m in messages)+'\n',capture_output=True,text=True,encoding='utf-8',env=env,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr);lines=[json.loads(x) for x in result.stdout.splitlines()]
        self.assertEqual(len(lines),4);self.assertEqual(len(lines[1]['result']['tools']),17);self.assertIn('agent_halt',{t['name'] for t in lines[1]['result']['tools']})
        self.assertEqual(len(json.loads(lines[2]['result']['content'][0]['text'])['agents']),9)
        self.assertTrue(lines[3]['result']['isError'])

    def test_setup_http_status_save_and_static_route(self):
        with self.request('/setup') as response:self.assertIn('setupWizard',response.read().decode())
        with self.request('/setup.js') as response:self.assertIn('setup_save',response.read().decode())
        with self.request('/api/action',{'action':'setup_status','args':{}}) as response:self.assertIsNone(json.load(response)['result']['saved'])
        with self.request('/api/action',{'action':'setup_save','args':{'project_name':'HTTP 项目','route':'simulation','budget_cents':0,'confirmed':True}}) as response:self.assertEqual(json.load(response)['result']['project_name'],'HTTP 项目')

    def test_codex_authorized_http_queue_uses_runtime_not_simulation(self):
        from test_codex_runtime import FakeAppServer
        self.s.codex.factory=FakeAppServer
        with self.request('/api/action',{'action':'codex_configure','args':{'cwd':self.temp.name,'permission':'full','max_runs':1,'max_seconds':60,'confirmed':True}}) as response:self.assertEqual(json.load(response)['result']['permission'],'full')
        with self.request('/api/action',{'action':'codex_submit','args':{'agent':'sol-1','instruction':'HTTP real adapter test','confirmed':True}}) as response:run_id=json.load(response)['result']['id']
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            with self.request('/api/state') as response:state=json.load(response)
            run=next(r for r in state['codex']['runs'] if r['id']==run_id)
            if run['status']=='completed':break
            time.sleep(.05)
        self.assertEqual(run['status'],'completed');self.assertNotIn('模拟',run['result']);self.assertEqual(state['real_agents'],['astra','sol-1','sol-2'])

    def test_project_create_http_groups_messages_without_starting_models(self):
        with self.request('/api/action',{'action':'project_create','args':{'name':'separate project'}}) as response:p=json.load(response)['result']
        before=self.s.hub.db.execute('SELECT count(*) FROM executions').fetchone()[0]
        with self.request('/api/action',{'action':'send','args':{'recipient':'argon','body':'project private question'}},headers={'X-Hub-Project':p['id']}):pass
        with self.request('/api/state',headers={'X-Hub-Project':p['id']}) as response:state=json.load(response)
        self.assertEqual(state['selected_project'],p['id']);self.assertTrue(any(m['body']=='project private question' for m in state['messages']))
        self.assertEqual(before,self.s.hub.db.execute('SELECT count(*) FROM executions').fetchone()[0])

    def test_argon_completion_tool_over_real_mcp_stdio_and_http(self):
        self.s.stop_event.set();self.s.worker.join(5);self.s.quota_monitor.close();self.s.deepseek.close();self.s.codex.close();self.s.antigravity.close()
        for rt in (self.s.codex,self.s.antigravity):rt.configure('user',self.temp.name,'full',20,60,True,True)
        plan={'done':False,'report':'approved','tasks':[{'agent':'sol-1','instruction':'work and verify'}]}
        w=self.s.workflows.start('user','finish verified work',['sol-1'],max_calls=8,confirmed=True,approved_proposal=plan)
        self.s.workflows.patrol();s=self.s.workflows.steps(w['id'])[0]
        self.s.hub.db.execute("UPDATE executions SET status='completed',result=?,finished=? WHERE id=?",(json.dumps({'summary':'verified','risk':'low','evidence':['test passed']}),time.time(),s['run_id']))
        self.s.coordination.patrol();self.s.workflows.patrol();self.s.workflows.patrol();manager=self.s.workflows.steps(w['id'])[-1]
        self.s.hub.db.execute("UPDATE executions SET status='running' WHERE id=?",(manager['run_id'],))
        env={**os.environ,'HUB_URL':self.url,'HUB_TOKEN':self.s.hub.tokens['argon'],'HUB_RUN_ID':manager['run_id'],'HUB_AGENT':'argon','PYTHONIOENCODING':'utf-8'}
        messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'test','version':'1'}}},{'jsonrpc':'2.0','method':'notifications/initialized'},{'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'project_complete','arguments':{'summary':'verified completion','evidence':['test passed']}}}]
        result=subprocess.run([sys.executable,'-m','hub.mcp'],input='\n'.join(json.dumps(m) for m in messages)+'\n',capture_output=True,text=True,encoding='utf-8',env=env,timeout=10)
        lines=[json.loads(line) for line in result.stdout.splitlines()];self.assertFalse(lines[-1]['result']['isError']);self.assertEqual(self.s.workflows.snapshot('user')[0]['status'],'completed')

    def test_antigravity_http_configuration_and_real_stream_route(self):
        from test_antigravity import FakeProbe,FakeStream
        self.s.antigravity.probe=FakeProbe();self.s.antigravity.stream_factory=FakeStream
        with self.request('/api/action',{'action':'antigravity_configure','args':{'cwd':self.temp.name,'permission':'full','max_runs':1,'max_seconds':60,'confirmed':True}}) as response:self.assertTrue(json.load(response)['result']['enabled'])
        with self.request('/api/action',{'action':'refresh_antigravity','args':{}}) as response:self.assertEqual(json.load(response)['result']['quota_source'],'official_cli')
        with self.request('/api/action',{'action':'antigravity_submit','args':{'agent':'flash-1','instruction':'Gemini HTTP test','confirmed':True}}) as response:ident=json.load(response)['result']['id']
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            with self.request('/api/state') as response:state=json.load(response)
            run=next(r for r in state['antigravity']['runs'] if r['id']==ident)
            if run['status']=='completed':break
            time.sleep(.05)
        self.assertEqual(run['status'],'completed');self.assertEqual(run['provider'],'antigravity');self.assertFalse(state['codex']['runs'])

if __name__=='__main__':unittest.main()
