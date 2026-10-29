"""Build all platform icons from the approved Deskfellows artwork."""
import base64
from pathlib import Path
from PIL import Image


def build():
    root = Path(__file__).resolve().parents[1]
    source = root / 'hub/static/deskfellows-icon.png'
    with Image.open(source) as original:
        image = original.convert('RGBA')
        image.save(root / 'desktop/app.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
        image.save(root / 'desktop/app.icns', sizes=[(16,16),(32,32),(64,64),(128,128),(256,256),(512,512),(1024,1024)])
    # Preserve the public asset URL used by cached UI and integrations.
    encoded = base64.b64encode(source.read_bytes()).decode('ascii')
    (root / 'hub/static/hub-mark.svg').write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">'
        '<image width="1024" height="1024" href="data:image/png;base64,' + encoded + '"/></svg>', encoding='utf8')


if __name__ == '__main__':
    build()
