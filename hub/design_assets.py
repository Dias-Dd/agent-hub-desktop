"""Bundle project-local demo styles/images into immutable, self-contained HTML."""
import base64,html as html_module,mimetypes,re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit,unquote
from .core import HubError

ASSETS={'.png','.jpg','.jpeg','.gif','.webp','.svg','.ico','.avif','.woff','.woff2','.ttf','.otf'}


def bundle_html(source,page,root):
 root=Path(root).resolve();page=Path(page).resolve();stack=set();cache={}
 def local(reference,base,suffixes):
  url=urlsplit(reference)
  if url.scheme or url.netloc or url.path.startswith(('/',chr(92))):raise HubError('演示资源须使用项目内相对路径：'+reference)
  path=(base/unquote(url.path)).resolve()
  if not path.is_relative_to(root) or path.suffix.lower() not in suffixes:raise HubError('演示资源超出目录或类型不支持：'+reference)
  if not path.is_file():raise HubError('演示资源缺失：'+reference)
  return path
 def data_uri(reference,base):
  if reference.startswith(('data:','#')):return reference
  path=local(reference,base,ASSETS);kind=mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
  return 'data:'+kind+';base64,'+base64.b64encode(path.read_bytes()).decode()+('#'+urlsplit(reference).fragment if urlsplit(reference).fragment else '')
 def css(path):
  if path in stack:raise HubError('演示样式循环引用：'+path.name)
  if path in cache:return cache[path]
  stack.add(path)
  try:
   content=path.read_text(encoding='utf-8-sig')
   imports=re.compile(r"@import\s+(?:url\(\s*(['\"]?)(.*?)\1\s*\)|(['\"])(.*?)\3)\s*([^;]*);",re.I)
   def imported(match):
    child=css(local(match[2] if match[2] is not None else match[4],path.parent,{'.css'}));media=match[5].strip()
    return '@media '+media+'{'+child+'}' if media else child
   content=imports.sub(imported,content)
   def asset(match):return 'url("'+data_uri(match[2].strip(),path.parent)+'")'
   content=re.sub(r"url\(\s*(['\"]?)(.*?)\1\s*\)",asset,content,flags=re.I)
   cache[path]=content;return content
  finally:stack.remove(path)
 lines=source.splitlines(keepends=True);offsets=[0]
 for line in lines:offsets.append(offsets[-1]+len(line))
 edits=[]
 class Parser(HTMLParser):
  def handle_starttag(self,tag,attrs):
   values=dict(attrs);replacement=None
   if tag=='link' and 'stylesheet' in (values.get('rel') or '').lower().split() and values.get('href'):
    style=css(local(values['href'],page.parent,{'.css'}));media=values.get('media')
    replacement='<style'+(' media="'+html_module.escape(media,quote=True)+'"' if media else '')+'>'+style+'</style>'
   elif tag=='img' and values.get('src') and not values['src'].startswith('data:'):
    values['src']=data_uri(values['src'],page.parent)
    replacement='<img'+''.join(' '+k+('="'+html_module.escape(v,quote=True)+'"' if v is not None else '') for k,v in values.items())+'>'
   if replacement is not None:
    line,column=self.getpos();start=offsets[line-1]+column;edits.append((start,start+len(self.get_starttag_text()),replacement))
  handle_startendtag=handle_starttag
 parser=Parser();parser.feed(source)
 for start,end,replacement in reversed(edits):source=source[:start]+replacement+source[end:]
 return source
