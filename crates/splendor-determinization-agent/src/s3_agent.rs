//! S3 live rollout-enhanced heuristic agent (Stage B; DESIGN_V2 @ 92af7bb,
//! base-policy semantics frozen in the Repair-1 record).
//!
//! Live semantics (frozen): every real decision computes the frozen
//! heuristic proposal EXACTLY ONCE using the persistent root RNG (the
//! `run_agent` seed = 20_260_812 — the standalone heuristic stream; unique
//! maxima consume no RNG, ties advance it exactly as the standalone agent).
//! Fast paths return the ACTUAL standalone heuristic action (including
//! RNG-tiebreaks):
//!   - phase != Main
//!   - legal_actions < 2
//!   - |H*| > 1 (root tie: RNG-tiebroken a_H, NOT canonical-first)
//! Only Main-phase contexts with a unique heuristic optimum and a
//! non-trivial proposal set run the rollout comparison; simulation never
//! touches the root RNG.

use splendor_agent::{heuristic_term_scores, AgentError, AgentIdentity, AgentPolicy, DecisionContext};
use splendor_core::{Action, Observation, VisibleEvent};
use splendor_search::canonical_order;

use crate::s3_rollout::{s3_comparison, s3_m07_config, s3_n1_config, S3Path};
use crate::DeterminizationAgentPolicyV1;

/// Public name of the S3 live candidate.
pub const S3_AGENT_NAME: &str = "effective-splendor-s3-rollout-v1";

/// The persistent root RNG seed: identical to the standalone heuristic
/// agent's `--seed 20260812`.
pub const S3_ROOT_SEED: u64 = 20_260_812;

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
}

impl Default for S3RolloutAgentPolicy {
    fn default() -> Self {
        Self::new().expect("frozen configs are valid")
    }
}

impl AgentPolicy for S3RolloutAgentPolicy {
    type Error = crate::DeterminizationAgentError;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, Self::Error> {
        if context.meta.recipient_seat != context.observation.viewer {
            return Err(crate::DeterminizationAgentError::RecipientViewerMismatch);
        }
        self.total_decisions += 1;
        let legal = canonical_order(context.legal_actions);

        // Fast paths: non-Main, <2 legal actions, or a root tie -> the ACTUAL
        // standalone heuristic action (RNG-tiebroken, consuming context.rng
        // exactly as the standalone agent would).
        let is_main = context.observation.public.phase == splendor_core::Phase::Main;
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
        if !is_main || legal.len() < 2 || hs_len > 1 {
            self.fast_path_heuristic += 1;
            return Ok(a_h);
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
            _ => {
                // ProposalsAgreed can occur here (|C|==1 after dedup).
                self.fast_path_heuristic += 1;
            }
        }
        Ok(decision.action)
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
}
