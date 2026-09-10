//! S3 rollout reviewer (AnalysisTraceV2 `policy_recommendation`).
//!
//! One process reads and verifies the replay once, then reconstructs, for
//! every recorded decision ply and in ply order, the exact S3 decision the
//! live candidate would have made on that player's information set.
//!
//! - Inputs per position are only the recorded actor's `Observation`, the
//!   actor-visible event history and the canonical legal action set. The
//!   referee projection is carried for display only and is never an input.
//! - The decision itself is NOT re-implemented here. The reviewer builds one
//!   real [`S3RolloutAgentPolicy`] per seat with its own persistent
//!   `StableRng(S3_ROOT_SEED)`, exactly as live S3-vs-S3 play builds its
//!   agents, and calls the single production `choose_action_explained` entry
//!   point per ply. Live play and the review therefore cannot drift apart.
//! - The result is the honest proposal set (`None` when the decision was a
//!   fast path that never evaluated proposals) and the decision path. No
//!   utility, rank, prior, visit, Q, accuracy or rollout outcome score is
//!   ever written.

use splendor_agent::{DecisionContext, PublicRequestMeta, StableRng};
use splendor_belief::build_information_set_v1;
use splendor_core::{observation_hash, visible_events, Audience, Ruleset};
use splendor_determinization_agent::s3_agent::{S3RolloutAgentPolicy, S3_ROOT_SEED};
use splendor_determinization_agent::s3_rollout::S3Path;
use splendor_replay::{replay_document_hash_v1, verify_replay_trace, ReplayV1};
use splendor_search::canonical_order;

use crate::review_trace::{build_catalog_v1, S3ReviewPathV2};
use crate::{
    AnalysisError, AnalysisFrameV2, AnalysisTraceV2, PolicyRecommendationReviewResultV2,
    RefereeRevealV1, ReviewResultV2, ReviewerConfigV2, ReviewerIdentityV2,
    ReviewerResultKindV2, ANALYSIS_TRACE_FORMAT, REVIEW_TRACE_VERSION,
};

pub fn analyze_replay_s3_v2(
    replay: &ReplayV1,
    reviewer: &ReviewerIdentityV2,
) -> Result<AnalysisTraceV2, AnalysisError> {
    analyze_replay_s3_v2_with_progress(replay, reviewer, &mut |_, _, _| {})
}

pub fn analyze_replay_s3_v2_with_progress(
    replay: &ReplayV1,
    reviewer: &ReviewerIdentityV2,
    progress: &mut dyn FnMut(u32, u32, u32),
) -> Result<AnalysisTraceV2, AnalysisError> {
    let ReviewerConfigV2::PolicyRecommendation(config) = &reviewer.config else {
        return Err(AnalysisError::Reviewer(
            "S3 reviewer requires a policy-recommendation config".into(),
        ));
    };
    if reviewer.result_kind != ReviewerResultKindV2::PolicyRecommendation {
        return Err(AnalysisError::Reviewer(
            "reviewer result kind is not policy_recommendation".into(),
        ));
    }
    config
        .validate()
        .map_err(|error| AnalysisError::Reviewer(format!("S3 review config: {error}")))?;
    if reviewer.checkpoint_hash.is_some() {
        return Err(AnalysisError::Reviewer(
            "S3 reviewer must not bind a checkpoint".into(),
        ));
    }
    if replay.player_count != 2 {
        return Err(AnalysisError::Reviewer(
            "S3 review is frozen for 2-player replays".into(),
        ));
    }
    let verified =
        verify_replay_trace(replay).map_err(|error| AnalysisError::Replay(error.to_string()))?;
    if verified.positions.len() != replay.steps.len() {
        return Err(AnalysisError::Replay(
            "verified trace length differs from replay".into(),
        ));
    }
    let replay_document_hash = replay_document_hash_v1(replay)
        .map_err(|error| AnalysisError::Replay(error.to_string()))?;

    // One real production S3 policy per seat, each with its own persistent
    // root RNG stream — exactly how live S3-vs-S3 play builds its agents
    // (the policy instance carries the frozen n1/M07 proposal policies).
    let mut seat_policies = [
        S3RolloutAgentPolicy::new()
            .map_err(|error| AnalysisError::Reviewer(format!("S3 policy: {error}")))?,
        S3RolloutAgentPolicy::new()
            .map_err(|error| AnalysisError::Reviewer(format!("S3 policy: {error}")))?,
    ];
    let mut seat_rng = [StableRng::new(S3_ROOT_SEED), StableRng::new(S3_ROOT_SEED)];

    let total = verified.positions.len() as u32;
    let mut frames = Vec::with_capacity(verified.positions.len());
    for position in &verified.positions {
        progress(position.ply, total, position.ply);
        let seat = position.recorded_actor.index();
        if seat >= seat_policies.len() {
            return Err(binding(position.ply, "S3 review is frozen for two seats"));
        }
        frames.push(analyze_s3_position(
            position,
            &mut seat_policies[seat],
            &mut seat_rng[seat],
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

fn analyze_s3_position(
    position: &splendor_replay::VerifiedReplayTraceStep,
    policy: &mut S3RolloutAgentPolicy,
    root_rng: &mut StableRng,
) -> Result<AnalysisFrameV2, AnalysisError> {
    bind_position(position)?;
    let actor = position.recorded_actor;
    let player_view = position.state.observation(actor);
    let visible_history = visible_events(&position.state.log, Audience::Player(actor));
    let legal_actions = canonical_order(&position.state.legal_actions());
    if legal_actions.is_empty() || !legal_actions.contains(&position.recorded_action) {
        return Err(binding(position.ply, "recorded action is not legal"));
    }
    let information_set = build_information_set_v1(Ruleset::base_v1(), &player_view, &visible_history)
        .map_err(|error| binding(position.ply, format!("information set build failed: {error}")))?;

    let observation_hash_value = observation_hash(&player_view).clone();
    let decision = policy
        .choose_action_explained(DecisionContext {
            observation: player_view.clone(),
            visible_history: &visible_history,
            legal_actions: &legal_actions,
            meta: PublicRequestMeta {
                game_id: "s3-review".to_owned(),
                recipient_seat: actor,
                request_id: u64::from(position.ply) + 1,
                observation_hash: observation_hash_value.clone(),
            },
            rng: root_rng,
        })
        .map_err(|error| binding(position.ply, format!("S3 decision failed: {error}")))?;

    let visible_event_count =
        u32::try_from(visible_history.len()).map_err(|_| AnalysisError::ArithmeticOverflow)?;
    Ok(AnalysisFrameV2 {
        ply: position.ply,
        state_hash_before: position.state_hash.clone(),
        actor,
        recorded_action: position.recorded_action,
        observation_hash: observation_hash_value.as_str().into(),
        visible_event_count,
        visible_history_hash: information_set.visible_history_hash().as_str().into(),
        information_set_hash: information_set.information_set_hash().as_str().into(),
        player_view,
        referee_reveal: referee_projection(&position.state),
        legal_actions,
        review_result: ReviewResultV2::PolicyRecommendation(PolicyRecommendationReviewResultV2 {
            recommended_action: decision.action,
            base_heuristic_action: decision.base_heuristic_action,
            n1_proposal: decision.n1_proposal,
            m07_proposal: decision.m07_proposal,
            decision_path: map_s3_path(decision.path),
            recommended_differs_from_base_heuristic: decision.action
                != decision.base_heuristic_action,
        }),
        recommended_matches_recorded: decision.action == position.recorded_action,
    })
}

fn map_s3_path(path: S3Path) -> S3ReviewPathV2 {
    match path {
        // Both live fast paths (non-Main / <2 legal actions, and root ties)
        // returned before any proposal was evaluated; the review schema
        // reports them as one fast path.
        S3Path::HeuristicFastPath | S3Path::RootTieKeptA_H => S3ReviewPathV2::HeuristicFastPath,
        S3Path::ProposalsAgreed => S3ReviewPathV2::ProposalsAgreed,
        S3Path::PlyCapFallback => S3ReviewPathV2::PlyCapFallback,
        S3Path::RolloutComparison => S3ReviewPathV2::RolloutComparison,
    }
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
    use super::*;
    use splendor_agent::{DecisionContext, PublicRequestMeta, StableRng};
    use splendor_core::{
        observation_hash, FullState, GameConfig, Phase, CATALOG_VERSION, ENGINE_VERSION,
    };
    use splendor_determinization_agent::s3_agent::S3_AGENT_NAME;
    use splendor_determinization_agent::s3_rollout::h_star;
    use splendor_replay::{record_random_game, ReplayRecorder};

    use crate::{
        analysis_trace_hash_v2, review_cache_key_v2, ReviewerStatusV2, S3ReviewConfigV2,
        S3_REVIEWER_ALGORITHM_ID, S3_REVIEWER_DISPLAY_NAME, S3_REVIEWER_ID, S3_REVIEWER_METRICS,
    };

    fn s3_reviewer() -> ReviewerIdentityV2 {
        ReviewerIdentityV2::new(
            S3_REVIEWER_ID,
            S3_REVIEWER_DISPLAY_NAME,
            ReviewerStatusV2::Champion,
            ReviewerResultKindV2::PolicyRecommendation,
            ReviewerConfigV2::PolicyRecommendation(S3ReviewConfigV2::frozen_v1()),
            None,
        )
    }

    /// Counters of one in-test recorded S3-vs-S3 game (non-vacuity evidence
    /// for Gate 1).
    #[derive(Debug, Default, PartialEq, Eq)]
    struct RecordingStats {
        root_ties_by_seat: [usize; 2],
        proposals_evaluated: usize,
        rollout_comparisons: usize,
        overrides: usize,
    }

    /// Record a real game where BOTH seats play the real production S3
    /// policy (one policy + one persistent per-seat root RNG stream per
    /// seat, exactly as live play), returning the replay and non-vacuity
    /// counters of the recorded decision paths.
    fn record_s3_game(seed: u64) -> (ReplayV1, RecordingStats) {
        let mut recorder = ReplayRecorder::new(GameConfig {
            player_count: 2,
            seed,
            ..Default::default()
        })
        .unwrap();
        let mut policies = [
            S3RolloutAgentPolicy::new().unwrap(),
            S3RolloutAgentPolicy::new().unwrap(),
        ];
        let mut rngs = [StableRng::new(S3_ROOT_SEED), StableRng::new(S3_ROOT_SEED)];
        let mut stats = RecordingStats::default();
        let mut request_id = 0u64;
        while !recorder.is_terminal() {
            let actor = recorder.current_player();
            let state = recorder.state();
            let observation = state.observation(actor);
            let visible_history = visible_events(&state.log, Audience::Player(actor));
            let legal = canonical_order(&state.legal_actions());
            request_id += 1;
            let meta = PublicRequestMeta {
                game_id: "s3-review-parity".to_owned(),
                recipient_seat: actor,
                request_id,
                observation_hash: observation_hash(&observation).clone(),
            };
            let decision = policies[actor.index()]
                .choose_action_explained(DecisionContext {
                    observation,
                    visible_history: &visible_history,
                    legal_actions: &legal,
                    meta,
                    rng: &mut rngs[actor.index()],
                })
                .unwrap();
            match decision.path {
                S3Path::RootTieKeptA_H => stats.root_ties_by_seat[actor.index()] += 1,
                S3Path::HeuristicFastPath => {}
                S3Path::ProposalsAgreed
                | S3Path::PlyCapFallback
                | S3Path::RolloutComparison => {
                    stats.proposals_evaluated += 1;
                    assert!(
                        decision.n1_proposal.is_some() && decision.m07_proposal.is_some(),
                        "comparison paths always report both evaluated proposals"
                    );
                    if decision.path == S3Path::RolloutComparison {
                        stats.rollout_comparisons += 1;
                    }
                    if decision.action != decision.base_heuristic_action {
                        stats.overrides += 1;
                    }
                }
            }
            recorder.apply(decision.action).unwrap();
        }
        let (_, replay) = recorder.finish().unwrap();
        (replay, stats)
    }

    #[test]
    fn reviewer_reproduces_recorded_s3_decisions() {
        // Gate 1 (non-vacuous): a deterministic replay recorded with the REAL
        // production S3 policy must be reproduced exactly, ply by ply, by the
        // reviewer — which itself calls the same production policy. Any
        // stream-ordering error (tie consumption, per-seat routing,
        // actor/history mismatch) desynchronizes and fails here.
        //
        // The seed below is a fixed deterministic fixture chosen (small
        // bounded dev search, no corpus scan) because it exercises every
        // required non-vacuity condition; the assertions below re-prove that
        // on every test run.
        const GATE1_SEED: u64 = 1;
        let (replay, stats) = record_s3_game(GATE1_SEED);
        assert!(
            stats.root_ties_by_seat[0] > 0,
            "fixture must exercise a root heuristic tie on seat 0 (seed {GATE1_SEED})"
        );
        assert!(
            stats.root_ties_by_seat[1] > 0,
            "fixture must exercise a root heuristic tie on seat 1 (seed {GATE1_SEED})"
        );
        assert!(
            stats.rollout_comparisons > 0,
            "fixture must exercise a rollout comparison (seed {GATE1_SEED})"
        );
        assert!(
            stats.overrides > 0,
            "fixture must exercise an S3 override of the base heuristic (seed {GATE1_SEED})"
        );

        let trace = analyze_replay_s3_v2(&replay, &s3_reviewer()).unwrap();
        assert_eq!(trace.frames.len(), replay.steps.len());
        let mut comparison_frames = 0usize;
        let mut override_frames = 0usize;
        for frame in &trace.frames {
            let ReviewResultV2::PolicyRecommendation(result) = &frame.review_result else {
                panic!("expected a policy recommendation result");
            };
            if result.decision_path == S3ReviewPathV2::RolloutComparison {
                comparison_frames += 1;
            }
            if result.recommended_differs_from_base_heuristic {
                override_frames += 1;
            }
            assert_eq!(
                frame.review_result.recommended_action(),
                frame.recorded_action,
                "ply {} actor {} S3 recommendation diverged from the recorded S3 action",
                frame.ply,
                frame.actor.index()
            );
            assert!(frame.recommended_matches_recorded);
        }
        assert_eq!(
            comparison_frames, stats.rollout_comparisons,
            "every recorded rollout comparison must reappear in the trace"
        );
        assert_eq!(
            override_frames, stats.overrides,
            "every recorded override must reappear in the trace"
        );
        assert!(comparison_frames > 0, "trace must contain rollout_comparison frames");
        assert!(
            override_frames > 0,
            "trace must contain frames where S3 overrode the base heuristic"
        );
    }

    /// One shared S3 review of a short (58-ply) random replay for the
    /// schema-level tests, so the expensive analysis runs once per process.
    fn short_trace() -> &'static AnalysisTraceV2 {
        static TRACE: std::sync::OnceLock<AnalysisTraceV2> = std::sync::OnceLock::new();
        TRACE.get_or_init(|| {
            let (_, replay) = record_random_game(2, 38, 3).unwrap();
            analyze_replay_s3_v2(&replay, &s3_reviewer()).unwrap()
        })
    }

    #[test]
    fn trace_is_deterministic_and_identity_bound() {
        let (_, replay) = record_random_game(2, 73, 3).unwrap();
        let first = analyze_replay_s3_v2(&replay, &s3_reviewer()).unwrap();
        let second = analyze_replay_s3_v2(&replay, &s3_reviewer()).unwrap();
        assert_eq!(first, second);
        assert_eq!(
            analysis_trace_hash_v2(&first).unwrap(),
            analysis_trace_hash_v2(&second).unwrap()
        );
        assert_eq!(first.reviewer.algorithm_id, S3_REVIEWER_ALGORITHM_ID);
        assert_eq!(
            first.reviewer.algorithm_id,
            S3_AGENT_NAME,
            "S3 review algorithm identity must equal the live candidate name"
        );
        assert_eq!(first.reviewer.algorithm_id, "effective-splendor-s3-rollout-v1");
        assert_eq!(first.reviewer.checkpoint_hash, None);
        assert_eq!(
            first.reviewer.provenance.metrics,
            S3_REVIEWER_METRICS
                .iter()
                .map(|metric| metric.to_string())
                .collect::<Vec<_>>()
        );
        assert_eq!(first.engine_version, ENGINE_VERSION);
        assert_eq!(first.catalog_version, CATALOG_VERSION);
        assert!(first.frames.iter().all(|frame| {
            frame.legal_actions.contains(&frame.recorded_action)
                && frame.review_result.kind() == ReviewerResultKindV2::PolicyRecommendation
        }));
    }

    #[test]
    fn fast_path_frames_report_no_proposals_and_comparison_frames_report_both() {
        let trace = short_trace();
        let mut fast_paths = 0usize;
        let mut comparisons = 0usize;
        for frame in &trace.frames {
            let ReviewResultV2::PolicyRecommendation(result) = &frame.review_result else {
                panic!("expected a policy recommendation result");
            };
            if result.decision_path == S3ReviewPathV2::HeuristicFastPath {
                fast_paths += 1;
                assert_eq!(result.recommended_action, result.base_heuristic_action);
                assert!(
                    result.n1_proposal.is_none(),
                    "fast paths must never fabricate an n1 proposal"
                );
                assert!(
                    result.m07_proposal.is_none(),
                    "fast paths must never fabricate an M07 proposal"
                );
                assert!(!result.recommended_differs_from_base_heuristic);
            } else {
                comparisons += 1;
                let n1 = result.n1_proposal.expect("comparison path reports n1");
                let m07 = result.m07_proposal.expect("comparison path reports M07");
                assert!(frame.legal_actions.contains(&n1));
                assert!(frame.legal_actions.contains(&m07));
            }
            assert_eq!(
                result.recommended_differs_from_base_heuristic,
                result.recommended_action != result.base_heuristic_action
            );
        }
        assert!(fast_paths > 0, "fixture must exercise a fast path");
        assert!(comparisons > 0, "fixture must exercise an evaluated comparison");
    }

    #[test]
    fn player_view_does_not_expose_opponent_blind_reserves() {
        let trace = short_trace();
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
    fn s3_decision_depends_only_on_information_safe_inputs() {
        // The production entry point's only game inputs are the observation,
        // the actor-visible history and the canonical legal set; two
        // invocations with identical public inputs and identical fresh
        // streams produce identical decisions (no hidden state can enter by
        // construction).
        let (state, _) = FullState::new(GameConfig {
            player_count: 2,
            seed: 20260910,
            ..Default::default()
        })
        .unwrap();
        let actor = state.current_player;
        let observation = state.observation(actor);
        let visible_history = visible_events(&state.log, Audience::Player(actor));
        let legal = canonical_order(&state.legal_actions());
        let meta = || PublicRequestMeta {
            game_id: "s3-iso".to_owned(),
            recipient_seat: actor,
            request_id: 1,
            observation_hash: observation_hash(&observation).clone(),
        };
        let mut policy_a = S3RolloutAgentPolicy::new().unwrap();
        let mut policy_b = S3RolloutAgentPolicy::new().unwrap();
        let mut rng_a = StableRng::new(S3_ROOT_SEED);
        let mut rng_b = StableRng::new(S3_ROOT_SEED);
        let first = policy_a
            .choose_action_explained(DecisionContext {
                observation: observation.clone(),
                visible_history: &visible_history,
                legal_actions: &legal,
                meta: meta(),
                rng: &mut rng_a,
            })
            .unwrap();
        let second = policy_b
            .choose_action_explained(DecisionContext {
                observation: observation.clone(),
                visible_history: &visible_history,
                legal_actions: &legal,
                meta: meta(),
                rng: &mut rng_b,
            })
            .unwrap();
        assert_eq!(first, second);
        assert!(legal.contains(&first.action));
    }

    #[test]
    fn s3_decision_is_blind_to_the_true_hidden_world() {
        // Gate 2 counterfactual: two DIFFERENT true hidden completions of the
        // same root information set (identical observation + visible history)
        // must produce the same S3 decision. Referee truth cannot leak into
        // the recommendation because it is never an input.
        let (state, _) = FullState::new(GameConfig {
            player_count: 2,
            seed: 20260910,
            ..Default::default()
        })
        .unwrap();
        let viewer = state.current_player;
        let observation = state.observation(viewer);
        let visible_history = visible_events(&state.log, Audience::Player(viewer));
        let information_set =
            build_information_set_v1(Ruleset::base_v1(), &observation, &visible_history).unwrap();
        let world_a = splendor_belief::sample_determinization_v1(&information_set, 43_300_101, 0)
            .unwrap();
        let world_b = splendor_belief::sample_determinization_v1(&information_set, 43_300_101, 1)
            .unwrap();
        assert_ne!(
            world_a.state_hash(),
            world_b.state_hash(),
            "fixture must produce two different hidden worlds"
        );
        let observation_a = world_a.state().observation(viewer);
        let observation_b = world_b.state().observation(viewer);
        assert_eq!(observation_a, observation_b, "same information set, same view");
        let legal_a = canonical_order(&world_a.state().legal_actions());
        let legal_b = canonical_order(&world_b.state().legal_actions());
        assert_eq!(legal_a, legal_b);
        let mut policy_a = S3RolloutAgentPolicy::new().unwrap();
        let mut policy_b = S3RolloutAgentPolicy::new().unwrap();
        let mut rng_a = StableRng::new(S3_ROOT_SEED);
        let mut rng_b = StableRng::new(S3_ROOT_SEED);
        let decision_a = policy_a
            .choose_action_explained(DecisionContext {
                observation: observation_a,
                visible_history: &visible_history,
                legal_actions: &legal_a,
                meta: PublicRequestMeta {
                    game_id: "s3-blind-a".to_owned(),
                    recipient_seat: viewer,
                    request_id: 1,
                    observation_hash: observation_hash(&observation).clone(),
                },
                rng: &mut rng_a,
            })
            .unwrap();
        let decision_b = policy_b
            .choose_action_explained(DecisionContext {
                observation: observation_b,
                visible_history: &visible_history,
                legal_actions: &legal_b,
                meta: PublicRequestMeta {
                    game_id: "s3-blind-b".to_owned(),
                    recipient_seat: viewer,
                    request_id: 1,
                    observation_hash: observation_hash(&observation).clone(),
                },
                rng: &mut rng_b,
            })
            .unwrap();
        assert_eq!(decision_a, decision_b);
    }

    #[test]
    fn root_tie_consumes_exactly_one_persistent_stream_draw() {
        // Find a context with a root heuristic tie, then verify the decision
        // is exactly `hs[rng.index(tie_len)]` on the persistent stream: the
        // same draw a fresh stream would produce, with no other consumption,
        // and no evaluated proposals.
        for seed in 1..200u64 {
            let (state, _) = FullState::new(GameConfig {
                player_count: 2,
                seed,
                ..Default::default()
            })
            .unwrap();
            let actor = state.current_player;
            let observation = state.observation(actor);
            let visible_history = visible_events(&state.log, Audience::Player(actor));
            let legal = canonical_order(&state.legal_actions());
            if observation.public.phase != Phase::Main || legal.len() < 2 {
                continue;
            }
            let hs = h_star(&observation, &legal);
            if hs.len() < 2 {
                continue;
            }
            let mut expected_rng = StableRng::new(7);
            let pick = expected_rng.index(hs.len());
            let mut policy = S3RolloutAgentPolicy::new().unwrap();
            let mut root_rng = StableRng::new(7);
            let decision = policy
                .choose_action_explained(DecisionContext {
                    observation: observation.clone(),
                    visible_history: &visible_history,
                    legal_actions: &legal,
                    meta: PublicRequestMeta {
                        game_id: "s3-tie".to_owned(),
                        recipient_seat: actor,
                        request_id: 1,
                        observation_hash: observation_hash(&observation).clone(),
                    },
                    rng: &mut root_rng,
                })
                .unwrap();
            assert_eq!(decision.path, S3Path::RootTieKeptA_H);
            assert_eq!(decision.action, hs[pick]);
            assert_eq!(
                decision.action, decision.base_heuristic_action,
                "root ties keep the base heuristic action"
            );
            assert!(decision.n1_proposal.is_none());
            assert!(decision.m07_proposal.is_none());
            return;
        }
        panic!("no root-tie fixture found in seed sweep");
    }

    #[test]
    fn cache_key_binds_s3_identity_and_exact_proposal_configs() {
        let trace = short_trace();
        let base = review_cache_key_v2(&trace.replay_document_hash, &trace.reviewer).unwrap();

        let mut versioned = trace.clone();
        versioned.reviewer.algorithm_version += 1;
        assert_ne!(
            base,
            review_cache_key_v2(&versioned.replay_document_hash, &versioned.reviewer).unwrap()
        );

        // Each drift mutation must BOTH flip the cache key (the exact config
        // is part of the cached identity) AND fail `validate()` (the trace
        // cannot claim the frozen v1 identity).
        let check_drift = |label: &str, mutate: &dyn Fn(&mut S3ReviewConfigV2)| {
            let mut drifted = trace.clone();
            let ReviewerConfigV2::PolicyRecommendation(config) = &mut drifted.reviewer.config
            else {
                panic!("expected policy recommendation config");
            };
            mutate(config);
            assert_ne!(
                base,
                review_cache_key_v2(&drifted.replay_document_hash, &drifted.reviewer).unwrap(),
                "{label} drift must flip the cache key"
            );
            let ReviewerConfigV2::PolicyRecommendation(config) = &drifted.reviewer.config else {
                panic!("expected policy recommendation config");
            };
            assert!(
                config.validate().is_err(),
                "{label} drift must not claim the frozen v1 identity"
            );
        };

        check_drift("m07 max_nodes", &|config| {
            config.m07_config.continuation_search.max_nodes = 4_000;
        });
        check_drift("n1 max_nodes", &|config| {
            config.n1_config.continuation_search.max_nodes = 2;
        });
        check_drift("n1 sample_count", &|config| {
            config.n1_config.sample_count = 1;
        });
        check_drift("ply_cap", &|config| {
            config.ply_cap += 1;
        });
    }

    #[test]
    fn s3_reviewer_identity_cannot_be_relabelled() {
        let mut trace = short_trace().clone();
        trace.reviewer.competitive_status = ReviewerStatusV2::Experimental;
        assert!(trace.validate().is_err());
        trace.reviewer.competitive_status = ReviewerStatusV2::Champion;
        trace.reviewer.provenance.metrics = vec!["accuracy".into()];
        assert!(trace.validate().is_err());
        trace.reviewer.provenance.metrics = S3_REVIEWER_METRICS
            .iter()
            .map(|metric| metric.to_string())
            .collect();
        trace.reviewer.checkpoint_hash = Some("11".repeat(32));
        assert!(trace.validate().is_err());
    }

    #[test]
    fn non_two_player_replays_are_rejected() {
        let (_, replay) = record_random_game(2, 42, 9).unwrap();
        let mut four_player = replay.clone();
        four_player.player_count = 4;
        assert!(analyze_replay_s3_v2(&four_player, &s3_reviewer()).is_err());
    }

    #[test]
    fn mismatched_config_kind_fails_closed() {
        let (_, replay) = record_random_game(2, 42, 9).unwrap();
        let reviewer = ReviewerIdentityV2::new(
            S3_REVIEWER_ID,
            S3_REVIEWER_DISPLAY_NAME,
            ReviewerStatusV2::Champion,
            ReviewerResultKindV2::RootDeterminization,
            ReviewerConfigV2::PolicyRecommendation(S3ReviewConfigV2::frozen_v1()),
            None,
        );
        assert!(analyze_replay_s3_v2(&replay, &reviewer).is_err());
    }
}
