use std::fs;

use serde_json::Value;
use sha2::{Digest, Sha256};

/// Hash the canonical LF byte form of a tracked text artifact so the contract
/// is line-ending independent: a CRLF Windows checkout and an LF checkout of
/// the same file must produce the same hash. CRLF and lone CR both normalize
/// to LF (valid JSON never contains a raw CR inside a string value).
fn sha256_canonical(bytes: &[u8]) -> String {
    let mut normalized = Vec::with_capacity(bytes.len());
    let mut index = 0usize;
    while index < bytes.len() {
        if bytes[index] == b'\r' {
            normalized.push(b'\n');
            if index + 1 < bytes.len() && bytes[index + 1] == b'\n' {
                index += 1;
            }
        } else {
            normalized.push(bytes[index]);
        }
        index += 1;
    }
    hex::encode(Sha256::digest(&normalized))
}

#[test]
fn m21_defers_external_work_and_binds_completed_internal_routes() {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let decision: Value = serde_json::from_slice(
        &fs::read(root.join("benchmarks/m21-external-benchmark-decision-v1.json")).unwrap(),
    )
    .unwrap();

    assert_eq!(
        decision["evidence_contract_commit"],
        "86c44657695d4db7f24ddfae752727e09b745097"
    );
    assert_eq!(decision["status"], "complete_decision_deferred");
    assert_eq!(decision["scope"], "1v1_only");
    assert_eq!(decision["decision"]["external_benchmark"], "deferred");
    assert_eq!(
        decision["decision"]["external_teacher_training"],
        "not_authorized"
    );
    assert_eq!(decision["decision"]["external_model_downloaded"], false);
    assert_eq!(decision["decision"]["external_match_executed"], false);
    assert_eq!(decision["reopen_gate"]["all_required"], true);
    assert_eq!(
        decision["reopen_gate"]["conditions"]
            .as_array()
            .unwrap()
            .len(),
        4
    );

    for key in [
        "m17_own_gpu_model",
        "m18a_alpha_zero_like",
        "m18b_rainbow",
        "m19_internal_championship",
    ] {
        let evidence = &decision["prerequisites"][key];
        let path = evidence["result_path"].as_str().unwrap();
        let expected = evidence["result_file_sha256"].as_str().unwrap();
        assert_eq!(
            sha256_canonical(&fs::read(root.join(path)).unwrap()),
            expected
        );
    }

    assert_eq!(
        decision["prerequisites"]["m19_internal_championship"]["completed_matches"],
        42
    );
    assert_eq!(
        decision["prerequisites"]["m19_internal_championship"]["aborted_matches"],
        0
    );
    assert_eq!(
        decision["prerequisites"]["m19_internal_championship"]["champion_decision"],
        "unchanged_m07"
    );
}
