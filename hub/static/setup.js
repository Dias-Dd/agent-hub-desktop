"use strict";
(() => {
 const H=window.HubDesktop,$=H.$;
 const models=()=>document.getElementById('openIntegrations').click();
 H.openProviderGuide=models;
 for(const id of ['openProviderGuide','openDeepSeekIntegration'])H.bind(id,'click',models,false);
 if(!window.__HUB_NATIVE_MACOS__){
  H.bind('reopenSetup','click',models,false);
  for(const id of ['setupNext','setupClose'])H.bind(id,'click',()=>{$('setupWizard').hidden=true;},false);
  H.bind('setupBack','click',()=>{},false);
  if(location.hash==='#setup'){const show=()=>{if(!H.client.hasToken()){setTimeout(show,100);return;}models();history.replaceState(null,'',location.pathname);};show();}
  return;
 }
 let step=0,skipVm=false,pending=false,details={};
 const request=args=>H.client.postAction('desktop_onboarding',args);
 const error=message=>{$('setupError').textContent=message;};
 function vmSettings(){
  $('configModalToggle').checked=true;$('configModalToggle').dispatchEvent(new Event('change'));
  $('vmSettings').closest('#configModal').querySelector('[aria-controls="vmSettings"]')?.click();
  void H.connectSavedVm?.();
 }
 async function render(){
  error('');$('setupTitle').textContent='欢迎使用 Deskfellows';
  $('setupWizard').querySelector('.eyebrow').textContent='MACOS · 首次配置';
  $('setupSteps').replaceChildren(...['1 模型接入','2 Tart（可选）','3 完成'].map((text,index)=>{const item=H.node('li',text);item.className=index===step?'current':'';return item;}));
  $('setupBack').disabled=step===0;$('setupNext').textContent=step===2?'完成配置':'下一步';$('setupClose').textContent='稍后配置并进入工作台';
  const body=$('setupBody');body.replaceChildren();
  if(step===0){
   body.append(H.node('p','配置已有 Harness 或 API 账号。应用不附带模型额度，接入测试可能计费；本引导不会自动调用模型。'));
   body.append(H.button('添加或管理 Agent',models));
   body.append(H.node('p','也可先进入工作台，稍后在 Agent 面板继续配置。','settings-help'));
   body.append(H.node('p','当前应用数据目录：'),H.node('code',details.data_directory||''));
  }else if(step===1){
   body.append(H.node('p','Tart 是可选的独立执行环境，不影响普通项目使用。'));
   body.append(H.node('p','在虚拟机设置中检测或安装 Tart、下载镜像、保存连接，并开启自动连接。不会自动更改主机安全策略。'));
   body.append(H.button('自动安装或手动指定 Tart 镜像',()=>{vmSettings();H.openTartInstaller();}));
   body.append(H.button('安装或检查 Peekaboo 控件驱动',()=>{vmSettings();H.openTartAccessibility();}));
   body.append(H.node('p','控件驱动可自动安装到所选 macOS 虚拟机；辅助功能和屏幕录制需在访客中手动授权。','settings-help'));
   const value=await H.client.postAction('vm_control',{action:'status'});
   body.append(H.node('p',value.connected?'Tart 命令连接已验证。':'当前未连接 Tart 虚拟机。','settings-help'));
   const label=H.node('label','','settings-toggle-row'),input=H.node('input');input.type='checkbox';input.id='setupSkipVm';input.checked=skipVm;
   input.addEventListener('change',()=>{skipVm=input.checked;});label.append(input,H.node('span','暂时跳过虚拟机'));body.append(label);
   body.append(H.button('重新检查连接',()=>render()));
  }else{
   body.append(H.node('p','基础配置已准备好。模型调用仍需你明确授权，虚拟机能力以实际验证结果为准。'));
   body.append(H.node('p',skipVm?'已选择跳过虚拟机，可随时在设置中配置。':'已验证 Tart 连接。'));
   body.append(H.node('p','关闭主窗口会保留后台运行；可从菜单栏状态图标恢复窗口、查看项目和 Agent 状态。显式退出会停止后台任务。'));
  }
 }
 async function complete(skip){
  if(pending)return;pending=true;
  try{await request({operation:'complete',skip_vm:skip});$('setupWizard').hidden=true;}
  catch(e){error(e.message);}finally{pending=false;}
 }
 H.openFirstRunGuide=async()=>{
  try{H.ready();details=await request({operation:'status'});step=0;skipVm=false;await render();$('setupWizard').hidden=false;}
  catch(e){H.notice(e.message,'error');}
 };
 H.bind('reopenSetup','click',()=>H.openFirstRunGuide(),false);
 H.bind('setupClose','click',()=>complete(true),false);
 H.bind('setupBack','click',()=>{if(step>0){step--;void render();}},false);
 H.bind('setupNext','click',async()=>{
  if(pending)return;
  try{
   if(step===2){await complete(skipVm);return;}
   if(step===1&&!skipVm){const value=await H.client.postAction('vm_control',{action:'status'});if(!value.connected)throw Error('请先验证 Tart 连接，或勾选暂时跳过虚拟机。');}
   step++;await render();
  }catch(e){error(e.message);}
 },false);
 H.firstRunChecked=false;
 const bootstrap=async()=>{
  if(!H.client.hasToken()){setTimeout(bootstrap,100);return;}
  try{
   details=await request({operation:'status'});
   if(details.needed||location.hash==='#setup')await H.openFirstRunGuide();
   if(location.hash==='#setup')history.replaceState(null,'',location.pathname);
  }catch(e){H.notice('首次配置状态读取失败：'+e.message,'error');}
  finally{H.firstRunChecked=true;}
 };
 void bootstrap();
})();
