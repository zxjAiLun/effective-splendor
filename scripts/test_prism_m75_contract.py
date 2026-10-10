"""Zero-game regression checks for larger finite schedule and resource limits."""
import copy
from pathlib import Path
import sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from training.prism_portable.common import read
from scripts.prism_m75_prepare import CONFIG,ARMS,validate
class ContractTest(unittest.TestCase):
    def setUp(self):
        self.c=read(ROOT/CONFIG);self.bps={k:read(ROOT/v['blueprint']) for k,v in ARMS.items()}
    def test_finite_bound_and_dual_seats(self):
        validate(self.c,self.bps)
        jobs=[j for group in self.bps['a']['template']['cycles'] for j in group]
        self.assertEqual(len(jobs),5120)
        self.assertEqual(len({j['job_id'] for j in jobs}),5120)
        from collections import Counter
        self.assertEqual(set(Counter((j['environment_seed'],j['opponent_id']) for j in jobs).values()),{2})
    def test_wrong_parent_rejected(self):
        self.c['base_model']['sha256']='0'*64
        with self.assertRaises(ValueError):validate(self.c,self.bps)
    def test_old_small_storage_cap_rejected(self):
        self.c['training']['storage_bytes']=2*1024**3
        with self.assertRaises(ValueError):validate(self.c,self.bps)
    def test_missing_whole_disk_reserve_rejected(self):
        self.c['resources']['minimum_free_bytes']=36*1024**3
        with self.assertRaises(ValueError):validate(self.c,self.bps)
    def test_missing_job_rejected(self):
        self.bps['a']['template']['cycles'][-1].pop()
        with self.assertRaises(ValueError):validate(self.c,self.bps)
    def test_extra_retry_rejected(self):
        self.c['resources']['automatic_retries']=1
        with self.assertRaises(ValueError):validate(self.c,self.bps)
    def test_physical_evaluation_count(self):
        e=self.c['evaluation'];common=sum((hi-lo+1)*4 for lo,hi in e['common_seed_by_opponent'].values())
        coverage=sum((hi-lo+1)*4 for lo,hi in e['coverage_seed_by_opponent'].values())
        direct=(e['direct_seed_end']-e['direct_seed_start']+1)*2
        self.assertEqual(common+coverage+direct,e['total_games'])
    def test_development_budget_is_fixed(self):
        self.c['development']['total_games']=2048
        with self.assertRaises(ValueError):validate(self.c,self.bps)
    def test_development_confirmation_overlap_rejected(self):
        self.c['evaluation']['direct_seed_start']=13040000
        self.c['evaluation']['direct_seed_end']=13040511
        with self.assertRaises(ValueError):validate(self.c,self.bps)
if __name__=='__main__':unittest.main()
