"""Independent M79 audit inventory adapter; retain the full checkpoint."""
import sys,json,os,time,subprocess,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from training.prism_portable.common import read,write,digest,lock
from scripts import prism_m79_completion_r24 as prior,prism_m79_completion_r21 as r21,prism_m79_run as run
REV=ROOT/'execution-revisions/completion-r28'
SELF=str(Path(__file__).resolve())
PY='/mnt/workspace/envs/splendor-m79-ppo-py312/bin/python'
def install():
    meta=read(REV/'revision.json')
    if digest(SELF)!=meta['adapter_sha256']:raise ValueError('r28 identity drift')
    from scripts import prism_m79_audit as a
    a.audit=run.adapted(a.audit,[
      ('require(set(state["model"]) == {"policy." + key for key in model.state_dict()},',
       'require(set(state["model"]) == ({"policy." + key for key in model.state_dict()} | {"style_head.0.weight","style_head.0.bias","style_head.2.weight","style_head.2.bias"}),')])
    original_self=prior.SELF
    original_verify=prior.verify
    def retained_verify():
        active=prior.SELF
        try:
            prior.SELF=original_self
            return original_verify()
        finally:prior.SELF=active
    prior.verify=retained_verify
    prior.SELF=SELF
def execute(mode,output=None):
    install()
    return prior.execute(mode,output)
def pipeline():
    install()
    return prior.pipeline()
def resume():
    prior.no_writer();r21.verify();prior.verify()
    with lock(REV/'launch-control'):
      if (REV/'launch.json').exists():raise ValueError('r28 single launch already consumed')
      st=read(ROOT/'pipeline/status.json')
      if st['state']!='STOPPED_REQUIRES_RECONCILIATION' or st['phase']!='AUDIT':raise ValueError('unexpected stage')
      rows=read(ROOT/'pipeline/resources.json')
      if any(x['state']=='RUNNING' for x in rows):raise ValueError('live resource row')
      if sum(prior.cpu(x) for x in rows if x['category']=='audit_transfer_control')>=30000:raise ValueError('audit budget exhausted')
      log=ROOT/'pipeline/audit-16.log'
      if 'committed model tensor inventory' not in log.read_text():raise ValueError('unexpected failure')
      rows.append(dict(category='audit_transfer_control',mode='completion-r27-adapter-start-failure',state='FINISHED',cpu_seconds=1.0,accounting_scope='conservative failed coordinator charge; actual CPU UNKNOWN'))
      write(ROOT/'pipeline/resources.json',rows)
      REV.mkdir(parents=True,exist_ok=True)
      for n in ('status.json','audit.completion.json','resources.json'):write(REV/('prior-'+n),read(ROOT/'pipeline'/n))
      write(REV/'revision.json',dict(adapter_sha256=digest(SELF),execution_sha256=digest(ROOT/'execution.json'),prior_audit_source_sha256=digest(ROOT/'scripts/prism_m79_audit.py'),failure_log_sha256=digest(log),scientific_change=False,launch_limit=1,observed_at=time.time()))
      with (REV/'supervisor.log').open('xb') as f:p=subprocess.Popen([PY,'-B',SELF,'pipeline'],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True)
      import psutil,platform
      rec=dict(pid=p.pid,create_time=psutil.Process(p.pid).create_time(),node=platform.node(),adapter_sha256=digest(SELF),observed_at=time.time())
      write(REV/'launch.json',rec);print(json.dumps(rec))
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('mode');p.add_argument('--output');a=p.parse_args()
    if a.mode=='resume':resume()
    elif a.mode=='pipeline':pipeline()
    else:execute(a.mode,a.output)
