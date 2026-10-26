"use strict";
(()=>{
 const H=window.HubDesktop;if(!H)return;const $=id=>H.$(id);let renderLoaded=false,notifyLoaded=false,poll=null,busy=false;
 const api=(action,args)=>{H.ready();return H.client.postAction(action,args);};
 const visible=id=>$('configModalToggle').checked&&!$(id).classList.contains('settings-section-inactive')&&!document.hidden;
 const work=async(fn)=>{if(busy)return;busy=true;try{await fn();}catch(e){H.notice(e.message,'error');}finally{busy=false;}};
 function download(value){
  const active=['downloading','installing'].includes(value?.state);$('renderCancel').hidden=!active;$('renderDownload').disabled=active;
  const progress=$('renderDownloadProgress');progress.hidden=!active;
  if(value?.total)progress.value=Math.round(value.received/value.total*100);else progress.removeAttribute('value');
  const labels={idle:'',downloading:'正在下载 Chromium',installing:'正在校验并安装 Chromium',completed:'Chromium 已安装，可在上方选择使用',cancelled:'下载已取消',failed:'下载失败'};
  $('renderDownloadStatus').textContent=(value?.retrying?'网络中断，正在重试':labels[value?.state]||'')+(value?.total?' · '+Math.round(value.received/value.total*100)+'%':'')+(value?.error?' · '+value.error:'');
  clearTimeout(poll);if(active&&visible('renderSettings'))poll=setTimeout(()=>loadRender(false).catch(e=>H.notice(e.message,'error')),1500);
 }
 async function loadRender(fill=false){
  const value=await api('render_settings',{operation:'read'});if(!value.config)return;
  const select=$('renderBrowserChoice'),previous=select.value;
  select.replaceChildren(new Option('自动选择','auto'),...(value.browsers||[]).map(b=>new Option(b.name,'installed:'+b.path)),new Option('指定 Chromium 主程序','custom'));
  if(value.managed)select.add(new Option('应用专用 Chromium · '+value.managed.revision,'managed'));
  const selected=fill?(value.config.mode==='installed'?'installed:'+value.config.path:value.config.mode):previous;
  if(selected.startsWith('installed:')&&![...select.options].some(o=>o.value===selected))select.add(new Option('已保存的浏览器（未检测到）',selected));
  select.value=[...select.options].some(o=>o.value===selected)?selected:'auto';if(fill)$('renderBrowserPath').value=value.config.path||'';
  $('renderCustomPath').hidden=select.value!=='custom';$('renderCurrent').textContent=value.current?'当前主程序：'+value.current:value.error||'没有可用浏览器';
  renderLoaded=true;download(value.download);
 }
 $('renderBrowserChoice').addEventListener('change',()=>{$('renderCustomPath').hidden=$('renderBrowserChoice').value!=='custom';});
 $('renderBrowserForm').addEventListener('submit',e=>{e.preventDefault();work(async()=>{const choice=$('renderBrowserChoice').value;await api('render_settings',{operation:'save',mode:choice.startsWith('installed:')?'installed':choice,path:choice.startsWith('installed:')?choice.slice(10):$('renderBrowserPath').value});await loadRender(true);H.notice('渲染设置已保存');});});
 $('renderDetect').addEventListener('click',()=>work(()=>loadRender(false)));
 $('renderBrowse').addEventListener('click',()=>work(async()=>{const value=await api('render_settings',{operation:'browse'});if(value.path)$('renderBrowserPath').value=value.path;}));
 $('renderDownload').addEventListener('click',()=>work(async()=>{await api('render_settings',{operation:'download'});await loadRender(false);}));
 $('renderCancel').addEventListener('click',()=>work(async()=>{await api('render_settings',{operation:'cancel'});await loadRender(false);}));
 $('renderTest').addEventListener('click',()=>work(async()=>{await api('render_settings',{operation:'test'});H.notice('渲染测试通过（使用已保存的浏览器设置）');}));
 async function loadNotifications(){const cfg=await api('notification_settings',{operation:'read'});if(typeof cfg.enabled!=='boolean')return;$('notificationsEnabled').checked=cfg.enabled;$('notificationWhen').value=cfg.when;$('notifyDemo').checked=cfg.demo;$('notifyProject').checked=cfg.project;$('notifyAttention').checked=cfg.attention;notifyLoaded=true;}
 $('notificationForm').addEventListener('submit',e=>{e.preventDefault();work(async()=>{await api('notification_settings',{operation:'save',config:{enabled:$('notificationsEnabled').checked,when:$('notificationWhen').value,demo:$('notifyDemo').checked,project:$('notifyProject').checked,attention:$('notifyAttention').checked}});$('notificationSaveStatus').textContent='通知设置已保存';});});
 $('notificationTest').addEventListener('click',()=>work(async()=>{await api('notification_settings',{operation:'test'});$('notificationSaveStatus').textContent='测试通知已提交，请查看系统通知中心';}));
 function opened(){if(visible('renderSettings'))work(()=>loadRender(!renderLoaded));else clearTimeout(poll);if(visible('notificationSettings')&&!notifyLoaded)work(loadNotifications);}
 window.addEventListener('hub-settings-section',opened);$('configModalToggle').addEventListener('change',opened);document.addEventListener('visibilitychange',opened);
})();
