// Offline DOM transformation checks, without browser control or network.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {createRequire}=require('node:module'),root=path.resolve(__dirname,'../..');
const {JSDOM,VirtualConsole}=createRequire(path.join(root,'local-artifacts/prism/report-ui-test/package.json'))('jsdom');
const files=['m63-prism-beta-timed-building-evaluation','m62-prism-beta-building-comparison','m61-prism-alpha-balance-ab-comparison','m65-prism-version-release-comparison'];
let groups=0,greedy=0;
for(const file of files)for(const suffix of ['', '.sampling']){
 const source=fs.readFileSync(path.join(root,'docs/prism',file+suffix+'.html'),'utf8'),errors=[],vc=new VirtualConsole();vc.on('jsdomError',e=>errors.push(String(e)));
 const dom=new JSDOM(source,{runScripts:'dangerously',virtualConsole:vc}),d=dom.window.document,data=JSON.parse(d.getElementById('report-data').textContent);
 const select=(id,v)=>{const e=d.getElementById(id);e.value=v;e.dispatchEvent(new dom.window.Event('change'));};
 assert.equal(data.schema,'prism-human-report-v2');
 assert.equal(d.querySelectorAll('.card').length,3);
 assert.equal(d.querySelector('#gates'),null);assert.equal(d.querySelector('#evidence'),null);
 assert.ok(!/SHA256|FAIL_BUILDING|校正下界|容忍线|点估计是这批/.test(d.getElementById('app').textContent),file+suffix+' '+d.getElementById('app').textContent.match(/.{0,30}(SHA256|FAIL_BUILDING|校正下界|容忍线|点估计是这批).{0,30}/));
 assert.ok(!/[a-f0-9]{64}/.test(source),'human file contains an audit hash');
 assert.equal(data.view,suffix?'history':'greedy');
 for(const a of d.querySelectorAll('footer a'))assert.ok(fs.existsSync(path.join(root,'docs/prism',a.getAttribute('href'))),'missing footer link '+a.getAttribute('href'));
 const tie=dom.window.compare(1.00001,1.00002,v=>v.toFixed(3));assert.ok(tie.every(v=>!v.includes('metric-win')));
 const lower=dom.window.compare(1,2,String,'low');assert.ok(lower[0].includes('metric-win better'));assert.ok(!lower[1].includes('metric-win'));
 const more=dom.window.compare(2,1,String,'more');assert.ok(more[0].includes('metric-win higher'));
 for(const [stage,record] of Object.entries(data.result)){
  select('detail-stage',stage);
  for(const p of record.pairs){
   groups++;if(!suffix){greedy++;assert.equal(p.candidate_mode,'greedy');assert.equal(p.opponent_mode,'greedy');}
   select('detail-model',p.candidate);select('detail-opponent',p.opponent);
   const t=d.querySelector('#detail-body table'),a=p.candidate_metrics,b=p.opponent_metrics;
   for(const [i,key] of ['games','wins','ties','losses'].entries()){
    const row=t.rows[i+1];assert.equal(row.cells[1].querySelector('strong,span').firstChild.textContent,String(a[key]));assert.equal(row.cells[2].querySelector('strong,span').firstChild.textContent,String(b[key]));
    if(a[key]!==b[key]){const winner=key==='losses'?(a[key]<b[key]?1:2):(a[key]>b[key]?1:2);assert.ok(row.cells[winner].querySelector('strong.metric-win'));}
   }
   assert.equal(t.rows[5].cells[1].querySelector('strong,span').firstChild.textContent,a.win_rate_percent.toFixed(2)+'%');
   assert.equal(t.rows[6].cells[1].querySelector('strong,span').firstChild.textContent,(a.score_rate*100).toFixed(2)+'%');
   assert.equal(d.querySelectorAll('#detail-body details').length,p.candidate_trajectory?7:6);
   if(p.candidate_trajectory){
    const rush=d.querySelectorAll('#detail-body details')[6].querySelector('table');
    assert.equal(rush.rows[1].cells[1].querySelector('strong,span').firstChild.textContent,(p.candidate_trajectory.vp8_by_main20_rate*100).toFixed(2)+'%');
    assert.equal(rush.rows[3].cells[2].querySelector('strong,span').firstChild.textContent,(p.opponent_trajectory.first_4plus_card_main.coverage_rate*100).toFixed(2)+'%');
    assert.ok(d.getElementById('detail-body').textContent.includes('只对实际买到该类牌的对局计算'));
   }
   const action=d.querySelectorAll('#detail-body details')[2].querySelector('table');assert.equal(action.rows.length,8);
   assert.ok(d.getElementById('detail-body').textContent.includes('NOT_MEASURED / NOT_MEASURED'));
  }
  select('strength-stage',stage);
  const base=data.comparison_baseline||data.baseline,focus=data.focus;
  select('strength-baseline',base);
  const expected=[...new Set(record.pairs.filter(p=>[base,focus].includes(p.candidate)).map(p=>p.opponent))];
  const rows=d.querySelectorAll('#strength-body tbody tr');assert.equal(rows.length,expected.length);
  for(const o of expected){
   const label=(data.names[o]||o).replace(/（(?:T=1|greedy)）/g,'');const row=[...rows].find(r=>r.cells[0].textContent===label);assert.ok(row);
   const a=record.pairs.find(p=>p.candidate===base&&p.opponent===o),b=record.pairs.find(p=>p.candidate===focus&&p.opponent===o);
   assert.ok(row.cells[1].textContent.includes(a?(a.candidate_metrics.score_rate*100).toFixed(2)+'%':'未测'));
   assert.ok(row.cells[2].textContent.includes(b?(b.candidate_metrics.score_rate*100).toFixed(2)+'%':'未测'));
   for(const [i,p] of [[1,a],[2,b]])if(p){
    assert.equal(row.cells[i].children.length,5,'match figures must use the same five aligned lines');
    for(const cls of ['match-rate','match-win','match-record','match-interval','match-games'])assert.ok(row.cells[i].querySelector('.'+cls));
    for(const badge of row.cells[i].querySelectorAll('.metric-win')){
     assert.equal(dom.window.getComputedStyle(badge).display,'inline');
     assert.equal(dom.window.getComputedStyle(badge.querySelector('small')).display,'inline','highlight must not introduce a block line');
     assert.ok(['↑','↓'].includes(badge.querySelector('small').textContent));
    }
   }
   if(!a||!b)assert.equal(row.cells[3].textContent,'—','missing comparison must not carry a unit');
  }
  const common=record.pairs.filter(p=>p.candidate===focus&&record.pairs.some(q=>q.candidate===base&&q.opponent===p.opponent));
  if(common.length){
   const style=d.querySelector('#style-body table');assert.equal(style.rows[1].cells[0].textContent,'得分效率');assert.equal(style.rows[2].cells[0].textContent,'贵族覆盖率');
   const totalVP=common.reduce((s,p)=>s+p.candidate_metrics.mean_prestige*p.candidate_metrics.games,0),main=common.reduce((s,p)=>s+p.candidate_metrics.total_main_actions,0);
   assert.equal(style.rows[1].cells[2].querySelector('strong,span').firstChild.textContent,(totalVP/main).toFixed(4));
   if(common.every(p=>p.candidate_trajectory)){
    // Frozen replay cohort totals: conditional means require purchase coverage,
    // not an equal average of opponent-level means or a denominator of all games.
    const row=label=>[...style.rows].find(r=>r.cells[0].textContent===label);
    assert.equal(row('20Main内达到8分的对局比例').cells[1].querySelector('strong,span').firstChild.textContent,'32.73%');
    assert.equal(row('20Main内达到8分的对局比例').cells[2].querySelector('strong,span').firstChild.textContent,'33.83%');
    assert.equal(row('首张4–5 VP牌购买时点（条件均值）').cells[1].querySelector('strong,span').firstChild.textContent,'20.205');
    assert.equal(row('首张4–5 VP牌购买时点（条件均值）').cells[2].querySelector('strong,span').firstChild.textContent,'20.014');
    assert.equal(row('购到4–5 VP牌的局数比例').cells[2].querySelector('strong,span').firstChild.textContent,'80.16%');
    assert.ok(d.querySelector('header').textContent.includes('Prism Alpha v0.1.5'));
   }
  }
 }
 assert.deepEqual(errors,[]);dom.window.close();
}
assert.equal(greedy,31);
console.log('PASS: '+groups+' match groups (31 greedy), matched version matrix, correct high/low/tie emphasis, pooled denominators, human/audit separation.');
