# Studio League v1 — Participant + Match Ledger + Studio Elo + statistics

- **Status**: `AUTHORIZED`.
  **Commit A** landed as `9f88aca` → Repair 1 `714bc5f` → Repair 2 `2501fe0` → Repair 2b `44c704b`.
  The owner independently reviewed `44c704b` and declared **Commit A — ACCEPTED / CLOSED**
  (P0=0/P1=0).
  **Commit B — Historical Migration** authorized: Slice 1 (ReplayV1 duplicate-preserving content index,
  portable logical source paths, content-only arena report resolver, canonical record builder outside
  `ledger.rs`, read-only 48,273-match dry-run, and forward/reverse root-order determinism digest gate)
  is now `IMPLEMENTED` / `VERIFIED`. No derived SQLite database has been created or modified yet.
- **Baseline**: `44c704b1c69f6e04b8c17484b362cd19051c8d09` (`main == origin/main`; Commit A ACCEPTED/CLOSED).
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
manifest: the local human participant id and display name, and the explicit identity aliases. An
alias is stored as `alias_key -> canonical_identity_key` (never as a participant id), and engine
participant ids are **derived** from the canonical identity key
(`sha256("studio-league-participant-v1\n" + identity_key)[..32]`, prefixed `eng-`), so an alias never
has to wait for its target row to exist and can never introduce an authored id. `league_seq`
likewise comes from an explicit canonical sort
([`canonical_league_order`](../crates/splendor-studio-league/src/ledger.rs)), never from filesystem
traversal order. The Studio Elo rating config is a **protocol constant**; `league_meta` keeps a copy
only as integrity evidence (Repair 2, P1-2).

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
   merging is only ever an explicit alias in the durable identity manifest, stored as
   `alias_key -> canonical_identity_key`, so the merged participant id is the one derived from the
   canonical key regardless of declaration order (Repair 2, P1-1).
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
13. **The rating identity is a protocol constant and cannot drift.** `ingest_match` accepts no
    caller config; `league_meta` records `StudioRatingConfigV1` as integrity evidence, and any
    mismatch with this build's protocol fails closed with zero mutation. A rebuild therefore needs
    the same corpus and the same manifest and *nothing* the caller remembers (Repair 2, P1-2).
14. **No-result is never a loss.** Leaderboard W/T/L count **rated** matches only (a match that did
    not move Elo cannot appear as a win, tie or loss); `recorded_games` is a separate
    `COUNT(DISTINCT match_id)`, so a self-match adds one recorded game, not two seat rows.
15. **Idempotency means same-content**, not same-key. `source_document_hash` is **required** and
    validated as 64 lowercase hex, so `None == None` can never make two different hashless
    documents look idempotent; the same `(source_kind, source_identity)` with a different hash is a
    `SourceConflict` error, never a silent no-op (Repair 2, P1-3).
16. **`rating_eligible` implies exactly two rating events.** A record is structurally validated
    before any write (seat count must equal `player_count`, seats unique, no winner outside
    `completed`, a `Verified` binding must be complete), and an eligible 1v1 match that cannot
    produce a pair event is an error rather than a silent skip.
17. `match_gameplay_stats` exists only for replay-backed matches; its rows carry
    `metric_integrity` and the invariant
    `tier1_vp + tier2_vp + tier3_vp + noble_vp == final prestige` is asserted, never silently patched.
18. Average ending round is derived from a real `main_turn_count`, never from `completed_plies`
    (follow-up decision phases make one turn several recorded decisions).
19. The importer is **fail-closed**: an unknown or malformed document raises a clear error and
    changes nothing; it never partially imports. `ingest_batch_canonical` therefore shares ONE
    transaction for the whole batch, so a failure at record N rolls back records 1..N-1
    (Repair 2, P1-4).
20. **Identity recovery is fail-closed.** `load_or_recover` returns `None` only when primary,
    `.tmp`, and `.bak` are all absent. If any identity evidence exists but no candidate validates,
    it errors without replacing the bytes or minting a new local-human id (Repair 2b, P1-1).
21. **Aliases are direct.** Every accepted `canonical_identity_key` is terminal — it must not also
    appear as an alias key. Chains and cycles are malformed V2 manifests, so the intentionally
    one-hop resolver cannot split one identity into two (Repair 2b, P1-2).
22. **No normal public authority bypass.** The only local-human DB writer is crate-private and is
    reached through `sync_identity_manifest`; the rating-event writer is private and receives the
    protocol config only from ledger internals (Repair 2b, P1-3).

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
- 2026-09-11 (owner re-review of `714bc5f`): **`REPAIR_REQUIRED`** again, P0 = 0 / P1 = 4 / P2 = 1,
  all on authority / ingestion seams rather than the ledger's core semantics. Commit A Repair 2
  implemented and verified (see its section below): an alias is `alias_key -> canonical_identity_key`
  with one resolution path, the Studio Elo config is a protocol constant rather than stored caller
  input, `source_document_hash` is required and hex-validated (schema v3), `ingest_batch_canonical`
  shares one transaction, and the identity manifest replaces via a synced `.tmp` plus `.bak` with
  recovery. 24 tests pass (19 -> 24) with three negative controls.
- 2026-09-11 (owner review of `2501fe0`): Repair 2's four principal fixes all **PASS**, but Commit A
  remains `REPAIR_REQUIRED` for a narrow close patch (P0=0/P1=3/P2=1): damaged identity evidence
  could be mistaken for first launch; aliases could target another alias; and two public write APIs
  bypassed the manifest/protocol authorities. Repair 2b seals those three boundaries, adds exactly
  two targeted tests, fixes the duplicated invariant numbering, and does not start commit B.
- 2026-09-11 (owner final review of `44c704b`): **Commit A ACCEPTED / CLOSED** (P0=0 / P1=0).
  Authoritative closure statements confirmed: corrupt identity evidence never creates a new identity;
  every accepted alias points directly to one canonical identity; authored identity / Elo mutation
  has no normal public bypass. Commit B authorized.
- 2026-09-11: **Commit B Slice 1 (Content Index + Resolver + Canonical Record Builder + Full Dry-Run)**
  implemented and verified. Replay content index preserves all candidates per `final_state_hash`;
  source identity uses portable `logical namespace + normalized relative path` (no machine drive letters
  or repo roots); resolver verifies ReplayV1 strictly by content and binds candidates deterministically
  by `(document_sha256, logical_path)` without filename fallback; aborted/truncated remain valid
  result-only records; canonical builder lives outside `ledger.rs`; full read-only dry-run executed on
  all 48,273 historical reports with 0 builder failures and 0 malformed records; root-order determinism
  gate proven identical between forward and reverse directory traversals.

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

## Commit A Repair 2 (second owner review follow-up)

The owner re-reviewed `714bc5f` and returned **`REPAIR_REQUIRED`** again: P0 = 0 / **P1 = 4** /
P2 = 1. Repair 1 had already fixed the body of the five original findings; what remained were four
authority / ingestion seams that were not sealed. Scope stayed narrow — no commit B, no replay
resolver, no historical alias census, no gameplay stats, no Host API.

| P1 | Problem | Fix |
| --- | --- | --- |
| 1 | The alias fix was bypassed on the real path: `ingest_match_ordered` resolved the alias itself and returned early, so `resolve_engine_participant`'s bootstrap never ran; and the bootstrap registered the *alias* key as the canonical participant's identity. | An alias is now `alias_key -> canonical_identity_key`, and the participant id is always derived from the canonical identity key — in the manifest and in the index. The ledger's duplicate lookup is gone, so seat resolution has exactly one path. `alias_participants` and `rename_participant` were removed: no authored state may exist only in the deletable index. |
| 2 | "Delete the DB and rebuild" still needed a third input: `StudioRatingConfigV1` lived only in the deletable `league_meta`, so a caller had to remember K. | Studio Elo v1's config is a protocol constant (`protocol_rating_config()`). `ingest_match`, `ingest_batch_canonical`, `rebuild_ratings`, `leaderboard`, `participant_elo` and `preview_eligibility` take no config; `league_meta` keeps it as integrity evidence, and a mismatch with the build fails closed with zero mutation. |
| 3 | `source_document_hash` was `Option<String>` and unvalidated, so `None == None` let two different hashless documents share one key and be swallowed as `AlreadyPresent`. | The field is a required `String`, validated as 64 lowercase hex in `validate_for_ingest`, with `NOT NULL` columns (schema v3). A source without a stable content hash is un-ingestable. |
| 4 | `ingest_batch_canonical` looped `ingest_match_ordered`, and each iteration opened its own transaction: a failure at record 20,001 left the first 20,000 committed, contradicting the documented fail-closed import promise. | `ingest_match_in_tx` is the transaction-scoped primitive. `ingest_match_ordered` = one match / one transaction; `ingest_batch_canonical` = one transaction for the whole batch, so any failure rolls back participants, config evidence, matches, seats and rating events together. |
| P2 | The manifest's "atomic save" was write-temp → remove → rename, so a Windows crash inside that window deleted the only user-authored identity authority. | `save` writes and syncs `.tmp` before touching the primary, keeps a `.bak` of the previous contents, and `load_or_recover` recovers from primary → `.tmp` → `.bak` and heals the primary. |

This supersedes Repair 1's "remove the alias foreign key and bootstrap the alias target" approach:
both the FK and the bootstrap disappear, because the durable mapping no longer names a participant id
at all.

### The new gates, and what proves each

| Sentence | Test |
| --- | --- |
| an alias resolves identically whichever key is seen first | `alias_resolution_does_not_depend_on_which_key_appears_first` — builds the alias-first and canonical-first cases, asserts one derived id, asserts the row carries the canonical `identity_key`, and asserts an alias-first *ingest* creates no third participant |
| a rebuild needs no out-of-band rating config | `rating_reads_and_rebuild_need_no_caller_config`, plus the delete-and-rebuild proof below (every ingest/rebuild/read call compiles and runs with no config argument) |
| the stored config cannot silently disagree with the build | `rating_config_cannot_drift` — a drifted stored config is refused with zero mutation, and a rebuild refuses that database |
| a source without a valid content hash is refused | `a_source_without_a_valid_document_hash_is_refused` — eight malformed forms (empty, blank, short, uppercase, non-hex, 63 chars, 65 chars, trailing `g`), each rejected with nothing written |
| a late batch failure imports nothing | `a_late_batch_failure_rolls_the_entire_batch_back` — record 3 conflicts with record 1; asserts 0 matches, 0 rating events, 0 participants, 0 aliases and no config evidence survive, then the corrected batch succeeds |
| the manifest survives losing its primary | `the_identity_manifest_survives_losing_its_primary_file` — constructs the interrupted-replace state and the backup-only state; both recover the same hash and heal the primary |

**Negative controls (run, then reverted).** Each of the three highest-stakes gates was checked
against the defect it exists to catch:

- Restoring per-record transactions in `ingest_batch_canonical` made
  `a_late_batch_failure_rolls_the_entire_batch_back` **FAIL** (`no match may survive`: left 1,
  right 0).
- Making `canonical_identity_key` ignore aliases made
  `alias_resolution_does_not_depend_on_which_key_appears_first` **FAIL** (two different derived ids).
- Removing the `source_document_hash` validation made
  `a_source_without_a_valid_document_hash_is_refused` **FAIL**.

## Commit A Close Patch / Repair 2b

The owner reviewed `2501fe0` and confirmed that Repair 2's alias-first resolution, protocol rating
config, required source hash, and batch atomicity are all genuine and correctly directed. The
remaining verdict was a deliberately small close patch: **`REPAIR_REQUIRED`, P0=0 / P1=3 / P2=1**.
No exact-alias reconciliation, historical import, replay index, Host API, gameplay stats, or UI was
included.

| Item | Boundary left open | Close patch |
| --- | --- | --- |
| P1-1 | If primary, `.tmp`, and `.bak` were all unusable, `load_or_recover` returned `None`, and `load_or_create` treated damaged authority as first launch and minted a new local-human id. | The loader records whether *any* candidate exists. `None` now means all three are absent; existing-but-unrecoverable evidence returns `Invalid` without modifying any candidate. |
| P1-2 | V2 accepted `old -> middle -> current` and `a -> b -> a`, but runtime resolution intentionally follows one edge, splitting chains into multiple participants. | Validation now requires every `canonical_identity_key` to be terminal: no target may also appear in the alias-key set. Chains and cycles both fail closed. |
| P1-3 | `ensure_local_human` and the mutating `apply_rating_for_match(config, ...)` remained public/re-exported, bypassing the two newly established authorities. | The DB local-human writer is `pub(crate)` and only manifest projection calls it; the rating-event writer is private. Both re-exports were removed. |
| P2 | The invariant list repeated 12/13/14. | Renumbered continuously through 22. |

The requested closure statement is now an implementation contract:

> corrupt identity evidence never creates a new identity; every accepted alias points directly to
> one canonical identity; authored identity and Elo mutation have no normal public bypass.

Targeted proofs:

- `unrecoverable_identity_manifest_fails_closed_without_replacing_identity`: corrupt primary +
  invalid `.tmp` + absent `.bak` ⇒ error; primary and staging bytes unchanged; only after all three
  are absent does first-run creation succeed.
- `non_terminal_and_cyclic_aliases_are_rejected`: one test covers both chain and cycle manifests.
- `cargo check` / crate tests verify that removed public exports have no remaining consumer; a
  source-surface grep confirms neither mutating function is public/re-exported.

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

### Commit A Repair 2 — run 2026-09-11

| Command | Result |
| --- | --- |
| `cargo test -p splendor-studio-league` | **24 passed / 0 failed** (was 19; +5 repair gates; no existing gate weakened) |
| `cargo fmt --check -p splendor-studio-league` | clean |
| `cargo build --bin splendor` (isolated `CARGO_TARGET_DIR`) | ok; only pre-existing warnings in other crates |
| `cargo test -p splendor-eval` | 37 passed / 0 failed (the Elo extraction stayed inert) |
| `cargo test -p splendor-cli --bin splendor` | 89 passed / 0 failed |
| negative controls | all three failed as required, then reverted |

Not run in this repair (unchanged from Repair 1 and still deferred to B–E): the historical import,
the replay archive, the Host APIs, the UI, and any browser check. `m19_result` / `m22_result` /
`model_evaluation_contract` were not re-run because this repair touches no evaluation or arena code,
and the publish-frozen numbers were already proven inert in Repair 1.

`cargo build --bin splendor` against the shared `target/` failed at the final step with
`failed to remove ...\target\debug\splendor.exe: 拒绝访问 (os error 5)` — a Windows file lock on the
previously built executable, not a compile error. The isolated-target build succeeded, matching the
Repair 1 procedure.

### Commit A Close Patch / Repair 2b — run 2026-09-11

| Command | Result |
| --- | --- |
| `cargo test -p splendor-studio-league` | **26 passed / 0 failed** (24 → 26; exactly two targeted tests added) |
| `cargo fmt --check -p splendor-studio-league` | clean |
| `cargo test -p splendor-eval` | 37 passed / 0 failed; shared Elo arithmetic remains inert |
| `cargo test -p splendor-cli --bin splendor` (isolated `CARGO_TARGET_DIR`) | 89 passed / 0 failed |
| `cargo build --bin splendor` (isolated `CARGO_TARGET_DIR`) | PASS |
| `rg` public-surface check for `ensure_local_human` / `apply_rating_for_match` | no public function or crate-root re-export remains; only the manifest's distinct in-memory `ensure_local_human` authoring method is public |

GitHub had no status checks / workflow runs for `2501fe0`, so this section reports local evidence
only and makes no cloud-CI claim.

### Commit B Slice 1 — Full Historical Canonical Record Dry-Run (2026-09-11)

| Gate / Characteristic | Actual | Expected / Notes | Verdict |
| --- | ---: | ---: | :---: |
| source reports | 48,273 | 48,273 | **PASS** |
| canonical records built | 48,273 | 48,273 | **PASS** |
| builder failures | 0 | 0 | **PASS** |
| completed matches | 48,050 | 48,050 | **PASS** |
| completed + Verified replay | 48,050 | 48,050 | **PASS** |
| completed replay unresolved | 0 | 0 | **PASS** |
| aborted matches | 221 | 221 | **PASS** |
| truncated matches | 2 | 2 | **PASS** |
| unavailable replay | 223 | 223 | **PASS** |
| malformed canonical records | 0 | 0 | **PASS** |
| completed with >1 index candidate | 15,682 | reported | informational |
| completed with >1 verified candidate | 15,682 | reported | informational |
| selected distinct replay document SHA | 37,655 | reported | informational |
| distinct source document SHA | 42,521 | reported | informational |
| source-document SHA duplicates | 5,752 | reported | informational |
| unmapped seats | 406 | reported (214 matches) | informational |
| self-matches (1v1 same participant) | 31,598 | reported | informational |
| exact participant identities | 68 | reported | informational |
| canonical-record-set digest (forward) | `7a1ffd615bad76a1753959d602cc055005d757f895cfd24c67b54e628d153e57` | stable projection | **PASS** |
| reverse-root order digest | `7a1ffd615bad76a1753959d602cc055005d757f895cfd24c67b54e628d153e57` | identical | **PASS** |

Targeted test suite:
- `cargo test -p splendor-studio-league`: **32 passed / 0 failed** (historical_resolver: 3, league_core: 26, replay_index: 3).
- `cargo test -p splendor-cli --bin splendor`: **89 passed / 0 failed**.
- `cargo fmt --check -p splendor-studio-league`: clean.

## Result and decision

Commit A: `ACCEPTED / CLOSED` @ `44c704b`.
Commit B Slice 1: `IMPLEMENTED / VERIFIED`. Dry-run gates and root-order determinism pass completely.
Next step: proceed to migration CLI (`ingest_batch_canonical`) on an empty database.

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
- 5,752 historical arena reports share byte-for-byte identical document content with another report
  occurrence, confirming that `(source_kind, source_identity)` with normalized logical path must be
  the occurrence identity, while `source_document_hash` provides mandatory same-content / idempotency
  enforcement.
- `participant_aliases` stores `alias_key -> canonical_identity_key` with no foreign key: the
  manifest is its authority, and an alias target may legitimately be unseen until the corpus
  provides it. The participant id is derived from the canonical key, so nothing has to be
  bootstrapped or reconciled later.
- The identity manifest is replaced with remove + rename (Windows cannot rename over an existing
  file), so `save` leaves a synced `.tmp` and a `.bak`, and `load_or_recover` recovers from either
  and heals the primary (Repair 2, P2). `None` is reserved for the true first-run state where all
  three candidates are absent; any existing-but-invalid evidence fails closed (Repair 2b). A full
  filesystem-durability guarantee was explicitly out of scope: if all three files are physically
  lost, the manifest is gone.
- Authored state has exactly one writer. `alias_participants` and `rename_participant` were removed
  from the API, because a database-only alias or rename would silently vanish on the next rebuild.
- `detail_metrics_available` is still always false; `match_gameplay_stats` has no writer until
  commit B/C.
- The Studio Elo pool is not comparable to `official_elo` pools; the two must never be rendered in
  one column.

## Next authorized gate

Full dry-run gate completed and verified (48,273 / 48,050 / 223 / 0 failures / 0 malformed / forward-reverse digest identical).
Next authorized step: implement migration CLI command to perform `ingest_batch_canonical()` on an
initially empty derived SQLite database and report post-migration eligibility / rating reconciliation.
