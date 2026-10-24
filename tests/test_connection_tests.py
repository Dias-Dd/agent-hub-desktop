import unittest,json,time
from unittest.mock import patch
from module_fixture import implementation
from hub.core import HubError
from hub.connection_tests import ConnectionTests
import test_integrations as base
class Tests(base.RegistryTests):
 def item(self,a):return {'id':a['id'],'name':a['name'],'model':a['model'],'effort':a['effort'],'connection_id':a['connection_id'],'batch':'fixture','status':'pending','created':time.time()}
 def test_confirmation_and_actor_required(self):
  with self.assertRaises(HubError):self.registry.test_all('user')
  with self.assertRaises(HubError):self.registry.test_all('deepseek-4',True)
  self.assertEqual(self.registry.connection_tests.snapshot(),{})
 def test_disabled_and_busy_skip_without_submit(self):
  c=self.connection();a=self.agent(c);rt=self.server.workflows.runtime(a['id']);item=self.item(a)
  with patch.object(rt,'submit') as submit:self.registry.connection_tests.test_one(item);submit.assert_not_called()
  self.assertEqual(item['status'],'skipped');self.assertIn('未启用',item['detail'])
  with patch.object(self.registry,'busy',return_value=True),patch.object(rt,'submit') as submit:self.registry.connection_tests.test_one(item);submit.assert_not_called()
  self.assertIn('不插队',item['detail'])
 def test_real_runtime_path_with_mock_acp_isolated_and_no_chat(self):
  c=self.connection(enabled=True);a=self.agent(c);rt=self.server.workflows.runtime(a['id']);item=self.item(a);calls=[]
  class FakeACP:
   def __init__(self,argv,cwd,env,update,permission):self.update=update;self.cwd=cwd
   def request(self,method,params,guard=None,*args):
    if guard:guard()
    calls.append((method,params))
    if method=='initialize':return {'protocolVersion':1}
    if method=='session/new':return {'sessionId':'probe-session'}
    if method=='session/set_config_option':return {'configOptions':[{'id':'model','currentValue':params['value']}]}
    if method=='session/prompt':self.update({'update':{'sessionUpdate':'agent_message_chunk','content':{'text':'连接成功'}}});return {'stopReason':'end_turn'}
    return {}
   def close(self):pass
  with patch.object(implementation(self.server.hub,'opencode'),'ACP',FakeACP),patch('hub.integrations.locate',return_value='opencode.exe'):
   rt.start();self.registry.connection_tests.test_one(item)
  self.assertEqual(item['status'],'passed');self.assertEqual(len([x for x in calls if x[0]=='session/prompt']),1)
  run=dict(self.server.hub.db.execute('SELECT * FROM executions WHERE id=?',(item['run_id'],)).fetchone())
  self.assertTrue(run['session_scope'].startswith('connection-test:'));self.assertIn('connection-tests',run['cwd']);self.assertEqual(run['purpose'],'question')
  self.assertEqual(self.server.hub.db.execute("SELECT count(*) FROM messages WHERE recipient='user'").fetchone()[0],0)
  self.assertNotEqual(rt.sessions.scope(run),rt.sessions.scope({**run,'session_scope':'hub-project:actual'}))
 def test_failure_is_not_retried_and_secret_redacted(self):
  c=self.connection(enabled=True);a=self.agent(c);rt=self.server.workflows.runtime(a['id']);item=self.item(a)
  with patch.dict('os.environ',{'EXAMPLE_API_KEY':'long-secret-value'}),patch.object(rt,'submit',side_effect=HubError('budget long-secret-value')) as submit:
   self.registry.connection_tests.test_one(item);self.assertEqual(submit.call_count,1)
  self.assertNotIn('long-secret-value',item['detail']);self.assertEqual(item['status'],'skipped')
 def test_restart_records_interruption_without_replay(self):
  a=self.registry.rows('agent_profiles')[0];item=self.item(a);item['status']='testing';self.registry.connection_tests.save(item)
  recovered=ConnectionTests(self.registry);self.assertEqual(recovered.snapshot()[a['id']]['status'],'interrupted');self.assertIsNone(recovered.thread)
