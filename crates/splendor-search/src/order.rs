//! Frozen canonical action order.
//!
//! Every search node must sort the full legal action set into this order
//! before traversal. The order decides the tiny-budget fallback, root and
//! internal tie-breaks, the principal variation and deterministic node
//! visitation. No legal action is ever pruned by ordering.
//!
//! Category order (earlier = smaller key):
//! 1. `ChooseNoble`   — noble id ascending
//! 2. `BuyMarket`     — tier ascending, slot ascending
//! 3. `BuyReserved`   — slot ascending
//! 4. `TakeTokens`    — take tuple ascending, give_back tuple ascending
//! 5. `ReserveMarket` — tier ascending, slot ascending, give_back ascending
//! 6. `ReserveDeck`   — tier ascending, give_back ascending
//! 7. `Pass`          — singleton
//!
//! The gems tuple order is frozen as
//! `(white, blue, green, red, black, gold)`.

use splendor_core::{Action, Gems};

/// Frozen gems tuple projection: `[white, blue, green, red, black, gold]`.
pub fn gems_tuple(gems: Gems) -> [u8; 6] {
    [
        gems.white, gems.blue, gems.green, gems.red, gems.black, gems.gold,
    ]
}

/// Total-order key over actions. Injective for actions with equal category:
/// two actions with the same key are the same action.
type CanonicalKey = (u8, u8, u8, [u8; 6], [u8; 6]);

const ZERO_TUPLE: [u8; 6] = [0; 6];

fn canonical_key(action: &Action) -> CanonicalKey {
    match *action {
        Action::ChooseNoble { noble } => (0, noble.0, 0, ZERO_TUPLE, ZERO_TUPLE),
        Action::BuyMarket { tier, slot } => (1, tier.index() as u8, slot, ZERO_TUPLE, ZERO_TUPLE),
        Action::BuyReserved { slot } => (2, slot, 0, ZERO_TUPLE, ZERO_TUPLE),
        Action::TakeTokens { take, give_back } => {
            (3, 0, 0, gems_tuple(take), gems_tuple(give_back))
        }
        Action::ReserveMarket {
            tier,
            slot,
            give_back,
        } => (
            4,
            tier.index() as u8,
            slot,
            gems_tuple(give_back),
            ZERO_TUPLE,
        ),
        Action::ReserveDeck { tier, give_back } => {
            (5, tier.index() as u8, 0, gems_tuple(give_back), ZERO_TUPLE)
        }
        Action::Pass => (6, 0, 0, ZERO_TUPLE, ZERO_TUPLE),
    }
}

/// Sort actions in place into the frozen canonical order.
pub fn canonical_sort(actions: &mut [Action]) {
    actions.sort_by_key(canonical_key);
}

/// Return a canonically ordered copy of `actions`.
pub fn canonical_order(actions: &[Action]) -> Vec<Action> {
    let mut sorted = actions.to_vec();
    canonical_sort(&mut sorted);
    sorted
}

/// The canonically first action of a set, regardless of input order.
///
/// This is the frozen tie-break selector: among equally good candidates the
/// search always picks the action this function would pick, and the
/// tiny-budget fallback returns exactly this action for the root legal set.
pub fn first_canonical_action(actions: &[Action]) -> Option<Action> {
    actions.iter().copied().min_by_key(canonical_key)
}
