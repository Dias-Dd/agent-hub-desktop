"""Local Git worktrees, worker checkpoints and explicit manager integration."""
import hashlib,json,os,re,shutil,subprocess,threading,time
from pathlib import Path
from .core import HubError

POLICY='正式开发使用独立Git worktree；只在本轮cwd改文件。完成后用project_git(action="commit")提交并汇报；平台也会在本轮结束后保存提交。经理用project_git(action="status")查看，action="integrate",agent=成员ID合并后验证；冲突在主目录解决并commit，不强推、不清空文件。执行失败保留现场，不自动提交。虚拟机文件须pull回本轮宿主工作区后提交，不自动同步；演示阶段不启用此流程。'
EXCLUDES='''
# Agent Hub: local credentials, caches and generated outputs stay local.
**/bin/
**/obj/
**/node_modules/
**/__pycache__/
.hub-design/
.dotnet-home/
packages-offline/
.nuget/
.venv/
venv/
.env
.env.*
credentials.json
*.pfx
*.p12
*.key
*.msix
*.appx
*.dll
*.exe
*.pdb
'''

class GitWorkspaces:
 def __init__(self,workflows):
  self.workflows=workflows;self.hub=workflows.hub;self.lock=threading.RLock()
  with self.hub.tx():
   self.hub.db.execute('CREATE TABLE IF NOT EXISTS git_workspaces(project TEXT,agent TEXT,root TEXT,cwd TEXT,branch TEXT,PRIMARY KEY(project,agent))')
   self.hub.db.execute('CREATE TABLE IF NOT EXISTS git_runs(run TEXT PRIMARY KEY,project TEXT,agent TEXT,cwd TEXT,branch TEXT,base TEXT,head TEXT,result TEXT)')
 def applies(self,w):
  if w.get('design_review') and not w.get('design_baseline'):return False
  with self.hub.lock:
   if not w.get('project_id') or not self.hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='hub_projects'").fetchone():return False
   return bool(self.hub.db.execute('SELECT 1 FROM hub_projects WHERE id=?',(w['project_id'],)).fetchone())
 def git(self,cwd,*args,check=True):
  result=subprocess.run(['git','-c','core.longpaths=true','-c','core.quotepath=false','-c','commit.gpgsign=false','-c','user.name=Deskfellows','-c','user.email=agent-hub@localhost',*args],cwd=cwd,capture_output=True,encoding='utf8',errors='replace',timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  if check and result.returncode:raise HubError('Git: '+(result.stderr or result.stdout).strip()[-1800:])
  return result
 def checkpoint(self,cwd,message):
  # Unresolved merges need a human/model resolution, never an automatic choice.
  conflicts=self.git(cwd,'diff','--name-only','--diff-filter=U').stdout.splitlines()
  if conflicts:return {'status':'conflict','files':conflicts}
  self.git(cwd,'add','-A')
  dirty=self.git(cwd,'diff','--cached','--quiet',check=False).returncode!=0
  merging=Path(self.git(cwd,'rev-parse','--git-path','MERGE_HEAD').stdout.strip())
  if not merging.is_absolute():merging=Path(cwd)/merging
  save=dirty or merging.exists()
  if save:self.git(cwd,'-c','core.hooksPath='+str(Path(self.hub.directory)/'git-empty-hooks'),'commit','-m',message or 'Hub checkpoint')
  return {'status':'committed' if save else 'clean','commit':self.git(cwd,'rev-parse','HEAD').stdout.strip()}
 def ensure(self,w):
  root=Path(w['cwd']).resolve();root.mkdir(parents=True,exist_ok=True)
  if not shutil.which('git'):raise HubError('未找到 Git，请安装 Git for Windows；工作文件保留')
  if not (root/'.git').exists():self.git(root,'init')
  exclude=Path(self.git(root,'rev-parse','--git-path','info/exclude').stdout.strip())
  if not exclude.is_absolute():exclude=root/exclude
  exclude.parent.mkdir(parents=True,exist_ok=True)
  old=exclude.read_text(encoding='utf8') if exclude.exists() else ''
  if '# Agent Hub:' not in old:exclude.write_text(old+EXCLUDES,encoding='utf8')
  head=self.git(root,'rev-parse','--verify','HEAD',check=False)
  if head.returncode:self.checkpoint(root,'Hub: initial project snapshot') if self.git(root,'status','--porcelain').stdout else self.git(root,'commit','--allow-empty','-m','Hub: initial project snapshot')
  return root
 def prepare(self,run):
  with self.lock:
   with self.hub.lock:
    row=self.hub.db.execute('SELECT s.kind,w.body FROM workflow_steps s JOIN workflows w ON w.id=s.workflow WHERE s.task=?',(run['task_id'],)).fetchone()
   if not row:return run
   w=json.loads(row['body'])
   if not self.applies(w):return run
   with self.hub.lock:prior=self.hub.db.execute('SELECT e.cwd,e.prompt,e.actual_input FROM git_runs g JOIN executions e ON e.id=g.run WHERE g.run=?',(run['id'],)).fetchone()
   if prior:return {**run,**dict(prior)}
   root=self.ensure(w)
   from .manager_identity import resolve
   if run['agent']==resolve(self.hub,record=w):return run
   # A first worktree sees the manager's existing files, including uncommitted
   # setup. Later tasks never auto-commit unrelated manager edits.
   project=w['project_id'];agent=run['agent']
   with self.hub.lock:saved=self.hub.db.execute('SELECT * FROM git_workspaces WHERE project=? AND agent=?',(project,agent)).fetchone()
   if not saved:
    self.checkpoint(root,'Hub: project baseline before parallel work')
    suffix=hashlib.sha256((project+':'+agent).encode()).hexdigest()[:16]
    branch='hub/'+suffix;cwd=Path(self.hub.directory)/'git-worktrees'/hashlib.sha256(project.encode()).hexdigest()[:16]/suffix
    cwd.parent.mkdir(parents=True,exist_ok=True)
    listed=self.git(root,'worktree','list','--porcelain').stdout
    if str(cwd).replace('\\','/') not in listed.replace('\\','/'):
     if self.git(root,'show-ref','--verify','refs/heads/'+branch,check=False).returncode:self.git(root,'worktree','add','-b',branch,str(cwd),'HEAD')
     else:self.git(root,'worktree','add',str(cwd),branch)
    with self.hub.tx():self.hub.db.execute('INSERT OR REPLACE INTO git_workspaces VALUES(?,?,?,?,?)',(project,agent,str(root),str(cwd),branch))
   else:cwd=Path(saved['cwd']);branch=saved['branch']
   with self.hub.lock:previous=self.hub.db.execute('SELECT base,head FROM git_runs WHERE project=? AND agent=? ORDER BY rowid DESC LIMIT 1',(project,agent)).fetchone()
   base=self.git(cwd,'rev-parse','HEAD').stdout.strip();main=self.git(root,'rev-parse','HEAD').stdout.strip()
   # Fast-forward a clean, already integrated branch; never discard local work.
   if not self.git(cwd,'status','--porcelain').stdout and not self.git(root,'merge-base','--is-ancestor',base,main,check=False).returncode:
    self.git(cwd,'merge','--ff-only',main);base=main
   notice=''
   before=(previous['head'] or previous['base']) if previous else None
   if before and before!=base:
    delta=self.git(cwd,'diff','--name-only',before,base,check=False);changed=delta.stdout.splitlines()
    notice='版本更新：'+before[:8]+' → '+base[:8]+'；变化文件：'+('、'.join(changed[:16])+(' 等'+str(len(changed))+'项' if len(changed)>16 else '') or ('差异列表暂不可读' if delta.returncode else '无文件差异'))+'。此前读取的内容与诊断可能过期，请重读相关文件后继续，不重放旧任务。\n'
   if base!=main:
    notice+='你的分支HEAD='+base[:8]+'，主目录HEAD='+main[:8]+'；本地改动/独立提交已保留，尚未自动同步。诊断请注明分支与版本，勿把本分支结果当成主目录结果。\n'
   prompt=run['prompt']
   for original in {str(root),str(root).replace('\\','/')}:
    prompt=re.sub(re.escape(original)+r'(?=[/\\\s"\']|$)',lambda m:str(cwd),prompt,flags=re.I)
   prompt=notice+'本轮工作目录：'+str(cwd)+'（独立Git worktree，分支 '+branch+'，HEAD '+base[:8]+'）。任务里原项目路径均以此目录为准；不要修改主目录。\n'+prompt
   with self.hub.tx():
    self.hub.db.execute('UPDATE executions SET cwd=?,prompt=?,actual_input=? WHERE id=?',(str(cwd),prompt,prompt,run['id']))
    self.hub.db.execute('INSERT OR IGNORE INTO git_runs VALUES(?,?,?,?,?,?,NULL,NULL)',(run['id'],project,agent,str(cwd),branch,base))
    self.hub.audit(agent,'git.workspace_ready',{'project':project,'run':run['id'],'cwd':str(cwd),'branch':branch,'base':base})
   return {**run,'cwd':str(cwd),'prompt':prompt,'actual_input':prompt}
 def finish(self,run,status):
  with self.lock:
   with self.hub.lock:row=self.hub.db.execute('SELECT * FROM git_runs WHERE run=?',(run['id'],)).fetchone()
   if not row:return None
   if row['result']:return json.loads(row['result'])
   try:
    with self.hub.lock:step=self.hub.db.execute('SELECT kind FROM workflow_steps WHERE task=?',(run['task_id'],)).fetchone()
    readonly=run.get('purpose')=='question' or (step and step['kind']=='check')
    result=({'status':'inspected','note':'只读任务，不提交文件'} if readonly else self.checkpoint(row['cwd'],'Hub: '+run['agent']+' task '+run['task_id'][:12])) if status=='completed' else {'status':'preserved','note':'执行未成功结束，工作文件保留，未自动提交'}
    result.update(branch=row['branch'],cwd=row['cwd'],base=row['base'])
    result['commit']=self.git(row['cwd'],'rev-parse','HEAD').stdout.strip()
   except Exception as error:result={'status':'error','detail':str(error),'cwd':row['cwd'],'branch':row['branch']}
   with self.hub.tx():
    self.hub.db.execute('UPDATE git_runs SET head=?,result=? WHERE run=?',(result.get('commit'),json.dumps(result,ensure_ascii=False),run['id']))
    self.hub.audit(run['agent'],'git.worker_saved',{'project':row['project'],'run':run['id'],**result})
   return result
 def status(self,w):
  if not self.applies(w):return {'enabled':False,'note':'演示及独立接入测试仍使用原目录'}
  with self.lock:
   root=Path(w['cwd']).resolve()
   with self.hub.lock:rows=[dict(r) for r in self.hub.db.execute('SELECT * FROM git_workspaces WHERE project=?',(w['project_id'],))]
   for row in rows:
    try:
     row['head']=self.git(row['cwd'],'rev-parse','HEAD').stdout.strip()
     row['integrated']=not self.git(root,'merge-base','--is-ancestor',row['head'],'HEAD',check=False).returncode
    except Exception as error:row.update(error=str(error),integrated=False)
   return {'enabled':True,'root':str(root),'workspaces':rows}
 def tool(self,actor,run_id,action='status',agent=None,message=None):
  w,run=self.workflows.run_context(actor,run_id)
  if action=='status':return self.status(w)
  with self.lock:
   if action=='commit':
    with self.hub.lock:step=self.hub.db.execute('SELECT kind FROM workflow_steps WHERE task=?',(run.get('task_id'),)).fetchone()
    if run.get('purpose')=='question' or (step and step['kind']=='check'):return {'status':'read_only','note':'本轮只读，不提交文件'}
    result=self.checkpoint(run['cwd'],message or 'Hub: '+actor+' checkpoint')
    with self.hub.tx():self.hub.audit(actor,'git.commit',{'project':w.get('project_id'),'run':run_id,**result})
    return result
   if action!='integrate':raise HubError('Git 操作仅支持 status、commit、integrate')
   self.workflows.run_context(actor,run_id,manager=True)
   with self.hub.lock:row=self.hub.db.execute('SELECT * FROM git_workspaces WHERE project=? AND agent=?',(w['project_id'],agent)).fetchone()
   if not row:return {'status':'unavailable','note':'该成员尚未创建本项目工作分支'}
   root=self.ensure(w);branch=row['branch']
   if not self.git(root,'merge-base','--is-ancestor',branch,'HEAD',check=False).returncode:return {'status':'integrated','already_integrated':True,'branch':branch}
   merged=self.git(root,'merge','--no-ff','--no-edit',branch,check=False)
   with self.hub.tx():self.hub.audit(actor,'git.integrate',{'project':w['project_id'],'agent':agent,'branch':branch,'exit_code':merged.returncode})
   if merged.returncode:return {'status':'conflict' if self.git(root,'diff','--name-only','--diff-filter=U').stdout else 'needs_attention','branch':branch,'cwd':str(root),'files':self.git(root,'diff','--name-only','--diff-filter=U').stdout.splitlines(),'detail':(merged.stderr or merged.stdout)[-1800:],'next':'保留现场；在主目录解决冲突并git add后用 project_git(action="commit")，或 git merge --abort 取消合并'}
   return {'status':'integrated','branch':branch,'commit':self.git(root,'rev-parse','HEAD').stdout.strip(),'next':'在主目录运行集成验证'}
