"""Configuration-only host. Never constructs a runtime or starts a worker."""
import json
import os
import sys
from pathlib import Path
import subprocess
import threading
import time
from types import SimpleNamespace
import webbrowser

from hub.core import Hub, HubError
from hub.integrations import Integrations, BASES, locate, command
from hub.locking import acquire
from hub.vm_bridge import VmBridge


class ConfigurationRegistry(Integrations):
    def __init__(self, server):
        from hub.harness_adapters import prepare_layout, builtin_catalog
        self.server=server;self.hub=server.hub;self.lock=threading.RLock()
        self.instances={};self.running=False;self.adapter_scan_at=0;self.adapter_errors=[]
        prepare_layout(self.hub.directory)
        with self.hub.tx():
            self.hub.db.execute('CREATE TABLE IF NOT EXISTS integration_connections(id TEXT PRIMARY KEY,body TEXT)')
            self.hub.db.execute('CREATE TABLE IF NOT EXISTS agent_profiles(id TEXT PRIMARY KEY,body TEXT)')
            self.hub.db.execute('CREATE TABLE IF NOT EXISTS agent_change_queue(project_id TEXT,agent TEXT,before_json TEXT,after_json TEXT,first_at REAL,updated REAL,version TEXT,PRIMARY KEY(project_id,agent))')
            for kind,spec in builtin_catalog().items():
                preset={'id':kind+'-local','name':spec['name'],'kind':kind,'enabled':False,'cwd':server.deepseek.config()['cwd'],'permission':'workspace' if kind=='codex' or kind.endswith('-api') else 'full','call_limit':0,'executable':'','key_env':BASES.get(kind,('',''))[1],'models':[],'quota':{'source':'unknown','remaining':None,'resets_at':None}}
                self.hub.db.execute('INSERT OR IGNORE INTO integration_connections VALUES(?,?)',(preset['id'],json.dumps(preset,ensure_ascii=False)))
        self.scan_adapters(force=True)

    def close(self):
        pass

    def apply(self):
        pass  # Applying grants must not create execution runtimes during setup.

    def manager_projects(self):
        if not self.hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='workflows'").fetchone():
            return {}
        return super().manager_projects()

    def busy(self, agents):
        if not self.hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='executions'").fetchone():
            return False
        return super().busy(agents)


class SetupService:
    def __init__(self, directory):
        self.directory = Path(directory)
        try:
            self.ownership = acquire(self.directory, 'service.lock')
        except RuntimeError:
            raise HubError('请先从托盘退出 Agent Hub，再打开配置引导。已有任务不会被强制中止。') from None
        try:
            fresh = not (self.directory/'hub.sqlite3').exists()
            self.hub = Hub(self.directory, recover=False)
            workspace = self.directory / 'projects'
            workspace.mkdir(exist_ok=True)
            # Borrow pure configuration readers without running __init__/recovery.
            from hub.deepseek_runtime import DeepSeekRuntime
            deepseek = DeepSeekRuntime.__new__(DeepSeekRuntime)
            deepseek.hub = self.hub
            deepseek._api_injected = False
            workflows = SimpleNamespace(lock=threading.RLock(), snapshot=lambda actor: self.workflows())
            self.server = SimpleNamespace(hub=self.hub, deepseek=deepseek, workflows=workflows)
            self.registry = ConfigurationRegistry(self.server)
            if fresh:
                with self.hub.tx():
                    for a in self.registry.rows('agent_profiles'):
                        a['enabled']=False
                        self.registry.put('agent_profiles',a)
                    self.hub.db.execute('UPDATE agents SET enabled=0')
            self.vm = VmBridge(self.directory)
            self.verified = set()
            self.login_opened = set()
        except BaseException:
            if hasattr(self, 'hub'): self.hub.db.close()
            self.ownership.close()
            raise

    def workflows(self):
        if not self.hub.db.execute("SELECT 1 FROM sqlite_master WHERE name='workflows'").fetchone(): return []
        return [json.loads(row[0]) for row in self.hub.db.execute('SELECT body FROM workflows')]

    def close(self):
        self.registry.close()
        self.hub.db.close()
        self.ownership.close()

    def manifest(self, connection):
        path = Path(connection['adapter']['manifest']) if connection.get('adapter') else self.directory / 'adapters' / 'builtin' / connection['kind'] / 'adapter.json'
        return json.loads(path.read_text(encoding='utf-8-sig'))

    def refresh_environment(self):
        if os.name != 'nt': return
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
            index = 0
            while True:
                try: name, value, kind = winreg.EnumValue(key, index)
                except OSError: break
                index += 1
                if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) and name.upper().endswith(('_KEY', '_TOKEN')):
                    os.environ[name] = os.path.expandvars(value)

    def connections(self):
        self.registry.scan_adapters(force=True)
        entries = []
        for c in self.registry.rows('integration_connections'):
            # Use a normal modular connection instead of the old dedicated DS UI.
            if c.get('legacy'): continue
            spec = self.manifest(c).get('setup', {})
            installed = bool(c.get('adapter_available')) if c.get('adapter') else c['kind'] in BASES or bool(locate(c['kind'], c.get('executable', '')))
            entries.append({**c, 'installed': installed, 'setup': spec})
        if not any(c['kind'] == 'deepseek-harness' for c in entries):
            c = self.registry.save_connection('user', {'id': 'deepseek-harness-local', 'kind': 'deepseek-harness', 'name': 'DeepSeek Harness', 'permission': 'full', 'enabled': False})
            entries.append({**c, 'installed': bool(locate(c['kind'])), 'setup': self.manifest(c).get('setup', {})})
        return entries

    def agents(self):
        connections = {c['id']: c for c in self.registry.rows('integration_connections')}
        return [a for a in self.registry.rows('agent_profiles') if a.get('enabled') and connections.get(a['connection_id'], {}).get('enabled') and not connections.get(a['connection_id'], {}).get('legacy')]

    def open_url(self, url):
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise HubError('适配器需要提供有效的 HTTPS 官网链接')
        webbrowser.open(url)

    def open_login(self, connection_id):
        c = self.registry.get('integration_connections', connection_id)
        spec = self.manifest(c).get('setup', {})
        if not c.get('adapter') or c['adapter']['protocol']=='hub-module-v1':
            from hub.module_loader import load
            folder=c['adapter']['directory'] if c.get('adapter') else self.directory/'adapters'/'builtin'/c['kind']
            module, _ = load(folder)
            hook = getattr(module, 'setup_login', None)
            if callable(hook):
                hook(self.registry, dict(c))
                self.login_opened.add(connection_id)
                return
        if spec.get('login_url'):
            self.open_url(spec['login_url'])
        else:
            exe = locate(c['kind'], c.get('executable', ''))
            if not exe: raise HubError('请先安装 Harness，再重新检测')
            args = spec.get('login_args', [])
            if not isinstance(args, list) or not all(isinstance(x, str) for x in args): raise HubError('登录参数格式错误')
            argv = command([exe, *args])
            if spec.get('terminal'):
                # Visible interactive process; no shell interpolation or elevation.
                subprocess.Popen(argv, cwd=c['cwd'], creationflags=getattr(subprocess, 'CREATE_NEW_CONSOLE', 0))
            else:
                subprocess.Popen(argv, cwd=c['cwd'])
        self.login_opened.add(connection_id)

    def inspect(self, connection_id):
        self.refresh_environment()
        c = next(c for c in self.connections() if c['id'] == connection_id)
        if not c['installed']: return {'state': 'missing', 'message': '本机未安装，请通过官网安装后重新检测。'}
        spec = c['setup']
        # Model catalogues may be public. They are never proof of login.
        if not c.get('adapter') or c['adapter']['protocol'] == 'hub-module-v1':
            from hub.module_loader import load
            folder=c['adapter']['directory'] if c.get('adapter') else self.directory/'adapters'/'builtin'/c['kind']
            module, _ = load(folder)
            hook = getattr(module, 'setup_status', None)
            if callable(hook):
                result = hook(self.registry, dict(c))
                if not isinstance(result, dict) or result.get('state') not in ('ready','login','unknown','missing'): raise HubError('setup_status 返回值无效')
                return result
        return {'state':'unknown','message':'此 Harness 没有独立登录检测接口。请在官方界面确认登录，再继续读取模型目录。'}

    def probe(self, connection_id, login_confirmed=False):
        status = self.inspect(connection_id)
        if status['state'] == 'missing': raise HubError(status['message'])
        if status['state'] == 'login':
            return {'login_required':True, 'message':status['message']}
        if status['state'] == 'unknown' and not login_confirmed:
            return {'login_required':True, 'manual_confirmation':True, 'message':status['message']}
        try:
            value = self.registry.probe('user', connection_id)
        except HubError as error:
            if any(word in str(error).lower() for word in ('401','unauth','未登录','login required','authentication')):
                return {'login_required':True,'message':'官方账号凭据已失效，请使用打开登录界面完成登录。'}
            raise
        self.verified.add(connection_id)
        return value

    def add_agent(self, connection_id, model, name, consent):
        if consent is not True: raise HubError('请先确认执行权限和提供商费用')
        if connection_id not in self.verified: raise HubError('请先检查登录并读取模型目录')
        return self.registry.wizard_add('user', connection_id, model, name, confirmed=True)

    def save_deepseek_key(self, key):
        import base64
        from hub.deepseek_runtime import protect
        if not isinstance(key,str) or not 10<=len(key.strip())<=500 or any(c.isspace() for c in key.strip()):raise HubError('API 密钥格式无效')
        if self.registry.busy([a['id'] for a in self.registry.rows('agent_profiles')]):raise HubError('存在在途任务，请等待任务结束再更换密钥')
        if sys.platform=='darwin':
            from hub.macos_keychain import save
            save(self.directory,key.strip())
        else:
            path=self.directory/'deepseek-key.dpapi';temp=path.with_suffix('.tmp')
            temp.write_bytes(base64.b64encode(protect(key.strip().encode())));temp.replace(path)
        with self.hub.tx():
            self.hub.db.execute("DELETE FROM settings WHERE key='deepseek_validation'")
            self.hub.audit('user','deepseek.key_saved',{'storage':'macOS Keychain' if sys.platform=='darwin' else 'Windows DPAPI','key':'[redacted]'})

    @staticmethod
    def open_environment():
        subprocess.Popen([str(Path(os.environ.get('SystemRoot','C:/Windows'))/'System32'/'rundll32.exe'), 'sysdm.cpl,EditEnvironmentVariables'])

    def complete(self, skip_agents, manager, skip_vm):
        if type(skip_agents) is not bool or type(skip_vm) is not bool: raise HubError('跳过选项无效')
        if not skip_agents:
            if manager not in {a['id'] for a in self.agents()}: raise HubError('请选择一个已启用的 Agent 作为经理')
        if not skip_vm and not self.vm.status().get('connected'): raise HubError('虚拟机尚未连接，可以返回连接或选择跳过')
        if not skip_agents:
            with self.hub.tx():
                self.hub.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', ('project_manager:default', manager))
        marker = {'version':1,'completed_at':time.time(),'agent_skipped':skip_agents,'manager':None if skip_agents else manager,'vm_skipped':skip_vm}
        path=self.directory/'onboarding.completed.json'
        temp=path.with_suffix('.tmp');temp.write_text(json.dumps(marker,ensure_ascii=False),encoding='utf-8');temp.replace(path)
        return marker

    @staticmethod
    def hyperv():
        root=Path(os.environ.get('SystemRoot', 'C:/Windows'))/'System32'
        return {'installed':(root/'virtmgmt.msc').is_file(), 'manager':str(root/'virtmgmt.msc')}

    def open_hyperv(self):
        state=self.hyperv()
        if state['installed']: os.startfile(state['manager'])
        else: subprocess.Popen([str(Path(os.environ.get('SystemRoot','C:/Windows'))/'System32'/'OptionalFeatures.exe')])

