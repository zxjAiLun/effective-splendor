"""Separate auxiliary progress writers, retain the first 72 valid games and costs."""
import argparse,copy,json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts import prism_m79_dual_dispatch as dual


def verify():
    r=dual.read_json(ROOT/'execution-revisions/aux-r2.json')
    if dual.sha_file(Path(__file__))!=r['adapter_sha256'] or dual.sha_file(ROOT/'scripts/prism_m79_dual_dispatch.py')!=r['original_adapter_sha256']:
        raise ValueError('auxiliary r2 source drift')
    state=dual._load_state(ROOT)
    if r['previous_resource_sha256']!=dual.sha_file(ROOT/'execution-revisions/dual-dispatch-r1/aux-resource-r1.json'):
        raise ValueError('retained auxiliary resource drift')
    if state['aux_cpu_reservation']!=40000:raise ValueError('aux CPU reservation changed')
    return r


def worker(workers):
    verify();original=dual._dispatch_pristine
    def dispatch(root,rows,workers,status_path):
        return original(root,rows,workers,status_path.with_name('aux-worker-progress-r2.json'))
    dual._dispatch_pristine=dispatch
    return dual._aux_worker(ROOT,workers)


def run(workers):
    revision=verify();previous=dual.read_json(ROOT/'execution-revisions/dual-dispatch-r1/aux-resource-r1.json')
    original_state=dual._load_state
    def state(root):
        value=copy.deepcopy(original_state(root));value['aux_cpu_reservation']-=previous['cpu_seconds'];return value
    dual._load_state=state
    from scripts.prism_dsw_ppo_process import ProcessTree
    native=ProcessTree.start
    def start(self,argv,**kw):
        if len(argv)>3 and argv[2]==str(ROOT/'scripts/prism_m79_dual_dispatch.py') and argv[3]=='aux-worker':
            argv=[argv[0],argv[1],str(Path(__file__).resolve()),'worker','--workers',str(workers)]
        return native(self,argv,**kw)
    ProcessTree.start=start
    result=dual.aux_run(ROOT,workers)
    result['cpu_seconds']+=previous['cpu_seconds'];result['previous_attempts']=[previous]
    result['cpu_reservation']=40000;result['r2_sha256']=dual.sha_file(Path(__file__))
    dual.write_json(ROOT/dual.REV_DIR_REL/'aux-resource.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('run','worker'));p.add_argument('--workers',type=int,default=8);a=p.parse_args()
    print(json.dumps(run(a.workers) if a.mode=='run' else worker(a.workers)),flush=True)
