"""M70 read-only exact final checkpoint and all saved training games audit."""
import argparse
from collections import Counter,defaultdict
import gc
import json
from pathlib import Path
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from training.prism_portable.common import read,write,digest
from scripts.prism_m70_run import verify,bounds

def checked(argv,receipt,timeout=600):
    import subprocess
    start=time.monotonic();r=subprocess.run(list(map(str,argv)),capture_output=True,text=True,timeout=min(timeout,bounds()))
    write(receipt,{'argv':list(map(str,argv)),'exit':r.returncode,'stdout':r.stdout,'stderr':r.stderr,'wall_seconds':time.monotonic()-start})
    if r.returncode:raise ValueError('offline audit failed: '+str(receipt))

def audit(arm):
    c,_=verify()
    from scripts.prism_m67_storage import install
    install()
    import torch
    from training.prism_portable.engine.ppo.coordinator import Run
    from training.prism_portable.engine.ppo.store import CommitStore
    from training.prism_portable.protocol import validate_launch_ledger
    from training.prism_portable.engine.export import load_weights
    from training.prism_portable.engine.parity import predict_jsonl
    from scripts.prism_alpha_cloud_audit_m60 import compare_values
    from scripts import prism_match_details as details,prism_notebook_report as report
    from scripts.prism_human_report import write_markdown
    from training.prism_portable.engine.ppo.execution import verify_completion
    engineering=arm=='engineering';expected_games=8 if engineering else 1024;cycles=1 if engineering else 4
    camp=ROOT/'campaigns'/arm;out=ROOT/'audits'/arm;out.mkdir(parents=True,exist_ok=False)
    completion=read(ROOT/'control'/arm/'completion.json')
    if completion['state']!='STOPPED_COMMITTED' or completion['completed_games']!=expected_games:raise ValueError('training incomplete')
    before={p.relative_to(ROOT).as_posix():digest(p) for p in (camp/'run/HEAD.json',camp/'launch-ledger/HEAD.json')}
    run=Run.open(camp/'run');s=run.state
    if (s['phase'],s['cycle'],s['attempts'],len(s['all_jobs']),len(s['consumed']))!=('COMMITTED',cycles,expected_games,expected_games,cycles):raise ValueError('training ledger mismatch')
    ledger=CommitStore(camp/'launch-ledger',run.config['arena_contract_sha256']).load()[1]
    spec=read(camp/'contract.json');validate_launch_ledger(ledger,s,spec)
    if ledger['retries']!=0 or ledger['failed']:raise ValueError('retry/failed ledger')
    export=camp/f'cycle-{cycles}-export/weights.json';weight_sha=digest(export)
    if weight_sha!=completion['completion']['weights_sha256']:raise ValueError('export completion mismatch')
    model=load_weights(export,expected_catalog_fingerprint=run.config['catalog_fingerprint'])
    if len(s['optimizer']['state'])!=32:raise ValueError('optimizer slots mismatch')
    for k,t in model.state_dict().items():
        if not torch.equal(t,s['model']['policy.'+k]):raise ValueError('tensor mismatch: '+k)
    parent=load_weights(ROOT/'inputs/parent.json',expected_catalog_fingerprint=run.config['catalog_fingerprint'])
    changed=any(not torch.equal(t,parent.state_dict()[k]) for k,t in model.state_dict().items())
    if not changed:raise ValueError('training weight did not change')
    checkpoint={'status':'PASS','cycle':cycles,'games':expected_games,'global_step':s['global_step'],'update_attempts':s['update_attempts'],
        'optimizer_slots':32,'exact_export_tensors':32,'changed_from_parent':changed,'weights_sha256':weight_sha,'run_identity':run.identity,
        'commit':run.parent,'new_training_updates':0,'initialization':read(camp/'initialization-verification.json')}
    write(out/'checkpoint.json',checkpoint);del model,parent,run,s;gc.collect()
    raw=out/'inputs.jsonl';rows=[row.get('input',row) for row in (json.loads(l) for l in (ROOT/'inputs/fixtures.jsonl').read_text().splitlines())]
    raw.write_text(''.join(json.dumps(row)+'\n' for row in rows))
    checked([ROOT/'bin/splendor','prism-predict','--weights',export,'--input',raw,'--output',out/'rust.jsonl'],out/'native-parity.json')
    predict_jsonl(export,raw,out/'python.jsonl',expected_catalog_fingerprint=spec['run']['catalog_fingerprint'])
    expected=[json.loads(l) for l in (out/'rust.jsonl').read_text().splitlines()];actual=[json.loads(l) for l in (out/'python.jsonl').read_text().splitlines()]
    if len(expected)!=68 or len(actual)!=68:raise ValueError('parity input count')
    errors=[]
    for a,b in zip(expected,actual):compare_values(a,b,errors)
    parity={'status':'PASS','rows':68,'max_abs_error':max(errors),'atol':1e-4,'rtol':1e-4,'weights_sha256':weight_sha};write(out/'parity.json',parity)
    jobs={j['job_id']:(cycle+1,j) for cycle,group in enumerate(spec['cycles']) for j in group};groups=defaultdict(list);sources=[]
    for number,item in sorted(ledger['attempts'].items(),key=lambda pair:int(pair[0])):
        if item['status']!='COMPLETE':raise ValueError('noncomplete attempt')
        p=camp/'attempts'/f'{int(number):03d}';done=read(p/'completion.json');job=done['job'];cycle,expected_job=jobs[job['job_id']]
        if job!=expected_job:raise ValueError('schedule drift')
        result=verify_completion(spec['run'],job,int(number),p/'completion.json',replay=p/'replay.json',sidecar=p/'sidecar.jsonl',behavior_id=done['behavior_id'])
        replay=read(p/'replay.json');actor=job['actor'];score=.5 if result['ranks'][0]==result['ranks'][1] else float(result['ranks'][actor]<result['ranks'][1-actor])
        actions=[Counter(),Counter()]
        for step in replay['steps']:actions[step['actor']][step['action']['type']]+=1
        row={'candidate':f'train-{arm}-c{cycle}','opponent':job['opponent_id'],'seed':job['environment_seed'],'candidate_seat':actor,
             'candidate_score':score,'record':'win' if score==1 else 'draw' if score==.5 else 'loss',
             'candidate_points':result['scores'][actor],'opponent_points':result['scores'][1-actor],'plies':len(replay['steps']),
             '_candidate_actions':actions[actor],'_opponent_actions':actions[1-actor],'_wall_seconds':done['resources']['wall_seconds'],'_replay_path':str(p/'replay.json')}
        groups[(row['candidate'],row['opponent'],actor)].append(row)
        sources.append({'attempt':int(number),'job':job,'files':{n:digest(p/n) for n in ('completion.json','replay.json','report.json','sidecar.jsonl')}})
    if len(sources)!=expected_games:raise ValueError('source count mismatch')
    write(out/'training-sources.json',sources);metrics={}
    for i,(key,rs) in enumerate(sorted(groups.items())):
        manifest=out/f'group-{i}.json';target=out/f'group-{i}.metrics.json';write(manifest,{'rows':[{'replay_path':r['_replay_path']} for r in rs]})
        checked([ROOT/'bin/s4_batch_metrics',manifest,target],out/f'group-{i}.receipt.json');metrics[key]=read(target)
    pairs=[]
    for m,o in sorted({(m,o) for m,o,_ in groups}):
        rs=groups[m,o,0]+groups[m,o,1];cb=[];ob=[];seats=[]
        for seat in (0,1):
            rawm=metrics[m,o,seat];sub=groups[m,o,seat]
            a=rawm['seat_p0_first' if seat==0 else 'seat_p1_second'];b=rawm['seat_p1_second' if seat==0 else 'seat_p0_first']
            cb.append((a,len(sub)));ob.append((b,len(sub)))
            seats.append({'candidate_seat':seat,'candidate':details.merge_player([(a,len(sub))],sub,True),'opponent':details.merge_player([(b,len(sub))],sub,False)})
        pairs.append({'candidate':m,'opponent':o,'candidate_metrics':details.merge_player(cb,rs,True),'opponent_metrics':details.merge_player(ob,rs,False),
            'macro':details.macro(rs),'seats':seats,'score_uncertainty':{'ordinary_95_ci':report.interval(rs)['ci95'],'seed_blocks':len(rs)//2},
            'win_uncertainty':{'ordinary_95_ci':report.interval(rs,True)['ci95'],'seed_blocks':len(rs)//2},'candidate_mode':'sample','opponent_mode':'greedy'})
    names=dict(c['names'],**{f'train-{arm}-c{i}':f'M70种子{arm.upper()}第{i}周期训练行为策略（未发布，非最终验收）' for i in range(1,cycles+1)})
    story={'title':f'M70种子{arm.upper()}训练对战完整数据','headline':'训练数据仅诊断，不用于判断最终c4棋力。',
        'identity':'各周期当时的行为策略；不能把全部训练对局归给最终权重。','conclusions':[{'label':'训练产物','value':'完成并核验','explanation':f'{expected_games}局、{cycles}周期。'}],
        'interpretation':'候选T=1采样，对手greedy；与独立双方greedy验收分报。','next':'按冻结网格验收唯一最终检查点。'}
    write_markdown(out/'training-report.md',{'story':story,'view':'history','history_headline':story['headline'],'names':names,
        'focus':f'train-{arm}-c{cycles}','comparison_baseline':'NOT_RUN','result':{'training':{'label':'训练用对战（非独立验收）','pairs':pairs}}})
    import markdown
    (out/'training-report.html').write_text('<!doctype html><meta charset="utf-8"><title>M70训练对战</title>'+markdown.markdown((out/'training-report.md').read_text(),extensions=['tables']),encoding='utf-8')
    if any(digest(ROOT/p)!=h for p,h in before.items()):raise ValueError('audit mutated committed state')
    result={'status':'PASS_TRAINING_ARTIFACT_AUDIT','weights_sha256':weight_sha,'completed_games':expected_games,'checkpoint':checkpoint,'parity':parity,
        'source_ledger_sha256':digest(out/'training-sources.json'),'new_games':0,'new_optimizer_updates':0,'automatic_retries':0,
        'rule_replay_validation':f'all {expected_games} saved replays via pinned s4_batch_metrics','training_report_sha256':digest(out/'training-report.md')}
    write(out/'audit.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--arm',choices=('engineering','a'),required=True);a=p.parse_args()
    print(json.dumps(audit(a.arm),ensure_ascii=False))
