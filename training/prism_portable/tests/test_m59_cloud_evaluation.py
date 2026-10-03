"""Guard the M59 cloud adapter's frozen grid and no-repeat boundary; zero games."""
import copy
from pathlib import Path
import sys
import time
from unittest.mock import patch

import pytest

from scripts import prism_alpha_cloud_acceptance as cloud


@pytest.fixture
def inputs(tmp_path):
    frozen = cloud.read(Path(__file__).resolve().parents[3] / 'benchmarks/m59-prism-alpha-cloud-ppo.config.json')
    train = cloud.read(Path(__file__).resolve().parents[3] / 'benchmarks/m59-prism-alpha-cloud-ppo.train.json')['template']
    engine = Path(sys.executable)
    weight = tmp_path / 'weights.json'
    weight.write_text('{}')
    descriptor = {'program': str(engine), 'sha256': cloud.sha(engine),
                  'args': ['agent-prism-sample', '--weights', str(weight), '--seed', '59020001'],
                  'files': [{'path': str(weight), 'sha256': cloud.sha(weight)}]}
    candidates = {name: copy.deepcopy(descriptor) for name in ('base', 'candidate')}
    opponents = {name: copy.deepcopy(descriptor) for name in frozen['evaluation']['acceptance']['anchors']}
    return frozen, train, weight, (engine, candidates, opponents)


def test_frozen_physical_grid_and_distinct_stages(tmp_path, inputs):
    pilot, train, weight, assets = inputs
    with patch.object(cloud, 'descriptors', return_value=assets):
        plans = {stage: cloud.make_plan(tmp_path, tmp_path, stage, pilot, train, weight)
                 for stage in ('development', 'acceptance')}
    assert [len(plans[s]['shards']) for s in plans] == [2, 24]
    seen = {}
    for stage, plan in plans.items():
        grid = []
        for shard in plan['shards']:
            cfg = cloud.read(shard['config'])
            grid.extend((m, op, seed, seat) for m in cfg['candidates'] for op in cfg['opponents']
                        for seed in cfg['seeds'] for seat in (0, 1))
            assert cloud.sha(shard['config']) == shard['config_sha256']
            assert all(d['args'][-1] == '59020001' for d in cfg['candidates'].values())
        assert len(grid) == len(set(grid)) == (384 if stage == 'development' else 4096)
        seen[stage] = {g[2] for g in grid}
        if stage == 'acceptance':
            assert sum(op == 'base-t1' for _, op, _, _ in grid) == 1024
            assert {m for m, op, _, _ in grid if op == 'base-t1'} == {'candidate'}
    assert not seen['development'].intersection(seen['acceptance'])


def test_physical_budget_cannot_be_extended(tmp_path, inputs):
    pilot, train, weight, assets = inputs
    pilot = copy.deepcopy(pilot)
    pilot['evaluation']['development']['total_games'] += 2
    with patch.object(cloud, 'descriptors', return_value=assets), pytest.raises(ValueError, match='grid mismatch'):
        cloud.make_plan(tmp_path, tmp_path, 'development', pilot, train, weight)
    assert not (tmp_path / 'development/plan.json').exists()


def test_source_drift_stops_preflight(tmp_path):
    asset = tmp_path / 'worker.py'
    asset.write_text('before')
    execution = {'workers': 2, 'physical_games': 4480, 'infrastructure_retries': 0,
                 'memory_bytes': 8589934592, 'files': {str(asset): cloud.sha(asset)}}
    asset.write_text('after')
    with pytest.raises(ValueError, match='source/asset drift'):
        cloud.verify(tmp_path, execution)


def test_existing_partial_output_never_launches_again(tmp_path):
    stage = tmp_path / 'acceptance'
    stage.mkdir()
    output = stage / 'partial'
    output.mkdir()
    cloud.write(stage / 'plan.json', {'shards': [{'output': str(output), 'config': 'unused', 'games': 1}]})
    with patch.object(cloud.subprocess, 'Popen') as start, pytest.raises(ValueError, match='repeat/partial'):
        cloud.stage_run(tmp_path, tmp_path, 'acceptance', {'workers': 2}, time.monotonic())
    start.assert_not_called()


def test_existing_preparation_is_preserved(tmp_path):
    (tmp_path / 'evaluation').mkdir()
    old = tmp_path / 'evaluation/execution.json'
    old.write_text('old receipt')
    with patch.object(cloud, 'bindings', return_value=({}, {}, None)), pytest.raises(ValueError, match='refuse overwrite'):
        cloud.prepare(tmp_path)
    assert old.read_text() == 'old receipt'
