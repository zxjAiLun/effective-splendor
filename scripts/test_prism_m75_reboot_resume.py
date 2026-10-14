"""Zero-game recovery tests: completed identity, idle warning boundaries, resumption."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

HERE=Path(__file__).parent
def load(name):
    spec=importlib.util.spec_from_file_location(name,HERE/(name+'.py'))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
r=load('prism_m75_reboot_resume');w=load('prism_m75_recovery_watchdog')


class RecoveryTests(unittest.TestCase):
    def test_resume_preserves_committed_game_and_interrupted_bytes(self):
        from scripts import prism_bounded_eval as b
        with tempfile.TemporaryDirectory() as temporary:
            dest=Path(temporary);jobs=[('a','x',1,0),('a','x',1,1),('a','x',2,0)]
            key=lambda job:b.fixed._game_key(*job)
            directory=lambda output,job:output/('game-'+str(jobs.index(job)))
            (dest/'manifest.json').write_text('{}')
            completed=directory(dest,jobs[0]);completed.mkdir();(completed/'sentinel').write_bytes(b'KEEP_COMPLETED')
            interrupted=directory(dest,jobs[1]);interrupted.mkdir();(interrupted/'partial').write_bytes(b'KEEP_PARTIAL')
            ledger=dict(execution_state='RUNNING',entries={key(jobs[0]):dict(state='COMPLETED'),key(jobs[1]):dict(state='DISPATCHED')},consumed_cpu_seconds=1.)
            b.write(dest/'ledger.json',ledger);called=[]
            def evaluate(validated,policy,out,job,remaining):
                called.append(job);d=directory(out,job);d.mkdir();(d/'result').write_text('new')
                return dict(state='COMPLETED',cpu_seconds=1.)
            mutex=SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=lambda *a:None)
            validated=dict(config=dict(timeouts=dict(game_wall_seconds=90)))
            policy=dict(cpu_seconds=4000,deadline_unix=1e20,storage_bytes=1e10,ply_cap=512,max_truncated_games=8)
            with patch.object(r,'fcntl',mutex),patch.object(r,'contract',return_value={}),patch.object(b,'load_bound',return_value=(validated,policy)),patch.object(b,'inspect',return_value={}),patch.object(b.legacy,'jobs',return_value=jobs),patch.object(b.legacy,'game_directory',side_effect=directory),patch.object(b.fixed,'check_assets'),patch.object(b,'evaluate',side_effect=evaluate),patch.object(b,'summary',return_value={}):
                r.resume_grid(dest)
            self.assertEqual(called,jobs[1:]);self.assertEqual((completed/'sentinel').read_bytes(),b'KEEP_COMPLETED')
            self.assertEqual(list((dest/'recovery-attempts').glob('*/partial'))[0].read_bytes(),b'KEEP_PARTIAL')
            saved=b.read(dest/'ledger.json');self.assertEqual(saved['execution_state'],'FINISHED');self.assertEqual(saved['consumed_cpu_seconds'],3.)

    def test_finished_grid_runs_no_games(self):
        from scripts import prism_bounded_eval as b
        with tempfile.TemporaryDirectory() as temporary:
            dest=Path(temporary);b.write(dest/'ledger.json',dict(execution_state='FINISHED'))
            with patch.object(r,'fcntl',SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=lambda *a:None)),patch.object(b,'load_bound',return_value=({},{})),patch.object(b,'inspect',return_value=dict(completed_games=64)),patch.object(b,'evaluate') as evaluate:
                self.assertEqual(r.resume_grid(dest)['completed_games'],64);evaluate.assert_not_called()

    def test_unpaired_training_is_explicit_missing(self):
        self.assertEqual(r.training_interval(lambda *a:self.fail('no fabricated bootstrap'),[dict(seed=1,candidate_seat=0)])['status'],'NOT_MEASURED_UNPAIRED')

    def test_paired_training_unchanged(self):
        rows=[dict(seed=1,candidate_seat=s) for s in (0,1)]
        self.assertEqual(r.training_interval(lambda rows,pure:dict(ci95=[.2,.8]),rows)['ci95'],[.2,.8])

    def test_duplicate_training_rejected(self):
        with self.assertRaisesRegex(ValueError,'duplicate'):
            r.training_interval(None,[dict(seed=1,candidate_seat=0)]*2)

    def test_skip_complete_and_cap(self):
        entries={'a':{'state':'COMPLETED'},'b':{'state':'RETAINED_FAILURE','kind':'PLY_CAP_TRUNCATED'},'c':{'state':'DISPATCHED'}}
        self.assertEqual(r.pending_jobs(['a','b','c','d'],entries,lambda x:x),['c','d'])

    def test_pid_reuse_rejected(self):
        with patch.object(r.psutil,'Process') as constructor:
            process=constructor.return_value;process.create_time.return_value=12
            self.assertFalse(r.live(dict(pid=1,create_time=11)))

    def test_unrelated_argv_rejected(self):
        with patch.object(r.psutil,'Process') as constructor:
            process=constructor.return_value;process.create_time.return_value=11
            process.cmdline.return_value=['unrelated'];process.status.return_value='running'
            self.assertFalse(r.live(dict(pid=1,create_time=11)))

    def test_idle_early_warning(self):
        a,notify=w.transition({},dict(state='IDLE_WAIT',node='pod1'),100)
        self.assertTrue(notify);self.assertEqual(a['idle_seconds'],0)
        b,notify=w.transition(a,dict(state='IDLE_WAIT',node='pod1'),1899)
        self.assertFalse(notify)
        c,notify=w.transition(b,dict(state='IDLE_WAIT',node='pod1'),1900)
        self.assertTrue(notify);self.assertEqual(c['idle_bucket'],30)
        d,notify=w.transition(c,dict(state='IDLE_WAIT',node='pod1'),2800)
        self.assertTrue(notify);self.assertEqual(d['idle_bucket'],45)

    def test_active_resets_idle(self):
        a,_=w.transition({},dict(state='IDLE_WAIT'),100)
        b,_=w.transition(a,dict(state='RUNNING'),1900)
        self.assertIsNone(b['idle_since'])
        c,_=w.transition(b,dict(state='IDLE_WAIT'),2000)
        self.assertEqual(c['idle_seconds'],0)

    def test_node_replacement_alerts(self):
        _,alert=w.transition(dict(state='RUNNING',node='old'),dict(state='RUNNING',node='new'),100)
        self.assertTrue(alert)

    def test_live_owner_never_restarts(self):
        with patch.object(r,'status',return_value=dict(state='RUNNING')):
            self.assertEqual(r.ensure('opaque'),dict(state='RUNNING'))

    def test_deadline_never_restarts(self):
        with patch.object(r,'status',return_value=dict(state='DEADLINE')):
            self.assertEqual(r.ensure('opaque'),dict(state='DEADLINE'))


if __name__=='__main__':unittest.main()
