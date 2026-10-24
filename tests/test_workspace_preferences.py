import unittest
from test_nine_deepseek import NineDeepSeek
from hub.projects import Projects
from hub.core import HubError
class Preferences(unittest.TestCase):
 setUp=NineDeepSeek.setUp
 tearDown=NineDeepSeek.tearDown
 def test_restore_latest_explicit_selection_and_missing_fallback(self):
  p=Projects(self.h);a=p.create('user','A');b=p.create('user','B');p.select('user',a['id'])
  self.assertEqual(p.state({'codex':{},'antigravity':{},'deepseek':{},'audit':[],'coordination':{'wakeups':[],'reports':[]},'agents':[]})['selected_project'],a['id'])
  self.assertEqual(p.state({'codex':{},'antigravity':{},'deepseek':{},'audit':[],'coordination':{'wakeups':[],'reports':[]},'agents':[]},'deleted')['selected_project'],a['id'])
  with self.assertRaises(HubError):p.select('deepseek-1',b['id'])
