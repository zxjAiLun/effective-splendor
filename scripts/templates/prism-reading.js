'use strict';
const data = JSON.parse(document.getElementById('report-data').textContent);
const R = data.result, S = data.story;
const E = x => String(x ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = (v,d=3) => typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : 'NOT_MEASURED';
const pct = v => typeof v === 'number' ? (100*v).toFixed(2)+'%' : 'NOT_MEASURED';
const name = key => data.names[key] || key;
const signed = (v,d=3) => (v>0?'↑ +':v<0?'↓ ':'→ ')+num(v,d);
const table = (headers, rows, cls='') => '<div class="scroll"><table class="'+cls+'"><thead><tr>'+headers.map(h=>'<th>'+E(h)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(c=>'<td>'+c+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';
const options = (items,selected) => items.map(([v,t])=>'<option value="'+E(v)+'"'+(v===selected?' selected':'')+'>'+E(t)+'</option>').join('');
const mode = p => /greedy/.test(p.opponent_display) ? '对手固定选最高分动作' : '双方按策略采样（T=1）';
function intervalPlot(mean,ci){
  const x = v=>20+220*v;
  return '<svg class="chart" viewBox="0 0 260 43" role="img" aria-label="半平得分'+E(pct(mean))+'，配对95%区间'+E(pct(ci[0]))+'至'+E(pct(ci[1]))+'"><line x1="20" y1="21" x2="240" y2="21" stroke="#dce5eb"/><line x1="130" y1="3" x2="130" y2="37" stroke="#acb7c6" stroke-dasharray="3 3"/><line x1="'+x(ci[0])+'" y1="21" x2="'+x(ci[1])+'" y2="21" stroke="#265dc5" stroke-width="4"/><circle cx="'+x(mean)+'" cy="21" r="5" fill="#265dc5"/><text x="20" y="42">0%</text><text x="120" y="42">50%</text><text x="216" y="42">100%</text></svg>';
}
document.getElementById('app').innerHTML = `
<header><div class="eyebrow">PRISM · ${E(S.round)} · 每轮研究报告</div><p class="foot"><a href="reports.html">← 查看其他轮报告</a></p><h1>${E(S.title)}</h1><p class="headline">${E(S.headline)}</p><p class="goal"><strong>这轮想解决什么？</strong> ${E(S.question)}</p></header>
<nav aria-label="报告导航"><a href="#overview">先看结论</a>${data.practical_review?'<a href="#coverage">实战覆盖面</a>':''}<a href="#strength">对战表现</a><a href="#style">${data.practical_review?'实际画像与路线':'风格有没有变'}</a><a href="#details">查具体对局</a><a href="#gates">${data.practical_review?'旧研究检验':'为什么这样判'}</a><a href="#evidence">来源与原文</a></nav>
<div class="conclusions" id="overview">${S.conclusions.map(c=>`<article class="card ${E(c.tone)}"><small>${E(c.label)}</small><b>${E(c.value)}</b><p>${E(c.explanation)}</p></article>`).join('')}</div>
<section><h2>这几个模型是什么关系？</h2><p>${E(S.identity)}</p><div class="lineage">${S.lineage.map((c,i)=>`<div><small>${E(c.role)}</small><strong>${E(c.name)}</strong><span>${E(c.change)}</span></div>`).join('<span aria-hidden="true">／</span>')}</div><p class="foot">后两项是从共同起点分出的两条训练分支，不是按顺序继续训练。候选身份、正式接受与实际发布是三个不同记录。</p></section>
${data.practical_review?'<section id="coverage"><h2>实战提升是否只针对父代？</h2><div id="coverage-body"></div></section>':''}
<section id="strength"><h2>对战表现：打得过谁？</h2><p>${E(S.strength)}</p><div class="controls"><label class="control-wide">查看被测模型<select id="strength-model"></select></label></div><div id="strength-body"></div><div class="explain"><strong>怎么读这张图：</strong>圆点是半平得分率（胜=1、平=0.5、负=0），横线是配对95%区间。50%虚线只是直接对战的描述参照；区间跨过50%时，不能据此确认谁更强，也不能说已经证明一样强。正式验收仍看原先冻结的门，不用这张图改判。</div></section>
<section id="style"><h2>${data.practical_review?'实际画像：适合归到哪条路线？':'风格有没有向目标靠近？'}</h2><p>${E(S.style)}</p><p class="muted">只比较相同种子、相同三个对手、相同动作模式的独立共同锚点。下面每项属于模型本人，先看对照和候选的绝对值，再看差值。</p><div id="style-body"></div><div class="why">${E(S.interpretation)}</div></section>
<section><h2>这一轮支持什么决定？</h2><p class="next">${E(S.next)}</p><p class="foot">这是建议，不表示已启动下一轮训练或更改本轮验收。</p><div id="timing"></div></section>
<section id="details"><h2>查具体对局：一次只看一组双方</h2><p class="muted">选择阶段、被测模型和对手。表里始终明确写“模型本人”与“对手本人”；先后手另列，不把物理P0误当候选。</p><div class="controls"><label>数据阶段<select id="detail-stage"><option value="acceptance">独立验收</option><option value="development">开发评测（仅描述）</option></select></label><label class="control-wide">被测模型<select id="detail-model"></select></label><label class="control-wide">对手<select id="detail-opponent"></select></label></div><div id="detail-body"></div></section>
<section id="gates"><h2>${data.practical_review?'历史记录：原基建研究目标有没有实现？':'为什么这样判？逐项展开解释'}</h2><p>${E(S.gate_intro)}</p>${data.practical_review?'<details id="historical-research"><summary>展开旧研究合同的十项记录（不是当前模型整体晋级结论）</summary><div class="inside">':''}<div class="controls"><label>显示<select id="gate-filter"><option value="failed">先看原门未达项</option><option value="all">全部原研究门</option></select></label></div><div id="gate-body"></div><details><summary>“区间”“校正下界”和“容忍线”是什么意思？</summary><div class="inside"><p>点估计是这批比赛观察到的平均值。95%区间说明有限种子带来的不确定性。原研究合同同时检查多个要求，因此使用该合同规定的、更保守的校正下界。</p><p>比如得分率估计46.88%，并不自动满足原“至少45%”保留门：若下界只有42.77%，仍没有足够证据排除低于45%。未达不表示真实水平等于下界。风格门检验原先指定的训练假设，不自动决定候选可否归到其他路线。</p><p>所有原阈值、区间和判定保持；实战优先的当前路线评审单独记录，不把旧风格检验改成PASS。两侧/单侧和校正配置见原证据。</p></div></details>${data.practical_review?'</div></details>':''}</section>
<section id="evidence"><h2>来源与完整原文</h2><p class="muted">日常判断看到上面即可；需要追溯时再打开这里。</p><details><summary>完整报告、原判定、权重身份和时钟</summary><div class="inside" id="evidence-body"></div></details></section><footer class="foot">离线阅读版 · prism-reading-report-v1 · 仅重组已保存的证据，不执行对战或训练。颜色与箭头表示数值方向，结论以文字和原合同为准。</footer>`;

function models(stage){return [...new Set((R[stage]?.pairs||[]).map(p=>p.candidate))];}
const sm = document.getElementById('strength-model');
if(data.practical_review){
 const review=data.practical_review;
 const pair=(model,opponent)=>R.acceptance.pairs.find(p=>p.candidate===model&&p.opponent===opponent);
 const rows=R.acceptance_policy.anchors.map(opponent=>{
  const base=pair(review.parent_key,opponent).candidate_metrics.score_rate;
  const candidate=pair(data.focus,opponent).candidate_metrics.score_rate;
  const control=pair(data.baseline,opponent).candidate_metrics.score_rate;
  return [E(name(opponent)),pct(base),pct(candidate),`<span class="${candidate>base?'up':'down'}">${signed(100*(candidate-base),2)}个百分点</span>`,`${signed(100*(candidate-control),2)}个百分点`];
 });
 document.getElementById('coverage-body').innerHTML=`<p>${E(review.practical_conclusion)}</p>`+table(['相同独立锚点','父代半平得分','候选半平得分','候选 − 父代','候选 − 同轮对照'],rows)+`<p class="foot">${E(review.coverage_caveat)}</p><div class="explain"><strong>当前路线：${E(review.route_label)}</strong><p>${E(review.route_caveat)}</p><p class="foot">实战评审：${E(review.review_status_label)}。发布登记：尚未执行。原权重SHA <code>${E(review.weight_sha256)}</code>；研究归类不会生成新的模型权重。</p></div>`;
}
sm.innerHTML=options(models('acceptance').map(k=>[k,name(k)]),data.focus);
function strength(){
 const pairs=(R.acceptance?.pairs||[]).filter(p=>p.candidate===sm.value);
 const rows=pairs.map(p=>{
  const m=p.candidate_metrics,ci=p.score_uncertainty.ordinary_95_ci;
  return [`<strong>${E(name(p.opponent))}</strong><div class="ci">${E(mode(p))} · ${m.games}局 / ${p.score_uncertainty.seed_blocks}种子块</div>`,
   `<div class="focus-number">${pct(m.score_rate)}</div><div class="ci">[${pct(ci[0])}, ${pct(ci[1])}]</div>`,intervalPlot(m.score_rate,ci),
   `${num(m.win_rate_percent,2)}%<div class="ci">${m.wins}胜 / ${m.ties}平 / ${m.losses}负</div>`];
 });
 document.getElementById('strength-body').innerHTML=table(['对手 / 比赛口径','半平得分 / 95%区间','得分与不确定性','纯胜率 / 战绩'],rows,'strength-table');
 document.querySelectorAll('.strength-table td:nth-child(3)').forEach(e=>e.className='plot');
 document.querySelectorAll('.strength-table th:last-child,.strength-table td:last-child').forEach(e=>e.className='wins-col');
}
sm.addEventListener('change',strength);strength();
function getMetric(p,path){return path.split('.').reduce((v,k)=>v?.[k],p);}
function anchorMean(model,path){
 const pairs=(R.acceptance?.pairs||[]).filter(p=>p.candidate===model&&R.acceptance_policy.anchors.includes(p.opponent));
 if(pairs.length!==R.acceptance_policy.anchors.length) return null;
 const values=pairs.map(p=>getMetric(p,path));return values.every(v=>typeof v==='number')?values.reduce((a,b)=>a+b,0)/values.length:null;
}
const styleRows=data.style_metrics.map(meta=>{
 const a=anchorMean(data.baseline,meta.path),b=anchorMean(data.focus,meta.path),scale=meta.scale||1,delta=(b-a)*scale;
 const valid=typeof a==='number'&&typeof b==='number';
 return [`<strong>${E(meta.label)}</strong><div class="ci">${E(meta.meaning)}</div>`,valid?num(a*scale,meta.digits??3):'NOT_MEASURED',valid?num(b*scale,meta.digits??3):'NOT_MEASURED',
  valid?`<span class="${delta>0?'up':delta<0?'down':''}">${signed(delta,meta.digits??3)} ${E(meta.unit)}</span><div class="ci">${E(meta.interpretation)}</div>`:'NOT_MEASURED'];
});
document.getElementById('style-body').innerHTML=table(['关键指标 / 是什么',name(data.baseline),name(data.focus),'候选 − 对照 / 怎么理解'],styleRows);
const stages=['development','acceptance'].filter(s=>R[s]?.games);
const dispatch=stages.every(s=>typeof R[s].dispatch_wall_seconds==='number')?stages.reduce((a,s)=>a+R[s].dispatch_wall_seconds,0):NaN,games=stages.reduce((a,s)=>a+R[s].games,0);
document.getElementById('timing').innerHTML=`<details><summary>这轮跑了多久？${Number.isFinite(dispatch)?num(dispatch/60,1)+'分钟对战派发 / '+num(games/dispatch*60,1)+'局每分钟':'对战派发吞吐 NOT_MEASURED'}</summary><div class="inside"><p>${E(S.compute)}。对战派发共${games.toLocaleString()}局，${num(dispatch/60,2)}分钟，实测${num(games/dispatch*60,2)}局/分钟、1000局${num(dispatch/games*1000/60,2)}分钟；全评测含采集与统计${num(R.elapsed_wall_seconds/60,2)}分钟。两者时钟范围不同，缺失数据不从总耗时反推。</p><p>决策耗时与推理耗时：NOT_MEASURED。原资源记录RSS峰${num(R.resources?.memory_peak_bytes/1024**3,3)}GiB；资源统计范围见原文，缺失时不推算。运行负载和来源见完整原文。</p></div></details>`;

function detailGroup(title,headers,rows){return '<details><summary>'+E(title)+'</summary><div class="inside">'+table(headers,rows)+'</div></details>';}
function metricsRows(a,b){
 const list=[['终局分数','mean_prestige','VP/局'],['得分速度（本人Main动作）','vp_per_main_action','VP/Main'],['得分速度（本人决策）','vp_per_turn','VP/决策'],['得分速度（全局步数）','vp_per_ply','VP/全局步'],['永久折扣','mean_permanent_bonuses','个/局'],['贵族','mean_nobles','个/局'],['拿到贵族的局数比例','games_with_nobles_percent','%'],['预留获得','mean_reserves_acquired','张/局'],['预留买回','mean_reserves_bought','张/局'],['终局没买回的预留','mean_reserves_stranded','张/局'],['预留买回率（总买回/总获得）','reserve_redemption_rate_percent','%']];
 return list.map(([label,key,unit])=>[E(label),num(a[key])+' '+unit,num(b[key])+' '+unit]);
}
const ds=document.getElementById('detail-stage'),dm=document.getElementById('detail-model'),dop=document.getElementById('detail-opponent');
function modelChoices(){dm.innerHTML=options(models(ds.value).map(k=>[k,name(k)]),models(ds.value).includes(dm.value)?dm.value:data.focus);opponentChoices();}
function opponentChoices(){const pairs=(R[ds.value]?.pairs||[]).filter(p=>p.candidate===dm.value);dop.innerHTML=options(pairs.map(p=>[p.opponent,name(p.opponent)]),dop.value);details();}
function details(){
 const p=(R[ds.value]?.pairs||[]).find(p=>p.candidate===dm.value&&p.opponent===dop.value);
 if(!p){document.getElementById('detail-body').textContent='本阶段没有这组比赛。NOT_RUN';return;}
 const a=p.candidate_metrics,b=p.opponent_metrics,cols=['指标',name(p.candidate)+'（模型本人）',name(p.opponent)+'（对手本人）'];
 let out=`<div class="explain"><strong>${E(name(p.candidate))} 对 ${E(name(p.opponent))}</strong><p class="foot">${ds.value==='acceptance'?'独立验收':'开发评测，仅描述'} · ${E(mode(p))} · ${a.games}局 / ${p.score_uncertainty.seed_blocks}双座种子块。${E(p.candidate_display)}；${E(p.opponent_display)}。</p></div>`;
 out+=table(['比赛结果',cols[1],cols[2]],['games','wins','ties','losses','win_rate_percent','score_rate'].map((k,i)=>[[ '局数','胜','平','负','纯胜率','半平得分率'][i],k==='score_rate'?pct(a[k]):k==='win_rate_percent'?num(a[k],2)+'%':String(a[k]),k==='score_rate'?pct(b[k]):k==='win_rate_percent'?num(b[k],2)+'%':String(b[k])]));
 out+=`<p class="foot">模型本人配对95%区间：纯胜率 [${p.win_uncertainty.ordinary_95_ci.map(pct).join(', ')}]；半平得分 [${p.score_uncertainty.ordinary_95_ci.map(pct).join(', ')}]。对手半平区间是 [${pct(1-p.score_uncertainty.ordinary_95_ci[1])}, ${pct(1-p.score_uncertainty.ordinary_95_ci[0])}]；对手纯胜率区间未单独重算。</p>`;
 out+=detailGroup('① 双方经济：分数、得分速度、折扣、贵族、预留',cols,metricsRows(a,b));
 const cards=[];for(let vp=0;vp<=5;vp++)cards.push([vp+' VP牌 / 局',num(a.mean_cards_by_vp[vp]),num(b.mean_cards_by_vp[vp])]);
 for(const [key,label] of Object.entries({White:'白',Blue:'蓝',Green:'绿',Red:'红',Black:'黑'}))cards.push([label+'色永久折扣 / 局',num(a.mean_bonuses_by_color[key]),num(b.mean_bonuses_by_color[key])]);
 out+=detailGroup('② 买了哪些牌？六种VP牌与五色折扣',cols,cards);
 const labels={buy_market:'买公开牌',buy_reserved:'买回预留牌',take_tokens:'拿宝石',reserve_market:'预留公开牌',reserve_deck:'盲预留牌',choose_noble:'选择贵族',pass:'跳过'};
 out+=detailGroup('③ 七类动作：总次数 / 本人全部决策占比',cols,Object.entries(labels).map(([k,v])=>[E(v),a.action_distribution[k]+'次 / '+num(a.action_percentages[k],2)+'%',b.action_distribution[k]+'次 / '+num(b.action_percentages[k],2)+'%']));
 out+=detailGroup('④ 先后手：按模型身份归属', ['候选的物理座位','局数','候选胜/平/负','候选纯胜率 / 半平得分','双方终局VP'],p.seats.map(s=>[s.candidate_seat===0?'先手（P0）':'后手（P1）',String(s.candidate.games),`${s.candidate.wins} / ${s.candidate.ties} / ${s.candidate.losses}`,`${num(s.candidate.win_rate_percent,2)}% / ${pct(s.candidate.score_rate)}`,`${num(s.candidate.mean_prestige)} / ${num(s.opponent.mean_prestige)}`]));
 const ma=p.macro;
 out+=detailGroup('⑤ 对局长度与计时：属于整局，不属于某一模型',['全局指标','值 / 范围'],[['平均全局步数',num(ma.mean_plies)+'步'],['平均本人轮数（旧口径）',num(ma.mean_turns)+'轮'],['局长 最小 / 中位 / 最大 / 标准差',`${num(ma.min_turns,0)} / ${num(ma.median_turns)} / ${num(ma.max_turns,0)} / ${num(ma.std_turns)}轮`],['平均绝对分差',num(ma.mean_victory_margin)+' VP'],['分差≤2的对局',num(ma.close_games_margin_le_2_percent,2)+'%'],['逐局进程墙钟 平均 / P95',num(ma.process_wall_seconds_mean)+' / '+num(ma.process_wall_seconds_p95)+'秒'],['决策 / 推理延迟','NOT_MEASURED / NOT_MEASURED']] );
 if(p.candidate_building){
  const labels={mean_building_utility:'旧基建效用（0..1）',mean_timed_building_utility:'时间加权基建效用（0..1）',mean_early_bonus_auc12:'前12个Main平均折扣（个）',mean_early_lowvp_buys:'早期低分投资牌（张/局）',mean_redeemed_investments:'兑现过的投资牌（张/局）',mean_unredeemed_investments:'未兑现投资牌（张/局）',investment_redemption_rate:'投资兑现比例（0..1）',mean_late_scoring_vp_main25to32:'Main25..32真实买牌分（VP/局，包含早结束局）'};
  out+=detailGroup('⑥ 基建画像：双方投资与后续兑现',cols,Object.entries(labels).filter(([k])=>k in p.candidate_building).map(([k,v])=>[E(v),num(p.candidate_building[k]),num(p.opponent_building[k])]));
 }
 if(p.candidate_bigcard){const aa=p.candidate_bigcard,bb=p.opponent_bigcard;
  const rows=[['大牌印刷分AUC24（0..1）',num(aa.mean_large_card_vp_auc24),num(bb.mean_large_card_vp_auc24)],['终局大牌印刷分（VP/局）',num(aa.mean_terminal_large_card_printed_vp),num(bb.mean_terminal_large_card_printed_vp)],['前24Main大牌购入（张/局）',num(aa.mean_large_card_buys_within24),num(bb.mean_large_card_buys_within24)]];
  for(const [i,c] of (aa.score_checkpoints||[]).entries())rows.push([`Main${c.own_main}分数 / 大牌印刷分（VP/局）`,`${num(c.mean_vp)} / ${num(c.mean_large_card_printed_vp)}`,`${num(bb.score_checkpoints[i].mean_vp)} / ${num(bb.score_checkpoints[i].mean_large_card_printed_vp)}`]);
  out+=detailGroup('⑦ 大牌与冲分画像：贵族分不算大牌印刷分',cols,rows);
 }
 out+='<p class="foot">完整风格轨迹、删失条件、来源及所有原表见证据原文；本页精简视图不删改原始表。所选阶段的种子区间和动作种子见来源。</p>';
 document.getElementById('detail-body').innerHTML=out;
}
ds.addEventListener('change',modelChoices);dm.addEventListener('change',opponentChoices);dop.addEventListener('change',details);modelChoices();

function gates(){
 const all=document.getElementById('gate-filter').value==='all';
 const keys=Object.keys(data.gates).filter(k=>all||!R.gates[k]);
 document.getElementById('gate-body').innerHTML=keys.length?keys.map(key=>{
  const meta=data.gates[key],m=R.measurements[key],pass=R.gates[key];
  const lower=m.simultaneous_one_sided_lower??m.simultaneous_lower;
  const format=v=>num(v*(meta.scale||1),meta.digits??3)+' '+meta.unit;
  const why=pass?meta.pass:meta.fail;
  return `<details><summary><span class="badge ${pass?'good':'warn'}">${data.practical_review?(pass?'原门达到':'原门未达'):(pass?'通过':'未通过')}</span> ${E(meta.label)} <span class="muted">· ${E(meta.category)}</span></summary><div class="inside"><p><strong>为什么设这项？</strong> ${E(meta.purpose)}</p><div class="gate-info"><div><small>这批比赛的估计</small><b>${E(format(m.mean))}</b><small>95%区间 [${E(format(m.ci95[0]))}, ${E(format(m.ci95[1]))}]</small></div><div><small>原合同校正下界</small><b>${E(format(lower))}</b></div><div><small>原先冻结的要求</small><b>下界 ≥ ${E(format(meta.threshold))}</b></div></div><div class="why"><strong>${pass?'原门达到意味着':'原门未达意味着'}：</strong>${E(why)}</div><p class="foot">历史研究记录：<code>${E(key)}</code> / ${pass?'PASS':'FAIL'} · 配对种子块${m.seed_blocks} · 原统计配置在证据记录中。${data.practical_review?'该记录不作为当前实战优先晋级的一票否决。':''}</p></div></details>`;
 }).join(''):'<p>本轮原门没有未通过项。展开“全部原验收门”可查验。</p>';
}
document.getElementById('gate-filter').addEventListener('change',gates);gates();
const src=data.sources;
document.getElementById('evidence-body').innerHTML=`<p><a href="${E(src.markdown)}">完整原Markdown（所有双方指标与原始判定）</a> · <a href="${E(src.markdown.replace(/\.md$/,'.reading.md'))}" id="reading-md-link">阅读版Markdown</a>${src.original_html?' · <a href="'+E(src.original_html)+'">冻结原HTML</a>':''}</p><p><a href="${E(src.result)}">机器结果JSON</a>（核验用途，不要求读者阅读JSON）</p><p>结果SHA256：<code>${E(src.result_sha256)}</code><br>原Markdown SHA256：<code>${E(src.markdown_sha256)}</code></p>`+table(['被测产物','固定权重SHA256'],Object.entries(R.candidate_sha256||{}).map(([k,v])=>[E(name(k)),`<code>${E(v)}</code>`]))+`<p class="foot">原结果状态：<code>${E(R.status)}</code>；原判定：<code>${E(JSON.stringify(R.verdicts||R.arm_verdicts))}</code>；A/B原判定：<code>${E(JSON.stringify(R.comparison||null))}</code>。</p><p class="foot">独立锚点种子：${E(R.acceptance_policy.seed_start)}..${E(R.acceptance_policy.seed_end)}；直接对战种子：${E(R.acceptance_policy.direct_seed_end ? R.acceptance_policy.seed_start+'..'+R.acceptance_policy.direct_seed_end : '见原文')}；action seed ${E(R.acceptance_policy.action_seed)}。原运行起止${E(R.started_at)} → ${E(R.finished_at)}（原时区）；资源负载${E(JSON.stringify(R.resources?.load_average))}。所有完整runtime/config/replay哈希清单见原Markdown。原回放位置不因阅读改版迁移。</p>`;
document.getElementById('reading-md-link').setAttribute('href',location.pathname.split('/').pop().replace(/\.html$/,'.md'));
