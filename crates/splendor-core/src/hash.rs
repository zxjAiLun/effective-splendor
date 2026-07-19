use sha2::{Digest, Sha256};

use crate::observation::Observation;
use crate::state::{FullState, Phase, PlayerId};

/// Raw hex string produced by a hasher. Internal only; prefer the typed wrappers.
pub type HashHex = String;

/// Canonical hash of the full referee state.
///
/// **Private to the referee.** Includes deck order and every reserved `CardId`,
/// so it is a fingerprint of information players must never see. It must never
/// be serialized into a protocol message or an agent transcript.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct FullStateHash(pub HashHex);

impl FullStateHash {
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl std::fmt::Display for FullStateHash {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

/// Hash of public information only (board + public reserved identities).
///
/// Safe to show to any spectator or as a ruleset/catalog fingerprint.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct PublicStateHash(pub HashHex);

impl PublicStateHash {
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl std::fmt::Display for PublicStateHash {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

/// Hash of a single player's observation (public board + own private cards).
///
/// This is what the protocol attaches to `Observation`/`RequestAction` messages.
/// Two observations that a player cannot distinguish will hash identically.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct ObservationHash(pub HashHex);

impl ObservationHash {
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl std::fmt::Display for ObservationHash {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

fn finish(hasher: Sha256) -> HashHex {
    hex::encode(hasher.finalize())
}

fn write_gems(h: &mut Sha256, g: crate::gems::Gems) {
    h.update([g.white, g.blue, g.green, g.red, g.black, g.gold]);
}

/// Canonical hash of the full referee state (includes private info + deck).
pub fn full_state_hash(state: &FullState) -> FullStateHash {
    let mut h = Sha256::new();
    // Deterministic, version-tagged encoding. No serde_json in hot path.
    h.update(b"splendor-full-v2|");
    h.update(state.ruleset.id.0.as_bytes());
    h.update(b"|");
    h.update(state.ruleset.catalog_version.as_bytes());
    h.update(b"|");
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

    // Players (full private info)
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

    // Terminal result summary (if finished)
    if let Some(res) = &state.result {
        h.update(b"|result|");
        for s in &res.scores {
            h.update([*s]);
        }
        h.update([res.reason as u8]);
        for w in &res.winners {
            h.update([w.0]);
        }
    }

    FullStateHash(finish(h))
}

/// Hash of public information only.
pub fn public_state_hash(state: &FullState) -> PublicStateHash {
    let obs = state.observation(state.current_player); // public fields via any observer
    let mut h = Sha256::new();
    h.update(b"splendor-public-v2|");
    h.update(state.ruleset.id.0.as_bytes());
    h.update(b"|");
    h.update(state.ruleset.catalog_version.as_bytes());
    h.update(b"|");
    let pub_s = &obs.public;
    h.update([pub_s.player_count]);
    h.update([pub_s.current_player.0]);
    h.update([phase_byte(pub_s.phase)]);
    h.update([pub_s.end_game_triggered as u8]);
    h.update([pub_s.turns_remaining_in_final_round.unwrap_or(0xFF)]);
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
        h.update([p.prestige, p.reserved_count]);
        // Public reserved card identities are part of public info.
        h.update([p.public_reserved.len() as u8]);
        for c in &p.public_reserved {
            h.update([c.0]);
        }
        h.update([p.nobles.len() as u8]);
        for n in &p.nobles {
            h.update([n.0]);
        }
    }
    // Pending noble choices are public.
    h.update([pub_s.pending_nobles.len() as u8]);
    for n in &pub_s.pending_nobles {
        h.update([n.0]);
    }
    PublicStateHash(finish(h))
}

/// Hash of a single player's observation. Deterministic + stable: no `Debug`
/// formatting, so refactors of `Observation` field repr don't silently change it.
pub fn observation_hash(obs: &Observation) -> ObservationHash {
    let mut h = Sha256::new();
    h.update(b"splendor-obs-v2|");
    h.update([obs.viewer.0]);

    // Public fields
    let pub_s = &obs.public;
    h.update([pub_s.player_count]);
    h.update([pub_s.current_player.0]);
    h.update([phase_byte(pub_s.phase)]);
    h.update([pub_s.end_game_triggered as u8]);
    h.update([pub_s.turns_remaining_in_final_round.unwrap_or(0xFF)]);
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
        h.update([p.prestige, p.reserved_count]);
        h.update([p.public_reserved.len() as u8]);
        for c in &p.public_reserved {
            h.update([c.0]);
        }
        h.update([p.nobles.len() as u8]);
        for n in &p.nobles {
            h.update([n.0]);
        }
    }
    h.update([pub_s.pending_nobles.len() as u8]);
    for n in &pub_s.pending_nobles {
        h.update([n.0]);
    }

    // Private fields (only the viewer sees these)
    h.update([obs.private.reserved.len() as u8]);
    for r in &obs.private.reserved {
        h.update([r.slot, r.card.0, r.tier as u8, r.from_deck as u8]);
    }

    ObservationHash(finish(h))
}

fn phase_byte(phase: Phase) -> u8 {
    match phase {
        Phase::Main => 0,
        Phase::ChooseNoble => 1,
        Phase::GameOver => 2,
    }
}

/// Convenience: identity of `who` as seen by `viewer`. Used by leak tests.
pub fn observer_hash(state: &FullState, viewer: PlayerId) -> ObservationHash {
    observation_hash(&state.observation(viewer))
}
