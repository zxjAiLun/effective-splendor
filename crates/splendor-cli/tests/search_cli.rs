//! End-to-end CLI tests for `splendor analyze-replay`.
//!
//! These run the real `splendor` binary as a subprocess, generating input
//! replays with the binary's own `record-replay` command so the whole
//! pipeline — record, verify, position rebuild, search, atomic publish — is
//! exercised exactly as a user would drive it.
//!
//! The frozen CLI contract asserted here:
//! - success → exit 0, stdout empty, stderr empty, artifact published;
//! - argv grammar error → exit 2;
//! - every other failure (invalid search config included) → exit 1;
//! - on any failure stdout is empty, stderr is exactly one `error: ...` line,
//!   and no artifact exists.
//!
//! Run single-threaded: `cargo test -p splendor-cli --test search_cli -- --test-threads=1`.

use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::atomic::{AtomicU64, Ordering};

use splendor_core::Phase;
use splendor_replay::{replay_document_hash_v1, verify_replay_position, ReplayV1};
use splendor_search::{
    SearchAnalysisV1, SEARCH_ALGORITHM_ID, SEARCH_ANALYSIS_FORMAT, SEARCH_ANALYSIS_VERSION,
    SEARCH_VERSION,
};

static TMP_SEQ: AtomicU64 = AtomicU64::new(0);

/// The path to the built `splendor` binary under test.
fn bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_splendor"))
}

/// A unique temp directory for one test run.
fn tmp_dir(label: &str) -> PathBuf {
    let n = TMP_SEQ.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!(
        "splendor-search-cli-{}-{}-{}",
        std::process::id(),
        label,
        n
    ));
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

/// Record a deterministic replay into `dir` and return its path.
fn record_replay(dir: &Path) -> PathBuf {
    let path = dir.join("replay.json");
    let out = Command::new(bin())
        .args(["record-replay", "--players", "2", "--seed", "42"])
        .args(["--action-seed", "1001", "--out"])
        .arg(&path)
        .output()
        .expect("spawn record-replay");
    assert!(out.status.success(), "record-replay failed: {out:?}");
    path
}

/// Run `splendor analyze-replay` with the standard five flags.
fn run_analyze(input: &Path, ply: u32, depth: u32, nodes: u64, out_path: &Path) -> Output {
    Command::new(bin())
        .arg("analyze-replay")
        .arg("--input")
        .arg(input)
        .args(["--ply", &ply.to_string()])
        .args(["--max-depth-turns", &depth.to_string()])
        .args(["--max-nodes", &nodes.to_string()])
        .arg("--out")
        .arg(out_path)
        .output()
        .expect("spawn analyze-replay")
}

/// Run `analyze-replay` with raw argument tokens (for usage-error tests).
fn run_raw(args: &[&str]) -> Output {
    Command::new(bin())
        .arg("analyze-replay")
        .args(args)
        .output()
        .expect("spawn analyze-replay")
}

/// Every failure path shares one observable shape: silent stdout and exactly
/// one `error: ...` line on stderr.
fn assert_failure_streams(out: &Output, context: &str) {
    assert!(
        out.stdout.is_empty(),
        "{context}: stdout must be empty on failure, got {:?}",
        String::from_utf8_lossy(&out.stdout)
    );
    let stderr = String::from_utf8_lossy(&out.stderr);
    let lines: Vec<&str> = stderr.lines().collect();
    assert_eq!(
        lines.len(),
        1,
        "{context}: stderr must be exactly one line, got {stderr:?}"
    );
    assert!(
        lines[0].starts_with("error: "),
        "{context}: stderr line must start with `error: `, got {stderr:?}"
    );
    assert!(
        stderr.ends_with('\n'),
        "{context}: the error line must be LF-terminated"
    );
}

fn load_replay(path: &Path) -> ReplayV1 {
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

fn load_analysis(path: &Path) -> SearchAnalysisV1 {
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

fn no_temp_residue(dir: &Path) -> bool {
    std::fs::read_dir(dir)
        .unwrap()
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .all(|n| !n.ends_with(".tmp"))
}

#[test]
fn success_is_silent_and_artifact_is_fully_bound() {
    let dir = tmp_dir("success");
    let replay_path = record_replay(&dir);
    let out_path = dir.join("analysis.json");

    let out = run_analyze(&replay_path, 0, 1, 10_000, &out_path);
    assert_eq!(out.status.code(), Some(0), "expected exit 0: {out:?}");
    assert!(out.stdout.is_empty(), "stdout must be empty on success");
    assert!(out.stderr.is_empty(), "stderr must be empty on success");

    let raw = std::fs::read_to_string(&out_path).unwrap();
    assert!(raw.ends_with('\n'), "artifact ends with a single LF");
    assert!(raw.starts_with("{\n"), "artifact is pretty-printed");

    let analysis = load_analysis(&out_path);
    let replay = load_replay(&replay_path);

    // Frozen identity block.
    assert_eq!(analysis.format, SEARCH_ANALYSIS_FORMAT);
    assert_eq!(analysis.version, SEARCH_ANALYSIS_VERSION);
    assert_eq!(analysis.search_algorithm_id, SEARCH_ALGORITHM_ID);
    assert_eq!(analysis.search_version, SEARCH_VERSION);
    assert_eq!(analysis.engine_version, replay.engine_version);

    // Source block binds the exact replay document and analyzed step.
    assert_eq!(
        analysis.source.replay_document_hash,
        replay_document_hash_v1(&replay).unwrap()
    );
    assert_eq!(
        analysis.source.replay_final_state_hash,
        replay.final_state_hash.as_str()
    );
    assert_eq!(analysis.source.replay_version, replay.version);
    assert_eq!(
        analysis.source.ruleset_fingerprint,
        replay.ruleset_fingerprint.as_str()
    );
    assert_eq!(analysis.source.analyzed_ply, 0);
    let step = &replay.steps[0];
    assert_eq!(
        analysis.source.analyzed_state_hash,
        step.state_hash_before.as_str()
    );
    assert_eq!(analysis.source.recorded_actor, step.actor);
    assert_eq!(analysis.source.recorded_action, step.action);

    // Result block is bound to the analyzed position.
    assert_eq!(analysis.result.root_player, step.actor);
    assert_eq!(analysis.config.max_depth_turns, 1);
    assert_eq!(analysis.config.max_nodes, 10_000);
    assert_eq!(
        analysis.recommended_matches_recorded,
        analysis.result.action == step.action
    );

    // The published artifact's principal variation must still be a legal line
    // from the analyzed position after the full search → DTO → JSON → disk →
    // deserialize round trip. Rebuild the referee state independently and
    // replay every PV entry against it.
    assert_published_pv_is_playable(&replay, &analysis);
}

/// Replay `analysis.result.principal_variation` from the state rebuilt by
/// `verify_replay_position`, asserting every entry is legal, applies, and the
/// line never skips a required `ChooseNoble` continuation.
fn assert_published_pv_is_playable(replay: &ReplayV1, analysis: &SearchAnalysisV1) {
    let position = verify_replay_position(replay, analysis.source.analyzed_ply)
        .expect("the analyzed position must re-verify independently");
    assert_eq!(
        position.state_hash, analysis.source.analyzed_state_hash,
        "the rebuilt state must be the one the artifact claims to analyze"
    );

    let pv = &analysis.result.principal_variation;
    assert!(
        !pv.is_empty(),
        "a published analysis must carry a non-empty principal variation"
    );
    assert_eq!(
        pv[0], analysis.result.action,
        "principal_variation[0] must equal the recommended action"
    );

    let mut cursor = position.state;
    for (i, &action) in pv.iter().enumerate() {
        // A required noble choice must be the very next PV entry, never
        // skipped over: in `ChooseNoble` only `ChooseNoble` actions are legal,
        // so the legality assertion below is what catches a skipped one.
        let expects_noble = cursor.phase == Phase::ChooseNoble;
        let legal = cursor.legal_actions();
        assert!(
            legal.contains(&action),
            "principal_variation[{i}] = {action:?} is not legal in the state \
             reached after the previous PV prefix (phase = {:?}, \
             choose-noble pending = {expects_noble}); legal = {legal:?}",
            cursor.phase
        );
        cursor.apply(action).unwrap_or_else(|e| {
            panic!("principal_variation[{i}] = {action:?} failed to apply: {e}")
        });
    }
}

#[test]
fn analysis_is_deterministic_byte_for_byte() {
    let dir = tmp_dir("determinism");
    let replay_path = record_replay(&dir);
    let out_a = dir.join("a.json");
    let out_b = dir.join("b.json");

    let ra = run_analyze(&replay_path, 3, 1, 10_000, &out_a);
    let rb = run_analyze(&replay_path, 3, 1, 10_000, &out_b);
    assert_eq!(ra.status.code(), Some(0));
    assert_eq!(rb.status.code(), Some(0));

    let a = std::fs::read(&out_a).unwrap();
    let b = std::fs::read(&out_b).unwrap();
    assert_eq!(a, b, "same replay/ply/config must be byte-identical");
}

#[test]
fn middle_ply_binds_that_exact_step() {
    let dir = tmp_dir("middle");
    let replay_path = record_replay(&dir);
    let replay = load_replay(&replay_path);
    let mid = (replay.steps.len() / 2) as u32;
    let out_path = dir.join("analysis.json");

    let out = run_analyze(&replay_path, mid, 1, 10_000, &out_path);
    assert_eq!(out.status.code(), Some(0), "expected exit 0: {out:?}");

    let analysis = load_analysis(&out_path);
    let step = &replay.steps[mid as usize];
    assert_eq!(analysis.source.analyzed_ply, mid);
    assert_eq!(
        analysis.source.analyzed_state_hash,
        step.state_hash_before.as_str()
    );
    assert_eq!(analysis.source.recorded_actor, step.actor);
    assert_eq!(analysis.source.recorded_action, step.action);
    assert_eq!(analysis.result.root_player, step.actor);

    // The mid-game published line must be playable too.
    assert_published_pv_is_playable(&replay, &analysis);
}

#[test]
fn existing_out_target_is_never_overwritten() {
    let dir = tmp_dir("no-overwrite");
    let replay_path = record_replay(&dir);
    let out_path = dir.join("analysis.json");
    std::fs::write(&out_path, "SENTINEL\n").unwrap();

    let out = run_analyze(&replay_path, 0, 1, 10_000, &out_path);
    assert_eq!(out.status.code(), Some(1), "expected exit 1: {out:?}");
    assert_failure_streams(&out, "pre-existing out target");
    assert_eq!(
        std::fs::read_to_string(&out_path).unwrap(),
        "SENTINEL\n",
        "pre-existing artifact must be preserved"
    );
    assert!(no_temp_residue(&dir), "no temp residue may remain");
}

#[test]
fn ply_out_of_range_is_a_fatal_error() {
    let dir = tmp_dir("range");
    let replay_path = record_replay(&dir);
    let replay = load_replay(&replay_path);
    let out_path = dir.join("analysis.json");

    let out = run_analyze(
        &replay_path,
        replay.steps.len() as u32,
        1,
        10_000,
        &out_path,
    );
    assert_eq!(out.status.code(), Some(1), "expected exit 1: {out:?}");
    assert_failure_streams(&out, "ply out of range");
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(stderr.contains("out of range"), "stderr: {stderr}");
    assert!(!out_path.exists(), "no artifact may be written");
}

#[test]
fn tampered_replay_is_rejected_before_any_artifact() {
    let dir = tmp_dir("tamper");
    let replay_path = record_replay(&dir);
    let mut value: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(&replay_path).unwrap()).unwrap();
    let seed = value["seed"].as_u64().unwrap();
    value["seed"] = serde_json::json!(seed + 1);
    let tampered_path = dir.join("tampered.json");
    std::fs::write(
        &tampered_path,
        serde_json::to_string_pretty(&value).unwrap(),
    )
    .unwrap();
    let out_path = dir.join("analysis.json");

    let out = run_analyze(&tampered_path, 0, 1, 10_000, &out_path);
    assert_eq!(out.status.code(), Some(1), "expected exit 1: {out:?}");
    assert_failure_streams(&out, "tampered prefix");
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(
        stderr.contains("replay verification failed"),
        "stderr: {stderr}"
    );
    assert!(!out_path.exists(), "no artifact may be written");
}

/// Tampering *after* the analyzed ply must still be fatal: the CLI verifies
/// the whole suffix, not merely the prefix leading to the target position.
/// This drives the full composite path through the real subprocess — argv
/// parse, strict replay parse, `verify_replay_position`, suppressed publish.
#[test]
fn tampered_suffix_after_target_ply_is_rejected() {
    let dir = tmp_dir("tamper-suffix");
    let replay_path = record_replay(&dir);
    let mut value: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(&replay_path).unwrap()).unwrap();

    let steps = value["steps"].as_array_mut().expect("steps array");
    assert!(
        steps.len() > 2,
        "the fixture replay must have a suffix past ply 0"
    );
    let last = steps.len() - 1;
    // Corrupt the LAST step's after-hash: strictly later than the analyzed
    // ply 0, so only full-suffix verification can catch it.
    let original = steps[last]["state_hash_after"]
        .as_str()
        .expect("hash string")
        .to_string();
    let mut flipped: Vec<char> = original.chars().collect();
    flipped[0] = if flipped[0] == '0' { '1' } else { '0' };
    let flipped: String = flipped.into_iter().collect();
    assert_ne!(
        flipped, original,
        "the tamper must actually change the hash"
    );
    steps[last]["state_hash_after"] = serde_json::json!(flipped);

    let tampered_path = dir.join("tampered-suffix.json");
    std::fs::write(
        &tampered_path,
        serde_json::to_string_pretty(&value).unwrap(),
    )
    .unwrap();
    let out_path = dir.join("analysis.json");

    // Analyze ply 0 — the prefix up to it is pristine.
    let out = run_analyze(&tampered_path, 0, 1, 10_000, &out_path);
    assert_eq!(
        out.status.code(),
        Some(1),
        "a tampered suffix must be fatal even when the target ply verifies: {out:?}"
    );
    assert_failure_streams(&out, "tampered suffix");
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(
        stderr.contains("replay verification failed"),
        "stderr: {stderr}"
    );
    assert!(!out_path.exists(), "no artifact may be published");
    assert!(no_temp_residue(&dir), "no temp residue may remain");
}

#[test]
fn invalid_replay_json_is_a_fatal_error() {
    let dir = tmp_dir("badjson");
    let bad_path = dir.join("bad.json");
    std::fs::write(&bad_path, "{ not json").unwrap();
    let out_path = dir.join("analysis.json");

    let out = run_analyze(&bad_path, 0, 1, 10_000, &out_path);
    assert_eq!(out.status.code(), Some(1), "expected exit 1: {out:?}");
    assert_failure_streams(&out, "invalid replay json");
    assert!(!out_path.exists());
}

#[test]
fn missing_out_parent_is_a_fatal_error() {
    let dir = tmp_dir("noparent");
    let replay_path = record_replay(&dir);
    let out_path = dir.join("no").join("such").join("dir").join("a.json");

    let out = run_analyze(&replay_path, 0, 1, 10_000, &out_path);
    assert_eq!(out.status.code(), Some(1), "expected exit 1: {out:?}");
    assert_failure_streams(&out, "missing out parent");
    assert!(!out_path.exists());
}

/// A search config outside the frozen limits is a runtime rejection, not an
/// argv grammar error: exit 1, never 2.
#[test]
fn invalid_search_config_is_a_fatal_error() {
    let dir = tmp_dir("badconfig");
    let replay_path = record_replay(&dir);
    let replay_str = replay_path.to_string_lossy().into_owned();
    let out_path = dir.join("analysis.json");
    let out_str = out_path.to_string_lossy().into_owned();

    // All four frozen bounds: depth below/above range, nodes below/above.
    for (depth, nodes) in [("0", "1000"), ("13", "1000"), ("1", "0"), ("1", "10000001")] {
        let out = run_raw(&[
            "--input",
            &replay_str,
            "--ply",
            "0",
            "--max-depth-turns",
            depth,
            "--max-nodes",
            nodes,
            "--out",
            &out_str,
        ]);
        assert_eq!(
            out.status.code(),
            Some(1),
            "depth={depth} nodes={nodes} must exit 1, not a usage error: {out:?}"
        );
        assert_failure_streams(&out, "invalid search config");
        let stderr = String::from_utf8_lossy(&out.stderr);
        assert!(stderr.contains("invalid search config"), "stderr: {stderr}");
        assert!(!out_path.exists(), "no artifact may be written");
    }
}

#[test]
fn usage_errors_exit_two_and_write_nothing() {
    let dir = tmp_dir("usage");
    let replay_path = record_replay(&dir);
    let replay_str = replay_path.to_string_lossy().into_owned();
    let out_path = dir.join("analysis.json");
    let out_str = out_path.to_string_lossy().into_owned();

    let cases: Vec<Vec<&str>> = vec![
        // no arguments at all
        vec![],
        // missing --out
        vec![
            "--input",
            &replay_str,
            "--ply",
            "0",
            "--max-depth-turns",
            "1",
            "--max-nodes",
            "1000",
        ],
        // duplicate --ply
        vec![
            "--input",
            &replay_str,
            "--ply",
            "0",
            "--ply",
            "1",
            "--max-depth-turns",
            "1",
            "--max-nodes",
            "1000",
            "--out",
            &out_str,
        ],
        // unknown flag
        vec![
            "--input",
            &replay_str,
            "--ply",
            "0",
            "--max-depth-turns",
            "1",
            "--max-nodes",
            "1000",
            "--out",
            &out_str,
            "--bogus",
            "x",
        ],
        // non-numeric ply
        vec![
            "--input",
            &replay_str,
            "--ply",
            "abc",
            "--max-depth-turns",
            "1",
            "--max-nodes",
            "1000",
            "--out",
            &out_str,
        ],
        // `--flag=value` form is not part of the frozen grammar
        vec![
            "--input=replay.json",
            "--ply",
            "0",
            "--max-depth-turns",
            "1",
            "--max-nodes",
            "1000",
            "--out",
            &out_str,
        ],
        // flag value may not be another flag
        vec!["--input", "--ply", "0"],
        // stray positional token
        vec![
            "--input",
            &replay_str,
            "--ply",
            "0",
            "--max-depth-turns",
            "1",
            "--max-nodes",
            "1000",
            "--out",
            &out_str,
            "stray",
        ],
    ];

    for case in cases {
        let out = run_raw(&case);
        assert_eq!(out.status.code(), Some(2), "case {case:?}: {out:?}");
        assert_failure_streams(&out, &format!("usage case {case:?}"));
        assert!(!out_path.exists(), "case {case:?}: nothing may be written");
    }
}

/// There is no help mode in the C4 contract. `-h`/`--help` behave exactly like
/// any other unknown flag and can never short-circuit the strict grammar, in
/// any position or combination.
#[test]
fn help_flags_are_usage_errors_and_never_bypass_parsing() {
    let dir = tmp_dir("help");
    let replay_path = record_replay(&dir);
    let replay_str = replay_path.to_string_lossy().into_owned();
    let out_path = dir.join("analysis.json");
    let out_str = out_path.to_string_lossy().into_owned();

    let cases: Vec<Vec<&str>> = vec![
        vec!["--help"],
        vec!["-h"],
        // help must not excuse an unknown flag
        vec!["--help", "--bogus", "x"],
        // help must not excuse a duplicate flag
        vec!["--ply", "1", "--ply", "2", "--help"],
        // help must not excuse missing flags
        vec!["--input", &replay_str, "--help"],
        // help appended to an otherwise complete invocation still fails
        vec![
            "--input",
            &replay_str,
            "--ply",
            "0",
            "--max-depth-turns",
            "1",
            "--max-nodes",
            "1000",
            "--out",
            &out_str,
            "--help",
        ],
    ];

    for case in cases {
        let out = run_raw(&case);
        assert_eq!(
            out.status.code(),
            Some(2),
            "case {case:?} must be a usage error: {out:?}"
        );
        assert_failure_streams(&out, &format!("help case {case:?}"));
        assert!(!out_path.exists(), "case {case:?}: nothing may be written");
    }
}
