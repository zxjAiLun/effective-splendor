"""M63 once-only fixed Beta/control evaluation; import/prepare/verify run zero games.

Frozen M61 helpers are imported, never edited. The report/replay collector is bound through an isolated M63 namespace; M61 helpers remain read-only. A successful two-arm raw training audit and precommitted
execution SHA are required before the owned cgroup can dispatch the fixed grid.
"""
import argparse
import copy
import math
import os
from pathlib import Path
import sys
import time
import types

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import prism_balance_ab_evaluation_m61 as frozen
from scripts.prism_cloud_storage_snapshot import storage_bytes
from training.prism_portable.engine.ppo.building import default_building_config, validate_building_config
from training.prism_portable.engine.ppo.building_timed import default_timed_building_config, validate_timed_building_config

alpha, fixed = frozen.alpha, frozen.fixed
read, write, sha, require, now = frozen.read, frozen.write, frozen.sha, frozen.require, frozen.now
CONFIG = 'benchmarks/m63-prism-beta-timed-building.config.json'
CLOUD = '/home/ubuntu/splendor-ppo-m63'
MODELS = ('base', 'control', 'beta')
ARMS = ('control', 'beta')
ANCHORS = ('heuristic-v031', 'prism-v01', 'prism-general-v011')
DIRECT_PAIRS = (('control', 'base-t1'), ('beta', 'base-t1'),
                ('beta', 'control-t1'), ('beta', 'alpha-t1'), ('beta', 'previous-beta-t1'))
ACTION_SEED, BOOTSTRAP_SEED, SAMPLES = 63042001, 63049999, 20000
LOWER_Q = .05 / 10
GATES = {'control/strength_pool': -.05, 'control/direct_parent': .45,
         'beta/strength_pool': -.05, 'beta/general_anchor': -.075,
         'beta/direct_control': .45, 'beta/direct_alpha': .45,
         'beta/direct_parent': .45, 'beta/direct_previous_beta': .45, 'beta/building_utility': -.015,
         'beta/early_bonus_auc12': .25}
REQUIRED_GATES = {arm: [key.split('/')[1] for key in GATES if key.startswith(arm + '/')] for arm in ARMS}
PARENT_SHA = '225daf49e8746576b1edc3508ca0454715e5454529fea53dc7dfeb9043cf01f1'
PREVIOUS_BETA_SHA = '69a885b20527dda2e43fad9c00d7cc36537b45a0f5ccbaef4320001bef8836fb'
ALPHA_SHA = 'd3a313090bb2ccae678d3b9cf1216f0a60527ec330432c5c2dcdddd85b53b2d9'
LIMITS = dict(memory_bytes=8589934592, cpu_quota_percent=200, workers=2,
              wall_seconds=28800, cpu_seconds=40000, storage_bytes=34359738368,
              infrastructure_retries=0, physical_games=10304)
HELPERS = ('prism_building_evaluation_m63.py', 'prism_building_metrics_m63.py',
           'prism_building_report_m63.py', 'prism_building_html_report_m63.py', 'prism_balance_ab_evaluation_m61.py',
           'prism_balance_ab_report_m61.py', 'prism_cloud_storage_snapshot.py',
           'prism_alpha_round.py', 'prism_ppo_fixed_eval.py', 'prism_match_details.py',
           'prism_rush_round.py', 'prism_alpha_report.py', 'prism_rush_report.py')
SOURCE_FILES = tuple('scripts/' + name for name in HELPERS) + (
    'training/prism_portable/__init__.py', 'training/prism_portable/engine/__init__.py',
    'training/prism_portable/engine/ppo/__init__.py', 'training/prism_portable/engine/ppo/building.py',
    'training/prism_portable/engine/ppo/building_timed.py',
    'training/prism_portable/engine/ppo/contract.py', 'training/prism_portable/engine/data.py',
    'training/prism_portable/engine/io.py')
DISPLAY = {'base': 'Prism Balance v0.1.0 (T=1)',
           'control': 'M63 原目标对照 c4 (unpublished; no version registration; T=1)',
           'beta': 'Prism Beta v0.1.1 candidate (unpublished; T=1)',
           'base-t1': 'Prism Balance v0.1.0 (T=1)',
           'control-t1': 'M63 原目标对照 c4 (unpublished; no version registration; T=1)',
           'alpha-t1': 'Prism Alpha v0.1.4 (T=1)',
           'previous-beta-t1': 'Prism Beta v0.1.0 M62 frozen T1 (unpublished candidate; T=1)',
           'heuristic-v031': 'Heuristic v0.3.1 (greedy; Hello 0.2.9)',
           'prism-v01': 'Prism v0.1.0 (greedy)',
           'prism-general-v011': 'Prism v0.1.1 (T=1)'}
# Legacy bigcard curves are diagnostics. This contract is never used as M63 reward.
DIAGNOSTIC_STYLE = dict(format='prism-rush-style-v1', terminal_only=True,
    phase_semantics='choose_noble-belongs-to-preceding-main', short_game_padding='terminal-prestige',
    window_main_actions=24, score_cap=15, diagnostic_horizon_main_actions=20,
    diagnostic_score_threshold=8, style_reward_input='player-visible-own-prestige-and-terminal-own-prestige')


def expected_grid(start, end, direct=False):
    pairs = DIRECT_PAIRS if direct else [(m, op) for m in MODELS for op in ANCHORS]
    return {(m, op, seed, seat) for m, op in pairs for seed in range(start, end + 1) for seat in (0, 1)}


def stage_grid(stage, policy):
    c = policy[stage]
    grid = expected_grid(c['seed_start'], c['seed_end'])
    if stage == 'acceptance':
        grid |= expected_grid(c['seed_start'], c['direct_seed_end'], True)
    return grid


def validate_policy(evaluation):
    require(evaluation['total_games'] == 10304, 'M63 full evaluation budget drift')
    for stage, start, end, count, blocks in (('development', 9656000, 9656031, 576, 32),
                                            ('acceptance', 9661000, 9661255, 9728, 256)):
        c = evaluation[stage]
        require((c['seed_start'], c['seed_end'], c['total_games'], c['blocks'], c['action_seed']) ==
                (start, end, count, blocks, ACTION_SEED), 'M63 stage/seed/action/count drift')
        require(tuple(c['anchors']) == ANCHORS and tuple(c['models']) == MODELS, 'M63 anchor/model order drift')
    c = evaluation['acceptance']
    for key, value in dict(direct_seed_end=9661511, direct_blocks=512, anchor_total_games=4608,
            direct_total_games=5120, one_sided_claims=10, simultaneous_comparisons=10, family_alpha=.05,
            interval_sides='one-sided', lower_quantile=LOWER_Q, bootstrap_samples=SAMPLES,
            bootstrap_rng_seed=BOOTSTRAP_SEED, required_gates=REQUIRED_GATES, gates=GATES,
            no_extension_or_checkpoint_selection=True, once_only_final_candidate=True).items():
        require(c.get(key) == value, 'M63 frozen statistical policy drift: ' + key)
    require('upper_quantile' not in c, 'M63 family has a lower bound only')
    require(c.get('direct_pairs') == [['control', 'base'], ['beta', 'base'], ['beta', 'control'],
                                      ['beta', 'alpha'], ['beta', 'previous_beta']],
            'M63 direct-pair inventory drift')
    require(c.get('direct_previous_beta_games') == 1024 and c.get('total_physical_budget') == 12352,
            'M63 previous-Beta or total physical budget drift')


arm_path, blueprint_path = frozen.arm_path, frozen.blueprint_path


def source_sha_manifest(root=ROOT):
    """Return exact SHA256 pins for the M63 evaluator and read-only report helpers."""
    root = Path(root).resolve()
    return {name: sha(root / name) for name in SOURCE_FILES}


def owned(project, path):
    path = Path(path)
    if not path.is_absolute(): path = project / path
    require(path.resolve().is_relative_to(project.resolve()), 'evidence outside owned M63 root')
    return path.resolve()


def audit_evidence(project, pilot, audit, hashes, config_sha):
    require(audit.get('initial_policy_value_and_rng_equal') is True and audit.get('completed_games') == 2048,
            'M63 two-arm audit/initialization incomplete')
    require(set(audit['arms']) == set(ARMS), 'M63 audit arm coverage drift')
    files = {}
    for arm in ARMS:
        binding = audit['arms'][arm]
        require(binding['config_sha256'] == config_sha and binding['candidate_sha256'] == hashes[arm],
                'audit config/candidate binding drift')
        evidence, raw = binding['evidence'], {}
        for name in ('checkpoint', 'parity', 'full_training', 'campaign_status', 'source_ledger'):
            descriptor = evidence[name]; path = owned(project, descriptor['path'])
            require(sha(path) == descriptor['sha256'], 'raw audit receipt drift: ' + name)
            files[str(path)] = descriptor['sha256']; raw[name] = read(path)
        checkpoint, parity, full, status, ledger = (raw[k] for k in
                ('checkpoint', 'parity', 'full_training', 'campaign_status', 'source_ledger'))
        require(checkpoint['status'] == parity['status'] == 'PASS' and
                full['status'] == 'PASS_TRAINING_ARTIFACT_AUDIT' and status['status'] == 'STOPPED_COMMITTED',
                'raw audit not PASS/stopped')
        require(checkpoint['arm'] == parity['arm'] == full['arm'] == arm, 'raw audit arm drift')
        require(checkpoint['final_weights_sha256'] == parity['weights_sha256'] == full['candidate_sha256'] == hashes[arm],
                'raw audit weight drift')
        require(full['checkpoint'] == checkpoint and full['supervisor'] == status and
                full['completed_games'] == 1024 and full['source_ledger'] == evidence['source_ledger'],
                'full audit receipt/source/game mismatch')
        require(ledger['arm'] == arm and ledger['candidate_sha256'] == hashes[arm] and
                ledger['config_sha256'] == config_sha and len(ledger['rows']) == 1024 and
                len({r['job_id'] for r in ledger['rows']}) == 1024, 'training source ledger coverage')
        require(checkpoint['config_sha256'] == parity['config_sha256'] == config_sha and
                checkpoint['blueprint_sha256'] == pilot['training']['arms'][arm]['blueprint_sha256'],
                'raw audit blueprint/config drift')
        require(status['resources']['returncode'] == 0 and status['resources']['stop_reason'] is None and
                not status.get('alive', False), 'campaign not successfully stopped')
        require(owned(project, evidence['campaign_status']['path']) ==
                (arm_path(project, pilot, arm).parents[1] / 'control/status.json').resolve(), 'wrong campaign status')
    return files


def bindings(project, config_sha, audit_path):
    require(sha(project / CONFIG) == config_sha, 'pre-frozen M63 config drift')
    pilot = read(project / CONFIG)
    require(pilot['format'] == 'm63-prism-beta-timed-building-v1', 'M63 config format')
    validate_policy(pilot['evaluation'])
    require(pilot['runtime']['cloud_root'] == CLOUD, 'owned M63 root drift')
    require(pilot['base_model']['name'] == 'Prism Balance v0.1.0' and
            pilot['base_model']['sha256'] == pilot['assets']['parent']['sha256'] == PARENT_SHA and
            pilot['assets']['alpha']['sha256'] == ALPHA_SHA, 'frozen parent/Alpha identity drift')
    require(pilot['assets']['previous_beta']['sha256'] == PREVIOUS_BETA_SHA,
            'frozen M62 previous Beta identity drift')
    audit_path = owned(project, audit_path); audit = read(audit_path)
    require(audit['format'] == 'm63-training-audit-binding-v1' and
            audit['status'] == 'PASS_TRAINING_ARTIFACT_AUDIT', 'M63 raw training audit required')
    require(set(pilot['training']['arms']) == set(ARMS), 'M63 training arm coverage')
    trains, hashes = {}, {}
    for arm in ARMS:
        descriptor = pilot['training']['arms'][arm]
        path = owned(project, blueprint_path(project, descriptor))
        require(sha(path) == descriptor['blueprint_sha256'], 'blueprint drift: ' + arm)
        trains[arm] = read(path)['template']
        style_contract = trains[arm]['run']['style']
        if arm == 'control':
            validate_building_config(style_contract)
        else:
            validate_timed_building_config(style_contract)
            require(style_contract['base_contract'] == trains['control']['run']['style'],
                    'timed Beta base contract differs from original v1 control contract')
        require(style_contract == descriptor['style'], 'blueprint building contract drift')
        expected_coefficients = (.3, .5)
        require((trains[arm]['run']['ppo']['style_beta'], trains[arm]['run']['ppo']['style_value_weight']) ==
                expected_coefficients, 'M63 style coefficient drift')
        hashes[arm] = sha(arm_path(project, pilot, arm))
    require(trains['control']['run']['catalog_fingerprint'] == trains['beta']['run']['catalog_fingerprint'],
            'arm ruleset mismatch')
    audit_evidence(project, pilot, audit, hashes, config_sha)
    return pilot, trains, hashes


def descriptors(project, pilot, hashes):
    engine = pilot['runtime']['engine']
    require(engine == pilot['evaluation']['native_path_and_sha256'], 'engine identity disagreement')
    paths = {name: project / 'inputs' / (asset + '.json') for name, asset in
             (('base', 'parent'), ('alpha', 'alpha'), ('prism-v01', 'initial'), ('prism-general-v011', 'general'), ('previous_beta', 'previous_beta'))}
    paths.update({arm: arm_path(project, pilot, arm) for arm in ARMS})
    for name, asset in (('base', 'parent'), ('alpha', 'alpha'), ('prism-v01', 'initial'), ('prism-general-v011', 'general'), ('previous_beta', 'previous_beta')):
        require(sha(paths[name]) == pilot['assets'][asset]['sha256'], 'weight identity drift: ' + name)
    def desc(name, sampled=True):
        return dict(program=engine['path'], sha256=engine['sha256'],
            args=['agent-prism-sample' if sampled else 'agent-prism', '--weights', str(paths[name]),
                  '--seed', str(ACTION_SEED) if sampled else '51000001'],
            files=[dict(path=str(paths[name]), sha256=hashes[name] if name in hashes else sha(paths[name]))])
    candidates = {model: desc(model) for model in MODELS}
    opponents = {'heuristic-v031': dict(program=engine['path'], sha256=engine['sha256'],
        args=['agent-heuristic-v02', '--seed', '20260926'], files=[]),
        'prism-v01': desc('prism-v01', False), 'prism-general-v011': desc('prism-general-v011'),
        'alpha-t1': desc('alpha'), 'previous-beta-t1': desc('previous_beta')}
    return candidates, opponents


def shard_configs(stage, evaluation, engine, catalog, candidates, opponents):
    c = evaluation[stage]
    common = dict(format=fixed.FORMAT, engine=dict(program=engine['path'], sha256=engine['sha256']),
        catalog_fingerprint=catalog, action_seed=ACTION_SEED,
        timeouts=dict(game_wall_seconds=60, handshake_timeout_ms=10000, move_timeout_ms=10000, shutdown_grace_ms=1000))
    modes = [('anchors', candidates, {op: opponents[op] for op in ANCHORS}, c['seed_end'])]
    if stage == 'acceptance':
        modes += [('direct-parent', {m: candidates[m] for m in ARMS}, {'base-t1': candidates['base']}, c['direct_seed_end']),
                  ('direct-control', {'beta': candidates['beta']}, {'control-t1': candidates['control']}, c['direct_seed_end']),
                  ('direct-alpha', {'beta': candidates['beta']}, {'alpha-t1': opponents['alpha-t1']}, c['direct_seed_end']),
                  ('direct-previous-beta', {'beta': candidates['beta']}, {'previous-beta-t1': opponents['previous-beta-t1']}, c['direct_seed_end'])]
    seen, result = set(), []
    for mode, cs, ops, end in modes:
        width = 16 if stage == 'development' else 32
        for index, start in enumerate(range(c['seed_start'], end + 1, width)):
            cfg = copy.deepcopy(common)
            cfg.update(candidates=copy.deepcopy(cs), opponents=copy.deepcopy(ops), seeds=list(range(start, min(start + width, end + 1))))
            keys = {(m, op, s, seat) for m in cs for op in ops for s in cfg['seeds'] for seat in (0, 1)}
            require(not seen.intersection(keys), 'duplicate logical M63 match')
            seen.update(keys); result.append((f'{mode}-{index}', mode, cfg, len(keys)))
    require(seen == stage_grid(stage, evaluation) and len(seen) == c['total_games'], 'M63 evaluation grid mismatch')
    return result


def prepare(project, config_sha, audit_path):
    project = Path(project).resolve()
    pilot, trains, hashes = bindings(project, config_sha, audit_path)
    audit_path = owned(project, audit_path)
    work = project / 'evaluation'
    require(not work.exists(), 'evaluation already prepared; refuse overwrite')
    candidates, opponents = descriptors(project, pilot, hashes)
    files = {str(project / name): digest for name, digest in source_sha_manifest(project).items()}
    for name in SOURCE_FILES:
        require(sha(ROOT / name) == files[str(project / name)], 'imported/deployed source mismatch: ' + name)
    files.update({str(project / CONFIG): config_sha, str(audit_path): sha(audit_path)})
    files.update(audit_evidence(project, pilot, read(audit_path), hashes, config_sha))
    for arm in ARMS:
        path = blueprint_path(project, pilot['training']['arms'][arm]); files[str(path)] = sha(path)
        files[str(arm_path(project, pilot, arm))] = hashes[arm]
    for name, digest in pilot['runtime'].get('source_hashes', {}).items():
        path = owned(project, name)
        require(sha(path) == digest, 'training source drift: ' + name); files[str(path)] = digest
    assets = {}
    for name in ('parent', 'alpha', 'general', 'initial', 'previous_beta', 'fixtures'):
        path = project / 'inputs' / (name + ('.jsonl' if name == 'fixtures' else '.json'))
        require(sha(path) == pilot['assets'][name]['sha256'], 'asset drift: ' + name)
        files[str(path)] = sha(path); assets[name] = dict(path=str(path), sha256=sha(path))
    binaries = {key: pilot['runtime'][field] for key, field in
                (('engine', 'engine'), ('economy', 'metrics'), ('style', 'bigcard_metrics'), ('projection', 'projection'))}
    for desc in binaries.values():
        require(sha(desc['path']) == desc['sha256'], 'native drift'); files[desc['path']] = desc['sha256']
    snapshot = pilot['runtime']['projection_source_snapshot']
    require(bool(snapshot.get('files')), 'projection source snapshot missing')
    for name, digest in snapshot['files'].items():
        path = owned(project, name)
        require(sha(path) == digest, 'projection source drift: ' + name); files[str(path)] = digest
    work.mkdir()
    for name, value in (('style.json', DIAGNOSTIC_STYLE), ('building-style.json', default_building_config()),
                        ('timed-building-style.json', default_timed_building_config())):
        write(work / name, value); files[str(work / name)] = sha(work / name)
    for link, target in ((work / 'build/release/examples/prism_bigcard_metrics.exe', binaries['style']['path']),
            (work / 'collector-root/local-artifacts/prism/v01/bin/s4_batch_metrics.exe', binaries['economy']['path'])):
        link.parent.mkdir(parents=True, exist_ok=True); link.symlink_to(target); files[str(link)] = sha(link)
    for stage in ('development', 'acceptance'):
        stage_root = work / stage; (stage_root / 'configs').mkdir(parents=True)
        shards = []
        for name, mode, cfg, count in shard_configs(stage, pilot['evaluation'], binaries['engine'],
                trains['beta']['run']['catalog_fingerprint'], candidates, opponents):
            path = stage_root / 'configs' / (name + '.json'); write(path, cfg)
            fixed.check_assets(fixed.validate_config(cfg, path)); files[str(path)] = sha(path)
            shards.append(dict(mode=mode, config=str(path), config_sha256=sha(path), output=str(stage_root / 'runs' / name), games=count))
        path = stage_root / 'plan.json'
        write(path, dict(format='m63-building-evaluation-plan-v1', stage=stage, created_at=now(),
            started_after_audited_final_c4=True, candidate_sha256=hashes, shards=shards))
        files[str(path)] = sha(path)
    execution = dict(format='m63-building-evaluation-execution-v1', created_at=now(),
        candidates={m: dict(path=candidates[m]['files'][0]['path'], sha256=candidates[m]['files'][0]['sha256'], display_name=DISPLAY[m]) for m in MODELS},
        assets=assets, config_sha256=config_sha, audit_path=str(audit_path), audit_sha256=sha(audit_path),
        candidate_sha256=hashes, files=files, source_files=list(SOURCE_FILES), binaries=binaries,
        evaluation=pilot['evaluation'], projection_source_snapshot=snapshot,
        building_style=default_building_config(), timed_building_style=default_timed_building_config(),
        diagnostic_bigcard_style=DIAGNOSTIC_STYLE,
        candidate_selection='fixed audited final c4; no tuning', **LIMITS)
    write(work / 'execution.json', execution); verify(work, execution)
    print('PREPARED_ZERO_GAMES: fixed 10304-game grid; execution sha256=' + sha(work / 'execution.json'))
    return execution


def verify(work, execution):
    work = Path(work).resolve()
    require(execution['format'] == 'm63-building-evaluation-execution-v1', 'M63 execution format')
    require(all(execution.get(k) == v for k, v in LIMITS.items()), 'M63 execution resource/scope drift')
    validate_policy(execution['evaluation']); validate_building_config(execution['building_style'])
    validate_timed_building_config(execution['timed_building_style'])
    require(execution['timed_building_style']['base_contract'] == execution['building_style'],
            'timed metric base must match original v1 building contract')
    require(execution['diagnostic_bigcard_style'] == DIAGNOSTIC_STYLE, 'diagnostic style drift')
    require(execution['source_files'] == list(SOURCE_FILES), 'required helper/building source pins missing')
    for name in SOURCE_FILES:
        path = str(work.parent / name)
        require(path in execution['files'] and sha(ROOT / name) == execution['files'][path], 'imported source not pinned: ' + name)
    for path, digest in execution['files'].items(): require(sha(path) == digest, 'execution source/asset drift: ' + path)
    require(set(execution['binaries']) == {'engine', 'economy', 'style', 'projection'}, 'missing native identity')
    for desc in execution['binaries'].values():
        require(execution['files'].get(desc['path']) == desc['sha256'], 'native descriptor not pinned')
    require(bool(execution['projection_source_snapshot']['files']), 'projection source snapshot missing')
    for name, digest in execution['projection_source_snapshot']['files'].items():
        require(execution['files'].get(str(owned(work.parent, name))) == digest, 'projection source not pinned')
    for stage in ('development', 'acceptance'):
        plan = read(work / stage / 'plan.json'); rows = []
        require(plan['format'] == 'm63-building-evaluation-plan-v1' and plan['stage'] == stage and
                plan['candidate_sha256'] == execution['candidate_sha256'] and plan['started_after_audited_final_c4'] is True,
                'plan audit/context drift')
        for shard in plan['shards']:
            cfg = read(shard['config'])
            require(sha(shard['config']) == shard['config_sha256'], 'shard drift')
            fixed.check_assets(fixed.validate_config(cfg, shard['config']))
            batch = [dict(candidate=m, opponent=op, seed=s, candidate_seat=seat)
                for m in cfg['candidates'] for op in cfg['opponents'] for s in cfg['seeds'] for seat in (0, 1)]
            require(len(batch) == shard['games'], 'shard game count drift'); rows += batch
        alpha.assert_grid(rows, stage_grid(stage, execution['evaluation']))


def resources(work):
    import psutil
    cg = Path('/sys/fs/cgroup') / next(line.split(':', 2)[2].strip().lstrip('/')
        for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0:'))
    require('prism-m63-evaluation' in cg.name, 'not inside owned M63 evaluation service')
    require(int((cg / 'memory.max').read_text()) == LIMITS['memory_bytes'], 'systemd memory ceiling')
    quota, period = map(int, (cg / 'cpu.max').read_text().split()); require(quota == 2 * period, 'systemd CPU quota')
    cpu = dict(line.split() for line in (cg / 'cpu.stat').read_text().splitlines())
    return dict(cpu_seconds=int(cpu['usage_usec']) / 1e6, storage_bytes=storage_bytes(work.parent),
        memory_current_bytes=int((cg / 'memory.current').read_text()), memory_peak_bytes=int((cg / 'memory.peak').read_text()),
        host_available_memory_bytes=psutil.virtual_memory().available,
        memory_events={k: int(v) for k, v in (line.split() for line in (cg / 'memory.events').read_text().splitlines())}, cgroup=str(cg))


class Monitor(frozen.Monitor):
    def check_budget(self):
        usage = resources(self.work)
        require(time.monotonic() - self.started < LIMITS['wall_seconds'], 'evaluation wall budget')
        require(usage['cpu_seconds'] < LIMITS['cpu_seconds'], 'evaluation CPU budget')
        require(usage['storage_bytes'] < LIMITS['storage_bytes'], 'evaluation storage budget')
        require(usage['memory_events']['oom'] == usage['memory_events']['oom_kill'] == 0, 'evaluation OOM')
        return usage


def descriptive_ci(rows, pure_win=False):
    blocks = {}
    for row in rows:
        seat = row['candidate_seat']; block = blocks.setdefault(row['seed'], {})
        require(seat not in block, 'duplicate descriptive seed/seat')
        block[seat] = float(row['record'] == 'win') if pure_win else row['candidate_score']
    require(bool(blocks) and all(set(b) == {0, 1} for b in blocks.values()), 'incomplete descriptive seed block')
    result = alpha.interval([math.fsum(blocks[s].values()) / 2 for s in sorted(blocks)],
                           dict(bootstrap_rng_seed=BOOTSTRAP_SEED, bootstrap_samples=SAMPLES, lower_quantile=.025))
    return dict(mean=result['mean'], ordinary_95_ci=result['ci95'], seed_blocks=len(blocks),
                rng_seed=BOOTSTRAP_SEED, resamples=SAMPLES, kind='descriptive paired-seed ' + ('pure-win' if pure_win else 'half-draw'))


def validate_outcomes(rows, expected):
    alpha.assert_grid(rows, expected)
    for row in rows:
        seat = row['candidate_seat']
        require(type(seat) is int and seat in (0, 1), 'invalid candidate physical seat')
        scores, ranks, winners = row['scores'], row['ranks'], row['winners']
        fixed._validate_result(dict(scores=scores, ranks=ranks, winners=winners, reason='verified-terminal'))
        score, record = ((.5, 'draw') if ranks[seat] == ranks[1-seat] else
                         (1., 'win') if ranks[seat] < ranks[1-seat] else (0., 'loss'))
        require(row['candidate_score'] == score and row['record'] == record and
                row['candidate_points'] == scores[seat] and row['opponent_points'] == scores[1-seat],
                'outcome conservation / model seat mismatch')


def isolated_replay_collector(namespace):
    return types.FunctionType(alpha.collect.__code__, dict(namespace),
        name='m63_isolated_replay_collect', argdefs=alpha.collect.__defaults__,
        closure=alpha.collect.__closure__)


def collect(plan, evaluation, train, work, execution):
    from scripts import prism_building_metrics_m63 as building_metrics
    adapted = copy.deepcopy(train)
    adapted['run']['style'] = copy.deepcopy(DIAGNOSTIC_STYLE)
    for op in ('base-t1', 'control-t1', 'alpha-t1', 'previous-beta-t1', 'prism-general-v011'):
        adapted['opponents'][op] = {'hello': dict(agent_name='prism-sample', agent_version='0.1.0')}
    adapted['opponents']['heuristic-v031'] = {'hello': dict(agent_name='splendor-cli-heuristic-v02', agent_version='0.2.9')}
    # Bind the frozen replay collector to an isolated globals namespace. No legacy
    # M61/M56 module globals are patched and the M63 evaluation policy stays local.
    namespace = dict(alpha.__dict__)
    namespace.update(ART=Path(work), ROOT=ROOT, MODELS=MODELS, ANCHORS=ANCHORS,
                    DISPLAY=DISPLAY, expected_grid=expected_grid)
    isolated_collect = isolated_replay_collector(namespace)
    rows, pairs = isolated_collect(plan, evaluation, adapted)
    validate_outcomes(rows, stage_grid(plan['stage'], evaluation))
    profiles = building_metrics.collect(rows, work / plan['stage'], execution)
    for row in rows:
        key = (row['candidate'], row['opponent'], row['seed'], row['candidate_seat'])
        row['_building_profiles'] = profiles[key]
        profile = profiles[key][row['candidate_seat']]
        row.update(building_utility=profile['building_utility'], early_bonus_auc12=profile['early_bonus_auc12'])
    for pair in pairs:
        xs = [r for r in rows if (r['candidate'], r['opponent']) == (pair['candidate'], pair['opponent'])]
        pair['score_uncertainty'], pair['win_uncertainty'] = descriptive_ci(xs), descriptive_ci(xs, True)
        for name, offset in (('candidate_building', 0), ('opponent_building', 1)):
            pair[name] = building_metrics.profile_summary([r['_building_profiles'][r['candidate_seat'] ^ offset] for r in xs])
        for seat_record in pair['seats']:
            seat = seat_record['candidate_seat']; seat_rows = [r for r in xs if r['candidate_seat'] == seat]
            seat_record['candidate_building'] = building_metrics.profile_summary([r['_building_profiles'][seat] for r in seat_rows])
            seat_record['opponent_building'] = building_metrics.profile_summary([r['_building_profiles'][1-seat] for r in seat_rows])
    path = work / plan['stage'] / 'match-details.json'; document = read(path)
    document.update(pairs=pairs, building_metrics_sha256=sha(work / plan['stage'] / 'building-metrics.json'))
    write(path, document)
    return rows, pairs


def joint_intervals(vectors, stats):
    # Frozen helper shares draws for equal-length vectors. Its extra upper tail
    # is discarded; the M63 family is exclusively the ten one-sided lower bounds.
    adapted = dict(stats, upper_quantile=1 - stats['lower_quantile'])
    out = frozen.joint_intervals(vectors, adapted)
    return {key: dict(mean=value['mean'], ci95=value['ci95'],
        simultaneous_one_sided_lower=value['simultaneous_lower'], seed_blocks=value['seed_blocks'],
        bootstrap_rng_seed=stats['bootstrap_rng_seed'], bootstrap_samples=stats['bootstrap_samples'],
        lower_quantile=stats['lower_quantile']) for key, value in out.items()}


def measurements(rows, stats):
    expected = expected_grid(stats['seed_start'], stats['seed_end']) | expected_grid(stats['seed_start'], stats['direct_seed_end'], True)
    validate_outcomes(rows, expected)
    keyed = {(r['candidate'], r['opponent'], r['seed'], r['candidate_seat']): r for r in rows}
    def delta(model, baseline, field, anchors=ANCHORS):
        return [math.fsum(float(keyed[(model, op, s, seat)][field]) - float(keyed[(baseline, op, s, seat)][field])
                    for op in anchors for seat in (0, 1)) / (2 * len(anchors))
                for s in range(stats['seed_start'], stats['seed_end'] + 1)]
    def direct(model, opponent):
        return [math.fsum(keyed[(model, opponent, s, seat)]['candidate_score'] for seat in (0, 1)) / 2
                for s in range(stats['seed_start'], stats['direct_seed_end'] + 1)]
    vectors = {'control/strength_pool': delta('control', 'base', 'candidate_score'),
        'control/direct_parent': direct('control', 'base-t1'),
        'beta/strength_pool': delta('beta', 'control', 'candidate_score'),
        'beta/general_anchor': delta('beta', 'control', 'candidate_score', ('prism-general-v011',)),
        'beta/direct_control': direct('beta', 'control-t1'), 'beta/direct_alpha': direct('beta', 'alpha-t1'),
        'beta/direct_parent': direct('beta', 'base-t1'),
        'beta/building_utility': delta('beta', 'control', 'building_utility'),
        'beta/early_bonus_auc12': delta('beta', 'control', 'early_bonus_auc12'),
        'beta/direct_previous_beta': direct('beta', 'previous-beta-t1')}
    require(stats['gates'] == GATES and stats['one_sided_claims'] == stats['simultaneous_comparisons'] == len(vectors) == 10,
            'M63 ten-claim family drift')
    require(all(np.isfinite(v).all() for v in vectors.values()), 'nonfinite claim vector')
    out = joint_intervals(vectors, stats)
    gates = {key: out[key]['simultaneous_one_sided_lower'] >= threshold for key, threshold in GATES.items()}
    return out, gates


def verdicts(measures, gates):
    control = all(gates[key] for key in GATES if key.startswith('control/'))
    beta = all(gates[key] for key in GATES if key.startswith('beta/'))
    style = gates['beta/early_bonus_auc12']
    return dict(control_retention='PASS_RETENTION_FLOORS' if control else 'FAIL_RETENTION_FLOORS',
        beta_eight_gates='PASS_BETA_GATES' if beta else 'FAIL_BETA_GATES',
        beta_building_retention='PASS_BUILDING_RETENTION_TOLERANCE' if gates['beta/building_utility'] else 'FAIL_BUILDING_RETENTION_TOLERANCE',
        beta_style='PASS_BUILDING_STYLE_THRESHOLD' if style else 'FAIL_BUILDING_STYLE_THRESHOLD',
        cohort_qualified=control, beta_accepted=control and beta,
        beta_acceptance='ACCEPTED_BUILDING_CANDIDATE' if control and beta else
                        'BLOCKED_UNQUALIFIED_CONTROL' if beta else 'NOT_ACCEPTED_BUILDING_CANDIDATE',
        confirmed_enhancement={key: value['simultaneous_one_sided_lower'] > (.5 if '/direct_' in key else 0.)
                              for key, value in measures.items()})


def all_grid_completed(work, execution):
    # No diagnostic or formal statistics until every stage is complete.
    for stage in ('development', 'acceptance'):
        rows = []
        for shard in read(work / stage / 'plan.json')['shards']:
            root = Path(shard['output']); completion = read(root / 'completion.json')
            require(completion['result_sha256'] == sha(root / 'result.json'), 'completed shard result drift')
            validated = fixed.validate_config(read(shard['config']), shard['config'])
            rows += fixed._rows_from_progress(read(root / 'progress.json'), validated)
        validate_outcomes(rows, stage_grid(stage, execution['evaluation']))


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
                proc = subprocess.Popen([sys.executable, '-B', str(project / 'scripts/prism_ppo_fixed_eval.py'),
                    '--config', shard['config'], '--output', shard['output']], stdin=subprocess.DEVNULL,
                    stdout=log, stderr=subprocess.STDOUT)
                active.append((proc, log, shard))
            running, completed = [], finished
            for proc, log, shard in active:
                code = proc.poll()
                if code is None:
                    progress = Path(shard['output']) / 'progress.json'
                    if progress.exists(): completed += sum(r['status'] == 'completed' for r in read(progress)['games'].values())
                    running.append((proc, log, shard))
                else:
                    log.close()
                    require(code == 0, f"shard failed without retry: {shard['config']} exit={code}")
                    require(Path(shard['output'], 'completion.json').exists(), 'missing completed shard')
                    finished += shard['games']; completed += shard['games']
            active = running
            write(work / 'status.json', dict(state=stage.upper() + '_RUNNING', timestamp=now(),
                stage_completed=completed, stage_total=sum(s['games'] for s in plan['shards']),
                active_worker_pids=[proc.pid for proc, _, _ in active], retry=0, resources=monitor.check()))
            if queue or active: time.sleep(5)
    finally:
        for _, log, _ in active: log.close()
    return plan


def run(project, execution_sha):
    project = Path(project).resolve(); work = project / 'evaluation'; started_at = now()
    require(sha(work / 'execution.json') == execution_sha, 'precommitted execution binding drift')
    execution = read(work / 'execution.json'); verify(work, execution)
    fd = os.open(work / 'once-only.lock', os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode()); os.close(fd)
    started, monitor = time.monotonic(), None
    try:
        monitor = Monitor(work, started)
        pilot, trains, hashes = bindings(project, execution['config_sha256'], Path(execution['audit_path']))
        plans, clocks = {}, {}
        for stage in ('development', 'acceptance'):
            verify(work, execution); stamp = time.monotonic()
            plans[stage] = stage_run(project, work, stage, monitor)
            clocks[stage] = time.monotonic() - stamp
        verify(work, execution); all_grid_completed(work, execution)
        result = dict(format='m63-building-evaluation-result-v1', started_at=started_at,
            clock_scope='owned service: dispatch, saved replay audits, metrics, one formal analysis',
            execution_sha256=execution_sha, config_sha256=execution['config_sha256'], candidate_sha256=hashes,
            acceptance_policy=pilot['evaluation']['acceptance'], training_artifact_audit=dict(path=execution['audit_path'], sha256=execution['audit_sha256']),
            inference_time='NOT_MEASURED', decision_time='NOT_MEASURED', retries=0, physical_games=10304)
        for stage in ('development', 'acceptance'):
            monitor.check(); verify(work, execution); stamp = time.monotonic()
            rows, pairs = collect(plans[stage], pilot['evaluation'], trains['beta'], work, execution)
            result[stage] = dict(games=len(rows), pairs=pairs, dispatch_wall_seconds=clocks[stage],
                audit_metrics_wall_seconds=time.monotonic() - stamp,
                clock_scope='stage dispatch wall and subsequent saved-replay metric wall; no per-inference clock',
                **{name.replace('-', '_') + '_sha256': sha(work / stage / (name + '.json'))
                   for name in ('match-details', 'source-ledger', 'style-metrics', 'building-metrics', 'plan')})
            if stage == 'acceptance':
                fd = os.open(work / 'formal-analysis.lock', os.O_CREAT | os.O_EXCL | os.O_WRONLY); os.close(fd)
                result['measurements'], result['gates'] = measurements(rows, pilot['evaluation']['acceptance'])
            del rows, pairs
        result['verdicts'] = verdicts(result['measurements'], result['gates'])
        verify(work, execution)
        result.update(status='COMPLETED_FIXED_BUILDING_EVALUATION', finished_at=now(),
                      elapsed_wall_seconds=time.monotonic() - started, resources=monitor.check())
        write(work / 'result.json', result)
        write(work / 'completion.json', dict(status=result['status'], timestamp=now(),
            result_sha256=sha(work / 'result.json'), physical_games=10304, retry=0, formal_gates_analyzed_once=True))
        write(work / 'status.json', read(work / 'completion.json'))
    except BaseException as exc:
        frozen.stop_children()
        write(work / 'status.json', dict(state='FAILED_NO_RETRY', timestamp=now(), error=str(exc),
                                       elapsed_wall_seconds=time.monotonic() - started, retry=0))
        raise
    finally:
        if monitor is not None: monitor.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('prepare', 'verify', 'run'))
    parser.add_argument('--project', type=Path, default=Path(CLOUD))
    parser.add_argument('--config-sha256'); parser.add_argument('--audit-receipt', type=Path)
    parser.add_argument('--execution-sha256'); args = parser.parse_args(); project = args.project.resolve()
    if args.mode == 'prepare':
        require(bool(args.config_sha256) and args.audit_receipt is not None, 'prepare needs frozen config hash and raw audit binding')
        prepare(project, args.config_sha256, args.audit_receipt.resolve())
    else:
        require(bool(args.execution_sha256), 'verify/run needs precommitted execution hash')
        if args.mode == 'run': run(project, args.execution_sha256)
        else:
            work = project / 'evaluation'
            require(sha(work / 'execution.json') == args.execution_sha256, 'execution binding drift')
            verify(work, read(work / 'execution.json')); print('PASS: frozen M63 execution; zero games')


if __name__ == '__main__': main()
