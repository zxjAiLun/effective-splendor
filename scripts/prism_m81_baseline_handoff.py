"""Finite M81 baseline delivery between its two admitted nodes."""
import json,subprocess,time,hashlib,os
from pathlib import Path
ROOT='/mnt/workspace/splendor-m81-anchor-coverage-r1'
HERE=Path(__file__).resolve().parent
START=time.time()
PY='/mnt/workspace/envs/splendor-m79-ppo-py312/bin/python'
def query(port,code,timeout=90):
 p=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=8','-p',str(port),'root@127.0.0.1',PY,'-B','-'],input=code,text=True,capture_output=True,timeout=timeout)
 if p.returncode:raise ValueError(p.stderr[-1500:])
 return json.loads(p.stdout.splitlines()[-1])
def save(**x):
 x['observed_at']=time.time();(HERE/'status.json').write_text(json.dumps(x,indent=2))
try:
 while time.time()-START<7*3600:
  a=query(2223,"import json\nfrom pathlib import Path\np=Path("+repr(ROOT)+")/'pipeline/evaluate.completion.json'\nprint(json.dumps(json.loads(p.read_text()) if p.exists() else {'status':'WAITING'}))")
  if a['status']=='PASS':break
  if a['status']=='FAIL':raise ValueError('auxiliary baseline failed')
  save(state='WAITING_BASELINE_EXECUTION');time.sleep(30)
 else:raise ValueError('finite baseline handoff7h exhausted')
 code="""import json,zipfile,hashlib
from pathlib import Path
r=Path(ROOT);files=[]
for n in ('evaluation','evaluation-configs'):
 files.extend(p for p in (r/n).rglob('*') if p.is_file() and not p.name.endswith('.lock'))
files.extend([r/'evaluation-plan.json',r/'evaluation-completion.json',r/'pipeline/evaluate.completion.json'])
p=r/'baseline-results.zip'
if p.exists():raise ValueError('bundle alreadyexists')
with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED,compresslevel=1) as z:
 for f in files:z.write(f,str(f.relative_to(r)))
b=p.read_bytes();receipt=dict(sha256=hashlib.sha256(b).hexdigest(),bytes=len(b),files={str(f.relative_to(r)):dict(bytes=f.stat().st_size,sha256=hashlib.sha256(f.read_bytes()).hexdigest()) for f in files})
(r/'baseline-results.receipt.json').write_text(json.dumps(receipt))
print(json.dumps({'sha256':receipt['sha256'],'bytes':receipt['bytes'],'cpu_seconds':json.loads((r/'pipeline/evaluate.completion.json').read_text())['resources']['cpu_seconds']}))
""".replace('ROOT',repr(ROOT))
 a=query(2223,code,timeout=900)
 bundle=HERE/'baseline-results.zip'
 with bundle.open('xb') as f:
  p=subprocess.run(['ssh','-o','BatchMode=yes','-p','2223','root@127.0.0.1','cat',ROOT+'/baseline-results.zip'],stdout=f,timeout=900)
 if p.returncode or hashlib.sha256(bundle.read_bytes()).hexdigest()!=a['sha256']:raise ValueError('transport SHA')
 p=subprocess.run(['scp','-q','-P','2222',str(bundle),'root@127.0.0.1:'+ROOT+'/baseline-results.zip'],timeout=900)
 if p.returncode:raise ValueError('main transport')
 code="""import json,zipfile,hashlib
from pathlib import Path
r=Path(ROOT);p=r/'baseline-results.zip'
assert hashlib.sha256(p.read_bytes()).hexdigest()==SHA
with zipfile.ZipFile(p) as z:
 for n in z.namelist():
  q=Path(n)
  if q.is_absolute() or '..' in q.parts:raise ValueError('unsafe member')
  if q.parts[0] not in ('evaluation','evaluation-configs') and n not in ('evaluation-plan.json','evaluation-completion.json','pipeline/evaluate.completion.json'):raise ValueError('unexpected member')
  target=r/q
  if n.startswith('pipeline/') or n=='evaluation-completion.json':target=r/'baseline-original'/q
  v=z.read(n)
  if target.exists() and target.read_bytes()!=v:raise ValueError('existing member drift')
  target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(v)
out=dict(status='PASS_SHA_BOUND_BASELINE_IMPORT',sha256=SHA,cpu_seconds=CPU,new_games_on_import=0)
(r/'baseline-import.json').write_text(json.dumps(out))
print(json.dumps(out))
""".replace('ROOT',repr(ROOT)).replace('==SHA','=='+repr(a['sha256'])).replace('sha256=SHA','sha256='+repr(a['sha256'])).replace('CPU',repr(a['cpu_seconds']))
 out=query(2222,code,timeout=900);save(state='COMPLETED',receipt=out)
except BaseException as e:
 save(state='FAILED_RETAINED_EVIDENCE',error=repr(e))
 try:query(2222,"from pathlib import Path\nimport json\np=Path("+repr(ROOT)+")/'baseline-dispatch-failure.json';p.write_text("+repr(json.dumps({'error':repr(e)}))+");print('{}')")
 except BaseException:pass
 raise
