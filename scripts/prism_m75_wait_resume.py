"""M75 r5 resumes only the completed-development wait after DSW2 replacement."""
import importlib.util,json,os,sys,time,zipfile,hashlib
from pathlib import Path
import psutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
REV=ROOT/'wait-resume-r5'
from training.prism_portable.common import read,write,digest

def validate_completed(stage,done):
    if stage['state']!='PASS' or stage['resources']['returncode']!=0 or stage['resources']['stop_reason']:
        raise ValueError('early stage not successful')
    if done['completed_games']!=768 or done['truncated_games']!=0 or len(done['shards'])!=12:
        raise ValueError('early development grid changed')
    if len({s['label'] for s in done['shards']})!=12 or sum(s['planned_games'] for s in done['shards'])!=768:
        raise ValueError('duplicate/missing early shards')
    return stage['resources']['cpu_seconds']

def controller():
    b=read(REV/'policy.json')
    if digest(__file__)!=b['adapter_sha256']:raise ValueError('wait recovery source drift')
    for rel,h in b['files'].items():
        if digest(ROOT/rel)!=h:raise ValueError('wait recovery input drift: '+rel)
    spec=importlib.util.spec_from_file_location('m75_r4_wait_resume',ROOT/'eval-handoff-r4/controller.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.policy()
    return m,b

def preflight():
    m,b=controller();os.sched_setaffinity(0,range(8));m.verify_arena()
    old=read(ROOT/'eval-handoff-r4/launch.json')
    try:
        p=psutil.Process(old['pid'])
        if abs(p.create_time()-old['create_time'])<.01 and p.status()!=psutil.STATUS_ZOMBIE:raise ValueError('old coordinator still live')
    except psutil.NoSuchProcess:pass
    for proc in psutil.process_iter(['pid','cmdline']):
        if proc.pid!=os.getpid() and any(str(ROOT) in a for a in (proc.info['cmdline'] or [])):
            raise ValueError('execution process still active: '+str(proc.pid))
    stage=read(ROOT/'eval-handoff-r4/early-development/completion.json');done=read(ROOT/'eval-handoff-r4/early-development-completion.json')
    cpu=validate_completed(stage,done)
    from scripts import prism_bounded_eval as bounded
    for shard in done['shards']:
        dest=Path(shard['output']);grid=bounded.inspect(dest)
        if digest(dest/'manifest.json')!=shard['manifest_sha256'] or grid['execution_state']!='FINISHED' or grid['completed_games']!=64 or grid['truncated_games']!=0:raise ValueError('early saved grid drift')
    if (ROOT/'eval-handoff-r4/final-evaluation').exists() or (ROOT/'evaluation-plan.json').exists():raise ValueError('later evaluation already attempted; cannot use waiting-only recovery')
    if (ROOT/'candidate-registry.json').exists():raise ValueError('final input already imported')
    proof=dict(state='PASS_WAIT_ONLY_RESUME_ZERO_NEW_GAMES',observed_at=time.time(),hostname=os.uname().nodename,old_hostname=b['old_hostname'],original_early_cpu_seconds=cpu,retained_development_games=768,retained_baseline_attempts=4096,pinned_files=len(read(ROOT/'execution.json')['files']),deadline=m.policy()['deadline'],source_sha256=digest(__file__),policy_sha256=digest(REV/'policy.json'))
    write(REV/'preflight.json',proof);return proof

def run(token):
    m,b=controller();m.TOKEN=token;os.sched_setaffinity(0,range(8))
    native_extract=m.extract_bound;native_stage=m.stage
    def extract(archive,receipt,allowed):
        if Path(archive).resolve()==(ROOT/'eval-handoff-r4/early-input.zip').resolve():
            if digest(archive)!=receipt['sha256']:raise ValueError('retained early archive changed')
            with zipfile.ZipFile(archive) as z:
                members=json.loads(z.read('transfer-manifest.json'))
                for rel,h in members.items():
                    if not allowed(rel) or digest(ROOT/rel)!=h:raise ValueError('retained early export mismatch')
            return members
        return native_extract(archive,receipt,allowed)
    def stage(mode,cpu_left,node):
        if mode=='early-development':return validate_completed(read(ROOT/'eval-handoff-r4/early-development/completion.json'),read(ROOT/'eval-handoff-r4/early-development-completion.json'))
        return native_stage(mode,cpu_left,node)
    m.extract_bound=extract;m.stage=stage
    write(REV/'status.json',dict(state='RUNNING_RESUMED_WAIT',pid=os.getpid(),create_time=psutil.Process().create_time(),observed_at=time.time(),retained_development_games=768,deadline=m.policy()['deadline']))
    try:m.run('dsw2')
    except BaseException as error:
        write(REV/'failure.json',dict(state='FAILED',error_type=type(error).__name__,observed_at=time.time()));raise
    write(REV/'completion.json',dict(state='PASS_RESUMED_PIPELINE_FINISHED',finished_at=time.time()))

if __name__=='__main__':print(json.dumps(preflight()))
