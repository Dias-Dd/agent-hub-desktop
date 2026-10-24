import unittest,tempfile,subprocess,threading,re
import test_automation_browser as base
CHECK="""
const wait=()=>new Promise(r=>setTimeout(r,100));
const root=document.getElementById('sharedArtifacts'),card=root.querySelector('.shared-artifact'),frame=card.querySelector('iframe'),footer=card.querySelector('footer');
if(card.querySelector('header')||card.lastElementChild!==footer||!footer.querySelector('time[datetime]'))throw Error('old header metadata layout');
if(!footer.classList.contains('chat-message-meta')||parseFloat(getComputedStyle(footer).fontSize)>12||getComputedStyle(footer).justifyContent!=='flex-start')throw Error('footer not small and left-aligned');
if(parseFloat(getComputedStyle(card).paddingTop)<20||parseFloat(getComputedStyle(root).marginLeft)<14||parseFloat(getComputedStyle(root).rowGap)<24)throw Error('card spacing too tight');
card.focus();await wait();if(getComputedStyle(footer).opacity!=='1')throw Error('footer not revealed on focus');
let copied='';Object.defineProperty(navigator,'clipboard',{value:{writeText:async x=>{copied=x;}},configurable:true});card.querySelector('.artifact-copy').click();await wait();if(!copied.includes('/api/shared/'))throw Error('copy link failed');
const reader=document.getElementById('managerReadingArea');reader.scrollTop=40;const top=reader.scrollTop;H.store.rawState.shared_artifacts.reverse();H.store._notify();await wait();
if(root.firstElementChild!==card||root.querySelector('iframe')!==frame||Math.abs(reader.scrollTop-top)>2)throw Error('chronology/reuse/scroll changed');
if(card.dataset.artifact!=='a'.repeat(64))throw Error('artifacts not chronological');
card.querySelector('.artifact-enlarge').click();if(!document.getElementById('artifactViewer').open)throw Error('open preview failed');document.getElementById('closeArtifactViewer').click();
"""
class Browser(unittest.TestCase):
 @unittest.skipUnless(base.base.m.EDGE.exists(),'Edge unavailable')
 def test_artifact_footer_spacing_copy_and_preserved_preview(self):
  old=base.base.DRIVER;base.base.DRIVER=old.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
  server=base.base.Server(('127.0.0.1',0),base.Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
  try:
   for size in ['1440,900','1024,600','600,800']:
    with self.subTest(size=size),tempfile.TemporaryDirectory() as folder:
     r=subprocess.run([str(base.base.m.EDGE),'--headless','--disable-gpu','--no-first-run','--window-size='+size,'--user-data-dir='+folder,'--dump-dom','--virtual-time-budget=6000','http://127.0.0.1:'+str(server.server_port)+'/'],capture_output=True,encoding='utf8',errors='replace',timeout=30)
     result=re.search(r'<pre id="result">(.*?)</pre>',r.stdout,re.S);self.assertIsNotNone(result);self.assertTrue(result.group(1).startswith('PASS'),result.group(1));print('PASS artifact footer, whitespace, copy, stable iframe and chronological cards at '+size)
  finally:server.shutdown();server.server_close();thread.join();base.base.DRIVER=old
