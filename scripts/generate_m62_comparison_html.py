import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parents[1]
RESULT_PATH = ROOT / 'local-artifacts/prism/building-beta-m62/evaluation/result.json'
CONFIG_PATH = ROOT / 'benchmarks/m62-prism-beta-building.config.json'
OUT_HTML = ROOT / 'docs/prism/prism-beta-v0.1.0-comparison.html'

result = json.loads(RESULT_PATH.read_text(encoding='utf-8'))
config = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))

names = {
    'heuristic-v031': 'Heuristic v0.3.1 (greedy)',
    'prism-general-v011': 'Prism v0.1.1 (T=1)',
    'prism-v01': '初代 Prism v0.1.0 (greedy)',
    'alpha-t1': 'Prism Alpha v0.1.4 (T=1，大牌流)',
    'base-t1': 'Prism Balance v0.1.0 (父模型)',
    'control-t1': 'Prism Balance v0.1.1 candidate (Control，未发布)',
}

cnames = {
    'base': 'Prism Balance v0.1.0 (父代)',
    'control': 'Prism Balance v0.1.1 candidate (Control，未发布)',
    'beta': 'Prism Beta v0.1.0 candidate',
}

gates_data = [
    {
        'label': 'control/strength_pool',
        'role': 'Control 总体保留底线',
        'mean': result['measurements']['control/strength_pool']['mean'],
        'unit': 'pp',
        'threshold': -0.05,
        'lower': result['measurements']['control/strength_pool']['simultaneous_one_sided_lower'],
        'strict': False,
        'original_pass': result['gates']['control/strength_pool'],
        'reading': 'PASS 排除退步超 5pp',
    },
    {
        'label': 'control/direct_parent',
        'role': 'Control 对父直接得分率',
        'mean': result['measurements']['control/direct_parent']['mean'],
        'unit': 'rate',
        'threshold': 0.45,
        'lower': result['measurements']['control/direct_parent']['simultaneous_one_sided_lower'],
        'strict': False,
        'original_pass': result['gates']['control/direct_parent'],
        'reading': 'PASS 确认直接得分率 >= 45%',
    },
    {
        'label': 'beta/strength_pool',
        'role': 'Beta 总体代价控制',
        'mean': result['measurements']['beta/strength_pool']['mean'],
        'unit': 'pp',
        'threshold': -0.05,
        'lower': result['measurements']['beta/strength_pool']['simultaneous_one_sided_lower'],
        'strict': False,
        'original_pass': result['gates']['beta/strength_pool'],
        'reading': 'PASS 排除相对 Control 退步超过 5pp',
    },
    {
        'label': 'beta/general_anchor',
        'role': '关键通用锚点保护 (Prism v0.1.1)',
        'mean': result['measurements']['beta/general_anchor']['mean'],
        'unit': 'pp',
        'threshold': -0.075,
        'lower': result['measurements']['beta/general_anchor']['simultaneous_one_sided_lower'],
        'strict': False,
        'original_pass': result['gates']['beta/general_anchor'],
        'reading': 'FAIL 未能排除退步超过 7.5pp；未证明退化',
    },
    {
        'label': 'beta/direct_control',
        'role': 'Beta 对 Control 直接得分率',
        'mean': result['measurements']['beta/direct_control']['mean'],
        'unit': 'rate',
        'threshold': 0.45,
        'lower': result['measurements']['beta/direct_control']['simultaneous_one_sided_lower'],
        'strict': False,
        'original_pass': result['gates']['beta/direct_control'],
        'reading': 'FAIL 未能确认达到 45% 底线',
    },
    {
        'label': 'beta/direct_alpha',
        'role': '大牌流路线竞争力 (Alpha v0.1.4)',
        'mean': result['measurements']['beta/direct_alpha']['mean'],
        'unit': 'rate',
        'threshold': 0.45,
        'lower': result['measurements']['beta/direct_alpha']['simultaneous_one_sided_lower'],
        'strict': False,
        'original_pass': result['gates']['beta/direct_alpha'],
        'reading': 'PASS 确认对 Alpha 直接优势 (>50%)',
    },
    {
        'label': 'beta/direct_parent',
        'role': 'Beta 对父直接得分率',
        'mean': result['measurements']['beta/direct_parent']['mean'],
        'unit': 'rate',
        'threshold': 0.45,
        'lower': result['measurements']['beta/direct_parent']['simultaneous_one_sided_lower'],
        'strict': False,
        'original_pass': result['gates']['beta/direct_parent'],
        'reading': 'PASS 确认直接得分率 >= 45%',
    },
    {
        'label': 'beta/building_utility',
        'role': '早期投资兑现效用增量',
        'mean': result['measurements']['beta/building_utility']['mean'],
        'unit': 'auc',
        'threshold': 0.015,
        'lower': result['measurements']['beta/building_utility']['simultaneous_one_sided_lower'],
        'strict': False,
        'original_pass': result['gates']['beta/building_utility'],
        'reading': 'FAIL 增幅仅 +0.0033 未达标',
    },
    {
        'label': 'beta/early_bonus_auc12',
        'role': '前12Main永久折扣增量',
        'mean': result['measurements']['beta/early_bonus_auc12']['mean'],
        'unit': 'auc',
        'threshold': 0.25,
        'lower': result['measurements']['beta/early_bonus_auc12']['simultaneous_one_sided_lower'],
        'strict': False,
        'original_pass': result['gates']['beta/early_bonus_auc12'],
        'reading': 'FAIL 增幅仅 +0.0186 折扣未达标',
    },
]

for gate in gates_data:
    gate['ci95'] = result['measurements'][gate['label']]['ci95']

model_data = {
    'result': result,
    'config': {'format': config.get('format'), 'name': 'm62-prism-beta-building'},
    'gates': gates_data,
    'names': names,
    'cnames': cnames,
    'completedLocal': datetime.fromisoformat(result['finished_at']).astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M'),
}

html_template = '''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Prism Beta v0.1.0 candidate · 基建风格探索与同起点对照</title>
<style>
:root{color-scheme:light dark;--bg:#f4f6f8;--card:#fff;--ink:#18212d;--muted:#586678;--line:#dfe5ed;--up:#076c77;--down:#8d500b;--up-bg:#e4f5f6;--down-bg:#fff1d8;--pass:#206637;--pass-bg:#e8f4eb;--pending:#825306;--pending-bg:#fff3d6;--fail:#b22222;--fail-bg:#fdf2f2;--soft:#edf1f6}
@media(prefers-color-scheme:dark){:root{--bg:#131820;--card:#1c2430;--ink:#edf2f7;--muted:#b0bdce;--line:#394657;--up:#85dedb;--down:#f1cc8e;--up-bg:#173a40;--down-bg:#433321;--pass:#a0d9af;--pass-bg:#203b2c;--pending:#f3cf8d;--pending-bg:#423720;--fail:#ff8a8a;--fail-bg:#471c1c;--soft:#253040}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:"Microsoft YaHei","Segoe UI",sans-serif;line-height:1.6}main{max-width:1380px;margin:auto;padding:32px 28px}h1{font-size:28px;line-height:1.35;margin:9px 0 12px;letter-spacing:-.5px}h2{font-size:19px;margin:8px 0 14px}h3{font-size:16px;margin:12px 0}.eyebrow{color:var(--muted);font-size:13px}.subtitle{font-size:15.5px;margin:0 0 20px}.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:18px 0}.card,.section{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:19px 20px}.card .title{font-size:13px;color:var(--muted)}.card .value{font-size:22px;font-weight:700;margin:5px 0}.card p{margin:4px 0;font-size:12.5px}.section{margin:16px 0}.status{display:inline-block;font-weight:600;padding:4px 10px;border-radius:7px;font-size:13px;white-space:nowrap}.pass{color:var(--pass);background:var(--pass-bg)}.pending{color:var(--pending);background:var(--pending-bg)}.fail{color:var(--fail);background:var(--fail-bg)}.note{color:var(--muted);font-size:13px;margin:9px 0}.tiny{font-size:12px;color:var(--muted)}.controls{display:flex;flex-wrap:wrap;align-items:center;gap:12px;margin:12px 0 17px}button,select{font:inherit;background:var(--soft);color:var(--ink);border:1px solid var(--line);border-radius:7px;padding:8px 12px}button{cursor:pointer}button[aria-pressed=true]{background:var(--ink);color:var(--card)}label{font-size:13px}select{margin-left:6px}.scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:10px 9px;border-bottom:1px solid var(--line);vertical-align:middle;text-align:right;font-variant-numeric:tabular-nums}th{color:var(--muted);font-weight:600}th:first-child,td:first-child{text-align:left}th{background:var(--card)}td:first-child{font-weight:600;min-width:145px}.delta{display:inline-block;border-radius:5px;padding:3px 7px;font-weight:700;white-space:nowrap}.up{color:var(--up);background:var(--up-bg)}.down{color:var(--down);background:var(--down-bg)}.same{color:var(--muted);background:var(--soft)}.subhead th{font-size:12px;padding:6px 9px}.muted{color:var(--muted)}.baseline{color:var(--muted)}.candidate{font-weight:700}.stage{font-size:15px;font-weight:700;padding:7px 10px;border-radius:6px;background:var(--soft)}summary{font-weight:600;cursor:pointer;padding:7px 0}.source{overflow-wrap:anywhere;font-family:Consolas,monospace;font-size:12px}.footer{margin-top:26px;color:var(--muted);font-size:13px}@media(max-width:900px){main{padding:20px 13px}.cards{grid-template-columns:1fr 1fr}.card{padding:14px}h1{font-size:24px}th,td{padding:8px 7px}.section{padding:16px 12px}}
</style>
</head>
<body><main>
<header><div class="eyebrow">M62 · 风格路线对照实验 · <span id="completed"></span> 北京时间</div>
<h1>Prism Beta v0.1.0 candidate：基建风格探索与同起点对照</h1>
<p class="subtitle">同父起步（Prism Balance v0.1.0）分出 Control 与 Beta，各串行训练 1,024 局。<strong>Control 保留门全部 PASS；Beta 风格门未过，判定 NOT_ACCEPTED_BUILDING_CANDIDATE，不予发布。</strong></p>
<div class="cards" id="summary-cards">
  <div class="card"><div class="title">全量评测对局</div><div class="value">9,280 局</div><p>2,048训练 · 576开发 · 8,704独立</p><span class="status pass">0 重试 · cgroup 8G</span></div>
  <div class="card"><div class="title">Control 参照保留门</div><div class="value">2 / 2 PASS</div><p>总体保留 +1.30pp · 对父 52.05%</p><span class="status pass">底线稳固</span></div>
  <div class="card"><div class="title">Beta 七项核心门</div><div class="value">3 PASS / 4 FAIL</div><p>通用锚点与直接得分率底线未获确认</p><span class="status fail">未达晋升条件</span></div>
  <div class="card"><div class="title">基建风格判定</div><div class="value">FAIL</div><p>效用差+0.0033 / 折扣差+0.0186</p><span class="status fail">未达到实质风格门槛</span></div>
</div>
</header>
<section class="section" id="comparison-section">
<h2>同一对手、同一批种子：父代 → Control → Beta 三方全量对照</h2>
<div class="controls">
  <button type="button" id="acceptance-button" aria-pressed="true">独立验收 · 8,704 局</button>
  <button type="button" id="development-button" aria-pressed="false">开发评测 · 576 局（仅描述）</button>
  <label>指标组
    <select id="group">
      <option value="core">关键变化与胜率</option>
      <option value="building">基建风格专属画像</option>
      <option value="economy">经济与节奏</option>
      <option value="cards">卡牌 VP 与五色折扣</option>
      <option value="actions">全部七类动作</option>
    </select>
  </label>
  <label>对手
    <select id="opponent">
      <option value="anchors">三个共同锚点汇总</option>
      <option value="heuristic-v031">Heuristic v0.3.1 (greedy)</option>
      <option value="prism-general-v011">Prism v0.1.1 (T=1)</option>
      <option value="prism-v01">初代 Prism v0.1.0 (greedy)</option>
      <option value="alpha-t1">Prism Alpha v0.1.4 (T=1，大牌流对决)</option>
      <option value="base-t1">Prism Balance v0.1.0 (对父直接对决)</option>
      <option value="control-t1">Control 候选 (对Control直接对决)</option>
    </select>
  </label>
</div>
<div class="stage" id="stage-label"></div>
<p class="note">↑ 只是数值更高，↓ 只是数值更低；不自动等于更好或显著。pp = 百分点。每列均为模型本人指标，双座已严格合并。</p>
<div class="scroll" id="comparison-table"></div>
</section>
<section class="section"><h2>九项采样前冻结门（Bootstrap 判定结果）</h2>
<p class="note">family α=0.05，9项单侧同时下界（q=0.05/9），20,000次配对双座种子块抽样（RNG 62049999）。所有门均在第一局采样前锁定。pp = 百分点；% = 半平得分率。</p>
<p class="note">Beta 对固定 Prism Alpha v0.1.4 的直接优势已确认（54.98%，校正下界50.98%）。早期折扣差的校正下界+0.000380高于0，但未达到+0.25个折扣的实质门槛。底线 FAIL 表示容忍要求未获确认，不等于证明模型退化；奖励失效或克制机制仍需诊断。</p>
<div class="scroll" id="gate-table"></div>
</section>
<section class="section"><h2>完整双方数据 · 当前选中的评测组</h2><div id="full-data"></div></section>
<footer class="footer">数据源自 local-artifacts/prism/building-beta-m62/ 独立审计与评测结果。未替换默认模型、未向共享池部署。
<br><a href="m62-prism-beta-building-comparison.html">全量展开版 HTML 报告 (97 表)</a> · <a href="m62-prism-beta-building-evaluation.md">Markdown 完整报告 (7.8 MB)</a></footer>
</main>
<script>
'use strict';
const DATA = __MODEL_DATA__;
const names = DATA.names;
const cnames = DATA.cnames;
let activeStage = 'acceptance';

const byId = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

const fmt = (v, u='number') => {
  if (v === null || v === undefined) return 'N/A';
  if (u === 'rate') return (v * 100).toFixed(2) + '%';
  if (u === 'percent') return v.toFixed(2) + '%';
  if (u === 'count') return Math.round(v).toLocaleString('zh-CN');
  if (u === 'auc') return v.toFixed(6);
  return v.toFixed(4);
};

const signed = (v, d=4) => (v > 0 ? '+' : '') + v.toFixed(d);

const deltaHTML = (a, b, u) => {
  if (a === null || a === undefined || b === null || b === undefined) return '<span class="delta same">-</span>';
  const d = b - a;
  const x = u === 'rate' ? d * 100 : d;
  const n = (u === 'rate' || u === 'percent') ? 2 : (u === 'count' ? 0 : 4);
  const cls = d > 0 ? 'up' : d < 0 ? 'down' : 'same';
  const sym = d > 0 ? '↑' : d < 0 ? '↓' : '＝';
  return `<span class="delta ${cls}">${sym} ${signed(x, n)}${(u==='rate'||u==='percent')?'pp':''}</span>`;
};

const getMetric = (p, key) => {
  if (!p) return null;
  if (key.startsWith('building.')) {
    const k = key.replace('building.', '');
    return p.candidate_building ? p.candidate_building[k] : null;
  }
  if (key === 'score_rate') return p.candidate_metrics.score_rate;
  if (key === 'win_rate_percent') return p.candidate_metrics.win_rate_percent;
  return key.split('.').reduce((v, k) => (v ? v[k] : null), p.candidate_metrics);
};

// Ratios across opponents use the total numerator and denominator. Counts sum;
// other means are game weighted. The fixed gate calculations are unchanged.
const pooledMetric = (pairs, key) => {
  if (!pairs.length) return null;
  const sum = getter => pairs.reduce((value, pair) => value + getter(pair), 0);
  const games = sum(p => p.candidate_metrics.games);
  const vp = sum(p => p.candidate_metrics.mean_prestige * p.candidate_metrics.games);
  const ratio = (n, d, scale=1) => d ? scale * n / d : null;
  if (key === 'score_rate') return ratio(sum(p => p.candidate_metrics.wins + .5 * p.candidate_metrics.ties), games);
  if (key === 'win_rate_percent') return ratio(sum(p => p.candidate_metrics.wins), games, 100);
  if (key === 'games_with_nobles_percent') return ratio(sum(p => p.candidate_metrics.games_with_nobles), games, 100);
  if (key === 'reserve_redemption_rate_percent') return ratio(
    sum(p => p.candidate_metrics.mean_reserves_bought * p.candidate_metrics.games),
    sum(p => p.candidate_metrics.mean_reserves_acquired * p.candidate_metrics.games), 100);
  if (key === 'vp_per_main_action') return ratio(vp, sum(p => p.candidate_metrics.total_main_actions));
  if (key === 'vp_per_turn') return ratio(vp, sum(p => p.candidate_metrics.total_actor_decisions));
  if (key === 'vp_per_ply') return ratio(vp, sum(p => p.macro.total_plies));
  if (key === 'building.investment_redemption_rate') return ratio(
    sum(p => p.candidate_building.total_redeemed_investments),
    sum(p => p.candidate_building.total_early_lowvp_buys));
  if (key.startsWith('action_distribution.')) return sum(p => getMetric(p, key));
  if (key.startsWith('action_percentages.')) return ratio(
    sum(p => p.candidate_metrics.action_distribution[key.split('.')[1]]),
    sum(p => p.candidate_metrics.total_actor_decisions), 100);
  return ratio(sum(p => getMetric(p, key) * p.candidate_metrics.games), games);
};

const core = [
  ['半平得分率', 'score_rate', 'rate'],
  ['纯胜率', 'win_rate_percent', 'percent'],
  ['局均最终 VP', 'mean_prestige', 'number'],
  ['VP / 自身 Main', 'vp_per_main_action', 'number'],
  ['基建 building 效用', 'building.mean_building_utility', 'auc'],
  ['前12Main 早期 bonus AUC12', 'building.mean_early_bonus_auc12', 'auc'],
  ['终局永久折扣总数', 'mean_permanent_bonuses', 'number'],
  ['终局未买回预留', 'mean_reserves_stranded', 'number'],
];

const building = [
  ['基建 building 效用 (0..1)', 'building.mean_building_utility', 'auc'],
  ['前12Main 早期 bonus AUC12', 'building.mean_early_bonus_auc12', 'auc'],
  ['早期投资低分卡购入 (VP<=1)', 'building.mean_early_lowvp_buys', 'number'],
  ['早期投资兑现数', 'building.mean_redeemed_investments', 'number'],
  ['早期投资兑现率', 'building.investment_redemption_rate', 'rate'],
  ['终局未兑现投资数', 'building.mean_unredeemed_investments', 'number'],
  ['building 使用单位数', 'building.mean_building_use_units', 'number'],
  ['Main 25..32 后期购卡得分', 'building.mean_late_scoring_vp_main25to32', 'number'],
];

const economy = [
  ['局均最终 VP', 'mean_prestige', 'number'],
  ['VP / 自身决策', 'vp_per_turn', 'number'],
  ['VP / 自身 Main', 'vp_per_main_action', 'number'],
  ['VP / 全局步数', 'vp_per_ply', 'number'],
  ['局均永久折扣', 'mean_permanent_bonuses', 'number'],
  ['局均贵族', 'mean_nobles', 'number'],
  ['获得贵族对局比例', 'games_with_nobles_percent', 'percent'],
  ['局均预留获取', 'mean_reserves_acquired', 'number'],
  ['局均预留买回', 'mean_reserves_bought', 'number'],
  ['终局未买回预留', 'mean_reserves_stranded', 'number'],
  ['预留兑现率', 'reserve_redemption_rate_percent', 'percent'],
];

const cards = [
  ...Array.from({length:6}, (_, i) => [`局均购入 ${i} VP卡`, `mean_cards_by_vp.${i}`, 'number']),
  ...['White','Blue','Green','Red','Black'].map((c, i) => [`局均${['白','蓝','绿','红','黑'][i]}折扣`, `mean_bonuses_by_color.${c}`, 'number']),
];

const actionLabels = ['买市场卡', '买预留卡', '拿筹码', '预留市场卡', '盲预留牌堆', '选贵族', '跳过'];
const actionKeys = ['buy_market', 'buy_reserved', 'take_tokens', 'reserve_market', 'reserve_deck', 'choose_noble', 'pass'];
const actions = actionKeys.flatMap((a, i) => [
  [actionLabels[i] + ' 次数', `action_distribution.${a}`, 'count'],
  [actionLabels[i] + ' 占自身决策', `action_percentages.${a}`, 'percent'],
]);

const groups = {core, building, economy, cards, actions};

const getPairs = stage => DATA.result[stage].pairs;
const findPair = (stage, cand, opp) => getPairs(stage).find(p => p.candidate === cand && p.opponent === opp);

function renderComparison() {
  const group = groups[byId('group').value];
  const choice = byId('opponent').value;
  const isAnchors = (choice === 'anchors');
  const anchorOpps = ['heuristic-v031', 'prism-general-v011', 'prism-v01'];
  
  byId('stage-label').textContent = (activeStage === 'acceptance' ? '独立验收 · 8,704 局' : '开发评测 · 576 局（仅描述）') +
    (isAnchors ? ' · 三个共同锚点汇总（比例取总计数 / 总分母）' : ` · 对战对手: ${names[choice] || choice}`);
  
  byId('acceptance-button').setAttribute('aria-pressed', String(activeStage === 'acceptance'));
  byId('development-button').setAttribute('aria-pressed', String(activeStage === 'development'));
  
  let html = '<table><thead><tr>' +
    '<th>被测玩家指标</th>' +
    `<th>${esc(cnames.base)}</th>` +
    `<th>${esc(cnames.control)}</th>` +
    `<th>${esc(cnames.beta)}</th>` +
    '<th>Control − 父代</th>' +
    '<th>Beta − Control</th>' +
    '<th>Beta − 父代</th>' +
    '</tr></thead><tbody>';
  
  for (const [label, key, unit] of group) {
    let vBase = null, vControl = null, vBeta = null;
    
    if (isAnchors) {
      vBase = pooledMetric(anchorOpps.map(op => findPair(activeStage, 'base', op)).filter(Boolean), key);
      vControl = pooledMetric(anchorOpps.map(op => findPair(activeStage, 'control', op)).filter(Boolean), key);
      vBeta = pooledMetric(anchorOpps.map(op => findPair(activeStage, 'beta', op)).filter(Boolean), key);
    } else {
      vBase = getMetric(findPair(activeStage, 'base', choice), key);
      vControl = getMetric(findPair(activeStage, 'control', choice), key);
      vBeta = getMetric(findPair(activeStage, 'beta', choice), key);
    }
    
    html += `<tr>` +
      `<td>${esc(label)}</td>` +
      `<td class="baseline">${fmt(vBase, unit)}</td>` +
      `<td>${fmt(vControl, unit)}</td>` +
      `<td class="candidate">${fmt(vBeta, unit)}</td>` +
      `<td>${deltaHTML(vBase, vControl, unit)}</td>` +
      `<td>${deltaHTML(vControl, vBeta, unit)}</td>` +
      `<td>${deltaHTML(vBase, vBeta, unit)}</td>` +
      `</tr>`;
  }
  
  byId('comparison-table').innerHTML = html + '</tbody></table>';
  renderFull();
}

function renderGates() {
  const gateFormat = (v, u) => u === 'auc' ? signed(v, 6) : u === 'pp' ? signed(v * 100, 2) + ' pp' : (v * 100).toFixed(2) + '%';
  let html = '<table><thead><tr>' +
    '<th>门标识 / 目的</th>' +
    '<th>实测点估计</th>' +
    '<th>普通配对95% CI</th>' +
    '<th>冻结阈值</th>' +
    '<th>九门同时单侧下界</th>' +
    '<th>判定结果与解释</th>' +
    '</tr></thead><tbody>';
  
  for (const g of DATA.gates) {
    const cls = g.original_pass ? 'pass' : 'fail';
    html += `<tr>` +
      `<td><b>${esc(g.label)}</b><br><span class="tiny">${esc(g.role)}</span></td>` +
      `<td>${gateFormat(g.mean, g.unit)}</td>` +
      `<td>[${g.ci95.map(v => gateFormat(v, g.unit)).join(', ')}]</td>` +
      `<td>下界 ≥ ${gateFormat(g.threshold, g.unit)}</td>` +
      `<td><b>${gateFormat(g.lower, g.unit)}</b></td>` +
      `<td><span class="status ${cls}">${esc(g.reading)}</span></td>` +
      `</tr>`;
  }
  byId('gate-table').innerHTML = html + '</tbody></table>';
}

function renderFull() {
  const currentPairs = getPairs(activeStage);
  const choice = byId('opponent').value;
  const filtered = (choice === 'anchors')
    ? currentPairs
    : currentPairs.filter(p => p.opponent === choice);
  
  let html = '';
  for (const p of filtered) {
    const candName = cnames[p.candidate] || p.candidate_display;
    const oppName = names[p.opponent] || p.opponent_display;
    const cm = p.candidate_metrics;
    const om = p.opponent_metrics;
    
    html += `<details style="margin: 12px 0; border: 1px solid var(--line); border-radius: 8px; padding: 12px 16px; background: var(--card);">` +
      `<summary style="font-size: 15px;"><b>${esc(candName)}</b> vs <b>${esc(oppName)}</b> · ${cm.games} 局 · ${cm.wins} 胜 / ${cm.ties} 平 / ${cm.losses} 负 (半平得分率 ${fmt(cm.score_rate, 'rate')})</summary>` +
      `<p class="note">纯胜率: ${cm.win_rate_percent.toFixed(2)}% · 纯胜率配对95% CI: [${p.win_uncertainty.ordinary_95_ci.map(v => fmt(v, 'rate')).join(', ')}]；半平得分率配对95% CI: [${p.score_uncertainty.ordinary_95_ci.map(v => fmt(v, 'rate')).join(', ')}]。均为描述性区间。</p>` +
      `<p class="note">先后手明细: ${p.seats.map(s => `${s.candidate_seat===0?'先手 P0':'后手 P1'} ${s.candidate.games}局 ${s.candidate.wins}W/${s.candidate.ties}D/${s.candidate.losses}L (得分率 ${fmt(s.candidate.score_rate, 'rate')}，局均VP ${s.candidate.mean_prestige.toFixed(2)} vs ${s.opponent.mean_prestige.toFixed(2)})`).join('；')}</p>` +
      `<div class="scroll"><table><thead><tr><th>个人指标</th><th>${esc(candName)}</th><th>${esc(oppName)}</th></tr></thead><tbody>` +
      `<tr><td>终局 VP</td><td>${cm.mean_prestige.toFixed(2)}</td><td>${om.mean_prestige.toFixed(2)}</td></tr>` +
      `<tr><td>VP / 自身 Main 行动</td><td>${cm.vp_per_main_action.toFixed(4)}</td><td>${om.vp_per_main_action.toFixed(4)}</td></tr>` +
      `<tr><td>永久折扣总数</td><td>${cm.mean_permanent_bonuses.toFixed(2)}</td><td>${om.mean_permanent_bonuses.toFixed(2)}</td></tr>` +
      `<tr><td>斩获贵族数</td><td>${cm.mean_nobles.toFixed(2)}</td><td>${om.mean_nobles.toFixed(2)}</td></tr>` +
      `<tr><td>预留获取 / 买回 / 终局未买回</td><td>${cm.mean_reserves_acquired.toFixed(2)} / ${cm.mean_reserves_bought.toFixed(2)} / ${cm.mean_reserves_stranded.toFixed(2)} (兑现率 ${cm.reserve_redemption_rate_percent.toFixed(1)}%)</td><td>${om.mean_reserves_acquired.toFixed(2)} / ${om.mean_reserves_bought.toFixed(2)} / ${om.mean_reserves_stranded.toFixed(2)} (兑现率 ${om.reserve_redemption_rate_percent.toFixed(1)}%)</td></tr>` +
      `<tr><td>卡牌 VP 分布 [0/1/2/3/4/5分]</td><td>${[0,1,2,3,4,5].map(v => cm.mean_cards_by_vp[v].toFixed(2)).join(' / ')}</td><td>${[0,1,2,3,4,5].map(v => om.mean_cards_by_vp[v].toFixed(2)).join(' / ')}</td></tr>` +
      `<tr><td>五色折扣 [白/蓝/绿/红/黑]</td><td>${['White','Blue','Green','Red','Black'].map(c => cm.mean_bonuses_by_color[c].toFixed(2)).join(' / ')}</td><td>${['White','Blue','Green','Red','Black'].map(c => om.mean_bonuses_by_color[c].toFixed(2)).join(' / ')}</td></tr>` +
      `</tbody></table></div>` +
      `<p class="note">宏观节奏: 局均步数 ${p.macro.mean_plies.toFixed(2)} · 局均轮数 ${p.macro.mean_turns.toFixed(2)} (最短 ${p.macro.min_turns} / 中位 ${p.macro.median_turns} / 最长 ${p.macro.max_turns}) · 终局分差 <= 2 比例 ${p.macro.close_games_margin_le_2_percent.toFixed(1)}%</p>` +
      `</details>`;
  }
  byId('full-data').innerHTML = html;
}

byId('completed').textContent = DATA.completedLocal;
byId('acceptance-button').addEventListener('click', () => {
  activeStage = 'acceptance';
  renderComparison();
});

byId('development-button').addEventListener('click', () => {
  activeStage = 'development';
  renderComparison();
});

byId('group').addEventListener('change', renderComparison);
byId('opponent').addEventListener('change', renderComparison);

renderGates();
renderComparison();
</script>
</body>
</html>
'''

data_json = json.dumps(model_data, ensure_ascii=False).replace('<', '\\u003c')
final_html = html_template.replace('__MODEL_DATA__', data_json)

OUT_HTML.write_bytes(final_html.encode('utf-8'))
print(f"Generated {OUT_HTML} (size: {len(final_html)} bytes)")
