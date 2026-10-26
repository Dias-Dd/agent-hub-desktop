import json,tempfile,time,unittest
from unittest.mock import patch
from hub.core import HubError
from hub.tart_bridge import TartBridge
from hub.peekaboo_guest import PeekabooGuest

class Bridge(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.b=TartBridge(self.temp.name)
  self.calls=[]
  self.patch=patch('hub.tart_accessibility.PeekabooGuest');self.provider=self.patch.start().return_value;self.addCleanup(self.patch.stop)
  self.provider.run.side_effect=self.run_driver
  self.ready=patch.object(self.b,'ax_probe',return_value={'ready':True});self.ready.start();self.addCleanup(self.ready.stop)
 def run_driver(self,args):
  self.calls.append(args)
  if args==['app','list']:return {'apps':[{'pid':123,'name':'Fixture','process_start_identity_decimal':'777'}]}
  if args[:2]==['window','list']:return {'windows':[{'window_id':42,'window_title':'Fixture'}]}
  if args[0]=='see':return {'snapshot_id':'ps1_'+'a'*32,'snapshot_reusable':True,'mutation_targeting_available':True,'ui_elements':[{'id':'e1','ax_role':'AXTextField','is_actionable':True,'is_value_settable':True}]}
  return {'effect':'confirmed','newValue':'中文'}
 def tree(self,agent='alice'):
  self.b.ax_work('p',agent,'vm','windows',{})
  return self.b.ax_work('p',agent,'vm','ui_tree',{'window_handle':42})
 def test_unicode_value_and_snapshot_consumed_before_dispatch(self):
  tree=self.tree();ident=tree['controls'][0]['element_id']
  result=self.b.ax_work('p','alice','vm','ui_set_value',{'window_handle':42,'element_id':ident,'value':'中文'})
  self.assertEqual(result['result']['newValue'],'中文');self.assertIn('--value=中文',self.calls[-1])
  with self.assertRaisesRegex(HubError,'已过期或已使用'):self.b.ax_work('p','alice','vm','ui_set_value',{'window_handle':42,'element_id':ident,'value':'again'})
 def test_wrong_agent_cannot_reuse_receipt_even_after_lease_release(self):
  ident=self.tree()['controls'][0]['element_id'];self.b.desktop_lease('p','alice','vm',release=True)
  self.b.ax_work('p','bob','vm','windows',{})
  with self.assertRaisesRegex(HubError,'不属于当前 Agent'):self.b.ax_work('p','bob','vm','ui_invoke',{'window_handle':42,'element_id':ident})
 def test_uncertain_provider_failure_never_replays(self):
  ident=self.tree()['controls'][0]['element_id'];original=self.provider.run.side_effect
  self.provider.run.side_effect=lambda args:(_ for _ in ()).throw(HubError('indeterminate')) if args[0]=='action' else original(args)
  with self.assertRaisesRegex(HubError,'indeterminate'):self.b.ax_work('p','alice','vm','ui_invoke',{'window_handle':42,'element_id':ident})
  with self.assertRaisesRegex(HubError,'已过期或已使用'):self.b.ax_work('p','alice','vm','ui_invoke',{'window_handle':42,'element_id':ident})
 def test_permission_denial_does_not_list_windows(self):
  with patch.object(self.b,'ax_probe',return_value={'ready':False}):
   with self.assertRaisesRegex(HubError,'未就绪'):self.b.ax_work('p','alice','vm','windows',{})
  self.provider.run.assert_not_called()
 def test_recycled_pid_refuses_tree(self):
  self.b.ax_work('p','alice','vm','windows',{})
  self.provider.run.side_effect=lambda args:{'apps':[{'pid':123,'process_start_identity_decimal':'DIFFERENT'}]}
  with self.assertRaisesRegex(HubError,'进程已变化'):self.b.ax_work('p','alice','vm','ui_tree',{'window_handle':42})
 def test_partial_tree_is_readable_but_not_actionable(self):
  original=self.run_driver
  self.provider.run.side_effect=lambda args:{'snapshot_id':None,'snapshot_reusable':False,'mutation_targeting_available':False,'ui_elements':[{'id':'e1','is_actionable':True}]} if args[0]=='see' else original(args)
  tree=self.tree();self.assertFalse(tree['controls'][0]['is_actionable'])
  with self.assertRaisesRegex(HubError,'已过期或已使用'):self.b.ax_work('p','alice','vm','ui_invoke',{'window_handle':42,'element_id':tree['controls'][0]['element_id']})
 def test_expired_receipt_is_refused(self):
  ident=self.tree()['controls'][0]['element_id'];path=self.b.ax_directory()/(ident.split('_')[1]+'.json')
  value=json.loads(path.read_text());value['created']=time.time()-61;self.b.write(path,value)
  with self.assertRaisesRegex(HubError,'已过期或已使用'):self.b.ax_work('p','alice','vm','ui_invoke',{'window_handle':42,'element_id':ident})
 def test_install_is_user_confirmation_only(self):
  with self.assertRaises(HubError):self.b.control('peekaboo_install',vm_name='vm')
  with self.assertRaises(HubError):self.b.call('p','alice',self.temp.name,action='peekaboo_install')
