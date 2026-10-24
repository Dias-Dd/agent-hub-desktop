from unittest.mock import patch
import test_nine_browser as base
from test_demo_cards_browser import Fixture
EXTRA=r"""
const cards=document.getElementById('discussionHistory');
if(cards.querySelector('iframe')||!cards.querySelector('a.artifact-web-link'))throw Error('webpage still embeds a preview');
cards.querySelector('a.artifact-web-link').click();
if(!document.getElementById('artifactViewer').open||!document.querySelector('#artifactViewerContent iframe'))throw Error('web link failed to open');
document.getElementById('artifactViewer').close();
const reader=document.getElementById('managerReadingArea');
reader.style.height='260px';reader.style.maxHeight='260px';reader.style.overflow='auto';
const wait=()=>new Promise(r=>setTimeout(r,100));
const row=H.node('div','streaming reply');row.style.height='1600px';
H.list('discussionHistory',[row]);await wait();reader.scrollTop=reader.scrollHeight;reader.dispatchEvent(new Event('scroll'));await wait();
row.style.height='2300px';await wait();
if(reader.scrollHeight-reader.clientHeight-reader.scrollTop>3)throw Error('late layout lost bottom follow '+[reader.scrollTop,reader.scrollHeight,reader.clientHeight]);
reader.scrollTop=120;reader.dispatchEvent(new Event('scroll'));await wait();const saved=reader.scrollTop;
row.style.height='2800px';await wait();
if(Math.abs(reader.scrollTop-saved)>3)throw Error('late layout interrupted reading');
"""
class Browser(base.Browser):
 def test_nine(self):
  with patch.object(base,'Fixture',Fixture),patch.object(base,'DRIVER',base.DRIVER.replace("out.textContent='PASS nine",EXTRA+"out.textContent='PASS follow, reading position, compact links; nine")):super().test_nine()

