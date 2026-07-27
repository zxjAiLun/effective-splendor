//! Protocol runtime and policy boundary for Splendor stdio agents.
//!
//! This crate is the shared, strictly-scoped client side of the NDJSON arena
//! protocol. It reuses the exact server FSM the reference `agent-random` spoke
//! (Hello / GameStart / Observation / RequestAction / Ping / Pong) and adds the
//! [`AgentPolicy`] boundary: a policy may only choose an action from the
//! `legal_actions` the server hands it, using the `Observation`, public request
//! metadata, and its own RNG. It can never observe `FullState`, the
//! `FullStateHash`, the raw game seed, a `ReplayV1`, an opponent's blind-reserved
//! `CardId`, or the deck order.
//!
//! [`run_agent`] drives the FSM over any `BufRead` / `Write` pair, so the same
//! code serves both the real stdio binary and hand-built transcript tests. The
//! reference random agent is [`run_random_agent`], which preserves the frozen
//! xorshift64\* output of the historical `splendor agent-random --seed <u64>`.

mod error;
mod heuristic;
mod policy;
mod runtime;
mod stable_rng;

pub use error::AgentError;
pub use heuristic::{HeuristicAgentPolicy, HEURISTIC_AGENT_NAME, HEURISTIC_AGENT_VERSION};
pub use policy::{AgentPolicy, DecisionContext, PublicRequestMeta, RandomAgentPolicy};
pub use runtime::{run_agent, AgentIdentity};
pub use stable_rng::StableRng;

/// The agent name the reference random agent declares in its `hello`. Kept
/// stable so existing arena fixtures and E2E tests that assert this name keep
/// passing.
pub const RANDOM_AGENT_NAME: &str = "splendor-cli-random";

/// Convenience entry for the reference random agent: a [`RandomAgentPolicy`]
/// over a seed-initialized [`StableRng`]. This is the exact behavior the
/// `splendor agent-random --seed <u64>` subcommand has always had, so existing
/// reference transcripts are byte-for-byte unchanged.
///
/// The reference identity (`RANDOM_AGENT_NAME` / `ENGINE_VERSION`) is passed
/// explicitly to [`run_agent`], so the CLI and every other caller are insulated
/// from the runtime's identity input — the random agent keeps presenting exactly
/// `splendor-cli-random / 0.4.0`.
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

/// Convenience entry for the deterministic heuristic agent: a
/// [`HeuristicAgentPolicy`] over a seed-initialized [`StableRng`], presenting
/// the heuristic identity (`HEURISTIC_AGENT_NAME` / `HEURISTIC_AGENT_VERSION`).
///
/// The heuristic policy is fully deterministic and uses its `seed` only to
/// break ties among equally-scored legal actions; a unique best action is
/// chosen without consuming the RNG, so the same server transcript always
/// yields the same action regardless of seed.
pub fn run_heuristic_agent<R, W, E>(
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
            name: HEURISTIC_AGENT_NAME,
            version: HEURISTIC_AGENT_VERSION,
        },
        seed,
        HeuristicAgentPolicy::new(),
    )
}
