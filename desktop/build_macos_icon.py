"""Convert the existing Windows brand icon into Apple's multi-size ICNS."""
from pathlib import Path
import subprocess
import tempfile


def build():
    root=Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix='hub-icon-') as directory:
        folder=Path(directory)/'AgentHub.iconset';folder.mkdir()
        source=Path(directory)/'source.png'
        subprocess.run(['sips','-s','format','png',str(root/'app.ico'),'--out',str(source)],check=True,capture_output=True)
        for size in (16,32,128,256,512):
            for scale in (1,2):
                output=folder/('icon_'+str(size)+'x'+str(size)+('@2x' if scale==2 else '')+'.png')
                pixels=str(size*scale)
                subprocess.run(['sips','-z',pixels,pixels,str(source),'--out',str(output)],check=True,capture_output=True)
        subprocess.run(['iconutil','-c','icns',str(folder),'-o',str(root/'app.icns')],check=True)


if __name__=='__main__':build()
