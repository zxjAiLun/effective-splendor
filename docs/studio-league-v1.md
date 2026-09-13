# Studio League v1 — Participant + Match Ledger + Studio Elo + statistics

- **Status**: **Commit B — CLOSED** (historical migration complete: Slices 1–2 + Repair 1; the final
  migration passed the five-digest forward/reverse-root determinism gate — see "Commit B Slice 2
  Repair 1" and "Result and decision").
  **Commit A** landed as `9f88aca` → Repair 1 `714bc5f` → Repair 2 `2501fe0` → Repair 2b `44c704b`.
  The owner independently reviewed `44c704b` and declared **Commit A — ACCEPTED / CLOSED**
  (P0=0/P1=0).
  **Commit B — Historical Migration**: Slice 1 (ReplayV1 duplicate-preserving content index,
  portable logical source paths, content-only arena report resolver, canonical record builder outside
  `ledger.rs`, read-only 48,273-match dry-run, and forward/reverse root-order determinism digest gate)
  and Slice 2 (config-level policy identity, diagnostic classification, checked evidence writes)
  landed at `ddc938e`. The owner's final review returned **REPAIR_REQUIRED (P0=0 / P1=3)** — the
  ddc938e-era derived numbers (79 identities / 26,892 self-match / 13,747 eligible / 27,494 events)
  are **superseded**, never published as canonical. Slice 2 Repair 1 closed all three P1s (fail-closed
  config association, three-state seat attribution, unclassified-argv fail-closed, manifest-guard
  fail-closed), and the final migration passed the five-digest determinism gate (2026-09-13). The
  derived database is `local-artifacts/studio-league/league.sqlite3` (local-only, ignored).
  **Commit C — Runtime Ingestion** has started: Slice 1 (`2c9da0e`) was reviewed
  `REPAIR_REQUIRED` (P0=0/P1=3/P2=1 — runtime occurrence authority was not yet established);
  Repair 1 (`ec2cb98`) landed the durable occurrence envelope and was reviewed
  `REPAIR_REQUIRED` (P0=0/P1=2/P2=1 — the authority had not reached the official rebuild path);
  Repair 2 (`IMPLEMENTED` / `VERIFIED` locally, pending owner review) extends occurrence claims
  to exact sibling paths, makes the official `studio-league-migrate` rebuild
  `42,521 historical + N runtime`, and compares the full canonical key in the tail guard.
  No API/UI; no new Elo logic.
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

(Handshake-identity scan of 2026-09-11, recorded verbatim; the participant-identity and
eligibility semantics were superseded by Commit B Slice 2's config-level policy identity —
see the corrected dry-run and rebuild determinism gate below.)

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
    history is reproducible after a rebuild. For historical batches `league_seq` is
    content-derived: `canonical_league_order` sorts historical entries (whose `played_at` is
    `None`) by their `historical-sha256:<…>` source identity. The resulting Studio Elo is a
    **deterministic historical canonical-order Elo** — **not a chronology** and **not a
    strength-timeline verdict**.

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

- 2026-09-12 (Commit B Slice 2 P1 repair): configuration-level policy identity and diagnostic classification were added to the real historical import path. `match-config.json` is joined to arena reports by `game_id`; semantic strategy parameters are retained while run-only paths/seeds are excluded; unresolved seats remain explicitly unresolved and fall back only to the handshake identity for legacy reports without configuration. Explicit non-`full` attribution profiles are diagnostic. Regression coverage proves S0 `n1 vs M07` is not a self-match, M44A `drop_convertibility` is diagnostic while `full` is competitive, and no-config reports do not invent a policy identity. The migration report now returns failure when JSON evidence cannot be written.

## Commit B Slice 2 — P1 repair validation (2026-09-12)

The corrected full-corpus dry-run used the existing `benchmarks` and `local-artifacts` roots and produced the local-only evidence file `local-artifacts/studio-league/historical-migration-dry-run.json`.

| Gate / characteristic | Actual | Verdict |
| --- | ---: | :---: |
| source reports | 48,273 | PASS |
| canonical records | 42,521 | PASS under Distinct-Document policy |
| completed / verified replays | 42,303 / 42,303 | PASS |
| aborted / truncated / unavailable | 216 / 2 / 218 | PASS |
| builder failures / malformed records | 0 / 0 | PASS |
| config-resolved policy matches | 21,276 | measured |
| handshake-only matches | 21,245 | measured, no config evidence |
| diagnostic matches | 1,664 | measured and excluded by eligibility |
| exact participant identities | 79 | measured; replaces the old 68-count claim |
| self-matches | 26,892 | measured after policy identity resolution |
| unmapped seats / matches | 388 / 196 | measured |
| forward/reverse canonical digest | `ed00b68e46dc914e4860e9cf296793a559c99d92b55ec579020ab68064407d4d` | PASS |

Targeted validation: `cargo test -p splendor-studio-league --test policy_identity` passed 3/3; the full crate passed 45/45 across its unit and integration suites; `cargo test -p splendor-cli --bin splendor` passed 89/89; `cargo fmt --check -p splendor-studio-league -p splendor-cli` passed. A negative write-path check against an invalid JSON destination returned exit 2 with an explicit error instead of reporting success.

These are implementation and migration-evidence results, not an accepted public strength ranking.
**Superseded (2026-09-12):** the owner's final review of `ddc938e` returned `REPAIR_REQUIRED`
(P0=0 / P1=3) — the config association behind this table used `game_id` first-wins binding,
unresolved seats silently fell back to the handshake identity, and unclassified argv switches were
silently dropped. Every attribution-dependent number in this section (21,276 / 21,245 / 79 /
26,892) describes the pre-Repair-1 implementation result and is **not canonical**; see "Commit B
Slice 2 Repair 1" below for the accepted derived state.

### Rebuild determinism gate and promotion (2026-09-12, superseded by Repair 1)

> **Superseded record.** This gate proved rebuildability of the pre-Repair-1 attribution
> semantics and promoted that database the same day. The owner's final review then returned
> `REPAIR_REQUIRED` for the attribution layer itself (P1-1/P1-2/P1-3 below), so the counting
> values and DB digests in this section describe a superseded derived state and are kept only
> as the round's iteration history. The accepted record is the Repair 1 section that follows.

The derived database was rebuilt **from scratch** — same corpus roots (`benchmarks`,
`local-artifacts`), same identity manifest (`identity.json`), same code — into a fresh
`league.rebuild.sqlite3` (`studio-league-migrate`, 42,521 records ingested in atomic canonical
order), and compared against the corrected migration on **semantic state only**. SQLite file
bytes were deliberately not compared: page layout, freelist, and write-order details are not
league semantics.

Counting gates (expected value held in both databases): matches **42,521** · completed
**42,303** · aborted **216** · truncated **2** · exact policy identities (engine participants)
**79** · participants **80** (79 engine + local human) · self-match **26,892** · diagnostic
**1,664** · eligible **13,747** · rating events **27,494**. Arithmetic closure:
26,892 + 1,664 + 13,747 = 42,303 completed; 216 + 2 + 42,303 = 42,521; 27,494 = 2 × 13,747.

Semantic digests (SHA-256 over the canonical order defined per digest; **identical across the
two databases**):

| Digest | Rows | Value |
| --- | ---: | --- |
| match digest (`league_seq` → `match_id`, `source_identity`, `source_document_hash`, eligibility, reason) | 42,521 | `3135e949d2fcdf3bc82adb60f3aafd14469bbaea1f2b7da2f1f99d2597b5938c` |
| rating-event digest (`league_seq, participant_id` → `match_id`, `participant_id`, `opponent_id`, `elo_before`, `elo_after`, `delta`, `score`) | 27,494 | `c80892b8efc2120e84637c0e0eb80c46282514482d190cb6f88d854ae7fcc18d` |
| leaderboard digest (`participant_id` → elo, rated games, W/T/L, recorded games, provisional) | 80 | `4c165448c9c4037295019a6c86019d4ad2a808f20e004b135a5d37ec76b941a9` |

`PRAGMA integrity_check` returned `ok` and `PRAGMA foreign_key_check` returned 0 rows on **both**
databases; the identity manifest hash recorded in both is
`572faa16c70693d5778f3ad9e3cfdb5262ae50bfaff560717b2a9af7172e17e4`. Evidence:
`local-artifacts/studio-league/rebuild-determinism-report.json` (comparison result),
`historical-migration-rebuild.json` (rebuild reconciliation), `rebuild_determinism_gate.py`
(gate definitions).

On gate PASS the rebuild database was deleted, the corrected database was promoted to
`local-artifacts/studio-league/league.sqlite3`, and the superseded pre-policy-fix database was
deleted rather than archived: the gate proves it is exactly reproducible from the same evidence +
manifest + code, so keeping it would only invite treating a known-wrong derived state as
authoritative.

## Commit B Slice 2 Repair 1 — fail-closed policy attribution (2026-09-12/13)

The owner's final review of `ddc938e` returned **`REPAIR_REQUIRED` (P0=0 / P1=3 / P2=1)**:
rebuild determinism had proven the derived database reproducible, but the **attribution layer**
had three fail-open seams that the determinism gate could not see (two rebuilds bind the same
wrong config the same way). The three P1s:

1. **P1-1 — config association used non-unique `game_id` first-wins.** `game_id` is not a
   usable key (22,294 distinct across 48,273 reports), yet pass 1 kept the first config per
   `game_id` and pass 2 bound every same-`game_id` report to it. Repair: every parsed
   configuration is retained as a [`ConfigurationCandidateV1`], and
   [`associate_configuration`] binds a report only when **companion provenance** (a config in
   the same logical directory as the report) or **content consistency** (seat-count agreement,
   collapse of identical per-seat configurations, or the report's recomputed `seed_commitment`)
   selects exactly one distinct configuration. Conflicts fail closed to `Ambiguous`; scan order
   and path order are never authority.
2. **P1-2 — "unresolved does not guess" was not true.** The builder kept the handshake
   identity on every seat and the ledger fell back to it whenever the policy key was absent, so
   "unresolved" silently degraded to the coarse runtime identity; and an argv switch outside
   the frozen vocabulary was silently dropped, yielding a `Resolved` identity that could not be
   proven. Repair: seats carry a three-state [`SeatPolicyIdentityV1`]
   (`NoConfigEvidence` / `Resolved` / `Unresolved`); only `NoConfigEvidence` may fall back to
   the handshake identity, `Unresolved` stays unmapped (`unmapped_participant`, never rated);
   argv classification is a frozen vocabulary measured by census — an unclassified switch
   fails the seat closed.
3. **P1-3 — manifest hash guard was fail-open.** `sync_identity_manifest` read the match count
   with `.unwrap_or(0)`, so an unreadable ledger was treated as an empty one. Repair: the query
   error propagates; the guard's triangle (non-empty + changed hash → Err; non-empty + missing
   hash → Err; unreadable ledger → Err, zero mutation) is complete.
4. *(P2, process)* the repair touches only `splendor-studio-league` (+ the CLI command surface it
   owns); no workspace-wide formatting churn.

**Measured corpus facts the repair was built on (2026-09-12 census, production parsers):**
configuration documents are 19,299 (12,765 of them not named `match-config.json`; the earlier
6,534 count was filename-based); the argv vocabulary is exactly 26 `--` switches plus the `-m`
structural token, every one now explicitly semantic or run-only (`--plan-hash` was verified in
the m39a agent source to be a server ready-file identity check, i.e. run-only); 19,253 reports
have a single companion config and **all 19,253 reproduce the report's `seed_commitment` from
the companion's recorded seed (0 mismatches)**.

**Read-only reconciliation (accepted by the owner, 2026-09-12):** the repaired full-corpus
dry-run reproduced every locked evidence gate (42,521 / 42,303 / 216 / 2 / 0 malformed /
forward==reverse `ed00b68e…`) and measured the attribution change: **120** `game_id`s carry
distinct configurations; **113** matches have config evidence that no companion or seed
evidence can disambiguate and are `Ambiguous` (226 extra unmapped seats); **133** matches
whose `game_id` belongs to the conflict surface were still resolved deterministically by
companion/seed evidence; **0** bound configurations contain an unclassified switch;
self-match **26,521** (−371: ambiguous removal + previously-merged policies such as the m40a
arm A/arm B seats now distinct); exact policy identities **99** (+20); diagnostic unchanged
**1,664**.

**Final migration (authorized on dry-run acceptance; forward and reverse roots in parallel):**
`benchmarks,local-artifacts` → `league.candidate-repair1.sqlite3` and
`local-artifacts,benchmarks` → `league.rebuild-repair1.sqlite3` (61 min each). Locked values,
held by both databases: matches **42,521** · completed **42,303** · aborted **216** · truncated
**2** · verified replay **42,303** · unavailable **218** · exact/effective engine identities
**99** · local human **1** · participants **100** · self-match **26,521** · diagnostic
**1,664** · unmapped-participant matches **113** · total unmapped seats **614** (309 matches) ·
eligible **14,005** · rating events **28,010** · builder failures **0** · malformed **0**.
Closure: 26,521 + 1,664 + 113 + 14,005 = 42,303; 216 + 2 = 218; 28,010 = 2 × 14,005.

**Five-digest determinism gate — all identical across the two root orders:**

| Layer | Digest |
| --- | --- |
| evidence/document set (`canonical_set_digest`, unchanged since `ddc938e` by design) | `ed00b68e46dc914e4860e9cf296793a559c99d92b55ec579020ab68064407d4d` |
| policy attribution (`policy_attribution_digest`, new; per-seat state + resolved key, no prose) | `7b86a6b2de9fa4351c96788b912f0f63299212553fa31569b0771cc46eb44f8e` |
| match digest (DB, `league_seq`-ordered) | `9deb8f49f7ceea839c1c28f79be66e0c09da89edc7a9dff9a2b9de6dac1ecf3a` |
| rating-event digest (DB) | `168b9da1ace6a85817bafc40c72b3291ae9132dbdfe0cd1aa84259a0b6aef845` |
| leaderboard digest (DB) | `9b05a0b54bce8fe409678c469aa2661481755f6f30cd78ecee224b8e27da5a98` |

`PRAGMA integrity_check` = ok and `foreign_key_check` = 0 rows on both databases; manifest hash
`572faa16c70693d5778f3ad9e3cfdb5262ae50bfaff560717b2a9af7172e17e4` recorded in both. The gate
simultaneously proves that document set, policy attribution, derived ledger, Elo history, and
leaderboard are all independent of root traversal order. Evidence (local-only):
`historical-migration-dry-run-repair1.json`, `historical-migration-repair1.json`,
`historical-migration-repair1-reversed.json`, `rebuild-determinism-report-repair1.json`,
`rebuild_determinism_gate.py`.

On gate PASS (owner pre-authorization): the rebuild database was deleted, the candidate was
promoted to `local-artifacts/studio-league/league.sqlite3`, and the superseded
`ddc938e`-semantics database was deleted (reproducible from `ddc938e` itself). The temporary
census example was removed.

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
Commit B Slice 2 @ `ddc938e`: `IMPLEMENTED / VERIFIED` locally, but the owner's final review
returned **`REPAIR_REQUIRED` (P0=0 / P1=3)** — rebuild determinism proved reproducibility while
the attribution layer still bound configurations first-wins by `game_id`, degraded unresolved
seats to the handshake identity, silently dropped unclassified argv switches, and read the
ledger with a fail-open manifest guard. The ddc938e-era numbers (79 identities / 26,892
self-match / 13,747 eligible / 27,494 events) are **superseded**.
Commit B Slice 2 **Repair 1**: the three P1s were repaired fail-closed, the owner accepted the
read-only reconciliation, and the final migration passed the five-digest forward/reverse-root
determinism gate. **Commit B — `ACCEPTED / CLOSED`** (historical migration complete,
2026-09-13). The derived database is `local-artifacts/studio-league/league.sqlite3` with
42,521 canonical matches (85,042 seats), 99 exact/effective engine policy identities + the local
human (100 participants), 26,521 self-match, 1,664 diagnostic, 113 unmapped, 14,005 eligible
matches and 28,010 rating events. The leaderboard is a deterministic historical canonical-order
Studio Elo, not a chronology and not a strength baseline.

## Known limitations

- The inventory is a point-in-time scan of this machine's `local-artifacts/`; corpora are
  local-only and not part of the repository.
- 218 canonical matches have no replay binding; these must stay visible as `RESULT_ONLY` rather
  than being guessed. The 218 are exactly the 216 aborted and 2 truncated matches. A further 113
  completed matches carry configuration evidence that no companion or seed evidence can
  disambiguate, so all 614 unmapped seats (309 matches) stay explicitly unmapped — the ledger
  never guesses an identity to make a match rateable. (Slice 1 inventory values — 223 and
  406/214 — describe the pre-dedup scan and are superseded by the Distinct-Document policy.)
- `game_id` is not unique (25,979 duplicates) and is never a ledger or join key. A historical
  report's source identity is the document-SHA-derived `historical-sha256:<source_document_hash>`;
  the replay binds by `replay_final_hash` content, and paths are recorded as provenance only.
- Replay binding must be by `final_state_hash` content join, not by filename; only 7.4% of matches
  use the colocated naming convention.
- Alias projection changes never retroactively mutate a non-empty derived database. The manifest is
  the authority for `participant_aliases`, an alias is resolvable before its target exists, and the
  mapping is load-order-independent — but applying a manifest change means rebuilding the derived
  database from the corpus plus the updated manifest; an altered manifest hash on a non-empty ledger
  is rejected fail-closed.
- 5,752 historical arena reports are byte-for-byte identical copies of another report document.
  Under the Distinct-Document Evidence Policy these are provenance copies, not independent
  occurrences: one distinct document hash is one canonical record, so identical content can never
  be double-weighted, and `source_document_hash` stays mandatory schema evidence for every
  ingestable source.
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

## Commit C — Runtime Ingestion, Slice 1 (2026-09-13)

The owner authorized the first, deliberately narrow cut of runtime ingestion: **prove that one
just-finished real arena occurrence can enter the Studio League through the existing authority
chain — strict parse, replay verification, canonical record, the existing `ingest_match`,
eligibility, and 0 or 2 Elo events — without any corpus scan.** Everything verified in Commits
A/B is reused verbatim: participant resolution, the identity manifest, replay verification,
eligibility precedence, self-match and diagnostic exclusion, the single Elo implementation, the
ledger, and source idempotency. No API/UI; no new runtime Elo logic.

Landed in this slice:

- `runtime_match_record` builds the canonical record for one occurrence from its three
  documents — the arena report, the recorded ReplayV1, and the run's own `match-config.json`.
  The replay bytes are verified in place (full `verify_replay` plus the report/replay fact
  agreement used by the historical resolver); the configuration is bound as exact evidence only
  after its `game_id`, seat count, and `seed_commitment` reproduction all agree with the report.
- ~~Occurrence identity stays content-derived (`runtime-sha256:<…>`); `played_at` remains
  `None`.~~ **Superseded by Repair 1** — see below: identity now comes from a durable occurrence
  envelope, and `played_at` comes from its `completed_at`.
- ~~The ledger rejects a document hash already ingested under any occurrence identity.~~
  **Superseded by Repair 1**: that rule over-applied the historical Distinct-Document policy to
  the general ledger and was removed; occurrence authority is exactly `(source_kind,
  source_identity)`.
- `splendor studio-league-ingest --occurrence --report --replay --config [--identity --db --json]`
  drives the
  chain end to end through the same authority seams as the migration (protocol rating config,
  durable manifest with non-empty-ledger hash guard, single-match transaction) and writes a
  receipt (occurrence identity, outcome, eligibility, per-seat Elo deltas) read back from the
  ledger via `match_receipt`.
- Replay storage is `in_place_reference` in this slice; the content-addressed archive copy is a
  later Commit C slice.

Validation (local evidence): `cargo test -p splendor-studio-league` **53/53** including the new
`runtime_ingest` gates — end-to-end ingest of a fresh occurrence yields exactly 2 Elo events and
an eligible receipt, a re-offered occurrence is `AlreadyPresent` with no extra events, a tampered
replay/report and a foreign configuration are rejected fail-closed, and the same document under a
second occurrence identity is refused. `cargo test -p splendor-cli --bin splendor` **89/89**;
`cargo fmt --check` clean.

### Commit C Slice 1 Repair 1 — runtime occurrence authority (2026-09-13)

The owner's review of `2c9da0e` returned **`REPAIR_REQUIRED` (P0=0 / P1=3 / P2=1)**: the chain
worked, but "what makes a runtime occurrence" was not yet established. Repairs:

1. **P1-1 — the historical Distinct-Document rule had been promoted to a global ledger
   invariant.** Content equality is not occurrence equality: two genuinely played deterministic
   matches may produce byte-identical documents and are still two occurrences. The ledger-wide
   `source_document_hash` duplicate rejection was removed; the ledger's occurrence/idempotency
   authority is exactly Commit A's `(source_kind, source_identity)` (same identity + same
   document → `AlreadyPresent`; same identity + changed document → `SourceConflict`; different
   occurrence identities coexist). The Distinct-Document dedup stays where it belongs: the
   historical corpus builder, which lacks occurrence evidence.
2. **P1-2 — the runtime append order existed only in SQLite.** A durable
   [`RuntimeOccurrenceV1`] envelope is now the occurrence evidence, written by the harness at
   match completion: `occurrence_id` (harness-authored; `source_identity = runtime:<id>`, never
   content-derived) and `completed_at` (recorded once at completion, never invented at ingest
   time), plus the report/replay/config document SHAs which must match the provided bytes. The
   record's `played_at` is the envelope's `completed_at` — the Elo-ordering evidence that
   survives a database delete — and `build_historical_corpus` now discovers occurrence envelopes
   in the corpus roots, excludes their claimed report/config documents from the historical pass,
   and rebuilds runtime records from colocated evidence. A narrow tail guard rejects an
   incremental append whose `completed_at` is not strictly after the ledger's last occurrence
   (live append order == canonical rebuild order); out-of-order arrival requires a rebuild. The
   `studio-league-migrate` preflight still expects exactly the 42,521 historical records, so it
   fail-closed refuses once runtime occurrences enter its roots.
3. **P1-3 — the "triple config binding" allowed a missing seed to bypass the `seed_commitment`
   check.** A fresh runtime configuration must carry its `seed`; `seed = None` is rejected.
4. **P2 — a receipt export failure after the DB commit** now prints explicitly that the match
   was committed successfully and only the receipt export failed (re-offering the occurrence is
   a no-op), instead of implying a rollback.

Targeted gates: two different occurrence ids with byte-identical documents both enter the ledger
(4 rating events, two match identities); the same occurrence id is idempotent with the same bytes
and conflicts with changed bytes; deleting the database and rebuilding from the same occurrence
evidence reproduces the live ingest exactly (league_seq assignment, full Elo history, and
leaderboard identical, over a 3-fixture corpus); a seedless runtime configuration, a wrong seed,
and a tampered replay are rejected; an out-of-order append is rejected. A CLI smoke over a real
corpus match directory recorded `runtime:smoke-occ-1` with exactly 2 Elo events into a scratch
database. `cargo test -p splendor-studio-league` **56/56**; `cargo test -p splendor-cli --bin
splendor` **89/89**; `cargo fmt --check` clean.

### Commit C Slice 1 Repair 2 — occurrence authority through the official rebuild (2026-09-13)

The owner's review of the Repair 1 (`ec2cb98`) confirmed all three earlier P1s closed and
returned **`REPAIR_REQUIRED` (P0=0 / P1=2 / P2=1)** on two rebuild-integration seams:

1. **P1-1 — envelope claims were global by SHA.** A runtime envelope excluded *every* document
   with its report/config SHA from the historical pass, so a byte-identical historical match
   would have vanished from the rebuild. Claims are now resolved to the **exact sibling logical
   paths** inside the envelope's own directory (by SHA, within that directory), and the
   historical pass excludes only those exact paths. Content equality is not occurrence equality,
   at claim time either.
2. **P1-2 — the official `studio-league-migrate` still could not rebuild a league containing
   runtime occurrences** (its preflight hard-coded 42,521). The preflight is now split: the
   historical canonical record count stays locked at **42,521** (`historical_canonical_records_built`),
   runtime occurrences add `runtime_occurrences_built` on top, and `expected_total =
   42,521 + N` drives the record/unique-key gates. Post-migration reconciliation is total-aware:
   matches, seats (`canonical_seat_count`), verified replays, completed matches, and the
   eligibility breakdown sum reconcile against the report's totals, while the historical-only
   invariants (aborted 216, truncated 2, unavailable 218) stay locked. The structural gates
   (rating events = 2 x eligible, rated = eligible) are unchanged. A full rebuild of the official
   database therefore becomes possible from corpus + occurrence evidence + manifest.
3. **P2 — same-second occurrences were rejected outright.** The tail guard now compares the
   **full canonical key** `(played_at, source_kind, source_identity)`: same-second occurrences
   with a stable identity order append; only arrivals that would diverge from the canonical
   rebuild order fail closed.

Targeted tests (no 42k corpus run): the rebuild fixture now carries `old/` (a plain historical
match) plus `new-a/` whose documents are **byte-identical** to `old/`'s and carry a runtime
envelope - the rebuild returns 1 historical + 2 runtime records, all three present in the
ledger, and live append equals canonical rebuild (league_seq, Elo history, leaderboard identical);
the official migrate preflight split and total reconciliation follow the same counts; the
canonical-key tail gate accepts same-second identity-ordered appends and rejects divergent ones.
`splendor-studio-league` **56/56**; `splendor-cli` bin **89/89**; `cargo fmt --check` clean.

### Commit C Slice 1 Repair 3 / close patch — provenance copies are one occurrence (2026-09-13)

The owner's review of `e89ce8d` confirmed both Repair 2 main repairs (**PASS**: the official
`42,521 + N runtime` rebuild and the full canonical-key append guard) and returned
**`REPAIR_REQUIRED` (P0=0 / P1=1 / P2=0)** on one narrow remaining seam that would cause a
**rebuild double-count**:

1. **P1 — a duplicate runtime provenance copy leaked back into the historical pass.** The
   envelope dedup collapsed an occurrence to a *single* sidecar path, and claims were resolved
   only inside that one directory with the lexicographically first matching sibling. If a whole
   runtime run directory was archived or mirrored (`run-a/` plus `archive/run-a-copy/`, same
   `occurrence_id`, same report/config bytes), only the first directory was claimed; the copy's
   report/config fell through to the historical scan, the Distinct-Document rule counted that
   SHA as historical evidence, and the runtime pass separately built `runtime:X` - turning one
   real occurrence into two matches (`historical-sha256:H` + `runtime:X`). The same defect could
   trigger with two byte-identical report/config siblings in one directory.

Close patch (historical builder only; envelope format, `ledger.rs`, and the official migrate
reconciliation are untouched):

- `resolve_sibling` -> `resolve_siblings`, returning **every** matching sibling in logical path
  order instead of the single lexicographically first one.
- The occurrence map now carries the canonical envelope plus **all** provenance sidecar paths
  (`occurrences` + `occurrence_sidecars`); identical envelopes are provenance copies, a
  different envelope under the same id remains a builder failure.
- Claims iterate **every** provenance directory and claim **every** matching report/config
  path in each, so no copy can re-enter the historical pass.
- The runtime record is still built **exactly once** per occurrence; the bytes come
  deterministically from the first complete provenance copy (logical path order).

Contract now satisfied in both directions: different occurrence + identical content => two
matches; same occurrence + multiple provenance copies => one match.

Targeted gate (`archived_provenance_copies_of_one_occurrence_build_one_match`): a corpus with
`copy-a/` (occurrence envelope + a byte-identical duplicate report sibling) and `copy-b/`
(archive copy of the same occurrence) must report `runtime_occurrences_seen = 2`,
`runtime_occurrences_built = 1`, `historical_canonical_records_built = 0`, `records.len() = 1`,
and `source_identity = runtime:occ-copy-1`. Verified to fail against the pre-patch logic
(`historical_canonical_records_built` was `1`) and to pass after it.
`splendor-studio-league` **57/57**; `splendor-cli` bin **89/89**; `cargo fmt --check` clean;
`git diff --check` clean.

**Owner re-review of `1011607` (2026-09-13): `ACCEPTED / CLOSED` — P0=0 / P1=0 / P2=0.** The
provenance-copy seam is closed: an occurrence now keeps its canonical envelope **and all** of its
provenance sidecar paths, claims cover **every** provenance directory and **every** matching
report/config sibling, and the runtime record is still built exactly once from the first complete
provenance in deterministic path order. The owner confirmed the two symmetric rules now hold
(`different occurrence + identical content => two matches`; `same occurrence + multiple copies =>
one match`) and that the scope stayed clean (one commit, `e89ce8d -> 1011607`, only
`historical_import.rs` / `runtime_ingest.rs` / this document; ledger, migrate reconciliation, and
the envelope format were not re-disturbed). **Commit C Slice 1 is CLOSED.** 57/57, 89/89, fmt, and
diff-check remain **local validation evidence**; there are no cloud status checks for this commit
and no CI is claimed.

## Next authorized gate

Commit B (historical migration) is **CLOSED**. The derived database
`local-artifacts/studio-league/league.sqlite3` (local-only, ignored) holds the accepted derived
state: 42,521 canonical matches (85,042 seats), 99 exact/effective engine policy identities plus
the local human participant (100 total), 26,521 self-match, 1,664 diagnostic, 113
unmapped-participant matches (614 unmapped seats), 14,005 eligible matches, and 28,010 rating
events; SQLite integrity and foreign-key checks pass; the five-digest forward/reverse-root gate
proves that document set, policy attribution, derived ledger, Elo history, and leaderboard are
all independent of root traversal order. The leaderboard is a **deterministic historical
canonical-order Studio Elo** — historical entries are ordered by source-document SHA-256, so it
is not a chronology and not a strength-timeline verdict; it is not comparable to `official_elo`
pools and is not accepted as a strength baseline. The panic-hardening round that followed closure ran as a read-only static census and closed with
**no code change**: zero externally triggerable panic sites exist on the scoped historical
replay/import production path (strict parsing, `Result` propagation, and explicit guards already
fail closed); the few internally guarded `unwrap/expect` sites were deliberately left as-is.
Commit C Slice 2 (content-addressed replay archive) is `IMPLEMENTED` / `VERIFIED` locally and
awaits the owner's re-review of Repair 2, the bind-time revalidation close patch (`P1-1` opaque
handle, `P1-2` fixed protocol archive root, reader re-hash, and now `verify_present()` before the
ledger records `archive`). The concurrency `P2` from the earlier review remains open and must be
fixed before the central completion outlet is built. Commit C Slice 1 (runtime ingestion
of one fresh occurrence) is **CLOSED** @ `1011607`
(`ACCEPTED`, P0=0 / P1=0 / P2=0): fresh occurrence evidence -> durable occurrence identity/order ->
strict report/replay/config verification -> exact policy attribution -> existing eligibility/Elo ->
append -> delete the database and rebuild the same league from corpus + envelopes + manifest.

**Commit C Slice 2 — Content-Addressed Replay Archive is AUTHORIZED** (owner, 2026-09-13), with a
deliberately narrow first cut:

```text
verified runtime ReplayV1 -> immutable content-addressed archive -> ledger binding points to the
archived replay -> the archive survives deletion of the original run directory
```

Four contract points only: (1) archive key = verified replay document SHA-256; (2) same hash already
present with identical bytes -> idempotent no-op; (3) same target hash/path with different bytes ->
fail closed; (4) after the original runtime run directory is deleted, the league record's archived
replay is still readable and still passes `verify_replay`. The central arena/evaluation completion
outlet, the Studio Host APIs, and any UI remain **not authorized** for this slice.

### Commit C Slice 2 design (2026-09-13)

**Problem.** A verified runtime `ReplayV1` is currently bound with
`replay_storage = in_place_reference` and the record's `replay.path` is the original run
directory's file. Invariant 2 requires every eligible match to keep its ReplayV1; if that run
directory is moved, cleaned, or its file is overwritten, the league's replay-backed evidence
silently becomes unreachable even though the ledger still claims `verified`. This slice makes the
verified bytes immutable and self-contained.

**Design.**

1. **Archive layout.** The archive root is a directory (default
   `local-artifacts/studio-league/replays/`, ignored by Git with the rest of `local-artifacts/`).
   A replay is stored at `<root>/<sha256[0..2]>/<sha256>.json`, where `<sha256>` is the verified
   replay **document** hash — the same value already carried by
   `ReplayBindingV1.document_hash`. The two-character fan-out keeps one directory from holding
tens of thousands of entries; the object is identified by content alone, never by the original
   filename or run directory.
2. **Archive write is verify-then-copy, fail closed.** The bytes are written to a unique temporary
   file in the target directory, `fsync`ed, and only then atomically linked/renamed into place. A
   pre-existing object is never trusted on the strength of its name: on a hash-path collision the
   existing bytes are re-hashed, and (2) identical bytes → idempotent no-op, (3) different bytes →
   `Err` with zero mutation and no overwrite. The archive is append-only; nothing in this slice
   deletes or rewrites an object.
3. **The ledger binding points at the archive.** The ingested record carries
   `storage = Some(ReplayStorage::Archive)` and `path = Some(<root>/<sha[0..2]>/<sha>.json)` (a
   normalized, portable `/`-separated logical path). `document_hash`, `final_hash`, and
   `verification = verified` are unchanged, so the schema and the whole eligibility chain are
   untouched. The original run directory is **not** deleted by this slice — the archive is an
   additional durable copy, and removing the source is the operator's separate decision.
4. **Archiving never substitutes for verification.** The replay is verified exactly as it is today
   (strict parse + full `verify_replay` + report/replay fact agreement) **before** any archive
   write. A replay that does not verify is rejected and nothing is archived; the archive cannot
   launder an unverified document into a `verified` binding. The archive path is also never used
   as a content source: the bytes are always the ones just verified in memory.

**Scope.**

- In: a small archive module in `splendor-studio-league` (key derivation, idempotent/fail-closed
  object write, archive path formatting); the runtime record's binding switched to `Archive`; the
  `studio-league-ingest` CLI gaining an archive root option (defaulted) and archiving before
  ingest; targeted tests.
- Out: the central arena/evaluation completion outlet, Studio Host APIs, any UI, any change to
  historical-migration bindings (historical records keep `in_place_reference`), any delete/move of
  original run directories, any Garbage collection / pruning, and any change to `ledger.rs`
  write semantics, the migrate reconciliation, or the envelope format.

**Gates.**

1. Archiving a verified runtime replay twice is an idempotent no-op (one object, one match, no
   second copy) and the ledger binding reads `archive` with the content-addressed path.
2. A target hash path already holding **different** bytes fails closed, mutates nothing, and leaves
   the pre-existing object byte-identical.
3. After the original runtime run directory is deleted, the archived replay is still readable at
   the recorded path and still passes `verify_replay`.
4. A non-verifying replay is rejected before any archive write (no orphan object appears).
5. An archived runtime occurrence still rebuilds identically from corpus + envelopes + manifest
   (archive bindings are deterministic), and no historical binding changed storage.

### Commit C Slice 2 implementation (2026-09-13)

Landed in this slice:

- **`crates/splendor-studio-league/src/replay_archive.rs`** (new): `archive_replay(root, sha256,
  bytes) -> ArchivedReplayV1`, `read_archived_replay(root, sha256)`, and
  `replay_document_sha256(bytes)`. The object lives at `<root>/<sha[0..2]>/<sha>.json`. The
  writer validates the claimed address is 64 lowercase hex, re-hashes the bytes against it, then
  either returns `AlreadyPresent` (identical object) or fails closed (different bytes at the
  address). A new object is written to a unique `.tmp`, `sync_all`ed, and `rename`d into place,
  so a crash leaves at most an orphan temp file, never a half-written object under a content
  address. `ArchiveOutcome::{Stored, AlreadyPresent}` is reported.
- **`bind_archived_replay(record, archived)`** in `historical_import.rs`: after verification has
  already succeeded (`runtime_match_record`), rewrites the binding to `ReplayStorage::Archive`
  with the archive's portable logical path. It refuses unless the record's
  `replay.document_hash` equals the archive key and the binding is `Verified`, so an object can
  never be attached to a record it does not describe. The public `runtime_match_record` and its
  historical counterpart are unchanged.
- **`studio-league-ingest`** gained `--archive-root <path>` (default
  `local-artifacts/studio-league/replays`, the pre-existing `STUDIO_LEAGUE_REPLAY_DIR`). The flow
  is verify -> archive -> bind -> ingest, so the archive write only ever happens *after* the
  replay verified. The receipt JSON now carries a `replay` block (`storage`, `document_hash`,
  `path`, `archive_outcome`).

Validation (local evidence):

- Module unit tests (`replay_archive.rs`) **4**: idempotent double-archive leaves exactly one
  object; a corrupt occupant (bytes that do not hash to their name) fails closed and is left
  byte-identical; a mismatched claimed address is rejected before any write; an archived replay
  survives deletion of its source directory.
- Integration gates (`tests/replay_archive.rs`) **6**: a verified occurrence is archived and the
  ledger row reads `archive` with the content-addressed path (and the recorded path resolves under
  the archive root); re-archiving and re-offering is idempotent (one object, one match); after the
  run directory is deleted the archived bytes are re-read and **pass `verify_replay`**; a collision
  with different bytes fails closed and leaves no `.tmp`; a record cannot bind an archive object
  naming a different replay; a tampered (non-verifying) replay is rejected before any archive
  write and creates no object.
- Real CLI smoke over a corpus match directory (M39a `baseline-M07-5000000-r0`): a synthesized
  occurrence envelope drove `studio-league-ingest` to archive
  `f66a1685…b052` (`stored`), record `runtime:smoke-occ-slice2` with 2 Elo events, and write
  `replay_storage = archive`, `replay_path = f6/f66a1685…b052.json`, `replay_verification =
  verified`. Re-offering the same occurrence printed `already_present`, left one object and one
  match; a second occurrence with byte-identical replay content archived as `already_present` yet
  produced a **second** match (content equality is not occurrence equality) and one shared
  object; after deleting the run directory both matches' archived replays were still readable and
  hashed to their recorded `document_hash`.
- Baseline: `splendor-studio-league` **68/68** (14 lib + 3 + 29 + 5 + 6 + 4 + 7); `splendor-cli`
  bin **89/89**; `cargo fmt --check` clean; `git diff --check` clean. No real 42k migration was
  re-run; historical bindings keep `in_place_reference`.

### Commit C Slice 2 Repair 1 — the archive binding becomes real League authority (2026-09-13)

The owner's review of `806a989` confirmed the four normal-path archive contracts and the CLI
verify -> archive -> bind -> ingest ordering, and accepted the orphan-object trade-off, but
returned **`REPAIR_REQUIRED` (P0=0 / P1=2 / P2=1)** on two authority seams:

1. **P1-1 — an `archive` binding could be fabricated without a real object.** `ArchivedReplayV1`
   had four public fields, so any caller could construct one by hand (a real
   `document_sha256` plus a nonexistent path) and `bind_archived_replay` would accept it after
   checking only the hash and `Verified`. The ledger could then claim
   `archive` / `verified` / a path where nothing exists — exactly the product truth Slice 2 is
   supposed to guarantee.
2. **P1-2 — `--archive-root` made the recorded binding un-locatable.** The ledger stores only the
   content-relative `replay_path`, and the root is not recorded in `matches`, `league_meta`, or
   the occurrence envelope; letting the CLI choose an arbitrary root meant a later process
   holding only the database could not know where the object lives.
3. **P2 — the "unique" temp file was not unique and the publish step is not concurrency-safe.**
   `.{sha}.{pid}.tmp` collides for two threads of one process, and `check-absent -> write ->
   rename` is a TOCTOU: on Windows a second writer's `rename` can fail even when the first
   published a byte-identical object. Single-threaded CLI ingest is fine, but a concurrent
   central completion outlet must not inherit this.

Repair (narrow; envelope format, `ledger.rs` semantics, runtime occurrence identity/order, and
Elo are untouched):

- **P1-1:** `ArchivedReplayV1` is now an **opaque handle** — all four fields are private and the
  only constructor is `archive_replay`. Read-only getters (`document_sha256`, `logical_path`,
  `filesystem_path`, `outcome`) replace direct field access. Fabricating a handle is now a
  compile error, so holding one is evidence the object was published or confirmed present.
- **P1-2:** the production `studio-league-ingest` no longer accepts `--archive-root` (it is now an
  unexpected argument); it always archives under the protocol constant
  `STUDIO_LEAGUE_REPLAY_DIR` and records only the content-relative path. The library
  `archive_replay(root, ..)` stays parameterised so tests can use a temp directory. `storage =
  archive` + relative `replay_path` + `STUDIO_LEAGUE_REPLAY_DIR` is now a fixed protocol, so the
  recorded path is locatable from the database alone.
- **Reader hardening (folded into P1-1):** `read_archived_replay` now re-hashes the bytes it read
  and refuses an object that no longer matches its content address, so on-disk corruption fails
  closed instead of returning bytes that disagree with the record's `document_hash`.

Targeted gates:

- `reading_a_tampered_archive_object_fails_closed` (`tests/replay_archive.rs`): corrupting an
  archived object on disk makes `read_archived_replay` return `Err` naming the corruption.
  Verified to fail against the pre-patch reader (it returned `Ok`) and to pass after.
- `the_recorded_archive_path_resolves_under_the_protocol_root_alone`
  (`tests/archive_protocol_root.rs`, its own binary because it changes the process cwd): a
  record archived under `STUDIO_LEAGUE_REPLAY_DIR`, bound and ingested into a database, is
  located by that constant joined with the recorded `replay_path`, and the located bytes hash to
  the recorded `document_hash` — nothing else about the ingest invocation is needed.
- Real CLI smoke (M39a `baseline-M07-5000000-r0`): `--archive-root` is rejected with
  "unexpected argument" (exit 2); the default run archives `f66a1685...b052`, records
  `runtime:smoke-r1-occ` with 2 Elo events, and the row's `replay_path` resolves under
  `STUDIO_LEAGUE_REPLAY_DIR` with the bytes hashing to the recorded `document_hash`. Scratch
  artifacts were removed afterwards.

Baseline: `splendor-studio-league` **70/70**; `splendor-cli` bin **89/89**; `cargo fmt --check`
clean; `git diff --check` clean. No 42k migration was re-run.

### Commit C Slice 2 Repair 2 / close patch — bind-time revalidation (2026-09-13)

The owner's review of `f579b2a` closed the previous P1-2 (the CLI no longer accepts an archive
root; the reader re-hashes) and confirmed the opaque handle stops a caller fabricating a handle,
but returned **`REPAIR_REQUIRED` (P0=0 / P1=1 / P2=1)** on one remaining seam:

1. **P1 — an opaque handle only proves the object existed when it was created, not when it is
   bound.** `bind_archived_replay` checked the hash match and `Verified` and then wrote
   `storage = archive` / `path`, without re-reading the object. A caller that obtained a valid
   handle could delete or overwrite `archived.filesystem_path()` and then bind successfully, so
   the ledger could still record `archive` + `verified` + a path whose object no longer exists
   (or no longer hashes to the recorded `document_hash`). The earlier comment ("holding a handle
   is evidence that the object exists") was therefore too strong.

Close patch (historical builder + archive module only):

- `ArchivedReplayV1::verify_present()` re-reads the object at the handle's `filesystem_path` and
  requires it to exist **and** still hash to the handle's content address, naming either failure
  explicitly.
- `bind_archived_replay` now does: hash-identity check -> `Verified` check -> `verify_present()`
  -> set `Archive`/path. A ledger row can no longer claim an archive object that has since been
  deleted or overwritten.
- The doc comment on `ArchivedReplayV1` was corrected to say a handle proves the object existed
  at creation and that binding must call `verify_present` first.

Targeted gates (`tests/replay_archive.rs`):

- `binding_a_handle_whose_object_was_deleted_fails_closed`: archive -> delete the object ->
  `bind_archived_replay` must `Err` ("no longer readable").
- `binding_a_handle_whose_object_was_overwritten_fails_closed`: archive -> overwrite the object
  with corrupt bytes -> `bind_archived_replay` must `Err` ("changed after it was written").
- Both verified to fail against the pre-patch bind (which returned `Ok`) and to pass after.
- Real CLI smoke (M39a `baseline-M07-5000000-r0`): the happy path still archives
  `f66a1685...b052`, records `runtime:smoke-r2-occ` with 2 Elo events, and exits 0; scratch
  artifacts were removed afterwards.

Baseline: `splendor-studio-league` **72/72**; `splendor-cli` bin **89/89**; `cargo fmt --check`
clean; `git diff --check` clean. No 42k migration was re-run.

**P2 follow-up (open, not fixed this round):** the archive temp-file name and the
`check-absent -> write -> rename` publish step are not concurrency-safe. This must be fixed
**before** the central arena/evaluation completion outlet is built, because that outlet is the
first concurrent producer. The intended fix is a unique nonce/counter temp name plus a
`rename`-failure path that re-reads the target and reports `AlreadyPresent` when its bytes
already hash to the expected address (only a genuine byte mismatch stays an error).

**Superseded next-step text** (kept for the record): the earlier version of this section said
Slice 1 awaited owner review and that the content-addressed replay archive, the central
completion outlet, and the Studio Host APIs were **not authorized** yet and needed the owner's
review of this slice first.
