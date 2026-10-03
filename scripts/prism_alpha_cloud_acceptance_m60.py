"""M60 once-only cloud evaluation of the already committed final c4.

New execution binding only. Frozen M60 training and M56 statistical helpers are
never edited. All matches stay inside the invoking systemd control group.
"""
import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import prism_ppo_fixed_eval as fixed
from scripts import prism_alpha_round as alpha

read, write, sha, require = fixed.read_json, fixed.atomic_json, fixed.sha256_file, fixed._require
CONFIG_SHA = 'afa21fc1e588ecc80e8bab64ca08392448758d68d47544900f48b8eaa9f89c4b'
TRAIN_SHA = 'a5e45455332a4514baac3cf3c77f5bc6a589ebe701e405b5fef7e17130d5c50d'
CANDIDATE_SHA = '7f6cdbc2acdff129b0ef6a3417e79d4b8f27bf59f40be53ae2892bf00b5e1544'
HELPERS = ('prism_alpha_cloud_acceptance_m60.py', 'prism_alpha_round.py',
           'prism_ppo_fixed_eval.py', 'prism_match_details.py', 'prism_rush_round.py',
           'prism_rush_report.py', 'prism_alpha_report.py')
DISPLAY = {'base': '父模型 Prism Alpha v0.1.2',
           'candidate': 'M60 未发布最终 c4 候选',
           'base-t1': '父模型 Prism Alpha v0.1.2（T=1）',
           'heuristic-portable-v029': '便携 Heuristic v0.2.9（greedy）',
           'prism-v01': '初代 Prism v0.1.0（greedy）',
           'prism-general-v011': '通用 Prism v0.1.1（T=1）'}
ACTION_SEED = 59032001


def now():
    return datetime.now(timezone.utc).isoformat()


def bindings(project):
    config = project / 'benchmarks/m60-prism-alpha-cloud-ppo.config.json'
    blueprint = project / 'benchmarks/m60-prism-alpha-cloud-ppo.train.json'
    require(sha(config) == CONFIG_SHA and sha(blueprint) == TRAIN_SHA, 'frozen M60 input drift')
    pilot, train = read(config), read(blueprint)['template']
    candidate = project / 'campaigns/m60-alpha-bigcard-g0/cycle-4-export/weights.json'
    require(sha(candidate) == CANDIDATE_SHA, 'fixed final-c4 drift')
    return pilot, train, candidate


def descriptors(project, pilot, candidate):
    engine = Path(pilot['evaluation']['native_path_and_sha256']['path'])
    require(sha(engine) == pilot['evaluation']['native_path_and_sha256']['sha256'], 'engine drift')
    runtime_root = engine.parents[2]
    # M60 parent/initial weights: parent lives in this round's own inputs; initial
    # stays on the frozen M57 runtime snapshot. General is this round's copy.
    paths = {'base': project / 'inputs/parent.json',
             'prism-v01': runtime_root / 'inputs/initial.json',
             'prism-general-v011': project / 'inputs/general.json', 'candidate': candidate}
    for name, asset in (('base', 'parent'), ('prism-v01', 'initial'), ('prism-general-v011', 'general')):
        require(sha(paths[name]) == pilot['assets'][asset]['sha256'], 'weight identity drift: ' + name)
    def desc(name, sampled=True):
        p = paths[name]
        return {'program': str(engine), 'sha256': sha(engine),
                'args': ['agent-prism-sample' if sampled else 'agent-prism', '--weights', str(p),
                         '--seed', str(ACTION_SEED) if sampled else '51000001'],
                'files': [{'path': str(p), 'sha256': sha(p)}]}
    candidates = {m: desc(m) for m in ('base', 'candidate')}
    opponents = {'heuristic-portable-v029': {'program': str(engine), 'sha256': sha(engine),
                 'args': ['agent-heuristic-v02', '--seed', '20260926'], 'files': []},
                 'prism-v01': desc('prism-v01', False), 'prism-general-v011': desc('prism-general-v011')}
    return engine, candidates, opponents


def make_plan(project, work, stage, pilot, train, candidate):
    engine, candidates, opponents = descriptors(project, pilot, candidate)
    contract = pilot['evaluation'][stage]
    require(contract['action_seed'] == ACTION_SEED, 'action RNG drift')
    cfg = {'format': fixed.FORMAT, 'engine': {'program': str(engine), 'sha256': sha(engine)},
           'catalog_fingerprint': train['run']['catalog_fingerprint'], 'action_seed': contract['action_seed'],
           'candidates': candidates, 'opponents': opponents,
           'timeouts': {'game_wall_seconds': 60, 'handshake_timeout_ms': 10000,
                        'move_timeout_ms': 10000, 'shutdown_grace_ms': 1000}}
    stage_root = work / stage
    (stage_root / 'configs').mkdir(parents=True)
    shards, keys = [], set()
    for mode in (('anchors', 'direct') if stage == 'acceptance' else ('anchors',)):
        end = contract['direct_seed_end'] if mode == 'direct' else contract['seed_end']
        width = 16 if stage == 'development' else 32
        for i, first in enumerate(range(contract['seed_start'], end + 1, width)):
            sub = copy.deepcopy(cfg)
            sub['seeds'] = list(range(first, min(first + width, end + 1)))
            if mode == 'direct':
                sub['candidates'] = {'candidate': candidates['candidate']}
                sub['opponents'] = {'base-t1': candidates['base']}
            path = stage_root / 'configs' / f'{mode}-{i}.json'
            write(path, sub)
            fixed.check_assets(fixed.validate_config(sub, path))
            grid = {(m, op, s, seat) for m in sub['candidates'] for op in sub['opponents']
                    for s in sub['seeds'] for seat in (0, 1)}
            require(not keys.intersection(grid), 'overlapping seed shard')
            keys.update(grid)
            shards.append({'mode': mode, 'config': str(path), 'config_sha256': sha(path),
                           'output': str(stage_root / 'runs' / f'{mode}-{i}'), 'games': len(grid)})
    expected = {(m, op, s, seat) for m in ('base', 'candidate') for op in contract['anchors']
                for s in range(contract['seed_start'], contract['seed_end'] + 1) for seat in (0, 1)}
    if stage == 'acceptance':
        expected |= {('candidate', 'base-t1', s, seat)
                     for s in range(contract['seed_start'], contract['direct_seed_end'] + 1) for seat in (0, 1)}
    require(keys == expected and len(keys) == contract['total_games'], 'frozen evaluation grid mismatch')
    plan = {'format': 'm60-cloud-evaluation-plan-v1', 'stage': stage, 'created_at': now(),
            'started_after_final_c4': True, 'candidate_weights_sha256': CANDIDATE_SHA,
            'base_weights_sha256': pilot['base_model']['sha256'], 'shards': shards}
    write(stage_root / 'plan.json', plan)
    return plan


def prepare(project):
    pilot, train, candidate = bindings(project)
    work = project / 'evaluation'
    require(not work.exists(), 'evaluation already prepared; refuse overwrite')
    work.mkdir()
    files = {str(project / 'scripts' / name): sha(project / 'scripts' / name) for name in HELPERS}
    for name in ('config', 'train'):
        path = project / f'benchmarks/m60-prism-alpha-cloud-ppo.{name}.json'
        files[str(path)] = sha(path)
    style = work / 'style.json'
    write(style, train['run']['style'])
    files[str(style)] = sha(style)
    binaries = {'style': {'path': '/home/ubuntu/splendor-ppo-m57/build/release/examples/prism_bigcard_metrics',
                         'sha256': '5510f847e31981bb223147639ef1e20c1b7317b5fe2a24d12668f4293919ad5a'},
                'economy': pilot['runtime']['metrics'], 'engine': pilot['runtime']['engine']}
    for descriptor in binaries.values():
        require(sha(descriptor['path']) == descriptor['sha256'], 'native metrics drift')
        files[descriptor['path']] = descriptor['sha256']
    # Frozen M56 offline collector uses historical .exe suffixes. These are
    # private symlinks to pinned ARM Linux binaries, never Windows executables.
    for link, target in ((work / 'build/release/examples/prism_bigcard_metrics.exe', binaries['style']['path']),
                         (work / 'collector-root/local-artifacts/prism/v01/bin/s4_batch_metrics.exe', binaries['economy']['path'])):
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target)
        files[str(link)] = sha(link)
    plans = {stage: make_plan(project, work, stage, pilot, train, candidate)
             for stage in ('development', 'acceptance')}
    for stage, plan in plans.items():
        path = work / stage / 'plan.json'
        files[str(path)] = sha(path)
        for shard in plan['shards']:
            files[shard['config']] = shard['config_sha256']
    receipt = {'format': 'm60-cloud-evaluation-execution-v1', 'created_at': now(), 'host': 'cloud1',
               'owner_authorization': '继续迭代？（M60 finite continuation; evaluation per frozen contract）',
               'training_original_memory_bytes': 8589934592, 'training_original_status': 'recorded_in_training_audit',
               'memory_bytes': 8589934592, 'cpu_quota_percent': 200, 'workers': 2,
               'wall_seconds': 28800, 'cpu_seconds': 40000, 'storage_bytes': 34359738368,
               'infrastructure_retries': 0, 'physical_games': 4480, 'candidate_sha256': CANDIDATE_SHA,
               'config_sha256': CONFIG_SHA, 'blueprint_sha256': TRAIN_SHA, 'files': files,
               'binaries': binaries, 'acceptance': pilot['evaluation']['acceptance'],
               'development': pilot['evaluation']['development'],
               'semantics': 'new finite-round evaluation only; no PPO, seed, gate or action-mode change'}
    write(work / 'execution.json', receipt)
    print(json.dumps({'status': 'PREPARED_ZERO_GAMES', 'execution_sha256': sha(work / 'execution.json'),
                      'games': 4480, 'shards': {k: len(v['shards']) for k, v in plans.items()}}))


def verify(work, execution):
    require(execution['workers'] == 2 and execution['physical_games'] == 4480
            and execution['infrastructure_retries'] == 0 and execution['memory_bytes'] == 8589934592,
            'execution scope drift')
    for path, digest in execution['files'].items():
        require(sha(path) == digest, 'execution source/asset drift: ' + path)
    for stage in ('development', 'acceptance'):
        for shard in read(work / stage / 'plan.json')['shards']:
            fixed.check_assets(fixed.validate_config(read(shard['config']), shard['config']))


def resources(work):
    import psutil
    cg = Path('/sys/fs/cgroup') / Path(next(line.split(':', 2)[2].strip().lstrip('/')
                                         for line in Path('/proc/self/cgroup').read_text().splitlines()
                                         if line.startswith('0:')))
    require('prism-m60-evaluation' in str(cg), 'not inside owned evaluation service')
    require(int((cg / 'memory.max').read_text()) == 8589934592, 'systemd memory ceiling not applied')
    quota, period = map(int, (cg / 'cpu.max').read_text().split())
    require(quota / period == 2, 'systemd CPU quota not applied')
    cpu = dict(line.split() for line in (cg / 'cpu.stat').read_text().splitlines())
    size = sum(p.stat().st_size for p in work.rglob('*') if p.is_file() and not p.is_symlink())
    return {'cpu_seconds': int(cpu['usage_usec']) / 1e6, 'storage_bytes': size,
            'memory_current_bytes': int((cg / 'memory.current').read_text()),
            'memory_peak_bytes': int((cg / 'memory.peak').read_text()),
            'host_available_memory_bytes': psutil.virtual_memory().available,
            'memory_events': dict((k, int(v)) for k, v in
                                  (line.split() for line in (cg / 'memory.events').read_text().splitlines())),
            'cgroup': str(cg)}


def stage_run(project, work, stage, execution, started):
    plan = read(work / stage / 'plan.json')
    queue, active, finished = list(plan['shards']), [], 0
    while queue or active:
        while queue and len(active) < execution['workers']:
            shard = queue.pop(0)
            require(not Path(shard['output']).exists(), 'refuse repeat/partial shard')
            log = open(Path(shard['config']).with_suffix('.log'), 'xb')
            p = subprocess.Popen([sys.executable, '-B', str(project / 'scripts/prism_ppo_fixed_eval.py'),
                                  '--config', shard['config'], '--output', shard['output']],
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
            active.append((p, log, shard))
        completed = finished
        running = []
        for p, log, shard in active:
            code = p.poll()
            if code is not None:
                log.close()
                require(code == 0, f"shard failed without retry: {shard['config']} exit={code}")
                require(Path(shard['output'], 'completion.json').exists(), 'missing completed shard')
                finished += shard['games']
                completed += shard['games']
            else:
                progress = Path(shard['output']) / 'progress.json'
                if progress.exists():
                    completed += sum(r['status'] == 'completed' for r in read(progress)['games'].values())
                running.append((p, log, shard))
        active = running
        usage = resources(work)
        require(time.monotonic() - started < execution['wall_seconds'], 'evaluation wall budget')
        require(usage['cpu_seconds'] < execution['cpu_seconds'], 'evaluation CPU budget')
        require(usage['storage_bytes'] < execution['storage_bytes'], 'evaluation storage budget')
        write(work / 'status.json', {'state': stage.upper() + '_RUNNING', 'timestamp': now(),
                                    'stage_completed': completed, 'stage_total': sum(s['games'] for s in plan['shards']),
                                    'elapsed_wall_seconds': time.monotonic() - started, 'resources': usage,
                                    'active_worker_pids': [p.pid for p, _, _ in active], 'retry': 0})
        if queue or active:
            time.sleep(5)
    return plan


def run(project, expected_execution_sha):
    work = project / 'evaluation'
    require(sha(work / 'execution.json') == expected_execution_sha, 'execution binding drift')
    execution = read(work / 'execution.json')
    verify(work, execution)
    fd = os.open(work / 'once-only.lock', os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode()); os.close(fd)
    started = time.monotonic()
    resources(work)  # Fail before the first match if the owning cgroup is wrong.
    pilot, train, _ = bindings(project)
    # Adapter state is process-local; original helper files remain byte-identical.
    alpha.ART, alpha.ROOT = work, work / 'collector-root'
    alpha.ANCHORS = tuple(pilot['evaluation']['acceptance']['anchors'])
    alpha.DISPLAY = DISPLAY
    eval_train = copy.deepcopy(train)
    eval_train['opponents']['prism-general-v011']['hello'] = {'agent_name': 'prism-sample', 'agent_version': '0.1.0'}
    result = {'format': 'm60-fixed-c4-evaluation-result-v1', 'created_at': now(),
              'candidate_sha256': CANDIDATE_SHA, 'execution_sha256': expected_execution_sha,
              'training_original_status': 'STOPPED_COMMITTED_PER_TRAINING_AUDIT', 'development': 'NOT_RUN',
              'independent_strength_acceptance': 'NOT_RUN', 'inference_time': 'NOT_MEASURED',
              'decision_time': 'NOT_MEASURED', 'acceptance_policy': pilot['evaluation']['acceptance']}
    try:
        for stage in ('development', 'acceptance'):
            verify(work, execution)
            plan = stage_run(project, work, stage, execution, started)
            write(work / 'status.json', {'state': stage.upper() + '_REPLAY_AUDIT', 'timestamp': now(),
                                        'stage_completed': sum(s['games'] for s in plan['shards']),
                                        'retry': 0, 'resources': resources(work)})
            rows, pairs = alpha.collect(plan, pilot['evaluation'], eval_train)
            result[stage] = {'games': len(rows), 'pairs': pairs,
                             'match_details_sha256': sha(work / stage / 'match-details.json'),
                             'source_ledger_sha256': sha(work / stage / 'source-ledger.json'),
                             'style_metrics_sha256': sha(work / stage / 'style-metrics.json'),
                             'plan_sha256': sha(work / stage / 'plan.json')}
            if stage == 'acceptance':
                result['measurements'], result['gates'] = alpha.measurements(rows, pilot['evaluation']['acceptance'])
                result['all_three_gates_passed'] = all(result['gates'].values())
                result['independent_strength_acceptance'] = 'PASS' if result['all_three_gates_passed'] else 'FAIL'
            write(work / 'result.json', result)
            del rows, pairs
        verify(work, execution)
        result['status'] = 'ACCEPTED_BIGCARD_CONTINUATION' if result['all_three_gates_passed'] else 'NOT_ACCEPTED_BIGCARD_CONTINUATION'
        result['finished_at'] = now()
        result['elapsed_wall_seconds'] = time.monotonic() - started
        result['resources'] = resources(work)
        write(work / 'result.json', result)
        write(work / 'completion.json', {'status': result['status'], 'timestamp': now(),
                                         'result_sha256': sha(work / 'result.json'), 'physical_games': 4480,
                                         'retry': 0, 'formal_gates_analyzed_once': True})
        write(work / 'status.json', read(work / 'completion.json'))
    except BaseException as exc:
        import psutil
        children = psutil.Process().children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(children, timeout=3)
        for child in alive:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        write(work / 'status.json', {'state': 'FAILED_NO_RETRY', 'timestamp': now(), 'error': str(exc),
                                    'elapsed_wall_seconds': time.monotonic() - started, 'retry': 0})
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('prepare', 'run', 'verify'))
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--execution-sha256')
    args = parser.parse_args()
    project = args.project.resolve()
    if args.mode == 'prepare':
        prepare(project)
    elif args.mode == 'verify':
        verify(project / 'evaluation', read(project / 'evaluation/execution.json'))
        print('PASS: frozen execution/assets/configs; zero games')
    else:
        require(bool(args.execution_sha256), 'run requires precommitted execution hash')
        run(project, args.execution_sha256)


if __name__ == '__main__':
    main()
