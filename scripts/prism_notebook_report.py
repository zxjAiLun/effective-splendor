"""Read-only replay verification and full model-oriented Notebook arena reports."""
from collections import Counter, defaultdict
import html
from pathlib import Path
import subprocess
import time

import markdown
import numpy as np
from scripts import prism_match_details as details
from scripts import prism_ppo_fixed_eval as fixed

read, write, sha, require = fixed.read_json, fixed.atomic_json, fixed.sha256_file, fixed._require


def interval(rows, pure=False):
    paired=defaultdict(dict)
    for r in rows:
        require(r['candidate_seat'] not in paired[r['seed']], 'duplicate paired seat')
        paired[r['seed']][r['candidate_seat']]=float(r['record']=='win') if pure else r['candidate_score']
    require(paired and all(set(v)=={0,1} for v in paired.values()),'incomplete paired seats')
    blocks=np.array([sum(v.values())/2 for _,v in sorted(paired.items())]);rng=np.random.default_rng(64049999)
    # Bound the bootstrap index allocation even with many seed blocks.
    width=max(1,min(128,1024*1024//len(blocks)));samples=[]
    for start in range(0,20000,width):
        samples.extend(blocks[rng.integers(0,len(blocks),(min(width,20000-start),len(blocks)))].mean(1))
    return dict(estimate=float(blocks.mean()),ci95=np.quantile(samples,[.025,.975]).tolist(),seed_blocks=len(blocks),
                samples=20000,seed=64049999,scope='descriptive paired seed bootstrap; one-block intervals are degenerate')


def table(headers,rows):
    def safe(v):return str(v).replace('|','\\|').replace('\n',' ')
    return '\n'.join(['| '+' | '.join(map(safe,headers))+' |','| '+' | '.join(['---']*len(headers))+' |',
                      *['| '+' | '.join(map(safe,r))+' |' for r in rows]])+'\n'


def num(v):return 'NOT_APPLICABLE' if v is None else f'{v:.4f}'


def collect(work,plan,state):
    from scripts.prism_notebook_arena import completed_shard
    groups=defaultdict(list);ledger=[]
    for shard in plan['shards']:
        rows=completed_shard(shard,state['shards'][shard['name']]);out=Path(shard['output'])
        for row in rows:
            p=out/'games'/row['candidate']/row['opponent']/f"seed-{row['seed']}-seat-{row['candidate_seat']}"
            replay=read(p/'replay.json');report=read(p/'report.json');proc=read(p/'process-result.json');game=read(p/'game.json')
            config=read(p/'match-config.json')
            require(fixed.canonical_hash(config)==game['game_config_sha256'],'match config drift')
            verified=fixed._report_result(report,replay,game_id=game['game_id'],seed=row['seed'],seat=row['candidate_seat'],catalog=read(work/'config.json')['catalog_fingerprint'])
            require(all(row[k]==v for k,v in verified.items()),'saved row differs from verified terminal result')
            require(proc['returncode']==0 and proc['wall_seconds']>0,'invalid observed game clock')
            row=dict(row);row['_candidate_actions'],row['_opponent_actions']=Counter(),Counter()
            for step in replay['steps']:
                row['_candidate_actions' if step['actor']==row['candidate_seat'] else '_opponent_actions'][step['action']['type']]+=1
            row.update(_wall_seconds=proc['wall_seconds'],_replay_path=str(p/'replay.json'))
            groups[(row['candidate'],row['opponent'],row['candidate_seat'])].append(row)
            ledger.append(dict(game=str(p/'game.json'),hashes={n:sha(p/n) for n in ('game.json','report.json','replay.json','process-result.json','match-config.json')}))
    require(len(ledger)==plan['total_games'],'full report grid incomplete')
    write(work/'source-ledger.json',ledger);metrics={};audits=work/'metrics';audits.mkdir(exist_ok=True)
    for index,(key,rows) in enumerate(sorted(groups.items())):
        manifest=audits/f'group-{index:04d}.manifest.json';output=audits/f'group-{index:04d}.metrics.json'
        write(manifest,dict(rows=[dict(replay_path=r['_replay_path']) for r in rows]))
        argv=[plan['metrics_program']['path'],str(manifest),str(output)];started=time.monotonic()
        p=subprocess.run(argv,capture_output=True,text=True,timeout=180)
        write(audits/f'group-{index:04d}.receipt.json',dict(argv=argv,exit_code=p.returncode,wall_seconds=time.monotonic()-started,
                    stdout=p.stdout,stderr=p.stderr,manifest_sha256=sha(manifest)))
        require(p.returncode==0,'Rust rules replay verification failed: '+p.stderr)
        metrics[key]=read(output)
    pairs=[]
    for model,opponent in sorted({(m,o) for m,o,_ in groups}):
        rows=groups[(model,opponent,0)]+groups[(model,opponent,1)];cb=[];ob=[];seats=[]
        for seat in (0,1):
            rs=groups[(model,opponent,seat)];raw=metrics[(model,opponent,seat)]
            c=raw['seat_p0_first' if seat==0 else 'seat_p1_second'];o=raw['seat_p1_second' if seat==0 else 'seat_p0_first']
            cb.append((c,len(rs)));ob.append((o,len(rs)))
            seats.append(dict(candidate_seat=seat,candidate=details.merge_player([(c,len(rs))],rs,True),
                              opponent=details.merge_player([(o,len(rs))],rs,False)))
        pairs.append(dict(candidate=model,opponent=opponent,candidate_metrics=details.merge_player(cb,rows,True),
            opponent_metrics=details.merge_player(ob,rows,False),seats=seats,macro=details.macro(rows),
            win_ci=interval(rows,True),score_ci=interval(rows)))
    return pairs


def report(work,plan,state):
    work=Path(work).resolve();pairs=collect(work,plan,state)
    lines=['# Prism 通用对战结果（DSW / SSH）','', '**产物：已完成全部固定网格，Rust规则回放验核与双方指标守恒通过。**','',
        '**竞技：DEVELOPMENT_ONLY_NOT_PROMOTED。**这是独立通用开发测量，没有执行任何里程碑正式晋级门。','',
        '**风格：描述性数据。**不凭单一更高/更低经济指标授予风格身份。','',
        '候选按用户声明的完整模型名及导出SHA识别，未发布检查点仍须在名称中明确标注。每对手恰好双座种子块；个人表按模型身份归并，物理P0不总是候选。',
        '', '## 候选匹配比较','']
    config=read(work/'config.json');baseline=next(iter(config['candidates']));by={(p['candidate'],p['opponent']):p for p in pairs}
    comparison=[]
    for p in pairs:
        if p['candidate']==baseline:continue
        b=by[(baseline,p['opponent'])]
        for key,label,unit in [('score_rate','半平得分率','百分点'),('mean_prestige','本人最终VP','VP/局'),
                               ('vp_per_main_action','本人得分速度','VP/Main'),('mean_permanent_bonuses','本人永久折扣','个/局')]:
            old,new=b['candidate_metrics'][key],p['candidate_metrics'][key];scale=100 if key=='score_rate' else 1;delta=(new-old)*scale
            comparison.append([plan['candidates'][p['candidate']]['display_name'],plan['opponents'][p['opponent']]['display_name'],label,unit,
                num(old*scale),num(new*scale),f'**{"↑" if delta>0 else "↓" if delta<0 else "="} {delta:+.4f}**'])
    lines.append(table(['候选','共同对手','本人指标','单位','首候选基线','候选','候选−基线'],comparison) if comparison else
                 '只有一个候选，匹配基线到候选比较NOT_APPLICABLE。')
    lines+=['↑/↓仅为方向标记，不表示更好或差异显著。下面CI为逐对手描述性双座bootstrap；不做多门验收或发布。若只有一个种子块，CI退化，不能据此确认稳定性。','',
            '## 总体执行与来源','',table(['字段','记录'],[
                ['固定局数',plan['total_games']],['并发进程 / 每进程库线程',f"{plan['limits']['workers']} / 1"],
                ['累计已测活动墙钟秒（至报告前监测点）',num(state.get('elapsed_wall_seconds',0))],
                ['首次派发至报告生成秒（包含暂停）',num(time.time()-state['started_at'])],
                ['时钟范围',plan['clock_scope']],['资源监控',plan['profile']['limit_scope']],
                ['已测负载',state.get('resources',{})],['逐决策 / 推理延迟','NOT_MEASURED / NOT_MEASURED'],
                ['配置SHA256',plan['config_sha256']],['plan SHA256',sha(work/'plan.json')],
                ['engine SHA256',config['engine']['sha256']],['metrics SHA256',plan['metrics_program']['sha256']],
                ['Git基线 / 源码dirty',f"{plan['provenance']['git_head']} / {plan['provenance']['dirty_worktree']}"],
                ['Bootstrap',plan['bootstrap']],['种子',config['seeds']],['完整逐局来源', 'source-ledger.json'],
                ['冻结源码SHA',plan['source_hashes']]])]
    for p in pairs:
        m,o=p['candidate'],p['opponent'];a,b=p['candidate_metrics'],p['opponent_metrics'];macro=p['macro']
        lines+=['', '## '+plan['candidates'][m]['display_name']+' 对阵 '+plan['opponents'][o]['display_name'], '',
            f"被测模型模式：{plan['candidates'][m]['mode']}（sample=T=1）；对手模式：{plan['opponents'][o]['mode']}。下表个人指标分别属于模型/对手，整局指标另列。",
            '',table(['局数/双座种子块','胜/平/负','纯胜率','半平得分率','纯胜配对95%CI','半平配对95%CI'],[[
                f"{a['games']}/{p['score_ci']['seed_blocks']}",f"{a['wins']}/{a['ties']}/{a['losses']}",
                f"{a['win_rate_percent']:.4f}%",f"{100*a['score_rate']:.4f}%",
                ' / '.join(f'{100*x:.4f}%' for x in p['win_ci']['ci95']),' / '.join(f'{100*x:.4f}%' for x in p['score_ci']['ci95'])]]),
            table(['模型物理座位','局数','胜/平/负','纯胜%','半平%','模型VP/局','对手VP/局'],[
                [f"P{s['candidate_seat']}（{'先' if s['candidate_seat']==0 else '后'}手）",s['candidate']['games'],
                 f"{s['candidate']['wins']}/{s['candidate']['ties']}/{s['candidate']['losses']}",
                 num(s['candidate']['win_rate_percent']),num(100*s['candidate']['score_rate']),num(s['candidate']['mean_prestige']),num(s['opponent']['mean_prestige'])] for s in p['seats']])]
        metrics=[('最终VP/局','mean_prestige'),('VP/本人全部决策','vp_per_turn'),('VP/本人Main','vp_per_main_action'),('VP/全局ply','vp_per_ply'),
                 ('永久折扣/购卡每局','mean_permanent_bonuses'),('贵族/局','mean_nobles'),('获得贵族的对局%','games_with_nobles_percent'),
                 ('预留获取/局','mean_reserves_acquired'),('预留买回/局','mean_reserves_bought'),('终局未买回预留/局','mean_reserves_stranded'),
                 ('预留买回/获取%（总分母）','reserve_redemption_rate_percent')]
        personal=[[label,num(a[key]),num(b[key])] for label,key in metrics]
        personal += [[f'购入{vp} VP卡/局',num(a['mean_cards_by_vp'][str(vp)]),num(b['mean_cards_by_vp'][str(vp)])] for vp in range(6)]
        personal += [[f'{color}折扣/局',num(a['mean_bonuses_by_color'][color]),num(b['mean_bonuses_by_color'][color])] for color in details.COLORS]
        lines.append(table(['个人指标','被测模型','对手'],personal))
        lines.append(table(['动作 / 占本人全部决策','模型次数 / %','对手次数 / %'],[[action,
            f"{a['action_distribution'][action]} / {a['action_percentages'][action]:.4f}%",
            f"{b['action_distribution'][action]} / {b['action_percentages'][action]:.4f}%"] for action in details.ACTIONS]))
        lines.append(table(['整局 / 两人共同指标','值'],[
            ['总 / 均ply',f"{macro['total_plies']} / {macro['mean_plies']:.4f}"],
            ['legacy决策轮：均 / 最小 / 中位 / 最大 / 总体SD',' / '.join(num(macro[k]) for k in ['mean_turns','min_turns','median_turns','max_turns','std_turns'])],
            ['Main轮均值',num(macro['mean_main_rounds'])],['绝对终局分差',num(macro['mean_victory_margin'])],['分差≤2对局%',num(macro['close_games_margin_le_2_percent'])],
            ['对局监督墙钟秒：累计 / 均 / P95',' / '.join(num(macro[k]) for k in ['process_wall_seconds_sum','process_wall_seconds_mean','process_wall_seconds_p95'])],
            ['逐决策 / 推理延迟','NOT_MEASURED / NOT_MEASURED']]))
        lines.append('单局时间含启动、比赛、输出；累计单局秒数包含并行重叠，不等于整批墙钟。')
        lines.append(table(['身份','源码绑定的完整descriptor'],[['模型',config['candidates'][m]],['对手',config['opponents'][o]]]))
    text='\n\n'.join(lines)+'\n';fixed._atomic_text(work/'report.md',text)
    body=markdown.markdown(text,extensions=['tables','fenced_code']);body=body.replace('<table>','<div class="scroll"><table>').replace('</table>','</table></div>')
    css='body{font:16px/1.7 system-ui;color:#183238;background:#f5f8f7;max-width:1200px;margin:auto;padding:30px}h1,h2{color:#135d54}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;background:white}td,th{border:1px solid #d8e3df;padding:9px;text-align:left;overflow-wrap:anywhere}th{background:#e8f1ee}.scroll{overflow:auto;margin:18px 0}strong{color:#075d52}code{overflow-wrap:anywhere}'
    fixed._atomic_text(work/'report.html','<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Prism DSW对战报告</title><style>'+css+'</style></head><body>'+body+'</body></html>')
    write(work/'result.json',dict(format='prism-notebook-arena-result-v1',verdict='DEVELOPMENT_ONLY_NOT_PROMOTED',
        formal_acceptance='NOT_RUN',style_acceptance='NOT_RUN',games=plan['total_games'],pairs=pairs,
        config_sha256=plan['config_sha256'],plan_sha256=sha(work/'plan.json'),source_ledger_sha256=sha(work/'source-ledger.json'),
        bootstrap=plan['bootstrap'],runtime=state.get('resources',{}),measured_elapsed_before_report_seconds=time.time()-state['started_at']))
