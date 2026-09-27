//! M50: Replay dataset extractor for competitive 2-player Policy-Value learning.
//!
//! Reconstructs verified match replays (such as `s4-heuristic-v025-pilot`)
//! ply-by-ply using `verify_replay_trace`, extracting for each decision:
//! - 2-player viewer observation (368 features via `encode_observation_v1`)
//! - candidate legal action features (36 features each via `encode_action_v1`)
//! - chosen action index among legal actions
//! - actor game outcome (won {0, 1, 0.5}, score difference)
//!
//! Outputs memory-mappable binary tensors partitioned into train / val splits.

use std::fs::{self, File};
use std::io::{BufWriter, Read, Write};
use std::path::{Path, PathBuf};
use std::time::Instant;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
// splendor_core types used via splendor_replay / splendor_learning
use splendor_learning::{
    encode_action_v1, encode_observation_v1, ACTION_FEATURES_V1, OBSERVATION_FEATURES_V1,
};
use splendor_replay::{verify_replay_trace, ReplayV1};

const USAGE: &str = "\
Usage: splendor m50-extract-replays --replays-dir <dir> --out-dir <dir> [--val-modulus <N>] [--val-remainder <R>]

Extract 2-player policy-value training dataset from verified match replays.
Options:
  --replays-dir    Directory containing match-replay.json files (searched recursively)
  --manifest       (Optional) Path to pilot/league manifest.json
  --out-dir        Output directory for exported tensors
  --val-modulus    Validation seed modulus (default: 5, i.e. 20% val)
  --val-remainder  Validation seed remainder (default: 0)
";

#[derive(Debug, Clone)]
struct Args {
    replays_dirs: Vec<PathBuf>,
    out_dir: PathBuf,
    val_modulus: u64,
    val_remainder: u64,
    winner_only: bool,
    top_fastest_percent: Option<f64>,
}

#[derive(Debug, Default)]
struct SplitBuffer {
    step_count: usize,
    game_count: usize,
    total_actions: usize,
    obs_bytes: Vec<u8>,
    action_bytes: Vec<u8>,
    action_offsets: Vec<u64>,
    chosen_action_indices: Vec<u32>,
    values_bytes: Vec<u8>,
    wins: usize,
    losses: usize,
    ties: usize,
}

impl SplitBuffer {
    fn new() -> Self {
        let mut buf = Self::default();
        buf.action_offsets.push(0);
        buf
    }

    fn add_step(
        &mut self,
        obs_feat: &[f32],
        legal_feats: &[Vec<f32>],
        chosen_idx: usize,
        won: f32,
        score_diff: f32,
        steps_to_15: f32,
    ) {
        assert_eq!(obs_feat.len(), OBSERVATION_FEATURES_V1);
        for &v in obs_feat {
            self.obs_bytes.extend_from_slice(&v.to_le_bytes());
        }

        for act_feat in legal_feats {
            assert_eq!(act_feat.len(), ACTION_FEATURES_V1);
            for &v in act_feat {
                self.action_bytes.extend_from_slice(&v.to_le_bytes());
            }
        }

        self.total_actions += legal_feats.len();
        self.action_offsets.push(self.total_actions as u64);
        self.chosen_action_indices.push(chosen_idx as u32);

        self.values_bytes.extend_from_slice(&won.to_le_bytes());
        self.values_bytes
            .extend_from_slice(&score_diff.to_le_bytes());
        self.values_bytes
            .extend_from_slice(&steps_to_15.to_le_bytes());

        if won > 0.75 {
            self.wins += 1;
        } else if won < 0.25 {
            self.losses += 1;
        } else {
            self.ties += 1;
        }

        self.step_count += 1;
    }

    fn write_to_dir(&self, dir: &Path) -> Result<SplitMeta, String> {
        fs::create_dir_all(dir).map_err(|e| format!("create dir {}: {e}", dir.display()))?;

        let obs_path = dir.join("obs.f32");
        let act_path = dir.join("actions.f32");
        let offsets_path = dir.join("action_offsets.u64");
        let chosen_path = dir.join("chosen_action.u32");
        let values_path = dir.join("values.f32");

        write_bytes(&obs_path, &self.obs_bytes)?;
        write_bytes(&act_path, &self.action_bytes)?;

        let mut offsets_raw = Vec::with_capacity(self.action_offsets.len() * 8);
        for &off in &self.action_offsets {
            offsets_raw.extend_from_slice(&off.to_le_bytes());
        }
        write_bytes(&offsets_path, &offsets_raw)?;

        let mut chosen_raw = Vec::with_capacity(self.chosen_action_indices.len() * 4);
        for &idx in &self.chosen_action_indices {
            chosen_raw.extend_from_slice(&idx.to_le_bytes());
        }
        write_bytes(&chosen_path, &chosen_raw)?;

        write_bytes(&values_path, &self.values_bytes)?;

        Ok(SplitMeta {
            game_count: self.game_count,
            step_count: self.step_count,
            total_actions: self.total_actions,
            mean_actions_per_step: if self.step_count > 0 {
                self.total_actions as f64 / self.step_count as f64
            } else {
                0.0
            },
            wins: self.wins,
            losses: self.losses,
            ties: self.ties,
            obs_sha256: sha256_file(&obs_path)?,
            actions_sha256: sha256_file(&act_path)?,
            action_offsets_sha256: sha256_file(&offsets_path)?,
            chosen_action_sha256: sha256_file(&chosen_path)?,
            values_sha256: sha256_file(&values_path)?,
        })
    }
}

#[derive(Debug, Serialize, Deserialize)]
pub struct SplitMeta {
    pub game_count: usize,
    pub step_count: usize,
    pub total_actions: usize,
    pub mean_actions_per_step: f64,
    pub wins: usize,
    pub losses: usize,
    pub ties: usize,
    pub obs_sha256: String,
    pub actions_sha256: String,
    pub action_offsets_sha256: String,
    pub chosen_action_sha256: String,
    pub values_sha256: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct DatasetManifest {
    pub format: String,
    pub version: u32,
    pub source_replays_dir: String,
    pub val_modulus: u64,
    pub val_remainder: u64,
    pub observation_width: usize,
    pub action_width: usize,
    pub total_replays_parsed: usize,
    pub total_steps: usize,
    pub splits: SplitsMeta,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct SplitsMeta {
    pub train: SplitMeta,
    pub val: SplitMeta,
}

fn write_bytes(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let mut f =
        BufWriter::new(File::create(path).map_err(|e| format!("create {}: {e}", path.display()))?);
    f.write_all(bytes)
        .map_err(|e| format!("write {}: {e}", path.display()))?;
    f.flush()
        .map_err(|e| format!("flush {}: {e}", path.display()))
}

fn sha256_file(path: &Path) -> Result<String, String> {
    let mut hasher = Sha256::new();
    let file = File::open(path).map_err(|e| format!("open {}: {e}", path.display()))?;
    let mut reader = std::io::BufReader::new(file);
    let mut buffer = vec![0u8; 1 << 20];
    loop {
        let read = reader
            .read(&mut buffer)
            .map_err(|e| format!("read {}: {e}", path.display()))?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(hex::encode(hasher.finalize()))
}

fn collect_replays_recursive(dir: &Path, list: &mut Vec<PathBuf>) {
    if let Ok(entries) = fs::read_dir(dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                collect_replays_recursive(&path, list);
            } else if let Some(name) = path.file_name().and_then(|n| n.to_str()) {
                if name == "match-replay.json"
                    || (name.ends_with(".replay.json") && !name.ends_with(".meta.json"))
                {
                    list.push(path);
                }
            }
        }
    }
}

fn parse_args(args: &[String]) -> Result<Args, String> {
    let mut replays_dirs = Vec::new();
    let mut out_dir = None;
    let mut val_modulus = 5u64;
    let mut val_remainder = 0u64;
    let mut winner_only = false;
    let mut top_fastest_percent = None;

    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--replays-dir" => {
                if let Some(dir) = args.get(i + 1) {
                    replays_dirs.push(PathBuf::from(dir));
                }
                i += 2;
            }
            "--manifest" => {
                // optional manifest argument accepted for compatibility
                i += 2;
            }
            "--out-dir" => {
                out_dir = args.get(i + 1).map(PathBuf::from);
                i += 2;
            }
            "--val-modulus" => {
                let val = args.get(i + 1).ok_or("missing --val-modulus value")?;
                val_modulus = val
                    .parse()
                    .map_err(|e| format!("invalid --val-modulus: {e}"))?;
                i += 2;
            }
            "--val-remainder" => {
                let val = args.get(i + 1).ok_or("missing --val-remainder value")?;
                val_remainder = val
                    .parse()
                    .map_err(|e| format!("invalid --val-remainder: {e}"))?;
                i += 2;
            }
            "--winner-only" => {
                winner_only = true;
                i += 1;
            }
            "--top-fastest-percent" => {
                let val = args
                    .get(i + 1)
                    .ok_or("missing --top-fastest-percent value")?;
                let pct: f64 = val
                    .parse()
                    .map_err(|e| format!("invalid --top-fastest-percent: {e}"))?;
                top_fastest_percent = Some(pct);
                i += 2;
            }
            other => return Err(format!("unknown option `{other}`")),
        }
    }

    if replays_dirs.is_empty() {
        return Err("missing required --replays-dir (specify one or more)".into());
    }

    Ok(Args {
        replays_dirs,
        out_dir: out_dir.ok_or("missing --out-dir")?,
        val_modulus,
        val_remainder,
        winner_only,
        top_fastest_percent,
    })
}

fn run(args: Args) -> Result<(), String> {
    let t0 = Instant::now();
    println!(
        "M50 Replay Extractor: scanning {} root directories",
        args.replays_dirs.len()
    );

    let mut replay_paths = Vec::new();
    for d in &args.replays_dirs {
        println!("  - scanning {}", d.display());
        collect_replays_recursive(d, &mut replay_paths);
    }
    replay_paths.sort();
    replay_paths.dedup();
    println!(
        "Found {} unique match-replay.json files",
        replay_paths.len()
    );

    if replay_paths.is_empty() {
        return Err("no match-replay.json files found".into());
    }

    let mut train_buf = SplitBuffer::new();
    let mut val_buf = SplitBuffer::new();

    let mut total_parsed = 0;
    let mut total_failed = 0;

    // Optional pre-pass to compute plies threshold if top_fastest_percent is set
    let plies_threshold = if let Some(pct) = args.top_fastest_percent {
        println!("Computing {pct}% fastest plies threshold across all replays...");
        let mut all_plies = Vec::with_capacity(replay_paths.len());
        for path in &replay_paths {
            if let Ok(c) = fs::read(path) {
                if let Ok(r) = serde_json::from_slice::<ReplayV1>(&c) {
                    if r.player_count == 2 {
                        all_plies.push(r.steps.len());
                    }
                }
            }
        }
        all_plies.sort_unstable();
        if all_plies.is_empty() {
            None
        } else {
            let idx = ((all_plies.len() as f64) * (pct / 100.0)).floor() as usize;
            let thresh = all_plies[idx.min(all_plies.len() - 1)];
            println!(
                "  Threshold for fastest {pct}%: <= {thresh} plies (evaluated {} games)",
                all_plies.len()
            );
            Some(thresh)
        }
    } else {
        None
    };

    for (idx, path) in replay_paths.iter().enumerate() {
        if idx % 100 == 0 && idx > 0 {
            println!(
                "Processed {}/{} replays (train_steps={}, val_steps={})...",
                idx,
                replay_paths.len(),
                train_buf.step_count,
                val_buf.step_count
            );
        }

        let content = match fs::read(path) {
            Ok(c) => c,
            Err(e) => {
                eprintln!("Warning: failed to read {}: {e}", path.display());
                total_failed += 1;
                continue;
            }
        };

        let replay: ReplayV1 = match serde_json::from_slice(&content) {
            Ok(r) => r,
            Err(e) => {
                eprintln!("Warning: failed to parse {}: {e}", path.display());
                total_failed += 1;
                continue;
            }
        };

        if replay.player_count != 2 {
            continue;
        }

        // Apply fastest threshold filter if requested
        if let Some(thresh) = plies_threshold {
            if replay.steps.len() > thresh {
                continue;
            }
        }

        let trace = match verify_replay_trace(&replay) {
            Ok(t) => t,
            Err(e) => {
                eprintln!(
                    "Warning: replay verification failed for {}: {e}",
                    path.display()
                );
                total_failed += 1;
                continue;
            }
        };

        // Determine split by seed
        let seed = replay.seed;
        let is_val = (seed % args.val_modulus) == args.val_remainder;
        let buf = if is_val { &mut val_buf } else { &mut train_buf };
        buf.game_count += 1;

        let result = &replay.result;
        assert!(
            result.scores.len() >= 2,
            "2-player replay must have >= 2 scores"
        );

        // Precompute the final/target turn for each seat where they reached >= 15 VP (or game end turn)
        let mut seat_turn_reached_15 = [None, None];
        let mut current_turn_count = [0u32, 0u32];
        for step in &trace.positions {
            let seat = step.recorded_actor.index();
            current_turn_count[seat] += 1;
            let p_prestige = step.state.players[seat].prestige;
            if p_prestige >= 15 && seat_turn_reached_15[seat].is_none() {
                seat_turn_reached_15[seat] = Some(current_turn_count[seat]);
            }
        }
        let seat_total_turns = current_turn_count;

        let mut actor_turn_cursor = [0u32, 0u32];

        for step in &trace.positions {
            let actor = step.recorded_actor;
            let actor_seat = actor.index();
            actor_turn_cursor[actor_seat] += 1;
            let current_turn = actor_turn_cursor[actor_seat];

            // If winner_only is enabled, skip steps made by losing/tied players
            if args.winner_only {
                let actor_won =
                    result.winners.len() == 1 && result.winners.contains(&(actor_seat as u8));
                if !actor_won {
                    continue;
                }
            }

            let obs = step.state.observation(actor);
            let legal = step.state.legal_actions();

            if legal.is_empty() {
                continue;
            }

            // Find chosen action index
            let chosen_idx = match legal.iter().position(|a| a == &step.recorded_action) {
                Some(idx) => idx,
                None => {
                    eprintln!(
                        "Warning: recorded action {:?} not in legal actions at ply {} in {}",
                        step.recorded_action,
                        step.ply,
                        path.display()
                    );
                    continue;
                }
            };

            let obs_feat = match encode_observation_v1(&obs) {
                Ok(f) => f,
                Err(e) => {
                    eprintln!("Warning: encode_observation failed: {e}");
                    continue;
                }
            };

            let legal_feats: Result<Vec<Vec<f32>>, _> =
                legal.iter().map(encode_action_v1).collect();
            let legal_feats = match legal_feats {
                Ok(lf) => lf,
                Err(e) => {
                    eprintln!("Warning: encode_action failed: {e}");
                    continue;
                }
            };

            let actor_seat_u8 = actor_seat as u8;
            let won = if result.winners.contains(&actor_seat_u8) {
                if result.winners.len() == 1 {
                    1.0f32
                } else {
                    0.5f32
                }
            } else {
                0.0f32
            };

            let opp_seat = 1 - actor_seat;
            let actor_score = result.scores[actor_seat] as f32;
            let opp_score = result.scores.get(opp_seat).copied().unwrap_or(0) as f32;
            let score_diff = (actor_score - opp_score) / 10.0f32;

            // Calculate exact remaining main turns to reach 15 (or game end + penalty if never reached 15)
            let steps_to_15 = match seat_turn_reached_15[actor_seat] {
                Some(target_turn) => {
                    if target_turn >= current_turn {
                        (target_turn - current_turn) as f32
                    } else {
                        0.0f32
                    }
                }
                None => {
                    let rem_turns = seat_total_turns[actor_seat].saturating_sub(current_turn) as f32;
                    let vp_deficit = (15.0 - actor_score).max(1.0);
                    rem_turns + vp_deficit * 2.0
                }
            };

            buf.add_step(&obs_feat, &legal_feats, chosen_idx, won, score_diff, steps_to_15);
        }

        total_parsed += 1;
    }

    println!(
        "Parsing complete in {:.2}s. Total parsed: {}, failed: {}",
        t0.elapsed().as_secs_f64(),
        total_parsed,
        total_failed
    );
    println!(
        "Train: {} games, {} steps, {} actions (wins={}, losses={}, ties={})",
        train_buf.game_count,
        train_buf.step_count,
        train_buf.total_actions,
        train_buf.wins,
        train_buf.losses,
        train_buf.ties
    );
    println!(
        "Val:   {} games, {} steps, {} actions (wins={}, losses={}, ties={})",
        val_buf.game_count,
        val_buf.step_count,
        val_buf.total_actions,
        val_buf.wins,
        val_buf.losses,
        val_buf.ties
    );

    let train_meta = train_buf.write_to_dir(&args.out_dir.join("train"))?;
    let val_meta = val_buf.write_to_dir(&args.out_dir.join("val"))?;

    let manifest = DatasetManifest {
        format: "m50-competitive-replay-dataset-v1".to_string(),
        version: 1,
        source_replays_dir: format!("{:?}", args.replays_dirs),
        val_modulus: args.val_modulus,
        val_remainder: args.val_remainder,
        observation_width: OBSERVATION_FEATURES_V1,
        action_width: ACTION_FEATURES_V1,
        total_replays_parsed: total_parsed,
        total_steps: train_meta.step_count + val_meta.step_count,
        splits: SplitsMeta {
            train: train_meta,
            val: val_meta,
        },
    };

    let manifest_path = args.out_dir.join("manifest.json");
    let manifest_json =
        serde_json::to_string_pretty(&manifest).map_err(|e| format!("serialize manifest: {e}"))?;
    fs::write(&manifest_path, manifest_json).map_err(|e| format!("write manifest: {e}"))?;

    println!(
        "Exported dataset successfully to {}. Manifest written.",
        args.out_dir.display()
    );
    Ok(())
}

pub fn run_m50_extract_replays(args: &[String]) -> i32 {
    let parsed = match parse_args(args) {
        Ok(a) => a,
        Err(e) => {
            eprintln!("usage error: {e}\n{USAGE}");
            return 2;
        }
    };

    let handle = std::thread::Builder::new()
        .stack_size(128 * 1024 * 1024)
        .spawn(move || run(parsed));

    let joined = match handle {
        Ok(h) => h.join(),
        Err(e) => {
            eprintln!("error: failed to spawn worker thread: {e}");
            return 1;
        }
    };

    match joined {
        Ok(Ok(())) => 0,
        Ok(Err(e)) => {
            eprintln!("error: {e}");
            1
        }
        Err(panic) => {
            eprintln!("error: thread panicked: {panic:?}");
            1
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_args_valid_and_defaults() {
        let args = vec![
            "--replays-dir".to_string(),
            "some/path".to_string(),
            "--out-dir".to_string(),
            "out/path".to_string(),
        ];
        let parsed = parse_args(&args).expect("valid args");
        assert_eq!(parsed.replays_dirs, vec![PathBuf::from("some/path")]);
        assert_eq!(parsed.out_dir, PathBuf::from("out/path"));
        assert_eq!(parsed.val_modulus, 5);
        assert_eq!(parsed.val_remainder, 0);
    }

    #[test]
    fn test_parse_args_missing_required() {
        let args = vec!["--replays-dir".to_string(), "some/path".to_string()];
        assert!(parse_args(&args).is_err());
    }

    #[test]
    fn test_parse_args_custom_val_split() {
        let args = vec![
            "--replays-dir".to_string(),
            "dir".to_string(),
            "--out-dir".to_string(),
            "out".to_string(),
            "--val-modulus".to_string(),
            "10".to_string(),
            "--val-remainder".to_string(),
            "3".to_string(),
        ];
        let parsed = parse_args(&args).expect("valid args");
        assert_eq!(parsed.val_modulus, 10);
        assert_eq!(parsed.val_remainder, 3);
    }
}
