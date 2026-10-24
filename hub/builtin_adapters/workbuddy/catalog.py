"""Public ACP catalog first, packaged product catalog second; never prompt a model."""
import json,re,os
from pathlib import Path
from hub.core import HubError

def acp_models(view):
 result={}
 for item in view.get('models',{}).get('availableModels',[]):
  ident=item.get('modelId') or item.get('id')
  if isinstance(ident,str) and ident and not item.get('disabled'):
   result[ident]={'id':ident,'name':item.get('name') or ident,'efforts':['default'],'source':'official_acp_catalog','availability':'catalog_only','pricing':'unknown'}
 def visit(options):
  for option in options:
   if isinstance(option.get('value'),str):
    ident=option['value'];result.setdefault(ident,{'id':ident,'name':option.get('name') or option.get('label') or ident,'efforts':['default'],'source':'official_acp_catalog','availability':'catalog_only','pricing':'unknown'})
   elif isinstance(option.get('options'),list):visit(option['options'])
 for config in view.get('configOptions',[]):
  if config.get('id')=='model' or config.get('category')=='model':visit(config.get('options',[]))
 return list(result.values())

def product_models(executable):
 exe=Path(executable)
 for file in [exe.parent/'product.json',exe.parent.parent/'product.json']:
  if not file.is_file():continue
  try:data=json.loads(file.read_text(encoding='utf8'))
  except (OSError,ValueError):continue
  result=[]
  for model in data.get('models',[]):
   if not isinstance(model,dict) or not isinstance(model.get('id'),str) or model.get('disabled'):continue
   if set(model.get('tags',[]))&{'text-to-image','image-to-image','embedding'}:continue
   if model['id'] in ('default','lite','builtin-lite'):continue
   result.append({'id':model['id'],'name':model.get('name') or model['id'],'efforts':['default'],'source':'official_installed_catalog','availability':'unverified','pricing':'unknown'})
  if result:return result
 return []

def environment(base=None):
 # WorkBuddy's own network layer owns its proxy configuration. Do not synthesize
 # HTTP(S)_PROXY from Windows settings: its bundled Axios proxy path is broken.
 # Preserve any explicitly configured parent environment unchanged.
 return dict(os.environ if base is None else base)

def acp_arguments(executable):
 return [executable,'--serve','--acp','--acp-transport','stdio','--host','127.0.0.1','--port','0']

def catalog(executable,cwd,help_text='',standalone=False):
 from hub.deepseek_harness import ACP
 from hub.integrations import command
 client=None
 try:
  client=ACP(command([executable,'--acp'] if standalone else acp_arguments(executable)),str(Path(cwd or '.').resolve()),environment())
  client.request('initialize',{'protocolVersion':1,'clientCapabilities':{},'clientInfo':{'name':'agent-message-hub-catalog','version':'0.3'}},timeout=8)
  view=client.request('session/new',{'cwd':str(Path(cwd or '.').resolve()),'mcpServers':[]},timeout=8)
  models=acp_models(view)
  if models:
   return models,('CodeBuddy 独立 CLI 的 ACP 目录已刷新；未发送推理请求，账号权限及免费资格尚未验证' if standalone else 'ACP 目录已刷新；此 CLI 返回的菜单可能少于客户端，不能据此确认账号权限或免费资格')
 except Exception:pass
 finally:
  if client:client.close()
 models=[] if standalone else product_models(executable)
 if models:return [],'ACP 目录暂不可读；安装包候选项已单独保存，未验证账号可用性'
 found=re.search(r'--model\s+<model>.*?supported:\s*\(([^)]+)\)',help_text,re.S|re.I)
 if found:return [{'id':x.strip(),'efforts':['default'],'source':'official_cli_help'} for x in found.group(1).split(',') if x.strip()],'动态及安装目录不可读，暂用 CLI 帮助目录；账号可用性未知'
 raise HubError('WorkBuddy 暂未返回模型目录；未发送推理请求，请检查官方客户端登录与安装情况')


def configured_models(home=None,folders=('.workbuddy','.codebuddy')):
 """Read only model metadata from documented user configuration; never expose keys."""
 home=Path(home) if home else Path.home()
 result={}
 for folder in folders:
  try:data=json.loads((home/folder/'models.json').read_text(encoding='utf8'))
  except (OSError,ValueError):continue
  rows=data if isinstance(data,list) else data.get('models',[]) if isinstance(data,dict) else []
  if not isinstance(rows,list):continue
  for item in rows:
   if not isinstance(item,dict) or item.get('disabled'):continue
   ident=item.get('id') or item.get('model')
   if not isinstance(ident,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}',ident):continue
   result[ident]={'id':ident,'name':item.get('name') if isinstance(item.get('name'),str) else ident,'efforts':['default'],'source':'official_user_config','availability':'configured_not_verified','pricing':'unknown'}
 return list(result.values())
