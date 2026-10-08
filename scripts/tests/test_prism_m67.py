"""M67 finite seed/cadence and compression durability checks, zero games."""
import copy
import gzip
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import prism_m67_prepare as prepare

class ContractTests(unittest.TestCase):
    def setup_values(self):
        c=prepare.read(prepare.ROOT/prepare.CONFIG)
        bps={k:prepare.read(prepare.ROOT/a['blueprint']) for k,a in prepare.ARMS.items()}
        return c,bps
    def test_scope_and_independent_seeds(self):
        c,bps=self.setup_values();prepare.validate(c,bps)
        self.assertEqual(c['training']['total_games'],10240)
        self.assertNotEqual(bps['a']['template']['run']['seed'],bps['b']['template']['run']['seed'])
        for bp in bps.values():
            jobs=[j for g in bp['template']['cycles'] for j in g]
            self.assertEqual({k:sum(j['opponent_id']==k for j in jobs) for k in set(prepare.ORDER)},c['training']['mix_per_arm'])
    def test_reject_gate_and_seed_drift(self):
        c,bps=self.setup_values();bad=copy.deepcopy(c);bad['evaluation']['gates']['candidate/direct_parent']=.5
        with self.assertRaisesRegex(ValueError,'gate drift'):prepare.validate(bad,bps)
        bps['b']['template']['cycles'][0][0]['environment_seed']=9801000
        c['training']['arms']['b']['blueprint_identity']=prepare.identity(bps['b'])
        with self.assertRaisesRegex(ValueError,'seed drift'):prepare.validate(c,bps)
    def test_no_checkpoint_reselection_and_no_overwrite(self):
        c,_=self.setup_values();self.assertIn('final c20 only',c['training']['selection'])
        with self.assertRaisesRegex(ValueError,'already frozen'):prepare.freeze()
    def test_engineering_separate(self):
        c,_=self.setup_values();bp=prepare.blueprint(prepare.read(prepare.ROOT/'benchmarks/m63-prism-control-building.train.json'),{k:v['sha256'] for k,v in c['assets'].items()},engineering=True)
        self.assertEqual(len(bp['template']['cycles'][0]),8)
        self.assertEqual({j['environment_seed'] for j in bp['template']['cycles'][0]},set(range(9800000,9800004)))

try:
    import torch
except ImportError:
    torch=None

@unittest.skipIf(torch is None,'Torch required for storage integration')
class StorageTests(unittest.TestCase):
    def setUp(self):
        from training.prism_portable.engine.ppo.store import CommitStore
        from scripts.prism_m67_storage import install
        self.cls=CommitStore;self.original=(CommitStore._put,CommitStore._get)
        self.flag=getattr(CommitStore,'_m67_compressed',False);install()
        self.temp=tempfile.TemporaryDirectory(dir=os.environ.get('PI_SCRATCH_DIR'));self.root=Path(self.temp.name)
        self.store=CommitStore(self.root,'a'*64,max_bytes=1024*1024)
    def tearDown(self):
        self.cls._put,self.cls._get=self.original
        if not self.flag:del self.cls._m67_compressed
        self.temp.cleanup()
    def test_raw_content_hash_roundtrip_and_reload(self):
        from training.prism_portable.engine.ppo.store import json_bytes
        value={'rows':[{'value':.5,'array':[0]*30} for _ in range(100)]}
        with self.store.lock():key=self.store.put_json(value)
        raw=json_bytes(value);packed=(self.root/'objects'/(key+'.json')).read_bytes()
        self.assertEqual(key,hashlib.sha256(raw).hexdigest());self.assertEqual(gzip.decompress(packed),raw)
        self.assertLess(len(packed),len(raw)//4);self.assertEqual(self.store.get_json(key),value)
        payload={'tensor':torch.arange(10),'json':key}
        with self.store.lock():head=self.store.commit(payload,expected_parent=None)
        loaded=self.cls(self.root,'a'*64).load()
        self.assertEqual(loaded[0],head);self.assertTrue(torch.equal(loaded[1]['tensor'],payload['tensor']))
        self.assertEqual(loaded[1]['json'],key)
    def test_corruption_rejected(self):
        with self.store.lock():key=self.store.put_json({'value':1})
        path=self.root/'objects'/(key+'.json');path.write_bytes(gzip.compress(b'{"value":2}\n'))
        with self.assertRaisesRegex(ValueError,'hash mismatch'):self.store.get_json(key)
        with self.store.lock():
            with self.assertRaisesRegex(ValueError,'hash mismatch'):self.store.put_json({'value':1})
    def test_unpublished_commit_preserves_head_and_stale_writer_rejected(self):
        with self.store.lock():head=self.store.commit({'step':0},expected_parent=None)
        def fault(phase):
            if phase=='commit_written':raise RuntimeError('simulated crash')
        with self.store.lock():
            with self.assertRaisesRegex(RuntimeError,'simulated crash'):self.store.commit({'step':1},expected_parent=head,fault=fault)
        self.assertEqual(self.store.load(),(head,{'step':0}))
        with self.store.lock():
            new=self.store.commit({'step':2},expected_parent=head)
            with self.assertRaisesRegex(ValueError,'stale writer'):self.store.commit({'step':3},expected_parent=head)
        self.assertEqual(self.store.load(),(new,{'step':2}))
    def test_tensor_dedup_exact_bytes_and_corruption(self):
        import io,json
        from scripts.prism_m67_storage import pt_segments
        payload={'tensor':torch.arange(10000),'step':0}
        stream=io.BytesIO();torch.save(payload,stream);raw=stream.getvalue()
        self.assertEqual(b''.join(pt_segments(raw)),raw)
        with self.store.lock():key=self.store.put_payload(payload)
        count=len(list((self.root/'m67-blocks').glob('*.gz')))
        payload['step']=1
        with self.store.lock():self.store.put_payload(payload)
        self.assertLess(len(list((self.root/'m67-blocks').glob('*.gz'))),count*2)
        self.assertEqual(self.store._get('objects',key,'.pt'),raw)
        manifest=json.loads(gzip.decompress((self.root/'objects'/(key+'.pt')).read_bytes()))
        p=self.root/'m67-blocks'/(manifest['parts'][0]['sha256']+'.gz');p.write_bytes(gzip.compress(b'bad'))
        with self.assertRaisesRegex(ValueError,'block hash mismatch'):self.store.get_payload(key)

if __name__=='__main__':unittest.main()
