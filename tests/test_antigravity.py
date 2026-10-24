import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from hub.core import Hub,HubError
from hub.antigravity import AntigravityRuntime,parse_usage,applicable_windows,environment,executable
from hub.codex_runtime import CodexRuntime
from test_codex_runtime import FakeAppServer

class FakeProbe:
    def __init__(self,claude=0):self.claude=claude
    def run(self):return {'installed':True,'models':[{'model':m} for m in ('gemini-3.8-flash-medium','gemini-4-argon-medium','claude-opus-5-5-medium')],'windows':[{'group':g,'window':w,'remaining':n,'resets_at':time.time()+300} for g,w,n in [('Gemini Models','Five Hour Limit Remaining',100),('Gemini Models','Weekly Limit Remaining',100),('Gemini 4 Argon','Gemini 4 Argon Weekly Limit',95),('Claude and GPT models','Five Hour Limit Remaining',self.claude)]],'quota_source':'official_cli','observed_at':time.time()}

class FakeStream:
    instances=[]
    def __init__(self,run,instructions):
        self.__class__.instances.append(self);self.closed=False
        self.events=[{'event':'init','conversation_id':'agy-conversation','init':{'model':run['model'],'cwd':run['cwd'],'permission_mode':'always-proceed'}},{'event':'step_update','step_update':{'state':'DONE','step_type':'tool','tool_name':'write_to_file','step_index':1}},{'event':'result','result':{'status':'SUCCESS','response':'Created files and tested.','usage':{'total_tokens':100}}}]
    def event(self):return self.events.pop(0) if self.events else None
    def wait(self):return 0
    def close(self):self.closed=True

class AntigravityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.h=Hub(self.temp.name);self.r=AntigravityRuntime(self.h,FakeStream,FakeProbe());FakeStream.instances=[]
    def tearDown(self):self.r.close();self.h.db.close();self.temp.cleanup()
    def configure(self):self.r.configure('user',self.temp.name,'full',3,60,True,True)
    def wait(self,ident,statuses):
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            run=next(r for r in self.r.snapshot('user')['runs'] if r['id']==ident)
            if run['status'] in statuses:return run
            time.sleep(.01)
        self.fail('runtime timeout')
    def test_malformed_tool_failure_is_not_success_or_automatic_retry(self):
        class BadTool(FakeStream):
            def __init__(self,run,instructions):
                super().__init__(run,instructions)
                self.events=[self.events[0],{'event':'result','result':{'status':'ERROR','error':'Malformed function call: Function call is empty - no input to parse.','denied_actions':[{'action':'mcp'}]}}]
        self.r.stream_factory=BadTool;self.configure()
        job=self.r.submit('user','flash-1','fixture',True)
        run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone());self.r.execute(run)
        stored=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone())
        self.assertEqual(stored['status'],'failed');self.assertIn('未自动重试',stored['result'])
        self.assertEqual(self.r.sessions.get(run)['session_id'],'agy-conversation')
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0],1)
        self.assertTrue(self.h.db.execute("SELECT 1 FROM execution_events WHERE run_id=? AND kind='antigravity.failure'",(run['id'],)).fetchone())

    def test_historical_error_is_promoted_only_with_transcript_evidence(self):
        from hub.antigravity_evidence import historical_error_evidence
        from datetime import datetime,timezone
        cid='b6f1259c-8576-47c8-a403-682596fd9715';error='Malformed function call: empty'
        transcript=Path(self.temp.name)/'exported.jsonl'
        class Historical(FakeStream):
            def __init__(self,run,instructions):
                super().__init__(run,instructions)
                stamp=datetime.now(timezone.utc).isoformat()
                rows=[{'step_index':1,'type':'ERROR_MESSAGE','source':'SYSTEM','status':'DONE','content':error},{'step_index':2,'type':'USER_INPUT','source':'USER_EXPLICIT','status':'DONE','created_at':stamp,'content':run['_wire_content']},{'step_index':3,'type':'GENERIC','source':'MODEL','status':'RUNNING','content':'background command'},{'step_index':4,'type':'PLANNER_RESPONSE','source':'MODEL','status':'DONE','content':'current complete answer'}]
                transcript.write_text(''.join(json.dumps(r)+'\n' for r in rows),encoding='utf-8')
                self.events=[{'event':'init','conversation_id':cid,'init':{'model':run['model'],'permission_mode':'always-proceed'}},{'event':'step_update','step_update':{'step_type':'tool','state':'DONE','step_index':3,'tool_name':'run_command'}},{'event':'result','result':{'conversation_id':cid,'status':'ERROR','response':'current complete answer','error':error}}]
        self.configure();self.r.stream_factory=Historical
        job=self.r.submit('user','flash-1','new input',True)
        run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone())
        self.r.sessions.bind(run,cid)
        with patch('hub.antigravity_evidence.historical_error_evidence',side_effect=lambda *args,**kwargs:historical_error_evidence(*args,transcript_path=transcript,**kwargs)):
            self.r.start();self.wait(run['id'],{'completed','failed','uncertain'})
        result=self.h.db.execute('SELECT status,result FROM executions WHERE id=?',(run['id'],)).fetchone()
        self.assertEqual(tuple(result),('completed','current complete answer'))
        self.assertTrue(self.h.db.execute("SELECT 1 FROM execution_events WHERE run_id=? AND kind='antigravity.historical_error_ignored'",(run['id'],)).fetchone())
        raw=json.loads(self.h.db.execute("SELECT data FROM execution_events WHERE run_id=? AND kind='antigravity.final_payload'",(run['id'],)).fetchone()[0]);self.assertEqual(raw['status'],'ERROR')

    def test_current_fatal_stderr_marker_prevents_historical_override(self):
        cid='b6f1259c-8576-47c8-a403-682596fd9715'
        class Fatal(FakeStream):
            current_fatal_error=True
            def __init__(self,run,instructions):
                super().__init__(run,instructions)
                self.events=[{'event':'init','conversation_id':cid,'init':{'model':run['model'],'permission_mode':'always-proceed'}},{'event':'result','result':{'conversation_id':cid,'status':'ERROR','response':'partial answer','error':'Malformed function call: empty'}}]
        self.configure();self.r.stream_factory=Fatal;job=self.r.submit('user','flash-1','new input',True)
        run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone());self.r.sessions.bind(run,cid)
        with patch('hub.antigravity_evidence.historical_error_evidence') as proof:
            self.r.execute(run);proof.assert_not_called()
        self.assertEqual(self.h.db.execute('SELECT status FROM executions WHERE id=?',(run['id'],)).fetchone()[0],'failed')

    def test_official_quota_parser_and_shared_groups(self):
        rows=parse_usage('Gemini Models\tFive Hour Limit Remaining\t100%\t2026-10-18T01:00:00Z\nClaude and GPT models\tFive Hour Limit Remaining\t0%\t2026-10-18T02:00:00Z\nunknown line')
        self.assertEqual(len(rows),2);self.assertEqual(applicable_windows({'windows':rows},'opus')[0]['remaining'],0)
        self.assertEqual(applicable_windows({'windows':rows},'flash-1')[0]['remaining'],100)
        self.assertFalse(parse_usage('Gemini Models\tFive Hour Limit Remaining\tNaN%\t2026-10-18T01:00:00Z'))
    def test_long_structured_response_is_not_silently_truncated(self):
        value=json.dumps({'done':False,'report':'计划'*10000,'tasks':[{'agent':'sol-1','instruction':'x'*6000}]},ensure_ascii=False)
        class LongResult(FakeStream):
            def __init__(self,run,instructions):
                super().__init__(run,instructions);self.events[-1]['result']['response']=value
        self.r.stream_factory=LongResult;self.configure()
        job=self.r.submit('user','flash-1','fixture',True);self.r.start();run=self.wait(job['id'],{'completed'})
        self.assertEqual(run['result'],value);self.assertEqual(len(json.loads(run['result'])['report']),20000)

    def test_google_execution_records_real_stream_and_usage(self):
        self.configure();job=self.r.submit('user','flash-1','implement',True);self.r.start();run=self.wait(job['id'],{'completed'})
        self.assertEqual(run['provider'],'antigravity');self.assertEqual(run['thread_id'],'agy-conversation');self.assertEqual(json.loads(run['usage'])['total_tokens'],100)
        self.assertTrue(FakeStream.instances[0].closed);self.assertEqual(self.h.snapshot('user')['tasks'][0]['status'],'done')
    def test_final_success_survives_local_exit_timeout(self):
        import subprocess
        class SlowExit(FakeStream):
            def wait(self):raise subprocess.TimeoutExpired('agy',10)
        self.r.stream_factory=SlowExit;self.configure()
        job=self.r.submit('user','flash-1','implement',True);self.r.start()
        run=self.wait(job['id'],{'completed'})
        self.assertEqual(run['result'],'Created files and tested.')
        self.assertTrue(self.h.db.execute("SELECT 1 FROM execution_events WHERE run_id=? AND kind='antigravity.final_payload'",(job['id'],)).fetchone())

    def test_exhausted_claude_waits_without_inference_or_busy_loop(self):
        self.configure();job=self.r.submit('user','opus','review',True);self.r.start();run=self.wait(job['id'],{'waiting_quota'})
        self.assertFalse(FakeStream.instances);self.assertGreater(run['retry_after'],time.time());time.sleep(.1)
        self.assertEqual(self.r.snapshot('user')['runs'][0]['status'],'waiting_quota')
        self.r.stop('user',job['id']);self.assertEqual(self.r.snapshot('user')['remaining_runs'],3)
    def test_mismatched_model_init_is_uncertain_not_success(self):
        class Wrong(FakeStream):
            def __init__(self,run,instructions):super().__init__(run,instructions);self.events[0]['init']['model']='wrong'
        self.r.stream_factory=Wrong;self.configure();job=self.r.submit('user','argon','plan',True);self.r.start()
        self.assertEqual(self.wait(job['id'],{'uncertain'})['status'],'uncertain')
    def test_provider_queues_are_isolated_and_use_one_global_slot(self):
        codex=CodexRuntime(self.h,FakeAppServer)
        try:
            self.configure();codex.configure('user',self.temp.name,'full',2,60,True,True)
            a=self.r.submit('user','flash-1','gemini',True);b=codex.submit('user','sol-1','openai',True)
            self.r.start();codex.start();self.wait(a['id'],{'completed'})
            deadline=time.monotonic()+4
            while time.monotonic()<deadline and codex.snapshot('user')['runs'][0]['status']!='completed':time.sleep(.01)
            self.assertEqual(codex.snapshot('user')['runs'][0]['id'],b['id']);self.assertEqual(codex.snapshot('user')['runs'][0]['status'],'completed')
            self.assertEqual(len(self.r.snapshot('user')['runs']),1);self.assertEqual(len(codex.snapshot('user')['runs']),1)
        finally:codex.close()
    def test_environment_excludes_api_billing_and_cli_discovery_fallback(self):
        with patch.dict('os.environ',{'GEMINI_API_KEY':'secret','GOOGLE_API_KEY':'secret','GOOGLE_APPLICATION_CREDENTIALS':'private.json'}):
            env=environment();self.assertNotIn('GEMINI_API_KEY',env);self.assertNotIn('GOOGLE_APPLICATION_CREDENTIALS',env)
        with self.assertRaises(HubError):self.r.configure('user',self.temp.name,'workspace',3,60,True,True)
    def test_unknown_quotas_never_start_model(self):
        probe=FakeProbe();original=probe.run
        probe.run=lambda:{**original(),'windows':[]};self.r.probe=probe
        self.configure();job=self.r.submit('user','flash-1','work',True);self.r.start();self.wait(job['id'],{'failed'})
        self.assertFalse(FakeStream.instances)

    def test_waiting_task_rechecks_official_quota_before_waking(self):
        self.configure();job=self.r.submit('user','opus','review',True);self.r.start();self.wait(job['id'],{'waiting_quota'})
        self.r.probe.claude=100
        with self.h.tx():self.h.db.execute('UPDATE executions SET retry_after=0 WHERE id=?',(job['id'],))
        self.assertEqual(self.wait(job['id'],{'completed'})['status'],'completed')
        self.assertEqual(len(FakeStream.instances),1)

    def test_official_region_error_is_failure_not_simulated_success(self):
        class RegionDenied(FakeStream):
            def __init__(self,run,instructions):
                super().__init__(run,instructions);self.events[-1]['result']={'status':'ERROR','error':'FAILED_PRECONDITION: User location is not supported for the API use.'}
        self.r.stream_factory=RegionDenied;self.configure();job=self.r.submit('user','flash-1','work',True);self.r.start();run=self.wait(job['id'],{'failed'})
        self.assertIn('location',run['result']);self.assertEqual(self.h.snapshot('user')['tasks'][0]['status'],'blocked')

if __name__=='__main__':unittest.main()
