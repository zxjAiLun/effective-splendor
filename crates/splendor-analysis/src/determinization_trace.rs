//! M07 replay-wide root-determinization reviewer (AnalysisTraceV2).
//!
//! One process reads and verifies the replay once, then analyzes every
//! decision ply in a single pass, emitting exactly one trace document. The
//! per-ply sampling seed is derived from the frozen base seed, the decision
//! ply and the verified replay document hash — never from the referee replay
//! seed — so hidden state is never hinted at while the run stays reproducible.

use splendor_core::{observation_hash, visible_events, Audience, Ruleset};
use splendor_imperfect_search::{analyze_player_view_v1, RootDeterminizationConfigV1};
use splendor_replay::{replay_document_hash_v1, verify_replay_trace, ReplayV1};
use splendor_search::canonical_order;

use crate::review_trace::{build_catalog_v1, derive_determinization_ply_seed};
use crate::{
    AnalysisError, AnalysisFrameV2, AnalysisTraceV2, RefereeRevealV1, ReviewResultV2,
    ReviewerConfigV2, ReviewerIdentityV2, ReviewerResultKindV2, RootDeterminizationActionStatsV2,
    RootDeterminizationReviewResultV2, ANALYSIS_TRACE_FORMAT, REVIEW_TRACE_VERSION,
};

pub fn analyze_replay_determinization_v2(
    replay: &ReplayV1,
    reviewer: &ReviewerIdentityV2,
) -> Result<AnalysisTraceV2, AnalysisError> {
    analyze_replay_determinization_v2_with_progress(replay, reviewer, &mut |_, _, _| {})
}

pub fn analyze_replay_determinization_v2_with_progress(
    replay: &ReplayV1,
    reviewer: &ReviewerIdentityV2,
    progress: &mut dyn FnMut(u32, u32, u32),
) -> Result<AnalysisTraceV2, AnalysisError> {
    let ReviewerConfigV2::RootDeterminization(config) = &reviewer.config else {
        return Err(AnalysisError::Reviewer(
            "determinization reviewer requires a root-determinization config".into(),
        ));
    };
    if reviewer.result_kind != ReviewerResultKindV2::RootDeterminization {
        return Err(AnalysisError::Reviewer(
            "reviewer result kind is not root_determinization".into(),
        ));
    }
    config
        .validate()
        .map_err(|error| AnalysisError::Determinization(error.to_string()))?;
    let verified =
        verify_replay_trace(replay).map_err(|error| AnalysisError::Replay(error.to_string()))?;
    if verified.positions.len() != replay.steps.len() {
        return Err(AnalysisError::Replay(
            "verified trace length differs from replay".into(),
        ));
    }
    let replay_document_hash = replay_document_hash_v1(replay)
        .map_err(|error| AnalysisError::Replay(error.to_string()))?;

    let total = verified.positions.len() as u32;
    let mut frames = Vec::with_capacity(verified.positions.len());
    for position in &verified.positions {
        progress(position.ply, total, position.ply);
        frames.push(analyze_determinization_position(
            position,
            config,
            &replay_document_hash,
        )?);
    }

    let trace = AnalysisTraceV2 {
        format: ANALYSIS_TRACE_FORMAT.into(),
        version: REVIEW_TRACE_VERSION,
        engine_version: splendor_core::ENGINE_VERSION.into(),
        catalog_version: splendor_core::CATALOG_VERSION.into(),
        replay_version: replay.version,
        replay_document_hash,
        replay_final_state_hash: replay.final_state_hash.as_str().into(),
        ruleset_fingerprint: replay.ruleset_fingerprint.as_str().into(),
        player_count: replay.player_count,
        result: replay.result.clone(),
        reviewer: reviewer.clone(),
        catalog: build_catalog_v1(),
        frames,
    };
    trace.validate()?;
    Ok(trace)
}

fn analyze_determinization_position(
    position: &splendor_replay::VerifiedReplayTraceStep,
    config: &RootDeterminizationConfigV1,
    replay_document_hash: &str,
) -> Result<AnalysisFrameV2, AnalysisError> {
    bind_position(position)?;
    let actor = position.recorded_actor;
    let player_view = position.state.observation(actor);
    let visible_history = visible_events(&position.state.log, Audience::Player(actor));
    let legal_actions = canonical_order(&position.state.legal_actions());
    if !legal_actions.contains(&position.recorded_action) {
        return Err(binding(position.ply, "recorded action is not legal"));
    }

    let ply_seed =
        derive_determinization_ply_seed(config.sample_seed, position.ply, replay_document_hash);
    let ply_config = RootDeterminizationConfigV1 {
        sample_seed: ply_seed,
        ..*config
    };
    let analysis = analyze_player_view_v1(
        Ruleset::base_v1(),
        &player_view,
        &visible_history,
        ply_config,
    )
    .map_err(|error| AnalysisError::Determinization(error.to_string()))?;
    let result = analysis.result();
    if result.root_player != actor {
        return Err(binding(
            position.ply,
            "determinization root player does not match recorded actor",
        ));
    }
    let stats_actions = result
        .action_aggregates
        .iter()
        .map(|aggregate| aggregate.action)
        .collect::<Vec<_>>();
    if stats_actions != legal_actions || !legal_actions.contains(&result.action) {
        return Err(binding(
            position.ply,
            "determinization root actions do not match canonical legal actions",
        ));
    }
    let visible_event_count =
        u32::try_from(visible_history.len()).map_err(|_| AnalysisError::ArithmeticOverflow)?;
    let action_stats = result
        .action_aggregates
        .iter()
        .map(|aggregate| RootDeterminizationActionStatsV2 {
            action: aggregate.action,
            utility_sum_by_player: aggregate.utility_sum_by_player.clone(),
        })
        .collect::<Vec<_>>();
    Ok(AnalysisFrameV2 {
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
        review_result: ReviewResultV2::RootDeterminization(RootDeterminizationReviewResultV2 {
            recommended_action: result.action,
            sample_seed: result.sample_seed,
            sample_count: result.sample_count,
            action_stats,
            stats: result.stats.clone(),
        }),
        recommended_matches_recorded: result.action == position.recorded_action,
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

fn referee_projection(state: &splendor_core::FullState) -> RefereeRevealV1 {
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
    use splendor_imperfect_search::RootDeterminizationConfigV1;
    use splendor_replay::record_random_game;
    use splendor_search::SearchConfigV1;

    use super::*;
    use crate::{
        analysis_trace_hash_v2, review_cache_key_v2, ReviewerStatusV2, M07_REVIEWER_DISPLAY_NAME,
        M07_REVIEWER_ID,
    };

    fn config() -> RootDeterminizationConfigV1 {
        RootDeterminizationConfigV1 {
            sample_seed: 20260810,
            sample_count: 4,
            continuation_search: SearchConfigV1 {
                max_depth_turns: 1,
                max_nodes: 2_000,
            },
        }
    }

    fn reviewer() -> ReviewerIdentityV2 {
        ReviewerIdentityV2::new(
            M07_REVIEWER_ID,
            M07_REVIEWER_DISPLAY_NAME,
            ReviewerStatusV2::Champion,
            ReviewerResultKindV2::RootDeterminization,
            ReviewerConfigV2::RootDeterminization(config()),
            None,
        )
    }

    #[test]
    fn complete_replay_becomes_one_deterministic_trace() {
        let (_, replay) = record_random_game(2, 42, 9).unwrap();
        let first = analyze_replay_determinization_v2(&replay, &reviewer()).unwrap();
        let second = analyze_replay_determinization_v2(&replay, &reviewer()).unwrap();
        assert_eq!(first, second);
        first.validate().unwrap();
        assert_eq!(first.frames.len(), replay.steps.len());
        assert_eq!(
            analysis_trace_hash_v2(&first).unwrap(),
            analysis_trace_hash_v2(&second).unwrap()
        );
        assert!(first.frames.iter().all(|frame| {
            frame.legal_actions.contains(&frame.recorded_action)
                && frame.review_result.kind() == ReviewerResultKindV2::RootDeterminization
        }));
    }

    #[test]
    fn utility_vectors_match_player_count_and_are_never_q() {
        let (_, replay) = record_random_game(2, 7, 11).unwrap();
        let trace = analyze_replay_determinization_v2(&replay, &reviewer()).unwrap();
        for frame in &trace.frames {
            let ReviewResultV2::RootDeterminization(result) = &frame.review_result else {
                panic!("expected determinization result");
            };
            for stats in &result.action_stats {
                assert_eq!(
                    stats.utility_sum_by_player.len(),
                    trace.player_count as usize
                );
            }
        }
    }

    #[test]
    fn player_view_does_not_expose_opponent_blind_reserves() {
        let (_, replay) = record_random_game(2, 7, 11).unwrap();
        let trace = analyze_replay_determinization_v2(&replay, &reviewer()).unwrap();
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
                }
            }
        }
        assert!(blind_count > 0, "fixture must exercise a blind reserve");
    }

    #[test]
    fn tampered_replay_is_rejected() {
        let (_, mut replay) = record_random_game(2, 42, 9).unwrap();
        let step = replay.steps.last_mut().unwrap();
        // Corrupt the final action to diverge from the verifier.
        step.action = splendor_core::Action::Pass;
        assert!(matches!(
            analyze_replay_determinization_v2(&replay, &reviewer()),
            Err(AnalysisError::Replay(_))
        ));
    }

    #[test]
    fn cache_key_binds_full_reviewer_identity() {
        let (_, replay) = record_random_game(2, 42, 9).unwrap();
        let a = analyze_replay_determinization_v2(&replay, &reviewer()).unwrap();
        let mut b = a.clone();
        b.reviewer.algorithm_version += 1;
        assert_ne!(
            review_cache_key_v2(&a.replay_document_hash, &a.reviewer).unwrap(),
            review_cache_key_v2(&b.replay_document_hash, &b.reviewer).unwrap()
        );
    }

    #[test]
    fn champion_identity_cannot_be_relabelled() {
        let (_, replay) = record_random_game(2, 42, 9).unwrap();
        let mut trace = analyze_replay_determinization_v2(&replay, &reviewer()).unwrap();
        trace.reviewer.competitive_status = ReviewerStatusV2::Experimental;
        assert!(trace.validate().is_err());
        trace.reviewer.competitive_status = ReviewerStatusV2::Champion;
        trace.reviewer.provenance.metrics = vec!["win_probability".into()];
        assert!(trace.validate().is_err());
    }
}
