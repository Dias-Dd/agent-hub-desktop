"use strict";
(()=>{
 const H=window.HubDesktop;if(!H)return;
 const card=H.$('managerLiveReply'),reader=H.$('managerReadingArea');
 let owner='',controller=null,retryAt=0,lastRevision=-1,lastStatus='',quotaSignature='';
 const active=new Set(['queued','running','interrupting']);
 function put(id,value){const el=H.$(id);value=String(value||'');const old=el.textContent;if(old===value)return;delete el._markdownSource;if(value.startsWith(old)&&el.childNodes.length===1&&el.firstChild.nodeType===3)el.firstChild.appendData(value.slice(old.length));else el.textContent=value;}
 function quoted(source,start){let out='';for(let i=start;i<source.length;i++){const c=source[i];if(c==='"')return out;if(c.charCodeAt(0)!==92){out+=c;continue;}const next=source[++i];if(next===undefined)break;const codes={n:10,r:13,t:9,b:8,f:12};if(next==='u'){const code=source.slice(i+1,i+5);if(!/^[a-f0-9]{4}$/i.test(code))break;out+=String.fromCharCode(parseInt(code,16));i+=4;}else out+=next in codes?String.fromCharCode(codes[next]):next;}return out;}
 function visible(raw){let source=String(raw||'').trimStart();if(source.startsWith('```')){const end=source.indexOf(String.fromCharCode(10));if(end<0)return '';source=source.slice(end+1).trimStart();}if(!source.startsWith('{'))return raw;const display=window.HubChatFormat?.readableChat(raw);if(display!==undefined&&display!==raw)return display;let depth=0;for(let i=0;i<source.length;i++){const c=source[i];if(c==='{'||c==='['){depth++;continue;}if(c==='}'||c===']'){depth--;continue;}if(c!=='"')continue;const start=i;for(i++;i<source.length;i++){if(source.charCodeAt(i)===92){i++;continue;}if(source[i]==='"')break;}if(i>=source.length)return '';if(depth!==1)continue;let key;try{key=JSON.parse(source.slice(start,i+1));}catch{continue;}let j=i+1;while(j<source.length&&source[j].trim()==='')j++;if(source[j++]!==':')continue;while(j<source.length&&source[j].trim()==='')j++;if(['report','summary'].includes(key)&&source[j]==='"')return quoted(source,j+1);}return '';}
 let scheduled=null,queuedDraft=null;
 function enqueue(data,key){queuedDraft={data,key};if(scheduled!==null)return;scheduled=setTimeout(()=>{scheduled=null;const next=queuedDraft;queuedDraft=null;if(next)draw(next.data,next.key);},100);}
 function draw(data,key){if(key!==owner||data.revision<lastRevision||(data.revision===lastRevision&&data.status===lastStatus))return;const selection=window.getSelection(),reading=selection&&!selection.isCollapsed&&reader.contains(selection.anchorNode);const bottom=!reading&&reader.scrollHeight-reader.scrollTop-reader.clientHeight<36;
  lastRevision=data.revision;lastStatus=data.status;const text=visible(data.text||'');if(window.HubChatFormat)window.HubChatFormat.renderMarkdown(H.$('managerLiveText'),text);else put('managerLiveText',text);put('managerLiveRawText',data.text||'');H.$('managerLivePlaceholder').hidden=!!text;
  put('managerLiveStatus',data.phase||({queued:'排队中',running:'正在等待提供商输出',waiting_quota:'等待额度恢复',interrupting:'正在确认中断'}[data.status]||'本轮已结束'));
  put('managerLiveSummaryText',data.summary||'');H.$('managerLiveSummary').hidden=!data.summary;
  if(active.has(data.status)){const phase=(data.text&&data.phase?.startsWith('正在使用工具'))?'正在生成回复':data.phase; if(phase)operationPhases.set(data.run_id,phase);const operation=H.$('operation_'+data.run_id);if(operation){const runs=[...['deepseek','codex','antigravity'].flatMap(p=>H.view?.rawSnapshot?.[p]?.runs||[]),...(H.view?.rawSnapshot?.integration_runs||[])];const run=runs.find(r=>r.id===data.run_id);operation.textContent=H.agentName(data.agent||run?.agent||H.view?.managerStream?.manager)+' · '+(run?operationLabel(H.view,run):phase||'正在生成回复');}}
  if(bottom)reader.scrollTop=reader.scrollHeight;
 }
 async function connect(run,project,key){const abort=new AbortController();controller=abort;
  try{while(owner===key&&!abort.signal.aborted){const response=await fetch(H.client.baseUrl+'/api/reply-stream?run='+encodeURIComponent(run),{headers:{Authorization:'Bearer '+H.client.getUserToken(),'X-Hub-Project':project},signal:abort.signal,cache:'no-store'});if(!response.ok||!response.body)throw Error('stream unavailable');
   const stream=response.body.getReader(),decoder=new TextDecoder();let buffer='';const nl=String.fromCharCode(10);
   while(true){const part=await stream.read();if(part.done)break;buffer+=decoder.decode(part.value,{stream:true});let boundary;while((boundary=buffer.indexOf(nl+nl))>=0){const event=buffer.slice(0,boundary);buffer=buffer.slice(boundary+2);for(const line of event.split(nl))if(line.startsWith('data: ')){const data=JSON.parse(line.slice(6));if(data.run_id===run&&H.client.getSelectedProjectId()===project)enqueue(data,key);}}}
   if(owner!==key||abort.signal.aborted)break;await H.store.refresh(true);if(!active.has(lastStatus))break;await new Promise(r=>setTimeout(r,500));
  }}catch(error){if(error.name!=='AbortError')retryAt=Date.now()+5000;}
  finally{if(owner===key&&controller===abort)controller=null;}
 }
 const operationPhases=new Map();
 function operationLabel(v,run){
  if(run.status==='queued')return '排队等待';if(run.status==='waiting_quota')return '等待额度恢复';if(run.status==='interrupting')return '正在确认中断';
  const events=['deepseek','codex','antigravity'].flatMap(p=>v.rawSnapshot?.[p]?.events||[]).filter(e=>e.run_id===run.id).sort((a,b)=>(a.seq||0)-(b.seq||0));
  const calls=new Map();
  for(const event of events){let data;try{data=typeof event.data==='string'?JSON.parse(event.data):event.data||{};}catch{continue;}
   if(event.kind?.endsWith('.tool')&&data.toolCallId){const old=calls.get(data.toolCallId)||{};calls.set(data.toolCallId,{...old,...data});}
   const item=data.item;if(['item/started','item/completed'].includes(event.kind)&&item&&['commandExecution','mcpToolCall','webSearch','fileChange'].includes(item.type))calls.set(item.id,{title:({commandExecution:'运行命令',mcpToolCall:'调用工具',webSearch:'检索资料',fileChange:'修改文件'})[item.type],status:event.kind==='item/started'?'in_progress':'completed'});
  }
  const tool=[...calls.values()].reverse().find(x=>['in_progress','pending'].includes(x.status));
  if(tool)return '正在使用工具：'+String(tool.title||tool.kind||'项目工具').slice(0,100);
  return calls.size?'正在生成回复':operationPhases.get(run.id)||'正在执行任务';
 }
 function renderOperations(v,runs){
  const live=runs.filter(r=>['queued','running','interrupting','waiting_quota'].includes(r.status));
  const ids=new Set(live.map(r=>r.id));for(const id of operationPhases.keys())if(!ids.has(id))operationPhases.delete(id);
  H.$('managerOperations').hidden=!live.length;
  H.list('managerOperationList',live.map(run=>{const row=H.node('div','','manager-operation');row.dataset.runId=run.id;const motion=H.node('span','','operation-motion');motion.setAttribute('aria-hidden','true');for(let i=0;i<3;i++)motion.append(H.node('i'));
   row.dataset.moving=['running','interrupting'].includes(run.status)?'true':'false';const label=H.node('span',H.agentName(run.agent,v)+' · '+operationLabel(v,run),'operation-text');label.id='operation_'+run.id;row.append(motion,label);return row;}));
  return live.length;
 }
 function updateQuotaResets(){for(const el of H.$('providerQuotaList').querySelectorAll('[data-quota-reset]')){const timestamp=Number(el.dataset.quotaReset);if(!timestamp){el.textContent='恢复时间未知';continue;}const minutes=Math.max(0,Math.ceil((timestamp*1000-Date.now())/60000)),days=Math.floor(minutes/1440),hours=Math.floor(minutes%1440/60),rest=minutes%60;el.textContent=minutes===0?'等待刷新额度':days?'约 '+days+' 天 '+hours+' 小时后恢复':hours?'约 '+hours+' 小时 '+rest+' 分钟后恢复':'约 '+rest+' 分钟后恢复';}}
 setInterval(updateQuotaResets,60000);
 function quota(v){const groups=v.rawSnapshot?.quota_overview||[];const signature=JSON.stringify(groups);if(signature===quotaSignature)return;quotaSignature=signature;
  H.list('providerQuotaList',groups.length?groups.map(g=>{const item=H.node('section','','provider-quota');item.append(H.node('strong',g.name));
   for(const w of g.windows){const row=H.node('div','','provider-quota-window');row.title=w.account||g.name;
    const label=H.node('div','','quota-window-label');const shortName=String(w.name||'').replace(/^(?:Gemini Models|Claude and GPT models|Gemini 4 Argon|codex)\s*\/\s*/i,'');label.append(H.node('span',shortName));const reset=H.node('small');reset.dataset.quotaReset=w.resets_at||'';label.append(reset);
    const valid=w.remaining!==null&&w.remaining!==''&&Number.isFinite(Number(w.remaining)),pct=valid?Math.max(0,Math.min(100,Number(w.remaining))):null;
    const value=H.node('div','','quota-window-value');value.append(H.node('span',pct===null?'未知':pct+'%'+(w.source==='manual'?' · 手动':'')));
    const ns='http://www.w3.org/2000/svg',ring=document.createElementNS(ns,'svg');ring.setAttribute('viewBox','0 0 24 24');ring.setAttribute('aria-hidden','true');ring.classList.add('quota-ring');
    for(const foreground of [false,true]){const circle=document.createElementNS(ns,'circle');for(const [key,val]of Object.entries({cx:12,cy:12,r:9,fill:'none','stroke-width':2.5}))circle.setAttribute(key,String(val));circle.setAttribute('class',foreground?'quota-ring-fill':'quota-ring-track');if(foreground){circle.setAttribute('stroke-dasharray',String((pct||0)*.56549)+' 56.549');if(pct!==null&&pct<=10)circle.classList.add('quota-ring-low');}ring.append(circle);}value.append(ring);row.append(label,value);item.append(row);} 
   for(const balance of g.balances||[]){const row=H.node('div','','provider-quota-window');row.append(H.node('span',balance.name),H.node('b',balance.amount+' '+balance.currency));if(balance.observed_at)row.append(H.node('small','读取于 '+new Date(balance.observed_at*1000).toLocaleString()));item.append(row);}
   if(g.unreadable.length)item.append(H.node('p',g.unreadable.join('、')+'：当前接口无法读取额度','muted'));return item;}):[H.node('p','暂无已接入的提供商','muted')]);
  updateQuotaResets();
  H.$('refreshProviderQuotas').disabled=!groups.some(g=>g.refreshable?.length);
 }
 H.bind('refreshProviderQuotas','click',async()=>{const ids=new Set((H.view.rawSnapshot?.quota_overview||[]).flatMap(g=>g.refreshable||[]));let failed=0;for(const id of ids){try{await H.action('integration_quota_refresh',{connection_id:id});}catch{failed++;}}H.notice(failed?'部分接入暂时无法读取，已保留上次数据。':'可读额度已刷新。',failed?'error':'status');});
 H.store.subscribe(v=>{quota(v);const s=v.rawSnapshot;if(!s||!H.client.hasToken()||(H.client.getSelectedProjectId()&&s.selected_project&&s.selected_project!==H.client.getSelectedProjectId())){if(controller)controller.abort();controller=null;owner='';card.hidden=true;return;}const manager=v.managerStream.manager,project=s.selected_project||H.client.getSelectedProjectId();const planning=(s.planning||[]).find(p=>p.id===v.managerStream.planning?.sessionId);
  const runs=[...['deepseek','codex','antigravity'].flatMap(p=>s[p]?.runs||[]),...(s.integration_runs||[])];const operationCount=renderOperations(v,runs);const run=runs.find(r=>r.id===planning?.pending)||runs.filter(r=>r.agent===manager&&active.has(r.status)).sort((a,b)=>(b.created||0)-(a.created||0))[0];
  if(!run||run.agent!==manager||(!active.has(run.status)&&!(planning?.pending===run.id&&run.status==='completed'))){if(controller)controller.abort();controller=null;owner='';card.hidden=!operationCount;H.$('managerLiveText').hidden=true;H.$('managerLivePlaceholder').hidden=true;H.$('managerLiveSummary').hidden=true;card.querySelector('.chat-message-meta').hidden=true;return;}
  H.$('managerLiveText').hidden=false;card.querySelector('.chat-message-meta').hidden=false;
  const key=project+':'+run.id;if(key!==owner){if(controller)controller.abort();controller=null;owner=key;retryAt=0;lastRevision=-1;lastStatus=run.status;put('managerLiveText','');put('managerLiveRawText','');put('managerLiveSummaryText','');}
  put('managerLiveSender','经理 '+H.agentName(manager,v));const stamp=run.started||run.created;if(stamp){const date=new Date(stamp*1000),time=H.$('managerLiveTime');time.dateTime=date.toISOString();time.textContent=date.toLocaleString('zh-CN',{hour12:false});}
  card.hidden=false;const checkpoint=(s.live_replies||[]).find(r=>r.run_id===run.id);if(checkpoint)draw(checkpoint,key);else if(lastRevision<0)draw({run_id:run.id,revision:0,status:run.status,text:'',phase:''},key);
  if(active.has(run.status)&&!controller&&Date.now()>=retryAt)connect(run.id,project,key);
 });
 window.addEventListener('beforeunload',()=>{controller?.abort();if(scheduled!==null)clearTimeout(scheduled);});
 H.$('managerLiveCopy').addEventListener?.('click',()=>H.copyChat(H.$('managerLiveText')._markdownSource??H.$('managerLiveText').textContent,H.$('managerLiveCopy')));
 H.$('managerLiveRawCopy').addEventListener?.('click',()=>H.copyChat(H.$('managerLiveRawText').textContent,H.$('managerLiveRawCopy')));
 H.visibleLiveReply=visible;
})();
