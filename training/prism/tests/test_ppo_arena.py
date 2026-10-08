"""Stage II tests: synthetic contracts/processes, never extra Splendor games."""
import copy
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from training.prism.export import export_weights
from training.prism.io import canonical_hash, read_json, sha256_file, write_json
from training.prism.model import PrismModel
from training.prism.ppo.arena import Campaign
from training.prism.ppo.coordinator import Run
from training.prism.ppo.execution import (absolute, arena_config, check_assets, seed_commitment,
                                         validate_spec, verify_completion, verify_report)
from training.prism.ppo.processes import ProcessTree
from training.prism.tests.ppo_support import CATALOG, game, run_config


def pin(spec):
    spec['run'].pop('arena_contract_sha256', None)
    spec['run']['opponents'] = {name: canonical_hash(value) for name, value in spec['opponents'].items()}
    spec['run']['arena_contract_sha256'] = canonical_hash(spec)
    return spec


@pytest.fixture
def spec(tmp_path):
    weights = tmp_path / 'synthetic-parent.json'
    export_weights(PrismModel(), weights, CATALOG)
    binary = tmp_path / 'NOT-AN-EXECUTABLE'
    binary.write_bytes(b'synthetic pinned asset, never executed')
    config = run_config(sha256_file(weights))
    config.update(format='prism-ppo-run-v2', auditor_sha256=sha256_file(binary))
    config['ppo'].update(passes=1, minibatch_size=40)
    config['budget'].update(max_cycles=2, max_jobs=8, max_attempts=10, max_optimizer_steps=2,
                            max_update_attempts=2, max_decisions=80)
    descriptor = {'program': str(binary), 'sha256': sha256_file(binary), 'args': ['synthetic-greedy'],
                  'files': {}, 'hello': {'agent_name': 'synthetic-greedy', 'agent_version': 'test'}, 'mode': 'greedy'}
    value = {'format': 'prism-ppo-arena-v1', 'run': config, 'parent_weights': str(weights),
             'arena': {'program': str(binary), 'sha256': sha256_file(binary), 'engine_version': 'test',
                       'protocol_version': 'test', 'ruleset': 'test'},
             'learner': {'program': str(binary), 'sha256': sha256_file(binary)},
             'opponents': {'one': descriptor, 'two': copy.deepcopy(descriptor)},
             'cycles': [[{'job_id': f'cycle{cycle}-opponent{opponent}-seat{seat}', 'actor': seat,
                          'opponent_id': opponent, 'environment_seed': cycle * 10 + i}
                         for i, opponent in enumerate(('one', 'two')) for seat in range(2)] for cycle in (1, 2)],
             'limits': {'max_plies': 10, 'max_infra_retries': 2, 'max_physical_decisions': 100,
                        'game_wall_seconds': 30, 'game_cpu_seconds': 30, 'campaign_cpu_seconds': 300,
                        'memory_bytes': 1024**3, 'handshake_timeout_ms': 1000,
                        'move_timeout_ms': 1000, 'shutdown_grace_ms': 1000}}
    return pin(value)


def fake_completion(spec, job, tmp_path, behavior='a'*64):
    directory = tmp_path / 'attempt'; directory.mkdir()
    replay_path, sidecar_path = directory / 'replay.json', directory / 'sidecar.jsonl'
    result = {'scores': [15, 10], 'ranks': [0, 1], 'winners': [0], 'reason': 'prestige_threshold'}
    replay = {'engine_version': 'test', 'ruleset': {'id': 'test'}, 'ruleset_fingerprint': CATALOG,
              'seed': job['environment_seed'], 'player_count': 2, 'final_state_hash': 'f'*64,
              'steps': [{}], 'result': result}
    report = {'format': 'effective-splendor-arena-report', 'version': 1, 'game_id': job['job_id'],
              'engine_version': 'test', 'protocol_version': 'test', 'ruleset': 'test',
              'ruleset_fingerprint': CATALOG, 'player_count': 2,
              'seed_commitment': seed_commitment(job['job_id'], job['environment_seed'], CATALOG),
              'agents': [{'seat': seat, 'agent_name': 'prism-ppo' if seat == job['actor'] else 'synthetic-greedy',
                          'agent_version': '0.1.0' if seat == job['actor'] else 'test'} for seat in range(2)],
              'outcome': {'status': 'completed', 'result': result, 'completed_plies': 1, 'replay_final_hash': 'f'*64}}
    write_json(replay_path, replay); sidecar_path.write_text('{}\n')
    write_json(directory / 'report.json', report)
    config = arena_config(spec, job, behavior, '127.0.0.1:12345', sidecar_path)
    write_json(directory / 'arena-config.json', config)
    argv = [absolute(spec['arena']['program']), 'run-rollout', '--config', str(directory / 'arena-config.json'),
            '--max-plies', '10', '--report-out', str(directory / 'report.json'), '--replay-out', str(replay_path),
            '--prefix-out', str(directory / 'prefix.json')]
    package = {'format': 'prism-ppo-arena-completion-v1', 'contract': spec, 'job': job, 'attempt': 1,
               'behavior_id': behavior, 'snapshot_sha256': 'b'*64, 'endpoint': '127.0.0.1:12345',
               'cwd': absolute('.'), 'arena_config': config, 'arena_argv': argv, 'pid': 123,
               'resources': {'returncode': 0, 'stop_reason': None},
               'files': {name: {'path': str(path), 'sha256': sha256_file(path)} for name, path in
                         [('report', directory / 'report.json'), ('replay', replay_path), ('sidecar', sidecar_path)]}}
    output = directory / 'completion.json'; write_json(output, package)
    return output, replay_path, sidecar_path, report, replay


def test_seed_commitment_rust_vector():
    assert seed_commitment('g1', 42, '0'*62+'aa') == 'e19e4c351e3ad58ecad21d70b9ddb89b0495a2c419c00d973c7835eb99ee87e8'


def test_spec_and_assets(spec):
    validate_spec(spec); check_assets(spec)
    Path(spec['learner']['program']).write_bytes(b'drift')
    with pytest.raises(ValueError, match='hash mismatch'):
        check_assets(spec)


@pytest.mark.parametrize('field', ['actor', 'seed', 'opponent'])
def test_budget_schedule_constraints(spec, field):
    if field == 'actor': spec['cycles'][0][0]['actor'] = 1
    if field == 'seed': spec['cycles'][0][0]['environment_seed'] = 1
    if field == 'opponent': spec['opponents']['one']['mode'] = 'sampling'
    pin(spec)
    with pytest.raises(ValueError): validate_spec(spec)


def test_regular_multi_seed_minibatch_pass_contract(spec):
    spec['run']['ppo'].update(passes=2, minibatch_size=3)
    spec['run']['budget'].update(max_optimizer_steps=200, max_update_attempts=210,
                                max_jobs=16, max_attempts=18, max_decisions=160)
    spec['limits']['max_physical_decisions'] = 180
    for cycle in spec['cycles']:
        more = [dict(job, job_id=job['job_id']+'-extra', environment_seed=job['environment_seed']+100)
                for job in cycle]
        cycle.extend(more)
    validate_spec(pin(spec))


def test_completion_good_and_changed_file(spec, tmp_path):
    job = spec['cycles'][0][0]
    output, replay, sidecar, _, _ = fake_completion(spec, job, tmp_path)
    assert verify_completion(spec['run'], job, 1, output, replay=replay, sidecar=sidecar, behavior_id='a'*64)['ranks'] == [0, 1]
    sidecar.write_text('changed')
    with pytest.raises(ValueError, match='hash mismatch'):
        verify_completion(spec['run'], job, 1, output, replay=replay, sidecar=sidecar, behavior_id='a'*64)


@pytest.mark.parametrize('field', ['seat', 'seed', 'result', 'rules', 'job', 'argv', 'attempt', 'behavior', 'snapshot', 'config'])
def test_completion_identity_tampering(spec, tmp_path, field):
    job = spec['cycles'][0][0]
    output, replay, sidecar, report, replay_data = fake_completion(spec, job, tmp_path)
    package = read_json(output)
    if field in ('seat', 'seed', 'result', 'rules', 'job'):
        if field == 'seat': report['agents'].reverse()
        if field == 'seed': report['seed_commitment'] = '0'*64
        if field == 'result': report['outcome']['result']['scores'][0] = 99
        if field == 'rules': report['ruleset'] = 'wrong'
        if field == 'job': report['game_id'] = 'other'
        write_json(package['files']['report']['path'], report)
        package['files']['report']['sha256'] = sha256_file(package['files']['report']['path'])
    if field == 'argv': package['arena_argv'][1] = 'run-match'
    if field == 'attempt': package['attempt'] = 2
    if field == 'behavior': package['behavior_id'] = 'c'*64
    if field == 'snapshot': package['contract']['run']['arena_contract_sha256'] = 'c'*64
    if field == 'config': package['arena_config']['agents'][1]['args'].append('bias')
    write_json(output, package)
    with pytest.raises(ValueError):
        verify_completion(spec['run'], job, 1, output, replay=replay, sidecar=sidecar, behavior_id='a'*64)


def test_v2_no_package_fails_before_auditor(spec, tmp_path, monkeypatch):
    run = Run.create(tmp_path / 'run', spec['run'], spec['parent_weights'])
    run.begin_cycle(spec['cycles'][0]); job = spec['cycles'][0][0]
    attempt = run.start_attempt(job['job_id'])
    def no_audit(*args, **kw): raise AssertionError('must fail before Rust')
    monkeypatch.setattr('training.prism.ppo.coordinator.audit_game', no_audit)
    with pytest.raises(ValueError, match='completion package'):
        run.submit(job['job_id'], attempt, executable='unused', replay='unused', sidecar='unused')
    assert run.status()['phase'] == 'FAILED'


def test_interrupted_attempt_costed_once_and_completed_job_skipped(spec, tmp_path):
    campaign = Campaign.create(tmp_path / 'campaign', spec)
    snapshot = campaign.run.begin_cycle(spec['cycles'][0])
    job = spec['cycles'][0][0]
    number = campaign.run.start_attempt(job['job_id'])
    campaign.recover_running(job, snapshot); campaign.recover_running(job, snapshot)
    state = campaign._load()[1]
    assert state['physical_decisions'] == 10 and state['retries'] == 1
    assert state['attempts'][str(number)]['status'] == 'INFRA_ABORT'


def test_v1_single_full_batch_step_and_restore(tmp_path, monkeypatch):
    weights = tmp_path / 'parent.json'; export_weights(PrismModel(), weights, CATALOG)
    spec = run_config(sha256_file(weights)); spec['ppo'].update(passes=1, minibatch_size=40)
    spec['budget'].update(max_optimizer_steps=2, max_update_attempts=2)
    run = Run.create(tmp_path / 'run', spec, weights)
    schedule = [{'job_id': 'synthetic', 'actor': 0, 'opponent_id': 'synthetic-opponent', 'environment_seed': 0}]
    run.begin_cycle(schedule)
    from training.prism.ppo.sampling import Behavior
    behavior = Behavior.from_payload(run.store.get_payload(run.state['snapshot']), runtime=run.runtime)
    shard = game(behavior, job='synthetic', count=10)
    monkeypatch.setattr('training.prism.ppo.coordinator.audit_game', lambda *args, **kw: shard)
    replay = tmp_path / 'meta.json'; write_json(replay, {'seed': 0, 'player_count': 2})
    attempt = run.start_attempt('synthetic'); run.submit('synthetic', attempt, executable='unused', replay=replay, sidecar='unused')
    run.seal(); run.step()
    restored = Run.open(run.root)
    assert restored.status()['phase'] == 'COMMITTED' and restored.status()['global_step'] == 1
    with pytest.raises(ValueError, match='no unconsumed'):
        restored.step()


@pytest.mark.skipif(os.name != 'nt', reason='Windows Job Object')
def test_owned_process_tree_wall_deadline_kills_descendant(tmp_path):
    pidfile = tmp_path / 'pid.txt'
    code = 'import subprocess,sys,time,pathlib; p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]);pathlib.Path(sys.argv[1]).write_text(str(p.pid));time.sleep(60)'
    with ProcessTree(cpu_seconds=10, memory_bytes=512*1024**2) as tree:
        tree.start([sys.executable, '-B', '-c', code, str(pidfile)], cwd='.', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        result = tree.wait(wall_seconds=1)
        assert result['stop_reason'] == 'wall_deadline' and result['total_processes'] == 2
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    handle = kernel.OpenProcess(0x1000, False, int(pidfile.read_text()))
    if handle:
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        exit_code = ctypes.c_ulong(); assert kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        assert exit_code.value != 259  # STILL_ACTIVE
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]; kernel.CloseHandle(handle)


@pytest.mark.skipif(os.name != 'nt', reason='Windows Job Object')
def test_storage_supervision_and_cpu_limit(tmp_path):
    with ProcessTree(cpu_seconds=10, memory_bytes=256*1024**2) as tree:
        tree.start([sys.executable, '-B', '-c', 'import time;time.sleep(30)'], cwd='.', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        (tmp_path / 'large').write_bytes(b'x'*100)
        result = tree.wait(wall_seconds=5, storage_root=tmp_path, max_storage_bytes=50)
        assert result['stop_reason'] == 'storage_deadline'
    with ProcessTree(cpu_seconds=1, memory_bytes=256*1024**2) as tree:
        tree.start([sys.executable, '-B', '-c', 'while True: pass'], cwd='.', stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        result = tree.wait(wall_seconds=8)
        assert result['returncode'] != 0 and result['stop_reason'] is None
        assert result['user_cpu_seconds'] >= 0.8

def test_physical_ledger_publication_recovery_idempotent(spec, tmp_path):
    campaign = Campaign.create(tmp_path / 'campaign', spec)
    job = spec['cycles'][0][0]
    campaign.record(1, {'job': job, 'status': 'PUBLISHED'}, decisions=7)
    campaign.record(1, {'job': job, 'status': 'PUBLISHED'}, decisions=7)
    campaign.record(1, {'job': job, 'status': 'COMPLETE'})
    assert campaign._load()[1]['physical_decisions'] == 7
    campaign.record(2, {'job': job, 'status': 'INFRA_ABORT'}, decisions=10, retry=True)
    campaign.record(2, {'job': job, 'status': 'INFRA_ABORT'}, decisions=10, retry=True)
    assert campaign._load()[1]['retries'] == 1


def test_published_terminal_without_package_never_replayed(spec, tmp_path):
    campaign = Campaign.create(tmp_path / 'campaign', spec)
    snapshot = campaign.run.begin_cycle(spec['cycles'][0])
    job = spec['cycles'][0][0]
    number = campaign.run.start_attempt(job['job_id'])
    directory = campaign._paths(number)[0]; directory.mkdir(parents=True)
    write_json(directory / 'report.json', {'outcome': {'status': 'completed'}})
    with pytest.raises(ValueError, match='never replay'):
        campaign.recover_running(job, snapshot)
    assert campaign.run.status()['attempts'] == 1


def test_existing_completion_recovery_no_spawn(spec, tmp_path, monkeypatch):
    campaign = Campaign.create(tmp_path / 'campaign', spec)
    snapshot = campaign.run.begin_cycle(spec['cycles'][0])
    job = spec['cycles'][0][0]
    number = campaign.run.start_attempt(job['job_id'])
    folder = tmp_path / 'package'; folder.mkdir()
    output, replay, sidecar, _, _ = fake_completion(spec, job, folder, snapshot['behavior_id'])
    package = read_json(output); package['snapshot_sha256'] = snapshot['snapshot_sha256']; write_json(output, package)
    monkeypatch.setattr(campaign, '_paths', lambda n: (output.parent, output, replay, sidecar))
    calls = []
    # Synthetic package has no real rules transcript; replace ingestion ONLY.
    monkeypatch.setattr(campaign.run, 'submit', lambda *args, **kw: calls.append((args, kw)))
    campaign.recover_running(job, snapshot)
    assert len(calls) == 1 and campaign.run.status()['attempts'] == 1
    assert campaign._load()[1]['physical_decisions'] == 1

def install_synthetic_shards(run, jobs):
    from training.prism.ppo.sampling import Behavior
    behavior = Behavior.from_payload(run.store.get_payload(run.state['snapshot']), runtime=run.runtime)
    shards = [game(behavior, job=j['job_id'], actor=j['actor'], count=3) for j in jobs]
    # Bypass only live Arena ingestion; no actual games are generated.
    with run.store.lock():
        for i, (job, shard) in enumerate(zip(jobs, shards)):
            run.state['jobs'][job['job_id']] = {'status': 'COMPLETE', 'attempt': i+1,
                                               'artifact': run.store.put_json(shard)}
        run.state['decisions'] = sum(len(shard['decisions']) for shard in shards)
        run._commit()


def test_v2_multi_step_pass_restore_and_resident_batch(spec, tmp_path, monkeypatch):
    spec['run']['ppo'].update(passes=2, minibatch_size=5, target_kl=1.0)
    spec['run']['budget'].update(max_optimizer_steps=30, max_update_attempts=40)
    run = Run.create(tmp_path / 'run', pin(spec)['run'], spec['parent_weights'])
    run.begin_cycle(spec['cycles'][0]); install_synthetic_shards(run, spec['cycles'][0])
    batch_id = run.seal()
    original_validate = __import__('training.prism.ppo.coordinator', fromlist=['validate_batch']).validate_batch
    calls = []
    def validate_once(*args):
        calls.append(True); return original_validate(*args)
    monkeypatch.setattr('training.prism.ppo.coordinator.validate_batch', validate_once)
    monkeypatch.setattr('training.prism.ppo.learner.validate_batch', lambda *args: pytest.fail('hot-path full validation'))
    monkeypatch.setattr(run.learner, 'diagnostics', lambda *args: pytest.fail('full-batch forward'))
    for _ in range(2): run.step()
    assert not calls
    run.pause(); recovered = Run.open(run.root); recovered.pause(False)
    assert len(calls) == 1
    monkeypatch.setattr(recovered.store, 'get_json', lambda *args: pytest.fail('hot-path batch reread'))
    while recovered.status()['phase'] == 'UPDATING': recovered.step()
    assert len(calls) == 1
    assert recovered.status()['global_step'] == 6
    assert recovered.status()['consumed'] == [batch_id]
    steps = [m for m in recovered.state['metrics'] if m['event'] == 'optimizer_step']
    assert [m['samples'] for m in steps] == [5, 5, 2, 5, 5, 2]
    assert [m['cursor'] for m in steps] == [5, 10, 12, 17, 22, 24]
    assert all('kl' in m and 'clip_fraction' in m for m in steps)


@pytest.mark.parametrize('event', ['backward_done', 'optimizer_done', 'payload_written', 'commit_written', 'head_published'])
def test_v2_interrupted_optimizer_can_resume_with_remaining_attempt_budget(spec, tmp_path, event):
    import shutil
    from training.prism.io import tensor_identity
    spec['run']['ppo'].update(passes=2, minibatch_size=5, target_kl=1.0)
    spec['run']['budget'].update(max_optimizer_steps=30, max_update_attempts=40)
    base = Run.create(tmp_path / 'base', pin(spec)['run'], spec['parent_weights'])
    base.begin_cycle(spec['cycles'][0]); install_synthetic_shards(base, spec['cycles'][0]); base.seal()
    clone = tmp_path / 'interrupted'; shutil.copytree(base.root, clone)
    while base.status()['phase'] == 'UPDATING': base.step()
    interrupted = Run.open(clone)
    def fault(point):
        if point == event: raise RuntimeError('synthetic optimizer interruption')
    with pytest.raises(RuntimeError, match='interruption'): interrupted.step(fault=fault)
    recovered = Run.open(clone)
    while recovered.status()['phase'] == 'UPDATING': recovered.step()
    assert recovered.status()['global_step'] == base.status()['global_step'] == 6
    assert recovered.status()['consumed'] == base.status()['consumed']
    assert tensor_identity(recovered.learner.model.state_dict()) == tensor_identity(base.learner.model.state_dict())
    assert recovered.status()['update_attempts'] == 6 + (event != 'head_published')


def test_campaign_loops_regular_passes_and_summarizes_rewards(spec, tmp_path):
    spec['run']['ppo'].update(passes=2, minibatch_size=5, target_kl=1.0)
    spec['run']['budget'].update(max_optimizer_steps=30, max_update_attempts=40)
    campaign = Campaign.create(tmp_path / 'campaign', pin(spec))
    campaign.run.begin_cycle(spec['cycles'][0]); install_synthetic_shards(campaign.run, spec['cycles'][0])
    campaign.run.seal(); campaign.work(stop_after_cycle=True)
    summary = read_json(campaign.root / 'cycle-1-summary.json')
    assert summary['optimizer_steps'] == summary['update_attempts'] == 6
    assert summary['groups']['all']['mean_reward'] == 0.5
    assert summary['groups']['all']['decisions'] == 12
    assert (campaign.root / 'cycle-1-export' / 'weights.json').is_file()
