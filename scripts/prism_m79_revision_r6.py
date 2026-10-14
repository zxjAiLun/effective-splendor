"""M79 independent ownership bootstrap adapter; original r4 source is immutable."""
import argparse,hashlib,inspect,json,os,sys,textwrap,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from training.prism_portable.common import read,write,digest,lock
from scripts import prism_m79_run as run,prism_m79_recovery as recovery

def source_patch(function,old,new):
    source=textwrap.dedent(inspect.getsource(function))
    if source.count(old)!=1:raise ValueError('revision adapter target drift')
    ns=dict(function.__globals__);exec(compile(source.replace(old,new),str(Path(__file__))+'::'+function.__name__,'exec'),ns)
    return ns[function.__name__]

def verify_revision():
    r=read(ROOT/'execution-revisions/r6.json')
    if digest(__file__)!=r['adapter_sha256'] or digest(ROOT/'execution.json')!=r['base_execution_sha256']:raise ValueError('independent execution revision drift')
    run.verify()
    return r

def patched_worker():
    verify_revision()
    fn=source_patch(run.worker,"owner=assert_owner(camp,host['host_id']);", "owner=read(camp/'ownership.json');owner=assert_owner(camp,host['host_id'],nonce=owner['nonce']);")
    result=fn();result['execution_revision_sha256']=digest(ROOT/'execution-revisions/r6.json');result['adapter_sha256']=digest(__file__)
    write(ROOT/'campaigns/a/worker-completion.json',result);return result

def pipeline():
    verify_revision()
    native_start=run.ProcessTree.start
    def start(self,argv,**kw):
        if len(argv)>=4 and argv[-1]=='worker' and argv[-2]==str(ROOT/'scripts/prism_m79_run.py'):
            argv=[*argv[:-2],str(Path(__file__).resolve()),'worker']
        return native_start(self,argv,**kw)
    run.ProcessTree.start=start
    return run.pipeline()

def reconcile_zero_attempt_bootstrap():
    verify_revision();import psutil
    from scripts.prism_m67_storage import install
    from training.prism_portable.engine.ppo.coordinator import Run
    from training.prism_portable.protocol import assert_owner,state_fingerprints
    from training.prism_portable.engine.export import load_weights
    install();host=read(ROOT/'host.json');camp=ROOT/'campaigns/a';owner=read(camp/'ownership.json')
    assert_owner(camp,host['host_id'],owner['nonce'])
    state=Run.open(camp/'run');s=state.state
    if s['attempts'] or s['cycle'] or s['global_step'] or s['update_attempts'] or s['optimizer']['state'] or s['all_jobs'] or s['phase']!='READY':raise ValueError('bootstrap repair requires zero-attempt READY state')
    import torch
    parent=load_weights(ROOT/'inputs/parent.json',expected_catalog_fingerprint=state.config['catalog_fingerprint'])
    if any(not torch.equal(s['model']['policy.'+k],v) for k,v in parent.state_dict().items()):raise ValueError('bootstrap parent state drift')
    for p in psutil.process_iter(['pid','cmdline']):
        try:
            if p.pid!=os.getpid() and str(ROOT/'scripts/prism_m79_run.py') in (p.info['cmdline'] or []):raise ValueError('original owner still active')
        except (psutil.NoSuchProcess,psutil.AccessDenied):pass
    path=ROOT/'pipeline/train.completion.json';saved=read(path)
    log=(ROOT/'pipeline/train-3.log').read_text()
    if saved['status']!='FAIL' or saved['resources']['returncode']!=1 or "KeyError: 'worker'" not in log:raise ValueError('failure does not match finite bootstrap repair')
    destination=ROOT/'execution-revisions/r5-bootstrap-failure.json'
    if destination.exists():raise ValueError('bootstrap already reconciled')
    receipt=dict(status='PASS_ZERO_ATTEMPT_BOOTSTRAP_RECONCILIATION',original_train_completion=saved,original_completion_sha256=digest(path),original_log_sha256=digest(ROOT/'pipeline/train-3.log'),state_fingerprints=state_fingerprints(s),run_commit=state.parent,initialization_sha256=digest(camp/'initialization-verification.json'),budget=read(ROOT/'round-budget.json'),charged_cpu_seconds=saved['resources']['cpu_seconds'],new_games=0,observed_at=time.time())
    write(destination,receipt)
    # Move the original stage receipt into this immutable failure archive; never erase it.
    path.rename(ROOT/'execution-revisions/r5-train.completion.json')
    return receipt

def ensure():
    verify_revision();recovery.bind_replacement_node()
    native=run.subprocess.Popen
    def launch(argv,**kw):
        if len(argv)>=4 and argv[-1]=='pipeline' and argv[-2]==str(ROOT/'scripts/prism_m79_run.py'):
            argv=[*argv[:-2],str(Path(__file__).resolve()),'pipeline']
        return native(argv,**kw)
    run.subprocess.Popen=launch
    from scripts.prism_dsw_ppo_process import same_process
    with lock(ROOT/'revision-dispatch-control'):
        path=ROOT/'pipeline/launches.json'
        for receipt in reversed(read(path) if path.exists() else []):
            if same_process(receipt['pid'],receipt['create_time']):
                import psutil
                if str(Path(__file__).resolve()) not in psutil.Process(receipt['pid']).cmdline():raise ValueError('another revision owner remains active')
                return dict(receipt,action='LIVE_STARTUP_OR_OWNER_KEEP',execution_revision_sha256=digest(ROOT/'execution-revisions/r6.json'))
        result=run.ensure();result['execution_revision_sha256']=digest(ROOT/'execution-revisions/r6.json');return result

def status():
    verify_revision()
    from scripts.prism_dsw_ppo_process import same_process
    saved=read(ROOT/'pipeline/status.json') if (ROOT/'pipeline/status.json').exists() else {}
    budget=read(ROOT/'round-budget.json');result=dict(saved,node=run.environment()['node'],observed_at=time.time(),execution_sha256=digest(ROOT/'execution.json'),execution_revision_sha256=digest(ROOT/'execution-revisions/r6.json'),deadline=budget['deadline'])
    if (ROOT/'pipeline/completion.json').exists():result['state']='COMPLETED'
    elif time.time()>=budget['deadline']:result['state']='DEADLINE'
    elif saved.get('pid') and same_process(saved['pid'],saved['create_time']):
        import psutil
        if str(Path(__file__).resolve()) not in psutil.Process(saved['pid']).cmdline():raise ValueError('revision process identity mismatch')
        result['state']='RUNNING'
        p=ROOT/'campaigns/a/control/live-progress.json'
        if p.exists():result['training']=read(p)
    else:result['state']='NO_OWNER'
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['worker','pipeline','reconcile','ensure','endpoint','status']);args=parser.parse_args()
    method=json.loads(sys.stdin.readline())['method'] if args.mode=='endpoint' else args.mode
    if args.mode=='endpoint' and method not in ('status','ensure'):raise ValueError('restricted revision RPC method')
    if method not in ('worker','pipeline','reconcile','ensure','status'):raise ValueError('restricted revision method')
    print(json.dumps(reconcile_zero_attempt_bootstrap() if method=='reconcile' else patched_worker() if method=='worker' else globals()[method]()),flush=True)
