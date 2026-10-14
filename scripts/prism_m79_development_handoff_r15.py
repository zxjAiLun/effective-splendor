"""Finite c5/c10/c15 transfer dependency on server1; no training monitoring/service."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
STOP = 1791833400.0  # New user 7h50 window; conservative 2026-10-13 03:30 +08.
MAIN = '/mnt/workspace/splendor-m79-mainline-r4'
AUX = '/mnt/workspace/splendor-m79-aux-r1'


def save(**value):
    value.update(observed_at=time.time(), pid=os.getpid(), operational_stop=STOP)
    temp = HERE / 'status.tmp'
    temp.write_text(json.dumps(value, indent=2) + '\n')
    temp.replace(HERE / 'status.json')


def ssh(port, source, *, timeout=90):
    if time.time() >= STOP:
        raise ValueError('finite auxiliary operational deadline reached')
    p = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
        '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2',
        '-p', str(port), 'root@127.0.0.1', 'python3 -B -'],
        input=source, text=True, capture_output=True, timeout=timeout)
    if p.returncode:
        raise ValueError('remote operation failed port=' + str(port) + ': ' + p.stderr[-2500:])
    return json.loads(p.stdout.splitlines()[-1])


def result_ready(cycle):
    directory = 'aux-development-r12' if cycle == 5 else f'aux-development-r13-c{cycle}'
    return ssh(2223, f"from pathlib import Path\nimport json\np=Path({AUX!r})/'execution-revisions'/{directory!r}\nprint(json.dumps(dict(ready=(p/'results.receipt.json').exists(),resource=json.loads((p/'resource.json').read_text()) if (p/'resource.json').exists() else None)))\n")


def import_result(cycle):
    directory = 'aux-development-r12' if cycle == 5 else f'aux-development-r13-c{cycle}'
    payload = ssh(2223, f"from pathlib import Path\nimport json,base64\np=Path({AUX!r})/'execution-revisions'/{directory!r}\nprint(json.dumps(dict(receipt=json.loads((p/'results.receipt.json').read_text()),bundle=getattr(base64, 'b64'+'encode')((p/'results.zip').read_bytes()).decode())))\n", timeout=120)
    blob = base64.b64decode(payload['bundle'])
    if hashlib.sha256(blob).hexdigest() != payload['receipt']['sha256']:
        raise ValueError('auxiliary result transport SHA mismatch')
    (HERE / f'c{cycle}-results.zip').write_bytes(blob)
    (HERE / f'c{cycle}-receipt.json').write_text(json.dumps(payload['receipt'], indent=2) + '\n')
    source = 'PAYLOAD=' + repr(json.dumps(payload)) + '\nCYCLE=' + repr(cycle) + '\n' + r'''
import base64,json,hashlib,io,zipfile,sys,time
from pathlib import Path
r=Path('/mnt/workspace/splendor-m79-mainline-r4');sys.path.insert(0,str(r));x=json.loads(PAYLOAD)
out=r/'execution-revisions'/('aux-development-r12' if CYCLE==5 else f'aux-development-r13-c{CYCLE}')
done=out/'import.json'
if done.exists():print(done.read_text().replace('\n',' '));sys.exit(0)
raw=base64.b64decode(x['bundle']);assert hashlib.sha256(raw).hexdigest()==x['receipt']['sha256']
archive=out/'results.zip';archive.write_bytes(raw);(out/'results.receipt.json').write_text(json.dumps(x['receipt'],indent=2)+'\n')
from scripts import prism_m79_dual_dispatch as dual,prism_m79_import_r2 as imp
b,e,_=dual._runtime(r)
canon=imp.replace(dual._canonicalize_imported_shard,[
 ('if semantic_config(config, root) != semantic_config(expected_cfg, root):',"source_root=Path(config['engine']['program']).parent.parent\n    if semantic_config(config, source_root) != semantic_config(expected_cfg, root):"),
 ('validated = b.arena.validate_arena_config(expected_cfg, expected_config_path)',"for name in ('config.json','policy.json','manifest.json','ledger.json'):\n        old=out/name\n        saved=out/('aux-original-'+name)\n        if old.exists() and not saved.exists():saved.write_bytes(old.read_bytes())\n    write_json(config_path,expected_cfg)\n    validated = b.arena.validate_arena_config(expected_cfg, expected_config_path)")])
with zipfile.ZipFile(io.BytesIO(raw)) as z:
 if set(z.namelist())!=set(x['receipt']['files']):raise ValueError('delivery member set changed')
 for n,info in x['receipt']['files'].items():
  dual.safe_member(n);v=z.read(n)
  if len(v)!=info['bytes'] or hashlib.sha256(v).hexdigest()!=info['sha256']:raise ValueError('delivery member SHA drift')
  dest=out/'original-results'/n;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(v)
  if n.startswith('evaluation/'):
   parts=Path(n).parts;label=parts[1]
   if label not in x['receipt']['labels']:raise ValueError('unexpected result label')
   target=r/n;target.parent.mkdir(parents=True,exist_ok=True)
   if target.exists() and parts[-1] not in ('config.json','policy.json','manifest.json') and target.read_bytes()!=v:raise ValueError('existing main evidence would be overwritten')
   target.write_bytes(v)
for label in x['receipt']['labels']:canon(r,label,b,e)
counts=[b.inspect(r/'evaluation'/label) for label in x['receipt']['labels']]
if sum(v['completed_games']+v['truncated_games'] for v in counts)!=256:raise ValueError('import grid incomplete')
cpu=x['receipt']['resources']['resources']['cpu_seconds']
if x['receipt']['resources']['status']!='PASS' or not 0<=cpu<=4000:raise ValueError('auxiliary development CPU receipt invalid')
resource=r/'execution-revisions/dual-dispatch-r1/aux-resource.json';current=json.loads(resource.read_text())
(out/'aux-resource-before-import.json').write_bytes(resource.read_bytes())
previous=2313.151749
for old_cycle in (5,10):
 if old_cycle<CYCLE:
  d='aux-development-r12' if old_cycle==5 else f'aux-development-r13-c{old_cycle}'
  previous+=json.loads((r/'execution-revisions'/d/'import.json').read_text())['cpu_seconds']
current.update(cpu_seconds=previous+cpu,additional_development_cpu_seconds=previous+cpu-2313.151749,additional_reservation=None,auxiliary_development_evidence=str(done),original_aux_cpu_seconds=2313.151749)
resource.write_text(json.dumps(current,indent=2)+'\n')
result=dict(status='PASS_SHA_BOUND_DEVELOPMENT_IMPORT',cycle=CYCLE,games=sum(v['completed_games'] for v in counts),truncated_games=sum(v['truncated_games'] for v in counts),cpu_seconds=cpu,combined_external_eval_cpu_seconds=previous+cpu,archive_sha256=x['receipt']['sha256'],labels=x['receipt']['labels'],new_games_on_import=0,observed_at=time.time())
done.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
'''
    result = ssh(2222, source, timeout=300)
    (HERE / f'c{cycle}-import.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def prepare_checkpoint(cycle):
    source = r'''
import json,time,sys,zipfile,io,base64,hashlib
from pathlib import Path
r=Path('/mnt/workspace/splendor-m79-mainline-r4');p=r/'campaigns/a/cycle-10-export/weights.json'
if not p.exists():print(json.dumps(dict(ready=False)));sys.exit(0)
sys.path.insert(0,str(r));from scripts import prism_m79_evaluate as e
from scripts.prism_m79_run import verify
verify();c=json.loads((r/e.PLAN).read_text());lo,hi=c['development']['seed_range'];rows=[]
for start in range(lo,hi+1,32):
 label=f'development-curve-c10-parent-{start}';rows.append(e.freeze(label,e.config('curve-c10','parent',list(range(start,min(start+32,hi+1))),True),'development'))
out=r/'execution-revisions/aux-development-r13-c10';out.mkdir(exist_ok=True)
res=r/'execution-revisions/dual-dispatch-r1/aux-resource.json';value=json.loads(res.read_text())
if not (out/'dispatch.json').exists():
 (out/'aux-resource-before-reservation.json').write_bytes(res.read_bytes());value.update(cpu_seconds=value['cpu_seconds']+4000,additional_reservation=dict(revision='aux-development-r13-c10',cpu_seconds=4000,state='RESERVED'));res.write_text(json.dumps(value,indent=2)+'\n')
names=['campaigns/a/cycle-10-export/weights.json']+[f'evaluation-configs/{x["label"]}'+s for x in rows for s in ('.json','.policy.json')];blob=io.BytesIO()
with zipfile.ZipFile(blob,'w',zipfile.ZIP_DEFLATED) as z:
 for n in names:z.write(r/n,n)
raw=blob.getvalue();manifest=dict(format='prism-m79-aux-development-r13-c10',source_root=str(r),execution_sha256=hashlib.sha256((r/'execution.json').read_bytes()).hexdigest(),plan_sha256=hashlib.sha256((r/e.PLAN).read_bytes()).hexdigest(),rows=rows,cpu_limit=4000,original_aux_cpu=2313.151749,operational_stop=1791813600.0,deadline=json.loads((r/'round-budget.json').read_text())['deadline'],files={n:hashlib.sha256((r/n).read_bytes()).hexdigest() for n in names},bundle_sha256=hashlib.sha256(raw).hexdigest(),bundle_bytes=len(raw),observed_at=time.time())
(out/'dispatch.json').write_text(json.dumps(manifest,indent=2)+'\n');(out/'inputs.zip').write_bytes(raw)
print(json.dumps(dict(ready=True,manifest=manifest,bundle=getattr(base64, 'b64'+'encode')(raw).decode())))
'''
    source = source.replace('cycle-10',f'cycle-{cycle}').replace('curve-c10',f'curve-c{cycle}').replace('r13-c10',f'r13-c{cycle}').replace('1791813600.0',repr(STOP))
    payload = ssh(2222, source, timeout=120)
    if not payload['ready']:
        return False
    payload['script'] = getattr(base64, 'b64'+'encode')((HERE / 'aux-development-r13.py').read_bytes()).decode()
    source = 'PAYLOAD=' + repr(json.dumps(payload)) + '\n' + r'''
import json,base64,hashlib,zipfile,subprocess,os,time,psutil,platform
from pathlib import Path
x=json.loads(PAYLOAD);r=Path('/mnt/workspace/splendor-m79-aux-r1');out=r/'execution-revisions/aux-development-r13-c10';out.mkdir(exist_ok=False)
raw=base64.b64decode(x['bundle']);assert hashlib.sha256(raw).hexdigest()==x['manifest']['bundle_sha256'];(out/'inputs.zip').write_bytes(raw);(out/'dispatch.json').write_text(json.dumps(x['manifest'],indent=2)+'\n')
with zipfile.ZipFile(out/'inputs.zip') as z:
 for n,h in x['manifest']['files'].items():
  b=z.read(n);assert hashlib.sha256(b).hexdigest()==h;p=out/'original-inputs'/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b);dest=r/n;dest.parent.mkdir(parents=True,exist_ok=True)
  if n.startswith('evaluation-configs/') and not n.endswith('.policy.json'):
   def replace(v):
    if isinstance(v,str):return v.replace(x['manifest']['source_root'],str(r))
    if isinstance(v,list):return [replace(t) for t in v]
    if isinstance(v,dict):return {k:replace(t) for k,t in v.items()}
    return v
   b=(json.dumps(replace(json.loads(b)),indent=2)+'\n').encode()
  if dest.exists():assert dest.read_bytes()==b
  else:dest.write_bytes(b)
p=r/'scripts/prism_m79_aux_development_r13.py';data=base64.b64decode(x['script'])
if p.exists():assert p.read_bytes()==data
else:p.write_bytes(data)
env=os.environ.copy();env.update(PRISM_M79_DEVELOPMENT_CYCLE='10',PYTHONPATH=str(r),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1');py='/mnt/workspace/envs/splendor-m79-ppo-py312/bin/python'
v=subprocess.run([py,'-B',str(p),'verify'],cwd=r,env=env,capture_output=True,text=True,timeout=60)
if v.returncode:raise ValueError('c10 zero-game precheck failed: '+v.stderr[-1000:])
with (out/'supervisor.log').open('xb') as log:proc=subprocess.Popen([py,'-B',str(p),'run'],cwd=r,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
receipt=dict(status='STARTED_FIXED_C10_DEVELOPMENT',pid=proc.pid,create_time=psutil.Process(proc.pid).create_time(),node=platform.node(),games=256,workers=4,cpu_limit=4000,adapter_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),observed_at=time.time());(out/'launch.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
'''
    source = source.replace('r13-c10',f'r13-c{cycle}').replace("DEVELOPMENT_CYCLE='10'",f"DEVELOPMENT_CYCLE='{cycle}'").replace('C10_DEVELOPMENT',f'C{cycle}_DEVELOPMENT')
    launch = ssh(2223, source, timeout=100)
    (HERE / f'c{cycle}-launch.json').write_text(json.dumps(launch, indent=2) + '\n')
    return True


def main():
    try:
        for cycle in (5, 10, 15):
            if cycle != 5:
                save(state='WAITING_FOR_FIXED_C10_INPUT', last_import=json.loads((HERE/'c5-import.json').read_text()))
                while not prepare_checkpoint(cycle):
                    if time.time() >= STOP-1800:
                        save(state='C10_DEFERRED_TO_MAIN_NO_AUX_DISPATCH_WINDOW')
                        return
                    time.sleep(30)
            save(state='WAITING_FOR_FIXED_DEVELOPMENT_RESULT', cycle=cycle)
            while True:
                value = result_ready(cycle)
                if value['ready']:
                    break
                if value.get('resource') and value['resource']['status'] != 'PASS':
                    raise ValueError('retained auxiliary hard failure')
                time.sleep(15)
            save(state='IMPORTING_FIXED_DEVELOPMENT', cycle=cycle)
            result = import_result(cycle)
            save(state='FIXED_DEVELOPMENT_IMPORTED', cycle=cycle, result=result)
        save(state='COMPLETED_C5_C10_C15_IMPORTED', new_training_games=0)
    except BaseException as error:
        save(state='STOPPED_RETAINED_EVIDENCE', error=repr(error))
        raise


if __name__ == '__main__':
    main()
