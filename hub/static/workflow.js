'use strict';
(() => {
  const H = window.HubDesktop;
  let miniSignature='';
  function measureMiniNames(){for(const name of document.querySelectorAll('.agent-mini-name')){const overflow=name.firstElementChild.scrollWidth>name.clientWidth+1;name.classList.toggle('is-overflowing',overflow);name.tabIndex=overflow?0:-1;}}
  const miniResize=new ResizeObserver(()=>requestAnimationFrame(measureMiniNames));if(document.getElementById('agentMiniStates'))miniResize.observe(document.getElementById('agentMiniStates'));

  const { $, store, node, value, checked, number, text, bind, list, record, longText } = H;
  let fresh = false, startingPlan = false;
  let project = H.client.getSelectedProjectId();
  const session = () => fresh ? null : H.view.managerStream.planning;
  const workflow = () => H.view.managerStream.workflow;
  function settings() {
    return { preview_mode:value('workflowPreviewMode') || 'demo', cwd:value('workflowCwd'), agents:[...$('workflowAgents').querySelectorAll('input')].filter(c => c.checked && c.value !== H.view.managerStream.manager).map(c => c.value), max_calls:number('workflowMax'), expires_minutes:Math.round(number('workflowExpires') * 1440), max_parallel:number('workflowParallel'), max_seconds:Math.round(number('workflowTaskMinutes') * 60), reviewer:value('workflowReviewer'), delegate_stop:checked('workflowDelegateStop'), max_hops:number('workflowHops'), max_messages:number('workflowMessages') };
  }
  H.projectSettings=settings;
  bind('managerPatrolForm','submit',async()=>{await H.action('manager_patrol_config',{enabled:$('managerPatrolEnabled').checked,interval_minutes:Number($('managerPatrolMinutes').value)});H.notice('巡检设置已保存','status');});
  let patrolSignature=null;
  H.render(v=>{const cfg=v.rawSnapshot?.manager_patrol;if(!cfg)return;const signature=JSON.stringify(cfg);if(signature===patrolSignature)return;patrolSignature=signature;$('managerPatrolEnabled').checked=cfg.enabled;$('managerPatrolMinutes').value=cfg.interval_minutes;});
  list('workflowAgents', ALL_AGENT_IDS.filter(id => id !== H.view.managerStream.manager).map(id => {
    const label = node('label',id,'setupConsent'), c = node('input'); c.type = 'checkbox'; c.value = id; label.prepend(c); return label;
  }));
  bind('workflowForm','submit', async () => {
    const selected=H.view.rawSnapshot?.projects?.find(p=>p.id===H.client.getSelectedProjectId());
    if(!selected)throw Error('请先通过左侧新建项目按钮创建项目');
    const options=H.projectDiscussionOptions?H.projectDiscussionOptions(selected):settings();
    if(startingPlan)return;
    const projectId=H.client.getSelectedProjectId();startingPlan=true;render(H.view);
    try {
      await store.sendPlanChat({body:value('workflowRequirement'), options, confirmed:true});
      if(projectId===H.client.getSelectedProjectId()){fresh=false;$('workflowConfirm').checked=false;}
    } finally {startingPlan=false;render(H.view);}
  });
  let sendingInput=false, insertingInput=false;
  const armedInputs=new Map();
  const inputKey=()=>H.client.getSelectedProjectId()+':'+session()?.sessionId;
  function pendingInputs(){
    const manager=H.view.managerStream.manager;
    const pending=(H.view.rawSnapshot?.messages||[]).filter(m=>m.sender==='user'&&m.recipient===manager&&m.status==='pending'&&!m.body.startsWith('[task:')).map(m=>m.id);
    return [...new Set([...pending,...(armedInputs.get(inputKey())||[])])];
  }
  function managerBusy(){
    const manager=H.view.managerStream.manager;
    return !!session()?.pending || [...(H.view.rawSnapshot?.deepseek?.runs||[]),...(H.view.rawSnapshot?.integration_runs||[])].some(r=>r.agent===manager&&['queued','running','interrupting','waiting_quota'].includes(r.status));
  }
  function updateSendButton(){
    const hasText=!!value('discussionReply').trim(),busy=managerBusy(),insert=busy&&!hasText&&pendingInputs().length>0;
    const mode=insert?'interrupt':busy?'queue':'send';
    const label=insertingInput?'正在请求插入，等待确认':sendingInput?'正在发送':insert?'中断经理当前轮次，并优先插入已排队消息':busy?'排队发送；经理结束当前轮次后处理':'发送给经理';
    const button=$('discussionSend');button.dataset.mode=mode;button.title=label;button.setAttribute('aria-label',label);button.setAttribute('aria-busy',String(sendingInput||insertingInput));
    button.disabled=sendingInput||insertingInput||(!hasText&&!insert)||!session();
    $('managerSendIconPath').setAttribute('d',mode==='send'?'M12 20V4m-7 7 7-7 7 7':mode==='queue'?'M4 5h11M4 10h11M4 15h6m8-5v10m-4-4 4 4 4-4':'M4 4h7v7H4zM20 5v10a4 4 0 0 1-4 4h-5m4-4-4 4 4 4');
  }
  $('discussionReply').addEventListener('input',updateSendButton);
  $('discussionReplyForm').addEventListener('submit',async event=>{
    event.preventDefault();if(sendingInput||insertingInput)return;
    const p=session();if(!p)return;
    const reply=value('discussionReply').trim(),key=inputKey(),projectId=H.client.getSelectedProjectId();
    if(!reply){
      const ids=pendingInputs();if(!managerBusy()||!ids.length)return;
      insertingInput=true;updateSendButton();
      try {const result=await H.client.postAction('manager_interrupt',{session_id:p.sessionId,message_ids:ids});armedInputs.delete(key);void store.refresh(true).catch(()=>{});H.notice(result.note,'status');}
      catch(error){H.notice(error.message);}
      finally {insertingInput=false;updateSendButton();}
      return;
    }
    sendingInput=true;updateSendButton();
    $('discussionReply').value='';$('discussionReply').dispatchEvent(new Event('input',{bubbles:true}));text('discussionReplyCount','0 / 20,000 字符');
    try {
      const result=await H.client.postAction('manager_message',{session_id:p.sessionId,revision:p.revision,body:reply,request_key:H.client.generateRequestKey()});
      if(result.queued)armedInputs.set(key,[...(armedInputs.get(key)||[]),...(result.message_ids||[])]);
      void store.refresh(true).catch(()=>{});
    } catch(error){
      if(projectId===H.client.getSelectedProjectId()&&key===inputKey()){$('discussionReply').value=reply+(value('discussionReply')?'\n\n'+value('discussionReply'):'');$('discussionReply').dispatchEvent(new Event('input',{bubbles:true}));}
      H.notice(error.message);
    }
    finally {sendingInput=false;updateSendButton();}
  });
  // The only approval path is an explicit click on the visible reviewed revision.
  let displayed = null;
  bind('approvePlan','click', async () => {
    const p = session(), shown = displayed;
    if (!p || !p.canApprove || !shown || shown.id !== p.sessionId || shown.revision !== p.revision) throw new Error('计划版本已变化，请重新审阅');
    await store.approvePlan({sessionId:shown.id, revision:shown.revision});
  });
  bind('recoverPlanResult','click', () => store.recoverPlan(session()?.sessionId));
  bind('workflowWakeBtn','click', () => store.wakeWorkflow(workflow()?.id));
  bind('workflowResumeBtn','click', () => store.resumeWorkflow(workflow()?.id));
  const patrolEnabled=()=> (H.view.rawSnapshot?.workflows||[]).find(x=>x.id===workflow()?.id)?.patrol_enabled!==false;
  bind('workflowPatrolBtn','click',async()=>{if(workflow()?.id)await H.action('workflow_set_patrol',{workflow_id:workflow().id,enabled:!patrolEnabled()});});
  bind('workflowStopBtn','click', () => store.stopWorkflow(workflow()?.id));
  bind('switchManagerDeepseekBtn', 'click', async () => {
    const target = value('projectManagerSelect');
    await store.switchManager({
      workflowId: workflow()?.id || null,
      sessionId: session()?.sessionId || null,
      targetManager: target,
      inheritContext: true
    });
    H.notice(`已成功切换项目经理为 ${target}（已继承上下文）`, 'status');
  });
  const onNewDiscussion = async () => {
    if(startingPlan)return;
    const p=session(),newRound=!!p && p.mode!=='alignment';
    if(p?.pending)throw Error('请等待经理本轮回复后开始计划');
    const editor=p ? $('discussionReply') : $('workflowRequirement'),originalDraft=editor.value,projectId=H.client.getSelectedProjectId();
    const draft=originalDraft.trim();
    const body=draft || (newRound ? '请根据当前项目的已有上下文制定新一轮计划，等待我审阅批准后再启动新一轮执行。' : p ? '请根据我们刚才对齐的需求制定计划。' : '');
    if(!body){$('workflowRequirement').focus();H.notice('填写需求后点击开始计划，即可直接制定计划','status');return;}
    const selected=H.view.rawSnapshot?.projects?.find(x=>x.id===H.client.getSelectedProjectId());
    if(!selected)throw Error('请先创建项目');
    startingPlan=true;render(H.view);
    try {
      await store.sendPlanChat({body,sessionId:newRound ? null : p?.sessionId,options:(!newRound && p?.options) || H.projectDiscussionOptions(selected),confirmed:true,startPlanning:true});
      if(projectId===H.client.getSelectedProjectId()){
        if(editor.value===originalDraft){editor.value='';editor.dispatchEvent(new Event('input',{bubbles:true}));}
        fresh=false;
      }
    } finally {startingPlan=false;render(H.view);}
  };
  bind('newDiscussion','click', onNewDiscussion);
  if ($('newDiscussionInline')) bind('newDiscussionInline','click', onNewDiscussion);
  if ($('toggleDiscussionView')) bind('toggleDiscussionView','click', () => { fresh = false; render(H.view); });
  function stageLabel(v) {
    const raw=v.rawSnapshot||{},p=v.managerStream.planning;
    const discussion=(raw.planning||[]).find(x=>x.id===p?.sessionId);
    const w=(raw.workflows||[]).find(x=>x.id===discussion?.workflow_id)||(raw.workflows||[])[0]||v.managerStream.workflow;
    const design=(raw.designs||[]).find(x=>x.id===discussion?.design_id)||(raw.designs||[])[0];
    if(p?.mode==='alignment')return '需求对齐';
    if(p?.state==='error')return '讨论需处理';
    if(p?.state==='thinking'||p?.state==='draft')return '需求讨论';
    if(p?.state==='awaiting_approval'&&!discussion?.design_approved)return '计划待确认';
    const production=!!(w?.design_baseline||w?.delivery_stage==='implementation'||discussion?.design_approved);
    const stage=production?'正式制作':w?.design_review||p?.state==='designing'?'产品演示':'项目执行';
    if(production&&p?.state==='awaiting_approval')return '正式制作 · 待启动';
    if(!production&&design?.state==='review')return '演示待确认';
    if(w?.status==='completed')return stage+' · 已完成';
    if(['paused','stopped','blocked','needs_attention','waiting_quota','failed','cancelled'].includes(w?.status))return stage+' · '+({paused:'已暂停',stopped:'已停止',blocked:'待核查',needs_attention:'待核查',waiting_quota:'等待额度',failed:'需处理',cancelled:'已取消'}[w.status]);
    if(!production&&design?.state==='review')return '演示待确认';
    if(production||w?.status==='active'||p?.state==='designing')return stage;
    return p?'需求讨论':'开始新讨论';
  }
  H.chatStageLabel=stageLabel;
  H.updateReviewerOptions=(preferred=$('workflowReviewer').value)=>{
    const chosen=new Set([...$('workflowAgents').querySelectorAll('input:checked')].map(c=>c.value));
    const reviewers=H.view.agents.filter(a=>a.id!==H.view.managerStream.manager&&chosen.has(a.id));
    const placeholder=node('option','由经理另选独立成员');placeholder.value='';
    $('workflowReviewer').replaceChildren(placeholder,...reviewers.map(a=>{const o=node('option',a.name);o.value=a.id;return o;}));
    $('workflowReviewer').value=reviewers.some(a=>a.id===preferred)?preferred:(reviewers[0]?.id||'');
  };
  $('workflowAgents').addEventListener('change',()=>H.updateReviewerOptions());
  let rosterSignature='';
  function render(v) {
    const current=session();
    for(const id of ['newDiscussion','newDiscussionInline']){const b=$(id);if(b){b.textContent=(!current || current.mode==='alignment')?'开始计划':'新建讨论';b.disabled=startingPlan || !!current?.pending;b.classList.toggle('primary-btn',!current || current.mode==='alignment');b.classList.toggle('secondary-btn',!!current && current.mode!=='alignment');}}
    const roster=JSON.stringify([v.managerStream.manager,v.agents.map(a=>[a.id,a.name,a.model])]);
    if(roster!==rosterSignature){rosterSignature=roster;const chosen=new Set([...$('workflowAgents').querySelectorAll('input:checked')].map(c=>c.value));list('workflowAgents',v.agents.filter(a=>a.id!==v.managerStream.manager).map(a=>{const label=node('label',a.name+' · '+a.model,'setupConsent'),c=node('input');c.type='checkbox';c.value=a.id;c.checked=chosen.has(a.id);label.prepend(c);return label;}));H.updateReviewerOptions();}

    if (project !== H.client.getSelectedProjectId()) { project = H.client.getSelectedProjectId(); fresh = false; }
    const stream = v.managerStream, p = session(), w = stream.workflow;
    const known=v.rawSnapshot?.messages||[];
    if(armedInputs.has(inputKey()))armedInputs.set(inputKey(),armedInputs.get(inputKey()).filter(id=>!known.some(m=>m.id===id&&m.status!=='pending')));
    const running=new Set([...(v.rawSnapshot?.deepseek?.runs||[]),...(v.rawSnapshot?.integration_runs||[])].filter(r=>['running','interrupting'].includes(r.status)).map(r=>r.agent));
    const nextMiniSignature=JSON.stringify(v.agents.map(a=>[a.id,a.name,a.status,running.has(a.id),a.quotaExhausted,a.modelUnavailable]));
    if(nextMiniSignature!==miniSignature){miniSignature=nextMiniSignature;
      list('agentMiniStates',v.agents.map(a=>{const state=a.quotaExhausted||a.modelUnavailable?'offline':running.has(a.id)||a.status==='busy'?'busy':['idle','standby'].includes(a.status)?'idle':'offline';const row=node('div',null,'agent-mini-row '+state);const lamp=node('span','','agent-mini-lamp');lamp.setAttribute('aria-hidden','true');row.classList.toggle('quota-exhausted',!!a.quotaExhausted);row.classList.toggle('model-unavailable',!!a.modelUnavailable);row.title=(a.name||a.id)+(a.modelUnavailable?' · 模型不可用：'+a.modelUnavailable.detail:a.quotaExhausted?' · 额度耗尽':'');const name=node('span','','agent-mini-name');name.append(node('span',a.name||a.id,'agent-mini-name-text'));name.setAttribute('aria-label',a.name||a.id);row.append(lamp,name,node('span',state,'agent-mini-status '+state));return row;}));requestAnimationFrame(measureMiniNames);
    }
    text('currentManagerName',H.agentName(stream.manager,v));
    const switchBtn = $('switchManagerDeepseekBtn');
    if (switchBtn) {
      text('switchManagerDeepseekBtn', '切换项目经理');
      switchBtn.title = '选择已接入的 Agent 担任项目经理';
    }
    text('discussionStatus',stageLabel(v));
    $('discussionStatus')?.classList?.remove('is-loading');
    $('workflowForm').hidden = !!p;
    $('discussionReplyForm').hidden = !p;
    if ($('discussionReplyLabel')) {
      text('discussionReplyLabel', p?.mode === 'alignment' ? '与经理对齐需求，准备好后点击开始计划：' : p?.state === 'executing' ? '向当前项目经理发送工作沟通消息：' : '回复经理，或按当前流程批准计划：');
    }
    $('discussionReply').placeholder = p?.mode === 'alignment' ? '先聊聊你的想法、需求和限制...' : p?.state === 'executing' ? '向当前项目经理发送工作沟通消息...' : '输入补充要求、反馈，或输入“按计划执行”...';
    updateSendButton();
    if ($('toggleDiscussionView')) {
      $('toggleDiscussionView').hidden = !fresh || !v.managerStream?.planning;
    }
    // Input stays available while the manager is busy; it enters the durable queue.
    $('planApprovalCard').hidden = !p?.isAwaitingApproval;
    $('approvePlan').hidden = !p?.canApprove;
    $('approvePlan').disabled = !!p?.pending;
    displayed = p?.canApprove ? {id:p.sessionId,revision:p.revision} : null;
    text('approvePlan',p?.options?.preview_mode==='skip'?'按计划执行':'先制作产品演示');
    $('skipDesign').hidden=!p?.canApprove || p?.options?.preview_mode==='skip';
    text('planRevisionBadge','计划 v' + (p?.revision ?? '—'));
    list('planTaskPreview',(p?.planDraft?.tasks || []).map(t => H.chatMessage(t.agent,t.instruction,'待审批',null)));
    const permissions = (v.rawSnapshot?.planning || []).find(s => s.id === p?.sessionId)?.permissions;
    text('planApprovalSummary', p ? '目录与执行授权：' + H.dump(p.options) + '\n权限：' + H.dump(permissions) + '\n批准当前版本 v' + p.revision + ' 后按所选流程启动（先演示或直接制作）。' : '');
    const timeline=[...(!fresh ? stream.history : []), ...stream.userDirectMessages].map(m=>({id:m.id,time:m.timestamp||0,render:()=>{const row=H.chatMessage(m.senderName,m.text,m.status||m.role,m.timestamp,m.result);row.dataset.messageId=m.id;return row;}}));
    for(const item of H.artifactItems?.(v.rawSnapshot||{})||[])timeline.push({id:'artifact:'+item.id,time:item.created||0,render:()=>H.artifactMessage(item)});
    for(const item of v.rawSnapshot?.memory_updates||[])timeline.push({id:'memory-update:'+item.revision,time:item.created,render:()=>H.memoryUpdateMessage(item)});
    const discussion=(v.rawSnapshot?.planning||[]).find(x=>x.id===p?.sessionId);
    if(discussion?.error)timeline.push({id:'plan-error:'+discussion.id+':'+discussion.revision+':'+discussion.error,time:discussion.history?.at(-1)?.created||discussion.created||0,render:()=>{const node=H.chatMessage('平台','计划处理失败：'+discussion.error+'。请检查接入状态后重新发送消息；尚未开始执行。','需要处理',null);node.setAttribute('role','alert');return node;}});
    if(discussion?.notice)timeline.push({id:'plan-notice:'+discussion.id+':'+discussion.revision+':'+discussion.notice,time:discussion.history?.at(-1)?.created||discussion.created||0,render:()=>H.chatMessage('平台',discussion.notice,'计划状态',null)});
    const design=(v.rawSnapshot?.designs||[]).find(x=>x.id===discussion?.design_id)||(v.rawSnapshot?.designs||[])[0];
    if(design)timeline.push({id:'design:'+design.id,time:design.approved_at||design.versions?.at(-1)?.created||design.created||0,render:()=>{
      const caption=design.publish_error?'设计 v'+design.version+' 发布未完成：'+design.publish_error:design.state==='building'?'设计 v'+design.version+' 制作中，仅制作演示，尚未开始真实产品。':design.state==='review'?'设计 v'+design.version+' 已就绪，请逐页审阅、框选修改或确认后正式制作。':'设计 v'+design.version+' 已确认，正式制作须遵循此基线。';
      const row=H.chatMessage('产品演示',caption,'设计',design.approved_at||design.versions?.at(-1)?.created||design.created);row.dataset.design=design.id;row.classList.add('design-delivery');
      const open=H.button('审阅产品演示',()=>H.$('openDesignReview').click());open.className='design-review-launch';open.setAttribute('aria-label','打开产品演示，逐页审阅与批注');open.disabled=!design.versions?.length;row.querySelector('.chat-message-body').append(open);return row;
    }});
    list('discussionHistory',timeline.sort((a,b)=>a.time-b.time||String(a.id).localeCompare(String(b.id))).map(item=>item.render()));
    $('recoverPlanResult').hidden = p?.mode==='alignment' || !(p?.state==='error'||(p?.state==='draft'&&discussion?.last_run&&discussion?.notice&&!discussion.pending&&!discussion.plan));
    $('workflowResumeBtn').hidden = !['paused','stopped'].includes(w?.status);
    $('workflowWakeBtn').hidden = !w || !['active','needs_attention','blocked'].includes(w.status);
    $('workflowPatrolBtn').hidden=!w;
    text('workflowPatrolBtn',patrolEnabled()?'允许项目静置':'恢复定期巡检');
    $('workflowPatrolBtn').setAttribute('aria-pressed',String(!patrolEnabled()));
    $('workflowStopBtn').hidden = !w || !['active','needs_attention','paused'].includes(w.status);
    // Reports already appear in the chronological chat and overall progress.
    list('workflowList',[]);
  }
  H.render(render);
})();
