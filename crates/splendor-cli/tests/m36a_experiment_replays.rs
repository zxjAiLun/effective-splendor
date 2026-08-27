//! M36A Experiment Replay Library backend tests.
//!
//! Validates the read-only source registry contract against the real M35A
//! artifacts when present, plus a synthetic tamper/escape fixture tree under
//! a temp directory for fail-closed behavior that must hold everywhere.

use std::fs;
use std::path::{Path, PathBuf};

use splendor_cli::experiment_replays::{
    ExperimentReplayLibrary, ReplaySourceRegistry, REGISTRY_FORMAT, REGISTRY_VERSION,
};

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn registry_path() -> PathBuf {
    root().join("benchmarks/studio-replay-sources.registry.json")
}

fn m35a_artifacts_present() -> bool {
    root()
        .join("local-artifacts/m35a-retrospective-arena/runs")
        .is_dir()
}

fn load_library() -> ExperimentReplayLibrary {
    ExperimentReplayLibrary::load(&registry_path(), &root())
        .expect("the tracked replay source registry must load")
}

#[test]
fn registry_loads_and_declares_m35a() {
    let registry = ReplaySourceRegistry::load(&registry_path()).unwrap();
    assert_eq!(registry.format, REGISTRY_FORMAT);
    assert_eq!(registry.version, REGISTRY_VERSION);
    assert_eq!(registry.experiments.len(), 1);
    let experiment = &registry.experiments[0];
    assert_eq!(experiment.id, "m35a");
    assert_eq!(experiment.pairings.len(), 17);
}

#[test]
fn index_reports_17_pairings_1035_replays() {
    if !m35a_artifacts_present() {
        eprintln!("M35A artifacts not present; skipping");
        return;
    }
    let library = load_library();
    let index = library.index().unwrap();
    assert_eq!(index.experiments.len(), 1);
    let experiment = &index.experiments[0];
    assert_eq!(experiment.pairings.len(), 17);
    let valid: Vec<_> = experiment
        .pairings
        .iter()
        .filter(|p| p.status == "VALID")
        .collect();
    let prefix: Vec<_> = experiment
        .pairings
        .iter()
        .filter(|p| p.status == "EXCLUDED_PREFIX")
        .collect();
    assert_eq!(valid.len(), 15);
    assert_eq!(prefix.len(), 2);
    let total: u32 = experiment
        .pairings
        .iter()
        .map(|p| p.browsable_replays)
        .sum();
    assert_eq!(total, 1035, "960 formal + 75 excluded-prefix replays");
    let formal: u32 = valid.iter().map(|p| p.browsable_replays).sum();
    assert_eq!(formal, 960);
    let excluded: u32 = prefix.iter().map(|p| p.browsable_replays).sum();
    assert_eq!(excluded, 75);
}

#[test]
fn pairing_matches_classify_slots_and_bind_identity() {
    if !m35a_artifacts_present() {
        eprintln!("M35A artifacts not present; skipping");
        return;
    }
    let library = load_library();
    // A VALID pairing: all 64 slots valid, reports bound.
    let matches = library
        .pairing_matches("m35a", "m35a-m28a-vs-d2v2-v1")
        .unwrap();
    assert_eq!(matches.scheduled_matches, 64);
    assert_eq!(matches.matches.len(), 64);
    assert!(matches
        .matches
        .iter()
        .all(|m| m.availability == splendor_cli::experiment_replays::MatchAvailability::Valid));
    for (index, slot) in matches.matches.iter().enumerate() {
        assert_eq!(
            slot.game_id,
            format!("m35a-m28a-vs-d2v2-v1-s{:06}-r{:02}", index / 2, index % 2)
        );
        assert_eq!(slot.seed_index as usize, index / 2);
        assert_eq!(slot.rotation as usize, index % 2);
        // Seat rotation: r00 -> candidate seat 0; r01 -> candidate seat 1.
        assert_eq!(slot.candidate_seat, Some((index % 2) as u8));
        assert_eq!(slot.opponent_seat, Some((1 - index % 2) as u8));
        // M35A frozen seed schedule.
        assert_eq!(slot.seed, Some(300_001 + (index / 2) as u64));
        // Completed match data present.
        assert!(slot.completed_plies.unwrap() > 0);
        assert!(slot.scores.is_some());
        assert!(slot.winner_seats.is_some());
        assert!(slot.replay_document_hash.is_some());
        let replay = serde_json::from_slice::<serde_json::Value>(
            &fs::read(
                root().join(format!(
                    "local-artifacts/m35a-retrospective-arena/runs/m35a-m28a-vs-d2v2-v1/matches/match-{index:06}.replay.json"
                )),
            )
            .unwrap(),
        )
        .unwrap();
        let steps = replay["steps"].as_array().unwrap();
        assert_eq!(steps.len() as u32, slot.completed_plies.unwrap());
        // Ply 0 is always acted by seat 0.
        assert_eq!(steps[0]["actor"].as_u64().unwrap() as u8, 0);
        // Seat-model identity: the report's per-seat agent_version must match
        // the rotation-derived candidate/opponent seats.
        let report = serde_json::from_slice::<serde_json::Value>(
            &fs::read(
                root().join(format!(
                    "local-artifacts/m35a-retrospective-arena/runs/m35a-m28a-vs-d2v2-v1/matches/match-{index:06}.report.json"
                )),
            )
            .unwrap(),
        )
        .unwrap();
        for agent in report["agents"].as_array().unwrap() {
            let seat = agent["seat"].as_u64().unwrap() as u8;
            let version = agent["agent_version"].as_str().unwrap();
            let expected = if seat == slot.candidate_seat.unwrap() {
                "M28A"
            } else {
                "M25-D2-v2"
            };
            assert_eq!(
                version, expected,
                "seat {seat} model mismatch at match {index}"
            );
        }
    }

    // The M29A-v2 EXCLUDED_PREFIX pairing: 60 valid-prefix + 1 nontermination
    // + 3 not-started.
    let prefix = library
        .pairing_matches("m35a", "m35a-m29a-v2-vs-m07-v1")
        .unwrap();
    assert_eq!(prefix.scheduled_matches, 64);
    let valid_count = prefix
        .matches
        .iter()
        .filter(|m| {
            m.availability == splendor_cli::experiment_replays::MatchAvailability::ExcludedPrefix
        })
        .count();
    let nonterm_count = prefix
        .matches
        .iter()
        .filter(|m| {
            m.availability == splendor_cli::experiment_replays::MatchAvailability::Nontermination
        })
        .count();
    let not_started_count = prefix
        .matches
        .iter()
        .filter(|m| {
            m.availability == splendor_cli::experiment_replays::MatchAvailability::NotStarted
        })
        .count();
    assert_eq!(valid_count, 60);
    assert_eq!(nonterm_count, 1);
    assert_eq!(not_started_count, 3);
    let failure_slot = prefix
        .matches
        .iter()
        .find(|m| {
            m.availability == splendor_cli::experiment_replays::MatchAvailability::Nontermination
        })
        .unwrap();
    assert_eq!(failure_slot.match_index, 60);
    assert_eq!(failure_slot.game_id, "m35a-m29a-v2-vs-m07-v1-s000030-r00");

    // M31A prefix: 15 + 1 + 48.
    let m31a = library
        .pairing_matches("m35a", "m35a-m31a-vs-m07-v1")
        .unwrap();
    let counts = (
        m31a.matches
            .iter()
            .filter(|m| {
                m.availability
                    == splendor_cli::experiment_replays::MatchAvailability::ExcludedPrefix
            })
            .count(),
        m31a.matches
            .iter()
            .filter(|m| {
                m.availability
                    == splendor_cli::experiment_replays::MatchAvailability::Nontermination
            })
            .count(),
        m31a.matches
            .iter()
            .filter(|m| {
                m.availability == splendor_cli::experiment_replays::MatchAvailability::NotStarted
            })
            .count(),
    );
    assert_eq!(counts, (15, 1, 48));
}

#[test]
fn bundle_reverifies_and_projects_player_view() {
    if !m35a_artifacts_present() {
        eprintln!("M35A artifacts not present; skipping");
        return;
    }
    let library = load_library();
    let bundle = library
        .bundle("m35a", "m35a-m28a-vs-d2v2-v1", 0)
        .expect("bundle for a VALID match");
    assert_eq!(
        bundle.availability,
        splendor_cli::experiment_replays::MatchAvailability::Valid
    );
    assert_eq!(bundle.game_id, "m35a-m28a-vs-d2v2-v1-s000000-r00");
    assert_eq!(bundle.candidate_model_id, "M28A");
    assert_eq!(bundle.opponent_model_id, "M25-D2-v2");
    assert!(!bundle.replay_document_hash.is_empty());
    assert!(bundle.result.is_some());
    assert!(!bundle.frames.is_empty());
    for (index, frame) in bundle.frames.iter().enumerate() {
        assert_eq!(frame.ply as usize, index);
        // Player view must be projected for the actor.
        assert_eq!(frame.player_view.viewer, frame.actor);
        // Actor model labeling follows seat rotation (candidate at seat 0).
        if frame.actor.0 == 0 {
            assert_eq!(frame.actor_model, "M28A");
            assert!(frame.candidate_acted);
        } else {
            assert_eq!(frame.actor_model, "M25-D2-v2");
            assert!(!frame.candidate_acted);
        }
        // Legal actions are non-empty and include the recorded action.
        assert!(!frame.legal_actions.is_empty());
        assert!(frame
            .legal_actions
            .iter()
            .any(|action| *action == frame.recorded_action));
        // Referee reveal carries deck order for the confirm-gated view.
        assert_eq!(frame.referee_reveal.decks.len(), 3);
    }

    // Excluded-prefix bundle also loads but is marked NOT_SCORED.
    let prefix_bundle = library
        .bundle("m35a", "m35a-m29a-v2-vs-m07-v1", 0)
        .expect("prefix bundle");
    assert_eq!(
        prefix_bundle.availability,
        splendor_cli::experiment_replays::MatchAvailability::ExcludedPrefix
    );

    // The nontermination slot itself must not serve a bundle.
    let error = library
        .bundle("m35a", "m35a-m29a-v2-vs-m07-v1", 60)
        .unwrap_err();
    assert!(error.contains("NONTERMINATION"), "error was: {error}");
    // Nor a not-started slot.
    let error = library
        .bundle("m35a", "m35a-m29a-v2-vs-m07-v1", 61)
        .unwrap_err();
    assert!(error.contains("NOT_STARTED"), "error was: {error}");
}

#[test]
fn unknown_ids_and_out_of_range_indexes_fail_closed() {
    if !m35a_artifacts_present() {
        eprintln!("M35A artifacts not present; skipping");
        return;
    }
    let library = load_library();
    assert!(library
        .pairing_matches("nope", "m35a-m28a-vs-d2v2-v1")
        .is_err());
    assert!(library
        .pairing_matches("m35a", "m35a-does-not-exist")
        .is_err());
    // Identifiers with path separators must be rejected before any fs access.
    assert!(library.pairing_matches("m35a", "../../etc").is_err());
    assert!(library
        .pairing_matches("..%2F..", "m35a-m28a-vs-d2v2-v1")
        .is_err());
    assert!(library.bundle("m35a", "m35a-m28a-vs-d2v2-v1", 64).is_err());
    assert!(library
        .bundle("m35a", "m35a-m28a-vs-d2v2-v1", u32::MAX)
        .is_err());
}

// ---------------------------------------------------------------------------
// Synthetic fixtures: tamper + traversal rejection must hold regardless of
// the local M35A artifacts.
// ---------------------------------------------------------------------------

fn temp_tree(tag: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("m36a-test-{tag}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).unwrap();
    dir
}

fn sha256_of(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    hex::encode(hasher.finalize())
}

fn write_synthetic_experiment(base: &Path) -> PathBuf {
    // Build a minimal but legitimate run directory using a real engine replay.
    let run_dir = base.join("local-artifacts/m36a-synth/runs/synth-pairing-v1/matches");
    fs::create_dir_all(&run_dir).unwrap();
    // Generate a genuine short replay: uniform-random legal play.
    let (_state, replay) = splendor_replay::record_random_game(2, 7, 11).unwrap();
    let replay_json = serde_json::to_vec(&replay).unwrap();
    fs::write(run_dir.join("match-000000.replay.json"), &replay_json).unwrap();
    // Report with the true final hash, result, and the REAL M35A agent
    // identities (candidate M28A at seat 0, D2-v2 at seat 1).
    let report = serde_json::json!({
        "format": "effective-splendor-arena-report",
        "game_id": "synth-pairing-v1-s000000-r00",
        "agents": [
            {"seat": 0, "agent_name": "effective-splendor-m35a-direct-agent-v1", "agent_version": "M28A"},
            {"seat": 1, "agent_name": "effective-splendor-m35a-direct-agent-v1", "agent_version": "M25-D2-v2"}
        ],
        "outcome": {
            "status": "completed",
            "result": {
                "scores": replay.result.scores,
                "ranks": replay.result.ranks,
                "winners": replay.result.winners,
                "reason": replay.result.reason
            },
            "completed_plies": replay.steps.len() as u32,
            "replay_final_hash": replay.final_state_hash.as_str()
        }
    });
    fs::write(
        run_dir.join("match-000000.report.json"),
        serde_json::to_vec(&report).unwrap(),
    )
    .unwrap();
    // Tracked result + eval report with REAL, verified SHA-256 bindings.
    fs::create_dir_all(base.join("benchmarks")).unwrap();
    let tracked_path = base.join("benchmarks/synth.json");
    let tracked_bytes = br#"{"synthetic":"tracked-result"}"#;
    fs::write(&tracked_path, tracked_bytes).unwrap();
    let eval_report = serde_json::json!({
        "format": "effective-splendor-evaluation-report",
        "records": [{"match_index": 0, "outcome": {"status": "completed"}}]
    });
    let eval_path = base.join("local-artifacts/m36a-synth/runs/synth-pairing-v1/eval-report.json");
    fs::write(&eval_path, serde_json::to_vec_pretty(&eval_report).unwrap()).unwrap();
    // Registry pointing at the synthetic tree with real hashes.
    let registry = serde_json::json!({
        "format": REGISTRY_FORMAT,
        "version": REGISTRY_VERSION,
        "experiments": [{
            "id": "synth",
            "display_name": "Synthetic",
            "description": "test",
            "tracked_result": "benchmarks/synth.json",
            "tracked_result_sha256": sha256_of(tracked_bytes),
            "runs_root": "local-artifacts/m36a-synth/runs",
            "pairings": [{
                "evaluation_id": "synth-pairing-v1",
                "candidate_model_id": "M28A",
                "opponent_model_id": "M25-D2-v2",
                "status": "VALID",
                "scheduled_matches": 1,
                "run_dir": "local-artifacts/m36a-synth/runs/synth-pairing-v1",
                "eval_report_sha256": sha256_of(&fs::read(&eval_path).unwrap())
            }]
        }]
    });
    let registry_path = base.join("synth-registry.json");
    fs::write(&registry_path, serde_json::to_vec(&registry).unwrap()).unwrap();
    registry_path
}

#[test]
fn synthetic_bundle_serves_then_tampered_replay_is_rejected() {
    let base = temp_tree("tamper");
    let registry_path = write_synthetic_experiment(&base);
    let library = ExperimentReplayLibrary::load(&registry_path, &base).unwrap();
    let bundle = library.bundle("synth", "synth-pairing-v1", 0).unwrap();
    assert!(!bundle.frames.is_empty());
    assert_eq!(bundle.game_id, "synth-pairing-v1-s000000-r00");

    // Tamper: flip one action in the replay JSON (breaks re-verification).
    let replay_path = base
        .join("local-artifacts/m36a-synth/runs/synth-pairing-v1/matches/match-000000.replay.json");
    let mut value: serde_json::Value =
        serde_json::from_slice(&fs::read(&replay_path).unwrap()).unwrap();
    let steps = value["steps"].as_array_mut().unwrap();
    steps[0]["ply"] = serde_json::json!(99);
    fs::write(&replay_path, serde_json::to_vec(&value).unwrap()).unwrap();
    let error = library.bundle("synth", "synth-pairing-v1", 0).unwrap_err();
    assert!(!error.is_empty());
    assert!(error.contains("ply") || error.contains("actor") || error.contains("hash"));

    // Tamper: report hash no longer matches the replay.
    let mut value: serde_json::Value =
        serde_json::from_slice(&fs::read(&replay_path).unwrap()).unwrap();
    let steps = value["steps"].as_array_mut().unwrap();
    steps[0]["ply"] = serde_json::json!(0);
    fs::write(&replay_path, serde_json::to_vec(&value).unwrap()).unwrap();
    let report_path = base
        .join("local-artifacts/m36a-synth/runs/synth-pairing-v1/matches/match-000000.report.json");
    let mut report: serde_json::Value =
        serde_json::from_slice(&fs::read(&report_path).unwrap()).unwrap();
    report["outcome"]["replay_final_hash"] = serde_json::json!("f".repeat(64));
    fs::write(&report_path, serde_json::to_vec(&report).unwrap()).unwrap();
    let error = library.bundle("synth", "synth-pairing-v1", 0).unwrap_err();
    assert!(error.contains("final hash"), "error was: {error}");

    let _ = fs::remove_dir_all(&base);
}

#[test]
fn registry_rejects_escaping_run_dirs_and_bad_statuses() {
    let base = temp_tree("escape");
    let run_root = base.join("local-artifacts/m36a-escape/runs");
    fs::create_dir_all(run_root).unwrap();

    let escaping = serde_json::json!({
        "format": REGISTRY_FORMAT,
        "version": REGISTRY_VERSION,
        "experiments": [{
            "id": "escape",
            "display_name": "E",
            "description": "d",
            "tracked_result": "t",
            "tracked_result_sha256": "0".repeat(64),
            "runs_root": "local-artifacts/m36a-escape/runs",
            "pairings": [{
                "evaluation_id": "p1",
                "candidate_model_id": "A",
                "opponent_model_id": "B",
                "status": "VALID",
                "scheduled_matches": 1,
                "run_dir": "local-artifacts/elsewhere/runs/p1",
                "eval_report_sha256": "1".repeat(64)
            }]
        }]
    });
    let path = base.join("escape-registry.json");
    fs::write(&path, serde_json::to_vec(&escaping).unwrap()).unwrap();
    let error = ReplaySourceRegistry::load(&path).unwrap_err();
    assert!(error.contains("escapes"), "error was: {error}");

    // run_dir outside local-artifacts entirely.
    let outside = serde_json::json!({
        "format": REGISTRY_FORMAT,
        "version": REGISTRY_VERSION,
        "experiments": [{
            "id": "outside",
            "display_name": "O",
            "description": "d",
            "tracked_result": "t",
            "tracked_result_sha256": "0".repeat(64),
            "runs_root": "local-artifacts/m36a-escape/runs",
            "pairings": [{
                "evaluation_id": "p1",
                "candidate_model_id": "A",
                "opponent_model_id": "B",
                "status": "VALID",
                "scheduled_matches": 1,
                "run_dir": "/etc",
                "eval_report_sha256": "1".repeat(64)
            }]
        }]
    });
    let path = base.join("outside-registry.json");
    fs::write(&path, serde_json::to_vec(&outside).unwrap()).unwrap();
    let error = ReplaySourceRegistry::load(&path).unwrap_err();
    assert!(error.contains("local-artifacts"), "error was: {error}");

    // Unknown status string.
    let bad_status = serde_json::json!({
        "format": REGISTRY_FORMAT,
        "version": REGISTRY_VERSION,
        "experiments": [{
            "id": "bad",
            "display_name": "B",
            "description": "d",
            "tracked_result": "t",
            "tracked_result_sha256": "0".repeat(64),
            "runs_root": "local-artifacts/m36a-escape/runs",
            "pairings": [{
                "evaluation_id": "p1",
                "candidate_model_id": "A",
                "opponent_model_id": "B",
                "status": "MAYBE",
                "scheduled_matches": 1,
                "run_dir": "local-artifacts/m36a-escape/runs/p1"
            }]
        }]
    });
    let path = base.join("bad-status-registry.json");
    fs::write(&path, serde_json::to_vec(&bad_status).unwrap()).unwrap();
    let error = ReplaySourceRegistry::load(&path).unwrap_err();
    assert!(error.contains("unsupported status"), "error was: {error}");

    let _ = fs::remove_dir_all(&base);
}

// ---------------------------------------------------------------------------
// Review repair: fail-closed provenance, agent lineup, symlink escape.
// ---------------------------------------------------------------------------

#[test]
fn library_load_rejects_wrong_tracked_result_sha() {
    let base = temp_tree("trackedsha");
    let registry_path = write_synthetic_experiment(&base);
    // Tamper with the tracked result bytes after the registry was written.
    let tracked_path = base.join("benchmarks/synth.json");
    fs::write(&tracked_path, br#"{"synthetic":"tampered"}"#).unwrap();
    let error = ExperimentReplayLibrary::load(&registry_path, &base).unwrap_err();
    assert!(
        error.contains("tracked result SHA mismatch"),
        "error was: {error}"
    );
    let _ = fs::remove_dir_all(&base);
}

#[test]
fn library_load_rejects_wrong_eval_report_sha() {
    let base = temp_tree("evalsha");
    let registry_path = write_synthetic_experiment(&base);
    // Tamper with the eval report after the registry was written.
    let eval_path = base.join("local-artifacts/m36a-synth/runs/synth-pairing-v1/eval-report.json");
    fs::write(&eval_path, br#"{"tampered":true}"#).unwrap();
    let error = ExperimentReplayLibrary::load(&registry_path, &base).unwrap_err();
    assert!(
        error.contains("eval report SHA mismatch"),
        "error was: {error}"
    );
    let _ = fs::remove_dir_all(&base);
}

#[test]
fn library_load_rejects_fake_all_zero_hashes() {
    let base = temp_tree("fakehash");
    let registry_path = write_synthetic_experiment(&base);
    // Registry with the old-style fake hashes must now fail at load.
    let mut registry: serde_json::Value =
        serde_json::from_slice(&fs::read(&registry_path).unwrap()).unwrap();
    registry["experiments"][0]["tracked_result_sha256"] = serde_json::json!("0".repeat(64));
    registry["experiments"][0]["pairings"][0]["eval_report_sha256"] =
        serde_json::json!("1".repeat(64));
    fs::write(&registry_path, serde_json::to_vec(&registry).unwrap()).unwrap();
    let error = ExperimentReplayLibrary::load(&registry_path, &base).unwrap_err();
    assert!(
        error.contains("tracked result SHA mismatch") || error.contains("eval report SHA mismatch"),
        "error was: {error}"
    );
    let _ = fs::remove_dir_all(&base);
}

#[test]
fn library_load_rejects_missing_tracked_result_and_eval_report() {
    let base = temp_tree("missingfiles");
    let registry_path = write_synthetic_experiment(&base);
    fs::remove_file(base.join("benchmarks/synth.json")).unwrap();
    let error = ExperimentReplayLibrary::load(&registry_path, &base).unwrap_err();
    assert!(
        error.contains("cannot read tracked result"),
        "error was: {error}"
    );

    let base2 = temp_tree("missingeval");
    let registry_path2 = write_synthetic_experiment(&base2);
    fs::remove_file(
        base2.join("local-artifacts/m36a-synth/runs/synth-pairing-v1/eval-report.json"),
    )
    .unwrap();
    let error = ExperimentReplayLibrary::load(&registry_path2, &base2).unwrap_err();
    assert!(
        error.contains("cannot read eval report"),
        "error was: {error}"
    );
    let _ = fs::remove_dir_all(&base);
    let _ = fs::remove_dir_all(&base2);
}

#[test]
fn wrong_agent_lineup_is_rejected_for_matches_and_bundles() {
    let base = temp_tree("lineup");
    let registry_path = write_synthetic_experiment(&base);
    let library = ExperimentReplayLibrary::load(&registry_path, &base).unwrap();

    // Swap the two agents' versions in the match report (wrong lineup).
    let report_path = base
        .join("local-artifacts/m36a-synth/runs/synth-pairing-v1/matches/match-000000.report.json");
    let mut report: serde_json::Value =
        serde_json::from_slice(&fs::read(&report_path).unwrap()).unwrap();
    report["agents"][0]["agent_version"] = serde_json::json!("M25-D2-v2");
    report["agents"][1]["agent_version"] = serde_json::json!("M28A");
    fs::write(&report_path, serde_json::to_vec(&report).unwrap()).unwrap();

    let error = library
        .pairing_matches("synth", "synth-pairing-v1")
        .unwrap_err();
    assert!(
        error.contains("agent lineup mismatch"),
        "error was: {error}"
    );
    let error = library.bundle("synth", "synth-pairing-v1", 0).unwrap_err();
    assert!(
        error.contains("agent lineup mismatch"),
        "error was: {error}"
    );

    // Unknown agent name is also a lineup violation.
    let mut report: serde_json::Value =
        serde_json::from_slice(&fs::read(&report_path).unwrap()).unwrap();
    report["agents"][0]["agent_version"] = serde_json::json!("M28A");
    report["agents"][1]["agent_version"] = serde_json::json!("M25-D2-v2");
    report["agents"][0]["agent_name"] = serde_json::json!("some-other-agent");
    fs::write(&report_path, serde_json::to_vec(&report).unwrap()).unwrap();
    let error = library.bundle("synth", "synth-pairing-v1", 0).unwrap_err();
    assert!(
        error.contains("agent lineup mismatch"),
        "error was: {error}"
    );

    let _ = fs::remove_dir_all(&base);
}

#[test]
fn symlink_escape_from_run_dir_is_rejected_at_load_and_access() {
    let base = temp_tree("symlink");
    let registry_path = write_synthetic_experiment(&base);
    // Replace the run directory with a symlink pointing OUTSIDE
    // local-artifacts (but keep a real, valid tree behind it so only the
    // escape is wrong).
    let real_outside = base.join("outside-tree/synth-pairing-v1");
    fs::create_dir_all(&real_outside).unwrap();
    let run_dir = base.join("local-artifacts/m36a-synth/runs/synth-pairing-v1");
    let stash = base.join("local-artifacts/m36a-synth/runs/stashed-real");
    fs::rename(&run_dir, &stash).unwrap();
    #[cfg(unix)]
    std::os::unix::fs::symlink(&real_outside, &run_dir).unwrap();

    // Load-time containment check rejects the symlinked run dir.
    let error = ExperimentReplayLibrary::load(&registry_path, &base).unwrap_err();
    assert!(
        error.contains("resolves outside local-artifacts"),
        "error was: {error}"
    );

    // Even a registry that passes structural validation cannot serve data
    // through a symlinked run dir: build a library from a stashed,
    // non-symlinked copy and then swap in the symlink before access.
    #[cfg(unix)]
    {
        let _ = fs::remove_file(&run_dir);
        fs::rename(&stash, &run_dir).unwrap();
        let library = ExperimentReplayLibrary::load(&registry_path, &base).unwrap();
        // Now replace with a symlink mid-flight.
        let _ = fs::rename(&run_dir, &stash);
        std::os::unix::fs::symlink(&real_outside, &run_dir).unwrap();
        let error = library
            .pairing_matches("synth", "synth-pairing-v1")
            .unwrap_err();
        assert!(
            error.contains("resolves outside local-artifacts"),
            "error was: {error}"
        );
        let error = library.bundle("synth", "synth-pairing-v1", 0).unwrap_err();
        assert!(
            error.contains("resolves outside local-artifacts"),
            "error was: {error}"
        );
    }
    let _ = fs::remove_dir_all(&base);
}

#[test]
fn symlinked_run_dir_inside_local_artifacts_still_serves() {
    // A symlink that stays INSIDE local-artifacts is legitimate.
    let base = temp_tree("symlink-ok");
    let registry_path = write_synthetic_experiment(&base);
    let run_dir = base.join("local-artifacts/m36a-synth/runs/synth-pairing-v1");
    let alias = base.join("local-artifacts/m36a-synth/runs/alias-target");
    fs::rename(&run_dir, &alias).unwrap();
    #[cfg(unix)]
    std::os::unix::fs::symlink(&alias, &run_dir).unwrap();
    // Rebind the eval report SHA (same bytes, new path) and reload.
    let eval_path = alias.join("eval-report.json");
    let mut registry: serde_json::Value =
        serde_json::from_slice(&fs::read(&registry_path).unwrap()).unwrap();
    registry["experiments"][0]["pairings"][0]["eval_report_sha256"] =
        serde_json::json!(sha256_of(&fs::read(&eval_path).unwrap()));
    fs::write(&registry_path, serde_json::to_vec(&registry).unwrap()).unwrap();
    let library = ExperimentReplayLibrary::load(&registry_path, &base)
        .expect("inside-artifacts symlink must be accepted");
    let bundle = library.bundle("synth", "synth-pairing-v1", 0).unwrap();
    assert!(!bundle.frames.is_empty());
    let _ = fs::remove_dir_all(&base);
}

#[test]
fn real_m35a_library_loads_with_verified_provenance() {
    if !m35a_artifacts_present() {
        eprintln!("M35A artifacts not present; skipping");
        return;
    }
    // The tracked registry must load fail-closed: this now verifies the
    // tracked result SHA, all 15 eval-report SHAs, and symlink containment.
    let _library = load_library();
}

// ---------------------------------------------------------------------------
// Review repair 2: duplicate seats, file-level symlink escape, deep link.
// ---------------------------------------------------------------------------

#[test]
fn duplicate_seat_agent_records_are_rejected() {
    let base = temp_tree("dupseat");
    let registry_path = write_synthetic_experiment(&base);
    let library = ExperimentReplayLibrary::load(&registry_path, &base).unwrap();

    // Two identical candidate-seat records: seat set is {0, 0}, not {0, 1}.
    let report_path = base
        .join("local-artifacts/m36a-synth/runs/synth-pairing-v1/matches/match-000000.report.json");
    let mut report: serde_json::Value =
        serde_json::from_slice(&fs::read(&report_path).unwrap()).unwrap();
    report["agents"] = serde_json::json!([
        {"seat": 0, "agent_name": "effective-splendor-m35a-direct-agent-v1", "agent_version": "M28A"},
        {"seat": 0, "agent_name": "effective-splendor-m35a-direct-agent-v1", "agent_version": "M28A"}
    ]);
    fs::write(&report_path, serde_json::to_vec(&report).unwrap()).unwrap();
    let error = library.bundle("synth", "synth-pairing-v1", 0).unwrap_err();
    assert!(
        error.contains("does not cover both seats") || error.contains("duplicate seat"),
        "error was: {error}"
    );
    let error = library
        .pairing_matches("synth", "synth-pairing-v1")
        .unwrap_err();
    assert!(
        error.contains("does not cover both seats") || error.contains("duplicate seat"),
        "error was: {error}"
    );

    // Two identical opponent-seat records: seat set is {1, 1}.
    let mut report: serde_json::Value =
        serde_json::from_slice(&fs::read(&report_path).unwrap()).unwrap();
    report["agents"] = serde_json::json!([
        {"seat": 1, "agent_name": "effective-splendor-m35a-direct-agent-v1", "agent_version": "M25-D2-v2"},
        {"seat": 1, "agent_name": "effective-splendor-m35a-direct-agent-v1", "agent_version": "M25-D2-v2"}
    ]);
    fs::write(&report_path, serde_json::to_vec(&report).unwrap()).unwrap();
    let error = library.bundle("synth", "synth-pairing-v1", 0).unwrap_err();
    assert!(
        error.contains("does not cover both seats") || error.contains("duplicate seat"),
        "error was: {error}"
    );

    // Out-of-range seat (2) with correct identities elsewhere.
    let mut report: serde_json::Value =
        serde_json::from_slice(&fs::read(&report_path).unwrap()).unwrap();
    report["agents"] = serde_json::json!([
        {"seat": 0, "agent_name": "effective-splendor-m35a-direct-agent-v1", "agent_version": "M28A"},
        {"seat": 2, "agent_name": "effective-splendor-m35a-direct-agent-v1", "agent_version": "M25-D2-v2"}
    ]);
    fs::write(&report_path, serde_json::to_vec(&report).unwrap()).unwrap();
    let error = library.bundle("synth", "synth-pairing-v1", 0).unwrap_err();
    assert!(
        error.contains("does not cover both seats") || error.contains("out-of-range"),
        "error was: {error}"
    );

    let _ = fs::remove_dir_all(&base);
}

#[test]
fn file_level_symlink_escape_of_report_and_replay_is_rejected() {
    let base = temp_tree("filesymlink");
    let registry_path = write_synthetic_experiment(&base);
    let library = ExperimentReplayLibrary::load(&registry_path, &base).unwrap();
    let run_dir = base.join("local-artifacts/m36a-synth/runs/synth-pairing-v1");

    // Replace the match REPORT with a symlink to a copy outside the run dir
    // (but still inside local-artifacts is not possible for "escape", so
    // point it fully outside).
    let report_path = run_dir.join("matches/match-000000.report.json");
    let outside_dir = base.join("outside");
    fs::create_dir_all(&outside_dir).unwrap();
    let outside_report = outside_dir.join("stolen-report.json");
    fs::rename(&report_path, &outside_report).unwrap();
    #[cfg(unix)]
    std::os::unix::fs::symlink(&outside_report, &report_path).unwrap();

    // The library was loaded BEFORE the swap: mid-flight access must reject.
    let error = library.bundle("synth", "synth-pairing-v1", 0).unwrap_err();
    assert!(
        error.contains("resolves outside its run directory"),
        "report-symlink error was: {error}"
    );
    let error = library
        .pairing_matches("synth", "synth-pairing-v1")
        .unwrap_err();
    assert!(
        error.contains("resolves outside its run directory"),
        "report-symlink error was: {error}"
    );

    // Restore the report and repeat with the REPLAY file symlinked out.
    fs::remove_file(&report_path).unwrap();
    fs::rename(&outside_report, &report_path).unwrap();
    let replay_path = run_dir.join("matches/match-000000.replay.json");
    let outside_replay = outside_dir.join("stolen-replay.json");
    fs::rename(&replay_path, &outside_replay).unwrap();
    #[cfg(unix)]
    std::os::unix::fs::symlink(&outside_replay, &replay_path).unwrap();
    let error = library.bundle("synth", "synth-pairing-v1", 0).unwrap_err();
    assert!(
        error.contains("resolves outside its run directory"),
        "replay-symlink error was: {error}"
    );

    // Restore and confirm the bundle serves again.
    fs::remove_file(&replay_path).unwrap();
    fs::rename(&outside_replay, &replay_path).unwrap();
    let bundle = library.bundle("synth", "synth-pairing-v1", 0).unwrap();
    assert!(!bundle.frames.is_empty());

    let _ = fs::remove_dir_all(&base);
}

#[test]
fn file_level_symlink_inside_run_dir_still_serves() {
    let base = temp_tree("filesymlink-ok");
    let registry_path = write_synthetic_experiment(&base);
    let library = ExperimentReplayLibrary::load(&registry_path, &base).unwrap();
    let run_dir = base.join("local-artifacts/m36a-synth/runs/synth-pairing-v1");

    // Alias the report via a symlink that stays INSIDE the run dir.
    let report_path = run_dir.join("matches/match-000000.report.json");
    let alias = run_dir.join("matches/alias-report.json");
    fs::rename(&report_path, &alias).unwrap();
    #[cfg(unix)]
    std::os::unix::fs::symlink(&alias, &report_path).unwrap();
    let bundle = library.bundle("synth", "synth-pairing-v1", 0).unwrap();
    assert!(!bundle.frames.is_empty());

    let _ = fs::remove_dir_all(&base);
}
