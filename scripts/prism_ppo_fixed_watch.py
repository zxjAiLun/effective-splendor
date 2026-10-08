"""Bounded fixed-only development checkpoint watcher (stdlib, no pool/DB).

Reuse immutable parent result; wait only for prescheduled c1/c4/c8 assets.
No mixed games, Elo writes, training imports or production enrollment.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import time
if __package__:
    from .prism_ppo_cloud2_controller import digest, import_file, load, paired_delta, save
else:
    from prism_ppo_cloud2_controller import digest, import_file, load, paired_delta, save

FORMAT = "prism-ppo-fixed-watch-v1"


def run(plan_path, *, clock=time.time, sleep=time.sleep, evaluator=None):
    plan = load(plan_path)
    if plan.get('format') != FORMAT or type(plan.get('wait_seconds')) is not int or not 1 <= plan['wait_seconds'] <= 43200:
        raise ValueError('bounded fixed watcher plan required')
    if [(r['label'], r['cycle']) for r in plan['checkpoints']] != [('c1', 1), ('c4', 4), ('c8', 8)]:
        raise ValueError('fixed checkpoint schedule')
    root = Path(plan['root'])
    root.mkdir(parents=True, exist_ok=True)
    state_path = root / 'fixed-watch-state.json'
    if evaluator is None:
        evaluator = import_file('m54_fixed_only_evaluator', plan['eval_script'])
    state = load(state_path) if state_path.exists() else {
        'format': FORMAT, 'plan_sha256': digest(plan), 'deadline': clock() + plan['wait_seconds'],
        'started_at': clock(), 'rounds': {}, 'complete': False}
    if state['plan_sha256'] != digest(plan):
        raise ValueError('fixed watcher plan drift')
    if state['complete']:
        return state
    state.update(pid=os.getpid(), error=None)
    def check_deadline():
        if clock() >= state['deadline']:
            raise TimeoutError('fixed development watcher deadline')
    save(state_path, state)
    parent = None
    try:
        for label, checkpoint in [('parent', None)] + [(r['label'], r) for r in plan['checkpoints']]:
            state['waiting_for'] = label
            save(state_path, state)
            if checkpoint is None:
                descriptor, asset = plan['parent'], None
            else:
                ready = Path(checkpoint['weights_ready'])
                while not ready.is_file():
                    check_deadline(); sleep(10)
                asset = load(ready)
                if set(asset) != {'path', 'sha256', 'cycle', 'training_commit'} or asset['cycle'] != checkpoint['cycle']:
                    raise ValueError('checkpoint ready metadata mismatch')
                if evaluator.sha256_file(asset['path']) != asset['sha256']:
                    raise ValueError('checkpoint weight drift')
                descriptor = {'program': plan['engine']['program'], 'sha256': plan['engine']['sha256'],
                    'args': ['agent-prism-sample', '--weights', asset['path'], '--seed', str(plan['action_seed'])],
                    'files': [{'path': asset['path'], 'sha256': asset['sha256']}]}
            check_deadline()
            config = {key: plan[key] for key in ('engine', 'catalog_fingerprint', 'action_seed', 'seeds', 'timeouts', 'opponents')}
            config.update(format='prism-ppo-fixed-eval-v1', candidates={label: descriptor})
            config_path = root / (label + '-fixed.config.json')
            if config_path.exists() and load(config_path) != config:
                raise ValueError('fixed config drift')
            save(config_path, config)
            evaluator.check_assets(evaluator.validate_config(config, config_path))
            result = evaluator.run_eval(config_path, root / (label + '-fixed'))
            check_deadline()
            row = state['rounds'].setdefault(label, {})
            if asset is not None:
                if 'checkpoint' in row and row['checkpoint'] != asset:
                    raise ValueError('immutable checkpoint drift')
                row['checkpoint'] = asset
            row.update(complete=True, result_sha256=evaluator.sha256_file(root / (label + '-fixed' ) / 'result.json'))
            if label == 'parent':
                parent = result
            else:
                delta = paired_delta(evaluator, plan, parent, result, label)
                delta['reused_parent_result'] = str(root / 'parent-fixed' / 'result.json')
                path = root / (label + '-paired-delta.json')
                if path.exists() and load(path) != delta:
                    raise ValueError('paired delta drift')
                save(path, delta)
            save(state_path, state)
        state.update(complete=True, waiting_for=None, finished_at=clock())
        save(state_path, state)
    except BaseException as exc:
        state.update(complete=False, error=type(exc).__name__ + ': ' + str(exc))
        save(state_path, state)
        raise
    return state


@contextmanager
def watcher_lock(root):
    import fcntl
    Path(root).mkdir(parents=True, exist_ok=True)
    with (Path(root) / 'fixed-watch.lock').open('a+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', required=True)
    args = parser.parse_args()
    with watcher_lock(load(args.plan)['root']):
        run(args.plan)


if __name__ == '__main__':
    main()
