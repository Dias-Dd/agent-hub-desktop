"""One-time durable identity migration. Run only with the Hub stopped."""
import argparse,json,sqlite3,time,shutil
from pathlib import Path
MAP={'flash-1':'deepseek-1','flash-2':'deepseek-2','flash-3':'deepseek-3','argon':'deepseek-4','opus':'deepseek-5','sol-1':'deepseek-6','sol-2':'deepseek-7','astra':'deepseek-8','deepseek':'deepseek-9'}
IDENTITY_KEYS={'agent','sender','recipient','manager','reviewer','backup_manager','target_manager','from','by','assigned_by'}
LIST_KEYS={'agents','allowed_agents','participants','sharedWith'}
def rewrite(value,key=None):
 if isinstance(value,dict):
  return {(MAP.get(k,k) if key=='roles' else k):rewrite(v,k) for k,v in value.items()}
 if isinstance(value,list):return [MAP.get(v,v) if isinstance(v,str) and key in LIST_KEYS else rewrite(v) for v in value]
 if isinstance(value,str) and key in IDENTITY_KEYS:return MAP.get(value,value)
 return value

def migrate(directory):
 d=Path(directory).resolve();db=d/'hub.sqlite3';c=sqlite3.connect(db);c.row_factory=sqlite3.Row
 if c.execute("select 1 from settings where key='nine_deepseek_migration'").fetchone():
  creds=d/'credentials.json';old=json.loads(creds.read_text(encoding='utf8'))
  renamed={MAP.get(k,k):v for k,v in old.items()}
  if old!=renamed:creds.write_text(json.dumps(renamed,indent=2),encoding='utf8')
  c.close();return {'already_migrated':True}
 assert not c.execute("select 1 from executions where status in ('running','interrupting','queued','waiting_quota')").fetchone(),'Wait for executions before migrating'
 backup=d/('before-nine-deepseek-'+str(int(time.time())));backup.mkdir()
 dest=sqlite3.connect(backup/'hub.sqlite3');c.backup(dest);dest.close()
 creds=d/'credentials.json';shutil.copy2(creds,backup/'credentials.json')
 credentials=json.loads(creds.read_text(encoding='utf8'))
 renamed={MAP.get(k,k):v for k,v in credentials.items()}
 cfg=json.loads(c.execute("select value from settings where key='deepseek_runtime'").fetchone()[0])
 assert (d/'deepseek-key.dpapi').exists(),'Missing API key; migration must not silently enable an unconfigured provider'
 cfg.update(enabled=True,unlimited=True,max_runs=0,budget_cents=None,max_requests=None,takeover=False)
 with c:
  for table in ['agents','messages','tasks','quotas','calls','executions','workflow_steps','agent_stops','agent_sessions']:
   cols={r[1] for r in c.execute('pragma table_info('+table+')')}
   for col in ['agent','sender','recipient','assigned_by']+(['id'] if table=='agents' else []):
    if col in cols:
     for old,new in MAP.items():c.execute('update '+table+' set '+col+'=? where '+col+'=?',(new,old))
  for table in ['workflows','planning_sessions','model_reports']:
   cols={r[1] for r in c.execute('pragma table_info('+table+')')}
   if 'body' not in cols:continue
   for row in c.execute('select rowid,body from '+table).fetchall():
    try:body=rewrite(json.loads(row['body']))
    except (ValueError,TypeError):continue
    if table=='workflows':
     body['manager']='deepseek-4';body['backup_manager']=None;body['unlimited_calls']=True
     body['grants']={'deepseek':cfg['grant_id']}
     if body.get('status') in ('active','needs_attention'):body['status']='paused';body['report']='已迁移为九个 DeepSeek 身份，等待用户恢复项目；不重放旧执行。'
    c.execute('update '+table+' set body=? where rowid=?',(json.dumps(body,ensure_ascii=False),row['rowid']))
  for name in ['codex_runtime','antigravity_runtime']:
   row=c.execute('select value from settings where key=?',(name,)).fetchone()
   if row:
    old=json.loads(row[0]);old['enabled']=False;c.execute('update settings set value=? where key=?',(json.dumps(old),name))
  c.execute("insert or replace into settings values('deepseek_runtime',?)",(json.dumps(cfg),))
  c.execute("insert or replace into settings values('nine_deepseek_migration',?)",(json.dumps({'at':time.time(),'mapping':MAP,'unlimited':True}),))
  c.execute("insert into audit(ts,actor,event,detail) values(?,'user','identities.migrated',?)",(time.time(),json.dumps({'mapping':MAP,'unlimited':True,'backup':str(backup),'inference_started':False})))
  c.execute("update agents set status='offline',active=NULL")
 temp=creds.with_suffix('.migration.tmp');temp.write_text(json.dumps(renamed,indent=2),encoding='utf8')
 try:temp.replace(creds)
 except PermissionError:
  # Some existing files allow writes but deny atomic replacement. A backup exists.
  creds.write_text(json.dumps(renamed,indent=2),encoding='utf8');temp.unlink()
 c.close()
 return {'agents':9,'backup':str(backup),'inference_started':False}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('data');a=p.parse_args();print(json.dumps(migrate(a.data)))
