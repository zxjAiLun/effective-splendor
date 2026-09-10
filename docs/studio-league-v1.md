# Studio League v1 — Participant + Match Ledger + Studio Elo + statistics

- **Status**: `AUTHORIZED` (owner pre-authorized implementation end-to-end: "直接授权实施，不需要再回来问设计确认").
  Implementation in progress. No part of this round is `VERIFIED` or `ACCEPTED` yet.
- **Baseline**: `3468046` (`main == origin/main`; Replay Studio Product Shell / History v1 ACCEPTED/CLOSED).
- **Owner-date**: 2026-09-10, product owner, in the Studio League design conversation.
- **Round type**: product milestone (not strength research). Explicit pause on S4 / D-P tuning / evaluator research continues.

## Problem and evidence

`/ratings` is a **frozen-tournament report viewer**, not a league. `RatingReportV1`
(`crates/splendor-eval/src/rating.rs:129`) is built around a fixed round-robin plan, one canonical
`EvaluationReportV1` per pair, and two batch statistics (`live_elo`, `official_elo`). It cannot
represent a human player at all: `RatedAgentV1` (`rating.rs:39`) requires an executable
`command: AgentCommand` plus runtime/policy/checkpoint identity.

Consequences measured in this round's read-only inventory:

| Fact | Measured value |
| --- | --- |
| JSON documents under `benchmarks/` + `local-artifacts/` | 143,456 (32.9 GB) |
| `effective-splendor-arena-report` documents | 48,273 |
| `effective-splendor-replay` documents | 48,278 |
| Arena outcomes | completed 48,050 · aborted 221 · truncated 2 |
| Matches with a sibling `*.replay.json` on disk | 48,069 / 48,273 (99.6%) |
| Completed matches with a replay | 48,050 |
| Total replay bytes | **0.15 GB** (avg 3 KB/file) |
| Distinct `replay_final_hash` | 37,655 (10,395 repeated occurrences) |
| Distinct replay file SHA-256 | 41,525 (of 48,069 files) |
| Distinct `game_id` | 22,294 (25,979 duplicated ⇒ **not a usable key**) |
| Distinct participant identities (`agent_name@agent_version`) | 69 |
| Seats with no identity at all | 406 seats / 214 matches |
| Distinct unordered participant pairs | 316 |
| Human-play replays | 10 replays · 6 `.meta.json` · **4 without meta** |

Two corrections to the design assumptions this inventory produced:

1. **Most historical arena data is NOT result-only.** 99.6% of arena matches have a full ReplayV1
   beside them. "RESULT_ONLY" is the exception (204 matches, plus the 406 identity-less seats), not
   the rule.
2. **The replay corpus is cheap.** 0.15 GB for ~48k replays. The 32.9 GB corpus bulk is
   m39a/m40a trajectory and materialization sidecars, not replays — so the owner's preferred
   content-addressed replay archive is affordable rather than a multi-GB copy.

Scale caveat that the owner must see: **25,622 of 48,273 matches (53%) are
`m35a-direct-agent-v1@M25-D2-v2` played against itself**, and two more self-play blocks
(`m46a-n1-selfplay` 2,560; m39a self-play 288) follow. A literal reading of the owner's eligibility
list would make every one of them an Elo event.

Evidence basis: read-only scan of every `*.json` under `benchmarks/` and `local-artifacts/`
(paths/names/sizes, `JSON.parse` + `.format` dispatch), writing
`local-artifacts/studio-league/inventory.jsonl` (48,273 rows, 40.6 MB, local-only). Reproduce with
`splendor studio-league-inventory --json` once commit A lands the durable command; the ad-hoc scan
above read only documents ≤ 40 MB and skipped `node_modules`, `.git`, `.uv-cache`,
`m24-torch-cu124`, and the architecture-html artifacts.

## Initial design

A long-lived league layer **beside** the research rating layer; nothing existing is rewritten.

```text
Actual match ───┬─ Research experiment view   (unchanged, frozen)
                ├─ Replay viewer              (/replay, unchanged)
                ├─ Review                     (/review, unchanged)
                ├─ League / Studio Elo        (new)
                └─ Participant statistics     (new)
```

```text
match finishes → canonical MatchRecord → Studio League ledger → rating/stat/replay immediately available
```

Data layer: SQLite as a **derived long-term index**; the original ReplayV1 / arena report /
evaluation artifacts stay the source evidence. The DB may be deleted and rebuilt at any time.

```text
local-artifacts/studio-league/league.sqlite3     derived, rebuildable
local-artifacts/studio-league/replays/<sha256>.json   content-addressed replay archive
```

Core tables: `participants`, `participant_aliases`, `matches`, `match_seats`,
`match_gameplay_stats`, `rating_events`, `league_meta` / `ingest_sources`.

## Scope and non-goals

Five natural commits, one product milestone (not five separately-approved rounds):

- **A. League core** — Participant / Match Ledger / SQLite schema / rating eligibility /
  deterministic Elo events + the durable read-only `studio-league-inventory` command.
- **B. Historical migration** — inventory-driven import, participant alias resolution,
  replay-backed + result-only handling, idempotent reconciliation.
- **C. Runtime ingestion** — human-play completion ingest, one central arena/evaluation completion
  outlet, persistent replay archive, Studio Host APIs, startup reconcile safety net.
- **D. Product UI** — `/ratings` → League leaderboard, `/ratings/participants/<id>` detail,
  match history / H2H / scoring stats, research reports preserved as `/ratings/reports`.
- **E. Play UX** — remove the duplicated "Earlier games" block, seat default Random, Randomize-seed
  button, live post-game Elo delta.

Non-goals (frozen): no rewrite or semantic change to `RatingReportV1` / `RatedAgentV1`; no
recomputation of M16/M19/M22 numbers; no new Arena runs to "validate" the League; no S4 / D-P /
evaluator research; no arbitrary ReplayV1 upload; no external account system; no deletion or
pagination features in this round.

## Contracts and invariants

The owner's frozen boundaries, verbatim in intent:

1. **Every completed match enters the Ledger; only eligible matches enter Studio Elo.**
2. **Every future eligible match keeps its ReplayV1** (content-addressed archive).
3. **Old research artifacts are never rewritten; old official rating reports are never
   recomputed.**
4. **Human identity never goes into `RatedAgentV1`** — a separate `Participant` layer with
   `Human` / `Engine` kinds.
5. **Missing human metadata is never auto-assigned** to the local profile.
6. **Engines are counted by exact policy identity**; display-name collisions never auto-merge;
   merging is only ever an explicit `participant_aliases` row.
7. **No fabrication of Tier/Noble statistics for replay-less matches.**
8. **Elo has exactly one implementation, in the Rust backend**; the frontend only displays.
9. **Studio Elo ≠ `official_elo`** (order-independent batch Bradley–Terry on a frozen pool). Both
   names are kept distinct in code, JSON, and UI.
10. **Elo order is determined by a stable `league_seq`**, not by thread/arrival order, so Elo
    history is reproducible after a rebuild.

Additional invariants introduced by this round:

11. `rating_eligible = false` for: invalid/failed replay verification, aborted, truncated
    (ply-cap/non-termination), excluded-prefix, differing ruleset fingerprint, diagnostic or
    altered-config agents, unresolvable identity, and — **new, see Deviations** — self-matches where
    both seats resolve to the same participant.
12. `match_gameplay_stats` exists only for replay-backed matches; its rows carry
    `metric_integrity` and the invariant
    `tier1_vp + tier2_vp + tier3_vp + noble_vp == final prestige` is asserted, never silently patched.
13. Average ending round is derived from a real `main_turn_count`, never from `completed_plies`
    (follow-up decision phases make one turn several recorded decisions).
14. The importer is **fail-closed**: an unknown or malformed document raises a clear error and
    changes nothing; it never partially imports.

## Implementation plan

1. Milestone document (this file) with the frozen scope, contracts and gates. ✅
2. Read-only historical match inventory, recording candidate/replay-backed/result-only/invalid/
   duplicate and identity-resolution counts. ✅ (evidence above)
3. Commit A — League core crate + SQLite schema + eligibility + deterministic Elo + durable
   inventory command.
4. Commit B — migration on top of the inventory; aliases; idempotent reconcile.
5. Commit C — runtime ingestion + replay archive + Host APIs.
6. Commit D — League UI.
7. Commit E — Play UX.
8. Reconcile docs, record validation evidence, update `handoff.md`, push.

## Iteration log

- 2026-09-10: Round authorized as a product milestone; owner supplied the frozen scope and
  boundaries above and required the ordering *documentation → read-only inventory → data model*,
  explicitly forbidding "just add a few fields to the existing `/ratings` page".
- 2026-09-10: Reconnaissance found two blockers that changed the plan (see Deviations):
  `crates/splendor-league` already exists, and the workspace has no SQLite dependency.
- 2026-09-10: Inventories run (two passes; the first mis-assumed arena reports were multi-match
  collections when in fact each `*.report.json` is exactly one match, and the outcome key is
  `outcome.status`, not `outcome.kind`). Corrected counts are the table above.

## Deviations (decided under the owner's standing pre-authorization)

**D1 — the new crate cannot be called `crates/splendor-league`.**
That path is already the **M11 research self-play league** (`LeagueManifestV1`,
`TrainingDatasetV1`, `arena_report_document_hash_v1`; consumed by `splendor-analysis`,
`splendor-cli` (`league_command.rs`, `learning_command.rs`, `m39a_command.rs`),
`splendor-learning`, and `tests/league_cli.rs`). Overloading it would either break those contracts
or make one crate serve two unrelated meanings. The Studio League layer therefore lands in
**`crates/splendor-studio-league`**, table/type names prefixed `Studio…` where a collision is
possible. No existing file or export is touched.

**D2 — `rusqlite` (`bundled`) becomes the workspace's first native dependency.**
Verified before committing to it, not assumed: `rusqlite 0.40.2 + bundled` compiles in a throwaway
project in **12.84 s** on this machine using the locally installed MSVC toolchain
(`C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools`, VC/Tools/MSVC/14.29.30133,
`cl.exe` + `link.exe` Hostx64/x64; `vswhere.exe` present, so the `cc` crate's own detection works).
crates.io is reachable; `rusqlite`/`libsqlite3-sys` were not in the 364-crate local cache. Cost: one
C compilation at first build, and a C toolchain requirement for everyone building the workspace.
`uuid` and `chrono` are absent from the lockfile, so participant UUIDs use `getrandom`/`rand`
(already resolved: `getrandom 0.2.17`, `rand 0.8.7`) and timestamps use `SystemTime` epoch seconds,
matching existing code — no extra dependency.

**D3 — self-matches are recorded but not rating-eligible.**
53% of the historical corpus is one participant against itself. Rating a participant against
itself produces no meaningful Elo event (expected 0.5 for both seats ⇒ net zero) while inflating
games/W-T-L and burning ~25k `rating_events`. They stay in the Ledger with `recorded = true` and
`rating_eligible = false`, which is a refinement of boundary 1 rather than a departure from it: the
owner's exclusion list is a family of "must not pollute Studio Elo" cases and this belongs to it.
**Flagged for the owner to veto** — it is one predicate in `eligibility.rs`, trivially reversible.

## Validation and evidence

_(filled in per commit; nothing here is claimed as run until it has been run)_

## Result and decision

`AUTHORIZED`; implementation in progress. No verdict is claimed.

## Known limitations

- The inventory is a point-in-time scan of this machine's `local-artifacts/`; corpora are
  local-only and not part of the repository.
- 204 arena matches have no replay and 406 seats carry no identity; these must stay visible as
  `RESULT_ONLY` / `unmapped` rather than being guessed.
- `game_id` is not unique (25,979 duplicates), so ingest keys on content identity
  (`replay_final_hash` / replay document hash) plus source path — never on `game_id`.
- The Studio Elo pool is not comparable to `official_elo` pools; the two must never be rendered in
  one column.

## Next authorized gate

Owner review of commit A (League core) once it lands. The owner pre-authorized the whole round, so
the working expectation is continuous progress through A→E followed by one owner closure review —
not per-commit approval.
