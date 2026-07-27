//! Seat-balanced schedule expansion.
//!
//! Evaluation v1 uses a *cyclic* seat rotation rather than a factorial
//! permutation: for `N` agents and each game seed, it generates `N` matches,
//! one per rotation. Rotation `r` right-rotates the agent list by `r`, so seat
//! `s` is occupied by the agent originally at index `(s + N - r) % N`. Across
//! the `N` rotations each agent occupies each seat exactly once per seed —
//! every agent is therefore scheduled for every match, and seat bias is
//! cancelled without `N!` blow-up.
//!
//! The match order is frozen: outer loop over `seed_index` ascending, inner
//! loop over `rotation` `0..N`. Each match gets a deterministic `game_id` of
//! the form `{evaluation_id}-s{seed:06}-r{rotation:02}` — no UUID, clock, or
//! randomness.

use splendor_arena::ArenaConfig;

use crate::error::EvaluationError;
use crate::plan::{EvaluationPlanV1, MAX_MATCHES};

/// One scheduled match: its deterministic slot coordinates and the concrete
/// `ArenaConfig` to run it with.
#[derive(Debug, Clone)]
pub struct EvaluationMatchSpecV1 {
    /// Position in the frozen schedule (0-based, contiguous).
    pub match_index: u32,
    /// Index into the plan's `game_seeds` (outer loop).
    pub seed_index: u32,
    /// Rotation index `0..N` (inner loop).
    pub rotation: u8,
    /// Agent ids in seat order for this rotation.
    pub agent_ids_by_seat: Vec<String>,
    /// Concrete arena configuration (validated on construction).
    pub arena_config: ArenaConfig,
}

/// Expand a validated plan into its full frozen schedule.
///
/// Re-validates the plan (cheap; already validated for hashing) and enforces
/// the match ceiling, then builds one [`EvaluationMatchSpecV1`] per
/// (seed, rotation) slot with a validated [`ArenaConfig`].
pub fn expand_schedule(
    plan: &EvaluationPlanV1,
) -> Result<Vec<EvaluationMatchSpecV1>, EvaluationError> {
    plan.validate()?;
    let n = plan.agents.len();
    let planned = (n as u64).checked_mul(plan.game_seeds.len() as u64).ok_or(
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

    let mut specs = Vec::with_capacity(planned as usize);
    let mut match_index: u32 = 0;
    for (seed_index, &seed) in plan.game_seeds.iter().enumerate() {
        for rotation in 0..n {
            let game_id = format!("{}-s{:06}-r{:02}", plan.evaluation_id, seed_index, rotation);
            let mut agent_ids_by_seat = Vec::with_capacity(n);
            let mut agents = Vec::with_capacity(n);
            for seat in 0..n {
                // Right-rotate the agent list by `rotation`: seat `s` gets the
                // agent originally at index (s + n - rotation) % n.
                let idx = (seat + n - rotation) % n;
                agent_ids_by_seat.push(plan.agents[idx].id.clone());
                agents.push(plan.agents[idx].command.clone());
            }
            let arena_config = ArenaConfig {
                game_id: game_id.clone(),
                seed,
                handshake_timeout_ms: plan.handshake_timeout_ms,
                move_timeout_ms: plan.move_timeout_ms,
                shutdown_grace_ms: plan.shutdown_grace_ms,
                agents,
            };
            arena_config
                .validate()
                .map_err(|e| EvaluationError::ArenaConfig(e.to_string()))?;
            specs.push(EvaluationMatchSpecV1 {
                match_index,
                seed_index: seed_index as u32,
                rotation: rotation as u8,
                agent_ids_by_seat,
                arena_config,
            });
            match_index += 1;
        }
    }
    Ok(specs)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn two_agents_expand_to_two_seat_swapped_matches_per_seed() {
        let plan = crate::make_plan(&["A", "B"], &[7]);
        let specs = expand_schedule(&plan).unwrap();
        assert_eq!(specs.len(), 2);
        assert_eq!(specs[0].agent_ids_by_seat, vec!["A", "B"]);
        assert_eq!(specs[1].agent_ids_by_seat, vec!["B", "A"]);
        assert_eq!(specs[0].rotation, 0);
        assert_eq!(specs[1].rotation, 1);
    }

    #[test]
    fn three_agents_receive_each_seat_once_per_seed() {
        let plan = crate::make_plan(&["A", "B", "C"], &[1]);
        let specs = expand_schedule(&plan).unwrap();
        assert_eq!(specs.len(), 3);

        let mut seats_for: std::collections::HashMap<&str, std::collections::HashSet<u8>> =
            std::collections::HashMap::new();
        for spec in &specs {
            for (seat, id) in spec.agent_ids_by_seat.iter().enumerate() {
                seats_for.entry(id.as_str()).or_default().insert(seat as u8);
            }
        }
        for id in ["A", "B", "C"] {
            let seats = seats_for.get(id).unwrap();
            assert_eq!(seats.len(), 3, "agent {id} should occupy 3 distinct seats");
            assert!(seats.contains(&0));
            assert!(seats.contains(&1));
            assert!(seats.contains(&2));
        }
    }

    #[test]
    fn schedule_order_is_frozen() {
        let plan = crate::make_plan(&["A", "B", "C"], &[10, 20, 30]);
        let specs = expand_schedule(&plan).unwrap();
        assert_eq!(specs.len(), 9);

        for (i, spec) in specs.iter().enumerate() {
            assert_eq!(spec.match_index, i as u32);
        }
        // Outer seed_index ascending, inner rotation 0..n.
        let seq: Vec<(u32, u8)> = specs.iter().map(|s| (s.seed_index, s.rotation)).collect();
        assert_eq!(
            seq,
            vec![
                (0, 0),
                (0, 1),
                (0, 2),
                (1, 0),
                (1, 1),
                (1, 2),
                (2, 0),
                (2, 1),
                (2, 2),
            ]
        );
    }

    #[test]
    fn arena_configs_from_schedule_validate() {
        let plan = crate::make_plan(&["A", "B", "C", "D"], &[1, 2, 3]);
        let specs = expand_schedule(&plan).unwrap();
        for spec in &specs {
            spec.arena_config
                .validate()
                .expect("arena config must validate");
            assert!(spec.arena_config.game_id.starts_with(&plan.evaluation_id));
            assert!(spec
                .arena_config
                .game_id
                .contains(&format!("-s{:06}", spec.seed_index)));
        }
    }
}
