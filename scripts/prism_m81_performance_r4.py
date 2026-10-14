"""Bind copied Arena globals to the qualified DSW/storage adapters explicitly."""
import argparse
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
REV=ROOT/'execution-revisions/performance-r4'
SELF=str(Path(__file__).resolve())


def setup(campaign):
    from scripts import prism_m81_performance_r3 as previous
    from scripts import prism_dsw_ppo_process as process
    from training.prism_portable.engine.ppo import arena,execution
    native=inspect.getclosurevars(arena.Campaign.launch).nonlocals['native_launch']
    previous.install_campaign(campaign)
    # adapted() creates a separate globals dict. Module rebinding alone does not
    # update this cloned function: explicitly bind all execution-only overrides.
    native.__globals__['ProcessTree']=process.ProcessTree
    native.__globals__['directory_bytes']=campaign._performance_storage.size
    native.__globals__['check_assets']=arena.check_assets
    campaign._qualified_native=native


def install():
    from scripts import prism_m81_performance_r3 as previous
    from training.prism_portable.common import read,digest
    meta=read(REV/'revision.json')
    for path,expected in meta['new_files'].items():
        if digest(ROOT/path)!=expected:raise ValueError('r4 source drift '+path)
    module=previous.install()
    previous.REV=REV
    module.worker.__globals__['install_campaign']=setup
    original=module.ProcessTree.start
    def route(self,argv,**kwargs):
        argv=[SELF if a in (str(ROOT/'scripts/prism_m81_performance_r3.py'),
                           str(ROOT/'scripts/prism_m81_run.py'),
                           str(ROOT/'scripts/prism_m81_start_r2.py')) else a for a in argv]
        return original(self,argv,**kwargs)
    module.ProcessTree.start=route
    return module


def qualify():
    import resource
    from types import SimpleNamespace
    from training.prism_portable.common import read,write,digest
    from scripts import prism_dsw_ppo_process as process
    from scripts.prism_m67_storage import install as compressed
    from training.prism_portable.engine.ppo.store import CommitStore
    m=install();m.verify();m.install_resource_mode();compressed()
    c=ROOT/'campaigns/B';before=digest(c/'run/HEAD.json');head=read(c/'run/HEAD.json')
    commit=read(c/'run/commits'/(head['commit']+'.json'))
    state=CommitStore(c/'run',head['identity']).get_payload(commit['payload'])
    fake=SimpleNamespace(root=c,spec=read(c/'contract.json'),
                         run=SimpleNamespace(state=state,submit=lambda:None,seal=lambda:None))
    setup(fake)
    assert fake._qualified_native.__globals__['ProcessTree'] is process.ProcessTree
    assert fake._qualified_native.__globals__['directory_bytes'].__self__ is fake._performance_storage
    assert fake._qualified_native.__globals__['check_assets'].__name__=='wrapped'
    fake._performance_storage.reconcile()
    fake._performance_publications.__exit__(None,None,None)
    assert digest(c/'run/HEAD.json')==before
    u=resource.getrusage(resource.RUSAGE_SELF)
    value=dict(status='PASS',new_games=0,source_routing='DSW adapter and incremental guard bound to actual cloned launcher',
               heads_unchanged=True,cpu_seconds=u.ru_utime+u.ru_stime,observed_at=time.time())
    write(REV/'qualification.json',value);print(json.dumps(value))


def recover_and_start():
    import psutil
    from training.prism_portable.common import read,write,digest
    from training.prism_portable.protocol import state_fingerprints
    from training.prism_portable.engine.ppo.arena import Campaign
    m=install();m.verify();m.install_resource_mode()
    if read(REV/'qualification.json')['status']!='PASS':raise ValueError('qualification missing')
    for proc in psutil.process_iter(['pid','cmdline']):
        if proc.pid!=os.getpid() and any(str(ROOT) in s for s in proc.info['cmdline'] or []):
            raise ValueError('owned worker still active')
    with (REV/'start-once.lock').open('x'):pass
    c=Campaign(ROOT/'campaigns/B',read(ROOT/'campaigns/B/contract.json'))
    state=c.run.state;_,ledger=c._load();prior=read(ROOT/'execution-revisions/performance-r3/handoff-boundary.json')
    fingerprints=state_fingerprints(state)
    for k in ('model','optimizer','rng'):
        if fingerprints[k]!=prior['fingerprints'][k]:raise ValueError('scientific state changed '+k)
    if state['attempts']!=1511 or state['global_step']!=276 or state['phase']!='COLLECTING':raise ValueError('unexpected boundary')
    row=ledger['attempts']['1511'];job=row['job'];p=c.root/'attempts/1511'
    if row['status']!='RUNNING' or not ledger['failed'] or not state['paused']:raise ValueError('unexpected retained failure')
    if any((p/n).exists() for n in ('report.json','replay.json','sidecar.jsonl','completion.json','prefix.json')):raise ValueError('unexpected game evidence')
    tail=(ROOT/'pipeline/train-B.log').read_text()[-6000:]
    if 'systemd-run' not in tail or 'CalledProcessError' not in tail:raise ValueError('failure classification mismatch')
    write(REV/'before-recovery.json',dict(run_head_sha256=digest(c.root/'run/HEAD.json'),
                                       ledger_head_sha256=digest(c.root/'launch-ledger/HEAD.json'),
                                       fingerprints=fingerprints,failed_attempt=row,
                                       evidence='systemd launcher failed before Rust game; no outcome/sidecar'))
    # Preserve attempt1511, reserve its full unknown-work allowance, and consume
    # the existing one infrastructure retry for this exact scheduled job.
    c.recover_running(job,{})
    with c.ledger.lock():
        parent,retained=c._load()
        import copy
        retained=copy.deepcopy(retained);retained['failed']=False
        retained['recoveries'].append(dict(event='authorized_r4_execution_adapter_repair',attempt=1511))
        c._ledger_cache=(c.ledger.commit(retained,expected_parent=parent),retained)
    c.run.pause(False)
    after=state_fingerprints(c.run.state)
    if any(after[k]!=fingerprints[k] for k in ('model','optimizer','rng')):raise ValueError('repair changed learning state')
    for name in ('status.json','resources.json','train-B.completion.json'):
        write(REV/('retained-'+name),read(ROOT/'pipeline'/name))
    rows=read(ROOT/'pipeline/resources.json')
    rows.append(dict(category='control',label='r4-adapter-recovery',cpu_seconds=read(REV/'qualification.json')['cpu_seconds']+100.,
                     accounting_scope='qualification measured; 100 CPU-second allowance for recovery'))
    write(ROOT/'pipeline/resources.json',rows)
    write(REV/'recovery.json',dict(status='PASS',new_games=0,attempts_preserved=1511,
                                  terminal_games_preserved=1510,infra_attempts_charged=1,
                                  scientific_fingerprints_unchanged=True,observed_at=time.time()))
    with (REV/'supervisor.log').open('xb') as log:
        child=subprocess.Popen([m.PY,'-B',SELF,'pipeline'],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    receipt=dict(pid=child.pid,create_time=psutil.Process(child.pid).create_time(),observed_at=time.time(),revision='performance-r4')
    write(REV/'launch.json',receipt);print(json.dumps(receipt))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode');parser.add_argument('--stage');parser.add_argument('--arm');parser.add_argument('--stop-cycle',type=int,default=20);a=parser.parse_args()
    if a.mode=='qualify':qualify()
    elif a.mode=='recover':recover_and_start()
    else:
        m=install()
        if a.mode=='pipeline':m.pipeline('main')
        elif a.mode=='execute':m.execute(a.stage,a.arm,a.stop_cycle)
        else:raise ValueError('unknown mode')
