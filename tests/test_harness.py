import json,unittest
from pathlib import Path
from unittest.mock import patch
from module_fixture import implementation
from test_nine_deepseek import NineDeepSeek
from hub.deepseek_harness import patch_text,ACP
from hub.mcp import Protocol
from hub.core import HubError

class FakeACP:
 calls=[];stop='end_turn';model='["deepseek-official","deepseek-flash"]';missing=False;bad_permission=False;bad_root=False
 def __init__(self,argv,cwd,env,on_update,permission):
  self.redactions=[];self.update=on_update;self.permission=permission;self.closed=False;self.__class__.calls.append(('launch',permission))
  raw_patch=Path(argv[-1]).read_text(encoding='utf-8')
  self.__class__.calls.append(('system-patch',raw_patch))
  rows=[json.loads(line[2:]) for line in raw_patch.splitlines()]
  self.policy=next(x['config'] for row in rows for x in row.get('insert',[]) if x['id']=='hub-permission-sync')
  self.__class__.calls.append(('native-policy',self.policy['mode']))
  Path(self.policy['record']).write_text(json.dumps({'sessionId':'persistent-fixture','mode':'wrong' if self.bad_permission else self.policy['mode'],'workspaceRoot':cwd if self.bad_root else self.policy['workspaceRoot']}),encoding='utf-8')
 def clean(self,text):return text
 def request(self,method,params,guard=None,timeout=60):
  if guard:guard()
  self.__class__.calls.append((method,params))
  if method=='session/resume' and self.missing:raise HubError('session missing')
  if method=='initialize':return {'protocolVersion':1,'agentInfo':{'name':'deepseek-harness-acp'}}
  if method in ('session/new','session/resume'):return {'sessionId':'persistent-fixture','configOptions':[{'id':'model','currentValue':self.model},{'id':'reasoning_effort','currentValue':'high','options':[{'value':v} for v in ['off','low','high','max']]}]}
  if method=='session/set_config_option':return {'configOptions':[{'id':'reasoning_effort','currentValue':params['value']}]}
  return {}
 def begin(self,method,params):self.__class__.calls.append((method,params));return 42
 def wait(self,ident,guard=None,timeout=60):
  if guard:guard()
  self.update({'update':{'sessionUpdate':'agent_message_chunk','content':{'type':'text','text':'verified native harness answer'}}});return {'stopReason':self.stop}
 def notify(self,*args):pass
 def close(self):self.closed=True

class HarnessTests(unittest.TestCase):
 def setUp(self):
  self.f=NineDeepSeek();self.f.setUp();self.h=self.f.h;self.d=self.f.d
  self.adapter_module=implementation(self.h,'deepseek-harness')
  self.account_patch=patch.object(__import__(self.adapter_module.__package__+'.account',fromlist=['auth']),'auth',return_value=('deepseek-official',None,{'DEEPSEEK_API_KEY':'fixture-key-not-real'}));self.account_patch.start()
  cfg=self.d.config();cfg['engine']='harness'
  with self.h.tx():self.h.db.execute("update settings set value=? where key='deepseek_runtime'",(json.dumps(cfg),))
  self.d.key=lambda:'fixture-key-not-real';FakeACP.calls=[];FakeACP.stop='end_turn';FakeACP.model='["deepseek-official","deepseek-flash"]';FakeACP.missing=False;FakeACP.bad_permission=False;FakeACP.bad_root=False
 def tearDown(self):self.account_patch.stop();self.f.tearDown()
 def execute(self,purpose='question'):
  r=self.d.submit('user','deepseek-1','new input only',True,purpose=purpose,session_scope='hub-project:fixture')
  with patch.object(self.adapter_module,'ACP',FakeACP),patch.object(self.adapter_module,'installation',return_value=('fixture.exe','cli.js')):self.d.execute(self.f.running(r['id']))
  return dict(self.h.db.execute('select * from executions where id=?',(r['id'],)).fetchone())
 def test_logged_in_account_route_uses_account_models_without_api_key(self):
  self.h.url='http://127.0.0.1:8765'
  FakeACP.model='["deepseek-account","deepseek-flash"]'
  account=__import__(self.adapter_module.__package__+'.account',fromlist=['auth'])
  with patch.object(account,'auth',return_value=('deepseek-account',Path(self.f.t.name)/'official-credentials.yaml',{})):
   result=self.execute('task')
  self.assertEqual(result['status'],'completed',result.get('result'))
  policy=next(v for k,v in FakeACP.calls if k=='system-patch')
  self.assertIn('deepseek-account',policy)
  self.assertNotIn('fixture-key-not-real',policy)
 def test_selected_pro_reaches_execution_and_patch(self):
  self.h.url='http://127.0.0.1:8765'
  FakeACP.model='["deepseek-official","deepseek-v4-pro"]'
  with patch.dict(self.d.models,{'deepseek-1':'deepseek-v4-pro'}):result=self.execute()
  self.assertEqual(result['status'],'completed')
  self.assertEqual(result['model'],'deepseek-v4-pro')
  rows=[json.loads(line[2:]) for line in next(v for k,v in FakeACP.calls if k=='system-patch').splitlines()]
  self.assertEqual(next(r['config']['model'] for r in rows if r['id']=='acp'),'deepseek-v4-pro')

 def test_official_catalog_preserves_names_and_excludes_other_providers(self):
  from hub.deepseek_harness import catalog_entries
  view={'configOptions':[{'id':'model','options':[{'group':'official','options':[{'value':'["deepseek-official","deepseek-v4-pro"]','name':'DeepSeek-V4-Pro'},{'value':'["other","private"]'},{'value':'malformed'}]}]}]}
  self.assertEqual(catalog_entries(view),[{'id':'deepseek-v4-pro','name':'DeepSeek-V4-Pro','source':'official_acp','efforts':[]}])

 def test_execution_patch_teaches_vm_channel(self):
  self.h.url='http://127.0.0.1:8765'
  run=self.execute('task')
  self.assertEqual(run['status'],'completed')
  policy=[value for method,value in FakeACP.calls if method=='system-patch'][-1]
  self.assertIn('project_vm',policy);self.assertIn('command_elevated',policy)

 def test_uses_official_acp_and_resumes_without_replaying_history(self):
  self.h.url='http://127.0.0.1:8765'
  a=self.execute();b=self.execute();self.assertEqual(a['status'],'completed');self.assertEqual(b['thread_id'],a['thread_id'])
  self.assertEqual(sum(x[0]=='session/new' for x in FakeACP.calls),1);self.assertEqual(sum(x[0]=='session/resume' for x in FakeACP.calls),1)
  self.assertEqual(len(self.f.api.requests),1) # only fixture /models; no old API inference fallback
 def test_same_project_changed_directory_keeps_session(self):
  self.h.url="http://127.0.0.1:8765"
  a=self.execute()
  from pathlib import Path
  target=Path(self.d.config()['cwd'])/'moved';target.mkdir(exist_ok=True)
  cfg=self.d.config();cfg['cwd']=str(target)
  with self.h.tx():self.h.db.execute("update settings set value=? where key='deepseek_runtime'",(json.dumps(cfg),))
  b=self.execute()
  self.assertEqual(b['status'],'completed');self.assertEqual(a['thread_id'],b['thread_id'])
  resumed=[v for method,v in FakeACP.calls if method=='session/resume'][-1]
  self.assertEqual(resumed['cwd'],str(Path(a['cwd']).resolve()))
  self.assertEqual(sum(x[0]=='session/new' for x in FakeACP.calls),1)
 def test_workspace_directory_move_preserves_session_and_targets_sandbox(self):
  self.h.url='http://127.0.0.1:8765';a=self.execute()
  from pathlib import Path
  target=Path(self.d.config()['cwd'])/'new-workspace';target.mkdir()
  cfg=self.d.config();cfg.update(cwd=str(target),permission='workspace')
  with self.h.tx():self.h.db.execute("update settings set value=? where key='deepseek_runtime'",(json.dumps(cfg),))
  b=self.execute(purpose='task')
  self.assertEqual(b['status'],'completed');self.assertEqual(a['thread_id'],b['thread_id'])
  rows=[json.loads(line[2:]) for line in (self.h.directory/'harness/deepseek-1/hub.patch.yml').read_text(encoding='utf8').splitlines()]
  self.assertEqual(next(r['config']['workspaceRoot'] for r in rows if r['id']=='sandbox-policy'),str(target.resolve()))
 def test_wrong_actual_workspace_stops_before_model_request(self):
  self.h.url='http://127.0.0.1:8765';self.execute()
  target=Path(self.d.config()['cwd'])/'moved-bad';target.mkdir()
  cfg=self.d.config();cfg.update(cwd=str(target),permission='workspace')
  with self.h.tx():self.h.db.execute("UPDATE settings SET value=? WHERE key='deepseek_runtime'",(json.dumps(cfg),))
  FakeACP.bad_root=True;before=sum(m=='session/prompt' for m,v in FakeACP.calls)
  result=self.execute('task');self.assertEqual(result['status'],'failed');self.assertEqual(sum(m=='session/prompt' for m,v in FakeACP.calls),before)
 def test_effort_uses_official_config_before_prompt(self):
  self.h.url='http://127.0.0.1:8765';self.d.set_effort('user','deepseek-1','low');result=self.execute()
  self.assertEqual(result['status'],'completed')
  config_index=next(i for i,c in enumerate(FakeACP.calls) if c[0]=='session/set_config_option')
  prompt_index=next(i for i,c in enumerate(FakeACP.calls) if c[0]=='session/prompt')
  self.assertLess(config_index,prompt_index);self.assertEqual(FakeACP.calls[config_index][1]['value'],'low')
 def test_discussion_without_scope_does_not_inject_global_effort_list(self):
  self.h.url='http://127.0.0.1:8765';self.execute(purpose='discussion')
  patch_path=self.h.directory/'harness/deepseek-1/hub.patch.yml'
  self.assertNotIn('各 Agent 当前推理档位',patch_path.read_text(encoding='utf8'));self.assertIn('本轮未附项目成员快照',patch_path.read_text(encoding='utf8'))
  self.execute(purpose='task');self.assertNotIn('各 Agent 当前推理档位',patch_path.read_text(encoding='utf8'))
 def test_deferred_notice_retries_until_provider_confirms_turn(self):
  from hub.projects import Projects
  project=Projects(self.h).create('user','tier notice fixture');self.h.url='http://127.0.0.1:8765'
  self.d.set_effort('user','deepseek-2','max',project['id'])
  for stop in ['max_tokens','end_turn']:
   FakeACP.stop=stop
   run=self.d.submit('user','deepseek-4','继续',True,purpose='question',session_scope='hub-project:'+project['id'])
   with patch.object(self.adapter_module,'ACP',FakeACP),patch.object(self.adapter_module,'installation',return_value=('fixture.exe','cli.js')):self.d.execute(self.f.running(run['id']))
   result=dict(self.h.db.execute('select * from executions where id=?',(run['id'],)).fetchone())
   self.assertIn('档位变更：deepseek-2 high → max',result['actual_input'])
   pending=self.h.db.execute('select count(*) from agent_effort_notices where delivered is null').fetchone()[0]
   self.assertEqual(pending,1 if stop=='max_tokens' else 0)
 def test_incomplete_stop_is_not_falsely_completed(self):
  self.h.url='http://127.0.0.1:8765';FakeACP.stop='max_tokens';r=self.execute();self.assertEqual(r['status'],'uncertain')
 def test_discussion_has_no_tools_or_full_access(self):
  self.h.url='http://127.0.0.1:8765';r=self.execute('discussion');self.assertEqual(r['status'],'completed')
  args=next(v for m,v in FakeACP.calls if m=='session/new');self.assertEqual(args['mcpServers'],[]);self.assertFalse(next(v for m,v in FakeACP.calls if m=='launch'))
  text=patch_text('deepseek-4','manager',True);self.assertIn('tool-fs',text);self.assertIn('"disabled": true',text)
 def test_provider_cancel_is_interrupted_not_completed(self):
  self.h.url='http://127.0.0.1:8765';FakeACP.stop='cancelled';self.assertEqual(self.execute()['status'],'interrupted')
 def test_configuration_save_preserves_harness_engine(self):
  self.d.configure_api('user',self.f.t.name,'full',0,600,0,1,1,0,256,True,False,True)
  self.assertEqual(self.d.config()['engine'],'harness')
 def test_frozen_app_uses_console_python_mcp_bridge(self):
  self.h.url='http://127.0.0.1:8765'
  with patch('sys.frozen',True,create=True),patch.object(Path,'is_file',return_value=True),patch('sys.executable','C:/App/AgentMessageHubDesktop.exe'):
   self.assertEqual(self.execute('task')['status'],'completed')
  mount=next(v for m,v in FakeACP.calls if m=='session/new')['mcpServers'][0]
  self.assertEqual(Path(mount['command']).name,'AgentHubMcp.exe');self.assertEqual(mount['args'],[])
  self.assertTrue(any(x['name']=='HUB_RUN_ID' for x in mount['env']))
 def test_new_messages_are_not_wrapped_in_repeated_platform_prompt(self):
  self.h.url='http://127.0.0.1:8765';self.execute()
  message=next(v for m,v in FakeACP.calls if m=='session/prompt')['prompt'][0]['text']
  self.assertEqual(message,'new input only')
 def test_read_only_permission_request_never_auto_escalates(self):
  a=ACP.__new__(ACP);a.permission=False;responses=[];a.write=responses.append
  a.dispatch({'jsonrpc':'2.0','id':4,'method':'session/request_permission','params':{'options':[{'optionId':'allow','kind':'allow_once'},{'optionId':'deny','kind':'reject_once'}]}})
  self.assertEqual(responses[0]['result']['outcome']['optionId'],'deny')
 def test_wrong_model_does_not_fall_back_to_old_api(self):
  self.h.url='http://127.0.0.1:8765';FakeACP.model='["deepseek-official","deepseek-v4-pro"]'
  self.assertEqual(self.execute()['status'],'failed');self.assertEqual(len(self.f.api.requests),1)
 def test_missing_session_is_not_silently_replaced(self):
  self.h.url='http://127.0.0.1:8765';self.execute();FakeACP.missing=True
  self.assertEqual(self.execute()['status'],'failed')
  self.assertEqual(sum(m=='session/new' for m,v in FakeACP.calls),1)
 def test_mcp_rejects_tools_outside_per_run_allowlist(self):
  with patch.dict('os.environ',{'HUB_TOOL_ALLOWLIST':'["project_status"]','HUB_AGENT':'deepseek-4','HUB_RUN_ID':'run'},clear=False):
   p=Protocol();p.handle({'jsonrpc':'2.0','id':1,'method':'initialize','params':{}});p.handle({'jsonrpc':'2.0','method':'notifications/initialized'})
   listed=p.handle({'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}})
   self.assertEqual([x['name'] for x in listed['result']['tools']],['project_status'])
   answer=p.handle({'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'project_assign','arguments':{}}});self.assertTrue(answer['result']['isError'])

 def test_restored_session_switches_readonly_to_workspace_and_back(self):
  self.h.url='http://127.0.0.1:8765'
  first=self.execute('discussion');cfg=self.d.config();cfg['permission']='workspace'
  with self.h.tx():self.h.db.execute("update settings set value=? where key='deepseek_runtime'",(json.dumps(cfg),))
  second=self.execute('task');third=self.execute('question')
  self.assertEqual([first['thread_id'],second['thread_id'],third['thread_id']],['persistent-fixture']*3)
  self.assertEqual([v for m,v in FakeACP.calls if m=='native-policy'],['read-only','workspace-write','read-only'])
 def test_unconfirmed_session_permission_stops_before_model_prompt(self):
  self.h.url='http://127.0.0.1:8765';FakeACP.bad_permission=True
  result=self.execute('task');self.assertEqual(result['status'],'failed')
  self.assertFalse(any(m=='session/prompt' for m,v in FakeACP.calls))

 def manager_run(self):
  self.h.url='http://127.0.0.1:8765'
  w=self.f.w.start('user','Build approved app',['deepseek-2'],confirmed=True,manager='deepseek-1',reviewer='deepseek-1')
  step=self.f.w.steps(w['id'])[0]
  title=self.h.db.execute('SELECT title FROM tasks WHERE id=?',(step['task'],)).fetchone()[0]
  run=self.d.submit('user','deepseek-1',title,True,step['task'])
  return w,self.f.running(run['id'])
 def test_actual_project_manager_execution_reaches_native_harness_prompt(self):
  w,run=self.manager_run()
  with patch.object(self.adapter_module,'ACP',FakeACP),patch.object(self.adapter_module,'installation',return_value=('fixture.exe','cli.js')):self.d.execute(run)
  saved=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(run['id'],)).fetchone())
  self.assertEqual(saved['status'],'completed',saved['result']);self.assertTrue(any(m=='session/prompt' for m,v in FakeACP.calls))
  policy=(self.h.directory/'harness/deepseek-1/hub.patch.yml').read_text(encoding='utf8');self.assertIn('你是当前项目经理',policy)
 def test_local_manager_error_is_visible_redacted_and_does_not_trigger_retry(self):
  w,run=self.manager_run()
  with patch.object(self.adapter_module,'installation',return_value=('fixture.exe','cli.js')),patch('hub.execution_policy.project_manager',side_effect=NameError('undefined '+self.h.tokens['deepseek-1'])):self.d.execute(run)
  saved=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(run['id'],)).fetchone());self.assertIn('NameError',saved['result']);self.assertNotIn(self.h.tokens['deepseek-1'],saved['result'])
  event=json.loads(self.h.db.execute("SELECT data FROM execution_events WHERE run_id=? AND kind='deepseek.harness.internal_error'",(run['id'],)).fetchone()[0]);self.assertFalse(event['auto_retry']);self.assertTrue(event['location'])
  before=self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0]
  self.f.w.advance(w)
  saved_workflow=json.loads(self.h.db.execute('SELECT body FROM workflows WHERE id=?',(w['id'],)).fetchone()[0]);self.assertEqual(saved_workflow['status'],'blocked');self.assertEqual(saved_workflow['phase'],'adapter_error')
  self.assertEqual(self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0],before)


class SandboxPolicyConfig(unittest.TestCase):
 def test_native_policy_explicitly_matches_authorized_mode(self):
  for mode in ('read-only','workspace-write','danger-full-access'):
   rows=[json.loads(line[2:]) for line in patch_text('deepseek-2','frontend',workspace_root='C:/project',sandbox_mode=mode).splitlines()]
   config=next(x['config'] for x in rows if x['id']=='sandbox-policy')
   self.assertEqual(config,{'mode':mode,'workspaceRoot':'C:/project'})
 def test_invalid_native_policy_is_rejected(self):
  with self.assertRaises(HubError):patch_text('deepseek-2','frontend',sandbox_mode='allow-everything')
