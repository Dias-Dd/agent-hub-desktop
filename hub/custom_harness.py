"""User-owned harness adapters. Discovery reads JSON only; never imports user code."""
import hashlib,json,os,re,shutil,sys,time,subprocess,queue,threading
from pathlib import Path
from .core import HubError
from .cli_paths import which,child_environment
from .process_job import ProcessJob


def discover(directory):
 from .harness_adapters import prepare_layout
 root=Path(directory)/'adapters'/'custom'
 try:root=prepare_layout(directory,install_builtins=False)
 except OSError as e:return [],[{'file':str(root),'error':str(e)}]
 examples=Path(__file__).with_name('adapter_examples')
 if examples.is_dir():
  for sample in examples.iterdir():
   dest=root/sample.name
   if sample.is_file() and not dest.exists():
    try:dest.write_bytes(sample.read_bytes())
    except OSError:pass
 found=[];errors=[];ids=set();duplicates=set()
 for path in sorted(root.glob('*/adapter.json')):
  try:
   if path.stat().st_size>131072:raise ValueError('配置文件过大')
   data=json.loads(path.read_text(encoding='utf-8-sig'))
   if not isinstance(data,dict):raise ValueError('配置必须是 JSON 对象')
   ident=data.get('id','')
   if type(data.get('version'))!=int or data.get('version')!=1 or data.get('protocol') not in ('hub-jsonl-v1','hub-module-v1') or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,47}',ident):raise ValueError('version/protocol/id 无效')
   if ident in ids:
    duplicates.add('custom-'+ident)
    raise ValueError('适配器 ID 重复；同 ID 的全部接入已停用，请修改其中一个 ID')
   name=data.get('name');argv=data.get('command')
   if not isinstance(name,str) or not name.strip() or len(name)>120:raise ValueError('name 无效')
   protocol=data['protocol']
   if protocol=='hub-module-v1':
    entry=data.get('entrypoint','adapter.py')
    if not isinstance(entry,str) or Path(entry).name!=entry or not entry.endswith('.py') or not (path.parent/entry).is_file():raise ValueError('模块 entrypoint 必须是目录内存在的 Python 文件')
    exe=str((path.parent/entry).resolve());argv=[]
   else:
    if not isinstance(argv,list) or not argv or not all(isinstance(x,str) and x and len(x)<4096 for x in argv):raise ValueError('command 必须是参数数组')
    if any('${python}' in x for x in argv) and getattr(sys,'frozen',False) and not (which('python3') or which('python')):raise ValueError('此适配器需要安装 Python 或改用自带 EXE')
    argv=[x.replace('${adapter_dir}',str(path.parent.resolve())).replace('${python}',(which('python3') or which('python')) or sys.executable) for x in argv]
    exe=which(argv[0]) or str((path.parent/argv[0]).resolve())
    if not Path(exe).is_file():raise ValueError('找不到启动程序：'+argv[0])
    argv[0]=exe
   models=data.get('models',[]);caps=data.get('capabilities',{})
   if not isinstance(caps,dict) or any(k not in ('tools','resume','streaming') or type(v)!=bool for k,v in caps.items()):raise ValueError('capabilities 仅支持 tools/resume/streaming 布尔值')
   if not isinstance(models,list) or (not models and protocol=='hub-jsonl-v1'):raise ValueError('至少声明一个模型，Python 模块也可通过 probe 返回目录')
   catalog=[];model_ids=set()
   for m in models:
    if not isinstance(m,dict) or not isinstance(m.get('id'),str) or not m['id'] or len(m['id'])>200:raise ValueError('模型 id 无效')
    if m['id'] in model_ids:raise ValueError('模型 id 重复')
    model_ids.add(m['id'])
    efforts=m.get('efforts',['default'])
    if not isinstance(efforts,list) or not efforts or any(not isinstance(x,str) or not x or len(x)>30 for x in efforts):raise ValueError('模型档位无效')
    if 'name' in m and (not isinstance(m['name'],str) or not m['name'] or len(m['name'])>200):raise ValueError('模型 name 无效')
    catalog.append({'id':m['id'],'name':m.get('name',m['id']),'efforts':efforts,'source':'user_adapter_manifest'})
   env=data.get('environment',{})
   if not isinstance(env,dict) or any(not isinstance(k,str) or not isinstance(v,str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',k) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',v) for k,v in env.items()):raise ValueError('environment 必须是环境变量引用映射')
   config={'protocol':protocol,'manifest_data':data,'command':argv,'capabilities':caps,'environment':env,'directory':str(path.parent.resolve()),'manifest':str(path.resolve())}
   found.append({'id':'custom-'+ident,'name':name,'kind':'custom-harness','models':catalog,'adapter':config,'executable':exe,'manifest_hash':hashlib.sha256(path.read_bytes()).hexdigest()})
   ids.add(ident)
  except (ValueError,OSError,TypeError) as e:errors.append({'file':str(path),'error':str(e)})
 return [entry for entry in found if entry['id'] not in duplicates],errors


def execute(runtime,run):
 if runtime.connection().get('adapter',{}).get('protocol')=='hub-module-v1':
  from .module_loader import execute as execute_module
  return execute_module(runtime,run,runtime.connection()['adapter']['directory'])
 run=dict(run);run['started']=time.time();proc=None;job=None;status='failed';result='';parts=[];session=None;reader_stop=threading.Event();secrets=[]
 try:
  runtime.guard(run)
  from .memory_notices import attach
  run=attach(runtime.hub,run)
  connection=runtime.connection()
  current=next((c for c in discover(runtime.hub.directory)[0] if c['id']==connection['id']),None)
  if not current or current['manifest_hash']!=connection.get('manifest_hash'):raise HubError('适配器配置已变化或不可用，请刷新自定义接入后重试；未运行脚本')
  config=connection['adapter']
  if run['permission']!='full':raise HubError('自定义脚本不提供操作系统沙箱；需明确启用完全访问')
  run['_read_only']=runtime.read_only(run)
  key=runtime.sessions.key(run)
  with runtime.hub.tx():runtime.hub.db.execute('CREATE TABLE IF NOT EXISTS custom_harness_context(key TEXT PRIMARY KEY,body TEXT)')
  with runtime.hub.lock:previous=runtime.hub.db.execute('SELECT body FROM custom_harness_context WHERE key=?',(key,)).fetchone()
  history=json.loads(previous[0]) if previous else []
  old=runtime.sessions.get(run) if config['capabilities'].get('resume') else None
  definitions=runtime.definitions(run) if config['capabilities'].get('tools') else []
  allowed={x['function']['name'] for x in definitions}
  envelope={'type':'run','protocol':'hub-jsonl-v1','run_id':run['id'],'timeout_seconds':run['max_seconds'],'agent':run['agent'],'model':run['model'],'effort':runtime.efforts()[run['agent']],'cwd':run['cwd'],'permission':'read-only' if run['_read_only'] else 'full','prompt':run['prompt'],'system':runtime.execution_instructions(run)+runtime.report_instructions(run),'history':history,'session_id':old['session_id'] if old else None,'session_cwd':old.get('cwd',run['cwd']) if old else run['cwd'],'tools':definitions}
  if len(json.dumps(envelope,ensure_ascii=False).encode('utf-8'))>4000000:raise HubError('自定义适配器上下文超过 4 MB；上下文保留，不自动截断')
  env=child_environment(os.environ)
  for name,source in config.get('environment',{}).items():
   if source not in os.environ:raise HubError('缺少适配器所需环境变量：'+source)
   env[name]=os.environ[source]
   if env[name] and any(word in (name+' '+source).upper() for word in ('KEY','TOKEN','SECRET','PASSWORD')):secrets.append(env[name])
  env.update(PYTHONIOENCODING='utf-8',PYTHONUTF8='1')
  from .integrations import command
  proc=subprocess.Popen(command(config['command']),cwd=run['cwd'],env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',start_new_session=os.name!='nt',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  job=ProcessJob(proc);events=queue.Queue(maxsize=128);outgoing=queue.Queue(maxsize=16)
  def emit(value):
   while not reader_stop.is_set():
    try:events.put(value,timeout=.2);return
    except queue.Full:continue
  def read():
   try:
    while True:
     line=proc.stdout.readline(4000002)
     if not line:break
     if len(line.encode('utf-8'))>4000000:emit({'type':'error','message':'适配器输出帧超过限制'});break
     try:emit(json.loads(line))
     except ValueError:emit({'type':'error','message':'标准输出必须逐行输出 JSON；日志请写 stderr'});break
   finally:emit(None)
  def drain():
   while proc.stderr.read(4096):pass
  threading.Thread(target=read,daemon=True).start();threading.Thread(target=drain,daemon=True).start()
  def send(value):
   try:outgoing.put(json.dumps(value,ensure_ascii=False)+'\n',timeout=.2)
   except queue.Full:raise HubError('适配器未读取输入，停止本轮')
  def writer():
   while not reader_stop.is_set():
    try:line=outgoing.get(timeout=.2)
    except queue.Empty:continue
    try:proc.stdin.write(line);proc.stdin.flush()
    except (OSError,ValueError):emit({'type':'error','message':'适配器输入通道已关闭'});return
  threading.Thread(target=writer,daemon=True).start()
  send(envelope);output_size=0;deadline=time.monotonic()+run['max_seconds'];final=None
  while time.monotonic()<deadline:
   runtime.guard(run)
   try:event=events.get(timeout=.2)
   except queue.Empty:continue
   if event is None:raise HubError('适配器未发送最终 result 就退出；不会视为成功')
   if not isinstance(event,dict):raise HubError('适配器事件必须为 JSON 对象')
   kind=event.get('type')
   if kind=='text':
    chunk=event.get('text','')
    if not isinstance(chunk,str):raise HubError('text 必须为字符串')
    output_size+=len(chunk.encode('utf-8'))
    if output_size>4000000:raise HubError('适配器回复超过 4 MB，停止本轮')
    for secret in secrets:chunk=chunk.replace(secret,'[已隐藏]')
    parts.append(chunk);runtime.public_reply(run,chunk,phase='自定义适配器正在回复')
   elif kind=='tool_call':
    call_id=event.get('id');name=event.get('name');args=event.get('arguments',{})
    if not isinstance(args,dict):raise HubError('工具参数必须为对象')
    try:output=runtime.tool(run,name,args,allowed);reply={'type':'tool_result','id':call_id,'result':output}
    except Exception as e:reply={'type':'tool_result','id':call_id,'error':str(e)}
    runtime.record(run['id'],'custom_harness.tool',{'name':name,'id':call_id,'failed':'error' in reply});send(reply)
   elif kind=='result':final=event;break
   elif kind=='error':raise HubError(str(event.get('message') or '适配器失败'))
   else:raise HubError('未知适配器事件：'+str(kind))
  if final is None:raise HubError('适配器本轮超时；未确认完成')
  result=final.get('text') if isinstance(final.get('text'),str) else ''.join(parts)
  if final.get('status')!='completed' or not result.strip():raise HubError('适配器未确认完成或回复为空')
  for secret in secrets:result=result.replace(secret,'[已隐藏]')
  session=final.get('session_id')
  if config['capabilities'].get('resume') and (not isinstance(session,str) or not session or len(session)>500):raise HubError('声明 resume 的适配器必须返回 session_id')
  if old and session!=old['session_id']:raise HubError('适配器更换了恢复中的原生会话 ID；未确认上下文延续，不视为完成')
  runtime.guard(run)
  with runtime.hub.tx():runtime.hub.db.execute('INSERT OR REPLACE INTO custom_harness_context VALUES(?,?)',(key,json.dumps(history+[{'role':'user','content':run['prompt']},{'role':'assistant','content':result}],ensure_ascii=False)))
  if session:runtime.sessions.bind(run,session,cwd=run['cwd'])
  status='completed';runtime.record(run['id'],'custom_harness.result',{'protocol':'hub-jsonl-v1','capabilities':config['capabilities'],'session':session})
 except Exception as e:
  status='interrupted' if '停止' in str(e) or '取消' in str(e) else 'failed';result=str(e)
 finally:
  reader_stop.set()
  for secret in secrets:result=result.replace(secret,'[已隐藏]')
  if job:job.close()
  if proc:
   if proc.poll() is None:proc.kill()
   try:proc.wait(timeout=5)
   except subprocess.TimeoutExpired:pass
   for stream in (proc.stdin,proc.stdout,proc.stderr):
    if stream:
     try:stream.close()
     except OSError:pass
  runtime.sessions.state(run,status);runtime.finalize(run,status,result)
