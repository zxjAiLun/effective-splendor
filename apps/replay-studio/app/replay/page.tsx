"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  BoardSurface,
  ReplayTimeline,
  simpleActionLabel,
  usePlyNavigation,
  type Action,
  type BoardFrame,
  type CardId,
  type NobleId,
  type PlayerId,
} from "../components/replay-board";
import { type DevelopmentCardData } from "../development-card";

const API = "http://127.0.0.1:43120";

type ArchiveFrame = {
  ply: number;
  actor: PlayerId;
  player_view: BoardFrame["player_view"];
  legal_actions: Action[];
  recorded_action: Action;
  referee_reveal: BoardFrame["referee_reveal"];
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
  const [reveal, setReveal] = useState(false);
  const [filter, setFilter] = useState<"mine" | "all">("all");
  const [frameIndex, setFrameIndex] = useState(0);

  useEffect(() => {
    queueMicrotask(() =>
      void (async () => {
        const session = new URLSearchParams(window.location.search).get("session") ?? "";
        if (!session) {
          setError("Missing session id in the replay URL.");
          return;
        }
        try {
          const response = await fetch(`${API}/replays/${encodeURIComponent(session)}`);
          const value = await response.json();
          if (!response.ok) throw new Error(value.error ?? `Studio Host ${response.status}`);
          const next = value as ReplayArchive;
          if (!Array.isArray(next.frames) || next.frames.length === 0) {
            throw new Error("This replay produced no decision frames.");
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
          <Link className="studio-link" href="/play">
            Play vs S3
          </Link>
          {archive ? (
            <Link
              className="studio-link"
              href={`/review?session=${encodeURIComponent(archive.session_id)}${seat === null ? "" : `&seat=${seat}`}`}
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
              <BoardSurface frame={frame} cards={cards} nobles={nobles} reveal={reveal} />
            </div>
            <aside className="analysis-panel">
              <div className="analysis-header">
                <div>
                  <span className="section-kicker">RECORDED ACTION</span>
                  <h2>{simpleActionLabel(frame.recorded_action)}</h2>
                </div>
                <span className="budget">{archive.player_count}-player · verified ReplayV1</span>
              </div>
              <div className="decision-summary">
                <span>REPLAY VIEWER · NO ANALYSIS</span>
                <p>
                  Actor <strong>Player {frame.actor}</strong>
                </p>
                <p>
                  Action <strong>{simpleActionLabel(frame.recorded_action)}</strong>
                </p>
                <p>
                  Final score <strong>{scores.join(" – ") || "—"}</strong>
                </p>
              </div>
              <div className="human-audit-action" style={{ marginTop: "14px" }}>
                <small>Chosen from {frame.legal_actions.length} canonical legal actions</small>
                <code>{JSON.stringify(frame.recorded_action, null, 2)}</code>
              </div>
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
