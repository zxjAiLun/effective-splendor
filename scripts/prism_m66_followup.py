"""M66 once-only post-training audit and frozen greedy grid. Never trains/retries.

Pins are checked before stages. A dead training owner without completion is fatal.
Only the specified final c4 can enter the candidate arenas. Generic arena reports
remain evidence; M66's two frozen competitive gates are evaluated separately.
"""
import argparse
from collections import Counter,defaultdict
import copy
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from training.prism_portable.common import read,write,digest
from scripts.prism_m66_train import contract,verify as verify_training
from scripts.prism_dsw_ppo_process import ProcessTree,same_process


def bounds():
    remaining=read(ROOT/'round-budget.json')['deadline']-time.time()
    if remaining<=0:raise ValueError('original M66 deadline exhausted')
    return remaining


def pinned():
    c=contract();p=read(ROOT/'followup-execution.json')
    if p['config_sha256']!=digest(ROOT/'benchmarks/m66-prism-alpha-dsw.config.json'):raise ValueError('followup config drift')
    for name,expected in p['files'].items():
        if digest(ROOT/name)!=expected:raise ValueError('followup source drift: '+name)
    return c


def checked_command(argv,receipt,timeout=180):
    started=time.monotonic()
    x=subprocess.run(list(map(str,argv)),capture_output=True,text=True,timeout=min(timeout,bounds()))
    write(receipt,{'argv':list(map(str,argv)),'exit':x.returncode,'stdout':x.stdout,'stderr':x.stderr,
                   'wall_seconds':time.monotonic()-started})
    if x.returncode:raise ValueError('offline command failed: '+str(receipt))


def audit(engineering=False):
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
    c,_=verify_training();name='engineering' if engineering else 'training'
    expected_games=8 if engineering else 1024;expected_cycles=1 if engineering else 4
    camp=ROOT/'campaigns'/name;out=ROOT/('engineering-audit' if engineering else 'final-audit')
    out.mkdir(exist_ok=False)
    completion=read(ROOT/'control'/name/'completion.json')
    if completion['state']!='STOPPED_COMMITTED' or completion['completed_games']!=expected_games:raise ValueError('training incomplete')
    before={str(p.relative_to(ROOT)):digest(p) for p in (camp/'run/HEAD.json',camp/'launch-ledger/HEAD.json')}
    run=Run.open(camp/'run');s=run.state
    if (s['phase'],s['cycle'],s['attempts'],len(s['all_jobs']),len(s['consumed']))!=('COMMITTED',expected_cycles,expected_games,expected_games,expected_cycles):raise ValueError('final training ledger mismatch')
    ledger=CommitStore(camp/'launch-ledger',run.config['arena_contract_sha256']).load()[1]
    spec=read(camp/'contract.json');validate_launch_ledger(ledger,s,spec)
    export=camp/f'cycle-{expected_cycles}-export/weights.json';weight_sha=digest(export)
    if weight_sha!=completion['completion']['weights_sha256']:raise ValueError('supervisor/export mismatch')
    model=load_weights(export,expected_catalog_fingerprint=run.config['catalog_fingerprint'])
    if len(s['optimizer']['state'])!=32:raise ValueError('outcome-only optimizer slots mismatch')
    for key,t in model.state_dict().items():
        if not torch.equal(t,s['model']['policy.'+key]):raise ValueError('export tensor mismatch: '+key)
    parent=load_weights(ROOT/'inputs/parent.json',expected_catalog_fingerprint=run.config['catalog_fingerprint'])
    changed=any(not torch.equal(t,parent.state_dict()[k]) for k,t in model.state_dict().items())
    checkpoint={'status':'PASS','cycle':expected_cycles,'games':expected_games,'global_step':s['global_step'],'update_attempts':s['update_attempts'],
        'optimizer_slots':32,'exact_export_tensors':32,'changed_from_parent':changed,'weights_sha256':weight_sha,
        'run_identity':run.identity,'commit':run.parent,'new_training_updates':0}
    write(out/'checkpoint.json',checkpoint)
    del model,parent,run,s
    import gc;gc.collect()
    raw=out/'inputs.jsonl';rows=[readrow.get('input',readrow) for readrow in
        (json.loads(line) for line in (ROOT/'inputs/fixtures.jsonl').read_text().splitlines())]
    raw.write_text(''.join(json.dumps(row)+'\n' for row in rows))
    checked_command([ROOT/'bin/splendor','prism-predict','--weights',export,'--input',raw,'--output',out/'rust.jsonl'],out/'native-parity.json')
    predict_jsonl(export,raw,out/'python.jsonl',expected_catalog_fingerprint=spec['run']['catalog_fingerprint'])
    expected=[json.loads(l) for l in (out/'rust.jsonl').read_text().splitlines()]
    actual=[json.loads(l) for l in (out/'python.jsonl').read_text().splitlines()]
    if len(actual)!=68 or len(expected)!=68:raise ValueError('parity count')
    errors=[]
    for a,b in zip(expected,actual):compare_values(a,b,errors)
    parity={'status':'PASS','rows':68,'max_abs_error':max(errors),'atol':1e-4,'rtol':1e-4,'weights_sha256':weight_sha}
    write(out/'parity.json',parity)
    jobs={j['job_id']:(cycle+1,j) for cycle,group in enumerate(spec['cycles']) for j in group}
    groups=defaultdict(list);sources=[]
    for number,item in sorted(ledger['attempts'].items(),key=lambda pair:int(pair[0])):
        if item['status']!='COMPLETE':raise ValueError('noncomplete training attempt')
        p=camp/'attempts'/f'{int(number):03d}';done=read(p/'completion.json');job=done['job'];cycle,expected_job=jobs[job['job_id']]
        if job!=expected_job:raise ValueError('training schedule changed')
        result=verify_completion(spec['run'],job,int(number),p/'completion.json',replay=p/'replay.json',
                                 sidecar=p/'sidecar.jsonl',behavior_id=done['behavior_id'])
        replay=read(p/'replay.json');actor=job['actor'];score=.5 if result['ranks'][0]==result['ranks'][1] else float(result['ranks'][actor]<result['ranks'][1-actor])
        actions=[Counter(),Counter()]
        for step in replay['steps']:actions[step['actor']][step['action']['type']]+=1
        row={'candidate':f'train-c{cycle}','opponent':job['opponent_id'],'seed':job['environment_seed'],'candidate_seat':actor,
            'candidate_score':score,'record':'win' if score==1 else 'draw' if score==.5 else 'loss',
            'candidate_points':result['scores'][actor],'opponent_points':result['scores'][1-actor],
            'plies':len(replay['steps']),'_candidate_actions':actions[actor],'_opponent_actions':actions[1-actor],
            '_wall_seconds':done['resources']['wall_seconds'],'_replay_path':str(p/'replay.json')}
        groups[(row['candidate'],row['opponent'],actor)].append(row)
        sources.append({'attempt':int(number),'job':job,'files':{n:digest(p/n) for n in ('completion.json','replay.json','report.json','sidecar.jsonl')}})
    if len(sources)!=expected_games:raise ValueError('training source count mismatch')
    write(out/'training-sources.json',sources);metrics={}
    for i,(key,rs) in enumerate(sorted(groups.items())):
        manifest=out/f'group-{i}.json';target=out/f'group-{i}.metrics.json'
        write(manifest,{'rows':[{'replay_path':r['_replay_path']} for r in rs]})
        checked_command([ROOT/'bin/s4_batch_metrics',manifest,target],out/f'group-{i}.receipt.json')
        metrics[key]=read(target)
    pairs=[]
    for m,o in sorted({(m,o) for m,o,_ in groups}):
        rs=groups[m,o,0]+groups[m,o,1];cb=[];ob=[];seats=[]
        for seat in (0,1):
            rawm=metrics[m,o,seat];sub=groups[m,o,seat]
            a=rawm['seat_p0_first' if seat==0 else 'seat_p1_second'];b=rawm['seat_p1_second' if seat==0 else 'seat_p0_first']
            cb.append((a,len(sub)));ob.append((b,len(sub)))
            seats.append({'candidate_seat':seat,'candidate':details.merge_player([(a,len(sub))],sub,True),
                          'opponent':details.merge_player([(b,len(sub))],sub,False)})
        pairs.append({'candidate':m,'opponent':o,'candidate_metrics':details.merge_player(cb,rs,True),
            'opponent_metrics':details.merge_player(ob,rs,False),'macro':details.macro(rs),'seats':seats,
            'score_uncertainty':{'ordinary_95_ci':report.interval(rs)['ci95'],'seed_blocks':len(rs)//2},
            'win_uncertainty':{'ordinary_95_ci':report.interval(rs,True)['ci95'],'seed_blocks':len(rs)//2},
            'candidate_mode':'sample','opponent_mode':'greedy'})
    names=dict(c['names'],**{f'train-c{i}':f'M66第{i}轮训练行为策略（未发布，非最终c4验收）' for i in range(1,5)})
    story={'title':'M66 训练对战完整数据','headline':'训练数据仅诊断，不用于判断最终c4棋力。',
           'identity':'各cycle使用当轮冻结行为策略；不是把所有训练对局归给最终权重。',
           'conclusions':[{'label':'训练产物','value':'完成并核验','explanation':f'{expected_games}局、{expected_cycles}次提交边界。'}],
           'interpretation':'候选训练按T=1采样，对手greedy；不与独立双方greedy验收合并。',
           'next':'最终c4独立评测按原冻结合同执行。'}
    write_markdown(out/'training-report.md',{'story':story,'view':'history','history_headline':story['headline'],
        'names':names,'focus':'train-c4','comparison_baseline':'NOT_RUN','result':{'training':{'label':'训练用对战（非独立验收）','pairs':pairs}}})
    import markdown
    (out/'training-report.html').write_text('<!doctype html><meta charset="utf-8"><title>M66训练对战</title>'+markdown.markdown((out/'training-report.md').read_text(),extensions=['tables']),encoding='utf-8')
    if any(digest(ROOT/p)!=h for p,h in before.items()):raise ValueError('audit mutated committed state')
    result={'status':'PASS_TRAINING_ARTIFACT_AUDIT','weights_sha256':weight_sha,'completed_games':expected_games,'checkpoint':checkpoint,
        'parity':parity,'source_ledger_sha256':digest(out/'training-sources.json'),'new_games':0,'new_optimizer_updates':0,
        'rule_replay_validation':f'all {expected_games} saved replays via pinned s4_batch_metrics',
        'completion_validation':'each saved report/sidecar/hash/seed/actor/completion verified; no resampling',
        'training_report_sha256':digest(out/'training-report.md')}
    write(out/'audit.json',result)
    return result


def arena_stage(direct=False):
    from scripts import prism_notebook_arena as arena
    c=pinned();e=c['evaluation'];audit_result=read(ROOT/'final-audit/audit.json')
    export=ROOT/'campaigns/training/cycle-4-export/weights.json'
    if audit_result['status']!='PASS_TRAINING_ARTIFACT_AUDIT' or digest(export)!=audit_result['weights_sha256']:raise ValueError('candidate audit drift')
    engine=ROOT/'bin/splendor';names=c['names']
    candidates={'candidate':arena.model(export,names['candidate'],engine,mode='greedy',action_seed=e['action_seed'])}
    keys=['parent'] if direct else e['common_opponents']
    opponents={k:(arena.heuristic(engine,names[k],e['action_seed']) if k=='heuristic' else
                   arena.model(ROOT/f'inputs/{k}.json',names[k],engine,mode='greedy',action_seed=e['action_seed'])) for k in keys}
    start=e['direct_seed_start' if direct else 'common_seed_start'];end=e['direct_seed_end' if direct else 'common_seed_end']
    work=ROOT/'evaluation'/('direct' if direct else 'candidate')
    plan=arena.prepare(work,engine,ROOT/'bin/s4_batch_metrics',candidates,opponents,list(range(start,end+1)),workers=4,
        action_seed=e['action_seed'],shard_seed_blocks=16,memory_gib=8,wall_hours=min(7200,bounds()-5)/3600,
        cpu_hours=20000/3600,storage_gib=16)
    reference=read(ROOT/'evaluation/reference/plan.json')
    if plan['provenance']['dependencies']!=reference['provenance']['dependencies'] or plan['source_hashes']!=reference['source_hashes']:
        raise ValueError('candidate/reference arena runtime mismatch')
    arena.verify(work);owner=arena.start(work)
    while True:
        bounds();s=arena.status(work)
        if s['state']=='COMPLETED_DEVELOPMENT_ONLY':return {'games':s['completed_games'],'work':str(work)}
        if s['state'].startswith('FAILED') or not arena.alive(owner):raise ValueError('candidate arena failed/stopped; no retry')
        time.sleep(1)


def run():
    c=pinned();out=ROOT/'followup';out.mkdir(exist_ok=True)
    with (out/'once-only.lock').open('x'):pass
    import psutil
    me=psutil.Process();state={'state':'RUNNING','phase':'WAITING_TRAINING','pid':me.pid,'create_time':me.create_time(),'started_at':time.time()}
    def publish(**fields):state.update(fields,observed_at=time.time());write(out/'status.json',state)
    publish()
    try:
        while not (ROOT/'control/training/completion.json').exists():
            bounds();s=read(ROOT/'control/training/status.json')
            if s['state'].startswith('FAILED') or not same_process(s['pid'],s['create_time']):raise ValueError('training ended without committed completion')
            publish(training_completed=s.get('completed_games',0));time.sleep(2)
        phases=[('FINAL_ARTIFACT_AUDIT',str(ROOT/'.venv/bin/python'),'audit'),
                ('CANDIDATE_COMMON_GREEDY','/mnt/workspace/splendor-dsw/.venv/bin/python','arena'),
                ('CANDIDATE_DIRECT_GREEDY','/mnt/workspace/splendor-dsw/.venv/bin/python','direct'),
                ('READABLE_RESULT_REPORT',str(ROOT/'.venv/bin/python'),'report')]
        for phase,py,mode in phases:
            pinned();remaining=bounds();publish(phase=phase)
            os.environ.update(PRISM_PPO_CONTROL_DIR=str(out),PRISM_DSW_REMAINING_WALL=str(remaining),
                              OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
            script=ROOT/'scripts'/('prism_m66_report.py' if mode=='report' else 'prism_m66_followup.py')
            argv=[py,'-B',str(script)]+([] if mode=='report' else [mode])
            with (out/(mode+'.stdout.log')).open('wb') as stdout,(out/(mode+'.stderr.log')).open('wb') as stderr:
                with ProcessTree(cpu_seconds=20000,memory_bytes=8*1024**3,max_processes=32) as tree:
                    tree.start(argv,cwd=ROOT,stdout=stdout,stderr=stderr)
                    resources=tree.wait(wall_seconds=min(7200,remaining),storage_root=ROOT/'evaluation',max_storage_bytes=48*1024**3,
                        snapshot=lambda counters:publish(resources=counters))
            if resources['returncode']!=0 or resources['stop_reason']:raise ValueError('followup phase failed: '+mode)
            write(out/(mode+'.completion.json'),{'status':'PASS','resources':resources,'completed_at':time.time()})
        publish(state='COMPLETED',phase='COMPLETE_RESULTS_AND_REPORTS',finished_at=time.time())
        write(out/'completion.json',state)
    except BaseException as error:
        publish(state='FAILED_STOPPED_NO_RETRY',error=repr(error),finished_at=time.time());raise


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('run','audit','audit-engineering','arena','direct'));a=p.parse_args()
    value=run() if a.mode=='run' else audit(a.mode=='audit-engineering') if a.mode in ('audit','audit-engineering') else arena_stage(a.mode=='direct')
    print(json.dumps(value,ensure_ascii=False))
