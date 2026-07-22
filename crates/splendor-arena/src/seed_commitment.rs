//! Seed commitment (v1), algorithm locked.
//!
//! The commitment binds `game_id`, `player_count`, `seed`, and the
//! `ruleset_fingerprint` into a single 64-char lowercase-hex SHA-256 digest.
//! It is published in `game_start` so that, once a match is complete, the
//! exact (game_id, player_count, seed, ruleset) triple can be independently
//! recomputed and verified against the value the agents saw.

use sha2::{Digest, Sha256};
use splendor_core::RulesetFingerprint;
#[cfg(test)]
use std::str::FromStr;

/// Domain separation prefix for the v1 seed commitment.
const SEED_COMMITMENT_DOMAIN: &[u8] = b"effective-splendor-seed-v1\x00";

/// A strict seed-commitment digest. The inner string is always exactly 64
/// lowercase-hex characters; construction is only possible through a hashing
/// path, so an arbitrary (possibly malformed) string cannot be smuggled in.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct SeedCommitment(String);

impl SeedCommitment {
    /// The 64-char lowercase-hex digest.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl std::fmt::Display for SeedCommitment {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl serde::Serialize for SeedCommitment {
    fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&self.0)
    }
}

impl<'de> serde::Deserialize<'de> for SeedCommitment {
    fn deserialize<D: serde::Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let raw = String::deserialize(deserializer)?;
        if raw.len() != 64 || !raw.bytes().all(|b| b.is_ascii_hexdigit()) {
            return Err(serde::de::Error::custom(
                "seed commitment must be 64 hex chars",
            ));
        }
        Ok(SeedCommitment(raw))
    }
}

/// Build a `RulesetFingerprint` from a 64-char lowercase-hex string. Used to
/// pin the fixed-vector test against a controlled digest independent of the
/// live `Ruleset::base()` fingerprint.
#[cfg(test)]
fn fingerprint_from_hex(hex: &str) -> RulesetFingerprint {
    RulesetFingerprint::from_str(hex).expect("valid 64-hex fingerprint in test")
}

/// Compute the v1 seed commitment.
///
/// ```text
/// SHA-256(
///     "effective-splendor-seed-v1\0"
///     || game_id_len_u32_le
///     || game_id_utf8
///     || player_count_u8
///     || seed_u64_le
///     || ruleset_fingerprint_ascii_hex
/// )
/// ```
pub fn seed_commitment_v1(
    game_id: &str,
    player_count: u8,
    seed: u64,
    fingerprint: &RulesetFingerprint,
) -> SeedCommitment {
    let mut hasher = Sha256::new();
    hasher.update(SEED_COMMITMENT_DOMAIN);
    hasher.update((game_id.len() as u32).to_le_bytes());
    hasher.update(game_id.as_bytes());
    hasher.update([player_count]);
    hasher.update(seed.to_le_bytes());
    hasher.update(fingerprint.to_string().as_bytes());
    let digest = hasher.finalize();
    SeedCommitment(hex::encode(digest))
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A fixed, controlled fingerprint (64 hex chars) so the digest below is
    /// fully determined and independent of any live `Ruleset`.
    const CONTROL_FP: &str = "00000000000000000000000000000000000000000000000000000000000000aa";

    fn control_fp() -> RulesetFingerprint {
        fingerprint_from_hex(CONTROL_FP)
    }

    #[test]
    fn seed_commitment_matches_fixed_vector() {
        // Inputs (controlled fingerprint so the digest is fully determined):
        //   game_id = "g1"
        //   player_count = 2
        //   seed = 42
        //   fingerprint = CONTROL_FP (64 x '0' except trailing "aa")
        // The literal below is the SHA-256 of the exact byte layout above,
        // computed once and frozen here to pin the algorithm.
        let commit = seed_commitment_v1("g1", 2, 42, &control_fp());
        assert_eq!(
            commit.as_str(),
            "e19e4c351e3ad58ecad21d70b9ddb89b0495a2c419c00d973c7835eb99ee87e8"
        );
    }

    #[test]
    fn seed_commitment_changes_with_game_id() {
        let fp = control_fp();
        let a = seed_commitment_v1("g1", 2, 42, &fp);
        let b = seed_commitment_v1("g2", 2, 42, &fp);
        assert_ne!(a, b);
    }

    #[test]
    fn seed_commitment_changes_with_player_count() {
        let fp = control_fp();
        let a = seed_commitment_v1("g1", 2, 42, &fp);
        let b = seed_commitment_v1("g1", 3, 42, &fp);
        assert_ne!(a, b);
    }

    #[test]
    fn seed_commitment_changes_with_seed() {
        let fp = control_fp();
        let a = seed_commitment_v1("g1", 2, 42, &fp);
        let b = seed_commitment_v1("g1", 2, 43, &fp);
        assert_ne!(a, b);
    }

    #[test]
    fn seed_commitment_changes_with_fingerprint() {
        let a = seed_commitment_v1("g1", 2, 42, &control_fp());
        let other = fingerprint_from_hex(
            "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
        );
        let b = seed_commitment_v1("g1", 2, 42, &other);
        assert_ne!(a, b);
    }

    #[test]
    fn seed_commitment_is_lowercase_hex_and_deterministic() {
        let fp = control_fp();
        let a = seed_commitment_v1("GAME", 4, 0xFFFF_FFFF_FFFF_FFFF, &fp);
        let b = seed_commitment_v1("GAME", 4, 0xFFFF_FFFF_FFFF_FFFF, &fp);
        assert_eq!(a, b);
        assert_eq!(a.as_str(), a.as_str().to_ascii_lowercase());
        assert!(a.as_str().bytes().all(|b| b.is_ascii_hexdigit()));
    }
}
