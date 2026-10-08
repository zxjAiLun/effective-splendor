import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import prism_m67_eval_recovery_r4 as r4


class R4RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.out = Path(self.temp.name)
        self.cp = self.out / 'config.json'
        self.c = {'candidates': {'candidate-a': {}}, 'opponents': {'general': {}}, 'seeds': [10, 11]}
        r4.write(self.cp, self.c)
        self.keys = sorted(r4.r3.expected_keys(self.c))

    def test_worker_reuses_partial_6_games_and_runs_only_remaining(self):
        saved = {self.keys[0]: {'status': 'completed', 'row': {}}, self.keys[1]: {'status': 'completed', 'row': {}}}
        r4.write(self.out / 'progress.json', {'config_sha256': r4.r3.fixed.canonical_hash(self.c), 'games': saved})
        r4.write(self.out / 'recovery.json', {'retained_errors': {}, 'orphan_keys': []})
        called = []
        def evaluate(v, output, m, o, seed, seat, progress):
            k = r4.r3.fixed._game_key(m, o, seed, seat)
            called.append(k)
            progress['games'][k] = {'status': 'completed', 'row': {}}
        validated = {'config': self.c, 'candidates': self.c['candidates'], 'opponents': self.c['opponents']}
        shard = {'name': 'shard-00413', 'config': str(self.cp), 'output': str(self.out), 'sha256': r4.digest(self.cp), 'games': 4}
        with patch.object(r4, 'configure_bounds', return_value=3600), \
             patch.object(r4, 'remaining', return_value=3600), \
             patch.object(r4, 'read', side_effect=lambda p: {'shards': [shard]} if str(p).endswith('plan.json') else {'plan_sha256': 'ok'} if str(p).endswith('prepared.json') else r4.r3.read(p)), \
             patch.object(r4, 'digest', return_value='ok'), \
             patch.object(r4.r3.arena, 'validate_arena_config', return_value=validated), \
             patch.object(r4.r3.fixed, 'check_assets'), \
             patch.object(r4.r3.fixed, '_evaluate_one', side_effect=evaluate), \
             patch.object(r4.r3.fixed, '_rows_from_progress', return_value=[{}, {}, {}, {}]):
            res = r4.worker('shard-00413')
        self.assertEqual(called, self.keys[2:])
        self.assertEqual(res['state'], 'COMPLETE')
        self.assertEqual(res['games'], 4)

    def test_expired_deadline_rejected(self):
        policy_mock = {'adapter_sha256': 'a', 'r3_adapter_sha256': 'b', 'r3b_adapter_sha256': 'c', 'execution_sha256': 'd', 'weights': {'a': 'wa', 'b': 'wb'}, 'deadline': time.time() - 10}
        audit_a = {'status': 'PASS_TRAINING_ARTIFACT_AUDIT', 'weights_sha256': 'wa'}
        audit_b = {'status': 'PASS_TRAINING_ARTIFACT_AUDIT', 'weights_sha256': 'wb'}
        with patch.object(r4, 'read', side_effect=[policy_mock, audit_a, audit_b]), \
             patch.object(r4, 'digest', side_effect=['a', 'b', 'c', 'd', 'wa', 'wb']), \
             patch.object(r4.original, 'verify'):
            with self.assertRaisesRegex(ValueError, 'deadline exhausted'):
                r4.remaining()


if __name__ == '__main__':
    unittest.main()
