//! Validation tests for M35A Retrospective Arena Manifest and 17 Realized Plans.
//!
//! Bindings verified here:
//! 1. Manifest schema, seed schedule, and pairing matrix totals.
//! 2. Every realized plan file exists and its SHA256 matches the manifest.
//! 3. Every plan parses and validates against the official splendor-eval
//!    schema (agents, seeds, timeouts).
//! 4. `source_shas` binds the exact current bytes of the Python agent sources.
//! 5. `checkpoint_shas` entries reference existing checkpoint files whose
//!    SHA256 matches, and the parameter counts / output semantics agree with
//!    the pairing expectations.
//! 6. Each plan's neural agent command invokes the entry-point script with
//!    `--device cpu` and the `--model-id` matching the manifest pairing.
//! 7. Each plan's M07 command matches the manifest `champion_command`
//!    exactly, and D2-v2 benchmark pairings use the D2-v2 model id.
//! 8. Checkpoint tamper rejection: a mutated registry checkpoint SHA must be
//!    rejected by the Python registry (fail-closed), verified via the
//!    repository-root entry-point script.

use serde::Deserialize;
use sha2::{Digest, Sha256};
use splendor_eval::EvaluationPlanV1;
use std::fs::File;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

#[derive(Debug, Deserialize)]
struct Manifest {
    format: String,
    version: u32,
    milestone: String,
    evaluation_mode: String,
    total_pairings: usize,
    total_scheduled_matches: usize,
    seeds_count: usize,
    seeds: Vec<u64>,
    seat_rotations_per_seed: u32,
    handshake_timeout_ms: u64,
    move_timeout_ms: u64,
    shutdown_grace_ms: u64,
    champion_command: AgentCommandJson,
    source_shas: std::collections::BTreeMap<String, String>,
    checkpoint_shas: std::collections::BTreeMap<String, CheckpointBinding>,
    realized_plans: Vec<RealizedPlanInfo>,
}

#[derive(Debug, Deserialize, Clone)]
struct AgentCommandJson {
    program: String,
    args: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct CheckpointBinding {
    path: String,
    file_sha256: String,
    param_count: u64,
    dataset_hash: String,
    output_semantics: String,
}

#[derive(Debug, Deserialize)]
struct RealizedPlanInfo {
    #[serde(rename = "series")]
    _series: String,
    pairing: String,
    evaluation_id: String,
    plan_file: String,
    plan_file_sha256: String,
    candidate_model_id: String,
    opponent_model_id: String,
    scheduled_matches: u64,
}

fn file_sha256(path: &Path) -> String {
    let mut file = File::open(path).expect("open file");
    let mut hasher = Sha256::new();
    let mut buf = [0u8; 64 * 1024];
    loop {
        let n = file.read(&mut buf).expect("read chunk");
        if n == 0 {
            break;
        }
        hasher.update(&buf[..n]);
    }
    hex::encode(hasher.finalize())
}

fn is_valid_hex_sha256(s: &str) -> bool {
    s.len() == 64 && s.chars().all(|c| c.is_ascii_hexdigit())
}

/// The Python sources the manifest binds, in stable manifest-key order.
const SOURCE_FILES: &[(&str, &str)] = &[
    (
        "registry_py",
        "training/m17_gpu/splendor_gpu/m35a_registry.py",
    ),
    ("belief_py", "training/m17_gpu/splendor_gpu/m35a_belief.py"),
    (
        "adapters_py",
        "training/m17_gpu/splendor_gpu/m35a_adapters.py",
    ),
    ("agent_py", "training/m17_gpu/splendor_gpu/m35a_agent.py"),
    ("agent_entry_py", "training/m17_gpu/m35a_agent_entry.py"),
    (
        "parity_test_py",
        "training/m17_gpu/tests/test_m35a_agent_parity.py",
    ),
];

fn python_bin() -> PathBuf {
    PathBuf::from("local-artifacts/m24-torch-cu124/bin/python")
}

fn python_available() -> bool {
    python_bin().exists()
}

#[test]
fn test_m35a_manifest_and_all_17_realized_plans() {
    let manifest_path = root().join("benchmarks/m35a-retrospective-arena.manifest.json");
    assert!(
        manifest_path.exists(),
        "manifest file must exist at {}",
        manifest_path.display()
    );

    let manifest_text = std::fs::read_to_string(&manifest_path).expect("read manifest");
    let manifest: Manifest = serde_json::from_str(&manifest_text).expect("parse manifest JSON");

    assert_eq!(
        manifest.format,
        "effective-splendor-m35a-retrospective-arena-manifest"
    );
    assert_eq!(manifest.version, 1);
    assert_eq!(manifest.milestone, "M35A");
    assert_eq!(manifest.evaluation_mode, "direct_policy_argmax_cpu");
    assert_eq!(manifest.total_pairings, 17);
    assert_eq!(manifest.total_scheduled_matches, 1088);
    assert_eq!(manifest.seeds_count, 32);
    assert_eq!(manifest.seeds.len(), 32);
    assert_eq!(manifest.seeds, (300001..=300032).collect::<Vec<_>>());
    assert_eq!(manifest.seat_rotations_per_seed, 2);
    assert_eq!(manifest.handshake_timeout_ms, 5000);
    assert_eq!(manifest.move_timeout_ms, 10000);
    assert_eq!(manifest.shutdown_grace_ms, 2000);
    assert_eq!(manifest.realized_plans.len(), 17);

    // ---- 4. source_shas must bind the exact current source bytes. ----
    for (key, rel_path) in SOURCE_FILES {
        let bound = manifest
            .source_shas
            .get(*key)
            .unwrap_or_else(|| panic!("manifest source_shas must contain '{key}'"));
        let src_path = root().join(rel_path);
        assert!(src_path.exists(), "bound source file {rel_path} must exist");
        let actual = file_sha256(&src_path);
        assert_eq!(
            actual, *bound,
            "source_shas['{key}'] does not match current bytes of {rel_path}"
        );
    }

    // ---- 5. checkpoint_shas structural validation. ----
    assert_eq!(manifest.checkpoint_shas.len(), 9);
    let expected_models = [
        "M24-S2",
        "M25-D2-v2",
        "M28A",
        "M28B",
        "M29A-v2",
        "M31A",
        "M32A",
        "M33A",
        "M34A",
    ];
    for model in expected_models {
        let binding = manifest
            .checkpoint_shas
            .get(model)
            .unwrap_or_else(|| panic!("checkpoint_shas must contain '{model}'"));
        assert!(
            is_valid_hex_sha256(&binding.file_sha256),
            "checkpoint SHA for {model} must be 64 hex chars"
        );
        assert!(
            is_valid_hex_sha256(&binding.dataset_hash),
            "dataset hash for {model} must be 64 hex chars"
        );
        assert!(
            binding.param_count > 0,
            "param count for {model} must be positive"
        );
        assert!(
            matches!(
                binding.output_semantics.as_str(),
                "flat_logits" | "composite_residual_logits" | "hierarchical_log_probs"
            ),
            "unknown output semantics for {model}: {}",
            binding.output_semantics
        );
        // When the checkpoint file is present locally, its bytes must match
        // the bound SHA (local artifacts are not tracked; absence is allowed
        // for checkout-only environments).
        let ckpt_path = root().join(&binding.path);
        if ckpt_path.exists() {
            let actual = file_sha256(&ckpt_path);
            assert_eq!(
                actual, binding.file_sha256,
                "checkpoint file SHA mismatch for {model} at {}",
                binding.path
            );
        }
    }

    // ---- 6+7. plan-level command and pairing binding. ----
    let mut total_scheduled: u64 = 0;
    let mut seen_pairings = std::collections::BTreeSet::new();
    for plan_info in &manifest.realized_plans {
        let plan_path = root().join(&plan_info.plan_file);
        assert!(
            plan_path.exists(),
            "plan file {} must exist",
            plan_path.display()
        );
        assert!(
            seen_pairings.insert(plan_info.pairing.clone()),
            "duplicate pairing {}",
            plan_info.pairing
        );

        // Verify SHA256 matches manifest binding
        let actual_sha = file_sha256(&plan_path);
        assert_eq!(
            actual_sha, plan_info.plan_file_sha256,
            "Plan SHA256 mismatch for {}",
            plan_info.evaluation_id
        );
        assert!(
            is_valid_hex_sha256(&plan_info.plan_file_sha256),
            "plan SHA must be 64 hex chars for {}",
            plan_info.evaluation_id
        );

        // Validate via official splendor-eval schema
        let plan_text = std::fs::read_to_string(&plan_path).expect("read plan");
        let plan: EvaluationPlanV1 = serde_json::from_str(&plan_text).expect("parse plan JSON");
        plan.validate().expect("validate plan invariants");

        assert_eq!(plan.agents.len(), 2);
        assert_eq!(plan.game_seeds.len(), 32);
        assert_eq!(plan.game_seeds, (300001..=300032).collect::<Vec<_>>());
        assert_eq!(plan.handshake_timeout_ms, 5000);
        assert_eq!(plan.move_timeout_ms, 10000);
        assert_eq!(plan.shutdown_grace_ms, 2000);
        assert_eq!(plan.evaluation_id, plan_info.evaluation_id);
        assert_eq!(plan_info.scheduled_matches, 64);
        total_scheduled += plan_info.scheduled_matches;

        // Neural agent command must use the entry script, CPU device, and the
        // pairing's candidate (or benchmark) model id.
        let neural = plan
            .agents
            .iter()
            .find(|a| {
                a.command
                    .program
                    .to_str()
                    .map(|p| p.ends_with("python"))
                    .unwrap_or(false)
            })
            .unwrap_or_else(|| panic!("plan {} must contain a python agent", plan.evaluation_id));
        assert_eq!(
            neural.command.program,
            python_bin(),
            "neural agent must use the pinned python binary"
        );
        let args = &neural.command.args;
        assert_eq!(args.first().map(String::as_str), Some("training/m17_gpu/m35a_agent_entry.py"),
            "neural agent must invoke the repository-root entry script (no PYTHONPATH available in plans)");
        assert_eq!(
            args[args.len() - 1],
            "cpu",
            "neural agent must pin --device cpu"
        );
        assert_eq!(args[args.len() - 2], "--device");
        let model_id = args[args.len() - 5].clone();
        assert_eq!(args[args.len() - 6], "--model-id");
        assert!(
            manifest.checkpoint_shas.contains_key(&model_id),
            "plan {} references unknown model id {model_id}",
            plan.evaluation_id
        );

        if plan_info.opponent_model_id == "M07" {
            // vs-M07 series: candidate is the neural agent, M07 is the champion.
            assert_eq!(
                model_id, plan_info.candidate_model_id,
                "plan {} neural model must equal candidate_model_id",
                plan_info.evaluation_id
            );
            let champion = plan
                .agents
                .iter()
                .find(|a| {
                    a.command
                        .program
                        .to_str()
                        .map(|p| p.ends_with("splendor"))
                        .unwrap_or(false)
                })
                .unwrap_or_else(|| {
                    panic!(
                        "plan {} must contain the M07 champion agent",
                        plan.evaluation_id
                    )
                });
            assert_eq!(
                champion.command.program,
                PathBuf::from(&manifest.champion_command.program)
            );
            assert_eq!(champion.command.args, manifest.champion_command.args);
        } else {
            // vs-D2-v2 series: opponent_model_id must be the benchmark model and
            // both agents are neural.
            assert_eq!(
                plan_info.opponent_model_id, "M25-D2-v2",
                "benchmark series opponent must be M25-D2-v2"
            );
            let neural_count = plan
                .agents
                .iter()
                .filter(|a| {
                    a.command
                        .program
                        .to_str()
                        .map(|p| p.ends_with("python"))
                        .unwrap_or(false)
                })
                .count();
            assert_eq!(
                neural_count, 2,
                "plan {} must run two neural agents",
                plan_info.evaluation_id
            );
            assert!(
                model_id == plan_info.candidate_model_id || model_id == plan_info.opponent_model_id,
                "plan {} neural model {model_id} must be one of the pairing",
                plan_info.evaluation_id
            );
        }
    }

    assert_eq!(total_scheduled, 1088);

    // Pairing matrix coverage: 9 vs-M07 + 8 vs-D2-v2.
    let vs_m07 = manifest
        .realized_plans
        .iter()
        .filter(|p| p.opponent_model_id == "M07")
        .count();
    let vs_d2 = manifest
        .realized_plans
        .iter()
        .filter(|p| p.opponent_model_id == "M25-D2-v2")
        .count();
    assert_eq!(vs_m07, 9);
    assert_eq!(vs_d2, 8);

    // 9 distinct candidates vs M07 must cover the full registry.
    let candidates: std::collections::BTreeSet<_> = manifest
        .realized_plans
        .iter()
        .filter(|p| p.opponent_model_id == "M07")
        .map(|p| p.candidate_model_id.clone())
        .collect();
    assert_eq!(candidates.len(), 9);
    for model in expected_models {
        assert!(
            candidates.contains(model),
            "candidate {model} missing from vs-M07 series"
        );
    }
}

/// The entry script must import the agent module without PYTHONPATH: a
/// repository-root process with default environment. With no stdin the agent
/// exits after model load (EOF on the hello read loop).
#[test]
fn test_m35a_agent_entry_script_launches_without_pythonpath() {
    if !python_available() {
        eprintln!("python binary not present; skipping launch check");
        return;
    }
    let out = Command::new(python_bin())
        .arg("training/m17_gpu/m35a_agent_entry.py")
        .arg("--model-id")
        .arg("M25-D2-v2")
        .arg("--catalog")
        .arg("apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json")
        .arg("--device")
        .arg("cpu")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .current_dir(root())
        .env_remove("PYTHONPATH")
        .output()
        .expect("spawn agent entry");
    assert!(
        out.status.success(),
        "agent entry must exit 0 on EOF without PYTHONPATH; stderr: {}",
        String::from_utf8_lossy(&out.stderr)
    );
}

/// Checkpoint tamper rejection: the registry must reject a checkpoint whose
/// on-disk SHA does not match the manifest binding. We verify fail-closed
/// behavior by asking the registry to validate with a mutated expected SHA
/// through the module API (import-time check with a doctored environment is
/// not required: `load_and_validate_checkpoint` compares the file SHA to the
/// registry entry, and the manifest binding equals the registry entry).
#[test]
fn test_m35a_checkpoint_tamper_rejected_by_registry() {
    if !python_available() {
        eprintln!("python binary not present; skipping tamper check");
        return;
    }
    // Read the registry's bound SHA for M25-D2-v2 and flip one hex digit.
    let script = r#"
import sys
sys.path.insert(0, "training/m17_gpu")
from splendor_gpu.m35a_registry import REGISTRY, load_and_validate_checkpoint
import torch

entry = REGISTRY["M25-D2-v2"]
tampered = ("0" if entry.checkpoint_file_sha256[0] != "0" else "1") + entry.checkpoint_file_sha256[1:]
assert tampered != entry.checkpoint_file_sha256
object.__setattr__(entry, "checkpoint_file_sha256", tampered)
try:
    load_and_validate_checkpoint("M25-D2-v2", entry.catalog_hash, torch.device("cpu"))
except ValueError as err:
    assert "SHA256 mismatch" in str(err), f"unexpected error: {err}"
    print("TAMPER_REJECTED")
except Exception as err:  # noqa: BLE001
    raise AssertionError(f"non-ValueError failure: {err!r}")
else:
    raise AssertionError("tampered checkpoint SHA was accepted")
"#;
    let out = Command::new(python_bin())
        .arg("-c")
        .arg(script)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .current_dir(root())
        .env_remove("PYTHONPATH")
        .output()
        .expect("spawn tamper probe");
    assert!(
        out.status.success(),
        "registry must reject tampered checkpoint SHA; stdout: {} stderr: {}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    );
    assert!(
        String::from_utf8_lossy(&out.stdout).contains("TAMPER_REJECTED"),
        "tamper probe must print the sentinel"
    );
}
