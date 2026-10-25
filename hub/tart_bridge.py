"""Tart backend behind the existing VM tool, without host elevation or passwords.

Guest commands use Tart Guest Agent. Desktop automation is deliberately unavailable
until a real guest desktop RPC has been implemented and tested.
"""
import base64
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shlex
import shutil
import subprocess
import threading
import time
import uuid

from .core import HubError


class TartBridge:
    _lock = threading.RLock()
    _processes = {}
    _connecting = {}
    _verified = {}
    IMAGES = {'ubuntu': 'ghcr.io/cirruslabs/ubuntu:latest',
              'macos': 'ghcr.io/cirruslabs/macos-sequoia-base:latest'}

    def __init__(self, directory):
        self.root = Path(directory) / 'vm-bridge' / 'tart'
        self.root.mkdir(parents=True, exist_ok=True)
        self.requests = self.root / 'requests'
        self.results = self.root / 'results'
        self.requests.mkdir(exist_ok=True)
        self.results.mkdir(exist_ok=True)

    def executable(self):
        return shutil.which('tart') or next((str(p) for p in
            (Path('/opt/homebrew/bin/tart'), Path('/usr/local/bin/tart')) if p.is_file()), None)

    def environment(self):
        # Each Hub data directory owns its VM inventory/cache; no user VM is adopted.
        return {**os.environ, 'TART_HOME': str((self.root / 'machines').resolve()),
                'TART_NO_AUTO_PRUNE': '1'}

    @staticmethod
    def brew():
        return next((str(p) for p in (Path('/opt/homebrew/bin/brew'),Path('/usr/local/bin/brew')) if p.is_file()),None)

    def preferences(self):
        try:return json.loads((self.root/'preferences.json').read_text())
        except (OSError,ValueError):return {'auto_connect':True}

    def inventory(self):
        rows=json.loads(self.run('list','--source','local','--format','json'))
        return [{'name':r.get('Name',r.get('name')),'state':r.get('State',r.get('state'))} for r in rows]

    def run(self, *args, timeout=30, input=None):
        exe = self.executable()
        if not exe:
            raise HubError('未安装 Tart；请在终端运行 brew install openai/tools/tart，然后刷新。')
        try:
            result = subprocess.run([exe, *args], input=input, capture_output=True,
                                    env=self.environment(), timeout=timeout)
        except subprocess.TimeoutExpired:
            raise HubError('Tart 操作超时；访客命令可能仍在运行，请检查，未自动重试。') from None
        except OSError as error:
            raise HubError('Tart 无法启动：' + str(error)) from None
        if result.returncode:
            raise HubError('Tart: ' + result.stderr.decode('utf-8', errors='replace')[-2000:])
        return result.stdout

    def selected(self):
        try:
            return json.loads((self.root / 'connection.json').read_text())
        except (OSError, ValueError):
            return {}

    def guest_write(self, name, path, raw, timeout):
        code = ('import base64,pathlib,sys; p=pathlib.Path(sys.argv[1]); '
                'p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(base64.b64decode(sys.stdin.buffer.read(),validate=True))')
        self.run('exec', '-i', name, 'python3', '-c', code, path,
                 timeout=timeout, input=base64.b64encode(raw))

    def guest_read(self, name, path, timeout):
        code = ('import base64,pathlib,sys; p=pathlib.Path(sys.argv[1]); '
                'assert p.is_file() and p.stat().st_size<=8388608; '
                'sys.stdout.buffer.write(base64.b64encode(p.read_bytes()))')
        raw = base64.b64decode(self.run('exec', name, 'python3', '-c', code, path, timeout=timeout), validate=True)
        if len(raw) > 8 * 1024 * 1024:raise HubError('访客文件超过 8 MiB')
        return raw

    def saved_connections(self):
        state = self.selected()
        return [{'vm': state['vm'], 'account': 'Tart Guest Agent', 'unattended': False}] if state.get('remember') else []

    def status(self):
        state = self.selected()
        supported = platform.system() == 'Darwin' and platform.machine() == 'arm64' and int(platform.mac_ver()[0].split('.')[0]) >= 13
        available = bool(self.executable()) and supported
        connected = False
        error = ''
        power = 'Unknown'
        if available and state.get('vm'):
            try:
                rows = json.loads(self.run('list', '--source', 'local', '--format', 'json'))
                row = next((r for r in rows if r.get('Name') == state['vm'] or r.get('name') == state['vm']), {})
                power = str(row.get('State', row.get('state', 'Unknown'))).capitalize()
                if power == 'Stopped': power = 'Off'
                connected = power == 'Running' and self._verified.get(str(self.root.resolve()))==state['vm']
            except (HubError, ValueError) as exc:
                error = str(exc)
        return {'backend': 'tart', 'installed': bool(self.executable()), 'supported': supported,
                'helper_alive': available, 'connected': connected, 'vm': state.get('vm'),
                'power_state': power, 'connection_phase': 'ready' if connected else 'disconnected',
                'connection_error': error or ('' if available else 'Tart 需要 Apple Silicon、macOS 13+ 和已安装的 Tart。'),
                'saved_connections': self.saved_connections(), 'tart_home': self.environment()['TART_HOME'],
                'auto_connect':self.preferences().get('auto_connect',True),
                'homebrew_installed':bool(self.brew()),'transfer_verified':state.get('transfer_verified',False) if connected else False,
                'install_command': 'brew install openai/tools/tart',
                'capabilities': {'exec': 'guest-agent-required', 'push': 'guest-agent-required',
                                 'pull': 'guest-agent-required', 'screenshot': False, 'desktop': False},
                'operations': ['list', 'connect', 'disconnect', 'power_on', 'power_off', 'power_force'],
                'desktop': {'ready': False, 'warning': 'Tart 桌面截图、键鼠和控件自动化尚未实现；请使用 Tart 原生窗口。'}}

    @staticmethod
    def name(value):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', value):
            raise HubError('Tart 虚拟机名称只能使用字母、数字、点、短横线和下划线')
        return value

    def write(self, path, value):
        temp = path.with_suffix('.tmp-' + uuid.uuid4().hex)
        temp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        temp.replace(path)

    def queue(self, job, work):
        ident = uuid.uuid4().hex
        job = {**job, 'id': ident, 'created': time.time(), 'owner_pid':os.getpid()}
        self.write(self.requests / (ident + '.json'), job)
        self.write(self.results / (ident + '.json'), {'state': 'queued', 'request_id': ident})
        def execute():
            self.write(self.results / (ident + '.json'), {'state': 'running', 'request_id': ident})
            try:
                result = {'state': 'completed', **work()}
            except Exception as error:
                result = {'state': 'failed', 'error': str(error)}
            self.write(self.results / (ident + '.json'), {**result, 'request_id': ident})
        threading.Thread(target=execute, daemon=True).start()
        return {'state': 'queued', 'request_id': ident}

    def record(self, request_id):
        if not isinstance(request_id, str) or not re.fullmatch('[a-f0-9]{32}', request_id):
            raise HubError('请求编号无效')
        try:
            job=json.loads((self.requests / (request_id + '.json')).read_text())
            result=json.loads((self.results / (request_id + '.json')).read_text())
            if result.get('state') in ('queued','running') and job.get('owner_pid'):
                try:os.kill(job['owner_pid'],0)
                except ProcessLookupError:
                    result={**result,'state':'failed','error':'上次应用已退出；操作结果未知，请检查虚拟机现场，未自动重试。'}
            return job,result
        except (OSError, ValueError):
            raise HubError('Tart 请求不存在或结果不可读') from None

    def control(self, action='status', request_id=None, vm_name='', username='', password='', remember=True, unattended=None,
                auto_connect=None, image='ubuntu', confirmed=False):
        if action == 'status': return self.status()
        if action=='save_preferences':
            if type(auto_connect) is not bool:raise HubError('自动连接选项无效')
            self.write(self.root/'preferences.json',{'auto_connect':auto_connect})
            return {'state':'completed','auto_connect':auto_connect}
        if action=='auto_connect':
            if not self.preferences().get('auto_connect',True) or not self.selected().get('remember'):
                return {'state':'completed','skipped':True}
            return self.connect(self.selected()['vm'],True)
        if action=='install':
            if confirmed is not True:raise HubError('请确认安装 Tart')
            if self.executable():return {'state':'completed','installed':True}
            brew=self.brew()
            if not brew:raise HubError('未安装 Homebrew，请先按官方指南安装 Homebrew，再返回重试。应用不会自动执行 sudo。')
            def install():
                env={**os.environ,'HOMEBREW_NO_AUTO_UPDATE':'1','HOMEBREW_NO_INSTALL_CLEANUP':'1'}
                result=subprocess.run([brew,'install','openai/tools/tart'],capture_output=True,env=env,timeout=1800)
                if result.returncode or not self.executable():
                    raise HubError('Tart 安装未完成：'+result.stderr.decode('utf8',errors='replace')[-2000:])
                return {'installed':True}
            return self.queue({'control':True,'action':action},install)
        if action=='create':
            if confirmed is not True:raise HubError('请确认下载虚拟机镜像（数 GB）')
            name=self.name(vm_name)
            if image not in self.IMAGES:raise HubError('请选择受支持的镜像模板')
            def create():
                if any(r['name']==name for r in self.inventory()):raise HubError('同名虚拟机已存在，未覆盖')
                self.run('clone',self.IMAGES[image],name,timeout=3600)
                if not any(r['name']==name for r in self.inventory()):raise HubError('创建后未发现虚拟机')
                return {'vm':name,'created':True}
            return self.queue({'control':True,'action':action,'vm':name},create)
        if action == 'result':
            job, result = self.record(request_id)
            if not job.get('control'): raise HubError('这不是用户控制请求')
            return result
        if action == 'open_manager':
            import webbrowser
            if not webbrowser.open('https://tart.run/quick-start/'):
                raise HubError('无法打开 Tart 安装文档')
            return {'state': 'completed', 'opened': True}
        if action=='open_homebrew':
            import webbrowser
            if not webbrowser.open('https://brew.sh/'):raise HubError('无法打开 Homebrew 官方安装指南')
            return {'state':'completed','opened':True}
        if action == 'thumbnail':
            return self.queue({'control': True}, lambda: {'available': False, 'note': 'Tart 屏幕预览尚未实现'})
        if action == 'forget':
            state=self.selected()
            if state:self.write(self.root/'connection.json',{**state,'remember':False})
            return {'state':'completed'}
        if action == 'disconnect':
            self._verified.pop(str(self.root.resolve()),None)
            self.write(self.root/'preferences.json',{'auto_connect':False})
            return {'state':'completed','disconnected':True}
        if action == 'list':
            def inventory():
                return {'backend': 'tart', 'vms': self.inventory()}
            return self.queue({'control': True}, inventory)
        if action not in ('connect', 'connect_saved', 'power_on', 'power_off', 'power_force'):
            raise HubError('Tart 不支持此控制操作')
        name = self.name(vm_name)
        if password or username:
            raise HubError('Tart 使用 Guest Agent，不接收 Windows 用户名或密码，请清空这两栏')
        if action in ('connect','connect_saved'):
            if auto_connect is not None:
                if type(auto_connect) is not bool:raise HubError('自动连接选项无效')
                self.write(self.root/'preferences.json',{'auto_connect':auto_connect})
            return self.connect(name,remember)
        def operation():
            if action == 'power_on':
                with self._lock:
                    key = (str(self.root.resolve()), name)
                    child = self._processes.get(key)
                    if child and child.poll() is None: raise HubError('此虚拟机已在启动或运行，请查询状态')
                    log = open(self.root / (name + '.log'), 'ab')
                    try:
                        child = subprocess.Popen([self.executable(), 'run', name], env=self.environment(),
                            stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
                    finally: log.close()
                    self._processes[key] = child
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    if child.poll() is not None: raise HubError('Tart 启动进程已退出，请查看 ' + str(self.root / (name + '.log')))
                    rows = json.loads(self.run('list', '--source', 'local', '--format', 'json'))
                    if any(r.get('Name', r.get('name')) == name and str(r.get('State', r.get('state'))).lower() == 'running' for r in rows):
                        return {'vm': name, 'power_state': 'Running', 'guest_verified': False}
                    time.sleep(.5)
                raise HubError('Tart 未在期限内进入 Running；请检查实际 VM 状态，不要重复启动')
            if action.startswith('power_'):
                self.run('stop', name, '--timeout', '0' if action == 'power_force' else '30', timeout=40)
                return {'vm': name, 'power_state': 'Off'}
        return self.queue({'control': True, 'action': action, 'vm': name}, operation)

    def connect(self,name,remember):
        """One connection attempt per data directory, including power-on and probes."""
        name=self.name(name);key=str(self.root.resolve())
        with self._lock:
            pending=self._connecting.get(key)
            if pending:
                _,result=self.record(pending)
                if result.get('state') in ('queued','running'):return {'state':result['state'],'request_id':pending}
            def work():
                self._verified.pop(key,None)
                self.write(self.root/'connection.json',{'vm':name,'remember':bool(remember),'verified':False})
                row=next((r for r in self.inventory() if r['name']==name),None)
                if not row:raise HubError('此应用数据目录内没有所选虚拟机，请先创建或刷新列表')
                if str(row['state']).lower()!='running':
                    request=self.control('power_on',vm_name=name)
                    while True:
                        _,result=self.record(request['request_id'])
                        if result['state']=='completed':break
                        if result['state']=='failed':raise HubError(result['error'])
                        time.sleep(.3)
                marker=uuid.uuid4().hex;deadline=time.monotonic()+120;last=''
                while time.monotonic()<deadline:
                    try:
                        if self.run('exec',name,'/bin/sh','-c','printf %s '+marker,timeout=8).decode().strip()!=marker:
                            raise HubError('Guest Agent 返回的验证标记不匹配')
                        break
                    except HubError as error:last=str(error);time.sleep(1)
                else:raise HubError('Guest Agent 尚未就绪；请在访客中安装 Tart Guest Agent。'+last)
                transfer=False;warning='';probe='/tmp/agent-hub-probe-'+marker
                try:
                    raw=b'Agent Hub Tart verification\x00\xff'+marker.encode()
                    self.guest_write(name,probe,raw,30)
                    if self.guest_read(name,probe,30)!=raw:raise HubError('文件往返内容校验失败')
                    transfer=True
                except Exception as error:warning='文件传输不可用：'+str(error)
                finally:
                    try:self.run('exec',name,'/bin/rm','-f',probe,timeout=10)
                    except HubError:pass
                self.write(self.root/'connection.json',{'vm':name,'verified':True,'remember':bool(remember),
                           'transfer_verified':transfer,'verified_at':time.time()})
                self._verified[key]=name
                return {'vm':name,'account':'Tart Guest Agent','command_verified':True,'transfer_verified':transfer,
                        'credential_saved':False,'desktop_warning':warning or '桌面截图和自动化未实现'}
            request=self.queue({'control':True,'action':'connect','vm':name},work)
            self._connecting[key]=request['request_id']
            return request

    def call(self, project, agent, cwd, action='status', request_id=None, script='', path='', timeout_seconds=300,
             shell=None, **unused):
        if not all(isinstance(v, str) and re.fullmatch(r'[\w-]{1,100}', v) for v in (project, agent)):
            raise HubError('项目或成员标识无效')
        if request_id:
            job, result = self.record(request_id)
            if job.get('control') or job.get('project') != project or job.get('agent') != agent:
                raise HubError('只能查询自己在本项目的虚拟机操作')
            return result
        if action == 'status': return self.status()
        if action not in ('exec', 'push', 'pull'):
            raise HubError('Tart 尚不支持截图、桌面窗口、控件及键鼠操作')
        state = self.status()
        if not state.get('connected'): raise HubError('Tart Guest Agent 尚未连接，请在设置中验证命令连接')
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 3600:
            raise HubError('超时秒数应在 1–3600 之间')
        name = self.name(state['vm'])
        guest = '/tmp/agent-hub/' + project + '/' + agent
        if action == 'exec':
            if shell != 'posix': raise HubError('Tart 的 exec 必须显式指定 shell="posix"；不会将 PowerShell script 当作 Shell 执行')
            if not isinstance(script, str) or not script.strip(): raise HubError('请输入 POSIX Shell 脚本')
            def work():
                code = 'mkdir -p ' + shlex.quote(guest) + ' && cd ' + shlex.quote(guest) + ' && ' + script
                output = self.run('exec', name, '/bin/sh', '-c', code, timeout=timeout_seconds)
                return {'output': output.decode('utf-8', errors='replace'), 'guest_cwd': guest, 'shell': 'posix'}
        else:
            rel = PurePosixPath(path)
            if not path or rel.is_absolute() or '..' in rel.parts or '\\' in path or ':' in path:
                raise HubError('文件路径必须是工作目录内的 POSIX 相对路径')
            root = Path(cwd).resolve()
            local = (root / path).resolve()
            if not local.is_relative_to(root): raise HubError('文件不在当前工作目录内')
            remote = guest + '/' + str(rel)
            if action == 'push':
                if not local.is_file() or local.stat().st_size > 8 * 1024 * 1024:
                    raise HubError('Tart 目前仅支持传输不超过 8 MiB 的普通文件')
                raw = local.read_bytes()
                def work():
                    self.guest_write(name,remote,raw,timeout_seconds)
                    return {'path': path, 'bytes': len(raw), 'guest_path': remote}
            else:
                def work():
                    raw = self.guest_read(name,remote,timeout_seconds)
                    local.parent.mkdir(parents=True, exist_ok=True)
                    # Recheck after mkdir, before writing through any local symlink.
                    if not local.resolve().is_relative_to(root): raise HubError('文件不在当前工作目录内')
                    local.write_bytes(raw)
                    return {'path': path, 'bytes': len(raw)}
        return self.queue({'project': project, 'agent': agent, 'action': action, 'vm': name}, work)
