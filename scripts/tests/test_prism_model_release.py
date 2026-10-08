import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts import prism_model_release as release


class ReleaseTests(unittest.TestCase):
    def test_existing_export_exact_tensor_identity_and_weight_drift(self):
        p=release.ROOT/'local-artifacts/prism/m62-reception-2026-10-04/harvest/beta/weights.json'
        self.assertEqual(len(release.validate_export(p,p.with_name('weights.manifest.json'),release.sha(p))['tensors']),32)
        with self.assertRaisesRegex(ValueError,'weight drift'):
            release.validate_export(p,p.with_name('weights.manifest.json'),'0'*64)

    def test_rehashed_manifest_still_requires_exact_tensor_bytes(self):
        p=release.ROOT/'local-artifacts/prism/m62-reception-2026-10-04/harvest/beta/weights.json'
        m=release.read(p.with_name('weights.manifest.json'));key=next(iter(m['tensors']))
        m['tensors'][key]['sha256']='0'*64;m['tensor_sha256']=release.canonical(m['tensors'])
        with tempfile.TemporaryDirectory() as temp:
            manifest=Path(temp)/'manifest.json';manifest.write_text(json.dumps(m),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'tensor content drift'):
                release.validate_export(p,manifest,release.sha(p))

    def test_publication_requires_explicit_owner_scope_before_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'spec.json';p.write_text(json.dumps({'authorization':{'source':'another_agent'}}),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'owner publication required'):release.publish(p,Path(temp))
            self.assertEqual(list(Path(temp).iterdir()),[p])

    def test_exact_publication_and_collision_refusal(self):
        spec=release.read(release.ROOT/'benchmarks/m65-prism-version-release.publication.json')
        # Archive evidence stays read-only at its original project paths while
        # both version destinations are installed into an isolated test root.
        for item in spec['models']:
            for key in ('source_weights','source_companion','original_result','original_config','artifact_audit'):
                item[key]=str(release.ROOT/item[key])
            for ref in item['greedy_evidence']:
                for key in ('path','config','plan','completion'):ref[key]=str(release.ROOT/ref[key])
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=root/'publication.json';p.write_text(json.dumps(spec),encoding='utf-8')
            output=release.publish(p,root)
            self.assertEqual(output['status'],'RELEASED_TWO_EXPERIMENTAL_MODELS')
            for item in spec['models']:
                record=release.read(root/item['record_path'])
                self.assertEqual(release.sha(root/record['weights_path']),item['weights_sha256'])
                self.assertFalse(record['default_replaced'])
                self.assertEqual(record['original_research_verdict'],release.read(item['original_result'])['verdicts'])
            with self.assertRaisesRegex(ValueError,'already registered'):release.publish(p,root)


if __name__=='__main__':unittest.main()
