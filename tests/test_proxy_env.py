import unittest
from unittest.mock import patch
from hub.proxy_env import inherit_system_proxy,describe,bypass_values

class ProxyTests(unittest.TestCase):
    def test_single_windows_proxy_applies_only_to_child_copy(self):
        original={'PATH':'local'}
        env=inherit_system_proxy(original,{'enabled':True,'server':'127.0.0.1:7890','bypass':'localhost;127.*;*.local;<local>'})
        self.assertEqual(env['HTTPS_PROXY'],'http://127.0.0.1:7890');self.assertEqual(env['HTTP_PROXY'],env['HTTPS_PROXY'])
        self.assertIn('127.0.0.0/8',env['NO_PROXY']);self.assertNotIn('HTTPS_PROXY',original)
    def test_explicit_environment_is_not_overwritten(self):
        for key in ('HTTPS_PROXY','https_proxy','ALL_PROXY'):
            original={key:'http://explicit.example:3128'}
            self.assertEqual(inherit_system_proxy(original,{'enabled':True,'server':'127.0.0.1:7890'}),original)
    def test_protocol_specific_and_disabled_proxy(self):
        settings={'enabled':True,'server':'http=127.0.0.1:7890;https=127.0.0.1:7891;socks=127.0.0.1:7892'}
        env=inherit_system_proxy({},settings);self.assertEqual(env['HTTPS_PROXY'],'http://127.0.0.1:7891');self.assertNotIn('ALL_PROXY',env)
        self.assertEqual(inherit_system_proxy({},{'enabled':False,'server':'127.0.0.1:7890','pac':True}),{})
    def test_diagnostics_redact_credentials(self):
        text=str(describe({'HTTPS_PROXY':'http://alice:secret@127.0.0.1:7890'}))
        self.assertNotIn('alice',text);self.assertNotIn('secret',text);self.assertIn('127.0.0.1:7890',text)
    def test_existing_bypass_is_preserved_and_invalid_endpoint_ignored(self):
        env=inherit_system_proxy({'NO_PROXY':'example.test'},{'enabled':True,'server':'127.0.0.1:7890'})
        self.assertEqual(env['NO_PROXY'],'example.test')
        self.assertFalse(inherit_system_proxy({},{'enabled':True,'server':'http://host/invalid'}))

if __name__=='__main__':unittest.main()
