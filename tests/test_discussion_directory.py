import json
from pathlib import Path
import unittest
import test_nine_deepseek as fixtures
from hub.core import HubError
from hub.projects import Projects

class DiscussionDirectory(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.NineDeepSeek();self.fixture.setUp()
        self.h=self.fixture.h;self.runtime=self.fixture.d;self.planning=self.fixture.p
    def tearDown(self):self.fixture.tearDown()
    def test_new_project_discussion_and_format_repair_ignore_deleted_old_runtime_cwd(self):
        projects=Projects(self.h)
        previous=projects.create('user','old');old=Path(previous['cwd'])
        current=projects.create('user','current')
        cfg=self.runtime.config();cfg['cwd']=str(old)
        with self.h.tx():
            self.h.db.execute("UPDATE settings SET value=? WHERE key='deepseek_runtime'",(json.dumps(cfg),))
            self.h.db.execute('INSERT INTO settings VALUES(?,?)',('deleted_project:'+previous['id'],'true'))
        old.rmdir()
        discussion=self.planning.message('user','new project',{'agents':[]},project_id=current['id'])
        run=dict(self.h.db.execute('SELECT * FROM executions WHERE id=?',(discussion['pending'],)).fetchone())
        self.assertEqual(run['cwd'],current['cwd']);self.assertEqual(run['grant_id'],cfg['grant_id'])
        self.assertEqual(self.runtime.config()['cwd'],str(old));self.assertFalse(old.exists())
        self.h.db.execute("UPDATE executions SET status='completed' WHERE id=?",(run['id'],))
        self.assertTrue(self.planning.request_format_repair(discussion,run,HubError('invalid JSON')))
        repair=self.h.db.execute('SELECT cwd FROM executions WHERE id=?',(discussion['pending'],)).fetchone()
        self.assertEqual(repair['cwd'],run['cwd'])
    def test_missing_directory_is_rejected_before_a_run_is_queued(self):
        missing=str(Path(self.fixture.t.name)/'missing')
        before=self.h.db.execute('SELECT COUNT(*) FROM executions').fetchone()[0]
        with self.assertRaisesRegex(HubError,'项目工作目录'):
            self.planning.submit_discussion(self.runtime,'deepseek-4','hello','hub-project:new',missing)
        self.assertEqual(self.h.db.execute('SELECT COUNT(*) FROM executions').fetchone()[0],before)
    def test_file_is_not_accepted_as_a_working_directory(self):
        path=Path(self.fixture.t.name)/'file';path.write_text('not a directory')
        with self.assertRaisesRegex(HubError,'项目工作目录'):
            self.planning.submit_discussion(self.runtime,'deepseek-4','hello','hub-project:new',str(path))

    def test_direct_chat_uses_project_directory_not_last_runtime_default(self):
        projects=Projects(self.h)
        current=projects.create('user','current chat');other=projects.create('user','other chat')
        cfg=self.runtime.config();cfg['cwd']=other['cwd']
        with self.h.tx():self.h.db.execute("UPDATE settings SET value=? WHERE key='deepseek_runtime'",(json.dumps(cfg),))
        ids=self.fixture.co.send('user','deepseek-4','follow up',project_id=current['id'])
        run=self.h.db.execute('SELECT cwd,session_scope FROM executions WHERE message_id=?',(ids[0],)).fetchone()
        self.assertEqual(run['cwd'],current['cwd']);self.assertEqual(run['session_scope'],'chat:'+current['id'])
        self.assertEqual(self.runtime.config()['cwd'],other['cwd'])
    def test_discussion_inbox_is_not_claimed_by_generic_wakeup(self):
        from hub.manager_inbox import ManagerInbox
        projects=Projects(self.h);project=projects.create('user','chat')
        inbox=ManagerInbox(self.h,self.planning,self.fixture.w,self.fixture.co)
        discussion=self.planning.message('user','hello',{'agents':[]},project_id=project['id'])
        queued=inbox.send('user',discussion['id'],'next question')
        message=queued['message_ids'][0]
        self.fixture.co.route(message)
        self.assertIsNone(self.h.db.execute('SELECT id FROM executions WHERE message_id=?',(message,)).fetchone())
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='completed',result='hello back' WHERE id=?",(discussion['pending'],))
        self.planning.patrol();inbox.patrol();self.fixture.co.patrol()
        claimed=self.h.db.execute('SELECT run_id FROM manager_discussion_inputs WHERE message_id=?',(message,)).fetchone()[0]
        self.assertIsNotNone(claimed)
        run=self.h.db.execute('SELECT cwd,purpose FROM executions WHERE id=?',(claimed,)).fetchone()
        self.assertEqual(run['cwd'],project['cwd']);self.assertEqual(run['purpose'],'alignment')
        self.assertIsNone(self.h.db.execute('SELECT id FROM executions WHERE message_id=?',(message,)).fetchone())

    def test_workflow_task_and_demo_bind_directory_before_worker_pickup(self):
        projects=Projects(self.h);project=projects.create('user','workflow');other=projects.create('user','unrelated')
        w=self.fixture.w.start('user','scope',[],confirmed=True,project_id=project['id'])
        w['cwd']=project['cwd'];self.fixture.w.save(w)
        step=self.fixture.w.steps(w['id'])[0]
        cfg=self.runtime.config();cfg['cwd']=other['cwd']
        with self.h.tx():self.h.db.execute("UPDATE settings SET value=? WHERE key='deepseek_runtime'",(json.dumps(cfg),))
        title=self.h.db.execute('SELECT title FROM tasks WHERE id=?',(step['task'],)).fetchone()[0]
        job=self.runtime.submit('user',step['agent'],title,True,task_id=step['task'])
        self.assertEqual(self.h.db.execute('SELECT cwd FROM executions WHERE id=?',(job['id'],)).fetchone()[0],project['cwd'])
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='completed' WHERE id=?",(job['id'],))
        demo=Path(project['cwd'])/'.hub-design'/'draft';demo.mkdir(parents=True)
        w['design_dir']=str(demo);self.fixture.w.save(w)
        task=self.fixture.w.add_step(w,'deepseek-4','review','review demo')
        codex=self.fixture.c;codex.models={'deepseek-4':'gpt-6-luna'}
        codex.configure('user',other['cwd'],'workspace',0,600,True,True)
        job=codex.submit('user','deepseek-4','review demo',True,task_id=task)
        self.assertEqual(self.h.db.execute('SELECT cwd FROM executions WHERE id=?',(job['id'],)).fetchone()[0],str(demo))
    def test_unscoped_legacy_session_cannot_adopt_current_task_project(self):
        from hub.sessions import Sessions
        projects=Projects(self.h);project=projects.create('user','new project')
        w=self.fixture.w.start('user','scope',[],confirmed=True,project_id=project['id'])
        step=self.fixture.w.steps(w['id'])[0]
        run={'id':'new','agent':'deepseek-4','provider':'legacy-provider','model':'model','task_id':step['task'],'cwd':project['cwd'],'permission':'full','grant_id':'grant','purpose':'task','session_scope':None}
        with self.h.tx():self.h.db.execute('INSERT INTO agent_sessions VALUES(?,?,?,?,?,?,?)',('legacy-key',None,run['provider'],run['agent'],'unrelated-session','completed',9999999999))
        self.assertIsNone(Sessions(self.h).get(run))

    def test_missing_workflow_scope_never_falls_back_to_another_directory(self):
        from hub.module_sdk import execution_directory
        with self.assertRaisesRegex(HubError,'原项目执行流程不存在'):
            execution_directory(self.h,{'session_scope':'project:removed'},self.fixture.t.name)

    def test_direct_workflow_start_binds_selected_project_not_provider_default(self):
        projects=Projects(self.h);project=projects.create('user','direct workflow')
        w=self.fixture.w.start('user','work',[],confirmed=True,project_id=project['id'])
        self.assertEqual(w['cwd'],project['cwd'])
        step=self.fixture.w.steps(w['id'])[0]
        title=self.h.db.execute('SELECT title FROM tasks WHERE id=?',(step['task'],)).fetchone()[0]
        job=self.runtime.submit('user',step['agent'],title,True,task_id=step['task'])
        self.assertEqual(self.h.db.execute('SELECT cwd FROM executions WHERE id=?',(job['id'],)).fetchone()[0],project['cwd'])
