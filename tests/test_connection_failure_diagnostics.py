import io,json,unittest,tempfile,time
from pathlib import Path
from datetime import datetime
from unittest.mock import patch
from hub.antigravity import AntigravityStream
from hub.integration_runtime import cli_failure,workbuddy_auth_failure
from hub.connection_tests import failure_kind
class NonClosing(io.StringIO):
 def close(self):pass
class Proc:
 def __init__(self,*args,**kwargs):self.stdin=NonClosing();self.stdout=io.StringIO('');self.stderr=io.StringIO('');self.pid=0
 def poll(self):return 0
 def wait(self,timeout=None):return 0
class Job:
 def __init__(self,proc):pass
 def close(self):pass
class Diagnostics(unittest.TestCase):
 def test_real_antigravity_stream_constructor_does_not_assume_database_owner(self):
  run={'id':'fixture','cwd':'.','model':'gemini-test','max_seconds':30,'purpose':'question','prompt':'连接成功','_executable':'fake'}
  with patch('hub.antigravity.subprocess.Popen',Proc),patch('hub.antigravity.ProcessJob',Job):
   stream=AntigravityStream(run,'test only')
   try:self.assertIn('连接成功',json.loads(stream.proc.stdin.getvalue())['message']['content'])
   finally:stream.close()
 def test_provider_final_error_is_retained_and_secret_removed(self):
  message=cli_failure({'is_error':True,'error':'Authentication required secret-value'},0,[],{'HUB_TOKEN':'secret-value'})
  self.assertIn('Authentication required',message);self.assertNotIn('secret-value',message);self.assertEqual(failure_kind(message),'auth_required')
 def test_stderr_diagnostics_when_cli_exits_without_final_result(self):
  message=cli_failure(None,0,['Authentication required. Please use /login'])
  self.assertIn('/login',message);self.assertIn('退出码 0',message)
 def test_rate_limit_does_not_claim_concurrency_or_auth_failure(self):
  self.assertEqual(failure_kind('Rate limit exceeded. Please try again later.'),'rate_limited')
  self.assertEqual(failure_kind("object has no attribute 'hub'"),'adapter_error')
  self.assertEqual(failure_kind('insufficient_quota'),'quota_exhausted');self.assertIsNone(failure_kind('unknown error'))

 def test_workbuddy_log_fallback_matches_child_pid_not_other_account_diagnostics(self):
  with tempfile.TemporaryDirectory() as home:
   folder=Path(home)/'.codebuddy/logs'/datetime.now().strftime('%Y-%m-%d');folder.mkdir(parents=True)
   log=folder/'fixture.log';log.write_text('[pid=99] Authentication required. Please use /login command',encoding='utf8')
   self.assertIsNone(workbuddy_auth_failure(42,time.time()-2,home))
   log.write_text('[pid=42] Authentication required. Please use /login command SECRET',encoding='utf8')
   result=workbuddy_auth_failure(42,time.time()-2,home);self.assertIn('要求登录',result);self.assertNotIn('SECRET',result)

 def test_encoded_antigravity_tier_overrides_stale_effort(self):
  run={'id':'fixture','cwd':'.','model':'claude-opus-5-5-low','_effort':'medium','max_seconds':30,'purpose':'question','prompt':'test','_executable':'fake'}
  with patch('hub.antigravity.subprocess.Popen',side_effect=Proc) as launch,patch('hub.antigravity.ProcessJob',Job):
   stream=AntigravityStream(run,'test only')
   try:
    args=launch.call_args.args[0];self.assertEqual(args[args.index('--effort')+1],'low')
   finally:stream.close()
  self.assertEqual(failure_kind('invalid model selection: conflicts with --effort=medium'),'configuration_error')
 def test_unknown_model_does_not_get_invented_effort(self):
  from hub.antigravity import model_efforts,selected_effort
  self.assertEqual(model_efforts('claude-opus-5-5-high'),['high'])
  self.assertIsNone(selected_effort('future-model'))
