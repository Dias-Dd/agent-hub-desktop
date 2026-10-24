import re,tempfile,threading,unittest
import test_nine_browser as base

CHECK=r'''
const raw='[真实 DeepSeek Harness · completed] ```json\n{"done":true,"report":"## 交付完成\\n\\n**计算器**与`calc.exe`已就绪，不能把"演示一致"当验收。\\n\\n- 功能通过\\n- 视觉已检查","tasks":[]}\n```';
const row=H.chatMessage('经理',raw,'completed',1792749511);
document.getElementById('discussionHistory').replaceChildren(row);
if(row.textContent.includes('"tasks"')||row.textContent.includes('[真实')||row.textContent.includes('"done"'))throw Error('JSON envelope visible');
if(!row.querySelector('h3')||!row.querySelector('strong')||!row.querySelector('code')||row.querySelectorAll('li').length!==2)throw Error('Markdown not rendered');
if(!row.textContent.includes('"演示一致"'))throw Error('malformed JSON report truncated');
const text='## 安全显示\n\n<script>window.__markdownInjected=true</script>\n\n[安全](https://example.com) [危险](javascript:alert(1))\n\n```html\n<img src=x onerror=alert(1)>\n```';
const safe=H.chatMessage('经理',text,'completed',1);document.getElementById('discussionHistory').append(safe);
if(safe.querySelector('script,img')||window.__markdownInjected)throw Error('HTML executed');
if(safe.querySelectorAll('a').length!==1||!safe.querySelector('a').href.startsWith('https://example.com'))throw Error('unsafe link rendered');
if(!safe.querySelector('pre code').textContent.includes('<img'))throw Error('code missing');
if(safe.querySelector('.chat-message-body')._markdownSource!==text)throw Error('copy source not preserved');
const user=H.chatMessage('用户','**保持原文**','completed',1);if(user.querySelector('strong')||!user.textContent.includes('**保持原文**'))throw Error('user source rewritten');
const live=document.getElementById('managerLiveText');window.HubChatFormat.renderMarkdown(live,'## 正在执行\n\n**进度**');if(!live.querySelector('strong'))throw Error('live Markdown missing');
const valid='```json\n'+JSON.stringify({done:true,report:'**有效报告**',tasks:[]})+'\n```';if(H.readableChat(valid)!=='**有效报告**')throw Error('valid legacy JSON failed');

const tableSource='| 项目 | 状态 | 数值 |\n| :--- | :---: | ---: |\n| **测试** | `a|b` | 42 |\n| [链接](https://example.com) | a\\|b | <img src=x> |';
const tables=document.createElement('div');document.getElementById('discussionHistory').append(tables);window.HubChatFormat.renderMarkdown(tables,tableSource);
if(tables.querySelectorAll('th').length!==3||tables.querySelectorAll('tbody tr').length!==2||tables.querySelectorAll('td').length!==6)throw Error('table structure missing');
if(tables.querySelectorAll('td')[1].textContent!=='a|b'||tables.querySelectorAll('td')[4].textContent!=='a|b')throw Error('pipe escaping or code cell broken');
if(!tables.querySelector('td strong')||tables.querySelector('img')||getComputedStyle(tables.querySelector('th:last-child')).textAlign!=='right')throw Error('cell formatting, safety or alignment broken');
const savedCell=tables.querySelector('td'),scroller=tables.querySelector('.markdown-table-scroll');tables.style.width='240px';scroller.scrollLeft=30;const position=scroller.scrollLeft;
window.HubChatFormat.renderMarkdown(tables,tableSource+'\n| 追加 | 通过 | 99 |');
if(tables.querySelector('td')!==savedCell||scroller.scrollLeft!==position||scroller.scrollWidth<=scroller.clientWidth)throw Error('stream update reset table or wide table cannot scroll');
if(tables._markdownSource!==tableSource+'\n| 追加 | 通过 | 99 |')throw Error('table copy source lost');
window.HubChatFormat.renderMarkdown(live,'名称 | 状态\n--- | ---\n项目 | 完成');if(live.querySelectorAll('th').length!==2)throw Error('table without outer pipes unsupported');
window.HubChatFormat.renderMarkdown(live,'```\n| a | b |\n| --- | --- |\n```');if(live.querySelector('table')||!live.querySelector('pre'))throw Error('code fence interpreted as table');
const original='## 很长的回复\n\n'+Array.from({length:150},(_,i)=>'- 第'+i+'项内容，保留完整阅读和滚动位置。').join('\n');
H.list('discussionHistory',[H.chatMessage('经理',original,'completed',1)]);
const area=document.getElementById('managerReadingArea');area.scrollTop=80;const draft=document.getElementById('discussionReply');draft.value='保留我的草稿';
await H.store.refresh(true);if(draft.value!=='保留我的草稿')throw Error('draft lost');
'''

class Markdown(unittest.TestCase):
 @unittest.skipUnless(base.m.EDGE.exists(),'Edge unavailable')
 def test_completed_legacy_live_markdown_and_safe_links(self):
  original=base.DRIVER;base.DRIVER=original.replace("out.textContent='PASS",CHECK+"out.textContent='PASS")
  server=base.Server(('127.0.0.1',0),base.Fixture);thread=threading.Thread(target=server.serve_forever);thread.start()
  try:
   with tempfile.TemporaryDirectory() as folder:
    p=base.browser_run([str(base.m.EDGE),'--headless','--disable-gpu','--no-first-run','--window-size=1440,900',f'--user-data-dir={folder}','--dump-dom','--virtual-time-budget=6000',f'http://127.0.0.1:{server.server_port}/'],capture_output=True,encoding='utf8',errors='replace',timeout=30)
    result=re.search(r'<pre id="result">(.*?)</pre>',p.stdout,re.S);self.assertIsNotNone(result);self.assertTrue(result.group(1).startswith('PASS'),result.group(1))
  finally:server.shutdown();server.server_close();thread.join();base.DRIVER=original
