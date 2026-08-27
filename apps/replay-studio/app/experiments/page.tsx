"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BoardPanel,
  ReplayTimeline,
  simpleActionLabel,
  usePlyNavigation,
  type Action,
  type CardId,
  type NobleId,
  type PlayerId,
  type PlayerView,
} from "../components/replay-board";
import {
  STATUS_LABEL,
  buildExperimentsQuery,
  createDeepLinkHydration,
  filterMatches,
  filterPairings,
  isBrowsableAvailability,
  isStepDisabled,
  stepCandidateDecision,
  validateExperimentBundle,
} from "../experiment-runtime.mjs";

const API = "http://127.0.0.1:43120";
const CATALOG_URL = `${API}/catalog`;

type Availability = "valid" | "excluded_prefix" | "nontermination" | "not_started";

type PairingIndexEntry = {
  evaluation_id: string;
  candidate_model_id: string;
  opponent_model_id: string;
  status: string;
  scheduled_matches: number;
  browsable_replays: number;
  label: string;
  series: string;
  completed_before_abort?: number;
  nontermination_match_slot?: string;
  not_started_after_abort?: number;
};

type ExperimentIndexEntry = {
  id: string;
  display_name: string;
  description: string;
  tracked_result: string;
  pairings: PairingIndexEntry[];
};

type ExperimentIndex = {
  format: string;
  version: number;
  experiments: ExperimentIndexEntry[];
};

type MatchSlot = {
  match_index: number;
  game_id: string;
  seed_index: number;
  rotation: number;
  availability: Availability;
  seed?: number;
  candidate_seat?: number;
  opponent_seat?: number;
  scores?: number[];
  winner_seats?: number[];
  completed_plies?: number;
  end_reason?: string;
  candidate_won?: boolean;
  replay_document_hash?: string;
};

type PairingMatches = {
  format: string;
  version: number;
  experiment_id: string;
  evaluation_id: string;
  candidate_model_id: string;
  opponent_model_id: string;
  pairing_status: string;
  scheduled_matches: number;
  matches: MatchSlot[];
};

type BundleFrame = {
  ply: number;
  actor: PlayerId;
  actor_model: string;
  actor_seat: number;
  candidate_acted: boolean;
  recorded_action: Action;
  legal_actions: Action[];
  player_view: PlayerView;
  referee_reveal: {
    seed: number;
    decks: CardId[][];
    players: Array<{ id: PlayerId; reserved: Array<{ card: CardId; from_deck: boolean }> }>;
  };
};

type ExperimentReplayBundle = {
  format: string;
  version: number;
  experiment_id: string;
  evaluation_id: string;
  candidate_model_id: string;
  opponent_model_id: string;
  pairing_status: string;
  availability: Availability;
  match_index: number;
  game_id: string;
  replay_document_hash: string;
  result?: { scores: number[]; winners: number[]; reason: string };
  frames: BundleFrame[];
};

type CatalogCard = { id: CardId; tier: string; bonus: string; prestige: number; cost: number[] };
type CatalogNoble = { id: NobleId; prestige: number; requirements: number[] };

function availabilityTone(availability: Availability): string {
  if (availability === "valid") return "avail-valid";
  if (availability === "excluded_prefix") return "avail-prefix";
  return "avail-none";
}

export default function ExperimentsPage() {
  const [index, setIndex] = useState<ExperimentIndex | null>(null);
  const [error, setError] = useState("");
  const [selectedExperiment, setSelectedExperiment] = useState("");
  const [selectedPairing, setSelectedPairing] = useState("");
  const [pairing, setPairing] = useState<PairingMatches | null>(null);
  const [selectedMatch, setSelectedMatch] = useState<number | null>(null);
  const [bundle, setBundle] = useState<ExperimentReplayBundle | null>(null);
  const [catalog, setCatalog] = useState<{ cards: CatalogCard[]; nobles: CatalogNoble[] } | null>(null);
  const [frameIndex, setFrameIndex] = useState(0);
  const [reveal, setReveal] = useState(false);
  const [revealArmed, setRevealArmed] = useState(false);
  const [candidateOnly, setCandidateOnly] = useState(false);
  const [filterText, setFilterText] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | Availability>("all");
  // Deep-link hydration: the initial query is captured once at first
  // render and applied after the experiment index loads; URL sync stays
  // disabled until the initial deep link has been fully applied so it
  // cannot clobber it (the sync effect would otherwise rewrite the URL
  // from the still-empty selection state during the async bootstrap).
  const [deepLinkReady, setDeepLinkReady] = useState(false);
  const capturedQuery = useMemo(
    () => (typeof window === "undefined" ? null : new URLSearchParams(window.location.search)),
    [],
  );

  // ---- bootstrap: index + catalog ----
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [indexResponse, catalogResponse] = await Promise.all([
          fetch(`${API}/experiment-replays`),
          fetch(CATALOG_URL),
        ]);
        if (!indexResponse.ok) throw new Error(`experiment index failed (${indexResponse.status})`);
        if (!catalogResponse.ok) throw new Error(`catalog failed (${catalogResponse.status})`);
        const indexData = (await indexResponse.json()) as ExperimentIndex;
        const catalogData = (await catalogResponse.json()) as { cards: CatalogCard[]; nobles: CatalogNoble[] };
        if (cancelled) return;
        setIndex(indexData);
        setCatalog(catalogData);
        const params = capturedQuery ?? new URLSearchParams(window.location.search);
        const experiment = params.get("experiment") ?? indexData.experiments[0]?.id ?? "";
        setSelectedExperiment(experiment);
      } catch (cause) {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Failed to load experiment replays.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [capturedQuery]);

  const currentExperiment = useMemo(
    () => index?.experiments.find((experiment) => experiment.id === selectedExperiment) ?? null,
    [index, selectedExperiment],
  );

  // ---- deep link: ?experiment=..&pairing=..&match=N ----
  // Uses the query captured at first render (the bootstrap's async
  // fetches give the URL-sync effect a window in which the live query may
  // already have been rewritten), and marks hydration complete so the sync
  // effect below takes over only afterwards.
  useEffect(() => {
    if (!currentExperiment) return;
    const selection = createDeepLinkHydration(capturedQuery).apply(index);
    if (selection) {
      queueMicrotask(() => {
        setSelectedPairing(selection.pairing);
        if (selection.match != null) setSelectedMatch(selection.match);
      });
    }
    queueMicrotask(() => setDeepLinkReady(true));
  }, [currentExperiment, capturedQuery, index]);

  // ---- load pairing matches ----
  useEffect(() => {
    if (!selectedExperiment || !selectedPairing) return;
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch(
          `${API}/experiment-replays/${selectedExperiment}/pairings/${selectedPairing}/matches`,
        );
        const text = await response.text();
        if (cancelled) return;
        if (!response.ok) throw new Error(JSON.parse(text)?.error ?? `pairing load failed (${response.status})`);
        const data = JSON.parse(text) as PairingMatches;
        if (cancelled) return;
        setPairing(data);
        setError("");
      } catch (cause) {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Failed to load pairing.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedExperiment, selectedPairing]);

  // Clear the stale pairing whenever the selection becomes empty.
  useEffect(() => {
    if (!selectedExperiment || !selectedPairing) {
      const timer = setTimeout(() => setPairing(null), 0);
      return () => clearTimeout(timer);
    }
  }, [selectedExperiment, selectedPairing]);

  // ---- load match bundle ----
  useEffect(() => {
    if (!selectedExperiment || !selectedPairing || selectedMatch == null) return;
    let cancelled = false;
    (async () => {
      try {
        const response = await fetch(
          `${API}/experiment-replays/${selectedExperiment}/pairings/${selectedPairing}/matches/${selectedMatch}/bundle`,
        );
        const text = await response.text();
        if (cancelled) return;
        if (!response.ok) throw new Error(JSON.parse(text)?.error ?? `bundle load failed (${response.status})`);
        const data = validateExperimentBundle(JSON.parse(text)) as ExperimentReplayBundle;
        if (cancelled) return;
        setBundle(data);
        setFrameIndex(0);
        setReveal(false);
        setRevealArmed(false);
        setError("");
      } catch (cause) {
        if (!cancelled) {
          setBundle(null);
          setError(cause instanceof Error ? cause.message : "Failed to load match bundle.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedExperiment, selectedPairing, selectedMatch]);

  // Clear the stale bundle whenever no match is selected.
  useEffect(() => {
    if (selectedMatch == null) {
      const timer = setTimeout(() => setBundle(null), 0);
      return () => clearTimeout(timer);
    }
  }, [selectedMatch]);

  // ---- deep-link sync (only after the initial deep link has hydrated) ----
  useEffect(() => {
    if (!deepLinkReady) return;
    const url = buildExperimentsQuery({
      experiment: selectedExperiment,
      pairing: selectedPairing,
      match: selectedMatch,
    });
    window.history.replaceState(null, "", url);
  }, [deepLinkReady, selectedExperiment, selectedPairing, selectedMatch]);

  // ---- navigation ----
  const frame = bundle?.frames[frameIndex] ?? null;
  const changeFrame = useCallback(
    (next: number) => {
      if (!bundle) return;
      setFrameIndex(Math.max(0, Math.min(bundle.frames.length - 1, next)));
    },
    [bundle],
  );
  const stepPly = useCallback(
    (delta: number) => {
      if (!bundle) return;
      setFrameIndex((current) =>
        candidateOnly
          ? stepCandidateDecision(bundle.frames, current, delta)
          : Math.max(0, Math.min(bundle.frames.length - 1, current + delta)),
      );
    },
    [bundle, candidateOnly],
  );
  usePlyNavigation(bundle?.frames.length ?? 0, stepPly);

  // Step buttons disable exactly when stepping would not change the
  // position (boundary case in candidate-only mode; first/last ply in
  // plain mode) — shared logic with the runtime tests.
  const stepDisabled = (delta: number): boolean =>
    isStepDisabled(bundle?.frames ?? [], frameIndex, delta, candidateOnly);

  const stepButton = stepPly;

  // ---- filters ----
  const visiblePairings = useMemo(
    () => (currentExperiment ? filterPairings(currentExperiment.pairings, { query: filterText, status: statusFilter }) : []),
    [currentExperiment, filterText, statusFilter],
  );

  const visibleMatches = useMemo(
    () => (pairing ? filterMatches(pairing.matches, { status: statusFilter }) : []),
    [pairing, statusFilter],
  );

  const cards = useMemo(() => {
    const map = new Map<number, CatalogCard>();
    catalog?.cards.forEach((card) => map.set(card.id, card));
    return map;
  }, [catalog]);
  const nobles = useMemo(() => {
    const map = new Map<number, CatalogNoble>();
    catalog?.nobles.forEach((noble) => map.set(noble.id, noble));
    return map;
  }, [catalog]);

  const candidateSeatsLabel = (slot: MatchSlot) =>
    slot.candidate_seat == null ? "" : `${pairing?.candidate_model_id ?? "C"} @ P${slot.candidate_seat} · ${pairing?.opponent_model_id ?? "O"} @ P${slot.opponent_seat}`;

  return (
    <main className="studio experiments-page">
      <header className="topbar">
        <div className="brand-block">
          <span className="eyebrow">EFFECTIVE SPLENDOR · M36A</span>
          <h1>Experiment Replay Library</h1>
        </div>
        <div className="match-meta">
          <span className="status-dot" aria-hidden="true" />
          <span>{currentExperiment ? `${currentExperiment.display_name} · ${currentExperiment.pairings.length} pairings` : "loading…"}</span>
        </div>
        <div className="header-actions">
          <Link className="studio-link" href="/">Replay Studio</Link>
          <a className="studio-link" href="/play">Play vs AI</a>
        </div>
      </header>

      {error && <div className="error-banner" role="alert">{error}</div>}

      <section className="experiments-grid">
        {/* Column 1: experiments + pairings */}
        <div className="experiments-column pairings-column">
          <div className="panel-heading">
            <div>
              <span className="section-kicker">EXPERIMENTS</span>
              <h2>{currentExperiment?.display_name ?? "—"}</h2>
            </div>
          </div>
          <input
            className="experiments-search"
            type="search"
            placeholder="Filter pairings (model, opponent…)"
            value={filterText}
            onChange={(event) => setFilterText(event.target.value)}
            aria-label="Filter pairings"
          />
          <select
            className="experiments-search"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value as typeof statusFilter)}
            aria-label="Filter by status"
          >
            <option value="all">All statuses</option>
            <option value="valid">VALID (formal)</option>
            <option value="excluded_prefix">EXCLUDED_PREFIX</option>
            <option value="nontermination">NONTERMINATION</option>
          </select>
          <ul className="pairing-list">
            {visiblePairings.map((entry) => (
              <li key={entry.evaluation_id}>
                <button
                  className={`pairing-item ${entry.evaluation_id === selectedPairing ? "selected" : ""}`}
                  onClick={() => {
                    setSelectedPairing(entry.evaluation_id);
                    setSelectedMatch(null);
                  }}
                >
                  <span className="pairing-label">{entry.label}</span>
                  <span className={`pairing-status status-${entry.status.toLowerCase()}`}>{entry.status}</span>
                  <small>
                    {entry.status === "VALID"
                      ? `${entry.browsable_replays} replays`
                      : `${entry.completed_before_abort ?? 0} prefix · 1 nontermination`}
                  </small>
                </button>
              </li>
            ))}
          </ul>
        </div>

        {/* Column 2: match list */}
        <div className="experiments-column matches-column">
          <div className="panel-heading">
            <div>
              <span className="section-kicker">MATCHES</span>
              <h2>{pairing ? `${pairing.candidate_model_id} vs ${pairing.opponent_model_id}` : "select a pairing"}</h2>
            </div>
            {pairing && <span className="budget">{pairing.pairing_status}</span>}
          </div>
          {pairing && pairing.pairing_status !== "VALID" && (
            <div className="warning-banner" role="alert">
              EXCLUDED_PREFIX PAIRING — this run aborted on the engine ply limit. Completed replays below are
              preserved as evidence and are NOT part of the formal {pairing.scheduled_matches}-game result.
              {pairing.matches.find((m) => m.availability === "nontermination") && (
                <> The slot {pairing.matches.find((m) => m.availability === "nontermination")!.game_id} hit the
                deterministic 10,000-ply limit and has no replay.</>
              )}
            </div>
          )}
          <ul className="match-list">
            {visibleMatches.map((slot) => {
              const browsable = isBrowsableAvailability(slot.availability);
              return (
                <li key={slot.match_index}>
                  <button
                    className={`match-item ${slot.match_index === selectedMatch ? "selected" : ""} ${availabilityTone(slot.availability)}`}
                    onClick={() => setSelectedMatch(browsable ? slot.match_index : null)}
                    disabled={!browsable}
                    title={browsable ? slot.game_id : STATUS_LABEL[slot.availability]}
                  >
                    <span className="match-id">s{String(slot.seed_index).padStart(6, "0")}-r{String(slot.rotation).padStart(2, "0")}</span>
                    <span className={`availability ${availabilityTone(slot.availability)}`}>{STATUS_LABEL[slot.availability]}</span>
                    {slot.scores && (
                      <span className="match-score">
                        {slot.scores[0]}–{slot.scores[1]} {slot.candidate_won ? "· candidate won" : "· candidate lost"}
                      </span>
                    )}
                    <small>{candidateSeatsLabel(slot)}{slot.completed_plies != null ? ` · ${slot.completed_plies} plies` : ""}</small>
                  </button>
                </li>
              );
            })}
            {!pairing && <li className="match-empty">Select a pairing to list its 64 scheduled match slots.</li>}
          </ul>
        </div>

        {/* Column 3: replay board */}
        <div className="experiments-column board-column">
          {bundle ? (
            <>
              <div className="panel-heading">
                <div>
                  <span className="section-kicker">REPLAY</span>
                  <h2>{bundle.game_id}</h2>
                </div>
                <div className="view-switch" role="group" aria-label="Information perspective">
                  <button className={!reveal ? "active" : ""} onClick={() => { setReveal(false); setRevealArmed(false); }}>Player view</button>
                  <button
                    className={reveal ? "active reveal-active" : ""}
                    onClick={() => {
                      if (reveal) { setReveal(false); setRevealArmed(false); }
                      else if (revealArmed) setReveal(true);
                      else setRevealArmed(true);
                    }}
                  >
                    {reveal ? "Referee reveal" : revealArmed ? "Confirm reveal" : "Referee reveal"}
                  </button>
                </div>
              </div>

              {bundle.availability === "excluded_prefix" && (
                <div className="warning-banner" role="alert">
                  EXCLUDED_PREFIX / NOT_SCORED — this replay belongs to an aborted pairing prefix and must not be
                  counted toward formal results.
                </div>
              )}

              {frame && (
                <BoardPanel
                  frame={frame}
                  cards={cards}
                  nobles={nobles}
                  reveal={reveal}
                  actorLabel={`${frame.actor_model} · P${frame.actor_seat}`}
                />
              )}

              <aside className="experiments-decision">
                <span className="section-kicker">RECORDED DECISION</span>
                <h2>{frame ? simpleActionLabel(frame.recorded_action) : "—"}</h2>
                <p>
                  Actor <strong>{frame ? `${frame.actor_model} (P${frame.actor_seat})` : "—"}</strong> at ply{" "}
                  {frame?.ply ?? "—"}, chosen from {frame?.legal_actions.length ?? 0} server-certified legal actions.
                </p>
                <code>{frame ? JSON.stringify(frame.recorded_action, null, 2) : ""}</code>
                <label className="candidate-only-toggle">
                  <input
                    type="checkbox"
                    checked={candidateOnly}
                    onChange={(event) => setCandidateOnly(event.target.checked)}
                  />
                  {bundle.candidate_model_id} decisions only
                </label>
                <div className="decision-nav">
                  <button
                    className="icon-button"
                    onClick={() => stepButton(-1)}
                    disabled={stepDisabled(-1)}
                    aria-label="Previous ply"
                  >
                    ←
                  </button>
                  <button
                    className="icon-button"
                    onClick={() => stepButton(1)}
                    disabled={stepDisabled(1)}
                    aria-label="Next ply"
                  >
                    →
                  </button>
                </div>
                {bundle.result && (
                  <div className="final-score">
                    Final: {bundle.result.scores.join(" – ")} · winners {bundle.result.winners.map((w) => `P${w}`).join(", ")} · {bundle.result.reason}
                  </div>
                )}
              </aside>
            </>
          ) : (
            <div className="experiments-empty">
              <span className="section-kicker">REPLAY</span>
              <h2>No match selected</h2>
              <p>Select a browsable match (VALID or EXCLUDED_PREFIX) to load its verified replay bundle.</p>
            </div>
          )}
        </div>
      </section>

      {bundle && frame && (
        <ReplayTimeline
          frames={bundle.frames}
          frameIndex={frameIndex}
          onSeek={changeFrame}
          isCandidatePly={(item) => item.candidate_acted}
          title="← → keyboard navigation"
          footnote={`${bundle.candidate_model_id} plies highlighted${candidateOnly ? " · candidate-only stepping" : ""}`}
        />
      )}
    </main>
  );
}
