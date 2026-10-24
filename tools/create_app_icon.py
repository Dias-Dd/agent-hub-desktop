"""Generate the local vector identity and multiresolution Windows icon."""
from pathlib import Path
from PIL import Image,ImageDraw
root=Path(__file__).resolve().parents[1]
svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="#171d22"/><g fill="none" stroke="#bce6df" stroke-width="1.65" stroke-linejoin="round"><rect x="6.5" y="7" width="8" height="18" rx="2.4"/><rect x="18.5" y="7" width="7" height="7" rx="2"/><rect x="18.5" y="18" width="7" height="7" rx="2"/><path d="M14.5 10.5h4m-4 11h4"/></g></svg>'
(root/'hub/static/hub-mark.svg').write_text(svg,encoding='utf8')
scale=16;im=Image.new('RGBA',(512,512));d=ImageDraw.Draw(im)
def rect(box,r,fill=None,outline=None,width=1):d.rounded_rectangle(tuple(round(x*scale) for x in box),radius=r*scale,fill=fill,outline=outline,width=round(width*scale))
rect((0,0,32,32),8,'#171d22')
color='#bce6df'
for box,r in [((6.5,7,14.5,25),2.4),((18.5,7,25.5,14),2),((18.5,18,25.5,25),2)]:rect(box,r,outline=color,width=1.65)
for y in (10.5,21.5):d.line((14.5*scale,y*scale,18.5*scale,y*scale),fill=color,width=round(1.65*scale))
im.save(root/'desktop/app.ico',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
