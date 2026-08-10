//! End-to-end tests for `splendor promotion-gate`.

use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::atomic::{AtomicU64, Ordering};

use splendor_arena::{AgentCommand, ArenaOutcomeV1};
use splendor_core::{GameResult, PlayerId, TerminalReason};
use splendor_eval::{
    aggregate, expand_schedule, EvaluationAgentV1, EvaluationMatchRecordV1, EvaluationPlanV1,
    EvaluationReportV1, PromotionDecisionV1, PromotionGateV1, PromotionReportV1,
    EVALUATION_PLAN_FORMAT, EVALUATION_VERSION, PROMOTION_CONFIDENCE_BPS, PROMOTION_GATE_FORMAT,
    PROMOTION_VERSION,
};

static TMP_SEQ: AtomicU64 = AtomicU64::new(0);

fn bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_splendor"))
}

fn temp_dir(label: &str) -> PathBuf {
    let sequence = TMP_SEQ.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!(
        "splendor-promotion-cli-{}-{label}-{sequence}",
        std::process::id()
    ));
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn plan() -> EvaluationPlanV1 {
    EvaluationPlanV1 {
        format: EVALUATION_PLAN_FORMAT.to_string(),
        version: EVALUATION_VERSION,
        evaluation_id: "m09-cli".to_string(),
        agents: ["candidate", "champion"]
            .iter()
            .map(|id| EvaluationAgentV1 {
                id: (*id).to_string(),
                command: AgentCommand {
                    program: PathBuf::from(format!("unused-{id}")),
                    args: Vec::new(),
                },
            })
            .collect(),
        game_seeds: (0..20).collect(),
        handshake_timeout_ms: 1_000,
        move_timeout_ms: 2_000,
        shutdown_grace_ms: 1_000,
    }
}

fn report(plan: &EvaluationPlanV1, candidate_always_wins: bool) -> EvaluationReportV1 {
    let records = expand_schedule(plan)
        .unwrap()
        .into_iter()
        .map(|spec| {
            let candidate_seat = spec
                .agent_ids_by_seat
                .iter()
                .position(|id| id == "candidate")
                .unwrap();
            let champion_seat = 1 - candidate_seat;
            let candidate_wins = candidate_always_wins || spec.match_index % 2 == 0;
            let winner = if candidate_wins {
                candidate_seat
            } else {
                champion_seat
            };
            let mut scores = vec![10, 10];
            let mut ranks = vec![2, 2];
            scores[winner] = 15;
            ranks[winner] = 1;
            EvaluationMatchRecordV1 {
                match_index: spec.match_index,
                game_id: spec.arena_config.game_id,
                seed_index: spec.seed_index,
                rotation: spec.rotation,
                agent_ids_by_seat: spec.agent_ids_by_seat,
                outcome: ArenaOutcomeV1::completed(
                    GameResult {
                        scores,
                        ranks,
                        winners: vec![PlayerId(winner as u8)],
                        reason: TerminalReason::PrestigeThreshold,
                    },
                    30,
                    "ab".repeat(32),
                ),
            }
        })
        .collect::<Vec<_>>();
    aggregate(plan, &records).unwrap()
}

fn gate() -> PromotionGateV1 {
    PromotionGateV1 {
        format: PROMOTION_GATE_FORMAT.to_string(),
        version: PROMOTION_VERSION,
        promotion_id: "m09-cli-gate".to_string(),
        candidate_agent_id: "candidate".to_string(),
        champion_agent_id: "champion".to_string(),
        confidence_bps: PROMOTION_CONFIDENCE_BPS,
        min_completed_seed_blocks: 20,
        min_pairwise_score_lower_bound_bps: 5_000,
        max_aborted_matches: 0,
        max_candidate_faults: 0,
        max_move_timeout_ms: 2_000,
    }
}

fn write_json<T: serde::Serialize>(path: &Path, value: &T) {
    let mut json = serde_json::to_string_pretty(value).unwrap();
    json.push('\n');
    std::fs::write(path, json).unwrap();
}

fn run(dir: &Path, report: &EvaluationReportV1, preexisting_output: bool) -> (Output, PathBuf) {
    let plan_path = dir.join("plan.json");
    let report_path = dir.join("eval-report.json");
    let gate_path = dir.join("gate.json");
    let out_path = dir.join("promotion-report.json");
    write_json(&plan_path, &plan());
    write_json(&report_path, report);
    write_json(&gate_path, &gate());
    if preexisting_output {
        std::fs::write(&out_path, "SENTINEL\n").unwrap();
    }
    let output = Command::new(bin())
        .arg("promotion-gate")
        .arg("--plan")
        .arg(plan_path)
        .arg("--eval-report")
        .arg(report_path)
        .arg("--gate")
        .arg(gate_path)
        .arg("--out")
        .arg(&out_path)
        .output()
        .expect("spawn promotion-gate");
    (output, out_path)
}

#[test]
fn promote_writes_report_and_exits_zero() {
    let dir = temp_dir("promote");
    let (output, out_path) = run(&dir, &report(&plan(), true), false);
    assert_eq!(output.status.code(), Some(0));
    assert!(output.stdout.is_empty());
    assert!(output.stderr.is_empty());
    let promotion: PromotionReportV1 =
        serde_json::from_str(&std::fs::read_to_string(out_path).unwrap()).unwrap();
    assert_eq!(promotion.decision, PromotionDecisionV1::Promote);
    assert_eq!(promotion.pairwise.completed_seed_blocks, 20);
}

#[test]
fn reject_writes_report_and_exits_two() {
    let dir = temp_dir("reject");
    let (output, out_path) = run(&dir, &report(&plan(), false), false);
    assert_eq!(output.status.code(), Some(2));
    assert!(output.stdout.is_empty());
    assert!(output.stderr.is_empty());
    let promotion: PromotionReportV1 =
        serde_json::from_str(&std::fs::read_to_string(out_path).unwrap()).unwrap();
    assert_eq!(promotion.decision, PromotionDecisionV1::Reject);
}

#[test]
fn tampered_report_is_fatal_and_writes_nothing() {
    let dir = temp_dir("tampered");
    let mut eval_report = report(&plan(), true);
    eval_report.plan_hash = "00".repeat(32);
    let (output, out_path) = run(&dir, &eval_report, false);
    assert_eq!(output.status.code(), Some(1));
    assert!(output.stdout.is_empty());
    assert!(String::from_utf8_lossy(&output.stderr).contains("does not match"));
    assert!(!out_path.exists());
}

#[test]
fn existing_output_is_never_overwritten() {
    let dir = temp_dir("no-overwrite");
    let (output, out_path) = run(&dir, &report(&plan(), true), true);
    assert_eq!(output.status.code(), Some(1));
    assert_eq!(std::fs::read_to_string(out_path).unwrap(), "SENTINEL\n");
}
