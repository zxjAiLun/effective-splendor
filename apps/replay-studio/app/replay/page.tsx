"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { API_BASE as API } from "../api-base.mjs";
import {
  BoardSurface,
  ReplayTimeline,
  usePlyNavigation,
  type Action,
  type BoardFrame,
  type CardId,
  type NobleId,
  type PlayerId,
} from "../components/replay-board";
import { visibleParticipant } from "../agent-visibility.mjs";
import { PlayerStateStrip } from "../components/player-state-strip";
import { StructuredAction, type ActionCatalog, type ActionPlayerView } from "../components/structured-action";
import { JevInteractionPanel, type StepView } from "../components/jev-interaction-panel";
import { describeStep } from "../jev-trace-runtime.mjs";
import { type DevelopmentCardData } from "../development-card";

type ArchiveFrame = {
  ply: number;
  actor: PlayerId;
  player_view: BoardFrame["player_view"];
  legal_actions: Action[];
  recorded_action: Action;
  referee_reveal: BoardFrame["referee_reveal"];
  observation_hash?: string;
};

type JevTraceBundle = {
  format?: string;
  version?: number;
  run_id?: string;
  config?: { agents?: Array<{ program?: string; args?: string[] }> };
  trace?: {
    decisions?: Record<string, unknown>;
    journal_recorded?: boolean;
    game_document?: string;
    game_plies?: number | null;
  } | null;
};

type ReplayArchive = {
  format: string;
  version: number;
  session_id: string;
  opponent: string | null;
  human_seat: number | null;
  player_count: number;
  replay_document_hash: string;
  replay: { result: { scores: number[]; ranks: number[]; winners: PlayerId[]; reason: string } };
  frames: ArchiveFrame[];
  catalog: {
    cards: Array<DevelopmentCardData & { id: CardId }>;
    nobles: Array<{ id: NobleId; prestige: number; requirements: number[] }>;
  };
};

export default function ReplayPage() {
  const [archive, setArchive] = useState<ReplayArchive | null>(null);
  const [error, setError] = useState("");
  /**
   * `true` when this board was opened by content address (`?league=<sha256>`).
   *
   * A league replay has no human session behind it, so the human-only actions
   * ("mine" filtering, "Review this game") are not offered for it.
   */
  const [leagueSource, setLeagueSource] = useState(false);
  const [reveal, setReveal] = useState(false);
  const [filter, setFilter] = useState<"mine" | "all">("all");
  const [frameIndex, setFrameIndex] = useState(0);
  /**
   * The optional local Jev interaction trace for this session (`?jev=<run_id>`).
   *
   * `undefined` means the query parameter was absent (no panel is offered at
   * all); `null` means it was requested but could not be read, which is shown as
   * unavailable rather than as "this run made no calls".
   */
  const [jevTrace, setJevTrace] = useState<JevTraceBundle | null | undefined>(undefined);

  useEffect(() => {
    queueMicrotask(() =>
      void (async () => {
        const params = new URLSearchParams(window.location.search);
        const session = params.get("session") ?? "";
        const league = params.get("league") ?? "";
        if (!session && !league) {
          setError("Missing session id or league content hash in the replay URL.");
          return;
        }
        try {
          // A league match is addressed by the content hash of its verified
          // replay and read through the League reader's own authority: the
          // route refuses a stale league and reports an unknown address as
          // absent, exactly like every other league read.
          const url = league
            ? `${API}/league/replays/${encodeURIComponent(league)}/archive`
            : `${API}/replays/${encodeURIComponent(session)}`;
          setLeagueSource(Boolean(league));
          const response = await fetch(url);
          const value = await response.json();
          if (!response.ok) throw new Error(value.error ?? `Studio Host ${response.status}`);
          const next = value as ReplayArchive;
          if (!Array.isArray(next.frames) || next.frames.length === 0) {
            throw new Error("This replay produced no decision frames.");
          }
          if (next.opponent && !visibleParticipant({ displayName: next.opponent, participantId: next.opponent })) {
            throw new Error("This replay is not in the current Studio lineup.");
          }
          setArchive(next);
          setFrameIndex(0);
          setReveal(false);
          setFilter("all");
          setError("");
        } catch (reason) {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      })(),
    );
  }, []);

  useEffect(() => {
    queueMicrotask(() =>
      void (async () => {
        const params = new URLSearchParams(window.location.search);
        const jev = params.get("jev") ?? "";
        if (!jev) {
          setJevTrace(undefined);
          return;
        }
        try {
          // Read-only: this route serves the run's own journal projection and its
          // verified game document. It never runs the agent or a reviewer.
          const response = await fetch(`${API}/jev/runs/${encodeURIComponent(jev)}`);
          const value = await response.json();
          if (!response.ok) throw new Error(value.error ?? `Studio Host ${response.status}`);
          setJevTrace(value as JevTraceBundle);
        } catch {
          // A missing or unreadable trace must not hide the replay itself; the
          // panel reports the absence instead.
          setJevTrace(null);
        }
      })(),
    );
  }, []);

  const cards = useMemo(
    () => new Map((archive?.catalog.cards ?? []).map((card) => [card.id, card])),
    [archive],
  );
  const nobles = useMemo(
    () => new Map((archive?.catalog.nobles ?? []).map((noble) => [noble.id, noble])),
    [archive],
  );

  const frames = useMemo(() => {
    if (!archive) return [];
    if (filter === "all" || archive.human_seat === null) return archive.frames;
    return archive.frames.filter((frame) => frame.actor === archive.human_seat);
  }, [archive, filter]);

  const frame = frames[Math.min(frameIndex, frames.length - 1)] ?? null;
  const changeFrame = (next: number) =>
    setFrameIndex(Math.max(0, Math.min(frames.length - 1, next)));

  usePlyNavigation(frames.length, (delta) => {
    setFrameIndex((current) => Math.max(0, Math.min(frames.length - 1, current + delta)));
  });

  useEffect(() => {
    const timeline = document.querySelector<HTMLElement>(".timeline");
    const activeBtn = document.querySelector<HTMLElement>(".timeline button.current");
    if (timeline && activeBtn) {
      const targetLeft = activeBtn.offsetLeft - timeline.clientWidth / 2 + activeBtn.clientWidth / 2;
      timeline.scrollTo({ left: targetLeft, behavior: "smooth" });
    }
  }, [frameIndex]);

  const seat = archive?.human_seat ?? null;
  const scores = archive?.replay.result?.scores ?? [];

  return (
    <main className="studio">
      <header className="topbar">
        <div className="brand-block">
          <span className="eyebrow">VERIFIED REPLAY · NO ANALYSIS</span>
          <h1>Replay Studio</h1>
        </div>
        <div className="match-meta">
          <span className="status-dot" aria-hidden="true" />
          <span>{archive?.session_id ?? "loading…"}</span>
          <span className="meta-separator">/</span>
          <span>{archive?.opponent ?? "—"}</span>
          <span className="meta-separator">/</span>
          <span>{scores.length ? scores.join(" – ") : "—"}</span>
          <span className="meta-separator">/</span>
          <span>Ply {frame?.ply ?? 0}</span>
        </div>
        <div className="header-actions">
          <Link className="studio-link" href="/">
            Games
          </Link>
          <Link className="studio-link" href="/jev" style={{ color: "#38bdf8", fontWeight: 700 }}>
            Jev Replay
          </Link>
          <Link className="studio-link" href="/play">
            Play vs S3
          </Link>
          {archive && !leagueSource ? (
            <Link
              className="studio-link"
              // No seat: the review reads the authoritative human seat from durable
              // session metadata, so the URL must not carry a second opinion.
              href={`/review?session=${encodeURIComponent(archive.session_id)}`}
            >
              Review this game
            </Link>
          ) : null}
          <button
            className="icon-button"
            onClick={() => changeFrame(frameIndex - 1)}
            disabled={frameIndex === 0}
            aria-label="Previous ply"
          >
            ←
          </button>
          <button
            className="icon-button"
            onClick={() => changeFrame(frameIndex + 1)}
            disabled={frameIndex >= frames.length - 1}
            aria-label="Next ply"
          >
            →
          </button>
        </div>
      </header>

      {error ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}

      {!archive && !error ? (
        <div className="review-progress">
          <span className="section-kicker">LOADING</span>
          <h2>Rebuilding the replay</h2>
          <p>Reading and verifying the ReplayV1, then reconstructing every decision. No reviewer runs.</p>
        </div>
      ) : null}

      {archive && frame ? (
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
              {reveal ? (
                <div className="reveal-warning">
                  <span>REFEREE ONLY</span>
                  Hidden reserves and future deck order are visible. Do not use this view to judge what P
                  {frame.actor} knew.
                </div>
              ) : null}
              <PlayerStateStrip playerView={frame.player_view} actor={frame.actor} humanSeat={seat} />
              <BoardSurface frame={frame} cards={cards} nobles={nobles} reveal={reveal} />
            </div>
            <aside className="analysis-panel">
              <div className="analysis-header">
                <div>
                  <span className="section-kicker">RECORDED ACTION</span>
                  <h2>Player {frame.actor}</h2>
                </div>
                <span className="budget">{archive.player_count}-player · verified ReplayV1</span>
              </div>
              {/* The structured action is the product view. The raw enum stays
                  available, but folded away: it is diagnostics, not the thing a
                  reader came to the replay to understand. */}
              <StructuredAction
                action={frame.recorded_action}
                playerView={frame.player_view as ActionPlayerView}
                cards={cards as ActionCatalog["cards"]}
                nobles={nobles as ActionCatalog["nobles"]}
              />
              {jevTrace === undefined ? null : (
                <JevInteractionPanel step={describeStep(frame, jevTrace) as StepView} />
              )}
              <div className="decision-summary">
                <span>REPLAY VIEWER · NO ANALYSIS</span>
                <p>
                  Final score <strong>{scores.join(" – ") || "—"}</strong>
                </p>
                <p>
                  Chosen from <strong>{frame.legal_actions.length}</strong> canonical legal actions
                </p>
              </div>
              <details className="action-raw">
                <summary>Show raw action</summary>
                <code>{JSON.stringify(frame.recorded_action, null, 2)}</code>
              </details>
            </aside>
          </section>

          <footer className="timeline-panel">
            <div className="timeline-title">
              <div>
                <span className="section-kicker">TIMELINE</span>
                <strong>
                  {frameIndex + 1} / {frames.length}
                </strong>
                {seat === null ? null : (
                  <span className="review-filter" role="group" aria-label="Decision filter">
                    <button
                      className={filter === "mine" ? "active" : ""}
                      onClick={() => {
                        setFilter("mine");
                        setFrameIndex(0);
                      }}
                    >
                      My decisions
                    </button>
                    <button
                      className={filter === "all" ? "active" : ""}
                      onClick={() => {
                        setFilter("all");
                        setFrameIndex(0);
                      }}
                    >
                      All decisions
                    </button>
                  </span>
                )}
              </div>
              <span>← → keyboard navigation</span>
            </div>
            <ReplayTimeline
              frames={frames}
              frameIndex={frameIndex}
              onSeek={changeFrame}
              title="player-view replay"
              footnote="recorded actions"
            />
          </footer>
        </>
      ) : null}
    </main>
  );
}
