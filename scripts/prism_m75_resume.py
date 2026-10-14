"""M75 owner-authorized r2: exact state resume, retained caps, no resampling.

Deploy as ROOT/continuation-r2/resume.py. Original source/config/failure receipts
stay pinned; all adaptations below belong to this separately hashed revision.
"""
import argparse
import copy
import gc
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import time
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REV = ROOT / 'continuation-r2'
POLICY = REV / 'policy.json'
from training.prism_portable.common import read, write, digest
from scripts import prism_m75_run as original
from scripts.prism_dsw_ppo_process import ProcessTree, install as process_install


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('pinned adapter target changed: ' + old[:80])
    return source.replace(old, new)


def policy():
    p = read(POLICY)
    if digest(__file__) != p['adapter_sha256']:
        raise ValueError('recovery source drift')
    if digest(ROOT/'execution.json') != p['original_execution_sha256']:
        raise ValueError('original execution drift')
    if digest(ROOT/'round-budget.json') != p['original_budget_sha256']:
        raise ValueError('original budget changed')
    return p


def remaining():
    left = policy()['deadline'] - time.time()
    if left <= 0:
        raise ValueError('finite recovery deadline exhausted')
    return left


def assert_idle():
    import psutil
    me = psutil.Process()
    excluded = {me.pid, *[p.pid for p in me.parents()]}
    for proc in psutil.process_iter(['pid', 'cmdline', 'cwd']):
        if proc.pid in excluded:
            continue
        if str(ROOT) in ' '.join(proc.info['cmdline'] or []) or (proc.info['cwd'] or '').startswith(str(ROOT)):
            raise ValueError('execution process remains active: '+str(proc.pid))


def validate_cap(spec, job, row, report, prefix, resources, *, sidecar_count, replay_exists):
    from training.prism_portable.engine.ppo.execution import verify_report
    from scripts.prism_bounded_eval import trace_metrics
    outcome = verify_report(spec, job, report)
    cap = spec['limits']['max_plies']
    if row['status'] not in ('FATAL', 'TRUNCATED') or row['job'] != job:
        raise ValueError('not a retained cap attempt')
    if resources != row['resources'] or resources['returncode'] != 0 or resources['stop_reason'] is not None:
        raise ValueError('cap process did not finish normally')
    if outcome['status'] != 'truncated' or replay_exists or 'result' in prefix:
        raise ValueError('cap must have no fabricated terminal result')
    if (prefix.get('format'), prefix.get('version'), prefix.get('seed'), prefix.get('player_count'), prefix.get('ruleset_fingerprint')) != ('splendor-rollout-prefix', 1, job['environment_seed'], 2, spec['run']['catalog_fingerprint']):
        raise ValueError('cap identity drift')
    if not (prefix['ply_cap'] == outcome['completed_plies'] == len(prefix['steps']) == cap):
        raise ValueError('cap length mismatch')
    if prefix['cap_state_hash'] != outcome['cap_state_hash'] or row.get('outcome') != outcome:
        raise ValueError('cap hash/outcome drift')
    metrics = trace_metrics(prefix)
    expected_count = sum(s['actor'] == job['actor'] for s in prefix['steps'])
    if expected_count != sidecar_count or row['charged_decisions'] != sidecar_count:
        raise ValueError('cap decision accounting drift')
    return metrics


def cap_files(campaign, number):
    _, ledger = campaign._load()
    row = ledger['attempts'][str(number)]
    directory = campaign.root/'attempts'/f'{number:03d}'
    count = sum(1 for line in (directory/'sidecar.jsonl').read_text().splitlines() if line.strip())
    metrics = validate_cap(campaign.spec, row['job'], row, read(directory/'report.json'), read(directory/'prefix.json'), read(directory/'process-result.json'), sidecar_count=count, replay_exists=(directory/'replay.json').exists())
    return {'attempt':number, 'job':row['job'], 'metrics':metrics,
            'files':{name:digest(directory/name) for name in ('report.json','prefix.json','sidecar.jsonl','process-result.json','arena-config.json')}}


def adopt_cap(campaign, number):
    from training.prism_portable.protocol import state_fingerprints
    evidence = cap_files(campaign, number)
    head, ledger = campaign._load()
    job = evidence['job']; before = state_fingerprints(campaign.run.state)
    if ledger['attempts'][str(number)]['status'] == 'TRUNCATED':
        if campaign.run.state['jobs'][job['job_id']]['status'] != 'TRUNCATED':
            raise ValueError('partially committed cap adoption')
        return evidence
    if campaign.run.state['jobs'].get(job['job_id']) != {'status':'RUNNING','attempt':number}:
        raise ValueError('cap job state mismatch')
    # Immutable original FATAL commit stays in the chain. No zeroing of work.
    with campaign.ledger.lock():
        fixed = copy.deepcopy(ledger)
        fixed['attempts'][str(number)]['status'] = 'TRUNCATED'
        fixed['attempts'][str(number)]['cap_evidence'] = evidence
        fixed['failed'] = False
        fixed['recoveries'].append({'event':'owner_authorized_retained_cap','attempt':number,'policy_sha256':digest(POLICY),'previous_commit':head,'physical_attempts_replayed':0})
        campaign.ledger.commit(fixed, expected_parent=head)
    campaign._ledger_cache = None
    with campaign.run._transaction():
        campaign.run.state['jobs'][job['job_id']] = {'status':'TRUNCATED','attempt':number,'cap_evidence':evidence}
        campaign.run.state['paused'] = False
        campaign.run.state['metrics'].append({'event':'retained_cap_excluded_from_training','cycle':campaign.run.state['cycle'],'job_id':job['job_id'],'attempt':number,'policy_sha256':digest(POLICY)})
        campaign.run._commit()
    after = state_fingerprints(campaign.run.state)
    if any(before[k] != after[k] for k in ('model','optimizer','rng')):
        raise ValueError('numeric state changed during cap adoption')
    return evidence


def resolved_jobs(state):
    statuses = [state['jobs'].get(j['job_id'],{}).get('status') for j in state['schedule']]
    if any(s not in ('COMPLETE','TRUNCATED') for s in statuses):
        raise ValueError('unresolved jobs cannot seal')
    return [j for j in state['schedule'] if state['jobs'][j['job_id']]['status'] == 'COMPLETE']


def validate_ledger(ledger, state, spec):
    if ledger['failed'] or ledger['retries'] != 0 or len(ledger['attempts']) != state['attempts']:
        raise ValueError('failed/retry/attempt ledger mismatch')
    rows = list(ledger['attempts'].values())
    jobs = [r['job']['job_id'] for r in rows]
    if len(jobs) != len(set(jobs)) or set(jobs) != set(state['all_jobs']):
        raise ValueError('missing/duplicate physical jobs')
    if any(r['status'] not in ('COMPLETE','TRUNCATED') for r in rows):
        raise ValueError('unresolved physical attempt')
    if sum(r['charged_decisions'] for r in rows) != ledger['physical_decisions'] or ledger['physical_decisions'] > spec['limits']['max_physical_decisions']:
        raise ValueError('physical work accounting mismatch')
    if any(r.get('retry_charged') for r in rows):
        raise ValueError('cap is not a replacement game')


def adapted_method(method, changes, extra=None):
    namespace = dict(method.__globals__)
    namespace.update(extra or {})
    source = textwrap.dedent(inspect.getsource(method))
    for old, new in changes:
        source = replace_once(source, old, new)
    exec(compile(source, str(REV/'resume.py')+'::'+method.__name__, 'exec'), namespace)
    return namespace[method.__name__]


def install():
    from scripts.prism_m67_storage import install as storage_install
    storage_install(); process_install()
    from training.prism_portable.engine.ppo import arena
    from training.prism_portable.engine.ppo.coordinator import Run
    p = policy()
    original.bounds = remaining
    if getattr(arena, '_m75_retained_caps', False):
        return
    native_launch = arena.Campaign.launch
    native_recover = arena.Campaign.recover_running
    def launch(self, *args, **kwargs):
        try:
            result = native_launch(self, *args, **kwargs)
        except ValueError:
            head, ledger = self._load()
            number = self.run.state['attempts']
            row = ledger['attempts'].get(str(number),{})
            if row.get('status') != 'FATAL' or row.get('outcome',{}).get('status') != 'truncated':
                raise
            adopt_cap(self, number)
            result = True
        publish_progress(self)
        return result
    def recover_running(self, job, snapshot):
        if self.run.state['jobs'].get(job['job_id'],{}).get('status') == 'TRUNCATED':
            return
        return native_recover(self, job, snapshot)
    def admit(self):
        if self.state['paused'] or self.state['phase'] == 'FAILED':
            raise ValueError('run paused/failed')
        remaining()
    Run._admit = admit
    arena.Campaign.launch = launch
    arena.Campaign.recover_running = recover_running
    arena.Campaign.work = adapted_method(arena.Campaign.work, [("!= 'COMPLETE':", "not in ('COMPLETE','TRUNCATED'):")])
    Run.seal = adapted_method(Run.seal, [
        ('if s["phase"] != "COLLECTING" or any(s["jobs"].get(j["job_id"], {}).get("status") != "COMPLETE" for j in s["schedule"]):', 'if s["phase"] != "COLLECTING":'),
        ('games = [self.store.get_json(s["jobs"][j["job_id"]]["artifact"]) for j in s["schedule"]]', 'valid = resolved_jobs(s)\n        if not valid: raise ValueError("no terminal training data in cycle")\n        games = [self.store.get_json(s["jobs"][j["job_id"]]["artifact"]) for j in valid]')], {'resolved_jobs':resolved_jobs})
    arena.Campaign.cycle_summary = adapted_method(arena.Campaign.cycle_summary, [
        ("if record['status'] != 'COMPLETE':", "if record['status'] == 'TRUNCATED': continue\n        if record['status'] != 'COMPLETE':")])
    arena._m75_retained_caps = True


def publish_progress(campaign):
    _, ledger = campaign._load()
    s = campaign.run.state
    data = {k:s[k] for k in ('phase','cycle','global_step','update_attempts','attempts')}
    data.update(observed_at=time.time(), completed_games=sum(r['status']=='COMPLETE' for r in ledger['attempts'].values()), truncated_games=sum(r['status']=='TRUNCATED' for r in ledger['attempts'].values()), policy_sha256=digest(POLICY))
    write(REV/'live-progress.json', data)


def campaign():
    from training.prism_portable.engine.ppo.arena import Campaign
    return Campaign(ROOT/'campaigns/a', read(ROOT/'campaigns/a/contract.json'))


def preflight():
    import psutil
    from training.prism_portable.processes import directory_bytes
    from training.prism_portable.protocol import state_fingerprints
    original.verify(); remaining(); assert_idle(); install()
    c = campaign(); p = policy()
    if c.run.parent != p['failed_run_commit'] or c._load()[0] != p['failed_ledger_commit']:
        raise ValueError('failure HEAD drift')
    if (c.run.state['phase'], c.run.state['paused'], c.run.state['attempts'], c.run.state['global_step']) != ('COLLECTING',True,3405,718):
        raise ValueError('unexpected recovery state')
    evidence = cap_files(c,3405)
    a_bytes = directory_bytes(c.root); total = directory_bytes(ROOT)
    projected = a_bytes / 3405 * 5120 * 1.3
    if projected > p['training_storage_bytes'] or total-a_bytes+projected+p['evaluation_storage_reserve_bytes'] > p['total_storage_bytes']:
        raise ValueError('projected storage insufficient')
    free = psutil.disk_usage(ROOT).free
    if free < p['total_storage_bytes']-total+8*1024**3:
        raise ValueError('whole disk reserve insufficient')
    proof = {'status':'PASS_ZERO_GAME_PREFLIGHT','observed_at':time.time(),'before_state':state_fingerprints(c.run.state),'cap_evidence':evidence,'run_commit':c.run.parent,'ledger_commit':c._load()[0],'capacity':{'arm_bytes':a_bytes,'total_bytes':total,'projected_training_bytes':projected,'free_bytes':free},'new_games':0}
    write(REV/'preflight.json',proof)
    return proof


def recover():
    original.verify();remaining();assert_idle();install()
    if (REV/'recovery.json').exists():raise ValueError('already recovered')
    pre=read(REV/'preflight.json');c=campaign();p=policy()
    if c.run.parent!=pre['run_commit'] or c._load()[0]!=pre['ledger_commit']:raise ValueError('HEAD changed after preflight')
    evidence=adopt_cap(c,3405)
    from training.prism_portable.protocol import state_fingerprints,state_digest
    from training.prism_portable.engine.ppo.runtime import capture_rng
    after=state_fingerprints(c.run.state)
    if any(after[k]!=pre['before_state'][k] for k in ('model','optimizer','rng')):raise ValueError('numeric recovery drift')
    if state_digest(capture_rng())!=after['rng']:raise ValueError('RNG restoration drift')
    proof={'status':'PASS_FULL_STATE_RESUME_RETAINED_CAP','state':after,'run_commit':c.run.parent,'ledger_commit':c._load()[0],'cap_evidence':evidence,'observed_at':time.time(),'normal_games_preserved':3404,'physical_attempts_preserved':3405,'new_games':0,'new_updates':0}
    write(REV/'recovery.json',proof);return proof


def worker():
    original.verify();remaining();install()
    c=campaign()
    from training.prism_portable.protocol import state_fingerprints,state_digest,assert_owner
    from training.prism_portable.engine.ppo.runtime import capture_rng
    proof=read(REV/'recovery.json')
    if c.run.parent!=proof['run_commit'] or state_fingerprints(c.run.state)!=proof['state'] or c._load()[0]!=proof['ledger_commit']:raise ValueError('exact resume identity drift')
    if state_digest(capture_rng())!=proof['state']['rng']:raise ValueError('RNG restore mismatch')
    owner=read(c.root/'ownership.json');assert_owner(c.root,read(ROOT/'host.json')['host_id'],owner['nonce'])
    os.environ.update(PRISM_PPO_HOST_ID=owner['host_id'],PRISM_PPO_OWNER_NONCE=owner['nonce'],PRISM_PPO_CONTROL_DIR=str(REV/'train'),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
    write(REV/'worker-resume-verification.json',{'status':'PASS','identity':proof,'observed_at':time.time()})
    while not (c.run.state['phase']=='COMMITTED' and c.run.state['cycle']==20):
        c.work(stop_after_cycle=True);publish_progress(c)
    s=c.run.state;_,ledger=c._load();validate_ledger(ledger,s,c.spec)
    if s['attempts']!=5120 or len(s['consumed'])!=20:raise ValueError('incomplete final training')
    completed=sum(r['status']=='COMPLETE' for r in ledger['attempts'].values());truncated=5120-completed
    export=c.root/'cycle-20-export/weights.json'
    done={'status':'STOPPED_COMMITTED','games':completed,'physical_attempts':5120,'truncated_games':truncated,'cycle':20,'global_step':s['global_step'],'update_attempts':s['update_attempts'],'weights':str(export),'weights_sha256':digest(export),'execution_sha256':digest(ROOT/'execution.json'),'continuation_policy_sha256':digest(POLICY)}
    write(c.root/'worker-completion.json',done)
    return done


def audit():
    """Same original audit, with explicit cap/accounting schema adaptation."""
    from training.prism_portable.engine.ppo.store import CommitStore
    spec=read(ROOT/'campaigns/a/contract.json')
    ledger=CommitStore(ROOT/'campaigns/a/launch-ledger',spec['run']['arena_contract_sha256']).load()[1]
    valid_games=sum(r['status']=='COMPLETE' for r in ledger['attempts'].values())
    c=campaign()
    caps=[cap_files(c,int(n)) for n,r in ledger['attempts'].items() if r['status']=='TRUNCATED']
    del c;gc.collect()
    source=(ROOT/'scripts/prism_m75_audit.py').read_text()
    changes=[
        ("completion['completed_games']!=expected_games", "completion['completed_games']!=valid_games or completion['completion']['physical_attempts']!=expected_games"),
        ("'games':expected_games", "'games':valid_games,'physical_attempts':expected_games,'truncated_games':len(caps)"),
        ("'completed_games':expected_games", "'completed_games':valid_games,'physical_attempts':expected_games,'truncated_games':len(caps)"),
        ("if item['status']!='COMPLETE':raise ValueError('noncomplete attempt')", "if item['status']=='TRUNCATED':continue\n        if item['status']!='COMPLETE':raise ValueError('noncomplete attempt')"),
        ("if len(sources)!=expected_games:", "if len(sources)!=valid_games:"),
        ("f'{expected_games}局、{cycles}周期。'", "f'{expected_games}物理尝试、{valid_games}正常终局、{len(caps)}截断，{cycles}周期。'"),
        ("f'all {expected_games} saved replays", "f'all {valid_games} saved terminal replays")]
    for old,new in changes:source=replace_once(source,old,new)
    import training.prism_portable.protocol as protocol
    protocol.validate_launch_ledger=validate_ledger
    ns={'__file__':str(ROOT/'scripts/prism_m75_audit.py'),'__name__':'m75_recovery_audit','valid_games':valid_games,'caps':caps}
    exec(compile(source,str(REV/'resume.py')+'::audit','exec'),ns)
    result=ns['audit']('a')
    result['continuation']={'policy_sha256':digest(POLICY),'adapter_sha256':digest(__file__),'original_failed_pipeline_retained':True,'physical_attempts':5120,'terminal_training_games':valid_games,'truncated_games':len(caps),'caps':caps,'full_state_resume':read(REV/'worker-resume-verification.json')}
    write(ROOT/'audits/a/audit.json',result);return result


def child(mode):
    training=mode in ('train','audit')
    original.verify(training=training);remaining()
    if training:install()
    else:original.bounds=remaining
    if mode=='train':return worker()
    if mode=='audit':return audit()
    from scripts import prism_m75_evaluate as evaluation
    native_read=evaluation.read
    def revised_read(path):
        value=native_read(path)
        if Path(path).resolve()==(ROOT/'round-budget.json').resolve():
            value=dict(value,deadline=policy()['deadline'],continuation_policy_sha256=digest(POLICY))
        return value
    evaluation.read=revised_read
    if mode=='curve':
        from scripts.prism_m75_curve import build
        return build()
    if mode in ('candidates','evaluate'):return getattr(evaluation,mode)()
    if mode=='report':
        from scripts import prism_m75_report as report
        source=Path(report.__file__).read_text()
        source=replace_once(source,"headline='新增5120局后，比较最终c20与直接父代Balance v0.2.3。'","headline='完成5120次训练尝试后，比较最终c20与直接父代Balance v0.2.3；截断保留并排除胜负训练。'")
        source=replace_once(source,"explanation='20周期、5120训练局，全部中间导出保留。'","explanation='20周期、5120物理尝试；正常终局与截断数见训练审计，全部中间导出保留。'")
        ns={'__name__':'m75_recovery_report','__file__':report.__file__}
        exec(compile(source,str(REV/'resume.py')+'::report','exec'),ns)
        result=ns['build']()
        write(REV/'report-execution-binding.json',{'original_execution_sha256':digest(ROOT/'execution.json'),'policy_sha256':digest(POLICY),'adapter_sha256':digest(__file__),'audit_sha256':digest(ROOT/'audits/a/audit.json'),'result_sha256':result['result_sha256']})
        return result
    raise ValueError('unknown stage')


def stage(mode,cpu_left):
    from training.prism_portable.processes import directory_bytes
    p=policy();out=REV/mode;out.mkdir(exist_ok=False)
    py=original.contract()['runtime']['arena_python'] if mode in ('curve','evaluate','report','candidates') else sys.executable
    wall=min(remaining(),p['remaining_training_active_wall_seconds'] if mode=='train' else remaining())
    cpu=min(cpu_left,p['remaining_training_cpu_seconds'] if mode=='train' else cpu_left)
    os.environ.update(PRISM_PPO_CONTROL_DIR=str(out),PRISM_DSW_REMAINING_WALL=str(wall),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
    last=[0.]
    def stop_total():
        if time.monotonic()<last[0]:return None
        last[0]=time.monotonic()+60
        return 'whole_round_storage_limit' if directory_bytes(ROOT)>p['total_storage_bytes'] else None
    def snapshot(counters):
        row={'state':'RUNNING','phase':mode,'resources':counters,'observed_at':time.time(),'policy_sha256':digest(POLICY)}
        if mode=='train' and (REV/'live-progress.json').exists():row.update(read(REV/'live-progress.json'))
        write(out/'status.json',row)
    with (out/'stdout.log').open('xb') as stdout,(out/'stderr.log').open('xb') as stderr:
        with ProcessTree(cpu_seconds=cpu,memory_bytes=8*1024**3,max_processes=64) as tree:
            tree.start([py,'-B',str(Path(__file__).resolve()),'child','--stage',mode],cwd=ROOT,stdout=stdout,stderr=stderr)
            resources=tree.wait(wall_seconds=wall,storage_root=ROOT/'campaigns/a' if mode=='train' else ROOT,max_storage_bytes=p['training_storage_bytes'] if mode=='train' else p['total_storage_bytes'],storage_interval=60,stop_checker=stop_total,snapshot=snapshot)
    done={'state':'PASS' if resources['returncode']==0 and not resources['stop_reason'] else 'FAILED','resources':resources,'finished_at':time.time()}
    write(out/'completion.json',done)
    if done['state']!='PASS':raise ValueError('recovery stage failed '+mode+': '+str(resources))
    if mode=='train':
        dest=ROOT/'control/a/completion.json'
        if dest.exists():raise ValueError('completion already exists')
        complete=read(ROOT/'campaigns/a/worker-completion.json')
        write(dest,{'state':'STOPPED_COMMITTED','completed_games':complete['games'],'completion':complete,'resources':resources,'finished_at':time.time(),'continuation_policy_sha256':digest(POLICY)})
    return done


def pipeline():
    import psutil
    original.verify();remaining()
    with (REV/'pipeline-once.lock').open('x'):pass
    p=policy();me=psutil.Process()
    s={'state':'RUNNING','phase':'RESUME_TRAIN','pid':me.pid,'create_time':me.create_time(),'started_at':time.time(),'execution_sha256':digest(POLICY),'original_execution_sha256':digest(ROOT/'execution.json'),'consumed_cpu_seconds':p['consumed_cpu_seconds'],'deadline':p['deadline']}
    def publish(**fields):s.update(fields,observed_at=time.time());write(REV/'status.json',s)
    try:
        for mode in ('train','audit','candidates','curve','evaluate','report'):
            original.verify();remaining();publish(phase=mode)
            left=p['total_cpu_seconds']-s['consumed_cpu_seconds']
            if left<=0:raise ValueError('whole-round CPU exhausted')
            result=stage(mode,left)
            s['consumed_cpu_seconds']+=result['resources']['cpu_seconds'];publish()
        publish(state='COMPLETED',phase='RESULTS_AND_REPORTS_READY',finished_at=time.time());write(REV/'completion.json',s)
    except BaseException as error:
        publish(state='FAILED',error=repr(error),finished_at=time.time());raise
    return s


def start():
    import psutil
    original.verify();remaining();assert_idle();install()
    c=campaign();proof=read(REV/'recovery.json')
    if c.run.parent!=proof['run_commit'] or c._load()[0]!=proof['ledger_commit']:raise ValueError('resume HEAD drift')
    del c;gc.collect()
    with (REV/'launch-once.lock').open('x'):pass
    with (REV/'supervisor.log').open('xb') as log:
        proc=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'pipeline'],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    receipt={'status':'STARTED_AUTHORIZED_M75_RECOVERY_R2','pid':proc.pid,'create_time':psutil.Process(proc.pid).create_time(),'execution_sha256':digest(POLICY),'original_execution_sha256':digest(ROOT/'execution.json'),'deadline':policy()['deadline'],'remaining_physical_attempts':1715,'automatic_retries':0}
    write(REV/'launch.json',receipt);return receipt


if __name__=='__main__':
    if sys.platform.startswith('linux'):os.sched_setaffinity(0,[0,1,2,3])
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('preflight','recover','start','pipeline','child'))
    parser.add_argument('--stage',choices=('train','audit','candidates','curve','evaluate','report'))
    args=parser.parse_args()
    print(json.dumps(child(args.stage) if args.mode=='child' else globals()[args.mode](),ensure_ascii=False))
