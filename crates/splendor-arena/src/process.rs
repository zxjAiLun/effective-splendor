//! Agent process transport and lifecycle.
//!
//! An [`AgentProcess`] wraps a spawned agent subprocess and forwards its
//! stdout lines (bounded, CRLF-normalized) to an [`InboundEvent`] channel,
//! while draining stderr into a bounded 64 KiB tail. The arena runner owns the
//! channel receiver and drives match flow; this module only moves bytes and
//! reaps the child.
//!
//! Lifecycle is best-effort and never panics in `Drop`: on shutdown the arena
//! closes stdin, polls `try_wait` under a grace period, then `kill`s and
//! `wait`s. `Drop` repeats the `kill + wait` as a final backstop. No Unix
//! signals and no shell are used.

use std::io::{self, Read, Write};
use std::process::{Child, ChildStdin, Command, ExitStatus, Stdio};
use std::sync::mpsc::Sender;
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use splendor_core::PlayerId;
use splendor_protocol::ServerMessage;

use crate::config::AgentCommand;
use crate::error::ProcessError;

/// Maximum bytes retained for a single stdout line before it is rejected as
/// too large. One extra byte is buffered to detect the overflow deterministically.
pub const MAX_AGENT_LINE_BYTES: usize = 1024 * 1024;

/// Maximum bytes retained of an agent's stderr tail.
pub const STDERR_TAIL_BYTES: usize = 64 * 1024;

/// Events emitted by a single agent's stdout/stderr, bound to its seat.
#[derive(Debug, Clone)]
pub enum InboundEvent {
    /// One complete, CRLF-normalized stdout line (possibly empty).
    Line {
        /// The seat this agent occupies.
        seat: PlayerId,
        /// The decoded line contents (newline stripped).
        line: String,
    },
    /// The agent's stdout reached EOF.
    StdoutEof {
        /// The seat this agent occupies.
        seat: PlayerId,
    },
    /// A stdout read failed or produced invalid UTF-8.
    StdoutError {
        /// The seat this agent occupies.
        seat: PlayerId,
        /// Human-readable reason.
        message: String,
    },
    /// A single stdout line exceeded [`MAX_AGENT_LINE_BYTES`].
    MessageTooLarge {
        /// The seat this agent occupies.
        seat: PlayerId,
        /// The configured limit.
        limit: usize,
    },
}

/// A bounded, overwrite-style tail of stderr bytes.
#[derive(Debug, Default)]
struct StderrTail {
    buf: Box<[u8]>,
    head: usize,
    len: usize,
}

impl StderrTail {
    fn new() -> Self {
        StderrTail {
            buf: vec![0u8; STDERR_TAIL_BYTES].into_boxed_slice(),
            head: 0,
            len: 0,
        }
    }

    fn push(&mut self, chunk: &[u8]) {
        for &b in chunk {
            self.buf[self.head] = b;
            self.head = (self.head + 1) % self.buf.len();
            if self.len < self.buf.len() {
                self.len += 1;
            }
        }
    }

    fn as_bytes(&self) -> Vec<u8> {
        if self.len < self.buf.len() {
            self.buf[..self.len].to_vec()
        } else {
            let mut out = Vec::with_capacity(self.buf.len());
            out.extend_from_slice(&self.buf[self.head..]);
            out.extend_from_slice(&self.buf[..self.head]);
            out
        }
    }
}

/// A spawned agent subprocess with its I/O plumbing.
pub struct AgentProcess {
    seat: PlayerId,
    child: Child,
    stdin: Option<ChildStdin>,
    stderr_tail: Arc<Mutex<StderrTail>>,
    stdout_thread: Option<JoinHandle<()>>,
    stderr_thread: Option<JoinHandle<()>>,
}

impl AgentProcess {
    /// The seat this process is bound to.
    pub fn seat(&self) -> PlayerId {
        self.seat
    }

    /// Send one server message: serialize, write JSON bytes, append `'\n'`,
    /// flush, return. The runner may start its deadline only after this
    /// returns `Ok`.
    pub fn send(&mut self, message: &ServerMessage) -> Result<(), ProcessError> {
        let bytes = message
            .to_json_line()
            .map_err(|e| ProcessError::Io(io::Error::new(io::ErrorKind::InvalidData, e)))?;
        let mut stdin = self.stdin.take().ok_or_else(|| {
            ProcessError::Io(io::Error::new(io::ErrorKind::BrokenPipe, "stdin closed"))
        })?;
        let write_result = (|| {
            stdin.write_all(bytes.as_bytes())?;
            stdin.write_all(b"\n")?;
            stdin.flush()?;
            io::Result::Ok(())
        })();
        self.stdin = Some(stdin);
        write_result.map_err(ProcessError::from_write)
    }

    /// Copy the current stderr tail (at most [`STDERR_TAIL_BYTES`]).
    pub fn stderr_tail(&self) -> Vec<u8> {
        self.stderr_tail.lock().unwrap().as_bytes()
    }

    /// Reap the child. Closes stdin, polls `try_wait` under `grace`, then
    /// `kill`s and `wait`s. Returns the final [`ExitStatus`].
    pub fn shutdown(&mut self, grace: Duration) -> Result<ExitStatus, ProcessError> {
        // 1. Close stdin so a reading child observes EOF.
        self.stdin = None;

        // 2. Poll under the grace period. Cleanup must run on every exit path,
        //    including a `try_wait` error: the contract is "error also cleans
        //    up", never "error skips cleanup".
        let deadline = Instant::now() + grace;
        loop {
            match self.child.try_wait() {
                Ok(Some(status)) => {
                    self.join_readers();
                    return Ok(status);
                }
                Ok(None) => {
                    if Instant::now() >= deadline {
                        break;
                    }
                    thread::sleep(Duration::from_millis(10));
                }
                Err(e) => {
                    let _ = self.child.kill();
                    let _ = self.child.wait();
                    self.join_readers();
                    return Err(ProcessError::Wait(e));
                }
            }
        }

        // 3. Escalate to kill, then final wait.
        let _ = self.child.kill();
        let status = self.child.wait().map_err(ProcessError::Wait)?;
        self.join_readers();
        Ok(status)
    }

    /// Join both reader threads. Safe only after the child has exited (pipes
    /// closed), so the threads are guaranteed to be terminating.
    fn join_readers(&mut self) {
        if let Some(t) = self.stdout_thread.take() {
            let _ = t.join();
        }
        if let Some(t) = self.stderr_thread.take() {
            let _ = t.join();
        }
    }
}

impl Drop for AgentProcess {
    fn drop(&mut self) {
        // Best-effort reaping backstop; must never panic. A `try_wait` error is
        // treated like "still running": kill + wait before joining readers so
        // the reader threads are never left blocking on a live pipe.
        self.stdin = None;
        match self.child.try_wait() {
            Ok(Some(_)) => {}
            Ok(None) | Err(_) => {
                let _ = self.child.kill();
                let _ = self.child.wait();
            }
        }
        self.join_readers();
    }
}

/// Spawn an agent and start its stdout/stderr reader threads. Emitted
/// [`InboundEvent`]s are sent to `inbound_tx`, tagged with `seat`.
pub fn spawn_agent(
    seat: PlayerId,
    command: &AgentCommand,
    inbound_tx: Sender<InboundEvent>,
) -> Result<AgentProcess, ProcessError> {
    let mut cmd = Command::new(&command.program);
    cmd.args(&command.args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    let mut child = cmd.spawn().map_err(ProcessError::Spawn)?;

    let mut stdout = child.stdout.take().expect("stdout was piped");
    let mut stderr = child.stderr.take().expect("stderr was piped");
    let stdin = child.stdin.take().expect("stdin was piped");

    let stderr_tail: Arc<Mutex<StderrTail>> = Arc::new(Mutex::new(StderrTail::new()));

    let stdout_tx = inbound_tx;
    let stdout_seat = seat;
    let stdout_thread = thread::spawn(move || {
        run_stdout_reader(&mut stdout, stdout_seat, &stdout_tx);
    });

    let stderr_tail_for_thread = Arc::clone(&stderr_tail);
    let stderr_thread = thread::spawn(move || {
        let mut buf = [0u8; 4096];
        loop {
            match stderr.read(&mut buf) {
                Ok(0) => break,
                Ok(n) => {
                    let mut guard = stderr_tail_for_thread.lock().unwrap();
                    guard.push(&buf[..n]);
                }
                Err(_) => break,
            }
        }
    });

    Ok(AgentProcess {
        seat,
        child,
        stdin: Some(stdin),
        stderr_tail,
        stdout_thread: Some(stdout_thread),
        stderr_thread: Some(stderr_thread),
    })
}

/// Read stdout in bounded chunks, reconstructing complete lines without ever
/// buffering more than [`MAX_AGENT_LINE_BYTES`] + 1 per line.
fn run_stdout_reader(stdout: &mut impl Read, seat: PlayerId, tx: &Sender<InboundEvent>) {
    const CHUNK: usize = 8192;
    let mut buf = [0u8; CHUNK];
    let mut line: Vec<u8> = Vec::with_capacity(256);
    // While true, the tail of an oversize line is being dropped until the next
    // newline: no `Line` may be emitted for it, and only one fault may fire.
    let mut discarding_oversize_line = false;

    loop {
        match stdout.read(&mut buf) {
            Ok(0) => break,
            Ok(n) => {
                let mut start = 0;
                while start < n {
                    let remaining = &buf[start..n];
                    if let Some(pos) = remaining.iter().position(|&b| b == b'\n') {
                        let slice = &remaining[..pos];
                        if discarding_oversize_line {
                            // This newline ends the oversize line; drop it
                            // entirely and exit discard mode (no Line emitted).
                            discarding_oversize_line = false;
                            line.clear();
                        } else if line.len() + slice.len() > MAX_AGENT_LINE_BYTES {
                            // The completed line overflows, but its terminating
                            // newline was found in this same chunk, so the line
                            // is already finished. Fire exactly one fault and
                            // move on: do NOT enter discard mode, otherwise the
                            // next (valid) line after this newline would be
                            // wrongly dropped on the same boundary.
                            let _ = tx.send(InboundEvent::MessageTooLarge {
                                seat,
                                limit: MAX_AGENT_LINE_BYTES,
                            });
                            line.clear();
                        } else {
                            line.extend_from_slice(slice);
                            // Strip a trailing '\r' (CRLF normalization).
                            if line.last() == Some(&b'\r') {
                                line.pop();
                            }
                            emit_line(seat, &line, tx);
                            line.clear();
                        }
                        start += pos + 1;
                    } else if discarding_oversize_line {
                        // Still inside the oversize line; skip this data.
                        start = n;
                    } else if line.len() + remaining.len() > MAX_AGENT_LINE_BYTES {
                        let _ = tx.send(InboundEvent::MessageTooLarge {
                            seat,
                            limit: MAX_AGENT_LINE_BYTES,
                        });
                        discarding_oversize_line = true;
                        line.clear();
                        start = n;
                    } else {
                        line.extend_from_slice(remaining);
                        start = n;
                    }
                }
            }
            Err(e) => {
                let _ = tx.send(InboundEvent::StdoutError {
                    seat,
                    message: e.to_string(),
                });
                break;
            }
        }
    }

    // Emit a trailing partial line only if it was a real (in-bounds) line.
    // If we are still discarding an oversize line, its tail must NOT be
    // forwarded as a partial `Line`.
    if !discarding_oversize_line && !line.is_empty() {
        emit_line(seat, &line, tx);
    }

    let _ = tx.send(InboundEvent::StdoutEof { seat });
}

/// Decode a collected line buffer as UTF-8 and forward it. Non-UTF-8 yields a
/// `StdoutError` rather than a panic; the protocol parser will still reject a
/// malformed line sent via the `Line` path.
fn emit_line(seat: PlayerId, line: &[u8], tx: &Sender<InboundEvent>) {
    match std::str::from_utf8(line) {
        Ok(s) => {
            let _ = tx.send(InboundEvent::Line {
                seat,
                line: s.to_string(),
            });
        }
        Err(_) => {
            let _ = tx.send(InboundEvent::StdoutError {
                seat,
                message: "non-UTF-8 stdout line".to_string(),
            });
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;
    use std::sync::mpsc;

    /// Drive the private reader over an in-memory byte stream so the 8192-byte
    /// chunk boundary is fully under our control (no OS pipe splitting), then
    /// collect every emitted event in order.
    fn collect(reader_input: Vec<u8>, seat: PlayerId) -> Vec<InboundEvent> {
        let (tx, rx) = mpsc::channel();
        let mut cursor = Cursor::new(reader_input);
        run_stdout_reader(&mut cursor, seat, &tx);
        // The reader returns only after EOF, having sent StdoutEof last.
        // Drop the sender so `rx.iter()` terminates once drained.
        drop(tx);
        rx.iter().collect()
    }

    #[test]
    fn oversize_boundary_newline_then_valid_line_recovers() {
        // A single oversize line whose terminating newline lands in the same
        // read that first detects the overflow, immediately followed by a valid
        // line. The overflow must fire exactly one fault, and the valid line
        // after the newline must NOT be discarded.
        //
        // With 8192-byte reads and MAX = 1024*1024 = 128*8192, the line
        // accumulates to exactly MAX without triggering the no-newline discard
        // path; the final read ("a\nOK\n") is where overflow and the newline
        // coincide.
        let mut input = vec![b'a'; MAX_AGENT_LINE_BYTES + 1];
        input.push(b'\n');
        input.extend_from_slice(b"OK\n");

        let events = collect(input, PlayerId(0));

        let faults = events
            .iter()
            .filter(|e| matches!(e, InboundEvent::MessageTooLarge { .. }))
            .count();
        assert_eq!(faults, 1, "expected exactly one MessageTooLarge");

        let ok_forwarded = events
            .iter()
            .any(|e| matches!(e, InboundEvent::Line { line, .. } if line == "OK"));
        assert!(
            ok_forwarded,
            "valid line after boundary overflow must be forwarded: {events:?}"
        );

        // The oversize line's tail must never be forwarded as a Line.
        let oversize_fragment = events
            .iter()
            .any(|e| matches!(e, InboundEvent::Line { line, .. } if line.starts_with('a')));
        assert!(
            !oversize_fragment,
            "oversize tail must not be forwarded: {events:?}"
        );

        // Strict ordering: the fault, then the recovered valid line, then EOF.
        let seq: Vec<&str> = events
            .iter()
            .map(|e| match e {
                InboundEvent::MessageTooLarge { .. } => "fault",
                InboundEvent::Line { line, .. } => {
                    if line == "OK" {
                        "ok"
                    } else {
                        "other"
                    }
                }
                InboundEvent::StdoutEof { .. } => "eof",
                _ => "ignored",
            })
            .collect();
        assert_eq!(
            seq,
            vec!["fault", "ok", "eof"],
            "unexpected event sequence after boundary overflow: {seq:?}"
        );
    }
}
