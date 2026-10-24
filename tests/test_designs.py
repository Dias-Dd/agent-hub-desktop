import unittest,json,time,tempfile
from pathlib import Path
from hub.core import Hub,HubError
from hub.codex_runtime import CodexRuntime
from hub.antigravity import AntigravityRuntime
from hub.deepseek_runtime import DeepSeekRuntime
from hub.workflows import Workflows
from hub.planning import Planning
from hub.coordination import Coordination
from hub.designs import Designs
from test_nine_deepseek import API

class DesignFlow(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.h=Hub(self.t.name);self.api=API()
  self.c=CodexRuntime(self.h);self.a=AntigravityRuntime(self.h);self.c.models={};self.a.models={}
  self.d=DeepSeekRuntime(self.h,self.api);self.d.validate('user');self.d.configure_api('user',self.t.name,'full',0,600,0,1,1,0,256,True,False,True)
  self.w=Workflows(self.h,[self.c,self.a,self.d]);self.co=Coordination(self.h,[self.c,self.a,self.d],self.w);self.p=Planning(self.h,self.d,self.w);self.ds=Designs(self.h,self.p,self.w)
 def tearDown(self):self.h.db.close();self.t.cleanup()
 def plan(self,mode='demo'):
  s=self.p.message('user','Build a beautiful app',options={'preview_mode':mode,'cwd':self.t.name,'agents':['deepseek-1','deepseek-2','deepseek-3'],'reviewer':'deepseek-4','max_seconds':600},project_id='p')
  result={'done':False,'report':'Home, settings and architecture','tasks':[{'agent':'deepseek-1','instruction':'IMPLEMENT_REAL_PRODUCT'}],'preview':{'pages':[{'id':'home'},{'id':'settings'},{'id':'architecture'}]}}
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='completed',finished=?,result=? WHERE id=?",(time.time(),json.dumps(result),s['pending']))
  self.p.patrol();return self.p.get(s['id'])
 def start(self):
  s=self.plan();s=self.p.message('user','按计划执行',session_id=s['id'],revision=s['revision']);return s,self.ds.get(s['design_id'])
 def write_manifest(self,d):
  root=Path(d['working_directory']);pages=[]
  for ident in ['home','settings','architecture']:
   (root/(ident+'.html')).write_text('<!doctype html><style>body{background:#eef}</style><h1>'+ident+'</h1><p>→ annotation</p>',encoding='utf-8')
   pages.append({'id':ident,'title':ident,'parent':'home' if ident=='settings' else None,'kind':'architecture' if ident=='architecture' else 'screen','path':ident+'.html','note':'arrow explanation'})
  (root/'manifest.json').write_text(json.dumps({'title':'App','pages':pages}),encoding='utf-8')
 def finish(self,d):
  w=next(x for x in self.w.snapshot('user') if x['id']==d['workflow_id'])
  # Fake provider end-turn; no external model or real product code.
  step=self.w.steps(w['id'])[0];self.d.submit('user',step['agent'],self.h.db.execute('SELECT title FROM tasks WHERE id=?',(step['task'],)).fetchone()[0],True,step['task'])
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='completed',finished=?,result=? WHERE task_id=?",(time.time(),'{"summary":"demo done","risk":"low","evidence":["manifest"]}',step['task']))
  self.w.ingest(w,self.w.steps(w['id']));task=self.w.prepare_manager(w,self.w.steps(w['id']))
  instruction=self.h.db.execute('SELECT title FROM tasks WHERE id=?',(task,)).fetchone()[0]
  job=self.d.submit('user','deepseek-4',instruction,True,task)
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='running',started=? WHERE id=?",(time.time(),job['id']))
  from hub.automation import Automation
  from types import SimpleNamespace
  automation=Automation(SimpleNamespace(hub=self.h,workflows=self.w))
  completed=self.w.project_complete('deepseek-4',job['id'],'Demo ready',['manifest checked'])
  self.assertTrue(completed['completed']);self.assertTrue(completed['design_review_ready']);self.assertNotIn('confirmation_required',completed)
  with self.h.tx():self.h.db.execute("UPDATE executions SET status='completed',finished=?,result=? WHERE id=?",(time.time(),'{"done":true,"report":"ready","tasks":[]}',job['id']))
  return self.ds.get(d['id'])
 def test_demo_is_not_real_implementation_and_manager_publication(self):
  s,d=self.start();self.assertEqual(s['state'],'designing');self.assertEqual(len(self.w.snapshot('user')),1)
  task=self.h.db.execute('SELECT title FROM tasks WHERE id=?',(self.w.steps(d['workflow_id'])[0]['task'],)).fetchone()[0]
  self.assertEqual(self.w.steps(d['workflow_id'])[0]['agent'],'deepseek-4');self.assertEqual(self.w.steps(d['workflow_id'])[0]['kind'],'plan');self.assertIn('project_assign',task);self.assertNotIn('IMPLEMENT_REAL_PRODUCT',task);self.assertTrue((Path(d['working_directory'])/'brief.md').exists());self.assertIn('data-design-only',(Path(d['working_directory'])/'brief.md').read_text(encoding='utf-8'))
  self.write_manifest(d);d=self.finish(d);self.assertEqual(d['state'],'review');self.assertEqual(len(d['versions'][0]['pages']),3)
  content=self.ds.content('user',d['id']);self.assertIn('home',content['html'])
  s=self.ds.accept('user',d['id'],d['version'],d['digest']);self.assertEqual(s['state'],'executing')
  implementation=next(x for x in self.w.snapshot('user') if x['id']==s['workflow_id']);self.assertEqual(implementation['design_baseline']['digest'],d['digest']);self.assertIn('演示说明层',implementation['requirement']);self.assertIn('200%',implementation['requirement']);self.assertIn('DPI',implementation['initial_manager_instruction']);self.assertIn('file://',implementation['initial_manager_instruction'])
  self.assertEqual(implementation['reviewer'],'deepseek-1');self.assertEqual(implementation['delivery_stage'],'implementation');self.assertEqual(self.w.steps(implementation['id'])[0]['kind'],'plan');self.assertIn('真实产品开发',implementation['initial_manager_instruction']);self.assertIn('逐页',self.w.check_prompt(implementation,[]));self.assertEqual(self.ds.accept('user',d['id'],d['version'],d['digest'])['workflow_id'],s['workflow_id'])
 def test_revision_isolated_and_stale_approval_blocked(self):
  s,d=self.start();self.write_manifest(d);d=self.finish(d);old=d['versions'][0]
  d=self.ds.feedback('user',d['id'],1,'Make it blue','home',{'x':.1,'y':.2,'width':.3,'height':.4},'page')
  self.assertEqual(d['version'],2);self.assertEqual(d['state'],'building');self.assertEqual(len(d['versions']),1)
  self.assertIn('Make it blue',(Path(d['working_directory'])/'brief.md').read_text(encoding='utf-8'))
  self.assertTrue((Path(old['directory'])/'home.html').exists())
  with self.assertRaises(HubError):self.ds.accept('user',d['id'],1,old['digest'])
 def test_batch_feedback_one_revision(self):
  s,d=self.start();self.write_manifest(d);d=self.finish(d);before=len(self.w.snapshot('user'))
  with self.assertRaises(HubError):self.ds.feedback('user',d['id'],1,entries=[{'page_id':'home','body':'one'},{'page_id':'missing','body':'two'}])
  self.assertEqual(self.ds.get(d['id'])['feedback'],[])
  d=self.ds.feedback('user',d['id'],1,entries=[{'page_id':'home','body':'one'},{'page_id':'settings','body':'two','scope':'page'}],overall='overall')
  self.assertEqual(d['version'],2);self.assertEqual(self.w.steps(d['workflow_id'])[0]['agent'],'deepseek-4');self.assertEqual(len(d['feedback']),3);self.assertEqual(len(self.w.snapshot('user')),before+1)
  brief=(Path(d['working_directory'])/'brief.md').read_text(encoding='utf-8')
  for value in ['one','two','overall']:self.assertIn(value,brief)
 def test_demo_uses_selected_backup_manager(self):
  s=self.plan();s['manager']='deepseek-9';self.p.save(s)
  s=self.ds.start('user',s['id'],s['revision']);d=self.ds.get(s['design_id'])
  w=next(w for w in self.w.snapshot('user') if w['id']==d['workflow_id'])
  self.assertEqual(w['manager'],'deepseek-9');self.assertEqual(self.w.steps(w['id'])[0]['agent'],'deepseek-9')
 def test_explicit_skip_keeps_original_plan(self):
  s=self.plan();s=self.ds.skip('user',s['id'],s['revision']);self.assertEqual(s['state'],'executing')
  self.assertEqual(self.ds.snapshot('p'),[]);self.assertFalse(self.w.snapshot('user')[0].get('design_review'))
 def test_incomplete_pages_hierarchy_and_paths_are_rejected(self):
  s,d=self.start();self.write_manifest(d);root=Path(d['working_directory']);manifest=json.loads((root/'manifest.json').read_text())
  w=self.w.snapshot('user')[0]
  for change in ['missing','cycle','escape','architecture']:
   value=json.loads(json.dumps(manifest))
   if change=='missing':value['pages']=value['pages'][1:]
   if change=='cycle':value['pages'][0]['parent']='settings'
   if change=='escape':value['pages'][0]['path']='../../outside.html'
   if change=='architecture':value['pages'][-1]['kind']='screen'
   (root/'manifest.json').write_text(json.dumps(value))
   with self.subTest(change=change),self.assertRaises(HubError):self.ds.prepare_publish(w)
 def test_modified_frozen_artifact_and_cross_project_rejected(self):
  s,d=self.start();self.write_manifest(d);d=self.finish(d)
  with self.assertRaises(HubError):self.ds.content('user',d['id'],project_id='other')
  (Path(d['versions'][0]['directory'])/'home.html').write_text('tampered')
  with self.assertRaises(HubError):self.ds.accept('user',d['id'],1,d['digest'])
 def test_reopen_retains_review_and_no_inference_on_view(self):
  s,d=self.start();self.write_manifest(d);d=self.finish(d);count=self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0]
  restored=Designs(self.h,self.p,self.w);self.assertEqual(restored.snapshot('p')[0]['state'],'review')
  restored.content('user',d['id']);self.assertEqual(self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0],count)
 def test_long_feedback_is_in_brief_not_oversized_task(self):
  s,d=self.start();self.write_manifest(d);d=self.finish(d)
  d=self.ds.feedback('user',d['id'],1,'长'*20000,scope='all')
  self.assertIn('长'*20000,(Path(d['working_directory'])/'brief.md').read_text(encoding='utf-8'))
  task=self.w.steps(d['workflow_id'])[0];title=self.h.db.execute('SELECT title FROM tasks WHERE id=?',(task['task'],)).fetchone()[0];self.assertLess(len(title),1000)

 def test_http_content_uses_scoped_capability_and_no_script_preview(self):
  from hub.server import Server,Handler
  from urllib.request import Request,urlopen
  from urllib.error import HTTPError
  import threading
  s,d=self.start();self.write_manifest(d);d=self.finish(d)
  server=Server(('127.0.0.1',0),Handler);server.hub=self.h;server.designs=self.ds;server.design_tickets={}
  thread=threading.Thread(target=server.serve_forever);thread.start();url='http://127.0.0.1:'+str(server.server_port)
  try:
   payload=json.dumps({'action':'design_content','args':{'design_id':d['id'],'version':1}}).encode()
   with self.assertRaises(HTTPError):urlopen(Request(url+'/api/action',payload,{'Content-Type':'application/json'}))
   request=Request(url+'/api/action',payload,{'Content-Type':'application/json','Authorization':'Bearer '+self.h.tokens['user'],'X-Hub-Project':'p'})
   with urlopen(request) as response:content=json.load(response)['result']
   self.assertNotIn('html',content);preview=content['urls']['home'];self.assertNotIn(self.h.tokens['user'],preview)
   with urlopen(url+preview) as response:
    self.assertIn('home',response.read().decode());policy=response.headers['Content-Security-Policy'];self.assertIn("script-src 'none'",policy);self.assertIn('sandbox',policy);self.assertIn("connect-src 'none'",policy)
   with self.assertRaises(HTTPError):urlopen(url+'/api/design-preview/unknown')
  finally:server.shutdown();server.server_close();thread.join()

 def test_stale_skip_does_not_disable_demo_gate(self):
  s=self.plan()
  with self.assertRaises(HubError):self.ds.skip('user',s['id'],s['revision']-1)
  self.assertEqual(self.p.get(s['id'])['options']['preview_mode'],'demo')
 def test_final_user_approval_renews_discussion_expiry(self):
  s,d=self.start();self.write_manifest(d);d=self.finish(d)
  s=self.p.get(s['id']);s['expires']=time.time()-60;self.p.save(s)
  result=self.ds.accept('user',d['id'],d['version'],d['digest']);self.assertEqual(result['state'],'executing')

 def test_normal_chat_cannot_reopen_published_design(self):
  s,d=self.start();self.write_manifest(d);d=self.finish(d)
  messages=self.co.send('user','deepseek-4','Explain this design',project_id='p')
  workflow=next(w for w in self.w.snapshot('user') if w['id']==d['workflow_id']);self.assertEqual(workflow['status'],'completed')
  job=self.h.db.execute('SELECT purpose FROM executions WHERE message_id=?',(messages[0],)).fetchone();self.assertEqual(job['purpose'],'task')
  self.assertEqual(self.ds.get(d['id'])['state'],'review')
