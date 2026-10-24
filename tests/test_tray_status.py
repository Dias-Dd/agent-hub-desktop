import json,sqlite3,tempfile,unittest
from pathlib import Path
from desktop.tray_status import read_status,menu_rows

class Status(unittest.TestCase):
 def test_real_progress_names_and_readonly(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'hub.sqlite3'
   with sqlite3.connect(path) as db:
    db.executescript('CREATE TABLE agents(id,model,status,enabled);CREATE TABLE agent_profiles(id,body);CREATE TABLE executions(agent,status);CREATE TABLE workflows(body);CREATE TABLE hub_projects(id,name);CREATE TABLE settings(key,value);')
    db.executemany('INSERT INTO hub_projects VALUES(?,?)',[('p','天气'),('done','完成项目'),('no-progress','音乐')])
    for w in [{'project_id':'p','status':'active','manager_progress':{'progress':15}},{'project_id':'p','status':'active','manager_progress':{'progress':42}},{'project_id':'done','status':'completed'},{'project_id':'no-progress','status':'paused'}]:db.execute('INSERT INTO workflows VALUES(?)',(json.dumps(w),))
    db.executemany('INSERT INTO agents VALUES(?,?,?,?)',[('internal-1','model','offline',1),('internal-2','model','offline',1),('removed','model','idle',0)])
    for identity,name in [('internal-1','Gemini Flash 1'),('internal-2','Sol 2')]:db.execute('INSERT INTO agent_profiles VALUES(?,?)',(identity,json.dumps({'name':name,'enabled':True})))
    db.execute("INSERT INTO executions VALUES('internal-1','running')")
   db.close();before=path.read_bytes();status=read_status(Path(directory));self.assertEqual(before,path.read_bytes())
   self.assertEqual([(p['name'],p['progress']) for p in status['projects']],[('天气',42),('音乐',None)])
   self.assertEqual([(a['name'],a['status']) for a in status['agents']],[('Gemini Flash 1','busy'),('Sol 2','idle')])
   menu=menu_rows(status);self.assertTrue(any('42%' in label for _,label,_ in menu));self.assertTrue(any('待经理汇报' in label for _,label,_ in menu));self.assertFalse(any('internal-' in label for _,label,_ in menu))
 def test_failure_label_does_not_claim_all_idle(self):
  self.assertTrue(any('保留上次记录' in label for _,label,_ in menu_rows({'stale':True})))

 def test_quota_block_overrides_busy_and_clears_on_new_observation(self):
  with tempfile.TemporaryDirectory() as directory:
   dbpath=Path(directory)/'hub.sqlite3'
   with sqlite3.connect(dbpath) as db:
    db.executescript('CREATE TABLE agents(id,model,status,enabled);CREATE TABLE agent_profiles(id,body);CREATE TABLE executions(agent,status);CREATE TABLE quotas(agent,remaining,resets_at,source,updated);CREATE TABLE model_quota_blocks(agent,body);CREATE TABLE integration_connections(id,body);')
    db.execute("INSERT INTO agents VALUES('a','model','idle',1)")
    db.execute('INSERT INTO agent_profiles VALUES(?,?)',('a',json.dumps({'id':'a','name':'Quota member','enabled':True,'model':'model','connection_id':'test'})))
    db.execute('INSERT INTO integration_connections VALUES(?,?)',('test',json.dumps({'id':'test','kind':'opencode','quota':{'remaining':0,'updated':10}})))
    db.execute("INSERT INTO executions VALUES('a','running')")
   db.close()
   self.assertEqual(read_status(Path(directory))['agents'][0]['status'],'offline')
   with sqlite3.connect(dbpath) as db:db.execute('UPDATE integration_connections SET body=?',(json.dumps({'id':'test','kind':'opencode','quota':{'remaining':50,'updated':20}}),))
   self.assertEqual(read_status(Path(directory))['agents'][0]['status'],'busy')
   db.close()
