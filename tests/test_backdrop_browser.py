from unittest.mock import patch
import test_nine_browser as base

CHECK=r"""
window.__HUB_NATIVE_WINDOWS__=true;window.__HUB_NATIVE_BACKDROP__='acrylic';
window.chrome.webview={postMessage(){},addEventListener(){}};
await new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='/titlebar.js';script.onload=resolve;script.onerror=reject;document.head.append(script);});
const root=document.documentElement;
if(!root.classList.contains('native-acrylic')||!root.classList.contains('native-backdrop')||root.classList.contains('native-mica'))throw Error('Acrylic capability ignored');
if(getComputedStyle(document.getElementById('nativeTitlebar')).backgroundColor!=='rgba(0, 0, 0, 0)')throw Error('Acrylic hidden behind titlebar paint');
if(getComputedStyle(document.getElementById('workbenchCenter')).backgroundColor==='rgba(0, 0, 0, 0)')throw Error('Reading canvas became transparent');
window.HubNativeBackdrop('mica');
if(!root.classList.contains('native-mica')||root.classList.contains('native-acrylic'))throw Error('Mica selection failed');
window.HubNativeBackdrop(null);
if(root.classList.contains('native-backdrop')||root.classList.contains('native-acrylic')||root.classList.contains('native-mica'))throw Error('Solid fallback retained transparency');
"""


class Browser(base.Browser):
    def test_nine(self):
        with patch.object(base,'DRIVER',base.DRIVER.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")):
            super().test_nine()
