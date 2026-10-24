import unittest,tempfile,json,os
from pathlib import Path
from unittest.mock import patch
import test_automation as base
from hub.core import HubError
from hub.browser_render import executable
from hub.mcp import Protocol
class Browser(unittest.TestCase):
 def setUp(self):base.AutomationTests.setUp(self)
 def tearDown(self):base.AutomationTests.tearDown(self)
 def page(self):
  p=Path(self.temp.name)/'page.html';p.write_text('<!doctype html><meta charset="utf-8"><title>Hub screenshot</title><style>body{margin:0;background:#174a3d;color:white;font:48px sans-serif}main{padding:70px}</style><main>Actual browser render<br>1280 × 800</main>',encoding='utf8');return p
 def test_real_browser_screenshot_in_readonly_task(self):
  try:executable()
  except HubError:self.skipTest('browser unavailable')
  p=self.page();before=p.read_bytes();result=self.service.browser_render('deepseek-1','run','page.html');self.assertEqual((result['width'],result['height']),(1280,800));self.assertEqual(p.read_bytes(),before);self.assertTrue(result['image_data']);self.assertEqual(len(self.service.artifacts(self.project['id'])),1)
 def test_real_devtools_fallback_when_browser_cli_exits_without_png(self):
  import subprocess
  self.page()
  with patch('hub.browser_render.launch_browser',return_value=subprocess.CompletedProcess([],0,b'',b'')):
   result=self.service.browser_render('deepseek-1','run','page.html',width=900,height=600)
  self.assertEqual((result['width'],result['height']),(900,600));self.assertTrue(result['image_data']);self.assertEqual(len(self.service.artifacts(self.project['id'])),1)
 def test_escape_remote_and_bad_dimensions_rejected(self):
  self.page()
  for path in ['../outside.html','https://example.com']:
   with self.assertRaises(HubError):self.service.browser_render('deepseek-1','run',path)
  with self.assertRaises(HubError):self.service.browser_render('deepseek-1','run','page.html',width=10000)
 def test_failure_keeps_actual_error(self):
  self.page()
  with patch('hub.browser_render.launch_browser') as run:
   run.return_value.returncode=1;run.return_value.stderr=b'CreateNamedPipe Access denied';run.return_value.stdout=b''
   with self.assertRaisesRegex(HubError,'CreateNamedPipe Access denied'):self.service.browser_render('deepseek-1','run','page.html')
  self.assertEqual(self.service.artifacts(self.project['id']),[])
 def test_mcp_returns_image_block_not_base64_text(self):
  p=Protocol();p.initialized=True;p.ready=True
  with patch('hub.mcp.call',return_value={'image_data':'fakeimage','source':'page.html'}):
   r=p.handle({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'browser_render','arguments':{'path':'page.html'}}})
  content=r['result']['content'];self.assertEqual(content[1]['type'],'image');self.assertNotIn('fakeimage',content[0]['text'])

 def test_unexpected_service_error_keeps_redacted_diagnostic(self):
  secret=self.server.hub.tokens['user']
  with patch('hub.browser_render.render',side_effect=RuntimeError('fixture '+secret)):
   with self.assertRaisesRegex(HubError,'RuntimeError') as caught:self.service.browser_render('deepseek-1','run','page.html')
  self.assertNotIn(secret,str(caught.exception));self.assertIn('诊断编号',str(caught.exception))
  detail=self.server.hub.db.execute("SELECT detail FROM audit WHERE event='browser.render_internal_error'").fetchone()[0]
  self.assertIn('RuntimeError',detail);self.assertNotIn(secret,detail)
