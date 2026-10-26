"""Serve the real app shell before importing/initializing backend services."""
import html
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class FastHub:
    def __init__(self, data, port, simulate=False,startup_extras=True):
        self.backend=None;self.closing=False;self.error=None;self.startup_extras=startup_extras
        self.data=Path(data)
        root=Path(__file__).resolve().parents[1]
        class Server(ThreadingHTTPServer):
            daemon_threads=True;allow_reuse_address=True
            request_queue_size=128
        owner=self
        session=secrets.token_urlsafe(32)
        class Shell(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(handler):
                if handler.headers.get('Host') not in (f'127.0.0.1:{owner.port}',f'localhost:{owner.port}'):
                    handler.send_error(403);return
                path=handler.path.split('?',1)[0]
                if path=='/startup-status':return handler.reply(200,owner.server.startup)
                name='index.html' if path in ('/','/setup') else path.lstrip('/')
                if '/' in name or chr(92) in name or ':' in name or name.startswith('.'):
                    handler.send_error(404);return
                target=root/'hub/static'/name
                if not target.is_file() or target.suffix not in ('.html','.css','.js','.svg','.json'):
                    return handler.reply(503,{'error':'Hub 正在加载','starting':True})
                text=target.read_text(encoding='utf-8')
                if name=='index.html':
                    from desktop.ui_preferences import language
                    meta='<meta name="hub-desktop-session" content="'+session+'"><meta name="hub-credentials-path" content="'+html.escape(str(owner.data/'credentials.json'),quote=True)+'">'
                    meta+='<meta name="hub-interface-language" content="'+language(owner.data)+'">'
                    text=text.replace('<head>','<head>'+meta,1)
                handler.reply(200,json.loads(text) if target.suffix=='.json' else text,{'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.json':'application/json'}[target.suffix])
            def do_POST(handler):
                if handler.path=='/startup-ui-ready' and handler.headers.get('X-Desktop-Session')==session and handler.headers.get('Origin') in (f'http://127.0.0.1:{owner.port}',f'http://localhost:{owner.port}'):
                    owner.server.ui_ready.set();return handler.reply(200,{'ok':True})
                handler.reply(503,{'error':'Hub 正在加载，请稍候','starting':True})
            def reply(handler,status,body,kind='application/json'):
                raw=(json.dumps(body,ensure_ascii=False) if kind=='application/json' else body).encode('utf-8')
                handler.send_response(status);handler.send_header('Content-Type',kind+'; charset=utf-8')
                handler.send_header('Content-Length',str(len(raw)));handler.send_header('Cache-Control','no-store')
                handler.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'")
                handler.end_headers()
                try:handler.wfile.write(raw)
                except OSError:pass
        self.server=Server(('127.0.0.1',port),Shell)
        self.server.desktop_session=session
        self.server.ui_ready=threading.Event()
        self.server.startup={'backend_ready':False,'stages':{
            'backend':{'state':'loading','label':'加载 Hub 后台'},
            'dependencies':{'state':'waiting','label':'准备本机依赖'},
            'vm':{'state':'waiting','label':'准备虚拟机连接'}}}
        self.server.serving_thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.server.serving_thread.start()
        # Ask for the guest bridge's elevation immediately, independently of
        # backend/database/provider startup and the page's UI-ready handshake.
        # ShellExecute can wait for consent on this worker; the real UI keeps loading.
        if self.startup_extras:
            self.vm_initializer=threading.Thread(target=self.virtual_machine,daemon=True)
            self.vm_initializer.start()
        else:
            self.vm_initializer=None
            self.stage('vm','skipped','测试模式未启动虚拟机连接')
        self.initializer=threading.Thread(target=self.initialize,args=(simulate,),daemon=True)
        self.initializer.start()

    @property
    def port(self):return self.server.server_address[1]

    def stage(self,name,state,label):self.server.startup['stages'][name]={'state':state,'label':label}

    def initialize(self,simulate):
        try:
            from desktop.launch_desktop import OwnedHub
            self.backend=OwnedHub(self.data,self.port,simulate,prebound=self.server)
            self.server.startup['backend_ready']=True
            self.stage('backend','ready','Hub 后台已就绪')
            if self.closing:
                self.backend.close();return
            threading.Thread(target=self.dependencies,daemon=True).start()
        except Exception as error:
            self.error=type(error).__name__+': '+str(error)[:300]
            self.stage('backend','failed','Hub 启动失败：'+self.error)

    def dependencies(self):
        self.stage('dependencies','loading','加载本机依赖')
        try:
            from desktop.dependencies import start_dependencies
            if not self.closing and self.startup_extras:start_dependencies(self.data)
            self.stage('dependencies','ready','本机依赖检查完成')
        except Exception:
            self.stage('dependencies','failed','部分本机依赖未启动，可在配置中重试')

    def virtual_machine(self):
        if self.closing:return
        from hub.vm_bridge import VmBridge
        bridge=VmBridge(self.data)
        if __import__('sys').platform=='darwin':
            if not bridge.preferences().get('auto_connect',True):
                self.stage('vm','skipped','已关闭 Tart 自动连接');return
        saved=bridge.saved_connections()
        if not saved:
            self.stage('vm','skipped','未保存虚拟机凭据，可在配置中连接');return
        try:
            preferred=json.loads((bridge.root/'last-vm.json').read_text(encoding='utf-8-sig'))['vm']
        except (OSError,ValueError,KeyError):preferred=saved[0]['vm']
        try:
            mac=__import__('sys').platform=='darwin'
            self.stage('vm','loading','启动并验证 Tart Guest Agent' if mac else '启动并连接虚拟机（可能需要 Windows 授权）')
            request=bridge.control('auto_connect' if mac else 'connect_saved',vm_name=preferred)
            if request.get('skipped'):
                self.stage('vm','skipped','本次不自动启动虚拟机，可在设置中手动连接');return
            end=time.monotonic()+600
            while not self.closing and time.monotonic()<end:
                result=bridge.control('result',request_id=request['request_id'])
                if result.get('state')=='completed':
                    warning='；'.join(filter(None,[result.get('desktop_warning'),result.get('unattended_warning')]))
                    self.stage('vm','ready','虚拟机命令已连接'+('；'+warning if warning else '，桌面服务已就绪'))
                    return
                if result.get('state') not in ('queued','running'):raise RuntimeError(result.get('error','连接未完成'))
                time.sleep(.5)
            if not self.closing:raise RuntimeError('虚拟机连接超时，可在配置中重试')
        except Exception as error:self.stage('vm','failed','虚拟机：'+str(error)[:200])

    def close(self):
        self.closing=True
        self.initializer.join(timeout=10)
        if self.backend:
            # initialize owns cleanup if it observed closing before starting dependencies.
            if not getattr(self.backend,'_closed',False):
                self.backend.close()
        else:
            self.server.shutdown();self.server.server_close()
