"""M81 byte-equivalent seal and primitive-ledger serialization revision."""
import argparse
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REV = ROOT/'execution-revisions/performance-r5'
SELF = str(Path(__file__).resolve())


def setup(campaign):
    from scripts import prism_m81_performance_r4 as previous
    from scripts.prism_seal_storage_fast import SealScope, install_ledger_serializer
    previous.setup(campaign)
    install_ledger_serializer()
    from scripts import prism_m79_run as legacy
    legacy.record_batch = legacy.adapted(legacy.record_batch, [
        ("batch=run.store.get_json(s['batch'])",
         "batch=run._batch_cache[1] if run._batch_cache is not None and run._batch_cache[0]==s['batch'] else run.store.get_json(s['batch'])")])
    original = campaign.run.seal
    def seal():
        scope = SealScope()
        started = time.perf_counter()
        try:
            with scope.installed():
                return original()
        finally:
            campaign._performance_timing['last_seal_cache'] = dict(
                scope.metrics, wall_seconds=time.perf_counter()-started)
    campaign.run.seal = seal


def install():
    from scripts import prism_m81_performance_r4 as previous
    from scripts import prism_m81_performance_r3 as base
    from training.prism_portable.common import read, digest
    meta = read(REV/'revision.json')
    for name, expected in meta['new_files'].items():
        if digest(ROOT/name) != expected:
            raise ValueError('r5 source drift '+name)
    module = previous.install()
    base.REV = REV
    module.worker.__globals__['install_campaign'] = setup
    original = module.ProcessTree.start
    def route(self, argv, **kwargs):
        entries = {str(ROOT/'scripts'/name) for name in (
            'prism_m81_run.py', 'prism_m81_start_r2.py',
            'prism_m81_performance_r3.py', 'prism_m81_performance_r4.py')}
        argv = [SELF if value in entries else value for value in argv]
        return original(self, argv, **kwargs)
    module.ProcessTree.start = route
    return module


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['pipeline', 'execute', 'verify'])
    parser.add_argument('--stage'); parser.add_argument('--arm')
    parser.add_argument('--stop-cycle', type=int, default=20)
    args = parser.parse_args(); module = install()
    if args.mode == 'pipeline': module.pipeline('main')
    elif args.mode == 'execute': module.execute(args.stage, args.arm, args.stop_cycle)
    else: print(module.verify()[1]['status'])
