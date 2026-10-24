import unittest
from desktop.ui_recovery import RecoveryPolicy
class Recovery(unittest.TestCase):
 def test_blank_must_repeat_and_healthy_page_resets_it(self):
  p=RecoveryPolicy();self.assertFalse(p.observe(False));self.assertTrue(p.observe(False));self.assertFalse(p.observe(True));self.assertFalse(p.observe(False))
 def test_cooldown_and_three_attempt_limit(self):
  p=RecoveryPolicy();self.assertTrue(p.allow(100));self.assertFalse(p.allow(101));self.assertTrue(p.allow(120));self.assertTrue(p.allow(140));self.assertFalse(p.allow(200));self.assertTrue(p.allow(500))
 def test_manual_retry_is_available_after_auto_limit(self):
  p=RecoveryPolicy()
  for now in [100,120,140]:p.allow(now)
  self.assertFalse(p.allow(200));self.assertTrue(p.allow(201,manual=True))
 def test_long_run_keeps_only_bounded_history(self):
  p=RecoveryPolicy()
  for now in range(100000):p.allow(now)
  self.assertLessEqual(len(p.attempts),3)
