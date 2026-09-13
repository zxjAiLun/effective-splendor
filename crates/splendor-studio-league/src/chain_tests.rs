//! Crate-internal gates over the runtime completion chain.
//!
//! These two suites used to be integration tests (`tests/replay_archive.rs` and
//! `tests/runtime_ingest.rs`). Commit C Slice 3 Repair 2 made
//! [`crate::historical_import::runtime_match_record`] and
//! [`crate::historical_import::bind_archived_replay`] crate-private, because a
//! public `runtime_match_record` + `bind_archived_replay` pair *is* the shortcut
//! the completion outlet exists to remove: any external producer could build and
//! archive-bind a legitimate runtime canonical record, on a root of its own
//! choosing, and then ingest it directly — bypassing
//! [`crate::completion::CompletionLeagueV1`], the manifest session gate, and the
//! fixed protocol archive root.
//!
//! They are still the tests of those primitives, so they moved next to the code
//! they exercise instead of gaining a public `*_for_test` escape hatch. The
//! public surface keeps its own integration coverage: `tests/completion_outlet.rs`
//! (the outlet's gates), `tests/archive_protocol_root.rs` (the recorded path
//! resolves under the protocol root alone, now driven through the outlet), and
//! `crates/splendor-cli/tests/completion_equivalence.rs` (the CLI adapter).
//!
//! Each suite keeps the temp-directory label prefix it had before the move, so
//! the two suites and the unit tests in [`crate::replay_archive`] cannot collide
//! inside the one lib test process.

mod replay_archive;
mod runtime_ingest;
