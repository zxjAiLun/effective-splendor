use std::fs;
use std::time::Instant;

use clap::{Parser, Subcommand};
use rand::rngs::SmallRng;
use rand::{Rng, SeedableRng};
use splendor_core::{
    full_state_hash, observation_hash, play_random_game_with_stats, ruleset_fingerprint,
    visible_events, Action, Audience, FullState, GameConfig, PlayerId, ENGINE_VERSION,
};
use splendor_protocol::{
    to_ndjson, ClientMessage, ClientRequestMeta, ObservationMeta, RecipientMeta, RequestMeta,
    ServerMessage, PROTOCOL_VERSION,
};
use splendor_replay::{record_random_game, verify_replay, ReplayV1};

#[derive(Parser)]
#[command(name = "splendor", about = "Splendor rules engine CLI")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    /// Print engine / protocol / catalog versions
    Version,
    /// Run random self-play games and report stats
    Bench {
        #[arg(long, default_value_t = 1000)]
        games: u32,
        #[arg(long, default_value_t = 2)]
        players: u8,
        #[arg(long, default_value_t = 0)]
        seed: u64,
    },
    /// Play one random game and print the result JSON
    Play {
        #[arg(long, default_value_t = 2)]
        players: u8,
        #[arg(long, default_value_t = 42)]
        seed: u64,
        #[arg(long, default_value_t = false)]
        verbose: bool,
    },
    /// Record a deterministic random game to a replay v1 file
    RecordReplay {
        #[arg(long, default_value_t = 2)]
        players: u8,
        #[arg(long, default_value_t = 42)]
        seed: u64,
        #[arg(long, default_value_t = 1001)]
        action_seed: u64,
        #[arg(long)]
        out: String,
    },
    /// Load and strictly verify a replay v1 file
    VerifyReplay {
        #[arg(long)]
        input: String,
    },
    /// Smoke-test NDJSON protocol message encoding against a live state
    ProtocolDemo {
        #[arg(long, default_value_t = 42)]
        seed: u64,
    },
    /// Generate golden protocol transcripts under fixtures/protocol/v0.4/
    GenFixtures {
        #[arg(long, default_value = "fixtures/protocol/v0.4")]
        out_dir: String,
    },
}

fn main() {
    let cli = Cli::parse();
    match cli.command {
        Commands::Version => {
            println!("engine={}", ENGINE_VERSION);
            println!("protocol={}", PROTOCOL_VERSION);
            println!("catalog={}", splendor_core::CATALOG_VERSION);
            println!("ruleset={}", splendor_core::RULESET_BASE_V1.0);
        }
        Commands::Bench {
            games,
            players,
            seed,
        } => cmd_bench(games, players, seed),
        Commands::Play {
            players,
            seed,
            verbose,
        } => cmd_play(players, seed, verbose),
        Commands::RecordReplay {
            players,
            seed,
            action_seed,
            out,
        } => cmd_record_replay(players, seed, action_seed, &out),
        Commands::VerifyReplay { input } => cmd_verify_replay(&input),
        Commands::ProtocolDemo { seed } => cmd_protocol_demo(seed),
        Commands::GenFixtures { out_dir } => cmd_gen_fixtures(&out_dir),
    }
}

fn cmd_bench(games: u32, players: u8, seed: u64) {
    let mut rng = SmallRng::seed_from_u64(seed);
    let start = Instant::now();
    let mut total_plies = 0u64;
    let mut total_legal_actions = 0u64;
    let mut total_decisions = 0u64;
    let mut max_legal_actions = 0usize;
    let mut wins = vec![0u64; players as usize];

    for _ in 0..games {
        let s = rng.gen::<u64>();
        let (state, stats) = play_random_game_with_stats(GameConfig {
            player_count: players,
            seed: s,
            ..Default::default()
        })
        .unwrap_or_else(|e| panic!("game failed seed={s}: {e}"));
        total_plies += state
            .log
            .iter()
            .filter(|e| matches!(e, splendor_core::GameEvent::ActionApplied { .. }))
            .count() as u64;
        total_legal_actions += stats.total_legal_actions;
        total_decisions += stats.decisions;
        max_legal_actions = max_legal_actions.max(stats.max_legal_actions);
        if let Some(res) = &state.result {
            for w in &res.winners {
                wins[w.index()] += 1;
            }
        }
    }

    let elapsed = start.elapsed().as_secs_f64().max(1e-9);
    println!("games={}", games);
    println!("players={}", players);
    println!("elapsed_s={:.3}", elapsed);
    println!("games_per_s={:.1}", games as f64 / elapsed);
    println!(
        "avg_actions_per_game={:.1}",
        total_plies as f64 / games as f64
    );
    println!("actions_per_s={:.1}", total_plies as f64 / elapsed);
    println!(
        "avg_legal_actions_per_decision={:.2}",
        total_legal_actions as f64 / total_decisions.max(1) as f64
    );
    println!("max_legal_actions_seen={max_legal_actions}");
    println!("wins_by_seat={:?}", wins);
}

fn cmd_play(players: u8, seed: u64, verbose: bool) {
    let (mut state, setup) = FullState::new(GameConfig {
        player_count: players,
        seed,
        ..Default::default()
    })
    .expect("setup");
    if verbose {
        eprintln!("setup_hash={}", setup.state_hash_after.as_str());
    }

    let mut rng = SmallRng::seed_from_u64(seed ^ 0xA5A5_A5A5_A5A5_A5A5);
    while !state.is_terminal() {
        let acts = state.legal_actions();
        let action = acts[rng.gen_range(0..acts.len())];
        let step = state.apply(action).expect("apply");
        if verbose {
            eprintln!(
                "p{} {:?} hash={}",
                state.current_player.0, action, step.state_hash_after
            );
        }
    }

    let result = state.result.as_ref().expect("result");
    println!(
        "{}",
        serde_json::to_string_pretty(&serde_json::json!({
            "seed": seed,
            "players": players,
            "scores": result.scores,
            "ranks": result.ranks,
            "winners": result.winners.iter().map(|p| p.0).collect::<Vec<_>>(),
            "full_hash": full_state_hash(&state).as_str(),
            "actions": state.log.iter().filter(|e| {
                matches!(e, splendor_core::GameEvent::ActionApplied { .. })
            }).count(),
        }))
        .unwrap()
    );
}

fn cmd_record_replay(players: u8, seed: u64, action_seed: u64, out: &str) {
    let (_state, replay) = record_random_game(players, seed, action_seed).unwrap_or_else(|e| {
        eprintln!("record failed: {e}");
        std::process::exit(1);
    });
    let json = serde_json::to_string_pretty(&replay).expect("serialize replay");
    let mut json = json;
    json.push('\n');
    fs::write(out, json).unwrap_or_else(|e| {
        eprintln!("write failed: {e}");
        std::process::exit(1);
    });
    println!("ok");
    println!("out={out}");
    println!("steps={}", replay.steps.len());
    println!("final_hash={}", replay.final_state_hash.as_str());
}

fn cmd_verify_replay(input: &str) {
    let raw = match fs::read_to_string(input) {
        Ok(raw) => raw,
        Err(e) => {
            eprintln!("read failed: {e}");
            std::process::exit(1);
        }
    };
    let replay: ReplayV1 = match serde_json::from_str(&raw) {
        Ok(replay) => replay,
        Err(e) => {
            eprintln!("parse error: {e}");
            std::process::exit(1);
        }
    };
    match verify_replay(&replay) {
        Ok(verified) => {
            println!("ok");
            println!("format_version={}", replay.version);
            println!("steps={}", verified.steps);
            println!("final_hash={}", verified.final_state_hash);
            println!("reason={}", result_reason_str(&verified.result));
            println!("winners={}", format_winners(&verified.result));
        }
        Err(e) => {
            eprintln!("verify error: {e}");
            std::process::exit(1);
        }
    }
}

fn result_reason_str(result: &splendor_replay::ReplayGameResultV1) -> &'static str {
    match result.reason {
        splendor_replay::ReplayTerminalReason::PrestigeThreshold => "prestige_threshold",
        splendor_replay::ReplayTerminalReason::Stalemate => "stalemate",
    }
}

fn format_winners(result: &splendor_replay::ReplayGameResultV1) -> String {
    result
        .winners
        .iter()
        .map(|w| w.to_string())
        .collect::<Vec<_>>()
        .join(",")
}

fn cmd_protocol_demo(seed: u64) {
    let (state, _) = FullState::new(GameConfig {
        seed,
        ..Default::default()
    })
    .unwrap();
    let game_id = format!("demo-{seed}");
    let hello = ServerMessage::hello(
        &game_id,
        splendor_core::RULESET_BASE_V1.0,
        splendor_core::CATALOG_VERSION,
        ruleset_fingerprint(&state.ruleset),
    );
    println!("{}", hello.to_json_line().unwrap());

    let obs = state.observation(PlayerId(0));
    let obs_msg = ServerMessage::Observation {
        meta: ObservationMeta::new(&game_id, 1, PlayerId(0), observation_hash(&obs)),
        observation: obs,
    };
    println!("{}", obs_msg.to_json_line().unwrap());

    let req = ServerMessage::RequestAction {
        meta: RequestMeta::new(
            &game_id,
            2,
            PlayerId(0),
            1,
            observation_hash(&state.observation(PlayerId(0))),
        ),
        deadline_ms: 1000,
        legal_actions: state.legal_actions(),
    };
    println!("{}", req.to_json_line().unwrap());

    let action = state.legal_actions()[0];
    let client = ClientMessage::Action {
        meta: ClientRequestMeta::new(&game_id, 1),
        action,
    };
    println!("{}", serde_json::to_string(&client).unwrap());
}

/// Build a complete player-scoped server transcript. State construction and
/// referee-event projection stay in the host/fixture layer; only the final
/// `ServerMessage` values cross into the protocol serializer.
fn server_transcript(
    game_id: &str,
    state: &FullState,
    events: &[splendor_core::RefereeEvent],
    recipient: PlayerId,
    audience: Audience,
    request_id: u64,
) -> String {
    let observation = state.observation(recipient);
    let observation_hash = observation_hash(&observation);
    let mut messages = vec![
        ServerMessage::hello(
            game_id,
            state.ruleset.id.0,
            state.ruleset.catalog_version,
            ruleset_fingerprint(&state.ruleset),
        ),
        ServerMessage::GameStart {
            meta: RecipientMeta::new(game_id, 1, recipient),
            player_count: state.player_count(),
            seed_commitment: format!("fixture-commitment-{game_id}"),
        },
        ServerMessage::Observation {
            meta: ObservationMeta::new(game_id, 2, recipient, observation_hash.clone()),
            observation,
        },
    ];

    for event in visible_events(events, audience) {
        let server_seq = messages.len() as u64;
        messages.push(ServerMessage::event(
            RecipientMeta::new(game_id, server_seq, recipient),
            event,
        ));
    }

    let server_seq = messages.len() as u64;
    messages.push(ServerMessage::RequestAction {
        meta: RequestMeta::new(game_id, server_seq, recipient, request_id, observation_hash),
        deadline_ms: 1000,
        legal_actions: state.legal_actions(),
    });

    to_ndjson(&messages)
}

/// Pure deterministic normal-game fixture generator.
fn normal_golden_transcript() -> String {
    let (state, setup) = FullState::new(GameConfig::default()).expect("fixture setup");
    server_transcript(
        "golden-normal",
        &state,
        &setup.events,
        PlayerId(0),
        Audience::Player(PlayerId(0)),
        1,
    )
}

/// Pure deterministic blind-reserve fixture generator for a selected player.
fn blind_reserve_transcript(audience: Audience) -> String {
    let recipient = match audience {
        Audience::Player(player) => player,
        _ => panic!("blind fixture requires a player audience"),
    };
    let (mut state, setup) = FullState::new(GameConfig {
        seed: 7,
        ..Default::default()
    })
    .expect("fixture setup");
    let reserve = state
        .legal_actions()
        .into_iter()
        .find(|action| matches!(action, Action::ReserveDeck { .. }))
        .expect("reserve deck is legal at start");
    let step = state.apply(reserve).expect("apply reserve");
    let mut events = setup.events;
    events.extend(step.events);

    server_transcript("golden-blind", &state, &events, recipient, audience, 2)
}

/// Write a deterministic protocol transcript to `<out_dir>/<name>.ndjson`.
fn write_transcript(name: &str, out_dir: &str, transcript: String) {
    fs::create_dir_all(out_dir).expect("mkdir fixtures dir");
    let path = format!("{out_dir}/{name}.ndjson");
    let line_count = transcript.lines().count();
    fs::write(&path, transcript).expect("write fixture");
    println!("wrote {path} ({line_count} lines)");
}

fn cmd_gen_fixtures(out_dir: &str) {
    write_transcript("normal-game", out_dir, normal_golden_transcript());
    write_transcript(
        "blind-reserve",
        out_dir,
        blind_reserve_transcript(splendor_core::Audience::Player(PlayerId(1))),
    );
}
