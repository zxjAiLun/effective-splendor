// Optional local Chromium gate for the retired Rating Studio roster. Built app
// + mocked Host boundary; no real League, no browser download. Run after build.
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { launchStudioBrowser } from "./helpers/studio-browser.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const artifactDir = process.env.PLAYER_LOOP_ARTIFACTS || path.join(root, "../../local-artifacts/m80-local-history-cleanup/browser");
const b = await launchStudioBrowser({ artifactDir });

try {
  await b.send("Page.addScriptToEvaluateOnNewDocument", { source: `(() => {
    const nativeFetch=window.fetch.bind(window);window.hostCalls=[];
    const reply=(body,status=200)=>Promise.resolve(new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}}));
    window.fetch=(url,opts={})=>{
      const address=new URL(String(url),location.href);
      if(address.origin!=='http://127.0.0.1:43120')return nativeFetch(url,opts);
      const route=address.pathname;window.hostCalls.push(route);
      if(route==='/league/leaderboard')return reply({format:'effective-splendor-studio-league-leaderboard',version:1,rows:[
        {participant_id:'12345678-1234-1234-1234-123456789012',kind:'human',display_name:'You',elo:1530,rated_games:1,recorded_games:1,rated_wins:1,rated_ties:0,rated_losses:0,provisional:true},
        {participant_id:'prism-v011',kind:'engine',display_name:'Prism v0.1.1',elo:1516,rated_games:2,recorded_games:2,rated_wins:1,rated_ties:0,rated_losses:1,provisional:true},
        {participant_id:'eng-old',kind:'engine',display_name:'S3 Rollout (Default · Strong)',elo:1923,rated_games:168,recorded_games:168,rated_wins:100,rated_ties:4,rated_losses:64,provisional:false}
      ]});
      return reply({error:'unhandled test route '+route},404);
    };
  })();` });
  await b.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  await b.send("Page.navigate", { url: `${b.origin}/ratings` });
  await b.wait("document.body && document.body.innerText.includes('1530')");
  const ratingsText = await b.evaluate("document.body.innerText");
  assert.match(ratingsText, /STUDIO LEAGUE · CURRENT STANDINGS/);
  assert.match(ratingsText, /You/);
  assert.match(ratingsText, /1530/);
  assert.match(ratingsText, /1-0-0/);
  assert.doesNotMatch(ratingsText, /Prism v0\.1\.1|S3 Rollout|1923/);
  assert.doesNotMatch(ratingsText, /Official/i);
  assert.deepEqual(await b.evaluate("window.hostCalls"), ["/league/leaderboard"]);
  await b.screenshot("ratings-retired-roster.png");

  await b.send("Page.navigate", { url: `${b.origin}/ratings/reports` });
  await b.wait("document.body && document.body.innerText.includes('No current Studio models')");
  let text = await b.evaluate("document.body.innerText");
  assert.match(text, /UPLOAD ONLY · ARCHIVED RESEARCH/);
  assert.match(text, /0\/0/);
  assert.match(text, /Load rating report/);
  assert.doesNotMatch(text, /Archive A|Archive B|M19|M22/);
  assert.deepEqual(await b.evaluate("window.hostCalls"), []);

  const upload = {
    format: "effective-splendor-rating-report", version: 1, tournament_id: "gate-upload-report",
    registry_hash: "0".repeat(64), round_robin_plan_hash: "1".repeat(64),
    scheduled_matches: 2, completed_matches: 2, aborted_matches: 0,
    agents: [
      { rank: 1, agent_id: "prism-v011", display_name: "Upload A", class: "search", completed: 2, aborted: 0, wins: 2, ties: 0, losses: 0, live_elo: 1516, official_elo: 1600, provisional: true },
      { rank: 2, agent_id: "prism-alpha-v01", display_name: "Upload B", class: "baseline", completed: 2, aborted: 0, wins: 0, ties: 0, losses: 2, live_elo: 1484, official_elo: 1400, provisional: true },
    ],
    head_to_head: [{ agent_a: "prism-v011", agent_b: "prism-alpha-v01", completed: 2, aborted: 0, wins_a: 2, ties: 0, wins_b: 0 }],
    pair_evaluation_report_hashes: ["2".repeat(64)],
  };
  const uploadPath = path.join(os.tmpdir(), `m80-gate-upload-${process.pid}.json`);
  fs.writeFileSync(uploadPath, JSON.stringify(upload));
  const { root: docRoot } = await b.send("DOM.getDocument");
  const input = await b.send("DOM.querySelector", { nodeId: docRoot.nodeId, selector: "input[type=file]" });
  assert.ok(input.nodeId);
  await b.send("DOM.setFileInputFiles", { files: [uploadPath], nodeId: input.nodeId });
  await b.wait("document.body && document.body.innerText.includes('2/2')");
  text = await b.evaluate("document.body.innerText");
  assert.doesNotMatch(text, /Upload A|Upload B|gate-upload-report/);
  assert.match(text, /No current Studio model or archived report is displayed/);
  assert.deepEqual(await b.evaluate("window.hostCalls"), []);
  await b.screenshot("reports-upload-retired-filter.png");
  assert.deepEqual(b.exceptions, []);
  console.log("ratings-page-browser: PASS (retired roster shows no engines; default/upload research reports render no pre-cleanup models and make zero league reads)");
} finally {
  await b.close();
}
