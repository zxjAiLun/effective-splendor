//! Deterministic evaluation model, version 1.
//!
//! This crate is the *pure* model for evaluating agents against one another:
//! plan validation and hashing ([`plan`]), a frozen seat-balanced schedule
//! expansion ([`schedule`]), and report aggregation ([`report`]). It performs
//! no process spawning, writes no files, and defines no CLI — those belong to a
//! future driver crate that consumes this model.
//!
//! Dependency direction is one-way into this crate: `splendor-eval` depends on
//! `splendor-arena`, `splendor-core`, and the usual serde/sha2 tooling. The
//! arena, core, agent, and CLI crates must never depend on `splendor-eval`.

pub mod error;
pub mod plan;
pub mod report;
pub mod schedule;

pub use error::EvaluationError;
pub use plan::{
    evaluation_plan_hash_v1, EvaluationAgentV1, EvaluationPlanHash, EvaluationPlanV1,
    EVALUATION_PLAN_FORMAT, EVALUATION_VERSION, MAX_MATCHES,
};
pub use report::{
    aggregate, AgentAggregateV1, EvaluationMatchRecordV1, EvaluationReportV1, SeatAggregateV1,
    EVALUATION_REPORT_FORMAT,
};
pub use schedule::{expand_schedule, EvaluationMatchSpecV1};

#[cfg(test)]
pub(crate) use test_helpers::make_plan;

#[cfg(test)]
pub(crate) mod test_helpers {
    //! Shared builders for the crate's unit tests.

    use std::path::PathBuf;

    use splendor_arena::AgentCommand;

    use crate::plan::{
        EvaluationAgentV1, EvaluationPlanV1, EVALUATION_PLAN_FORMAT, EVALUATION_VERSION,
    };

    /// Build a minimal valid plan: agents with ids `agent_ids` and game seeds
    /// `seeds`, all timeouts 1000ms, program `/bin/{id}`.
    pub(crate) fn make_plan(agent_ids: &[&str], seeds: &[u64]) -> EvaluationPlanV1 {
        EvaluationPlanV1 {
            format: EVALUATION_PLAN_FORMAT.to_string(),
            version: EVALUATION_VERSION,
            evaluation_id: "eval-unit".to_string(),
            agents: agent_ids
                .iter()
                .map(|id| EvaluationAgentV1 {
                    id: id.to_string(),
                    command: AgentCommand {
                        program: PathBuf::from(format!("/bin/{id}")),
                        args: vec![],
                    },
                })
                .collect(),
            game_seeds: seeds.to_vec(),
            handshake_timeout_ms: 1000,
            move_timeout_ms: 1000,
            shutdown_grace_ms: 1000,
        }
    }
}
