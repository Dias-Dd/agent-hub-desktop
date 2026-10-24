import json
from unittest.mock import patch
from test_project_setup import ProjectSetup
from hub.quota_monitor import QuotaMonitor
from hub.core import HubError
class QuotaRosterMenu(ProjectSetup):
 def monitor(self):return QuotaMonitor(self.h,self.server.workflows,self.server.codex,self.server.antigravity,self.server.deepseek)
 def test_alert_cycles_preempt_urgencies_only_and_retain_notices(self):
  p=self.projects.create('user','quota');w={'id':'qw','project_id':p['id'],'manager':'deepseek-4','agents':['deepseek-1'],'status':'active'};self.server.workflows.save(w)
  monitor=self.monitor();sample={'id':'current:window','label':'Current account','agents':['deepseek-1'],'remaining':50,'resets_at':None}
  with patch.object(self.server.coordination,'prioritize') as preempt:
   for value in [50,9,8,0,0,90,9,0]:monitor.observe({**sample,'remaining':value})
   self.assertEqual(preempt.call_count,4)
  events=[json.loads(r[0]) for r in self.h.db.execute('SELECT body FROM workflow_events')];self.assertEqual(len(events),5);self.assertEqual(sum(e['type']=='quota_recovered' for e in events),1)
  self.assertEqual(self.h.db.execute("SELECT count(*) FROM messages WHERE sender='平台' AND mode='immediate'").fetchone()[0],4)
 def test_idle_paused_project_keeps_quota_notice_without_interrupt(self):
  p=self.projects.create('user','paused');self.server.workflows.save({'id':'pw','project_id':p['id'],'manager':'deepseek-4','agents':['deepseek-1'],'status':'paused'})
  with patch.object(self.server.coordination,'prioritize') as preempt:self.monitor().observe({'id':'x','label':'X','agents':['deepseek-4'],'remaining':0});preempt.assert_not_called()
  self.assertEqual(self.h.db.execute('SELECT count(*) FROM workflow_events').fetchone()[0],1)
 def test_new_agent_not_authorized_until_selected_and_membership_coalesces(self):
  p=self.projects.create('user','roster',options={'agents':[],'reviewer':'deepseek-4'})
  c=self.registry.save_connection('user',{'name':'Optional','kind':'opencode','cwd':self.temp.name,'enabled':False,'permission':'full'},confirmed=False)
  a=self.registry.save_agent('user',{'name':'Optional model','connection_id':c['id'],'model':'provider/test','effort':'default','role':'engineer','enabled':True})
  self.assertEqual(self.registry.changes(p['id']),[]);self.assertEqual(self.projects.get(p['id'])['options']['agents'],[])
  self.projects.update('user',p['id'],{'agents':[a['id']]});changes=self.registry.changes(p['id']);self.assertEqual(len(changes),1);self.assertEqual(changes[0]['agent'],'__roster__')
  self.registry.archive_agent('user',a['id']);self.assertNotIn(a['id'],self.projects.get(p['id'])['options']['agents'])
 def test_rename_retains_project_id_and_directory(self):
  p=self.projects.create('user','Before');after=self.projects.rename('user',p['id'],'After');self.assertEqual(after['id'],p['id']);self.assertEqual(after['cwd'],p['cwd']);self.assertEqual(after['name'],'After')
 def test_manager_immediate_scoped_and_calls_preempt(self):
  p=self.projects.create('user','Priority');w={'id':'w','project_id':p['id'],'manager':'deepseek-4','agents':['deepseek-1']}
  co=self.server.coordination
  with patch.object(co,'context',return_value=(w,{})),patch.object(co,'prioritize') as preempt,patch.object(co,'route'):
   ids=co.send('deepseek-4','deepseek-1','Urgent',mode='immediate',project_id=p['id']);preempt.assert_called_once();self.assertEqual(self.h.db.execute('SELECT mode FROM messages WHERE id=?',(ids[0],)).fetchone()[0],'immediate')
   with self.assertRaises(HubError):co.send('deepseek-4','deepseek-2','Outside',mode='immediate',project_id=p['id'])

 def test_preemption_preserves_other_project_and_pending_queue(self):
  from types import SimpleNamespace
  from unittest.mock import Mock
  p=self.projects.create('user','Scope')
  with self.h.tx():
   for ident,project,status in [('current',p['id'],'running'),('queued',p['id'],'queued'),('other','elsewhere','running')]:
    self.h.db.execute('INSERT INTO tasks(id,agent,title,project_id) VALUES(?,?,?,?)',('task-'+ident,'deepseek-1',ident,project))
    self.h.db.execute('INSERT INTO executions(id,task_id,agent,status,provider) VALUES(?,?,?,?,?)',(ident,'task-'+ident,'deepseek-1',status,'deepseek'))
  stop=Mock()
  with patch.object(self.server.workflows,'runtime',return_value=SimpleNamespace(stop=stop)):self.assertEqual(self.server.coordination.prioritize('deepseek-1',p['id'],actor='deepseek-4'),1)
  stop.assert_not_called()
  self.assertEqual(self.h.db.execute("SELECT stop_requested FROM executions WHERE id='current'").fetchone()[0],1)
  row=self.h.db.execute("SELECT actor,detail FROM audit WHERE event='deepseek.stop_requested' ORDER BY seq DESC LIMIT 1").fetchone();self.assertEqual(row['actor'],'deepseek-4');self.assertIn('message_preemption',row['detail'])
  self.assertEqual(self.h.db.execute("SELECT status FROM executions WHERE id='queued'").fetchone()[0],'queued')
