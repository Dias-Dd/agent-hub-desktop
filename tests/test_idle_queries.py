import unittest,tempfile
from hub.core import Hub
class IdleQueries(unittest.TestCase):
 def test_history_and_queue_use_indexes(self):
  with tempfile.TemporaryDirectory() as tmp:
   h=Hub(tmp)
   try:
    q1='SELECT * FROM messages ORDER BY created DESC LIMIT 300'
    q2="SELECT id FROM messages WHERE status='pending' AND recipient='deepseek-1'"
    plans=[' '.join(str(tuple(r)) for r in h.db.execute('EXPLAIN QUERY PLAN '+q)) for q in [q1,q2]]
    self.assertIn('messages_recent',plans[0]);self.assertNotIn('TEMP B-TREE',plans[0]);self.assertIn('messages_pending',plans[1])
   finally:h.db.close()
if __name__=='__main__':unittest.main()
