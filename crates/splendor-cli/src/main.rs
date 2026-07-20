use std::fs;
use std::time::Instant;

use clap::{Parser, Subcommand};
use rand::rngs::SmallRng;
use rand::{Rng, SeedableRng};
use splendor_core::{
    full_state_hash, observation_hash, play_random_game, ruleset_fingerprint, visible_events,
    Action, Audience, FullState, GameConfig, PlayerId, VisibleEvent, ENGINE_VERSION,
};
use splendor_protocol::{ClientMessage, ClientMeta, Meta, ServerMessage, PROTOCOL_VERSION};

#[derive(Parser)]
#[command(name = "splendor", about = "Splendor rules engine CLI (Phase 0)")]
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
    /// Verify that replaying recorded actions reproduces the final hash
    ReplayCheck {
        #[arg(long, default_value_t = 2)]
        players: u8,
        #[arg(long, default_value_t = 42)]
        seed: u64,
    },
    /// Smoke-test NDJSON protocol message encoding against a live state
    ProtocolDemo {
        #[arg(long, default_value_t = 42)]
        seed: u64,
    },
    /// Generate golden protocol transcripts under fixtures/protocol/v0.2/
    GenFixtures {
        #[arg(long, default_value = "fixtures/protocol/v0.2")]
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
        Commands::ReplayCheck { players, seed } => cmd_replay_check(players, seed),
        Commands::ProtocolDemo { seed } => cmd_protocol_demo(seed),
        Commands::GenFixtures { out_dir } => cmd_gen_fixtures(&out_dir),
    }
}

fn cmd_bench(games: u32, players: u8, seed: u64) {
    let mut rng = SmallRng::seed_from_u64(seed);
    let start = Instant::now();
    let mut total_plies = 0u64;
    let mut wins = vec![0u64; players as usize];

    for _ in 0..games {
        let s = rng.gen::<u64>();
        let state = play_random_game(GameConfig {
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

fn cmd_replay_check(players: u8, seed: u64) {
    let (mut state, _) = FullState::new(GameConfig {
        player_count: players,
        seed,
        ..Default::default()
    })
    .unwrap();

    let mut actions: Vec<Action> = Vec::new();
    let mut rng = SmallRng::seed_from_u64(seed ^ 0x1111);
    while !state.is_terminal() {
        let acts = state.legal_actions();
        let a = acts[rng.gen_range(0..acts.len())];
        actions.push(a);
        state.apply(a).unwrap();
    }
    let expected = full_state_hash(&state).as_str().to_string();

    let (mut replay, _) = FullState::new(GameConfig {
        player_count: players,
        seed,
        ..Default::default()
    })
    .unwrap();
    for a in &actions {
        replay.apply(*a).unwrap();
    }
    let got = full_state_hash(&replay).as_str().to_string();
    assert_eq!(expected, got, "replay hash mismatch");
    println!("ok actions={} final_hash={}", actions.len(), expected);
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
        meta: Meta::new(&game_id, 1)
            .with_recipient(PlayerId(0))
            .with_observation_hash(observation_hash(&obs)),
        observation: obs,
    };
    println!("{}", obs_msg.to_json_line().unwrap());

    let req = ServerMessage::RequestAction {
        meta: Meta::new(&game_id, 2)
            .with_recipient(PlayerId(0))
            .with_observation_hash(observation_hash(&state.observation(PlayerId(0)))),
        deadline_ms: 1000,
        legal_actions: state.legal_actions(),
    };
    println!("{}", req.to_json_line().unwrap());

    let action = state.legal_actions()[0];
    let client = ClientMessage::Action {
        meta: ClientMeta::new(&game_id).with_request(1),
        action,
    };
    println!("{}", serde_json::to_string(&client).unwrap());
}

/// Build a golden protocol transcript (NDJSON) for a sequence of server messages
/// plus a single client action, writing it to `<out_dir>/<name>.ndjson`.
///
/// The transcript is produced by the referee and projected to a spectator, so it
/// must contain NO hidden card identities and NO full state hash.
fn write_transcript(name: &str, out_dir: &str, lines: &[String]) {
    fs::create_dir_all(out_dir).expect("mkdir fixtures dir");
    let path = format!("{out_dir}/{name}.ndjson");
    fs::write(&path, lines.join("\n") + "\n").expect("write fixture");
    println!("wrote {path} ({} lines)", lines.len());
}

fn cmd_gen_fixtures(out_dir: &str) {
    // --- normal-game.ndjson: setup + first request for player 0 ---
    {
        let (state, _) = FullState::new(GameConfig::default()).unwrap();
        let game_id = "golden-normal";
        let mut lines = Vec::new();
        lines.push(
            ServerMessage::hello(
                game_id,
                splendor_core::RULESET_BASE_V1.0,
                splendor_core::CATALOG_VERSION,
                ruleset_fingerprint(&state.ruleset),
            )
            .to_json_line()
            .unwrap(),
        );
        let obs0 = state.observation(PlayerId(0));
        lines.push(
            ServerMessage::Observation {
                meta: Meta::new(game_id, 1)
                    .with_recipient(PlayerId(0))
                    .with_observation_hash(observation_hash(&obs0)),
                observation: obs0,
            }
            .to_json_line()
            .unwrap(),
        );
        lines.push(
            ServerMessage::RequestAction {
                meta: Meta::new(game_id, 2)
                    .with_recipient(PlayerId(0))
                    .with_observation_hash(observation_hash(&state.observation(PlayerId(0)))),
                deadline_ms: 1000,
                legal_actions: state.legal_actions(),
            }
            .to_json_line()
            .unwrap(),
        );
        write_transcript("normal-game", out_dir, &lines);
    }

    // --- blind-reserve.ndjson: a blind deck reserve, projected to the OPPONENT ---
    // The opponent's transcript must NOT reveal the reserved card identity.
    {
        let (mut state, _) = FullState::new(GameConfig {
            seed: 7,
            ..Default::default()
        })
        .unwrap();
        let reserve = state
            .legal_actions()
            .into_iter()
            .find(|a| matches!(a, Action::ReserveDeck { .. }))
            .expect("reserve deck is legal at start");
        let step = state.apply(reserve).expect("apply reserve");

        // Project the referee log to the opponent (player 1) and serialize.
        let visible: Vec<VisibleEvent> =
            visible_events(&step.events, Audience::Player(PlayerId(1)));
        let game_id = "golden-blind";
        let mut lines = Vec::new();
        lines.push(
            ServerMessage::hello(
                game_id,
                splendor_core::RULESET_BASE_V1.0,
                splendor_core::CATALOG_VERSION,
                ruleset_fingerprint(&state.ruleset),
            )
            .to_json_line()
            .unwrap(),
        );
        for ev in &visible {
            // Serialize each already-projected event as a protocol message.
            let server_seq = lines.len() as u64;
            lines.push(
                ServerMessage::event(Meta::new(game_id, server_seq), ev.clone())
                    .to_json_line()
                    .unwrap(),
            );
        }
        write_transcript("blind-reserve", out_dir, &lines);
    }
}
