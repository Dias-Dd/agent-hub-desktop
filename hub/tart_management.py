"""User-only storage, image and resource management for the Tart backend."""
import os
from pathlib import Path
import re
import time

from .core import HubError


class TartManagement:
    def default_home(self):
        # Stable across upgrades, app moves and DMG launches. --data keeps
        # development/test instances isolated without exposing checkout paths.
        return self.root/'machines'

    def save_preferences(self, **changes):
        with self._lock:
            self.write(self.root/'preferences.json', {**self.preferences(), **changes})

    def resources(self, cpu, memory):
        if type(cpu) is not int or not 1 <= cpu <= (os.cpu_count() or 1):
            raise HubError('CPU 核心数超出本机范围')
        if type(memory) is not int or not 4096 <= memory <= 65536 or memory % 256:
            raise HubError('内存应为 4096–65536 MiB，且为 256 的倍数')
        # Keep at least 2 GiB for the host; never silently change requested values.
        try:
            import subprocess
            total = int(subprocess.check_output(['/usr/sbin/sysctl','-n','hw.memsize'],timeout=5,stderr=subprocess.DEVNULL))//1048576
        except (OSError, ValueError, subprocess.SubprocessError): total = 0
        if total and memory > total-2048: raise HubError('请至少为主机保留 2048 MiB 内存')
        return ['--cpu',str(cpu),'--memory',str(memory)]

    def stopped(self, name):
        row = next((r for r in self.inventory() if r['name']==name), None)
        if not row: raise HubError('所选虚拟机不存在')
        if str(row['state']).lower() != 'stopped': raise HubError('请先关闭虚拟机，再修改资源或删除')

    def management(self, action, vm_name='', image='macos', confirmed=False, cpu=2, memory=4096,
                   source='', source_type='oci', tart_home='', **unused):
        if action == 'browse_home':
            from desktop.folder_picker import pick_directory
            return {'state':'completed','path':pick_directory(self.environment()['TART_HOME'])}
        if action == 'set_home':
            if confirmed is not True: raise HubError('请确认切换虚拟机目录；不会移动或删除原目录')
            path = Path(tart_home).expanduser()
            if not path.is_absolute() or any(p.suffix=='.app' for p in (path,*path.parents)):
                raise HubError('请选择 .app 外的绝对目录')
            with self._lock:
                if self.executable() and any(str(r['state']).lower()=='running' for r in self.inventory()):
                    raise HubError('请先关闭当前目录内的虚拟机，再切换目录')
                for request in self.requests.glob('*.json'):
                    _, result = self.record(request.stem)
                    if result.get('state') in ('queued','running'): raise HubError('虚拟机操作仍在进行，请稍后切换目录')
                path.mkdir(parents=True,exist_ok=True)
                probe=path/('.hub-write-'+str(os.getpid()))
                try: probe.write_bytes(b''); probe.unlink()
                except OSError: raise HubError('目录不可写，请选择当前用户可写的目录') from None
                self.save_preferences(tart_home=str(path.resolve()))
                self._verified.pop(str(self.root.resolve()),None)
                self.write(self.root/'connection.json',{})
            return {'state':'completed','tart_home':str(path.resolve())}
        if action == 'images':
            import json
            return self.queue({'control':True,'action':action},lambda:{'images':json.loads(self.run('list','--source','oci','--format','json'))})
        if action == 'delete_image':
            if confirmed is not True: raise HubError('请确认删除下载的镜像缓存')
            import json
            rows=json.loads(self.run('list','--source','oci','--format','json'))
            if source not in [r.get('Name',r.get('name')) for r in rows]: raise HubError('镜像不在此目录的缓存列表内')
            return self.queue({'control':True,'action':action},lambda:(self.run('delete',source) and {}) or {'deleted':True})
        if action in ('delete','configure'):
            if confirmed is not True: raise HubError('请确认虚拟机管理操作')
            name=self.name(vm_name)
            args=self.resources(cpu,memory) if action=='configure' else []
            def work():
                with self._lock:
                    self.stopped(name)
                    self.run('delete',name) if action=='delete' else self.run('set',name,*args)
                    if action=='delete' and self.selected().get('vm')==name:
                        self.write(self.root/'connection.json',{})
                        self._verified.pop(str(self.root.resolve()),None)
                return {'vm':name,'deleted':action=='delete','configured':action=='configure'}
            return self.queue({'control':True,'action':action,'vm':name},work)
        if action == 'create':
            if confirmed is not True: raise HubError('请确认下载并创建虚拟机，macOS 镜像需要数十 GB')
            name=self.name(vm_name); args=self.resources(cpu,memory)
            source=source.strip() or self.IMAGES.get(image,'')
            if source_type=='oci':
                if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/@-]{1,500}',source) or '/' not in source:
                    raise HubError('请输入有效的 OCI 镜像地址')
                command=['clone',source,name]
            elif source_type=='tvm':
                path=Path(source).expanduser()
                if not path.is_absolute() or not path.is_file() or path.suffix.lower()!='.tvm':
                    raise HubError('请输入本机 .tvm 镜像文件的绝对路径')
                command=['import',str(path),name]
            elif source_type=='ipsw':
                path=Path(source).expanduser()
                if not path.is_absolute() or not path.is_file() or path.suffix.lower()!='.ipsw':
                    raise HubError('请输入本机 .ipsw 恢复镜像的绝对路径')
                command=['create',name,'--from-ipsw',str(path)]
            else: raise HubError('未知镜像来源')
            home=self.environment()['TART_HOME']
            def work():
                with self._lock:
                    if home!=self.environment()['TART_HOME']: raise HubError('虚拟机目录已变化，请重新创建')
                    if any(r['name']==name for r in self.inventory()): raise HubError('同名虚拟机已存在，未覆盖')
                    self.run_download(command,timeout=7200)
                    self.run('set',name,*args,'--display','1280x800px','--no-display-refit')
                return {'vm':name,'created':True,'manual_setup':source_type=='ipsw',
                        'note':'IPSW 安装需在访客完成初始设置，并安装 Guest Agent / Python 3。' if source_type=='ipsw' else '请连接以实际验证 Guest Agent、root 和桌面。'}
            return self.queue({'control':True,'action':action,'vm':name},work)
        raise HubError('未知 Tart 管理操作')

    def run_download(self, args, timeout):
        """Capture real Tart progress without inventing a percentage or replaying a job."""
        import subprocess
        import uuid
        ident=getattr(self._job_context,'ident',None)
        path=self.root/('download-'+uuid.uuid4().hex+'.log')
        descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(descriptor,'wb') as log:
            child=subprocess.Popen([self.executable(),*args],stdout=log,stderr=log,env=self.environment())
            deadline=time.monotonic()+timeout
            try:
                while child.poll() is None:
                    if time.monotonic()>deadline:
                        child.terminate()
                        try:child.wait(timeout=10)
                        except subprocess.TimeoutExpired:child.kill();child.wait()
                        raise HubError('下载超时，未自动重试；请检查磁盘和网络后重新操作')
                    if ident:
                        with path.open('rb') as stream:
                            stream.seek(max(0,path.stat().st_size-2000));tail=stream.read().decode('utf8',errors='replace')
                        tail=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',tail)
                        self.write(self.results/(ident+'.json'),{'state':'running','request_id':ident,'progress':tail[-1500:]})
                    time.sleep(.7)
                if child.returncode:
                    raise HubError('镜像创建失败：'+path.read_text(errors='replace')[-1500:])
            finally:
                if child.poll() is None:child.terminate();child.wait(timeout=10)
                path.unlink(missing_ok=True)
