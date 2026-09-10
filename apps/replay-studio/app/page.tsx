"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { describeGameRow } from "./games-runtime.mjs";

const API = "http://127.0.0.1:43120";

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

export default function GamesHome() {
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
          setError(
            `Studio Host is not running. Launch the project once with Start Splendor Studio.cmd. ${
              reason instanceof Error ? reason.message : String(reason)
            }`,
          );
        } finally {
          setLoading(false);
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
          <Link className="studio-link" href="/advanced">
            Legacy AnalysisTraceV1 viewer
          </Link>
        </div>
      </header>

      {error ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}

      <section className="recent-games">
        <span className="section-kicker">GAMES</span>
        <h2>Saved human vs engine games</h2>
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
                    {game.player_count ?? "?"}-player · {row.verified ? "verified" : game.error ?? "invalid"} ·{" "}
                    {cached} cached review{cached === 1 ? "" : "s"}
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
    </main>
  );
}
