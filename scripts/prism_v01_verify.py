"""Reproducible, read-only Prism v0.1 evidence checks (no training or match retries)."""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.prism_v01_round import CONFIG, invoke, save, sha

ART = ROOT / 'local-artifacts/prism/v01'
KINDS = ['take_tokens', 'buy_market', 'buy_reserved', 'reserve_market', 'reserve_deck', 'choose_noble', 'pass']


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def audit_dataset():
    from training.prism.data import PrismDataset
    import numpy as np
    config = read(CONFIG)
    source_path = ART/'collect/manifest.json'
    source = read(source_path)
    manifest = read(ART/'dataset/manifest.json')
    assert len(source['rows']) == 4000
    assert [r['seed'] for r in source['rows']] == list(range(9400000, 9404000))
    assert manifest['source_manifest_sha256'] == sha(source_path)
    assert sha(ROOT/config['teacher']['program']) == sha(ROOT/config['teacher']['origin']) == config['teacher']['sha256']
    identities = {'config_sha256': sha(CONFIG), 'teacher_sha256': config['teacher']['sha256'], 'engine_sha256': config['teacher']['sha256']}
    dataset_sources = {r['seed']: r for r in manifest['sources']}
    count = Counter()
    for row in source['rows']:
        assert row['candidate_seat'] == row['rotation'] == 0 and row['identity'] == identities
        path = ART/'collect'/row['replay_path']
        for name, digest in row['hashes'].items():
            assert sha(path.parent/name) == digest, path.parent/name
        cfg = read(path.parent/'match-config.json')
        assert cfg['seed'] == row['seed'] and len(cfg['agents']) == 2
        for a in cfg['agents']:
            assert Path(a['program']).resolve() == (ROOT/config['teacher']['program']).resolve()
            assert a['args'] == config['teacher']['args']
        report = read(path.parent/'arena-report.json')
        replay = read(path)
        assert report['outcome']['status'] == 'completed'
        assert replay['result'] == report['outcome']['result'] == row['result']
        assert len(replay['steps']) == row['plies'] == report['outcome']['completed_plies']
        for name in ['run-log.json', 'verify-log.json']:
            assert read(path.parent/name)['exit_code'] == 0
        ds = dataset_sources[row['seed']]
        assert ds['sha256'] == sha(path) and ds['steps'] == len(replay['steps'])
        assert Path(ds['path']).resolve() == path.resolve()
        assert ds['split'] == ('val' if row['seed'] % 5 == 0 else 'train')
        count['verified_games'] += 1
    for split, games in [('train', 3200), ('val', 800)]:
        with PrismDataset(ART/'dataset', split) as data:
            assert data.meta['games'] == games
            rows = iter((ART/f'dataset/{split}/rows.jsonl').open(encoding='utf-8'))
            index = 0
            labels = Counter()
            for src in manifest['sources']:
                if src['split'] != split:
                    continue
                replay = read(src['path'])
                for step in replay['steps']:
                    row = json.loads(next(rows))
                    assert (row['seed'], row['ply'], row['actor'], row['chosen_action']) == (src['seed'], step['ply'], step['actor'], step['action'])
                    winners = replay['result']['winners']
                    expected = (1.0 if len(winners) == 1 else 0.5) if row['actor'] in winners else 0.0
                    assert data.outcomes[index] == expected
                    lo, hi = int(data.action_offsets[index]), int(data.action_offsets[index+1])
                    chosen = int(data.chosen[index]); assert 0 <= chosen < hi-lo
                    kind = step['action']['type']
                    assert data.actions[lo+chosen, KINDS.index(kind)] == 1.0
                    labels[str(expected)] += 1
                    index += 1
            assert next(rows, None) is None and index == len(data)
            count[f'{split}_states'] = index
            count[f'{split}_actions'] = int(data.meta['actions'])
            count[f'{split}_entities'] = int(data.meta['entities'])
            save(ART/f'provenance/{split}-data-audit.json', dict(status='PASS', labels=labels, states=index,
                 dataset_sha256=data.dataset_sha256, manifest_sha256=data.manifest_sha256))
    parity = [json.loads(x) for x in (ART/'dataset/parity.jsonl').read_text().splitlines()]
    assert len(parity) == 32 and len({p['seed'] for p in parity}) == 32
    assert all(p['seed'] % 5 == 0 for p in parity)
    save(ART/'provenance/dataset-audit.json', dict(status='PASS', **count, real_parity_roots=32,
         collection_manifest_sha256=sha(source_path), dataset_manifest_sha256=sha(ART/'dataset/manifest.json')))
    print('dataset audit PASS', dict(count), flush=True)


def parity(weights, label):
    import numpy as np
    import torch
    from training.prism.export import load_weights
    from training.prism.model import predict
    torch.set_num_threads(2)
    catalog = read(ART/'dataset/manifest.json')['catalog_fingerprint']
    model = load_weights(weights, expected_catalog_fingerprint=catalog)
    results = []
    kinds = set()
    for source, category in [(ART/'dataset/parity.jsonl', 'real'), (ART/'provenance/boundary-fixtures.jsonl', 'boundary')]:
        output = ART/f'provenance/{label}-{category}-rust.jsonl'
        invoke([ART/'bin/splendor-prism.exe', 'prism-predict', '--weights', weights, '--input', source, '--output', output],
               ART/f'provenance/{label}-{category}-parity-command.json')
        cases = [json.loads(line) for line in source.read_text().splitlines()]
        actual = [json.loads(line) for line in output.read_text().splitlines()]
        assert len(cases) == len(actual)
        max_logit = max_value = 0.0
        actions = 0
        for case, rust in zip(cases, actual):
            inp = case['input']; py = predict(model, inp)
            np.testing.assert_allclose(rust['logits'], py['logits'], atol=1e-4, rtol=1e-4)
            np.testing.assert_allclose(rust['value'], py['value'], atol=1e-4, rtol=1e-4)
            max_logit = max(max_logit, float(np.max(np.abs(np.asarray(rust['logits'])-py['logits']))))
            max_value = max(max_value, abs(rust['value']-py['value']))
            kinds.update(int(np.argmax(a[:7])) for a in inp['actions'])
            actions += len(inp['actions'])
        results.append(dict(category=category, states=len(cases), actions=actions, max_abs_logit_error=max_logit,
                            max_abs_value_error=max_value, input_sha256=sha(source), rust_output_sha256=sha(output)))
    assert kinds == set(range(7))
    result = dict(status='PASS', weights_sha256=sha(weights), atol=1e-4, rtol=1e-4,
                  covered_action_kinds=KINDS, cases=results)
    save(ART/f'provenance/{label}-parity.json', result)
    print(label, 'parity PASS', results, flush=True)
    return result


def preflight():
    import torch
    from training.prism.model import PrismModel
    from training.prism.export import export_weights
    from training.prism.data import collate_states
    from training.prism.train import configure_runtime, validate_config, loss_terms
    audit_dataset()
    config = read(CONFIG)
    device, runtime = configure_runtime(validate_config(config))
    torch.manual_seed(config['training']['seed'])
    model = PrismModel().float()
    catalog = read(ART/'dataset/manifest.json')['catalog_fingerprint']
    weights = ART/'provenance/preflight-init-weights.json'
    export_weights(model, weights, catalog)
    parity(weights, 'preflight')
    roots = [json.loads(line)['input'] for line in (ART/'dataset/parity.jsonl').read_text().splitlines()]
    for i, r in enumerate(roots):
        r['chosen'] = 0
        r['outcome'] = [0.0, 0.5, 1.0][i % 3]
    batch = {k: v.to(device) for k, v in collate_states(roots).items()}
    model.to(device)
    torch.cuda.reset_peak_memory_stats()
    start = time.perf_counter()
    logits, values = model.forward_batch(batch)
    ce, bce = loss_terms(logits, values, batch['chosen'], batch['outcomes'])
    (ce.mean()+0.5*bce.mean()).backward()
    assert model.encoder.weight.grad is not None and torch.isfinite(model.encoder.weight.grad).all()
    assert model.encoder.weight.grad.abs().sum() > 0
    torch.cuda.synchronize()
    files = [ROOT/'Cargo.toml', ROOT/'Cargo.lock', ROOT/'crates/splendor-cli/Cargo.toml', ROOT/'crates/splendor-cli/src/main.rs']
    files += list((ROOT/'crates/splendor-prism').rglob('*.rs'))
    files += list((ROOT/'crates/splendor-cli/src').glob('prism*.rs'))
    files += list((ROOT/'training/prism').rglob('*.py'))
    files += [CONFIG, ROOT/'docs/m51-prism-implementation-contract.md']
    frozen = dict(status='FROZEN_BEFORE_FORMAL_TRAINING', config_sha256=sha(CONFIG),
                  dataset_manifest_sha256=sha(ART/'dataset/manifest.json'), runtime=runtime,
                  gpu_gradient_smoke=dict(status='PASS', states=len(roots), seconds=time.perf_counter()-start,
                  peak_allocated_bytes=torch.cuda.max_memory_allocated(), optimizer_steps=0),
                  sources={str(p.relative_to(ROOT)).replace('\\','/'): sha(p) for p in files},
                  binaries={p.name: sha(p) for p in (ART/'bin').glob('*.exe')},
                  formal_candidates=1, epochs=20, no_arena_checkpoint_selection=True)
    save(ART/'provenance/pretraining-freeze.json', frozen)
    print('preflight PASS; frozen before formal training', frozen['gpu_gradient_smoke'], flush=True)


def trained():
    import torch
    from training.prism.export import load_checkpoint_model, load_weights
    from training.prism.io import tensor_identity
    from training.prism.train import select_best_epoch
    summary = read(ART/'run/training-summary.json')
    history = read(ART/'run/history.json')
    catalog = read(ART/'dataset/manifest.json')['catalog_fingerprint']
    best, ckpt = load_checkpoint_model(ART/'run/best_model.pt', expected_catalog_fingerprint=catalog)
    init, _ = load_checkpoint_model(ART/'run/init.pt', expected_catalog_fingerprint=catalog)
    exported = load_weights(ART/'run/weights.json', expected_catalog_fingerprint=catalog)
    assert summary['status'] == 'COMPLETE' and summary['completed_epochs'] == len(history) == 20
    assert summary['best_epoch'] == ckpt['epoch'] == select_best_epoch(history)
    assert tensor_identity(best.state_dict()) != tensor_identity(init.state_dict())
    assert all(torch.equal(v, exported.state_dict()[k]) for k, v in best.state_dict().items())
    assert summary['config_sha256'] == sha(CONFIG)
    for name, digest in summary['hashes'].items():
        assert sha(ART/'run'/name) == digest
    for filename, digest in read(ART/'provenance/pretraining-freeze.json')['sources'].items():
        assert sha(ROOT/filename) == digest, filename
    parity(ART/'run/weights.json', 'trained')
    save(ART/'provenance/training-audit.json', dict(status='PASS', epochs=20, selected_epoch=ckpt['epoch'],
         changed_from_init=True, checkpoint_export_exact=True, best_tensor_sha256=tensor_identity(best.state_dict()),
         init_tensor_sha256=tensor_identity(init.state_dict()), summary_sha256=sha(ART/'run/training-summary.json')))
    print('training audit PASS', ckpt['epoch'], flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('stage', choices=['dataset', 'preflight', 'trained'])
    args=parser.parse_args()
    {'dataset': audit_dataset, 'preflight': preflight, 'trained': trained}[args.stage]()
