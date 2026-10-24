"""Durable resource ordering, independent of model/provider identity."""
import json,re
from pathlib import Path
from .core import HubError

TERMINAL={'completed','failed','cancelled','interrupted','uncertain'}

def paths(instruction,explicit=None):
    if explicit is not None:
        if not isinstance(explicit,list) or any(not isinstance(p,str) or not p.strip() for p in explicit):raise HubError('文件范围须为路径列表')
        result=explicit
    else:
        result=[]
        for line in instruction.splitlines():
            if re.search(r'不得|禁止|不要|不改|勿改|必读|先读|参考|基准|只读|项目根目录',line):continue
            result+=re.findall(r'[\w./\\-]+\.(?:xaml\.cs|csproj|vbproj|fsproj|vcxproj|slnx?|appxmanifest|manifest|xaml|html?|tsx?|jsx?|css|json|md|txt|py|rs|toml|cs|fs|vb|xml|resx|props|targets|ps1|ya?ml)\b',line,re.I)
    return sorted(set(p.replace('\\','/').removeprefix('./').casefold() for p in result)) or ['*']

def overlaps(left,right):
    return any(a=='*' or b=='*' or a==b or a.startswith(b.rstrip('/')+'/') or b.startswith(a.rstrip('/')+'/') for a in left for b in right)

def register(workflows,w,task,agent,kind,instruction,write_paths=None):
    if kind not in ('work','check'):return []
    hub=workflows.hub;scope=paths(instruction,write_paths)
    if getattr(workflows,'git',None) and workflows.git.applies(w):
        hub.db.execute('DELETE FROM workflow_resource_dependencies WHERE task=?',(task,))
        hub.db.execute('INSERT OR REPLACE INTO workflow_resources VALUES(?,?,?)',(task,kind,json.dumps(scope)))
        return []
    root=Path(w.get('design_dir') or w.get('cwd') or hub.directory).resolve()
    canonical=[]
    for value in scope:
        if value=='*':canonical.append('*');continue
        resolved=(root/value).resolve()
        if not resolved.is_relative_to(root):
            if write_paths is not None:raise HubError('文件范围必须在当前项目目录内')
            canonical=['*'];break
        canonical.append(resolved.relative_to(root).as_posix().casefold())
    scope=sorted(set(canonical))
    dependencies=[]
    # Existing prepared/running tasks from earlier releases are also considered.
    steps=workflows.steps(w['id']);current=next(s for s in steps if s['task']==task);sequence=current['seq']
    # A manager's follow-up supplements its existing assignment. Retain that
    # assignment's declared files instead of locking the entire repository.
    if current['kind']=='message' and kind=='work' and write_paths is None:
        previous=next((s for s in reversed(steps) if s['seq']<sequence and s['agent']==agent and s['kind'] in ('work','message')),None)
        prior=hub.db.execute('SELECT paths FROM workflow_resources WHERE task=?',(previous['task'],)).fetchone() if previous else None
        inherited=json.loads(prior[0]) if prior else ['*']
        if inherited!=['*']:scope=sorted(set(inherited+(scope if scope!=['*'] else [])))
    for step in steps:
        if step['seq']>=sequence:continue
        if step['task']==task or step['status'] in TERMINAL:continue
        row=hub.db.execute('SELECT paths,kind FROM workflow_resources WHERE task=?',(step['task'],)).fetchone()
        other_kind=row['kind'] if row else step['kind']
        if other_kind not in ('work','check'):continue
        if kind=='check' and other_kind=='check':continue
        other=json.loads(row[0]) if row else paths(step.get('prompt') or hub.db.execute('SELECT title FROM tasks WHERE id=?',(step['task'],)).fetchone()[0])
        if overlaps(scope,other):dependencies.append(step['task'])
    hub.db.execute('INSERT OR REPLACE INTO workflow_resources VALUES(?,?,?)',(task,kind,json.dumps(scope)))
    for prior in dependencies:hub.db.execute('INSERT OR IGNORE INTO workflow_resource_dependencies VALUES(?,?)',(task,prior))
    return dependencies
