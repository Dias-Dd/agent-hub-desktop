'use strict';
(()=>{
 const mac=!!window.__HUB_NATIVE_MACOS__&&!!window.webkit?.messageHandlers?.hubNative;
 if(!window.__HUB_NATIVE_WINDOWS__||(!mac&&!window.chrome?.webview))return;
 document.documentElement.classList.add('native-chrome',mac?'native-macos':'native-caption-buttons');
 const post=message=>mac?window.webkit.messageHandlers.hubNative.postMessage(message):window.chrome.webview.postMessage(message);
 window.HubNativeBackdrop=material=>{const root=document.documentElement;root.classList.toggle('native-backdrop',['mica','acrylic','sidebar'].includes(material));root.classList.toggle('native-mica',material==='mica');root.classList.toggle('native-acrylic',material==='acrylic');};
 window.HubNativeBackdrop(window.__HUB_NATIVE_BACKDROP__||(window.__HUB_NATIVE_MICA__?'mica':null));
 const bar=document.createElement('header');bar.id='nativeTitlebar';bar.setAttribute('aria-label','工作台标题栏');
 const controls=document.createElement('div');controls.className='titlebar-tools';
 const send=command=>post({type:'hub-window',command});
 function button(label,glyph,fn,cls=''){const b=document.createElement('button');b.type='button';b.title=label;b.setAttribute('aria-label',label);b.textContent=glyph;b.className='titlebar-button '+cls;b.addEventListener('click',fn);return b;}
 const sidebar=button('显示／隐藏项目列表','◫',()=>{
  const surface=document.querySelector('.workbench-content-surface'),list=document.getElementById('sidebarLeft'),before=surface.getBoundingClientRect();
  for(const element of [surface,list])for(const animation of element.getAnimations())animation.cancel();
  const collapsed=document.documentElement.classList.toggle('sidebar-collapsed');list.inert=collapsed;sidebar.setAttribute('aria-pressed',String(collapsed));
  if(matchMedia('(prefers-reduced-motion: reduce)').matches)return;
  const after=surface.getBoundingClientRect();
  if(after.width&&after.height)surface.animate([{transformOrigin:'0 0',transform:`translate(${before.left-after.left}px,${before.top-after.top}px) scale(${before.width/after.width},${before.height/after.height})`},{transformOrigin:'0 0',transform:'none'}],{duration:240,easing:'cubic-bezier(.22,.8,.25,1)'});
  if(!collapsed)list.animate([{opacity:0,transform:'translateX(-12px)'},{opacity:1,transform:'none'}],{duration:200,easing:'cubic-bezier(.22,.8,.25,1)'});
 });
 controls.append(sidebar);
 if(mac){
  const icon=(paths)=>{const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.5');svg.setAttribute('stroke-linejoin','round');for(const [tag,attrs] of paths){const node=document.createElementNS(svg.namespaceURI,tag);for(const [key,value] of Object.entries(attrs))node.setAttribute(key,value);svg.append(node);}return svg;};
  sidebar.replaceChildren(icon([['rect',{x:3,y:4,width:18,height:16,rx:3}],['path',{d:'M9 4v16'}]]));
  const cells=[];for(const y of [3,10,17])for(const x of [3,10,17])cells.push(['rect',{x,y,width:4,height:4,rx:0.7}]);
  document.getElementById('btnViewStatus')?.replaceChildren(icon(cells));
 }
 const brand=document.createElement('span');brand.className='titlebar-brand';brand.textContent=window.HubI18n?.t('搭班')||'搭班';
 const title=document.createElement('span');title.id='nativeProjectTitle';title.textContent='';
 const actions=document.createElement('div');actions.className='titlebar-actions';
 const system=document.createElement('div');system.className='titlebar-system';const maximize=button('最大化','□',()=>send('maximize'));
 if(!mac)system.append(button('最小化','−',()=>send('minimize')),maximize,button('关闭至托盘','×',()=>send('close'),'titlebar-close'));
 bar.append(controls,brand,title,actions,system);document.body.prepend(bar);
 const geometry=()=>{if(mac)return;const r=maximize.getBoundingClientRect(),rgb=value=>(value.match(/\d+/g)||[]).slice(0,3).map(Number);post({type:'hub-window',command:'caption-geometry',rect:[r.left,r.top,r.right,r.bottom],scale:devicePixelRatio,colors:[rgb(getComputedStyle(bar).backgroundColor),rgb(getComputedStyle(maximize).color)]});};
 new ResizeObserver(geometry).observe(bar);if(!mac)new ResizeObserver(geometry).observe(maximize);
 window.addEventListener('resize',geometry);window.visualViewport?.addEventListener('resize',geometry);requestAnimationFrame(geometry);
 new MutationObserver(geometry).observe(document.documentElement,{attributes:true,attributeFilter:['class','data-theme','data-color-mode']});
 bar.addEventListener('pointerdown',event=>{if(event.button===0&&!event.target.closest('button')){event.preventDefault();send('drag');}});
 bar.addEventListener('dblclick',event=>{if(!event.target.closest('button'))send('maximize');});
 if(!mac)document.addEventListener('pointerdown',event=>{if(event.button!==0)return;const edge=5,x=event.clientX,y=event.clientY;let side='';if(y<edge)side='top';else if(y>innerHeight-edge)side='bottom';if(x<edge)side+='left';else if(x>innerWidth-edge)side+='right';if(side){event.preventDefault();event.stopImmediatePropagation();send('resize:'+side);}},true);
 if(!mac)window.chrome.webview.addEventListener('message',event=>{if(event.data?.type==='hub-native-caption'){const width=event.data.width;for(const sheet of document.styleSheets){try{for(const rule of sheet.cssRules||[])if(rule.selectorText==='.native-caption-buttons #nativeTitlebar .titlebar-system')rule.style.width=width+'px';}catch{}}}if(event.data?.type==='hub-window-focus')bar.classList.toggle('is-inactive',!event.data.active);if(event.data?.type==='hub-window-state'){const full=event.data.maximized;maximize.textContent=full?'❐':'□';maximize.title=full?'还原':'最大化';maximize.setAttribute('aria-label',maximize.title);}});
 if(mac){
  const appearance=()=>post({type:'hub-window',command:'appearance',dark:document.documentElement.dataset.theme==='dark'||(!document.documentElement.dataset.theme&&matchMedia('(prefers-color-scheme:dark)').matches)});
  new MutationObserver(appearance).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
  matchMedia('(prefers-color-scheme:dark)').addEventListener('change',appearance);appearance();
 }
 const focusTitle=active=>bar.classList.toggle('is-inactive',!active);
 window.addEventListener('focus',()=>focusTitle(true));window.addEventListener('blur',()=>focusTitle(false));focusTitle(document.hasFocus());
 const start=()=>{const H=window.HubDesktop;if(!H){setTimeout(start,50);return;}H.store.subscribe(v=>{const id=H.client.getSelectedProjectId();const p=v.rawSnapshot?.projects?.find(p=>p.id===id);title.textContent=p?.name||'';});};start();
})();
