"""Local M67 observer/harvester. No remote start/resume/retry or model release.

Actual SSH observations heartbeat ALL every minute while this process is alive.
On completion harvest fixed evidence, verify member hashes and result/contract,
then mark the task review (not done: local full-statistics/visual closeout remains).
Requires this workstation and ALL; remote finite pipeline is independent.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from training.prism_portable.common import read,write,digest
REMOTE='/mnt/workspace/splendor-m67-alpha-repeat'
OUT=ROOT/'local-artifacts/prism/m67-alpha-repeat'
AGENT='pi:81c2df41-350d-4f4f-997d-16e9e5ce922a'
TASK='926f1b3a-db9d-49c8-a834-c2fc57d6b9b4'
CLI=Path('E:/AUbuntuProject/project/All/scripts/agent-client.mjs')

def ssh(code, timeout=45):
    x=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=15','dsw','/mnt/workspace/envs/splendor-arena-py312/bin/python','-B','-'],input=code,capture_output=True,text=True,encoding='utf-8',timeout=timeout)
    if x.returncode:raise RuntimeError('SSH observation failed: '+x.stderr[-2000:])
    return json.loads(x.stdout)

def all_call(command,value):
    folder=OUT/'monitor-api';folder.mkdir(exist_ok=True)
    target=folder/(command+'-input.json');write(target,value)
    x=subprocess.run(['node',str(CLI),command,'--input',str(target)],capture_output=True,text=True,encoding='utf-8',timeout=25)
    write(folder/(command+'-receipt.json'),{'exit':x.returncode,'stdout':x.stdout,'stderr':x.stderr,'observed_at':time.time()})
    if x.returncode:raise RuntimeError('ALL reporting failed: '+x.stderr[-1000:])
    return json.loads(x.stdout)

OBSERVE='''from pathlib import Path
import json,time,psutil
r=Path(%r);rows={}
for name in ['pipeline/launch.json','pipeline/status.json','pipeline/completion.json','control/engineering/status.json','audits/engineering/audit.json','control/a/status.json','control/b/status.json','audits/a/audit.json','audits/b/audit.json']:
 p=r/name
 if p.exists():rows[name]=json.loads(p.read_text())
for name in ['reference','a-common','a-direct','b-common','b-direct']:
 p=r/'evaluation'/name/'status.json'
 if p.exists():
  s=json.loads(p.read_text());rows['evaluation/'+name]={k:s.get(k) for k in ['state','completed_games','elapsed_wall_seconds','consumed_cpu_seconds']}
s=rows.get('pipeline/status.json',{});launch=rows.get('pipeline/launch.json',{});alive=False
identity_matches=all(s.get(k)==launch.get(k) and k in s for k in ['pid','create_time','execution_sha256'])
try:
 p=psutil.Process(launch['pid']);alive=identity_matches and p.is_running() and p.status()!=psutil.STATUS_ZOMBIE and abs(p.create_time()-launch['create_time'])<.01
except (psutil.Error,KeyError):pass
print(json.dumps(dict(observed_at=time.time(),pipeline_alive=alive,identity_matches=identity_matches,rows=rows)))
''' % REMOTE

def run_state(observation):
    s=observation['rows'].get('pipeline/status.json',{})
    state=s.get('state','UNKNOWN')
    if not observation.get('identity_matches'):return 'unknown'
    if state=='COMPLETED':
        done=observation['rows'].get('pipeline/completion.json',{})
        return 'completed' if done==s else 'unknown'
    if state.startswith('FAILED') or not observation['pipeline_alive']:return 'failed'
    return 'running'

def harvest():
    context_receipt=subprocess.run(['node',str(CLI),'context','splendor'],capture_output=True,text=True,encoding='utf-8',timeout=25)
    if context_receipt.returncode:raise RuntimeError('ALL context before harvest failed')
    context=json.loads(context_receipt.stdout)
    if not any(t['id']==TASK for t in context['tasks']):raise ValueError('ALL task missing')
    code='''from pathlib import Path
import json,hashlib,zipfile
r=Path(%r);files={}
for name in ['execution.json','host.json','round-budget.json','storage-calibration.json','linux-targeted.receipt.json','preflight.receipt.json']:
 p=r/name
 if p.exists():files[name]=p
for folder in ['pipeline','control','audits','docs','benchmarks']:
 for p in (r/folder).rglob('*'):
  if p.is_file():files[p.relative_to(r).as_posix()]=p
for arm in ['a','b']:
 for p in (r/'campaigns'/arm).glob('*.json'):files[p.relative_to(r).as_posix()]=p
 for p in (r/'campaigns'/arm/'cycle-20-export').glob('*'):
  if p.is_file():files[p.relative_to(r).as_posix()]=p
for name in ['reference','a-common','a-direct','b-common','b-direct']:
 for p in (r/'evaluation'/name).glob('*'):
  if p.is_file():files[p.relative_to(r).as_posix()]=p
 for p in (r/'evaluation'/name/'shards').rglob('*'):
  if p.is_file() and p.name in ['progress.json','completion.json']:files[p.relative_to(r).as_posix()]=p
manifest={n:{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size} for n,p in files.items()}
p=r/'monitor-evidence.zip'
with zipfile.ZipFile(p,'x',zipfile.ZIP_DEFLATED) as z:
 for n,f in files.items():z.write(f,n)
 z.writestr('harvest-manifest.json',json.dumps(manifest,sort_keys=True,indent=2))
print(json.dumps(dict(archive=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),files=len(files))))
''' % REMOTE
    receipt=ssh(code,timeout=300);write(OUT/'remote-harvest.json',receipt)
    archive=OUT/'monitor-evidence.zip'
    x=subprocess.run(['scp','-o','BatchMode=yes','-o','ConnectTimeout=15','dsw:'+receipt['archive'],str(archive)],capture_output=True,text=True,timeout=120)
    if x.returncode:raise RuntimeError('SCP failed: '+x.stderr)
    if digest(archive)!=receipt['sha256']:raise ValueError('archive SHA mismatch')
    dest=OUT/'harvest';dest.mkdir(exist_ok=False)
    with zipfile.ZipFile(archive) as z:
        manifest=json.loads(z.read('harvest-manifest.json'))
        for name,meta in manifest.items():
            if not (dest/name).resolve().is_relative_to(dest.resolve()):raise ValueError('archive path')
            data=z.read(name)
            if len(data)!=meta['bytes'] or hashlib.sha256(data).hexdigest()!=meta['sha256']:raise ValueError('member hash mismatch')
        z.extractall(dest)
    result=read(dest/'benchmarks/m67-prism-alpha-repeat.result.json')
    if result['games']!=110000 or result['source_config_sha256']!=digest(ROOT/'benchmarks/m67-prism-alpha-repeat.config.json'):raise ValueError('result/contract binding mismatch')
    summary={'status':'HARVEST_HASHES_PASS_PENDING_LOCAL_REVIEW','archive_sha256':digest(archive),'files':len(manifest),'games':result['games'],
             'remaining':'Local bootstrap recomputation, readable local source links and rendered report review; saved shard progress/completion included, full raw replay/checkpoint remains remote', 'observed_at':time.time()}
    write(OUT/'monitor-harvest-verification.json',summary)
    for path,title in [('monitor-harvest-verification.json','M67自动取回SHA核验'),('harvest/benchmarks/m67-prism-alpha-repeat.result.json','M67固定110000局双候选结果')]:
        all_call('register-artifact',{'agentId':AGENT,'projectId':'splendor','taskId':TASK,'path':(OUT/path).relative_to(ROOT).as_posix(),'title':title,'status':'HARVESTED_PENDING_LOCAL_REVIEW'})
    x=subprocess.run(['node',str(CLI),'context','splendor'],capture_output=True,text=True,encoding='utf-8',timeout=25)
    if x.returncode:raise RuntimeError('ALL context failed')
    context=json.loads(x.stdout);task=next(t for t in context['tasks'] if t['id']==TASK)
    all_call('update-task',{'agentId':AGENT,'taskId':TASK,'expectedRevision':task['revision'],'lane':'review',
        'result':{'summary':'DSW有限双训练/固定110000双方greedy与报告已完成，自动取回逐文件SHA通过。尚待本地统计复算/阅读来源链接与实际像素核验；完整原回放/恢复状态留远端。',
                  'evidence':[(OUT/'monitor-harvest-verification.json').relative_to(ROOT).as_posix(),(OUT/'harvest/benchmarks/m67-prism-alpha-repeat.result.json').relative_to(ROOT).as_posix()]}})
    return summary

def run():
    OUT.mkdir(parents=True,exist_ok=True)
    with (OUT/'monitor-once.lock').open('x'):pass
    started=time.time();deadline=started+90000;errors=0
    while time.time()<deadline:
        try:
            observation=ssh(OBSERVE);write(OUT/'latest-observation.json',observation)
            with (OUT/'observation-history.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(observation,ensure_ascii=False)+'\n')
            s=observation['rows'].get('pipeline/status.json',{});state=s.get('state','UNKNOWN');phase=s.get('phase','UNKNOWN')
            progress=[]
            for key,row in observation['rows'].items():
                if key.startswith('control/') or key.startswith('evaluation/'):progress.append(key+':'+str(row.get('completed_games',0)))
            observed_state=run_state(observation)
            all_call('report-run',{'agentId':AGENT,'id':'splendor:m67-repeat','projectId':'splendor','taskId':TASK,'nodeId':'dsw',
                'state':observed_state,'name':'M67双训练种子扩量重复实验','kind':'ppo-arena','phase':phase,'pid':s.get('pid'),
                'progress':'实际SSH观察；'+', '.join(progress)+'; pipeline '+state})
            if observed_state=='completed':
                try:
                    final=harvest();write(OUT/'monitor-completion.json',final)
                except Exception as error:
                    write(OUT/'monitor-completion.json',{'status':'HARVEST_FAILED_PENDING_MANUAL_REVIEW','error':repr(error),'remote_not_restarted':True})
                return
            if observed_state in ('failed','unknown'):
                write(OUT/'monitor-completion.json',{'status':'REMOTE_FAILED_OR_IDENTITY_UNCONFIRMED_NO_RETRY','observation':observation});return
            errors=0
        except Exception as error:
            errors+=1;write(OUT/'monitor-error.json',{'observed_at':time.time(),'error':repr(error),'consecutive_errors':errors})
            if errors>=10:
                write(OUT/'monitor-completion.json',{'status':'OBSERVER_FAILED','error':repr(error),'remote_not_restarted':True});return
        time.sleep(45)
    write(OUT/'monitor-completion.json',{'status':'OBSERVER_DEADLINE_EXHAUSTED','remote_not_restarted':True})

if __name__=='__main__':
    argparse.ArgumentParser(description=__doc__).parse_args();run()
