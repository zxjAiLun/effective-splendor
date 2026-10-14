"""Zero-game tests for r4 immutable transfers, runtime allocation and accounting."""
import importlib.util,json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'scripts/prism_m75_eval_handoff.py'
if not path.exists():path=ROOT/'eval-handoff-r4/controller.py'
spec=importlib.util.spec_from_file_location('eval_handoff',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class EvalHandoff(unittest.TestCase):
    def archive(self,rel='development/curve.json',corrupt=False,existing=False):
        td=tempfile.TemporaryDirectory();self.addCleanup(td.cleanup);root=Path(td.name);rev=root/'eval-handoff-r4';rev.mkdir();m.write(rev/'policy.json',{})
        z=rev/'evidence.zip';raw=b'original';h=m.hashlib.sha256(raw).hexdigest()
        with zipfile.ZipFile(z,'w') as out:out.writestr(rel,raw);out.writestr('transfer-manifest.json',json.dumps({rel:'0'*64 if corrupt else h}))
        receipt=dict(sha256=m.digest(z),bytes=z.stat().st_size,members=1,policy_sha256=m.digest(rev/'policy.json'))
        if existing:(root/rel).parent.mkdir(parents=True,exist_ok=True);(root/rel).write_bytes(b'keep')
        return root,rev,z,receipt
    def test_exact_bytes_import(self):
        root,rev,z,r=self.archive()
        with patch.object(m,'ROOT',root),patch.object(m,'REV',rev):m.extract_bound(z,r,lambda rel:rel.startswith('development/'))
        self.assertEqual((root/'development/curve.json').read_bytes(),b'original')
    def test_path_escape_rejected_before_write(self):
        root,rev,z,r=self.archive('../escape')
        with patch.object(m,'ROOT',root),patch.object(m,'REV',rev):
            with self.assertRaises(ValueError):m.extract_bound(z,r,lambda rel:True)
    def test_corruption_rejected(self):
        root,rev,z,r=self.archive(corrupt=True)
        with patch.object(m,'ROOT',root),patch.object(m,'REV',rev):
            with self.assertRaises(ValueError):m.extract_bound(z,r,lambda rel:True)
        self.assertFalse((root/'development/curve.json').exists())
    def test_existing_dispatch_never_overwritten(self):
        root,rev,z,r=self.archive(existing=True)
        with patch.object(m,'ROOT',root),patch.object(m,'REV',rev):
            with self.assertRaises(ValueError):m.extract_bound(z,r,lambda rel:True)
        self.assertEqual((root/'development/curve.json').read_bytes(),b'keep')
    def test_revision_drift_rejected(self):
        root,rev,z,r=self.archive();r['policy_sha256']='0'*64
        with patch.object(m,'ROOT',root),patch.object(m,'REV',rev):
            with self.assertRaises(ValueError):m.extract_bound(z,r,lambda rel:True)
    def test_whole_archive_sha_rejected(self):
        root,rev,z,r=self.archive();r['sha256']='0'*64
        with patch.object(m,'ROOT',root),patch.object(m,'REV',rev):
            with self.assertRaises(ValueError):m.extract_bound(z,r,lambda rel:True)
    def test_early_and_final_development_seeds_are_disjoint(self):
        c=m.read(ROOT/'benchmarks/m75-prism-continuation.config.json');dev=c['development']
        groups=[{(cycle,seed,seat) for cycle in cycles for seed in range(dev['seed_start'],dev['seed_end']+1) for seat in (0,1)} for cycles in ([5,10,15],[20])]
        self.assertEqual([len(x) for x in groups],[768,256]);self.assertFalse(groups[0]&groups[1]);self.assertEqual(len(set.union(*groups)),1024)

if __name__=='__main__':unittest.main()
