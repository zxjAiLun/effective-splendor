//! M43A: Successor state reconstruction and decision-time successor sampling.

use std::io::{self, BufRead, BufReader, Write};
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use serde_json::Value;
use splendor_belief::{build_information_set_v1, sample_determinization_v1};
use splendor_core::{
    full_state_hash, observation_hash, Action, GameConfig, Observation, PlayerId, Ruleset,
};
use splendor_replay::{verify_replay, ReplayRecorder, ReplayV1};

const M07_SAMPLE_SEED: u64 = 20_260_703;
const M07_SAMPLE_COUNT: u16 = 4;

// ===========================================================================
// export-branch-successors
// ===========================================================================

pub fn run_export_successors(args: &[String]) -> i32 {
    let mut state_dir: Option<String> = None;
    let mut source_replay: Option<String> = None;
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--state-dir" => {
                state_dir = args.get(i + 1).cloned();
                i += 2;
            }
            "--source-replay" => {
                source_replay = args.get(i + 1).cloned();
                i += 2;
            }
            other => {
                eprintln!("error: unknown flag `{other}`");
                return 2;
            }
        }
    }

    let state_dir = match state_dir {
        Some(d) => PathBuf::from(d),
        None => {
            eprintln!("error: missing required flag `--state-dir`");
            return 2;
        }
    };
    let source_replay = match source_replay {
        Some(r) => PathBuf::from(r),
        None => {
            // Default to ../replay.json relative to state_dir
            state_dir.parent().unwrap().join("replay.json")
        }
    };

    match export_state_successors_inner(&state_dir, &source_replay) {
        Ok(json_str) => {
            println!("{json_str}");
            0
        }
        Err(e) => {
            eprintln!("error: {e}");
            1
        }
    }
}

fn export_state_successors_inner(state_dir: &Path, source_replay_path: &Path) -> Result<String, String> {
    let probe_file = state_dir.join("state-probe.json");
    let manifest_file = state_dir.join("state-manifest.json");

    if !probe_file.is_file() {
        return Err(format!("missing state-probe.json in {}", state_dir.display()));
    }
    if !manifest_file.is_file() {
        return Err(format!("missing state-manifest.json in {}", state_dir.display()));
    }

    let probe_val: Value = serde_json::from_str(
        &std::fs::read_to_string(&probe_file).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    let manifest_val: Value = serde_json::from_str(
        &std::fs::read_to_string(&manifest_file).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;

    let branch_ply = probe_val["branch_ply"]
        .as_u64()
        .ok_or_else(|| "missing branch_ply".to_string())? as u32;
    let root_actor = probe_val["acting_seat"]
        .as_u64()
        .ok_or_else(|| "missing acting_seat".to_string())? as u8;
    let expected_state_hash = probe_val["state_hash"]
        .as_str()
        .ok_or_else(|| "missing state_hash".to_string())?;
    let expected_obs_hash = probe_val["observation_hash"]
        .as_str()
        .ok_or_else(|| "missing observation_hash".to_string())?;

    // 1. Rebuild source state from source replay prefix
    let source_text = std::fs::read_to_string(source_replay_path)
        .map_err(|e| format!("cannot read source replay: {e}"))?;
    let source_replay: ReplayV1 =
        serde_json::from_str(&source_text).map_err(|e| format!("parse source replay: {e}"))?;
    verify_replay(&source_replay).map_err(|e| format!("source replay verification failed: {e}"))?;

    let (mut rec, _) = ReplayRecorder::new_with_setup(GameConfig {
        player_count: source_replay.player_count,
        seed: source_replay.seed,
        ruleset: Ruleset::base_v1(),
    })
    .map_err(|e| format!("rebuild setup failed: {e}"))?;

    for step in &source_replay.steps[..branch_ply as usize] {
        rec.apply(step.action).map_err(|e| format!("replay step failed: {e}"))?;
    }
    let source_state = rec.state();
    let rebuilt_state_hash = full_state_hash(source_state);
    if rebuilt_state_hash.as_str() != expected_state_hash {
        return Err(format!(
            "H0 error: rebuilt state hash {} != expected {}",
            rebuilt_state_hash.as_str(),
            expected_state_hash
        ));
    }

    let source_obs = source_state.observation(PlayerId(root_actor));
    let rebuilt_obs_hash = observation_hash(&source_obs);
    if rebuilt_obs_hash.as_str() != expected_obs_hash {
        return Err(format!(
            "H0 error: rebuilt obs hash {} != expected {}",
            rebuilt_obs_hash.as_str(),
            expected_obs_hash
        ));
    }

    // 2. Iterate over actions from state-manifest
    let actions_val = manifest_val["actions"]
        .as_array()
        .ok_or_else(|| "missing actions array".to_string())?;

    let mut successors = Vec::with_capacity(actions_val.len());

    for item in actions_val {
        let action_index = item["action_index"]
            .as_u64()
            .ok_or_else(|| "missing action_index".to_string())? as usize;
        let forced_action_val = &item["forced_action"];
        let forced_action: Action = serde_json::from_value(forced_action_val.clone())
            .map_err(|e| format!("parse forced_action: {e}"))?;
        let _expected_post_hash = item["final_state_hash"].as_str();

        // One-action reconstruction: s' = T(s, a)
        let mut child_state = source_state.clone();
        child_state
            .apply(forced_action)
            .map_err(|e| format!("action {action_index} apply failed: {e}"))?;

        let post_hash = full_state_hash(&child_state);

        // H1 check: check post-action state hash against branch replay if branch replay is present
        let action_dir = state_dir.join(format!("action-{action_index:03}"));
        let branch_replay_path = action_dir.join("replay.json");
        let branch_report_path = action_dir.join("report.json");

        if branch_replay_path.is_file() {
            let br_text = std::fs::read_to_string(&branch_replay_path)
                .map_err(|e| format!("cannot read branch replay {action_index}: {e}"))?;
            let br_replay: ReplayV1 = serde_json::from_str(&br_text)
                .map_err(|e| format!("parse branch replay {action_index}: {e}"))?;
            let step_after = &br_replay.steps[branch_ply as usize];
            if post_hash.as_str() != step_after.state_hash_after.as_str() {
                return Err(format!(
                    "H1 error: action {action_index} post_hash {} != branch replay {}",
                    post_hash.as_str(),
                    step_after.state_hash_after.as_str()
                ));
            }
        }

        // H2: Player-view observation from root_actor perspective
        let post_obs = child_state.observation(PlayerId(root_actor));
        let post_obs_hash = observation_hash(&post_obs);

        // Target y from terminal result
        let target_y = if branch_report_path.is_file() {
            let rep_text = std::fs::read_to_string(&branch_report_path)
                .map_err(|e| format!("cannot read branch report {action_index}: {e}"))?;
            let rep_val: Value = serde_json::from_str(&rep_text)
                .map_err(|e| format!("parse branch report {action_index}: {e}"))?;
            let outcome = &rep_val["outcome"];
            if outcome["status"] != "completed" {
                return Err(format!(
                    "Branch report {action_index} is not completed: {:?}",
                    outcome["status"]
                ));
            }
            let ranks = outcome["result"]["ranks"]
                .as_array()
                .ok_or_else(|| "missing ranks".to_string())?;
            let root_rank = ranks[root_actor as usize]
                .as_u64()
                .ok_or_else(|| "missing root rank".to_string())? as u8;
            if root_rank == 0 {
                1.0f32
            } else {
                0.0f32
            }
        } else {
            // Fallback to acting_seat_return from manifest
            let return_val = item["acting_seat_return"]
                .as_f64()
                .ok_or_else(|| "missing acting_seat_return".to_string())?;
            // centered return: +1.0 = win (rank 0), 0.0 = draw (shared rank 0), -1.0 = loss (rank > 0)
            if return_val >= 0.0 {
                1.0f32
            } else {
                0.0f32
            }
        };

        successors.push(serde_json::json!({
            "action_index": action_index,
            "forced_action": forced_action,
            "post_action_state_hash": post_hash.as_str(),
            "post_action_observation": post_obs,
            "post_action_observation_hash": post_obs_hash.as_str(),
            "target_y": target_y,
        }));
    }

    let out = serde_json::json!({
        "branch_ply": branch_ply,
        "root_actor": root_actor,
        "source_state_hash": expected_state_hash,
        "source_observation_hash": expected_obs_hash,
        "successors": successors,
    });
    serde_json::to_string(&out).map_err(|e| e.to_string())
}

// ===========================================================================
// sample-successors (Decision-time 4-determinization sampling)
// ===========================================================================

#[derive(Debug, Deserialize)]
struct SampleSuccessorsRequest {
    observation: Observation,
    visible_history: Vec<splendor_core::VisibleEvent>,
    legal_actions: Vec<Action>,
}

#[derive(Debug, Serialize)]
struct SuccessorSampleEntry {
    action_index: usize,
    sample_index: u16,
    is_terminal: bool,
    terminal_value: Option<f32>,
    observation: Option<Observation>,
}

pub fn run_sample_successors(_args: &[String]) -> i32 {
    let stdin = io::stdin();
    let mut reader = BufReader::new(stdin.lock());
    let mut line = String::new();

    loop {
        line.clear();
        match reader.read_line(&mut line) {
            Ok(0) => break, // EOF
            Ok(_) => {
                let trimmed = line.trim();
                if trimmed.is_empty() {
                    continue;
                }
                match sample_successors_line(trimmed) {
                    Ok(resp) => {
                        println!("{resp}");
                        let _ = io::stdout().flush();
                    }
                    Err(e) => {
                        eprintln!("error: {e}");
                        let _ = io::stderr().flush();
                        return 1;
                    }
                }
            }
            Err(e) => {
                eprintln!("error reading stdin: {e}");
                return 1;
            }
        }
    }
    0
}

fn sample_successors_line(json_line: &str) -> Result<String, String> {
    let req: SampleSuccessorsRequest = serde_json::from_str(json_line)
        .map_err(|e| format!("parse SampleSuccessorsRequest: {e}"))?;

    let ruleset = Ruleset::base_v1();
    let viewer = req.observation.viewer;

    // 1. Build information set
    let info_set = build_information_set_v1(ruleset, &req.observation, &req.visible_history)
        .map_err(|e| format!("build_information_set_v1 failed: {e}"))?;

    let mut entries = Vec::with_capacity(M07_SAMPLE_COUNT as usize * req.legal_actions.len());

    // 2. Sample 4 determinizations
    for k in 0..M07_SAMPLE_COUNT {
        let det = sample_determinization_v1(&info_set, M07_SAMPLE_SEED, k as u64)
            .map_err(|e| format!("sample_determinization_v1 failed for k={k}: {e}"))?;
        let base_state = det.state();

        // 3. For each legal action, apply and observe from viewer's perspective
        for (action_index, &action) in req.legal_actions.iter().enumerate() {
            let mut s_prime = base_state.clone();
            s_prime
                .apply(action)
                .map_err(|e| format!("apply action {action:?} failed: {e}"))?;

            if s_prime.is_terminal() {
                let ranks = &s_prime
                    .result
                    .as_ref()
                    .ok_or_else(|| "terminal without result".to_string())?
                    .ranks;
                let viewer_rank = ranks[viewer.0 as usize];
                let terminal_value = if viewer_rank == 0 { 1.0f32 } else { 0.0f32 };
                entries.push(SuccessorSampleEntry {
                    action_index,
                    sample_index: k,
                    is_terminal: true,
                    terminal_value: Some(terminal_value),
                    observation: None,
                });
            } else {
                let obs_prime = s_prime.observation(viewer);
                entries.push(SuccessorSampleEntry {
                    action_index,
                    sample_index: k,
                    is_terminal: false,
                    terminal_value: None,
                    observation: Some(obs_prime),
                });
            }
        }
    }

    let resp = serde_json::json!({
        "successors": entries,
    });
    serde_json::to_string(&resp).map_err(|e| e.to_string())
}
