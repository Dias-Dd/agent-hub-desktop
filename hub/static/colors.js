"use strict";
(()=>{
 const root=document.documentElement,fields=[['--bg-app','聊天与内容区'],['--bg-sidebar','侧栏'],['--bg-card','卡片'],['--bg-panel','面板'],['--bg-inset','输入框'],['--text-main','正文'],['--accent','强调色']];
 const key='hub.interfaceColors.v2',system=matchMedia('(prefers-color-scheme: dark)');
 const mode=()=>root.dataset.theme==='dark'?'dark':root.dataset.theme==='light'?'light':system.matches?'dark':'light';
 let palettes={light:{},dark:{}};try{const value=JSON.parse(localStorage.getItem(key)||'null');if(value&&typeof value==='object')palettes={light:value.light||{},dark:value.dark||{}};else{const old=JSON.parse(localStorage.getItem('hub.interfaceColors.v1')||'{}');if(old&&typeof old==='object'){palettes[mode()]=old;localStorage.setItem(key,JSON.stringify(palettes));}}}catch{}
 const valid=value=>typeof value==='string'&&/^#[0-9a-f]{6}$/i.test(value);
 const saved=(theme=mode())=>palettes[theme];
 function apply(){for(const [token] of fields){if(valid(saved()[token]))root.style.setProperty(token,saved()[token]);else root.style.removeProperty(token);}}
 apply();
 const grid=document.getElementById('interfaceColors');if(!grid)return;
 function defaultHex(token){
  const raw=getComputedStyle(root).getPropertyValue(token).trim();
  if(/^#[0-9a-f]{6}$/i.test(raw))return raw.toLowerCase();
  if(/^#[0-9a-f]{3}$/i.test(raw))return '#'+[...raw.slice(1)].map(c=>c+c).join('').toLowerCase();
  const canvas=document.createElement('canvas');canvas.width=canvas.height=1;
  const probe=document.createElement('span');probe.style.color=getComputedStyle(root).getPropertyValue(token);document.body.append(probe);
  const context=canvas.getContext('2d');context.fillStyle=getComputedStyle(probe).color;probe.remove();context.fillRect(0,0,1,1);
  return '#'+Array.from(context.getImageData(0,0,1,1).data).slice(0,3).map(n=>n.toString(16).padStart(2,'0')).join('');
 }
 const defaults={light:{},dark:{}};
 function captureDefaults(){
  const originalTheme=root.getAttribute('data-theme');
  for(const theme of ['light','dark']){for(const [token] of fields)root.style.removeProperty(token);root.dataset.theme=theme;for(const [token] of fields)defaults[theme][token]=defaultHex(token);}
  if(originalTheme===null)root.removeAttribute('data-theme');else root.dataset.theme=originalTheme;apply();
 }
 captureDefaults();
 const make=(tag,cls='',text='')=>{const n=document.createElement(tag);n.className=cls;n.textContent=text;return n;};
 const picker=make('div','hub-color-picker');picker.id='interfaceColorPicker';picker.setAttribute('popover','auto');picker.setAttribute('aria-label','选择界面颜色');grid.after(picker);
 const heading=make('strong','','选择颜色'),square=make('div','color-saturation'),marker=make('span','color-marker');square.append(marker);square.tabIndex=0;square.setAttribute('role','slider');square.setAttribute('aria-label','饱和度与亮度，左右调整饱和度，上下调整亮度');
 const hue=make('input','color-hue');hue.type='range';hue.autocomplete='off';hue.min='0';hue.max='360';hue.setAttribute('aria-label','色相');
 const hex=make('input','color-hex');hex.type='text';hex.autocomplete='off';hex.maxLength=7;hex.setAttribute('aria-label','十六进制颜色');hex.spellcheck=false;
 const presets=make('div','color-presets');picker.append(heading,square,hue,hex,presets);
 let chosen=null,h=0,sat=0,val=1;
 function rgb(){const c=val*sat,x=c*(1-Math.abs((h/60)%2-1)),m=val-c;const channels=h<60?[c,x,0]:h<120?[x,c,0]:h<180?[0,c,x]:h<240?[0,x,c]:h<300?[x,0,c]:[c,0,x];return '#'+channels.map(n=>Math.round((n+m)*255).toString(16).padStart(2,'0')).join('');}
 function fromHex(color){const r=parseInt(color.slice(1,3),16)/255,g=parseInt(color.slice(3,5),16)/255,b=parseInt(color.slice(5,7),16)/255,max=Math.max(r,g,b),min=Math.min(r,g,b),d=max-min;h=d?(max===r?60*(((g-b)/d+6)%6):max===g?60*((b-r)/d+2):60*((r-g)/d+4)):h;sat=max?d/max:0;val=max;}
 function paint(){hue.value=String(h);square.style.setProperty('--picker-hue',h);marker.style.left=(sat*100)+'%';marker.style.top=((1-val)*100)+'%';hex.value=rgb().toUpperCase();square.setAttribute('aria-valuetext',hex.value);}
 function commit(color){if(!chosen||!valid(color))return;chosen.value=color;chosen.dispatchEvent(new Event('input',{bubbles:true}));}
 function change(){paint();commit(rgb());}
 function point(event){const r=square.getBoundingClientRect();sat=Math.max(0,Math.min(1,(event.clientX-r.left)/r.width));val=1-Math.max(0,Math.min(1,(event.clientY-r.top)/r.height));change();}
 square.addEventListener('pointerdown',event=>{square.setPointerCapture(event.pointerId);point(event);});square.addEventListener('pointermove',event=>{if(square.hasPointerCapture(event.pointerId))point(event);});
 square.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key))return;event.preventDefault();if(event.key==='ArrowLeft')sat-=.02;if(event.key==='ArrowRight')sat+=.02;if(event.key==='ArrowUp')val+=.02;if(event.key==='ArrowDown')val-=.02;sat=Math.max(0,Math.min(1,sat));val=Math.max(0,Math.min(1,val));change();});
 hue.addEventListener('input',()=>{h=Number(hue.value);change();});hex.addEventListener('input',()=>{if(valid(hex.value)){fromHex(hex.value);commit(hex.value);paint();}});
 for(const color of ['#00796b','#6086d6','#8c6bc2','#c47c53','#ca596a','#1c2427','#f5f7f6','#ffffff']){const button=make('button','color-preset');button.type='button';button.style.backgroundColor=color;button.setAttribute('aria-label','选择 '+color);button.addEventListener('click',()=>{fromHex(color);change();});presets.append(button);}
 function refresh(){for(const input of grid.querySelectorAll('input[data-token]')){input.value=valid(saved(input.dataset.mode)[input.dataset.token])?saved(input.dataset.mode)[input.dataset.token]:defaults[input.dataset.mode][input.dataset.token];const row=input.parentElement;row.querySelector('.interface-color-value').textContent=input.value.toUpperCase();row.querySelector('.interface-color-swatch').style.backgroundColor=input.value;}}
 for(const theme of ['light','dark']){const section=make('section','interface-color-theme'),title=make('h4','',theme==='light'?'浅色模式':'深色模式');section.dataset.palette=theme;section.append(title);grid.append(section);for(const [token,name] of fields){const label=make('div','interface-color-row'),input=make('input'),text=make('span','',name),code=make('span','interface-color-value'),button=make('button','interface-color-button'),swatch=make('span','interface-color-swatch');input.type='hidden';input.dataset.token=token;input.dataset.mode=theme;button.type='button';button.setAttribute('aria-label',name+'颜色');button.append(swatch);input.addEventListener('input',()=>{saved(theme)[token]=input.value;apply();try{localStorage.setItem(key,JSON.stringify(palettes));}catch{}refresh();});button.addEventListener('click',()=>{chosen=input;heading.textContent=name;fromHex(input.value);paint();picker.showPopover();const box=button.getBoundingClientRect(),win=button.ownerDocument.defaultView;picker.style.left=Math.max(8,Math.min(box.right-248,win.innerWidth-260))+'px';picker.style.top=Math.max(8,Math.min(box.bottom+8,win.innerHeight-330))+'px';});label.append(text,code,button,input);section.append(label);}}
 document.getElementById('resetInterfaceColors').addEventListener('click',()=>{palettes={light:{},dark:{}};apply();localStorage.setItem(key,JSON.stringify(palettes));refresh();});
 function themeChanged(){picker.hidePopover();chosen=null;apply();refresh();const label=document.getElementById('colorModeLabel');if(label)label.textContent='浅色与深色配色独立保存；当前主题即时预览。';}
 const loadedDefaults=()=>{captureDefaults();themeChanged();};
 if(document.readyState==='complete')setTimeout(loadedDefaults,0);else window.addEventListener('load',loadedDefaults,{once:true});
 window.addEventListener('hub-settings-section',()=>{if(!document.getElementById('colorSettings').classList.contains('settings-section-inactive'))loadedDefaults();});
 new MutationObserver(themeChanged).observe(root,{attributes:true,attributeFilter:['data-theme']});system.addEventListener('change',themeChanged);themeChanged();
})();
