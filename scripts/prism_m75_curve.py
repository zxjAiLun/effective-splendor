"""Fixed four-checkpoint development curve; independent confirmation stays separate."""
from pathlib import Path
import html,json,sys,time
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from training.prism_portable.common import read,write,digest
from scripts.prism_m75_run import verify
from scripts.prism_m75_evaluate import config,freeze_shard,dispatch
from scripts.prism_m75_report import blocks
from scripts.prism_m70_report import measure

def render_curve(result,out):
    lines=['# M75 阶段棋力曲线','','四个检查点均与同一父代 Balance v0.2.3 双方 greedy 对战；同一组128个双座种子。仅描述趋势，最终候选固定 c20。','','| 检查点 | 训练局 | 终局数 | W/D/L | 半平得分 | 配对95%区间 |','| --- | --- | --- | --- | --- | --- |']
    for row in result['curve']:
        n=row['completed_games'];rate=(row['wins']+.5*row['draws'])/n if n else None;s=row['paired_statistics']
        interval=' / '.join(f'{v:.2%}' for v in s['ci95']) if s else '配对不完整'
        lines.append(f"| c{row['cycle']} | {row['cycle']*256} | {n}/256 | {row['wins']}/{row['draws']}/{row['losses']} | {rate:.2%} | {interval} |" if rate is not None else f"| c{row['cycle']} | {row['cycle']*256} | 0/256 | 0/0/0 | 未测 | 未测 |")
    lines+=['','半平得分=(W+0.5D)/终局数。截断不计平局；缺双座配对时不显示完整配对区间。该开发集独立于最终9216局确认，不选择检查点。','',f"网格：{result['grid']}；缺项：{len(result['missing'])}。"]
    text='\n'.join(lines)+'\n';out.parent.mkdir(parents=True,exist_ok=True);out.with_suffix('.md').write_text(text,encoding='utf-8')
    import markdown
    bars=''.join(f"<div>c{r['cycle']} · {r['cycle']*256}训练局 <progress max='1' value='{(r['wins']+.5*r['draws'])/r['completed_games'] if r['completed_games'] else 0}'></progress> {(r['wins']+.5*r['draws'])/r['completed_games']:.2%}</div>" for r in result['curve'] if r['completed_games'])
    out.write_text('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{font:16px system-ui;max-width:1000px;margin:32px auto;padding:16px}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:10px}progress{width:35%;margin:12px}pre{overflow:auto}</style>'+markdown.markdown(text,extensions=['tables'])+bars,encoding='utf-8')

def build():
    c,_=verify(training=False);dev=c['development'];out=ROOT/'development'
    if out.exists():raise ValueError('development already attempted')
    out.mkdir();registry=read(ROOT/'candidate-registry.json');models={};shards=[]
    for cycle in dev['checkpoints']:
        key=f'curve-c{cycle}';path=ROOT/f'campaigns/a/cycle-{cycle}-export/weights.json'
        weight=read(path)
        if weight['format']!='prism-weights-v1' or len(weight['state_dict'])!=32:raise ValueError('invalid development export')
        for row in weight['state_dict'].values():
            a=np.asarray(row['data'],dtype='<f4')
            if a.size!=int(np.prod(row['shape'])) or not np.isfinite(a).all():raise ValueError('invalid development tensor')
        models[key]={'cycle':cycle,'path':str(path),'sha256':digest(path)}
        for start in range(dev['seed_start'],dev['seed_end']+1,32):
            shards.append(freeze_shard(f'development-{key}-{start}',config([key],['parent'],list(range(start,min(start+32,dev['seed_end']+1)))),c['evaluation']['ply_cap']))
    if models['curve-c20']['sha256']!=registry['models']['a']['sha256']:raise ValueError('final frozen candidate drift')
    write(out/'plan.json',{'models':models,'shards':shards,'total_games':dev['total_games'],'config_sha256':digest(ROOT/'benchmarks/m75-prism-continuation.config.json'),'candidate_registry_sha256':digest(ROOT/'candidate-registry.json')})
    done=dispatch(shards,truncation_limit=dev['max_truncated_games']);rows=[];missing=[]
    for shard in shards:
        ledger=read(Path(shard['output'])/'ledger.json')
        for key,entry in ledger['entries'].items():
            if entry['state']=='COMPLETED':rows.append(entry['row'])
            else:missing.append({'shard':shard['label'],'key':key,'kind':entry.get('kind')})
    if len(rows)+len(missing)!=dev['total_games']:raise ValueError('development count drift')
    curve=[]
    for key,model in models.items():
        selected=[r for r in rows if r['candidate']==key];scores=blocks(rows,key,'parent',range(dev['seed_start'],dev['seed_end']+1))
        stats=measure(scores,75049999,20000,.025) if scores is not None else None
        curve.append(dict(model,completed_games=len(selected),wins=sum(r['candidate_score']==1 for r in selected),draws=sum(r['candidate_score']==.5 for r in selected),losses=sum(r['candidate_score']==0 for r in selected),paired_statistics=stats))
    result={'format':'m75-development-curve-v1','finished_at':time.time(),'curve':curve,'missing':missing,'grid':'INCOMPLETE' if missing else 'COMPLETE','role':dev['role'],'final_candidate_unchanged':digest(ROOT/'campaigns/a/cycle-20-export/weights.json')==registry['models']['a']['sha256'],'new_training_updates':0}
    write(out/'rows.json',rows);write(out/'completion.json',{'shards':done,'completed_games':len(rows),'missing':len(missing)});write(out/'curve.json',result)
    render_curve(result,ROOT/'docs/prism/m75-prism-continuation-curve.html')
    return {'status':'DEVELOPMENT_CURVE_COMPLETE','completed_games':len(rows),'missing':len(missing)}
if __name__=='__main__':print(json.dumps(build()))
