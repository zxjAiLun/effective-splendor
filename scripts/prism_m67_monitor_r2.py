"""Independent local R2 observer; owner-reported shutdown retained separately."""
import json
import time
from pathlib import Path
from scripts import prism_m67_monitor as base
from training.prism_portable.common import write,digest
OUT=base.OUT/'monitor-r2'
OBSERVE='''from pathlib import Path
import json,time,psutil
r=Path(%r);rows={}
for name in ['launch.json','status.json','completion.json']:
 p=r/'continuation-r2'/name
 if p.exists():rows['pipeline/'+name]=json.loads(p.read_text())
for arm in ['a','b']:
 for folder in ['campaigns/'+arm+'/control','continuation-r2/train-'+arm]:
  p=r/folder/('live-progress.json' if folder.startswith('campaigns/') else 'status.json')
  if p.exists():rows['control/'+arm+'/status.json']=json.loads(p.read_text())
 p=r/'audits'/arm/'audit.json'
 if p.exists():rows['audits/'+arm]=json.loads(p.read_text())
for name in ['reference','a-common','a-direct','b-common','b-direct']:
 p=r/'evaluation'/name/'status.json'
 if p.exists():
  s=json.loads(p.read_text());rows['evaluation/'+name]={k:s.get(k) for k in ['state','completed_games','elapsed_wall_seconds','consumed_cpu_seconds']}
s=rows.get('pipeline/status.json',{});launch=rows.get('pipeline/launch.json',{});alive=False
identity_matches=all(s.get(k)==launch.get(k) and k in s for k in ['pid','create_time','execution_sha256','policy_sha256'])
try:
 p=psutil.Process(launch['pid']);alive=identity_matches and p.is_running() and p.status()!=psutil.STATUS_ZOMBIE and abs(p.create_time()-launch['create_time'])<.01
except (psutil.Error,KeyError):pass
print(json.dumps(dict(observed_at=time.time(),pipeline_alive=alive,identity_matches=identity_matches,rows=rows)))
''' % base.REMOTE
NATIVE_SSH=base.ssh

def ssh(code,timeout=45):
    code=code.replace("['pipeline','control','audits','docs','benchmarks']","['pipeline','continuation-r1','continuation-r2','control','audits','docs','benchmarks']").replace("r/'monitor-evidence.zip'","r/'monitor-r2-evidence.zip'")
    return NATIVE_SSH(code,timeout)


def run():
    OUT.mkdir(parents=True,exist_ok=True);base.OUT=OUT;base.ssh=ssh
    with (OUT/'monitor-once.lock').open('x'):pass
    write(OUT/'observer-source.json',dict(sha256=digest(__file__),started_at=time.time(),owner_report='2026-10-06 owner said previous observer exited because local workstation shutdown; exact time unverified'))
    deadline=time.time()+129600;errors=0
    while time.time()<deadline:
        try:
            obs=ssh(OBSERVE);write(OUT/'latest-observation.json',obs)
            with (OUT/'observation-history.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(obs,ensure_ascii=False)+'\n')
            s=obs['rows'].get('pipeline/status.json',{});state=base.run_state(obs)
            progress=[key+':'+str(row.get('completed_games',0)) for key,row in obs['rows'].items() if key.startswith(('control/','evaluation/'))]
            base.all_call('report-run',dict(agentId=base.AGENT,id='splendor:m67-repeat',projectId='splendor',taskId=base.TASK,nodeId='dsw',state=state,name='M67双训练种子扩量重复实验',kind='ppo-arena',phase='R2_'+s.get('phase','UNKNOWN'),pid=s.get('pid'),progress='实际SSH观察；'+', '.join(progress)+'；R2身份匹配='+str(obs['identity_matches'])))
            if state=='completed':
                try:write(OUT/'monitor-completion.json',base.harvest())
                except Exception as error:write(OUT/'monitor-completion.json',dict(status='HARVEST_FAILED_PENDING_MANUAL_REVIEW',error=repr(error),remote_not_restarted=True))
                return
            if state in ('failed','unknown'):
                write(OUT/'monitor-completion.json',dict(status='REMOTE_FAILED_OR_IDENTITY_UNCONFIRMED_NO_RETRY',observation=obs));return
            errors=0
        except Exception as error:
            errors+=1;write(OUT/'monitor-error.json',dict(observed_at=time.time(),error=repr(error),consecutive_errors=errors))
            if errors>=10:
                write(OUT/'monitor-completion.json',dict(status='OBSERVER_FAILED',error=repr(error),remote_not_restarted=True));return
        time.sleep(45)
    write(OUT/'monitor-completion.json',dict(status='OBSERVER_DEADLINE_EXHAUSTED',remote_not_restarted=True))


if __name__=='__main__':run()
