"use strict";
(() => {
 const H=window.HubDesktop, {$,bind,node,text}=H;
 let loaded=null,current=null,page=null,region=null,start=null,selecting=false,previousFocus=null,loadedProject=null;
 let zoom=60,zoomMode='fit',opening=false,restoreAttempt=null,pageDrafts={};
 const zoomRules=new WeakMap();let zoomDocument=null,zoomRule=null,canvasWidth=1280,canvasHeight=900;
 const pageSizes=new Map();
 function applyZoom(){const doc=$('designCanvas').ownerDocument;if(!zoomRule||zoomDocument!==doc){zoomDocument=doc;zoomRule=zoomRules.get(doc);if(!zoomRule){const sheet=[...doc.styleSheets].find(s=>s.href?.endsWith('/design.css'));const index=sheet.insertRule('.design-canvas {}',sheet.cssRules.length);zoomRule=sheet.cssRules[index];zoomRules.set(doc,zoomRule);}}zoomRule.style.zoom=String(zoom/100);zoomRule.style.width=canvasWidth+'px';zoomRule.style.height=canvasHeight+'px';}
 function feedbackCount(){text('designFeedbackCount','已填写 '+Object.values(pageDrafts).filter(d=>d.text?.trim()).length+' 页修改意见，提交时与整体意见一起发送。');}
 const reviewKey=()=> 'hub.designReview.'+(loadedProject||H.client.getSelectedProjectId()||'');
 const savedReview=()=>{try{return JSON.parse(sessionStorage.getItem(reviewKey())||'null');}catch{return null;}};
 function savePageDraft(){if(page)pageDrafts[page.id]={text:$('designFeedbackText').value,scope:$('designFeedbackScope').value,region};feedbackCount();}
 function persistReview(){if(!current||!loaded)return;savePageDraft();try{sessionStorage.setItem(reviewKey(),JSON.stringify({id:current.id,version:loaded.version,page:page?.id,zoom,zoomMode,open:!$('designReviewDialog').hidden,navTop:$('designPageList').scrollTop,stageTop:$('designStage').scrollTop,stageLeft:$('designStage').scrollLeft,overall:$('designOverallFeedback').value,drafts:pageDrafts}));}catch{}}
 let saveTimer=null;function saveSoon(){clearTimeout(saveTimer);saveTimer=setTimeout(persistReview,80);}
 window.addEventListener('beforeunload',persistReview);
 for(const id of ['designFeedbackText','designFeedbackScope','designOverallFeedback'])$(id).addEventListener('input',saveSoon);
 for(const el of [$('designPageList'),$('designStage')])el.addEventListener('scroll',saveSoon,{passive:true});
 function setZoom(value,mode='manual',anchor=null){
  const stage=$('designStage'),old=zoom;zoom=Math.max(5,Math.min(200,value));zoomMode=mode;
  const x=anchor?.x??stage.clientWidth/2,y=anchor?.y??stage.clientHeight/2,left=(stage.scrollLeft+x)/old,top=(stage.scrollTop+y)/old;
  $('designCanvas').dataset.zoom=String(zoom);applyZoom();
  stage.scrollLeft=mode==='fit'?0:left*zoom-x;stage.scrollTop=mode==='fit'?0:top*zoom-y;
  const select=$('designZoomLevel');select.options[0].textContent='适应窗口'+(mode==='fit'?' · '+Math.round(zoom)+'%':'');select.value=mode==='fit'?'fit':String(zoom);
  if(!select.value){const option=node('option',Math.round(zoom)+'%');option.value=String(zoom);select.append(option);select.value=String(zoom);}
  persistReview();
 }
 function fitZoom(){const stage=$('designStage');if(stage.clientWidth&&stage.clientHeight)setZoom(Math.min((stage.clientWidth-24)/canvasWidth,(stage.clientHeight-24)/canvasHeight)*100,'fit');}
 function canvasSize(width,height){
  canvasWidth=width;canvasHeight=height;
  applyZoom();zoomRule.style.width=width+'px';zoomRule.style.height=height+'px';
 }
 $('designFrame').addEventListener('load',()=>{
  const frame=$('designFrame');if(!loaded||!page||frame.getAttribute('src')!==loaded.urls[page.id])return;
  try{
   const doc=frame.contentDocument;if(!doc?.body)return;
   // Read-only measurement: preview scripts remain forbidden by CSP and sandbox.
   // Centred fixed-width pages can extend LEFT of a narrow iframe. scrollWidth
   // only includes their right-hand overflow; include the missing negative edge.
   let left=0,right=0;
   for(const element of doc.body.querySelectorAll('*')){
    const bounds=element.getBoundingClientRect();
    if(bounds.width&&bounds.height){left=Math.min(left,bounds.left);right=Math.max(right,bounds.right);}
   }
   const width=Math.ceil(Math.max(canvasWidth,doc.documentElement.scrollWidth,doc.body.scrollWidth,right-left));
   const height=Math.max(canvasHeight,doc.documentElement.scrollHeight,doc.body.scrollHeight);
   pageSizes.set(frame.getAttribute('src'),[width,height]);canvasSize(width,height);if(zoomMode==='fit')fitZoom();
  }catch(_){}
 });
 function stepZoom(direction,anchor=null){setZoom(zoom*Math.exp(direction*.18),'manual',anchor);}
 $('designZoomIn').addEventListener('click',()=>stepZoom(1));$('designZoomOut').addEventListener('click',()=>stepZoom(-1));
 $('designZoomActual').addEventListener('click',()=>setZoom(100));$('designZoomFit').addEventListener('click',fitZoom);
 $('designZoomLevel').addEventListener('change',()=>{$('designZoomLevel').value==='fit'?fitZoom():setZoom(Number($('designZoomLevel').value));});
 $('designStage').addEventListener('wheel',event=>{event.preventDefault();if(!event.deltaY)return;const r=event.currentTarget.getBoundingClientRect();const delta=event.deltaY*(event.deltaMode===1?16:event.deltaMode===2?stage.clientHeight:1);setZoom(zoom*Math.exp(-delta*.0015),'manual',{x:event.clientX-r.left,y:event.clientY-r.top});},{passive:false});
 const stage=$('designStage');let pan=null;
 function endPan(){pan=null;stage.classList.remove('panning');persistReview();}
 stage.addEventListener('pointerdown',event=>{
  if(event.button!==1&&(event.button!==0||selecting))return;event.preventDefault();event.stopPropagation();
  pan={id:event.pointerId,x:event.clientX,y:event.clientY,left:stage.scrollLeft,top:stage.scrollTop};
  stage.classList.add('panning');stage.focus({preventScroll:true});stage.setPointerCapture(event.pointerId);
 },true);
 stage.addEventListener('pointermove',event=>{if(!pan||event.pointerId!==pan.id)return;event.preventDefault();event.stopPropagation();stage.scrollLeft=pan.left+pan.x-event.clientX;stage.scrollTop=pan.top+pan.y-event.clientY;},true);
 stage.addEventListener('pointerup',event=>{if(pan&&event.pointerId===pan.id){event.preventDefault();event.stopPropagation();endPan();}},true);
 for(const type of ['pointercancel','lostpointercapture'])stage.addEventListener(type,endPan);
 stage.addEventListener('auxclick',event=>{if(event.button===1)event.preventDefault();});
 window.addEventListener('blur',()=>{if(pan)endPan();});
 $('designClearRegion').addEventListener('click',()=>{clearRegion();persistReview();});
 new ResizeObserver(()=>{if(zoomMode==='fit'&&!$('designReviewDialog').hidden)fitZoom();}).observe($('designStage'));
 const currentSession=()=>H.view.managerStream.planning;
 const activeDesign=()=>{const p=currentSession();const raw=(H.view.rawSnapshot?.planning||[]).find(x=>x.id===p?.sessionId);return (H.view.rawSnapshot?.designs||[]).find(d=>d.id===raw?.design_id)||null;};
 const call=(name,args)=>H.action(name,args);
 bind('skipDesign','click',()=>{const p=currentSession();return call('design_skip',{session_id:p.sessionId,revision:p.revision});});
 function close(){ $('designReviewDialog').hidden=true;persistReview();previousFocus?.focus(); }
 bind('closeDesignReview','click',close);
 document.addEventListener('keydown',e=>{
  if($('designReviewDialog').hidden||!$('designReviewDialog').contains(e.target))return;
  if(e.key==='Delete' && region && !e.target.closest('input,textarea,select,[contenteditable]')){e.preventDefault();clearRegion();persistReview();return;}
  if(e.key==='Escape'){e.preventDefault();close();}
  if(e.key==='Tab'){
   const items=[...$('designReviewDialog').querySelectorAll('button,select,textarea,[tabindex="0"]')].filter(x=>!x.disabled && x.getClientRects().length);
   if(e.shiftKey && $('designReviewDialog').ownerDocument.activeElement===items[0]){e.preventDefault();items.at(-1)?.focus();}
   else if(!e.shiftKey && $('designReviewDialog').ownerDocument.activeElement===items.at(-1)){e.preventDefault();items[0]?.focus();}
  }
 });
 function clearRegion(){region=null;start=null;$('designClearRegion').disabled=true;$('designSelection').setAttribute('width','0');$('designSelection').setAttribute('height','0');$('designSelectionArrow').setAttribute('d','M 0 0');text('designRegionText','尚未框选，可直接描述设计或逻辑意见。');}
 let previewIssuedAt=0,previewRenewal=null,previewSerial=0;
 async function renewPreview(){
  if(previewRenewal)return previewRenewal;
  const original=loaded,design=current?.id,project=loadedProject;
  const request=call('design_content',{design_id:design,version:original.version}).then(content=>{
   if(loaded===original&&current?.id===design&&loadedProject===project&&project===H.client.getSelectedProjectId()){
    loaded.urls=content.urls;previewIssuedAt=Date.now();return true;
   }return false;
  });previewRenewal=request;
  try{return await request;}finally{if(previewRenewal===request)previewRenewal=null;}
 }
 async function loadPreview(id,probe=false){
  const serial=++previewSerial,original=loaded;
  try{
   if(Date.now()-previewIssuedAt>45*60*1000){if(!await renewPreview())return;}
   if(probe){
    const response=await fetch(loaded.urls[id],{cache:'no-store',signal:AbortSignal.timeout(10000)});
    if(!response.ok){if(!await renewPreview())return;}
   }
   if(serial!==previewSerial||loaded!==original||page?.id!==id||loadedProject!==H.client.getSelectedProjectId())return;
   const frame=$('designFrame'),url=loaded.urls[id];if(frame.getAttribute('src')!==url)frame.src=url;
  }catch(error){if(serial===previewSerial)H.notice('演示预览暂时无法连接，恢复后会自动重试：'+error.message);}
 }
 function recoverPreview(){if(loaded&&page&&!$('designReviewDialog').hidden)loadPreview(page.id,true);}
 window.addEventListener('focus',recoverPreview);
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)recoverPreview();});
 setInterval(recoverPreview,60000);
 function showPage(id){
  savePageDraft();page=loaded.pages.find(p=>p.id===id);if(!page)return;
  canvasSize(...(pageSizes.get(loaded.urls[id])||[1280,900]));
  clearRegion();loadPreview(id,true);text('designPageTitle',page.title);text('designPageNote',page.note||'此页展示最终布局与设计语言；实际交互在正式制作阶段实现。');
  for(const b of $('designPageList').querySelectorAll('button'))b.setAttribute('aria-current',b.dataset.page===id?'page':'false');
  const draft=pageDrafts[id];$('designFeedbackText').value=draft?.text||'';$('designFeedbackScope').value=draft?.scope||'region';
  if(draft?.region){start={x:draft.region.x,y:draft.region.y};draw({x:start.x+draft.region.width,y:start.y+draft.region.height});start=null;}
  if(zoomMode==='fit')fitZoom();
  persistReview();
 }
 function renderTree(){
  const make=parent=>{const ul=node('ul');for(const p of loaded.pages.filter(x=>(x.parent||null)===parent)){
   const li=node('li'),b=node('button',(p.kind==='architecture'?'◇ ':'')+p.title,'secondary-btn');b.type='button';b.dataset.page=p.id;b.addEventListener('click',()=>showPage(p.id));li.append(b,make(p.id));ul.append(li);
  }return ul;};
  $('designPageList').replaceChildren(node('h3','全部页面与层级'),make(null));
 }
 async function openReview(){
  if(opening)return;opening=true;
  try{
   const d=activeDesign();if(!d?.versions?.length)throw Error('演示仍在制作，请稍后查看');
   const project=H.client.getSelectedProjectId(),version=d.versions.at(-1).version;
   const content=await call('design_content',{design_id:d.id,version});
   if(project!==H.client.getSelectedProjectId())return;
   current=d;loaded=content;previewIssuedAt=Date.now();loadedProject=project;previousFocus=document.activeElement;
   const candidate=savedReview(),saved=candidate?.id===d.id&&candidate.version===content.version?candidate:null;
   page=null;pageDrafts=saved?.drafts||{};$('designOverallFeedback').value=saved?.overall||'';zoom=saved?.zoom||60;zoomMode=saved?.zoomMode||'fit';
   renderTree();showPage(saved?.page&&content.pages.some(p=>p.id===saved.page)?saved.page:content.pages[0].id);
   text('designVersionText',content.title+' · 设计 v'+content.version+' · 共 '+content.pages.length+' 页');
   $('designReviewDialog').hidden=false;if(zoomMode==='fit')fitZoom();else setZoom(zoom);
   if(saved){$('designPageList').scrollTop=saved.navTop||0;if(zoomMode!=='fit'){const stage=$('designStage');stage.scrollTop=saved.stageTop||0;stage.scrollLeft=saved.stageLeft||0;}}
   $('closeDesignReview').focus();persistReview();render(H.view);
  }finally{opening=false;}
 }
 bind('openDesignReview','click',openReview);
 bind('designSelectRegion','click',()=>{selecting=!selecting;$('designOverlay').classList.toggle('selecting',selecting);$('designSelectRegion').setAttribute('aria-pressed',String(selecting));text('designSelectRegion',selecting?'正在框选，拖动标记区域':'框选需要修改的区域');});
 const point=e=>{const r=$('designOverlay').getBoundingClientRect();return {x:Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),y:Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))};};
 const draw=end=>{
  $('designClearRegion').disabled=false;
  region={x:Math.min(start.x,end.x),y:Math.min(start.y,end.y),width:Math.abs(start.x-end.x),height:Math.abs(start.y-end.y)};
  for(const [k,v] of Object.entries(region))$('designSelection').setAttribute(k,String(v*1000));
  const x=(region.x+region.width)*1000,y=region.y*1000;
  $('designSelectionArrow').setAttribute('d',`M ${x} ${y} l 45 -35 m -18 0 h 18 v 18`);
  text('designRegionText','已框选「'+page.title+'」：横向 '+Math.round(region.x*100)+'%、纵向 '+Math.round(region.y*100)+'% 起，宽 '+Math.round(region.width*100)+'%、高 '+Math.round(region.height*100)+'%。');
 };
 $('designOverlay').addEventListener('pointerdown',e=>{if(!selecting||e.button!==0)return;e.preventDefault();stage.focus({preventScroll:true});start=point(e);e.currentTarget.setPointerCapture(e.pointerId);draw(start);});
 $('designOverlay').addEventListener('pointermove',e=>{if(start)draw(point(e));});
 $('designOverlay').addEventListener('pointerup',e=>{if(start){draw(point(e));start=null;persistReview();}});
 $('designOverlay').addEventListener('pointercancel',()=>{start=null;});
 bind('submitDesignFeedback','click',async()=>{
  if(!loaded||!current)throw Error('请先查看演示');
  savePageDraft();
  const entries=Object.entries(pageDrafts).filter(([id,d])=>d.text?.trim()).map(([id,d])=>({page_id:id,body:d.text.trim(),scope:d.scope,region:d.region}));
  const overall=$('designOverallFeedback').value.trim();if(!entries.length&&!overall)throw Error('请填写修改意见');
  const button=$('submitDesignFeedback');button.disabled=true;
  try{await call('design_feedback',{design_id:current.id,version:loaded.version,entries,overall});
   pageDrafts={};$('designFeedbackText').value='';$('designOverallFeedback').value='';clearRegion();persistReview();H.notice('全部修改意见已交给经理，正在统一制作下一版演示。','status');
  }finally{button.disabled=false;}
 });
 bind('acceptDesign','click',async()=>{
  if(!loaded||!current)throw Error('请先查看最终演示');
  await call('design_accept',{design_id:current.id,version:loaded.version,digest:loaded.digest});close();H.notice('已确认最终设计，经理开始安排正式制作。','status');
 });
 function render(v){
  if(loadedProject && loadedProject!==H.client.getSelectedProjectId()) {close();loaded=null;current=null;loadedProject=null;}
  const d=activeDesign();$('designStatusCard').hidden=!d;
  const remembered=savedReview(),attemptKey=H.client.getSelectedProjectId()+':'+d?.id;
  if(d?.versions?.length&&!loaded&&!opening&&remembered?.open&&remembered.id===d.id&&restoreAttempt!==attemptKey){restoreAttempt=attemptKey;openReview().catch(error=>H.notice(error.message));}
  if(d){
   text('designStatusText',d.publish_error?'设计 v'+d.version+' 发布未完成：'+d.publish_error:d.state==='building'?'设计 v'+d.version+' 制作中，仅制作演示，尚未开始真实产品。':d.state==='review'?'设计 v'+d.version+' 已就绪，请逐页审阅、框选修改或确认后正式制作。':'设计 v'+d.version+' 已确认，正式制作须遵循此基线。');
   $('openDesignReview').disabled=!d.versions.length;
  }
  if(loaded && current){
   const latest=(v.rawSnapshot?.designs||[]).find(x=>x.id===current.id);
   const editable=latest?.state==='review' && latest.version===loaded.version;
   $('acceptDesign').disabled=!editable;$('submitDesignFeedback').disabled=!editable;
   H.list('designFeedbackHistory',(latest?.feedback||[]).map(f=>H.record('v'+f.version+' · '+(f.page_id||'整体')+' · '+f.scope,f.body,'修改意见')));
  }
 }
 const designSource=document.createElement('div');designSource.hidden=true;document.body.append(designSource);designSource.append($('designStatusCard'));
 H.render(render);
})();
