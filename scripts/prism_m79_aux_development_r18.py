"""Finite frozen c5 development on restored auxiliary node, no candidate selection."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import prism_m79_dual_dispatch as dual
from training.prism_portable.common import read, write, digest

CYCLE = int(os.environ['PRISM_M79_DEVELOPMENT_CYCLE'])
if CYCLE not in (10, 15):
    raise ValueError('only fixed c10/c15 authorized in this continuation')
OUT = ROOT / f'execution-revisions/aux-development-r13-c{CYCLE}'


def verify():
    binding = read(OUT / 'dispatch.json')
    dual._load_state(ROOT)
    dual._verify_aux_sources(ROOT, read(ROOT / 'execution.json'))
    runtime = dual._compatible_eval_runtime(ROOT, read(ROOT / 'execution.json'))
    capacity = read(ROOT / 'execution-revisions/aux-capacity-r18.json')
    if capacity['status'] != 'PASS_OWNER_100GB_CAPACITY' or capacity['owner_limit_bytes'] != 100000000000:
        raise ValueError('actual personal 100GB capacity qualification missing')
    if capacity['free_under_owner_limit_bytes'] < 20*1024**3:
        raise ValueError('personal capacity lacks 12GiB auxiliary role plus 8GiB reserve')
    if digest(ROOT / 'execution.json') != binding['execution_sha256'] or digest(ROOT / dual.PLAN_REL) != binding['plan_sha256']:
        raise ValueError('development execution binding drift')
    if binding['cpu_limit'] != 4000 or sum(x['planned_games'] for x in binding['rows']) != 256:
        raise ValueError('fixed development reservation changed')
    if digest(OUT / 'inputs.zip') != binding['bundle_sha256']:
        raise ValueError('development input transport drift')
    for name, expected in binding['files'].items():
        original = OUT / 'original-inputs' / name
        if digest(original) != expected:
            raise ValueError('original development input member drift')
    if digest(ROOT / f'campaigns/a/cycle-{CYCLE}-export/weights.json') != binding['files'][f'campaigns/a/cycle-{CYCLE}-export/weights.json']:
        raise ValueError('fixed checkpoint identity drift')
    return binding, runtime


def worker():
    binding, runtime = verify()
    b, e, _ = dual._runtime(ROOT)
    for row in binding['rows']:
        cfg = read(ROOT / 'evaluation-configs' / (row['label'] + '.json'))
        if dual.semantic_sha(cfg, ROOT) != dual.semantic_sha(
                read(OUT / 'original-inputs/evaluation-configs' / (row['label'] + '.json')),
                Path(binding['source_root'])):
            raise ValueError('development config semantic drift')
        output = ROOT / 'evaluation' / row['label']
        if output.exists():
            raise ValueError('new auxiliary development dispatch requires pristine shard')
        b.prepare(ROOT / 'evaluation-configs' / (row['label'] + '.json'),
                  ROOT / 'evaluation-configs' / (row['label'] + '.policy.json'), output)
    write(OUT / 'preflight.json', dict(status='PASS_ZERO_GAME_PREFLIGHT', new_games=0,
        runtime=runtime, execution_sha256=binding['execution_sha256'],
        adapter_sha256=digest(__file__), observed_at=time.time()))
    result = dual._dispatch_pristine(ROOT, binding['rows'], 4, OUT / 'worker-progress.json')
    counts = [b.inspect(ROOT / 'evaluation' / row['label']) for row in binding['rows']]
    completed = sum(x['completed_games'] for x in counts)
    caps = sum(x['truncated_games'] for x in counts)
    if completed + caps != 256 or caps > 8:
        raise ValueError('frozen c5 development incomplete or scientific cap exhausted')
    result.update(status='PASS_FIXED_CHECKPOINT_DEVELOPMENT', completed_games=completed,
        truncated_games=caps, counts=counts, node=platform.node(),
        checkpoint_sha256=digest(ROOT / f'campaigns/a/cycle-{CYCLE}-export/weights.json'),
        execution_sha256=binding['execution_sha256'], observed_at=time.time())
    write(OUT / 'worker-completion.json', result)
    return result


def run():
    binding, runtime = verify()
    from scripts.prism_dsw_ppo_process import ProcessTree
    os.environ.update(PRISM_PPO_CONTROL_DIR=str(OUT), OPENBLAS_NUM_THREADS='1',
        OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', PYTHONPATH=str(ROOT),
        PRISM_DSW_REMAINING_WALL=str(min(3600, binding['deadline'] - time.time(), binding['operational_stop'] - time.time())))
    with (OUT / 'worker.log').open('xb') as stream:
        with ProcessTree(cpu_seconds=4000, memory_bytes=8*1024**3, max_processes=64) as tree:
            proc = tree.start([sys.executable, '-B', str(Path(__file__).resolve()), 'worker'],
                cwd=ROOT, stdout=stream, stderr=stream)
            def publish(counters):
                write(OUT / 'status.json', dict(state='RUNNING', phase='FIXED_CHECKPOINT_DEVELOPMENT',
                    node=platform.node(), pid=os.getpid(), relay_pid=proc.pid,
                    resources=counters, observed_at=time.time()))
            # Each frozen shard independently enforces its 128 MiB budget.
            # Scan only this checkpoint's four shards; previous completed
            # cohorts on shared NAS are outside this invocation's writer scope.
            from training.prism_portable.processes import directory_bytes
            next_scan = [0.]
            def owned_storage_guard():
                if time.monotonic() < next_scan[0]:
                    return None
                next_scan[0] = time.monotonic() + 60
                total = sum(directory_bytes(ROOT/'evaluation'/row['label'])
                            for row in binding['rows']
                            if (ROOT/'evaluation'/row['label']).exists())
                return 'owned_development_storage_deadline' if total > 512*1024**2 else None
            counters = tree.wait(wall_seconds=min(3600, binding['deadline'] - time.time(), binding['operational_stop'] - time.time()),
                stop_checker=owned_storage_guard, snapshot=publish)
    receipt = dict(status='PASS' if counters['returncode']==0 and not counters['stop_reason'] else 'FAIL',
        resources=counters, original_aux_cpu=binding['original_aux_cpu'],
        cpu_reservation=4000, execution_sha256=binding['execution_sha256'],
        adapter_sha256=digest(__file__), node=platform.node(), observed_at=time.time())
    write(OUT / 'resource.json', receipt)
    if receipt['status'] != 'PASS':
        raise ValueError('auxiliary development hard failure retained')
    package = OUT / 'results.zip'
    members = {}
    with zipfile.ZipFile(package, 'x', zipfile.ZIP_DEFLATED) as archive:
        paths = [OUT / 'resource.json', OUT / 'worker-completion.json', OUT / 'preflight.json']
        paths += [p for row in binding['rows'] for p in sorted((ROOT/'evaluation'/row['label']).rglob('*')) if p.is_file()]
        for p in paths:
            name = p.relative_to(ROOT).as_posix()
            archive.write(p, name)
            members[name] = dict(sha256=digest(p), bytes=p.stat().st_size)
    delivery = dict(status='READY_FOR_SHA_IMPORT', sha256=digest(package),
        bytes=package.stat().st_size, files=members,
        labels=[x['label'] for x in binding['rows']],
        resources=receipt, observed_at=time.time())
    write(OUT / 'results.receipt.json', delivery)
    write(OUT / 'status.json', dict(state='COMPLETED_PENDING_CONTROL_IMPORT',
        resources=receipt, observed_at=time.time()))
    return delivery


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('run', 'worker', 'verify'))
    args = parser.parse_args()
    print(json.dumps(globals()[args.mode]()), flush=True)
