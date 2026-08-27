"use client";

import { ChangeEvent, useEffect, useMemo, useState } from "react";
import {
  actionKey,
  buildAnalysisRows,
  formatActionLabel as formatAction,
  isAnalysisTraceEnvelope,
  validateAnalysisTrace,
} from "./trace-runtime.mjs";
import { DevelopmentCard, EmptyDevelopmentCard, type DevelopmentCardData } from "./development-card";
import {
  BoardPanel,
  ReplayTimeline,
  gemCode,
  simpleActionLabel,
  type Action,
  type CardId,
  type Frame as BoardFrameLike,
  type Gems,
  type NobleId,
  type PlayerId,
  type PlayerView,
} from "./components/replay-board";

type Frame = BoardFrameLike & {
  state_hash_before: string;
  observation_hash: string;
  visible_event_count: number;
  information_set_hash: string;
  legal_actions: Action[];
  neural_result: {
    action: Action;
    action_stats: EdgeStats[];
    stats: { root_visits: number; simulations: number; tree_nodes: number };
  };
  recommended_matches_recorded: boolean;
};

type EdgeStats = {
  action: Action;
  prior_micros: number;
  visits: number;
  value_sum_by_player: number[];
};

type Trace = {
  format: string;
  version: number;
  replay_document_hash: string;
  replay_final_state_hash: string;
  player_count: number;
  analyzer_label: string;
  model_id: string;
  checkpoint_hash: string;
  value_scale: number;
  config: {
    simulations: number;
    max_depth_turns: number;
    puct_exploration_milli: number;
  };
  catalog: {
    cards: Array<{
      id: CardId;
      tier: string;
      bonus: string;
      prestige: number;
      cost: number[];
    }>;
    nobles: Array<{
      id: NobleId;
      prestige: number;
      requirements: number[];
    }>;
  };
  frames: Frame[];
};

type Replay = {
  format: string;
  version: number;
  player_count: number;
  final_state_hash: string;
  steps: Array<{
    ply: number;
    actor: PlayerId;
    action: Action;
    state_hash_before: string;
  }>;
  result?: { scores: number[]; ranks: number[]; winners: PlayerId[]; reason: string };
};

type HumanReplayArchive = {
  format: "effective-splendor-human-replay-archive";
  version: 1;
  session_id: string;
  opponent: string;
  replay_document_hash: string;
  replay: Replay;
  catalog?: { cards: DevelopmentCardData[]; nobles: Array<{ id:number; prestige:number; requirements:number[] }> };
  frames: Array<{
    ply: number;
    actor: PlayerId;
    player_view: PlayerView;
    legal_actions: Action[];
    recorded_action: Action;
  }>;
};

const GEM_KEYS: Array<keyof Gems> = [
  "white",
  "blue",
  "green",
  "red",
  "black",
  "gold",
];

const DEMO_TRACE: Trace = {
  format: "effective-splendor-analysis-trace",
  version: 1,
  replay_document_hash: "demo".padEnd(64, "0"),
  replay_final_state_hash: "demo-final".padEnd(64, "0"),
  player_count: 2,
  analyzer_label: "M13 Neural ISMCTS",
  model_id: "m12-policy-value-h32-v1",
  checkpoint_hash: "108d32fa2d0d2499ead38e99b23e42cd905644358a76d5adb7392ad43401b462",
  value_scale: 1_000_000,
  config: { simulations: 64, max_depth_turns: 2, puct_exploration_milli: 1500 },
  catalog: {
    cards: [
      { id: 7, tier: "One", bonus: "Blue", prestige: 0, cost: [1, 0, 2, 1, 1] },
      { id: 18, tier: "One", bonus: "Green", prestige: 1, cost: [0, 4, 0, 0, 0] },
      { id: 37, tier: "One", bonus: "Black", prestige: 0, cost: [0, 0, 2, 1, 0] },
      { id: 45, tier: "Two", bonus: "White", prestige: 2, cost: [0, 1, 4, 2, 0] },
      { id: 52, tier: "Two", bonus: "Red", prestige: 2, cost: [0, 3, 0, 2, 3] },
      { id: 65, tier: "Two", bonus: "Green", prestige: 3, cost: [0, 0, 6, 0, 0] },
      { id: 72, tier: "Three", bonus: "Blue", prestige: 4, cost: [3, 0, 3, 6, 0] },
      { id: 82, tier: "Three", bonus: "Red", prestige: 5, cost: [7, 0, 0, 0, 3] },
      { id: 88, tier: "Three", bonus: "Black", prestige: 4, cost: [0, 3, 3, 5, 3] },
    ],
    nobles: [
      { id: 1, prestige: 3, requirements: [0, 3, 3, 3, 0] },
      { id: 7, prestige: 3, requirements: [0, 4, 4, 0, 0] },
      { id: 9, prestige: 3, requirements: [4, 0, 0, 0, 4] },
    ],
  },
  frames: [demoFrame(28, 0, false), demoFrame(29, 1, true), demoFrame(30, 0, true), demoFrame(31, 1, false), demoFrame(32, 0, true)],
};

function demoFrame(ply: number, actor: number, mismatch: boolean): Frame {
  const market = [[7, 18, 37, null], [45, 52, 65, null], [72, 82, 88, null]];
  const buy: Action = { type: "buy_market", tier: "Two", slot: 2 };
  const take: Action = {
    type: "take_tokens",
    take: { white: 1, blue: 1, green: 1, red: 0, black: 0, gold: 0 },
    return: { white: 0, blue: 0, green: 0, red: 0, black: 0, gold: 0 },
  };
  const reserve: Action = {
    type: "reserve_market",
    tier: "Three",
    slot: 1,
    return: { white: 0, blue: 0, green: 0, red: 0, black: 0, gold: 0 },
  };
  const edges: EdgeStats[] = [
    { action: buy, prior_micros: 351_000, visits: 31, value_sum_by_player: actor === 0 ? [22_010_000, 8_990_000] : [8_990_000, 22_010_000] },
    { action: take, prior_micros: 227_000, visits: 20, value_sum_by_player: actor === 0 ? [12_600_000, 7_400_000] : [7_400_000, 12_600_000] },
    { action: reserve, prior_micros: 142_000, visits: 10, value_sum_by_player: actor === 0 ? [5_520_000, 4_480_000] : [4_480_000, 5_520_000] },
    { action: { type: "reserve_deck", tier: "Two", return: { white: 0, blue: 0, green: 0, red: 0, black: 0, gold: 0 } }, prior_micros: 80_000, visits: 3, value_sum_by_player: actor === 0 ? [1_410_000, 1_590_000] : [1_590_000, 1_410_000] },
  ];
  const recorded = mismatch ? take : buy;
  return {
    ply,
    state_hash_before: `state-${ply}`.padEnd(64, "0"),
    actor,
    recorded_action: recorded,
    observation_hash: `observation-${ply}`.padEnd(64, "0"),
    visible_event_count: 34 + ply,
    information_set_hash: `information-${ply}`.padEnd(64, "0"),
    player_view: {
      viewer: actor,
      public: {
        player_count: 2,
        current_player: actor,
        phase: "Main",
        bank: { white: 4, blue: 3, green: 2, red: 4, black: 3, gold: 4 },
        market,
        deck_counts: [26, 20, 13],
        nobles: [1, 7, 9],
        players: [
          { id: 0, tokens: { white: 2, blue: 1, green: 3, red: 0, black: 1, gold: 1 }, bonuses: [2, 1, 2, 0, 1], prestige: 8, reserved_count: 2, public_reserved: [37], purchased: [7, 18, 45], nobles: [] },
          { id: 1, tokens: { white: 1, blue: 3, green: 0, red: 2, black: 2, gold: 0 }, bonuses: [1, 3, 1, 2, 2], prestige: 10, reserved_count: 2, public_reserved: [52], purchased: [37, 52, 72], nobles: [1] },
        ],
        pending_nobles: [],
      },
      private: { reserved: [{ slot: 0, card: actor === 0 ? 82 : 65, tier: actor === 0 ? "Three" : "Two", from_deck: true }] },
    },
    referee_reveal: {
      seed: 930008,
      decks: [[3, 8, 21], [41, 63, 68], [73, 85, 89]],
      players: [
        { id: 0, reserved: [{ card: 82, from_deck: true }, { card: 37, from_deck: false }] },
        { id: 1, reserved: [{ card: 65, from_deck: true }, { card: 52, from_deck: false }] },
      ],
    },
    legal_actions: edges.map((edge) => edge.action),
    neural_result: { action: buy, action_stats: edges, stats: { root_visits: 64, simulations: 64, tree_nodes: 29 } },
    recommended_matches_recorded: !mismatch,
  };
}

function shortHash(hash: string): string {
  return `${hash.slice(0, 8)}…${hash.slice(-6)}`;
}

function isReplay(value: unknown): value is Replay {
  if (!value || typeof value !== "object") return false;
  const replay = value as Partial<Replay>;
  return replay.format === "effective-splendor-replay" && replay.version === 1 && Array.isArray(replay.steps);
}

function bindReplay(trace: Trace, replay: Replay): void {
  if (trace.replay_final_state_hash !== replay.final_state_hash || trace.player_count !== replay.player_count || trace.frames.length !== replay.steps.length) {
    throw new Error("Replay and analysis source identity do not match.");
  }
  for (let index = 0; index < trace.frames.length; index += 1) {
    const frame = trace.frames[index];
    const step = replay.steps[index];
    if (frame.ply !== step.ply || frame.actor !== step.actor || frame.state_hash_before !== step.state_hash_before || actionKey(frame.recorded_action) !== actionKey(step.action)) {
      throw new Error(`Replay and analysis diverge at ply ${index}.`);
    }
  }
}

export default function ReplayStudio() {
  const [trace, setTrace] = useState<Trace>(DEMO_TRACE);
  const [frameIndex, setFrameIndex] = useState(2);
  const [reveal, setReveal] = useState(false);
  const [fileName, setFileName] = useState("Guided demo · load an AnalysisTraceV1");
  const [sourceState, setSourceState] = useState("DEMO");
  const [error, setError] = useState("");
  const [humanArchive, setHumanArchive] = useState<HumanReplayArchive | null>(null);
  const frame = trace.frames[frameIndex] ?? trace.frames[0];
  const cards = useMemo(() => new Map(trace.catalog.cards.map((card) => [card.id, card])), [trace]);
  const nobles = useMemo(() => new Map(trace.catalog.nobles.map((noble) => [noble.id, noble])), [trace]);

  const changeFrame = (next: number) => {
    setFrameIndex(Math.max(0, Math.min(trace.frames.length - 1, next)));
  };

  useEffect(() => {
    const navigate = (event: globalThis.KeyboardEvent) => {
      if (event.key === "ArrowLeft") setFrameIndex((current) => Math.max(0, current - 1));
      if (event.key === "ArrowRight") setFrameIndex((current) => Math.min(trace.frames.length - 1, current + 1));
    };
    window.addEventListener("keydown", navigate);
    return () => window.removeEventListener("keydown", navigate);
  }, [trace.frames.length]);

  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("humanReplay") !== "1") return;
    try {
      const raw = sessionStorage.getItem("effective-splendor-human-replay");
      if (!raw) throw new Error("The completed human match is no longer in this browser session.");
      const value = JSON.parse(raw) as HumanReplayArchive;
      if (value.format !== "effective-splendor-human-replay-archive" || value.version !== 1 || !isReplay(value.replay) || !Array.isArray(value.frames) || value.frames.length !== value.replay.steps.length) {
        throw new Error("The human replay handoff is malformed or incomplete.");
      }
      queueMicrotask(() => setHumanArchive(value));
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "Unable to load human replay handoff.";
      queueMicrotask(() => setError(message));
    }
  }, []);

  const loadTrace = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    if (!files.length) return;
    try {
      const parsed = await Promise.all(files.map(async (file) => ({ file, value: JSON.parse(await file.text()) as unknown })));
      const traceFile = parsed.find((item) => isAnalysisTraceEnvelope(item.value));
      const replayFile = parsed.find((item) => isReplay(item.value));
      if (!traceFile) throw new Error("Select an AnalysisTraceV1 sidecar, optionally with its ReplayV1.");
      const nextTrace = validateAnalysisTrace(traceFile.value) as Trace;
      if (replayFile && isReplay(replayFile.value)) bindReplay(nextTrace, replayFile.value);
      setTrace(nextTrace);
      setFrameIndex(0);
      setReveal(false);
      setFileName(parsed.map((item) => item.file.name).join(" + "));
      setSourceState(replayFile ? "REPLAY + SIDECAR" : "SIDECAR");
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to read analysis file.");
    } finally {
      event.target.value = "";
    }
  };

  const actor = frame.actor;
  const rows = buildAnalysisRows(trace, frame) as Array<EdgeStats & {
    prior: number;
    visit: number;
    q: number | null;
    actual: boolean;
    best: boolean;
  }>;
  const bestQ = rows.find((row) => row.best)?.q ?? null;

  if (humanArchive) return <HumanReplayAudit archive={humanArchive} />;

  return (
    <main className="studio">
      <header className="topbar">
        <div className="brand-block">
          <span className="eyebrow">EFFECTIVE SPLENDOR · M14A</span>
          <h1>Replay Studio</h1>
        </div>
        <div className="match-meta">
          <span className="status-dot" aria-hidden="true" />
          <span>{sourceState} · {fileName}</span>
          <span className="meta-separator">/</span>
          <span>Ply {frame.ply}</span>
          <span className="meta-separator">/</span>
          <span>Actor P{frame.actor}</span>
        </div>
        <div className="header-actions">
          <a className="studio-link" href="/play">Play vs AI</a>
          <a className="studio-link" href="/ratings">Rating Studio</a>
          <label className="load-button">
            Load replay + analysis
            <input type="file" accept="application/json,.json" multiple onChange={loadTrace} />
          </label>
          <button className="icon-button" onClick={() => changeFrame(frameIndex - 1)} disabled={frameIndex === 0} aria-label="Previous ply">←</button>
          <button className="icon-button" onClick={() => changeFrame(frameIndex + 1)} disabled={frameIndex === trace.frames.length - 1} aria-label="Next ply">→</button>
        </div>
      </header>

      {error && <div className="error-banner" role="alert">{error}</div>}

      <section className="workspace">
        <div className="board-panel">
          <div className="panel-heading">
            <div>
              <span className="section-kicker">POSITION</span>
              <h2>Decision board</h2>
            </div>
            <div className="view-switch" role="group" aria-label="Information perspective">
              <button className={!reveal ? "active" : ""} onClick={() => setReveal(false)}>Player view</button>
              <button className={reveal ? "active reveal-active" : ""} onClick={() => setReveal(true)}>Referee reveal</button>
            </div>
          </div>

          <BoardPanel frame={frame} cards={cards} nobles={nobles} reveal={reveal} />
        </div>

        <aside className="analysis-panel">
          <div className="analysis-header">
            <div><span className="section-kicker">ACTION ANALYSIS</span><h2>{trace.analyzer_label}</h2></div>
            <span className="budget">{trace.config.simulations} sims · d{trace.config.max_depth_turns} · c{(trace.config.puct_exploration_milli / 1000).toFixed(3)}</span>
          </div>
          <div className="legend"><span><i className="actual-marker">★</i> actual</span><span><i className="best-marker">▲</i> search best</span></div>
          <div className="analysis-table" role="table" aria-label="Root action analysis">
            <div className="analysis-row table-head" role="row"><span>Action</span><span>Prior</span><span>Visit</span><span>Q(P{actor})</span><span>ΔQ</span></div>
            {rows.map((row) => {
              const delta = row.q != null && bestQ != null ? row.q - bestQ : null;
              return (
                <div className={`analysis-row ${row.actual ? "actual-row" : ""} ${row.best ? "best-row" : ""}`} role="row" key={actionKey(row.action)}>
                  <span className="action-name"><i>{row.actual ? "★" : row.best ? "▲" : ""}</i>{formatAction(row.action, frame, cards)}</span>
                  <MetricBar value={row.prior} tone="prior" />
                  <MetricBar value={row.visit} tone="visit" />
                  <span className="q-value">{row.q == null ? "—" : row.q.toFixed(3)}</span>
                  <span className={`delta ${delta === 0 ? "best" : ""}`}>{delta == null ? "—" : delta === 0 ? "BEST" : delta.toFixed(3)}</span>
                </div>
              );
            })}
          </div>
          <div className="decision-summary">
            <span className={frame.recommended_matches_recorded ? "match" : "mismatch"}>{frame.recommended_matches_recorded ? "SEARCH AGREED" : "SEARCH DISAGREED"}</span>
            <p>Played <strong>{formatAction(frame.recorded_action, frame, cards)}</strong></p>
            <p>Recommended <strong>{formatAction(frame.neural_result.action, frame, cards)}</strong></p>
          </div>
          <dl className="trace-meta">
            <div><dt>Information set</dt><dd>{shortHash(frame.information_set_hash)}</dd></div>
            <div><dt>Observation</dt><dd>{shortHash(frame.observation_hash)}</dd></div>
            <div><dt>Checkpoint</dt><dd>{shortHash(trace.checkpoint_hash)}</dd></div>
            <div><dt>Tree nodes</dt><dd>{frame.neural_result.stats.tree_nodes}</dd></div>
          </dl>
        </aside>
      </section>

      <ReplayTimeline
        frames={trace.frames}
        frameIndex={frameIndex}
        onSeek={changeFrame}
        isCandidatePly={(item) => item.recommended_matches_recorded}
        title="← → keyboard navigation"
        footnote="agreement coloring"
      />
    </main>
  );
}

function HumanReplayAudit({ archive }: { archive: HumanReplayArchive }) {
  const [index, setIndex] = useState(0);
  const frame = archive.frames[index];
  const view = frame.player_view.public;
  const cards = useMemo(() => new Map((archive.catalog?.cards ?? []).map(card=>[card.id,card])), [archive.catalog]);
  const change = (next: number) => setIndex(Math.max(0, Math.min(archive.frames.length - 1, next)));
  return <main className="studio human-replay-audit">
    <header className="topbar">
      <div className="brand-block"><span className="eyebrow">M20 · VERIFIED HUMAN MATCH</span><h1>Replay Studio</h1></div>
      <div className="match-meta"><span className="status-dot"/><span>{archive.opponent}</span><span className="meta-separator">/</span><span>Ply {frame.ply}</span><span className="meta-separator">/</span><span>Actor P{frame.actor}</span></div>
      <div className="header-actions"><a className="studio-link" href="/play">Back to Human Play</a><button className="icon-button" onClick={()=>change(index-1)} disabled={index===0} aria-label="Previous ply">←</button><button className="icon-button" onClick={()=>change(index+1)} disabled={index===archive.frames.length-1} aria-label="Next ply">→</button></div>
    </header>
    <section className="human-audit-summary"><div><span className="section-kicker">REPLAY V1 VERIFIED</span><h2>{archive.session_id}</h2></div><dl><div><dt>Document hash</dt><dd>{archive.replay_document_hash}</dd></div><div><dt>Final score</dt><dd>{archive.replay.result?.scores.join(" – ")??"—"}</dd></div><div><dt>Frames</dt><dd>{archive.frames.length}</dd></div></dl></section>
    <section className="human-audit-grid">
      <article className="human-board">
        <div className="human-score">{view.players.map(player=><div className={player.id===frame.actor?"you":""} key={player.id}><span>{player.id===frame.actor?"ACTOR":`PLAYER ${player.id}`}</span><strong>{player.prestige}<small> VP</small></strong><small>{player.reserved_count} reserved</small></div>)}</div>
        <div className="human-bank"><span>BANK</span>{GEM_KEYS.map(gem=><i className={`token-${gem}`} key={gem}>{gemCode(gem)} <b>{view.bank[gem]}</b></i>)}</div>
        <div className="human-market">{[2,1,0].map(tier=><div className="human-tier" key={tier}><span>TIER {tier+1}<small>{view.deck_counts[tier]} deck</small></span>{view.market[tier].map((cardId,slot)=>cardId==null?<EmptyDevelopmentCard key={slot}/>:cards.has(cardId)?<DevelopmentCard card={cards.get(cardId)!} slotLabel={`slot ${slot+1}`} key={slot}/>:<div className="development-card development-card-empty" key={slot}>#{cardId}</div>)}</div>)}</div>
        <div className="human-private"><span>ACTOR PLAYER VIEW</span><p>Each frame shows only the Observation that the acting player received at that decision. Hidden deck order and opponent blind reserves remain unavailable.</p></div>
      </article>
      <aside className="human-actions"><span className="section-kicker">RECORDED DECISION</span><h2>{simpleActionLabel(frame.recorded_action)}</h2><div className="human-audit-action"><small>Chosen from {frame.legal_actions.length} server-certified legal actions</small><code>{JSON.stringify(frame.recorded_action,null,2)}</code></div></aside>
    </section>
    <footer className="timeline-panel"><div className="timeline-title"><div><span className="section-kicker">HUMAN MATCH TIMELINE</span><strong>{index+1} / {archive.frames.length}</strong></div><span>player-view audit · no analysis sidecar</span></div><div className="timeline">{archive.frames.map((item,itemIndex)=><button key={item.ply} onClick={()=>change(itemIndex)} className={itemIndex===index?"current agreed":"agreed"} aria-label={`Ply ${item.ply}, actor P${item.actor}`}><span>{item.ply}</span><i/></button>)}</div></footer>
  </main>;
}

function MetricBar({ value, tone }: { value: number; tone: "prior" | "visit" }) {
  return <span className="metric"><span>{(value * 100).toFixed(1)}%</span><i><b className={tone} style={{ width: `${Math.min(100, value * 100)}%` }} /></i></span>;
}
