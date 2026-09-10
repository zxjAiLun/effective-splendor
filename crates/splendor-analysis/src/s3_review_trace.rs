//! S3 rollout reviewer (AnalysisTraceV2 `policy_recommendation`).
//!
//! One process reads and verifies the replay once, then reconstructs, for
//! every recorded decision ply and in ply order, the exact S3 decision the
//! live candidate would have made on that player's information set. The
//! reviewer is deliberately a *replication*, never a re-tuning:
//!
//! - Inputs per position are only the recorded actor's `Observation`, the
//!   actor-visible event history and the canonical legal action set. The
//!   referee projection is carried for display only and is never an input.
//! - The base heuristic action (including its root-RNG tie break) is computed
//!   with one persistent `StableRng(20_260_812)` per seat, advanced in replay
//!   ply order and consumed only on root heuristic ties — bit-identical to the
//!   standalone S3 agent stream.
//! - Eligible decisions (Main phase, >= 2 legal actions, unique heuristic
//!   optimum) run the frozen n1/M07 proposals and the frozen
//!   `s3_comparison` rollout engine; every other decision is a fast path that
//!   keeps the base heuristic action and never computes proposals.
//! - The result is the honest proposal set and the decision path. No utility,
//!   rank, prior, visit, Q or accuracy is ever written.

use splendor_agent::{AgentPolicy, DecisionContext, PublicRequestMeta, StableRng};
use splendor_belief::build_information_set_v1;
use splendor_core::{
    observation_hash, visible_events, Action, Audience, Observation, Phase, Ruleset, VisibleEvent,
};
use splendor_determinization_agent::s3_agent::S3_ROOT_SEED;
use splendor_determinization_agent::s3_rollout::{
    h_star, s3_comparison, s3_m07_config, s3_n1_config, S3Path,
};
use splendor_determinization_agent::DeterminizationAgentPolicyV1;
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

    let mut n1_policy = DeterminizationAgentPolicyV1::new(s3_n1_config())
        .map_err(|error| AnalysisError::Reviewer(format!("S3 n1 policy: {error}")))?;
    let mut m07_policy = DeterminizationAgentPolicyV1::new(s3_m07_config())
        .map_err(|error| AnalysisError::Reviewer(format!("S3 M07 policy: {error}")))?;
    // Frozen per-seat persistent root RNG streams (identical to the live
    // standalone S3 agent seed), advanced in replay ply order.
    let mut seat_rng = [StableRng::new(S3_ROOT_SEED), StableRng::new(S3_ROOT_SEED)];

    let total = verified.positions.len() as u32;
    let mut frames = Vec::with_capacity(verified.positions.len());
    for position in &verified.positions {
        progress(position.ply, total, position.ply);
        let seat = position.recorded_actor.index();
        if seat >= seat_rng.len() {
            return Err(binding(position.ply, "S3 review is frozen for two seats"));
        }
        frames.push(analyze_s3_position(
            position,
            &mut n1_policy,
            &mut m07_policy,
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

/// Internal S3 position decision (mirrors `S3Decision` for the fields the
/// review result exposes; the agent's own struct is not serialized here).
#[derive(Debug, Clone, PartialEq, Eq)]
struct S3PositionDecision {
    recommended_action: Action,
    base_heuristic_action: Action,
    n1_proposal: Action,
    m07_proposal: Action,
    path: S3ReviewPathV2,
}

fn analyze_s3_position(
    position: &splendor_replay::VerifiedReplayTraceStep,
    n1_policy: &mut DeterminizationAgentPolicyV1,
    m07_policy: &mut DeterminizationAgentPolicyV1,
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

    let decision = decide_s3_position(
        &player_view,
        &visible_history,
        &legal_actions,
        n1_policy,
        m07_policy,
        root_rng,
    )
    .map_err(|message| binding(position.ply, message))?;

    let visible_event_count =
        u32::try_from(visible_history.len()).map_err(|_| AnalysisError::ArithmeticOverflow)?;
    Ok(AnalysisFrameV2 {
        ply: position.ply,
        state_hash_before: position.state_hash.clone(),
        actor,
        recorded_action: position.recorded_action,
        observation_hash: observation_hash(&player_view).as_str().into(),
        visible_event_count,
        visible_history_hash: information_set.visible_history_hash().as_str().into(),
        information_set_hash: information_set.information_set_hash().as_str().into(),
        player_view,
        referee_reveal: referee_projection(&position.state),
        legal_actions,
        review_result: ReviewResultV2::PolicyRecommendation(PolicyRecommendationReviewResultV2 {
            recommended_action: decision.recommended_action,
            base_heuristic_action: decision.base_heuristic_action,
            n1_proposal: decision.n1_proposal,
            m07_proposal: decision.m07_proposal,
            decision_path: decision.path,
            recommended_differs_from_base_heuristic: decision.recommended_action
                != decision.base_heuristic_action,
        }),
        recommended_matches_recorded: decision.recommended_action == position.recorded_action,
    })
}

/// The exact live S3 decision procedure, replicated from
/// `S3RolloutAgentPolicy::choose_action` on the same information-safe inputs.
///
/// The only game-state inputs are `(observation, visible_history,
/// legal_actions)`; `root_rng` is the caller's persistent per-seat stream and
/// is consumed only on a root heuristic tie (unique maxima consume nothing).
fn decide_s3_position(
    observation: &Observation,
    visible_history: &[VisibleEvent],
    legal_actions: &[Action],
    n1_policy: &mut DeterminizationAgentPolicyV1,
    m07_policy: &mut DeterminizationAgentPolicyV1,
    root_rng: &mut StableRng,
) -> Result<S3PositionDecision, String> {
    let is_main = observation.public.phase == Phase::Main;
    let hs_len = h_star(observation, legal_actions).len();
    if !is_main || legal_actions.len() < 2 || hs_len > 1 {
        // Fast path: the ACTUAL standalone heuristic action, including its
        // RNG tie break. Proposals were never computed; report the base
        // heuristic action for all proposal fields.
        let a_h = base_heuristic_action(observation, legal_actions, root_rng)?;
        return Ok(S3PositionDecision {
            recommended_action: a_h,
            base_heuristic_action: a_h,
            n1_proposal: a_h,
            m07_proposal: a_h,
            path: S3ReviewPathV2::HeuristicFastPath,
        });
    }
    let a_h = base_heuristic_action(observation, legal_actions, root_rng)?;
    let engine_observation_hash = observation_hash(observation);
    let meta = |request_id: u64| PublicRequestMeta {
        game_id: "s3-review".to_owned(),
        recipient_seat: observation.viewer,
        request_id,
        observation_hash: engine_observation_hash.clone(),
    };
    let a_n1 = {
        let mut rng = StableRng::new(0);
        n1_policy
            .choose_action(DecisionContext {
                observation: observation.clone(),
                visible_history,
                legal_actions,
                meta: meta(1),
                rng: &mut rng,
            })
            .map_err(|error| format!("S3 n1 proposal failed: {error}"))?
    };
    let a_m07 = {
        let mut rng = StableRng::new(0);
        m07_policy
            .choose_action(DecisionContext {
                observation: observation.clone(),
                visible_history,
                legal_actions,
                meta: meta(2),
                rng: &mut rng,
            })
            .map_err(|error| format!("S3 M07 proposal failed: {error}"))?
    };
    let decision = s3_comparison(
        observation,
        visible_history,
        legal_actions,
        a_h,
        a_n1,
        a_m07,
        Ruleset::base_v1(),
    )
    .map_err(|error| format!("S3 rollout comparison failed: {error}"))?;
    Ok(S3PositionDecision {
        recommended_action: decision.action,
        base_heuristic_action: decision.base_heuristic_action,
        n1_proposal: decision.n1_proposal,
        m07_proposal: decision.m07_proposal,
        path: map_s3_path(decision.path),
    })
}

/// The standalone heuristic action with the frozen tie rule: unique maximum
/// consumes no RNG, a tie advances the persistent stream by exactly one draw.
fn base_heuristic_action(
    observation: &Observation,
    legal_actions: &[Action],
    root_rng: &mut StableRng,
) -> Result<Action, String> {
    let totals: Vec<i64> = splendor_agent::heuristic_term_scores(observation, legal_actions)
        .iter()
        .map(|t| t.total())
        .collect();
    let max = *totals
        .iter()
        .max()
        .ok_or_else(|| "no legal actions for the S3 heuristic".to_owned())?;
    let best: Vec<usize> = totals
        .iter()
        .enumerate()
        .filter(|(_, score)| **score == max)
        .map(|(index, _)| index)
        .collect();
    if best.len() == 1 {
        Ok(legal_actions[best[0]])
    } else {
        let pick = root_rng.index(best.len());
        Ok(legal_actions[best[pick]])
    }
}

fn map_s3_path(path: S3Path) -> S3ReviewPathV2 {
    match path {
        // The reviewer's fast path always emits `HeuristicFastPath` itself;
        // this mapping is defensive for the shared decision type.
        S3Path::RootTieKeptA_H => S3ReviewPathV2::HeuristicFastPath,
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
    use splendor_agent::{AgentPolicy, DecisionContext, PublicRequestMeta, StableRng};
    use splendor_core::{
        observation_hash, FullState, GameConfig, CATALOG_VERSION, ENGINE_VERSION,
    };
    use splendor_determinization_agent::s3_agent::{S3RolloutAgentPolicy, S3_AGENT_NAME};
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

    /// Record a real game where seat 0 plays the live S3 candidate (its own
    /// persistent per-seat RNG stream) and seat 1 plays S3 as well, so both
    /// seats are exact S3 trajectories. Returns the replay plus counters of
    /// root heuristic ties and eligible comparison contexts encountered.
    fn record_s3_game(seed: u64) -> (ReplayV1, usize, usize) {
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
        let mut ties = 0usize;
        let mut eligible = 0usize;
        let mut request_id = 0u64;
        while !recorder.is_terminal() {
            let actor = recorder.current_player();
            let state = recorder.state();
            let observation = state.observation(actor);
            let visible_history = visible_events(&state.log, Audience::Player(actor));
            let legal = canonical_order(&state.legal_actions());
            let hs = h_star(&observation, &legal);
            if hs.len() > 1 {
                ties += 1;
            }
            if observation.public.phase == Phase::Main && legal.len() >= 2 && hs.len() == 1 {
                eligible += 1;
            }
            request_id += 1;
            let meta = PublicRequestMeta {
                game_id: "s3-review-parity".to_owned(),
                recipient_seat: actor,
                request_id,
                observation_hash: observation_hash(&observation).clone(),
            };
            let action = policies[actor.index()]
                .choose_action(DecisionContext {
                    observation,
                    visible_history: &visible_history,
                    legal_actions: &legal,
                    meta,
                    rng: &mut rngs[actor.index()],
                })
                .unwrap();
            recorder.apply(action).unwrap();
        }
        let (_, replay) = recorder.finish().unwrap();
        (replay, ties, eligible)
    }

    #[test]
    fn reviewer_reproduces_recorded_s3_decisions() {
        // Gate 1: every recorded S3 decision must be reproduced exactly by
        // the reviewer, per seat, with the persistent per-seat RNG advanced
        // in ply order. Any stream-ordering error (tie consumption, per-seat
        // routing, actor/history mismatch) desynchronizes and fails here.
        let (replay, ties, eligible) = record_s3_game(1);
        assert!(ties > 0, "fixture must exercise a root heuristic tie");
        assert!(eligible > 0, "fixture must exercise an eligible comparison");
        let trace = analyze_replay_s3_v2(&replay, &s3_reviewer()).unwrap();
        assert_eq!(trace.frames.len(), replay.steps.len());
        for frame in &trace.frames {
            assert_eq!(
                frame.review_result.recommended_action(),
                frame.recorded_action,
                "ply {} actor {} S3 recommendation diverged from the recorded S3 action",
                frame.ply,
                frame.actor.index()
            );
            assert!(frame.recommended_matches_recorded);
        }
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
    fn fast_path_frames_keep_the_heuristic_action_and_never_fabricate_proposals() {
        let trace = short_trace();
        let mut fast_paths = 0usize;
        for frame in &trace.frames {
            let ReviewResultV2::PolicyRecommendation(result) = &frame.review_result else {
                panic!("expected a policy recommendation result");
            };
            if result.decision_path == S3ReviewPathV2::HeuristicFastPath {
                fast_paths += 1;
                assert_eq!(result.recommended_action, result.base_heuristic_action);
                assert_eq!(result.n1_proposal, result.base_heuristic_action);
                assert_eq!(result.m07_proposal, result.base_heuristic_action);
                assert!(!result.recommended_differs_from_base_heuristic);
            }
            assert_eq!(
                result.recommended_differs_from_base_heuristic,
                result.recommended_action != result.base_heuristic_action
            );
        }
        assert!(fast_paths > 0, "fixture must exercise a fast path");
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
        // The decision function's only game inputs are the observation, the
        // actor-visible history and the canonical legal set; two invocations
        // with identical public inputs and identical fresh streams produce
        // identical decisions (no hidden state can enter by construction).
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
        let mut n1_a = DeterminizationAgentPolicyV1::new(s3_n1_config()).unwrap();
        let mut m07_a = DeterminizationAgentPolicyV1::new(s3_m07_config()).unwrap();
        let mut n1_b = DeterminizationAgentPolicyV1::new(s3_n1_config()).unwrap();
        let mut m07_b = DeterminizationAgentPolicyV1::new(s3_m07_config()).unwrap();
        let mut rng_a = StableRng::new(S3_ROOT_SEED);
        let mut rng_b = StableRng::new(S3_ROOT_SEED);
        let first = decide_s3_position(
            &observation,
            &visible_history,
            &legal,
            &mut n1_a,
            &mut m07_a,
            &mut rng_a,
        )
        .unwrap();
        let second = decide_s3_position(
            &observation,
            &visible_history,
            &legal,
            &mut n1_b,
            &mut m07_b,
            &mut rng_b,
        )
        .unwrap();
        assert_eq!(first, second);
        assert!(legal.contains(&first.recommended_action));
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
        let mut n1_a = DeterminizationAgentPolicyV1::new(s3_n1_config()).unwrap();
        let mut m07_a = DeterminizationAgentPolicyV1::new(s3_m07_config()).unwrap();
        let mut n1_b = DeterminizationAgentPolicyV1::new(s3_n1_config()).unwrap();
        let mut m07_b = DeterminizationAgentPolicyV1::new(s3_m07_config()).unwrap();
        let mut rng_a = StableRng::new(S3_ROOT_SEED);
        let mut rng_b = StableRng::new(S3_ROOT_SEED);
        let decision_a = decide_s3_position(
            &observation_a,
            &visible_history,
            &legal_a,
            &mut n1_a,
            &mut m07_a,
            &mut rng_a,
        )
        .unwrap();
        let decision_b = decide_s3_position(
            &observation_b,
            &visible_history,
            &legal_b,
            &mut n1_b,
            &mut m07_b,
            &mut rng_b,
        )
        .unwrap();
        assert_eq!(decision_a, decision_b);
    }

    #[test]
    fn root_tie_consumes_exactly_one_persistent_stream_draw() {
        // Find a context with a root heuristic tie, then verify the decision
        // is exactly `base[rng.index(tie_len)]` on the persistent stream: the
        // same draw a fresh stream would produce, with no other consumption.
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
            let hs = h_star(&observation, &legal);
            if hs.len() < 2 {
                continue;
            }
            let mut n1 = DeterminizationAgentPolicyV1::new(s3_n1_config()).unwrap();
            let mut m07 = DeterminizationAgentPolicyV1::new(s3_m07_config()).unwrap();
            let mut expected_rng = StableRng::new(7);
            let pick = expected_rng.index(hs.len());
            let mut root_rng = StableRng::new(7);
            let decision = decide_s3_position(
                &observation,
                &visible_history,
                &legal,
                &mut n1,
                &mut m07,
                &mut root_rng,
            )
            .unwrap();
            assert_eq!(decision.recommended_action, hs[pick]);
            assert_eq!(
                decision.recommended_action, decision.base_heuristic_action,
                "root ties keep the base heuristic action"
            );
            assert_eq!(decision.path, S3ReviewPathV2::HeuristicFastPath);
            return;
        }
        panic!("no root-tie fixture found in seed sweep");
    }

    #[test]
    fn cache_key_binds_s3_identity_and_config() {
        let trace = short_trace();
        let base = review_cache_key_v2(&trace.replay_document_hash, &trace.reviewer).unwrap();

        let mut versioned = trace.clone();
        versioned.reviewer.algorithm_version += 1;
        assert_ne!(
            base,
            review_cache_key_v2(&versioned.replay_document_hash, &versioned.reviewer).unwrap()
        );

        let mut reconfigured = trace.clone();
        let ReviewerConfigV2::PolicyRecommendation(config) = &reconfigured.reviewer.config else {
            panic!("expected policy recommendation config");
        };
        let mut drifted = config.clone();
        drifted.ply_cap += 1;
        reconfigured.reviewer.config = ReviewerConfigV2::PolicyRecommendation(drifted);
        assert_ne!(
            base,
            review_cache_key_v2(
                &reconfigured.replay_document_hash,
                &reconfigured.reviewer
            )
            .unwrap()
        );
        let ReviewerConfigV2::PolicyRecommendation(drifted) = &reconfigured.reviewer.config else {
            panic!("expected policy recommendation config");
        };
        assert!(
            drifted.validate().is_err(),
            "a drifted config must not claim the frozen v1 identity"
        );
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
