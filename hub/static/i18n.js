"use strict";
(()=>{
 const key='hub.interfaceLanguage',documents=new Set(),originals=new WeakMap(),attributes=new WeakMap();
 let language=document.querySelector('meta[name="hub-interface-language"]')?.content||'zh-CN',catalog={};
 try{if(!document.querySelector('meta[name="hub-interface-language"]'))language=localStorage.getItem(key)||language;}catch{}
 if(!['en','zh-CN'].includes(language))language='zh-CN';
 const protectedContent='script,style,pre,code,textarea,[contenteditable],.chat-markdown,.chat-message-body,.artifact-file-title,.artifact-caption,.agent-name,.agent-id-tag,.agent-model,.agent-mini-name,#currentManagerName,#nativeProjectTitle,.project-name,.project-list-item,#hubProjectSelect option:not([value=""]),#agentConnection option,#agentModel option,[data-user-content]';
 function translate(source){
  if(language!=='en'||typeof source!=='string')return source;
  const trimmed=source.trim();if(catalog[trimmed])return source.replace(trimmed,catalog[trimmed]);
  const patterns=[[/^(\d+) 项目$/,'$1 projects'],[/^(\d[\d,]*) \/ 20,000 字符$/,'$1 / 20,000 characters'],[/^当前经理：\s*/,'Current manager: '],[/^经理：\s*/,'Manager: '],[/^已填写 (\d+) 页修改意见，提交时与整体意见一起发送。$/,'Feedback saved for $1 pages; submitted with overall feedback.'],[/^适应窗口 · /,'Fit · '],[/^最近 (\d+) 条 · 每 (\d+) 秒刷新/,'Last $1 entries · Refresh every $2 seconds'],[/^等待 /,'Waiting for '],[/^适配器目录：/,'Adapter directory: '],[/^已接入：/,'Connected: ']];
  for(const [pattern,replacement] of patterns)if(pattern.test(trimmed))return source.replace(pattern,replacement);
  const dynamic=[[/^当前连接：/,'Connected to: '],[/^计划 v/,'Plan v'],[/^停止 /,'Stop '],[/^经理 /,'Manager '],[/^当前任务：/,'Current task: '],[/^(\d+) 个待执行提醒 · (\d+) 条待交付通知$/,'$1 reminders · $2 pending notifications']];
  for(const [pattern,replacement] of dynamic)if(pattern.test(trimmed))return source.replace(pattern,replacement);
  const cleanup=source.match(/^清理“(.*)”的文件$/);if(cleanup)return 'Clean files for “'+cleanup[1]+'”';
  const testing=source.match(/^测试 (.*)？$/);if(testing)return 'Test '+testing[1]+'?';
  const realTests=source.match(/^将测试 (\d+) 个 Agent，/);if(realTests)return 'Test '+realTests[1]+' Agents, up to 8 at a time. Each Agent sends at most one real request using its current connection and effort, consuming subscription quota or API balance. Busy, disabled and stop-locked Agents are skipped. Tests use isolated sessions without project history or task assignment. Failures are not retried automatically. Results appear on each Agent card.';
  if(source.includes(' · '))return source.split(' · ').map(part=>translate(part)).join(' · ');
  if(source.includes('\n'))return source.split('\n').map(part=>translate(part)).join('\n');
  return source;
 }
 function text(node){
  if(!node.parentElement||node.parentElement.closest(protectedContent))return;
  const prior=originals.get(node),current=node.nodeValue;
  const source=prior&&current===prior.output?prior.source:current;
  const output=translate(source);originals.set(node,{source,output});if(current!==output)node.nodeValue=output;
 }
 function element(el){
  if(el.closest?.(protectedContent)&&el.tagName!=='TEXTAREA')return;
  let saved=attributes.get(el);if(!saved){saved={};attributes.set(el,saved);}
  for(const name of ['title','placeholder','aria-label']){
   const current=el.getAttribute(name);if(current===null)continue;
   const previous=saved[name],source=previous&&current===previous.output?previous.source:current,output=translate(source);
   saved[name]={source,output};if(current!==output)el.setAttribute(name,output);
  }
 }
 function visit(root){
  if(root.nodeType===3){text(root);return;}
  if(root.nodeType!==1&&root.nodeType!==9)return;
  if(root.nodeType===1)element(root);
  const doc=root.ownerDocument||root;
  const walker=doc.createTreeWalker(root,NodeFilter.SHOW_ELEMENT|NodeFilter.SHOW_TEXT);
  while(walker.nextNode()){const node=walker.currentNode;if(node.nodeType===3)text(node);else element(node);}
 }
 function attach(doc,titleSource=null){
  if(titleSource)doc._hubWindowTitleSource=titleSource;
  if(documents.has(doc))return;documents.add(doc);visit(doc.body);
  const observer=new MutationObserver(changes=>{
   for(const change of changes){if(change.type==='childList')for(const added of change.addedNodes)visit(added);else if(change.type==='characterData')text(change.target);else element(change.target);}
  });observer.observe(doc.body,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['title','placeholder','aria-label']});
  doc.defaultView.addEventListener('unload',()=>{observer.disconnect();documents.delete(doc);},{once:true});
 }
 function set(value,persist=true){
  if(!['en','zh-CN'].includes(value))return;language=value;document.documentElement.lang=value;
  if(persist){try{localStorage.setItem(key,value);}catch{}window.chrome?.webview?.postMessage({type:'hub-window',command:'language',language:value});window.webkit?.messageHandlers?.hubNative?.postMessage({language:value});}
  for(const doc of documents){doc.documentElement.lang=value;if(doc._hubWindowTitleSource)doc.title=translate(doc._hubWindowTitleSource)+' · Agent Hub';visit(doc.body);}
  const select=document.getElementById('interfaceLanguage');if(select)select.value=value;
  document.dispatchEvent(new CustomEvent('hub-language-change',{detail:value}));
 }
 window.HubI18n={t:translate,set,attach,get language(){return language;}};
 attach(document);
 document.getElementById('interfaceLanguage')?.addEventListener('change',event=>set(event.target.value));
 fetch('/i18n.json').then(response=>response.json()).then(value=>{catalog=value;set(language,false);}).catch(()=>{});
})();
