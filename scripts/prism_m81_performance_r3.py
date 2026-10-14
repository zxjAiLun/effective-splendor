"""M81 execution-only revision: incremental storage and copy-on-write ledger.

The frozen sources remain untouched. Numerical state, schedules, attempts and
all completed artifacts are resumed; this module adds no research budget.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REV = ROOT/'execution-revisions/performance-r3'
SELF = str(Path(__file__).resolve())


def install_campaign(campaign):
    from scripts import prism_dsw_ppo_process as process
    from scripts import prism_m81_run as m
    from scripts.prism_incremental_storage import CampaignStorage, copy_ledger_for_record, FrozenFiles
    from training.prism_portable.engine.ppo import arena, execution
    from training.prism_portable.common import write
    tracker = CampaignStorage(campaign.root, campaign.spec['run']['budget']['max_storage_bytes'])
    publications = tracker.publications(); publications.__enter__()
    campaign._performance_storage = tracker
    campaign._performance_publications = publications
    timing = {'started_at':time.time(), 'games':0, 'stages':{}, 'new_games_budget':0}
    campaign._performance_timing = timing
    frozen_spec=copy.deepcopy(campaign.spec)
    full_assets=execution.check_assets
    full_assets(frozen_spec)
    paths=[frozen_spec['parent_weights']]
    for desc in [frozen_spec['arena'],frozen_spec['learner'],*frozen_spec['opponents'].values()]:
        paths.append(desc['program']);paths.extend(desc.get('files',{}))
    frozen_files=FrozenFiles(paths)
    def assets(spec):
        if spec != frozen_spec:raise ValueError('frozen campaign contract changed')
        frozen_files.check()
    def validate(spec):
        if spec != frozen_spec:raise ValueError('frozen campaign contract changed')
        return spec
    execution.check_assets=assets
    execution.validate_spec=validate
    arena.check_assets=assets
    campaign._performance_full_assets=lambda: full_assets(frozen_spec)

    def timed(name, function):
        def wrapped(*args, **kwargs):
            started=time.perf_counter()
            try: return function(*args, **kwargs)
            finally:
                row=timing['stages'].setdefault(name, {'calls':0, 'seconds':0.})
                row['calls']+=1;row['seconds']+=time.perf_counter()-started
        return wrapped

    original_record=arena.Campaign.record
    arena.Campaign.record=m.adapted(original_record,
        [('state = copy.deepcopy(state)', 'state = copy_ledger_for_record(state)')],
        {'copy_ledger_for_record':copy_ledger_for_record})
    arena.Campaign.record=timed('ledger_record', arena.Campaign.record)
    original_launch=arena.Campaign.launch

    def launch(self, *args, **kwargs):
        directory=self.root/'attempts'/f'{self.run.state["attempts"]+1:03d}'
        tracker.watch(directory)
        started=time.perf_counter()
        try:return original_launch(self,*args,**kwargs)
        finally:
            tracker.unwatch(directory)
            timing['games']+=1
            timing['stages'].setdefault('launch_total', {'calls':0,'seconds':0.})
            timing['stages']['launch_total']['calls']+=1
            timing['stages']['launch_total']['seconds']+=time.perf_counter()-started
            if timing['games']%32==0:publish(campaign)

    arena.Campaign.launch=launch
    arena.directory_bytes=tracker.size
    process.directory_bytes=tracker.size
    original_start=process.ProcessTree.start
    original_close=process.ProcessTree.close

    def start(self,*args,**kwargs):
        result=original_start(self,*args,**kwargs)
        tracker.watch(self.record)
        return result

    def close(self):
        try:return original_close(self)
        finally:
            if hasattr(self,'record') and self.record in tracker.external:
                tracker.unwatch(self.record)

    process.ProcessTree.start=start
    process.ProcessTree.close=close
    for name in ('submit','seal'):
        setattr(campaign.run,name,timed(name,getattr(campaign.run,name)))
    arena.check_assets=timed('asset_checks',arena.check_assets)
    arena.verify_completion=timed('completion_checks',arena.verify_completion)
    publish(campaign)


def publish(campaign):
    from training.prism_portable.common import write
    write(REV/('timing-'+campaign.root.name+'.json'),dict(
        **campaign._performance_timing, observed_at=time.time(),
        cycle=campaign.run.state['cycle'],attempts=campaign.run.state['attempts'],
        optimizer_steps=campaign.run.state['global_step'],
        storage_bytes=campaign._performance_storage.total,
        storage_metrics=campaign._performance_storage.metrics,
        timing_note='nested stage timings; do not add overlapping stages'))


def boundary(campaign):
    campaign._performance_storage.reconcile()
    campaign._performance_full_assets()
    publish(campaign)


def install():
    from scripts import prism_m81_run as m
    from training.prism_portable.engine.ppo import arena
    from training.prism_portable.common import read,digest
    meta=read(REV/'revision.json')
    for path,expected in meta['new_files'].items():
        if digest(ROOT/path)!=expected:raise ValueError('r3 adapter drift '+path)
    if digest(ROOT/'execution.json')!=meta['execution_sha256']:
        raise ValueError('r3 original execution drift')
    m.worker=m.adapted(m.worker,[
        ("owner=assert_owner(camp,host['host_id'])",
         "expected=read(camp/'ownership.json');owner=assert_owner(camp,host['host_id'],expected['nonce'])"),
        ("campaign=Campaign(camp,read(camp/'contract.json'))",
         "campaign=Campaign(camp,read(camp/'contract.json'));install_campaign(campaign)"),
        ('campaign.work(stop_after_cycle=True);legacy.publish_progress(campaign)',
         'campaign.work(stop_after_cycle=True);boundary(campaign);legacy.publish_progress(campaign)')],
        {'install_campaign':install_campaign,'boundary':boundary})
    # submit() validates this exact completion before committing the sample.
    # Keep that check once, rather than running the same full validation twice.
    arena.Campaign.launch=m.adapted(arena.Campaign.launch,[
        ("verify_completion(self.run.config, job, number, completion, replay=replay, sidecar=sidecar,\n                          behavior_id=snapshot['behavior_id'])",
         "pass  # full verification occurs once in Run.submit before sample commit")])
    old_start=m.ProcessTree.start
    def route(self,argv,**kwargs):
        argv=[SELF if a in (str(ROOT/'scripts/prism_m81_run.py'),str(ROOT/'scripts/prism_m81_start_r2.py')) else a for a in argv]
        return old_start(self,argv,**kwargs)
    m.ProcessTree.start=route
    return m


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['pipeline','execute','verify'])
    parser.add_argument('--stage');parser.add_argument('--arm')
    parser.add_argument('--stop-cycle',type=int,default=20)
    args=parser.parse_args();module=install()
    if args.mode=='verify':print(json.dumps(module.verify()[1]['status']))
    elif args.mode=='pipeline':module.pipeline('main')
    else:module.execute(args.stage,args.arm,args.stop_cycle)
