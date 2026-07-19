use sha2::{Digest, Sha256};

use crate::observation::Observation;
use crate::state::FullState;

pub type HashHex = String;

fn finish(hasher: Sha256) -> HashHex {
    hex::encode(hasher.finalize())
}

/// Canonical hash of the full referee state (includes private info + deck).
pub fn full_state_hash(state: &FullState) -> HashHex {
    let mut h = Sha256::new();
    // Deterministic, version-tagged serialization without serde_json dependency
    // in hot path — hand-rolled compact encoding.
    h.update(b"splendor-full-v1|");
    h.update([state.player_count()]);
    h.update([state.current_player.0]);
    h.update([phase_byte(state.phase)]);
    h.update([state.end_game_triggered as u8]);
    h.update([state.turns_remaining_in_final_round.unwrap_or(0xFF)]);

    // Bank
    write_gems(&mut h, state.bank);

    // Market
    for tier in 0..3 {
        for slot in 0..4 {
            match state.market[tier][slot] {
                Some(id) => {
                    h.update([1, id.0]);
                }
                None => h.update([0, 0]),
            }
        }
    }

    // Decks (order matters)
    for tier in 0..3 {
        let deck = &state.decks[tier];
        h.update((deck.len() as u16).to_le_bytes());
        for id in deck {
            h.update([id.0]);
        }
    }

    // Nobles
    h.update([state.nobles.len() as u8]);
    for n in &state.nobles {
        h.update([n.0]);
    }

    // Players
    for p in &state.players {
        write_gems(&mut h, p.tokens);
        for b in p.bonuses {
            h.update([b]);
        }
        h.update([p.prestige]);
        h.update([p.reserved.len() as u8]);
        for r in &p.reserved {
            h.update([r.card.0, r.from_deck as u8]);
        }
        h.update([p.nobles.len() as u8]);
        for n in &p.nobles {
            h.update([n.0]);
        }
    }

    // Pending noble choices
    h.update([state.pending_nobles.len() as u8]);
    for n in &state.pending_nobles {
        h.update([n.0]);
    }

    finish(h)
}

/// Hash of public information only.
pub fn public_state_hash(state: &FullState) -> HashHex {
    let obs = state.observation(state.current_player); // uses public fields via any observer
                                                       // Better: hash PublicState directly
    let mut h = Sha256::new();
    h.update(b"splendor-public-v1|");
    let pub_s = &obs.public;
    h.update([pub_s.player_count]);
    h.update([pub_s.current_player.0]);
    h.update([phase_byte(pub_s.phase)]);
    write_gems(&mut h, pub_s.bank);
    for tier in 0..3 {
        for slot in 0..4 {
            match pub_s.market[tier][slot] {
                Some(id) => h.update([1, id.0]),
                None => h.update([0, 0]),
            }
        }
        h.update([pub_s.deck_counts[tier]]);
    }
    h.update([pub_s.nobles.len() as u8]);
    for n in &pub_s.nobles {
        h.update([n.0]);
    }
    for p in &pub_s.players {
        write_gems(&mut h, p.tokens);
        for b in p.bonuses {
            h.update([b]);
        }
        h.update([p.prestige, p.reserved_count, p.nobles.len() as u8]);
        for n in &p.nobles {
            h.update([n.0]);
        }
    }
    finish(h)
}

/// Hash of a single player's observation (for leak tests / agent caches).
pub fn observation_hash(obs: &Observation) -> HashHex {
    let mut h = Sha256::new();
    h.update(b"splendor-obs-v1|");
    h.update([obs.viewer.0]);
    // public
    let jsonish = format!("{:?}", obs);
    h.update(jsonish.as_bytes());
    finish(h)
}

fn phase_byte(phase: crate::state::Phase) -> u8 {
    match phase {
        crate::state::Phase::Main => 0,
        crate::state::Phase::ChooseNoble => 1,
        crate::state::Phase::GameOver => 2,
    }
}

fn write_gems(h: &mut Sha256, g: crate::gems::Gems) {
    h.update([g.white, g.blue, g.green, g.red, g.black, g.gold]);
}
