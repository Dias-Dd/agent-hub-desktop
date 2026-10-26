"""Public host SDK for every harness module, regardless of installation source."""
import json
import time


def working_directory(value,label='执行工作目录'):
    from pathlib import Path
    from .core import HubError
    try:
        path=Path(value)
        if path.is_absolute() and path.is_dir():return str(path.resolve(strict=True))
    except (TypeError,ValueError,OSError):pass
    raise HubError(label+'已不存在或不是有效目录：'+str(value)+'。请检查项目目录；未启动 Harness，不会自动新建会话或重放任务。')


def runtime_view(host, implementation=None, provider=None):
    """Use a module-owned implementation with the current host grant and scope.

    No constructor runs: creating a view cannot recover/replay active jobs or
    replace the host's queues, locks, sessions, process ownership or identity.
    """
    view = object.__new__(implementation or type(host))
    view.__dict__.update(host.__dict__)
    manifest=getattr(host,'_module_manifest',{})
    settings=manifest.get('settings',{})
    view.config=lambda:{**settings,**host.config()}
    view.environment=dict(__import__('os').environ)
    for name,source in manifest.get('environment',{}).items():
        if source not in view.environment:raise ValueError('缺少模块所需环境变量：'+source)
        view.environment[name]=view.environment[source]
    for name in ('saved_validation','reserve','finalize','guard','definitions','tool','efforts','effort_summary','read_only','execution_instructions','report_instructions','compact_manager_input'):
        if hasattr(host,name):setattr(view,name,getattr(host,name))
    if hasattr(host, 'connection'):
        connection = host.connection()
        manifest = getattr(host, '_module_manifest', {})
        settings = manifest.get('settings', {})
        merged = {**connection, **settings}
        if provider: merged['kind'] = provider
        if manifest.get('api'): merged['api'] = manifest['api']
        merged['module_environment']=manifest.get('environment',{})
        # For a copied CLI module, executable identifies the provider launcher,
        # not this Python entrypoint. An absent launcher uses module discovery.
        if connection.get('kind') == 'custom-harness':
            merged['executable'] = settings.get('executable', '')
        view.connection = lambda: merged
    return view


def request(host, run):
    """The same model-neutral input exposed to Python and JSONL modules."""
    key = host.sessions.key(run)
    with host.hub.tx():
        host.hub.db.execute('CREATE TABLE IF NOT EXISTS custom_harness_context(key TEXT PRIMARY KEY,body TEXT)')
    with host.hub.lock:
        row = host.hub.db.execute('SELECT body FROM custom_harness_context WHERE key=?', (key,)).fetchone()
    old = host.sessions.get(run)
    return {'type':'run','protocol':'hub-module-v1','run_id':run['id'],
        'agent':run['agent'],'model':run['model'],'cwd':run['cwd'],
        'effort':host.efforts().get(run['agent'],'default') if hasattr(host,'efforts') else 'default',
        'permission':'read-only' if host.read_only(run) else run['permission'],
        'prompt':run['prompt'],'system':host.execution_instructions(run)+host.report_instructions(run),
        'history':json.loads(row[0]) if row else [],
        'session_id':old['session_id'] if old else None,
        'tools':host.definitions(run),'timeout_seconds':run['max_seconds']}


def finish(host, run, result):
    """Finalize a simple module result; advanced modules may finish themselves."""
    if isinstance(result, str): result={'status':'completed','text':result}
    if not isinstance(result, dict) or result.get('status')!='completed' or not isinstance(result.get('text'),str) or not result['text'].strip():
        raise ValueError('模块必须明确返回 completed 和非空 text，或自行确认执行终态')
    host.check_latch(run)
    if len(result['text'].encode('utf-8'))>4000000:raise ValueError('模块回复超过 4 MB，未截断为有效结果')
    before=request(host,run)
    session=result.get('session_id')
    if before['session_id'] and session and session!=before['session_id']:
        raise ValueError('模块更换了原会话 ID，未确认上下文延续')
    if session:
        if not isinstance(session,str) or not session or len(session)>500:raise ValueError('session_id 无效')
        host.sessions.bind(run,session,cwd=run['cwd'])
    with host.hub.tx():
        host.hub.db.execute('INSERT OR REPLACE INTO custom_harness_context VALUES(?,?)',
            (host.sessions.key(run),json.dumps(before['history']+[{'role':'user','content':run['prompt']},{'role':'assistant','content':result['text']}],ensure_ascii=False)))
    host.sessions.state(run,'completed')
    finalize(host,run,'completed',result['text'])


def finalize(host,run,status,text):
    """Shared state delivery; provider protocol code does not belong here."""
    with host.hub.tx():
        if host.force_stopped(run):return
        host.hub.db.execute('UPDATE executions SET status=?,finished=?,result=? WHERE id=?',(status,time.time(),text,run['id']))
        host.hub.db.execute('UPDATE messages SET status=?,result=?,lease=NULL WHERE id=?',(status,text,run['message_id']))
        host.hub.db.execute("UPDATE agents SET status='idle',active=NULL,heartbeat=? WHERE id=? AND active=?",(time.time(),run['agent'],run['message_id']))
        host.hub.db.execute('UPDATE tasks SET status=?,progress=?,note=? WHERE id=?',('done' if status=='completed' else 'blocked',100 if status=='completed' else 0,text,run['task_id']))
    host.deliver_result(run,status,text)


def host_resource(name):
    """Locate host-owned resources independently of a module's folder."""
    import hub
    from pathlib import Path
    return Path(hub.__file__).resolve().parent / name


def instructions(context,run,style='default',**options):
    from . import execution_policy as policy
    if style=='tool_agent':return policy.tool_agent_instructions(context,run,options.get('project'),options.get('read_only',False),options.get('dialogue',False))
    if style=='tool_api':return policy.api_instructions(context,run,options.get('project'),options.get('manager',False))
    return policy.execution_instructions(context,run)+policy.report_instructions(context,run)


def persona_prefix(agent,role,manager,model):
    from .execution_policy import persona_prefix as build
    return build(agent,role,manager,model)


def workspace_notice(target_cwd,session_cwd=None):
    from .execution_policy import workspace_notice as build
    return build(target_cwd,session_cwd)


def remember_instructions(context,run):
    from .execution_policy import remember_instructions as remember
    return remember(context,run)
