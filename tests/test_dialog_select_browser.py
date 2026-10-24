import test_nine_browser as base
from test_project_menu_browser import MenuFixture
from unittest.mock import patch
EXTRA="""H.deleteProject(H.view.rawSnapshot.projects[0]);const d=document.getElementById('deleteProjectDialog'),b=d.getBoundingClientRect(),footer=d.querySelector('footer');if(b.width>450||b.left<0||b.right>innerWidth||b.top<0||b.bottom>innerHeight)throw Error('dialog size/position');if(!footer||footer.children.length!==2)throw Error('missing actions');if(document.activeElement.textContent!=='保留项目')throw Error('unsafe default focus');if(!CSS.supports('appearance','base-select'))throw Error('custom picker unavailable');const select=document.getElementById('workflowPreviewMode');if(getComputedStyle(select).appearance!=='base-select')throw Error('picker style not active');"""
class PolishBrowser(base.Browser):
 def test_nine(self):
  with patch.object(base,'Fixture',MenuFixture),patch.object(base,'DRIVER',base.DRIVER.replace("out.textContent='PASS nine",EXTRA+"out.textContent='PASS dialog polish and customizable selects; nine")):super().test_nine()
