import unittest
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch
from scripts.prism_m79_platform_guard import safe_training_state, verify_pause
from scripts import prism_m79_platform_guard as guard


class PlatformGuardTest(unittest.TestCase):
    def test_no_inflight_game_or_failed_evidence(self):
        state = {'phase': 'COLLECTING', 'jobs': {'j': {'status': 'COMPLETE'}}}
        ledger = {'failed': False, 'attempts': {'1': {'status': 'COMPLETE'}}}
        safe_training_state(state, ledger)
        state['jobs']['j']['status'] = 'RUNNING'
        with self.assertRaises(ValueError):
            safe_training_state(state, ledger)
        state['jobs']['j']['status'] = 'COMPLETE'
        ledger['failed'] = True
        with self.assertRaises(ValueError):
            safe_training_state(state, ledger)

    def test_exact_resume_rejects_drift_and_other_failure(self):
        pause = {'status': 'PAUSED_SAFE_FULL_STATE', 'stage': 'train', 'run_commit': 'h',
                 'state_fingerprints': {'rng': 'r'}, 'stage_completion_sha256': 'c'}
        verify_pause(pause, 'h', {'rng': 'r'}, 'c')
        for commit, fingerprints, completion in [('x', {'rng': 'r'}, 'c'), ('h', {'rng': 'x'}, 'c'), ('h', {'rng': 'r'}, 'x')]:
            with self.assertRaises(ValueError):
                verify_pause(pause, commit, fingerprints, completion)
        pause['stage'] = 'audit'
        with self.assertRaises(ValueError):
            verify_pause(pause, 'h', {'rng': 'r'}, 'c')

    @unittest.skipUnless(sys.platform.startswith('linux'), 'real POSIX stop/kill verification')
    def test_real_stop_preserves_full_committed_store_and_no_game_relaunch(self):
        import torch
        import psutil
        from scripts.prism_m67_storage import install
        from training.prism_portable.engine.ppo.store import CommitStore
        from training.prism_portable.protocol import state_fingerprints
        install()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            camp = root / 'campaigns/a'
            camp.mkdir(parents=True)
            (camp / 'contract.json').write_text('{"run":{"arena_contract_sha256":"' + 'b'*64 + '"}}')
            state = dict(phase='COLLECTING', model={'p': torch.ones(2)}, optimizer={'step': 7},
                         rng={'torch': torch.get_rng_state()}, cycle=3, global_step=7, update_attempts=7,
                         attempts=3, decisions=11, all_jobs=['j'], consumed=['batch'], schedule=['j'],
                         jobs={'j': {'status': 'COMPLETE'}}, cursor=11, order=[0], started_at=1)
            store = CommitStore(camp / 'run', 'a'*64)
            with store.lock():
                committed = store.commit(state, expected_parent=None)
            ledger_store = CommitStore(camp / 'launch-ledger', 'b'*64)
            with ledger_store.lock():
                ledger_store.commit({'failed': False, 'attempts': {'3': {'status': 'COMPLETE'}}}, expected_parent=None)
            class SavedRun:
                @contextmanager
                def _transaction(self):
                    with store.lock():
                        self.parent, self.state = store.load()
                        yield
            worker = subprocess.Popen([sys.executable, '-B', '-c', 'import time; time.sleep(30)'])
            try:
                binding = {'stop_at': time.time(), 'estimated_platform_stop': time.time()+1800}
                with patch.object(guard, 'ROOT', root), patch('training.prism_portable.engine.ppo.coordinator.Run.open', return_value=SavedRun()):
                    proof = guard.stop_training(binding, psutil.Process(), psutil.Process(worker.pid))
                self.assertEqual(worker.wait(timeout=5), -9)
                head, after = store.load()
                self.assertEqual(head, committed)
                self.assertEqual(proof['run_commit'], committed)
                self.assertEqual(state_fingerprints(after), state_fingerprints(state))
                self.assertEqual(after['attempts'], 3)
                self.assertEqual(after['cursor'], 11)
            finally:
                if worker.poll() is None:
                    worker.kill()
                    worker.wait()


if __name__ == '__main__':
    unittest.main()
