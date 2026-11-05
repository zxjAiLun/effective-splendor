//! Player-view NDJSON runtime and policy interface for external agents.
//!
//! A policy receives its own observation, projected history and the referee's
//! legal actions. The runtime manages handshake, request correlation and output.

mod error;
mod policy;
mod runtime;
mod stable_rng;

pub use error::AgentError;
pub use policy::{AgentPolicy, DecisionContext, PublicRequestMeta, RandomAgentPolicy};
pub use runtime::{run_agent, AgentIdentity};
pub use stable_rng::StableRng;

pub const RANDOM_AGENT_NAME: &str = "splendor-cli-random";

/// Run the reference random policy over an NDJSON connection.
pub fn run_random_agent<R, W, E>(
    input: R,
    output: W,
    diagnostics: E,
    seed: u64,
) -> Result<(), AgentError>
where
    R: std::io::BufRead,
    W: std::io::Write,
    E: std::io::Write,
{
    run_agent(
        input,
        output,
        diagnostics,
        AgentIdentity {
            name: RANDOM_AGENT_NAME,
            version: splendor_core::ENGINE_VERSION,
        },
        seed,
        RandomAgentPolicy::new(),
    )
}
