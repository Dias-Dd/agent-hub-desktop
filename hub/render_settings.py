"""Browser discovery and user-owned rendering choices. Never touches browser profiles."""
import json,os,plistlib,shutil,sys,threading
from pathlib import Path
from .core import HubError
DEFAULTS={'mode':'auto','path':''}

def installed():
    candidates=[]
    if sys.platform=='darwin':
        for base in (Path('/Applications'),Path.home()/'Applications'):
            for name,exe in [('Microsoft Edge','Microsoft Edge'),('Google Chrome','Google Chrome'),('Chromium','Chromium'),('Brave Browser','Brave Browser')]:candidates.append((name,base/(name+'.app')/'Contents/MacOS'/exe))
    if os.name=='nt':
        for env in ('PROGRAMFILES','PROGRAMFILES(X86)','LOCALAPPDATA'):
            base=Path(os.environ.get(env,''))
            for name,rel in [('Microsoft Edge','Microsoft/Edge/Application/msedge.exe'),('Google Chrome','Google/Chrome/Application/chrome.exe'),('Chromium','Chromium/Application/chrome.exe'),('Brave','BraveSoftware/Brave-Browser/Application/brave.exe')]:candidates.append((name,base/rel))
    for name in ('chromium','chromium-browser','google-chrome','msedge','brave-browser'):
        path=shutil.which(name)
        if path:candidates.append((name,Path(path)))
    result=[];seen=set()
    for name,path in candidates:
        key=str(path.resolve()).casefold()
        if path.is_file() and key not in seen:result.append({'name':name,'path':str(path.resolve())});seen.add(key)
    return result

def config(hub):
    with hub.lock:row=hub.db.execute("SELECT value FROM settings WHERE key='render_settings'").fetchone()
    return {**DEFAULTS,**(json.loads(row[0]) if row else {})}

def validate(path):
    if not isinstance(path,str) or not path.strip():raise HubError('请选择浏览器主程序')
    file=Path(path.strip()).expanduser()
    if sys.platform=='darwin' and file.suffix.lower()=='.app' and file.is_dir():
        try:
            with (file/'Contents/Info.plist').open('rb') as source:info=plistlib.load(source)
            name=info['CFBundleExecutable']
            if not isinstance(name,str) or not name or Path(name).name!=name:raise ValueError('Invalid executable')
            binary=file/'Contents/MacOS'/name
            if not binary.resolve().is_relative_to(file.resolve()):raise ValueError('Executable outside app')
            file=binary
        except (OSError,ValueError,KeyError,TypeError,plistlib.InvalidFileException):
            raise HubError('应用包中没有有效的浏览器主程序') from None
    if not file.is_absolute() or not file.is_file():raise HubError('浏览器主程序不存在，请选择绝对文件路径')
    if os.name=='nt' and file.suffix.lower()!='.exe':raise HubError('请选择浏览器的 exe 主程序')
    if os.name!='nt' and not os.access(file,os.X_OK):raise HubError('浏览器主程序没有执行权限')
    return str(file.resolve())

def managed(hub):
    p=hub.directory/'browsers'/'chromium'/'installed.json'
    try:
        value=json.loads(p.read_text(encoding='utf-8'));file=Path(value['path']).resolve()
        if not file.is_relative_to(p.parent.resolve()) or not file.is_file():return None
        return value
    except (OSError,ValueError,KeyError):return None

def resolve(hub):
    cfg=config(hub)
    if cfg['mode']=='managed':
        value=managed(hub)
        if not value:raise HubError('尚未安装应用专用 Chromium，请在设置中下载')
        return validate(value['path'])
    if cfg['mode'] in ('installed','custom'):return validate(cfg['path'])
    values=installed()
    if values:return values[0]['path']
    value=managed(hub)
    if value:return validate(value['path'])
    raise HubError('没有可用的渲染浏览器，请在设置中选择主程序或下载 Chromium')

def downloader(hub):
    # One manager per Hub, created only when the settings page is opened.
    with hub.lock:
        if not hasattr(hub,'_chromium_download'):
            from .chromium_download import Download
            hub._chromium_download=Download(hub.directory)
        return hub._chromium_download

def action(hub,actor,operation='read',mode='auto',path=''):
    hub.require(actor,{'user'})
    if operation=='save':
        if mode not in ('auto','installed','custom','managed'):raise HubError('渲染浏览器选择无效')
        if mode in ('installed','custom'):path=validate(path)
        else:path=''
        if mode=='managed' and not managed(hub):raise HubError('请先安装应用专用 Chromium')
        with hub.tx():
            hub.db.execute("INSERT OR REPLACE INTO settings VALUES('render_settings',?)",(json.dumps({'mode':mode,'path':path}),))
            hub.audit(actor,'browser.configured',{'mode':mode,'path':path})
    elif operation=='browse':
        from desktop.folder_picker import pick_file
        return {'path':pick_file()}
    elif operation=='download':downloader(hub).start()
    elif operation=='cancel':downloader(hub).cancel.set()
    elif operation=='test':
        import tempfile
        from .browser_render import spawn_browser
        from .browser_cdp import capture
        exe=resolve(hub)
        with tempfile.TemporaryDirectory(prefix='hub-render-check-') as folder:
            root=Path(folder);page=root/'test.html';page.write_text('<html><body>Deskfellows browser test</body></html>',encoding='utf-8')
            capture(exe,page.as_uri(),root/'test.png',640,480,spawn_browser)
            if not (root/'test.png').read_bytes().startswith(b'\x89PNG'):raise HubError('浏览器未生成有效截图')
        return {'ok':True,'path':exe}
    elif operation!='read':raise HubError('未知渲染设置操作')
    cfg=config(hub)
    try:current=resolve(hub);error=None
    except HubError as problem:current=None;error=str(problem)
    return {'config':cfg,'browsers':installed(),'managed':managed(hub),'current':current,'error':error,'download':downloader(hub).status()}
