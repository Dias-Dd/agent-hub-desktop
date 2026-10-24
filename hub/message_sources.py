"""Repair generated review envelopes without relabeling human messages."""
import json,time

def review_sender(db, task):
    events=db.execute('SELECT body FROM workflow_events WHERE manager_task=?',(task,)).fetchall()
    if len(events)==1:
        try:event=json.loads(events[0][0])
        except (TypeError,ValueError):return '平台'
        if not isinstance(event,dict):return '平台'
        if event.get('type')=='message':
            original=db.execute('SELECT sender,body FROM messages WHERE id=?',(event.get('message_id'),)).fetchone()
            if original and original[0]=='user' and not (original[1] or '').startswith('[task:'):return 'user'
    return '平台'

def repair_platform_sources(hub,terminal_only=False):
    """Only messages linked to an internally generated review task are eligible.

    Old prompts already sent to providers stay intact as execution evidence.
    """
    repaired=[]
    with hub.tx():
        tables={r[0] for r in hub.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'messages','tasks','executions','workflow_steps','workflow_events'}.issubset(tables):return repaired
        rows=hub.db.execute("SELECT m.id,m.body,s.task FROM messages m JOIN executions e ON e.message_id=m.id JOIN workflow_steps s ON s.task=e.task_id WHERE s.kind='review' AND m.sender='user' UNION SELECT m.id,m.body,s.task FROM messages m JOIN workflow_steps s ON s.task=substr(m.body,7,32) JOIN tasks t ON t.id=s.task WHERE m.body='[task:'||s.task||'] '||t.title AND abs(m.created-t.created)<1 AND s.kind='review' AND m.sender='user' AND NOT EXISTS(SELECT 1 FROM executions e WHERE e.message_id=m.id)").fetchall()
        for row in rows:
            if not row[1].startswith('[task:'+row[2]+'] '):continue
            if review_sender(hub.db,row[2])=='user':continue
            if terminal_only:
                run=hub.db.execute('SELECT status,finished FROM executions WHERE message_id=?',(row[0],)).fetchone()
                if not run or run[0] in ('queued','running','interrupting','waiting_quota') or not run[1] or run[1]>time.time()-60:continue
            hub.db.execute("UPDATE messages SET sender='平台' WHERE id=? AND sender='user'",(row[0],))
            repaired.append(row[0])
    return repaired
