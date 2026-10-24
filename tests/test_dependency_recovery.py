import unittest,json
from unittest.mock import patch
import test_manager_owned_review as base
class Recovery(base.ManagerOwnedReview):
 def test_failed_dependency_notifies_once(self):
  w,steps=self.workflow('uncertain')
  steps.append({'task':'later','agent':'deepseek-3','kind':'check','run_id':'later-run','status':'queued','depends_on':'t'})
  self.w.notify_dependency_blocks(w,steps);self.w.notify_dependency_blocks(w,steps)
  rows=self.h.db.execute('select body from workflow_events where workflow=?',(w['id'],)).fetchall()
  self.assertEqual(len(rows),1);event=json.loads(rows[0][0]);self.assertEqual(event['task_id'],'later');self.assertEqual(event['dependency_status'],'uncertain')
  self.assertEqual(steps[-1]['status'],'queued')
 def test_running_dependency_does_not_warn(self):
  w,steps=self.workflow('running');steps.append({'task':'later','status':'queued','depends_on':'t'})
  self.w.notify_dependency_blocks(w,steps)
  self.assertEqual(self.h.db.execute('select count(*) from workflow_events').fetchone()[0],0)
