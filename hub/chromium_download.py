"""Install Chromium official snapshots into app data with integrity and archive checks."""
import base64,hashlib,http.client,json,os,platform,stat,sys,tempfile,threading,time,urllib.request,urllib.error,urllib.parse,zipfile
from pathlib import Path
from .core import HubError
BUCKET='https://storage.googleapis.com/chromium-browser-snapshots/'
MAX_ARCHIVE=1024*1024*1024


def target():
    arm=platform.machine().lower() in ('arm64','aarch64')
    if sys.platform=='win32':return ('Win_Arm64' if arm else 'Win_x64','chrome-win.zip','chrome-win/chrome.exe')
    if sys.platform=='darwin':return ('Mac_Arm' if arm else 'Mac','chrome-mac.zip','chrome-mac/Chromium.app/Contents/MacOS/Chromium')
    if sys.platform.startswith('linux') and not arm:return ('Linux_x64','chrome-linux.zip','chrome-linux/chrome')
    raise HubError('此平台没有已支持的官方 Chromium 下载包，请自行指定浏览器')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise HubError('下载地址发生重定向，已停止')


def extract(archive,root,cancel):
    root=Path(root).resolve();links=[];total=0
    with zipfile.ZipFile(archive) as zipped:
        items=zipped.infolist()
        if len(items)>50000 or sum(x.file_size for x in items)>3*MAX_ARCHIVE:raise HubError('Chromium 解压体积异常')
        for item in items:
            if cancel.is_set():raise HubError('已取消下载')
            name=item.filename
            if '\\' in name or any(':' in part for part in name.split('/')):raise HubError('下载包包含非法文件路径')
            dest=(root/name).resolve()
            if not dest.is_relative_to(root) or Path(name).is_absolute():raise HubError('下载包包含越界文件路径')
            mode=item.external_attr>>16
            if stat.S_ISLNK(mode):
                if item.file_size>4096:raise HubError('下载包链接无效')
                link=zipped.read(item).decode('utf-8')
                if Path(link).is_absolute() or not (dest.parent/link).resolve().is_relative_to(root):raise HubError('下载包包含越界链接')
                links.append((dest,link));continue
            if item.is_dir():dest.mkdir(parents=True,exist_ok=True);continue
            dest.parent.mkdir(parents=True,exist_ok=True)
            with zipped.open(item) as source,dest.open('wb') as output:
                while chunk:=source.read(256*1024):
                    if cancel.is_set():raise HubError('已取消下载')
                    total+=len(chunk)
                    if total>3*MAX_ARCHIVE:raise HubError('Chromium 解压体积异常')
                    output.write(chunk)
            if os.name!='nt' and mode&0o777:os.chmod(dest,mode&0o777)
        for dest,link in links:
            dest.parent.mkdir(parents=True,exist_ok=True);os.symlink(link,dest)


def transfer(opener,url,archive,size,cancel,progress):
    received=0;md5=hashlib.md5();sha=hashlib.sha256()
    with Path(archive).open('wb') as output:
        for attempt in range(5):
            if cancel.is_set():raise HubError('已取消下载')
            try:
                request=urllib.request.Request(url,headers={'Range':'bytes='+str(received)+'-'} if received else {})
                with opener.open(request,timeout=30) as response:
                    if received:
                        status=getattr(response,'status',200)
                        if status==206:
                            if not response.headers.get('Content-Range','').startswith('bytes '+str(received)+'-'):raise HubError('Chromium 断点下载响应无效')
                        elif status==200:
                            output.seek(0);output.truncate();received=0;md5=hashlib.md5();sha=hashlib.sha256()
                        else:raise HubError('Chromium 下载响应无效')
                    while chunk:=response.read(256*1024):
                        if cancel.is_set():raise HubError('已取消下载')
                        received+=len(chunk)
                        if received>size:raise HubError('Chromium 下载体积异常')
                        output.write(chunk);md5.update(chunk);sha.update(chunk);progress(received=received)
                if received==size:return md5.digest(),sha.hexdigest()
            except urllib.error.HTTPError as error:
                if error.code not in (408,429,500,502,503,504):raise HubError('Chromium 官方下载返回 HTTP '+str(error.code)) from None
            except (OSError,urllib.error.URLError,http.client.IncompleteRead):pass
            if attempt<4:
                progress(retrying=True)
                if cancel.wait(min(2**attempt,8)):raise HubError('已取消下载')
                progress(retrying=False)
        raise HubError('网络多次中断，Chromium 下载未完成，请检查网络后重试')


class Download:
    def __init__(self,directory):
        self.root=Path(directory)/'browsers'/'chromium';self.lock=threading.RLock();self.cancel=threading.Event();self.value={'state':'idle','received':0,'total':None};self.thread=None
    def status(self):
        with self.lock:return dict(self.value)
    def update(self,**values):
        with self.lock:self.value.update(values)
    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():return
            target();self.cancel.clear();self.value={'state':'downloading','received':0,'total':None}
            self.thread=threading.Thread(target=self.run,daemon=True,name='hub-chromium-download');self.thread.start()
    def run(self):
        try:
            group,filename,relative=target();opener=urllib.request.build_opener(NoRedirect())
            def small(url):
                with opener.open(urllib.request.Request(url,headers={'User-Agent':'AgentHub Chromium installer'}),timeout=30) as response:
                    data=response.read(262145)
                    if len(data)>262144:raise HubError('Chromium 下载元数据过大')
                    return data
            revision=small(BUCKET+group+'/LAST_CHANGE').decode('ascii').strip()
            if not revision.isdigit() or len(revision)>12:raise HubError('Chromium 官方版本信息无效')
            key=group+'/'+revision+'/'+filename
            metadata=json.loads(small('https://storage.googleapis.com/storage/v1/b/chromium-browser-snapshots/o/'+urllib.parse.quote(key,safe='')+'?fields=size,md5Hash'))
            size=int(metadata['size']);digest=base64.b64decode(metadata['md5Hash'],validate=True)
            if not 0<size<=MAX_ARCHIVE or len(digest)!=16:raise HubError('Chromium 下载信息无效')
            self.root.mkdir(parents=True,exist_ok=True);self.update(total=size,revision=revision)
            with tempfile.TemporaryDirectory(prefix='.download-',dir=self.root,ignore_cleanup_errors=True) as tmp:
                folder=Path(tmp);archive=folder/'chromium.zip'
                actual,sha256=transfer(opener,BUCKET+key,archive,size,self.cancel,self.update)
                if actual!=digest:raise HubError('Chromium 下载校验失败，请重试')
                self.update(state='installing');unpacked=folder/'unpacked';unpacked.mkdir();extract(archive,unpacked,self.cancel)
                binary=unpacked/relative
                if not binary.is_file():raise HubError('下载包中没有 Chromium 主程序')
                if os.name!='nt':os.chmod(binary,binary.stat().st_mode|0o111)
                if self.cancel.is_set():raise HubError('已取消下载')
                # Unique directory: never replace a selected or running browser.
                destination=self.root/(group+'-'+revision+'-'+str(time.time_ns()));unpacked.rename(destination)
                record={'path':str((destination/relative).resolve()),'revision':revision,'platform':group,'source':BUCKET+key,'sha256':sha256}
                manifest=self.root/'installed.json';temporary=self.root/'installed.json.tmp';temporary.write_text(json.dumps(record),encoding='utf-8');temporary.replace(manifest)
            self.update(state='completed',path=record['path'])
        except Exception as error:
            message=str(error) if isinstance(error,HubError) else 'Chromium 下载或安装失败，请检查网络、可用空间后重试'
            self.update(state='cancelled' if self.cancel.is_set() else 'failed',error=message,error_kind=type(error).__name__)
