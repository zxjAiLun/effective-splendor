"""M81 resource-bounded A/B controller; no calendar stop or monitoring service."""
import argparse,copy,gc,hashlib,importlib.metadata,json,os,platform,shutil,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
PLAN='benchmarks/m81-anchor-coverage.execution-plan.json'
PY='/mnt/workspace/envs/splendor-m79-ppo-py312/bin/python'
from training.prism_portable.common import read,write,digest,lock,numerical_identity
from scripts.prism_dsw_ppo_process import ProcessTree,install as process_install
from scripts import prism_m79_run as legacy
adapted=legacy.adapted
def bounds():
    return 300000.0
def environment():
    return dict(python=sys.version,executable=str(Path(sys.executable).resolve()),packages={k:importlib.metadata.version(k) for k in ('torch','numpy','psutil','Markdown')},node=platform.node())
def verify():
    p=read(ROOT/'execution.json');c=read(ROOT/PLAN)
    if digest(ROOT/PLAN)!=p['plan_sha256']:raise ValueError('M81 plan drift')
    for name,h in p['files'].items():
        if digest(ROOT/name)!=h:raise ValueError('source/input drift '+name)
    e=environment()
    if e!=p['environment']:raise ValueError('M81 execution environment drift')
    return c,p
def install_resource_mode():
    process_install()
    from training.prism_portable.engine.ppo import coordinator as co,arena
    if getattr(co,'_m81_resource',False):return
    co.validate_config=adapted(co.validate_config,[
      ('if number(value["budget"]["max_run_seconds"], 0, float("inf"), "max_run_seconds") <= 0:',
       'if value["budget"]["max_run_seconds"] is not None and number(value["budget"]["max_run_seconds"], 0, float("inf"), "max_run_seconds") <= 0:')])
    co.Run._admit=adapted(co.Run._admit,[
      ('if elapsed < 0 or elapsed >= self.config["budget"]["max_run_seconds"]:',
       'if elapsed < 0 or (self.config["budget"]["max_run_seconds"] is not None and elapsed >= self.config["budget"]["max_run_seconds"]):')])
    arena.supervised=adapted(arena.supervised,[
      ("remaining_wall = spec['run']['budget']['max_run_seconds'] - elapsed",
       "remaining_wall = spec['limits']['campaign_cpu_seconds'] * 2 if spec['run']['budget']['max_run_seconds'] is None else spec['run']['budget']['max_run_seconds'] - elapsed")])
    from training.prism_portable import protocol
    protocol.create=adapted(protocol.create,[('campaign.run.state["started_at"]\n                                         + blueprint["template"]["run"]["budget"]["max_run_seconds"]','None if blueprint["template"]["run"]["budget"]["max_run_seconds"] is None else campaign.run.state["started_at"] + blueprint["template"]["run"]["budget"]["max_run_seconds"]')])
    from scripts import prism_bounded_eval as b
    b.validate_policy=adapted(b.validate_policy,[
      ('for key in ("deadline_unix", "cpu_seconds"):','require(policy["deadline_unix"] is None, "M81 resource policy requires null calendar");\n    for key in ("cpu_seconds",):')])
    b.prepare=adapted(b.prepare,[('require(policy["deadline_unix"] > time.time(), "deadline exhausted")','require(policy["deadline_unix"] is None, "resource policy required")')])
    b.launch=adapted(b.launch,[
      ('wall = min(validated["config"]["timeouts"]["game_wall_seconds"],\n               policy["deadline_unix"] - time.time())','wall = validated["config"]["timeouts"]["game_wall_seconds"]'),
      ('remaining_wall = min(wall, max(0., policy["deadline_unix"] - time.time()))','remaining_wall = max(0., wall - (time.monotonic() - admitted_at))'),
      ('require(wall > 0 and remaining_cpu > 0, "resource budget exhausted")','require(wall > 0 and remaining_cpu > 0, "resource budget exhausted"); admitted_at = time.monotonic()')])
    b.run=adapted(b.run,[
      ('require(time.time() + validated["config"]["timeouts"]["game_wall_seconds"]\n                    <= policy["deadline_unix"], "insufficient deadline for next game")','require(policy["deadline_unix"] is None, "resource policy required")'),
      ('require(time.time() <= policy["deadline_unix"], "absolute deadline exhausted")','require(policy["deadline_unix"] is None, "resource policy required")')])
    legacy.ROOT=ROOT;legacy.bounds=bounds
    legacy.install()
    co._m81_resource=True
def blueprint(arm):
    c=read(ROOT/PLAN);bp=read(ROOT/'benchmarks/m79-prism-mainline.a-train.json')
    bp=copy.deepcopy(bp);t=bp['template'];r=t['run'];r.update(run_id='m81-'+arm,seed=c['training']['run_seed'])
    r['budget']['max_run_seconds']=None
    r['budget']['max_attempts']=5184;t['limits']['max_infra_retries']=64
    order=c['training']['arms'][arm]['opponent_period']
    t['cycles']=[[dict(job_id=f'm81-{arm}-c{cy+1}-b{bl}-s{seat}',actor=seat,opponent_id=order[bl%16],environment_seed=81001000+128*cy+bl) for bl in range(128) for seat in (0,1)] for cy in range(20)]
    for name in set(order):
        if name not in t['opponents']:
            if name=='heuristic':
                t['opponents'][name]=dict(program='@engine',sha256='@engine_sha256',args=['agent-heuristic-v02','--seed','81090002'],files={},hello=dict(agent_name='splendor-cli-heuristic-v02',agent_version='0.2.9'),mode='greedy')
            else:
                row=copy.deepcopy(t['opponents']['general']);row['args']=['agent-prism','--weights','@'+name,'--seed','81090002'];row['files']={'@'+name:'@'+name+'_sha256'};t['opponents'][name]=row
    t['opponents']={name:t['opponents'][name] for name in set(order)}
    r['opponents']={name:'' for name in set(order)}
    bp['weight_hashes']={name:c['assets'][name]['sha256'] for name in set(order) if name!='heuristic'}
    bp['model_label']='M81 '+arm+' fixed c20';return bp
def worker(arm,stop_cycle=20):
    verify();install_resource_mode()
    from training.prism_portable.protocol import create,assert_owner
    from training.prism_portable.engine.ppo.coordinator import Run
    from training.prism_portable.engine.ppo.arena import Campaign
    from training.prism_portable.engine.export import load_weights
    import torch
    camp=ROOT/'campaigns'/arm;host=read(ROOT/'host.json')
    if not camp.exists():
        owner=create(camp,read(ROOT/f'benchmarks/m81-{arm}.train.json'),host,'m81-'+arm)
        run=Run.open(camp/'run');parent=load_weights(ROOT/'inputs/parent.json',expected_catalog_fingerprint=run.config['catalog_fingerprint'])
        if run.state['optimizer']['state'] or run.state['attempts']:raise ValueError('not fresh')
        if not all(torch.equal(t,run.state['model']['policy.'+k]) for k,t in parent.state_dict().items()):raise ValueError('parent tensor mismatch')
        write(camp/'initialization-verification.json',dict(status='PASS',exact_parent_tensors=32,optimizer_slots=0,run_seed=81090001,parent_sha256=digest(ROOT/'inputs/parent.json'),torch_rng_sha256=hashlib.sha256(bytes(run.state['rng']['torch'].tolist())).hexdigest()))
        del run,parent;gc.collect()
    owner=assert_owner(camp,host['host_id'])
    os.environ.update(PRISM_PPO_HOST_ID=owner['host_id'],PRISM_PPO_OWNER_NONCE=owner['nonce'],PRISM_PPO_CONTROL_DIR=str(camp/'control'),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
    campaign=Campaign(camp,read(camp/'contract.json'))
    while not(campaign.run.state['phase']=='COMMITTED' and campaign.run.state['cycle']>=stop_cycle):
        campaign.work(stop_after_cycle=True);legacy.publish_progress(campaign)
    _,ledger=campaign._load();s=campaign.run.state
    result=dict(status='COMMITTED_FULL' if s['cycle']==20 else 'COMMITTED_PARTIAL',cycle=s['cycle'],logical_attempts=len(s['all_jobs']),physical_attempts=s['attempts'],games=sum(x['status']=='COMPLETE' for x in ledger['attempts'].values()),truncated_games=sum(x['status']=='TRUNCATED' for x in ledger['attempts'].values()),global_step=s['global_step'],update_attempts=s['update_attempts'],weights=str(camp/f'cycle-{s["cycle"]}-export/weights.json'),execution_sha256=digest(ROOT/'execution.json'))
    result['weights_sha256']=digest(result['weights']);write(camp/'worker-completion.json',result);return result
def preflight():
    install_resource_mode();c=read(ROOT/PLAN)
    from training.prism_portable.provision import provision
    reserve=8*1024**3
    if shutil.disk_usage(ROOT).free<reserve:raise ValueError('8GiB reserve missing')
    if digest(ROOT/'bin/splendor')!=c['assets']['heuristic']['engine_sha256']:raise ValueError('heuristic engine drift')
    expected={'torch':'2.6.0+cpu','numpy':'2.2.4','psutil':'7.0.0','Markdown':'3.7'}
    if environment()['packages']!=expected:raise ValueError('numeric runtime drift')
    host,parity=provision(ROOT,ROOT,ROOT/'bin/splendor',ROOT/'bin/s4_batch_metrics',ROOT/'inputs/parent.json',ROOT/'inputs/initial.json',ROOT/'inputs/fixtures.jsonl','m81-'+platform.node())
    if parity['boundary_inputs']!=68:raise ValueError('parity boundary count')
    for name,v in c['assets'].items():
        if name=='heuristic':continue
        f=ROOT/f'inputs/{name}.json'
        if digest(f)!=v['sha256']:raise ValueError('asset drift '+name)
        host['assets'][name]=dict(path=str(f),sha256=v['sha256'])
    write(ROOT/'host.json',host)
    from training.prism_portable.protocol import bind
    for arm in ('A','B'):
        bp=blueprint(arm);write(ROOT/f'benchmarks/m81-{arm}.train.json',bp);bind(bp,host)
    members={}
    for folder in ('training','scripts'):
        for p in (ROOT/folder).rglob('*.py'):
            members[str(p.relative_to(ROOT))]=digest(p)
    for p in (ROOT/'inputs').glob('*'):
        if p.is_file():members[str(p.relative_to(ROOT))]=digest(p)
    members.update({n:digest(ROOT/n) for n in ['bin/splendor','bin/s4_batch_metrics','host.json','benchmarks/m81-A.train.json','benchmarks/m81-B.train.json']})
    receipt=dict(status='PASS_ZERO_GAME_PREFLIGHT',plan_sha256=digest(ROOT/PLAN),files=members,environment=environment(),parity=parity,new_games=0,resource_mode='finite work and CPU; null calendar',node=platform.node(),observed_at=time.time())
    write(ROOT/'execution.json',receipt);return receipt
def stage(mode,arm=None,stop_cycle=20):
    c,p=verify();control=ROOT/'pipeline';control.mkdir(exist_ok=True)
    rows=read(control/'resources.json') if (control/'resources.json').exists() else [dict(category='control',cpu_seconds=1000.0,label='engineering-preparation-reservation',accounting_scope='conservative engineering preparation charge; actual CPU unmeasured')]
    label=mode+('-'+arm if arm else '')
    receipt_path=control/(label+'.completion.json')
    if receipt_path.exists() and read(receipt_path)['status']=='PASS':return read(receipt_path)
    cap=150000 if mode in ('train','evaluate') else 30000
    category=('training-'+arm) if mode=='train' else 'evaluation' if mode=='evaluate' else 'control'
    spent=sum(x['cpu_seconds'] for x in rows if x['category']==category)
    external=read(ROOT/'baseline-import.json').get('cpu_seconds',0.0) if (ROOT/'baseline-import.json').exists() else 0.0
    remaining=min(cap-spent-(external if category=='evaluation' else 0.0),480000-sum(x['cpu_seconds'] for x in rows)-external)
    if remaining<=0:raise ValueError('CPU budget exhausted '+category)
    os.environ.update(PRISM_PPO_CONTROL_DIR=str(control),PRISM_DSW_REMAINING_WALL=str(remaining*2),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2' if mode=='train' else '1',MKL_NUM_THREADS='2' if mode=='train' else '1')
    argv=[PY,'-B',str(Path(__file__).resolve()),'execute','--stage',mode,'--stop-cycle',str(stop_cycle)]
    if arm:argv+=['--arm',arm]
    with (control/(label+'.log')).open('ab') as f:
        with ProcessTree(cpu_seconds=remaining,memory_bytes=8*1024**3 if mode=='train' else 16*1024**3,max_processes=128) as tree:
            proc=tree.start(argv,cwd=ROOT,stdout=f,stderr=f)
            write(control/'status.json',dict(state='RUNNING',phase=label,pid=os.getpid(),relay_pid=proc.pid,node=platform.node(),observed_at=time.time()))
            def publish(resources):write(control/'status.json',dict(state='RUNNING',phase=label,pid=os.getpid(),relay_pid=proc.pid,node=platform.node(),resources=resources,observed_at=time.time()))
            resource=tree.wait(wall_seconds=min(remaining*2,7*3600) if os.environ.get('M81_EVAL_ACTORS')=='base' else remaining*2,storage_root=ROOT/'campaigns'/arm if mode=='train' else ROOT,max_storage_bytes=32*1024**3 if mode=='train' else 80*1024**3,storage_interval=60,snapshot=publish,stop_checker=lambda: 'NODE_FREE_8GIB_RESERVE' if shutil.disk_usage(ROOT).free<8*1024**3 else None)
    rows.append(dict(category=category,cpu_seconds=resource['cpu_seconds'],resources=resource,label=label));write(control/'resources.json',rows)
    result=dict(status='PASS' if resource['returncode']==0 and not resource['stop_reason'] else 'FAIL',resources=resource,label=label)
    write(receipt_path,result)
    if result['status']!='PASS':raise ValueError('stage failed '+label)
    return result
def pipeline(role):
    verify();process_install()
    with lock(ROOT/'pipeline'):
        try:
            if role=='main':
                for arm in ('A','B'):stage('train',arm)
                stage('audit')
                while not (ROOT/'baseline-import.json').exists():
                    if (ROOT/'baseline-dispatch-failure.json').exists():raise ValueError('baseline handoff failed; retained evidence')
                    write(ROOT/'pipeline/status.json',dict(state='WAITING_BASELINE_DELIVERY',observed_at=time.time()));time.sleep(30)
                stage('evaluate');stage('report')
            elif role=='baseline':
                os.environ['M81_EVAL_ACTORS']='base';stage('evaluate')
            else:raise ValueError('role')
            write(ROOT/'pipeline/status.json',dict(state='COMPLETED_EXECUTION_PENDING_LOCAL_VISUAL_ARCHIVE',observed_at=time.time()))
        except BaseException as e:
            write(ROOT/'pipeline/status.json',dict(state='STOPPED_RETAINED_EVIDENCE',error=repr(e),observed_at=time.time()));raise
def execute(mode,arm=None,stop_cycle=20):
    install_resource_mode();verify()
    if mode=='train':return worker(arm,stop_cycle)
    if mode=='audit':
        from scripts.prism_m81_audit import audit
        return audit(ROOT)
    if mode=='evaluate':
        from scripts.prism_m81_evaluate import evaluate
        return evaluate(ROOT)
    if mode=='report':
        from scripts.prism_m81_report import report
        return report(ROOT)
    raise ValueError(mode)
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('mode');a.add_argument('--role',default='main');a.add_argument('--arm');a.add_argument('--stage');a.add_argument('--stop-cycle',type=int,default=20);x=a.parse_args()
    result=preflight() if x.mode=='preflight' else pipeline(x.role) if x.mode=='pipeline' else execute(x.stage,x.arm,x.stop_cycle)
    print(json.dumps(result),flush=True)
