import unittest,subprocess,tempfile,re,threading
import test_nine_browser as base
CHECK=r"""
for(const id of ['tabManagerChat','tabGroupChat','tabProjectStatus']){
 const tab=document.getElementById(id),label=tab.lastElementChild;
 const offset=()=>label.getBoundingClientRect().top-tab.getBoundingClientRect().top;
 const before=offset();tab.click();const after=offset();tab.click();
 if(Math.abs(before-after)>.5||Math.abs(after-offset())>.5)throw Error('tab text shifts: '+id);
}
document.getElementById('tabManagerChat').click();
const colorInputs=[...document.querySelectorAll('#interfaceColors input[data-token]')];
if(colorInputs.length!==14)throw Error('both theme palettes must be editable');
const darkColor=colorInputs.find(x=>x.dataset.mode==='dark'&&x.dataset.token==='--accent');
const currentTheme=document.documentElement.dataset.theme;
document.documentElement.dataset.theme='light';
const previousAccent=getComputedStyle(document.documentElement).getPropertyValue('--accent');
darkColor.value='#123456';darkColor.dispatchEvent(new Event('input'));
if(getComputedStyle(document.documentElement).getPropertyValue('--accent')!==previousAccent)throw Error('inactive palette changed current theme');
if(JSON.parse(localStorage.getItem('hub.interfaceColors.v2')).dark['--accent']!=='#123456')throw Error('dark palette not saved');
if(currentTheme===undefined)delete document.documentElement.dataset.theme;else document.documentElement.dataset.theme=currentTheme;
const surface=document.querySelector('.workbench-content-surface');
if(!surface)throw Error("content surface missing");
{
 const style=getComputedStyle(surface);
 for(const corner of ['borderTopLeftRadius','borderTopRightRadius','borderBottomLeftRadius','borderBottomRightRadius']){
  const radius=parseFloat(style[corner]);
  if(radius<7||radius>9)throw Error('content corner not visibly rounded: '+corner+' '+radius);
 }
}
const edgeStyle=getComputedStyle(surface);
if(parseFloat(edgeStyle.marginRight)!==4||parseFloat(edgeStyle.marginBottom)!==4)throw Error('unequal or oversized nested frame gap');
document.getElementById('workflowForm').hidden=true;
document.getElementById('discussionReplyForm').hidden=false;
document.getElementById('planApprovalCard').hidden=false;
document.getElementById('approvePlan').hidden=false;
const body=Array.from({length:200},(_,i)=>'原始输出第'+i+'行，长内容阅读测试。').join('\n');
H.list('discussionHistory',[H.record('经理原始回复',body,'completed')]);
const detail=document.querySelector('#discussionHistory details');detail.open=true;detail.ensureContent();
H.list('planTaskPreview',Array.from({length:8},(_,i)=>H.record('task '+i,body,'pending')));
document.getElementById('planApprovalSummary').textContent=body;
await new Promise(r=>setTimeout(r,30));
const area=document.getElementById('managerReadingArea'),reply=document.getElementById('discussionReplyForm'),send=document.getElementById('discussionSend');
if(innerWidth<680)reply.scrollIntoView({block:'end'});
const rr=reply.getBoundingClientRect(),sr=send.getBoundingClientRect();
if(rr.top<0||rr.bottom>innerHeight+2||sr.bottom>innerHeight+2)throw Error('reply/send clipped '+JSON.stringify({height:innerHeight,rr:rr.toJSON()}));
if(area.clientHeight<80||area.scrollHeight<=area.clientHeight)throw Error('reading area collapsed or cannot scroll '+JSON.stringify({client:area.clientHeight,scroll:area.scrollHeight,reply:rr.toJSON(),panel:area.parentElement.getBoundingClientRect().toJSON()}));
area.scrollTop=area.scrollHeight;
if(area.scrollTop<=0)throw Error('reading scroll failed');
area.scrollTop=0;
if(!document.querySelector('#discussionHistory pre').textContent.includes('原始输出第0行'))throw Error('original reply missing');
"""
class ManagerLayout(unittest.TestCase):
 @unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
 def test_long_plan_composer_and_original_reply_across_viewports(self):
  original=base.DRIVER;base.DRIVER=original.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
  s=base.Server(('127.0.0.1',0),base.Fixture);t=threading.Thread(target=s.serve_forever);t.start()
  try:
   for size in ['1440,900','1024,600','600,800']:
    with self.subTest(size=size),tempfile.TemporaryDirectory() as p:
     r=base.browser_run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run',f'--window-size={size}',f'--user-data-dir={p}','--dump-dom','--virtual-time-budget=6000',f'http://127.0.0.1:{s.server_port}/'],capture_output=True,encoding='utf8',errors='replace',timeout=30)
     result=re.search(r'<pre id="result">(.*?)</pre>',r.stdout,re.S);self.assertIsNotNone(result);self.assertTrue(result.group(1).startswith('PASS'),result.group(1));print('PASS visible composer/send, scrollable full original reply and long approval at '+size)
  finally:s.shutdown();s.server_close();t.join();base.DRIVER=original
