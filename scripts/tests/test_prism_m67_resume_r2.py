import copy
import time
import unittest
from unittest.mock import patch
from scripts import prism_m67_resume_r2 as r


class RevisionTests(unittest.TestCase):
    def test_reservation_translation_matches_real_revised_cap(self):
        old,new,reserve=16*1024**3,28*1024**3,64*1024**2
        for actual in [0,old-reserve,old,new-reserve,new-reserve+1,new,new+1]:
            self.assertEqual(r.reservation_bytes(actual,old,new)+reserve>old,actual+reserve>new)
        with self.assertRaises(ValueError):r.reservation_bytes(0,new,old)

    def test_deadline_and_source_are_bound(self):
        deadline=time.time()+100
        policy={key:key for key in ['adapter_sha256','r1_adapter_sha256','r1_policy_sha256','original_execution_sha256']}
        budget={'policy_sha256':'policy','deadline':deadline}
        def rd(path):
            if path==r.POLICY:return policy
            if path==r.R2/'budget.json':return budget
            if path==r.R2/'capacity-revision.json':return {'adapter_sha256':'capacity-adapter','base_policy_sha256':'policy'}
            if path==r.R2/'capacity-budget.json':return {'capacity_sha256':'capacity','deadline':deadline}
            return {'deadline':deadline}
        def dg(path):
            if path==r.POLICY:return 'policy'
            if path==r.R2/'capacity-revision.json':return 'capacity'
            if path==r.ROOT/'execution.json':return policy['original_execution_sha256']
            if path==r.ROOT/'continuation-r1/policy.json':return policy['r1_policy_sha256']
            if path==r.ROOT/'scripts/prism_m67_resume.py':return policy['r1_adapter_sha256']
            if str(path)==r.__file__:return 'capacity-adapter'
            return policy['adapter_sha256']
        with patch.object(r,'read',side_effect=rd),patch.object(r,'digest',side_effect=dg):
            self.assertGreater(r.remaining(),0)
            budget['deadline']=deadline+1
            with self.assertRaises(ValueError):r.remaining()
            budget['deadline']=deadline;budget['policy_sha256']='drift'
            with self.assertRaises(ValueError):r.remaining()

    def test_storage_adapters_preserve_contract_and_scope(self):
        from training.prism_portable.engine.ppo import arena
        from training.prism_portable.engine.ppo.coordinator import Run
        from types import SimpleNamespace
        cap=28*1024**3;old=16*1024**3;contract={'run':{'budget':{'max_storage_bytes':old}}};before=copy.deepcopy(contract)
        def rd(path):return {'storage_per_training_bytes':cap} if path==r.POLICY else contract
        def opened(cls,path):return SimpleNamespace(store=SimpleNamespace(root=path,max_bytes=old))
        with patch.object(arena,'directory_bytes',return_value=old),patch.object(arena,'ProcessTree'),patch.object(arena,'_m67_r2_storage',False,create=True),patch.object(Run,'open',classmethod(opened)),patch.object(r,'read',side_effect=rd),patch.object(r.ProcessTree,'wait',return_value={'ok':True}) as wait:
            r.install_storage_limits()
            tree_type=arena.ProcessTree
            r.install_storage_limits();self.assertIs(arena.ProcessTree,tree_type)
            self.assertEqual(arena.directory_bytes(r.ROOT/'campaigns/a'),4*1024**3)
            self.assertEqual(arena.directory_bytes(r.ROOT/'other'),old)
            self.assertEqual(Run.open(r.ROOT/'campaigns/a/run').store.max_bytes,cap)
            self.assertEqual(Run.open(r.ROOT/'other').store.max_bytes,old)
            tree=tree_type(cpu_seconds=1,memory_bytes=1)
            tree.wait(storage_root=r.ROOT/'campaigns/a',max_storage_bytes=old,wall_seconds=1)
            self.assertEqual(wait.call_args.kwargs['max_storage_bytes'],cap)
            self.assertEqual(contract,before)
    def test_recovery_retains_failure_and_rejects_launched_or_unknown_job(self):
        from scripts.tests.test_prism_m67_resume import ResumeTests
        spec,state,ledger=ResumeTests().fixture()
        state['paused']=True;ledger['failed']=True
        ledger['recoveries']=[{'job_id':'m67-m67-repeat-a-c16-b83-s1','event':'fatal','error_type':'ValueError'}]
        before=copy.deepcopy((state,ledger))
        s,l=r.recovery_view(spec,state,ledger)
        self.assertFalse(s['paused']);self.assertFalse(l['failed']);self.assertEqual((state,ledger),before)
        self.assertEqual(l['recoveries'],ledger['recoveries'])
        ledger['recoveries'][0]['error_type']='RuntimeError'
        with self.assertRaises(ValueError):r.recovery_view(spec,state,ledger)


if __name__=='__main__':unittest.main()
