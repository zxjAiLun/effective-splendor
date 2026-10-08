import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import prism_m67_eval_recovery_r3b as b


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.out=Path(self.temp.name);self.cp=self.out/'config.json'
        self.config={'candidates':{'candidate-a':{}},'opponents':{'general':{}},'seeds':[1]}
        b.write(self.cp,self.config)
        b.write(self.out/'progress.json',{'config_sha256':b.old.fixed.canonical_hash(self.config),'games':{}})
        b.write(self.out/'recovery.json',{'orphan_keys':[],'retained_errors':{}})
        self.shard={'config':str(self.cp),'output':str(self.out),'sha256':b.digest(self.cp)}
        self.validator=patch.object(b.old.arena,'validate_arena_config',return_value={'config':self.config})
        self.validator.start();self.addCleanup(self.validator.stop)

    def test_valid_bindings_pass(self):b.guard(self.shard)

    def test_config_drift_rejected(self):
        self.shard['sha256']='wrong'
        with self.assertRaisesRegex(ValueError,'config hash drift'):b.guard(self.shard)

    def test_progress_drift_rejected(self):
        b.write(self.out/'progress.json',{'config_sha256':'wrong','games':{}})
        with self.assertRaisesRegex(ValueError,'progress config drift'):b.guard(self.shard)

    def test_foreign_failure_rejected(self):
        b.write(self.out/'recovery.json',{'orphan_keys':[],'retained_errors':{'foreign':{}}})
        with self.assertRaisesRegex(ValueError,'unexpected retained failure'):b.guard(self.shard)

    def test_orphan_drift_before_preparation(self):
        with patch.object(b,'verify'),patch.object(b,'read',side_effect=[{'orphan_keys':['original']},{'shards':[{}]}]),patch.object(b.old,'scan_saved',return_value=({}, {}, ['changed'])),patch.object(b.old,'prepare_a') as prepare:
            with self.assertRaisesRegex(ValueError,'orphan cohort changed'):b.prepare()
            prepare.assert_not_called()


if __name__=='__main__':unittest.main()
