"""One request inside a persistent print-mode CLI session, without replay leakage."""
import json,time,datetime,hashlib

class PrintTurn:
 def __init__(self,prompt,request_id,started):
  self.prompt=prompt;self.request_id=request_id;self.started=started;self.accepted=False;self.seen=set();self.replayed=0
 def payload(self):
  return json.dumps({'type':'user','uuid':self.request_id,'message':{'role':'user','content':self.prompt}},ensure_ascii=False)+'\n'
 def receive(self,value):
  if value.get('type')=='user':
   message=value.get('message') or {};content=message.get('content','')
   if isinstance(content,list):content=''.join(b.get('text','') for b in content if isinstance(b,dict))
   if value.get('uuid')==self.request_id or content==self.prompt:self.accepted=True
   return None
  if value.get('type')!='assistant':return None
  stamp=value.get('__timestamp') or value.get('timestamp')
  try:
   when=datetime.datetime.fromisoformat(stamp.replace('Z','+00:00')).timestamp() if isinstance(stamp,str) else float(stamp) if stamp is not None else None
   if when and when>1e12:when/=1000
  except (ValueError,TypeError):when=None
  if value.get('isReplay') or when is not None and when<self.started-1 or not self.accepted:
   self.replayed+=1;return None
  identity=value.get('uuid') or (value.get('message') or {}).get('id')
  if identity and identity in self.seen:return None
  if identity:self.seen.add(identity)
  message=value.get('message') or {};blocks=message.get('content') or []
  return '\n'.join(str(b.get('text') or '') for b in blocks if isinstance(b,dict) and b.get('type')=='text')

def completed_result(final,reported=None):
 text=final.get('result','')
 if isinstance(text,str) and text.strip():return 'completed',text
 if reported:
  try:
   report=json.loads(reported)
   if isinstance(report,dict) and str(report.get('summary','')).strip():return 'completed',reported
  except (ValueError,TypeError):pass
 return 'failed','CLI 已确认本轮结束，但未返回本轮文字结果或有效 report_result；没有验收结论，不认定任务成功。原会话保留，不自动重试。'
