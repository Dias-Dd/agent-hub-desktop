"""Small read-only tray snapshot; no provider calls and no full state payload."""
import json,sqlite3,threading,time,queue
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace


def read_status(directory):
 path=Path(directory)/'hub.sqlite3'
 with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.3)) as db:
  db.row_factory=sqlite3.Row;db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
  tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
  latest={};projects=[]
  if {'hub_projects','workflows','settings'}<=tables:
   for row in db.execute("SELECT json_extract(body,'$.project_id') project_id,json_extract(body,'$.status') status,json_extract(body,'$.manager_progress.progress') progress FROM workflows WHERE rowid IN (SELECT max(rowid) FROM workflows GROUP BY json_extract(body,'$.project_id'))"):
    if row['project_id']:latest[row['project_id']]={'status':row['status'],'progress':row['progress']}
   for p in db.execute("SELECT id,name FROM hub_projects WHERE NOT EXISTS(SELECT 1 FROM settings WHERE key='deleted_project:'||hub_projects.id)"):
    w=latest.get(p['id']);
    if not w or w.get('status') not in ('active','paused','blocked','needs_attention'):continue
    progress=w.get('progress')
    projects.append({'id':p['id'],'name':p['name'],'progress':progress,'status':w['status']})
  profiles={}
  if 'agent_profiles' in tables:
   profiles={r['id']:json.loads(r['body']) for r in db.execute('SELECT id,body FROM agent_profiles')}
  connections={r['id']:json.loads(r['body']) for r in db.execute('SELECT id,body FROM integration_connections')} if 'integration_connections' in tables else {}
  registry=SimpleNamespace(rows=lambda table:list(profiles.values()) if table=='agent_profiles' else list(connections.values()),get=lambda table,ident:connections[ident])
  quota_hub=SimpleNamespace(db=db,lock=threading.RLock(),integrations=None)
  busy=set()
  if 'executions' in tables:busy={r[0] for r in db.execute("SELECT DISTINCT agent FROM executions WHERE status IN ('running','interrupting')")}
  unavailable={(r[0],r[1]) for r in db.execute('SELECT provider,model FROM unavailable_models')} if 'unavailable_models' in tables else set()
  agents=[]
  if 'agents' in tables:
   for row in db.execute('SELECT id,model,status,enabled FROM agents'):
    profile=profiles.get(row['id'],{})
    if not profile.get('enabled',row['enabled']):continue
    provider='deepseek' if profile.get('connection_id')=='deepseek-default' else 'integration:'+profile.get('connection_id','')
    blocked=(provider,profile.get('model',row['model'])) in unavailable
    exhausted=False
    if 'quotas' in tables:
     from hub.quota_state import status as quota_status
     quota_hub.integrations=registry if profile.get('connection_id') in connections else None
     exhausted=quota_status(quota_hub,row['id'],profile=profile or None)['exhausted']
    agents.append({'id':row['id'],'name':profile.get('name') or row['id'],'status':'offline' if blocked or exhausted else 'busy' if row['id'] in busy else 'idle' if profile.get('enabled') or row['status']!='offline' else 'offline'})
  names={r[0]:r[1] for r in db.execute('SELECT id,name FROM hub_projects')} if 'hub_projects' in tables else {}
  completions=[]
  if 'desktop_notifications' in tables:
   for row in db.execute('SELECT id,kind,project_id FROM desktop_notifications ORDER BY rowid DESC LIMIT 100'):
    project=row['project_id'];completions.append({'id':row['id'],'kind':row['kind'],'project':project,'name':names.get(project,'')})
  return {'projects':projects,'agents':agents,'completions':completions,'updated':time.time(),'stale':False}


class StatusCache:
 def __init__(self,directory):
  self.directory=Path(directory).resolve();self.value={'projects':[],'agents':[],'updated':None,'stale':True};self.stop=threading.Event();self.seen=None;self.notifications=queue.SimpleQueue()
  self.worker=threading.Thread(target=self.run,daemon=True,name='hub-tray-status');self.worker.start()
 def run(self):
  while not self.stop.is_set():
   try:
    self.value=read_status(self.directory);self.observe(self.value.get('completions',[]))
   except (OSError,ValueError,sqlite3.Error):self.value={**self.value,'stale':True}
   self.stop.wait(3)
 def close(self):self.stop.set();self.worker.join(timeout=1)

 def observe(self,events):
  if self.seen is None:self.seen={e['id'] for e in events};return
  for event in events:
   if event['id'] not in self.seen:self.notifications.put(event);self.seen.add(event['id'])


def menu_rows(snapshot):
 rows=[('header','进行中的项目',None)]
 labels={'active':'进行中','paused':'暂停','blocked':'等待处理','needs_attention':'待核查'}
 for p in snapshot.get('projects',[]):
  progress=p.get('progress');percent='待经理汇报' if progress is None else f'{progress:g}%'
  rows.append(('project',p['name']+' · '+percent+' · '+labels.get(p['status'],p['status']),p['id']))
 if not snapshot.get('projects'):rows.append(('info','暂无进行中的项目',None))
 rows.append(('header','Agent 状态',None))
 for a in snapshot.get('agents',[]):rows.append(('info',({'busy':'●','idle':'○','offline':'–'}.get(a['status'],'○'))+' '+a['name']+' · '+a['status'],None))
 if not snapshot.get('agents'):rows.append(('info','正在加载 Agent 状态',None))
 if snapshot.get('stale'):rows.append(('info','状态暂未更新，保留上次记录',None))
 return rows
