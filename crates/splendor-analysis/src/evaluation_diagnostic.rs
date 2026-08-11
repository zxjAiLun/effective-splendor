use std::collections::HashMap;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use splendor_arena::ArenaOutcomeV1;
use splendor_belief::build_information_set_v1;
use splendor_core::{visible_events, Audience, PlayerId, Ruleset};
use splendor_eval::{
    aggregate, evaluation_plan_hash_v1, expand_schedule, EvaluationPlanV1, EvaluationReportV1,
};
use splendor_learning::{model_checkpoint_hash_v1, PolicyValueCheckpointV1, PolicyValueModelV1};
use splendor_neural_search::{
    search_neural_ismcts_ablation_v1, NeuralAblationModeV1, NeuralIsmctsConfigV1,
};
use splendor_replay::{replay_document_hash_v1, verify_replay_trace, ReplayV1};

use crate::{analysis_trace_hash_v1, analyze_replay_neural_v1, AnalysisError, AnalysisTraceV1};

pub const ANALYSIS_EVALUATION_FORMAT: &str = "effective-splendor-neural-evaluation-diagnostic";
pub const ANALYSIS_EVALUATION_VERSION: u32 = 1;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SeatOutcomeSummaryV1 {
    pub seat: u8,
    pub matches: u32,
    pub wins: u32,
    pub ties: u32,
    pub losses: u32,
    pub score_sum: u64,
    pub rank_sum: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SeedBlockSummaryV1 {
    pub blocks: u32,
    pub candidate_wins_zero: u32,
    pub candidate_wins_one: u32,
    pub candidate_wins_two: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CandidateOutcomeSummaryV1 {
    pub matches: u32,
    pub wins: u32,
    pub ties: u32,
    pub losses: u32,
    pub score_sum: u64,
    pub rank_sum: u64,
    pub completed_plies_sum: u64,
    pub by_seat: Vec<SeatOutcomeSummaryV1>,
    pub seed_blocks: SeedBlockSummaryV1,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AgentDecisionMetricsV1 {
    pub agent_id: String,
    pub frames: u32,
    pub legal_actions_sum: u64,
    pub visited_actions_sum: u64,
    pub full_matches_recorded: u32,
    pub direct_policy_matches_recorded: u32,
    pub value_only_matches_recorded: u32,
    pub policy_only_matches_recorded: u32,
    pub neutral_matches_recorded: u32,
    pub full_matches_direct_policy: u32,
    pub full_matches_value_only: u32,
    pub full_matches_policy_only: u32,
    pub full_matches_neutral: u32,
    pub full_selected_top_prior: u32,
    pub selected_prior_rank_sum: u64,
    pub selected_prior_micros_sum: u64,
    pub top_prior_micros_sum: u64,
    pub top_visit_count_sum: u64,
    pub chosen_q_micros_sum: u64,
    pub best_q_minus_chosen_q_micros_sum: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct AnalyzedEvaluationMatchV1 {
    pub match_index: u32,
    pub seed_index: u32,
    pub rotation: u8,
    pub seed: u64,
    pub agent_ids_by_seat: Vec<String>,
    pub replay_document_hash: String,
    pub analysis_trace_hash: String,
    pub analysis_relative_path: String,
    pub frame_count: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NeuralEvaluationDiagnosticV1 {
    pub format: String,
    pub version: u32,
    pub evaluation_id: String,
    pub evaluation_plan_hash: String,
    pub evaluation_report_hash: String,
    pub candidate_agent_id: String,
    pub champion_agent_id: String,
    pub checkpoint_hash: String,
    pub config: NeuralIsmctsConfigV1,
    pub outcome: CandidateOutcomeSummaryV1,
    pub total_frames: u32,
    pub decision_metrics: Vec<AgentDecisionMetricsV1>,
    pub matches: Vec<AnalyzedEvaluationMatchV1>,
}

impl NeuralEvaluationDiagnosticV1 {
    pub fn validate(&self) -> Result<(), AnalysisError> {
        if self.format != ANALYSIS_EVALUATION_FORMAT
            || self.version != ANALYSIS_EVALUATION_VERSION
            || self.evaluation_id.trim().is_empty()
            || self.candidate_agent_id == self.champion_agent_id
            || self.checkpoint_hash != self.config.expected_checkpoint_hash
        {
            return Err(invalid("identity or format binding is invalid"));
        }
        self.config
            .validate()
            .map_err(|error| invalid(error.to_string()))?;
        for hash in [
            &self.evaluation_plan_hash,
            &self.evaluation_report_hash,
            &self.checkpoint_hash,
        ] {
            validate_hash(hash)?;
        }
        if self.matches.is_empty()
            || self.outcome.matches != self.matches.len() as u32
            || self.outcome.wins + self.outcome.ties + self.outcome.losses != self.outcome.matches
            || self.decision_metrics.len() != 2
            || self
                .decision_metrics
                .iter()
                .map(|entry| entry.frames)
                .sum::<u32>()
                != self.total_frames
        {
            return Err(invalid("aggregate counts are inconsistent"));
        }
        for (index, entry) in self.matches.iter().enumerate() {
            if entry.match_index != index as u32 || entry.frame_count == 0 {
                return Err(invalid("match indices or frame counts are invalid"));
            }
            validate_hash(&entry.replay_document_hash)?;
            validate_hash(&entry.analysis_trace_hash)?;
            if entry.analysis_relative_path
                != format!("matches/match-{:06}.analysis.json", entry.match_index)
            {
                return Err(invalid("analysis sidecar path is not canonical"));
            }
        }
        for entry in &self.decision_metrics {
            if entry.frames == 0
                || entry.full_matches_recorded > entry.frames
                || entry.direct_policy_matches_recorded > entry.frames
                || entry.value_only_matches_recorded > entry.frames
                || entry.policy_only_matches_recorded > entry.frames
                || entry.neutral_matches_recorded > entry.frames
            {
                return Err(invalid("decision metric counts are invalid"));
            }
        }
        Ok(())
    }
}

pub struct EvaluationDiagnosticOutputV1 {
    pub diagnostic: NeuralEvaluationDiagnosticV1,
    pub traces: Vec<AnalysisTraceV1>,
}

#[allow(clippy::too_many_arguments)]
pub fn analyze_evaluation_neural_v1(
    plan: &EvaluationPlanV1,
    report: &EvaluationReportV1,
    replays: &[(u32, ReplayV1)],
    checkpoint: &PolicyValueCheckpointV1,
    config: &NeuralIsmctsConfigV1,
    candidate_agent_id: &str,
    champion_agent_id: &str,
) -> Result<EvaluationDiagnosticOutputV1, AnalysisError> {
    plan.validate()
        .map_err(|error| evaluation(error.to_string()))?;
    let canonical_report =
        aggregate(plan, &report.records).map_err(|error| evaluation(error.to_string()))?;
    if &canonical_report != report {
        return Err(evaluation("evaluation report is not canonical"));
    }
    if plan.agents.len() != 2
        || !plan
            .agents
            .iter()
            .any(|agent| agent.id == candidate_agent_id)
        || !plan
            .agents
            .iter()
            .any(|agent| agent.id == champion_agent_id)
        || candidate_agent_id == champion_agent_id
    {
        return Err(evaluation(
            "diagnostic requires distinct candidate/champion ids in a two-agent plan",
        ));
    }
    config
        .validate()
        .map_err(|error| AnalysisError::Learning(error.to_string()))?;
    let checkpoint_hash = model_checkpoint_hash_v1(checkpoint)
        .map_err(|error| AnalysisError::Learning(error.to_string()))?;
    if checkpoint_hash != config.expected_checkpoint_hash {
        return Err(AnalysisError::Learning(format!(
            "checkpoint hash mismatch: expected {}, found {checkpoint_hash}",
            config.expected_checkpoint_hash
        )));
    }
    let model = PolicyValueModelV1::from_checkpoint(checkpoint.clone())
        .map_err(|error| AnalysisError::Learning(error.to_string()))?;
    let specs = expand_schedule(plan).map_err(|error| evaluation(error.to_string()))?;
    if replays.len() != specs.len() {
        return Err(evaluation(format!(
            "expected {} replays, found {}",
            specs.len(),
            replays.len()
        )));
    }
    let replay_by_index = replays
        .iter()
        .map(|(match_index, replay)| (*match_index, replay))
        .collect::<HashMap<_, _>>();
    if replay_by_index.len() != replays.len() {
        return Err(evaluation("duplicate replay match index"));
    }

    let mut metrics = vec![
        empty_metrics(candidate_agent_id),
        empty_metrics(champion_agent_id),
    ];
    let mut outcome = empty_outcome();
    let mut wins_by_seed = vec![0u8; plan.game_seeds.len()];
    let mut traces = Vec::with_capacity(specs.len());
    let mut matches = Vec::with_capacity(specs.len());
    let mut total_frames = 0u32;

    for (record, spec) in report.records.iter().zip(&specs) {
        let replay = replay_by_index
            .get(&spec.match_index)
            .ok_or_else(|| evaluation(format!("missing replay {}", spec.match_index)))?;
        bind_match(record, spec, replay)?;
        accumulate_outcome(&mut outcome, &mut wins_by_seed, record, candidate_agent_id)?;
        let trace = analyze_replay_neural_v1(replay, checkpoint, config)?;
        let verified = verify_replay_trace(replay)
            .map_err(|error| AnalysisError::Replay(error.to_string()))?;
        if verified.positions.len() != trace.frames.len() {
            return Err(evaluation("trace and verified replay lengths differ"));
        }
        for (position, frame) in verified.positions.iter().zip(&trace.frames) {
            let seat = frame.actor.index();
            let agent_id = record
                .agent_ids_by_seat
                .get(seat)
                .ok_or_else(|| evaluation("actor seat is outside scheduled mapping"))?;
            let metric = metrics
                .iter_mut()
                .find(|entry| entry.agent_id == *agent_id)
                .ok_or_else(|| evaluation("scheduled agent is not diagnostic participant"))?;
            accumulate_decision(metric, position, frame, &model, config)?;
            total_frames = total_frames
                .checked_add(1)
                .ok_or(AnalysisError::ArithmeticOverflow)?;
        }
        let frame_count =
            u32::try_from(trace.frames.len()).map_err(|_| AnalysisError::ArithmeticOverflow)?;
        let trace_hash = analysis_trace_hash_v1(&trace)?;
        matches.push(AnalyzedEvaluationMatchV1 {
            match_index: spec.match_index,
            seed_index: spec.seed_index,
            rotation: spec.rotation,
            seed: spec.arena_config.seed,
            agent_ids_by_seat: spec.agent_ids_by_seat.clone(),
            replay_document_hash: replay_document_hash_v1(replay)
                .map_err(|error| AnalysisError::Replay(error.to_string()))?,
            analysis_trace_hash: trace_hash,
            analysis_relative_path: format!("matches/match-{:06}.analysis.json", spec.match_index),
            frame_count,
        });
        traces.push(trace);
    }
    outcome.seed_blocks = summarize_seed_blocks(&wins_by_seed)?;
    let diagnostic = NeuralEvaluationDiagnosticV1 {
        format: ANALYSIS_EVALUATION_FORMAT.into(),
        version: ANALYSIS_EVALUATION_VERSION,
        evaluation_id: plan.evaluation_id.clone(),
        evaluation_plan_hash: evaluation_plan_hash_v1(plan)
            .map_err(|error| evaluation(error.to_string()))?
            .to_string(),
        evaluation_report_hash: canonical_report_hash_v1(report)?,
        candidate_agent_id: candidate_agent_id.into(),
        champion_agent_id: champion_agent_id.into(),
        checkpoint_hash,
        config: config.clone(),
        outcome,
        total_frames,
        decision_metrics: metrics,
        matches,
    };
    diagnostic.validate()?;
    Ok(EvaluationDiagnosticOutputV1 { diagnostic, traces })
}

fn bind_match(
    record: &splendor_eval::EvaluationMatchRecordV1,
    spec: &splendor_eval::EvaluationMatchSpecV1,
    replay: &ReplayV1,
) -> Result<(), AnalysisError> {
    if record.match_index != spec.match_index
        || record.seed_index != spec.seed_index
        || record.rotation != spec.rotation
        || record.agent_ids_by_seat != spec.agent_ids_by_seat
        || replay.seed != spec.arena_config.seed
        || usize::from(replay.player_count) != spec.agent_ids_by_seat.len()
    {
        return Err(evaluation(format!(
            "match {} schedule/replay identity mismatch",
            spec.match_index
        )));
    }
    match &record.outcome {
        ArenaOutcomeV1::Completed {
            result,
            completed_plies,
            replay_final_hash,
        } if replay.result.matches(result)
            && *completed_plies == replay.steps.len() as u32
            && replay_final_hash == replay.final_state_hash.as_str() =>
        {
            Ok(())
        }
        ArenaOutcomeV1::Completed { .. } => Err(evaluation(format!(
            "match {} terminal replay binding mismatch",
            spec.match_index
        ))),
        ArenaOutcomeV1::Aborted { .. } => Err(evaluation(format!(
            "match {} is aborted and cannot be analyzed",
            spec.match_index
        ))),
    }
}

fn accumulate_decision(
    metric: &mut AgentDecisionMetricsV1,
    position: &splendor_replay::VerifiedReplayTraceStep,
    frame: &crate::AnalysisFrameV1,
    model: &PolicyValueModelV1,
    config: &NeuralIsmctsConfigV1,
) -> Result<(), AnalysisError> {
    let observation = &frame.player_view;
    let visible_history = visible_events(&position.state.log, Audience::Player(frame.actor));
    let information_set =
        build_information_set_v1(Ruleset::base_v1(), observation, &visible_history).map_err(
            |error| AnalysisError::Neural {
                ply: frame.ply,
                message: error.to_string(),
            },
        )?;
    if information_set.information_set_hash().as_str() != frame.information_set_hash {
        return Err(evaluation(format!(
            "information-set hash differs at match ply {}",
            frame.ply
        )));
    }
    let run = |mode| {
        search_neural_ismcts_ablation_v1(&information_set, model, config, mode).map_err(|error| {
            AnalysisError::Neural {
                ply: frame.ply,
                message: error.to_string(),
            }
        })
    };

    let value_only = run(NeuralAblationModeV1::ValueOnly)?;
    let policy_only = run(NeuralAblationModeV1::PolicyOnly)?;
    let neutral = run(NeuralAblationModeV1::Neutral)?;
    let full_result = &frame.neural_result;
    let top_prior = full_result
        .action_stats
        .iter()
        .reduce(|best, current| {
            if current.prior_micros > best.prior_micros {
                current
            } else {
                best
            }
        })
        .ok_or_else(|| invalid("empty full-search action stats"))?;
    let chosen = full_result
        .action_stats
        .iter()
        .find(|stats| stats.action == full_result.action)
        .ok_or_else(|| invalid("chosen action missing from stats"))?;
    if chosen.visits == 0 {
        return Err(invalid("chosen root action has zero visits"));
    }
    let chosen_q = chosen.value_sum_by_player[frame.actor.index()] / u64::from(chosen.visits);
    let best_q = full_result
        .action_stats
        .iter()
        .filter(|stats| stats.visits > 0)
        .map(|stats| stats.value_sum_by_player[frame.actor.index()] / u64::from(stats.visits))
        .max()
        .ok_or_else(|| invalid("no visited root action"))?;
    let prior_rank = 1 + full_result
        .action_stats
        .iter()
        .filter(|stats| stats.prior_micros > chosen.prior_micros)
        .count() as u64;
    let recorded = frame.recorded_action;

    metric.frames = add_u32(metric.frames, 1)?;
    metric.legal_actions_sum = add_u64(metric.legal_actions_sum, frame.legal_actions.len() as u64)?;
    metric.visited_actions_sum = add_u64(
        metric.visited_actions_sum,
        full_result
            .action_stats
            .iter()
            .filter(|stats| stats.visits > 0)
            .count() as u64,
    )?;
    add_match(
        &mut metric.full_matches_recorded,
        full_result.action == recorded,
    )?;
    add_match(
        &mut metric.direct_policy_matches_recorded,
        top_prior.action == recorded,
    )?;
    add_match(
        &mut metric.value_only_matches_recorded,
        value_only.action == recorded,
    )?;
    add_match(
        &mut metric.policy_only_matches_recorded,
        policy_only.action == recorded,
    )?;
    add_match(
        &mut metric.neutral_matches_recorded,
        neutral.action == recorded,
    )?;
    add_match(
        &mut metric.full_matches_direct_policy,
        full_result.action == top_prior.action,
    )?;
    add_match(
        &mut metric.full_matches_value_only,
        full_result.action == value_only.action,
    )?;
    add_match(
        &mut metric.full_matches_policy_only,
        full_result.action == policy_only.action,
    )?;
    add_match(
        &mut metric.full_matches_neutral,
        full_result.action == neutral.action,
    )?;
    add_match(
        &mut metric.full_selected_top_prior,
        full_result.action == top_prior.action,
    )?;
    metric.selected_prior_rank_sum = add_u64(metric.selected_prior_rank_sum, prior_rank)?;
    metric.selected_prior_micros_sum = add_u64(
        metric.selected_prior_micros_sum,
        u64::from(chosen.prior_micros),
    )?;
    metric.top_prior_micros_sum = add_u64(
        metric.top_prior_micros_sum,
        u64::from(top_prior.prior_micros),
    )?;
    metric.top_visit_count_sum = add_u64(
        metric.top_visit_count_sum,
        u64::from(
            full_result
                .action_stats
                .iter()
                .map(|stats| stats.visits)
                .max()
                .unwrap_or(0),
        ),
    )?;
    metric.chosen_q_micros_sum = add_u64(metric.chosen_q_micros_sum, chosen_q)?;
    metric.best_q_minus_chosen_q_micros_sum = add_u64(
        metric.best_q_minus_chosen_q_micros_sum,
        best_q.saturating_sub(chosen_q),
    )?;
    Ok(())
}

fn empty_metrics(agent_id: &str) -> AgentDecisionMetricsV1 {
    AgentDecisionMetricsV1 {
        agent_id: agent_id.into(),
        frames: 0,
        legal_actions_sum: 0,
        visited_actions_sum: 0,
        full_matches_recorded: 0,
        direct_policy_matches_recorded: 0,
        value_only_matches_recorded: 0,
        policy_only_matches_recorded: 0,
        neutral_matches_recorded: 0,
        full_matches_direct_policy: 0,
        full_matches_value_only: 0,
        full_matches_policy_only: 0,
        full_matches_neutral: 0,
        full_selected_top_prior: 0,
        selected_prior_rank_sum: 0,
        selected_prior_micros_sum: 0,
        top_prior_micros_sum: 0,
        top_visit_count_sum: 0,
        chosen_q_micros_sum: 0,
        best_q_minus_chosen_q_micros_sum: 0,
    }
}

fn empty_outcome() -> CandidateOutcomeSummaryV1 {
    CandidateOutcomeSummaryV1 {
        matches: 0,
        wins: 0,
        ties: 0,
        losses: 0,
        score_sum: 0,
        rank_sum: 0,
        completed_plies_sum: 0,
        by_seat: (0..2)
            .map(|seat| SeatOutcomeSummaryV1 {
                seat,
                matches: 0,
                wins: 0,
                ties: 0,
                losses: 0,
                score_sum: 0,
                rank_sum: 0,
            })
            .collect(),
        seed_blocks: SeedBlockSummaryV1 {
            blocks: 0,
            candidate_wins_zero: 0,
            candidate_wins_one: 0,
            candidate_wins_two: 0,
        },
    }
}

fn accumulate_outcome(
    summary: &mut CandidateOutcomeSummaryV1,
    wins_by_seed: &mut [u8],
    record: &splendor_eval::EvaluationMatchRecordV1,
    candidate_agent_id: &str,
) -> Result<(), AnalysisError> {
    let seat = record
        .agent_ids_by_seat
        .iter()
        .position(|id| id == candidate_agent_id)
        .ok_or_else(|| evaluation("candidate missing from match seat mapping"))?;
    let ArenaOutcomeV1::Completed {
        result,
        completed_plies,
        ..
    } = &record.outcome
    else {
        return Err(evaluation("aborted match in completed diagnostic"));
    };
    let candidate = PlayerId(seat as u8);
    let is_winner = result.winners.contains(&candidate);
    let is_tie = is_winner && result.winners.len() > 1;
    let seat_summary = summary
        .by_seat
        .get_mut(seat)
        .ok_or_else(|| evaluation("candidate seat outside outcome summary"))?;
    summary.matches = add_u32(summary.matches, 1)?;
    seat_summary.matches = add_u32(seat_summary.matches, 1)?;
    if is_tie {
        summary.ties = add_u32(summary.ties, 1)?;
        seat_summary.ties = add_u32(seat_summary.ties, 1)?;
    } else if is_winner {
        summary.wins = add_u32(summary.wins, 1)?;
        seat_summary.wins = add_u32(seat_summary.wins, 1)?;
        let seed_wins = wins_by_seed
            .get_mut(record.seed_index as usize)
            .ok_or_else(|| evaluation("seed index outside plan"))?;
        *seed_wins = seed_wins
            .checked_add(1)
            .ok_or(AnalysisError::ArithmeticOverflow)?;
    } else {
        summary.losses = add_u32(summary.losses, 1)?;
        seat_summary.losses = add_u32(seat_summary.losses, 1)?;
    }
    summary.score_sum = add_u64(summary.score_sum, u64::from(result.scores[seat]))?;
    summary.rank_sum = add_u64(summary.rank_sum, u64::from(result.ranks[seat]))?;
    summary.completed_plies_sum =
        add_u64(summary.completed_plies_sum, u64::from(*completed_plies))?;
    seat_summary.score_sum = add_u64(seat_summary.score_sum, u64::from(result.scores[seat]))?;
    seat_summary.rank_sum = add_u64(seat_summary.rank_sum, u64::from(result.ranks[seat]))?;
    Ok(())
}

fn summarize_seed_blocks(wins: &[u8]) -> Result<SeedBlockSummaryV1, AnalysisError> {
    let mut summary = SeedBlockSummaryV1 {
        blocks: u32::try_from(wins.len()).map_err(|_| AnalysisError::ArithmeticOverflow)?,
        candidate_wins_zero: 0,
        candidate_wins_one: 0,
        candidate_wins_two: 0,
    };
    for count in wins {
        let slot = match count {
            0 => &mut summary.candidate_wins_zero,
            1 => &mut summary.candidate_wins_one,
            2 => &mut summary.candidate_wins_two,
            _ => return Err(evaluation("more than two wins in a two-seat seed block")),
        };
        *slot = add_u32(*slot, 1)?;
    }
    Ok(summary)
}

fn canonical_report_hash_v1(report: &EvaluationReportV1) -> Result<String, AnalysisError> {
    let json = serde_json::to_vec(report)
        .map_err(|error| AnalysisError::Serialization(error.to_string()))?;
    let mut hasher = Sha256::new();
    hasher.update(b"effective-splendor-evaluation-report-v1\0");
    hasher.update(json);
    Ok(hex::encode(hasher.finalize()))
}

pub fn evaluation_diagnostic_hash_v1(
    diagnostic: &NeuralEvaluationDiagnosticV1,
) -> Result<String, AnalysisError> {
    diagnostic.validate()?;
    let json = serde_json::to_vec(diagnostic)
        .map_err(|error| AnalysisError::Serialization(error.to_string()))?;
    let mut hasher = Sha256::new();
    hasher.update(b"effective-splendor-neural-evaluation-diagnostic-v1\0");
    hasher.update(json);
    Ok(hex::encode(hasher.finalize()))
}

fn add_match(target: &mut u32, matches: bool) -> Result<(), AnalysisError> {
    if matches {
        *target = add_u32(*target, 1)?;
    }
    Ok(())
}

fn add_u32(left: u32, right: u32) -> Result<u32, AnalysisError> {
    left.checked_add(right)
        .ok_or(AnalysisError::ArithmeticOverflow)
}

fn add_u64(left: u64, right: u64) -> Result<u64, AnalysisError> {
    left.checked_add(right)
        .ok_or(AnalysisError::ArithmeticOverflow)
}

fn validate_hash(hash: &str) -> Result<(), AnalysisError> {
    if hash.len() != 64
        || !hash
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(invalid("expected lowercase SHA-256"));
    }
    Ok(())
}

fn evaluation(message: impl Into<String>) -> AnalysisError {
    AnalysisError::Evaluation(message.into())
}

fn invalid(message: impl Into<String>) -> AnalysisError {
    AnalysisError::InvalidDiagnostic(message.into())
}

#[cfg(test)]
mod tests {
    use std::path::PathBuf;

    use splendor_arena::AgentCommand;
    use splendor_core::{GameResult, PlayerId, TerminalReason};
    use splendor_eval::{
        aggregate, expand_schedule, EvaluationAgentV1, EvaluationMatchRecordV1, EvaluationPlanV1,
        EVALUATION_PLAN_FORMAT, EVALUATION_VERSION,
    };
    use splendor_learning::{
        model_checkpoint_hash_v1, ModelParametersV1, PolicyValueCheckpointV1, ACTION_FEATURES_V1,
        MAX_PLAYERS_V1, OBSERVATION_FEATURES_V1, POLICY_VALUE_CHECKPOINT_FORMAT,
        POLICY_VALUE_CHECKPOINT_VERSION, REPRESENTATION_VERSION_V1,
    };
    use splendor_replay::{record_random_game, ReplayGameResultV1};

    use super::*;

    fn checkpoint() -> PolicyValueCheckpointV1 {
        let hidden = 4usize;
        PolicyValueCheckpointV1 {
            format: POLICY_VALUE_CHECKPOINT_FORMAT.into(),
            version: POLICY_VALUE_CHECKPOINT_VERSION,
            model_id: "diagnostic-test-model".into(),
            representation_version: REPRESENTATION_VERSION_V1.into(),
            observation_features: OBSERVATION_FEATURES_V1 as u32,
            action_features: ACTION_FEATURES_V1 as u32,
            hidden_features: hidden as u32,
            max_players: MAX_PLAYERS_V1 as u8,
            source_dataset_id: "diagnostic-test-dataset".into(),
            source_dataset_hash: "11".repeat(32),
            league_manifest_hash: "22".repeat(32),
            evaluation_plan_hash: "33".repeat(32),
            evaluation_report_hash: "44".repeat(32),
            training_config_hash: "55".repeat(32),
            training_contract_version: None,
            trained_examples: 4,
            validation_examples: 2,
            validation_seed_modulus: 2,
            validation_seed_remainder: 0,
            epochs: 1,
            parameters: ModelParametersV1 {
                encoder_weights: vec![0.0; hidden * OBSERVATION_FEATURES_V1],
                encoder_bias: vec![0.0; hidden],
                policy_bilinear: vec![0.0; hidden * ACTION_FEATURES_V1],
                policy_action_bias: vec![0.0; ACTION_FEATURES_V1],
                value_weights: vec![0.0; MAX_PLAYERS_V1 * hidden],
                value_bias: vec![0.0; MAX_PLAYERS_V1],
            },
        }
    }

    fn plan() -> EvaluationPlanV1 {
        EvaluationPlanV1 {
            format: EVALUATION_PLAN_FORMAT.into(),
            version: EVALUATION_VERSION,
            evaluation_id: "diagnostic-test".into(),
            agents: ["candidate", "champion"]
                .iter()
                .map(|id| EvaluationAgentV1 {
                    id: (*id).into(),
                    command: AgentCommand {
                        program: PathBuf::from(id),
                        args: vec![],
                    },
                })
                .collect(),
            game_seeds: vec![42],
            handshake_timeout_ms: 1_000,
            move_timeout_ms: 1_000,
            shutdown_grace_ms: 1_000,
        }
    }

    fn runtime_result(result: &ReplayGameResultV1) -> GameResult {
        GameResult {
            scores: result.scores.clone(),
            ranks: result.ranks.clone(),
            winners: result.winners.iter().copied().map(PlayerId).collect(),
            reason: match result.reason {
                splendor_replay::ReplayTerminalReason::PrestigeThreshold => {
                    TerminalReason::PrestigeThreshold
                }
                splendor_replay::ReplayTerminalReason::Stalemate => TerminalReason::Stalemate,
            },
        }
    }

    #[test]
    fn complete_evaluation_produces_bound_deterministic_diagnostics() {
        let plan = plan();
        let specs = expand_schedule(&plan).unwrap();
        let replays = specs
            .iter()
            .map(|spec| {
                let (_, replay) =
                    record_random_game(2, spec.arena_config.seed, 9 + spec.match_index as u64)
                        .unwrap();
                (spec.match_index, replay)
            })
            .collect::<Vec<_>>();
        let records = specs
            .iter()
            .zip(&replays)
            .map(|(spec, (_, replay))| EvaluationMatchRecordV1 {
                match_index: spec.match_index,
                game_id: spec.arena_config.game_id.clone(),
                seed_index: spec.seed_index,
                rotation: spec.rotation,
                agent_ids_by_seat: spec.agent_ids_by_seat.clone(),
                outcome: ArenaOutcomeV1::completed(
                    runtime_result(&replay.result),
                    replay.steps.len() as u32,
                    replay.final_state_hash.as_str().into(),
                ),
            })
            .collect::<Vec<_>>();
        let report = aggregate(&plan, &records).unwrap();
        let checkpoint = checkpoint();
        let config = NeuralIsmctsConfigV1 {
            sample_seed: 17,
            simulations: 2,
            max_depth_turns: 1,
            puct_exploration_milli: 1_500,
            expected_checkpoint_hash: model_checkpoint_hash_v1(&checkpoint).unwrap(),
        };
        let first = analyze_evaluation_neural_v1(
            &plan,
            &report,
            &replays,
            &checkpoint,
            &config,
            "candidate",
            "champion",
        )
        .unwrap();
        let second = analyze_evaluation_neural_v1(
            &plan,
            &report,
            &replays,
            &checkpoint,
            &config,
            "candidate",
            "champion",
        )
        .unwrap();
        assert_eq!(first.diagnostic, second.diagnostic);
        assert_eq!(first.traces, second.traces);
        first.diagnostic.validate().unwrap();
        assert_eq!(first.diagnostic.matches.len(), 2);
        assert_eq!(first.diagnostic.outcome.seed_blocks.blocks, 1);
        assert_eq!(
            evaluation_diagnostic_hash_v1(&first.diagnostic).unwrap(),
            evaluation_diagnostic_hash_v1(&second.diagnostic).unwrap()
        );
    }

    #[test]
    fn noncanonical_report_is_rejected_before_replay_analysis() {
        let plan = plan();
        let specs = expand_schedule(&plan).unwrap();
        let (_, replay) = record_random_game(2, 42, 9).unwrap();
        let records = specs
            .iter()
            .map(|spec| EvaluationMatchRecordV1 {
                match_index: spec.match_index,
                game_id: spec.arena_config.game_id.clone(),
                seed_index: spec.seed_index,
                rotation: spec.rotation,
                agent_ids_by_seat: spec.agent_ids_by_seat.clone(),
                outcome: ArenaOutcomeV1::completed(
                    runtime_result(&replay.result),
                    replay.steps.len() as u32,
                    replay.final_state_hash.as_str().into(),
                ),
            })
            .collect::<Vec<_>>();
        let mut report = aggregate(&plan, &records).unwrap();
        report.agents[0].wins ^= 1;
        let checkpoint = checkpoint();
        let config = NeuralIsmctsConfigV1 {
            sample_seed: 17,
            simulations: 1,
            max_depth_turns: 1,
            puct_exploration_milli: 1_500,
            expected_checkpoint_hash: model_checkpoint_hash_v1(&checkpoint).unwrap(),
        };
        assert!(matches!(
            analyze_evaluation_neural_v1(
                &plan,
                &report,
                &[],
                &checkpoint,
                &config,
                "candidate",
                "champion",
            ),
            Err(AnalysisError::Evaluation(message)) if message.contains("not canonical")
        ));
    }
}
