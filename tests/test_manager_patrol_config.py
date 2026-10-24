import unittest
import test_integrations as base
class PatrolConfig(base.RegistryTests):
 def test_default_and_persistent_config(self):
  w=self.server.workflows
  self.assertEqual(w.patrol_config(),{'enabled':True,'interval_minutes':10})
  w.patrol_config('user',False,15)
  self.assertEqual(w.patrol_seconds(),900)
  self.assertFalse(w.patrol_config()['enabled'])
  self.assertIn('15',self.server.hub.db.execute("SELECT value FROM settings WHERE key='manager_patrol'").fetchone()[0])
 def test_resources_do_not_advertise_unlimited_deepseek(self):
  self.assertNotIn('deepseek',self.server.workflows.resources({'id':'fixture','agents':[],'manager':'deepseek-1'}))

 def test_changing_config_does_not_send_messages_or_stop_agents(self):
  w=self.server.workflows;w.save({'id':'one','status':'active','agents':[]})
  before=[tuple(x) for x in self.server.hub.db.execute('SELECT * FROM agents')]
  w.patrol_config('user',False,12)
  import json
  saved=json.loads(self.server.hub.db.execute("SELECT body FROM workflows WHERE id='one'").fetchone()[0])
  self.assertEqual(saved['inspection_policy']['manager_interval_seconds'],720)
  self.assertEqual(saved['status'],'active')
  self.assertEqual(before,[tuple(x) for x in self.server.hub.db.execute('SELECT * FROM agents')])
  self.assertEqual(self.server.hub.db.execute('SELECT count(*) FROM messages').fetchone()[0],0)
