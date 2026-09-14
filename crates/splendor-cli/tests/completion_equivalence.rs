//! Commit C Slice 3 gate 1: the CLI adapter and a direct outlet call must agree.
//!
//! `studio-league-ingest` is only an adapter now — it reads the occurrence
//! envelope and the three documents, calls
//! [`splendor_studio_league::complete_runtime_occurrence`], and prints the
//! receipt. This test pins that: the same fixture, completed once through the
//! process boundary and once through the library, must produce the same match
//! identity, the same eligibility, the same rating events, and the same archive
//! binding.
use rusqlite::Connection;
use sha2::{Digest, Sha256};
use splendor_arena::{seed_commitment_v1, AgentIdentity, ArenaOutcomeV1, ArenaReportV1, PlayerId};
use splendor_core::{ruleset_fingerprint, FullState, GameConfig, Ruleset};
use splendor_replay::record_random_game;
use splendor_studio_league::{
    complete_runtime_occurrence, leaderboard, open_completion_league, parse_runtime_occurrence,
    CompletionRequestV1, IdentityManifestV1, StudioLeaguePathsV1, RUNTIME_OCCURRENCE_FORMAT,
};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::atomic::{AtomicU64, Ordering};

fn bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_splendor"))
}

static TMP_SEQ: AtomicU64 = AtomicU64::new(0);

fn tempdir(label: &str) -> PathBuf {
    let seq = TMP_SEQ.fetch_add(1, Ordering::SeqCst);
    let dir = std::env::temp_dir().join(format!(
        "splendor-completion-equiv-{}-{}-{}",
        std::process::id(),
        seq,
        label
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn sha256(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

/// The three documents a finished arena occurrence produces.
fn occurrence_documents(game_id: &str, seed: u64) -> (Vec<u8>, Vec<u8>, Vec<u8>) {
    let (_, replay) = record_random_game(2, seed, 101).unwrap();
    assert!(FullState::new(GameConfig {
        player_count: replay.player_count,
        seed: replay.seed,
        ruleset: Ruleset::base_v1(),
    })
    .is_ok());
    let fingerprint = ruleset_fingerprint(&Ruleset::base_v1());
    let report = ArenaReportV1::new(
        game_id,
        replay.engine_version.clone(),
        "1",
        "base_v1",
        fingerprint.as_str(),
        replay.player_count,
        seed_commitment_v1(game_id, replay.player_count, replay.seed, &fingerprint),
        (0..replay.player_count)
            .map(|seat| AgentIdentity {
                seat: PlayerId(seat),
                agent_name: Some("effective-splendor-determinization-agent-v1".into()),
                agent_version: Some("1".into()),
            })
            .collect(),
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
    );
    let config = serde_json::json!({
        "game_id": game_id,
        "seed": seed,
        "agents": [
            { "program": "splendor.exe", "args": [
                "agent-determinization", "--sample-count", "4",
                "--max-depth-turns", "1", "--max-nodes", "2000" ] },
            { "program": "splendor.exe", "args": [
                "agent-determinization", "--sample-count", "4",
                "--max-depth-turns", "1", "--max-nodes", "1" ] }
        ]
    });
    (
        serde_json::to_vec(&report).unwrap(),
        serde_json::to_vec(&replay).unwrap(),
        serde_json::to_vec(&config).unwrap(),
    )
}

/// Every ledger fact the two paths must agree on.
#[derive(Debug, PartialEq, Eq)]
struct LedgerSnapshot {
    matches: Vec<String>,
    seats: Vec<String>,
    rating_events: Vec<String>,
    leaderboard: Vec<String>,
}

fn snapshot(db_path: &Path) -> LedgerSnapshot {
    let conn = Connection::open(db_path).unwrap();
    let collect = |sql: &str| -> Vec<String> {
        let mut stmt = conn.prepare(sql).unwrap();
        let rows = stmt
            .query_map([], |row| {
                let mut cells = Vec::new();
                for index in 0..row.as_ref().column_count() {
                    let value: rusqlite::types::Value = row.get(index)?;
                    cells.push(format!("{value:?}"));
                }
                Ok(cells.join("|"))
            })
            .unwrap()
            .collect::<Result<Vec<_>, _>>()
            .unwrap();
        rows
    };
    let events = collect(
        "SELECT match_id, league_seq, participant_id, opponent_id, elo_before, elo_after, delta, score
           FROM rating_events ORDER BY league_seq, participant_id",
    );
    let board = leaderboard(&conn)
        .unwrap()
        .into_iter()
        .map(|row| {
            format!(
                "{}|{:?}|{}|{}|{}|{}|{}",
                row.participant_id,
                row.kind,
                row.display_name,
                row.elo,
                row.rated_games,
                row.recorded_games,
                row.provisional
            )
        })
        .collect();
    LedgerSnapshot {
        matches: collect(
            "SELECT match_id, source_kind, source_identity, source_document_hash, league_seq,
                    played_at, replay_storage, replay_path, replay_document_hash,
                    replay_final_hash, replay_verification, rating_eligible,
                    rating_ineligible_reason
               FROM matches ORDER BY league_seq",
        ),
        seats: collect(
            "SELECT match_id, seat, participant_id, score, rank, won
               FROM match_seats ORDER BY match_id, seat",
        ),
        rating_events: events,
        leaderboard: board,
    }
}

#[test]
fn the_cli_adapter_and_a_direct_outlet_call_agree() {
    let root = tempdir("equivalence");
    // Each path gets its own explicit project root. Both are exercised from a
    // cwd that is neither of them, so agreement cannot come from the process
    // working directory.
    let cli_root = root.join("cli-root");
    let direct_root = root.join("direct-root");
    let cli_paths = StudioLeaguePathsV1::from_root(&cli_root);
    let direct_paths = StudioLeaguePathsV1::from_root(&direct_root);
    // One manifest, published into both roots: the comparison must be about the
    // archived evidence and the ledger, not about two freshly minted local ids.
    let mut manifest = IdentityManifestV1::new();
    manifest.ensure_local_human("Nick");
    for paths in [&cli_paths, &direct_paths] {
        std::fs::create_dir_all(paths.dir()).unwrap();
        manifest.save(paths.identity()).unwrap();
    }

    let (report, replay, config) = occurrence_documents("game-equivalence", 31);
    let completed_at: i64 = 1_800_001_000;
    let envelope = serde_json::to_vec(&serde_json::json!({
        "format": RUNTIME_OCCURRENCE_FORMAT,
        "version": 1,
        "occurrence_id": "occ-equivalence",
        "completed_at": completed_at,
        "report_sha256": sha256(&report),
        "replay_sha256": sha256(&replay),
        "config_sha256": sha256(&config),
    }))
    .unwrap();
    let occurrence_sidecar = root.join("occurrence.json");
    let report_sidecar = root.join("report.json");
    let replay_sidecar = root.join("replay.json");
    let config_sidecar = root.join("config.json");
    let receipt_path = root.join("receipt.json");
    std::fs::write(&occurrence_sidecar, &envelope).unwrap();
    std::fs::write(&report_sidecar, &report).unwrap();
    std::fs::write(&replay_sidecar, &replay).unwrap();
    std::fs::write(&config_sidecar, &config).unwrap();

    // Path A: the process boundary.
    let output = Command::new(bin())
        .current_dir(&root)
        .args([
            "studio-league-ingest",
            "--occurrence",
            occurrence_sidecar.to_str().unwrap(),
            "--report",
            report_sidecar.to_str().unwrap(),
            "--replay",
            replay_sidecar.to_str().unwrap(),
            "--config",
            config_sidecar.to_str().unwrap(),
            "--project-root",
            cli_root.to_str().unwrap(),
            "--json",
            receipt_path.to_str().unwrap(),
        ])
        .output()
        .expect("run studio-league-ingest");
    assert!(
        output.status.success(),
        "CLI failed: {}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );

    // Path B: the library outlet, same documents, same protocol archive root.
    let occurrence = parse_runtime_occurrence(&envelope)
        .unwrap()
        .expect("a well-formed envelope");
    let request = CompletionRequestV1 {
        occurrence: &occurrence,
        report_bytes: &report,
        replay_bytes: &replay,
        config_bytes: &config,
        replay_source_path: "replay.json",
    };
    let mut session = open_completion_league(&direct_paths, completed_at).unwrap();
    let direct = complete_runtime_occurrence(&mut session, &request).unwrap();
    assert!(direct.was_inserted(), "the direct path inserts");

    // Neither path was told where to archive beyond its own project root; each
    // landed under its own root, not under the cwd.
    let replay_sha = sha256(&replay);
    let object_in = |paths: &StudioLeaguePathsV1| {
        paths
            .replay_root()
            .join(&replay_sha[..2])
            .join(format!("{replay_sha}.json"))
    };
    assert!(
        object_in(&cli_paths).exists(),
        "the CLI archived under its own project root"
    );
    assert!(
        object_in(&direct_paths).exists(),
        "the direct outlet archived under its own project root"
    );
    assert!(
        !root.join("local-artifacts").join("studio-league").exists(),
        "nothing may be archived relative to the process working directory"
    );

    let cli = snapshot(cli_paths.db());
    let library = snapshot(direct_paths.db());
    assert_eq!(cli.matches, library.matches, "match rows agree");
    assert_eq!(cli.seats, library.seats, "seat rows agree");
    assert_eq!(
        cli.rating_events, library.rating_events,
        "rating events agree"
    );
    assert_eq!(cli.leaderboard, library.leaderboard, "leaderboards agree");
    assert!(!cli.matches.is_empty(), "the comparison is not vacuous");
    assert!(!cli.seats.is_empty(), "seat rows were compared");
    assert_eq!(cli.rating_events.len(), 2, "two Elo events were compared");
    assert!(!cli.leaderboard.is_empty(), "the leaderboard was compared");

    // The receipt the CLI exported is the receipt the ledger holds.
    let exported: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&receipt_path).unwrap()).unwrap();
    assert_eq!(exported["match_id"].as_str().unwrap(), direct.match_id());
    assert_eq!(
        exported["outcome"]["kind"].as_str().unwrap(),
        "inserted",
        "receipt records the inserted outcome"
    );
}
