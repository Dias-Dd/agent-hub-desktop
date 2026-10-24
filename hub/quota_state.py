"""Cached, model-aware quota state; never sends inference requests."""
import json,re,time

def is_exhausted_error(detail):
 value=str(detail).lower()
 return any(x in value for x in ('free usage limit reached','free quota exceeded','free limit reached','individual quota reached','insufficient_quota','quota exhausted','quota exceeded','quota limit reached','quota_exceeded','usage_limit_reached','usage limit reached','额度耗尽','余额不足','insufficient balance'))

def status(hub,agent,profile=None,connection=None):
 registry=getattr(hub,'integrations',None);windows=[];observed=0;model=None;provider=None
 if registry:
  profile=profile or next((a for a in registry.rows('agent_profiles') if a['id']==agent),None)
  if profile:
   model=profile['model'];provider='deepseek' if profile['connection_id']=='deepseek-default' else 'integration:'+profile['connection_id'];c=connection or registry.get('integration_connections',profile['connection_id']);observed=c.get('probed_at') or 0
   windows=list(c.get('official_windows') or [])
   if c['kind']=='antigravity':
    from .antigravity import applicable_windows
    windows=applicable_windows({'windows':windows},agent,model)
   manual=c.get('quota') or {};observed=max(observed,manual.get('updated') or 0)
   if manual.get('remaining') is not None:windows.append({'remaining':manual['remaining'],'resets_at':manual.get('resets_at'),'group':'手动额度'})
 with hub.lock:
  manual=hub.db.execute('SELECT remaining,resets_at,source,updated FROM quotas WHERE agent=?',(agent,)).fetchone()
  if manual and manual['remaining'] is not None and manual['source']!='unknown':
   windows.append(dict(manual));observed=max(observed,manual['updated'] or 0)
  exists=hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='model_quota_blocks'").fetchone()
  blocked=hub.db.execute('SELECT body FROM model_quota_blocks WHERE agent=?',(agent,)).fetchone() if exists else None
 known=[w for w in windows if type(w.get('remaining')) in (int,float)];empty=[w for w in known if w['remaining']<=0]
 block=json.loads(blocked[0]) if blocked else None
 if block and ((model and block.get('model')!=model) or (provider and block.get('provider')!=provider)):block=None
 # Only a newer positive provider observation clears an explicit rejection.
 if block and known and not empty and observed>block['observed_at']:block=None
 reset=max([w.get('resets_at') or 0 for w in empty] or [0]) or (block or {}).get('resets_at')
 return {'exhausted':bool(empty or block),'remaining':min([w['remaining'] for w in known]) if known else None,'resets_at':reset,'windows':windows,'detail':(block or {}).get('detail'),'observed_at':observed}

def record_rejection(hub,run,detail):
 # Caller owns the SQLite transaction. The raw execution is retained for audit.
 hub.db.execute('CREATE TABLE IF NOT EXISTS model_quota_blocks(agent TEXT PRIMARY KEY,body TEXT)')
 hub.db.execute('CREATE TABLE IF NOT EXISTS model_reports(run TEXT PRIMARY KEY,body TEXT)')
 match=re.search(r'Resets in (?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?',detail,re.I)
 reset=time.time()+sum(int(x or 0)*unit for x,unit in zip(match.groups(),(3600,60,1))) if match else None
 hub.db.execute('INSERT OR REPLACE INTO model_quota_blocks VALUES(?,?)',(run['agent'],json.dumps({'observed_at':time.time(),'resets_at':reset,'detail':detail[:1800],'model':run.get('model'),'provider':run.get('provider')},ensure_ascii=False)))
 summary='该模型额度耗尽，本任务已取消、未完成；请经理改派或设置额度恢复提醒，不自动重跑。'
 hub.db.execute('INSERT OR REPLACE INTO model_reports VALUES(?,?)',(run['id'],json.dumps({'summary':summary,'risk':'blocked','evidence':[detail[:1800]]},ensure_ascii=False)))
 hub.audit('supervisor','execution.quota_cancelled',{'run_id':run['id'],'agent':run['agent'],'detail':detail[:1800]})

def cancel_queued(hub,run,quota):
 detail='已知额度耗尽，未启动模型。'+(quota.get('detail') or '')
 record_rejection(hub,run,detail)
 hub.db.execute("UPDATE executions SET status='cancelled',finished=?,result=? WHERE id=? AND status='queued'",(time.time(),detail,run['id']))
 hub.db.execute("UPDATE messages SET status='cancelled',lease=NULL,result=? WHERE id=?",(detail,run['message_id']))
 hub.db.execute("UPDATE tasks SET status='cancelled',note=? WHERE id=?",(detail,run['task_id']))
