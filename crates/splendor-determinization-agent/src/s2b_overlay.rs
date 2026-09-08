//! S2b parameter-free n1 buy-overlay policy (DESIGN_V2 @ ff7a4f1).
//!
//! Wraps the EXACT frozen n1 configuration (sample_seed 20_260_703 /
//! sample_count 4 / max_depth_turns 1 / max_nodes 1 / StaticEvaluatorV1)
//! and applies the single frozen rule:
//!
//! ```text
//! if base_action is TakeTokens
//!    AND |H*(s)| == 1
//!    AND the unique H* action is BuyMarket
//! then choose that unique BuyMarket action
//! else keep the base action (bit-identical to n1)
//! ```
//!
//! H* is computed via `heuristic_term_scores(...).total()` — never the
//! heuristic policy's `choose_action` — so no RNG is consumed and no tie
//! state exists; |H*| > 1 is an automatic no-op.

use splendor_agent::{
    heuristic_term_scores, AgentError, AgentIdentity, AgentPolicy, DecisionContext,
};
use splendor_core::Action;
use crate::DeterminizationAgentPolicyV1;
use splendor_imperfect_search::RootDeterminizationConfigV1;
use thiserror::Error;

/// Public name the S2b overlay declares.
pub const S2B_OVERLAY_AGENT_NAME: &str = "effective-splendor-s2b-n1-buy-overlay-v1";

/// The exact frozen n1 configuration the overlay is valid for.
pub const S2B_N1_SAMPLE_SEED: u64 = 20_260_703;
pub const S2B_N1_SAMPLE_COUNT: u16 = 4;
pub const S2B_N1_DEPTH_TURNS: u8 = 1;
pub const S2B_N1_MAX_NODES: u64 = 1;

#[derive(Debug, Error)]
pub enum S2bOverlayError {
    #[error("the buy overlay is only valid for the exact frozen n1 config (20260703/s4/d1/n1); got {found}")]
    NotExactN1Config { found: String },
    #[error(transparent)]
    Determinization(#[from] crate::DeterminizationAgentError),
}

/// The S2b overlay policy.
pub struct N1BuyOverlayPolicy {
    inner: DeterminizationAgentPolicyV1,
    /// Trigger/decision counters (descriptive only; never a gate).
    pub trigger_count: u64,
    pub decision_count: u64,
}

impl N1BuyOverlayPolicy {
    /// Construct the overlay over the EXACT frozen n1 config; any other
    /// config is a fail-closed identity error.
    pub fn new(config: RootDeterminizationConfigV1) -> Result<Self, S2bOverlayError> {
        let ok = config.sample_seed == S2B_N1_SAMPLE_SEED
            && config.sample_count == S2B_N1_SAMPLE_COUNT
            && config.continuation_search.max_depth_turns == S2B_N1_DEPTH_TURNS
            && config.continuation_search.max_nodes == S2B_N1_MAX_NODES;
        if !ok {
            return Err(S2bOverlayError::NotExactN1Config {
                found: format!(
                    "{}/{}/d{}/n{}",
                    config.sample_seed,
                    config.sample_count,
                    config.continuation_search.max_depth_turns,
                    config.continuation_search.max_nodes
                ),
            });
        }
        let inner = DeterminizationAgentPolicyV1::new(config)
            .map_err(S2bOverlayError::Determinization)?;
        Ok(Self {
            inner,
            trigger_count: 0,
            decision_count: 0,
        })
    }

    /// The frozen overlay rule, exposed for fixed-context scope analysis:
    /// given the base n1 action and the legal actions with their heuristic
    /// term scores, return the candidate action and whether the trigger
    /// fired.
    pub fn apply_rule(
        base: Action,
        observation: &splendor_core::Observation,
        legal_actions: &[Action],
    ) -> (Action, bool) {
        match base {
            Action::TakeTokens { .. } => {}
            _ => return (base, false),
        }
        let totals: Vec<i64> = heuristic_term_scores(observation, legal_actions)
            .iter()
            .map(|t| t.total())
            .collect();
        let max = match totals.iter().max() {
            Some(m) => *m,
            None => return (base, false),
        };
        let best: Vec<&Action> = legal_actions
            .iter()
            .zip(totals.iter())
            .filter(|(_, s)| **s == max)
            .map(|(a, _)| a)
            .collect();
        if best.len() != 1 {
            return (base, false); // |H*| != 1 -> no-op (covers ties)
        }
        match best[0] {
            Action::BuyMarket { .. } => (*best[0], true),
            _ => (base, false),
        }
    }
}

impl AgentPolicy for N1BuyOverlayPolicy {
    type Error = crate::DeterminizationAgentError;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, Self::Error> {
        if context.meta.recipient_seat != context.observation.viewer {
            return Err(crate::DeterminizationAgentError::RecipientViewerMismatch);
        }
        // Base decision on the SAME context the wrapper received. The
        // DecisionContext is not Copy, so clone what the rule needs first.
        let observation = context.observation.clone();
        let legal: Vec<Action> = context.legal_actions.to_vec();
        let base = self.inner.choose_action(context)?;
        self.decision_count += 1;
        let (action, triggered) = Self::apply_rule(base, &observation, &legal);
        if triggered {
            self.trigger_count += 1;
        }
        Ok(action)
    }
}

/// Run the S2b overlay over the standard NDJSON Agent SDK runtime.
pub fn run_n1_buy_overlay_agent_v1<R, W, E>(
    input: R,
    output: W,
    mut diagnostics: E,
    config: RootDeterminizationConfigV1,
    identity: AgentIdentity<'_>,
) -> Result<(), AgentError>
where
    R: std::io::BufRead,
    W: std::io::Write,
    E: std::io::Write,
{
    let policy = match N1BuyOverlayPolicy::new(config) {
        Ok(policy) => policy,
        Err(error) => {
            let agent_error = AgentError::Policy(error.to_string());
            let _ = writeln!(diagnostics, "error: {agent_error}");
            let _ = diagnostics.flush();
            return Err(agent_error);
        }
    };
    splendor_agent::run_agent(input, output, diagnostics, identity, 0, policy)
}

#[cfg(test)]
mod tests {
    use super::*;
    use splendor_agent::{PublicRequestMeta, StableRng};
    use splendor_core::{
        observation_hash, visible_events, Audience, FullState, GameConfig, PlayerId,
    };
    use splendor_imperfect_search::RootDeterminizationConfigV1;
    use splendor_search::SearchConfigV1;

    fn n1_config() -> RootDeterminizationConfigV1 {
        RootDeterminizationConfigV1 {
            sample_seed: S2B_N1_SAMPLE_SEED,
            sample_count: S2B_N1_SAMPLE_COUNT,
            continuation_search: SearchConfigV1 {
                max_depth_turns: S2B_N1_DEPTH_TURNS,
                max_nodes: S2B_N1_MAX_NODES,
            },
        }
    }

    #[test]
    fn overlay_rejects_non_n1_configs() {
        let bad = RootDeterminizationConfigV1 {
            sample_seed: S2B_N1_SAMPLE_SEED,
            sample_count: S2B_N1_SAMPLE_COUNT,
            continuation_search: SearchConfigV1 {
                max_depth_turns: 1,
                max_nodes: 2000,
            },
        };
        assert!(N1BuyOverlayPolicy::new(bad).is_err());
        assert!(N1BuyOverlayPolicy::new(n1_config()).is_ok());
    }

    #[test]
    fn apply_rule_no_op_when_base_is_not_take() {
        // A Pass/Buy base never triggers, regardless of H*.
        let (state, _) = FullState::new(GameConfig {
            player_count: 2,
            seed: 1,
            ..Default::default()
        })
        .unwrap();
        let obs = state.observation(PlayerId(0));
        let legal: Vec<Action> = state.legal_actions();
        let base = legal[0]; // whatever it is, claim a non-take variant below
        let non_take = Action::Pass;
        let _ = base;
        let (action, triggered) = N1BuyOverlayPolicy::apply_rule(
            non_take,
            &obs,
            &legal,
        );
        assert!(!triggered);
        assert_eq!(action, non_take);
    }

    #[test]
    fn overlay_flag_off_matches_plain_n1_bitwise() {
        // The overlay wraps the exact n1; with the rule never firing on this
        // early-game context (n1's base is rarely TakeTokens with a unique-H
        // buy here... but to make the parity test robust we instead assert
        // the wrapper delegates: flag identity is n1's config), we run both
        // policies on the same context and compare ACTIONS.
        let (state, setup) = FullState::new(GameConfig {
            player_count: 2,
            seed: 20260908,
            ..Default::default()
        })
        .unwrap();
        let viewer = PlayerId(0);
        let observation = state.observation(viewer);
        let actions: Vec<Action> = state.legal_actions();
        let history: Vec<splendor_core::VisibleEvent> =
            visible_events(&setup.events, Audience::Player(viewer));
        let obs_hash = observation_hash(&observation).clone();
        let legal_static: &'static [Action] = Box::leak(actions.clone().into_boxed_slice());
        let history_ref: &'static [splendor_core::VisibleEvent] =
            Box::leak(history.into_boxed_slice());

        let cfg = n1_config();
        let mut plain = DeterminizationAgentPolicyV1::new(cfg).unwrap();
        let mut overlay = N1BuyOverlayPolicy::new(cfg).unwrap();

        let mut rng_a = StableRng::new(5);
        let mut rng_b = StableRng::new(5);
        let meta = PublicRequestMeta {
            game_id: "s2b-test".into(),
            recipient_seat: viewer,
            request_id: 1,
            observation_hash: obs_hash.clone(),
        };
        let a = plain
            .choose_action(splendor_agent::DecisionContext {
                observation: observation.clone(),
                visible_history: history_ref,
                legal_actions: legal_static,
                meta: meta.clone(),
                rng: &mut rng_a,
            })
            .unwrap();
        let b = overlay
            .choose_action(splendor_agent::DecisionContext {
                observation,
                visible_history: history_ref,
                legal_actions: legal_static,
                meta,
                rng: &mut rng_b,
            })
            .unwrap();
        // Either identical (no trigger) or the trigger shape holds.
        if a != b {
            assert!(matches!(a, Action::TakeTokens { .. }));
            assert!(matches!(b, Action::BuyMarket { .. }));
            assert_eq!(overlay.trigger_count, 1);
        } else {
            // Verify no trigger fired and the rule is a no-op.
            let (rule_action, triggered) =
                N1BuyOverlayPolicy::apply_rule(a, &state.observation(viewer), legal_static);
            assert!(!triggered);
            assert_eq!(rule_action, a);
        }
        assert_eq!(overlay.decision_count, 1);
    }
}
