//! M54 tests: hand-built decisions and an explicitly supplied EXISTING replay.
use super::*;
use splendor_agent::{PublicRequestMeta, StableRng};
use splendor_core::{observation_hash, FullState, GameConfig, Phase, Ruleset};

fn initial() -> FullState {
    FullState::new(GameConfig {
        player_count: 2,
        seed: 7,
        ruleset: Ruleset::base_v1(),
    })
    .unwrap()
    .0
}

fn fixture_row() -> DecisionRow {
    let state = initial();
    let actor = state.current_player;
    let observation = state.observation(actor);
    let visible_history = visible_events(&state.log, Audience::Player(actor));
    let legal_actions = state.legal_actions();
    let request = RequestBody {
        format: REQUEST_FORMAT.into(),
        behavior_id: "a".repeat(64),
        job_id: "fixture".into(),
        game_id: "synthetic-game".into(),
        actor: actor.0,
        request_id: 1,
        decision_index: 0,
        catalog_fingerprint: catalog_fingerprint(),
        input: encode(&observation, &visible_history, &legal_actions).unwrap(),
    };
    let mut probabilities = vec![0.0; legal_actions.len()];
    probabilities[0] = 1.0;
    let response = PpoResponse {
        format: RESPONSE_FORMAT.into(),
        behavior_id: request.behavior_id.clone(),
        job_id: request.job_id.clone(),
        game_id: request.game_id.clone(),
        actor: actor.0,
        request_id: 1,
        decision_index: 0,
        chosen_index: 0,
        log_prob: 0.0,
        value: 0.5,
        style_value: 0.0,
        probabilities,
    };
    DecisionRow {
        format: DECISION_FORMAT.into(),
        request,
        response,
        observation,
        visible_history,
        chosen_action: legal_actions[0],
        legal_actions,
    }
}

#[test]
fn nested_duplicate_missing_and_unknown_fields_rejected() {
    for bad in [
        br#"{"a":1,"a":2}"#.as_slice(),
        br#"{"a":[{"x":null,"x":null}]}"#,
    ] {
        assert!(strict_json_keys(bad).is_err());
    }
    let row = fixture_row();
    assert!(parse_decision_row(&serde_json::to_vec(&row).unwrap()).is_ok());
    let mut value = serde_json::to_value(&row).unwrap();
    value["observation"]["seed"] = json!(7);
    assert!(parse_decision_row(&serde_json::to_vec(&value).unwrap()).is_err());
    let mut value = serde_json::to_value(&row).unwrap();
    value["observation"]
        .as_object_mut()
        .unwrap()
        .remove("private");
    assert!(parse_decision_row(&serde_json::to_vec(&value).unwrap()).is_err());
    let mut value = serde_json::to_value(&row).unwrap();
    value["request"]["input"]["targets"][0] = json!(true);
    assert!(parse_decision_row(&serde_json::to_vec(&value).unwrap()).is_err());
}

#[test]
fn hidden_deck_order_does_not_change_features() {
    let a = initial();
    let mut b = a.clone();
    b.decks[0].swap(0, 1);
    let actor = a.current_player;
    let project = |s: &FullState| {
        encode(
            &s.observation(actor),
            &visible_events(&s.log, Audience::Player(actor)),
            &s.legal_actions(),
        )
        .unwrap()
    };
    assert_eq!(project(&a), project(&b));
}

#[test]
fn bounded_socket_roundtrip_and_nonnewline_rejected() {
    for with_newline in [true, false] {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let endpoint = match listener.local_addr().unwrap() {
            SocketAddr::V4(a) => a,
            _ => unreachable!(),
        };
        let row = fixture_row();
        let response = row.response.clone();
        let server = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut bytes = Vec::new();
            stream.read_to_end(&mut bytes).unwrap();
            let request: Value = serde_json::from_slice(&bytes).unwrap();
            assert_eq!(request["token"], "test-token");
            let mut out = serde_json::to_vec(&response).unwrap();
            if with_newline {
                out.push(b'\n');
            }
            stream.write_all(&out).unwrap();
        });
        let result = exchange(endpoint, "test-token", &row.request);
        assert_eq!(result.is_ok(), with_newline);
        server.join().unwrap();
    }
}

#[test]
#[ignore = "requires an ephemeral Python behavior service and scratch output"]
fn python_service_synthetic_decisions() {
    let endpoint = validate_endpoint(&std::env::var("M54_TEST_ENDPOINT").unwrap()).unwrap();
    let behavior_id = std::env::var("M54_TEST_BEHAVIOR").unwrap();
    let path = std::env::var("M54_TEST_SIDECAR").unwrap();
    let mut policy = RemotePolicy {
        endpoint,
        token: "m54-engineering-token".into(),
        behavior_id,
        job_id: "python-rust-fixture".into(),
        decision_index: 0,
        sidecar: create_new_writer(Path::new(&path)).unwrap(),
    };
    let mut state = initial();
    let mut rng = StableRng::new(1);
    for i in 0..2 {
        if i == 1 {
            // Hand-built ChooseNoble phase; no match or trajectory is generated.
            state.phase = Phase::ChooseNoble;
            state.pending_nobles = state.nobles.iter().take(2).copied().collect();
        }
        let actor = state.current_player;
        let observation = state.observation(actor);
        let legal = state.legal_actions();
        let history = visible_events(&state.log, Audience::Player(actor));
        let meta = PublicRequestMeta {
            game_id: "synthetic-game".into(),
            recipient_seat: actor,
            request_id: i + 1,
            observation_hash: observation_hash(&observation),
        };
        let chosen = policy
            .choose_action(DecisionContext {
                observation,
                visible_history: &history,
                legal_actions: &legal,
                meta,
                rng: &mut rng,
            })
            .unwrap();
        assert!(legal.contains(&chosen));
    }
    drop(policy);
    let text = fs::read_to_string(path).unwrap();
    assert_eq!(text.lines().count(), 2);
    assert!(!text.contains("m54-engineering-token"));
    for line in text.lines() {
        parse_decision_row(line.as_bytes()).unwrap();
    }
}

#[test]
#[ignore = "audits an existing caller-supplied replay; never generates a game"]
fn existing_replay_audit_and_tamper_rejection() {
    let replay_path = std::env::var("M54_TEST_REPLAY").unwrap();
    let directory = std::env::var("M54_TEST_AUDIT_DIR").unwrap();
    let directory = Path::new(&directory);
    fs::create_dir(directory).unwrap();
    let replay: ReplayV1 = serde_json::from_slice(&fs::read(&replay_path).unwrap()).unwrap();
    let trace = verify_replay_trace(&replay).unwrap();
    for actor in 0..2 {
        let mut rows = Vec::new();
        for step in trace
            .positions
            .iter()
            .filter(|s| s.recorded_actor.0 == actor)
        {
            let observation = step.state.observation(step.recorded_actor);
            let visible_history =
                visible_events(&step.state.log, Audience::Player(step.recorded_actor));
            let legal_actions = step.state.legal_actions();
            let chosen_index = legal_actions
                .iter()
                .position(|a| *a == step.recorded_action)
                .unwrap();
            let decision_index = rows.len() as u64;
            let request_id = u64::from(step.ply) + 1;
            let request = RequestBody {
                format: REQUEST_FORMAT.into(),
                behavior_id: "a".repeat(64),
                job_id: "existing-replay-fixture".into(),
                game_id: "offline-audit-fixture".into(),
                actor,
                request_id,
                decision_index,
                catalog_fingerprint: catalog_fingerprint(),
                input: encode(&observation, &visible_history, &legal_actions).unwrap(),
            };
            // Fabricated one-hot distribution ONLY tests the rules/sidecar join.
            // It is not claimed to be an on-policy learner batch.
            let mut probabilities = vec![0.0; legal_actions.len()];
            probabilities[chosen_index] = 1.0;
            let response = PpoResponse {
                format: RESPONSE_FORMAT.into(),
                behavior_id: request.behavior_id.clone(),
                job_id: request.job_id.clone(),
                game_id: request.game_id.clone(),
                actor,
                request_id,
                decision_index,
                chosen_index,
                log_prob: 0.0,
                value: 0.5,
                style_value: 0.0,
                probabilities,
            };
            rows.push(DecisionRow {
                format: DECISION_FORMAT.into(),
                request,
                response,
                observation,
                visible_history,
                legal_actions,
                chosen_action: step.recorded_action,
            });
        }
        let sidecar = directory.join(format!("actor{actor}.jsonl"));
        let output = directory.join(format!("actor{actor}-audit.json"));
        let mut data = Vec::new();
        for row in &rows {
            data.extend(serde_json::to_vec(row).unwrap());
            data.push(b'\n');
        }
        fs::write(&sidecar, &data).unwrap();
        let args = vec![
            "--replay".into(),
            replay_path.clone(),
            "--sidecar".into(),
            sidecar.to_string_lossy().into(),
            "--output".into(),
            output.to_string_lossy().into(),
            "--behavior-id".into(),
            "a".repeat(64),
            "--job-id".into(),
            "existing-replay-fixture".into(),
            "--actor".into(),
            actor.to_string(),
        ];
        audit_command(&args).unwrap();
        let audit: Value = serde_json::from_slice(&fs::read(&output).unwrap()).unwrap();
        assert_eq!(audit["decisions"].as_array().unwrap().len(), rows.len());
        assert_eq!(
            audit["result"],
            serde_json::to_value(&replay.result).unwrap()
        );
        let mut bad_args = args.clone();
        let bad_output = directory.join(format!("actor{actor}-invalid.json"));
        bad_args[5] = bad_output.to_string_lossy().into();
        data.extend(b"{}\n");
        fs::write(&sidecar, &data).unwrap();
        assert!(audit_command(&bad_args).is_err());
        assert!(!bad_output.exists());
        let mut missing = Vec::new();
        for row in rows.iter().skip(1) {
            missing.extend(serde_json::to_vec(row).unwrap());
            missing.push(b'\n');
        }
        fs::write(&sidecar, missing).unwrap();
        assert!(audit_command(&bad_args).is_err());
        assert!(!bad_output.exists());
    }
}
