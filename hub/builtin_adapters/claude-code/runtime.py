"""Official Claude Code print protocol; no global config or MCP mutations."""
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import uuid
from hub.core import HubError
from hub.process_job import ProcessJob
from hub.integration_runtime import bridge, cli_failure
from .config import executable, environment


class Stream:
    def __init__(self,argv,cwd,env):
        from hub.integrations import command
        self.closed=threading.Event();self.events=queue.Queue(maxsize=16);self.errors=[];self.threads=[]
        self.proc=subprocess.Popen(command(argv),cwd=cwd,env=env,stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',
            start_new_session=os.name!='nt',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:self.job=ProcessJob(self.proc)
        except Exception:
            self.proc.kill();self.proc.wait(timeout=5)
            for pipe in (self.proc.stdin,self.proc.stdout,self.proc.stderr):pipe.close()
            raise
        def offer(value):
            while not self.closed.is_set():
                try:self.events.put(value,timeout=.2);return
                except queue.Full:pass
        def read():
            try:
                while not self.closed.is_set():
                    line=self.proc.stdout.readline(4_000_001)
                    if not line:break
                    if len(line)>4_000_000:offer({'_error':'Claude Code 单条输出超过 4 MB'});break
                    try:value=json.loads(line)
                    except ValueError:offer({'_error':'Claude Code 未返回合法 JSON 事件'});break
                    if not isinstance(value,dict):offer({'_error':'Claude Code 事件必须是对象'});break
                    offer(value)
            finally:offer({'_eof':True})
        def errors():
            while not self.closed.is_set():
                line=self.proc.stderr.readline(4096)
                if not line:break
                self.errors.append(line[-1200:]);del self.errors[:-16]
        for target in (read,errors):
            thread=threading.Thread(target=target,daemon=True);thread.start();self.threads.append(thread)

    def send(self,prompt):
        self.proc.stdin.write(prompt);self.proc.stdin.flush();self.proc.stdin.close()

    def close(self):
        self.closed.set();self.job.close()
        if self.proc.poll() is None:
            self.proc.kill();self.proc.wait(timeout=5)
        if not self.proc.stdin.closed:self.proc.stdin.close()
        for thread in self.threads:thread.join(timeout=3)
        for pipe in (self.proc.stdout,self.proc.stderr):pipe.close()


def execute(self,original):
    run=dict(original);run['started']=run.get('started') or time.time()
    stream=None;mcp_path=None;submitted=False;status='failed';result='';usage=None;env={}
    try:
        self.guard(run)
        connection=self.connection();exe=executable(connection.get('executable',''))
        if not exe:raise HubError('尚未安装 Claude Code，请先通过官网安装；未调用模型')
        readonly=self.read_only(run);run['_read_only']=readonly
        if not readonly and run['permission']!='full':raise HubError('Claude Code 接入未声明工作区沙箱，需要用户明确授权完全访问')
        allowed=[t['function']['name'] for t in self.definitions(run) if t['function']['name'] not in ('read_file','write_file','run_command')]
        native=[] if run.get('purpose') in ('discussion','question') else ['Read','Glob','Grep'] if readonly else ['Read','Glob','Grep','Write','Edit','Bash']
        old=self.sessions.get(run)
        session=old['session_id'] if old else str(uuid.uuid4())
        try:uuid.UUID(session)
        except (ValueError,TypeError):raise HubError('Claude Code 原会话 ID 无效，保留记录，不创建替代会话') from None
        target=str(Path(run['cwd']).resolve());cwd=str(Path(old['cwd']).resolve()) if old else target
        prompt=self.execution_instructions(run)+self.report_instructions(run)+'\n\n'+run['prompt']
        if os.path.normcase(cwd)!=os.path.normcase(target):
            from hub.module_sdk import workspace_notice
            prompt=workspace_notice(target,cwd)+prompt
        # Per-run MCP configuration contains only the Hub token, never provider
        # credentials. Tokens are not passed on the command line or persisted.
        mcp=bridge(self,run,allowed)
        folder=self.hub.directory/'integrations'/run['id'];folder.mkdir(parents=True,exist_ok=True)
        mcp_path=folder/'claude-mcp.json'
        payload={'mcpServers':{'agent-message-hub':{'command':mcp['command'],'args':mcp['args'],
            'env':{item['name']:item['value'] for item in mcp['env']}}}} if allowed else {'mcpServers':{}}
        with open(mcp_path,'w',encoding='utf-8',opener=lambda path,flags:os.open(path,flags,0o600)) as handle:json.dump(payload,handle)
        names=['mcp__agent-message-hub__'+name for name in allowed]
        argv=[exe,'-p','--output-format','stream-json','--verbose','--include-partial-messages',
            '--model',run['model'],'--permission-mode','dontAsk' if readonly else 'bypassPermissions',
            '--tools',','.join(native),'--strict-mcp-config','--mcp-config',str(mcp_path),
            '--disable-slash-commands','--settings',json.dumps({'disableAllHooks':True})]
        if native or names:argv+=['--allowedTools',','.join(native+names)]
        argv+=['--resume' if old else '--session-id',session]
        if target!=cwd:argv+=['--add-dir',target]
        env=environment();env.update(self.run_environment(run))
        with self.hub.tx():self.hub.db.execute('UPDATE executions SET actual_input=? WHERE id=?',(prompt,run['id']))
        self.guard(run);stream=Stream(argv,cwd,env);self.track_client(run,stream)
        self.guard(run)
        # Reserve the UUID before stdin submission. A disconnect before init
        # must not silently create a different conversation on the next run.
        self.sessions.bind(run,session,'inflight',cwd=cwd)
        with self.hub.tx():self.hub.db.execute('UPDATE executions SET thread_id=? WHERE id=?',(session,run['id']))
        submitted=True;stream.send(prompt)
        initialized=False;final=None;seen=set()
        while final is None:
            self.guard(run)
            try:event=stream.events.get(timeout=.25)
            except queue.Empty:continue
            if event.get('_error'):raise HubError(event['_error'])
            if event.get('_eof'):raise HubError(cli_failure(None,stream.proc.poll(),stream.errors,env))
            kind=event.get('type')
            if event.get('session_id') and event['session_id']!=session:raise HubError('Claude Code 返回了不同会话，已停止，不自动重试')
            if kind=='system' and event.get('subtype')=='init':
                if initialized:raise HubError('Claude Code 重复初始化，未确认当前回合')
                if event.get('session_id')!=session:raise HubError('Claude Code 未确认本轮会话 ID')
                if os.path.normcase(str(Path(event.get('cwd','')).resolve()))!=os.path.normcase(cwd):raise HubError('Claude Code 启动目录与原会话不一致')
                if event.get('permissionMode')!=('dontAsk' if readonly else 'bypassPermissions'):raise HubError('Claude Code 未确认批准的权限模式')
                actual_tools=event.get('tools',[])
                if not isinstance(actual_tools,list) or not set(names).issubset(set(actual_tools)):raise HubError('Claude Code 未挂载本轮所需 Hub 工具，请检查 MCP 连接；不自动重试')
                if not isinstance(event.get('model'),str) or not event['model']:raise HubError('Claude Code 未返回实际模型')
                if run['model'] not in ('sonnet','opus','haiku') and event['model']!=run['model']:raise HubError('Claude Code 实际模型与所选模型不一致；不自动降级')
                initialized=True;self.sessions.bind(run,session,'inflight',cwd=cwd)
                with self.hub.tx():self.hub.db.execute('UPDATE executions SET thread_id=? WHERE id=?',(session,run['id']))
                self.record(run['id'],'claude.init',{'model':event['model'],'session':session,'resumed':bool(old),'cwd':cwd})
            elif kind=='result':final=event
            elif kind in ('assistant','stream_event'):
                if not initialized:raise HubError('Claude Code 在初始化确认前返回回复，不能核实执行状态')
                if event.get('isReplay'):continue
                if kind=='stream_event':
                    update=event.get('event') or {}
                    delta=update.get('delta') or {}
                    if update.get('type')=='content_block_delta' and delta.get('type')=='text_delta' and isinstance(delta.get('text'),str):
                        self.public_reply(run,delta['text'],phase='正在生成回复')
                else:
                    message=event.get('message') or {};ident=message.get('id') or event.get('uuid')
                    if ident and ident in seen:continue
                    if ident:seen.add(ident)
                    blocks=message.get('content') or []
                    text='\n'.join(b['text'] for b in blocks if isinstance(b,dict) and b.get('type')=='text' and isinstance(b.get('text'),str))
                    if text:self.public_reply(run,text,replace=True,phase='正在生成回复')
                    if any(b.get('type')=='tool_use' for b in blocks if isinstance(b,dict)):
                        self.public_reply(run,phase='正在使用项目工具')
        deadline=time.monotonic()+5
        while stream.proc.poll() is None:
            self.guard(run)
            if time.monotonic()>=deadline:raise HubError('Claude Code 返回结果后未退出，执行状态待核实，不自动重试')
            time.sleep(.05)
        code=stream.proc.returncode
        if final.get('is_error') or final.get('subtype')!='success' or code!=0:
            status='failed';result=cli_failure(final,code,stream.errors,env)
        else:
            if not initialized or final.get('session_id')!=session:raise HubError('Claude Code 最终结果没有对应的会话确认')
            text=final.get('result')
            if not isinstance(text,str) or not text.strip():raise HubError('Claude Code 本轮没有文字结果，不能确认成功；保留会话，不自动重试')
            if len(text)>262144:raise HubError('Claude Code 回复超过 262144 字符，未截断为有效计划')
            status='completed';result=text;usage=final.get('usage')
            self.public_reply(run,text,replace=True,phase='回复已完成')
        self.record(run['id'],'claude.result',{'status':status,'exit_code':code,'usage':usage})
    except Exception as error:
        stopped=self.stop_event.is_set()
        with self.hub.lock:
            row=self.hub.db.execute('SELECT stop_requested FROM executions WHERE id=?',(run['id'],)).fetchone()
        status='interrupted' if stopped or row and row[0] else 'uncertain' if submitted else 'failed'
        result=cli_failure(None,None,[str(error) if isinstance(error,HubError) else type(error).__name__+': '+str(error)],env)
    finally:
        if stream:stream.close()
        if mcp_path:mcp_path.unlink(missing_ok=True)
        self.clients.pop(run['id'],None);self.sessions.state(run,status);self.finalize(run,status,result,usage)
