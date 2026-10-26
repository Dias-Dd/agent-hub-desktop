"""Bounded local-page rendering with a clean browser profile, separate from agent shell policy."""
import base64,hashlib,json,os,shutil,subprocess,tempfile,time,threading,sys
from pathlib import Path
from urllib.parse import urlsplit
from .core import HubError,uid

def executable():
    supplied=os.environ.get('HUB_TEST_BROWSER','')
    if supplied and Path(supplied).is_file():return supplied
    if sys.platform=='darwin':
        for base in (Path('/Applications'),Path.home()/'Applications'):
            for app,name in (('Microsoft Edge','Microsoft Edge'),('Google Chrome','Google Chrome'),('Chromium','Chromium')):
                candidate=base/(app+'.app')/'Contents/MacOS'/name
                if candidate.is_file():return str(candidate)
    for base in ('PROGRAMFILES(X86)','PROGRAMFILES','LOCALAPPDATA'):
        for rel in ('Microsoft/Edge/Application/msedge.exe','Google/Chrome/Application/chrome.exe'):
            file=Path(os.environ.get(base,''))/rel
            if file.is_file():return str(file)
    for name in ('chromium','chromium-browser','google-chrome','msedge'):
        found=shutil.which(name)
        if found:return found
    raise HubError('未找到可用的 Edge/Chrome/Chromium 浏览器，请安装浏览器后重试')

_spawn_lock=threading.Lock()
def browser_environment():
    env=os.environ.copy()
    for key in list(env):
        if key.startswith(('QTWEBENGINE_','WEBVIEW2_','_PYI_','CHROME_','ELECTRON_')) or key in ('PYTHONHOME','PYTHONPATH'):
            env.pop(key,None)
    frozen=str(getattr(sys,'_MEIPASS',''))
    if frozen:env['PATH']=os.pathsep.join(p for p in env.get('PATH','').split(os.pathsep) if not p.casefold().startswith(frozen.casefold()))
    return env

def spawn_browser(argv,**kwargs):
    kwargs.setdefault('start_new_session',os.name!='nt')
    kwargs.setdefault('env',browser_environment());kwargs.setdefault('creationflags',getattr(subprocess,'CREATE_NO_WINDOW',0))
    with _spawn_lock:
        kernel=None;old=None
        if os.name=='nt' and getattr(sys,'frozen',False):
            import ctypes
            kernel=ctypes.WinDLL('kernel32',use_last_error=True)
            buffer=ctypes.create_unicode_buffer(32768)
            kernel.GetDllDirectoryW(len(buffer),buffer);old=buffer.value
            kernel.SetDllDirectoryW(None)
        try:
            child=subprocess.Popen(argv,**kwargs)
        finally:
            if kernel:kernel.SetDllDirectoryW(old or None)
    return child

def launch_browser(argv,timeout=30):
    child=spawn_browser(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:stdout,stderr=child.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        child.kill();child.communicate()
        raise
    return subprocess.CompletedProcess(argv,child.returncode,stdout,stderr)

def failure_detail(result,output):
    code=result.returncode
    return ('exit='+str(code)+' (0x'+format(code&0xffffffff,'08X')+'); PNG='+str(output.is_file())+
            '; stderr='+(result.stderr.decode('utf8',errors='replace')[-1600:] or '(empty)')+
            '; stdout='+(result.stdout.decode('utf8',errors='replace')[-800:] or '(empty)'))

def render(service,actor,run_id,path,width=1280,height=800):
    if type(width)!=int or type(height)!=int or not 320<=width<=2560 or not 240<=height<=2160:raise HubError('截图尺寸需在320×240到2560×2160内')
    with service.server.workflows.lock:
        w,run=service.server.workflows.run_context(actor,run_id)
        if service.server.coordination.is_stopped(actor):raise HubError('停止锁有效，未启动截图')
        # Split URL routing before filesystem validation; never resolve a URL as a path.
        if not isinstance(path,str) or not path.strip():raise HubError('请选择本地HTML页面')
        local,sep,fragment=path.partition('#')
        filename,query_sep,query=local.partition('?')
        # A Windows drive prefix is a local path, not a URL scheme.
        windows_drive=len(filename)>2 and filename[1]==':' and filename[2] in ('/',chr(92))
        parsed=urlsplit(filename.replace(chr(92),'/'))
        if (parsed.scheme and not windows_drive) or parsed.netloc:raise HubError('只能渲染本地HTML页面，不接受远程URL')
        root=Path(run['cwd']).resolve();source=(root/filename).resolve()
        roots=[root]
        if w.get('design_baseline'):roots.append(Path(w['design_baseline']['directory']).resolve())
        if not any(source.is_relative_to(r) for r in roots) or not source.is_file() or source.suffix.lower() not in ('.html','.htm'):raise HubError('只能渲染当前项目或已确认基线内的本地HTML页面')
        page_url=source.as_uri()+('?' + query if query_sep else '')+('#' + fragment if sep else '')
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        from .render_settings import config as render_config,resolve
        exe=resolve(service.hub) if render_config(service.hub)['mode']!='auto' else _automatic_browser(service.hub)
    ident=uid()+uid();folder=service.root/ident;folder.mkdir();output=folder/'screenshot.png'
    try:
        with tempfile.TemporaryDirectory(prefix='hub-browser-',ignore_cleanup_errors=True) as profile:
            argv=[exe,'--headless','--disable-gpu','--no-first-run','--no-default-browser-check','--hide-scrollbars','--disable-background-networking','--disable-sync','--no-proxy-server','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost','--user-data-dir='+profile,'--window-size='+str(width)+','+str(height),'--force-device-scale-factor=1','--virtual-time-budget=1500','--screenshot='+str(output.resolve()),page_url]
            try:
                result=launch_browser(argv)
            except subprocess.TimeoutExpired:raise HubError('浏览器截图超时（30秒），本次未形成视觉验收证据') from None
            if not result.returncode and not output.is_file():
                # Some Edge launchers exit successfully without honoring --screenshot.
                # Use the browser's public protocol with an isolated profile, not account UI.
                from .browser_cdp import capture
                try:capture(exe,page_url,output,width,height,spawn_browser)
                except Exception as error:
                    detail=failure_detail(result,output)+'; DevTools='+str(error)[:1600]
                    with service.hub.tx():service.hub.audit(actor,'browser.render_failed',{'run_id':run_id,'source':str(source),'detail':detail})
                    raise HubError('浏览器截图失败：'+detail) from None
            if result.returncode or not output.is_file():
                detail=failure_detail(result,output)
                with service.hub.tx():service.hub.audit(actor,'browser.render_failed',{'run_id':run_id,'source':str(source),'page_url':page_url,'browser':exe,'detail':detail})
                raise HubError('浏览器截图失败：'+detail)
        image=output.read_bytes()
        if not image.startswith(bytes([137,80,78,71,13,10,26,10])):raise HubError('浏览器未生成有效PNG截图')
        with service.server.workflows.lock:
            service.server.workflows.run_context(actor,run_id)
            if service.server.coordination.is_stopped(actor):raise HubError('截图期间已停止，不发布新产物')
        item={'id':ident,'project_id':w.get('project_id') or w['id'],'workflow_id':w['id'],'sender':actor,'kind':'image','caption':'浏览器实际渲染：'+source.name,'entry':'screenshot.png','url':'/api/shared/'+ident+'/screenshot.png','created':time.time()}
        with service.hub.tx():
            service.hub.db.execute('INSERT INTO shared_artifacts VALUES(?,?)',(ident,json.dumps(item,ensure_ascii=False)))
            service.hub.audit(actor,'browser.rendered',{'project':item['project_id'],'run_id':run_id,'source':str(source),'page_url':page_url,'source_sha256':digest,'artifact':ident})
        return {**item,'source':str(source),'page_url':page_url,'source_sha256':digest,'width':int.from_bytes(image[16:20],'big'),'height':int.from_bytes(image[20:24],'big'),'image_data':base64.b64encode(image).decode(),'mimeType':'image/png','note':'此截图仅证明所选页面的渲染，不等于功能或全部页面验收通过。'}
    except Exception:
        if folder.resolve().is_relative_to(service.root.resolve()):shutil.rmtree(folder,ignore_errors=True)
        raise


def _automatic_browser(hub):
    try:return executable()
    except HubError:
        from .render_settings import resolve
        return resolve(hub)
