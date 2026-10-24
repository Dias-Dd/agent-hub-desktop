import json,tempfile,unittest
from pathlib import Path
from hub.core import HubError
from hub.design_assets import bundle_html
from hub.designs import Designs
import test_designs as base
class BundleAssets(unittest.TestCase):
 def test_local_css_import_and_images_are_self_contained(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);assets=root/'assets';assets.mkdir();(assets/'dot.png').write_bytes(b'fixture')
   (assets/'colors.css').write_text('.key{color:rgb(1,2,3)}',encoding='utf-8')
   (assets/'demo.css').write_text('@import "colors.css";body{background-image:url(dot.png)}',encoding='utf-8')
   text=bundle_html('<link rel="stylesheet" href="assets/demo.css"><img src="assets/dot.png">',root/'index.html',root)
   self.assertNotIn('<link',text);self.assertNotIn('@import',text);self.assertIn('.key{color:rgb(1,2,3)}',text);self.assertIn('data:image/png;base64,',text)
 def test_missing_outside_and_remote_assets_are_not_published_as_broken(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder)
   for href in ('missing.css','../outside.css','https://example.com/demo.css'):
    with self.subTest(href=href),self.assertRaises(HubError):bundle_html('<link rel="stylesheet" href="'+href+'">',root/'p.html',root)
class AssetPublication(unittest.TestCase):
 def setUp(self):self.f=base.DesignFlow();self.f.setUp()
 def tearDown(self):self.f.tearDown()
 def test_publish_bundles_css_and_keeps_it_in_frozen_baseline(self):
  _,d=self.f.start();self.f.write_manifest(d);root=Path(d['working_directory']);(root/'assets').mkdir();(root/'assets/demo.css').write_text('body{background:rgb(3,4,5)}',encoding='utf-8')
  (root/'home.html').write_text('<link rel="stylesheet" href="assets/demo.css"><h1>home</h1>',encoding='utf-8')
  published=self.f.finish(d);version=published['versions'][-1];text=(Path(version['directory'])/'home.html').read_text(encoding='utf-8')
  self.assertIn('<style>body{background:rgb(3,4,5)}</style>',text);self.assertNotIn('<link',text);self.f.ds.verify_baseline(version)
 def test_repair_unapproved_legacy_snapshot_without_editing_old_frozen_directory(self):
  _,d=self.f.start();self.f.write_manifest(d);root=Path(d['working_directory']);(root/'assets').mkdir();(root/'assets/demo.css').write_text('h1{color:red}',encoding='utf-8')
  raw='<link rel="stylesheet" href="assets/demo.css"><h1>home</h1>';(root/'home.html').write_text(raw,encoding='utf-8')
  from unittest.mock import patch
  with patch('hub.design_assets.bundle_html',side_effect=lambda source,*_:source):published=self.f.finish(d)
  old=Path(published['versions'][-1]['directory']);old_digest=published['digest']
  self.assertEqual(self.f.ds.repair_unapproved_assets(d['id']),[d['id']])
  repaired=self.f.ds.get(d['id']);self.assertNotEqual(repaired['digest'],old_digest);self.assertEqual((old/'home.html').read_text(encoding='utf-8'),raw)
  self.assertIn('<style>',(Path(repaired['versions'][-1]['directory'])/'home.html').read_text(encoding='utf-8'));self.f.ds.verify_baseline(repaired['versions'][-1])
  repaired['state']='approved';self.f.ds.save(repaired);self.assertEqual(self.f.ds.repair_unapproved_assets(d['id']),[])
