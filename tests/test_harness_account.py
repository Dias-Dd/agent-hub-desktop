import importlib
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from module_fixture import implementation
import test_nine_deepseek as base


class Account(unittest.TestCase):
    def setUp(self):
        self.fixture = base.NineDeepSeek(); self.fixture.setUp()
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

    def test_native_api_credential_uses_official_route_without_exporting_key(self):
        runtime=SimpleNamespace(config=lambda:{},key=lambda:self.fail('Native key must stay inside Harness'))
        with patch.object(self.account,'inspect',return_value={'status':'signed-out','api_key_configured':True}):
            provider,store,env=self.account.auth(runtime)
        self.assertEqual(provider,'deepseek-official');self.assertEqual(env,{})
        rows=[__import__('json').loads(x[2:]) for x in self.runtime.patch_text('test','manager',provider=provider,credentials_path=store).splitlines()]
        self.assertIn({'id':'credentials','config':{'path':str(store)}},rows)

    def test_api_status_is_ready_without_account_login(self):
        adapter=importlib.import_module(self.runtime.__package__+'.adapter')
        registry=SimpleNamespace(server=SimpleNamespace(deepseek=object()))
        with patch.object(self.account,'inspect',return_value={'status':'signed-out','api_key_configured':True}):
            self.assertEqual(adapter.setup_status(registry,{})['state'],'ready')

    def test_native_api_balance_is_distinct_from_account_balance(self):
        registry=SimpleNamespace(server=SimpleNamespace(deepseek=object()))
        with patch.object(self.account,'inspect',return_value={'status':'signed-out','api_key_configured':True,'api_balance':[{'amount':'12.5','currency':'CNY'}]}):
            value=self.account.quota(registry,{})
        self.assertEqual(value['balance_source'],'deepseek-api')
        self.assertEqual(value['official_balance'][0]['amount'],'12.5')

    def test_existing_account_route_is_preserved_when_api_key_also_exists(self):
        runtime=SimpleNamespace(config=lambda:{},key=lambda:self.fail('Must reuse account'))
        with patch.object(self.account,'inspect',return_value={'status':'credential-stored','api_key_configured':True}):
            provider,store,env=self.account.auth(runtime)
        self.assertEqual(provider,'deepseek-account');self.assertEqual(env,{})
        rows=[__import__('json').loads(x[2:]) for x in self.runtime.patch_text('test','manager',provider='deepseek-official',credentials_path=store).splitlines()]
        self.assertIn({'id':'llm-deepseek-account','disabled':False},rows)
