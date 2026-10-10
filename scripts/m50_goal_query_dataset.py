"""Collect bounded teacher root labels, then materialize distinct policy targets."""
from __future__ import annotations

import concurrent.futures as futures
import json
import random
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from m50_teacher_query import query_teacher
from m50_v031_goal_round import goal, champion, read
from m50_reserve_target_binding_round import write_json, sha256


def open_split(directory, split, width):
    p = directory / split
    return {
        'obs': np.memmap(p / 'obs.f32', dtype='<f4', mode='r').reshape(-1, 368),
        'actions': np.memmap(p / 'actions.f32', dtype='<f4', mode='r').reshape(-1, width),
        'offsets': np.memmap(p / 'action_offsets.u64', dtype='<u8', mode='r'),
        'chosen': np.memmap(p / 'chosen_action.u32', dtype='<u4', mode='r'),
        'values': np.memmap(p / 'values.f32', dtype='<f4', mode='r').reshape(-1, 3),
    }


def query_roots(cfg, base):
    assert read(base / 'provenance/query-probe.json')['status'] == 'PASS'
    assert sha256(ROOT / cfg['executables']['teacher']['path']) == cfg['executables']['teacher']['sha256']
    model = read(base / 'interaction/planned.json')['candidate']
    rng = random.Random(50000037)
    samples, seen = {}, {}
    context_path = base / 'interaction-contexts.jsonl'
    with context_path.open(encoding='utf-8') as stream:
        for line in stream:
            context = json.loads(line)
            source = Path(context['offline']['source_replay'])
            if not source.is_absolute():
                source = ROOT / source
            source.relative_to(base / 'interaction')
            seat = int(source.parent.name.removeprefix('r'))
            if int(context['player_view']['actor']) != seat:
                continue
            key = str(source)
            seen[key] = seen.get(key, 0) + 1
            group = samples.setdefault(key, [])
            if len(group) < 5:
                group.append(context)
            else:
                j = rng.randrange(seen[key])
                if j < 5:
                    group[j] = context
    assert len(samples) == 2000
    roots = [c for group in samples.values() for c in group]
    rng.shuffle(roots)
    remaining_budget = 10000 - read(base / 'provenance/query-probe.json')['queries_used']
    roots = roots[:remaining_budget]
    write_json(base / 'provenance/query-roots-plan.json', [c['offline'] for c in roots])
    raw_meta = read(base / 'raw-c/manifest.json')
    width = raw_meta['action_width']
    arrays = {s: open_split(base / 'raw-c', s, width) for s in ('train', 'val')}
    def run(item):
        index, context = item
        off = context['offline']
        source = Path(off['source_replay'])
        if not source.is_absolute():
            source = ROOT / source
        seat = int(source.parent.name.removeprefix('r'))
        match = read(source.parent / 'match-config.json')
        assert Path(match['agents'][seat]['program']).resolve() == (ROOT / model['candidate_exe']).resolve()
        assert match['agents'][1 - seat]['args'] == cfg['teacher_args']
        assert off['split'] == ('val' if off['seed'] % 5 == 0 else 'train')
        data = arrays[off['split']]
        row = off['row_index_in_split']
        assert int(data['chosen'][row]) == off['chosen_action_index']
        assert int(data['offsets'][row + 1] - data['offsets'][row]) == len(context['player_view']['legal_actions'])
        result = query_teacher(ROOT / cfg['executables']['teacher']['path'], cfg['teacher_args'], context,
                               read(source.parent / 'arena-report.json'), f'correction-{index}')
        return {'offline': off, **result, 'teacher_sha256': cfg['executables']['teacher']['sha256']}
    records, errors = [], []
    pending, items = {}, iter(enumerate(roots))
    with (base / 'provenance/query-labels.jsonl').open('x', encoding='utf-8') as log, futures.ThreadPoolExecutor(max_workers=12) as pool:
        while pending or not errors:
            if not errors:
                while len(pending) < 12:
                    item = next(items, None)
                    if item is None:
                        break
                    pending[pool.submit(run, item)] = item[0]
            if not pending:
                break
            done, _ = futures.wait(pending, return_when=futures.FIRST_COMPLETED)
            for future in done:
                index = pending.pop(future)
                try:
                    row = future.result()
                    records.append(row)
                    log.write(json.dumps({'status': 'PASS', **row}) + '\n')
                except Exception as error:
                    errors.append({'index': index, 'error': repr(error)})
                    log.write(json.dumps({'status': 'ERROR', **errors[-1]}) + '\n')
                log.flush()
            if len(records) % 500 == 0 or len(records) == len(roots):
                print(f'queries: {len(records)}/{len(roots)}, errors={len(errors)}', flush=True)
    write_json(base / 'provenance/query-summary.json', {'status': 'PASS' if not errors else 'ERROR',
               'queries_used': len(records) + len(errors), 'probe_queries': 32, 'errors': errors,
               'contexts_sha256': sha256(context_path)})
    if errors:
        raise RuntimeError('unexpected query error after probe: no partial-label training or automatic retry')
    assert len(records) == len(roots)
    return records


def materialize(cfg, base, records):
    model = read(base / 'interaction/planned.json')['candidate']
    width = model['action_dim']
    expert_dir = base / ('data-b' if width == 97 else 'data-a')
    assert read(base / 'raw-c/manifest.json')['action_width'] == width
    out = base / 'data-c'
    out.mkdir(exist_ok=False)
    meta = {'format': 'm50-teacher-query-dataset-v1', 'observation_width': 368, 'action_width': width,
            'action_representation': read(expert_dir / 'manifest.json')['action_representation'],
            'policy_supervision': 'teacher-query', 'policy_label_source': 'policy_target.u32',
            'policy_mask': 'all', 'policy_row_alignment': 'dataset-row', 'policy_group': 'policy_group.u8',
            'policy_group_labels': {'0': 'teacher', '1': 'query'}, 'teacher_sha256': cfg['executables']['teacher']['sha256'],
            'expert_manifest_sha256': sha256(expert_dir / 'manifest.json'), 'query_labels_sha256': sha256(base / 'provenance/query-labels.jsonl'),
            'validation_mixture': 'equal groups by frozen deterministic expert-val subsample', 'splits': {}}
    rng = np.random.default_rng(50000037)
    for split in ('train', 'val'):
        expert = open_split(expert_dir, split, width)
        raw = open_split(base / 'raw-c', split, width)
        queries = sorted((r for r in records if r['offline']['split'] == split),
                         key=lambda r: r['offline']['row_index_in_split'])
        assert len({r['offline']['row_index_in_split'] for r in queries}) == len(queries)
        expert_ids = np.arange(len(expert['obs']))
        if split == 'val':
            expert_ids = np.sort(rng.choice(expert_ids, size=len(queries), replace=False))
        plan = [(expert, int(i), int(expert['chosen'][i]), 0) for i in expert_ids]
        plan += [(raw, r['offline']['row_index_in_split'], r['policy_target_idx'], 1) for r in queries]
        folder = out / split
        folder.mkdir()
        names = ('obs.f32', 'actions.f32', 'action_offsets.u64', 'chosen_action.u32', 'values.f32', 'policy_target.u32', 'policy_group.u8')
        streams = {n: (folder / n).open('xb', buffering=1024 * 1024) for n in names}
        total_actions = 0
        try:
            streams['action_offsets.u64'].write(np.array([0], dtype='<u8').tobytes())
            for data, row, target, group in plan:
                start, end = int(data['offsets'][row]), int(data['offsets'][row + 1])
                assert 0 <= target < end - start
                streams['obs.f32'].write(data['obs'][row].tobytes())
                streams['actions.f32'].write(data['actions'][start:end].tobytes())
                streams['chosen_action.u32'].write(np.array([data['chosen'][row]], dtype='<u4').tobytes())
                streams['values.f32'].write(data['values'][row].tobytes())
                streams['policy_target.u32'].write(np.array([target], dtype='<u4').tobytes())
                streams['policy_group.u8'].write(bytes([group]))
                total_actions += end - start
                streams['action_offsets.u64'].write(np.array([total_actions], dtype='<u8').tobytes())
        finally:
            for stream in streams.values():
                stream.close()
        meta['splits'][split] = {'step_count': len(plan), 'total_actions': total_actions,
                               'teacher_rows': len(expert_ids), 'query_rows': len(queries),
                               'hashes': {n: sha256(folder / n) for n in names}}
    train_seeds = {r['offline']['seed'] for r in records if r['offline']['split'] == 'train'}
    val_seeds = {r['offline']['seed'] for r in records if r['offline']['split'] == 'val'}
    assert train_seeds.isdisjoint(val_seeds)
    write_json(out / 'manifest.json', meta)
    print(json.dumps({'status': 'PASS', 'action_dim': width, 'splits': meta['splits']}, indent=2))


if __name__ == '__main__':
    config, base_dir = goal()
    labels = query_roots(config, base_dir)
    materialize(config, base_dir, labels)
