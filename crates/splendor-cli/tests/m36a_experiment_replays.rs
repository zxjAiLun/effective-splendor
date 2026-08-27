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

fn write_synthetic_experiment(base: &Path) -> PathBuf {
    // Build a minimal but legitimate run directory using a real engine replay.
    let run_dir = base.join("local-artifacts/m36a-synth/runs/synth-pairing-v1/matches");
    fs::create_dir_all(&run_dir).unwrap();
    // Generate a genuine short replay: uniform-random legal play.
    let (_state, replay) = splendor_replay::record_random_game(2, 7, 11).unwrap();
    let replay_json = serde_json::to_vec(&replay).unwrap();
    fs::write(run_dir.join("match-000000.replay.json"), &replay_json).unwrap();
    // Report with the true final hash and result.
    let report = serde_json::json!({
        "format": "effective-splendor-arena-report",
        "game_id": "synth-pairing-v1-s000000-r00",
        "agents": [
            {"seat": 0, "agent_name": "synthetic-candidate", "agent_version": "1"},
            {"seat": 1, "agent_name": "synthetic-opponent", "agent_version": "1"}
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
    // Registry pointing at the synthetic tree.
    let registry = serde_json::json!({
        "format": REGISTRY_FORMAT,
        "version": REGISTRY_VERSION,
        "experiments": [{
            "id": "synth",
            "display_name": "Synthetic",
            "description": "test",
            "tracked_result": "benchmarks/synth.json",
            "tracked_result_sha256": "0".repeat(64),
            "runs_root": "local-artifacts/m36a-synth/runs",
            "pairings": [{
                "evaluation_id": "synth-pairing-v1",
                "candidate_model_id": "SYN-A",
                "opponent_model_id": "SYN-B",
                "status": "VALID",
                "scheduled_matches": 1,
                "run_dir": "local-artifacts/m36a-synth/runs/synth-pairing-v1",
                "eval_report_sha256": "1".repeat(64)
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
