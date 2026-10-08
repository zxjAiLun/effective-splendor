"""Readable M55 records from verified metrics. Never dispatches games."""
from pathlib import Path
import json
import math
from scripts.prism_rush_round import ART, ROOT, PILOT, TRAIN, RESULT, DISPLAY, read, write, sha, require

START='<!-- M55 VERIFIED RESULTS BEGIN -->'
END='<!-- M55 VERIFIED RESULTS END -->'


def table(headers, rows):
    return '\n'.join(['| '+' | '.join(map(str,headers))+' |','| '+' | '.join(['---']*len(headers))+' |',
                      *['| '+' | '.join(map(str,row))+' |' for row in rows]])+'\n'


def pct(x):
    return f'{100*x:.4f}%'


def pair_cell(p, getter):
    return getter(p['candidate_metrics'])+' / '+getter(p['opponent_metrics'])


def detailed_tables(pairs, title):
    out=[f'### {title}',
         '“模型”列是被测玩家；对手列注明动作模式。个人指标每格为“被测模型 / 对手”。节奏是该模型对阵该对手的整局指标。纯胜率=胜/局数，得分率=(胜+0.5平)/局数。']
    out.append(table(['模型（T=1）','对手','局数 / 双座种子数','胜 / 平 / 负','纯胜率','得分率','描述性配对95%区间'],
                     [[DISPLAY[p['candidate']],DISPLAY[p['opponent']],f"{p['macro']['total_games']} / {p['macro']['total_games']//2}",
                       f"{p['candidate_metrics']['wins']} / {p['candidate_metrics']['ties']} / {p['candidate_metrics']['losses']}",
                       f"{p['candidate_metrics']['win_rate_percent']:.4f}%",pct(p['candidate_metrics']['score_rate']),
                       '['+', '.join(pct(x) for x in p['score_uncertainty']['ordinary_95_ci'])+']'] for p in pairs]))
    out.append('#### 双座明细')
    out.append(table(['模型','对手','本模型座位','局数','胜 / 平 / 负','得分率','局均VP（模型 / 对手）'],
                     [[DISPLAY[p['candidate']],DISPLAY[p['opponent']],('先手 P0' if s['candidate_seat']==0 else '后手 P1'),
                       s['candidate']['games'],f"{s['candidate']['wins']} / {s['candidate']['ties']} / {s['candidate']['losses']}",
                       pct(s['candidate']['score_rate']),f"{s['candidate']['mean_prestige']:.3f} / {s['opponent']['mean_prestige']:.3f}"] for p in pairs for s in p['seats']]))
    out.append('#### 对局节奏与风格')
    out.append(table(['模型 / 对手','局均步数','决策轮：均值 / 最短 / 中位 / 最长','轮标准差','Main轮均值','终局绝对分差','分差≤2','Rush AUC','20 Main内8VP'],
                     [[DISPLAY[p['candidate']]+' / '+DISPLAY[p['opponent']],f"{p['macro']['mean_plies']:.3f}",
                       f"{p['macro']['mean_turns']:.3f} / {p['macro']['min_turns']} / {p['macro']['median_turns']} / {p['macro']['max_turns']}",
                       f"{p['macro']['std_turns']:.3f}",f"{p['macro']['mean_main_rounds']:.3f}",f"{p['macro']['mean_victory_margin']:.3f}",
                       f"{p['macro']['close_games_margin_le_2_percent']:.2f}%",f"{p['mean_rush_auc']:.5f}",pct(p['vp8_by_main20_rate'])] for p in pairs]))
    out.append('Rush AUC/20 Main列为被测玩家；短于16自身Main的AUC按终局分补足固定窗口。legacy决策轮=ceil(全动作步数/2)，含贵族选择；Main轮排除贵族选择。风格两项之外的经济数据为新增描述性指标。')
    headers=['个人指标：模型 / 对手']+[DISPLAY[p['candidate']]+' 对阵 '+DISPLAY[p['opponent']] for p in pairs]
    metrics=[('局均最终VP','mean_prestige'),('VP / 自身决策（含贵族选择）','vp_per_turn'),('VP / 自身Main','vp_per_main_action'),
             ('VP / 全局步数','vp_per_ply'),('局均永久折扣 / 购卡','mean_permanent_bonuses'),('局均贵族数','mean_nobles'),
             ('局均预留获取','mean_reserves_acquired'),('局均预留买回','mean_reserves_bought'),('终局未买回预留','mean_reserves_stranded')]
    rows=[[label]+[pair_cell(p,lambda m,k=key:f'{m[k]:.4f}') for p in pairs] for label,key in metrics]
    for label,key in [('获得贵族的对局比例','games_with_nobles_percent'),('预留买回 / 获取','reserve_redemption_rate_percent')]:
        rows.append([label]+[pair_cell(p,lambda m,k=key:'NOT_APPLICABLE' if m[k] is None else f'{m[k]:.3f}%') for p in pairs])
    for vp in map(str,range(6)):
        rows.append(['局均购入 '+vp+' VP卡']+[pair_cell(p,lambda m,v=vp:f"{m['mean_cards_by_vp'][v]:.4f}") for p in pairs])
    for color,label in zip(('White','Blue','Green','Red','Black'),('白','蓝','绿','红','黑')):
        rows.append(['局均 '+label+' 折扣']+[pair_cell(p,lambda m,c=color:f"{m['mean_bonuses_by_color'][c]:.4f}") for p in pairs])
    out+=['#### 双方得分、购卡、折扣、贵族与预留',table(headers,rows)]
    actions=('buy_market','buy_reserved','take_tokens','reserve_market','reserve_deck','choose_noble','pass')
    labels=('买市场','买预留','取宝石','预留市场','预留牌堆','选贵族','跳过')
    rows=[]
    for action,label in zip(actions,labels):
        rows.append([label+' 次数']+[pair_cell(p,lambda m,a=action:str(m['action_distribution'][a])) for p in pairs])
        rows.append([label+' 占自身全部决策']+[pair_cell(p,lambda m,a=action:f"{m['action_percentages'][a]:.3f}%") for p in pairs])
    out+=['#### 全部七类动作',table(headers,rows),'#### 实测计时']
    out.append(table(['模型 / 对手','进程耗时累计s','单局均值s','单局P95s','决策 / 推理延迟'],
                     [[DISPLAY[p['candidate']]+' / '+DISPLAY[p['opponent']],f"{p['macro']['process_wall_seconds_sum']:.3f}",
                       f"{p['macro']['process_wall_seconds_mean']:.4f}",f"{p['macro']['process_wall_seconds_p95']:.4f}",'NOT_MEASURED / NOT_MEASURED'] for p in pairs]))
    out.append('单局时钟包括程序启动、比赛、验核和输出；累计单局秒数含并行重叠，不等于整批墙钟。未记录逐决策/推理延迟，不能填0或由单局时间推算。')
    return '\n\n'.join(out)


def replace_block(path, body):
    p=Path(path);s=p.read_text(encoding='utf-8');block=START+'\n\n'+body+'\n\n'+END
    if START in s:
        require(s.count(START)==s.count(END)==1,'ambiguous generated document boundary')
        a=s.index(START);b=s.index(END)+len(END);s=s[:a]+block+s[b:]
    else:s=s.rstrip()+'\n\n'+block+'\n'
    p.write_text(s,encoding='utf-8')


def finalize_documents(result):
    require(result['physical_games']==4096 and result['training']['games']==1024 and result['acceptance']['games']==2560,'finite report budget')
    require(result['all_six_gates_passed']==all(result['gates'].values()),'verdict/gate disagreement')
    accepted=result['all_six_gates_passed']
    verdict='冲分风格与棋力保护六门全部通过，接受这一个风格迭代。' if accepted else '本轮训练与对战检验完成，但六门未全部通过，保留负结果；不登记正式冲分版本，不自动补局或续训。'
    gates=[]
    for name,m in result['measurements'].items():
        gates.append([name,f"{m['mean']:.6f}",'['+', '.join(f'{x:.6f}' for x in m['ci95'])+']',f"{m['simultaneous_one_sided_lower']:.6f}",'PASS' if result['gates'][name] else 'FAIL'])
    out=[f"# Prism Rush v0.1.0 样机：完整对战数据与验收\n\n状态：**{result['status']}**。完成时间 UTC：{result['completed_at']}。\n\n{verdict}",
         'Prism v0.1.1 是本轮起点及直接对照；它的权重保持冻结。本轮在其 policy/value 参数上新建风格头与优化器，训练四轮，固定只取最终 c4。这里的 Rush 候选是新权重，不是给基座改名。',
         '## 训练与完整预算',
         table(['项目','实际值'],[['训练局数',1024],['训练决策',result['training']['decisions']],['新优化器更新',result['training']['new_steps']],['开发局数',512],['独立验收局数',2560],['总物理局数',4096],['重试',0],['默认替换 / 共享池部署','false / false']]),
         '开发只描述，不用于调参数或选择检查点；独立验收只分析一次，20,000次双座seed块bootstrap，六项单侧下界分位0.05/6。相同索引抽样用于各配对量；六门都要通过。普通95%区间不能替代校正门。',
         '## 独立验收六门',table(['测量','均值','普通95%区间','六门校正单侧下界','门'],gates)]
    for stage,label in [('acceptance','独立验收'),('development','开发评测（描述性）')]:
        out.append(f"## {label}\n\n整批墙钟 {result[stage]['run_receipt']['wall_seconds']:.3f}s；本机4个 BelowNormal进程；每局60s、0 retry。")
        out.append(detailed_tables(result[stage]['pairs'],label+'完整表格'))
    pilot=read(PILOT)
    out+=['## 证据与边界',table(['证据','位置 / SHA256'],[['冻结试验合同',f'`{PILOT.relative_to(ROOT)}` / `{sha(PILOT)}`'],['真实Arena训练合同',f'`{TRAIN.relative_to(ROOT)}` / `{sha(TRAIN)}`'],['固定最终c4',f'`local-artifacts/prism/rush-v0.1.0/campaign/cycle-4-export/weights.json` / `{result["training"]["final_weights_sha256"]}`'],['独立验收结果',f'`{RESULT.relative_to(ROOT)}` / `{sha(RESULT)}`'],['基座 Prism v0.1.1',f'`{pilot["base_model"]["weights_path"]}` / `{pilot["base_model"]["sha256"]}`']]),
           '逐局配置、握手、report/replay/hash与双座grid已复核；Rust按真实规则离线重演全部开发/验收回放。规则/catalog、固定greedy锚点、Arena和抽样runtime的完整SHA见训练合同和 controller-contract。动作seed55020001；开发9490000..9490063，独立验收9500000..9500255，均未训练。逐对手95%区间为描述性20,000次seed块bootstrap，RNG54049999；正式六门RNG55029999。没有独立reviewer结论、共享池/Elo写入或Git发布。',
           '## 结论与下一步',verdict+' 本轮到此停止；新候选、追加训练或新的验收需要另定范围。公开得分速度不等同于所有场景的主观风格；保留全部原始对局。']
    report='\n\n'.join(out)+'\n'
    if accepted:report=report.replace('Prism Rush v0.1.0 候选','Prism Rush v0.1.0')
    readable=ROOT/'docs/prism/prism-rush-v0.1.0-evaluation-summary.md';readable.write_text(report,encoding='utf-8')
    replace_block(ROOT/'docs/m55-prism-rush-style-model.md',report.replace('# Prism Rush','## 最终记录：Prism Rush',1))
    p=ROOT/'docs/m55-prism-rush-style-model.md';s=p.read_text().replace('Status: **AUTHORIZED / IN PROGRESS**。','Status: **'+result['status']+'**。',1)
    s=s.replace('训练/开发/独立验收：**NOT_RUN**。当前尚无模型对战结果；完成后本文件必须直接包含逐对手/双座、经济/贵族/预留/动作/计时详细表，不能仅链接 JSON。','训练/开发/独立验收已完成；完整数据与六门结论见下方最终记录。原始设计、工程状态与迭代记录保留历史。',1)
    p.write_text(s,encoding='utf-8')
    for path in ('docs/m51-prism-model-line.md','docs/aran-model-evolution-matrix.md'):
        replace_block(ROOT/path,report.replace('# Prism Rush','## M55 Prism Rush',1))
    replace_block(ROOT/'handoff.md',f"## M55 当前终局：{result['status']}\n\n{verdict}\n\n4,096局全部完成，0 retry；[详细报告](docs/prism/prism-rush-v0.1.0-evaluation-summary.md) / [结果](benchmarks/m55-prism-rush-v0.1.0.result.json) / [M55](docs/m55-prism-rush-style-model.md)。基座 Prism v0.1.1 冻结不改；本轮停止，未部署或Git发布。")
    handoff=ROOT/'handoff.md';h=handoff.read_text(encoding='utf-8')
    snapshot=f"### {result['completed_at']} M55 终局 — {result['status']}\n\n{verdict}\n\n训练1,024、开发512、独立验收2,560，总4,096局、0 retry。完整双座/经济/动作/计时表：[阅读报告](docs/prism/prism-rush-v0.1.0-evaluation-summary.md)。六门结果：[结果](benchmarks/m55-prism-rush-v0.1.0.result.json)。本轮已停止，未部署/Git发布。下方M55启动快照为历史。\n\n"
    h=h.replace('## Current Snapshot\n','## Current Snapshot\n\n'+snapshot,1)
    handoff.write_text(h,encoding='utf-8')
    if accepted:
        write(ROOT/'benchmarks/m55-prism-rush-v0.1.0.release.json',{'format':'prism-model-release-v1','status':result['status'],'model_version':'prism-rush-v0.1.0','display_name':'Prism Rush v0.1.0','weights':{'path':'local-artifacts/prism/rush-v0.1.0/campaign/cycle-4-export/weights.json','sha256':result['training']['final_weights_sha256']},'base_model':result['base_model'],'acceptance':{'path':str(RESULT.relative_to(ROOT)),'sha256':sha(RESULT),'all_six_gates_passed':True},'readable_report':str(readable.relative_to(ROOT)),'default_replaced':False,'shared_pool_deployed':False})
