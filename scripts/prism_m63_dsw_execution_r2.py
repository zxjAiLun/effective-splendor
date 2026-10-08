"""Explicit DSW execution port of the frozen M63 experiment, never retraining it.

The original config, audit, failure and source files remain byte-identical. Only
an in-memory path/native mapping, the R1 schema alias, and bounded DSW resources
change. Frozen match grids and the ten statistical tests are delegated verbatim.
"""
import argparse
from contextlib import contextmanager
import copy
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prism_m63_dsw_metrics_runtime import install as install_metrics_runtime
METRICS_RUNTIME = install_metrics_runtime(ROOT)
from scripts import prism_building_evaluation_m63 as experiment
from scripts import prism_m63_evaluation_compat_r1 as schema
from scripts.prism_notebook_arena import process_usage, resource_profile

PROJECT = Path('/mnt/workspace/splendor-m63-dsw-r2')
ORIGINAL_ROOT = '/home/ubuntu/splendor-ppo-m63'
REVISION = 'm63-dsw-execution-r2'
FAILURE_SHA = '3eaafea0b32a146f80f1918ea5bffd2fc4f3ac5524aaa713a972dd1b17c11148'
AUDIT_SHA = 'e193b9d91faab787751dd4d299a3f2c42f50e724e079833210e6e4f72669db75'
CANDIDATES = dict(control='965aa74777fc79ef6db592060fbdeac93836bbd1d47b1526efeddf7cde35a55d',
                  beta='3d81da745b7863b148cc3013386274f7aa7ac3f2ebdbe8a7701cc99c771edc12')
LIMITS = dict(experiment.LIMITS, workers=3, cpu_quota_percent=300)
DEPENDENCIES = {'numpy': '2.2.4', 'psutil': '7.0.0', 'Markdown': '3.8'}
READ, VERIFY, COLLECTOR = experiment.read, experiment.verify, experiment.isolated_replay_collector
sha, require, write, now = experiment.sha, experiment.require, experiment.write, experiment.now
NATIVES = dict(engine='splendor', metrics='s4_batch_metrics',
               bigcard_metrics='prism_bigcard_metrics', projection='prism_building_projection')


def relocate(value, project):
    """Map only absolute paths rooted at the original experiment, not arbitrary text."""
    if isinstance(value, str):
        if value == ORIGINAL_ROOT or value.startswith(ORIGINAL_ROOT + '/'):
            return str(project) + value[len(ORIGINAL_ROOT):]
        return value
    if isinstance(value, list): return [relocate(x, project) for x in value]
    if isinstance(value, dict): return {relocate(k, project): relocate(v, project) for k, v in value.items()}
    return value


def mapped_reader(project, native):
    def read(path):
        value = relocate(READ(path), project)
        if Path(path).resolve() == (project / experiment.CONFIG).resolve():
            value['runtime']['cloud_root'] = str(project)
            for key, name in NATIVES.items():
                value['runtime'][key] = dict(path=str(project / 'bin' / name),
                                            sha256=native['files']['bin/' + name]['sha256'])
            value['evaluation']['native_path_and_sha256'] = value['runtime']['engine'].copy()
        return value
    return read


def collector(namespace):
    # The frozen collector invokes the economy tool relative to ROOT. The
    # original prepare created that link under collector-root, not source ROOT.
    namespace = dict(namespace, ROOT=Path(namespace['ART']) / 'collector-root')
    return COLLECTOR(namespace)


def projection_profile_adapter(original):
    def profiles(row, projected, replay, config):
        experiment.validate_building_config(config)
        # The frozen collector passed the v1 contract to the timed extractor.
        # Supply its separately frozen timed wrapper; its base is that same v1.
        timed = experiment.default_timed_building_config()
        require(timed['base_contract'] == config, 'projection base contract drift')
        return original(row, projected, replay, timed)
    return profiles


def revision(project):
    project = Path(project).resolve()
    require(project == PROJECT, 'R2 requires its dedicated persistent DSW root')
    require(sha(project / experiment.CONFIG) == schema.CONFIG_SHA, 'original M63 config drift')
    require(sha(project / 'pipeline-driver-completion.json') == FAILURE_SHA, 'original failure drift')
    require(sha(project / 'training-artifact-audit.json') == AUDIT_SHA, 'original audit drift')
    failure = READ(project / 'pipeline-driver-completion.json')
    require(failure['status'] == 'FAILED_STOPPED_NO_RETRY' and
            failure['steps']['eval_prepare']['exit_code'] == 1 and
            'evaluation' not in failure['steps'], 'original pre-dispatch failure required')
    schema.canonical_binding(READ(project / 'training-artifact-audit.json'))
    config = READ(project / experiment.CONFIG)
    experiment.validate_policy(config['evaluation'])
    native = READ(project / 'native-port-receipt.json')
    require(native['format'] == 'm63-dsw-native-port-v1', 'native port receipt format')
    require(native['rust_source_snapshot'] == config['runtime']['rust_source_snapshot'] and
            native['projection_source_snapshot'] == config['runtime']['projection_source_snapshot'],
            'native source lineage differs from original M63')
    for key in NATIVES:
        require(native['original_binaries'][key] == config['runtime'][key], 'original binary lineage drift')
    for snapshot in (native['rust_source_snapshot'], native['projection_source_snapshot']):
        for name, digest in snapshot['files'].items():
            require(sha(project / name) == digest, 'frozen native source drift: ' + name)
    for name, descriptor in native['files'].items():
        require(name in {'bin/' + n for n in NATIVES.values()} and descriptor['elf_machine'] == 62,
                'wrong x86 native inventory')
        require(sha(project / name) == descriptor['sha256'], 'ported native drift: ' + name)
    require(set(native['files']) == {'bin/' + n for n in NATIVES.values()}, 'missing native port')
    parity_path = project / 'portability-parity.json'
    parity = READ(parity_path)
    require(parity['status'] == 'PASS_SAVED_INPUT_PORTABILITY' and parity['new_games'] == 0 and
            parity['boundary_rows_per_model'] == 68 and parity['models'] == 7 and
            parity['saved_replays'] == 8 and parity['prediction_max_abs_error'] <= 1e-4 and
            parity['offline_tool_semantics_equal'] is True and
            parity['native_port_receipt_sha256'] == sha(project / 'native-port-receipt.json'),
            'cross-architecture parity incomplete')
    dependencies = {n: importlib.metadata.version(n) for n in DEPENDENCIES}
    require(dependencies == DEPENDENCIES, 'R2 dependency versions drift')
    profile = resource_profile()
    require(profile['effective_cpu_capacity'] >= 3 and profile['effective_memory_bytes'] >= 10 * 1024**3,
            'DSW capacity below execution contract')
    files = ('scripts/prism_m63_dsw_execution_r2.py', 'scripts/prism_m63_dsw_metrics_runtime.py', 'scripts/prism_m63_evaluation_compat_r1.py',
             'scripts/prism_notebook_arena.py', 'native-port-receipt.json', 'portability-parity.json')
    return dict(format=REVISION, original_config_sha256=schema.CONFIG_SHA,
                original_failure_sha256=FAILURE_SHA, original_audit_sha256=AUDIT_SHA,
                candidate_sha256=CANDIDATES, project=str(project), dependencies=dependencies,
                original_limits=dict(LIMITS, workers=2, cpu_quota_percent=200), limits=LIMITS,
                resource_contract='3 inherited affinity cores; sampled aggregate RSS <=8GiB; per-process AS <=8GiB; no dedicated cgroup; zero retries',
                authorization='owner: use dsw; DSW2 shuts down after 1 hour of inactivity',
                compatibility=['canonical audit alias R1', 'ARM to x86 same frozen Rust sources',
                               'absolute evidence path mapping in memory', 'missing subprocess import',
                               'economy collector-root link', 'timed projection wrapper contract', METRICS_RUNTIME],
                files={str(project / n): sha(project / n) for n in files})


def verify_revision(project, execution):
    expected = revision(project)
    require(execution.get('execution_revision') == expected, 'R2 frozen revision drift')
    for path, digest in expected['files'].items():
        require(execution['files'].get(path) == digest, 'R2 evidence/source not pinned')
    require(execution['candidate_sha256'] == CANDIDATES, 'audited final c4 changed')
    VERIFY(project / 'evaluation', execution)


class Monitor(experiment.frozen.Monitor):
    def __init__(self, work, started):
        self.peak = 0
        super().__init__(work, started)

    def check_budget(self):
        usage = process_usage()
        self.peak = max(self.peak, usage['process_tree_rss_sum_bytes'])
        elapsed = time.monotonic() - self.started
        require(elapsed < LIMITS['wall_seconds'], 'R2 wall budget')
        require(usage['process_tree_cpu_seconds'] < LIMITS['cpu_seconds'], 'R2 CPU budget')
        require(usage['process_tree_rss_sum_bytes'] < LIMITS['memory_bytes'], 'R2 aggregate RSS budget')
        disk = experiment.storage_bytes(self.work.parent)
        require(disk < LIMITS['storage_bytes'], 'R2 storage budget')
        return dict(**usage, memory_peak_bytes=self.peak, storage_bytes=disk,
                    elapsed_wall_seconds=elapsed, load_average=list(os.getloadavg()),
                    affinity_cpus=sorted(os.sched_getaffinity(0)),
                    memory_limit_scope='sampled aggregate RSS; per-process AS; no dedicated cgroup')


@contextmanager
def context(project, strict=False):
    from scripts import prism_building_metrics_m63 as metrics
    native = READ(project / 'native-port-receipt.json')
    patches = dict(ROOT=project, CLOUD=str(project), LIMITS=LIMITS,
                   read=mapped_reader(project, native), Monitor=Monitor, subprocess=subprocess,
                   audit_evidence=schema.compatible_audit_evidence, isolated_replay_collector=collector)
    if strict:
        patches['verify'] = lambda work, execution: verify_revision(project, execution)
    saved = {name: (hasattr(experiment, name), getattr(experiment, name, None)) for name in patches}
    original_profiles = metrics.profiles_from_projection
    try:
        for name, value in patches.items(): setattr(experiment, name, value)
        metrics.profiles_from_projection = projection_profile_adapter(original_profiles)
        yield
    finally:
        metrics.profiles_from_projection = original_profiles
        for name, (existed, value) in saved.items():
            if existed: setattr(experiment, name, value)
            else: delattr(experiment, name)


def prepare(project):
    rev = revision(project)
    with context(project):
        execution = experiment.prepare(project, schema.CONFIG_SHA, project / 'training-artifact-audit.json')
        require(execution['candidate_sha256'] == CANDIDATES, 'final candidates differ')
        execution['execution_revision'] = rev
        execution['files'].update(rev['files'])
        verify_revision(project, execution)
        write(project / 'evaluation/execution.json', execution)
    print('R2 PREPARED_ZERO_GAMES: execution sha256=' + sha(project / 'evaluation/execution.json'))


def reports(project):
    from scripts import prism_building_report_m63 as report
    from scripts import prism_building_html_report_m63 as html
    work = project / 'evaluation'
    output = project / 'reports/m63-prism-beta-timed-building-evaluation.md'
    # Keep report provenance literal; the evaluator itself uses the audited
    # in-memory mapping within this context. Correct the legacy resource prose.
    report.report(work, output)
    text = output.read_text(encoding='utf-8').replace(
        '评测服务8GiB/CPU200%/2workers/8h/40,000CPU-s/32GiB。',
        'R2 DSW评测：3个继承affinity CPU/3workers；8GiB aggregate RSS软限额和单进程AS限额；8h/40,000CPU-s/32GiB；没有独占cgroup。')
    text += '\n## DSW执行修订R2（原失败保留）\n\nARM→x86使用原冻结305份Rust/Cargo源码；7模型×68保存输入及8份保存回放跨平台检查通过，0新增工程对局。原配置和审计字节保持，路径仅在内存映射；原十门及种子不变。\n'
    output.write_text(text, encoding='utf-8')
    html_path = output.with_suffix('.html')
    html.main(output, work / 'result.json', html_path)
    write(project / 'reports/completion.json', dict(status='COMPLETE_READABLE_REPORTS', timestamp=now(),
          markdown_sha256=sha(output), html_sha256=sha(html_path), result_sha256=sha(work / 'result.json')))


def run(project, digest):
    import resource
    path = project / 'evaluation/execution.json'
    require(sha(path) == digest, 'precommitted R2 execution SHA drift')
    with context(project, strict=True):
        verify_revision(project, READ(path))
        cpus = sorted(os.sched_getaffinity(0))[:3]
        require(len(cpus) == 3, 'three owned affinity cores unavailable')
        os.sched_setaffinity(0, cpus)
        resource.setrlimit(resource.RLIMIT_AS, (LIMITS['memory_bytes'], LIMITS['memory_bytes']))
        def interrupted(signum, frame): raise RuntimeError('R2 stopped by signal ' + str(signum))
        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        write(project / 'runner-owner.json', dict(pid=os.getpid(), execution_sha256=digest, started_at=now()))
        driver_started = time.monotonic()
        try:
            experiment.run(project, digest)
            monitor = Monitor(project / 'evaluation', driver_started)
            try:
                reports(project)
                monitor.check()
            finally: monitor.close()
            write(project / 'driver-completion.json', dict(status='COMPLETED_EVALUATION_AND_READABLE_REPORTS',
                  timestamp=now(), execution_sha256=digest, result_sha256=sha(project / 'evaluation/result.json'), retry=0))
        except BaseException as exc:
            experiment.frozen.stop_children()
            write(project / 'driver-completion.json', dict(status='FAILED_STOPPED_NO_RETRY',
                  timestamp=now(), execution_sha256=digest, error=str(exc), retry=0))
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('diagnose', 'prepare', 'verify', 'run'))
    parser.add_argument('--project', type=Path, default=PROJECT)
    parser.add_argument('--execution-sha256')
    args = parser.parse_args(); project = args.project.resolve()
    if args.mode == 'prepare': prepare(project)
    elif args.mode == 'diagnose':
        rev = revision(project)
        with context(project):
            _, _, hashes = experiment.bindings(project, schema.CONFIG_SHA, project / 'training-artifact-audit.json')
            require(hashes == CANDIDATES, 'c4 drift')
        print(json.dumps(dict(status='PASS_R2_ZERO_GAMES', new_games=0, **rev)))
    else:
        require(bool(args.execution_sha256), 'frozen execution SHA required')
        if args.mode == 'run': run(project, args.execution_sha256)
        else:
            require(sha(project / 'evaluation/execution.json') == args.execution_sha256, 'R2 execution hash drift')
            with context(project): verify_revision(project, READ(project / 'evaluation/execution.json'))
            print('PASS_R2_FROZEN_EXECUTION_ZERO_GAMES')


if __name__ == '__main__': main()
