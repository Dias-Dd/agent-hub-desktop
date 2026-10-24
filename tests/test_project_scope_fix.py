import tempfile,json
from pathlib import Path
from unittest.mock import patch
from test_project_setup import ProjectSetup
from hub.core import HubError
class ScopeFix(ProjectSetup):
 def test_explicit_user_project_choice_rebinds_workspace_without_new_grant(self):
  rt=self.server.deepseek;old={**rt.config(),'enabled':True,'permission':'workspace','cwd':self.temp.name,'authorized_cwd':self.temp.name,'grant_id':'same-grant','max_runs':7,'max_seconds':600,'authorized_max_seconds':600}
  with self.h.tx():self.h.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(rt.config_key,json.dumps(old)))
  with tempfile.TemporaryDirectory() as target:
   new=rt.configure('user',target,'workspace',0,300,True,True)
   self.assertEqual(new['cwd'],str(Path(target).resolve()));self.assertEqual(new['authorized_cwd'],new['cwd']);self.assertEqual(new['permission'],'workspace');self.assertEqual(new['grant_id'],'same-grant');self.assertEqual(new['max_runs'],old.get('max_runs') if not new.get('unlimited') else 0)
 def test_agent_or_unconfirmed_request_cannot_rebind(self):
  for actor,confirmed in [('deepseek-4',True),('user',False)]:
   with self.assertRaises(HubError):self.server.deepseek.configure(actor,self.temp.name,'full',0,600,True,confirmed)
 def test_same_directory_settings_do_not_block_on_existing_run(self):
  rt=self.server.deepseek;old={**rt.config(),'enabled':True,'permission':'workspace','cwd':self.temp.name,'authorized_cwd':self.temp.name,'grant_id':'same-grant','max_runs':7,'max_seconds':600,'authorized_max_seconds':600}
  with self.h.tx():
   self.h.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(rt.config_key,json.dumps(old)))
   self.h.db.execute("INSERT INTO executions(id,agent,provider,status) VALUES('existing','deepseek-1','deepseek','running')")
  rt.configure('user',self.temp.name,'workspace',0,300,True,True)
  self.assertEqual(self.h.db.execute("SELECT status FROM executions WHERE id='existing'").fetchone()[0],'running')
