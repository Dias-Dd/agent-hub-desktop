"""Use the installed Harness account service; never copy or export its token."""
import json,os,tempfile,time
from pathlib import Path
from hub.core import HubError

INSPECT = r'''
const fs=require('node:fs');
exports.name='hub-account-read';exports.inject=['deepseekAccount','credentials'];
exports.apply=async(ctx,config)=>{
 try{
 const state=await ctx.deepseekAccount.getState();
 const api=await ctx.credentials.describe('DEEPSEEK_API_KEY');
 const result={status:state.status,api_key_configured:!!api.configured};
 if(config.balance&&api.configured&&state.status!=='credential-stored'){
  const key=await ctx.credentials.resolve('DEEPSEEK_API_KEY');
  const response=await fetch('https://api.deepseek.com/user/balance',{headers:{Authorization:'Bearer '+key.value},redirect:'error',signal:AbortSignal.timeout(15000)});
  if(!response.ok)throw new Error('API balance HTTP '+response.status);
  const body=await response.json();
  result.api_balance=(body.balance_infos||[]).map(x=>({currency:x.currency,amount:x.total_balance}));
 }else if(config.balance&&state.status==='credential-stored'){
  const value=await ctx.deepseekAccount.getBalance({version:'0.1.0',locale:'zh-CN',timezoneOffsetSeconds:-new Date().getTimezoneOffset()*60});
  result.balance=value?{status:value.status,value:value.value,bonusWallets:value.bonusWallets}:null;
 }
 fs.writeFileSync(config.output,JSON.stringify(result),{encoding:'utf8',mode:0o600});
 }catch(e){fs.writeFileSync(config.output,JSON.stringify({error:'Harness 账号或额度读取失败，请检查凭据和网络后刷新'}));}
};
'''

def credential_store(config=None):
    config=config or {}
    return Path(config.get('account_credential_store') or Path(os.environ.get('DSH_HOME',str(Path.home()/'.dsh')))/'.credentials.yaml').resolve()

def account_rows(path):
    return [{'id':'credentials','config':{'path':str(path)}},{'id':'deepseek-account','disabled':False},{'id':'llm-deepseek-account','disabled':False}]

def inspect(runtime,balance=False,config=None):
    from .runtime import installation,patch_text,ACP
    from hub.proxy_env import inherit_system_proxy
    cfg=config or runtime.config();store=credential_store(cfg)
    if not store.is_file():return {'status':'signed-out','api_key_configured':bool(os.environ.get('DEEPSEEK_API_KEY'))}
    exe,cli=installation(cfg)
    with tempfile.TemporaryDirectory(prefix='hub-dsh-account-') as folder:
        root=Path(folder);plugin=root/'account.cjs';plugin.write_text(INSPECT,encoding='utf-8');output=root/'account.json'
        rows=account_rows(store)+[{'insert':[{'id':'hub-account-read','name':str(plugin),'config':{'balance':bool(balance),'output':str(output)}}]}]
        patch=root/'account.patch.yml'
        patch.write_text(patch_text('account','账号状态',provider='deepseek-account',credentials_path=store)+'\n'+'\n'.join('- '+json.dumps(x) for x in rows),encoding='utf-8')
        env=inherit_system_proxy(dict(os.environ));env.update(ELECTRON_RUN_AS_NODE='1',DSH_HOME=str(root))
        env.pop('DEEPSEEK_API_KEY',None)
        client=ACP([str(exe),'--expose-internals',str(cli),'--profile','acp','--patch',str(patch)],str(root),env)
        try:
            client.request('initialize',{'protocolVersion':1,'clientCapabilities':{},'clientInfo':{'name':'agent-message-hub','version':'0.1'}},timeout=45)
            deadline=time.monotonic()+35
            while not output.exists() and time.monotonic()<deadline:time.sleep(.05)
            if not output.exists():raise HubError('Harness 未提供账号读取结果，请更新官方 Harness 后重试')
            result=json.loads(output.read_text(encoding='utf-8'))
            if result.get('error'):raise HubError(result['error'])
            if result.get('status') not in ('signed-out','credential-stored'):raise HubError('Harness 账号状态无效')
            return result
        finally:client.close()

def auth(runtime,config=None):
    config=config or runtime.config()
    state=inspect(runtime,config=config)
    # Preserve the account route used by existing sessions when both exist.
    if state.get('status')=='credential-stored':
        return 'deepseek-account',credential_store(config),{}
    if state.get('api_key_configured'):
        return ('deepseek-official',credential_store(config),{}) if credential_store(config).is_file() else ('deepseek-official',None,{'DEEPSEEK_API_KEY':os.environ['DEEPSEEK_API_KEY']})
    try:key=runtime.key()
    except HubError:raise HubError('请在 DeepSeek Harness 中登录账号或配置 API 凭据后重试') from None
    return 'deepseek-official',None,{'DEEPSEEK_API_KEY':key}


def quota(registry,connection):
    result=inspect(registry.server.deepseek,True,connection)
    if 'api_balance' in result:
        values=[{'name':'API可用余额','amount':str(x['amount']),'currency':x['currency']} for x in result['api_balance'] if x.get('currency') in ('CNY','USD') and x.get('amount') is not None]
        return {**connection,'official_balance':values,'balance_source':'deepseek-api','quota_observed_at':time.time(),'quota_error':None}
    if result['status']!='credential-stored':
        try: registry.server.deepseek.key()
        except HubError: raise HubError('请先在 DeepSeek Harness 中登录，再读取账号余额') from None
        from hub.builtin_adapters._shared.quota import quota as api_quota
        return {**api_quota(registry,{**connection,'legacy':True}),'balance_source':'deepseek-api'}
    balance=result.get('balance')
    if not isinstance(balance,dict) or balance.get('status')!='ready':raise HubError('Harness 账号余额暂不可读，保留上次结果')
    values=[]
    for key,label in [('value','账号充值余额'),('bonusWallets','账号赠送余额')]:
        for wallet in balance.get(key) or []:
            if wallet.get('currency') in ('CNY','USD') and isinstance(wallet.get('balance'),str):values.append({'name':label,'amount':wallet['balance'],'currency':wallet['currency']})
    return {**connection,'official_balance':values,'balance_source':'dsh-account','quota_observed_at':time.time(),'quota_error':None}
