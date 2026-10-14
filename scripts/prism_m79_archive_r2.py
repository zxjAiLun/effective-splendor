"""Independent R7 null-metric adapter for undispatched M79 pairs."""
import argparse,hashlib,inspect,json,textwrap,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts import prism_m79_archive as original

NATIVE=original.aggregate

def aggregate(plan,result,attempts,*args,**kwargs):
    for row in result.get('pairs',[]):
        if row.get('candidate_metrics') is None or row.get('opponent_metrics') is None:
            key=(row.get('candidate'),row.get('opponent'))
            completed=[r for r in attempts if original._attempt_key(r)[:2]==key and original._status(r)=='COMPLETED']
            original.require(not completed and row.get('completed_games')==0 and row.get('candidate_metrics') is None and row.get('opponent_metrics') is None and row.get('seats')==[], 'null pair metrics require zero completed games and no seat summaries')
    source=textwrap.dedent(inspect.getsource(NATIVE))
    for field in ('candidate_metrics','opponent_metrics'):
        old=f'isinstance(row.get("{field}"), dict)'
        original.require(source.count(old)==1,'independent archive adapter target drift')
        source=source.replace(old,f'isinstance(row.get("{field}"), (dict, type(None)))')
    ns=dict(NATIVE.__globals__);exec(compile(source,str(Path(__file__))+'::aggregate','exec'),ns)
    return ns['aggregate'](plan,result,attempts,*args,**kwargs)

def build(plan,result,raw_root,prefix):
    original.aggregate=aggregate
    try:card,receipt=original.build(plan,result,raw_root,prefix)
    finally:original.aggregate=NATIVE
    receipt['independent_adapter']=dict(path=str(Path(__file__).resolve()),sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),original_archive_sha256=original.digest(original.__file__),scope='null metrics only for zero-completion pairs; all original identity and grid checks retained')
    return original._write_outputs(card,receipt,Path(prefix))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--plan',required=True);parser.add_argument('--result',required=True);parser.add_argument('--raw-root',required=True);parser.add_argument('--prefix',required=True);a=parser.parse_args()
    print(json.dumps(build(a.plan,a.result,a.raw_root,a.prefix)[1],ensure_ascii=False))
