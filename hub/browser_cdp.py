"""Isolated local Edge/Chromium capture using its public DevTools protocol."""
import base64,json,os,socket,struct,subprocess,tempfile,time,urllib.request
from pathlib import Path
from urllib.parse import urlsplit
from .core import HubError
from .process_job import ProcessJob

class WebSocket:
    def __init__(self,url):
        u=urlsplit(url);self.sock=socket.create_connection((u.hostname,u.port),5);self.sock.settimeout(10);self.counter=0
        key=base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(('GET '+u.path+' HTTP/1.1\r\nHost: '+u.netloc+'\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: '+key+'\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
        response=b''
        try:
            while not response.endswith(b'\r\n\r\n'):
                part=self.sock.recv(1)
                if not part:raise HubError('截图浏览器在 DevTools 握手时断开连接')
                response+=part
                if len(response)>16384:raise HubError('截图浏览器握手响应过大')
            if not response.startswith(b'HTTP/1.1 101'):raise HubError('独立截图浏览器的 DevTools 连接被拒绝')
        except Exception:
            self.sock.close();raise
    def read(self,n):
        data=b''
        while len(data)<n:
            part=self.sock.recv(n-len(data))
            if not part:raise HubError('独立截图浏览器连接已断开')
            data+=part
        return data
    def send(self,payload,opcode=1):
        mask=os.urandom(4);n=len(payload);header=bytes([0x80|opcode,0x80|n]) if n<126 else bytes([0x80|opcode,0xfe])+struct.pack('!H',n) if n<65536 else bytes([0x80|opcode,0xff])+struct.pack('!Q',n)
        self.sock.sendall(header+mask+bytes(c^mask[i%4] for i,c in enumerate(payload)))
    def receive(self):
        message=b''
        while True:
            a,b=self.read(2);n=b&127
            if n==126:n=struct.unpack('!H',self.read(2))[0]
            elif n==127:n=struct.unpack('!Q',self.read(8))[0]
            if n>50000000 or len(message)+n>50000000:raise HubError('截图浏览器响应过大')
            mask=self.read(4) if b&128 else None;data=self.read(n)
            if mask:data=bytes(c^mask[i%4] for i,c in enumerate(data))
            if a&15==8:raise HubError('截图浏览器已关闭连接')
            if a&15==9:self.send(data,10);continue
            if a&15==10:continue
            message+=data
            if a&128:return json.loads(message)
    def call(self,method,params=None):
        self.counter+=1;ident=self.counter;self.send(json.dumps({'id':ident,'method':method,'params':params or {}}).encode())
        while True:
            item=self.receive()
            if item.get('id')!=ident:continue
            if item.get('error'):raise HubError('浏览器 DevTools：'+str(item['error']))
            return item.get('result',{})
    def close(self):self.sock.close()

def capture(exe,url,output,width,height,spawn):
    with tempfile.TemporaryDirectory(prefix='hub-cdp-',ignore_cleanup_errors=True) as folder,tempfile.TemporaryFile() as err:
        args=[exe,'--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--no-proxy-server','--disable-background-networking','--remote-debugging-port=0','--user-data-dir='+folder,'about:blank']
        proc=spawn(args,cwd=str(Path(exe).parent),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=err)
        job=None;ws=None
        try:
            job=ProcessJob(proc);port_file=Path(folder)/'DevToolsActivePort';deadline=time.monotonic()+12
            # Edge's launcher may exit before its isolated browser child opens CDP.
            while not port_file.exists() and time.monotonic()<deadline:time.sleep(.05)
            if not port_file.exists():
                err.seek(0);raise HubError('独立截图浏览器未开放 DevTools；exit='+str(proc.poll())+'；stderr='+err.read()[-1400:].decode('utf8',errors='replace'))
            port=int(port_file.read_text().splitlines()[0]);opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            targets=json.load(opener.open('http://127.0.0.1:'+str(port)+'/json/list',timeout=5));target=next(t for t in targets if t.get('type')=='page')
            ws=WebSocket(target['webSocketDebuggerUrl']);ws.call('Page.enable');ws.call('Network.enable');ws.call('Network.setBlockedURLs',{'urls':['http://*','https://*']})
            ws.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':False})
            ws.call('Page.navigate',{'url':url})
            ready_deadline=time.monotonic()+10
            while True:
                try:ready=ws.call('Runtime.evaluate',{'expression':'document.readyState==="complete" && location.href!=="about:blank"','returnByValue':True}).get('result',{}).get('value')
                except HubError:ready=False
                if ready:break
                if time.monotonic()>ready_deadline:raise HubError('独立浏览器等待本地页面加载超时')
                time.sleep(.05)
            ws.call('Runtime.evaluate',{'expression':'new Promise(resolve=>{const ready=()=>document.fonts.ready.then(()=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(true))));if(document.readyState==="complete")ready();else window.addEventListener("load",ready,{once:true})})','awaitPromise':True,'returnByValue':True})
            data=ws.call('Page.captureScreenshot',{'format':'png','captureBeyondViewport':False,'clip':{'x':0,'y':0,'width':width,'height':height,'scale':1}})
            output.write_bytes(base64.b64decode(data['data']))
        finally:
            if ws:
                try:ws.call('Browser.close')
                except Exception:pass
            if ws:ws.close()
            if job:job.close()
            if proc.poll() is None:proc.kill()
            proc.wait(timeout=5)
