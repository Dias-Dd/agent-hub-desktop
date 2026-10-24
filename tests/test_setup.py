import json
import tempfile
import unittest
from unittest.mock import patch
from hub.core import Hub, HubError
from hub.setup import Setup

class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.h=Hub(self.temp.name);self.setup=Setup(self.h,True)
    def tearDown(self):self.h.db.close();self.temp.cleanup()
    def test_status_never_exposes_environment_secret(self):
        with patch.dict('os.environ',{'DEEPSEEK_API_KEY':'never-send-this-secret','HUB_ALLOW_REAL':'0'}):
            result=self.setup.status('user')
        self.assertTrue(result['deepseek_key_present']);self.assertFalse(result['real_calls_enabled'])
        self.assertNotIn('never-send-this-secret',json.dumps(result))
        with self.assertRaises(HubError):self.setup.status('astra')
    def test_configuration_persists_without_model_authorization(self):
        with self.assertRaises(HubError):self.setup.save('user','demo','simulation',0)
        saved=self.setup.save('user','测试项目','deepseek',25,True)
        self.assertEqual(saved['project_name'],'测试项目')
        self.h.db.close();self.h=Hub(self.temp.name);self.setup=Setup(self.h,True)
        status=self.setup.status('user');self.assertEqual(status['saved']['route'],'deepseek');self.assertEqual(status['budget_cents'],25)
        self.assertEqual(self.h.db.execute('SELECT count(*) FROM calls').fetchone()[0],0)
    def test_permissions_and_invalid_config_do_not_save(self):
        for actor,name,route,budget in [('argon','demo','simulation',0),('user','','simulation',0),('user','demo','auto-real',0),('user','demo','simulation',-1),('user','demo','simulation',True)]:
            with self.assertRaises(HubError):self.setup.save(actor,name,route,budget,True)
        self.assertIsNone(self.setup.status('user')['saved'])
    def test_existing_reservations_cannot_be_overwritten_by_wizard(self):
        self.h.db.execute("INSERT INTO calls(id,status,reserve_cents) VALUES('existing','approved',5)")
        with self.assertRaises(HubError):self.setup.save('user','demo','simulation',0,True)
        self.assertIsNone(self.setup.status('user')['saved'])

if __name__=='__main__':unittest.main()
