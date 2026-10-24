import unittest
from test_project_setup import ProjectSetup
class DiscussionIdentity(unittest.TestCase):
 setUp=ProjectSetup.setUp
 tearDown=ProjectSetup.tearDown
 def test_project_state_exposes_bound_discussion_identity(self):
  p=self.projects.create('user','One');other=self.projects.create('user','Other')
  ids=self.h.send('user','deepseek-4','followup',mode='queue')
  with self.h.tx():
   self.h.db.execute('CREATE TABLE IF NOT EXISTS manager_discussion_inputs(message_id TEXT PRIMARY KEY,session_id TEXT,run_id TEXT)')
   self.h.db.execute('UPDATE messages SET project_id=? WHERE id=?',(p['id'],ids[0]))
   self.h.db.execute('INSERT INTO manager_discussion_inputs VALUES(?,?,?)',(ids[0],'discussion','run'))
  state=self.projects.state({'audit':[],'coordination':{'wakeups':[],'reports':[]},**{k:{'runs':[]} for k in ['codex','antigravity','deepseek']}},p['id'])
  for key in ['messages','manager_messages']:
   m=next(x for x in state[key] if x['id']==ids[0]);self.assertEqual(m['discussion_session_id'],'discussion');self.assertEqual(m['discussion_run_id'],'run')
  self.assertFalse(any(x['id']==ids[0] for x in self.projects.state({'audit':[],'coordination':{'wakeups':[],'reports':[]},**{k:{'runs':[]} for k in ['codex','antigravity','deepseek']}},other['id'])['messages']))
