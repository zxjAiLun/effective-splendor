"""Explicit M67 evaluation continuation, without changing rules or retrying games.

Original failed arena and physical attempts are immutable. Other arenas run once;
A common reuses verified completed games and executes only undispatched keys.
Known errors and orphan artifacts remain gaps, never draws. Diagnostic is separate.
"""
import argparse
import concurrent.futures
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from training.prism_portable.common import read, write, digest
from scripts import prism_m67_run as original
from scripts import prism_m67_resume_r2 as r2
from scripts import prism_notebook_arena as arena
from scripts import prism_ppo_fixed_eval as fixed
from scripts.prism_dsw_ppo_process import ProcessTree, same_process
R3 = ROOT / 'continuation-r3'
POLICY = R3 / 'policy.json'
FAILED_KEY = 'candidate-a/general/seed-9831381/seat-0'


def expected_keys(config):
    return {fixed._game_key(m, o, s, seat) for m in config['candidates']
            for o in config['opponents'] for s in config['seeds'] for seat in (0, 1)}


def missing_keys(config, games, orphan_keys=()):
    expected = expected_keys(config)
    if not set(games).issubset(expected) or not set(orphan_keys).issubset(expected):
        raise ValueError('unexpected saved game keys')
    if any(r.get('status') not in ('completed', 'error') for r in games.values()):
        raise ValueError('unrecognized saved status')
    return expected - set(games) - set(orphan_keys)


def verify():
    p = read(POLICY)
    if digest(__file__) != p['adapter_sha256']:
        raise ValueError('R3 adapter drift')
    if digest(ROOT / 'execution.json') != p['execution_sha256']:
        raise ValueError('original execution drift')
    if p['deadline'] != read(ROOT / 'continuation-r2/budget.json')['deadline']:
        raise ValueError('absolute deadline drift')
    original.verify(False)
    left = r2.remaining()
    original.bounds = r2.remaining
    for arm in ('a', 'b'):
        audit = read(ROOT / f'audits/{arm}/audit.json')
        weights = ROOT / f'campaigns/{arm}/cycle-20-export/weights.json'
        if audit['status'] != 'PASS_TRAINING_ARTIFACT_AUDIT' or digest(weights) != p['weights'][arm] or audit['weights_sha256'] != p['weights'][arm]:
            raise ValueError('final c20 identity drift')
    return left


def scan_saved(shard, validate_artifacts=True):
    out = Path(shard['output']); cp = Path(shard['config'])
    v = arena.validate_arena_config(read(cp), cp)
    v.update(saved_config=read(cp), config_sha256=fixed.canonical_hash(read(cp)))
    progress = read(out / 'progress.json') if (out / 'progress.json').exists() else {'games': {}, 'config_sha256': v['config_sha256']}
    if progress['config_sha256'] != v['config_sha256']:
        raise ValueError('partial shard config drift')
    missing_keys(v['config'], progress['games'])
    for key, record in progress['games'].items():
        if record['status'] != 'completed':
            continue
        row = record['row']; m, o, seed, seat = (row[k] for k in ('candidate', 'opponent', 'seed', 'candidate_seat'))
        if fixed._game_key(m, o, seed, seat) != key:
            raise ValueError('saved row key drift')
        if validate_artifacts:
            actual = fixed._evaluate_one(v, out, m, o, seed, seat, progress)
            if actual != row:
                raise ValueError('saved terminal row drift')
            game = out / 'games' / m / o / f'seed-{seed}-seat-{seat}'
            for name, sha in record.get('artifact_hashes', {}).items():
                if digest(game / name) != sha:
                    raise ValueError('saved provenance drift')
            if read(game / 'game.json')['row'] != row or read(game / 'process-result.json')['returncode'] != 0:
                raise ValueError('saved game provenance mismatch')
    orphans = []
    for m in v['candidates']:
        for o in v['opponents']:
            for seed in v['config']['seeds']:
                for seat in (0, 1):
                    key = fixed._game_key(m, o, seed, seat)
                    gp = out / 'games' / m / o / f'seed-{seed}-seat-{seat}'
                    if key not in progress['games'] and gp.exists() and any(gp.iterdir()):
                        orphans.append(key)
    return v, progress, orphans


def preflight():
    import psutil
    verify()
    for name in ('a-direct', 'b-common', 'b-direct'):
        if (ROOT / 'evaluation' / name).exists():
            raise ValueError('downstream arena already exists: ' + name)
    old = ROOT / 'evaluation/a-common'
    arena.verify(old)
    state, plan = read(old / 'status.json'), read(old / 'plan.json')
    if state['state'] != 'FAILED_PARTIAL_NO_RETRY':
        raise ValueError('unexpected original failure state')
    count = 0; errors = []; orphans = []; manifest = []
    for shard in plan['shards']:
        v, progress, orphan = scan_saved(shard)
        count += sum(g['status'] == 'completed' for g in progress['games'].values())
        errors.extend(k for k, g in progress['games'].items() if g['status'] == 'error')
        orphans.extend(orphan)
        manifest.append({'name': shard['name'], 'progress_sha256': digest(Path(shard['output']) / 'progress.json') if (Path(shard['output']) / 'progress.json').exists() else None,
                         'completed': sum(g['status'] == 'completed' for g in progress['games'].values()),
                         'missing': len(missing_keys(v['config'], progress['games'], orphan))})
    if count != 12762 or errors != [FAILED_KEY]:
        raise ValueError('saved completed/failure cohort differs from authorized recovery')
    policy = read(POLICY)
    if psutil.disk_usage(str(ROOT)).free < policy['minimum_free_bytes']:
        raise ValueError('insufficient free capacity')
    from training.prism_portable.processes import directory_bytes
    actual = directory_bytes(ROOT)
    if actual + policy['reserved_new_bytes'] > policy['storage_total_bytes']:
        raise ValueError('insufficient total storage reservation')
    receipt = dict(status='PASS_ZERO_NEW_GAMES', observed_at=time.time(), reused_games=count,
                   original_failure_keys=errors, orphan_keys=orphans, shards=manifest,
                   remaining_wall_seconds=verify(), actual_bytes=actual,
                   free_bytes=psutil.disk_usage(str(ROOT)).free, policy_sha256=digest(POLICY))
    write(R3 / 'preflight.json', receipt)
    return receipt


def prepare_a():
    verify()
    old = ROOT / 'evaluation/a-common'; work = ROOT / 'evaluation/a-common-recovery-r3'
    work.mkdir(exist_ok=False); (work / 'configs').mkdir(); (work / 'shards').mkdir()
    config, plan = read(old / 'config.json'), copy.deepcopy(read(old / 'plan.json'))
    proof = read(R3 / 'preflight.json'); bindings = {s['name']: s for s in proof['shards']}
    write(work / 'config.json', config)
    states = {}; deferred = []
    for shard in plan['shards']:
        source = Path(shard['output']); cp = Path(shard['config'])
        sha = digest(source / 'progress.json') if (source / 'progress.json').exists() else None
        if sha != bindings[shard['name']]['progress_sha256']:
            raise ValueError('original progress changed after preflight')
        v, progress, orphan = scan_saved(shard)
        new_cp = work / 'configs' / cp.name; fixed.atomic_json(new_cp, read(cp))
        if digest(new_cp) != digest(cp):
            raise ValueError('copied config bytes drift')
        if (source / 'completion.json').exists():
            states[shard['name']] = read(old / 'status.json')['shards'][shard['name']]
            continue
        output = work / 'shards' / shard['name']; output.mkdir()
        completed = {k: g for k, g in progress['games'].items() if g['status'] == 'completed'}
        for record in completed.values():
            row = record['row']; rel = Path('games') / row['candidate'] / row['opponent'] / f"seed-{row['seed']}-seat-{row['candidate_seat']}"
            dest = output / rel; dest.parent.mkdir(parents=True, exist_ok=True)
            dest.symlink_to(source / rel, target_is_directory=True)
        errors = {k: g for k, g in progress['games'].items() if g['status'] == 'error'}
        deferred.extend([*errors, *orphan])
        write(output / 'progress.json', dict(format='prism-ppo-fixed-eval-progress-v1', config_sha256=v['config_sha256'], games=completed))
        write(output / 'recovery.json', dict(original_output=str(source), original_progress_sha256=sha,
                    retained_errors=errors, orphan_keys=orphan, reused_games=len(completed), policy_sha256=digest(POLICY)))
        shard.update(config=str(new_cp), sha256=digest(new_cp), output=str(output))
        states[shard['name']] = {'state': 'PENDING', 'reused_games': len(completed)}
    plan['recovery'] = dict(original_work=str(old), original_plan_sha256=digest(old / 'plan.json'),
                            policy_sha256=digest(POLICY), original_completed_games=12762, deferred_keys=deferred)
    write(work / 'plan.json', plan)
    write(work / 'status.json', dict(state='PREPARED_EXPLICIT_RECOVERY', completed_games=12762,
          total_games=30000, plan_sha256=digest(work / 'plan.json'), shards=states, deferred_keys=deferred))
    return work


def a_worker(shard):
    verify()
    cp, out = Path(shard['config']), Path(shard['output'])
    v = arena.validate_arena_config(read(cp), cp); fixed.check_assets(v)
    v.update(saved_config=read(cp), config_sha256=fixed.canonical_hash(read(cp)))
    progress = read(out / 'progress.json'); recovery = read(out / 'recovery.json')
    excluded = set(recovery['retained_errors']) | set(recovery['orphan_keys'])
    errors = dict(recovery['retained_errors'])
    for m in v['candidates']:
        for o in v['opponents']:
            for seed in v['config']['seeds']:
                for seat in (0, 1):
                    key = fixed._game_key(m, o, seed, seat)
                    if key in excluded or key in progress['games']:
                        continue
                    if time.time() >= read(POLICY)['deadline']: raise ValueError('absolute deadline exhausted')
                    try:
                        fixed._evaluate_one(v, out, m, o, seed, seat, progress)
                        gp = out / 'games' / m / o / f'seed-{seed}-seat-{seat}'
                        progress['games'][key]['artifact_hashes'] = {n: digest(gp / n) for n in ('game.json', 'process-result.json', 'match-config.json')}
                        write(out / 'progress.json', progress)
                    except ValueError as error:
                        # Retain each failed physical attempt; continue independent keys once.
                        if progress['games'].get(key, {}).get('status') != 'error':
                            raise
                        errors[key] = progress['games'][key]
                        if len(errors) > 16:
                            raise ValueError('bounded failure budget exhausted') from error
    completed = sum(g['status'] == 'completed' for g in progress['games'].values())
    if completed == shard['games'] and not excluded:
        fixed._rows_from_progress(progress, v)
        write(out / 'completion.json', dict(status='COMPLETED_NO_RETRY', config_sha256=v['config_sha256'],
                games=completed, progress_sha256=digest(out / 'progress.json')))
        return dict(state='COMPLETE', games=completed, completion_sha256=digest(out / 'completion.json'))
    write(out / 'incomplete.json', dict(status='INCOMPLETE_RETAINED_FAILURES', completed_games=completed,
          errors=errors, excluded_keys=sorted(excluded), progress_sha256=digest(out / 'progress.json')))
    return dict(state='INCOMPLETE_RETAINED_FAILURES', games=completed, errors=sorted(errors), excluded_keys=sorted(excluded))


def run_a():
    work = prepare_a(); plan = read(work / 'plan.json'); state = read(work / 'status.json')
    state.update(state='RUNNING_EXPLICIT_RECOVERY', started_at=time.time())
    write(work / 'status.json', state)
    pending = [s for s in plan['shards'] if state['shards'][s['name']]['state'] == 'PENDING']
    # Each worker subprocess owns one shard and all of its agent children.
    def run_shard(shard):
        log = R3 / 'a-shards' / shard['name']; log.mkdir(parents=True, exist_ok=False)
        os.environ['PRISM_PPO_CONTROL_DIR'] = str(R3 / 'a-shards')
        wall = min(1800, verify())
        with (log / 'stdout.log').open('xb') as out, (log / 'stderr.log').open('xb') as err:
            with ProcessTree(cpu_seconds=7200, memory_bytes=2*1024**3, max_processes=10) as tree:
                tree.start([sys.executable, '-B', __file__, 'a-worker', '--shard', shard['name']], cwd=ROOT, stdout=out, stderr=err)
                resources = tree.wait(wall_seconds=wall)
        write(log / 'process-receipt.json', resources)
        if resources['returncode'] or resources['stop_reason']:
            raise ValueError('recovery shard failed: ' + shard['name'])
        return read(Path(shard['output']) / 'worker-receipt.json')
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        jobs = {pool.submit(run_shard, s): s for s in pending}
        for future in concurrent.futures.as_completed(jobs):
            shard = jobs[future]; state['shards'][shard['name']] = future.result()
            state['completed_games'] = sum(s.get('games', s.get('reused_games', 0)) for s in state['shards'].values())
            state['observed_at'] = time.time(); write(work / 'status.json', state)
    state.update(state='COMPLETED_GRID_WITH_RETAINED_GAPS' if any(s['state'] != 'COMPLETE' for s in state['shards'].values()) else 'COMPLETED_DEVELOPMENT_ONLY', finished_at=time.time())
    write(work / 'status.json', state); write(R3 / 'a-recovery-receipt.json', state)
    return state


def downstream(name):
    verify()
    return original.arena_stage(name)


def bounded_stage(mode, name=None):
    p = read(POLICY); label = name or mode; folder = R3 / label; folder.mkdir(exist_ok=False)
    wall = min(18000, verify()); os.environ.update(PRISM_PPO_CONTROL_DIR=str(folder), PRISM_DSW_REMAINING_WALL=str(wall), OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
    with (folder / 'stdout.log').open('xb') as out, (folder / 'stderr.log').open('xb') as err:
        with ProcessTree(cpu_seconds=72000, memory_bytes=8*1024**3, max_processes=64) as tree:
            tree.start([sys.executable, '-B', __file__, mode] + (['--arm', name] if name else []), cwd=ROOT, stdout=out, stderr=err)
            resources = tree.wait(wall_seconds=wall, storage_root=ROOT, max_storage_bytes=p['storage_total_bytes'], storage_interval=60,
                   snapshot=lambda counters: write(folder / 'status.json', dict(observed_at=time.time(), resources=counters)))
    write(folder / 'completion.json', resources)
    if resources['returncode'] or resources['stop_reason']:
        raise ValueError('bounded recovery stage failed: ' + label)


def pipeline():
    import psutil
    verify(); me = psutil.Process()
    with (R3 / 'pipeline-once.lock').open('x'): pass
    state = dict(state='RUNNING', pid=me.pid, create_time=me.create_time(), started_at=time.time(), policy_sha256=digest(POLICY))
    try:
        for mode, arm in [('downstream', 'a-direct'), ('downstream', 'b-common'), ('downstream', 'b-direct'), ('run-a', None)]:
            state.update(phase=arm or mode, observed_at=time.time()); write(R3 / 'status.json', state)
            bounded_stage(mode, arm)
        state.update(state='EVALUATIONS_FINISHED_WITH_RETAINED_A_GAPS', phase='AWAITING_LONG_GAME_RESOLUTION', finished_at=time.time())
        write(R3 / 'status.json', state)
    except BaseException as error:
        state.update(state='FAILED_STOPPED_NO_RETRY', error=repr(error), finished_at=time.time()); write(R3 / 'status.json', state); raise


def start():
    import psutil
    verify()
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            if proc.pid != os.getpid() and str(ROOT) in ' '.join(proc.info['cmdline'] or []):
                raise ValueError('project process still active')
        except (psutil.NoSuchProcess, psutil.AccessDenied): pass
    preflight()
    with (R3 / 'launch-once.lock').open('x'): pass
    with (R3 / 'supervisor.log').open('xb') as log:
        proc = subprocess.Popen([sys.executable, '-B', __file__, 'pipeline'], cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    receipt = dict(status='STARTED_BOUNDED_EVALUATION_CONTINUATION_R3', pid=proc.pid, create_time=psutil.Process(proc.pid).create_time(),
                   deadline=read(POLICY)['deadline'], policy_sha256=digest(POLICY), observed_at=time.time())
    write(R3 / 'launch.json', receipt); return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['preflight', 'start', 'pipeline', 'downstream', 'run-a', 'a-worker'])
    parser.add_argument('--arm'); parser.add_argument('--shard'); args = parser.parse_args()
    if args.mode == 'a-worker':
        plan = read(ROOT / 'evaluation/a-common-recovery-r3/plan.json')
        shard = next(s for s in plan['shards'] if s['name'] == args.shard)
        result = a_worker(shard); write(Path(shard['output']) / 'worker-receipt.json', result)
    else:
        result = downstream(args.arm) if args.mode == 'downstream' else globals()[args.mode.replace('-', '_')]()
    if result is not None: print(json.dumps(result, ensure_ascii=False))
