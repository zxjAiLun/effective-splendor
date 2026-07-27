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

/// Fixed byte length of the suffix `expand_schedule` appends to each plan's
/// `evaluation_id` to derive a per-match `game_id`:
/// `-s{seed_index:06}-r{rotation:02}` → `-s000000-r00` = exactly 12 bytes.
///
/// This is kept as a named constant (rather than recomputed) so the
/// `evaluation_id` length ceiling can be derived from the arena's
/// [`MAX_GAME_ID_BYTES`](splendor_arena::config::MAX_GAME_ID_BYTES) without
/// hiding the arithmetic.
pub const MATCH_GAME_ID_SUFFIX_BYTES: usize = 12;

/// Maximum UTF-8 byte length of an `evaluation_id`. Held to
/// `arena::MAX_GAME_ID_BYTES - MATCH_GAME_ID_SUFFIX_BYTES` so every derived
/// match `game_id` (`{evaluation_id}-s......-r..`) is guaranteed to fit the
/// arena's 128-byte `game_id` ceiling. A plan that hashes must also be
/// schedulable: an id at this limit still expands cleanly.
pub const MAX_EVALUATION_ID_BYTES: usize =
    splendor_arena::config::MAX_GAME_ID_BYTES - MATCH_GAME_ID_SUFFIX_BYTES;

/// Maximum UTF-8 byte length of an agent id. Agent ids are never embedded in a
/// derived `game_id`, so they may use the full arena `game_id` byte budget.
pub const MAX_AGENT_ID_BYTES: usize = splendor_arena::config::MAX_GAME_ID_BYTES;

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

        check_id(
            "evaluation_id",
            &self.evaluation_id,
            MAX_EVALUATION_ID_BYTES,
        )?;

        let n = self.agents.len();
        if !(2..=4).contains(&n) {
            return Err(EvaluationError::InvalidPlan(format!(
                "agent count must be 2..=4 (got {n})"
            )));
        }

        let mut seen = std::collections::HashSet::new();
        for agent in &self.agents {
            check_id("agent id", &agent.id, MAX_AGENT_ID_BYTES)?;
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

/// Reject empty/over-long/control-character ids. Each kind carries its own byte
/// ceiling: `evaluation_id` is bounded by [`MAX_EVALUATION_ID_BYTES`] (so the
/// derived `game_id` always fits the arena limit), agent ids by
/// [`MAX_AGENT_ID_BYTES`]. Control characters (C0) are forbidden so ids cannot
/// corrupt framing.
fn check_id(kind: &str, value: &str, max_bytes: usize) -> Result<(), EvaluationError> {
    if value.trim().is_empty() {
        return Err(EvaluationError::InvalidPlan(format!(
            "{kind} must not be empty"
        )));
    }
    let bytes = value.as_bytes();
    if bytes.len() > max_bytes {
        return Err(EvaluationError::InvalidPlan(format!(
            "{kind} exceeds the {max_bytes} byte limit"
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

    // ----- Blocker 3: evaluation_id / agent_id byte ceilings -----

    #[test]
    fn evaluation_id_116_bytes_validates_hashes_and_expands() {
        // 116 bytes is the maximum schedulable evaluation_id: the derived
        // game_id (116 + 12-byte suffix) lands exactly on the arena's
        // 128-byte ceiling. Validate, hash, AND expand must all succeed — a
        // plan that hashes must be schedulable.
        let mut plan = crate::make_plan(&["A", "B"], &[1]);
        plan.evaluation_id = "e".repeat(116);
        assert_eq!(plan.evaluation_id.len(), 116);
        assert_eq!(116, MAX_EVALUATION_ID_BYTES);
        assert_eq!(128, MAX_AGENT_ID_BYTES);
        assert_eq!(12, MATCH_GAME_ID_SUFFIX_BYTES);

        plan.validate()
            .expect("116-byte evaluation_id must validate");
        let _hash = evaluation_plan_hash_v1(&plan).expect("116-byte id must hash");
        let specs = expand_schedule(&plan).expect("116-byte id must expand");

        // Every derived game_id fits the arena ceiling; the seed-0 / rot-0
        // game_id sits exactly at 128 bytes (116 + "-s000000-r00").
        for spec in &specs {
            assert!(spec.arena_config.game_id.len() <= 128);
        }
        assert_eq!(specs[0].arena_config.game_id.len(), 128);
    }

    #[test]
    fn evaluation_id_117_bytes_is_rejected_by_plan_validation() {
        // 117 bytes would derive a 129-byte game_id (117 + 12), exceeding the
        // arena ceiling. Plan validation must reject it — so it can never be
        // hashed, and the system never produces a plan hash for an
        // unschedulable plan.
        let mut plan = crate::make_plan(&["A", "B"], &[1]);
        plan.evaluation_id = "e".repeat(117);
        assert!(matches!(
            plan.validate(),
            Err(EvaluationError::InvalidPlan(_))
        ));
        // Hashing runs validate first, so it must also refuse.
        assert!(evaluation_plan_hash_v1(&plan).is_err());
        // And expand must refuse too.
        assert!(expand_schedule(&plan).is_err());
    }

    #[test]
    fn agent_id_128_bytes_remains_valid() {
        // Agent ids are never embedded in a derived game_id, so they may use
        // the full 128-byte arena budget.
        let mut plan = crate::make_plan(&["A", "B"], &[1]);
        plan.agents[0].id = "x".repeat(128);
        plan.validate().expect("128-byte agent id must validate");
        let _ = evaluation_plan_hash_v1(&plan).expect("128-byte agent id must hash");
        let specs = expand_schedule(&plan).expect("128-byte agent id must expand");
        // The 128-byte agent sits at seat 0 in rotation 0.
        assert_eq!(specs[0].agent_ids_by_seat[0], "x".repeat(128));
    }
}
