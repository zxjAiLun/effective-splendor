import copy
import time
import unittest
from unittest.mock import patch
from scripts import prism_m67_resume as r


class ResumeTests(unittest.TestCase):
    def fixture(self):
        spec={'cycles':[[{'job_id':'old'}],[{'job_id':'done'},{'job_id':'future'}]],'limits':{'max_physical_decisions':100,'max_infra_retries':0}}
        state={'phase':'COLLECTING','paused':False,'cycle':2,'consumed':['batch1'],'jobs':{'done':{'status':'COMPLETE'}},'all_jobs':['old','done','future'],'attempts':2}
        ledger={'format':'prism-ppo-launch-ledger-v1','failed':False,'attempts':{'1':{'job':{'job_id':'old'},'status':'COMPLETE','charged_decisions':3},'2':{'job':{'job_id':'done'},'status':'COMPLETE','charged_decisions':4}},'physical_decisions':7,'retries':0}
        return spec,state,ledger

    def test_partial_cycle_accepts_unlaunched_schedule_without_mutation(self):
        spec,state,ledger=self.fixture();before=copy.deepcopy((spec,state,ledger))
        r.validate_collecting(spec,state,ledger)
        self.assertEqual(before,(spec,state,ledger))

    def test_unfinished_physical_attempt_rejected(self):
        spec,state,ledger=self.fixture();ledger['attempts']['2']['status']='RUNNING'
        with self.assertRaises(ValueError):r.validate_collecting(spec,state,ledger)

    def test_cohort_and_accounting_drift_rejected(self):
        for target in ['cohort','charge','jobs','consumed']:
            spec,state,ledger=self.fixture()
            if target=='cohort':state['all_jobs'].append('wrong')
            if target=='charge':ledger['physical_decisions']=99
            if target=='jobs':state['jobs']['done']['status']='RUNNING'
            if target=='consumed':state['consumed']=[]
            with self.assertRaises(ValueError):r.validate_collecting(spec,state,ledger)

    def test_wall_override_preserves_state_and_refuses_failed_paused_expired(self):
        state={'phase':'COLLECTING','paused':False,'started_at':0}
        r.guard_wall(state,time.time()+20);self.assertEqual(state['started_at'],0)
        for bad,deadline in [({'phase':'FAILED','paused':False},time.time()+20),({'phase':'COLLECTING','paused':True},time.time()+20),(state,time.time()-1)]:
            with self.assertRaises(ValueError):r.guard_wall(bad,deadline)

    def test_policy_adapter_original_execution_and_deadline_binding(self):
        policy={'adapter_sha256':'adapter','original_execution_sha256':'execution'}
        budget={'policy_sha256':'policy','deadline':time.time()+100}
        def rd(path):return policy if path==r.POLICY else budget
        def dg(path):return 'adapter' if str(path)==r.__file__ else 'policy' if path==r.POLICY else 'execution'
        with patch.object(r,'read',side_effect=rd),patch.object(r,'digest',side_effect=dg):
            self.assertGreater(r.remaining(),0)
            budget['deadline']=0
            with self.assertRaises(ValueError):r.remaining()
            budget['deadline']=time.time()+100;budget['policy_sha256']='wrong'
            with self.assertRaises(ValueError):r.remaining()

    def test_exact_resume_drift_rejected(self):
        spec,state,ledger=self.fixture()
        class Campaign:
            root=r.ROOT/'campaigns/a';run=type('Run',(),{'state':state,'parent':'runhead'})()
            def _load(self):return 'ledgerhead',ledger
        Campaign.spec=spec
        fingerprints={'rng':'rng','model':'model','optimizer':'optimizer','progress':'progress'}
        policy={'resume_state':{'run_commit':'different','ledger_commit':'ledgerhead','state':fingerprints,'ledger_state_sha256':'ledger'}}
        with patch.object(r,'read',return_value={'nonce':'n','host_id':'host'}),patch('training.prism_portable.protocol.assert_owner'),patch('training.prism_portable.protocol.state_fingerprints',return_value=fingerprints),patch('training.prism_portable.protocol.state_digest',return_value='ledger'):
            with self.assertRaises(ValueError):r.verify_resume(Campaign(),policy)


if __name__=='__main__':unittest.main()
