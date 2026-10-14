"""Zero-game partition/import regressions and owned Linux handoff integration."""
import importlib.util,json,os,signal,subprocess,sys,tempfile,time,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
target=ROOT/'scripts/prism_m75_dual_node.py'
if not target.exists():target=ROOT/'dual-node-r3/dual_node.py'
spec=importlib.util.spec_from_file_location('dual',target)
d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)

class DualNode(unittest.TestCase):
    def setUp(self):self.c=d.read(ROOT/'benchmarks/m75-prism-continuation.config.json')
    def test_exact_grid_and_no_duplicates(self):
        groups=d.validate_partition(self.c)
        keys=[(m,o,s,seat) for rows in groups.values() for _,m,o,seeds in rows for s in seeds for seat in (0,1)]
        self.assertEqual(len(keys),9216);self.assertEqual(len(set(keys)),9216)
        expected={(m,o,s,seat) for m in ('base','a') for o,(lo,hi) in {**self.c['evaluation']['common_seed_by_opponent'],**self.c['evaluation']['coverage_seed_by_opponent'],'parent':[13030000,13030511]}.items() if not(m=='base' and o=='parent') for s in range(lo,hi+1) for seat in (0,1)}
        self.assertEqual(set(keys),expected)
    def test_grid_loss_rejected(self):
        self.c['evaluation']['common_seed_by_opponent']['general'][1]-=1
        with self.assertRaises(ValueError):d.validate_partition(self.c)
    def test_candidate_parent_remains_candidate_only(self):
        self.assertFalse(any(o=='parent' for _,m,o,s in d.assigned(self.c,'base')))
        self.assertEqual(sum(len(s)*2 for _,m,o,s in d.assigned(self.c,'a') if o=='parent'),1024)
    def malformed_import(self,member,existing=False,corrupt=False):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);rev=root/'dual-node-r3';(rev/'inbox').mkdir(parents=True)
            d.write(rev/'policy.json',{'test':True})
            archive=rev/'inbox/baseline-evidence.zip';raw=b'original'
            with zipfile.ZipFile(archive,'w') as z:
                z.writestr(member,raw);z.writestr('transfer-manifest.json',json.dumps({member:'0'*64 if corrupt else d.hashlib.sha256(raw).hexdigest()}))
            d.write(rev/'inbox/transfer-ready.json',dict(policy_sha256=d.digest(rev/'policy.json'),sha256=d.digest(archive),bytes=archive.stat().st_size,members=1))
            if existing:
                (root/member).parent.mkdir(parents=True);(root/member).write_bytes(b'keep')
            with patch.object(d,'ROOT',root),patch.object(d,'REV',rev),patch.object(d,'policy',return_value={}):
                with self.assertRaises(ValueError):d.import_baseline()
            if existing:self.assertEqual((root/member).read_bytes(),b'keep')
    def test_archive_path_escape_rejected(self):self.malformed_import('../bad')
    def test_archive_corruption_rejected(self):self.malformed_import('evaluation/base-general-1/ledger.json',corrupt=True)
    def test_existing_dispatch_never_overwritten(self):self.malformed_import('evaluation/base-general-1/ledger.json',existing=True)
    @unittest.skipUnless(sys.platform.startswith('linux'),'Linux signal ownership integration')
    def test_held_outer_parent_does_not_stop_owned_worker(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td);fixture=td/'parent.py'
            fixture.write_text('import sys,os,time\nfrom pathlib import Path\nsys.path.insert(0,'+repr(str(ROOT))+')\nfrom scripts.prism_dsw_ppo_process import ProcessTree\nos.environ["PRISM_PPO_CONTROL_DIR"]='+repr(str(td))+'\nwith open('+repr(str(td/'log'))+',"wb") as f:\n with ProcessTree(cpu_seconds=10,memory_bytes=512*1024**2) as t:\n  t.start([sys.executable,"-c",'+repr('import time;from pathlib import Path\nfor i in range(20):\n Path('+repr(str(td/'ticks'))+').write_text(str(i));time.sleep(.1)')+'],cwd='+repr(str(ROOT))+',stdout=f,stderr=f)\n  t.wait(wall_seconds=10)\n')
            p=subprocess.Popen([sys.executable,'-B',str(fixture)])
            try:
                deadline=time.time()+5
                while not (td/'ticks').exists():
                    if time.time()>deadline:raise AssertionError('owned worker did not start')
                    time.sleep(.05)
                before=int((td/'ticks').read_text());os.kill(p.pid,signal.SIGSTOP);time.sleep(.4)
                self.assertGreater(int((td/'ticks').read_text()),before)
                os.kill(p.pid,signal.SIGCONT);self.assertEqual(p.wait(timeout=8),0)
                record=d.read(next((td/'relay').glob('*.json')));self.assertEqual(record['status'],'FINISHED');self.assertIsNone(record['stop_reason'])
            finally:
                if p.poll() is None:os.kill(p.pid,signal.SIGCONT);p.terminate();p.wait(timeout=5)

if __name__=='__main__':unittest.main()
