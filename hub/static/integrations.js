"use strict";
(() => {
 const H=window.HubDesktop,{$,node,text,bind}=H;
 const supported=new Set(['custom-harness','codex','antigravity','deepseek-harness','opencode','ori','workbuddy','openrouter-api','gemini-api','deepseek-api']);
 let catalogConnection=null,modelRequest=0;
 let snapshot=null,mode='list',catalog=[],returnFocus=null,request=0,busy=false,lastList='',lastDefault='';
 const val=id=>$(id).value;
 const connection=()=>snapshot?.connections.find(c=>c.id===val('agentConnection'));
 const draftKey='hub.agentManagerWizard';
 function persist(){try{sessionStorage.setItem(draftKey,JSON.stringify({open:!$('integrationsDialog').hidden,mode,connection:val('agentConnection'),model:val('agentModel'),name:val('agentName')}));}catch{}}
 function show(step){mode=step;for(const [id,key] of [['agentManagerListStep','list'],['agentWizardProviderStep','provider'],['agentWizardModelStep','model']])$(id).hidden=key!==step;text('integrationsTitle',step==='list'?'管理 Agent':'添加 Agent');persist();}
 function options(id,items,selected){$(id).replaceChildren(...items.map(([value,label])=>{const o=node('option',label);o.value=value;return o;}));if(selected)$(id).value=selected;if(!$(id).value)$(id).selectedIndex=0;}
 function providers(selected){options('agentConnection',(snapshot?.connections||[]).filter(c=>supported.has(c.kind)).map(c=>[c.id,c.name]),selected);hint();}
 function hint(){const c=connection();const guides={'custom-harness':'用户脚本接入。脚本以当前 Windows 用户运行，需完全访问；支持能力以配置声明为准。','deepseek-harness':'使用本机 DeepSeek Harness；模型与档位从官方目录读取。',ori:'使用 Ori 的 OpenRouter 登录。未登录时先运行 ori login。',opencode:'使用 OpenCode 已连接的模型与账号。',codex:'使用本机 Codex 官方登录和模型目录。',antigravity:'使用 Antigravity 的 Google 登录和模型目录。',workbuddy:'使用官方独立 CodeBuddy CLI；先在终端运行 codebuddy 并完成 /login。'};text('wizardConnectionHint',c?(guides[c.kind]||'使用此接入已有的密钥环境变量。')+(c.installed?'':' 工具尚未安装。'):'请先连接本地服务。');if(c?.kind==='custom-harness'){const caps=c.adapter?.capabilities||{};text('wizardConnectionHint',(c.adapter?.protocol==='hub-module-v1'?'Harness 模块 · ':'自定义脚本 · ')+(caps.tools?'支持平台工具':'基础问答，不支持派工与平台工具')+' · '+(caps.resume?'原生会话恢复':'平台保留问答上下文')+' · '+(caps.streaming?'流式输出':'最终回复')+'。脚本以当前用户运行；启用前请检查脚本。');}text('wizardProviderError','');}
 function defaultName(){const m=catalog.find(m=>m.id===val('agentModel'));if(!m)return '';const base=(m.name||m.id.split('/').at(-1)).slice(0,95);const used=new Set((snapshot?.agents||[]).map(a=>a.name));let i=1;while(used.has(base+' '+i))i++;return base+' '+i;}
 function modelChanged(){if(!val('agentName').trim()||val('agentName')===lastDefault){lastDefault=defaultName();$('agentName').value=lastDefault;}persist();}
 function models(selected){
  const c=connection(),extra=c?.kind==='workbuddy'&&$('showCandidateModels').checked?(c.candidate_models||[]):[];
  const known=new Map((c?.models||catalog).map(m=>[m.id,m]));for(const m of extra)if(!known.has(m.id))known.set(m.id,m);catalog=[...known.values()];
  const labels={official_acp_catalog:'CLI 目录',official_installed_catalog:'候选 · 未验证',user_confirmed_client_model:'用户确认',official_user_config:'用户配置 · 未验证',official_cli_help:'帮助目录 · 未验证'};
  options('agentModel',catalog.map(m=>[m.id,(m.name&&m.name!==m.id?m.name+' · ':'')+m.id+(c?.kind==='workbuddy'?' ['+(labels[m.source]||'未验证')+(m.stale?' · 已过期':'')+']':'')]),selected);modelChanged();
  $('candidateModelsRow').hidden=c?.kind!=='workbuddy'||!c.candidate_models?.length;
 }
 async function refreshModels(){const c=connection();if(!c)return;const id=c.id,ticket=++request,selected=val('agentModel');$('refreshModelCatalog').disabled=true;try{const result=await H.action('integration_probe',{connection_id:id});if(ticket!==request||connection()?.id!==id)return;Object.assign(c,result);catalog=c.models||[];models(selected);probeChosenModel();H.notice(c.probe_detail||'目录已刷新；未发送推理请求。','status');}catch(error){H.notice(error.message);}finally{$('refreshModelCatalog').disabled=false;}}
 bind('refreshModelCatalog','click',refreshModels);
 bind('openHarnessAdapters','click',async()=>{const result=await H.action('integration_adapters',{open_folder:true});H.notice('适配器目录：'+result.directory+(result.errors.length?'；配置错误：'+result.errors.map(e=>e.error).join('；'):''),result.errors.length?'error':'status');await H.store.refresh(true);});
 bind('refreshHarnessAdapters','click',async()=>{const result=await H.action('integration_adapters',{});await H.store.refresh(true);H.notice(result.errors.length?result.errors.map(e=>e.file+'：'+e.error).join('；'):'自定义接入目录已刷新；未运行脚本。',result.errors.length?'error':'status');});
 $('showCandidateModels').addEventListener('change',()=>{models(val('agentModel'));probeChosenModel();});
 function enableHint(){const c=connection(),needs=!!c&&!c.enabled;$('wizardEnableRow').hidden=!needs;$('wizardEnableConnection').checked=false;text('wizardEnableText','允许此接入在已批准项目中执行（'+(c?.permission==='workspace'?'工作目录权限':'完全访问权限')+'），使用现有登录与账号额度。');text('wizardModelHint',!c?.installed?'尚未安装，可先添加离线 Agent；安装登录后再启用接入。':needs?'未勾选启用时只添加身份，不会启动模型。':'此接入已启用。添加本身不会调用模型，任务仍按项目授权执行。');}
 async function probeChosenModel(){
  const c=connection(),model=val('agentModel'),item=catalog.find(m=>m.id===model),ticket=++modelRequest;
  if(!c||!['opencode','ori'].includes(c.kind)||!item||item.efforts?.length>1||item.source==='official_acp_config'){$('saveIntegrationAgent').disabled=busy;text('wizardModelHint',c?.kind==='workbuddy'?(item?.source==='official_installed_catalog'?'仅安装包候选，尚未确认此账号或 CLI 可以调用；添加不会验证实际推理。':item?.source==='user_confirmed_client_model'?'此模型曾由你确认在旧客户端可用；CodeBuddy 中的实际调用与免费资格尚未验证。':c.probe_detail||'模型目录不代表账号权限或免费资格；添加不会调用模型。'):item?.efforts?.length>1?'添加后可在卡片上调整档位。':'添加本身不会调用模型。');return;}
  $('saveIntegrationAgent').disabled=true;text('wizardModelHint','正在读取这个模型的可用档位，不发送推理请求…');
  try{const result=await H.action('integration_model_options',{connection_id:c.id,model});
   if(ticket!==modelRequest||mode!=='model'||$('integrationsDialog').hidden||connection()?.id!==c.id||val('agentModel')!==model)return;
   if(result.id===model&&result.efforts){catalog=catalog.map(m=>m.id===model?result:m);text('wizardModelHint','可用档位：'+result.efforts.join(' / ')+'。添加后在卡片上调整。');}
  }catch(error){if(ticket===modelRequest&&mode==='model')text('wizardModelHint','暂时无法读取档位，添加后先使用默认档位。'+error.message);}
  finally{if(ticket===modelRequest)$('saveIntegrationAgent').disabled=busy;}
 }
 function open(){returnFocus=document.activeElement;providers(val('agentConnection'));$('integrationsDialog').hidden=false;show('list');$('closeIntegrations').focus();}
 bind('openIntegrations','click',open);
 const testDialog=node('dialog','','new-project-dialog connection-test-dialog');testDialog.id='connectionTestDialog';
 const testTitle=node('h2','测试全部 Agent？'),testNote=node('p'),testError=node('p','','test-error');testError.id='connectionTestError';
 const testCancel=node('button','取消','secondary-btn'),testConfirm=node('button','开始真实测试','primary-btn'),testClose=node('button','×','dialog-close');
 testCancel.type=testConfirm.type=testClose.type='button';testClose.title='关闭';testClose.setAttribute('aria-label','关闭');testCancel.onclick=testClose.onclick=()=>testDialog.close();
 const testHeader=node('header','','project-dialog-header');testHeader.append(testTitle,testClose);const testActions=node('footer','','agent-wizard-actions');testActions.append(testCancel,testConfirm);testDialog.append(testHeader,testNote,testError,testActions);document.body.append(testDialog);
 let testingAgent=null;
 H.openAgentTest=agent=>{testingAgent=agent?.id||null;const count=testingAgent?1:snapshot?.agents.filter(a=>a.enabled).length||0;testTitle.textContent=testingAgent?'测试 '+agent.name+'？':'测试全部 Agent？';testNote.textContent='将测试 '+count+' 个 Agent，最多 8 个同时进行，超过时自动分批；也可同时单独测试不同 Agent。同一 Agent 不重复提交。每个最多提交一轮真实请求，使用当前接入和档位，会消耗订阅额度或 API 余额。忙碌、未启用或停止锁定的 Agent 会跳过。使用独立会话，不读取项目历史、不派工，失败不自动重试。结果显示在对应 Agent 卡片内。';testError.textContent='';testDialog.showModal();testCancel.focus();};
 bind('verifyIntegrationsHeader','click',()=>H.openAgentTest(null));
 testConfirm.onclick=async()=>{testConfirm.disabled=true;try{const result=await H.action('integration_test_all',{confirmed:true,...(testingAgent?{agent_id:testingAgent}:{})});if(result.started===false)throw Error(result.detail||'所选 Agent 已在测试中，不重复提交。');testDialog.close();await H.store.refresh(true);}catch(error){testError.textContent=error.message;}finally{testConfirm.disabled=false;}};
 bind('applyProjectManager','click',async()=>{const id=val('projectManagerSelect');await H.action('integration_set_manager',{project_id:H.view.rawSnapshot.selected_project,target_manager:id});H.notice('项目经理已更新，任务与历史记录保留。','status');});
 bind('closeIntegrations','click',()=>{request++;$('integrationsDialog').hidden=true;persist();returnFocus?.focus();});
 bind('newIntegrationAgent','click',()=>{request++;providers(val('agentConnection'));catalog=[];catalogConnection=null;$('showCandidateModels').checked=false;$('agentName').value='';lastDefault='';show('provider');$('agentConnection').focus();let adapterWarning='';void H.action('integration_adapters',{}).then(result=>{adapterWarning=(result.errors||[]).map(e=>e.file+'：'+e.error).join('；');return H.store.refresh(true);}).then(()=>{if(mode==='provider'){providers(val('agentConnection'));if(adapterWarning)text('wizardProviderError',adapterWarning);}}).catch(error=>text('wizardProviderError',error.message));});
 $('agentConnection').addEventListener('change',()=>{request++;catalog=[];hint();persist();});
 $('agentModel').addEventListener('change',()=>{modelChanged();probeChosenModel();});$('agentName').addEventListener('input',persist);
 bind('wizardCancel','click',()=>{request++;show('list');});bind('wizardBack','click',()=>{request++;show('provider');});
 bind('wizardNext','click',async()=>{
  const c=connection();if(!c)throw Error('请选择接入选项');const ticket=++request,button=$('wizardNext');button.disabled=true;text('wizardProviderError','正在读取模型列表…');
  try{const result=c.kind!=='workbuddy'&&c.models?.length?c:await H.action('integration_probe',{connection_id:c.id});if(ticket!==request||$('integrationsDialog').hidden||val('agentConnection')!==c.id)return;
   const keep=catalogConnection===c.id,selected=val('agentModel');Object.assign(c,result);catalog=result.models||[];catalogConnection=c.id;if(!catalog.length&&!c.candidate_models?.length)throw Error('工具尚未提供模型列表，请先在工具中完成登录或配置，再重试。');if(!keep){lastDefault='';$('agentName').value='';}models(keep?selected:null);enableHint();text('wizardProviderError','');show('model');$('agentModel').focus();probeChosenModel();
  }catch(error){if(ticket===request){text('wizardProviderError',error.message);H.notice(error.message);}}
  finally{button.disabled=false;}
 });
 bind('saveIntegrationAgent','click',async()=>{
  if(busy)return;const c=connection();if(!c||!catalog.some(m=>m.id===val('agentModel')))throw Error('请选择列表中的模型');busy=true;$('saveIntegrationAgent').disabled=true;
  try{const saved=await H.action('integration_wizard_add',{connection_id:c.id,model:val('agentModel'),name:val('agentName').trim()===lastDefault?'':val('agentName').trim(),confirmed:$('wizardEnableConnection').checked,candidate_confirmed:$('showCandidateModels').checked});show('list');H.notice('已添加 '+saved.name+'，可在卡片上调整档位。','status');}
  finally{busy=false;$('saveIntegrationAgent').disabled=false;}
 });
 const details=$('agentDetailsDialog');let detailBody=null,detailParent=null;
 H.openAgentDetails=(agent,body)=>{if(details.open)return;detailBody=body;detailParent=body.parentElement;body.hidden=false;$('agentDetailsContent').replaceChildren(body);text('agentDetailsTitle',agent.name+' · '+agent.role);details.showModal();};
 bind('closeAgentDetails','click',()=>details.close());
 details.addEventListener('close',()=>{if(detailBody){detailBody.hidden=true;if(detailParent?.isConnected)detailParent.append(detailBody);else detailBody.remove();detailBody=null;detailParent=null;}});
 document.addEventListener('keydown',e=>{if($('integrationsDialog').hidden||!$('integrationsDialog').contains(e.target))return;if(e.key==='Escape'){e.preventDefault();$('closeIntegrations').click();}if(e.key==='Tab'){const items=[...$('integrationsDialog').querySelectorAll('input,select,button')].filter(x=>!x.disabled&&x.getClientRects().length);if(e.shiftKey&&$('integrationsDialog').ownerDocument.activeElement===items[0]){e.preventDefault();items.at(-1)?.focus();}else if(!e.shiftKey&&$('integrationsDialog').ownerDocument.activeElement===items.at(-1)){e.preventDefault();items[0]?.focus();}}});
 window.addEventListener('beforeunload',persist);
 H.testLabel=r=>({pending:'等待测试',testing:'正在测试',passed:'接入测试通过',rate_limited:'暂时限流',quota_exhausted:'额度不足',auth_required:'需要登录/授权',adapter_error:'接入程序错误',configuration_error:'模型/档位不匹配',model_unavailable:'模型不可用/已下线',failed:'接入测试失败',skipped:'已跳过',timeout:'测试超时',interrupted:'测试中断'}[r.status]||r.status)+(r.elapsed_ms!=null?' · '+(r.elapsed_ms/1000).toFixed(1)+'s':'');
 let restored=false;
 H.render(v=>{
  const next=v.rawSnapshot?.integrations;if(!next)return;snapshot=next;
  const active=next.agents.filter(a=>a.enabled);text('integrationAgentCount',active.length+' 个 Agent');
  const testing=Object.values(next.test_results||{}).some(r=>['pending','testing'].includes(r.status));$('verifyIntegrationsHeader').disabled=false;$('verifyIntegrationsHeader').textContent=testing?'全部测试 · 进行中':'全部测试';
  const signature=JSON.stringify({manager:v.managerStream.manager,managerProjects:next.manager_projects,tests:next.test_results,agents:active,status:v.agents.map(a=>[a.id,a.status])});
  if(signature!==lastList){lastList=signature;options('projectManagerSelect',active.map(a=>[a.id,a.name]),v.managerStream.manager);$('integrationAgentList').replaceChildren(...active.map(a=>{
   const c=next.connections.find(c=>c.id===a.connection_id),row=node('article','','agent-manager-row'),info=node('div');info.append(node('strong',a.name),node('small',(c?.name||'')+' · '+a.model));const test=next.test_results?.[a.id];if(test){const result=node('small',H.testLabel(test),'agent-test-status test-'+test.status);result.title=test.detail;info.append(result);}const remove=node('button','删除','secondary-btn');remove.type='button';remove.dataset.removeAgent=a.id;
   const running=v.agents.find(x=>x.id===a.id)?.activeRuns?.length;const uses=next.manager_projects?.[a.id]||[];const isManager=a.id===v.managerStream.manager;remove.disabled=isManager||!!running||!!uses.length;remove.title=uses.length?'请先更换这些项目的经理：'+uses.map(p=>p.name+'（'+p.status+'）').join('、'):isManager?'请先选择其他 Agent 担任当前项目经理':running?'执行结束后可删除':'从面板移除，保留历史';
   remove.addEventListener('click',async()=>{remove.disabled=true;try{await H.action('integration_agent_archive',{agent_id:a.id});H.notice('已删除 '+a.name+'，历史记录保留。','status');}catch(error){remove.disabled=false;H.notice(error.message);}});const testButton=node('button','测试','secondary-btn');testButton.type='button';testButton.dataset.testAgent=a.id;testButton.addEventListener('click',()=>H.openAgentTest(a));row.append(info,testButton,remove);return row;
  }));}
  if(!restored){restored=true;try{const saved=JSON.parse(sessionStorage.getItem(draftKey)||'null');if(saved?.open){providers(saved.connection);$('integrationsDialog').hidden=false;catalog=connection()?.models||[];catalogConnection=connection()?.id;$('agentName').value=saved.name||'';lastDefault='';if(saved.mode==='model'&&catalog.some(m=>m.id===saved.model)){models(saved.model);enableHint();show('model');}else show(saved.mode==='list'?'list':'provider');}}catch{}}
 });
})();
