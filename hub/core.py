"""Single-process transactional hub; durable inbox with at-least-once delivery."""
import contextlib
import hashlib
import json
import math
import secrets
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from .identities import AGENTS, QUOTA_READERS, prompt
from .manager_identity import managers,resolve as project_manager

class HubError(Exception):
    pass

def uid():
    return uuid.uuid4().hex

def number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
        raise HubError(f'number must be between {low} and {high}')
    return value

def text(value, limit=20000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise HubError(f'nonempty text required, max {limit}')
    return value

class Hub:
    def __init__(self, directory, recover=True):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.directory / 'hub.sqlite3', check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
        PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000;
        CREATE TABLE IF NOT EXISTS agents(id TEXT PRIMARY KEY,model TEXT,role TEXT,prompt TEXT,status TEXT DEFAULT 'offline',heartbeat REAL,enabled INTEGER DEFAULT 1,active TEXT);
        CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY,sender TEXT,recipient TEXT,body TEXT,mode TEXT,status TEXT,created REAL,delivered REAL,acked REAL,lease REAL,attempts INTEGER DEFAULT 0,result TEXT,request_key TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS dedup ON messages(sender,request_key,recipient) WHERE request_key IS NOT NULL;
        CREATE INDEX IF NOT EXISTS messages_recent ON messages(created DESC);
        CREATE INDEX IF NOT EXISTS messages_pending ON messages(status,recipient,created);
        CREATE INDEX IF NOT EXISTS messages_sender_recent ON messages(sender,created DESC);
        CREATE INDEX IF NOT EXISTS messages_recipient_recent ON messages(recipient,created DESC);
        CREATE TABLE IF NOT EXISTS project_queue_positions(item_id TEXT PRIMARY KEY,position REAL);
        CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,agent TEXT,title TEXT,assigned_by TEXT,progress REAL DEFAULT 0,status TEXT DEFAULT 'assigned',note TEXT DEFAULT '',created REAL);
        CREATE INDEX IF NOT EXISTS tasks_status ON tasks(status,agent);
        CREATE TABLE IF NOT EXISTS quotas(agent TEXT PRIMARY KEY,remaining REAL,resets_at REAL,source TEXT,updated REAL);
        CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY AUTOINCREMENT,ts REAL,actor TEXT,event TEXT,detail TEXT);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS long_term_memory_versions(revision INTEGER PRIMARY KEY AUTOINCREMENT,user TEXT NOT NULL,memory TEXT NOT NULL,locked INTEGER NOT NULL,actor TEXT NOT NULL,reason TEXT NOT NULL,project_id TEXT,created REAL NOT NULL);
        INSERT OR IGNORE INTO long_term_memory_versions(revision,user,memory,locked,actor,reason,created) VALUES(0,'','',0,'user','initial',CAST(strftime('%s','now') AS REAL));
        CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY,agent TEXT,prompt TEXT,digest TEXT,status TEXT,reserve_cents INTEGER,created REAL,expires REAL,result TEXT);
        CREATE INDEX IF NOT EXISTS calls_recent ON calls(created DESC);
        ''')
        self.db.execute('PRAGMA cache_size=-16384')
        credentials = self.directory / 'credentials.json'
        if not credentials.exists():
            credentials.write_text(json.dumps({a: secrets.token_urlsafe(32) for a in ['user'] + [x[0] for x in AGENTS]}, indent=2), encoding='utf-8')
        self.tokens = json.loads(credentials.read_text(encoding='utf-8'))
        with self.tx():
            for a in AGENTS:
                self.db.execute('INSERT OR IGNORE INTO agents(id,model,role,prompt) VALUES(?,?,?,?)', (*a[:3], prompt(a)))
                customized=self.db.execute("SELECT 1 FROM sqlite_master WHERE name='agent_profiles'").fetchone() and self.db.execute('SELECT 1 FROM agent_profiles WHERE id=?',(a[0],)).fetchone()
                if not customized:self.db.execute('UPDATE agents SET model=?,prompt=? WHERE id=?', (a[1],prompt(a), a[0]))
                self.db.execute("INSERT OR IGNORE INTO quotas VALUES(?,NULL,NULL,'unknown',?)", (a[0], time.time()))
            self.db.execute("INSERT OR IGNORE INTO settings VALUES('project',?)", (json.dumps({'progress': 0, 'note': '尚未汇报'}),))
            self.db.execute("INSERT OR IGNORE INTO settings VALUES('budget_cents','0')")
            if recover:
                self.db.execute("UPDATE messages SET status='pending',lease=NULL WHERE status IN ('delivered','acknowledged') AND recipient!='user'")
                self.db.execute("UPDATE agents SET status='offline',active=NULL")
                self.db.execute("UPDATE calls SET status='uncertain',result='服务重启；可能已计费，禁止自动重试' WHERE status='running'")
                self.audit('supervisor', 'recovered', {})

    @contextlib.contextmanager
    def tx(self):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK')
                raise

    def audit(self, actor, event, detail):
        self.db.execute('INSERT INTO audit(ts,actor,event,detail) VALUES(?,?,?,?)', (time.time(), actor, event, json.dumps(detail, ensure_ascii=False)))

    def auth(self, token):
        for actor, secret in self.tokens.items():
            if secrets.compare_digest(secret, token):
                return actor
        raise HubError('unauthorized')

    def require(self, actor, allowed):
        if actor not in allowed:
            raise HubError('forbidden')

    def agent(self, ident):
        with self.lock:
            row = self.db.execute('SELECT * FROM agents WHERE id=?', (ident,)).fetchone()
        if row is None:
            raise HubError('unknown agent')
        return dict(row)

    def snapshot(self, actor):
        with self.lock:
            agents = [dict(r) for r in self.db.execute('SELECT * FROM agents')]
            can_read_quotas=actor=='user' or actor in managers(self)
            for a in agents:
                if actor != 'user' and a['id'] != actor:
                    a.pop('prompt')
                a['quota'] = dict(self.db.execute('SELECT * FROM quotas WHERE agent=?', (a['id'],)).fetchone()) if can_read_quotas or actor == a['id'] else {'source': 'restricted'}

            where, args = ('', ()) if actor == 'user' else ('WHERE sender=? OR recipient=?', (actor, actor))
            return {'agents': agents, 'tasks': [dict(r) for r in self.db.execute('SELECT * FROM tasks ORDER BY created')],
                    'messages': [dict(r) for r in self.db.execute(f'SELECT * FROM messages {where} ORDER BY created DESC LIMIT 300', args)],
                    'project': json.loads(self.db.execute("SELECT value FROM settings WHERE key='project'").fetchone()[0]),
                    'audit': [dict(r) for r in self.db.execute('SELECT * FROM audit ORDER BY seq DESC LIMIT 100')] if actor == 'user' else [],
                    'calls': [dict(r) for r in self.db.execute('SELECT * FROM calls ORDER BY created DESC LIMIT 100')] if actor == 'user' else [],
                    'budget_cents': int(self.db.execute("SELECT value FROM settings WHERE key='budget_cents'").fetchone()[0]) if actor == 'user' else None,
                    'simulation': False, 'time': time.time()}

    def send(self, actor, recipient, body, mode='queue', request_key=None):
        text(body)
        if mode not in ('immediate', 'queue'):
            raise HubError('mode must be immediate or queue')
        recipients = [r[0] for r in self.db.execute('SELECT id FROM agents WHERE enabled=1')] if recipient == '*' else [recipient]
        if recipient == '*':
            self.require(actor, {'user'}|managers(self))
        for r in recipients:
            if r != 'user': self.agent(r)
        if request_key is not None: text(request_key, 128)
        ids = []
        with self.tx():
            for r in recipients:
                old = self.db.execute('SELECT * FROM messages WHERE sender=? AND recipient=? AND request_key=?', (actor, r, request_key)).fetchone() if request_key else None
                if old:
                    if old['body'] != body or old['mode'] != mode: raise HubError('idempotency key conflict')
                    ids.append(old['id'])
                    continue
                ident = uid()
                self.db.execute('INSERT INTO messages(id,sender,recipient,body,mode,status,created,request_key) VALUES(?,?,?,?,?,?,?,?)', (ident, actor, r, body, mode, 'user_delivered' if r == 'user' else 'pending', time.time(), request_key))
                ids.append(ident)
            self.audit(actor, 'message.sent', {'ids': ids, 'mode': mode})
        return ids

    def heartbeat(self, actor, status):
        self.agent(actor)
        if status not in ('idle', 'busy'): raise HubError('invalid state')
        with self.tx():
            a = self.agent(actor)
            if status == 'idle' and a['active']: raise HubError('complete active message first')
            self.db.execute('UPDATE agents SET heartbeat=?,status=? WHERE id=?', (time.time(), status, actor))
            if a['active']:
                self.db.execute('UPDATE messages SET lease=? WHERE id=?',(time.time()+30,a['active']))
        return {'status': status}

    def poll(self, actor):
        self.agent(actor)
        with self.tx():
            a = self.agent(actor)
            if not a['enabled'] or (getattr(self,'coordination',None) and self.coordination.is_stopped(actor)): return None
            # One durable active turn; only immediate input can preempt it.
            row = self.db.execute("SELECT * FROM messages WHERE recipient=? AND ((status='pending' AND (?='idle' OR mode='immediate')) OR (status='paused' AND ?='idle')) ORDER BY CASE status WHEN 'paused' THEN 1 ELSE 0 END,CASE mode WHEN 'immediate' THEN 0 ELSE 1 END,coalesce((SELECT position FROM project_queue_positions WHERE item_id=messages.id),created),created,id LIMIT 1", (actor, a['status'], a['status'])).fetchone()
            if not row or a['status'] == 'offline': return None
            if a['active']:
                self.db.execute("UPDATE messages SET status='paused',lease=NULL,result='协作式中断，等待重新领取' WHERE id=?", (a['active'],))
                self.audit(actor, 'message.interrupted', {'id': a['active'], 'by': row['id']})
            now = time.time()
            self.db.execute("UPDATE messages SET status='delivered',delivered=?,lease=?,attempts=attempts+1 WHERE id=?", (now, now+30, row['id']))
            self.db.execute("UPDATE agents SET active=?,status='busy',heartbeat=? WHERE id=?", (row['id'], now, actor))
            self.audit(actor, 'message.delivered', {'id': row['id']})
            return dict(self.db.execute('SELECT * FROM messages WHERE id=?', (row['id'],)).fetchone())

    def ack(self, actor, message_id, complete=False, result=''):
        if not isinstance(complete, bool): raise HubError('complete must be boolean')
        if not isinstance(result, str) or len(result)>20000: raise HubError('invalid result')
        with self.tx():
            row = self.db.execute('SELECT * FROM messages WHERE id=?', (message_id,)).fetchone()
            if not row or row['recipient'] != actor: raise HubError('forbidden')
            if row['status'] == 'completed': return {'status': 'completed'}
            a = self.agent(actor)
            if a['active'] != message_id or row['status'] not in ('delivered', 'acknowledged'): raise HubError('message not active')
            status = 'completed' if complete else 'acknowledged'
            self.db.execute('UPDATE messages SET status=?,acked=?,lease=?,result=? WHERE id=?', (status,time.time(),None if complete else time.time()+30,result,message_id))
            if complete:
                self.db.execute("UPDATE agents SET active=NULL,status='idle' WHERE id=?", (actor,))
            self.audit(actor, 'message.'+status, {'id': message_id})
            return {'status': status}

    def assign(self, actor, agent, title):
        self.require(actor, {'user'}|managers(self))
        self.agent(agent); text(title, 1000)
        ident = uid()
        with self.tx():
            self.db.execute('INSERT INTO tasks(id,agent,title,assigned_by,created) VALUES(?,?,?,?,?)', (ident,agent,title,actor,time.time()))
            # Assignment and wakeup are one atomic operation.
            self.db.execute("INSERT INTO messages(id,sender,recipient,body,mode,status,created) VALUES(?,?,?,?,'queue','pending',?)", (uid(),actor,agent,'[task:'+ident+'] '+title,time.time()))
            self.audit(actor,'task.assigned', {'id':ident,'agent':agent})
        return {'id':ident}

    def progress(self, actor, task_id, progress, note, status='working'):
        number(progress,0,100); text(note, 5000)
        if status not in ('working','blocked','done'): raise HubError('invalid task status')
        if status == 'done' and progress != 100: raise HubError('done requires 100%')
        with self.tx():
            task = self.db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
            if not task or task['agent'] != actor: raise HubError('only assignee may report')
            self.db.execute('UPDATE tasks SET progress=?,note=?,status=? WHERE id=?',(progress,note,status,task_id))
            self.audit(actor,'task.progress', {'id':task_id,'progress':progress,'status':status})
        return {'ok':True}

    def project(self, actor, progress, note):
        self.require(actor, managers(self)); number(progress,0,100); text(note,5000)
        with self.tx():
            self.db.execute("UPDATE settings SET value=? WHERE key='project'", (json.dumps({'progress':progress,'note':note,'by':actor,'updated':time.time()}),))
            self.audit(actor,'project.progress', {'progress':progress})
        return {'ok':True}

    def quota(self, actor, agent, remaining=None, resets_at=None):
        self.require(actor, {'user'}); self.agent(agent)
        if remaining is not None: number(remaining,0,100)
        if resets_at is not None: number(resets_at,0,4102444800)
        with self.tx():
            self.db.execute("UPDATE quotas SET remaining=?,resets_at=?,source='manual',updated=? WHERE agent=?", (remaining,resets_at,time.time(),agent))
            self.audit(actor,'quota.manual', {'agent':agent,'remaining':remaining,'resets_at':resets_at})
        return {'ok':True}

    def enable(self, actor, agent, enabled):
        self.require(actor, {'user'}); self.agent(agent)
        if not isinstance(enabled,bool): raise HubError('enabled must be boolean')
        with self.tx():
            self.db.execute('UPDATE agents SET enabled=? WHERE id=?',(int(enabled),agent))
            self.audit(actor,'agent.enabled', {'agent':agent,'enabled':enabled})
        return {'ok':True}

    def tick(self, simulate=True, excluded=None):
        now = time.time()
        with self.tx():
            expired = self.db.execute("SELECT id,recipient FROM messages WHERE status IN ('delivered','acknowledged') AND lease<?", (now,)).fetchall()
            for m in expired:
                self.db.execute("UPDATE messages SET status='pending',lease=NULL WHERE id=?", (m['id'],))
                self.db.execute("UPDATE agents SET active=NULL,status='offline' WHERE id=? AND active=?", (m['recipient'],m['id']))
                self.audit('supervisor','lease.expired', {'id':m['id']})
            stale = self.db.execute("SELECT id FROM agents WHERE status!='offline' AND heartbeat<?", (now-15,)).fetchall()
            for a in stale:
                self.db.execute("UPDATE agents SET status='offline' WHERE id=?", (a['id'],))
                self.audit('supervisor','heartbeat.stale', {'agent':a['id']})
        if simulate:
            for ident, *_ in AGENTS:
                if (excluded and ident in excluded) or (getattr(self,'coordination',None) and self.coordination.is_stopped(ident)):continue
                a = self.agent(ident)
                if not a['enabled']: continue
                self.heartbeat(ident, 'busy' if a['active'] else 'idle')
                m = self.poll(ident)
                if m:
                    self.ack(ident,m['id'])
                    continue
                a = self.agent(ident)
                if a['active']:
                    with self.lock:
                        current = dict(self.db.execute('SELECT * FROM messages WHERE id=?',(a['active'],)).fetchone())
                    if now-current['delivered'] >= 2:
                        body = current['body']
                        if body.startswith('[task:'):
                            task_id = body.split(']',1)[0][6:]
                            self.progress(ident,task_id,100,'模拟执行完成；未生成实际工程产物','done')
                        self.ack(ident,current['id'],True,'模拟 Agent 已处理：'+body[:200])
                        self.send(ident,'user','[模拟回复] '+body[:300])
            manager=project_manager(self)
            tasks = self.snapshot(manager)['tasks']
            if tasks and self.agent(manager)['enabled'] and not excluded and not (getattr(self,'coordination',None) and self.coordination.is_stopped(manager)):
                avg = sum(t['progress'] for t in tasks)/len(tasks)
                old = self.snapshot(manager)['project']
                if old['progress'] != avg:
                    self.project(manager,avg,'模拟项目经理：任务进度等权汇总，仅演示')

    def action(self, actor, name, args):
        methods = {'snapshot':self.snapshot,'send':self.send,'heartbeat':self.heartbeat,'poll':self.poll,'ack':self.ack,'assign':self.assign,'progress':self.progress,'project':self.project,'quota':self.quota,'enable':self.enable}
        if name not in methods: raise HubError('unknown action')
        if not isinstance(args,dict): raise HubError('arguments must be object')
        try: return methods[name](actor,**args)
        except TypeError as e: raise HubError('invalid arguments') from e
