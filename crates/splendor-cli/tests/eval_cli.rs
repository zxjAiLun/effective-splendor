//! End-to-end CLI tests for `splendor eval`.
//!
//! These run the real `splendor` binary as a subprocess (so the full path
//! through `eval_command::run_eval` is exercised, including `ArenaRunner`
//! spawning agent subprocesses). Agents are pointed at the same binary's
//! `agent-random` subcommand via `CARGO_BIN_EXE_splendor`, which is the
//! canonical reference agent and plays a full game to terminal.
//!
//! Run single-threaded: `cargo test -p splendor-cli --test eval_cli -- --test-threads=1`.
//! Each test uses a unique temp dir so concurrent runs would not collide, but
//! the gate runs these tests with `--test-threads=1` to match the existing
//! arena/runner single-threaded discipline.

use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::atomic::{AtomicU64, Ordering};

use splendor_arena::AgentCommand;
use splendor_eval::{
    EvaluationAgentV1, EvaluationPlanV1, EvaluationReportV1, EVALUATION_PLAN_FORMAT,
    EVALUATION_VERSION,
};

static TMP_SEQ: AtomicU64 = AtomicU64::new(0);

/// The path to the built `splendor` binary under test.
fn bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_splendor"))
}

/// A unique temp directory for one test run.
fn tmp_eval_dir(label: &str) -> PathBuf {
    let n = TMP_SEQ.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!(
        "splendor-eval-cli-{}-{}-{}",
        std::process::id(),
        label,
        n
    ));
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

/// A plan whose two agents are real `agent-random` subprocesses. All matches
/// complete, so every match publishes a replay.
fn completed_plan(evaluation_id: &str, seeds: &[u64]) -> EvaluationPlanV1 {
    let b = bin();
    EvaluationPlanV1 {
        format: EVALUATION_PLAN_FORMAT.to_string(),
        version: EVALUATION_VERSION,
        evaluation_id: evaluation_id.to_string(),
        agents: vec![
            EvaluationAgentV1 {
                id: "A".to_string(),
                command: AgentCommand {
                    program: b.clone(),
                    args: vec!["agent-random".into(), "--seed".into(), "1".into()],
                },
            },
            EvaluationAgentV1 {
                id: "B".to_string(),
                command: AgentCommand {
                    program: b,
                    args: vec!["agent-random".into(), "--seed".into(), "2".into()],
                },
            },
        ],
        game_seeds: seeds.to_vec(),
        handshake_timeout_ms: 5_000,
        move_timeout_ms: 5_000,
        shutdown_grace_ms: 2_000,
    }
}

/// A plan where agent `B` points at a program that does not exist, so every
/// match aborts (spawn failure → `Aborted`, `replay: None`).
fn aborted_plan(evaluation_id: &str, seeds: &[u64]) -> EvaluationPlanV1 {
    let good = bin();
    let bad = PathBuf::from("C:/nonexistent_dir_xyz/agent.exe");
    EvaluationPlanV1 {
        format: EVALUATION_PLAN_FORMAT.to_string(),
        version: EVALUATION_VERSION,
        evaluation_id: evaluation_id.to_string(),
        agents: vec![
            EvaluationAgentV1 {
                id: "A".to_string(),
                command: AgentCommand {
                    program: good,
                    args: vec!["agent-random".into(), "--seed".into(), "1".into()],
                },
            },
            EvaluationAgentV1 {
                id: "B".to_string(),
                command: AgentCommand {
                    program: bad,
                    args: vec![],
                },
            },
        ],
        game_seeds: seeds.to_vec(),
        handshake_timeout_ms: 5_000,
        move_timeout_ms: 5_000,
        shutdown_grace_ms: 2_000,
    }
}

fn write_plan(dir: &Path, plan: &EvaluationPlanV1) -> PathBuf {
    let path = dir.join("plan.json");
    let json = serde_json::to_string_pretty(plan).unwrap();
    std::fs::write(&path, json).unwrap();
    path
}

/// Run `splendor eval --plan <plan> --out-dir <out_dir>`.
fn run_eval(plan: &Path, out_dir: &Path) -> Output {
    Command::new(bin())
        .arg("eval")
        .arg("--plan")
        .arg(plan)
        .arg("--out-dir")
        .arg(out_dir)
        .output()
        .expect("failed to spawn splendor eval")
}

fn matches_dir(out_dir: &Path) -> PathBuf {
    out_dir.join("matches")
}

/// The canonical per-match artifact names: derived from `match_index` only.
fn match_report_name(match_index: u32) -> String {
    format!("match-{match_index:06}.report.json")
}

fn match_replay_name(match_index: u32) -> String {
    format!("match-{match_index:06}.replay.json")
}

/// Test 1: a normal 2-agent x 2-seed plan publishes every artifact and exits 0.
#[test]
fn normal_run_publishes_all_artifacts_and_exits_zero() {
    let dir = tmp_eval_dir("normal");
    let plan_path = write_plan(&dir, &completed_plan("eval-cli-normal", &[1, 2]));
    let out_dir = dir.join("out");

    let output = run_eval(&plan_path, &out_dir);
    assert!(
        output.status.success(),
        "eval should exit 0 on success; stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    // stdout must be empty on success.
    assert!(
        output.stdout.is_empty(),
        "stdout must be empty on success, got: {}",
        String::from_utf8_lossy(&output.stdout)
    );

    let report_path = out_dir.join("eval-report.json");
    assert!(report_path.exists(), "eval-report.json must be published");
    assert!(
        out_dir.join("plan.json").exists(),
        "plan.json must be published"
    );
    assert!(
        out_dir.join("plan-hash.txt").exists(),
        "plan-hash.txt must be published"
    );

    let report: EvaluationReportV1 =
        serde_json::from_str(&std::fs::read_to_string(&report_path).unwrap()).unwrap();
    assert_eq!(report.scheduled_matches, 4);
    assert_eq!(report.records.len(), 4);

    for rec in &report.records {
        let report_file = matches_dir(&out_dir).join(match_report_name(rec.match_index));
        let replay_file = matches_dir(&out_dir).join(match_replay_name(rec.match_index));
        assert!(
            report_file.exists(),
            "per-match report must exist for match {}",
            rec.match_index
        );
        assert!(
            replay_file.exists(),
            "per-match replay must exist for completed match {}",
            rec.match_index
        );
    }
}

/// Match artifact filenames are derived from the canonical `match_index`
/// (fixed `match-NNNNNN.*` shape) and never embed the game ID / evaluation ID.
#[test]
fn match_artifact_names_are_derived_from_match_index() {
    let dir = tmp_eval_dir("names");
    let plan_path = write_plan(&dir, &completed_plan("eval-cli-names", &[7, 8]));
    let out_dir = dir.join("out");

    let output = run_eval(&plan_path, &out_dir);
    assert!(
        output.status.success(),
        "stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );

    let mut entries = std::fs::read_dir(matches_dir(&out_dir))
        .unwrap()
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .collect::<Vec<_>>();
    entries.sort();
    // 2 agents x 2 seeds = 4 matches (indices 0..=3), each completed:
    // exactly one report + one replay per index, nothing else.
    let mut expected: Vec<String> = (0..4)
        .flat_map(|i| [match_report_name(i), match_replay_name(i)])
        .collect();
    expected.sort();
    assert_eq!(
        entries, expected,
        "per-match artifacts must be exactly the match-index-derived names"
    );
    // The evaluation ID must not leak into any filename.
    assert!(
        entries.iter().all(|n| !n.contains("eval-cli-names")),
        "evaluation ID must not appear in artifact filenames: {entries:?}"
    );

    // The records still carry the original game IDs (mapping is by index).
    let report: EvaluationReportV1 =
        serde_json::from_str(&std::fs::read_to_string(out_dir.join("eval-report.json")).unwrap())
            .unwrap();
    for rec in &report.records {
        assert!(
            rec.game_id.starts_with("eval-cli-names-s"),
            "record must preserve the original game_id, got {}",
            rec.game_id
        );
    }
}

/// A path-like evaluation ID (traversal attempt) must not place any artifact
/// outside `<out-dir>`; filenames stay `match-NNNNNN.*` and the original game
/// ID survives inside the report/replay JSON for verification.
#[test]
fn path_like_evaluation_id_cannot_escape_out_dir() {
    let dir = tmp_eval_dir("traversal");
    // Legal per the C3 model (non-empty, short, no C0 controls), but hostile
    // as a path fragment.
    let evil_id = "../../escaped";
    let plan_path = write_plan(&dir, &completed_plan(evil_id, &[1]));
    // Nest out-dir so an escaped write would land inside `dir` (observable).
    let out_parent = dir.join("nest");
    std::fs::create_dir_all(&out_parent).unwrap();
    let out_dir = out_parent.join("out");

    let output = run_eval(&plan_path, &out_dir);
    // 1. The evaluation completes normally.
    assert!(
        output.status.success(),
        "path-like evaluation_id must still evaluate; stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );

    // 2+3. All match artifacts live in <out-dir>/matches with index-derived
    // names that do not contain the evaluation ID. One seed x two agents
    // expands to 2 rotations = 2 matches (indices 0 and 1).
    let m = matches_dir(&out_dir);
    let entries = std::fs::read_dir(&m)
        .unwrap()
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .collect::<Vec<_>>();
    assert_eq!(
        entries.len(),
        4,
        "two matches x (report + replay) expected: {entries:?}"
    );
    for i in 0..2 {
        assert!(entries.contains(&match_report_name(i)));
        assert!(entries.contains(&match_replay_name(i)));
    }
    assert!(
        entries.iter().all(|n| !n.contains("escaped")),
        "evaluation ID must not leak into filenames: {entries:?}"
    );

    // 4. Nothing escaped the out-dir: the traversal targets that the old
    // game-id-derived naming would have produced must not exist.
    for escape_root in [dir.as_path(), dir.parent().unwrap(), out_parent.as_path()] {
        for leaked in [
            "escaped-s000000-r00.report.json",
            "escaped-s000000-r00.replay.json",
            "escaped-s000000-r01.report.json",
            "escaped-s000000-r01.replay.json",
        ] {
            assert!(
                !escape_root.join(leaked).exists(),
                "artifact escaped out-dir into {}",
                escape_root.display()
            );
        }
    }

    // 5. The eval report still preserves the original (hostile) game IDs.
    let report: EvaluationReportV1 =
        serde_json::from_str(&std::fs::read_to_string(out_dir.join("eval-report.json")).unwrap())
            .unwrap();
    assert_eq!(report.records.len(), 2);
    assert_eq!(report.records[0].game_id, "../../escaped-s000000-r00");
    assert_eq!(report.records[1].game_id, "../../escaped-s000000-r01");

    // 6. The per-match report/replay verify and map to the correct match:
    // the report embeds the record's game_id, and the replay's final state
    // hash equals the report outcome's replay_final_hash (replay ↔ report ↔
    // record correlation via match_index-derived filenames).
    let match_report: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(m.join(match_report_name(0))).unwrap())
            .unwrap();
    assert_eq!(
        match_report["game_id"].as_str().unwrap(),
        "../../escaped-s000000-r00"
    );
    let expected_final_hash = match_report["outcome"]["replay_final_hash"]
        .as_str()
        .expect("completed outcome must carry replay_final_hash")
        .to_owned();
    let replay: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(m.join(match_replay_name(0))).unwrap())
            .unwrap();
    assert_eq!(
        replay["final_state_hash"].as_str().unwrap(),
        expected_final_hash,
        "replay must correspond to the report for match_index 0"
    );
}

/// Test 2: a plan whose agent cannot spawn aborts every match, records the
/// fault on the bad agent, and still exits 0 (aborted matches are not errors).
#[test]
fn aborted_run_records_fault_and_exits_zero() {
    let dir = tmp_eval_dir("aborted");
    let plan_path = write_plan(&dir, &aborted_plan("eval-cli-aborted", &[1, 2]));
    let out_dir = dir.join("out");

    let output = run_eval(&plan_path, &out_dir);
    assert!(
        output.status.success(),
        "eval must exit 0 even when matches abort; stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(
        output.stdout.is_empty(),
        "stdout must be empty on success, got: {}",
        String::from_utf8_lossy(&output.stdout)
    );

    let report_path = out_dir.join("eval-report.json");
    let report: EvaluationReportV1 =
        serde_json::from_str(&std::fs::read_to_string(&report_path).unwrap()).unwrap();
    assert_eq!(report.scheduled_matches, 4);
    for rec in &report.records {
        assert!(
            matches!(rec.outcome, splendor_arena::ArenaOutcomeV1::Aborted { .. }),
            "every match must be aborted"
        );
    }

    // The bad agent (B) is attributed every fault; the good agent (A) none.
    let a = report.agents.iter().find(|a| a.agent_id == "A").unwrap();
    let b = report.agents.iter().find(|a| a.agent_id == "B").unwrap();
    assert_eq!(a.faults_caused, 0, "good agent must not be faulted");
    assert_eq!(
        b.faults_caused, 4,
        "bad agent must be faulted for every match"
    );
    assert_eq!(a.aborted_matches, 4);
    assert_eq!(b.aborted_matches, 4);
}

/// Test 3 (companion to Test 2): an aborted match publishes NO replay file.
#[test]
fn aborted_match_publishes_no_replay() {
    let dir = tmp_eval_dir("no-replay");
    let plan_path = write_plan(&dir, &aborted_plan("eval-cli-noreplay", &[1]));
    let out_dir = dir.join("out");

    let output = run_eval(&plan_path, &out_dir);
    assert!(output.status.success());

    let m = matches_dir(&out_dir);
    let entries = std::fs::read_dir(&m)
        .unwrap()
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .collect::<Vec<_>>();
    // Every per-match artifact must be a .report.json; no .replay.json allowed.
    assert!(
        !entries.iter().any(|n| n.ends_with(".replay.json")),
        "aborted matches must not publish a replay; found: {entries:?}"
    );
    assert!(
        entries.iter().all(|n| n.ends_with(".report.json")),
        "only report artifacts expected; found: {entries:?}"
    );
}

/// Test 4: an invalid plan (bad version) exits 1 and writes no artifacts.
#[test]
fn invalid_plan_exits_one_and_writes_nothing() {
    let dir = tmp_eval_dir("invalid");
    let mut plan = completed_plan("eval-cli-invalid", &[1]);
    plan.version = 999; // invalid; validate() rejects before hashing.
    let plan_path = write_plan(&dir, &plan);
    let out_dir = dir.join("out");

    let output = run_eval(&plan_path, &out_dir);
    assert!(
        !output.status.success(),
        "invalid plan must exit non-zero; stdout: {}",
        String::from_utf8_lossy(&output.stdout)
    );
    assert!(
        !out_dir.exists(),
        "no output directory must be created for an invalid plan"
    );
}

/// Test 5: a pre-existing eval-report.json is never overwritten; exit is 1.
#[test]
fn existing_eval_report_is_not_overwritten() {
    let dir = tmp_eval_dir("preexist");
    let plan_path = write_plan(&dir, &completed_plan("eval-cli-preexist", &[1]));
    let out_dir = dir.join("out");
    std::fs::create_dir_all(&out_dir).unwrap();
    let report_path = out_dir.join("eval-report.json");
    let sentinel = "SENTINEL-DO-NOT-OVERWRITE\n";
    std::fs::write(&report_path, sentinel).unwrap();

    let output = run_eval(&plan_path, &out_dir);
    assert!(
        !output.status.success(),
        "pre-existing eval-report.json must be rejected"
    );
    assert_eq!(
        std::fs::read_to_string(&report_path).unwrap(),
        sentinel,
        "pre-existing eval-report.json must be left untouched"
    );
}

/// Test 6: a missing output parent directory exits 1.
#[test]
fn missing_output_parent_exits_one() {
    let dir = tmp_eval_dir("missing-parent");
    let plan_path = write_plan(&dir, &completed_plan("eval-cli-missing", &[1]));

    // Parent of `out` does not exist.
    let out_dir = dir.join("no-such-parent").join("out");

    let output = run_eval(&plan_path, &out_dir);
    assert!(
        !output.status.success(),
        "missing output parent must exit 1; stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    // The missing parent directory itself must not be created.
    assert!(
        !dir.join("no-such-parent").exists(),
        "the missing parent must not be created"
    );
}
