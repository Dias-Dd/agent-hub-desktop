import json,tempfile,threading,unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
from module_fixture import implementation
from hub.core import Hub,HubError
from hub.codex_runtime import CodexRuntime
from hub.antigravity import AntigravityRuntime
from hub.deepseek_runtime import DeepSeekRuntime
from hub.workflows import Workflows
from hub.coordination import Coordination
from hub.integrations import Integrations

class RegistryTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();h=Hub(self.temp.name)
  c=CodexRuntime(h);a=AntigravityRuntime(h);d=DeepSeekRuntime(h);c.models={};a.models={}
  w=Workflows(h,[c,a,d]);co=Coordination(h,[c,a,d],w)
  self.server=SimpleNamespace(hub=h,codex=c,antigravity=a,deepseek=d,workflows=w,coordination=co)
  self.registry=Integrations(self.server);h.integrations=self.registry
 def tearDown(self):self.registry.close();self.server.hub.db.close();self.temp.cleanup()
 def connection(self,kind='opencode',enabled=False):return self.registry.save_connection('user',{'name':kind+' test','kind':kind,'cwd':self.temp.name,'enabled':enabled,'permission':'full'},confirmed=enabled)
 def agent(self,c,name='Gemini worker',model='google/gemini-3.8-flash'):
  return self.registry.save_agent('user',{'name':name,'connection_id':c['id'],'model':model,'effort':'default','role':'工程师','enabled':True})
 def test_antigravity_encoded_tier_repairs_old_catalog_and_profile(self):
  c=self.connection('antigravity');c['models']=[{'id':'claude-opus-5-5-low','efforts':['medium']}]
  self.registry.put('integration_connections',c)
  a=self.registry.save_agent('user',{'name':'Claude','connection_id':c['id'],'model':'claude-opus-5-5-low','effort':'medium','role':'工程师','enabled':True})
  self.assertEqual(a['effort'],'low')
  a['effort']='medium';self.registry.put('agent_profiles',a)
  self.registry.align_antigravity_efforts()
  self.assertEqual(self.registry.get('agent_profiles',a['id'])['effort'],'low')
  self.assertEqual(self.registry.get('integration_connections',c['id'])['models'][0]['efforts'],['low'])


 def test_project_manager_selection_persists_and_preserves_discussion(self):
  from hub.projects import Projects
  from hub.planning import Planning
  h=self.server.hub;planning=Planning(h,self.server.deepseek,self.server.workflows);h.planning=planning;projects=Projects(h)
  project=projects.create('user','manager test')
  session={'id':'test-session','project_id':project['id'],'manager':'deepseek-4','history':[{'role':'user','text':'keep me'}],'plan':{'report':'keep plan'}}
  planning.save(session)
  self.registry.set_manager('user',project['id'],'deepseek-2')
  saved=planning.get('test-session')
  self.assertEqual(saved['manager'],'deepseek-2');self.assertEqual(saved['history'],session['history']);self.assertEqual(saved['plan'],session['plan'])
  self.assertEqual(h.db.execute('SELECT value FROM settings WHERE key=?',('project_manager:'+project['id'],)).fetchone()[0],'deepseek-2')
  with self.assertRaises(HubError):self.registry.set_manager('deepseek-1',project['id'],'deepseek-3')
  with patch.object(self.registry,'busy',return_value=True):
   with self.assertRaises(HubError):self.registry.set_manager('user',project['id'],'deepseek-3')
  self.assertEqual(planning.get('test-session')['manager'],'deepseek-2')

 def setup_change_project(self):
  from hub.projects import Projects
  from hub.planning import Planning
  h=self.server.hub;h.planning=Planning(h,self.server.deepseek,self.server.workflows)
  return Projects(h).create('user','changes')['id']
 def test_changes_coalesce_net_state_and_survive_restart(self):
  project=self.setup_change_project();c=self.connection();a=self.agent(c)
  self.assertEqual(len(self.registry.changes(project)),0)
  self.registry.queue_change('__roster__',{'agents':[]},{'agents':[a['id']]},project)
  self.registry.set_effort('user','deepseek-1','low',project)
  self.registry.set_effort('user','deepseek-1','max',project)
  rows=self.registry.changes(project);self.assertEqual(len(rows),2)
  body=self.registry.change_text(rows)
  self.assertIn('允许调度的成员',body);self.assertIn('high → max',body);self.assertNotIn('→ low',body)
  reopened=Hub(self.temp.name,recover=False)
  try:self.assertEqual(reopened.db.execute('SELECT count(*) FROM agent_change_queue').fetchone()[0],2)
  finally:reopened.db.close()
  # Acknowledging an older read cannot erase a newer edit.
  self.registry.set_effort('user','deepseek-1','low',project)
  self.registry.acknowledge_changes(rows)
  self.assertEqual(len(self.registry.changes(project)),1)
  self.assertIn('high → low',self.registry.change_text(self.registry.changes(project)))
 def test_changes_debounce_single_event_and_route_to_current_manager(self):
  project=self.setup_change_project();self.registry.set_effort('user','deepseek-1','low',project);self.registry.set_effort('user','deepseek-2','max',project)
  w={'id':'fake-workflow','project_id':project,'manager':'deepseek-7','status':'active'}
  self.registry.flush_changes(w)
  self.assertEqual(self.server.hub.db.execute('SELECT count(*) FROM workflow_events').fetchone()[0],0)
  self.server.workflows.save({**w,'status':'paused'});self.registry.patrol_changes()
  self.assertEqual(len(self.registry.changes(project)),2)
  with self.server.hub.tx():self.server.hub.db.execute('UPDATE agent_change_queue SET updated=updated-6')
  self.server.workflows.save(w);self.registry.patrol_changes()
  self.assertEqual(len(self.registry.changes(project)),2) # idle projects retain passive notices
  with patch.object(self.registry,'project_is_running',return_value=True):self.registry.patrol_changes();self.registry.patrol_changes()
  self.assertEqual(len(self.registry.changes(project)),0)
  events=self.server.hub.db.execute('SELECT body FROM workflow_events').fetchall();self.assertEqual(len(events),1)
  event=json.loads(events[0][0]);message=self.server.hub.db.execute('SELECT recipient,body,project_id FROM messages WHERE id=?',(event['message_id'],)).fetchone()
  self.assertEqual(message['recipient'],'deepseek-7');self.assertEqual(message['project_id'],project)
  self.assertIn('deepseek-1',message['body']);self.assertIn('deepseek-2',message['body'])
 def test_inactive_changes_join_next_discussion_and_submission_failure_retains_them(self):
  project=self.setup_change_project();self.registry.set_effort('user','deepseek-1','low',project)
  planning=self.server.hub.planning
  with patch.object(self.server.deepseek,'submit',side_effect=HubError('provider unavailable')):
   with self.assertRaises(HubError):planning.message('user','discuss',project_id=project)
  self.assertEqual(len(self.registry.changes(project)),1)
  with patch.object(self.server.deepseek,'submit',return_value={'id':'fake-discussion-run'}) as submit:
   planning.message('user','discuss',project_id=project)
  self.assertIn('high → low',submit.call_args.args[2]);self.assertEqual(self.registry.changes(project),[])

 def test_reverted_changes_and_create_delete_do_not_notify(self):
  project=self.setup_change_project();self.registry.set_effort('user','deepseek-1','low',project);self.registry.set_effort('user','deepseek-1','high',project)
  self.assertEqual(self.registry.changes(project),[])
  c=self.connection();a=self.agent(c);self.registry.archive_agent('user',a['id'])
  self.assertTrue(any(not json.loads(r['after_json']).get('enabled',True) for r in self.registry.changes(project)))

 def test_migration_preserves_nine_and_default_route(self):
  self.assertEqual(len(self.registry.snapshot()['agents']),9)
  self.assertEqual(self.server.workflows.runtime('deepseek-4'),self.server.deepseek)
 def test_duplicate_models_multiple_platforms_and_more_than_nine(self):
  c=self.connection();other=self.connection()
  agents=[self.agent(c),self.agent(c),self.agent(other)]
  self.assertEqual(len({a['id'] for a in agents}),3)
  self.assertEqual(len(self.registry.snapshot()['agents']),12)
  self.assertNotEqual(self.server.workflows.runtime(agents[0]['id']).provider,self.server.workflows.runtime(agents[2]['id']).provider)
  self.server.hub.send('user','*','broadcast')
  self.assertEqual(self.server.hub.db.execute('SELECT count(*) FROM messages').fetchone()[0],12)
 def test_archive_below_nine_retains_history(self):
  self.server.hub.send('user','deepseek-1','retain history')
  self.registry.archive_agent('user','deepseek-1')
  self.assertEqual(sum(a['enabled'] for a in self.registry.snapshot()['agents']),8)
  self.assertEqual(self.server.hub.db.execute('SELECT count(*) FROM messages').fetchone()[0],1)
  self.assertNotIn('deepseek-1',self.server.deepseek.models)
  self.assertFalse(self.registry.archive_agent('user','deepseek-4')['enabled'])
 def test_identity_model_role_persist_restart(self):
  c=self.connection();a=self.agent(c);h=self.server.hub
  a.update(name='renamed',role='designer');self.registry.save_agent('user',a)
  reopened=Hub(self.temp.name,recover=False)
  try:self.assertEqual(reopened.agent(a['id'])['role'],'designer');self.assertEqual(reopened.agent(a['id'])['model'],a['model'])
  finally:reopened.db.close()
 def test_enabled_requires_confirmation_and_agent_only_authority(self):
  with self.assertRaises(HubError):self.registry.save_connection('user',{'name':'x','kind':'codex','enabled':True,'cwd':self.temp.name})
  with self.assertRaises(HubError):self.registry.save_connection('deepseek-4',{'name':'x','kind':'codex','cwd':self.temp.name})
 def test_busy_agent_not_rerouted(self):
  c=self.connection();a=self.agent(c)
  with self.server.hub.tx():self.server.hub.db.execute("INSERT INTO executions(id,agent,status,provider) VALUES('busy',?,'running',?)",(a['id'],'integration:'+c['id']))
  a['model']='other/model'
  with self.assertRaises(HubError):self.registry.save_agent('user',a)
 def test_opencode_catalog_probe_never_infers(self):
  c=self.connection()
  with patch('hub.integrations.locate',return_value='opencode.exe'),patch('hub.integrations.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout='google/gemini-a\nopenrouter/vendor/model\n')) as run:
   result=self.registry.probe('user',c['id'])
   self.assertEqual(len(result['models']),2);self.assertEqual(run.call_args.args[0],['opencode.exe','models'])
 def test_manual_quota_is_connection_shared_and_unknown_by_default(self):
  c=self.connection();self.agent(c);self.agent(c)
  self.assertIsNone(c['quota']['remaining']);q=self.registry.quota('user',c['id'],9,2000000000)
  self.assertEqual(q['source'],'manual');self.assertEqual(self.registry.get('integration_connections',c['id'])['quota']['remaining'],9)
 def test_legacy_agent_editor_effort_reaches_actual_harness(self):
  a=self.registry.get('agent_profiles','deepseek-2');a['effort']='low';self.registry.save_agent('user',a)
  self.assertEqual(self.server.deepseek.efforts()['deepseek-2'],'low')
 def test_wizard_uses_catalog_and_numbers_duplicate_models(self):
  c=self.connection();c['models']=[{'id':'google/gemini-test','efforts':['default','high']}]
  with self.server.hub.tx():self.registry.put('integration_connections',c)
  a=self.registry.wizard_add('user',c['id'],'google/gemini-test')
  b=self.registry.wizard_add('user',c['id'],'google/gemini-test')
  self.assertEqual(a['name'],'gemini-test 1');self.assertEqual(b['name'],'gemini-test 2');self.assertNotEqual(a['id'],b['id'])
  self.assertFalse(self.server.workflows.runtime(a['id']).config()['enabled'])
  with self.assertRaises(HubError):self.registry.wizard_add('user',c['id'],'invented/model')
 def test_wizard_enable_preserves_api_catalog_validation(self):
  c=self.connection('openrouter-api');c.update(models=[{'id':'test/model','efforts':['default']}],probed_at=123)
  with self.server.hub.tx():self.registry.put('integration_connections',c)
  a=self.registry.wizard_add('user',c['id'],'test/model','User name',True)
  rt=self.server.workflows.runtime(a['id']);self.assertTrue(rt.config()['enabled']);self.assertTrue(rt.saved_validation()['supported']);self.assertEqual(a['name'],'User name')
  self.assertEqual(self.server.hub.db.execute('SELECT count(*) FROM executions').fetchone()[0],0)
 def test_native_project_scope_does_not_erase_connection_limit(self):
  c=self.registry.save_connection('user',{'name':'Codex','kind':'codex','cwd':self.temp.name,'permission':'full','enabled':True,'call_limit':25},True)
  a=self.registry.save_agent('user',{'name':'GPT','role':'工程师','connection_id':c['id'],'model':'gpt-test','effort':'medium'})
  rt=self.server.workflows.runtime(a['id']);before=rt.config()['grant_id']
  rt.configure('user',self.temp.name,'full',0,7200,True,True)
  self.assertEqual(rt.config()['max_runs'],25);self.assertEqual(rt.config()['grant_id'],before)
 def test_distinct_sessions_by_agent_model_platform_project(self):
  c=self.connection();a=self.agent(c);b=self.agent(c);rt=self.server.workflows.runtime(a['id'])
  run={'agent':a['id'],'provider':rt.provider,'model':a['model'],'session_scope':'hub-project:p'}
  first=rt.sessions.key(run)
  for change in [{'agent':b['id']},{'model':'another/model'},{'provider':'another-connection'},{'session_scope':'hub-project:q'}]:self.assertNotEqual(first,rt.sessions.key({**run,**change}))
 def test_acp_round_trip_model_ack_and_persistent_resume(self):
  import time
  c=self.connection(enabled=True);a=self.agent(c);rt=self.server.workflows.runtime(a['id']);calls=[]
  class FakeACP:
   def __init__(self,argv,cwd,env,update,permission):self.update=update
   def request(self,method,params,guard=None,*args):
    if guard:guard()
    calls.append((method,params))
    if method=='initialize':return {'protocolVersion':1}
    if method=='session/new':return {'sessionId':'persistent-one'}
    if method=='session/set_config_option':return {'configOptions':[{'id':'model','currentValue':params['value']}]}
    if method=='session/prompt':self.update({'update':{'sessionUpdate':'agent_message_chunk','content':{'text':'test completed'}}});return {'stopReason':'end_turn','usage':{'totalTokens':4}}
    return {}
   def close(self):pass
  with patch.object(implementation(self.server.hub,'opencode'),'ACP',FakeACP),patch('hub.integrations.locate',return_value='opencode.exe'):
   for _ in range(2):
    job=rt.submit('user',a['id'],'say test completed',True,purpose='question',session_scope='hub-project:test')
    with self.server.hub.tx():self.server.hub.db.execute("UPDATE executions SET status='running',started=? WHERE id=?",(time.time(),job['id']))
    rt.execute(dict(self.server.hub.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone()))
    row=self.server.hub.db.execute('SELECT status,result FROM executions WHERE id=?',(job['id'],)).fetchone();self.assertEqual(row['status'],'completed',row['result']);self.assertEqual(row['result'],'test completed')
  self.assertEqual(sum(m=='session/new' for m,p in calls),1);self.assertEqual(sum(m=='session/load' for m,p in calls),1)
  self.assertEqual([p['value'] for m,p in calls if m=='session/set_config_option'],[a['model'],a['model']])
 def test_completed_manager_can_receive_provider_end_confirmation(self):
  import time
  c=self.connection(enabled=True);a=self.agent(c);rt=self.server.workflows.runtime(a['id'])
  job=rt.submit('user',a['id'],'task',True)
  self.server.workflows.save({'id':'finished','status':'completed','completion':{'run_id':job['id']}})
  with self.server.hub.tx():
   self.server.hub.db.execute("UPDATE executions SET status='running',started=? WHERE id=?",(time.time(),job['id']))
   self.server.hub.db.execute('INSERT INTO workflow_steps VALUES(?,?,?,?,?)',('finished',1,job['task_id'],a['id'],'review'))
  run=dict(self.server.hub.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone());rt.guard(run)

class HttpRegistryTests(unittest.TestCase):
 def test_real_server_state_and_action_support_dynamic_agents(self):
  from hub.server import build
  from urllib.request import Request,urlopen
  with tempfile.TemporaryDirectory() as p:
   s=build(p,0,False);t=threading.Thread(target=s.serve_forever);t.start();base='http://127.0.0.1:'+str(s.server_port)
   headers={'Authorization':'Bearer '+s.hub.tokens['user'],'Content-Type':'application/json'}
   try:
    def action(name,args):
     with urlopen(Request(base+'/api/action',json.dumps({'action':name,'args':args}).encode(),headers)) as r:return json.load(r)['result']
    c=action('integration_connection_save',{'connection':{'name':'OpenCode','kind':'opencode','cwd':p}})
    a=action('integration_agent_save',{'agent':{'name':'Additional Gemini','role':'工程师','connection_id':c['id'],'model':'google/model','effort':'default'}})
    c['models']=[{'id':'google/model','efforts':['default']}]
    with s.hub.tx():s.integrations.put('integration_connections',c)
    added=action('integration_wizard_add',{'connection_id':c['id'],'model':'google/model'})
    self.assertEqual(added['name'],'model 1')
    with urlopen(Request(base+'/api/state',headers=headers)) as r:state=json.load(r)
    self.assertEqual(len(state['agents']),11);self.assertEqual(len(state['integrations']['agents']),11)
    self.assertIn(a['id'],[a['id'] for a in state['agents']])
    self.assertIn('timers',state);self.assertIn('shared_artifacts',state);self.assertIn('pending_notifications',state)
    project=s.projects.create('user','preview')
    page=Path(p)/'preview.html';page.write_text('<h1>preserved preview</h1>',encoding='utf-8')
    with patch.object(s.workflows,'run_context',return_value=({'project_id':project['id'],'id':'fixture'},{'cwd':p})):
     item=s.automation.publish_artifact('deepseek-1','fake-run',str(page),'webpage')
    page.unlink()
    with urlopen(base+item['url']) as r:
     self.assertIn(b'preserved preview',r.read());self.assertIn("script-src 'none'",r.headers['Content-Security-Policy']);self.assertIn('sandbox',r.headers['Content-Security-Policy'])
    s.integrations.set_effort('user','deepseek-1','low',project['id'])
    with urlopen(Request(base+'/api/state',headers={**headers,'X-Hub-Project':project['id']})) as r:notifications=json.load(r)['pending_notifications']
    self.assertTrue(any('high → low' in n['body'] for n in notifications))

   finally:
    s.stop_event.set();s.worker.join(5);s.shutdown();t.join(5);s.quota_monitor.close();s.integrations.close();s.deepseek.close();s.codex.close();s.antigravity.close();s.server_close();s.hub.db.close();s.guard.close()
