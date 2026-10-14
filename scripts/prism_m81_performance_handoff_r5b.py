"""One finite safe-boundary transfer from the admitted M81 r4 B worker to r5."""
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
REV=ROOT/'execution-revisions/performance-r5'


def transfer():
    import psutil
    import torch
    from scripts import prism_m81_run as old
    from training.prism_portable.common import read,write,digest
    from training.prism_portable.protocol import state_fingerprints
    from scripts.prism_m67_storage import install as install_compressed_store
    from training.prism_portable.engine.ppo.store import CommitStore
    install_compressed_store()
    old.verify()
    assert read(REV/'qualification.json')['status']=='PASS'
    with (REV/'handoff-attempt-2.lock').open('x'):
        pass
    admission=read(REV/'handoff-admission.json')
    if digest(__file__)!=admission['transfer_sha256']:raise ValueError('transfer source drift')
    if digest(REV/'revision.json')!=admission['revision_sha256'] or digest(REV/'qualification.json')!=admission['qualification_sha256']:
        raise ValueError('qualified revision changed')
    expected={role:tuple(value) for role,value in admission['processes'].items()}
    owned={}
    for role,(pid,created) in expected.items():
        proc=psutil.Process(pid)
        if abs(proc.create_time()-created)>.01 or not any(str(ROOT) in s for s in proc.cmdline()):
            raise ValueError('old process identity drift '+role)
        owned[role]=proc
    status=read(ROOT/'pipeline/status.json')
    if status['phase']!='train-B' or status['pid']!=expected['coordinator'][0] or status['relay_pid']!=expected['relay'][0]:
        raise ValueError('not the admitted B stage')
    campaign=ROOT/'campaigns/B'
    def committed(directory):
        pointer=read(directory/'HEAD.json')
        record_bytes=(directory/'commits'/(pointer['commit']+'.json')).read_bytes()
        if hashlib.sha256(record_bytes).hexdigest()!=pointer['commit']:raise ValueError('commit hash')
        record=json.loads(record_bytes)
        return CommitStore(directory,pointer['identity']).get_payload(record['payload'])
    worker=owned['worker'];transferred=False;frozen=False
    try:
        expires=time.monotonic()+300
        while time.monotonic()<expires:
            worker.send_signal(signal.SIGSTOP);frozen=True
            stop_deadline=time.monotonic()+1
            while worker.status()!=psutil.STATUS_STOPPED and time.monotonic()<stop_deadline:
                time.sleep(.001)
            if worker.status()!=psutil.STATUS_STOPPED:raise RuntimeError('worker stop not confirmed')
            # Do not interrupt an actual game or its inference service.
            children=[p for p in worker.children(recursive=True)
                      if p.is_running() and p.status()!=psutil.STATUS_ZOMBIE]
            if not children:
                state=committed(campaign/'run');ledger=committed(campaign/'launch-ledger')
                rows=ledger['attempts'].values()
                safe=(state['phase']=='COLLECTING' and not state['paused']
                      and len(ledger['attempts'])==state['attempts']
                      and all(row['status'] in ('COMPLETE','TRUNCATED','INFRA_ABORT') for row in rows)
                      and all(row['status'] in ('COMPLETE','TRUNCATED') for row in state['jobs'].values()))
                if safe:
                    snapshot=dict(observed_at=time.time(),cycle=state['cycle'],attempts=state['attempts'],
                                  global_step=state['global_step'],cursor=state['cursor'],
                                  fingerprints=state_fingerprints(state),
                                  run_head_sha256=digest(campaign/'run/HEAD.json'),
                                  ledger_head_sha256=digest(campaign/'launch-ledger/HEAD.json'),
                                  old_processes=expected,new_games_on_transfer=0)
                    write(REV/'handoff-boundary.json',snapshot)
                    # Relay records its complete CPU use and terminates only its owned child.
                    owned['relay'].send_signal(signal.SIGTERM);transferred=True
                    break
            worker.send_signal(signal.SIGCONT);frozen=False
            time.sleep(2.)
        if not transferred:raise RuntimeError('no safe game boundary within 300 seconds; old worker left running')
    finally:
        if frozen and not transferred:
            worker.send_signal(signal.SIGCONT)
    deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        if all(not p.is_running() or p.status()==psutil.STATUS_ZOMBIE for p in owned.values()):break
        time.sleep(.3)
    else:raise RuntimeError('old process exit not confirmed; do not launch another writer')
    after=committed(campaign/'run')
    if state_fingerprints(after)!=snapshot['fingerprints'] or digest(campaign/'run/HEAD.json')!=snapshot['run_head_sha256'] or digest(campaign/'launch-ledger/HEAD.json')!=snapshot['ledger_head_sha256']:
        raise ValueError('committed state changed during handoff')
    for n in ('status.json','resources.json','train-B.completion.json'):
        write(REV/('retained-'+n),read(ROOT/'pipeline'/n))
    rows=read(ROOT/'pipeline/resources.json')
    if not any(row.get('resources',{}).get('pid')==expected['relay'][0] for row in rows):raise ValueError('current relay CPU charge missing')
    if not any(x['category']=='training-B' for x in rows):raise ValueError('old CPU charge missing')
    qualification=read(REV/'qualification.json');profiles=[read(REV/name) for name in ('profile-before.json','profile-seal-store.json')]
    rows.append(dict(category='control',label='performance-r5-qualification',
                     cpu_seconds=qualification['cpu_seconds']+sum(p['cpu_seconds'] for p in profiles)+300.,
                     accounting_scope='measured qualification/profiles plus 300 CPU-second conservative allowance including the first no-boundary transfer window for deployment/preflight/transfer'))
    write(ROOT/'pipeline/resources.json',rows)
    with (REV/'supervisor.log').open('xb') as log:
        child=subprocess.Popen([old.PY,'-B',str(ROOT/'scripts/prism_m81_performance_r5.py'),'pipeline'],
                               cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    launch=dict(pid=child.pid,create_time=psutil.Process(child.pid).create_time(),
                observed_at=time.time(),boundary=snapshot,execution_revision='performance-r5',
                retained_cpu_charge=True,original_scientific_contract_unchanged=True)
    write(REV/'launch.json',launch)
    print(json.dumps(launch),flush=True)


if __name__=='__main__':transfer()
