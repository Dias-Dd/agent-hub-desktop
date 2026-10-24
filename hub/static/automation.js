"use strict";
(()=>{
 const H=window.HubDesktop;if(!H)return;
 const viewer=H.$('artifactViewer');
 H.bind('closeArtifactViewer','click',()=>viewer.close());
 viewer.addEventListener('close',()=>{if(!viewer.open)H.$('artifactViewerContent').replaceChildren();});
 function enlarge(item){H.text('artifactViewerTitle','Agent 成果');const content=H.$('artifactViewerContent');content.replaceChildren();viewer.classList.add('artifact-viewer-full');const media=H.node(item.kind==='image'?'img':'iframe');media.src=item.url;if(item.kind==='image')media.alt=item.caption||'图片';else{media.title=item.caption||'静态网页';media.setAttribute('sandbox','');}content.append(media);if(!viewer.open)viewer.showModal();}
 const states={scheduled:'等待到期',held:'已保留',finished:'已投递／结束',cancelled:'已取消',failed:'需要检查'};
 H.artifactMessage=item=>{
   if(item.kind==='folder'){
    const row=H.node('article','','shared-artifact artifact-attachment');row.dataset.artifact=item.id;
    const link=H.node('a','','artifact-web-link folder-link');if(/^\/api\/folder\/[a-f0-9]{64}$/.test(item.url))link.href=item.url;link.title=item.path||'打开文件夹';
    const icon=H.node('span','','folder-link-icon');icon.setAttribute('aria-hidden','true');const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.6');const outline=document.createElementNS(svg.namespaceURI,'path');outline.setAttribute('d','M3 7V5a1 1 0 0 1 1-1h5l2 3h9a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7Z M3 8h18');svg.append(outline);icon.append(svg);
    const words=H.node('span','','artifact-file-text');words.append(H.node('span',item.caption||item.entry,'artifact-file-title'),H.node('span',item.path||'在资源管理器中打开','artifact-file-description'));
    link.append(icon,words,H.node('span','↗','artifact-file-arrow'));
    link.addEventListener('click',async event=>{event.preventDefault();try{await H.client.postAction('artifact_open_folder',{artifact_id:item.id});}catch(error){H.notice(error.message,'error');}});
    const meta=H.node('footer','','chat-message-meta artifact-message-meta');meta.append(H.node('span',H.agentName(item.sender)+' → 用户'),H.chatTime(item.created));row.append(link,meta);return row;
   }
   const screenshot=item.entry==='screenshot.png'||String(item.caption||'').startsWith('浏览器实际渲染：');
   const inlineImage=item.kind==='image'&&!screenshot;
   const card=H.node('article','','shared-artifact');card.dataset.artifact=item.id;card.tabIndex=0;if(!inlineImage)card.classList.add('artifact-attachment');
   if(item.caption&&inlineImage)card.append(H.node('p',item.caption,'artifact-caption'));
   const footer=H.node('footer','','chat-message-meta artifact-message-meta');
   footer.append(H.node('span',H.agentName(item.sender)+' → 用户'),H.node('span',screenshot?'网页截图':item.kind==='image'?'图片':'网页'),H.chatTime(item.created));
   // Only server-generated relative capability URLs; never model-supplied markup.
   if(/^\/api\/shared\/[a-f0-9]{64}\//.test(item.url)){
    if(inlineImage){const image=H.node('img');image.src=item.url;image.alt=item.caption||'Agent 图片';image.loading='lazy';card.append(image);}
    else {
      const title=String(item.caption||(screenshot?'网页截图':'网页')).replace(/^浏览器实际渲染：[\s]*/,'');
      const link=H.node('a','','artifact-web-link');link.href=item.url;link.title='打开'+title;
      const icon=H.node('span','','artifact-file-icon');icon.setAttribute('aria-hidden','true');
      const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.5');
      const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d',screenshot?'M5 4h14v16H5z M8 8h8 M8 15l3-3 2 2 3-4':'M4 5h16v14H4z M4 9h16 M7 7h.01 M10 7h.01');svg.append(path);icon.append(svg);
      const words=H.node('span','','artifact-file-text');words.append(H.node('span',title,'artifact-file-title'),H.node('span',screenshot?'网页截图 · 点击查看':'网页 · 点击打开','artifact-file-description'));
      const arrow=H.node('span','↗','artifact-file-arrow');arrow.setAttribute('aria-hidden','true');link.append(icon,words,arrow);
      link.addEventListener('click',event=>{event.preventDefault();enlarge(item);});card.append(link);
    }
    const label=item.kind==='image'?'放大图片':'放大查看网页';const enlargeButton=H.button('↗',()=>enlarge(item));enlargeButton.className='chat-copy artifact-enlarge';enlargeButton.title=label;enlargeButton.setAttribute('aria-label',label);if(inlineImage)footer.append(enlargeButton);
    const copy=H.node('button','⧉','chat-copy artifact-copy');copy.type='button';copy.title=item.kind==='image'?'复制图片链接':'复制网页链接';copy.setAttribute('aria-label',copy.title);copy.addEventListener('click',()=>H.copyChat(new URL(item.url,H.client.baseUrl||location.origin).href,copy));footer.append(copy);
   }else card.append(H.node('p','展示地址暂不可用','muted'));
   card.append(footer);return card;
 };
 H.artifactItems=s=>{
  const workflows=[...(s.workflows||[])].sort((a,b)=>(a.created||0)-(b.created||0));
  return (s.shared_artifacts||[]).filter(item=>{
   if(item.kind!=='webpage')return true;
   if(item.presentation==='design_review'||item.design_id)return false;
   const direct=workflows.find(w=>w.id===item.workflow_id);
   return !(direct||workflows.filter(w=>(w.created||0)<=(item.created||0)).at(-1))?.design_review;
  });
 };
 let timerSignature='',dismissProject='',dismissed=new Set();
 const timerKey=t=>t.id+':'+(t.generation||t.created||0);
 const timerClock=seconds=>{const n=Math.max(0,Math.ceil(seconds));return [Math.floor(n/3600),Math.floor(n%3600/60),n%60].map(x=>String(x).padStart(2,'0')).join(':');};
 function tickTimers(){for(const clock of document.querySelectorAll('#timerList .timer-countdown')){const active=['scheduled','held','failed'].includes(clock.dataset.state);const seconds=active?Math.max(0,Number(clock.dataset.due)-Date.now()/1000):0;const label=timerClock(seconds);if(clock.textContent!==label)clock.textContent=label;}}
 setInterval(()=>{if(!document.hidden)tickTimers();},1000);document.addEventListener('visibilitychange',tickTimers);
 function dismissTimer(t,button){button.disabled=true;Promise.resolve(['scheduled','held','failed'].includes(t.state)?H.action('timer_cancel',{timer_id:t.id}):null).then(()=>{dismissed.add(timerKey(t));try{localStorage.setItem('hub.dismissedTimers.'+dismissProject,JSON.stringify([...dismissed].slice(-500)));}catch{}timerSignature='';return H.store.refresh(true);}).catch(error=>{button.disabled=false;const card=button.closest('.timer-row');let note=card.querySelector('.timer-error');if(!note){note=H.node('p','','timer-error');card.append(note);}note.textContent=error.message;});}
 H.render(v=>{
  const s=v.rawSnapshot||{};
  if(!H.$('timerList'))return;
  H.$('sharedArtifacts').hidden=true;
  const project=s.selected_project||H.client.getSelectedProjectId()||'default';
  if(project!==dismissProject){dismissProject=project;try{const values=JSON.parse(localStorage.getItem('hub.dismissedTimers.'+project)||'[]');dismissed=new Set(Array.isArray(values)?values:[]);}catch{dismissed=new Set();}timerSignature='';}
  const timers=[...(s.timers||[])].filter(t=>['scheduled','held','failed'].includes(t.state)&&!dismissed.has(timerKey(t))).sort((a,b)=>Number(['scheduled','held','failed'].includes(b.state))-Number(['scheduled','held','failed'].includes(a.state))||a.due-b.due),notices=s.pending_notifications||[],active=timers.filter(t=>['scheduled','held','failed'].includes(t.state)).length,pending=notices.filter(n=>n.state==='pending').length;
  H.text('timerCount',String(active));H.text('pendingNoticeCount',String(pending));H.text('automationSummary',active+' 个待执行提醒 · '+pending+' 条待交付通知');
  const names=new Map((v.agents||[]).map(a=>[a.id,a.name||a.id]));names.set('user','用户');
  const signature=JSON.stringify([project,timers,[...names]]);
  if(signature!==timerSignature){timerSignature=signature;
   H.list('timerList',timers.length?timers.map(t=>{
    const row=H.node('article','','timer-row timer-ios-card');row.dataset.timer=t.id;
    const label=H.node('span',t.condition==='quota_recovered'?'等待额度恢复':states[t.state]||t.state,'timer-state');row.append(label);
    const close=H.button('×',()=>dismissTimer(t,close));close.className='timer-dismiss';close.title=['scheduled','held','failed'].includes(t.state)?'取消并移除此计时器':'移除此记录';close.setAttribute('aria-label',close.title);row.append(close);
    const clock=H.node('div','','timer-countdown');clock.dataset.due=String(t.due);clock.dataset.state=t.state;clock.setAttribute('role','timer');clock.setAttribute('aria-live','off');row.append(clock);
    row.append(H.node('p',t.note||'没有附言','timer-note'));
    const route=H.node('div','','timer-route');const sender=names.get(t.creator)||t.creator||'平台',recipient=names.get(t.recipient)||t.recipient||'当前经理';route.append(H.node('span',sender,'timer-sender'),H.node('span','→','timer-route-arrow'),H.node('span',recipient,'timer-recipient'));route.title='发送方：'+sender+'；接收方：'+recipient;row.append(route);
    const due=H.node('small',new Date(t.due*1000).toLocaleString()+(t.interval?' · 每 '+timerClock(t.interval)+' 重复':''),'timer-due');row.append(due);
    if(t.wait_for_agent)row.append(H.node('p','等待 '+(names.get(t.wait_for_agent)||t.wait_for_agent),'timer-condition'));if(t.reason)row.append(H.node('p',t.reason,'timer-condition'));
    return row;
   }):[H.node('p','暂无计时器','muted')]);
  }
  tickTimers();
  const kinds={agent_config_changed:'配置变更',quota_wait:'额度不足',quota_resume:'额度恢复检查',quota_recovered:'额度恢复',quota_low:'额度预警',message:'消息',result:'工作汇报',timer:'定时提醒',control:'调度提醒'};
  H.list('pendingNotices',notices.length?notices.map(n=>{const row=H.node('details','','pending-notice');row.open=true;row.dataset.detailKey='notice_'+n.id;row.append(H.node('summary',H.agentName(n.source||'平台')+' → '+H.agentName(n.recipient)+' · '+(kinds[n.category]||n.category)+' · '+(n.state==='processing'?'已排入经理回合':'待交付')));if(n.created)row.append(H.node('small',new Date(n.created*1000).toLocaleString()));row.append(H.node('pre',n.body,'pending-notice-body'));return row;}):[H.node('p','暂无积累的通知','muted')]);
 });
})();
