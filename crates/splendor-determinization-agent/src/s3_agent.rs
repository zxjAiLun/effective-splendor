//! S3 live rollout-enhanced heuristic agent (Stage B; DESIGN_V2 @ 92af7bb,
//! base-policy semantics frozen in the Repair-1 record).
//!
//! Live semantics (frozen): every real decision computes the frozen
//! heuristic proposal EXACTLY ONCE using the persistent root RNG (the
//! `run_agent` seed = 20_260_812 — the standalone heuristic stream; unique
//! maxima consume no RNG, ties advance it exactly as the standalone agent).
//! Fast paths return the ACTUAL standalone heuristic action (including
//! RNG-tiebreaks):
//!   - phase != Main (`S3Path::HeuristicFastPath`)
//!   - legal_actions < 2 (`S3Path::HeuristicFastPath`)
//!   - |H*| > 1 (root tie: RNG-tiebroken a_H, NOT canonical-first;
//!     `S3Path::RootTieKeptA_H`)
//! Only Main-phase contexts with a unique heuristic optimum and a
//! non-trivial proposal set run the rollout comparison; simulation never
//! touches the root RNG.
//!
//! There is exactly ONE choose+explain implementation:
//! [`S3RolloutAgentPolicy::choose_action_explained`]. The [`AgentPolicy`]
//! implementation delegates to it, and every consumer (live play, review
//! trace) calls the same method, so the two can never drift apart.

use splendor_agent::{heuristic_term_scores, AgentError, AgentIdentity, AgentPolicy, DecisionContext};
use splendor_core::{Action, VisibleEvent};
use splendor_search::canonical_order;

use crate::s3_rollout::{s3_comparison, s3_m07_config, s3_n1_config, S3Path};
use crate::DeterminizationAgentPolicyV1;

/// Public name of the S3 live candidate.
pub const S3_AGENT_NAME: &str = "effective-splendor-s3-rollout-v1";

/// The persistent root RNG seed: identical to the standalone heuristic
/// agent's `--seed 20260812`.
pub const S3_ROOT_SEED: u64 = 20_260_812;

/// The full explained outcome of one live S3 decision: the chosen action
/// plus the honest proposal set and the decision path.
///
/// The proposal fields are `None` exactly when the decision returned on a
/// fast path and no proposal was ever evaluated; they are never backfilled
/// with the heuristic action.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct S3ExplainedDecision {
    /// The chosen action (identical to `AgentPolicy::choose_action`).
    pub action: Action,
    /// The base heuristic action, including its persistent root-RNG tie break.
    pub base_heuristic_action: Action,
    /// The n1 proposal, when the decision evaluated proposals.
    pub n1_proposal: Option<Action>,
    /// The M07 proposal, when the decision evaluated proposals.
    pub m07_proposal: Option<Action>,
    /// Which live path produced the decision.
    pub path: S3Path,
}

/// The S3 live policy.
pub struct S3RolloutAgentPolicy {
    n1_policy: DeterminizationAgentPolicyV1,
    m07_policy: DeterminizationAgentPolicyV1,
    ruleset: splendor_core::Ruleset,
    /// Descriptive counters (never gates).
    pub total_decisions: u64,
    pub fast_path_heuristic: u64,
    pub rollout_comparisons: u64,
    pub rollout_overrides: u64,
    pub ply_cap_fallbacks: u64,
}

impl S3RolloutAgentPolicy {
    pub fn new() -> Result<Self, AgentError> {
        let n1_policy = DeterminizationAgentPolicyV1::new(s3_n1_config())
            .map_err(|e| AgentError::Policy(e.to_string()))?;
        let m07_policy = DeterminizationAgentPolicyV1::new(s3_m07_config())
            .map_err(|e| AgentError::Policy(e.to_string()))?;
        Ok(Self {
            n1_policy,
            m07_policy,
            ruleset: splendor_core::Ruleset::base_v1(),
            total_decisions: 0,
            fast_path_heuristic: 0,
            rollout_comparisons: 0,
            rollout_overrides: 0,
            ply_cap_fallbacks: 0,
        })
    }

    /// The single S3 choose+explain implementation: fast-path detection, the
    /// persistent root-RNG heuristic action, the frozen n1/M07 proposals and
    /// the frozen rollout comparison, all in the live decision order.
    ///
    /// Exactly one implementation of this orchestration exists; live play
    /// ([`AgentPolicy::choose_action`]) and the review trace both call this
    /// method, so the two can never drift apart.
    pub fn choose_action_explained(
        &mut self,
        context: DecisionContext<'_>,
    ) -> Result<S3ExplainedDecision, crate::DeterminizationAgentError> {
        if context.meta.recipient_seat != context.observation.viewer {
            return Err(crate::DeterminizationAgentError::RecipientViewerMismatch);
        }
        self.total_decisions += 1;
        let legal = canonical_order(context.legal_actions);

        // The standalone heuristic proposal: argmax with RNG used ONLY on
        // exact-score ties (identical consumption to HeuristicAgentPolicy —
        // unique maxima never advance the stream).
        let totals: Vec<i64> = heuristic_term_scores(&context.observation, &legal)
            .iter()
            .map(|t| t.total())
            .collect();
        let max = *totals.iter().max().expect("non-empty legal actions");
        let best: Vec<usize> = totals
            .iter()
            .enumerate()
            .filter(|(_, s)| **s == max)
            .map(|(i, _)| i)
            .collect();
        let hs_len = best.len();
        let a_h = if best.len() == 1 {
            legal[best[0]]
        } else {
            legal[best[context.rng.index(best.len())]]
        };

        // Fast paths: non-Main, <2 legal actions (no proposal is computed),
        // or a root tie (the proposals would be discarded by the frozen tie
        // rule, so they are never computed either).
        let is_main = context.observation.public.phase == splendor_core::Phase::Main;
        let fast_path = if !is_main || legal.len() < 2 {
            Some(S3Path::HeuristicFastPath)
        } else if hs_len > 1 {
            Some(S3Path::RootTieKeptA_H)
        } else {
            None
        };
        if let Some(path) = fast_path {
            self.fast_path_heuristic += 1;
            return Ok(S3ExplainedDecision {
                action: a_h,
                base_heuristic_action: a_h,
                n1_proposal: None,
                m07_proposal: None,
                path,
            });
        }

        // Eligible: Main, >=2 legal, unique H optimum. Compute the frozen
        // search proposals on this context (their cost is part of the live
        // decision pipeline).
        let obs_hash = splendor_core::observation_hash(&context.observation).clone();
        let observation = context.observation.clone();
        let visible_history: Vec<VisibleEvent> = context.visible_history.to_vec();
        let a_n1 = {
            let mut rng = splendor_agent::StableRng::new(0);
            self.n1_policy
                .choose_action(DecisionContext {
                    observation: observation.clone(),
                    visible_history: &visible_history,
                    legal_actions: &legal,
                    meta: splendor_agent::PublicRequestMeta {
                        game_id: context.meta.game_id.clone(),
                        recipient_seat: context.meta.recipient_seat,
                        request_id: context.meta.request_id,
                        observation_hash: obs_hash.clone(),
                    },
                    rng: &mut rng,
                })
                .map_err(|e| e)?
        };
        let a_m07 = {
            let mut rng = splendor_agent::StableRng::new(0);
            self.m07_policy
                .choose_action(DecisionContext {
                    observation: observation.clone(),
                    visible_history: &visible_history,
                    legal_actions: &legal,
                    meta: splendor_agent::PublicRequestMeta {
                        game_id: context.meta.game_id.clone(),
                        recipient_seat: context.meta.recipient_seat,
                        request_id: context.meta.request_id,
                        observation_hash: obs_hash.clone(),
                    },
                    rng: &mut rng,
                })
                .map_err(|e| e)?
        };

        let decision = s3_comparison(
            &observation,
            &visible_history,
            &legal,
            a_h,
            a_n1,
            a_m07,
            self.ruleset,
        )
        .map_err(|e| crate::DeterminizationAgentError::Search(
                    splendor_imperfect_search::ImperfectSearchError::Engine(e),
               ))?;
        match decision.path {
            S3Path::RolloutComparison => {
                self.rollout_comparisons += 1;
                if decision.action != a_h {
                    self.rollout_overrides += 1;
                }
            }
            S3Path::PlyCapFallback => {
                self.ply_cap_fallbacks += 1;
            }
            S3Path::HeuristicFastPath | S3Path::RootTieKeptA_H => {
                // Unreachable: those paths returned before the comparison.
                self.fast_path_heuristic += 1;
            }
            S3Path::ProposalsAgreed => {
                self.fast_path_heuristic += 1;
            }
        }
        Ok(S3ExplainedDecision {
            action: decision.action,
            base_heuristic_action: decision.base_heuristic_action,
            n1_proposal: decision.n1_proposal,
            m07_proposal: decision.m07_proposal,
            path: decision.path,
        })
    }
}

impl Default for S3RolloutAgentPolicy {
    fn default() -> Self {
        Self::new().expect("frozen configs are valid")
    }
}

impl AgentPolicy for S3RolloutAgentPolicy {
    type Error = crate::DeterminizationAgentError;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, Self::Error> {
        // Single implementation: delegate to the explained entry point.
        self.choose_action_explained(context).map(|decision| decision.action)
    }
}

/// Run the S3 live agent over the standard NDJSON Agent SDK runtime with
/// the frozen root seed (the standalone heuristic stream).
pub fn run_s3_agent_v1<R, W, E>(
    input: R,
    output: W,
    diagnostics: E,
    identity: AgentIdentity<'_>,
) -> Result<(), AgentError>
where
    R: std::io::BufRead,
    W: std::io::Write,
    E: std::io::Write,
{
    let policy = S3RolloutAgentPolicy::new()?;
    splendor_agent::run_agent(input, output, diagnostics, identity, S3_ROOT_SEED, policy)
}

#[cfg(test)]
mod tests {
    use super::*;
    use splendor_agent::{PublicRequestMeta, StableRng};
    use splendor_core::{observation_hash, Audience, FullState, GameConfig, PlayerId};

    fn ctx_parts(state: &FullState, actor: PlayerId) -> (splendor_core::Observation, Vec<VisibleEvent>, Vec<Action>) {
        let observation = state.observation(actor);
        let history = splendor_core::visible_events(&state.log, Audience::Player(actor));
        let legal = canonical_order(&state.legal_actions());
        (observation, history, legal)
    }

    #[test]
    fn fast_paths_match_standalone_heuristic_step_by_step_including_ties() {
        // Drive both the S3 policy and the standalone heuristic policy over
        // the SAME decision sequence (same seed -> same RNG stream). Every
        // S3 decision must equal the standalone decision when the S3 path
        // is a fast path (non-Main / <2 legal / root tie), and the S3 root
        // RNG must never advance differently from the standalone stream
        // (rollout simulation never touches it).
        let mut s3 = S3RolloutAgentPolicy::new().unwrap();
        let mut standalone = splendor_agent::HeuristicAgentPolicy::new();

        // Synthesize a decision sequence: walk a real game with BOTH
        // policies deciding in lockstep on cloned states.
        let (state, _) = FullState::new(GameConfig {
            player_count: 2, seed: 20260909, ..Default::default()
        }).unwrap();
        let mut st_a = state.clone();
        let mut st_b = state.clone();
        let mut rng_a = StableRng::new(S3_ROOT_SEED);
        let mut rng_b = StableRng::new(S3_ROOT_SEED);

        for step in 0..80 {
            if st_a.is_terminal() { break; }
            let actor = st_a.current_player;
            let (obs, hist, legal) = ctx_parts(&st_a, actor);
            assert_eq!(ctx_parts(&st_b, actor).0, obs, "lockstep states diverge");
            let meta = PublicRequestMeta {
                game_id: "parity".into(), recipient_seat: actor,
                request_id: step as u64 + 1,
                observation_hash: observation_hash(&obs).clone(),
            };
            let a_s3 = s3.choose_action(DecisionContext {
                observation: obs.clone(), visible_history: &hist, legal_actions: &legal,
                meta: meta.clone(), rng: &mut rng_a,
            }).unwrap();
            let a_std = standalone.choose_action(DecisionContext {
                observation: obs, visible_history: &hist, legal_actions: &legal,
                meta, rng: &mut rng_b,
            }).unwrap();
            // On fast paths they must be identical; on rollout comparisons
            // they may differ (that is the candidate's purpose) — but then
            // the states diverge and the lockstep test ends.
            if a_s3 != a_std {
                // This must be a rollout override (S3 chose differently).
                assert!(s3.rollout_overrides >= 1, "divergence without a rollout override");
                break;
            }
            let _ = st_a.apply(a_s3);
            let _ = st_b.apply(a_std);
        }
    }

    #[test]
    fn counters_are_consistent() {
        let mut s3 = S3RolloutAgentPolicy::new().unwrap();
        assert_eq!(s3.total_decisions, 0);
        let (state, _) = FullState::new(GameConfig {
            player_count: 2, seed: 3, ..Default::default()
        }).unwrap();
        let actor = state.current_player;
        let (obs, hist, legal) = ctx_parts(&state, actor);
        let mut rng = StableRng::new(S3_ROOT_SEED);
        let meta = PublicRequestMeta {
            game_id: "c".into(), recipient_seat: actor, request_id: 1,
            observation_hash: observation_hash(&obs).clone(),
        };
        let _ = s3.choose_action(DecisionContext {
            observation: obs, visible_history: &hist, legal_actions: &legal,
            meta, rng: &mut rng,
        }).unwrap();
        assert_eq!(s3.total_decisions, 1);
        assert_eq!(
            s3.fast_path_heuristic + s3.rollout_comparisons + s3.ply_cap_fallbacks,
            1,
            "exactly one path counter per decision"
        );
    }

    #[test]
    fn choose_action_delegates_to_the_single_explained_implementation() {
        // The trait method and the explained entry point must be the same
        // code path: same action, same counters, same stream consumption.
        let (state, _) = FullState::new(GameConfig {
            player_count: 2, seed: 20260909, ..Default::default()
        }).unwrap();
        let actor = state.current_player;
        let (obs, hist, legal) = ctx_parts(&state, actor);
        let meta = PublicRequestMeta {
            game_id: "delegate".into(), recipient_seat: actor, request_id: 1,
            observation_hash: observation_hash(&obs).clone(),
        };
        let mut explained = S3RolloutAgentPolicy::new().unwrap();
        let mut delegating = S3RolloutAgentPolicy::new().unwrap();
        let mut rng_a = StableRng::new(S3_ROOT_SEED);
        let mut rng_b = StableRng::new(S3_ROOT_SEED);
        let decision = explained
            .choose_action_explained(DecisionContext {
                observation: obs.clone(), visible_history: &hist, legal_actions: &legal,
                meta: meta.clone(), rng: &mut rng_a,
            })
            .unwrap();
        let action = delegating
            .choose_action(DecisionContext {
                observation: obs, visible_history: &hist, legal_actions: &legal,
                meta, rng: &mut rng_b,
            })
            .unwrap();
        assert_eq!(decision.action, action);
        assert_eq!(explained.total_decisions, delegating.total_decisions);
        assert_eq!(explained.fast_path_heuristic, delegating.fast_path_heuristic);
        assert_eq!(explained.rollout_comparisons, delegating.rollout_comparisons);
        assert_eq!(explained.ply_cap_fallbacks, delegating.ply_cap_fallbacks);
        assert_eq!(explained.rollout_overrides, delegating.rollout_overrides);
    }

    #[test]
    fn explained_fast_paths_report_no_evaluated_proposals() {
        // Walk a heuristic self-play game into a real non-Main decision (a
        // ChooseNoble phase; seed 122 reaches one at ply 49) and check the S3
        // fast path: the ACTUAL heuristic action plus `None` proposals —
        // never a backfilled a_H. The root-tie fast path is covered
        // separately below; both are exercised end-to-end by the review
        // trace tests.
        let (mut state, _) = FullState::new(GameConfig {
            player_count: 2, seed: 122, ..Default::default()
        }).unwrap();
        let mut driver = splendor_agent::HeuristicAgentPolicy::new();
        let mut driver_rng = StableRng::new(1);
        let mut policy = S3RolloutAgentPolicy::new().unwrap();
        let mut rng = StableRng::new(S3_ROOT_SEED);
        for step in 0..400u64 {
            if state.is_terminal() {
                break;
            }
            let actor = state.current_player;
            let (obs, hist, legal) = ctx_parts(&state, actor);
            let meta = PublicRequestMeta {
                game_id: "fast-path".into(), recipient_seat: actor,
                request_id: step + 1,
                observation_hash: observation_hash(&obs).clone(),
            };
            if obs.public.phase != splendor_core::Phase::Main || legal.len() < 2 {
                let decision = policy
                    .choose_action_explained(DecisionContext {
                        observation: obs, visible_history: &hist, legal_actions: &legal,
                        meta, rng: &mut rng,
                    })
                    .unwrap();
                assert_eq!(decision.path, S3Path::HeuristicFastPath);
                assert_eq!(decision.action, decision.base_heuristic_action);
                assert!(decision.n1_proposal.is_none(), "fast path must not fabricate n1");
                assert!(decision.m07_proposal.is_none(), "fast path must not fabricate M07");
                return;
            }
            let action = driver
                .choose_action(DecisionContext {
                    observation: obs, visible_history: &hist, legal_actions: &legal,
                    meta, rng: &mut driver_rng,
                })
                .unwrap();
            state.apply(action).unwrap();
        }
        panic!("seed 122 must reach a non-Main / <2-legal decision");
    }

    #[test]
    fn explained_root_tie_keeps_the_rng_tiebroken_heuristic_action() {
        use crate::s3_rollout::h_star;
        for seed in 1..64u64 {
            let (state, _) = FullState::new(GameConfig {
                player_count: 2, seed, ..Default::default()
            }).unwrap();
            let actor = state.current_player;
            let (obs, hist, legal) = ctx_parts(&state, actor);
            if obs.public.phase != splendor_core::Phase::Main || legal.len() < 2 {
                continue;
            }
            let hs = h_star(&obs, &legal);
            if hs.len() < 2 {
                continue;
            }
            let mut expected_rng = StableRng::new(S3_ROOT_SEED);
            let expected = hs[expected_rng.index(hs.len())];
            let mut policy = S3RolloutAgentPolicy::new().unwrap();
            let mut rng = StableRng::new(S3_ROOT_SEED);
            let meta = PublicRequestMeta {
                game_id: "tie".into(), recipient_seat: actor, request_id: 1,
                observation_hash: observation_hash(&obs).clone(),
            };
            let decision = policy
                .choose_action_explained(DecisionContext {
                    observation: obs, visible_history: &hist, legal_actions: &legal,
                    meta, rng: &mut rng,
                })
                .unwrap();
            assert_eq!(decision.path, S3Path::RootTieKeptA_H);
            assert_eq!(decision.action, expected, "root tie keeps the RNG-tiebroken a_H");
            assert_eq!(decision.action, decision.base_heuristic_action);
            assert!(decision.n1_proposal.is_none());
            assert!(decision.m07_proposal.is_none());
            return;
        }
        panic!("no root-tie first decision found in seed sweep");
    }
}
