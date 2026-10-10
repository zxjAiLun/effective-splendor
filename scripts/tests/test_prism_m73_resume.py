"""Zero-game recovery edge cases: no replay, unchanged science and new caps."""
import copy
import unittest
from unittest.mock import patch
from scripts.prism_m73_resume import recovery_view,reservation_bytes,finish_partial_final,require_saved_terminal
from types import SimpleNamespace


class RecoveryTests(unittest.TestCase):
    def test_terminal_recovery_rejects_killed_truncated_or_other_failures(self):
        row={'status':'FATAL','resources':{'returncode':0,'stop_reason':'storage_deadline'},'outcome':{'status':'completed'}}
        require_saved_terminal(row)
        for change in [('returncode',124),('stop_reason','wall_deadline')]:
            bad=copy.deepcopy(row);bad['resources'][change[0]]=change[1]
            with self.assertRaises(ValueError):require_saved_terminal(bad)
        bad=copy.deepcopy(row);bad['outcome']['status']='truncated'
        with self.assertRaises(ValueError):require_saved_terminal(bad)

    def test_partial_final_cycle_is_executed_once_then_committed(self):
        class FakeCampaign:
            def __init__(self):self.run=SimpleNamespace(state={'phase':'COLLECTING','cycle':4});self.calls=0
            def work(self,*,stop_after_cycle):
                self.calls+=1;self.assert_stop=stop_after_cycle;self.run.state['phase']='COMMITTED'
        campaign=FakeCampaign();finish_partial_final(campaign)
        self.assertEqual(campaign.calls,1);self.assertTrue(campaign.assert_stop)
        with self.assertRaisesRegex(ValueError,'expected partial'):finish_partial_final(campaign)
        self.assertEqual(campaign.calls,1)

    def fixture(self):
        return {'cycles':[[{'job_id':'next'}]]},{'phase':'COLLECTING','paused':True,'cycle':1,'model':{'v':3},'optimizer':{'momentum':7},'rng':[1,2],'consumed':[]}, {'failed':True,'recoveries':[{'job_id':'next','event':'fatal','error_type':'ValueError'}],'attempts':{},'retries':0}

    def test_storage_translation_matches_actual_capacity_predicate(self):
        old,new,reserve=2*1024**3,8*1024**3,64*1024**2
        for actual in [0,old-1,old,new-reserve-1,new-reserve,new-reserve+1,new,new+1]:
            self.assertEqual(reservation_bytes(actual,old,new)+reserve<=old,actual+reserve<=new)
        with self.assertRaises(ValueError):reservation_bytes(1,new,old)

    def test_recovery_control_change_preserves_original_and_science(self):
        spec,state,ledger=self.fixture();before=copy.deepcopy((state,ledger))
        with patch('scripts.prism_m73_resume.validate_collecting') as validate:
            after,updated=recovery_view(spec,state,ledger,'next');validate.assert_called_once_with(spec,after,updated)
        self.assertEqual((state,ledger),before)
        self.assertEqual({k:v for k,v in after.items() if k!='paused'},{k:v for k,v in state.items() if k!='paused'})
        self.assertFalse(after['paused']);self.assertFalse(updated['failed'])

    def test_launched_attempt_cannot_be_reset_or_replayed(self):
        spec,state,ledger=self.fixture();ledger['attempts']={'1':{'job':{'job_id':'next'}}}
        with self.assertRaisesRegex(ValueError,'already attempted'):recovery_view(spec,state,ledger,'next')

    def test_other_failure_and_job_outside_schedule_rejected(self):
        spec,state,ledger=self.fixture();ledger['recoveries'][0]['error_type']='OSError'
        with self.assertRaisesRegex(ValueError,'unrecognized'):recovery_view(spec,state,ledger,'next')
        spec,state,ledger=self.fixture();spec['cycles'][0]=[]
        with self.assertRaisesRegex(ValueError,'outside'):recovery_view(spec,state,ledger,'next')


if __name__=='__main__':unittest.main()
