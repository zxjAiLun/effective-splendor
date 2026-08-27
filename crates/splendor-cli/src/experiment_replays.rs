//! M36A Experiment Replay Library: read-only browsing of experiment run
//! directories (v1: M35A) through the Studio Host.
//!
//! Security invariants:
//! - Every replay path is derived from the tracked source registry's
//!   `run_dir` joined with a fixed `matches/match-%06d.(report|replay).json`
//!   filename; client input is limited to registry-known identifiers and a
//!   checked `u32` match index, so path traversal is impossible by
//!   construction.
//! - Bundles are served only after full identity binding (game_id equals
//!   the pairing's expected game id; replay final hash equals the match
//!   report's `replay_final_hash`) and a complete `verify_replay_trace()`
//!   re-verification.
//! - Source files are opened read-only; nothing under the runs root is
//!   ever written.

use std::fs;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use splendor_analysis::RefereeRevealV1;
use splendor_core::{Action, FullState, Observation, PlayerId};
use splendor_replay::{
    replay_document_hash_v1, verify_replay_trace, ReplayV1, VerifiedReplayTrace,
};

pub const REGISTRY_FORMAT: &str = "effective-splendor-studio-replay-sources";
pub const REGISTRY_VERSION: u32 = 1;
pub const INDEX_FORMAT: &str = "effective-splendor-experiment-replay-index";
pub const INDEX_VERSION: u32 = 1;
pub const BUNDLE_FORMAT: &str = "effective-splendor-experiment-replay-bundle";
pub const BUNDLE_VERSION: u32 = 1;

const MAX_MATCHES_PER_PAIRING: u32 = 4096;

/// Agent identity contract for M35A run reports:
/// - every M35A neural checkpoint reports
///   `agent_name = "effective-splendor-m35a-direct-agent-v1"` with
///   `agent_version = <model id>` (see `m35a_agent.py`);
/// - the M07 champion reports
///   `agent_name = "effective-splendor-determinization-agent-v1"` with
///   `agent_version = "1"`.
const M35A_NEURAL_AGENT_NAME: &str = "effective-splendor-m35a-direct-agent-v1";
const M07_AGENT_NAME: &str = "effective-splendor-determinization-agent-v1";
const M07_AGENT_VERSION: &str = "1";

/// Expected (agent_name, agent_version) for a pairing's candidate and
/// opponent identities.
pub fn expected_agent_identity(model_id: &str) -> Result<(&'static str, String), String> {
    match model_id {
        "M07" => Ok((M07_AGENT_NAME, M07_AGENT_VERSION.to_string())),
        other => Ok((M35A_NEURAL_AGENT_NAME, other.to_string())),
    }
}

// ---------------------------------------------------------------------------
// Registry model
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ReplaySourceRegistry {
    pub format: String,
    pub version: u32,
    pub experiments: Vec<ExperimentSource>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExperimentSource {
    pub id: String,
    pub display_name: String,
    pub description: String,
    pub tracked_result: String,
    pub tracked_result_sha256: String,
    pub runs_root: String,
    pub pairings: Vec<PairingSource>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PairingSource {
    pub evaluation_id: String,
    pub candidate_model_id: String,
    pub opponent_model_id: String,
    pub status: String,
    pub scheduled_matches: u32,
    pub run_dir: String,
    #[serde(default)]
    pub eval_report_sha256: Option<String>,
    #[serde(default)]
    pub completed_before_abort: Option<u32>,
    #[serde(default)]
    pub nontermination_match_slot: Option<String>,
    #[serde(default)]
    pub not_started_after_abort: Option<u32>,
}

impl ReplaySourceRegistry {
    pub fn load(path: &Path) -> Result<Self, String> {
        let bytes = fs::read(path)
            .map_err(|error| format!("cannot read replay source registry: {error}"))?;
        let registry: ReplaySourceRegistry = serde_json::from_slice(&bytes)
            .map_err(|error| format!("invalid replay source registry JSON: {error}"))?;
        registry.validate()?;
        Ok(registry)
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.format != REGISTRY_FORMAT {
            return Err(format!(
                "unsupported replay source registry format: {}",
                self.format
            ));
        }
        if self.version != REGISTRY_VERSION {
            return Err(format!(
                "unsupported replay source registry version: {}",
                self.version
            ));
        }
        if self.experiments.is_empty() {
            return Err("replay source registry has no experiments".into());
        }
        for experiment in &self.experiments {
            validate_identifier("experiment id", &experiment.id)?;
            if !experiment.runs_root.starts_with("local-artifacts/") {
                return Err(format!(
                    "experiment {} runs_root must live under local-artifacts/",
                    experiment.id
                ));
            }
            if experiment.pairings.is_empty() {
                return Err(format!("experiment {} has no pairings", experiment.id));
            }
            for pairing in &experiment.pairings {
                validate_identifier("evaluation id", &pairing.evaluation_id)?;
                match pairing.status.as_str() {
                    "VALID" => {
                        if pairing.scheduled_matches == 0
                            || pairing.scheduled_matches > MAX_MATCHES_PER_PAIRING
                        {
                            return Err(format!(
                                "pairing {} has invalid scheduled_matches",
                                pairing.evaluation_id
                            ));
                        }
                        if pairing.eval_report_sha256.is_none() {
                            return Err(format!(
                                "VALID pairing {} must bind an eval report SHA",
                                pairing.evaluation_id
                            ));
                        }
                    }
                    "EXCLUDED_PREFIX" => {
                        let completed = pairing.completed_before_abort.ok_or_else(|| {
                            format!(
                                "EXCLUDED_PREFIX pairing {} must declare completed_before_abort",
                                pairing.evaluation_id
                            )
                        })?;
                        if completed >= pairing.scheduled_matches {
                            return Err(format!(
                                "EXCLUDED_PREFIX pairing {} completed count must be below schedule",
                                pairing.evaluation_id
                            ));
                        }
                        let failed =
                            pairing
                                .nontermination_match_slot
                                .as_deref()
                                .ok_or_else(|| {
                                    format!(
                                        "EXCLUDED_PREFIX pairing {} must declare its failure slot",
                                        pairing.evaluation_id
                                    )
                                })?;
                        if failed.is_empty() {
                            return Err("failure slot must not be empty".into());
                        }
                    }
                    other => {
                        return Err(format!(
                            "pairing {} has unsupported status {other}",
                            pairing.evaluation_id
                        ));
                    }
                }
                if !pairing.run_dir.starts_with("local-artifacts/") {
                    return Err(format!(
                        "pairing {} run_dir must live under local-artifacts/",
                        pairing.evaluation_id
                    ));
                }
                // The run_dir must sit inside the experiment's runs_root.
                let runs_root = Path::new(&experiment.runs_root);
                let run_dir = Path::new(&pairing.run_dir);
                if !run_dir.starts_with(runs_root) {
                    return Err(format!(
                        "pairing {} run_dir escapes the experiment runs root",
                        pairing.evaluation_id
                    ));
                }
            }
        }
        Ok(())
    }

    /// Fail-closed provenance + path binding, evaluated against the
    /// repository root. Enforces, for every experiment:
    /// 1. the bound tracked result file exists and its SHA-256 matches
    ///    `tracked_result_sha256`;
    /// 2. every run directory resolves (following symlinks) to a path that
    ///    stays inside the canonical `local-artifacts` tree — symlinks
    ///    cannot escape;
    /// 3. for VALID pairings, the bound `eval-report.json` exists and its
    ///    SHA-256 matches `eval_report_sha256`.
    ///
    /// This is called by `ExperimentReplayLibrary::load`; the structural
    /// `validate()` above remains available for offline checks.
    pub fn validate_against_root(&self, repo_root: &Path) -> Result<(), String> {
        // Canonical local-artifacts root: the only allowed physical parent.
        let artifacts_root = repo_root.join("local-artifacts");
        let artifacts_canon = artifacts_root
            .canonicalize()
            .map_err(|error| format!("cannot resolve {}: {error}", artifacts_root.display()))?;

        for experiment in &self.experiments {
            validate_identifier("experiment id", &experiment.id)?;

            // 1. tracked result provenance.
            let tracked_path = repo_root.join(&experiment.tracked_result);
            let tracked_bytes = fs::read(&tracked_path).map_err(|error| {
                format!(
                    "experiment {} cannot read tracked result {}: {error}",
                    experiment.id,
                    tracked_path.display()
                )
            })?;
            let tracked_sha = {
                let mut hasher = Sha256::new();
                hasher.update(&tracked_bytes);
                hex::encode(hasher.finalize())
            };
            if tracked_sha != experiment.tracked_result_sha256 {
                return Err(format!(
                    "experiment {} tracked result SHA mismatch: registry binds {} but {} hashes to {}",
                    experiment.id,
                    experiment.tracked_result_sha256,
                    tracked_path.display(),
                    tracked_sha
                ));
            }

            for pairing in &experiment.pairings {
                validate_identifier("evaluation id", &pairing.evaluation_id)?;

                // 2. symlink-escape-proof run directory containment.
                let run_dir = repo_root.join(&pairing.run_dir);
                let run_dir_canon = run_dir.canonicalize().map_err(|error| {
                    format!(
                        "pairing {} run dir {} cannot be resolved: {error}",
                        pairing.evaluation_id,
                        run_dir.display()
                    )
                })?;
                if !run_dir_canon.starts_with(&artifacts_canon) {
                    return Err(format!(
                        "pairing {} run dir {} resolves outside local-artifacts (resolved to {})",
                        pairing.evaluation_id,
                        run_dir.display(),
                        run_dir_canon.display()
                    ));
                }

                // 3. VALID pairing eval-report provenance.
                if pairing.status == "VALID" {
                    let bound_sha = pairing.eval_report_sha256.as_deref().ok_or_else(|| {
                        format!(
                            "VALID pairing {} must bind an eval report SHA",
                            pairing.evaluation_id
                        )
                    })?;
                    let report_path = run_dir_canon.join("eval-report.json");
                    let report_bytes = fs::read(&report_path).map_err(|error| {
                        format!(
                            "pairing {} cannot read eval report {}: {error}",
                            pairing.evaluation_id,
                            report_path.display()
                        )
                    })?;
                    let report_sha = {
                        let mut hasher = Sha256::new();
                        hasher.update(&report_bytes);
                        hex::encode(hasher.finalize())
                    };
                    if report_sha != bound_sha {
                        return Err(format!(
                            "pairing {} eval report SHA mismatch: registry binds {} but {} hashes to {}",
                            pairing.evaluation_id,
                            bound_sha,
                            report_path.display(),
                            report_sha
                        ));
                    }
                }
            }
        }
        Ok(())
    }

    fn experiment(&self, experiment_id: &str) -> Result<&ExperimentSource, String> {
        validate_identifier("experiment id", experiment_id)?;
        self.experiments
            .iter()
            .find(|experiment| experiment.id == experiment_id)
            .ok_or_else(|| format!("unknown experiment `{experiment_id}`"))
    }

    fn pairing(
        &self,
        experiment_id: &str,
        evaluation_id: &str,
    ) -> Result<(&ExperimentSource, &PairingSource), String> {
        let experiment = self.experiment(experiment_id)?;
        validate_identifier("evaluation id", evaluation_id)?;
        let pairing = experiment
            .pairings
            .iter()
            .find(|pairing| pairing.evaluation_id == evaluation_id)
            .ok_or_else(|| format!("unknown pairing `{evaluation_id}`"))?;
        Ok((experiment, pairing))
    }
}

fn validate_identifier(kind: &str, value: &str) -> Result<(), String> {
    let safe = !value.is_empty()
        && value.len() <= 128
        && value
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_');
    if safe {
        Ok(())
    } else {
        Err(format!("invalid {kind}: `{value}`"))
    }
}

/// Resolve a registry run dir against the repo root with symlink-proof
/// containment: the canonicalized directory must stay inside the canonical
/// `local-artifacts` root.
fn resolve_run_dir(
    repo_root: &Path,
    artifacts_root: &Path,
    run_dir: &str,
) -> Result<PathBuf, String> {
    let joined = repo_root.join(run_dir);
    let resolved = joined
        .canonicalize()
        .map_err(|error| format!("cannot resolve run dir {}: {error}", joined.display()))?;
    if !resolved.starts_with(artifacts_root) {
        return Err(format!(
            "run dir {} resolves outside local-artifacts (resolved to {})",
            joined.display(),
            resolved.display()
        ));
    }
    Ok(resolved)
}

/// Verify the match report's recorded agent identities against the pairing's
/// expected lineup: exactly two seats (0 and 1), the candidate seat occupied
/// by the candidate's agent identity, the opponent seat by the opponent's.
/// A wrong-lineup report must never be displayed as this pairing's replay.
fn verify_agent_lineup(
    report: &MatchReport,
    evaluation_id: &str,
    candidate_model_id: &str,
    opponent_model_id: &str,
    candidate_seat: u8,
) -> Result<(), String> {
    if report.agents.len() != 2 {
        return Err(format!(
            "pairing {} match report must list exactly two agents, found {}",
            evaluation_id,
            report.agents.len()
        ));
    }
    let (cand_name, cand_version) = expected_agent_identity(candidate_model_id)?;
    let (opp_name, opp_version) = expected_agent_identity(opponent_model_id)?;
    let opponent_seat = 1 - candidate_seat;
    for agent in &report.agents {
        let (expected_name, expected_version) = if agent.seat == candidate_seat {
            (cand_name, &cand_version)
        } else if agent.seat == opponent_seat {
            (opp_name, &opp_version)
        } else {
            return Err(format!(
                "pairing {} match report has an out-of-range seat {}",
                evaluation_id, agent.seat
            ));
        };
        if agent.agent_name != expected_name || agent.agent_version != *expected_version {
            return Err(format!(
                "pairing {} agent lineup mismatch at seat {}: expected {} v{}, found {} v{}",
                evaluation_id,
                agent.seat,
                expected_name,
                expected_version,
                agent.agent_name,
                agent.agent_version
            ));
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// On-disk match report model (subset of the arena report)
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Deserialize)]
struct MatchReport {
    game_id: String,
    #[allow(dead_code)]
    agents: Vec<MatchReportAgent>,
    outcome: MatchOutcome,
}

#[derive(Debug, Clone, Deserialize)]
#[allow(dead_code)]
struct MatchReportAgent {
    seat: u8,
    agent_name: String,
    agent_version: String,
}

#[derive(Debug, Clone, Deserialize)]
struct MatchOutcome {
    status: String,
    #[serde(default)]
    result: Option<MatchResult>,
    #[serde(default)]
    completed_plies: Option<u32>,
    #[serde(default)]
    replay_final_hash: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
struct MatchResult {
    scores: Vec<u8>,
    #[allow(dead_code)]
    ranks: Vec<u8>,
    winners: Vec<PlayerId>,
    reason: String,
}

fn read_match_report(run_dir: &Path, index: u32) -> Result<MatchReport, String> {
    let path = match_report_path(run_dir, index);
    let bytes = fs::read(&path)
        .map_err(|error| format!("cannot read match report {}: {error}", path.display()))?;
    // The arena report carries additional fields (format, version, engine
    // metadata); select only the identity-relevant subset strictly.
    let value: serde_json::Value = serde_json::from_slice(&bytes)
        .map_err(|error| format!("invalid match report {}: {error}", path.display()))?;
    let game_id = value
        .get("game_id")
        .and_then(|v| v.as_str())
        .ok_or_else(|| format!("match report {} lacks game_id", path.display()))?
        .to_string();
    let agents = value
        .get("agents")
        .and_then(|v| v.as_array())
        .map(|entries| {
            entries
                .iter()
                .map(|entry| {
                    Ok(MatchReportAgent {
                        seat: entry
                            .get("seat")
                            .and_then(|v| v.as_u64())
                            .ok_or("agent lacks seat")? as u8,
                        agent_name: entry
                            .get("agent_name")
                            .and_then(|v| v.as_str())
                            .ok_or("agent lacks name")?
                            .to_string(),
                        agent_version: entry
                            .get("agent_version")
                            .and_then(|v| v.as_str())
                            .ok_or("agent lacks version")?
                            .to_string(),
                    })
                })
                .collect::<Result<Vec<_>, &str>>()
        })
        .transpose()
        .map_err(|error| {
            format!(
                "match report {} has malformed agents: {error}",
                path.display()
            )
        })?
        .unwrap_or_default();
    let outcome_value = value
        .get("outcome")
        .ok_or_else(|| format!("match report {} lacks outcome", path.display()))?;
    let outcome: MatchOutcome = serde_json::from_value(outcome_value.clone()).map_err(|error| {
        format!(
            "match report {} has malformed outcome: {error}",
            path.display()
        )
    })?;
    Ok(MatchReport {
        game_id,
        agents,
        outcome,
    })
}

fn read_replay(run_dir: &Path, index: u32) -> Result<ReplayV1, String> {
    let path = match_replay_path(run_dir, index);
    let bytes = fs::read(&path)
        .map_err(|error| format!("cannot read replay {}: {error}", path.display()))?;
    serde_json::from_slice(&bytes)
        .map_err(|error| format!("invalid replay {}: {error}", path.display()))
}

pub fn match_report_path(run_dir: &Path, index: u32) -> PathBuf {
    run_dir.join(format!("matches/match-{index:06}.report.json"))
}

pub fn match_replay_path(run_dir: &Path, index: u32) -> PathBuf {
    run_dir.join(format!("matches/match-{index:06}.replay.json"))
}

/// Expected game id for a match slot: `{evaluation_id}-s{seed_index:06}-r{rotation:02}`.
fn expected_game_id(evaluation_id: &str, scheduled: u32, index: u32) -> Result<String, String> {
    if index >= scheduled {
        return Err(format!(
            "match index {index} is outside the {scheduled}-match schedule"
        ));
    }
    let seed_index = index / 2;
    let rotation = index % 2;
    Ok(format!("{evaluation_id}-s{seed_index:06}-r{rotation:02}"))
}

// ---------------------------------------------------------------------------
// API responses
// ---------------------------------------------------------------------------

#[derive(Debug, Serialize)]
pub struct ExperimentIndex {
    pub format: &'static str,
    pub version: u32,
    pub experiments: Vec<ExperimentIndexEntry>,
}

#[derive(Debug, Serialize)]
pub struct ExperimentIndexEntry {
    pub id: String,
    pub display_name: String,
    pub description: String,
    pub tracked_result: String,
    pub pairings: Vec<PairingIndexEntry>,
}

#[derive(Debug, Serialize)]
pub struct PairingIndexEntry {
    pub evaluation_id: String,
    pub candidate_model_id: String,
    pub opponent_model_id: String,
    pub status: String,
    pub scheduled_matches: u32,
    pub browsable_replays: u32,
    pub label: String,
    pub series: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub completed_before_abort: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub nontermination_match_slot: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub not_started_after_abort: Option<u32>,
}

#[derive(Debug, Serialize)]
pub struct PairingMatches {
    pub format: &'static str,
    pub version: u32,
    pub experiment_id: String,
    pub evaluation_id: String,
    pub candidate_model_id: String,
    pub opponent_model_id: String,
    pub pairing_status: String,
    pub scheduled_matches: u32,
    pub matches: Vec<MatchSlot>,
}

#[derive(Debug, Serialize)]
pub struct MatchSlot {
    pub match_index: u32,
    pub game_id: String,
    pub seed_index: u32,
    pub rotation: u32,
    pub availability: MatchAvailability,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub seed: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub candidate_seat: Option<u8>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub opponent_seat: Option<u8>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub scores: Option<Vec<u8>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub winner_seats: Option<Vec<u8>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub completed_plies: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub end_reason: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub candidate_won: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub replay_document_hash: Option<String>,
}

#[derive(Debug, Serialize, PartialEq, Eq, Clone, Copy)]
#[serde(rename_all = "snake_case")]
pub enum MatchAvailability {
    /// Formal scored replay (VALID pairing, completed match).
    Valid,
    /// Completed replay from an aborted pairing's prefix; NOT scored.
    ExcludedPrefix,
    /// The deterministic ply-limit failure slot itself; no replay exists.
    Nontermination,
    /// Slot was never started because the pairing aborted earlier.
    NotStarted,
}

#[derive(Debug, Serialize)]
pub struct ExperimentReplayBundle {
    pub format: &'static str,
    pub version: u32,
    pub experiment_id: String,
    pub evaluation_id: String,
    pub candidate_model_id: String,
    pub opponent_model_id: String,
    pub pairing_status: String,
    pub availability: MatchAvailability,
    pub match_index: u32,
    pub game_id: String,
    pub replay_document_hash: String,
    pub result: Option<BundleResult>,
    pub frames: Vec<BundleFrame>,
}

#[derive(Debug, Serialize)]
pub struct BundleResult {
    pub scores: Vec<u8>,
    pub winners: Vec<u8>,
    pub reason: String,
}

#[derive(Debug, Serialize)]
pub struct BundleFrame {
    pub ply: u32,
    pub actor: PlayerId,
    pub actor_model: String,
    pub actor_seat: u8,
    pub candidate_acted: bool,
    pub recorded_action: Action,
    pub legal_actions: Vec<Action>,
    pub player_view: Observation,
    pub referee_reveal: RefereeRevealV1,
}

// ---------------------------------------------------------------------------
// Library service
// ---------------------------------------------------------------------------

#[derive(Debug)]
pub struct ExperimentReplayLibrary {
    registry: ReplaySourceRegistry,
    repo_root: PathBuf,
    /// Canonical `local-artifacts` root; every served file must resolve
    /// inside it (symlink-proof containment).
    artifacts_root: PathBuf,
}

impl ExperimentReplayLibrary {
    pub fn load(registry_path: &Path, repo_root: &Path) -> Result<Self, String> {
        let registry = ReplaySourceRegistry::load(registry_path)?;
        // Fail-closed provenance and path binding: tracked-result SHA,
        // eval-report SHAs, and symlink-proof containment all verified at
        // load time.
        registry.validate_against_root(repo_root)?;
        let artifacts_root = repo_root
            .join("local-artifacts")
            .canonicalize()
            .map_err(|error| format!("cannot resolve local-artifacts root: {error}"))?;
        Ok(Self {
            registry,
            repo_root: repo_root.to_path_buf(),
            artifacts_root,
        })
    }

    pub fn registry(&self) -> &ReplaySourceRegistry {
        &self.registry
    }

    pub fn index(&self) -> Result<ExperimentIndex, String> {
        let mut experiments = Vec::new();
        for experiment in &self.registry.experiments {
            let pairings = experiment
                .pairings
                .iter()
                .map(|pairing| {
                    let browsable = match pairing.status.as_str() {
                        "VALID" => pairing.scheduled_matches,
                        _ => pairing.completed_before_abort.unwrap_or(0),
                    };
                    PairingIndexEntry {
                        label: pairing_label(pairing),
                        series: series_of(pairing),
                        evaluation_id: pairing.evaluation_id.clone(),
                        candidate_model_id: pairing.candidate_model_id.clone(),
                        opponent_model_id: pairing.opponent_model_id.clone(),
                        status: pairing.status.clone(),
                        scheduled_matches: pairing.scheduled_matches,
                        browsable_replays: browsable,
                        completed_before_abort: pairing.completed_before_abort,
                        nontermination_match_slot: pairing.nontermination_match_slot.clone(),
                        not_started_after_abort: pairing.not_started_after_abort,
                    }
                })
                .collect();
            experiments.push(ExperimentIndexEntry {
                id: experiment.id.clone(),
                display_name: experiment.display_name.clone(),
                description: experiment.description.clone(),
                tracked_result: experiment.tracked_result.clone(),
                pairings,
            });
        }
        Ok(ExperimentIndex {
            format: INDEX_FORMAT,
            version: INDEX_VERSION,
            experiments,
        })
    }

    pub fn pairing_matches(
        &self,
        experiment_id: &str,
        evaluation_id: &str,
    ) -> Result<PairingMatches, String> {
        let (experiment, pairing) = self.registry.pairing(experiment_id, evaluation_id)?;
        let run_dir = resolve_run_dir(&self.repo_root, &self.artifacts_root, &pairing.run_dir)?;
        let mut matches = Vec::new();
        for index in 0..pairing.scheduled_matches {
            let game_id =
                expected_game_id(&pairing.evaluation_id, pairing.scheduled_matches, index)?;
            let availability = self.slot_availability(pairing, index, &run_dir, &game_id)?;
            let mut slot = MatchSlot {
                match_index: index,
                game_id,
                seed_index: index / 2,
                rotation: index % 2,
                availability: availability.0,
                seed: None,
                candidate_seat: None,
                opponent_seat: None,
                scores: None,
                winner_seats: None,
                completed_plies: None,
                end_reason: None,
                candidate_won: None,
                replay_document_hash: None,
            };
            if let Some(report) = &availability.1 {
                // Seat mapping: r00 -> candidate seat 0; r01 -> candidate
                // seat 1 (arena right-rotation with 2 agents). The report's
                // own agent identities must agree with the pairing lineup.
                let candidate_seat = (index % 2) as u8;
                verify_agent_lineup(
                    report,
                    &pairing.evaluation_id,
                    &pairing.candidate_model_id,
                    &pairing.opponent_model_id,
                    candidate_seat,
                )?;
                slot.seed = Some(seed_from_game_id(
                    &report.game_id,
                    &pairing.evaluation_id,
                    index,
                )?);
                slot.candidate_seat = Some(candidate_seat);
                slot.opponent_seat = Some(1 - candidate_seat);
                slot.completed_plies = report.outcome.completed_plies;
                if let Some(result) = &report.outcome.result {
                    slot.scores = Some(result.scores.clone());
                    slot.winner_seats = Some(result.winners.iter().map(|w| w.0).collect());
                    slot.end_reason = Some(result.reason.clone());
                    slot.candidate_won = Some(result.winners.iter().any(|w| w.0 == candidate_seat));
                }
                // Replay document hash only when the replay file exists.
                if match_replay_path(&run_dir, index).exists() {
                    let replay = read_replay(&run_dir, index)?;
                    slot.replay_document_hash =
                        Some(replay_document_hash_v1(&replay).map_err(|e| e.to_string())?);
                }
            }
            matches.push(slot);
        }
        Ok(PairingMatches {
            format: INDEX_FORMAT,
            version: INDEX_VERSION,
            experiment_id: experiment.id.clone(),
            evaluation_id: pairing.evaluation_id.clone(),
            candidate_model_id: pairing.candidate_model_id.clone(),
            opponent_model_id: pairing.opponent_model_id.clone(),
            pairing_status: pairing.status.clone(),
            scheduled_matches: pairing.scheduled_matches,
            matches,
        })
    }

    /// Availability classification for one slot. Returns the availability
    /// plus the match report when one exists on disk.
    fn slot_availability(
        &self,
        pairing: &PairingSource,
        index: u32,
        run_dir: &Path,
        expected_id: &str,
    ) -> Result<(MatchAvailability, Option<MatchReport>), String> {
        let report_path = match_report_path(run_dir, index);
        if report_path.exists() {
            let report = read_match_report(run_dir, index)?;
            if report.game_id != expected_id {
                return Err(format!(
                    "match report {} has unexpected game id {} (expected {expected_id})",
                    report_path.display(),
                    report.game_id
                ));
            }
            if report.outcome.status != "completed" {
                return Err(format!(
                    "match report {} is not a completed match",
                    report_path.display()
                ));
            }
            let availability = if pairing.status == "VALID" {
                MatchAvailability::Valid
            } else {
                MatchAvailability::ExcludedPrefix
            };
            return Ok((availability, Some(report)));
        }
        if pairing.status != "VALID" {
            // EXCLUDED_PREFIX pairing: the missing slot is either the
            // ply-limit failure itself or a never-started match.
            if index == pairing.completed_before_abort.unwrap_or(0) {
                return Ok((MatchAvailability::Nontermination, None));
            }
            return Ok((MatchAvailability::NotStarted, None));
        }
        Err(format!(
            "VALID pairing slot {} is missing its match report at {}",
            index,
            report_path.display()
        ))
    }

    pub fn bundle(
        &self,
        experiment_id: &str,
        evaluation_id: &str,
        index: u32,
    ) -> Result<ExperimentReplayBundle, String> {
        let (experiment, pairing) = self.registry.pairing(experiment_id, evaluation_id)?;
        if index >= pairing.scheduled_matches {
            return Err(format!(
                "match index {index} is outside the {}-match schedule",
                pairing.scheduled_matches
            ));
        }
        let run_dir = resolve_run_dir(&self.repo_root, &self.artifacts_root, &pairing.run_dir)?;
        let game_id = expected_game_id(&pairing.evaluation_id, pairing.scheduled_matches, index)?;

        let report = read_match_report(&run_dir, index).map_err(|_| {
            format!(
                "match {index} has no replay: it is a {} slot",
                if pairing.status == "VALID" {
                    "missing"
                } else if index == pairing.completed_before_abort.unwrap_or(0) {
                    "NONTERMINATION (engine ply-limit abort)"
                } else {
                    "NOT_STARTED"
                }
            )
        })?;
        if report.game_id != game_id {
            return Err(format!(
                "match report game id `{}` does not match expected `{game_id}`",
                report.game_id
            ));
        }
        if report.outcome.status != "completed" {
            return Err("match did not complete; no replay bundle".into());
        }

        // Seat mapping: r00 -> candidate seat 0; r01 -> candidate seat 1.
        // The report's own agent identities must agree before any model
        // labeling is emitted.
        let candidate_seat = (index % 2) as u8;
        verify_agent_lineup(
            &report,
            &pairing.evaluation_id,
            &pairing.candidate_model_id,
            &pairing.opponent_model_id,
            candidate_seat,
        )?;

        let replay = read_replay(&run_dir, index)?;
        // Identity binding: replay final hash must equal the report's hash.
        let report_hash = report
            .outcome
            .replay_final_hash
            .as_deref()
            .ok_or("match report is missing replay_final_hash")?;
        if replay.final_state_hash.as_str() != report_hash {
            return Err(format!(
                "replay final hash {} does not match the recorded match hash {report_hash}",
                replay.final_state_hash.as_str()
            ));
        }
        if replay.steps.len() as u32 != report.outcome.completed_plies.unwrap_or(0) {
            return Err("replay step count does not match the recorded completed plies".into());
        }

        // Full re-verification: replay must re-execute cleanly.
        let trace: VerifiedReplayTrace =
            verify_replay_trace(&replay).map_err(|error| error.to_string())?;
        if trace.verified.steps as usize != replay.steps.len() {
            return Err("verified trace diverges from the replay steps".into());
        }

        let document_hash = replay_document_hash_v1(&replay).map_err(|error| error.to_string())?;

        // Model labels follow the lineup verified above.
        let model_for_seat = |seat: u8| -> String {
            if seat == candidate_seat {
                pairing.candidate_model_id.clone()
            } else {
                pairing.opponent_model_id.clone()
            }
        };

        let availability = if pairing.status == "VALID" {
            MatchAvailability::Valid
        } else {
            MatchAvailability::ExcludedPrefix
        };

        let mut frames = Vec::with_capacity(trace.positions.len());
        for position in &trace.positions {
            let actor = position.recorded_actor;
            let observation = position.state.observation(actor);
            let legal_actions = canonical_legal_actions(&position.state);
            frames.push(BundleFrame {
                ply: position.ply,
                actor,
                actor_seat: actor.0,
                actor_model: model_for_seat(actor.0),
                candidate_acted: actor.0 == candidate_seat,
                recorded_action: position.recorded_action,
                legal_actions,
                player_view: observation,
                referee_reveal: referee_projection(&position.state),
            });
        }

        let result = report.outcome.result.map(|result| BundleResult {
            scores: result.scores,
            winners: result.winners.iter().map(|w| w.0).collect(),
            reason: result.reason,
        });

        Ok(ExperimentReplayBundle {
            format: BUNDLE_FORMAT,
            version: BUNDLE_VERSION,
            experiment_id: experiment.id.clone(),
            evaluation_id: pairing.evaluation_id.clone(),
            candidate_model_id: pairing.candidate_model_id.clone(),
            opponent_model_id: pairing.opponent_model_id.clone(),
            pairing_status: pairing.status.clone(),
            availability,
            match_index: index,
            game_id,
            replay_document_hash: document_hash,
            result,
            frames,
        })
    }
}

fn series_of(pairing: &PairingSource) -> String {
    match pairing.opponent_model_id.as_str() {
        "M07" => "vs_m07".into(),
        "M25-D2-v2" => "vs_d2v2".into(),
        other => format!("vs_{other}"),
    }
}

fn pairing_label(pairing: &PairingSource) -> String {
    let opponent = match pairing.opponent_model_id.as_str() {
        "M07" => "M07".to_string(),
        "M25-D2-v2" => "D2-v2".to_string(),
        other => other.to_string(),
    };
    format!("{} vs {}", pairing.candidate_model_id, opponent)
}

/// Recover the game seed from a game id + schedule position. The schedule
/// maps `s{seed_index}` to `plan.game_seeds[seed_index]`; for M35A the
/// seeds are contiguous `300001..=300032`, and the report itself does not
/// carry the seed, so we re-derive it from the pairing's seed index using
/// the M35A convention, validated against the tracked result's ledger.
fn seed_from_game_id(game_id: &str, evaluation_id: &str, index: u32) -> Result<u64, String> {
    let suffix = game_id
        .strip_prefix(evaluation_id)
        .and_then(|rest| rest.strip_prefix('-'))
        .ok_or_else(|| format!("malformed game id `{game_id}`"))?;
    let mut parts = suffix.split('-');
    let seed_part = parts.next().ok_or("missing seed part in game id")?;
    let rotation_part = parts.next().ok_or("missing rotation part in game id")?;
    let seed_index: u32 = seed_part
        .strip_prefix('s')
        .and_then(|value| value.parse().ok())
        .ok_or("malformed seed index in game id")?;
    let rotation: u32 = rotation_part
        .strip_prefix('r')
        .and_then(|value| value.parse().ok())
        .ok_or("malformed rotation in game id")?;
    if seed_index * 2 + rotation != index {
        return Err(format!(
            "game id `{game_id}` does not agree with match index {index}"
        ));
    }
    // M35A frozen seed schedule: 300001..=300032.
    let seed = 300_001u64 + seed_index as u64;
    if !(300_001..=300_032).contains(&seed) {
        return Err(format!("derived seed {seed} is outside the M35A schedule"));
    }
    Ok(seed)
}

fn canonical_legal_actions(state: &FullState) -> Vec<Action> {
    splendor_search::canonical_order(&state.legal_actions()).to_vec()
}

fn referee_projection(state: &FullState) -> RefereeRevealV1 {
    RefereeRevealV1 {
        seed: state.seed,
        decks: state.decks.clone(),
        players: state.players.clone(),
    }
}

/// SHA-256 of a file, used by the manifest-style guard tests.
pub fn file_sha256(path: &Path) -> String {
    let mut file = fs::File::open(path).expect("open file");
    let mut hasher = Sha256::new();
    let mut buf = [0u8; 64 * 1024];
    use std::io::Read;
    loop {
        let n = file.read(&mut buf).expect("read chunk");
        if n == 0 {
            break;
        }
        hasher.update(&buf[..n]);
    }
    hex::encode(hasher.finalize())
}
