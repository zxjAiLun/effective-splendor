# ADR-0005: Stdio arena process boundary

## Status

Accepted in M04 (`m04-arena-v1` target).

## Context

M04 introduces a referee that runs a real match between two to four agents.
An agent could have been a Rust trait object called in-process, which is fast
and simple. But the platform's whole point is to evaluate *foreign,
adversarial* agents — eventually written in other languages, of unknown
quality, and not to be trusted with referee state. An in-process agent shares
the arena's address space: it can read `FullState` (deck order, opponents'
blind reserves), block the referee thread, or panic the whole process. None of
that is acceptable for a competition harness.

We also already have a strict NDJSON protocol (`splendor-protocol`) with
per-recipient observation projection and owned wire DTOs. The information
boundary it enforces is only meaningful if there is an actual boundary to
enforce.

## Decision

1. **An agent is an OS process, not a trait.** The arena spawns each agent as a
   subprocess and speaks v0.5 NDJSON over its stdio. The agent's memory, its
   panics, and its clock are its own; the referee is isolated from all three.

2. **The runner binds the seat; the agent never authorizes itself.** A client
   `Action` carries no seat — the seat is the connection the arena spawned.
   `game_id`, `request_id`, and the observation hash are correlation checks the
   arena verifies, not identity the client asserts.

3. **Agent commands are spawned literally, never shelled.** `AgentCommand` is a
   `program` plus literal argv tokens. The arena never joins them into a shell
   string, expands environment variables, or performs glob/quote handling. A
   crafted `game_id` cannot inject framing either — C0 control characters are
   rejected at config validation.

4. **Faults are categorized, not fatal.** Timeouts, malformed lines, EOF,
   illegal actions, wrong `request_id`, and I/O breaks each map to a stable
   `AgentFault` and abort the match cleanly with an attributable seat and phase,
   rather than crashing the referee. An aborted match fabricates no
   `GameResult` and no winners.

5. **The referee record is separate from the wire.** A completed match writes a
   referee `ReplayV1` (raw seed, full-state hashes) *and* an `ArenaReportV1`.
   The replay is never sent to an agent mid-match — it is the same referee-only
   artifact defined in ADR-0004. The report binds the transcript to the result
   via `replay_final_hash`, which the CLI re-verifies before publishing.

6. **Publication is atomic and report-last.** Artifacts are written to sibling
   temp files and renamed into place; on a completed match the replay is
   committed before the report, so observing the report guarantees the replay is
   already present. A partial pair is never observable. (See `docs/arena.md`.)

## Consequences

- The arena can host agents in any language that can read/write NDJSON on
  stdio, with no shared memory and no trust in agent code.
- Every match produces a self-verifying, reproducible pair of artifacts, or a
  clean categorized abort — never a corrupt or half-written result.
- The cost is process and serialization overhead per ply; that is acceptable
  for evaluation and explicitly *not* the path for high-volume RL self-play,
  which uses the in-process `splendor-core` / PyO3 env instead.
- M04 deliberately excludes tournaments, Elo, TCP, async, agent sandboxing, and
  resume/reconnect. Those would each extend, not revise, this boundary.
