"""Portable, bounded SSH/Notebook arena. Import/prepare never dispatch matches.

Independent development measurement; never resumes a frozen milestone campaign.
Only gracefully stopped, never-dispatched shards can be resumed. Failed or
partially dispatched shards cannot be retried. psutil limits are observed soft
process-tree limits; no claim of a dedicated cgroup or hard memory isolation.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib.metadata
import json
import math
import os
import platform
from pathlib import Path
import signal
import subprocess
import struct
import sys
import time
import zipfile

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import prism_ppo_fixed_eval as fixed

FORMAT = 'prism-notebook-arena-v1'
SOURCES = ('scripts/prism_notebook_arena.py', 'scripts/prism_notebook_report.py',
           'scripts/prism_ppo_fixed_eval.py', 'scripts/prism_match_details.py',
           'scripts/prism_cloud_storage_snapshot.py', 'scripts/prism_dsw_arena.py')
read, write, sha, require = fixed.read_json, fixed.atomic_json, fixed.sha256_file, fixed._require


def resource_profile(cgroup_root=Path('/sys/fs/cgroup'), cgroup_lines=None):
    """Combine affinity and every visible cgroup ancestor, without modifying one."""
    affinity = len(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else (os.cpu_count() or 1)
    capacity, memory = float(min(affinity,os.cpu_count() or affinity)), psutil.virtual_memory().total
    constraints = []
    if sys.platform.startswith('linux'):
        lines=cgroup_lines if cgroup_lines is not None else Path('/proc/self/cgroup').read_text().splitlines()
        cg = next((line.split(':', 2)[2].strip() for line in lines if line.startswith('0:')), '/')
        root = Path(cgroup_root).resolve()
        leaf = root / cg.lstrip('/')
        # Container namespaces may expose only the mount root.
        if not leaf.is_dir(): leaf = root
        for p in [leaf, *leaf.parents]:
            if not p.is_relative_to(root): break
            row = {'path': str(p)}
            if (p/'cpu.max').is_file():
                quota, period = (p/'cpu.max').read_text().split()
                if quota != 'max':
                    value = int(quota) / int(period); capacity = min(capacity, value); row['cpu_quota_cores'] = value
            if (p/'memory.max').is_file():
                value = (p/'memory.max').read_text().strip()
                if value != 'max': memory = min(memory, int(value)); row['memory_max_bytes'] = int(value)
            constraints.append(row)
        # DSW currently uses cgroup v1; affinity can expose the host CPU set.
        for line in lines:
            _,controllers,relative=line.split(':',2)
            controllers=controllers.split(',')
            for controller in ('cpu','memory'):
                if controller not in controllers:continue
                mount=root/controller
                if not mount.exists() and controller=='cpu':mount=root/'cpu,cpuacct'
                if not mount.is_dir():continue
                mount=mount.resolve();leaf=mount/relative.lstrip('/')
                if not leaf.is_dir():leaf=mount
                for p in [leaf,*leaf.parents]:
                    if not p.is_relative_to(mount):break
                    row={'path':str(p),'cgroup_version':1}
                    if controller=='cpu' and (p/'cpu.cfs_quota_us').is_file():
                        quota=int((p/'cpu.cfs_quota_us').read_text());period=int((p/'cpu.cfs_period_us').read_text())
                        if quota>0:capacity=min(capacity,quota/period);row['cpu_quota_cores']=quota/period
                    if controller=='memory' and (p/'memory.limit_in_bytes').is_file():
                        value=int((p/'memory.limit_in_bytes').read_text());memory=min(memory,value);row['memory_max_bytes']=value
                    constraints.append(row)
    cores = max(1, math.floor(capacity))
    return dict(logical_host_cpus=os.cpu_count(), affinity_cpus=affinity,
                effective_cpu_capacity=capacity, effective_whole_cores=cores,
                effective_memory_bytes=memory, host_available_memory_bytes=psutil.virtual_memory().available,
                recommended_workers=max(1, cores - (2 if cores >= 8 else 1)),
                cgroup_constraints=constraints, platform=sys.platform,
                limit_scope='observed process-tree soft limits; shared platform cgroups are not owned')


def model(weights, display_name, engine, *, mode='sample', action_seed=64010001):
    require(mode in ('sample', 'greedy'), 'model mode must be sample or greedy')
    weights, engine = Path(weights).resolve(), Path(engine).resolve()
    export = read(weights)
    require(export.get('format') == 'prism-weights-v1', 'expected exported Prism JSON, not a torch checkpoint')
    require(isinstance(display_name, str) and display_name.strip(), 'full display name required')
    return dict(display_name=display_name, mode=mode, catalog_fingerprint=export['catalog_fingerprint'],
                descriptor=dict(program=str(engine), sha256=sha(engine),
                    args=['agent-prism-sample' if mode == 'sample' else 'agent-prism', '--weights', str(weights),
                          '--seed', str(action_seed)], files=[dict(path=str(weights), sha256=sha(weights))]))


def heuristic(engine, display_name='Heuristic 开发快照（agent-heuristic-v02，greedy）', seed=20260926):
    engine = Path(engine).resolve()
    return dict(display_name=display_name, mode='greedy', descriptor=dict(program=str(engine),
                sha256=sha(engine), args=['agent-heuristic-v02', '--seed', str(seed)], files=[]))


def check_native_architecture(path):
    with Path(path).open('rb') as stream:header=stream.read(64)
    if header[:4]!=b'\x7fELF':return
    require(sys.platform.startswith('linux'),'Linux ELF tool cannot run on this platform')
    require(len(header)>=20 and header[5] in (1,2),'invalid ELF header')
    machine=struct.unpack_from('<H' if header[5]==1 else '>H',header,18)[0]
    expected={'x86_64':62,'amd64':62,'aarch64':183,'arm64':183}.get(platform.machine().lower())
    require(expected is not None and machine==expected,
            f'native architecture mismatch: ELF machine {machine}, host {platform.machine()}; build a matching tool')


def validate_arena_config(config, path):
    """Extend the generic arena only; the frozen PPO evaluator remains sample-only.

    Reuse its descriptor/path/seed validation, then restore the explicitly saved
    command in both the validated config and effective argv. No saved bytes change.
    """
    checked = copy.deepcopy(config)
    greedy = []
    for name, descriptor in checked.get('candidates', {}).items():
        if descriptor.get('args', [])[:1] == ['agent-prism']:
            greedy.append(name)
            descriptor['args'][0] = 'agent-prism-sample'
    validated = fixed.validate_config(checked, path)
    for name in greedy:
        validated['candidates'][name]['args'][0] = 'agent-prism'
        validated['candidates'][name]['args_resolved'][0] = 'agent-prism'
    return validated


def worker_limit(profile, performance_calibration=False):
    require(type(performance_calibration) is bool, 'calibration flag must be boolean')
    cores=profile['effective_whole_cores']
    if performance_calibration:
        require(cores==4, 'oversubscription calibration requires the measured four-core allocation')
        return 6
    return cores


def prepare(work, engine, metrics_program, candidates, opponents, seeds, *, workers=None,
            action_seed=64010001, shard_seed_blocks=8, memory_gib=None, wall_hours=8,
            cpu_hours=24, storage_gib=32, instance_hours=None, expiry_margin_minutes=45,
            performance_calibration=False):
    work, engine, metrics = Path(work).resolve(), Path(engine).resolve(), Path(metrics_program).resolve()
    require(not work.exists(), 'new run directory required; never overwrite an existing experiment')
    check_native_architecture(engine);check_native_architecture(metrics)
    profile = resource_profile()
    workers = profile['recommended_workers'] if workers is None else workers
    require(type(workers) is int and 1 <= workers <= worker_limit(profile,performance_calibration), 'workers exceed effective CPU allocation')
    require(type(shard_seed_blocks) is int and 1 <= shard_seed_blocks <= 128, 'shard size must be 1..128 seed blocks')
    maximum_memory = min(profile['effective_memory_bytes']*.75, profile['host_available_memory_bytes']*.8)
    memory_bytes = int(maximum_memory if memory_gib is None else memory_gib*1024**3)
    require(256*1024**2 <= memory_bytes <= maximum_memory, 'memory budget exceeds available headroom')
    require(0 < wall_hours <= 48 and 0 < cpu_hours <= 512 and 0 < storage_gib <= 1024, 'invalid bounded resource budget')
    deadline=None
    if instance_hours is not None:
        require(sys.platform.startswith('linux') and 0 < instance_hours <= 48 and expiry_margin_minutes >= 15,
                'invalid instance lifetime guard')
        deadline=psutil.Process(1).create_time()+instance_hours*3600-expiry_margin_minutes*60
        require(time.time()+wall_hours*3600 < deadline,'wall budget exceeds remaining instance lifetime margin')
    names = set(candidates) | set(opponents)
    for name in names: fixed._validate_name(name, 'model/opponent')
    require(all(c['mode'] in ('sample', 'greedy') for c in candidates.values()), 'invalid candidate mode')
    catalogs = {c['catalog_fingerprint'] for c in [*candidates.values(), *opponents.values()] if 'catalog_fingerprint' in c}
    require(len(catalogs) == 1, 'all model exports must share one catalog fingerprint')
    config = dict(format=fixed.FORMAT, engine=dict(program=str(engine), sha256=sha(engine)),
                  catalog_fingerprint=next(iter(catalogs)), action_seed=action_seed, seeds=list(seeds),
                  candidates={k:copy.deepcopy(v['descriptor']) for k,v in candidates.items()},
                  opponents={k:copy.deepcopy(v['descriptor']) for k,v in opponents.items()},
                  timeouts=dict(game_wall_seconds=90, handshake_timeout_ms=10000,
                                move_timeout_ms=10000, shutdown_grace_ms=1000))
    validated = validate_arena_config(config, work/'config.json'); fixed.check_assets(validated)
    total = len(candidates)*len(opponents)*len(seeds)*2
    if performance_calibration:
        require(total<=256 and wall_hours<=1 and memory_bytes<=8*1024**3,
                'calibration is limited to256 executions, one hour and8GiB per configuration')
    require(total <= 100000, 'bounded run supports at most100000 games; split larger prospective studies explicitly')
    subprocess.run([str(engine), 'version'], capture_output=True, text=True, timeout=20, check=True)
    require(metrics.is_file(), 'Rust replay metrics tool missing; build the s4_batch_metrics example')
    try:
        head = subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
        dirty = bool(subprocess.run(['git','status','--porcelain'],cwd=ROOT,capture_output=True,text=True,check=True).stdout)
    except (FileNotFoundError, subprocess.CalledProcessError): head, dirty = 'NOT_AVAILABLE', None
    work.mkdir(parents=True); (work/'configs').mkdir()
    write(work/'config.json', config)
    shards = []
    for candidate in candidates:
        for opponent in opponents:
            for start in range(0,len(seeds),shard_seed_blocks):
                shard = copy.deepcopy(config)
                shard.update(candidates={candidate:config['candidates'][candidate]},
                             opponents={opponent:config['opponents'][opponent]},
                             seeds=config['seeds'][start:start+shard_seed_blocks])
                name = f'shard-{len(shards):05d}'; path = work/'configs'/(name+'.json'); write(path,shard)
                shards.append(dict(name=name, config=str(path), sha256=sha(path),
                                   output=str(work/'shards'/name), games=2*len(shard['seeds'])))
    plan = dict(format=FORMAT, created_at=time.time(), verdict='DEVELOPMENT_ONLY_NOT_PROMOTED',
        config_sha256=sha(work/'config.json'), total_games=total, action_seed=action_seed,
        candidates={k:{a:v[a] for a in ('display_name','mode')} for k,v in candidates.items()},
        opponents={k:{a:v[a] for a in ('display_name','mode')} for k,v in opponents.items()},
        shards=shards, metrics_program=dict(path=str(metrics),sha256=sha(metrics)),
        source_hashes={p:sha(ROOT/p) for p in SOURCES},
        provenance=dict(git_head=head,dirty_worktree=dirty,python=sys.version,
            dependencies={n:importlib.metadata.version(n) for n in ('numpy','psutil','Markdown')}),
        profile=profile, limits=dict(workers=workers,memory_bytes=memory_bytes,
            wall_seconds=wall_hours*3600,cpu_seconds=cpu_hours*3600,storage_bytes=int(storage_gib*1024**3),
            automatic_game_retries=0,library_threads_per_worker=1,instance_deadline=deadline,
            instance_hours=instance_hours,expiry_margin_minutes=expiry_margin_minutes),
        clock_scope='standalone arena dispatch, saved replay audit and descriptive reports; excludes build/download',
        bootstrap=dict(seed=64049999,samples=20000,kind='descriptive paired seed blocks, not acceptance'))
    if performance_calibration:
        plan['limits']['performance_calibration']=True
        plan['verdict']='PERFORMANCE_DIAGNOSTIC_NOT_STRENGTH'
    write(work/'plan.json', plan)
    write(work/'status.json',dict(state='PREPARED_ZERO_GAMES',completed_games=0,total_games=total,shards={},
                                 plan_sha256=sha(work/'plan.json')))
    verify(work)
    return plan


def verify(work):
    work = Path(work).resolve(); plan = read(work/'plan.json')
    require(plan.get('format') == FORMAT and plan['limits']['automatic_game_retries']==0, 'plan contract drift')
    if plan['limits'].get('performance_calibration'):
        require(plan['verdict']=='PERFORMANCE_DIAGNOSTIC_NOT_STRENGTH' and plan['total_games']<=256
                and plan['limits']['wall_seconds']<=3600 and plan['limits']['memory_bytes']<=8*1024**3,
                'calibration scope drift')
    require(sha(work/'config.json') == plan['config_sha256'], 'config bytes changed')
    for path,digest in plan['source_hashes'].items(): require(sha(ROOT/path)==digest,'runner source changed: '+path)
    fixed.check_assets(validate_arena_config(read(work/'config.json'),work/'config.json'))
    require(sha(plan['metrics_program']['path']) == plan['metrics_program']['sha256'], 'metrics binary changed')
    for name,version in plan['provenance']['dependencies'].items():
        require(importlib.metadata.version(name)==version,'dependency version changed: '+name)
    config = read(work/'config.json'); grid=set()
    for s in plan['shards']:
        require(Path(s['config']).is_relative_to(work/'configs') and Path(s['output']).is_relative_to(work/'shards'), 'shard path outside run')
        require(sha(s['config'])==s['sha256'],'shard config changed')
        v=read(s['config']); validate_arena_config(v,s['config'])
        expected=copy.deepcopy(config);expected.update(candidates=v['candidates'],opponents=v['opponents'],seeds=v['seeds'])
        require(v==expected,'shard protocol differs from whole run')
        keys={(m,o,seed,seat) for m in v['candidates'] for o in v['opponents'] for seed in v['seeds'] for seat in (0,1)}
        require(not grid.intersection(keys) and len(keys)==s['games'],'duplicate or incomplete shard')
        grid.update(keys)
    expected={(m,o,seed,seat) for m in config['candidates'] for o in config['opponents'] for seed in config['seeds'] for seat in (0,1)}
    require(grid==expected and len(grid)==plan['total_games'],'logical game grid drift')
    return plan


def alive(owner):
    if owner.get('instance_key')!=instance_key():return False
    try: return abs(psutil.Process(owner['pid']).create_time()-owner['create_time'])<.01 and psutil.Process(owner['pid']).is_running()
    except (psutil.NoSuchProcess, KeyError): return False


def status(work):
    work=Path(work).resolve(); value=read(work/'status.json')
    if value['state'] in ('STARTING','RUNNING','STOP_REQUESTED'):
        owner=read(work/'owner.json') if (work/'owner.json').exists() else {}
        value['runner_alive']=alive(owner)
        if not value['runner_alive']: value['state']='INTERRUPTED_NO_AUTO_RETRY'
    return value


def start(work):
    work=Path(work).resolve(); plan=verify(work); state=status(work)
    require(state['state'] in ('PREPARED_ZERO_GAMES','STOPPED_SAFE'), 'only new or gracefully stopped runs may start')
    require(state.get('plan_sha256')==sha(work/'plan.json'),'prepared plan changed')
    require(not (work/'owner.json').exists() or not alive(read(work/'owner.json')),'a live runner already owns this run')
    for s in plan['shards']:
        if s['name'] in state.get('shards',{}):
            require(state['shards'][s['name']]['state']=='COMPLETE','partial/failed shard cannot be respawned')
            completed_shard(s,state['shards'][s['name']])
    profile=resource_profile();require(plan['limits']['workers']<=worker_limit(profile,plan['limits'].get('performance_calibration',False)), 'available CPU allocation decreased')
    fd=os.open(work/'launch.lock',os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
    try:
        # Recheck under the lock: a second caller may have waited until the first
        # finished launch but before its runner published RUNNING.
        state=status(work)
        require(state['state'] in ('PREPARED_ZERO_GAMES','STOPPED_SAFE'),'run state changed during launch')
        require(not (work/'owner.json').exists() or not alive(read(work/'owner.json')),'a live runner already owns this run')
        require(plan['limits']['memory_bytes'] <= min(profile['effective_memory_bytes']*.75,profile['host_available_memory_bytes']*.8),
                'available memory headroom decreased')
        deadline=instance_deadline(plan)
        remaining=plan['limits']['wall_seconds']-state.get('elapsed_wall_seconds',0)
        require(remaining>0 and (deadline is None or time.time()+remaining<deadline),
                'remaining wall budget exceeds instance lifetime margin')
        token=os.urandom(16).hex(); attempt=work/'attempts'/token;attempt.mkdir(parents=True)
        env=dict(os.environ)
        for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','RAYON_NUM_THREADS'):env[key]='1'
        with (attempt/'stdout.log').open('wb') as out,(attempt/'stderr.log').open('wb') as err:
            proc=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'run','--work',str(work),'--token',token],
                cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=err,start_new_session=(os.name!='nt'))
        owner=dict(pid=proc.pid,create_time=psutil.Process(proc.pid).create_time(),token=token,
                   instance_key=instance_key(),plan_sha256=sha(work/'plan.json'),instance_deadline=deadline)
        write(work/'owner.json',owner)
        return owner
    finally: (work/'launch.lock').unlink(missing_ok=True)


def stop(work,force=False):
    work=Path(work).resolve();owner=read(work/'owner.json');require(alive(owner),'owned runner is no longer alive')
    write(work/'attempts'/owner['token']/'stop.json',dict(force=bool(force),requested_at=time.time()))
    return 'force stop requested' if force else 'drain active shards, then stop safely; start can continue unstarted shards'


def instance_key():
    if sys.platform.startswith('linux'):
        text=Path('/proc/self/cgroup').read_text()
        return fixed.canonical_hash(dict(cgroup=text,pid1_created=psutil.Process(1).create_time()))
    return fixed.canonical_hash(dict(host=os.environ.get('COMPUTERNAME',''),boot=psutil.boot_time()))


def instance_deadline(plan):
    limits=plan['limits']
    if limits['instance_hours'] is None:return None
    require(sys.platform.startswith('linux'),'instance lifetime guard requires Linux')
    return psutil.Process(1).create_time()+limits['instance_hours']*3600-limits['expiry_margin_minutes']*60


def recover(work):
    """Reconcile durable completed shards; never replay a partial dispatched shard."""
    work=Path(work).resolve();plan=verify(work);owner=read(work/'owner.json')
    require(not alive(owner),'cannot recover a live runner')
    state=read(work/'status.json');require(state['state'] not in ('COMPLETED_DEVELOPMENT_ONLY','FAILED_PARTIAL_NO_RETRY'),
                                        'completed or failed runs cannot be automatically reopened')
    require(state.get('plan_sha256')==sha(work/'plan.json'),'recovery plan changed')
    saved=copy.deepcopy(state);failed=[]
    for shard in plan['shards']:
        name=shard['name'];entry=state.get('shards',{}).get(name)
        if entry is None:
            require(not Path(shard['output']).exists(),'unaccounted shard files; recovery stops');continue
        if entry['state']=='COMPLETE':completed_shard(shard,entry);continue
        path=Path(shard['output'])/'completion.json'
        if path.exists():
            receipt=dict(state='COMPLETE',games=shard['games'],completion_sha256=sha(path))
            completed_shard(shard,receipt);state['shards'][name]=receipt
        else:failed.append(name)
    write(work/'attempts'/owner['token']/'pre-recovery-status.json',saved)
    state.update(state='FAILED_PARTIAL_NO_RETRY' if failed else 'STOPPED_SAFE',recovered_at=time.time(),
                 completed_games=sum(e['games'] for e in state['shards'].values() if e['state']=='COMPLETE'),
                 interrupted_shards=failed)
    write(work/'status.json',state)
    return state


def completed_shard(shard, receipt):
    out=Path(shard['output']);require(sha(out/'completion.json')==receipt['completion_sha256'],'completed shard receipt changed')
    c=read(out/'completion.json');require(c['config_sha256']==fixed.canonical_hash(read(shard['config'])) and c['games']==shard['games'],'shard completion binding drift')
    require(c['progress_sha256']==sha(out/'progress.json'),'completed progress changed')
    progress=read(out/'progress.json');validated=validate_arena_config(read(shard['config']),shard['config'])
    rows=fixed._rows_from_progress(progress,validated)
    require(progress['config_sha256']==c['config_sha256'],'progress config drift')
    for record in progress['games'].values():
        row=record['row'];p=out/'games'/row['candidate']/row['opponent']/f"seed-{row['seed']}-seat-{row['candidate_seat']}"
        require(sha(p/'report.json')==record['report_sha256'] and sha(p/'replay.json')==record['replay_sha256'],'completed replay/report changed')
        game=read(p/'game.json');require(game['row']==row and game['status']=='completed','completed game binding drift')
        for filename in ('game.json','process-result.json','match-config.json'):
            require(sha(p/filename)==record['artifact_hashes'][filename],'completed game provenance changed: '+filename)
    return rows


def worker(config_path,output):
    config_path,output=Path(config_path).resolve(),Path(output).resolve()
    require(not output.exists(),'worker never respawns an existing shard')
    v=validate_arena_config(read(config_path),config_path);fixed.check_assets(v)
    v.update(saved_config=read(config_path),config_sha256=fixed.canonical_hash(read(config_path)))
    progress=fixed._load_progress(output,v)
    for m in v['candidates']:
        for o in v['opponents']:
            for seed in v['config']['seeds']:
                for seat in (0,1):
                    fixed._evaluate_one(v,output,m,o,seed,seat,progress)
                    p=output/'games'/m/o/f'seed-{seed}-seat-{seat}'
                    progress['games'][fixed._game_key(m,o,seed,seat)]['artifact_hashes']={
                        name:sha(p/name) for name in ('game.json','process-result.json','match-config.json')}
                    write(output/'progress.json',progress)
    rows=fixed._rows_from_progress(progress,v)
    write(output/'completion.json',dict(status='COMPLETED_NO_RETRY',config_sha256=v['config_sha256'],games=len(rows),
                                       progress_sha256=sha(output/'progress.json')))


def process_usage():
    processes=[psutil.Process(),*psutil.Process().children(recursive=True)]
    rss=cpu=0
    for p in processes:
        try:
            rss+=p.memory_info().rss;t=p.cpu_times();cpu+=t.user+t.system+getattr(t,'children_user',0)+getattr(t,'children_system',0)
        except (psutil.NoSuchProcess,psutil.AccessDenied):continue
    return dict(process_tree_rss_sum_bytes=rss,process_tree_cpu_seconds=cpu,
                observed_processes=len(processes),scope='sampled live tree plus OS-accounted waited child CPU; RSS sum may double count shared pages')


def kill_children():
    children=psutil.Process().children(recursive=True)
    for p in reversed(children):
        try:p.terminate()
        except psutil.NoSuchProcess:pass
    _,remaining=psutil.wait_procs(children,timeout=3)
    for p in remaining:
        try:p.kill()
        except psutil.NoSuchProcess:pass


def run(work,token):
    work=Path(work).resolve();plan=verify(work);attempt=work/'attempts'/token
    for _ in range(100):
        if (work/'owner.json').exists() and read(work/'owner.json').get('token')==token:break
        time.sleep(.05)
    owner=read(work/'owner.json');require(owner['pid']==os.getpid() and owner['token']==token and alive(owner),'runner ownership mismatch')
    require(owner['plan_sha256']==sha(work/'plan.json'),'plan changed at launch')
    fd=os.open(attempt/'once-only.lock',os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
    state=read(work/'status.json');state.pop('new_games',None)
    shards=state.get('shards',{});pending=[s for s in plan['shards'] if s['name'] not in shards]
    for s in plan['shards']:
        if s['name'] in shards:completed_shard(s,shards[s['name']])
    active=[];began=time.monotonic();peak=state.get('resources',{}).get('peak_observed_rss_bytes',0);last_storage=0;storage=0;signal_stop=[]
    prior_wall=state.get('elapsed_wall_seconds',0);prior_cpu=state.get('consumed_cpu_seconds',0)
    def handle_signal(number,frame):signal_stop.append(number)
    signal.signal(signal.SIGTERM,handle_signal);signal.signal(signal.SIGINT,handle_signal)
    state.update(state='RUNNING',attempt=token,started_at=state.get('started_at',time.time()),
                 attempt_started_at=time.time(),plan_sha256=owner['plan_sha256'],instance_deadline=owner.get('instance_deadline'))
    def publish():write(work/'status.json',state)
    def observe():
        nonlocal peak
        usage=process_usage();peak=max(peak,usage['process_tree_rss_sum_bytes'])
        elapsed=prior_wall+time.monotonic()-began;cpu=prior_cpu+usage['process_tree_cpu_seconds']
        state.update(resources=dict(usage,peak_observed_rss_bytes=peak),elapsed_wall_seconds=elapsed,consumed_cpu_seconds=cpu)
        require(elapsed<plan['limits']['wall_seconds'],'arena cumulative active wall budget exceeded')
        require(cpu<plan['limits']['cpu_seconds'],'arena cumulative CPU budget exceeded')
        require(usage['process_tree_rss_sum_bytes']<plan['limits']['memory_bytes'],'arena sampled RSS budget exceeded')
        require(owner.get('instance_deadline') is None or time.time()<owner['instance_deadline'],
                'instance lifetime safety deadline reached')
        return usage
    try:
        while pending or active:
            request=read(attempt/'stop.json') if (attempt/'stop.json').exists() else None
            if signal_stop or (request and request['force']):raise RuntimeError('forced stop; partial shards cannot be retried')
            usage=observe()
            if time.monotonic()-last_storage>=10:
                from scripts.prism_cloud_storage_snapshot import storage_bytes
                storage=storage_bytes(work);last_storage=time.monotonic()
            require(storage<plan['limits']['storage_bytes'],'arena storage budget exceeded')
            state.update(state='STOP_REQUESTED' if request else 'RUNNING',resources=dict(usage,peak_observed_rss_bytes=peak,storage_bytes=storage))
            while pending and not request and len(active)<plan['limits']['workers']:
                shard=pending.pop(0);name=shard['name'];shards[name]=dict(state='DISPATCHED',games=shard['games']);publish()
                log=attempt/(name+'.log');stream=log.open('wb')
                proc=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'worker','--config',shard['config'],'--output',shard['output']],
                    stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT)
                active.append((proc,shard,stream))
            for proc,shard,stream in list(active):
                code=proc.poll()
                if code is None:continue
                stream.close();active.remove((proc,shard,stream));name=shard['name']
                require(code==0,f'shard {name} failed with exit{code}; no retry; see {attempt/name}.log')
                receipt=dict(state='COMPLETE',games=shard['games'],completion_sha256=sha(Path(shard['output'])/'completion.json'))
                completed_shard(shard,receipt);shards[name]=receipt
            state['completed_games']=sum(x['games'] for x in shards.values() if x['state']=='COMPLETE');state['shards']=shards;publish()
            if request and not active:
                state.update(state='STOPPED_SAFE',finished_at=time.time());publish();return
            time.sleep(.2)
        verify(work)
        state.update(state='RUNNING',phase='REPLAY_AUDIT_AND_REPORT');publish()
        with (attempt/'report.log').open('wb') as stream:
            proc=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'report','--work',str(work)],
                                  stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT)
            while proc.poll() is None:
                request=read(attempt/'stop.json') if (attempt/'stop.json').exists() else None
                if signal_stop or (request and request['force']):raise RuntimeError('forced stop during report')
                observe()
                from scripts.prism_cloud_storage_snapshot import storage_bytes
                require(storage_bytes(work)<plan['limits']['storage_bytes'],'report storage budget exceeded')
                publish()
                time.sleep(.5)
            require(proc.returncode==0,'offline replay/report failed; completed games retained; see report.log')
        observe()
        state.update(state='COMPLETED_DEVELOPMENT_ONLY',finished_at=time.time(),elapsed_wall_seconds=prior_wall+time.monotonic()-began)
        publish();write(work/'completion.json',dict(status=state['state'],plan_sha256=sha(work/'plan.json'),
            result_sha256=sha(work/'result.json'),report_sha256=sha(work/'report.md'),html_sha256=sha(work/'report.html'),
            games=state['completed_games'],automatic_game_retries=0,model_promotion='NOT_RUN'))
    except BaseException as error:
        kill_children()
        for _,_,stream in active:stream.close()
        state.update(state='FAILED_PARTIAL_NO_RETRY',error=f'{type(error).__name__}: {error}',finished_at=time.time())
        publish();raise


def export_zip(work,output=None):
    work=Path(work).resolve();output=Path(output).resolve() if output else work.parent/(work.name+'.zip')
    require(not output.is_relative_to(work),'download archive must be outside run')
    require(not output.exists(),'refuse overwriting a previous download archive')
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(work.rglob('*')):
            if p.is_file() and not p.is_symlink():z.write(p,str(Path(work.name)/p.relative_to(work)))
    return output


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=('run','worker','report'))
    p.add_argument('--work',type=Path);p.add_argument('--token');p.add_argument('--config',type=Path);p.add_argument('--output',type=Path)
    a=p.parse_args()
    if a.mode=='worker':worker(a.config,a.output)
    elif a.mode=='report':
        from scripts import prism_notebook_report
        plan=verify(a.work);prism_notebook_report.report(a.work,plan,read(a.work/'status.json'))
    else:run(a.work,a.token)


if __name__=='__main__':main()
