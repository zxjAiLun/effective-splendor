"""Resume r22 with serial admission and separately retained infrastructure CPU charges.
Original attempts and measured CPU are retained; serial admission avoids lock races.
"""
import argparse,copy,json,os,platform,subprocess,sys,time,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from training.prism_portable.common import read,write,digest,lock
from scripts import prism_m79_run as main,prism_m79_dual_dispatch as dual,prism_m79_evaluate as e
OUT=ROOT/'execution-revisions/aux-finish-r22'

def verify():
    d=read(OUT/'dispatch.json')
    repair=read(OUT/'r24-repair.json')
    if digest(__file__)!=repair['adapter_sha256'] or digest(ROOT/'execution.json')!=d['execution_sha256'] or d['adapter_sha256']!=repair['r22_adapter_sha256']:
        raise ValueError('aux completion binding drift')
    dual._verify_aux_sources(ROOT,read(ROOT/'execution.json'))
    dual._compatible_eval_runtime(ROOT,read(ROOT/'execution.json'))
    if len(d['labels'])!=8 or d['remaining_games']!=440 or d['cpu_reservation']!=4000 or len(d['retry_keys'])!=8:
        raise ValueError('fixed remaining allocation drift')
    return d

def install():
    d=verify()
    # Parent relay charges finite CPU/RSS and original game limits remain intact.
    e.bounds=lambda:float('inf')
    e.b.launch=main.adapted(e.b.launch,[
        ('wall = min(validated["config"]["timeouts"]["game_wall_seconds"],\n               policy["deadline_unix"] - time.time())','wall = validated["config"]["timeouts"]["game_wall_seconds"]'),
        ('require(wall > 0 and remaining_cpu > 0, "resource budget exhausted")','require(wall > 0 and remaining_cpu > 0, "resource budget exhausted"); admitted_at=time.monotonic()'),
        ('remaining_wall = min(wall, max(0., policy["deadline_unix"] - time.time()))','remaining_wall = max(0.,wall-(time.monotonic()-admitted_at))')])
    def reserved_retry(key):
        if key not in d['retry_keys']:raise ValueError('outside eight reserved infrastructure attempts')
        with lock(OUT/'retry-control'):
            p=OUT/'retries.json';rows=read(p) if p.exists() else []
            if key in rows:raise ValueError('per-job infrastructure retry exhausted')
            rows.append(key);write(p,rows)
    e.global_retry=reserved_retry
    return d

def preflight():
    d=install();counts=[]
    for label in d['labels']:
        p=ROOT/'evaluation'/label
        e.b.load_bound(p)
        if digest(p/'ledger.json')!=read(OUT/'r24-repair.json')['post_ledger_sha256'][label]:raise ValueError('aux ledger advanced before allocation')
        old=read(p/'ledger.json')
        if sum(x['state']=='COMPLETED' for x in old['entries'].values())!=9:raise ValueError('existing completed count drift')
        if any(x.get('kind') for x in old['entries'].values()):raise ValueError('unexpected historical scientific failure')
        counts.append(e.b.inspect(p))
    cap=read(OUT/'capacity.json')
    if cap['status']!='PASS' or cap['node']!=platform.node() or time.time()-cap['observed_at']>1800:
        raise ValueError('fresh actual owner-capacity receipt missing')
    result=dict(status='PASS_ZERO_GAME_PREFLIGHT',shards=8,existing_completed=72,remaining=440,new_games=0,node=platform.node(),observed_at=time.time())
    write(OUT/'preflight.json',result);return result

def worker():
    d=verify();procs=[]
    try:
        for label in d['labels']:
            log=(OUT/(label+'.log')).open('xb')
            p=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'grid','--label',label],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
            procs.append((p,log,label))
        while any(p.poll() is None for p,_,_ in procs):
            if any(p.poll() not in (None,0) for p,_,_ in procs):raise ValueError('retained shard failure')
            counts=[read(ROOT/'evaluation'/label/'ledger.json') for label in d['labels']]
            write(OUT/'progress.json',dict(state='RUNNING',completed=sum(sum(x['state']=='COMPLETED' for x in v['entries'].values()) for v in counts),planned=512,original_completed=72,observed_at=time.time()))
            time.sleep(2)
        if any(p.returncode!=0 for p,_,_ in procs):raise ValueError('shard failed')
        counts=[e.b.inspect(ROOT/'evaluation'/label) for label in d['labels']]
        n=sum(x['completed_games'] for x in counts);caps=sum(x['truncated_games'] for x in counts)
        if n+caps!=512:raise ValueError('incomplete fixed grid')
        result=dict(status='PASS_ORIGINAL_GRID_FINISHED',completed=n,truncated=caps,new_logical_games=440,counts=counts,observed_at=time.time())
        write(OUT/'worker-completion.json',result);return result
    finally:
        for p,log,_ in procs:
            if p.poll() is None:p.terminate()
        for p,log,_ in procs:
            try:p.wait(timeout=15)
            finally:log.close()

def run():
    d=verify()
    from scripts.prism_dsw_ppo_process import ProcessTree
    from training.prism_portable.processes import directory_bytes
    with lock(OUT/'owner'):
        if (OUT/'resource.json').exists():raise ValueError('one authorized launch already resolved')
        preflight()
        os.environ.update(PRISM_PPO_CONTROL_DIR=str(OUT),PRISM_DSW_REMAINING_WALL='8000',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
        os.sched_setaffinity(0,set(sorted(os.sched_getaffinity(0))[:8]))
        scan=[0.]
        def storage():
            if time.monotonic()<scan[0]:return
            scan[0]=time.monotonic()+60
            return 'owned_storage_limit' if sum(directory_bytes(ROOT/'evaluation'/label) for label in d['labels'])>1024**3 else None
        with (OUT/'worker.log').open('xb') as log:
            with ProcessTree(cpu_seconds=4000-read(OUT/'r24-repair.json')['charged_cpu_seconds'],memory_bytes=8*1024**3,max_processes=128) as tree:
                p=tree.start([sys.executable,'-B',str(Path(__file__).resolve()),'worker'],cwd=ROOT,stdout=log,stderr=log)
                counters=tree.wait(wall_seconds=8000,stop_checker=storage,snapshot=lambda x:write(OUT/'status.json',dict(state='RUNNING',node=platform.node(),pid=os.getpid(),relay_pid=p.pid,resources=x,observed_at=time.time())))
        current_cpu=counters['cpu_seconds'];counters['cpu_seconds']+=read(OUT/'r24-repair.json')['charged_cpu_seconds']
        counters['r23_measured_cpu_seconds']=current_cpu
        result=dict(status='PASS' if counters['returncode']==0 and not counters['stop_reason'] else 'FAIL',resources=counters,observed_at=time.time(),adapter_sha256=digest(__file__))
        write(OUT/'resource.json',result)
        if result['status']!='PASS':raise ValueError('retained auxiliary failure')
        members={};dest=OUT/'results.zip'
        with zipfile.ZipFile(dest,'x',zipfile.ZIP_DEFLATED) as z:
            files=[OUT/'resource.json',OUT/'worker-completion.json',OUT/'retries.json']
            files += [p for label in d['labels'] for p in (ROOT/'evaluation'/label).rglob('*') if p.is_file()]
            for p in files:
                name=p.relative_to(ROOT).as_posix();z.write(p,name);members[name]=dict(sha256=digest(p),bytes=p.stat().st_size)
        receipt=dict(status='READY_FOR_SHA_IMPORT',sha256=digest(dest),bytes=dest.stat().st_size,files=members,labels=d['labels'],resource=result)
        write(OUT/'results.receipt.json',receipt);write(OUT/'status.json',dict(state='COMPLETED_PENDING_IMPORT',observed_at=time.time()))
        return {k:v for k,v in receipt.items() if k!='files'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['preflight','run','worker','grid']);p.add_argument('--label');a=p.parse_args()
    if a.mode=='grid':
        d=install()
        if a.label not in d['labels']:raise ValueError('unowned shard')
        result=e.grid(ROOT/'evaluation'/a.label)
    else:result=globals()[a.mode]()
    print(json.dumps(result),flush=True)
