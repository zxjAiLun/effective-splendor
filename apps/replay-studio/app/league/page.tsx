"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { API_BASE } from "../api-base.mjs";
import {
  classifyBookingResponse,
  describeAgentOptions,
  describeHostBanner,
  describeLeaderboard,
  describeReadFailure,
  FIRST_SCREEN_READ_TIMEOUT_MS,
  gameIdFor,
  HOST_CHECKING,
  hostStateOf,
  hostStatusText,
  LEADERBOARD_READ_TIMEOUT_MS,
  newOccurrenceId,
  randomSalt,
  READ_OK,
  READ_REFUSED,
  retryRequest,
  startRequestBody,
  validateStart,
} from "../league-runtime.mjs";

/**
 * League Play v1.
 *
 * This page is a client of the closed Studio League authority and never a second
 * one. It does not rate anything, does not decide eligibility, does not read the
 * ledger or the archive, and does not know how a match is run: it mints one
 * occurrence id, sends one request to `POST /league/matches`, and renders the two
 * facts the Host returns.
 *
 * The occurrence id is an identity, not a token: minted once per attempt, shown,
 * copyable, never editable, and re-sent unchanged on retry — so a retry completes
 * the match that already happened instead of booking a second one.
 */

type Attempt = {
  occurrenceId: string;
  gameId: string;
  seed: number;
};

type AgentOption = {
  id: string;
  displayName: string;
  agentClass: string | null;
  policyVersion: string | null;
};

/** The whole write protocol. Nothing else may travel to the Host. */
type BookingRequest = {
  occurrence_id: string;
  game_id: string;
  seed: number;
  seats: string[];
};

type EloEvent = { participantId: string; eloBefore: number; eloAfter: number };

type BookingResult = {
  matchStatus: string | null;
  completionStatus: string | null;
  headline: string;
  booking: string;
  problem: string | null;
  retryable: boolean;
  sourceIdentity: string | null;
  /** The ledger's match id is a string (`IngestOutcome::match_id`), not a number. */
  matchId: string | null;
  eligibility: string | null;
  elo: EloEvent[];
  documentSha256: string | null;
  replayHref: string | null;
  raw: unknown;
};

type BookingFailure = {
  /** The panel's own label: a claim about the ledger, decided by `describeFailure`. */
  kicker: string;
  headline: string;
  detail: string;
  retryable: boolean;
};

/**
 * The outcome of classifying one write response.
 *
 * `settled` says a match fact exists. It is NOT the same as `response.ok`: a
 * completed match whose booking failed arrives as HTTP 503 with both axes set, and
 * it must reach the result panel with its retry.
 */
type BookingClassification = {
  settled: boolean;
  result: BookingResult | null;
  failure: BookingFailure | null;
};

type LeaderRow = {
  participantId: string | null;
  displayName: string | null;
  elo: number | null;
  ratedGames: number | null;
  recordedGames: number | null;
  ratedWins: number | null;
  ratedTies: number | null;
  ratedLosses: number | null;
  provisional: boolean | null;
};

const MAX_SEATS = 4;
const SEED_CEILING = 2 ** 31;

/**
 * Read one JSON document the first screen needs.
 *
 * `timeoutMs` is the UI budget for a *read*, and it is passed in rather than baked in
 * so that the booking `POST` — which can legitimately run a real match for minutes —
 * cannot inherit it by accident. A read that is refused is tagged, because "the Host
 * answered no" and "the Host never answered" are different facts.
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

function mintAttempt(): Attempt {
  const occurrenceId = newOccurrenceId(Date.now(), randomSalt());
  return {
    occurrenceId,
    gameId: gameIdFor(occurrenceId),
    seed: Math.floor(Math.random() * SEED_CEILING),
  };
}

function reasonText(reason: unknown) {
  return reason instanceof Error ? reason.message : String(reason);
}

export default function LeaguePage() {
  const [agents, setAgents] = useState<AgentOption[]>([]);
  const [rows, setRows] = useState<LeaderRow[]>([]);
  // `checking` until a read actually answers: an unheard request is never evidence
  // that the Host is fine, so readiness has to be earned by an answer.
  const [rosterRead, setRosterRead] = useState<string>(HOST_CHECKING);
  const [rosterMessage, setRosterMessage] = useState("");
  const [leagueRead, setLeagueRead] = useState<string>(HOST_CHECKING);
  const [leagueMessage, setLeagueMessage] = useState("");
  const [seats, setSeats] = useState<string[]>(["", ""]);
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const [notes, setNotes] = useState<string[]>([]);
  const [problem, setProblem] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<BookingResult | null>(null);
  const [failure, setFailure] = useState<BookingFailure | null>(null);
  const [pending, setPending] = useState<BookingRequest | null>(null);
  const [copied, setCopied] = useState(false);

  /**
   * Read the roster and the leaderboard once, independently.
   *
   * They are read separately on purpose: an unreadable league must not hide the
   * roster, and an unreadable roster must not look like an unreadable league.
   */
  const loadRoster = useCallback(async () => {
    setRosterRead(HOST_CHECKING);
    try {
      const budget = FIRST_SCREEN_READ_TIMEOUT_MS;
      const body = await readJson("/agents", budget);
      setAgents(describeAgentOptions(body.agents) as AgentOption[]);
      setRosterRead(READ_OK);
      setRosterMessage("");
    } catch (reason) {
      const failure = describeReadFailure(reason, FIRST_SCREEN_READ_TIMEOUT_MS);
      setRosterRead(failure.kind);
      setRosterMessage(failure.message);
    }
  }, []);

  const loadLeaderboard = useCallback(async () => {
    setLeagueRead(HOST_CHECKING);
    try {
      // The leaderboard aggregates the whole league, so a cold first read is
      // legitimately slower than the roster; it gets its own, larger budget.
      const budget = LEADERBOARD_READ_TIMEOUT_MS;
      const body = await readJson("/league/leaderboard", budget);
      setRows(describeLeaderboard(body.rows) as LeaderRow[]);
      setLeagueRead(READ_OK);
      setLeagueMessage("");
    } catch (reason) {
      const failure = describeReadFailure(reason, LEADERBOARD_READ_TIMEOUT_MS);
      setLeagueRead(failure.kind);
      setLeagueMessage(failure.message);
    }
  }, []);

  // Minting happens on the client only: a server-rendered id would not match the
  // one the browser mints, and an occurrence id must exist exactly once.
  useEffect(() => {
    setAttempt(mintAttempt());
    void loadRoster();
    void loadLeaderboard();
  }, [loadRoster, loadLeaderboard]);

  /**
   * Send one booking request body, and nothing else.
   *
   * `body` is the whole protocol: no timeout, no program, no config. A retry
   * passes the *same* body, so the Host can recognise the occurrence and answer
   * `already_present` instead of running the match again.
   */
  async function send(body: BookingRequest) {
    setRunning(true);
    setResult(null);
    setFailure(null);
    setProblem("");
    try {
      const response = await fetch(`${API_BASE}/league/matches`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const value = await response.json().catch(() => null);
      // Classified by the body, never by `response.ok`: a settled match arrives as
      // 503 when its booking failed, and it must be rendered as the two facts it is.
      const classified = classifyBookingResponse(response.status, value) as BookingClassification;
      if (!classified.settled || !classified.result) {
        setFailure(classified.failure);
        return;
      }
      const settled = classified.result;
      setResult(settled);
      // One refresh, and only when the league actually recorded something. A match
      // whose booking failed changed nothing to refresh, and the page never polls:
      // the Host serves one request at a time, so polling would only queue behind it.
      if (settled.completionStatus === "inserted" || settled.completionStatus === "already_present") {
        void loadLeaderboard();
      }
    } catch (reason) {
      // A thrown fetch is ambiguous, not a plain refusal: it may mean the request
      // never arrived, is still running, or completed with its response lost. The
      // module decides that the retry re-sends the same body, never a new occurrence.
      const ambiguous = classifyBookingResponse(null, {
        error: reasonText(reason),
      }) as BookingClassification;
      setFailure(ambiguous.failure);
    } finally {
      setRunning(false);
    }
  }

  function start() {
    if (!attempt) return;
    const start = {
      occurrenceId: attempt.occurrenceId,
      gameId: attempt.gameId,
      seed: attempt.seed,
      seats,
    };
    const checked = validateStart(start);
    setNotes(checked.notes);
    if (checked.error) {
      setProblem(checked.error);
      return;
    }
    const body = startRequestBody(start);
    setPending(body);
    void send(body);
  }

  function retry() {
    if (!pending) return;
    void send(retryRequest(pending));
  }

  function newMatch() {
    setAttempt(mintAttempt());
    setSeats(["", ""]);
    setNotes([]);
    setProblem("");
    setResult(null);
    setFailure(null);
    setPending(null);
    setCopied(false);
  }

  async function copyOccurrenceId() {
    if (!attempt) return;
    try {
      await navigator.clipboard.writeText(attempt.occurrenceId);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  const hostState = hostStateOf({ roster: rosterRead, league: leagueRead });
  // A banner is a claim that something failed, so it may only exist once a read has
  // actually settled. `describeHostBanner` describes failures and treats anything it
  // does not recognise as a refusal, so feeding it the *pending* state produced
  // "The request was refused: ." beside "Checking Studio Host…" — the page announcing
  // a refusal it had no evidence for, which is the same class of lie as a premature
  // "ready". Pending and success both mean "nothing to report".
  const rosterBanner =
    rosterRead === HOST_CHECKING || rosterRead === READ_OK
      ? null
      : describeHostBanner(rosterRead, rosterMessage);

  const hostLine = running
    ? "Match running · the local Host takes one request at a time"
    : hostStatusText(hostState);

  return (
    <main className="human-studio">
      <header className="human-topbar">
        <div>
          <span className="section-kicker">RATED MATCHES · STUDIO LEAGUE</span>
          <h1>League Play</h1>
        </div>
        <div className="human-status">
          <span className={`status-dot ${hostState === "not_responding" ? "offline" : ""}`} />
          {hostLine}
        </div>
        <nav>
          <Link href="/">Games</Link>
          <Link href="/play">Play vs S3</Link>
          <Link href="/ratings">Ratings</Link>
          <Link href="/ratings/reports">Research reports</Link>
        </nav>
      </header>

      {rosterBanner ? (
        <div className="error-banner" role="alert">
          {rosterBanner.headline} {rosterBanner.advice}{" "}
          {rosterRead === "unreachable" ? (
            <>
              with <code>splendor studio-host --registry &lt;registry.json&gt; --port 43120</code>.
            </>
          ) : null}
        </div>
      ) : null}

      <section className="human-connect">
        <span className="section-kicker">START A RATED MATCH</span>
        <h2>Two registered agents, one league row</h2>
        <p>
          <strong>Rated:</strong> this match is written to the Studio League — a ledger row, Elo
          rating events and an archived replay. Elo may change. It is not an exhibition and it does
          not touch your saved human games.
        </p>
        <p>
          Occurrence id:{" "}
          {attempt ? (
            <>
              <code>{attempt.occurrenceId}</code>{" "}
              <button type="button" onClick={() => void copyOccurrenceId()} disabled={running}>
                Copy
              </button>{" "}
              <small>
                {copied ? "Copied." : "Fixed for this match, reused by Retry. Not editable."}
              </small>
            </>
          ) : (
            <small>Preparing an occurrence id…</small>
          )}
        </p>
        <p>
          Seed: <code>{attempt ? attempt.seed : "…"}</code>{" "}
          <small>Fixed with the occurrence id; a retry replays this seed, it does not re-roll one.</small>
        </p>

        {rosterRead !== READ_OK ? (
        <p>
          {rosterRead === HOST_CHECKING
            ? "Loading the agent roster from the Studio Host…"
            : "No agent can be picked: the roster could not be read from the Studio Host."}
        </p>
      ) : null}

      {seats.map((seat, index) => (
          <label key={index}>
            Seat {index + 1}
            <select
              value={seat}
              disabled={running || rosterRead !== READ_OK}
              onChange={(event) => {
                const next = [...seats];
                next[index] = event.target.value;
                setSeats(next);
              }}
            >
              <option value="">Choose an agent…</option>
              {agents.map((agent) => (
                <option value={agent.id} key={agent.id}>
                  {agent.displayName} · {agent.id}
                </option>
              ))}
            </select>
          </label>
        ))}

        <button
          type="button"
          disabled={running || !attempt || seats.length >= MAX_SEATS}
          onClick={() => setSeats([...seats, ""])}
        >
          Add a seat
        </button>
        {seats.length > 2 ? (
          <button type="button" disabled={running} onClick={() => setSeats(seats.slice(0, -1))}>
            Remove the last seat
          </button>
        ) : null}

        {problem ? (
          <div className="error-banner" role="alert">
            {problem}
          </div>
        ) : null}
        {notes.map((note) => (
          <p key={note}>
            <small>{note}</small>
          </p>
        ))}

        <div>
          <button type="button" disabled={running || !attempt} onClick={start}>
            Start rated match
          </button>
          <button type="button" disabled={running} onClick={newMatch}>
            New match
          </button>
        </div>
        {running ? (
          <p>
            <small>
              Running… the Host is playing this match now and will answer when it settles. It is not
              stuck, and the page does not poll while it waits.
            </small>
          </p>
        ) : null}
      </section>

      {failure ? (
        <section className="recent-games">
          <span className="section-kicker">{failure.kicker}</span>
          <h2>{failure.headline}</h2>
          <p>{failure.detail}</p>
          {failure.retryable && pending ? (
            <button type="button" onClick={retry}>
              Retry the same match
            </button>
          ) : null}
        </section>
      ) : null}

      {result ? (
        <section className="recent-games">
          <span className="section-kicker">RESULT</span>
          <h2>{result.headline}</h2>
          <p>{result.booking}</p>
          {result.problem ? <p role="alert">{result.problem}</p> : null}
          {result.retryable && pending ? (
            <button type="button" onClick={retry}>
              Retry the booking (same occurrence, same seed)
            </button>
          ) : null}
          <ul>
            <li>match_status: <code>{result.matchStatus ?? "—"}</code></li>
            <li>completion_status: <code>{result.completionStatus ?? "—"}</code></li>
            <li>occurrence: <code>{result.sourceIdentity ?? "—"}</code></li>
            <li>match row: <code>{result.matchId ?? "—"}</code></li>
            <li>eligibility: <code>{result.eligibility ?? "—"}</code></li>
          </ul>
          {result.elo.length ? (
            <div className="recent-game-list">
              {result.elo.map((event) => (
                <article key={`${event.participantId}-${event.eloBefore}`}>
                  <div>
                    <strong>{event.participantId}</strong>
                    <small>
                      {event.eloBefore} → {event.eloAfter} ({event.eloAfter - event.eloBefore >= 0 ? "+" : ""}
                      {event.eloAfter - event.eloBefore})
                    </small>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <p>
              <small>No Elo moved for this match (the receipt carries no rating event).</small>
            </p>
          )}
          {result.replayHref ? <Link href={result.replayHref}>Open replay</Link> : null}
          <details>
            <summary>Raw Host response</summary>
            <pre>{JSON.stringify(result.raw, null, 2)}</pre>
          </details>
        </section>
      ) : null}

      <section className="recent-games">
        <span className="section-kicker">LEADERBOARD</span>
        <h2>Studio League standings</h2>
        {leagueRead !== READ_OK ? (
          <p role="alert">
            {leagueRead === HOST_CHECKING
              ? "Loading the standings from the Studio Host…"
              : `The league could not be read: ${leagueMessage}. The Host serves it from `}
            {leagueRead === HOST_CHECKING ? null : (
              <code>&lt;project-root&gt;/local-artifacts/studio-league/league.sqlite3</code>
            )}
          </p>
        ) : null}
        {leagueRead === READ_OK && rows.length === 0 ? <p>No league rows yet.</p> : null}
        {rows.length ? (
          <div className="recent-game-list">
            {rows.map((row, index) => (
              <article key={row.participantId ?? `row-${index}`}>
                <div>
                  <strong>{row.displayName ?? row.participantId}</strong>
                  <small>
                    {row.participantId} · {row.ratedGames ?? "—"} rated / {row.recordedGames ?? "—"}{" "}
                    recorded · W {row.ratedWins ?? "—"} / T {row.ratedTies ?? "—"} / L{" "}
                    {row.ratedLosses ?? "—"}
                    {row.provisional === null ? "" : row.provisional ? " · provisional" : ""}
                  </small>
                </div>
                <div>
                  <span>{row.elo === null ? "—" : row.elo}</span>
                </div>
              </article>
            ))}
          </div>
        ) : null}
        <p>
          <small>
            Standings are ordered by the ledger, not by this page. A registry agent is listed in the
            pickers by its registry id; these rows are league participants, and the two closed read
            routes share no join key — so no agent is labelled with a rating this page cannot
            attribute. The Elo above is per participant, and a match&apos;s own deltas are in the
            result panel.
          </small>
        </p>
      </section>
    </main>
  );
}
