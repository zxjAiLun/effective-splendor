"""Zero games: both fixed checkpoints, transported code and capacity gating."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import prism_m79_development_handoff_r18 as director


class AuxiliaryHandoffTest(unittest.TestCase):
    def test_capacity_pending_never_freezes_or_dispatches_checkpoint(self):
        with patch.object(director, 'ssh', return_value={'ready': False}) as ssh:
            self.assertFalse(director.prepare_checkpoint(10))
            self.assertEqual(ssh.call_count, 1)

    def test_capacity_failure_refuses_sampling(self):
        with patch.object(director, 'ssh', return_value={
                'ready': True, 'capacity': {'status': 'FAIL_OWNER_CAPACITY'}}) as ssh:
            with self.assertRaises(ValueError):
                director.prepare_checkpoint(10)
            self.assertEqual(ssh.call_count, 1)

    def test_fixed_c10_c15_transport_templates_compile_with_correct_identity(self):
        for cycle in (10, 15):
            with self.subTest(cycle=cycle), tempfile.TemporaryDirectory() as folder:
                here = Path(folder)
                (here / 'aux-development-r18.py').write_text('print("transport")')
                calls = []
                def remote(port, source, **kwargs):
                    compile(source, 'remote-template', 'exec')
                    calls.append((port, source))
                    if len(calls) == 1:
                        return {'ready': True, 'capacity': {'status': 'PASS_OWNER_100GB_CAPACITY'}}
                    if port == 2222:
                        return {'ready': True, 'manifest': {}, 'bundle': ''}
                    return {'status': 'FAKE_ZERO_GAME_LAUNCH'}
                with patch.object(director, 'HERE', here), patch.object(director, 'ssh', remote):
                    self.assertTrue(director.prepare_checkpoint(cycle))
                self.assertIn(f'curve-c{cycle}', calls[1][1])
                self.assertIn(f'cycle-{cycle}-export', calls[1][1])
                self.assertIn(f"DEVELOPMENT_CYCLE='{cycle}'", calls[2][1])
                self.assertIn(repr(director.STOP), calls[1][1])
                self.assertNotIn('SECRET_', calls[1][1] + calls[2][1])


if __name__ == '__main__':
    unittest.main()
