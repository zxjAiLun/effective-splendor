import importlib.util,inspect,json,sys
from pathlib import Path
v=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('r9_corrected_entry',v/'controller.py');q=importlib.util.module_from_spec(s);s.loader.exec_module(q);q.policy()
text=inspect.getsource(q.ensure_subset);assert text.count('len(attempts)>=2')==1
ns=dict(q.__dict__);exec(compile(text.replace('len(attempts)>=2','len(attempts)>=4'),str(__file__)+'::bounded-zero-game-correction','exec'),ns);q.ensure_subset=ns['ensure_subset']
factory=q.recovery
def recovery():
 r=factory();native=r.status
 def status():
  row=native()
  if row['role']=='dsw2' and row['state'] not in ('COMPLETED','DEADLINE'):
   workers=[p.pid for p in q.psutil.process_iter(['status','cmdline']) if p.info['status']!='zombie' and 'grid' in (p.info['cmdline'] or []) and any(str(q.ROOT) in a for a in (p.info['cmdline'] or []))]
   if workers:row.update(state='RUNNING',phase='CANDIDATE_SHARDS_DSW2',live_workers=workers)
  return row
 r.status=status
 return r
q.recovery=recovery
# On a full DSW reboot admit the main owner before the subset owner, avoiding
# the original orphan guard rejecting the newly started sibling supervisor.
original_subset=q.ensure_subset
def ensure_subset(token):
 r=factory()
 if r.contract()['role']=='dsw' and r.status()['state']=='NO_OWNER' and q.subset_status()['state']=='NO_OWNER':r.ensure(token)
 return original_subset(token)
q.ensure_subset=ensure_subset
try:
 result=q.endpoint(sys.argv[1])
 if result.get('role')=='dsw' and result.get('split_subset',{}).get('state')=='COMPLETED' and str(result.get('phase','')).startswith(('WAIT_','TRANSPORT_READ_RETRY_')):
  result['state']='IDLE_WAIT';result['idle_reason']='EVALUATION_COMPLETE_WAITING_BOUND_FINAL_OUTPUT'
 print(json.dumps(result))
except Exception as error:print(json.dumps(dict(state='RECOVERY_BLOCKED',error_type=type(error).__name__)));sys.exit(1)
