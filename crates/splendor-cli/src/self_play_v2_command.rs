//! M24 self-play dataset v2: provenance-bound replay + diagnostic audit.
//!
//! The existing `collect-gpu-self-play` command and its version-1 dataset stay
//! byte-for-byte frozen for M18A/M22 reproducibility. M24 introduces a second
//! collector that emits `effective-splendor-neural-self-play-v2` with:
//!
//! - per-game verified `ReplayV1` plus document/final-state hashes;
//! - per-example observation / visible-history / information-set hashes;
//! - explicit search visit and viewer-relative value targets;
//! - a strict CPU-only diagnostic command that re-verifies every game and
//!   every example without touching the GPU model or the search tree.

use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};

use rand::rngs::SmallRng;
use rand::SeedableRng;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use splendor_belief::build_information_set_v1;
use splendor_core::{
    observation_hash, ruleset_fingerprint, visible_events, Action, Audience, GameConfig,
    GameResult, Observation, PlayerId, Ruleset, ENGINE_VERSION,
};
use splendor_neural_agent::{GpuInferenceConfigV1, GpuPolicyValueEvaluatorV1};
use splendor_neural_search::{
    search_neural_ismcts_with_evaluator_v1, NeuralIsmctsActionStatsV1, NeuralIsmctsConfigV1,
};
use splendor_replay::{
    replay_document_hash_v1, verify_replay, verify_replay_trace, ReplayRecorder, ReplayV1,
};
use splendor_search::canonical_order;

use crate::atomic_output;
use crate::m18a_command::{hash_bytes, sample_visits, validate_config, SelfPlayConfigV1};

const COLLECT_USAGE: &str =
    "Usage: splendor collect-gpu-self-play-v2 --config <config.json> --out <dataset.json>";
const DIAGNOSE_USAGE: &str =
    "Usage: splendor diagnose-gpu-self-play-v2 --input <dataset.json> --config <config.json> --out <diagnostics.json>";
const DATASET_FORMAT_V2: &str = "effective-splendor-neural-self-play-v2";
const DATASET_VERSION_V2: u32 = 2;
const DIAGNOSTICS_FORMAT: &str = "effective-splendor-self-play-diagnostics";
const DIAGNOSTICS_VERSION: u32 = 1;
const DATASET_HASH_DOMAIN_V2: &[u8] = b"effective-splendor-neural-self-play-v2\0";
const CONFIG_HASH_DOMAIN_V1: &[u8] = b"effective-splendor-self-play-config-v1\0";

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct SelfPlayGameSourceV2 {
    game_index: u32,
    game_seed: u64,
    base_checkpoint_hash: String,
    collector_config_hash: String,
    search_config_identity: String,
    replay_document_hash: String,
    replay_final_state_hash: String,
    replay: ReplayV1,
    result: GameResult,
    first_example_index: u32,
    example_count: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct SelfPlayExampleV2 {
    game_index: u32,
    ply: u32,
    actor: u8,
    observation: Observation,
    observation_hash: String,
    visible_history_hash: String,
    information_set_hash: String,
    legal_actions: Vec<Action>,
    action_stats: Vec<NeuralIsmctsActionStatsV1>,
    chosen_action: Action,
    final_scores: Vec<u8>,
    final_ranks: Vec<u8>,
    policy_target_visits: Vec<u32>,
    value_target: Vec<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct SelfPlayDatasetV2 {
    format: String,
    version: u32,
    self_play_id: String,
    engine_version: String,
    ruleset: String,
    ruleset_fingerprint: String,
    base_checkpoint_hash: String,
    collector_config_hash: String,
    search_config_identity: String,
    games: Vec<SelfPlayGameSourceV2>,
    examples: Vec<SelfPlayExampleV2>,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct SummaryStatsV1 {
    count: u64,
    min: f64,
    max: f64,
    mean: f64,
    p25: f64,
    p50: f64,
    p75: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct DiagnosticsReportV1 {
    format: String,
    version: u32,
    diagnostics_id: String,
    dataset_format: String,
    dataset_version: u32,
    dataset_file_sha256: String,
    dataset_semantic_hash: String,
    config_file_sha256: String,
    collector_config_hash: String,
    base_checkpoint_hash: String,
    search_config_identity: String,
    games: u32,
    examples: u64,
    games_verified: u32,
    duplicate_game_seeds: u32,
    plies_per_game: SummaryStatsV1,
    legal_actions_per_decision: SummaryStatsV1,
    legal_action_type_counts: BTreeMap<String, u64>,
    chosen_action_type_counts: BTreeMap<String, u64>,
    policy_entropy: SummaryStatsV1,
    visit_entropy: SummaryStatsV1,
    duplicate_observation_rate: f64,
    duplicate_information_set_rate: f64,
    value_target_counts: BTreeMap<String, u64>,
    winner_seat_counts: BTreeMap<String, u64>,
}

pub fn run_collect_gpu_self_play_v2(args: &[String]) -> i32 {
    if args == ["--help"] || args == ["-h"] {
        println!("{COLLECT_USAGE}");
        return 0;
    }
    match collect_v2(args) {
        Ok(summary) => {
            println!("{summary}");
            0
        }
        Err(error) => {
            eprintln!("error: {error}");
            1
        }
    }
}

pub fn run_diagnose_gpu_self_play_v2(args: &[String]) -> i32 {
    if args == ["--help"] || args == ["-h"] {
        println!("{DIAGNOSE_USAGE}");
        return 0;
    }
    match diagnose_v2(args) {
        Ok(summary) => {
            println!("{summary}");
            0
        }
        Err(error) => {
            eprintln!("error: {error}");
            1
        }
    }
}

fn collect_v2(args: &[String]) -> Result<String, String> {
    let (config_path, out_path) = parse_collect_args(args)?;
    let config = read_config(&config_path)?;
    let config_bytes = fs::read(&config_path)
        .map_err(|error| format!("cannot read config {}: {error}", config_path.display()))?;
    let collector_config_hash = hash_bytes(CONFIG_HASH_DOMAIN_V1, &config_bytes);
    if out_path.exists() {
        return Err(format!("output already exists: {}", out_path.display()));
    }

    let evaluator = GpuPolicyValueEvaluatorV1::spawn(&GpuInferenceConfigV1 {
        python: config.python.clone(),
        module_root: config.module_root.clone(),
        checkpoint: config.checkpoint.clone(),
        checkpoint_hash: config.checkpoint_hash.clone(),
        catalog: config.catalog.clone(),
        device: config.device.clone(),
    })
    .map_err(|error| error.to_string())?;

    let mut action_rng = SmallRng::seed_from_u64(config.action_seed);
    let ruleset = Ruleset::base_v1();
    let search_config_identity = search_config_identity(&config);
    let mut games = Vec::with_capacity(config.game_seeds.len());
    let mut examples: Vec<SelfPlayExampleV2> = Vec::new();

    for (game_index, &seed) in config.game_seeds.iter().enumerate() {
        let game_index_u32 = u32::try_from(game_index).map_err(|_| "too many games")?;
        let mut recorder = ReplayRecorder::new(GameConfig {
            player_count: 2,
            seed,
            ruleset,
        })
        .map_err(|error| error.to_string())?;
        let first_example_index = u32::try_from(examples.len())
            .map_err(|_| "too many examples for u32 game source index")?;
        let mut ply = 0u32;

        while !recorder.is_terminal() {
            if ply >= config.max_plies {
                return Err(format!("game {game_index} exceeded max_plies"));
            }
            let state = recorder.state();
            let actor = state.current_player;
            let observation = state.observation(actor);
            let history = visible_events(&state.log, Audience::Player(actor));
            let information_set = build_information_set_v1(ruleset, &observation, &history)
                .map_err(|error| error.to_string())?;
            let legal_actions = canonical_order(&state.legal_actions());
            let search_seed = config
                .search_seed
                .wrapping_add(u64::from(game_index_u32) << 32)
                .wrapping_add(u64::from(ply));
            let search_result = search_neural_ismcts_with_evaluator_v1(
                &information_set,
                &evaluator,
                &NeuralIsmctsConfigV1 {
                    sample_seed: search_seed,
                    simulations: config.simulations,
                    max_depth_turns: config.max_depth_turns,
                    puct_exploration_milli: config.puct_exploration_milli,
                    expected_checkpoint_hash: config.checkpoint_hash.clone(),
                },
            )
            .map_err(|error| error.to_string())?;
            let chosen_action = if ply < config.temperature_plies {
                sample_visits(&search_result.action_stats, &mut action_rng)?
            } else {
                search_result.action
            };
            if !legal_actions.contains(&chosen_action) {
                return Err("search selected an illegal action".into());
            }

            let policy_target_visits = legal_actions
                .iter()
                .map(|action| {
                    search_result
                        .action_stats
                        .iter()
                        .find(|stats| stats.action == *action)
                        .map(|stats| stats.visits)
                        .ok_or_else(|| "action_stats missing a legal root action".to_string())
                })
                .collect::<Result<Vec<_>, _>>()?;

            examples.push(SelfPlayExampleV2 {
                game_index: game_index_u32,
                ply,
                actor: actor.0,
                observation_hash: observation_hash(&observation).as_str().to_string(),
                visible_history_hash: information_set.visible_history_hash().as_str().to_string(),
                information_set_hash: information_set.information_set_hash().as_str().to_string(),
                observation,
                legal_actions,
                action_stats: search_result.action_stats,
                chosen_action,
                final_scores: Vec::new(),
                final_ranks: Vec::new(),
                policy_target_visits,
                value_target: Vec::new(),
            });
            recorder
                .apply(chosen_action)
                .map_err(|error| error.to_string())?;
            ply += 1;
        }

        let (state, replay) = recorder.finish().map_err(|error| error.to_string())?;
        verify_replay(&replay)
            .map_err(|error| format!("game {game_index}: replay verification failed: {error}"))?;
        let result = state
            .result
            .clone()
            .ok_or_else(|| "terminal game has no result".to_string())?;
        let replay_document_hash = replay_document_hash_v1(&replay)
            .map_err(|error| format!("game {game_index}: {error}"))?;
        let replay_final_state_hash = replay.final_state_hash.as_str().to_string();
        let example_count = u32::try_from(examples.len())
            .ok()
            .and_then(|end| end.checked_sub(first_example_index))
            .ok_or("example range arithmetic failed")?;

        for example in &mut examples[first_example_index as usize..] {
            example.final_scores.clone_from(&result.scores);
            example.final_ranks.clone_from(&result.ranks);
            example.value_target = viewer_relative_value_target(example.actor, &result.ranks)?;
        }

        games.push(SelfPlayGameSourceV2 {
            game_index: game_index_u32,
            game_seed: seed,
            base_checkpoint_hash: config.checkpoint_hash.clone(),
            collector_config_hash: collector_config_hash.clone(),
            search_config_identity: search_config_identity.clone(),
            replay_document_hash,
            replay_final_state_hash,
            replay,
            result,
            first_example_index,
            example_count,
        });
    }

    let dataset = SelfPlayDatasetV2 {
        format: DATASET_FORMAT_V2.into(),
        version: DATASET_VERSION_V2,
        self_play_id: config.self_play_id,
        engine_version: ENGINE_VERSION.into(),
        ruleset: ruleset.id.0.into(),
        ruleset_fingerprint: ruleset_fingerprint(&ruleset).to_string(),
        base_checkpoint_hash: config.checkpoint_hash,
        collector_config_hash,
        search_config_identity,
        games,
        examples,
    };
    let compact = serde_json::to_vec(&dataset).map_err(|error| error.to_string())?;
    let output = serde_json::to_string_pretty(&dataset).map_err(|error| error.to_string())?;
    let semantic_hash = hash_bytes(DATASET_HASH_DOMAIN_V2, &compact);
    if let Some(parent) = out_path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let temp = atomic_output::write_temp(&out_path, &output).map_err(|error| error.to_string())?;
    atomic_output::publish_new(&temp, &out_path).map_err(|error| error.to_string())?;
    let summary = serde_json::json!({
        "status": "ok",
        "out": out_path.display().to_string(),
        "self_play_hash": semantic_hash,
        "games": dataset.games.len(),
        "examples": dataset.examples.len(),
    });
    serde_json::to_string(&summary).map_err(|error| error.to_string())
}

fn diagnose_v2(args: &[String]) -> Result<String, String> {
    let (input_path, config_path, out_path) = parse_diagnose_args(args)?;
    if input_path == out_path || config_path == out_path {
        return Err("--out must differ from --input and --config".into());
    }
    if out_path.exists() {
        return Err(format!("output already exists: {}", out_path.display()));
    }
    let config = read_config(&config_path)?;
    let config_bytes = fs::read(&config_path)
        .map_err(|error| format!("cannot read config {}: {error}", config_path.display()))?;
    let collector_config_hash = hash_bytes(CONFIG_HASH_DOMAIN_V1, &config_bytes);
    let config_file_sha256 = file_sha256(&config_path)?;
    let expected_search_identity = search_config_identity(&config);
    let dataset_bytes = fs::read(&input_path)
        .map_err(|error| format!("cannot read dataset {}: {error}", input_path.display()))?;
    let dataset: SelfPlayDatasetV2 = serde_json::from_slice(&dataset_bytes)
        .map_err(|error| format!("invalid self-play v2 dataset: {error}"))?;
    let diagnostics_id = format!("{}-diagnostics-v1", dataset.self_play_id);
    let dataset_file_sha256 = file_sha256(&input_path)?;
    let report = audit_dataset(
        &dataset,
        &config,
        &collector_config_hash,
        &expected_search_identity,
        dataset_file_sha256,
        config_file_sha256,
        diagnostics_id,
    )?;
    let output = serde_json::to_string_pretty(&report).map_err(|error| error.to_string())?;
    if let Some(parent) = out_path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let temp = atomic_output::write_temp(&out_path, &output).map_err(|error| error.to_string())?;
    atomic_output::publish_new(&temp, &out_path).map_err(|error| error.to_string())?;
    serde_json::to_string(&serde_json::json!({
        "status": "ok",
        "out": out_path.display().to_string(),
        "games": report.games,
        "examples": report.examples,
    }))
    .map_err(|error| error.to_string())
}

fn read_config(path: &Path) -> Result<SelfPlayConfigV1, String> {
    let bytes = fs::read(path)
        .map_err(|error| format!("cannot read config {}: {error}", path.display()))?;
    let config: SelfPlayConfigV1 =
        serde_json::from_slice(&bytes).map_err(|error| format!("invalid config JSON: {error}"))?;
    validate_config(&config)?;
    Ok(config)
}

fn search_config_identity(config: &SelfPlayConfigV1) -> String {
    format!(
        "neural-ismcts-s{}-d{}-c{}-v1",
        config.simulations, config.max_depth_turns, config.puct_exploration_milli
    )
}

fn viewer_relative_value_target(actor: u8, ranks: &[u8]) -> Result<Vec<f64>, String> {
    if ranks.len() != 2 || actor > 1 {
        return Err("value target requires 1v1 ranks and actor 0/1".into());
    }
    let actor = actor as usize;
    let opponent = 1 - actor;
    Ok(vec![
        1.0 - f64::from(ranks[actor]),
        1.0 - f64::from(ranks[opponent]),
    ])
}

fn audit_dataset(
    dataset: &SelfPlayDatasetV2,
    config: &SelfPlayConfigV1,
    expected_collector_config_hash: &str,
    expected_search_identity: &str,
    dataset_file_sha256: String,
    config_file_sha256: String,
    diagnostics_id: String,
) -> Result<DiagnosticsReportV1, String> {
    if dataset.format != DATASET_FORMAT_V2 || dataset.version != DATASET_VERSION_V2 {
        return Err(format!(
            "unsupported dataset format/version: {} v{}",
            dataset.format, dataset.version
        ));
    }
    if dataset.self_play_id != config.self_play_id {
        return Err(format!(
            "dataset self_play_id `{}` does not match config `{}`",
            dataset.self_play_id, config.self_play_id
        ));
    }
    if dataset.base_checkpoint_hash != config.checkpoint_hash {
        return Err("dataset base_checkpoint_hash does not match config".into());
    }
    if dataset.collector_config_hash != expected_collector_config_hash {
        return Err("dataset collector_config_hash does not match config".into());
    }
    if dataset.search_config_identity != expected_search_identity {
        return Err("dataset search_config_identity does not match config".into());
    }
    if dataset.games.len() != config.game_seeds.len() {
        return Err("dataset game count does not match config game_seeds".into());
    }
    if dataset.games.len()
        != dataset
            .games
            .iter()
            .map(|g| g.game_seed)
            .collect::<HashSet<_>>()
            .len()
    {
        return Err("duplicate game seeds in dataset".into());
    }

    let mut plies = Vec::with_capacity(dataset.games.len());
    let mut legal_action_counts = Vec::with_capacity(dataset.examples.len());
    let mut legal_action_type_counts: BTreeMap<String, u64> = BTreeMap::new();
    let mut chosen_action_type_counts: BTreeMap<String, u64> = BTreeMap::new();
    let mut policy_entropies = Vec::with_capacity(dataset.examples.len());
    let mut visit_entropies = Vec::with_capacity(dataset.examples.len());
    let mut observation_hashes = HashSet::with_capacity(dataset.examples.len());
    let mut information_set_hashes = HashSet::with_capacity(dataset.examples.len());
    let mut value_target_counts: BTreeMap<String, u64> = BTreeMap::new();
    let mut winner_seat_counts: BTreeMap<String, u64> = BTreeMap::new();
    let mut cursor = 0usize;

    for (game_index, game) in dataset.games.iter().enumerate() {
        if game.game_index as usize != game_index {
            return Err(format!("game {game_index}: non-sequential game_index"));
        }
        let expected_seed = config
            .game_seeds
            .get(game_index)
            .copied()
            .ok_or_else(|| format!("game {game_index}: missing config seed"))?;
        if game.game_seed != expected_seed {
            return Err(format!(
                "game {game_index}: seed {} does not match config {}",
                game.game_seed, expected_seed
            ));
        }
        if game.base_checkpoint_hash != config.checkpoint_hash
            || game.collector_config_hash != expected_collector_config_hash
            || game.search_config_identity != expected_search_identity
        {
            return Err(format!("game {game_index}: source identity mismatch"));
        }
        if game.first_example_index as usize != cursor {
            return Err(format!("game {game_index}: first_example_index mismatch"));
        }
        if game.example_count != game.replay.steps.len() as u32 {
            return Err(format!(
                "game {game_index}: example_count does not match replay steps"
            ));
        }
        if cursor + game.example_count as usize > dataset.examples.len() {
            return Err(format!("game {game_index}: example range overruns dataset"));
        }

        let verified = verify_replay(&game.replay)
            .map_err(|error| format!("game {game_index}: replay verification failed: {error}"))?;
        if verified.steps != game.example_count
            || verified.final_state_hash != game.replay_final_state_hash
            || !game.replay.result.matches(&game.result)
        {
            return Err(format!(
                "game {game_index}: replay identity/result mismatch"
            ));
        }
        let document_hash = replay_document_hash_v1(&game.replay)
            .map_err(|error| format!("game {game_index}: {error}"))?;
        if document_hash != game.replay_document_hash {
            return Err(format!("game {game_index}: replay document hash mismatch"));
        }
        let trace = verify_replay_trace(&game.replay).map_err(|error| {
            format!("game {game_index}: replay trace verification failed: {error}")
        })?;
        if trace.positions.len() != game.example_count as usize {
            return Err(format!("game {game_index}: replay trace length mismatch"));
        }

        plies.push(f64::from(game.example_count));
        let winner_seat = game
            .result
            .winners
            .first()
            .map(|winner| winner.0)
            .ok_or_else(|| format!("game {game_index}: no winner"))?;
        let winner_key = if winner_seat == 0 {
            "seat_0".to_string()
        } else if winner_seat == 1 {
            "seat_1".to_string()
        } else {
            format!("seat_{winner_seat}")
        };
        *winner_seat_counts.entry(winner_key).or_insert(0) += 1;

        let end = cursor + game.example_count as usize;
        for example in &dataset.examples[cursor..end] {
            let position = trace.positions.get(example.ply as usize).ok_or_else(|| {
                format!(
                    "game {game_index}: example ply {} outside replay",
                    example.ply
                )
            })?;
            validate_example(
                game_index,
                game,
                position.ply,
                position.recorded_actor,
                position.recorded_action,
                &position.state,
                example,
            )?;
            *chosen_action_type_counts
                .entry(action_kind(&example.chosen_action)?)
                .or_insert(0) += 1;
            legal_action_counts.push(example.legal_actions.len() as f64);
            for action in &example.legal_actions {
                let kind = action_kind(action)?;
                *legal_action_type_counts.entry(kind).or_insert(0) += 1;
            }
            policy_entropies.push(entropy(&example.policy_target_visits)?);
            visit_entropies.push(visit_entropy(&example.action_stats)?);
            observation_hashes.insert(example.observation_hash.clone());
            information_set_hashes.insert(example.information_set_hash.clone());
            let value_key =
                serde_json::to_string(&example.value_target).map_err(|e| e.to_string())?;
            *value_target_counts.entry(value_key).or_insert(0) += 1;
        }
        cursor = end;
    }
    if cursor != dataset.examples.len() {
        return Err("dataset contains examples not covered by any game".into());
    }

    let dataset_compact = serde_json::to_vec(dataset).map_err(|error| error.to_string())?;
    let dataset_semantic_hash = hash_bytes(DATASET_HASH_DOMAIN_V2, &dataset_compact);
    let duplicate_game_seeds = 0u32;
    let games = dataset.games.len() as u32;
    let examples = dataset.examples.len() as u64;
    let total_obs = examples.max(1) as f64;
    Ok(DiagnosticsReportV1 {
        format: DIAGNOSTICS_FORMAT.into(),
        version: DIAGNOSTICS_VERSION,
        diagnostics_id,
        dataset_format: DATASET_FORMAT_V2.into(),
        dataset_version: DATASET_VERSION_V2,
        dataset_file_sha256,
        dataset_semantic_hash,
        config_file_sha256,
        collector_config_hash: expected_collector_config_hash.into(),
        base_checkpoint_hash: config.checkpoint_hash.clone(),
        search_config_identity: expected_search_identity.into(),
        games,
        examples,
        games_verified: games,
        duplicate_game_seeds,
        plies_per_game: summary_f64(&plies)?,
        legal_actions_per_decision: summary_f64(&legal_action_counts)?,
        legal_action_type_counts,
        chosen_action_type_counts,
        policy_entropy: summary_f64(&policy_entropies)?,
        visit_entropy: summary_f64(&visit_entropies)?,
        duplicate_observation_rate: 1.0 - (observation_hashes.len() as f64 / total_obs),
        duplicate_information_set_rate: 1.0 - (information_set_hashes.len() as f64 / total_obs),
        value_target_counts,
        winner_seat_counts,
    })
}

#[allow(clippy::too_many_arguments)]
fn validate_example(
    game_index: usize,
    game: &SelfPlayGameSourceV2,
    replay_ply: u32,
    replay_actor: PlayerId,
    replay_action: Action,
    state: &splendor_core::FullState,
    example: &SelfPlayExampleV2,
) -> Result<(), String> {
    if example.game_index as usize != game_index {
        return Err(format!("game {game_index}: example game_index mismatch"));
    }
    if example.ply != replay_ply {
        return Err(format!(
            "game {game_index}: example ply {} does not match replay {}",
            example.ply, replay_ply
        ));
    }
    if example.actor != replay_actor.0 {
        return Err(format!(
            "game {game_index} ply {}: actor mismatch",
            example.ply
        ));
    }
    if example.chosen_action != replay_action {
        return Err(format!(
            "game {game_index} ply {}: chosen action mismatch",
            example.ply
        ));
    }
    if example.final_scores != game.result.scores || example.final_ranks != game.result.ranks {
        return Err(format!(
            "game {game_index} ply {}: result target mismatch",
            example.ply
        ));
    }
    let observation = state.observation(replay_actor);
    if example.observation != observation {
        return Err(format!(
            "game {game_index} ply {}: observation mismatch",
            example.ply
        ));
    }
    if example.observation_hash != observation_hash(&observation).as_str() {
        return Err(format!(
            "game {game_index} ply {}: observation hash mismatch",
            example.ply
        ));
    }
    let history = visible_events(&state.log, Audience::Player(replay_actor));
    let ruleset = Ruleset::base_v1();
    let information_set = build_information_set_v1(ruleset, &observation, &history)
        .map_err(|error| error.to_string())?;
    if example.visible_history_hash != information_set.visible_history_hash().as_str() {
        return Err(format!(
            "game {game_index} ply {}: visible history hash mismatch",
            example.ply
        ));
    }
    if example.information_set_hash != information_set.information_set_hash().as_str() {
        return Err(format!(
            "game {game_index} ply {}: information set hash mismatch",
            example.ply
        ));
    }
    let legal_actions = canonical_order(&state.legal_actions());
    if example.legal_actions != legal_actions {
        return Err(format!(
            "game {game_index} ply {}: legal action mismatch",
            example.ply
        ));
    }
    validate_action_stats(game_index, example)?;
    let expected_value = viewer_relative_value_target(example.actor, &example.final_ranks)?;
    if example.value_target != expected_value {
        return Err(format!(
            "game {game_index} ply {}: value target mismatch",
            example.ply
        ));
    }
    Ok(())
}

fn validate_action_stats(game_index: usize, example: &SelfPlayExampleV2) -> Result<(), String> {
    if example.action_stats.len() != example.legal_actions.len() {
        return Err(format!(
            "game {game_index} ply {}: action_stats length mismatch",
            example.ply
        ));
    }
    let legal_set: HashSet<Action> = example.legal_actions.iter().copied().collect();
    let stats_actions: HashSet<Action> = example.action_stats.iter().map(|s| s.action).collect();
    if legal_set != stats_actions {
        return Err(format!(
            "game {game_index} ply {}: action_stats set mismatch",
            example.ply
        ));
    }
    for stats in &example.action_stats {
        if stats.prior_micros > 1_000_000 {
            return Err(format!(
                "game {game_index} ply {}: prior exceeds 1_000_000",
                example.ply
            ));
        }
        if stats.value_sum_by_player.len() != 2 {
            return Err(format!(
                "game {game_index} ply {}: value shape mismatch",
                example.ply
            ));
        }
    }
    let total_visits: u32 = example.action_stats.iter().map(|s| s.visits).sum();
    if total_visits == 0 {
        return Err(format!(
            "game {game_index} ply {}: zero root visits",
            example.ply
        ));
    }
    if example.policy_target_visits.len() != example.legal_actions.len() {
        return Err(format!(
            "game {game_index} ply {}: policy target length mismatch",
            example.ply
        ));
    }
    let visit_map: HashMap<Action, u32> = example
        .action_stats
        .iter()
        .map(|stats| (stats.action, stats.visits))
        .collect();
    for (action, visits) in example
        .legal_actions
        .iter()
        .zip(example.policy_target_visits.iter())
    {
        if visit_map.get(action).copied() != Some(*visits) {
            return Err(format!(
                "game {game_index} ply {}: policy target mismatch",
                example.ply
            ));
        }
    }
    Ok(())
}

fn entropy(visits: &[u32]) -> Result<f64, String> {
    let total: u32 = visits.iter().sum();
    if total == 0 {
        return Ok(0.0);
    }
    let mut entropy = 0.0f64;
    for &count in visits {
        if count == 0 {
            continue;
        }
        let p = f64::from(count) / f64::from(total);
        entropy -= p * p.ln();
    }
    Ok(entropy)
}

fn visit_entropy(stats: &[NeuralIsmctsActionStatsV1]) -> Result<f64, String> {
    let visits: Vec<u32> = stats.iter().map(|s| s.visits).collect();
    entropy(&visits)
}

fn summary_f64(values: &[f64]) -> Result<SummaryStatsV1, String> {
    if values.is_empty() {
        return Err("cannot summarize an empty metric set".into());
    }
    let mut sorted = values.to_vec();
    sorted.sort_by(|a, b| a.total_cmp(b));
    let count = sorted.len() as u64;
    let sum: f64 = sorted.iter().sum();
    let mean = sum / count as f64;
    Ok(SummaryStatsV1 {
        count,
        min: sorted[0],
        max: sorted[sorted.len() - 1],
        mean,
        p25: quantile(&sorted, 0.25),
        p50: quantile(&sorted, 0.50),
        p75: quantile(&sorted, 0.75),
    })
}

fn quantile(sorted: &[f64], q: f64) -> f64 {
    if sorted.len() == 1 {
        return sorted[0];
    }
    let pos = q * (sorted.len() - 1) as f64;
    let lo = pos.floor() as usize;
    let hi = pos.ceil() as usize;
    let weight = pos - lo as f64;
    sorted[lo] * (1.0 - weight) + sorted[hi] * weight
}

fn action_kind(action: &Action) -> Result<String, String> {
    let value = serde_json::to_value(action).map_err(|e| e.to_string())?;
    value
        .get("type")
        .and_then(|v| v.as_str())
        .map(str::to_string)
        .ok_or_else(|| "action has no type tag".to_string())
}

fn file_sha256(path: &Path) -> Result<String, String> {
    let bytes =
        fs::read(path).map_err(|error| format!("cannot read {}: {error}", path.display()))?;
    let mut digest = Sha256::new();
    digest.update(&bytes);
    Ok(hex::encode(digest.finalize()))
}

fn parse_collect_args(args: &[String]) -> Result<(PathBuf, PathBuf), String> {
    parse_two_path_args(args, COLLECT_USAGE, "--config", "--out")
}

fn parse_diagnose_args(args: &[String]) -> Result<(PathBuf, PathBuf, PathBuf), String> {
    let mut input = None;
    let mut config = None;
    let mut out = None;
    let mut index = 0;
    while index < args.len() {
        let target = match args[index].as_str() {
            "--input" => &mut input,
            "--config" => &mut config,
            "--out" => &mut out,
            other => return Err(format!("unknown argument `{other}`; {DIAGNOSE_USAGE}")),
        };
        if target.is_some() {
            return Err(format!("duplicate argument `{}`", args[index]));
        }
        *target = args.get(index + 1).cloned();
        index += 2;
    }
    Ok((
        PathBuf::from(input.ok_or_else(|| "missing --input".to_string())?),
        PathBuf::from(config.ok_or_else(|| "missing --config".to_string())?),
        PathBuf::from(out.ok_or_else(|| "missing --out".to_string())?),
    ))
}

fn parse_two_path_args(
    args: &[String],
    usage: &str,
    first: &str,
    second: &str,
) -> Result<(PathBuf, PathBuf), String> {
    let mut first_value = None;
    let mut second_value = None;
    let mut index = 0;
    while index < args.len() {
        let target = if args[index] == first {
            &mut first_value
        } else if args[index] == second {
            &mut second_value
        } else {
            return Err(format!("unknown argument `{}`; {usage}", args[index]));
        };
        if target.is_some() {
            return Err(format!("duplicate argument `{}`", args[index]));
        }
        *target = args.get(index + 1).cloned();
        index += 2;
    }
    Ok((
        PathBuf::from(first_value.ok_or_else(|| format!("missing {first}"))?),
        PathBuf::from(second_value.ok_or_else(|| format!("missing {second}"))?),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use splendor_replay::record_random_game;

    #[test]
    fn search_identity_matches_m22_convention() {
        let config = SelfPlayConfigV1 {
            format: "effective-splendor-neural-self-play-config".into(),
            version: 1,
            self_play_id: "test".into(),
            python: "python".into(),
            module_root: "training/m17_gpu".into(),
            checkpoint: "checkpoint.pt".into(),
            checkpoint_hash: "11".repeat(32),
            catalog: "catalog.json".into(),
            device: "cuda".into(),
            game_seeds: vec![1],
            action_seed: 1,
            search_seed: 2,
            simulations: 16,
            max_depth_turns: 1,
            puct_exploration_milli: 1_500,
            temperature_plies: 24,
            max_plies: 512,
        };
        assert_eq!(
            search_config_identity(&config),
            "neural-ismcts-s16-d1-c1500-v1"
        );
    }

    #[test]
    fn entropy_is_zero_for_delta_and_positive_for_mixed() {
        assert_eq!(entropy(&[1, 0, 0]).unwrap(), 0.0);
        let mixed = entropy(&[1, 1, 1, 1]).unwrap();
        assert!((mixed - 4.0f64.ln()).abs() < 1e-12);
    }

    #[test]
    fn summary_quantiles_are_sorted() {
        let stats = summary_f64(&[4.0, 1.0, 2.0, 3.0]).unwrap();
        assert_eq!(stats.min, 1.0);
        assert_eq!(stats.max, 4.0);
        assert_eq!(stats.p50, 2.5);
        assert_eq!(stats.p25, 1.75);
        assert_eq!(stats.p75, 3.25);
    }

    #[test]
    fn value_target_is_viewer_relative() {
        assert_eq!(
            viewer_relative_value_target(0, &[0, 1]).unwrap(),
            vec![1.0, 0.0]
        );
        assert_eq!(
            viewer_relative_value_target(1, &[0, 1]).unwrap(),
            vec![0.0, 1.0]
        );
    }

    #[test]
    fn audit_accepts_a_minimal_valid_v2_dataset_and_reports_metrics() {
        let checkpoint_hash = "11".repeat(32);
        let config = SelfPlayConfigV1 {
            format: "effective-splendor-neural-self-play-config".into(),
            version: 1,
            self_play_id: "unit-v2".into(),
            python: "python".into(),
            module_root: "training/m17_gpu".into(),
            checkpoint: "checkpoint.pt".into(),
            checkpoint_hash: checkpoint_hash.clone(),
            catalog: "catalog.json".into(),
            device: "cpu".into(),
            game_seeds: vec![42],
            action_seed: 1,
            search_seed: 2,
            simulations: 8,
            max_depth_turns: 1,
            puct_exploration_milli: 1_500,
            temperature_plies: 10,
            max_plies: 100,
        };
        let config_hash = hash_bytes(CONFIG_HASH_DOMAIN_V1, &serde_json::to_vec(&config).unwrap());
        let identity = search_config_identity(&config);
        let (terminal_state, replay) = record_random_game(2, 42, 1001).unwrap();
        verify_replay(&replay).unwrap();
        let trace = verify_replay_trace(&replay).unwrap();
        let result = terminal_state.result.clone().unwrap();
        let ruleset = Ruleset::base_v1();
        let mut examples = Vec::new();
        for position in &trace.positions {
            let actor = position.recorded_actor;
            let observation = position.state.observation(actor);
            let history = visible_events(&position.state.log, Audience::Player(actor));
            let information_set =
                build_information_set_v1(ruleset, &observation, &history).unwrap();
            let legal_actions = canonical_order(&position.state.legal_actions());
            let action_stats = legal_actions
                .iter()
                .map(|action| NeuralIsmctsActionStatsV1 {
                    action: *action,
                    prior_micros: 1_000_000 / legal_actions.len() as u32,
                    visits: 1,
                    value_sum_by_player: vec![0, 0],
                })
                .collect::<Vec<_>>();
            let policy_target_visits = legal_actions
                .iter()
                .map(|action| {
                    action_stats
                        .iter()
                        .find(|stats| stats.action == *action)
                        .map(|stats| stats.visits)
                        .unwrap()
                })
                .collect::<Vec<_>>();
            examples.push(SelfPlayExampleV2 {
                game_index: 0,
                ply: position.ply,
                actor: actor.0,
                observation_hash: observation_hash(&observation).as_str().to_string(),
                visible_history_hash: information_set.visible_history_hash().as_str().to_string(),
                information_set_hash: information_set.information_set_hash().as_str().to_string(),
                observation,
                legal_actions,
                action_stats,
                chosen_action: position.recorded_action,
                final_scores: result.scores.clone(),
                final_ranks: result.ranks.clone(),
                policy_target_visits,
                value_target: viewer_relative_value_target(actor.0, &result.ranks).unwrap(),
            });
        }
        let game = SelfPlayGameSourceV2 {
            game_index: 0,
            game_seed: 42,
            base_checkpoint_hash: checkpoint_hash.clone(),
            collector_config_hash: config_hash.clone(),
            search_config_identity: identity.clone(),
            replay_document_hash: replay_document_hash_v1(&replay).unwrap(),
            replay_final_state_hash: replay.final_state_hash.as_str().to_string(),
            replay,
            result: result.clone(),
            first_example_index: 0,
            example_count: examples.len() as u32,
        };
        let dataset = SelfPlayDatasetV2 {
            format: DATASET_FORMAT_V2.into(),
            version: DATASET_VERSION_V2,
            self_play_id: "unit-v2".into(),
            engine_version: ENGINE_VERSION.into(),
            ruleset: ruleset.id.0.into(),
            ruleset_fingerprint: ruleset_fingerprint(&ruleset).to_string(),
            base_checkpoint_hash: checkpoint_hash,
            collector_config_hash: config_hash.clone(),
            search_config_identity: identity.clone(),
            games: vec![game],
            examples,
        };
        let report = audit_dataset(
            &dataset,
            &config,
            &config_hash,
            &identity,
            "d".repeat(64),
            "c".repeat(64),
            "unit-v2-diagnostics-v1".into(),
        )
        .unwrap();
        assert_eq!(report.games, 1);
        assert_eq!(report.plies_per_game.count, 1);
        assert_eq!(report.examples, report.plies_per_game.max as u64);
        assert_eq!(report.games_verified, 1);
        assert_eq!(report.duplicate_game_seeds, 0);
        assert!(report.policy_entropy.count > 0);
    }
}
