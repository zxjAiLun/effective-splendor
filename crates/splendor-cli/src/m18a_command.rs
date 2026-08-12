use std::fs;
use std::path::PathBuf;

use rand::rngs::SmallRng;
use rand::{Rng, SeedableRng};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use splendor_belief::build_information_set_v1;
use splendor_core::{
    ruleset_fingerprint, visible_events, Action, Audience, FullState, GameConfig, GameResult,
    Observation, Ruleset, ENGINE_VERSION,
};
use splendor_neural_agent::{GpuInferenceConfigV1, GpuPolicyValueEvaluatorV1};
use splendor_neural_search::{
    search_neural_ismcts_with_evaluator_v1, NeuralIsmctsActionStatsV1, NeuralIsmctsConfigV1,
};
use splendor_search::canonical_order;

use crate::atomic_output;

const USAGE: &str =
    "Usage: splendor collect-gpu-self-play --config <config.json> --out <dataset.json>";
const HASH_DOMAIN: &[u8] = b"effective-splendor-neural-self-play-v1\0";

#[derive(Debug, Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct SelfPlayConfigV1 {
    format: String,
    version: u32,
    self_play_id: String,
    python: PathBuf,
    module_root: PathBuf,
    checkpoint: PathBuf,
    checkpoint_hash: String,
    catalog: PathBuf,
    device: String,
    game_seeds: Vec<u64>,
    action_seed: u64,
    search_seed: u64,
    simulations: u32,
    max_depth_turns: u8,
    puct_exploration_milli: u32,
    temperature_plies: u32,
    max_plies: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct SelfPlayExampleV1 {
    game_index: u32,
    ply: u32,
    actor: u8,
    observation: Observation,
    legal_actions: Vec<Action>,
    action_stats: Vec<NeuralIsmctsActionStatsV1>,
    chosen_action: Action,
    final_ranks: Vec<u8>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct SelfPlayGameV1 {
    game_index: u32,
    seed: u64,
    plies: u32,
    result: GameResult,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct SelfPlayDatasetV1 {
    format: String,
    version: u32,
    self_play_id: String,
    engine_version: String,
    ruleset: String,
    ruleset_fingerprint: String,
    checkpoint_hash: String,
    config_hash: String,
    games: Vec<SelfPlayGameV1>,
    examples: Vec<SelfPlayExampleV1>,
}

pub fn run_collect_gpu_self_play(args: &[String]) -> i32 {
    if args == ["--help"] || args == ["-h"] {
        println!("{USAGE}");
        return 0;
    }
    match collect(args) {
        Ok((path, hash, games, examples)) => {
            println!(
                "{{\"status\":\"ok\",\"out\":{},\"self_play_hash\":\"{}\",\"games\":{},\"examples\":{}}}",
                serde_json::to_string(&path.display().to_string()).unwrap(),
                hash,
                games,
                examples
            );
            0
        }
        Err(error) => {
            eprintln!("error: {error}");
            1
        }
    }
}

fn collect(args: &[String]) -> Result<(PathBuf, String, usize, usize), String> {
    let (config_path, out_path) = parse_args(args)?;
    let bytes = fs::read(&config_path)
        .map_err(|error| format!("cannot read config {}: {error}", config_path.display()))?;
    let config: SelfPlayConfigV1 =
        serde_json::from_slice(&bytes).map_err(|error| format!("invalid config JSON: {error}"))?;
    validate_config(&config)?;
    if out_path.exists() {
        return Err(format!("output already exists: {}", out_path.display()));
    }
    let config_hash = hash_bytes(b"effective-splendor-self-play-config-v1\0", &bytes);
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
    let mut games = Vec::with_capacity(config.game_seeds.len());
    let mut examples = Vec::new();

    for (game_index, &seed) in config.game_seeds.iter().enumerate() {
        let game_index_u32 = u32::try_from(game_index).map_err(|_| "too many games")?;
        let (mut state, _) = FullState::new(GameConfig {
            player_count: 2,
            seed,
            ruleset,
        })
        .map_err(|error| error.to_string())?;
        let start = examples.len();
        let mut ply = 0u32;
        while !state.is_terminal() {
            if ply >= config.max_plies {
                return Err(format!("game {game_index} exceeded max_plies"));
            }
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
            let result = search_neural_ismcts_with_evaluator_v1(
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
                sample_visits(&result.action_stats, &mut action_rng)?
            } else {
                result.action
            };
            if !legal_actions.contains(&chosen_action) {
                return Err("search selected an illegal action".into());
            }
            examples.push(SelfPlayExampleV1 {
                game_index: game_index_u32,
                ply,
                actor: actor.0,
                observation,
                legal_actions,
                action_stats: result.action_stats,
                chosen_action,
                final_ranks: Vec::new(),
            });
            state
                .apply(chosen_action)
                .map_err(|error| error.to_string())?;
            ply += 1;
        }
        let result = state
            .result
            .clone()
            .ok_or_else(|| "terminal game has no result".to_string())?;
        for example in &mut examples[start..] {
            example.final_ranks.clone_from(&result.ranks);
        }
        games.push(SelfPlayGameV1 {
            game_index: game_index_u32,
            seed,
            plies: ply,
            result,
        });
    }

    let dataset = SelfPlayDatasetV1 {
        format: "effective-splendor-neural-self-play".into(),
        version: 1,
        self_play_id: config.self_play_id,
        engine_version: ENGINE_VERSION.into(),
        ruleset: ruleset.id.0.into(),
        ruleset_fingerprint: ruleset_fingerprint(&ruleset).to_string(),
        checkpoint_hash: config.checkpoint_hash,
        config_hash,
        games,
        examples,
    };
    let output = serde_json::to_string_pretty(&dataset).map_err(|error| error.to_string())?;
    let hash = hash_bytes(HASH_DOMAIN, &serde_json::to_vec(&dataset).unwrap());
    if let Some(parent) = out_path.parent() {
        fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let temp = atomic_output::write_temp(&out_path, &output).map_err(|error| error.to_string())?;
    atomic_output::publish_new(&temp, &out_path).map_err(|error| error.to_string())?;
    Ok((out_path, hash, dataset.games.len(), dataset.examples.len()))
}

fn sample_visits(
    stats: &[NeuralIsmctsActionStatsV1],
    rng: &mut SmallRng,
) -> Result<Action, String> {
    let total: u64 = stats.iter().map(|stats| u64::from(stats.visits)).sum();
    if total == 0 {
        return stats
            .first()
            .map(|stats| stats.action)
            .ok_or_else(|| "search returned no root actions".into());
    }
    let mut needle = rng.gen_range(0..total);
    for stats in stats {
        if needle < u64::from(stats.visits) {
            return Ok(stats.action);
        }
        needle -= u64::from(stats.visits);
    }
    Err("visit sampling arithmetic failed".into())
}

fn parse_args(args: &[String]) -> Result<(PathBuf, PathBuf), String> {
    let mut config = None;
    let mut out = None;
    let mut index = 0;
    while index < args.len() {
        let target = match args[index].as_str() {
            "--config" => &mut config,
            "--out" => &mut out,
            other => return Err(format!("unknown argument `{other}`; {USAGE}")),
        };
        if target.is_some() {
            return Err(format!("duplicate argument `{}`", args[index]));
        }
        *target = args.get(index + 1).cloned();
        index += 2;
    }
    Ok((
        PathBuf::from(config.ok_or_else(|| "missing --config".to_string())?),
        PathBuf::from(out.ok_or_else(|| "missing --out".to_string())?),
    ))
}

fn validate_config(config: &SelfPlayConfigV1) -> Result<(), String> {
    if config.format != "effective-splendor-neural-self-play-config" || config.version != 1 {
        return Err("unsupported self-play config format/version".into());
    }
    if config.game_seeds.is_empty() || config.game_seeds.len() > 10_000 {
        return Err("game_seeds must contain 1..=10000 entries".into());
    }
    if config
        .game_seeds
        .iter()
        .collect::<std::collections::HashSet<_>>()
        .len()
        != config.game_seeds.len()
    {
        return Err("game_seeds must be unique".into());
    }
    if config.max_plies == 0 || config.max_plies > 10_000 {
        return Err("max_plies must be within 1..=10000".into());
    }
    NeuralIsmctsConfigV1 {
        sample_seed: config.search_seed,
        simulations: config.simulations,
        max_depth_turns: config.max_depth_turns,
        puct_exploration_milli: config.puct_exploration_milli,
        expected_checkpoint_hash: config.checkpoint_hash.clone(),
    }
    .validate()
    .map_err(|error| error.to_string())
}

fn hash_bytes(domain: &[u8], bytes: &[u8]) -> String {
    let mut digest = Sha256::new();
    digest.update(domain);
    digest.update(bytes);
    hex::encode(digest.finalize())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn action() -> Action {
        Action::Pass
    }

    #[test]
    fn visit_sampling_never_returns_a_zero_visit_edge() {
        let stats = vec![
            NeuralIsmctsActionStatsV1 {
                action: action(),
                prior_micros: 500_000,
                visits: 0,
                value_sum_by_player: vec![0, 0],
            },
            NeuralIsmctsActionStatsV1 {
                action: Action::ChooseNoble {
                    noble: splendor_core::NobleId(0),
                },
                prior_micros: 500_000,
                visits: 4,
                value_sum_by_player: vec![2_000_000, 2_000_000],
            },
        ];
        let mut rng = SmallRng::seed_from_u64(1);
        for _ in 0..32 {
            assert_eq!(sample_visits(&stats, &mut rng).unwrap(), stats[1].action);
        }
    }

    #[test]
    fn duplicate_game_seeds_fail_closed() {
        let config = SelfPlayConfigV1 {
            format: "effective-splendor-neural-self-play-config".into(),
            version: 1,
            self_play_id: "test".into(),
            python: "python".into(),
            module_root: ".".into(),
            checkpoint: "checkpoint.pt".into(),
            checkpoint_hash: "11".repeat(32),
            catalog: "catalog.json".into(),
            device: "cpu".into(),
            game_seeds: vec![7, 7],
            action_seed: 1,
            search_seed: 2,
            simulations: 8,
            max_depth_turns: 1,
            puct_exploration_milli: 1_500,
            temperature_plies: 10,
            max_plies: 100,
        };
        assert!(validate_config(&config).unwrap_err().contains("unique"));
    }
}
