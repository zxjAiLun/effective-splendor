"use client";

/**
 * Legacy AnalysisTraceV1 / diagnostic import.
 *
 * Kept for historical sidecars only (per-ply M07/M13 analyses). It is NOT the
 * product entry point: modern reviews are AnalysisTraceV2 bundles opened by
 * `/review`, and saved games are listed on `/`.
 */

import Link from "next/link";
import { ChangeEvent, useEffect, useMemo, useState } from "react";
import {
  actionKey,
  buildAnalysisRows,
  formatActionLabel as formatAction,
  isAnalysisTraceEnvelope,
  validateAnalysisTrace,
} from "../trace-runtime.mjs";
import {
  BoardSurface,
  ReplayTimeline,
  usePlyNavigation,
  type Action,
  type BoardFrame as BoardFrameLike,
  type CardId,
  type NobleId,
  type PlayerId,
} from "../components/replay-board";
import { type DevelopmentCardData } from "../development-card";

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
  config: { simulations: number; max_depth_turns: number; puct_exploration_milli: number };
  catalog: {
    cards: Array<DevelopmentCardData & { id: CardId }>;
    nobles: Array<{ id: NobleId; prestige: number; requirements: number[] }>;
  };
  frames: Frame[];
};

type Replay = {
  format: string;
  version: number;
  player_count: number;
  final_state_hash: string;
  steps: Array<{ ply: number; actor: PlayerId; action: Action; state_hash_before: string }>;
};

function shortHash(hash: string): string {
  return `${hash.slice(0, 8)}…${hash.slice(-6)}`;
}

function isReplay(value: unknown): value is Replay {
  if (!value || typeof value !== "object") return false;
  const replay = value as Partial<Replay>;
  return replay.format === "effective-splendor-replay" && replay.version === 1 && Array.isArray(replay.steps);
}

function bindReplay(trace: Trace, replay: Replay): void {
  if (
    trace.replay_final_state_hash !== replay.final_state_hash ||
    trace.player_count !== replay.player_count ||
    trace.frames.length !== replay.steps.length
  ) {
    throw new Error("Replay and analysis source identity do not match.");
  }
  for (let index = 0; index < trace.frames.length; index += 1) {
    const frame = trace.frames[index];
    const step = replay.steps[index];
    if (
      frame.ply !== step.ply ||
      frame.actor !== step.actor ||
      frame.state_hash_before !== step.state_hash_before ||
      actionKey(frame.recorded_action) !== actionKey(step.action)
    ) {
      throw new Error(`Replay and analysis diverge at ply ${index}.`);
    }
  }
}

export default function LegacyTraceViewer() {
  const [trace, setTrace] = useState<Trace | null>(null);
  const [frameIndex, setFrameIndex] = useState(0);
  const [reveal, setReveal] = useState(false);
  const [fileName, setFileName] = useState("");
  const [sourceState, setSourceState] = useState("");
  const [error, setError] = useState("");
  const frame = trace ? trace.frames[frameIndex] ?? trace.frames[0] : null;
  const cards = useMemo(
    () => new Map((trace?.catalog.cards ?? []).map((card) => [card.id, card])),
    [trace],
  );
  const nobles = useMemo(() => new Map((trace?.catalog.nobles ?? []).map((noble) => [noble.id, noble])), [trace]);

  const changeFrame = (next: number) => {
    if (!trace) return;
    setFrameIndex(Math.max(0, Math.min(trace.frames.length - 1, next)));
  };

  usePlyNavigation(trace?.frames.length ?? 0, (delta) => {
    if (!trace) return;
    setFrameIndex((current) => Math.max(0, Math.min(trace.frames.length - 1, current + delta)));
  });

  useEffect(() => {
    const timeline = document.querySelector<HTMLElement>(".timeline");
    const activeBtn = document.querySelector<HTMLElement>(".timeline button.current");
    if (timeline && activeBtn) {
      const targetLeft = activeBtn.offsetLeft - timeline.clientWidth / 2 + activeBtn.clientWidth / 2;
      timeline.scrollTo({ left: targetLeft, behavior: "smooth" });
    }
  }, [frameIndex]);

  const loadTrace = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    if (!files.length) return;
    try {
      const parsed = await Promise.all(
        files.map(async (file) => ({ file, value: JSON.parse(await file.text()) as unknown })),
      );
      const traceFile = parsed.find((item) => isAnalysisTraceEnvelope(item.value));
      if (!traceFile) {
        throw new Error("No AnalysisTraceV1 sidecar in the selection. This viewer requires one.");
      }
      const replayFile = parsed.find((item) => isReplay(item.value));
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

  const rows = trace && frame ? (buildAnalysisRows(trace, frame) as Array<EdgeStats & { prior: number; visit: number; q: number | null; actual: boolean; best: boolean }>) : [];
  const bestQ = rows.find((row) => row.best)?.q ?? null;

  return (
    <main className="studio">
      <header className="topbar">
        <div className="brand-block">
          <span className="eyebrow">M14A · LEGACY DIAGNOSTIC VIEWER</span>
          <h1>Replay Studio</h1>
        </div>
        <div className="match-meta">
          <span className="status-dot" aria-hidden="true" />
          <span>{trace ? `${sourceState} · ${fileName}` : "no sidecar loaded"}</span>
          {trace && frame ? (
            <>
              <span className="meta-separator">/</span>
              <span>Ply {frame.ply}</span>
              <span className="meta-separator">/</span>
              <span>Actor P{frame.actor}</span>
            </>
          ) : null}
        </div>
        <div className="header-actions">
          <Link className="studio-link" href="/">
            Games
          </Link>
          <Link className="studio-link" href="/play">
            Play vs S3
          </Link>
          <label className="load-button">
            Load legacy sidecar
            <input type="file" accept="application/json,.json" multiple onChange={loadTrace} />
          </label>
          {trace ? (
            <>
              <button className="icon-button" onClick={() => changeFrame(frameIndex - 1)} disabled={frameIndex === 0} aria-label="Previous ply">
                ←
              </button>
              <button
                className="icon-button"
                onClick={() => changeFrame(frameIndex + 1)}
                disabled={frameIndex === trace.frames.length - 1}
                aria-label="Next ply"
              >
                →
              </button>
            </>
          ) : null}
        </div>
      </header>

      {error ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}

      {!trace ? (
        <section className="recent-games">
          <span className="section-kicker">LEGACY ANALYSIS TRACE V1 VIEWER</span>
          <h2>Diagnostic viewer for historical sidecars</h2>
          <p>
            Requires an <strong>AnalysisTraceV1</strong> sidecar. ReplayV1 may be supplied only for identity
            binding.
          </p>
          <p>
            Saved games are listed on the <Link href="/">Games</Link> page and open in the replay viewer;
            finished reviews are AnalysisTraceV2 bundles opened by <Link href="/review">Review</Link>.
          </p>
        </section>
      ) : null}

      {trace && frame ? (
        <>
          <section className="workspace">
            <div className="board-panel">
              <div className="panel-heading">
                <div>
                  <span className="section-kicker">POSITION</span>
                  <h2>Decision board</h2>
                </div>
                <div className="view-switch" role="group" aria-label="Information perspective">
                  <button className={!reveal ? "active" : ""} onClick={() => setReveal(false)}>
                    Player view
                  </button>
                  <button className={reveal ? "active reveal-active" : ""} onClick={() => setReveal(true)}>
                    Referee reveal
                  </button>
                </div>
              </div>
              <BoardSurface frame={frame} cards={cards} nobles={nobles} reveal={reveal} />
            </div>
            <aside className="analysis-panel">
              <div className="analysis-header">
                <div>
                  <span className="section-kicker">ACTION ANALYSIS</span>
                  <h2>{trace.analyzer_label}</h2>
                </div>
                <span className="budget">
                  {trace.config.simulations} sims · d{trace.config.max_depth_turns} · c
                  {(trace.config.puct_exploration_milli / 1000).toFixed(3)}
                </span>
              </div>
              <div className="legend">
                <span>
                  <i className="actual-marker">★</i> actual
                </span>
                <span>
                  <i className="best-marker">▲</i> search best
                </span>
              </div>
              <div className="analysis-table" role="table" aria-label="Root action analysis">
                <div className="analysis-row table-head" role="row">
                  <span>Action</span>
                  <span>Prior</span>
                  <span>Visit</span>
                  <span>Q(P{frame.actor})</span>
                  <span>ΔQ</span>
                </div>
                {rows.map((row) => {
                  const delta = row.q != null && bestQ != null ? row.q - bestQ : null;
                  return (
                    <div
                      className={`analysis-row ${row.actual ? "actual-row" : ""} ${row.best ? "best-row" : ""}`}
                      role="row"
                      key={actionKey(row.action)}
                    >
                      <span className="action-name">
                        <i>{row.actual ? "★" : row.best ? "▲" : ""}</i>
                        {formatAction(row.action, frame, cards)}
                      </span>
                      <MetricBar value={row.prior} tone="prior" />
                      <MetricBar value={row.visit} tone="visit" />
                      <span className="q-value">{row.q == null ? "—" : row.q.toFixed(3)}</span>
                      <span className={`delta ${delta === 0 ? "best" : ""}`}>
                        {delta == null ? "—" : delta === 0 ? "BEST" : delta.toFixed(3)}
                      </span>
                    </div>
                  );
                })}
              </div>
              <div className="decision-summary">
                <span className={frame.recommended_matches_recorded ? "match" : "mismatch"}>
                  {frame.recommended_matches_recorded ? "SEARCH AGREED" : "SEARCH DISAGREED"}
                </span>
                <p>
                  Played <strong>{formatAction(frame.recorded_action, frame, cards)}</strong>
                </p>
                <p>
                  Recommended{" "}
                  <strong>{formatAction(frame.neural_result.action, frame, cards)}</strong>
                </p>
              </div>
              <dl className="trace-meta">
                <div>
                  <dt>Information set</dt>
                  <dd>{shortHash(frame.information_set_hash)}</dd>
                </div>
                <div>
                  <dt>Observation</dt>
                  <dd>{shortHash(frame.observation_hash)}</dd>
                </div>
                <div>
                  <dt>Checkpoint</dt>
                  <dd>{shortHash(trace.checkpoint_hash)}</dd>
                </div>
                <div>
                  <dt>Tree nodes</dt>
                  <dd>{frame.neural_result.stats.tree_nodes}</dd>
                </div>
              </dl>
            </aside>
          </section>

          <ReplayTimeline
            frames={trace.frames}
            frameIndex={frameIndex}
            onSeek={changeFrame}
            isCandidatePly={(item) =>
              trace.frames.find((candidate) => candidate.ply === item.ply)?.recommended_matches_recorded ?? false
            }
            title="← → keyboard navigation"
            footnote="agreement coloring"
          />
        </>
      ) : null}
    </main>
  );
}

function MetricBar({ value, tone }: { value: number; tone: "prior" | "visit" }) {
  return (
    <span className="metric">
      <span>{(value * 100).toFixed(1)}%</span>
      <i>
        <b className={tone} style={{ width: `${Math.min(100, value * 100)}%` }} />
      </i>
    </span>
  );
}
