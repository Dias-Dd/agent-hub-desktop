import json,time,unittest
from unittest.mock import patch
import test_designs as fixtures
from hub.core import HubError
from hub.projects import Projects
from hub.manager_inbox import ManagerInbox

class AuditFixes(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.DesignFlow();self.f.setUp()
        self.h=self.f.h;self.p=self.f.p;self.w=self.f.w
        self.projects=Projects(self.h)
        with self.h.tx():self.h.db.execute('INSERT INTO hub_projects VALUES(?,?,?,?)',('p','project',self.f.t.name,time.time()))
        self.inbox=ManagerInbox(self.h,self.p,self.w,self.f.co)
    def tearDown(self):self.f.tearDown()
    def test_archived_discussion_queue_never_reopens_or_starts_model(self):
        s=self.p.message('user','hello',{'agents':[]},project_id='p')
        queued=self.inbox.send('user',s['id'],'queued question')['message_ids'][0]
        s.update(state='archived',pending=None,superseded_by='new-round');self.p.save(s)
        with patch.object(self.f.d,'submit') as submit:
            self.inbox.patrol();submit.assert_not_called()
        self.assertEqual(self.h.db.execute('SELECT status FROM messages WHERE id=?',(queued,)).fetchone()[0],'cancelled')
        for operation in (lambda:self.inbox.send('user',s['id'],'stale'),lambda:self.p.message('user','stale',session_id=s['id'])):
            with self.assertRaises(HubError):operation()
    def test_removed_runtime_returns_actionable_error(self):
        w={'status':'active','expires':time.time()+60,'grants':{'integration:removed':'old-grant'}}
        with self.assertRaisesRegex(HubError,'接入已被移除'):self.w.valid(w)
    def test_active_round_outside_snapshot_still_blocks_and_can_be_superseded(self):
        original=self.w.start('user','first round',[],confirmed=True,project_id='p')
        for i in range(25):self.w.save({**original,'id':'history-'+str(i),'status':'completed'})
        self.assertNotIn(original['id'],[w['id'] for w in self.w.snapshot('user')])
        with self.assertRaisesRegex(HubError,'先结束'):self.w.start('user','second round',[],confirmed=True,project_id='p')
        s=self.f.plan('skip')
        self.p.supersede_rounds(s)
        old=json.loads(self.h.db.execute('SELECT body FROM workflows WHERE id=?',(original['id'],)).fetchone()[0])
        self.assertEqual(old['status'],'stopped');self.assertEqual(old['superseded_by'],s['id'])
    def test_all_previous_discussions_archived_beyond_snapshot_limit(self):
        saved=[]
        for i in range(13):
            s=self.p.message('user','hello '+str(i),{'agents':[]},project_id='p');s.update(pending=None,state='chatting');self.p.save(s);saved.append(s['id'])
        self.p.supersede_rounds(s)
        self.assertTrue(all(self.p.get(i)['state']=='archived' for i in saved[:-1]))

    def test_superseding_discussion_cancels_prior_pending_execution(self):
        s=self.p.message('user','old question',{'agents':[]},project_id='p')
        newer={**s,'id':'new-discussion','pending':None};self.p.save(newer)
        self.p.supersede_rounds(newer)
        self.assertIsNone(self.p.get(s['id'])['pending'])
        self.assertEqual(self.h.db.execute('SELECT status FROM executions WHERE id=?',(s['pending'],)).fetchone()[0],'cancelled')

    def test_stop_requested_blocks_native_mcp_before_worker_acknowledges(self):
        s,d=self.f.start()
        step=self.w.steps(d['workflow_id'])[0]
        title=self.h.db.execute('SELECT title FROM tasks WHERE id=?',(step['task'],)).fetchone()[0]
        job=self.f.d.submit('user',step['agent'],title,True,task_id=step['task'])
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='running',started=?,stop_requested=1 WHERE id=?",(time.time(),job['id']))
        with self.assertRaisesRegex(HubError,'请求停止'):self.w.run_context(step['agent'],job['id'])
    def test_missing_directory_does_not_stop_current_round_on_approval(self):
        w=self.w.start('user','current',[],confirmed=True,project_id='p')
        s=self.f.plan('skip');s['options']['cwd']=self.f.t.name+'/gone';self.p.save(s)
        with self.assertRaisesRegex(HubError,'工作目录'):self.p.approve(s,s['revision'],None)
        old=json.loads(self.h.db.execute('SELECT body FROM workflows WHERE id=?',(w['id'],)).fetchone()[0])
        self.assertEqual(old['status'],'active')

    def test_mcp_bridge_carries_run_and_server_rejects_stopping_turn(self):
        import threading,os
        from hub.server import Server,Handler
        from hub.mcp import call
        job=self.f.d.submit('user','deepseek-4','test',True,purpose='task',session_scope='chat:p')
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='running',started=? WHERE id=?",(time.time(),job['id']))
        server=Server(('127.0.0.1',0),Handler);server.hub=self.h;server.workflows=self.w;server.projects=self.projects
        thread=threading.Thread(target=server.serve_forever);thread.start()
        try:
            with patch.dict(os.environ,{'HUB_URL':'http://127.0.0.1:'+str(server.server_port),'HUB_TOKEN':self.h.tokens['deepseek-4'],'HUB_RUN_ID':job['id']}):
                call('heartbeat',{'status':'busy'})
                with self.h.tx():self.h.db.execute('UPDATE executions SET stop_requested=1 WHERE id=?',(job['id'],))
                with self.assertRaisesRegex(ValueError,'停止'):call('heartbeat',{'status':'idle'})
        finally:server.shutdown();server.server_close();thread.join()

    def test_missing_pending_execution_becomes_visible_error_without_replay(self):
        s=self.p.message('user','hello',{'agents':[]},project_id='p')
        with self.h.tx():self.h.db.execute('DELETE FROM executions WHERE id=?',(s['pending'],))
        with patch.object(self.f.d,'submit') as submit:
            self.p.patrol();submit.assert_not_called()
        current=self.p.get(s['id']);self.assertIsNone(current['pending']);self.assertEqual(current['state'],'error')
        self.assertIn('执行记录不存在',current['error'])

    def test_pending_discussion_outside_history_page_still_settles(self):
        s=self.p.message('user','old question',{'agents':[]},project_id='p')
        for i in range(13):self.p.save({**s,'id':'new-history-'+str(i),'pending':None,'state':'chatting'})
        self.assertNotIn(s['id'],[x['id'] for x in self.p.snapshot('user')])
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='completed',result='answer' WHERE id=?",(s['pending'],))
        self.p.patrol()
        current=self.p.get(s['id']);self.assertIsNone(current['pending']);self.assertEqual(current['history'][-1]['text'],'answer')

    def test_active_workflow_outside_history_page_is_patrolled_and_halted(self):
        w=self.w.start('user','active round',[],confirmed=True,project_id='p')
        for i in range(23):self.w.save({**w,'id':'finished-history-'+str(i),'status':'completed'})
        with patch.object(self.w,'advance') as advance:
            self.w.patrol();advance.assert_called_once();self.assertEqual(advance.call_args.args[0]['id'],w['id'])
        self.f.co.halt('user')
        self.assertEqual(self.w.records('p',statuses=('active','needs_attention')),[])

    def test_project_delete_archives_discussions_and_cancels_queued_input(self):
        from hub.automation import Automation
        from types import SimpleNamespace
        Automation(SimpleNamespace(hub=self.h))
        s=self.p.message('user','hello',{'agents':[]},project_id='p')
        queued=self.inbox.send('user',s['id'],'queued question',project_id='p')['message_ids'][0]
        self.projects.delete('user','p');self.inbox.patrol()
        self.assertEqual(self.p.get(s['id'])['state'],'archived')
        self.assertEqual(self.h.db.execute('SELECT status FROM messages WHERE id=?',(queued,)).fetchone()[0],'cancelled')

    def test_project_delete_stops_direct_chat_and_preserves_completed_history(self):
        from hub.automation import Automation
        from types import SimpleNamespace
        Automation(SimpleNamespace(hub=self.h))
        w=self.w.start('user','past work',[],confirmed=True,project_id='p');w['status']='completed';self.w.save(w)
        job=self.f.d.submit('user','deepseek-4','follow up',True,purpose='task',session_scope='project:'+w['id'])
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='running',started=? WHERE id=?",(time.time(),job['id']))
        self.projects.delete('user','p')
        self.assertEqual(self.h.db.execute('SELECT stop_requested FROM executions WHERE id=?',(job['id'],)).fetchone()[0],1)
        self.assertEqual(json.loads(self.h.db.execute('SELECT body FROM workflows WHERE id=?',(w['id'],)).fetchone()[0])['status'],'completed')

    def test_removed_module_run_can_be_stopped_and_does_not_break_patrol(self):
        w=self.w.start('user','past work',[],confirmed=True,project_id='p');step=self.w.steps(w['id'])[0]
        title=self.h.db.execute('SELECT title FROM tasks WHERE id=?',(step['task'],)).fetchone()[0]
        job=self.f.d.submit('user',step['agent'],title,True,task_id=step['task'])
        w['grants']={'integration:removed':'grant'};self.w.save(w)
        with self.h.tx():self.h.db.execute("UPDATE executions SET provider='integration:removed',status='running',started=? WHERE id=?",(time.time(),job['id']))
        self.w.patrol()
        self.assertEqual(self.h.db.execute('SELECT status FROM executions WHERE id=?',(job['id'],)).fetchone()[0],'interrupted')
        stored=json.loads(self.h.db.execute('SELECT body FROM workflows WHERE id=?',(w['id'],)).fetchone()[0]);self.assertEqual(stored['status'],'blocked')

    def test_mutable_module_run_cannot_extend_durable_time_budget(self):
        from hub.module_tools import guard
        job=self.f.d.submit('user','deepseek-4','test',True,purpose='alignment',session_scope='hub-project:p')
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='running',started=?,max_seconds=1 WHERE id=?",(time.time()-5,job['id']))
        run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(job['id'],)).fetchone())
        run.update(started=time.time(),max_seconds=999999)
        with self.assertRaisesRegex(HubError,'时间预算'):guard(self.f.d,run)
        with self.h.tx():self.h.db.execute('UPDATE executions SET started=NULL WHERE id=?',(job['id'],))
        with self.assertRaisesRegex(HubError,'尚未确认启动'):guard(self.f.d,run)
