"""Project manager resolution; seed identities never define runtime authority."""
import json


def resolve(hub, project_id=None, record=None):
    record=record or {};project_id=project_id or record.get('project_id')
    with hub.lock:
        if record.get('manager'):return record['manager']
        tables={r[0] for r in hub.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        enabled={r[0] for r in hub.db.execute('SELECT id FROM agents WHERE enabled=1')}
        if 'agent_profiles' in tables:
            enabled&={r[0] for r in hub.db.execute("SELECT id FROM agent_profiles WHERE json_extract(body,'$.enabled')=1")}
        if project_id:
            row=hub.db.execute('SELECT value FROM settings WHERE key=?',('project_manager:'+project_id,)).fetchone()
            if row and row[0] in enabled:return row[0]
        if project_id:
            for table in ('workflows','planning_sessions'):
                if table not in tables:continue
                row=hub.db.execute('SELECT json_extract(body,\'$.manager\') FROM '+table+" WHERE json_extract(body,'$.project_id')=? AND json_extract(body,'$.manager') IS NOT NULL ORDER BY rowid DESC LIMIT 1",(project_id,)).fetchone()
                if row and row[0] in enabled:return row[0]
        # A new project inherits the last user-selected manager, never a deleted seed ID.
        for row in hub.db.execute("SELECT value FROM settings WHERE key LIKE 'project_manager:%' ORDER BY rowid DESC"):
            if row[0] in enabled:return row[0]
        row=hub.db.execute("SELECT id FROM agents WHERE enabled=1 AND role='项目经理' ORDER BY rowid LIMIT 1").fetchone()
        if row and row[0] in enabled:return row[0]
        return next((r[0] for r in hub.db.execute('SELECT id FROM agents WHERE enabled=1 ORDER BY rowid') if r[0] in enabled),None)


def managers(hub):
    with hub.lock:
        result={r[0] for r in hub.db.execute("SELECT value FROM settings WHERE key LIKE 'project_manager:%'")}
        tables={r[0] for r in hub.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ('workflows','planning_sessions'):
            if table in tables:
                for row in hub.db.execute('SELECT body FROM '+table):
                    record=json.loads(row[0]);manager=resolve(hub,record=record)
                    if manager:result.add(manager)
        if not result:
            manager=resolve(hub)
            if manager:result.add(manager)
        enabled={r[0] for r in hub.db.execute('SELECT id FROM agents WHERE enabled=1')}
        return result&enabled


def independent_reviewer(manager,agents,selected=None):
    """A suggested independent reviewer is a participant, never the manager."""
    choices=[a for a in agents if a!=manager]
    return selected if selected in choices else next(iter(choices),None)
