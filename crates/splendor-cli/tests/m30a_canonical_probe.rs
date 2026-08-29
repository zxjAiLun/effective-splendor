//! Unit tests for M30A Canonical Teacher Target calculations:
//! 1. even_allocation handles integer division and remainders.
//! 2. proportional_allocation handles utility advantages, ties, and remainders.
//! 3. first_max_action strictly selects the first index on utility ties (matching torch.argmax).
//! 4. canonical_policy_targets strictly sums to 1_000_000 micros.

use splendor_core::{Action, Gems, Tier};
use splendor_imperfect_search::RootActionAggregateV1;

// Import allocation functions from probe binary module. The probe is a binary:
// only the four allocation helpers are used here, so everything else in it
// (including `main`) is dead in this context and must not be linted as such.
#[allow(dead_code)]
#[path = "../src/bin/m30a_probe.rs"]
mod m30a_probe;
use m30a_probe::{
    canonical_policy_targets, even_allocation, first_max_action, proportional_allocation,
};

#[test]
fn test_even_allocation_with_remainders() {
    // 100_000 micros across 3 actions: 33334, 33333, 33333 (first remainder receives +1)
    let alloc = even_allocation(100_000, 3);
    assert_eq!(alloc.len(), 3);
    assert_eq!(alloc, vec![33334, 33333, 33333]);
    assert_eq!(alloc.iter().sum::<u32>(), 100_000);

    // 100_000 across 6 actions
    let alloc6 = even_allocation(100_000, 6);
    assert_eq!(alloc6.iter().sum::<u32>(), 100_000);
    assert_eq!(alloc6, vec![16667, 16667, 16667, 16667, 16666, 16666]);
}

#[test]
fn test_proportional_allocation_with_ties_and_remainders() {
    let total = 900_000u32;
    // Two equal weights: must divide equally
    let weights = vec![50u128, 50u128];
    let alloc = proportional_allocation(total, &weights, 100).unwrap();
    assert_eq!(alloc, vec![450_000, 450_000]);
    assert_eq!(alloc.iter().sum::<u32>(), total);

    // Three weights with remainder: 1, 1, 1 (total 10)
    let w3 = vec![1u128, 1u128, 1u128];
    let alloc3 = proportional_allocation(10, &w3, 3).unwrap();
    // 10 / 3 = 3 with remainder 1. First index receives +1: [4, 3, 3]
    assert_eq!(alloc3, vec![4, 3, 3]);
    assert_eq!(alloc3.iter().sum::<u32>(), 10);
}

#[test]
fn test_first_max_selection_on_ties() {
    let dummy_actions = [
        Action::ReserveMarket {
            tier: Tier::One,
            slot: 0,
            give_back: Gems::ZERO,
        },
        Action::ReserveMarket {
            tier: Tier::One,
            slot: 1,
            give_back: Gems::ZERO,
        },
        Action::ReserveMarket {
            tier: Tier::One,
            slot: 2,
            give_back: Gems::ZERO,
        },
    ];

    // Tied policy targets at index 0 and index 2: index 0 must be selected
    let policy_micros = vec![400_000, 200_000, 400_000];
    let chosen = first_max_action(&dummy_actions, &policy_micros);
    assert_eq!(chosen, dummy_actions[0]);
}

#[test]
fn test_canonical_policy_targets_exact_sum_and_floor() {
    let dummy_actions = [
        Action::ReserveMarket {
            tier: Tier::One,
            slot: 0,
            give_back: Gems::ZERO,
        },
        Action::ReserveMarket {
            tier: Tier::One,
            slot: 1,
            give_back: Gems::ZERO,
        },
    ];

    let aggregates = vec![
        RootActionAggregateV1 {
            action: dummy_actions[0],
            utility_sum_by_player: vec![100, -100],
        },
        RootActionAggregateV1 {
            action: dummy_actions[1],
            utility_sum_by_player: vec![300, -300],
        },
    ];

    let policy = canonical_policy_targets(&aggregates, 0, 100_000).unwrap();
    assert_eq!(policy.len(), 2);
    assert_eq!(policy.iter().sum::<u32>(), 1_000_000);
    // Action 1 has advantage 200 vs advantage 0: receives 100% of the 900_000 remaining + 50_000 floor
    assert_eq!(policy[0], 50_000);
    assert_eq!(policy[1], 950_000);
}
