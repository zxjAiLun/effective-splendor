"""Fixed-only watcher synthetic tests, no pool or actual games."""
import copy
from pathlib import Path

import pytest

from scripts import prism_ppo_fixed_watch as watch
from training.prism.tests.test_ppo_cloud2_controller import setup


@pytest.fixture
def plan(setup, tmp_path):
    original, _, evaluator = setup
    plan = copy.deepcopy(original)
    plan.update(format=watch.FORMAT)
    plan['checkpoints'] = []
    source = watch.load(original['checkpoints'][0]['weights_ready'])
    for cycle in (1, 4, 8):
        ready = tmp_path / f'c{cycle}.ready.json'
        watch.save(ready, dict(source, cycle=cycle))
        plan['checkpoints'].append(dict(label=f'c{cycle}', cycle=cycle, weights_ready=str(ready)))
    path = tmp_path / 'fixed-plan.json'
    watch.save(path, plan)
    return path, plan, evaluator


def test_fixed_only_complete_cache_and_no_pool_changes(plan, setup):
    path, value, evaluator = plan
    _, store, _ = setup
    before = [m.to_dict() if hasattr(m, 'to_dict') else (m.id, m.config, m.elo, m.enabled) for m in store.list_models()]
    state = watch.run(path, evaluator=evaluator)
    assert state['complete'] and evaluator.started == ['parent', 'c1', 'c4', 'c8']
    assert watch.load(Path(value['root']) / 'c8-paired-delta.json')['mean_delta_score_rate'] == .25
    assert watch.run(path, evaluator=evaluator) == state
    assert evaluator.started == ['parent', 'c1', 'c4', 'c8']
    assert before == [m.to_dict() if hasattr(m, 'to_dict') else (m.id, m.config, m.elo, m.enabled) for m in store.list_models()]


def test_deadline_resume_does_not_restart_parent_or_reset_time(plan):
    path, value, evaluator = plan
    ready = Path(value['checkpoints'][0]['weights_ready'])
    saved = watch.load(ready); ready.unlink()
    clock = [10]
    def tick(_): clock[0] += 101
    with pytest.raises(TimeoutError):
        watch.run(path, evaluator=evaluator, clock=lambda: clock[0], sleep=tick)
    state = watch.load(Path(value['root']) / 'fixed-watch-state.json')
    assert state['deadline'] == 110 and evaluator.started == ['parent']
    watch.save(ready, saved)
    with pytest.raises(TimeoutError):
        watch.run(path, evaluator=evaluator, clock=lambda: 120)
    assert evaluator.started == ['parent']
    assert watch.load(Path(value['root']) / 'fixed-watch-state.json')['deadline'] == 110


def test_ready_hash_and_plan_drift_rejected(plan):
    path, value, evaluator = plan
    ready = Path(value['checkpoints'][0]['weights_ready'])
    watch.save(ready, dict(watch.load(ready), sha256='f'*64))
    with pytest.raises(ValueError, match='weight drift'):
        watch.run(path, evaluator=evaluator)
    value['action_seed'] = 99
    watch.save(path, value)
    with pytest.raises(ValueError, match='plan drift'):
        watch.run(path, evaluator=evaluator)
