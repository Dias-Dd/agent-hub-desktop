/* Independent desktop windows share the original DOM, listeners and store.
   No second login, polling loop, model call or copy of project state. */
'use strict';
(() => {
 if(!window.__HUB_NATIVE_WINDOWS__)return;
 const lookup=document.getElementById.bind(document),entries=new Map();let serial=0,activeOwner='';
 const hidden=Object.getOwnPropertyDescriptor(HTMLElement.prototype,'hidden');
 const checked=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'checked');
 const originalClose=HTMLDialogElement.prototype.close;
 const specs={
  setupWizard:{title:window.__HUB_NATIVE_MACOS__?'首次配置':'模型接入配置',width:780,height:820},
  configModal:{title:'配置中心',width:1080,height:820,close:'btnCloseConfig'},
  designReviewDialog:{title:'产品演示与设计确认',width:1560,height:980,close:'closeDesignReview'},
  integrationsDialog:{title:'管理 Agent',width:720,height:780,close:'closeIntegrations'},
  agentDetailsDialog:{title:'Agent 详情',width:680,height:740},
  artifactViewer:{title:'Agent 成果',width:1280,height:880},
  chatSourceDialog:{title:'模型原始输入',width:980,height:760},
  newProjectDialog:{title:'项目设置',width:780,height:850,modal:true},
  projectCleanupDialog:{title:'清理项目文件',width:640,height:400,modal:true},
  deleteProjectDialog:{title:'删除项目',width:560,height:380,modal:true},
  tartAccessibilityDialog:{title:'控件操作 · Peekaboo',width:760,height:600,modal:true},
  tartDirectoryDialog:{title:'修改虚拟机目录',width:680,height:400,modal:true},
  tartInstallDialog:{title:'自动安装或导入虚拟机',width:720,height:820,modal:true},
  vmForceDialog:{title:'强制关闭虚拟机',width:560,height:380,modal:true},
  connectionTestDialog:{title:'确认接入测试',width:620,height:310,modal:true}
 };
 document.getElementById=function(id){const local=lookup(id);if(local)return local;for(const e of entries.values()){if(e.root.id===id)return e.root;const found=e.root.querySelector('#'+CSS.escape(id));if(found)return found;}return null;};
 function savePositions(root){return [root,...root.querySelectorAll('*')].filter(n=>n.scrollTop||n.scrollLeft).map(n=>[n,n.scrollLeft,n.scrollTop]);}
 function restorePositions(values){for(const [n,x,y]of values){n.scrollLeft=x;n.scrollTop=y;}}
 function notify(error){window.HubDesktop?.notice(error,'error');}
 function finish(e){
  if(e.finishing)return;e.finishing=true;
  const positions=savePositions(e.root),dialog=e.root instanceof HTMLDialogElement;
  // Return the exact nodes, including form values and event listeners.
  e.marker.replaceWith(e.root);e.root.removeAttribute('data-window-pending');e.root.removeAttribute('data-detached-window');
  if(dialog){e.root.removeAttribute('open');e.root.returnValue=e.returnValue||'';}
  else if(e.root.id==='configModal')checked.set.call(lookup('configModalToggle'),false);
  else hidden.set.call(e.root,true);
  e.themeObserver?.disconnect();e.noticeObserver?.disconnect();entries.delete(e.id);if(activeOwner===e.id)activeOwner='';
  restorePositions(positions);
  if(dialog)e.root.dispatchEvent(new Event('close'));
  else if(e.spec.close)document.getElementById(e.spec.close)?.click();
  if(e.root.id==='configModal')lookup('configModalToggle').dispatchEvent(new Event('change'));
  e.focus?.focus({preventScroll:true});
 }
 function close(root,value){const e=entries.get(root.id);if(!e)return false;e.returnValue=value;finish(e);if(e.win&&!e.win.closed)e.win.close();return true;}
 function open(root){
  if(!root.id)root.id='nativeDialog'+(++serial);
  const existing=entries.get(root.id);if(existing){existing.win?.focus();return;}
  const spec=specs[root.id]||{title:root.querySelector('h2,h3')?.textContent||'确认',width:700,height:600,modal:true};
  const marker=document.createComment('window '+root.id),focus=document.activeElement;
  root.before(marker);root.setAttribute('data-window-pending','');
  if(root instanceof HTMLDialogElement){root.setAttribute('open','');root.addEventListener('close',()=>{if(!root.open)close(root);},{once:true});}else hidden.set.call(root,false);
  const e={id:root.id,root,marker,spec,focus,win:null};entries.set(e.id,e);
  const params=new URLSearchParams({id:e.id,title:spec.title,modal:spec.modal?'1':'0',owner:activeOwner,width:String(spec.width),height:String(spec.height)});
  try{
   e.win=window.open('/popup.html#'+params,'hub-popup-'+e.id,'popup=yes,width='+spec.width+',height='+spec.height);
   if(!e.win){finish(e);notify('无法打开独立窗口，请允许此工作台打开窗口。');}
  }catch(error){finish(e);notify('独立窗口打开失败：'+error.message);}
 }
 HTMLDialogElement.prototype.showModal=function(){open(this);};
 HTMLDialogElement.prototype.show=function(){open(this);};
 HTMLDialogElement.prototype.close=function(value){if(!close(this,value))originalClose.call(this,value);};
 function watchHidden(id){const root=lookup(id);Object.defineProperty(root,'hidden',{configurable:true,get(){return hidden.get.call(this);},set(value){if(value){if(!close(this))hidden.set.call(this,true);}else open(this);}});}
 for(const id of ['designReviewDialog','integrationsDialog','setupWizard'])watchHidden(id);
 const toggle=lookup('configModalToggle');
 Object.defineProperty(toggle,'checked',{configurable:true,get(){return checked.get.call(this);},set(value){checked.set.call(this,value);if(value)open(document.getElementById('configModal'));else close(document.getElementById('configModal'));}});
 toggle.addEventListener('change',()=>{if(toggle.checked)open(document.getElementById('configModal'));else close(document.getElementById('configModal'));});
 // Native label default toggling does not call a JS property setter.
 for(const id of ['btnOpenConfig','btnCloseConfig'])lookup(id)?.addEventListener('click',event=>{event.preventDefault();toggle.checked=id==='btnOpenConfig';toggle.dispatchEvent(new Event('change'));});
 window.HubWindows={
  entries,
  attach(child,id){
   const e=entries.get(id);if(!e){child.close();return;}e.win=child;
   const positions=savePositions(e.root);child.document.body.append(e.root);e.root.removeAttribute('data-window-pending');e.root.setAttribute('data-detached-window','');
   e.root.setAttribute('aria-modal',String(!!e.spec.modal));child.document.title=(window.HubI18n?.t(e.spec.title)||e.spec.title)+' · Agent Hub';
   window.HubI18n?.attach(child.document,e.spec.title);
   const theme=()=>{for(const a of ['data-theme','class','style']){const value=document.documentElement.getAttribute(a);if(value===null)child.document.documentElement.removeAttribute(a);else child.document.documentElement.setAttribute(a,a==='class'?value.split(/\s+/).filter(c=>!['native-chrome','native-caption-buttons','native-mica','native-acrylic','native-backdrop','sidebar-collapsed'].includes(c)).join(' '):value);}child.document.body.className=document.body.className+' hub-window-body';};theme();
   e.themeObserver=new MutationObserver(theme);e.themeObserver.observe(document.documentElement,{attributes:true});e.themeObserver.observe(document.body,{attributes:true,attributeFilter:['class']});
   const notice=child.document.createElement('div');notice.id='notice';notice.setAttribute('role','status');child.document.body.append(notice);
   const mainNotice=lookup('notice');e.noticeObserver=new MutationObserver(()=>{notice.className=mainNotice.className;notice.textContent=mainNotice.textContent;});e.noticeObserver.observe(mainNotice,{childList:true,subtree:true,characterData:true,attributes:true});
   // Only keyboard events need to reach the existing global shortcuts. Node
   // click/input listeners travel with their DOM; do not dispatch them twice.
   child.document.addEventListener('keydown',event=>{
    if(event.key==='Escape'){event.preventDefault();if(e.root instanceof HTMLDialogElement){const cancel=new Event('cancel',{cancelable:true});if(!e.root.dispatchEvent(cancel))return;}close(e.root);return;}
    const copy=new KeyboardEvent('keydown',event);Object.defineProperty(copy,'target',{value:event.target});document.dispatchEvent(copy);if(copy.defaultPrevented)event.preventDefault();
   });
   const menu=child.document.createElement('nav');menu.className='detached-context-menu';menu.hidden=true;menu.setAttribute('role','menu');child.document.body.append(menu);
   let selectedText='';
   const dismiss=()=>{menu.hidden=true;};
   for(const [label,command] of [['复制','copy'],['全选','selectAll']]){const item=child.document.createElement('button');item.type='button';item.textContent=label;item.setAttribute('role','menuitem');item.addEventListener('click',async()=>{if(command==='copy'){try{await child.navigator.clipboard.writeText(selectedText);}catch{child.document.execCommand('copy');}}else{const range=child.document.createRange();range.selectNodeContents(e.root);const selection=child.getSelection();selection.removeAllRanges();selection.addRange(range);}dismiss();});menu.append(item);}
   child.document.addEventListener('contextmenu',event=>{
    if(event.target.closest('input,textarea,[contenteditable=true]')){dismiss();return;}
    event.preventDefault();selectedText=child.getSelection()?.toString()||'';menu.firstElementChild.disabled=!selectedText;menu.hidden=false;
    menu.style.left=Math.max(8,Math.min(event.clientX,child.innerWidth-168))+'px';menu.style.top=Math.max(8,Math.min(event.clientY,child.innerHeight-88))+'px';
   });
   child.document.addEventListener('pointerdown',event=>{if(!menu.contains(event.target))dismiss();});child.document.addEventListener('scroll',dismiss,true);child.addEventListener('blur',dismiss);child.addEventListener('keydown',event=>{if(event.key==='Escape')dismiss();});
   child.document.addEventListener('submit',event=>{const copy=new Event('submit',{cancelable:true});Object.defineProperty(copy,'target',{value:event.target});document.dispatchEvent(copy);if(copy.defaultPrevented){event.preventDefault();event.stopImmediatePropagation();}},true);
   child.document.addEventListener('focusin',()=>{activeOwner=e.id;});child.addEventListener('focus',()=>{activeOwner=e.id;});
   child.addEventListener('resize',()=>window.dispatchEvent(new Event('resize')));
   child.HubPopupClose=()=>close(e.root);
   child.addEventListener('pagehide',()=>finish(e),{once:true});
   child.requestAnimationFrame(()=>{restorePositions(positions);child.dispatchEvent(new Event('resize'));e.root.querySelector('input:not([type=hidden]):not([type=checkbox]),textarea,button:not(.dialog-close)')?.focus({preventScroll:true});});
  },closeAll(){for(const e of [...entries.values()])close(e.root);}
 };
 document.addEventListener('pointerdown',()=>{activeOwner='';},true);
 window.addEventListener('pagehide',()=>window.HubWindows.closeAll());
 setInterval(()=>{for(const e of [...entries.values()])if(e.win?.closed)finish(e);},1000);
 const pendingStyle=document.createElement('link');pendingStyle.rel='stylesheet';pendingStyle.href='/windows.css';document.head.append(pendingStyle);
})();
