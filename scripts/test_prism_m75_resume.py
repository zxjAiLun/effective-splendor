"""No games: real failed-cap validation, exclusion, budget and schema regressions."""
import copy
from contextlib import nullcontext
import importlib.util
import json
import os
from pathlib import Path
import types
import unittest

ROOT=Path(__file__).resolve().parents[1]
adapter=Path(os.environ.get('M75_RESUME_ADAPTER',ROOT/'scripts/prism_m75_resume.py'))
spec_module=importlib.util.spec_from_file_location('m75_resume_tested',adapter)
m=importlib.util.module_from_spec(spec_module);spec_module.loader.exec_module(m)
FIXTURE=Path(os.environ.get('M75_CAP_FIXTURE',ROOT/'local-artifacts/prism/m75-continuation/result-check-20261011/evidence/campaigns/a/attempts/3405'))

class RecoveryTest(unittest.TestCase):
    def setUp(self):
        self.report=json.loads((FIXTURE/'report.json').read_text())
        self.prefix=json.loads((FIXTURE/'prefix.json').read_text())
        self.resources=json.loads((FIXTURE/'process-result.json').read_text())
        self.job={'job_id':'m75-a-c14-b38-s0','actor':0,'environment_seed':13002702,'opponent_id':'latest-alpha'}
        self.spec={'limits':{'max_plies':256,'max_physical_decisions':5120*256},'run':{'catalog_fingerprint':self.report['ruleset_fingerprint']},'arena':{k:self.report[k] for k in ('engine_version','protocol_version','ruleset')},'opponents':{'latest-alpha':{'hello':{k:v for k,v in self.report['agents'][1].items() if k!='seat'}}}}
        self.row={'status':'FATAL','job':self.job,'resources':self.resources,'outcome':self.report['outcome'],'charged_decisions':128}
    def check(self,**kwargs):
        return m.validate_cap(self.spec,self.job,self.row,self.report,self.prefix,self.resources,sidecar_count=kwargs.get('count',128),replay_exists=kwargs.get('replay',False))
    def test_actual_256_ply_failure_is_valid_cap(self):
        self.assertIsInstance(self.check(),dict)
    def test_deadline_failure_still_stops(self):
        self.resources['stop_reason']='wall_deadline'
        with self.assertRaises(ValueError):self.check()
    def test_fabricated_draw_rejected(self):
        self.prefix['result']={'ranks':[0,0]}
        with self.assertRaises(ValueError):self.check()
    def test_broken_hash_chain_rejected(self):
        self.prefix['steps'][1]['state_hash_before']='0'*64
        with self.assertRaises(ValueError):self.check()
    def test_changed_seed_rejected(self):
        self.prefix['seed']+=1
        with self.assertRaises(ValueError):self.check()
    def test_cap_count_and_work_mismatch_rejected(self):
        with self.assertRaises(ValueError):self.check(count=127)
        self.prefix['ply_cap']=255
        with self.assertRaises(ValueError):self.check()
    def test_terminal_replay_with_cap_rejected(self):
        with self.assertRaises(ValueError):self.check(replay=True)
    def test_mixed_terminal_cap_ledger_preserves_work(self):
        ledger={'failed':False,'retries':0,'attempts':{'1':{'status':'COMPLETE','job':{'job_id':'a'},'charged_decisions':12},'2':{'status':'TRUNCATED','job':{'job_id':'b'},'charged_decisions':128}},'physical_decisions':140}
        state={'attempts':2,'all_jobs':['a','b']}
        m.validate_ledger(ledger,state,self.spec)
        ledger['physical_decisions']=12
        with self.assertRaises(ValueError):m.validate_ledger(ledger,state,self.spec)
    def test_duplicate_jobs_rejected(self):
        ledger={'failed':False,'retries':0,'attempts':{'1':{'status':'COMPLETE','job':{'job_id':'a'},'charged_decisions':1},'2':{'status':'TRUNCATED','job':{'job_id':'a'},'charged_decisions':1}},'physical_decisions':2}
        with self.assertRaises(ValueError):m.validate_ledger(ledger,{'attempts':2,'all_jobs':['a']},self.spec)
    def test_seal_filters_cap_without_terminal_reward(self):
        from training.prism_portable.engine.ppo.coordinator import Run
        seen=[]
        def prepare(games,*args,**kwargs):
            seen.extend(games)
            return {'batch_id':'batch','rows':[{}],'advantage_mean':0.,'advantage_std':1.}
        seal=m.adapted_method(Run.seal,[
          ('if s["phase"] != "COLLECTING" or any(s["jobs"].get(j["job_id"], {}).get("status") != "COMPLETE" for j in s["schedule"]):','if s["phase"] != "COLLECTING":'),
          ('games = [self.store.get_json(s["jobs"][j["job_id"]]["artifact"]) for j in s["schedule"]]','valid = resolved_jobs(s)\n        if not valid: raise ValueError("no terminal training data in cycle")\n        games = [self.store.get_json(s["jobs"][j["job_id"]]["artifact"]) for j in valid]')],{'resolved_jobs':m.resolved_jobs,'prepare_batch':prepare,'validate_batch':lambda *a:None,'tensor_identity':lambda *a:'same'})
        model=types.SimpleNamespace(state_dict=lambda:{})
        fake=types.SimpleNamespace(_transaction=lambda:nullcontext(),_admit=lambda:None,ppo=types.SimpleNamespace(style_beta=0,passes=2),config={'budget':{'max_decisions':256}},runtime={},learner=types.SimpleNamespace(model=model),_commit=lambda:None)
        fake.state={'phase':'COLLECTING','schedule':[{'job_id':'terminal'},{'job_id':'cap'}],'jobs':{'terminal':{'status':'COMPLETE','artifact':'terminal-only'},'cap':{'status':'TRUNCATED'}},'snapshot':'snapshot','consumed':[],'metrics':[],'cycle':14}
        fake._behavior_cache={'snapshot':types.SimpleNamespace(model=model)}
        fake.store=types.SimpleNamespace(get_json=lambda key:{'artifact':key},put_json=lambda b:'batch-object')
        self.assertEqual(seal(fake),'batch')
        self.assertEqual(seen,[{'artifact':'terminal-only'}])
        self.assertEqual(fake.state['jobs']['cap']['status'],'TRUNCATED')
        self.assertEqual(len(fake.state['schedule']),2)
    def test_unresolved_or_empty_cycle_rejected(self):
        s={'schedule':[{'job_id':'a'}],'jobs':{'a':{'status':'RUNNING'}}}
        with self.assertRaises(ValueError):m.resolved_jobs(s)
        s['jobs']['a']['status']='TRUNCATED'
        self.assertEqual(m.resolved_jobs(s),[])
    def test_adapter_rejects_changed_source_target(self):
        with self.assertRaises(ValueError):m.replace_once('changed','expected','new')

if __name__=='__main__':unittest.main()
