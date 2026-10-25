"""Optional non-inference account probes owned by Harness modules."""
import os,re,subprocess,sys,shlex,uuid
from hub.cli_paths import search_path
from hub.integrations import locate,command

def status(registry,connection,kind,spec):
    c=connection
    key_env = c.get('key_env') or spec.get('key_env')
    if key_env:
        present = bool(os.environ.get(key_env))
        if kind == 'deepseek-harness': present |= (registry.hub.directory / 'deepseek-key.dpapi').exists()
        return {'state': 'ready' if present else 'login', 'message': '已找到凭据；下一步读取模型目录。' if present else '请在官方界面登录，并按接入要求设置 '+key_env+' 环境变量。'}
    if kind == 'codex':
        from hub.codex_runtime import AppServer
        client = AppServer(c['cwd'], executable_path=locate(kind, c.get('executable','')))
        try:
            account = client.rpc('account/read', {'refreshToken':False}).get('account')
            return {'state':'ready' if account else 'login','message':'账号已登录。' if account else '请在 Codex 官方界面完成登录。'}
        finally: client.close()
    if kind == 'antigravity':
        from hub.antigravity import AntigravityProbe
        try:
            result=AntigravityProbe(locate(kind,c.get('executable',''))).run()
            return {'state':'ready' if result.get('windows') else 'unknown','message':'已读取官方账号额度与模型目录。' if result.get('windows') else '模型目录可读，但未取得独立登录证据。可在官方界面确认登录后勾选确认。'}
        except Exception:
            return {'state':'unknown','message':'官方只读检查暂未成功。请检查网络；如已在官方界面登录，可勾选确认后读取模型。'}
    if kind == 'workbuddy':
        return {'state':'unknown','message':'CodeBuddy 没有已验证的独立账号检查接口。请确认已在官方 CLI 登录，勾选确认后读取模型目录；检查不会打开 CLI。'}
    if kind == 'opencode':
        result = subprocess.run(command([locate('opencode', c.get('executable','')), 'auth', 'list']), stdin=subprocess.DEVNULL, capture_output=True, timeout=30, encoding='utf-8', errors='replace', creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        import re
        output=re.sub(r'\x1b\[[0-9;]*m','',result.stdout+result.stderr)
        counts=re.findall(r'(\d+)\s+credentials?',output,re.I)
        # Public CLI versions show both stored credentials and environment keys.
        counts+=re.findall(r'(\d+)\s+environment\s+variables?',output,re.I)
        ready=result.returncode==0 and any(int(x)>0 for x in counts)
        return {'state':'ready' if ready else 'login','message':'发现已连接的提供商。' if ready else '请在 OpenCode 中连接订阅或 API 提供商。'}
    return {'state':'unknown','message':'此 Harness 没有独立登录检测接口。请在官方界面确认登录，再继续读取模型目录。'}


def login(registry,connection,kind,spec):
    from pathlib import Path
    from urllib.parse import urlsplit
    import webbrowser
    from hub.core import HubError
    url=spec.get('login_url')
    if url:
        parsed=urlsplit(url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:raise HubError('适配器需要提供有效的 HTTPS 官网链接')
        webbrowser.open(url);return
    supplied=connection.get('executable','')
    if connection.get('adapter') and Path(supplied).suffix=='.py':supplied=''
    exe=locate(kind,supplied)
    if not exe:raise HubError('请先安装 Harness，再重新检测')
    if sys.platform=='darwin' and kind=='deepseek-harness':
        from hub.deepseek_harness import installation
        app=installation({'harness_install':exe})[0].parents[2]
        subprocess.run(['/usr/bin/open','-a',str(app)],check=True,timeout=15)
        return
    args=spec.get('login_args',[])
    if not isinstance(args,list) or not all(isinstance(x,str) for x in args):raise HubError('登录参数格式错误')
    if sys.platform=='darwin' and spec.get('terminal'):
        # A user-triggered login opens an inspectable script in Terminal; no
        # AppleScript, shell profile execution, or interpolated shell arguments.
        folder=registry.hub.directory/'login';folder.mkdir(parents=True,exist_ok=True)
        script=folder/('login-'+uuid.uuid4().hex+'.command')
        lines=['#!/bin/sh','export PATH='+shlex.quote(search_path()),
               'cd '+shlex.quote(connection['cwd'])+' || exit 1',
               shlex.join(command([exe,*args])), 'result=$?',
               'printf "\\nLogin process exited: %s\\n" "$result"',
               'rm -- '+shlex.quote(str(script.resolve())), 'exit "$result"']
        script.write_text('\n'.join(lines)+'\n',encoding='utf-8');script.chmod(0o700)
        subprocess.run(['/usr/bin/open','-a','Terminal',str(script.resolve())],check=True,timeout=15)
        return
    subprocess.Popen(command([exe,*args]),cwd=connection['cwd'],creationflags=getattr(subprocess,'CREATE_NEW_CONSOLE',0) if spec.get('terminal') else 0)
