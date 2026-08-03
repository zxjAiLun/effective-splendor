//! The `analyze-replay-player-view` command (M07 C4).
//!
//! This command is the only binding layer between a referee-only replay and
//! the player-view imperfect-information API. It fully verifies the replay,
//! rebuilds the target state and visible prefix independently from the
//! verifier's captured position, projects only `VisibleEvent`s for the
//! recorded actor, then publishes a replay-bound C3 analysis artifact.
//!
//! Contract:
//! - all seven flags are required exactly once; unknown flags, positional
//!   tokens, `-h`/`--help`, and non-numeric values are usage errors (exit 2);
//! - runtime, replay, binding, search, and output failures are fatal (exit 1);
//! - success is silent on stdout and stderr;
//! - failure writes exactly one `error: ...` line to stderr and nothing to
//!   stdout;
//! - output is pretty JSON with one trailing LF and is atomically created
//!   without overwriting an existing target.

use std::fs::File;
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use splendor_core::{
    full_state_hash, observation_hash, ruleset_fingerprint, visible_events, Action, Audience,
    FullState, GameConfig, PlayerId, Ruleset, CATALOG_VERSION, ENGINE_VERSION,
};
use splendor_imperfect_search::{
    analyze_player_view_v1, RootDeterminizationConfigV1, RootDeterminizationResultV1,
    DETERMINIZATION_VERSION, IMPERFECT_SEARCH_ALGORITHM_ID, IMPERFECT_SEARCH_VERSION,
    INFORMATION_SET_VERSION,
};
use splendor_replay::{replay_document_hash_v1, verify_replay_position, ReplayV1};
use splendor_search::{SearchConfigV1, SEARCH_ALGORITHM_ID, SEARCH_VERSION};

use crate::atomic_output;

/// Frozen player-view artifact format identifier.
pub const PLAYER_VIEW_ANALYSIS_FORMAT: &str = "effective-splendor-imperfect-search-analysis";

/// Frozen player-view artifact schema version.
pub const PLAYER_VIEW_ANALYSIS_VERSION: u32 = 1;

/// Maximum accepted replay document size.
pub const MAX_REPLAY_BYTES: u64 = 16 * 1024 * 1024;

#[derive(Debug)]
enum AnalyzePlayerViewError {
    Usage(String),
    Fatal(String),
}

impl std::fmt::Display for AnalyzePlayerViewError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Usage(message) | Self::Fatal(message) => f.write_str(message),
        }
    }
}

/// Entry point for `splendor analyze-replay-player-view ...`.
pub fn run_analyze_replay_player_view(args: &[String]) -> i32 {
    match run_analyze_player_view_inner(args) {
        Ok(()) => 0,
        Err(error) => {
            let mut stderr = io::stderr().lock();
            let _ = writeln!(stderr, "error: {error}");
            let _ = stderr.flush();
            match error {
                AnalyzePlayerViewError::Usage(_) => 2,
                AnalyzePlayerViewError::Fatal(_) => 1,
            }
        }
    }
}

fn run_analyze_player_view_inner(args: &[String]) -> Result<(), AnalyzePlayerViewError> {
    let parsed = parse_analyze_player_view_args(args).map_err(AnalyzePlayerViewError::Usage)?;
    let continuation_search = SearchConfigV1 {
        max_depth_turns: parsed.max_depth_turns,
        max_nodes: parsed.max_nodes,
    };
    let config = RootDeterminizationConfigV1 {
        sample_seed: parsed.sample_seed,
        sample_count: parsed.sample_count,
        continuation_search,
    };
    config.validate().map_err(|error| {
        AnalyzePlayerViewError::Fatal(format!("invalid search config: {error}"))
    })?;

    if !parent_dir_exists(&parsed.out) {
        return Err(AnalyzePlayerViewError::Fatal(format!(
            "output parent directory does not exist: {}",
            parsed.out.display()
        )));
    }
    if parsed.out.exists() {
        return Err(AnalyzePlayerViewError::Fatal(format!(
            "artifact already exists: {}",
            parsed.out.display()
        )));
    }

    let replay = read_replay(&parsed.input)?;
    let position = verify_replay_position(&replay, parsed.ply).map_err(|error| {
        AnalyzePlayerViewError::Fatal(format!("replay verification failed: {error}"))
    })?;
    let replay_document_hash = replay_document_hash_v1(&replay).map_err(|error| {
        AnalyzePlayerViewError::Fatal(format!("replay document hash failed: {error}"))
    })?;

    let step = replay.steps.get(parsed.ply as usize).ok_or_else(|| {
        AnalyzePlayerViewError::Fatal("verified ply not present in replay".to_string())
    })?;
    bind_verified_position(&replay, &position, step, parsed.ply)?;

    let viewer = position.recorded_actor;
    let (reconstructed_state, visible_history) =
        reconstruct_visible_prefix(&replay, parsed.ply, viewer, &position)?;
    let observation = reconstructed_state.observation(viewer);
    if observation.viewer != viewer {
        return Err(AnalyzePlayerViewError::Fatal(
            "observation viewer does not match recorded actor".to_string(),
        ));
    }
    if full_state_hash(&reconstructed_state).as_str() != position.state_hash.as_str() {
        return Err(AnalyzePlayerViewError::Fatal(
            "reconstructed target hash does not match verified position".to_string(),
        ));
    }

    let player_view =
        analyze_player_view_v1(Ruleset::base_v1(), &observation, &visible_history, config)
            .map_err(|error| {
                AnalyzePlayerViewError::Fatal(format!("player-view analysis failed: {error}"))
            })?;
    let result = player_view.result();
    if result.root_player != viewer {
        return Err(AnalyzePlayerViewError::Fatal(
            "result root player does not match recorded actor".to_string(),
        ));
    }
    if !reconstructed_state.legal_actions().contains(&result.action) {
        return Err(AnalyzePlayerViewError::Fatal(
            "result action is not legal at the analyzed position".to_string(),
        ));
    }
    if !result
        .action_aggregates
        .iter()
        .any(|aggregate| aggregate.action == result.action)
    {
        return Err(AnalyzePlayerViewError::Fatal(
            "result action is absent from action aggregates".to_string(),
        ));
    }

    let visible_event_count = u32::try_from(visible_history.len()).map_err(|_| {
        AnalyzePlayerViewError::Fatal("visible event count exceeds u32".to_string())
    })?;
    let analysis = ReplayPlayerViewAnalysisV1 {
        format: PLAYER_VIEW_ANALYSIS_FORMAT.to_string(),
        version: PLAYER_VIEW_ANALYSIS_VERSION,
        engine_version: ENGINE_VERSION.to_string(),
        catalog_version: CATALOG_VERSION.to_string(),
        information_set_version: INFORMATION_SET_VERSION,
        determinization_version: DETERMINIZATION_VERSION,
        imperfect_search_algorithm_id: IMPERFECT_SEARCH_ALGORITHM_ID.to_string(),
        imperfect_search_version: IMPERFECT_SEARCH_VERSION,
        continuation_search_algorithm_id: SEARCH_ALGORITHM_ID.to_string(),
        continuation_search_version: SEARCH_VERSION,
        source: ReplayPlayerViewSourceV1 {
            replay_document_hash,
            replay_final_state_hash: replay.final_state_hash.as_str().to_string(),
            replay_version: replay.version,
            ruleset_fingerprint: replay.ruleset_fingerprint.as_str().to_string(),
            analyzed_ply: position.ply,
            analyzed_state_hash: position.state_hash.clone(),
            viewer,
            observation_hash: observation_hash(&observation).as_str().to_string(),
            visible_event_count,
            visible_history_hash: player_view.visible_history_hash().as_str().to_string(),
            information_set_hash: player_view.information_set_hash().as_str().to_string(),
            recorded_actor: position.recorded_actor,
            recorded_action: position.recorded_action,
        },
        config,
        result: result.clone(),
        recommended_matches_recorded: result.action == position.recorded_action,
    };

    let json = to_pretty_line(&analysis).map_err(|error| {
        AnalyzePlayerViewError::Fatal(format!("serialize analysis failed: {error}"))
    })?;
    atomic_output::commit_single(&parsed.out, &json)
        .map_err(|error| AnalyzePlayerViewError::Fatal(error.to_string()))?;

    Ok(())
}

fn bind_verified_position(
    replay: &ReplayV1,
    position: &splendor_replay::VerifiedReplayPosition,
    step: &splendor_replay::ReplayStepV1,
    requested_ply: u32,
) -> Result<(), AnalyzePlayerViewError> {
    let recomputed = full_state_hash(&position.state);
    if position.ply != requested_ply
        || position.state_hash != step.state_hash_before.as_str()
        || position.state_hash != recomputed.as_str()
    {
        return Err(AnalyzePlayerViewError::Fatal(
            "verified target hash does not match replay before-hash".to_string(),
        ));
    }
    if position.recorded_actor != step.actor
        || position.recorded_action != step.action
        || position.state.current_player != position.recorded_actor
    {
        return Err(AnalyzePlayerViewError::Fatal(
            "verified target actor or action does not match replay step".to_string(),
        ));
    }
    if position.verified.final_state_hash != replay.final_state_hash.as_str()
        || position.verified.steps != replay.steps.len() as u32
    {
        return Err(AnalyzePlayerViewError::Fatal(
            "verified replay summary does not match replay document".to_string(),
        ));
    }
    Ok(())
}

/// Rebuild the target state and the visible history without consulting the
/// referee log stored on `position.state`. The target step itself is excluded.
fn reconstruct_visible_prefix(
    replay: &ReplayV1,
    ply: u32,
    viewer: PlayerId,
    position: &splendor_replay::VerifiedReplayPosition,
) -> Result<(FullState, Vec<splendor_core::VisibleEvent>), AnalyzePlayerViewError> {
    let ruleset = Ruleset::base_v1();
    if ruleset_fingerprint(&ruleset).as_str() != replay.ruleset_fingerprint.as_str() {
        return Err(AnalyzePlayerViewError::Fatal(
            "reconstruction ruleset fingerprint does not match replay".to_string(),
        ));
    }
    let (mut state, setup) = FullState::new(GameConfig {
        player_count: replay.player_count,
        seed: replay.seed,
        ruleset,
    })
    .map_err(|error| AnalyzePlayerViewError::Fatal(format!("rebuild setup failed: {error}")))?;
    if full_state_hash(&state).as_str() != replay.initial_state_hash.as_str() {
        return Err(AnalyzePlayerViewError::Fatal(
            "reconstructed setup hash does not match replay".to_string(),
        ));
    }

    let audience = Audience::Player(viewer);
    let mut visible_history = visible_events(&setup.events, audience);
    for (index, step) in replay.steps.iter().take(ply as usize).enumerate() {
        if step.ply != index as u32 {
            return Err(AnalyzePlayerViewError::Fatal(format!(
                "reconstruction found non-contiguous ply {}",
                step.ply
            )));
        }
        if state.current_player != step.actor {
            return Err(AnalyzePlayerViewError::Fatal(format!(
                "reconstruction actor mismatch at ply {}",
                step.ply
            )));
        }
        let before = full_state_hash(&state);
        if before.as_str() != step.state_hash_before.as_str() {
            return Err(AnalyzePlayerViewError::Fatal(format!(
                "reconstruction before-hash mismatch at ply {}",
                step.ply
            )));
        }
        let step_result = state.apply(step.action).map_err(|error| {
            AnalyzePlayerViewError::Fatal(format!(
                "reconstruction action failed at ply {}: {error}",
                step.ply
            ))
        })?;
        state.assert_invariants().map_err(|error| {
            AnalyzePlayerViewError::Fatal(format!(
                "reconstruction invariant failed at ply {}: {error}",
                step.ply
            ))
        })?;
        let after = full_state_hash(&state);
        if after.as_str() != step.state_hash_after.as_str() {
            return Err(AnalyzePlayerViewError::Fatal(format!(
                "reconstruction after-hash mismatch at ply {}",
                step.ply
            )));
        }
        visible_history.extend(visible_events(&step_result.events, audience));
    }

    if full_state_hash(&state).as_str() != position.state_hash.as_str()
        || state.current_player != viewer
    {
        return Err(AnalyzePlayerViewError::Fatal(
            "reconstructed target does not match verified player view".to_string(),
        ));
    }
    Ok((state, visible_history))
}

/// Strictly read and deserialize a complete replay document.
fn read_replay(path: &Path) -> Result<ReplayV1, AnalyzePlayerViewError> {
    let file = File::open(path).map_err(|error| {
        AnalyzePlayerViewError::Fatal(format!("cannot open replay {}: {error}", path.display()))
    })?;
    let mut raw = Vec::new();
    file.take(MAX_REPLAY_BYTES + 1)
        .read_to_end(&mut raw)
        .map_err(|error| {
            AnalyzePlayerViewError::Fatal(format!("cannot read replay {}: {error}", path.display()))
        })?;
    if raw.len() as u64 > MAX_REPLAY_BYTES {
        return Err(AnalyzePlayerViewError::Fatal(format!(
            "replay exceeds {MAX_REPLAY_BYTES} bytes"
        )));
    }
    let text = String::from_utf8(raw)
        .map_err(|_| AnalyzePlayerViewError::Fatal("replay is not valid UTF-8".to_string()))?;
    let mut deserializer = serde_json::Deserializer::from_str(&text);
    let replay = ReplayV1::deserialize(&mut deserializer)
        .map_err(|error| AnalyzePlayerViewError::Fatal(format!("invalid replay: {error}")))?;
    deserializer.end().map_err(|_| {
        AnalyzePlayerViewError::Fatal("trailing data after replay JSON".to_string())
    })?;
    Ok(replay)
}

fn to_pretty_line<T: Serialize>(value: &T) -> serde_json::Result<String> {
    let mut json = serde_json::to_string_pretty(value)?;
    json.push('\n');
    Ok(json)
}

// ---------------------------------------------------------------------------
// Artifact DTOs
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct ReplayPlayerViewSourceV1 {
    replay_document_hash: String,
    replay_final_state_hash: String,
    replay_version: u32,
    ruleset_fingerprint: String,
    analyzed_ply: u32,
    analyzed_state_hash: String,
    viewer: PlayerId,
    observation_hash: String,
    visible_event_count: u32,
    visible_history_hash: String,
    information_set_hash: String,
    recorded_actor: PlayerId,
    recorded_action: Action,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct ReplayPlayerViewAnalysisV1 {
    format: String,
    version: u32,
    engine_version: String,
    catalog_version: String,
    information_set_version: u32,
    determinization_version: u32,
    imperfect_search_algorithm_id: String,
    imperfect_search_version: u32,
    continuation_search_algorithm_id: String,
    continuation_search_version: u32,
    source: ReplayPlayerViewSourceV1,
    config: RootDeterminizationConfigV1,
    result: RootDeterminizationResultV1,
    recommended_matches_recorded: bool,
}

// ---------------------------------------------------------------------------
// Strict argument parsing
// ---------------------------------------------------------------------------

#[derive(Debug)]
struct AnalyzePlayerViewArgs {
    input: PathBuf,
    ply: u32,
    sample_seed: u64,
    sample_count: u16,
    max_depth_turns: u8,
    max_nodes: u64,
    out: PathBuf,
}

fn parse_analyze_player_view_args(args: &[String]) -> Result<AnalyzePlayerViewArgs, String> {
    let mut input: Option<String> = None;
    let mut ply: Option<String> = None;
    let mut sample_seed: Option<String> = None;
    let mut sample_count: Option<String> = None;
    let mut max_depth_turns: Option<String> = None;
    let mut max_nodes: Option<String> = None;
    let mut out: Option<String> = None;

    let mut index = 0;
    while index < args.len() {
        match args[index].as_str() {
            "--input" => set_flag(&mut input, "--input", args.get(index + 1))?,
            "--ply" => set_flag(&mut ply, "--ply", args.get(index + 1))?,
            "--sample-seed" => set_flag(&mut sample_seed, "--sample-seed", args.get(index + 1))?,
            "--sample-count" => set_flag(&mut sample_count, "--sample-count", args.get(index + 1))?,
            "--max-depth-turns" => set_flag(
                &mut max_depth_turns,
                "--max-depth-turns",
                args.get(index + 1),
            )?,
            "--max-nodes" => set_flag(&mut max_nodes, "--max-nodes", args.get(index + 1))?,
            "--out" => set_flag(&mut out, "--out", args.get(index + 1))?,
            other if other.starts_with('-') => {
                return Err(format!("unknown flag `{other}`"));
            }
            other => return Err(format!("unexpected positional argument `{other}`")),
        }
        index += 2;
    }

    let input = input.ok_or_else(|| "missing required --input".to_string())?;
    let ply = ply.ok_or_else(|| "missing required --ply".to_string())?;
    let sample_seed = sample_seed.ok_or_else(|| "missing required --sample-seed".to_string())?;
    let sample_count = sample_count.ok_or_else(|| "missing required --sample-count".to_string())?;
    let max_depth_turns =
        max_depth_turns.ok_or_else(|| "missing required --max-depth-turns".to_string())?;
    let max_nodes = max_nodes.ok_or_else(|| "missing required --max-nodes".to_string())?;
    let out = out.ok_or_else(|| "missing required --out".to_string())?;

    Ok(AnalyzePlayerViewArgs {
        input: PathBuf::from(input),
        ply: parse_number("--ply", &ply)?,
        sample_seed: parse_number("--sample-seed", &sample_seed)?,
        sample_count: parse_number("--sample-count", &sample_count)?,
        max_depth_turns: parse_number("--max-depth-turns", &max_depth_turns)?,
        max_nodes: parse_number("--max-nodes", &max_nodes)?,
        out: PathBuf::from(out),
    })
}

fn parse_number<T: std::str::FromStr>(name: &str, raw: &str) -> Result<T, String> {
    raw.parse::<T>()
        .map_err(|_| format!("flag `{name}` expects an unsigned integer, got `{raw}`"))
}

fn set_flag(slot: &mut Option<String>, name: &str, value: Option<&String>) -> Result<(), String> {
    if slot.is_some() {
        return Err(format!("duplicate flag `{name}`"));
    }
    match value {
        Some(value) if !value.starts_with("--") => {
            *slot = Some(value.clone());
            Ok(())
        }
        _ => Err(format!("flag `{name}` is missing a value")),
    }
}

fn parent_dir_exists(path: &Path) -> bool {
    match path.parent() {
        Some(parent) if parent.as_os_str().is_empty() => true,
        Some(parent) => parent.is_dir(),
        None => true,
    }
}
