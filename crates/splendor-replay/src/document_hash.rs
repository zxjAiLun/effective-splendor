//! Canonical replay document identity hash.
//!
//! A replay's *document hash* identifies the exact replay content — every
//! field, step, action and recorded hash — independently of how the input
//! file happened to be formatted on disk. It is deliberately distinct from
//! `final_state_hash`: two different action histories could in principle
//! reach the same final state, so the final state hash is not a replay
//! identity.

use sha2::{Digest, Sha256};

use crate::error::{ReplayError, ReplayResult};
use crate::format::ReplayV1;

/// Frozen domain-separation prefix for the v1 replay document hash.
const REPLAY_DOCUMENT_HASH_DOMAIN_V1: &[u8] = b"effective-splendor-replay-document-v1\0";

/// Compute the frozen v1 document hash of a parsed replay.
///
/// Algorithm (frozen):
///
/// ```text
/// SHA-256(
///   b"effective-splendor-replay-document-v1\0"
///   || serde_json canonical compact encoding of ReplayV1
/// )
/// ```
///
/// The hash is computed over the *parsed* `ReplayV1` re-serialized with the
/// fixed field order and compact separators of `serde_json::to_string`, so it
/// is deterministic for a given document and unaffected by whitespace or
/// pretty-printing in the input file. Any change to a replay field, step,
/// action or recorded hash changes the document hash.
///
/// This is an identity over *content only*; it performs no verification.
/// Callers that need a verified identity (such as the analyze-replay CLI)
/// must verify the replay first and only then hash it.
pub fn replay_document_hash_v1(replay: &ReplayV1) -> ReplayResult<String> {
    let json = serde_json::to_string(replay).map_err(|e| ReplayError::Json(e.to_string()))?;
    let mut hasher = Sha256::new();
    hasher.update(REPLAY_DOCUMENT_HASH_DOMAIN_V1);
    hasher.update(json.as_bytes());
    Ok(lower_hex(&hasher.finalize()))
}

/// Lowercase hex encoding of a digest.
fn lower_hex(bytes: &[u8]) -> String {
    use std::fmt::Write;
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        let _ = write!(out, "{byte:02x}");
    }
    out
}
