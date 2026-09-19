"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { API_BASE as API } from "./api-base.mjs";
import { describeGameRow } from "./games-runtime.mjs";
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

type RecentGame = {
  session_id: string;
  opponent?: string | null;
  human_seat?: number | null;
  scores?: number[];
  winners?: number[];
  player_count?: number;
  timestamp?: number | null;
  verification?: "verified" | "invalid";
  available_reviews?: string[];
  error?: string;
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
    return page;
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
    <section className="recent-games">
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
        <p>No matches are recorded in the league yet.</p>
      ) : null}
      <div className="recent-game-list">
        {rows.map((row) => (
          <article key={row.matchId ?? `seq-${row.leagueSeq}`}>
            <div>
              <strong>{when(row.playedAt)}</strong>
              <small>
                {row.leagueSeq === null ? "position unknown" : `league position ${row.leagueSeq}`} ·{" "}
                {row.sourceKind ?? "unknown source"} · {row.status ?? "unknown status"}
              </small>
              <small>
                {row.seats.length === 0
                  ? "no seats recorded"
                  : row.seats
                      .map((seat) =>
                        `${seat.label}${seat.rank === null ? "" : ` (rank ${seat.rank})`}`,
                      )
                      .join(" · ")}
              </small>
              {row.ratingEligible ? (
                <small>Rated · Elo moved for both seats.</small>
              ) : (
                <small>
                  Not rated{row.ineligibleReason ? ` · ${row.ineligibleReason}` : ""}
                </small>
              )}
            </div>
            <div>
              <span>{row.outcome}</span>
              <small>{row.scoreLine}</small>
              {row.replayHref ? (
                <Link href={row.replayHref}>Open replay</Link>
              ) : (
                <small>{row.replayUnavailableReason}</small>
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

/**
 * The legacy standalone history.
 *
 * This is a *different* corpus from the league ledger: human-vs-engine games the
 * old console/`/play` path wrote to `local-artifacts/m20-human-play`, which the
 * Host serves from disk. It is kept visible rather than merged, because folding it
 * into the league list would claim games for the league that the league never
 * recorded — and would present an unrecorded exhibition as a rated match.
 */
function LegacyGames() {
  const [games, setGames] = useState<RecentGame[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    queueMicrotask(() =>
      void (async () => {
        try {
          const response = await fetch(`${API}/recent-games`);
          const value = await response.json();
          if (!response.ok) throw new Error(value.error ?? `Studio Host ${response.status}`);
          setGames((value.games ?? []) as RecentGame[]);
          setError("");
        } catch (reason) {
          setError(reason instanceof Error ? reason.message : String(reason));
        } finally {
          setLoading(false);
        }
      })(),
    );
  }, []);

  return (
    <section className="recent-games legacy-games">
      <span className="section-kicker">LOCAL / LEGACY GAMES</span>
      <h2>Saved human vs engine games</h2>
      <p>
        Games saved on this machine before the Studio League record. These are not league matches
        unless they also appear above.
      </p>
      {error ? (
        <p role="alert" className="games-error">
          {error}
        </p>
      ) : null}
      {loading ? <p>Loading games…</p> : null}
      {!loading && !error && games.length === 0 ? (
        <p>No saved games yet. Start one from Play vs S3.</p>
      ) : null}
      <div className="recent-game-list">
        {games.map((game) => {
          const row = describeGameRow(game);
          const cached = game.available_reviews?.length ?? 0;
          return (
            <article key={game.session_id}>
              <div>
                <strong>{when(game.timestamp)}</strong>
                <small>{game.session_id}</small>
                <small>
                  vs {game.opponent ?? "unknown opponent"} · {row.seatLabel} ·{" "}
                  {game.player_count ?? "?"}-player ·{" "}
                  {row.verified ? "verified" : game.error ?? "invalid"} · {cached} cached review
                  {cached === 1 ? "" : "s"}
                </small>
              </div>
              <div>
                <span>{row.outcome}</span>
                <small>{row.scoreLine}</small>
                {row.verified ? (
                  <>
                    <Link href={row.replayHref}>View replay</Link>
                    <Link href={row.reviewHref}>Review</Link>
                  </>
                ) : null}
              </div>
            </article>
          );
        })}
      </div>
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
            `Studio Host is not running. Launch the project once with Start Splendor Studio.cmd. ${
              reason instanceof Error ? reason.message : String(reason)
            }`,
          );
        }
      })(),
    );
  }, []);

  return (
    <main className="studio">
      <header className="topbar">
        <div className="brand-block">
          <span className="eyebrow">EFFECTIVE SPLENDOR · REPLAY STUDIO</span>
          <h1>Replay Studio</h1>
        </div>
        <div className="header-actions">
          <Link className="studio-link" href="/play">
            Play vs S3
          </Link>
          <Link className="studio-link" href="/league">
            League
          </Link>
          <Link className="studio-link" href="/ratings">
            Ratings
          </Link>
          <Link className="studio-link" href="/ratings/reports">
            Research reports
          </Link>
          <Link className="studio-link" href="/advanced">
            Legacy AnalysisTraceV1 viewer
          </Link>
        </div>
      </header>

      {hostError ? (
        <div className="error-banner" role="alert">
          {hostError}
        </div>
      ) : null}

      <StudioLeagueGames />
      <LegacyGames />
    </main>
  );
}

export const GAMES_PAGE_LIMIT_CEILING = GAMES_PAGE_MAX_LIMIT;
