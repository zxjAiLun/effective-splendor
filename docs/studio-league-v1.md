# Studio League v1 — Participant + Match Ledger + Studio Elo + statistics

- **Status**: `AUTHORIZED` (owner pre-authorized implementation end-to-end: "直接授权实施，不需要再回来问设计确认").
  **Commit A** landed as `9f88aca`, the owner's review returned **`REPAIR_REQUIRED`**
  (P0=0, P1=5), and **Commit A Repair 1 is `IMPLEMENTED` / `VERIFIED`** — see the repair
  section below. Commits B–E are not started. Nothing here is `ACCEPTED`.
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
| Matches bounding a real ReplayV1 (content join on `final_state_hash`) | **48,050 / 48,273 (99.5%)** |
| Matches with the colocated `<stem>.replay.json` naming convention | 3,594 (7.4%) |
| Completed matches lacking a replay | **0** |
| Replay documents · distinct sha256 · distinct `final_state_hash` | 48,278 · 43,192 · 37,883 |
| Total replay bytes | **0.15 GB** (avg 3 KB/file) |
| Distinct match binding hash (`replay_final_hash`) | 37,655 (10,395 repeated occurrences) |
| Distinct `game_id` | 22,294 (25,979 duplicated ⇒ **not a usable key**) |
| Distinct participant identities (`agent_name@agent_version`) | 68 |
| Seats with no identity at all | 406 seats / 214 matches |
| Distinct unordered participant pairs | 316 |
| Human-play replays | 10 replays · 6 `.meta.json` · **4 without meta** |

Three corrections to the design assumptions this inventory produced:

1. **Replay coverage is essentially total, but not where the filenames suggest.** 48,050 of
   48,273 matches (99.5%) bind a real ReplayV1 — and the 223 that do not are *exactly* the 221
   aborted + 2 truncated matches, which carry no `replay_final_hash` at all. So **every completed
   match has a replay; zero completed matches are result-only.** However only 3,594 matches (7.4%)
   use the colocated `<stem>.report.json` + `<stem>.replay.json` convention; the rest are bound by
   *content* (`final_state_hash`), because corpora like `m41a-corpus` store
   `game-NNNN/{arena-report.json, replay.json}` and `m40a-run` nests them yet differently. The
   importer must therefore bind on the hash, never on a filename — see the iteration log for the
   measurement error that made this look like a filename question.
2. **"RESULT_ONLY" is a category for aborted/truncated and identity-less matches, not for the
   archive as a whole.** It is the exception (223 matches, plus the 406 identity-less seats).
3. **The replay corpus is cheap.** 0.15 GB for ~48k replays. The 32.9 GB corpus bulk is
   m39a/m40a trajectory and materialization sidecars, not replays — so the owner's preferred
   content-addressed replay archive is affordable rather than a multi-GB copy.

Scale caveat that the owner must see: **25,622 of 48,273 matches (53%) are
`m35a-direct-agent-v1@M25-D2-v2` played against itself**, and two more self-play blocks
(`m46a-n1-selfplay` 2,560; m39a self-play 288) follow. A literal reading of the owner's eligibility
list would make every one of them an Elo event.

Evidence basis: the durable read-only command landed in commit A,
`splendor studio-league-inventory --json <path> --jsonl <path>`, which scans every `*.json` under
`benchmarks/` and `local-artifacts/`, prints the summary above and writes the per-match rows
(`local-artifacts/studio-league/inventory.jsonl`, 48,273 rows, local-only). Measured output:

```text
documents: seen 143457 · parsed 143420 · unparseable 0 · skipped-too-large 37
candidate matches: 48273 · replays 48278 · evaluation reports 112
outcomes: aborted 221 completed 48050 truncated 2
replay coverage (content join on final_state_hash): bound 48050 · unbound 223 · no binding hash 223
replay coverage (colocated <stem>.replay.json convention): present 3594 · absent 44679
replay documents: 48278 · distinct sha256 43192 · distinct final_state_hash 37883
duplication: match binding hash distinct 37655 (repeats 10395) · game_id distinct 22294 (duplicates 25979)
identity: distinct participants 68 · unmapped seats 406 · matches with an unmapped seat 214 · distinct pairs 316
```

The scan skips `node_modules`, `.git`, `.uv-cache`, `m24-torch-cu124`, and the architecture-html
artifacts, and skips documents above 40 MB (37 of them).

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
local-artifacts/studio-league/identity.json      durable, user-authored identity state
local-artifacts/studio-league/replays/<sha256>.json   content-addressed replay archive
```

Because the index is derived, everything it cannot re-derive from the corpus lives in the identity
manifest: the local human participant id and display name, and the explicit `participant_aliases`.
Engine participant ids are **derived** from the exact identity key
(`sha256("studio-league-participant-v1\n" + identity_key)[..32]`, prefixed `eng-`), so they rebuild
for free. `league_seq` likewise comes from an explicit canonical sort
([`canonical_league_order`](../crates/splendor-studio-league/src/ledger.rs)), never from filesystem
traversal order. The rating config is frozen in `league_meta` on first ingest.

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
    altered-config agents, unresolvable identity, and self-matches where both seats resolve to the
    same participant (deviation D3, **approved by the owner**).
12. **Rebuildability.** Deleting the index and replaying the same corpus with the same identity
    manifest reproduces identical participant ids, aliases, league ordering and Elo history.
13. **The rating config cannot drift.** The first ingest freezes `StudioRatingConfigV1` in
    `league_meta`; every later ingest and every rebuild must match it exactly or fail closed with
    zero mutation; `rebuild_ratings` reads the stored config rather than trusting its caller.
14. **No-result is never a loss.** Leaderboard W/T/L count **rated** matches only (a match that did
    not move Elo cannot appear as a win, tie or loss); `recorded_games` is a separate
    `COUNT(DISTINCT match_id)`, so a self-match adds one recorded game, not two seat rows.
15. **Idempotency means same-content**, not same-key. Each record carries
    `source_document_hash`; the same `(source_kind, source_identity)` with a different hash is a
    `SourceConflict` error, never a silent no-op.
16. **`rating_eligible` implies exactly two rating events.** A record is structurally validated
    before any write (seat count must equal `player_count`, seats unique, no winner outside
    `completed`, a `Verified` binding must be complete), and an eligible 1v1 match that cannot
    produce a pair event is an error rather than a silent skip.
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
- 2026-09-10: Inventories run (three passes). **Two measurement errors, both corrected and kept
  here on purpose.**
  (a) The first pass assumed each `*.report.json` was a multi-match collection and that the outcome
  key was `outcome.kind`; in fact each file is exactly one match, the outcome key is
  `outcome.status`, and the agent array is `agents[].agent_name/agent_version`. All counts in the
  table above are post-correction.
  (b) The second pass measured replay coverage with
  `sib = path.replace(/\.report\.json$/, '.replay.json')` and then `existsSync(sib)`. For arena
  reports whose filename does **not** end in `.report.json` (most of the corpus — e.g.
  `m41a-corpus/train/game-0000/arena-report.json`), the regex did not match, `sib === path`, and the
  file trivially "existed" — inflating coverage to 48,069/48,273 (99.6%). The durable Rust command
  disagreed (3,594), which exposed the bug. The honest resolution was to measure *both* things
  separately, because they are different questions: colocated-filename coverage is 3,594 (7.4%)
  while content-join coverage is 48,050 (99.5%), and **the importer must bind on
  `final_state_hash`.** The inventory command now reports both numbers side by side so the two can
  never be conflated again.
  (c) A third pass confirmed the join: every one of the 48,050 `replay_final_hash` values resolves
  to a real ReplayV1 `final_state_hash`, with zero unmatched.
- 2026-09-10 (owner review of `9f88aca`): **`REPAIR_REQUIRED`**, P0=0 / P1=5, all five in the
  long-term ledger semantics, scope kept narrow to identity/ledger truthfulness and explicitly
  forbidden from starting commit B. D1/D2 approved; D3 approved (no longer a veto invitation); the
  Elo extraction explicitly approved and left untouched. Repair 1 implemented and verified (see the
  repair section). Two extra defects were surfaced by the new tests during the repair: the alias
  foreign-key ordering trap, and the schema-version bump implied by adding `source_document_hash`.

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

**D3 — self-matches are recorded but not rating-eligible. APPROVED by the owner** (2026-09-10),
no longer a pending veto. 53% of the historical corpus is one participant against itself; rating a
participant against itself produces no meaningful Elo event (expected 0.5 for both seats ⇒ net
zero) while inflating games/W-T-L and burning ~25k `rating_events`. They stay in the Ledger with
`recorded = true` and `rating_eligible = false`. The residual risk the owner identified is not D3
itself but that the leaderboard could still let those matches pollute *recorded* W/T-L — addressed
by Repair 1 item 3 (rated W/T/L only).

## Commit A Repair 1 (owner review follow-up)

The owner reviewed `9f88aca` and returned **`REPAIR_REQUIRED`** — direction `APPROVED`, but
P0 = 0 / **P1 = 5**, all of them in the long-term ledger semantics of Commit A, to be fixed
*before* B rather than after C/D started depending on the APIs. D1 (`splendor-studio-league` split
from the M11 research league) and D2 (`rusqlite + bundled`) were approved as-is; the Elo extraction
was explicitly approved and left untouched.

| P1 | Problem | Fix |
| --- | --- | --- |
| 1 | "The DB is derived and always rebuildable" was false: participant ids were random UUIDs and the local human id/name, renames and aliases lived only in SQLite, so deleting the DB changed every id and discarded authored identity. `league_seq` was `MAX(seq)+1`, i.e. ingest order. | New durable `identity_manifest.rs` holds exactly the non-derivable authored state (local human id + display name, explicit aliases). Engine ids are derived from the identity key. `league_seq` for historical batches comes from `canonical_league_order` (played_at, source_kind, source_identity) via `ingest_batch_canonical`, which refuses a non-empty ledger. |
| 2 | `RATING_CONFIG_META_KEY` existed but was never written or checked, so K=32 today and K=64 tomorrow could write into one DB, and `rebuild_ratings(conn, config)` recomputed history with whatever the caller passed. | `ensure_rating_config` freezes the config on first use and exact-matches afterwards, failing closed with zero mutation. `rebuild_ratings(conn)` reads the stored config; `rebuild_ratings_with` proves equality first. |
| 3 | The leaderboard re-created the fabricated-result problem that `3468046` had just fixed: `recorded_games` counted seat rows (a self-match counted 2), and `losses = recorded − wins − ties`, so aborted/truncated/no-result matches became **losses**. | W/T/L are now **rated** records only (`rating_eligible = 1`); `recorded_games` is `COUNT(DISTINCT match_id)`; `rated_losses = rated_games − rated_wins − rated_ties`. |
| 4 | "Idempotent" silently swallowed source drift: the key hit returned `AlreadyPresent` without comparing content, and the record had no source document hash at all. | `StudioMatchRecordV1::source_document_hash` (new column, schema v2) plus `StudioLeagueError::SourceConflict`: same key + same hash ⇒ `AlreadyPresent`; same key + different hash ⇒ error. |
| 5 | No real fail-closed validation: eligibility only checked `participants.len() < 2`, so `player_count=2` with three seats could be marked eligible while the rating path produced no pair event; `Verified` was trusted with no structural binding. | `StudioMatchRecordV1::validate_for_ingest()` (seat count must equal `player_count`, seats unique, no winner outside `completed`, `Verified` requires a complete binding, `Unavailable` forbids any binding) and eligibility now requires an exact seat/player-count agreement. An eligible match that does not produce exactly two events is an error. |

Two further defects were found by the new tests while repairing:

- Declaring a manifest alias whose target participant the index had not created yet violated the
  `participant_aliases → participants` foreign key, i.e. the authored state could not be loaded
  before the corpus was. The FK is removed (the manifest is the authority for that mapping, and its
  target legitimately may not exist yet) and `resolve_engine_participant` now bootstraps an alias
  target on demand, registering the key being resolved as the canonical participant's identity so
  declaration order cannot change the outcome.
- `STUDIO_LEAGUE_SCHEMA_VERSION` moved 1 → 2 for the added `source_document_hash` columns and the
  alias FK removal. The version guard therefore rejects a stale v1 index, which is correct because
  the index is derived.

### The five sentences, and what proves each

The owner asked for these to be *true*, not for more tests, so each is bound to a named test:

| Sentence | Test |
| --- | --- |
| same evidence rebuilds same league | `same_evidence_and_manifest_rebuild_the_identical_league` — builds a temp-file DB, ingests 6 matches via `ingest_batch_canonical`, deletes the DB file, rebuilds from the **reversed** record slice, and asserts identical identity index, aliases, `(match_id, league_seq)` order, per-participant Elo history and leaderboard; plus an anti-vacuity assertion that a different participant set produces a different league |
| rating config cannot drift | `rating_config_cannot_drift` (K=64 rejected, `match_count`/`rating_event_count`/stored config all unchanged) and `rebuild_reads_the_stored_config_and_rejects_a_drifting_caller` (rebuild reproduces the identical snapshot; a drifting caller is refused; a DB with no stored config cannot be rebuilt) |
| no-result never becomes loss | `no_result_never_becomes_a_loss` (aborted + truncated + a self-match ⇒ `recorded_games == 3`, `rated_games = rated_wins = rated_ties = rated_losses = 0`; a self-match alone ⇒ `recorded_games == 1`) |
| same source key with changed content fails | `same_source_key_with_changed_content_fails` (identical content ⇒ `AlreadyPresent`; drifted hash ⇒ `SourceConflict`; counts and Elo unchanged) |
| `rating_eligible` implies exactly one valid 1v1 Elo update | `rating_eligible_always_implies_exactly_two_rating_events` (`rating_event_count == 2 × eligible_match_count`), `malformed_records_are_rejected_before_anything_is_written` (7 structural contradictions each rejected with nothing written) |

**Negative controls (run, then reverted).** To show the two highest-stakes tests are not vacuous,
each was checked against the defect it exists to catch:

- Replacing the derived engine id with a random UUID made `same_evidence_and_manifest_rebuild_the_
  identical_league` **FAIL**; restoring it made it pass. (`participant.rs` byte-identical afterwards,
  verified with `diff`.)
- Restoring the recorded-based loss computation
  (`rated_losses = recorded − rated_wins − rated_ties`) made `no_result_never_becomes_a_loss`
  **FAIL** with `left: 3, right: 0` — exactly the fabricated-loss bug; reverting made it pass.

## Validation and evidence

### Commit A (League core) — run 2026-09-10

| Command | Result |
| --- | --- |
| `cargo build -p splendor-studio-league` | ok (compiles the bundled SQLite amalgamation) |
| `cargo test -p splendor-studio-league` | **12 passed / 0 failed** (`tests/league_core.rs`) |
| `cargo build --bin splendor` (isolated `CARGO_TARGET_DIR`) | ok; 2 pre-existing warnings in `s2_census_command.rs` |
| `splendor studio-league-inventory` | output quoted in "Problem and evidence" |

The 12 gates cover: schema version + idempotent init; exact-identity keying (same key ⇒ same
participant, different version ⇒ different participant, a later label never renames); local human
profile created once and surviving a rename; the reserved unassigned-human pseudo participant; the
full eligibility matrix (10 cases, one per reason code); that Studio Elo reuses
`splendor_eval::elo_delta` exactly (1500/1500 K=32 ⇒ ±16, zero-sum, and equal to the frozen
function for three uneven pairs); that an eligible match writes two events and moves both ratings;
that aborted / invalid-replay / diagnostic / self-match / unmapped matches are all recorded yet move
nobody's rating; ingest idempotency on `(source_kind, source_identity)`; that
`rebuild_ratings` reproduces the identical event history for a 6-match round robin; monotonic
`league_seq`; and that only an explicit alias merges identities.

Not yet run (deferred to commits B–E): the historical import, the replay archive, the Host APIs, the
UI, and any browser check.

### Commit A Repair 1 — run 2026-09-10

| Command | Result |
| --- | --- |
| `cargo test -p splendor-studio-league` | **19 passed / 0 failed** (was 12; +7 repair/contract gates; the round-robin rebuild test was replaced by the stronger delete-and-rebuild proof) |
| `cargo test -p splendor-eval` | 37 passed / 0 failed (the Elo extraction stayed inert) |
| `cargo test -p splendor-cli --bin splendor` | 89 passed / 0 failed |
| `--test m19_result` / `--test m22_result` / `--test model_evaluation_contract` | 8 / 1 / 1 passed, 0 failed — frozen published numbers did not move |
| `cargo fmt --check -p splendor-studio-league` | clean |
| negative controls | both failed as required, then reverted (see above) |

Not yet run (deferred to commits B–E): the historical import, the replay archive, the Host APIs, the
UI, and any browser check. The `studio-league-inventory` command was re-run unchanged and still
reports the numbers quoted in "Problem and evidence".

## Result and decision

`AUTHORIZED`; implementation in progress. No verdict is claimed.

## Known limitations

- The inventory is a point-in-time scan of this machine's `local-artifacts/`; corpora are
  local-only and not part of the repository.
- 223 matches have no replay binding and 406 seats carry no identity; these must stay visible as
  `RESULT_ONLY` / `unmapped` rather than being guessed. The 223 are exactly the aborted and
  truncated matches.
- `game_id` is not unique (25,979 duplicates), so ingest keys on content identity
  (`replay_final_hash` / replay document hash) plus source path — never on `game_id`.
- Replay binding must be by `final_state_hash` content join, not by filename; only 7.4% of matches
  use the colocated naming convention.
- An alias declared *after* matches were ingested does not retroactively reassign those matches yet;
  Repair 1 makes the mapping load order-independent and makes an alias resolvable before its target
  exists, but reassigning already-ingested history remains commit B's job.
- `participant_aliases` intentionally has no foreign key to `participants`: the manifest is its
  authority and an alias target may legitimately be unseen until the corpus provides it.
- `detail_metrics_available` is still always false; `match_gameplay_stats` has no writer until
  commit B/C.
- The Studio Elo pool is not comparable to `official_elo` pools; the two must never be rendered in
  one column.

## Next authorized gate

Owner review of commit A (League core) once it lands. The owner pre-authorized the whole round, so
the working expectation is continuous progress through A→E followed by one owner closure review —
not per-commit approval.
