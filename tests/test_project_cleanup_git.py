import hashlib,json,subprocess,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from hub.core import Hub,HubError
from hub.projects import Projects

class CleanupGit(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.h=Hub(Path(self.temp.name)/'data')
  with patch.object(Projects,'tag'):self.p=Projects(self.h)
  self.project=self.p.create('user','Fixture');self.root=Path(self.project['cwd']);self.ident=self.project['id'];self.stopped=[]
  flow=SimpleNamespace(lock=threading.RLock(),records=lambda project_id=None,statuses=None:[{'id':'w','project_id':self.ident}],snapshot=lambda actor:[{'id':'w','project_id':self.ident}],stop=lambda actor,w:self.stopped.append(w))
  self.h.planning=SimpleNamespace(workflows=flow)
  with self.h.tx():
   self.h.db.execute('CREATE TABLE IF NOT EXISTS planning_sessions(id TEXT PRIMARY KEY,body TEXT)')
   self.h.db.execute('CREATE TABLE IF NOT EXISTS hub_timers(id TEXT PRIMARY KEY,body TEXT)')
   self.h.db.execute('CREATE TABLE IF NOT EXISTS git_workspaces(project TEXT,agent TEXT,root TEXT,cwd TEXT,branch TEXT)')
   self.h.db.execute('CREATE TABLE IF NOT EXISTS git_runs(run TEXT,project TEXT,agent TEXT,cwd TEXT,branch TEXT,base TEXT,head TEXT,result TEXT)')
   self.h.db.execute('CREATE TABLE IF NOT EXISTS design_reviews(id TEXT,body TEXT)')
   self.h.db.execute('CREATE TABLE IF NOT EXISTS shared_artifacts(id TEXT,body TEXT)')
 def tearDown(self):self.h.db.close();self.temp.cleanup()
 def git(self,*args):return subprocess.run(['git','-C',str(self.root),*args],check=True,capture_output=True).stdout
 def workspace(self):
  self.git('init');self.git('config','user.name','Fixture');self.git('config','user.email','fixture@localhost')
  (self.root/'main.txt').write_text('main');self.git('add','.');self.git('commit','-m','baseline')
  self.work=Path(self.h.directory)/'git-worktrees'/hashlib.sha256(self.ident.encode()).hexdigest()[:16]/'worker';self.work.parent.mkdir(parents=True)
  self.git('worktree','add','-b','worker',str(self.work));(self.work/'untracked.txt').write_text('uncommitted')
  with self.h.tx():self.h.db.execute('INSERT INTO git_workspaces VALUES(?,?,?,?,?)',(self.ident,'a',str(self.root),str(self.work),'worker'))
 def test_preview_is_read_only_cleanup_all_for_existing_project(self):
  self.workspace()
  paths=[]
  for table,folder,ident in [('design_reviews','designs','a'*32),('shared_artifacts','shared-artifacts','b'*64)]:
   target=Path(self.h.directory)/folder/ident;target.mkdir(parents=True);(target/'page').write_text('asset');paths.append(target)
   with self.h.tx():self.h.db.execute('INSERT INTO '+table+' VALUES(?,?)',(ident,json.dumps({'id':ident,'project_id':self.ident})))
  plan=self.p.cleanup('user',self.ident);self.assertFalse(plan['removed']);self.assertEqual(self.stopped,[]);self.assertTrue(self.root.exists())
  result=self.p.cleanup('user',self.ident,True,plan['inventory_key']);self.assertTrue(result['ok'],result);self.assertEqual(self.stopped,[])
  for path in [self.root,self.work,*paths]:self.assertFalse(path.exists(),path)
  self.assertFalse(self.p.cleanup('user',self.ident)['removed']);self.p.ensure_ready(self.ident);self.assertTrue(self.root.is_dir());self.assertFalse(self.h.db.execute('SELECT 1 FROM git_workspaces').fetchone())
 def test_stale_confirmation_and_agent_denied(self):
  plan=self.p.cleanup('user',self.ident);self.workspace()
  with self.assertRaises(HubError):self.p.cleanup('user',self.ident,True,plan['inventory_key'])
  with self.assertRaises(HubError):self.p.cleanup('deepseek-1',self.ident)
  self.assertTrue(self.root.exists());self.assertEqual(self.stopped,[])
 def test_shared_directory_is_preserved_and_error_visible(self):
  self.p.create('user','Other',str(self.root));(self.root/'keep').write_text('data');plan=self.p.cleanup('user',self.ident)
  result=self.p.cleanup('user',self.ident,True,plan['inventory_key']);self.assertFalse(result['ok']);self.assertTrue(result['errors']);self.assertTrue((self.root/'keep').exists())
 def test_partial_failure_is_reported_and_retryable(self):
  (self.root/'keep').write_text('data');plan=self.p.cleanup('user',self.ident)
  with patch('hub.project_files.shutil.rmtree',side_effect=PermissionError('busy')):result=self.p.cleanup('user',self.ident,True,plan['inventory_key'])
  self.assertFalse(result['ok']);self.assertIn('busy',result['errors'][0]['error']);self.assertTrue(self.root.exists())
  plan=self.p.cleanup('user',self.ident);self.assertTrue(self.p.cleanup('user',self.ident,True,plan['inventory_key'])['ok'])
 def test_graph_has_real_worker_commit_and_merge(self):
  self.workspace();subprocess.run(['git','-C',str(self.work),'add','.'],check=True,capture_output=True);subprocess.run(['git','-C',str(self.work),'commit','-m','worker implementation'],check=True,capture_output=True)
  self.git('merge','--no-ff','worker','-m','integrate worker');data=self.p.git_tree('user',self.ident)
  self.assertIn('worker implementation',data['graph']);self.assertIn('integrate worker',data['graph']);self.assertIn('|',data['graph']);self.assertEqual(data['workspaces'][0]['agent'],'a')
 def test_storage_includes_external_worktree_bytes(self):
  self.workspace();(self.work/'large').write_bytes(b'x'*10000);data=self.p.storage('user');project=next(p for p in data['projects'] if p['id']==self.ident)
  self.assertGreater(project['bytes'],10000);self.assertTrue(any('git-worktrees' in p['path'] for p in project['associated_paths']))
 def test_removed_project_disappears_after_cleanup_without_erasing_history(self):
  with self.h.tx():self.h.db.execute('INSERT INTO settings VALUES(?,?)',('deleted_project:'+self.ident,'true'))
  self.assertIn(self.ident,{p['id'] for p in self.p.storage('user')['projects']})
  plan=self.p.cleanup('user',self.ident)
  self.assertTrue(self.p.cleanup('user',self.ident,True,plan['inventory_key'])['ok'])
  self.assertNotIn(self.ident,{p['id'] for p in self.p.storage('user')['projects']})
  self.assertEqual(self.p.get(self.ident)['name'],'Fixture')
 def test_retained_project_still_shows_after_its_files_are_cleaned(self):
  plan=self.p.cleanup('user',self.ident)
  self.assertTrue(self.p.cleanup('user',self.ident,True,plan['inventory_key'])['ok'])
  project=next(p for p in self.p.storage('user')['projects'] if p['id']==self.ident)
  self.assertFalse(project['exists']);self.assertFalse(project['removed'])
 def test_removed_project_with_missing_root_keeps_external_leftovers_visible(self):
  import shutil
  self.work=Path(self.h.directory)/'git-worktrees'/hashlib.sha256(self.ident.encode()).hexdigest()[:16]/'worker';self.work.mkdir(parents=True)
  with self.h.tx():self.h.db.execute('INSERT INTO git_workspaces VALUES(?,?,?,?,?)',(self.ident,'a',str(self.root),str(self.work),'worker'))
  attachment=Path(self.h.directory)/'shared-artifacts'/('c'*32);attachment.mkdir(parents=True)
  with self.h.tx():
   self.h.db.execute('INSERT INTO settings VALUES(?,?)',('deleted_project:'+self.ident,'true'))
   self.h.db.execute('INSERT INTO shared_artifacts VALUES(?,?)',('c'*32,json.dumps({'id':'c'*32,'project_id':self.ident})))
  shutil.rmtree(self.root)
  project=next(p for p in self.p.storage('user')['projects'] if p['id']==self.ident)
  self.assertFalse(project['exists']);self.assertTrue(project['removed'])
  shutil.rmtree(self.work.parent)
  self.assertIn(self.ident,{p['id'] for p in self.p.storage('user')['projects']})
  shutil.rmtree(attachment)
  self.assertNotIn(self.ident,{p['id'] for p in self.p.storage('user')['projects']})
