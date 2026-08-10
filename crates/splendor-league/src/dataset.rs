use std::collections::HashSet;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use splendor_arena::{
    seed_commitment_v1, ArenaOutcomeV1, ArenaReportV1, ARENA_REPORT_FORMAT, ARENA_REPORT_VERSION,
};
use splendor_belief::build_information_set_v1;
use splendor_core::{
    observation_hash, visible_events, Action, Audience, Observation, PlayerId, RulesetFingerprint,
};
use splendor_eval::{
    aggregate, evaluation_plan_hash_v1, expand_schedule, EvaluationMatchRecordV1,
    EvaluationMatchSpecV1, EvaluationPlanV1, EvaluationReportV1,
};
use splendor_replay::{replay_document_hash_v1, verify_replay_trace, ReplayGameResultV1, ReplayV1};
use splendor_search::canonical_order;
use std::str::FromStr;

use crate::{league_manifest_hash_v1, LeagueError, LeagueManifestV1};

pub const TRAINING_DATASET_FORMAT: &str = "effective-splendor-training-dataset";
pub const TRAINING_DATASET_VERSION: u32 = 1;

pub struct DatasetReplaySourceV1<'a> {
    pub source_id: &'a str,
    pub match_index: u32,
    pub replay: &'a ReplayV1,
    pub arena_report: &'a ArenaReportV1,
}

pub struct DatasetEvaluationRunV1<'a> {
    pub plan: &'a EvaluationPlanV1,
    pub report: &'a EvaluationReportV1,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TrainingAgentIdentityV1 {
    pub seat: PlayerId,
    pub league_agent_id: String,
    pub policy_version: String,
    pub model_version: Option<String>,
    pub runtime_name: String,
    pub runtime_version: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TrainingReplayV1 {
    pub source_id: String,
    pub evaluation_match_index: u32,
    pub seed_index: u32,
    pub rotation: u8,
    pub arena_game_id: String,
    pub arena_report_hash: String,
    pub replay_document_hash: String,
    pub engine_version: String,
    pub ruleset_id: String,
    pub ruleset_fingerprint: String,
    pub player_count: u8,
    pub steps: u32,
    pub final_state_hash: String,
    pub result: ReplayGameResultV1,
    pub agents_by_seat: Vec<TrainingAgentIdentityV1>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TrainingExampleV1 {
    pub source_id: String,
    pub replay_document_hash: String,
    pub ply: u32,
    pub actor: PlayerId,
    pub observation_hash: String,
    pub visible_history_hash: String,
    pub information_set_hash: String,
    pub observation: Observation,
    pub legal_actions: Vec<Action>,
    pub chosen_action: Action,
    pub final_scores: Vec<u8>,
    pub final_ranks: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TrainingDatasetV1 {
    pub format: String,
    pub version: u32,
    pub dataset_id: String,
    pub league_manifest_hash: String,
    pub evaluation_id: String,
    pub evaluation_plan_hash: String,
    pub evaluation_report_hash: String,
    pub replays: Vec<TrainingReplayV1>,
    pub examples: Vec<TrainingExampleV1>,
}

pub fn build_training_dataset_v1(
    dataset_id: &str,
    manifest: &LeagueManifestV1,
    evaluation: DatasetEvaluationRunV1<'_>,
    sources: &[DatasetReplaySourceV1<'_>],
) -> Result<TrainingDatasetV1, LeagueError> {
    validate_dataset_label("dataset_id", dataset_id)?;
    if sources.is_empty() {
        return Err(LeagueError::InvalidDataset(
            "at least one replay source is required".into(),
        ));
    }
    let manifest_hash = league_manifest_hash_v1(manifest)?;
    let (plan_hash, report_hash, schedule) = validate_evaluation_run(manifest, &evaluation)?;
    let mut seen_sources = HashSet::new();
    let mut seen_matches = HashSet::new();
    let mut replays = Vec::with_capacity(sources.len());
    let mut examples = Vec::new();

    for source in sources {
        validate_dataset_label("source_id", source.source_id)?;
        if !seen_sources.insert(source.source_id.to_string()) {
            return Err(LeagueError::DuplicateReplaySource(
                source.source_id.to_string(),
            ));
        }
        if !seen_matches.insert(source.match_index) {
            return Err(LeagueError::DuplicateEvaluationMatch(source.match_index));
        }
        let spec = schedule
            .get(source.match_index as usize)
            .filter(|spec| spec.match_index == source.match_index)
            .ok_or_else(|| {
                LeagueError::EvaluationBinding(format!(
                    "source `{}` names unknown match_index {}",
                    source.source_id, source.match_index
                ))
            })?;
        let record = evaluation
            .report
            .records
            .get(source.match_index as usize)
            .filter(|record| record.match_index == source.match_index)
            .ok_or_else(|| {
                LeagueError::EvaluationBinding(format!(
                    "evaluation report is missing canonical match_index {}",
                    source.match_index
                ))
            })?;
        let trace = verify_replay_trace(source.replay).map_err(|error| {
            LeagueError::ReplayVerification {
                source_id: source.source_id.to_string(),
                message: error.to_string(),
            }
        })?;
        let replay_hash = replay_document_hash_v1(source.replay).map_err(|error| {
            LeagueError::ReplayVerification {
                source_id: source.source_id.to_string(),
                message: error.to_string(),
            }
        })?;
        let agents_by_seat = bind_arena_report(source, manifest, spec, record)?;
        let arena_report_hash = arena_report_document_hash_v1(source.arena_report)?;
        for position in trace.positions {
            let observation = position.state.observation(position.recorded_actor);
            let history = visible_events(
                &position.state.log,
                Audience::Player(position.recorded_actor),
            );
            let information_set =
                build_information_set_v1(position.state.ruleset, &observation, &history).map_err(
                    |error| LeagueError::InformationSet {
                        source_id: source.source_id.to_string(),
                        ply: position.ply,
                        message: error.to_string(),
                    },
                )?;
            let legal_actions = canonical_order(&position.state.legal_actions());
            if !legal_actions.contains(&position.recorded_action) {
                return Err(LeagueError::RecordedActionNotLegal {
                    source_id: source.source_id.to_string(),
                    ply: position.ply,
                });
            }
            examples.push(TrainingExampleV1 {
                source_id: source.source_id.to_string(),
                replay_document_hash: replay_hash.clone(),
                ply: position.ply,
                actor: position.recorded_actor,
                observation_hash: observation_hash(&observation).as_str().to_string(),
                visible_history_hash: information_set.visible_history_hash().as_str().to_string(),
                information_set_hash: information_set.information_set_hash().as_str().to_string(),
                observation,
                legal_actions,
                chosen_action: position.recorded_action,
                final_scores: trace.verified.result.scores.clone(),
                final_ranks: trace.verified.result.ranks.clone(),
            });
        }
        replays.push(TrainingReplayV1 {
            source_id: source.source_id.to_string(),
            evaluation_match_index: source.match_index,
            seed_index: spec.seed_index,
            rotation: spec.rotation,
            arena_game_id: source.arena_report.game_id.clone(),
            arena_report_hash,
            replay_document_hash: replay_hash,
            engine_version: source.replay.engine_version.clone(),
            ruleset_id: source.replay.ruleset.id.clone(),
            ruleset_fingerprint: source.replay.ruleset_fingerprint.as_str().to_string(),
            player_count: trace.verified.player_count,
            steps: trace.verified.steps,
            final_state_hash: trace.verified.final_state_hash,
            result: trace.verified.result,
            agents_by_seat,
        });
    }

    Ok(TrainingDatasetV1 {
        format: TRAINING_DATASET_FORMAT.to_string(),
        version: TRAINING_DATASET_VERSION,
        dataset_id: dataset_id.to_string(),
        league_manifest_hash: manifest_hash,
        evaluation_id: evaluation.plan.evaluation_id.clone(),
        evaluation_plan_hash: plan_hash,
        evaluation_report_hash: report_hash,
        replays,
        examples,
    })
}

fn validate_evaluation_run(
    manifest: &LeagueManifestV1,
    evaluation: &DatasetEvaluationRunV1<'_>,
) -> Result<(String, String, Vec<EvaluationMatchSpecV1>), LeagueError> {
    let expected_plan = manifest.evaluation_plan_v1()?;
    let expected_hash = evaluation_plan_hash_v1(&expected_plan)
        .map_err(|error| LeagueError::InvalidEvaluationPlan(error.to_string()))?;
    let supplied_hash = evaluation_plan_hash_v1(evaluation.plan)
        .map_err(|error| LeagueError::InvalidEvaluationPlan(error.to_string()))?;
    if supplied_hash != expected_hash {
        return Err(LeagueError::EvaluationBinding(format!(
            "evaluation plan hash {} does not match manifest-derived plan hash {}",
            supplied_hash, expected_hash
        )));
    }

    let canonical = aggregate(evaluation.plan, &evaluation.report.records)
        .map_err(|error| LeagueError::EvaluationBinding(error.to_string()))?;
    if canonical != *evaluation.report {
        return Err(LeagueError::EvaluationBinding(
            "evaluation report is not the canonical aggregate for the supplied plan".into(),
        ));
    }
    let schedule = expand_schedule(evaluation.plan)
        .map_err(|error| LeagueError::EvaluationBinding(error.to_string()))?;
    let report_hash = evaluation_report_document_hash_v1(evaluation.report)?;
    Ok((supplied_hash.to_string(), report_hash, schedule))
}

pub fn evaluation_report_document_hash_v1(
    report: &EvaluationReportV1,
) -> Result<String, LeagueError> {
    hash_serialized(
        b"effective-splendor-evaluation-report-document-v1\0",
        report,
    )
}

pub fn arena_report_document_hash_v1(report: &ArenaReportV1) -> Result<String, LeagueError> {
    hash_serialized(b"effective-splendor-arena-report-document-v1\0", report)
}

fn hash_serialized<T: Serialize>(domain: &[u8], value: &T) -> Result<String, LeagueError> {
    let json =
        serde_json::to_vec(value).map_err(|error| LeagueError::Serialization(error.to_string()))?;
    let mut hasher = Sha256::new();
    hasher.update(domain);
    hasher.update(json);
    Ok(hex::encode(hasher.finalize()))
}

fn validate_dataset_label(label: &str, value: &str) -> Result<(), LeagueError> {
    if value.trim().is_empty()
        || value.len() > 128
        || value.as_bytes().iter().any(|byte| *byte < 0x20)
    {
        return Err(LeagueError::InvalidDataset(format!(
            "{label} must be non-empty, at most 128 bytes, and contain no C0 controls"
        )));
    }
    Ok(())
}

fn bind_arena_report(
    source: &DatasetReplaySourceV1<'_>,
    manifest: &LeagueManifestV1,
    spec: &EvaluationMatchSpecV1,
    record: &EvaluationMatchRecordV1,
) -> Result<Vec<TrainingAgentIdentityV1>, LeagueError> {
    let report = source.arena_report;
    let replay = source.replay;
    let fail = |message: String| LeagueError::ArenaBinding {
        source_id: source.source_id.to_string(),
        message,
    };

    if report.format != ARENA_REPORT_FORMAT || report.version != ARENA_REPORT_VERSION {
        return Err(fail("invalid arena report format/version".into()));
    }
    if report.game_id.trim().is_empty() {
        return Err(fail("arena game_id must be non-empty".into()));
    }
    if report.game_id != spec.arena_config.game_id
        || replay.seed != spec.arena_config.seed
        || record.game_id != spec.arena_config.game_id
        || record.outcome != report.outcome
    {
        return Err(fail(
            "arena report/replay do not match the attested evaluation match".into(),
        ));
    }
    if report.player_count != replay.player_count
        || report.ruleset != replay.ruleset.id
        || report.ruleset_fingerprint != replay.ruleset_fingerprint.as_str()
        || report.engine_version != replay.engine_version
    {
        return Err(fail(
            "arena compatibility metadata does not match replay".into(),
        ));
    }
    if report.protocol_version.trim().is_empty() {
        return Err(fail("arena protocol_version must be non-empty".into()));
    }

    let fingerprint = RulesetFingerprint::from_str(&report.ruleset_fingerprint)
        .map_err(|message| fail(format!("invalid ruleset fingerprint: {message}")))?;
    let expected_commitment = seed_commitment_v1(
        &report.game_id,
        replay.player_count,
        replay.seed,
        &fingerprint,
    );
    if report.seed_commitment != expected_commitment {
        return Err(fail("seed commitment does not bind this replay".into()));
    }

    match &report.outcome {
        ArenaOutcomeV1::Completed {
            result,
            completed_plies,
            replay_final_hash,
        } => {
            if *completed_plies != replay.steps.len() as u32
                || replay_final_hash != replay.final_state_hash.as_str()
                || !replay.result.matches(result)
            {
                return Err(fail("completed arena outcome does not match replay".into()));
            }
        }
        ArenaOutcomeV1::Aborted { .. } => {
            return Err(fail("aborted arena reports cannot enter a dataset".into()));
        }
    }

    if report.agents.len() != replay.player_count as usize
        || manifest.agents.len() != replay.player_count as usize
        || spec.agent_ids_by_seat.len() != replay.player_count as usize
        || spec.arena_config.agents.len() != replay.player_count as usize
    {
        return Err(fail(
            "arena, replay, and league lineup seat counts differ".into(),
        ));
    }

    let mut seats = vec![None; replay.player_count as usize];
    for identity in &report.agents {
        let seat = identity.seat.0 as usize;
        if seat >= seats.len() || seats[seat].is_some() {
            return Err(fail(
                "arena agent seats are not unique and contiguous".into(),
            ));
        }
        let runtime_name = identity
            .agent_name
            .as_deref()
            .ok_or_else(|| fail(format!("seat {seat} has no runtime name")))?;
        let runtime_version = identity
            .agent_version
            .as_deref()
            .ok_or_else(|| fail(format!("seat {seat} has no runtime version")))?;
        let expected_agent_id = spec
            .agent_ids_by_seat
            .get(seat)
            .ok_or_else(|| fail(format!("evaluation schedule is missing seat {seat}")))?;
        let league_agent = manifest
            .agents
            .iter()
            .find(|agent| &agent.id == expected_agent_id)
            .ok_or_else(|| {
                fail(format!(
                    "scheduled league agent `{expected_agent_id}` is not in the manifest"
                ))
            })?;
        if league_agent.runtime_name != runtime_name
            || league_agent.runtime_version != runtime_version
        {
            return Err(fail(format!(
                "seat {seat} runtime identity `{runtime_name}@{runtime_version}` does not match scheduled agent `{expected_agent_id}`"
            )));
        }
        seats[seat] = Some(TrainingAgentIdentityV1 {
            seat: identity.seat,
            league_agent_id: league_agent.id.clone(),
            policy_version: league_agent.policy_version.clone(),
            model_version: league_agent.model_version.clone(),
            runtime_name: runtime_name.to_string(),
            runtime_version: runtime_version.to_string(),
        });
    }

    seats
        .into_iter()
        .enumerate()
        .map(|(seat, identity)| {
            identity.ok_or_else(|| fail(format!("arena report is missing seat {seat}")))
        })
        .collect()
}

pub fn training_dataset_hash_v1(dataset: &TrainingDatasetV1) -> Result<String, LeagueError> {
    hash_serialized(b"effective-splendor-training-dataset-v1\0", dataset)
}

#[cfg(test)]
mod tests {
    use std::path::PathBuf;

    use splendor_arena::{AgentCommand, AgentIdentity, ArenaReportV1};
    use splendor_core::{FullState, RulesetFingerprint};
    use splendor_eval::{aggregate, expand_schedule, EvaluationMatchRecordV1};
    use splendor_replay::record_random_game;

    use super::*;
    use crate::{LeagueAgentV1, LeagueRoleV1, LEAGUE_MANIFEST_FORMAT, LEAGUE_VERSION};

    fn manifest(game_seed: u64, simulations: &str, depth: &str) -> LeagueManifestV1 {
        LeagueManifestV1 {
            format: LEAGUE_MANIFEST_FORMAT.into(),
            version: LEAGUE_VERSION,
            league_id: "m11-unit".into(),
            lineup_id: "champion-candidate".into(),
            agents: vec![
                LeagueAgentV1 {
                    id: "champion".into(),
                    role: LeagueRoleV1::Champion,
                    policy_version: "heuristic-v1".into(),
                    model_version: None,
                    runtime_name: "splendor-cli-heuristic".into(),
                    runtime_version: "0.1.0".into(),
                    command: AgentCommand {
                        program: PathBuf::from("splendor"),
                        args: vec!["agent-heuristic".into(), "--seed".into(), "1".into()],
                    },
                },
                LeagueAgentV1 {
                    id: "candidate".into(),
                    role: LeagueRoleV1::Candidate,
                    policy_version: "ismcts-v1".into(),
                    model_version: None,
                    runtime_name: "effective-splendor-ismcts-agent-v1".into(),
                    runtime_version: "1".into(),
                    command: AgentCommand {
                        program: PathBuf::from("splendor"),
                        args: vec![
                            "agent-ismcts".into(),
                            "--sample-seed".into(),
                            "17".into(),
                            "--simulations".into(),
                            simulations.into(),
                            "--max-depth-turns".into(),
                            depth.into(),
                            "--exploration-bias".into(),
                            "100000000".into(),
                        ],
                    },
                },
            ],
            game_seeds: vec![game_seed],
            handshake_timeout_ms: 1_000,
            move_timeout_ms: 2_000,
            shutdown_grace_ms: 1_000,
        }
    }

    fn report(
        manifest: &LeagueManifestV1,
        spec: &EvaluationMatchSpecV1,
        state: &FullState,
        replay: &ReplayV1,
    ) -> ArenaReportV1 {
        let fingerprint =
            RulesetFingerprint::from_str(replay.ruleset_fingerprint.as_str()).unwrap();
        ArenaReportV1::new(
            spec.arena_config.game_id.clone(),
            replay.engine_version.clone(),
            "0.5",
            replay.ruleset.id.clone(),
            replay.ruleset_fingerprint.as_str(),
            replay.player_count,
            seed_commitment_v1(
                &spec.arena_config.game_id,
                replay.player_count,
                replay.seed,
                &fingerprint,
            ),
            spec.agent_ids_by_seat
                .iter()
                .enumerate()
                .map(|(seat, id)| {
                    let agent = manifest
                        .agents
                        .iter()
                        .find(|agent| &agent.id == id)
                        .unwrap();
                    AgentIdentity {
                        seat: PlayerId(seat as u8),
                        agent_name: Some(agent.runtime_name.clone()),
                        agent_version: Some(agent.runtime_version.clone()),
                    }
                })
                .collect(),
            ArenaOutcomeV1::completed(
                state.result.clone().unwrap(),
                replay.steps.len() as u32,
                replay.final_state_hash.as_str().to_string(),
            ),
        )
    }

    fn execution(
        manifest: &LeagueManifestV1,
        state: &FullState,
        replay: &ReplayV1,
    ) -> (EvaluationPlanV1, EvaluationReportV1, ArenaReportV1) {
        let plan = manifest.evaluation_plan_v1().unwrap();
        let specs = expand_schedule(&plan).unwrap();
        let arena_report = report(manifest, &specs[0], state, replay);
        let records = specs
            .iter()
            .map(|spec| EvaluationMatchRecordV1 {
                match_index: spec.match_index,
                game_id: spec.arena_config.game_id.clone(),
                seed_index: spec.seed_index,
                rotation: spec.rotation,
                agent_ids_by_seat: spec.agent_ids_by_seat.clone(),
                outcome: arena_report.outcome.clone(),
            })
            .collect::<Vec<_>>();
        let evaluation_report = aggregate(&plan, &records).unwrap();
        (plan, evaluation_report, arena_report)
    }

    #[test]
    fn manifest_expands_to_a_valid_seat_rotated_evaluation_plan() {
        let manifest = manifest(1, "64", "2");
        manifest.validate().unwrap();
        let plan = manifest.evaluation_plan_v1().unwrap();
        assert_eq!(plan.agents.len(), 2);
        assert_eq!(plan.game_seeds, vec![1]);
        assert_eq!(league_manifest_hash_v1(&manifest).unwrap().len(), 64);
    }

    #[test]
    fn verified_replay_becomes_player_view_examples_without_seed_or_full_state() {
        let (state, replay) = record_random_game(2, 42, 7).unwrap();
        let manifest = manifest(42, "64", "2");
        let (plan, evaluation_report, report) = execution(&manifest, &state, &replay);
        let dataset = build_training_dataset_v1(
            "m11-dataset-unit",
            &manifest,
            DatasetEvaluationRunV1 {
                plan: &plan,
                report: &evaluation_report,
            },
            &[DatasetReplaySourceV1 {
                source_id: "game-0001",
                match_index: 0,
                replay: &replay,
                arena_report: &report,
            }],
        )
        .unwrap();
        assert_eq!(dataset.replays.len(), 1);
        assert_eq!(dataset.examples.len(), replay.steps.len());
        assert!(dataset
            .examples
            .iter()
            .all(|example| example.legal_actions.contains(&example.chosen_action)));
        assert_eq!(training_dataset_hash_v1(&dataset).unwrap().len(), 64);
        let json = serde_json::to_string(&dataset).unwrap();
        assert!(!json.contains("state_hash_before"));
        assert!(!json.contains("\"seed\""));
        assert_eq!(dataset.evaluation_plan_hash, evaluation_report.plan_hash);
        assert_eq!(dataset.replays[0].evaluation_match_index, 0);
        assert_eq!(
            dataset.replays[0].agents_by_seat[1].policy_version,
            "ismcts-v1"
        );
    }

    #[test]
    fn duplicate_source_ids_are_rejected() {
        let (state, replay) = record_random_game(2, 1, 2).unwrap();
        let manifest = manifest(1, "64", "2");
        let (plan, evaluation_report, report) = execution(&manifest, &state, &replay);
        let sources = [
            DatasetReplaySourceV1 {
                source_id: "same",
                match_index: 0,
                replay: &replay,
                arena_report: &report,
            },
            DatasetReplaySourceV1 {
                source_id: "same",
                match_index: 0,
                replay: &replay,
                arena_report: &report,
            },
        ];
        assert!(matches!(
            build_training_dataset_v1(
                "dataset",
                &manifest,
                DatasetEvaluationRunV1 {
                    plan: &plan,
                    report: &evaluation_report,
                },
                &sources
            ),
            Err(LeagueError::DuplicateReplaySource(_))
        ));
    }

    #[test]
    fn duplicate_match_indices_are_rejected_even_with_distinct_source_ids() {
        let (state, replay) = record_random_game(2, 5, 2).unwrap();
        let manifest = manifest(5, "64", "2");
        let (plan, evaluation_report, report) = execution(&manifest, &state, &replay);
        let sources = [
            DatasetReplaySourceV1 {
                source_id: "first",
                match_index: 0,
                replay: &replay,
                arena_report: &report,
            },
            DatasetReplaySourceV1 {
                source_id: "second",
                match_index: 0,
                replay: &replay,
                arena_report: &report,
            },
        ];
        assert!(matches!(
            build_training_dataset_v1(
                "dataset",
                &manifest,
                DatasetEvaluationRunV1 {
                    plan: &plan,
                    report: &evaluation_report,
                },
                &sources
            ),
            Err(LeagueError::DuplicateEvaluationMatch(0))
        ));
    }

    #[test]
    fn noncanonical_evaluation_report_is_rejected() {
        let (state, replay) = record_random_game(2, 6, 2).unwrap();
        let manifest = manifest(6, "64", "2");
        let (plan, mut evaluation_report, report) = execution(&manifest, &state, &replay);
        evaluation_report.plan_hash = "00".repeat(32);
        assert!(matches!(
            build_training_dataset_v1(
                "dataset",
                &manifest,
                DatasetEvaluationRunV1 {
                    plan: &plan,
                    report: &evaluation_report,
                },
                &[DatasetReplaySourceV1 {
                    source_id: "tampered-report",
                    match_index: 0,
                    replay: &replay,
                    arena_report: &report,
                }]
            ),
            Err(LeagueError::EvaluationBinding(_))
        ));
    }

    #[test]
    fn arena_report_must_bind_seed_outcome_and_runtime_identity() {
        let (state, replay) = record_random_game(2, 19, 3).unwrap();
        let manifest = manifest(19, "64", "2");
        let (plan, evaluation_report, mut mismatched) = execution(&manifest, &state, &replay);
        mismatched.agents[1].agent_version = Some("other".into());
        assert!(matches!(
            build_training_dataset_v1(
                "dataset",
                &manifest,
                DatasetEvaluationRunV1 {
                    plan: &plan,
                    report: &evaluation_report,
                },
                &[DatasetReplaySourceV1 {
                    source_id: "bad-binding",
                    match_index: 0,
                    replay: &replay,
                    arena_report: &mismatched,
                }]
            ),
            Err(LeagueError::ArenaBinding { .. })
        ));

        let (_, other_replay) = record_random_game(2, 20, 3).unwrap();
        let (_, _, valid_report_for_first) = execution(&manifest, &state, &replay);
        assert!(matches!(
            build_training_dataset_v1(
                "dataset",
                &manifest,
                DatasetEvaluationRunV1 {
                    plan: &plan,
                    report: &evaluation_report,
                },
                &[DatasetReplaySourceV1 {
                    source_id: "bad-commitment",
                    match_index: 0,
                    replay: &other_replay,
                    arena_report: &valid_report_for_first,
                }]
            ),
            Err(LeagueError::ArenaBinding { .. })
        ));
    }

    #[test]
    fn same_runtime_identity_with_different_executed_command_is_rejected() {
        let declared = manifest(31, "64", "2");
        let actual = manifest(31, "16", "1");
        assert_eq!(
            declared.agents[1].runtime_name,
            actual.agents[1].runtime_name
        );
        assert_eq!(
            declared.agents[1].runtime_version,
            actual.agents[1].runtime_version
        );
        let (state, replay) = record_random_game(2, 31, 4).unwrap();
        let (actual_plan, actual_report, arena_report) = execution(&actual, &state, &replay);
        assert!(matches!(
            build_training_dataset_v1(
                "wrong-command",
                &declared,
                DatasetEvaluationRunV1 {
                    plan: &actual_plan,
                    report: &actual_report,
                },
                &[DatasetReplaySourceV1 {
                    source_id: "wrong-command",
                    match_index: 0,
                    replay: &replay,
                    arena_report: &arena_report,
                }]
            ),
            Err(LeagueError::EvaluationBinding(_))
        ));
    }
}
