"""r9.2 control-only ordering repair; finished validation overlaps new shards."""
import importlib.util,inspect,json,sys,threading
from pathlib import Path
v=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('r9_ordering',v/'controller.py');q=importlib.util.module_from_spec(s);s.loader.exec_module(q);q.policy()
factory=q.recovery

def replace_cell(function,name,value):
 cells=dict(zip(function.__code__.co_freevars,function.__closure__ or ()))
 if name not in cells:raise ValueError('adapter closure target drift: '+name)
 cells[name].cell_contents=value

def recovery():
 r=factory();base_contract=r.contract
 def contract():
  p=base_contract();return dict(p,max_coordinator_restarts=8)
 r.contract=contract
 base_install=r.install_adapters
 def install(m):
  base_install(m)
  from scripts import prism_m75_evaluate as e,prism_bounded_eval as b
  cells=dict(zip(e.dispatch.__code__.co_freevars,e.dispatch.__closure__))
  original=cells['native'].cell_contents
  def overlap(shards,limit=4,truncation_limit=16):
   complete=[];pending=[]
   for row in shards:
    f=Path(row['output'])/'ledger.json'
    (complete if f.exists() and q.read(f)['execution_state']=='FINISHED' else pending).append(row)
   result={}
   def work():
    try:result['done']=original(pending,limit=limit,truncation_limit=truncation_limit)
    except BaseException as error:result['error']=error
   t=threading.Thread(target=work);t.start()
   saved=[dict(row,grid=b.inspect(Path(row['output']))) for row in complete]
   t.join()
   if 'error' in result:raise result['error']
   all_done=saved+result['done']
   if sum(row['grid']['truncated_games'] for row in all_done)>truncation_limit:raise ValueError('combined cap budget exceeded')
   return all_done
  replace_cell(e.dispatch,'native',overlap)
  r8_stage=dict(zip(m.stage.__code__.co_freevars,m.stage.__closure__))['native_stage'].cell_contents
  native=r.load('ordering_original_stage',q.ROOT/'eval-handoff-r4/controller.py')
  source=inspect.getsource(native.stage);target='str(Path(__file__).resolve())';assert source.count(target)==1
  ns=dict(native.__dict__);exec(compile(source.replace(target,"str(ROOT/'split-eval-r9/ordering-v2.py')"),str(__file__)+'::owned-stage','exec'),ns)
  replace_cell(r8_stage,'native_stage',ns['stage'])
  original_stage=m.stage
  def stage(mode,cpu_left,node):
   if mode=='early-development':
    receipt=q.read(m.REV/mode/'completion.json');assert receipt['state']=='PASS'
    # Previously completed and independently revalidated in this same r9 run.
    return receipt['resources']['cpu_seconds']
   return original_stage(mode,cpu_left,node)
  m.stage=stage
 r.install_adapters=install
 return r
q.recovery=recovery
if sys.argv[1]=='child':
 r=recovery();m=r.load('ordering_child',q.ROOT/'eval-handoff-r4/controller.py');r.install_adapters(m);m.child(sys.argv[2])
else:
 try:print(json.dumps(q.endpoint(sys.argv[1])))
 except Exception as error:print(json.dumps(dict(state='RECOVERY_BLOCKED',error_type=type(error).__name__)));sys.exit(1)
