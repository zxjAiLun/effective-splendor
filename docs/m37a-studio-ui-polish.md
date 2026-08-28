# M37A — Studio UI Polish

```ini
MILESTONE = M37A
STATUS = ACCEPTED / FROZEN
BASE_COMMIT = 6d0c37a
ROUND_COMMIT = f1467ea
SCOPE = GUI-only polish round on Replay Studio: font-size token system, token/cost
        visual hierarchy, BoardView consolidation, reserve-card rendering, net-cost
        card geometry, dead-code cleanup, responsive breakpoint fixes, tsbuildinfo ignore.
        No Arena, no model, no replay/engine semantics change.
UI = /play, /review, /experiments, /ratings in apps/replay-studio
PROMOTION = N/A (no competitive result; champion unchanged = M07)
DECISION = ACCEPTED / FROZEN — gate passed; user closed the round on 2026-08-28.
           One item DEFERRED: --ui-scale UI entry (reopen conditions recorded below).
```

## 提交记录

本轮刻意分成两个提交，因此 `ROUND_COMMIT` 无法在第一个提交里自填（提交不能包含
自身哈希，反复 amend 只会让哈希漂移）：

1. **实现提交** —— 全部代码改动 + 本文件（此时 `ROUND_COMMIT` 为占位符）。
2. **文档提交** —— 仅把上述提交的 SHA 回填进 `ROUND_COMMIT` 与下方表格。

| 提交 | SHA | 内容 |
|---|---|---|
| 实现提交 | `f1467ea` | 7 modified + 1 新增组件 + 本文件 |
| 文档提交 | （本提交） | 仅回填 `ROUND_COMMIT` |

`handoff.md` 按仓库发布规则保持 local-only（`.gitignore:12:/handoff.md`），
两个提交均未包含它。

## Problem and evidence

M36A closed the experiment replay library at `6d0c37a` (`ACCEPTED / CLOSED`). A
post-closure pass over the Replay Studio surfaces eight concrete readability and
consistency defects, each reproducible by rendering a page:

1. **Ad-hoc font sizes.** `globals.css` mixed raw `px` with one-off `rem`/`em`
   sizes across roughly ninety rules. There was no scale, so a global readability
   fix was impossible without editing every rule by hand. Several sizes had
   drifted below 8 px, below any usable legibility floor.
2. **No token-cap readout on the replay/review boards.** The 10-token cap is the
   binding constraint that forces token returns, yet the boards rendered six
   per-colour counts and never the total. `/play` carried a private inline
   readout that no other surface could reuse.
3. **Two divergent board renderers.** `app/review/page.tsx` held a private
   `BoardView` (plus private `GemSet`/`gemCode`) duplicating `BoardPanel` in
   `app/components/replay-board.tsx`. The copies had already drifted: the review
   copy rendered noble prestige from the **card** catalogue with a hardcoded
   fallback of `3` and dropped noble requirements entirely.
4. **Reserve cards rendered as counts, not cards.** Opponent reserves showed only
   `reserved_count` in the player panel. In Splendor a reserve taken face-up from
   the market is public information, so the UI was withholding information the
   player is entitled to. Own reserves rendered a card face but always at the
   printed cost, never net of the player's permanent bonuses.
5. **Net cost invisible.** `DevelopmentCard` had no way to show `cost − bonus`,
   so a player had to do the subtraction offline for every card on every turn.
6. **Dead CSS and dead code.** Rules orphaned by earlier rounds, plus the private
   `BoardView` helpers once item 3 landed.
7. **Responsive breakpoint gaps.** `/play` player panels did not stack below
   680 px, and the nobles strip overflowed its container below 900 px.
8. **`*.tsbuildinfo` not ignored** in `apps/replay-studio/.gitignore`, so a plain
   `tsc --noEmit` polluted `git status` with a build artifact.

## Initial design

Eight independent, low-risk fixes bundled as one polish round. Every change is
local to the presentation layer; no runtime, protocol, referee, or training code
is touched.

Guiding principle: **make the type scale the single readability knob, then express
every other fix as a consumer of it.** Item 1 is the enabler for items 2, 4 and 5,
all of which add text to already-dense card geometry and would otherwise have
needed hand-tuned per-rule sizes.

## Scope and non-goals

**In scope**

- `--fs-*` token scale in `globals.css`; no rule hardcodes a `px` font size;
  `--ui-scale` multiplies the root font size.
- Shared `TokenTotal` component for the 10-token cap.
- Consolidate `/review`'s private `BoardView` onto `BoardSurface` from
  `components/replay-board.tsx`.
- `ReservedCards` in `BoardSurface` (referee-reveal / own / opponent-public
  three-way split) and `OpponentReserve` in `/play`.
- Net-cost rendering on `DevelopmentCard` via an optional `discount` prop.
- Responsive fixes at 900 px and 680 px.
- `*.tsbuildinfo` ignore.

**Non-goals**

- No UI control to change `--ui-scale` (see Known limitations).
- No change to card art, layout structure, or the market grid.
- No change to `trace-runtime.mjs`, the review API contract, or any
  referee/protocol surface.
- No new tests for pure presentational geometry beyond the existing rendered-HTML
  suite; visual verification is by screenshot at named breakpoints.
- No reduction of the pre-existing `tsc` error count (see C7).

## Contracts and invariants

- **C1 — Type scale.** Every `font-size` in `globals.css` resolves to a
  `var(--fs-*)` token. Floor is `--fs-3xs` (`.6875rem` / 11 px).
  `html { font-size: calc(100% * var(--ui-scale)); }` multiplies the browser's
  own font-size preference rather than overriding it.
- **C2 — Token cap.** `TOKEN_CAP = 10`. A board renders `held / 10` next to every
  gem strip. `sumTokens` covers exactly the six keys
  `white, blue, green, red, black, gold`.
- **C3 — Cap violation is visible, not clamped.** `TokenTotal` renders an
  `over-cap` state rather than clamping to 10, so a state bug surfaces in the UI
  instead of hiding behind a plausible-looking "10/10". `over-cap` must never
  appear in a verified replay.
- **C4 — Reserve information parity.** Three cases, resolved in `ReservedCards`
  (`app/components/replay-board.tsx:288`):
  - referee reveal → every reserve, blind ones flagged;
  - own reserve → `player_view.private.reserved`, including own blind deck reserves;
  - opponent → `public_reserved` only; `reserved_count − known` renders as
    `HiddenDevelopmentCard`.

  The player view must never leak a blind reserve's identity.
- **C5 — Net cost is additive.** `discount` is optional. Without it the printed
  cost renders unchanged. With it, cost gems render `owed` after the free bonus
  deduction, with the printed cost retained and struck through. `covered` gems
  (owed ≤ 0) are dimmed but still shown.
- **C6 — One board renderer.** `/review` consumes `BoardSurface`; the private
  `BoardView`/`GemSet`/`gemCode` are deleted, not left as fallbacks.
- **C7 — tsc non-regression.** The round must not increase the pre-existing
  `tsc --noEmit` error count. Baseline measured at 10 (see Validation); the round
  may reduce it but need not clear it.
- **C8 — Publication.** No generated artifact is committed. Screenshots live
  under `local-artifacts/m37a-studio-ui-polish/`, which is gitignored via
  `/local-artifacts/`; `handoff.md` stays local-only per the repository rule.

## Implementation plan

1. Define `--ui-scale` and the `--fs-3xs … --fs-5xl` scale in `:root`; rewrite
   every `font-size` in `globals.css` to a token; delete orphaned rules.
2. Add `app/components/token-total.tsx` exporting `sumTokens` and `TokenTotal`;
   wire into `/play` (`PlayerResources`) and both boards.
3. Generalise `BoardPanel` into `BoardSurface` (market + nobles + bank + player
   panels) and add `ReservedCards`; migrate `/review` off its private
   `BoardView`; update `/` to the new export name and `BoardFrame` type.
4. Add `discount` to `DevelopmentCard`, net-cost rendering in `CostGems`, a
   `mini` variant, and `HiddenDevelopmentCard`.
5. Add `OpponentReserve` to `/play` and pass `humanBonuses` as `discount` for
   market and own-reserve cards.
6. Fix the 900 px nobles-strip overflow and the 680 px player-panel stacking.
7. Add `*.tsbuildinfo` to `apps/replay-studio/.gitignore`.
8. Validate: `npm test`, `npm run lint`, `npx tsc --noEmit`, then screenshot the
   named pages and edge cases.

## Iteration log

- **Rename, not rewrite, for the board.** The first instinct was to extend
  `BoardPanel` in place. Reading `/review`'s private `BoardView` showed it was a
  strict subset of `BoardPanel` plus a nobles row, so `BoardSurface`
  (`app/components/replay-board.tsx:144`) now exports the full surface and
  `BoardPanel` (`:108`) remains the wrapper with its heading. `/experiments`
  keeps `BoardPanel` because its three-column layout needs the title wrapper.
  This let `/review` drop ~49 lines plus its `GemSet`/`gemCode` duplicates in one
  import swap.
- **Nobles catalogue was the blocking dependency for C6.** `/review` had never
  built a nobles `Map` — its deleted `BoardView` rendered noble prestige from the
  card catalogue with a hardcoded `3` and no requirements, an always-wrong
  expression. Consolidation required adding the missing `nobles` memo in
  `/review` (`app/review/page.tsx:135`). This is a latent bug fixed as a side
  effect of C6, not a scope addition.
- **`TokenTotal` renders `over-cap` rather than clamping.** `Math.min(total, 10)`
  was considered and rejected: clamping would silently hide a referee or state
  bug behind a plausible-looking "10/10". C3 records this deliberately.
- **Hidden reserve count is floored at zero.** The arithmetic
  `reserved_count − known.length` is clamped so a malformed frame degrades to
  "no hidden cards" rather than rendering a negative count.
- **Breakpoint ordering bug found during verification.** The `@media(max-width:1250px)`
  rule re-declared `.human-workspace` *after* the `@media(max-width:1000px)` rule,
  so at 900–999 px the single-column collapse was overridden by the two-column
  declaration and the sidebar was clipped off-screen. Fixed by splitting the
  workspace declaration into a `@media(min-width:1001px) and (max-width:1250px)`
  range, leaving the bank/table-gem rules at `max-width:1250px`. Caught by
  screenshot, not by the test suite — see Known limitation 5.
- **`--ui-scale` has no UI entry.** The token and its root-font hook are
  implemented so the scale is genuinely global, but no control was added. Left
  `DEFERRED`: adding a control is a product decision about where it lives
  (topbar? per-page?) and whether it persists, not a mechanical step.
- **Closure decision (2026-08-28).** The round was held at `BLOCKED` pending the
  user's call on that control. The user chose to defer it and authorized closure
  with the item carried as `DEFERRED`, so the round moved to `ACCEPTED / FROZEN`
  rather than staying open. The unexercised live `/play` `OpponentReserve` path
  stays a documented limitation (2) rather than a blocker, because the shared
  `ReservedCards` rendering path is verified via `/review` frame 13 — the
  `/play`-specific `OpponentReserve` is a thin wrapper over the same data.

## Final implementation

| File | Change |
|---|---|
| `apps/replay-studio/app/globals.css` | `--ui-scale` + `--fs-3xs…--fs-5xl` scale in `:root`; every `font-size` retargeted to a token; new `.token-total`, `.reserved-*`, `.opponent-reserve`, `.development-card-mini`, `.development-card-hidden` and net-cost `.gem em` rules; orphaned rules deleted; new `@media(max-width:900px)` nobles-strip rule, `@media(max-width:680px)` `.human-score` stacking, and the split `@media(max-width:1250px)` / `@media(min-width:1001px) and (max-width:1250px)` play-table rules |
| `apps/replay-studio/app/components/token-total.tsx` | **New.** `TOKEN_CAP`, `GEM_KEYS`, `sumTokens`, `TokenTotal` with `at-cap` / `over-cap` states and an `aria-label` of the form `N of 10 tokens held` |
| `apps/replay-studio/app/components/replay-board.tsx` | `BoardSurface` (`:144`) with `ReservedCards` (`:288`) implementing the C4 three-way split; `BoardFrame` type exported; `TokenTotal` rendered per player; dead code removed |
| `apps/replay-studio/app/development-card.tsx` | `discount?: number[]` prop; `CostGems` net-cost rendering with struck-through printed cost and `discounted` / `covered` gem states; `mini` variant; `HiddenDevelopmentCard` |
| `apps/replay-studio/app/page.tsx` | `BoardPanel` → `BoardSurface`, `Frame` → `BoardFrame`; removes the nonexistent `Frame` import; demo frame extended to two reserves (one market, one blind deck) so both C4 branches render |
| `apps/replay-studio/app/review/page.tsx` | Private `BoardView` / `GemSet` / `gemCode` deleted; `BoardSurface` imported from `components/replay-board`; `nobles` memo added |
| `apps/replay-studio/app/play/page.tsx` | `OpponentReserve` component; `TokenTotal` in `PlayerResources`; `discount={humanBonuses}` on market and own-reserve cards |
| `apps/replay-studio/.gitignore` | `*.tsbuildinfo` added under a `# typescript` heading |

Net: 7 files modified, 1 file added; `+360 / −240`.

## Validation and evidence

All commands run from `apps/replay-studio/`, against the M37A working tree as
committed at `f1467ea`.

| Check | Command | Result |
|---|---|---|
| Tests | `npm test` | **27 / 27 pass**, 0 fail, 0 cancelled, 0 skipped |
| Lint | `npm run lint` (= `eslint . --ignore-pattern dist --ignore-pattern .next`) | **clean**, exit 0, no output |
| Typecheck | `npx tsc --noEmit` | **9 errors** — non-regression satisfied (C7) |
| Whitespace | `git diff --check` | **clean**, exit 0 |

### tsc baseline provenance

The baseline is **10 errors**, measured in an isolated git worktree at `6d0c37a`
(`git worktree add /tmp/m37a-baseline 6d0c37a`, then `npx tsc --noEmit` with
`node_modules` symlinked from the main tree). Measuring in a worktree rather than
by stashing keeps the working tree untouched and makes the number reproducible.

The single error removed by this round is:

```
app/page.tsx(19,8): error TS2305: Module '"./components/replay-board"' has no exported member 'Frame'.
```

It disappeared because `/` was migrated off the nonexistent `Frame` type import
onto the exported `BoardFrame`. The 9 remaining errors are pre-existing
`any`-inference issues, all outside this round's scope:

- `app/experiments/page.tsx` 393, 435, 443, 446, 558
- `app/page.tsx` 398
- `app/review/page.tsx` 238, 381, 408

### Screenshots

Stored under `local-artifacts/m37a-studio-ui-polish/` (gitignored via
`/local-artifacts/`, so durable across sessions but not committed — C8).

| File | What it shows |
|---|---|
| `play-1600.png` | `/play` at 1600 px, ply 0 |
| `play-ply6-1600.png` | `/play` after a market reserve — own reserve tray, net cost |
| `play-1250.png` | `/play` at the 1250 px breakpoint |
| `play-900.png` / `play-900-fixed.png` | before/after the breakpoint-ordering fix |
| `play-680.png` / `play-680-fixed.png` | before/after the 680 px player-panel stacking |
| `review-1600.png` | `/review` frame 0, M07 determinization review |
| `review-frame13-1600.png` | `/review` frame 13 — 10/10 FULL token cap, opponent `public_reserved`, own reserve |
| `experiments-1600.png` | `/experiments` browse view |
| `experiments-replay-1600.png` | `/experiments` deep-link replay (`BoardPanel` → `BoardSurface`) |
| `ratings-1600.png` | `/ratings`, which inherits the global type scale |

### Edge cases verified

| Edge case | Evidence |
|---|---|
| 4-cost-row cards | `play-1600.png`, `review-1600.png` |
| 10-token cap display | `review-frame13-1600.png` (`TokenTotal` at-cap state) |
| Own reserves | `play-ply6-1600.png` |
| Opponent `public_reserved` | `review-frame13-1600.png` (shared `ReservedCards` path) |
| 900 px single-column collapse | `play-900-fixed.png` |
| 680 px stacked player panels | `play-680-fixed.png` |

## Result and decision

**ACCEPTED / FROZEN.** The declared acceptance gate passed in full:

| Gate | Result |
|---|---|
| `npm test` | 27 / 27 pass |
| `npm run lint` | clean |
| `npx tsc --noEmit` | 9 errors ≤ baseline 10 (non-regression, C7) |
| `git diff --check` | clean |
| Screenshot verification of the six named edge cases | passed |

Consolidation (C6) also removed a latent defect: `/review` rendered noble prestige
from the wrong catalogue with a hardcoded `3` and dropped requirements entirely.

The user resolved the pending gate on 2026-08-28 by **deferring** the `--ui-scale`
UI entry rather than requesting it. The round is therefore closed as
`ACCEPTED / FROZEN`, not `BLOCKED`: nothing is waiting on external input for
closure, and the deferred item carries its own reopen conditions.

### Deferred: `--ui-scale` UI entry

`DEFERRED`, not rejected and not blocking. The custom property is live
(`html { font-size: calc(100% * var(--ui-scale)); }`) and the whole `--fs-*`
scale is expressed through it, so the knob works — there is simply no control to
turn it.

**Reopen conditions** (any one is sufficient):

1. A user needs to resize the interface at runtime without devtools — e.g. a
   HiDPI display, a projector, or a live demo.
2. A follow-up round touches the type scale or card geometry and would benefit
   from being able to eyeball more than one scale value.
3. Accessibility review requests a user-controllable text size.

When reopened, the decision still owed by the user is *placement and persistence*
(topbar vs per-page; localStorage vs session-only), not whether to build it.

## Known limitations

1. **`--ui-scale` has no UI entry (DEFERRED, not blocking).** The custom property
   is live (`html { font-size: calc(100% * var(--ui-scale)); }`) but can only be
   changed by editing CSS or devtools. Reopen conditions are recorded under
   Result and decision.
2. **Opponent reserve in `/play` was not exercised against a live game state.**
   The heuristic agent did not reserve during the test game. The shared
   `ReservedCards` path is verified on `/review` frame 13
   (`review-frame13-1600.png`); the `/play`-specific `OpponentReserve` wrapper is
   verified structurally (lint, typecheck, rendered markup) but not against a
   real opponent reserve.
3. **`/experiments` was verified via one deep-link replay**, not all 17 pairings.
   `experiments-replay-1600.png` covers the deep-link path only.
4. **9 pre-existing `tsc` errors remain.** All are `any`-inference issues in
   pages touched by earlier rounds. Out of scope for a polish round; C7 required
   only non-regression.
5. **Visual verification is by human-eye screenshot, not pixel diff.** The
   900 px and 680 px fixes are judged from before/after PNG pairs. No automated
   layout regression suite exists, which is exactly why the breakpoint-ordering
   bug surfaced only when a page was actually rendered.
6. **The screenshot corpus is evidence, not a fixture.** The 12 PNGs under
   `local-artifacts/m37a-studio-ui-polish/` are deliberately not committed. They
   are not deterministic: they depend on the running Studio Host, on the cached
   M07 review for session `human-1786554356-0-25816-1`, and on ad-hoc headless
   Chrome invocations with no committed script. See Next authorized gate.

## Post-freeze correction (2026-08-29)

**Commit `a042f9b`** — `fix(replay-studio): reserve cards show printed cost, not net cost`

This section is appended after the round was frozen. It does **not** revise the
acceptance record: the gate table, the `ACCEPTED / FROZEN` verdict and the
validation evidence in Result and decision stand as recorded at closure. The
status is unchanged; this is a correction to the implementation, not a reopening
of the round.

### Defect

M37A passed `discount={owner.bonuses}` to `DevelopmentCard` for reserve cards.
With `discount` set, `CostGems` renders the *owed* amount as the primary number
and the printed cost as a struck-through secondary badge. On the compact `mini`
variant used inside reserve strips that produced a crowded second column of
numbers in the lower-left of every reserved card. The user reported it as
"reserve 的牌在手里，左下角还多了一列".

The net-cost display was not wrong in itself — it was the right feature in the
wrong place. The reserve strip is the narrowest card surface in the UI, and the
owed/printed pair that reads well on a full-size market card does not fit there.

### Fix scope

`discount` removed from the three reserve render sites:

| Site | File | Was |
|---|---|---|
| shared `ReservedCards` (used by `/`, `/review`, `/experiments`) | `apps/replay-studio/app/components/replay-board.tsx` | `discount={player.bonuses}` |
| `/play` own reserve tray | `apps/replay-studio/app/play/page.tsx` | `discount={humanBonuses}` |
| `/play` `OpponentReserve` | `apps/replay-studio/app/play/page.tsx` | `discount={player.bonuses}` |

Deliberately **unchanged**: market cards in `/play` and the selected-card preview
in the pending-move panel still pass `discount` and render net cost. Net cost is
most useful at the moment of judging whether a card is affordable, which is the
market — not the reserve strip, where the card is already held.

The `ReservedCards` JSDoc was updated to record why no discount is applied.

### Validation

| Check | Result |
|---|---|
| `npm test` | 27 / 27 pass |
| `npm run lint` | clean |
| `npx tsc --noEmit` | 9 errors — unchanged (baseline 10) |
| `git diff --check` | clean |
| Screenshot | `/` demo — reserve strips on both seats show printed cost only |

Screenshots: `local-artifacts/m37a-studio-ui-polish/root-demo-1600.png` (before)
and `root-demo-fixed-1600.png` (after). Same caveat as Known limitation 6 —
gitignored, local evidence, not a committed fixture.

### Why the round's gate did not catch it

The gate passed because this is not a test failure. It is a judgement about
density on one card variant, and no check in the suite encodes it. Two recorded
limitations explain the gap: the `/play` opponent-reserve path was never
exercised against a live game (limitation 2), and visual verification is
human-eye rather than automated (limitation 5). The user found the defect within
minutes of opening the page.

This is the same class of gap as the 900 px breakpoint bug found earlier in the
round — both were invisible to a green suite and obvious on first real use — and
it is further evidence for the deterministic layout fixture proposed under Next
authorized gate.

## Next authorized gate

The round is closed. Two follow-ups are proposed; **neither is authorized yet and
both need a new round**:

1. **Deterministic UI regression fixture (proposed, not authorized).** M37A's
   visual evidence is not reproducible outside this session. A worthwhile
   follow-up would commit (a) a self-contained replay or session fixture — a
   pinned trace/state that exercises the worst cases (4-cost-row cards, token cap
   reached, reserves on both seats) without needing a live Host or a specific
   cached review — and (b) a scripted capture runner that renders each page at
   the named breakpoints. Scripted geometry assertions would be stronger still:
   the 900 px breakpoint bug was a pure CSS cascade ordering fault that a pixel
   diff would not have caught either, so assertions on computed layout (e.g.
   "no element overflows the viewport at 900 px") are the real goal. Scope,
   tooling and whether the corpus itself is committed should be decided then.
2. **`--ui-scale` UI entry** — `DEFERRED`, reopen conditions under Result and
   decision.

Per the repository publication rule, `handoff.md` is local-only — confirmed with
`git check-ignore -v handoff.md` (`.gitignore:12:/handoff.md`) — and was not
staged with the M37A commits.
