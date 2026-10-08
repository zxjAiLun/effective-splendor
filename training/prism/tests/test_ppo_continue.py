"""Synthetic continuation checks: no real games or formal environment seeds."""
import copy
from pathlib import Path

import pytest
import torch

from scripts import prism_ppo_continue as continuation
from scripts import prism_ppo_campaign_supervisor as supervisor
from training.prism.io import canonical_hash, read_json, sha256_file, tensor_identity, write_json
from training.prism.ppo.coordinator import Run, source_identity
from training.prism.ppo.learner import Learner, prepare_batch
from training.prism.ppo.model import new_model
from training.prism.ppo.runtime import capture_rng, restore_rng
from training.prism.ppo.sampling import Behavior
from training.prism.tests.ppo_support import game
from training.prism.tests.test_ppo_arena import spec, pin
from training.prism.tests.test_ppo_recovery import synthetic_submit, finish


@pytest.fixture
def completed(spec, tmp_path, monkeypatch):
    old_config = copy.deepcopy(spec['run'])
    old_config['format'] = 'prism-ppo-run-v1'
    old_config.pop('arena_contract_sha256')
    old_config['budget'].update(max_cycles=1, max_jobs=1)
    old = Run.create(tmp_path / 'old', old_config, spec['parent_weights'])
    old.begin_cycle([{'job_id': 'source-job', 'actor': 0, 'opponent_id': 'one', 'environment_seed': 0}])
    synthetic_submit(old, monkeypatch, tmp_path, 'source-job')
    old.seal(); finish(old)
    old.export(tmp_path / 'old-export')
    spec['parent_weights'] = str(tmp_path / 'old-export' / 'weights.json')
    spec['run']['parent_sha256'] = sha256_file(spec['parent_weights'])
    spec['run'].update(run_id='synthetic-continuation-only', seed=987)
    pin(spec)
    commit = read_json(old.root / 'commits' / (old.parent + '.json'))
    lineage = {'format': continuation.FORMAT, 'authorized_by': 'user-continue-training',
        'contract_sha256': canonical_hash(spec), 'source_run': str(old.root),
        'source_identity': old.identity, 'source_commit': old.parent,
        'source_payload_sha256': commit['payload'], 'source_config_sha256': sha256_file(old.root / 'config.json'),
        'source_sha256': source_identity(), 'initializer_sha256': sha256_file(continuation.__file__),
        'source_policy_tensor_sha256': tensor_identity(old.learner.model.policy.state_dict()),
        'inherited_optimizer_steps': old.state['global_step']}
    return old, spec, lineage


def test_continuation_exact_state_fresh_counters_and_recovery(completed, tmp_path):
    old, spec, lineage = completed
    before = sha256_file(old.root / 'HEAD.json')
    receipt = continuation.initialize(tmp_path / 'new', spec, lineage)
    new = Run.open(tmp_path / 'new' / 'run')
    assert new.state['phase'] == 'READY'
    assert new.state['cycle'] == new.state['global_step'] == new.state['update_attempts'] == 0
    assert new.state['attempts'] == new.state['decisions'] == 0
    assert new.state['jobs'] == {} and new.state['all_jobs'] == new.state['consumed'] == []
    assert new.state['batch'] is new.state['snapshot'] is None
    assert tensor_identity(new.state['model']) == tensor_identity(old.state['model'])
    assert continuation.state_digest(new.state['optimizer']) == continuation.state_digest(old.state['optimizer'])
    assert continuation.state_digest(new.state['rng']) == continuation.state_digest(old.state['rng'])
    assert continuation.verify_initialization(tmp_path / 'new', lineage)['inherited_optimizer_steps'] == 1
    assert receipt['identity'] != old.identity
    assert sha256_file(old.root / 'HEAD.json') == before
    with pytest.raises(ValueError, match='must not exist'):
        continuation.initialize(tmp_path / 'new', spec, lineage)
    # Receipt publication gap cannot reset/import again; committed origin is authoritative.
    (tmp_path / 'new' / 'continuation-receipt.json').unlink()
    assert continuation.verify_initialization(tmp_path / 'new', lineage)['source_commit'] == old.parent
    new.begin_cycle(spec['cycles'][0])
    resumed = Run.open(new.root)
    assert resumed.state['phase'] == 'COLLECTING' and resumed.state['cycle'] == 1
    assert continuation.verify_initialization(tmp_path / 'new', lineage)['source_commit'] == old.parent


def test_next_optimizer_step_matches_preserved_adamw(completed, tmp_path):
    old, spec, lineage = completed
    continuation.initialize(tmp_path / 'new', spec, lineage)
    new = Run.open(tmp_path / 'new' / 'run')
    behavior = Behavior(old.learner.model, catalog_fingerprint=old.config['catalog_fingerprint'],
                        action_seed=1, runtime=old.runtime)
    batch = prepare_batch([game(behavior)], behavior, old.ppo, max_decisions=100, verify=False)
    a = Learner(new_model(style_enabled=False, state_dict=new.state['model']), old.ppo)
    a.load_optimizer(copy.deepcopy(new.state['optimizer']))
    b = Learner(new_model(style_enabled=False, state_dict=old.state['model']), old.ppo)
    b.load_optimizer(copy.deepcopy(old.state['optimizer']))
    a.step(batch, list(range(len(batch['rows']))))
    b.step(batch, list(range(len(batch['rows']))))
    assert tensor_identity(a.model.state_dict()) == tensor_identity(b.model.state_dict())
    assert continuation.state_digest(a.optimizer.state_dict()) == continuation.state_digest(b.optimizer.state_dict())
    assert all(slot['step'].item() == 2 for slot in a.optimizer.state.values())


@pytest.mark.parametrize('field', ['source_commit', 'source_payload_sha256', 'source_config_sha256',
                                  'source_sha256', 'initializer_sha256', 'source_policy_tensor_sha256',
                                  'inherited_optimizer_steps', 'contract_sha256'])
def test_lineage_drift_rejected_before_campaign_created(completed, tmp_path, field):
    _, spec, lineage = completed
    changed = dict(lineage)
    changed[field] = 12345 if field == 'inherited_optimizer_steps' else 'f'*64
    with pytest.raises(ValueError):
        continuation.initialize(tmp_path / 'new', spec, changed)
    assert not (tmp_path / 'new').exists()


def test_changed_ppo_and_incomplete_parent_rejected(completed, tmp_path):
    old, spec, lineage = completed
    changed = copy.deepcopy(spec)
    changed['run']['ppo']['lr'] *= 2
    pin(changed)
    altered = dict(lineage, contract_sha256=canonical_hash(changed))
    with pytest.raises(ValueError, match='changed ppo'):
        continuation.validate_source(changed, altered)
    with old.store.lock():
        old.state['phase'] = 'COLLECTING'
        old._commit()
    record = read_json(old.root / 'commits' / (old.parent + '.json'))
    altered = dict(lineage, source_commit=old.parent, source_payload_sha256=record['payload'])
    with pytest.raises(ValueError, match='fully committed'):
        continuation.validate_source(spec, altered)


def test_changed_rng_origin_rejected_on_resume(completed, tmp_path):
    _, spec, lineage = completed
    continuation.initialize(tmp_path / 'new', spec, lineage)
    changed = dict(lineage, inherited_optimizer_steps=99)
    with pytest.raises(ValueError, match='lineage drift'):
        continuation.verify_initialization(tmp_path / 'new', changed)


def test_resource_resume_charges_gap_and_preserves_deadline():
    state = supervisor.prepare_state(None, 'identity', 'run', 1000, 1)
    state['sessions'].append({'status': 'RUNNING', 'cpu_reservation': 100,
        'logical_cpus': 4, 'snapshot': {'observed_at': 10, 'user_cpu_seconds': 20}})
    resumed = supervisor.prepare_state(state, 'identity', 'run', 1000, 15)
    assert resumed['deadline'] == 1000
    assert resumed['sessions'][0]['user_cpu_seconds'] == 40
    assert supervisor.remaining_cpu(resumed['sessions'], 100) == 60
    assert supervisor.prepare_state(resumed, 'identity', 'run', 1000, 25)['sessions'][0]['user_cpu_seconds'] == 40
    for values in [('other', 'run', 1000), ('identity', 'other', 1000), ('identity', 'run', 2000)]:
        with pytest.raises(ValueError, match='drift'):
            supervisor.prepare_state(resumed, *values, 25)
