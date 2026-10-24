"""Project-owned file cleanup and read-only Git history for the user panel."""
import hashlib
import json
import shutil
import subprocess
import threading
import time
from pathlib import Path
from .core import HubError


def rows(hub, table, project):
    if not hub.db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
        return []
    if table in ('design_reviews', 'shared_artifacts'):
        return [json.loads(r[0]) for r in hub.db.execute("SELECT body FROM " + table + " WHERE json_extract(body,'$.project_id')=?", (project,))]
    return [dict(r) for r in hub.db.execute('SELECT * FROM ' + table + ' WHERE project=?', (project,))]


def inventory(projects, project_id):
    hub = projects.hub
    project = projects.get(project_id)
    data = Path(hub.directory).resolve()
    root = Path(project['cwd']).absolute()
    managed = data / 'git-worktrees' / hashlib.sha256(project_id.encode()).hexdigest()[:16]
    with hub.lock:
        workspaces = rows(hub, 'git_workspaces', project_id)
        runs = rows(hub, 'git_runs', project_id)
        designs = rows(hub, 'design_reviews', project_id)
        artifacts = rows(hub, 'shared_artifacts', project_id)
        removed = bool(hub.db.execute("SELECT 1 FROM settings WHERE key=? AND value='true'", ('deleted_project:' + project_id,)).fetchone())
        others = [Path(r[0]).resolve() for r in hub.db.execute('SELECT cwd FROM hub_projects WHERE id!=?', (project_id,))]
    paths = [(root, '项目目录')]
    for item in workspaces + runs:
        path = Path(item['cwd']).absolute()
        if path.is_relative_to(managed) and path != managed:
            paths.append((path, '独立 Git 工作区'))
    # Include interrupted worktree creation which did not reach its database insert.
    if managed.is_dir():
        paths.append((managed, '项目全部独立工作区'))
    for table_rows, folder, label in ((designs, 'designs', '演示版本'), (artifacts, 'shared-artifacts', '展示附件')):
        for item in table_rows:
            ident = item['id']
            if ident and all(c in '0123456789abcdef' for c in ident):
                paths.append((data / folder / ident, label))
    protected = {Path(root.anchor), Path.home().resolve(), data}
    result = []
    seen = set()
    for path, label in paths:
        path = path.absolute()
        key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        # Refuse parent/shared-directory deletion, and never follow directory links.
        linked = path.is_symlink() or getattr(path, 'is_junction', lambda: False)()
        resolved = path.resolve()
        unsafe = not linked and (resolved in protected or data.is_relative_to(resolved) or any(other == resolved or other.is_relative_to(resolved) for other in others))
        result.append({'path': str(path), 'kind': label, 'exists': path.exists() or linked, 'protected': unsafe})
    digest = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()
    return {'project_id': project_id, 'name': project['name'], 'removed': removed, 'paths': result, 'inventory_key': digest, 'workspaces': workspaces}


def cleanup(projects, actor, project_id, confirmed=False, inventory_key=None):
    hub=projects.hub
    hub.require(actor,{'user'})
    with hub.planning.workflows.lock:
        try:return _cleanup(projects,actor,project_id,confirmed,inventory_key)
        finally:
            with hub.tx():getattr(hub,'cleaning_projects',set()).discard(project_id)


def _cleanup(projects, actor, project_id, confirmed=False, inventory_key=None):
    hub = projects.hub
    hub.require(actor, {'user'})
    workflows = hub.planning.workflows
    with workflows.lock:
        plan = inventory(projects, project_id)
        from .project_activity import busy
        if busy(hub, project_id):raise HubError('项目正在执行，不能清理文件；请先暂停或结束项目，等待 Agent 停止后再清理')
        if not confirmed:
            return {k: v for k, v in plan.items() if k != 'workspaces'}
        if inventory_key != plan['inventory_key']:
            raise HubError('关联目录已变化，请重新查看清理清单后确认')
        with hub.tx():
            if busy(hub,project_id):raise HubError('项目正在执行，不能清理文件')
            if not hasattr(hub,'cleaning_projects'):hub.cleaning_projects=set()
            hub.cleaning_projects.add(project_id)
        removed, errors = [], []
        for item in plan['paths']:
            if item['protected']:
                errors.append({'path': item['path'], 'error': '与其它项目共享或属于存储根目录，已保留'})
                continue
            path = Path(item['path'])
            try:
                linked = path.is_symlink() or getattr(path, 'is_junction', lambda: False)()
                if linked:
                    if path.is_dir(): path.rmdir()
                    else: path.unlink()
                elif path.is_dir():
                    # Verify the final absolute path again immediately before recursive deletion.
                    if str(path.resolve()).casefold() != str(path.absolute()).casefold():
                        raise OSError('目录含重定向链接，已保留，请检查实际位置')
                    def writable(fn, filename, exc):
                        import os, stat
                        os.chmod(filename, stat.S_IWRITE)
                        fn(filename)
                    shutil.rmtree(path, onerror=writable)
                elif path.exists():
                    path.unlink()
                removed.append(item['path'])
            except OSError as error:
                errors.append({'path': item['path'], 'error': str(error)})
        # If a main repository remains (for example shared), clear stale Git registrations.
        for workspace in plan['workspaces']:
            root = Path(workspace['root'])
            if (root / '.git').exists():
                try: subprocess.run(['git', '-C', str(root), 'worktree', 'prune'], capture_output=True, timeout=10, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                except (OSError, subprocess.TimeoutExpired): pass
        with hub.tx():
            if not errors:
                reset_project(projects, project_id, plan['removed'])
                for table in ('git_workspaces', 'git_runs'):
                    if hub.db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
                        hub.db.execute('DELETE FROM ' + table + ' WHERE project=?', (project_id,))
            hub.audit(actor, 'project.files_cleaned', {'project': project_id, 'removed': removed, 'errors': errors})
        return {'ok': not errors, 'removed': removed, 'errors': errors, 'project_removed': plan['removed'], 'reset': not errors}


def reset_project(projects, project_id, was_removed):
    hub=projects.hub
    now=time.time()
    if hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='executions'").fetchone():
        hub.db.execute("UPDATE executions SET status='cancelled',finished=?,result='项目文件已清理；旧的未启动执行不再重试' WHERE task_id IN (SELECT id FROM tasks WHERE project_id=?) AND status IN ('queued','waiting_quota')",(now,project_id))
    for table in ('workflows','planning_sessions','design_reviews'):
        if not hub.db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(table,)).fetchone():continue
        for row in hub.db.execute("SELECT id,body FROM "+table+" WHERE json_extract(body,'$.project_id')=?",(project_id,)).fetchall():
            item=json.loads(row['body'])
            if table=='workflows':item.update(status='cancelled',phase='cleaned',report='项目文件已清理；旧工作流归档，等待用户重新发起',next_inspection=None)
            elif table=='planning_sessions':
                item.update(state='draft',pending=None,plan=None,workflow_id=None,notice='项目文件已清理；对话和模型上下文保留，旧产物需要重建')
                item.pop('design_id',None)
            else:item.update(state='cleaned')
            hub.db.execute('UPDATE '+table+' SET body=? WHERE id=?',(json.dumps(item,ensure_ascii=False),row['id']))
    for table in ('hub_timers','hub_timer_history'):
        if hub.db.execute("SELECT 1 FROM sqlite_master WHERE name=?",(table,)).fetchone():
            hub.db.execute("DELETE FROM "+table+" WHERE json_extract(body,'$.project_id')=?",(project_id,))
    hub.db.execute("UPDATE messages SET status='archived',result='项目文件已清理；旧消息归档，不再投递' WHERE project_id=? AND status IN ('pending','paused','acknowledged')",(project_id,))
    hub.db.execute("UPDATE tasks SET status='blocked',note='项目文件已清理；旧任务归档' WHERE project_id=? AND status!='done'",(project_id,))
    if hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='workflow_events'").fetchone():
        hub.db.execute("UPDATE workflow_events SET status='archived' WHERE workflow IN (SELECT id FROM workflows WHERE json_extract(body,'$.project_id')=?) AND status IN ('pending','claimed')",(project_id,))
    if not was_removed:
        hub.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('project_files_cleaned:'+project_id,'true'))
    if hasattr(projects,'_git_views'):projects._git_views.pop(project_id,None)


def git_tree(projects, actor, project_id):
    projects.hub.require(actor, {'user'})
    project = projects.get(project_id)
    if not hasattr(projects, '_git_view_lock'):
        projects._git_view_lock = threading.Lock()
        projects._git_views = {}
    with projects._git_view_lock:
        cached = projects._git_views.get(project_id)
        if cached and time.monotonic() - cached[0] < 3:
            return cached[1]
        root = Path(project['cwd'])
        result = {'project_id': project_id, 'root': str(root), 'graph': '', 'workspaces': [], 'updated': time.time()}
        if not (root / '.git').exists():
            result['note'] = '此项目尚未建立 Git 仓库'
        else:
            try:
                run = subprocess.run(['git', '-C', str(root), 'log', '--all', '--graph', '--decorate=short', '--date=short', '--format=%h %d %s · %ad', '-80'], capture_output=True, encoding='utf-8', errors='replace', timeout=4, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                result['graph'] = run.stdout
                if run.returncode: result['note'] = run.stderr.strip()[:500] or '暂无提交'
                with projects.hub.lock:
                    result['workspaces'] = rows(projects.hub, 'git_workspaces', project_id)
            except (OSError, subprocess.TimeoutExpired) as error:
                result['note'] = 'Git 暂时无法读取：' + str(error)[:300]
        projects._git_views[project_id] = (time.monotonic(), result)
        return result
