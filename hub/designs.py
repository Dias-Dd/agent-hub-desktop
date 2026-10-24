from .manager_identity import independent_reviewer
from .manager_identity import resolve as project_manager
"""Versioned visual demo approval, separate from production implementation."""
import hashlib,json,time,threading,re,math
from pathlib import Path
from .core import HubError,uid,text

DESIGN_POLICY = ('当前仅制作产品演示，禁止实施真实完整产品、业务后端、真实按钮逻辑。'
 '只在演示工作目录写文件；以静态自包含HTML展示成品设计语言、全部页面/弹窗/关键状态及层级，视频用逐镜头故事板、长文档用各章版式。'
 '产品界面与演示说明层分开组织，编号、批注、讲解箭头放在可独立移除的说明层（如data-design-only），不要混入产品控件；产品本身的流程图不算说明层。1440×900等画布尺寸仅用于演示，成品须按系统DPI和窗口尺寸自适应。'
 '每页有箭头和注解，最后提供架构页说明模块、后端、数据与接口规划。经理可派工，提交前逐项核对需求覆盖。'
 '每页按单屏展示设计，长页面拆成多个画面，避免画面内部滚动导致批注位置歧义。所有HTML内嵌CSS/图片，不引用外部资源或脚本。交付manifest.json：'
 '{"title":"产品名","pages":[{"id":"home","title":"首页","parent":null,"kind":"screen","path":"home.html","note":"箭头注解及交互意图"},'
 '{"id":"architecture","title":"架构规划","parent":null,"kind":"architecture","path":"architecture.html","note":"后端规划"}]}。'
 'kind可为screen/storyboard/document/architecture，parent引用页面id。'
 '用project_complete提交时平台会检查并冻结演示，等待用户确认；演示完成不代表真实产品完成。')

class Designs:
 def __init__(self,hub,planning,workflows):
  self.hub=hub;self.planning=planning;self.workflows=workflows;self.lock=threading.RLock();hub.designs=self
  with hub.tx():hub.db.execute('CREATE TABLE IF NOT EXISTS design_reviews(id TEXT PRIMARY KEY,body TEXT)')
  self.recover_publications()
  self.repair_unapproved_assets()
 def recover_publications(self):
  with self.workflows.lock,self.lock:
   with self.hub.lock:rows=self.hub.db.execute("SELECT d.body,w.body FROM design_reviews d JOIN workflows w ON w.id=json_extract(d.body,'$.workflow_id') WHERE json_extract(w.body,'$.status')='completed'").fetchall()
   for row in rows:
    d=json.loads(row[0]);w=json.loads(row[1])
    if d['state'] not in ('building','publish_error') or any(v['version']==d['version'] for v in d.get('versions',[])):continue
    # The saved manager completion is authority to retire leftover member
    # work, including queues that survived an older build or restart.
    manager=project_manager(self.hub,record=w)
    for step in self.workflows.steps(w['id']):
     if step['agent']!=manager and (not step.get('run_id') or step['status'] in ('queued','running','interrupting','waiting_quota')):
      self.workflows._stop_task(w,step['task'],manager,'恢复已完成项目的演示发布，结束剩余任务')
    try:
     review=self.prepare_publish(w);self.save(review)
     w['design_review_ready']=True;w['publication_recovered_at']=time.time();self.workflows.save(w)
    except HubError as error:
     d.update(state='publish_error',publish_error=str(error));self.save(d)

 def repair_unapproved_assets(self,design_id=None):
  """Repair packaging only when the unapproved page originals are unchanged."""
  repaired=[]
  with self.workflows.lock,self.lock:
   with self.hub.lock:rows=self.hub.db.execute('SELECT body FROM design_reviews WHERE id=?',(design_id,)).fetchall() if design_id else self.hub.db.execute('SELECT body FROM design_reviews').fetchall()
   for row in rows:
    d=json.loads(row[0])
    if d.get('state')!='review' or d.get('approved_at') or not d.get('versions'):continue
    current=next((v for v in d['versions'] if v['version']==d['version']),None)
    if not current:continue
    root=Path(d.get('working_directory',''));frozen=Path(current['directory'])
    if not root.is_absolute() or not root.is_dir():continue
    try:
     manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8-sig'))
     sources={p['id']:(root/p['path']).resolve() for p in manifest['pages']}
     if set(sources)!={p['id'] for p in current['pages']} or manifest.get('title','产品演示')!=current['title']:continue
     from .design_assets import bundle_html
     changed=False
     for page in current['pages']:
      original=(frozen/page['path']).read_text(encoding='utf-8-sig');file=sources[page['id']]
      if not file.is_relative_to(root.resolve()) or file.read_text(encoding='utf-8-sig')!=original:break
      changed=changed or bundle_html(original,file,root)!=original
     else:
      if changed:
       updated=self.prepare_publish({'design_review':d['id'],'design_dir':str(root)})
       updated['asset_repaired_at']=time.time();self.save(updated);repaired.append(d['id'])
    except (OSError,ValueError,KeyError,HubError):continue
  return repaired

 def save(self,d):
  with self.hub.tx():
   self.hub.db.execute('INSERT OR REPLACE INTO design_reviews VALUES(?,?)',(d['id'],json.dumps(d,ensure_ascii=False)))
   if d.get('state')=='review' and d.get('versions') and not d.get('publish_error'):
    from .desktop_notifications import enqueue
    enqueue(self.hub,'demo:'+d['id']+':'+str(d.get('version',0)),'demo',d.get('project_id'))
 def get(self,ident,project_id=None):
  with self.hub.lock:row=self.hub.db.execute('SELECT body FROM design_reviews WHERE id=?',(ident,)).fetchone()
  if not row:raise HubError('演示不存在')
  d=json.loads(row[0])
  if project_id and d['project_id']!=project_id:raise HubError('演示不属于当前项目')
  return d
 def snapshot(self,project_id):
  with self.hub.lock:rows=self.hub.db.execute("SELECT body FROM design_reviews WHERE json_extract(body,'$.project_id')=? AND coalesce(json_extract(body,'$.state'),'')!='cleaned' ORDER BY rowid DESC",(project_id,)).fetchall()
  return [json.loads(r[0]) for r in rows]
 def skip(self,actor,session_id,revision,project_id=None):
  self.hub.require(actor,{'user'})
  with self.planning.lock,self.workflows.lock:
   s=self.planning.get(session_id)
   if project_id and s.get('project_id')!=project_id:raise HubError('讨论不属于当前项目')
   if s.get('design_id'):raise HubError('演示已启动，请先完成或停止演示流程')
   if s.get('pending') or s['state']!='awaiting_approval' or revision!=s['revision']:raise HubError('请先审阅最新讨论计划')
   s['options']['preview_mode']='skip';self.planning.save(s)
   return self.planning.approve(s,revision,None)
 def start(self,actor,session_id,revision,project_id=None):
  self.hub.require(actor,{'user'})
  with self.planning.lock,self.workflows.lock,self.lock:
   s=self.planning.get(session_id)
   if project_id and s.get('project_id')!=project_id:raise HubError('讨论不属于当前项目')
   if s.get('design_id'):
    d=self.get(s['design_id'])
    if d['state'] in ('building','review'):return s
   if s.get('pending') or s['state']!='awaiting_approval' or revision!=s['revision']:raise HubError('请先审阅最新讨论计划')
   if not s.get('project_id'):raise HubError('请在项目中制作演示')
   d={'id':uid(),'session_id':s['id'],'project_id':s['project_id'],'revision':s['revision'],'version':0,'state':'new','created':time.time(),'versions':[],'feedback':[],'outline':s.get('design_outline',[]),'production_options':dict(s['options']),'production_plan':s['plan'],'requirement':s['history'][0]['text']}
   self.launch(d,s,'首次制作：按讨论计划展示全部页面与层次。')
   s.update(design_id=d['id'],state='designing');self.planning.save(s);return s
 def launch(self,d,s,feedback):
  manager=project_manager(self.hub,record=s)
  d['production_options'],removed=self.workflows.launch_options(d['production_options'],manager)
  if removed:s['roster_replan']={'unavailable':removed,'available':d['production_options']['agents']}
  version=d['version']+1
  folder=(Path(d['production_options']['cwd'])/'.hub-design'/d['id']/('draft-'+str(version))).resolve();folder.mkdir(parents=True,exist_ok=True)
  previous=d['versions'][-1] if d['versions'] else None
  if previous:
   import shutil
   for page in previous['pages']:shutil.copy2(Path(previous['directory'])/page['path'],folder/page['path'])
   (folder/'manifest.json').write_text(json.dumps({'title':previous['title'],'pages':previous['pages']},ensure_ascii=False,indent=2),encoding='utf-8')
  brief=folder/'brief.md'
  brief.write_text(DESIGN_POLICY+'\n需求：'+d['requirement']+'\n讨论计划：'+d['production_plan']['report']+'\n页面基线：'+json.dumps(d['outline'],ensure_ascii=False)+'\n本轮反馈：'+feedback,encoding='utf-8')
  opts=dict(d['production_options']);opts.pop('preview_mode',None);opts.pop('cwd');seconds=opts.pop('max_seconds')
  for rt in self.workflows.runtimes:
   if rt.provider in {self.workflows.runtime(a).provider for a in [manager]+opts['agents']}:
    cfg=rt.config()
    if cfg['cwd']!=d['production_options']['cwd'] or cfg['max_seconds']!=min(seconds,cfg.get('authorized_max_seconds',seconds)):
     rt.configure('user',d['production_options']['cwd'],cfg['permission'],opts['max_calls'],seconds,True,True)
  manager=project_manager(self.hub,record=s);opts['agents']=[a for a in opts['agents'] if a!=manager]
  opts['reviewer']=independent_reviewer(manager,opts['agents'],opts.get('reviewer'))
  task='你负责组织本轮产品演示。先读 '+str(brief)+'，其中含完整需求、页面基线和本轮全部修改意见。按范围自行制作或用 project_assign 分派，避免重做无需修改的页面；核查后用 project_complete 发布。仅制作静态演示，不实现真实业务。全部页面统一通过manifest.json和project_complete提交到演示审阅入口，不逐页publish_artifact发送网页卡片。'
  if s.get('roster_replan'):task+='\n'+self.workflows.roster_instruction(s['roster_replan']['unavailable'],opts['agents'])
  requirement='产品演示阶段，禁止真实产品实现。完整需求与交付契约在 '+str(brief)
  w=self.workflows.start('user',requirement,confirmed=True,manager=manager,manager_instruction=task,approval_key='design:'+d['id']+':'+str(version),project_id=d['project_id'],**opts)
  w.update(approved_plan=d['production_plan'],roster_replan=s.get('roster_replan'),design_review=d['id'],design_version=version,design_dir=str(folder),design_brief=str(brief));self.workflows.save(w)
  d.update(version=version,state='building',workflow_id=w['id'],working_directory=str(folder));self.save(d)
 def prepare_publish(self,w):
  d=self.get(w['design_review']);root=Path(w['design_dir']).resolve()
  try:manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
  except (OSError,ValueError) as e:raise HubError('演示尚无可读取manifest.json，请补齐后再提交') from e
  pages=manifest.get('pages');title=manifest.get('title','产品演示')
  if not isinstance(pages,list) or not pages:raise HubError('演示必须包含完整页面清单')
  ids=set();blobs={};normalized=[]
  for p in pages:
   if not isinstance(p,dict) or not isinstance(p.get('id'),str) or not re.fullmatch(r'[A-Za-z0-9_-]+',p['id']) or p['id'] in ids:raise HubError('演示页面ID缺失或重复')
   ids.add(p['id']);path=p.get('path','');file=(root/path).resolve()
   if not file.is_relative_to(root) or file.suffix.lower()!='.html':raise HubError('演示页面必须在工作目录内且为HTML')
   try:html=file.read_text(encoding='utf-8-sig')
   except OSError as e:raise HubError('缺少演示页面：'+str(path)) from e
   if '<' not in html:raise HubError('演示页面没有HTML内容')
   from .design_assets import bundle_html
   html=bundle_html(html,file,root)
   # Freeze simple filenames; no copied project executables or credentials.
   filename=p['id']+'.html';blobs[filename]=html
   normalized.append({'id':p['id'],'title':str(p.get('title') or p['id']),'parent':p.get('parent') or None,'kind':p.get('kind','screen'),'path':filename,'note':str(p.get('note',''))})
  if not any(p['kind']=='architecture' for p in normalized):raise HubError('请补充架构与后端规划页面')
  for p in normalized:
   seen={p['id']};parent=p['parent']
   while parent:
    if parent not in ids or parent in seen:raise HubError('页面层级引用缺失或形成循环')
    seen.add(parent);parent=next(x['parent'] for x in normalized if x['id']==parent)
  normalized.sort(key=lambda p:p['kind']=='architecture')
  # The manager confirms requirement coverage. Outline IDs are planning
  # labels, not a publication contract; renamed pages remain reviewable.
  payload=json.dumps({'title':title,'pages':normalized,'html':blobs},sort_keys=True,ensure_ascii=False)
  digest=hashlib.sha256(payload.encode()).hexdigest()
  frozen=(self.hub.directory/'designs'/d['id']/(str(d['version'])+'-'+digest[:12])).resolve();frozen.mkdir(parents=True,exist_ok=True)
  for name,html in blobs.items():(frozen/name).write_text(html,encoding='utf-8')
  manifest={'title':title,'pages':normalized};(frozen/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
  version={**manifest,'version':d['version'],'digest':digest,'directory':str(frozen),'created':time.time()}
  d['versions']=[v for v in d['versions'] if v['version']!=version['version']]+[version]
  d.pop('publish_error',None);d.update(state='review',digest=digest)
  return d
 def verify_baseline(self,baseline):
  try:
   root=Path(baseline['directory']);manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
   html={p['path']:(root/p['path']).read_text(encoding='utf-8') for p in manifest['pages']}
   digest=hashlib.sha256(json.dumps({'title':manifest['title'],'pages':manifest['pages'],'html':html},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
  except (OSError,KeyError,ValueError) as e:raise HubError('已确认设计基线缺失，请恢复该版本后再验收') from e
  if digest!=baseline['digest']:raise HubError('已确认设计基线被修改，不能将其冒充原设计验收')
 def content(self,actor,design_id,version=None,project_id=None):
  self.hub.require(actor,{'user'});d=self.get(design_id,project_id)
  v=next((v for v in d['versions'] if v['version']==(version or d['version'])),None)
  if not v:raise HubError('演示尚在制作，暂无可预览版本')
  return {**v,'html':{p['id']:(Path(v['directory'])/p['path']).read_text(encoding='utf-8') for p in v['pages']}}
 def feedback(self,actor,design_id,version,body='',page_id=None,region=None,scope='region',project_id=None,entries=None,overall=''):
  self.hub.require(actor,{'user'})
  with self.planning.lock,self.workflows.lock,self.lock:
   d=self.get(design_id,project_id)
   if d['state']!='review' or version!=d['version']:raise HubError('请等待并审阅最新演示版本后修改')
   latest=d['versions'][-1];page_ids={p['id'] for p in latest['pages']}
   if entries is None:entries=[{'body':body,'page_id':page_id,'region':region,'scope':scope}]
   if not isinstance(entries,list):raise HubError('修改意见格式无效')
   pending=[]
   if overall:
    text(overall,20000);pending.append({'body':overall,'page_id':None,'scope':'all','region':None})
   for item in entries:
    if not isinstance(item,dict):raise HubError('修改意见格式无效')
    body=item.get('body','');text(body,20000)
    page_id=item.get('page_id');scope=item.get('scope','region');region=item.get('region')
    if scope not in ('region','page','all'):raise HubError('修改范围无效')
    if scope!='all' and page_id not in page_ids:raise HubError('请选择要修改的页面')
    if region is not None:
     if not isinstance(region,dict) or set(region)!={'x','y','width','height'} or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in region.values()) or region['x']+region['width']>1.001 or region['y']+region['height']>1.001:raise HubError('框选坐标无效')
    pending.append({'page_id':page_id,'scope':scope,'region':region,'body':body})
   if not pending:raise HubError('请填写修改意见')
   for entry in pending:entry.update(version=version,created=time.time())
   d['feedback'].extend(pending)
   s=self.planning.get(d['session_id'])
   self.launch(d,s,'用户本轮全部修改意见，请统一处理（坐标相对于页面展示区域）：'+json.dumps(pending,ensure_ascii=False))
   s.update(state='designing');self.planning.save(s);return d
 def accept(self,actor,design_id,version,digest,project_id=None):
  self.hub.require(actor,{'user'})
  with self.planning.lock,self.workflows.lock,self.lock:
   d=self.get(design_id,project_id)
   if d['state']=='approved':return self.planning.get(d['session_id'])
   if d['state']!='review' or version!=d['version'] or digest!=d.get('digest'):raise HubError('设计已变化，请审阅最新版本后确认')
   baseline=d['versions'][-1]
   # Re-read the frozen artifact so approval cannot silently accept changed files.
   self.verify_baseline(baseline)
   s=self.planning.get(d['session_id']);s.update(expires=time.time()+86400,state='awaiting_approval',design_approved={'id':d['id'],'version':version,'digest':digest,'directory':baseline['directory']})
   self.planning.save(s)
   result=self.planning.approve(s,s['revision'],None)
   d.update(state='approved',approved_at=time.time(),implementation_workflow=result['workflow_id']);self.save(d)
   with self.hub.tx():self.hub.audit(actor,'design.approved',{'project':d['project_id'],'design':d['id'],'version':version,'digest':digest})
   return result
