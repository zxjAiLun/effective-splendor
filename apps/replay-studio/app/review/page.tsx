"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { API_BASE as API } from "../api-base.mjs";
import {
  actionKey,
  buildReviewRows,
  buildReviewSummary,
  decodeReviewersEnvelope,
  defaultReviewerIdFor,
  jobMatchesRequest,
  parseUrlSeat,
  resolveHumanSeat,
  resolveSwitchIndex,
  reviewRecommendedAction,
  reviewerSupportsPlayerCount,
  validateReviewTrace,
} from "../trace-runtime.mjs";
import { type DevelopmentCardData } from "../development-card";
import {
  BoardSurface,
  usePlyNavigation,
} from "../components/replay-board";
import { PlayerStateStrip } from "../components/player-state-strip";
import { StructuredAction, type ActionCatalog, type ActionPlayerView } from "../components/structured-action";

type Action = { type: string; [key: string]: unknown };
type GemName = "white" | "blue" | "green" | "red" | "black" | "gold";
type Gems = Record<GemName, number>;
type PlayerView = {
  viewer: number;
  public: {
    player_count: number;
    current_player: number;
    phase: string;
    bank: Gems;
    market: Array<Array<number | null>>;
    deck_counts: number[];
    nobles: number[];
    players: Array<{
      id: number;
      tokens: Gems;
      bonuses: number[];
      prestige: number;
      reserved_count: number;
      public_reserved: number[];
      purchased: number[];
      nobles: number[];
    }>;
    pending_nobles: number[];
  };
  private: { reserved: Array<{ slot: number; card: number; tier: string; from_deck: boolean }> };
};
type Reviewer = {
  id: string;
  display_name: string;
  description: string;
  competitive_status: "champion" | "experimental" | "rejected";
  result_kind: "root_determinization" | "neural_ismcts" | "policy_recommendation";
  supported_player_counts: number[];
  default_for_player_counts: number[];
  available_metrics: string[];
  required_artifacts: string[];
  estimated_cost: string;
};
type ReviewFrame = {
  ply: number;
  state_hash_before: string;
  actor: number;
  recorded_action: Action;
  observation_hash: string;
  visible_event_count: number;
  visible_history_hash: string;
  information_set_hash: string;
  player_view: PlayerView;
  referee_reveal: { seed: number; decks: number[][]; players: Array<{ id: number; reserved: Array<{ card: number; from_deck: boolean }> }> };
  legal_actions: Action[];
  review_result: {
    kind: "root_determinization" | "neural_ismcts" | "policy_recommendation";
    recommended_action?: Action;
    sample_count?: number;
    action_stats?: Array<{ action: Action; utility_sum_by_player: number[] }>;
    result?: { action: Action; action_stats: Array<{ action: Action; prior_micros: number; visits: number; value_sum_by_player: number[] }>; stats: { root_visits: number; simulations: number; tree_nodes: number } };
    base_heuristic_action?: Action;
    n1_proposal?: Action | null;
    m07_proposal?: Action | null;
    decision_path?: "heuristic_fast_path" | "proposals_agreed" | "ply_cap_fallback" | "rollout_comparison";
    recommended_differs_from_base_heuristic?: boolean;
  };
  recommended_matches_recorded: boolean;
};
type ReviewTraceReviewer = Reviewer & {
  algorithm_id: string;
  algorithm_version: number;
  config: {
    kind: string;
    version?: number;
    sample_seed: number;
    sample_count?: number;
    continuation_search?: { max_depth_turns: number; max_nodes: number };
    simulations?: number;
    max_depth_turns?: number;
    puct_exploration_milli?: number;
    expected_checkpoint_hash?: string;
    rollout_policy?: string;
    determinizations?: number;
    ply_cap?: number;
    root_seed?: number;
    n1_config?: { sample_seed: number; sample_count: number; continuation_search: { max_depth_turns: number; max_nodes: number } };
    m07_config?: { sample_seed: number; sample_count: number; continuation_search: { max_depth_turns: number; max_nodes: number } };
  };
  checkpoint_hash: string | null;
  provenance: { seed_derivation: string; metrics: string[] };
};

type ReviewTrace = {
  format: string;
  version: 2;
  replay_document_hash: string;
  replay_final_state_hash: string;
  player_count: number;
  result: { scores: number[]; ranks: number[]; winners: number[]; reason: string };
  reviewer: ReviewTraceReviewer;
  catalog: { cards: DevelopmentCardData[]; nobles: Array<{ id: number; prestige: number; requirements: number[] }> };
  frames: ReviewFrame[];
};
type Job = {
  id: string;
  session_id: string;
  reviewer_id: string;
  status: "queued" | "running" | "completed" | "failed";
  processed_decisions: number;
  total_decisions: number;
  current_ply: number;
  error: string | null;
  cached: boolean;
  cache_key: string;
};

const S3_PATH_LABELS: Record<string, string> = {
  heuristic_fast_path: "Heuristic fast path",
  proposals_agreed: "Proposals agreed",
  ply_cap_fallback: "Ply-cap fallback",
  rollout_comparison: "Rollout comparison",
};

function reviewConfigLabel(trace: ReviewTrace) {
  const config = trace.reviewer.config;
  if (trace.reviewer.result_kind === "policy_recommendation") {
    return `S3 · D=${config.determinizations ?? "?"} · P=${config.ply_cap ?? "?"}`;
  }
  if (trace.reviewer.result_kind === "root_determinization") {
    return `s${config.sample_count}`;
  }
  return `s${config.simulations} d${config.max_depth_turns}`;
}

function shortHash(hash: string) {
  return `${hash.slice(0, 8)}…${hash.slice(-6)}`;
}

export default function ReviewPage() {
  const [sessionId, setSessionId] = useState("");
  const [humanSeat, setHumanSeat] = useState<number | null>(null);
  const [reviewerId, setReviewerId] = useState("");
  const [reviewers, setReviewers] = useState<Reviewer[]>([]);
  const [playerCount, setPlayerCount] = useState<number | null>(null);
  const [trace, setTrace] = useState<ReviewTrace | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState("");
  const [reveal, setReveal] = useState(false);
  const [filter, setFilter] = useState<"mine" | "all">("all");
  const [frameIndex, setFrameIndex] = useState(0);
  const requestGeneration = useRef(0);
  // Validated traces already fetched in this page lifetime, keyed by the Host's
  // cache key — the only identity that covers replay document + reviewer
  // identity/config. Switching back to a reviewer steps on the same key and
  // restores the trace without a second bundle fetch. Keying by reviewer id would
  // be a lie: a reviewer whose config changed keeps its id and gets a new key.
  const traceCache = useRef(new Map<string, ReviewTrace>());
  // The logical position to preserve across a reviewer switch. It is the
  // recorded ply, not a raw index: "All decisions index 17" and "My decisions
  // index 17" are different plies, so an index would silently move the user.
  const switchIntent = useRef<{ ply: number; filter: "mine" | "all"; reveal: boolean } | null>(null);

  const cards = useMemo(() => new Map((trace?.catalog.cards ?? []).map((card) => [card.id, card])), [trace]);
  const nobles = useMemo(() => new Map((trace?.catalog.nobles ?? []).map((noble) => [noble.id, noble])), [trace]);

  const startReview = async (session: string, id: string, seat = humanSeat, intent: { ply: number; filter: "mine" | "all"; reveal: boolean } | null = null) => {
    const generation = ++requestGeneration.current;
    setError("");
    setReviewerId(id);
    // Preserve the logical position, not the rendered index, before the trace is
    // replaced. Only a switch away from a rendered trace has a position to keep;
    // the caller passes the position it captured at click time.
    switchIntent.current = intent;
    setTrace(null);
    const url = new URL(window.location.href);
    url.searchParams.set("session", session);
    url.searchParams.set("reviewer", id);
    if (seat !== null) url.searchParams.set("seat", String(seat));
    window.history.replaceState(null, "", url);
    try {
      const response = await fetch(`${API}/reviews`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: session, reviewer_id: id }),
      });
      const value = (await response.json()) as Job;
      if (!response.ok) throw new Error((value as unknown as { error?: string }).error ?? `Studio Host ${response.status}`);
      // The Host's answer must describe the request that was made. A job record
      // for another session or reviewer is a refusal, not a result to render.
      if (!jobMatchesRequest(value, session, id)) {
        throw new Error(`Review job ${value.id} belongs to session ${value.session_id} / reviewer ${value.reviewer_id}, not the requested ${session} / ${id}`);
      }
      const cached = traceCache.current.get(value.cache_key);
      if (cached) {
        if (generation === requestGeneration.current) {
          applyTrace(cached, value.cache_key);
          setJob(value);
        }
        return;
      }
      void poll(value, generation);
    } catch (reason) {
      if (generation === requestGeneration.current) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    }
  };

  /**
   * Restore a validated trace and re-anchor the logical position it replaced.
   *
   * The cache key comes from the Host's job record, never from the trace: the trace
   * is a pure analysis document and carries no cache identity. Keying the browser
   * cache off the trace would silently fall back to the empty string and defeat the
   * whole reuse contract.
   */
  const applyTrace = (nextTrace: ReviewTrace, cacheKey: string) => {
    const intent = switchIntent.current;
    switchIntent.current = null;
    if (cacheKey) traceCache.current.set(cacheKey, nextTrace);
    setTrace(nextTrace);
    if (intent) {
      setFilter(intent.filter);
      setReveal(intent.reveal);
      setFrameIndex(resolveSwitchIndex(nextTrace.frames, intent, humanSeat));
    } else {
      setFrameIndex(0);
    }
    setError("");
  };

  const poll = async (initial: Job, generation: number) => {
    if (generation !== requestGeneration.current) return;
    setJob(initial);
    let current = initial;
    for (let attempt = 0; attempt < 600; attempt += 1) {
      if (generation !== requestGeneration.current) return;
      if (current.status === "completed") {
        const bundle = await fetch(`${API}/reviews/${current.id}/bundle`);
        if (generation !== requestGeneration.current) return;
        if (!bundle.ok) { setError(`bundle ${bundle.status}`); return; }
        const value = await bundle.json();
        try {
          const nextTrace = validateReviewTrace(value) as ReviewTrace;
          applyTrace(nextTrace, current.cache_key);
        } catch (reason) {
          setError(reason instanceof Error ? reason.message : "Invalid review trace");
        }
        return;
      }
      if (current.status === "failed") {
        setError(current.error ?? "Review failed");
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 400));
      if (generation !== requestGeneration.current) return;
      const response = await fetch(`${API}/reviews/${current.id}`);
      if (generation !== requestGeneration.current) return;
      if (!response.ok) { setError(`status ${response.status}`); return; }
      current = await response.json();
      setJob(current);
    }
    setError("Review timed out");
  };

  useEffect(() => {
    queueMicrotask(() => void (async () => {
      const params = new URLSearchParams(window.location.search);
      const session = params.get("session") ?? "";
      const requestedReviewer = params.get("reviewer") ?? "";
      if (!session) { setError("Missing session id in the review URL."); return; }
      let urlSeat: number | null;
      try {
        urlSeat = parseUrlSeat(params.get("seat"));
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : String(reason));
        return;
      }
      setSessionId(session);
      try {
        // Reviewer discovery resolves per-context defaults and availability from
        // the replay itself, and carries the *authoritative* human seat from the
        // session's durable metadata. The URL remains only an integrity hint.
        const response = await fetch(`${API}/reviewers?session=${encodeURIComponent(session)}`);
        const raw = await response.json();
        if (!response.ok) throw new Error(raw.error ?? `Studio Host ${response.status}`);
        const { reviewers: list, playerCount: count, humanSeat: durableSeat } = decodeReviewersEnvelope(raw);
        const reviewerList = list as Reviewer[];
        const decided = resolveHumanSeat(durableSeat, urlSeat);
        if (decided.error) { setError(decided.error); return; }
        const seat = decided.seat;
        setHumanSeat(seat);
        setFilter(seat === null ? "all" : "mine");
        setReviewers(reviewerList);
        setPlayerCount(count);
        if (count === null) { setError("The host did not report this replay's player count."); return; }
        const requested = requestedReviewer ? reviewerList.find((r) => r.id === requestedReviewer) ?? null : null;
        if (requested && !reviewerSupportsPlayerCount(requested, count)) {
          // Fail closed in the UI too: never POST an unsupported reviewer.
          setError(`${requested.display_name} is unavailable for ${count}-player replays (the S3 rollout reviewer is frozen for 2 players). Choose a supported reviewer.`);
          return;
        }
        const target = requested?.id ?? defaultReviewerIdFor(reviewerList, count);
        if (!target) { setError(`No reviewer is available for ${count}-player replays.`); return; }
        await startReview(session, target, seat);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    })());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const frames = useMemo(() => {
    if (!trace) return [];
    if (filter === "all" || humanSeat === null) return trace.frames;
    return trace.frames.filter((frame) => frame.actor === humanSeat);
  }, [trace, filter, humanSeat]);

  // The My decisions control exists only when the durable metadata names a human.
  // An unknown seat is not a disabled button: there is nothing honest to show.
  const hasHumanSeat = humanSeat !== null;

  const frame = frames[Math.min(frameIndex, frames.length - 1)] ?? null;
  const summary = useMemo(() => (trace ? buildReviewSummary(trace, humanSeat) : null), [trace, humanSeat]);
  const activeReviewer = reviewers.find((r) => r.id === reviewerId) ?? null;

  const changeFrame = (next: number) => setFrameIndex(Math.max(0, Math.min(frames.length - 1, next)));

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

  return (
    <main className="studio">
      <header className="topbar">
        <div className="brand-block">
          <span className="eyebrow">M23 · ONE-CLICK REVIEW</span>
          <h1>Replay Studio</h1>
        </div>
        <div className="match-meta">
          <span className="status-dot" aria-hidden="true" />
          <span>{sessionId || "no session"}</span>
          <span className="meta-separator">/</span>
          <span>{activeReviewer?.display_name ?? reviewerId}</span>
        </div>
        <div className="header-actions">
          <Link className="studio-link" href="/play">Play vs AI</Link>
          <Link className="studio-link" href="/ratings/reports">Research reports</Link>
          <Link className="studio-link" href="/">Games</Link>
          <button className="icon-button" onClick={() => changeFrame(frameIndex - 1)} disabled={frameIndex === 0} aria-label="Previous ply">←</button>
          <button className="icon-button" onClick={() => changeFrame(frameIndex + 1)} disabled={frameIndex >= frames.length - 1} aria-label="Next ply">→</button>
        </div>
      </header>

      {error && <div className="error-banner" role="alert">{error}</div>}

      {reviewers.length > 0 && (
        <div className="reviewer-switch" role="group" aria-label="Review with">
          <span>Review with</span>
          {reviewers.map((reviewer) => {
            const supported = playerCount === null || reviewerSupportsPlayerCount(reviewer, playerCount);
            const statusLabel = reviewer.competitive_status === "rejected"
              ? "Experimental · Formal promotion rejected"
              : reviewer.competitive_status;
            return (
              <button
                key={reviewer.id}
                className={reviewer.id === reviewerId ? "active" : ""}
                disabled={!supported}
                title={supported ? undefined : `Unavailable for ${playerCount}-player replays`}
                onClick={() => void startReview(sessionId, reviewer.id, humanSeat, frame ? { ply: frame.ply, filter: filter === "mine" && humanSeat !== null ? "mine" : "all", reveal } : null)}
              >
                <strong>{reviewer.display_name}</strong>
                <small>{statusLabel}{reviewer.estimated_cost === "cpu" ? " · CPU" : ""}{supported ? "" : ` · unavailable for ${playerCount}-player replays`}</small>
              </button>
            );
          })}
        </div>
      )}

      {!trace && !error && (
        <div className="review-progress">
          <span className="section-kicker">ANALYZING</span>
          <h2>Reviewing {sessionId}</h2>
          <p>{job ? `Analyzing ${job.processed_decisions} / ${job.total_decisions} decisions · current ply ${job.current_ply}` : "Starting review job…"}</p>
        </div>
      )}

      {trace && activeReviewer && (
        <>
          <ReviewSummaryBar trace={trace} reviewer={activeReviewer} summary={summary} job={job} hasHumanSeat={hasHumanSeat} />
          <section className="workspace">
            <div className="board-panel">
              <div className="panel-heading">
                <div>
                  <span className="section-kicker">POSITION</span>
                  <h2>Decision board</h2>
                </div>
                <div className="view-switch" role="group" aria-label="Information perspective">
                  <button className={!reveal ? "active" : ""} onClick={() => setReveal(false)}>Player view</button>
                  <button className={reveal ? "active reveal-active" : ""} onClick={() => setReveal(true)}>Referee reveal</button>
                </div>
              </div>
              {reveal && (
                <div className="reveal-warning">
                  <span>REFEREE ONLY</span>
                  Hidden reserves and future deck order are visible. Do not use this view to judge what P{frame?.actor} knew.
                </div>
              )}
              {frame && <PlayerStateStrip playerView={frame.player_view} actor={frame.actor} humanSeat={humanSeat} />}
              {frame && <BoardSurface frame={frame} cards={cards} nobles={nobles} reveal={reveal} />}
            </div>
            <aside className="analysis-panel">
              <AnalysisPanel trace={trace} frame={frame} cards={cards} nobles={nobles} humanSeat={humanSeat} />
            </aside>
          </section>
          <footer className="timeline-panel">
            <div className="timeline-title">
              <div>
                <span className="section-kicker">TIMELINE</span>
                <strong>{frameIndex + 1} / {frames.length}</strong>
                <span className="review-filter" role="group" aria-label="Decision filter">
                  {hasHumanSeat && (
                    <button className={filter === "mine" ? "active" : ""} onClick={() => { setFilter("mine"); setFrameIndex(0); }}>My decisions</button>
                  )}
                  <button className={filter === "all" ? "active" : ""} onClick={() => { setFilter("all"); setFrameIndex(0); }}>All decisions</button>
                </span>
              </div>
              <span>← → keyboard navigation</span>
            </div>
            <div className="timeline">
              {frames.map((item, index) => (
                <button key={`${item.ply}-${index}`} onClick={() => changeFrame(index)} className={`${index === frameIndex ? "current" : ""} ${item.recommended_matches_recorded ? "agreed" : "disagreed"}`} aria-label={`Ply ${item.ply}, actor P${item.actor}`}>
                  <span>{item.ply}</span><i />
                </button>
              ))}
            </div>
          </footer>
        </>
      )}
    </main>
  );
}

function ReviewSummaryBar({ trace, reviewer, summary, job, hasHumanSeat }: { trace: ReviewTrace; reviewer: Reviewer; summary: ReturnType<typeof buildReviewSummary> | null; job: Job | null; hasHumanSeat: boolean }) {
  const cacheLabel = job?.cached ? "cached" : "generated";
  // The decisions count follows whoever the count belongs to. With a recorded
  // human seat it is that human's decisions; without one the summary covers every
  // recorded decision, so calling them "human" would invent an attribution the
  // session never made. The other figures never claimed a person, so they stay.
  const decisionsLabel = hasHumanSeat ? "human decisions" : "reviewed decisions";
  return (
    <section className="review-summary">
      <div className="review-summary-title">
        <span className="section-kicker">VERIFIED REPLAY · REVIEW</span>
        <h2>{trace.result.scores.join(" – ")} final score</h2>
        <code>{shortHash(trace.replay_document_hash)}</code>
      </div>
      <dl>
        <div><dt>Reviewer</dt><dd>{reviewer.display_name}</dd></div>
        <div><dt>Status</dt><dd>{reviewer.competitive_status === "rejected" ? "Experimental · rejected" : reviewer.competitive_status}</dd></div>
        <div><dt>Replay verified</dt><dd>yes</dd></div>
        <div><dt>Artifact</dt><dd>{cacheLabel}</dd></div>
        <div><dt>Config</dt><dd>{reviewConfigLabel(trace)}</dd></div>
      </dl>
      {summary && ("matches" in summary ? (
        <div className="review-summary-stats">
          <span><b>{summary.decisions}</b> {decisionsLabel}</span>
          <span><b>{summary.matches}</b> matches S3 recommendation</span>
          <span><b>{summary.differs}</b> S3 recommends another action</span>
          <span><b>{summary.differsFromBase}</b> rollout differs from base heuristic</span>
        </div>
      ) : (
        <div className="review-summary-stats">
          <span><b>{summary.decisions}</b> {decisionsLabel}</span>
          <span><b>{summary.scored}</b> scored</span>
          <span><b>{summary.unscored}</b> unscored</span>
          <span><b>{summary.agreements}</b> reviewer agreements</span>
          <span><b>{summary.topRanked}</b> top-ranked</span>
          <span><b>{summary.medianActionRank ?? "—"}</b> median rank</span>
        </div>
      ))}
    </section>
  );
}

function AnalysisPanel({ trace, frame, cards, nobles, humanSeat }: { trace: ReviewTrace; frame: ReviewFrame | null; cards: Map<number, DevelopmentCardData & { id: number }>; nobles: Map<number, { id: number; prestige: number; requirements: number[] }>; humanSeat: number | null }) {
  if (!frame) return null;
  const rows = buildReviewRows(trace, frame).rows;
  const recommended = reviewRecommendedAction(frame.review_result);
  if (trace.reviewer.result_kind === "policy_recommendation") {
    const result = frame.review_result;
    const recommendedAction = recommended as Action;
    const pathLabel = S3_PATH_LABELS[result.decision_path ?? ""] ?? result.decision_path ?? "unknown";
    const proposalLabels: Record<string, string> = {
      recommended_action: "S3 recommendation",
      base_heuristic_action: "Base heuristic",
      n1_proposal: "n1 proposal",
      m07_proposal: "M07 proposal",
    };
    const proposalRows = rows as Array<{ role: string; action: Action | null; evaluated: boolean; actual: boolean; recommended: boolean }>;
    return (
      <div>
        <div className="analysis-header">
          <div><span className="section-kicker">POLICY RECOMMENDATION</span><h2>{trace.reviewer.display_name}</h2></div>
          <span className="budget">D={trace.reviewer.config.determinizations} · P={trace.reviewer.config.ply_cap} · no utility</span>
        </div>
        <div className="legend"><span><i className="actual-marker">★</i> recorded</span><span><i className="best-marker">▲</i> S3 recommendation</span></div>
        <div className="analysis-table" role="table" aria-label="S3 policy recommendation">
          <div className="analysis-row determinization table-head" role="row"><span>Proposal</span><span>Action</span><span>Recorded</span><span>S3</span></div>
          {proposalRows.map((row) => (
            <div className={`analysis-row determinization ${row.actual ? "actual-row" : ""} ${row.recommended ? "best-row" : ""}`} role="row" key={row.role}>
              <span className="action-name"><i>{row.actual ? "★" : row.recommended ? "▲" : ""}</i>{proposalLabels[row.role] ?? row.role}</span>
              <div className="action-name">{row.action ? <StructuredAction action={row.action} playerView={frame.player_view} cards={cards} nobles={nobles} variant="compact" /> : "Not evaluated"}</div>
              <span className="q-value">{row.actual ? "★" : "—"}</span>
              <span className="q-value">{row.recommended ? "▲" : "—"}</span>
            </div>
          ))}
        </div>
        <ActionVerdict
          frame={frame}
          humanSeat={humanSeat}
          recommended={recommendedAction}
          cards={cards}
          nobles={nobles}
          matchLabel="MATCHES S3 RECOMMENDATION"
          differLabel="S3 RECOMMENDS ANOTHER ACTION"
        />
        <div className="decision-summary">
          <p>Decision path <strong>{pathLabel}</strong></p>
        </div>
      </div>
    );
  }
  if (trace.reviewer.result_kind === "root_determinization") {
    const scoredRows = rows as Array<{ action: Action; actual: boolean; recommended: boolean; meanUtility: number; utilityGap: number; actionRank: number }>;
    return (
      <div>
        <div className="analysis-header">
          <div><span className="section-kicker">ACTION ANALYSIS</span><h2>{trace.reviewer.display_name}</h2></div>
          <span className="budget">mean utility · {frame.review_result.sample_count} samples</span>
        </div>
        <div className="legend"><span><i className="actual-marker">★</i> actual</span><span><i className="best-marker">▲</i> recommended</span></div>
        <div className="analysis-table" role="table" aria-label="Root determinization analysis">
          <div className="analysis-row determinization table-head" role="row"><span>Action</span><span>Mean utility</span><span>Utility gap</span><span>Rank</span></div>
          {scoredRows.map((row) => (
            <div className={`analysis-row determinization ${row.actual ? "actual-row" : ""} ${row.recommended ? "best-row" : ""}`} role="row" key={actionKey(row.action)}>
              <div className="action-name"><i>{row.actual ? "★" : row.recommended ? "▲" : ""}</i><StructuredAction action={row.action} playerView={frame.player_view} cards={cards} nobles={nobles} variant="compact" /></div>
              <span className="q-value">{row.meanUtility.toFixed(0)}</span>
              <span className={`delta ${row.utilityGap === 0 ? "best" : ""}`}>{row.utilityGap === 0 ? "BEST" : row.utilityGap.toFixed(0)}</span>
              <span className="q-value">{row.actionRank} / {rows.length}</span>
            </div>
          ))}
        </div>
        <ActionVerdict
          frame={frame}
          humanSeat={humanSeat}
          recommended={recommended}
          cards={cards}
          nobles={nobles}
          matchLabel="REVIEWER AGREED"
          differLabel="REVIEWER DISAGREED"
        />
      </div>
    );
  }
  const neuralRows = rows as Array<{ action: Action; actual: boolean; searchChoice: boolean; highestQ: boolean; prior: number; visit: number; q: number | null; qGap: number | null; unscored: boolean }>;
  return (
    <div>
      <div className="analysis-header">
        <div><span className="section-kicker">ACTION ANALYSIS</span><h2>{trace.reviewer.display_name}</h2></div>
        <span className="budget">{trace.reviewer.config.simulations} sims · d{trace.reviewer.config.max_depth_turns}</span>
      </div>
      <div className="rejected-warning">Experimental reviewer · formal promotion rejected. Q is a model value estimate, not a calibrated win probability.</div>
      <div className="legend"><span><i className="actual-marker">★</i> actual</span><span><i className="best-marker">▲</i> search choice</span><span><i className="best-marker">◆</i> highest visited Q</span></div>
      <div className="analysis-table" role="table" aria-label="Neural ISMCTS analysis">
        <div className="analysis-row table-head" role="row"><span>Action</span><span>Prior</span><span>Visit</span><span>Q(P{frame.actor})</span><span>Q gap</span></div>
        {neuralRows.map((row) => (
          <div className={`analysis-row ${row.actual ? "actual-row" : ""} ${row.searchChoice ? "best-row" : ""} ${row.highestQ ? "highest-q-row" : ""}`} role="row" key={actionKey(row.action)}>
            <div className="action-name"><i>{row.actual ? "★" : ""}{row.searchChoice ? "▲" : ""}{row.highestQ ? "◆" : ""}</i><StructuredAction action={row.action} playerView={frame.player_view} cards={cards} nobles={nobles} variant="compact" /></div>
            <MetricBar value={row.prior} tone="prior" />
            <MetricBar value={row.visit} tone="visit" />
            <span className="q-value">{row.q === null ? "UNSCORED" : row.q.toFixed(3)}</span>
            <span className="delta">{row.qGap === null ? "UNSCORED" : row.qGap === 0 ? "BEST" : row.qGap.toFixed(3)}</span>
          </div>
        ))}
      </div>
      <ActionVerdict
        frame={frame}
        humanSeat={humanSeat}
        recommended={recommended}
        cards={cards}
        nobles={nobles}
        matchLabel="SEARCH AGREED"
        differLabel="SEARCH DISAGREED"
      />
    </div>
  );
}

/**
 * The recorded action and the reviewer's recommendation through one renderer.
 *
 * This is the point of the review page: "what you played" and "what S3 recommends"
 * must be visually comparable. When the two used different renderers — a coloured
 * card face on one side and the string "Buy T2 slot 3" on the other — the
 * comparison the page exists to support was the hardest thing to read. Both sides
 * now go through `StructuredAction` at the same variant, against the same
 * pre-action player view, so identical actions produce identical DOM.
 */
function ActionVerdict({
  frame,
  humanSeat,
  recommended,
  cards,
  nobles,
  matchLabel,
  differLabel,
}: {
  frame: ReviewFrame;
  humanSeat: number | null;
  recommended: Action | null;
  cards: ActionCatalog["cards"];
  nobles: ActionCatalog["nobles"];
  matchLabel: string;
  differLabel: string;
}) {
  const playerView = frame.player_view as ActionPlayerView;
  return (
    <div className="action-duo">
      <div className="action-duo-row">
        <span className="section-kicker">{humanSeat !== null && frame.actor === humanSeat ? "YOU PLAYED" : `P${frame.actor} PLAYED`}</span>
        <StructuredAction action={frame.recorded_action} playerView={playerView} cards={cards} nobles={nobles} />
      </div>
      {recommended ? (
        <div className="action-duo-row">
          <span className="section-kicker">REVIEWER RECOMMENDS</span>
          <StructuredAction action={recommended} playerView={playerView} cards={cards} nobles={nobles} />
        </div>
      ) : null}
      <span className={`action-verdict ${frame.recommended_matches_recorded ? "match" : "differ"}`}>
        {frame.recommended_matches_recorded ? matchLabel : differLabel}
      </span>
    </div>
  );
}

function MetricBar({ value, tone }: { value: number; tone: "prior" | "visit" }) {
  return <span className="metric"><span>{(value * 100).toFixed(1)}%</span><i><b className={tone} style={{ width: `${Math.min(100, value * 100)}%` }} /></i></span>;
}
