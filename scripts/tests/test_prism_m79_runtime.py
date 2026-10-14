"""Zero research games: retained-cap filtering, writer safety and idle transitions."""
import copy,json,tempfile,unittest,subprocess,sys
from pathlib import Path
from unittest.mock import patch
from scripts import prism_m79_run as run,prism_m79_watchdog as watch

class RuntimeTest(unittest.TestCase):
    def test_real_saved_cap_checks_hash_chain_seed_and_terminal_exclusion(self):
        root=Path(__file__).resolve().parents[2]
        p=root/'local-artifacts/prism/m75-continuation/result-check-20261011/evidence/campaigns/a/attempts/3405'
        report=json.loads((p/'report.json').read_text());prefix=json.loads((p/'prefix.json').read_text());resources=json.loads((p/'process-result.json').read_text())
        job=dict(job_id='m75-a-c14-b38-s0',actor=0,environment_seed=13002702,opponent_id='latest-alpha')
        spec=dict(limits=dict(max_plies=256,max_physical_decisions=5184*256),run=dict(catalog_fingerprint=report['ruleset_fingerprint']),arena={k:report[k] for k in ('engine_version','protocol_version','ruleset')},opponents={'latest-alpha':dict(hello={k:v for k,v in report['agents'][1].items() if k!='seat'})})
        row=dict(status='FATAL',job=job,resources=resources,outcome=report['outcome'],charged_decisions=128)
        def check():return run.validate_cap(spec,job,row,report,prefix,resources,sidecar_count=128,replay_exists=False)
        self.assertIsInstance(check(),dict)
        prefix['steps'][1]['state_hash_before']='0'*64
        with self.assertRaises(ValueError):check()
    def test_only_terminal_jobs_enter_training_and_unresolved_rejected(self):
        s=dict(schedule=[dict(job_id='t'),dict(job_id='c')],jobs={'t':dict(status='COMPLETE'),'c':dict(status='TRUNCATED')})
        self.assertEqual(run.resolved_jobs(s),[dict(job_id='t')]);s['jobs']['c']['status']='RUNNING'
        with self.assertRaises(ValueError):run.resolved_jobs(s)
    def test_idle_notifications_at_entry_30_45_and_recovery(self):
        a,notify=watch.transition({},dict(state='NO_OWNER',node='n'),100);self.assertTrue(notify)
        b,notify=watch.transition(a,dict(state='NO_OWNER',node='n'),100+1800);self.assertTrue(notify);self.assertEqual(b['wait_bucket'],30)
        c,notify=watch.transition(b,dict(state='NO_OWNER',node='n'),100+2700);self.assertTrue(notify);self.assertEqual(c['wait_bucket'],45)
        d,notify=watch.transition(c,dict(state='RUNNING',node='n'),3000);self.assertTrue(notify);self.assertIsNone(d['wait_since'])
    def test_immutable_budget_cannot_bind_another_execution(self):
        with tempfile.TemporaryDirectory() as d,patch.object(run,'ROOT',Path(d)):
            (Path(d)/'execution.json').write_text('{}')
            (Path(d)/'round-budget.json').write_text(json.dumps(dict(execution_sha256='0'*64,deadline=9999999999)))
            with self.assertRaises(ValueError):run.bounds()
    def test_dynamic_adaptation_rejects_source_drift(self):
        with self.assertRaises(ValueError):run.adapted(run.resolved_jobs,[('missing target','replacement')])
    def test_real_process_crash_keeps_full_payload_and_atomic_cursor(self):
        import torch
        from training.prism_portable.engine.ppo.store import CommitStore
        from scripts.prism_m67_storage import install
        install()
        script='''import os,sys,torch
from training.prism_portable.engine.ppo.store import CommitStore
from scripts.prism_m67_storage import install
install();s=CommitStore(sys.argv[1],'a'*64)
with s.lock():
 p=s.load()[1];p.update(cursor=12,consumed=['batch-one'],optimizer={'step':1,'moment':torch.ones(2)})
 s.commit(p,expected_parent=s.head(),fault=lambda event:os._exit(37) if event==sys.argv[2] else None)
'''
        for event in ('payload_written','commit_written','head_published'):
            with self.subTest(event=event),tempfile.TemporaryDirectory() as d:
                store=CommitStore(Path(d)/'store','a'*64)
                initial=dict(model=torch.ones(2),optimizer=dict(step=0,moment=torch.zeros(2)),rng=torch.get_rng_state(),cursor=0,consumed=[])
                with store.lock():old=store.commit(initial,expected_parent=None)
                result=subprocess.run([sys.executable,'-B','-c',script,str(store.root),event],capture_output=True,timeout=30)
                self.assertEqual(result.returncode,37,result.stderr.decode())
                head,state=store.load();published=event=='head_published'
                self.assertEqual(state['cursor'],12 if published else 0);self.assertEqual(state['consumed'],['batch-one'] if published else [])
                self.assertTrue(torch.equal(state['model'],initial['model']));self.assertTrue(torch.equal(state['rng'],initial['rng']))
                self.assertEqual(state['optimizer']['step'],int(published));self.assertEqual(head!=old,published)

if __name__=='__main__':unittest.main()
