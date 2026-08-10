//! Live Arena policy for the frozen M07 root-determinization baseline.
//!
//! The policy consumes only the public [`splendor_agent::DecisionContext`]:
//! the acting player's observation, cumulative player-projected visible event
//! history, server-certified legal actions, and public request metadata. It
//! never receives a replay, raw game seed, referee event, or `FullState`.

use splendor_agent::{run_agent, AgentError, AgentIdentity, AgentPolicy, DecisionContext};
use splendor_core::{Action, Ruleset};
use splendor_imperfect_search::{
    analyze_player_view_v1, ImperfectSearchError, RootDeterminizationConfigV1,
};
use splendor_search::canonical_order;
use thiserror::Error;

/// Stable Arena identity for the first live M07-backed policy.
pub const DETERMINIZATION_AGENT_NAME: &str = "effective-splendor-determinization-agent-v1";
/// Policy release version, independent of the engine crate version.
pub const DETERMINIZATION_AGENT_VERSION: &str = "1";

/// A player-view-only live policy backed by M07 root determinization.
#[derive(Debug, Clone)]
pub struct DeterminizationAgentPolicyV1 {
    ruleset: Ruleset,
    config: RootDeterminizationConfigV1,
}

impl DeterminizationAgentPolicyV1 {
    /// Create a base-rules policy after validating all deterministic budgets.
    pub fn new(config: RootDeterminizationConfigV1) -> Result<Self, DeterminizationAgentError> {
        config.validate()?;
        Ok(Self {
            ruleset: Ruleset::base_v1(),
            config,
        })
    }

    pub fn config(&self) -> RootDeterminizationConfigV1 {
        self.config
    }
}

/// Fail-closed live-policy errors.
#[derive(Debug, Error)]
pub enum DeterminizationAgentError {
    #[error(transparent)]
    Search(#[from] ImperfectSearchError),
    #[error("request recipient does not match observation viewer")]
    RecipientViewerMismatch,
    #[error("server-certified legal actions do not match the player-view search root")]
    LegalActionSetMismatch,
}

impl AgentPolicy for DeterminizationAgentPolicyV1 {
    type Error = DeterminizationAgentError;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, Self::Error> {
        if context.meta.recipient_seat != context.observation.viewer {
            return Err(DeterminizationAgentError::RecipientViewerMismatch);
        }

        let analysis = analyze_player_view_v1(
            self.ruleset,
            &context.observation,
            context.visible_history,
            self.config,
        )?;
        let result = analysis.result();
        let search_actions = result
            .action_aggregates
            .iter()
            .map(|aggregate| aggregate.action)
            .collect::<Vec<_>>();
        if canonical_order(context.legal_actions) != search_actions {
            return Err(DeterminizationAgentError::LegalActionSetMismatch);
        }

        Ok(result.action)
    }
}

/// Run the v1 policy over the standard NDJSON Agent SDK runtime.
pub fn run_determinization_agent_v1<R, W, E>(
    input: R,
    output: W,
    mut diagnostics: E,
    config: RootDeterminizationConfigV1,
) -> Result<(), AgentError>
where
    R: std::io::BufRead,
    W: std::io::Write,
    E: std::io::Write,
{
    let policy = match DeterminizationAgentPolicyV1::new(config) {
        Ok(policy) => policy,
        Err(error) => {
            let agent_error = AgentError::Policy(error.to_string());
            let _ = writeln!(diagnostics, "error: {agent_error}");
            let _ = diagnostics.flush();
            return Err(agent_error);
        }
    };
    run_agent(
        input,
        output,
        diagnostics,
        AgentIdentity {
            name: DETERMINIZATION_AGENT_NAME,
            version: DETERMINIZATION_AGENT_VERSION,
        },
        0,
        policy,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use splendor_agent::{PublicRequestMeta, StableRng};
    use splendor_core::{
        observation_hash, visible_events, Audience, FullState, GameConfig, PlayerId,
    };
    use splendor_search::SearchConfigV1;

    fn config() -> RootDeterminizationConfigV1 {
        RootDeterminizationConfigV1 {
            sample_seed: 17,
            sample_count: 1,
            continuation_search: SearchConfigV1 {
                max_depth_turns: 1,
                max_nodes: 100,
            },
        }
    }

    #[test]
    fn live_policy_matches_replay_neutral_player_view_analysis() {
        let (state, setup) = FullState::new(GameConfig {
            player_count: 2,
            seed: 42,
            ..Default::default()
        })
        .unwrap();
        let viewer = PlayerId(0);
        let observation = state.observation(viewer);
        let history = visible_events(&setup.events, Audience::Player(viewer));
        let legal = state.legal_actions();
        let expected = analyze_player_view_v1(Ruleset::base_v1(), &observation, &history, config())
            .unwrap()
            .result()
            .action;
        let mut rng = StableRng::new(999);
        let context = DecisionContext {
            observation: observation.clone(),
            visible_history: &history,
            legal_actions: &legal,
            meta: PublicRequestMeta {
                game_id: "live-policy-test".to_string(),
                recipient_seat: viewer,
                request_id: 1,
                observation_hash: observation_hash(&observation),
            },
            rng: &mut rng,
        };

        let actual = DeterminizationAgentPolicyV1::new(config())
            .unwrap()
            .choose_action(context)
            .unwrap();
        assert_eq!(actual, expected);
    }

    #[test]
    fn mismatched_server_legal_actions_fail_closed() {
        let (state, setup) = FullState::new(GameConfig::default()).unwrap();
        let viewer = PlayerId(0);
        let observation = state.observation(viewer);
        let history = visible_events(&setup.events, Audience::Player(viewer));
        let legal = [Action::Pass];
        let mut rng = StableRng::new(0);
        let context = DecisionContext {
            observation: observation.clone(),
            visible_history: &history,
            legal_actions: &legal,
            meta: PublicRequestMeta {
                game_id: "bad-legal-set".to_string(),
                recipient_seat: viewer,
                request_id: 1,
                observation_hash: observation_hash(&observation),
            },
            rng: &mut rng,
        };

        let error = DeterminizationAgentPolicyV1::new(config())
            .unwrap()
            .choose_action(context)
            .unwrap_err();
        assert!(matches!(
            error,
            DeterminizationAgentError::LegalActionSetMismatch
        ));
    }
}
