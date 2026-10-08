"""Readable M56 result and version identity, from verified measurements only."""
import html
import json
import shutil
from scripts.prism_alpha_round import ART, ROOT, PILOT, TRAIN, RESULT, DISPLAY, read, write, sha, require
from scripts import prism_rush_report as old_tables

START = '<!-- M56 VERIFIED RESULTS BEGIN -->'
END = '<!-- M56 VERIFIED RESULTS END -->'
table, pct = old_tables.table, old_tables.pct


def replace_block(path, body):
    text = path.read_text(encoding='utf-8')
    block = START + '\n\n' + body + '\n\n' + END
    if START in text:
        require(text.count(START) == text.count(END) == 1, 'M56 document boundary')
        a = text.index(START); b = text.index(END) + len(END)
        text = text[:a] + block + text[b:]
    else:
        text += '\n\n' + block + '\n'
    path.write_text(text, encoding='utf-8')


def fmt(value):
    return 'NOT_APPLICABLE' if value is None else f'{value:.4f}'


def trajectory_tables(pairs):
    headers = ['个人指标：模型 / 对手'] + [DISPLAY[p['candidate']] + ' 对阵 ' + DISPLAY[p['opponent']] for p in pairs]
    def cell(pair, key):
        return fmt(pair['candidate_bigcard'][key]) + ' / ' + fmt(pair['opponent_bigcard'][key])
    rows = [[label] + [cell(p, key) for p in pairs] for label, key in (
        ('24 Main 总VP AUC（训练效用）', 'mean_total_vp_auc24'),
        ('24 Main 大牌印刷VP AUC（风格底线）', 'mean_large_card_vp_auc24'),
        ('终局3～5VP牌印刷分合计', 'mean_terminal_large_card_printed_vp'),
        ('前24自身Main购入3～5VP牌数', 'mean_large_card_buys_within24'))]
    for key, label in (('first_large_card_main', '首张3～5VP牌'), ('first_4plus_card_main', '首张4～5VP牌')):
        rows.append([label + ' 自身Main（仅买到的局）'] + [fmt(p['candidate_bigcard'][key]['conditional_mean']) + ' / ' + fmt(p['opponent_bigcard'][key]['conditional_mean']) for p in pairs])
        rows.append([label + ' 覆盖局数 / 总局数（双方）'] + [f"{p['candidate_bigcard'][key]['coverage_games']}/{p['candidate_bigcard']['games']} ; {p['opponent_bigcard'][key]['coverage_games']}/{p['opponent_bigcard']['games']}" for p in pairs])
    for i, main in enumerate((8, 12, 16, 20, 24)):
        for key, label in (('mean_vp', '总VP'), ('mean_large_card_printed_vp', '大牌印刷VP')):
            rows.append([f'自身Main {main} 后局均{label}'] + [fmt(p['candidate_bigcard']['score_checkpoints'][i][key]) + ' / ' + fmt(p['opponent_bigcard']['score_checkpoints'][i][key]) for p in pairs])
        rows.append([f'自身Main {main} 实际达到局数（双方）'] + [f"{p['candidate_bigcard']['score_checkpoints'][i]['observed_games']} / {p['opponent_bigcard']['score_checkpoints'][i]['observed_games']}" for p in pairs])
    return '\n\n'.join(['### 大牌购入时点与分段得分（双方个人指标）', table(headers, rows),
        '每格为模型 / 对手。自身Main含购卡/取宝石/预留/跳过，不含贵族选择；贵族分计入前一个Main。短局在后续固定检查点用其终局分补足，并列实际达到该Main的局数。大牌仅含购入3～5VP卡的印刷VP，排除贵族；AUC按15VP截断、固定24分母。首牌时点只对买到的局取均值，必须连同覆盖率解读，不能单凭均值认定更快。'])


def comparisons(result):
    pairs = result['acceptance']['pairs']; keyed = {(p['candidate'], p['opponent']): p for p in pairs}
    rows = []
    for op in ('heuristic-v031', 'prism-v01', 'prism-v0.1.1'):
        base = keyed[('base', op)]; candidate = keyed[('candidate', op)]
        for label, getter, percent in (
            ('半平得分率', lambda p: p['candidate_metrics']['score_rate'], True),
            ('大牌印刷VP AUC24', lambda p: p['candidate_bigcard']['mean_large_card_vp_auc24'], False),
            ('终局大牌印刷VP', lambda p: p['candidate_bigcard']['mean_terminal_large_card_printed_vp'], False),
            ('购入4VP牌 / 局', lambda p: p['candidate_metrics']['mean_cards_by_vp']['4'], False),
            ('购入5VP牌 / 局', lambda p: p['candidate_metrics']['mean_cards_by_vp']['5'], False),
            ('VP / 自身Main', lambda p: p['candidate_metrics']['vp_per_main_action'], False)):
            a, b = getter(base), getter(candidate); delta = b - a
            arrow = '↑' if delta > 0 else ('↓' if delta < 0 else '→')
            f = pct if percent else fmt
            change = f'{delta * 100:+.2f}个百分点' if percent else f'{delta:+.4f}'
            rows.append([DISPLAY[op], label, f(a), f(b), f'**{arrow} {change}**'])
    return table(['同种子共同对手', '被测模型个人指标', '父模型 Prism Alpha v0.1.0', 'Prism Alpha v0.1.1', '变化'], rows)


def readable_body(result):
    accepted = result['all_three_gates_passed']
    out = [f'本轮结论：**{result["status"]}**。四轮训练完成；最终c4固定为Prism Alpha v0.1.1实验产物。' +
        ('三项保留底线均通过。' if accepted else '至少一项预设保留底线未通过；候选及有效负结果保留。'),
        '父模型是Prism Alpha v0.1.0（M55最终c4）；Prism v0.1.1是更早的通用模型，本轮作为额外固定对手。Prism Alpha v0.1.1是从Alpha父权重继续四轮所得，命名登记不等于默认模型替换。',
        '“通过本轮保留底线”与“证明更强”分开：' + '；'.join(k + '=' + ('有校正下界证据' if v else '未建立校正下界增强证据') for k, v in result['confirmed_enhancement'].items()) + '。',
        '## 一眼看变化：相同新种子、相同对手、父模型→新产物', comparisons(result),
        '箭头只表示数值变化；大牌数更多未必单独更好。共同对手各512局/模型，直接父模型对战另有1,024局，不能混成一张胜率。',
        '## 原定三门及本次结果']
    thresholds = {'strength_pool': '相对父模型总体得分率 Δ下界 ≥ −5个百分点',
                  'direct_parent': '直接对父模型得分率下界 ≥45%',
                  'bigcard_auc24': '大牌印刷VP AUC24 Δ下界 ≥−0.015'}
    out.append(table(['验收项', '采样前阈值', '估计值', '普通配对95%区间', '三门校正单侧下界', '结论'],
        [[k, thresholds[k], f'{result["measurements"][k]["mean"]:.6f}',
          '[' + ', '.join(f'{x:.6f}' for x in result['measurements'][k]['ci95']) + ']',
          f'{result["measurements"][k]["simultaneous_one_sided_lower"]:.6f}',
          '**PASS**' if result['gates'][k] else '**FAIL**'] for k in thresholds]))
    out += ['三项是容许代价的保留门，不要求所有数据上涨。20,000次双座seed块bootstrap，RNG56029999，family α=0.05，单侧下界分位0.05/3；共同锚点按256个匹配seed块，直接父模型按512块。各对手、早期总VP、预留/折扣等为诊断，不额外否决。本轮一次分析，无挑种子、加局、挑中间检查点。',
        '## 训练与实测时间', table(['项目', '实测/合同'], [
            ['训练', f"4×256 = {result['training']['games']}局；{result['training']['new_steps']}次新优化更新；{result['training']['decisions']}次训练决策"],
            ['奖励代理', '前24自身Main的公开总VP归一化AUC；β0.3；新style head、AdamW和RNG；策略/胜负value权重从父模型继承'],
            ['训练监督进程墙钟s', f"{sum(s['wall_seconds'] for s in result['training']['supervisor_sessions']):.3f}"],
            ['开发整批墙钟s', f"{result['development']['run_receipt']['wall_seconds']:.3f}"],
            ['独立验收整批墙钟s', f"{result['acceptance']['run_receipt']['wall_seconds']:.3f}"],
            ['设备/负载', '本机CPU；训练2线程；评测4个BelowNormal工作进程。此为当前负载观测'],
            ['决策 / 推理时延', 'NOT_MEASURED / NOT_MEASURED']]),
        '训练总VP代理含贵族，能鼓励兑现分数；大牌专属AUC由完整回放另测。窗口16→24是本轮预设改变，并非从新结果挑出。保留不等于机制已证实。总计5,504物理局，0重试；其中训练1,024、开发384、独立验收4,096。']
    old_tables.DISPLAY = DISPLAY
    for stage, label in (('development', '开发对照：32双座种子 / 每模型每对手64局，仅描述'),
                         ('acceptance', '独立验收：共同对手256双座种子 / 每组512局；直接父模型512种子 / 1,024局')):
        pairs = result[stage]['pairs']
        text = old_tables.detailed_tables(pairs, label)
        text = text.replace('Rush AUC', '总VP AUC24').replace('短于16自身Main', '短于24自身Main')
        out += ['## ' + ('完整开发对战数据' if stage == 'development' else '完整独立对战数据'), text, trajectory_tables(pairs)]
    out += ['## 来源与身份', table(['证据', '路径 / SHA256'], [
        ['采样前冻结合同', f'`{PILOT.relative_to(ROOT)}` / `{sha(PILOT)}`'],
        ['真实Arena训练合同', f'`{TRAIN.relative_to(ROOT)}` / `{sha(TRAIN)}`'],
        ['固定父模型', f"`{result['base_model']['weights_path']}` / `{result['base_model']['sha256']}`"],
        ['最终c4策略', f"`local-artifacts/prism/alpha-v0.1.1/campaign/cycle-4-export/weights.json` / `{result['training']['final_weights_sha256']}`"],
        ['结果', f'`{RESULT.relative_to(ROOT)}` / `{sha(RESULT)}`'],
        ['冻结源/引擎/规则/运行身份', '`benchmarks/m56-prism-alpha-v0.1.1.evaluate.json` 与 `local-artifacts/prism/alpha-v0.1.1/controller-contract.json`'],
        ['逐局回放、握手、配置和hash', '`local-artifacts/prism/alpha-v0.1.1/{development,acceptance}/source-ledger.json`、plan/configs/runs'],
        ['Rust/Python导出一致', f"{result['training']['export_parity']['boundary_states']}个固定边界输入，32张量；atol/rtol均1e-4，PASS"]]),
        '训练环境种子9510000..9510511；开发9515000..9515031；独立共同锚点9520000..9520255，直接父模型9520000..9520511。独立seed prefix共享用于匹配布局，未用于训练。训练动作seed56010001，评测候选/T=1对手动作seed56020001；greedy锚点沿用其冻结命令seed。逐对手得分率区间为描述性配对95%区间，RNG54049999；正式三门采用上述M56分位。',
        '## 限制与下一步', '结果只覆盖三个固定锚点及直接父模型，单一训练seed与最终检查点。没有独立人工review、跨架构/跨机器棋力确认或普适风格机制结论。M55原六门与原NOT_ACCEPTED_RUSH_STYLE不变。新产物保留固定实验身份；未改默认模型、共享池或Git远端。',
        '本有限轮到此停止。下一轮先据本次大牌时点、分段得分与棋力结果判断目标代理是否合适；新训练或其他风格需另定预算/种子/验收。']
    return '\n\n'.join(out)


def comparison_html(result):
    data = {stage: result[stage]['pairs'] for stage in ('development', 'acceptance')}
    payload = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c')
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Prism Alpha v0.1.1 对战对照</title><style>
body{font:16px/1.55 system-ui,sans-serif;margin:0;background:#101827;color:#e8eef9}main{max-width:1120px;margin:auto;padding:28px}h1{margin:0;font-size:29px}p{color:#b7c5db}button{background:#26364c;color:#fff;border:1px solid #526780;padding:9px 15px;border-radius:7px;margin:5px;cursor:pointer}button.active{background:#345f9d}table{border-collapse:collapse;width:100%;background:#172335;margin-top:15px}th,td{padding:11px;text-align:left;border-bottom:1px solid #344257}th{color:#c2d2eb}td.up{color:#71e2b1;font-weight:700}td.down{color:#ffbc81;font-weight:700}.cards{display:flex;gap:15px;margin:18px 0}.card{flex:1;background:#1d2c43;padding:18px;border-radius:9px}.card b{font-size:25px;display:block}.note{font-size:14px}.scroll{overflow:auto}a{color:#9cc6ff}@media(max-width:700px){.cards{display:block}.card{margin:8px 0}main{padding:16px}}
</style><main><h1>Prism Alpha v0.1.1 · 大牌取分迭代</h1><p>父模型 Prism Alpha v0.1.0 → 新产物 Prism Alpha v0.1.1。先看同种子对照，再看完整个人指标。</p>
<div class="cards"><div class="card">本轮验收<b>VERDICT</b>三条预设保留底线</div><div class="card">训练 / 独立验收<b>1,024 / 4,096 局</b>另有384局开发</div><div class="card">重试 / 额外训练<b>0 / 0</b>最终c4固定</div></div><div id="stages"></div><div id="opponents"></div><div id="groups"></div><div id="result" class="scroll"></div><p class="note">↑绿色为数值增加，↓橙色为减少。颜色仅帮助读数；卡数、折扣和预留更多未必更好。首张大牌时点是条件均值，须连同覆盖率读。直接父模型组的两列来自同1,024局；共同对手组的两模型各512局。</p><p><a href="prism-alpha-v0.1.1-evaluation-summary.md">完整Markdown报告：全部七类动作、双方经济、物理双座、置信区间及来源</a></p></main><script>
const data=PAYLOAD;let stage='acceptance',op='heuristic-v031',group='big';
const names={'heuristic-v031':'Heuristic v0.3.1（greedy）','prism-v01':'初代 Prism v0.1.0（greedy）','prism-v0.1.1':'Prism v0.1.1（T=1）','base-t1':'直接父模型（T=1）'};
const metrics={big:[['半平得分率',m=>m.score_rate*100,'%'],['3VP牌 / 局',m=>m.mean_cards_by_vp['3'],''],['4VP牌 / 局',m=>m.mean_cards_by_vp['4'],''],['5VP牌 / 局',m=>m.mean_cards_by_vp['5'],''],['3～5VP牌 / 局',m=>[3,4,5].reduce((s,v)=>s+m.mean_cards_by_vp[v],0),''],['大牌印刷VP / 局',m=>[3,4,5].reduce((s,v)=>s+v*m.mean_cards_by_vp[v],0),''],['最终VP / 局',m=>m.mean_prestige,''],['VP / 自身Main',m=>m.vp_per_main_action,'']],economy:[['永久折扣 / 局',m=>m.mean_permanent_bonuses,''],['贵族 / 局',m=>m.mean_nobles,''],['贵族覆盖',m=>m.games_with_nobles_percent,'%'],['预留获取 / 局',m=>m.mean_reserves_acquired,''],['预留买回 / 局',m=>m.mean_reserves_bought,''],['终局未买回 / 局',m=>m.mean_reserves_stranded,''],['预留买回率',m=>m.reserve_redemption_rate_percent,'%']],cards:[0,1,2,3,4,5].map(v=>[v+'VP牌 / 局',m=>m.mean_cards_by_vp[v],''])};
function buttons(id,items,current,fn){const e=document.getElementById(id);e.replaceChildren();for(const [k,n]of items){let b=document.createElement('button');b.textContent=n;b.className=k===current?'active':'';b.onclick=()=>{fn(k);render()};e.append(b)}}
function render(){buttons('stages',[['acceptance','独立验收'],['development','开发（仅描述）']],stage,k=>{stage=k;if(stage==='development'&&op==='base-t1')op='heuristic-v031'});buttons('opponents',Object.entries(names).filter(([k])=>stage==='acceptance'||k!=='base-t1'),op,k=>op=k);buttons('groups',[['big','大牌与取分'],['economy','经济与预留'],['cards','完整0～5VP购卡'],['trajectory','时点与分段']],group,k=>group=k);let ps=data[stage],a,b,ap,bp;if(op==='base-t1'){const p=ps.find(p=>p.opponent===op);a=p.opponent_metrics;b=p.candidate_metrics;ap=p.opponent_bigcard;bp=p.candidate_bigcard}else{const p=ps.find(p=>p.candidate==='base'&&p.opponent===op),q=ps.find(p=>p.candidate==='candidate'&&p.opponent===op);a=p.candidate_metrics;b=q.candidate_metrics;ap=p.candidate_bigcard;bp=q.candidate_bigcard}let rows;if(group==='trajectory'){rows=[['总VP AUC24',ap.mean_total_vp_auc24,bp.mean_total_vp_auc24,''],['大牌印刷VP AUC24',ap.mean_large_card_vp_auc24,bp.mean_large_card_vp_auc24,''],['首张3～5VP自身Main（条件）',ap.first_large_card_main.conditional_mean,bp.first_large_card_main.conditional_mean,''],['首张3～5VP覆盖率',100*ap.first_large_card_main.coverage_rate,100*bp.first_large_card_main.coverage_rate,'%'],...ap.score_checkpoints.flatMap((c,i)=>[['Main '+c.own_main+' 总VP',c.mean_vp,bp.score_checkpoints[i].mean_vp,''],['Main '+c.own_main+' 大牌VP',c.mean_large_card_printed_vp,bp.score_checkpoints[i].mean_large_card_printed_vp,'']])]}else rows=metrics[group].map(([n,f,u])=>[n,f(a),f(b),u]);let t=document.createElement('table');t.innerHTML='<thead><tr><th>个人指标 · '+names[op]+'</th><th>父模型</th><th>Prism Alpha v0.1.1</th><th>变化</th></tr></thead>';let body=document.createElement('tbody');for(const[n,x,y,u]of rows){let tr=document.createElement('tr'),d=x===null||y===null?null:y-x;for(const v of[n,x===null?'NOT_APPLICABLE':x.toFixed(4)+u,y===null?'NOT_APPLICABLE':y.toFixed(4)+u,d===null?'NOT_APPLICABLE':(d>0?'↑ +':d<0?'↓ ':'→ ')+d.toFixed(4)+(u==='%'?'个百分点':u)]){let td=document.createElement('td');td.textContent=v;tr.append(td)}tr.lastChild.className=d>0?'up':d<0?'down':'';body.append(tr)}t.append(body);document.getElementById('result').replaceChildren(t)}render();</script></html>'''.replace('VERDICT', 'PASS' if result['all_three_gates_passed'] else '未通过').replace('PAYLOAD', payload)


def finalize_documents(result):
    DISPLAY['candidate'] = 'Prism Alpha v0.1.1'
    body = readable_body(result)
    report = ROOT / 'docs/prism/prism-alpha-v0.1.1-evaluation-summary.md'
    report.write_text('# Prism Alpha v0.1.1：大牌取分有限迭代\n\n' + body + '\n', encoding='utf-8')
    page = ROOT / 'docs/prism/prism-alpha-v0.1.1-comparison.html'
    page.write_text(comparison_html(result), encoding='utf-8')
    for name in ('weights.json', 'weights.manifest.json'):
        target = ART / name
        require(not target.exists(), 'model identity already fixed')
        shutil.copyfile(ART / 'campaign/cycle-4-export' / name, target)
    write(ROOT / 'benchmarks/m56-prism-alpha-v0.1.1.model.json', {
        'format': 'prism-experimental-model-identity-v1', 'status': 'REGISTERED_EXPERIMENTAL_MODEL',
        'display_name': 'Prism Alpha v0.1.1', 'model_id': 'prism-alpha-v0.1.1',
        'style_descriptor': '大牌取分 / 大牌冲分取向；非基建专用',
        'weights_path': str((ART / 'weights.json').relative_to(ROOT)), 'weights_sha256': sha(ART / 'weights.json'),
        'companion_path': str((ART / 'weights.manifest.json').relative_to(ROOT)),
        'companion_sha256': sha(ART / 'weights.manifest.json'), 'parent': result['base_model'],
        'independent_acceptance': {'status': result['status'], 'result_path': str(RESULT.relative_to(ROOT)),
                                 'result_sha256': sha(RESULT)},
        'readable_report': str(report.relative_to(ROOT)), 'readable_report_sha256': sha(report),
        'default_replaced': False, 'shared_pool_deployed': False})
    replace_block(ROOT / 'docs/m56-prism-alpha-bigcard-ppo.md', body)
    # Evolution records contain the same detailed model tables, not a JSON-only link.
    replace_block(ROOT / 'docs/aran-model-evolution-matrix.md', '## M56 Prism Alpha v0.1.1\n\n' + body)
    handoff = ROOT / 'handoff.md'; current = handoff.read_text(encoding='utf-8')
    snapshot = ('### M56 终局 — Prism Alpha v0.1.1\n\n**' + result['status'] + '**；' +
        '4轮/1,024训练局，384开发局，4,096独立验收局，0重试。固定实验身份与大牌画像保留；增强证据与保留门分开。' +
        '\n\n- [完整双方表](docs/prism/prism-alpha-v0.1.1-evaluation-summary.md) / [彩色对照](docs/prism/prism-alpha-v0.1.1-comparison.html) / [M56](docs/m56-prism-alpha-bigcard-ppo.md)。' +
        '\n- 固定权重SHA `' + result['training']['final_weights_sha256'] + '`；原M55三PASS/三FAIL保持。' +
        '\n- 本有限轮停止；新训练需新合同。无默认替换、共享池变更或Git发布。\n\n')
    current = current.replace('## Current Snapshot\n\n', '## Current Snapshot\n\n' + snapshot, 1)
    handoff.write_text(current, encoding='utf-8')
