//! M39A authoritative trajectory materialization.
//!
//! The policy process writes a player-view sidecar while Arena writes the
//! referee report and replay.  This command joins those artifacts only after
//! replaying the complete game and rebuilding every learner observation and
//! ordered legal-action list from the referee state.  The resulting batch is
//! the only input accepted by the M39A PPO trainer.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::str::FromStr;

use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use splendor_arena::{
    seed_commitment_v1, ArenaOutcomeV1, ArenaReportV1, ARENA_REPORT_FORMAT, ARENA_REPORT_VERSION,
};
use splendor_core::{observation_hash, Action, Observation, PlayerId, RulesetFingerprint};
use splendor_league::arena_report_document_hash_v1;
use splendor_replay::{
    replay_document_hash_v1, rollout_prefix_document_hash_v1, verify_replay_trace,
    verify_rollout_prefix, ReplayGameResultV1, ReplayV1, RolloutPrefixV1,
};

use crate::atomic_output::commit_single;

const PLAN_FORMAT: &str = "effective-splendor-m39a-plan";
const PLAN_VERSION: u64 = 1;
const SIDECAR_FORMAT: &str = "effective-splendor-m39a-trajectory-sidecar";
const SIDECAR_VERSION: u32 = 1;
const MANIFEST_FORMAT: &str = "effective-splendor-m39a-materialization-manifest";
const MANIFEST_VERSION: u32 = 1;
const BATCH_FORMAT: &str = "effective-splendor-m39a-authoritative-batch";
const BATCH_VERSION: u32 = 1;
const PLAN_HASH_DOMAIN: &[u8] = b"effective-splendor-m39a-plan-v1\0";
const DECISION_SEED_BASE: u64 = 7_000_000;
const SPLITMIX64_GAMMA: u64 = 0x9E37_79B9_7F4A_7C15;
const SPLITMIX64_MUL1: u64 = 0xBF58_476D_1CE4_E5B9;
const SPLITMIX64_MUL2: u64 = 0x94D0_49BB_1331_11EB;
const GAMES_PER_CYCLE: u32 = 512;
const TRAINING_GAME_SEED_BASE: u64 = 4_000_000;
const M39A_AGENT_NAME: &str = "effective-splendor-m39a-policy-value-agent-v1";
const M07_AGENT_NAME: &str = "effective-splendor-determinization-agent-v1";
const M35A_AGENT_NAME: &str = "effective-splendor-m35a-direct-agent-v1";
const LEAGUE_ORDER: [&str; 9] = [
    "M24-S2",
    "M25-D2-v2",
    "M28A",
    "M28B",
    "M29A-v2",
    "M31A",
    "M32A",
    "M33A",
    "M34A",
];

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct MaterializationManifest {
    format: String,
    version: u32,
    mode: MaterializationMode,
    plan_hash: String,
    checkpoint_sha256: String,
    checkpoint_hash: String,
    checkpoint_cycle: u32,
    cycle: u32,
    ply_cap: u32,
    games: Vec<GameSource>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum MaterializationMode {
    Smoke,
    CompleteCycle,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct GameSource {
    game_index: u32,
    report_path: PathBuf,
    /// Terminal games: the full `ReplayV1`.
    replay_path: PathBuf,
    /// Truncated (ply-capped) games: the `RolloutPrefixV1`. One of
    /// `replay_path` / `prefix_path` must exist on disk; which one is
    /// authoritative is decided by the report's outcome, fail-closed.
    prefix_path: Option<PathBuf>,
    sidecar_paths: Vec<PathBuf>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct TrajectorySidecar {
    format: String,
    version: u32,
    plan_hash: String,
    checkpoint_sha256: String,
    checkpoint_hash: String,
    checkpoint_cycle: u32,
    catalog_hash: String,
    game_id: String,
    game_index: u32,
    seat: u8,
    records: Vec<SidecarRecord>,
    /// Terminal games: the engine result seen at `game_end`. Truncated
    /// (ply-capped) games: the no-result cap envelope seen at
    /// `game_truncated`.
    result: SidecarResult,
}

#[derive(Debug, Deserialize, PartialEq, Eq)]
#[serde(untagged)]
enum SidecarResult {
    Terminal(ReplayGameResultV1),
    Truncated(SidecarTruncatedResult),
}

#[derive(Debug, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
struct SidecarTruncatedResult {
    truncated: bool,
    completed_plies: u32,
    cap_state_hash: String,
    cap_scores: Vec<u8>,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct SidecarRecord {
    game_index: u32,
    game_id: String,
    seat: u8,
    ply_index: u32,
    request_id: u64,
    observation_hash: String,
    observation: Observation,
    legal_actions: Vec<Action>,
    action: Action,
    decision_seed: u64,
    old_log_probability: f64,
    old_value: f64,
    old_value_by_player: Vec<f64>,
    old_auxiliary_score: f64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(deny_unknown_fields)]
struct AuthoritativeResult {
    scores: Vec<u8>,
    centered_returns: Vec<f64>,
    truncated: bool,
    /// `Some` for games with a real terminal result (including completed
    /// games longer than the cap, where the terminal result exists but the
    /// training prefix uses the cap state). `None` for capped rollout
    /// prefix games, which never reached a terminal state and never
    /// fabricate one.
    source_terminal_result: Option<ReplayGameResultV1>,
}

#[derive(Debug, Serialize)]
#[serde(deny_unknown_fields)]
struct AuthoritativeRecord {
    game_index: u32,
    game_id: String,
    seat: u8,
    ply_index: u32,
    request_id: u64,
    observation_hash: String,
    observation: Observation,
    legal_actions: Vec<Action>,
    action: Action,
    decision_seed: u64,
    old_log_probability: f64,
    old_value: f64,
    old_value_by_player: Vec<f64>,
    old_auxiliary_score: f64,
    result: AuthoritativeResult,
    arena_report_hash: String,
    replay_document_hash: String,
    /// M40A predictive-label payload, derived from the referee trace.
    /// `prestige_after_ply[i]` = [self, opp] prestige immediately after
    /// the ply `record.ply_index + i` executed (i = 0 is the record's own
    /// action). Length = total_plies − ply_index. The final entry is the
    /// end-of-training-window prestige (terminal result for completed
    /// games; cap state for truncated ones).
    m40a_labels: M40aLabels,
}

/// Per-record predictive-label payload (M40A).
#[derive(Debug, Clone, Serialize)]
#[serde(deny_unknown_fields)]
struct M40aLabels {
    /// Seat-indexed [self, opp] prestige after each subsequent ply.
    prestige_after_ply: Vec<[u8; 2]>,
    /// Number of plies in the training window (== result is over the
    /// same window; completed: full game; truncated: the 150-ply prefix).
    window_plies: u32,
    /// Whether the game is truncated in the training window.
    truncated: bool,
}

#[derive(Debug, Serialize)]
#[serde(deny_unknown_fields)]
struct GameBinding {
    game_index: u32,
    game_id: String,
    seed: u64,
    completed_plies: u32,
    training_plies: u32,
    truncated: bool,
    learner_seats: Vec<u8>,
    arena_report_hash: String,
    replay_document_hash: String,
}

#[derive(Debug, Serialize)]
#[serde(deny_unknown_fields)]
struct AuthoritativeBatch {
    format: String,
    version: u32,
    mode: MaterializationMode,
    plan_hash: String,
    checkpoint_sha256: String,
    checkpoint_hash: String,
    checkpoint_cycle: u32,
    cycle: u32,
    ply_cap: u32,
    games: Vec<GameBinding>,
    records: Vec<AuthoritativeRecord>,
}

pub(crate) fn run_materialize(args: &[String]) -> i32 {
    match parse_args(args).and_then(|(plan, manifest, out)| materialize(&plan, &manifest, &out)) {
        Ok(summary) => {
            println!("{summary}");
            0
        }
        Err(error) => {
            eprintln!("error: {error}");
            2
        }
    }
}

fn parse_args(args: &[String]) -> Result<(PathBuf, PathBuf, PathBuf), String> {
    let mut values = BTreeMap::new();
    let mut index = 0;
    while index < args.len() {
        let flag = args[index].as_str();
        if !matches!(flag, "--plan" | "--manifest" | "--out") {
            return Err(format!("unknown argument `{flag}`"));
        }
        let value = args
            .get(index + 1)
            .ok_or_else(|| format!("missing value for `{flag}`"))?;
        if values.insert(flag, value).is_some() {
            return Err(format!("duplicate argument `{flag}`"));
        }
        index += 2;
    }
    let required = |flag| {
        values
            .get(flag)
            .map(|value| PathBuf::from(*value))
            .ok_or_else(|| format!("missing required argument `{flag}`"))
    };
    Ok((
        required("--plan")?,
        required("--manifest")?,
        required("--out")?,
    ))
}

fn read_json<T: for<'de> Deserialize<'de>>(path: &Path, label: &str) -> Result<T, String> {
    let bytes =
        fs::read(path).map_err(|error| format!("read {label} {}: {error}", path.display()))?;
    serde_json::from_slice(&bytes)
        .map_err(|error| format!("parse {label} {}: {error}", path.display()))
}

fn resolve(parent: &Path, path: &Path) -> PathBuf {
    if path.is_absolute() {
        path.to_path_buf()
    } else {
        parent.join(path)
    }
}

fn materialize(plan_path: &Path, manifest_path: &Path, out: &Path) -> Result<String, String> {
    if out.exists() {
        return Err(format!("output already exists: {}", out.display()));
    }
    let plan: Value = read_json(plan_path, "plan")?;
    let digest = plan_hash(&plan)?;
    let catalog_hash = plan
        .get("catalog")
        .and_then(|value| value.get("semantic_hash"))
        .and_then(Value::as_str)
        .ok_or_else(|| "plan.catalog.semantic_hash must be a string".to_string())?;
    let manifest: MaterializationManifest = read_json(manifest_path, "manifest")?;
    validate_manifest(&manifest, &digest)?;
    let parent = manifest_path.parent().unwrap_or_else(|| Path::new("."));

    let mut game_indices = BTreeSet::new();
    let mut bindings = Vec::with_capacity(manifest.games.len());
    let mut records = Vec::new();
    for source in &manifest.games {
        if !game_indices.insert(source.game_index) {
            return Err(format!("duplicate game_index {}", source.game_index));
        }
        let report: ArenaReportV1 =
            read_json(&resolve(parent, &source.report_path), "arena report")?;
        let sidecars = source
            .sidecar_paths
            .iter()
            .map(|path| read_json(&resolve(parent, path), "trajectory sidecar"))
            .collect::<Result<Vec<TrajectorySidecar>, String>>()?;
        let (binding, mut game_records) = match &report.outcome {
            ArenaOutcomeV1::Completed { .. } => {
                let replay: ReplayV1 = read_json(&resolve(parent, &source.replay_path), "replay")?;
                materialize_game(
                    &manifest,
                    catalog_hash,
                    source.game_index,
                    &report,
                    &replay,
                    &sidecars,
                )?
            }
            ArenaOutcomeV1::Truncated { .. } => {
                let prefix_path = source.prefix_path.as_ref().ok_or_else(|| {
                    format!(
                        "game {}: truncated report has no prefix_path in the manifest",
                        source.game_index
                    )
                })?;
                let prefix: RolloutPrefixV1 =
                    read_json(&resolve(parent, prefix_path), "rollout prefix")?;
                materialize_game_truncated(
                    &manifest,
                    catalog_hash,
                    source.game_index,
                    &report,
                    &prefix,
                    &sidecars,
                )?
            }
            ArenaOutcomeV1::Aborted { .. } => {
                return Err(format!(
                    "game {}: aborted arena report cannot enter training",
                    source.game_index
                ))
            }
        };
        bindings.push(binding);
        records.append(&mut game_records);
    }
    bindings.sort_by_key(|game| game.game_index);
    records.sort_by_key(|record| (record.game_index, record.ply_index, record.seat));
    if manifest.mode == MaterializationMode::CompleteCycle {
        let start = (manifest.cycle - 1) * GAMES_PER_CYCLE;
        let expected = (start..start + GAMES_PER_CYCLE).collect::<BTreeSet<_>>();
        if game_indices != expected {
            return Err(
                "complete_cycle manifest must contain exactly the cycle's 512 game indices".into(),
            );
        }
    }
    let batch = AuthoritativeBatch {
        format: BATCH_FORMAT.into(),
        version: BATCH_VERSION,
        mode: manifest.mode,
        plan_hash: digest,
        checkpoint_sha256: manifest.checkpoint_sha256,
        checkpoint_hash: manifest.checkpoint_hash,
        checkpoint_cycle: manifest.checkpoint_cycle,
        cycle: manifest.cycle,
        ply_cap: manifest.ply_cap,
        games: bindings,
        records,
    };
    let game_count = batch.games.len();
    let record_count = batch.records.len();
    let truncated = batch.games.iter().filter(|game| game.truncated).count();
    let json = serde_json::to_string_pretty(&batch).map_err(|error| error.to_string())? + "\n";
    commit_single(out, &json).map_err(|error| error.to_string())?;
    Ok(format!(
        "materialized games={game_count} records={record_count} truncated={truncated} out={}",
        out.display()
    ))
}

fn validate_manifest(manifest: &MaterializationManifest, plan_hash: &str) -> Result<(), String> {
    if manifest.format != MANIFEST_FORMAT || manifest.version != MANIFEST_VERSION {
        return Err("unsupported M39A materialization manifest format/version".into());
    }
    if manifest.plan_hash != plan_hash {
        return Err(format!(
            "manifest plan_hash {} does not match computed plan hash {plan_hash}",
            manifest.plan_hash
        ));
    }
    if !(1..=8).contains(&manifest.cycle) || manifest.checkpoint_cycle + 1 != manifest.cycle {
        return Err("manifest cycle/checkpoint_cycle must describe the next cycle in 1..=8".into());
    }
    if manifest.ply_cap != 150 {
        return Err("manifest ply_cap must equal 150".into());
    }
    validate_hash("checkpoint_sha256", &manifest.checkpoint_sha256)?;
    validate_hash("checkpoint_hash", &manifest.checkpoint_hash)?;
    if manifest.games.is_empty() {
        return Err("materialization manifest must contain at least one game".into());
    }
    Ok(())
}

fn materialize_game(
    manifest: &MaterializationManifest,
    catalog_hash: &str,
    game_index: u32,
    report: &ArenaReportV1,
    replay: &ReplayV1,
    sidecars: &[TrajectorySidecar],
) -> Result<(GameBinding, Vec<AuthoritativeRecord>), String> {
    if game_index / GAMES_PER_CYCLE + 1 != manifest.cycle {
        return Err(format!("game {game_index}: outside manifest cycle"));
    }
    let expected_seed = TRAINING_GAME_SEED_BASE + u64::from(game_index / 2);
    if replay.seed != expected_seed {
        return Err(format!(
            "game {game_index}: replay seed {} does not match frozen schedule {expected_seed}",
            replay.seed
        ));
    }
    bind_report_replay(report, replay).map_err(|error| format!("game {game_index}: {error}"))?;
    bind_scheduled_agents(report, manifest, game_index)?;
    let trace = verify_replay_trace(replay)
        .map_err(|error| format!("game {game_index}: replay verification failed: {error}"))?;
    let report_hash = arena_report_document_hash_v1(report).map_err(|error| error.to_string())?;
    let replay_hash = replay_document_hash_v1(replay).map_err(|error| error.to_string())?;
    let completed_plies = trace.verified.steps;
    let training_plies = completed_plies.min(manifest.ply_cap);
    let truncated = completed_plies > manifest.ply_cap;
    let training_scores = if truncated {
        trace
            .positions
            .get(manifest.ply_cap as usize)
            .ok_or_else(|| format!("game {game_index}: missing state at ply cap"))?
            .state
            .players
            .iter()
            .map(|player| player.prestige)
            .collect::<Vec<_>>()
    } else {
        trace.verified.result.scores.clone()
    };
    let centered = centered_returns(
        &training_scores,
        &Some(trace.verified.result.clone()),
        truncated,
    )?;
    let result = AuthoritativeResult {
        scores: training_scores.clone(),
        centered_returns: centered,
        truncated,
        source_terminal_result: Some(trace.verified.result.clone()),
    };
    // M40A label window finality: for a completed game the window ends at
    // the terminal state, whose prestige IS the terminal result's scores;
    // for a truncated game the window ends at the ply cap, whose prestige
    // is the cap-instant training_scores. In both cases `training_scores`
    // is the per-seat prestige at the end of the training window.
    let window_final_prestige = [training_scores[0], training_scores[1]];

    let expected_seats = learner_seats(game_index);
    let actual_seats = sidecars
        .iter()
        .map(|sidecar| sidecar.seat)
        .collect::<BTreeSet<_>>();
    if actual_seats != expected_seats {
        return Err(format!(
            "game {game_index}: learner sidecars {:?} do not match schedule {:?}",
            actual_seats, expected_seats
        ));
    }
    let mut output = Vec::new();
    for sidecar in sidecars {
        validate_sidecar(sidecar, manifest, catalog_hash, game_index, report, replay)?;
        let mut seen_plies = BTreeSet::new();
        for record in &sidecar.records {
            if record.ply_index >= training_plies {
                continue;
            }
            if !seen_plies.insert(record.ply_index) {
                return Err(format!(
                    "game {game_index}: duplicate sidecar ply {}",
                    record.ply_index
                ));
            }
            let position = trace
                .positions
                .get(record.ply_index as usize)
                .ok_or_else(|| format!("game {game_index}: sidecar ply outside replay"))?;
            if position.recorded_actor != PlayerId(sidecar.seat)
                || position.recorded_action != record.action
            {
                return Err(format!(
                    "game {game_index}: actor/action mismatch at ply {}",
                    record.ply_index
                ));
            }
            let observation = position.state.observation(position.recorded_actor);
            let observation_digest = observation_hash(&observation).as_str().to_string();
            if observation != record.observation || observation_digest != record.observation_hash {
                return Err(format!(
                    "game {game_index}: observation mismatch at ply {}",
                    record.ply_index
                ));
            }
            let legal_actions = position.state.legal_actions();
            if legal_actions != record.legal_actions {
                return Err(format!(
                    "game {game_index}: ordered legal actions mismatch at ply {}",
                    record.ply_index
                ));
            }
            if record.request_id != u64::from(record.ply_index) + 1
                || record.decision_seed
                    != decision_seed(game_index, sidecar.seat, record.request_id)
            {
                return Err(format!(
                    "game {game_index}: request/decision seed mismatch at ply {}",
                    record.ply_index
                ));
            }
            if !record.old_log_probability.is_finite()
                || !record.old_value.is_finite()
                || !record.old_auxiliary_score.is_finite()
                || record.old_value_by_player.len() != 2
                || record
                    .old_value_by_player
                    .iter()
                    .any(|value| !value.is_finite())
            {
                return Err(format!(
                    "game {game_index}: non-finite or malformed model output at ply {}",
                    record.ply_index
                ));
            }
            if !record.legal_actions.contains(&record.action) {
                return Err(format!(
                    "game {game_index}: chosen action not legal at ply {}",
                    record.ply_index
                ));
            }
            let labels = m40a_labels_for_record(
                sidecar.seat,
                record.ply_index,
                &trace.positions,
                training_plies,
                window_final_prestige,
                truncated,
            );
            output.push(AuthoritativeRecord {
                game_index,
                game_id: report.game_id.clone(),
                seat: sidecar.seat,
                ply_index: record.ply_index,
                request_id: record.request_id,
                observation_hash: observation_digest,
                observation,
                legal_actions,
                action: record.action,
                decision_seed: record.decision_seed,
                old_log_probability: record.old_log_probability,
                old_value: record.old_value,
                old_value_by_player: record.old_value_by_player.clone(),
                old_auxiliary_score: record.old_auxiliary_score,
                result: result.clone(),
                arena_report_hash: report_hash.clone(),
                replay_document_hash: replay_hash.clone(),
                m40a_labels: labels,
            });
        }
        let expected_plies = trace
            .positions
            .iter()
            .take(training_plies as usize)
            .filter(|position| position.recorded_actor == PlayerId(sidecar.seat))
            .map(|position| position.ply)
            .collect::<BTreeSet<_>>();
        if seen_plies != expected_plies {
            return Err(format!(
                "game {game_index}: sidecar is missing or adds learner decisions before the cap"
            ));
        }
    }
    Ok((
        GameBinding {
            game_index,
            game_id: report.game_id.clone(),
            seed: replay.seed,
            completed_plies,
            training_plies,
            truncated,
            learner_seats: expected_seats.into_iter().collect(),
            arena_report_hash: report_hash,
            replay_document_hash: replay_hash,
        },
        output,
    ))
}

/// Materialize one truncated (ply-capped) game from its rollout prefix.
///
/// Mirrors [`materialize_game`]'s checks, but the authoritative document is
/// the [`RolloutPrefixV1`]: every step is re-executed, the cap state hash is
/// verified, and the pre-registered truncation return is computed from the
/// cap-instant VP differential. There is no terminal result and none is
/// fabricated.
#[allow(clippy::too_many_arguments)]
fn materialize_game_truncated(
    manifest: &MaterializationManifest,
    catalog_hash: &str,
    game_index: u32,
    report: &ArenaReportV1,
    prefix: &RolloutPrefixV1,
    sidecars: &[TrajectorySidecar],
) -> Result<(GameBinding, Vec<AuthoritativeRecord>), String> {
    if game_index / GAMES_PER_CYCLE + 1 != manifest.cycle {
        return Err(format!("game {game_index}: outside manifest cycle"));
    }
    let expected_seed = TRAINING_GAME_SEED_BASE + u64::from(game_index / 2);
    if prefix.seed != expected_seed {
        return Err(format!(
            "game {game_index}: prefix seed {} does not match frozen schedule {expected_seed}",
            prefix.seed
        ));
    }
    if prefix.player_count != 2 {
        return Err(format!("game {game_index}: prefix is not 1v1"));
    }
    let (report_cap_hash, report_plies, report_cap_scores) = match &report.outcome {
        ArenaOutcomeV1::Truncated {
            completed_plies,
            cap_state_hash,
            cap_scores,
        } => (cap_state_hash.clone(), *completed_plies, cap_scores.clone()),
        _ => {
            return Err(format!(
                "game {game_index}: prefix materialization requires a truncated report"
            ))
        }
    };
    if report_plies != manifest.ply_cap || prefix.ply_cap != manifest.ply_cap {
        return Err(format!(
            "game {game_index}: truncated plies do not equal the manifest ply cap"
        ));
    }
    if report_cap_hash != prefix.cap_state_hash.as_str() {
        return Err(format!(
            "game {game_index}: report cap hash does not bind the prefix"
        ));
    }
    if report.format != ARENA_REPORT_FORMAT || report.version != ARENA_REPORT_VERSION {
        return Err("invalid arena report format/version".into());
    }
    if report.player_count != 2
        || report.ruleset != prefix.ruleset.id
        || report.ruleset_fingerprint != prefix.ruleset_fingerprint.as_str()
        || report.engine_version != prefix.engine_version
    {
        return Err("arena compatibility metadata does not match prefix".into());
    }
    let fingerprint = RulesetFingerprint::from_str(&report.ruleset_fingerprint)
        .map_err(|error| format!("invalid ruleset fingerprint: {error}"))?;
    if report.seed_commitment
        != seed_commitment_v1(
            &report.game_id,
            prefix.player_count,
            prefix.seed,
            &fingerprint,
        )
    {
        return Err("seed commitment does not bind prefix".into());
    }
    bind_scheduled_agents(report, manifest, game_index)?;

    let verified = verify_rollout_prefix(prefix)
        .map_err(|error| format!("game {game_index}: prefix verification failed: {error}"))?;
    let report_hash = arena_report_document_hash_v1(report).map_err(|error| error.to_string())?;
    let prefix_hash = rollout_prefix_document_hash_v1(prefix).map_err(|error| error.to_string())?;

    // Cap-instant VP from the rebuilt state; cross-check against the report.
    let cap_state = verified
        .positions
        .last()
        .map(|position| &position.state)
        .ok_or_else(|| format!("game {game_index}: empty prefix trace"))?;
    let _ = cap_state; // positions[0..n-1] are pre-action states; cap state is rebuilt below.
    let cap_scores: Vec<u8> = {
        // The verifier's positions are pre-action states; rebuild the cap
        // state by re-applying the recorded steps (verify already confirmed
        // the terminal cap hash, so this reconstruction is exact).
        let mut state = verified
            .positions
            .first()
            .map(|position| position.state.clone())
            .ok_or_else(|| format!("game {game_index}: empty prefix trace"))?;
        for step in &prefix.steps {
            state
                .apply(step.action)
                .map_err(|error| format!("game {game_index}: prefix replay failed: {error}"))?;
        }
        state.players.iter().map(|player| player.prestige).collect()
    };
    if cap_scores != report_cap_scores {
        return Err(format!(
            "game {game_index}: rebuilt cap scores do not match the report"
        ));
    }

    let training_plies = prefix.ply_cap;
    let completed_plies = report_plies;
    let centered = centered_returns(&cap_scores, &None, true)?;
    let result = AuthoritativeResult {
        scores: cap_scores.clone(),
        centered_returns: centered,
        truncated: true,
        source_terminal_result: None,
    };
    // M40A: the truncated window ends at the ply cap; the window-final
    // prestige is the cap-instant scores. `verified.positions` are
    // pre-action states, so prestige-after-ply falls back to the cap
    // scores at the last ply of the window.
    let window_final_prestige = [cap_scores[0], cap_scores[1]];

    let expected_seats = learner_seats(game_index);
    let actual_seats = sidecars
        .iter()
        .map(|sidecar| sidecar.seat)
        .collect::<BTreeSet<_>>();
    if actual_seats != expected_seats {
        return Err(format!(
            "game {game_index}: learner sidecars {:?} do not match schedule {:?}",
            actual_seats, expected_seats
        ));
    }
    let mut output = Vec::new();
    for sidecar in sidecars {
        validate_sidecar_prefix(sidecar, manifest, catalog_hash, game_index, report, prefix)?;
        let mut seen_plies = BTreeSet::new();
        for record in &sidecar.records {
            if record.ply_index >= training_plies {
                continue;
            }
            if !seen_plies.insert(record.ply_index) {
                return Err(format!(
                    "game {game_index}: duplicate sidecar ply {}",
                    record.ply_index
                ));
            }
            let position = verified
                .positions
                .get(record.ply_index as usize)
                .ok_or_else(|| format!("game {game_index}: sidecar ply outside prefix"))?;
            if position.recorded_actor != PlayerId(sidecar.seat)
                || position.recorded_action != record.action
            {
                return Err(format!(
                    "game {game_index}: actor/action mismatch at ply {}",
                    record.ply_index
                ));
            }
            let observation = position.state.observation(position.recorded_actor);
            let observation_digest = observation_hash(&observation).as_str().to_string();
            if observation != record.observation || observation_digest != record.observation_hash {
                return Err(format!(
                    "game {game_index}: observation mismatch at ply {}",
                    record.ply_index
                ));
            }
            let legal_actions = position.state.legal_actions();
            if legal_actions != record.legal_actions {
                return Err(format!(
                    "game {game_index}: ordered legal actions mismatch at ply {}",
                    record.ply_index
                ));
            }
            if record.request_id != u64::from(record.ply_index) + 1
                || record.decision_seed
                    != decision_seed(game_index, sidecar.seat, record.request_id)
            {
                return Err(format!(
                    "game {game_index}: request/decision seed mismatch at ply {}",
                    record.ply_index
                ));
            }
            if !record.old_log_probability.is_finite()
                || !record.old_value.is_finite()
                || !record.old_auxiliary_score.is_finite()
                || record.old_value_by_player.len() != 2
                || record
                    .old_value_by_player
                    .iter()
                    .any(|value| !value.is_finite())
            {
                return Err(format!(
                    "game {game_index}: non-finite or malformed model output at ply {}",
                    record.ply_index
                ));
            }
            if !record.legal_actions.contains(&record.action) {
                return Err(format!(
                    "game {game_index}: chosen action not legal at ply {}",
                    record.ply_index
                ));
            }
            let labels = m40a_labels_for_record(
                sidecar.seat,
                record.ply_index,
                &verified.positions,
                training_plies,
                window_final_prestige,
                true,
            );
            output.push(AuthoritativeRecord {
                game_index,
                game_id: report.game_id.clone(),
                seat: sidecar.seat,
                ply_index: record.ply_index,
                request_id: record.request_id,
                observation_hash: observation_digest,
                observation,
                legal_actions,
                action: record.action,
                decision_seed: record.decision_seed,
                old_log_probability: record.old_log_probability,
                old_value: record.old_value,
                old_value_by_player: record.old_value_by_player.clone(),
                old_auxiliary_score: record.old_auxiliary_score,
                result: result.clone(),
                arena_report_hash: report_hash.clone(),
                replay_document_hash: prefix_hash.clone(),
                m40a_labels: labels,
            });
        }
        let expected_plies = verified
            .positions
            .iter()
            .take(training_plies as usize)
            .filter(|position| position.recorded_actor == PlayerId(sidecar.seat))
            .map(|position| position.ply)
            .collect::<BTreeSet<_>>();
        if seen_plies != expected_plies {
            return Err(format!(
                "game {game_index}: sidecar is missing or adds learner decisions before the cap"
            ));
        }
    }
    Ok((
        GameBinding {
            game_index,
            game_id: report.game_id.clone(),
            seed: prefix.seed,
            completed_plies,
            training_plies,
            truncated: true,
            learner_seats: expected_seats.into_iter().collect(),
            arena_report_hash: report_hash,
            replay_document_hash: prefix_hash,
        },
        output,
    ))
}

/// Compute the M40A predictive-label payload for one retained record.
///
/// `positions[p]` is the referee state BEFORE ply `p` (the shared shape
/// of `VerifiedReplayTrace::positions` and
/// `VerifiedRolloutPrefix::positions`). The prestige AFTER ply `p` is
/// taken from `positions[p + 1]` when it exists; for the final ply of
/// the training window the caller supplies the terminal (completed game)
/// or cap-instant (truncated game) per-seat prestige, which the
/// authoritative result already carries.
fn m40a_labels_for_record(
    seat: u8,
    ply_index: u32,
    positions: &[splendor_replay::VerifiedReplayTraceStep],
    total_plies: u32,
    window_final_prestige: [u8; 2],
    truncated: bool,
) -> M40aLabels {
    let viewer = usize::from(seat);
    let mut prestige_after_ply = Vec::with_capacity((total_plies - ply_index) as usize);
    for ply in ply_index..total_plies {
        let entry = match positions.get(ply as usize + 1) {
            Some(position) => {
                let players = &position.state.players;
                [players[viewer].prestige, players[1 - viewer].prestige]
            }
            None => window_final_prestige,
        };
        prestige_after_ply.push(entry);
    }
    M40aLabels {
        prestige_after_ply,
        window_plies: total_plies,
        truncated,
    }
}

fn bind_scheduled_agents(
    report: &ArenaReportV1,
    manifest: &MaterializationManifest,
    game_index: u32,
) -> Result<(), String> {
    let learner = learner_seats(game_index);
    let ordinal = game_index % GAMES_PER_CYCLE;
    let cycle_zero = game_index / GAMES_PER_CYCLE;
    let league_ordinal = cycle_zero * 128 + ordinal.saturating_sub(192);
    for seat in 0..2u8 {
        let identity = report
            .agents
            .iter()
            .find(|identity| identity.seat == PlayerId(seat))
            .ok_or_else(|| {
                format!("game {game_index}: missing runtime identity for seat {seat}")
            })?;
        let actual_name = identity
            .agent_name
            .as_deref()
            .ok_or_else(|| format!("game {game_index}: seat {seat} has no runtime name"))?;
        let actual_version = identity
            .agent_version
            .as_deref()
            .ok_or_else(|| format!("game {game_index}: seat {seat} has no runtime version"))?;
        let (expected_name, expected_version) = if learner.contains(&seat) {
            (M39A_AGENT_NAME, manifest.checkpoint_hash.as_str())
        } else if ordinal < 16 {
            ("splendor-cli-random", splendor_core::ENGINE_VERSION)
        } else if ordinal < 64 {
            ("splendor-cli-heuristic", "0.1.0")
        } else if ordinal < 192 {
            (M07_AGENT_NAME, "1")
        } else if ordinal < 320 {
            (
                M35A_AGENT_NAME,
                LEAGUE_ORDER[league_ordinal as usize % LEAGUE_ORDER.len()],
            )
        } else {
            (M39A_AGENT_NAME, manifest.checkpoint_hash.as_str())
        };
        if actual_name != expected_name || actual_version != expected_version {
            return Err(format!(
                "game {game_index}: seat {seat} runtime `{actual_name}@{actual_version}` does not match frozen `{expected_name}@{expected_version}`"
            ));
        }
    }
    Ok(())
}

fn validate_sidecar(
    sidecar: &TrajectorySidecar,
    manifest: &MaterializationManifest,
    catalog_hash: &str,
    game_index: u32,
    report: &ArenaReportV1,
    replay: &ReplayV1,
) -> Result<(), String> {
    if sidecar.format != SIDECAR_FORMAT || sidecar.version != SIDECAR_VERSION {
        return Err(format!(
            "game {game_index}: unsupported sidecar format/version"
        ));
    }
    if sidecar.plan_hash != manifest.plan_hash
        || sidecar.checkpoint_sha256 != manifest.checkpoint_sha256
        || sidecar.checkpoint_hash != manifest.checkpoint_hash
        || sidecar.checkpoint_cycle != manifest.checkpoint_cycle
        || sidecar.catalog_hash != catalog_hash
        || sidecar.game_id != report.game_id
        || sidecar.game_index != game_index
        || sidecar.result != SidecarResult::Terminal(replay.result.clone())
    {
        return Err(format!(
            "game {game_index}: sidecar provenance/result mismatch"
        ));
    }
    if sidecar.seat > 1 {
        return Err(format!("game {game_index}: invalid sidecar seat"));
    }
    for record in &sidecar.records {
        if record.game_index != game_index
            || record.game_id != report.game_id
            || record.seat != sidecar.seat
        {
            return Err(format!("game {game_index}: record envelope mismatch"));
        }
    }
    Ok(())
}

/// Terminal-game sidecar validation counterpart for truncated games: the
/// sidecar's result must be the no-result cap envelope matching the report
/// and the prefix exactly.
#[allow(clippy::too_many_arguments)]
fn validate_sidecar_prefix(
    sidecar: &TrajectorySidecar,
    manifest: &MaterializationManifest,
    catalog_hash: &str,
    game_index: u32,
    report: &ArenaReportV1,
    prefix: &RolloutPrefixV1,
) -> Result<(), String> {
    if sidecar.format != SIDECAR_FORMAT || sidecar.version != SIDECAR_VERSION {
        return Err(format!(
            "game {game_index}: unsupported sidecar format/version"
        ));
    }
    let expected = SidecarResult::Truncated(SidecarTruncatedResult {
        truncated: true,
        completed_plies: prefix.ply_cap,
        cap_state_hash: prefix.cap_state_hash.as_str().to_string(),
        cap_scores: match &report.outcome {
            ArenaOutcomeV1::Truncated { cap_scores, .. } => cap_scores.clone(),
            _ => return Err(format!("game {game_index}: report is not truncated")),
        },
    });
    if sidecar.plan_hash != manifest.plan_hash
        || sidecar.checkpoint_sha256 != manifest.checkpoint_sha256
        || sidecar.checkpoint_hash != manifest.checkpoint_hash
        || sidecar.checkpoint_cycle != manifest.checkpoint_cycle
        || sidecar.catalog_hash != catalog_hash
        || sidecar.game_id != report.game_id
        || sidecar.game_index != game_index
        || sidecar.result != expected
    {
        return Err(format!(
            "game {game_index}: sidecar provenance/truncation mismatch"
        ));
    }
    if sidecar.seat > 1 {
        return Err(format!("game {game_index}: invalid sidecar seat"));
    }
    for record in &sidecar.records {
        if record.game_index != game_index
            || record.game_id != report.game_id
            || record.seat != sidecar.seat
        {
            return Err(format!("game {game_index}: record envelope mismatch"));
        }
    }
    Ok(())
}

fn bind_report_replay(report: &ArenaReportV1, replay: &ReplayV1) -> Result<(), String> {
    if report.format != ARENA_REPORT_FORMAT || report.version != ARENA_REPORT_VERSION {
        return Err("invalid arena report format/version".into());
    }
    if report.player_count != 2
        || replay.player_count != 2
        || report.player_count != replay.player_count
        || report.ruleset != replay.ruleset.id
        || report.ruleset_fingerprint != replay.ruleset_fingerprint.as_str()
        || report.engine_version != replay.engine_version
    {
        return Err("arena compatibility metadata does not match 1v1 replay".into());
    }
    let fingerprint = RulesetFingerprint::from_str(&report.ruleset_fingerprint)
        .map_err(|error| format!("invalid ruleset fingerprint: {error}"))?;
    if report.seed_commitment
        != seed_commitment_v1(
            &report.game_id,
            replay.player_count,
            replay.seed,
            &fingerprint,
        )
    {
        return Err("seed commitment does not bind replay".into());
    }
    match &report.outcome {
        ArenaOutcomeV1::Completed {
            result,
            completed_plies,
            replay_final_hash,
        } if *completed_plies == replay.steps.len() as u32
            && replay_final_hash == replay.final_state_hash.as_str()
            && replay.result.matches(result) => {}
        ArenaOutcomeV1::Completed { .. } => {
            return Err("completed arena outcome does not match replay".into())
        }
        ArenaOutcomeV1::Aborted { .. } => {
            return Err("aborted arena report cannot enter training".into())
        }
        ArenaOutcomeV1::Truncated { .. } => {
            return Err("truncated arena report binds a rollout prefix, not a replay".into())
        }
    }
    if report.agents.len() != 2
        || report
            .agents
            .iter()
            .map(|agent| agent.seat.0)
            .collect::<BTreeSet<_>>()
            != BTreeSet::from([0, 1])
    {
        return Err("arena report agent seats are not exactly 0 and 1".into());
    }
    Ok(())
}

fn centered_returns(
    scores: &[u8],
    terminal: &Option<ReplayGameResultV1>,
    truncated: bool,
) -> Result<Vec<f64>, String> {
    if scores.len() != 2 {
        return Err("1v1 result must contain two scores".into());
    }
    if truncated {
        let delta = (f64::from(scores[0]) - f64::from(scores[1])) / 4.0;
        return Ok(vec![-0.5 + 0.5 * delta.tanh(), -0.5 - 0.5 * delta.tanh()]);
    }
    let terminal = terminal
        .as_ref()
        .ok_or_else(|| "non-truncated result requires a terminal result".to_string())?;
    if terminal.ranks.len() != 2 {
        return Err("terminal result must contain two ranks".into());
    }
    Ok(if terminal.ranks[0] == terminal.ranks[1] {
        vec![0.0, 0.0]
    } else if terminal.ranks[0] < terminal.ranks[1] {
        vec![1.0, -1.0]
    } else {
        vec![-1.0, 1.0]
    })
}

fn learner_seats(game_index: u32) -> BTreeSet<u8> {
    let ordinal = game_index % GAMES_PER_CYCLE;
    if ordinal >= 320 {
        BTreeSet::from([0, 1])
    } else {
        BTreeSet::from([(game_index % 2) as u8])
    }
}

fn splitmix64(value: u64) -> u64 {
    let mut z = value.wrapping_add(SPLITMIX64_GAMMA);
    z = (z ^ (z >> 30)).wrapping_mul(SPLITMIX64_MUL1);
    z = (z ^ (z >> 27)).wrapping_mul(SPLITMIX64_MUL2);
    z ^ (z >> 31)
}

fn decision_seed(game_index: u32, seat: u8, request_id: u64) -> u64 {
    let game_seed = splitmix64(DECISION_SEED_BASE + 2 * u64::from(game_index) + u64::from(seat));
    splitmix64(game_seed ^ request_id.wrapping_mul(SPLITMIX64_GAMMA))
}

fn plan_hash(plan: &Value) -> Result<String, String> {
    if plan.get("format").and_then(Value::as_str) != Some(PLAN_FORMAT)
        || plan.get("version").and_then(Value::as_u64) != Some(PLAN_VERSION)
    {
        return Err("unsupported M39A plan format/version".into());
    }
    let json = python_canonical_json(plan)?.into_bytes();
    let mut hasher = Sha256::new();
    hasher.update(PLAN_HASH_DOMAIN);
    hasher.update(json);
    Ok(hex::encode(hasher.finalize()))
}

/// Match Python's frozen ``json.dumps(sort_keys=True, separators=(",", ":"),
/// ensure_ascii=False, allow_nan=False)`` contract.  In particular Python
/// switches small floats to scientific notation earlier than serde_json and
/// pads one-digit exponents (``1e-08``).  Rust's f64 Debug formatter uses the
/// same shortest-roundtrip significand; the small exponent normalization is
/// the only remaining spelling difference.
fn python_canonical_json(value: &Value) -> Result<String, String> {
    match value {
        Value::Null => Ok("null".into()),
        Value::Bool(value) => Ok(value.to_string()),
        Value::Number(number) => {
            if let Some(value) = number.as_i64() {
                return Ok(value.to_string());
            }
            if let Some(value) = number.as_u64() {
                return Ok(value.to_string());
            }
            let value = number
                .as_f64()
                .filter(|value| value.is_finite())
                .ok_or_else(|| "plan contains a non-finite number".to_string())?;
            let mut rendered = format!("{value:?}");
            if let Some(exponent) = rendered.find('e') {
                let digits = rendered.len() - exponent - 2;
                if digits == 1 {
                    rendered.insert(exponent + 2, '0');
                }
            }
            Ok(rendered)
        }
        Value::String(value) => serde_json::to_string(value).map_err(|error| error.to_string()),
        Value::Array(values) => {
            let rendered = values
                .iter()
                .map(python_canonical_json)
                .collect::<Result<Vec<_>, _>>()?;
            Ok(format!("[{}]", rendered.join(",")))
        }
        Value::Object(values) => {
            let mut entries = values.iter().collect::<Vec<_>>();
            entries.sort_by(|(left, _), (right, _)| left.cmp(right));
            let rendered = entries
                .into_iter()
                .map(|(key, value)| {
                    Ok(format!(
                        "{}:{}",
                        serde_json::to_string(key).map_err(|error| error.to_string())?,
                        python_canonical_json(value)?
                    ))
                })
                .collect::<Result<Vec<String>, String>>()?;
            Ok(format!("{{{}}}", rendered.join(",")))
        }
    }
}

fn validate_hash(label: &str, value: &str) -> Result<(), String> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(format!("{label} must be 64 lowercase hex characters"));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use splendor_arena::{AgentIdentity, ArenaReportV1};
    use splendor_core::{GameResult, TerminalReason};
    use splendor_replay::{record_random_game, ReplayTerminalReason};
    use std::sync::atomic::{AtomicU64, Ordering};

    static TEST_SEQUENCE: AtomicU64 = AtomicU64::new(0);

    fn temp_dir() -> PathBuf {
        let sequence = TEST_SEQUENCE.fetch_add(1, Ordering::SeqCst);
        let path = std::env::temp_dir().join(format!(
            "m39a-materialize-test-{}-{sequence}",
            std::process::id()
        ));
        fs::create_dir_all(&path).unwrap();
        path
    }

    fn runtime_result(replay: &ReplayV1) -> GameResult {
        GameResult {
            scores: replay.result.scores.clone(),
            ranks: replay.result.ranks.clone(),
            winners: replay
                .result
                .winners
                .iter()
                .copied()
                .map(PlayerId)
                .collect(),
            reason: match replay.result.reason {
                ReplayTerminalReason::PrestigeThreshold => TerminalReason::PrestigeThreshold,
                ReplayTerminalReason::Stalemate => TerminalReason::Stalemate,
            },
        }
    }

    #[test]
    fn rust_plan_hash_matches_python_contract() {
        let plan: Value = read_json(
            &PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("../../benchmarks/m39a-arena-driven-policy-value-rl.plan.json"),
            "plan",
        )
        .unwrap();
        assert_eq!(
            plan_hash(&plan).unwrap(),
            "06cbd7b2413b7e640402799ff25c25ae57985ab3ea25b113b3eddf053f2841d6"
        );
    }

    #[test]
    fn decision_seed_matches_python_fixed_vectors() {
        assert_eq!(decision_seed(0, 0, 1), 9_830_301_397_363_971_053);
        assert_eq!(decision_seed(0, 1, 2), 12_458_482_928_076_461_532);
    }

    #[test]
    fn learner_seats_follow_frozen_schedule() {
        assert_eq!(learner_seats(0), BTreeSet::from([0]));
        assert_eq!(learner_seats(1), BTreeSet::from([1]));
        assert_eq!(learner_seats(320), BTreeSet::from([0, 1]));
        assert_eq!(learner_seats(511), BTreeSet::from([0, 1]));
    }

    #[test]
    fn authoritative_join_accepts_rebuilt_player_view_and_rejects_tamper() {
        let directory = temp_dir();
        let (_, replay) = record_random_game(2, 4_000_000, 99).unwrap();
        let trace = verify_replay_trace(&replay).unwrap();
        let game_id = "m39a-unit-game";
        let fingerprint =
            RulesetFingerprint::from_str(replay.ruleset_fingerprint.as_str()).unwrap();
        let report = ArenaReportV1::new(
            game_id,
            replay.engine_version.clone(),
            "0.5",
            replay.ruleset.id.clone(),
            replay.ruleset_fingerprint.as_str(),
            2,
            seed_commitment_v1(game_id, 2, replay.seed, &fingerprint),
            vec![
                AgentIdentity {
                    seat: PlayerId(0),
                    agent_name: Some("effective-splendor-m39a-policy-value-agent-v1".into()),
                    agent_version: Some("b".repeat(64)),
                },
                AgentIdentity {
                    seat: PlayerId(1),
                    agent_name: Some("splendor-cli-random".into()),
                    agent_version: Some("0.4.0".into()),
                },
            ],
            ArenaOutcomeV1::completed(
                runtime_result(&replay),
                replay.steps.len() as u32,
                replay.final_state_hash.as_str().to_string(),
            ),
        );
        let records = trace
            .positions
            .iter()
            .filter(|position| position.recorded_actor == PlayerId(0))
            .map(|position| {
                let observation = position.state.observation(PlayerId(0));
                SidecarRecord {
                    game_index: 0,
                    game_id: game_id.into(),
                    seat: 0,
                    ply_index: position.ply,
                    request_id: u64::from(position.ply) + 1,
                    observation_hash: observation_hash(&observation).as_str().into(),
                    observation,
                    legal_actions: position.state.legal_actions(),
                    action: position.recorded_action,
                    decision_seed: decision_seed(0, 0, u64::from(position.ply) + 1),
                    old_log_probability: -1.0,
                    old_value: 0.0,
                    old_value_by_player: vec![0.0, 0.0],
                    old_auxiliary_score: 0.0,
                }
            })
            .collect::<Vec<_>>();
        let sidecar = TrajectorySidecar {
            format: SIDECAR_FORMAT.into(),
            version: SIDECAR_VERSION,
            plan_hash: "06cbd7b2413b7e640402799ff25c25ae57985ab3ea25b113b3eddf053f2841d6".into(),
            checkpoint_sha256: "a".repeat(64),
            checkpoint_hash: "b".repeat(64),
            checkpoint_cycle: 0,
            catalog_hash: "4c90cb85d565e74af3e955df62d431174aaf5a8d4192895f95c8d21d57d78a26".into(),
            game_id: game_id.into(),
            game_index: 0,
            seat: 0,
            records,
            result: SidecarResult::Terminal(replay.result.clone()),
        };
        let manifest = MaterializationManifest {
            format: MANIFEST_FORMAT.into(),
            version: MANIFEST_VERSION,
            mode: MaterializationMode::Smoke,
            plan_hash: sidecar.plan_hash.clone(),
            checkpoint_sha256: sidecar.checkpoint_sha256.clone(),
            checkpoint_hash: sidecar.checkpoint_hash.clone(),
            checkpoint_cycle: 0,
            cycle: 1,
            ply_cap: 150,
            games: Vec::new(),
        };
        let (binding, output) = materialize_game(
            &manifest,
            &sidecar.catalog_hash,
            0,
            &report,
            &replay,
            std::slice::from_ref(&sidecar),
        )
        .unwrap();
        assert_eq!(binding.completed_plies, replay.steps.len() as u32);
        assert_eq!(output.len(), sidecar.records.len());

        let mut tampered = sidecar;
        tampered.records[0].observation.public.bank.gold ^= 1;
        let catalog_hash = tampered.catalog_hash.clone();
        let error =
            match materialize_game(&manifest, &catalog_hash, 0, &report, &replay, &[tampered]) {
                Ok(_) => panic!("tampered observation must be rejected"),
                Err(error) => error,
            };
        assert!(error.contains("observation mismatch"));
        fs::remove_dir_all(directory).ok();
    }

    #[test]
    fn truncated_prefix_join_produces_truncated_returns_and_rejects_mismatch() {
        // Build a 5-ply prefix from a recorded random game by replaying the
        // first five steps through a fresh recorder.
        let (_, replay) = record_random_game(2, 4_000_000, 99).unwrap();
        let cap = 5u32;
        let mut recorder = splendor_replay::ReplayRecorder::new(splendor_core::GameConfig {
            player_count: 2,
            seed: replay.seed,
            ..Default::default()
        })
        .unwrap();
        for step in replay.steps.iter().take(cap as usize) {
            recorder.apply(step.action).unwrap();
        }
        assert!(!recorder.is_terminal());
        let (state, prefix) = recorder.finish_prefix(cap).unwrap();
        let cap_scores: Vec<u8> = state.players.iter().map(|p| p.prestige).collect();
        let verified_prefix = verify_rollout_prefix(&prefix).unwrap();

        let game_id = "m39a-unit-truncated";
        let fingerprint =
            RulesetFingerprint::from_str(prefix.ruleset_fingerprint.as_str()).unwrap();
        let report = ArenaReportV1::new(
            game_id,
            prefix.engine_version.clone(),
            "0.5",
            prefix.ruleset.id.clone(),
            prefix.ruleset_fingerprint.as_str(),
            2,
            seed_commitment_v1(game_id, 2, prefix.seed, &fingerprint),
            vec![
                AgentIdentity {
                    seat: PlayerId(0),
                    agent_name: Some("effective-splendor-m39a-policy-value-agent-v1".into()),
                    agent_version: Some("b".repeat(64)),
                },
                AgentIdentity {
                    seat: PlayerId(1),
                    agent_name: Some("splendor-cli-random".into()),
                    agent_version: Some("0.4.0".into()),
                },
            ],
            ArenaOutcomeV1::truncated(
                cap,
                prefix.cap_state_hash.as_str().to_string(),
                cap_scores.clone(),
            ),
        );

        let records = verified_prefix
            .positions
            .iter()
            .filter(|position| position.recorded_actor == PlayerId(0))
            .map(|position| {
                let observation = position.state.observation(PlayerId(0));
                SidecarRecord {
                    game_index: 0,
                    game_id: game_id.into(),
                    seat: 0,
                    ply_index: position.ply,
                    request_id: u64::from(position.ply) + 1,
                    observation_hash: observation_hash(&observation).as_str().into(),
                    observation,
                    legal_actions: position.state.legal_actions(),
                    action: position.recorded_action,
                    decision_seed: decision_seed(0, 0, u64::from(position.ply) + 1),
                    old_log_probability: -1.0,
                    old_value: 0.0,
                    old_value_by_player: vec![0.0, 0.0],
                    old_auxiliary_score: 0.0,
                }
            })
            .collect::<Vec<_>>();
        let sidecar = TrajectorySidecar {
            format: SIDECAR_FORMAT.into(),
            version: SIDECAR_VERSION,
            plan_hash: "06cbd7b2413b7e640402799ff25c25ae57985ab3ea25b113b3eddf053f2841d6".into(),
            checkpoint_sha256: "a".repeat(64),
            checkpoint_hash: "b".repeat(64),
            checkpoint_cycle: 0,
            catalog_hash: "4c90cb85d565e74af3e955df62d431174aaf5a8d4192895f95c8d21d57d78a26".into(),
            game_id: game_id.into(),
            game_index: 0,
            seat: 0,
            records,
            result: SidecarResult::Truncated(SidecarTruncatedResult {
                truncated: true,
                completed_plies: cap,
                cap_state_hash: prefix.cap_state_hash.as_str().to_string(),
                cap_scores: cap_scores.clone(),
            }),
        };
        let manifest = MaterializationManifest {
            format: MANIFEST_FORMAT.into(),
            version: MANIFEST_VERSION,
            mode: MaterializationMode::Smoke,
            plan_hash: sidecar.plan_hash.clone(),
            checkpoint_sha256: sidecar.checkpoint_sha256.clone(),
            checkpoint_hash: sidecar.checkpoint_hash.clone(),
            checkpoint_cycle: 0,
            cycle: 1,
            ply_cap: cap,
            games: Vec::new(),
        };
        let (binding, output) = materialize_game_truncated(
            &manifest,
            &sidecar.catalog_hash,
            0,
            &report,
            &prefix,
            std::slice::from_ref(&sidecar),
        )
        .unwrap();
        assert_eq!(binding.completed_plies, cap);
        assert_eq!(binding.training_plies, cap);
        assert!(binding.truncated);
        assert!(!output.is_empty());
        let delta = (f64::from(cap_scores[0]) - f64::from(cap_scores[1])) / 4.0;
        let expected_first = -0.5 + 0.5 * delta.tanh();
        assert!((output[0].result.centered_returns[0] - expected_first).abs() < 1e-12);
        assert!(output[0].result.truncated);
        assert!(output[0].result.source_terminal_result.is_none());

        // A sidecar claiming the wrong cap scores must be rejected.
        let mut wrong = sidecar;
        if let SidecarResult::Truncated(ref mut envelope) = wrong.result {
            envelope.cap_scores[0] = envelope.cap_scores[0].saturating_add(1);
        }
        let catalog_hash = wrong.catalog_hash.clone();
        let error = materialize_game_truncated(
            &manifest,
            &catalog_hash,
            0,
            &report,
            &prefix,
            std::slice::from_ref(&wrong),
        )
        .unwrap_err();
        assert!(error.contains("truncation mismatch"), "got: {error}");
    }
}
