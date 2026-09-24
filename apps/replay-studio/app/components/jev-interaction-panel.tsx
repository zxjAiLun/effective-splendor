"use client";

import { attemptLines, STAGE_LABEL } from "../jev-trace-runtime.mjs";

export type TraceAttempt = {
  outcome: string;
  code?: string;
  http_status?: number;
  seconds?: number;
  selected_id?: string | null;
  returned_model?: string | null;
  usage?: { input_tokens?: number; output_tokens?: number } | null;
  probabilities?: Record<string, number> | null;
  confidence?: number | null;
  latency_ms?: number | null;
};

export type TraceStage = {
  stage: "helper" | "family" | "move" | "colors" | "target" | "return" | "noble";
  latency_ms?: number | null;
  requested_model?: string | null;
  payload_sha256?: string | null;
  payload_snapshot?: unknown;
  payload_snapshot_recorded?: boolean;
  candidates?: Record<string, unknown> | null;
  candidate_ids?: string[] | null;
  attempts?: TraceAttempt[];
};

export type StepView = {
  kind: "unavailable" | "opponent" | "missing" | "mismatch" | "recorded" | "action_mismatch";
  headline: string;
  detail: string | null;
  usable: boolean;
  stages?: TraceStage[];
  actionAgrees?: boolean | null;
  family?: string | null;
  decisionMode?: string | null;
  selectionPath?: unknown[] | null;
  targetRemoved?: number | null;
  selectedIndex?: number | null;
  offeredCount?: number | null;
  exclusions?: { noop: number; routed: number; capped: number };
  actionSent?: boolean;
};

/**
 * One step's interaction with Jev.
 *
 * This panel is read-only and never calls a model. It renders what the run's own
 * journal recorded, joined to the verified replay step; when the record is
 * missing or does not line up, it says so instead of filling the gap.
 */
export function JevInteractionPanel({ step }: { step: StepView }) {
  return (
    <section className="jev-trace" aria-label="Jev interaction for this step">
      <div className="analysis-header">
        <div>
          <span className="section-kicker">JEV INTERACTION</span>
          <h2>{step.headline}</h2>
        </div>
        <span className="budget">read-only · no model call</span>
      </div>

      {step.detail ? <p className="jev-trace-note">{step.detail}</p> : null}

      {step.kind === "recorded" || step.kind === "action_mismatch" ? (
        <>
          <dl className="jev-trace-facts">
            {step.family ? (
              <>
                <dt>Chosen family</dt>
                <dd>{step.decisionMode ?? step.family}</dd>
              </>
            ) : null}
            {step.offeredCount === null ? null : (
              <>
                <dt>{step.decisionMode ? "Legal completions for selected target/take" : "Exact actions offered"}</dt>
                <dd>{step.offeredCount}</dd>
              </>
            )}
            {step.exclusions ? (
              <>
                <dt>Excluded before the choice</dt>
                <dd>
                  {step.exclusions.noop} no-op · {step.exclusions.routed} other family ·{" "}
                  {step.exclusions.capped} over cap
                </dd>
              </>
            ) : null}
            <dt>Action delivered</dt>
            <dd>{step.actionSent ? "yes" : "no"}</dd>
          </dl>

          {step.selectionPath ? (
            <details className="jev-request">
              <summary>Recorded program mapping · colors / target / returns</summary>
              <p className="jev-trace-note">
                Color Choice probabilities rank eligible colors; code constructs the take bundle.
                They are not joint-bundle utility or win probability. Returns are separate explicit choices.
                Forced stages have no model response. Other target/take completions: {step.targetRemoved ?? 0}.
              </p>
              <pre>{JSON.stringify(step.selectionPath, null, 2)}</pre>
            </details>
          ) : null}

          {(step.stages ?? []).map((stage, index) => (
            <TraceStageView key={`${stage.stage}-${index}`} stage={stage as TraceStage} />
          ))}
        </>
      ) : null}
    </section>
  );
}

function TraceStageView({ stage }: { stage: TraceStage }) {
  const label = STAGE_LABEL[stage.stage] ?? stage.stage;
  return (
    <article className="jev-stage">
      <header>
        <strong>{label}</strong>
        {Number.isFinite(stage.latency_ms) ? <span>{stage.latency_ms} ms</span> : null}
      </header>

      {stage.stage === "helper" ? (
        <p className="jev-trace-note">
          Local Rust sidecar ran for this decision before any Jev call; its advisory terms are not
          a model answer.
        </p>
      ) : null}

      {Array.isArray(stage.candidate_ids) && stage.candidate_ids.length > 0 ? (
        <details className="jev-stage-candidates">
          <summary>
            {stage.candidate_ids.length} option{stage.candidate_ids.length === 1 ? "" : "s"} sent
          </summary>
          {stage.candidates ? (
            <pre>{JSON.stringify(stage.candidates, null, 2)}</pre>
          ) : (
            <p className="jev-trace-note">Option payload was not recorded for this attempt.</p>
          )}
        </details>
      ) : null}

      <ol className="jev-attempts">
        {(stage.attempts ?? []).map((attempt, index) => (
          <li key={index}>
            {attemptLines(attempt).map((line) => (
              <span key={line}>{line}</span>
            ))}
            {attempt.probabilities ? (
              <details>
                <summary>Choice probabilities · not win probability</summary>
                <pre>{JSON.stringify(attempt.probabilities, null, 2)}</pre>
              </details>
            ) : null}
          </li>
        ))}
      </ol>

      {stage.payload_snapshot_recorded ? (
        <details className="jev-request">
          <summary>Show the request sent to Jev</summary>
          <p className="jev-trace-note">
            Application payload only. Credentials travel in an HTTP header and are never part of
            this body or this record.
          </p>
          <pre>{JSON.stringify(stage.payload_snapshot, null, 2)}</pre>
          {stage.payload_sha256 ? <code>sha256 {stage.payload_sha256}</code> : null}
        </details>
      ) : (
        <p className="jev-trace-note">
          The exact request body was not recorded for this run (it predates request snapshots).
          Only its hash and the option list are available.
        </p>
      )}
    </article>
  );
}
