"""No games: admission deadline, retained stop gates, and controller limits."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from scripts import prism_m79_deadline_r11 as revision
from scripts import prism_m79_run as run
from training.prism_portable.engine.ppo.coordinator import Run


class DeadlineRevisionTest(unittest.TestCase):
    def setUp(self):
        self.admit = revision.patch_admit(Run._admit)
        self.state = SimpleNamespace(state={'paused': False, 'phase': 'COLLECTING',
            'started_at': revision.TRAIN_DEADLINE - 85000},
            config={'budget': {'max_run_seconds': 64800}})

    def test_passes_old_deadline_but_stops_at_exact_new_deadline(self):
        with patch.object(revision.time, 'time', return_value=revision.TRAIN_DEADLINE - 1):
            with self.assertRaises(ValueError):
                Run._admit(self.state)
            self.admit(self.state)
        with patch.object(revision.time, 'time', return_value=revision.TRAIN_DEADLINE):
            with self.assertRaises(ValueError):
                self.admit(self.state)

    def test_scientific_failure_pause_and_backwards_clock_still_rejected(self):
        for change in ({'paused': True}, {'phase': 'FAILED'},
                       {'started_at': revision.TRAIN_DEADLINE + 1}):
            s = SimpleNamespace(state=dict(self.state.state, **change), config=self.state.config)
            with patch.object(revision.time, 'time', return_value=revision.TRAIN_DEADLINE - 1):
                with self.assertRaises(ValueError):
                    self.admit(s)

    def test_controller_preserves_cpu_limits_and_external_aux_accounting(self):
        function = revision.patched_pipeline(run.pipeline)
        stages = next(v for v in function.__code__.co_consts
                      if isinstance(v, tuple) and v and isinstance(v[0], tuple))
        self.assertEqual({r[0]: r[2] for r in stages}, dict(
            train=150000, audit=30000, candidates=30000,
            curve=120000, evaluate=120000, report=30000))
        self.assertIn(300000, function.__code__.co_consts)
        self.assertIn(revision.TRAIN_DEADLINE, function.__code__.co_consts)
        self.assertIn('_external_eval_cpu', function.__code__.co_names)
        self.assertNotIn(64800, function.__code__.co_consts)

    def test_source_drift_refuses_deadline_patch(self):
        with self.assertRaises(ValueError):
            revision.patched_pipeline(run.bounds)


if __name__ == '__main__':
    unittest.main()
