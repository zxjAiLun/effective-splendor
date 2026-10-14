"""M79 finite greedy grid, independent dispatch ledger and interrupted-job recovery."""
from __future__ import annotations
import argparse, hashlib, json, os
from pathlib import Path
import subprocess, sys, time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from training.prism_portable.common import read,write,digest,lock
from scripts.prism_m79_run import verify,bounds,PLAN
from scripts import prism_bounded_eval as b,prism_notebook_arena as arena

def candidates():
    c,_=verify();proof=read(ROOT/'audits/a/audit.json');p=ROOT/'campaigns/a/cycle-20-export/weights.json'
    if proof['status']!='PASS_TRAINING_ARTIFACT_AUDIT' or digest(p)!=proof['weights_sha256']:raise ValueError('candidate audit drift')
    row=dict(status='FROZEN_FINAL_C20_BEFORE_EVALUATION',parent_sha256=c['assets']['parent']['sha256'],selection='fixed final c20; no independent feedback',models={'a':dict(path=str(p),sha256=digest(p),audit_sha256=digest(ROOT/'audits/a/audit.json'))})
    dest=ROOT/'candidate-registry.json'
    if dest.exists():
        if read(dest)!=row:raise ValueError('frozen candidate drift')
    else:write(dest,row)
    return row

def config(model,opponent,seeds,development=False):
    c=read(ROOT/PLAN);engine=ROOT/'bin/splendor';seed=c['development' if development else 'evaluation']['action_seed']
    path=ROOT/'inputs/parent.json' if model=='base' else ROOT/'inputs/style-reference.json' if model=='style-reference' else ROOT/'campaigns/a'/f'cycle-{model.removeprefix("curve-c") if model.startswith("curve-c") else 20}-export/weights.json'
    candidate=arena.model(path,model,engine,mode='greedy',action_seed=seed)['descriptor']
    opp=arena.heuristic(engine,'Heuristic v0.3.1',seed)['descriptor'] if opponent=='heuristic' else arena.model(ROOT/f'inputs/{opponent}.json',opponent,engine,mode='greedy',action_seed=seed)['descriptor']
    return dict(format='prism-ppo-fixed-eval-v1',engine=dict(program=str(engine),sha256=digest(engine)),catalog_fingerprint=read(ROOT/'inputs/parent.json')['catalog_fingerprint'],action_seed=seed,seeds=seeds,candidates={model:candidate},opponents={opponent:opp},timeouts=dict(game_wall_seconds=90,handshake_timeout_ms=10000,move_timeout_ms=10000,shutdown_grace_ms=1000))

def freeze(label,cfg,category):
    p=ROOT/'evaluation-configs'/label;dest=ROOT/'evaluation'/label
    count=len(cfg['seeds'])*2
    if dest.exists():
        validated,_=b.load_bound(dest)
        if validated['config']!=cfg:raise ValueError('existing shard differs from frozen config')
    else:
        write(p.with_suffix('.json'),cfg)
        policy=dict(format=b.FORMAT,max_games=count,max_truncated_games=count,ply_cap=512,deadline_unix=read(ROOT/'round-budget.json')['deadline'],cpu_seconds=4000,memory_bytes=2*1024**3,storage_bytes=128*1024**2,max_processes=12,automatic_game_retries=0)
        write(p.with_suffix('.policy.json'),policy);b.prepare(p.with_suffix('.json'),p.with_suffix('.policy.json'),dest)
    return dict(label=label,category=category,output=str(dest),planned_games=count,manifest_sha256=digest(dest/'manifest.json'))

def scientific_caps(category):
    total=0
    for p in (ROOT/'evaluation').glob('*/ledger.json'):
        is_dev=p.parent.name.startswith('development-')
        if is_dev!=(category=='development'):continue
        total+=sum(e.get('kind')=='PLY_CAP_TRUNCATED' for e in read(p)['entries'].values())
    return total

def global_retry(key):
    with lock(ROOT/'retry-control'):
        path=ROOT/'infrastructure-retries.json';rows=read(path) if path.exists() else []
        if any(r['logical_key']==key for r in rows):raise ValueError('per-job retry exhausted')
        # Training retries and evaluation retries share one 64-attempt ceiling.
        from training.prism_portable.engine.ppo.store import CommitStore
        from scripts.prism_m67_storage import install
        install();spec=read(ROOT/'campaigns/a/contract.json')
        training=CommitStore(ROOT/'campaigns/a/launch-ledger',spec['run']['arena_contract_sha256']).load()[1]['retries']
        if training+len(rows)>=64:raise ValueError('whole-round infrastructure extra-attempt budget exhausted')
        rows.append(dict(logical_key=key,observed_at=time.time()));write(path,rows)

def grid(output):
    """An immutable resolved game is adopted; only an unpublished interruption retries."""
    output=Path(output).resolve();category='development' if output.name.startswith('development-') else 'independent'
    with lock(output/'m79-dispatch-owner'):
        validated,policy=b.load_bound(output);path=output/'ledger.json'
        ledger=read(path) if path.exists() else dict(execution_state='RUNNING',entries={},consumed_cpu_seconds=0.,manifest_sha256=digest(output/'manifest.json'))
        if ledger['manifest_sha256']!=digest(output/'manifest.json'):raise ValueError('ledger manifest drift')
        if ledger['execution_state']=='FINISHED':return b.inspect(output)
        if any(e.get('kind')=='UNKNOWN_OR_RESOURCE_FAILURE' for e in ledger['entries'].values()):raise ValueError('hard retained evaluation failure')
        ledger['execution_state']='RUNNING';write(path,ledger)
        try:
            for job in b.legacy.jobs(validated['config']):
                key=b.fixed._game_key(*job);directory=b.legacy.game_directory(output,job)
                prior=ledger['entries'].get(key)
                if prior and prior['state'] in ('COMPLETED','RETAINED_FAILURE'):
                    if prior['state']=='RETAINED_FAILURE' and prior.get('kind')!='PLY_CAP_TRUNCATED':raise ValueError('scientific failure is not retryable')
                    continue
                bounds()
                if scientific_caps(category)>8:break
                if directory.exists():
                    if (directory/'process-result.json').exists() and (directory/'report.json').exists():
                        resources=read(directory/'process-result.json')
                        cpu=b.validate_resources(resources,b.rollout_command(validated,policy,directory))
                        if read(directory/'match-config.json')!=b.match_config(validated,job):raise ValueError('saved match drift')
                        entry=b.validate_artifacts(directory,validated['config'],job,512)
                        write(directory/'game.json',entry)
                        ledger['entries'][key]=dict(entry,evidence_sha256=b.evidence(directory));ledger['consumed_cpu_seconds']+=cpu;write(path,ledger);continue
                    # A saved terminal/cap or malformed result is never replayed.
                    if any((directory/n).exists() for n in ('game.json','replay.json','prefix.json','report.json')):raise ValueError('incomplete publication of scientific result; preserve without retry')
                    for p in directory.glob('process-identity.json'):
                        import psutil
                        from scripts.prism_dsw_ppo_process import same_process
                        r=read(p)
                        if same_process(r['pid'],r['create_time']):raise ValueError('owned orphan still live; no duplicate dispatch')
                    global_retry(output.name+'/'+key)
                    history=output/'recovery-attempts'/hashlib.sha256(key.encode()).hexdigest();history.parent.mkdir(exist_ok=True)
                    directory.rename(history)
                    charge=30. # Each M79 game receives an explicit 30 CPU-second process-tree cap.
                    ledger['consumed_cpu_seconds']+=charge
                    write(history/'interruption.json',dict(kind='INFRASTRUCTURE_ABORT',logical_key=key,cpu_charge=charge,original_evidence=b.evidence(history)))
                remaining=policy['cpu_seconds']-ledger['consumed_cpu_seconds']
                if remaining<=0:raise ValueError('shard CPU budget exhausted')
                ledger['entries'][key]={'state':'DISPATCHED'};write(path,ledger)
                try:entry=b.evaluate(validated,policy,output,job,min(30.,remaining))
                except BaseException as error:
                    ledger['entries'][key]=dict(state='RETAINED_FAILURE',kind='UNKNOWN_OR_RESOURCE_FAILURE',error=repr(error),evidence_sha256=b.evidence(directory))
                    ledger['consumed_cpu_seconds']=policy['cpu_seconds'];write(path,ledger);raise
                ledger['consumed_cpu_seconds']+=entry.pop('cpu_seconds');ledger['entries'][key]=dict(entry,evidence_sha256=b.evidence(directory));write(path,ledger)
            ledger['execution_state']='FINISHED' if len(ledger['entries'])==len(b.legacy.jobs(validated['config'])) else 'STOPPED'
            if ledger['execution_state']=='STOPPED':ledger['stop_reason']='SCIENTIFIC_CAP_BUDGET'
        finally:
            write(path,ledger);write(output/'grid-status.json',b.summary(validated['config'],ledger))
        return b.summary(validated['config'],ledger)

def dispatch(shards,category):
    c,p=verify();limit=min(8,len(os.sched_getaffinity(0)),p['binding']['cpu_quota_cores']);pending=[];active={};done=[]
    for s in shards:
        path=Path(s['output'])/'ledger.json'
        if path.exists() and read(path)['execution_state']=='FINISHED':done.append(dict(s,grid=b.inspect(s['output'])))
        else:pending.append(s)
    start=time.time();status=ROOT/f'{category}-progress.json'
    try:
        while pending or active:
            bounds()
            if scientific_caps(category)>8:pending.clear()
            while pending and len(active)<limit:
                s=pending.pop(0);stream=(Path(s['output'])/'worker.log').open('ab')
                proc=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'grid','--output',s['output']],cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
                active[proc.pid]=(proc,stream,s)
            for pid,(proc,stream,s) in list(active.items()):
                if proc.poll() is None:continue
                stream.close();del active[pid]
                if proc.returncode:raise ValueError('hard shard failure '+s['label'])
                done.append(dict(s,grid=read(Path(s['output'])/'grid-status.json')))
            write(status,dict(state='RUNNING',observed_at=time.time(),completed_shards=len(done),total_shards=len(shards),completed_games=sum(s['grid']['completed_games'] for s in done),truncated_games=scientific_caps(category),active_pids=list(active),elapsed_seconds=time.time()-start))
            time.sleep(.5)
    finally:
        for proc,stream,s in active.values():proc.terminate()
        for proc,stream,s in active.values():
            try:proc.wait(timeout=15)
            finally:stream.close()
    return done

def make_grid(development=False):
    c,_=verify();e=c['evaluation'];shards=[]
    if development:
        lo,hi=c['development']['seed_range']
        groups=[(f'curve-c{cycle}','parent',lo,hi) for cycle in c['development']['checkpoints']]
    else:
        groups=[(actor,op,lo,hi) for actor in e['common_actors'] for op,(lo,hi) in e['common_seed_by_opponent'].items()]
        groups += [(actor,op,lo,hi) for actor in e['coverage_actors'] for op,(lo,hi) in e['coverage_seed_by_opponent'].items()]
        groups += [('a','parent',*e['direct']['seed_range'])]
    for model,op,lo,hi in groups:
        for start in range(lo,hi+1,32):
            label=('development-' if development else '')+f'{model}-{op}-{start}'
            shards.append(freeze(label,config(model,op,list(range(start,min(start+32,hi+1))),development),'development' if development else 'independent'))
    if sum(s['planned_games'] for s in shards)!=(1024 if development else 12288):raise ValueError('generated evaluation grid count drift')
    return shards

def curve():
    shards=make_grid(True);out=ROOT/'development';out.mkdir(exist_ok=True)
    write(out/'plan.json',dict(shards=shards,total_games=1024,role='fixed descriptive curve; no selection',config_sha256=digest(ROOT/PLAN)))
    done=dispatch(shards,'development');rows=[]
    for s in shards:
        path=Path(s['output'])/'ledger.json'
        if path.exists():rows += [r['row'] for r in read(path)['entries'].values() if r['state']=='COMPLETED']
    curve=[]
    for cycle in (5,10,15,20):
        selected=[r for r in rows if r['candidate']==f'curve-c{cycle}'];n=len(selected)
        curve.append(dict(cycle=cycle,training_attempts=cycle*256,completed_games=n,planned_games=256,wins=sum(r['candidate_score']==1 for r in selected),draws=sum(r['candidate_score']==.5 for r in selected),losses=sum(r['candidate_score']==0 for r in selected),descriptive_half_draw_score=sum(r['candidate_score'] for r in selected)/n if n else None,complete=n==256,weights_sha256=digest(ROOT/f'campaigns/a/cycle-{cycle}-export/weights.json')))
    result=dict(format='prism-m79-development-v1',curve=curve,role='descriptive only; fixed c20',games=len(rows),planned_games=1024)
    write(out/'rows.json',rows);write(out/'curve.json',result);write(out/'completion.json',dict(shards=done,completed_games=len(rows)))
    table=[];md=['# M79 固定检查点开发曲线','','仅用于描述训练走势；最终候选固定为 c20，独立评测不参与选择。','','| 检查点 | 训练尝试 | 有效局 / 计划局 | 胜 / 平 / 负 | 半平得分 |','| --- | ---: | ---: | --- | ---: |']
    for row in curve:
        score=f"{row['descriptive_half_draw_score']:.2%}" if row['descriptive_half_draw_score'] is not None else 'NOT_MEASURED'
        cells=[f"c{row['cycle']}",str(row['training_attempts']),f"{row['completed_games']} / 256",f"{row['wins']} / {row['draws']} / {row['losses']}",score]
        md.append('| '+' | '.join(cells)+' |');table.append('<tr>'+''.join('<td>'+cell+'</td>' for cell in cells)+'</tr>')
    md+=['','半平得分 = (胜 + 0.5 × 平) / 有效终局数。截断和缺项保留，不计为平局。','',f"曲线数据 SHA256：`{digest(out/'curve.json')}`"]
    (out/'curve.md').write_text('\n'.join(md)+'\n',encoding='utf-8')
    (out/'curve.html').write_text('<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>M79 开发曲线</title><style>body{font:16px/1.7 system-ui;margin:24px auto;padding:16px;max-width:1000px;color:#18283a;background:#f6f8fb}.scroll{overflow:auto}table{border-collapse:collapse;min-width:650px;width:100%;background:white}td,th{text-align:left;padding:12px;border-bottom:1px solid #dbe2ec}code{overflow-wrap:anywhere}h1{font-size:28px}@media(max-width:600px){body{margin:0;padding:16px}}</style><h1>M79 固定检查点开发曲线</h1><p>描述训练走势；最终候选固定为 c20，独立评测不参与选择。</p><div class="scroll"><table><thead><tr><th>检查点</th><th>训练尝试</th><th>有效局 / 计划局</th><th>胜 / 平 / 负</th><th>半平得分</th></tr></thead><tbody>'+''.join(table)+'</tbody></table></div><p>半平得分 = (胜 + 0.5 × 平) / 有效终局数。截断和缺项保留，不计为平局。</p><p>数据 SHA256：<code>'+digest(out/'curve.json')+'</code></p></html>',encoding='utf-8')
    return result

def evaluate():
    candidates();shards=make_grid();plan=dict(format='prism-m79-bounded-shards-v1',shards=shards,total_games=12288,plan_sha256=digest(ROOT/PLAN),candidate_registry_sha256=digest(ROOT/'candidate-registry.json'))
    dest=ROOT/'evaluation-plan.json'
    if dest.exists() and read(dest)!=plan:raise ValueError('grid binding drift')
    write(dest,plan);done=dispatch(shards,'independent')
    result=dict(status='FINISHED_WITH_EXPLICIT_MISSINGNESS',shards=done,completed_games=sum(s['grid']['completed_games'] for s in done),truncated_games=scientific_caps('independent'),plan_sha256=digest(dest),finished_at=time.time())
    write(ROOT/'evaluation-completion.json',result);return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['candidates','curve','evaluate','grid']);parser.add_argument('--output');args=parser.parse_args()
    print(json.dumps(grid(args.output) if args.mode=='grid' else globals()[args.mode](),ensure_ascii=False),flush=True)
