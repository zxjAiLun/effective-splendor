//! End-to-end process tests for `splendor analyze-replay-player-view`.
//!
//! The fixture replay is created with the replay crate, while the command is
//! always exercised through the real `splendor` binary. The assertions rebuild
//! the visible prefix independently from the replay verifier so a successful
//! artifact cannot be explained by accidentally reusing the referee log.

use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::atomic::{AtomicU64, Ordering};

use serde_json::Value;
use splendor_core::{
    full_state_hash, observation_hash, visible_events, Action, Audience, FullState, GameConfig,
    PlayerId, Ruleset, Tier, VisibleEvent,
};
use splendor_imperfect_search::{analyze_player_view_v1, RootDeterminizationConfigV1};
use splendor_replay::{
    record_random_game, replay_document_hash_v1, verify_replay_position, ReplayRecorder, ReplayV1,
};
use splendor_search::SearchConfigV1;

const ANALYSIS_FORMAT: &str = "effective-splendor-imperfect-search-analysis";
const ANALYSIS_VERSION: u64 = 1;
const MAX_REPLAY_BYTES: usize = 16 * 1024 * 1024;

static TMP_SEQ: AtomicU64 = AtomicU64::new(0);

fn bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_splendor"))
}

fn tmp_dir(label: &str) -> PathBuf {
    let n = TMP_SEQ.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!(
        "splendor-imperfect-search-cli-{}-{label}-{n}",
        std::process::id()
    ));
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn write_replay(path: &Path, replay: &ReplayV1) {
    let mut json = serde_json::to_string_pretty(replay).unwrap();
    json.push('\n');
    std::fs::write(path, json).unwrap();
}

fn record_replay(path: &Path, players: u8, seed: u64, action_seed: u64) -> ReplayV1 {
    let (_, replay) = record_random_game(players, seed, action_seed).unwrap();
    write_replay(path, &replay);
    replay
}

fn finish_blind_prefix_replay(path: &Path) -> ReplayV1 {
    let mut recorder = ReplayRecorder::new(GameConfig {
        player_count: 2,
        seed: 7331,
        ruleset: Ruleset::base_v1(),
    })
    .unwrap();

    recorder
        .apply(Action::ReserveDeck {
            tier: Tier::One,
            give_back: splendor_core::Gems::ZERO,
        })
        .unwrap();
    recorder
        .apply(Action::ReserveDeck {
            tier: Tier::One,
            give_back: splendor_core::Gems::ZERO,
        })
        .unwrap();

    let mut rng_state = 0xC4C4_C4C4_1234_5678u64;
    let mut next = || {
        let mut x = rng_state;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        rng_state = x;
        x.wrapping_mul(0x2545_F491_4F6C_DD1D)
    };

    let mut guard = 0u32;
    while !recorder.is_terminal() {
        assert!(guard < 10_000, "blind-prefix fixture did not terminate");
        let actions = recorder.legal_actions();
        let action = actions[(next() % actions.len() as u64) as usize];
        recorder.apply(action).unwrap();
        guard += 1;
    }

    let (_, replay) = recorder.finish().unwrap();
    write_replay(path, &replay);
    replay
}

fn run_player_view(
    input: &Path,
    ply: u32,
    sample_seed: u64,
    sample_count: u16,
    max_depth_turns: u8,
    max_nodes: u64,
    out: &Path,
) -> Output {
    let args = player_view_args(
        input,
        ply,
        sample_seed,
        sample_count,
        max_depth_turns,
        max_nodes,
        out,
    );
    Command::new(bin())
        .args(args)
        .output()
        .expect("spawn analyze-replay-player-view")
}

fn player_view_args(
    input: &Path,
    ply: u32,
    sample_seed: u64,
    sample_count: u16,
    max_depth_turns: u8,
    max_nodes: u64,
    out: &Path,
) -> Vec<String> {
    vec![
        "analyze-replay-player-view".to_string(),
        "--input".to_string(),
        input.display().to_string(),
        "--ply".to_string(),
        ply.to_string(),
        "--sample-seed".to_string(),
        sample_seed.to_string(),
        "--sample-count".to_string(),
        sample_count.to_string(),
        "--max-depth-turns".to_string(),
        max_depth_turns.to_string(),
        "--max-nodes".to_string(),
        max_nodes.to_string(),
        "--out".to_string(),
        out.display().to_string(),
    ]
}

fn run_args(args: &[String]) -> Output {
    Command::new(bin())
        .args(args)
        .output()
        .expect("spawn splendor")
}

fn assert_failure_streams(output: &Output, label: &str) {
    assert!(
        output.stdout.is_empty(),
        "{label}: stdout must be empty, got {:?}",
        String::from_utf8_lossy(&output.stdout)
    );
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert_eq!(
        stderr.lines().count(),
        1,
        "{label}: stderr must contain exactly one line, got {stderr:?}"
    );
    assert!(
        stderr.starts_with("error: "),
        "{label}: stderr must start with `error: `, got {stderr:?}"
    );
    assert!(
        stderr.ends_with('\n'),
        "{label}: stderr must be LF-terminated, got {stderr:?}"
    );
}

fn assert_success(output: &Output, label: &str) {
    assert_eq!(
        output.status.code(),
        Some(0),
        "{label}: expected exit 0, got {output:?}"
    );
    assert!(output.stdout.is_empty(), "{label}: stdout must be empty");
    assert!(output.stderr.is_empty(), "{label}: stderr must be empty");
}

/// Rebuild setup plus steps `[0, ply)` from the replay, projecting every
/// `StepResult.events` independently. This intentionally never reads
/// `FullState::log` or the verifier's captured state.
fn rebuild_visible_prefix(
    replay: &ReplayV1,
    ply: u32,
    viewer: PlayerId,
) -> (FullState, Vec<VisibleEvent>) {
    let (mut state, setup) = FullState::new(GameConfig {
        player_count: replay.player_count,
        seed: replay.seed,
        ruleset: Ruleset::base_v1(),
    })
    .unwrap();
    assert_eq!(
        full_state_hash(&state).as_str(),
        replay.initial_state_hash.as_str()
    );

    let audience = Audience::Player(viewer);
    let mut visible_history = visible_events(&setup.events, audience);
    for step in replay.steps.iter().take(ply as usize) {
        assert_eq!(state.current_player, step.actor);
        assert_eq!(
            full_state_hash(&state).as_str(),
            step.state_hash_before.as_str()
        );
        let step_result = state.apply(step.action).unwrap();
        state.assert_invariants().unwrap();
        assert_eq!(
            full_state_hash(&state).as_str(),
            step.state_hash_after.as_str()
        );
        visible_history.extend(visible_events(&step_result.events, audience));
    }

    (state, visible_history)
}

fn config(
    sample_seed: u64,
    sample_count: u16,
    depth: u8,
    nodes: u64,
) -> RootDeterminizationConfigV1 {
    RootDeterminizationConfigV1 {
        sample_seed,
        sample_count,
        continuation_search: SearchConfigV1 {
            max_depth_turns: depth,
            max_nodes: nodes,
        },
    }
}

/// Check the published artifact against an independently reconstructed
/// information set and a direct replay-neutral C3 call.
fn assert_bound_artifact(
    replay: &ReplayV1,
    ply: u32,
    sample_seed: u64,
    sample_count: u16,
    depth: u8,
    nodes: u64,
    out: &Path,
) -> Value {
    let raw = std::fs::read_to_string(out).unwrap();
    assert!(raw.ends_with('\n'));
    assert!(!raw.ends_with("\n\n"));
    assert!(raw.starts_with("{\n"));
    let artifact: Value = serde_json::from_str(&raw).unwrap();

    assert_eq!(artifact["format"], ANALYSIS_FORMAT);
    assert_eq!(artifact["version"], ANALYSIS_VERSION);
    assert_eq!(artifact["config"]["sample_seed"], sample_seed);
    assert_eq!(artifact["config"]["sample_count"], sample_count);
    assert_eq!(
        artifact["config"]["continuation_search"]["max_depth_turns"],
        depth
    );
    assert_eq!(
        artifact["config"]["continuation_search"]["max_nodes"],
        nodes
    );

    let position = verify_replay_position(replay, ply).unwrap();
    let viewer = position.recorded_actor;
    let (reconstructed_state, visible_history) = rebuild_visible_prefix(replay, ply, viewer);
    assert_eq!(reconstructed_state.current_player, viewer);
    assert_eq!(
        full_state_hash(&reconstructed_state).as_str(),
        replay.steps[ply as usize].state_hash_before.as_str()
    );
    assert_eq!(
        full_state_hash(&reconstructed_state).as_str(),
        position.state_hash.as_str()
    );
    let observation = reconstructed_state.observation(viewer);
    assert_eq!(observation.viewer, viewer);

    let direct = analyze_player_view_v1(
        Ruleset::base_v1(),
        &observation,
        &visible_history,
        config(sample_seed, sample_count, depth, nodes),
    )
    .unwrap();
    let step = &replay.steps[ply as usize];
    let source = &artifact["source"];
    assert_eq!(
        source["replay_document_hash"],
        replay_document_hash_v1(replay).unwrap()
    );
    assert_eq!(
        source["replay_final_state_hash"],
        replay.final_state_hash.as_str()
    );
    assert_eq!(source["replay_version"], replay.version);
    assert_eq!(
        source["ruleset_fingerprint"],
        replay.ruleset_fingerprint.as_str()
    );
    assert_eq!(source["analyzed_ply"], ply);
    assert_eq!(
        source["analyzed_state_hash"],
        step.state_hash_before.as_str()
    );
    assert_eq!(source["viewer"], viewer.0);
    assert_eq!(source["recorded_actor"], step.actor.0);
    assert_eq!(
        source["recorded_action"],
        serde_json::to_value(step.action).unwrap()
    );
    assert_eq!(
        source["observation_hash"],
        observation_hash(&observation).as_str()
    );
    assert_eq!(source["visible_event_count"], visible_history.len());
    assert_eq!(
        source["visible_history_hash"],
        direct.visible_history_hash().as_str()
    );
    assert_eq!(
        source["information_set_hash"],
        direct.information_set_hash().as_str()
    );

    assert_eq!(
        artifact["result"],
        serde_json::to_value(direct.result()).unwrap()
    );
    assert_eq!(
        artifact["result"]["root_player"], viewer.0,
        "result root must be the recorded actor"
    );
    assert!(reconstructed_state
        .legal_actions()
        .contains(&direct.result().action));
    assert!(direct
        .result()
        .action_aggregates
        .iter()
        .any(|aggregate| aggregate.action == direct.result().action));
    assert_eq!(
        artifact["recommended_matches_recorded"],
        direct.result().action == step.action
    );

    assert_no_forbidden_exact_keys(&artifact);

    // A non-terminal target step must not be included in the visible prefix.
    // The target always emits at least ActionApplied, so the independent
    // prefix after the target has strictly more projected events.
    if (ply as usize) + 1 < replay.steps.len() {
        let (_, after_history) = rebuild_visible_prefix(replay, ply + 1, viewer);
        assert!(after_history.len() > visible_history.len());
        assert_ne!(after_history, visible_history);
    }

    artifact
}

fn assert_no_forbidden_exact_keys(value: &Value) {
    const FORBIDDEN: &[&str] = &[
        "seed",
        "state",
        "deck",
        "blind",
        "principal_variation",
        "visible_history",
        "sample_index",
        "sample_state_hash",
        "sample_utility",
    ];
    match value {
        Value::Object(object) => {
            for (key, child) in object {
                assert!(!FORBIDDEN.contains(&key.as_str()), "forbidden key: {key}");
                assert_no_forbidden_exact_keys(child);
            }
        }
        Value::Array(array) => {
            for child in array {
                assert_no_forbidden_exact_keys(child);
            }
        }
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => {}
    }
}

fn assert_fatal_for_tampered_value(dir: &Path, replay_value: &Value, label: &str, ply: u32) {
    let input = dir.join(format!("{label}.json"));
    std::fs::write(&input, serde_json::to_string_pretty(replay_value).unwrap()).unwrap();
    let out_path = dir.join(format!("{label}-analysis.json"));
    let output = run_player_view(&input, ply, 7, 1, 1, 1, &out_path);
    assert_eq!(output.status.code(), Some(1), "{label}: {output:?}");
    assert_failure_streams(&output, label);
    assert!(!out_path.exists(), "{label}: no artifact may be published");
}

#[test]
fn two_three_four_player_positions_and_nonzero_viewers_are_bound() {
    let dir = tmp_dir("player-counts");
    for (players, seed, action_seed, ply) in [(2, 42, 1001, 0), (3, 12, 1201, 1), (4, 99, 9901, 1)]
    {
        let input = dir.join(format!("{players}p-replay.json"));
        let replay = record_replay(&input, players, seed, action_seed);
        let out = dir.join(format!("{players}p-analysis.json"));
        let process = run_player_view(&input, ply, 1234, 1, 1, 1, &out);
        assert_success(&process, &format!("{players}p"));
        let artifact = assert_bound_artifact(&replay, ply, 1234, 1, 1, 1, &out);
        assert_eq!(
            artifact["source"]["viewer"],
            if players == 2 { 0 } else { 1 }
        );
        if players > 2 {
            assert_eq!(artifact["source"]["viewer"], 1, "nonzero viewer required");
        }
    }
}

#[test]
fn blind_prefix_exposes_own_card_but_redacts_opponent_card() {
    let dir = tmp_dir("blind-prefix");
    let input = dir.join("replay.json");
    let replay = finish_blind_prefix_replay(&input);
    let out = dir.join("analysis.json");
    let process = run_player_view(&input, 2, 77, 1, 1, 1, &out);
    assert_success(&process, "blind prefix");
    let artifact = assert_bound_artifact(&replay, 2, 77, 1, 1, 1, &out);

    let (_, history) = rebuild_visible_prefix(&replay, 2, PlayerId(0));
    assert!(history.iter().any(|event| {
        matches!(
            event,
            VisibleEvent::CardReserved {
                card: Some(_),
                from: _,
                ..
            }
        )
    }));
    assert!(history.iter().any(|event| {
        matches!(
            event,
            VisibleEvent::CardReserved {
                card: None,
                from: _,
                ..
            }
        )
    }));
    assert_eq!(artifact["source"]["viewer"], 0);
}

#[test]
fn choose_noble_and_terminal_producing_positions_are_supported() {
    let dir = tmp_dir("special-positions");
    let choose_input = dir.join("choose-replay.json");
    let choose_replay = record_replay(&choose_input, 2, 12, 1012);
    let choose_ply = choose_replay
        .steps
        .iter()
        .position(|step| matches!(step.action, Action::ChooseNoble { .. }))
        .expect("frozen random fixture must contain ChooseNoble") as u32;
    let choose_out = dir.join("choose-analysis.json");
    let choose_process = run_player_view(&choose_input, choose_ply, 9, 1, 1, 1, &choose_out);
    assert_success(&choose_process, "ChooseNoble position");
    let choose_artifact =
        assert_bound_artifact(&choose_replay, choose_ply, 9, 1, 1, 1, &choose_out);
    assert!(choose_artifact["result"]["action"]["type"] == "choose_noble");

    let terminal_input = dir.join("terminal-replay.json");
    let terminal_replay = record_replay(&terminal_input, 2, 42, 1001);
    let terminal_ply = terminal_replay.steps.len() as u32 - 1;
    let terminal_out = dir.join("terminal-analysis.json");
    let terminal_process =
        run_player_view(&terminal_input, terminal_ply, 10, 1, 1, 1, &terminal_out);
    assert_success(&terminal_process, "terminal-producing position");
    assert_bound_artifact(&terminal_replay, terminal_ply, 10, 1, 1, 1, &terminal_out);
}

#[test]
fn same_input_config_is_byte_identical_and_output_is_no_overwrite() {
    let dir = tmp_dir("output");
    let input = dir.join("replay.json");
    let replay = record_replay(&input, 2, 42, 1001);
    let first = dir.join("first.json");
    let second = dir.join("second.json");

    let first_process = run_player_view(&input, 0, 55, 1, 1, 1, &first);
    let second_process = run_player_view(&input, 0, 55, 1, 1, 1, &second);
    assert_success(&first_process, "first deterministic output");
    assert_success(&second_process, "second deterministic output");
    assert_eq!(
        std::fs::read(&first).unwrap(),
        std::fs::read(&second).unwrap(),
        "identical input/config must produce byte-identical artifacts"
    );
    assert_bound_artifact(&replay, 0, 55, 1, 1, 1, &first);

    let sentinel = dir.join("sentinel.json");
    std::fs::write(&sentinel, "SENTINEL\n").unwrap();
    let process = run_player_view(&input, 0, 55, 1, 1, 1, &sentinel);
    assert_eq!(process.status.code(), Some(1));
    assert_failure_streams(&process, "existing output");
    assert_eq!(std::fs::read_to_string(&sentinel).unwrap(), "SENTINEL\n");
    assert!(
        std::fs::read_dir(&dir)
            .unwrap()
            .map(|entry| entry.unwrap().file_name().to_string_lossy().into_owned())
            .all(|name| !name.ends_with(".tmp")),
        "failed publish must not leave temp residue"
    );
}

#[test]
fn full_suffix_prefix_and_target_action_tampering_are_rejected() {
    let dir = tmp_dir("tamper");
    let input = dir.join("replay.json");
    let replay = record_replay(&input, 2, 42, 1001);
    let original: Value = serde_json::from_str(&std::fs::read_to_string(&input).unwrap()).unwrap();

    let mut suffix = original.clone();
    let steps = suffix["steps"].as_array_mut().unwrap();
    let last = steps.len() - 1;
    steps[last]["state_hash_after"] = Value::String("0".repeat(64));
    assert_fatal_for_tampered_value(&dir, &suffix, "suffix-tamper", 0);

    let mut prefix = original.clone();
    prefix["steps"][0]["state_hash_before"] = Value::String("0".repeat(64));
    assert_fatal_for_tampered_value(&dir, &prefix, "prefix-tamper", 1);

    let mut action = original;
    action["steps"][0]["action"] = serde_json::json!({"type": "pass"});
    assert_fatal_for_tampered_value(&dir, &action, "action-tamper", 0);

    assert!(!replay.steps.is_empty());
}

#[test]
fn invalid_trailing_and_oversize_replays_fail_without_output() {
    let dir = tmp_dir("replay-input-errors");
    let invalid = dir.join("invalid.json");
    std::fs::write(&invalid, "{").unwrap();
    let invalid_out = dir.join("invalid-out.json");
    let invalid_process = run_player_view(&invalid, 0, 1, 1, 1, 1, &invalid_out);
    assert_eq!(invalid_process.status.code(), Some(1));
    assert_failure_streams(&invalid_process, "invalid JSON");
    assert!(!invalid_out.exists());

    let replay_input = dir.join("valid.json");
    record_replay(&replay_input, 2, 42, 1001);
    let trailing = dir.join("trailing.json");
    let mut trailing_bytes = std::fs::read(&replay_input).unwrap();
    trailing_bytes.extend_from_slice(b"x");
    std::fs::write(&trailing, trailing_bytes).unwrap();
    let trailing_out = dir.join("trailing-out.json");
    let trailing_process = run_player_view(&trailing, 0, 1, 1, 1, 1, &trailing_out);
    assert_eq!(trailing_process.status.code(), Some(1));
    assert_failure_streams(&trailing_process, "trailing JSON");
    assert!(!trailing_out.exists());

    let oversize = dir.join("oversize.json");
    std::fs::write(&oversize, vec![b'x'; MAX_REPLAY_BYTES + 1]).unwrap();
    let oversize_out = dir.join("oversize-out.json");
    let oversize_process = run_player_view(&oversize, 0, 1, 1, 1, 1, &oversize_out);
    assert_eq!(oversize_process.status.code(), Some(1));
    assert_failure_streams(&oversize_process, "oversize replay");
    assert!(!oversize_out.exists());
}

#[test]
fn runtime_limits_are_fatal_and_argv_grammar_is_usage_error() {
    let dir = tmp_dir("argv");
    let input = dir.join("replay.json");
    record_replay(&input, 2, 42, 1001);

    for (label, sample_count, depth, nodes) in [
        ("sample-count-zero", 0, 1, 1),
        ("sample-count-high", 65, 1, 1),
        ("depth-zero", 1, 0, 1),
        ("depth-high", 1, 13, 1),
        ("nodes-zero", 1, 1, 0),
        ("nodes-high", 1, 1, 10_000_001),
    ] {
        let out = dir.join(format!("{label}.json"));
        let process = run_player_view(&input, 0, 1, sample_count, depth, nodes, &out);
        assert_eq!(process.status.code(), Some(1), "{label}: {process:?}");
        assert_failure_streams(&process, label);
        assert!(!out.exists(), "{label}: no output");
    }

    let valid = player_view_args(&input, 0, 1, 1, 1, 1, &dir.join("unused.json"));
    let grammar_cases: Vec<(&str, Vec<String>)> = vec![
        (
            "help",
            vec![
                "analyze-replay-player-view".to_string(),
                "--help".to_string(),
            ],
        ),
        (
            "short-help",
            vec!["analyze-replay-player-view".to_string(), "-h".to_string()],
        ),
        (
            "missing",
            vec![
                "analyze-replay-player-view".to_string(),
                "--input".to_string(),
            ],
        ),
        ("duplicate", {
            let mut args = valid.clone();
            args.extend(["--input".to_string(), "second.json".to_string()]);
            args
        }),
        ("unknown", {
            let mut args = valid.clone();
            args.extend(["--unknown".to_string(), "value".to_string()]);
            args
        }),
        ("non-numeric", {
            let mut args = valid.clone();
            let ply_index = args.iter().position(|arg| arg == "--ply").unwrap() + 1;
            args[ply_index] = "not-a-number".to_string();
            args
        }),
        ("equals-form", {
            let mut args = valid.clone();
            let input_index = args.iter().position(|arg| arg == "--input").unwrap();
            args[input_index] = format!("--input={}", input.display());
            args.remove(input_index + 1);
            args
        }),
        ("positional", {
            let mut args = valid.clone();
            args.push("extra".to_string());
            args
        }),
    ];

    for (label, args) in grammar_cases {
        let process = run_args(&args);
        assert_eq!(process.status.code(), Some(2), "{label}: {process:?}");
        assert_failure_streams(&process, label);
    }
}
