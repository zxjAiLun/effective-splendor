"""M81 DSW2 offline delivery: existing replays only, no game dispatch."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import resource
import socket
import subprocess
import sys
import time
import zipfile

ROOT = Path('/mnt/workspace/splendor-m81-anchor-coverage-r1')
HERE = Path('/mnt/workspace/splendor-m81-delivery-r6')
PY = '/mnt/workspace/envs/splendor-m79-ppo-py312/bin/python'
PLAN = 'benchmarks/m81-anchor-coverage.execution-plan.json'
sys.path.insert(0, str(ROOT))


def read(p):
    return json.loads(Path(p).read_text())


def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def write(p, v):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + '.tmp')
    tmp.write_text(json.dumps(v, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(p)


def snapshot():
    from scripts.prism_m81_evaluate import _planned_shards
    shards = _planned_shards(read(ROOT / PLAN))
    if any(not (ROOT/'evaluation'/s['label']/'ledger.json').exists() or
           read(ROOT/'evaluation'/s['label']/'ledger.json')['execution_state'] != 'FINISHED'
           for s in shards):
        return {'status': 'WAITING_EVALUATION'}
    receipt = HERE/'snapshot.json'
    if receipt.exists():
        return read(receipt)
    files = []
    for s in shards:
        files.extend(p for p in (ROOT/'evaluation'/s['label']).rglob('*')
                     if p.is_file() and not p.name.endswith('.lock'))
    files.extend(p for p in (ROOT/'evaluation-configs').glob('*.json'))
    files.extend(ROOT/n for n in [PLAN, 'evaluation-plan.json', 'execution.json',
                                  'campaigns/A/cycle-20-export/weights.json',
                                  'campaigns/B/cycle-20-export/weights.json'])
    members = {}
    HERE.mkdir(exist_ok=True)
    with zipfile.ZipFile(HERE/'snapshot.zip', 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        for p in sorted(set(files)):
            data = p.read_bytes()
            name = p.relative_to(ROOT).as_posix()
            members[name] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
            z.writestr(name, data)
        z.writestr('transfer-members.json', json.dumps(members))
    out = dict(status='PASS', sha256=sha(HERE/'snapshot.zip'),
               bytes=(HERE/'snapshot.zip').stat().st_size, files=len(members),
               shards=len(shards), node=socket.gethostname(), observed_at=time.time())
    write(receipt, out)
    return out


def unpack(expected):
    assert sha(HERE/'snapshot.zip') == expected, 'transfer ZIP SHA mismatch'
    with zipfile.ZipFile(HERE/'snapshot.zip') as z:
        members = json.loads(z.read('transfer-members.json'))
        assert set(z.namelist()) == set(members) | {'transfer-members.json'}
        for name, identity in members.items():
            rel = Path(name)
            assert not rel.is_absolute() and '..' not in rel.parts
            data = z.read(name)
            assert len(data) == identity['bytes'] and hashlib.sha256(data).hexdigest() == identity['sha256']
            p = HERE/'data'/rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if p.exists():
                assert p.read_bytes() == data, 'existing snapshot differs'
            else:
                p.write_bytes(data)
        write(HERE/'data/transfer-members.json', members)
    write(HERE/'import.json', dict(status='PASS_SHA_BOUND_IMPORT', sha256=expected, files=len(members)))


def one_shard(args):
    source, label = args
    source = Path(source)
    from scripts import prism_m79_profile as profiler
    from scripts import prism_m81_report as report
    profiler.ROOT = ROOT
    profiler.legacy.ROOT = ROOT
    report._profile_source_bindings(ROOT)
    ledger_path = source/'evaluation'/label/'ledger.json'
    ledger = read(ledger_path)
    assert ledger['execution_state'] == 'FINISHED'
    assert ledger['manifest_sha256'] == sha(ledger_path.parent/'manifest.json')
    output = HERE/'profiles'/(label + '.json')
    binding = {'ledger_sha256': sha(ledger_path), 'profiler_sha256': sha(ROOT/'scripts/prism_m79_profile.py'),
               'adapter_sha256': sha(Path(__file__)), 'projector_sha256': report.PROFILE_PROJECTOR_SHA256}
    if output.exists():
        old = read(output)
        assert old['binding'] == binding, 'completed profile identity drift'
        return label, len(old['profiles']) // 2
    plan = read(source/PLAN)
    assets = plan['assets']
    rows, retained = [], []
    for key, entry in ledger['entries'].items():
        if entry['state'] != 'COMPLETED' or entry.get('kind') == 'PLY_CAP_TRUNCATED':
            retained.append({'key': key, 'state': entry['state'], 'kind': entry.get('kind')})
            continue
        r = entry['row']
        actor, opponent, seed, seat = (r[x] for x in ('candidate','opponent','seed','candidate_seat'))
        replay = ledger_path.parent/'games'/actor/opponent/f'seed-{seed}-seat-{seat}'/'replay.json'
        rows.append(dict(game_key=f'{actor}|{opponent}|{seed}|{seat}', replay_path=str(replay),
                         replay_sha256=sha(replay), candidate_model=actor, opponent_model=opponent,
                         candidate_sha256=assets['parent']['sha256'] if actor == 'base' else
                             sha(source/f'campaigns/{actor}/cycle-20-export/weights.json'),
                         opponent_sha256=None if opponent == 'heuristic' else
                             assets['parent' if opponent == 'parent' else opponent]['sha256'],
                         candidate_seat=seat, seed=seed, opponent=opponent))
    began = time.monotonic()
    result = profiler.profile_saved_replays(rows, projector=ROOT/'bin/prism_building_projection', batch_size=64)
    assert result['verify_receipt']['status'] == 'PASS'
    profiles = [p for group in result['profiles'].values() for p in group]
    write(output, dict(binding=binding, profiles=profiles, retained=retained,
                       receipt=result['verify_receipt'], wall_seconds=time.monotonic()-began))
    return label, len(rows)


def profile(source, baseline=False):
    from scripts.prism_m81_evaluate import _planned_shards
    specs = _planned_shards(read(source/PLAN))
    labels = [s['label'] for s in specs if not baseline or s['actor'] == 'base']
    finished, games = 0, 0
    began = time.time()
    with concurrent.futures.ProcessPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(one_shard, (str(source), label)) for label in labels]
        for future in concurrent.futures.as_completed(futures):
            label, n = future.result()
            finished += 1
            games += n
            write(HERE/'profile-status.json', dict(state='RUNNING', node=socket.gethostname(),
                  pid=os.getpid(), started_at=began, observed_at=time.time(),
                  finished_shards=finished, total_shards=len(labels), completed_replays=games, last_shard=label,
                  new_games=0, workers=8))
    write(HERE/('baseline-profile-completion.json' if baseline else 'profile-completion.json'),
          dict(status='PASS', shards=finished, games=games, new_games=0,
               wall_seconds=time.time()-began, observed_at=time.time()))


def summary():
    from collections import defaultdict
    from scripts import prism_m79_profile as profiler
    profiles, retained = [], []
    for p in sorted((HERE/'profiles').glob('*.json')):
        value = read(p)
        profiles.extend(v for v in value['profiles'] if v['candidate_role'] == 'candidate')
        retained.extend(value['retained'])
    aggregate = profiler.aggregate_profiles(profiles)
    groups = defaultdict(list)
    for p in profiles:
        groups[p['model'], p['opponent']].append(p)
    table = ['# M81 DSW2 回放补充画像', '',
             '使用本轮已保存回放，0新对局。补充第12/24个本人Main行动后的公开得分及贵族覆盖；全部为描述统计，不改变原竞技门。', '',
             '|模型|对手|终局数|Main12分数/覆盖|Main24分数/覆盖|有贵族局比例|',
             '|---|---|---:|---:|---:|---:|']
    extra = []
    for (actor, opponent), rows in sorted(groups.items()):
        temporal = profiler._temporal_summary(rows)
        noble_games = sum(p['nobles_selected'] > 0 for p in rows)
        extra.append(dict(model=actor, opponent=opponent, noble_games=noble_games,
                          nobles=sum(p['nobles_selected'] for p in rows), **temporal))
        values = []
        for horizon in (12,24):
            mean = temporal[f'own_main_{horizon}_vp_mean']
            values.append(('未测' if mean is None else f'{mean:.2f}') +
                          f" / {temporal[f'own_main_{horizon}_snapshot_games']}/{len(rows)}")
        table.append(f'|{actor}|{opponent}|{len(rows)}|{values[0]}|{values[1]}|{noble_games}/{len(rows)} ({noble_games/len(rows):.2%})|')
    table.extend(['', f'保留非终局记录：{len(retained)}；不以新局替换。提前结束未到达Main12/24的局不填零，均值仅针对实际到达该时点的局。', ''])
    write(HERE/'supplement.json', dict(status='PASS', new_games=0, games=len(profiles),
          aggregate=aggregate, groups=extra, retained=retained))
    (HERE/'supplement.md').write_text('\n'.join(table), encoding='utf-8')


def main():
    HERE.mkdir(exist_ok=True)
    mode = sys.argv[1]
    if mode == 'snapshot':
        print(json.dumps(snapshot()), flush=True)
    elif mode == 'import':
        unpack(sys.argv[2])
    elif mode == 'baseline':
        profile(ROOT, baseline=True)
    elif mode == 'complete':
        profile(HERE/'data')
        summary()
    else:
        raise ValueError(mode)


if __name__ == '__main__':
    # Finite auxiliary delivery window, independent of healthy main training.
    import signal
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError('DSW2 delivery window')))
    signal.alarm(6*3600)
    resource.setrlimit(resource.RLIMIT_CPU, (18000, 18030))
    try:
        main()
    except BaseException as error:
        write(HERE/'failure.json', dict(state='FAILED_RETAINED_EVIDENCE', error=repr(error), observed_at=time.time()))
        raise
