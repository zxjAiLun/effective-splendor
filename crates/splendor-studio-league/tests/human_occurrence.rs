//! Human Live League integration, Slice A gates.
//!
//! Slice A ships the pieces a human completion needs and nothing else: the one
//! shared policy resolver, the durable human occurrence envelope and its builder,
//! and the shared completion tail the arena path already used. There is no Host
//! wiring, no durable evidence publish, and no retry orchestration here — that is
//! Slice B.
//!
//! The sentences these gates make true:
//!
//! * **H1 — the builder refuses to invent a match.** Every way a human record
//!   could be wrong (replay bytes that are not the attested ones, a seed that
//!   disagrees with the replay, a seat outside the game, an identity the league
//!   does not recognize, a manifest that changed since the game started, an
//!   opponent command that re-resolves to a different policy) fails closed.
//! * **H2 — both seats map to the right participants**, for both human seats.
//! * **H3 — a rated human match produces exactly two rating events**, one for the
//!   human and one for the engine, and moves the human from `NULL` to a real Elo.
//! * **H4 — the human content path is the occurrence evidence, not the replay.**
//!   Re-offering identical evidence is `AlreadyPresent` with no new events;
//!   changing the evidence under the same occurrence id is a conflict.

use sha2::{Digest, Sha256};
use splendor_replay::record_random_game;
use splendor_studio_league::{
    complete_human_runtime_occurrence, human_runtime_occurrence_evidence_hash,
    open_completion_league, open_league, parse_human_runtime_occurrence, CompletionLeagueV1,
    CompletionOutcomeV1, HumanCompletionRequestV1, HumanOccurrenceHumanV1,
    HumanOccurrenceOpponentV1, HumanRuntimeOccurrenceV1, IdentityManifestV1, StudioLeagueError,
    StudioLeaguePathsV1, HUMAN_RUNTIME_OCCURRENCE_FORMAT,
};
use std::path::PathBuf;

fn sha256(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

fn tempdir(label: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!(
        "splendor-human-occurrence-{}-{}",
        std::process::id(),
        label
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

/// A played-out 1v1 game recorded by the engine, plus its document hash.
fn played_game(seed: u64) -> (splendor_replay::ReplayV1, Vec<u8>) {
    let (_, replay) = record_random_game(2, seed, 101).unwrap();
    let bytes = serde_json::to_vec(&replay).unwrap();
    (replay, bytes)
}

/// A league whose manifest has a local human, exactly as `studio-league-migrate`
/// leaves it.
struct League {
    paths: StudioLeaguePathsV1,
    manifest_hash: String,
    local_human: String,
}

impl League {
    fn new(label: &str) -> Self {
        let root = tempdir(label);
        let paths = StudioLeaguePathsV1::from_root(&root);
        std::fs::create_dir_all(paths.dir()).unwrap();
        let mut manifest = IdentityManifestV1::new();
        let local = manifest.ensure_local_human("You");
        let local_human = local.participant_id.clone();
        manifest.save(paths.identity()).unwrap();
        let manifest_hash = manifest.hash().unwrap();
        let league = Self {
            paths,
            manifest_hash,
            local_human,
        };
        // Create the database and sync the manifest once, single-threaded.
        drop(league.session());
        league
    }

    fn session(&self) -> CompletionLeagueV1 {
        open_completion_league(&self.paths, 1_700_000_000).expect("open a completion session")
    }

    fn inspect(&self) -> rusqlite::Connection {
        open_league(self.paths.db()).unwrap()
    }

    fn count(&self, sql: &str) -> i64 {
        self.inspect().query_row(sql, [], |row| row.get(0)).unwrap()
    }
}

/// An envelope for one human game, built the way the Host producer will build it.
fn occurrence(
    league: &League,
    occurrence_id: &str,
    completed_at: i64,
    seed: u64,
    human_seat: u8,
    replay_bytes: &[u8],
) -> HumanRuntimeOccurrenceV1 {
    HumanRuntimeOccurrenceV1 {
        format: HUMAN_RUNTIME_OCCURRENCE_FORMAT.to_string(),
        version: 1,
        occurrence_id: occurrence_id.to_string(),
        completed_at,
        seed,
        human_seat,
        replay_sha256: sha256(replay_bytes),
        human: HumanOccurrenceHumanV1 {
            participant_id: league.local_human.clone(),
            display_name: "You".to_string(),
            identity_manifest_hash: league.manifest_hash.clone(),
        },
        opponent: HumanOccurrenceOpponentV1 {
            registry_id: "studio-1v1".to_string(),
            agent_id: "s3-rollout".to_string(),
            display_name: "splendor.exe:agent-s3-rollout".to_string(),
            runtime_name: "effective-splendor-s3-rollout-v1".to_string(),
            runtime_version: "1".to_string(),
            program: "splendor.exe".to_string(),
            args: vec!["agent-s3-rollout".to_string()],
            policy_key: "splendor.exe:agent-s3-rollout".to_string(),
        },
    }
}

fn request<'a>(
    occurrence: &'a HumanRuntimeOccurrenceV1,
    replay_bytes: &'a [u8],
) -> HumanCompletionRequestV1<'a> {
    HumanCompletionRequestV1 {
        occurrence,
        replay_bytes,
        replay_source_path: "human-replay.json",
    }
}

fn complete(
    league: &League,
    occurrence: &HumanRuntimeOccurrenceV1,
    replay_bytes: &[u8],
) -> splendor_studio_league::Result<CompletionOutcomeV1> {
    let mut session = league.session();
    complete_human_runtime_occurrence(&mut session, &request(occurrence, replay_bytes))
}

/// H1a: the envelope parses, and a non-human document is not mistaken for one.
#[test]
fn only_a_human_occurrence_document_parses_as_one() {
    let league = League::new("parse");
    let (_, replay) = played_game(11);
    let good = occurrence(&league, "human-11-0-1", 1_800_000_100, 11, 0, &replay);
    let bytes = serde_json::to_vec(&good).unwrap();
    assert_eq!(
        parse_human_runtime_occurrence(&bytes).unwrap(),
        Some(good.clone())
    );

    // An arena occurrence envelope and an arbitrary document are both `None`,
    // so a human slot and an arena slot can never be confused by format.
    let arena = br#"{"format":"effective-splendor-runtime-occurrence","version":1}"#;
    assert!(parse_human_runtime_occurrence(arena).unwrap().is_none());
    assert!(parse_human_runtime_occurrence(b"{}").unwrap().is_none());
    assert!(parse_human_runtime_occurrence(b"not json")
        .unwrap()
        .is_none());

    // A document that *claims* to be one but is malformed is an error.
    let mut wrong_version = serde_json::to_value(&good).unwrap();
    wrong_version["version"] = serde_json::json!(2);
    assert!(parse_human_runtime_occurrence(&serde_json::to_vec(&wrong_version).unwrap()).is_err());

    let mut bad_seat = serde_json::to_value(&good).unwrap();
    bad_seat["human_seat"] = serde_json::json!(2);
    assert!(parse_human_runtime_occurrence(&serde_json::to_vec(&bad_seat).unwrap()).is_err());

    let mut empty_runtime = serde_json::to_value(&good).unwrap();
    empty_runtime["opponent"]["runtime_name"] = serde_json::json!("");
    assert!(parse_human_runtime_occurrence(&serde_json::to_vec(&empty_runtime).unwrap()).is_err());
}

/// H4a: the evidence hash covers the whole envelope, not the replay.
#[test]
fn the_evidence_hash_covers_every_envelope_field() {
    let league = League::new("hash");
    let (_, replay) = played_game(13);
    let base = occurrence(&league, "human-13-0-1", 1_800_000_200, 13, 0, &replay);
    let base_hash = human_runtime_occurrence_evidence_hash(&base);
    assert_eq!(
        base_hash,
        human_runtime_occurrence_evidence_hash(&base.clone())
    );
    assert_ne!(
        base_hash,
        sha256(&replay),
        "the replay sha is not the evidence"
    );
    assert_ne!(
        base_hash,
        splendor_studio_league::runtime_occurrence_evidence_hash(
            &splendor_studio_league::RuntimeOccurrenceV1 {
                format: splendor_studio_league::RUNTIME_OCCURRENCE_FORMAT.to_string(),
                version: 1,
                occurrence_id: base.occurrence_id.clone(),
                completed_at: base.completed_at,
                report_sha256: base.replay_sha256.clone(),
                replay_sha256: base.replay_sha256.clone(),
                config_sha256: base.replay_sha256.clone(),
            }
        ),
        "a human hash must not collide with an arena hash domain"
    );

    // Each representative mutation must change the hash: these are the fields a
    // future producer could silently reinterpret.
    let mutations: Vec<(&str, Box<dyn Fn(&mut HumanRuntimeOccurrenceV1)>)> = vec![
        ("completed_at", Box::new(|o| o.completed_at += 1)),
        (
            "replay_sha256",
            Box::new(|o| o.replay_sha256 = "b".repeat(64)),
        ),
        (
            "human participant",
            Box::new(|o| o.human.participant_id = "someone-else".to_string()),
        ),
        (
            "manifest hash",
            Box::new(|o| o.human.identity_manifest_hash = "c".repeat(64)),
        ),
        (
            "policy key",
            Box::new(|o| o.opponent.policy_key = "splendor.exe:agent-other".to_string()),
        ),
        (
            "program",
            Box::new(|o| o.opponent.program = "other.exe".to_string()),
        ),
        (
            "args",
            Box::new(|o| o.opponent.args.push("--max-nodes".to_string())),
        ),
        ("human_seat", Box::new(|o| o.human_seat = 1)),
        ("seed", Box::new(|o| o.seed += 1)),
        (
            "occurrence id",
            Box::new(|o| o.occurrence_id = "human-13-0-2".to_string()),
        ),
    ];
    for (label, mutate) in mutations {
        let mut changed = base.clone();
        mutate(&mut changed);
        assert_ne!(
            human_runtime_occurrence_evidence_hash(&changed),
            base_hash,
            "mutating `{label}` must change the occurrence evidence hash"
        );
    }
}

/// H1b: a replay that is not the attested one writes nothing.
#[test]
fn a_replay_that_is_not_the_attested_one_writes_nothing() {
    let league = League::new("replay-mismatch");
    let (_, replay) = played_game(17);
    let (_, other) = played_game(19);
    let good = occurrence(&league, "human-17-0-1", 1_800_000_300, 17, 0, &replay);

    let error = complete(&league, &good, &other).unwrap_err();
    assert!(
        error.to_string().contains("envelopes replay sha"),
        "the replay sha must be checked, got: {error}"
    );
    assert_eq!(league.count("SELECT COUNT(*) FROM matches"), 0);
    assert_eq!(league.count("SELECT COUNT(*) FROM rating_events"), 0);
}

/// H1c: the envelope's seed must be the seed the replay was actually played with.
#[test]
fn a_seed_that_disagrees_with_the_replay_writes_nothing() {
    let league = League::new("seed-mismatch");
    let (_, replay) = played_game(23);
    let mut wrong_seed = occurrence(&league, "human-23-0-1", 1_800_000_400, 23, 0, &replay);
    wrong_seed.seed = 24;

    let error = complete(&league, &wrong_seed, &replay).unwrap_err();
    assert!(
        error.to_string().contains("was played with seed"),
        "the seed must agree with the replay, got: {error}"
    );
    assert_eq!(league.count("SELECT COUNT(*) FROM matches"), 0);
}

/// H1d: identity the league cannot confirm never becomes a rated human match.
#[test]
fn an_human_identity_the_league_cannot_confirm_never_rates() {
    let league = League::new("identity");
    let (_, replay) = played_game(29);

    // (i) a human participant the league does not have.
    let mut stranger = occurrence(&league, "human-29-0-1", 1_800_000_500, 29, 0, &replay);
    stranger.human.participant_id = "b901a2ea-0000-0000-0000-000000000000".to_string();
    let error = complete(&league, &stranger, &replay).unwrap_err();
    assert!(
        error.to_string().contains("this league's local human is"),
        "an unknown human id must fail closed, got: {error}"
    );

    // (ii) a manifest hash that changed since the game started.
    let mut stale = occurrence(&league, "human-29-0-1", 1_800_000_500, 29, 0, &replay);
    stale.human.identity_manifest_hash = "d".repeat(64);
    let error = complete(&league, &stale, &replay).unwrap_err();
    assert!(
        error.to_string().contains("the identity authority changed"),
        "a changed manifest must fail closed, got: {error}"
    );

    // (iii) an opponent command that no longer resolves to the recorded policy,
    //       and one that cannot be attributed at all.
    let mut reinterpreted = occurrence(&league, "human-29-0-1", 1_800_000_500, 29, 0, &replay);
    reinterpreted.opponent.args = vec![
        "agent-s3-rollout".to_string(),
        "--max-nodes".to_string(),
        "9999".to_string(),
    ];
    let error = complete(&league, &reinterpreted, &replay).unwrap_err();
    assert!(
        error.to_string().contains("re-resolves to policy"),
        "a re-resolved policy mismatch must fail closed, got: {error}"
    );

    let mut unattributable = occurrence(&league, "human-29-0-1", 1_800_000_500, 29, 0, &replay);
    unattributable.opponent.args = vec![
        "agent-s3-rollout".to_string(),
        "--future-policy-knob".to_string(),
        "7".to_string(),
    ];
    let error = complete(&league, &unattributable, &replay).unwrap_err();
    assert!(
        error.to_string().contains("cannot be attributed"),
        "an unclassifiable command must fail closed, got: {error}"
    );

    assert_eq!(
        league.count("SELECT COUNT(*) FROM matches"),
        0,
        "no match row"
    );
    assert_eq!(league.count("SELECT COUNT(*) FROM rating_events"), 0);
}

/// H2 + H3: both seats map correctly, and one rated 1v1 produces exactly two
/// events — one for the human, one for the engine.
#[test]
fn a_rated_human_match_rates_both_seats_exactly_once() {
    for human_seat in [0u8, 1u8] {
        let league = League::new(&format!("rated-seat-{human_seat}"));
        let seed = 31 + u64::from(human_seat);
        let (_, replay) = played_game(seed);
        let occ = occurrence(
            &league,
            &format!("human-{seed}-{human_seat}-1"),
            1_800_000_600 + i64::from(human_seat),
            seed,
            human_seat,
            &replay,
        );

        let outcome = complete(&league, &occ, &replay).unwrap();
        assert!(outcome.was_inserted());
        assert_eq!(
            outcome.rating_events(),
            2,
            "an eligible 1v1 produces exactly two rating events"
        );
        assert_eq!(outcome.record.source_kind, "human_play");
        assert_eq!(
            outcome.record.source_identity,
            format!("runtime:{}", occ.occurrence_id)
        );
        assert_eq!(
            outcome.record.source_document_hash,
            human_runtime_occurrence_evidence_hash(&occ),
            "idempotency is keyed on the occurrence evidence, not the replay"
        );
        assert_eq!(outcome.record.played_at, Some(occ.completed_at));

        // The two seats are shaped as the contract requires: an explicit human
        // participant with no engine identity, and a resolved engine policy.
        let human = &outcome.record.seats[human_seat as usize];
        let engine = &outcome.record.seats[1 - human_seat as usize];
        assert_eq!(
            human.participant_id.as_deref(),
            Some(league.local_human.as_str())
        );
        assert_eq!(human.identity, None, "a human is not an engine identity");
        assert_eq!(
            human.display_name.as_deref(),
            Some("You"),
            "the human seat keeps its manifest display name"
        );
        assert_eq!(
            engine.identity.as_ref().unwrap().agent_name,
            "effective-splendor-s3-rollout-v1"
        );
        assert_eq!(engine.participant_id, None);
        assert_eq!(
            engine.policy_identity,
            splendor_studio_league::SeatPolicyIdentityV1::Resolved {
                policy_key: "splendor.exe:agent-s3-rollout".to_string()
            }
        );

        // Exactly one event per participant, and the human moves off NULL.
        let human_events: i64 = league
            .inspect()
            .query_row(
                "SELECT COUNT(*) FROM rating_events WHERE participant_id = ?1",
                [&league.local_human],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(human_events, 1, "the human has exactly one rating event");
        assert_eq!(league.count("SELECT COUNT(*) FROM rating_events"), 2);

        let human_elo: Option<f64> = league
            .inspect()
            .query_row(
                "SELECT current_elo FROM participants WHERE participant_id = ?1",
                [&league.local_human],
                |row| row.get(0),
            )
            .unwrap();
        assert!(
            human_elo.is_some(),
            "the human's current_elo must move from NULL to a real value"
        );

        // The engine seat resolved to a real engine participant, distinct from
        // the human.
        let engine_participant: Option<String> = league
            .inspect()
            .query_row(
                "SELECT participant_id FROM match_seats WHERE seat = ?1",
                [i64::from(1 - human_seat)],
                |row| row.get(0),
            )
            .unwrap();
        let engine_participant = engine_participant.expect("the engine seat is mapped");
        assert_ne!(engine_participant, league.local_human);
        assert!(
            engine_participant.starts_with("eng-"),
            "an engine participant keeps its derived id, got {engine_participant}"
        );
    }
}

/// H4b: identical evidence re-offered is `AlreadyPresent` with no new events;
/// changed evidence under the same occurrence id is a conflict.
#[test]
fn the_same_human_occurrence_is_idempotent_and_changed_evidence_conflicts() {
    let league = League::new("idempotent");
    let (_, replay) = played_game(37);
    let occ = occurrence(&league, "human-37-0-1", 1_800_000_700, 37, 0, &replay);

    let first = complete(&league, &occ, &replay).unwrap();
    assert!(first.was_inserted());
    assert_eq!(first.rating_events(), 2);

    let second = complete(&league, &occ, &replay).unwrap();
    assert!(!second.was_inserted(), "identical evidence is idempotent");
    assert_eq!(second.rating_events(), 0, "no extra rating events");
    assert_eq!(first.match_id(), second.match_id());
    assert_eq!(league.count("SELECT COUNT(*) FROM matches"), 1);
    assert_eq!(league.count("SELECT COUNT(*) FROM rating_events"), 2);

    // Same occurrence id, same documents, but a different `completed_at`: the
    // occurrence evidence changed, so this must conflict rather than be
    // swallowed as idempotent.
    let mut shifted = occ.clone();
    shifted.completed_at += 1;
    let error = complete(&league, &shifted, &replay).unwrap_err();
    assert!(
        matches!(error, StudioLeagueError::SourceConflict { .. }),
        "changed human evidence under one occurrence id must conflict, got: {error}"
    );
    assert_eq!(
        league.count("SELECT COUNT(*) FROM matches"),
        1,
        "no new row"
    );
    assert_eq!(
        league.count("SELECT COUNT(*) FROM rating_events"),
        2,
        "no new event"
    );
}

/// H1e: a league with no local human cannot attribute a human match at all.
#[test]
fn a_league_without_a_local_human_refuses_a_human_completion() {
    let root = tempdir("no-local-human");
    let paths = StudioLeaguePathsV1::from_root(&root);
    std::fs::create_dir_all(paths.dir()).unwrap();
    let manifest = IdentityManifestV1::new();
    manifest.save(paths.identity()).unwrap();
    let mut session = open_completion_league(&paths, 1_700_000_000).unwrap();

    let (_, replay) = played_game(41);
    let occ = HumanRuntimeOccurrenceV1 {
        format: HUMAN_RUNTIME_OCCURRENCE_FORMAT.to_string(),
        version: 1,
        occurrence_id: "human-41-0-1".to_string(),
        completed_at: 1_800_000_800,
        seed: 41,
        human_seat: 0,
        replay_sha256: sha256(&replay),
        human: HumanOccurrenceHumanV1 {
            participant_id: "any".to_string(),
            display_name: "You".to_string(),
            identity_manifest_hash: manifest.hash().unwrap(),
        },
        opponent: HumanOccurrenceOpponentV1 {
            registry_id: "studio-1v1".to_string(),
            agent_id: "s3-rollout".to_string(),
            display_name: "s3".to_string(),
            runtime_name: "effective-splendor-s3-rollout-v1".to_string(),
            runtime_version: "1".to_string(),
            program: "splendor.exe".to_string(),
            args: vec!["agent-s3-rollout".to_string()],
            policy_key: "splendor.exe:agent-s3-rollout".to_string(),
        },
    };
    let error =
        complete_human_runtime_occurrence(&mut session, &request(&occ, &replay)).unwrap_err();
    assert!(
        error.to_string().contains("no local human participant"),
        "a league without a local human must refuse, got: {error}"
    );
}
