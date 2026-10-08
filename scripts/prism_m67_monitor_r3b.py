"""Read-only observer across the explicit R3 -> R3B evaluation boundary."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import prism_m67_monitor_r3 as prior
import os
folder = os.environ.get('M67_R3_OBSERVER_FOLDER', 'monitor-r3b')
prior.OUT=ROOT/'local-artifacts/prism/m67-alpha-repeat'/folder
marker="print(json.dumps(dict(observed_at=time.time(),launch=launch,state=state,process_identity_matches=alive,stages=stages,completed_evaluations=total)))"
assert prior.PROBE.count(marker)==1
prior.PROBE=prior.PROBE.replace(marker,r'''
if not alive:
 path=r/'continuation-r3b/status.json'
 if path.exists():
  successor=json.loads(path.read_text())
  try:
   proc=psutil.Process(successor['pid'])
   successor_alive=proc.is_running() and proc.status()!=psutil.STATUS_ZOMBIE and abs(proc.create_time()-successor['create_time'])<.01 and str(r/'scripts/prism_m67_eval_recovery_r3b.py') in proc.cmdline()
  except psutil.Error:successor_alive=False
  if successor_alive:
   launch=dict(pid=successor['pid'],create_time=successor['create_time'])
   state=dict(successor);state.pop('shards',None)
   state['phase']='a-common-recovery-r3b' if successor['state']=='RUNNING_EXPLICIT_RECOVERY_R3B' else 'waiting-r3b-boundary'
   state['state']='RUNNING';alive=True
   state['execution_successor']='r3b'
print(json.dumps(dict(observed_at=time.time(),launch=launch,state=state,process_identity_matches=alive,stages=stages,completed_evaluations=total)))
''')
if __name__=='__main__':prior.run()
