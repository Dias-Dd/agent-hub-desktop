"""Onboarding configuration. Credentials stay in the process environment."""
import os
import shutil
import sys
from .antigravity import executable
from .codex_runtime import codex_executable
import time
import json
from .core import HubError, number, text

class Setup:
    def __init__(self,hub,simulate):self.hub=hub;self.simulate=simulate

    def status(self,actor):
        self.hub.require(actor,{'user'})
        with self.hub.lock:
            row=self.hub.db.execute("SELECT value FROM settings WHERE key='onboarding'").fetchone()
            saved=json.loads(row[0]) if row else None
            budget=int(self.hub.db.execute("SELECT value FROM settings WHERE key='budget_cents'").fetchone()[0])
        return {'saved':saved,'budget_cents':budget,'python':sys.version.split()[0],'simulation':self.simulate,
                'openai_installed':bool(codex_executable()),'antigravity_installed':bool(executable()),
                'deepseek_key_present':bool(os.environ.get('DEEPSEEK_API_KEY')),'real_calls_enabled':os.environ.get('HUB_ALLOW_REAL')=='1'}

    def save(self,actor,project_name,route,budget_cents,confirmed=False):
        self.hub.require(actor,{'user'});text(project_name,100)
        if route not in ('simulation','deepseek','codex','antigravity'):raise HubError('invalid setup route')
        if not isinstance(budget_cents,int) or isinstance(budget_cents,bool):raise HubError('integer cents required')
        number(budget_cents,0,100000)
        if confirmed is not True:raise HubError('请确认配置摘要')
        config={'project_name':project_name.strip(),'route':route,'completed_at':time.time()}
        with self.hub.tx():
            used=self.hub.db.execute("SELECT COALESCE(SUM(reserve_cents),0) FROM calls WHERE status IN ('approved','running','completed','uncertain')").fetchone()[0]
            if budget_cents<used:raise HubError('预算不能低于已有调用的保留费用')
            self.hub.db.execute("UPDATE settings SET value=? WHERE key='budget_cents'",(str(budget_cents),))
            self.hub.db.execute("INSERT OR REPLACE INTO settings VALUES('onboarding',?)",(json.dumps(config,ensure_ascii=False),))
            self.hub.audit(actor,'setup.completed',{'route':route,'budget_cents':budget_cents})
        return config
