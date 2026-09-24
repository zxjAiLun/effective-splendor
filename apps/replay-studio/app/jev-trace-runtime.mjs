// Pure presentation derivations for the Jev interaction panel.
//
// The panel answers one question per step: what did the agent talk to Jev about
// here, and what came back? Two honesty rules shape everything below.
//
// 1. The replay is the game authority and the journal is only a record of calls.
//    A step is joined by ply plus the pre-action observation hash and confirmed
//    against the action the replay actually recorded; anything that does not line
//    up is reported as a mismatch, never smoothed into a plausible story.
// 2. An absent record is reported as absent. Older runs have no journal at all,
//    and a forced decision has no call by design. Neither becomes a fabricated
//    prompt, and neither hides a call that did happen.
//
// Keeping this logic here (instead of inline in the page) makes both rules
// directly unit-testable and keeps information-boundary decisions in one place.

export const STAGE_LABEL = {
  helper: "Local heuristic terms",
  family: "Stage 1 · choose move family",
  move: "Stage 2 · choose exact action",
  colors: "Gem color probabilities · program maps to a legal take",
  target: "Choose legal card target",
  return: "Choose exact overflow return",
  noble: "Choose eligible noble",
};

/** Which artifact backs a run, and what a reader can do with it. */
export function describeRun(run) {
  const document = run?.game_document ?? "unavailable";
  return {
    runId: typeof run?.run_id === "string" ? run.run_id : "",
    journalRecorded: run?.journal_recorded === true,
    traceSummary: run?.has_trace_summary === true,
    gameDocument: document,
    playable: document === "completed_replay" || document === "truncated_prefix",
    completed: document === "completed_replay",
    // Distinct states a reader must be able to tell apart.
    documentLabel:
      document === "completed_replay"
        ? "Verified completed replay"
        : document === "truncated_prefix"
          ? "Verified truncated prefix (no winner)"
          : "No verified game document",
    status: typeof run?.status === "string" ? run.status : null,
    agentVersion: typeof run?.agent_version === "string" ? run.agent_version : null,
    modelVersions: Array.isArray(run?.model_versions) ? run.model_versions : [],
    decisions: typeof run?.decisions === "number" ? run.decisions : null,
  };
}

/**
 * Decide what the panel shows for one replay step.
 *
 * @param {{ply:number, actor:number, player_view:{viewer:number}, recorded_action:object}} frame
 * @param {{trace?:object|null, config?:object|null}|null} bundle the run trace archive
 */
export function describeStep(frame, bundle) {
  const decisions = bundle?.trace?.decisions ?? null;
  const traceAvailable = Boolean(bundle?.trace);
  const decision = decisions ? decisions[String(frame.ply)] ?? null : null;

  if (!traceAvailable) {
    return {
      kind: "unavailable",
      headline: "Interaction not recorded",
      detail:
        "This run predates the per-call journal, so the requests and answers that produced this step cannot be shown. The recorded action below is still the verified replay's own fact.",
      usable: false,
    };
  }

  const controller = seatOf(bundle?.config);
  if (controller === null || frame.actor !== controller) {
    return {
      kind: "opponent",
      headline: "Not a Jev decision",
      detail: `Player ${frame.actor} was not the Jev seat in this run; no model call belongs to this step.`,
      usable: true,
      stages: [],
    };
  }

  if (!decision) {
    return {
      kind: "missing",
      headline: "No call recorded for this step",
      detail:
        "The Jev seat acted here without a journalled call. A forced single legal move needs no call; a crash can also end a journal early. The journal cannot say which, so this step is left unknown.",
      usable: true,
      stages: [],
    };
  }

  if (decision.observation_hash && frame.observation_hash &&
      decision.observation_hash !== frame.observation_hash) {
    return {
      kind: "mismatch",
      headline: "Trace does not match this position",
      detail:
        "The journal entry for this ply was recorded against a different observation hash than the verified replay position. Treating it as this step's interaction would be wrong, so it is not shown.",
      usable: false,
    };
  }

  const stages = Array.isArray(decision.stages) ? decision.stages : [];
  const selected = decision.selected_action ?? null;
  // The journal's selected action is checked against the action the verified
  // replay recorded; disagreement is surfaced rather than hidden.
  const recorded = frame.recorded_action ?? null;
  const actionAgrees =
    selected === null || recorded === null ? null : sameAction(selected, recorded);

  return {
    kind: actionAgrees === false ? "action_mismatch" : "recorded",
    headline:
      actionAgrees === false
        ? "Recorded action disagrees with the journal"
        : `${stages.filter((s) => s.stage !== "helper").length} Jev call stage(s)`,
    detail:
      actionAgrees === false
        ? "The selected option in the journal does not equal the action in the verified replay. The replay stands; the journal is shown only as diagnostics for this step."
        : null,
    usable: true,
    stages,
    actionAgrees,
    family: decision.family ?? null,
    decisionMode: decision.decision_mode ?? null,
    selectionPath: Array.isArray(decision.selection_path) ? decision.selection_path : null,
    targetRemoved: decision.target_removed ?? null,
    selectedIndex: decision.selected_index ?? null,
    offeredCount: Array.isArray(decision.offered_indices) ? decision.offered_indices.length : null,
    exclusions: {
      noop: decision.noops_removed ?? 0,
      routed: decision.routed_out ?? 0,
      capped: decision.cap_removed ?? 0,
    },
    actionSent: decision.action_sent === true,
  };
}

/** The seat the config actually starts the Jev agent in, or null if unknown. */
export function seatOf(config) {
  const agents = config?.agents;
  if (!Array.isArray(agents)) return null;
  const index = agents.findIndex((agent) => {
    const program = typeof agent?.program === "string" ? agent.program : "";
    return /agent\.py$/.test(program) || (agent?.args ?? []).some((a) => /agent\.py$/.test(String(a)));
  });
  return index < 0 ? null : index;
}

function sameAction(a, b) {
  return normalize(a) === normalize(b);
}

function normalize(action) {
  if (action === null || typeof action !== "object") return JSON.stringify(action);
  return JSON.stringify(
    Object.keys(action)
      .sort()
      .map((key) => [key, action[key]]),
  );
}

/** One-line accounting of tokens actually reported, never assumed free. */
export function usageLine(metrics) {
  if (!metrics || typeof metrics !== "object") return "Usage not recorded";
  const input = Number.isFinite(metrics.input_tokens) ? metrics.input_tokens : null;
  const output = Number.isFinite(metrics.output_tokens) ? metrics.output_tokens : null;
  const unknown = Number.isFinite(metrics.unknown_usage_attempts) ? metrics.unknown_usage_attempts : null;
  const reported = input === null || output === null ? "usage unavailable" : `${input} in / ${output} out`;
  const unknownNote = unknown ? ` · ${unknown} attempt(s) did not report usage` : "";
  return `${reported}${unknownNote}`;
}

/** Summarize one attempt for display, distinguishing outcome from selection. */
export function attemptLines(attempt) {
  if (!attempt || typeof attempt !== "object") return [];
  if (attempt.outcome === "error") {
    return [`Attempt failed: ${attempt.code ?? "unknown"}${attempt.http_status ? ` (HTTP ${attempt.http_status})` : ""}`];
  }
  if (attempt.outcome === "retry_wait") {
    return [`Waiting ${attempt.seconds ?? "?"}s before retry`];
  }
  if (attempt.outcome === "received") {
    const lines = [`Selected ${attempt.selected_id ?? "—"}`];
    if (attempt.returned_model) lines.push(`model ${attempt.returned_model}`);
    if (Number.isFinite(attempt.latency_ms)) lines.push(`${attempt.latency_ms} ms`);
    const usage = attempt.usage;
    if (usage && Number.isFinite(usage.input_tokens) && Number.isFinite(usage.output_tokens)) {
      lines.push(`${usage.input_tokens} in / ${usage.output_tokens} out`);
    } else {
      lines.push("usage not reported for this attempt");
    }
    return lines;
  }
  return [];
}

/** @typedef {ReturnType<typeof describeStep>} StepView */
