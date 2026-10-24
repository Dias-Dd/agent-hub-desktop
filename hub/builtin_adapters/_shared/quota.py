import time
from hub.core import HubError
def quota(self,c):
 c=dict(c);kind=c['kind']
 if kind in ('codex','antigravity'):
  from importlib import import_module
  return import_module('hub.builtin_adapters._shared.catalog').probe(self,c)
 from hub.integration_runtime import CompatibleAPI
 from decimal import Decimal
 balances=[]
 try:
  if kind=='deepseek-api' or c.get('legacy'):
   result=self.server.deepseek.api.request('/user/balance') if c.get('legacy') else CompatibleAPI(c).request('/user/balance')
   balances=[{'name':'API可用余额','amount':str(x['total_balance']),'currency':x['currency']} for x in result.get('balance_infos',[]) if x.get('currency') in ('CNY','USD') and x.get('total_balance') is not None]
  elif kind=='openrouter-api':
   api=CompatibleAPI(c);key=api.request('/key').get('data',{})
   if key.get('limit_remaining') is not None:balances.append({'name':'当前密钥剩余预算','amount':str(key['limit_remaining']),'currency':'USD'})
   if key.get('is_management_key') or key.get('is_provisioning_key'):
    credits=api.request('/credits').get('data',{})
    if credits.get('total_credits') is not None and credits.get('total_usage') is not None:balances.append({'name':'账户可用余额','amount':str(Decimal(str(credits['total_credits']))-Decimal(str(credits['total_usage']))),'currency':'USD'})
  else:raise HubError('此接入没有已验证的公开额度读取接口')
  c['official_balance']=balances;c['quota_observed_at']=time.time();c.pop('quota_error',None)
  return c
 except HubError:
  # A failed refresh must not erase the last observation.
  raise
