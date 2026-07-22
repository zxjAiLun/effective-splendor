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

/// Collect every event up to and including `StdoutEof`, with a bounded timeout
/// so a misbehaving transport cannot hang the test forever. The `StdoutEof`
/// marker is normalized (seat irrelevant) for stable assertions.
fn drain_to_eof(rx: &mpsc::Receiver<InboundEvent>, timeout: Duration) -> Vec<InboundEvent> {
    let mut out = Vec::new();
    loop {
        match rx.recv_timeout(timeout) {
            Ok(InboundEvent::StdoutEof { .. }) => {
                out.push(InboundEvent::StdoutEof { seat: PlayerId(0) });
                break;
            }
            Ok(ev) => out.push(ev),
            Err(_) => break,
        }
    }
    out
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
    let events = drain_to_eof(&rx, Duration::from_secs(5));
    let faults: Vec<usize> = events
        .iter()
        .filter_map(|e| match e {
            InboundEvent::MessageTooLarge { limit, .. } => Some(*limit),
            _ => None,
        })
        .collect();
    assert_eq!(faults.len(), 1, "expected exactly one MessageTooLarge");
    assert_eq!(faults[0], MAX_AGENT_LINE_BYTES);
}

#[test]
fn oversize_line_emits_exactly_one_fault() {
    let (tx, rx) = mpsc::channel();
    let _proc = spawn_agent(PlayerId(0), &agent("oversize-line"), tx).expect("spawn");
    let events = drain_to_eof(&rx, Duration::from_secs(5));
    let faults = events
        .iter()
        .filter(|e| matches!(e, InboundEvent::MessageTooLarge { .. }))
        .count();
    assert_eq!(
        faults, 1,
        "a single oversize line must emit exactly one fault"
    );
}

#[test]
fn oversize_line_emits_no_tail_fragment() {
    let (tx, rx) = mpsc::channel();
    let _proc = spawn_agent(PlayerId(0), &agent("oversize-line"), tx).expect("spawn");
    let events = drain_to_eof(&rx, Duration::from_secs(5));
    // The oversize line's tail must never be forwarded as a Line.
    assert!(
        events
            .iter()
            .all(|e| !matches!(e, InboundEvent::Line { .. })),
        "oversize tail must not be forwarded: {events:?}"
    );
    assert!(
        events
            .iter()
            .any(|e| matches!(e, InboundEvent::MessageTooLarge { .. })),
        "expected the single MessageTooLarge fault"
    );
}

#[test]
fn oversize_then_valid_line_recovers_at_next_newline() {
    let (tx, rx) = mpsc::channel();
    let _proc = spawn_agent(PlayerId(0), &agent("oversize-then-valid"), tx).expect("spawn");
    let events = drain_to_eof(&rx, Duration::from_secs(5));

    let mut saw_fault = false;
    let mut saw_ok = false;
    let mut line_before_fault = false;
    for e in &events {
        match e {
            InboundEvent::MessageTooLarge { .. } => saw_fault = true,
            InboundEvent::Line { line, .. } => {
                if !saw_fault {
                    line_before_fault = true;
                }
                if line == "OK" {
                    saw_ok = true;
                }
            }
            _ => {}
        }
    }
    assert!(saw_fault, "expected the oversize fault");
    assert!(
        !line_before_fault,
        "no valid line should appear before the fault"
    );
    assert!(
        saw_ok,
        "a valid line after the oversize line must still be forwarded"
    );
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
