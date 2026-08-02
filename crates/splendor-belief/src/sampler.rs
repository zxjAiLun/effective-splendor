//! C2: deterministic hidden-state sampler (M07).
//!
//! [`sample_determinization_v1`] completes a validated [`InformationSetV1`]
//! into a referee `FullState` that is consistent with the information set's
//! observation, using only:
//!
//! - the information set itself (`observation`, `information_set_hash`,
//!   canonical per-tier unseen pools, reserved knowledge);
//! - the caller-supplied `sample_seed` / `sample_index` key.
//!
//! The production entry point never receives the original setup seed, a
//! `ReplayV1`, a `RefereeEvent`, a raw `FullState`, a real deck order, or an
//! opponent's blind-reserved `CardId`.
//!
//! # Frozen position ordering
//!
//! For every tier independently the sampler starts from the C1 canonical
//! ascending unseen pool (see [`InformationSetV1::unseen_cards`]) and applies
//! one without-replacement Fisher-Yates:
//!
//! ```text
//! for i from len-1 down to 1:
//!     j = draw_below(i + 1)
//!     swap(i, j)
//! ```
//!
//! The permutation prefix maps to that tier's `HiddenDeck` reserved slots in
//! frozen label order (player id ascending, then slot index ascending); the
//! permutation suffix maps to that tier's deck vector bottom-to-top. The core
//! draws deck tops with `Vec::pop()`, so the last deck element is the top
//! card.
//!
//! (A single Fisher-Yates across the *concatenated* unseen pools cannot
//! satisfy the frozen post-condition that every `HiddenDeck` slot receives a
//! card of its own tier, so the without-replacement permutation is applied
//! per tier, tier order frozen as One, Two, Three, consuming one shared RNG
//! stream.)
//!
//! # Post-conditions
//!
//! After reconstruction the sampler verifies, returning
//! [`BeliefError::SamplingInvariant`] on any violation (never a panic):
//!
//! - `sampled_state.observation(viewer) == *information_set.observation()`;
//! - all 90 cards appear exactly once across market / purchased / reserved /
//!   decks;
//! - every deck length equals `observation.public.deck_counts[tier]`;
//! - every `HiddenDeck` slot received a card of the correct tier;
//! - every `Known` reserved slot keeps its card identity and `from_deck` flag.

use sha2::{Digest, Sha256};

use splendor_catalog::{card, CardId, Tier, CARD_COUNT};
use splendor_core::{
    full_state_hash, FullPlayerState, FullState, GameEvent, Phase, PlayerId, ReservedCard,
};

use crate::deterministic_rng::DeterministicRng;
use crate::error::BeliefError;
use crate::model::{DeterminizationV1, InformationSetV1, ReservedKnowledgeV1};

/// Frozen domain for the synthetic referee-state seed.
const STATE_SEED_DOMAIN: &str = "effective-splendor-determinization-state-seed-v1\0";

/// Maximum number of market slots per tier (frozen layout).
const MARKET_SLOTS: usize = 4;

/// Sample one deterministic hidden-state completion of `information_set`.
pub fn sample_determinization_v1(
    information_set: &InformationSetV1,
    sample_seed: u64,
    sample_index: u64,
) -> Result<DeterminizationV1, BeliefError> {
    let observation = information_set.observation();
    let public = &observation.public;
    if public.phase == Phase::GameOver {
        return Err(BeliefError::TerminalInformationSet);
    }

    // One shared frozen RNG stream for the whole sample.
    let mut key = Vec::with_capacity(64 + 16);
    key.extend_from_slice(information_set.information_set_hash().as_str().as_bytes());
    key.extend_from_slice(&sample_seed.to_le_bytes());
    key.extend_from_slice(&sample_index.to_le_bytes());
    let mut rng = DeterministicRng::new(key);

    // HiddenDeck labels per tier: (player, slot index), player-ascending then
    // slot-ascending within the tier.
    let mut hidden_by_tier: [Vec<(PlayerId, usize)>; 3] = Default::default();
    for player_knowledge in information_set.reserved_knowledge() {
        for (slot_index, slot) in player_knowledge.slots.iter().enumerate() {
            if let ReservedKnowledgeV1::HiddenDeck { tier } = slot {
                hidden_by_tier[tier.index()].push((player_knowledge.player, slot_index));
            }
        }
    }

    // Reserved vectors: restore Known slots as-is; HiddenDeck slots get the
    // sampled card, written in place by the per-tier loop below.
    let mut reserved_by_player: Vec<Vec<ReservedCard>> = information_set
        .reserved_knowledge()
        .iter()
        .map(|pk| {
            pk.slots
                .iter()
                .map(|slot| match slot {
                    ReservedKnowledgeV1::Known { card, from_deck } => ReservedCard {
                        card: *card,
                        from_deck: *from_deck,
                    },
                    ReservedKnowledgeV1::HiddenDeck { .. } => ReservedCard {
                        card: CardId(0), // placeholder; filled by sampling
                        from_deck: true,
                    },
                })
                .collect()
        })
        .collect();

    let mut decks: [Vec<CardId>; 3] = Default::default();
    for tier in Tier::ALL {
        let t = tier.index();
        let mut pool = information_set.unseen_cards(tier).to_vec();
        fisher_yates_in_place(&mut rng, &mut pool);

        let hidden_count = hidden_by_tier[t].len();
        let deck_len = public.deck_counts[t] as usize;
        if pool.len() != hidden_count + deck_len {
            return Err(BeliefError::SamplingInvariant(format!(
                "tier {tier:?} unseen pool {} != hidden {hidden_count} + deck {deck_len}",
                pool.len()
            )));
        }

        // Prefix -> HiddenDeck labels in frozen order.
        for (k, (player, slot_index)) in hidden_by_tier[t].iter().enumerate() {
            let sampled = pool[k];
            if card(sampled).tier != tier {
                return Err(BeliefError::SamplingInvariant(format!(
                    "tier {tier:?} hidden slot sampled card {sampled:?} of wrong tier"
                )));
            }
            reserved_by_player[player.index()][*slot_index] = ReservedCard {
                card: sampled,
                from_deck: true,
            };
        }

        // Suffix -> deck vector bottom-to-top (last element is the top card).
        decks[t] = pool[hidden_count..].to_vec();
    }

    // Synthetic internal seed derived from the sample key (never a real seed).
    let seed = synthetic_state_seed(information_set, sample_seed, sample_index);

    let state = FullState {
        ruleset: information_set.ruleset(),
        seed,
        decks,
        market: public.market,
        nobles: public.nobles.clone(),
        bank: public.bank,
        players: public
            .players
            .iter()
            .map(|view| FullPlayerState {
                id: view.id,
                tokens: view.tokens,
                bonuses: view.bonuses,
                prestige: view.prestige,
                reserved: reserved_by_player[view.id.index()].clone(),
                purchased: view.purchased.clone(),
                nobles: view.nobles.clone(),
            })
            .collect(),
        current_player: public.current_player,
        phase: public.phase,
        pending_nobles: public.pending_nobles.clone(),
        end_game_triggered: public.end_game_triggered,
        turns_remaining_in_final_round: public.turns_remaining_in_final_round,
        consecutive_forced_passes: public.consecutive_forced_passes,
        result: None,
        log: Vec::<GameEvent>::new(),
    };

    verify_sampled_state(&state, information_set)?;

    let state_hash = full_state_hash(&state);
    Ok(DeterminizationV1::new(
        state,
        state_hash,
        sample_seed,
        sample_index,
    ))
}

/// Frozen Fisher-Yates: `for i from len-1 down to 1 { j = draw_below(i+1); swap(i,j) }`.
fn fisher_yates_in_place<T>(rng: &mut DeterministicRng, items: &mut [T]) {
    let len = items.len();
    for i in (1..len).rev() {
        let j = rng.draw_below((i + 1) as u64) as usize;
        items.swap(i, j);
    }
}

/// Synthetic referee-state seed: first 8 bytes of
/// `SHA-256(STATE_SEED_DOMAIN || info-set hash || sample_seed LE || sample_index LE)`,
/// interpreted little-endian.
fn synthetic_state_seed(
    information_set: &InformationSetV1,
    sample_seed: u64,
    sample_index: u64,
) -> u64 {
    let mut hasher = Sha256::new();
    hasher.update(STATE_SEED_DOMAIN.as_bytes());
    hasher.update(information_set.information_set_hash().as_str().as_bytes());
    hasher.update(sample_seed.to_le_bytes());
    hasher.update(sample_index.to_le_bytes());
    let digest = hasher.finalize();
    let mut bytes = [0u8; 8];
    bytes.copy_from_slice(&digest[..8]);
    u64::from_le_bytes(bytes)
}

/// Verify every frozen post-condition of a sampled state.
fn verify_sampled_state(
    state: &FullState,
    information_set: &InformationSetV1,
) -> Result<(), BeliefError> {
    let observation = information_set.observation();
    let public = &observation.public;

    // Observation equality is the strongest check: it covers the public board,
    // deck counts, viewer private reserved cards, current player, phase, ...
    if state.observation(observation.viewer) != *observation {
        return Err(BeliefError::SamplingInvariant(
            "state.observation(viewer) != information set observation".to_string(),
        ));
    }

    // All 90 cards exactly once (also implies market/purchased/reserved/decks
    // are pairwise disjoint).
    let mut seen = [false; CARD_COUNT];
    for tier in Tier::ALL {
        let t = tier.index();
        if state.market[t].len() != MARKET_SLOTS {
            return Err(BeliefError::SamplingInvariant(format!(
                "market tier {tier:?} has {} slots, expected {MARKET_SLOTS}",
                state.market[t].len()
            )));
        }
        for card in state.market[t].iter().flatten() {
            if !mark_seen(&mut seen, *card, "market", tier)? {
                return Err(BeliefError::SamplingInvariant(format!(
                    "duplicate card {card:?} in market tier {tier:?}"
                )));
            }
        }
    }
    for player in &state.players {
        for card in &player.purchased {
            if !mark_seen(&mut seen, *card, "purchased", tier_of(*card))? {
                return Err(BeliefError::SamplingInvariant(format!(
                    "duplicate card {card:?} in purchased of player {:?}",
                    player.id
                )));
            }
        }
        for reserved in &player.reserved {
            if !mark_seen(&mut seen, reserved.card, "reserved", tier_of(reserved.card))? {
                return Err(BeliefError::SamplingInvariant(format!(
                    "duplicate card {:?} in reserved of player {:?}",
                    reserved.card, player.id
                )));
            }
        }
    }
    for tier in Tier::ALL {
        for card in &state.decks[tier.index()] {
            if !mark_seen(&mut seen, *card, "deck", tier)? {
                return Err(BeliefError::SamplingInvariant(format!(
                    "duplicate card {card:?} in tier {tier:?} deck"
                )));
            }
        }
        // Deck length post-condition.
        if state.decks[tier.index()].len() != public.deck_counts[tier.index()] as usize {
            return Err(BeliefError::SamplingInvariant(format!(
                "tier {tier:?} deck length {} != deck_counts {}",
                state.decks[tier.index()].len(),
                public.deck_counts[tier.index()]
            )));
        }
    }
    if seen.iter().filter(|s| **s).count() != CARD_COUNT {
        return Err(BeliefError::SamplingInvariant(format!(
            "card partition covers {} of {CARD_COUNT} cards",
            seen.iter().filter(|s| **s).count()
        )));
    }

    // HiddenDeck slots: tier correctness and Known regions unchanged.
    for player_knowledge in information_set.reserved_knowledge() {
        let state_player = &state.players[player_knowledge.player.index()];
        if state_player.reserved.len() != player_knowledge.slots.len() {
            return Err(BeliefError::SamplingInvariant(format!(
                "player {:?} reserved length mismatch",
                player_knowledge.player
            )));
        }
        for (slot_index, slot) in player_knowledge.slots.iter().enumerate() {
            let reserved = &state_player.reserved[slot_index];
            match slot {
                ReservedKnowledgeV1::Known { card, from_deck } => {
                    if reserved.card != *card || reserved.from_deck != *from_deck {
                        return Err(BeliefError::SamplingInvariant(format!(
                            "player {:?} slot {slot_index} known card changed",
                            player_knowledge.player
                        )));
                    }
                }
                ReservedKnowledgeV1::HiddenDeck { tier } => {
                    if !reserved.from_deck {
                        return Err(BeliefError::SamplingInvariant(format!(
                            "player {:?} slot {slot_index} hidden reserve lost from_deck",
                            player_knowledge.player
                        )));
                    }
                    if card(reserved.card).tier != *tier {
                        return Err(BeliefError::SamplingInvariant(format!(
                            "player {:?} slot {slot_index} hidden reserve card {:?} tier mismatch",
                            player_knowledge.player, reserved.card
                        )));
                    }
                }
            }
        }
    }

    Ok(())
}

fn tier_of(id: CardId) -> Tier {
    card(id).tier
}

fn mark_seen(
    seen: &mut [bool; CARD_COUNT],
    card: CardId,
    region: &str,
    tier: Tier,
) -> Result<bool, BeliefError> {
    let index = card.index();
    if index >= CARD_COUNT {
        return Err(BeliefError::SamplingInvariant(format!(
            "card {card:?} out of catalog in {region} (tier {tier:?})"
        )));
    }
    let slot = &mut seen[index];
    let first = !*slot;
    *slot = true;
    Ok(first)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::deterministic_rng::DeterministicRng;

    #[test]
    fn fisher_yates_small_vector_frozen() {
        // Frozen golden permutation for the 4-element pool [1,2,3,4] with key
        // "fy-test": deterministic across runs.
        let mut rng = DeterministicRng::new(b"fy-test".to_vec());
        let mut items = [1u32, 2, 3, 4];
        fisher_yates_in_place(&mut rng, &mut items);
        let golden = [1u32, 4, 2, 3];
        assert_eq!(items, golden);
    }
}
