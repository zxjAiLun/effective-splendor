"""Owner-authorized M67 R4 final evaluation tail continuation (remaining 61 shards / 3842 games).

Preserves all R1/R2/R3/R3B files, weights, engine, seeds, and completed games.
Reconciles shards 00410..00412 (already 64/64 completed before wall_deadline) and
completes shard 00413 (6/64 completed, 0 orphans/errors) through shard 00473.
"""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from training.prism_portable.common import read, write, digest
from scripts import prism_m67_run as original
from scripts import prism_m67_eval_recovery_r3 as r3
from scripts import prism_m67_eval_recovery_r3b as r3b
from scripts.prism_dsw_ppo_process import ProcessTree

BASE = ROOT / 'continuation-r4'
POLICY = BASE / 'policy.json'
WORK = ROOT / 'evaluation/a-common-recovery-r3'


def remaining():
    p = read(POLICY)
    if digest(__file__) != p['adapter_sha256']:
        raise ValueError('R4 adapter drift')
    if digest(r3.__file__) != p['r3_adapter_sha256'] or digest(r3b.__file__) != p['r3b_adapter_sha256']:
        raise ValueError('prior recovery adapter drift')
    if digest(ROOT / 'execution.json') != p['execution_sha256']:
        raise ValueError('original execution drift')
    original.verify(False)
    for arm in ('a', 'b'):
        audit = read(ROOT / f'audits/{arm}/audit.json')
        weights = ROOT / f'campaigns/{arm}/cycle-20-export/weights.json'
        if audit['status'] != 'PASS_TRAINING_ARTIFACT_AUDIT' or digest(weights) != p['weights'][arm] or audit['weights_sha256'] != p['weights'][arm]:
            raise ValueError('final c20 identity drift')
    left = p['deadline'] - time.time()
    if left <= 0:
        raise ValueError('R4 continuation deadline exhausted')
    return left


def configure_bounds():
    left = remaining()
    r3.r2.remaining = remaining
    original.bounds = remaining
    return left


def reconcile_and_preflight():
    import psutil
    left = configure_bounds()
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            if proc.pid != os.getpid() and str(ROOT) in ' '.join(proc.info['cmdline'] or []):
                raise ValueError('project process still active')
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    sup = read(ROOT / 'continuation-r3b/supervisor-completion.json')
    if sup.get('stop_reason') != 'wall_deadline':
        raise ValueError('unexpected R3B stop reason')

    plan = read(WORK / 'plan.json')
    state = read(WORK / 'status.json')
    if digest(WORK / 'plan.json') != read(ROOT / 'continuation-r3b/prepared.json')['plan_sha256']:
        raise ValueError('prepared plan drift')

    reconciled_complete = []
    pending_to_run = []
    total_missing = 0

    for shard in plan['shards']:
        name = shard['name']
        s_state = state['shards'][name]
        if s_state['state'] != 'PENDING':
            continue
        r3b.guard(shard)
        out = Path(shard['output'])
        v, prog, orphans = r3.scan_saved(shard, validate_artifacts=True)
        if orphans:
            raise ValueError(f'unexpected orphan in pending shard {name}: {orphans}')
        comp_count = sum(g['status'] == 'completed' for g in prog['games'].values())
        err_keys = [k for k, g in prog['games'].items() if g['status'] == 'error']
        if err_keys:
            raise ValueError(f'unexpected error in pending shard {name}: {err_keys}')
        miss_count = len(r3.missing_keys(v['config'], prog['games'], orphans))

        if (out / 'completion.json').exists() and (out / 'worker-receipt.json').exists():
            receipt = read(out / 'worker-receipt.json')
            comp = read(out / 'completion.json')
            if receipt.get('state') != 'COMPLETE' or receipt.get('games') != shard['games'] or comp_count != shard['games'] or miss_count != 0:
                raise ValueError(f'completed shard receipt mismatch: {name}')
            if digest(out / 'completion.json') != receipt['completion_sha256'] or comp['progress_sha256'] != digest(out / 'progress.json'):
                raise ValueError(f'completed shard hash drift: {name}')
            state['shards'][name] = receipt
            reconciled_complete.append(name)
        else:
            pending_to_run.append({'name': name, 'completed': comp_count, 'missing': miss_count})
            total_missing += miss_count

    state['completed_games'] = sum(
        s.get('games', s.get('reused_games', 0)) for s in state['shards'].values()
    )
    state['observed_at'] = time.time()
    write(WORK / 'status.json', state)

    proof = dict(
        status='PASS_ZERO_NEW_GAMES_R4_PREFLIGHT',
        observed_at=time.time(),
        reconciled_complete_shards=reconciled_complete,
        pending_shards_count=len(pending_to_run),
        total_missing_games=total_missing,
        committed_games_in_status=state['completed_games'],
        remaining_wall_seconds=left,
        free_bytes=psutil.disk_usage(str(ROOT)).free,
        policy_sha256=digest(POLICY)
    )
    write(BASE / 'preflight.json', proof)
    return proof


def worker(name):
    configure_bounds()
    plan = read(WORK / 'plan.json')
    if digest(WORK / 'plan.json') != read(ROOT / 'continuation-r3b/prepared.json')['plan_sha256']:
        raise ValueError('prepared plan drift')
    shard = next(s for s in plan['shards'] if s['name'] == name)
    r3b.guard(shard)
    cp, out = Path(shard['config']), Path(shard['output'])
    v = r3.arena.validate_arena_config(read(cp), cp)
    r3.fixed.check_assets(v)
    v.update(saved_config=read(cp), config_sha256=r3.fixed.canonical_hash(read(cp)))
    progress = read(out / 'progress.json')
    recovery = read(out / 'recovery.json')
    excluded = set(recovery['retained_errors']) | set(recovery['orphan_keys'])
    errors = dict(recovery['retained_errors'])

    for m in v['candidates']:
        for o in v['opponents']:
            for seed in v['config']['seeds']:
                for seat in (0, 1):
                    key = r3.fixed._game_key(m, o, seed, seat)
                    if key in excluded or key in progress['games']:
                        continue
                    remaining()
                    try:
                        r3.fixed._evaluate_one(v, out, m, o, seed, seat, progress)
                        gp = out / 'games' / m / o / f'seed-{seed}-seat-{seat}'
                        progress['games'][key]['artifact_hashes'] = {
                            n: digest(gp / n) for n in ('game.json', 'process-result.json', 'match-config.json')
                        }
                        write(out / 'progress.json', progress)
                    except ValueError as error:
                        if progress['games'].get(key, {}).get('status') != 'error':
                            raise
                        errors[key] = progress['games'][key]
                        if len(errors) > 16:
                            raise ValueError('bounded failure budget exhausted') from error

    completed = sum(g['status'] == 'completed' for g in progress['games'].values())
    if completed == shard['games'] and not excluded and not errors:
        r3.fixed._rows_from_progress(progress, v)
        write(out / 'completion.json', dict(
            status='COMPLETED_NO_RETRY', config_sha256=v['config_sha256'],
            games=completed, progress_sha256=digest(out / 'progress.json')
        ))
        res = dict(state='COMPLETE', games=completed, completion_sha256=digest(out / 'completion.json'))
    else:
        write(out / 'incomplete.json', dict(
            status='INCOMPLETE_RETAINED_FAILURES', completed_games=completed,
            errors=errors, excluded_keys=sorted(excluded), progress_sha256=digest(out / 'progress.json')
        ))
        res = dict(state='INCOMPLETE_RETAINED_FAILURES', games=completed, errors=sorted(errors), excluded_keys=sorted(excluded))
    write(out / 'worker-receipt.json', res)
    return res


def run():
    import psutil
    configure_bounds()
    me = psutil.Process()
    plan = read(WORK / 'plan.json')
    state = read(WORK / 'status.json')
    state.update(state='RUNNING_EXPLICIT_RECOVERY_R4', pid=me.pid, create_time=me.create_time(), observed_at=time.time())
    write(WORK / 'status.json', state)
    write(BASE / 'status.json', state)

    os.environ['PRISM_PPO_CONTROL_DIR'] = str(BASE)
    os.environ['PRISM_DSW_REMAINING_WALL'] = str(min(18000, remaining()))

    def shard_run(shard):
        folder = BASE / shard['name']
        folder.mkdir(exist_ok=False)
        with (folder / 'stdout.log').open('xb') as out, (folder / 'stderr.log').open('xb') as err:
            with ProcessTree(cpu_seconds=7200, memory_bytes=2*1024**3, max_processes=10) as tree:
                tree.start([sys.executable, '-B', __file__, 'worker', '--shard', shard['name']], cwd=ROOT, stdout=out, stderr=err)
                resources = tree.wait(wall_seconds=min(1800, remaining()), storage_root=ROOT, max_storage_bytes=64*1024**3, storage_interval=60)
        write(folder / 'process-receipt.json', resources)
        if resources['returncode'] or resources['stop_reason']:
            raise ValueError('R4 shard failure: ' + shard['name'])
        return read(Path(shard['output']) / 'worker-receipt.json')

    pending = [s for s in plan['shards'] if state['shards'][s['name']]['state'] == 'PENDING']
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(shard_run, s): s for s in pending}
        for future in concurrent.futures.as_completed(futures):
            shard = futures[future]
            state['shards'][shard['name']] = future.result()
            state.update(
                completed_games=sum(s.get('games', s.get('reused_games', 0)) for s in state['shards'].values()),
                observed_at=time.time()
            )
            write(WORK / 'status.json', state)
            write(BASE / 'status.json', state)

    state.update(state='EVALUATIONS_FINISHED_WITH_RETAINED_GAPS', finished_at=time.time())
    write(WORK / 'status.json', state)
    write(BASE / 'status.json', state)
    write(BASE / 'completion.json', state)
    return state


def supervisor():
    import psutil
    reconcile_and_preflight()
    with (BASE / 'supervisor-once.lock').open('x'):
        pass
    me = psutil.Process()
    write(BASE / 'supervisor-launch.json', dict(pid=me.pid, create_time=me.create_time(), at=time.time(), policy_sha256=digest(POLICY)))
    wall = remaining()
    os.environ.update(
        PRISM_PPO_CONTROL_DIR=str(BASE / 'total'),
        PRISM_DSW_REMAINING_WALL=str(wall),
        OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1'
    )
    with (BASE / 'stdout.log').open('xb') as out, (BASE / 'stderr.log').open('xb') as err:
        with ProcessTree(cpu_seconds=72000, memory_bytes=8*1024**3, max_processes=64) as tree:
            tree.start([sys.executable, '-B', __file__, 'run'], cwd=ROOT, stdout=out, stderr=err)
            resources = tree.wait(
                wall_seconds=wall, storage_root=ROOT, max_storage_bytes=64*1024**3,
                storage_interval=60, snapshot=lambda v: write(BASE / 'supervisor-status.json', dict(at=time.time(), resources=v))
            )
    write(BASE / 'supervisor-completion.json', resources)
    if resources['returncode'] or resources['stop_reason']:
        raise ValueError('R4 supervisor stopped: ' + str(resources))
    return resources


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['preflight', 'worker', 'run', 'supervisor'])
    parser.add_argument('--shard')
    args = parser.parse_args()
    if args.mode == 'preflight':
        res = reconcile_and_preflight()
    elif args.mode == 'worker':
        res = worker(args.shard)
    else:
        res = globals()[args.mode]()
    if res is not None:
        print(json.dumps(res, ensure_ascii=False))
