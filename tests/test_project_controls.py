import json,time
from unittest.mock import patch
from test_project_setup import ProjectSetup
class ProjectControls(ProjectSetup):
 def test_delete_keeps_files_hides_project_and_cancels_timer(self):
  p=self.projects.create('user','Delete me');file=__import__('pathlib').Path(p['cwd'])/'keep.txt';file.write_text('keep')
  with self.h.tx():
   self.h.db.execute('CREATE TABLE IF NOT EXISTS hub_timers(id TEXT PRIMARY KEY,body TEXT)')
   self.h.db.execute('INSERT INTO hub_timers VALUES(?,?)',('t',json.dumps({'project_id':p['id'],'state':'scheduled'})))
  self.projects.delete('user',p['id']);self.assertTrue(file.exists());self.assertEqual(json.loads(self.h.db.execute('SELECT body FROM hub_timers').fetchone()[0])['state'],'cancelled')
  state=self.projects.state({});self.assertNotIn(p['id'],[x['id'] for x in state['projects']])
 def test_update_persists_and_updates_workflow_without_inference(self):
  p=self.projects.create('user','Settings');w={'id':'w','project_id':p['id'],'manager':'deepseek-4','agents':[],'grants':{},'status':'active','expires':0}
  self.server.workflows.save(w)
  result=self.projects.update('user',p['id'],{'agents':[],'reviewer':'deepseek-4','max_parallel':128,'expires_minutes':14400,'max_hops':9,'max_messages':2000,'max_seconds':3600})
  saved=json.loads(self.h.db.execute('SELECT body FROM workflows WHERE id=?',('w',)).fetchone()[0]);self.assertEqual(saved['max_parallel'],128);self.assertGreater(saved['expires'],time.time()+14399*60);self.assertEqual(result['options']['max_hops'],9);self.assertEqual(self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0],0)
 def test_open_directory_uses_project_directory(self):
  p=self.projects.create('user','Open')
  with patch('os.startfile') as start:self.projects.open_directory('user',p['id']);start.assert_called_once_with(p['cwd'])
 def test_quota_refresh_uses_current_connections_only(self):
  import threading
  with patch.object(self.registry,'quota_overview',return_value=[{'refreshable':['current']}]),patch.object(self.registry,'refresh_quota') as refresh:
   self.registry.start_quota_refresh()
   for _ in range(50):
    if refresh.called:break
    time.sleep(.01)
   self.registry.quota_stop.set();self.registry.quota_thread.join(2);refresh.assert_called_once_with('user','current')
