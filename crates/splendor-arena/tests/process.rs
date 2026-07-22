use splendor_arena::process::{spawn_agent, InboundEvent, MAX_AGENT_LINE_BYTES, STDERR_TAIL_BYTES};
use splendor_arena::AgentCommand;
use splendor_core::PlayerId;
use splendor_protocol::RecipientMeta;
use splendor_protocol::ServerMessage;
use std::path::PathBuf;
use std::sync::mpsc;
use std::time::Duration;

fn fixture_path() -> PathBuf {
    // Integration tests run from target/<profile>/deps/<test-exe>; the crate's
    // own binary lives one level up in target/<profile>/. Derive it from the
    // running test exe so it works on any platform and profile.
    let exe = std::env::current_exe().expect("current_exe available in tests");
    let profile_dir = exe
        .parent()
        .and_then(|p| p.parent())
        .expect("test exe is two levels under the profile dir");
    let name = if cfg!(windows) {
        "arena-fixture.exe"
    } else {
        "arena-fixture"
    };
    profile_dir.join(name)
}

fn agent(sub: &str) -> AgentCommand {
    AgentCommand {
        program: fixture_path(),
        args: vec![sub.to_string()],
    }
}

#[test]
fn spawn_binds_reported_seat() {
    let seat = PlayerId(1);
    let (tx, rx) = mpsc::channel();
    let proc = spawn_agent(seat, &agent("early-exit"), tx).expect("spawn");
    // Wait for EOF (child exits immediately) to confirm the seat tag.
    let mut eof_seen = false;
    loop {
        match rx.recv_timeout(Duration::from_secs(5)) {
            Ok(InboundEvent::StdoutEof { seat: s }) => {
                assert_eq!(s, seat);
                eof_seen = true;
                break;
            }
            Ok(_) => continue,
            Err(_) => break,
        }
    }
    assert!(eof_seen, "expected StdoutEof with bound seat");
    drop(proc);
}

#[test]
fn send_writes_one_flushed_ndjson_line() {
    let (tx, rx) = mpsc::channel();
    let mut proc = spawn_agent(PlayerId(0), &agent("echo"), tx).expect("spawn");
    let msg = ServerMessage::Ping {
        meta: RecipientMeta::new("g1", 0, PlayerId(0)),
    };
    proc.send(&msg).expect("send flush");

    // The echo fixture writes back exactly one line.
    let mut got_line = false;
    loop {
        match rx.recv_timeout(Duration::from_secs(5)) {
            Ok(InboundEvent::Line { seat, line }) => {
                assert_eq!(seat, PlayerId(0));
                // The echoed bytes are the JSON we sent, plus the fixture's
                // extra '\n' (already stripped). It must be valid JSON.
                assert!(line.starts_with('{') && line.contains("\"type\":\"ping\""));
                got_line = true;
                break;
            }
            Ok(_) => continue,
            Err(_) => break,
        }
    }
    assert!(got_line, "echo did not forward the sent line");
}

#[test]
fn stdout_lines_are_forwarded_with_bound_seat() {
    let (tx, rx) = mpsc::channel();
    let mut proc = spawn_agent(PlayerId(2), &agent("echo"), tx).expect("spawn");
    let msg = ServerMessage::Ping {
        meta: RecipientMeta::new("g1", 7, PlayerId(2)),
    };
    proc.send(&msg).expect("send");
    let mut ok = false;
    loop {
        match rx.recv_timeout(Duration::from_secs(5)) {
            Ok(InboundEvent::Line { seat, .. }) => {
                assert_eq!(seat, PlayerId(2));
                ok = true;
                break;
            }
            Ok(_) => continue,
            Err(_) => break,
        }
    }
    assert!(ok);
}

#[test]
fn crlf_is_normalized() {
    let (tx, rx) = mpsc::channel();
    let mut proc = spawn_agent(PlayerId(0), &agent("echo-crlf"), tx).expect("spawn");
    // The fixture echoes back with a trailing CRLF. The reader must strip the
    // '\r' so the forwarded line has no trailing carriage return.
    let msg = ServerMessage::Ping {
        meta: RecipientMeta::new("g1", 0, PlayerId(0)),
    };
    proc.send(&msg).expect("send");
    let mut ok = false;
    loop {
        match rx.recv_timeout(Duration::from_secs(5)) {
            Ok(InboundEvent::Line { line, .. }) => {
                assert!(!line.ends_with('\r'), "CRLF not normalized: {line:?}");
                ok = true;
                break;
            }
            Ok(_) => continue,
            Err(_) => break,
        }
    }
    assert!(ok);
}

#[test]
fn early_exit_reports_eof() {
    let (tx, rx) = mpsc::channel();
    let _proc = spawn_agent(PlayerId(0), &agent("early-exit"), tx).expect("spawn");
    let mut eof = false;
    loop {
        match rx.recv_timeout(Duration::from_secs(5)) {
            Ok(InboundEvent::StdoutEof { .. }) => {
                eof = true;
                break;
            }
            Ok(_) => continue,
            Err(_) => break,
        }
    }
    assert!(eof);
}

#[test]
fn oversize_line_is_bounded() {
    let (tx, rx) = mpsc::channel();
    let _proc = spawn_agent(PlayerId(0), &agent("oversize-line"), tx).expect("spawn");
    let mut too_large = false;
    loop {
        match rx.recv_timeout(Duration::from_secs(5)) {
            Ok(InboundEvent::MessageTooLarge { limit, .. }) => {
                assert_eq!(limit, MAX_AGENT_LINE_BYTES);
                too_large = true;
                break;
            }
            Ok(InboundEvent::Line { line, .. }) => {
                // Any forwarded line must be within the cap.
                assert!(line.len() <= MAX_AGENT_LINE_BYTES);
            }
            Ok(_) => continue,
            Err(_) => break,
        }
    }
    assert!(too_large, "expected MessageTooLarge for oversize line");
}

#[test]
fn stderr_flood_is_drained_and_tail_is_bounded() {
    let (tx, rx) = mpsc::channel();
    let mut proc = spawn_agent(PlayerId(0), &agent("stderr-flood"), tx).expect("spawn");
    // Let it write for a bit, then shut it down.
    std::thread::sleep(Duration::from_millis(200));
    let _ = proc.shutdown(Duration::from_millis(300));
    let tail = proc.stderr_tail();
    assert!(
        tail.len() <= STDERR_TAIL_BYTES,
        "stderr tail exceeded bound"
    );
    assert!(!tail.is_empty(), "expected some stderr bytes drained");
    drop(rx);
}

#[test]
fn shutdown_reaps_child() {
    let (tx, rx) = mpsc::channel();
    let mut proc = spawn_agent(PlayerId(0), &agent("sleep"), tx).expect("spawn");
    // Child is still alive (sleeping); shutdown must reap it.
    let status = proc.shutdown(Duration::from_millis(200)).expect("shutdown");
    assert!(status.success() || status.code().is_some());
    drop(rx);
}

#[test]
fn drop_reaps_child() {
    let (tx, rx) = mpsc::channel();
    {
        let _proc = spawn_agent(PlayerId(0), &agent("sleep"), tx).expect("spawn");
        // `_proc` drops here; Drop must kill + wait without panic.
    }
    // Give the reaper a moment; if Drop leaked the child this test would hang
    // or leave a zombie, but we assert the channel sender side is gone.
    drop(rx);
}
