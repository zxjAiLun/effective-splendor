"""M61 audited final-c4 A/B evaluation. Import, prepare and verify run zero games.

prepare requires a previously frozen config SHA and a training-audit binding:
{"format":"m61-training-audit-binding-v1","status":"PASS_TRAINING_ARTIFACT_AUDIT",
 "arms":{"alpha":{"candidate_sha256":"..."},"balance":{"candidate_sha256":"..."}}}
No retry/resume: preserve the permanent lock and partial artifacts on any failure.
"""
import argparse
from contextlib import contextmanager
import copy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import prism_alpha_round as alpha
from scripts import prism_ppo_fixed_eval as fixed
from scripts.prism_cloud_storage_snapshot import storage_bytes

read, write, sha, require = fixed.read_json, fixed.atomic_json, fixed.sha256_file, fixed._require
CONFIG = 'benchmarks/m61-prism-alpha-balance-ab.config.json'
CLOUD = '/home/ubuntu/splendor-ppo-m61'
MODELS = ('base', 'alpha', 'balance')
ANCHORS = ('heuristic-v031', 'prism-v01', 'prism-general-v011')
ACTION_SEED = 61032001
BOOTSTRAP_SEED = 61039999
SAMPLES = 20000
LOWER_Q = .05 / (2 * 7)
LIMITS = dict(memory_bytes=8589934592, cpu_quota_percent=200, workers=2,
              wall_seconds=28800, cpu_seconds=40000, storage_bytes=34359738368,
              infrastructure_retries=0, physical_games=8256)
HELPERS = ('prism_balance_ab_evaluation_m61.py', 'prism_cloud_storage_snapshot.py',
           'prism_alpha_round.py', 'prism_ppo_fixed_eval.py', 'prism_match_details.py',
           'prism_rush_round.py', 'prism_alpha_report.py', 'prism_rush_report.py',
           'prism_balance_ab_report_m61.py')
DISPLAY = {'base': 'Prism Alpha v0.1.3 (T=1)',
           'alpha': 'M61 Alpha unpublished final-c4 training checkpoint (T=1)',
           'balance': 'M61 Balance unpublished final-c4 training checkpoint (T=1)',
           'base-t1': 'Prism Alpha v0.1.3 (T=1)',
           'alpha-t1': 'M61 Alpha unpublished final-c4 training checkpoint (T=1)',
           'heuristic-v031': 'Heuristic v0.3.1 (greedy; Hello 0.2.9)',
           'prism-v01': 'Prism v0.1.0 (greedy)',
           'prism-general-v011': 'Prism v0.1.1 (T=1)'}


def now():
    return datetime.now(timezone.utc).isoformat()


def expected_grid(start, end, direct=False):
    pairs = ([(m, 'base-t1') for m in ('alpha', 'balance')] + [('balance', 'alpha-t1')]
             if direct else [(m, op) for m in MODELS for op in ANCHORS])
    return {(m, op, seed, seat) for m, op in pairs
            for seed in range(start, end + 1) for seat in (0, 1)}


def validate_policy(evaluation):
    for stage, start, end, total in (('development', 9616000, 9616031, 576),
                                   ('acceptance', 9621000, 9621255, 7680)):
        c = evaluation[stage]
        require((c['seed_start'], c['seed_end'], c['total_games'], c['action_seed']) ==
                (start, end, total, ACTION_SEED), 'M61 stage/seed/action scope drift')
        require(tuple(c['anchors']) == ANCHORS, 'anchor identity/order drift')
    s = evaluation['acceptance']
    for k, v in dict(direct_seed_end=9621511, one_sided_claims=0, simultaneous_comparisons=7, family_alpha=.05,
                     lower_quantile=LOWER_Q, upper_quantile=1 - LOWER_Q,
                     bootstrap_samples=SAMPLES, bootstrap_rng_seed=BOOTSTRAP_SEED,
                     strength_pool_delta_lower_gte=-.05, direct_parent_score_lower_gte=.45,
                     bigcard_auc24_delta_lower_gte=-.015,
                     balance_alpha_pool_delta_lower_gt=0,
                     balance_alpha_direct_score_lower_gt=.5,
                     alpha_balance_pool_delta_upper_lt=0,
                     alpha_balance_direct_score_upper_lt=.5).items():
        require(s.get(k) == v, 'M61 frozen statistical policy drift: ' + k)
    require(s.get('interval_sides') == 'two-sided', 'two-sided family required')
    require(s.get('no_extension_or_checkpoint_selection') is True,
            'development/checkpoint selection prohibited')


def arm_path(project, pilot, arm):
    campaign = Path(pilot['training']['arms'][arm]['campaign'])
    if not campaign.is_absolute(): campaign = project / campaign
    require(campaign.resolve().is_relative_to((project / 'campaigns').resolve()), 'campaign outside owned root')
    return campaign / 'cycle-4-export/weights.json'


def blueprint_path(project, descriptor):
    return project / descriptor['blueprint_path']


def audit_evidence(project, pilot, audit, hashes, config_sha):
    require(audit.get('initial_policy_value_and_rng_equal') is True and audit.get('completed_games') == 2048,
            'two-arm audit/initialization incomplete')
    files = {}
    for arm in ('alpha', 'balance'):
        binding = audit['arms'][arm]
        require(binding['config_sha256'] == config_sha, 'audit/config binding drift')
        evidence = binding['evidence']; raw = {}
        for name in ('checkpoint', 'parity', 'full_training', 'campaign_status', 'source_ledger'):
            descriptor = evidence[name]; p = project / descriptor['path']
            require(p.resolve().is_relative_to(project.resolve()), 'audit evidence outside owned root')
            require(sha(p) == descriptor['sha256'], 'raw audit evidence drift: ' + name)
            files[str(p)] = descriptor['sha256']; raw[name] = read(p)
        checkpoint, parity, full, status = (raw[k] for k in ('checkpoint', 'parity', 'full_training', 'campaign_status'))
        require(checkpoint['status'] == parity['status'] == 'PASS' and
                full['status'] == 'PASS_TRAINING_ARTIFACT_AUDIT' and status['status'] == 'STOPPED_COMMITTED',
                'raw training audit not PASS/stopped')
        require(checkpoint['arm'] == parity['arm'] == full['arm'] == arm, 'audit arm identity drift')
        require(checkpoint['final_weights_sha256'] == parity['weights_sha256'] == full['candidate_sha256'] == hashes[arm],
                'raw audit/candidate binding drift')
        require(full['checkpoint'] == checkpoint and full['supervisor'] == status,
                'full audit/checkpoint/supervisor mismatch')
        require(full['completed_games'] == 1024 and full['source_ledger'] == evidence['source_ledger'],
                'full audit game/source coverage')
        ledger = raw['source_ledger']
        require(ledger['arm'] == arm and ledger['candidate_sha256'] == hashes[arm] and
                ledger['config_sha256'] == config_sha and len(ledger['rows']) == 1024 and
                len({row['job_id'] for row in ledger['rows']}) == 1024, 'training source ledger coverage')
        require(checkpoint['config_sha256'] == parity['config_sha256'] == config_sha and
                checkpoint['blueprint_sha256'] == pilot['training']['arms'][arm]['blueprint_sha256'],
                'raw audit frozen contract mismatch')
        require(status['resources']['returncode'] == 0 and status['resources']['stop_reason'] is None and
                not status.get('alive', False), 'campaign not successfully stopped')
        require(Path(evidence['campaign_status']['path']).resolve() ==
                (arm_path(project, pilot, arm).parents[1] / 'control/status.json').resolve(), 'wrong campaign status')
    return files


def bindings(project, config_sha, audit_path):
    require(sha(project / CONFIG) == config_sha, 'pre-frozen config drift')
    pilot = read(project / CONFIG)
    validate_policy(pilot['evaluation'])
    require(pilot['runtime']['cloud_root'] == CLOUD, 'owned M61 root drift')
    audit = read(audit_path)
    require(audit['format'] == 'm61-training-audit-binding-v1' and
            audit['status'] == 'PASS_TRAINING_ARTIFACT_AUDIT', 'training audit required')
    trains, hashes = {}, {}
    for arm in ('alpha', 'balance'):
        descriptor = pilot['training']['arms'][arm]
        path = blueprint_path(project, descriptor)
        require(sha(path) == descriptor['blueprint_sha256'], 'blueprint drift: ' + arm)
        trains[arm] = read(path)['template']
        hashes[arm] = sha(arm_path(project, pilot, arm))
        require(hashes[arm] == audit['arms'][arm]['candidate_sha256'], 'audited final-c4 drift: ' + arm)
    require(trains['alpha']['run']['catalog_fingerprint'] ==
            trains['balance']['run']['catalog_fingerprint'], 'arm ruleset mismatch')
    audit_evidence(project, pilot, audit, hashes, config_sha)
    return pilot, trains, hashes


def descriptors(project, pilot, hashes):
    engine = pilot['runtime']['engine']
    require(engine == pilot['evaluation']['native_path_and_sha256'], 'engine identity disagreement')
    paths = {'base': project / 'inputs/parent.json', 'prism-v01': project / 'inputs/initial.json',
             'prism-general-v011': project / 'inputs/general.json',
             **{arm: arm_path(project, pilot, arm) for arm in ('alpha', 'balance')}}
    for name, asset in (('base', 'parent'), ('prism-v01', 'initial'), ('prism-general-v011', 'general')):
        require(sha(paths[name]) == pilot['assets'][asset]['sha256'], 'weight identity drift: ' + name)
    require(sha(paths['base']) == pilot['base_model']['sha256'], 'parent identity mismatch')
    def desc(name, sampled=True):
        return {'program': engine['path'], 'sha256': engine['sha256'],
                'args': ['agent-prism-sample' if sampled else 'agent-prism', '--weights', str(paths[name]),
                         '--seed', str(ACTION_SEED) if sampled else '51000001'],
                'files': [{'path': str(paths[name]), 'sha256': hashes.get(name, sha(paths[name]))}]}
    candidates = {m: desc(m) for m in MODELS}
    opponents = {'heuristic-v031': {'program': engine['path'], 'sha256': engine['sha256'],
                 'args': ['agent-heuristic-v02', '--seed', '20260926'], 'files': []},
                 'prism-v01': desc('prism-v01', False), 'prism-general-v011': desc('prism-general-v011')}
    return candidates, opponents


def shard_configs(stage, evaluation, engine, catalog, candidates, opponents):
    """Pure grid partitioner; base anchors appear exactly once per stage."""
    c = evaluation[stage]
    common = dict(format=fixed.FORMAT, engine={'program': engine['path'], 'sha256': engine['sha256']},
                  catalog_fingerprint=catalog, action_seed=ACTION_SEED,
                  timeouts=dict(game_wall_seconds=60, handshake_timeout_ms=10000,
                                move_timeout_ms=10000, shutdown_grace_ms=1000))
    modes = [('anchors', candidates, opponents, c['seed_end'])]
    if stage == 'acceptance':
        modes += [('direct-parent', {m: candidates[m] for m in ('alpha', 'balance')},
                   {'base-t1': candidates['base']}, c['direct_seed_end']),
                  ('direct-ab', {'balance': candidates['balance']},
                   {'alpha-t1': candidates['alpha']}, c['direct_seed_end'])]
    seen, result = set(), []
    for mode, cs, ops, end in modes:
        width = 16 if stage == 'development' else 32
        for i, start in enumerate(range(c['seed_start'], end + 1, width)):
            cfg = copy.deepcopy(common)
            cfg.update(candidates=cs, opponents=ops, seeds=list(range(start, min(start + width, end + 1))))
            keys = {(m, op, s, seat) for m in cs for op in ops for s in cfg['seeds'] for seat in (0, 1)}
            require(not seen.intersection(keys), 'duplicate logical match')
            seen.update(keys)
            result.append((f'{mode}-{i}', mode, cfg, len(keys)))
    expected = expected_grid(c['seed_start'], c['seed_end'])
    if stage == 'acceptance':
        expected |= expected_grid(c['seed_start'], c['direct_seed_end'], True)
    require(seen == expected and len(seen) == c['total_games'], 'evaluation grid mismatch')
    return result


def prepare(project, config_sha, audit_path):
    pilot, trains, hashes = bindings(project, config_sha, audit_path)
    work = project / 'evaluation'
    require(not work.exists(), 'evaluation already prepared; refuse overwrite')
    candidates, opponents = descriptors(project, pilot, hashes)
    work.mkdir()
    files = {str(project / 'scripts' / name): sha(project / 'scripts' / name) for name in HELPERS}
    files.update({str(project / CONFIG): config_sha, str(audit_path): sha(audit_path)})
    files.update(audit_evidence(project, pilot, read(audit_path), hashes, config_sha))
    for arm in ('alpha', 'balance'):
        p = blueprint_path(project, pilot['training']['arms'][arm]); files[str(p)] = sha(p)
        files[str(arm_path(project, pilot, arm))] = hashes[arm]
    # Freeze all deployed Python source provenance too, when supplied by training freeze.
    for name, digest in pilot['runtime'].get('source_hashes', {}).items():
        p = project / name
        require(sha(p) == digest, 'training source drift: ' + name)
        files[str(p)] = digest
    for name in ('parent', 'general', 'initial', 'fixtures'):
        p = project / 'inputs' / (name + ('.jsonl' if name == 'fixtures' else '.json'))
        require(sha(p) == pilot['assets'][name]['sha256'], 'asset drift: ' + name)
        files[str(p)] = sha(p)
    write(work / 'style.json', trains['alpha']['run']['style'])
    files[str(work / 'style.json')] = sha(work / 'style.json')
    binaries = {'engine': pilot['runtime']['engine'], 'economy': pilot['runtime']['metrics'],
                'style': pilot['runtime'].get('bigcard_metrics', {
                    'path': '/home/ubuntu/splendor-ppo-m57/build/release/examples/prism_bigcard_metrics',
                    'sha256': '5510f847e31981bb223147639ef1e20c1b7317b5fe2a24d12668f4293919ad5a'})}
    for d in binaries.values():
        require(sha(d['path']) == d['sha256'], 'native drift')
        files[d['path']] = d['sha256']
    for link, target in ((work / 'build/release/examples/prism_bigcard_metrics.exe', binaries['style']['path']),
                         (work / 'collector-root/local-artifacts/prism/v01/bin/s4_batch_metrics.exe', binaries['economy']['path'])):
        link.parent.mkdir(parents=True, exist_ok=True); link.symlink_to(target)
        files[str(link)] = sha(link)
    for stage in ('development', 'acceptance'):
        stage_root = work / stage; (stage_root / 'configs').mkdir(parents=True)
        shards = []
        for name, mode, cfg, games in shard_configs(stage, pilot['evaluation'], binaries['engine'],
                trains['alpha']['run']['catalog_fingerprint'], candidates, opponents):
            p = stage_root / 'configs' / (name + '.json'); write(p, cfg)
            fixed.check_assets(fixed.validate_config(cfg, p)); files[str(p)] = sha(p)
            shards.append(dict(mode=mode, config=str(p), config_sha256=sha(p),
                               output=str(stage_root / 'runs' / name), games=games))
        p = stage_root / 'plan.json'
        write(p, dict(format='m61-balance-ab-evaluation-plan-v1', stage=stage, created_at=now(),
                      started_after_audited_final_c4=True, candidate_sha256=hashes, shards=shards))
        files[str(p)] = sha(p)
    execution = dict(format='m61-balance-ab-evaluation-execution-v1', created_at=now(),
                     candidates={m: {'path': candidates[m]['files'][0]['path'],
                                     'sha256': candidates[m]['files'][0]['sha256'],
                                     'display_name': DISPLAY[m]} for m in MODELS},
                     assets={name: {'path': str(project / 'inputs' / (name + ('.jsonl' if name == 'fixtures' else '.json'))),
                                    'sha256': pilot['assets'][name]['sha256']}
                             for name in ('parent', 'general', 'initial', 'fixtures')},
                     config_sha256=config_sha, audit_path=str(audit_path), audit_sha256=sha(audit_path),
                     candidate_sha256=hashes, files=files, binaries=binaries,
                     evaluation=pilot['evaluation'], balance_style_acceptance='NOT_CLAIMED', **LIMITS)
    write(work / 'execution.json', execution)
    verify(work, execution)
    print(json.dumps(dict(status='PREPARED_ZERO_GAMES', execution_sha256=sha(work / 'execution.json'), games=8256)))


def verify(work, execution):
    require(execution['format'] == 'm61-balance-ab-evaluation-execution-v1', 'execution format')
    require(all(execution.get(k) == v for k, v in LIMITS.items()), 'execution resource/scope drift')
    validate_policy(execution['evaluation'])
    for path, digest in execution['files'].items():
        require(sha(path) == digest, 'execution source/asset drift: ' + path)
    for stage in ('development', 'acceptance'):
        plan = read(work / stage / 'plan.json'); rows = []
        for shard in plan['shards']:
            cfg = read(shard['config'])
            require(sha(shard['config']) == shard['config_sha256'], 'shard drift')
            fixed.check_assets(fixed.validate_config(cfg, shard['config']))
            rows += [dict(candidate=m, opponent=o, seed=s, candidate_seat=seat)
                     for m in cfg['candidates'] for o in cfg['opponents'] for s in cfg['seeds'] for seat in (0, 1)]
        c = execution['evaluation'][stage]
        expected = expected_grid(c['seed_start'], c['seed_end'])
        if stage == 'acceptance': expected |= expected_grid(c['seed_start'], c['direct_seed_end'], True)
        alpha.assert_grid(rows, expected)


def resources(work):
    import psutil
    cg = Path('/sys/fs/cgroup') / next(line.split(':', 2)[2].strip().lstrip('/')
            for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0:'))
    require('prism-m61-evaluation' in cg.name, 'not inside owned M61 evaluation service')
    require(int((cg / 'memory.max').read_text()) == LIMITS['memory_bytes'], 'systemd memory ceiling')
    quota, period = map(int, (cg / 'cpu.max').read_text().split())
    require(quota == 2 * period, 'systemd CPU quota')
    cpu = dict(line.split() for line in (cg / 'cpu.stat').read_text().splitlines())
    return dict(cpu_seconds=int(cpu['usage_usec']) / 1e6, storage_bytes=storage_bytes(work.parent),
                memory_current_bytes=int((cg / 'memory.current').read_text()),
                memory_peak_bytes=int((cg / 'memory.peak').read_text()),
                host_available_memory_bytes=psutil.virtual_memory().available,
                memory_events={k: int(v) for k, v in (line.split() for line in (cg / 'memory.events').read_text().splitlines())},
                cgroup=str(cg))


def stop_children():
    import psutil
    children = psutil.Process().children(recursive=True)
    for child in children:
        try: child.terminate()
        except psutil.NoSuchProcess: pass
    _, alive = psutil.wait_procs(children, timeout=3)
    for child in alive:
        try: child.kill()
        except psutil.NoSuchProcess: pass


class Monitor:
    """Budget enforcement includes replay collection and final statistics."""
    def __init__(self, work, started):
        self.work, self.started = work, started
        self.done = threading.Event(); self.error = None
        self.check_budget()
        self.thread = threading.Thread(target=self.watch, daemon=True); self.thread.start()

    def check_budget(self):
        usage = resources(self.work)
        require(time.monotonic() - self.started < LIMITS['wall_seconds'], 'evaluation wall budget')
        require(usage['cpu_seconds'] < LIMITS['cpu_seconds'], 'evaluation CPU budget')
        require(usage['storage_bytes'] < LIMITS['storage_bytes'], 'evaluation storage budget')
        require(usage['memory_events']['oom'] == usage['memory_events']['oom_kill'] == 0, 'evaluation OOM')
        return usage

    def watch(self):
        while not self.done.wait(5):
            try: self.check_budget()
            except BaseException as exc:
                self.error = exc; stop_children(); return

    def check(self):
        if self.error is not None: raise self.error
        return self.check_budget()

    def close(self):
        self.done.set(); self.thread.join(timeout=10)


def stage_run(project, work, stage, monitor):
    plan = read(work / stage / 'plan.json')
    queue, active, finished = list(plan['shards']), [], 0
    try:
        while queue or active:
            monitor.check()
            while queue and len(active) < LIMITS['workers']:
                shard = queue.pop(0)
                require(not Path(shard['output']).exists(), 'refuse repeat/partial shard')
                log = open(Path(shard['config']).with_suffix('.log'), 'xb')
                p = subprocess.Popen([sys.executable, '-B', str(project / 'scripts/prism_ppo_fixed_eval.py'),
                                      '--config', shard['config'], '--output', shard['output']],
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
                active.append((p, log, shard))
            completed, running = finished, []
            for p, log, shard in active:
                code = p.poll()
                if code is None:
                    progress = Path(shard['output']) / 'progress.json'
                    if progress.exists(): completed += sum(r['status'] == 'completed' for r in read(progress)['games'].values())
                    running.append((p, log, shard))
                else:
                    log.close()
                    require(code == 0, f"shard failed without retry: {shard['config']} exit={code}")
                    require(Path(shard['output'], 'completion.json').exists(), 'missing completed shard')
                    finished += shard['games']; completed += shard['games']
            active = running
            write(work / 'status.json', dict(state=stage.upper() + '_RUNNING', timestamp=now(),
                stage_completed=completed, stage_total=sum(s['games'] for s in plan['shards']),
                active_worker_pids=[p.pid for p, _, _ in active], retry=0, resources=monitor.check()))
            if queue or active: time.sleep(5)
    finally:
        for _, log, _ in active: log.close()
    return plan


@contextmanager
def collector_adapter(work):
    names = ('ART', 'ROOT', 'MODELS', 'ANCHORS', 'DISPLAY', 'expected_grid')
    saved = {name: getattr(alpha, name) for name in names}
    try:
        alpha.ART, alpha.ROOT = work, work / 'collector-root'
        alpha.MODELS, alpha.ANCHORS, alpha.DISPLAY, alpha.expected_grid = MODELS, ANCHORS, DISPLAY, expected_grid
        yield
    finally:
        for name, value in saved.items(): setattr(alpha, name, value)


def descriptive_ci(rows, pure_win=False):
    blocks = {}
    for r in rows:
        blocks.setdefault(r['seed'], {})[r['candidate_seat']] = float(r['record'] == 'win') if pure_win else r['candidate_score']
    require(all(set(b) == {0, 1} for b in blocks.values()), 'incomplete descriptive seed block')
    stats = dict(bootstrap_rng_seed=BOOTSTRAP_SEED, bootstrap_samples=SAMPLES, lower_quantile=.025)
    result = alpha.interval([math.fsum(blocks[s].values()) / 2 for s in sorted(blocks)], stats)
    return dict(mean=result['mean'], ordinary_95_ci=result['ci95'], ci95=result['ci95'], seed_blocks=len(blocks),
                rng_seed=BOOTSTRAP_SEED, resamples=SAMPLES,
                kind='descriptive paired-seed pure-win bootstrap' if pure_win else 'descriptive paired-seed half-draw bootstrap')


def collect(plan, evaluation, train, work):
    adapted = copy.deepcopy(train)
    for op in ('prism-general-v011', 'alpha-t1'):
        adapted['opponents'][op] = {'hello': {'agent_name': 'prism-sample', 'agent_version': '0.1.0'}}
    adapted['opponents']['heuristic-v031'] = {'hello': {'agent_name': 'splendor-cli-heuristic-v02', 'agent_version': '0.2.9'}}
    with collector_adapter(work):
        rows, pairs = alpha.collect(plan, evaluation, adapted)
    for pair in pairs:
        xs = [r for r in rows if (r['candidate'], r['opponent']) == (pair['candidate'], pair['opponent'])]
        pair['score_uncertainty'] = descriptive_ci(xs)
        pair['win_uncertainty'] = descriptive_ci(xs, True)
    path = work / plan['stage'] / 'match-details.json'
    document = read(path); document['pairs'] = pairs; write(path, document)
    return rows, pairs


def joint_intervals(vectors, stats):
    """Share resampled seed indices across all claims with the same seed block."""
    out = {}
    for n in sorted({len(v) for v in vectors.values()}):
        keys = [k for k, v in vectors.items() if len(v) == n]
        xs = np.asarray([vectors[k] for k in keys], dtype=float)
        require(np.isfinite(xs).all(), 'nonfinite claim vector')
        rng = np.random.default_rng(stats['bootstrap_rng_seed'])
        draws = []
        for first in range(0, stats['bootstrap_samples'], 1000):
            indices = rng.integers(0, n, (min(1000, stats['bootstrap_samples'] - first), n))
            draws.append(xs[:, indices].mean(axis=2))
        samples = np.concatenate(draws, axis=1)
        for i, key in enumerate(keys):
            bounds = np.quantile(samples[i], [stats['lower_quantile'], stats['upper_quantile']]).tolist()
            out[key] = dict(mean=float(xs[i].mean()), ci95=np.quantile(samples[i], [.025, .975]).tolist(),
                            simultaneous_two_sided_ci=bounds, simultaneous_lower=bounds[0],
                            simultaneous_upper=bounds[1], seed_blocks=n)
    return out


def measurements(rows, stats):
    expected = expected_grid(stats['seed_start'], stats['seed_end']) | expected_grid(stats['seed_start'], stats['direct_seed_end'], True)
    alpha.assert_grid(rows, expected)
    keyed = {(r['candidate'], r['opponent'], r['seed'], r['candidate_seat']): r for r in rows}
    def delta(m, base, key):
        return [math.fsum(float(keyed[(m, op, s, seat)][key]) - float(keyed[(base, op, s, seat)][key])
                         for op in ANCHORS for seat in (0, 1)) / 6
                for s in range(stats['seed_start'], stats['seed_end'] + 1)]
    def direct(m, op):
        return [math.fsum(keyed[(m, op, s, seat)]['candidate_score'] for seat in (0, 1)) / 2
                for s in range(stats['seed_start'], stats['direct_seed_end'] + 1)]
    vectors = {}
    for arm in ('alpha', 'balance'):
        vectors[arm + '/strength_pool'] = delta(arm, 'base', 'candidate_score')
        vectors[arm + '/direct_parent'] = direct(arm, 'base-t1')
    vectors['alpha/bigcard_auc24'] = delta('alpha', 'base', 'large_card_vp_auc24')
    vectors['balance_vs_alpha/strength_pool'] = delta('balance', 'alpha', 'candidate_score')
    vectors['balance_vs_alpha/direct'] = direct('balance', 'alpha-t1')
    require(len(vectors) == stats['simultaneous_comparisons'] == 7 and stats['one_sided_claims'] == 0,
            'seven-comparison two-sided family')
    out = joint_intervals(vectors, stats)
    thresholds = {arm + '/' + key: stats[field] for arm in ('alpha', 'balance')
                  for key, field in (('strength_pool', 'strength_pool_delta_lower_gte'),
                                     ('direct_parent', 'direct_parent_score_lower_gte'))}
    thresholds['alpha/bigcard_auc24'] = stats['bigcard_auc24_delta_lower_gte']
    gates = {key: out[key]['simultaneous_lower'] >= threshold for key, threshold in thresholds.items()}
    a, b = out['balance_vs_alpha/strength_pool'], out['balance_vs_alpha/direct']
    balance = a['simultaneous_lower'] > 0 and b['simultaneous_lower'] > .5
    alpha_superior = a['simultaneous_upper'] < 0 and b['simultaneous_upper'] < .5
    comparison = dict(direction='Balance minus Alpha; direct score belongs to Balance',
                      balance_confirmed=balance, alpha_confirmed=alpha_superior,
                      verdict='CONFIRMED_BALANCE_SUPERIOR' if balance else
                              'CONFIRMED_ALPHA_SUPERIOR' if alpha_superior else 'INCONCLUSIVE')
    return out, gates, comparison


def run(project, execution_sha):
    started_at = now()
    work = project / 'evaluation'
    require(sha(work / 'execution.json') == execution_sha, 'precommitted execution binding drift')
    execution = read(work / 'execution.json'); verify(work, execution)
    fd = os.open(work / 'once-only.lock', os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode()); os.close(fd)
    started, monitor = time.monotonic(), None
    try:
        monitor = Monitor(work, started)
        pilot, trains, hashes = bindings(project, execution['config_sha256'], Path(execution['audit_path']))
        plans = {}
        for stage in ('development', 'acceptance'):
            verify(work, execution); plans[stage] = stage_run(project, work, stage, monitor)
        result = dict(format='m61-balance-ab-evaluation-result-v1', created_at=started_at,
                      started_at=started_at, clock_scope='owned service run: dispatch, replay audit and formal analysis',
                      execution_sha256=execution_sha, config_sha256=execution['config_sha256'],
                      candidate_sha256=hashes, acceptance_policy=pilot['evaluation']['acceptance'],
                      inference_time='NOT_MEASURED', decision_time='NOT_MEASURED',
                      balance_style_acceptance='NOT_CLAIMED', retries=0)
        # Formal analysis starts only after every declared shard has completed.
        for stage in ('development', 'acceptance'):
            monitor.check(); verify(work, execution)
            rows, pairs = collect(plans[stage], pilot['evaluation'], trains['alpha'], work)
            result[stage] = dict(games=len(rows), pairs=pairs,
                **{name.replace('-', '_') + '_sha256': sha(work / stage / (name + '.json'))
                   for name in ('match-details', 'source-ledger', 'style-metrics', 'plan')})
            if stage == 'acceptance':
                analysis_lock = work / 'formal-analysis.lock'
                fd = os.open(analysis_lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY); os.close(fd)
                result['measurements'], result['gates'], result['comparison'] = measurements(rows, pilot['evaluation']['acceptance'])
            del rows, pairs
        result['arm_verdicts'] = {arm: ('PASS_RETENTION_FLOORS' if all(v for k, v in result['gates'].items()
                                    if k.startswith(arm + '/')) else 'FAIL_RETENTION_FLOORS') for arm in ('alpha', 'balance')}
        verify(work, execution)
        result.update(status='COMPLETED_FIXED_AB_EVALUATION', finished_at=now(),
                      elapsed_wall_seconds=time.monotonic() - started, resources=monitor.check())
        write(work / 'result.json', result)
        write(work / 'completion.json', dict(status=result['status'], timestamp=now(),
              result_sha256=sha(work / 'result.json'), physical_games=8256, retry=0, formal_gates_analyzed_once=True))
        write(work / 'status.json', read(work / 'completion.json'))
    except BaseException as exc:
        stop_children()
        write(work / 'status.json', dict(state='FAILED_NO_RETRY', timestamp=now(), error=str(exc),
                                        elapsed_wall_seconds=time.monotonic() - started, retry=0))
        raise
    finally:
        if monitor is not None: monitor.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode', choices=('prepare', 'verify', 'run'))
    p.add_argument('--project', type=Path, default=Path(CLOUD))
    p.add_argument('--config-sha256'); p.add_argument('--audit-receipt', type=Path)
    p.add_argument('--execution-sha256')
    args = p.parse_args(); project = args.project.resolve()
    if args.mode == 'prepare':
        require(bool(args.config_sha256) and args.audit_receipt is not None, 'prepare needs frozen config hash and audit receipt')
        prepare(project, args.config_sha256, args.audit_receipt.resolve())
    else:
        require(bool(args.execution_sha256), 'verify/run requires precommitted execution hash')
        if args.mode == 'run': run(project, args.execution_sha256)
        else:
            work = project / 'evaluation'
            require(sha(work / 'execution.json') == args.execution_sha256, 'execution binding drift')
            verify(work, read(work / 'execution.json')); print('PASS: frozen execution/assets/configs; zero games')


if __name__ == '__main__':
    main()
