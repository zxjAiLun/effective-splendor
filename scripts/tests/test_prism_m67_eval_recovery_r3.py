import unittest
from unittest.mock import patch
from scripts import prism_m67_eval_recovery_r3 as r


class RecoveryGridTests(unittest.TestCase):
    def setUp(self):
        self.c = {'candidates': {'candidate-a': {}}, 'opponents': {'general': {}}, 'seeds': [10, 11]}
        self.keys = sorted(r.expected_keys(self.c))

    def test_exact_grid(self):
        self.assertEqual(len(self.keys), 4)
        self.assertEqual(set(self.keys), {f'candidate-a/general/seed-{s}/seat-{seat}' for s in [10, 11] for seat in [0, 1]})

    def test_completed_and_errors_never_replayed(self):
        games = {self.keys[0]: {'status': 'completed'}, self.keys[1]: {'status': 'error'}}
        self.assertEqual(r.missing_keys(self.c, games), set(self.keys[2:]))

    def test_orphan_never_replayed(self):
        self.assertEqual(r.missing_keys(self.c, {}, [self.keys[0]]), set(self.keys[1:]))

    def test_unexpected_key_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            r.missing_keys(self.c, {'another': {'status': 'completed'}})

    def test_in_progress_rejected(self):
        with self.assertRaisesRegex(ValueError, 'unrecognized'):
            r.missing_keys(self.c, {self.keys[0]: {'status': 'running'}})

    def test_full_grid_runs_zero_games(self):
        self.assertEqual(r.missing_keys(self.c, {k: {'status': 'completed'} for k in self.keys}), set())

    def test_identity_drift_fails_before_original_verify(self):
        with patch.object(r, 'read', return_value={'adapter_sha256': 'bad'}), patch.object(r, 'digest', return_value='actual'), patch.object(r.original, 'verify') as native:
            with self.assertRaisesRegex(ValueError, 'adapter drift'): r.verify()
            native.assert_not_called()

    def test_worker_skips_saved_and_failed_keys(self):
        import tempfile, time
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp); cp = out / 'config.json'; r.write(cp, self.c)
            saved = {self.keys[0]: {'status': 'completed', 'row': {}}, self.keys[1]: {'status': 'completed', 'row': {}}}
            r.write(out / 'progress.json', {'games': saved})
            r.write(out / 'recovery.json', {'retained_errors': {self.keys[2]: {'status': 'error'}}, 'orphan_keys': []})
            policy = out / 'policy.json'; r.write(policy, {'deadline': time.time() + 60})
            called = []
            def evaluate(v, output, m, o, seed, seat, progress):
                key = r.fixed._game_key(m, o, seed, seat); called.append(key)
                progress['games'][key] = {'status': 'completed', 'row': {}}
            validated = {'config': self.c, 'candidates': self.c['candidates'], 'opponents': self.c['opponents']}
            with patch.object(r, 'verify'), patch.object(r, 'POLICY', policy), patch.object(r.arena, 'validate_arena_config', return_value=validated), patch.object(r.fixed, 'check_assets'), patch.object(r.fixed, '_evaluate_one', side_effect=evaluate), patch.object(r, 'digest', return_value='test-hash'):
                result = r.a_worker({'config': str(cp), 'output': str(out), 'games': 4})
            self.assertEqual(called, [self.keys[3]])
            self.assertEqual(result['state'], 'INCOMPLETE_RETAINED_FAILURES')
            self.assertIn(self.keys[2], result['excluded_keys'])


if __name__ == '__main__': unittest.main()
