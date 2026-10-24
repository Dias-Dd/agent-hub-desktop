"""Receipt reconciliation only: never submit, wake, or replay a model execution."""
import json

def reconcile(hub):
    with hub.tx():
        users=hub.db.execute("UPDATE messages SET status='user_delivered',lease=NULL WHERE recipient='user' AND status IN ('pending','paused','delivered','acknowledged')").rowcount
        tables={r[0] for r in hub.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        archived=0
        if {'workflows','executions','wakeups'}<=tables and 'project_id' in {r[1] for r in hub.db.execute('PRAGMA table_info(messages)')}:
            # A newer active workflow or in-flight execution must keep its messages intact.
            latest={}
            for row in hub.db.execute('SELECT body FROM workflows ORDER BY rowid DESC'):
                w=json.loads(row[0]);project=w.get('project_id')
                if project and project not in latest:latest[project]=w
            for project,w in latest.items():
                if w.get('status') not in ('completed','cancelled','failed'):continue
                if hub.db.execute("SELECT 1 FROM workflows WHERE json_extract(body,'$.project_id')=? AND json_extract(body,'$.status') NOT IN ('completed','cancelled','failed')",(project,)).fetchone():continue
                if hub.db.execute("SELECT 1 FROM executions e JOIN tasks t ON t.id=e.task_id WHERE t.project_id=? AND e.status IN ('queued','running','interrupting','waiting_quota')",(project,)).fetchone():continue
                archived+=hub.db.execute("UPDATE messages SET status='archived',lease=NULL,result=CASE WHEN result IS NULL OR result='' THEN '项目已结束；旧消息归档，未重新投递，不表示已处理' ELSE result END WHERE project_id=? AND recipient!='user' AND NOT (sender='user' AND body NOT LIKE '[task:%') AND status IN ('pending','paused','delivered','acknowledged')",(project,)).rowcount
            hub.db.execute("UPDATE wakeups SET status='archived',note='项目已结束；历史消息保留，不再唤醒' WHERE message IN (SELECT id FROM messages WHERE status='archived') AND status!='archived'")
        if users or archived:hub.audit('supervisor','message.receipts_reconciled',{'user_delivered':users,'archived':archived})
        return {'user_delivered':users,'archived':archived}
