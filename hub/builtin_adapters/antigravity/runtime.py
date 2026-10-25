from hub.module_sdk import host_resource
"""Google's supported Antigravity CLI, cached Google account login only."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time
from hub.core import HubError
from hub.codex_runtime import CodexRuntime
from hub.process_job import ProcessJob
from hub.proxy_env import inherit_system_proxy,describe

MODELS={'deepseek-1':'gemini-3.8-flash-medium','deepseek-2':'gemini-3.8-flash-medium','deepseek-3':'gemini-3.8-flash-medium','deepseek-4':'gemini-4-argon-medium','deepseek-5':'claude-opus-5-5-medium'}

def executable():
    found=shutil.which('agy')
    if found:return found
    root=os.environ.get('LOCALAPPDATA')
    path=Path(root)/'agy/bin/agy.exe' if root else None
    return str(path) if path and path.is_file() else None

def environment():
    # Explicitly remove API/ADC environment routes, do not export/read OAuth tokens.
    blocked={'GEMINI_API_KEY','GOOGLE_API_KEY','GOOGLE_APPLICATION_CREDENTIALS','GOOGLE_GENAI_USE_VERTEXAI','GOOGLE_GEMINI_BASE_URL','ANTHROPIC_API_KEY','OPENAI_API_KEY','DEEPSEEK_API_KEY','HUB_TOKEN'}
    return inherit_system_proxy({k:v for k,v in os.environ.items() if k.upper() not in blocked})

def personal_settings():
    path=Path.home()/'.gemini/antigravity-cli/settings.json'
    if not path.exists():return
    try:
        data=json.loads(path.read_text(encoding='utf-8-sig'))
        auth=(data.get('auth') or {}).get('type')
        provider=data.get('modelProvider')
        if auth not in (None,'oauth-personal') or provider not in (None,'antigravity'):
            raise HubError('Antigravity 配置不是个人 Google 登录；不切换到 API/企业计费')
    except (ValueError,TypeError):raise HubError('无法核实 Antigravity 用户设置；请在官方 CLI 检查登录方式') from None

def parse_usage(output):
    rows=[]
    for line in output.splitlines():
        fields=line.strip().split('\t')
        if len(fields)!=4 or not re.fullmatch(r'\d+(?:\.\d+)?%',fields[2]):continue
        try:
            remaining=float(fields[2][:-1]);reset=datetime.fromisoformat(fields[3].replace('Z','+00:00')).timestamp()
        except ValueError:continue
        if 0<=remaining<=100:rows.append({'group':fields[0],'window':fields[1],'remaining':remaining,'resets_at':reset})
    return rows

class AntigravityProbe:
    def __init__(self,executable_path=None):self.executable_path=executable_path
    def exe(self):return self.executable_path() if callable(self.executable_path) else self.executable_path or executable()
    def command(self,args,cwd=None):
        exe=self.exe()
        if not exe:raise HubError('找不到 agy；支持 PATH 及 Windows 官方默认安装位置')
        personal_settings()
        try:
            out=subprocess.run([exe,*args],cwd=cwd,env=environment(),stdin=subprocess.DEVNULL,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=35,creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000) if os.name == 'nt' else 0)
        except subprocess.TimeoutExpired:raise HubError('Antigravity 官方只读检查超时') from None
        if out.returncode:raise HubError('Antigravity 官方检查失败；请在终端运行 agy 并确认个人 Google 账号已登录')
        return out.stdout

    def run(self):
        if not self.exe():return {'installed':False,'models':[],'windows':[],'quota_source':'unknown'}
        version=self.command(['--version']).strip()
        models=[]
        for line in self.command(['models']).splitlines():
            fields=line.split('\t',1)
            if len(fields)==2 and re.fullmatch(r'[a-z0-9][a-z0-9.-]+',fields[0]):models.append({'model':fields[0],'name':fields[1]})
        windows=parse_usage(self.command(['-p','/usage']))
        return {'installed':True,'version':version,'models':models,'windows':windows,'observed_at':time.time(),'quota_source':'official_cli' if windows else 'unknown','auth_evidence':'cached Google account model quotas' if windows else 'unknown','inference_tested':False,'network':describe(environment())}

def applicable_windows(probe,agent,model=None):
    windows=probe.get('windows') or []
    group='Claude and GPT models' if (model and model.startswith(('claude','gpt'))) or (not model and agent=='deepseek-5') else 'Gemini Models'
    return [w for w in windows if w['group']==group or (model and 'argon' in model and w['group']=='Gemini 4 Argon')]

def model_efforts(model):
    match=re.search(r'-(low|medium|high|xhigh|max)$',model)
    return [match.group(1)] if match else ['default']

def selected_effort(model,requested='default'):
    bound=model_efforts(model)[0]
    if bound!='default':return bound
    return requested if requested in ('low','medium','high','xhigh','max') else None

class AntigravityStream:
    hub_transport="antigravity"
    def __init__(self,run,instructions):
        args=[run.get('_executable') or executable(),'--input-format','stream-json','--output-format','stream-json','--model',run['model'],'--mode','auto','--dangerously-skip-permissions','--disable-slash-commands','--print-timeout',str(run['max_seconds'])+'s']
        effort=selected_effort(run['model'],run.get('_effort','default'))
        if effort:args+=['--effort',effort]
        if run.get('_conversation'):args+=['--conversation',run['_conversation']]
        if run.get('purpose') in ('discussion','question'):
            args[args.index('--mode')+1]='plan';args.remove('--dangerously-skip-permissions');args.append('--sandbox')
        self.proc=subprocess.Popen(args,cwd=run['cwd'],env={**{k:v for k,v in environment().items() if not k.startswith('HUB_')},**run.get('_hub_env',{})},stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',bufsize=1,creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000) if os.name == 'nt' else 0)
        self.closed=False;self.inbox=queue.Queue();self.invalid=False
        try:self.job=ProcessJob(self.proc)
        except Exception:
            self.proc.terminate();self.proc.wait(timeout=5)
            self.proc.stdin.close();self.proc.stdout.close();self.proc.stderr.close()
            raise HubError('无法建立 Antigravity CLI 子进程守护') from None
        def read():
            try:
                for line in self.proc.stdout:
                    try:self.inbox.put(json.loads(line))
                    except ValueError:self.invalid=True
            finally:self.inbox.put({'event':'eof'})
        def diagnostics():
            # Drain stderr to prevent deadlock; do not persist auth diagnostics.
            for _ in self.proc.stderr:pass
        self.reader=threading.Thread(target=read,daemon=True);self.reader.start()
        self.drainer=threading.Thread(target=diagnostics,daemon=True);self.drainer.start()
        if not run.get('_defer_prompt'):self.start_prompt(run,instructions)
    def start_prompt(self,run,instructions):
        try:
            actual_content=run.get('_manager_content',instructions+'\n\n用户任务（按以下内容实际执行）：\n'+run['prompt'])
            self.proc.stdin.write(json.dumps({'event':'user','message':{'content':actual_content}},ensure_ascii=False)+'\n');self.proc.stdin.flush();self.proc.stdin.close()
        except Exception:
            self.close();raise

    def event(self):
        try:return self.inbox.get(timeout=.5)
        except queue.Empty:return None

    def wait(self):return self.proc.wait(timeout=10)

    def close(self):
        if self.closed:return
        self.closed=True;self.job.close()
        if self.proc.poll() is None:
            self.proc.terminate()
            try:self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait()
        self.reader.join(timeout=2);self.drainer.join(timeout=2)
        self.proc.stdout.close();self.proc.stderr.close()

class AntigravityRuntime(CodexRuntime):
    provider='antigravity'
    models=MODELS
    config_key='antigravity_runtime'
    title='Antigravity'

    def __init__(self,hub,stream_factory=AntigravityStream,probe=None):
        super().__init__(hub)
        self.stream_factory=stream_factory;self.probe=probe or AntigravityProbe()

    def configure(self,actor,cwd,permission,max_runs,max_seconds,enabled=True,confirmed=False):
        if permission!='full':raise HubError('当前 Antigravity 适配器仅支持明确授权的完全访问；不假设命令工具可在工作区模式无人值守批准')
        return super().configure(actor,cwd,permission,max_runs,max_seconds,enabled,confirmed)

    def refresh(self,actor):
        self.hub.require(actor,{'user'})
        result=self.probe.run()
        with self.hub.tx():
            self.hub.db.execute("INSERT OR REPLACE INTO settings VALUES('antigravity_limits',?)",(json.dumps(result,ensure_ascii=False),))
            self.hub.audit(actor,'antigravity.official_read',{'installed':result.get('installed'),'quota_source':result.get('quota_source')})
        return result

    def snapshot(self,actor):
        data=super().snapshot(actor)
        with self.hub.lock:
            row=self.hub.db.execute("SELECT value FROM settings WHERE key='antigravity_limits'").fetchone()
        data['capabilities']=json.loads(row[0]) if row else None
        validation=host_resource('../docs/antigravity-live-test.json')
        if validation.is_file():
            try:
                checked=json.loads(validation.read_text(encoding='utf-8'))
                data['delivery_validation']={k:checked.get(k) for k in ('model','status','result','finished')}
            except (OSError,ValueError):pass
        proxy_test=host_resource('../docs/antigravity-proxy-test.json')
        if proxy_test.is_file():
            try:
                checked=json.loads(proxy_test.read_text(encoding='utf-8'))
                end=next((e for e in checked.get('events',[]) if e.get('event')=='result'),{})
                data['proxy_validation']={'date':checked.get('date'),'status':(end.get('result') or {}).get('status'),'response':(end.get('result') or {}).get('response'),'exit_code':end.get('exit_code')}
            except (OSError,ValueError):pass
        return data

    def ensure_mcp(self):
        if getattr(self,'mcp_ready',False):return
        import sys
        if getattr(sys, 'frozen', False):
            bridge = Path(self.hub.directory) / 'mcp_bridge.py'
            try:
                src_mcp = host_resource('mcp.py')
                if src_mcp.is_file():
                    bridge.write_bytes(src_mcp.read_bytes())
            except OSError:
                pass
            py_exe = shutil.which('python')
            if py_exe and bridge.is_file():
                command=[(self.connection_executable() if hasattr(self,'connection_executable') else executable()),'mcp','add','agent-message-hub',py_exe,str(bridge.resolve())]
            else:
                command=[(self.connection_executable() if hasattr(self,'connection_executable') else executable()),'mcp','add','agent-message-hub','--',sys.executable,'--mcp-server']
        else:
            command=[(self.connection_executable() if hasattr(self,'connection_executable') else executable()),'mcp','add','agent-message-hub',sys.executable,str(host_resource('mcp.py').resolve())]
        check=subprocess.run(command,env=environment(),capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=20,creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000) if os.name == 'nt' else 0)
        if check.returncode:raise HubError('官方 CLI 未能配置 Hub MCP；未启动本轮推理')
        self.mcp_ready=True

    def execute(self,run):
        from hub.harness_adapters import execute_builtin
        return execute_builtin(self,run,'antigravity')

    def _execute_native(self,run):
        stream=None;status='failed';result='';usage=None;submitted=False
        renew_stop=threading.Event()
        def renew():
            while not renew_stop.wait(3):
                try:self.check_latch(run);self.hub.heartbeat(run['agent'],'busy')
                except Exception:return
        renewal=threading.Thread(target=renew,daemon=True);renewal.start()
        try:
            self.check_latch(run)
            if hasattr(self,'connection_executable'):run['_executable']=self.connection_executable()
            run['_effort']=selected_effort(run['model'],self.effort(run['agent']) if hasattr(self,'effort') else 'default')
            capabilities=self.refresh('user')
            self.check_latch(run)
            if run['model'] not in {m['model'] for m in capabilities.get('models',[])}:raise HubError('官方模型列表未返回指定模型；不替换模型')
            windows=applicable_windows(capabilities,run['agent'],run['model'])
            if not windows:raise HubError('无法核实订阅额度，未启动推理')
            empty=[w for w in windows if w['remaining']<=0]
            if empty:
                status='cancelled';estimated=max(w['resets_at'] for w in empty)
                result='订阅额度耗尽，本任务已取消；预计恢复 '+datetime.fromtimestamp(estimated,timezone.utc).isoformat()+'。请经理改派或设置恢复提醒，不自动重跑。'
                from hub.quota_state import record_rejection
                with self.hub.tx():record_rejection(self.hub,run,result)

            else:
                instructions=self.execution_instructions(run)
                if run.get('purpose')=='discussion':instructions=self.execution_instructions(run)
                else:instructions+=self.report_instructions(run)
                compact=self.compact_manager_input(run)
                if compact is not None:instructions=compact
                with self.hub.lock:project_step=self.hub.db.execute('SELECT 1 FROM workflow_steps WHERE task=?',(run['task_id'],)).fetchone() if self.hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='workflow_steps'").fetchone() else None
                plain_dialogue=run.get('purpose')=='question' and not project_step
                session=self.sessions.get(run)
                if session:run['_conversation']=session['session_id']
                run['_hub_env']=self.run_environment(run)
                if self.stream_factory is AntigravityStream:self.ensure_mcp()
                actual_content=run.get('_manager_content',instructions+'\n\n用户任务（按以下内容实际执行）：\n'+run['prompt'])
                with self.hub.tx():self.hub.db.execute('UPDATE executions SET actual_input=? WHERE id=?',(actual_content,run['id']))
                if self.stream_factory is AntigravityStream:run['_defer_prompt']=True
                stream=self.stream_factory(run,instructions);self.track_client(run,stream)
                if isinstance(stream,AntigravityStream):
                    with self.hub.lock:
                        self.check_latch(run);stream.start_prompt(run,instructions)
                submitted=True;started=time.monotonic();validated=False
                if run.get('_manager_content') is not None:self.record(run['id'],'manager.input',{'role':'user','characters':len(run['_manager_content']),'policy_added':bool(instructions),'content':run['_manager_content'],'scope':'Hub新增输入，不含历史和工具结果'})
                while True:
                    with self.hub.lock:
                        stop=self.hub.db.execute('SELECT stop_requested FROM executions WHERE id=?',(run['id'],)).fetchone()[0]
                    if stop or self.stop_event.is_set() or time.monotonic()-started>run['max_seconds']:
                        status='uncertain';result='已停止本地 CLI 进程树；此接口没有已验证的服务端取消确认，文件和订阅消耗可能已发生，不自动重试'
                        self.record(run['id'],'local_stop',{'confirmed_server_cancel':False});break
                    event=stream.event()
                    if event is None:continue
                    kind=event.get('event')
                    if kind=='init':
                        init=event.get('init') or {}
                        if init.get('model')!=run['model'] or (init.get('permission_mode')=='always-proceed' if run.get('purpose') in ('discussion','question') else init.get('permission_mode')!='always-proceed'):raise HubError('官方 init 的模型或权限与批准不一致，停止本地进程')
                        conversation=event.get('conversation_id')
                        if run.get('_conversation') and conversation!=run['_conversation']:raise HubError('Antigravity 恢复的会话 ID 不匹配，不自动重试')
                        self.sessions.bind(run,conversation,'inflight')
                        validated=True
                        self.record(run['id'],'antigravity.init',{k:init.get(k) for k in ('cwd','model','permission_mode')})
                        with self.hub.tx():self.hub.db.execute('UPDATE executions SET thread_id=? WHERE id=?',(event.get('conversation_id'),run['id']))
                    elif kind=='step_update':
                        step=event.get('step_update') or {}
                        if (run.get('purpose')=='discussion' or plain_dialogue) and step.get('step_type')=='tool' and step.get('tool_name') not in ('memory','mcp_agent-message-hub_memory','mcp__agent-message-hub__memory'):raise HubError('当前是普通对话，CLI尝试调用工具，已停止本地回合；未恢复项目执行。请通过项目恢复入口继续派工。')
                        if step.get('step_type')=='agent_response' and isinstance(step.get('text_delta'),str):self.public_reply(run,step['text_delta'],phase='正在生成回复')
                        if step.get('step_type')=='tool':self.public_reply(run,phase='正在使用工具：'+str(step.get('tool_name') or '项目工具'))
                        if step.get('step_type') in ('tool','agent_response','checkpoint'):
                            self.record(run['id'],'antigravity.'+step['step_type'],{k:step[k] for k in ('step_index','state','tool_name','text_delta','duration_seconds','usage') if k in step})
                    elif kind=='result':
                        end=event.get('result') or {};usage=end.get('usage');exit_code=None
                        # Persist provider evidence before waiting for local CLI cleanup.
                        self.record(run['id'],'antigravity.final_payload',end)
                        try:exit_code=stream.wait()
                        except subprocess.TimeoutExpired:self.record(run['id'],'antigravity.cleanup_timeout',{'provider_status':end.get('status')})
                        if not validated:
                            if end.get('status')!='SUCCESS' and end.get('error'):
                                status='failed' if end.get('num_turns')==0 else 'uncertain';result='Antigravity：'+str(end['error'])
                                self.record(run['id'],'antigravity.failure',{'code':'provider_rejected_before_init','provider_error':end['error'],'num_turns':end.get('num_turns'),'auto_retry':False});break
                            raise HubError('缺少官方模型/权限 init 验证，不能确认成功')
                        status='completed' if end.get('status')=='SUCCESS' and exit_code in (0,None) else 'failed'
                        if end.get('status') in ('CANCELED','INTERRUPTED'):status='interrupted'
                        result=(end.get('response') or end.get('error') or end.get('status') or '无结果')
                        if status!='completed' and 'Malformed function call' in str(end.get('error','')):
                            self.record(run['id'],'antigravity.failure',{'code':'malformed_function_call','provider_error':end.get('error'),'denied_actions':end.get('denied_actions',[]),'auto_retry':False})
                            result='Antigravity返回空或格式无效的工具调用，本轮失败，未自动重试。原始错误已保存；会话和旧记录保留，不自动清空上下文。\n'+str(end.get('error'))
                        if len(result)>262144:raise HubError('提供商结果超过262144字符，未截断为有效计划')
                        self.record(run['id'],'antigravity.result',{'status':end.get('status'),'exit_code':exit_code,'usage':usage});break
                    elif kind=='eof':raise HubError('CLI 未返回最终 result；不确认成功，不自动重试')
        except Exception as e:status='uncertain' if submitted else 'failed';result=str(e)[:5000]
        finally:
            renew_stop.set();renewal.join(timeout=5)
            if stream:stream.close()
            if status=='completed' and run.get('_manager_policy'):
                from hub.module_sdk import remember_instructions
                remember_instructions(self,run)
            status=self.quota_outcome(run,status,result)
            self.sessions.state(run,status)
            self.clients.pop(run['id'],None)
            with self.hub.tx():
                if self.force_stopped(run):return
                self.hub.db.execute('UPDATE executions SET status=?,finished=?,result=?,usage=? WHERE id=?',(status,time.time(),result,json.dumps(usage),run['id']))
                self.hub.db.execute('UPDATE messages SET status=?,result=?,lease=NULL WHERE id=?',(status,result,run['message_id']))
                self.hub.db.execute("UPDATE agents SET status='idle',active=NULL,heartbeat=? WHERE id=? AND active=?",(time.time(),run['agent'],run['message_id']))
                self.hub.db.execute('UPDATE tasks SET status=?,progress=?,note=? WHERE id=?',('done' if status=='completed' else 'cancelled' if status=='cancelled' else 'blocked',100 if status=='completed' else 0,result,run['task_id']))
                self.hub.audit(run['agent'],'antigravity.'+status,{'run_id':run['id']})
            if status=='waiting_quota' and getattr(self.hub,'automation',None):self.hub.automation.quota_waiting(run)
            if status!='waiting_quota':self.deliver_result(run,status,result)
