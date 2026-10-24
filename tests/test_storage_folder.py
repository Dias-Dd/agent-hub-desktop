import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
from hub.core import Hub,HubError
from hub.projects import Projects
import test_automation as base
class Storage(unittest.TestCase):
 def test_new_root_only_affects_new_projects_and_lists_usage(self):
  with tempfile.TemporaryDirectory() as folder:
   h=Hub(Path(folder)/'data')
   with patch.object(Projects,'tag'):projects=Projects(h)
   try:
    before=projects.create('user','Old project');(Path(before['cwd'])/'a.txt').write_bytes(b'12345')
    target=Path(folder)/'custom';result=projects.storage('user',str(target));after=projects.create('user','New project')
    self.assertEqual(Path(after['cwd']).parent,target)
    self.assertNotEqual(Path(before['cwd']).parent,target)
    self.assertEqual(projects.get(before['id'])['cwd'],before['cwd'])
    self.assertEqual(next(p for p in result['projects'] if p['id']==before['id'])['bytes'],5)
    with self.assertRaises(HubError):projects.storage('deepseek-4',str(target))
   finally:h.db.close()
class Folder(unittest.TestCase):
 def setUp(self):base.AutomationTests.setUp(self)
 def tearDown(self):base.AutomationTests.tearDown(self)
 def test_folder_link_is_persistent_and_only_user_can_open(self):
  folder=Path(self.temp.name)/'dist';folder.mkdir()
  item=self.service.publish_artifact('deepseek-4','run','dist',kind='folder',caption='交付目录')
  self.assertEqual(item['kind'],'folder');self.assertEqual(item['path'],str(folder.resolve()))
  self.assertIsNotNone(self.server.hub.db.execute('SELECT 1 FROM shared_artifacts WHERE id=?',(item['id'],)).fetchone())
  with patch('os.startfile') as opened:
   self.service.open_folder('user',item['id']);opened.assert_called_once_with(str(folder.resolve()))
   with self.assertRaises(HubError):self.service.open_folder('deepseek-4',item['id'])
 def test_folder_rejects_outside_project_and_files(self):
  with tempfile.TemporaryDirectory() as other:
   with self.assertRaises(HubError):self.service.publish_artifact('deepseek-4','run',other,kind='folder')
  file=Path(self.temp.name)/'not-a-folder';file.write_text('data')
  with self.assertRaises(HubError):self.service.publish_artifact('deepseek-4','run',str(file),kind='folder')
