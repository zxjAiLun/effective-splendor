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
  **Commit C Next Slice — Completion Producer Wiring: ACCEPTED / CLOSED @ `6170c7c`**
  (P0=0/P1=0/P2=0). **Commit C Next Slice — Project-Root / Launcher Resolution (2026-09-14)**:
  `IMPLEMENTED` / `VERIFIED` locally, pending owner review. One `StudioLeaguePathsV1` resolves
  `db` / `identity` / `replay_root` from a single project root, so the database, the identity manifest
  and the replay archive can no longer be chosen apart; `--project-root` replaces `--db`/`--identity`
  on the four league-path commands; the completion session captures the root at open, and
  `complete_runtime_occurrence` still takes no path. Authority (ledger / Elo / eligibility / archive)
  unchanged; Host API and UI still **not authorized**.
  **Repair 1 (2026-09-14)** — owner review of the above = `REPAIR_REQUIRED` (P0=0/P1=1/P2=1): the
  crate root still published a second path authority (`DEFAULT_IDENTITY_MANIFEST_PATH`, now deleted,
  plus the four layout names). All five removed from the public surface; the layout is now defined
  once, privately, in `paths.rs`, and the three full location literals appear nowhere else in the
  workspace. Locating a league is exactly `StudioLeaguePathsV1::resolve(..)` plus `db()` /
  `identity()` / `replay_root()`. `83/83` and CLI `273/273` unchanged.
  **Project-Root / Launcher Resolution: ACCEPTED / CLOSED @ `1ecb343` (P0=0/P1=0/P2=0).**
  **Commit D — Host API Slice 1 (read-only) (2026-09-14)**: `IMPLEMENTED` / `VERIFIED` locally,
  pending owner review. Three read-only routes on the existing `studio-host`
  (`GET /league/leaderboard`, `/league/matches/{match_id}`, `/league/replays/{document_sha256}`),
  served from a new opaque **read-only** `StudioLeagueReaderV1` (opened `SQLITE_OPEN_READ_ONLY`,
  schema-checked, fails closed) that keeps the ledger the sole owner of its queries. Project root
  resolved once at startup from `--project-root`. No write authority, no new table, no Elo
  recomputation. Gate baselines: `83/83` and CLI **277/277** (44 → 45 binaries). **UI still not
  authorized.**
  **League Play v1**: design `ea98798` → `b7a29d7` → Repair 1 `50a4f3b`（锚点 `0a1f7b9`）→
  close patch `cf587d2`（锚点 `b569fa2`）→ 中文改写 `c41143c`。首个面向玩家的完整往返页面。
  **Real-Scale Walkthrough Blocker Repair (2026-09-15)**: `IMPLEMENTED` / `VERIFIED`（本地），
  **尚未 `ACCEPTED`**。第一次真实手工走查在第 2 步被两个独立缺陷卡死：真实 42k 库上
  leaderboard 查询是 O(参与者 × 座位全表扫描 × 5)（约 4,200 万次行访问，实测 19.7 s，
  且因 accept 串行而让*所有*路由包括 `/health` 一起不可用），以及公共 HTTP 边界没有任何
  socket 超时（一条空闲连接即可永久卡死 Host）。同时页面在未确认 Host 可用时就写了
  `ready`。本轮修三处（集合式聚合 19.7 s → 1.1 s 且逐字段一致；
  `set_read_timeout(2s)`/`set_write_timeout(5s)` 于两个 accept 循环共用的边界；
  `/league` 三态就绪 + 首屏读 5 s `AbortController`），加一条中型 fixture 回归门，
  并把启动器降级回普通双击脚本。
  **`06f949b` 的终审 = `REPAIR_REQUIRED`**（P0=0 / P1=1 / P2=1）：主体 PASS，
  但首屏在 `checking` 时还渲染了一个「The request was refused」横幅
  —— 未获得事实前就宣布失败，与之前的 premature `ready` 是同一个错误的两个方向。
  已修为「只在 settled failure 时创建 banner」，并补 SSR 首屏真相 gate。
  `LEADERBOARD_SQL` 的公共面登记为 **P2 deferred — test-driven public surface**
  （以后收回 `pub(crate)`，本轮不为它搬测试）。
  详见 `docs/studio-league-real-scale-repair.md`。
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
Commit C Slice 2 (content-addressed replay archive) is **CLOSED** @ `85c15ed`
(`ACCEPTED`, P0=0 / P1=0 / P2=1 deferred): the archive writes an immutable content-addressed
object, binds it through an opaque handle revalidated at bind time, records
`ReplayStorage::Archive` plus a content-relative path under the protocol root, and re-hashes on
read. The deferred concurrency `P2` was then closed, so the archive now publishes safely from
concurrent producers. Commit C Slice 1 (runtime ingestion
of one fresh occurrence) is **CLOSED** @ `1011607`
(`ACCEPTED`, P0=0 / P1=0 / P2=0): fresh occurrence evidence -> durable occurrence identity/order ->
strict report/replay/config verification -> exact policy attribution -> existing eligibility/Elo ->
append -> delete the database and rebuild the same league from corpus + envelopes + manifest.

**Commit C Slice 3 — Central Completion Outlet is AUTHORIZED** (owner, 2026-09-13), with the
explicit constraint that its first cut must **not** connect to the Arena yet. The prerequisite was
the archive concurrency repair (above), which is now done; the corrected publish path is the one
the concurrent outlet will use. The Arena connection, the Studio Host APIs, and any UI remain
**not authorized** until the owner reviews that first cut.

> **Update (2026-09-13).** The first cut is now implemented on top of `5ca0c3a`: the chain lives in
> `crates/splendor-studio-league/src/completion.rs` and `studio-league-ingest` is a thin adapter.
> It is locally `VERIFIED` and awaiting owner review — see *Commit C Slice 3 — Central Completion
> Outlet* at the end of this document. The Arena is still not connected.

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

**P2 at the time of this repair (since fixed):** the archive temp-file name and the
`check-absent -> write -> rename` publish step were not concurrency-safe. It was fixed as the
prerequisite for Commit C Slice 3, below.

**Owner re-review of `85c15ed` (2026-09-13): `ACCEPTED / CLOSED` — P0=0 / P1=0 / P2=1 (deferred).**
The remaining P1 is closed: `bind_archived_replay` calls `archived.verify_present()?` before it
records `ReplayStorage::Archive`, and that method re-reads the handle's filesystem object and
requires its bytes to still hash to the handle's content address (both the deleted and the
overwritten states have regressions). The owner accepted the residual window between
`verify_present()` and the SQLite commit as out of scope (closing it would need cross
filesystem + SQLite transaction semantics) and accepted the scope as a lean iteration
(`f579b2a -> 85c15ed`, one commit, archive bind/revalidation + two targeted tests + docs, with
occurrence, ledger Elo, and historical migration untouched). **Commit C Slice 2 is CLOSED.** The
archive concurrency P2 stayed open and was fixed as the prerequisite in the next section.

### Archive concurrency prerequisite (2026-09-13)

The owner authorized **Commit C Slice 3 / Central Completion Outlet** but ruled that its first
cut must not connect to the Arena yet: the archive concurrency P2 had to be closed first, because
the completion outlet is the first **concurrent** producer. The P2 was:

1. **Not thread-unique temp name.** `.{sha}.{pid}.tmp` is identical for two threads of one
   process, so they share (and `File::create`-truncate) the same temporary file.
2. **TOCTOU between `target absent` and `rename`.** With multiple producers, the loser's
   `rename` fails on Windows even when the winner already published a byte-identical object, so
a legitimate concurrent producer was reported as a failure.

Fix (archive module only):

- `create_unique_temp` builds the temp name from the process id **and a per-process atomic
  counter**, and opens it with `create_new(true)` so an existing path is never reused (retrying
  on the rare `AlreadyExists`). Two threads can no longer share a temp file.
- On a `rename` failure the writer **re-reads the target** and accepts it only when its bytes
  still hash to the expected address (`AlreadyPresent`); a genuine byte mismatch, or a target
  that cannot be read, still fails closed. `object_present` centralises this check so the
  idempotent path, the publish-race path, and the corruption path share one rule.

Gate (`tests/replay_archive.rs`): `concurrent_producers_of_one_sha_publish_exactly_one_correct_object`
lines up 16 producers on a barrier across 25 rounds, each racing to archive the same content
address. Every producer must return `Stored` or `AlreadyPresent`, at least one must be `Stored`,
and exactly one byte-correct object must exist with no `.tmp` residue. The repeated rounds make
the race reliable rather than schedule-dependent: against the pre-P2 code the gate failed
**5/5** runs, and against the fix it passed 5/5 runs.

Baseline: `splendor-studio-league` **73/73**; `splendor-cli` bin **89/89**; `cargo fmt --check`
clean; `git diff --check` clean. No 42k migration was re-run.

**Superseded next-step text** (kept for the record): the earlier version of this section said
Slice 1 awaited owner review and that the content-addressed replay archive, the central
completion outlet, and the Studio Host APIs were **not authorized** yet and needed the owner's
review of this slice first.

---

## Commit C Slice 3 — Central Completion Outlet (2026-09-13)

Status: **IMPLEMENTED + locally VERIFIED**, awaiting owner review. Baseline
`5ca0c3a` (archive concurrency prerequisite, already accepted as the prerequisite for this
slice). Scope was authorized by the owner on 2026-09-13 with an explicit prohibition: this first
cut must **not** connect to the Arena.

### Problem and evidence

Until this slice, the only way a finished occurrence became ledger state was the
`studio-league-ingest` command, and the authority chain lived inline inside that command:

```text
runtime_match_record -> archive_replay -> bind_archived_replay -> ingest_match -> match_receipt
```

Two consequences followed. First, "how an occurrence enters the League" was a CLI implementation
detail, so the next producer (Arena completion, a worker, a host API) would have had to re-derive
the chain and could silently skip a gate. Second, the CLI already carried the *session* authority
too — open database, enforce schema version, enforce the protocol rating config, load and validate
the durable identity manifest, sync it — so those gates were also duplicated per caller.

### Design

One new module, `crates/splendor-studio-league/src/completion.rs`, owns the chain:

```rust
pub fn open_completion_league(db_path, identity_manifest_path, now) -> Result<Connection>
pub fn complete_runtime_occurrence(conn, archive_root, request) -> Result<CompletionOutcomeV1>
```

`open_completion_league` is the session authority: it opens/creates the database, initialises the
schema, enforces the protocol rating config, and loads → validates → syncs the durable identity
manifest. A missing manifest is still an error, never a fresh identity, so a caller cannot
complete an occurrence into a database that skipped one of those gates.

`complete_runtime_occurrence` performs, in this order:

1. `runtime_match_record` — strict envelope parse, full replay verification, report/replay fact
   agreement, exact configuration evidence;
2. the archive key, taken from the *verified* record's replay document hash;
3. `archive_replay` then `bind_archived_replay` — object before ledger row;
4. `ingest_match` — the single ledger entry point;
5. `match_receipt` — read back what the ledger actually recorded.

`CompletionOutcomeV1` returns the ingest outcome, the canonical record that was ingested, the
opaque archive handle, and the receipt, so a caller never needs to re-derive provenance.

`run_studio_league_ingest` is reduced to an adapter: parse the flags, read the envelope and the
three documents, parse the envelope, call the outlet, print the receipt and the optional JSON
receipt. `--archive-root` remains absent (a protocol constant, per Commit C Slice 2 Repair 1).

### Contracts and invariants preserved

- **Occurrence authority is unchanged.** Identity is still `runtime:<occurrence_id>` and
  `played_at` is still the envelope's `completed_at`.
- **The canonical-tail guard is untouched.** The outlet never reorders, never retries with a
  different position, and never chooses a position itself; ordering is decided entirely inside
  `ingest_match`. A non-canonical arrival still fails closed and still requires canonical-order
  retry or a rebuild.
- **Object before row.** A failure after the object is published leaves at most an unreferenced
  immutable object; a match row can never claim a replay that was not written.
- **The arena is not connected.** No Arena code path calls the outlet in this cut. No worker
  queue, no Host API, no UI.

### The one behavioural change: write transactions are `IMMEDIATE`

Gate 2 (concurrent idempotency) exposed a real defect, not just a test artefact. The naive
configuration — `busy_timeout` plus SQLite's default `DEFERRED` transactions — fails a legitimate
concurrent producer with `SQLITE_BUSY`. A deferred transaction that *reads* before it *writes*
holds a shared lock, and when another connection commits in between, the lock *upgrade* returns
`SQLITE_BUSY` immediately without ever consulting the busy handler. Both the manifest sync
(read then write) and incremental ingest (identity resolution and tail check, then insert) have
exactly that shape, so concurrent producers of the same occurrence failed instead of serializing.

Fix, and nothing else:

- `ingest_match_ordered` opens its transaction with
  `TransactionBehavior::Immediate`, so it takes the write lock up front and `busy_timeout`
  actually serializes writers. Ordering semantics are unchanged — only lock-acquisition timing.
- `open_completion_league` sets a 30-second `busy_timeout`, and runs the manifest sync inside an
  `IMMEDIATE` transaction for the same reason.

`ingest_match` is production-reachable only from the outlet; the historical batch path
(`ingest_batch_canonical`) keeps its own single-writer transaction and is unchanged.

### Validation and evidence

New gates:

- `crates/splendor-studio-league/tests/completion_outlet.rs` — 5 tests.
  - gate 2a `completing_one_occurrence_twice_records_exactly_one_match`: second completion is
    `AlreadyPresent` with 0 rating events, one match row, two rating events, one archive object.
  - gate 2b `concurrent_producers_of_one_occurrence_record_exactly_one_match`: 8 independent
    connections on one database, all completing the same occurrence. Exactly one reports
    `Inserted` with 2 rating events; every producer resolves the same match id; exactly one match
    row, exactly one rating-event pair, and exactly one archive object named `<sha>.json`.
  - gate 3a `a_replay_that_fails_verification_leaves_no_ledger_row_and_no_object`: the step list
    is emptied and the envelope is *recomputed over the tampered bytes*, so the only thing that can
    reject it is strict replay verification; no match row, no rating event, no archive object.
  - gate 3b `an_unusable_archive_root_leaves_no_ledger_row`: archive failure leaves no match row.
  - gate 3c `a_non_canonical_arrival_fails_closed_and_leaves_only_an_orphan_object`: after a later
    occurrence is recorded, an earlier one is rejected by the tail guard; the match row is absent,
    the previously recorded match still claims its object, and the only residue is one additional
    unreferenced object.
- `crates/splendor-cli/tests/completion_equivalence.rs` — 1 test, gate 1
  `the_cli_adapter_and_a_direct_outlet_call_agree`: the same fixture is completed once through the
  process boundary (with the CLI's own protocol archive root, resolved from its working directory)
  and once through a direct library call, into two databases, and the full ledger snapshots are
  compared — match rows (identity, source hash, `league_seq`, `played_at`, replay storage, path,
  document hash, final hash, verification, eligibility, reason), seat rows, rating events, and the
  leaderboard. The test also asserts the comparison is non-vacuous (non-empty matches, seats,
  exactly two Elo events, non-empty leaderboard) and that the exported receipt matches the ledger.
  This gate needs `rusqlite` in `splendor-cli`'s **dev-dependencies** only; no CLI code path opens
  a database.

Results (local evidence): `splendor-studio-league` **78/78** (lib 14 + `archive_protocol_root` 1 +
`completion_outlet` 5 + `historical_resolver` 3 + `league_core` 29 + `policy_identity` 5 +
`replay_archive` 10 + `replay_index` 4 + `runtime_ingest` 7); the whole `splendor-cli` suite
passes, including `--bin splendor` **89/89** and the new `completion_equivalence` 1/1. The
concurrency gate was run 8 consecutive times with no flake. `git diff --check` clean. No 42k
migration was re-run. There are no cloud status checks for this commit and no CI is claimed.

### Result and decision

`IMPLEMENTED` / locally `VERIFIED`. Not `ACCEPTED`: the owner's review of this cut is the gate.

### Known limitations

- **`IMMEDIATE` serializes writers; it does not make the league lock-free.** With SQLite's default
  rollback journal, a long-running reader still blocks a writer, and beyond the 30-second busy
  timeout a producer fails rather than waiting forever. WAL was deliberately not enabled: it would
  change the on-disk shape of the official derived artifact.
- **`archive_root` is still a parameter of the outlet.** Production passes the protocol constant
  `STUDIO_LEAGUE_REPLAY_DIR` and the CLI exposes no flag for it, but a library caller could pass a
  different root. The same residual was accepted for `archive_replay` in Commit C Slice 2.
  **Superseded by Commit C Slice 3 Repair 1 (below):** the outlet no longer accepts an
  `archive_root` at all, and `complete_runtime_occurrence` no longer accepts a raw
  `rusqlite::Connection`; the session type is the authority. See that section.
- **An ingest failure can leave an orphan archive object.** This is the deliberate
  object-before-row trade-off, now visible as a test assertion rather than a comment.
- The equivalence gate compares *this* fixture end to end. It is a strong adapter gate, not a
  proof that every future CLI flag combination routes through the outlet.

### Next authorized gate

Owner review of Commit C Slice 3. Wiring Arena completion into the outlet, the Studio Host APIs,
and any UI remain **not authorized** until that review. The open question for the next slice is
whether the Arena should call the outlet in-process or hand the occurrence documents to a
separate completion step; that decision is deliberately deferred.

**Superseded next-step text** (kept for the record): the earlier version of this section said
Slice 3 was authorized but not started, and that the archive concurrency prerequisite had to be
closed first.

---

## Commit C Slice 3 Repair 1 — the outlet owns its authority (2026-09-13)

Status: **IMPLEMENTED + locally VERIFIED**, awaiting owner review. Baseline `ff9ad91`.
Owner review of `ff9ad91` = **REPAIR_REQUIRED (P0=0 / P1=2 / P2=0)**. Both findings are authority
seams that a previous round had already closed once, and that this slice reopened by moving the
chain into public API.

### P1-1: the central outlet did not own its authority

`open_completion_league` returned a bare `rusqlite::Connection`, and
`complete_runtime_occurrence` accepted a `&mut Connection` **plus** an `archive_root: &Path`. A
future producer could therefore (a) pass an arbitrary archive root — reintroducing exactly the
un-locatable binding Commit C Slice 2 Repair 1 closed, since the ledger stores only a
content-relative `replay_path` — or (b) call `open_league` itself and hand the raw connection to
the outlet, skipping the manifest, rating-config, and schema session gates this slice had just
extracted. The module comment claimed a second producer could not take a shortcut; the signatures
allowed two.

Fix — the authority is now the type, not a convention:

```rust
pub struct CompletionLeagueV1 { conn: Connection }   // private field, one constructor, no accessor
pub fn open_completion_league(db_path, identity_manifest_path, now) -> Result<CompletionLeagueV1>
pub fn complete_runtime_occurrence(
    league: &mut CompletionLeagueV1,
    request: &CompletionRequestV1<'_>,
) -> Result<CompletionOutcomeV1>
```

`CompletionLeagueV1` has no method that yields its connection, so a caller cannot obtain one and
hand it to the outlet; the archive root is the protocol constant `STUDIO_LEAGUE_REPLAY_DIR` bound
inside the outlet, and no public function accepts a root at all. The CLI still rejects
`--archive-root` (`unexpected argument`, exit 2).

Honest scoping of gate A: the "the session cannot be constructed any other way" half is a
**compile-time** property and cannot be asserted at runtime. What the gate asserts is the two
consequences an integrator would actually hit: an occurrence completed through the outlet lands
under the protocol root with a content-relative ledger path that resolves there
(`the_completion_authority_cannot_be_bypassed`), and a league with no identity evidence refuses to
open a session. The negative control for the API half is a compile error, not a failing assertion.

Tests keep temporary archive roots without reopening the production seam:
`tests/completion_outlet.rs` now sandboxes the **process working directory** once — it is its own
test binary, so the process-wide cwd change cannot race another binary — and addresses objects by
content address instead of counting files, since all of its tests now share one protocol root.

### P1-2: idempotency evidence did not cover the occurrence

`runtime_match_record` set `source_document_hash` to `SHA256(arena-report bytes)`, while the ledger
decides idempotency on `(source_kind, source_identity, source_document_hash)`. A runtime
occurrence's durable authority is the whole envelope — `occurrence_id`, `completed_at`,
`report_sha256`, `replay_sha256`, `config_sha256`. So the same `occurrence_id` with a changed
replay, configuration, or `completed_at`, where the new triple still verified on its own, produced:

```text
build a new candidate record -> (maybe) archive a new object -> ingest_match returns AlreadyPresent
-> CompletionOutcomeV1 { record: <the candidate>, archived: <this object>, receipt: <the old row's> }
```

The outcome then described a replay binding that was never written into the ledger, and the CLI
printed it. Worse, the rebuild path treats two envelopes sharing one `occurrence_id` as two
distinct pieces of evidence, so live ingest could disagree with a rebuild of the same corpus — a
live/rebuild inconsistency of exactly the kind Slice 1 Repair 2/3 closed.

Fix — the idempotency evidence, not the return value.
`runtime_occurrence_evidence_hash()` covers `format`, `version`, `occurrence_id`, `completed_at`,
`report_sha256`, `replay_sha256`, `config_sha256`, under a domain separator and with every field
length-prefixed in a fixed order, so shifting bytes between fields cannot collide and a future
envelope format cannot reproduce an earlier format's hash. `OccurrenceIdentityV1::Runtime` now
carries it, and `build_match_record_with_configuration` keys `source_document_hash` on it for
runtime sources while historical sources keep the arena-report SHA-256 — the Distinct-Document
policy and the historical digests are untouched. Live ingest and the corpus rebuild both build
runtime records through `runtime_match_record`, so both use the one computation by construction.

The consequence:

```text
same occurrence + same complete evidence      -> AlreadyPresent
same occurrence + changed replay/config/time  -> SourceConflict, no new match, no new rating event
```

### Validation and evidence

| Gate | Where | What it proves |
|---|---|---|
| A | `completion_outlet::the_completion_authority_cannot_be_bypassed` | the protocol root is fixed and actually used; a league with no identity evidence cannot open a session |
| B | `completion_outlet::the_same_occurrence_with_the_same_evidence_is_idempotent` | identical evidence is a no-op; the record's evidence hash equals `runtime_occurrence_evidence_hash` and differs from both the report SHA and the replay SHA |
| C | `completion_outlet::the_same_occurrence_with_changed_evidence_is_a_conflict` | changed configuration evidence, and changed documents, both give `SourceConflict` with no new match row and no new rating event |
| 2b | `completion_outlet::concurrent_producers_of_one_occurrence_record_exactly_one_match` | 8 concurrent sessions on one database → one match, one object, one rating-event pair |
| 3a/3b/3c | `completion_outlet::{a_replay_that_fails_verification…, an_unpublishable_archive…, a_non_canonical_arrival…}` | no ledger row; a colliding object is never overwritten; ordering still fails closed with only an orphan object |
| builder agreement | `runtime_ingest::rebuild_from_occurrence_evidence_reproduces_the_live_ingest` | the corpus-built and live-built records for one envelope carry the same evidence hash |
| CLI equivalence | `splendor-cli/tests/completion_equivalence.rs` | the thin adapter and a direct outlet call still produce identical ledger snapshots, both archiving under the protocol root |

**Negative control.** Reverting only the line that keys the hash — making
`OccurrenceIdentityV1::source_document_hash` return the report document hash again — fails
**three** gates: B (the `assert_ne!(evidence, report sha)` assertion), C (variant (i) returns
`AlreadyPresent` instead of `SourceConflict`), and the `runtime_ingest` builder-agreement assertion.
The gates are not vacuous.

Results (local evidence): `splendor-studio-league` **80/80** (lib 14 + `archive_protocol_root` 1 +
`completion_outlet` 7 + `historical_resolver` 3 + `league_core` 29 + `policy_identity` 5 +
`replay_archive` 10 + `replay_index` 4 + `runtime_ingest` 7); the whole `splendor-cli` suite passes
(43 test binaries, `--bin splendor` 89/89, `completion_equivalence` 1/1); the completion outlet
binary ran 6 consecutive times with no flake. `git diff --check` clean; `rustfmt` was applied to the
touched files only, and it reported no diff in the large untouched files
(`historical_import.rs`, `match_record.rs`, `runtime_ingest.rs`, `studio_league_command.rs`). No 42k
migration was re-run. There are no cloud status checks for this commit and no CI is claimed.

### Result and decision

`IMPLEMENTED` / locally `VERIFIED`. Not `ACCEPTED`: the owner's review of this repair is the gate.

### Known limitations

- Gate A's "the session cannot be constructed another way" half is a compile-time property; only its
  runtime consequences are asserted.
- `CompletionLeagueV1` derives `Debug` (so `Result::unwrap_err` and error contexts work for
  callers). It reveals the database path, which the caller supplied anyway.
- The object-before-row trade-off is unchanged: a rejected occurrence can still leave an
  unreferenced immutable archive object (asserted in gate C and gate 3c).
- The runtime evidence hash is a *new* value in `source_document_hash` for runtime records. No
  accepted artifact contains runtime records (the official `league.sqlite3` holds 42,521 historical
  matches and no runtime matches), so no locked digest changes; a future corpus with runtime
  occurrences will produce a different canonical-set digest, as it must, because the record set
  differs.

### Next authorized gate

Owner review of this repair. Arena wiring, the Studio Host APIs, and any UI remain **not
authorized**.

> **Update (2026-09-13).** The owner's review confirmed both repairs here (evidence hash:
> CLOSED; opaque session and fixed protocol root: PASS) and raised one further finding: the crate's
> public surface still re-exported `runtime_match_record` and `bind_archived_replay`, so the outlet
> was the official path only by convention. See *Commit C Slice 3 Repair 2* below.

---

## Commit C Slice 3 Repair 2 — the public surface stops offering the shortcut (2026-09-13)

Status: **IMPLEMENTED + locally VERIFIED**, awaiting owner review. Baseline `257ccb6`.
Owner review of `257ccb6` = **REPAIR_REQUIRED (P0=0 / P1=1 / P2=0)**. Both repairs from the
previous round were confirmed: the occurrence evidence hash is **CLOSED**, and the opaque session
plus fixed protocol root **PASS**. The remaining finding is that the *crate's public surface* still
re-exported the whole old chain, so the completion outlet was only the official path by convention.

### P1: the old chain was still publicly re-exported

`lib.rs` still exported `open_league`, `ingest_match`, `archive_replay`, **`runtime_match_record`**
and **`bind_archived_replay`**, and `historical_import` is a `pub mod`. An external crate — the
future Arena crate among them — could therefore still write:

```rust
let mut conn = open_league(db)?;
let record = runtime_match_record(&occurrence, report, replay, config, source_path)?;
let archived = archive_replay(Path::new("some-other-root"), replay_sha, replay)?;
let record = bind_archived_replay(record, &archived)?;
ingest_match(&mut conn, &record)?;
```

which re-acquires everything the outlet exists to remove: no `CompletionLeagueV1`, no manifest
session gate, an arbitrary archive root, and a direct ledger ingest. The claim in the module docs
and in the Repair 1 section — "a second producer cannot complete an occurrence through a
shortcut" — was true of the *type* and false of the *crate*.

### Fix

Only the two runtime-specific completion primitives are narrowed:

```rust
pub(crate) fn runtime_match_record(...)   // was pub, re-exported
pub(crate) fn bind_archived_replay(...)   // was pub, re-exported
```

and both are removed from `lib.rs`'s `pub use historical_import::{...}`. `completion.rs` and
`historical_import.rs` keep calling them internally. `archive_replay`, `read_archived_replay`,
`open_league`, `ingest_match`, `ingest_batch_canonical` and `runtime_occurrence_evidence_hash`
stay public: they are generic ledger/archive tools, and the goal is to close the *official runtime
completion shortcut*, not to turn the crate into a sandbox. `StudioMatchRecordV1` keeps its public
fields. No `*_for_test` public escape hatch was added.

**Negative control (compile-time, as this class of gate must be).** From an external crate:

```text
error[E0432]: unresolved imports `splendor_studio_league::bind_archived_replay`,
              `splendor_studio_league::runtime_match_record`
error[E0603]: function `runtime_match_record` is private
error[E0603]: function `bind_archived_replay` is private
```

The first is the direct re-export path, the second the module path
(`splendor_studio_league::historical_import::…`), so both routes are closed.

### Where the primitive tests went

`tests/replay_archive.rs` and `tests/runtime_ingest.rs` exercise exactly these primitives, so they
can no longer be integration tests. They moved, unchanged in substance, into a crate-internal test
module:

```text
src/chain_tests.rs
src/chain_tests/replay_archive.rs     (was tests/replay_archive.rs, 10 tests)
src/chain_tests/runtime_ingest.rs     (was tests/runtime_ingest.rs, 7 tests)
```

declared as `#[cfg(test)] mod chain_tests;`. They keep their original temp-directory label prefixes
(`splendor-replay-archive-*`, `splendor-runtime-ingest-*`), so they cannot collide with each other
or with the unit tests in `src/replay_archive.rs` inside the one lib test process. The alternative —
rewriting every assertion to go through the outlet — was rejected because it would have quietly
deleted the primitive-level gates (bind-mismatch, deleted object, overwritten object) that the
outlet's single call cannot express, and because the public surface keeps its own integration
coverage regardless.

`tests/archive_protocol_root.rs` used the primitives too, but its subject is public behaviour, so it
was **rewritten through the completion outlet** instead of moved: it now completes an occurrence
with the process working directory inside a temp sandbox, reads the row back, and asserts that
`STUDIO_LEAGUE_REPLAY_DIR + replay_path` resolves to an object whose bytes hash to the recorded
`document_hash`, and that the recorded path is not absolute. That is a strictly stronger version of
the same gate, because the caller no longer supplies a root anywhere.

### Validation and evidence

| Gate | Where | What it proves |
|---|---|---|
| surface closed (compile) | external-crate probe | neither the re-export nor the module path resolves to the two primitives |
| protocol root, public path | `tests/archive_protocol_root.rs` | the recorded relative path resolves under the protocol root alone, driven through the outlet |
| outlet gates A/B/C, 2b, 3a/3b/3c | `tests/completion_outlet.rs` | unchanged |
| CLI equivalence | `splendor-cli/tests/completion_equivalence.rs` | unchanged |
| primitive archive/chain gates | `src/chain_tests/*` (17 tests) | relocated verbatim, still passing |

Results (local evidence): `splendor-studio-league` **80/80** — 31 in the lib binary (14 unit + 17
relocated chain tests) + `archive_protocol_root` 1 + `completion_outlet` 7 + `historical_resolver` 3
+ `league_core` 29 + `policy_identity` 5 + `replay_index` 4. The whole `splendor-cli` suite passes
(43 test binaries, 268 tests, `--bin splendor` 89/89, `completion_equivalence` 1/1). `git diff
--check` clean; `rustfmt` run on the touched files only. No 42k migration was re-run. There are no
cloud status checks for this commit and no CI is claimed.

### Upgrade note — earlier runtime rows carry a different `source_document_hash`

Repair 1 changed what the ledger compares under `(source_kind, source_identity)` for a runtime
source: previously the arena-report SHA-256, now the whole-occurrence evidence hash. A derived
database written by a build *before* Repair 1 may therefore hold a runtime row whose
`source_document_hash` is the report SHA. If the same occurrence is offered again, the ledger
reports `SourceConflict` rather than `AlreadyPresent`.

That is correct and intended, not corruption: the two hashes are genuinely different evidence
records for the same key, and `SourceConflict` is the fail-closed answer. The SQLite index is
derived state, so the remedy is to **rebuild** it (`studio-league-migrate` plus the occurrence
envelopes), not to add a compatibility fallback that would let a changed occurrence be swallowed as
a no-op. No accepted artifact is affected: the official `league.sqlite3` holds 42,521 historical
matches and no runtime matches.

### Result and decision

`IMPLEMENTED` / locally `VERIFIED`. Not `ACCEPTED`: the owner's review of this repair is the gate.

### Known limitations

- The narrowing is scoped to the two runtime-specific primitives; `archive_replay`,
  `open_league`, `ingest_match` and friends stay public by design, so a determined external caller
  can still assemble a chain by hand from generic tools. What is closed is the *official* runtime
  completion path, which is the owner's stated contract — a Rust crate is not a security boundary.
- The relocated suites no longer exercise the public surface directly. Their replacements on the
  public surface are the outlet, protocol-root, and CLI-equivalence suites listed above.
- `src/chain_tests/runtime_ingest.rs` keeps its Slice 1 framing (it drives `ingest_match` directly to
  isolate the ledger from the archive); that isolation is deliberate and is why it moved rather than
  being rewritten onto the outlet.

### Next authorized gate

Owner review of this repair. Arena wiring, the Studio Host APIs, and any UI remain **not
authorized**.

---

## Commit C Next Slice — Completion Producer Wiring (design frozen before implementation)

Status: **AUTHORIZED** by the owner, 2026-09-13, together with the closure of Commit C Slice 3.
Baseline: `0c37335` (Commit C Slice 3 **ACCEPTED / CLOSED**, P0=0 / P1=0 / P2=0).

### Problem and evidence

Commit C Slice 3 ended with a working, gated completion authority:

```text
verify -> archive (object before row) -> bind -> ingest_match -> match_receipt
```

reachable through exactly one supported entry point (`open_completion_league` +
`complete_runtime_occurrence`), with the archive root pinned to
`STUDIO_LEAGUE_REPLAY_DIR`. But nothing in production ever calls it. The
reconnaissance for this slice established three facts:

1. **The occurrence producer does not exist.** Every `RuntimeOccurrenceV1`
   envelope in the repository is hand-written inside a test
   (`tests/completion_outlet.rs`, `tests/archive_protocol_root.rs`,
   `crates/splendor-cli/tests/completion_equivalence.rs`). No command or runner
   mints an `occurrence_id` or a `completed_at` and persists an envelope. The
   durable evidence half of the contract is unimplemented.
2. **The real match producer is `splendor run-match`.** `arena_command::run_match`
   → `run_match_inner` → `commit_completed` → `publish_completed` is the only
   command that runs one real arena match and publishes a report plus a replay.
   The configuration is that run's own input file (`--config`).
3. **The consumer already exists.** `splendor studio-league-ingest` reads the four
   documents (envelope, report, replay, config) and drives the outlet, but it is
   invoked by hand. Nothing connects production to it.

So the missing work is a *producer* and an *orchestration edge*, not more
authority.

### Layering ruling (owner-frozen): no `splendor-arena` → `splendor-studio-league` edge

Studio League already consumes `splendor-arena`'s report and config types. Adding
the reverse dependency would create a cycle in spirit even where Cargo permits it.
The frozen direction is:

```text
Arena / runner
    |  persists report + replay + config + RuntimeOccurrenceV1
    v
upper orchestration / CLI harness
    |  open_completion_league() + complete_runtime_occurrence()
    v
Studio League ledger + archive
```

**Arena produces durable occurrence evidence; Studio completion consumes it; the
upper orchestrator joins them — never Arena core.** `splendor-arena` stays
unaware of Studio League.

### Scope

In scope, exactly one real runtime completion path:

- mint and durably persist the occurrence envelope for a completed arena match,
  exactly once, at completion;
- have the upper orchestration layer offer that persisted evidence to the
  completion outlet;
- make a completion failure visible without falsifying the match result.

### Non-goals (explicitly not authorized)

- No `splendor-arena` → `splendor-studio-league` dependency.
- No evaluation wiring, no batch/worker wiring, no watcher, no Host API, no UI.
- No change to the ledger, Elo, eligibility, archive or completion authority. The
  frozen authorities are consumed as-is.
- No re-run of the 42k historical migration; no new historical digest.
- No new public surface in `splendor-studio-league`.

### Contracts and invariants

**C1 — the match is a fact, completion is a separate fact.**
`run-match`'s frozen contract (exit `0` completed / `2` aborted / `1` error, no
artifacts left behind on error, stdout exactly one outcome line) must not be
reinterpreted. A *studio completion* failure is not an *arena match* failure. The
observable outcome must distinguish "match completed, Studio completion failed"
from "match failed".

**C2 — the envelope is produced once, from persisted bytes.**
`occurrence_id` and `completed_at` are minted at completion time and are never
re-derived or re-minted by any consumer, retry, or rebuild. The orchestrator
consumes the durable envelope; it does not construct one.

**C3 — the four evidence documents are durable before completion is attempted.**
report, replay, config and envelope must all be on disk (and, for report/replay,
already through `run-match`'s atomic publish) before the outlet is called. The
evidence must survive any completion failure unmodified.

**C4 — retry replays documents, never matches.**
Re-offering completion after a failure re-reads the same four documents. It must
not re-run the game, re-serialize the report, or regenerate the envelope.

**C5 — idempotency is the ledger's, not the wiring's.**
A repeated trigger for one completion yields the ledger's own answer
(`AlreadyPresent`, `0` rating events). The wiring must not add a second
deduplication layer, and must not swallow `SourceConflict` — a changed document
under an existing occurrence identity is a real conflict and stays fail-closed.

**C6 — no hidden success.**
A completion failure must never print or persist a receipt, must never leave a
partial ledger row, and must be distinguishable by exit code and by machine-
readable output.

### Acceptance gates (frozen before implementation)

1. **Real completion enters the league.**
   A real runner completes a match, the four evidence documents exist on disk,
   and the occurrence enters the Studio ledger plus the content-addressed
   archive, with the expected rating events.

2. **Completion failure is not match failure.**
   With completion forced to fail, the match evidence is still complete and
   unmodified, the ledger contains no fake success, and after the failing
   condition is repaired, retrying *only* the completion step books the
   occurrence — without re-running the match.

3. **Repeated wiring is idempotent.**
   Triggering the same completion twice yields `AlreadyPresent` on the second
   attempt and produces no duplicate Elo events.

Each gate is a real end-to-end test over on-disk documents, not a mock.

### Open questions to settle during implementation

- Whether the envelope is published by `run-match` itself (a new, explicitly
  opt-in flag) or by a small separate harness command that runs the match and
  then persists evidence. The owner's contract only requires that the evidence be
  durably present *before* the outlet is called and that retry not re-run the
  match; both shapes satisfy it. The deciding constraint is C1: `run-match`'s
  published exit-code/stdout contract is frozen and heavily tested, so the
  evidence must not change that contract's meaning.
  *Settled before implementation, because it decides the whole shape: neither.*
  `run-match` keeps its frozen contract untouched. It gains no Studio League
  dependency and no new flag, because roughly fifteen end-to-end tests pin its
  exit codes, its empty-stdout-on-error rule and its artifact-refusal rules, and
  C1 forbids reinterpreting them.
  Instead the whole slice lives in the **upper orchestration layer, which already
  exists**: `splendor-cli`'s Studio League command family already depends on
  `splendor-arena` *and* `splendor-studio-league`, which is precisely the "upper
  orchestration / CLI harness" position the owner's layering diagram describes.
  The producer mints and persists the envelope there, and the same layer offers it
  to the completion outlet. Arena core stays unaware of the league, no new
  cross-crate edge appears, and the frozen arena CLI contract is untouched.

### Final implementation

The slice is delivered in the **upper orchestration layer** and nowhere else.

*New module* `crates/splendor-cli/src/completion_wiring_command.rs`, and two
commands wired in `main.rs`:

| Command | Role |
|---|---|
| `splendor studio-league-complete-match` | runs one real arena match, durably persists the four evidence documents, then offers them to the completion outlet |
| `splendor studio-league-complete` | completion-only retry: re-reads the four persisted documents and offers them again |

Nothing in `splendor-arena` changed, and `splendor-arena` still does not depend on
`splendor-studio-league`. `run-match` is untouched — its exit codes, its
one-line stdout and its artifact-refusal rules are frozen and remain covered by
their existing end-to-end tests.

**Envelope production.** `studio-league-complete-match` mints `occurrence_id`
(from the caller, with the run) and `completed_at` (`now_epoch_seconds()`) exactly
once, at completion, and persists the envelope after the report and replay have
been published. The evidence hashes cover the **serialized published bytes**, not
the in-memory values, so the envelope attests to what is actually on disk. The
publish order is replay → report (the existing commit marker) → envelope; if the
envelope cannot be written, report and replay are rolled back, so an occurrence
whose evidence set is incomplete can never look finished.

**Two facts, two exit codes.** This is the contract the owner asked for, made
mechanical:

| Situation | Exit | Meaning |
|---|---|---|
| match completed, completion succeeded | `0` | both facts are good |
| match completed, completion failed | `3` | the **match** is a real completed match; only completion failed; evidence is intact |
| match failed / aborted / bad evidence set | `1` or `2` | the failure belongs to the match half |
| usage error | `2` | bad arguments |

On a completion failure the message names the failing half explicitly and prints
the exact retry command, and the evidence is left byte-for-byte untouched.

**Retry cannot re-run a match, structurally.** The module contains exactly one
`ArenaRunner::run` call site, inside `run_studio_league_complete_match`.
`run_studio_league_complete` has no path to the runner at all — it reads four
files and calls the outlet. This is a property of the call graph, not a
convention.

**No new public surface.** `RuntimeOccurrenceV1` already had public fields and was
already exported, as was `replay_document_sha256`; the orchestrator builds and
hashes the envelope with what already exists. `splendor-studio-league` was not
modified at all in this slice.

### Iteration log

- **Envelope producer had to be written for real.** Reconnaissance found that
  every `RuntimeOccurrenceV1` in the repository was hand-written inside a test;
  no production code had ever minted one. This slice is therefore the first
  production producer, and the first time the durable-evidence half of Commit C
  is exercised by anything other than a fixture.
- **Where the edge lives.** Decided against touching `run-match` (see the frozen
  design's resolved question): roughly fifteen end-to-end tests pin its exit
  codes and refusal rules, and the owner's C1 forbids reinterpreting them. The
  `splendor-cli` Studio League family already sits in the exact "upper
  orchestration" position and already depends on both crates.
- **Gate 2's first forced failure did not fail.** The initial version broke the
  completion half by pointing `--db` at a path whose parent did not exist. The
  command exited `0`: `open_league` deliberately creates missing parent
  directories (`schema.rs`), so that is not a failure at all. The gate now forces
  a **missing identity manifest**, which `open_completion_league` genuinely
  refuses (that refusal is one of the Slice 3 Repair 1 gates). Recorded here
  because "the test's chosen failure was not actually a failure" is exactly the
  kind of gate defect that would otherwise silently pass.
- **Two seats of the same agent are a self-match.** The gates were first written
  with `agent-random` in both seats. The occurrence was recorded, but
  `rating_eligible = 0` with `rating_ineligible_reason = self_match`, so there
  were **zero** rating events — and the idempotency gate became vacuous ("no
  duplicate Elo" held because there was never any Elo). The gates now use
  `agent-heuristic` vs `agent-random`, which report distinct runtime identities
  (`splendor-cli-heuristic` / `splendor-cli-random`). Verified against the
  database: `rating_eligible = 1`, two real events (1500 → 1516 / 1484).

### Validation and evidence

Three end-to-end gates in `crates/splendor-cli/tests/completion_wiring.rs`, all
driving real subprocess agents through the process boundary:

1. `a_real_match_completion_enters_the_ledger_and_the_archive` — the match
   completes; all four documents exist; the envelope hashes match the bytes on
   disk; the ledger row is `runtime:occ-gate1` with `storage = archive` and a
   **relative** path; `STUDIO_LEAGUE_REPLAY_DIR + path` resolves to an object
   hashing to the envelope's `replay_sha256`; two rating events are recorded.
2. `a_completion_failure_preserves_the_match_and_can_be_retried_alone` — with the
   identity manifest absent, the exit code is `3`, stdout records that the match
   completed, stderr says the match is unaffected, no match is booked, and the
   three evidence documents are byte-identical afterwards. Retrying completion
   alone then books it, with the evidence still byte-identical.
3. `triggering_the_same_completion_twice_is_idempotent_and_adds_no_elo` —
   re-offering yields `already_present`, exactly one match row, and an unchanged
   rating-event count.

**Negative controls (all run, then reverted):**

| Control | Result |
|---|---|
| collapse the two facts (return `1` instead of `3` on completion failure, dropping the "match is unaffected" message) | gate 2 **FAILS** |
| assert `rating_events == after + 1` on re-offer | gate 3 **FAILS** — the ledger really does not double-book |

One further structural check: `ArenaRunner::run` appears exactly once in the
module, in the match entry point; the completion-only entry point cannot reach it.

**Results.** `splendor-studio-league` **80/80** unchanged. Whole `splendor-cli`
suite **44 test binaries / 271 tests, 0 failed** (was 43 / 268 — the three new
gates), `--bin splendor` 89/89, `arena_cli` 24/24 and `completion_equivalence`
1/1 unchanged. `git diff --check` exit 0; `rustfmt --edition 2021` on the three
touched files only. The 42k historical migration was not re-run. There are no
cloud status checks for this commit; none are claimed.

### Result and decision

`IMPLEMENTED` / locally `VERIFIED`. Not `ACCEPTED`: the owner's review is the gate.
Arena/runner wiring is now exercised by one real runtime completion path;
Host API and UI remain not authorized.

### Known limitations

- Exactly one completion path is wired, as instructed. Evaluation runs, batch
  workers, watchers, the Host API and the UI are deliberately untouched.
- The wiring inherits the documented slice-3 boundary: generic ledger/archive
  tools stay public, so a determined external caller can still assemble a chain
  by hand. What this slice closes is that the **production** path now goes
  through the outlet, not that the crate is a sandbox.
- `studio-league-complete-match` reports an aborted match with exit `2` (the
  arena CLI's own convention for "aborted") and writes only the report. No
  occurrence evidence exists for an aborted match, because the occurrence never
  happened.
- The archive root remains the relative protocol constant, so these commands must
  run with the project root as their working directory. The gates set `cwd`
  explicitly; a future Host/launcher must unify project-root resolution (already
  recorded as a deferred slice-3 note).

### Next authorized gate

Owner review of this slice. Host API and UI remain **not authorized**.

> **Update (2026-09-13).** The owner's review accepted the architecture, the layering and the
> structural retry property, and raised two P1s plus one P2: the config was still the caller's input
> file rather than producer-persisted evidence (and was read twice), the receipt export could
> overwrite evidence or the database, and exit code `2` meant both "arena aborted" and "bad usage".
> The claim above that four documents were durably persisted was therefore true for only three. See
> *Commit C Next Slice Repair 1* below.

---

## Commit C Next Slice Repair 1 — the fourth evidence document was never persisted (2026-09-13)

Status: **IMPLEMENTED + locally VERIFIED**, awaiting owner review. Baseline `2b06d7f`.
Owner review of `2b06d7f` = **REPAIR_REQUIRED (P0=0 / P1=2 / P2=1)**. The architecture was
accepted: the layering (no `splendor-arena` → `splendor-studio-league` edge), the untouched frozen
`run-match`, and the structural "retry cannot re-run a match" property all stand.

### P1-1: the config was an input file, not producer-persisted evidence

The slice claimed report + replay + config + envelope as four durable evidence documents. Only
three were actually published by the producer: the report, the replay and the envelope. The config
was the caller's **original `--config` input file**, re-read after the match to be hashed.

Two consequences, both real:

1. **The retry was not self-contained.** If completion failed (exit `3`) and the user then moved,
   edited or deleted the original `--config`, report/replay/envelope were intact but the exact
   config evidence was gone. The envelope records a `config_sha256`, which can prove what is
   missing but cannot restore the bytes.
2. **The hash could describe a file the runner never consumed.** The code read the config twice —
   `read_config(&parsed.config)` to parse, then `fs::read(&parsed.config)` to hash. A change between
   the two reads would make `config_sha256` attest to bytes that did not produce the match.

**Fix.** `--config-out` is now required, and the config is read **once**:

```text
read config bytes ONCE
  -> parse ArenaConfig from those same bytes        (parse_config_bytes)
  -> ArenaRunner::run(parsed config)
  -> persist the exact bytes to --config-out
  -> envelope.config_sha256 = SHA256(those bytes)
```

`read_config` keeps its path-based signature and now delegates to the new
`arena_command::parse_config_bytes`, so `run-match`'s limits, strictness and error messages are
byte-for-byte unchanged (a pure refactor; `arena_cli` 24/24 and `--bin splendor` 89/89 still pass).

Publish order is now **config snapshot → replay → report (commit marker) → envelope**, with every
already-written document rolled back if a later step fails, so an incomplete evidence set can never
be left looking finished. The retry hint printed on a completion failure names `--config-out`, never
the original input.

**Gate.** Gate 2 now **deletes the original `--config`** after the exit-3 failure and then retries
from the persisted four documents alone. Negative control: making the retry depend on the original
input instead fails with `cannot read config … os error 2` — i.e. the gate really does test the
durability of the fourth document.

### P1-2: the receipt export could destroy the evidence, or the league

The receipt export ended in `fs::write(path, text)`, which overwrites. Nothing stopped `--json` from
naming `--report-out`, `--replay-out`, `--occurrence-out`, `--config-out`, `--db` or `--identity`.
Because the receipt is written *after* the occurrence is booked, an aliased path would have replaced
the very evidence the booking depends on — or, if `--db` was targeted, the league itself — with a
JSON receipt. A successful completion destroying its own durable state is precisely the truthfulness
property this slice exists to establish.

**Fix, two layers:**

1. The receipt is published with `atomic_output::commit_single`, which is create-if-absent and
   **never overwrites**. This is the real backstop; it holds even for an alias the parser cannot see.
2. `--json` is additionally rejected at parse time when it aliases any evidence document, the config
   input, the database or the identity manifest (`reject_receipt_alias` / `paths_alias`, which
   compares raw paths and then canonicalised parents). The four outputs are also now required to be
   pairwise distinct and distinct from `--config`. This layer exists so an obvious mistake is an
   immediate usage error rather than a silent refusal after the fact.

**Gate.** Gate 4 points `--json` at every evidence document, the DB and the identity manifest, and
also at two routes the parser provably cannot detect — a `sub/../report.json` spelling and a
**hardlink** to the report — then asserts that every byte of evidence, the identity manifest and the
logical league state are unchanged, and that the DB is still a real SQLite file rather than a
receipt. It also asserts that a *non-colliding* `--json` still writes normally, so the primitive is
not simply refusing everything.

Negative control: reverting `commit_single` to `fs::write` makes gate 4 **fail** on the hardlink
route. That control was essential, because the gate's first version passed even with the destructive
write — the parse-time alias check alone was catching the obvious cases. The gate as shipped tests
the primitive, not just the parser.

### P2: exit code `2` meant two different things

`studio-league-complete-match`'s help documented `2 = bad usage`, but the aborted-match branch also
returned `2`. Since this command deliberately mirrors `run-match`, where `2` is the frozen meaning of
"arena aborted", automation could not distinguish "the match aborted" from "you typed a flag wrong".

**Fix.** The match half now uses `run-match`'s frozen meanings exactly, and usage gets its own code:

| Code | Meaning |
|---|---|
| `0` | match completed and Studio completion fine |
| `3` | match completed, Studio completion failed (evidence intact) |
| `2` | arena aborted (same as `run-match`) |
| `1` | config / I/O / internal producer error |
| `64` | bad usage (`EX_USAGE`) |

`studio-league-complete` keeps its own smaller space: `0` success/idempotent, `1` completion
failure, `64` bad usage.

### Validation and evidence

| Gate | Command | Result |
|---|---|---|
| 1 | `cargo test -p splendor-cli --test completion_wiring a_real_match_completion_enters_the_ledger_and_the_archive` | PASS |
| 2 | `… a_completion_failure_preserves_the_match_and_can_be_retried_alone` | PASS (original config deleted before retry) |
| 3 | `… triggering_the_same_completion_twice_is_idempotent_and_adds_no_elo` | PASS |
| 4 | `… a_receipt_export_can_never_overwrite_evidence_or_league_state` | PASS |

Manual exit-code check: usage error → **64**, bad flag → **64**, `--help` → **0**, forced abort → **2**
with only the report written (no snapshot, occurrence, replay or league). Negative controls run and
reverted: destructive `fs::write` → gate 4 fails (hardlink route); retry depending on the original
config → gate 2 fails (`os error 2`).

Baselines: `splendor-studio-league` **80/80** unchanged; whole `splendor-cli` suite **44 test
binaries / 272 tests, 0 failed** (was 271; gate 4 added), `--bin splendor` 89/89, `arena_cli` 24/24,
`completion_equivalence` 1/1. `git diff --check` exit 0; `rustfmt --edition 2021` on the touched
files only. The 42k migration was not re-run. No cloud status checks exist for this commit and none
are claimed.

### Known limitations

- `parse_config_bytes` duplicates the size/UTF-8 checks with `read_config`; the shapes differ only in
  that the path entry point bounds its read first. Kept deliberately so `run-match`'s existing
  messages are untouched.
- The parse-time alias check is a convenience, not the guarantee: a path reached through a route it
  cannot canonicalise (or a different filesystem view) is still safe because the publish primitive
  refuses to overwrite. The guarantee is the primitive.
- Gate 4 compares the league database logically (header + row counts + rating-event count) rather
  than byte-for-byte, because the colliding attempts are still legitimate completion calls and a
  session legitimately touches its own metadata. Byte equality would have been a wrong assertion,
  not a stronger one.

### Next authorized gate

Owner review of this repair. Host API and UI remain **not authorized**.

> **Update (2026-09-13).** The owner's review confirmed both P1s here as genuinely fixed (single-read
> config with a persisted snapshot, and a receipt export that cannot overwrite). Two narrower findings
> remained: the config snapshot and the occurrence envelope were still published by a private
> `create_new` + `write_all` + `flush` helper rather than the shared atomic machinery, and the
> completion-only path printed the other command's name on a missing-argument error. See
> *Commit C Next Slice Repair 2* below.

---

## Commit C Next Slice Repair 2 — the last two evidence documents publish atomically (2026-09-13)

Status: **IMPLEMENTED + locally VERIFIED**, awaiting owner review. Baseline `80b0403`.
Owner review of `80b0403` = **REPAIR_REQUIRED (P0=0 / P1=1 / P2=1)**. Both original P1s were
confirmed fixed: the config is genuinely single-read (same bytes parsed, run, hashed, persisted) and
Gate 2 deletes the original `--config` before retrying from the four persisted documents; the receipt
export is genuinely non-destructive via `commit_single`, with Gate 4's hardlink route proving it tests
the primitive rather than the parser. This round is a narrow close patch.

### P1: the config snapshot and the occurrence envelope did not publish atomically

`persist_completed_evidence` published in the right order — config → replay → report → envelope — but
steps 1 and 4 went through a private helper, `write_new_file`, that was not in the same class as the
report/replay machinery:

```rust
// before
fn write_new_file(path: &Path, contents: &str) -> io::Result<()> {
    let mut file = OpenOptions::new().write(true).create_new(true).open(path)?;
    file.write_all(contents.as_bytes())?;
    file.flush()
}
```

Two defects:

1. **`create_new` guarantees "does not overwrite", not "completes atomically".** If `write_all` failed
   part-way (ENOSPC, I/O error), the *final path* already existed holding a half-written config or
   envelope. `create_new` prevents clobbering; it does not prevent a truncated artifact at the real
   name.
2. **It only `flush`ed.** No `sync_all`, so the document was not durable on return — weaker than the
   `atomic_output` machinery the rest of the evidence set (and this round's own claims) rely on.

The error handling compounded it. The config branch returned without removing a possibly-created
target, and the envelope branch removed report/replay/config but **not** `--occurrence-out` — so an
extreme I/O failure could leave a final-path partial occurrence envelope. That directly contradicts the
invariant this slice exists to hold: *a producer error must never leave something that looks like a
half-published occurrence.*

**Fix.** Use the primitive that already exists and that this round's receipt export already adopted:

```rust
atomic_output::commit_single(&parsed.config_out, config_text)
atomic_output::commit_single(&parsed.occurrence_out, &occurrence_json)
```

`write_new_file` is deleted, along with the now-unused `use std::io::{self, Write};`.

`commit_single` is `temp → write → flush → sync_all → create-if-absent publish`, where the publish is
a `hard_link` (the true commit point, failing if the target exists) followed by best-effort temp
unlink. So every one of the four evidence documents now has identical publish semantics:

| Document | Publish |
|---|---|
| config snapshot | `commit_single` |
| replay | `commit_completed_with` (same machinery) |
| report | `commit_completed_with` (commit marker) |
| envelope | `commit_single` |

Rollback stays best-effort `remove_file` (unchanged). The residual state after an external filesystem
fault is now at worst a **complete, atomically published** artifact rather than a truncated
final-path JSON — and with no envelope, the occurrence is not treated as complete. That is the
boundary the owner accepted.

**No new test was added, deliberately.** The primitive's own gates already cover exactly this
behaviour and run in the same suite (`--bin splendor`, 89/89):

- `atomic_output::tests::single_commit_publish_failure_leaves_no_residue` — the "no partial final
  path" guarantee, which is the P1 itself;
- `atomic_output::tests::single_commit_writes_target_with_no_residue`;
- `atomic_output::tests::single_commit_refuses_to_overwrite_and_preserves_sentinel`;
- `atomic_output::tests::single_commit_unlink_failure_still_commits_target`.

### P2: the completion-only path printed the wrong command name

The missing-required-arguments branch of `studio-league-complete` called `fail_usage`, whose message
prefix is `studio-league-complete-match:`, so the error named a command the user had not run. The exit
code was already correct (64); only the text was wrong. Changed to `fail_usage_complete`, giving
`studio-league-complete:`.

### Validation and evidence

| Check | Command | Result |
|---|---|---|
| 4 wiring gates | `cargo test -p splendor-cli --test completion_wiring` | 4 passed |
| frozen arena contract | `cargo test -p splendor-cli --test arena_cli` | 24 passed |
| CLI ↔ outlet equivalence | `cargo test -p splendor-cli --test completion_equivalence` | 1 passed |
| binary suite (primitive gates) | `cargo test -p splendor-cli --bin splendor` | 89 passed |
| studio league | `cargo test -p splendor-studio-league` | 80 passed |
| whole CLI suite | `cargo test -p splendor-cli` | 44 binaries / 272 tests, 0 failed |

Behavioural probe over a real match (temporary directory, real subprocess agents):

- exit `0`; all four documents parse as JSON; the config snapshot is **byte-identical** to the input;
- **zero `*.tmp` residue** in the output tree, confirming the create-if-absent publish unlinks its temp;
- with a pre-existing `--config-out`, the command exits `64`, leaves that file **untouched**, and
  writes **neither** report nor envelope — so a refused publish leaves no partial set.

Exit-code spot checks after the patch: `studio-league-complete` with no arguments prints
`studio-league-complete: --occurrence, --report, --replay and --config are all required` and exits
`64`.

`git diff --check` exit 0; `rustfmt --edition 2021` on the single touched file. The 42k migration was
not re-run. No cloud status checks exist for this commit and none are claimed.

### Known limitations

- Rollback after a successful publish remains best-effort `remove_file`. If the filesystem itself is
  failing, a complete artifact may survive alongside the error. That is deliberate and is the accepted
  boundary: a surviving artifact is always complete and atomically published, and without the envelope
  the set is not read as a finished occurrence.
- A `commit_single` that fails mid-`write_all` can leave its sibling temp file behind if the process
  dies before cleanup. This is the same trade-off the existing report/replay machinery already makes;
  the guarantee that matters is that the **final path** is never partial.

### Next authorized gate

Owner review of this repair. Expected outcome on acceptance: **Completion Producer Wiring ACCEPTED /
CLOSED**, then a decision on whether the next product surface is the Host API or unified
project-root / launcher path resolution. Host API and UI remain **not authorized** until then.

*Settled:* the owner accepted / closed Completion Producer Wiring at `6170c7c` and chose
**project-root / launcher path resolution** as the next slice, explicitly *before* the Host API and
explicitly not the Host API. See the following section.

## Commit C Next Slice — Project-Root / Launcher Resolution (2026-09-14)

- **Status**: `IMPLEMENTED` / `VERIFIED` locally, pending owner review.
- **Baseline**: `6170c7c2abd6937fcd094d3c7b1710062357d2da`. The owner formally closed the previous
  slice there — **Completion Producer Wiring ACCEPTED / CLOSED (P0=0 / P1=0 / P2=0)** — and corrected
  the delivery description: GitHub records **two tracked files** for `6170c7c`
  (`crates/splendor-cli/src/completion_wiring_command.rs` and `docs/studio-league-v1.md`), the code
  file being only `+11/-14`; the repository has **no cloud status checks**, so the four wiring gates,
  `--bin splendor` 89/89, `splendor-studio-league` 80/80 and the 272-test CLI suite are **local
  evidence only**.
- **Round type**: product milestone plumbing. No authority change.

### Problem and evidence

Every Studio League location was an independent string literal, and the one location that could not be
supplied by a caller was silently defined relative to the process working directory.

Read directly at `6170c7c`:

1. `crates/splendor-studio-league/src/lib.rs` declared **four parallel literals** with an unenforced
   repeated prefix `local-artifacts/studio-league`: `STUDIO_LEAGUE_DIR`, `STUDIO_LEAGUE_DB_FILE`,
   `STUDIO_LEAGUE_IDENTITY_FILE`, `STUDIO_LEAGUE_REPLAY_DIR`. `STUDIO_LEAGUE_DIR` was referenced by
   **nothing** — the shared prefix existed only as text repeated three times.
2. `crates/splendor-studio-league/src/completion.rs` bound `Path::new(STUDIO_LEAGUE_REPLAY_DIR)`
   **inside** the outlet. That was deliberate (Slice 3 Repair 1 had just closed the `--archive-root`
   seam), but it left exactly one meaning for the replay root: *the literal resolved against the
   process cwd*. The ledger stores only content-relative `replay_path` values, so "relative to what"
   was a property of how the process happened to start.
3. Three test files were forced to change the process working directory to make that work:
   `crates/splendor-studio-league/tests/archive_protocol_root.rs`,
   `crates/splendor-studio-league/tests/completion_outlet.rs` (a `OnceLock` sandbox, because a
   process-wide cwd change would race other tests in the same binary), and
   `crates/splendor-cli/tests/completion_equivalence.rs`.
4. `open_completion_league` had ~8 call sites, each choosing a database path and an identity path
   separately (production: `completion_wiring_command.rs`, `studio_league_command.rs`).
5. Naming: `--root` was **already taken** on `studio-league-inventory`, `studio-league-dry-run` and
   `studio-league-migrate` (a repeatable corpus-scan root), so the new concept needed a different name.

The owner's reason for doing this **before** the Host API: the ledger stores content-relative replay
paths, and changing "relative to what" later would force the Host, the launcher, the CLI and the
replay reader to be reworked together. Settling root resolution first keeps that blast radius at zero.

### Initial design

One value object owns the derivation, and nothing else composes paths:

```rust
pub struct StudioLeaguePathsV1 { root, dir, db, identity, replay_root }
impl StudioLeaguePathsV1 {
    pub fn from_root(root: &Path) -> Self;              // the only composer
    pub fn resolve(explicit: Option<&Path>) -> Self;    // Some = explicit; None = today's default
    pub fn root/dir/db/identity/replay_root(&self) -> &Path;
}
```

- `from_root` derives `dir = root/local-artifacts/studio-league` and then the three leaf paths from
  `dir`, so the prefix exists **once**, in code.
- `resolve(None)` is `from_root(Path::new(""))`, which reproduces today's bare relative paths
  byte-for-byte. That is what makes the default a no-regression: existing commands behave identically
  when no root is given.
- Threading decision: `open_completion_league(paths: &StudioLeaguePathsV1, now: i64)`, and
  `CompletionLeagueV1` privately stores the replay root it captured at session open.
  **`complete_runtime_occurrence(league, request)` keeps its signature** — no path parameter is added.
  This is the point that preserves Slice 3 Repair 1: a caller still cannot choose an arbitrary archive
  root *at completion time*; it chooses a project root **once**, when it opens the session, and every
  recorded relative path is then resolvable against the root that session was opened with.
- Constants: keep `STUDIO_LEAGUE_DIR`; replace the three parallel path literals with
  `STUDIO_LEAGUE_DB_NAME`, `STUDIO_LEAGUE_IDENTITY_NAME`, `STUDIO_LEAGUE_REPLAY_DIR_NAME`.
- CLI surface: a single `--project-root <dir>` on the four league-path commands
  (`studio-league-migrate`, `studio-league-ingest`, `studio-league-complete-match`,
  `studio-league-complete`), **replacing** their `--db` / `--identity` flags. Corpus `--root` untouched.

### Scope and non-goals

In scope: the path value object and its constants in `splendor-studio-league`; threading it through
the completion session; `--project-root` on the four commands; migrating the tests off cwd sandboxes.

Non-goals, explicitly not authorized: Host API, UI, any launcher, any new read surface; **no authority
change** (ledger, Elo, eligibility, archive, completion semantics all untouched); no layout change
(the protocol layout is still `local-artifacts/studio-league/{league.sqlite3,identity.json,replays}`);
no re-run of the 42k migration; no auto-discovery of the project root.

### Contracts and invariants

- **I1 — one derivation.** Every protocol path is produced by `from_root`; no other code joins the
  prefix. Four literals become three leaf names plus one directory name.
- **I2 — cwd independence.** Given the same explicit root, evidence and league state are identical no
  matter which directory the process runs in, and everything lands under that root.
- **I3 — no regression at the default.** `resolve(None)` must reproduce the previous behaviour
  exactly, including the exact relative strings.
- **I4 — the reader contract survives.** A row's `replay_path` must still be resolvable as
  `replay root + relative path`, hashing to the recorded `replay_document_hash`.
- **I5 — no authority reopened.** The project root is chosen once, at session open. Completion still
  receives no root, and a session still refuses to open without identity evidence.

### Final implementation

`crates/splendor-studio-league/src/paths.rs` (new) — `StudioLeaguePathsV1` with `from_root`,
`resolve`, and five getters, plus three unit tests: `all_protocol_paths_derive_from_one_root`,
`the_default_resolution_is_the_bare_protocol_relative_layout`,
`an_explicit_root_wins_over_the_default`.

`lib.rs` — the three parallel path literals became `STUDIO_LEAGUE_DB_NAME`,
`STUDIO_LEAGUE_IDENTITY_NAME`, `STUDIO_LEAGUE_REPLAY_DIR_NAME`; `pub mod paths;` and
`pub use paths::StudioLeaguePathsV1;`. `STUDIO_LEAGUE_DIR` is now actually used (by `from_root`).
*(Repair 1 later moved these four names into `paths.rs` as private constants and removed them from
the crate root, because publishing them was itself a second path authority — see the Repair 1
section.)*

`completion.rs` — `CompletionLeagueV1 { conn, replay_root }`; `open_completion_league(paths, now)`
uses `paths.db()` / `paths.identity()` and captures `paths.replay_root().to_path_buf()`. In
`complete_runtime_occurrence` the replay root is cloned **before** `league.conn` is mutably borrowed,
then passed to `archive_replay`.

`crates/splendor-cli/src/completion_wiring_command.rs` — `CompleteArgs.identity/db` became
`paths: StudioLeaguePathsV1`; `--identity`/`--db` parsing replaced by `--project-root`, resolved once
via `StudioLeaguePathsV1::resolve(project_root.as_deref())`; `complete_persisted(...)` now takes
`paths: &StudioLeaguePathsV1`; the receipt-alias check now compares against `paths.db()`,
`paths.identity()` and `paths.replay_root()`.

`crates/splendor-cli/src/studio_league_command.rs` — same flag change on `studio-league-migrate` and
`studio-league-ingest`. `migrate` keeps its local `identity_path` / `db_path` names (it uses them
throughout its staging/rename/reconciliation body) but derives them from the resolved paths.

Tests — all three cwd sandboxes are gone or repurposed:

- `completion_outlet.rs`: the `OnceLock` cwd sandbox and the `std::env::set_current_dir` call were
  **deleted**. Each `League` now owns a root and a `StudioLeaguePathsV1`; `object_path` /
  `archive_root` became methods on that league, so per-test isolation comes from each test's own root
  rather than from a shared process cwd.
- `archive_protocol_root.rs`: now builds `StudioLeaguePathsV1::from_root(&root)` and, as a stronger
  form of the same assertion, deliberately runs from an **unrelated** working directory, then asserts
  the object is under the chosen root and that nothing was created relative to the cwd.
- `completion_equivalence.rs`: the CLI child and the direct outlet call now use **two different
  explicit roots**, from a cwd that is neither of them; both objects are asserted under their own
  root, and the two ledgers are still compared field-by-field.
- `completion_wiring.rs`: the sandbox identity/db pair became `--project-root`; a new fifth gate
  (below) runs the identical argv from an unrelated cwd.

### Iteration log

- **`--root` was unavailable**, so the flag is `--project-root`. Recorded here because it is the kind
  of naming collision that silently changes an unrelated command's meaning.
- **The `--db`/`--identity` removal is a deliberate breaking change** to the four league-path commands.
  Keeping both would have allowed a state where the database lives under root A while the session
  archives under root B — exactly the drift this slice exists to prevent. No compatibility shim was
  added; the affected commands are still unreleased local surfaces.
- **`complete_runtime_occurrence` was deliberately left with no path parameter.** The obvious
  "simplification" (pass the replay root straight into completion) would reopen Slice 3 Repair 1's
  seam one round after it was closed. The root belongs to the session, not to the call.
- **Per-test isolation forced the test refactor.** With paths derived from a single root, two tests
  sharing one root would share one database; that is why `object_path` had to become root-aware
  instead of staying a sandbox-global helper. The chdir removal is a consequence, not the goal.
- **`completion_equivalence` initially failed on the leaderboard.** Each root minted its own identity
  manifest, so the two runs differed by one freshly generated local participant id (`58a7acd6...`
  vs `9910f9ac...`) — the comparison was measuring identity minting, not evidence handling. Fixed by
  minting one manifest and publishing it into both roots.
- **`completion_outlet`'s first repair attempt did not compile**: the concurrent-producer gate moved
  the shared paths into an `FnMut` closure. Fixed by capturing a shared reference
  (`&StudioLeaguePathsV1` is `Copy`), which is also what the previous `&Path` capture did.
- **Two pre-existing gates also caught the regression during the negative control** (see below),
  which is a sign the wiring gates were already exercising the session honestly.

### Validation and evidence

- `cargo test -p splendor-studio-league`: **83 passed / 0 failed** (was 80/80; +3 new `paths` unit
  tests). Breakdown: lib 34 (17 unit incl. 3 new + 17 relocated chain tests), `archive_protocol_root`
  1, `completion_outlet` 7, `historical_resolver` 3, `league_core` 29, `policy_identity` 5,
  `replay_index` 4.
- `cargo test -p splendor-cli`: **273 passed / 0 failed** across 44 test binaries (was 272; +1 new
  gate). `--bin splendor` 89/89, `arena_cli` 24/24, `completion_equivalence` 1/1, `completion_wiring`
  4 -> **5**.
- **New gate** (`crates/splendor-cli/tests/completion_wiring.rs`):
  `an_explicit_project_root_decides_the_location_regardless_of_the_cwd` — runs
  `studio-league-complete-match` with `--project-root <sandbox>` from a working directory that is
  neither the root nor inside it, asserts exit 0, exactly one ledger row
  (`runtime:occ-gate-cwd`, `storage = archive`), that the recorded relative path resolves under the
  chosen root, and that **nothing** was created at `<cwd>/local-artifacts`.
- **Negative control (run, then reverted):** `StudioLeaguePathsV1::resolve` was patched to ignore its
  explicit argument and always return the default. Result: the crate unit test
  `an_explicit_root_wins_over_the_default` **FAILED**; the new CLI gate **FAILED** with the exact
  diagnostic `cannot open the league for completion: invalid studio league document: identity manifest
  does not exist` (the explicit root had been ignored and the cwd consulted), and the pre-existing
  forced-failure gate `a_completion_failure_preserves_the_match_and_can_be_retried_alone` **FAILED**
  too, because the root that was supposed to hold no identity was no longer being consulted. After
  restoring the file, all of the above is green again.
- Static: `git diff --check` exit 0; NUL bytes 0; CRLF 0; `rustfmt --edition 2021` run on the nine
  touched files only, and `git status --porcelain` shows exactly those nine paths (no unrelated
  reflow). Build warnings are limited to the pre-existing `s2_census_command.rs` and
  `studio_league_command.rs` sites.
- The 42k historical migration was **not** re-run. There are **no cloud status checks**; every number
  above is local evidence.

### Result and decision

`IMPLEMENTED` / `VERIFIED` locally. The default resolution is byte-identical to the previous layout,
so no existing behaviour changes unless a caller opts into `--project-root`; when it does, the
database, the identity manifest and the replay archive can no longer be chosen apart, and the process
working directory stops deciding where a league lives. Two crate-internal test binaries no longer
need to change the process cwd at all.

`ACCEPTED` is **not** claimed; that is the owner's verdict after review.

### Known limitations

- `StudioLeaguePathsV1::from_root` is public, so a library caller can still point a session at any
  project root. That is the intended surface of this slice (choosing the root once, at session open);
  it is not a sandbox, exactly as recorded for the previous slice. What remains closed is choosing a
  root at completion time.
- Root resolution is explicit only: there is no discovery, no environment variable, and no search
  upward for a project marker. A launcher must know its root, or run from it.
- `--db` / `--identity` were removed rather than deprecated, so any existing local script that passes
  them now gets exit `64` (usage). That is deliberate and recorded above.
- The protocol layout itself is unchanged; this slice only makes "relative to what" explicit.
- `read_archived_replay` still has no production caller. Invariant I4 is therefore validated through
  the ledger row (`archive_protocol_root`), not through a read surface.

### Next authorized gate

Owner review of this slice. On acceptance, the remaining product-surface decision recorded at the
previous gate is the **Host API** (root resolution having now been settled first, which was the point
of the ordering). Host API and UI remain **not authorized** until that decision.

*Review outcome:* `REPAIR_REQUIRED` (P0=0 / P1=1 / P2=1) — the design was accepted, but the crate
root still published a second path authority. See the following section.

## Commit C Next Slice Repair 1 — one path authority on the public surface (2026-09-14)

- **Status**: `IMPLEMENTED` / `VERIFIED` locally, pending owner review.
- **Baseline**: `3bd5fe57dcfb47707ed21878dfa04fcbe99fbdd7`. Owner review of that commit =
  **REPAIR_REQUIRED (P0=0 / P1=1 / P2=1)**.

The owner accepted the core of the slice: `StudioLeaguePathsV1` binds `root` / `dir` / `db` /
`identity` / `replay_root` together behind private fields, `resolve(None)` keeps the old bare relative
layout, the completion session receives the whole bundle at open and privately captures the replay
root, and `complete_runtime_occurrence()` did **not** regain an archive-root parameter. The CLI
migration to a single `--project-root` (with `migrate`'s corpus `--root` keeping its own meaning) was
also accepted, as was the new cwd-independence gate for actually starting the command from an
unrelated working directory.

### P1: the public API still carried a second path authority

`paths.rs` claims `from_root` is the one composer, but the crate still *published* a second, equally
official way to answer "relative to what?":

```rust
// still public, still re-exported from the crate root
pub const DEFAULT_IDENTITY_MANIFEST_PATH: &str = "local-artifacts/studio-league/identity.json";
pub const STUDIO_LEAGUE_DIR: &str              = "local-artifacts/studio-league";
pub const STUDIO_LEAGUE_DB_NAME: &str          = "league.sqlite3";
pub const STUDIO_LEAGUE_IDENTITY_NAME: &str    = "identity.json";
pub const STUDIO_LEAGUE_REPLAY_DIR_NAME: &str  = "replays";
```

A future Host or launcher could therefore legally write
`use splendor_studio_league::DEFAULT_IDENTITY_MANIFEST_PATH;` and be back to a cwd-relative identity
path, while the database and archive came from `StudioLeaguePathsV1` — the exact drift this slice
exists to prevent reorganised one layer up. The owner's framing is the same lesson the completion
outlet already taught: **if the goal is that the next layer has one supported entry point, do not
simultaneously publish another convenient composer.**

### Fix (narrow, as prescribed)

- The four layout names moved into `paths.rs` as **private module constants**, next to the only code
  that uses them. They are gone from the crate root: `splendor_studio_league::STUDIO_LEAGUE_DIR` no
  longer exists. The layout is now defined in exactly one place.
- `DEFAULT_IDENTITY_MANIFEST_PATH` was **deleted**. It turned out to have **zero users anywhere in the
  repository** beyond its own re-export — dead surface that only invited hand-composition.
- The resulting supported way to locate a league is exactly one call:

```rust
let paths = StudioLeaguePathsV1::resolve(explicit_root);
paths.db();  paths.identity();  paths.replay_root();
```

The generic filesystem APIs are untouched and still public (`archive_replay`,
`read_archived_replay`, `open_league`, `ingest_match`, ...). As recorded for the previous slice, a
Rust crate is not a security sandbox; what is closed here is the **published Studio League location
surface**, not the crate.

### P2: one doc comment described the wrong mechanism

`completion.rs` said the archive root "is the protocol constant [`StudioLeaguePathsV1`]" —
`StudioLeaguePathsV1` is a *resolved value object*, not a constant, and the sentence contradicted the
paragraph immediately below it. It now reads:

```text
The archive root is likewise not a parameter: it is captured from the resolved
[`StudioLeaguePathsV1`] when the completion session is opened, and is never a
per-call choice.
```

(The other `protocol constant` usages in `ledger.rs` refer to the rating config, which genuinely is a
constant, and were left alone.)

### Close patch: the default-layout assertion now covers all three locations

The requested assertion was added to `the_default_resolution_is_the_bare_protocol_relative_layout`:

```rust
assert_eq!(
    paths.identity(),
    Path::new(STUDIO_LEAGUE_DIR).join(STUDIO_LEAGUE_IDENTITY_NAME)
);
```

This was a real gap rather than a formality: that test already pinned `dir()`, `db()` and
`replay_root()`, but **not** `identity()` — the one leaf that had the second public definition being
removed. `assert!(paths.identity().is_relative())` was added alongside it, so all three leaves are
now asserted to stay relative under the default.

### Static census

Run over all Rust source in `crates/`. The three full location literals now appear in exactly one
file:

```text
crates/splendor-studio-league/src/paths.rs:15-17   doc comment describing the OLD duplicated layout
crates/splendor-studio-league/src/paths.rs:42-49   the single layout definition (private consts)
```

Nothing else — neither production code nor tests — restates `local-artifacts/studio-league/league.sqlite3`,
`.../identity.json` or `.../replays` as a full path. One residual was worth tightening rather than
arguing about: the four `--help` texts spelled the protocol directory out as literal text. They are
not a composer, but they *were* a second copy of the layout that could silently go stale. They now
carry a `{league-dir}` placeholder substituted at print time from
`StudioLeaguePathsV1::resolve(None).dir()`, so the help text is rendered from the single source of
truth. Verified byte-identical: all four commands still print
`<dir>/local-artifacts/studio-league`, and no placeholder leaks into any output.

### Validation and evidence

- **Negative control, both routes (run, then deleted).** An integration test is an external crate, so
  a throwaway `tests/zz_surface_probe.rs` saw exactly the surface a future Host would see.
  - *Closed route 1 (crate root):* `use splendor_studio_league::{DEFAULT_IDENTITY_MANIFEST_PATH,
    STUDIO_LEAGUE_DB_NAME, STUDIO_LEAGUE_DIR, STUDIO_LEAGUE_IDENTITY_NAME,
    STUDIO_LEAGUE_REPLAY_DIR_NAME};` → `error[E0432]: unresolved imports ...` for all five names.
  - *Closed route 2 (module path):* `splendor_studio_league::identity_manifest::DEFAULT_IDENTITY_MANIFEST_PATH`
    → `error[E0432]: unresolved import` (the item no longer exists, so the path cannot resolve either).
  - *Positive control, same external-crate viewpoint:* `StudioLeaguePathsV1::resolve(None)` plus
    `db()` / `identity()` / `replay_root()` compiles and asserts the three historical relative paths
    exactly. So the one supported surface is sufficient to locate a league — it is not merely
    "everything else was removed". The probe file was deleted after the run.
- **Baselines unchanged**: `splendor-studio-league` **83/83**, whole `splendor-cli` **273 passed / 0
  failed** across 44 binaries. Nothing failed when the constants were privatised, which is itself
  evidence that no internal caller depended on the published names.
- Static: `git diff --check` exit 0; NUL 0; CRLF 0; `rustfmt --edition 2021` on the six touched files
  only, `git status --porcelain` showing exactly those six. Build warnings remain limited to the
  pre-existing `s2_census_command.rs` and `studio_league_command.rs` sites.
- The 42k historical migration was **not** re-run. No cloud status checks exist for this commit and
  none are claimed; every number above is local evidence.

### Result and decision

`IMPLEMENTED` / `VERIFIED` locally. The public surface now offers exactly one way to locate a Studio
League, and the layout is defined in one private place. `ACCEPTED` is **not** claimed; that is the
owner's verdict.

### Known limitations

- The four layout names still exist as constants — they are private to `paths` rather than deleted,
  because `from_root` needs them. Only their *publication* was removed, which is what the owner asked
  for.
- `from_root` remains public, so a library caller can still point a session at any project root. As
  recorded for the parent slice, that is the intended surface (choose the root once, at session open);
  what remains closed is choosing a root at completion time.
- The `{league-dir}` placeholder is substituted only by `render_usage`. A future caller that prints a
  usage constant directly, without rendering, would leak the placeholder into its output. Every
  current site renders, and the four commands were re-run and checked.
- `read_archived_replay` still has no production caller; invariant I4 is validated through the ledger
  row, not through a read surface.

### Next authorized gate

Owner review of this repair. On acceptance the project-root slice is expected to close, and the Host
API — the surface this slice was ordered *before* — becomes the next thing to authorize. Host API and
UI remain **not authorized** until then.

## Commit D — Host API Slice 1 (read-only) (2026-09-14)

- **Status**: `IMPLEMENTED` / `VERIFIED` locally as `59ffe9b1c826f6e1b430284f6260884b6ff06cbd`.
  Owner review found **REPAIR_REQUIRED (P0=0 / P1=1 / P2=2)**; see *Repair 1* below. The design and the
  structure were accepted, and the P1 was that a read must also respect the authority evidence the
  write paths already enforce.
- **Baseline**: `1ecb34365642ad534e6a20caa1d281eb8e530806`. Project-Root / Launcher Resolution was
  **ACCEPTED / CLOSED** there (P0=0 / P1=0 / P2=0). The owner accepted the recorded `{league-dir}`
  help-rendering limitation as *not* a problem (every current output path renders; a future caller
  printing a private usage constant directly is a future mistake, not a present seam).
- **Authorization**: the read-only Host API. UI is **still not authorized**.

The owner's contract: serve three product reads — leaderboard, match detail, replay document — from a
Host that resolves the project root **once**, reuses the existing ledger authority instead of
recomputing anything, reads replay bytes only through archive root + content address, and adds **no
write** authority (no run-match, no completion POST, no identity/alias mutation, no migrate/rebuild,
no delete, no WebSocket, no UI).

### Problem and evidence

Read at `1ecb343`:

1. **A Host already exists.** `splendor studio-host` (`run_studio_host` → `serve_studio_host` →
   `StudioHost` → `handle_host`, all in `crates/splendor-cli/src/human_play_command.rs`) is a
   hand-rolled HTTP/1.1 server over `std::net`, serving `/health`, `/agents`, `/catalog`, `/state`,
   `/games`, `/action`, `/archive`, `/reviewers`, `/recent-games`, `/replays/*`,
   `/experiment-replays*`, `/reviews`, `/reviews/*`. It has **no Studio League routes**.
2. **There is no web stack in the workspace at all.** No `axum`, `tokio`, `hyper`, `warp`, `actix`,
   `tiny_http`, `rouille`: `grep` over every `Cargo.toml` is empty. The repository deliberately
   hand-rolls HTTP rather than pulling in an async runtime.
3. **`rusqlite` is a test-only dependency of `splendor-cli`** (Cargo.toml, with a comment saying so).
   So the Host can neither name a `rusqlite::Connection` in a struct field nor hand-write SQL over the
   ledger — the second of which would make the Host a **second ledger authority**, the exact class of
   defect this project has spent several rounds closing.
4. The ledger already exposes the reads this slice needs: `leaderboard(conn) -> Vec<LeaderboardRow>`,
   `match_receipt(conn, match_id) -> Option<MatchReceiptV1>`, `read_archived_replay(archive_root, sha)`,
   plus `MatchStatus` / `ReplayStorage` / `ReplayVerification` value enums with `as_str()`.
5. `match_receipt` returns only `{match_id, rating_ineligible_reason, elo_events}` — **not** the seats,
   status, source identity, or replay binding the match-detail requirement asks for. The `matches` and
   `match_seats` tables hold all of it, but nothing reads it today.
6. `open_league` calls `initialise` (PRAGMA + DDL + meta version), i.e. it **writes**. Using it to
   serve reads would mean a "read-only" Host that mutates the database on every request, and one that
   silently creates an empty league when the database is missing.
7. There is **no HTTP test harness** in the repository: no test drives `studio-host` over the wire.

### Two design deviations, stated before implementation

**D1 — extend the existing `studio-host`; do not add a second Host.** The owner's contract describes
"a Host", and one already exists with the plumbing (request parsing, CORS headers, `Connection: close`
responses), the process model, and an unrelated read surface. A new binary would duplicate all of that
and split "the Host" in two. The league routes therefore join `handle_host`.

**D2 — add an opaque, read-only league session to `splendor-studio-league`.** This is the one
decision that adds **public surface**, so it is called out for review. The Host must serve ledger
reads, but (finding 3) `splendor-cli` cannot hold a connection and (finding 4/5) the match-detail
query does not exist yet. The options were:

| Option | Consequence |
| --- | --- |
| Promote `rusqlite` to a production dependency of `splendor-cli` | The Host gains raw SQL over the ledger — a **second ledger authority**, and precisely the shortcut class closed in Slice 3 Repair 2 |
| Open the league per request via `open_league` | Writes on every request (finding 6) and silently creates an empty league; still needs new query code for match detail |
| **An opaque read-only session owned by the ledger crate** | The ledger keeps sole ownership of its queries; the Host holds a value it cannot name, mutate, or bypass |

The third option is taken. It is deliberately **symmetric with `CompletionLeagueV1`**, the opaque
session the owner accepted in Slice 3 Repair 1: one constructor, private connection, no accessor.
The difference is that this one is read-only by construction — it opens the database with
`SQLITE_OPEN_READ_ONLY`, so it *cannot* write, and it **fails closed** when the database is absent
rather than creating an empty league.

New public surface (flagged for the owner: this is the whole of it):

```rust
pub struct StudioLeagueReaderV1;                 // opaque: private conn + paths
pub fn open_studio_league_reader(paths: &StudioLeaguePathsV1) -> Result<StudioLeagueReaderV1>;
pub struct MatchDetailV1;                        // + MatchSeatDetailV1 / ReplayBindingSummaryV1
impl StudioLeagueReaderV1 {
    pub fn leaderboard(&self) -> Result<Vec<LeaderboardRow>>;
    pub fn match_detail(&self, match_id: &str) -> Result<Option<MatchDetailV1>>;
    pub fn read_replay(&self, document_sha256: &str) -> Result<Vec<u8>>;
}
```

The backing ledger query is one new function, `match_detail(conn, match_id)`, reading the existing
`matches` / `match_seats` / `rating_events` tables. **No schema change, no new table, no write path,
and no new authority**: the reader answers only with facts the ledger already recorded, and
`MatchEloEventV1` is reused rather than redefined.

### Scope and non-goals

In scope: the read-only reader type + `match_detail` query in `splendor-studio-league`; `--project-root`
on `studio-host`; three GET routes; the four gates below.

Not authorized in this slice: run match, completion POST, identity mutation, alias editing,
migrate/rebuild, delete match, WebSocket, UI, any write endpoint, any new table, and any
recomputation of Elo / wins / provisional values in the Host.

### Endpoints

Naming follows the existing Host (bare paths; the owner explicitly allowed adapting the literal URLs):

```text
GET /league/leaderboard
GET /league/matches/{match_id}
GET /league/replays/{document_sha256}
```

The owner's `/api/studio/...` sketch was adapted rather than copied, because no existing Host route
uses an `/api` prefix and consistency with the neighbouring routes is worth more than the literal
spelling. The capability scope is exactly the owner's.

### Contracts and invariants

- **H1 — one root, resolved once.** `StudioHost` stores `StudioLeaguePathsV1` resolved from
  `--project-root` at startup. No handler joins `local-artifacts/...`, and none re-derives from cwd.
- **H2 — ledger truth only.** Leaderboard, seats, eligibility, and rating events come from the ledger
  through `leaderboard()` / `match_detail()`. The Host computes nothing and infers nothing: no win is
  guessed from a replay, no identity from a filename.
- **H3 — replay by content address only.** The replay route calls `read_archived_replay(paths.replay_root(), sha)`.
  A client supplies a SHA-256, never a path; `replay_path` is never taken from a request.
- **H4 — structurally read-only.** The reader opens `SQLITE_OPEN_READ_ONLY`; it cannot create a
  database, create a table, or write a row. A missing league fails closed at startup.
- **H5 — unknown input fails closed.** Unknown `match_id` → 404. Malformed or unknown SHA → 404.
  Neither returns placeholder data.

### Acceptance gates (frozen before implementation)

Four gates, as the owner specified — not a schema-test suite:

- **A — root authority.** Start `studio-host` from a working directory unrelated to the project root,
  with an explicit `--project-root`. `/league/leaderboard` must return the league in that root, and
  **nothing** may be created at `<cwd>/local-artifacts`.
- **B — leaderboard truth.** `/league/leaderboard` must agree with a direct `leaderboard()` call on the
  same database, field for field.
- **C — match detail truth.** An eligible match returns its real Elo events (two, for a two-seat rated
  match); an ineligible match returns its reason and **no fabricated events**.
- **D — replay content-addressing.** The correct SHA returns the exact archived `ReplayV1` bytes; an
  unknown SHA and a malformed SHA both fail closed; no request can name an arbitrary filesystem path.

### Resolved open questions

- *Which Host?* The existing `studio-host` (D1).
- *How does a Host without `rusqlite` read the ledger?* An opaque read-only session in the ledger
  crate (D2).
- *Should `--registry` / `--reviewer-registry` stop being required?* No. They are existing required
  arguments of a command this slice is not authorized to redefine; the gates supply minimal valid
  registries instead.
- *Fail-fast or lazy league open?* The root is resolved once at startup and the reader is opened once
  at startup. If the league database is missing, the Host still starts (existing non-league users are
  unaffected) and the league routes answer with a clear error rather than an empty league.
- *Status codes.* Existing routes answer 400 for every error. The new read routes need 404 for
  genuinely absent resources, so they get a small typed response path of their own; existing routes
  are left byte-identical.

### Final implementation

`crates/splendor-studio-league/src/ledger.rs` — new read: `match_detail(conn, match_id)` plus the typed
`MatchDetailV1`, `ReplayBindingSummaryV1`, `MatchSeatDetailV1`. It reads the existing `matches`,
`match_seats` and `rating_events` tables, reuses `MatchEloEventV1` rather than redefining it, and
rejects an unknown stored `status` / `replay_storage` / `replay_verification` with an error instead of
guessing. `archived` is a statement about the **ledger's** record (archive + verified + a recorded
document hash), not a filesystem probe — the replay route remains the authority on whether the object
can actually be read. `MatchEloEventV1` gained the `Deserialize` derive so the read types round-trip,
matching `MatchReceiptV1`; that is the only change to a pre-existing type in this slice.

`crates/splendor-studio-league/src/reader.rs` (new) — `StudioLeagueReaderV1` and
`open_studio_league_reader(paths)`. Private connection, no accessor, one constructor; opened with
`SQLITE_OPEN_READ_ONLY`, then the schema version is checked, so a missing file, a foreign SQLite
database, or a stale schema all fail closed at startup rather than being served as an empty league.

`crates/splendor-cli/src/human_play_command.rs` — `HostArgs.project_root`, the `--project-root` flag,
two new `StudioHost` fields, the one-time resolve-and-open in `serve_studio_host`, the three routes in
`handle_host`, the `LeagueRead` / `respond_league` response type, and the three `StudioHost` read
methods. `respond` gained explicit `404` and `503` reason phrases; its existing cases are unchanged.
The in-file unit test that builds a `StudioHost` now passes `league: None, league_error: None`.

Response shapes carry the repository's usual envelope:
`{"format":"effective-splendor-studio-league-leaderboard","version":1,"rows":[...]}` and
`{"format":"effective-splendor-studio-league-match","version":1,"match":{...}}`. The replay route
serves the archived document itself.

### Iteration log

- **The reviewer-registry default is cwd-relative.** The first smoke run started the host from an
  unrelated cwd without `--reviewer-registry`; its default (`benchmarks/studio-reviewers.registry.json`)
  resolved against that cwd and the host exited before binding. The gates therefore pass both registry
  paths as absolute. This is pre-existing behaviour, not introduced here, but it is the same class of
  cwd-drift the previous slice closed for league paths, and it is worth recording.
- **A missing league must not break the existing Host.** Opening the reader at startup could have made
  `studio-host` unusable for every current non-league caller. The failure is instead remembered and
  reported by the league routes only.
- **Gate B is deliberately insensitive to the root.** Under the root negative control it still passes,
  because it starts the host with cwd equal to the root. That is correct: gate B is about agreement
  with the ledger, and gate A is the gate that owns root authority. Both are needed.
- **`workspace_path` uses `CARGO_MANIFEST_DIR`,** not a walk up from `current_exe`: the first attempt
  popped one level too few and looked for `target/benchmarks/...`, which failed every host start.

### Validation and evidence

- `cargo test -p splendor-studio-league`: **83 passed / 0 failed** (unchanged).
- `cargo test -p splendor-cli`: **277 passed / 0 failed** across 45 test binaries (was 273 across 44;
  the new `league_host_api` binary contributes the four gates).
- **New gates** (`crates/splendor-cli/tests/league_host_api.rs`, 4 tests, ~2.3s): they build a real
  league by running the real producer twice (one rated pair, one self-match), start the real binary as
  a subprocess from a real unrelated cwd, and speak HTTP over `std::net` — there is no web stack in this
  repository and this slice did not add one.
  - **A** `the_league_comes_from_the_explicit_project_root_not_the_working_directory` — leaderboard is
    served from the explicit root, and `<cwd>/local-artifacts` does not exist afterwards.
  - **B** `the_leaderboard_agrees_with_the_ledger_itself` — every row matches a direct `leaderboard()`
    call on the same database across `participant_id`, `display_name`, `elo`, `rated_games`,
    `recorded_games`, W/T/L and `provisional`.
  - **C** `match_detail_reports_recorded_facts_and_never_fabricates_events` — the rated match reports
    `status`, `player_count`, source identity, two attributed seats and exactly two Elo events starting
    from the protocol initial 1500; the self-match reports `self_match` and **zero** events; an unknown
    id is 404.
  - **D** `replays_are_read_by_content_address_only` — the served body is byte-identical to the archived
    object on disk; a malformed address, an unknown address and a path-shaped request all 404.
- **Behavioural probe (manual, before the gates).** Real league, real matches: leaderboard 200 with the
  expected 1516 / 1500 / 1484 rows; match detail with both seats and two real events; replay body
  **byte-identical** to the archived file (28,730 bytes); `unknown match` / `not-a-sha` /
  `0000…0000` / `../../etc/passwd` all 404; `elsewhere/local-artifacts` never created.
- **Negative controls (run, then reverted).** Two independent injections into the Host:
  1. ignore `--project-root` and resolve the default instead → **gate A FAILED**;
  2. let the replay route serve whatever `read_replay` returns instead of failing closed →
     **gate D FAILED**.
  Gates B and C correctly stayed green under (1), because gate B runs with cwd equal to the root and
  gate C's subject is the detail payload. Both injections were reverted and the suite is green again.
- Static: `git diff --check` exit 0; NUL 0; CRLF 0; `rustfmt --edition 2021` on the touched files.
  Build warnings remain the pre-existing `s2_census_command.rs` and `studio_league_command.rs` sites.
  The 42k historical migration was not re-run. There are no cloud status checks; every number above is
  local evidence.

### Result and decision

`IMPLEMENTED` / `VERIFIED` locally. Three read-only endpoints answer from the existing ledger and the
existing archive, with the project root resolved once at startup, and the Host holds no way to write.
No new authority was created: the only new capability is a read-only session over data the ledger
already owned. `ACCEPTED` is **not** claimed.

### Known limitations

- The reader type and `MatchDetailV1` are **new public surface** in `splendor-studio-league`. It is
  read-only and it prevents a worse outcome (raw SQL in the Host), but it is public surface, and the
  owner should weigh it as such.
- `read_archived_replay` returns 404 for a malformed address as well as an unknown one. Both fail
  closed; the distinction is not surfaced.
- League routes are unauthenticated and the Host binds `127.0.0.1` only. That is the existing Host's
  posture and this slice does not change it.
- The league routes are served by the same process as the existing command/registry surface, so the
  process as a whole is not read-only — only the league reader is.
- `--registry` remains a required argument, so serving league reads needs a rating registry file even
  though the league reads do not use it.

### Next authorized gate

Owner review of this slice. Per the owner's stated ordering, if the read-only Host is accepted the next
step is the Host completion API / match orchestration, then the UI. **UI remains not authorized.**

## Commit D Slice 1 Repair 1 — reading respects the authority evidence (2026-09-14)

- **Status**: `IMPLEMENTED` / `VERIFIED` locally. Owner review of this repair found a remaining
  temporal seam — the check ran once at startup while the Host is long-running — and returned
  **REPAIR_REQUIRED (P0=0 / P1=1 / P2=1)**; see *Repair 2* below. The logical content of this repair
  was accepted as correct.
- **Baseline**: `59ffe9b1c826f6e1b430284f6260884b6ff06cbd`, owner verdict
  **REPAIR_REQUIRED (P0=0 / P1=1 / P2=2)**.
- **Prescribed scope**: (1) stored rating config must equal this build's protocol config, pure read;
  (2) strict identity manifest load plus stored-hash equality; (3) two fail-closed gates;
  (4) `match_detail(conn, …)` becomes crate-internal; (5) corrupt/unreadable replay becomes 503 if
  small. Explicitly not in scope: schema changes, new endpoints, write APIs, UI.

The verdict accepted the design, the reuse of `studio-host`, the single root resolution at startup, the
physical read-only-ness of the session, and the content-addressed replay route. What it rejected was
narrower and correct: **the reader validated the schema version and nothing else.**

### P1 — a stronger integrity contract than the schema was not checked

`open_studio_league_reader()` did `open READ_ONLY` → `schema_version()` → compare → serve. But two
higher-level contracts were already frozen for this database, and both were enforced on every write
path while being ignored on the read path:

1. **The rating protocol identity.** `ensure_rating_config` fails closed when the persisted
   `studio_rating_config` evidence disagrees with `protocol_rating_config()`: a derived database
   written by another Studio Elo protocol must be rebuilt. A reader that skipped this could serve one
   protocol's Elo as if the current build stood behind it, while `complete-match` refused the very
   same database.
2. **The durable identity authority.** `sync_identity_manifest` requires, on a non-empty ledger, that
   the recorded manifest hash equals the hash of the manifest on disk, and fails closed when the
   evidence is missing. `identity.json` is *authored* state and the SQLite index is *derived*; a user
   may legally rename themselves or add an alias before any rebuild. The reader did not read
   `paths.identity()` at all, so it would serve superseded participants and aliases as current fact.

That is the boundary this project has held throughout: **SQLite is derived state; the durable manifest
is the authored identity authority.** A read surface that does not check it is not a product entry
point to ledger truth, it is a view of a stale index.

### Fix

Both checks are pure reads, with zero mutation and no new dependency on the write path:

- `stored_rating_config(&conn)` → `ok_or_else` when missing, then `!= protocol_rating_config()` fails
  with `StudioLeagueError::RatingConfig`, reusing the same "the index is derived, so rebuild it"
  message the write path uses.
- `IdentityManifestV1::load(paths.identity())` — deliberately **not** `load_or_recover`, which can
  heal the primary and therefore writes, and therefore has no place in a read-only session. Missing
  manifest, missing stored hash, and mismatched hash all fail closed.

Both failures reach the client through the `league_error → 503` path that already existed, so the HTTP
architecture did not change: a league that cannot be trusted is unavailable, not silently empty.

### P2-1 — the backing primitive was also external API

`match_detail(conn, …)` was newly added and re-exported from the crate root. It grants no write
authority and the generic `leaderboard(&Connection)` family was already public, so it was not a
blocker — but it contradicted the stated point of this slice, which is that a consumer does not need a
raw connection *or* a query seam. It is now `pub(crate)` and removed from the re-export. The DTOs stay
public because they are the read session's return type.

### P2-2 — corruption was reported as absence

The replay route mapped every `read_replay` error to 404. But that function fails both when there is no
object and when there is one it cannot serve (unreadable, or bytes that no longer hash to their
address). Telling a client "this replay does not exist" when the archive has lost it is not honest,
least of all in a slice that just introduced `Unavailable → 503` for the league itself. A present
object that fails to read is now 503; only an address that was never archived is 404.

This was done without a new error taxonomy, as prescribed: crate-internal
`content_address_path` / `archived_replay_present` in `replay_archive.rs`, and one public predicate
`StudioLeagueReaderV1::replay_present()` that says whether the archive holds an object at an address
(existence only — a later failed read of a present object is still server-side corruption).

### Validation and evidence

- `cargo test -p splendor-studio-league`: **83 passed / 0 failed** (unchanged: 34 lib + 1 + 7 + 3 + 29
  + 5 + 4).
- `cargo test -p splendor-cli`: **280 passed / 0 failed** across 45 test binaries (was 277 across 45;
  the three new gates).
- **New gates** (`crates/splendor-cli/tests/league_host_api.rs`, now 7 tests, ~3.3–7.4 s). Each copies
  the fixture league first, because it has to damage evidence that the other gates share.
  - `a_league_whose_durable_identity_moved_on_is_not_served` — rename the local human through the
    public manifest API (the hash is canonical over the whole document) → leaderboard **503**, and
    `/health` still **200**.
  - `a_league_built_by_another_rating_protocol_is_not_served` — rewrite the persisted rating config
    with a different `k_factor` *keeping the schema version intact*, so a schema check provably cannot
    see the difference → **503**, `/health` still **200**.
  - `a_corrupt_archive_object_is_a_server_fault_not_a_missing_replay` — flip one byte of a copied
    archived object (same length, still readable, no longer its content address) → **503**; an address
    that was never archived stays **404**.
- **Negative controls (run, then reverted).**
  1. Make both authority gates no-ops → the durable-identity gate and the rating-protocol gate
     **FAILED**, while the corrupt-object gate and all four original gates stayed green.
  2. Restore `Err(error) => NotFound` in the replay route → the corrupt-object gate **FAILED**,
     everything else green.
- **Surface probe (throwaway, deleted).** From an external crate:
  `use splendor_studio_league::match_detail;` → **`error[E0432]`**: no `match_detail` in the root.
  Positive control from the same viewpoint: `StudioLeagueReaderV1` + `MatchDetailV1` /
  `MatchSeatDetailV1` / `ReplayBindingSummaryV1` compile and the session method is callable.
- Static: `git diff --check` exit 0; NUL 0; `rustfmt --edition 2021` on the six touched files; diff is
  `6 files changed, 284 insertions(+), 8 deletions(-)` with no whole-file churn. Build warnings remain
  the pre-existing `s2_census_command.rs` and `studio_league_command.rs` sites. The 42k historical
  migration was not re-run. There are no cloud status checks; every number here is local evidence.

**Correction to an earlier hygiene claim.** Previous rounds recorded `CRLF 0` on touched files as
evidence. That number was an artifact of this work's own editing (whole-file rewrites emitted LF), not
a repository invariant: `core.autocrlf=true`, the repo's working tree is normally CRLF, and the index
stores LF either way. The check that means something is `git diff --check` plus a diff with no
whole-file churn; both are recorded above.

### Result and decision

`IMPLEMENTED` / `VERIFIED` locally. The read session now enforces, on the read side, the same two
integrity contracts the write side already enforces — with no schema change, no new endpoint, no write
authority, and no new dependency, so a read can no longer present derived state that the ledger would
refuse to accept. `ACCEPTED` is not claimed: owner review is the gate.

### Known limitations

- `StudioLeagueReaderV1` remains **new public surface** (now plus `replay_present`). The reviewer
  accepted the abstraction and explicitly asked that the P1 not be fixed by retreating from it toward
  raw SQL in the Host.
- A league with **no** integrity evidence at all (for instance an empty database created by
  `open_league` and never completed into) is also refused — 503, not an empty leaderboard. That is the
  strict reading of "fail closed on missing evidence" and it is deliberate.
- The distinction between a malformed address and an unknown one is still not surfaced; both are 404,
  which the owner accepted.
- League routes remain unauthenticated, bound to `127.0.0.1`; `--registry` remains required even though
  league reads do not use it; and the process as a whole is still not read-only.

### Next authorized gate

Owner review of this repair. Per the owner's stated ordering, acceptance closes **Host API Slice 1**,
after which the next authorized step is the **Host Completion API / match orchestration**, then the UI.
**UI remains not authorized.**

## Commit D Slice 1 Repair 2 — authority evidence is revalidated on every read (2026-09-14)

- **Status**: `IMPLEMENTED` / `VERIFIED` locally. The temporal seam this repair addressed was confirmed
  closed, but the owner found a remaining consequence of how the replay route reached its status code
  and returned **REPAIR_REQUIRED (P0=0 / P1=1 / P2=1)**; see *Repair 3* below.
- **Baseline**: `6927500bf488b9b76b26acee75149227188df40a`, owner verdict
  **REPAIR_REQUIRED (P0=0 / P1=1 / P2=1)**.
- **Prescribed scope**: (1) move the rating + identity integrity comparison into a private
  `StudioLeagueReaderV1` helper; (2) every public read revalidates before it answers; (3) one new gate
  for "host already running → manifest edited → next request 503"; (4) no new endpoint, no watcher, no
  write API, no UI; (5) the `is_file()` classification extreme stays P2.

Repair 1 was accepted as correct — schema, stored rating config versus protocol config, and manifest
hash versus stored hash, all through the non-healing `IdentityManifestV1::load()`. The shortfall was
temporal, not logical.

### P1 — the check ran once, at boot, and this Host does not restart

The opener validated the evidences once, then `StudioHost` entered its long-lived accept loop holding
just `conn` and `replay_root`. No read re-checked anything, so this sequence was still possible:

```text
host starts            → reader validates the identity hash : PASS
user legally edits identity.json (rename, alias change)
host does not restart
GET /league/leaderboard → 200, with the superseded display name and attribution
```

That is the same state Repair 1's gate was written to forbid, reached by a path the Repair 1 gate
cannot see: it edits the manifest and *then* starts a host. The two are not equivalent, because the
lifetime differs. For a one-shot completion session, "validated when the session opened" is
whole-life. `studio-host` runs indefinitely, so for it the correct contract is not *this league was
valid when it was opened* but *this answer is still backed by authority evidence*.

### Fix — one helper, run by every read

`validate_authority_evidence(&self)` is now the only implementation of the comparison, and reads call
it before querying:

```rust
pub fn leaderboard(&self) -> Result<Vec<LeaderboardRow>> {
    self.validate_authority_evidence()?;
    leaderboard(&self.conn)
}
```

`match_detail` and `read_replay` do the same. The reader therefore stores `identity_path` alongside
`conn` and `replay_root`, and the **opener calls the very same helper** before returning — so opening
can never be laxer than reading, and there is exactly one copy of the comparison to drift out of sync.
The failure still travels the existing `league_error → 503` route; the Host knows nothing about
authority rules. All of it remains pure reading: two `league_meta` lookups and one strict manifest
load per read, with no mutation and no watcher.

### Why `replay_present()` deliberately does not revalidate

The owner suggested `read_replay()` join the contract, and it does. `replay_present()` is left out on
purpose: it is a `bool`, so it cannot report "unavailable", and having a drifted league make it return
`false` would turn authority drift into a 404 — exactly the dishonest classification Repair 1 removed
for corruption. It also serves no league state; it only answers what the archive holds. A drifted
league still cannot hand back any bytes, because `read_replay()` revalidates first and fails, and a
present object then classifies as 503 through the existing path.

**Correction (Repair 3).** The reasoning in that section is wrong and the deviation did not have the
effect claimed. Leaving `replay_present()` without revalidation does **not** stop authority drift from
becoming a 404: `read_replay()` fails on the authority evidence *first*, and the predicate is consulted
afterwards, so for an address that was never archived it answers `false` and the client is told "this
replay does not exist" while the league is in fact untrustworthy. Repair 3 removes the predicate from the
public API and moves the absence decision inside `read_replay()`, where the authority check owns the
result. See *Repair 3* below.

### P2 (deferred, as prescribed) — `replay_present` classification is not yet a full split

`replay_present()` is implemented as `target.is_file()`. That covers the gate's case (a regular file
exists and the bytes no longer match), but a content-address path occupied by a directory, or a
metadata/traversal failure, would report `false` and could fall back to 404. It still fails closed and
never serves a wrong replay; only the HTTP classification is imprecise. Deferred by the owner: the
eventual shape is a three-state archive answer (`Absent` / `Present` / `InspectionFailed`) or a typed
read error, and neither belongs in this repair.

### Owner decision recorded — a league with no integrity evidence stays refused

Repair 1 refused a database that has a schema but no `studio_rating_config`, no
`identity_manifest_hash` and no durable `identity.json`, answering 503 instead of
`200 {"rows": []}`. The owner accepted this as a **deliberate strictness, not a defect**: such a
database is "a SQLite shell whose product authority was never established", and serving it would make
the two states indistinguishable to a user:

```text
properly initialised, genuinely zero matches
versus
a shell was created and no authority evidence was ever written
```

Formal completion/migration paths write that evidence, so if an empty product league is ever wanted,
it needs an explicit initialisation flow rather than a reader guessing that missing evidence means
"probably just empty". Retained.

### Validation and evidence

- `cargo test -p splendor-studio-league`: **83 passed / 0 failed** (unchanged).
- `cargo test -p splendor-cli`: **281 passed / 0 failed** across 45 test binaries (was 280; the one new
  gate).
- **New gate** `a_league_that_goes_stale_while_the_host_is_running_stops_being_served`
  (`crates/splendor-cli/tests/league_host_api.rs`, now 8 tests, ~1.5–2.2 s): start the host on a copied
  league, confirm `/league/leaderboard` is 200, rename the local human through the public manifest API
  **while that process keeps running**, then on the same process and port assert 503 for the
  leaderboard, for match detail and for the replay, with `/health` still 200. The three routes are
  asserted in one gate because they are one contract: a stale session stops answering league reads.
- **Negative control (decisive).** Remove only the three per-read calls, leaving the startup check
  intact → `a_league_that_goes_stale_while_the_host_is_running_stops_being_served` **FAILED**, while
  `a_league_whose_durable_identity_moved_on_is_not_served` — the Repair 1 gate that edits the manifest
  and *then* starts a host — **stayed green**. That is the evidence that the two gates are not
  redundant and that the old one structurally cannot cover this seam. Reverted; suite green again.
- Static: `git diff --check` exit 0; NUL 0; `rustfmt --edition 2021` on the two touched files; diff is
  `2 files changed, 140 insertions(+), 51 deletions(-)` with no whole-file churn. Build warnings remain
  the pre-existing `s2_census_command.rs` / `studio_league_command.rs` sites. The 42k historical
  migration was not re-run. No cloud status checks: every number is local evidence.

### Result and decision

`IMPLEMENTED` / `VERIFIED` locally. `StudioLeagueReaderV1` now carries the session contract directly —
*while authority evidence has moved, this session serves no league reads* — with one private
implementation shared by open and by every read, no new endpoint, no watcher, and no new authority.
`ACCEPTED` is not claimed; owner review is the gate.

### Known limitations

- Revalidation costs two `league_meta` reads, one manifest load and one JSON parse per request. That is
  nothing against an HTTP round trip, and it avoids a watcher, but it is not free and it is not cached:
  a cache would have to be invalidated, and an invalidation bug is the exact failure mode this repair
  exists to remove.
- `replay_present()`'s classification extreme remains P2, deferred above.
- Unchanged from Repair 1: the reader is still new public surface; league routes are unauthenticated and
  bound to `127.0.0.1`; `--registry` is still required though league reads do not use it; the process as
  a whole is not read-only.

### Next authorized gate

Owner review of this repair. On acceptance **Host API Slice 1** closes, and per the owner's ordering the
next authorized step is the **Host Completion API / match orchestration**, then the UI. **UI remains not
authorized.**

## Commit D Slice 1 Repair 3 — one owner for absence and refusal (2026-09-14)

- **Status**: `IMPLEMENTED` / `VERIFIED` locally; awaiting owner review. `ACCEPTED` is not claimed.
- **Baseline**: `fc36e6652bd3db6b33257e7598c1b22cc13d372b`, owner verdict
  **REPAIR_REQUIRED (P0=0 / P1=1 / P2=1, the original deferred one)**.
- **Scope**: the replay-result ownership only. No endpoint, no write Host, no UI, no new error
  taxonomy.

Repair 2's substance was accepted: `validate_authority_evidence()` is the single implementation, the
opener calls it, and all three reads call it, so a manifest edit during the host's life is now caught.
The new gate was accepted as genuinely different from the earlier one. What remained was a specific
consequence of how the replay route reached its status code.

### P1 — the classification predicate ran *after* the authority gate

Repair 2 kept `read_replay()` revalidating first, and left the absence/refusal decision to the Host:

```rust
Err(error) => if reader.replay_present(sha) { 503 } else { 404 }
```

So for a stale league and an address that was **never archived**:

```text
read_replay()          -> authority validation fails
replay_present(unknown) -> false
HTTP                    -> 404
```

The server knows the League cannot be trusted and answers "this replay does not exist". That is
precisely the authority-drift-becomes-404 outcome Repair 2 claimed to have avoided, and the claim was
wrong: omitting revalidation from the predicate does not prevent it, because the predicate's `false`
is consulted *after* the authority failure has already happened. Repair 2's gate missed it because it
requested a replay that **exists**, so `replay_present()` returned `true` and the 503 came out right
for the wrong reason.

### Fix — `read_replay` owns the distinction

```rust
pub fn read_replay(&self, document_sha256: &str) -> Result<Option<Vec<u8>>> {
    self.validate_authority_evidence()?;
    if !archived_replay_present(&self.replay_root, document_sha256) {
        return Ok(None);
    }
    read_archived_replay(&self.replay_root, document_sha256).map(Some)
}
```

and the Host collapses to three arms: `Ok(Some)` → 200, `Ok(None)` → 404, `Err` → 503. Ordering is
now structural rather than a convention the caller must respect, giving the four cases the owner
specified:

```text
authority invalid                          -> Err            -> 503
authority valid + malformed/unknown SHA    -> Ok(None)       -> 404
authority valid + present valid object     -> Ok(Some)       -> 200
authority valid + present unservable object-> Err            -> 503
```

The public `replay_present()` is **deleted**. It was grown in Repair 1 to let the Host classify a read
error, and once the reader owns that decision it has no reason to remain a long-term part of the API:
this repair shrinks the public surface rather than growing it. `archived_replay_present` stays
crate-internal.

### Gate and its negative control

The existing stale-league gate gained exactly one case, the one that matters:

```text
host running -> manifest drift -> GET existing replay = 503
                               -> GET valid SHA that was never archived = 503
```

Run **before** the fix on `fc36e66`, that added case failed with

```text
got 404: {"error":"invalid studio league document: identity manifest hash `c30c68…` disagrees with
stored database evidence `489333…`; rebuild the derived database to apply identity or alias changes"}
```

— the status code saying "not found" while the body carries the authority failure. After the fix the
same case is 503 and the whole gate passes. The reverse-order probe is also confirmed: the
never-archived address is still 404 on a *healthy* league (`replays_are_read_by_content_address_only`
and the corrupt-object gate both still pass), so the fix moved only the stale case.

### Surface probe (throwaway, deleted)

From an external crate: `reader.replay_present("x")` → **`error[E0599]`**: no method named
`replay_present` found for reference `&StudioLeagueReaderV1` — the temporary predicate is gone from the
public API. Positive control from the same viewpoint: `let got: Result<Option<Vec<u8>>, StudioLeagueError>
= r.read_replay("x");` compiles, pinning the new contract at the type level.

### Validation and evidence

- `cargo test -p splendor-studio-league`: **83 passed / 0 failed** (unchanged).
- `cargo test -p splendor-cli`: **281 passed / 0 failed** across 45 test binaries (unchanged count: this
  repair extends an existing gate rather than adding one).
- Static: `git diff --check` exit 0; NUL 0; `rustfmt --edition 2021` on the three touched files; diff is
  `3 files changed, 27 insertions(+), 33 deletions(-)` — net negative, no whole-file churn. Build
  warnings remain the pre-existing `s2_census_command.rs` / `studio_league_command.rs` sites. The 42k
  historical migration was not re-run. No cloud status checks: every number is local evidence.

### Result and decision

`IMPLEMENTED` / `VERIFIED` locally. A stale session can no longer be reported as an absent resource,
because the authority check owns the result and the absence decision happens inside the same call, in a
fixed order. No new endpoint, no write authority, no new error taxonomy, and one fewer public method
than before. `ACCEPTED` is not claimed; owner review is the gate.

### Known limitations

- `archived_replay_present` still decides existence with `Path::is_file()`, so a content-address path
  occupied by a directory, or a metadata-inspection failure, could still be classified as absence. This
  is the same **P2 (deferred)** as before: it fails closed and never serves a wrong replay; only the
  HTTP classification is imprecise. The eventual shape remains a three-state archive answer
  (`Absent` / `Present` / `InspectionFailed`) or a typed read error, deliberately not in this repair.
- The 404 body for an absent object is now the reader's own message
  (`no archived replay at content address \`…\``) rather than the archive-layer path detail. The Host
  no longer echoes an internal path for a client-caused absence, which is an improvement, but it is a
  user-visible wording change.
- `read_replay` still returns `Ok(None)` for a **malformed** address as well as an unknown one; the two
  remain indistinguishable to a client, as the owner accepted in Repair 1.
- Unchanged: the reader is new public surface (one method smaller now); league routes are unauthenticated
  and bound to `127.0.0.1`; `--registry` is still required though league reads do not use it; the
  process as a whole is not read-only.

### Next authorized gate

Owner review of this repair. On acceptance the owner expects **Host API Slice 1** to close, after which
the next authorized step is the **Host Completion API / match orchestration**, then the UI. **UI remains
not authorized.**

## Commit E — Host Completion API / match orchestration, Slice 1 (2026-09-14)

- **Status**: **`AUTHORIZED`** by the owner, 2026-09-14. The design below is frozen **before**
  implementation; nothing in this section is implemented or verified yet. It will be filled in as the
  round proceeds.
- **Baseline**: `73090cee856701a9d25504150c7bd89493a0193a`. **Host API Slice 1 is ACCEPTED / CLOSED**
  there (P0=0 / P1=0 / P2=1 deferred — `archived_replay_present`'s `is_file()` classification extreme,
  to be closed later as one archive three-state, not by another predicate).
- **Authorization**: the Host Completion API / match orchestration. **UI remains not authorized.**

The owner's contract for this slice: the Host becomes an **upper orchestration adapter** over the
already-closed producer and completion authority — it does not reimplement `complete-match`:

```text
POST /league/matches
        ↓
real Arena producer
        ↓
durable report + replay + config snapshot + RuntimeOccurrenceV1
        ↓
complete_runtime_occurrence()
        ↓
existing archive + ledger + Elo authority
```

with: (1) no hand-written ledger SQL, no direct archive, no Elo arithmetic in the Host; (2) a match
that completed while Studio completion failed must say exactly that, never present the whole match as
failed; (3) all four evidence documents durable *before* completion is attempted; (4) retry consumes
the original four documents and never re-runs the match; (5) occurrence id and `completed_at` are
minted once by the producer, never reconstructed; (6) one single-match real Arena path only — no worker
queue, watcher, scheduler or batch; (7) no identity editing, migration, deletion or UI.

### Problem and evidence

Read at `73090ce`:

1. **The producer and completion authority already exist and are closed** — as CLI commands.
   `crates/splendor-cli/src/completion_wiring_command.rs` (911 lines) holds
   `run_studio_league_complete_match` (producer + completion) and `run_studio_league_complete`
   (completion-only retry). The chain is: read the config **once** → `parse_config_bytes` →
   `ArenaRunner::run` → aborted? persist the report and stop → `persist_completed_evidence`
   (config snapshot → replay + report via `commit_completed_with` → envelope last, rolling back
   everything already written on failure) → `complete_persisted` → `open_completion_league(paths, now)`
   + `complete_runtime_occurrence`. Exit codes: `0` completed, `3` completed-but-completion-failed,
   `2` arena aborted, `1` config/IO/internal, `64` usage.
2. **That authority is callable in-process, but it is not yet a callable unit.** It is fused to CLI
   arguments (`CompleteArgs` carries the four output paths plus `json_out`), to exit codes, and to
   `println!`. There is no function the Host can call that returns a *typed outcome*.
3. **`StudioHost` holds the reader and the registry but not `StudioLeaguePathsV1`.** The completion
   outlet needs `&StudioLeaguePathsV1`, and the reader keeps `replay_root`/`identity_path` private on
   purpose, so the write route cannot borrow a location from it: the resolved bundle has to be stored
   alongside the reader, exactly as it is resolved once at startup today.
4. **The Host already resolves agent ids to spawn commands and never accepts a program.** The rating
   registry carries `RatedAgentV1.command: AgentCommand` (a ready arena spawn command), `StudioHost`
   already holds `registry: RatingRegistryV1`, and the existing `POST /games` takes an `agent_id` which
   is validated against the registry and resolved to a command from it. **The product surface already
   never lets a client name an executable.**
5. **`ArenaConfig` is strict** (`deny_unknown_fields`, requires `game_id` / `seed` /
   `handshake_timeout_ms` / `move_timeout_ms` / `shutdown_grace_ms` / 2–4 `agents`), and
   `parse_config_bytes` is `pub(crate)` in this same crate, bounded by `MAX_ARENA_CONFIG_BYTES` (1 MiB).
6. **The Host's HTTP layer is minimal.** `HttpRequest { method, path, body: Vec<u8> }`; `read_request`
   honours `Content-Length` only and **caps the body at 64 KiB** (no chunked encoding); the league
   routes use `respond_league` (200/404/503) while pre-existing routes use `respond_result`
   (Ok → 200 / Err → 400).
7. **The accept loop is serial**: `for connection in listener.incoming() { handle_host(stream, &mut host) }`.
   One request is handled at a time, so a match-running POST blocks every other request until it
   returns.
8. **`HostArgs` has no handshake or shutdown-grace timeout** — only `--move-timeout-ms`.

### Initial design

**Route.** One write entry, `POST /league/matches`, additive; every existing route stays byte-identical.

**Request.** `deny_unknown_fields`, so an unexpected key is a 400 rather than a silently ignored field:

```json
{ "occurrence_id": "occ-2026-09-14-a", "game_id": "studio-host-1", "seed": 9200001,
  "seats": ["heuristic-v1", "s3-rollout"] }
```

**The Host builds the `ArenaConfig` itself** from its own registry: `seats` are registry **agent ids**,
resolved to `AgentCommand`s exactly as `POST /games` already does, and the timeouts come from
`HostArgs`. The client cannot supply `program`, `args`, or the timeouts. The built config is serialized
once, and **those bytes are the bytes that are parsed, run, and persisted** — the CLI's "read once"
invariant becomes "derive once", and `config_sha256` still attests exactly the configuration the runner
consumed.

**Evidence location.** A new accessor on `StudioLeaguePathsV1` derives
`<root>/local-artifacts/studio-league/occurrences/<occurrence_id>/` holding `config.json`, `replay.json`,
`report.json` and `occurrence.json`. Keeping this in `paths.rs` preserves the single-composer rule; the
`occurrence_id` is validated as **one safe path component** before any side effect.

**Retry through the same route.** Re-POSTing the same body: if a complete envelope already exists for
that occurrence id, the match is **not** re-run and the request goes straight to completion; if the
presented config bytes disagree with the envelope's recorded `config_sha256`, the request is refused
without running anything. That satisfies "retry must consume the original four documents" while keeping
exactly one write entry.

**The orchestration core is extracted, not duplicated.** The chain in `completion_wiring_command.rs`
becomes a shared function returning a typed outcome, and both callers become adapters: the CLI maps the
outcome to its frozen exit codes, the Host maps it to HTTP. The core keeps calling
`complete_runtime_occurrence` through `open_completion_league` — **no new authority is created.**

**Status codes** (the completed / completion-failed distinction is the point):

```text
200  match completed, completion ok            body carries inserted | already_present
409  match aborted                             a settled, non-completed occurrence; nothing booked
503  match completed, Studio completion failed evidence intact; the request is retryable
400  bad request                               bad JSON, unsafe occurrence id, unknown agent id, bad config
500  internal failure                          runner/IO error
```

### Scope and non-goals

**In scope**: the single `POST /league/matches` route; the extracted shared orchestration core; the
occurrence evidence location; a `paths` bundle on `StudioHost`; three gates.

**Explicitly out of scope**: worker queue, watcher, scheduler, batch orchestration; identity or alias
editing; migration; match deletion; a separate completion-only retry route; any change to the read API;
authentication; and the UI.

### Contracts and invariants

- **E1 — No new authority.** The Host never writes ledger SQL, never archives directly, never computes
  Elo. It calls the completion outlet, exactly as the CLI does.
- **E2 — The client names agents, never executables.** `seats` are registry agent ids. A request can
  never introduce a `program` or `argv`. Without this, an unauthenticated POST on a 127.0.0.1-bound
  server would be a local arbitrary-binary-execution surface, which the existing product surface
  deliberately avoids.
- **E3 — The occurrence id is one safe path component.** It is validated before any side effect, because
  it becomes a directory name; anything else is a 400 with nothing written.
- **E4 — Evidence before completion.** All four documents are durable before completion is attempted, so
  a completion failure always leaves a retryable, complete evidence set.
- **E5 — Two facts are reported separately.** A match that completed while completion failed is reported
  as exactly that; it is never presented as a whole-match failure, and never as a success.
- **E6 — Retry never re-runs the match.** A retry consumes the persisted four documents. The gate proves
  it by bytes, not by timing.
- **E7 — Minted once.** `occurrence_id` (from the caller, as in the CLI) and `completed_at` (minted by
  the producer) are never reconstructed on retry; the persisted envelope is authoritative.
- **E8 — Additive.** Existing routes stay byte-identical, and the CLI's exit codes and behaviour are
  unchanged — the five existing wiring gates are the guard.

### Decisions I want confirmed before I write code

These are the contract-level choices in this slice. Each has a default I believe is right; flagging them
because they are the kind of seam that has needed repair in this slice family.

- **D1 — agent ids, not programs** (E2). Chosen because the alternative would add a remote
  code-execution surface to an unauthenticated server; also consistent with `POST /games`. Consequence:
  a match can only use agents already in `--registry`.
- **D2 — evidence under `occurrences/<id>/`, id strictly validated.** Alternative would be a new CLI
  flag or client-supplied paths; both would let a caller choose a filesystem location, which is the class
  the project-root slice closed. Consequence: one new layout constant and one accessor in `paths.rs`.
- **D3 — status codes as tabulated above**, in particular **409 for an aborted match** (a real, settled
  fact, not a client error) and **503 for completed-but-completion-failed** (mirroring the read API's
  "league unavailable"). Alternative: always 200 with the facts in the body, or 500 for both failures.
- **D4 — retry is a re-POST of the same body**, with "a complete envelope already exists" as the
  completion-only trigger. The alternative is a second `POST /league/occurrences/{id}/complete` route,
  which contradicts "one write entry".
- **D5 — extracting the shared core, touching the frozen CLI file.** `completion_wiring_command.rs` is
  currently frozen by five gates; the extraction keeps its observable behaviour identical. If you would
  rather the Host call the CLI's internals without refactoring, say so — I would not recommend it,
  because that path leads to two implementations of the publish order.
- **D6 — handshake/shutdown timeouts for the Host.** `HostArgs` has only `--move-timeout-ms`. Default is
  to add two Host options mirroring the arena's own defaults rather than inventing new numbers; the
  client cannot set them either way.

### Acceptance gates (frozen before implementation)

Three gates, as specified, each driving the real binary over a real socket with the real producer:

- **G1 — a normal POST is registered.** `POST /league/matches` returns 200; the match then appears in
  `GET /league/leaderboard` and in `GET /league/matches/{match_id}`, with exactly two rating events and
  the replay readable at its content address from the write response's `document_sha256`.
- **G2 — completion can fail while the match succeeded.** Completion is forced to fail; the response says
  match completed / completion failed and is not a whole-match failure; all four evidence documents
  exist and are byte-identical after the failure; a retry then succeeds **without re-running the match**
  (proved by the four documents still hashing to the same bytes).
- **G3 — re-triggering the same occurrence books nothing twice.** A third POST of the same body reports
  `already_present`, adds no rating events, and leaves the ledger's match and event counts unchanged.

### Implementation plan

1. Freeze this design (this section) and mark the round in progress in `handoff.md`.
2. Refactor: extract the orchestration core out of `completion_wiring_command.rs` into a shared function
   with a typed outcome; make the CLI an adapter that maps the outcome to its existing exit codes. Run
   the five existing wiring gates to prove the CLI contract is unchanged.
3. `paths.rs`: add the occurrence evidence directory accessor plus the id-validation rule, with unit
   tests next to the existing three.
4. `StudioHost`: store the resolved `StudioLeaguePathsV1`; add the route, request/response types, the
   registry-seat resolution, and the status mapping.
5. Write G1–G3, including the negative controls (below), then the full baselines.
6. Record validation, evidence and limitations in this document; update `handoff.md`; commit and push.

**Negative controls to run and revert** (each gate must be shown to be sensitive to the fix it guards):
ignoring the occurrence-id validation must fail the "unsafe id" case with no side effect; treating a
completion failure as a whole-match failure must fail G2; re-running the match on retry must fail G2's
byte-identity assertion; and skipping the "envelope already exists" check must make G3 report
`inserted` instead of `already_present`.

## Commit E Slice 1 — implementation and validation (2026-09-15)

Status: **IMPLEMENTED / VERIFIED (local evidence only; no cloud status checks exist in
this repository)**. Baseline commit `a6a4298` (design-only freeze). This section records
what was built, the three owner corrections, the deviations, and the evidence.

### Owner corrections applied

- **D3 (modified):** a settled **aborted** match is `200`, not `409`. The frozen mapping is
  `200` completed+completion ok / `200` aborted / `503` completed+completion failed / `400`
  malformed, unsafe id, unknown agent, invalid config / `409` occurrence slot neither empty
  nor complete / `500` producer, runner or I/O failure before a settled fact.
- **D4 (modified, and this is the branch that matters):** the retry path checks **persisted
  evidence first**. The order in `StudioHost::run_league_match` is now: parse the body →
  validate the occurrence id and derive the slot → classify the slot → **if complete**,
  read the four documents, verify them against the envelope's own hashes, and complete (the
  registry is never consulted, no configuration is rebuilt, the runner is never called) →
  **if settled without completion**, report the recorded fact → **if ambiguous**, `409` →
  only then resolve seats, build the configuration, run the Arena, publish and complete. The
  earlier "rebuild the config and compare its hash on retry" design is **deleted**, not
  merely unused: retry integrity is now `persisted config bytes` ↔ `envelope.config_sha256`.
  A registry, timeout or agent-build change after a restart therefore cannot block retrying
  an occurrence that already happened.
- **D6 (modified):** `--handshake-timeout-ms` (Studio Host default `30_000`) and
  `--shutdown-grace-ms` (default `2_000`) join the existing `--move-timeout-ms` (default
  `120_000`). All three are parsed by one shared `parse_host_timeout`, bounded by the arena's
  own `MAX_TIMEOUT_MS`, and are **Host-owned settings**: the request body cannot express a
  timeout. The Arena has no defaults of its own — every `ArenaConfig` timeout is a mandatory
  field — so these are called Studio Host defaults and `ArenaConfig::validate()` remains
  authoritative.
- **D1 / D2 / D5 confirmed as designed**: seats are registry ids and the request type cannot
  express a program; the `occurrences/<id>/` layout and its validation live in the path
  composer; the shared core was extracted and `completion_wiring_command.rs` was edited.

### What was built

1. **`crates/splendor-cli/src/runtime_orchestration.rs` (new, `pub(crate)`) — the shared
   producer authority.** `OccurrenceEvidence` (the four documents as one value),
   `OccurrenceSlotV1` + `occurrence_slot()` (pure inspection: `Empty` / `Complete` /
   `SettledWithoutCompletion { match_status }` / `Ambiguous`), `RuntimeOrchestrationOutcome`
   (`Completed` / `CompletionFailed` / `Aborted`), `RuntimeOrchestrationError`
   (`Invalid` / `Conflict` / `Failed`), `produce_and_complete()`,
   `complete_persisted_occurrence()`, `completion_receipt_json()`. It does not print, and it
   knows nothing about exit codes, `CompleteArgs`, `--json`, HTTP or command names.
2. **`completion_wiring_command.rs` became two adapters.** The fused chain, the four
   `persist_*`/`complete_persisted`/`describe_completion_error` functions and the
   `PersistedEvidence` struct were **removed** (`-516/+…` in the diff); both entry points now
   build an `OccurrenceEvidence`, call the shared core, and map the typed outcome onto the
   frozen stdout/stderr/exit `0/3/2/1/64`. Argument handling, the alias and distinctness
   checks, `reject_receipt_alias`, `write_json_report` and the usage texts stayed in the CLI.
3. **`paths.rs`: one new accessor, and the id rule inside it.** `occurrence_dir(id) ->
   Result<PathBuf>` validates and composes; the validator is private, so the rule belongs to
   the composer rather than to the network-facing caller. The rule is non-empty, ≤ 128 bytes,
   not `.` or `..`, no leading or trailing dot, and every byte in `[A-Za-z0-9._-]`. Three
   unit tests (one of which enumerates 19 real escape/alias shapes).
4. **`human_play_command.rs`: `StudioHost.paths`, the route, and the mapping.** The resolved
   `StudioLeaguePathsV1` is stored at startup (the reader keeps its own copy private);
   `POST /league/matches` is the single write route; `LeagueMatchRequest` is
   `deny_unknown_fields` with `{occurrence_id, game_id, seed, seats}`; `build_league_match_config`
   turns registry ids into the trusted commands and lets `ArenaConfig::validate()` own every
   arena invariant; `respond_league_write` maps the four settled facts and the three failures
   onto the frozen status codes. The eight read gates are untouched.

### Deviations from the frozen design, and why

- **Completion now reads the documents back from disk.** `produce_and_complete` publishes all
  four, then calls `complete_persisted_occurrence`, which reads them and checks them against
  the envelope's hashes. The CLI previously handed the completion outlet its in-memory bytes.
  The change makes "all four documents are durable *before* completion is attempted"
  structural rather than a matter of call ordering, at the cost of one read-back per match.
  It is strictly stricter: a document that cannot be read back can no longer be completed.
- **One completion implementation.** There is exactly one place that opens the completion
  outlet and one place that verifies the evidence set, shared by the fresh produce path and
  the retry path. The alternative — in-memory completion for a fresh produce, disk completion
  for a retry — would have been two verification paths that could drift.
- **The settled status is read from the report, not asserted.** `ArenaRunner::run` can only
  yield `Aborted` (a `Truncated` report comes from the capped entry point, which this
  pipeline does not call), but the status word is taken from the report's own outcome so the
  Host can never label a truncated match "aborted".
- **G1 carries a second phase for the aborted case.** D3 froze `200` for a settled aborted
  match and no gate covered it, so the aborted round trip (including "re-offering a settled
  aborted occurrence reports the recorded fact and does not produce it again") was folded into
  G1 rather than left as a frozen-but-unmeasured mapping. The gate count stays at four new gates.
- **The write gates prime the league through the CLI.** The read session validates the stored
  rating protocol identity and the durable identity hash, and a completion is what writes
  them, so a gate that reads the league back over HTTP has to start from a league that has
  already booked a match.

### Validation and evidence (local)

- `cargo test -p splendor-studio-league` → **86 passed, 0 failed** (8 test binaries; was 83,
  +3 `paths.rs` unit tests).
- `cargo test -p splendor-cli` → **285 passed, 0 failed, 2 ignored** (46 test binaries; was
  281, +4 gates). Definitive run recorded after the revert of every negative control.
- `cargo test -p splendor-cli --test league_host_api` → **12 passed, 0 failed**
  (8 read gates + `a_post_runs_one_real_match_and_books_it_end_to_end`,
  `a_retry_after_a_completion_failure_never_reruns_the_match`,
  `re_posting_a_booked_occurrence_adds_no_second_match_and_no_elo`,
  `the_match_request_cannot_name_a_program_or_an_unsafe_occurrence_id`).
- `cargo test -p splendor-cli --test completion_wiring --test completion_equivalence` →
  **5 + 1 passed, 0 failed**: the frozen CLI contract survived the extraction of the core.
- **Honest note:** the first full `cargo test -p splendor-cli` run reported 7 `atomic_output::`
  and `arena_command::` unit failures. They pass in isolation and on re-running the same
  target, the code paths are untouched by this slice, and the definitive full run is 285/0.
  It is recorded here as an unexplained transient rather than as a pass-by-default.

### Gates and their negative controls

Three negative controls were applied, run, and reverted. Each gate was shown to be sensitive
to the fix it guards:

| Control | Expectation | Observed |
| --- | --- | --- |
| `occurrence_slot`: `is_complete()` no longer decides `Complete` | G2 and G3 must fail | both failed; the retry fell through to the safety net and answered `409 a completed arena report exists without its occurrence envelope` |
| `respond_league_write`: `Aborted` answered `409` instead of `200` | G1 must fail | only G1 failed, on the aborted phase: `left: 409, right: 200` |
| `run_league_match`: the id validator's error is ignored and the raw id is joined | the refusal gate must fail | it failed on `../escape`, which ran a full match, booked `runtime:../escape`, and wrote its evidence outside the occurrence directory |

### Known limitations (all accepted, none silent)

- The accept loop is serial, so a POST that runs a match blocks `/health` and the read routes
  for the duration of that match. A worker queue is explicitly out of scope for this slice.
- The HTTP layer caps a request body at 64 KiB, well below `MAX_ARENA_CONFIG_BYTES` (1 MiB);
  the effective cap for this route is 64 KiB. The bodies here are a few hundred bytes.
- The league routes are unauthenticated and bound to `127.0.0.1`. This slice adds no auth and
  does not widen the bind address; the security property relied on is that the request cannot
  name a program.
- An occurrence id is an occurrence's **identity**, not a per-request token. Re-using an id
  returns the recorded fact and never runs a new match. On a case-insensitive filesystem two
  ids differing only in case address one slot, and a Windows reserved device name is refused
  by the filesystem rather than by the validator.
- `--registry` remains required, and the three timeouts apply to the Host, not per request.
- The league must already hold a completion before the read surface serves it (the reader
  checks the stored rating protocol identity and the durable identity hash).

### Result and decision

Commit E Slice 1 is **IMPLEMENTED and VERIFIED locally**: one write route, one shared producer
authority, the retry path driven by persisted evidence, and the four frozen status families
each with a gate and a negative control. The CLI's five wiring gates and the eight read gates
are unchanged and green. No capability claim is made beyond these commands.

### Next authorized gate

Owner review of Commit E Slice 1 before any further scope. UI, worker queue, watcher,
scheduler and batch remain **not authorized**. The deferred P2 from Commit D Slice 1 (one
archive three-state instead of `is_file()` classification) is still open and unchanged.

## Commit E Slice 1 — Repair 1: three state/identity seams (2026-09-15)

Status: **IMPLEMENTED / VERIFIED (local evidence only)**. An independent review of
`91afb01` returned **REPAIR_REQUIRED** with **P0 = 0 / P1 = 3 / P2 = 1**. The review
accepted the extraction of the shared core (one authority for the Arena run, the four
documents, the persisted retry and the completion outlet; the CLI reduced to an adapter
with no second `ArenaRunner + publish + completion`), the D4 ordering (the slot is
classified before the registry is consulted, and only `Empty` reaches
`build_league_match_config`), and D1/D2 (four fields, `deny_unknown_fields`, registry ids
only, path-component validation inside the composer).

### P1-1 — the first successful completion now activates the read session

The read session was opened once at startup and its failure cached, so on a fresh league
the Host answered `503` for the read routes **forever**: `run_league_match` never
re-opened it. The write route is precisely the initialisation flow that creates the
stored rating protocol identity and the durable identity hash a read session validates, so
a Host had to be restarted before it could serve the match it had just booked.

`run_league_match` is now a wrapper around `run_league_match_once`, and a booking triggers
`reopen_read_session_if_unavailable()` — which only acts when no reader is open, and whose
failure is recorded for the read routes rather than allowed to reinterpret a booking that
already succeeded. G1 was rebuilt as a genuine first-match bootstrap
(`new_league` → Host → `503` → POST → `200` → **same process** → leaderboard `200` with the
booked participants → match `200` → replay `200`); it previously used `primed_league`, which
is why it could not see this.

### P1-2 — a settled, non-completed match is a report-only slot

`occurrence_slot()` parsed any readable aborted report as `SettledWithoutCompletion`
without requiring that the report be the *only* document in the slot. A leftover
`config.json`, or a stray `occurrence.json`, therefore produced `200
match_status=aborted` out of an evidence set that was not the normal aborted shape. The
frozen D3 order says a settled aborted report is a recorded fact *only* then, and anything
else is a conflict. The slot now refuses the presence of any of the other three protocol
evidence documents beside the report as `Ambiguous` (409), naming the files it found. The
check covers those three protocol positions; it does not scan the directory for arbitrary
extra files.

### P1-3 — the request's occurrence id is bound to the persisted envelope

`complete_persisted_occurrence` verified that the documents agreed with **each other** and
then completed whatever occurrence the envelope named. It never knew which occurrence the
caller had asked for, so a byte-for-byte copy of a complete slot under a second id was
answered `200 already_present` with the *first* occurrence's `source_identity` — a caller
receiving a match it never named. Internal consistency is not identity.

The function takes `expected_occurrence_id: Option<&str>`. The Host passes the request's
id, the fresh path passes the id it minted (so both paths share one invariant), and the
completion-only CLI command passes `None` because its authority is the four documents the
operator names rather than a slot. A mismatch is a conflict, not a recorded fact.

This also **retracts the case-folding claim** in the previous section of this document: on
a case-insensitive filesystem two ids differing only in case address one slot, and that is
now a conflict rather than another occurrence's recorded fact. `paths.rs`' documentation
was corrected accordingly. Cross-platform identity semantics no longer drift with the
filesystem.

### P2 — 409 and 500 reason phrases

`respond()`'s reason table knew only 200/204/400/404/503, so the new `409` and `500`
responses went out on the wire as `HTTP/1.1 409 Not Found` / `500 Not Found`. Both phrases
were added; the status codes themselves were already correct.

### Validation and evidence (local)

- `cargo test -p splendor-cli --test league_host_api` → **12 passed, 0 failed** (G1 now
  covers the first-match bootstrap, the aborted round trip, the report-only rule and the
  stray-document conflict; G3 covers the copied-slot conflict).
- `cargo test -p splendor-studio-league` → **86 passed, 0 failed**.
- `cargo test -p splendor-cli` → **285 passed, 0 failed, 2 ignored** (46 test binaries).
- `cargo test -p splendor-cli --test completion_wiring --test completion_equivalence` →
  **5 + 1 passed**: the frozen CLI contract is unchanged, including the `None` binding.

### Negative controls (applied, failed their gate, reverted)

| Control | Expectation | Observed |
| --- | --- | --- |
| the booking does not refresh the read session (P1-1) | G1 must fail | G1 failed: after a successful POST the same Host still answered `503 no Studio rating config integrity evidence is recorded` |
| the stray-document guard is removed (P1-2) | G1 must fail | G1 failed: report plus a stray `config.json` was answered `200 match_status=aborted` instead of `409` |
| the Host does not bind the request id (P1-3) | G3 must fail | G3 failed: POST `gate-k-0002` was answered `200 already_present` with `source_identity: runtime:gate-k-0001` |

### Known limitations (updated)

The limitation list of the previous section stands, with one correction: a case-insensitive
filesystem folding two ids onto one slot is now a **conflict**, not another occurrence's
recorded fact. Everything else is unchanged — a serial accept loop, a 64 KiB body cap,
unauthenticated `127.0.0.1`-bound routes, `--registry` required, and a read surface that
needs a league with at least one completed (or settled-and-refused) match.

### Next authorized gate

Owner re-review of Commit E Slice 1 with Repair 1, on the evidence above. No scope was
added: still no concurrency, worker queue, authentication, UI, batch, watcher, archive
three-state or new error framework.

### Repair 1 terminal review — ACCEPTED / CLOSED (2026-09-15)

```text
Commit E Slice 1 @ 0b69dfe
APPROVED / ACCEPTED / CLOSED

P0 = 0
P1 = 0
P2 = 0
Further repair = NONE

Commit D's registered archive three-state P2: still DEFERRED, not folded into this round
```

An independent review of `91afb01 → 0b69dfe` confirmed all three P1s and the P2 as fixed, verified
HEAD, a clean work tree and `main == origin/main`, and re-ran the gates locally:
`league_host_api` 12/12, `completion_wiring` 5/5, `completion_equivalence` 1/1, the
`splendor-studio-league` suite, and `git diff --check` on the commit's diff. The full CLI run
(285 passed / 2 ignored) and the three negative controls were not re-executed by the reviewer and
remain recorded as **local execution evidence**. The first-run seven transient unit-test failures
stay recorded as an unexplained transient: not a new defect, and not described as diagnosed.

What the review singled out as the repair's value is that it protects two different layers of fact at
once: four documents may agree with each other and still have to belong to the match the request
named, and a booking that has already succeeded must not be rewritten into a failure because a read
session could not be re-opened. The shared implementation stayed whole — the Host and the fresh
producer both bind the expected occurrence id, the completion-only CLI command keeps `None`, and the
retry still consumes persisted evidence first, reaching the registry and the Arena only from an empty
slot.

**Correction recorded in this document (wording narrowed, no behaviour changed).** The P1-2 prose
above said the slot "refuses any stray document beside the report". What the code actually checks is
the three other **protocol evidence positions** — `config.json`, `replay.json`, `occurrence.json` —
and it does not scan the directory for arbitrary extra files. Corrected reading: a settled,
non-completed match is settled only while the report is the sole protocol evidence document in the
slot; the presence of any of the other three protocol documents is a conflict (409). The code comment
inside `OccurrenceEvidence`'s own vocabulary ("document" = one of the four protocol documents) remains
accurate in context, so no code was touched for this and no directory-scanning capability was added.

### Result and next stage

The background chain **Host starts an Arena match → evidence is durable → completion → archive,
ledger and Elo → the same process reads the result back** is closed. This is *not* the same as the
seven original product requirements being met: the next stage turns to what a player actually uses —
the pages and the onboarding flow — and the UI, statistics and Review repair backlog remain
undelivered. This round closes here.
