use splendor_catalog::{all_cards, all_nobles};
use splendor_core::{observation_hash, visible_events, Audience, FullState, Ruleset};
use splendor_learning::{model_checkpoint_hash_v1, PolicyValueCheckpointV1, PolicyValueModelV1};
use splendor_neural_search::{analyze_player_view_neural_ismcts_v1, NeuralIsmctsConfigV1};
use splendor_replay::{replay_document_hash_v1, verify_replay_trace, ReplayV1};
use splendor_search::canonical_order;

use crate::{
    AnalysisCardV1, AnalysisCatalogV1, AnalysisError, AnalysisFrameV1, AnalysisNobleV1,
    AnalysisTraceV1, RefereeRevealV1, ANALYSIS_TRACE_FORMAT, ANALYSIS_TRACE_VERSION,
};

pub fn analyze_replay_neural_v1(
    replay: &ReplayV1,
    checkpoint: &PolicyValueCheckpointV1,
    config: &NeuralIsmctsConfigV1,
) -> Result<AnalysisTraceV1, AnalysisError> {
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
    let verified =
        verify_replay_trace(replay).map_err(|error| AnalysisError::Replay(error.to_string()))?;
    if verified.positions.len() != replay.steps.len() {
        return Err(AnalysisError::Replay(
            "verified trace length differs from replay".into(),
        ));
    }

    let mut frames = Vec::with_capacity(verified.positions.len());
    for position in &verified.positions {
        frames.push(analyze_position(position, &model, config)?);
    }
    let replay_document_hash = replay_document_hash_v1(replay)
        .map_err(|error| AnalysisError::Replay(error.to_string()))?;
    let catalog = AnalysisCatalogV1 {
        cards: all_cards()
            .iter()
            .map(|card| AnalysisCardV1 {
                id: card.id,
                tier: card.tier,
                bonus: card.bonus,
                prestige: card.prestige,
                cost: card.cost,
            })
            .collect(),
        nobles: all_nobles()
            .iter()
            .map(|noble| AnalysisNobleV1 {
                id: noble.id,
                prestige: noble.prestige,
                requirements: noble.requirements,
            })
            .collect(),
    };
    let trace = AnalysisTraceV1 {
        format: ANALYSIS_TRACE_FORMAT.into(),
        version: ANALYSIS_TRACE_VERSION,
        engine_version: splendor_core::ENGINE_VERSION.into(),
        catalog_version: splendor_core::CATALOG_VERSION.into(),
        replay_version: replay.version,
        replay_document_hash,
        replay_final_state_hash: replay.final_state_hash.as_str().into(),
        ruleset_fingerprint: replay.ruleset_fingerprint.as_str().into(),
        player_count: replay.player_count,
        result: replay.result.clone(),
        analyzer_label: "M13 Neural ISMCTS".into(),
        model_id: model.checkpoint().model_id.clone(),
        checkpoint_hash,
        value_scale: splendor_neural_search::NEURAL_VALUE_SCALE_V1,
        config: config.clone(),
        catalog,
        frames,
    };
    trace.validate()?;
    Ok(trace)
}

fn analyze_position(
    position: &splendor_replay::VerifiedReplayTraceStep,
    model: &PolicyValueModelV1,
    config: &NeuralIsmctsConfigV1,
) -> Result<AnalysisFrameV1, AnalysisError> {
    bind_position(position)?;
    let actor = position.recorded_actor;
    let player_view = position.state.observation(actor);
    let visible_history = visible_events(&position.state.log, Audience::Player(actor));
    let legal_actions = canonical_order(&position.state.legal_actions());
    if !legal_actions.contains(&position.recorded_action) {
        return Err(binding(position.ply, "recorded action is not legal"));
    }
    let analysis = analyze_player_view_neural_ismcts_v1(
        Ruleset::base_v1(),
        &player_view,
        &visible_history,
        model,
        config,
    )
    .map_err(|error| AnalysisError::Neural {
        ply: position.ply,
        message: error.to_string(),
    })?;
    let result = analysis.result().clone();
    let result_actions = result
        .action_stats
        .iter()
        .map(|stats| stats.action)
        .collect::<Vec<_>>();
    if result_actions != legal_actions || !legal_actions.contains(&result.action) {
        return Err(binding(
            position.ply,
            "neural root actions do not match canonical legal actions",
        ));
    }
    let visible_event_count =
        u32::try_from(visible_history.len()).map_err(|_| AnalysisError::ArithmeticOverflow)?;
    Ok(AnalysisFrameV1 {
        ply: position.ply,
        state_hash_before: position.state_hash.clone(),
        actor,
        recorded_action: position.recorded_action,
        observation_hash: observation_hash(&player_view).as_str().into(),
        visible_event_count,
        visible_history_hash: analysis.visible_history_hash().as_str().into(),
        information_set_hash: analysis.information_set_hash().as_str().into(),
        player_view,
        referee_reveal: referee_projection(&position.state),
        legal_actions,
        recommended_matches_recorded: result.action == position.recorded_action,
        neural_result: result,
    })
}

fn bind_position(position: &splendor_replay::VerifiedReplayTraceStep) -> Result<(), AnalysisError> {
    if position.state.current_player != position.recorded_actor {
        return Err(binding(
            position.ply,
            "recorded actor differs from current player",
        ));
    }
    if position.state.is_terminal() {
        return Err(binding(position.ply, "decision state is terminal"));
    }
    Ok(())
}

fn referee_projection(state: &FullState) -> RefereeRevealV1 {
    RefereeRevealV1 {
        seed: state.seed,
        decks: state.decks.clone(),
        players: state.players.clone(),
    }
}

fn binding(ply: u32, message: impl Into<String>) -> AnalysisError {
    AnalysisError::Binding {
        ply,
        message: message.into(),
    }
}

#[cfg(test)]
mod tests {
    use splendor_learning::{
        model_checkpoint_hash_v1, ModelParametersV1, PolicyValueCheckpointV1, ACTION_FEATURES_V1,
        MAX_PLAYERS_V1, OBSERVATION_FEATURES_V1, POLICY_VALUE_CHECKPOINT_FORMAT,
        POLICY_VALUE_CHECKPOINT_VERSION, REPRESENTATION_VERSION_V1,
    };
    use splendor_replay::record_random_game;

    use super::*;
    use crate::analysis_trace_hash_v1;

    fn checkpoint() -> PolicyValueCheckpointV1 {
        let hidden = 4usize;
        PolicyValueCheckpointV1 {
            format: POLICY_VALUE_CHECKPOINT_FORMAT.into(),
            version: POLICY_VALUE_CHECKPOINT_VERSION,
            model_id: "m14a-test-model".into(),
            representation_version: REPRESENTATION_VERSION_V1.into(),
            observation_features: OBSERVATION_FEATURES_V1 as u32,
            action_features: ACTION_FEATURES_V1 as u32,
            hidden_features: hidden as u32,
            max_players: MAX_PLAYERS_V1 as u8,
            source_dataset_id: "m14a-test-dataset".into(),
            source_dataset_hash: "11".repeat(32),
            league_manifest_hash: "22".repeat(32),
            evaluation_plan_hash: "33".repeat(32),
            evaluation_report_hash: "44".repeat(32),
            training_config_hash: "55".repeat(32),
            training_contract_version: None,
            search_teacher_targets_hash: None,
            model_architecture_version: None,
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
                policy_hidden_bias: vec![],
                policy_output_weights: vec![],
                value_encoder_weights: vec![],
                value_encoder_bias: vec![],
            },
        }
    }

    fn config(checkpoint: &PolicyValueCheckpointV1) -> NeuralIsmctsConfigV1 {
        NeuralIsmctsConfigV1 {
            sample_seed: 20260811,
            simulations: 2,
            max_depth_turns: 1,
            puct_exploration_milli: 1_500,
            expected_checkpoint_hash: model_checkpoint_hash_v1(checkpoint).unwrap(),
        }
    }

    #[test]
    fn complete_replay_becomes_a_deterministic_bound_trace() {
        let (_, replay) = record_random_game(2, 42, 9).unwrap();
        let checkpoint = checkpoint();
        let first = analyze_replay_neural_v1(&replay, &checkpoint, &config(&checkpoint)).unwrap();
        let second = analyze_replay_neural_v1(&replay, &checkpoint, &config(&checkpoint)).unwrap();
        assert_eq!(first, second);
        first.validate().unwrap();
        assert_eq!(first.frames.len(), replay.steps.len());
        assert_eq!(
            analysis_trace_hash_v1(&first).unwrap(),
            analysis_trace_hash_v1(&second).unwrap()
        );
        assert!(first.frames.iter().all(|frame| {
            frame.legal_actions.contains(&frame.recorded_action)
                && frame.neural_result.stats.root_visits == 2
        }));
    }

    #[test]
    fn player_view_does_not_expose_opponent_blind_reserves() {
        let (_, replay) = record_random_game(2, 7, 11).unwrap();
        let checkpoint = checkpoint();
        let trace = analyze_replay_neural_v1(&replay, &checkpoint, &config(&checkpoint)).unwrap();
        let mut blind_count = 0usize;
        for frame in &trace.frames {
            for player in &frame.referee_reveal.players {
                if player.id == frame.actor {
                    continue;
                }
                for reserved in player.reserved.iter().filter(|reserved| reserved.from_deck) {
                    blind_count += 1;
                    let public_player = &frame.player_view.public.players[player.id.index()];
                    assert!(!public_player.public_reserved.contains(&reserved.card));
                    assert!(!frame
                        .player_view
                        .private
                        .reserved
                        .iter()
                        .any(|own| own.card == reserved.card));
                }
            }
        }
        assert!(blind_count > 0, "fixture must exercise a blind reserve");
    }

    #[test]
    fn checkpoint_mismatch_fails_before_replay_analysis() {
        let (_, replay) = record_random_game(2, 1, 2).unwrap();
        let checkpoint = checkpoint();
        let mut bad = config(&checkpoint);
        bad.expected_checkpoint_hash = "00".repeat(32);
        assert!(matches!(
            analyze_replay_neural_v1(&replay, &checkpoint, &bad),
            Err(AnalysisError::Learning(message)) if message.contains("checkpoint hash mismatch")
        ));
    }

    #[test]
    fn tampered_frozen_catalog_content_is_rejected() {
        let (_, replay) = record_random_game(2, 42, 9).unwrap();
        let checkpoint = checkpoint();
        let mut trace =
            analyze_replay_neural_v1(&replay, &checkpoint, &config(&checkpoint)).unwrap();
        trace.catalog.cards[52].prestige ^= 1;
        assert!(matches!(
            trace.validate(),
            Err(AnalysisError::InvalidTrace(message))
                if message.contains("frozen dense catalog")
        ));
    }

    #[test]
    fn out_of_domain_referee_card_and_noble_ids_fail_closed() {
        let (_, replay) = record_random_game(2, 42, 9).unwrap();
        let checkpoint = checkpoint();
        let trace = analyze_replay_neural_v1(&replay, &checkpoint, &config(&checkpoint)).unwrap();

        let mut bad_card = trace.clone();
        bad_card.frames[0].referee_reveal.decks[0][0] = splendor_core::CardId(u8::MAX);
        assert!(matches!(
            bad_card.validate(),
            Err(AnalysisError::InvalidTrace(message)) if message.contains("card id out of range")
        ));

        let mut bad_noble = trace;
        bad_noble.frames[0].referee_reveal.players[0]
            .nobles
            .push(splendor_core::NobleId(u8::MAX));
        assert!(matches!(
            bad_noble.validate(),
            Err(AnalysisError::InvalidTrace(message)) if message.contains("noble id out of range")
        ));
    }
}
