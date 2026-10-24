"""Public answer drafts only. Never collect private thought/reasoning chunks."""
import json
import threading
import time
from .core import HubError


class LiveReplies:
    def __init__(self, hub):
        self.hub = hub
        self.lock = threading.RLock()
        self.pending = {}
        self.next_flush = 0
        with hub.tx():
            hub.db.execute('CREATE TABLE IF NOT EXISTS reply_drafts(run_id TEXT PRIMARY KEY,body TEXT)')

    def update(self, run_id, text='', replace=False, summary=None, phase=None):
        # Provider adapters call this only for visible assistant output or a public summary.
        with self.lock:
            current = self.pending.get(run_id)
            if current is None:
                with self.hub.lock:
                    row = self.hub.db.execute('SELECT body FROM reply_drafts WHERE run_id=?', (run_id,)).fetchone()
                current = json.loads(row[0]) if row else {'run_id': run_id, 'text': '', 'summary': '', 'phase': '', 'revision': 0}
            current = dict(current)
            if replace: current['text'] = text
            else: current['text'] += text
            if summary is not None: current['summary'] += summary
            if phase is not None: current['phase'] = phase
            current.update(revision=current['revision'] + 1, updated=time.time())
            self.pending[run_id] = current

    def flush(self):
        if time.monotonic() < self.next_flush: return
        self.next_flush = time.monotonic() + .25
        # Serialize the short checkpoint with appenders; a concurrent delta must never lose its prefix.
        with self.lock:
            if self.pending:
                with self.hub.tx():
                    for ident,data in self.pending.items():
                        self.hub.db.execute('INSERT OR REPLACE INTO reply_drafts VALUES(?,?)',(ident,json.dumps(data,ensure_ascii=False)))
                self.pending={}

    def read(self, run_id, project_id):
        with self.hub.lock:
            row = self.hub.db.execute('SELECT e.*,t.project_id FROM executions e JOIN tasks t ON t.id=e.task_id WHERE e.id=?', (run_id,)).fetchone()
            if not row: raise HubError('执行不存在')
            scope = row['session_scope'] or ''
            belongs = row['project_id'] == project_id or scope in ('hub-project:' + str(project_id), 'chat:' + str(project_id))
            if not belongs:
                found = self.hub.db.execute("SELECT 1 FROM workflow_steps s JOIN workflows w ON w.id=s.workflow WHERE s.task=? AND json_extract(w.body,'$.project_id')=?", (row['task_id'], project_id)).fetchone()
                belongs = bool(found)
            if not project_id or not belongs: raise HubError('执行不属于当前项目')
            saved = self.hub.db.execute('SELECT body FROM reply_drafts WHERE run_id=?', (run_id,)).fetchone()
            status, agent = row['status'], row['agent']
        with self.lock:
            draft = self.pending.get(run_id)
            draft = dict(draft) if draft else json.loads(saved[0]) if saved else {'run_id': run_id, 'text': '', 'summary': '', 'phase': '', 'revision': 0}
        return {**draft, 'agent': agent, 'status': status}

    def snapshot(self, project_id):
        if not project_id: return []
        with self.hub.lock:
            rows = self.hub.db.execute("SELECT e.id FROM executions e JOIN tasks t ON t.id=e.task_id WHERE e.status IN ('queued','running','interrupting','waiting_quota') AND (t.project_id=? OR e.session_scope=?) ORDER BY e.created DESC LIMIT 20", (project_id, 'hub-project:' + project_id)).fetchall()
        return [self.read(r[0], project_id) for r in rows]
