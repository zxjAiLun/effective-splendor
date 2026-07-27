//! The agent policy boundary.
//!
//! A [`AgentPolicy`] chooses a single action for one request given only a
//! [`DecisionContext`]. The context is the hard information boundary of the
//! agent SDK: it exposes the agent's own `Observation`, the server-certified
//! `legal_actions`, public request metadata, and the agent's own RNG — and
//! *nothing* referee-only (no `FullState`, `FullStateHash`, raw game seed,
//! `ReplayV1`, opponent blind-reserved `CardId`, or deck order).

use splendor_core::{Action, Observation, ObservationHash, PlayerId};

use crate::StableRng;

/// Public, agent-facing request metadata.
///
/// Deliberately omits every referee-only field: no `FullState`, `FullStateHash`,
/// raw game seed, replay, opponent blind-reserved `CardId`, or deck order can
/// ever appear here. It carries only what a correctly-scoped agent needs to
/// correlate its request.
#[derive(Debug, Clone)]
pub struct PublicRequestMeta {
    pub game_id: String,
    pub recipient_seat: PlayerId,
    pub request_id: u64,
    pub observation_hash: ObservationHash,
}

/// Everything a policy is allowed to see when choosing an action.
///
/// This is the hard information boundary of the agent SDK. A policy receives its
/// own `Observation`, the server-certified `legal_actions`, public request
/// metadata, and its own RNG. It receives **nothing** referee-only: not
/// `FullState`, `FullStateHash`, the raw game seed, a `ReplayV1`, an opponent's
/// blind-reserved `CardId`, or the deck order.
pub struct DecisionContext<'a> {
    pub observation: Observation,
    pub legal_actions: &'a [Action],
    pub meta: PublicRequestMeta,
    pub rng: &'a mut StableRng,
}

/// The decision-making boundary for a Splendor agent.
///
/// Implementors choose an action for a single request given only the
/// [`DecisionContext`] — which never exposes referee-only state. The runtime
/// owns transport, protocol validation, and output; the policy owns only the
/// decision.
///
/// The associated `Error` must be `Display` so the runtime can emit a stable
/// diagnostic if the policy cannot decide.
pub trait AgentPolicy {
    type Error;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, Self::Error>;
}

/// Reference policy: choose uniformly at random from the legal actions using
/// the agent's own frozen [`StableRng`].
///
/// Behaviorally identical to the historical `splendor agent-random`: a given
/// seed and transcript always select the same action, so existing reference
/// transcripts are unchanged. The policy itself is stateless; the RNG lives in
/// the runtime and is handed in via [`DecisionContext::rng`].
pub struct RandomAgentPolicy;

impl RandomAgentPolicy {
    pub fn new() -> Self {
        RandomAgentPolicy
    }
}

impl Default for RandomAgentPolicy {
    fn default() -> Self {
        Self::new()
    }
}

impl AgentPolicy for RandomAgentPolicy {
    type Error = std::convert::Infallible;

    fn choose_action(&mut self, context: DecisionContext<'_>) -> Result<Action, Self::Error> {
        let choice = context.legal_actions[context.rng.index(context.legal_actions.len())];
        Ok(choice)
    }
}
