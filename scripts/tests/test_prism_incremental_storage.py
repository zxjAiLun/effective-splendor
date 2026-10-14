import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.prism_incremental_storage import CampaignStorage, copy_ledger_for_record, inventory, FrozenFiles


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        (self.root/'old').write_bytes(b'1234')

    def publish(self, name, data):
        p = self.root/name
        temporary = p.with_suffix('.tmp')
        temporary.write_bytes(data)
        os.replace(temporary, p)

    def test_atomic_new_replace_and_reconcile(self):
        t = CampaignStorage(self.root, 100)
        with t.publications():
            self.publish('new', b'1234567')
            self.publish('old', b'12')
        self.assertEqual(t.size(self.root), 9)
        self.assertEqual(t.reconcile(), 9)

    def test_external_append_truncate_delete_and_atomic_write(self):
        t = CampaignStorage(self.root, 100)
        active = self.root/'attempt'; active.mkdir()
        t.watch(active)
        with t.publications():
            self.publish('attempt/config', b'abcd')
        replay = active/'replay'; replay.write_bytes(b'123456')
        self.assertEqual(t.size(self.root), 14)
        replay.write_bytes(b'1')
        (active/'config').unlink()
        self.assertEqual(t.size(self.root), 5)
        t.unwatch(active)
        self.assertEqual(t.reconcile(), 5)

    def test_external_relay_create_then_atomic_overwrite(self):
        t = CampaignStorage(self.root, 100)
        p = self.root/'relay.json';t.watch(p)
        self.publish('relay.json', b'abc')
        self.assertEqual(t.size(self.root), 7)
        self.publish('relay.json', b'abcde')
        t.unwatch(p)
        self.assertEqual(t.reconcile(), 9)

    def test_limit_checks_external_growth_and_atomic_peak(self):
        t = CampaignStorage(self.root, 10)
        with t.publications():
            with self.assertRaisesRegex(ValueError, 'reservation'):
                self.publish('old', b'1234567')
        (self.root/'old.tmp').unlink()
        p=self.root/'log';t.watch(p);p.write_bytes(b'1234567')
        with self.assertRaisesRegex(ValueError, 'budget'):
            t.size(self.root)

    def test_unexpected_writer_fails_boundary_and_restart_recounts(self):
        t=CampaignStorage(self.root, 100)
        (self.root/'old').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'untracked'):
            t.reconcile()
        with self.assertRaisesRegex(ValueError, 'invalid'):
            t.size(self.root)
        fresh=CampaignStorage(self.root, 100)
        self.assertEqual(fresh.size(self.root), 7)

    def test_checks_do_not_rescan_history(self):
        for i in range(1000): (self.root/str(i)).write_bytes(b'x')
        t=CampaignStorage(self.root, 10000)
        p=self.root/'current';p.mkdir();t.watch(p)
        original=inventory;scanned=[]
        def observed(root):
            scanned.append(Path(root));return original(root)
        with patch('scripts.prism_incremental_storage.inventory', observed):
            for _ in range(20): self.assertEqual(t.size(self.root), 1004)
        self.assertEqual(scanned, [p]*20)

    def test_record_copy_is_equivalent_and_does_not_mutate_previous(self):
        state={'attempts': {'1': {'job':{'id':'old'},'status':'COMPLETE'}},
               'physical_decisions':2, 'recoveries':[], 'failed':False}
        saved=copy.deepcopy(state)
        a=copy.deepcopy(state);b=copy_ledger_for_record(state)
        for obj in (a,b):
            obj['attempts']['2']={'job':{'id':'new'},'status':'RUNNING'}
            obj['physical_decisions']+=3
        self.assertEqual(a,b);self.assertEqual(state,saved)

    def test_frozen_input_same_size_replacement_is_rejected(self):
        files=FrozenFiles([self.root/'old']);files.check()
        self.publish('old', b'5678')
        with self.assertRaisesRegex(ValueError,'changed'):files.check()

    def test_cloned_launch_gets_actual_dsw_and_incremental_bindings(self):
        from types import SimpleNamespace
        from scripts import prism_m81_performance_r4 as revision
        from scripts import prism_m81_performance_r3 as previous
        from scripts import prism_dsw_ppo_process as process
        from training.prism_portable.engine.ppo import arena
        namespace={'ProcessTree':object,'directory_bytes':lambda _:99,'check_assets':lambda _:None}
        exec('def launch(): return ProcessTree, directory_bytes, check_assets',namespace)
        native_launch=namespace['launch']
        def legacy_wrapper(*args): return native_launch(*args)
        tracker=SimpleNamespace(size=lambda _:4)
        campaign=SimpleNamespace()
        def install(fake):fake._performance_storage=tracker
        with patch.object(arena.Campaign,'launch',legacy_wrapper), patch.object(previous,'install_campaign',install):
            revision.setup(campaign)
        tree,scan,check=native_launch()
        self.assertIs(tree,process.ProcessTree)
        self.assertIs(scan,tracker.size)
        self.assertIs(check,arena.check_assets)


if __name__=='__main__': unittest.main()
