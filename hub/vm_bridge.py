"""PowerShell Direct bridge with Windows-protected guest credentials and desktop RPC."""
import json
import re
import time
import uuid
import sys
import os
import base64
import hashlib
import threading
import copy
from pathlib import Path, PureWindowsPath
from .core import HubError


class VmBridge:
    def __new__(cls, directory):
        if cls is VmBridge and sys.platform == 'darwin':
            from .tart_bridge import TartBridge
            return TartBridge(directory)
        return super().__new__(cls)

    _launch_lock=threading.RLock()
    _starting={}
    _status_cache={}

    @staticmethod
    def _process_alive(pid):
        if sys.platform!='win32' or not isinstance(pid,int) or pid<=0:return None
        import ctypes as C
        from ctypes import wintypes as W
        kernel=C.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];kernel.OpenProcess.restype=W.HANDLE
        kernel.GetExitCodeProcess.argtypes=[W.HANDLE,C.POINTER(W.DWORD)]
        kernel.CloseHandle.argtypes=[W.HANDLE]
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:return False if C.get_last_error()==87 else None
        try:
            code=W.DWORD()
            return code.value==259 if kernel.GetExitCodeProcess(handle,C.byref(code)) else None
        finally:kernel.CloseHandle(handle)

    def __init__(self, directory):
        self.root = Path(directory) / 'vm-bridge'
        self.requests = self.root / 'requests'
        self.results = self.root / 'results'
        for folder in (self.requests, self.results):
            folder.mkdir(parents=True, exist_ok=True)

    def status(self):
        key=str(self.root.resolve())
        try:
            state=json.loads((self.root/'status.json').read_text(encoding='utf-8-sig'))
            if not isinstance(state,dict):raise ValueError('invalid status')
            self._status_cache[key]=copy.deepcopy(state)
        except (OSError,ValueError):state=copy.deepcopy(self._status_cache.get(key,{}))
        fresh=time.time()-state.get('updated',0)<20
        process=self._process_alive(state.get('helper_pid'))
        alive=process is True or (fresh and process is not False)
        starting=time.monotonic()-self._starting.get(key,-1e9)<90
        state['helper_alive']=alive;state['heartbeat_stale']=alive and not fresh
        state['connected']=bool(alive and fresh and state.get('connected',True))
        if not state['connected']:
            state['command_elevated']=None
            if isinstance(state.get('desktop'),dict):state['desktop']['ready']=False
            if alive:
                if not fresh:state['connection_phase']='helper_busy';state['connection_error']='连接服务仍在运行，正在等待连接状态更新。'
                elif state.get('connection_phase')=='ready':state['connection_phase']='reconnecting' if state.get('auto_reconnect') else 'disconnected'
            elif starting:state['connection_phase']='booting';state['connection_error']='管理员连接服务正在启动，请稍候。'
            else:state['connection_phase']='helper_offline'
        state['saved_connections']=self.saved_connections()
        return state

    def saved_connections(self):
        folder=self.root/'saved-connections'
        rows=[]
        for path in folder.glob('*.json'):
            try:
                data=json.loads(path.read_text(encoding='utf-8-sig'))
                rows.append({'vm':data['vm'],'account':data.get('account',''),'unattended':data.get('unattended',True)})
            except (OSError,ValueError,KeyError):pass
        return rows

    def saved_path(self, name):
        return self.root/'saved-connections'/(hashlib.sha256(name.encode('utf-8')).hexdigest()+'.json')

    def launch_helper(self):
        with self._launch_lock:
            key=str(self.root.resolve())
            state=self.status()
            if state.get('helper_alive'):
                if state.get('protocol')!=4:raise HubError('旧版桥接仍在运行，请退出旧版 Hub 后打开新版')
                return
            if time.monotonic()-self._starting.get(key,-1e9)<90:return
            self._starting[key]=time.monotonic()
            try:self._launch_helper_process()
            except Exception:
                self._starting.pop(key,None)
                raise

    def _launch_helper_process(self):
        if self.status().get('helper_alive'):
            if self.status().get('protocol') != 4:
                raise HubError('旧版桥接窗口仍在运行，请先在该窗口按 Ctrl+C，再从此处连接')
            return
        import ctypes
        import subprocess
        script = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1])) / 'tools/Start-HubVmBridge.ps1'
        if not script.is_file():
            raise HubError('未找到虚拟机连接组件，请重新安装完整版本')
        args = subprocess.list2cmdline(['-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden',
                                      '-File', str(script), '-ServiceMode', '-OwnerPid', str(os.getpid()), '-DataDirectory', str(self.root.parent)])
        shell = ctypes.windll.shell32.ShellExecuteW
        shell.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int]
        shell.restype = ctypes.c_void_p
        result = shell(None, 'runas', 'powershell.exe', args, None, 0)
        if (result or 0) <= 32:
            raise HubError('管理员授权被取消或无法启动虚拟机连接组件')

    @staticmethod
    def protect_credentials(username, password):
        """DPAPI CurrentUser: decryptable by the same user's elevated helper only."""
        import base64
        import ctypes as C
        from ctypes import wintypes as W
        class Blob(C.Structure):
            _fields_ = [('size', W.DWORD), ('data', C.POINTER(C.c_ubyte))]
        raw = json.dumps({'username': username, 'password': password}, ensure_ascii=False).encode('utf-8')
        buffer = (C.c_ubyte * len(raw)).from_buffer_copy(raw)
        source, dest = Blob(len(raw), buffer), Blob()
        crypt = C.WinDLL('crypt32', use_last_error=True)
        crypt.CryptProtectData.argtypes = [C.POINTER(Blob), W.LPCWSTR, C.c_void_p, C.c_void_p, C.c_void_p, W.DWORD, C.POINTER(Blob)]
        crypt.CryptProtectData.restype = W.BOOL
        if not crypt.CryptProtectData(C.byref(source), None, None, None, None, 1, C.byref(dest)):
            raise HubError('Windows 无法安全传递凭据')
        try:
            return base64.b64encode(C.string_at(dest.data, dest.size)).decode('ascii')
        finally:
            kernel = C.WinDLL('kernel32')
            kernel.LocalFree.argtypes = [C.c_void_p]
            kernel.LocalFree(C.cast(dest.data, C.c_void_p))
            C.memset(buffer, 0, len(raw))

    def request_record(self, request_id):
        for folder in (self.requests,self.root/'request-history'):
            path=folder/(request_id+'.json')
            try:return path,json.loads(path.read_text(encoding='utf-8'))
            except FileNotFoundError:continue
        raise HubError('虚拟机请求不存在')

    def control(self, action='status', request_id=None, vm_name='', username='', password='', remember=True, unattended=None):
        if action == 'open_manager':
            panel=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32'/'virtmgmt.msc'
            if sys.platform!='win32' or not panel.is_file():raise HubError('本机未安装 Hyper-V 管理工具')
            os.startfile(str(panel))
            return {'state':'completed','opened':True}
        if action == 'status':
            return self.status()
        if action == 'result':
            if not isinstance(request_id, str) or not re.fullmatch(r'[a-f0-9]{32}', request_id):
                raise HubError('连接请求编号无效')
            request,job = self.request_record(request_id)
            if not job.get('control'):
                raise HubError('连接请求不存在')
            path = self.results / (request_id + '.json')
            data=json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {'state':'queued'}
            if data.get('state') not in ('queued','running') and job.get('action')=='thumbnail':
                request.unlink(missing_ok=True);path.unlink(missing_ok=True)
            return data
        if action == 'forget':
            self.saved_path(vm_name).unlink(missing_ok=True)
            return {'state':'completed','forgotten':vm_name}
        if action not in ('list', 'connect', 'connect_saved', 'disconnect','power_on','power_off','power_force','thumbnail'):
            raise HubError('未知虚拟机连接操作')
        if self.status().get('busy') and action not in ('power_on','power_off','power_force','thumbnail'):
            raise HubError('虚拟机正在执行任务，请完成后再更换连接')
        if action=='thumbnail':
            state=self.status()
            if not state.get('helper_alive'):raise HubError('等待管理员连接服务就绪，预览不会触发额外授权')
            if state.get('helper_alive') and isinstance(state.get('operations'),list) and 'thumbnail' not in state['operations']:
                raise HubError('请退出旧版 Hub 后打开新版，以启用缩略图桥接')
        job = {'id': uuid.uuid4().hex, 'control': True, 'action': action, 'created': time.time()}
        if (action.startswith('power_') or action=='thumbnail'):
            if not vm_name:raise HubError('请先选择虚拟机')
            job['vm_name']=vm_name
        if action == 'connect_saved':
            try:data=json.loads(self.saved_path(vm_name).read_text(encoding='utf-8-sig'))
            except (OSError,ValueError):raise HubError('未保存该虚拟机凭据，请重新输入一次') from None
            job.update(action='connect',vm_name=vm_name,credential_encrypted=data['credential_encrypted'],unattended=data.get('unattended',True) if unattended is None else bool(unattended))
        elif action == 'connect':
            if not vm_name.strip() or not username.strip():
                raise HubError('请选择虚拟机并填写 Windows 用户名')
            job.update(vm_name=vm_name, credential_encrypted=self.protect_credentials(username, password),unattended=True if unattended is None else bool(unattended))
        if job['action']=='connect':
            job['remember']=bool(remember)
            job['saved_path']=str(self.saved_path(vm_name))
        self.launch_helper()
        path = self.requests / (job['id'] + '.json')
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(job), encoding='utf-8')
        temp.replace(path)
        if action in ('power_off','power_force'):
            override=self.root/'power-override.json';temporary=override.with_suffix('.tmp')
            temporary.write_text(json.dumps({'vm':vm_name,'created':time.time()}),encoding='utf-8');temporary.replace(override)
        return {'request_id': job['id'], 'state': 'queued'}

    def call(self, project, agent, cwd, action='status', request_id=None, script='', path='', timeout_seconds=300,
             window_handle=None, element_id='', value='', key_codes=None, x=None, y=None, button=0, shell=None):
        if shell is not None:raise HubError('Hyper-V 使用 PowerShell，不接受 POSIX shell')
        # Separate VM directories preserve independent member worktrees.
        if not re.fullmatch(r'[\w-]{1,100}', project) or not re.fullmatch(r'[\w-]{1,100}', agent):
            raise HubError('项目或成员标识无效')
        if action == 'status' and not request_id:
            return self.status()
        if request_id:
            if not re.fullmatch(r'[a-f0-9]{32}', request_id):
                raise HubError('请求编号无效')
            source,job = self.request_record(request_id)
            if job.get('control') or job.get('project') != project or job.get('agent') != agent:
                raise HubError('只能查询自己在本项目的虚拟机操作')
            result = self.results / (request_id + '.json')
            data=json.loads(result.read_text(encoding='utf-8-sig')) if result.exists() else {'request_id': request_id, 'state': 'queued'}
            if job.get('desktop_action') and data.get('state')=='completed':
                try:desktop=json.loads(data.get('output',''))
                except ValueError:return {**data,'state':'failed','error':'桌面服务未返回有效结果，请核查桌面服务状态'}
                data={**desktop,'request_id':request_id}
                if data.get('result',{}).get('image_data'):
                    data['image_data']=data['result'].pop('image_data')
                    raw=base64.b64decode(data['image_data'],validate=True)
                    if not raw.startswith(b'\x89PNG\r\n\x1a\n'):raise HubError('桌面服务返回的图片不是 PNG')
                    local_root=Path(job['local_cwd']).resolve()
                    target=(local_root/'.hub-evidence'/('vm-'+request_id+'.png')).resolve()
                    if not target.is_relative_to(local_root):raise HubError('截图证据目录不在工作目录内')
                    target.parent.mkdir(parents=True,exist_ok=True)
                    target.write_bytes(raw)
                    data['result']['evidence_path']=str(target)
            return data
        desktop_actions={'desktop_status','desktop_release','desktop_launch','screenshot','windows','ui_tree','ui_invoke','ui_set_value'}
        if action not in {'exec','push','pull','key','mouse'} | desktop_actions:
            raise HubError('支持 status、exec、push、pull；桌面控制尚未验证')
        connection=self.status()
        if not connection.get('connected'):
            if connection.get('connection_phase') in ('reconnecting','booting','waiting_windows'):
                raise HubError('虚拟机命令通道正在自动恢复；本次操作尚未提交。请稍后查 status，勿反复发送命令。')
            raise HubError(connection.get('connection_error') or '虚拟机命令通道未连接，请在配置中重新连接')
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 3600:
            raise HubError('超时秒数应在 1–3600 之间')
        guest = str(PureWindowsPath('C:/HubWorkspace') / project / agent)
        job = dict(id=uuid.uuid4().hex, project=project, agent=agent, action=action,
                   guest_cwd=guest, timeout_seconds=timeout_seconds, created=time.time())
        if action in desktop_actions:
            payload=dict(action=action,owner=project+':'+agent,expires=int(time.time())+90,
                         window_handle=window_handle,element_id=element_id,value=value)
            if action=='desktop_launch':
                rel=PureWindowsPath(path)
                if not path or rel.is_absolute() or rel.drive or '..' in rel.parts or ':' in path:
                    raise HubError('请提供当前成员虚拟机工作目录内的可执行文件相对路径')
                payload['executable']=str(PureWindowsPath(guest)/rel)
            encoded=base64.b64encode(json.dumps(payload,ensure_ascii=False).encode('utf-8')).decode('ascii')
            job.update(action='exec',desktop_action=action,local_cwd=str(Path(cwd).resolve()),script=self.desktop_script(encoded))
        elif action in ('key','mouse'):
            if self.status().get('protocol')!=4:
                raise HubError('虚拟键鼠需重开新版 Hub 后重新连接；当前可使用控件自动化')
            if action=='key' and (not isinstance(key_codes,list) or not key_codes or len(key_codes)>8 or any(type(k)is not int or not 1<=k<=255 for k in key_codes)):
                raise HubError('key_codes 应为 1–8 个 Windows 虚拟键码')
            if action=='mouse' and (any(type(v)is not int or not 0<=v<=65535 for v in (x,y)) or button not in (0,1,2)):
                raise HubError('请提供有效鼠标坐标及按钮 0/1/2')
            job.update(key_codes=key_codes,x=x,y=y,button=button,owner=project+':'+agent)
        elif action == 'exec':
            if not isinstance(script, str) or not script.strip():
                raise HubError('请提供在虚拟机中执行的 PowerShell 脚本')
            job['script'] = script
        else:
            rel = PureWindowsPath(path)
            if not path or rel.is_absolute() or rel.drive or '..' in rel.parts or ':' in path:
                raise HubError('文件路径应为当前工作目录内的相对路径')
            root = Path(cwd).resolve()
            local = root.joinpath(*rel.parts).resolve()
            if not local.is_relative_to(root):
                raise HubError('文件不在当前工作目录内')
            if action == 'push' and not local.exists():
                raise HubError('要传入虚拟机的文件不存在')
            job.update(local_path=str(local), guest_path=str(PureWindowsPath(guest) / rel))
        source = self.requests / (job['id'] + '.json')
        temp = source.with_suffix('.tmp')
        temp.write_text(json.dumps(job, ensure_ascii=True), encoding='utf-8')
        temp.replace(source)
        return {'request_id': job['id'], 'state': 'queued', 'guest_cwd': guest,
                'note': '仅已入队，尚未确认成功；用 status 和 request_id 查询，completed 才是完成，failed 请读 error；不要重复提交。'}

    @staticmethod
    def desktop_script(encoded):
        return r'''$root='C:\ProgramData\AgentHubDesktop'
if(-not(Test-Path "$root\status.json")){throw 'Desktop service is not installed or user is not logged in.'}
$heartbeat=Get-Content "$root\status.json" -Raw | ConvertFrom-Json
if(([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()/1000.0)-$heartbeat.updated -gt 15){throw 'Desktop service offline; log into the guest Windows desktop.'}
$id=[guid]::NewGuid().ToString('N')
[IO.File]::WriteAllBytes("$root\requests\$id.tmp",[Convert]::FromBase64String('''+"'"+encoded+"'"+r'''))
Move-Item -LiteralPath "$root\requests\$id.tmp" -Destination "$root\requests\$id.json"
$deadline=(Get-Date).AddSeconds(70)
while((Get-Date) -lt $deadline){
 if(Test-Path "$root\results\$id.json"){
  $reply=Get-Content "$root\results\$id.json" -Raw -Encoding UTF8 | ConvertFrom-Json
  if($reply.state -ne 'running'){
   if($reply.result.image_path){$reply.result|Add-Member -NotePropertyName image_data -NotePropertyValue ([Convert]::ToBase64String([IO.File]::ReadAllBytes($reply.result.image_path)))}
   $reply|ConvertTo-Json -Depth 12 -Compress;return
  }
 };Start-Sleep -Milliseconds 200
}
throw 'Desktop operation timed out; not replayed. Inspect before retrying.'
'''
