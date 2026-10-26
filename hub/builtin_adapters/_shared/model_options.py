import os
from hub.core import HubError
from hub.integrations import locate,command
def probe_model(self,c,model,environment_override=None):
 c=dict(c)
 if c['kind'] not in ('opencode','ori'):raise HubError('此连接请通过模型目录选择档位')
 exe=locate(c['kind'],c.get('executable',''))
 if not exe:raise HubError('未找到 CLI')
 from hub.deepseek_harness import ACP
 from hub.proxy_env import inherit_system_proxy
 argv=[exe,'acp'] if c['kind']=='opencode' else [exe,'opencode','--model',model,'--','acp']
 selected=model if c['kind']=='opencode' or model.startswith('openrouter/') else 'openrouter/'+model
 client=ACP(command(argv),c['cwd'],environment_override if environment_override is not None else inherit_system_proxy(dict(os.environ)))
 try:
  client.request('initialize',{'protocolVersion':1,'clientCapabilities':{}},timeout=25)
  view=client.request('session/new',{'cwd':c['cwd'],'mcpServers':[]},timeout=25);session=view['sessionId']
  view=client.request('session/set_config_option',{'sessionId':session,'configId':'model','value':selected},timeout=25)
  if next((o.get('currentValue') for o in view.get('configOptions',[]) if o['id']=='model'),None)!=selected:raise HubError('CLI 未确认模型')
  effort=next((o for o in view.get('configOptions',[]) if o['id']=='effort'),{})
  values=[]
  def visit(options):
   for o in options:
    if 'value' in o:values.append(o['value'])
    else:visit(o.get('options',[]))
  visit(effort.get('options',[]));values=list(dict.fromkeys(['default']+values))
  item={'id':model,'efforts':values,'source':'official_acp_config'}
  c['models']=[m for m in c.get('models',[]) if m['id']!=model]+[item]
  return item
 finally:client.close()
