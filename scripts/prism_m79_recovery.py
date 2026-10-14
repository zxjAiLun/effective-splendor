"""Restricted persistent M79 recovery RPC; exact lineage and finite stop retained."""
import argparse, json, os
from pathlib import Path
import platform, sys, time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from training.prism_portable.common import read,write,digest,lock
from scripts.prism_dsw_ppo_process import same_process

def status():
    execution=read(ROOT/'execution.json');budget=read(ROOT/'round-budget.json') if (ROOT/'round-budget.json').exists() else None
    p=ROOT/'pipeline/status.json';saved=read(p) if p.exists() else {}
    result=dict(saved,node=platform.node(),observed_at=time.time(),execution_sha256=digest(ROOT/'execution.json'),deadline=budget['deadline'] if budget else None)
    if (ROOT/'pipeline/completion.json').exists():result.update(state='COMPLETED',phase='RESULTS_PENDING_LOCAL_VISUAL_ARCHIVE')
    elif budget and time.time()>=budget['deadline']:result['state']='DEADLINE'
    elif saved.get('pid') and same_process(saved['pid'],saved['create_time']):
        import psutil
        argv=psutil.Process(saved['pid']).cmdline()
        if str(ROOT/'scripts/prism_m79_run.py') not in argv:raise ValueError('PID command identity mismatch')
        result['state']='RUNNING';progress=ROOT/'campaigns/a/control/live-progress.json'
        if progress.exists():result['training']=read(progress)
    else:result['state']='NO_OWNER'
    return result

def bind_replacement_node():
    from scripts.prism_m79_run import environment
    actual=environment();p=read(ROOT/'execution.json');expected=p['environment']
    if actual['node']==expected['node']:return
    if any(actual[k]!=expected[k] for k in ('python','executable','packages')):raise ValueError('replacement numeric runtime changed')
    import shutil
    from training.prism_portable.processes import directory_bytes
    if len(actual['affinity'])<8:raise ValueError('replacement cpuset capacity insufficient')
    if shutil.disk_usage(ROOT).free<max(0,40802189312-directory_bytes(ROOT))+8589934592:raise ValueError('replacement storage reservation insufficient')
    quota=Path('/sys/fs/cgroup/cpu/cpu.cfs_quota_us');period=Path('/sys/fs/cgroup/cpu/cpu.cfs_period_us')
    if not quota.exists() or int(quota.read_text())/int(period.read_text())<8:raise ValueError('replacement actual CPU quota insufficient')
    memory=Path('/sys/fs/cgroup/memory/memory.limit_in_bytes')
    if not memory.exists() or int(memory.read_text())<16*1024**3:raise ValueError('replacement memory capacity insufficient')
    from training.prism_portable.provision import provision
    import hashlib
    qualification_root=ROOT/'runtime-checks'/hashlib.sha256(actual['node'].encode()).hexdigest()[:16]
    receipt_path=qualification_root/'preflight.json'
    if receipt_path.exists():
        parity=read(receipt_path)
        if parity['status']!='PASS' or parity['boundary_inputs']!=68:raise ValueError('replacement parity receipt invalid')
    else:
        _,parity=provision(qualification_root,ROOT,ROOT/'bin/splendor',ROOT/'bin/s4_batch_metrics',ROOT/'inputs/parent.json',ROOT/'inputs/initial.json',ROOT/'inputs/fixtures.jsonl','m79-replacement-'+actual['node'])
    with lock(ROOT/'runtime-control'):
        dest=ROOT/'runtime-revisions.json';rows=read(dest) if dest.exists() else []
        if not any(r['node']==actual['node'] for r in rows):
            rows.append(dict(node=actual['node'],observed_at=time.time(),environment=actual,execution_sha256=digest(ROOT/'execution.json'),source_numeric_identity=p['numeric_source_identity'],parity_receipt_sha256=digest(receipt_path),new_games=0))
            write(dest,rows)

def ensure():
    bind_replacement_node()
    from scripts.prism_m79_run import ensure as start
    return start()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['endpoint','ensure-local','status']);args=parser.parse_args()
    try:
        method=json.loads(sys.stdin.readline())['method'] if args.mode=='endpoint' else 'ensure' if args.mode=='ensure-local' else 'status'
        if method not in ('status','ensure'):raise ValueError('restricted M79 RPC method')
        print(json.dumps(globals()[method]()),flush=True)
    except Exception as error:
        print(json.dumps(dict(state='RECOVERY_BLOCKED',error_type=type(error).__name__,error=str(error),observed_at=time.time())),flush=True);sys.exit(1)
