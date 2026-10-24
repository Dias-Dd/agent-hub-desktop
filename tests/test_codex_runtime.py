import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from hub.core import Hub,HubError
from hub.codex_runtime import CodexRuntime,AppServer

class FakeAppServer:
    instances=[]
    def __init__(self,cwd):
        self.calls=[];self.events=[];self.closed=False;self.__class__.instances.append(self)
    def verify(self,model):self.model=model
    def rpc(self,method,params,timeout=25):
        self.calls.append((method,params))
        if method in ('thread/start','thread/resume'):return {'thread':{'id':'thread-test'},'model':params['model'],'modelProvider':'openai','approvalPolicy':'never','sandbox':{'type':'readOnly' if params['sandbox']=='read-only' else ('dangerFullAccess' if params['sandbox']=='danger-full-access' else 'workspaceWrite')}}
        if method=='turn/start':
            self.events=[{'method':'item/completed','params':{'threadId':'thread-test','item':{'type':'commandExecution','command':'python -m unittest','exitCode':0,'aggregatedOutput':'OK'}}},{'method':'item/completed','params':{'threadId':'thread-test','item':{'type':'fileChange','changes':[{'path':'module.py','kind':'add'}]}}},{'method':'item/completed','params':{'threadId':'thread-test','item':{'type':'agentMessage','text':'Implemented and tested.'}}},{'method':'thread/tokenUsage/updated','params':{'threadId':'thread-test','tokenUsage':{'total':{'totalTokens':123}}}},{'method':'turn/completed','params':{'threadId':'thread-test','turn':{'id':'turn-test','status':'completed'}}}]
            return {'turn':{'id':'turn-test','status':'inProgress'}}
        if method=='turn/interrupt':self.events=[{'method':'turn/completed','params':{'threadId':'thread-test','turn':{'id':'turn-test','status':'interrupted'}}}];return {}
        raise AssertionError(method)
    def event(self,timeout=.5):return self.events.pop(0) if self.events else None
    def write(self,value):pass
    def close(self):self.closed=True

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.h=Hub(self.temp.name);FakeAppServer.instances=[];self.r=CodexRuntime(self.h,FakeAppServer)
    def tearDown(self):self.r.close();self.h.db.close();self.temp.cleanup()
    def configure(self,runs=3):return self.r.configure('user',self.temp.name,'full',runs,60,True,True)
    def wait_run(self,run_id):
        until=time.monotonic()+5
        while time.monotonic()<until:
            run=next(x for x in self.r.snapshot('user')['runs'] if x['id']==run_id)
            if run['status'] not in ('queued','running','interrupting'):return run
            time.sleep(.01)
        self.fail('runtime did not finish')
    def test_long_result_keeps_json_prefix_and_full_payload(self):
        value=json.dumps({'done':False,'report':'说明'*10000,'tasks':[{'agent':'sol-1','instruction':'x'*6000}]},ensure_ascii=False)
        class LongResult(FakeAppServer):
            def rpc(self,method,params,timeout=25):
                result=super().rpc(method,params,timeout)
                if method=='turn/start':
                    for event in self.events:
                        item=event.get('params',{}).get('item',{})
                        if item.get('type')=='agentMessage':item['text']=value
                return result
        self.r.factory=LongResult;self.configure()
        job=self.r.submit('user','sol-1','fixture',True);self.r.start();run=self.wait_run(job['id'])
        self.assertEqual(run['status'],'completed');self.assertEqual(run['result'],value)

    def test_authorized_queue_reaches_official_payload_and_records_results(self):
        self.configure();run=self.r.submit('user','sol-1','implement module',True);self.r.start();done=self.wait_run(run['id'])
        self.assertEqual(done['status'],'completed');self.assertIn('Implemented',done['result'])
        rpc=dict(FakeAppServer.instances[0].calls)
        self.assertEqual(rpc['thread/start']['sandbox'],'danger-full-access');self.assertEqual(rpc['thread/start']['approvalPolicy'],'never')
        self.assertEqual(rpc['turn/start']['sandboxPolicy'],{'type':'dangerFullAccess'});self.assertEqual(rpc['turn/start']['effort'],'medium')
        self.assertEqual(next(t for t in self.h.snapshot('user')['tasks'] if t['id']==run['task_id'])['status'],'done')
        self.assertEqual({e['kind'] for e in self.r.snapshot('user')['events']},{'started','commandExecution','fileChange','agentMessage'})
        self.assertEqual(json.loads(done['usage'])['total']['totalTokens'],123)

    def test_permission_confirmation_budget_and_duplicate_guards(self):
        with self.assertRaises(HubError):self.r.submit('user','sol-1','work',True)
        with self.assertRaises(HubError):self.r.configure('astra',self.temp.name,'full',3,60,True,True)
        with self.assertRaises(HubError):self.r.configure('user',self.temp.name,'full',3,60,True,False)
        self.configure(1)
        with self.assertRaises(HubError):self.r.submit('user','sol-1','work',False)
        run=self.r.submit('user','sol-1','work',True)
        with self.assertRaises(HubError):self.r.submit('user','sol-2','more',True)
        self.r.stop('user',run['id']);self.assertEqual(self.r.snapshot('user')['remaining_runs'],1)
        self.assertEqual(self.h.snapshot('user')['tasks'][0]['status'],'blocked')

    def test_generic_task_needs_explicit_authorization_and_simulator_cannot_steal(self):
        self.configure();task=self.h.assign('argon','sol-2','review')['id'];self.h.tick(True,self.r.real_agents())
        self.assertEqual(self.h.snapshot('user')['tasks'][0]['status'],'assigned')
        with self.assertRaises(HubError):self.r.submit('user','sol-2','changed text',True,task)
        self.r.submit('user','sol-2','review',True,task)
        with self.assertRaises(HubError):self.r.submit('user','sol-2','review',True,task)

    def test_recovery_never_replays_running_task(self):
        self.configure();job=self.r.submit('user','astra','work',True)
        self.h.db.execute("UPDATE executions SET status='running' WHERE id=?",(job['id'],))
        self.h.db.close();self.h=Hub(self.temp.name);self.r=CodexRuntime(self.h,FakeAppServer)
        self.assertEqual(self.r.snapshot('user')['runs'][0]['status'],'uncertain')
        self.assertEqual(self.h.snapshot('user')['messages'][0]['status'],'uncertain')
        self.r.start();time.sleep(.1);self.assertFalse(FakeAppServer.instances)

    def test_interrupt_waits_for_provider_completion(self):
        class Waiting(FakeAppServer):
            started=threading.Event()
            def rpc(self,method,params,timeout=25):
                out=super().rpc(method,params,timeout)
                if method=='turn/start':self.events=[];self.started.set()
                return out
            def event(self,timeout=.5):
                time.sleep(.01);return super().event(timeout)
        self.r.factory=Waiting;self.configure();run=self.r.submit('user','sol-1','long work',True);self.r.start();self.assertTrue(Waiting.started.wait(2));self.r.stop('user',run['id'])
        self.assertEqual(self.wait_run(run['id'])['status'],'interrupted')
        self.assertEqual(self.h.snapshot('user')['tasks'][0]['status'],'blocked')

    def test_oauth_verification_refuses_api_key_and_absent_models(self):
        c=AppServer.__new__(AppServer);c.rpc=lambda *args,**kwargs:{'account':{'type':'apiKey'}}
        with self.assertRaises(HubError):c.verify('gpt-6.1-sol')
        c.rpc=lambda method,*args,**kwargs:{'account':{'type':'chatgpt'}} if method=='account/read' else {'data':[]}
        with self.assertRaises(HubError):c.verify('gpt-6.1-sol')

if __name__=='__main__':unittest.main()
