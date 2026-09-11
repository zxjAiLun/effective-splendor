use sha2::{Digest, Sha256};
use splendor_arena::{seed_commitment_v1, AgentIdentity, ArenaOutcomeV1, ArenaReportV1, PlayerId};
use splendor_core::{ruleset_fingerprint, GameConfig, Ruleset};
use splendor_replay::{record_random_game, ReplayV1};
use splendor_studio_league::{
    arena_report_to_match_record, build_replay_content_index, resolve_arena_report_replay,
    HistoricalReplayResolutionV1, MatchStatus, ReplayVerification, StudioLeagueError,
};
use std::path::PathBuf;

fn temp_dir(label: &str) -> PathBuf {
    std::env::temp_dir().join(format!(
        "splendor-studio-league-report-resolver-{label}-{}",
        std::process::id()
    ))
}

fn completed_report(replay: &ReplayV1) -> ArenaReportV1 {
    let ruleset = Ruleset::base_v1();
    let fingerprint = ruleset_fingerprint(&ruleset);
    let result = splendor_core::FullState::new(GameConfig {
        player_count: replay.player_count,
        seed: replay.seed,
        ruleset: ruleset.clone(),
    });
    assert!(result.is_ok());
    ArenaReportV1::new(
        "historical-game",
        replay.engine_version.clone(),
        "1",
        "base_v1",
        fingerprint.as_str(),
        replay.player_count,
        seed_commitment_v1(
            "historical-game",
            replay.player_count,
            replay.seed,
            &fingerprint,
        ),
        vec![
            AgentIdentity {
                seat: PlayerId(0),
                agent_name: Some("engine-a".into()),
                agent_version: Some("1".into()),
            },
            AgentIdentity {
                seat: PlayerId(1),
                agent_name: Some("engine-b".into()),
                agent_version: Some("1".into()),
            },
        ],
        ArenaOutcomeV1::completed(
            splendor_core::GameResult {
                scores: replay.result.scores.clone(),
                ranks: replay.result.ranks.clone(),
                winners: replay
                    .result
                    .winners
                    .iter()
                    .copied()
                    .map(PlayerId)
                    .collect(),
                reason: replay.result.reason.into(),
            },
            replay.steps.len() as u32,
            replay.final_state_hash.as_str().to_string(),
        ),
    )
}

#[test]
fn completed_report_resolves_only_by_final_hash_and_verifies_replay() {
    let dir = temp_dir("completed");
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let (_, replay) = record_random_game(2, 81, 101).unwrap();
    let bytes = serde_json::to_vec(&replay).unwrap();
    let replay_path = dir.join("unrelated-name.json");
    std::fs::write(&replay_path, &bytes).unwrap();
    let index = build_replay_content_index(&[dir.clone()], 1_000_000, &[]).unwrap();

    let resolution = resolve_arena_report_replay(&completed_report(&replay), &index).unwrap();
    let HistoricalReplayResolutionV1::Verified {
        candidate,
        completed_plies,
    } = resolution
    else {
        panic!("completed report must resolve a replay")
    };
    assert_eq!(
        candidate.document_sha256,
        hex::encode(Sha256::digest(&bytes))
    );
    assert_eq!(completed_plies, replay.steps.len() as u32);

    let report = completed_report(&replay);
    let report_bytes = serde_json::to_vec(&report).unwrap();
    let logical_path = "benchmarks/m41a-corpus/train/game-0000/arena-report.json";
    let record = arena_report_to_match_record(logical_path, &report_bytes, &index).unwrap();
    assert_eq!(record.source_identity, logical_path);
    assert_eq!(record.source_path.as_deref(), Some(logical_path));
    assert_eq!(
        record.source_document_hash,
        hex::encode(Sha256::digest(&report_bytes))
    );
    assert_eq!(record.status, MatchStatus::Completed);
    assert_eq!(record.completed_plies, Some(replay.steps.len() as u32));
    assert_eq!(
        record.main_turn_count, None,
        "plies must never be used as turns"
    );
    assert_eq!(
        record.seats[0].identity.as_ref().unwrap().key(),
        "engine-a@1"
    );
    assert_eq!(record.replay.verification(), ReplayVerification::Verified);
    assert_eq!(
        record.replay.document_hash.as_deref(),
        Some(candidate.document_sha256.as_str())
    );
    assert_eq!(
        record.replay.path.as_deref(),
        Some(candidate.logical_path.as_str())
    );

    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn completed_report_never_falls_back_to_a_colocated_filename() {
    let dir = temp_dir("no-filename-fallback");
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let (_, replay) = record_random_game(2, 82, 102).unwrap();
    std::fs::write(
        dir.join("historical-game.replay.json"),
        serde_json::to_vec(&replay).unwrap(),
    )
    .unwrap();
    let empty_index = build_replay_content_index(&[], 1_000_000, &[]).unwrap();

    let error = resolve_arena_report_replay(&completed_report(&replay), &empty_index).unwrap_err();
    assert!(matches!(error, StudioLeagueError::Invalid(_)));

    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn aborted_and_truncated_reports_remain_legal_result_only_records() {
    let (_, replay) = record_random_game(2, 83, 103).unwrap();
    let mut aborted = completed_report(&replay);
    aborted.outcome = ArenaOutcomeV1::aborted(
        1,
        splendor_arena::ArenaPhase::ActionRequest,
        splendor_arena::AgentFault::ActionTimeout,
        Some(7),
        12,
    );
    let mut truncated = completed_report(&replay);
    truncated.outcome = ArenaOutcomeV1::truncated(100, "a".repeat(64), vec![8, 7]);
    let empty_index = build_replay_content_index(&[], 1_000_000, &[]).unwrap();

    assert_eq!(
        resolve_arena_report_replay(&aborted, &empty_index).unwrap(),
        HistoricalReplayResolutionV1::ResultOnly
    );
    assert_eq!(
        resolve_arena_report_replay(&truncated, &empty_index).unwrap(),
        HistoricalReplayResolutionV1::ResultOnly
    );

    for (logical_path, report, status) in [
        (
            "benchmarks/m41a-corpus/train/game-0001/arena-report.json",
            aborted,
            MatchStatus::Aborted,
        ),
        (
            "benchmarks/m41a-corpus/train/game-0002/arena-report.json",
            truncated,
            MatchStatus::Truncated,
        ),
    ] {
        let bytes = serde_json::to_vec(&report).unwrap();
        let record = arena_report_to_match_record(logical_path, &bytes, &empty_index).unwrap();
        assert_eq!(record.source_identity, logical_path);
        assert_eq!(record.status, status);
        assert_eq!(
            record.replay.verification(),
            ReplayVerification::Unavailable
        );
        assert!(record.replay.document_hash.is_none());
        assert!(record.winners().is_empty());
    }
}
