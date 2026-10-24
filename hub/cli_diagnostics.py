"""Offline startup reproduction: copied state, no inference or task replay."""
import sqlite3,tempfile,shutil,os,subprocess
from pathlib import Path
from types import SimpleNamespace

def startup_probe(source):
 from .core import Hub
 from .codex_runtime import CodexRuntime
 from .antigravity import AntigravityRuntime
 from .deepseek_runtime import DeepSeekRuntime
 from .workflows import Workflows
 from .coordination import Coordination
 from .integrations import Integrations
 source=Path(source)
 if not (source/'hub.sqlite3').exists():return {'skipped':True}
 with tempfile.TemporaryDirectory() as folder:
  target=Path(folder);src=sqlite3.connect('file:'+ (source/'hub.sqlite3').as_posix()+'?mode=ro',uri=True);dest=sqlite3.connect(target/'hub.sqlite3');src.backup(dest);src.close();dest.close()
  shutil.copy2(source/'credentials.json',target/'credentials.json')
  h=Hub(target);c=CodexRuntime(h);a=AntigravityRuntime(h);d=DeepSeekRuntime(h);w=Workflows(h,[c,a,d]);h.workflows=w;w.valid=lambda *args:None;co=Coordination(h,[c,a,d],w)
  registry=Integrations(SimpleNamespace(hub=h,codex=c,antigravity=a,deepseek=d,workflows=w,coordination=co));h.integrations=registry;h.url='http://127.0.0.1:1'
  result={};original=subprocess.Popen
  try:
   row=h.db.execute("SELECT * FROM executions WHERE provider='integration:workbuddy-local' AND status='failed' ORDER BY created DESC LIMIT 1").fetchone()
   if not row:return {'skipped':True}
   run=dict(row);run['status']='running';h.db.execute("UPDATE executions SET status='running' WHERE id=?",(run['id'],));h.db.commit()
   rt=registry.instances['workbuddy-local'];rt.guard=lambda *args:None;rt.sessions.state=lambda *args:None
   rt.finalize=lambda run,status,text,*args:result.update(status=status,detail=text)
   def stop_launch(*args,**kwargs):
    result['reached_launch']=True
    raise RuntimeError('DIAGNOSTIC_STOP_NO_INFERENCE')
   subprocess.Popen=stop_launch
   rt.execute(run)
   return result
  finally:
   subprocess.Popen=original;registry.close();h.db.close()
