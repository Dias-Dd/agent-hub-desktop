"""Host-owned authorization and tools, shared by all module protocols."""
import json,os,subprocess,tempfile,time
from pathlib import Path
from .core import HubError
from .mcp import TOOLS
from .process_job import ProcessJob
from .manager_identity import resolve as project_manager
def guard(self,run):
    self.check_latch(run)
    with self.hub.lock:
        state=self.hub.db.execute('SELECT status,stop_requested FROM executions WHERE id=?',(run['id'],)).fetchone()
        row=self.hub.db.execute('SELECT w.body FROM workflows w JOIN workflow_steps s ON s.workflow=w.id WHERE s.task=?',(run['task_id'],)).fetchone()
    cfg=self.config()
    if not state or state['status']!='running' or state['stop_requested'] or self.stop_event.is_set():raise HubError('执行已停止；不发送下一次请求或运行工具')
    if time.time()>run['started']+run['max_seconds']:raise HubError('任务时间预算已到：本轮最长 '+str(run['max_seconds'])+' 秒；平台已停止本轮，并非模型额度耗尽。会话保留，请经理核查后续接。')
    if cfg['grant_id']!=run['grant_id'] or not cfg['enabled']:raise HubError('接入授权已变化')
    if row:
        project=json.loads(row[0])
        if not (project.get('status')=='completed' and project.get('completion',{}).get('run_id')==run['id']):self.hub.workflows.valid(project)


def definitions(self,run):
    with self.hub.lock:step=self.hub.db.execute('SELECT 1 FROM workflow_steps WHERE task=?',(run['task_id'],)).fetchone()
    if not step and run.get('purpose') in ('question','discussion'):
        from .long_term_memory import is_manager
        return [{'type':'function','function':{'name':n,'description':d,'parameters':s}} for n,d,s in TOOLS if n=='memory' and is_manager(self.hub,run)]
    w,context=self.hub.workflows.run_context(run['agent'],run['id']) if step else ({},{'step_kind':'work'})
    manager=project_manager(self.hub,record=w)==run['agent'] and context['step_kind'] in ('plan','review') and run.get('purpose')=='task' and not run.get('_read_only')
    allowed={'project_vm','project_git','send','report_result','project_status','project_mailbox','schedule_wake','timer_list','timer_cancel','browser_render','publish_artifact'}
    from hub.user_followup import direct
    if direct(self.hub,run):
        from hub.user_followup import manager as followup_manager
        allowed={'project_vm','publish_artifact'}
        if followup_manager(self.hub,run):allowed|={'project_assign','project_status','project_complete','project','project_stop_task','project_queue'}
    if run.get('purpose')=='alignment':allowed={n for n,_,_ in TOOLS}
    if manager:allowed|={'project','project_assign','project_complete','project_set_role','project_cancel_task','project_stop_task','project_queue','project_schedule_wake'}
    from .long_term_memory import is_manager
    if is_manager(self.hub,run):allowed.add('memory')
    result=[{'type':'function','function':{'name':n,'description':d,'parameters':s}} for n,d,s in TOOLS if n in allowed]
    for name,description,props,required in [('read_file','读取项目内UTF-8文件',{'path':{'type':'string'}},['path']),('write_file','写入项目内文件（仅实施任务）',{'path':{'type':'string'},'content':{'type':'string'}},['path','content']),('run_command','按已确认完全访问权限运行本机命令；不是沙箱',{'command':{'type':'string'}},['command'])]:
        if (name=='write_file' and run.get('purpose')=='question') or (name=='run_command' and (run.get('purpose')=='question' or run.get('_read_only'))):continue
        if name=='run_command' and run['permission']!='full':continue
        if name=='write_file' and run.get('_read_only'):continue
        result.append({'type':'function','function':{'name':name,'description':description,'parameters':{'type':'object','properties':props,'required':required,'additionalProperties':False}}})
    return result


def tool(self,run,name,args,allowed):
    self.guard(run)
    if run.get('purpose')=='alignment' and name!='project_vm' and name in {n for n,_,_ in TOOLS}:raise HubError('需求对齐阶段平台工具尚未启用，请由用户点击开始计划')
    readonly=self.read_only(run) if hasattr(self,'read_only') else run.get('purpose') in ('discussion','question')
    if readonly and name in ('write_file','run_command'):raise HubError('本轮只读，不能执行写入或命令工具')
    if name not in allowed:raise HubError('本轮未授权该工具')
    if name=='memory':
        from .long_term_memory import action
        return action(self.hub,run['agent'],run_id=run['id'],**args)
    if name in ('read_file','write_file'):
        root=Path(run['cwd']).resolve();path=(root/args['path']).resolve()
        if not path.is_relative_to(root):raise HubError('文件工具只允许当前项目目录')
        if name=='read_file':return path.read_text(encoding='utf-8')[:12000]
        if not isinstance(args.get('content'),str) or len(args['content'])>100000:raise HubError('写入内容过长')
        with self.hub.lock:
            self.guard(run)
            path.parent.mkdir(parents=True,exist_ok=True);path.write_text(args['content'],encoding='utf-8')
        return {'written':str(path)}
    if name=='run_command':
        command=args.get('command')
        if not isinstance(command,str) or not command.strip() or len(command)>6000:raise HubError('命令无效')
        env={k:v for k,v in os.environ.items() if not any(x in k.upper() for x in ('KEY','TOKEN','SECRET','PASSWORD')) and not k.startswith('HUB_')}
        argv=['powershell.exe','-NoProfile','-NonInteractive','-Command',command] if os.name=='nt' else ['/bin/sh','-c',command]
        with tempfile.TemporaryFile() as out:
            proc=None;job=None
            try:
                with self.hub.lock:
                    self.guard(run)
                    proc=subprocess.Popen(argv,cwd=run['cwd'],env=env,stdout=out,stderr=out,start_new_session=os.name!='nt',creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                    job=ProcessJob(proc);self.track_client(run,type('Command',(),{'proc':proc,'job':job})())
                deadline=time.time()+min(60,max(1,run['started']+run['max_seconds']-time.time()))
                while proc.poll() is None:
                    self.guard(run)
                    if time.time()>deadline:raise HubError('命令超时，已停止本地进程树')
                    time.sleep(.2)
            finally:
                if job:job.close()
                if proc and proc.poll() is None:proc.kill()
                if proc:proc.wait()
                self.clients.pop(run['id'],None)
            out.seek(0);return {'exit_code':proc.returncode,'output':out.read(12000).decode('utf-8',errors='replace')}
    if name in ('browser_render','project_vm'):
        value=getattr(self.hub.automation,name)(run['agent'],run_id=run['id'],**args);image=value.pop('image_data',None)
        if image or name=='browser_render':value['image_delivery']='当前API文本工具通道只返回截图链接与元数据，不能声称已查看图像；MCP图像通道可返回图片。'
        return value
    if name in ('project_vm','schedule_wake','timer_list','timer_cancel','publish_artifact'):return getattr(self.hub.automation,name)(run['agent'],run_id=run['id'],**args)
    if name=='project':return self.hub.workflows.project_progress(run['agent'],run_id=run['id'],**args)
    if name=='send':return self.hub.coordination.send(run['agent'],**args)
    return getattr(self.hub.workflows,name)(run['agent'],run_id=run['id'],**args)
