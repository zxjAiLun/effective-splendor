"""Read-only M55 gate interpretation and readable comparisons; launches no games.

Keeps the frozen controller, criteria, measurements and formal verdict intact.
"""
from collections import Counter
from datetime import datetime, timezone, timedelta
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.prism_rush_round import read, write, sha, require
from scripts.prism_rush_report import detailed_tables, table, replace_block

RESULT=ROOT/'benchmarks/m55-prism-rush-v0.1.0.result.json'
CONFIG=ROOT/'benchmarks/m55-prism-rush-v0.1.0.config.json'
INTERPRETATION=ROOT/'benchmarks/m55-prism-rush-v0.1.0.interpretation.json'
REPORT=ROOT/'docs/prism/prism-rush-v0.1.0-evaluation-summary.md'
HTML=ROOT/'docs/prism/prism-rush-v0.1.0-comparison.html'
IMAGE=ROOT/'docs/prism/prism-rush-v0.1.0-comparison.png'
ART=ROOT/'local-artifacts/prism/rush-v0.1.0/readability-2026-10-02'
ANCHORS=('heuristic-v031','prism-v01')
NAMES={'heuristic-v031':'Heuristic v0.3.1','prism-v01':'初代 Prism v0.1.0','base-t1':'Prism v0.1.1'}
BASELINE_SHA='9093d26aa1b8a31fd3874b4b79f046bf098755587a49f0eea345e03649bcac57'


def pct(value):return f'{value*100:.2f}%'

def delta(value,unit=''):
    return ('↑' if value>0 else '↓' if value<0 else '＝')+f' {value:+.4f}{unit}'


def pair_map(result,stage):return {(p['candidate'],p['opponent']):p for p in result[stage]['pairs']}


def metric_value(pair,key):
    return pair[key] if key in ('mean_rush_auc','vp8_by_main20_rate') else pair['candidate_metrics'][key]


def gate_rows(result,config):
    definitions=[
      ('strength_pool','共同锚点合计','棋力容差','strength_pool_delta_lower_gte','pp',False,'相对基座允许下降5个百分点'),
      ('strength/heuristic-v031','对 Heuristic v0.3.1','棋力容差','strength_each_anchor_delta_lower_gte','pp',False,'相对基座允许下降5个百分点'),
      ('strength/prism-v01','对初代 Prism v0.1.0','棋力容差','strength_each_anchor_delta_lower_gte','pp',False,'相对基座允许下降5个百分点'),
      ('direct_base','直接对 Prism v0.1.1','棋力底线','direct_base_score_lower_gte','rate',False,'得分率允许低到45%，不要求战胜基座'),
      ('rush_auc','前16自身Main得分曲线','冲分幅度','rush_auc_delta_lower_gt','auc',True,'归一化AUC至少提升0.015（严格大于）'),
      ('vp8_by_main20','20自身Main内达到8VP','第二风格目标','vp8_by_main20_rate_delta_lower_gt','pp',True,'达到8VP的对局比例至少提高2个百分点（严格大于）')]
    rows=[]
    for key,label,role,field,unit,strict,note in definitions:
        m=result['measurements'][key];threshold=config['acceptance'][field];lower=m['simultaneous_one_sided_lower']
        passed=lower>threshold if strict else lower>=threshold
        require(passed is result['gates'][key], 'original exact gate comparison disagrees')
        classification='CONFIRMED' if passed else ('EFFECT_BELOW_TARGET' if key=='rush_auc' else 'NOT_CONFIRMED')
        reading='🟢 原门通过' if passed else ('🟡 风格幅度未达' if key=='rush_auc' else '🟡 增益未确认' if key=='vp8_by_main20' else '🟡 容差未确认')
        rows.append({'key':key,'label':label,'role':role,'unit':unit,'threshold':threshold,'strict':strict,
                     'mean':m['mean'],'ci95':m['ci95'],'lower':lower,'original_pass':passed,
                     'classification':classification,'reading':reading,'note':note})
    return rows


def metric_format(value,unit):
    if unit=='auc':return f'{value:+.5f}'
    if unit=='rate':return pct(value)
    return f'{value*100:+.2f}个百分点'


def compare_table(result,stage):
    pairs=pair_map(result,stage)
    specs=[('得分率（计半平）','score_rate','rate'),('局均最终VP','mean_prestige','number'),
           ('VP / 自身Main','vp_per_main_action','number'),('前16自身Main AUC','mean_rush_auc','number'),
           ('20自身Main内8VP比例','vp8_by_main20_rate','rate'),('局均贵族','mean_nobles','number'),
           ('获得贵族的对局比例','games_with_nobles_percent','percent'),('预留买回 / 获取','reserve_redemption_rate_percent','percent'),
           ('终局未买回预留','mean_reserves_stranded','number')]
    rows=[]
    for label,key,unit in specs:
        cells=[]
        for op in ANCHORS:
            base,rush=pairs[('base',op)],pairs[('rush',op)]
            a,b=metric_value(base,key),metric_value(rush,key)
            if unit=='rate':cell=f'{pct(a)} → {pct(b)}；**{delta((b-a)*100,"pp")}**'
            elif unit=='percent':cell=f'{a:.2f}% → {b:.2f}%；**{delta(b-a,"pp")}**'
            else:cell=f'{a:.4f} → {b:.4f}；**{delta(b-a)}**'
            cells.append(cell)
        rows.append([label,*cells])
    return table(['被测玩家指标：基座 → 候选；变化','对 Heuristic v0.3.1','对初代 Prism v0.1.0'],rows)


def write_report(result,config,gates):
    stage=pair_map(result,'acceptance');bpool=sum(stage[('base',op)]['candidate_metrics']['score_rate'] for op in ANCHORS)/2
    rpool=sum(stage[('rush',op)]['candidate_metrics']['score_rate'] for op in ANCHORS)/2
    local_time=datetime.fromisoformat(result['completed_at']).astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
    front=[
      '# Prism Rush v0.1.0 样机：对战结论与清晰对照',
      '**本轮产物已完成；竞技表现可用；预设冲分目标尚未充分建立。** 完成时间：'+local_time+'（北京时间）。',
      table(['先看什么','结论'],[
       ['✅ 训练与数据有效','1,024训练局、216新更新；512开发局与2,560独立验收局完成，总4,096局，0 retry'],
       ['✅ 实战有竞争力','独立验收纯胜率：对 Heuristic v0.3.1 **65.82%**、对初代 Prism v0.1.0 **62.11%**、直接对 Prism v0.1.1 **52.73%**'],
       ['🟡 冲分幅度尚未建立','前16自身Main AUC只提高 **0.00164**，原定最小幅度是 **0.015**；20Main内8VP比例有向上信号，增益未被置信下界确认'],
       ['🟡 一个棋力容差未确认','对初代的得分率实际只比基座低 **0.88pp**；不代表已实测下降7.13pp']]),
      '冻结原判仍为 `NOT_ACCEPTED_RUSH_STYLE`：它回答“是否通过预先写定的全部冲分晋级门”，不代表训练失败或模型没有可用价值。权重和完整对战证据保留，未替换默认模型、未向共享池部署；本次只改解读与展示，不改原阈值、结果或标签。',
      '## 先看同条件的变化',
      '**以下是独立验收，每一模型/对手512局、256双座种子块。** 基座与候选对同一对手使用同一组种子/换座条件。每格只比较被测玩家“Prism v0.1.1 → Prism Rush v0.1.0 候选”；对手数据在后方完整表中。',
      compare_table(result,'acceptance'),
      f'两个共同锚点的合计得分率：**{pct(bpool)} → {pct(rpool)}，↑{(rpool-bpool)*100:.2f}pp**。直接对基座512局：270胜 / 4平 / 238负，纯胜率52.73%，计半平得分率53.13%。普通95%得分率区间48.83%..57.32%，因此当前不能确认已强于基座。',
      '**读表图例：↑/↓只是数值增减，不自动等于更好或统计显著。** `pp`=百分点。更多折扣、贵族或更少预留不天然更好；风格可以交换棋力、经济与节奏。🟢只用于原门确认通过，🟡区分幅度未达与证据不足。',
      '彩色对照页：[可切换独立/开发与指标组的对照](prism-rush-v0.1.0-comparison.html)。下方图为独立数据首屏快照；完整Markdown数表保留在本文件后面。',
      '![独立验收的基座与候选变化](prism-rush-v0.1.0-comparison.png)',
      '## 六个门怎么设计，为什么有 FAIL',
      '原设计是**4项棋力保护 + 2项风格目标**。棋力保护允许代价：三项相对基座的得分率差，下界允许到−5pp；直接对基座的得分率下界允许到45%。需要正向增益的是两项冲分目标。**从来不是六个数都必须为正。** 数值阈值是执行agent为这个样机选定的工程要求，不是用户亲自指定的偏好或棋力定律。',
      table(['原门 / 作用','实测均值','要求：校正下界','实际校正下界','原结果的正确读法'],
        [[g['label']+' / '+g['role'],metric_format(g['mean'],g['unit']),('> ' if g['strict'] else '≥ ')+metric_format(g['threshold'],g['unit']),metric_format(g['lower'],g['unit']),g['reading']+('（原 PASS）' if g['original_pass'] else '（原 FAIL）')] for g in gates]),
      '四项棋力门并不要求每个指标提高。对初代一项实测变化−0.88pp，但下界−7.13pp越过原设−5pp容差：含义是“这批样本没把下降风险压到预定容差以内”，**不是已证明模型明显退化**。直接对基座的53.13%及47.95%下界通过45%底线，也不要求它显著战胜基座。',
      'AUC门的另一层含义：实测+0.001636、普通95%区间[−0.000598,+0.003894]，连普通区间上端也低于原目标+0.015。按15VP归一化还原，窗口内平均截顶VP只提高约**0.0245VP**，原目标相当于**0.225VP**。该主指标上的幅度很小，不能只归因于多重校正。',
      '20Main内8VP比例：**29.69% → 32.42%，+2.73pp**；均值超过原+2pp目标，但普通95%增益区间[−0.59,+6.05]pp、校正下界−1.27pp，所以是“方向向上，增益未确认”。',
      '所有门以256个环境seed块进行配对bootstrap；双座是同一块，不能把每局当成独立种子。20,000次重采样、六项单侧判断，用0.05/6≈0.8333%分位作下界；原表只有0..1数值和PASS/FAIL，缺少阈值、单位和失败类型，容易误读。',
      '## 验收设计与产品意图的修正',
      '用户明确：锚定风格可以接受某些维度稍差。原方案虽允许5pp代价，却又把每个锚点、两项风格指标都设为独立硬门；配合有限样本与六门校正，对首轮风格样机偏保守。计算与原判可复核，产品层面的六门全过要求值得重新设计。',
      '后续方向 **PROPOSED**：把“训练/产物有效”“总体棋力底线”“风格目标”分别评估；用总体与直接基座对照保护实用强度，逐对手和经济细项作为画像/告警，除非产品目标确实要求每个对手都不退化。选择一个贴合所需风格的主指标，把其他行为指标作为诊断；提前定义可接受棋力损失与最低风格幅度，不要求全表变好。',
      '本轮候选是已完成、值得保留的实验产物；冲分标签的充分证据仍缺。此新意图不把旧FAIL事后改成PASS，不自动发布为已验证Rush版本，也不追加训练/比赛。下一次训练或正式验收需要新的固定范围与未使用种子。',
      '## 截图数据与训练对象说明',
      '**用户截图来自开发评测：每模型/对手128局；六个门来自独立验收：每组512局。** 开发组可用来描述，但不能混入独立验收。比如截图中贵族均值上升，独立组候选贵族均值对两个锚点约变化−0.002/−0.020，说明该行为尚不稳定；不要只凭某一屏把它定为贵族或冲分风格。',
      'Prism v0.1.1 来自trial-v2最终c8，其两批PPO并非只针对初代：trial-v1与trial-v2每批各2,048局，其中Heuristic v0.3.1与初代 Prism v0.1.0各1,024局。它们是训练锚点，所以这些胜率表明对该测试场的竞争力，不能扩写成全对手泛化结论。',
      '## 统计原值（保留原冻结判定）',
      table(['测量键','均值','普通95%区间','六门校正下界','冻结原门'],[[g['key'],f"{g['mean']:.6f}",'['+', '.join(f'{v:.6f}' for v in g['ci95'])+']',f"{g['lower']:.6f}",'PASS' if g['original_pass'] else 'FAIL'] for g in gates])]
    for stage_name,title in [('acceptance','独立验收：原始双方完整数据'),('development','开发评测：描述性完整数据')]:
        front.extend(['## '+title,f"每模型/锚点{512 if stage_name=='acceptance' else 128}局；整批墙钟 {result[stage_name]['run_receipt']['wall_seconds']:.3f}s；本机4个BelowNormal进程，0 retry。"])
        if stage_name=='development':front.extend(['开发组对照（不参与验收；↑/↓是描述性变化）：',compare_table(result,'development')])
        front.append(detailed_tables(result[stage_name]['pairs'],title))
    front.extend(['## 证据与边界',table(['证据','路径 / SHA256'],[
      ['冻结原结果',f'`benchmarks/m55-prism-rush-v0.1.0.result.json` / `{sha(RESULT)}`'],
      ['冻结原试验合同',f'`benchmarks/m55-prism-rush-v0.1.0.config.json` / `{sha(CONFIG)}`'],
      ['冻结c4',f'`local-artifacts/prism/rush-v0.1.0/campaign/cycle-4-export/weights.json` / `{result["training"]["final_weights_sha256"]}`'],
      ['冻结基座',f'`{config["base_model"]["weights_path"]}` / `{config["base_model"]["sha256"]}`'],
      ['解释与展示索引','`benchmarks/m55-prism-rush-v0.1.0.interpretation.json`'],
      ['可读生成器','`scripts/prism_rush_readability.py`（只读取既有数据，不启动比赛）']]),
      '开发9490000..9490063、独立9500000..9500255，动作seed55020001；规则重演/逐局hash/握手/完整双座grid验核来自原完成回执与source-ledger。全部3,072开发/验收回放已重验；训练1,024局由固定Arena完成。逐对手描述性95%bootstrap RNG54049999；正式六门RNG55029999，所有原值和原判不变。',
      '时钟包含进程启动/比赛/输出等，并行单局累计不等于整批墙钟。逐决策/推理延迟NOT_MEASURED。无独立reviewer结论、默认替换、共享池/Elo写入或Git发布。本次改读法0新局、0更新；原文与原收口回执作为历史保留。'])
    return '\n\n'.join(front)+'\n'


def main():
    result,config=read(RESULT),read(CONFIG)
    require(sha(RESULT)==BASELINE_SHA and result['status']=='NOT_ACCEPTED_RUSH_STYLE','frozen result drift')
    gates=gate_rows(result,config)
    require(not all(g['original_pass'] for g in gates),'retain original unaccepted verdict')
    coverage={}
    for stage in ('acceptance','development'):
        pairs=pair_map(result,stage)
        coverage[stage]=sum(p['candidate_metrics']['games'] for p in pairs.values())
        require(coverage[stage]==result[stage]['games'],'summary grid coverage')
        for op in ANCHORS:
            a,b=pairs['base',op],pairs['rush',op]
            require(a['candidate_metrics']['games']==b['candidate_metrics']['games'],'matched sample size')
    training_opponents={}
    for trial in ('v1','v2'):
        spec=read(ROOT/f'benchmarks/m54-prism-ppo-trial-{trial}.config.json')
        counts=Counter(j['opponent_id'] for cycle in spec['cycles'] for j in cycle)
        require(counts=={'heuristic-v031':1024,'prism-v01':1024},'training lineage fact')
        training_opponents[trial]=dict(counts)
    interpretation={'format':'m55-prism-rush-interpretation-v1','status':'VERIFIED_DESCRIPTIVE_INTERPRETATION',
      'original_result':{'path':str(RESULT.relative_to(ROOT)),'sha256':sha(RESULT)},'original_config':{'path':str(CONFIG.relative_to(ROOT)),'sha256':sha(CONFIG)},
      'formal_verdict':result['status'],'artifact_completion':'COMPLETE_VALID_EXPERIMENTAL_ARTIFACT',
      'competitive_reading':'COMPETENT_ON_TESTED_FIELD; no significant direct superiority claim',
      'style_reading':'PREREGISTERED_RUSH_EFFECT_NOT_ESTABLISHED','gate_rows':gates,
      'all_gates_require_positive_metrics':False,'owner_preference':'anchored style may trade some strength/economy; not all metrics must improve',
      'future_gate_policy':'PROPOSED: separate validity/strength floor/primary style effect; opponent-specific and secondary behavior checks diagnostic unless product requires them',
      'no_retroactive_pass_no_threshold_change':True,'new_games':0,'training_updates':0,'promotion_changed':False,
      'coverage':coverage,'historical_training_opponent_counts':training_opponents,
      'renderer':{'path':str(Path(__file__).relative_to(ROOT)),'sha256':sha(__file__)},'readable_report':str(REPORT.relative_to(ROOT)),'comparison_page':str(HTML.relative_to(ROOT))}
    write(INTERPRETATION,interpretation)
    data={'result':result,'config':config,'gates':gates,'sourceSHA':sha(RESULT),'sourcePath':str(RESULT.relative_to(ROOT)),
          'names':NAMES,'completedLocal':datetime.fromisoformat(result['completed_at']).astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')}
    template=(ROOT/'scripts/templates/prism-model-comparison.html').read_text(encoding='utf-8')
    require(template.count('__MODEL_DATA__')==1,'one bound data placeholder')
    HTML.write_text(template.replace('__MODEL_DATA__',json.dumps(data,ensure_ascii=False).replace('<','\\u003c')),encoding='utf-8')
    document=write_report(result,config,gates)
    REPORT.write_text(document,encoding='utf-8')
    for target,heading in [('docs/m55-prism-rush-style-model.md','## 最终记录：'),('docs/m51-prism-model-line.md','## M55：'),('docs/aran-model-evolution-matrix.md','## M55：')]:
        linked=document.replace('(prism-rush-v0.1.0-comparison.html)',
                                '(prism/prism-rush-v0.1.0-comparison.html)')
        linked=linked.replace('(prism-rush-v0.1.0-comparison.png)',
                              '(prism/prism-rush-v0.1.0-comparison.png)')
        replace_block(ROOT/target,linked.replace('# Prism Rush',heading+'Prism Rush',1))
    print('PASS: read-only gate explanation and full Markdown tables, frozen verdict preserved')


if __name__=='__main__':main()
