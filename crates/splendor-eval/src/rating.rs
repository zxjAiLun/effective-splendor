//! Pure 1v1 round-robin planning and rating, version 1.
//!
//! The rating layer deliberately consumes canonical [`EvaluationReportV1`]
//! artifacts rather than raw win counters. Each pair report is rebuilt from
//! its embedded evaluation plan before it contributes to the leaderboard.
//! This preserves the M11 provenance chain while adding two distinct views:
//!
//! - `live_elo`: conventional sequential Elo in frozen tournament order;
//! - `official_elo`: order-independent batch Bradley-Terry strength mapped to
//!   the familiar Elo scale (1500 centre, 400 points per tenfold odds).

use std::collections::{HashMap, HashSet};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use splendor_arena::{AgentCommand, ArenaOutcomeV1};

use crate::{
    aggregate, evaluation_plan_hash_v1, EvaluationAgentV1, EvaluationPlanV1, EvaluationReportV1,
    EVALUATION_PLAN_FORMAT, EVALUATION_VERSION,
};

pub const RATING_REGISTRY_FORMAT: &str = "effective-splendor-rating-registry";
pub const RATING_CONFIG_FORMAT: &str = "effective-splendor-rating-config";
pub const ROUND_ROBIN_PLAN_FORMAT: &str = "effective-splendor-round-robin-plan";
pub const RATING_REPORT_FORMAT: &str = "effective-splendor-rating-report";
pub const RATING_VERSION: u32 = 1;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AgentClassV1 {
    Baseline,
    Search,
    Checkpoint,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RatedAgentV1 {
    pub id: String,
    pub display_name: String,
    pub class: AgentClassV1,
    pub policy_version: String,
    pub model_version: Option<String>,
    pub checkpoint_hash: Option<String>,
    pub runtime_name: String,
    pub runtime_version: String,
    pub command: AgentCommand,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RatingRegistryV1 {
    pub format: String,
    pub version: u32,
    pub registry_id: String,
    pub agents: Vec<RatedAgentV1>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RatingConfigV1 {
    pub format: String,
    pub version: u32,
    pub tournament_id: String,
    pub participant_ids: Vec<String>,
    pub game_seeds: Vec<u64>,
    pub handshake_timeout_ms: u64,
    pub move_timeout_ms: u64,
    pub shutdown_grace_ms: u64,
    pub initial_elo: i32,
    pub live_k_factor: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct PairEvaluationV1 {
    pub pair_index: u32,
    pub agent_a: String,
    pub agent_b: String,
    pub evaluation_plan_hash: String,
    pub evaluation_plan: EvaluationPlanV1,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RoundRobinPlanV1 {
    pub format: String,
    pub version: u32,
    pub tournament_id: String,
    pub registry_hash: String,
    pub initial_elo: i32,
    pub live_k_factor: u32,
    pub participants: Vec<RatedAgentV1>,
    pub pairs: Vec<PairEvaluationV1>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HeadToHeadV1 {
    pub agent_a: String,
    pub agent_b: String,
    pub completed: u32,
    pub aborted: u32,
    pub wins_a: u32,
    pub ties: u32,
    pub wins_b: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RatingAgentResultV1 {
    pub rank: u32,
    pub agent_id: String,
    pub display_name: String,
    pub class: AgentClassV1,
    pub completed: u32,
    pub aborted: u32,
    pub wins: u32,
    pub ties: u32,
    pub losses: u32,
    pub live_elo: i32,
    pub official_elo: i32,
    pub provisional: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RatingReportV1 {
    pub format: String,
    pub version: u32,
    pub tournament_id: String,
    pub registry_hash: String,
    pub round_robin_plan_hash: String,
    pub scheduled_matches: u32,
    pub completed_matches: u32,
    pub aborted_matches: u32,
    pub agents: Vec<RatingAgentResultV1>,
    pub head_to_head: Vec<HeadToHeadV1>,
    pub pair_evaluation_report_hashes: Vec<String>,
}

fn check_text(field: &str, value: &str) -> Result<(), String> {
    if value.trim().is_empty() {
        return Err(format!("{field} must not be empty"));
    }
    if value.len() > 128 || value.as_bytes().iter().any(|b| *b < 0x20) {
        return Err(format!(
            "{field} is too long or contains a control character"
        ));
    }
    Ok(())
}

fn check_hash(field: &str, value: &str) -> Result<(), String> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|b| b.is_ascii_hexdigit() && !b.is_ascii_uppercase())
    {
        return Err(format!("{field} must be 64 lowercase hex characters"));
    }
    Ok(())
}

impl RatingRegistryV1 {
    pub fn validate(&self) -> Result<(), String> {
        if self.format != RATING_REGISTRY_FORMAT || self.version != RATING_VERSION {
            return Err("unsupported rating registry format/version".to_string());
        }
        check_text("registry_id", &self.registry_id)?;
        if self.agents.len() < 2 {
            return Err("rating registry requires at least two agents".to_string());
        }
        let mut ids = HashSet::new();
        for agent in &self.agents {
            check_text("agent id", &agent.id)?;
            check_text("display_name", &agent.display_name)?;
            check_text("policy_version", &agent.policy_version)?;
            check_text("runtime_name", &agent.runtime_name)?;
            check_text("runtime_version", &agent.runtime_version)?;
            if !ids.insert(agent.id.as_str()) {
                return Err(format!("duplicate agent id '{}'", agent.id));
            }
            if agent.command.program.as_os_str().is_empty() {
                return Err(format!("agent '{}' has an empty command program", agent.id));
            }
            if let Some(hash) = &agent.checkpoint_hash {
                check_hash("checkpoint_hash", hash)?;
            }
            if agent.class == AgentClassV1::Checkpoint && agent.checkpoint_hash.is_none() {
                return Err(format!(
                    "checkpoint agent '{}' must bind checkpoint_hash",
                    agent.id
                ));
            }
        }
        Ok(())
    }
}

impl RatingConfigV1 {
    pub fn validate(&self) -> Result<(), String> {
        if self.format != RATING_CONFIG_FORMAT || self.version != RATING_VERSION {
            return Err("unsupported rating config format/version".to_string());
        }
        check_text("tournament_id", &self.tournament_id)?;
        if self.participant_ids.len() < 2 {
            return Err("rating config requires at least two participants".to_string());
        }
        if self.game_seeds.is_empty() {
            return Err("game_seeds must not be empty".to_string());
        }
        if self.initial_elo < 100 || self.initial_elo > 4000 {
            return Err("initial_elo must be between 100 and 4000".to_string());
        }
        if self.live_k_factor == 0 || self.live_k_factor > 256 {
            return Err("live_k_factor must be in 1..=256".to_string());
        }
        let mut ids = HashSet::new();
        for id in &self.participant_ids {
            check_text("participant id", id)?;
            if !ids.insert(id.as_str()) {
                return Err(format!("duplicate participant id '{id}'"));
            }
        }
        Ok(())
    }
}

pub fn rating_registry_hash_v1(registry: &RatingRegistryV1) -> Result<String, String> {
    registry.validate()?;
    hash_json(registry)
}

pub fn build_round_robin_plan_v1(
    registry: &RatingRegistryV1,
    config: &RatingConfigV1,
) -> Result<RoundRobinPlanV1, String> {
    registry.validate()?;
    config.validate()?;
    let by_id: HashMap<&str, &RatedAgentV1> = registry
        .agents
        .iter()
        .map(|agent| (agent.id.as_str(), agent))
        .collect();
    let participants: Vec<RatedAgentV1> = config
        .participant_ids
        .iter()
        .map(|id| {
            by_id
                .get(id.as_str())
                .copied()
                .cloned()
                .ok_or_else(|| format!("unknown participant id '{id}'"))
        })
        .collect::<Result<_, _>>()?;

    let mut pairs = Vec::new();
    for i in 0..participants.len() {
        for j in (i + 1)..participants.len() {
            let pair_index = pairs.len() as u32;
            let plan = EvaluationPlanV1 {
                format: EVALUATION_PLAN_FORMAT.to_string(),
                version: EVALUATION_VERSION,
                evaluation_id: format!("{}-p{pair_index:04}", config.tournament_id),
                agents: vec![
                    EvaluationAgentV1 {
                        id: participants[i].id.clone(),
                        command: participants[i].command.clone(),
                    },
                    EvaluationAgentV1 {
                        id: participants[j].id.clone(),
                        command: participants[j].command.clone(),
                    },
                ],
                game_seeds: config.game_seeds.clone(),
                handshake_timeout_ms: config.handshake_timeout_ms,
                move_timeout_ms: config.move_timeout_ms,
                shutdown_grace_ms: config.shutdown_grace_ms,
            };
            let evaluation_plan_hash = evaluation_plan_hash_v1(&plan)
                .map_err(|e| e.to_string())?
                .to_string();
            pairs.push(PairEvaluationV1 {
                pair_index,
                agent_a: participants[i].id.clone(),
                agent_b: participants[j].id.clone(),
                evaluation_plan_hash,
                evaluation_plan: plan,
            });
        }
    }
    let plan = RoundRobinPlanV1 {
        format: ROUND_ROBIN_PLAN_FORMAT.to_string(),
        version: RATING_VERSION,
        tournament_id: config.tournament_id.clone(),
        registry_hash: rating_registry_hash_v1(registry)?,
        initial_elo: config.initial_elo,
        live_k_factor: config.live_k_factor,
        participants,
        pairs,
    };
    plan.validate()?;
    Ok(plan)
}

impl RoundRobinPlanV1 {
    pub fn validate(&self) -> Result<(), String> {
        if self.format != ROUND_ROBIN_PLAN_FORMAT || self.version != RATING_VERSION {
            return Err("unsupported round-robin plan format/version".to_string());
        }
        check_text("tournament_id", &self.tournament_id)?;
        check_hash("registry_hash", &self.registry_hash)?;
        if self.participants.len() < 2 {
            return Err("round-robin plan requires at least two participants".to_string());
        }
        if self.initial_elo < 100 || self.initial_elo > 4000 {
            return Err("initial_elo must be between 100 and 4000".to_string());
        }
        if self.live_k_factor == 0 || self.live_k_factor > 256 {
            return Err("live_k_factor must be in 1..=256".to_string());
        }
        RatingRegistryV1 {
            format: RATING_REGISTRY_FORMAT.to_string(),
            version: RATING_VERSION,
            registry_id: self.tournament_id.clone(),
            agents: self.participants.clone(),
        }
        .validate()?;
        let expected_pairs = self.participants.len() * (self.participants.len() - 1) / 2;
        if self.pairs.len() != expected_pairs {
            return Err(format!(
                "expected {expected_pairs} pairs, got {}",
                self.pairs.len()
            ));
        }
        let mut expected_pair_agents = Vec::with_capacity(expected_pairs);
        for i in 0..self.participants.len() {
            for j in (i + 1)..self.participants.len() {
                expected_pair_agents.push((&self.participants[i], &self.participants[j]));
            }
        }
        let reference_plan = &self.pairs[0].evaluation_plan;
        for (index, pair) in self.pairs.iter().enumerate() {
            if pair.pair_index != index as u32 {
                return Err("pair_index must be dense and canonical".to_string());
            }
            let actual = evaluation_plan_hash_v1(&pair.evaluation_plan)
                .map_err(|e| e.to_string())?
                .to_string();
            if actual != pair.evaluation_plan_hash {
                return Err(format!(
                    "pair {} evaluation plan hash mismatch",
                    pair.pair_index
                ));
            }
            if pair.evaluation_plan.agents.len() != 2
                || pair.evaluation_plan.agents[0].id != pair.agent_a
                || pair.evaluation_plan.agents[1].id != pair.agent_b
            {
                return Err(format!("pair {} agent binding mismatch", pair.pair_index));
            }
            let (expected_a, expected_b) = expected_pair_agents[index];
            if pair.agent_a != expected_a.id || pair.agent_b != expected_b.id {
                return Err(format!(
                    "pair {} is not the canonical unordered participant pair",
                    pair.pair_index
                ));
            }
            let expected_id = format!("{}-p{:04}", self.tournament_id, pair.pair_index);
            if pair.evaluation_plan.evaluation_id != expected_id
                || pair.evaluation_plan.game_seeds != reference_plan.game_seeds
                || pair.evaluation_plan.handshake_timeout_ms != reference_plan.handshake_timeout_ms
                || pair.evaluation_plan.move_timeout_ms != reference_plan.move_timeout_ms
                || pair.evaluation_plan.shutdown_grace_ms != reference_plan.shutdown_grace_ms
            {
                return Err(format!(
                    "pair {} does not share the canonical tournament schedule",
                    pair.pair_index
                ));
            }
            for (seat, expected) in [&expected_a.command, &expected_b.command]
                .into_iter()
                .enumerate()
            {
                let actual = serde_json::to_vec(&pair.evaluation_plan.agents[seat].command)
                    .map_err(|e| e.to_string())?;
                let expected = serde_json::to_vec(expected).map_err(|e| e.to_string())?;
                if actual != expected {
                    return Err(format!(
                        "pair {} command does not match its registered participant",
                        pair.pair_index
                    ));
                }
            }
        }
        Ok(())
    }
}

pub fn round_robin_plan_hash_v1(plan: &RoundRobinPlanV1) -> Result<String, String> {
    plan.validate()?;
    hash_json(plan)
}

pub fn build_rating_report_v1(
    plan: &RoundRobinPlanV1,
    reports: &[EvaluationReportV1],
) -> Result<RatingReportV1, String> {
    plan.validate()?;
    if reports.len() != plan.pairs.len() {
        return Err(format!(
            "expected {} pair reports, got {}",
            plan.pairs.len(),
            reports.len()
        ));
    }
    let index: HashMap<&str, usize> = plan
        .participants
        .iter()
        .enumerate()
        .map(|(i, a)| (a.id.as_str(), i))
        .collect();
    let mut live = vec![plan.initial_elo as f64; plan.participants.len()];
    let mut completed = vec![0u32; plan.participants.len()];
    let mut aborted = vec![0u32; plan.participants.len()];
    let mut wins = vec![0u32; plan.participants.len()];
    let mut ties = vec![0u32; plan.participants.len()];
    let mut losses = vec![0u32; plan.participants.len()];
    let mut head_to_head = Vec::new();
    let mut report_hashes = Vec::new();

    for (pair, report) in plan.pairs.iter().zip(reports) {
        let canonical =
            aggregate(&pair.evaluation_plan, &report.records).map_err(|e| e.to_string())?;
        if &canonical != report {
            return Err(format!("pair {} report is not canonical", pair.pair_index));
        }
        report_hashes.push(hash_json(report)?);
        let ia = index[pair.agent_a.as_str()];
        let ib = index[pair.agent_b.as_str()];
        let mut h = HeadToHeadV1 {
            agent_a: pair.agent_a.clone(),
            agent_b: pair.agent_b.clone(),
            completed: 0,
            aborted: 0,
            wins_a: 0,
            ties: 0,
            wins_b: 0,
        };
        for record in &report.records {
            match &record.outcome {
                ArenaOutcomeV1::Aborted { .. } => {
                    h.aborted += 1;
                    aborted[ia] += 1;
                    aborted[ib] += 1;
                }
                ArenaOutcomeV1::Completed { result, .. } => {
                    h.completed += 1;
                    completed[ia] += 1;
                    completed[ib] += 1;
                    let a_seat = record
                        .agent_ids_by_seat
                        .iter()
                        .position(|id| id == &pair.agent_a)
                        .ok_or("pair record missing agent_a")?;
                    let b_seat = record
                        .agent_ids_by_seat
                        .iter()
                        .position(|id| id == &pair.agent_b)
                        .ok_or("pair record missing agent_b")?;
                    let a_won = result.winners.iter().any(|winner| winner.index() == a_seat);
                    let b_won = result.winners.iter().any(|winner| winner.index() == b_seat);
                    let score_a = match (a_won, b_won) {
                        (true, false) => {
                            h.wins_a += 1;
                            wins[ia] += 1;
                            losses[ib] += 1;
                            1.0
                        }
                        (false, true) => {
                            h.wins_b += 1;
                            wins[ib] += 1;
                            losses[ia] += 1;
                            0.0
                        }
                        (true, true) => {
                            h.ties += 1;
                            ties[ia] += 1;
                            ties[ib] += 1;
                            0.5
                        }
                        (false, false) => return Err("completed result has no winner".to_string()),
                    };
                    let expected_a = 1.0 / (1.0 + 10f64.powf((live[ib] - live[ia]) / 400.0));
                    let delta = plan.live_k_factor as f64 * (score_a - expected_a);
                    live[ia] += delta;
                    live[ib] -= delta;
                }
            }
        }
        head_to_head.push(h);
    }

    let official = official_batch_elo(plan, &head_to_head, &index);
    let mut agents: Vec<RatingAgentResultV1> = plan
        .participants
        .iter()
        .enumerate()
        .map(|(i, agent)| RatingAgentResultV1 {
            rank: 0,
            agent_id: agent.id.clone(),
            display_name: agent.display_name.clone(),
            class: agent.class,
            completed: completed[i],
            aborted: aborted[i],
            wins: wins[i],
            ties: ties[i],
            losses: losses[i],
            live_elo: live[i].round() as i32,
            official_elo: official[i],
            provisional: completed[i] < 20,
        })
        .collect();
    agents.sort_by(|a, b| {
        b.official_elo
            .cmp(&a.official_elo)
            .then_with(|| b.completed.cmp(&a.completed))
            .then_with(|| a.agent_id.cmp(&b.agent_id))
    });
    for (i, agent) in agents.iter_mut().enumerate() {
        agent.rank = i as u32 + 1;
    }
    let completed_matches = head_to_head.iter().map(|h| h.completed).sum();
    let aborted_matches = head_to_head.iter().map(|h| h.aborted).sum();
    Ok(RatingReportV1 {
        format: RATING_REPORT_FORMAT.to_string(),
        version: RATING_VERSION,
        tournament_id: plan.tournament_id.clone(),
        registry_hash: plan.registry_hash.clone(),
        round_robin_plan_hash: round_robin_plan_hash_v1(plan)?,
        scheduled_matches: completed_matches + aborted_matches,
        completed_matches,
        aborted_matches,
        agents,
        head_to_head,
        pair_evaluation_report_hashes: report_hashes,
    })
}

fn official_batch_elo(
    plan: &RoundRobinPlanV1,
    head: &[HeadToHeadV1],
    index: &HashMap<&str, usize>,
) -> Vec<i32> {
    let n = plan.participants.len();
    let mut strength = vec![0.0f64; n];
    // Damped diagonal Newton updates on the regularised Bradley-Terry log likelihood.
    // The ridge gives finite ratings to undefeated agents while centring keeps the
    // population mean exactly at the configured initial rating.
    for _ in 0..512 {
        let mut gradient = vec![0.0f64; n];
        let mut curvature = vec![0.01f64; n];
        for h in head {
            if h.completed == 0 {
                continue;
            }
            let i = index[h.agent_a.as_str()];
            let j = index[h.agent_b.as_str()];
            let games = h.completed as f64;
            let score_i = h.wins_a as f64 + 0.5 * h.ties as f64;
            let p = 1.0 / (1.0 + (strength[j] - strength[i]).exp());
            let g = score_i - games * p;
            let c = games * p * (1.0 - p);
            gradient[i] += g;
            gradient[j] -= g;
            curvature[i] += c;
            curvature[j] += c;
        }
        for i in 0..n {
            gradient[i] -= 0.01 * strength[i];
        }
        let max_step = (0..n)
            .map(|i| (0.5 * gradient[i] / curvature[i]).abs())
            .fold(0.0, f64::max);
        for i in 0..n {
            strength[i] += 0.5 * gradient[i] / curvature[i];
        }
        let mean = strength.iter().sum::<f64>() / n as f64;
        for value in &mut strength {
            *value -= mean;
        }
        if max_step < 1e-10 {
            break;
        }
    }
    let scale = 400.0 / std::f64::consts::LN_10;
    strength
        .into_iter()
        .map(|s| (plan.initial_elo as f64 + scale * s).round() as i32)
        .collect()
}

fn hash_json<T: Serialize>(value: &T) -> Result<String, String> {
    let json = serde_json::to_vec(value).map_err(|e| e.to_string())?;
    let mut hasher = Sha256::new();
    hasher.update(json);
    Ok(hex::encode(hasher.finalize()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use splendor_arena::ArenaOutcomeV1;
    use splendor_core::{GameResult, PlayerId, TerminalReason};
    use std::path::PathBuf;

    fn agent(id: &str) -> RatedAgentV1 {
        RatedAgentV1 {
            id: id.into(),
            display_name: id.into(),
            class: AgentClassV1::Baseline,
            policy_version: "v1".into(),
            model_version: None,
            checkpoint_hash: None,
            runtime_name: "test".into(),
            runtime_version: "1".into(),
            command: AgentCommand {
                program: PathBuf::from("agent"),
                args: vec![id.into()],
            },
        }
    }

    fn fixture() -> (RatingRegistryV1, RatingConfigV1) {
        (
            RatingRegistryV1 {
                format: RATING_REGISTRY_FORMAT.into(),
                version: 1,
                registry_id: "unit".into(),
                agents: vec![agent("A"), agent("B"), agent("C")],
            },
            RatingConfigV1 {
                format: RATING_CONFIG_FORMAT.into(),
                version: 1,
                tournament_id: "unit-cup".into(),
                participant_ids: vec!["A".into(), "B".into(), "C".into()],
                game_seeds: vec![7],
                handshake_timeout_ms: 1000,
                move_timeout_ms: 1000,
                shutdown_grace_ms: 1000,
                initial_elo: 1500,
                live_k_factor: 32,
            },
        )
    }

    fn report_for(pair: &PairEvaluationV1, winner_id: &str) -> EvaluationReportV1 {
        let specs = crate::expand_schedule(&pair.evaluation_plan).unwrap();
        let records = specs
            .into_iter()
            .map(|spec| {
                let winner = spec
                    .agent_ids_by_seat
                    .iter()
                    .position(|id| id == winner_id)
                    .unwrap();
                crate::EvaluationMatchRecordV1 {
                    match_index: spec.match_index,
                    game_id: spec.arena_config.game_id,
                    seed_index: spec.seed_index,
                    rotation: spec.rotation,
                    agent_ids_by_seat: spec.agent_ids_by_seat,
                    outcome: ArenaOutcomeV1::Completed {
                        result: GameResult {
                            scores: if winner == 0 {
                                vec![15, 8]
                            } else {
                                vec![8, 15]
                            },
                            ranks: if winner == 0 { vec![1, 2] } else { vec![2, 1] },
                            winners: vec![PlayerId(winner as u8)],
                            reason: TerminalReason::PrestigeThreshold,
                        },
                        completed_plies: 1,
                        replay_final_hash: "0".repeat(64),
                    },
                }
            })
            .collect::<Vec<_>>();
        aggregate(&pair.evaluation_plan, &records).unwrap()
    }

    #[test]
    fn round_robin_has_every_pair_and_balanced_pair_plans() {
        let (registry, config) = fixture();
        let plan = build_round_robin_plan_v1(&registry, &config).unwrap();
        assert_eq!(plan.pairs.len(), 3);
        assert!(plan
            .pairs
            .iter()
            .all(|p| p.evaluation_plan.game_seeds == vec![7]));
        assert_eq!(
            crate::expand_schedule(&plan.pairs[0].evaluation_plan)
                .unwrap()
                .len(),
            2
        );
    }

    #[test]
    fn official_rating_is_order_independent_and_ranks_dominant_agent() {
        let (registry, config) = fixture();
        let plan = build_round_robin_plan_v1(&registry, &config).unwrap();
        let reports = vec![
            report_for(&plan.pairs[0], "A"),
            report_for(&plan.pairs[1], "A"),
            report_for(&plan.pairs[2], "B"),
        ];
        let result = build_rating_report_v1(&plan, &reports).unwrap();
        assert_eq!(result.agents[0].agent_id, "A");
        assert!(result.agents[0].official_elo > result.agents[1].official_elo);
        assert_eq!(result.completed_matches, 6);
    }

    #[test]
    fn tampered_pair_report_is_rejected() {
        let (registry, config) = fixture();
        let plan = build_round_robin_plan_v1(&registry, &config).unwrap();
        let mut reports = plan
            .pairs
            .iter()
            .map(|p| report_for(p, &p.agent_a))
            .collect::<Vec<_>>();
        reports[0].plan_hash = "f".repeat(64);
        assert!(build_rating_report_v1(&plan, &reports)
            .unwrap_err()
            .contains("not canonical"));
    }

    #[test]
    fn duplicated_pair_or_drifted_schedule_is_rejected() {
        let (registry, config) = fixture();
        let mut plan = build_round_robin_plan_v1(&registry, &config).unwrap();
        plan.pairs[1].agent_a = plan.pairs[0].agent_a.clone();
        plan.pairs[1].agent_b = plan.pairs[0].agent_b.clone();
        plan.pairs[1].evaluation_plan.agents = plan.pairs[0].evaluation_plan.agents.clone();
        plan.pairs[1].evaluation_plan_hash =
            evaluation_plan_hash_v1(&plan.pairs[1].evaluation_plan)
                .unwrap()
                .to_string();
        assert!(plan.validate().unwrap_err().contains("canonical unordered"));

        let (registry, config) = fixture();
        let mut drifted = build_round_robin_plan_v1(&registry, &config).unwrap();
        drifted.pairs[1].evaluation_plan.game_seeds[0] = 999;
        drifted.pairs[1].evaluation_plan_hash =
            evaluation_plan_hash_v1(&drifted.pairs[1].evaluation_plan)
                .unwrap()
                .to_string();
        assert!(drifted
            .validate()
            .unwrap_err()
            .contains("share the canonical"));
    }
}
