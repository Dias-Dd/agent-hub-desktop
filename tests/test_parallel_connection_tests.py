import threading,time
from unittest.mock import patch
import test_integrations as base
from hub.connection_tests import MAX_PARALLEL
class Parallel(base.RegistryTests):
 def wait_for(self,predicate):
  deadline=time.monotonic()+3
  while time.monotonic()<deadline:
   if predicate():return
   time.sleep(.01)
  self.fail('parallel test did not reach expected state')
 def test_separate_single_tests_overlap_and_duplicates_are_not_submitted(self):
  service=self.registry.connection_tests;agents=self.registry.rows('agent_profiles');release=threading.Event();entered=[];lock=threading.Lock()
  def work(item):
   with lock:entered.append(item['id'])
   release.wait(3)
  with patch.object(service,'test_one',side_effect=work):
   try:
    first=self.registry.test_all('user',True,agents[0]['id']);self.wait_for(lambda:len(entered)==1)
    second=self.registry.test_all('user',True,agents[1]['id']);self.wait_for(lambda:len(entered)==2)
    duplicate=self.registry.test_all('user',True,agents[0]['id'])
    self.assertTrue(first['started']);self.assertTrue(second['started']);self.assertFalse(duplicate['started']);self.assertEqual(len(entered),2)
   finally:
    release.set()
    for thread in service.threads:thread.join(3)
 def test_many_agents_are_batched_at_global_pool_limit(self):
  service=self.registry.connection_tests;release=threading.Event();lock=threading.Lock();current=0;peak=0;visited=[]
  def work(item):
   nonlocal current,peak
   with lock:current+=1;peak=max(current,peak);visited.append(item['id'])
   release.wait(3)
   with lock:current-=1
  with patch.object(service,'test_one',side_effect=work):
   try:
    result=self.registry.test_all('user',True);self.wait_for(lambda:len(visited)==MAX_PARALLEL)
    self.assertEqual(len(visited),MAX_PARALLEL);self.assertEqual(result['count'],9)
   finally:release.set();service.thread.join(3)
  self.assertEqual(len(visited),9);self.assertEqual(peak,MAX_PARALLEL)
 def test_runtime_test_lane_runs_two_even_when_project_limit_is_one(self):
  c=self.connection(enabled=True);a=self.agent(c);b=self.agent(c,name='second');rt=self.server.workflows.runtime(a['id']);service=self.registry.connection_tests;both=threading.Event();release=threading.Event();seen=[];lock=threading.Lock()
  with self.server.hub.tx():self.server.hub.db.execute("insert or replace into settings values('max_parallel','1')")
  def execute(run):
   with lock:
    seen.append(run['agent'])
    if len(seen)==2:both.set()
   release.wait(3);rt.finalize(run,'completed','连接成功')
  with patch.object(rt,'execute',side_effect=execute):
   try:
    rt.start();self.registry.test_all('user',True,a['id']);self.registry.test_all('user',True,b['id']);self.assertTrue(both.wait(3),'runtime serialized tests behind project limit')
   finally:
    release.set()
    for thread in service.threads:thread.join(4)
  self.assertEqual(service.snapshot()[a['id']]['status'],'passed');self.assertEqual(service.snapshot()[b['id']]['status'],'passed')
