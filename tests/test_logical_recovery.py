import json,time,unittest
from pathlib import Path
from unittest.mock import patch
from test_nine_deepseek import NineDeepSeek
from hub.core import HubError
class Recovery(unittest.TestCase):
 setUp=NineDeepSeek.setUp
 tearDown=NineDeepSeek.tearDown
 running=NineDeepSeek.running
 def discussion(self):return self.p.message('user','new request',project_id='fixture')
 def finish(self,s,answer):
  self.api.answers.append(answer);self.d.execute(self.running(s['pending']))
 def test_expired_discussion_keeps_session(self):
  s=self.discussion();self.finish(s,'A useful ordinary answer');self.p.patrol();s=self.p.get(s['id']);s['expires']=time.time()-1;self.p.save(s)
  b=self.p.message('user','continue',session_id=s['id'],project_id='fixture')
  self.assertEqual(b['id'],s['id']);self.assertGreater(b['expires'],time.time());self.assertEqual(self.w.snapshot('user'),[])
 def test_terminal_pending_reconciles_before_next_message(self):
  s=self.discussion();self.finish(s,'answer')
  b=self.p.message('user','next',session_id=s['id'],project_id='fixture')
  self.assertNotEqual(b['pending'],s['pending']);self.assertEqual(b['turns'],2)
 def test_plain_answer_is_visible_but_cannot_execute(self):
  s=self.discussion();self.finish(s,'Please clarify your preferred style.');self.p.patrol();s=self.p.get(s['id'])
  self.assertEqual(s['state'],'draft');self.assertEqual(s['history'][-1]['text'],'Please clarify your preferred style.')
  with self.assertRaises(HubError):self.p.message('user','按计划执行',session_id=s['id'],revision=s['revision'])
  self.assertEqual(self.w.snapshot('user'),[])
 def test_extra_metadata_does_not_break_discussion(self):
  s=self.discussion();self.finish(s,json.dumps({'done':False,'report':'ready','tasks':[{'agent':'deepseek-1','instruction':'work','metadata':1}],'metadata':2}));self.p.patrol()
  self.assertEqual(self.p.get(s['id'])['state'],'awaiting_approval')
 def test_executing_discussion_routes_to_manager(self):
  s=self.discussion();s['pending']=None;s['state']='executing';self.p.save(s)
  with patch.object(self.co,'send',return_value={'queued':True}) as send:
   self.assertTrue(self.p.message('user','status please',session_id=s['id'],project_id='fixture')['queued']);send.assert_called_once_with('user','deepseek-4','status please',mode='queue',project_id='fixture')
 def test_full_permission_allows_explicit_new_project_directory(self):
  import tempfile
  with tempfile.TemporaryDirectory() as other:
   cfg=self.d.configure('user',other,'full',0,600,confirmed=True);self.assertEqual(Path(cfg['cwd']),Path(other).resolve())
 def test_workspace_permission_still_enforces_boundary(self):
  import tempfile
  cfg=self.d.config();cfg['permission']='workspace'
  with self.h.tx():self.h.db.execute("update settings set value=? where key='deepseek_runtime'",(json.dumps(cfg),))
  with tempfile.TemporaryDirectory() as other:
   with self.assertRaises(HubError):self.d.configure('user',other,'workspace',0,600,confirmed=True)
