"""One unclaimed ordinary platform delivery per workflow and recipient.

Caller owns the transaction. Claimed input, human/agent messages and urgent
quota alerts are deliberately excluded; their delivery semantics stay intact.
"""
import json
import time
from .core import uid

KINDS = ('timer', 'agent_config_changed', 'quota_recovered')


def queue(hub, workflow, recipient, body, kind, creator='平台'):
    now = time.time()
    project = workflow.get('project_id') or workflow['id']
    rows = hub.db.execute("""SELECT e.id,e.body,m.id message_id,m.body message_body
        FROM workflow_events e JOIN messages m ON m.id=json_extract(e.body,'$.message_id')
        WHERE e.workflow=? AND e.status='pending' AND m.status='pending'
        AND m.sender='平台' AND m.recipient=? AND m.mode='queue'
        AND m.project_id=? AND json_extract(e.body,'$.type') IN (?,?,?)
        ORDER BY e.created,e.rowid""", (workflow['id'],recipient,project,*KINDS)).fetchall()
    if not rows:
        message = uid()
        event = {'type':kind,'from':creator,'message_id':message,'body':body,
                 'notice_parts':[{'type':kind,'from':creator,'body':body,'created':now}],
                 'merged_message_ids':[message]}
        hub.db.execute("INSERT INTO messages(id,sender,recipient,body,mode,status,created,project_id) VALUES(?,'平台',?,?,'queue','pending',?,?)", (message,recipient,body,now,project))
        hub.db.execute("INSERT INTO workflow_events VALUES(?,?,NULL,?,'pending',NULL,?)", (kind+':'+message,workflow['id'],json.dumps(event,ensure_ascii=False),now))
        return message
    first = rows[0]
    event = json.loads(first['body'])
    parts = []
    aliases = []
    for row in rows:
        prior = json.loads(row['body'])
        parts.extend(prior.get('notice_parts') or [{'type':prior['type'],'from':prior.get('from','平台'),'body':row['message_body']}])
        aliases.extend(prior.get('merged_message_ids') or [row['message_id']])
    parts.append({'type':kind,'from':creator,'body':body,'created':now})
    # Repeated identical reminders occupy one line, with their occurrence count.
    unique = {}
    for part in parts:
        key = (part['type'],part.get('from'),part['body'])
        if key in unique:
            unique[key]['occurrences'] = unique[key].get('occurrences',1)+part.get('occurrences',1)
            unique[key]['last_at'] = part.get('last_at',part.get('created',now))
        else: unique[key] = dict(part)
    parts = list(unique.values())
    combined = '合并通知（'+str(len(parts))+'项）：\n\n'+'\n\n'.join(p['body']+('（累计'+str(p['occurrences'])+'次）' if p.get('occurrences',1)>1 else '') for p in parts)
    event.update(body=combined,notice_parts=parts,merged_message_ids=list(dict.fromkeys(aliases)))
    hub.db.execute('UPDATE workflow_events SET body=? WHERE id=?',(json.dumps(event,ensure_ascii=False),first['id']))
    hub.db.execute('UPDATE messages SET body=? WHERE id=?',(combined,first['message_id']))
    for row in rows[1:]:
        hub.db.execute("UPDATE workflow_events SET status='coalesced' WHERE id=?",(row['id'],))
        hub.db.execute("UPDATE messages SET status='archived',result=? WHERE id=?",('已合并至 '+first['message_id']+'；等待经理领取，不代表已处理',row['message_id']))
    hub.audit('supervisor','notification.coalesced',{'workflow':workflow['id'],'recipient':recipient,'message':first['message_id'],'items':len(parts)})
    return first['message_id']
