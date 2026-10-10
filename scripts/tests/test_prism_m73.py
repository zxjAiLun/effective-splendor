"""Scientific drift, incomplete blocks and bounded-stage ordering; no games."""
import copy
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
from scripts import prism_m73_prepare as prepare,prism_m73_report as report,prism_m73_run as run

class M73Tests(unittest.TestCase):
    def setUp(self):
        self.c=prepare.read(prepare.ROOT/prepare.CONFIG)
        self.bps={a:prepare.read(prepare.ROOT/v['blueprint']) for a,v in prepare.ARMS.items()}

    def test_all_three_same_parent_and_numerical_recipe(self):
        prepare.validate(self.c,self.bps)
        old=prepare.read(prepare.ROOT/'benchmarks/m70-prism-b-continuation.train.json')
        for bp in self.bps.values():
            self.assertEqual(bp['weight_hashes'],old['weight_hashes'])
            self.assertEqual(bp['template']['run']['ppo'],old['template']['run']['ppo'])

    def test_seed_ranges_independent_and_physical_budget(self):
        for i,(lo,hi,_) in enumerate(prepare.RANGES):
            for a,b,_ in prepare.RANGES[i+1:]:self.assertGreater(max(lo,a),min(hi,b))
        self.assertEqual(len({bp['template']['run']['seed'] for bp in self.bps.values()}),3)
        self.assertEqual(self.c['evaluation']['total_games'],4*8*512+3*1024)

    def test_parent_drift_stops(self):
        c=copy.deepcopy(self.c);c['base_model']['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'parent'):prepare.validate(c,self.bps)

    def test_budget_and_mode_drift_stops(self):
        for key,value in [('total_games',19455),('mode','sample')]:
            c=copy.deepcopy(self.c);c['evaluation'][key]=value
            with self.assertRaises(ValueError):prepare.validate(c,self.bps)

    def test_schedule_cannot_be_rebound(self):
        c=copy.deepcopy(self.c);bps=copy.deepcopy(self.bps);bps['a']['template']['cycles'][0][0]['environment_seed']=9
        c['training']['arms']['a']['blueprint_identity']=prepare.identity(bps['a'])
        with self.assertRaisesRegex(ValueError,'schedule'):prepare.validate(c,bps)

    def test_duplicates_and_missing_blocks(self):
        rows=[dict(candidate='a',opponent='parent',seed=1,candidate_seat=0,candidate_score=1)]
        self.assertIsNone(report.blocks(rows,'a','parent',[1]))
        with self.assertRaisesRegex(ValueError,'duplicate'):report.blocks(rows*2,'a','parent',[1])

    def test_shared_baseline_is_paired_once(self):
        c=copy.deepcopy(self.c);e=c['evaluation'];e.update(common_seed_by_opponent={'x':[1,2]},coverage_seed_by_opponent={'z':[3,4]},direct_seed_start=5,direct_seed_end=6,bootstrap_samples=40)
        rows=[]
        for model in ['base','a','b','c']:
            for o,seeds in [('x',[1,2]),('z',[3,4])]+([] if model=='base' else [('parent',[5,6])]):
                for s in seeds:
                    for seat in (0,1):rows.append(dict(candidate=model,opponent=o,seed=s,candidate_seat=seat,candidate_score=.5 if model=='base' else 1))
        answer=report.competitive(c,rows)
        self.assertEqual(answer['a']['common_delta']['mean'],.5)
        self.assertEqual(answer['b']['direct_parent']['mean'],1)
        self.assertTrue(answer['c']['enhancement_direct'])
        rows.pop();partial=report.competitive(c,rows)
        self.assertEqual(partial['c']['enhancement_direct'],'INCOMPLETE')

    def test_engineering_failure_never_starts_research(self):
        class Tree:
            calls=[]
            def __init__(self,**kwargs):pass
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def start(self,argv,**kwargs):self.calls.append(argv)
            def wait(self,**kwargs):return dict(returncode=1,stop_reason=None,cpu_seconds=1,user_cpu_seconds=1,kernel_cpu_seconds=0)
        with tempfile.TemporaryDirectory() as temp,patch.object(run,'ROOT',Path(temp)),patch.object(run,'verify',return_value=(self.c,{})),patch.object(run,'bounds',return_value=1000),patch.object(run,'digest',return_value='pin'),patch.object(run,'ProcessTree',Tree):
            with self.assertRaisesRegex(ValueError,'bounded-engineering'):run.pipeline()
            self.assertEqual(len(Tree.calls),1)
            self.assertEqual(prepare.read(Path(temp)/'pipeline/status.json')['state'],'FAILED_STOPPED_NO_RETRY')

if __name__=='__main__':unittest.main()
