import json,os,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from desktop.dependencies import enabled_connections,start_dependencies
class Dependencies(unittest.TestCase):
 def test_only_enabled_used_connections(self):
  with tempfile.TemporaryDirectory() as t:
   c=sqlite3.connect(Path(t)/'hub.sqlite3');c.execute('create table integration_connections(body text)');c.execute('create table agent_profiles(body text)')
   for value in [{'id':'used','kind':'workbuddy','enabled':True},{'id':'disabled','kind':'antigravity','enabled':False},{'id':'unused','kind':'codex','enabled':True}]:c.execute('insert into integration_connections values(?)',(json.dumps(value),))
   for value in [{'id':'a','enabled':True,'connection_id':'used'},{'id':'b','enabled':True,'connection_id':'disabled'}]:c.execute('insert into agent_profiles values(?)',(json.dumps(value),))
   c.commit();c.close();self.assertEqual([x['id'] for x in enabled_connections(t)],['used'])
 def test_already_running_host_is_not_started_again(self):
  with tempfile.TemporaryDirectory() as t,patch('desktop.dependencies.enabled_connections',return_value=[{'kind':'antigravity'}]),patch('desktop.dependencies.running_names',return_value={'antigravity.exe'}),patch('desktop.dependencies.Path.is_file',return_value=True),patch('hub.proxy_env.inherit_system_proxy',return_value={}),patch('desktop.dependencies.spawn_host') as spawn:
   result=start_dependencies(t);self.assertEqual(result[0]['status'],'running');spawn.assert_not_called()
 def test_duplicate_connections_start_one_host(self):
  with tempfile.TemporaryDirectory() as t,patch('desktop.dependencies.enabled_connections',return_value=[{'kind':'antigravity'},{'kind':'antigravity'}]),patch('desktop.dependencies.running_names',return_value=set()),patch('desktop.dependencies.Path.is_file',return_value=True),patch('hub.proxy_env.inherit_system_proxy',return_value={}),patch('desktop.dependencies.spawn_host') as spawn:
   result=start_dependencies(t);self.assertEqual(spawn.call_count,1);self.assertEqual([r['status'] for r in result],['starting','running'])

 def test_standalone_codebuddy_does_not_launch_workbuddy_app(self):
  with tempfile.TemporaryDirectory() as t,patch('desktop.dependencies.enabled_connections',return_value=[{'kind':'workbuddy'}]),patch('hub.proxy_env.inherit_system_proxy',return_value={}),patch('desktop.dependencies.spawn_host') as spawn:
   start_dependencies(t);spawn.assert_not_called()
