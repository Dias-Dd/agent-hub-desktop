"""Milestone messages, delivered in the manager's normal turn, never a review fork."""
import json
import time
from contextlib import nullcontext
from .core import uid
from .manager_identity import resolve


def notify(hub, workflow, phase, milestone=None, run_id=None):
    label = '项目计划已确认' if phase == 'plan' else '已提交项目完成检查，正在核对验收情况'
    body = ('[长期记忆通知] ' + label + '。请检查本次交流是否产生值得跨项目保留的长期记忆：'
            '只保存用户明确表达的长期偏好、持续有效的工作约定，以及经过验证且适用于其他项目的通用经验。'
            '仅与本项目有关的需求、技术选型、计划、进度、产物路径、临时问题和完成记录不要保存，'
            '也不要把一次性要求泛化成全局偏好。先用 memory(operation="read") 检查已有内容与 revision；'
            '确有新内容或纠正再用 memory 写入，避免重复，遵守用户锁定。没有值得保存的内容就不写。'
            '这只是长期记忆提醒，不要求重开项目、派工或执行项目任务；只有写入成功才可声称已保存。')
    key = 'memory-review:' + (milestone or phase + ':' + workflow['id'])
    manager = resolve(hub, record=workflow)
    with hub.lock, (nullcontext() if hub.db.in_transaction else hub.tx()):
        hub.db.execute('CREATE TABLE IF NOT EXISTS memory_review_notices(message_id TEXT PRIMARY KEY,workflow TEXT,phase TEXT,delivery_run TEXT)')
        old = hub.db.execute("SELECT id FROM messages WHERE sender='平台' AND recipient=? AND request_key=?", (manager, key)).fetchone()
        message_id = old[0] if old else uid()
        if not old:
            hub.db.execute("INSERT INTO messages(id,sender,recipient,body,mode,status,created,request_key) VALUES(?,'平台',?,?,'queue','queued',?,?)", (message_id, manager, body, time.time(), key))
        inserted = hub.db.execute('INSERT OR IGNORE INTO memory_review_notices VALUES(?,?,?,?)',
                                  (message_id, workflow['id'], phase, run_id)).rowcount
        if inserted:
            hub.db.execute("UPDATE messages SET project_id=?,status=?,result=? WHERE id=?",
                           (workflow.get('project_id') or workflow['id'], 'completed' if run_id else 'queued',
                            '通知随工具结果送入经理当前轮次，不代表已保存记忆' if run_id else None, message_id))
            hub.audit('平台', 'memory.review_notified', {'message_id': message_id, 'workflow': workflow['id'], 'phase': phase, 'run_id': run_id})
    return {'id': message_id, 'sender': '平台', 'topic': 'long_term_memory', 'body': body}


def suffix(run):
    notices = run.get('_memory_notifications', [])
    return ('\n\n平台通知：\n' + '\n\n'.join(n['body'] for n in notices)) if notices else ''


def attach(hub, run):
    if run.get('_memory_notifications'):
        return run
    with hub.tx():
        if not hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='memory_review_notices'").fetchone():
            return run
        workflow = hub.db.execute('SELECT w.body FROM workflows w JOIN workflow_steps s ON s.workflow=w.id WHERE s.task=?', (run.get('task_id'),)).fetchone()
        if not workflow:
            return run
        w = json.loads(workflow[0])
        if resolve(hub, record=w) != run.get('agent') or w.get('status') != 'active':
            return run
        rows = hub.db.execute("SELECT m.id,m.body FROM messages m JOIN memory_review_notices n ON n.message_id=m.id WHERE n.workflow=? AND m.recipient=? AND m.status='queued' AND n.delivery_run IS NULL ORDER BY m.created", (w['id'], run['agent'])).fetchall()
        if not rows:
            return run
        run = dict(run)
        run['_memory_notifications'] = [dict(row) for row in rows]
        run['_memory_prompt_original'] = run['prompt']
        run['prompt'] += suffix(run)
        for row in rows:
            hub.db.execute('UPDATE memory_review_notices SET delivery_run=? WHERE message_id=?', (run['id'], row['id']))
            hub.db.execute("UPDATE messages SET status='completed',result='通知已加入经理本轮输入，不代表已保存记忆' WHERE id=?", (row['id'],))
    return run
