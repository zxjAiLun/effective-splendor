//! M05 fixed benchmark verifier: 200 matches, heuristic-v1 vs random-v1.
//!
//! This test runs the checked-in, frozen benchmark plan
//! (`benchmarks/m05-agent-eval-v1.plan.json`) end to end through the real
//! `splendor eval` subprocess and enforces the M05 strength gate. It is
//! `#[ignore]`d so the default workspace test passes do not replay 200 games;
//! the release gate runs it explicitly:
//!
//! ```text
//! cargo test --locked -p splendor-cli --test eval_benchmark -- --ignored --test-threads=1
//! ```
//!
//! The plan's agent commands use the portable literal program name
//! `splendor` (never an absolute path, so the plan hash freezes across
//! machines); this test prepends the freshly built binary's directory to
//! `PATH` before invoking `splendor eval`, and the agent subprocesses inherit
//! that environment.

use std::collections::BTreeSet;
use std::path::{Path, PathBuf};

use splendor_arena::{ArenaOutcomeV1, ArenaReportV1};
use splendor_eval::{evaluation_plan_hash_v1, EvaluationPlanV1, EvaluationReportV1};
use splendor_replay::{verify_replay, ReplayV1};

/// SHA-256 of the frozen benchmark plan. Any change to the checked-in plan
/// (agents, commands, seeds, timeouts) breaks this constant on purpose.
const FROZEN_PLAN_HASH: &str = "f574d7f5f5346978ee794a474e567b9a1b8930e69ed143a0ad782f9edd216f64";

/// The frozen schedule size: 2 agents x 100 seeds x 2 rotations.
const SCHEDULED_MATCHES: u32 = 200;

/// Strength gate, frozen before the benchmark was first run:
/// the heuristic must win at least 120 of the 200 matches.
const MIN_HEURISTIC_WINS: u32 = 120;

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn benchmark_plan_path() -> PathBuf {
    repo_root().join("benchmarks/m05-agent-eval-v1.plan.json")
}

fn bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_splendor"))
}

/// `PATH` with the built binary's directory prepended, so the plan's literal
/// `splendor` program name resolves to the binary under test.
fn path_with_bin_dir() -> std::ffi::OsString {
    let bin_dir = bin().parent().expect("binary has a parent dir").to_owned();
    let mut parts = vec![bin_dir];
    if let Some(existing) = std::env::var_os("PATH") {
        parts.extend(std::env::split_paths(&existing));
    }
    std::env::join_paths(parts).expect("PATH entries must be joinable")
}

fn match_report_name(match_index: u32) -> String {
    format!("match-{match_index:06}.report.json")
}

fn match_replay_name(match_index: u32) -> String {
    format!("match-{match_index:06}.replay.json")
}

#[test]
#[ignore = "M05 fixed 200-match benchmark; run explicitly with -- --ignored"]
fn m05_fixed_benchmark_meets_strength_gate() {
    // 1. Read and strictly parse the checked-in plan.
    let plan_path = benchmark_plan_path();
    let plan_text = std::fs::read_to_string(&plan_path)
        .unwrap_or_else(|e| panic!("read {}: {e}", plan_path.display()));
    let plan: EvaluationPlanV1 =
        serde_json::from_str(&plan_text).expect("benchmark plan must strictly parse");
    plan.validate().expect("benchmark plan must validate");

    // 2. The plan hash is frozen.
    let hash = evaluation_plan_hash_v1(&plan).expect("benchmark plan must hash");
    assert_eq!(
        hash.as_str(),
        FROZEN_PLAN_HASH,
        "the checked-in benchmark plan must hash to the frozen value"
    );

    // 3. Frozen composition: heuristic first, random second, 100 seeds.
    assert_eq!(plan.evaluation_id, "m05-agent-eval-v1");
    assert_eq!(plan.agents.len(), 2);
    assert_eq!(plan.agents[0].id, "heuristic-v1");
    assert_eq!(plan.agents[1].id, "random-v1");
    assert_eq!(plan.game_seeds.len(), 100);
    for agent in &plan.agents {
        assert_eq!(
            agent.command.program.to_str(),
            Some("splendor"),
            "benchmark agent commands must use the portable literal program name"
        );
    }

    // 4. Run the full evaluation through the real CLI, with the built
    // binary's directory prepended to PATH.
    let out_dir =
        std::env::temp_dir().join(format!("splendor-m05-benchmark-{}", std::process::id()));
    if out_dir.exists() {
        std::fs::remove_dir_all(&out_dir).unwrap();
    }
    let output = std::process::Command::new(bin())
        .arg("eval")
        .arg("--plan")
        .arg(&plan_path)
        .arg("--out-dir")
        .arg(&out_dir)
        .env("PATH", path_with_bin_dir())
        .output()
        .expect("failed to spawn splendor eval");
    assert!(
        output.status.success(),
        "benchmark eval must exit 0; stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(
        output.stdout.is_empty(),
        "stdout must be empty on success, got: {}",
        String::from_utf8_lossy(&output.stdout)
    );

    // 5. The published plan hash matches the frozen value.
    let published_hash = std::fs::read_to_string(out_dir.join("plan-hash.txt")).unwrap();
    assert_eq!(published_hash.trim(), FROZEN_PLAN_HASH);

    // 6. Strictly parse the evaluation report.
    let report: EvaluationReportV1 =
        serde_json::from_str(&std::fs::read_to_string(out_dir.join("eval-report.json")).unwrap())
            .expect("eval-report.json must strictly parse");
    assert_eq!(report.plan_hash, FROZEN_PLAN_HASH);
    assert_eq!(report.scheduled_matches, SCHEDULED_MATCHES);
    assert_eq!(report.records.len(), SCHEDULED_MATCHES as usize);

    // 7. Artifact containment + exact naming: 200 reports + 200 replays,
    // all named from match_index, nothing else in matches/.
    let matches_dir = out_dir.join("matches");
    let entries: BTreeSet<String> = std::fs::read_dir(&matches_dir)
        .unwrap()
        .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
        .collect();
    let expected: BTreeSet<String> = (0..SCHEDULED_MATCHES)
        .flat_map(|i| [match_report_name(i), match_replay_name(i)])
        .collect();
    assert_eq!(
        entries, expected,
        "matches/ must contain exactly the 400 match-index-derived artifacts"
    );

    // 8. Every record is completed; every match report and replay verifies
    // and binds to its record via match_index and the final state hash.
    for rec in &report.records {
        let replay_final_hash = match &rec.outcome {
            ArenaOutcomeV1::Completed {
                replay_final_hash, ..
            } => replay_final_hash.clone(),
            other => panic!(
                "benchmark match {} must complete, got {other:?}",
                rec.match_index
            ),
        };

        let match_report: ArenaReportV1 = serde_json::from_str(
            &std::fs::read_to_string(matches_dir.join(match_report_name(rec.match_index))).unwrap(),
        )
        .expect("match report must strictly parse");
        assert_eq!(match_report.game_id, rec.game_id);
        assert_eq!(match_report.outcome, rec.outcome);

        let replay: ReplayV1 = serde_json::from_str(
            &std::fs::read_to_string(matches_dir.join(match_replay_name(rec.match_index))).unwrap(),
        )
        .expect("match replay must strictly parse");
        let verified = verify_replay(&replay)
            .unwrap_or_else(|e| panic!("replay for match {} must verify: {e}", rec.match_index));
        assert_eq!(
            verified.final_state_hash, replay_final_hash,
            "re-executed replay final hash must bind to the report outcome (match {})",
            rec.match_index
        );
    }

    // 9. Strength gate (frozen before the first benchmark run).
    let heuristic = report
        .agents
        .iter()
        .find(|a| a.agent_id == "heuristic-v1")
        .expect("heuristic-v1 aggregate");
    let random = report
        .agents
        .iter()
        .find(|a| a.agent_id == "random-v1")
        .expect("random-v1 aggregate");

    for agent in [heuristic, random] {
        assert_eq!(agent.scheduled_matches, SCHEDULED_MATCHES);
        assert_eq!(
            agent.completed_matches, SCHEDULED_MATCHES,
            "{} must complete every match",
            agent.agent_id
        );
        assert_eq!(agent.aborted_matches, 0, "{} aborts", agent.agent_id);
        assert_eq!(agent.faults_caused, 0, "{} faults", agent.agent_id);
    }
    assert!(
        heuristic.wins >= MIN_HEURISTIC_WINS,
        "strength gate: heuristic wins {} < {MIN_HEURISTIC_WINS}",
        heuristic.wins
    );
    assert!(
        heuristic.rank_sum < random.rank_sum,
        "strength gate: heuristic rank_sum {} must beat random rank_sum {}",
        heuristic.rank_sum,
        random.rank_sum
    );

    // Clean up the ~400-file output tree on success.
    let _ = std::fs::remove_dir_all(&out_dir);
}
