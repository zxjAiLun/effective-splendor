//! Shared runtime orchestration: produce one occurrence, then complete it.
//!
//! This module is the single producer authority. Both callers are adapters:
//! `completion_wiring_command` maps the typed outcome onto the frozen CLI exit
//! codes and stdout, and the Studio Host maps it onto an HTTP response. Neither
//! reimplements the publish order or the completion chain, and **nothing here
//! prints, and nothing here knows about exit codes, command names or HTTP**.
//!
//! The invariants the adapters depend on:
//!
//! * the configuration bytes handed in are the bytes that are parsed, run and
//!   persisted, so `config_sha256` always attests the configuration the runner
//!   actually consumed;
//! * the four evidence documents are durable before completion is attempted — the
//!   completion step re-reads them from disk, so "durable first" is enforced by
//!   construction rather than by ordering discipline — and a failed publish rolls
//!   back whatever it already wrote;
//! * an occurrence whose evidence is already on disk is completed **from those
//!   documents**: the arena is never re-run, and the caller's current registry,
//!   agent commands and timeouts are never consulted for an occurrence that
//!   already happened (see [`occurrence_slot`] and
//!   [`complete_persisted_occurrence`]).

use std::fmt;
use std::path::{Path, PathBuf};

use splendor_arena::{ArenaOutcomeV1, ArenaReportV1, ArenaRunner};
use splendor_replay::ReplayV1;
use splendor_studio_league::{
    complete_runtime_occurrence, now_epoch_seconds, open_completion_league,
    parse_runtime_occurrence, replay_document_sha256, CompletionOutcomeV1, CompletionRequestV1,
    IngestOutcome, RuntimeOccurrenceV1, StudioLeaguePathsV1, RUNTIME_OCCURRENCE_FORMAT,
};

use crate::atomic_output;

/// Protocol file names inside one occurrence evidence directory.
const EVIDENCE_CONFIG_NAME: &str = "config.json";
const EVIDENCE_REPLAY_NAME: &str = "replay.json";
const EVIDENCE_REPORT_NAME: &str = "report.json";
const EVIDENCE_OCCURRENCE_NAME: &str = "occurrence.json";

/// The four durable documents of one occurrence, wherever the caller keeps them.
///
/// The CLI supplies four paths it was given; the Host derives them from
/// [`StudioLeaguePathsV1::occurrence_dir`]. They travel as one value because the
/// publish order, the retry read-back and the integrity checks all treat them as
/// a single evidence set — four loose path arguments is how one of them ends up
/// replaced by the caller's own choice.
#[derive(Debug, Clone)]
pub(crate) struct OccurrenceEvidence {
    pub(crate) config: PathBuf,
    pub(crate) replay: PathBuf,
    pub(crate) report: PathBuf,
    pub(crate) occurrence: PathBuf,
}

impl OccurrenceEvidence {
    /// The four documents inside one directory, under the protocol file names.
    pub(crate) fn in_dir(dir: &Path) -> Self {
        Self {
            config: dir.join(EVIDENCE_CONFIG_NAME),
            replay: dir.join(EVIDENCE_REPLAY_NAME),
            report: dir.join(EVIDENCE_REPORT_NAME),
            occurrence: dir.join(EVIDENCE_OCCURRENCE_NAME),
        }
    }

    /// Every document path, in publish order.
    pub(crate) fn all(&self) -> [&Path; 4] {
        [&self.config, &self.replay, &self.report, &self.occurrence]
    }

    /// `true` when all four documents are present, i.e. the occurrence is
    /// complete on disk and must be completed from them rather than re-run.
    pub(crate) fn is_complete(&self) -> bool {
        self.all().iter().all(|path| path.is_file())
    }

    /// `true` when any document exists at all.
    pub(crate) fn any_exists(&self) -> bool {
        self.all().iter().any(|path| path.exists())
    }
}

/// What an occurrence slot on disk holds, decided before anything is run.
///
/// Callers branch on this instead of probing for files themselves: the "already
/// complete means never re-run" rule is the whole point of the retry path, and it
/// belongs in one place.
#[derive(Debug, PartialEq, Eq)]
pub(crate) enum OccurrenceSlotV1 {
    /// Nothing is there: a fresh occurrence may be produced.
    Empty,
    /// All four documents are there: complete from them, never re-run.
    Complete,
    /// A settled report and **nothing else**: the arena already decided this
    /// occurrence without completing it. Report the recorded fact, never re-run.
    /// Any other document beside the report makes the slot ambiguous instead.
    SettledWithoutCompletion { match_status: &'static str },
    /// Anything else — a partial or unrecognised set. Nothing may be run, and
    /// nothing may be overwritten.
    Ambiguous(String),
}

/// Classify an occurrence slot. Pure inspection: it reads, and never writes.
pub(crate) fn occurrence_slot(evidence: &OccurrenceEvidence) -> OccurrenceSlotV1 {
    if !evidence.any_exists() {
        return OccurrenceSlotV1::Empty;
    }
    if evidence.is_complete() {
        return OccurrenceSlotV1::Complete;
    }
    // A settled, non-completed match is only settled when the report is the **only**
    // document in the slot. The moment any other document is present the slot is no
    // longer the normal aborted shape: it is a partial evidence set, and reading it
    // as a recorded fact would answer a request for a match that was never settled
    // in that shape. It must be refused instead.
    let strays = [
        ("config.json", &evidence.config),
        ("replay.json", &evidence.replay),
        ("occurrence.json", &evidence.occurrence),
    ]
    .into_iter()
    .filter(|(_, path)| path.exists())
    .map(|(name, _)| name)
    .collect::<Vec<_>>();
    if !strays.is_empty() {
        return OccurrenceSlotV1::Ambiguous(format!(
            "the occurrence slot holds a partial evidence set ({} present alongside the report); it is neither a complete occurrence nor a settled, non-completed match",
            strays.join(", ")
        ));
    }
    match std::fs::read(&evidence.report) {
        Ok(bytes) => match serde_json::from_slice::<ArenaReportV1>(&bytes) {
            Ok(report) => match &report.outcome {
                // A settled, non-completed match. The arena's own status is
                // carried through verbatim so a caller never has to call a
                // truncated match "aborted".
                ArenaOutcomeV1::Aborted { .. } => OccurrenceSlotV1::SettledWithoutCompletion {
                    match_status: "aborted",
                },
                ArenaOutcomeV1::Truncated { .. } => OccurrenceSlotV1::SettledWithoutCompletion {
                    match_status: "truncated",
                },
                // A completed report without its envelope is a broken evidence
                // set: completing is impossible and re-running would duplicate.
                ArenaOutcomeV1::Completed { .. } => OccurrenceSlotV1::Ambiguous(
                    "a completed arena report exists without its occurrence envelope".to_string(),
                ),
            },
            Err(error) => OccurrenceSlotV1::Ambiguous(format!(
                "the report at `{}` is not a readable arena report: {error}",
                evidence.report.display()
            )),
        },
        Err(error) => OccurrenceSlotV1::Ambiguous(format!(
            "cannot read the settled match report at `{}`: {error}",
            evidence.report.display()
        )),
    }
}

/// Why orchestration could not produce or complete an occurrence.
#[derive(Debug)]
pub(crate) enum RuntimeOrchestrationError {
    /// The inputs are unusable: the configuration does not parse, or the caller
    /// asked for something structurally impossible.
    Invalid(String),
    /// The occurrence slot holds state that is neither empty nor complete, so
    /// running or overwriting it would destroy evidence or duplicate a match.
    Conflict(String),
    /// The arena, the filesystem or the league failed.
    Failed(String),
}

impl fmt::Display for RuntimeOrchestrationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            RuntimeOrchestrationError::Invalid(message)
            | RuntimeOrchestrationError::Conflict(message)
            | RuntimeOrchestrationError::Failed(message) => f.write_str(message),
        }
    }
}

/// What the orchestration did with one occurrence.
///
/// The two axes are deliberately separate: a match can be `completed` while
/// completion `failed`, and reporting that as one thing is exactly the mistake
/// this type exists to prevent.
#[derive(Debug)]
pub(crate) enum RuntimeOrchestrationOutcome {
    /// The arena completed and the league accepted the occurrence — either by
    /// inserting it, or because an identical occurrence was already recorded.
    Completed {
        completion: Box<CompletionOutcomeV1>,
        evidence: OccurrenceEvidence,
    },
    /// The arena completed and all four documents are durable, but Studio
    /// completion failed. The evidence is intact and the occurrence is retryable;
    /// the arena must never be re-run for it.
    CompletionFailed {
        message: String,
        evidence: OccurrenceEvidence,
    },
    /// The arena settled the match without a completed occurrence. The report was
    /// persisted, nothing was booked, and nothing may be re-run.
    Aborted {
        match_status: &'static str,
        evidence: OccurrenceEvidence,
    },
}

impl RuntimeOrchestrationOutcome {
    pub(crate) fn evidence(&self) -> &OccurrenceEvidence {
        match self {
            RuntimeOrchestrationOutcome::Completed { evidence, .. }
            | RuntimeOrchestrationOutcome::CompletionFailed { evidence, .. }
            | RuntimeOrchestrationOutcome::Aborted { evidence, .. } => evidence,
        }
    }

    pub(crate) fn completion(&self) -> Option<&CompletionOutcomeV1> {
        match self {
            RuntimeOrchestrationOutcome::Completed { completion, .. } => Some(completion),
            _ => None,
        }
    }
}

/// Produce a new occurrence and complete it, running the arena at most once.
///
/// The caller has already decided that the slot is empty and has derived
/// `config_bytes` exactly once. This function parses, runs, persists and
/// completes; it never looks up a configuration of its own.
pub(crate) fn produce_and_complete(
    evidence: &OccurrenceEvidence,
    config_bytes: &[u8],
    occurrence_id: &str,
    paths: &StudioLeaguePathsV1,
) -> Result<RuntimeOrchestrationOutcome, RuntimeOrchestrationError> {
    let config = crate::arena_command::parse_config_bytes(config_bytes).map_err(|error| {
        RuntimeOrchestrationError::Invalid(format!("invalid arena configuration: {error}"))
    })?;

    let run = ArenaRunner::run(config)
        .map_err(|error| RuntimeOrchestrationError::Failed(format!("the match failed: {error}")))?;

    // `ArenaRunner::run` yields a replay only for a legal terminal state, so a
    // missing replay is a settled, non-completed match. Its report is the commit
    // marker and nothing is booked for it.
    let Some(replay) = run.replay else {
        persist_aborted_report(&evidence.report, &run.report)?;
        return Ok(RuntimeOrchestrationOutcome::Aborted {
            match_status: arena_match_status(&run.report),
            evidence: evidence.clone(),
        });
    };

    // Publish all four documents. Durability is not asserted here: completion
    // re-reads them from disk below, so an occurrence that was not actually made
    // durable cannot be completed.
    publish_completed_evidence(evidence, occurrence_id, &run.report, &replay, config_bytes)?;

    match complete_persisted_occurrence(evidence, paths, Some(occurrence_id)) {
        Ok(completion) => Ok(RuntimeOrchestrationOutcome::Completed {
            completion: Box::new(completion),
            evidence: evidence.clone(),
        }),
        // The match is a settled fact and its evidence is intact, so this is a
        // completion failure and not a match failure.
        Err(RuntimeOrchestrationError::Failed(message)) => {
            Ok(RuntimeOrchestrationOutcome::CompletionFailed {
                message,
                evidence: evidence.clone(),
            })
        }
        // The evidence just published cannot be read back or does not verify:
        // that is a broken evidence set, not a completion problem.
        Err(other) => Err(other),
    }
}

/// Complete an occurrence from the four documents already on disk.
///
/// This is the only place the orchestration touches the completion outlet, and
/// the only way an occurrence is ever completed. It never runs a match, and it
/// reads nothing but the evidence set — so a retry after a Host restart, with a
/// different registry, different agent commands or different timeouts, still
/// completes exactly the occurrence that happened.
///
/// `expected_occurrence_id` binds the evidence to the occurrence the caller asked
/// for. Internal consistency is not identity: a slot can hold four documents that
/// verify against each other perfectly and still belong to a *different*
/// occurrence. A caller that locates a slot by id therefore passes that id, and a
/// mismatch is a conflict rather than a recorded fact. A caller whose authority is
/// the four documents themselves — the completion-only CLI command, which takes
/// explicit paths rather than a slot — passes `None`.
pub(crate) fn complete_persisted_occurrence(
    evidence: &OccurrenceEvidence,
    paths: &StudioLeaguePathsV1,
    expected_occurrence_id: Option<&str>,
) -> Result<CompletionOutcomeV1, RuntimeOrchestrationError> {
    let occurrence_bytes = read_evidence(&evidence.occurrence, "occurrence envelope")?;
    let occurrence = match parse_runtime_occurrence(&occurrence_bytes) {
        Ok(Some(occurrence)) => occurrence,
        Ok(None) => {
            return Err(RuntimeOrchestrationError::Conflict(format!(
                "`{}` is not an occurrence envelope (format `{RUNTIME_OCCURRENCE_FORMAT}`)",
                evidence.occurrence.display()
            )))
        }
        Err(error) => {
            return Err(RuntimeOrchestrationError::Conflict(format!(
                "invalid occurrence envelope `{}`: {error}",
                evidence.occurrence.display()
            )))
        }
    };
    if let Some(expected) = expected_occurrence_id {
        if occurrence.occurrence_id != expected {
            return Err(RuntimeOrchestrationError::Conflict(format!(
                "this slot's evidence belongs to occurrence `{}`, not to `{expected}`: the documents are internally consistent, but they are not this occurrence's",
                occurrence.occurrence_id
            )));
        }
    }

    let report_bytes = read_evidence(&evidence.report, "arena report")?;
    let replay_bytes = read_evidence(&evidence.replay, "replay")?;
    let config_bytes = read_evidence(&evidence.config, "config snapshot")?;

    // The documents must still be the documents the envelope attests to. These
    // hashes are what make a retry safe: they bind the bytes on disk, not whatever
    // the caller believes it has now.
    for (label, path, bytes, expected) in [
        (
            "config snapshot",
            &evidence.config,
            &config_bytes,
            &occurrence.config_sha256,
        ),
        (
            "replay",
            &evidence.replay,
            &replay_bytes,
            &occurrence.replay_sha256,
        ),
        (
            "arena report",
            &evidence.report,
            &report_bytes,
            &occurrence.report_sha256,
        ),
    ] {
        let actual = replay_document_sha256(bytes);
        if &actual != expected {
            return Err(RuntimeOrchestrationError::Conflict(format!(
                "the {label} at `{}` hashes to {actual}, not the `{expected}` the occurrence envelope records; the evidence set is not coherent",
                path.display()
            )));
        }
    }

    let replay_source_path = evidence.replay.to_string_lossy().replace('\\', "/");
    let request = CompletionRequestV1 {
        occurrence: &occurrence,
        report_bytes: &report_bytes,
        replay_bytes: &replay_bytes,
        config_bytes: &config_bytes,
        replay_source_path: &replay_source_path,
    };

    let mut league = open_completion_league(paths, now_epoch_seconds()).map_err(|error| {
        RuntimeOrchestrationError::Failed(format!("cannot open the league for completion: {error}"))
    })?;
    complete_runtime_occurrence(&mut league, &request)
        .map_err(|error| RuntimeOrchestrationError::Failed(describe_completion_error(&error)))
}

/// The receipt payload both adapters report.
///
/// The CLI writes it to `--json`; the Host embeds it in the response body. One
/// definition, so the two cannot describe the same booking differently.
pub(crate) fn completion_receipt_json(completion: &CompletionOutcomeV1) -> serde_json::Value {
    let record = &completion.record;
    let archived = &completion.archived;
    let receipt = &completion.receipt;
    let (outcome_kind, event_count) = match &completion.ingest {
        IngestOutcome::Inserted { rating_events, .. } => ("inserted", *rating_events),
        IngestOutcome::AlreadyPresent { .. } => ("already_present", 0),
    };
    let eligibility = match &receipt.rating_ineligible_reason {
        Some(reason) => format!("ineligible ({reason})"),
        None => "eligible".to_string(),
    };
    serde_json::json!({
        "source_kind": record.source_kind,
        "source_identity": record.source_identity,
        "source_document_hash": record.source_document_hash,
        "match_id": receipt.match_id,
        "replay": {
            "storage": record.replay.storage().as_str(),
            "document_hash": record.replay.document_hash,
            "path": record.replay.path,
            "archive_outcome": archived.outcome().as_str(),
        },
        "outcome": {
            "kind": outcome_kind,
            "rating_events": event_count,
        },
        "eligibility": eligibility,
        "elo": receipt
            .elo_events
            .iter()
            .map(|event| {
                serde_json::json!({
                    "participant_id": event.participant_id,
                    "elo_before": event.elo_before,
                    "elo_after": event.elo_after,
                })
            })
            .collect::<Vec<_>>(),
    })
}

/// Read one evidence document, classifying a missing or unreadable file as an
/// incoherent evidence set rather than a transient failure.
fn read_evidence(path: &Path, label: &str) -> Result<Vec<u8>, RuntimeOrchestrationError> {
    std::fs::read(path).map_err(|error| {
        RuntimeOrchestrationError::Conflict(format!(
            "cannot read the {label} `{}`: {error}",
            path.display()
        ))
    })
}

/// The arena's own status word for a settled report.
fn arena_match_status(report: &ArenaReportV1) -> &'static str {
    match &report.outcome {
        ArenaOutcomeV1::Completed { .. } => "completed",
        ArenaOutcomeV1::Aborted { .. } => "aborted",
        ArenaOutcomeV1::Truncated { .. } => "truncated",
    }
}

/// Name the failing half: a completion failure never affects the match.
fn describe_completion_error(error: &splendor_studio_league::StudioLeagueError) -> String {
    format!("Studio completion failed (the match itself is unaffected): {error}")
}

/// Publish an aborted match's report only: the occurrence never happened.
fn persist_aborted_report(
    report_path: &Path,
    report: &ArenaReportV1,
) -> Result<(), RuntimeOrchestrationError> {
    let report_json = crate::arena_command::to_pretty_line(report).map_err(|error| {
        RuntimeOrchestrationError::Failed(format!("serialize report failed: {error}"))
    })?;
    atomic_output::commit_aborted_with(report_path, &report_json, atomic_output::publish_new)
        .map_err(|error| {
            RuntimeOrchestrationError::Failed(format!("could not publish aborted report: {error}"))
        })
}

/// Publish config snapshot, replay, report and envelope, in that order.
///
/// The report is published last-but-one because it is `run-match`'s commit
/// marker, and the envelope last because it attests to the other three. If any
/// step fails, everything already written is rolled back: an occurrence whose
/// evidence is incomplete must never look finished, or a later retry would be
/// ambiguous.
fn publish_completed_evidence(
    evidence: &OccurrenceEvidence,
    occurrence_id: &str,
    report: &ArenaReportV1,
    replay: &ReplayV1,
    config_bytes: &[u8],
) -> Result<RuntimeOccurrenceV1, RuntimeOrchestrationError> {
    let replay_final_hash = match &report.outcome {
        ArenaOutcomeV1::Completed {
            replay_final_hash, ..
        } => replay_final_hash.clone(),
        _ => {
            return Err(RuntimeOrchestrationError::Failed(
                "runner returned a replay for a non-completed outcome".to_string(),
            ))
        }
    };
    if replay_final_hash != replay.final_state_hash.as_str() {
        return Err(RuntimeOrchestrationError::Failed(
            "report replay_final_hash does not match replay final_state_hash".to_string(),
        ));
    }
    splendor_replay::verify_replay(replay).map_err(|error| {
        RuntimeOrchestrationError::Failed(format!("replay failed verification: {error}"))
    })?;

    let report_json = crate::arena_command::to_pretty_line(report).map_err(|error| {
        RuntimeOrchestrationError::Failed(format!("serialize report failed: {error}"))
    })?;
    let replay_json = crate::arena_command::to_pretty_line(replay).map_err(|error| {
        RuntimeOrchestrationError::Failed(format!("serialize replay failed: {error}"))
    })?;

    // The hashes must cover the exact published bytes, so hash the serialized
    // documents rather than the in-memory values.
    let report_bytes = report_json.as_bytes().to_vec();
    let replay_bytes = replay_json.as_bytes().to_vec();
    let occurrence = RuntimeOccurrenceV1 {
        format: RUNTIME_OCCURRENCE_FORMAT.to_string(),
        version: splendor_studio_league::RUNTIME_OCCURRENCE_VERSION,
        occurrence_id: occurrence_id.to_string(),
        completed_at: now_epoch_seconds(),
        report_sha256: replay_document_sha256(&report_bytes),
        replay_sha256: replay_document_sha256(&replay_bytes),
        config_sha256: replay_document_sha256(config_bytes),
    };
    let occurrence_json = crate::arena_command::to_pretty_line(&occurrence).map_err(|error| {
        RuntimeOrchestrationError::Failed(format!("serialize occurrence envelope failed: {error}"))
    })?;

    let config_text = std::str::from_utf8(config_bytes).map_err(|_| {
        RuntimeOrchestrationError::Failed(
            "config bytes are not valid UTF-8; cannot persist the config snapshot".to_string(),
        )
    })?;
    if let Err(error) = atomic_output::commit_single(&evidence.config, config_text) {
        return Err(RuntimeOrchestrationError::Failed(format!(
            "could not persist the config snapshot: {error}"
        )));
    }

    if let Err(error) = atomic_output::commit_completed_with(
        &evidence.replay,
        &replay_json,
        &evidence.report,
        &report_json,
        atomic_output::publish_new,
    ) {
        let _ = std::fs::remove_file(&evidence.config);
        return Err(RuntimeOrchestrationError::Failed(format!(
            "could not publish report and replay (config snapshot rolled back): {error}"
        )));
    }

    if let Err(error) = atomic_output::commit_single(&evidence.occurrence, &occurrence_json) {
        let _ = std::fs::remove_file(&evidence.report);
        let _ = std::fs::remove_file(&evidence.replay);
        let _ = std::fs::remove_file(&evidence.config);
        return Err(RuntimeOrchestrationError::Failed(format!(
            "could not publish the occurrence envelope; report, replay and config snapshot rolled back: {error}"
        )));
    }

    Ok(occurrence)
}
