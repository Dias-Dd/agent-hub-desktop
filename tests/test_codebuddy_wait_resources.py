from module_fixture import implementation
import io,json,time,tempfile,unittest
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
import test_integrations as base
import test_coordination_repairs as repairs
from hub.integration_runtime import workbuddy_session_failure
from hub.task_resources import paths
from hub.manager_input import WAIT_POLICY,POLICY
from hub.workflows import Workflows

class CodeBuddyDirectory(unittest.TestCase):
 setUp=base.RegistryTests.setUp
 tearDown=base.RegistryTests.tearDown
 connection=base.RegistryTests.connection
 agent=base.RegistryTests.agent
 def job(self,rt,a,scope):
  job=rt.submit('user',a,'Create current project files',True,session_scope=scope)
  with self.server.hub.tx():self.server.hub.db.execute("UPDATE executions SET status='running',started=? WHERE id=?",(time.time(),job['id']))
  return dict(self.server.hub.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone())
 def test_resume_from_original_directory_and_add_current_workspace(self):
  c=self.connection('workbuddy',True);a=self.agent(c,model='hy3');rt=self.server.workflows.runtime(a['id']);h=self.server.hub
  old=Path(self.temp.name)/'draft';old.mkdir();first=self.job(rt,a['id'],'hub-project:one');first['cwd']=str(old)
  with h.tx():h.db.execute("UPDATE executions SET cwd=?,thread_id='keep-context',status='completed' WHERE id=?",(str(old),first['id']))
  rt.sessions.bind(first,'keep-context',cwd=str(old));run=self.job(rt,a['id'],'hub-project:one')
  class Input(io.StringIO):
   def close(self):pass
  proc=SimpleNamespace(pid=42,stdin=Input(),stdout=io.StringIO('null\n[]\n'+json.dumps({'type':'assistant','message':None})+'\n'+json.dumps({'type':'result','session_id':'keep-context','result':'done'})+'\n'),stderr=io.StringIO(''),wait=lambda **k:0,poll=lambda:0)
  with patch('hub.integrations.locate',return_value='codebuddy.cmd'),patch('hub.integrations.command',side_effect=lambda x:x),patch('hub.integration_runtime.subprocess.Popen',return_value=proc) as spawn,patch.object(implementation(h,'workbuddy'),'ProcessJob',return_value=SimpleNamespace(close=lambda:None)),patch.object(rt,'track_client'):
   rt.execute(run)
  argv=spawn.call_args.args[0];self.assertEqual(spawn.call_args.kwargs['cwd'],str(old));self.assertEqual(argv[argv.index('--resume')+1],'keep-context');self.assertEqual(argv[argv.index('--add-dir')+1],str(Path(run['cwd']).resolve()))
  delivered=json.loads(proc.stdin.getvalue())['message']['content'];self.assertIn(str(old),delivered);self.assertIn(str(Path(run['cwd']).resolve()),delivered);self.assertIn('--input-format',argv)
  self.assertEqual(rt.sessions.get(run)['session_id'],'keep-context');self.assertEqual(rt.sessions.get(run)['cwd'],str(old))
  self.assertEqual(h.db.execute('SELECT status FROM executions WHERE id=?',(run['id'],)).fetchone()[0],'completed')
  self.assertIsNone(rt.sessions.get({**run,'session_scope':'hub-project:other'}))
 def test_startup_failure_retains_cause_and_stage(self):
  c=self.connection('workbuddy',True);a=self.agent(c,model='hy3');rt=self.server.workflows.runtime(a['id']);run=self.job(rt,a['id'],'hub-project:startup')
  with patch('hub.integrations.locate',return_value='codebuddy.cmd'),patch('hub.integrations.command',side_effect=lambda x:x),patch('hub.integration_runtime.subprocess.Popen',side_effect=OSError(6,'Invalid handle')):
   rt.execute(run)
  result=self.server.hub.db.execute('SELECT result FROM executions WHERE id=?',(run['id'],)).fetchone()[0]
  self.assertIn('Invalid handle',result);self.assertIn('启动 CLI 进程',result)
  self.assertTrue(self.server.hub.db.execute("SELECT 1 FROM execution_events WHERE run_id=? AND kind='integration.failure'",(run['id'],)).fetchone())

 def test_correlate_detached_cli_error_without_leaking_logs_or_old_failures(self):
  root=Path(self.temp.name)/'.codebuddy/logs'/datetime.now().strftime('%Y-%m-%d');root.mkdir(parents=True);log=root/'project.log';now=time.time();stamp=datetime.fromtimestamp(now).strftime('%Y/%m/%d %H:%M:%S.%f')[:-3]
  log.write_text('['+stamp+'] [Error] [pid=999] SessionNotFoundError: No conversation found with session ID: keep-context\nSECRET_OTHER_LOG_CONTENT',encoding='utf8')
  __import__('os').utime(log,(now+1,now+1))
  result=workbuddy_session_failure('keep-context',now,self.temp.name);self.assertIn('SessionNotFoundError',result);self.assertNotIn('SECRET',result)
  self.assertIsNone(workbuddy_session_failure('different-context',now,self.temp.name));self.assertIsNone(workbuddy_session_failure('keep-context',now+20,self.temp.name))

class ResourceWaitRepair(unittest.TestCase):
 def setUp(self):
  self.f=repairs.CoordinationRepairs();self.f.setUp();self.h=self.f.h;self.w=self.f.w;self.project=self.f.project
 def tearDown(self):self.f.tearDown()
 def test_dotnet_file_paths_are_recognized(self):
  self.assertEqual(paths('src/App.xaml.cs src/App.xaml WeatherApp.sln src/Weather.csproj scripts/build.ps1'),['scripts/build.ps1','src/app.xaml','src/app.xaml.cs','src/weather.csproj','weatherapp.sln'])
 def setup_followup(self):
  first=self.f.dispatch('deepseek-1','src/SearchPage.xaml');run=self.f.submit(first)
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='completed' WHERE id=?",(run['id'],))
  other=self.f.dispatch('deepseek-2','src/SettingsPage.xaml');self.f.submit(other)
  mid=self.h.send('deepseek-4','deepseek-1','Interface confirmed. Finish your assigned files.')[0]
  follow=self.w.add_step(self.project,'deepseek-1','message','Interface confirmed. Finish your assigned files.',source_message_id=mid);self.f.d.submit('user','deepseek-1','Interface confirmed. Finish your assigned files.',True,follow,source_message_id=mid)
  with self.h.tx():self.h.db.execute('INSERT OR REPLACE INTO wakeups VALUES(?,?,?,?,?,?,?)',(mid,self.project['id'],follow,mid,1,'queued','manager followup'))
  shell=self.f.dispatch('deepseek-3','src/App.xaml');self.f.submit(shell)
  return follow,shell,other
 def test_manager_followup_retains_original_files_without_serializing_unrelated_work(self):
  follow,shell,other=self.setup_followup()
  self.assertEqual(json.loads(self.h.db.execute('SELECT paths FROM workflow_resources WHERE task=?',(follow,)).fetchone()[0]),['src/searchpage.xaml'])
  self.assertFalse(self.h.db.execute('SELECT 1 FROM workflow_resource_dependencies WHERE task IN (?,?)',(follow,shell)).fetchone())
  conflict=self.f.dispatch('deepseek-2','src/SearchPage.xaml')
  self.assertTrue(self.h.db.execute('SELECT 1 FROM workflow_resource_dependencies WHERE task=? AND depends_on=?',(conflict,follow)).fetchone())
 def test_startup_rebuilds_only_queued_resource_dependencies_and_keeps_explicit_files(self):
  follow,shell,other=self.setup_followup()
  with self.h.tx():
   self.h.db.execute('UPDATE workflow_resources SET paths=? WHERE task=?',(json.dumps(['*']),follow))
   self.h.db.execute('INSERT OR IGNORE INTO workflow_resource_dependencies VALUES(?,?)',(follow,other));self.h.db.execute('INSERT OR IGNORE INTO workflow_resource_dependencies VALUES(?,?)',(shell,follow))
  Workflows(self.h,[self.f.d,self.f.f.c,self.f.f.a])
  self.assertFalse(self.h.db.execute('SELECT 1 FROM workflow_resource_dependencies WHERE task IN (?,?)',(follow,shell)).fetchone())
  self.assertEqual(json.loads(self.h.db.execute('SELECT paths FROM workflow_resources WHERE task=?',(shell,)).fetchone()[0]),['src/app.xaml'])
 def test_manager_wait_policy_is_explicit_and_shared(self):
  self.assertIn('schedule_wake',WAIT_POLICY);self.assertIn('Start-Sleep',WAIT_POLICY);self.assertIn(WAIT_POLICY,POLICY)
