"""Prism v0.1 isolated collection/evaluation runner. No automatic match retries."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import random
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'benchmarks/m51-prism-v01.config.json'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def save(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    tmp.replace(path)


def invoke(command, log, timeout=600):
    start = time.perf_counter()
    proc = subprocess.run([str(x) for x in command], cwd=ROOT, capture_output=True, timeout=timeout)
    record = dict(command=[str(x) for x in command], exit_code=proc.returncode,
                  seconds=time.perf_counter()-start,
                  stdout=proc.stdout.decode('utf-8', errors='replace'),
                  stderr=proc.stderr.decode('utf-8', errors='replace'))
    save(log, record)
    if proc.returncode:
        raise RuntimeError(f'command failed: {log}: {record["stderr"][-2000:]}')
    return record


def one(config, stage, seed, seat):
    root = ROOT / config['artifact_root'] / stage
    game = root / 'games' / f'seed-{seed}' / f'r{seat}'
    done = game / 'done.json'
    teacher = ROOT / config['teacher']['program']
    engine = teacher if stage == 'collect' else ROOT / config['evaluation']['engine']
    weights = ROOT / config['evaluation']['weights']
    identity = dict(config_sha256=sha(CONFIG), teacher_sha256=sha(teacher), engine_sha256=sha(engine))
    if stage != 'collect':
        identity['weights_sha256'] = sha(weights)
    if done.exists():
        row = json.loads(done.read_text(encoding='utf-8'))
        if row['identity'] != identity:
            raise RuntimeError(f'identity changed: {done}')
        for name, digest in row['hashes'].items():
            if sha(game / name) != digest:
                raise RuntimeError(f'artifact changed: {game / name}')
        return row
    if game.exists() and any(game.iterdir()):
        raise RuntimeError(f'incomplete prior match preserved, refusing automatic replay: {game}')
    game.mkdir(parents=True, exist_ok=True)
    teacher_agent = dict(program=str(teacher), args=config['teacher']['args'])
    agents = [teacher_agent, teacher_agent]
    if stage != 'collect':
        candidate = dict(program=str(engine), args=config['evaluation']['candidate_args'] +
                        ['--weights', str(weights), '--decisions-out', str(game / 'decisions.jsonl')])
        agents = [candidate, teacher_agent] if seat == 0 else [teacher_agent, candidate]
    match_config = dict(game_id=f'prism-v01-{stage}-{seed}-r{seat}', seed=seed, agents=agents,
                        handshake_timeout_ms=config['evaluation']['handshake_timeout_ms'],
                        move_timeout_ms=config['evaluation']['move_timeout_ms'], shutdown_grace_ms=2000)
    save(game / 'match-config.json', match_config)
    command = [engine, 'run-match', '--config', game / 'match-config.json',
               '--report-out', game / 'arena-report.json', '--replay-out', game / 'match-replay.json']
    run = invoke(command, game / 'run-log.json')
    report = json.loads((game / 'arena-report.json').read_text(encoding='utf-8'))
    if report['outcome'].get('status') != 'completed':
        raise RuntimeError(f'non-completed match: {game}: {report["outcome"]}')
    invoke([engine, 'verify-replay', '--input', game / 'match-replay.json'], game / 'verify-log.json')
    result = report['outcome']['result']
    winners = result['winners']
    score = 1.0 if winners == [seat] else (0.5 if seat in winners and len(winners) > 1 else 0.0)
    hashes = {name: sha(game / name) for name in ['match-config.json', 'arena-report.json', 'match-replay.json']}
    if stage != 'collect':
        hashes['decisions.jsonl'] = sha(game / 'decisions.jsonl')
    row = dict(seed=seed, candidate_seat=seat, rotation=seat, won=score, result=result,
               plies=report['outcome']['completed_plies'], wall_seconds=run['seconds'],
               replay_path=str((game/'match-replay.json').relative_to(root)).replace('\\','/'),
               identity=identity, hashes=hashes)
    save(done, row)
    return row


def summarize(rows, config):
    import numpy as np
    wins = sum(r['won']==1 for r in rows)
    ties = sum(r['won']==0.5 for r in rows)
    seeds = sorted(set(r['seed'] for r in rows))
    blocks = [sum(r['won'] for r in rows if r['seed']==s)/2 for s in seeds]
    rng = np.random.default_rng(config['evaluation']['bootstrap_seed'])
    ci = np.quantile(np.asarray(blocks)[rng.integers(0,len(blocks),
                     (config['evaluation']['bootstrap_samples'],len(blocks)))].mean(axis=1)*100,[0.025,0.975]).tolist()
    return dict(games=len(rows), wins=wins,ties=ties,losses=len(rows)-wins-ties,
                pure_win_rate_percent=wins/len(rows)*100,
                score_rate_percent=sum(r['won'] for r in rows)/len(rows)*100,
                paired_bootstrap_95_percent=ci,
                seats={str(s):dict(games=sum(r['candidate_seat']==s for r in rows),
                         score_rate_percent=sum(r['won'] for r in rows if r['candidate_seat']==s)/len(seeds)*100)
                       for s in (0,1)},
                candidate_mean_score=sum(r['result']['scores'][r['candidate_seat']] for r in rows)/len(rows),
                opponent_mean_score=sum(r['result']['scores'][1-r['candidate_seat']] for r in rows)/len(rows))


def run(stage):
    config = json.loads(CONFIG.read_text(encoding='utf-8'))
    assert sha(ROOT/config['teacher']['program']) == config['teacher']['sha256']
    if stage == 'collect':
        jobs = [(s,0) for s in range(config['teacher']['seed_start'],config['teacher']['seed_start']+4000)]
    elif stage == 'smoke':
        jobs = [(config['evaluation']['smoke_seed'],s) for s in (0,1)]
    else:
        smoke = ROOT/config['artifact_root']/'smoke/manifest.json'
        assert smoke.is_file(), 'smoke must finish first'
        start = config['evaluation']['baseline_seed_start']
        jobs = [(s,r) for s in range(start,start+128) for r in (0,1)]
    start = time.perf_counter()
    rows=[]
    with ThreadPoolExecutor(max_workers=config['workers']) as pool:
        futures=[pool.submit(one,config,stage,s,r) for s,r in jobs]
        for future in as_completed(futures):
            rows.append(future.result())
            if len(rows)%100==0 or len(rows)==len(jobs):
                print(f'{stage} {len(rows)}/{len(jobs)} elapsed={time.perf_counter()-start:.1f}s',flush=True)
    rows.sort(key=lambda r:(r['seed'],r['candidate_seat']))
    root = ROOT/config['artifact_root']/stage
    save(root/'manifest.json',dict(format='prism-match-manifest-v1',stage=stage,rows=rows,
         config_sha256=sha(CONFIG),wall_seconds=time.perf_counter()-start))
    if stage != 'collect':
        save(root/'summary.json',summarize(rows,config))
    print(f'{stage} COMPLETE valid games={len(rows)}',flush=True)


if __name__ == '__main__':
    p=argparse.ArgumentParser(); p.add_argument('stage',choices=['collect','smoke','baseline'])
    run(p.parse_args().stage)
