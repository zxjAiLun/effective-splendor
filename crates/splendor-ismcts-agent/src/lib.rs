//! Live player-view policy for M10 ISMCTS v1.

use splendor_agent::{run_agent, AgentError, AgentIdentity, AgentPolicy, DecisionContext};
use splendor_core::{Action, Ruleset};
use splendor_ismcts::{analyze_player_view_ismcts_v1, IsmctsConfigV1, IsmctsError};
use splendor_search::canonical_order;
use thiserror::Error;

pub const ISMCTS_AGENT_NAME: &str = "effective-splendor-ismcts-agent-v1";
pub const ISMCTS_AGENT_VERSION: &str = "1";

#[derive(Debug, Clone)]
pub struct IsmctsAgentPolicyV1 {
    ruleset: Ruleset,
    config: IsmctsConfigV1,
}

impl IsmctsAgentPolicyV1 {
    pub fn new(config: IsmctsConfigV1) -> Result<Self, IsmctsAgentError> {
        config.validate()?;
        Ok(Self {
            ruleset: Ruleset::base_v1(),
            config,
        })
    }

    pub fn config(&self) -> IsmctsConfigV1 {
        self.config
    }
}

#[derive(Debug, Error)]
pub enum IsmctsAgentError {
    #[error(transparent)]
    Search(#[from] IsmctsError),
    #[error("request recipient does not match observation viewer")]
    RecipientViewerMismatch,
    #[error("server-certified legal actions do not match the ISMCTS root")]
    LegalActionSetMismatch,
}

impl AgentPolicy for IsmctsAgentPolicyV1 {
    type Error = IsmctsAgentError;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, Self::Error> {
        if context.meta.recipient_seat != context.observation.viewer {
            return Err(IsmctsAgentError::RecipientViewerMismatch);
        }
        let analysis = analyze_player_view_ismcts_v1(
            self.ruleset,
            &context.observation,
            context.visible_history,
            self.config,
        )?;
        let search_actions = analysis
            .result()
            .action_stats
            .iter()
            .map(|stats| stats.action)
            .collect::<Vec<_>>();
        if canonical_order(context.legal_actions) != search_actions {
            return Err(IsmctsAgentError::LegalActionSetMismatch);
        }
        Ok(analysis.result().action)
    }
}

pub fn run_ismcts_agent_v1<R, W, E>(
    input: R,
    output: W,
    diagnostics: E,
    config: IsmctsConfigV1,
) -> Result<(), AgentError>
where
    R: std::io::BufRead,
    W: std::io::Write,
    E: std::io::Write,
{
    let policy =
        IsmctsAgentPolicyV1::new(config).map_err(|error| AgentError::Policy(error.to_string()))?;
    run_agent(
        input,
        output,
        diagnostics,
        AgentIdentity {
            name: ISMCTS_AGENT_NAME,
            version: ISMCTS_AGENT_VERSION,
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

    fn config() -> IsmctsConfigV1 {
        IsmctsConfigV1 {
            sample_seed: 23,
            simulations: 16,
            max_depth_turns: 1,
            exploration_bias: 100_000_000,
        }
    }

    #[test]
    fn policy_returns_a_server_certified_legal_action() {
        let (state, setup) = FullState::new(GameConfig::default()).unwrap();
        let viewer = PlayerId(0);
        let observation = state.observation(viewer);
        let history = visible_events(&setup.events, Audience::Player(viewer));
        let legal = state.legal_actions();
        let mut rng = StableRng::new(0);
        let context = DecisionContext {
            observation: observation.clone(),
            visible_history: &history,
            legal_actions: &legal,
            meta: PublicRequestMeta {
                game_id: "ismcts-agent-test".into(),
                recipient_seat: viewer,
                request_id: 1,
                observation_hash: observation_hash(&observation),
            },
            rng: &mut rng,
        };
        let action = IsmctsAgentPolicyV1::new(config())
            .unwrap()
            .choose_action(context)
            .unwrap();
        assert!(legal.contains(&action));
    }

    #[test]
    fn policy_fails_closed_on_legal_set_mismatch() {
        let (state, setup) = FullState::new(GameConfig::default()).unwrap();
        let viewer = PlayerId(0);
        let observation = state.observation(viewer);
        let history = visible_events(&setup.events, Audience::Player(viewer));
        let mut rng = StableRng::new(0);
        let context = DecisionContext {
            observation: observation.clone(),
            visible_history: &history,
            legal_actions: &[Action::Pass],
            meta: PublicRequestMeta {
                game_id: "ismcts-agent-test".into(),
                recipient_seat: viewer,
                request_id: 1,
                observation_hash: observation_hash(&observation),
            },
            rng: &mut rng,
        };
        assert!(matches!(
            IsmctsAgentPolicyV1::new(config())
                .unwrap()
                .choose_action(context),
            Err(IsmctsAgentError::LegalActionSetMismatch)
        ));
    }
}
