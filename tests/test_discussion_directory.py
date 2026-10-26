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
