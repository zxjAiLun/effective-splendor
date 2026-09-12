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
    MatchStatus, ReplayBindingV1, ReplayStorage, ReplayVerification, StudioMatchRecordV1,
    StudioMatchSeatV1,
};
use crate::participant::EngineIdentityV1;
use crate::replay_index::{
    collect_corpus_files, CorpusRoot, ReplayContentCandidateV1, ReplayContentIndexV1,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use splendor_arena::{ArenaOutcomeV1, ArenaReportV1, ARENA_REPORT_FORMAT, ARENA_REPORT_VERSION};
use splendor_replay::{verify_replay, ReplayV1};
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::path::Path;

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
        None,
    )
}

/// Build the ledger record, optionally with the arena's `match-config.json`
/// resolved into a per-seat **policy** identity and an evidence-based study
/// classification (P1 of the Commit B review).
///
/// When `configuration` is `None` the seat identity is the handshake runtime
/// identity and the match is non-diagnostic, exactly as before.
pub fn build_match_record_with_configuration(
    logical_source_path: &str,
    report_bytes: &[u8],
    report: &ArenaReportV1,
    resolution: HistoricalReplayResolutionV1,
    configuration: Option<&MatchConfigurationV1>,
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
        // When the arena's `match-config.json` was available, its per-seat
        // *policy* identity (search configuration included) supersedes the
        // handshake runtime identity, which collapses distinct search budgets
        // into one string. `configuration` is keyed by `game_id`, so a seat
        // position maps directly to its resolved identity.
        let policy_identity_key = configuration
            .and_then(|c| c.seats.get(seat as usize))
            .and_then(|s| s.resolved())
            .map(|identity| identity.key());
        seats.push(StudioMatchSeatV1 {
            seat,
            display_name: policy_identity_key
                .clone()
                .or_else(|| identity.as_ref().map(|i| i.agent_name.clone())),
            identity,
            policy_identity_key,
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
    let source_identity = format!("historical-sha256:{source_document_hash}");

    let record = StudioMatchRecordV1 {
        source_kind: "arena_report".to_string(),
        // Historical arena reports use content-derived identity (`historical-sha256:<hash>`)
        // so identity and canonical league ordering are invariant to archive file location.
        // `source_path` records the lexicographically first logical path for provenance/debugging.
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
        diagnostic: configuration.is_some_and(configuration_is_diagnostic),
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
    // policy identity from a `match-config.json`, and how many fell back to the
    // (coarser) handshake runtime identity because no config was found.
    pub matches_with_policy_identity: usize,
    pub matches_without_policy_identity: usize,
    pub diagnostic_matches: usize,
    pub self_matches: usize,
    pub distinct_participant_identities: usize,

    // Determinism gate digest:
    pub canonical_set_digest: String,
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
    let mut configurations_by_game_id: BTreeMap<String, MatchConfigurationV1> = BTreeMap::new();

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
            configurations_by_game_id
                .entry(parsed.game_id.clone())
                .or_insert(parsed);
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

    let mut report = HistoricalDryRunReportV1 {
        roots: config.roots.clone(),
        source_reports_seen: arena_files.len(),
        ..Default::default()
    };

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

        let record = match build_match_record_with_configuration(
            &file.logical_path,
            &bytes,
            &arena_report,
            resolution,
            configurations_by_game_id.get(&arena_report.game_id),
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
        for seat in &record.seats {
            // Prefer the exact policy identity from the arena config; fall back
            // to the handshake runtime identity only when no config was found.
            let effective_key = seat
                .policy_identity_key
                .clone()
                .or_else(|| seat.identity.as_ref().map(|identity| identity.key()));
            if seat.policy_identity_key.is_some() {
                match_has_policy_identity = true;
            }
            match effective_key {
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
        if match_has_policy_identity {
            report.matches_with_policy_identity += 1;
        } else {
            report.matches_without_policy_identity += 1;
        }
        if record.diagnostic {
            report.diagnostic_matches += 1;
        }
        if record.seats.len() == 2 {
            let first = record.seats[0]
                .policy_identity_key
                .clone()
                .or_else(|| record.seats[0].identity.as_ref().map(|i| i.key()));
            let second = record.seats[1]
                .policy_identity_key
                .clone()
                .or_else(|| record.seats[1].identity.as_ref().map(|i| i.key()));
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

    Ok((report, records))
}

/// Execute a read-only historical dry-run across the corpus without touching SQLite.
pub fn run_historical_dry_run(config: &HistoricalDryRunConfig) -> Result<HistoricalDryRunReportV1> {
    let (report, _) = build_historical_corpus(config)?;
    Ok(report)
}
