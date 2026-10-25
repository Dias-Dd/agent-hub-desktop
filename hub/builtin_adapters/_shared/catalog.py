import json,os,re,subprocess,time,urllib.request
from hub.core import HubError
from hub.integrations import locate,command,KINDS,BASES,AppServer
def probe(self,connection):
 from hub.integrations import locate,command,KINDS,BASES,AppServer
 c=dict(connection);kind=c['kind'];exe=locate(kind,c.get('executable',''));models=[];detail=''
 if kind=='codex':
  client=AppServer(c.get('cwd') or self.server.deepseek.config()['cwd'],executable_path=exe)
  try:
   cursor=None
   while True:
    result=client.rpc('model/list',{'limit':100,**({'cursor':cursor} if cursor else {})})
    for m in result.get('data',[]):models.append({'id':m.get('model',m.get('id')),'efforts':[x.get('reasoningEffort') for x in m.get('supportedReasoningEfforts',[]) if x.get('reasoningEffort')] or KINDS[kind][1]})
    cursor=result.get('nextCursor')
    if not cursor:break
   try:
    limits=client.rpc('account/rateLimits/read',{});windows=[]
    for bucket_id,bucket in (limits.get('rateLimitsByLimitId') or {'default':limits.get('rateLimits') or {}}).items():
     for name in ('primary','secondary'):
      window=bucket.get(name)
      if window and isinstance(window.get('usedPercent'),(int,float)):windows.append({'group':bucket_id,'name':name,'remaining':max(0,100-window['usedPercent']),'resets_at':window.get('resetsAt'),'source':'official_app_server'})
    c['official_windows']=windows
   except HubError:c['quota_error']='额度刷新失败，保留上次读数'
  finally:client.close()
 elif kind=='antigravity':
  from hub.antigravity import AntigravityProbe,model_efforts
  probe=AntigravityProbe(exe).run();models=[{'id':m['model'],'efforts':model_efforts(m['model'])} for m in probe.get('models',[])];c['official_windows']=probe.get('windows',[]);detail='官方 CLI 模型与账号共享额度'
 elif kind in BASES:
  from hub.integration_runtime import CompatibleAPI
  result=CompatibleAPI(c).request('/models');models=[{'id':m['id'],'efforts':['default']} for m in result.get('data',[]) if isinstance(m.get('id'),str)]
 elif kind=='deepseek-harness':
  if not exe:raise HubError('未安装 DeepSeek Harness')
  from hub.deepseek_harness import probe_catalog
  models=probe_catalog(self.server.deepseek,config=c);detail='已读取本机 Harness 官方模型与档位目录，未发送推理请求。'
 else:
  if not exe:raise HubError('未找到 '+KINDS[kind][0]+'；请先安装并登录')
  args=[exe,'models'] if kind=='opencode' else [exe,'--help']
  result=subprocess.run(command(args),stdin=subprocess.DEVNULL,capture_output=True,encoding='utf-8',errors='replace',timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  if result.returncode:raise HubError('官方命令探测未成功；未启动模型')
  if kind=='opencode':models=[{'id':x.strip(),'efforts':KINDS[kind][1]} for x in result.stdout.splitlines() if re.fullmatch(r'[^\s]+/[^\s]+',x.strip())]
  if kind=='workbuddy':
   from hub.workbuddy_catalog import catalog,product_models,configured_models
   models,detail=catalog(exe,c.get('cwd'),result.stdout,standalone=True)
   c['catalog_complete']=False
   c['candidate_models']=[]
   by_id={m['id']:m for m in models}
   for item in configured_models(folders=('.codebuddy',)):by_id.setdefault(item['id'],item)
   models=list(by_id.values())
   c['catalog_status']='partial' if models else 'unavailable'
   if not models:
    models=[{**m,'stale':True} for m in c.get('models',[]) if m.get('source') in ('official_acp_catalog','official_user_config')]
    if models:detail+='；保留上次目录（数据已过期）'
  if kind=='ori':
   import urllib.request
   from hub.proxy_env import inherit_system_proxy
   env=inherit_system_proxy(dict(os.environ));proxy=env.get('HTTPS_PROXY') or env.get('https_proxy')
   opener=urllib.request.build_opener(urllib.request.ProxyHandler({'https':proxy} if proxy else {}))
   try:
    with opener.open('https://openrouter.ai/api/v1/models',timeout=25) as response:catalog=json.load(response)
    models=[{'id':m['id'],'name':m.get('name',m['id']),'efforts':['default'],'source':'official_public_catalog'} for m in catalog.get('data',[]) if isinstance(m.get('id'),str)]
   except (OSError,ValueError):raise HubError('无法读取 OpenRouter 模型目录，请检查连接后重试；未调用模型') from None
  if kind!='workbuddy':detail='本机命令可用；模型可手动填写，执行前由提供商核实' if not models else '本机模型目录；目录不代表账号已获推理权限'
 if kind=='opencode':
  known={m['id']:m for m in c.get('models',[]) if m.get('source')=='official_acp_config'}
  models=[known.get(m['id'],m) for m in models]
 known={m['id']:m for m in models}
 for item in c.get('client_models',[]):known.setdefault(item['id'],item)
 models=list(known.values())
 c.update(models=models,verification=('用户声明的模型与能力，未验证实际调用' if kind=='custom-harness' else '目录暂不可读；未验证实际调用' if kind=='workbuddy' and c.get('catalog_status')=='unavailable' else '目录/命令已验证，未发送推理请求'),probe_detail=detail,probed_at=time.time())
 return c
