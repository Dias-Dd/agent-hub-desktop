from .manager_identity import resolve as project_manager
"""User project folders and history grouping; creating a project never starts inference."""
import json,time
from pathlib import Path
from .core import HubError,text,uid

class Projects:
    def __init__(self,hub):
        self.hub=hub;hub.projects=self
        with hub.tx():
            hub.db.execute('CREATE TABLE IF NOT EXISTS project_options(project_id TEXT PRIMARY KEY,body TEXT)')
            hub.db.execute('CREATE TABLE IF NOT EXISTS hub_projects(id TEXT PRIMARY KEY,name TEXT,cwd TEXT,created REAL)')
            for table in ('tasks','messages','calls'):
                if 'project_id' not in {r[1] for r in hub.db.execute('PRAGMA table_info('+table+')')}:hub.db.execute('ALTER TABLE '+table+' ADD COLUMN project_id TEXT')
        self.tag()
    def get(self,ident):
        with self.hub.lock:row=self.hub.db.execute('SELECT * FROM hub_projects WHERE id=?',(ident,)).fetchone()
        if not row:raise HubError('项目不存在')
        result=dict(row)
        with self.hub.lock:settings=self.hub.db.execute('SELECT body FROM project_options WHERE project_id=?',(ident,)).fetchone()
        result['options']=json.loads(settings[0]) if settings else {}
        return result
    def create(self,actor,name,cwd=None,options=None):
        self.hub.require(actor,{'user'});text(name,100)
        ident=uid()
        if cwd:
            cwd=Path(cwd).expanduser()
            if not cwd.is_absolute() or not cwd.is_dir():raise HubError('请选择已存在的绝对工作目录')
        else:
            cwd=self.storage_root()/ident;cwd.mkdir(parents=True,exist_ok=False)
        if options is not None and not isinstance(options,dict):raise HubError('项目设置必须为对象')
        allowed={'preview_mode','agents','reviewer','max_calls','expires_minutes','max_parallel','max_seconds','delegate_stop','max_hops','max_messages'}
        settings={k:v for k,v in (options or {}).items() if k in allowed};settings['cwd']=str(cwd.resolve())
        with self.hub.tx():
            self.hub.db.execute('INSERT INTO hub_projects VALUES(?,?,?,?)',(ident,name.strip(),str(cwd.resolve()),time.time()))
            self.hub.db.execute('INSERT INTO project_options VALUES(?,?)',(ident,json.dumps(settings,ensure_ascii=False)))
            manager=project_manager(self.hub)
            if manager:self.hub.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('project_manager:'+ident,manager))
            self.hub.audit(actor,'project.created',{'project':ident,'name':name,'inference_started':False})
        return self.get(ident)
    def storage_root(self):
        with self.hub.lock:row=self.hub.db.execute("SELECT value FROM settings WHERE key='project_storage_root'").fetchone()
        return Path(row[0]) if row else self.hub.directory/'projects'

    def storage(self,actor,path=None):
        self.hub.require(actor,{'user'})
        if path is not None:
            target=Path(path).expanduser()
            if not target.is_absolute():raise HubError('请选择绝对目录')
            target.mkdir(parents=True,exist_ok=True)
            import tempfile
            try:
                with tempfile.TemporaryFile(dir=target) as probe:probe.write(b'Hub storage check')
            except OSError:raise HubError('此目录不可写，请选择其它位置') from None
            with self.hub.tx():
                self.hub.db.execute("INSERT OR REPLACE INTO settings VALUES('project_storage_root',?)",(str(target.resolve()),))
                self.hub.audit(actor,'project.storage_changed',{'root':str(target.resolve()),'existing_projects_moved':False})
        import os,shutil
        deadline=time.monotonic()+2;projects=[]
        with self.hub.lock:rows=[dict(r) for r in self.hub.db.execute('SELECT * FROM hub_projects ORDER BY created DESC')];deleted={r[0].split(':',1)[1] for r in self.hub.db.execute("SELECT key FROM settings WHERE key LIKE 'deleted_project:%' AND value='true'")}
        for project in rows:
            size=0;files=0;partial=False
            root=Path(project['cwd'])
            from .project_files import inventory
            owned=inventory(self,project['id'])['paths']
            scan_roots=[]
            for item in sorted(owned,key=lambda x:len(Path(x['path']).parts)):
                target=Path(item['path'])
                if item['protected'] or target.is_symlink() or getattr(target,'is_junction',lambda:False)():continue
                if not any(target.is_relative_to(parent) for parent in scan_roots):scan_roots.append(target)
            for scan_root in scan_roots:
                for parent,dirs,names in os.walk(scan_root,followlinks=False):
                    dirs[:]=[name for name in dirs if not (Path(parent)/name).is_symlink() and not getattr(Path(parent)/name,'is_junction',lambda:False)()]
                    if time.monotonic()>deadline:partial=True;break
                    for index,name in enumerate(names):
                        if index%64==0 and time.monotonic()>deadline:partial=True;break
                        file=Path(parent)/name
                        try:
                            if not file.is_symlink():size+=file.stat().st_size;files+=1
                        except OSError:partial=True
                if partial:break
            from .project_activity import busy
            projects.append({**project,'busy':busy(self.hub,project['id']),'bytes':size,'files':files,'partial':partial,'exists':root.is_dir(),'removed':project['id'] in deleted,'associated_paths':owned})
        root=self.storage_root();disk=shutil.disk_usage(root if root.exists() else self.hub.directory)
        return {'root':str(root),'projects':projects,'disk_free':disk.free,'disk_total':disk.total,'data_directory':str(self.hub.directory)}

    def ensure_ready(self,project_id):
        with self.hub.tx():
            flag=self.hub.db.execute('SELECT value FROM settings WHERE key=?',('project_files_cleaned:'+project_id,)).fetchone()
            if flag and flag[0]=='true':
                Path(self.get(project_id)['cwd']).mkdir(parents=True,exist_ok=True)
                self.hub.db.execute('DELETE FROM settings WHERE key=?',('project_files_cleaned:'+project_id,))
                self.hub.audit('user','project.restart_after_cleanup',{'project':project_id})
                return True
        return False

    def cleanup(self,actor,project_id,confirmed=False,inventory_key=None):
        from .project_files import cleanup
        return cleanup(self,actor,project_id,confirmed,inventory_key)

    def git_tree(self,actor,project_id):
        from .project_files import git_tree
        return git_tree(self,actor,project_id)

    def browse_directory(self,actor,initial=''):
        self.hub.require(actor,{'user'})
        from desktop.folder_picker import pick_directory
        try:return {'path':pick_directory(initial) or None}
        except OSError as error:raise HubError('目录窗口暂不可用：'+str(error)) from None

    def rename(self,actor,project_id,name):
        self.hub.require(actor,{'user'});self.get(project_id);text(name,100)
        with self.hub.tx():
            self.hub.db.execute('UPDATE hub_projects SET name=? WHERE id=?',(name.strip(),project_id))
            self.hub.audit(actor,'project.renamed',{'project':project_id,'name':name.strip()})
        return self.get(project_id)

    def open_directory(self,actor,project_id):
        self.hub.require(actor,{'user'});project=self.get(project_id)
        import os
        if not Path(project['cwd']).is_dir():raise HubError('工作目录不存在')
        os.startfile(project['cwd'])
        return {'ok':True}

    def update(self,actor,project_id,options):
        self.hub.require(actor,{'user'});project=self.get(project_id)
        planning=self.hub.planning
        manager_row=self.hub.db.execute('SELECT value FROM settings WHERE key=?',('project_manager:'+project_id,)).fetchone()
        merged=planning.options({**project['options'],**options,'cwd':project['cwd']},project_manager(self.hub,project_id))
        with planning.workflows.lock:
            registry=getattr(self.hub,'integrations',None)
            if registry and project['options'].get('agents',[])!=merged['agents']:registry.queue_change('__roster__',{'agents':project['options'].get('agents',[])},{'agents':merged['agents']},project_id)
            for w in planning.workflows.snapshot('user'):
                if w.get('project_id')!=project_id:continue
                before_agents=list(w['agents']);w['agents']=merged['agents']
                for agent in merged['agents']:
                    rt=planning.workflows.runtime(agent)
                    if rt.config()['enabled']:w['grants'][rt.provider]=rt.config()['grant_id']
                for key in ('max_parallel','max_calls','reviewer','delegate_stop','max_hops','max_messages'):w[key]=merged[key]
                if merged['expires_minutes']!=project['options'].get('expires_minutes') or not w.get('expires'):w['expires']=time.time()+merged['expires_minutes']*60
                for a in [planning.workflows.manager(w)]+w['agents']:
                    rt=planning.workflows.runtime(a);cfg=rt.config()
                    cfg['max_seconds']=min(merged['max_seconds'],cfg.get('authorized_max_seconds',merged['max_seconds']))
                    with self.hub.tx():self.hub.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(rt.config_key,json.dumps(cfg,ensure_ascii=False)))
                planning.workflows.save(w)
            with self.hub.tx():
                self.hub.db.execute('INSERT OR REPLACE INTO project_options VALUES(?,?)',(project_id,json.dumps(merged,ensure_ascii=False)))
                self.hub.db.execute("INSERT OR REPLACE INTO settings VALUES('max_parallel',?)",(str(merged['max_parallel']),))
                for row in self.hub.db.execute("SELECT id,body FROM planning_sessions WHERE json_extract(body,'$.project_id')=?",(project_id,)).fetchall():
                    plan=json.loads(row['body']);plan['options']=merged;self.hub.db.execute('UPDATE planning_sessions SET body=? WHERE id=?',(json.dumps(plan,ensure_ascii=False),row['id']))
                self.hub.audit(actor,'project.options_updated',{'project':project_id,'options':merged})
        return self.get(project_id)

    def delete(self,actor,project_id):
        self.hub.require(actor,{'user'});self.get(project_id)
        workflows=self.hub.planning.workflows
        with workflows.lock:
            for w in workflows.snapshot('user'):
                if w.get('project_id')==project_id:workflows.stop(actor,w['id'])
            for row in self.hub.db.execute("SELECT body FROM planning_sessions WHERE json_extract(body,'$.project_id')=?",(project_id,)).fetchall():
                plan=json.loads(row[0])
                if plan.get('pending'):
                    run=self.hub.db.execute('SELECT provider,id FROM executions WHERE id=?',(plan['pending'],)).fetchone()
                    if run:
                        rt=next((r for r in workflows.runtimes if r.provider==run['provider']),None)
                        if rt:rt.stop(actor,run['id'])
                plan['pending']=None;plan['status']='cancelled';self.hub.planning.save(plan)
            with self.hub.tx():
                for row in self.hub.db.execute("SELECT id,body FROM hub_timers WHERE json_extract(body,'$.project_id')=?",(project_id,)).fetchall():
                    timer=json.loads(row['body']);timer['state']='cancelled';timer['reason']='项目已删除';self.hub.db.execute('UPDATE hub_timers SET body=? WHERE id=?',(json.dumps(timer,ensure_ascii=False),row['id']))
                self.hub.db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)",('deleted_project:'+project_id,'true'))
                self.hub.audit(actor,'project.deleted',{'project':project_id,'files_preserved':True})
        return {'ok':True,'files_preserved':True}

    def select(self,actor,project_id):
        self.hub.require(actor,{'user'});project=self.get(project_id)
        with self.hub.tx():self.hub.db.execute("INSERT OR REPLACE INTO settings VALUES('last_opened_project',?)",(project_id,))
        return project

    def tag(self):
        with self.hub.lock:
            marker=tuple(self.hub.db.execute('SELECT (SELECT MAX(rowid) FROM messages),(SELECT MAX(rowid) FROM tasks),(SELECT MAX(finished) FROM executions),(SELECT COUNT(*) FROM workflows),(SELECT COUNT(*) FROM planning_sessions)').fetchone())
        if marker==getattr(self,'tag_marker',None):return
        self.tag_marker=marker
        with self.hub.tx():
            if not self.hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='workflows'").fetchone():return
            for row in self.hub.db.execute('SELECT body FROM workflows').fetchall():
                w=json.loads(row[0]);ident=w.get('project_id') or w['id']
                self.hub.db.execute('INSERT OR IGNORE INTO hub_projects VALUES(?,?,?,?)',(ident,w.get('name') or w['requirement'].splitlines()[0][:60],w['cwd'],w['created']))
                if not w.get('project_id'):
                    w['project_id']=ident;self.hub.db.execute('UPDATE workflows SET body=? WHERE id=?',(json.dumps(w,ensure_ascii=False),w['id']))
                self.hub.db.execute('UPDATE tasks SET project_id=? WHERE project_id IS NULL AND id IN (SELECT task FROM workflow_steps WHERE workflow=?)',(ident,w['id']))
                self.hub.db.execute('UPDATE messages SET project_id=? WHERE project_id IS NULL AND (id IN (SELECT e.message_id FROM executions e JOIN workflow_steps s ON s.task=e.task_id WHERE s.workflow=?) OR id IN (SELECT message FROM wakeups WHERE workflow=?))',(ident,w['id'],w['id']))
                for run in self.hub.db.execute('SELECT e.id FROM executions e JOIN workflow_steps s ON s.task=e.task_id WHERE s.workflow=?',(w['id'],)).fetchall():
                    self.hub.db.execute('UPDATE messages SET project_id=? WHERE project_id IS NULL AND (request_key LIKE ? OR request_key=?)',(ident,'execution:'+run[0]+':%','report:'+run[0]))

            if self.hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='planning_sessions'").fetchone():
                for row in self.hub.db.execute('SELECT body FROM planning_sessions').fetchall():
                    p=json.loads(row[0]);ident=p.get('project_id') or p.get('workflow_id')
                    if not ident:continue
                    if not p.get('project_id'):p['project_id']=ident;self.hub.db.execute('UPDATE planning_sessions SET body=? WHERE id=?',(json.dumps(p,ensure_ascii=False),p['id']))
                    for m in p.get('history',[]):
                        if m.get('run_id'):
                            self.hub.db.execute('UPDATE tasks SET project_id=? WHERE project_id IS NULL AND id IN (SELECT task_id FROM executions WHERE id=?)',(ident,m['run_id']))
                            self.hub.db.execute('UPDATE messages SET project_id=? WHERE project_id IS NULL AND (id IN (SELECT message_id FROM executions WHERE id=?) OR request_key LIKE ?)',(ident,m['run_id'],'execution:'+m['run_id']+':%'))
            # Prepared task messages already belong to a workflow before any execution exists.
            for row in self.hub.db.execute("SELECT s.task,w.body FROM workflow_steps s JOIN workflows w ON w.id=s.workflow").fetchall():
                workflow=json.loads(row['body']);project=workflow.get('project_id') or workflow['id']
                prefix='[task:'+row['task']+'] '
                self.hub.db.execute('UPDATE messages SET project_id=? WHERE substr(body,1,?)=? AND (project_id IS NULL OR project_id!=?)',(project,len(prefix),prefix,project))
            # Unknown legacy messages stay unscoped, never guessed into another project.
    def state(self,state,ident=None):
        with self.hub.lock:
            state['projects']=[{**dict(r),'options':json.loads(r['options_body'] or '{}')} for r in self.hub.db.execute("SELECT p.*,o.body options_body FROM hub_projects p LEFT JOIN project_options o ON o.project_id=p.id WHERE NOT EXISTS (SELECT 1 FROM settings d WHERE d.key='deleted_project:'||p.id) ORDER BY p.created DESC")]
            saved=self.hub.db.execute("SELECT value FROM settings WHERE key='last_opened_project'").fetchone()
            remembered=saved[0] if saved else None
            valid_ids={p['id'] for p in state['projects']}
            state['last_opened_project']=remembered if remembered in valid_ids else None
            if not ident or ident not in valid_ids:
                ident=state['last_opened_project'] or (state['projects'][0]['id'] if state['projects'] else None)
            state['selected_project']=ident
            manager_row=self.hub.db.execute('SELECT value FROM settings WHERE key=?',('project_manager:'+str(ident),)).fetchone()
            state['selected_manager']=project_manager(self.hub,ident)
            if not ident:return state
            state['tasks']=[dict(r) for r in self.hub.db.execute('SELECT * FROM tasks WHERE project_id=? ORDER BY created',(ident,))]
            state['messages']=[dict(r) for r in self.hub.db.execute('SELECT * FROM messages WHERE project_id=? ORDER BY created DESC LIMIT 300',(ident,))]
            # Preserve direct user conversations independently of noisy agent traffic.
            state['manager_messages']=[dict(r) for r in self.hub.db.execute("SELECT * FROM messages WHERE project_id=? AND (sender='user' OR recipient='user') ORDER BY created DESC LIMIT 300",(ident,))]
            discussion_inputs={r['message_id']:dict(r) for r in self.hub.db.execute('SELECT q.* FROM manager_discussion_inputs q JOIN messages m ON m.id=q.message_id WHERE m.project_id=?',(ident,))} if self.hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='manager_discussion_inputs'").fetchone() else {}
            for message in state['messages']+state['manager_messages']:
                linked=discussion_inputs.get(message['id'])
                if linked:
                    message['discussion_session_id']=linked['session_id']
                    message['discussion_run_id']=linked['run_id']
            task_ids={task['id'] for task in state['tasks']}
            for message in state['messages']+state['manager_messages']:
                body=message.get('body') or ''
                if body.startswith('[task:') and body[6:38] in task_ids and body[38:40]=='] ':message['origin']='platform_task'
            # A queue retained behind a stopped/blocked project is not ready for pickup.
            for message in state['messages']:
                if message['status']!='pending':continue
                wake=self.hub.db.execute('SELECT a.status,a.note,w.body FROM wakeups a LEFT JOIN workflows w ON w.id=a.workflow WHERE a.message=?',(message['id'],)).fetchone()
                if wake:
                    workflow=json.loads(wake['body']) if wake['body'] else {}
                    if wake['status']=='held' or workflow.get('status') in ('blocked','paused','stopped','needs_attention'):
                        message['status']='waiting_project';message['delivery_reason']=wake['note']
                execution=self.hub.db.execute('SELECT status FROM executions WHERE message_id=? ORDER BY created DESC LIMIT 1',(message['id'],)).fetchone()
                if execution and execution['status'] in ('completed','failed','cancelled','uncertain'):
                    message['status']=execution['status']
            state['calls']=[dict(r) for r in self.hub.db.execute('SELECT * FROM calls WHERE project_id=? ORDER BY created DESC LIMIT 100',(ident,))]
            state['workflows']=[json.loads(r[0]) for r in self.hub.db.execute("SELECT body FROM workflows WHERE json_extract(body,'$.project_id')=? ORDER BY rowid DESC LIMIT 20",(ident,))]
            for w in state['workflows']:
                steps=[dict(r) for r in self.hub.db.execute('SELECT s.*,e.id run_id,e.status,e.result,e.prompt,e.actual_input FROM workflow_steps s LEFT JOIN executions e ON e.task_id=s.task WHERE s.workflow=? ORDER BY seq',(w['id'],))];w['steps']=steps;w['calls_used']=len(steps)
            state['planning']=[json.loads(r[0]) for r in self.hub.db.execute("SELECT body FROM planning_sessions WHERE json_extract(body,'$.project_id')=? ORDER BY rowid DESC LIMIT 20",(ident,))]
            for provider in ('codex','antigravity','deepseek') if 'deepseek' in state else ('codex','antigravity'):
                state[provider]['runs']=[dict(r) for r in self.hub.db.execute('SELECT e.* FROM executions e JOIN tasks t ON t.id=e.task_id WHERE t.project_id=? AND e.provider=? ORDER BY e.created DESC LIMIT 100',(ident,provider))]
                state[provider]['events']=[dict(r) for r in self.hub.db.execute('SELECT v.* FROM execution_events v JOIN executions e ON e.id=v.run_id JOIN tasks t ON t.id=e.task_id WHERE t.project_id=? AND e.provider=? ORDER BY v.seq DESC LIMIT 100',(ident,provider))]
            if 'integration_runs' in state:state['integration_runs']=[dict(r) for r in self.hub.db.execute("SELECT e.* FROM executions e JOIN tasks t ON t.id=e.task_id WHERE t.project_id=? AND e.provider LIKE 'integration:%' ORDER BY e.created DESC LIMIT 150",(ident,))]
            wfids={w['id'] for w in state['workflows']};taskids={t['id'] for t in state['tasks']};runids={r['id'] for provider in (('codex','antigravity','deepseek') if 'deepseek' in state else ('codex','antigravity')) for r in state[provider]['runs']}
            runids.update(r['id'] for r in state.get('integration_runs',[]))
            state['audit']=[a for a in state['audit'] if (lambda d:d.get('project') in wfids|{ident} or d.get('run_id') in runids or d.get('task') in taskids)(json.loads(a['detail']))]
            state['coordination']['wakeups']=[a for a in state['coordination']['wakeups'] if a['workflow'] in wfids]
            workerids={r[0] for r in self.hub.db.execute("SELECT e.id FROM executions e JOIN workflow_steps s ON s.task=e.task_id WHERE s.kind IN ('work','message','check')")}
            state['coordination']['reports']=[a for a in state['coordination']['reports'] if a['run'] in runids&workerids]
            latest=state['workflows'][0] if state['workflows'] else None
            manager_progress=latest.get('manager_progress') if latest else None
            state['project']=({'progress':100,'note':latest['report'],'by':latest.get('completion',{}).get('by') or latest.get('manager'),'updated':latest.get('completion',{}).get('at'),'source':'completed'} if latest and latest['status']=='completed' else {**(manager_progress or {'progress':None,'note':'等待经理汇报项目进度'}),'source':'manager' if manager_progress else 'not_reported'})
            if latest:
                for a in state['agents']:a['role']=latest.get('roles',{}).get(a['id'],a['role'])
        return state
