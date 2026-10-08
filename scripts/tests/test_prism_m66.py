"""M66 bounded process/contract tests. Real processes only on Linux; no games."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from scripts import prism_dsw_ppo_process as process
from scripts import prism_m66_prepare as prepare


class ContractTests(unittest.TestCase):
    def test_exact_frozen_scope(self):
        c=prepare.read(prepare.ROOT/prepare.CONFIG);bp=prepare.read(prepare.ROOT/prepare.BLUEPRINT)
        prepare.validate(c,bp)
        jobs=[j for cycle in bp['template']['cycles'] for j in cycle]
        self.assertEqual(len(jobs),1024)
        self.assertEqual(len({j['environment_seed'] for j in jobs}),512)
        self.assertEqual({k:sum(j['opponent_id']==k for j in jobs) for k in set(prepare.ORDER)},c['training']['mix'])
        self.assertEqual(bp['template']['run']['ppo']['style_beta'],0)
        self.assertNotIn('style',bp['template']['run'])

    def test_reject_scope_drift(self):
        c=prepare.read(prepare.ROOT/prepare.CONFIG);bp=prepare.read(prepare.ROOT/prepare.BLUEPRINT)
        bad=copy.deepcopy(c);bad['evaluation']['gates']['candidate/strength_pool']=0
        with self.assertRaisesRegex(ValueError,'gate drift'):prepare.validate(bad,bp)
        bp['template']['cycles'][0].pop()
        with self.assertRaisesRegex(ValueError,'budget drift'):prepare.validate(c,bp)

    def test_engineering_separate_and_bounded(self):
        c=prepare.read(prepare.ROOT/prepare.CONFIG)
        bp=prepare.build_blueprint(prepare.read(prepare.ROOT/'benchmarks/m63-prism-control-building.train.json'),{k:v['sha256'] for k,v in c['assets'].items()},True)
        jobs=bp['template']['cycles'][0]
        self.assertEqual(len(jobs),8)
        self.assertEqual({j['environment_seed'] for j in jobs},set(range(9700000,9700004)))
        self.assertEqual(bp['template']['limits']['max_infra_retries'],0)

    def test_limits_and_pid_identity(self):
        options=dict(wall=10,cpu_limit=20,memory=100,max_processes=5)
        self.assertIsNone(process.stop_reason(1,2,3,1,**options))
        for args,expected in [((10,2,3,1),'wall_deadline'),((1,20,3,1),'cpu_deadline'),((1,2,100,1),'memory_deadline'),((1,2,3,6),'process_limit')]:
            self.assertEqual(process.stop_reason(*args,**options),expected)
        p=process.psutil.Process()
        self.assertTrue(process.same_process(p.pid,p.create_time()))
        self.assertFalse(process.same_process(p.pid,p.create_time()-10))
        for value in (0,-1,float('inf')):
            with self.assertRaises(ValueError):process.ProcessTree(cpu_seconds=value,memory_bytes=100)


@unittest.skipUnless(sys.platform.startswith('linux'),'DSW Linux process integration')
class LinuxProcessTests(unittest.TestCase):
    def run_case(self,code,wall=10,memory=512*1024**2):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ,{'PRISM_PPO_CONTROL_DIR':temp}):
            with open(Path(temp)/'stdout','wb') as out,open(Path(temp)/'stderr','wb') as err:
                with process.ProcessTree(cpu_seconds=10,memory_bytes=memory,max_processes=8) as tree:
                    child=tree.start([sys.executable,'-B','-c',code],cwd=prepare.ROOT,stdout=out,stderr=err)
                    result=tree.wait(wall_seconds=wall)
                    self.assertFalse(process.same_process(child.pid,tree.created))
                result['stderr']=Path(err.name).read_text()
                return result

    def test_normal_exit_and_cpu_accounting(self):
        r=self.run_case('sum(i*i for i in range(200000));print("done")')
        self.assertEqual(r['returncode'],0,r)
        self.assertIsNone(r['stop_reason'])
        self.assertGreater(r['cpu_seconds'],0)

    def test_wall_deadline_kills_owned_child(self):
        r=self.run_case('import time;time.sleep(30)',wall=.6)
        self.assertNotEqual(r['returncode'],0)
        self.assertEqual(r['stop_reason'],'wall_deadline')
        self.assertLess(r['wall_seconds'],8)

    def test_child_failure_is_not_success(self):
        r=self.run_case('raise SystemExit(7)')
        self.assertEqual(r['returncode'],7)

    def test_parent_death_stops_relay(self):
        with tempfile.TemporaryDirectory() as temp:
            code='from scripts.prism_dsw_ppo_process import ProcessTree;import sys,time; t=ProcessTree(cpu_seconds=10,memory_bytes=536870912);p=t.start([sys.executable,"-c","import time;time.sleep(30)"],cwd="'+str(prepare.ROOT)+'",stdout=None,stderr=None);print(p.pid,flush=True);time.sleep(.5)'
            env=dict(os.environ,PRISM_PPO_CONTROL_DIR=temp)
            p=subprocess.Popen([sys.executable,'-B','-c',code],cwd=prepare.ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            pid=int(p.stdout.readline());p.wait(timeout=10)
            deadline=time.monotonic()+6
            while time.monotonic()<deadline:
                rec=list((Path(temp)/'relay').glob('*.json'))
                if rec and json.loads(rec[0].read_text()).get('status')=='FINISHED':break
                time.sleep(.1)
            row=json.loads(rec[0].read_text())
            self.assertEqual(row['stop_reason'],'parent_identity_lost')
            p.stdout.close();p.stderr.close()


if __name__=='__main__':unittest.main()
