"""Safety/provenance regressions for a presentation-only report layer."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts import prism_round_report as report


class ReadingReportTests(unittest.TestCase):
    def setUp(self):
        self.spec = report.ROOT / 'benchmarks/reports/m63-reading.json'

    def test_script_payload_cannot_close_script_element(self):
        value = {'name': '</script><script>alert(1)</script>&'}
        encoded = report.safe_json(value)
        self.assertNotIn('</script>', encoded)
        self.assertEqual(json.loads(encoded), value)

    def test_editorial_spec_rejects_different_result_and_frozen_gate(self):
        original = json.loads(self.spec.read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'spec.json'
            changed = copy.deepcopy(original)
            changed['result_sha256'] = '0' * 64
            target.write_text(json.dumps(changed), encoding='utf-8')
            with self.assertRaisesRegex(AssertionError, 'different result'):
                report.load(target)
            changed = copy.deepcopy(original)
            changed['gates']['beta/early_bonus_auc12']['threshold'] = -1
            target.write_text(json.dumps(changed), encoding='utf-8')
            with self.assertRaisesRegex(AssertionError, 'threshold drift'):
                report.load(target)

    def test_rerender_preserves_complete_evidence_and_can_repeat_on_new_page(self):
        spec = json.loads(self.spec.read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            spec['output'] = str(target/'report.html')
            spec_path = target/'spec.json'
            spec_path.write_text(json.dumps(spec), encoding='utf-8')
            evidence_bytes = b'<!doctype html><p>original evidence</p>'
            (target/'report.html').write_bytes(evidence_bytes)
            first = report.build(spec_path)
            second = report.build(spec_path)
            self.assertEqual(first, second)
            self.assertEqual((target/'report.evidence.html').read_bytes(), evidence_bytes)
            self.assertEqual(first['result_sha256'], spec['result_sha256'])
            full = (report.ROOT/spec['markdown']).read_text(encoding='utf-8')
            self.assertIn(full, (target/'report.audit.md').read_text(encoding='utf-8'))
            human=(target/'report.reading.md').read_text(encoding='utf-8')
            self.assertNotIn(spec['result_sha256'],human)
            self.assertNotIn('FAIL_BUILDING',human)
            self.assertIn('贵族覆盖率',human)
            spec['output'] = str(target/'fresh.html')
            spec_path.write_text(json.dumps(spec), encoding='utf-8')
            fresh = report.build(spec_path)
            self.assertEqual(fresh, report.build(spec_path))
            self.assertIsNone(fresh['original_html_sha256'])

    def test_provisional_route_cannot_drift_to_other_weights_or_registration(self):
        spec = json.loads(self.spec.read_text(encoding='utf-8'))
        review = json.loads((report.ROOT/spec['practical_review']).read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            spec['practical_review'] = str(target/'review.json')
            spec_path = target/'spec.json'
            spec_path.write_text(json.dumps(spec), encoding='utf-8')
            wrong = copy.deepcopy(review)
            wrong['weight_sha256'] = '0'*64
            (target/'review.json').write_text(json.dumps(wrong), encoding='utf-8')
            with self.assertRaisesRegex(AssertionError, 'weight drift'):
                report.load(spec_path)
            wrong = copy.deepcopy(review)
            wrong['registration_status'] = 'REGISTERED'
            (target/'review.json').write_text(json.dumps(wrong), encoding='utf-8')
            with self.assertRaisesRegex(AssertionError, 'cannot register'):
                report.load(spec_path)

    def test_greedy_result_requires_saved_mode_and_identity_binding(self):
        from scripts.prism_human_report import supplement
        spec=json.loads(self.spec.read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as temp:
            changed=copy.deepcopy(spec);changed['greedy_results'][0]['sha256']='0'*64
            with self.assertRaisesRegex(AssertionError,'result drift'):supplement(report.ROOT,changed)
            changed=copy.deepcopy(spec);changed['greedy_weight_sha256']['beta']='0'*64
            with self.assertRaisesRegex(AssertionError,'weight drift'):supplement(report.ROOT,changed)

    def test_trajectory_cannot_attach_different_replay_cohort(self):
        import hashlib
        from scripts.prism_human_report import supplement
        spec=json.loads(self.spec.read_text(encoding='utf-8'))
        changed=copy.deepcopy(spec);changed['greedy_trajectory']['sha256']='0'*64
        with self.assertRaisesRegex(AssertionError,'trajectory drift'):supplement(report.ROOT,changed)
        diagnostic=json.loads((report.ROOT/spec['greedy_trajectory']['path']).read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'trajectory.json'
            diagnostic['source_ledger_sha256']['common']='0'*64
            target.write_text(json.dumps(diagnostic),encoding='utf-8')
            changed=copy.deepcopy(spec)
            changed['greedy_trajectory']={'path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
            with self.assertRaisesRegex(AssertionError,'trajectory source cohort drift'):supplement(report.ROOT,changed)

    def test_release_display_requires_bound_record_and_weights(self):
        spec=json.loads(self.spec.read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'spec.json'
            changed=copy.deepcopy(spec)
            # The renderer must reject even a plausible release name when its
            # source record bytes do not match the reviewed reference.
            release=Path(temp)/'release.json';release.write_text('{}',encoding='utf-8')
            changed['model_releases']={'beta':{'path':str(release),'sha256':'0'*64}}
            target.write_text(json.dumps(changed),encoding='utf-8')
            with self.assertRaisesRegex(AssertionError,'release record drift'):report.load(target)


if __name__ == '__main__':
    unittest.main()
