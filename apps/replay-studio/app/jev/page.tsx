"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { API_BASE as API } from "../api-base.mjs";
import {
  BoardSurface,
  type Action,
  type BoardFrame,
  type CardId,
  type NobleId,
  type PlayerId,
} from "../components/replay-board";
import { PlayerStateStrip } from "../components/player-state-strip";
import { StructuredAction, type ActionCatalog, type ActionPlayerView } from "../components/structured-action";
import { JevInteractionPanel, type StepView } from "../components/jev-interaction-panel";
import { describeStep } from "../jev-trace-runtime.mjs";
import { type DevelopmentCardData } from "../development-card";

type JevRunSummary = {
  run_id: string;
  has_trace_summary?: boolean;
  journal_recorded?: boolean;
  game_document?: string;
  anchor?: string | null;
  jev_seat?: number | null;
  jev_won?: boolean | null;
  scores?: number[] | null;
  decisions?: number | null;
  status?: string | null;
};

type JevTraceBundle = {
  format?: string;
  version?: number;
  run_id?: string;
  config?: { agents?: Array<{ program?: string; args?: string[] }> };
  trace?: {
    decisions?: Record<string, {
      ply?: number;
      actor?: number;
      family?: string;
      selected_index?: number;
      stages?: Array<{ stage: string; [key: string]: unknown }>;
      [key: string]: unknown;
    }>;
    journal_recorded?: boolean;
    game_document?: string;
    game_plies?: number | null;
  } | null;
};

type ArchiveFrame = {
  ply: number;
  actor: PlayerId;
  player_view: BoardFrame["player_view"];
  legal_actions: Action[];
  recorded_action: Action;
  referee_reveal: BoardFrame["referee_reveal"];
  observation_hash?: string;
};

type ReplayArchive = {
  format: string;
  version: number;
  session_id: string;
  opponent?: string | null;
  human_seat?: number | null;
  player_count: number;
  replay: {
    seed: number;
    steps: Array<{ actor: number; action: Action; [key: string]: unknown }>;
    result?: { scores?: number[]; winners?: number[] };
  };
  frames: ArchiveFrame[];
  catalog: {
    cards: Array<DevelopmentCardData & { id: CardId }>;
    nobles: Array<{ id: NobleId; prestige: number; requirements: number[] }>;
  };
};

export default function JevReplayPage() {
  const [runs, setRuns] = useState<JevRunSummary[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string>("");
  const [archive, setArchive] = useState<ReplayArchive | null>(null);
  const [jevTrace, setJevTrace] = useState<JevTraceBundle | null>(null);
  const [jevStepIndex, setJevStepIndex] = useState<number>(0);
  const [reveal, setReveal] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string>("");

  // 1. Fetch available Jev runs index on mount
  useEffect(() => {
    queueMicrotask(() =>
      void (async () => {
        try {
          const resp = await fetch(`${API}/jev/runs`);
          if (!resp.ok) throw new Error(`Host error ${resp.status}`);
          const data = await resp.json();
          const available: JevRunSummary[] = data.runs ?? [];
          setRuns(available);

          // Pick initial run from ?run= query param or default to the first available game
          const params = new URLSearchParams(window.location.search);
          const queryRun = params.get("run");
          if (queryRun && available.some((r) => r.run_id === queryRun)) {
            setSelectedRunId(queryRun);
          } else if (available.length > 0) {
            // Prefer roundB2 runs if available
            const b2 = available.find((r) => r.run_id.startsWith("00-"));
            setSelectedRunId(b2 ? b2.run_id : available[0].run_id);
          }
        } catch (e) {
          setError(e instanceof Error ? e.message : String(e));
        } finally {
          setLoading(false);
        }
      })(),
    );
  }, []);

  // 2. When selectedRunId changes, load its replay archive and Jev trace bundle
  useEffect(() => {
    if (!selectedRunId) return;

    let active = true;
    queueMicrotask(() =>
      void (async () => {
        setLoading(true);
        setError("");
        try {
          const [repResp, traceResp] = await Promise.all([
            fetch(`${API}/replays/${encodeURIComponent(selectedRunId)}`),
            fetch(`${API}/jev/runs/${encodeURIComponent(selectedRunId)}`),
          ]);

          if (!repResp.ok) {
            const err = await repResp.json().catch(() => ({}));
            throw new Error(err.error ?? `Replay load failed: HTTP ${repResp.status}`);
          }
          if (!traceResp.ok) {
            const err = await traceResp.json().catch(() => ({}));
            throw new Error(err.error ?? `Jev trace load failed: HTTP ${traceResp.status}`);
          }

          const repData: ReplayArchive = await repResp.json();
          const traceData: JevTraceBundle = await traceResp.json();

          if (active) {
            setArchive(repData);
            setJevTrace(traceData);
            setJevStepIndex(0);
            setLoading(false);
          }
        } catch (e) {
          if (active) {
            setError(e instanceof Error ? e.message : String(e));
            setLoading(false);
          }
        }
      })(),
    );

    return () => {
      active = false;
    };
  }, [selectedRunId]);

  // Determine Jev's seat (from archive human_seat or trace config)
  const jevSeat = useMemo<number>(() => {
    if (archive?.human_seat != null) return archive.human_seat;
    return 0;
  }, [archive]);

  // Filter frames: ONLY Jev's decision points! No opponent decisions.
  const jevFrames = useMemo<ArchiveFrame[]>(() => {
    if (!archive?.frames) return [];
    return archive.frames.filter((frame) => {
      // Must be Jev's turn
      if (frame.actor !== jevSeat) return false;
      // Or explicitly recorded in Jev decisions
      if (jevTrace?.trace?.decisions?.[String(frame.ply)]) return true;
      return frame.actor === jevSeat;
    });
  }, [archive, jevSeat, jevTrace]);

  const currentFrame = jevFrames[jevStepIndex] ?? null;

  // Keyboard navigation between Jev decisions
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        setJevStepIndex((prev) => Math.max(0, prev - 1));
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        setJevStepIndex((prev) => Math.min(jevFrames.length - 1, prev + 1));
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [jevFrames.length]);

  const cards = useMemo(
    () => new Map((archive?.catalog.cards ?? []).map((card) => [card.id, card])),
    [archive],
  );
  const nobles = useMemo(
    () => new Map((archive?.catalog.nobles ?? []).map((n) => [n.id, n])),
    [archive],
  );

  const scores = useMemo(() => {
    return archive?.replay.result?.scores ?? [];
  }, [archive]);

  function switchRun(runId: string) {
    setSelectedRunId(runId);
    const params = new URLSearchParams(window.location.search);
    params.set("run", runId);
    window.history.replaceState(null, "", `?${params.toString()}`);
  }

  return (
    <main className="studio">
      <header className="topbar">
        <div className="brand-block">
          <span className="eyebrow">JEV DEBUG REPLAY · JEV PERSPECTIVE ONLY</span>
          <h1>Jev Replay Studio</h1>
        </div>

        <div className="match-meta" style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <label htmlFor="run-select" style={{ fontSize: "12px", color: "var(--muted)", textTransform: "uppercase" }}>
            Select Run:
          </label>
          <select
            id="run-select"
            value={selectedRunId}
            onChange={(e) => switchRun(e.target.value)}
            style={{
              background: "#1c232d",
              color: "#e2e8f0",
              border: "1px solid var(--line)",
              borderRadius: "6px",
              padding: "4px 10px",
              fontSize: "13px",
              fontWeight: 500,
            }}
          >
            {runs.map((r) => {
              const won = r.jev_won === true ? "🏆 W" : r.jev_won === false ? "❌ L" : "";
              const sc = r.scores ? `[${r.scores.join("-")}]` : "";
              const label = `${r.run_id} · ${r.anchor ?? "anchor"} ${won} ${sc}`;
              return (
                <option key={r.run_id} value={r.run_id}>
                  {label}
                </option>
              );
            })}
          </select>

          <span className="meta-separator">/</span>
          <span>Opponent: <strong>{archive?.opponent ?? "—"}</strong></span>
          <span className="meta-separator">/</span>
          <span>Jev Seat: P{jevSeat}</span>
          <span className="meta-separator">/</span>
          <span>Score: {scores.length ? `${scores[jevSeat]} – ${scores[1 - jevSeat]}` : "—"}</span>
        </div>

        <div className="header-actions">
          <Link className="studio-link" href="/">
            Games
          </Link>
          <Link className="studio-link" href="/replay">
            Universal Replay
          </Link>
          <button
            className="icon-button"
            onClick={() => setJevStepIndex((prev) => Math.max(0, prev - 1))}
            disabled={jevStepIndex === 0}
            aria-label="Previous Jev Decision"
            title="Previous Jev Decision (← ArrowLeft)"
          >
            ←
          </button>
          <span style={{ fontSize: "13px", fontWeight: 600, padding: "0 4px" }}>
            {jevFrames.length > 0 ? `${jevStepIndex + 1} / ${jevFrames.length}` : "—"}
          </span>
          <button
            className="icon-button"
            onClick={() => setJevStepIndex((prev) => Math.min(jevFrames.length - 1, prev + 1))}
            disabled={jevStepIndex >= jevFrames.length - 1}
            aria-label="Next Jev Decision"
            title="Next Jev Decision (→ ArrowRight)"
          >
            →
          </button>
        </div>
      </header>

      {error ? (
        <div className="error-banner" role="alert" style={{ margin: "16px 24px" }}>
          {error}
        </div>
      ) : null}

      {loading && !error ? (
        <div className="review-progress" style={{ margin: "32px 24px" }}>
          <span className="section-kicker">LOADING</span>
          <h2>Loading Jev replay trace</h2>
          <p>Rebuilding board positions and joining step-by-step Jev interaction telemetry...</p>
        </div>
      ) : null}

      {!loading && currentFrame ? (
        <>
          <section className="workspace">
            {/* Left: The Universal Replay Board */}
            <div className="board-panel">
              <div className="panel-heading">
                <div>
                  <span className="section-kicker">
                    JEV DECISION #{jevStepIndex + 1} · PLY {currentFrame.ply}
                  </span>
                  <h2>Board State at Jev Turn</h2>
                </div>
                <div className="view-switch" role="group" aria-label="Information perspective">
                  <button className={!reveal ? "active" : ""} onClick={() => setReveal(false)}>
                    Jev View
                  </button>
                  <button className={reveal ? "active reveal-active" : ""} onClick={() => setReveal(true)}>
                    Referee Reveal
                  </button>
                </div>
              </div>

              {reveal ? (
                <div className="reveal-warning">
                  <span>REFEREE VIEW</span> Hidden cards and remaining deck order are exposed. Jev did not know this during its decision.
                </div>
              ) : null}

              <PlayerStateStrip playerView={currentFrame.player_view} actor={currentFrame.actor} humanSeat={jevSeat} />
              <BoardSurface frame={currentFrame} cards={cards} nobles={nobles} reveal={reveal} />
            </div>

            {/* Right: Jev Debugging & Interaction Panel (No Opponent Analysis) */}
            <aside className="analysis-panel" style={{ overflowY: "auto", maxHeight: "calc(100vh - 180px)" }}>
              <div className="analysis-header">
                <div>
                  <span className="section-kicker">JEV DECISION DIAGNOSTICS</span>
                  <h2>P{currentFrame.actor} Jev Action</h2>
                </div>
                <span className="budget">
                  {currentFrame.legal_actions.length} Legal Options
                </span>
              </div>

              {/* What Jev chose on this step */}
              <div style={{ marginBottom: "16px" }}>
                <StructuredAction
                  action={currentFrame.recorded_action}
                  playerView={currentFrame.player_view as ActionPlayerView}
                  cards={cards as ActionCatalog["cards"]}
                  nobles={nobles as ActionCatalog["nobles"]}
                />
              </div>

              {/* Jev Interaction: Prompt, Candidates, Heuristics, Confidence, Tokens */}
              {jevTrace ? (
                <JevInteractionPanel step={describeStep(currentFrame, jevTrace) as StepView} />
              ) : null}

              <details className="action-raw" style={{ marginTop: "16px" }}>
                <summary>Show raw executed action JSON</summary>
                <code>{JSON.stringify(currentFrame.recorded_action, null, 2)}</code>
              </details>
            </aside>
          </section>

          {/* Bottom Timeline: strictly Jev decisions */}
          <footer className="timeline-panel" style={{ padding: "12px 24px" }}>
            <div className="timeline-title" style={{ marginBottom: "8px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                <span className="section-kicker">JEV DECISION TIMELINE</span>
                <strong>
                  Decision {jevStepIndex + 1} of {jevFrames.length} (Ply {currentFrame.ply})
                </strong>
                <span style={{ fontSize: "12px", color: "var(--muted)" }}>
                  Use ← / → keys to step through Jev decisions
                </span>
              </div>
            </div>

            <div
              className="timeline-strip"
              style={{
                display: "flex",
                gap: "6px",
                overflowX: "auto",
                paddingBottom: "8px",
              }}
            >
              {jevFrames.map((f, idx) => {
                const dec = jevTrace?.trace?.decisions?.[String(f.ply)];
                const fam = (typeof dec?.family === "string" ? dec.family : null) ?? f.recorded_action.type;
                const isSelected = idx === jevStepIndex;

                let badgeColor = "#334155";
                let badgeText = fam;
                if (fam.includes("buy")) {
                  badgeColor = "#166534";
                  badgeText = "BUY";
                } else if (fam.includes("take")) {
                  badgeColor = "#1e40af";
                  badgeText = "TAKE";
                } else if (fam.includes("reserve")) {
                  badgeColor = "#854d0e";
                  badgeText = "RES";
                }

                return (
                  <button
                    key={f.ply}
                    onClick={() => setJevStepIndex(idx)}
                    style={{
                      flex: "0 0 auto",
                      background: isSelected ? "var(--accent, #3b82f6)" : "#1e293b",
                      border: isSelected ? "2px solid #60a5fa" : "1px solid #334155",
                      color: isSelected ? "#ffffff" : "#cbd5e1",
                      borderRadius: "6px",
                      padding: "6px 10px",
                      fontSize: "12px",
                      cursor: "pointer",
                      display: "flex",
                      flexDirection: "column",
                      alignItems: "center",
                      gap: "2px",
                      minWidth: "64px",
                    }}
                  >
                    <span style={{ fontWeight: 700 }}>#{idx + 1}</span>
                    <span
                      style={{
                        fontSize: "10px",
                        background: badgeColor,
                        color: "#fff",
                        padding: "1px 4px",
                        borderRadius: "3px",
                        fontWeight: 600,
                      }}
                    >
                      {badgeText}
                    </span>
                    <span style={{ fontSize: "10px", color: isSelected ? "#e0f2fe" : "#94a3b8" }}>
                      p{f.ply}
                    </span>
                  </button>
                );
              })}
            </div>
          </footer>
        </>
      ) : null}
    </main>
  );
}
