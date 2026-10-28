"""Local Tart console and project-owned desktop lease; independent of command jobs."""
import base64
import json
import os
from pathlib import Path
import re
import time
import uuid
from .core import HubError
from .tart_rfb import Console


class TartDesktop:
    def endpoint(self, name):
        try:
            # Console passwords are kept only in a private local runtime log.
            text=(self.root/(name+'.log')).read_text(encoding='utf-8',errors='replace')[-65536:]
            matches=re.findall(r'vnc://[^\s\x1b]+',text)
            return matches[-1] if matches else None
        except OSError:return None

    def desktop_status(self, name):
        endpoint=bool(self.endpoint(name))
        ready=bool(endpoint and self._desktop_verified.get((str(self.root.resolve()),name)))
        return {'ready':ready, 'experimental':True,
                'warning':'' if ready else ('桌面截图尚未验证，请重新连接。' if endpoint else '没有可用控制台；请先关机，再从 Hub 开机。'),
                'limitations':'VNC 为实验性通道；控件操作需要访客 Peekaboo 授权。',
                'accessibility':self.ax_state(name),
                'text':'ASCII', 'ui_automation':bool(self.ax_state(name).get('ready'))}

    def desktop_lease(self, project, agent, name, release=False, inspect=False):
        import fcntl
        key=f'{project}/{agent}'
        with open(self.root/'desktop.lock','a') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX)
            path=self.root/'desktop-lease.json'
            try:state=json.loads(path.read_text(encoding='utf-8'))
            except (OSError,ValueError):state={}
            busy=state.get('expires',0)>time.time() and state.get('vm')==name
            if inspect:return {'busy':busy,'owned':busy and state.get('owner')==key,'expires':state.get('expires') if busy else None}
            if busy and state.get('owner')!=key:raise HubError('其他 Agent 正在使用此虚拟机桌面；命令通道仍可并发执行')
            if release:
                if busy:path.unlink(missing_ok=True)
                return {'released':True}
            self.write(path,{'owner':key,'vm':name,'expires':time.time()+120})

    def leased_desktop_work(self, project, agent, name, action, args, cwd):
        with self._desktop_lock:
            self.desktop_lease(project,agent,name)
            return self.desktop_work(name,action,args,cwd)

    def desktop_work(self, name, action, args, cwd=None):
        endpoint=self.endpoint(name)
        if not endpoint:raise HubError('此虚拟机没有 Hub 桌面通道；请先关闭，再从 Hub 开机，不能自动中断正在运行的虚拟机')
        with self._desktop_lock:
            console=Console(endpoint)
            try:
                if action=='screenshot':
                    raw=console.screenshot()
                    self._desktop_verified[(str(self.root.resolve()),name)]=True
                    result={'available':True,'format':'png','width':console.width,'height':console.height,
                            'image_data':base64.b64encode(raw).decode()}
                    if cwd:
                        root=Path(cwd).resolve();folder=root/'.hub-evidence'
                        folder.mkdir(exist_ok=True)
                        if not folder.resolve().is_relative_to(root):raise HubError('截图目录越界')
                        path=folder/('vm-'+uuid.uuid4().hex+'.png');path.write_bytes(raw)
                        result['path']=str(path.relative_to(root))
                    return result
                if action=='key':
                    keys=args.get('keys')
                    if keys is None:
                        codes=args.get('key_codes',[])
                        mapping={16:'shift',17:'ctrl',18:'option',91:'cmd',13:'enter',27:'escape',9:'tab',8:'backspace',
                                 37:'left',38:'up',39:'right',40:'down',46:'delete',32:'space'}
                        keys=[mapping.get(c,chr(c).lower() if type(c) is int and 48<=c<=90 else '') for c in codes]
                    console.chord(keys)
                elif action=='text':console.text(args.get('value',''))
                elif action in ('mouse','drag','scroll'):
                    x=args.get('x');y=args.get('y')
                    console.pointer(x,y)
                    if action=='mouse':
                        button=args.get('button',0)
                        if type(button) is not int or button not in (0,1,2):raise HubError('button 只能为 0/1/2')
                        if button:
                            console.pointer(x,y,1 if button==1 else 4);time.sleep(.1);console.pointer(x,y)
                    elif action=='drag':
                        end_x=args.get('end_x');end_y=args.get('end_y')
                        console.pointer(end_x,end_y);console.pointer(x,y)
                        try:
                            console.pointer(x,y,1);time.sleep(.1)
                            for i in range(1,21):
                                console.pointer(round(x+(end_x-x)*i/20),round(y+(end_y-y)*i/20),1);time.sleep(.02)
                        finally:console.pointer(end_x,end_y)
                    else:
                        steps=args.get('steps',1)
                        if type(steps) is not int or not 1<=abs(steps)<=100:raise HubError('滚动步数应为 ±1–100')
                        # macOS base uses natural scrolling; positive means content down.
                        for _ in range(abs(steps)):
                            console.pointer(x,y,8 if steps>0 else 16);console.pointer(x,y);time.sleep(.02)
                else:raise HubError('Tart 尚不支持此桌面操作')
                return {'sent':True,'note':'输入已发送；请截图核对结果，不自动重试输入。'}
            finally:console.close()
