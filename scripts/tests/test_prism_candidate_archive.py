import copy
import hashlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import prism_candidate_archive as archive


ROOT = Path(__file__).resolve().parents[2]


class CandidateArchiveTests(unittest.TestCase):
    def setUp(self):
        self.policy = archive.read(ROOT / 'benchmarks/prism-style-bands-v020.policy.json')
        self.reference = self.profile(self.policy['reference_sha256'])
        self.candidate = copy.deepcopy(self.reference)
        self.candidate['sha256'] = 'c' * 64
        self.candidate['metrics'].update({
            'big_printed_vp': 0.7,
            'low_share': 0.46,
            'first_big_main': 8.0,
            'first_big_coverage': 0.49,
        })

    def profile(self, sha256):
        seed_by_opponent = {'a' * 64: [4, 5], 'b' * 64: [90, 90]}
        entries = [
            dict(opponent=opponent, seed=seed, seat=seat)
            for opponent, limits in seed_by_opponent.items()
            for seed in range(limits[0], limits[1] + 1)
            for seat in (0, 1)
        ]
        keys = sorted((row['opponent'], row['seed'], row['seat']) for row in entries)
        return dict(
            sha256=sha256,
            rules_sha256='d' * 64,
            mode='both-greedy',
            metrics_semantics=self.policy['metrics_semantics_id'],
            seed_by_opponent=seed_by_opponent,
            grid=dict(entries=entries, sha256=archive.canonical(keys), games=len(entries)),
            metrics={
                'big_printed_vp': 0.0,
                'low_share': 0.49,
                'low_cards': 0.0,
                'first_big_main': 10.0,
                'first_big_coverage': 0.50,
                'early_low_cards': 0.0,
                'early_discount_redemptions': 0.0,
                'noble_coverage': 0.0,
            },
        )

    def assert_unclassified(self, candidate=None, reference=None, policy=None):
        result = archive.classify_matched_profiles(
            candidate or self.candidate,
            reference or self.reference,
            policy or self.policy,
        )
        self.assertEqual(result['route'], 'undetermined')
        self.assertEqual(result['evidence_level'], 'INSUFFICIENT')
        return result

    def test_expected_grid_uses_each_opponents_seed_range(self):
        contract = {'evaluation': {
            'common_seed_by_opponent': {'short': [10, 11], 'single': [70, 70]},
            'coverage_seed_by_opponent': {'wide': [500, 502]},
            'direct_seed_start': 900,
            'direct_seed_end': 901,
        }}

        expected = {
            (model, opponent, seed, seat)
            for model in ('a', 'base')
            for opponent, limits in {'short': [10, 11], 'single': [70, 70], 'wide': [500, 502]}.items()
            for seed in range(limits[0], limits[1] + 1)
            for seat in (0, 1)
        }
        expected.update(('a', 'parent', seed, seat)
                        for seed in (900, 901) for seat in (0, 1))

        self.assertEqual(archive.expected_grid(contract), expected)
        self.assertEqual(len(expected), 28)

    def test_expected_grid_rejects_reversed_opponent_seed_range(self):
        contract = {'evaluation': {
            'common_seed_by_opponent': {'bad': [8, 7]},
            'coverage_seed_by_opponent': {},
            'direct_seed_start': 1,
            'direct_seed_end': 1,
        }}
        with self.assertRaisesRegex(ValueError, 'invalid seed range'):
            archive.expected_grid(contract)

    def test_fixed_style_anchor_is_required(self):
        wrong_anchor = copy.deepcopy(self.reference)
        wrong_anchor['sha256'] = 'e' * 64
        self.assert_unclassified(reference=wrong_anchor)

    def test_matched_profiles_classify_against_the_exact_fixed_anchor(self):
        result = archive.classify_matched_profiles(self.candidate, self.reference, self.policy)
        self.assertEqual(result['route'], 'Alpha')
        self.assertEqual(result['evidence_level'], 'DESCRIPTIVE')
        self.assertEqual(result['fixed_anchor_sha256'], self.policy['reference_sha256'])

    def test_profile_mode_mismatch_is_rejected(self):
        changed = copy.deepcopy(self.candidate)
        changed['mode'] = 'sampling'
        self.assert_unclassified(candidate=changed)

    def test_two_sampling_profiles_are_not_a_greedy_style_match(self):
        candidate = copy.deepcopy(self.candidate)
        reference = copy.deepcopy(self.reference)
        candidate['mode'] = reference['mode'] = 'sampling'
        self.assert_unclassified(candidate=candidate, reference=reference)

    def test_rules_mismatch_is_rejected(self):
        changed = copy.deepcopy(self.candidate)
        changed['rules_sha256'] = 'f' * 64
        self.assert_unclassified(candidate=changed)

    def test_metrics_semantics_mismatch_is_rejected(self):
        candidate = copy.deepcopy(self.candidate)
        reference = copy.deepcopy(self.reference)
        candidate['metrics_semantics'] = reference['metrics_semantics'] = 'different-window-v2'
        self.assert_unclassified(candidate=candidate, reference=reference)

    def test_grid_hash_drift_is_rejected(self):
        changed = copy.deepcopy(self.candidate)
        changed['grid']['sha256'] = '0' * 64
        self.assert_unclassified(candidate=changed)

    def test_missing_grid_entry_is_rejected_even_when_profiles_match(self):
        candidate = copy.deepcopy(self.candidate)
        reference = copy.deepcopy(self.reference)
        for profile in (candidate, reference):
            profile['grid']['entries'].pop()
            keys = sorted((row['opponent'], row['seed'], row['seat'])
                          for row in profile['grid']['entries'])
            profile['grid']['sha256'] = archive.canonical(keys)
            profile['grid']['games'] -= 1
        self.assert_unclassified(candidate=candidate, reference=reference)

    def test_duplicate_grid_entry_is_rejected_even_with_recomputed_hash(self):
        changed = copy.deepcopy(self.candidate)
        entries = changed['grid']['entries']
        entries[-1] = copy.deepcopy(entries[0])
        keys = sorted((row['opponent'], row['seed'], row['seat']) for row in entries)
        changed['grid']['sha256'] = archive.canonical(keys)
        self.assert_unclassified(candidate=changed)

    def test_unmatched_per_opponent_seed_ranges_are_rejected(self):
        changed = copy.deepcopy(self.candidate)
        changed['seed_by_opponent']['a' * 64] = [4, 6]
        entries = [
            dict(opponent=opponent, seed=seed, seat=seat)
            for opponent, limits in changed['seed_by_opponent'].items()
            for seed in range(limits[0], limits[1] + 1)
            for seat in (0, 1)
        ]
        keys = sorted((row['opponent'], row['seed'], row['seat']) for row in entries)
        changed['grid'] = dict(entries=entries, sha256=archive.canonical(keys), games=len(entries))
        self.assert_unclassified(candidate=changed)

    def test_missing_temporal_metric_stays_unmeasured(self):
        changed = copy.deepcopy(self.candidate)
        changed['metrics']['first_big_main'] = None
        result = self.assert_unclassified(candidate=changed)
        self.assertEqual(result['missing_by_route']['Alpha'], ['first_big_main'])

    def test_duplicate_json_keys_are_rejected_at_every_object_depth(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'duplicate.json'
            path.write_text('{"outer":{"value":1,"value":2}}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'duplicate JSON key: value'):
                archive.read(path)

    def test_archive_build_only_writes_candidate_artifacts_and_never_releases(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs = root / 'inputs'
            inputs.mkdir()

            def write_json(path, value):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(value, separators=(',', ':')) + '\n', encoding='utf-8')
                return path

            weights = inputs / 'weights.bin'
            weights.write_bytes(b'candidate weights')
            candidate_sha = hashlib.sha256(weights.read_bytes()).hexdigest()
            parent_sha = '1' * 64
            contract = {'base_model': {'sha256': parent_sha}, 'evaluation': {
                'common_opponents': ['anchor'],
                'common_seed_by_opponent': {'anchor': [1, 1]},
                'coverage_seed_by_opponent': {},
            }}
            contract_path = write_json(inputs / 'contract.json', contract)
            audit = {'checkpoint': {'status': 'PASS', 'cycle': 20, 'weights_sha256': candidate_sha}}
            audit_path = write_json(inputs / 'audit.json', audit)
            registry = {'parent_sha256': parent_sha, 'training_rngs': [12], 'models': {
                'a': {'sha256': candidate_sha, 'audit_sha256': archive.digest(audit_path)},
            }}
            registry_path = write_json(inputs / 'registry.json', registry)
            policy = {'reference_sha256': '2' * 64, 'metrics_semantics_id': 'own-Main-test-v1'}
            policy_path = write_json(inputs / 'policy.json', policy)
            replay_manifest = write_json(inputs / 'replay-manifest.json', {})
            result = {
                'source_config_sha256': archive.digest(contract_path),
                'candidate_registry_sha256': archive.digest(registry_path),
                'candidate_sha256': {'a': candidate_sha, 'base': parent_sha},
                'acceptance_policy': contract['evaluation'],
                'planned_games': 2,
                'games': 2,
                'pairs': [
                    {'candidate': model, 'opponent': 'anchor', 'candidate_metrics': {'score_rate': 0.5},
                     'opponent_metrics': {'score_rate': 0.5}}
                    for model in ('a', 'base')
                ],
                'per_training_seed': {'a': {'direct_parent': {'mean': 0.56, 'ci95': [0.53, 0.59]}}},
                'published': False,
                'default_replaced': False,
            }
            result_path = write_json(inputs / 'result.json', result)
            input_paths = {
                'result': result_path,
                'contract': contract_path,
                'weights': weights,
                'registry': registry_path,
                'audit': audit_path,
                'style_policy': policy_path,
                'replay_manifest': replay_manifest,
            }
            spec = {
                'format': 'prism-candidate-archive-spec-v1',
                'candidate': {'label': 'M75 c20', 'round': 'M75', 'checkpoint': 'c20',
                              'cycle': 20, 'sha256': candidate_sha},
                'inputs': {
                    key: {'path': path.relative_to(root).as_posix(), 'sha256': archive.digest(path)}
                    for key, path in input_paths.items()
                },
                'output_prefix': 'archive/m75-candidate',
            }
            spec_path = write_json(root / 'spec.json', spec)
            script_dir = root / 'scripts'
            script_dir.mkdir()
            (script_dir / 'prism_replay_profile.py').write_text('# isolated profile fixture\n', encoding='utf-8')

            opponent_identity = '3' * 64
            rows = [
                {'model': model, 'opponent': 'anchor', 'opponent_identity': opponent_identity,
                 'seed': 1, 'seat': 0, 'score': 0.5,
                 'replay_path': replay_manifest}
                for model in ('a', 'base')
            ]
            aggregate = {'low_cards': 1.0, 'low_share': 0.5, 'big_printed_vp': 2.0,
                         'noble_coverage': 0.1, 'vp_main': 0.5}
            temporal = {'games': 1, 'first_big_main': None, 'first_big_coverage': 0.0,
                        'early_low_cards': 0.0, 'early_discount_redemptions': 0.0}
            route = {'route': 'undetermined', 'evidence_level': 'INSUFFICIENT'}
            replay_profile = types.ModuleType('scripts.prism_replay_profile')
            replay_profile.profile_replay = lambda replay, seat: {}
            replay_profile.aggregate_profiles = lambda profiles: temporal
            replay_profile.profile_saved_replays = lambda data: {
                'profiles': {r['game_key']: [{'seat':0},{'seat':1}] for r in data},
                'verify_receipt': {'status':'PASS','games_verified':len(data)},
            }
            with (
                patch.dict(sys.modules, {'scripts.prism_replay_profile': replay_profile}),
                patch.object(archive, 'load_evaluation', return_value=(rows, [], 'rules')),
                patch.object(archive, 'verify_profile_totals'),
                patch('scripts.prism_style_atlas.aggregate', return_value=aggregate),
                patch.object(archive, 'classify_matched_profiles', return_value=route),
            ):
                card, receipt = archive.build(spec_path, root=root)

            self.assertEqual(card['publication'], {
                'published': False, 'default_replaced': False, 'deployed': False,
                'evidence': 'source result plus owner authorization; this archive allocates no release version',
            })
            self.assertEqual(card['new_games'], 0)
            self.assertNotIn('release_version', card)
            self.assertEqual(receipt['status'], 'PASS_OFFLINE_ARCHIVE')
            self.assertEqual(receipt['new_games'], 0)
            self.assertEqual(
                {path.name for path in (root / 'archive').iterdir()},
                {'m75-candidate.json', 'm75-candidate.md', 'm75-candidate.html', 'm75-candidate.receipt.json'},
            )
            self.assertFalse((root / 'benchmarks/prism-v020-model-registry.json').exists())


if __name__ == '__main__':
    unittest.main()
