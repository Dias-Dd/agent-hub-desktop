import unittest
from unittest.mock import patch
import test_designs as base
from hub.message_sources import repair_platform_sources
from hub.workflows import Workflows

class Sources(unittest.TestCase):
    def setUp(self):
        self.f=base.DesignFlow();self.f.setUp()
        self.h=self.f.h;self.w=self.f.w
        self.workflow={'id':'source-test','project_id':'p','manager':'deepseek-4','agents':['deepseek-1'],'status':'active'}
        self.w.save(self.workflow)
    def tearDown(self):self.f.tearDown()
    def prepare(self):return self.w.prepare_manager(self.workflow,[])
    def message(self,task):
        return self.h.db.execute('SELECT * FROM messages WHERE body LIKE ?',('[task:'+task+'] %',)).fetchone()
    def test_platform_notice_has_explicit_origin_in_prompt_and_database(self):
        self.w.enqueue(self.workflow,'notice',{'type':'review_needed','body':'成员执行已结束。请核查新产物与风险。'})
        task=self.prepare();message=self.message(task)
        self.assertEqual(message['sender'],'平台')
        self.assertIn('平台通知：成员执行已结束',message['body'])
        self.assertIn('平台通知：',self.w.manager_prompt(self.workflow,[],manager_task=task))
        instructions=self.f.d.execution_instructions({'id':'source-run','task_id':task,'agent':'deepseek-4','model':'deepseek-flash','message_id':message['id'],'purpose':'task'})
        self.assertIn('本轮消息发送者：平台',instructions)
        with self.h.tx():self.h.db.execute("INSERT INTO executions(id,task_id,message_id,agent,status) VALUES(?,?,?,?,'running')",('source-run',task,message['id'],'deepseek-4'))
        with patch.object(self.w,'run_context',return_value=(self.workflow,{'id':'source-run'})):
            mailbox=self.w.project_mailbox('deepseek-4','source-run')
        self.assertEqual(next(m['authority'] for m in mailbox['messages'] if m['id']==message['id']),'platform_notice')
    def test_human_message_stays_unmodified_and_human_authored(self):
        ident=self.h.send('user','deepseek-4','继续做下去')[0]
        self.w.enqueue(self.workflow,'human',{'type':'message','message_id':ident,'from':'user','body':'继续做下去'})
        task=self.prepare();message=self.message(task)
        self.assertEqual(message['sender'],'user')
        self.assertEqual(self.w.manager_prompt(self.workflow,[],manager_task=task),'继续做下去')
        self.assertEqual(repair_platform_sources(self.h),[])
        self.assertEqual(self.h.db.execute('SELECT sender FROM messages WHERE id=?',(ident,)).fetchone()[0],'user')
    def test_legacy_envelope_repair_is_idempotent_and_keeps_raw_input(self):
        self.w.enqueue(self.workflow,'notice',{'type':'review_needed','body':'成员执行已结束。'})
        task=self.prepare();message=self.message(task)
        with self.h.tx():self.h.db.execute("UPDATE messages SET sender='user' WHERE id=?",(message['id'],))
        with self.h.tx():self.h.db.execute("INSERT INTO executions(id,task_id,message_id,prompt,actual_input,status) VALUES(?,?,?,?,?,'completed')",('old-run',task,message['id'],'original input','original input'))
        self.assertIn(message['id'],repair_platform_sources(self.h))
        self.assertEqual(self.h.db.execute("SELECT actual_input FROM executions WHERE id='old-run'").fetchone()[0],'original input')
        self.assertEqual(self.message(task)['sender'],'平台')
        self.assertEqual(repair_platform_sources(self.h),[])
    def test_live_history_repair_skips_active_executions(self):
        self.w.enqueue(self.workflow,'notice',{'type':'review_needed','body':'核查产物'})
        task=self.prepare();message=self.message(task)
        with self.h.tx():
            self.h.db.execute("UPDATE messages SET sender='user' WHERE id=?",(message['id'],))
            self.h.db.execute("INSERT INTO executions(id,task_id,message_id,status) VALUES(?,?,?,'running')",('active-run',task,message['id']))
        self.assertEqual(repair_platform_sources(self.h,terminal_only=True),[])
        self.assertEqual(self.message(task)['sender'],'user')

    def test_mixed_and_member_messages_keep_their_real_sources(self):
        self.assertEqual(Workflows.manager_event_text([('1','deepseek-1','已完成')]),'deepseek-1：已完成')
        text=Workflows.manager_event_text([('1','user','继续'),('2','平台','成员已结束')])
        self.assertIn('user：继续',text);self.assertIn('平台通知：成员已结束',text)
    def test_completed_platform_notice_does_not_reply_to_fictitious_agent(self):
        self.w.enqueue(self.workflow,'notice',{'type':'review_needed','body':'核查产物'})
        task=self.prepare();message=self.message(task)
        run={'id':'source-run','task_id':task,'agent':'deepseek-4','message_id':message['id']}
        with patch.object(self.h,'send') as send:
            self.f.d.deliver_result(run,'completed','已核查')
        self.assertEqual(send.call_count,1)
        self.assertEqual(send.call_args.args[1],'user')

if __name__=='__main__':unittest.main()
