import json,unittest,types
from hub.workflows import proposal
from hub.planning import Planning
from hub.core import HubError
class Simplified(unittest.TestCase):
 def test_extra_model_metadata_is_ignored(self):
  p=proposal(json.dumps({'done':False,'report':'ready','tasks':[{'agent':'deepseek-1','instruction':'implement','notes':'extra'}],'metadata':{'x':1}}))
  self.assertEqual(set(p),{'done','report','tasks'});self.assertEqual(set(p['tasks'][0]),{'agent','instruction'})
 def test_contradictory_completion_still_rejected(self):
  with self.assertRaises(HubError):proposal(json.dumps({'done':True,'report':'done','tasks':[{'agent':'deepseek-1','instruction':'work'}]}))
 def fixture(self):
  rt=types.SimpleNamespace(models={f'deepseek-{i}':'deepseek-flash' for i in range(1,10)},config=lambda:{'cwd':str(__import__('pathlib').Path.cwd())})
  p=Planning.__new__(Planning);p.workflows=types.SimpleNamespace(runtime=lambda _:rt);return p
 def test_partial_settings_get_defaults(self):
  p=self.fixture().options({'max_calls':0,'future_field':123});self.assertEqual(p['max_calls'],0);self.assertEqual(p['max_parallel'],8)
 def test_any_participant_can_review(self):
  self.assertEqual(self.fixture().options({'reviewer':'deepseek-2'})['reviewer'],'deepseek-2')
 def test_nonparticipant_reviewer_rejected(self):
  with self.assertRaises(HubError):self.fixture().options({'agents':['deepseek-1'],'reviewer':'deepseek-2'})
