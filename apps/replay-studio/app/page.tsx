"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { StudioGlyph, StudioHeader, StudioIntro, StudioTableArt } from "./components/studio-chrome";
import { API_BASE as API } from "./api-base.mjs";
import { visibleGame } from "./agent-visibility.mjs";
import {
  GAMES_PAGE_DEFAULT_LIMIT,
  GAMES_PAGE_MAX_LIMIT,
  clampGamesLimit,
  describeGamesPage,
  nextGamesQuery,
} from "./games-page-runtime.mjs";

type LeagueSeatRow = {
  seat: number | null;
  participantId: string | null;
  displayName: string | null;
  label: string;
  score: number | null;
  rank: number | null;
  won: boolean;
};

type LeagueGameRow = {
  matchId: string | null;
  leagueSeq: number | null;
  playedAt: number | null;
  sourceKind: string | null;
  status: string | null;
  ratingEligible: boolean;
  ineligibleReason: string | null;
  seats: LeagueSeatRow[];
  scoreLine: string;
  outcome: string;
  winnerLabels: string[];
  replayHref: string | null;
  replaySha: string | null;
  replayUnavailableReason: string | null;
};

function when(timestamp?: number | null): string {
  if (!timestamp) return "unknown time";
  return new Date(timestamp * 1000).toLocaleString();
}

/**
 * The league Games list, one bounded page at a time.
 *
 * The whole list is never fetched: the official league holds tens of thousands of
 * matches, and the Host answers requests serially. Paging is by the cursor the
 * Host returns, never by an offset this page computes, so a match recorded while
 * the reader is scrolling cannot make page 2 skip or repeat a row.
 *
 * "Load more" is offered only when the Host said there is a next cursor. A page
 * that happens to come back short is not evidence of the end of the recording, and
 * an empty page is still a truthful answer: it is rendered, not hidden.
 */
function StudioLeagueGames() {
  const [rows, setRows] = useState<LeagueGameRow[]>([]);
  const [nextQuery, setNextQuery] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);

  const readPage = async (query: string | null) => {
    const suffix = query ? `?${query}` : "";
    const response = await fetch(`${API}/league/games${suffix}`);
    const value = await response.json();
    if (!response.ok) throw new Error(value.error ?? `Studio Host ${response.status}`);
    const page = describeGamesPage(value) as {
      rows: LeagueGameRow[];
      nextBeforeLeagueSeq: number | null;
      atEnd: boolean;
      invalid: boolean;
    };
    if (page.invalid) throw new Error("Studio Host returned an invalid games page.");
    return { ...page, rows: page.rows.filter(visibleGame) };
  };

  useEffect(() => {
    queueMicrotask(() =>
      void (async () => {
        try {
          const page = await readPage(null);
          setRows(page.rows);
          setNextQuery(
            page.nextBeforeLeagueSeq === null
              ? null
              : nextGamesQuery(page.nextBeforeLeagueSeq, GAMES_PAGE_DEFAULT_LIMIT),
          );
          setError("");
        } catch (reason) {
          setError(reason instanceof Error ? reason.message : String(reason));
        } finally {
          setLoading(false);
        }
      })(),
    );
  }, []);

  const loadMore = () => {
    if (!nextQuery || loadingMore) return;
    setLoadingMore(true);
    void (async () => {
      try {
        const page = await readPage(nextQuery);
        // Append-only: a later page can never displace a row the reader has
        // already seen, because the cursor only walks downwards.
        setRows((current) => [...current, ...page.rows]);
        setNextQuery(
          page.nextBeforeLeagueSeq === null
            ? null
            : nextGamesQuery(page.nextBeforeLeagueSeq, clampGamesLimit(GAMES_PAGE_DEFAULT_LIMIT)),
        );
        setError("");
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : String(reason));
      } finally {
        setLoadingMore(false);
      }
    })();
  };

  const retryQuery = error ? (rows.length > 0 ? nextQuery : null) : null;

  return (
    <section className="recent-games games-ledger">
      <span className="section-kicker">STUDIO LEAGUE GAMES</span>
      <h2>Long-term league record</h2>
      <p>
        Every match the Studio League ledger recorded, newest first. Paged by league position, so
        scrolling stays stable while new matches are being booked.
      </p>
      {error ? (
        <div className="games-error" role="alert">
          <p>{error}</p>
          <button
            type="button"
            className="games-more"
            onClick={rows.length > 0 ? loadMore : () => window.location.reload()}
            disabled={loadingMore}
          >
            {loadingMore ? "Retrying…" : rows.length > 0 && retryQuery ? "Retry page" : "Retry"}
          </button>
        </div>
      ) : null}
      {loading ? <p>Loading league games…</p> : null}
      {!loading && !error && rows.length === 0 ? (
        <div className="studio-empty-card">
          <p>No matches are recorded in the league yet.</p>
          <small>Start a rated match in Play or League to record the first official game and replay.</small>
        </div>
      ) : null}
      <div className="recent-game-list">
        {rows.map((row) => (
          <article key={row.matchId ?? `seq-${row.leagueSeq}`} className="league-game-card">
            <div className="game-card-main">
              <div className="game-card-header">
                <strong>{when(row.playedAt)}</strong>
                <span className={`game-badge ${row.ratingEligible ? "rated" : "unrated"}`}>
                  {row.ratingEligible ? "Rated · Elo moved for both seats." : `Not rated${row.ineligibleReason ? ` · ${row.ineligibleReason}` : ""}`}
                </span>
              </div>
              <small className="game-card-meta">
                {row.leagueSeq === null ? "position unknown" : `league position ${row.leagueSeq}`} ·{" "}
                {row.sourceKind ?? "unknown source"} · {row.status ?? "unknown status"}
              </small>
              <small className="game-card-seats">
                {row.seats.length === 0
                  ? "no seats recorded"
                  : row.seats
                      .map((seat) =>
                        `${seat.label}${seat.rank === null ? "" : ` (rank ${seat.rank})`}`,
                      )
                      .join(" · ")}
              </small>
            </div>
            <div className="game-card-outcome">
              <span className="outcome-label">{row.outcome}</span>
              <span className="game-score-pill">{row.scoreLine}</span>
              {row.replayHref ? (
                <Link href={row.replayHref} className="studio-link game-replay-link">Open replay</Link>
              ) : (
                <small className="text-muted">{row.replayUnavailableReason}</small>
              )}
            </div>
          </article>
        ))}
      </div>
      {!loading && !error && nextQuery ? (
        <button type="button" className="games-more" onClick={loadMore} disabled={loadingMore}>
          {loadingMore ? "Loading…" : "Load more"}
        </button>
      ) : null}
      {!loading && !error && !nextQuery && rows.length > 0 ? (
        <p>End of the recorded league.</p>
      ) : null}
    </section>
  );
}

export default function GamesHome() {
  const [hostError, setHostError] = useState("");

  // The two sections read two different authorities, and a failure of one must
  // not be reported as a failure of the other; the only shared fact is whether the
  // Host is reachable at all.
  useEffect(() => {
    queueMicrotask(() =>
      void (async () => {
        try {
          const response = await fetch(`${API}/health`);
          if (!response.ok) throw new Error(`Studio Host ${response.status}`);
          setHostError("");
        } catch (reason) {
          setHostError(
            `Studio Host is not running. Launch the project once with Splendor Studio.cmd. ${
              reason instanceof Error ? reason.message : String(reason)
            }`,
          );
        }
      })(),
    );
  }, []);

  return (
    <main className="studio studio-page games-page">
      <StudioHeader active="games" />

      {hostError ? (
        <div className="error-banner" role="alert">
          {hostError}
        </div>
      ) : null}

      <div className="studio-content">
        <div className="games-welcome">
          <div>
            <StudioIntro eyebrow="WELCOME TO YOUR STUDIO" title="A seat at the table.">
              <p>Make your next move, revisit a great game, or follow the league. Your table and its history, in one place.</p>
            </StudioIntro>
            <div className="games-welcome-actions">
              <Link className="studio-button studio-primary" href="/play"><StudioGlyph name="play" />Play vs AI</Link>
              <Link className="studio-button" href="/ratings">View standings<StudioGlyph name="arrow" /></Link>
            </div>
          </div>
          <StudioTableArt />
        </div>
        <div className="games-dashboard">
          <StudioLeagueGames />
        </div>
      </div>
    </main>
  );
}

export const GAMES_PAGE_LIMIT_CEILING = GAMES_PAGE_MAX_LIMIT;
