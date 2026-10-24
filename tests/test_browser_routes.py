import unittest
from pathlib import Path
from hub.core import HubError
from test_automation import AutomationTests

class BrowserRouteTests(AutomationTests):
 def test_real_browser_renders_query_and_fragment(self):
  page=Path(self.temp.name)/'wincalc.html'
  page.write_text("<html><body><script>document.body.textContent=location.search+location.hash</script></body></html>",encoding='utf8')
  result=self.service.browser_render('deepseek-1','run','wincalc.html?route=history#details',640,480)
  self.assertTrue(result['page_url'].endswith('wincalc.html?route=history#details'))
  self.assertEqual(result['width'],640)
  self.assertEqual(result['height'],480)
  self.assertTrue(result['image_data'])
 def test_boundary_still_checked_without_query(self):
  for path in ('../outside.html?route=history','https://example.org/page.html?route=history','//server/share/page.html?x=1'):
   with self.subTest(path=path),self.assertRaises(HubError):
    self.service.browser_render('deepseek-1','run',path)

if __name__=='__main__':unittest.main()
