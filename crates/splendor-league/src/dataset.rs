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
use splendor_replay::{replay_document_hash_v1, verify_replay_trace, ReplayGameResultV1, ReplayV1};
use splendor_search::canonical_order;
use std::str::FromStr;

use crate::{league_manifest_hash_v1, LeagueError, LeagueManifestV1};

pub const TRAINING_DATASET_FORMAT: &str = "effective-splendor-training-dataset";
pub const TRAINING_DATASET_VERSION: u32 = 1;

pub struct DatasetReplaySourceV1<'a> {
    pub source_id: &'a str,
    pub replay: &'a ReplayV1,
    pub arena_report: &'a ArenaReportV1,
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
    pub arena_game_id: String,
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
    pub replays: Vec<TrainingReplayV1>,
    pub examples: Vec<TrainingExampleV1>,
}

pub fn build_training_dataset_v1(
    dataset_id: &str,
    manifest: &LeagueManifestV1,
    sources: &[DatasetReplaySourceV1<'_>],
) -> Result<TrainingDatasetV1, LeagueError> {
    validate_dataset_label("dataset_id", dataset_id)?;
    if sources.is_empty() {
        return Err(LeagueError::InvalidDataset(
            "at least one replay source is required".into(),
        ));
    }
    let manifest_hash = league_manifest_hash_v1(manifest)?;
    let mut seen = HashSet::new();
    let mut replays = Vec::with_capacity(sources.len());
    let mut examples = Vec::new();

    for source in sources {
        validate_dataset_label("source_id", source.source_id)?;
        if !seen.insert(source.source_id.to_string()) {
            return Err(LeagueError::DuplicateReplaySource(
                source.source_id.to_string(),
            ));
        }
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
        let agents_by_seat = bind_arena_report(source, manifest)?;
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
            arena_game_id: source.arena_report.game_id.clone(),
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
        replays,
        examples,
    })
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
    {
        return Err(fail(
            "arena, replay, and league lineup seat counts differ".into(),
        ));
    }

    let mut seats = vec![None; replay.player_count as usize];
    let mut matched_league_agents = HashSet::new();
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
        let league_agent = manifest
            .agents
            .iter()
            .find(|agent| {
                agent.runtime_name == runtime_name && agent.runtime_version == runtime_version
            })
            .ok_or_else(|| {
                fail(format!(
                    "seat {seat} runtime identity `{runtime_name}@{runtime_version}` is not in the league lineup"
                ))
            })?;
        if !matched_league_agents.insert(league_agent.id.as_str()) {
            return Err(fail(format!(
                "league agent `{}` appears in more than one seat",
                league_agent.id
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
    let json = serde_json::to_string(dataset)
        .map_err(|error| LeagueError::Serialization(error.to_string()))?;
    let mut hasher = Sha256::new();
    hasher.update(b"effective-splendor-training-dataset-v1\0");
    hasher.update(json.as_bytes());
    Ok(hex::encode(hasher.finalize()))
}

#[cfg(test)]
mod tests {
    use std::path::PathBuf;

    use splendor_arena::{AgentCommand, AgentIdentity, ArenaReportV1};
    use splendor_core::{FullState, RulesetFingerprint};
    use splendor_replay::record_random_game;

    use super::*;
    use crate::{LeagueAgentV1, LeagueRoleV1, LEAGUE_MANIFEST_FORMAT, LEAGUE_VERSION};

    fn manifest() -> LeagueManifestV1 {
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
                        args: vec!["agent-ismcts".into()],
                    },
                },
            ],
            game_seeds: vec![1, 2],
            handshake_timeout_ms: 1_000,
            move_timeout_ms: 2_000,
            shutdown_grace_ms: 1_000,
        }
    }

    fn report(state: &FullState, replay: &ReplayV1) -> ArenaReportV1 {
        let fingerprint =
            RulesetFingerprint::from_str(replay.ruleset_fingerprint.as_str()).unwrap();
        ArenaReportV1::new(
            "m11-unit-game",
            replay.engine_version.clone(),
            "0.5",
            replay.ruleset.id.clone(),
            replay.ruleset_fingerprint.as_str(),
            replay.player_count,
            seed_commitment_v1(
                "m11-unit-game",
                replay.player_count,
                replay.seed,
                &fingerprint,
            ),
            vec![
                AgentIdentity {
                    seat: PlayerId(0),
                    agent_name: Some("splendor-cli-heuristic".into()),
                    agent_version: Some("0.1.0".into()),
                },
                AgentIdentity {
                    seat: PlayerId(1),
                    agent_name: Some("effective-splendor-ismcts-agent-v1".into()),
                    agent_version: Some("1".into()),
                },
            ],
            ArenaOutcomeV1::completed(
                state.result.clone().unwrap(),
                replay.steps.len() as u32,
                replay.final_state_hash.as_str().to_string(),
            ),
        )
    }

    #[test]
    fn manifest_expands_to_a_valid_seat_rotated_evaluation_plan() {
        let manifest = manifest();
        manifest.validate().unwrap();
        let plan = manifest.evaluation_plan_v1().unwrap();
        assert_eq!(plan.agents.len(), 2);
        assert_eq!(plan.game_seeds, vec![1, 2]);
        assert_eq!(league_manifest_hash_v1(&manifest).unwrap().len(), 64);
    }

    #[test]
    fn verified_replay_becomes_player_view_examples_without_seed_or_full_state() {
        let (state, replay) = record_random_game(2, 42, 7).unwrap();
        let report = report(&state, &replay);
        let dataset = build_training_dataset_v1(
            "m11-dataset-unit",
            &manifest(),
            &[DatasetReplaySourceV1 {
                source_id: "game-0001",
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
        assert_eq!(
            dataset.replays[0].agents_by_seat[1].policy_version,
            "ismcts-v1"
        );
    }

    #[test]
    fn duplicate_source_ids_are_rejected() {
        let (state, replay) = record_random_game(2, 1, 2).unwrap();
        let report = report(&state, &replay);
        let sources = [
            DatasetReplaySourceV1 {
                source_id: "same",
                replay: &replay,
                arena_report: &report,
            },
            DatasetReplaySourceV1 {
                source_id: "same",
                replay: &replay,
                arena_report: &report,
            },
        ];
        assert!(matches!(
            build_training_dataset_v1("dataset", &manifest(), &sources),
            Err(LeagueError::DuplicateReplaySource(_))
        ));
    }

    #[test]
    fn arena_report_must_bind_seed_outcome_and_runtime_identity() {
        let (state, replay) = record_random_game(2, 19, 3).unwrap();
        let mut mismatched = report(&state, &replay);
        mismatched.agents[1].agent_version = Some("other".into());
        assert!(matches!(
            build_training_dataset_v1(
                "dataset",
                &manifest(),
                &[DatasetReplaySourceV1 {
                    source_id: "bad-binding",
                    replay: &replay,
                    arena_report: &mismatched,
                }]
            ),
            Err(LeagueError::ArenaBinding { .. })
        ));

        let (_, other_replay) = record_random_game(2, 20, 3).unwrap();
        let valid_report_for_first = report(&state, &replay);
        assert!(matches!(
            build_training_dataset_v1(
                "dataset",
                &manifest(),
                &[DatasetReplaySourceV1 {
                    source_id: "bad-commitment",
                    replay: &other_replay,
                    arena_report: &valid_report_for_first,
                }]
            ),
            Err(LeagueError::ArenaBinding { .. })
        ));
    }
}
