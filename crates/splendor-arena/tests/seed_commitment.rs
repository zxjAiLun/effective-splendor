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

#[test]
fn seed_commitment_rejects_uppercase_hex() {
    // Uppercase form of the frozen vector digest must be rejected: lowercase
    // only.
    let upper = "E19E4C351E3AD58ECAD21D70B9DDB89B0495A2C419C00D973C7835EB99EE87E8";
    let res = serde_json::from_str::<SeedCommitment>(&format!("\"{upper}\""));
    assert!(res.is_err(), "uppercase hex must be rejected");
}

#[test]
fn seed_commitment_rejects_non_hex() {
    // Contains 'g' (non-hex) and is the wrong length.
    let bad = "g19e4c351e3ad58ecad21d70b9ddb89b0495a2c419c00d973c7835eb99ee87e8";
    assert!(
        serde_json::from_str::<SeedCommitment>(&format!("\"{bad}\"")).is_err(),
        "non-hex string must be rejected"
    );
    // Wrong length.
    let short = "abc123";
    assert!(
        serde_json::from_str::<SeedCommitment>(&format!("\"{short}\"")).is_err(),
        "wrong-length hex must be rejected"
    );
}

#[test]
fn ruleset_fingerprint_from_str_rejects_uppercase() {
    let upper = "FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF";
    assert!(
        RulesetFingerprint::from_str(upper).is_err(),
        "uppercase fingerprint must be rejected"
    );
}

#[test]
fn ruleset_fingerprint_from_str_accepts_lowercase() {
    let lower = "00000000000000000000000000000000000000000000000000000000000000aa";
    assert!(
        RulesetFingerprint::from_str(lower).is_ok(),
        "lowercase fingerprint must be accepted"
    );
}
