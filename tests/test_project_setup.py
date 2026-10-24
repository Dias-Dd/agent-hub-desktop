import unittest,tempfile,ctypes as C,sys
from pathlib import Path
from unittest.mock import patch
import test_integrations as base
from hub.projects import Projects
from hub.planning import Planning
from hub.core import HubError
class ProjectSetup(unittest.TestCase):
 def setUp(self):
  base.RegistryTests.setUp(self);self.h=self.server.hub;Planning(self.h,self.server.deepseek,self.server.workflows);self.projects=Projects(self.h)
 def tearDown(self):base.RegistryTests.tearDown(self)
 def test_custom_directory_and_settings_persist_without_inference(self):
  opts={'preview_mode':'skip','agents':['deepseek-1'],'max_parallel':2,'cwd':'ignored','api_key':'must not store'}
  result=self.projects.create('user','New project',self.temp.name,opts);self.assertEqual(result['cwd'],str(Path(self.temp.name).resolve()));self.assertEqual(result['options']['agents'],['deepseek-1']);self.assertNotIn('api_key',result['options']);self.assertEqual(self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0],0);self.assertEqual(self.projects.get(result['id']),result)
 def test_default_directory_is_created(self):
  result=self.projects.create('user','Auto');self.assertTrue(Path(result['cwd']).is_dir());self.assertEqual(result['options']['cwd'],result['cwd'])
 def test_picker_cancel_and_selection_do_not_create_project(self):
  with patch('desktop.folder_picker.pick_directory',return_value=None):self.assertEqual(self.projects.browse_directory('user'),{'path':None})
  with patch('desktop.folder_picker.pick_directory',return_value=self.temp.name):self.assertEqual(self.projects.browse_directory('user')['path'],self.temp.name)
  self.assertEqual(self.h.db.execute('SELECT count(*) FROM hub_projects').fetchone()[0],0)
 def test_non_user_cannot_open_picker(self):
  with patch('desktop.folder_picker.pick_directory') as picker:
   with self.assertRaises(HubError):self.projects.browse_directory('deepseek-1')
   picker.assert_not_called()
 @unittest.skipUnless(sys.platform=='win32','Windows only')
 def test_real_native_dialog_initializes_folder_only_without_showing(self):
  from desktop.folder_picker import explorer_dialog,call
  with explorer_dialog(self.temp.name) as (dialog,_):
   value=C.c_uint32();self.assertGreaterEqual(call(dialog,10,(C.POINTER(C.c_uint32),),C.byref(value)),0);self.assertTrue(value.value&0x20);self.assertTrue(value.value&0x40)
