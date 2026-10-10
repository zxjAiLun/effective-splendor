"""Readable M62 saved-data research report, retaining original match tables."""
import gzip
import hashlib
import html
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'local-artifacts/prism/m62-building-research-2026-10-04'
NAMES = {'base': 'Prism Balance v0.1.0', 'control': 'Prism Balance v0.1.1 candidate（未发布）',
         'beta': 'Prism Beta v0.1.0 candidate（未发布）',
         'heuristic-v031': 'Heuristic v0.3.1 (greedy)', 'prism-v01': 'Prism v0.1.0 (greedy)',
         'prism-general-v011': 'Prism v0.1.1 (T=1)', 'alpha-t1': 'Prism Alpha v0.1.4 (T=1)',
         'base-t1': 'Prism Balance v0.1.0 (T=1)', 'control-t1': 'Prism Balance v0.1.1 candidate（未发布；T=1）',
         'COMMON_ANCHORS': '三共同锚点（分别同权）'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def table(headers, rows):
    return '\n\n| ' + ' | '.join(headers) + ' |\n| ' + ' | '.join(['---'] * len(headers)) + ' |\n' + '\n'.join('| ' + ' | '.join(map(str, row)) + ' |' for row in rows) + '\n\n'


def f(value, digits=4):
    return 'NOT_APPLICABLE' if value is None else f'{value:.{digits}f}'


def p(value):
    return 'NOT_APPLICABLE' if value is None else f'{100*value:.3f}%'


def signed(value, digits=4):
    return f'**{"↑" if value>0 else "↓" if value<0 else "→"} {value:+.{digits}f}**'


def main():
    import markdown
    profile_path = DATA / 'profile-diagnostic-final.json'
    profile = json.loads(profile_path.read_text('utf-8'))
    with gzip.open(DATA / 'training-diagnostic-attempt1.json.gz', 'rt', encoding='utf-8') as stream:
        training = json.load(stream)
    panel = json.loads((DATA / 'policy-panel.json').read_text('utf-8'))
    original_path = ROOT / 'docs/prism/m62-prism-beta-building-evaluation.md'
    original = original_path.read_text('utf-8')
    assert sha(original_path) == '80fc912e820a0f008aeeba6f2b244d0ed6640724dfc01c78422a7793087cb6c0'
    sections = []
    sections.append('''# M62 基建奖励与学习信号诊断

Status: VERIFIED / REVIEWED；2026-10-04；baseline `9899749188f35c838c85c5b3530049bd5dcbd105`。

**产物结论：**两份最终 c4 权重和保存数据有效；Prism Balance v0.1.1 candidate、Prism Beta v0.1.0 candidate 均未发布。本次新增诊断代码和报告，0 新对局、0 新优化器更新。

**竞技结论：**原 Control 两项保留门 PASS；Prism Beta v0.1.0 candidate 七门 3 PASS / 4 FAIL，仍为 `NOT_ACCEPTED_BUILDING_CANDIDATE`。固定对 Prism Alpha v0.1.4 半平得分率 54.9805%、校正下界 50.9766%，直接优势成立；通用锚点/对 Control 容忍底线未获确认，不是证明真实棋力退化。

**风格结论：**风格项确实改变了训练 advantage，但最终策略未形成预定的实质分化。逐笔封顶常见、utility 与投资张数高度相关，是改进奖励辨识度的依据；没有证明它们造成失败。不能再将本轮简单归因于“风格奖励没有进入训练”或“胜负完全压倒风格”。

[原交互对战页](prism-beta-v0.1.0-comparison.html) · [本报告 HTML](m62-building-reward-diagnostic.html) · [冻结完整原报告](m62-prism-beta-building-evaluation.md)。下方包含原完整双方对战表，JSON 仅作机器证据。

## 匹配的父版与候选变化

独立验收三共同锚点：Heuristic v0.3.1（greedy）、Prism v0.1.0（greedy）、Prism v0.1.1（T=1）；每模型 1,536 局 / 256 seed 块 × 双座 × 三对手。个人指标按模型身份合并座位。箭头只表示方向，不能单独表示更好或显著。''')
    sections.append(original.split('## 匹配共同锚点：父 → control → Beta\n',1)[1].split('## 九项采样前冻结门',1)[0])
    sections.append('''上表为原报告冻结描述：VP/Main 行是三个锚点各自速度的等权平均，不能当成合并总 VP/总 Main；总分母口径见已纠正的原交互页。本诊断的兑现比例一律使用总投资分母。

## 诊断范围与可验证边界

保存开发 576 局与独立验收 8,704 局的双方 18,560 个 profile 全量读入；两臂各 1,024 个完整 actor 轨迹、合计 55,149 个决策重算。12,288 个原来源文件按逐局 ledger 核对哈希，Beta 的 1,024 个重算 profile 与原训练 style targets 全字段一致。八个 cycle 的重算合成 advantage 均值/标准差与原封存指标差不超过 1e-12。

cloud1 仅读取原文件：不调用 `Run.open()`，不拿 writer lock，不写 campaign/store，不启动引擎。训练提取约 209.36 秒、峰值 RSS 389.8 MiB，4 GiB 地址空间/600 秒/最多两个 CPU 的上限内；HEAD、lock、ledger 前后哈希均无漂移。评测 profile 压缩抓取的解压 SHA 与冻结 result 完全一致。本次是公式/统计诊断，没有重跑规则审计、Bootstrap、正式门或参数梯度实验。

GPT-6 Luna 审阅奖励语义并实现 profile 统计，主代理审查、修订要求、独立重跑与训练/策略面板验证。两次 Gemini 3.8 Flash High 路由均在执行前因账户兼容限制失败；未产出代码或数据。''')
    pooled = [g for g in profile['groups'] if g['opponent_group']=='COMMON_ANCHORS' and g['role']=='candidate']
    sections.append('## 投资奖励的辨识度\n\n`use` 是后续实际购卡的原价在该颜色上达到这笔 bonus ordinal 的结构性适用次数，不是反事实节省 token，也不要求目标卡有 VP。原合同：前 12 个本人 Main 获得的 ≤1 VP 卡，统计至 Main24，每笔最多 3 use，全局最多 24，utility = credited units / 24。')
    rows = []
    for g in pooled:
        s = g['summary']
        rows.append([g['stage'],NAMES[g['model']],s['games'],f(s['mean_investments_per_game']),s['investment_count'],p(s['redemption_rate_by_total_investments']),p(s['investment_3plus_use_rate']),s['raw_use_units'],s['per_investment_cap_loss_units'],p(s['per_investment_cap_loss_units']/s['raw_use_units']),s['global_cap_loss_units'],p(s['censored_rate_by_total_investments'])])
    sections.append(table(['阶段','本人模型（T=1）','局','投资/局（张）','总投资','≥1 use/投资','≥3 use/投资','原始 use units','单笔截掉 units','截掉/原始','全局截掉 units','删失/投资'],rows))
    sections.append('独立验收中 Control/Beta 约 84% 投资达到单笔封顶，约三分之一结构性 use 被截掉，全局 cap24 没有截掉任何单位。约 99% 投资至少使用一次；因此“是否兑现”在现有策略分布中已很少区分好坏。逐笔封顶确实压缩了差异，但相关性与饱和度不能证明训练失败的原因。没有全局饱和，不能将 cap24 视为本轮瓶颈。')
    rows = []
    for g in pooled:
        s=g['summary'];u=s['utility'];c=s['correlations']
        rows.append([g['stage'],NAMES[g['model']],f(u['mean'],6),f(u['std'],6),f(u['min']),f(u['p10']),f(u['median']),f(u['p90']),f(u['max']),s['utility_zero_games'],s['utility_globalcap24_games'],f(c['utility_vs_investment_count']),f(c['utility_vs_auc12']),f(c['utility_vs_late_vp_main13to24']),f(c['utility_vs_main_actions'])])
    sections.append(table(['阶段','本人模型','utility均值','总体SD','min','p10','中位','p90','max','utility=0局','达到全局cap局','r:投资张数','r:AUC12','r:Main13..24 VP','r:本人Main局长'],rows))
    sections.append('profile 分位数采用 nearest-rank；训练与面板连续量使用线性插值分位数。SD 为总体标准差；r 为逐局 Pearson 描述相关，零方差返回 `NOT_APPLICABLE`。utility 与投资张数 r≈0.95，与 Main13..24 印刷 VP 仅约 0.17–0.20；后者不能作为“基建没有转换成胜利”的因果证明，也没有控制状态/市场/对手。')
    rows = []
    for g in pooled:
        s=g['summary']; n=s['investment_count']
        rows.append([g['stage'],NAMES[g['model']],s['redeemed_investments'],n,s['investments_with_3plus_uses'],n,f(s['first_use_main']['mean']),f(s['third_use_main']['mean']),f(s['first_use_delay_main']['mean']),f(s['third_use_delay_main']['mean'])])
    sections.append(table(['阶段','本人模型','首 use 覆盖投资','总投资','第三 use 覆盖投资','总投资','首 use 本人Main均值','第三 use 本人Main均值','首 use−购入Main','第三 use−购入Main'],rows))
    sections.append('时点只对实际发生相应 use 的投资计算，未发生的投资仍保留在完整总体/删失表中。独立验收中 Beta 的第三 use 比 Control 略早，首次 use 时点几乎相同；变化很小且未经独立时点验收，不能解释为稳定节奏优势。AUC12 的短局终局保持只用于描述，utility 没有补齐奖励。')
    rows=[]
    for m in profile['matched_control_beta_differences']:
        if m['role']=='candidate_profile' and m['opponent_group']=='COMMON_ANCHORS':
            d=m['mean_beta_minus_control']; rows.append([m['stage'],m['matched_seed_seat_rows'],signed(d['utility'],6),signed(d['investment_count']),signed(d['auc'],6),signed(d['late_vp']),signed(d['main_actions'])])
    sections.append(table(['匹配阶段','共同对手×seed×座位行','Beta−Control utility','投资/局 张','AUC12 折扣个','Main13..24 印刷VP','本人Main/局'],rows))
    sections.append('## 实际训练 advantage：风格信号存在，但不能与参数梯度混称\n\n按每个 cycle 的完整 actor 决策重算 `A = outcome_GAE + β × (utility − old_style_value)`，再用整个 batch 的均值/标准差归一化。终局 outcome 是 0/0.5/1，γ=1、λ=0.95、本人的决策时间轴。Control β=0；Beta β=0.3。由于归一化会减去整体均值，风格项的正均值不是额外全局推动力；需看中心化后的变异和变化。')
    rows=[]
    for arm,a in training['arms'].items():
        for c in a['cycles']:
            rows.append([NAMES[arm],c['cycle'],c['combined']['n'],f(c['outcome_gae']['std'],6),f(c['weighted_style']['mean'],6),f(c['weighted_style']['std'],6),f(c['combined']['mean'],6),f(c['combined']['std'],6),p(c['centered_style_std_over_combined_std']),f(c['normalized_mean_absolute_change'],6),p(c['centered_sign_flip_count']/c['combined']['n'])])
    sections.append(table(['训练模型','cycle','决策','outcome GAE SD','β×residual 均值','β×residual SD','合成 raw 均值','合成 raw SD','style SD/合成SD','相对仅outcome归一化平均绝对变化','中心化符号改变/决策'],rows))
    sections.append('Beta 的中心化风格项约占合成 SD 的 14.8%–15.6%，归一化后平均绝对变化约 0.12，并改变 2.1%–4.8% 的决策符号。它比 outcome GAE 的变异小，但有真实非零影响；这不足以判断应把 β 提高多少，更不等于测到了梯度占比。style value MSE 还以 0.5 权重作用于共享表示，因此原 M62 的 outcome-only/Beta 对照无法将 actor reward 与辅助 critic 作用各自归因。')
    rows=[]
    for arm,a in training['arms'].items():
        for c in a['cycles']:
            loss=c['historical_sample_weighted_losses']
            rows.append([NAMES[arm],c['cycle'],c['optimizer_steps'],f(c['profile_utility']['mean'],6),f(c['profile_auc12']['mean'],6),f(c['old_style_value']['mean'],6),f(loss['outcome_bce'],6),f(loss['style_mse'],6),f(loss['kl'],6),f(loss['clip_fraction'],6),f(loss['normalized_entropy'],6)])
    sections.append(table(['训练模型','cycle','optimizer step','局均utility（Control仅重算）','局均AUC12','决策加权old style value','BCE未乘0.5','style MSE未乘0.5','sample加权KL','sample加权clip fraction','sample加权normalized entropy'],rows))
    sections.append('style value 从 0 增至约 0.121，MSE 从约 0.222 降至 0.097；style critic 在学习，尚不能据此宣称校准完善。Beta 的 cycle utility/AUC 没有单调提升，这些是在不同训练局上得到的描述值。loss/KL 取历史每个 optimizer_step 按 samples 加权，未重新执行 optimizer，不据该表重挑 c4 或扩训。')
    sections.append('## 同状态冻结策略面板\n\n512 个已保存本人可见状态，按两臂×四 cycle×双座各 32 局；每个分组按 seed/job 排序，取首个 Main≤12 有 ≤1VP 合法购卡且有另一动作类别的机会。所有 2,048 训练局均有合格机会；面板只取前述固定子集。三个冻结导出模型在完全相同 input 上本机 CPU 单线程前向；float32 网络、float64 softmax、T=1、无动作偏置，同时记录 argmax 动作类别。')
    rows=[]
    for s in panel['summaries'][:2]:
        for model, stats in s['models'].items():
            rows.append([s['group'],s['states'],NAMES[model],p(stats['lowvp_mass']['mean']),p(stats['scoring_mass']['mean']),p(stats['buy_conditional_lowvp']['mean']),f(stats['entropy_nats']['mean']),stats['greedy_lowvp_count'],p(stats['greedy_lowvp_count']/s['states'])])
    sections.append(table(['机会子集','状态','冻结模型','≤1VP buy概率质量均值','≥2VP buy概率质量均值','逐状态条件P(低VP\u2223buy)均值','entropy nats','argmax低VP数','argmax低VP/状态'],rows))
    sections.append('整组 Beta−Control 的低 VP 购卡概率质量差为 **↑ +0.4045 个百分点**，argmax 低 VP 数为 415/414，父模型是 424。面板中只有 **8/512** 状态同时允许 ≥2VP 购卡；其余主要是在低 VP 买卡与拿 token/预留之间选择。约 99% 的条件 lowVP|buy 是机会集合造成的天花板，不能据此说三模型不区分牌质量。这份面板支持“早期首次购卡偏好相近”的有限结论，不能代表全部局面、未来收益、反事实 token 节省或夺走 Alpha 市场资源。')
    clock=panel['clock']
    rows=[[NAMES[key],f(value,4),512] for key,value in clock['model_predict_wall_seconds'].items()]
    sections.append(table(['模型','本机CPU model.predict 总wall秒','状态'],rows))
    sections.append(f'三模型面板总 wall {clock["panel_wall_seconds"]:.4f} 秒。计时包含单状态 collation/Python前向；运行PyTorch {clock["torch"]}、CPU单线程，远端训练记录运行PyTorch 2.6.0+cpu。该新离线计时不代替比赛的 decision/inference timing，后者原本未测的字段仍为 `NOT_MEASURED`；不能用它判定不同主机比赛速度。')
    sections.append('''## 下一轮单变量提议（PROPOSED / NOT_RUN）

优先继续基建 Beta 的有限研究，先修改奖励辨识度，再考虑增加轮数。保留真实后续购卡 use 条件，不直接把 AUC12 或 0VP 张数变成奖励。

建议下一次旧目标与时点目标做成两臂，**两臂都启用相同 style head/MSE、β=0.3、style_value_weight=0.5**，从同一冻结 Prism Balance v0.1.0、相同新初始化/RNG 开始；旧目标臂使用 M62 原 utility，新目标臂只改变 use 的时点权重。这比把当前 Beta 接着训练后与历史 Control 比较更能隔离此次修改。M62 c4 继续冻结作历史参照，不追加任何历史 seed。

可供下一合同审查的唯一新映射：对每笔符合原 early≤12、VP≤1 的投资，取原结构性规则下前 3 次真实 use，其本人 Main 时点 t≤24，每次记 `w(t)=(25−t)/24`；按原全局上限 24 截断总和，再除以 24。Main8/16/24 的相同 use 分别记 17/24、9/24、1/24；相同三次兑现会因更早发生而得到更高目标。未实际发生 use 仍为 0，noble 不加 Main，终局不补奖励，不读取隐藏信息。此映射未经实现/采样验证，数值尺度会随时点改变，不能声称等强或一定有效。

保留原 utility 与 AUC12 的独立描述；未来风格接受仍需预先声明实质变化和可接受代价，不能要求所有经济指标一齐提高。建议保留总体/通用锚点/直接竞争力保护，AUC12 实质目标仍以 +0.25 个折扣作为设计参照；旧 utility 的允许代价、全 family 校正、预算/种子/止损条件须在新对局之前另行冻结。原 M62 的九门完全保留，不把新 tolerance 套回原结果。

次序：先新映射合同与边界测试 → 保存轨迹上的数值范围及归一化核验（不用于证明更强）→ 固定有限 A/B 训练/独立验收合同 → 获得新采样授权后再运行。同步续训 Alpha、开 Denial 或单纯加 β 均不作为当前默认下一步。新的模型版本、训练及正式对战均 `NOT_RUN`。

## 证据与复现
''')
    paths=['scope.json','profile-fetch-receipt.json','profile-diagnostic-final.json','training-extraction-attempt1-receipt.json',
           'training-diagnostic-attempt1.json.gz','policy-panel.json']
    rows=[[f'`local-artifacts/prism/m62-building-research-2026-10-04/{name}`',sha(DATA/name)] for name in paths]
    rows += [[f'`{name}`',sha(ROOT/name)] for name in ('scripts/prism_building_profile_diagnostic_m62.py','scripts/prism_building_training_diagnostic_m62.py','scripts/prism_building_policy_panel_m62.py','scripts/generate_m62_reward_diagnostic_report.py')]
    sections.append(table(['本地材料（generated工件不发布）','SHA256'],rows))
    sections.append('''实际提取命令及 exit0/时钟见 training-extraction-attempt1-receipt.json；它通过SSH向cloud1执行 hash 固定的脚本 stdin，只输出gzip到本机新文件。profile与panel CLI、测试命令/exit另见 closeout-validation.json；报告的量化数据来自所列机器工件，人工解释不代替冻结验收。

## 全部逐对手 profile 诊断（双方个人指标）

此表每行是该 candidate 对 opponent group 的一个本人模型画像，role=candidate/opponent明确归属。pooled共同锚点的候选包含三个对手；对手按各自身份分开，不混成一个虚拟模型。''')
    rows=[]
    for g in profile['groups']:
        s=g['summary']; rows.append([g['stage'],NAMES[g['candidate']],NAMES.get(g['opponent_group'],g['opponent_group']),g['role'],NAMES.get(g['model'],g['model']),s['games'],f(s['utility']['mean'],6),s['investment_count'],p(s['redemption_rate_by_total_investments']),p(s['investment_3plus_use_rate']),s['per_investment_cap_loss_units'],s['global_cap_loss_units'],f(s['correlations']['utility_vs_investment_count'])])
    sections.append(table(['阶段','候选身份','对手组','本人role','本人模型','局','utility','投资张数','兑现率','单笔封顶率','单笔截掉use','全局截掉use','r utility/投资'],rows))
    research='\n\n'.join(sections)
    # Retain every original match table/clock/source row. The giant raw audit
    # JSON and per-game literal seeds remain in the hash-pinned original report.
    old_tables=original.split('## 原训练合同与raw审计回执',1)[0]
    old_tables=re.sub(r'^(#{1,5}) ',r'\1# ',old_tables,flags=re.M)
    appendix='## 原 M62 完整对战表与原门（原文保留）\n\n以下保存原判定及全部双方、双座、购卡、动作、节奏、时钟、身份/seed范围与来源表；上方解释边界和VP/Main口径更正优先。原报告 raw 审计与每局命令/字面seed仍保留在原SHA工件中。\n\n'+old_tables
    text=research+'\n\n'+appendix
    md_path=ROOT/'docs/prism/m62-building-reward-diagnostic.md'
    md_path.write_text(text,encoding='utf-8')
    def render(value):
        rendered=markdown.markdown(value,extensions=['tables','fenced_code'])
        return re.sub(r'(<table>.*?</table>)',r'<div class="scroll-table">\1</div>',rendered,flags=re.S)
    css='''*{box-sizing:border-box}body{margin:0;background:#101619;color:#e4eded;font:16px/1.7 "Segoe UI","Microsoft YaHei",sans-serif}main{max-width:1400px;margin:auto;padding:36px 28px}h1{font-size:32px;line-height:1.3}h2{margin-top:44px;color:#a6d9de;font-size:23px}h3{color:#bcced1}p,li{max-width:1100px}a{color:#88c9ff}strong{color:#f6d889}code{font-size:.85em;overflow-wrap:anywhere;background:#1e292f;padding:2px 5px;border-radius:4px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#1e292f;padding:20px}.scroll-table{max-width:100%;overflow:auto;margin:20px 0;border:1px solid #34454d;border-radius:8px}table{border-collapse:collapse;font-size:14px;width:100%}td,th{border-bottom:1px solid #34454d;padding:10px 13px;min-width:100px;text-align:left;vertical-align:top}th{background:#233740;color:#d2edf0;position:sticky;top:0}tr:nth-child(even){background:#172228}td strong{color:#f6d889}details{border:1px solid #3a545e;border-radius:10px;padding:18px;margin:30px 0}summary{cursor:pointer;font-size:22px;color:#a6d9de}.banner{border-left:5px solid #e2bb63;background:#213239;padding:16px 22px;margin:20px 0}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.card{padding:20px;background:#1c2a31;border:1px solid #3c565f;border-radius:10px}.metric{font-size:30px;color:#f6d889;display:block}.note{color:#afc2c8;font-size:14px}@media(max-width:650px){main{padding:20px 14px}h1{font-size:26px}.cards{grid-template-columns:1fr}.metric{font-size:26px}td,th{padding:8px;min-width:105px}}'''
    cards='<div class="cards"><div class="card"><span class="metric">≈15%</span>中心化 style SD / 合成 advantage SD<br><span class="note">训练信号确实存在；不是梯度占比</span></div><div class="card"><span class="metric">≈84%</span>投资达到单笔 3-use 封顶<br><span class="note">奖励区分度线索；未证明失败原因</span></div><div class="card"><span class="metric">↑ +0.40 pp</span>同状态 Beta−Control 低VP买卡概率<br><span class="note">512保存机会；仅8状态有≥2VP选择</span></div></div>'
    page='<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>M62 基建奖励诊断</title><style>'+css+'</style></head><body><main><div class="banner">保存数据研究完成 · 0新对局 / 0新训练 · 原Beta七门3 PASS / 4 FAIL保持</div>'+cards+'<article id="research">'+render(research)+'</article><details id="matches"><summary>展开：原 M62 完整对战表、双方指标、双座和九门</summary>'+render(appendix)+'</details></main></body></html>'
    html_path=md_path.with_suffix('.html')
    html_path.write_text(page,encoding='utf-8')
    receipt={'format':'m62-reward-report-generation-v1','markdown':str(md_path),'markdown_sha256':sha(md_path),
             'html':str(html_path),'html_sha256':sha(html_path),'generator_sha256':sha(Path(__file__)),
             'original_sha256':sha(original_path),'retained_original_tables':len(re.findall(r'^\|(?: --- \|)+$',old_tables,re.M)),
             'new_games':0,'optimizer_updates':0}
    with (DATA/'report-generation.json').open('w',encoding='utf-8') as stream:
        json.dump(receipt,stream,ensure_ascii=False,indent=2)
    print(json.dumps(receipt,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
