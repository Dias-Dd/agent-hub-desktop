import os
from .manager_identity import resolve as project_manager
"""Durable, non-model timer service and immutable user-facing artifacts."""
import json
import math
import mimetypes
import shutil
import time
from pathlib import Path
from urllib.parse import quote
from .core import HubError, uid, text


class Automation:
    def __init__(self, server):
        self.server = server
        self.hub = server.hub
        self.root = self.hub.directory / 'shared-artifacts'
        self.root.mkdir(exist_ok=True)
        self.next_poll = 0
        with self.hub.tx():
            self.hub.db.execute('CREATE TABLE IF NOT EXISTS hub_timers(id TEXT PRIMARY KEY,body TEXT)')
            self.hub.db.execute('CREATE TABLE IF NOT EXISTS hub_timer_history(id TEXT PRIMARY KEY,body TEXT)')
            for row in self.hub.db.execute("SELECT body FROM hub_timers WHERE json_extract(body,'$.state') IN ('finished','cancelled')").fetchall():self.save(json.loads(row[0]))
            self.hub.db.execute('CREATE TABLE IF NOT EXISTS shared_artifacts(id TEXT PRIMARY KEY,body TEXT)')

    def timers(self, project_id=None, include_finished=True):
        with self.hub.lock:
            rows=self.hub.db.execute('SELECT body FROM hub_timers ORDER BY rowid').fetchall()
            if include_finished:rows+=self.hub.db.execute('SELECT body FROM hub_timer_history ORDER BY rowid').fetchall()
            return [x for row in rows if (x:=json.loads(row[0])) and (project_id is None or x.get('project_id')==project_id) and (include_finished or x.get('state') in ('scheduled','held','failed'))]

    def save(self, item):
        # Caller owns the dispatch transaction; delivery cannot replay on restart.
        if item['state'] in ('finished','cancelled'):
            self.hub.db.execute('INSERT OR REPLACE INTO hub_timer_history VALUES(?,?)',(item['id'],json.dumps(item,ensure_ascii=False)))
            self.hub.db.execute('DELETE FROM hub_timers WHERE id=?',(item['id'],))
            self.hub.db.execute('DELETE FROM hub_timer_history WHERE rowid NOT IN (SELECT rowid FROM hub_timer_history ORDER BY rowid DESC LIMIT 500)')
        else:self.hub.db.execute('INSERT OR REPLACE INTO hub_timers VALUES(?,?)',(item['id'],json.dumps(item,ensure_ascii=False)))

    def schedule_wake(self, actor, run_id, delay_seconds=60, recipient=None, note='', request_key='reminder', interval_seconds=None, condition='time', wait_for_agent=None):
        with self.server.workflows.lock:
            w, run = self.server.workflows.run_context(actor, run_id)
            recipient = recipient or actor
            members = set(w['agents']) | {self.server.workflows.manager(w)}
            if wait_for_agent is not None:
                self.server.workflows.run_context(actor,run_id,manager=True)
                if actor!=self.server.workflows.manager(w):raise HubError('仅当前经理可以标记项目等待关键成员；成员可设置普通提醒')
            if wait_for_agent is not None and wait_for_agent not in members:raise HubError('只能等待本项目已授权的成员')
            if recipient not in members:
                raise HubError('只能唤醒当前已授权项目的成员')
            if condition not in ('time', 'quota_recovered'):
                raise HubError('未知唤醒条件')
            if type(delay_seconds) not in (int, float) or not math.isfinite(delay_seconds) or delay_seconds < 1:
                raise HubError('延迟必须是正秒数')
            if interval_seconds is not None and (type(interval_seconds) not in (int, float) or not math.isfinite(interval_seconds) or interval_seconds < 5):
                raise HubError('周期至少5秒；错过的周期合并一次')
            if note: text(note, 20000)
            text(request_key, 200)
            now = time.time()
            with self.hub.tx():
                prior = next((x for x in self.timers(w.get('project_id') or w['id']) if x['workflow_id'] == w['id'] and x['creator'] == actor and x['recipient'] == recipient and x['request_key'] == request_key and x['state'] not in ('cancelled', 'finished')), None)
                item = {**(prior or {}), 'id': prior['id'] if prior else uid(), 'project_id': w.get('project_id') or w['id'], 'workflow_id': w['id'], 'creator': actor, 'recipient': recipient, 'request_key': request_key, 'note': note, 'condition': condition, 'wait_for_agent': wait_for_agent, 'due': now + delay_seconds, 'interval': interval_seconds, 'state': 'scheduled', 'reason': '', 'created': prior['created'] if prior else now, 'updated': now, 'generation': (prior or {}).get('generation', 0) + 1, 'fires': (prior or {}).get('fires', 0), 'failures': 0}
                self.save(item)
                if wait_for_agent:
                    w['resource_wait']={'agent':wait_for_agent,'timer_id':item['id'],'until':item['due']}
                    w['phase']='waiting_resource';w['next_inspection']=item['due']
                    self.hub.db.execute('UPDATE workflows SET body=? WHERE id=?',(json.dumps(w,ensure_ascii=False),w['id']))
                self.hub.audit(actor, 'timer.saved', {'project': item['project_id'], 'timer': item['id'], 'recipient': recipient, 'due': item['due']})
            return {'timer_id': item['id'], 'due': item['due'], 'recipient': recipient, 'updated_existing': bool(prior),'wait_for_agent':wait_for_agent}

    def timer_list(self, actor, run_id):
        w, _ = self.server.workflows.run_context(actor, run_id)
        return self.timers(w.get('project_id') or w['id'],include_finished=False)

    def timer_cancel(self, actor, timer_id, run_id=None):
        with self.server.workflows.lock:
            w = self.server.workflows.run_context(actor, run_id)[0] if actor != 'user' else None
            if actor == 'user': self.hub.require(actor, {'user'})
            with self.hub.tx():
                row = self.hub.db.execute('SELECT body FROM hub_timers WHERE id=?', (timer_id,)).fetchone()
                if not row: raise HubError('定时器不存在')
                item = json.loads(row[0])
                if w and (item['workflow_id'] != w['id'] or actor not in (item['creator'], self.server.workflows.manager(w))):
                    raise HubError('只能取消自己或所管理项目的定时器')
                item.update(state='cancelled', reason='已取消', updated=time.time())
                self.save(item)
                row=self.hub.db.execute('SELECT body FROM workflows WHERE id=?',(item['workflow_id'],)).fetchone()
                workflow=json.loads(row[0]) if row else {}
                if workflow.get('resource_wait',{}).get('timer_id')==timer_id:
                    workflow.pop('resource_wait',None);workflow['phase']='working';workflow['next_inspection']=time.time()+self.server.workflows.patrol_seconds()
                    self.hub.db.execute('UPDATE workflows SET body=? WHERE id=?',(json.dumps(workflow,ensure_ascii=False),workflow['id']))
                self.hub.audit(actor, 'timer.cancelled', {'timer': timer_id, 'project': item['project_id']})
            return {'cancelled': True}

    def quota_waiting(self,run):
        # Only a provider-confirmed wait is actionable; a textual "paused" report is not a pause request.
        with self.server.workflows.lock:
            row=self.hub.db.execute('SELECT w.body,e.retry_after FROM workflows w JOIN workflow_steps s ON s.workflow=w.id JOIN executions e ON e.task_id=s.task WHERE e.id=?',(run['id'],)).fetchone()
            if not row:return
            w=json.loads(row['body']);retry=row['retry_after'];now=time.time()
            body=run['agent']+' 等待额度'+('，预计 '+time.strftime('%m-%d %H:%M',time.localtime(retry)) if retry else '，恢复时间未知')+'。该成员原执行保留；继续安排其它可用成员，不暂停项目，也不要重复派同一任务。'
            with self.hub.tx():
                self.hub.db.execute("INSERT OR IGNORE INTO workflow_events VALUES(?,?,NULL,?,'pending',NULL,?)",('quota-wait:'+run['id']+':'+str(retry),w['id'],json.dumps({'type':'quota_wait','agent':run['agent'],'body':body},ensure_ascii=False),now))
            # The runtime already has a durable retry_after. Do not create a second model execution.

    def quota_delay(self, agent):
        """Use known reset evidence; unknown readiness remains unknown, never invented."""
        now = time.time()
        with self.hub.lock:
            waiting = self.hub.db.execute("SELECT MAX(retry_after) FROM executions WHERE agent=? AND status='waiting_quota'", (agent,)).fetchone()[0]
        if waiting and waiting > now: return waiting, '等待提供商预计恢复时间'
        registry = self.server.integrations
        profile = registry.get('agent_profiles', agent)
        connection = registry.get('integration_connections', profile['connection_id'])
        samples = []
        quota = connection.get('quota') or {}
        if quota.get('remaining') is not None: samples.append(quota)
        samples += connection.get('official_windows') or []
        exhausted = [s for s in samples if s.get('remaining', 100) is not None and s.get('remaining', 100) <= 0]
        if exhausted:
            resets = [s.get('resets_at') for s in exhausted]
            if any(not isinstance(x, (int, float)) for x in resets): return now + 600, '额度耗尽，恢复时间未知；稍后再检查'
            if max(resets) > now: return max(resets), '等待预计额度恢复'
            return None, '预计恢复时间已到；仅尝试唤醒，真实可用性由提供商确认'
        if samples or waiting: return None, '已有额度或预计恢复证据'
        return now + 600, '无法读取额度；保持等待，不用推理调用探测余额'

    def quota_unknown(self,agent):
        with self.hub.lock:
            retry=self.hub.db.execute("SELECT MAX(retry_after) FROM executions WHERE agent=? AND status='waiting_quota'",(agent,)).fetchone()[0]
        if retry:return False
        profile=self.server.integrations.get('agent_profiles',agent)
        connection=self.server.integrations.get('integration_connections',profile['connection_id'])
        samples=[x for x in [connection.get('quota') or {}]+(connection.get('official_windows') or []) if x.get('remaining') is not None]
        return not samples or any(x['remaining']<=0 and not isinstance(x.get('resets_at'),(int,float)) for x in samples)

    def patrol(self):
        if time.monotonic() < self.next_poll: return
        self.next_poll = time.monotonic() + 1
        with self.server.workflows.lock:
            with self.hub.lock:pending=[json.loads(r[0]) for r in self.hub.db.execute("SELECT body FROM hub_timers WHERE json_extract(body,'$.state') IN ('scheduled','held') AND json_extract(body,'$.due')<=? ORDER BY rowid",(time.time(),))]
            processed=set()
            for timer in pending:
                if timer['id'] in processed:continue
                if timer['state'] not in ('scheduled', 'held') or timer['due'] > time.time(): continue
                batch=[x for x in pending if x['id'] not in processed and x['state'] in ('scheduled','held') and x['due']<=time.time() and (x['workflow_id'],x['recipient'],x['condition'],x.get('wait_for_agent'))==(timer['workflow_id'],timer['recipient'],timer['condition'],timer.get('wait_for_agent'))]
                processed.update(x['id'] for x in batch)
                try: self.fire(timer,batch)
                except Exception as error:
                    with self.hub.tx():
                        timer['failures'] += 1
                        timer.update(state='failed' if timer['failures'] >= 5 else 'held', reason=str(error)[:500], due=time.time() + min(3600, 30 * 2 ** min(timer['failures'], 6)), updated=time.time())
                        self.save(timer)
                        self.hub.audit('supervisor', 'timer.retry', {'timer': timer['id'], 'project': timer['project_id'], 'reason': timer['reason'], 'state': timer['state']})
            self.recover_quota_waits()

    def fire(self, timer, batch=None):
        batch=batch or [timer]
        row = self.hub.db.execute('SELECT body FROM workflows WHERE id=?', (timer['workflow_id'],)).fetchone()
        w = json.loads(row[0]) if row else None
        now = time.time()
        reason = None
        if not w or w['status'] in ('completed', 'cancelled', 'failed'):
            with self.hub.tx(): timer.update(state='finished', reason='项目已结束', updated=now); self.save(timer)
            return
        target = timer['recipient']
        if target not in set(w['agents']) | {self.server.workflows.manager(w)}: reason = '目标已不在项目参与者中'
        elif self.server.coordination.is_stopped(target): reason = '紧急停止锁；提醒已保留，不能绕过用户停止'
        elif w['status']=='needs_attention' and target!=self.server.workflows.manager(w): reason='经理恢复检查中；提醒保留'
        elif w['status'] == 'stopped': reason = '用户已停止项目，等待明确恢复'
        elif w['status'] in ('paused', 'blocked', 'waiting_quota'):
            if w.get('pause_reason') not in ('wait_time', 'quota'): reason = '人工暂停或待核查；提醒保留'
        from .project_activity import owner
        active_project=owner(self.hub)
        if active_project and active_project!=(w.get('project_id') or w['id']):reason='另一项目正在执行；定时提醒暂缓'
        if reason:
            with self.hub.tx(): timer.update(state='held', reason=reason, updated=now); self.save(timer)
            return
        unknown_check=False
        if timer['condition'] == 'quota_recovered':
            due, reason = self.quota_delay(timer.get('wait_for_agent') or target)
            unknown_check=bool(due and timer.get('wait_for_agent') and target==self.server.workflows.manager(w) and self.quota_unknown(timer['wait_for_agent']))
            if due and not unknown_check:
                with self.hub.tx():
                    timer.update(state='held',reason=reason,due=due,updated=now);self.save(timer)
                    if w.get('resource_wait',{}).get('timer_id')==timer['id']:
                        w['resource_wait']['until']=due;w['next_inspection']=due
                        self.hub.db.execute('UPDATE workflows SET body=? WHERE id=?',(json.dumps(w,ensure_ascii=False),w['id']))
                return
        self.server.workflows.valid({**w, 'status': 'active'})
        # Do not add a new execution while this timer's last delivery is still in flight.
        last_message=timer.get('last_message')
        if last_message:
            event=self.hub.db.execute("SELECT status FROM workflow_events WHERE (json_extract(body,'$.message_id')=? OR EXISTS (SELECT 1 FROM json_each(workflow_events.body,'$.merged_message_ids') WHERE value=?)) AND status IN ('pending','claimed')",(last_message,last_message)).fetchone()
            if event and event[0] in ('pending','claimed'):return
        prior = timer.get('last_task')
        if prior:
            run = self.hub.db.execute('SELECT status FROM executions WHERE task_id=?', (prior,)).fetchone()
            if not run or run[0] in ('queued', 'running', 'waiting_quota', 'interrupting'): return
        body = '\n'.join('定时提醒（来自 '+x['creator']+'）：'+(x['note'] or '检查当前项目并按原授权继续；不重复已完成任务。') for x in batch)+'\n只在经理已有分工和用户获批范围内继续，不能借提醒改变他人的分工。'
        if unknown_check:body+='\n关键模型额度与恢复时间未知；本轮是到期核查，不代表已恢复。检查原任务后推进；仍不足时延长下一次提醒，不要求用户手动续推。'
        # SQLite commits dispatch and the timer cursor atomically: restart cannot replay a fire.
        with self.hub.tx():
            if w.get('resource_wait',{}).get('timer_id') in {x['id'] for x in batch}:
                w.pop('resource_wait',None);w['phase']='working';w['next_inspection']=now+self.server.workflows.patrol_seconds()
                self.hub.db.execute('UPDATE workflows SET body=? WHERE id=?',(json.dumps(w,ensure_ascii=False),w['id']))
            if w['status'] in ('paused', 'blocked', 'waiting_quota'):
                w.update(status='active', pause_reason=None)
                self.hub.db.execute('UPDATE workflows SET body=? WHERE id=?', (json.dumps(w, ensure_ascii=False), w['id']))
            ident = uid()
            if target == self.server.workflows.manager(w):
                from .notice_batch import queue
                ident=queue(self.hub,w,target,body,'timer',timer['creator'])
                timer['last_task'] = None
            else:
                self.hub.db.execute("INSERT INTO messages(id,sender,recipient,body,mode,status,created,project_id) VALUES(?,'平台',?,?,'queue','pending',?,?)", (ident, target, body, now, timer['project_id']))
            if target == self.server.workflows.manager(w):
                pass
            elif (waiting_run:=self.hub.db.execute("SELECT e.id,e.task_id FROM executions e JOIN workflow_steps s ON s.task=e.task_id WHERE s.workflow=? AND e.agent=? AND e.status='waiting_quota'",(w['id'],target)).fetchone()):
                self.hub.db.execute("UPDATE executions SET retry_after=CASE WHEN retry_after IS NULL OR retry_after<=? THEN ? ELSE retry_after END WHERE agent=? AND status='waiting_quota' AND task_id IN (SELECT task FROM workflow_steps WHERE workflow=?)",(now,now,target,w['id']))
                self.hub.db.execute("UPDATE messages SET status='completed',result='已提示恢复原等待执行，未重复创建任务' WHERE id=?",(ident,))
                self.hub.db.execute("UPDATE executions SET prompt=COALESCE(prompt,'')||? WHERE id=?",('\n'+body,waiting_run['id']))
                timer['last_task']=waiting_run['task_id']
            else:
                # Inline the ordinary message step so it shares the cursor transaction.
                task = uid()
                seq = self.hub.db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM workflow_steps WHERE workflow=?', (w['id'],)).fetchone()[0]
                self.hub.db.execute('INSERT INTO tasks(id,agent,title,assigned_by,created,project_id) VALUES(?,?,?,?,?,?)', (task, target, body, timer['creator'], now, timer['project_id']))
                self.hub.db.execute('INSERT INTO workflow_steps VALUES(?,?,?,?,?)', (w['id'], seq, task, target, 'message'))
                self.hub.db.execute('INSERT INTO wakeups VALUES(?,?,?,?,?,?,?)', (ident, w['id'], task, ident, 0, 'queued', '定时器在现有授权内投递'))
                from .task_resources import register
                register(self.server.workflows,w,task,target,'work',body)
                timer['last_task'] = task
            if timer['condition']=='quota_recovered' and target!=self.server.workflows.manager(w):
                self.hub.db.execute("INSERT INTO workflow_events VALUES(?,?,NULL,?,'pending',NULL,?)",('quota-timer:'+ident,w['id'],json.dumps({'type':'quota_resume','from':'平台','body':target+' 的额度恢复条件已满足或预计恢复时间已到，已投递定时提醒；请以提供商真实结果为准，不重复派工。'},ensure_ascii=False),now))
            timer.update(state='scheduled' if timer['interval'] else 'finished', reason='已投递；忙碌时排队', fires=timer['fires'] + 1, last_message=ident, updated=now, due=now + (timer['interval'] or 0), failures=0)
            self.save(timer)
            for other in batch:
                if other['id']==timer['id']:continue
                other.update(state='scheduled' if other['interval'] else 'finished',reason='已合并投递；忙碌时排队',fires=other['fires']+1,last_message=ident,last_task=timer['last_task'],updated=now,due=now+(other['interval'] or 0),failures=0)
                self.save(other)
            self.hub.audit('supervisor', 'timer.fired', {'timer': timer['id'], 'project': timer['project_id'], 'message': ident})

    def recover_quota_waits(self):
        # Only explicit provider quota waits may auto-resume. Never replay failed/uncertain work.
        rows = self.hub.db.execute("SELECT DISTINCT w.body FROM workflows w JOIN workflow_steps s ON s.workflow=w.id JOIN executions e ON e.task_id=s.task WHERE e.status='waiting_quota' AND e.retry_after<=?", (time.time(),)).fetchall()
        for row in rows:
            w = json.loads(row[0])
            if w['status'] not in ('paused', 'waiting_quota', 'blocked') or w.get('pause_reason') != 'quota': continue
            from .project_activity import owner
            active_project=owner(self.hub)
            if active_project and active_project!=w.get('project_id'):continue
            try: self.server.workflows.valid({**w, 'status': 'active'})
            except HubError: continue
            with self.hub.tx():
                w.update(status='active', pause_reason=None)
                self.hub.db.execute('UPDATE workflows SET body=? WHERE id=?', (json.dumps(w, ensure_ascii=False), w['id']))
            self.server.workflows.enqueue(w, 'quota-resume:' + uid(), {'type': 'quota_resume', 'body': '预计额度恢复时间已到，平台继续等待额度的原执行；请核查后续，不重复派工。'})

    def project_vm(self, actor, run_id, **args):
        from .vm_bridge import VmBridge
        with self.server.workflows.lock:
            from .user_followup import direct,context
            with self.hub.lock:row=self.hub.db.execute('SELECT * FROM executions WHERE id=?',(run_id,)).fetchone()
            candidate=dict(row) if row else {}
            if candidate.get('agent')==actor and candidate.get('status')=='running' and candidate.get('purpose')=='alignment':
                from .long_term_memory import project,is_manager
                from .project_activity import require_available
                ident=project(self.hub,candidate)
                if not ident or not is_manager(self.hub,candidate):raise HubError('需求对齐虚拟机工具仅供当前项目经理使用')
                require_available(self.hub,ident)
                self.server.projects.get(ident)
                rt=self.server.workflows.runtime(actor)
                rt.guard(candidate)
                w,run={'id':ident,'project_id':ident},candidate
            elif candidate.get('agent')==actor and candidate.get('status')=='running' and direct(self.hub,candidate):
                rt=self.server.workflows.runtime(actor)
                rt.check_latch(candidate)
                if hasattr(rt,'guard'):rt.guard(candidate)
                w,run=context(self.hub,candidate),candidate
            else:
                w, run = self.server.workflows.run_context(actor, run_id)
            if (run.get('step_kind') == 'check' or run.get('_read_only')) and args.get('action', 'status') not in ('status','desktop_status','screenshot','windows','ui_tree'):
                raise HubError('只读核查轮次不能启动虚拟机操作；请经理安排执行者')
            result = VmBridge(self.hub.directory).call(w.get('project_id') or w['id'], actor, run['cwd'], **args)
            with self.hub.tx():
                self.hub.audit(actor, 'vm.' + args.get('action', 'status'), {'run': run_id, 'request': result.get('request_id')})
            return result

    def browser_render(self,actor,run_id,path,width=1280,height=800):
        try:
            from .browser_render import render
            return render(self,actor,run_id,path,width,height)
        except HubError:raise
        except Exception as error:
            import traceback
            detail=type(error).__name__+': '+str(error)
            secrets=list(getattr(self.hub,'tokens',{}).values())+[v for k,v in os.environ.items() if any(x in k.upper() for x in ('API_KEY','TOKEN','SECRET','PASSWORD')) and len(v)>5]
            for secret in secrets:
                if isinstance(secret,str) and secret:detail=detail.replace(secret,'[已隐藏]')
            incident=uid()
            frames=[{'file':Path(f.filename).name,'line':f.lineno,'function':f.name} for f in traceback.extract_tb(error.__traceback__)]
            with self.hub.tx():self.hub.audit(actor,'browser.render_internal_error',{'incident':incident,'run_id':run_id,'detail':detail[:2000],'frames':frames})
            raise HubError('浏览器截图服务错误：'+detail[:1000]+'；诊断编号 '+incident) from None

    def publish_folder(self,actor,w,run,path,caption):
        if caption:text(caption,20000)
        root=Path(run['cwd']).resolve();source=(root/path).resolve()
        roots=[root]
        if getattr(self.hub,'projects',None) and w.get('project_id'):
            roots.append(Path(self.hub.projects.get(w['project_id'])['cwd']).resolve())
        if not source.is_dir() or not any(source.is_relative_to(r) for r in roots):raise HubError('请选择本项目目录内的文件夹')
        ident=uid()+uid()
        item={'id':ident,'project_id':w.get('project_id') or w['id'],'sender':actor,'kind':'folder','caption':caption or source.name,'created':time.time(),'workflow_id':w['id'],'entry':source.name,'path':str(source),'folder_roots':[str(r) for r in roots],'url':'/api/folder/'+ident}
        with self.hub.tx():
            self.hub.db.execute('INSERT INTO shared_artifacts VALUES(?,?)',(ident,json.dumps(item,ensure_ascii=False)))
            self.hub.audit(actor,'artifact.folder_shared',{'project':item['project_id'],'artifact':ident})
        return item

    def open_folder(self,actor,artifact_id):
        self.hub.require(actor,{'user'})
        with self.hub.lock:row=self.hub.db.execute('SELECT body FROM shared_artifacts WHERE id=?',(artifact_id,)).fetchone()
        item=json.loads(row[0]) if row else {}
        if item.get('kind')!='folder' or not Path(item.get('path','')).is_dir():raise HubError('文件夹不存在或链接无效')
        target=Path(item['path']).resolve()
        if not any(target.is_relative_to(Path(root)) for root in item.get('folder_roots',[])):raise HubError('文件夹位置已变化，请重新分享')
        from .platform_paths import open_directory
        open_directory(target)
        return {'opened':True}

    def publish_artifact(self, actor, run_id, path, kind='image', caption=''):
        with self.server.workflows.lock:
            w, run = self.server.workflows.run_context(actor, run_id)
            if kind=='folder':return self.publish_folder(actor,w,run,path,caption)
            if kind not in ('image', 'webpage'): raise HubError('仅支持图片、静态网页或文件夹')
            if caption: text(caption, 20000)
            root = Path(run['cwd']).resolve(); source = (root / path).resolve()
            if not source.is_relative_to(root) or not source.is_file(): raise HubError('请选择本次项目目录中的产物文件')
            if source.stat().st_size>30*1024*1024:raise HubError('展示文件超过30MB')
            images = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}
            if source.suffix.lower() not in (images if kind == 'image' else {'.html', '.htm'}): raise HubError('文件类型与展示方式不符')
            if kind=='webpage' and w.get('design_review'):
                with self.hub.tx():self.hub.audit(actor,'artifact.routed_to_design',{'project':w.get('project_id') or w['id'],'design':w['design_review'],'entry':source.name})
                return {'published':False,'handled':True,'presentation':'design_review','design_id':w['design_review'],'message':'产品演示页面统一通过 manifest.json 和 project_complete 提交到“查看演示与批注”，无需逐页发送网页卡片。'}
            ident = uid() + uid(); folder = self.root / ident; folder.mkdir()
            try:
                if kind == 'image': shutil.copyfile(source, folder / source.name)
                else:
                    # Copy static siblings, never source code, credentials, or arbitrary project files.
                    allowed = images | {'.html', '.htm', '.css', '.woff', '.woff2'}
                    total = 0
                    for asset in source.parent.rglob('*'):
                        if not asset.is_file() or asset.suffix.lower() not in allowed: continue
                        if asset.resolve().is_relative_to(self.root.resolve()):continue
                        if not asset.resolve().is_relative_to(root): continue
                        total += asset.stat().st_size
                        if total > 30 * 1024 * 1024: raise HubError('静态预览资源超过30MB，请将需要展示的页面放在独立产物目录')
                        dest = folder / asset.relative_to(source.parent); dest.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(asset, dest)
                item = {'id': ident, 'project_id': w.get('project_id') or w['id'], 'sender': actor, 'kind': kind, 'caption': caption, 'created': time.time(), 'workflow_id':w['id'],'entry': source.name, 'url': '/api/shared/' + ident + '/' + quote(source.name)}
                with self.hub.tx():
                    self.hub.db.execute('INSERT INTO shared_artifacts VALUES(?,?)', (ident, json.dumps(item, ensure_ascii=False)))
                    self.hub.audit(actor, 'artifact.published', {'project': item['project_id'], 'artifact': ident, 'kind': kind})
                return item
            except Exception:
                resolved=folder.resolve()
                if not resolved.is_relative_to(self.root.resolve()) or resolved==self.root.resolve():raise HubError('展示清理路径无效')
                shutil.rmtree(resolved)
                raise

    def notifications(self,project_id):
        """Read-only user view: inspecting the queue must never wake a model."""
        if not project_id:return []
        result=[];seen=set();changes=self.server.integrations.changes(project_id)
        if changes:
            result.append({'id':'config:'+project_id,'source':'平台','recipient':'当前经理','body':self.server.integrations.change_text(changes),'state':'pending','created':min(x['first_at'] for x in changes),'category':'配置变更（已合并）'})
        with self.hub.lock:
            rows=self.hub.db.execute("SELECT e.id,e.body,e.status,e.created,w.body workflow FROM workflow_events e JOIN workflows w ON w.id=e.workflow WHERE json_extract(w.body,'$.project_id')=? AND e.status IN ('pending','claimed') AND json_extract(w.body,'$.status') NOT IN ('completed','cancelled','failed') ORDER BY e.created",(project_id,)).fetchall()
            for row in rows:
                event=json.loads(row['body']);workflow=json.loads(row['workflow']);ident=event.get('message_id')
                message=self.hub.db.execute('SELECT sender,recipient,body FROM messages WHERE id=?',(ident,)).fetchone() if ident else None
                if ident in seen:continue
                if ident:seen.add(ident)
                body=message['body'] if message else event.get('body') or event.get('summary') or json.dumps(event,ensure_ascii=False)
                result.append({'id':row['id'],'source':message['sender'] if message else event.get('from') or event.get('agent') or '平台','recipient':message['recipient'] if message else project_manager(self.hub,record=workflow),'body':body,'state':'processing' if row['status']=='claimed' else 'pending','created':row['created'],'category':event.get('type','通知')})
            legacy=self.hub.db.execute('SELECT * FROM agent_effort_notices WHERE project_id=? AND delivered IS NULL',(project_id,)).fetchall()
            for row in legacy:
                if row['message_id'] in seen:continue
                result.append({'id':row['message_id'],'source':'平台','recipient':row['recipient'],'body':row['body'],'state':'pending','created':0,'category':'档位通知'})
        return sorted(result,key=lambda row:row['created'])

    def artifacts(self, project_id):
        with self.hub.lock:
            return [json.loads(r[0]) for r in self.hub.db.execute("SELECT body FROM shared_artifacts WHERE json_extract(body,'$.project_id')=? ORDER BY rowid", (project_id,))]

    def asset(self, ident, relative):
        with self.hub.lock:
            if not self.hub.db.execute('SELECT 1 FROM shared_artifacts WHERE id=?', (ident,)).fetchone(): raise HubError('展示不存在')
        root = (self.root / ident).resolve(); path = (root / relative).resolve()
        if not path.is_relative_to(root) or not path.is_file(): raise HubError('展示文件不存在')
        return path.read_bytes(), mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
