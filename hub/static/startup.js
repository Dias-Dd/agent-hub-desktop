"use strict";
(() => {
  const H=window.HubDesktop,$=H.$;
  if(!document.querySelector('meta[name="hub-desktop-session"]'))return;
  let ready=false,snapshot=null,vmConnected=false;
  const pure=new Set(['btnViewChat','btnViewStatus','btnOpenConfig','btnCloseConfig','tabManagerChat','tabGroupChat','tabProjectStatus','toggleGroupComposer','resetInterfaceColors','toggleQuotaQuick']);
  function local(button){return pure.has(button.id)||button.id.startsWith('themeMode')||button.classList.contains('dialog-close')||button.classList.contains('titlebar-button');}
  function gate(){
    const roots=[document,...[...(window.HubWindows?.entries?.values()||[])].map(entry=>entry.root)];
    roots.flatMap(root=>[...root.querySelectorAll('button')]).forEach(button=>{
      if(local(button))return;
      if(!ready&&!button.inert){button.inert=true;button.dataset.startupInert='true';button.classList.add('startup-pending');}
      if(ready&&button.dataset.startupInert){button.inert=false;delete button.dataset.startupInert;button.classList.remove('startup-pending');}
    });
  }
  const observer=new MutationObserver(gate);observer.observe(document.body,{childList:true,subtree:true});
  document.addEventListener('submit',event=>{if(!ready){event.preventDefault();event.stopImmediatePropagation();}},true);
  H.store.subscribe(view=>{const next=!!view.rawSnapshot&&H.client.hasToken();if(next!==ready){ready=next;gate();if(ready)observer.disconnect();else observer.observe(document.body,{childList:true,subtree:true});}});
  let fade=null,finished=false;
  const cleanLabel=label=>String(label||'').replace(/（[^）]*）|\([^)]*\)/g,'').trim();
  function render(){
    if(!snapshot)return;
    const stages=Object.entries(snapshot.stages||{}).map(([key,value])=>key==='vm'&&vmConnected?{state:'ready',label:'虚拟机已连接'}:value);
    const done=stages.filter(stage=>['ready','failed','skipped'].includes(stage.state)).length;
    const complete=stages.length>0&&stages.every(stage=>['ready','skipped'].includes(stage.state));
    const progress=$('startupProgress');
    if(complete&&!finished){finished=true;fade=progress.animate([{opacity:1},{opacity:0}],{duration:240,easing:'ease-out'});fade.onfinish=()=>{progress.hidden=true;};}
    if(!complete){finished=false;fade?.cancel();progress.hidden=false;}
    $('startupBar').value=1+done;
    const active=stages.find(stage=>stage.state==='loading')||stages.find(stage=>stage.state==='failed');
    $('startupLabel').textContent=active?cleanLabel(active.label):'服务加载完成';
    $('startupProgress').title=stages.map(stage=>cleanLabel(stage.label)).join('\n');
  }
  window.addEventListener('hub-vm-status',event=>{vmConnected=!!event.detail.connected&&event.detail.desktop?.ready!==false&&!event.detail.unattended?.warning;render();});
  let pending=false,timer=null;
  async function poll(){
    if(pending)return;pending=true;
    try{const response=await fetch('/startup-status',{cache:'no-store'});if(response.ok){snapshot=await response.json();render();}}
    catch(_){}finally{pending=false;if(snapshot&&Object.values(snapshot.stages||{}).every(stage=>['ready','failed','skipped'].includes(stage.state))&&timer){clearInterval(timer);timer=null;}}
  }
  requestAnimationFrame(()=>requestAnimationFrame(()=>void fetch('/startup-ui-ready',{method:'POST',headers:{'Content-Type':'application/json','X-Desktop-Session':document.querySelector('meta[name="hub-desktop-session"]').content},body:'{}'}).catch(()=>{})));
  gate();timer=setInterval(poll,1000);void poll();
})();
