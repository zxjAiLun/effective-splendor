//! Evaluation plan model, validation, and hashing.
//!
//! An [`EvaluationPlanV1`] is the *pure* description of what an evaluation run
//! should play: which agents, which game seeds, and the timeouts. It is
//! deliberately free of any execution detail — no process spawning, no file
//! paths beyond each agent's literal `command`, no shell interpretation.
//!
//! Validation is strict (`deny_unknown_fields` plus the checks in
//! [`EvaluationPlanV1::validate`]) and runs *before* hashing so the plan hash
//! is only ever computed over a normalized, internally consistent plan.

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use splendor_arena::AgentCommand;

use crate::error::EvaluationError;

/// Top-level plan format tag written into every evaluation plan.
pub const EVALUATION_PLAN_FORMAT: &str = "effective-splendor-evaluation-plan";

/// Schema version of the evaluation plan (and report).
pub const EVALUATION_VERSION: u32 = 1;

/// Hard ceiling on the number of matches a single plan may schedule. Keeps a
/// single plan from exploding into unbounded work and bounds config accidents.
pub const MAX_MATCHES: u32 = 10_000;

/// Maximum UTF-8 byte length of an evaluation id or agent id. Held to the same
/// grade as the arena `game_id` limit so ids cannot corrupt framing.
pub const MAX_EVALUATION_ID_BYTES: usize = 128;

/// One agent participating in the evaluation.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EvaluationAgentV1 {
    /// Stable, human-readable agent identifier. Non-empty, unique, and free of
    /// control characters.
    pub id: String,
    /// Literal spawn command (program + argv tokens). Never shell-joined.
    pub command: AgentCommand,
}

/// The version-1 evaluation plan.
///
/// `PartialEq`/`Eq` are intentionally not derived: the embedded `AgentCommand`
/// (which wraps a `PathBuf`) does not implement `Eq`, and plan equality is not
/// needed — plans are compared by their [`EvaluationPlanHash`] instead.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EvaluationPlanV1 {
    /// Always [`EVALUATION_PLAN_FORMAT`].
    pub format: String,
    /// Always [`EVALUATION_VERSION`].
    pub version: u32,
    /// Stable evaluation identifier. Used to derive deterministic match ids.
    pub evaluation_id: String,
    /// Participating agents, in declaration order. Must contain 2–4 entries.
    pub agents: Vec<EvaluationAgentV1>,
    /// Game seeds to evaluate. Must be non-empty.
    pub game_seeds: Vec<u64>,
    /// Max time allowed for an agent to complete the handshake.
    pub handshake_timeout_ms: u64,
    /// Max time allowed for an agent to return an action per request.
    pub move_timeout_ms: u64,
    /// Grace period before a kill on shutdown.
    pub shutdown_grace_ms: u64,
}

/// A stable, lowercase-hex SHA-256 over the canonical plan JSON.
///
/// The hash binds the plan content (ids, agents, seeds, timeouts) independent
/// of wall-clock time or absolute artifact paths. Two byte-identical plans
/// always hash identically.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EvaluationPlanHash(String);

impl EvaluationPlanHash {
    /// The lowercase-hex hash string.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl std::fmt::Display for EvaluationPlanHash {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl EvaluationPlanV1 {
    /// Validate the frozen invariants. Returns [`EvaluationError`] on the first
    /// violation. Must pass before [`evaluation_plan_hash_v1`] or schedule
    /// expansion.
    pub fn validate(&self) -> Result<(), EvaluationError> {
        if self.format != EVALUATION_PLAN_FORMAT {
            return Err(EvaluationError::InvalidPlan(format!(
                "format must be '{}'",
                EVALUATION_PLAN_FORMAT
            )));
        }
        if self.version != EVALUATION_VERSION {
            return Err(EvaluationError::InvalidPlan(format!(
                "version must be {}",
                EVALUATION_VERSION
            )));
        }

        check_id("evaluation_id", &self.evaluation_id)?;

        let n = self.agents.len();
        if !(2..=4).contains(&n) {
            return Err(EvaluationError::InvalidPlan(format!(
                "agent count must be 2..=4 (got {n})"
            )));
        }

        let mut seen = std::collections::HashSet::new();
        for agent in &self.agents {
            check_id("agent id", &agent.id)?;
            if !seen.insert(agent.id.as_str()) {
                return Err(EvaluationError::InvalidPlan(format!(
                    "duplicate agent id '{}'",
                    agent.id
                )));
            }
            if agent.command.program.as_os_str().is_empty() {
                return Err(EvaluationError::InvalidPlan(
                    "agent command program must not be empty".to_string(),
                ));
            }
        }

        if self.game_seeds.is_empty() {
            return Err(EvaluationError::InvalidPlan(
                "game_seeds must not be empty".to_string(),
            ));
        }

        let planned = (n as u64).checked_mul(self.game_seeds.len() as u64).ok_or(
            EvaluationError::MatchLimitExceeded {
                limit: MAX_MATCHES,
                planned: u32::MAX,
            },
        )?;
        if planned > MAX_MATCHES as u64 {
            return Err(EvaluationError::MatchLimitExceeded {
                limit: MAX_MATCHES,
                planned: planned as u32,
            });
        }

        check_timeout("handshake_timeout_ms", self.handshake_timeout_ms)?;
        check_timeout("move_timeout_ms", self.move_timeout_ms)?;
        check_timeout("shutdown_grace_ms", self.shutdown_grace_ms)?;

        Ok(())
    }
}

/// Reject empty/over-long/control-character ids at the same grade as arena
/// `game_id`s.
fn check_id(kind: &str, value: &str) -> Result<(), EvaluationError> {
    if value.trim().is_empty() {
        return Err(EvaluationError::InvalidPlan(format!(
            "{kind} must not be empty"
        )));
    }
    let bytes = value.as_bytes();
    if bytes.len() > MAX_EVALUATION_ID_BYTES {
        return Err(EvaluationError::InvalidPlan(format!(
            "{kind} exceeds the {} byte limit",
            MAX_EVALUATION_ID_BYTES
        )));
    }
    if bytes.iter().any(|b| *b < 0x20) {
        return Err(EvaluationError::InvalidPlan(format!(
            "{kind} contains a forbidden control character"
        )));
    }
    Ok(())
}

/// Reuse the arena's timeout bounds so evaluation timeouts can never exceed the
/// arena's 24h safety ceiling.
fn check_timeout(field: &str, value: u64) -> Result<(), EvaluationError> {
    use splendor_arena::config::MAX_TIMEOUT_MS;
    if value == 0 {
        return Err(EvaluationError::InvalidPlan(format!(
            "{field} must be greater than zero"
        )));
    }
    if value > MAX_TIMEOUT_MS {
        return Err(EvaluationError::InvalidPlan(format!(
            "{field} exceeds the 24h ceiling ({MAX_TIMEOUT_MS} ms)"
        )));
    }
    Ok(())
}

/// Hash a validated plan.
///
/// Validation runs first; an invalid plan is rejected rather than hashed. The
/// hash is computed over the fixed-field-order compact JSON serialization, so
/// byte-identical plans hash identically and the result is independent of
/// absolute artifact paths or run time.
pub fn evaluation_plan_hash_v1(
    plan: &EvaluationPlanV1,
) -> Result<EvaluationPlanHash, EvaluationError> {
    plan.validate()?;
    let json =
        serde_json::to_string(plan).map_err(|e| EvaluationError::Serialization(e.to_string()))?;
    let mut hasher = Sha256::new();
    hasher.update(json.as_bytes());
    Ok(EvaluationPlanHash(hex::encode(hasher.finalize())))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::schedule::expand_schedule;
    use std::path::PathBuf;

    #[test]
    fn duplicate_agent_id_is_rejected() {
        let plan = crate::make_plan(&["A", "A"], &[1, 2]);
        assert!(matches!(
            plan.validate(),
            Err(EvaluationError::InvalidPlan(_))
        ));
    }

    #[test]
    fn empty_seed_list_is_rejected() {
        let plan = crate::make_plan(&["A", "B"], &[]);
        assert!(plan.validate().is_err());
    }

    #[test]
    fn match_limit_is_enforced() {
        let seeds: Vec<u64> = (0..6000).collect(); // 2 * 6000 = 12000 > 10000
        let plan = crate::make_plan(&["A", "B"], &seeds);
        assert!(matches!(
            plan.validate(),
            Err(EvaluationError::MatchLimitExceeded { .. })
        ));
        assert!(matches!(
            expand_schedule(&plan),
            Err(EvaluationError::MatchLimitExceeded { .. })
        ));
    }

    #[test]
    fn different_seed_or_command_changes_plan_hash() {
        let base = crate::make_plan(&["A", "B"], &[1, 2, 3]);
        let h0 = evaluation_plan_hash_v1(&base).unwrap();

        let mut changed_seed = base.clone();
        changed_seed.game_seeds[0] = 999;
        let h1 = evaluation_plan_hash_v1(&changed_seed).unwrap();
        assert_ne!(h0, h1);

        let mut changed_cmd = base.clone();
        changed_cmd.agents[0].command.program = PathBuf::from("/bin/other");
        let h2 = evaluation_plan_hash_v1(&changed_cmd).unwrap();
        assert_ne!(h0, h2);
    }

    #[test]
    fn same_plan_produces_same_specs_and_hash() {
        let plan = crate::make_plan(&["A", "B", "C"], &[1, 2]);
        let h1 = evaluation_plan_hash_v1(&plan).unwrap();
        let h2 = evaluation_plan_hash_v1(&plan).unwrap();
        assert_eq!(h1, h2);

        let s1 = expand_schedule(&plan).unwrap();
        let s2 = expand_schedule(&plan).unwrap();
        assert_eq!(s1.len(), s2.len());
        for (a, b) in s1.iter().zip(s2.iter()) {
            assert_eq!(a.match_index, b.match_index);
            assert_eq!(a.arena_config.game_id, b.arena_config.game_id);
            assert_eq!(a.agent_ids_by_seat, b.agent_ids_by_seat);
        }
        // The hash is a 64-char lowercase hex string.
        assert_eq!(h1.as_str().len(), 64);
        assert!(h1.as_str().chars().all(|c| c.is_ascii_hexdigit()));
    }
}
