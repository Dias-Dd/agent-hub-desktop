"use strict";
(()=>{
 const H=window.HubDesktop;if(!H)return;const $=id=>document.getElementById(id);
 let state=null,busy=false,offset=0,preview=null,historyTotal=0,latestRevision=0;
 const dirty=()=>state&&($('memoryUser').value!==state.user||$('memoryNotes').value!==state.memory);
 async function request(args){H.ready();return H.client.postAction('memory',args);}
 function controls(){
  $('memoryUserCount').textContent=$('memoryUser').value.length+' / 3000';$('memoryNotesCount').textContent=$('memoryNotes').value.length+' / 6000';
  $('memoryUser').disabled=$('memoryNotes').disabled=!state||busy;
  $('memorySave').disabled=!state||busy||!dirty();$('memoryLock').disabled=!state||busy;
  $('memoryNewer').disabled=busy||offset===0;$('memoryOlder').disabled=busy||offset+50>=historyTotal;
  $('memoryLoad').disabled=busy;$('memoryVersions').disabled=!state||busy;
  $('memoryRollback').disabled=!state||busy||!preview||preview.revision===state.revision;
  if(state){$('memoryStatus').textContent='v'+state.revision+' · '+(state.locked?'已锁定':'经理可保存')+(dirty()?' · 有未保存修改':'')+(state.revision<latestRevision?' · 已有新版本，草稿保留；重新加载可查看':'');$('memoryLock').textContent=state.locked?'解锁记忆':'锁定记忆';}
  $('memoryLoad').textContent=dirty()?'重新加载（丢弃草稿）':'加载记忆';
 }
 function fill(next){state=next;latestRevision=Math.max(latestRevision,next.revision);$('memoryUser').value=next.user;$('memoryNotes').value=next.memory;controls();}
 async function history(){
  const data=await request({operation:'history',offset});const select=$('memoryVersions');select.replaceChildren(new Option('选择版本预览',''));
  for(const v of data.versions){const date=new Date(v.created*1000).toLocaleString();select.add(new Option('v'+v.revision+' · '+date+' · '+v.actor+' · '+v.reason,String(v.revision)));}
  historyTotal=data.total;
  preview=null;$('memoryPreview').hidden=true;
 }
 async function task(fn){if(busy)return;busy=true;controls();try{await fn();}catch(error){H.notice(error.message,'error');}finally{busy=false;controls();}}
 $('memoryLoad').addEventListener('click',()=>task(async()=>{fill(await request({operation:'read'}));offset=0;await history();}));
 for(const id of ['memoryUser','memoryNotes'])$(id).addEventListener('input',controls);
 $('memoryForm').addEventListener('submit',event=>{event.preventDefault();task(async()=>{fill(await request({operation:'save',expected_revision:state.revision,user:$('memoryUser').value,memory:$('memoryNotes').value}));offset=0;await history();H.notice('长期记忆已保存');});});
 $('memoryLock').addEventListener('click',()=>task(async()=>{state=await request({operation:'lock',expected_revision:state.revision,locked:!state.locked});offset=0;await history();}));
 for(const [id,delta] of [['memoryNewer',-50],['memoryOlder',50]])$(id).addEventListener('click',()=>task(async()=>{offset=Math.max(0,offset+delta);await history();}));
 $('memoryVersions').addEventListener('change',()=>task(async()=>{preview=null;$('memoryPreview').hidden=true;if(!$('memoryVersions').value)return;preview=await request({operation:'version',revision:Number($('memoryVersions').value)});$('memoryPreviewUser').value=preview.user;$('memoryPreviewNotes').value=preview.memory;$('memoryVersionInfo').textContent='v'+preview.revision+' · '+preview.actor+' · '+new Date(preview.created*1000).toLocaleString();$('memoryPreview').hidden=false;}));
 $('memoryRollback').addEventListener('click',()=>task(async()=>{fill(await request({operation:'rollback',expected_revision:state.revision,revision:preview.revision}));offset=0;await history();H.notice('已回滚，原版本仍保留');}));
 async function synchronize(force=false){
  if(busy||!H.client.hasToken())return;
  if(dirty()){controls();return;}
  if(!force&&state&&state.revision>=latestRevision)return;
  await task(async()=>{
   const next=await request({operation:'read'});
   if(dirty())return;
   if(!state||state.revision!==next.revision){fill(next);if(!preview){offset=0;await history();}}
  });
 }
 H.render(view=>{
  const revision=view.rawSnapshot?.memory_revision;
  if(!Number.isInteger(revision))return;
  latestRevision=Math.max(latestRevision,revision);
  if(state||!$('memorySettings').classList.contains('settings-section-inactive'))synchronize();
 });
 window.addEventListener('hub-settings-section',()=>{if(!$('memorySettings').classList.contains('settings-section-inactive'))synchronize(true);});
 controls();
})();
