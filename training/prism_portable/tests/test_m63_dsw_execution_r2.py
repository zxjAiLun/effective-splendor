"""Regression checks for the explicit platform port, never running matches."""
import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import prism_m63_dsw_execution_r2 as port
from scripts import prism_building_evaluation_m63 as frozen
from training.prism_portable.engine.ppo import building_timed


def test_path_mapping_preserves_unrelated_content_and_input():
    value = {'path': port.ORIGINAL_ROOT + '/audit-beta/x.json',
             'sha': 'a' * 64, 'message': 'evidence ' + port.ORIGINAL_ROOT,
             'outside': '/home/ubuntu/splendor-ppo-m57/build/splendor'}
    before = copy.deepcopy(value)
    actual = port.relocate(value, Path('/mnt/workspace/test'))
    assert value == before
    assert actual['path'] == str(Path('/mnt/workspace/test')) + '/audit-beta/x.json'
    assert all(actual[k] == value[k] for k in ('sha', 'message', 'outside'))


def test_literal_config_is_preserved_when_mapping_native_descriptors(tmp_path):
    path = tmp_path / frozen.CONFIG
    path.parent.mkdir()
    config = {'runtime': {'cloud_root': port.ORIGINAL_ROOT},
              'evaluation': {'native_path_and_sha256': {}},
              'training': {'campaign': port.ORIGINAL_ROOT + '/campaigns/test'}}
    path.write_text(json.dumps(config))
    original_bytes = path.read_bytes()
    native = {'files': {'bin/' + name: {'sha256': 'a' * 64} for name in port.NATIVES.values()}}
    mapped = port.mapped_reader(tmp_path, native)(path)
    assert path.read_bytes() == original_bytes
    assert mapped['runtime']['cloud_root'] == str(tmp_path)
    assert mapped['evaluation']['native_path_and_sha256'] == mapped['runtime']['engine']
    assert mapped['runtime']['engine']['path'] == str(tmp_path / 'bin/splendor')


def test_collector_uses_prepared_economy_link_without_mutating_namespace():
    namespace = dict(frozen.alpha.__dict__, ART=Path('/a/evaluation'), ROOT=Path('/a'))
    isolated = port.collector(namespace)
    assert isolated.__globals__['ROOT'] == Path('/a/evaluation/collector-root')
    assert namespace['ROOT'] == Path('/a')
    assert isolated.__code__ is frozen.alpha.collect.__code__


def test_projection_supplies_valid_frozen_timed_wrapper():
    captured = []
    def extract(row, projected, replay, config):
        building_timed.validate_timed_building_config(config)
        captured.append(config)
        return 'profiles'
    adapter = port.projection_profile_adapter(extract)
    assert adapter({}, {}, {}, frozen.default_building_config()) == 'profiles'
    assert captured == [frozen.default_timed_building_config()]
    bad = frozen.default_building_config(); bad['global_use_cap'] = 100
    with pytest.raises(ValueError): adapter({}, {}, {}, bad)


def test_only_parallelism_changes_original_resource_contract():
    assert {k: v for k, v in port.LIMITS.items() if k not in ('workers', 'cpu_quota_percent')} == {
        k: v for k, v in frozen.LIMITS.items() if k not in ('workers', 'cpu_quota_percent')}
    assert port.LIMITS['workers'] == 3
    assert port.LIMITS['infrastructure_retries'] == 0
    assert port.LIMITS['physical_games'] == 10304
    assert frozen.ACTION_SEED == 63042001
    assert len(frozen.GATES) == 10


def test_context_restores_frozen_modules_after_failure(tmp_path):
    before = {k: getattr(frozen, k) for k in ('ROOT', 'CLOUD', 'LIMITS', 'read', 'Monitor', 'verify',
                                             'audit_evidence', 'isolated_replay_collector')}
    assert not hasattr(frozen, 'subprocess')
    with patch.object(port, 'READ', return_value={'files': {}}):
        with pytest.raises(RuntimeError):
            with port.context(tmp_path):
                assert frozen.subprocess is port.subprocess
                assert frozen.LIMITS['workers'] == 3
                raise RuntimeError('injected before dispatch')
    assert all(getattr(frozen, k) is v for k, v in before.items())
    assert not hasattr(frozen, 'subprocess')


def test_saved_metrics_runtime_exposes_only_unchanged_stdlib_helpers():
    from scripts.prism_m63_dsw_metrics_runtime import extract_functions
    from training.prism_portable.engine.io import canonical_hash
    root = Path(__file__).resolve().parents[3]
    io = extract_functions(root / 'training/prism_portable/engine/io.py', ['canonical_hash'])
    contract = extract_functions(root / 'training/prism_portable/engine/ppo/contract.py', ['exact', 'integer'])
    for value in ({'中文': [True, None, 1.25]}, {'z': 2, 'a': 1}, []):
        assert io.canonical_hash(value) == canonical_hash(value)
    assert 'torch' not in io.__dict__ and not hasattr(io, 'save_checkpoint')
    contract.exact({'a': 1}, {'a'}, 'test')
    assert contract.integer(2, 1, 3, 'test') == 2
    with pytest.raises(ValueError): contract.integer(True, 1, 3, 'test')
    with pytest.raises(ValueError): contract.exact({'a': 1, 'b': 2}, {'a'}, 'test')
