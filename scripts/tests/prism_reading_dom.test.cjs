// Offline DOM checks only: no browser, network, or live UI control.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {createRequire} = require('node:module');
const root = path.resolve(__dirname,'../..');
const localRequire = createRequire(path.join(root,'local-artifacts/prism/report-ui-test/package.json'));
const {JSDOM,VirtualConsole} = localRequire('jsdom');
let groups=0;
for(const filename of ['m63-prism-beta-timed-building-evaluation','m62-prism-beta-building-comparison','m61-prism-alpha-balance-ab-comparison']){
 const file=path.join(root,'docs/prism',filename+'.audit.html');
 const errors=[];
 const console=new VirtualConsole();console.on('jsdomError',e=>errors.push(String(e)));
 const dom=new JSDOM(fs.readFileSync(file,'utf8'),{runScripts:'dangerously',url:'file:///'+file.replaceAll('\\','/'),virtualConsole:console});
 const d=dom.window.document;
 const data=JSON.parse(d.querySelector('#report-data').textContent);
 assert.equal(d.querySelectorAll('.card').length,3);
 if(data.practical_review){
  assert.ok(d.querySelector('.headline').textContent.includes('Prism Alpha v0.1.5'));
  assert.ok(data.practical_review.route_history.some(r=>r.candidate_alias.includes('Balance')),'keep superseded route history');
  assert.ok(!d.querySelector('#overview').textContent.includes('未接受'));
  assert.equal(d.querySelector('#historical-research').open,false);
  const coverage=[...d.querySelectorAll('#coverage-body tbody tr')];
  assert.equal(coverage.length,data.result.acceptance_policy.anchors.length);
  const pair=(model,opponent)=>data.result.acceptance.pairs.find(p=>p.candidate===model&&p.opponent===opponent);
  for(const [i,opponent] of data.result.acceptance_policy.anchors.entries()){
   const base=pair(data.practical_review.parent_key,opponent).candidate_metrics.score_rate;
   const candidate=pair(data.focus,opponent).candidate_metrics.score_rate;
   assert.equal(coverage[i].cells[1].textContent,(base*100).toFixed(2)+'%');
   assert.equal(coverage[i].cells[2].textContent,(candidate*100).toFixed(2)+'%');
   assert.ok(coverage[i].cells[3].textContent.includes(((candidate-base)*100).toFixed(2)));
  }
  assert.equal(data.practical_review.weight_sha256,data.result.candidate_sha256[data.focus]);
  assert.equal(data.practical_review.registration_status,'RELEASED_EXPERIMENTAL_MODEL');
  assert.equal(data.result.verdicts.beta_acceptance,'NOT_ACCEPTED_BUILDING_CANDIDATE');
 }
 assert.equal(d.querySelectorAll('#gate-body>details').length,Object.values(data.result.gates).filter(v=>!v).length);
 function select(id,value){const el=d.getElementById(id);el.value=value;el.dispatchEvent(new dom.window.Event('change'));}
 select('gate-filter','all');
 assert.equal(d.querySelectorAll('#gate-body>details').length,Object.keys(data.result.gates).length);
 assert.equal(d.querySelectorAll('#gate-body>details[open]').length,0);
 for(const stage of ['acceptance','development']){
  select('detail-stage',stage);
  const models=[...new Set(data.result[stage].pairs.map(p=>p.candidate))];
  for(const model of models){
   select('detail-model',model);
   const pairs=data.result[stage].pairs.filter(p=>p.candidate===model);
   assert.equal(d.querySelectorAll('#detail-opponent option').length,pairs.length);
   for(const p of pairs){
    select('detail-opponent',p.opponent);
    const body=d.getElementById('detail-body');
    const rows=[...body.querySelectorAll('table:first-of-type tbody tr')];
    assert.ok(rows.length>=6);
    const matchTable=body.querySelector('table');
    assert.equal(matchTable.rows[1].cells[1].textContent,String(p.candidate_metrics.games));
    assert.equal(matchTable.rows[2].cells[1].textContent,String(p.candidate_metrics.wins));
    assert.equal(matchTable.rows[2].cells[2].textContent,String(p.opponent_metrics.wins));
    assert.ok(body.textContent.includes((100*p.candidate_metrics.score_rate).toFixed(2)+'%'));
    assert.ok(body.textContent.includes(p.candidate_metrics.win_rate_percent.toFixed(2)+'%'));
    assert.ok(body.textContent.includes('先手（P0）')&&body.textContent.includes('后手（P1）'));
    assert.ok(!/\bNaN\b|\bundefined\b|\bInfinity\b/.test(body.textContent));
    assert.ok(body.textContent.includes('NOT_MEASURED'));
    assert.ok(body.textContent.includes('买公开牌')&&body.textContent.includes('盲预留牌'));
    assert.ok([...body.querySelectorAll('details')].every(el=>!el.open));
    groups++;
   }
  }
 }
 select('strength-model',data.focus);
 assert.equal(d.querySelectorAll('#strength-body svg').length,data.result.acceptance.pairs.filter(p=>p.candidate===data.focus).length);
 assert.ok(!/\bNaN\b|\bundefined\b|\bInfinity\b/.test(d.getElementById('app').textContent));
 const link=d.getElementById('reading-md-link').getAttribute('href');
 assert.ok(fs.existsSync(path.join(path.dirname(file),link)));
 const md=fs.readFileSync(path.resolve(path.dirname(file),data.sources.markdown),'utf8');
 assert.ok(fs.readFileSync(path.join(path.dirname(file),link),'utf8').replaceAll('\r\n','\n').includes(md.replaceAll('\r\n','\n')));
 assert.deepEqual(errors,[]);
 dom.window.close();
}
console.log(`PASS: 3 offline reports; ${groups} stage/model/opponent groups; all gates, both actors, seats, action groups, source Markdown and unknown timings preserved.`);
