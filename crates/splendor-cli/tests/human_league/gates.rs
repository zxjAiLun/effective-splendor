//! Slice B gates, driven through the real Host socket. All roots, registries,
//! legacy files and SQLite databases belong to temp fixtures, never the real League.
use super::*;
use splendor_agent::{
    AgentPolicy, DecisionContext, HeuristicAgentPolicy, PublicRequestMeta, StableRng,
};
use splendor_core::{observation_hash, Action, Observation};
use splendor_studio_league::{now_epoch_seconds, replay_document_sha256, resolve_policy_identity};

fn human_registry(dir: &Path, program: &Path) -> PathBuf {
    let path = host_registry(dir, &gate_seats(program));
    let mut value: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    value["agents"][0]["runtime_name"] = splendor_agent::HEURISTIC_AGENT_NAME.into();
    value["agents"][0]["runtime_version"] = splendor_agent::HEURISTIC_AGENT_VERSION.into();
    value["agents"][1]["runtime_name"] = splendor_agent::RANDOM_AGENT_NAME.into();
    value["agents"][1]["runtime_version"] = splendor_core::ENGINE_VERSION.into();
    std::fs::write(&path, serde_json::to_vec(&value).unwrap()).unwrap();
    path
}

fn start_game(host: &HostProcess, seat: u8, seed: u64) -> serde_json::Value {
    let (code, state) = host.post_json(
        "/games",
        &serde_json::json!({
            "agent_id": "gate-heuristic", "human_seat": seat, "seed": seed
        }),
    );
    assert_eq!(code, 200, "{state}");
    assert!(state["league_completion"].is_null());
    assert_eq!(state["seed"], seed.to_string());
    assert_eq!(state["human_seat"], seat);
    state
}

// A scripted human uses ONLY the public observation and server-certified legal
// actions, not a fabricated replay or hidden game state. UI rendering is not tested.
fn finish_game(host: &HostProcess, mut state: serde_json::Value) -> serde_json::Value {
    let mut policy = HeuristicAgentPolicy::new();
    let mut rng = StableRng::new(27);
    for turn in 0..400 {
        if !state["result"].is_null() {
            return state;
        }
        let observation: Observation =
            serde_json::from_value(state["observation"].clone()).unwrap();
        let legal: Vec<Action> = serde_json::from_value(state["legal_actions"].clone()).unwrap();
        let action = policy
            .choose_action(DecisionContext {
                meta: PublicRequestMeta {
                    game_id: state["session_id"].as_str().unwrap().to_string(),
                    recipient_seat: observation.viewer,
                    request_id: turn,
                    observation_hash: observation_hash(&observation),
                },
                observation,
                visible_history: &[],
                legal_actions: &legal,
                rng: &mut rng,
            })
            .unwrap();
        let (code, next) = host.post_json("/action", &serde_json::to_value(action).unwrap());
        assert_eq!(
            code, 200,
            "terminal game fact must survive booking/IO failure: {next}"
        );
        state = next;
    }
    panic!("scripted game did not terminate");
}

fn retry(host: &HostProcess, id: &str, body: &[u8]) -> (u16, serde_json::Value) {
    let (status, bytes) =
        http_post_raw(host.port, &format!("/games/{id}/league-completion"), body).unwrap();
    (
        status_code(&status),
        serde_json::from_slice(&bytes).unwrap(),
    )
}

fn counts(paths: &StudioLeaguePathsV1) -> (i64, i64) {
    let conn = rusqlite::Connection::open_with_flags(
        paths.db(),
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
    )
    .unwrap();
    (
        count_rows(&conn, "SELECT COUNT(*) FROM matches"),
        count_rows(&conn, "SELECT COUNT(*) FROM rating_events"),
    )
}

fn block_db(paths: &StudioLeaguePathsV1) {
    std::fs::remove_file(paths.db()).unwrap();
    std::fs::create_dir(paths.db()).unwrap();
}
fn unblock_db(paths: &StudioLeaguePathsV1) {
    std::fs::remove_dir(paths.db()).unwrap();
}
fn envelope(paths: &StudioLeaguePathsV1, id: &str) -> serde_json::Value {
    serde_json::from_slice(
        &std::fs::read(paths.occurrence_dir(id).unwrap().join("occurrence.json")).unwrap(),
    )
    .unwrap()
}

#[test]
fn human_host_books_both_seats_and_freezes_the_selected_registry_entry() {
    for seat in [0, 1] {
        let dir = tmp_dir(&format!("human-seat-{seat}"));
        let (root, paths) = new_league(&dir);
        let human = IdentityManifestV1::load(paths.identity())
            .unwrap()
            .unwrap()
            .local_human
            .unwrap();
        let registry = human_registry(&dir, &bin());
        let host = HostProcess::start_with_registry(&root, &dir, &registry);
        // Decisive TOCTOU control: the Host already validated its registry. A
        // reread in RegisteredOpponent::start would fail before the first move.
        std::fs::write(&registry, "not JSON anymore").unwrap();
        let seed = if seat == 0 { 810_000 } else { u64::MAX };
        let state = finish_game(&host, start_game(&host, seat, seed));
        assert_eq!(state["seed"], seed.to_string());
        assert_eq!(host.get_json("/state").1["seed"], seed.to_string());
        let id = state["session_id"].as_str().unwrap();
        assert_eq!(state["league_completion"]["status"], "inserted", "{state}");
        assert_eq!(
            state["league_completion"]["receipt"]["outcome"]["rating_events"],
            2
        );
        assert_eq!(counts(&paths), (1, 2));
        let occurrence = envelope(&paths, id);
        assert_eq!(occurrence["seed"].as_u64(), Some(seed));
        assert_eq!(occurrence["human"]["participant_id"], human.participant_id);
        assert_eq!(occurrence["human_seat"], seat);
        assert_eq!(
            occurrence["opponent"]["registry_id"],
            "gate-host-write-registry"
        );
        assert_eq!(
            occurrence["opponent"]["runtime_name"],
            splendor_agent::HEURISTIC_AGENT_NAME
        );
        let args: Vec<String> =
            serde_json::from_value(occurrence["opponent"]["args"].clone()).unwrap();
        assert_eq!(
            occurrence["opponent"]["policy_key"],
            resolve_policy_identity(occurrence["opponent"]["program"].as_str(), &args)
                .resolved()
                .unwrap()
                .key()
        );
        let slot = paths.occurrence_dir(id).unwrap();
        let mut names = std::fs::read_dir(&slot)
            .unwrap()
            .map(|e| e.unwrap().file_name())
            .collect::<Vec<_>>();
        names.sort();
        assert_eq!(names, ["occurrence.json", "replay.json"]);
        let legacy = dir
            .join("local-artifacts/m20-human-play")
            .join(format!("{id}.replay.json"));
        assert_eq!(
            std::fs::read(&legacy).unwrap(),
            std::fs::read(slot.join("replay.json")).unwrap()
        );
        let meta: serde_json::Value =
            serde_json::from_slice(&std::fs::read(legacy.with_extension("meta.json")).unwrap())
                .unwrap();
        assert_eq!(meta["opponent"], state["opponent"]);
        assert_eq!(meta["human_seat"], seat);
        assert_eq!(host.get_json(&format!("/replays/{id}")).0, 200);
        assert_eq!(host.get_json("/recent-games").0, 200);
        assert_eq!(
            host.get_json("/league/leaderboard").0,
            200,
            "initial Human booking must refresh unavailable reader"
        );
        let conn = rusqlite::Connection::open(paths.db()).unwrap();
        let events: i64 = conn
            .query_row(
                "SELECT COUNT(*) FROM rating_events WHERE participant_id=?1",
                [&human.participant_id],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(events, 1);
        let (kind, elo): (String, Option<f64>) = conn
            .query_row(
                "SELECT kind,current_elo FROM participants WHERE participant_id=?1",
                [&human.participant_id],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .unwrap();
        assert_eq!(kind, "human");
        assert!(elo.is_some());
        let (code, again) = retry(&host, id, b"");
        assert_eq!(code, 200);
        assert_eq!(again["league_completion"]["status"], "already_present");
        assert_eq!(
            again["league_completion"]["receipt"]["outcome"]["rating_events"],
            0
        );
        assert_eq!(counts(&paths), (1, 2));
        assert_eq!(
            host.get_json("/state").1["league_completion"]["status"],
            "already_present"
        );
    }
}

#[test]
fn human_pending_retry_reads_disk_survives_restart_and_never_spawns() {
    let dir = tmp_dir("human-pending");
    let (root, paths) = new_league(&dir);
    block_db(&paths); // Authored identity is good; derived DB is unavailable BEFORE game creation.
    let executable = dir.join(if cfg!(windows) {
        "human-agent.exe"
    } else {
        "human-agent"
    });
    std::fs::copy(bin(), &executable).unwrap();
    let registry = human_registry(&dir, &executable);
    let host = HostProcess::start_with_registry(&root, &dir, &registry);
    let state = finish_game(&host, start_game(&host, 0, 810_010));
    assert_eq!(state["league_completion"]["status"], "failed");
    assert_eq!(state["league_completion"]["retryable"], true);
    assert!(!state["result"].is_null());
    assert_eq!(state["replay_ready"], true);
    let id = state["session_id"].as_str().unwrap();
    let slot = paths.occurrence_dir(id).unwrap();
    let before = ["occurrence.json", "replay.json"].map(|n| std::fs::read(slot.join(n)).unwrap());
    assert_eq!(
        envelope(&paths, id)["replay_sha256"],
        replay_document_sha256(&before[1])
    );
    drop(host);
    std::fs::remove_file(&executable).unwrap();
    unblock_db(&paths);
    // New Host, no original entry and no original executable. Retry's only input is disk.
    let changed_registry = human_registry(&dir, &bin());
    let mut changed: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&changed_registry).unwrap()).unwrap();
    changed["agents"].as_array_mut().unwrap().remove(0);
    std::fs::write(&changed_registry, serde_json::to_vec(&changed).unwrap()).unwrap();
    let host = HostProcess::start_with_registry(&root, &dir, &changed_registry);
    std::fs::write(slot.join("replay.json"), b"tampered after publish").unwrap();
    let (code, bad) = retry(&host, id, b"");
    assert_eq!(code, 409);
    assert_eq!(bad["league_completion"]["retryable"], false);
    assert_eq!(counts(&paths), (0, 0));
    std::fs::write(slot.join("replay.json"), &before[1]).unwrap();
    let (code, booked) = retry(&host, id, b"");
    assert_eq!(code, 200, "{booked}");
    assert_eq!(booked["league_completion"]["status"], "inserted");
    assert_eq!(counts(&paths), (1, 2));
    assert_eq!(host.get_json("/league/leaderboard").0, 200);
    assert_eq!(
        retry(&host, id, b"").1["league_completion"]["status"],
        "already_present"
    );
    for (i, n) in ["occurrence.json", "replay.json"].iter().enumerate() {
        assert_eq!(std::fs::read(slot.join(n)).unwrap(), before[i]);
    }
    assert_eq!(counts(&paths), (1, 2));
}

#[test]
fn human_gate_h_older_pending_cannot_insert_before_later_runtime_tail() {
    let dir = tmp_dir("human-canonical-tail");
    let (root, paths) = new_league(&dir);
    block_db(&paths);
    let registry = human_registry(&dir, &bin());
    let host = HostProcess::start_with_registry(&root, &dir, &registry);
    let state = finish_game(&host, start_game(&host, 0, 810_020));
    assert_eq!(state["league_completion"]["retryable"], true);
    let id = state["session_id"].as_str().unwrap();
    let saved = std::fs::read(paths.occurrence_dir(id).unwrap().join("occurrence.json")).unwrap();
    let completed_at = envelope(&paths, id)["completed_at"].as_i64().unwrap();
    unblock_db(&paths);
    // Distinct seconds make the canonical ordering deterministic, not dependent
    // on lexical source kinds within a second. No timestamp/evidence rewriting.
    while now_epoch_seconds() <= completed_at {
        std::thread::sleep(Duration::from_millis(20));
    }
    let (code, later) = host.post_json(
        "/league/matches",
        &serde_json::json!({
            "occurrence_id":"human-gate-h-later", "game_id":"gate-h-later", "seed":810_021,
            "seats":["gate-heuristic","gate-random"]
        }),
    );
    assert_eq!(code, 200, "{later}");
    assert_eq!(later["completion_status"], "inserted");
    assert_eq!(counts(&paths), (1, 2));
    for _ in 0..2 {
        let (code, rejected) = retry(&host, id, b"");
        assert_eq!(code, 409, "{rejected}");
        assert_eq!(rejected["league_completion"]["status"], "failed");
        assert_eq!(rejected["league_completion"]["retryable"], false);
        let error = rejected["league_completion"]["error"].as_str().unwrap();
        assert!(
            error.contains("canonical") && error.contains("rebuild"),
            "{error}"
        );
        assert_eq!(counts(&paths), (1, 2));
    }
    assert_eq!(
        std::fs::read(paths.occurrence_dir(id).unwrap().join("occurrence.json")).unwrap(),
        saved
    );
    assert!(!host.get_json("/state").1["result"].is_null());
}

#[test]
fn human_retry_refuses_wrong_session_partial_foreign_and_changed_evidence() {
    let dir = tmp_dir("human-refusals");
    let (root, paths) = new_league(&dir);
    let registry = human_registry(&dir, &bin());
    let host = HostProcess::start_with_registry(&root, &dir, &registry);
    let state = finish_game(&host, start_game(&host, 0, 810_030));
    let id = state["session_id"].as_str().unwrap();
    let slot = paths.occurrence_dir(id).unwrap();
    assert_eq!(retry(&host, id, b"{}").0, 400);
    assert_eq!(retry(&host, "../bad", b"").0, 400);
    assert_eq!(retry(&host, "missing", b"").0, 404);
    let moved = paths.occurrence_dir("wrong-session").unwrap();
    copy_tree(&slot, &moved);
    let (code, wrong) = retry(&host, "wrong-session", b"");
    assert_eq!(code, 409);
    assert!(wrong["league_completion"]["error"]
        .as_str()
        .unwrap()
        .contains("not requested session"));
    for (name, files) in [
        ("partial", vec!["replay.json"]),
        (
            "foreign",
            vec!["replay.json", "occurrence.json", "config.json"],
        ),
        ("nonfile", vec![]),
    ] {
        let dst = paths.occurrence_dir(name).unwrap();
        std::fs::create_dir_all(&dst).unwrap();
        for file in files {
            std::fs::write(dst.join(file), b"{}").unwrap();
        }
        if name == "nonfile" {
            std::fs::create_dir(dst.join("replay.json")).unwrap();
        }
        assert_eq!(retry(&host, name, b"").0, 409);
    }
    let original = std::fs::read(slot.join("occurrence.json")).unwrap();
    let mut changed = envelope(&paths, id);
    changed["completed_at"] = (changed["completed_at"].as_i64().unwrap() + 1).into();
    std::fs::write(
        slot.join("occurrence.json"),
        serde_json::to_vec(&changed).unwrap(),
    )
    .unwrap();
    let (code, conflict) = retry(&host, id, b"");
    assert_eq!(code, 409);
    assert!(conflict["league_completion"]["error"]
        .as_str()
        .unwrap()
        .contains("source conflict"));
    assert_eq!(counts(&paths), (1, 2));
    std::fs::write(slot.join("occurrence.json"), original).unwrap();
}

#[test]
fn human_creation_fails_closed_without_identity_policy_or_handshake() {
    for failure in ["missing", "corrupt", "no-human", "unresolved", "handshake"] {
        let dir = tmp_dir(failure);
        let (root, paths) = new_league(&dir);
        let registry = human_registry(&dir, &bin());
        if failure == "unresolved" || failure == "handshake" {
            let mut value: serde_json::Value =
                serde_json::from_slice(&std::fs::read(&registry).unwrap()).unwrap();
            if failure == "unresolved" {
                value["agents"][0]["command"]["args"] = serde_json::json!(["--version"]);
            } else {
                value["agents"][0]["runtime_name"] = "wrong-hello".into();
            }
            std::fs::write(&registry, serde_json::to_vec(&value).unwrap()).unwrap();
        }
        let host = HostProcess::start_with_registry(&root, &dir, &registry);
        match failure {
            "missing" => std::fs::remove_file(paths.identity()).unwrap(),
            "corrupt" => std::fs::write(paths.identity(), b"broken").unwrap(),
            "no-human" => IdentityManifestV1::new().save(paths.identity()).unwrap(),
            _ => {}
        }
        let request =
            serde_json::json!({"agent_id":"gate-heuristic","human_seat":0,"seed":810_040});
        let (code, rejected) = host.post_json("/games", &request);
        assert_eq!(code, 400, "{failure}: {rejected}");
        assert_eq!(host.get_json("/state").0, 400);
        assert_eq!(counts(&paths), (0, 0));
        assert!(!paths.dir().join("occurrences").exists());
        assert!(!dir.join("local-artifacts/m20-human-play").exists());
        for key in [
            "participant_id",
            "policy_key",
            "runtime_name",
            "command",
            "result",
            "replay",
        ] {
            let mut malicious = request.clone();
            malicious[key] = "forged".into();
            let (code, body) = host.post_json("/games", &malicious);
            assert_eq!(code, 400);
            assert!(body["error"].as_str().unwrap().contains("unknown field"));
        }
    }
}

#[test]
fn human_terminal_survives_legacy_or_occurrence_publication_failure() {
    for failure in ["legacy", "occurrence"] {
        let dir = tmp_dir(failure);
        let (root, paths) = new_league(&dir);
        let registry = human_registry(&dir, &bin());
        let host = HostProcess::start_with_registry(&root, &dir, &registry);
        let state = start_game(&host, 0, 810_050);
        let id = state["session_id"].as_str().unwrap().to_string();
        let legacy = dir
            .join("local-artifacts/m20-human-play")
            .join(format!("{id}.replay.json"));
        let slot = paths.occurrence_dir(&id).unwrap();
        if failure == "legacy" {
            std::fs::create_dir_all(legacy.with_extension("meta.json")).unwrap();
        } else {
            std::fs::create_dir_all(&slot).unwrap();
            std::fs::write(slot.join("replay.json"), b"do not overwrite").unwrap();
        }
        let terminal = finish_game(&host, state);
        assert!(!terminal["result"].is_null());
        assert_eq!(terminal["league_completion"]["status"], "failed");
        assert_eq!(terminal["league_completion"]["retryable"], false);
        assert_eq!(host.get_json("/state").0, 200);
        assert_eq!(host.get_json("/archive").0, 200);
        assert_eq!(counts(&paths), (0, 0));
        assert!(!slot.join("occurrence.json").exists());
        if failure == "legacy" {
            assert!(!slot.exists());
            assert!(!legacy.exists());
        } else {
            assert!(legacy.is_file());
            assert!(legacy.with_extension("meta.json").is_file());
            assert_eq!(
                std::fs::read(slot.join("replay.json")).unwrap(),
                b"do not overwrite"
            );
        }
    }
}

#[test]
fn human_identity_is_frozen_at_creation_not_reloaded_at_terminal() {
    let dir = tmp_dir("human-manifest-drift");
    let (root, paths) = new_league(&dir);
    let registry = human_registry(&dir, &bin());
    let host = HostProcess::start_with_registry(&root, &dir, &registry);
    let original = std::fs::read(paths.identity()).unwrap();
    let before = IdentityManifestV1::load(paths.identity()).unwrap().unwrap();
    let started = start_game(&host, 0, 810_070);
    let id = started["session_id"].as_str().unwrap().to_string();
    let mut replacement = IdentityManifestV1::new();
    replacement.ensure_local_human("Not the player who started");
    replacement.save(paths.identity()).unwrap();
    let terminal = finish_game(&host, started);
    assert_eq!(terminal["league_completion"]["status"], "failed");
    assert_eq!(terminal["league_completion"]["retryable"], false);
    let evidence = envelope(&paths, &id);
    assert_eq!(
        evidence["human"]["participant_id"],
        before.local_human.as_ref().unwrap().participant_id
    );
    assert_eq!(
        evidence["human"]["identity_manifest_hash"],
        before.hash().unwrap()
    );
    assert_eq!(counts(&paths), (0, 0));
    // The opener projected the replacement identity into an initially empty DB
    // before the builder rejected this occurrence. Restoring the manifest alone
    // does NOT authorize replacing that DB identity; the existing guard requires
    // rebuild. Do not promise eventual insertion for identity failures either.
    std::fs::write(paths.identity(), original).unwrap();
    let (_, retry_result) = retry(&host, &id, b"");
    assert_eq!(retry_result["league_completion"]["status"], "failed");
    assert_eq!(retry_result["league_completion"]["retryable"], false);
    assert!(retry_result["league_completion"]["error"]
        .as_str()
        .unwrap()
        .contains("rebuild"));
    assert_eq!(counts(&paths), (0, 0));
}

#[test]
fn standalone_human_play_remains_casual_even_beside_a_valid_league() {
    for registered in [false, true] {
        let dir = tmp_dir("human-standalone");
        let (root, paths) = new_league(&dir);
        let registry = human_registry(&dir, &bin());
        let port = free_port();
        let mut command = Command::new(bin());
        command.current_dir(&root).args([
            "human-play-server",
            "--seed",
            "810060",
            "--human-seat",
            "0",
            "--port",
            &port.to_string(),
        ]);
        if registered {
            command.args([
                "--registry",
                registry.to_str().unwrap(),
                "--agent-id",
                "gate-heuristic",
            ]);
        } else {
            command.args(["--opponent", "heuristic"]);
        }
        let child = command
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        let mut host = HostProcess { child, port };
        host.await_ready().unwrap();
        let terminal = finish_game(&host, host.get_json("/state").1);
        assert!(!terminal["result"].is_null());
        assert!(terminal["league_completion"].is_null());
        assert_eq!(counts(&paths), (0, 0));
        assert!(!paths.dir().join("occurrences").exists());
        let id = terminal["session_id"].as_str().unwrap();
        assert!(root
            .join("local-artifacts/m20-human-play")
            .join(format!("{id}.replay.json"))
            .is_file());
    }
}
