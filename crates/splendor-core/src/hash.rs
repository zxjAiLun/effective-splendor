use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use splendor_catalog::Ruleset;

use crate::observation::{Observation, PublicState};
use crate::state::{FullState, GameResult, Phase, PlayerId, TerminalReason};

/// Raw hex string produced by a hasher. Prefer the typed wrappers at API
/// boundaries; this alias is retained for internal compatibility.
pub type HashHex = String;

/// Canonical hash of the full referee state.
///
/// This is private referee material. It includes deck order and every reserved
/// `CardId`, so it must never be put in an agent-facing protocol message.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct FullStateHash(HashHex);

impl FullStateHash {
    pub fn as_str(&self) -> &str {
        &self.0
    }

    pub(crate) fn empty() -> Self {
        Self(String::new())
    }
}

impl std::fmt::Display for FullStateHash {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

/// Hash of public information only (board + public reserved identities).
///
/// This type is safe to expose publicly and identifies a particular public
/// game state. It is not interchangeable with a ruleset fingerprint.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct PublicStateHash(HashHex);

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

/// Fingerprint of the ruleset/catalog parameters, independent of a game
/// state. This is used for compatibility negotiation and observation scope.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct RulesetFingerprint(HashHex);

impl RulesetFingerprint {
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl std::fmt::Display for RulesetFingerprint {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

/// True only for lowercase ASCII hex digits (`0-9`, `a-f`). Uppercase `A-F` is
/// rejected so a fingerprint never silently accepts a different casing than it
/// emits.
fn is_lower_hex(byte: u8) -> bool {
    byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)
}

impl std::str::FromStr for RulesetFingerprint {
    type Err = String;

    /// Parse from a 64-char lowercase-hex digest. Used by tests and tooling
    /// that pin a known fingerprint without rebuilding a full `Ruleset`.
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        if s.len() != 64 || !s.bytes().all(is_lower_hex) {
            return Err("ruleset fingerprint must be 64 lowercase hex characters".to_string());
        }
        Ok(RulesetFingerprint(s.to_string()))
    }
}

/// Hash of a single player's observation (public board + own private cards).
///
/// This is the only state hash that the protocol may carry.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct ObservationHash(HashHex);

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

fn write_len(h: &mut Sha256, len: usize) {
    h.update((len as u64).to_le_bytes());
}

fn write_bytes(h: &mut Sha256, bytes: &[u8]) {
    write_len(h, bytes.len());
    h.update(bytes);
}

fn write_str(h: &mut Sha256, value: &str) {
    write_bytes(h, value.as_bytes());
}

fn write_gems(h: &mut Sha256, g: crate::gems::Gems) {
    h.update([g.white, g.blue, g.green, g.red, g.black, g.gold]);
}

fn write_ruleset(h: &mut Sha256, ruleset: &Ruleset) {
    write_str(h, ruleset.id.0);
    write_str(h, ruleset.catalog_version);
    h.update([
        ruleset.min_players,
        ruleset.max_players,
        ruleset.prestige_to_end,
        ruleset.max_tokens,
        ruleset.max_reserved,
        ruleset.market_slots_per_tier,
        ruleset.gold_tokens,
        ruleset.noble_extra,
    ]);
    h.update(ruleset.color_tokens_by_players);
}

fn write_option_u8(h: &mut Sha256, value: Option<u8>) {
    match value {
        Some(value) => h.update([1, value]),
        None => h.update([0]),
    }
}

fn write_card_option(h: &mut Sha256, value: Option<splendor_catalog::CardId>) {
    match value {
        Some(value) => h.update([1, value.0]),
        None => h.update([0]),
    }
}

fn write_nobles(h: &mut Sha256, nobles: &[splendor_catalog::NobleId]) {
    write_len(h, nobles.len());
    for noble in nobles {
        h.update([noble.0]);
    }
}

/// Purchased ownership is a set, not a sequence: canonicalize by `CardId` before
/// hashing so purchase order can never change the semantic state identity, even
/// if a caller hands us an out-of-order `Vec`.
fn write_purchased(h: &mut Sha256, purchased: &[splendor_catalog::CardId]) {
    let mut ids: Vec<u8> = purchased.iter().map(|card| card.0).collect();
    ids.sort_unstable();
    write_len(h, ids.len());
    for id in ids {
        h.update([id]);
    }
}

fn write_result(h: &mut Sha256, result: Option<&GameResult>) {
    let Some(result) = result else {
        h.update([0]);
        return;
    };

    h.update([1]);
    write_len(h, result.scores.len());
    h.update(&result.scores);
    write_len(h, result.ranks.len());
    h.update(&result.ranks);
    write_len(h, result.winners.len());
    for winner in &result.winners {
        h.update([winner.0]);
    }
    h.update([terminal_reason_byte(result.reason)]);
}

fn terminal_reason_byte(reason: TerminalReason) -> u8 {
    match reason {
        TerminalReason::PrestigeThreshold => 0,
        TerminalReason::Stalemate => 1,
    }
}

fn phase_byte(phase: Phase) -> u8 {
    match phase {
        Phase::Main => 0,
        Phase::ChooseNoble => 1,
        Phase::GameOver => 2,
    }
}

fn write_public_state(h: &mut Sha256, public: &PublicState) {
    h.update([public.player_count, public.current_player.0]);
    h.update([phase_byte(public.phase)]);
    h.update([public.end_game_triggered as u8]);
    write_option_u8(h, public.turns_remaining_in_final_round);
    h.update([public.consecutive_forced_passes]);
    write_gems(h, public.bank);

    for tier in 0..3 {
        for slot in 0..4 {
            write_card_option(h, public.market[tier][slot]);
        }
        h.update([public.deck_counts[tier]]);
    }

    write_nobles(h, &public.nobles);
    write_len(h, public.players.len());
    for player in &public.players {
        h.update([player.id.0, player.prestige, player.reserved_count]);
        write_gems(h, player.tokens);
        h.update(player.bonuses);
        write_len(h, player.public_reserved.len());
        for card in &player.public_reserved {
            h.update([card.0]);
        }
        write_purchased(h, &player.purchased);
        write_nobles(h, &player.nobles);
    }

    write_nobles(h, &public.pending_nobles);
}

fn write_observation_private(h: &mut Sha256, observation: &Observation) {
    write_len(h, observation.private.reserved.len());
    for reserved in &observation.private.reserved {
        h.update([
            reserved.slot,
            reserved.card.0,
            reserved.tier as u8,
            reserved.from_deck as u8,
        ]);
    }
}

/// Canonical hash of the full referee state (private info + deck + terminal
/// result). The version tag is part of the input and changes when this encoding
/// changes incompatibly.
pub fn full_state_hash(state: &FullState) -> FullStateHash {
    let mut h = Sha256::new();
    h.update(b"splendor-full-v5\0");
    write_ruleset(&mut h, &state.ruleset);
    h.update(state.seed.to_le_bytes());
    h.update([
        state.player_count(),
        state.current_player.0,
        phase_byte(state.phase),
        state.end_game_triggered as u8,
        state.consecutive_forced_passes,
    ]);
    write_option_u8(&mut h, state.turns_remaining_in_final_round);
    write_gems(&mut h, state.bank);

    for tier in 0..3 {
        for slot in 0..4 {
            write_card_option(&mut h, state.market[tier][slot]);
        }
        write_len(&mut h, state.decks[tier].len());
        for card in &state.decks[tier] {
            h.update([card.0]);
        }
    }

    write_nobles(&mut h, &state.nobles);
    write_len(&mut h, state.players.len());
    for player in &state.players {
        h.update([player.id.0]);
        write_gems(&mut h, player.tokens);
        h.update(player.bonuses);
        h.update([player.prestige]);
        write_len(&mut h, player.reserved.len());
        for reserved in &player.reserved {
            h.update([reserved.card.0, reserved.from_deck as u8]);
        }
        write_purchased(&mut h, &player.purchased);
        write_nobles(&mut h, &player.nobles);
    }

    write_nobles(&mut h, &state.pending_nobles);
    write_result(&mut h, state.result.as_ref());

    FullStateHash(finish(h))
}

/// Hash of public information only.
pub fn public_state_hash(state: &FullState) -> PublicStateHash {
    let mut h = Sha256::new();
    h.update(b"splendor-public-v5\0");
    write_ruleset(&mut h, &state.ruleset);
    write_public_state(&mut h, &state.observation(state.current_player).public);
    // A terminal reason/result is public once the game has ended and must not
    // be silently omitted from the public identity.
    write_result(&mut h, state.result.as_ref());
    PublicStateHash(finish(h))
}

/// Stable fingerprint for ruleset/catalog compatibility negotiation. It does
/// not include a particular game's seed, deck, or initial deal.
pub fn ruleset_fingerprint(ruleset: &Ruleset) -> RulesetFingerprint {
    let mut h = Sha256::new();
    h.update(b"splendor-ruleset-v1\0");
    write_ruleset(&mut h, ruleset);
    RulesetFingerprint(finish(h))
}

/// Hash of a single player's observation. This encoding is explicit and does
/// not depend on `Debug` or serde field formatting.
pub fn observation_hash(observation: &Observation) -> ObservationHash {
    let mut h = Sha256::new();
    h.update(b"splendor-obs-v6\0");
    write_str(&mut h, observation.ruleset_fingerprint.as_str());
    h.update([observation.viewer.0]);
    write_public_state(&mut h, &observation.public);
    write_observation_private(&mut h, observation);
    ObservationHash(finish(h))
}

/// Convenience: hash the observation of `viewer`.
pub fn observer_hash(state: &FullState, viewer: PlayerId) -> ObservationHash {
    observation_hash(&state.observation(viewer))
}
