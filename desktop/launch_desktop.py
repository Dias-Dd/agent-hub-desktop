"""Same-origin desktop app and owned local Hub lifecycle (also works when frozen)."""
import argparse
import html
import hashlib
import secrets
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import urllib.request

ROOT_DIR = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
DEFAULT_DATA = ((Path.home() / 'Library/Application Support') if sys.platform == 'darwin'
                else Path(os.environ.get('LOCALAPPDATA', str(Path.home())))) / 'AgentMessageHubDesktop' / 'data'
MAC_DESKTOP_BUILD='macos-vm-shutdown-colors-13'


def detect_environment():
    # Do not import the Win32 host on macOS (ctypes.wintypes is Windows-only).
    if sys.platform == 'win32':
        from desktop.native_webview import find_loader
        loader = find_loader()
    else:
        loader = None
    import importlib.util
    import platform
    env = {'python': sys.version, 'platform': sys.platform, 'native_webview2': loader,
           'native_wkwebview': sys.platform == 'darwin' and int(platform.mac_ver()[0].split('.')[0]) >= 14 and bool(importlib.util.find_spec('WebKit'))}
    for name, vendor, exe in [('msedge', 'Microsoft/Edge', 'msedge.exe'), ('chrome', 'Google/Chrome', 'chrome.exe')]:
        candidates = [Path(os.environ.get(base, '')) / vendor / 'Application' / exe
                      for base in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA')]
        env[name] = next((str(p) for p in candidates if p.is_file()), shutil.which(exe))
    import importlib.util
    for module in ('webview', 'PyInstaller'):
        env[{'webview': 'pywebview', 'PyInstaller': 'pyinstaller'}[module]] = bool(importlib.util.find_spec(module))
    return env


def get_user_token(data_dir):
    """Never fall back to another instance's credentials."""
    try:
        return json.loads((Path(data_dir) / 'credentials.json').read_text(encoding='utf-8')).get('user')
    except (OSError, ValueError):
        return None


def check_health(port, token):
    if not token:
        return False
    try:
        req = urllib.request.Request(f'http://127.0.0.1:{port}/health', headers={'Authorization': 'Bearer ' + token})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=2) as response:
            return response.status == 200 and json.load(response).get('ok') is True
    except (OSError, ValueError):
        return False


def ensure_context_seeded(data_dir, force_sync=False):
    db_file = Path(data_dir) / 'hub.sqlite3'
    target_project_id = '2481457293934dd183a2aa78f8776465'
    needs_sync = force_sync
    if not needs_sync:
        if not db_file.exists():
            needs_sync = True
        else:
            try:
                import sqlite3
                conn = sqlite3.connect(f'file:{db_file.resolve().as_posix()}?mode=ro', uri=True)
                has_proj = bool(conn.execute('SELECT 1 FROM hub_projects WHERE id = ?', (target_project_id,)).fetchone())
                conn.close()
                if not has_proj:
                    needs_sync = True
            except Exception:
                needs_sync = True

    if needs_sync:
        try:
            from desktop.migrate_project_context import migrate
            res = migrate(target_db=db_file)
            print(f"Project context auto-seeded/synced: {res.get('total_projects', 0)} projects, {res.get('total_messages', 0)} messages.")
        except Exception as err:
            print(f"Warning: context seeding skipped or encountered error: {err}", file=sys.stderr)


from desktop.fast_start import FastHub

class OwnedHub:
    def __init__(self, data, port, simulate=False, prebound=None):
        from hub.server import build, Handler
        from hub.core import HubError
        self.server = build(str(data), port=port, simulate=simulate,prebound=prebound,seed_defaults=sys.platform!='darwin')
        if sys.platform=='darwin':self.server.desktop_build=MAC_DESKTOP_BUILD
        # Only an owned desktop instance exposes this bridge. Bearer credentials
        # never appear in HTML, URLs, browser storage, logs or command arguments.
        session = getattr(self.server,"desktop_session",None) or secrets.token_urlsafe(32)
        self.server.desktop_session = session
        credential_path = str(Path(data).resolve() / 'credentials.json')

        class DesktopHandler(Handler):
            def do_GET(handler):
                if handler.path=='/startup-status' and hasattr(handler.server,'startup'):
                    handler.check();return handler.respond(200,handler.server.startup)
                if handler.path not in ('/', '/setup'):
                    return super().do_GET()
                try:
                    handler.check()
                    page = (ROOT_DIR / 'hub' / 'static' / 'index.html').read_text(encoding='utf-8')
                    from desktop.ui_preferences import language
                    meta = ('<meta name="hub-desktop-session" content="' + session + '">'
                            '<meta name="hub-interface-language" content="' + language(data) + '">'
                            '<meta name="hub-credentials-path" content="' + html.escape(credential_path, quote=True) + '">')
                    handler.respond(200, page.replace('<head>', '<head>' + meta, 1), 'text/html')
                except HubError as error:
                    handler.respond(403, {'error': str(error)})

            def do_POST(handler):
                if handler.path not in ('/desktop-session','/desktop-ui','/startup-ui-ready'):
                    return super().do_POST()
                try:
                    handler.check()
                    origin = handler.headers.get('Origin', '')
                    own_port = handler.server.server_address[1]
                    if (origin not in (f'http://127.0.0.1:{own_port}', f'http://localhost:{own_port}')
                            or handler.headers.get('Sec-Fetch-Site') != 'same-origin'
                            or not secrets.compare_digest(handler.headers.get('X-Desktop-Session', ''), session)):
                        raise HubError('desktop session requires the owned same-origin page')
                    if handler.path=='/startup-ui-ready':
                        if hasattr(handler.server,'ui_ready'):handler.server.ui_ready.set()
                        return handler.respond(200,{'ok':True})
                    if handler.path == '/desktop-ui':
                        length=int(handler.headers.get('Content-Length','0'))
                        if not 0 < length <= 128: raise HubError('invalid desktop UI request')
                        payload=json.loads(handler.rfile.read(length))
                        if not isinstance(payload,dict): raise HubError('invalid payload')
                        resp = {}
                        if 'zoom' in payload:
                            if sys.platform == 'darwin':
                                from desktop.macos_webview import request_native_zoom
                            else:
                                from desktop.native_webview import request_native_zoom
                            if not request_native_zoom(payload['zoom']):
                                raise HubError('native zoom unavailable or invalid')
                            resp['zoom'] = payload['zoom']
                        if 'theme' in payload:
                            if sys.platform == 'darwin':
                                from desktop.macos_webview import set_native_dark_mode
                            else:
                                from desktop.native_webview import set_native_dark_mode
                            set_native_dark_mode(payload['theme'] == 'dark')
                            resp['theme'] = payload['theme']
                        handler.respond(200, resp)
                    else:
                        handler.respond(200, {'token': get_user_token(data)})
                except (HubError,ValueError,TypeError) as error:
                    handler.respond(403, {'error': str(error)})

        self.server.RequestHandlerClass = DesktopHandler
        if prebound is None:
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.thread.start()
        else:self.thread=prebound.serving_thread

    @property
    def port(self):
        return self.server.server_address[1]

    def close(self):
        if getattr(self,'_closed',False):return
        self._closed=True
        s = self.server
        s.stop_event.set()
        s.worker.join(timeout=5)
        s.shutdown()
        self.thread.join(timeout=5)
        for runtime in (s.quota_monitor, s.integrations, s.deepseek, s.codex, s.antigravity):
            runtime.close()
        s.server_close()
        s.hub.db.close()
        s.guard.close()


def launch_app(executable, url, profile):
    profile.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen([executable, '--app=' + url, '--user-data-dir=' + str(profile),
                             '--window-size=1366,860', '--no-first-run', '--no-default-browser-check',
                             '--disable-background-mode'],
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000) if os.name == 'nt' else 0)


def check_static_assets(port):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    paths = ('/i18n.js','/i18n.json','/popup.html','/popup.js','/windows.js','/windows.css','/', '/style.css', '/api-client.js', '/state-store.js', '/app.js',
             '/workflow.js', '/deepseek.js', '/codex.js', '/antigravity.js', '/setup.js', '/vm-ui.js','/startup.js')
    expected = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
    for path in paths:
        with opener.open(f'http://127.0.0.1:{port}{path}', timeout=3) as response:
            if response.status != 200 or response.headers.get('Content-Security-Policy') != expected or not response.read():
                raise RuntimeError('Static asset/CSP check failed: ' + path)
    return len(paths)



def listener_pid(port):
    """Resolve a local IPv4 listener through the public Windows TCP owner table."""
    if sys.platform=='darwin':
        result=subprocess.run(['/usr/sbin/lsof','-nP','-iTCP:'+str(port),'-sTCP:LISTEN','-t'],capture_output=True,text=True,timeout=3)
        values=set(result.stdout.split())
        return int(next(iter(values))) if len(values)==1 else None
    if sys.platform!='win32':return None
    import ctypes as C,socket
    class Row(C.Structure):
        _fields_=[(name,C.c_uint32) for name in ('state','local_addr','local_port','remote_addr','remote_port','pid')]
    api=C.WinDLL('iphlpapi').GetExtendedTcpTable
    api.argtypes=[C.c_void_p,C.POINTER(C.c_uint32),C.c_bool,C.c_uint32,C.c_uint32,C.c_uint32];api.restype=C.c_uint32
    size=C.c_uint32();api(None,C.byref(size),False,2,3,0)
    for _ in range(3):
        buffer=C.create_string_buffer(size.value);status=api(buffer,C.byref(size),False,2,3,0)
        if status==122:continue
        if status:return None
        count=C.c_uint32.from_buffer(buffer).value
        for index in range(count):
            row=Row.from_buffer(buffer,4+index*C.sizeof(Row))
            if socket.ntohs(row.local_port&0xffff)==port:return row.pid
        return None
    return None


def restore_existing_window(port):
    if sys.platform=='darwin':
        import AppKit as A
        import Foundation as F
        pid=listener_pid(port)
        app=A.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid) if pid else None
        if not app:return False
        F.NSDistributedNotificationCenter.defaultCenter().postNotificationName_object_('AgentHubActivate',str(pid))
        return bool(app.activateWithOptions_(A.NSApplicationActivateAllWindows|A.NSApplicationActivateIgnoringOtherApps))
    if sys.platform!='win32':return False
    import ctypes as C
    pid=listener_pid(port)
    if not pid:return False
    user=C.WinDLL('user32');user.FindWindowW.argtypes=[C.c_wchar_p,C.c_wchar_p];user.FindWindowW.restype=C.c_void_p
    hwnd=user.FindWindowW('AgentMessageHubNative'+str(pid),None)
    if not hwnd:return False
    user.ShowWindowAsync.argtypes=[C.c_void_p,C.c_int];user.SetForegroundWindow.argtypes=[C.c_void_p]
    user.ShowWindowAsync(hwnd,9);user.SetForegroundWindow(hwnd)
    return True


def existing_ui_matches(port):
    """Never silently render old bundled UI when a previous desktop is still open."""
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        for name in ('app.js','style.css'):
            with opener.open(f'http://127.0.0.1:{port}/{name}',timeout=3) as response:
                expected=(ROOT_DIR / 'hub/static' / name).read_bytes()
                if hashlib.sha256(response.read()).digest()!=hashlib.sha256(expected).digest():return False
        return True
    except OSError:
        return False


def main(argv=None):
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if '--browser-probe' in raw_args:
        from hub.browser_render import executable,launch_browser,failure_detail
        import tempfile
        result_path=Path(raw_args[raw_args.index('--result-file')+1])
        with tempfile.TemporaryDirectory(prefix='hub-render-probe-') as temp:
            folder=Path(temp);page=folder/'probe.html';page.write_text('<h1>Browser probe</h1>')
            output=folder/'probe.png'
            result=launch_browser([executable(),'--headless','--disable-gpu','--no-first-run','--user-data-dir='+str(folder/'profile'),'--virtual-time-budget=1500','--screenshot='+str(output),page.as_uri()])
            result_path.write_text(json.dumps({'ok':result.returncode==0 and output.exists(),'detail':failure_detail(result,output)}))
        return 0
    if any(arg == '--mcp-server' or arg.endswith('mcp.py') for arg in raw_args):
        from hub.mcp import main as mcp_main
        mcp_main()
        return 0

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', type=int, default=8766)
    p.add_argument('--data', type=Path, default=None, help='Hub data directory; default: %(default)s (desktop local application data)')
    p.add_argument('--start-hub', action='store_true', help='Compatibility option; starting is the default')
    p.add_argument('--connect-only', action='store_true', help='Require an authenticated existing instance')
    modes = p.add_mutually_exclusive_group()
    modes.add_argument('--sim', action='store_true', help='Explicitly enable simulated consumers (default: production)')
    modes.add_argument('--no-sim', action='store_true', help='Compatibility option: production is already the default')
    p.add_argument('--probe-only', action='store_true')
    p.add_argument('--dry-run', action='store_true', help='Probe prerequisites without starting any service')
    p.add_argument('--module-smoke-test',action='store_true',help='Check installed and user modules in a temporary directory; no model calls')
    p.add_argument('--smoke-test', action='store_true', help='Start/check owned Hub then cleanly close it; no window')
    p.add_argument('--cli-smoke-test',action='store_true',help='With smoke test, check installed CodeBuddy startup using --version only')
    p.add_argument('--browser-smoke-test',action='store_true',help='With --smoke-test, verify an isolated real DevTools PNG; no model calls')
    p.add_argument('--engine', choices=['auto', 'native', 'edge', 'chrome', 'pywebview'], default='auto')
    p.add_argument('--fast-start-smoke-test',action='store_true',help='With window smoke, exercise asynchronous shell without starting optional host apps')
    p.add_argument('--window-smoke-test', action='store_true', help='Open and verify a real native window, then close it')
    p.add_argument('--notification-smoke-test', action='store_true', help='With macOS window smoke, submit one test notification without requesting permissions')
    p.add_argument('--result-file', type=Path, help='Write non-secret diagnostics for GUI executable smoke tests')
    p.add_argument('--sync-context', action='store_true', help='Sync project context into desktop database')
    p.add_argument('--setup', action='store_true', help='Open the in-app Harness configuration guide')
    args = p.parse_args(argv)
    if args.notification_smoke_test and (sys.platform!='darwin' or not args.window_smoke_test):
        p.error('--notification-smoke-test requires macOS --window-smoke-test')
    if args.module_smoke_test:
        from hub.module_diagnostics import check
        try:
            result=check()
        except Exception as error:
            result={'ok':False,'error':str(error),'inference_sent':False}
        if args.result_file:args.result_file.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
        return 0 if result['ok'] else 1
    if not 0 <= args.port <= 65535 or (args.port == 8765 and not args.connect_only):
        p.error('Port 8765 requires --connect-only; starting a Hub uses 8766 or 0')
    env = detect_environment()
    if args.probe_only or args.dry_run:
        print(json.dumps(env, indent=2))
        return 0
    temp_smoke_dir = None
    if args.data is None:
        if (args.smoke_test or args.window_smoke_test) and not args.connect_only and not args.sync_context:
            import tempfile
            temp_smoke_dir = tempfile.TemporaryDirectory(prefix='amh_smoke_')
            args.data = Path(temp_smoke_dir.name)
            args.port = 0
        else:
            args.data = DEFAULT_DATA
            if args.connect_only:
                # Read-only discovery: attach only after this directory's credential
                # successfully authenticates to the specifically requested port.
                roots = [Path.cwd(), Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent]
                candidates = [DEFAULT_DATA]
                for root in roots:
                    candidates.extend(parent / 'data' for parent in (root, *root.parents))
                for candidate in dict.fromkeys(candidates):
                    if check_health(args.port, get_user_token(candidate)):
                        args.data = candidate
                        break
    elif (args.smoke_test or args.window_smoke_test) and args.data.resolve() == DEFAULT_DATA.resolve():
        import tempfile
        temp_smoke_dir = tempfile.TemporaryDirectory(prefix='amh_smoke_')
        args.data = Path(temp_smoke_dir.name)
        args.port = 0
    if (args.smoke_test or args.window_smoke_test) and args.port == 8766:
        args.port = 0
    args.data = args.data.resolve()
    if not args.connect_only and not args.smoke_test and not args.window_smoke_test and args.sync_context:
        ensure_context_seeded(args.data, force_sync=args.sync_context)
    owned = None
    try:
        token = get_user_token(args.data)
        if args.port and check_health(args.port, token):
            port = args.port
            if not args.connect_only:
                request = urllib.request.Request(f'http://127.0.0.1:{port}/health',headers={'Authorization':'Bearer '+token})
                with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=2) as response:
                    current_health=json.load(response)
                    current_mode = current_health.get('simulation')
                if current_mode is not args.sim:
                    raise RuntimeError('The existing Hub has a different run mode. Close the previous desktop instance, or explicitly use --connect-only to retain its mode. No service was restarted.')
                if sys.platform=='darwin' and current_health.get('desktop_build')!=MAC_DESKTOP_BUILD:
                    raise RuntimeError('旧版 Deskfellows 仍在运行。请先保存草稿，从旧应用菜单退出，再打开新版本。已有任务未被强制停止。 / Quit the previous app after saving drafts, then reopen this version.')
                if args.engine in ('auto','native') and not args.window_smoke_test and restore_existing_window(port):
                    if args.result_file:args.result_file.write_text(json.dumps({'ok':True,'existing_window_restored':True}),encoding='utf8')
                    return 0
                if not existing_ui_matches(port):
                    raise RuntimeError('后台服务版本不同且未找到可恢复窗口；请显式使用 --connect-only 保留该服务。未停止现有任务。')
        elif args.connect_only:
            raise RuntimeError('No authenticated Hub matching --data and --port')
        else:
            # Binding failure is fatal: never attach to an unidentified occupied port.
            owned = FastHub(args.data,args.port,simulate=args.sim,startup_extras=False) if args.fast_start_smoke_test else (OwnedHub if args.smoke_test or args.window_smoke_test else FastHub)(args.data, args.port, simulate=args.sim)
            port = owned.port
            token = get_user_token(args.data)
        if not isinstance(owned,FastHub) and not check_health(port, token):
            raise RuntimeError('Authenticated Hub health check failed')
        url = f'http://127.0.0.1:{port}/'
        print('Hub ready: ' + url)
        print('Data directory: ' + str(args.data))
        if owned:
            print('Login: automatic same-origin desktop session; no token in URL or browser storage.')
        else:
            print('Login: existing service kept unchanged. Paste the user value OR full JSON from ' + str(args.data / 'credentials.json'))
        if args.smoke_test:
            count = check_static_assets(port)
            if owned:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                req = urllib.request.Request(url + 'desktop-session', data=b'{}', headers={
                    'Origin':url.rstrip('/'), 'Sec-Fetch-Site':'same-origin',
                    'X-Desktop-Session':owned.server.desktop_session, 'Content-Type':'application/json'})
                with opener.open(req, timeout=3) as response:
                    if json.load(response).get('token') != token:
                        raise RuntimeError('Desktop session credential mismatch')
                print('Desktop session: same-origin credential exchange PASS; credentials never printed')
            print(f'SMOKE PASS: authenticated health; assets={count}; strict CSP')
            diagnostics={'ok':True,'assets':count,'simulation':args.sim,'native_available':bool(env['native_webview2'])}
            if args.cli_smoke_test:
                from hub.integrations import command,locate
                from hub.process_job import ProcessJob
                from hub.workbuddy_catalog import environment
                import subprocess
                from hub.cli_diagnostics import startup_probe
                diagnostics['cli_offline_startup']=startup_probe(DEFAULT_DATA)
                cli=locate('workbuddy');child=None;job=None
                try:
                    if cli:
                        child=subprocess.Popen(command([cli,'--version']),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',env=environment(),start_new_session=os.name!='nt',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                        job=ProcessJob(child);out,err=child.communicate(timeout=20)
                        diagnostics['cli_startup']={'ok':child.returncode==0,'version':out.strip()[:80],'error':err[:160]}
                    else:diagnostics['cli_startup']={'skipped':True}
                except Exception as error:diagnostics['cli_startup']={'ok':False,'error':type(error).__name__+': '+str(error)}
                finally:
                    if job:job.close()
                    if child and child.poll() is None:child.kill()
            diagnostics['vm_helper_packaged']=all((Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))/'tools'/name).is_file() for name in ('Start-HubVmBridge.ps1','HubDesktopAgent.ps1','Configure-HubVmUnattended.ps1'))
            if not diagnostics['vm_helper_packaged']:raise RuntimeError('VM helper missing from build')
            if args.browser_smoke_test:
                import tempfile
                from hub.browser_cdp import capture
                from hub.browser_render import executable,spawn_browser
                with tempfile.TemporaryDirectory(prefix='hub-browser-smoke-') as directory:
                    page=Path(directory)/'test.html';page.write_text('<!doctype html><meta charset="utf-8"><body style="background:#218b56;color:white">Hub PNG verification</body>',encoding='utf8')
                    output=Path(directory)/'proof.png';capture(executable(),page.as_uri(),output,900,600,spawn_browser)
                    png=output.read_bytes()
                    if not png.startswith(bytes([137,80,78,71,13,10,26,10])):raise RuntimeError('Real browser PNG verification failed')
                    diagnostics['browser_png']={'width':int.from_bytes(png[16:20],'big'),'height':int.from_bytes(png[20:24],'big'),'bytes':len(png)}
                    # Exercise the actual HTTP -> Automation -> render -> artifact
                    # path as well, not just the underlying browser primitive.
                    if owned is None or temp_smoke_dir is None:raise RuntimeError('Full browser smoke requires an isolated owned service')
                    from hub.core import HubError
                    original_context=owned.server.workflows.run_context
                    def smoke_context(actor,run_id,*unused,**options):
                        if actor!='user' or run_id!='browser-smoke':raise HubError('Not the isolated browser smoke execution')
                        return {'id':'browser-smoke','project_id':'browser-smoke'},{'cwd':directory}
                    owned.server.workflows.run_context=smoke_context
                    try:
                        request=urllib.request.Request(url+'api/action',data=json.dumps({'action':'browser_render','args':{'run_id':'browser-smoke','path':str(page),'width':900,'height':600}}).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','Origin':url.rstrip('/')})
                        try:
                            with opener.open(request,timeout=45) as response:rendered=json.load(response)['result']
                        except urllib.error.HTTPError as error:raise RuntimeError('Full browser_render HTTP smoke: '+str(json.load(error))) from None
                        if rendered.get('width')!=900 or rendered.get('height')!=600 or not rendered.get('image_data'):raise RuntimeError('browser_render did not return a real PNG')
                        diagnostics['browser_render_http']={'ok':True,'width':rendered['width'],'height':rendered['height'],'artifact_saved':True}
                    finally:owned.server.workflows.run_context=original_context
            if args.result_file:args.result_file.write_text(json.dumps(diagnostics),encoding='utf-8')
            return 0
        engine = args.engine
        if engine == 'auto':
            engine = next((key for key, found in [('native', env['native_wkwebview'] or env['native_webview2']), ('pywebview', env['pywebview'])] if found), None)
        if engine == 'native':
            if sys.platform == 'darwin':
                from desktop.macos_webview import run_native
            else:
                from desktop.native_webview import run_native
            extra={'notification_probe':args.notification_smoke_test,'browser_probe':args.browser_smoke_test} if sys.platform=='darwin' else {}
            result = run_native(url+('#setup' if args.setup else ''), args.data.parent / ('native-profile-' + str(port)), smoke=args.window_smoke_test,data_directory=args.data,**extra)
            if args.result_file: args.result_file.write_text(json.dumps({'ok':True,**result}),encoding='utf-8')
        elif engine in ('edge', 'chrome'):
            executable = env['msedge' if engine == 'edge' else 'chrome']
            if not executable:
                raise RuntimeError('Requested desktop engine is unavailable')
            app = launch_app(executable, url, args.data.parent / ('profile-' + str(port)))
            try:
                app.wait()
            except KeyboardInterrupt:
                app.terminate()
                app.wait(timeout=5)
        elif engine == 'pywebview' and env['pywebview']:
            import webview
            webview.create_window('Deskfellows', url, width=1366, height=860)
            webview.start(debug=False)
        else:
            if sys.platform == 'darwin':
                raise RuntimeError('WKWebView host requires macOS 14+. Install desktop/requirements-macos.txt using Python 3.11+.')
            raise RuntimeError('Native WebView2 is unavailable. Install the Microsoft WebView2 Runtime or pywebview; no browser is launched automatically.')
        return 0
    except (OSError, RuntimeError) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        if args.result_file: args.result_file.write_text(json.dumps({'ok':False,'error':str(error)}),encoding='utf-8')
        elif getattr(sys,'frozen',False) and sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,str(error),'Deskfellows · 无法启动',0x10)
        elif getattr(sys,'frozen',False) and sys.platform=='darwin':
            import AppKit as A
            app=A.NSApplication.sharedApplication();app.setActivationPolicy_(A.NSApplicationActivationPolicyRegular)
            app.activateIgnoringOtherApps_(True)
            alert=A.NSAlert.alloc().init();alert.setMessageText_('Deskfellows · 无法启动 / Unable to start')
            alert.setInformativeText_(str(error));alert.runModal()
        return 1
    finally:
        if owned:
            owned.close()
        if temp_smoke_dir is not None:
            try:
                temp_smoke_dir.cleanup()
            except Exception:
                pass


if __name__ == '__main__':
    if getattr(sys, 'frozen', False):
        if sys.stdout is None: sys.stdout = open(os.devnull, 'w')
        if sys.stderr is None: sys.stderr = open(os.devnull, 'w')
    sys.exit(main())
