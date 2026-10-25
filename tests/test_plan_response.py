import json
import unittest
from hub.plan_response import decode
from hub.core import HubError


class Decode(unittest.TestCase):
    def test_empty_valueless_members_only(self):
        raw='{"done":false,"report":"scope","tasks":[{"agent":"a","instruction":"work",""},{"agent":"b","", "instruction":"check"}]}'
        data,count=decode(raw)
        self.assertEqual(count,2)
        self.assertEqual(data['tasks'],[{'agent':'a','instruction':'work'},{'agent':'b','instruction':'check'}])

    def test_report_text_and_valid_empty_keys_are_untouched(self):
        data={'report':'literal ,""} and braces {}', '': 'actual value'}
        self.assertEqual(decode(json.dumps(data)),(data,0))

    def test_nonempty_valueless_keys_and_other_errors_fail(self):
        for raw in ['{"a":1,"meaningful"}', '{"a":"unfinished}', '{"a":1,}', '{"a":1,"":}', '{"a":1'+',""'*9+'}']:
            with self.subTest(raw=raw),self.assertRaises(ValueError):decode(raw)


class Recovery(unittest.TestCase):
    def setUp(self):
        from test_manager_owned_plan import ManagerOwnedPlan
        self.fixture=ManagerOwnedPlan();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        self.h=self.fixture.h;self.p=self.fixture.p;self.w=self.fixture.w

    def test_recover_legacy_draft_without_inference_or_execution(self):
        session=self.fixture.plan()
        raw=json.dumps(session['plan']).replace('"instruction": "Build the hello page yourself"}', '"instruction": "Build the hello page yourself",""}')
        session.update(state='draft',plan=None,notice='已保留经理答复；尚无可审批的结构化计划，可继续讨论。')
        session['history'][-1]['text']=raw;self.p.save(session)
        run=session['last_run']
        with self.h.tx():self.h.db.execute('UPDATE executions SET result=? WHERE id=?',(raw,run))
        before=self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0]
        result=self.p.recover_result('user',session['id'])
        self.assertEqual(result['state'],'awaiting_approval')
        self.assertEqual(result['history'][-1]['text'],'Readable approved scope')
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0],before)
        self.assertEqual(self.h.db.execute('SELECT result FROM executions WHERE id=?',(run,)).fetchone()[0],raw)
        self.assertEqual(self.w.snapshot('user'),[])
        self.assertIn('原始回复保留',result['notice'])

    def test_unrecoverable_json_surfaces_error_and_preserves_raw(self):
        session=self.fixture.plan();run=session['last_run']
        raw='{"done":false,"tasks":[{"agent":"unterminated'
        session.update(state='thinking',pending=run,plan=None);session['history']=[];self.p.save(session)
        with self.h.tx():self.h.db.execute('UPDATE executions SET result=? WHERE id=?',(raw,run))
        self.p.patrol();result=self.p.get(session['id'])
        self.assertEqual(result['state'],'thinking');self.assertIn('已把错误反馈给经理',result['notice'])
        repair_run=result['pending']
        prompt=self.h.db.execute('SELECT prompt FROM executions WHERE id=?',(repair_run,)).fetchone()[0]
        self.assertIn('只修正上一份计划',prompt)
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='completed',result=? WHERE id=?",(raw,repair_run))
        count=self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0]
        self.p.patrol();result=self.p.get(session['id'])
        self.assertEqual(result['state'],'error');self.assertIn('计划格式无法读取',result['error'])
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM executions').fetchone()[0],count)
        self.assertEqual(result['history'][-1]['text'],raw);self.assertEqual(self.w.snapshot('user'),[])

    def test_corrected_manager_reply_waits_for_approval(self):
        session=self.fixture.plan();run=session['last_run'];valid=json.dumps(session['plan'])
        session.update(state='thinking',pending=run,plan=None);self.p.save(session)
        with self.h.tx():self.h.db.execute('UPDATE executions SET result=? WHERE id=?',('{"tasks":[',run))
        self.p.patrol();repair=self.p.get(session['id'])['pending']
        self.assertNotEqual(repair,run)
        with self.h.tx():self.h.db.execute("UPDATE executions SET status='completed',result=? WHERE id=?",(valid,repair))
        self.p.patrol();result=self.p.get(session['id'])
        self.assertEqual(result['state'],'awaiting_approval')
        self.assertEqual(self.w.snapshot('user'),[])
