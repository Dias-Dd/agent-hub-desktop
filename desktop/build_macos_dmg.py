"""Build a local DMG with the app and an Applications shortcut; never publishes."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile


def build(app,output):
    app=app.resolve();output=output.resolve()
    if not (app/'Contents/MacOS/AgentHub').is_file():raise RuntimeError('Missing built Agent Hub.app')
    subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True)
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='agent-hub-dmg-') as directory:
        stage=Path(directory)/'volume';stage.mkdir()
        shutil.copytree(app,stage/'Agent Hub.app',symlinks=True)
        (stage/'Applications').symlink_to('/Applications',target_is_directory=True)
        (stage/'安装说明 - Read Me.txt').write_text(
            'Agent Hub · macOS arm64 开发版\n\n'
            '将 Agent Hub.app 拖入 Applications。先退出旧版，再从 Applications 启动。\n'
            '首次启动会显示配置指引；可跳过模型和 Tart，稍后在设置中配置。\n'
            '关闭主窗口保留后台运行，通过菜单栏图标恢复；显式退出会停止后台任务。\n'
            '数据保存在 ~/Library/Application Support/AgentMessageHubDesktop/data。\n'
            '此构建仅本地 ad-hoc 签名，尚未进行 Developer ID 签名和 Apple 公证。\n\n'
            'Drag Agent Hub.app into Applications. Quit the previous app before opening.\n'
            'The first launch shows the setup guide. Harness and Tart setup can be skipped.\n'
            'Close the main window to keep running in the menu bar; Quit stops background tasks.\n'
            'This local development build is ad-hoc signed and is not notarized.\n',encoding='utf8')
        temporary=output.with_name(output.stem+'.building.dmg')
        subprocess.run(['hdiutil','create','-ov','-volname','Agent Hub','-srcfolder',str(stage),
                        '-format','UDZO',str(temporary)],check=True)
        subprocess.run(['hdiutil','verify',str(temporary)],check=True)
        temporary.replace(output)
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app',type=Path,default=Path(__file__).parent/'macos-dist/Agent Hub.app')
    parser.add_argument('--output',type=Path,default=Path(__file__).parent/'macos-installer-dist/AgentHub-macOS-arm64-dev.dmg')
    args=parser.parse_args();print(build(args.app,args.output))
