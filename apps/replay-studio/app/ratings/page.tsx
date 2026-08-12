"use client";

import { ChangeEvent, useState } from "react";
import Link from "next/link";
import { headToHeadCell, validateRatingReport } from "../rating-runtime.mjs";

type Agent = { rank: number; agent_id: string; display_name: string; class: string; completed: number; aborted: number; wins: number; ties: number; losses: number; live_elo: number; official_elo: number; provisional: boolean };
type Head = { agent_a: string; agent_b: string; completed: number; aborted: number; wins_a: number; ties: number; wins_b: number };
type Report = { format: string; version: number; tournament_id: string; registry_hash: string; round_robin_plan_hash: string; scheduled_matches: number; completed_matches: number; aborted_matches: number; agents: Agent[]; head_to_head: Head[]; pair_evaluation_report_hashes: string[] };

const DEMO: Report = {
  format: "effective-splendor-rating-report", version: 1, tournament_id: "m16-foundation-demo",
  registry_hash: "91".repeat(32), round_robin_plan_hash: "a7".repeat(32), scheduled_matches: 18, completed_matches: 18, aborted_matches: 0,
  agents: [
    { rank: 1, agent_id: "m07", display_name: "M07 Determinization", class: "search", completed: 12, aborted: 0, wins: 9, ties: 0, losses: 3, live_elo: 1588, official_elo: 1657, provisional: true },
    { rank: 2, agent_id: "heuristic", display_name: "Heuristic", class: "baseline", completed: 12, aborted: 0, wins: 6, ties: 0, losses: 6, live_elo: 1504, official_elo: 1500, provisional: true },
    { rank: 3, agent_id: "random", display_name: "Random", class: "baseline", completed: 12, aborted: 0, wins: 3, ties: 0, losses: 9, live_elo: 1408, official_elo: 1343, provisional: true },
  ],
  head_to_head: [
    { agent_a: "m07", agent_b: "heuristic", completed: 6, aborted: 0, wins_a: 4, ties: 0, wins_b: 2 },
    { agent_a: "m07", agent_b: "random", completed: 6, aborted: 0, wins_a: 5, ties: 0, wins_b: 1 },
    { agent_a: "heuristic", agent_b: "random", completed: 6, aborted: 0, wins_a: 4, ties: 0, wins_b: 2 },
  ], pair_evaluation_report_hashes: ["b1".repeat(32), "b2".repeat(32), "b3".repeat(32)],
};

export default function RatingsPage() {
  const [report, setReport] = useState<Report>(DEMO);
  const [error, setError] = useState("");
  async function load(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]; if (!file) return;
    try { setReport(validateRatingReport(JSON.parse(await file.text())) as Report); setError(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    event.target.value = "";
  }
  return <main className="rating-studio">
    <header className="rating-topbar">
      <div><span className="section-kicker">M16 · 1V1 LEAGUE</span><h1>Rating Studio</h1></div>
      <div className="rating-run"><span className="status-dot" />{report.tournament_id}</div>
      <nav><Link href="/play">Play vs AI</Link><Link href="/">Replay Studio</Link><label className="load-button">Load rating report<input type="file" accept="application/json,.json" onChange={load} /></label></nav>
    </header>
    {error && <div className="error-banner">{error}</div>}
    <section className="rating-summary">
      <div><small>COMPLETED</small><strong>{report.completed_matches}/{report.scheduled_matches}</strong></div>
      <div><small>ABORTS</small><strong className={report.aborted_matches ? "bad" : "good"}>{report.aborted_matches}</strong></div>
      <div><small>POOL</small><strong>{report.agents.length} agents</strong></div>
      <div><small>OFFICIAL METHOD</small><strong>Batch BT · Elo scale</strong></div>
    </section>
    <section className="rating-grid">
      <article className="rating-panel">
        <div className="rating-heading"><div><span className="section-kicker">LEADERBOARD</span><h2>Internal strength floor</h2></div><span>Official is order-independent</span></div>
        <div className="leaderboard">
          <div className="leader-row leader-head"><span>Rank / Agent</span><span>W-T-L</span><span>Live</span><span>Official</span></div>
          {report.agents.map((agent) => <div className="leader-row" key={agent.agent_id}>
            <span><b>#{agent.rank}</b><i>{agent.display_name}<small>{agent.class}{agent.provisional ? " · provisional" : ""}</small></i></span>
            <span>{agent.wins}-{agent.ties}-{agent.losses}</span><span>{agent.live_elo}</span><strong>{agent.official_elo}</strong>
          </div>)}
        </div>
      </article>
      <article className="rating-panel matrix-panel">
        <div className="rating-heading"><div><span className="section-kicker">HEAD TO HEAD</span><h2>Non-transitivity matrix</h2></div><span>row W-T-L vs column</span></div>
        <div className="matrix" style={{gridTemplateColumns: `minmax(145px, 1fr) repeat(${report.agents.length}, minmax(76px, .65fr))`}}>
          <span />{report.agents.map((agent) => <b key={agent.agent_id}>{agent.display_name}</b>)}
          {report.agents.flatMap((row) => [<strong key={`${row.agent_id}-name`}>{row.display_name}</strong>, ...report.agents.map((column) => { const cell = headToHeadCell(report, row.agent_id, column.agent_id); return <span className={cell.tone} key={`${row.agent_id}-${column.agent_id}`}>{cell.label}</span>; })])}
        </div>
      </article>
    </section>
    <footer className="rating-provenance"><span>PLAN <code>{report.round_robin_plan_hash.slice(0, 16)}…</code></span><span>REGISTRY <code>{report.registry_hash.slice(0, 16)}…</code></span><span>{report.pair_evaluation_report_hashes.length} canonical pair reports bound</span></footer>
  </main>;
}
