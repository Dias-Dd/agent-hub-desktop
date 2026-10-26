"use strict";
(() => {
  const H=window.HubDesktop, $=H.$;
  let busy=false, polling=false,lastState={},preferenceEdited=false;const selectedPower=new Map();
  $('vmUnattended').addEventListener('change',()=>{preferenceEdited=true;});
  $('vmSelect').addEventListener('change',()=>{preferenceEdited=false;const saved=lastState.saved_connections?.find(s=>s.vm===$('vmSelect').value);$('vmUnattended').checked=saved?.unattended!==false;});
  const status=message=>{$('vmConnectionStatus').textContent=message;for(const id of ['tartDirectoryDialog','tartInstallDialog','tartAccessibilityDialog']){const dialog=$(id);if(dialog.open)dialog.querySelector('[role=status]').textContent=message;}};
  const call=args=>{H.ready();return H.client.postAction('vm_control',args);};
  async function wait(request) {
    if(request.state==='completed')return request;
    const deadline=Date.now()+3600000;
    while(Date.now()<deadline) {
      const result=await call({action:'result',request_id:request.request_id});
      if(result.state==='completed')return result;
      if(result.progress)status(result.progress);
      if(!['queued','running'].includes(result.state))throw Error(result.error||'虚拟机操作未完成');
      await new Promise(resolve=>setTimeout(resolve,700));
    }
    throw Error('连接仍在处理，请稍后查看状态；不会自动重复提交凭据。');
  }
  async function operate(fn) {
    if(busy)return;busy=true;
    const buttons=[...$('vmSettings').querySelectorAll('button'),...$('tartDirectoryDialog').querySelectorAll('button'),...$('tartInstallDialog').querySelectorAll('button'),...$('tartAccessibilityDialog').querySelectorAll('button')].filter(button=>!button.hasAttribute('data-close-tart')),disabled=buttons.map(b=>b.disabled);buttons.forEach(b=>b.disabled=true);
    try{H.ready();await fn();}catch(error){status(error.message);$('vmAgentStatus').textContent=error.message;}
    finally{busy=false;buttons.forEach((b,i)=>b.disabled=disabled[i]);void refreshPower().catch(()=>{});}
  }
  async function refreshInventory(){
    status(lastState.backend==='tart'?'正在读取 Tart 虚拟机…':'正在读取，如 Windows 请求管理员授权，请确认…');
    const result=await wait(await call({action:'list'}));const selected=$('vmSelect').value;
    $('vmSelect').replaceChildren();
    for(const vm of result.vms||[]) {
      const option=document.createElement('option');option.value=vm.name;
      option.textContent=vm.name+' · '+vm.state+(result.backend==='tart'?' · Tart':' · 第 '+vm.generation+' 代');$('vmSelect').append(option);
    }
    if([...$('vmSelect').options].some(o=>o.value===selected))$('vmSelect').value=selected;
    status(result.vms?.length?(result.backend==='tart'?'请选择虚拟机，使用 Tart Guest Agent 连接，无需账号密码。':'请选择虚拟机，填写该系统的账号密码后连接。'):(result.backend==='tart'?'此数据目录内尚无 Tart 虚拟机。':'没有发现 Hyper-V 虚拟机。'));
  }
  $('vmRefresh').addEventListener('click',()=>operate(refreshInventory));
  $('vmConnectForm').addEventListener('submit',event=>{
    event.preventDefault();void operate(async()=>{
      status('正在连接并验证命令执行、双向文件传输…');
      const args={action:'connect',vm_name:$('vmSelect').value,username:$('vmUsername').value,password:$('vmPassword').value,remember:$('vmRemember').checked,unattended:$('vmUnattended').checked};
      if(lastState.backend==='tart')args.auto_connect=$('tartAutoConnect').checked;
      let pending;
      try{pending=call(args);}finally{$('vmPassword').value='';}
      let request;try{request=await pending;}finally{args.password='';}
      const result=await wait(request);
      status('已连接 '+result.vm+' · '+result.account+(result.transfer_verified!==true?' · 命令验证通过；文件传输未验证':' · 文件传输测试通过')+(result.credential_saved?' · 凭据已加密保存':'')+(result.unattended_warning?' · '+result.unattended_warning:result.unattended_configured?' · 无人值守'+(result.unattended_enabled?'已配置':'已关闭'):'')+(result.desktop_warning?' · 桌面：'+result.desktop_warning:''));
    });
  });
  $('vmReconnectSaved').addEventListener('click',()=>operate(async()=>{
    status('正在使用已保存凭据连接…');
    const result=await wait(await call({action:'connect_saved',vm_name:$('vmSelect').value,unattended:$('vmUnattended').checked}));
    status('已连接 '+result.vm+' · '+result.account+(result.unattended_warning?' · '+result.unattended_warning:result.unattended_configured?' · 无人值守'+(result.unattended_enabled?'已配置':'已关闭'):'')+(result.desktop_warning?' · 桌面：'+result.desktop_warning:''));
  }));
  $('vmForget').addEventListener('click',()=>operate(async()=>{
    await call({action:'forget',vm_name:$('vmSelect').value});status('已删除已保存凭据；当前连接保持不变。');
  }));
  $('vmDisconnect').addEventListener('click',()=>operate(async()=>{
    await wait(await call({action:'disconnect'}));$('vmPassword').value='';status('已断开；虚拟机仍保持原状态。');
  }));
  const powerName=()=>$('vmSelect').value||lastState.vm||lastState.saved_connections?.[0]?.vm;
  async function power(action){const run=async()=>{
    const name=powerName();if(!name)throw Error('请先在配置中选择虚拟机。');
    $('vmAgentStatus').textContent=name+' · 正在处理电源操作…';
    const result=await wait(await call({action,vm_name:name}));if(lastState.backend==='tart')selectedPower.set(name,result.power_state);
    if(action==='power_on'&&lastState.saved_connections?.some(s=>s.vm===name))await wait(await call({action:'connect_saved',vm_name:name}));
    await refreshPower();
  };if(action==='power_force'){try{H.ready();await run();}catch(error){status(error.message);}return;}return operate(run);}
  $('vmPowerOn').addEventListener('click',()=>power('power_on'));
  $('vmPowerOff').addEventListener('click',()=>power('power_off'));
  const forceDialog=H.node('dialog','','new-project-dialog project-delete-dialog');forceDialog.id='vmForceDialog';
  const forceHeader=H.node('header','','new-project-header');forceHeader.append(H.node('h2','强制关闭虚拟机？'));
  const forceClose=H.node('button','×','dialog-close');forceClose.type='button';forceClose.setAttribute('aria-label','关闭');forceClose.onclick=()=>forceDialog.close();forceHeader.append(forceClose);
  const forceCancel=H.node('button','取消','secondary-btn');forceCancel.type='button';forceCancel.onclick=()=>forceDialog.close();
  const forceConfirm=H.node('button','强制关机','danger-btn');forceConfirm.type='button';forceConfirm.onclick=()=>{forceDialog.close();void power('power_force');};
  forceDialog.append(forceHeader,H.node('p','会中断虚拟机内的程序，未保存的内容可能丢失。'),forceCancel,forceConfirm);document.body.append(forceDialog);
  $('vmPowerForce').addEventListener('click',()=>forceDialog.showModal());
  function displayPower(value){
    lastState=value;
    if(value.backend==='tart'){
      $('tartSetupOptions').hidden=false;
      $('tartEnvironment').hidden=false;
      $('tartEnvironment').textContent=!value.supported?'当前设备不满足 Tart 的 Apple Silicon / macOS 要求。':value.installed?'已检测到 Tart。':'尚未安装 Tart。'+(value.homebrew_installed?'可点击安装。':'请先安装 Homebrew，再返回重试。');
      $('tartActiveHome').textContent=(window.HubI18n?.t('实际使用目录：')||'实际使用目录：')+(value.tart_home||'');
      if(document.activeElement!==$('tartHome')&&!$('tartHome').dataset.dirty)$('tartHome').value=value.tart_home||'';
      $('tartCpu').max=$('tartManageCpu').max=value.max_cpu||1;

      $('tartInstall').hidden=!!value.installed;$('tartInstall').disabled=!value.supported||!value.homebrew_installed;
      $('tartHomebrewGuide').hidden=!!value.homebrew_installed;
      $('tartCreate').disabled=!value.supported||(!value.installed&&!value.homebrew_installed);
      if(document.activeElement!==$('tartAutoConnect'))$('tartAutoConnect').checked=value.auto_connect!==false;
      for(const id of ['vmUsername','vmPassword','vmUnattended']){$(id).disabled=true;}
      $('vmUsername').closest('.vm-account-grid').hidden=true;
      $('vmSelection').after($('vmConnectForm'));
      const quick=$('vmConnectForm').querySelector('.vm-quick-actions');quick.prepend($('vmConnect'));
      $('vmConnect').textContent='连接';$('vmReconnectSaved').hidden=true;
      $('vmRemember').checked=true;$('vmForget').hidden=true;
      $('vmConnectForm').querySelector('.vm-credentials-details').hidden=true;
      $('vmUnattended').closest('label').hidden=true;
      $('vmSettings').querySelector('.config-desc').textContent='Tart · 可选的独立执行环境';
      $('vmSettings').querySelector('.vm-credentials-details h4').textContent='Tart Guest Agent';
      $('vmRemember').closest('label').querySelector('small').textContent='仅保存虚拟机名称，不保存账号密码。';
      $('vmSettings').querySelector('.vm-credentials-details > .settings-help').textContent='访客需要 Tart Guest Agent；文件传输还需要 Python 3。连接时逐项验证。';
      $('vmSettings').querySelector(':scope > .settings-help').hidden=true;
      $('vmSettings').querySelector(':scope > .settings-help').textContent='可跳过虚拟机。点击安装指南查看安装方法；命令和文件传输按实际验证结果显示。';
      $('vmOpenManager').textContent='Tart 安装指南 ↗';
      $('vmOpenManager').title=value.install_command||'';
      $('vmForget').textContent='忘记已保存的连接';
      $('vmRefresh').title='刷新本机 Tart 列表';
      if(!$('vmSelect').value&&$('vmSelect').options.length===1)$('vmSelect').options[0].textContent='选择此数据目录内的 Tart 虚拟机';
      $('vmThumbnailRefresh').disabled=!value.desktop?.ready;
      $('vmThumbnailEmpty').lastElementChild.textContent='连接桌面后可读取真实预览';
      if(!value.vm)$('vmPreviewName').textContent='Tart';
    }
    if(!preferenceEdited){const saved=value.saved_connections?.find(s=>s.vm===($('vmSelect').value||value.vm));if(saved)$('vmUnattended').checked=saved.unattended!==false;}const labels={Running:'运行中',Off:'已关机',Starting:'正在开机',Stopping:'正在关机',Saved:'已保存',Paused:'已暂停',Unknown:'状态未知'};
    const state=value.helper_alive?value.power_state:'Unknown';
    const phases={reconnecting:'正在自动重连',waiting_windows:'等待 Windows 启动',credentials_required:'需要更新凭据',helper_offline:'连接服务未运行',helper_busy:'连接服务正在更新状态',booting:'连接服务启动中',deploying:'正在部署桌面通道'};
    const connectionLabel=value.connected?(value.backend==='tart'?'命令已连接':value.desktop?.ready===false?'命令已连接 · 等待桌面就绪':'已连接'):(phases[value.connection_phase]||'未连接');
    $('vmSettingsBadge').textContent=connectionLabel;$('vmSettingsBadge').classList.toggle('is-connected',!!value.connected);
    $('vmAgentStatus').textContent=(value.vm||value.saved_connections?.[0]?.vm||'虚拟机')+' · '+(labels[state]||'状态未知')+' · '+connectionLabel;
    const selectedState=value.backend==='tart'&&$('vmSelect').value&&$('vmSelect').value!==value.vm?(selectedPower.get($('vmSelect').value)||'Unknown'):state;
    $('vmPowerOn').disabled=selectedState==='Running'||selectedState==='Starting';
    $('vmPowerOff').disabled=selectedState==='Off';$('vmPowerForce').disabled=selectedState==='Off';
    window.dispatchEvent(new CustomEvent('hub-vm-status',{detail:value}));
  }
  async function refreshPower(){const value=await call({action:'status'});displayPower(value);return value;}
  let automatic=null;
  H.connectSavedVm=async()=>{
    if(automatic)return automatic;
    automatic=(async()=>{
      try{
        const value=await refreshPower();
        if(value.backend!=='tart'||value.auto_connect===false||!value.saved_connections?.length||value.connected)return;
        status('正在自动开机并验证 Tart 连接…');
        const result=await wait(await call({action:'auto_connect'}));if(result.skipped)status('本次不再自动开机；如需使用，请点击连接。');await refreshPower();
      }catch(error){status(error.message);}finally{automatic=null;}
    })();return automatic;
  };
  $('tartAutoConnect').addEventListener('change',()=>operate(async()=>{
    await call({action:'save_preferences',auto_connect:$('tartAutoConnect').checked});
    status($('tartAutoConnect').checked?'已开启自动连接。':'已关闭自动连接，虚拟机电源状态保持不变。');
  }));
  $('tartInstall').addEventListener('click',()=>operate(async()=>{
    status('正在安装 Tart，可能需要数分钟；不会自动执行 sudo。');
    await wait(await call({action:'install',confirmed:true}));await refreshPower();status('Tart 安装检测通过。');
  }));
  $('tartHomebrewGuide').addEventListener('click',()=>operate(()=>call({action:'open_homebrew'})));
  const confirmAction=(message,run)=>{
    const dialog=H.node('dialog','','new-project-dialog project-delete-dialog');dialog.id='tartConfirmDialog';const header=H.node('header','','new-project-header');
    header.append(H.node('h2','确认虚拟机操作'));
    const close=H.node('button','×','dialog-close');close.type='button';close.setAttribute('aria-label','关闭');close.onclick=()=>dialog.close();header.append(close);
    const cancel=H.node('button','取消','secondary-btn');cancel.type='button';cancel.onclick=()=>dialog.close();
    const yes=H.node('button','确认','primary-btn');yes.type='button';yes.onclick=()=>{dialog.close();void operate(run);};
    dialog.append(header,H.node('p',message),cancel,yes);dialog.addEventListener('close',()=>dialog.remove());document.body.append(dialog);dialog.showModal();cancel.focus();
  };
  H.openTartInstaller=()=>{if(!$('tartInstallDialog').open)$('tartInstallDialog').showModal();};
  $('tartOpenInstaller').addEventListener('click',H.openTartInstaller);
  $('tartEditHome').addEventListener('click',()=>{$('tartHome').value=lastState.tart_home||'';delete $('tartHome').dataset.dirty;$('tartDirectoryDialog').showModal();});
  document.querySelectorAll('[data-close-tart]').forEach(button=>button.addEventListener('click',()=>$(button.dataset.closeTart).close()));
  $('tartDirectoryDialog').addEventListener('close',()=>{$('tartHome').value=lastState.tart_home||'';delete $('tartHome').dataset.dirty;});
  $('tartHome').addEventListener('input',()=>{$('tartHome').dataset.dirty='1';});
  $('tartBrowseHome').addEventListener('click',()=>operate(async()=>{const result=await call({action:'browse_home'});if(result.path){$('tartHome').value=result.path;$('tartHome').dataset.dirty='1';}}));
  $('tartSaveHome').addEventListener('click',()=>{
    const home=$('tartHome').value.trim();confirmAction('切换到 '+home+'。不会移动或删除原目录；请先关闭虚拟机。',async()=>{
      await call({action:'set_home',tart_home:home,confirmed:true});delete $('tartHome').dataset.dirty;$('vmSelect').replaceChildren();await refreshPower();await refreshInventory();$('tartDirectoryDialog').close();status('目录已应用，虚拟机列表已更新。');
    });
  });
  $('tartImage').addEventListener('change',()=>{$('tartVmName').value=$('tartImage').value==='macos'?'agent-hub-macos':'agent-hub-ubuntu';});
  $('tartCreate').addEventListener('click',()=>{
    if($('tartHome').dataset.dirty){status('目录修改尚未应用，请先点击“使用此目录”，再创建虚拟机。');return;}
    const args={action:'create',vm_name:$('tartVmName').value.trim(),image:$('tartImage').value,source:$('tartSource').value.trim(),source_type:$('tartSourceType').value,cpu:Number($('tartCpu').value),memory:Number($('tartMemory').value),confirmed:true};
    confirmAction('将在 '+$('tartHome').value+' 创建 '+args.vm_name+'。在线 macOS 镜像需要下载数十 GB；请保持应用运行。',async()=>{
      if(!lastState.installed){status('正在安装 Tart…');await wait(await call({action:'install',confirmed:true}));}
      status('正在创建虚拟机；下载可能需要较长时间，请保持应用运行。');
      const created=await wait(await call(args));
      const result=await wait(await call({action:'list'}));$('vmSelect').replaceChildren();
      for(const vm of result.vms||[]){const option=document.createElement('option');option.value=vm.name;option.textContent=vm.name+' · '+vm.state+' · Tart';$('vmSelect').append(option);}
      $('vmSelect').value=args.vm_name;
      if(created.manual_setup){status(created.note);return;}
      status('虚拟机已创建，正在启动并验证连接…');
      const connected=await wait(await call({action:'connect',vm_name:args.vm_name,remember:true,auto_connect:$('tartAutoConnect').checked}));
      await refreshPower();status('已创建并连接 '+connected.vm+' · '+(connected.root_verified?'root 已验证':'root 未验证')+' · '+(connected.desktop_verified?'桌面截图已验证':connected.desktop_warning));
    });
  });
  $('vmSelect').addEventListener('change',async()=>{
    if(lastState.backend!=='tart'||!$('vmSelect').value)return;const name=$('vmSelect').value;
    try{const result=await wait(await call({action:'details',vm_name:name}));const state=String(result.details.State||'').toLowerCase();selectedPower.set(name,state==='running'?'Running':state==='stopped'?'Off':'Unknown');displayPower(lastState);}catch(error){status(error.message);}
  });
  $('tartReadResources').addEventListener('click',()=>operate(async()=>{
    const result=await wait(await call({action:'details',vm_name:powerName()}));$('tartManageCpu').value=result.details.CPU;$('tartManageMemory').value=result.details.Memory;status('已读取 '+result.vm+' 的实际资源。');
  }));
  $('tartConfigure').addEventListener('click',()=>{
    const args={action:'configure',vm_name:powerName(),cpu:Number($('tartManageCpu').value),memory:Number($('tartManageMemory').value),confirmed:true};
    confirmAction('修改 '+args.vm_name+'：CPU '+args.cpu+' 核，内存 '+args.memory+' MiB。必须先关机。',async()=>{await wait(await call(args));status('资源设置已保存。');});
  });
  $('tartDelete').addEventListener('click',()=>{
    const name=powerName();confirmAction('永久删除 '+name+' 的虚拟机磁盘，无法撤销。下载的镜像缓存单独保留。',async()=>{
      await wait(await call({action:'delete',vm_name:name,confirmed:true}));[...$('vmSelect').options].filter(o=>o.value===name).forEach(o=>o.remove());await refreshPower();status('所选虚拟机已删除。');
    });
  });
  $('tartImagesRefresh').addEventListener('click',()=>operate(async()=>{
    const result=await wait(await call({action:'images'}));$('tartCachedImage').replaceChildren();
    for(const image of result.images||[]){const option=document.createElement('option');option.value=option.textContent=image.Name||image.name;$('tartCachedImage').append(option);}status('已读取下载的镜像缓存。');
  }));
  $('tartDeleteImage').addEventListener('click',()=>{
    const source=$('tartCachedImage').value;if(!source)return;
    confirmAction('删除镜像缓存 '+source+'。再次使用时需要重新下载；已有虚拟机保留。',async()=>{await wait(await call({action:'delete_image',source,confirmed:true}));[...$('tartCachedImage').options].filter(o=>o.value===source).forEach(o=>o.remove());status('所选镜像缓存已删除。');});
  });
  const renderAccessibility=value=>{
    const state=value.accessibility||{};
    $('tartAccessibilityStatus').textContent=state.error||((state.ready?'控件通道已就绪':'控件通道未就绪')+(state.permissions?.length?' · '+state.permissions.map(p=>p.name+'：'+(p.isGranted?'已授权':'未授权')).join(' · '):''));
  };
  H.openTartAccessibility=()=>{if(!$('tartAccessibilityDialog').open)$('tartAccessibilityDialog').showModal();};
  $('tartOpenAccessibility').addEventListener('click',H.openTartAccessibility);
  $('tartCheckAccessibility').addEventListener('click',()=>operate(async()=>{
    status('正在检查访客控件权限…');renderAccessibility(await wait(await call({action:'peekaboo_status',vm_name:powerName()})));
  }));
  $('tartAccessibilityPermissions').addEventListener('click',()=>operate(async()=>{
    await wait(await call({action:'peekaboo_permissions',vm_name:powerName()}));status('已请求打开访客内的 Peekaboo 和权限设置，请在虚拟机内完成授权。');
  }));
  $('tartInstallAccessibility').addEventListener('click',()=>{
    const name=powerName();confirmAction('在 '+name+' 内安装官方 Peekaboo 4.9.7 控件驱动（约 60 MB）。需要访客 macOS 15+，首次使用需在访客内手动授权。',async()=>{
      status('正在下载、验证并安装访客控件驱动…');renderAccessibility(await wait(await call({action:'peekaboo_install',vm_name:name,confirmed:true})));
    });
  });
  $('tartOpenConsole').addEventListener('click',()=>operate(()=>call({action:'open_console',vm_name:powerName()})));
  $('btnViewStatus')?.addEventListener('click',()=>void H.connectSavedVm());
  async function refreshStatus() {
    if(busy||polling||!H.client.hasToken()||document.hidden)return;
    polling=true;
    try{const value=await refreshPower();
      for(const saved of value.saved_connections||[]){if(![...$('vmSelect').options].some(o=>o.value===saved.vm)){const o=document.createElement('option');o.value=saved.vm;o.textContent=saved.vm+' · 已保存凭据';$('vmSelect').append(o);if(!$('vmSelect').value)$('vmSelect').value=saved.vm;}}
      status(value.connected?'已连接 '+value.vm+(value.busy?' · 正在执行任务':value.power_warning?' · '+value.power_warning:value.unattended?.warning?' · '+value.unattended.warning:value.desktop?.ready===false?' · '+(value.desktop.warning||'等待 Windows 用户登录'):' · 待命'):value.connection_error||({reconnecting:'命令连接已断开，正在自动重连。',waiting_windows:'等待 Windows 启动，随后自动恢复命令连接。',credentials_required:'请更新虚拟机账号或密码。',helper_offline:'管理员连接服务未运行，请重开 Hub 或手动连接。',booting:'管理员连接服务正在启动，请稍候。',deploying:'正在部署虚拟机桌面通道。',helper_busy:'连接服务仍在运行，正在等待状态更新。'}[value.connection_phase])||(value.helper_alive?'连接服务已就绪，尚未连接虚拟机。':'尚未连接虚拟机。'));}
    catch(error){status(error.message);}finally{polling=false;}
    if(lastState.helper_alive&&!thumbCaptured)void thumbnail(true);
  }
  let thumbBusy=false,thumbName='',thumbCaptured=false,thumbAttempt=0;
  const previewVisible=()=>$('configModalToggle').checked&&!$('vmSettings').classList.contains('settings-section-inactive')&&!document.hidden;
  async function thumbnail(prefetch=false){
    if(lastState.backend==='tart'&&!lastState.desktop?.ready)return;
    if(thumbBusy||(!previewVisible()&&prefetch!==true)||!H.client.hasToken())return;
    if(prefetch===true&&Date.now()-thumbAttempt<15000)return;
    const name=$('vmSelect').value||lastState.vm;if(!name)return;
    thumbBusy=true;thumbAttempt=Date.now();const canvas=$('vmThumbnail'),label=$('vmThumbnailStatus');
    if(name!==thumbName){canvas.hidden=true;$('vmThumbnailEmpty').hidden=false;thumbName=name;thumbCaptured=false;}
    $('vmPreviewName').textContent=name;label.textContent='正在读取控制台预览…';
    try{
      const data=await wait(await call({action:'thumbnail',vm_name:name}));
      if(name!==($('vmSelect').value||lastState.vm))return;
      if(!data.available){canvas.hidden=true;$('vmThumbnailEmpty').hidden=false;label.textContent=data.note||'暂无屏幕预览';return;}
      if(data.format==='png'){
        const img=new Image();img.src='data:image/png;base64,'+data.image_data;await img.decode();
        canvas.width=img.naturalWidth;canvas.height=img.naturalHeight;canvas.getContext('2d').drawImage(img,0,0);
        thumbCaptured=true;canvas.hidden=false;$('vmThumbnailEmpty').hidden=true;label.textContent='控制台预览 · '+new Date().toLocaleTimeString();return;
      }
      const raw=atob(data.image_data||''),width=Number(data.width),height=Number(data.height);
      if(data.format!=='rgb565le'||width<1||height<1||width>640||height>480||raw.length!==width*height*2)throw Error('缩略图数据格式不正确');
      canvas.width=width;canvas.height=height;const ctx=canvas.getContext('2d'),frame=ctx.createImageData(width,height);
      for(let i=0;i<width*height;i++){const pixel=raw.charCodeAt(i*2)|(raw.charCodeAt(i*2+1)<<8);frame.data[i*4]=Math.round(((pixel>>11)&31)*255/31);frame.data[i*4+1]=Math.round(((pixel>>5)&63)*255/63);frame.data[i*4+2]=Math.round((pixel&31)*255/31);frame.data[i*4+3]=255;}
      ctx.putImageData(frame,0,0);thumbCaptured=true;canvas.hidden=false;$('vmThumbnailEmpty').hidden=true;label.textContent='控制台预览 · '+new Date().toLocaleTimeString();
    }catch(error){label.textContent=(canvas.hidden?'预览暂不可用：':'预览未更新，保留上一帧：')+error.message;}finally{thumbBusy=false;}
  }
  $('vmOpenManager').addEventListener('click',async()=>{try{await call({action:'open_manager'});}catch(error){status(error.message);}});
  $('vmThumbnailRefresh').addEventListener('click',thumbnail);$('vmSelect').addEventListener('change',thumbnail);
  window.addEventListener('hub-settings-section',()=>void thumbnail());setInterval(thumbnail,15000);
  $('configModalToggle').addEventListener('change',()=>{
    if(!$('configModalToggle').checked)$('vmPassword').value='';else {void H.connectSavedVm();void refreshStatus().then(thumbnail);}
  });
  window.addEventListener('pagehide',()=>{$('vmPassword').value='';});
  setInterval(refreshStatus,5000);
  void refreshStatus();
})();

"use strict";
(()=>{
 const H=window.HubDesktop,$=H.$;let loading=false,dirty=false;
 const bytes=n=>{const u=['B','KB','MB','GB','TB'];let i=0;while(n>=1024&&i<u.length-1){n/=1024;i++;}return n.toLocaleString(undefined,{maximumFractionDigits:i?1:0})+' '+u[i];};
 $('storageRoot').addEventListener('input',()=>{dirty=true;});
 const cleanDialog=document.createElement('dialog');cleanDialog.id='projectCleanupDialog';cleanDialog.className='project-cleanup-dialog';
 const cleanTitle=H.node('h2','清理项目文件'),cleanWarning=H.node('p','','cleanup-warning'),cleanPaths=H.node('ul','','cleanup-paths'),cleanStatus=H.node('p','','config-status-text');cleanStatus.setAttribute('role','status');
 const cleanHeader=H.node('header','','project-dialog-header'),cleanClose=H.button('×',()=>cleanDialog.close());cleanClose.className='dialog-close';cleanClose.setAttribute('aria-label','关闭');cleanHeader.append(cleanTitle,cleanClose);
 const cleanCancel=H.button('取消',()=>cleanDialog.close()),cleanConfirm=H.button('清理全部文件',async()=>{
  if(!cleanupPlan)return;
  if(!cleanupPlan.removed&&cleanupStep===0){cleanupStep=1;cleanStatus.textContent='这个项目仍保留在项目列表中。继续将删除它的项目文件和独立工作区，但保留聊天与模型上下文。请再次确认。';cleanConfirm.textContent='确认清理保留项目的文件';cleanCancel.focus();return;}
  cleanConfirm.disabled=true;cleanCancel.disabled=true;cleanClose.disabled=true;cleanStatus.textContent='正在清理项目文件…';
  try{const result=await H.client.postAction('project_cleanup',{project_id:cleanupPlan.project_id,confirmed:true,inventory_key:cleanupPlan.inventory_key});
   cleanStatus.textContent=result.ok?'已清理全部关联文件。':('部分文件未能清理：\n'+result.errors.map(e=>e.path+'：'+e.error).join('\n'));cleanupPlan=null;
   await refresh();if(result.ok)cleanDialog.close();
  }catch(error){cleanStatus.textContent=error.message;}finally{cleanCancel.disabled=false;cleanClose.disabled=false;cleanConfirm.disabled=!cleanupPlan;}
 });cleanConfirm.className='danger-btn';cleanCancel.className='secondary-btn';
 const cleanFooter=H.node('footer','','delete-dialog-actions');cleanFooter.append(cleanCancel,cleanConfirm);cleanDialog.append(cleanHeader,cleanWarning,cleanPaths,cleanStatus,cleanFooter);document.body.append(cleanDialog);let cleanupPlan=null,cleanupStep=0;
 async function cleanProject(project){
  try{H.ready();cleanupPlan=await H.client.postAction('project_cleanup',{project_id:project.id});cleanupStep=0;cleanConfirm.textContent=cleanupPlan.removed?'清理全部文件':'下一步';cleanTitle.textContent='清理“'+project.name+'”的文件';
   cleanWarning.textContent=(cleanupPlan.removed?'':'这个项目会保留在列表中。清理成功后，给经理发消息即可从空目录重新开始，对话和模型上下文会保留。')+'以下文件将永久删除，无法撤销；操作只清理本机记录的文件，不清理虚拟机内的副本。';
   cleanPaths.replaceChildren(...cleanupPlan.paths.map(p=>H.node('li',p.kind+' · '+p.path+(p.protected?'（共享或根目录，将保留）':p.exists?'':'（已不存在）'))));cleanStatus.textContent='';cleanConfirm.disabled=false;cleanDialog.showModal();cleanCancel.focus();
  }catch(error){$('storageStatus').textContent=error.message;}
 }
 function render(data){
  if(!dirty&&data.root)$('storageRoot').value=data.root;
  $('storageSummary').textContent=data.disk_free!==undefined?'所在磁盘可用 '+bytes(data.disk_free)+' / '+bytes(data.disk_total):'';
  const rows=(data.projects||[]).map(project=>{
   const row=H.node('article','','storage-project-row');row.dataset.projectId=project.id;row.dataset.removed=String(!!project.removed);
   const info=H.node('div','','storage-project-info');info.append(H.node('strong',project.name),H.node('span',project.cwd,'storage-project-path'),H.node('small',project.exists?(project.partial?'至少 ':'')+bytes(project.bytes)+' · '+project.files.toLocaleString()+' 个文件':'目录不存在','storage-project-size'));
   info.append(H.node('span',project.removed?'已从列表移除':'保留在项目列表','storage-project-badge '+(project.removed?'is-removed':'is-retained')));
   const actions=H.node('div','','storage-project-actions');const open=H.button('打开',async()=>{try{await H.client.postAction('project_open_directory',{project_id:project.id});}catch(error){$('storageStatus').textContent=error.message;}});open.className='secondary-btn btn-sm';open.disabled=!project.exists;actions.append(open);
   const remove=H.button('清理文件',()=>cleanProject(project));remove.className='settings-text-button danger-text';remove.disabled=!!project.busy;remove.title=project.busy?'项目正在执行，请先暂停或结束并等待 Agent 停止':'清理项目目录、独立工作区、演示与展示附件';actions.append(remove);
   row.append(info,actions);return row;
  });
  const groups=[];
  for(const [removed,label] of [[false,'保留的项目'],[true,'已移除的项目']]){
   const items=rows.filter(row=>row.dataset.removed===String(removed));if(!items.length)continue;
   const section=H.node('section','','storage-project-group');section.dataset.removed=String(removed);section.append(H.node('h4',label+' · '+items.length),...items);groups.push(section);
  }
  $('storageProjects').replaceChildren(...(groups.length?groups:[H.node('p','尚无项目','muted')]));
 }
 async function refresh(path){if(loading)return;loading=true;$('storageStatus').textContent='正在读取存储信息…';try{H.ready();const data=await H.client.postAction('project_storage',path===undefined?{}:{path});if(path!==undefined)dirty=false;render(data);$('storageStatus').textContent=path===undefined?'':'已保存，之后创建的新项目将使用此位置。';}catch(error){$('storageStatus').textContent=error.message;}finally{loading=false;}}
 $('storageRefresh').addEventListener('click',()=>refresh());
 $('storageForm').addEventListener('submit',event=>{event.preventDefault();void refresh($('storageRoot').value.trim());});
 $('storageBrowse').addEventListener('click',async()=>{try{const result=await H.client.postAction('project_browse_directory',{initial:$('storageRoot').value});if(result.path){$('storageRoot').value=result.path;dirty=true;}}catch(error){$('storageStatus').textContent=error.message;}});
 $('configModalToggle').addEventListener('change',()=>{if($('configModalToggle').checked)void refresh();});
})();

// Settings use category navigation; preserve the existing nodes, forms and drafts.
(() => {
 const H=window.HubDesktop;if(!H)return;const $=id=>document.getElementById(id),body=$('configModal').querySelector('.config-modal-body');
 const sections=[...body.children].filter(n=>n.matches('section.config-section-card'));const shell=H.node('div','','settings-two-column'),nav=H.node('nav','','settings-navigation');nav.setAttribute('aria-label','设置分类');const content=H.node('div','','settings-content scroll');let active=0;
 const buttons=sections.map((section,index)=>{if(!section.id)section.id='settingsSection'+index;const label=section.querySelector('h3')?.textContent.replace(/^\d+\s*·\s*/,'')||'其它';const button=H.button(label,()=>select(index));button.className='settings-nav-button';button.setAttribute('aria-controls',section.id);nav.append(button);content.append(section);return button;});
 function select(index){active=index;sections.forEach((s,i)=>s.classList.toggle('settings-section-inactive',i!==active));buttons.forEach((b,i)=>{b.hidden=sections[i].hidden;b.classList.toggle('active',i===active);b.setAttribute('aria-current',i===active?'page':'false');});content.scrollTop=0;window.dispatchEvent(new Event('hub-settings-section'));}
 const visibility=new MutationObserver(()=>{buttons.forEach((b,i)=>b.hidden=sections[i].hidden);if(sections[active]?.hidden)select(Math.max(0,sections.findIndex(s=>!s.hidden)));});sections.forEach(s=>visibility.observe(s,{attributes:true,attributeFilter:['hidden']}));
 shell.append(nav,content);body.append(shell);select(0);
})();

// Read-only Git graph: one bounded request at a time, only while the project status page is visible.
(() => {
 const H=window.HubDesktop;if(!H)return;const $=id=>document.getElementById(id),drawer=$('projectGitDrawer');let busy=false,lastProject='',lastText='';
 async function refreshGit(){if(!$('chatTabStatusRadio').checked||!$('viewModeChatRadio').checked||document.hidden||busy)return;const project=H.client.getSelectedProjectId();if(!project){$('projectGitStatus').textContent='请先选择项目';$('projectGitGraph').textContent='';$('projectGitBranches').replaceChildren();return;}
  busy=true;try{if(project!==lastProject){$('projectGitGraph').textContent='';$('projectGitBranches').replaceChildren();lastText='';lastProject=project;}$('projectGitStatus').textContent='正在刷新…';
   const data=await H.client.postAction('project_git_tree',{project_id:project});if(project!==H.client.getSelectedProjectId())return;
   const text=data.graph||data.note||'暂无提交';if(text!==lastText){$('projectGitGraph').textContent=text;lastText=text;}
   const branches=JSON.stringify(data.workspaces||[]);if($('projectGitBranches').dataset.snapshot!==branches){$('projectGitBranches').dataset.snapshot=branches;$('projectGitBranches').replaceChildren(...(data.workspaces||[]).map(w=>H.node('p',H.agentName(w.agent)+' · '+w.branch,'git-branch-label')));}
   $('projectGitStatus').textContent='最近 80 条 · 每 5 秒刷新 · '+new Date(data.updated*1000).toLocaleTimeString();
  }catch(error){$('projectGitStatus').textContent='刷新失败，保留上次记录：'+error.message;}finally{busy=false;}
 }
 for(const id of ['chatTabStatusRadio','viewModeChatRadio'])$(id).addEventListener('change',refreshGit);H.store.subscribe(()=>{if(H.client.getSelectedProjectId()!==lastProject)refreshGit();});$('refreshProjectGit').addEventListener('click',refreshGit);setInterval(refreshGit,5000);
})();
