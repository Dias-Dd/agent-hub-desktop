import json,tempfile,threading,time,unittest
from hub.core import Hub
from hub.codex_runtime import CodexRuntime,QuotaWait
from hub.workflows import Workflows
from hub.antigravity import AntigravityRuntime
from test_codex_runtime import FakeAppServer
class ParallelTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.h=Hub(self.tmp.name);self.r=CodexRuntime(self.h,FakeAppServer);self.release=threading.Event()
    def tearDown(self):self.release.set();self.r.close();self.h.db.close();self.tmp.cleanup()
    def until(self,fn):
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            if fn():return
            time.sleep(.02)
        self.fail('condition not reached')
    def test_parallel_slots_skip_busy_identity_and_no_same_agent_overlap(self):
        release=self.release;started=[]
        class Waiting(FakeAppServer):
            def rpc(self,method,params,timeout=25):
                out=super().rpc(method,params,timeout)
                if method=='turn/start':started.append(params['input'][0]['text'])
                return out
            def event(self,timeout=.5):
                if not release.wait(.02):return None
                return super().event(timeout)
        self.r.factory=Waiting;self.r.configure('user',self.tmp.name,'full',1000,7200,True,True)
        self.h.db.execute("INSERT OR REPLACE INTO settings VALUES('max_parallel','2')")
        for agent,body in [('sol-1','first'),('sol-1','same identity'),('sol-2','independent')]:self.r.submit('user',agent,body,True)
        self.r.start();self.until(lambda:len(started)==2)
        self.assertEqual(set(started),{'first','independent'})
        with self.h.lock:rows=list(self.h.db.execute("SELECT agent FROM executions WHERE status='running'"))
        self.assertEqual({r[0] for r in rows},{'sol-1','sol-2'});self.assertEqual(len(self.r.clients),2)
        release.set();self.until(lambda:len(started)==3)
        self.until(lambda:all(r['status']=='completed' for r in self.r.snapshot('user')['runs']))
    def test_days_long_authorization_bounds_and_parallel_configuration(self):
        self.r.configure('user',self.tmp.name,'full',10000,86400,True,True)
        a=AntigravityRuntime(self.h);a.configure('user',self.tmp.name,'full',10000,86400,True,True)
        w=Workflows(self.h,[self.r,a]);p=w.start('user','large project',['sol-1','sol-2'],max_calls=5000,expires_minutes=7*1440,max_parallel=3,max_messages=1000,max_hops=16,confirmed=True)
        self.assertEqual(p['max_parallel'],3);self.assertGreater(p['expires']-p['created'],6.9*86400)
        self.assertEqual(self.h.db.execute("SELECT value FROM settings WHERE key='max_parallel'").fetchone()[0],'3')
        context=w.manager_prompt(p,[]);self.assertLessEqual(len(context),400);self.assertNotIn('gpt-6.1-sol',context);self.assertIn('sol-1',context)
    def test_codex_app_installation_is_found_without_path(self):
        from pathlib import Path
        from unittest.mock import patch
        from hub.codex_runtime import codex_executable
        binary=Path(self.tmp.name)/'OpenAI/Codex/bin/version/codex.exe';binary.parent.mkdir(parents=True);binary.write_bytes(b'fixture')
        with patch('hub.codex_runtime.shutil.which',return_value=None),patch.dict('os.environ',{'LOCALAPPDATA':self.tmp.name}):self.assertEqual(codex_executable(),str(binary))
    def test_quota_wait_persists_without_starting_a_model_turn(self):
        class Empty(FakeAppServer):
            def verify(self,model):raise QuotaWait(time.time()+120)
        self.r.factory=Empty;self.r.configure('user',self.tmp.name,'full',1000,7200,True,True)
        run=self.r.submit('user','sol-1','work',True);self.r.start()
        self.until(lambda:self.r.snapshot('user')['runs'][0]['status']=='waiting_quota')
        row=self.r.snapshot('user')['runs'][0];self.assertGreater(row['retry_after'],time.time()+60)
        self.assertFalse(any(method=='turn/start' for method,_ in FakeAppServer.instances[-1].calls))
if __name__=='__main__':unittest.main()
