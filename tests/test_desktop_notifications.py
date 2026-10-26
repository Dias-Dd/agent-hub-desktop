import queue,tempfile,unittest
from pathlib import Path
from hub.core import Hub
from hub.desktop_notifications import enqueue
from desktop.tray_status import StatusCache,read_status


class Notifications(unittest.TestCase):
    def test_completion_events_commit_deduplicate_and_are_readonly(self):
        with tempfile.TemporaryDirectory() as folder:
            h=Hub(folder,recover=False)
            h.db.execute('CREATE TABLE hub_projects(id TEXT,name TEXT)')
            h.db.execute("INSERT INTO hub_projects VALUES('p','Original name')")
            with h.tx():
                enqueue(h,'demo:d:1','demo','p');enqueue(h,'demo:d:1','demo','p');enqueue(h,'project:w','project','p')
            path=Path(folder)/'hub.sqlite3';before=path.stat().st_mtime_ns
            status=read_status(Path(folder));self.assertEqual(len(status['completions']),2)
            self.assertEqual({x['name'] for x in status['completions']},{'Original name'})
            self.assertEqual(path.stat().st_mtime_ns,before)
            try:
                with h.tx():enqueue(h,'rolled-back','demo','p');raise ValueError('rollback')
            except ValueError:pass
            self.assertFalse(h.db.execute("SELECT 1 FROM desktop_notifications WHERE id='rolled-back'").fetchone())
            h.db.close()

    def test_existing_completions_do_not_notify_and_new_versions_notify_once(self):
        cache=StatusCache.__new__(StatusCache);cache.seen=None;cache.notifications=queue.SimpleQueue()
        old={'id':'demo:d:1','kind':'demo','project':'p'}
        cache.observe([old]);self.assertTrue(cache.notifications.empty())
        new={'id':'demo:d:2','kind':'demo','project':'p'}
        done={'id':'project:w','kind':'project','project':'p'}
        cache.observe([old,new,done]);cache.observe([old,new,done])
        self.assertEqual(cache.notifications.get_nowait(),new);self.assertEqual(cache.notifications.get_nowait(),done)
        self.assertTrue(cache.notifications.empty())

    def test_only_published_review_and_completed_project_enqueue(self):
        from hub.designs import Designs
        from hub.workflows import Workflows
        with tempfile.TemporaryDirectory() as folder:
            h=Hub(folder,recover=False);h.db.execute('CREATE TABLE design_reviews(id TEXT PRIMARY KEY,body TEXT)');h.db.execute('CREATE TABLE workflows(id TEXT PRIMARY KEY,body TEXT)')
            d=Designs.__new__(Designs);d.hub=h
            d.save({'id':'d','project_id':'p','state':'building','versions':[]})
            self.assertFalse(h.db.execute("SELECT 1 FROM sqlite_master WHERE name='desktop_notifications'").fetchone())
            d.save({'id':'d','project_id':'p','state':'review','version':1,'versions':[{'version':1}]})
            d.save({'id':'d','project_id':'p','state':'review','version':1,'versions':[{'version':1}]})
            w=Workflows.__new__(Workflows);w.hub=h;w.save({'id':'w','project_id':'p','status':'active'});w.save({'id':'w','project_id':'p','status':'completed'})
            self.assertEqual(h.db.execute('SELECT count(*) FROM desktop_notifications').fetchone()[0],2);h.db.close()

    def test_attention_notifies_only_when_entering_a_problem_state(self):
        from hub.workflows import Workflows
        with tempfile.TemporaryDirectory() as folder:
            h=Hub(folder,recover=False)
            try:
                h.db.execute('CREATE TABLE workflows(id TEXT PRIMARY KEY,body TEXT)')
                w=Workflows.__new__(Workflows);w.hub=h
                value={'id':'w','project_id':'p','status':'active'};w.save(value)
                value['status']='blocked';w.save(value);w.save(value)
                self.assertEqual(h.db.execute("SELECT count(*) FROM desktop_notifications WHERE kind='attention'").fetchone()[0],1)
                value['status']='active';w.save(value);value['status']='needs_attention';w.save(value)
                self.assertEqual(h.db.execute("SELECT count(*) FROM desktop_notifications WHERE kind='attention'").fetchone()[0],2)
            finally:h.db.close()
