//! Cross-platform agent fixture binary for arena transport tests.
//!
//! Selected by `argv[1]`; never uses a shell. Supported subcommands:
//! - `echo`               : read one line from stdin, write it back + '\n'
//! - `early-exit`         : exit immediately (before reading stdin)
//! - `oversize-line`      : write a single line far exceeding 1 MiB, then exit
//! - `stderr-flood`       : write to stderr in a loop until killed
//! - `sleep` <ms>         : sleep for the given milliseconds, then exit

use std::io::{self, Write};
use std::thread::sleep;
use std::time::Duration;

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
        other => {
            eprintln!("unknown fixture subcommand: {other:?}");
            std::process::exit(2);
        }
    }
}

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

/// Echo, but terminate the written line with CRLF so the transport's newline
/// normalization can be exercised end-to-end.
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
    // ~2 MiB of 'a' characters on a single line (no trailing newline needed to
    // trigger the over-length path). Exceeds MAX_AGENT_LINE_BYTES (1 MiB).
    let line = "a".repeat(2 * 1024 * 1024);
    let stdout = io::stdout();
    let mut out = stdout.lock();
    let _ = out.write_all(line.as_bytes());
    let _ = out.write_all(b"\n");
    let _ = out.flush();
}

/// One oversize line (terminated) followed by a valid short line. Exercises the
/// transport's "discard until the next newline, then resume normal parsing"
/// behavior.
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
        // A short sleep keeps the loop from busy-spinning; the arena kills the
        // process during shutdown/drop, which ends the loop.
        let _ = err.write_all(b"E");
        let _ = err.flush();
        sleep(Duration::from_millis(1));
    }
}

fn fixture_sleep(ms: Option<&String>) {
    let millis: u64 = ms.and_then(|s| s.parse().ok()).unwrap_or(1000);
    sleep(Duration::from_millis(millis));
}
