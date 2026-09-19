"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { API_BASE } from "../../api-base.mjs";
import { describeGamesPage } from "../../games-page-runtime.mjs";
import { READ_REFUSED } from "../../league-runtime.mjs";
import {
  buildEloChartData,
  classifyProfileError,
  decodeOpponentsPage,
  decodeParticipantProfile,
  decodeRatingHistoryPage,
  describeCompletedPlies,
  describeProfileElo,
  describeProfileKind,
  describeRecordText,
  describeSeatsText,
  GAMES_DEFAULT_LIMIT,
  OPPONENTS_DEFAULT_LIMIT,
  PARTICIPANT_READ_TIMEOUT_MS,
  RATING_HISTORY_DEFAULT_LIMIT,
} from "../../participant-profile-runtime.mjs";

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
    const error = new Error(value?.error ?? `Studio Host ${response.status}`) as Error & {
      readKind?: string;
      status?: number;
    };
    error.status = response.status;
    if (response.status === 503 || response.status === 404 || response.status === 400) {
      error.readKind = READ_REFUSED;
    }
    throw error;
  }
  return value;
}

type TabKey = "overview" | "games" | "ratings" | "opponents";

type ProfileElo = {
  value: number;
  display_rounded: number;
  origin: "rated" | "initial";
};

type ProfileSeats = {
  appearances: number;
  seat0: number;
  seat1: number;
  other: number;
};

type ProfileCompletedPlies = {
  availability: "available" | "partial" | "unavailable";
  value: number | null;
  observed_completed_games: number;
  total_completed_games: number;
  unit: string;
};

type ProfileUnavailableMetric = {
  availability: string;
  reason: string;
};

type ProfileData = {
  participant_id: string;
  kind: "human" | "engine";
  display_name: string;
  elo: ProfileElo;
  provisional: boolean;
  recorded_games: number;
  rated_games: number;
  rated_wins: number;
  rated_ties: number;
  rated_losses: number;
  seats: ProfileSeats;
  completed_plies: ProfileCompletedPlies;
  main_turns: ProfileUnavailableMetric;
  gameplay: ProfileUnavailableMetric;
};

type RatingPoint = {
  participant_id: string;
  league_seq: number;
  match_id: string;
  elo_before: number;
  elo_after: number;
  delta: number;
  opponent_id: string;
  opponent_name: string;
  played_at: number | null;
};

type OpponentItem = {
  opponent_id: string;
  display_name: string;
  recorded_games: number;
  rated_games: number;
  rated_wins: number;
  rated_ties: number;
  rated_losses: number;
};

type GameItem = {
  matchId: string | null;
  leagueSeq: number | null;
  playedAt: number | null;
  sourceKind: string | null;
  status: string | null;
  ratingEligible: boolean;
  ineligibleReason: string | null;
  scoreLine: string;
  outcome: string;
  replayHref: string | null;
  replaySha: string | null;
};

type ClassifiedError = {
  kind: string;
  message: string;
};

export default function ParticipantProfilePage() {
  const params = useParams();
  const pathname = usePathname();

  const participantId = useMemo(() => {
    if (params && typeof params.participant_id === "string" && params.participant_id) {
      return decodeURIComponent(params.participant_id);
    }
    if (pathname) {
      const match = pathname.match(/\/ratings\/([^/?#]+)/);
      if (match) return decodeURIComponent(match[1]);
    }
    return "";
  }, [params, pathname]);

  const [activeTab, setActiveTab] = useState<TabKey>("overview");

  // Profile Section State (Loaded on mount ONLY)
  const [profileState, setProfileState] = useState<{
    phase: "idle" | "loading" | "ok" | "failed";
    data: ProfileData | null;
    error: ClassifiedError | null;
  }>({ phase: "idle", data: null, error: null });

  // Ratings History Section State (On-demand loaded, cached in session)
  const [ratingsState, setRatingsState] = useState<{
    phase: "idle" | "loading" | "ok" | "failed";
    points: RatingPoint[];
    nextBeforeLeagueSeq: number | null;
    atEnd: boolean;
    error: ClassifiedError | null;
    loadingMore: boolean;
  }>({
    phase: "idle",
    points: [],
    nextBeforeLeagueSeq: null,
    atEnd: false,
    error: null,
    loadingMore: false,
  });

  // Opponents Section State (On-demand loaded, cached in session)
  const [opponentsState, setOpponentsState] = useState<{
    phase: "idle" | "loading" | "ok" | "failed";
    opponents: OpponentItem[];
    nextAfterOpponentId: string | null;
    atEnd: boolean;
    error: ClassifiedError | null;
    loadingMore: boolean;
  }>({
    phase: "idle",
    opponents: [],
    nextAfterOpponentId: null,
    atEnd: false,
    error: null,
    loadingMore: false,
  });

  // Personal Games Section State (On-demand loaded, cached in session)
  const [gamesState, setGamesState] = useState<{
    phase: "idle" | "loading" | "ok" | "failed";
    matches: GameItem[];
    nextBeforeLeagueSeq: number | null;
    atEnd: boolean;
    error: ClassifiedError | null;
    loadingMore: boolean;
  }>({
    phase: "idle",
    matches: [],
    nextBeforeLeagueSeq: null,
    atEnd: false,
    error: null,
    loadingMore: false,
  });

  // 1. Mount: Load Profile ONLY. Never fan-out to other endpoints.
  const loadProfile = useCallback(async () => {
    if (!participantId) return;
    setProfileState((prev) => ({ ...prev, phase: "loading", error: null }));
    try {
      const body = await readJson(
        `/league/participants/${encodeURIComponent(participantId)}`,
        PARTICIPANT_READ_TIMEOUT_MS
      );
      const decoded = decodeParticipantProfile(body, participantId);
      if (!decoded.ok) {
        setProfileState({
          phase: "failed",
          data: null,
          error: { kind: "invalid", message: decoded.error },
        });
        return;
      }
      setProfileState({ phase: "ok", data: decoded.profile as ProfileData, error: null });
    } catch (err: unknown) {
      setProfileState({
        phase: "failed",
        data: null,
        error: classifyProfileError(err, PARTICIPANT_READ_TIMEOUT_MS),
      });
    }
  }, [participantId]);

  useEffect(() => {
    queueMicrotask(() => void loadProfile());
  }, [loadProfile]);

  // 2. Ratings on-demand loader & paginator
  const loadRatings = useCallback(async () => {
    if (!participantId) return;
    setRatingsState((prev) => ({ ...prev, phase: "loading", error: null }));
    try {
      const body = await readJson(
        `/league/participants/${encodeURIComponent(participantId)}/ratings?limit=${RATING_HISTORY_DEFAULT_LIMIT}`,
        PARTICIPANT_READ_TIMEOUT_MS
      );
      const decoded = decodeRatingHistoryPage(body, participantId);
      if (!decoded.ok) {
        setRatingsState({
          phase: "failed",
          points: [],
          nextBeforeLeagueSeq: null,
          atEnd: false,
          error: { kind: "invalid", message: decoded.error },
          loadingMore: false,
        });
        return;
      }
      setRatingsState({
        phase: "ok",
        points: decoded.points as RatingPoint[],
        nextBeforeLeagueSeq: decoded.nextBeforeLeagueSeq,
        atEnd: decoded.atEnd,
        error: null,
        loadingMore: false,
      });
    } catch (err: unknown) {
      setRatingsState({
        phase: "failed",
        points: [],
        nextBeforeLeagueSeq: null,
        atEnd: false,
        error: classifyProfileError(err, PARTICIPANT_READ_TIMEOUT_MS),
        loadingMore: false,
      });
    }
  }, [participantId]);

  const loadMoreRatings = useCallback(async () => {
    if (!participantId || !ratingsState.nextBeforeLeagueSeq || ratingsState.loadingMore) return;
    setRatingsState((prev) => ({ ...prev, loadingMore: true }));
    try {
      const body = await readJson(
        `/league/participants/${encodeURIComponent(participantId)}/ratings?limit=${RATING_HISTORY_DEFAULT_LIMIT}&before=${ratingsState.nextBeforeLeagueSeq}`,
        PARTICIPANT_READ_TIMEOUT_MS
      );
      const decoded = decodeRatingHistoryPage(body, participantId);
      if (!decoded.ok) {
        setRatingsState((prev) => ({
          ...prev,
          loadingMore: false,
          error: { kind: "invalid", message: decoded.error },
        }));
        return;
      }
      setRatingsState((prev) => {
        const existingSeqs = new Set(prev.points.map((p) => p.league_seq));
        const newPoints = (decoded.points as RatingPoint[]).filter((p) => !existingSeqs.has(p.league_seq));
        return {
          ...prev,
          points: [...prev.points, ...newPoints],
          nextBeforeLeagueSeq: decoded.nextBeforeLeagueSeq,
          atEnd: decoded.atEnd,
          loadingMore: false,
          error: null,
        };
      });
    } catch (err: unknown) {
      setRatingsState((prev) => ({
        ...prev,
        loadingMore: false,
        error: classifyProfileError(err, PARTICIPANT_READ_TIMEOUT_MS),
      }));
    }
  }, [participantId, ratingsState.nextBeforeLeagueSeq, ratingsState.loadingMore]);

  // 3. Opponents on-demand loader & paginator
  const loadOpponents = useCallback(async () => {
    if (!participantId) return;
    setOpponentsState((prev) => ({ ...prev, phase: "loading", error: null }));
    try {
      const body = await readJson(
        `/league/participants/${encodeURIComponent(participantId)}/opponents?limit=${OPPONENTS_DEFAULT_LIMIT}`,
        PARTICIPANT_READ_TIMEOUT_MS
      );
      const decoded = decodeOpponentsPage(body, participantId);
      if (!decoded.ok) {
        setOpponentsState({
          phase: "failed",
          opponents: [],
          nextAfterOpponentId: null,
          atEnd: false,
          error: { kind: "invalid", message: decoded.error },
          loadingMore: false,
        });
        return;
      }
      setOpponentsState({
        phase: "ok",
        opponents: decoded.opponents as OpponentItem[],
        nextAfterOpponentId: decoded.nextAfterOpponentId,
        atEnd: decoded.atEnd,
        error: null,
        loadingMore: false,
      });
    } catch (err: unknown) {
      setOpponentsState({
        phase: "failed",
        opponents: [],
        nextAfterOpponentId: null,
        atEnd: false,
        error: classifyProfileError(err, PARTICIPANT_READ_TIMEOUT_MS),
        loadingMore: false,
      });
    }
  }, [participantId]);

  const loadMoreOpponents = useCallback(async () => {
    if (!participantId || !opponentsState.nextAfterOpponentId || opponentsState.loadingMore) return;
    setOpponentsState((prev) => ({ ...prev, loadingMore: true }));
    try {
      const body = await readJson(
        `/league/participants/${encodeURIComponent(participantId)}/opponents?limit=${OPPONENTS_DEFAULT_LIMIT}&after=${encodeURIComponent(opponentsState.nextAfterOpponentId)}`,
        PARTICIPANT_READ_TIMEOUT_MS
      );
      const decoded = decodeOpponentsPage(body, participantId);
      if (!decoded.ok) {
        setOpponentsState((prev) => ({
          ...prev,
          loadingMore: false,
          error: { kind: "invalid", message: decoded.error },
        }));
        return;
      }
      setOpponentsState((prev) => {
        const existingIds = new Set(prev.opponents.map((o) => o.opponent_id));
        const newOpponents = (decoded.opponents as OpponentItem[]).filter((o) => !existingIds.has(o.opponent_id));
        return {
          ...prev,
          opponents: [...prev.opponents, ...newOpponents],
          nextAfterOpponentId: decoded.nextAfterOpponentId,
          atEnd: decoded.atEnd,
          loadingMore: false,
          error: null,
        };
      });
    } catch (err: unknown) {
      setOpponentsState((prev) => ({
        ...prev,
        loadingMore: false,
        error: classifyProfileError(err, PARTICIPANT_READ_TIMEOUT_MS),
      }));
    }
  }, [participantId, opponentsState.nextAfterOpponentId, opponentsState.loadingMore]);

  // 4. Games on-demand loader & paginator (Reusing D1 endpoint)
  const loadGames = useCallback(async () => {
    if (!participantId) return;
    setGamesState((prev) => ({ ...prev, phase: "loading", error: null }));
    try {
      const body = await readJson(
        `/league/games?participant_id=${encodeURIComponent(participantId)}&limit=${GAMES_DEFAULT_LIMIT}`,
        PARTICIPANT_READ_TIMEOUT_MS
      );
      const decoded = describeGamesPage(body);
      if (decoded.invalid) {
        setGamesState({
          phase: "failed",
          matches: [],
          nextBeforeLeagueSeq: null,
          atEnd: false,
          error: { kind: "invalid", message: "Host returned an invalid games page." },
          loadingMore: false,
        });
        return;
      }
      setGamesState({
        phase: "ok",
        matches: decoded.rows as GameItem[],
        nextBeforeLeagueSeq: decoded.nextBeforeLeagueSeq,
        atEnd: decoded.atEnd,
        error: null,
        loadingMore: false,
      });
    } catch (err: unknown) {
      setGamesState({
        phase: "failed",
        matches: [],
        nextBeforeLeagueSeq: null,
        atEnd: false,
        error: classifyProfileError(err, PARTICIPANT_READ_TIMEOUT_MS),
        loadingMore: false,
      });
    }
  }, [participantId]);

  const loadMoreGames = useCallback(async () => {
    if (!participantId || !gamesState.nextBeforeLeagueSeq || gamesState.loadingMore) return;
    setGamesState((prev) => ({ ...prev, loadingMore: true }));
    try {
      const body = await readJson(
        `/league/games?participant_id=${encodeURIComponent(participantId)}&limit=${GAMES_DEFAULT_LIMIT}&before=${gamesState.nextBeforeLeagueSeq}`,
        PARTICIPANT_READ_TIMEOUT_MS
      );
      const decoded = describeGamesPage(body);
      if (decoded.invalid) {
        setGamesState((prev) => ({
          ...prev,
          loadingMore: false,
          error: { kind: "invalid", message: "Host returned an invalid games page." },
        }));
        return;
      }
      setGamesState((prev) => {
        const existingIds = new Set(prev.matches.map((m) => m.matchId));
        const newMatches = (decoded.rows as GameItem[]).filter((m) => !existingIds.has(m.matchId));
        return {
          ...prev,
          matches: [...prev.matches, ...newMatches],
          nextBeforeLeagueSeq: decoded.nextBeforeLeagueSeq,
          atEnd: decoded.atEnd,
          loadingMore: false,
          error: null,
        };
      });
    } catch (err: unknown) {
      setGamesState((prev) => ({
        ...prev,
        loadingMore: false,
        error: classifyProfileError(err, PARTICIPANT_READ_TIMEOUT_MS),
      }));
    }
  }, [participantId, gamesState.nextBeforeLeagueSeq, gamesState.loadingMore]);

  // Tab switcher with on-demand trigger: cached once ok
  const switchTab = (tab: TabKey) => {
    setActiveTab(tab);
    if (tab === "ratings" && ratingsState.phase === "idle") {
      void loadRatings();
    } else if (tab === "opponents" && opponentsState.phase === "idle") {
      void loadOpponents();
    } else if (tab === "games" && gamesState.phase === "idle") {
      void loadGames();
    }
  };

  const chartData = useMemo(() => {
    return buildEloChartData(ratingsState.points);
  }, [ratingsState.points]);

  const profile = profileState.data;
  const eloInfo = profile ? describeProfileElo(profile.elo, profile.provisional) : null;
  const recordInfo = profile ? describeRecordText(profile) : null;
  const seatsInfo = profile ? describeSeatsText(profile.seats) : null;
  const pliesInfo = profile ? describeCompletedPlies(profile.completed_plies) : null;

  return (
    <main className="studio profile-page">
      <header className="topbar">
        <div className="brand-block">
          <span className="eyebrow">EFFECTIVE SPLENDOR · STUDIO LEAGUE</span>
          <h1>Participant Profile</h1>
        </div>
        <div className="header-actions">
          <Link className="studio-link" href="/">
            Games
          </Link>
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
        </div>
      </header>

      <section className="profile-header-area">
        <div className="profile-breadcrumbs">
          <Link href="/ratings" className="profile-back-link">
            ← Back to Standings
          </Link>
          <span className="section-kicker">PARTICIPANT PROFILE</span>
        </div>

        {(profileState.phase === "idle" || profileState.phase === "loading") && (
          <p className="ratings-state">Loading participant profile from Studio Host…</p>
        )}

        {profileState.phase === "failed" && (
          <div className="error-banner" role="alert">
            {profileState.error?.kind === "not_found"
              ? `No participant with ID "${participantId}" is recorded in the Studio League.`
              : profileState.error?.kind === "refused"
              ? `The Studio League authority refused the read: ${profileState.error.message}`
              : `The profile could not be read: ${profileState.error?.message ?? "unknown error"}`}
            {" "}
            <button type="button" onClick={() => void loadProfile()}>
              Try again
            </button>
          </div>
        )}

        {profileState.phase === "ok" && profile && (
          <div className="profile-hero">
            <div className="profile-hero-main">
              <h2>{profile.display_name}</h2>
              <div className="profile-badges">
                <span className="profile-kind-badge">{describeProfileKind(profile.kind)}</span>
                {profile.provisional && (
                  <span className="profile-provisional-badge">Provisional</span>
                )}
                <code className="profile-id-tag">{profile.participant_id}</code>
              </div>
            </div>
          </div>
        )}
      </section>

      {/* Navigation tabs: clicking loads on-demand */}
      <nav className="profile-tabs" aria-label="Participant sections">
        <button
          type="button"
          className={`profile-tab-button ${activeTab === "overview" ? "active" : ""}`}
          onClick={() => switchTab("overview")}
        >
          Overview
        </button>
        <button
          type="button"
          className={`profile-tab-button ${activeTab === "games" ? "active" : ""}`}
          onClick={() => switchTab("games")}
        >
          Games {profile ? `(${profile.recorded_games})` : ""}
        </button>
        <button
          type="button"
          className={`profile-tab-button ${activeTab === "ratings" ? "active" : ""}`}
          onClick={() => switchTab("ratings")}
        >
          Rating history {profile ? `(${profile.rated_games})` : ""}
        </button>
        <button
          type="button"
          className={`profile-tab-button ${activeTab === "opponents" ? "active" : ""}`}
          onClick={() => switchTab("opponents")}
        >
          Opponents
        </button>
      </nav>

      {/* SECTION 1: Overview */}
      {activeTab === "overview" && profileState.phase === "ok" && profile && (
        <section className="profile-tab-content">
          <div className="profile-cards-grid">
            {/* Elo Card */}
            <div className="profile-card">
              <span className="profile-card-title">{eloInfo?.label}</span>
              <div className="profile-card-value elo-highlight">{eloInfo?.valueText}</div>
              <div className="profile-card-subtext">
                {eloInfo?.isInitial ? eloInfo.subtext : `${eloInfo?.preciseText} precise · ${eloInfo?.subtext}`}
              </div>
            </div>

            {/* Rated Record Card */}
            <div className="profile-card">
              <span className="profile-card-title">Rated Record (W–T–L)</span>
              <div className="profile-card-value">{recordInfo?.record}</div>
              <div className="profile-card-subtext">{recordInfo?.games}</div>
            </div>

            {/* Seat Usage Card */}
            <div className="profile-card">
              <span className="profile-card-title">Seat Usage</span>
              <div className="profile-card-value">{seatsInfo?.summary}</div>
              <div className="profile-card-subtext">{seatsInfo?.appearances}</div>
            </div>

            {/* Completed Games / Decision Plies Card */}
            <div className="profile-card">
              <span className="profile-card-title">Completed Games</span>
              <div className="profile-card-value">{pliesInfo?.valueText}</div>
              <div className="profile-card-subtext">{pliesInfo?.subtext}</div>
            </div>

            {/* Main Turns Card */}
            <div className="profile-card profile-card-muted">
              <span className="profile-card-title">Main Turns</span>
              <div className="profile-card-value">Not recorded</div>
              <div className="profile-card-subtext">Main turn metrics are not available in this build.</div>
            </div>

            {/* Gameplay Breakdown Card */}
            <div className="profile-card profile-card-muted">
              <span className="profile-card-title">Gameplay Breakdown</span>
              <div className="profile-card-value">Not available</div>
              <div className="profile-card-subtext">No authoritative gameplay-stat builder exists.</div>
            </div>
          </div>

          <p className="profile-notice">
            Ratings and records are authoritative ledger facts. Game duration, resource breakdown, and action statistics are not estimated or approximated.
          </p>
        </section>
      )}

      {/* SECTION 2: Games */}
      {activeTab === "games" && (
        <section className="profile-tab-content">
          {gamesState.phase === "loading" && gamesState.matches.length === 0 && (
            <p className="ratings-state">Loading personal games from Studio League…</p>
          )}

          {gamesState.phase === "failed" && gamesState.matches.length === 0 && (
            <div className="error-banner" role="alert">
              Failed to load personal games: {gamesState.error?.message ?? "unknown error"}.{" "}
              <button type="button" onClick={() => void loadGames()}>
                Try again
              </button>
            </div>
          )}

          {gamesState.matches.length > 0 && (
            <div className="ratings-panel">
              <div className="ratings-table">
                <div className="ratings-row ratings-head-row">
                  <span>Seq / Match ID</span>
                  <span>Source</span>
                  <span>Outcome</span>
                  <span>Seats & Scores</span>
                  <span>Replay</span>
                </div>
                {gamesState.matches.map((game) => (
                  <div className="ratings-row" key={game.matchId}>
                    <span>
                      <b>#{game.leagueSeq ?? "—"}</b>
                      <i>
                        <code>{game.matchId?.slice(0, 12) ?? "—"}…</code>
                        <small>{game.status}</small>
                      </i>
                    </span>
                    <span>{game.sourceKind ?? "—"}</span>
                    <span>{game.outcome}</span>
                    <span>{game.scoreLine}</span>
                    <span>
                      {game.replayHref ? (
                        <Link href={game.replayHref} className="studio-link">
                          Open replay
                        </Link>
                      ) : (
                        <span className="text-muted">—</span>
                      )}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {gamesState.phase === "ok" && gamesState.matches.length === 0 && (
            <p className="ratings-state">No games recorded for this participant.</p>
          )}

          {gamesState.nextBeforeLeagueSeq !== null && (
            <div className="load-more-container">
              <button
                type="button"
                className="games-more"
                disabled={gamesState.loadingMore}
                onClick={() => void loadMoreGames()}
              >
                {gamesState.loadingMore ? "Loading earlier games…" : "Load earlier games"}
              </button>
            </div>
          )}
        </section>
      )}

      {/* SECTION 3: Rating History */}
      {activeTab === "ratings" && (
        <section className="profile-tab-content">
          {ratingsState.phase === "loading" && ratingsState.points.length === 0 && (
            <p className="ratings-state">Loading rating events from Studio League…</p>
          )}

          {ratingsState.phase === "failed" && ratingsState.points.length === 0 && (
            <div className="error-banner" role="alert">
              Failed to load rating history: {ratingsState.error?.message ?? "unknown error"}.{" "}
              <button type="button" onClick={() => void loadRatings()}>
                Try again
              </button>
            </div>
          )}

          {/* SVG Elo Chart */}
          {chartData.series.length > 0 && (
            <div className="profile-chart-box">
              <div className="profile-chart-header">
                <h3>Rating progression</h3>
                <span className="profile-chart-sub">
                  x-axis: League sequence · Protocol starting Elo: 1500
                </span>
              </div>
              <div className="profile-svg-container">
                <svg viewBox="0 0 640 180" className="profile-chart-svg" role="img" aria-label="Elo chart">
                  {/* Grid / Reference lines */}
                  <line x1="60" y1="20" x2="600" y2="20" stroke="#252f3d" strokeDasharray="3 3" />
                  <line x1="60" y1="90" x2="600" y2="90" stroke="#252f3d" strokeDasharray="3 3" />
                  <line x1="60" y1="150" x2="600" y2="150" stroke="#374558" />

                  {/* Y Axis labels */}
                  <text x="50" y="24" textAnchor="end" fill="#758396" fontSize="10">
                    {Math.round(chartData.maxY)}
                  </text>
                  <text x="50" y="94" textAnchor="end" fill="#758396" fontSize="10">
                    {Math.round((chartData.minY + chartData.maxY) / 2)}
                  </text>
                  <text x="50" y="154" textAnchor="end" fill="#758396" fontSize="10">
                    {Math.round(chartData.minY)}
                  </text>

                  {/* Chart Line / Points */}
                  {chartData.series.length === 1 ? (
                    // Single point
                    <g>
                      <circle cx="330" cy="90" r="5" fill="var(--cyan)" />
                      <text x="330" y="75" textAnchor="middle" fill="#d0e2ec" fontSize="11" fontWeight="bold">
                        {chartData.series[0].y.toFixed(1)} Elo
                      </text>
                      <text x="330" y="170" textAnchor="middle" fill="#758396" fontSize="10">
                        Seq #{chartData.series[0].x}
                      </text>
                    </g>
                  ) : (
                    // Multiple points connected via polyline
                    <g>
                      <polyline
                        fill="none"
                        stroke="var(--cyan)"
                        strokeWidth="2.5"
                        points={chartData.series
                          .map((s) => {
                            const x = 60 + ((s.x - chartData.minX) / (chartData.maxX - chartData.minX || 1)) * 540;
                            const y = 150 - ((s.y - chartData.minY) / (chartData.maxY - chartData.minY || 1)) * 130;
                            return `${x.toFixed(1)},${y.toFixed(1)}`;
                          })
                          .join(" ")}
                      />
                      {chartData.series.map((s, idx) => {
                        const x = 60 + ((s.x - chartData.minX) / (chartData.maxX - chartData.minX || 1)) * 540;
                        const y = 150 - ((s.y - chartData.minY) / (chartData.maxY - chartData.minY || 1)) * 130;
                        return (
                          <circle
                            key={`pt-${idx}`}
                            cx={x.toFixed(1)}
                            cy={y.toFixed(1)}
                            r="3"
                            fill="#111822"
                            stroke="var(--cyan)"
                            strokeWidth="2"
                          />
                        );
                      })}
                      <text x="60" y="170" textAnchor="start" fill="#758396" fontSize="10">
                        Seq #{chartData.minX}
                      </text>
                      <text x="600" y="170" textAnchor="end" fill="#758396" fontSize="10">
                        Seq #{chartData.maxX}
                      </text>
                    </g>
                  )}
                </svg>
              </div>
            </div>
          )}

          {/* Points list table */}
          {ratingsState.points.length > 0 && (
            <div className="ratings-panel">
              <div className="ratings-table">
                <div className="ratings-row ratings-head-row">
                  <span>League Seq</span>
                  <span>Opponent</span>
                  <span>Before</span>
                  <span>Delta</span>
                  <span>After</span>
                </div>
                {ratingsState.points.map((pt) => (
                  <div className="ratings-row" key={`pt-${pt.league_seq}`}>
                    <span>
                      <b>#{pt.league_seq}</b>
                      <i>
                        <Link href={`/replay?league=${encodeURIComponent(pt.match_id)}`} className="studio-link">
                          <code>{pt.match_id.slice(0, 8)}…</code>
                        </Link>
                        <small>{pt.played_at ? new Date(pt.played_at * 1000).toLocaleDateString() : "—"}</small>
                      </i>
                    </span>
                    <span>
                      <Link href={`/ratings/${encodeURIComponent(pt.opponent_id)}`} className="studio-link">
                        {pt.opponent_name}
                      </Link>
                    </span>
                    <span>{pt.elo_before.toFixed(1)}</span>
                    <span className={pt.delta >= 0 ? "delta-pos" : "delta-neg"}>
                      {pt.delta >= 0 ? `+${pt.delta.toFixed(1)}` : pt.delta.toFixed(1)}
                    </span>
                    <span className="ratings-elo">{pt.elo_after.toFixed(1)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {ratingsState.phase === "ok" && ratingsState.points.length === 0 && (
            <p className="ratings-state">No rating events recorded for this participant.</p>
          )}

          {ratingsState.nextBeforeLeagueSeq !== null && (
            <div className="load-more-container">
              <button
                type="button"
                className="games-more"
                disabled={ratingsState.loadingMore}
                onClick={() => void loadMoreRatings()}
              >
                {ratingsState.loadingMore ? "Loading earlier events…" : "Load earlier events"}
              </button>
            </div>
          )}
        </section>
      )}

      {/* SECTION 4: Opponents */}
      {activeTab === "opponents" && (
        <section className="profile-tab-content">
          {opponentsState.phase === "loading" && opponentsState.opponents.length === 0 && (
            <p className="ratings-state">Loading head-to-head records from Studio League…</p>
          )}

          {opponentsState.phase === "failed" && opponentsState.opponents.length === 0 && (
            <div className="error-banner" role="alert">
              Failed to load opponents: {opponentsState.error?.message ?? "unknown error"}.{" "}
              <button type="button" onClick={() => void loadOpponents()}>
                Try again
              </button>
            </div>
          )}

          {opponentsState.opponents.length > 0 && (
            <div className="ratings-panel">
              <div className="ratings-table">
                <div className="ratings-row ratings-head-row">
                  <span>Opponent</span>
                  <span>Recorded Games</span>
                  <span>Rated Games</span>
                  <span>Rated W–T–L</span>
                </div>
                {opponentsState.opponents.map((opp) => (
                  <div className="ratings-row opponents-grid" key={opp.opponent_id}>
                    <span>
                      <Link href={`/ratings/${encodeURIComponent(opp.opponent_id)}`} className="profile-opponent-name">
                        {opp.display_name}
                      </Link>
                      <small><code>{opp.opponent_id}</code></small>
                    </span>
                    <span>{opp.recorded_games}</span>
                    <span>{opp.rated_games}</span>
                    <span>{`${opp.rated_wins}–${opp.rated_ties}–${opp.rated_losses}`}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {opponentsState.phase === "ok" && opponentsState.opponents.length === 0 && (
            <p className="ratings-state">No opponent matches recorded for this participant.</p>
          )}

          {opponentsState.nextAfterOpponentId !== null && (
            <div className="load-more-container">
              <button
                type="button"
                className="games-more"
                disabled={opponentsState.loadingMore}
                onClick={() => void loadMoreOpponents()}
              >
                {opponentsState.loadingMore ? "Loading more opponents…" : "Load more opponents"}
              </button>
            </div>
          )}
        </section>
      )}
    </main>
  );
}
