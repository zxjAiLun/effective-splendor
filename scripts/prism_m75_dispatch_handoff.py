"""Separately bound DSW r3 handoff adapter; leaves running baseline policy intact."""
import importlib.util,json,os,subprocess,sys,time
from pathlib import Path
import psutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));REV=ROOT/'dual-node-r3'
from training.prism_portable.common import read,write,digest

def bound_worker(p,b):
    if p['train_worker_pid']!=p['train_relay_pid']:raise ValueError('unexpected original selector binding')
    if b['relay_pid']!=p['train_relay_pid'] or b['r2_parent_pid']!=p['r2_parent_pid'] or b['worker_pid']==b['relay_pid']:raise ValueError('handoff binding drift')
    return dict(p,train_worker_pid=b['worker_pid'],train_worker_created=b['worker_created'])

def controller():
    binding=read(REV/'handoff-policy.json')
    if digest(__file__)!=binding['adapter_sha256'] or digest(REV/'policy.json')!=binding['parent_policy_sha256']:raise ValueError('handoff adapter source/policy drift')
    spec=importlib.util.spec_from_file_location('dual_r3',REV/'dual_node.py');d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
    native=d.policy
    d.policy=lambda:bound_worker(native(),binding)
    return d,binding

def start():
    d,b=controller();p=d.policy()
    d.handoff_contract(p,psutil.Process(p['r2_parent_pid']),psutil.Process(p['train_relay_pid']),psutil.Process(p['train_worker_pid']))
    with (REV/'coordinator-once.lock').open('x'):pass
    with (REV/'coordinator-supervisor.log').open('xb') as log:
        process=subprocess.Popen([p['training_python'],'-B',str(Path(__file__).resolve()),'coordinator'],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    receipt=dict(state='STARTED',node='dsw',role='coordinator',pid=process.pid,create_time=psutil.Process(process.pid).create_time(),policy_sha256=digest(REV/'policy.json'),handoff_policy_sha256=digest(REV/'handoff-policy.json'),deadline=p['deadline'],observed_at=time.time())
    write(REV/'coordinator-launch.json',receipt);return receipt

if __name__=='__main__':
    os.sched_setaffinity(0,range(4))
    try:
        d,b=controller();print(json.dumps(start() if sys.argv[-1]=='start' else d.coordinator()))
    except BaseException as error:
        write(REV/'handoff-adapter-failure.json',dict(error=repr(error),observed_at=time.time()));raise
