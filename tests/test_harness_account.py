import importlib
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from module_fixture import implementation
from test_nine_deepseek import NineDeepSeek


class Account(unittest.TestCase):
    def setUp(self):
        self.fixture = NineDeepSeek(); self.fixture.setUp()
        self.runtime = implementation(self.fixture.h, 'deepseek-harness')
        self.account = importlib.import_module(self.runtime.__package__ + '.account')

    def tearDown(self):
        self.fixture.tearDown()

    def test_account_auth_never_requests_an_api_key(self):
        runtime = SimpleNamespace(config=lambda: {}, key=lambda: self.fail('Account route read API key'))
        with patch.object(self.account, 'inspect', return_value={'status':'credential-stored'}):
            provider, store, env = self.account.auth(runtime)
        self.assertEqual(provider, 'deepseek-account'); self.assertEqual(env, {})
        rows = [__import__('json').loads(x[2:]) for x in self.runtime.patch_text('test','manager',provider=provider, credentials_path=store).splitlines() if x.startswith('- ')]
        self.assertEqual(next(x for x in rows if x.get('id')=='acp')['config']['provider'], provider)
        self.assertIn({'id':'credentials','config':{'path':str(store)}}, rows)

    def test_balances_keep_recharge_and_bonus_separate(self):
        registry = SimpleNamespace(server=SimpleNamespace(deepseek=object()))
        observation = {'status':'credential-stored','balance':{'status':'ready','value':[{'currency':'CNY','balance':'12.34'}],'bonusWallets':[{'currency':'CNY','balance':'5.00'}]}}
        with patch.object(self.account,'inspect',return_value=observation):
            result = self.account.quota(registry,{'id':'dsh','kind':'deepseek-harness'})
        self.assertEqual(result['balance_source'],'dsh-account')
        self.assertEqual([x['amount'] for x in result['official_balance']],['12.34','5.00'])
        self.assertNotEqual(result['official_balance'][0]['name'],result['official_balance'][1]['name'])

    def test_failed_refresh_does_not_mutate_saved_balance(self):
        from hub.core import HubError
        connection = {'official_balance':[{'amount':'old'}]}
        registry = SimpleNamespace(server=SimpleNamespace(deepseek=object()))
        with patch.object(self.account,'inspect',return_value={'status':'credential-stored','balance':{'status':'failed'}}):
            with self.assertRaises(HubError): self.account.quota(registry,connection)
        self.assertEqual(connection['official_balance'],[{'amount':'old'}])
