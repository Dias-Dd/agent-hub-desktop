'use strict';
// The controllers share one in-memory client/store; no credentials enter storage.
(() => {
  const lastProjectKey='hub.lastOpenedProject';
  class DesktopClient extends HubApiClient {
    setSelectedProjectId(projectId) {
      const seq=super.setSelectedProjectId(projectId);
      try { if(projectId)localStorage.setItem(lastProjectKey,projectId);else localStorage.removeItem(lastProjectKey); } catch (_) {}
      return seq;
    }
    async getState(meta = {}) {
      const request = this._desktopStateRequest = (this._desktopStateRequest || 0) + 1;
      const seq = this.getCurrentPollSeq();
      const project = this.getSelectedProjectId();
      try {
        const snapshot = await super.getState(meta);
        // Also guard the asynchronous JSON body read, and late failed requests.
        if (request !== this._desktopStateRequest || seq !== this.getCurrentPollSeq() || project !== this.getSelectedProjectId()) throw new Error('stale');
        return snapshot;
      } catch (error) {
        if (request !== this._desktopStateRequest || seq !== this.getCurrentPollSeq() || project !== this.getSelectedProjectId()) error.discarded = true;
        throw error;
      }
    }
  }
  let rememberedProject='';try {rememberedProject=localStorage.getItem(lastProjectKey)||'';}catch(_) {}
  const client = new DesktopClient({projectId:rememberedProject});
  const store = new HubStateStore({ client });
  const $ = id => document.getElementById(id);
  const node = (tag, text = '', cls = '') => SafeDOM.createElement(tag, text, cls);
  const text = (id, value) => SafeDOM.setText($(id), value);
  const value = id => $(id).value;
  const checked = id => $(id).checked;
  const number = id => Number(value(id));
  let noticeTimer = null;
  const notice = (message, kind = 'error') => {
    clearTimeout(noticeTimer);
    const el = $('notice'); el.className = kind === 'error' ? 'notice-error' : '';
    el.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    text('notice', message);
    noticeTimer = setTimeout(() => text('notice', ''), 9000);
  };
  const endpoint = window.location?.origin || '当前本机 Hub';
  const metadata = name => document.querySelector?.('meta[name="' + name + '"]')?.getAttribute('content');
  text('loginEndpoint', '当前连接：' + endpoint);
  const credentialFile = metadata('hub-credentials-path');
  if (credentialFile) text('credentialPath', '此实例凭证文件：' + credentialFile);
  function parseToken(input) {
    let token = input.trim().replace(/^\uFEFF/, '');
    if (token.startsWith('{') || token.startsWith('"')) {
      let parsed;
      try { parsed = JSON.parse(token); } catch (_) { throw new Error('凭证 JSON 格式不完整，请复制整个 credentials.json 文件，或仅复制 user 的值。'); }
      token = typeof parsed === 'string' ? parsed : parsed?.user;
      if (typeof token !== 'string') throw new Error('凭证文件缺少 user 字段，请使用当前实例的 credentials.json。');
    }
    token = token.trim().replace(/^['"]|['"]$/g, '').replace(/\s+/g, '');
    if (!token) throw new Error('请输入 user 凭证，或粘贴 credentials.json 全部内容。');
    return token;
  }
  const renderers = [];
  let view = store.getNormalizedState();
  let switching = false;
  let healthBusy = false;
  let healthTime = 0;
  const addCls = (el, name) => { if (!el) return; if (el.classList?.add) el.classList.add(name); else if (!el.className?.includes(name)) el.className = ((el.className || '') + ' ' + name).trim(); };
  const rmCls = (el, name) => { if (!el) return; if (el.classList?.remove) el.classList.remove(name); else if (el.className) el.className = el.className.replace(new RegExp('\\b' + name + '\\b', 'g'), '').trim(); };
  const isBusyStatus = s => ['running','working','pending','queued','acknowledged','waiting_quota','active'].includes(s);
  const statusLabel = status => ({
    pending:'pending · 排队待领取',
    user_delivered:'已送达',
    waiting_project:'暂缓 · 等待项目恢复或核查',
    archived:'已归档 · 项目结束，未再投递',
    acknowledged:'acknowledged · 已领取，非完成',
    completed:'completed · 已完成',
    paused:'paused · 已暂停',
    uncertain:'uncertain · 结果待核实',
    running:'running · 执行中',
    queued:'queued · 待执行',
    failed:'failed · 失败',
    cancelled:'cancelled · 已取消',
    active:'active · 执行中',
    working:'working · 执行中',
    waiting_quota:'waiting_quota · 等待额度'
  }[status] || status || '未知');
  const ready = () => {
    if (!client.hasToken()) throw new Error('请先连接工作台');
    if (switching) throw new Error('正在切换项目，请稍候');
  };
  // Per-control serialization prevents double clicks, while retries remain explicit.
  function bind(id, event, handler, guard = true) {
    const el = $(id);
    if (!el) throw new Error('缺少 DOM 挂载点 #' + id);
    let busy = false;
    el.addEventListener(event, async e => {
      e.preventDefault();
      if (busy) return;
      busy = true;
      const controls = el.tagName === 'FORM' ? [...el.querySelectorAll('button')] : [el];
      controls.forEach(c => { c.disabled = true; addCls(c, 'is-loading'); });
      try { if (guard) ready(); await handler(e); }
      catch (error) { notice(error.message); if (!$('setupWizard').hidden) text('setupError',error.message); }
      finally { busy = false; controls.forEach(c => { c.disabled = false; rmCls(c, 'is-loading'); }); }
    });
  }
  function projectMenuIcon(label) {
    const paths={'重命名':['M12 4l4 4','M4 16l1-5L13 3a2.1 2.1 0 013 3L8 14z'], '打开所在目录':['M3 6h5l2 2h7v8H3z','M3 6V4h5l2 2h7v2'], '项目设置':['M3 5h14M3 10h14M3 15h14','M7 3v4M13 8v4M7 13v4'], '删除项目':['M4 5h12M8 3h4M6 5l1 12h6l1-12','M9 8v6M11 8v6']};
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 20 20');svg.setAttribute('class','project-action-icon');svg.setAttribute('aria-hidden','true');svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','1.4');svg.setAttribute('stroke-linecap','round');svg.setAttribute('stroke-linejoin','round');for(const d of paths[label]||[]){const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d',d);svg.append(path);}return svg;
  }
  const button = (label, handler) => {
    const b = node('button', label, 'secondary-btn btn-xs'); b.type = 'button';
    let busy = false;
    b.addEventListener('click', async () => {
      if (busy) return;
      busy = true; b.disabled = true; addCls(b, 'is-loading');
      try { ready(); await handler(); } catch (e) { notice(e.message); }
      finally { busy = false; b.disabled = false; rmCls(b, 'is-loading'); }
    });
    return b;
  };
  function longText(body, heading = '展开全文') {
    const content = String(body ?? '');
    if (content.length <= 500) return node('p', content);
    const d = node('details');
    let hash = 0;
    for (let i = 0; i < content.length; i++) {
      hash = ((hash << 5) - hash) + content.charCodeAt(i);
      hash |= 0;
    }
    d.dataset.detailKey = `${heading}_${hash}_${content.length}`;
    d.append(node('summary', heading + ' · ' + (content.length > 80 ? content.slice(0, 80) + '…' : content)));
    let loaded = false;
    d.ensureContent = () => { if (!loaded) { d.append(node('pre', content, 'expanded-text-content')); loaded = true; } };
    d.addEventListener('toggle', () => { if (d.open) d.ensureContent(); });
    return d;
  }
  function createActualInputDrawer(key, promptText, label = '查看实际模型输入 (Actual Input)') {
    const content = String(promptText ?? '').trim();
    if (!content) return null;
    const d = node('details', '', 'actual-input-drawer');
    d.dataset.detailKey = 'actual_input_' + key;
    const summary = node('summary', label);
    const box = node('div', '', 'actual-input-box');
    const copyBtn = node('button', '复制完整 Prompt', 'secondary-btn btn-xs copy-prompt-btn');
    copyBtn.type = 'button';
    copyBtn.addEventListener('click', async e => {
      e?.preventDefault?.();
      e?.stopPropagation?.();
      try {
        if (navigator.clipboard?.writeText) {
          await navigator.clipboard.writeText(content);
          copyBtn.textContent = '已复制！';
          setTimeout(() => { copyBtn.textContent = '复制完整 Prompt'; }, 2000);
        } else {
          notice('剪贴板不可用');
        }
      } catch (_) {
        notice('复制失败，请手动选取');
      }
    });
    const pre = node('pre', '', 'actual-input-content');
    d.ensureContent = () => { if (!pre.textContent) pre.textContent = content; };
    d.addEventListener('toggle', () => { if (d.open) d.ensureContent(); });
    box.append(copyBtn, pre);
    d.append(summary, box);
    return d;
  }
  const record = (title, body, status) => {
    const d = node('article', '', 'item');
    d.dataset.live = isBusyStatus(status) || status === 'blocked' ? 'true' : 'false';
    const pStatus = node('p', '');
    if (isBusyStatus(status)) {
      const sp = node('span', '', 'loading-spinner');
      const textSpan = node('span', statusLabel(status));
      pStatus.append(sp, textSpan);
    } else {
      pStatus.textContent = statusLabel(status);
    }
    const fullTitle = String(title ?? '');
    d.append(node('strong', fullTitle.length > 180 ? fullTitle.slice(0, 180) + '…' : fullTitle), pStatus);
    if (fullTitle.length > 180) d.append(longText(fullTitle, '展开完整任务标题'));
    d.append(longText(body)); return d;
  };
  const dump = data => typeof data === 'string' ? data : JSON.stringify(data ?? {}, null, 2);
  function chatTime(timestamp) {
    const stamp=node('time','','chat-timestamp');
    if (typeof timestamp === 'number' && timestamp > 0) {
      const date=new Date(timestamp*1000);stamp.dateTime=date.toISOString();stamp.textContent=date.toLocaleString('zh-CN',{hour12:false});
    } else stamp.textContent='时间未记录';
    return stamp;
  }
  function readableChat(body) {
    const source=String(body??'');
    const plain=source.replace(/^\[真实[^\]\n]*\]\s*/, '').replace(/^\[主动汇报\]\s*/, '');
    const clean=plain.trim().replace(/^```(?:json)?\s*\n?/, '').replace(/\n?```\s*$/, '').trim();
    try {const data=JSON.parse(clean);if(data&&typeof data==='object')return typeof data.report==='string'?data.report:typeof data.summary==='string'?data.summary:source;}catch(_){}
    // Some providers return a JSON envelope with unescaped quotation marks inside
    // report. Recover its display text only; never use this to approve execution.
    if(clean.startsWith('{')) {
      const field=/"(?:report|summary)"\s*:\s*"/.exec(clean);
      if(field) {
        const start=field.index+field[0].length;
        const tail=clean.slice(start);
        const end=/"\s*,\s*"(?:tasks|done|risk|evidence)"\s*:/.exec(tail)||/"\s*}\s*$/.exec(tail);
        if(end)return tail.slice(0,end.index).replace(/\\(?:u[\da-fA-F]{4}|["\\/bfnrt])/g,token=>{try{return JSON.parse('"'+token+'"');}catch{return token;}});
      }
    }
    return plain;
  }
  function markdownInline(parent,text,depth=0) {
    if(depth>8){parent.append(document.createTextNode(text));return;}
    const pattern=/(`+)([^`\n]+)\1|\*\*([^*\n]+)\*\*|\*([^*\n]+)\*|\[([^\]\n]+)\]\(([^\s)]+)\)/g;
    let last=0;
    for(const match of text.matchAll(pattern)) {
      parent.append(document.createTextNode(text.slice(last,match.index)));
      if(match[2])parent.append(node('code',match[2]));
      else if(match[3]||match[4]){const tag=node(match[3]?'strong':'em');markdownInline(tag,match[3]||match[4],depth+1);parent.append(tag);}
      else {
        let safe=false;try{safe=['http:','https:','mailto:'].includes(new URL(match[6],location.href).protocol);}catch{}
        if(safe){const link=node('a',match[5]);link.href=match[6];link.target='_blank';link.rel='noopener noreferrer';parent.append(link);}
        else parent.append(document.createTextNode(match[5]));
      }
      last=match.index+match[0].length;
    }
    parent.append(document.createTextNode(text.slice(last)));
  }
  function reconcileMarkdown(parent,fresh) {
    const incoming=Array.from(fresh.childNodes);
    for(let i=0;i<incoming.length;i++) {
      const next=incoming[i],old=parent.childNodes[i];
      if(!old){parent.append(next);continue;}
      if(old.nodeType!==next.nodeType||old.nodeName!==next.nodeName){parent.replaceChild(next,old);continue;}
      if(old.nodeType===Node.TEXT_NODE){if(next.data.startsWith(old.data))old.appendData(next.data.slice(old.data.length));else if(old.data!==next.data)old.data=next.data;}
      else {
        for(const attr of Array.from(old.attributes))if(!next.hasAttribute(attr.name))old.removeAttribute(attr.name);
        for(const attr of next.attributes)if(old.getAttribute(attr.name)!==attr.value)old.setAttribute(attr.name,attr.value);
        reconcileMarkdown(old,next);
      }
    }
    while(parent.childNodes.length>incoming.length)parent.lastChild.remove();
  }
  function markdownCells(line) {
    const cells=[];let cell='',ticks=0;
    for(let i=0;i<line.length;i++){
      if(line[i]==='\\'&&line[i+1]==='|'){cell+='|';i++;continue;}
      if(line[i]==='`'){let end=i+1;while(line[end]==='`')end++;const count=end-i;if(!ticks)ticks=count;else if(ticks===count)ticks=0;cell+=line.slice(i,end);i=end-1;continue;}
      if(line[i]==='|'&&!ticks){cells.push(cell.trim());cell='';}else cell+=line[i];
    }
    cells.push(cell.trim());if(line.trimStart().startsWith('|'))cells.shift();if(cells.at(-1)===''&&line.trimEnd().endsWith('|'))cells.pop();return cells;
  }
  function renderMarkdown(target,source) {
    source=String(source??'');if(target._markdownSource===source)return;
    target._markdownSource=source;target.classList.add('chat-markdown');
    const fragment=document.createDocumentFragment(),lines=source.replace(/\r\n/g,'\n').split('\n');
    let paragraph=[],list=null,quote=null;
    function flush(){if(paragraph.length){const p=node('p');markdownInline(p,paragraph.join('\n'));fragment.append(p);paragraph=[];}list=null;quote=null;}
    for(let i=0;i<lines.length;i++) {
      const line=lines[i],fence=/^\s*(`{3,}|~{3,})([^\s]*)\s*$/.exec(line);
      if(fence){flush();const code=[],marker=fence[1];for(i++;i<lines.length&&!lines[i].trim().startsWith(marker);i++)code.push(lines[i]);const pre=node('pre');pre.append(node('code',code.join('\n')));fragment.append(pre);continue;}
      if(!line.trim()){flush();continue;}
      const headers=line.includes('|')?markdownCells(line):[],separators=i+1<lines.length?markdownCells(lines[i+1]):[];
      if(headers.length&&headers.length===separators.length&&separators.every(x=>/^:?-{3,}:?$/.test(x))){
        flush();const wrap=node('div','','markdown-table-scroll'),table=node('table'),head=node('thead'),body=node('tbody'),header=node('tr');
        wrap.tabIndex=0;wrap.setAttribute('role','region');wrap.setAttribute('aria-label','表格，可横向滚动');
        const align=separators.map(x=>x.startsWith(':')&&x.endsWith(':')?'center':x.endsWith(':')?'right':'left');
        headers.forEach((text,index)=>{const cell=node('th','','markdown-align-'+align[index]);cell.scope='col';markdownInline(cell,text);header.append(cell);});head.append(header);table.append(head,body);wrap.append(table);fragment.append(wrap);i++;
        while(i+1<lines.length&&lines[i+1].trim()&&lines[i+1].includes('|')){
          const values=markdownCells(lines[++i]),row=node('tr');
          headers.forEach((_,index)=>{const cell=node('td','','markdown-align-'+align[index]);markdownInline(cell,values[index]||'');row.append(cell);});body.append(row);
        }
        continue;
      }
      const heading=/^(#{1,6})\s+(.+)$/.exec(line);
      if(heading){flush();const h=node('h'+Math.min(6,heading[1].length+1));markdownInline(h,heading[2]);fragment.append(h);continue;}
      if(/^\s*(?:---+|\*\*\*+)\s*$/.test(line)){flush();fragment.append(node('hr'));continue;}
      const item=/^\s*(?:([-+*])|(\d+)[.)])\s+(.+)$/.exec(line);
      if(item){if(paragraph.length)flush();quote=null;const kind=item[2]?'ol':'ul';if(!list||list.tagName.toLowerCase()!==kind){list=node(kind);if(item[2])list.start=Number(item[2]);fragment.append(list);}const li=node('li');markdownInline(li,item[3]);list.append(li);continue;}
      if(/^>\s?/.test(line)){if(paragraph.length)flush();list=null;if(!quote){quote=node('blockquote');fragment.append(quote);}const p=node('p');markdownInline(p,line.replace(/^>\s?/,''));quote.append(p);continue;}
      list=null;quote=null;paragraph.push(line);
    }
    flush();reconcileMarkdown(target,fragment);
  }
  Object.assign(window.HubChatFormat ||= {},{readableChat,renderMarkdown});
  async function copyChat(text,control) {
    control._copyLabel ||= control.getAttribute('aria-label')||'复制回复';control._copyTitle ||= control.title||control._copyLabel;
    try {
      if(navigator.clipboard?.writeText)await navigator.clipboard.writeText(text);
      else {const box=node('textarea','','chat-copy-buffer');box.value=text;document.body.append(box);box.select();const copied=document.execCommand('copy');box.remove();if(!copied)throw Error('无法复制');control.focus();}
      control.setAttribute('aria-label','已复制');control.title='已复制';setTimeout(()=>{control.setAttribute('aria-label',control._copyLabel);control.title=control._copyTitle;},1500);
    }catch(_){notice('复制失败，请选中文字复制。');}
  }
  function agentName(id,v=view) {
    if(id==='user')return '用户';
    return v?.rawSnapshot?.integrations?.agents?.find(a=>a.id===id)?.name || v?.agents?.find(a=>a.id===id)?.name || v?.rawSnapshot?.agents?.find(a=>a.id===id)?.profile?.name || (/^agent-[a-z0-9]+$/i.test(id||'')?'Agent':id||'待选择');
  }
  function participantLabel(label) {
    return String(label||'').replace(/\b(?:agent-[a-z0-9]+|deepseek-\d+|sol-\d+|flash-\d+|argon|astra|opus)\b/gi,id=>agentName(id));
  }
  function chatMessage(sender,body,status,timestamp,result=null) {
    const row=node('article','','chat-message');row.tabIndex=0;row.dataset.role=/^(用户|user\b)/i.test(sender||'')?'user':'assistant';
    const content=readableChat(body),message=node('div','','chat-message-body');if(row.dataset.role==='user')message.textContent=String(body??'');else renderMarkdown(message,content);row.append(message);
    if(result&&readableChat(result)!==content){const reply=node('div','','chat-message-body chat-message-result');renderMarkdown(reply,readableChat(result));row.append(reply);}
    const footer=node('footer','','chat-message-meta');footer.append(node('span',participantLabel(sender)||'消息'),node('span',statusLabel(status)),chatTime(timestamp));
    const copy=node('button','⧉','chat-copy');copy.type='button';copy.title='复制回复';copy.setAttribute('aria-label','复制回复');copy.addEventListener('click',()=>copyChat([...row.querySelectorAll('.chat-message-body')].map(x=>x._markdownSource??x.textContent).join('\n\n'),copy));footer.append(copy);row.append(footer);return row;
  }
  const chatPositions = new Map();
  const chatScrollBound = new WeakSet();
  const chatListSizes = new Map();
  const chatIds = new Set(['discussionHistory','messages']);
  function chatKey(id) { return (client.getSelectedProjectId() || view.rawSnapshot?.selected_project || '')+':'+id; }
  function chatScroller(id) { return id==='discussionHistory' ? $('managerReadingArea') : $(id); }
  function captureChat(id) {
    if(!chatIds.has(id))return null;
    const scroller=chatScroller(id), key=chatKey(id);if(!scroller)return null;
    if(!chatScrollBound.has(scroller)) {
      chatScrollBound.add(scroller);
      scroller.addEventListener('scroll',()=>{
        if(!scroller.clientHeight)return;
        const key=chatKey(id),saved=chatPositions.get(key),height=scroller.scrollHeight;
        // Content growth is not a user decision to stop following.
        const resized=saved&&saved.height!==undefined&&saved.height!==height;
        chatPositions.set(key,{top:scroller.scrollTop,follow:resized?saved.follow:height-scroller.clientHeight-scroller.scrollTop<=24,height});
      },{passive:true});
      let pending=false;
      const followLayout=()=>{if(pending)return;pending=true;setTimeout(()=>{
        pending=false;const key=chatKey(id),saved=chatPositions.get(key);
        if(!saved||!scroller.clientHeight)return;
        const selection=window.getSelection(),reading=selection&&!selection.isCollapsed&&scroller.contains(selection.anchorNode);
        if(reading)saved.follow=false;
        if(saved.follow)scroller.scrollTop=scroller.scrollHeight;
        chatPositions.set(key,{...saved,top:scroller.scrollTop,height:scroller.scrollHeight});
      });};
      const resize=new ResizeObserver(followLayout);
      const observe=()=>{resize.disconnect();resize.observe(scroller);for(const child of scroller.children)resize.observe(child);followLayout();};
      new MutationObserver(observe).observe(scroller,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['style','class','open','hidden']});
      scroller.addEventListener('load',followLayout,true);observe();
    }
    const previous=chatPositions.get(key);
    const selection=window.getSelection(),reading=selection&&!selection.isCollapsed&&scroller.contains(selection.anchorNode);
    const moved=previous&&previous.height===scroller.scrollHeight&&Math.abs(previous.top-scroller.scrollTop)>2;
    const state=scroller.clientHeight && previous ? {...previous,top:scroller.scrollTop,follow:reading?false:moved?scroller.scrollHeight-scroller.clientHeight-scroller.scrollTop<=24:previous.follow} : previous || {top:0,follow:true};
    chatPositions.set(key,state);return {scroller,key,...state,initial:!previous};
  }
  function restoreChat(state) {
    if(!state)return;
    setTimeout(()=>{
      const el=state.scroller;if(!el.clientHeight)return;
      // Do not overrule scrolling performed by the user after this render started.
      if(Math.abs(el.scrollTop-state.top)>2 && !state.initial)return;
      const selection=window.getSelection(),reading=selection&&!selection.isCollapsed&&el.contains(selection.anchorNode);
      if(reading)state.follow=false;
      el.scrollTop=state.follow?el.scrollHeight:state.top;
      chatPositions.set(state.key,{top:el.scrollTop,follow:state.follow,height:el.scrollHeight});
    });
  }
  for(const id of ['chatTabManagerRadio','chatTabGroupRadio','viewModeChatRadio']) $(id)?.addEventListener('change',()=>{
    for(const chat of chatIds){const saved=chatPositions.get(chatKey(chat));restoreChat({scroller:chatScroller(chat),key:chatKey(chat),...(saved||{top:0,follow:true}),initial:true});}
  });
  const listPages = new Map();
  const pagedLists = new Set(['tasks','messages','discussionHistory','audit','wakeLog','reportLog','workflowList']);
  const rowSignatures = new WeakMap();
  const listProjects = new WeakMap();
  // Separate scope prevents a history button retaining pool/desired and all old renders.
  function historyMoreButton(id, key, count, items, shown) {
    return button('显示更多历史（已显示 ' + shown + ' / ' + items.length + '）', () => {
      listPages.set(key, count + 30); list(id, items);
    });
  }
  function list(id, items) {
    const container = $(id);
    if (!container) return;
    const chatState=captureChat(id);
    const openKeys = new Set();
    const detailScrolls = new Map();
    const restoreScrolls = [];
    const existingDetails = container.querySelectorAll ? container.querySelectorAll('details') : [];
    for (const d of existingDetails) {
      if (d.open && d.dataset?.detailKey) {
        openKeys.add(d.dataset.detailKey);
        detailScrolls.set(d.dataset.detailKey,[...d.querySelectorAll('pre')].map(el => [el.scrollTop,el.scrollLeft]));
      }
    }
    let visible = items;
    if (pagedLists.has(id)) {
      const project = client.getSelectedProjectId() || view.rawSnapshot?.selected_project || '';
      const key = project + ':' + id;
      let count = listPages.get(key) || 30;
      if(chatState && !chatState.follow)count+=Math.max(0,items.length-(chatListSizes.get(key)||items.length));
      listPages.set(key,count);chatListSizes.set(key,items.length);
      visible = ['tasks','discussionHistory','messages'].includes(id) ? items.slice(-count) : items.slice(0,count);
      if (id === 'tasks') {
        const shown = new Set(visible);
        visible = [...items.filter(row => row.dataset?.live === 'true' && !shown.has(row)), ...visible];
      }
      if (items.length > count) {
        const more = historyMoreButton(id, key, count, items, visible.length);
        if (['tasks','discussionHistory','messages'].includes(id)) visible = [more, ...visible];
        else visible = [...visible, more];
      }
    }
    const projectKey = client.getSelectedProjectId() || view.rawSnapshot?.selected_project || '';
    const sameProject = listProjects.get(container) === projectKey;
    const scrolls = [];
    if (sameProject) {
      for (let el = container; el; el = el.parentElement) scrolls.push([el,el.scrollTop,el.scrollLeft]);
    }
    const pool = new Map();
    if (sameProject) for (const el of container.children) {
      const signature = rowSignatures.get(el);
      if (signature) { if (!pool.has(signature)) pool.set(signature,[]); pool.get(signature).push(el); }
    }
    const desired = visible.map(el => {
      const signature = el.outerHTML;
      const retained = el.tagName === 'BUTTON' ? null : pool.get(signature)?.shift();
      if (retained) return retained;
      rowSignatures.set(el,signature);
      if (sameProject) for (const d of el.querySelectorAll('details')) {
        if (openKeys.has(d.dataset.detailKey)) {
          d.ensureContent?.(); d.open=true;
          [...d.querySelectorAll('pre')].forEach((el,i) => { const saved=detailScrolls.get(d.dataset.detailKey)?.[i]; if(saved)restoreScrolls.push([el,...saved]); });
        }
      }
      return el;
    });
    // Keep unchanged nodes alive: lazy content, selection, focus and nested scroll survive.
    const keep = new Set(desired);
    for (const el of [...container.children]) if (!keep.has(el)) el.remove();
    desired.forEach((el,index) => { if (container.children[index] !== el) container.insertBefore(el,container.children[index] || null); });
    listProjects.set(container,projectKey);
    for (const [el,top,left] of [...restoreScrolls,...scrolls]) { if (el.scrollTop !== top) el.scrollTop=top; if (el.scrollLeft !== left) el.scrollLeft=left; }
    restoreChat(chatState);
  }

  function options(id, entries) {
    const select = $(id), before = select.value;
    list(id, entries.map(([key, label]) => { const o = node('option', label); o.value = key; return o; }));
    select.value = entries.some(([key]) => key === before) ? before : (entries[0]?.[0] || '');
  }
  async function action(name, args = {}) {
    ready(); const result = await client.postAction(name, args); await store.refresh(true); return result;
  }
  async function chooseProject(id) {
    if(id!==client.getSelectedProjectId()){stashDrafts();for(const field of draftFields)if($(field))$(field).value='';restoredDraftProjects.delete('hub.draft.'+id);}
    switching = true; addCls($('connection'), 'is-loading'); text('connection', '切换项目 · 数据过期');
    try { await store.switchProject(id); if(store.connectionStatus==='connected')await client.postAction('project_select',{project_id:id}).catch(()=>{}); } finally { switching = false; rmCls($('connection'), 'is-loading'); }
  }
  async function login(id, suppliedToken = null) {
    text('loginError', '');
    store.stopPolling();
    const submit = $('btnLoginSubmit');
    if(submit)submit.textContent = '正在连接…';
    addCls(submit, 'is-loading');
    addCls($('loginEndpoint'), 'is-loading');
    try {
      const token = parseToken(suppliedToken ?? value(id));
      client.setUserToken(token);
      client.setSelectedProjectId(client.getSelectedProjectId());
      let timeout;
      try {
        await Promise.race([store.refresh(true), new Promise((_, reject) => {
          timeout = setTimeout(() => reject(new Error('连接超时，请确认本机 Hub 服务正在运行。')), 12000);
        })]);
      } finally { clearTimeout(timeout); }
      if (store.connectionStatus !== 'connected') {
        const reason = store.lastError || '连接失败';
        if (/403|401|unauthorized|invalid token/i.test(reason)) {
          throw new Error('凭证与当前 ' + endpoint + ' 数据目录不匹配。请粘贴对应 credentials.json 中的 user 值或整段 JSON；不要使用其他实例的凭证。' + (credentialFile ? ' 此实例文件：' + credentialFile : ' 请核对启动时 --data 指定的数据目录。'));
        }
        throw new Error('无法连接 ' + endpoint + '，请确认服务正在运行后重试。');
      }
      const available=store.rawState?.projects||[];
      if(available.length) {
        const current=client.getSelectedProjectId();
        const target=available.some(p=>p.id===current)?current:(store.rawState?.last_opened_project||available[0].id);
        if(target!==current)await store.switchProject(target);
      }
      if($(id))$(id).value = '';
      text('loginError', ''); text('notice', '');
      if($('login'))$('login').hidden = true; $('workspace').hidden = false;
      store.startPolling(); await pollHealth(true);
    } catch (error) {
      client.clearUserToken();
      client.setSelectedProjectId(client.getSelectedProjectId());
      text('loginError', error.message); notice(error.message);
      throw error;
    } finally { if(submit)submit.textContent = '连接工作台'; rmCls(submit, 'is-loading'); rmCls($('loginEndpoint'), 'is-loading'); }
  }
  async function pollHealth(force = false) {
    if (healthBusy || (!force && Date.now() - healthTime < 10000)) return;
    healthBusy = true; healthTime = Date.now();
    addCls($('health'), 'is-loading');
    const seq = client.getCurrentPollSeq();
    try {
      const h = await client.getHealth();
      if (seq === client.getCurrentPollSeq()) text('health', h.ok ? '运行中 · 心跳正常' : '心跳过期');
    } catch (_) { if (seq === client.getCurrentPollSeq()) text('health', '连接中断/心跳数据过期'); }
    finally { healthBusy = false; rmCls($('health'), 'is-loading'); }
  }
  window.HubDesktop = { client, store, $, node, text, value, checked, number, notice, bind, button, list, options, longText, record, chatTime, dump, action, ready, statusLabel, chooseProject, chatMessage, readableChat, copyChat, agentName, participantLabel,
    get view() { return view; }, get switching() { return switching; },
    render(fn) { renderers.push(fn); fn(view); }
  };
  bind('loginForm', 'submit', () => login('token'), false);
  bind('modalLoginForm', 'submit', () => login('modalToken'), false);
  // Only the owned desktop Hub advertises this same-origin, memory-only bridge.
  let desktopSession = metadata('hub-desktop-session');
  if (desktopSession) {
    // Desktop owns authentication; never ask users to copy internal credentials.
    $('login')?.remove();
    $('modalLoginForm')?.closest('.config-section-card')?.remove();
    $('workspace').hidden=false;
    void (async () => {
      let failures=0;
      while(!client.hasToken()) {
        try {
          const response=await fetch('/desktop-session',{method:'POST',headers:{'Content-Type':'application/json','X-Desktop-Session':desktopSession},body:'{}',signal:AbortSignal.timeout(10000)});
          if(response.status===403) {
            // A backend restart changes the nonce. Renew it without losing drafts.
            const html=await fetch('/',{cache:'no-store',signal:AbortSignal.timeout(10000)}).then(r=>r.text());
            const fresh=new DOMParser().parseFromString(html,'text/html').querySelector('meta[name="hub-desktop-session"]')?.content;
            if(fresh){desktopSession=fresh;document.querySelector('meta[name="hub-desktop-session"]').content=fresh;}
          }
          if(!response.ok)throw new Error('HTTP '+response.status);
          const data=await response.json();
          await login('token',data.token);
          break;
        } catch(error) {
          client.clearUserToken();
          text('startupLabel','正在连接本地服务，稍后自动重试…');
          await new Promise(resolve=>setTimeout(resolve,Math.min(3000,300*(++failures))));
        }
      }
    })();
  }

  bind('hubProjectSelect', 'change', () => chooseProject(value('hubProjectSelect')));
  for (const [id, target] of [['btnViewChat','viewModeChatRadio'], ['btnViewStatus','viewModeStatusRadio'], ['tabManagerChat','chatTabManagerRadio'], ['tabGroupChat','chatTabGroupRadio'], ['tabProjectStatus','chatTabStatusRadio']]) {
    $(id).addEventListener('click', event => {
      event.preventDefault();
      const radio=$(target), entering=!radio.checked;if(!entering)return;radio.checked=true;
      if(entering && id==='tabGroupChat')chatPositions.set(chatKey('messages'),{top:0,follow:true});
      radio.dispatchEvent(new Event('change',{bubbles:true}));
    });
  }
  let selectedChatTab=null,tabMotion=null;
  function syncChatTabs(){
    const oldTab=selectedChatTab;
    for(const [tab,radio] of [['tabManagerChat','chatTabManagerRadio'],['tabGroupChat','chatTabGroupRadio'],['tabProjectStatus','chatTabStatusRadio']]){$(tab).setAttribute('aria-selected',String($(radio).checked));if($(radio).checked)selectedChatTab=$(tab);}
    if(!selectedChatTab)return;
    const nav=selectedChatTab.parentElement;
    let indicator=nav.querySelector('.chat-tab-indicator');
    if(!indicator){indicator=node('span','','chat-tab-indicator');indicator.setAttribute('aria-hidden','true');nav.prepend(indicator);}
    const next=selectedChatTab.getBoundingClientRect(),bounds=nav.getBoundingClientRect();
    const geometry=[next.left-bounds.left,next.top-bounds.top,next.width,next.height].map(n=>n.toFixed(2)).join(',');
    if(oldTab===selectedChatTab&&indicator.dataset.geometry===geometry)return;
    const previous=indicator.dataset.geometry?indicator.getBoundingClientRect():null;
    indicator.dataset.geometry=geometry;
    tabMotion?.cancel();Object.assign(indicator.style,{left:(next.left-bounds.left)+'px',top:(next.top-bounds.top)+'px',width:next.width+'px',height:next.height+'px'});
    if(previous&&previous.width&&next.width&&!matchMedia('(prefers-reduced-motion: reduce)').matches&&(previous.left!==next.left||previous.width!==next.width))tabMotion=indicator.animate([{transform:`translate(${previous.left-next.left}px,${previous.top-next.top}px) scaleX(${previous.width/next.width})`},{transform:'none'}],{duration:260,easing:'cubic-bezier(.22,.8,.25,1)'});
  }
  const tabResize=new ResizeObserver(()=>syncChatTabs());
  for(const id of ['tabManagerChat','tabGroupChat','tabProjectStatus'])tabResize.observe($(id));
  for(const radio of ['chatTabManagerRadio','chatTabGroupRadio','chatTabStatusRadio'])$(radio).addEventListener('change',syncChatTabs);
  for(const tab of ['tabManagerChat','tabGroupChat','tabProjectStatus'])$(tab).addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();$(tab).click();}});
  syncChatTabs();
  for (const [id, open] of [['btnOpenConfig',true], ['btnCloseConfig',false]]) bind(id, 'click', () => { $('configModalToggle').checked = open; }, false);
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && $('desktopContextMenu').hidden) $('configModalToggle').checked = false; });
  function showQuotaQuick(open){$('quotaQuickPanel').hidden=!open;$('toggleQuotaQuick').setAttribute('aria-expanded',String(open));}
  bind('toggleQuotaQuick','click',()=>showQuotaQuick($('quotaQuickPanel').hidden),false);
  bind('closeQuotaQuick','click',()=>showQuotaQuick(false),false);
  document.addEventListener('pointerdown',event=>{if(!$('quotaQuickPanel').hidden&&!$('quotaQuickPanel').contains(event.target)&&!$('toggleQuotaQuick').contains(event.target))showQuotaQuick(false);});
  for(const id of ['btnViewChat','btnViewStatus','btnOpenConfig'])$(id).addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();$(id).click();}});
  document.addEventListener('keydown',event=>{if(event.key==='Escape')showQuotaQuick(false);});
  const themeChips = [
    { id: 'themeModeAuto', mode: 'auto' },
    { id: 'themeModeLight', mode: 'light' },
    { id: 'themeModeDark', mode: 'dark' }
  ];
  function updateThemeActive(mode) {
    for (const item of themeChips) {
      const el = $(item.id);
      if (el) {
        if (item.mode === mode) addCls(el, 'active');
        else rmCls(el, 'active');
      }
    }
  }
  for (const item of themeChips) {
    const el = $(item.id);
    if (el) {
      el.addEventListener('click', () => {
        if (item.mode === 'auto') {
          delete document.documentElement.dataset.theme;
        } else {
          document.documentElement.dataset.theme = item.mode;
        }
        updateThemeActive(item.mode);
      });
    }
  }
  for (const id of ['message','workflowRequirement','discussionReply']) {
    const update = () => text(id + 'Count', value(id).length.toLocaleString() + ' / 20,000 字符');
    $(id).addEventListener('input', update); update();
  }
  const ids = ALL_AGENT_IDS;
  for (const id of ['recipient','assignee','quotaAgent','conversation']) options(id, [ ...(id === 'recipient' ? [['*','广播给全部 Agent']] : id === 'conversation' ? [['*','全部动态'],['user','发给用户的回复']] : []), ...ids.map(a => [a,a]) ]);
  let messageAttempt = null;
  const composerForm=$('messageForm'),composerShell=node('div','','group-composer-motion');
  composerForm.before(composerShell);composerShell.append(composerForm);
  let composerMotion=null,composerOpen=!composerForm.hidden;
  $('toggleGroupComposer').addEventListener('click',()=>{
    const form=composerForm,toggle=$('toggleGroupComposer'),shell=composerShell;
    const feed=$('panelGroupChat').querySelector('.messages-feed-scroll'),follow=feed&&feed.scrollHeight-feed.scrollTop-feed.clientHeight<36;
    const from=shell.getBoundingClientRect().height,opacity=Number(getComputedStyle(shell).opacity);
    composerMotion?.cancel();composerOpen=!composerOpen;
    toggle.setAttribute('aria-expanded',String(composerOpen));toggle.setAttribute('aria-label',composerOpen?'收起群聊消息输入框':'展开群聊消息输入框');toggle.title=composerOpen?'收起输入框':'发送消息给 Agent';toggle.querySelector('[data-compose-icon=write]').hidden=composerOpen;toggle.querySelector('[data-compose-icon=collapse]').hidden=!composerOpen;
    form.hidden=false;form.inert=!composerOpen;shell.style.height='auto';
    const target=composerOpen?shell.getBoundingClientRect().height:0;
    const finish=()=>{if(follow)feed.scrollTop=feed.scrollHeight;form.hidden=!composerOpen;shell.style.height='';shell.style.overflow='';shell.style.opacity='';if(composerOpen)$('message').focus({preventScroll:true});else if(form.contains(document.activeElement))toggle.focus({preventScroll:true});};
    if(matchMedia('(prefers-reduced-motion: reduce)').matches||from===target){finish();return;}
    shell.style.overflow='hidden';
    const motion=shell.animate([{height:from+'px',opacity},{height:target+'px',opacity:composerOpen?1:0}],{duration:240,easing:'cubic-bezier(.22,.8,.25,1)',fill:'both'});
    composerMotion=motion;
    motion.onfinish=()=>{if(composerMotion!==motion)return;finish();motion.cancel();composerMotion=null;};
  });
  bind('messageForm', 'submit', async () => {
    const body = value('message');
    const recipient = value('recipient'), mode = value('mode');
    const signature = JSON.stringify([client.getSelectedProjectId(), recipient, mode, body]);
    if (messageAttempt?.signature !== signature) messageAttempt = { signature, key: client.generateRequestKey() };
    const attempt = messageAttempt;
    await store.sendMessage({ recipient, body, mode, requestKey: attempt.key });
    if (messageAttempt === attempt && signature === JSON.stringify([client.getSelectedProjectId(), value('recipient'), value('mode'), value('message')])) {
      $('message').value = ''; text('messageCount','0 / 20,000 字符'); messageAttempt = null;
    }
  });
  bind('conversation','change', () => renderActivity(view), false);
  bind('createFirstProject','click',()=>$('hubProjectCreateBtn').click(),false);
  bind('taskForm','submit', async () => { await store.assignTask({ agent:value('assignee'), title:value('taskTitle') }); $('taskTitle').value = ''; });
  bind('quotaForm','submit', () => store.setManualQuota({agent:value('quotaAgent'), remaining:value('remaining'), resetsAt:value('resets')}));
  bind('refreshQuota','click', () => store.refreshOpenAIQuota());
  bind('refreshAntigravity','click', () => store.refreshAntigravityQuota());
  bind('haltAll','click', () => store.haltAgent('*'));
  function renderDisasterBanner(v,s) {
    // Quota failures belong in manager coordination and per-agent state.
    const banner=$('quotaDisasterBanner');if(banner){banner.hidden=true;banner.replaceChildren();}
  }
  function renderActivity(v) {
    const filter = value('conversation');
    const stream = [...v.agentStream.timeline];
    const manager = v.managerStream.manager;
    for (const m of v.rawSnapshot?.messages || []) {
      if (m.sender === 'user' && m.recipient !== manager && !stream.some(row => row.id === m.id)) stream.push({id:m.id,title:m.sender + ' → ' + m.recipient,body:m.body,result:m.result,status:m.status,timestamp:m.created,prompt:m.prompt});
    }
    stream.sort((a,b) => (a.timestamp || 0) - (b.timestamp || 0));
    const rows = stream.filter(row => {
      if (filter === '*') return true;
      const m = v.rawSnapshot?.messages?.find(m => m.id === row.id);
      return m && (m.recipient === filter || (filter !== 'user' && m.sender === filter));
    });
    list('messages', rows.map(row => {
      const d = chatMessage(row.title, row.body, row.status, row.timestamp, row.result);
      if (row.prompt) {
        const drawer = createActualInputDrawer('msg_' + row.id, row.prompt, '查看实际模型输入 (Actual Input)');
        if (drawer) {
          const inspect=node('button','{ }','chat-copy');inspect.type='button';inspect.title='查看实际模型输入';inspect.setAttribute('aria-label','查看实际模型输入');
          inspect.addEventListener('click',()=>{let dialog=$('chatSourceDialog');if(!dialog){dialog=node('dialog','','chat-source-dialog');dialog.id='chatSourceDialog';const close=button('×',()=>dialog.close());close.className='dialog-close';close.title='关闭';close.setAttribute('aria-label','关闭');const source=node('pre','','chat-source-text');source.id='chatSourceText';dialog.append(close,source);document.body.append(dialog);dialog.addEventListener('click',e=>{if(e.target===dialog)dialog.close();});}text('chatSourceText',window.HubDesktop.view.agentStream.timeline.find(m=>m.id===row.id)?.prompt||row.prompt);dialog.showModal();});d.lastElementChild.append(inspect);
        }
      }
      if (row.meta) d.lastElementChild.append(node('span',row.meta)); return d;
    }));
  }
  let rosterOptionsSignature='';
  function render(v) {
    const rosterOptions=v.agents.map(a=>[a.id,a.name]);const nextSignature=JSON.stringify(rosterOptions);
    if(v.rawSnapshot?.integrations&&nextSignature!==rosterOptionsSignature){rosterOptionsSignature=nextSignature;for(const id of ['recipient','assignee','quotaAgent','conversation']){const old=value(id);options(id,[...(id==='recipient'?[['*','广播给全部 Agent']]:id==='conversation'?[['*','全部动态'],['user','发给用户的回复']]:[]),...rosterOptions]);$(id).value=old;if(!$(id).value)$(id).selectedIndex=0;}}
    text('connection', v.connection.message + (v.connection.lastUpdated ? ' · ' + new Date(v.connection.lastUpdated).toLocaleTimeString() : ''));
    if (v.connection.status !== 'connected' || v.connection.isStale) addCls($('connection'), 'is-loading');
    else rmCls($('connection'), 'is-loading');
    const s = v.rawSnapshot;
    if (!s) return;
    const empty=Array.isArray(s.projects)&&s.projects.length===0;
    document.querySelector('.workbench-content-surface').classList.toggle('no-project',empty);
    $('emptyWorkspace').hidden=!empty;
    for (const id of ['openCodexIntegration','openAntigravityIntegration','codexPanel','antigravityPanel','refreshOpenAIHeader','refreshAntigravityHeader','switchManagerDeepseekBtn']) if ($(id)) $(id).hidden=true;
    renderDisasterBanner(v, s);
    for (const id of ['dsRuns','dsBudget','dsRequests','workflowMax']) { const field=$(id);if(field?.closest) {const label=field.closest('label');if(label)label.hidden=true;} }

    options('hubProjectSelect', [['','全部项目与旧记录'], ...(s.projects || []).map(p => [p.id,p.name])]);
    $('hubProjectSelect').value = client.getSelectedProjectId() || s.selected_project || '';
    list('projectList',(s.projects||[]).map(project=>{
      const item=button(project.name,()=>chooseProject(project.id));item.className='project-list-item';item.title=project.name;item.dataset.projectId=project.id;
      if(project.id=== (client.getSelectedProjectId()||s.selected_project)){item.classList.add('is-selected');item.setAttribute('aria-current','page');}
      const row=node('div','','project-list-row');if(item.classList.contains('is-selected'))row.classList.add('is-selected');const menu=node('div','','project-row-menu');const toggle=node('button','⋯','project-menu-toggle');toggle.type='button';toggle.setAttribute('aria-haspopup','menu');toggle.setAttribute('aria-expanded','false');toggle.title='项目操作';toggle.setAttribute('aria-label','项目操作');const controls=node('div','','project-menu-list');controls.setAttribute('popover','auto');controls.id='project-menu-'+project.id;controls.setAttribute('role','menu');toggle.setAttribute('aria-controls',controls.id);controls.addEventListener('toggle',()=>toggle.setAttribute('aria-expanded',String(controls.matches(':popover-open'))));toggle.addEventListener('click',event=>{event.preventDefault();const opening=!controls.matches(':popover-open');if(opening){const rect=toggle.getBoundingClientRect();controls.showPopover();controls.style.left=Math.max(8,Math.min(rect.right-170,innerWidth-180))+'px';controls.style.top=Math.max(8,Math.min(rect.bottom+4,innerHeight-controls.offsetHeight-8))+'px';}else controls.hidePopover();});for(const [label,fn,danger] of [['重命名',()=>window.HubDesktop.renameProject(project)],['打开所在目录',()=>action('project_open_directory',{project_id:project.id})],['项目设置',()=>window.HubDesktop.editProject(project)],['删除项目',()=>window.HubDesktop.deleteProject(project),true]]){const control=button(label,()=>{controls.hidePopover();return fn();});if(danger)control.className='project-menu-danger';control.setAttribute('role','menuitem');control.prepend(projectMenuIcon(label));controls.append(control);}controls.addEventListener('keydown',event=>{const buttons=[...controls.querySelectorAll('button')];const index=buttons.indexOf(document.activeElement);if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();buttons[event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowUp'?-1:1)+buttons.length)%buttons.length]?.focus();}if(event.key==='Escape'){controls.hidePopover();toggle.focus();}});toggle.addEventListener('keydown',event=>{if(event.key==='ArrowDown'){event.preventDefault();if(!controls.matches(':popover-open'))toggle.click();controls.querySelector('button')?.focus();}});menu.append(toggle,controls);row.append(item,menu);return row;
    }));
    text('projectCountTag', (s.projects || []).length + ' 项目');
    const providers = [['codex','Codex'],['antigravity','Antigravity'],['deepseek','DeepSeek']].filter(([key]) => s[key]?.config?.enabled).map(([,label]) => label);
    const productionLabel = providers.length ? '真实执行 · ' + providers.join(' / ') + (s.deepseek?.config?.engine === 'harness' ? ' Harness · ACP' : '') : '待接入真实模型';
    text('runtimeMode', productionLabel);
    text('providerIntegrationStatus', productionLabel + ' · 经理 '+agentName(v.managerStream?.manager,v));
    if (!providers.length) addCls($('providerIntegrationStatus'), 'is-loading');
    else rmCls($('providerIntegrationStatus'), 'is-loading');
    $('providerIntegrationBar').className = 'provider-integration-bar' + (providers.length ? '' : ' needs-integration');
    text('overall', s.project?.progress==null?'—':s.project.progress+'%'); for(const id of ['projectBar','overallBar']){$(id).value=s.project?.progress??0;$(id).setAttribute('aria-valuetext',s.project?.progress==null?'等待经理汇报':s.project.progress+'%');}
    window.HubChatFormat.renderMarkdown($('projectNote'),s.project?.note || '暂无项目说明');$('projectNote').title=s.project?.by?'由 '+s.project.by+' 汇报'+(s.project.updated?' · '+new Date(s.project.updated*1000).toLocaleString():''):'';
    text('managerTag', '经理：' + agentName(v.managerStream.manager,v));
    const selected=(s.projects||[]).find(p=>p.id===(client.getSelectedProjectId()||s.selected_project));
    $('statusProjectName').toggleAttribute('data-user-content',!!selected?.name);text('statusProjectName',selected?.name||'当前项目');text('statusProjectProgress',s.project?.progress==null?'—':s.project.progress+'%');
    text('statusProgressUpdated',s.project?.updated?'经理汇报于 '+new Date(s.project.updated*1000).toLocaleString('zh-CN',{hour12:false}):'等待经理汇报');
    const state=v.managerStream?.workflow?.status||v.managerStream?.planning?.state;
    text('statusProjectStage',({active:'执行中',completed:'已完成',paused:'已暂停',stopped:'已停止',blocked:'等待处理',needs_attention:'需要关注',thinking:'讨论中',awaiting_approval:'等待确认',executing:'执行中',draft:'需求讨论',ready:'计划已就绪'})[state]||state||'等待安排');
    text('statusBusyAgents',v.agents.filter(a=>(s.agents||[]).find(x=>x.id===a.id)?.status==='busy').length);
    text('statusAgentCount',v.agents.length);text('statusQueuedMessages',(s.messages||[]).filter(m=>m.status==='pending'&&m.recipient!=='user').length);

    $('agents').classList.toggle('dynamic-agents',v.agents.length>9);$('agents').classList.toggle('mid-agents',v.agents.length>9&&v.agents.length<=16);$('agents').classList.toggle('few-agents',v.agents.length<=3);$('agents').classList.toggle('six-agents',v.agents.length>3&&v.agents.length<=6);$('agentsGrid').classList.toggle('multi-agent-overflow',v.agents.length>9);
    list('agents', v.agents.map(a => {
      const raw = (s.agents || []).find(r => r.id === a.id) || {};
      const card = node('article','','agent-box'); card.dataset.agent = a.id;card.classList.toggle('model-unavailable',!!a.modelUnavailable);card.classList.toggle('quota-exhausted',!!a.quotaExhausted);
      if(a.id===v.managerStream.manager){card.classList.add('is-project-manager');card.setAttribute('aria-label',a.name+' · 项目经理');}
      const header = node('header','','agent-box-header');
      const actual = a.modelUnavailable?'unavailable':a.quotaExhausted?'exhausted':raw.status || 'offline';
      const title = node('div','','agent-title-col');
      title.append(node('span',a.name,'agent-id-tag'),node('h3',a.model,'agent-model'),node('span',a.role,'agent-role'));
      const badge = node('span',(a.modelUnavailable?'模型不可用':a.quotaExhausted?'额度耗尽':actual) + (a.isStopped ? ' · 已停止锁' : ''),'status-badge status-' + actual);if(a.modelUnavailable)badge.title=a.modelUnavailable.detail;
      if (actual === 'busy' || actual === 'running') {
        const sp = node('span', '', 'loading-spinner');
        badge.prepend(sp);
      }
      header.append(title,badge); card.append(header);
      const connectionTest=s.integrations?.test_results?.[a.id];
      if(connectionTest){const old=connectionTest.stale_configuration||raw.profile&&(raw.profile.model!==connectionTest.model||raw.profile.connection_id!==connectionTest.connection_id||raw.profile.effort!==connectionTest.effort);const status=node('p',(old?'旧配置 · ':'')+(window.HubDesktop.testLabel?.(connectionTest)||connectionTest.status),'agent-test-status test-'+connectionTest.status);status.title=connectionTest.detail;card.append(status);}
      if(raw.profile){const platform=s.integrations?.connections.find(c=>c.id===raw.profile.connection_id);const roleLabel=title.querySelector('.agent-role');roleLabel.textContent=a.role+' · '+(platform?.name||raw.profile.connection_id);roleLabel.title=roleLabel.textContent+' · '+a.id;}
      const effortRow=node('label','','agent-effort-row');effortRow.append(node('span','档位'));
      const effortSelect=node('select');effortSelect.setAttribute('aria-label',a.id+' 推理档位');effortSelect.dataset.agent=a.id;
      const selectedEffort=raw.profile?.effort||s.deepseek?.efforts?.[a.id]||'high';effortRow.dataset.selectedEffort=selectedEffort;
      const link=s.integrations?.connections.find(c=>c.id===raw.profile?.connection_id);
      const effortOptions=link?(link.models?.find(m=>m.id===raw.profile?.model)?.efforts||link.effort_options).map(x=>[x,x]):[['off','关闭'],['low','低'],['high','高'],['max','最高']];
      for(const [key,label] of effortOptions){const option=node('option',label);option.value=key;option.selected=key===selectedEffort;effortSelect.append(option);}
      effortSelect.title='下一轮执行生效，不打断当前任务';
      effortSelect.addEventListener('change',async()=>{
        effortSelect.disabled=true;
        try{await action('agent_set_effort',{agent:a.id,effort:effortSelect.value});notice('档位已保存，下一轮生效；经理通知已排队','status');}
        catch(error){effortSelect.value=selectedEffort;notice(error.message);}
        finally{effortSelect.disabled=false;}
      });effortRow.append(effortSelect);card.append(effortRow);
      const task = node('div','','agent-task-block');
      const taskText = String(a.activeTasks[0]?.title || a.activeRuns[0]?.prompt || raw.active || '无');
      const taskDetails = node('details','','agent-task-details');
      taskDetails.dataset.detailKey = 'agent_task_' + a.id + '_' + (a.activeTasks[0]?.id || a.activeRuns[0]?.id || raw.active || 'idle');
      taskDetails.append(node('summary','当前任务：'+(taskText.length>60 ? taskText.slice(0,60)+'…' : taskText)));
      taskDetails.ensureContent = () => { if (!taskDetails.querySelector('pre')) taskDetails.append(node('pre',taskText,'agent-task-full')); };
      taskDetails.addEventListener('toggle',() => { if(taskDetails.open)taskDetails.ensureContent(); });
      task.append(taskDetails); card.append(task);
      const reasonText=a.stopReason || raw.blocked_reason || raw.waiting_reason || a.activeTasks[0]?.note || a.activeRuns.find(r => r.status === 'waiting_quota')?.status;
      if(reasonText) {
        const reason=node('details','','agent-reason-block');reason.dataset.detailKey='agent_reason_'+a.id;
        reason.append(node('summary','等待/阻塞：'+String(reasonText).slice(0,24)));
        reason.append(node('p',reasonText,'reason-text'));card.append(reason);
      }
      const info=node('details','','agent-extra-details');info.dataset.detailKey='agent_extra_'+a.id;
      info.append(node('summary','额度与执行详情 · 不限调用'));
      const q=a.sharedQuota;
      info.append(node('p',q.groupName+' · '+q.sharedWith.join('/'),'quota-window-chip'));
      for(const w of q.windows)info.append(node('p',w.name+'：'+(w.remainingPercent??'未知')+'% · 预计恢复 '+w.resetsAtFormatted));
      info.append(node('p',raw.profile?'同一账号的额度可能跨连接共享；未知不代表无限额度。':'DeepSeek 官方 API · 平台不限金额及次数，余额由官方账户决定'));
      card.append(info);
      const footer = node('footer','','agent-actions-footer');
      footer.append(button('停止', () => store.haltAgent(a.id)), button('解除锁', () => store.resumeAgent(a.id)));
      for (const r of a.activeRuns) {
        footer.append(button('停本轮', () => store.stopExecution(r.id, r.provider)));
        const promptText = r.actual_input || r.prompt;
        if (promptText) {
          const drawer = createActualInputDrawer('run_' + r.id, promptText, '查看 Run ' + r.id + ' 实际模型输入 (Actual Input)');
          if (drawer) info.append(drawer);
        }
      }
      card.append(footer);
      const detailsBody=node('div','','agent-card-details-body');detailsBody.hidden=true;
      detailsBody.append(node('p',a.role+' · '+a.model));
      if(connectionTest){const result=node('section','','agent-test-result');result.append(node('strong',(connectionTest.stale_configuration?'旧接入 · ':'')+(window.HubDesktop.testLabel?.(connectionTest)||connectionTest.status)),node('p',connectionTest.detail||''),node('p','模型：'+connectionTest.model+' · 档位：'+connectionTest.effort+' · '+new Date((connectionTest.finished||connectionTest.created)*1000).toLocaleString()));if(connectionTest.reply)result.append(node('pre',connectionTest.reply));detailsBody.append(result);}
      for(const child of [...card.children])if(child.classList.contains('agent-task-block')||child.classList.contains('agent-reason-block')||child.classList.contains('agent-extra-details')||child.classList.contains('agent-actions-footer'))detailsBody.append(child);
      const inspect=button('详情',()=>window.HubDesktop.openAgentDetails(a,detailsBody));inspect.classList.add('agent-details-toggle');inspect.setAttribute('aria-label','查看 '+a.name+' 的任务、额度与执行详情');const testButton=button('测试',()=>window.HubDesktop.openAgentTest(a));testButton.classList.add('agent-details-toggle');testButton.dataset.testAgent=a.id;testButton.setAttribute('aria-label','单独测试 '+a.name);const cardActions=node('div','','agent-card-test-actions');cardActions.append(testButton,inspect);card.append(cardActions,detailsBody);return card;
    }));
    list('agentStopButtons',v.agents.map(a => button('停止 ' + a.name, () => store.haltAgent(a.id))));
    list('stopLocks',(s.coordination?.stops || []).map(lock => { const d = node('div',lock.agent + ' · ' + (lock.reason || '停止锁')); d.append(button('解除锁', () => store.resumeAgent(lock.agent))); return d; }));
    list('tasks',(s.tasks || []).map(t => {
      const d = record((t.agent || '') + ' · ' + t.title, (t.note || '') + '\n进度 ' + (t.progress ?? 0) + '% · risk: ' + (t.risk || 'unknown'), t.status);
      const promptText = t.prompt || t.actual_input || t.input || t.instruction;
      if (promptText) {
        const drawer = createActualInputDrawer(t.id || t.title, promptText, '查看任务实际模型输入 (Actual Input)');
        if (drawer) {
          const inspect=node('button','{ }','chat-copy');inspect.type='button';inspect.title='查看实际模型输入';inspect.setAttribute('aria-label','查看实际模型输入');
          inspect.addEventListener('click',()=>{let dialog=$('chatSourceDialog');if(!dialog){dialog=node('dialog','','chat-source-dialog');dialog.id='chatSourceDialog';const close=button('×',()=>dialog.close());close.className='dialog-close';close.title='关闭';close.setAttribute('aria-label','关闭');const source=node('pre','','chat-source-text');source.id='chatSourceText';dialog.append(close,source);document.body.append(dialog);dialog.addEventListener('click',e=>{if(e.target===dialog)dialog.close();});}text('chatSourceText',promptText);dialog.showModal();});d.lastElementChild.append(inspect);
        }
      }
      return d;
    }));
    for (const [id, rows] of [['audit',s.audit],['wakeLog',s.coordination?.wakeups],['reportLog',s.coordination?.reports]]) list(id,(rows || []).map(r => {const entry=longText(dump(r));if(entry.tagName==='DETAILS'){entry.open=true;entry.ensureContent();}return entry;}));
    renderActivity(v);
  }
  const draftFields=['discussionReply','workflowRequirement','message'];
  const restoredDraftProjects=new Set();
  const draftKey=()=> 'hub.draft.'+(view.rawSnapshot?.selected_project||client.getSelectedProjectId()||'default');
  function stashDrafts() {
    if(!client.hasToken())return;
    try {sessionStorage.setItem(draftKey(),JSON.stringify(Object.fromEntries(draftFields.map(id=>[id,$(id)?.value||'']))));}catch(_) {}
  }
  function restoreDrafts() {
    if(!client.hasToken()||!view.rawSnapshot)return;
    const key=draftKey();if(restoredDraftProjects.has(key))return;
    restoredDraftProjects.add(key);
    try {const saved=JSON.parse(sessionStorage.getItem(key)||'{}');for(const id of draftFields)if($(id)&&!$(id).value&&typeof saved[id]==='string') {$(id).value=saved[id];$(id).dispatchEvent(new Event('input',{bubbles:true}));}}catch(_) {}
  }
  document.addEventListener('input',event=>{if(draftFields.includes(event.target?.id))stashDrafts();});
  document.addEventListener('visibilitychange',()=>{stashDrafts();if(!document.hidden&&client.hasToken())void store.refresh(true);});
  let lastRenderContent = null;
  store.subscribe(v => {
    view = v;
    // Heartbeats and receipt timestamps change each poll without changing content.
    const content = JSON.stringify({snapshot:v.rawSnapshot ? {...v.rawSnapshot,time:undefined} : null, discussion:v.managerStream?.planning?.sessionId, connection:[v.connection.status,v.connection.isStale,v.connection.message]},
      (key, value) => ['heartbeat','live_replies'].includes(key) ? undefined : value);
    if (content !== lastRenderContent) {
      render(v); for (const fn of renderers) fn(v);
      lastRenderContent = content;
    }
    restoreDrafts();
    if (client.hasToken()) { stashDrafts();void pollHealth(); }
  });
  window.addEventListener('pagehide', () => { stashDrafts(); store.stopPolling(); client.clearUserToken(); });

  // Native editing menus stay enabled. Other surfaces use this keyboard-accessible
  // workbench menu; clipboard failures always retain the native Ctrl+V fallback.
  const contextMenu = $('desktopContextMenu');
  let lastEditor = null, contextText = '', contextRange = null;
  const editor = target => target?.closest?.('input, textarea, [contenteditable="true"]');
  const writable = target => target && !target.disabled && !target.readOnly;
  const selectableEditor = target => target && typeof target.value === 'string' && typeof target.selectionStart === 'number';
  const hideContext = () => { contextMenu.hidden = true; };
  function selectedEditorText() {
    return selectableEditor(lastEditor) && lastEditor.type !== 'password' ? lastEditor.value.slice(lastEditor.selectionStart,lastEditor.selectionEnd) : '';
  }
  function showContext(event) {
    hideContext();
    const input = editor(event.target);
    if (input && !input.disabled) { lastEditor = input; return; } // Do not suppress OS editing menus.
    event.preventDefault();
    const selection = window.getSelection?.();
    contextText = lastEditor?.type === 'password' && document.activeElement === lastEditor ? '' : (selection?.toString() || selectedEditorText());
    contextRange = selection?.rangeCount ? selection.getRangeAt(0).cloneRange() : null;
    for (const item of contextMenu.querySelectorAll('button')) {
      const command = item.dataset.contextCommand;
      item.disabled = command === 'copy' ? !contextText : ['paste','clear','cut'].includes(command) ? !writable(lastEditor) || (command === 'cut' && !selectedEditorText()) : false;
    }
    contextMenu.hidden = false;
    const scale=Number(document.documentElement?.dataset.interfaceZoom || 100)/100;
    // CSSOM edits a trusted external rule, preserving the strict style-src CSP.
    for (const sheet of document.styleSheets || []) {
      try {
        const rule = [...sheet.cssRules].find(r => r.selectorText === '#desktopContextMenu');
        if (rule) {
          const width=window.innerWidth || 1280,height=window.innerHeight || 800;
          rule.style.setProperty('max-width',(width-16)/scale+'px');
          rule.style.setProperty('max-height',(height-16)/scale+'px');
          const rect=contextMenu.getBoundingClientRect();
          const x=Math.max(8,Math.min(event.clientX || 0,width-rect.width-8))/scale;
          const y=Math.max(8,Math.min(event.clientY || 0,height-rect.height-8))/scale;
          rule.style.setProperty('left',x+'px');rule.style.setProperty('top',y+'px');break;
        }
      } catch (_) { /* Ignore sheets which are not same-origin. */ }
    }
    [...contextMenu.querySelectorAll('button')].find(b => !b.disabled)?.focus?.();
  }
  function changed(input) { input.dispatchEvent(new Event('input',{bubbles:true})); }
  async function copyContext() {
    if (!contextText) return false;
    try { await navigator.clipboard.writeText(contextText);return true; }
    catch (_) {
      if (contextRange) { const selection=window.getSelection();selection.removeAllRanges();selection.addRange(contextRange); }
      else if (selectableEditor(lastEditor)) lastEditor.focus();
      if (document.execCommand?.('copy')) return true;
      throw new Error('剪贴板写入被系统限制。请选中文本后使用原生右键“复制”或 Ctrl+C。');
    }
  }
  async function setInterfaceZoom(percent) {
    if (![90,100,110,125,150].includes(percent)) throw new Error('不支持的缩放比例');
    if (desktopSession) {
      const response = await fetch('/desktop-ui',{method:'POST',headers:{'Content-Type':'application/json','X-Desktop-Session':desktopSession},body:JSON.stringify({zoom:percent}),signal:AbortSignal.timeout(5000)});
      if (!response.ok) throw new Error('原生缩放暂不可用，可使用 Ctrl + / − / 0 调整。');
    } else document.documentElement.dataset.interfaceZoom = String(percent);
  }
  async function contextCommand(command) {
    hideContext();
    if (command.startsWith('zoom-')) return setInterfaceZoom(Number(command.slice(5)));
    if (command === 'copy') return copyContext();
    if (command === 'paste') {
      if (!writable(lastEditor)) return;
      lastEditor.focus();
      let pasted;
      try { pasted=await navigator.clipboard.readText(); }
      catch (_) { throw new Error('剪贴板读取被系统限制。请在输入框右键选择“粘贴”，或按 Ctrl+V。'); }
      if (!pasted) return;
      if (lastEditor.isContentEditable) {
        if (!document.execCommand('insertText',false,pasted)) throw new Error('请使用原生右键菜单粘贴到编辑区域。');
      } else {
        const start=lastEditor.selectionStart ?? lastEditor.value.length,end=lastEditor.selectionEnd ?? start;
        if (lastEditor.maxLength >= 0) pasted=pasted.slice(0,Math.max(0,lastEditor.maxLength-lastEditor.value.length+end-start));
        try { lastEditor.setRangeText(pasted,start,end,'end'); }
        catch (_) { lastEditor.value=pasted; }
      }
      changed(lastEditor);return;
    }
    if (command === 'cut' && writable(lastEditor) && selectedEditorText()) {
      contextText=selectedEditorText();if (await copyContext()) {lastEditor.setRangeText('',lastEditor.selectionStart,lastEditor.selectionEnd,'end');changed(lastEditor);}return;
    }
    if (command === 'clear' && writable(lastEditor)) {
      if (lastEditor.isContentEditable) lastEditor.textContent='';else lastEditor.value='';changed(lastEditor);lastEditor.focus();return;
    }
    if (command === 'select') {
      if (lastEditor) {lastEditor.focus();lastEditor.select?.();}
      else {const range=document.createRange();range.selectNodeContents($('workspace').hidden ? $('login') : $('workbenchCenter'));const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);}return;
    }
    if (command === 'manager' || command === 'group') { $('viewModeChatRadio').checked=true;$(command==='manager'?'chatTabManagerRadio':'chatTabGroupRadio').checked=true;return; }
    if (command === 'status') {$('viewModeStatusRadio').checked=true;return;}
    if (command === 'config') {$('configModalToggle').checked=true;return;}
    ready();
    if (command === 'guide') return window.HubDesktop.openProviderGuide();
    if (command === 'refresh') return store.refresh(true);
    if (command === 'quota') {
      const results=await Promise.allSettled([store.refreshOpenAIQuota(),store.refreshAntigravityQuota()]);
      const failures=results.filter(r=>r.status==='rejected');if(failures.length)throw new Error(failures.map(r=>r.reason.message).join('；'));
    }
  }
  window.HubDesktop.setInterfaceZoom=setInterfaceZoom;
  document.addEventListener('focusin',event=>{const input=editor(event.target);if(input)lastEditor=input;});
  document.addEventListener('contextmenu',showContext);
  document.addEventListener('pointerdown',event=>{if(!contextMenu.contains(event.target))hideContext();});
  document.addEventListener('scroll',hideContext,true);
  window.addEventListener('resize',hideContext);
  document.addEventListener('keydown',event=>{if(event.key==='Escape')hideContext();});
  contextMenu.addEventListener('click',async event=>{
    const item=event.target.closest('button[data-context-command]');if(!item||item.disabled)return;
    try {await contextCommand(item.dataset.contextCommand);}catch(error){notice(error.message);}
  });
  contextMenu.addEventListener('keydown',event=>{
    const items=[...contextMenu.querySelectorAll('button')].filter(b=>!b.disabled);
    if (['ArrowDown','ArrowUp','Home','End'].includes(event.key)) {
      event.preventDefault();const current=items.indexOf(document.activeElement);
      const next=event.key==='Home'?0:event.key==='End'?items.length-1:(current+(event.key==='ArrowDown'?1:-1)+items.length)%items.length;items[next]?.focus();
    } else if(event.key==='Tab')hideContext();
  });
})();
