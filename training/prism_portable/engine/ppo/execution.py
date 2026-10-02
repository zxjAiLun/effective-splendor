"""Pinned local Arena execution identity and completion-package verification.

A local launcher attestation is not cryptographic proof against a malicious user
who can rewrite files. It prevents accidental pool/argv/seat/seed/artifact drift.
Control metadata never becomes a network feature.
"""
import copy
import hashlib
from pathlib import Path
import struct

from ..io import canonical_hash, sha256_file
from .audit import bounded_json
from .contract import exact, integer, sha, text

SPEC_KEYS = {'format', 'run', 'parent_weights', 'arena', 'learner', 'opponents', 'cycles', 'limits'}
LIMIT_KEYS = {'max_plies', 'max_infra_retries', 'max_physical_decisions', 'game_wall_seconds',
              'game_cpu_seconds', 'campaign_cpu_seconds', 'memory_bytes', 'handshake_timeout_ms',
              'move_timeout_ms', 'shutdown_grace_ms'}


import os
def absolute(path):
    return os.path.abspath(str(path))


_FILE_HASH_CACHE = {}

def check_file(path, digest):
    sha(digest, 'file hash')
    p = Path(path)
    try:
        st = p.stat()
        key = (absolute(p), st.st_mtime_ns, st.st_size)
    except OSError:
        key = None
    if key is not None and key in _FILE_HASH_CACHE:
        actual = _FILE_HASH_CACHE[key]
    else:
        actual = sha256_file(path)
        if key is not None:
            _FILE_HASH_CACHE[key] = actual
    if actual != digest:
        raise ValueError('pinned executable/weight hash mismatch')


def identity(descriptor):
    return canonical_hash(descriptor)


def validate_spec(spec):
    exact(spec, SPEC_KEYS, 'Arena contract')
    if spec['format'] != 'prism-ppo-arena-v1':
        raise ValueError('Arena contract format')
    from .coordinator import validate_config
    validate_config(spec['run'])
    if spec['run']['format'] not in ('prism-ppo-run-v2', 'prism-ppo-run-v3') or spec['run']['device'] != 'cpu':
        raise ValueError('live Arena run requires v2 CPU identity')
    exact(spec['arena'], {'program', 'sha256', 'engine_version', 'protocol_version', 'ruleset'}, 'arena')
    exact(spec['learner'], {'program', 'sha256'}, 'learner')
    if spec['arena']['sha256'] != spec['run']['auditor_sha256']:
        raise ValueError('Arena/auditor binary identity mismatch')
    if spec['run']['format'] != 'prism-ppo-run-v3' and spec['run']['ppo']['style_beta'] != 0:
        raise ValueError('live style rewards are not authorized')
    exact(spec['limits'], LIMIT_KEYS, 'live limits')
    for key in LIMIT_KEYS:
        integer(spec['limits'][key], 1 if key != 'max_infra_retries' else 0, 2**63 - 1, key)
    integer(spec['limits']['max_plies'], 1, 10000, 'ply cap')
    if set(spec['opponents']) != set(spec['run']['opponents']):
        raise ValueError('opponent pool mismatch')
    for name, opponent in spec['opponents'].items():
        exact(opponent, {'program', 'sha256', 'args', 'files', 'hello', 'mode'}, 'opponent')
        exact(opponent['hello'], {'agent_name', 'agent_version'}, 'hello')
        if opponent['mode'] != 'greedy' or not isinstance(opponent['args'], list):
            raise ValueError('frozen greedy opponent required')
        for arg in opponent['args']:
            text(arg, 'argv')
        for path, digest in opponent['files'].items():
            text(path, 'weight path'); sha(digest, 'weight hash')
        if identity(opponent) != spec['run']['opponents'][name]:
            raise ValueError('opponent descriptor identity mismatch')
    jobs = [j for cycle in spec['cycles'] for j in cycle]
    budget = spec['run']['budget']
    if len(spec['cycles']) != budget['max_cycles'] or len(jobs) != budget['max_jobs']:
        raise ValueError('explicit campaign size/budget mismatch')
    if spec['limits']['max_plies'] > budget['max_job_decisions']:
        raise ValueError('decision reservation must cover every possible learner ply')
    if budget['max_attempts'] != len(jobs) + spec['limits']['max_infra_retries']:
        raise ValueError('retry/attempt budgets disagree')
    if spec['limits']['max_physical_decisions'] < budget['max_attempts'] * budget['max_job_decisions']:
        raise ValueError('insufficient physical attempt decision reservation')
    names = []
    seeds = []
    for cycle in spec['cycles']:
        if not isinstance(cycle, list) or not cycle:
            raise ValueError('nonempty cycle required')
        blocks = {}
        for job in cycle:
            exact(job, {'job_id', 'actor', 'opponent_id', 'environment_seed'}, 'scheduled job')
            text(job['job_id'], 'job_id')
            if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in job['job_id']):
                raise ValueError('job_id must be a safe path component')
            integer(job['actor'], 0, 1, 'actor'); integer(job['environment_seed'], 0, 2**64-1, 'seed')
            if job['opponent_id'] not in spec['opponents']:
                raise ValueError('opponent outside frozen pool')
            blocks.setdefault((job['opponent_id'], job['environment_seed']), []).append(job['actor'])
            names.append(job['job_id'])
        if {name for name, _ in blocks} != set(spec['opponents']):
            raise ValueError('each cycle must cover the frozen opponent pool')
        for (_, seed), actors in blocks.items():
            if sorted(actors) != [0, 1]:
                raise ValueError('double-seat block mismatch')
            seeds.append(seed)
    if len(set(names)) != len(names) or len(set(seeds)) != len(seeds):
        raise ValueError('reused job/seed block')
    content = copy.deepcopy(spec)
    content['run'].pop('arena_contract_sha256')
    if canonical_hash(content) != spec['run']['arena_contract_sha256']:
        raise ValueError('Arena contract content hash mismatch')
    return spec


def check_assets(spec):
    check_file(spec['parent_weights'], spec['run']['parent_sha256'])
    for descriptor in [spec['arena'], spec['learner'], *spec['opponents'].values()]:
        check_file(descriptor['program'], descriptor['sha256'])
        for path, digest in descriptor.get('files', {}).items():
            check_file(path, digest)


def seed_commitment(game_id, seed, catalog):
    game = game_id.encode('utf-8')
    return hashlib.sha256(b'effective-splendor-seed-v1\0' + struct.pack('<I', len(game)) + game +
                          bytes([2]) + struct.pack('<Q', seed) + catalog.encode('ascii')).hexdigest()


def arena_config(spec, job, behavior_id, endpoint, sidecar):
    # Token supplied at launch, and always removed from retained config/argv.
    learner = {'program': absolute(spec['learner']['program']),
               'args': ['agent-prism-ppo', '--endpoint', endpoint, '--token', '<redacted>',
                        '--behavior-id', behavior_id, '--job-id', job['job_id'],
                        '--decisions-out', absolute(sidecar)]}
    opponent = spec['opponents'][job['opponent_id']]
    agents = [{'program': absolute(opponent['program']), 'args': opponent['args'][:]} for _ in range(2)]
    agents[job['actor']] = learner
    return {'game_id': job['job_id'], 'seed': job['environment_seed'], 'agents': agents,
            **{k: spec['limits'][k] for k in ('handshake_timeout_ms', 'move_timeout_ms', 'shutdown_grace_ms')}}


def verify_report(spec, job, report, replay=None):
    exact(report, {'format', 'version', 'game_id', 'engine_version', 'protocol_version', 'ruleset',
                   'ruleset_fingerprint', 'player_count', 'seed_commitment', 'agents', 'outcome'}, 'report')
    expected = {'format': 'effective-splendor-arena-report', 'version': 1, 'game_id': job['job_id'],
                'player_count': 2, 'ruleset_fingerprint': spec['run']['catalog_fingerprint'],
                'seed_commitment': seed_commitment(job['job_id'], job['environment_seed'], spec['run']['catalog_fingerprint'])}
    expected.update({k: spec['arena'][k] for k in ('engine_version', 'protocol_version', 'ruleset')})
    if any(type(report[k]) is not type(v) or report[k] != v for k, v in expected.items()):
        raise ValueError('report execution/rules/seed identity mismatch')
    hello = spec['opponents'][job['opponent_id']]['hello']
    expected_agents = [dict(hello, seat=seat) if seat != job['actor'] else
                       {'seat': seat, 'agent_name': 'prism-ppo', 'agent_version': '0.1.0'} for seat in range(2)]
    if report['agents'] != expected_agents:
        raise ValueError('report hello/seat mismatch')
    outcome = report['outcome']
    if outcome['status'] == 'completed':
        exact(outcome, {'status', 'result', 'completed_plies', 'replay_final_hash'}, 'completed report')
        if replay is None or replay['seed'] != job['environment_seed'] or replay['player_count'] != 2:
            raise ValueError('replay schedule mismatch')
        if outcome['replay_final_hash'] != replay['final_state_hash'] or outcome['result'] != replay['result'] or outcome['completed_plies'] != len(replay['steps']):
            raise ValueError('report/replay result/hash mismatch')
        for key in ('engine_version', 'ruleset_fingerprint'):
            if replay[key] != report[key]:
                raise ValueError('replay/report compatibility mismatch')
        if replay['ruleset']['id'] != report['ruleset']:
            raise ValueError('replay ruleset mismatch')
        integer(outcome['completed_plies'], 1, spec['limits']['max_plies'], 'completed plies')
    elif outcome['status'] == 'truncated':
        exact(outcome, {'status', 'completed_plies', 'cap_state_hash', 'cap_scores'}, 'truncated report')
    elif outcome['status'] == 'aborted':
        exact(outcome, {'status', 'seat', 'phase', 'reason', 'request_id', 'completed_plies'}, 'aborted report')
    else:
        raise ValueError('unknown Arena outcome')
    return outcome


def verify_completion(config, job, attempt, completion, *, replay, sidecar, behavior_id):
    package = bounded_json(completion)
    exact(package, {'format', 'contract', 'job', 'attempt', 'behavior_id', 'snapshot_sha256',
                    'endpoint', 'cwd', 'arena_config', 'arena_argv', 'pid', 'resources', 'files'}, 'completion')
    if package['format'] != 'prism-ppo-arena-completion-v1' or package['job'] != job or package['attempt'] != attempt or package['behavior_id'] != behavior_id:
        raise ValueError('completion job/attempt/behavior mismatch')
    spec = validate_spec(package['contract'])
    if spec['run'] != config:
        raise ValueError('completion run contract mismatch')
    if job not in [j for cycle in spec['cycles'] for j in cycle]:
        raise ValueError('job outside frozen campaign')
    integer(package['attempt'], 1, config['budget']['max_attempts'], 'attempt')
    integer(package['pid'], 1, 2**32-1, 'owned process pid')
    sha(package['snapshot_sha256'], 'snapshot hash')
    if not isinstance(package['endpoint'], str) or not package['endpoint'].startswith('127.0.0.1:'):
        raise ValueError('nonloopback completion endpoint')
    check_assets(spec)
    expected_config = arena_config(spec, job, behavior_id, package['endpoint'], sidecar)
    if package['arena_config'] != expected_config or package['cwd'] != absolute('.'):
        raise ValueError('completion launch argv/cwd mismatch')
    files = package['files']
    if set(files) != {'report', 'replay', 'sidecar'}:
        raise ValueError('completion artifact set mismatch')
    for item in files.values():
        exact(item, {'path', 'sha256'}, 'completion file'); check_file(item['path'], item['sha256'])
    if files['replay']['path'] != absolute(replay) or files['sidecar']['path'] != absolute(sidecar):
        raise ValueError('completion artifact paths mismatch')
    expected_argv = [absolute(spec['arena']['program']), 'run-rollout', '--config', str(Path(completion).resolve().parent / 'arena-config.json'),
                     '--max-plies', str(spec['limits']['max_plies']), '--report-out', files['report']['path'],
                     '--replay-out', absolute(replay), '--prefix-out', str(Path(completion).resolve().parent / 'prefix.json')]
    if package['arena_argv'] != expected_argv or package['resources']['returncode'] != 0 or package['resources']['stop_reason'] is not None:
        raise ValueError('completion process outcome/argv mismatch')
    retained = bounded_json(Path(completion).parent / 'arena-config.json')
    if retained != expected_config:
        raise ValueError('retained Arena config mismatch')
    report = bounded_json(files['report']['path'])
    replay_dict = replay if isinstance(replay, dict) else (bounded_json(replay) if replay is not None else None)
    outcome = verify_report(spec, job, report, replay_dict)
    if outcome['status'] != 'completed':
        raise ValueError('completion requires true terminal')
    return outcome['result']
