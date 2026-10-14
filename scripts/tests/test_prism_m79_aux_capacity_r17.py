import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from scripts import prism_m79_aux_capacity_r17 as capacity


class CapacityTest(unittest.TestCase):
    def test_dead_probe_or_failed_receipt_is_never_an_indefinite_wait(self):
        with self.assertRaises(ValueError):
            capacity.admission({'qualifier': {'alive': False}}, 500)
        with self.assertRaises(ValueError):
            capacity.admission({'capacity': {'status': 'FAIL_CAPACITY_TIMEOUT'}}, 500)
        with self.assertRaises(ValueError):
            capacity.admission({'qualifier': {'alive': True, 'started_at': 100}}, 280)
        self.assertFalse(capacity.admission({'qualifier': {'alive': True, 'started_at': 100}}, 279))

    def test_timeout_always_publishes_failure_even_when_scan_cannot_exit(self):
        p = MagicMock(pid=123)
        p.communicate.side_effect = subprocess.TimeoutExpired('du', 180)
        p.wait.side_effect = subprocess.TimeoutExpired('du', 5)
        with tempfile.TemporaryDirectory() as folder, patch.object(capacity.subprocess, 'Popen', return_value=p):
            target = Path(folder)/'receipt.json'
            result = capacity.qualify(target)
            self.assertEqual(json.loads(target.read_text())['status'], 'FAIL_CAPACITY_TIMEOUT')
            self.assertFalse(result['scan_exit_confirmed'])
            p.kill.assert_called_once()

    def test_full_capacity_refuses_admission(self):
        p = MagicMock(pid=123, returncode=0)
        p.communicate.return_value = ('99900000000 /mnt/workspace\n', '')
        with tempfile.TemporaryDirectory() as folder, patch.object(capacity.subprocess, 'Popen', return_value=p):
            result = capacity.qualify(Path(folder)/'receipt.json')
            self.assertEqual(result['status'], 'FAIL_OWNER_CAPACITY')

    def test_success_requires_actual_inventory_and_preserves_owner_limit(self):
        p = MagicMock(pid=123, returncode=0)
        p.communicate.return_value = ('52000000000 /mnt/workspace\n', '')
        with tempfile.TemporaryDirectory() as folder, patch.object(capacity.subprocess, 'Popen', return_value=p):
            result = capacity.qualify(Path(folder)/'receipt.json')
            self.assertEqual(result['status'], 'PASS_OWNER_100GB_CAPACITY')
            self.assertEqual(result['owner_limit_bytes'], 100000000000)
            self.assertEqual(result['free_under_owner_limit_bytes'], 48000000000)


if __name__ == '__main__':
    unittest.main()
