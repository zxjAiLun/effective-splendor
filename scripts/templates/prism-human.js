'use strict';
const data=JSON.parse(document.getElementById('report-data').textContent),R=data.result,S=data.story;
const E=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=(v,d=3)=>Number.isFinite(v)?v.toFixed(d):'未测';
const pct=v=>Number.isFinite(v)?num(v*100,2)+'%':'未测';
const name=k=>(data.names[k]||k).replace(/（(?:T=1|greedy)）/g,'');
const table=(heads,rows,cls='')=>'<div class="scroll"><table class="'+cls+'"><thead><tr>'+heads.map(h=>'<th>'+E(h)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(c=>'<td>'+c+'</td>').join('')+'</tr>').join('')+'</tbody></table></div>';
const options=(items,selected)=>items.map(([k,v])=>'<option value="'+E(k)+'"'+(k===selected?' selected':'')+'>'+E(v)+'</option>').join('');
const diff=(a,b,d=3,scale=1)=>Number.isFinite(a)&&Number.isFinite(b)?'<b class="delta">'+(b>a?'↑ +':b<a?'↓ ':'→ ')+num((b-a)*scale,d)+'</b>':'未测';
// Practical advantage is green; descriptive magnitude is blue. Display ties stay plain.
function compare(a,b,format=v=>num(v),direction='more'){
 const values=[a,b],rendered=values.map(format),valid=values.every(Number.isFinite);
 const winner=valid&&a!==b&&rendered[0]!==rendered[1]?(direction==='low'?(a<b?0:1):(a>b?0:1)):-1;
 return values.map((v,i)=>i!==winner?'<span class="metric-value">'+E(rendered[i])+'</span>':'<strong class="metric-win '+(direction==='more'?'higher':'better')+'" data-value="'+v+'" data-direction="'+direction+'" title="'+(direction==='low'?'数值更低':direction==='more'?'数量较多':'数值更高')+'">'+E(rendered[i])+'<small aria-hidden="true">'+(direction==='low'?'↓':'↑')+'</small></strong>');
}
const stages=Object.keys(R).filter(k=>R[k]?.pairs),pairs=k=>R[k]?.pairs||[];
const models=k=>[...new Set(pairs(k).map(p=>p.candidate))];
const stageName=k=>R[k].label||k,history=data.view==='history';
document.getElementById('app').innerHTML=`<header><div class="eyebrow">PRISM · ${E(S.round)} · ${history?'历史采样复盘':'GREEDY 对战报告'}</div><p class="foot"><a href="reports.html">← 其他轮次</a></p><h1>${E(S.title)}</h1><p class="headline">${E(history?data.history_headline:S.headline)}</p><p>${E(S.identity)}</p><p class="mode-note">${history?'此页是历史采样数据，候选使用 T=1；对手 greedy 不代表双方 greedy。':'本页只展示双方 greedy 的比赛。对比版本默认是训练父代；候选是同一份最终权重，尚未发布新版本。'}</p></header>
<nav><a href="#overview">结论</a><a href="#strength">同对手跨代比较</a><a href="#style">实际画像</a><a href="#details">双方详细数据</a></nav>
<div id="overview" class="conclusions">${S.conclusions.map(c=>`<article class="card ${E(c.tone)}"><small>${E(c.label)}</small><b>${E(c.value)}</b><p>${E(c.explanation)}</p></article>`).join('')}</div>
<section id="strength"><h2>对战表现：当代与上一代，打同一个对手</h2><p>每行一个对手，两代并列。绿底粗体标出本批占优数值。</p><div class="controls"><label>评测批次<select id="strength-stage"></select></label><label class="control-wide">对比版本<select id="strength-baseline"></select></label></div><div id="strength-body"></div></section>
<section id="style"><h2>实际画像：适合归到哪条路线？</h2><p>先看得分效率、贵族覆盖，再看买牌倾向。效率提高不能单独认定更偏基建。</p><div id="style-body"></div><div class="why">${E(S.interpretation)}</div></section>
<section id="details"><h2>查具体对局：一次只看一组双方</h2><p class="legend"><span class="metric-win better">✓ 更高 / 更低</span> 明确方向的结果与效率　<span class="metric-win higher">↑ 较多</span> 买牌、折扣、动作的数值方向</p><div class="controls"><label>评测批次<select id="detail-stage"></select></label><label class="control-wide">被测模型<select id="detail-model"></select></label><label class="control-wide">对手<select id="detail-opponent"></select></label></div><div id="detail-body"></div></section>
<section><h2>接下来</h2><p>${E(S.next)}</p><div id="timing"></div></section><footer class="foot"><a href="${E(data.links.main)}">greedy 主报告</a>${data.links.history?' · <a href="'+E(data.links.history)+'">历史采样页</a>':''} · <a href="${E(data.links.audit)}">Agent 审计页</a> · <a href="${E(data.links.markdown)}">本页 Markdown 数据表</a>${(data.links.related||[]).map(r=>' · <a href="'+E(r.href)+'">'+E(r.label)+'</a>').join('')}</footer>`;
const ss=document.getElementById('strength-stage'),sb=document.getElementById('strength-baseline'),ds=document.getElementById('detail-stage'),dm=document.getElementById('detail-model'),dop=document.getElementById('detail-opponent');
ss.innerHTML=ds.innerHTML=options(stages.map(k=>[k,stageName(k)]),stages[0]);
function updateBaseline(){const base=data.comparison_baseline||data.baseline;sb.innerHTML=options([...new Set([base,...models(ss.value).filter(k=>k!==data.focus)])].map(k=>[k,name(k)]),base);strength();style();}
function strength(){
 const stage=pairs(ss.value),focus=stage.filter(p=>p.candidate===data.focus),baseline=stage.filter(p=>p.candidate===sb.value),opponents=[...new Set([...focus,...baseline].map(p=>p.opponent))];
 if(!opponents.length){document.getElementById('strength-body').innerHTML='<p class="empty">没有双方 greedy 的已完成数据。历史采样在独立页面。</p>';return;}
 const rows=opponents.map(o=>{
  const a=baseline.find(p=>p.opponent===o),b=focus.find(p=>p.opponent===o),am=a?.candidate_metrics,bm=b?.candidate_metrics,scores=compare(am?.score_rate,bm?.score_rate,pct,'high');
  const wins=compare(am?.win_rate_percent,bm?.win_rate_percent,v=>num(v,2)+'%','high');
  const cell=(p,score,i)=>p?'<div class="match-rate"><span class="match-label">半平</span>'+score+'</div><div class="match-win"><span class="match-label">纯胜</span>'+wins[i]+'</div><div class="match-record">'+p.candidate_metrics.wins+'胜 · '+p.candidate_metrics.ties+'平 · '+p.candidate_metrics.losses+'负</div><div class="match-interval">得分区间 '+p.score_uncertainty.ordinary_95_ci.map(pct).join(' – ')+'</div><div class="match-games">'+p.candidate_metrics.games+'局 · '+p.score_uncertainty.seed_blocks+'种子块</div>':'<span class="unavailable">未测</span>';
  const delta=Number.isFinite(am?.score_rate)&&Number.isFinite(bm?.score_rate)?diff(am.score_rate,bm.score_rate,2,100)+'<span class="delta-unit"> 个百分点</span>':'<span class="unavailable">—</span>';
  return [E(name(o)),cell(a,scores[0],0),cell(b,scores[1],1),delta];
 });
 document.getElementById('strength-body').innerHTML=table(['对手',name(sb.value)+' · 半平得分',name(data.focus)+' · 半平得分','当代变化'],rows,'strength-table')+'<p class="foot">半平得分 =（胜局 + 0.5 × 平局）÷ 总局数。缺少同对手记录时显示未测。</p>';
}
function pooled(model){
 const common=pairs(ss.value).filter(p=>p.candidate===model&&pairs(ss.value).some(q=>q.candidate===data.focus&&q.opponent===p.opponent)&&pairs(ss.value).some(q=>q.candidate===sb.value&&q.opponent===p.opponent));
 if(!common.length)return null;
 const games=common.reduce((s,p)=>s+p.candidate_metrics.games,0),sum=k=>common.reduce((s,p)=>s+p.candidate_metrics[k]*p.candidate_metrics.games,0),cards=Array.from({length:6},(_,vp)=>common.reduce((s,p)=>s+p.candidate_metrics.mean_cards_by_vp[vp]*p.candidate_metrics.games,0)),total=cards.reduce((s,n)=>s+n,0);
 const result={efficiency:sum('mean_prestige')/common.reduce((s,p)=>s+p.candidate_metrics.total_main_actions,0),nobles:sum('mean_nobles')/games,coverage:common.reduce((s,p)=>s+p.candidate_metrics.games_with_nobles,0)/games,lowCards:(cards[0]+cards[1])/games,lowShare:(cards[0]+cards[1])/total,largeCards:(cards[3]+cards[4]+cards[5])/games,largeVP:(cards[3]*3+cards[4]*4+cards[5]*5)/games,nobleVP:3*sum('mean_nobles')/games,opponents:common.length,games};
 if(common.every(p=>p.candidate_trajectory)){
  result.vp8=common.reduce((s,p)=>s+p.candidate_trajectory.vp8_by_main20_rate*p.candidate_metrics.games,0)/games;
  const cover=common.reduce((s,p)=>s+p.candidate_trajectory.first_4plus_card_main.coverage_games,0);
  result.first4=cover?common.reduce((s,p)=>s+(p.candidate_trajectory.first_4plus_card_main.conditional_mean??0)*p.candidate_trajectory.first_4plus_card_main.coverage_games,0)/cover:NaN;
  result.coverage4=cover/games;
 }
 return result;
}
function style(){
 const a=pooled(sb.value),b=pooled(data.focus);
 if(!a||!b){document.getElementById('style-body').innerHTML='<p class="empty">同种子 greedy 画像尚未测完。路线暂定。</p>';return;}
 const metrics=[['得分效率','efficiency','VP / 本人Main','high',4],['贵族覆盖率','coverage','%','high',2],['每局获得贵族','nobles','个 / 局','high',3],['0–1 VP牌购买量','lowCards','张 / 局','more',3],['0–1 VP牌占全部购牌','lowShare','%','more',2],['3–5 VP牌购买量','largeCards','张 / 局','more',3],['3–5 VP牌贡献印刷分','largeVP','VP / 局','more',3],['贵族贡献分数','nobleVP','VP / 局','more',3]];
 if('vp8' in a&&'vp8' in b)metrics.push(['20Main内达到8分的对局比例','vp8','%','high',2],['首张4–5 VP牌购买时点（条件均值）','first4','本人Main','low',3],['购到4–5 VP牌的局数比例','coverage4','%','more',2]);
 document.getElementById('style-body').innerHTML='<p class="foot">同一批 '+a.opponents+' 个共同对手，每代 '+a.games+' 局。指标属于模型本人，按总计数计算比例。</p>'+table(['画像指标',name(sb.value),name(data.focus),'当代变化 / 单位'],metrics.map(([label,k,unit,direction,d])=>[E(label),...compare(a[k],b[k],unit==='%'?pct:v=>num(v,d),direction),diff(a[k],b[k],d,unit==='%'?100:1)+' '+E(unit==='%'?'个百分点':unit)]))+'<p class="foot">Alpha 看大牌购入和冲分；Beta 看相对 Balance 的低分牌购买倾向、贵族覆盖与得分效率；Balance 可保留混合倾向。折扣利用率不是流派判定器。</p>'+('first4' in a?'<p class="foot">首张4–5分牌时点 = 实际买到这类牌的对局中，首张购买发生在本人第几个Main的平均数；覆盖率 = 买到这类牌的局数 ÷ 全部局数。</p>':'');
}
const detailGroup=(title,headers,rows,open=false)=>'<details'+(open?' open':'')+'><summary>'+E(title)+'</summary><div class="inside">'+table(headers,rows)+'</div></details>';
function modelChoices(){dm.innerHTML=options(models(ds.value).map(k=>[k,name(k)]),data.focus);opponentChoices();}
function opponentChoices(){dop.innerHTML=options(pairs(ds.value).filter(p=>p.candidate===dm.value).map(p=>[p.opponent,name(p.opponent)]),dop.value);details();}
function details(){
 const p=pairs(ds.value).find(p=>p.candidate===dm.value&&p.opponent===dop.value),body=document.getElementById('detail-body');if(!p){body.innerHTML='<p class="empty">本批次未测。</p>';return;}
 const a=p.candidate_metrics,b=p.opponent_metrics,cols=['指标',name(p.candidate)+' · 模型本人',name(p.opponent)+' · 对手本人'],row=(label,x,y,fmt=v=>num(v),direction='more')=>[E(label),...compare(x,y,fmt,direction)];
 let out='<p class="mode-note">'+E(stageName(ds.value))+' · '+(p.candidate_mode==='greedy'&&p.opponent_mode==='greedy'?'双方 greedy':'历史：候选 T=1；对手 '+E(p.opponent_mode))+' · '+a.games+' 局 / '+p.score_uncertainty.seed_blocks+' 双座种子块</p>';
 out+=table(cols,[row('局数',a.games,b.games,String),row('胜局',a.wins,b.wins,String,'high'),row('平局',a.ties,b.ties,String),row('负局',a.losses,b.losses,String,'low'),row('纯胜率',a.win_rate_percent,b.win_rate_percent,v=>num(v,2)+'%','high'),row('半平得分',a.score_rate,b.score_rate,pct,'high')]);
 out+='<p class="foot">模型本人：纯胜率区间 '+p.win_uncertainty.ordinary_95_ci.map(pct).join(' ～ ')+'；半平得分区间 '+p.score_uncertainty.ordinary_95_ci.map(pct).join(' ～ ')+'。</p>';
 const econ=[['最终分数','mean_prestige','VP / 局','high'],['得分效率','vp_per_main_action','VP / 本人Main','high'],['每次决策得分','vp_per_turn','VP / 本人决策','high'],['按整局步数得分','vp_per_ply','VP / 全局步','high'],['贵族覆盖率','games_with_nobles_percent','%','high'],['获得贵族','mean_nobles','个 / 局','high'],['永久折扣','mean_permanent_bonuses','个 / 局','more'],['预留获得','mean_reserves_acquired','张 / 局','more'],['预留买回','mean_reserves_bought','张 / 局','more'],['终局未买回预留','mean_reserves_stranded','张 / 局','low'],['预留买回率','reserve_redemption_rate_percent','%','high']];
 out+=detailGroup('① 得分效率、贵族与预留',cols,econ.map(([label,k,unit,direction])=>row(label+'（'+unit+'）',a[k],b[k],v=>num(v,unit==='%'?2:4),direction)),true);
 const cards=[];for(let vp=0;vp<=5;vp++)cards.push(row(vp+' VP牌（张 / 局）',a.mean_cards_by_vp[vp],b.mean_cards_by_vp[vp]));for(const [k,v] of Object.entries({White:'白',Blue:'蓝',Green:'绿',Red:'红',Black:'黑'}))cards.push(row(v+'色折扣（个 / 局）',a.mean_bonuses_by_color[k],b.mean_bonuses_by_color[k]));
 out+=detailGroup('② 买牌倾向：0–5 VP逐项与五色折扣',cols,cards);
 const actions={buy_market:'买公开牌',buy_reserved:'买回预留',take_tokens:'拿宝石',reserve_market:'预留公开牌',reserve_deck:'盲预留',choose_noble:'选择贵族',pass:'跳过'};
 out+=detailGroup('③ 七类动作：次数与本人决策占比',cols,Object.entries(actions).map(([k,label])=>{const c=compare(a.action_distribution[k],b.action_distribution[k],v=>v+'次'),p=compare(a.action_percentages[k],b.action_percentages[k],v=>num(v,2)+'%');return [E(label),c[0]+' / '+p[0],c[1]+' / '+p[1]];}));
 out+=detailGroup('④ 先后手：双方分数按模型身份归属',['模型的物理座位','局数','模型胜 / 平 / 负','模型纯胜 / 半平','模型VP / 局','对手VP / 局'],p.seats.map(s=>[s.candidate_seat===0?'先手':'后手',String(s.candidate.games),s.candidate.wins+' / '+s.candidate.ties+' / '+s.candidate.losses,num(s.candidate.win_rate_percent,2)+'% / '+pct(s.candidate.score_rate),...compare(s.candidate.mean_prestige,s.opponent.mean_prestige,v=>num(v),'high')]));
 const m=p.macro;out+=detailGroup('⑤ 对局长度：两人共同的整局指标',['整局指标','实测值'],[['平均全局步数',num(m.mean_plies)],['轮数：最小 / 中位 / 最大',num(m.min_turns,0)+' / '+num(m.median_turns,1)+' / '+num(m.max_turns,0)],['轮数：平均 / 标准差',num(m.mean_turns)+' / '+num(m.std_turns)],['终局绝对分差（VP）',num(m.mean_victory_margin)],['分差≤2的对局',num(m.close_games_margin_le_2_percent,2)+'%'],['单局进程墙钟：平均 / P95（秒）',num(m.process_wall_seconds_mean)+' / '+num(m.process_wall_seconds_p95)],['决策 / 推理耗时','NOT_MEASURED / NOT_MEASURED']]);
 const scoring=x=>[0,1,2,3,4,5].reduce((s,v)=>s+v*x.mean_cards_by_vp[v],0),large=x=>[3,4,5].reduce((s,v)=>s+v*x.mean_cards_by_vp[v],0);
 out+=detailGroup('⑥ 分从哪里来？买牌与贵族分分开',cols,[row('全部购牌印刷分（VP / 局）',scoring(a),scoring(b)),row('其中3–5 VP牌的印刷分（VP / 局）',large(a),large(b)),row('3–5 VP牌占购牌印刷分',large(a)/scoring(a),large(b)/scoring(b),pct),row('贵族分 = 3 × 贵族数（VP / 局）',3*a.mean_nobles,3*b.mean_nobles),row('最终总分（VP / 局）',a.mean_prestige,b.mean_prestige,v=>num(v),'high')]);
 if(p.candidate_trajectory){const ca=p.candidate_trajectory,ob=p.opponent_trajectory;
  out+=detailGroup('⑦ 实战节奏：第20个Main前达到8分、首张4–5分牌',cols,[row('20Main内达到8分的对局比例',ca.vp8_by_main20_rate,ob.vp8_by_main20_rate,pct,'high'),row('首张4–5 VP牌购买时点（本人Main，条件均值）',ca.first_4plus_card_main.conditional_mean,ob.first_4plus_card_main.conditional_mean,v=>num(v),'low'),row('购到4–5 VP牌的局数比例',ca.first_4plus_card_main.coverage_rate,ob.first_4plus_card_main.coverage_rate,pct)]);
  out+='<p class="foot">首张4–5 VP牌时点只对实际买到该类牌的对局计算，覆盖率另列；20Main内达到8分比例 = 达到该分数的局数 ÷ 全部局数。</p>';
 }
 out+='<p class="foot">得分效率 = 累计终局VP ÷ 本人Main总数；贵族覆盖率 = 拿到至少一个贵族的局数 ÷ 总局数；预留买回率 = 总买回数 ÷ 总获得数。购牌印刷分 = Σ（牌的VP × 购入张数），不含贵族分。</p>';body.innerHTML=out;
}
ss.addEventListener('change',updateBaseline);sb.addEventListener('change',()=>{strength();style();});ds.addEventListener('change',modelChoices);dm.addEventListener('change',opponentChoices);dop.addEventListener('change',details);updateBaseline();modelChoices();
const t=data.timing;document.getElementById('timing').innerHTML=t?'<p class="foot">实测 '+t.workers+' 路并行 · '+num(t.games_per_minute,1)+' 局 / 分钟 · 1000局 '+num(t.minutes_per_1000,2)+' 分钟。时钟：'+E(t.clock_scope)+'。决策 / 推理耗时：NOT_MEASURED。</p>':'';
