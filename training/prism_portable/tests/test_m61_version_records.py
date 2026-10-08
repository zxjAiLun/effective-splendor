"""M61 registrar gates tested in isolated trees; fixtures never register real versions."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('m61_versions', ROOT / 'scripts/prism_m61_version_records.py')
versions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(versions)
REAL_CANDIDATE_SHAS = dict(versions.CANDIDATE_SHAS)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    return versions.sha(path)


def setup_receipt(root):
    """Synthetic remote/local proof graph; only inside TemporaryDirectory."""
    work = root / versions.WORK / 'reaudit-r1'
    work.mkdir(parents=True)
    remote_root = '/synthetic/m61'
    pins, source_rows, artifact_rows = {}, [], []
    for name in ('scripts/prism_balance_ab_reaudit_m61.py',
                 'training/prism_portable/tests/test_m61_reaudit.py',
                 'savedbefore-source/engine/ppo/model.py'):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# synthetic isolated test source\n', encoding='utf-8')
        remote = remote_root + '/' + name
        pins[remote] = versions.sha(path)
        source_rows.append({'remote_path': remote, 'local_path': str(path),
                            'sha256': pins[remote], 'kind': 'source'})
    inputs = {remote_root + '/unfetched-replay.json': 'f' * 64, **pins}
    outputs, arms, shas, downloaded = {}, {}, {}, {}
    for arm in ('alpha', 'balance'):
        folder = work / arm
        weights = folder / 'weights.json'
        digest = write_json(weights, {'fixture_only': True, 'arm': arm})
        shas[arm] = digest
        manifest = folder / 'weights.manifest.json'
        companion_sha = write_json(manifest, {'format': 'prism-weights-manifest-v1',
                                  'weights_sha256': digest, 'provenance': {'cycle': 4, 'run_identity': arm}})
        remote_weights = remote_root + '/campaigns/' + arm + '/weights.json'
        remote_manifest = remote_root + '/campaigns/' + arm + '/weights.manifest.json'
        row = {'status': 'PASS_TRAINING_ARTIFACT_AUDIT', 'candidate_path': remote_weights,
               'candidate_sha256': digest, 'manifest_path': remote_manifest,
               'manifest_sha256': companion_sha, 'games': 1024,
               'parity_max_abs_error': .000152744 if arm == 'alpha' else .000104761}
        downloaded[arm] = {}
        for key, path, remote, h in (('weights', weights, remote_weights, digest),
                                     ('manifest', manifest, remote_manifest, companion_sha)):
            inputs[remote] = h
            downloaded[arm][key] = {'path': str(path), 'remote_path': remote, 'sha256': h}
            artifact_rows.append({'remote_path': remote, 'local_path': str(path), 'sha256': h, 'kind': key})
        for key in ('checkpoint_validation', 'final_parity', 'training_audit', 'source_ledger', 'comparison'):
            value = {'status': 'PASS', 'weights_sha256': digest, 'new_games': 0, 'new_optimizer_updates': 0}
            if key == 'checkpoint_validation':
                value.update(final_weights_sha256=digest, parent_sha256=versions.PARENT_SHA,
                             exact_export_tensors=32, run_identity=arm)
            elif key == 'final_parity':
                value.update(boundary_inputs=68, atol=1e-4, rtol=1e-4, native_exit_code=0,
                             max_abs_error=row['parity_max_abs_error'])
            elif key == 'training_audit':
                value.update(status='PASS_TRAINING_ARTIFACT_AUDIT', new_matches=0)
            elif key == 'comparison':
                value.update(status='PASS_EXACT_CONTENT_PARITY')
            path = folder / (key + '.json')
            remote = remote_root + '/reaudit-r1/' + arm + '/' + path.name
            h = write_json(path, value)
            row[key] = {'path': remote, 'sha256': h}
            outputs[remote] = h
            artifact_rows.append({'remote_path': remote, 'local_path': str(path), 'sha256': h, 'kind': key})
        arms[arm] = row
    argv = ['python', '-B', remote_root + '/scripts/prism_balance_ab_reaudit_m61.py', '--synthetic-test-only']
    execution = {'format': 'm61-reaudit-r1-execution-v1', 'revision': versions.REVISION, 'source_pins': pins,
                 'argv': argv, 'cwd': remote_root, 'started_at': 1000, 'runtime_pins': {'/synthetic/python': 'e' * 64},
                 'inputs': inputs, 'new_games': 0, 'new_optimizer_updates': 0, 'retries': 0,
                 'revision_script': {'path': argv[2], 'sha256': pins[argv[2]]}}
    execution_path = work / 'execution.json'
    execution_sha = write_json(execution_path, execution)
    receipt = {'format': 'm61-reaudit-r1-execution-receipt-v1', 'status': 'PASS_M61_REAUDIT_R1',
               'exit_code': 0, 'execution_sha256': execution_sha, 'execution_path': remote_root + '/reaudit-r1/execution.json',
               'source_pins': pins, 'inputs': inputs, 'outputs': outputs, 'arms': arms, 'argv': argv,
               'runtime_pins': execution['runtime_pins'], 'new_games': 0, 'new_optimizer_updates': 0,
               'retries': 0, 'old_receipts_preserved': True, 'failures': [],
               'started_at': 1000, 'ended_at': 1010, 'wall_seconds': 10}
    path = work / 'completion.json'
    completion_sha = write_json(path, receipt)
    source_map, artifact_map = work / 'local-source-map.json', work / 'local-artifact-map.json'
    source_sha = write_json(source_map, {'format': 'm61-reaudit-r1-local-map-v1', 'rows': source_rows})
    artifact_sha = write_json(artifact_map, {'format': 'm61-reaudit-r1-local-map-v1', 'rows': artifact_rows})
    # validate_reaudit reads the frozen config and matches every runtime source
    # hash against an executed cwd-relative pin; mirror that contract synthetically.
    config_hashes = {name: pins[remote_root + '/' + name] for name in
                     ('scripts/prism_balance_ab_reaudit_m61.py',
                      'training/prism_portable/tests/test_m61_reaudit.py',
                      'savedbefore-source/engine/ppo/model.py')}
    write_json(root / 'benchmarks/m61-prism-alpha-balance-ab.config.json',
               {'runtime': {'source_hashes': config_hashes}})
    fetch = {'format': 'm61-reaudit-r1-local-fetch-receipt-v1', 'status': 'PASS_FETCH_HASH_VERIFICATION',
             'completion': {'path': str(path), 'remote_path': remote_root + '/reaudit-r1/completion.json', 'sha256': completion_sha},
             'execution': {'path': str(execution_path), 'remote_path': receipt['execution_path'], 'sha256': execution_sha},
             'source_map': {'path': str(source_map), 'sha256': source_sha},
             'artifact_map': {'path': str(artifact_map), 'sha256': artifact_sha}, 'candidates': downloaded,
             'unfetched_inputs': [remote_root + '/unfetched-replay.json'], 'verified_at': 1011}
    write_json(work / 'local-fetch-receipt.json', fetch)
    return path, receipt, shas


class VersionRecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path, self.receipt, self.shas = setup_receipt(self.root)
        self.pins = patch.object(versions, 'CANDIDATE_SHAS', self.shas)
        self.pins.start()
        self.addCleanup(self.pins.stop)
        self.result = {'candidate_sha256': self.shas}
        self.fetch_path = self.path.with_name('local-fetch-receipt.json')

    def validate(self):
        return versions.validate_reaudit(self.root, self.path, self.result, self.fetch_path)

    def rewrite(self):
        digest = write_json(self.path, self.receipt)
        fetch = versions.read(self.fetch_path)
        fetch['completion']['sha256'] = digest
        write_json(self.fetch_path, fetch)

    def mapped_path(self, remote):
        for name in ('local-source-map.json', 'local-artifact-map.json'):
            rows = versions.read(self.path.with_name(name))['rows']
            for row in rows:
                if row['remote_path'] == remote:
                    return Path(row['local_path'])
        raise AssertionError('test map missing: ' + remote)

    def test_pass_binds_original_candidate_and_combined_tolerance(self):
        result = self.validate()
        self.assertEqual(result['revision'], versions.REVISION)
        self.assertEqual(set(result['candidates']), {'alpha', 'balance'})
        self.assertEqual(result['completion']['sha256'], versions.sha(self.path))
        self.assertEqual(result['source_manifest']['path'], versions.relative(self.root, self.path.with_name('local-source-map.json')))
        self.assertEqual(len(result['unfetched_inputs']), 1)
        self.assertGreater(self.receipt['arms']['alpha']['parity_max_abs_error'], 1e-4)

    def test_original_and_failed_receipts_cannot_register(self):
        for change in ({'format': 'm61-final-parity-v1'}, {'status': 'FAILED'},
                       {'exit_code': 1}, {'failures': ['game_id']},
                       {'new_games': 1}, {'new_optimizer_updates': 1},
                       {'retries': 1}, {'old_receipts_preserved': False}):
            with self.subTest(change=change):
                saved = copy.deepcopy(self.receipt)
                self.receipt.update(change)
                self.rewrite()
                with self.assertRaises(ValueError):
                    self.validate()
                self.receipt = saved
                self.rewrite()

    def test_execution_source_and_input_output_drift_rejected(self):
        targets = [self.path.with_name('execution.json'),
                   self.mapped_path(next(iter(self.receipt['source_pins']))),
                   self.mapped_path(self.receipt['arms']['alpha']['candidate_path']),
                   self.mapped_path(next(iter(self.receipt['outputs']))),
                   self.path.with_name('local-source-map.json'), self.path.with_name('local-artifact-map.json')]
        for target in targets:
            with self.subTest(target=target):
                before = target.read_bytes()
                target.write_bytes(before + b' ')
                with self.assertRaisesRegex(ValueError, 'drift'):
                    self.validate()
                target.write_bytes(before)

    def test_candidate_and_companion_drift_rejected_even_with_rebound_outputs(self):
        for key in ('candidate_path', 'manifest_path'):
            with self.subTest(key=key):
                row = self.receipt['arms']['alpha']
                target = self.mapped_path(row[key])
                before = target.read_bytes()
                old = copy.deepcopy(self.receipt)
                target.write_bytes(before + b' ')
                self.receipt['outputs'][str(target)] = versions.sha(target)
                self.rewrite()
                with self.assertRaisesRegex(ValueError, 'drift'):
                    self.validate()
                target.write_bytes(before)
                self.receipt = old
                self.rewrite()

    def test_missing_or_unbound_source_manifest_rejected(self):
        del self.receipt['source_pins']
        self.rewrite()
        with self.assertRaisesRegex(ValueError, 'source manifest'):
            self.validate()

    def test_failed_arm_and_parity_coverage_rejected(self):
        for key, change in (('checkpoint_validation', {'status': 'FAILED'}),
                            ('final_parity', {'boundary_inputs': 67}),
                            ('final_parity', {'rtol': 0})):
            with self.subTest(key=key, change=change):
                old_receipt = copy.deepcopy(self.receipt)
                row = self.receipt['arms']['balance'][key]
                target = self.mapped_path(row['path'])
                before = target.read_bytes()
                value = json.loads(before)
                value.update(change)
                row['sha256'] = write_json(target, value)
                self.receipt['outputs'][str(target)] = row['sha256']
                self.rewrite()
                with self.assertRaises(ValueError):
                    self.validate()
                target.write_bytes(before)
                self.receipt = old_receipt
                self.rewrite()

    def test_outside_project_evidence_rejected(self):
        with tempfile.TemporaryDirectory() as other:
            path = Path(other) / 'weights.json'
            path.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'archived inside project'):
                versions.checked_descriptor(self.root, {'path': str(path), 'sha256': versions.sha(path)}, 'outside')

    def test_full_tables_remapped_and_historical_provenance_literal(self):
        original = (ROOT / 'docs/prism/m61-prism-alpha-balance-ab-evaluation.md').read_text(encoding='utf-8')
        mapped = versions.remapped_report(original)
        source = original[original.index('## 同种子共同锚点：'):]
        self.assertEqual(sum(line.startswith('|') for line in source.splitlines()),
                         sum(line.startswith('|') for line in mapped.splitlines()))
        boundary = mapped.index('## 冻结执行合同、模型与运行身份')
        for old, new in versions.OLD_LABELS.items():
            self.assertNotIn(old, mapped[:boundary])
            if old in source[:source.index('## 冻结执行合同、模型与运行身份')]:
                self.assertIn(new, mapped[:boundary])
        self.assertEqual(mapped[boundary:], original[original.index('## 冻结执行合同、模型与运行身份'):])
        for required in ('先手 P0', '后手 P1', '局均购入 0 VP卡', '局均购入 5 VP卡',
                         '局均 黑 折扣', '预留买回 / 获取', '选贵族 次数', '跳过 次数',
                         '开发评测（仅描述）', '独立验收', 'NOT_MEASURED', 'INCONCLUSIVE'):
            self.assertIn(required, mapped)

    def test_original_local_evidence_is_frozen_and_verdict_retained(self):
        with patch.object(versions, 'CANDIDATE_SHAS', REAL_CANDIDATE_SHAS):
            config, result, _ = versions.frozen_inputs(ROOT)
        self.assertEqual(result['comparison']['verdict'], 'INCONCLUSIVE')
        self.assertEqual(config['base_model']['sha256'], versions.PARENT_SHA)

    def test_archive_collision_checked_before_any_output_and_idempotent(self):
        actual_config = json.loads((ROOT / 'benchmarks/m61-prism-alpha-balance-ab.config.json').read_text())
        actual_result = json.loads((ROOT / versions.WORK / 'result.json').read_text())
        actual_execution = json.loads((ROOT / versions.WORK / 'execution.json').read_text())
        write_json(self.root / versions.WORK / 'result.json', actual_result)
        path = self.root / 'docs/prism/m61-prism-alpha-balance-ab-evaluation.md'
        path.parent.mkdir(parents=True)
        path.write_bytes((ROOT / 'docs/prism/m61-prism-alpha-balance-ab-evaluation.md').read_bytes())
        registrar = self.root / 'scripts/prism_m61_version_records.py'
        registrar.parent.mkdir(parents=True, exist_ok=True)
        registrar.write_bytes((ROOT / 'scripts/prism_m61_version_records.py').read_bytes())
        with patch.object(versions, 'frozen_inputs', return_value=(actual_config, actual_result, actual_execution)):
            actual_result['candidate_sha256'] = self.shas
            before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
            outputs = versions.register(self.root, self.path, self.fetch_path, check_only=True)
            self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
            self.assertEqual(len(outputs), 8)
            collision = self.root / 'local-artifacts/prism/balance-v0.1.0/weights.json'
            collision.parent.mkdir(parents=True)
            collision.write_text('different existing immutable identity')
            with self.assertRaisesRegex(ValueError, 'immutable identity collision'):
                versions.register(self.root, self.path, self.fetch_path)
            self.assertFalse((self.root / 'benchmarks/m61-prism-alpha-v0.1.4.model.json').exists())
            collision.unlink()
            first = versions.register(self.root, self.path, self.fetch_path)
            second = versions.register(self.root, self.path, self.fetch_path)
            self.assertEqual(first, second)
            balance = json.loads((self.root / 'benchmarks/m61-prism-balance-v0.1.0.model.json').read_text())
            self.assertEqual(balance['parent']['model_id'], 'prism-alpha-v0.1.3')
            self.assertFalse(balance['confirmed_enhancement']['overall_anchor_strength'])
            self.assertFalse(balance['studio_deployed'])
            self.assertEqual(balance['runtime']['temperature'], 1.0)
            self.assertEqual(balance['comparison']['verdict'], 'INCONCLUSIVE')


if __name__ == '__main__':
    unittest.main()
