# M47S — Residual Target Feasibility Diagnostic

```ini
MILESTONE = M47S
STATUS = COMPLETED_DIAGNOSTIC / RESIDUAL_TARGET_FEASIBLE
                (all three gates passed with wide margins; awaiting strategy
                review of the verdict; M48A design stage now justified but
                still NOT AUTHORIZED)
SCOPE = offline-only residual-target feasibility diagnostic; no model, no training
BASE_COMMIT = e159d64 (M46A permanently closed)
DESIGN = frozen by user ruling 2026-09-07; design-only commit first, then
         offline implementation + execution AUTOMATICALLY AUTHORIZED
CORPUS = M46A frozen test split ONLY (256 games, 2048 authoritative roots)
NEW_SELF_PLAY = NOT AUTHORIZED
TRAINING = NOT AUTHORIZED
ARENA = NOT AUTHORIZED
M48A = NOT AUTHORIZED
M48B = NOT AUTHORIZED
```

> **Through M46A, the learned-replacement route is closed. The candidate
> successor hypothesis is `score = q_static + Rθ`. Before any M48A design,
> this diagnostic answers one question: does a dense, stable, non-trivial
> correction target actually exist?**

## Problem and evidence

- M42S (permanently closed): n1 vs D2-direct is resolved at 8,203.1 bps, but
  n2000 vs n1 is UNRESOLVED; the strict common-state audit measured n1-vs-n2000
  disagreement ≈ 26/100 contexts. This is a promising prior but only a
  100-context descriptive audit — not a data contract for a new route.
- M46A (permanently closed): `RELATIONAL_SUCCESSOR_REPRESENTATION_NOT_VALIDATED`
  — the frozen SUM+MAX successor representation did not carry the n1 decision
  structure. Route-level ruling: static-prior + learned residual is the next
  candidate hypothesis, gated on this diagnostic.

M47S asks, with no neural network involved:

> **Between n1/static and M07/n2000 continuation, is there a sufficiently
> dense, budget-stable, non-tie, non-canonical-noise set of correctable
> ranking differences?**

## Scope and non-goals

### In scope

- All 2,048 M46A test roots (no resampling, no cherry-picking, no new root
  selection).
- Four search budgets per root: n1, n200, n500, n2000.
- Full per-action root-player aggregate utilities at every budget.
- Tie-aware correction metrics F1/F2/F3 plus descriptive diagnostics.
- One tracked result artifact.

### Not in scope / not authorized

- Any new self-play games.
- Any model training, checkpoint, or Arena.
- M48A/M48B design or implementation.
- Any claim that n2000 corrections are objectively correct.

## Contracts and invariants

### 1. Corpus binding (frozen)

```text
games:   6_602_304 .. 6_602_559 = 256 games
roots:   256 × 8 = 2048 authoritative roots
use all 2048 roots
```

These roots are proven (M46A) to be game-seed-disjoint from train/val, with
authoritative information-set identities and successor hashes disjoint across
splits. They are henceforth a **permanent diagnostic holdout**: M48A may never
train on them or use them for checkpoint selection.

### 2. Search budgets (frozen)

```text
sample_seed     = 20_260_703
sample_count    = 4
max_depth_turns = 1
max_nodes       = 1 / 200 / 500 / 2000
```

Roles: n1 = static prior; n2000 = M07 champion continuation target; n200/n500
= stability checks (M42S showed their behavior is close to n2000).

### 3. Full utility recording (fail closed)

For each root and each budget, record:

```text
canonical legal action list
per-action root-player aggregate utility
optimal action set A*_budget
canonical selected action
nodes/search metadata
```

Assertions (fail closed on violation):

```text
canonical action set identical across n1/n200/n500/n2000
all action utilities present
all optimal sets non-empty
```

### 4. Authoritative identity reuse

Reuse the M42S strict-audit identity path (`build_information_set_v1` triple)
and the M46A frozen test-root manifest. Do not invent a new identity system.
Final audit must verify the root identity digest matches M46A's test split.

### 5. Tie-aware correction definitions

Do NOT treat raw `a_n1 != a_n2000` as a correction (it may be pure canonical
tie-break noise). Define the n2000 optimal set:

```text
A*_2000 = {a : q_2000(a) = max_b q_2000(b)}
```

A true **n1 correction opportunity** is:

```text
a_n1 ∉ A*_2000
```

i.e. n1's choice is strictly non-optimal under the n2000 teacher. The legacy
canonical disagreement rate is also reported, as diagnostic only.

### 6. Scientific boundary

n2000 vs n1 remains UNRESOLVED in Arena terms (M42S). Therefore M47S may
claim only:

> n2000 is the current champion M07 continuation target and provides deeper
> continuation-based action preferences than n1.

It may NOT claim that every n2000 correction is objectively correct. M47S
tests the existence of an imitable, stable residual target — not ground-truth
Q*. Whether the residual adds playing strength can only be decided by a
future M48B Arena.

## Acceptance and rejection gates (frozen)

### F1 — Correction incidence

```text
C_2000 = #{s : a_n1 ∉ A*_2000(s)} / 2048
PASS:  C_2000 >= 10%   (≈ >= 205 roots)
```

If fewer than one in ten decisions carry a correction opportunity, the
residual training signal is too sparse — and n2000's own Arena advantage over
n1 was never resolved — so a neural residual milestone is not justified.

### F2 — Correction stability

For each n2000-correction root, define A*_200, A*_500, A*_2000. A **stable
correction** requires all of:

```text
a_n1 ∉ A*_200
a_n1 ∉ A*_500
a_n1 ∉ A*_2000
A*_200 ∩ A*_500 ∩ A*_2000 ≠ ∅
```

(Common continuation-optimal action must exist; canonical tie-breaks need not
coincide.)

```text
PASS: stable / n2000-correction roots >= 80%
PASS: stable correction roots / all roots >= 8%  (≈ >= 164 roots)
```

If budgets keep flipping against each other, the residual target itself is
too unstable to learn.

### F3 — Correction magnitude

For every stable-correction root, the n1 action's normalized regret under the
n2000 teacher:

```text
r(s) = (q_2000(a*_2000) - q_2000(a_n1))
       / max(q_2000(a*_2000) - min_a q_2000(a), 1)
```

```text
PASS: median normalized regret over stable-correction roots >= 0.05
```

Report mean, p25, p50, p75, p90, p95, max. Near-tie corrections do not
justify a learned residual.

### Verdict semantics

All three main gates pass:

```text
RESIDUAL_TARGET_FEASIBLE
→ M48A worth entering design stage (NOT automatic implementation authorization)
```

Any main gate fails:

```text
RESIDUAL_TARGET_WEAK_OR_UNSTABLE
→ recommendation: M48A = NOT PURSUED; neural evaluator research = STOP
```

No fifth neural architecture hunt after that.

## Descriptive diagnostics (no gates)

### Pairwise correction density (reported, not gated)

For each root's action pairs where the teacher is strict
(`q_2000(a_i) != q_2000(a_j)`), check whether n1's sign agrees:

```text
teacher-strict pair count
n1-correct pair count
n1-tie-on-teacher-strict count
n1-reversed pair count
pairwise correction rate
```

This directly informs how dense pairwise residual supervision would be for
M48A. No arbitrary threshold is set now; if F1/F2/F3 pass, an enlarged
training corpus typically supplies ample pairs.

### Static margin to overcome

For each correction with continuation-optimal action a_c:

```text
m_static = q_1(a_n1) - q_1(a_c)
```

Also its normalized form. This tells future M48A whether the residual must
fix small local mistakes or overturn strong static preferences.

### Correction taxonomy

Cross-tabulate by:

```text
n1 action kind → continuation-optimal action kind
(TakeTokens/BuyMarket/BuyReserved/ReserveMarket/ReserveDeck/Pass)
```

and by stage:

```text
early 1–20 / mid 21–45 / late 46+  (1-based decision ply)
```

All descriptive; no gates.

## Implementation plan

Minimal footprint, maximum reuse:

```text
docs/m47s-residual-target-feasibility-diagnostic.md   (this file)
Rust batch analyzer or scripts/m47s_residual_target_audit.py
    reusing: M42S analyze-replay-player-view path,
             M42S authoritative identity pipeline,
             M46A frozen test-root manifest
benchmarks/m47s-residual-target-feasibility-v1.result.json
```

Execution sequence (authorized after the design-only commit):

```text
design-only commit
→ bind M46A test corpus
→ analyze n1/n200/n500/n2000
→ authoritative identity/action-set audit
→ compute F1/F2/F3
→ tracked result
→ docs/handoff
→ commit + push
→ return to strategy review
```

## Final audit requirements (fail closed)

```text
M46A test roots == 2048
game seeds == frozen range 6_602_304..6_602_559
root identity digest matches M46A test manifest
2048 / 2048 roots analyzed
sample_seed = 20_260_703, sample_count = 4, depth = 1
budgets exactly 1 / 200 / 500 / 2000
canonical legal-action sets identical across budgets
all action utilities present; all optimal sets non-empty
authoritative root identities unique
F1/F2/F3 recomputed from raw per-root records; summary exact
no training, no checkpoint, no Arena
```

## Iteration log

### Design — 2026-09-07

- Created under explicit user authorization (design + offline execution
  authorized; training/Arena/M48A/M48B not authorized).
- Corpus, budgets, tie-aware definitions, F1/F2/F3 gates, descriptive
  diagnostics, scientific boundary, and verdict semantics all frozen by the
  user ruling before any analysis ran.

### Execution — 2026-09-07

- Implementation: `m47s-residual` Rust batch command (replay + M46A shard
  root selection → four budgets per root, full per-action utilities,
  cross-budget canonical action-set identity asserted, per-budget identity
  drift asserted, canonical-order cross-check) + orchestrator/audit scripts.
- Execution: 256 games × 8 roots × 4 budgets in 219.4s. Root identity digest
  recomputed from the run matches the M46A test manifest exactly
  (`3efa584b...`); 2,048 identities unique.
- Final audit: all recomputations (F1/F2/F3/legacy counts) match the tracked
  result; no training or Arena artifacts.

## Validation and evidence

```text
command: python scripts/m47s_residual_target_audit.py
result: VERDICT = RESIDUAL_TARGET_FEASIBLE; 219.4s
command: python scripts/m47s_final_audit.py
result: ALL CHECKS PASS (identity digest matches M46A; F1/F2/F3/legacy
  recomputed from raw records match; verdict consistent; no .pt artifacts)
```

- Tracked artifact:
  `benchmarks/m47s-residual-target-feasibility-v1.result.json`
  (SHA256: `56065c1a13933626efcc1aad5fceaaa74df21826e9c9e3ecc1ab757d4fa53a1d`).
- Raw per-root records: `local-artifacts/m47s-run/raw-records.json`
  (SHA256 bound in the tracked result provenance).

## Result and decision

**Verdict: `RESIDUAL_TARGET_FEASIBLE` — all three main gates passed with
wide margins.**

| Gate | Result | Threshold | Verdict |
|---|---:|---:|---|
| F1 incidence (n2000 optimal-set miss) | **27.78%** (569/2048) | ≥10% | **PASS** |
| F2 stability (stable/n2000) | **98.95%** (563/569) | ≥80% | **PASS** |
| F2 coverage (stable/all roots) | **27.49%** (563/2048) | ≥8% | **PASS** |
| F3 median normalized regret | **0.4604** | ≥0.05 | **PASS** |

Key findings:

- The correction target is dense (28% of roots, not 10%), almost entirely
  budget-stable (99%), and far from tie noise (median regret 0.46 — the n1
  choice is on average nearly the worst action under the n2000 teacher).
- Legacy canonical disagreement (28.6%) closely tracks the tie-aware rate
  (27.8%): the corrections are real preference reversals, not tie-break
  noise.
- Pairwise density: 4.72M teacher-strict pairs; n1 agrees on 89.9%, ties on
  4.1%, reverses on 6.1% → pairwise correction rate 10.1% — ample dense
  supervision for a future residual model.
- Static margin: median normalized static preference the residual must
  overcome is 0.115 (median raw 400k) — corrections are mostly local, not
  strong-preference overturns, though the tail reaches 1.14B.
- Taxonomy: the dominant correction is TakeTokens → ReserveMarket (121),
  then within-kind TakeTokens→TakeTokens (88) and ReserveMarket→ReserveDeck
  (41); corrections concentrate early (258 early / 203 mid / 108 late).

This establishes, under the frozen scientific boundary, that a dense,
  budget-stable, non-trivial imitable residual target exists between n1 and
  the champion continuation. It does NOT establish that imitating it adds
  playing strength — that question belongs to a future M48B Arena, if ever
  authorized.

## Known limitations and non-claims

- n2000 corrections are champion-continuation preferences, not ground truth;
  M47S cannot certify that imitating them adds playing strength (that is
  M48B's question, if ever authorized).
- The 10%/80%/8%/0.05 thresholds are strategy-review feasibility gates for
  opening a residual route, not claims about optimal training signal sizes.
- Results are specific to the frozen M46A test roots, the frozen n1 shell,
  and the champion continuation target.

## Next authorized gate

Strategy review of the `RESIDUAL_TARGET_FEASIBLE` verdict. A PASS opens
M48A's design stage (static-prior residual learnability gate) but does NOT
authorize M48A implementation; the M47S test roots remain a permanent
diagnostic holdout that M48A may never train or checkpoint-select on.
