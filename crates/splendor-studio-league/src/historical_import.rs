//! Historical arena-report resolution and canonical record building.
//!
//! A completed arena report names a terminal state through
//! `outcome.replay_final_hash`. Resolution consults only the duplicate-preserving
//! ReplayV1 content index and then strictly verifies candidates. Source filenames
//! are provenance, never a fallback binding mechanism.
//!
//! Source identity is portable across machines and platforms:
//! `<logical-namespace>/<relative-path>`, never machine-specific physical paths.

use crate::agent_configuration::{
    is_diagnostic_configuration, parse_match_configuration, MatchConfigurationV1,
};
use crate::canonical_league_order;
use crate::error::{Result, StudioLeagueError};
use crate::match_record::{
    MatchStatus, ReplayBindingV1, ReplayStorage, ReplayVerification, SeatPolicyIdentityV1,
    StudioMatchRecordV1, StudioMatchSeatV1,
};
use crate::participant::EngineIdentityV1;
use crate::replay_index::{
    collect_corpus_files, CorpusRoot, ReplayContentCandidateV1, ReplayContentIndexV1,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use splendor_arena::{
    seed_commitment_v1, ArenaOutcomeV1, ArenaReportV1, ARENA_REPORT_FORMAT, ARENA_REPORT_VERSION,
};
use splendor_core::RulesetFingerprint;
use splendor_replay::{verify_replay, ReplayV1};
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::path::Path;
use std::str::FromStr;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum HistoricalReplayResolutionV1 {
    /// A completed report resolved to exact bytes that passed strict ReplayV1
    /// verification and agree with the report's terminal facts.
    Verified {
        candidate: ReplayContentCandidateV1,
        completed_plies: u32,
    },
    /// Aborted and truncated reports legitimately have no ReplayV1 binding.
    ResultOnly,
}

pub fn parse_arena_report(logical_source_path: &str, bytes: &[u8]) -> Result<ArenaReportV1> {
    let report: ArenaReportV1 = serde_json::from_slice(bytes).map_err(|error| {
        StudioLeagueError::Invalid(format!(
            "arena report `{logical_source_path}` failed strict schema parsing: {error}"
        ))
    })?;
    if report.format != ARENA_REPORT_FORMAT || report.version != ARENA_REPORT_VERSION {
        return Err(StudioLeagueError::Invalid(format!(
            "arena report `{logical_source_path}` has unsupported format/version `{}@{}`",
            report.format, report.version
        )));
    }
    Ok(report)
}

pub fn resolve_arena_report_replay(
    report: &ArenaReportV1,
    index: &ReplayContentIndexV1,
) -> Result<HistoricalReplayResolutionV1> {
    let (result, completed_plies, final_hash) = match &report.outcome {
        ArenaOutcomeV1::Completed {
            result,
            completed_plies,
            replay_final_hash,
        } => (result, *completed_plies, replay_final_hash.as_str()),
        ArenaOutcomeV1::Aborted { .. } | ArenaOutcomeV1::Truncated { .. } => {
            return Ok(HistoricalReplayResolutionV1::ResultOnly)
        }
    };

    let candidates = index.candidates(final_hash);
    if candidates.is_empty() {
        return Err(StudioLeagueError::Invalid(format!(
            "completed arena report `{}` has replay_final_hash `{final_hash}`, but the ReplayV1 content index has no candidate",
            report.game_id
        )));
    }

    let mut valid = Vec::new();
    let mut failures = Vec::new();
    for candidate in candidates {
        match verify_candidate(report, result, completed_plies, final_hash, candidate) {
            Ok(()) => valid.push(candidate.clone()),
            Err(error) => failures.push(format!("{}: {error}", candidate.logical_path)),
        }
    }
    if valid.is_empty() {
        return Err(StudioLeagueError::Invalid(format!(
            "completed arena report `{}` resolved {} ReplayV1 candidate(s) by final_state_hash, but none verified: {}",
            report.game_id,
            candidates.len(),
            failures.join("; ")
        )));
    }

    // Freeze selection rule: filter PASS candidates -> sort by document_sha256
    // first -> tie-break by logical_path -> pick first.
    valid.sort_by(|left, right| {
        (&left.document_sha256, &left.logical_path)
            .cmp(&(&right.document_sha256, &right.logical_path))
    });

    Ok(HistoricalReplayResolutionV1::Verified {
        candidate: valid.remove(0),
        completed_plies,
    })
}

/// Build the source-independent ledger record for one historical arena report.
/// Parsing, replay binding, and report/replay consistency live here rather than
/// in `ledger.rs`; the ledger receives only validated canonical records.
pub fn arena_report_to_match_record(
    logical_source_path: &str,
    report_bytes: &[u8],
    replay_index: &ReplayContentIndexV1,
) -> Result<StudioMatchRecordV1> {
    let report = parse_arena_report(logical_source_path, report_bytes)?;
    let resolution = resolve_arena_report_replay(&report, replay_index)?;
    build_match_record_from_parsed(logical_source_path, report_bytes, &report, resolution)
}

pub fn build_match_record_from_parsed(
    logical_source_path: &str,
    report_bytes: &[u8],
    report: &ArenaReportV1,
    resolution: HistoricalReplayResolutionV1,
) -> Result<StudioMatchRecordV1> {
    build_match_record_with_configuration(
        logical_source_path,
        report_bytes,
        report,
        resolution,
        ConfigAssociationV1::NoConfigEvidence,
        OccurrenceNamespaceV1::Historical,
    )
}

/// Build the ledger record for **one just-finished arena occurrence**
/// (Commit C Slice 1), without any corpus scan.
///
/// The caller hands in the three documents the arena harness wrote for this
/// single match: the arena report, the recorded ReplayV1, and the run's own
/// `match-config.json`. The existing authority chain is reused verbatim:
/// strict report parsing, full `verify_replay` of the provided replay bytes
/// plus report/replay fact agreement, the exact configuration bound as
/// companion evidence (with a `seed_commitment` cross-check that the config
/// really is this match's), and the shared per-seat policy attribution.
///
/// Occurrence identity is content-derived
/// (`runtime-sha256:<report document sha256>`); `played_at` stays `None`, so
/// the match joins the same deterministic canonical league order as the
/// historical corpus (a canonical-order Studio Elo, not a chronology).
pub fn runtime_match_record(
    report_bytes: &[u8],
    replay_bytes: &[u8],
    config_bytes: &[u8],
    replay_storage_path: &str,
) -> Result<StudioMatchRecordV1> {
    let report = parse_arena_report("<runtime-occurrence>", report_bytes)?;
    let (result, completed_plies, final_hash) = match &report.outcome {
        ArenaOutcomeV1::Completed {
            result,
            completed_plies,
            replay_final_hash,
        } => (result, *completed_plies, replay_final_hash.as_str()),
        ArenaOutcomeV1::Aborted { .. } | ArenaOutcomeV1::Truncated { .. } => {
            return Err(StudioLeagueError::Invalid(
                "runtime ingestion requires a completed arena report; aborted and truncated occurrences are recorded result-only by the arena and carry no rateable result".to_string(),
            ));
        }
    };

    // Verify the provided replay bytes in place: parse, full verification, and
    // document-hash agreement. No content index and no filename is involved.
    let replay: ReplayV1 = serde_json::from_slice(replay_bytes).map_err(|error| {
        StudioLeagueError::Invalid(format!(
            "runtime replay document failed strict schema parsing: {error}"
        ))
    })?;
    let verified = verify_replay(&replay).map_err(|error| {
        StudioLeagueError::Invalid(format!("runtime replay failed verification: {error}"))
    })?;
    let replay_document_sha = hex::encode(Sha256::digest(replay_bytes));
    let candidate = ReplayContentCandidateV1 {
        final_state_hash: final_hash.to_string(),
        document_sha256: replay_document_sha,
        logical_path: replay_storage_path.to_string(),
        filesystem_path: None,
    };
    check_candidate_facts(
        &report,
        result,
        completed_plies,
        final_hash,
        &candidate,
        &CachedReplayVerification {
            final_state_hash: verified.final_state_hash,
            steps: verified.steps,
            player_count: replay.player_count,
            ruleset_fingerprint: replay.ruleset_fingerprint.as_str().to_string(),
            scores: replay.result.scores.iter().map(|s| *s as i32).collect(),
            ranks: replay.result.ranks.iter().map(|r| *r as i32).collect(),
            winners: replay.result.winners.iter().map(|w| *w as u8).collect(),
        },
    )?;

    // The run's own configuration document is the exact evidence for this
    // occurrence; it must agree with the report it claims to configure.
    let config = parse_match_configuration(config_bytes)?.ok_or_else(|| {
        StudioLeagueError::Invalid(
            "runtime configuration document is not an arena config".to_string(),
        )
    })?;
    if config.game_id != report.game_id {
        return Err(StudioLeagueError::Invalid(format!(
            "runtime configuration names game_id `{}` but the report names `{}`",
            config.game_id, report.game_id
        )));
    }
    if config.seats.len() != report.player_count as usize {
        return Err(StudioLeagueError::Invalid(format!(
            "runtime configuration carries {} seats but the report declares {} players",
            config.seats.len(),
            report.player_count
        )));
    }
    if let Some(seed) = config.seed {
        let fingerprint =
            RulesetFingerprint::from_str(&report.ruleset_fingerprint).map_err(|error| {
                StudioLeagueError::Invalid(format!("invalid ruleset fingerprint: {error}"))
            })?;
        if seed_commitment_v1(&report.game_id, report.player_count, seed, &fingerprint).as_str()
            != report.seed_commitment.as_str()
        {
            return Err(StudioLeagueError::Invalid(
                "runtime configuration's seed does not reproduce the report's seed commitment; this configuration is not evidence for this occurrence".to_string(),
            ));
        }
    }

    build_match_record_with_configuration(
        replay_storage_path,
        report_bytes,
        &report,
        HistoricalReplayResolutionV1::Verified {
            candidate,
            completed_plies,
        },
        ConfigAssociationV1::Bound(&config),
        OccurrenceNamespaceV1::Runtime,
    )
}

/// The occurrence-identity namespace of a built record.
///
/// Both namespaces use the same content-derived scheme (SHA-256 of the report
/// document bytes); the prefix keeps the ingestion era explicit so a historical
/// corpus document re-offered through the runtime path can never silently
/// become a "new" match (the ledger additionally rejects a document hash that
/// was already ingested under any identity).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OccurrenceNamespaceV1 {
    /// A document discovered by scanning the historical corpus.
    Historical,
    /// A single just-finished arena occurrence handed in directly.
    Runtime,
}

impl OccurrenceNamespaceV1 {
    pub fn prefix(self) -> &'static str {
        match self {
            OccurrenceNamespaceV1::Historical => "historical-sha256:",
            OccurrenceNamespaceV1::Runtime => "runtime-sha256:",
        }
    }
}

/// Build the ledger record, with the arena's `match-config.json` evidence
/// resolved into per-seat policy attribution and an evidence-based study
/// classification (Commit B Slice 2 review P1-1/P1-2).
///
/// * [`ConfigAssociationV1::NoConfigEvidence`] — seats keep the handshake
///   runtime identity (coarse but honest fallback).
/// * [`ConfigAssociationV1::Bound`] — each seat is either resolved to the exact
///   policy identity or explicitly unresolved (unclassified argv); a diagnostic
///   seat marks the whole match.
/// * [`ConfigAssociationV1::Ambiguous`] — configuration evidence exists but
///   selects no winner: every seat is unresolved and the match can never enter
///   Elo through a coarse identity.
pub fn build_match_record_with_configuration(
    logical_source_path: &str,
    report_bytes: &[u8],
    report: &ArenaReportV1,
    resolution: HistoricalReplayResolutionV1,
    association: ConfigAssociationV1<'_>,
    namespace: OccurrenceNamespaceV1,
) -> Result<StudioMatchRecordV1> {
    if report.agents.len() != report.player_count as usize {
        return Err(StudioLeagueError::Invalid(format!(
            "arena report `{logical_source_path}` declares {} players but carries {} agent seats",
            report.player_count,
            report.agents.len()
        )));
    }
    let (status, completed_plies, scores, ranks, winners) = match &report.outcome {
        ArenaOutcomeV1::Completed {
            result,
            completed_plies,
            ..
        } => (
            MatchStatus::Completed,
            Some(*completed_plies),
            result.scores.iter().map(|score| *score as i32).collect(),
            result.ranks.iter().map(|rank| *rank as i32).collect(),
            result
                .winners
                .iter()
                .map(|winner| winner.0)
                .collect::<Vec<_>>(),
        ),
        ArenaOutcomeV1::Aborted {
            completed_plies, ..
        } => (
            MatchStatus::Aborted,
            Some(*completed_plies),
            Vec::new(),
            Vec::new(),
            Vec::new(),
        ),
        ArenaOutcomeV1::Truncated {
            completed_plies,
            cap_scores,
            ..
        } => (
            MatchStatus::Truncated,
            Some(*completed_plies),
            cap_scores.iter().map(|score| *score as i32).collect(),
            Vec::new(),
            Vec::new(),
        ),
    };

    let mut seen_seats = BTreeSet::new();
    let mut seats = Vec::with_capacity(report.agents.len());
    for agent in &report.agents {
        let seat = agent.seat.0;
        if seat >= report.player_count || !seen_seats.insert(seat) {
            return Err(StudioLeagueError::Invalid(format!(
                "arena report `{logical_source_path}` has invalid or duplicate seat {seat}"
            )));
        }
        let identity = match (&agent.agent_name, &agent.agent_version) {
            (Some(name), Some(version))
                if !name.trim().is_empty() && !version.trim().is_empty() =>
            {
                Some(EngineIdentityV1::new(name.clone(), version.clone()))
            }
            (None, None) => None,
            _ => {
                return Err(StudioLeagueError::Invalid(format!(
                    "arena report `{logical_source_path}` seat {seat} carries only half an engine identity"
                )))
            }
        };
        // Per-seat attribution (Commit B Slice 2 Repair 1, P1-2): a bound
        // configuration resolves the seat to an exact policy identity; absent
        // configuration evidence may fall back to the handshake runtime
        // identity; present-but-unattributable evidence (ambiguous candidates,
        // unclassified argv) leaves the seat unresolved and is never guessed.
        let policy_identity = match &association {
            ConfigAssociationV1::NoConfigEvidence => SeatPolicyIdentityV1::NoConfigEvidence,
            ConfigAssociationV1::Ambiguous { reason } => SeatPolicyIdentityV1::Unresolved {
                reason: reason.clone(),
            },
            ConfigAssociationV1::Bound(configuration) => {
                match configuration.seats.get(seat as usize) {
                    Some(crate::agent_configuration::SeatConfigurationIdentityV1::Resolved(
                        identity,
                    )) => SeatPolicyIdentityV1::Resolved {
                        policy_key: identity.key(),
                    },
                    Some(crate::agent_configuration::SeatConfigurationIdentityV1::Unresolved {
                        reason,
                    }) => SeatPolicyIdentityV1::Unresolved {
                        reason: reason.clone(),
                    },
                    None => SeatPolicyIdentityV1::Unresolved {
                        reason: "bound configuration carries no entry for this seat".to_string(),
                    },
                }
            }
        };
        let display_name = match &policy_identity {
            SeatPolicyIdentityV1::Resolved { policy_key } => Some(policy_key.clone()),
            _ => identity.as_ref().map(|i| i.agent_name.clone()),
        };
        seats.push(StudioMatchSeatV1 {
            seat,
            display_name,
            identity,
            policy_identity,
            participant_id: None,
            score: scores.get(seat as usize).copied(),
            rank: ranks.get(seat as usize).copied(),
            won: winners.contains(&seat),
        });
    }

    let replay = match resolution {
        HistoricalReplayResolutionV1::Verified { candidate, .. } => ReplayBindingV1 {
            document_hash: Some(candidate.document_sha256),
            final_hash: Some(candidate.final_state_hash),
            storage: Some(ReplayStorage::InPlaceReference),
            path: Some(candidate.logical_path),
            verification: Some(ReplayVerification::Verified),
        },
        HistoricalReplayResolutionV1::ResultOnly => ReplayBindingV1::default(),
    };

    let source_document_hash = hex::encode(Sha256::digest(report_bytes));
    let source_identity = format!("{}{source_document_hash}", namespace.prefix());

    let record = StudioMatchRecordV1 {
        source_kind: "arena_report".to_string(),
        // Content-derived occurrence identity, invariant to archive file
        // location. `source_path` records the lexicographically first logical
        // path for provenance/debugging.
        source_identity,
        source_path: Some(logical_source_path.to_string()),
        source_document_hash,
        played_at: None,
        ruleset_fingerprint: report.ruleset_fingerprint.clone(),
        engine_version: Some(report.engine_version.clone()),
        player_count: report.player_count,
        status,
        seats,
        completed_plies,
        main_turn_count: None,
        replay,
        diagnostic: match &association {
            ConfigAssociationV1::Bound(configuration) => configuration_is_diagnostic(configuration),
            _ => false,
        },
    };
    record.validate_for_ingest()?;
    Ok(record)
}

/// True when any seat in the configuration is a diagnostic / altered policy.
///
/// The eligibility rule is per-match: one study seat contaminates the match
/// result, so the whole match leaves the default rating pool.
fn configuration_is_diagnostic(configuration: &MatchConfigurationV1) -> bool {
    configuration
        .seats
        .iter()
        .filter_map(|seat| seat.resolved())
        .any(is_diagnostic_configuration)
}

#[derive(Debug, Clone)]
pub struct CachedReplayVerification {
    pub final_state_hash: String,
    pub steps: u32,
    pub player_count: u8,
    pub ruleset_fingerprint: String,
    pub scores: Vec<i32>,
    pub ranks: Vec<i32>,
    pub winners: Vec<u8>,
}

/// One `match-config.json` document found in the corpus, kept with its logical
/// path so association can use document provenance instead of scan order
/// (Commit B Slice 2 Repair 1, P1-1).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ConfigurationCandidateV1 {
    pub logical_path: String,
    pub configuration: MatchConfigurationV1,
}

/// How a report's configuration evidence was associated.
///
/// `game_id` is **not** a unique key — the measured inventory shows 22,294
/// distinct `game_id`s across 48,273 reports — so a report only binds a
/// configuration when companion provenance or content consistency selects
/// exactly one distinct configuration. Nothing here compares scan order or path
/// order to pick a winner; conflict fails closed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ConfigAssociationV1<'a> {
    /// No configuration document names this report's `game_id`. The handshake
    /// runtime identity is the only per-seat evidence and may be used.
    NoConfigEvidence,
    /// Exactly one distinct configuration applies to this report.
    Bound(&'a MatchConfigurationV1),
    /// Configuration documents exist for this `game_id` but they disagree with
    /// each other or with the report's recorded shape, so no configuration is
    /// authoritative. The report stays in the ledger with unresolved seats and
    /// never enters Elo.
    Ambiguous { reason: String },
}

fn parent_logical_dir(logical_path: &str) -> &str {
    match logical_path.rfind('/') {
        Some(index) => &logical_path[..index],
        None => "",
    }
}

fn distinct_seat_configurations<'a>(
    candidates: &[&'a ConfigurationCandidateV1],
) -> Vec<&'a MatchConfigurationV1> {
    let mut distinct: Vec<&MatchConfigurationV1> = Vec::new();
    for candidate in candidates {
        if !distinct
            .iter()
            .any(|seen| seen.seats == candidate.configuration.seats)
        {
            distinct.push(&candidate.configuration);
        }
    }
    distinct
}

/// Associate one arena report with at most one authoritative configuration.
///
/// Binding evidence, in order:
///
/// 1. **Companion provenance** — a candidate whose document lives in the same
///    logical directory as the report (the corpus writes `match-config.json`
///    beside `arena-report.json` per match). Companion evidence, when present,
///    outranks the wider `game_id` candidate set.
/// 2. **Shape consistency** — a candidate whose seat count disagrees with the
///    report can never bind.
/// 3. **Collapse or content selection** — the remaining candidates must either
///    collapse to one distinct per-seat configuration, or the report's
///    `seed_commitment` (recomputed from each candidate's recorded seed) must
///    select exactly one.
///
/// Conflicting candidates are never resolved by "first seen" or by path order:
/// the association fails closed to [`ConfigAssociationV1::Ambiguous`].
pub fn associate_configuration<'a>(
    report_logical_path: &str,
    report: &ArenaReportV1,
    configs: &'a BTreeMap<String, Vec<ConfigurationCandidateV1>>,
) -> ConfigAssociationV1<'a> {
    let Some(candidates) = configs.get(&report.game_id) else {
        return ConfigAssociationV1::NoConfigEvidence;
    };
    let compatible: Vec<&ConfigurationCandidateV1> = candidates
        .iter()
        .filter(|candidate| candidate.configuration.seats.len() == report.player_count as usize)
        .collect();
    if compatible.is_empty() {
        return ConfigAssociationV1::Ambiguous {
            reason: format!(
                "{} configuration document(s) name game_id `{}` but none carries {} seats",
                candidates.len(),
                report.game_id,
                report.player_count
            ),
        };
    }
    let report_dir = parent_logical_dir(report_logical_path);
    let companions: Vec<&ConfigurationCandidateV1> = compatible
        .iter()
        .copied()
        .filter(|candidate| parent_logical_dir(&candidate.logical_path) == report_dir)
        .collect();
    let pool: Vec<&ConfigurationCandidateV1> = if companions.is_empty() {
        compatible
    } else {
        companions
    };
    let mut distinct = distinct_seat_configurations(&pool);
    if distinct.len() == 1 {
        return ConfigAssociationV1::Bound(distinct.remove(0));
    }
    // The candidates disagree. The report's seed commitment is the only content
    // evidence that can select one of them; if it cannot, the association fails
    // closed instead of guessing.
    let distinct_count = distinct.len();
    let seed_selects = |configuration: &MatchConfigurationV1| {
        configuration.seed.is_some_and(|seed| {
            RulesetFingerprint::from_str(&report.ruleset_fingerprint).is_ok_and(|fingerprint| {
                seed_commitment_v1(&report.game_id, report.player_count, seed, &fingerprint)
                    .as_str()
                    == report.seed_commitment.as_str()
            })
        })
    };
    let agreeing: Vec<&MatchConfigurationV1> = distinct
        .iter()
        .copied()
        .filter(|c| seed_selects(c))
        .collect();
    match agreeing.len() {
        1 => ConfigAssociationV1::Bound(agreeing[0]),
        _ => ConfigAssociationV1::Ambiguous {
            reason: format!(
                "{distinct_count} distinct configuration(s) name game_id `{}` and the report's seed commitment does not select exactly one of them",
                report.game_id
            ),
        },
    }
}

fn load_and_verify_candidate(
    candidate: &ReplayContentCandidateV1,
) -> std::result::Result<CachedReplayVerification, String> {
    let path = candidate
        .filesystem_path
        .as_deref()
        .unwrap_or_else(|| Path::new(&candidate.logical_path));
    let bytes = std::fs::read(path).map_err(|e| format!("read error: {e}"))?;
    let actual_hash = hex::encode(Sha256::digest(&bytes));
    if actual_hash != candidate.document_sha256 {
        return Err(format!(
            "document sha drifted: expected {}, found {actual_hash}",
            candidate.document_sha256
        ));
    }
    let replay: ReplayV1 =
        serde_json::from_slice(&bytes).map_err(|e| format!("parse error: {e}"))?;
    let verified = verify_replay(&replay).map_err(|e| format!("verification error: {e}"))?;
    Ok(CachedReplayVerification {
        final_state_hash: verified.final_state_hash,
        steps: verified.steps,
        player_count: replay.player_count,
        ruleset_fingerprint: replay.ruleset_fingerprint.as_str().to_string(),
        scores: replay.result.scores.iter().map(|s| *s as i32).collect(),
        ranks: replay.result.ranks.iter().map(|r| *r as i32).collect(),
        winners: replay.result.winners.iter().map(|w| *w as u8).collect(),
    })
}

fn verify_candidate(
    report: &ArenaReportV1,
    result: &splendor_core::GameResult,
    completed_plies: u32,
    final_hash: &str,
    candidate: &ReplayContentCandidateV1,
) -> Result<()> {
    let verified = load_and_verify_candidate(candidate).map_err(StudioLeagueError::Invalid)?;
    check_candidate_facts(
        report,
        result,
        completed_plies,
        final_hash,
        candidate,
        &verified,
    )
}

fn check_candidate_facts(
    report: &ArenaReportV1,
    result: &splendor_core::GameResult,
    completed_plies: u32,
    final_hash: &str,
    candidate: &ReplayContentCandidateV1,
    verified: &CachedReplayVerification,
) -> Result<()> {
    if verified.final_state_hash != final_hash || candidate.final_state_hash != final_hash {
        return Err(StudioLeagueError::Invalid(format!(
            "terminal hash disagrees with arena report binding `{final_hash}`"
        )));
    }
    if verified.steps != completed_plies {
        return Err(StudioLeagueError::Invalid(format!(
            "completed_plies mismatch: report {completed_plies}, replay {}",
            verified.steps
        )));
    }
    if verified.player_count != report.player_count {
        return Err(StudioLeagueError::Invalid(format!(
            "player_count mismatch: report {}, replay {}",
            report.player_count, verified.player_count
        )));
    }
    if verified.ruleset_fingerprint != report.ruleset_fingerprint {
        return Err(StudioLeagueError::Invalid(
            "ruleset_fingerprint mismatch between report and replay".to_string(),
        ));
    }
    if verified.scores != result.scores.iter().map(|s| *s as i32).collect::<Vec<_>>()
        || verified.ranks != result.ranks.iter().map(|r| *r as i32).collect::<Vec<_>>()
        || verified.winners
            != result
                .winners
                .iter()
                .map(|player| player.0)
                .collect::<Vec<_>>()
    {
        return Err(StudioLeagueError::Invalid(
            "terminal result mismatch between report and replay".to_string(),
        ));
    }
    Ok(())
}

fn verify_candidate_cached(
    report: &ArenaReportV1,
    result: &splendor_core::GameResult,
    completed_plies: u32,
    final_hash: &str,
    candidate: &ReplayContentCandidateV1,
    cache: &mut HashMap<String, std::result::Result<CachedReplayVerification, String>>,
) -> Result<()> {
    let entry = match cache.get(&candidate.document_sha256) {
        Some(entry) => entry.clone(),
        None => {
            let res = load_and_verify_candidate(candidate);
            cache.insert(candidate.document_sha256.clone(), res.clone());
            res
        }
    };
    let verified = entry.map_err(StudioLeagueError::Invalid)?;
    check_candidate_facts(
        report,
        result,
        completed_plies,
        final_hash,
        candidate,
        &verified,
    )
}

/// Compute a deterministic digest across the entire canonical record set.
/// Records are ordered by `canonical_league_order` and projected to a minimal
/// stable tuple.
pub fn compute_canonical_set_digest(records: &[StudioMatchRecordV1]) -> String {
    let order = canonical_league_order(records);
    let mut hasher = Sha256::new();
    for index in order {
        let record = &records[index];
        let mut line = String::new();
        line.push_str(&record.source_kind);
        line.push('\t');
        line.push_str(&record.source_identity);
        line.push('\t');
        line.push_str(&record.source_document_hash);
        line.push('\t');
        line.push_str(record.status.as_str());
        line.push('\t');
        line.push_str(&record.played_at.unwrap_or(0).to_string());
        line.push('\t');
        let seats = record
            .seats
            .iter()
            .map(|s| {
                format!(
                    "{}:{}",
                    s.seat,
                    s.identity
                        .as_ref()
                        .map(|id| id.key())
                        .unwrap_or_else(|| "(none)".to_string())
                )
            })
            .collect::<Vec<_>>()
            .join(",");
        line.push_str(&seats);
        line.push('\t');
        line.push_str(record.replay.document_hash.as_deref().unwrap_or("-"));
        line.push('\t');
        line.push_str(record.replay.final_hash.as_deref().unwrap_or("-"));
        line.push('\n');
        hasher.update(line.as_bytes());
    }
    hex::encode(hasher.finalize())
}

/// Deterministic digest over the **policy attribution** of every seat.
///
/// One line per seat, ordered by `source_identity` (then seat) so the digest is
/// independent of corpus traversal order. Fields per line: source identity,
/// diagnostic flag, seat, policy-resolution state (`no_config` / `resolved` /
/// `unresolved`), and the effective policy key — filled only in the `resolved`
/// state.
///
/// The human-readable unresolved *reasons* are deliberately excluded: the
/// stable contract is the three-state resolution and the resolved keys, not
/// prose that may be reworded. Together with
/// [`compute_canonical_set_digest`] this separates the two evidence layers:
/// the evidence/document set (unchanged by attribution repairs) and the
/// attribution read from that evidence.
pub fn compute_policy_attribution_digest(records: &[StudioMatchRecordV1]) -> String {
    let mut order: Vec<usize> = (0..records.len()).collect();
    order.sort_by(|left, right| {
        records[*left]
            .source_identity
            .cmp(&records[*right].source_identity)
    });
    let mut hasher = Sha256::new();
    for index in order {
        let record = &records[index];
        for seat in &record.seats {
            let (state, key) = match &seat.policy_identity {
                SeatPolicyIdentityV1::NoConfigEvidence => ("no_config", ""),
                SeatPolicyIdentityV1::Resolved { policy_key } => ("resolved", policy_key.as_str()),
                SeatPolicyIdentityV1::Unresolved { .. } => ("unresolved", ""),
            };
            let line = format!(
                "{}\t{}\t{}\t{}\t{}\n",
                record.source_identity, record.diagnostic as u8, seat.seat, state, key
            );
            hasher.update(line.as_bytes());
        }
    }
    hex::encode(hasher.finalize())
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HistoricalDryRunConfig {
    pub roots: Vec<String>,
    pub max_document_bytes: u64,
    pub skip_segments: Vec<String>,
    pub dedup_source_hash: bool,
}

impl Default for HistoricalDryRunConfig {
    fn default() -> Self {
        Self {
            roots: vec!["benchmarks".to_string(), "local-artifacts".to_string()],
            max_document_bytes: 40 * 1024 * 1024,
            skip_segments: vec![
                "node_modules".to_string(),
                ".git".to_string(),
                ".uv-cache".to_string(),
                "m24-torch-cu124".to_string(),
                "splendor-runtime-architecture".to_string(),
                "visual-check".to_string(),
            ],
            dedup_source_hash: true,
        }
    }
}

/// Full reconciliation report of a read-only canonical-record builder run.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct HistoricalDryRunReportV1 {
    pub roots: Vec<String>,
    pub source_reports_seen: usize,
    pub duplicate_source_reports_skipped: usize,
    pub canonical_records_built: usize,
    pub builder_failures: usize,
    pub failure_samples: Vec<String>,

    pub completed_matches: usize,
    pub completed_verified_replay: usize,
    pub completed_replay_unresolved: usize,
    pub aborted_matches: usize,
    pub truncated_matches: usize,
    pub unavailable_replay: usize,
    pub malformed_records: usize,

    // Reported corpus characteristics:
    pub completed_with_multiple_candidates: usize,
    pub completed_with_multiple_passing_candidates: usize,
    pub selected_distinct_replay_document_sha: usize,
    pub distinct_source_document_sha: usize,
    pub source_document_sha_duplicates: usize,
    pub unmapped_seats: usize,
    pub matches_with_unmapped_seat: usize,
    // Identity provenance for the P1 review: how many matches got an exact
    // policy identity from a `match-config.json`, how many had no config
    // evidence at all, and how many had config evidence that could not be
    // attributed (ambiguous candidates, unclassified argv).
    pub config_documents_seen: usize,
    pub game_ids_with_config_conflicts: usize,
    pub matches_resolved_from_conflicting_game_ids: usize,
    pub matches_with_policy_identity: usize,
    pub matches_without_config_evidence: usize,
    pub matches_with_ambiguous_config: usize,
    pub matches_with_unresolved_policy_seat: usize,
    pub matches_without_policy_identity: usize,
    pub diagnostic_matches: usize,
    pub self_matches: usize,
    pub distinct_participant_identities: usize,

    // Determinism gate digests. `canonical_set_digest` proves the historical
    // evidence/document set did not drift; `policy_attribution_digest` proves
    // the same evidence was resolved into the same policy attribution.
    pub canonical_set_digest: String,
    pub policy_attribution_digest: String,
}

/// Build the full set of canonical match records across the corpus.
///
/// Returns the validation and reconciliation report alongside the verified
/// canonical records ready for ingestion.
pub fn build_historical_corpus(
    config: &HistoricalDryRunConfig,
) -> Result<(HistoricalDryRunReportV1, Vec<StudioMatchRecordV1>)> {
    let corpus_roots: Vec<CorpusRoot> = config
        .roots
        .iter()
        .map(|s| CorpusRoot::from_spec(s))
        .collect();
    let files = collect_corpus_files(&corpus_roots, &config.skip_segments)?;

    let mut replay_index = ReplayContentIndexV1::default();
    let mut arena_files = Vec::new();
    // Every parsed configuration is kept: `game_id` is not a unique key, so a
    // later pass must resolve conflicts by evidence, not by scan order
    // (Commit B Slice 2 Repair 1, P1-1).
    let mut configurations_by_game_id: BTreeMap<String, Vec<ConfigurationCandidateV1>> =
        BTreeMap::new();
    let mut config_documents_seen = 0usize;

    // Pass 1: scan replays and identify arena reports
    for file in &files {
        let size = match std::fs::metadata(&file.filesystem_path) {
            Ok(meta) => meta.len(),
            Err(_) => continue,
        };
        if size > config.max_document_bytes {
            continue;
        }
        let bytes = match std::fs::read(&file.filesystem_path) {
            Ok(bytes) => bytes,
            Err(_) => continue,
        };
        let value: serde_json::Value = match serde_json::from_slice(&bytes) {
            Ok(v) => v,
            Err(_) => continue,
        };
        // `match-config.json` has no `format` tag: it is recognised by its
        // `game_id` + `agents[].args` shape alone, which is exactly what the
        // typed resolver accepts. Anything else that merely parses as JSON is
        // left untouched.
        if let Some(parsed) = parse_match_configuration(&bytes)? {
            config_documents_seen += 1;
            configurations_by_game_id
                .entry(parsed.game_id.clone())
                .or_default()
                .push(ConfigurationCandidateV1 {
                    logical_path: file.logical_path.clone(),
                    configuration: parsed,
                });
        }
        match value.get("format").and_then(|v| v.as_str()).unwrap_or("") {
            splendor_replay::REPLAY_FORMAT => {
                replay_index.index_replay_document(
                    &file.logical_path,
                    Some(&file.filesystem_path),
                    &bytes,
                )?;
            }
            splendor_arena::ARENA_REPORT_FORMAT => {
                arena_files.push(file.clone());
            }
            _ => {}
        }
    }
    replay_index.finish();

    // A `game_id` whose documents carry more than one distinct per-seat
    // configuration is a measured conflict surface; the per-report association
    // below resolves each report by evidence or leaves it unresolved.
    let conflicting_game_ids: BTreeSet<String> = configurations_by_game_id
        .iter()
        .filter_map(|(game_id, candidates)| {
            let refs: Vec<&ConfigurationCandidateV1> = candidates.iter().collect();
            if distinct_seat_configurations(&refs).len() > 1 {
                Some(game_id.clone())
            } else {
                None
            }
        })
        .collect();
    let game_ids_with_config_conflicts = conflicting_game_ids.len();

    let mut report = HistoricalDryRunReportV1 {
        roots: config.roots.clone(),
        source_reports_seen: arena_files.len(),
        ..Default::default()
    };
    report.config_documents_seen = config_documents_seen;
    report.game_ids_with_config_conflicts = game_ids_with_config_conflicts;

    let mut records: Vec<StudioMatchRecordV1> = Vec::with_capacity(arena_files.len());
    let mut verification_cache: HashMap<
        String,
        std::result::Result<CachedReplayVerification, String>,
    > = HashMap::new();
    let mut selected_replay_shas = BTreeSet::new();
    let mut source_sha_counts = BTreeMap::new();
    let mut seen_source_hashes = BTreeSet::new();
    let mut distinct_participants = BTreeSet::new();

    // Pass 2: build canonical records
    for file in &arena_files {
        let bytes = match std::fs::read(&file.filesystem_path) {
            Ok(b) => b,
            Err(e) => {
                report.builder_failures += 1;
                report
                    .failure_samples
                    .push(format!("{}: read error {e}", file.logical_path));
                continue;
            }
        };
        let source_sha = hex::encode(Sha256::digest(&bytes));
        *source_sha_counts
            .entry(source_sha.clone())
            .or_insert(0usize) += 1;

        if config.dedup_source_hash && !seen_source_hashes.insert(source_sha.clone()) {
            report.duplicate_source_reports_skipped += 1;
            continue;
        }

        let arena_report = match parse_arena_report(&file.logical_path, &bytes) {
            Ok(r) => r,
            Err(e) => {
                report.builder_failures += 1;
                report
                    .failure_samples
                    .push(format!("{}: parse error {e}", file.logical_path));
                continue;
            }
        };

        let resolution = match &arena_report.outcome {
            ArenaOutcomeV1::Completed {
                result,
                completed_plies,
                replay_final_hash,
            } => {
                report.completed_matches += 1;
                let candidates = replay_index.candidates(replay_final_hash.as_str());
                if candidates.len() > 1 {
                    report.completed_with_multiple_candidates += 1;
                }
                if candidates.is_empty() {
                    report.completed_replay_unresolved += 1;
                    report.builder_failures += 1;
                    report.failure_samples.push(format!(
                        "{}: no candidate for final hash {replay_final_hash}",
                        file.logical_path
                    ));
                    continue;
                }
                let mut valid = Vec::new();
                for candidate in candidates {
                    if verify_candidate_cached(
                        &arena_report,
                        result,
                        *completed_plies,
                        replay_final_hash.as_str(),
                        candidate,
                        &mut verification_cache,
                    )
                    .is_ok()
                    {
                        valid.push(candidate.clone());
                    }
                }
                if valid.len() > 1 {
                    report.completed_with_multiple_passing_candidates += 1;
                }
                if valid.is_empty() {
                    report.completed_replay_unresolved += 1;
                    report.builder_failures += 1;
                    report.failure_samples.push(format!(
                        "{}: no verified candidate for final hash {replay_final_hash}",
                        file.logical_path
                    ));
                    continue;
                }
                valid.sort_by(|a, b| {
                    (&a.document_sha256, &a.logical_path)
                        .cmp(&(&b.document_sha256, &b.logical_path))
                });
                let chosen = valid.remove(0);
                selected_replay_shas.insert(chosen.document_sha256.clone());
                report.completed_verified_replay += 1;
                HistoricalReplayResolutionV1::Verified {
                    candidate: chosen,
                    completed_plies: *completed_plies,
                }
            }
            ArenaOutcomeV1::Aborted { .. } => {
                report.aborted_matches += 1;
                report.unavailable_replay += 1;
                HistoricalReplayResolutionV1::ResultOnly
            }
            ArenaOutcomeV1::Truncated { .. } => {
                report.truncated_matches += 1;
                report.unavailable_replay += 1;
                HistoricalReplayResolutionV1::ResultOnly
            }
        };

        let association = associate_configuration(
            &file.logical_path,
            &arena_report,
            &configurations_by_game_id,
        );
        match &association {
            ConfigAssociationV1::NoConfigEvidence => report.matches_without_config_evidence += 1,
            ConfigAssociationV1::Ambiguous { .. } => report.matches_with_ambiguous_config += 1,
            ConfigAssociationV1::Bound(_) => {
                // Audit breakdown: a report whose game_id belongs to the
                // conflict surface but that companion/seed evidence still
                // resolved deterministically.
                if conflicting_game_ids.contains(&arena_report.game_id) {
                    report.matches_resolved_from_conflicting_game_ids += 1;
                }
            }
        }

        let record = match build_match_record_with_configuration(
            &file.logical_path,
            &bytes,
            &arena_report,
            resolution,
            association,
            OccurrenceNamespaceV1::Historical,
        ) {
            Ok(rec) => rec,
            Err(e) => {
                report.builder_failures += 1;
                report
                    .failure_samples
                    .push(format!("{}: record build error {e}", file.logical_path));
                continue;
            }
        };

        if let Err(e) = record.validate_for_ingest() {
            report.malformed_records += 1;
            report.failure_samples.push(format!(
                "{}: validate_for_ingest error {e}",
                file.logical_path
            ));
            continue;
        }

        let mut match_has_unmapped = false;
        let mut match_has_policy_identity = false;
        let mut match_has_unresolved_policy = false;
        // Effective attribution per seat: only `Resolved` proves the exact
        // policy participant; `NoConfigEvidence` may fall back to the
        // handshake runtime identity; `Unresolved` is never guessed.
        let effective_key = |seat: &StudioMatchSeatV1| match &seat.policy_identity {
            SeatPolicyIdentityV1::Resolved { policy_key } => Some(policy_key.clone()),
            SeatPolicyIdentityV1::NoConfigEvidence => {
                seat.identity.as_ref().map(|identity| identity.key())
            }
            SeatPolicyIdentityV1::Unresolved { .. } => None,
        };
        for seat in &record.seats {
            match &seat.policy_identity {
                SeatPolicyIdentityV1::Resolved { .. } => match_has_policy_identity = true,
                SeatPolicyIdentityV1::Unresolved { .. } => match_has_unresolved_policy = true,
                SeatPolicyIdentityV1::NoConfigEvidence => {}
            }
            match effective_key(seat) {
                Some(key) => {
                    distinct_participants.insert(key);
                }
                None => {
                    report.unmapped_seats += 1;
                    match_has_unmapped = true;
                }
            }
        }
        if match_has_unmapped {
            report.matches_with_unmapped_seat += 1;
        }
        if match_has_unresolved_policy {
            report.matches_with_unresolved_policy_seat += 1;
        }
        if match_has_policy_identity {
            report.matches_with_policy_identity += 1;
        } else {
            report.matches_without_policy_identity += 1;
        }
        if record.diagnostic {
            report.diagnostic_matches += 1;
        }
        if record.seats.len() == 2 {
            let first = effective_key(&record.seats[0]);
            let second = effective_key(&record.seats[1]);
            if first.is_some() && first == second {
                report.self_matches += 1;
            }
        }

        records.push(record);
        report.canonical_records_built += 1;
    }

    report.distinct_source_document_sha = source_sha_counts.len();
    report.source_document_sha_duplicates = source_sha_counts
        .values()
        .map(|c| c.saturating_sub(1))
        .sum();
    report.selected_distinct_replay_document_sha = selected_replay_shas.len();
    report.distinct_participant_identities = distinct_participants.len();
    report.canonical_set_digest = compute_canonical_set_digest(&records);
    report.policy_attribution_digest = compute_policy_attribution_digest(&records);

    Ok((report, records))
}

/// Execute a read-only historical dry-run across the corpus without touching SQLite.
pub fn run_historical_dry_run(config: &HistoricalDryRunConfig) -> Result<HistoricalDryRunReportV1> {
    let (report, _) = build_historical_corpus(config)?;
    Ok(report)
}
