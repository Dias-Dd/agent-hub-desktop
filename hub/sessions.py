"""Durable provider conversation IDs; task delivery is separate from conversation history."""
import hashlib,json,time

class Sessions:
    def __init__(self,hub):
        self.hub=hub
        with hub.tx():
            hub.db.execute("CREATE TABLE IF NOT EXISTS provider_session_roots(provider TEXT,agent TEXT,session_id TEXT,cwd TEXT,PRIMARY KEY(provider,agent,session_id))")
            hub.db.execute("CREATE TABLE IF NOT EXISTS session_policies(key TEXT PRIMARY KEY,digest TEXT,session_id TEXT)")
            hub.db.execute("CREATE TABLE IF NOT EXISTS agent_sessions(key TEXT PRIMARY KEY,scope TEXT,provider TEXT,agent TEXT,session_id TEXT,state TEXT,updated REAL)")
            columns={r[1] for r in hub.db.execute('PRAGMA table_info(executions)')}
            if {'provider','agent','thread_id','cwd','created','id'}.issubset(columns):
                hub.db.execute('INSERT OR IGNORE INTO provider_session_roots SELECT provider,agent,thread_id,cwd FROM executions WHERE thread_id IS NOT NULL AND cwd IS NOT NULL ORDER BY created,id')
    def has_table(self,name):
        return bool(self.hub.db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(name,)).fetchone())

    def scope(self,run):
        """Provider memory belongs to the visible project, not a discussion/workflow."""
        with self.hub.lock:
            scope=run.get('session_scope')
            while scope and scope.startswith('dialogue:'):scope=scope[len('dialogue:'):]
            if scope and scope.startswith('hub-project:'):return scope
            if scope and scope.startswith('chat:'):return 'hub-project:'+scope[5:]
            if scope and scope.startswith('discussion:') and self.has_table('planning_sessions'):
                row=self.hub.db.execute('SELECT body FROM planning_sessions WHERE id=?',(scope[11:],)).fetchone()
                if row:
                    discussion=json.loads(row[0]);return 'hub-project:'+(discussion.get('project_id') or 'default')
            if scope and scope.startswith('project:'):
                ident=scope[8:]
                row=self.hub.db.execute('SELECT body FROM workflows WHERE id=?',(ident,)).fetchone() if self.has_table('workflows') else None
                project=json.loads(row[0]) if row else {}
                return 'hub-project:'+(project.get('project_id') or ident)
            if scope:return scope
            if self.has_table('workflow_steps'):
                row=self.hub.db.execute('SELECT w.body FROM workflow_steps s JOIN workflows w ON w.id=s.workflow WHERE s.task=?',(run['task_id'],)).fetchone()
                if row:
                    project=json.loads(row[0]);return 'hub-project:'+(project.get('project_id') or project['id'])
        return 'standalone:'+run['grant_id']+':'+run.get('purpose','task')

    def reset_epoch(self,run):
        scope=self.scope(run)
        if not scope.startswith('hub-project:'):return 0
        with self.hub.lock:
            row=self.hub.db.execute('SELECT value FROM settings WHERE key=?',('project_reset_epoch:'+scope[12:],)).fetchone()
        return float(row[0]) if row else 0

    def key(self,run):
        scope=self.scope(run)
        identity=[scope,run['provider'],run['agent'],run['model']]
        epoch=self.reset_epoch(run)
        if epoch:identity.append(epoch)
        # Grants still gate every execution, but renewing permission must not erase memory.
        if not scope.startswith('hub-project:'):identity += [run['cwd'],run['permission'],run['grant_id']]
        return hashlib.sha256(json.dumps(identity,ensure_ascii=False).encode()).hexdigest()

    def session_details(self,row,run):
        result=dict(row)
        previous=self.hub.db.execute('SELECT purpose FROM executions WHERE provider=? AND agent=? AND thread_id=? AND id!=? ORDER BY created DESC LIMIT 1',(run['provider'],run['agent'],result['session_id'],run['id'])).fetchone()
        result['previous_purpose']=previous[0] if previous else None
        root=self.hub.db.execute('SELECT cwd FROM provider_session_roots WHERE provider=? AND agent=? AND session_id=?',(run['provider'],run['agent'],result['session_id'])).fetchone()
        if not root:root=self.hub.db.execute('SELECT cwd FROM executions WHERE provider=? AND agent=? AND thread_id=? ORDER BY created,id LIMIT 1',(run['provider'],run['agent'],result['session_id'])).fetchone()
        result['cwd']=root[0] if root else run['cwd']
        return result

    def get(self,run):
        key=self.key(run);scope=self.scope(run);epoch=self.reset_epoch(run)
        with self.hub.lock:
            row=self.hub.db.execute('SELECT * FROM agent_sessions WHERE key=?',(key,)).fetchone()
            if row:return self.session_details(row,run)
            if scope.startswith('hub-project:'):
                # Reuse the most recent existing project conversation, including old scope formats.
                for old in self.hub.db.execute('SELECT * FROM agent_sessions WHERE provider=? AND agent=? ORDER BY updated DESC',(run['provider'],run['agent'])).fetchall():
                    if old['updated']>=epoch and self.scope({**run,'session_scope':old['scope']})==scope:
                        model=self.hub.db.execute('SELECT model FROM executions WHERE provider=? AND agent=? AND thread_id=? ORDER BY created DESC LIMIT 1',(run['provider'],run['agent'],old['session_id'])).fetchone()
                        if not model or model[0]==run['model']:return self.session_details(old,run)
                for old in self.hub.db.execute("SELECT * FROM executions WHERE provider=? AND agent=? AND model=? AND thread_id IS NOT NULL AND status='completed' AND id!=? ORDER BY created DESC",(run['provider'],run['agent'],run['model'],run['id'])).fetchall():
                    if old['created']>=epoch and self.scope(dict(old))==scope:return self.session_details({'session_id':old['thread_id'],'state':'adopted'},run)
        return None
    def context_keys(self,run):
        """Legacy HTTP-provider history keys, newest matching project first."""
        keys=[self.key(run)];scope=self.scope(run)
        if run['agent']=='deepseek-9':keys.append(self.key({**run,'agent':'deepseek'}))
        with self.hub.lock:
            rows=self.hub.db.execute('SELECT * FROM executions WHERE provider=? AND agent=? AND model=? ORDER BY created DESC',(run['provider'],run['agent'],run['model'])).fetchall()
            for row in rows:
                old=dict(row)
                if old['created']<self.reset_epoch(run) or self.scope(old)!=scope:continue
                raw=old.get('session_scope')
                if not raw and self.has_table('workflow_steps'):
                    step=self.hub.db.execute('SELECT workflow FROM workflow_steps WHERE task=?',(old['task_id'],)).fetchone()
                    if step:raw='project:'+step[0]
                if not raw:raw='standalone:'+old['grant_id']+':'+old.get('purpose','task')
                variants=[raw]
                if old.get('purpose')=='question':variants.append('dialogue:'+raw)
                for variant in variants:
                    identity=[variant,old['provider'],old['agent'],old['model'],old['cwd'],old['permission'],old['grant_id']]
                    for ascii_only in (False,True):
                        key=hashlib.sha256(json.dumps(identity,ensure_ascii=ascii_only).encode()).hexdigest()
                        if key not in keys:keys.append(key)
                        if old['agent']=='deepseek-9':
                            legacy=list(identity);legacy[2]='deepseek'
                            key=hashlib.sha256(json.dumps(legacy,ensure_ascii=ascii_only).encode()).hexdigest()
                            if key not in keys:keys.append(key)
        return keys

    def revoked(self,run):
        if not self.has_table('execution_revocations'):return False
        return bool(self.hub.db.execute('SELECT 1 FROM execution_revocations WHERE run=?',(run.get('id'),)).fetchone())

    def bind(self,run,session_id,state='ready',cwd=None):
        if not isinstance(session_id,str) or not session_id:raise ValueError('provider session ID required')
        with self.hub.tx():
            if self.revoked(run):return
            self.hub.db.execute('INSERT OR IGNORE INTO provider_session_roots VALUES(?,?,?,?)',(run['provider'],run['agent'],session_id,cwd or run['cwd']))
            self.hub.db.execute('INSERT OR REPLACE INTO agent_sessions VALUES(?,?,?,?,?,?,?)',(self.key(run),self.scope(run),run['provider'],run['agent'],session_id,state,time.time()))
    def state(self,run,state):
        with self.hub.tx():
            if self.revoked(run):return
            self.hub.db.execute('UPDATE agent_sessions SET state=?,updated=? WHERE key=?',(state,time.time(),self.key(run)))

    def policy_needed(self,run,instructions):
        session=self.get(run)
        if not session:return True
        if session.get('previous_purpose') in ('discussion','question'):return True
        with self.hub.lock:row=self.hub.db.execute('SELECT * FROM session_policies WHERE key=?',(self.key(run),)).fetchone()
        digest=hashlib.sha256((instructions+'\n'+run['grant_id']).encode()).hexdigest()
        return not row or row['digest']!=digest or row['session_id']!=session['session_id']

    def remember_policy(self,run,instructions):
        session=self.get(run)
        if not session:return
        with self.hub.tx():
            if self.revoked(run):return
            self.hub.db.execute('INSERT OR REPLACE INTO session_policies VALUES(?,?,?)',(self.key(run),hashlib.sha256((instructions+'\n'+run['grant_id']).encode()).hexdigest(),session['session_id']))
