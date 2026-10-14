"""Offline strict Rust audit of completed auxiliary replays; no research sampling."""
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from training.prism_portable.common import read, write, digest
from scripts import prism_m79_dual_dispatch as dual


def main():
    out = ROOT / 'analysis/aux-saved-replay-audit-r14'
    out.mkdir(exist_ok=False)
    resource.setrlimit(resource.RLIMIT_CPU, (3000, 3001))
    resource.setrlimit(resource.RLIMIT_AS, (4*1024**3, 4*1024**3))
    os.sched_setaffinity(0, {4, 5, 6, 7})
    execution = read(ROOT / 'execution.json')
    dual._verify_aux_sources(ROOT, execution)
    binary = ROOT / 'bin/s4_batch_metrics'
    if digest(binary) != execution['files']['bin/s4_batch_metrics']:
        raise ValueError('strict Rust auditor identity drift')
    binding = dual._load_state(ROOT)
    started = time.time()
    rows = []
    for label in binding['aux_labels']:
        directory = ROOT / 'evaluation' / label
        ledger = read(directory / 'ledger.json')
        for key, entry in ledger['entries'].items():
            if entry.get('state') != 'COMPLETED':
                continue
            row = entry['row']
            replay = directory / 'games' / row['candidate'] / row['opponent'] / f"seed-{row['seed']}-seat-{row['candidate_seat']}" / 'replay.json'
            rows.append(dict(game_key=label+'/'+key, replay_path=str(replay),
                replay_sha256=digest(replay), candidate=row['candidate'],
                opponent=row['opponent'], seed=row['seed'], candidate_seat=row['candidate_seat']))
    if len(rows) != 6728:
        raise ValueError('completed auxiliary cohort changed; preserve new evidence separately')
    if len({row['game_key'] for row in rows}) != len(rows):
        raise ValueError('duplicate audit identity')
    completed = []
    for index, first in enumerate(range(0, len(rows), 256)):
        if time.time() >= 1791833400.0 or time.time()-started >= 7200:
            raise ValueError('finite offline audit deadline reached')
        subset = rows[first:first+256]
        manifest = out / f'batch-{index:03d}.manifest.json'
        result = out / f'batch-{index:03d}.metrics.json'
        write(manifest, dict(rows=subset))
        began = time.monotonic()
        process = subprocess.run([str(binary), str(manifest), str(result)],
            capture_output=True, text=True, timeout=600)
        record = dict(batch=index, games=len(subset), returncode=process.returncode,
            wall_seconds=time.monotonic()-began, manifest_sha256=digest(manifest),
            stdout=process.stdout, stderr=process.stderr,
            output_sha256=digest(result) if result.exists() else None)
        write(out / f'batch-{index:03d}.receipt.json', record)
        if process.returncode:
            raise ValueError('strict saved replay verification failed')
        completed.append(record)
        write(out / 'status.json', dict(state='RUNNING', node=platform.node(), pid=os.getpid(),
            games_verified=sum(row['games'] for row in completed), planned_games=6728,
            new_games=0, observed_at=time.time()))
    usage = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = dict(status='PASS_STRICT_SAVED_REPLAY_AUDIT', games_verified=len(rows),
        batches=completed, cohort_sha256=hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest(),
        binary_sha256=digest(binary), adapter_sha256=digest(__file__), new_games=0,
        cpu_seconds=usage.ru_utime+usage.ru_stime+children.ru_utime+children.ru_stime,
        accounting_category='audit_transfer_control', accounting_status='PENDING_ONCE_ONLY_CONTROL_RECONCILIATION',
        node=platform.node(), pid=os.getpid(), observed_at=time.time())
    write(out / 'completion.json', result)
    write(out / 'status.json', dict(result, state='COMPLETED'))
    return result


if __name__ == '__main__':
    print(json.dumps(main()), flush=True)
