"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { StudioGlyph, StudioHeader, StudioIntro } from "../components/studio-chrome";
import { API_BASE } from "../api-base.mjs";
import { visibleParticipant } from "../agent-visibility.mjs";
import {
  describeLeaderboard,
  describeReadFailure,
  LEADERBOARD_READ_TIMEOUT_MS,
  READ_REFUSED,
} from "../league-runtime.mjs";
import {
  describeKind,
  eloText,
  gamesText,
  provisionalText,
  recordText,
} from "../ratings-runtime.mjs";

/**
 * D2 — the `/ratings` product page: the Studio League's own current standings.
 *
 * This page is a client of the closed Studio League authority and never a
 * second one: it reads `GET /league/leaderboard` and renders what came back.
 * It does not rate anything, does not merge corpora, and has no concept of the
 * research reports' Batch BT official Elo — that is a different corpus under
 * `/ratings/reports`, and the two must stay visibly separate so a reader who
 * sees two 1900s does not take them for one system.
 *
 * Server render can only ever show the checking state. No rating is claimed
 * before a read returned one: an unread table renders "loading", never 1500.
 */

type LeaderRow = {
  participantId: string | null;
  kind: string | null;
  displayName: string | null;
  elo: number | null;
  ratedGames: number | null;
  recordedGames: number | null;
  ratedWins: number | null;
  ratedTies: number | null;
  ratedLosses: number | null;
  provisional: boolean | null;
};

/**
 * Read one JSON document, with a read budget.
 *
 * Mirrors the League Play page's helper: a refused read is tagged so a 503 from
 * a stale league is reported as the Host answering "no", not as a dead Host.
 */
async function readJson(path: string, timeoutMs: number) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
  const value = await response.json().catch(() => null);
  if (!response.ok) {
    const refused = new Error(value?.error ?? `Studio Host ${response.status}`) as Error & {
      readKind?: string;
    };
    refused.readKind = READ_REFUSED;
    throw refused;
  }
  return value;
}

export default function RatingsPage() {
  const [rows, setRows] = useState<LeaderRow[]>([]);
  const [phase, setPhase] = useState<"checking" | "ok" | "failed">("checking");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setPhase("checking");
    try {
      const body = await readJson("/league/leaderboard", LEADERBOARD_READ_TIMEOUT_MS);
      setRows((describeLeaderboard(body.rows) as LeaderRow[]).filter(visibleParticipant));
      setPhase("ok");
    } catch (reason) {
      setMessage(describeReadFailure(reason, LEADERBOARD_READ_TIMEOUT_MS).message);
      setPhase("failed");
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => void load());
  }, [load]);

  return (
    <main className="studio studio-page standings-page">
      <StudioHeader active="ratings" />
      <div className="studio-content">
      <section className="ratings-head">
        <StudioIntro eyebrow="STUDIO LEAGUE · CURRENT STANDINGS" title="Every match leaves a mark." action={<Link className="studio-button" href="/league">League Play<StudioGlyph name="arrow" /></Link>}>
          <p>The Studio League&apos;s own Elo table, read from the league ledger. Every participant enters at the same initial rating and moves only by matches the league recorded — human and engine seats alike.</p>
        </StudioIntro>
        <p className="ratings-note" role="note">
          This is <strong>not</strong> the research reports&apos; rating. The research corpus is a
          different rating system, kept unchanged under{" "}
          <Link href="/ratings/reports">Research reports</Link> — a rating there and a rating here
          are never the same scale.
        </p>
      </section>

      {phase === "checking" ? (
        <p className="ratings-state">Loading the standings from the Studio Host…</p>
      ) : null}
      {phase === "failed" ? (
        <div className="error-banner" role="alert">
          The league could not be read: {message}. The Host serves it from{" "}
          <code>{"<project-root>/local-artifacts/studio-league/league.sqlite3"}</code>.{" "}
          <button type="button" onClick={() => void load()}>
            Try again
          </button>
        </div>
      ) : null}
      {phase === "ok" && rows.length === 0 ? (
        <p className="ratings-state">No participants are recorded in the league yet.</p>
      ) : null}

      {phase === "ok" && rows.length > 0 ? (
        <section className="ratings-panel">
          <div className="ratings-table">
            <div className="ratings-row ratings-head-row">
              <span>Rank / Participant</span>
              <span>Kind</span>
              <span>W-T-L</span>
              <span>Games</span>
              <span>Elo</span>
            </div>
            {rows.map((row, index) => {
              const hasValidId =
                typeof row.participantId === "string" && row.participantId.length > 0;
              const nameText = row.displayName ?? row.participantId ?? "Unknown participant";
              const totalGames = row.ratedGames ?? 0;
              const winRate = totalGames > 0 ? Math.round(((row.ratedWins ?? 0) / totalGames) * 100) : null;
              return (
                <div className="ratings-row" key={row.participantId ?? `row-${index}`}>
                  <span>
                    <b data-rank={index + 1}>{index + 1}</b>
                    <i>
                      {hasValidId ? (
                        <Link
                          href={`/ratings/${encodeURIComponent(row.participantId!)}`}
                          className="profile-opponent-name"
                        >
                          {nameText}
                        </Link>
                      ) : (
                        nameText
                      )}
                      <small>
                        {row.participantId ?? "no participant id"}
                        {provisionalText(row) ? " · provisional" : ""}
                      </small>
                    </i>
                  </span>
                  <span data-label="Kind">
                    <span className={`kind-pill kind-${row.kind ?? "unknown"}`}>
                      {describeKind(row.kind) ?? "—"}
                    </span>
                  </span>
                  <span data-label="W-T-L">
                    <span className="record-line">{recordText(row)}</span>
                    {winRate !== null ? (
                      <i className="win-rate-track" title={`${winRate}% win rate`}>
                        <b style={{ width: `${winRate}%` }} />
                      </i>
                    ) : null}
                  </span>
                  <span data-label="Games">{gamesText(row)}</span>
                  <span className="ratings-elo">{eloText(row)}</span>
                </div>
              );
            })}
          </div>
          <p className="ratings-footnote">
            Only the curated participants are shown; their Elo and game counts remain the ledger&apos;s
            recorded values. Display positions are within this subset, not historical league ranks.
          </p>
        </section>
      ) : null}
      </div>
    </main>
  );
}
