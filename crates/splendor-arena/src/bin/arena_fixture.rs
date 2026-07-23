//! Cross-platform agent fixture binary for arena transport and process tests.
//!
//! Two command families:
//! - Top-level subcommands (`echo`, `early-exit`, `oversize-line`, `stderr-flood`,
//!   `sleep`, ...) are used by the Commit 2 transport tests and must stay.
//! - `agent <mode> [options]` is the protocol-speaking test agent used by the
//!   Commit 4 process / information-isolation tests. It speaks real NDJSON over
//!   stdin/stdout and never uses a shell.
//!
//! Supported `agent` modes:
//! `scripted`, `handshake-timeout`, `action-timeout`, `malformed-action`,
//! `wrong-protocol`, `wrong-game-id`, `wrong-request-id`, `illegal-action`,
//! `duplicate-hello`, `unsolicited-message`, `early-exit`, `oversize-handshake`,
//! `oversize-action`, `non-utf8-action`, `scripted-stderr-flood`.
//!
//! Options:
//! - `--script <path>` : JSON array of [`Action`] the `scripted` agent replays
//!   by `request_id - 1`.
//! - `--transcript <prefix>` : each received raw server NDJSON line is flushed
//!   to `<prefix>.received.ndjson` (test-only; never sent to the report).

use std::fs::File;
use std::io::{self, BufRead, Write};
use std::path::PathBuf;
use std::thread;

use splendor_core::{Action, Tier};
use splendor_protocol::{
    parse_server_line, ClientMessage, ClientMeta, ClientRequestMeta, ServerMessage,
};

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let sub = args.get(1).map(String::as_str).unwrap_or("");
    match sub {
        "echo" => fixture_echo(),
        "echo-crlf" => fixture_echo_crlf(),
        "early-exit" => std::process::exit(0),
        "oversize-line" => fixture_oversize(),
        "oversize-then-valid" => fixture_oversize_then_valid(),
        "stderr-flood" => fixture_stderr_flood(),
        "sleep" => fixture_sleep(args.get(2)),
        "agent" => run_agent(if args.len() > 2 { &args[2..] } else { &[] }),
        other => {
            eprintln!("unknown fixture subcommand: {other:?}");
            std::process::exit(2);
        }
    }
}

// ---------------------------------------------------------------------------
// Legacy top-level subcommands (Commit 2 transport tests).
// ---------------------------------------------------------------------------

fn fixture_echo() {
    let mut input = String::new();
    if io::stdin().read_line(&mut input).is_err() {
        return;
    }
    let stdout = io::stdout();
    let mut out = stdout.lock();
    let _ = out.write_all(input.as_bytes());
    let _ = out.write_all(b"\n");
    let _ = out.flush();
}

fn fixture_echo_crlf() {
    let mut input = String::new();
    if io::stdin().read_line(&mut input).is_err() {
        return;
    }
    let stdout = io::stdout();
    let mut out = stdout.lock();
    let _ = out.write_all(input.as_bytes());
    let _ = out.write_all(b"\r\n");
    let _ = out.flush();
}

fn fixture_oversize() {
    let line = "a".repeat(2 * 1024 * 1024);
    let stdout = io::stdout();
    let mut out = stdout.lock();
    let _ = out.write_all(line.as_bytes());
    let _ = out.write_all(b"\n");
    let _ = out.flush();
}

fn fixture_oversize_then_valid() {
    let big = "a".repeat(2 * 1024 * 1024);
    let stdout = io::stdout();
    let mut out = stdout.lock();
    let _ = out.write_all(big.as_bytes());
    let _ = out.write_all(b"\n");
    let _ = out.write_all(b"OK\n");
    let _ = out.flush();
}

fn fixture_stderr_flood() {
    let stderr = io::stderr();
    let mut err = stderr.lock();
    loop {
        let _ = err.write_all(b"E");
        let _ = err.flush();
        thread::sleep(std::time::Duration::from_millis(1));
    }
}

fn fixture_sleep(ms: Option<&String>) {
    let millis: u64 = ms.and_then(|s| s.parse().ok()).unwrap_or(1000);
    thread::sleep(std::time::Duration::from_millis(millis));
}

// ---------------------------------------------------------------------------
// Protocol-speaking agent (`agent <mode> [options]`).
// ---------------------------------------------------------------------------

/// Fixed protocol identity declared by every agent-mode fixture.
const AGENT_NAME: &str = "arena-fixture";
const AGENT_VERSION: &str = "1.0";

fn run_agent(agent_args: &[String]) {
    let mode = agent_args
        .first()
        .map(String::as_str)
        .unwrap_or("scripted")
        .to_string();

    let mut script_path: Option<PathBuf> = None;
    let mut transcript_prefix: Option<PathBuf> = None;
    let mut i = 1;
    while i < agent_args.len() {
        match agent_args[i].as_str() {
            "--script" => {
                if let Some(p) = agent_args.get(i + 1) {
                    script_path = Some(PathBuf::from(p));
                }
                i += 2;
            }
            "--transcript" => {
                if let Some(p) = agent_args.get(i + 1) {
                    transcript_prefix = Some(PathBuf::from(p));
                }
                i += 2;
            }
            _ => i += 1,
        }
    }

    // `early-exit` reads exactly one line (the server Hello) and then exits
    // without ever responding. Reading the Hello first guarantees the arena's
    // outbound flush succeeds, so the abort is deterministically classified as
    // `AgentEof` during the handshake phase (never a racy pipe-write failure).
    if mode == "early-exit" {
        let mut s = String::new();
        let _ = io::stdin().lock().read_line(&mut s);
        std::process::exit(0);
    }

    let actions: Vec<Action> = match &script_path {
        Some(p) => serde_json::from_str(&std::fs::read_to_string(p).expect("read script"))
            .expect("parse script actions"),
        None => Vec::new(),
    };

    let transcript_path = transcript_prefix.map(|p| {
        let mut os = p.into_os_string();
        os.push(".received.ndjson");
        PathBuf::from(os)
    });
    let mut transcript = transcript_path.map(|p| File::create(&p).expect("create transcript file"));

    let stdin = io::stdin();
    let mut reader = stdin.lock();
    let stdout = io::stdout();
    let mut out = stdout.lock();

    if mode == "scripted-stderr-flood" {
        thread::spawn(|| {
            let stderr = io::stderr();
            let mut err = stderr.lock();
            loop {
                let _ = err.write_all(b"x");
                let _ = err.flush();
            }
        });
    }

    let mut line = String::new();
    loop {
        line.clear();
        let n = reader.read_line(&mut line).expect("read stdin line");
        if n == 0 {
            break; // EOF: the arena closed our stdin on shutdown/abort.
        }
        if line.ends_with('\n') {
            line.pop();
        }
        if line.ends_with('\r') {
            line.pop();
        }
        if line.is_empty() {
            continue;
        }

        // Capture the raw server line before replying (flush-then-reply).
        if let Some(f) = transcript.as_mut() {
            let _ = writeln!(f, "{}", line);
            let _ = f.flush();
        }

        let msg = match parse_server_line(&line) {
            Ok(m) => m,
            Err(_) => continue,
        };

        let gid = extract_game_id(&msg);

        match mode.as_str() {
            "scripted" | "scripted-stderr-flood" => match &msg {
                ServerMessage::Hello { .. } => {
                    if let Some(g) = &gid {
                        send_client_hello(&mut out, g);
                    }
                }
                ServerMessage::RequestAction { meta, .. } => {
                    let rid = meta.request_id;
                    let action = actions
                        .get((rid as usize).saturating_sub(1))
                        .copied()
                        .expect("scripted action for request_id");
                    if let Some(g) = &gid {
                        send_client_action(&mut out, g, rid, action);
                    }
                }
                ServerMessage::GameEnd { .. } => break,
                _ => {}
            },
            "handshake-timeout" => { /* never respond */ }
            "action-timeout" => {
                if matches!(msg, ServerMessage::Hello { .. }) {
                    if let Some(g) = &gid {
                        send_client_hello(&mut out, g);
                    }
                }
            }
            "malformed-action" => match &msg {
                ServerMessage::Hello { .. } => {
                    if let Some(g) = &gid {
                        send_client_hello(&mut out, g);
                    }
                }
                ServerMessage::RequestAction { meta, .. } => {
                    let g = gid.clone().unwrap();
                    let rid = meta.request_id;
                    let bad = format!(
                        "{{\"type\":\"action\",\"protocol_version\":\"0.5\",\"game_id\":\"{g}\",\"request_id\":{rid},\"action\":{{\"type\":\"pass\"}},\"bogus_field\":1}}"
                    );
                    let _ = writeln!(out, "{}", bad);
                    let _ = out.flush();
                    break;
                }
                _ => {}
            },
            "wrong-protocol" => {
                if let ServerMessage::Hello { .. } = &msg {
                    let g = gid.clone().unwrap();
                    let bad = ClientMessage::Hello {
                        meta: ClientMeta {
                            protocol_version: "0.0".to_string(),
                            game_id: g,
                        },
                        agent_name: AGENT_NAME.to_string(),
                        agent_version: AGENT_VERSION.to_string(),
                    };
                    let _ = writeln!(out, "{}", serde_json::to_string(&bad).unwrap());
                    let _ = out.flush();
                    break;
                }
            }
            "wrong-game-id" => {
                if let ServerMessage::Hello { .. } = &msg {
                    let bad = ClientMessage::Hello {
                        meta: ClientMeta::new("wrong-game-id-literal"),
                        agent_name: AGENT_NAME.to_string(),
                        agent_version: AGENT_VERSION.to_string(),
                    };
                    let _ = writeln!(out, "{}", serde_json::to_string(&bad).unwrap());
                    let _ = out.flush();
                    break;
                }
            }
            "wrong-request-id" => match &msg {
                ServerMessage::Hello { .. } => {
                    if let Some(g) = &gid {
                        send_client_hello(&mut out, g);
                    }
                }
                ServerMessage::RequestAction { meta: _, .. } => {
                    let g = gid.clone().unwrap();
                    let bad = ClientMessage::Action {
                        meta: ClientRequestMeta::new(&g, 9999),
                        action: Action::Pass,
                    };
                    let _ = writeln!(out, "{}", serde_json::to_string(&bad).unwrap());
                    let _ = out.flush();
                    break;
                }
                _ => {}
            },
            "illegal-action" => match &msg {
                ServerMessage::Hello { .. } => {
                    if let Some(g) = &gid {
                        send_client_hello(&mut out, g);
                    }
                }
                ServerMessage::RequestAction { meta, .. } => {
                    let g = gid.clone().unwrap();
                    let bad = ClientMessage::Action {
                        meta: ClientRequestMeta::new(&g, meta.request_id),
                        action: Action::BuyMarket {
                            tier: Tier::One,
                            slot: 99,
                        },
                    };
                    let _ = writeln!(out, "{}", serde_json::to_string(&bad).unwrap());
                    let _ = out.flush();
                    break;
                }
                _ => {}
            },
            "duplicate-hello" => {
                if let ServerMessage::Hello { .. } = &msg {
                    let g = gid.clone().unwrap();
                    send_client_hello(&mut out, &g);
                    send_client_hello(&mut out, &g);
                    break;
                }
            }
            "unsolicited-message" => {
                if let ServerMessage::Hello { .. } = &msg {
                    let g = gid.clone().unwrap();
                    send_client_hello(&mut out, &g);
                    let bad = ClientMessage::Action {
                        meta: ClientRequestMeta::new(&g, 1),
                        action: Action::Pass,
                    };
                    let _ = writeln!(out, "{}", serde_json::to_string(&bad).unwrap());
                    let _ = out.flush();
                    break;
                }
            }
            "oversize-handshake" => {
                if let ServerMessage::Hello { .. } = &msg {
                    let big = "a".repeat(2 * 1024 * 1024);
                    let line_big = format!(
                        "{{\"type\":\"hello\",\"protocol_version\":\"0.5\",\"game_id\":\"x\",\"agent_name\":\"{big}\",\"agent_version\":\"1.0\"}}"
                    );
                    let _ = out.write_all(line_big.as_bytes());
                    let _ = out.write_all(b"\n");
                    let _ = out.flush();
                    break;
                }
            }
            "oversize-action" => match &msg {
                ServerMessage::Hello { .. } => {
                    if let Some(g) = &gid {
                        send_client_hello(&mut out, g);
                    }
                }
                ServerMessage::RequestAction { meta, .. } => {
                    let g = gid.clone().unwrap();
                    let big = "a".repeat(2 * 1024 * 1024);
                    let line_big = format!(
                        "{{\"type\":\"action\",\"protocol_version\":\"0.5\",\"game_id\":\"{g}\",\"request_id\":{},\"action\":{{\"type\":\"pass\",\"note\":\"{big}\"}}}}",
                        meta.request_id
                    );
                    let _ = out.write_all(line_big.as_bytes());
                    let _ = out.write_all(b"\n");
                    let _ = out.flush();
                    break;
                }
                _ => {}
            },
            "non-utf8-action" => match &msg {
                ServerMessage::Hello { .. } => {
                    if let Some(g) = &gid {
                        send_client_hello(&mut out, g);
                    }
                }
                ServerMessage::RequestAction { meta, .. } => {
                    let g = gid.clone().unwrap();
                    let mut bytes = format!(
                        "{{\"type\":\"action\",\"protocol_version\":\"0.5\",\"game_id\":\"{g}\",\"request_id\":{},\"action\":{{\"type\":\"pass\"}},",
                        meta.request_id
                    )
                    .into_bytes();
                    bytes.push(0xFF);
                    bytes.push(0xFE);
                    bytes.extend_from_slice(b"\"bad\":\xff}\n");
                    let _ = out.write_all(&bytes);
                    let _ = out.flush();
                    break;
                }
                _ => {}
            },
            _ => { /* unknown mode: behave like handshake-timeout */ }
        }
    }
}

/// Extract the `game_id` a server message was addressed under (Hello carries it
/// directly; every other recipient message carries it in `meta`).
fn extract_game_id(msg: &ServerMessage) -> Option<String> {
    match msg {
        ServerMessage::Hello { meta, .. } => Some(meta.game_id.clone()),
        ServerMessage::GameStart { meta, .. } => Some(meta.server.game_id.clone()),
        ServerMessage::Observation { meta, .. } => Some(meta.recipient.server.game_id.clone()),
        ServerMessage::RequestAction { meta, .. } => Some(meta.recipient.server.game_id.clone()),
        ServerMessage::ActionApplied { meta, .. } => Some(meta.server.game_id.clone()),
        ServerMessage::Event { meta, .. } => Some(meta.server.game_id.clone()),
        ServerMessage::GameEnd { meta, .. } => Some(meta.server.game_id.clone()),
        ServerMessage::Error { meta, .. } => Some(meta.server.game_id.clone()),
        ServerMessage::Ping { meta } => Some(meta.server.game_id.clone()),
    }
}

fn send_client_hello(out: &mut impl Write, game_id: &str) {
    let msg = ClientMessage::Hello {
        meta: ClientMeta::new(game_id),
        agent_name: AGENT_NAME.to_string(),
        agent_version: AGENT_VERSION.to_string(),
    };
    let _ = writeln!(out, "{}", serde_json::to_string(&msg).unwrap());
    let _ = out.flush();
}

fn send_client_action(out: &mut impl Write, game_id: &str, request_id: u64, action: Action) {
    let msg = ClientMessage::Action {
        meta: ClientRequestMeta::new(game_id, request_id),
        action,
    };
    let _ = writeln!(out, "{}", serde_json::to_string(&msg).unwrap());
    let _ = out.flush();
}
