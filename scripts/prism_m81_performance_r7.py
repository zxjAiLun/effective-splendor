"""M81 r7: compact cycle summaries and incremental launch queries.

Opt-in source-pinned entry. It does not launch anything on import, change the
scientific contract, or repair/retry the independently failed report stage.
"""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REV = ROOT / 'execution-revisions/performance-r7'
SELF = str(Path(__file__).resolve())


def setup(campaign):
    from scripts import prism_m81_performance_r5 as previous
    from scripts import prism_m79_run as legacy
    from scripts.prism_cycle_fast import install_cycle_cache, install_attempt_index
    from training.prism_portable.engine.ppo import arena
    previous.setup(campaign)
    install_cycle_cache(campaign, legacy)
    install_attempt_index(campaign, legacy, arena)


def install():
    from scripts import prism_m81_performance_r5 as previous
    from scripts import prism_m81_performance_r3 as base
    from training.prism_portable.common import read, digest
    meta = read(REV / 'revision.json')
    if digest(ROOT / 'execution.json') != meta['execution_sha256']:
        raise ValueError('r7 execution drift')
    for name, expected in meta['new_files'].items():
        if digest(ROOT / name) != expected:
            raise ValueError('r7 source drift ' + name)
    module = previous.install()
    base.REV = REV
    module.worker.__globals__['install_campaign'] = setup
    original_boundary = module.worker.__globals__['boundary']

    def boundary(campaign):
        campaign._attempt_index.reconcile()
        campaign._performance_timing['cycle_cache'] = dict(campaign._cycle_cache.metrics)
        campaign._performance_timing['attempt_index_rebuilds'] = campaign._attempt_index.rebuilds
        original_boundary(campaign)

    module.worker.__globals__['boundary'] = boundary
    original = module.ProcessTree.start

    def route(self, argv, **kwargs):
        entries = {str(ROOT / 'scripts' / name) for name in (
            'prism_m81_run.py', 'prism_m81_start_r2.py',
            'prism_m81_performance_r3.py', 'prism_m81_performance_r4.py',
            'prism_m81_performance_r5.py')}
        return original(self, [SELF if value in entries else value for value in argv], **kwargs)

    module.ProcessTree.start = route
    return module


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['pipeline', 'execute', 'verify'])
    parser.add_argument('--stage'); parser.add_argument('--arm')
    parser.add_argument('--stop-cycle', type=int, default=20)
    args = parser.parse_args()
    module = install()
    if args.mode == 'pipeline':
        module.pipeline('main')
    elif args.mode == 'execute':
        module.execute(args.stage, args.arm, args.stop_cycle)
    else:
        print(module.verify()[1]['status'])
