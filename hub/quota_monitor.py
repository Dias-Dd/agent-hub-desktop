"""Non-model quota sampling, durable threshold alerts and authorized manager handoff."""
import json
import time
from .core import HubError,uid


class QuotaMonitor:
    def __init__(self,hub,workflows,codex,antigravity,deepseek):
        self.next_sample=0
        with hub.tx():hub.db.execute('CREATE TABLE IF NOT EXISTS quota_alert_state(id TEXT PRIMARY KEY,level INTEGER,body TEXT,updated REAL)')
        self.hub=hub;self.workflows=workflows;self.codex=codex;self.antigravity=antigravity;self.deepseek=deepseek

    def start(self):
        pass
    def close(self):
        pass
    def snapshot(self):
        return []

    def samples(self):
        registry=getattr(self.hub,'integrations',None)
        if not registry:return []
        profiles=[a for a in registry.rows('agent_profiles') if a.get('enabled')]
        result=[]
        states={a['id']:registry.quota_status(a['id']) for a in profiles}
        for group in registry.quota_overview():
            for window in group['windows']:
                remaining=window.get('remaining')
                if type(remaining) not in (int,float):continue
                connection=window['connection_id']
                result.append({'id':connection+':'+window['name']+':'+window['source'],'label':group['name']+' / '+window['account']+' / '+window['name'],'remaining':remaining,'resets_at':window.get('resets_at'),'agents':[a['id'] for a in profiles if a['connection_id']==connection and (window['source']!='official' or any(' / '.join(str(x) for x in (w.get('group'),w.get('window') or w.get('name')) if x)==window['name'] for w in states[a['id']]['windows']))]})
        # Provider rejections can be definitive even without a numeric quota API.
        with self.hub.lock:prior_ids={r[0] for r in self.hub.db.execute("SELECT id FROM quota_alert_state WHERE id LIKE 'model-rejection:%'")}
        for profile in profiles:
            state=states[profile['id']];ident='model-rejection:'+profile['id']+':'+profile['connection_id']+':'+profile['model']
            if not state.get('detail') and ident not in prior_ids:continue
            result.append({'id':ident,'label':profile['name']+' / '+profile['model'],'agents':[profile['id']],'exhausted':state['exhausted'],'remaining':state.get('remaining'),'resets_at':state.get('resets_at'),'detail':state.get('detail')})
        return result

    def patrol(self):
        if time.time()<self.next_sample:return
        self.next_sample=time.time()+5
        for sample in self.samples():self.observe(sample)

    def observe(self,sample):
        remaining=sample['remaining']
        if 'exhausted' in sample:level=2 if sample['exhausted'] else 0
        else:
            if type(remaining) not in (int,float) or not 0<=remaining<=100:return
            level=2 if remaining<=0 else 1 if remaining<10 else 0
        preempt=[]
        with self.workflows.lock:
            projects=self.workflows.snapshot('user')
            with self.hub.tx():
                prior=self.hub.db.execute('SELECT level,body FROM quota_alert_state WHERE id=?',(sample['id'],)).fetchone()
                previous=prior['level'] if prior else 0
                body=json.dumps(sample,ensure_ascii=False)
                if prior and previous==level and prior['body']==body:return
                self.hub.db.execute('INSERT OR REPLACE INTO quota_alert_state VALUES(?,?,?,?)',(sample['id'],level,body,time.time()))
                if level==previous:return
                recovered=level<previous
                description='额度恢复' if recovered else '额度耗尽' if level==2 else '额度低于10%'
                body=description+'：'+sample['label']+('，剩余 '+str(remaining)+'%。' if type(remaining) in (int,float) else '，剩余比例未知。')+('预计恢复 '+time.strftime('%m-%d %H:%M',time.localtime(sample['resets_at'])) if sample.get('resets_at') else '恢复时间未知。')
                if sample.get('detail'):body+=' 提供商信息：'+sample['detail']
                for w in projects:
                    manager=self.workflows.manager(w)
                    if w['status'] in ('completed','stopped','cancelled') or not set(sample['agents'])&set([manager]+w['agents']):continue
                    project=w.get('project_id') or w['id'];message=uid();event_id='quota:'+uid()
                    if recovered:
                        from .notice_batch import queue
                        message=queue(self.hub,w,manager,body,'quota_recovered')
                    else:
                        self.hub.db.execute("INSERT INTO messages(id,sender,recipient,body,mode,status,created,project_id) VALUES(?,'平台',?,?,'immediate','pending',?,?)",(message,manager,body,time.time(),project))
                        event={'type':'quota_alert','message_id':message,'from':'平台','body':body}
                        self.hub.db.execute("INSERT INTO workflow_events VALUES(?,?,NULL,?,'pending',NULL,?)",(event_id,w['id'],json.dumps(event,ensure_ascii=False),time.time()))
                    self.hub.db.execute("INSERT INTO messages(id,sender,recipient,body,mode,status,created,project_id) VALUES(?,?,'user',?,'queue','user_delivered',?,?)",(uid(),'平台',body,time.time(),project))
                    if not recovered and w['status'] in ('active','needs_attention') and not self.hub.coordination.is_stopped(manager):preempt.append((manager,project))
            for manager,project in preempt:self.hub.coordination.prioritize(manager,project)

    def authorize(self,actor,workflow_id,confirmed=False):
        self.hub.require(actor,{'user'})
        if confirmed is not True:raise HubError('请确认将 DeepSeek 加入此项目并授权耗尽接管')
        with self.workflows.lock:
            w=next((x for x in self.workflows.snapshot('user') if x['id']==workflow_id),None)
            if not w or w['status'] not in ('active','paused','needs_attention'):raise HubError('请选择未结束项目')
            cfg=self.deepseek.config()
            if not cfg['enabled'] or not cfg.get('takeover'):raise HubError('请先完成 DeepSeek 接管授权')
            if cfg['cwd']!=w['cwd']:raise HubError('DeepSeek 工作目录必须与项目一致')
            self.workflows.valid({**w,'status':'active'})
            w.pop('steps',None)
            if 'deepseek' not in w['agents']:w['agents'].append('deepseek')
            w['grants']['deepseek']=cfg['grant_id'];w['backup_manager']='deepseek';self.workflows.save(w)
            with self.hub.tx():self.hub.audit(actor,'project.backup_authorized',{'project':w['id'],'provider_grant':cfg['grant_id']})
            return {'authorized':True,'project':w['id']}

    def takeover(self,item):
        target=item.get('backup_manager')
        if not target or target==self.workflows.manager(item):return
        try:backup=self.workflows.runtime(target)
        except HubError:return
        with self.workflows.lock:
            with self.hub.lock:
                w=json.loads(self.hub.db.execute('SELECT body FROM workflows WHERE id=?',(item['id'],)).fetchone()[0])
                previous=self.workflows.manager(w)
                busy=self.hub.db.execute("SELECT 1 FROM executions WHERE agent IN (?,?) AND status IN ('running','interrupting')",(previous,target)).fetchone()
            if w['status']!='active' or self.workflows.manager(w)==target or busy:return
            try:self.workflows.valid(w)
            except HubError:return
            cfg=backup.config()
            if cfg['grant_id']!=w['grants'].get(backup.provider) or not cfg.get('takeover') or not cfg['enabled'] or self.hub.coordination.is_stopped(target):return
            steps=self.workflows.steps(w['id'])
            if any(s['agent']==previous and s['kind'] in ('plan','review') and not s['run_id'] for s in steps):return
            if not w.get('unlimited_calls') and len(steps)>=w['max_calls']:return
            with self.hub.tx():
                if self.hub.db.execute("SELECT 1 FROM executions WHERE agent IN (?,?) AND status IN ('running','interrupting')",(previous,target)).fetchone():return
                for s in steps:
                    if s['kind'] not in ('plan','review') or s['agent']!=previous:continue
                    if not s['run_id'] or s['status'] in ('queued','waiting_quota'):
                        if s['run_id']:self.hub.db.execute("UPDATE executions SET status='cancelled',finished=?,result='经理额度耗尽，已交接；不重放' WHERE id=?",(time.time(),s['run_id']))
                        self.hub.db.execute("UPDATE messages SET status='cancelled' WHERE body LIKE ?",('[task:'+s['task']+'] %',))
                        self.hub.db.execute("UPDATE tasks SET status='blocked',note='经理交接，原回合不执行' WHERE id=?",(s['task'],))
                    self.hub.db.execute("UPDATE workflow_events SET status='pending',manager_task=NULL WHERE manager_task=? AND status='claimed'",(s['task'],))
                w.update(manager=target,previous_manager=previous,processed=max([s['seq'] for s in steps if s['kind'] in ('plan','review')]+[w['processed']]),phase='handoff',report='原经理额度耗尽，备用经理按用户授权接管')
                self.hub.db.execute('UPDATE workflows SET body=? WHERE id=?',(json.dumps(w,ensure_ascii=False),w['id']))
                self.hub.audit('supervisor','project.manager_handoff',{'project':w['id'],'from':previous,'to':target,'auto_return':False})
            w.pop('steps',None)
            self.workflows.prepare_manager(w,steps,'你接任当前项目经理。先读取状态和未完成事项，不重派在途任务。'+json.dumps({'previous_manager':previous,'requirement':w['requirement'],'reviewer':w.get('reviewer')},ensure_ascii=False))
