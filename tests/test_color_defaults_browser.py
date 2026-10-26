import re,threading,unittest
from unittest.mock import patch
import test_nine_browser as base
CHECK=r"""
const fields=[...document.querySelectorAll('#interfaceColors input[data-token]')];
if(fields.length!==14)throw Error('both palettes missing');
for(const field of fields){if(!/^#[0-9a-f]{6}$/i.test(field.value))throw Error('invalid color '+field.value);}
for(const mode of ['light','dark']){
 const values=fields.filter(f=>f.dataset.mode===mode).map(f=>f.value.toLowerCase());
 if(new Set(values).size<4||values.every(v=>v==='#000000'))throw Error('palette collapsed to black '+mode+JSON.stringify(values));
}
const canvas=document.createElement('canvas');canvas.width=canvas.height=1;const ctx=canvas.getContext('2d');
ctx.fillStyle='color(srgb 0.2 0.4 0.6)';ctx.fillRect(0,0,1,1);
if([...ctx.getImageData(0,0,1,1).data].slice(0,3).join(',')!=='51,102,153')throw Error('wide color conversion invalid');
const light=fields.find(f=>f.dataset.mode==='light'&&f.dataset.token==='--accent');
const dark=fields.find(f=>f.dataset.mode==='dark'&&f.dataset.token==='--accent');
light.value='#123456';light.dispatchEvent(new Event('input'));dark.value='#abcdef';dark.dispatchEvent(new Event('input'));
document.documentElement.dataset.theme='light';await new Promise(r=>setTimeout(r,30));if(document.documentElement.style.getPropertyValue('--accent')!=='#123456')throw Error('light palette lost');
document.documentElement.dataset.theme='dark';await new Promise(r=>setTimeout(r,30));if(document.documentElement.style.getPropertyValue('--accent')!=='#abcdef')throw Error('dark palette lost');
"""
class Colors(unittest.TestCase):
 @unittest.skipUnless(base.m.EDGE.exists(),'real browser missing')
 def test_non_black_defaults_and_independent_palettes(self):
  server=base.Server(('127.0.0.1',0),base.Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
  try:
   with patch.object(base,'DRIVER',base.DRIVER.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")):
    result=base.browser_run([str(base.m.EDGE),'--window-size=1024,600',f'http://127.0.0.1:{server.server_port}/'],timeout=30)
    match=re.search(r'<pre id="result">(.*?)</pre>',result.stdout,re.S);self.assertTrue(match and match.group(1).startswith('PASS'),match.group(1) if match else 'no result')
  finally:server.shutdown();server.server_close();thread.join()
