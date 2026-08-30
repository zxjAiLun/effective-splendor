//! M09 deterministic competitive promotion gate.
//!
//! This layer consumes the frozen M05 evaluation plan/report artifacts. It
//! re-aggregates the report from its own records, compares one candidate with
//! one champion inside every completed paired seed block, computes a
//! deterministic integer 95% Hoeffding interval, and emits `promote` only when
//! every declared reliability, strength, and deadline-budget check passes.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use splendor_arena::ArenaOutcomeV1;

use crate::error::EvaluationError;
use crate::plan::EvaluationPlanV1;
use crate::report::{aggregate, EvaluationReportV1};

pub const PROMOTION_GATE_FORMAT: &str = "effective-splendor-promotion-gate";
pub const PROMOTION_REPORT_FORMAT: &str = "effective-splendor-promotion-report";
pub const PROMOTION_VERSION: u32 = 1;
pub const PROMOTION_CONFIDENCE_BPS: u16 = 9_500;
pub const BASIS_POINTS_SCALE: u16 = 10_000;

const MAX_PROMOTION_ID_BYTES: usize = 128;
// One-sided Hoeffding: epsilon = sqrt(3 / (2*n)). Since exp(-3) < 0.05,
// the lower bound has confidence strictly greater than 95%.
const HOEFFDING_RADICAND_NUMERATOR_BPS_SQUARED: u64 = 150_000_000;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PromotionGateV1 {
    pub format: String,
    pub version: u32,
    pub promotion_id: String,
    pub candidate_agent_id: String,
    pub champion_agent_id: String,
    pub confidence_bps: u16,
    pub min_completed_seed_blocks: u32,
    pub min_pairwise_score_lower_bound_bps: u16,
    pub max_aborted_matches: u32,
    pub max_candidate_faults: u32,
    pub max_move_timeout_ms: u64,
}

impl PromotionGateV1 {
    pub fn validate(&self) -> Result<(), EvaluationError> {
        if self.format != PROMOTION_GATE_FORMAT {
            return Err(invalid_gate(format!(
                "format must be '{PROMOTION_GATE_FORMAT}'"
            )));
        }
        if self.version != PROMOTION_VERSION {
            return Err(invalid_gate(format!("version must be {PROMOTION_VERSION}")));
        }
        if self.promotion_id.trim().is_empty()
            || self.promotion_id.len() > MAX_PROMOTION_ID_BYTES
            || self.promotion_id.as_bytes().iter().any(|byte| *byte < 0x20)
        {
            return Err(invalid_gate(
                "promotion_id must be non-empty, at most 128 bytes, and contain no C0 controls",
            ));
        }
        if self.candidate_agent_id == self.champion_agent_id {
            return Err(invalid_gate(
                "candidate_agent_id and champion_agent_id must differ",
            ));
        }
        if self.candidate_agent_id.trim().is_empty() || self.champion_agent_id.trim().is_empty() {
            return Err(invalid_gate("candidate/champion ids must not be empty"));
        }
        if self.confidence_bps != PROMOTION_CONFIDENCE_BPS {
            return Err(invalid_gate(format!(
                "confidence_bps must be the frozen value {PROMOTION_CONFIDENCE_BPS}"
            )));
        }
        if self.min_completed_seed_blocks == 0 {
            return Err(invalid_gate(
                "min_completed_seed_blocks must be greater than zero",
            ));
        }
        if self.min_pairwise_score_lower_bound_bps > BASIS_POINTS_SCALE {
            return Err(invalid_gate(format!(
                "min_pairwise_score_lower_bound_bps must be <= {BASIS_POINTS_SCALE}"
            )));
        }
        if self.max_move_timeout_ms == 0
            || self.max_move_timeout_ms > splendor_arena::config::MAX_TIMEOUT_MS
        {
            return Err(invalid_gate(
                "max_move_timeout_ms must be within the Arena timeout bounds",
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PromotionGateHash(String);

impl PromotionGateHash {
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl std::fmt::Display for PromotionGateHash {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

pub fn promotion_gate_hash_v1(
    gate: &PromotionGateV1,
) -> Result<PromotionGateHash, EvaluationError> {
    gate.validate()?;
    let json = serde_json::to_string(gate)
        .map_err(|error| EvaluationError::Serialization(error.to_string()))?;
    let mut hasher = Sha256::new();
    hasher.update(b"effective-splendor-promotion-gate-v1\0");
    hasher.update(json.as_bytes());
    Ok(PromotionGateHash(hex::encode(hasher.finalize())))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PromotionDecisionV1 {
    Promote,
    Reject,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PairwiseSummaryV1 {
    pub scheduled_seed_blocks: u32,
    pub completed_seed_blocks: u32,
    pub excluded_seed_blocks: u32,
    pub completed_matches: u32,
    pub candidate_wins: u32,
    pub ties: u32,
    pub candidate_losses: u32,
    /// Win=2, tie=1, loss=0.
    pub score_half_points: u32,
    pub score_basis_points: u16,
    pub confidence_lower_bound_basis_points: u16,
    pub confidence_upper_bound_basis_points: u16,
    pub candidate_rank_sum: u64,
    pub champion_rank_sum: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PromotionChecksV1 {
    pub sufficient_completed_seed_blocks: bool,
    pub aborted_matches_within_limit: bool,
    pub candidate_faults_within_limit: bool,
    pub move_timeout_within_limit: bool,
    pub pairwise_lower_bound_meets_threshold: bool,
}

impl PromotionChecksV1 {
    fn all_pass(&self) -> bool {
        self.sufficient_completed_seed_blocks
            && self.aborted_matches_within_limit
            && self.candidate_faults_within_limit
            && self.move_timeout_within_limit
            && self.pairwise_lower_bound_meets_threshold
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PromotionReportV1 {
    pub format: String,
    pub version: u32,
    pub promotion_id: String,
    pub evaluation_id: String,
    pub evaluation_plan_hash: String,
    pub promotion_gate_hash: String,
    pub candidate_agent_id: String,
    pub champion_agent_id: String,
    pub confidence_bps: u16,
    pub pairwise: PairwiseSummaryV1,
    pub aborted_matches: u32,
    pub candidate_faults: u32,
    pub move_timeout_ms: u64,
    pub checks: PromotionChecksV1,
    pub decision: PromotionDecisionV1,
}

#[derive(Default)]
struct SeedBlock {
    complete: bool,
    comparisons: Vec<(u8, u8)>,
}

pub fn evaluate_promotion_v1(
    plan: &EvaluationPlanV1,
    report: &EvaluationReportV1,
    gate: &PromotionGateV1,
) -> Result<PromotionReportV1, EvaluationError> {
    gate.validate()?;
    plan.validate()?;
    if gate.min_completed_seed_blocks > plan.game_seeds.len() as u32 {
        return Err(invalid_gate(
            "min_completed_seed_blocks exceeds the plan's seed count",
        ));
    }

    let canonical = aggregate(plan, &report.records)?;
    if &canonical != report {
        return Err(EvaluationError::EvaluationReportMismatch);
    }

    let candidate_plan_index = agent_index(plan, &gate.candidate_agent_id)?;
    let champion_plan_index = agent_index(plan, &gate.champion_agent_id)?;
    debug_assert_ne!(candidate_plan_index, champion_plan_index);

    let candidate = &report.agents[candidate_plan_index];
    let mut blocks = (0..plan.game_seeds.len())
        .map(|_| SeedBlock {
            complete: true,
            comparisons: Vec::with_capacity(plan.agents.len()),
        })
        .collect::<Vec<_>>();
    let mut aborted_matches = 0u32;

    for record in &report.records {
        let block = blocks.get_mut(record.seed_index as usize).ok_or_else(|| {
            EvaluationError::InvalidPromotionGate("record seed out of range".into())
        })?;
        match &record.outcome {
            ArenaOutcomeV1::Completed { result, .. } => {
                let candidate_seat = record
                    .agent_ids_by_seat
                    .iter()
                    .position(|id| id == &gate.candidate_agent_id)
                    .ok_or_else(|| {
                        EvaluationError::UnknownPromotionAgent(gate.candidate_agent_id.clone())
                    })?;
                let champion_seat = record
                    .agent_ids_by_seat
                    .iter()
                    .position(|id| id == &gate.champion_agent_id)
                    .ok_or_else(|| {
                        EvaluationError::UnknownPromotionAgent(gate.champion_agent_id.clone())
                    })?;
                block
                    .comparisons
                    .push((result.ranks[candidate_seat], result.ranks[champion_seat]));
            }
            ArenaOutcomeV1::Aborted { .. } => {
                aborted_matches = aborted_matches.saturating_add(1);
                block.complete = false;
            }
            ArenaOutcomeV1::Truncated { .. } => {
                // A promotion gate scores terminal games only; a truncated
                // (ply-capped) game has no result and cannot count.
                return Err(EvaluationError::InvalidPromotionGate(format!(
                    "match {} is truncated; promotion gates score terminal games only",
                    record.match_index
                )));
            }
        }
    }

    let mut wins = 0u32;
    let mut ties = 0u32;
    let mut losses = 0u32;
    let mut candidate_rank_sum = 0u64;
    let mut champion_rank_sum = 0u64;
    let mut completed_seed_blocks = 0u32;
    for block in &blocks {
        if !block.complete || block.comparisons.len() != plan.agents.len() {
            continue;
        }
        completed_seed_blocks += 1;
        for &(candidate_rank, champion_rank) in &block.comparisons {
            candidate_rank_sum += u64::from(candidate_rank);
            champion_rank_sum += u64::from(champion_rank);
            match candidate_rank.cmp(&champion_rank) {
                std::cmp::Ordering::Less => wins += 1,
                std::cmp::Ordering::Equal => ties += 1,
                std::cmp::Ordering::Greater => losses += 1,
            }
        }
    }

    let completed_matches = wins + ties + losses;
    let score_half_points = wins
        .checked_mul(2)
        .and_then(|value| value.checked_add(ties))
        .ok_or_else(|| EvaluationError::Serialization("pairwise score overflow".into()))?;
    let score_basis_points = if completed_matches == 0 {
        0
    } else {
        ((u64::from(score_half_points) * u64::from(BASIS_POINTS_SCALE))
            / (u64::from(completed_matches) * 2)) as u16
    };
    let (lower, upper) = confidence_interval_95(score_basis_points, completed_seed_blocks);

    let pairwise = PairwiseSummaryV1 {
        scheduled_seed_blocks: plan.game_seeds.len() as u32,
        completed_seed_blocks,
        excluded_seed_blocks: plan.game_seeds.len() as u32 - completed_seed_blocks,
        completed_matches,
        candidate_wins: wins,
        ties,
        candidate_losses: losses,
        score_half_points,
        score_basis_points,
        confidence_lower_bound_basis_points: lower,
        confidence_upper_bound_basis_points: upper,
        candidate_rank_sum,
        champion_rank_sum,
    };
    let checks = PromotionChecksV1 {
        sufficient_completed_seed_blocks: completed_seed_blocks >= gate.min_completed_seed_blocks,
        aborted_matches_within_limit: aborted_matches <= gate.max_aborted_matches,
        candidate_faults_within_limit: candidate.faults_caused <= gate.max_candidate_faults,
        move_timeout_within_limit: plan.move_timeout_ms <= gate.max_move_timeout_ms,
        pairwise_lower_bound_meets_threshold: lower >= gate.min_pairwise_score_lower_bound_bps,
    };
    let decision = if checks.all_pass() {
        PromotionDecisionV1::Promote
    } else {
        PromotionDecisionV1::Reject
    };

    Ok(PromotionReportV1 {
        format: PROMOTION_REPORT_FORMAT.to_string(),
        version: PROMOTION_VERSION,
        promotion_id: gate.promotion_id.clone(),
        evaluation_id: plan.evaluation_id.clone(),
        evaluation_plan_hash: report.plan_hash.clone(),
        promotion_gate_hash: promotion_gate_hash_v1(gate)?.to_string(),
        candidate_agent_id: gate.candidate_agent_id.clone(),
        champion_agent_id: gate.champion_agent_id.clone(),
        confidence_bps: gate.confidence_bps,
        pairwise,
        aborted_matches,
        candidate_faults: candidate.faults_caused,
        move_timeout_ms: plan.move_timeout_ms,
        checks,
        decision,
    })
}

fn invalid_gate(message: impl Into<String>) -> EvaluationError {
    EvaluationError::InvalidPromotionGate(message.into())
}

fn agent_index(plan: &EvaluationPlanV1, id: &str) -> Result<usize, EvaluationError> {
    plan.agents
        .iter()
        .position(|agent| agent.id == id)
        .ok_or_else(|| EvaluationError::UnknownPromotionAgent(id.to_string()))
}

fn confidence_interval_95(center: u16, completed_seed_blocks: u32) -> (u16, u16) {
    if completed_seed_blocks == 0 {
        return (0, BASIS_POINTS_SCALE);
    }
    let radicand = ceil_div(
        HOEFFDING_RADICAND_NUMERATOR_BPS_SQUARED,
        u64::from(completed_seed_blocks),
    );
    let margin = ceil_sqrt(radicand).min(u64::from(BASIS_POINTS_SCALE)) as u16;
    (
        center.saturating_sub(margin),
        center.saturating_add(margin).min(BASIS_POINTS_SCALE),
    )
}

fn ceil_div(numerator: u64, denominator: u64) -> u64 {
    numerator / denominator + u64::from(numerator % denominator != 0)
}

fn ceil_sqrt(value: u64) -> u64 {
    let floor = integer_sqrt(value);
    if floor.saturating_mul(floor) == value {
        floor
    } else {
        floor + 1
    }
}

fn integer_sqrt(value: u64) -> u64 {
    if value < 2 {
        return value;
    }
    let mut low = 1u64;
    let mut high = value.min(u32::MAX as u64 + 1);
    while low + 1 < high {
        let mid = low + (high - low) / 2;
        if mid <= value / mid {
            low = mid;
        } else {
            high = mid;
        }
    }
    low
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    use splendor_arena::{AgentCommand, AgentFault, ArenaOutcomeV1, ArenaPhase};
    use splendor_core::{GameResult, PlayerId, TerminalReason};

    use crate::{
        aggregate, expand_schedule, EvaluationAgentV1, EvaluationMatchRecordV1,
        EVALUATION_PLAN_FORMAT, EVALUATION_VERSION,
    };

    fn plan(seed_count: u64) -> EvaluationPlanV1 {
        plan_with_agents(seed_count, &["candidate", "champion"])
    }

    fn plan_with_agents(seed_count: u64, agent_ids: &[&str]) -> EvaluationPlanV1 {
        EvaluationPlanV1 {
            format: EVALUATION_PLAN_FORMAT.to_string(),
            version: EVALUATION_VERSION,
            evaluation_id: "m09-unit".to_string(),
            agents: agent_ids
                .iter()
                .map(|id| EvaluationAgentV1 {
                    id: (*id).to_string(),
                    command: AgentCommand {
                        program: PathBuf::from(format!("/bin/{id}")),
                        args: Vec::new(),
                    },
                })
                .collect(),
            game_seeds: (0..seed_count).collect(),
            handshake_timeout_ms: 1_000,
            move_timeout_ms: 2_000,
            shutdown_grace_ms: 1_000,
        }
    }

    fn gate(min_blocks: u32) -> PromotionGateV1 {
        PromotionGateV1 {
            format: PROMOTION_GATE_FORMAT.to_string(),
            version: PROMOTION_VERSION,
            promotion_id: "candidate-vs-champion".to_string(),
            candidate_agent_id: "candidate".to_string(),
            champion_agent_id: "champion".to_string(),
            confidence_bps: PROMOTION_CONFIDENCE_BPS,
            min_completed_seed_blocks: min_blocks,
            min_pairwise_score_lower_bound_bps: 5_000,
            max_aborted_matches: 0,
            max_candidate_faults: 0,
            max_move_timeout_ms: 2_000,
        }
    }

    fn report_with<F>(plan: &EvaluationPlanV1, outcome_for: F) -> EvaluationReportV1
    where
        F: Fn(u32, usize, usize) -> ArenaOutcomeV1,
    {
        let records = expand_schedule(plan)
            .unwrap()
            .iter()
            .map(|spec| {
                let candidate_seat = spec
                    .agent_ids_by_seat
                    .iter()
                    .position(|id| id == "candidate")
                    .unwrap();
                let champion_seat = spec
                    .agent_ids_by_seat
                    .iter()
                    .position(|id| id == "champion")
                    .unwrap();
                EvaluationMatchRecordV1 {
                    match_index: spec.match_index,
                    game_id: spec.arena_config.game_id.clone(),
                    seed_index: spec.seed_index,
                    rotation: spec.rotation,
                    agent_ids_by_seat: spec.agent_ids_by_seat.clone(),
                    outcome: outcome_for(spec.match_index, candidate_seat, champion_seat),
                }
            })
            .collect::<Vec<_>>();
        aggregate(plan, &records).unwrap()
    }

    fn completed(
        candidate_seat: usize,
        champion_seat: usize,
        candidate_wins: bool,
    ) -> ArenaOutcomeV1 {
        let mut ranks = vec![2u8; 2];
        let mut scores = vec![10u8; 2];
        let winner = if candidate_wins {
            ranks[candidate_seat] = 1;
            scores[candidate_seat] = 15;
            candidate_seat
        } else {
            ranks[champion_seat] = 1;
            scores[champion_seat] = 15;
            champion_seat
        };
        ArenaOutcomeV1::completed(
            GameResult {
                scores,
                ranks,
                winners: vec![PlayerId(winner as u8)],
                reason: TerminalReason::PrestigeThreshold,
            },
            30,
            "ab".repeat(32),
        )
    }

    #[test]
    fn undefeated_candidate_promotes_with_paired_seed_confidence() {
        let plan = plan(20);
        let report = report_with(&plan, |_, candidate, champion| {
            completed(candidate, champion, true)
        });
        let result = evaluate_promotion_v1(&plan, &report, &gate(20)).unwrap();

        assert_eq!(result.decision, PromotionDecisionV1::Promote);
        assert_eq!(result.pairwise.completed_seed_blocks, 20);
        assert_eq!(result.pairwise.completed_matches, 40);
        assert_eq!(result.pairwise.candidate_wins, 40);
        assert_eq!(result.pairwise.score_basis_points, 10_000);
        assert_eq!(result.pairwise.confidence_lower_bound_basis_points, 7_261);
        assert!(result.checks.all_pass());
    }

    #[test]
    fn even_candidate_is_rejected_by_confidence_bound() {
        let plan = plan(20);
        let report = report_with(&plan, |match_index, candidate, champion| {
            completed(candidate, champion, match_index % 2 == 0)
        });
        let result = evaluate_promotion_v1(&plan, &report, &gate(20)).unwrap();

        assert_eq!(result.pairwise.score_basis_points, 5_000);
        assert_eq!(result.pairwise.confidence_lower_bound_basis_points, 2_261);
        assert_eq!(result.decision, PromotionDecisionV1::Reject);
        assert!(!result.checks.pairwise_lower_bound_meets_threshold);
    }

    #[test]
    fn four_player_rotations_form_one_independent_block_per_seed() {
        let plan = plan_with_agents(20, &["candidate", "champion", "other-a", "other-b"]);
        let report = report_with(&plan, |_, candidate, champion| {
            let mut ranks = vec![4u8; 4];
            let mut scores = vec![5u8; 4];
            ranks[candidate] = 1;
            scores[candidate] = 15;
            ranks[champion] = 2;
            scores[champion] = 12;
            let mut next_rank = 3;
            for seat in 0..4 {
                if seat != candidate && seat != champion {
                    ranks[seat] = next_rank;
                    scores[seat] = 11 - next_rank;
                    next_rank += 1;
                }
            }
            ArenaOutcomeV1::completed(
                GameResult {
                    scores,
                    ranks,
                    winners: vec![PlayerId(candidate as u8)],
                    reason: TerminalReason::PrestigeThreshold,
                },
                30,
                "ab".repeat(32),
            )
        });
        let result = evaluate_promotion_v1(&plan, &report, &gate(20)).unwrap();

        assert_eq!(result.decision, PromotionDecisionV1::Promote);
        assert_eq!(result.pairwise.completed_seed_blocks, 20);
        assert_eq!(result.pairwise.completed_matches, 80);
        assert_eq!(result.pairwise.candidate_wins, 80);
        assert_eq!(result.pairwise.candidate_rank_sum, 80);
        assert_eq!(result.pairwise.champion_rank_sum, 160);
    }

    #[test]
    fn aborted_rotation_excludes_whole_seed_block_and_fails_reliability() {
        let plan = plan(20);
        let report = report_with(&plan, |match_index, candidate, champion| {
            if match_index == 0 {
                ArenaOutcomeV1::aborted(
                    candidate as u8,
                    ArenaPhase::ActionRequest,
                    AgentFault::ActionTimeout,
                    Some(1),
                    0,
                )
            } else {
                completed(candidate, champion, true)
            }
        });
        let result = evaluate_promotion_v1(&plan, &report, &gate(20)).unwrap();

        assert_eq!(result.pairwise.completed_seed_blocks, 19);
        assert_eq!(result.pairwise.excluded_seed_blocks, 1);
        assert_eq!(result.pairwise.completed_matches, 38);
        assert_eq!(result.aborted_matches, 1);
        assert_eq!(result.candidate_faults, 1);
        assert_eq!(result.decision, PromotionDecisionV1::Reject);
        assert!(!result.checks.sufficient_completed_seed_blocks);
        assert!(!result.checks.aborted_matches_within_limit);
        assert!(!result.checks.candidate_faults_within_limit);
    }

    #[test]
    fn tampered_report_is_rejected_before_gate_evaluation() {
        let plan = plan(20);
        let mut report = report_with(&plan, |_, candidate, champion| {
            completed(candidate, champion, true)
        });
        report.plan_hash = "00".repeat(32);
        assert!(matches!(
            evaluate_promotion_v1(&plan, &report, &gate(20)),
            Err(EvaluationError::EvaluationReportMismatch)
        ));
    }

    #[test]
    fn gate_hash_and_report_serialization_are_deterministic() {
        let gate = gate(20);
        let first = promotion_gate_hash_v1(&gate).unwrap();
        let second = promotion_gate_hash_v1(&gate).unwrap();
        assert_eq!(first, second);
        assert_eq!(first.as_str().len(), 64);

        let plan = plan(20);
        let report = report_with(&plan, |_, candidate, champion| {
            completed(candidate, champion, true)
        });
        let promotion = evaluate_promotion_v1(&plan, &report, &gate).unwrap();
        let json = serde_json::to_string(&promotion).unwrap();
        let round_trip: PromotionReportV1 = serde_json::from_str(&json).unwrap();
        assert_eq!(promotion, round_trip);
        let noisy = json.trim_end_matches('}').to_string() + ",\"extra\":1}";
        assert!(serde_json::from_str::<PromotionReportV1>(&noisy).is_err());
    }

    #[test]
    fn integer_confidence_math_is_frozen_and_bounded() {
        assert_eq!(confidence_interval_95(10_000, 20), (7_261, 10_000));
        assert_eq!(confidence_interval_95(5_000, 20), (2_261, 7_739));
        assert_eq!(confidence_interval_95(0, 0), (0, 10_000));
        assert_eq!(ceil_sqrt(0), 0);
        assert_eq!(ceil_sqrt(1), 1);
        assert_eq!(ceil_sqrt(2), 2);
        assert_eq!(ceil_sqrt(9), 3);
    }
}
