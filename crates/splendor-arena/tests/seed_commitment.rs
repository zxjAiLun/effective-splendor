use splendor_arena::seed_commitment::{seed_commitment_v1, SeedCommitment};
use splendor_core::RulesetFingerprint;
use std::str::FromStr;

const CONTROL_FP: &str = "00000000000000000000000000000000000000000000000000000000000000aa";

fn control_fp() -> RulesetFingerprint {
    RulesetFingerprint::from_str(CONTROL_FP).unwrap()
}

#[test]
fn seed_commitment_matches_fixed_vector() {
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
    let other = RulesetFingerprint::from_str(
        "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
    )
    .unwrap();
    let b = seed_commitment_v1("g1", 2, 42, &other);
    assert_ne!(a, b);
}

#[test]
fn seed_commitment_is_stable_newtype_and_hex() {
    let fp = control_fp();
    let a: SeedCommitment = seed_commitment_v1("GAME", 4, 0xFFFF_FFFF_FFFF_FFFF, &fp);
    let b = seed_commitment_v1("GAME", 4, 0xFFFF_FFFF_FFFF_FFFF, &fp);
    assert_eq!(a, b);
    assert_eq!(a.as_str(), a.as_str().to_ascii_lowercase());
    assert!(a.as_str().bytes().all(|b| b.is_ascii_hexdigit()));
}
