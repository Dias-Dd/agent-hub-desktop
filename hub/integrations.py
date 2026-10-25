from .manager_identity import independent_reviewer
from .manager_identity import resolve as project_manager
"""Persistent connection and agent registry. Catalog probes never run inference."""
import json,os,re,secrets,shutil,subprocess,sys,time,threading
from contextlib import contextmanager
from pathlib import Path
from .core import HubError,uid,text
from .codex_runtime import CodexRuntime,AppServer,codex_executable
from .antigravity import AntigravityRuntime,executable as agy_executable
from .deepseek_runtime import DeepSeekRuntime

from .harness_adapters import builtin_catalog, custom_directory, prepare_layout
_BUILTINS=builtin_catalog()
KINDS={k:(v['name'],v['efforts']) for k,v in _BUILTINS.items()}
KINDS['custom-harness']=('自定义 Harness',['default'])
BASES={k:(v['api']['base_url'],v['api']['key_environment']) for k,v in _BUILTINS.items() if 'api' in v}
ACTIVE=('queued','running','interrupting','waiting_quota')

def locate(kind,supplied=''):
 from importlib import import_module
 return import_module('hub.builtin_adapters._shared.discovery').locate(kind,supplied)


def command(argv):
 # Batch launchers need cmd on Windows; no user-supplied shell text is accepted.
 if Path(argv[0]).suffix.lower() in ('.mjs','.cjs','.js'):return [shutil.which('node') or 'node',*argv]
 if Path(argv[0]).is_file() and not Path(argv[0]).suffix:
  with open(argv[0],'rb') as source:header=source.read(64)
  if header.startswith(b'#!') and b'node' in header:return [shutil.which('node') or 'node',*argv]
 if os.name=='nt' and Path(argv[0]).suffix.lower() in ('.cmd','.bat'):
  launcher=Path(argv[0]);base=launcher.parent.resolve()
  for match in re.finditer(r'%dp0%[\\/]+(node_modules[\\/][^"\r\n]+)',launcher.read_text(encoding='utf-8',errors='replace')):
   target=(base/match.group(1)).resolve()
   if target.is_file() and target.is_relative_to(base/'node_modules'):
    if target.suffix.lower()=='.exe':return [str(target),*argv[1:]]
    if target.suffix.lower() in ('.js','.mjs','.cjs') or (not target.suffix and target.read_bytes()[:128].startswith(b'#!') and b'node' in target.read_bytes()[:128]):return [shutil.which('node') or 'node',str(target),*argv[1:]]
  if any(re.search(r'["&|<>^%!\r\n]',value) for value in argv):raise HubError('此批处理启动器无法安全传递参数，请指定原生 EXE 或 Node 入口文件')
  return ['cmd.exe','/d','/s','/c',subprocess.list2cmdline(argv)]
 return argv

class Integrations:
 def __init__(self,server):
  self.server=server;self.hub=server.hub;self.lock=threading.RLock();self.instances={};self.running=False
  with self.hub.tx():
   self.hub.db.execute('CREATE TABLE IF NOT EXISTS integration_connections(id TEXT PRIMARY KEY,body TEXT)')
   self.hub.db.execute('CREATE TABLE IF NOT EXISTS agent_profiles(id TEXT PRIMARY KEY,body TEXT)')
   self.hub.db.execute('CREATE TABLE IF NOT EXISTS agent_change_queue(project_id TEXT,agent TEXT,before_json TEXT,after_json TEXT,first_at REAL,updated REAL,version TEXT,PRIMARY KEY(project_id,agent))')
   if not self.hub.db.execute('SELECT 1 FROM integration_connections').fetchone():
    self.hub.db.execute('INSERT INTO integration_connections VALUES(?,?)',('deepseek-default',json.dumps({'id':'deepseek-default','name':'DeepSeek Harness','kind':'deepseek-harness','legacy':True,'enabled':True,'models':[{'id':'deepseek-flash','efforts':KINDS['deepseek-harness'][1]}],'quota':{'source':'unknown','remaining':None,'resets_at':None}})))
    for a in self.hub.db.execute('SELECT * FROM agents').fetchall():
     self.hub.db.execute('INSERT INTO agent_profiles VALUES(?,?)',(a['id'],json.dumps({'id':a['id'],'name':a['id'],'connection_id':'deepseek-default','model':'deepseek-flash','effort':server.deepseek.efforts().get(a['id'],'high'),'role':a['role'],'enabled':bool(a['enabled'])},ensure_ascii=False)))
   for kind in KINDS:
    if kind in ('deepseek-harness','custom-harness'):continue
    preset={'id':kind+'-local','name':KINDS[kind][0],'kind':kind,'enabled':False,'cwd':server.deepseek.config()['cwd'],'permission':'workspace' if kind=='codex' or kind.endswith('-api') else 'full','call_limit':0 if kind=='deepseek-api' else 1000,'executable':'','key_env':BASES.get(kind,('',''))[1],'models':[],'quota':{'source':'unknown','remaining':None,'resets_at':None}}
    self.hub.db.execute('INSERT OR IGNORE INTO integration_connections VALUES(?,?)',(preset['id'],json.dumps(preset,ensure_ascii=False)))
  with self.hub.tx():
   for c in self.rows('integration_connections'):
    if c.get('kind')=='deepseek-harness' and c.get('name')=='现有 DeepSeek Harness':
     c['name']='DeepSeek Harness'
     self.hub.db.execute('UPDATE integration_connections SET body=? WHERE id=?',(json.dumps(c,ensure_ascii=False),c['id']))
  prepare_layout(self.hub.directory)
  self.adapter_scan_at=0;self.adapter_errors=[]
  self.scan_adapters(force=True)
  with self.hub.tx():
   for c in self.rows('integration_connections'):
    if c['kind'] in KINDS:continue
    c['enabled']=False;self.put('integration_connections',c)
    for a in self.rows('agent_profiles'):
     if a['connection_id']==c['id']:
      a['enabled']=False;self.put('agent_profiles',a)
      self.hub.db.execute('UPDATE agents SET enabled=0 WHERE id=?',(a['id'],))
  self.migrate_codebuddy()
  self.align_antigravity_efforts()
  self.apply()
  from .connection_tests import ConnectionTests
  self.connection_tests=ConnectionTests(self)
  from .model_availability import restore
  restore(self.hub)

 def scan_adapters(self,force=False):
  if not force and time.monotonic()<self.adapter_scan_at:return
  self.adapter_scan_at=time.monotonic()+5
  from .custom_harness import discover
  found,self.adapter_errors=discover(self.hub.directory)
  with self.hub.tx():
   for entry in found:
    old=next((c for c in self.rows('integration_connections') if c['id']==entry['id']),{})
    workspace=self.hub.directory/'adapter-workspaces'/entry['id'];workspace.mkdir(parents=True,exist_ok=True)
    value={**old,**entry,'adapter_available':True,'enabled':old.get('enabled',False),'cwd':old.get('cwd',str(workspace.resolve())),'permission':'full','call_limit':old.get('call_limit',0),'quota':old.get('quota',{'source':'unknown','remaining':None,'resets_at':None})}
    if entry['adapter'].get('protocol')=='hub-module-v1' and old.get('models') and (not entry['models'] or (old.get('manifest_hash')==entry['manifest_hash'] and old.get('probed_at'))):value['models']=old['models']
    if value!=old:self.put('integration_connections',value)
   for old in self.rows('integration_connections'):
    if old['kind']=='custom-harness' and old['id'] not in {c['id'] for c in found} and (old.get('enabled') or old.get('adapter_available')):
     old['enabled']=False;old['adapter_available']=False;self.put('integration_connections',old)

 def adapters(self,actor,open_folder=False):
  self.hub.require(actor,{'user'});self.scan_adapters(force=True)
  folder=custom_directory(self.hub.directory)
  if open_folder:os.startfile(str(folder.resolve()))
  self.apply()
  return {'directory':str(folder.resolve()),'parent_directory':str(folder.parent.resolve()),'builtin_directory':str((folder.parent/'builtin').resolve()),'errors':self.adapter_errors,'inference_sent':False}

 def migrate_codebuddy(self):
  # Keep the stable connection/Agent IDs and authorization. Only change launcher.
  with self.hub.tx():
   for c in self.rows('integration_connections'):
    if c['kind']!='workbuddy' or c.get('transport')=='codebuddy-standalone':continue
    c['previous_workbuddy_catalog']={k:c[k] for k in ('models','client_models','candidate_models','executable') if k in c}
    c.update(transport='codebuddy-standalone',name='CodeBuddy CLI',models=[],client_models=[],candidate_models=[],catalog_status='not_refreshed',catalog_complete=False,probed_at=None,verification='已切换官方独立 CodeBuddy CLI；待刷新目录和用户推理测试',probe_detail='不再启动 WorkBuddy 客户端自带的精简 CLI')
    if 'codebuddy-lite-wb' in c.get('executable','').lower():c['executable']=''
    self.put('integration_connections',c)
    self.hub.audit('supervisor','integration.codebuddy_migrated',{'connection':c['id'],'agents_preserved':True,'inference_sent':False})
 def align_antigravity_efforts(self):
  from .antigravity import model_efforts
  with self.hub.tx():
   ids=set()
   for c in self.rows('integration_connections'):
    if c['kind']!='antigravity':continue
    ids.add(c['id'])
    for item in c.get('models',[]):item['efforts']=model_efforts(item['id'])
    self.put('integration_connections',c)
   for a in self.rows('agent_profiles'):
    if a['connection_id'] not in ids:continue
    bound=model_efforts(a['model'])[0]
    if bound!='default' and a['effort']!=bound:
     before=dict(a);a['effort']=bound;self.put('agent_profiles',a);self.queue_change(a['id'],before,a)
     self.hub.audit('supervisor','integration.antigravity_effort_corrected',{'agent':a['id'],'model':a['model'],'from':before['effort'],'to':bound,'inference_sent':False})
 @contextmanager
 def change_tx(self):
  with self.hub.lock:
   if self.hub.db.in_transaction:yield
   else:
    with self.hub.tx():yield
 def queue_change(self,agent,before,after,project_id=None):
  if before==after:return
  with self.change_tx():
   projects={project_id} if project_id else set()
   if not project_id:
    if self.hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='hub_projects'").fetchone():projects.update(r[0] for r in self.hub.db.execute('SELECT id FROM hub_projects'))
    for table in ('workflows','planning_sessions'):
     if self.hub.db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(table,)).fetchone():projects.update(r[0] for r in self.hub.db.execute("SELECT DISTINCT json_extract(body,'$.project_id') FROM "+table) if r[0])
   for project in projects:
    # Global additions are available for selection, never project authorization.
    if before is None:continue
    if after.get('enabled',True) and before.get('project_opt_in') and agent not in ('__manager__','__roster__'):
     roster=set()
     for table in ('workflows','planning_sessions'):
      if self.hub.db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(table,)).fetchone():
       for entry in self.hub.db.execute("SELECT body FROM "+table+" WHERE json_extract(body,'$.project_id')=?",(project,)):
        item=json.loads(entry[0]);roster.update(item.get('agents',item.get('options',{}).get('agents',[])));roster.add(project_manager(self.hub,record=item))
     if self.hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='project_options'").fetchone():
      saved=self.hub.db.execute('SELECT body FROM project_options WHERE project_id=?',(project,)).fetchone()
      if saved:roster.update(json.loads(saved[0]).get('agents',[]))
     if agent not in roster:continue
    old=self.hub.db.execute('SELECT before_json,first_at FROM agent_change_queue WHERE project_id=? AND agent=?',(project,agent)).fetchone()
    initial=json.loads(old[0]) if old else before
    if initial==after or (initial is None and not after.get('enabled',True)):
     self.hub.db.execute('DELETE FROM agent_change_queue WHERE project_id=? AND agent=?',(project,agent));continue
    self.hub.db.execute('INSERT OR REPLACE INTO agent_change_queue VALUES(?,?,?,?,?,?,?)',(project,agent,json.dumps(initial,ensure_ascii=False),json.dumps(after,ensure_ascii=False),old[1] if old else time.time(),time.time(),uid()))
 def changes(self,project_id):
  with self.hub.lock:return [dict(r) for r in self.hub.db.execute('SELECT * FROM agent_change_queue WHERE project_id=? ORDER BY first_at,agent',(project_id,))]
 def change_text(self,rows):
  lines=[]
  labels={'name':'名称','model':'模型','connection_id':'接入','effort':'档位','role':'角色','manager':'经理'}
  for row in rows:
   before=json.loads(row['before_json']);after=json.loads(row['after_json']);name=after.get('name',row['agent'])
   if row['agent']=='__roster__':lines.append('允许调度的成员：'+('、'.join(after.get('agents',[])) or '仅经理本人'));continue
   if row['agent']=='__manager__':lines.append('经理：'+before['manager']+' → '+after['manager']);continue
   if not after.get('enabled',True):lines.append('移除 '+name+'（'+row['agent']+'）');continue
   if before is None or not before.get('enabled',True):lines.append('新增 '+name+'（'+row['agent']+'）：'+after['model']+'，档位 '+after['effort']+'，接入 '+after['connection_id']);continue
   fields=[label+' '+str(before.get(key,'未知'))+' → '+str(after.get(key,'未知')) for key,label in labels.items() if before.get(key)!=after.get(key)]
   if fields:lines.append(name+'（'+row['agent']+'）：'+'；'.join(fields))
  return 'Agent 配置更新（合并）：\n'+'\n'.join(lines)+'\n以最新配置为准；当前执行不打断，新接入仍须项目授权。' if lines else ''
 def acknowledge_changes(self,rows):
  with self.change_tx():
   for row in rows:self.hub.db.execute('DELETE FROM agent_change_queue WHERE project_id=? AND agent=? AND version=?',(row['project_id'],row['agent'],row['version']))
 def flush_changes(self,w,force=False):
  project=w.get('project_id') or w['id']
  with self.change_tx():
   rows=self.changes(project)
   if not rows:return
   now=time.time()
   if not force and now-max(r['updated'] for r in rows)<5 and now-min(r['first_at'] for r in rows)<20:return
   body=self.change_text(rows)
   if body:
    from .notice_batch import queue
    queue(self.hub,w,self.server.workflows.manager(w),body,'agent_config_changed')
   self.acknowledge_changes(rows)
 def patrol_changes(self):
  # Inactive projects retain their changes without spending a manager turn.
  with self.server.workflows.lock:
   with self.hub.lock:
    if not self.hub.db.execute('SELECT 1 FROM agent_change_queue LIMIT 1').fetchone():return
    pending={r[0] for r in self.hub.db.execute('SELECT DISTINCT project_id FROM agent_change_queue')}
    latest=[json.loads(r[0]) for r in self.hub.db.execute('SELECT body FROM workflows ORDER BY rowid DESC')]
   seen=set()
   for w in latest:
    project=w.get('project_id') or w['id']
    if project in seen:continue
    seen.add(project)
    if project in pending and w['status'] in ('active','needs_attention') and self.project_is_running(project):self.flush_changes(w)

 def project_is_running(self,project_id):
  with self.hub.lock:
   return bool(self.hub.db.execute("SELECT 1 FROM executions e JOIN tasks t ON t.id=e.task_id WHERE t.project_id=? AND e.purpose='task' AND e.status IN ('running','interrupting') LIMIT 1",(project_id,)).fetchone())
 def rows(self,table):
  with self.hub.lock:return [json.loads(r[0]) for r in self.hub.db.execute('SELECT body FROM '+table+' ORDER BY rowid')]
 def get(self,table,ident):
  with self.hub.lock:r=self.hub.db.execute('SELECT body FROM '+table+' WHERE id=?',(ident,)).fetchone()
  if not r:raise HubError('接入配置不存在')
  return json.loads(r[0])
 def put(self,table,value):self.hub.db.execute('INSERT OR REPLACE INTO '+table+' VALUES(?,?)',(value['id'],json.dumps(value,ensure_ascii=False)))
 def busy(self,agents):
  if not agents:return False
  marks=','.join('?' for _ in agents)
  with self.hub.lock:return bool(self.hub.db.execute("SELECT 1 FROM executions WHERE agent IN ("+marks+") AND status IN ('queued','running','interrupting','waiting_quota')",agents).fetchone())
 def manager_projects(self):
  result={}
  for row in self.hub.db.execute('SELECT body FROM workflows').fetchall():
   w=json.loads(row[0])
   if w.get('status') not in ('active','paused','blocked','needs_attention'):continue
   project=w.get('project_id') or w['id'];name=project[:8]
   if self.hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='hub_projects'").fetchone():
    record=self.hub.db.execute('SELECT name FROM hub_projects WHERE id=?',(project,)).fetchone()
    if record:name=record[0]
   result.setdefault(project_manager(self.hub,record=w),[]).append({'project_id':project,'name':name,'status':w['status']})
  return result

 def snapshot(self):
  self.scan_adapters()
  connections=[]
  for c in self.rows('integration_connections'):
   if c['kind'] not in KINDS:continue
   if c.get('legacy'):c['enabled']=self.server.deepseek.config()['enabled']
   api=c['kind'] in BASES;exe=locate(c['kind'],c.get('executable',''))
   connections.append({**c,'installed':True if api else bool(exe),'resolved_executable':exe,'key_present':bool(os.environ.get(c.get('key_env') or BASES.get(c['kind'],('',''))[1])) if api else None,'verification':c.get('verification','未验证真实模型调用'),'effort_options':KINDS[c['kind']][1]})
  profiles=self.rows('agent_profiles');by_connection={c['id']:c for c in connections}
  from .quota_state import status as quota_status
  from .model_availability import status as model_status
  return {'test_results':self.connection_tests.snapshot(),'adapter_directory':str(custom_directory(self.hub.directory)),'builtin_adapter_directory':str(self.hub.directory/'adapters'/'builtin'),'adapter_errors':self.adapter_errors,'connections':connections,'manager_projects':self.manager_projects(),'agents':[{**a,'quota_status':quota_status(self.hub,a['id'],a,by_connection.get(a['connection_id'])),'model_status':model_status(self.hub,'deepseek' if a['connection_id']=='deepseek-default' else 'integration:'+a['connection_id'],a['model'])} for a in profiles],'kinds':[{'id':k,'name':v[0],'efforts':v[1]} for k,v in KINDS.items()]}
 def model_status(self,agent):
  from .model_availability import status
  profile=next((a for a in self.rows('agent_profiles') if a['id']==agent),None)
  return status(self.hub,'deepseek' if profile['connection_id']=='deepseek-default' else 'integration:'+profile['connection_id'],profile['model']) if profile else None
 def quota_status(self,agent):
  from .quota_state import status
  return status(self.hub,agent)
 def start_quota_refresh(self):
  import threading
  self.quota_stop=threading.Event()
  def loop():
   while not self.quota_stop.is_set():
    try:
     ids={c for g in self.quota_overview() for c in g.get('refreshable',[])}
     for ident in ids:
      if self.quota_stop.is_set():return
      try:self.refresh_quota('user',ident)
      except Exception as error:
       with self.hub.tx():self.hub.audit('supervisor','integration.quota_refresh_failed',{'connection':ident,'error':str(error)[:200]})
    except Exception:pass
    self.quota_stop.wait(180)
  self.quota_thread=threading.Thread(target=loop,daemon=True);self.quota_thread.start()
 def quota_overview(self):
  profiles=[a for a in self.rows('agent_profiles') if a['enabled']]
  used={a['connection_id'] for a in profiles};groups={}
  labels={'codex':('openai','OpenAI / Codex'),'antigravity':('antigravity','Antigravity 订阅'),'deepseek-harness':('deepseek','DeepSeek'),'deepseek-api':('deepseek','DeepSeek'),'ori':('openrouter','OpenRouter'),'openrouter-api':('openrouter','OpenRouter'),'gemini-api':('google','Google Gemini'),'workbuddy':('codebuddy','CodeBuddy'),'opencode':('opencode','OpenCode')}
  for c in self.rows('integration_connections'):
   if c['id'] not in used:continue
   key,label=labels.get(c['kind'],('connection:'+c['id'],c['name']));group=groups.setdefault(key,{'id':key,'name':label,'connections':[],'connection_ids':[],'windows':[],'balances':[],'unreadable':[]})
   group['connections'].append(c['name']);group['connection_ids'].append(c['id'])
   windows=c.get('official_windows') or []
   for w in windows:
    remaining=w.get('remaining');reset=w.get('resets_at')
    if type(remaining) not in (int,float):continue
    group['windows'].append({'account':c['name'],'connection_id':c['id'],'name':' / '.join(str(x) for x in (w.get('group'),w.get('window') or w.get('name')) if x) or '账号窗口','remaining':remaining,'resets_at':reset,'source':'official','observed_at':c.get('probed_at')})
   quota=c.get('quota') or {}
   if quota.get('remaining') is not None:group['windows'].append({'account':c['name'],'connection_id':c['id'],'name':'手动录入','remaining':quota['remaining'],'resets_at':quota.get('resets_at'),'source':'manual','observed_at':quota.get('updated')})
   for balance in c.get('official_balance',[]):group['balances'].append({**balance,'account':'平台 DeepSeek API（独立凭证）' if c.get('legacy') and c.get('balance_source')!='dsh-account' else c['name'],'connection_id':c['id'],'observed_at':c.get('quota_observed_at')})
   if c.get('legacy') and c.get('official_balance') and c.get('balance_source')!='dsh-account':group['unreadable'].append(c['name']+'（Harness登录额度）')
   if not windows and not c.get('official_balance') and quota.get('remaining') is None:group['unreadable'].append(c['name'])
  # Keep distinct connection/account observations separate; do not invent shared quota identity.
  for group in groups.values():
   unique={}
   for window in group['windows']:unique[(window['connection_id'],window['name'],window['source'])]=window
   group['windows']=list(unique.values())
   group['refreshable']=[c['id'] for c in self.rows('integration_connections') if c['id'] in used and ((_BUILTINS.get(c['kind'],{}).get('quota_supported') or c.get('adapter',{}).get('manifest_data',{}).get('quota_supported')) or c.get('legacy') and (os.environ.get('DEEPSEEK_API_KEY') or (self.hub.directory/'deepseek-key.dpapi').exists())) and c['id'] in group['connection_ids']]
  return list(groups.values())
 def discussion_team(self,manager,agents,project_id=None):
  wanted=list(dict.fromkeys([manager]+[a for a in agents if a!=manager]));profiles={a['id']:a for a in self.rows('agent_profiles') if a['enabled']};connections={c['id']:c for c in self.rows('integration_connections')};roles={}
  if project_id and self.hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='workflows'").fetchone():
   row=self.hub.db.execute("SELECT body FROM workflows WHERE json_extract(body,'$.project_id')=? ORDER BY rowid DESC LIMIT 1",(project_id,)).fetchone()
   if row:roles=json.loads(row[0]).get('roles',{})
  rows=[]
  for ident in wanted:
   a=profiles.get(ident)
   if not a:continue
   from .model_availability import status as model_status
   c=connections[a['connection_id']];unavailable=model_status(self.hub,'deepseek' if c.get('legacy') else 'integration:'+c['id'],a['model']);ready=self.server.deepseek.config()['enabled'] if c.get('legacy') else bool(c.get('enabled'))
   quota=self.quota_status(ident)
   rows.append({'agent':ident,'name':a['name'],'model':a['model'],'platform':c['name'],'connection':c['id'],'effort':a['effort'],'role':'项目经理' if ident==manager else roles.get(ident,a['role']),'ready':ready and not unavailable and not quota['exhausted'],'quota_exhausted':quota['exhausted'],**({'quota_detail':quota.get('detail') or '当前额度窗口已耗尽','resets_at':quota.get('resets_at')} if quota['exhausted'] else {}),**({'unavailable':unavailable['detail']} if unavailable else {})})
  return {'manager':next((a for a in rows if a['agent']==manager),{'agent':manager,'role':'项目经理'}),'team':[a for a in rows if a['agent']!=manager]}
 def discussion_resources(self,agents):
  wanted=set(agents);profiles=[a for a in self.rows('agent_profiles') if a['enabled'] and a['id'] in wanted]
  grouped={}
  for agent in profiles:grouped.setdefault(agent['connection_id'],[]).append(agent['id'])
  overview=self.quota_overview();result=[]
  for ident,members in grouped.items():
   windows=[{k:w.get(k) for k in ('name','remaining','resets_at','source','observed_at')} for group in overview for w in group['windows'] if w['connection_id']==ident]
   balances=[{k:b.get(k) for k in ('name','amount','currency','observed_at')} for group in overview for b in group['balances'] if b['connection_id']==ident]
   manual=[]
   for member in members:
    row=self.hub.db.execute('SELECT remaining,resets_at,source,updated FROM quotas WHERE agent=?',(member,)).fetchone()
    if row and row['remaining'] is not None:manual.append({'agent':member,**dict(row)})
   result.append({'connection':ident,'agents':members,'grouped_by_connection':True,'windows':windows,'balances':balances,'manual_agents':manual,'unknown':not windows and not balances and not manual})
  blocked=[{'agent':a['id'],'name':a['name'],'model':a['model'],'detail':q.get('detail') or '额度窗口耗尽','resets_at':q.get('resets_at')} for a in profiles for q in [self.quota_status(a['id'])] if q['exhausted']]
  return {'captured_at':time.time(),'blocked_agents':blocked,'accounts':result,'note':'同一连接的额度只列一次，具体模型和窗口以 name 为准，不按 Agent 数重复相加；余额不等于剩余调用次数。未知不可推断为无限，读取时间见各条 observed_at。'}

 def refresh_quota(self,actor,connection_id):
  from .harness_adapters import quota_module
  return quota_module(self,actor,connection_id)
 def save_connection(self,actor,connection,confirmed=False):
  self.hub.require(actor,{'user'})
  if not isinstance(connection,dict):raise HubError('接入配置必须是对象')
  kind=connection.get('kind');text(connection.get('name',''),120)
  if kind not in KINDS:raise HubError('未知接入类型')
  ident=connection.get('id') or uid();old=next((c for c in self.rows('integration_connections') if c['id']==ident),{})
  if kind=='custom-harness' and (not old.get('adapter') or not old.get('adapter_available')):raise HubError('自定义 Harness 请通过适配器目录创建')
  if old.get('legacy'):raise HubError('原有连接由现有配置中心管理；可新建连接并迁移 Agent')
  if old and old['kind']!=kind:raise HubError('请新建另一类型的连接，再迁移 Agent，避免误用旧会话')
  assigned=[a['id'] for a in self.rows('agent_profiles') if a['connection_id']==ident]
  with self.lock,self.server.workflows.lock:
   if self.busy(assigned):raise HubError('此连接仍有在途任务，完成后再修改连接')
   if any(w['status'] in ('active','paused','blocked','needs_attention') and set(assigned)&set([project_manager(self.hub,record=w)]+w['agents']) for w in self.server.workflows.snapshot('user')):raise HubError('此连接仍被未结束项目授权使用，请结束项目后修改连接')
   enabled=connection.get('enabled',False) is True
   if enabled and confirmed is not True:raise HubError('请明确确认此连接的执行权限与费用')
   cwd=connection.get('cwd') or self.server.deepseek.config()['cwd']
   if not Path(cwd).is_absolute() or not Path(cwd).is_dir():raise HubError('请选择已存在的绝对工作目录')
   permission=connection.get('permission','workspace')
   if permission not in ('workspace','full'):raise HubError('权限无效')
   if enabled and kind in ('antigravity','opencode','ori','workbuddy','custom-harness') and permission!='full':raise HubError('此适配器尚未验证工作区沙箱；启用执行需要明确选择完全访问')
   env=connection.get('key_env') or BASES.get(kind,('',''))[1]
   if env and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',env):raise HubError('请输入密钥的环境变量名，不是密钥本身')
   limit=0 if kind in ('deepseek-harness','deepseek-api') else connection.get('call_limit',1000)
   if type(limit)!=int or limit<0:raise HubError('请求上限必须是非负整数，0 表示不限')
   c={'call_limit':limit,'id':ident,'name':connection['name'],'kind':kind,'enabled':enabled,'cwd':str(Path(cwd).resolve()),'permission':permission,'executable':connection.get('executable',''),'key_env':env,'models':old.get('models',[]),'quota':old.get('quota',{'source':'unknown','remaining':None,'resets_at':None}),'updated':time.time()}
   for field in ('adapter','adapter_available','manifest_hash','transport','previous_workbuddy_catalog','client_models','candidate_models','catalog_complete','catalog_status','probed_at','verification','probe_detail'):
    if field in old:c[field]=old[field]
   with self.hub.tx():
    self.put('integration_connections',c)
    cfg={'enabled':enabled,'cwd':c['cwd'],'authorized_cwd':c['cwd'],'permission':permission,'max_runs':limit,'max_seconds':3600,'authorized_max_seconds':86400,'grant_id':uid(),'confirmed_at':time.time(),'engine':'api','input_rate':0,'output_rate':0}
    self.hub.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('integration_runtime_'+ident,json.dumps(cfg)))
    self.hub.audit(actor,'integration.saved',{'id':ident,'kind':kind,'enabled':enabled})
   self.apply();return c
 def save_agent(self,actor,agent):
  self.hub.require(actor,{'user'})
  if not isinstance(agent,dict):raise HubError('Agent 配置必须是对象')
  ident=agent.get('id') or 'agent-'+uid()[:10]
  old=next((a for a in self.rows('agent_profiles') if a['id']==ident),None)
  if not old and not re.fullmatch(r'agent-[a-z0-9]{6,32}',ident):raise HubError('新 Agent 请使用自动生成的身份 ID')
  text(agent.get('name',''),120);text(agent.get('model',''),200);text(agent.get('role',''),200)
  c=self.get('integration_connections',agent.get('connection_id'));effort=agent.get('effort','default')
  # Archiving an unchanged identity must not depend on today's model catalogue.
  archiving=old is not None and agent.get('enabled') is False and all(agent.get(k)==old.get(k) for k in ('name','connection_id','model','role','effort'))
  if not archiving:
   if c['kind']=='antigravity':
    from .antigravity import model_efforts
    bound=model_efforts(agent['model'])[0]
    if bound!='default':effort=bound;agent={**agent,'effort':bound}
   options=next((m.get('efforts') for m in c.get('models',[]) if m['id']==agent['model']),None) or KINDS[c['kind']][1]
   if c['kind']=='antigravity':options=model_efforts(agent['model'])
   if effort not in options:raise HubError('此连接或模型不支持所选档位')
   if c['kind']=='deepseek-harness' and agent['model'] not in {m['id'] for m in c.get('models',[])}:raise HubError('请先刷新 Harness 官方模型目录，再选择模型')
  enabled=agent.get('enabled',True) is True
  value={k:agent[k] for k in ('name','connection_id','model','role')};value.update(id=ident,effort=effort,enabled=enabled)
  with self.lock,self.server.workflows.lock:
   if not enabled and self.manager_projects().get(ident):raise HubError('此 Agent 仍是未结束项目的经理，请先更换：'+'、'.join(p['name']+'（'+p['status']+'）' for p in self.manager_projects()[ident]))
   if self.busy([ident]):raise HubError('此 Agent 仍有在途任务，完成后再修改接入')
   # Changing an authorized participant must not silently reroute an active project.
   if old and enabled and any(w['status'] in ('active','paused','blocked','needs_attention') and ident in [project_manager(self.hub,record=w)]+w['agents'] for w in self.server.workflows.snapshot('user')):raise HubError('Agent 正参与未结束项目，请结束项目后更改接入')
   persona='你是 '+value['name']+'，独立身份 '+ident+'；当前平台 '+c['name']+'，模型 '+value['model']+'，职责 '+value['role']+'。服从项目经理调度，使用 Hub MCP 收发消息和 report_result 汇报；只处理新任务，不重放历史执行。若你是当前经理，send(mode="immediate") 可优先插入同项目已授权成员；普通协作使用 queue。'
   with self.hub.tx():
    self.put('agent_profiles',value)
    if c.get('legacy'):
     stored=self.hub.db.execute("SELECT value FROM settings WHERE key='agent_efforts'").fetchone();efforts=json.loads(stored[0]) if stored else {};efforts[ident]=effort
     self.hub.db.execute("INSERT OR REPLACE INTO settings VALUES('agent_efforts',?)",(json.dumps(efforts),))
    self.hub.db.execute("INSERT INTO agents(id,model,role,prompt,enabled) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET model=excluded.model,role=excluded.role,prompt=excluded.prompt,enabled=excluded.enabled",(ident,value['model'],value['role'],persona,int(enabled)))
    self.hub.db.execute("INSERT OR IGNORE INTO quotas VALUES(?,NULL,NULL,'unknown',?)",(ident,time.time()))
    value['project_opt_in']=old.get('project_opt_in',False) if old else True
    self.put('agent_profiles',value)
    self.queue_change(ident,old,value)
    if not enabled:
     for table in ('workflows','planning_sessions','project_options'):
      if not self.hub.db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(table,)).fetchone():continue
      key='project_id' if table=='project_options' else 'id'
      for row in self.hub.db.execute('SELECT '+key+',body FROM '+table).fetchall():
       item=json.loads(row[1]);opts=item.get('options',item);opts['agents']=[a for a in opts.get('agents',[]) if a!=ident]
       opts['reviewer']=independent_reviewer(project_manager(self.hub,record=item),opts.get('agents',[]),opts.get('reviewer'))
       self.hub.db.execute('UPDATE '+table+' SET body=? WHERE '+key+'=?',(json.dumps(item,ensure_ascii=False),row[0]))
    self.hub.audit(actor,'agent.integration_changed',{'agent':ident,'connection':c['id'],'model':value['model'],'effort':effort})
   if ident not in self.hub.tokens:
    self.hub.tokens[ident]=secrets.token_urlsafe(32)
    temp=self.hub.directory/'credentials.new.json';temp.write_text(json.dumps(self.hub.tokens),encoding='utf-8');temp.replace(self.hub.directory/'credentials.json')
   self.apply();return value
 def archive_agent(self,actor,agent_id):
  value=self.get('agent_profiles',agent_id);value['enabled']=False
  return self.save_agent(actor,value)
 def quota(self,actor,connection_id,remaining=None,resets_at=None):
  self.hub.require(actor,{'user'});c=self.get('integration_connections',connection_id)
  from .core import number
  if remaining is not None:number(remaining,0,100)
  if resets_at is not None:number(resets_at,0,1e12)
  c['quota']={'remaining':remaining,'resets_at':resets_at,'source':'manual','updated':time.time()}
  with self.hub.tx():self.put('integration_connections',c);self.hub.audit(actor,'integration.quota_manual',{'connection':connection_id,'remaining':remaining,'resets_at':resets_at})
  return c['quota']
 def probe(self,actor,connection_id):
  from .harness_adapters import probe_module
  return probe_module(self,actor,connection_id)
 def add_client_model(self,actor,connection_id,model,name='',confirmed=False):
  self.hub.require(actor,{'user'})
  if confirmed is not True:raise HubError('请确认此模型已在该客户端显示或使用')
  text(model,200)
  if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]*',model):raise HubError('请输入客户端的模型 ID')
  if name:text(name,120)
  with self.lock,self.hub.tx():
   c=self.get('integration_connections',connection_id)
   if c['kind']!='workbuddy':raise HubError('此补充入口目前仅用于 CodeBuddy 模型')
   item={'id':model,'name':name or model,'efforts':['default'],'source':'user_confirmed_client_model','availability':'user_confirmed_in_client','inference_verified':False,'pricing':'unknown','confirmed_at':time.time()}
   c['client_models']=[m for m in c.get('client_models',[]) if m['id']!=model]+[item]
   known={m['id']:m for m in c.get('models',[])};known.setdefault(model,item);c['models']=list(known.values())
   self.put('integration_connections',c);self.hub.audit(actor,'integration.client_model_added',{'connection':connection_id,'model':model,'inference_sent':False})
   return item

 def wizard_add(self,actor,connection_id,model,name='',confirmed=False,candidate_confirmed=False):
  self.hub.require(actor,{'user'});c=self.get('integration_connections',connection_id)
  if c['kind'] not in KINDS:raise HubError('请选择已有接入选项')
  item=next((m for m in c.get('models',[]) if m['id']==model),None)
  if not item and candidate_confirmed is True and c['kind']=='workbuddy':item=next((m for m in c.get('candidate_models',[]) if m['id']==model),None)
  if not item:raise HubError('请从已读取的模型列表中选择，不接受手动提供商或模型')
  with self.lock,self.server.workflows.lock:
   if confirmed and c.get('legacy') and not self.server.deepseek.config()['enabled']:raise HubError('请先在配置中心完成DeepSeek 接入，也可不勾选启用，先添加离线 Agent')
   if confirmed and not c.get('enabled'):
    if c.get('legacy'):raise HubError('请先在配置中心完成DeepSeek 接入')
    if c['kind'] not in BASES and not locate(c['kind'],c.get('executable','')):raise HubError('工具尚未安装，可以不勾选启用，先添加离线 Agent')
    proof={k:c[k] for k in ('probed_at','verification','probe_detail','official_windows') if k in c}
    c=self.save_connection(actor,{**c,'enabled':True},True);c.update(proof)
    with self.hub.tx():self.put('integration_connections',c)
   label=item.get('name') or model.rsplit('/',1)[-1]
   label=label[:95]
   if not name.strip():
    used={a['name'] for a in self.rows('agent_profiles')};index=1
    while label+' '+str(index) in used:index+=1
    name=label+' '+str(index)
   choices=item.get('efforts') or KINDS[c['kind']][1]
   preferred='high' if c['kind']=='deepseek-harness' else 'medium' if c['kind'] in ('codex','antigravity') else 'default'
   effort=preferred if preferred in choices else choices[0]
   return self.save_agent(actor,{'name':name,'connection_id':connection_id,'model':model,'effort':effort,'role':'工程师','enabled':True})
 def apply(self):
  from .integration_runtime import make_runtime
  profiles=self.rows('agent_profiles');connections=self.rows('integration_connections')
  self.server.deepseek.models={a['id']:a['model'] for a in profiles if a['connection_id']=='deepseek-default' and a['enabled']}
  for c in connections:
   if c['kind'] not in KINDS or c.get('legacy'):continue
   assigned=[a for a in profiles if a['connection_id']==c['id'] and a['enabled']]
   if not assigned and c['id'] not in self.instances:continue
   if c['id'] not in self.instances:
    runtime=make_runtime(self,c);self.instances[c['id']]=runtime
    self.server.workflows.runtimes.append(runtime)
    if self.server.coordination.runtimes is not self.server.workflows.runtimes:self.server.coordination.runtimes.append(runtime)
    if self.running and runtime.config()['enabled']:runtime.start()
   self.instances[c['id']].models={a['id']:a['model'] for a in profiles if a['connection_id']==c['id'] and a['enabled']}
   if self.running and self.instances[c['id']].config()['enabled']:self.instances[c['id']].start()
 def probe_model(self,actor,connection_id,model):
  from .harness_adapters import model_options_module
  return model_options_module(self,actor,connection_id,model)
 def test_all(self,actor,confirmed=False,agent_id=None):return self.connection_tests.start(actor,confirmed,agent_id)
 def start(self):
  self.running=True
  for rt in self.instances.values():
   if rt.config()['enabled']:rt.start()
 def close(self):
  self.connection_tests.close()
  if hasattr(self,'quota_stop'):self.quota_stop.set();self.quota_thread.join(timeout=2)
  for rt in self.instances.values():rt.close()
 def set_manager(self,actor,project_id,target_manager):
  self.hub.require(actor,{'user'})
  self.hub.projects.get(project_id)
  profile=self.get('agent_profiles',target_manager)
  if not profile.get('enabled'):raise HubError('请选择启用的 Agent')
  with self.hub.planning.lock,self.server.workflows.lock:
   sessions=[json.loads(r[0]) for r in self.hub.db.execute("SELECT body FROM planning_sessions WHERE json_extract(body,'$.project_id')=? ORDER BY rowid DESC",(project_id,))]
   rows=self.hub.db.execute("SELECT body FROM workflows WHERE json_extract(body,'$.project_id')=? ORDER BY rowid DESC",(project_id,)).fetchall()
   w=json.loads(rows[0][0]) if rows else None
   saved_manager=self.hub.db.execute('SELECT value FROM settings WHERE key=?',('project_manager:'+project_id,)).fetchone()
   old=(w or (sessions[0] if sessions else {})).get('manager',project_manager(self.hub,project_id))
   if old==target_manager:return {'manager':old}
   if self.busy([old,target_manager]):raise HubError('当前经理或目标 Agent 正在执行，请在本轮结束后切换；消息与上下文保留')
   rt=self.server.workflows.runtime(target_manager)
   if w and w['status'] not in ('completed','stopped','cancelled','failed'):
    cfg=rt.config()
    if not cfg.get('enabled'):raise HubError('请先启用目标 Agent 的接入')
    if rt.provider not in w['grants'] or w['grants'][rt.provider]!=cfg.get('grant_id'):raise HubError('目标接入尚未获得本项目执行授权，请选择已授权的 Agent')
    w['manager']=target_manager;w['previous_manager']=old;w.pop('return_manager',None)
    w['agents']=[a for a in w['agents'] if a!=target_manager]
    w['reviewer']=independent_reviewer(target_manager,w['agents'],w.get('reviewer'))
    w['report']='项目经理已切换为 '+profile['name']+'；保留任务和项目记录'
    self.server.workflows.save(w)
    # Prepared manager turns have no provider session yet; transfer their mailbox atomically.
    with self.hub.tx():
     for step in self.server.workflows.steps(w['id']):
      if step['agent']!=old or step['kind'] not in ('plan','review') or step['run_id']:continue
      self.hub.db.execute('UPDATE workflow_steps SET agent=? WHERE task=?',(target_manager,step['task']))
      self.hub.db.execute('UPDATE tasks SET agent=?,assigned_by=? WHERE id=?',(target_manager,target_manager,step['task']))
      self.hub.db.execute("UPDATE messages SET recipient=? WHERE project_id=? AND recipient=? AND body LIKE ? AND status='pending'",(target_manager,project_id,old,'[task:'+step['task']+'] %'))
   if w and w['status'] in ('completed','stopped','cancelled','failed'):
    w['manager']=target_manager;self.server.workflows.save(w)
   for session in sessions:
    session['manager']=target_manager
    session.setdefault('options',{})
    session['options']['agents']=[a for a in session.get('options',{}).get('agents',[]) if a!=target_manager]
    session['options']['reviewer']=independent_reviewer(target_manager,session['options']['agents'],session['options'].get('reviewer'))
    session['inherited_context']={'previous_manager':old,'history':session.get('history',[]),'plan':session.get('plan')}
    self.hub.planning.save(session)
   with self.hub.tx():
    self.hub.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('project_manager:'+project_id,target_manager))
    saved_options=self.hub.db.execute('SELECT body FROM project_options WHERE project_id=?',(project_id,)).fetchone()
    if saved_options:
     opts=json.loads(saved_options[0]);opts['agents']=[a for a in opts.get('agents',[]) if a!=target_manager]
     opts['reviewer']=independent_reviewer(target_manager,opts.get('agents',[]),opts.get('reviewer'))
     self.hub.db.execute('UPDATE project_options SET body=? WHERE project_id=?',(json.dumps(opts,ensure_ascii=False),project_id))
    self.hub.db.execute("UPDATE messages SET recipient=? WHERE project_id=? AND recipient=? AND status='pending'",(target_manager,project_id,old))
    self.queue_change('__manager__',{'manager':old},{'manager':target_manager},project_id)
    self.hub.audit(actor,'project.manager_selected',{'project':project_id,'from':old,'to':target_manager})
   if w and w['status']=='active':self.server.workflows.prepare_manager(w,self.server.workflows.steps(w['id']),'用户指定你接任项目经理。先查项目状态，保留在途分工，不重复派工。')
   return {'manager':target_manager}

 def effort(self,agent):return self.get('agent_profiles',agent)['effort']
 def set_effort(self,actor,agent,effort,project_id=None):
  self.hub.require(actor,{'user'});a=self.get('agent_profiles',agent);c=self.get('integration_connections',a['connection_id'])
  options=next((m.get('efforts') for m in c.get('models',[]) if m['id']==a['model']),None) or KINDS[c['kind']][1]
  if effort not in options:raise HubError('所选模型不支持此档位')
  if a['effort']==effort:return {'changed':False}
  before=dict(a)
  if c.get('legacy'):
   with self.hub.tx():
    efforts=self.server.deepseek.efforts();efforts[agent]=effort;self.hub.db.execute("INSERT OR REPLACE INTO settings VALUES('agent_efforts',?)",(json.dumps(efforts),))
  a['effort']=effort
  with self.hub.tx():self.put('agent_profiles',a);self.queue_change(agent,before,a);self.hub.audit(actor,'integration.effort_changed',{'agent':agent,'effort':effort})
  return {'changed':True,'applies':'next_turn'}
 def capabilities(self):
  connections={c['id']:c for c in self.rows('integration_connections')}
  return [{'agent':a['id'],'name':a['name'],'model':a['model'],'platform':connections[a['connection_id']]['name'],'effort':a['effort'],'role':a['role'],'quota_exhausted':self.quota_status(a['id'])['exhausted']} for a in self.rows('agent_profiles') if a['enabled']]

