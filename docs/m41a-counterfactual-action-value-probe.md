# M41A Player-View Counterfactual Action-Value Probe

```text
Milestone:      M41A
Title:          Player-View Counterfactual Action-Value Probe
Status:         PROPOSED / DESIGN_DRAFT_PENDING_REVIEW
Authorization:  DESIGN_DRAFT_AUTHORIZED / CODE_NOT_AUTHORIZED
                (2026-09-03; no run-branch, no corpus, no training
                before the design review passes)
Prior rounds:   M39A (COMPLETED_NEGATIVE / CLOSED — M39A_NO_IMPROVEMENT);
                M40A (COMPLETED_NEGATIVE / CLOSED —
                M40A_WARM_START_NO_EFFECT)
Design SHA:     (assigned at review approval)
Champion:       M07 (determinization-s4-d1-n2000-v1) — unchanged
Promotion:      NONE (this round seeks no promotion; it is a
                measurement round)
```

## Problem and motivation

M40A closed the head-only predictive warm-start route: pretraining
state-level predictive readouts (outcome / final-VP / VP-difference /
timing) on the frozen D2-v2 representation produced no detectable
causal benefit to the final PPO policy. The two post-mortems converge
on one structural diagnosis: **every M40A target was a function of the
state alone.** A model can predict "this position usually wins" with
perfect calibration and still have no information about "which legal
action causes a better future" — two actions from the same observation
share one V(s) baseline, and the action distinction is left entirely
to the sparse policy gradient.

M41A asks the next question directly, with the strongest possible
supervision and no RL machinery:

> **Under a strictly player-view input, given paired counterfactual
> continuation returns for EVERY legal action at an observation, can a
> model learn to rank actions — and does its argmax action produce a
> positive one-step causal improvement over the D2-v2 policy's own
> action, on unseen games?**

This is deliberately a probe, not a training method: no PPO, no TD, no
target networks, no bootstrapping. If exhaustive counterfactual
supervision fails here, TD/Q has no excuse to succeed later; if it
succeeds, we will have the first direct evidence that the network can
represent action value at all — the prerequisite any future fitted-Q /
TD round must establish first.

## Core design (one line)

```text
deterministic full-state branch teacher G_D2(s,a)
        → player-view action-value learner  E[G_D2(S,a) | O=o]
        → exhaustive legal-set centered advantage
        → F/U representation arms
        → sealed held-out one-step causal intervention
```

## 1. The branch teacher is deterministic

Splendor's randomness is exhausted by the opening game seed: the deck
order (including blind reserves and the noble order) is fixed at game
start, and no later stochastic source exists. The frozen D2-v2
continuation policy is pure argmax (no sampling), and the frozen
decision-seed namespace (`decision_seed`) is consumed only by
categorical sampling — argmax never draws. Therefore:

> **Given (source game seed, branch ply, forced action), the
> continuation is a deterministic function; the branch return is a
> single exact value, not a Monte Carlo sample.**

This is an assumption about the engine, not a fact to be trusted —
it becomes the hard gate **H0_BRANCH_DETERMINISM** (§7). If it fails,
M41A STOPs; there is no K-rollout / CRN / Monte-Carlo-averaging
fallback in this design. (The earlier draft's K continuation seeds are
removed precisely because determinism makes them meaningless.)

### 1.1 What the teacher computes

For a source full state `s` at the branch point (reconstructed from an
authoritative replay prefix), with legal set `L(s)`:

```text
G_D2(s, a) = terminal-or-cap centered return for the acting seat,
             after: forced action a at s, then BOTH seats play
             frozen D2-v2 to the end of the game.
```

- Completed branches: `win = +1 / draw = 0 / loss = −1` (viewer
  relative).
- Truncated branches (engine ply cap, frozen at the M39A/M40A value
  150 for source rollouts; see §5): the frozen cap-return
  `R = −0.5 + 0.5·tanh(d/4)` with `d = VP_self − VP_opp`, exactly the
  M39A/M40A contract. Truncated branches are NEVER excluded
  (action-dependent censoring would corrupt action comparison).

### 1.2 What the network learns

The teacher sees the full state; the network only ever sees the
player-view observation. The learnable object is therefore the
**player-view conditional expectation**

```text
Q_obs(o, a) = E[ G_D2(S, a) | O = o ]
```

Each corpus branch `(s_i, o_i, a_i, G_i)` is one hidden-world sample
of this conditional expectation (different source games with similar
observations correspond to different hidden worlds). The design does
NOT claim a single branch "is" Q(o,a). The irreducible gap between
`G(s,a)` and `E[G|o]` is the hidden-information floor of the
player-view setting — the same floor a mahjong model faces across
unseen wall/opponent-hand configurations.

### 1.3 Continuation world: Q^{D2,D2}

The continuation is **D2-v2 vs D2-v2 for both seats**, regardless of
who produced the source game. The measured quantity is therefore a
one-step policy-evaluation target inside the closed D2/D2 world:
"if we play `a` here and then let frozen D2-v2 finish both sides,
what is the return?" This is the cleanest self-consistent definition —
source distribution, baseline action, and continuation policy all
live in the same world (§3). It is NOT a claim about performance
against M07 or league opponents; those appear only in the report-only
OOD diagnostic (§10).

## 2. Source distribution: fresh D2-v2 self-play

The primary corpus sources are **fresh D2-v2 vs D2-v2 games**,
newly generated for M41A:

```text
source policy    = D2-v2 / D2-v2
baseline action  = the D2-v2 action actually taken at the branch state
continuation     = D2-v2 / D2-v2
```

Rationale: with the continuation frozen to D2/D2, using M07 or league
visitations as sources would put the branch states in a distribution
the continuation policy never generates, recreating exactly the
offline→online mismatch that contaminated M40A's interpretation.
M07 and league source states are retained ONLY as the Phase 6
report-only OOD diagnostic (§10).

Fresh seed namespaces (disjoint from every allocated range — M39A
4M/5.0M/5.1M/5.2M/7M; M40A 8_0xx/8_1xx/8_2xx/8_3xx/8_4xx/8_9xx):

```text
M41A source-game seeds      9_000_000 .. 9_000_000 + N_games − 1
M41A pilot seeds            9_100_000 .. (pilot games; NEVER enter
                             the formal train/val/test corpus)
```

(If the engine requires per-game unique seed integers only, a single
contiguous 9_0xx range for formal and a 9_1xx range for pilot suffice;
the exact allocation is frozen at P0 exit.)

## 3. Counterfactual target: exhaustive legal-set centering

For every selected source state `s` with legal set `L(s)` (the FULL
legal set — every action is branched, no sampling of actions), the
teacher computes `G(s, b)` for **all** `b ∈ L(s)`, and the target is
the legal-set centered advantage:

```text
A_cf(s, a) = G(s, a) − (1/|L(s)|) · Σ_{b∈L(s)} G(s, b)
```

The model `f_θ(o, a)` is centered with the same legal set:

```text
A_θ(o, a) = f_θ(o, a) − (1/|L(o)|) · Σ_{b∈L(o)} f_θ(o, b)
```

and the training loss is

```text
L = Huber( A_θ(o, a), A_cf(s, a) )     over all (state, action)
                                          training branches
```

This centering is the structural heart of M41A. A degenerate
state-only model (`f(o,a) = c(o)` for all a) has `A_θ ≡ 0` on every
legal set and cannot reduce the loss; the objective **forces action
dependence by construction**. This is the exact property M40A's
state-level heads lacked.

## 4. Model arms: F (frozen) / U (unfrozen) — both formal

One architecture, one initialization, one dataset, one objective; the
ONLY difference is the representation boundary:

| Arm | State encoder | Action encoder | Policy scorer | A(o,a) head |
|---|---|---|---|---|
| **F** | D2-v2, **frozen** | D2-v2, **frozen** | frozen / unused | new, trained |
| **U** | trained | trained | frozen / unused | new, trained |

- The action-value head is a small MLP over the existing joint
  representation `z(o,a) = concat(s_emb, a_emb, s_emb ⊙ a_emb)`
  (the same interaction form the policy scorer already uses), ending
  in a single scalar. **No other heads exist in M41A** — no outcome,
  no VP, no timing, no value, no CE. Multi-head engineering is
  explicitly over (§14 non-goals).
- U initializes the encoders FROM D2-v2 weights (not fresh random) —
  the question U answers is "must the representation ADAPT", and the
  natural null is the incumbent representation. U trains the encoders
  end-to-end with the A-head.
- Both arms go through the SAME formal causal intervention (§9), as
  two pre-registered hypotheses with familywise control
  (Bonferroni, one-sided α = 0.025 each, FWER = 0.05; §9.3).

The F/U pair turns the two M40A post-mortem explanations into an
experimental fork:

| F | U | Licensed reading |
|---|---|---|
| PASS | PASS | D2 representation already carries action-value information; M40A failed because its TARGET was state-level. Warm-start/aux-head route stays closed; action-value target works without representation change. |
| PASS | FAIL | Action-value target works frozen-in; unfreezing overfits or destroys it (dataset scale vs capacity). Route: frozen-representation value heads. |
| FAIL | PASS | Action-value target is right but requires representation adaptation — M40A's head-only boundary was doubly wrong (wrong target AND frozen trunk). Route: action-conditioned representation learning. |
| FAIL | FAIL | Action-value not validated under exhaustive supervision; TD/Q is NOT authorized. Next step is diagnosed by P4/P6 evidence (architecture expressiveness vs OOD), or STOP. |

## 5. Frozen contracts that are NOT implementation decisions

The following are frozen NOW and may not be decided during
implementation:

1. **Target definition**: `G_D2(s,a)` = deterministic D2/D2
   terminal-or-cap centered return; network learns `E[G|o,a]` via
   legal-set-centered Huber (§1, §3).
2. **Truncation**: never excluded; frozen cap-return formula
   `−0.5 + 0.5·tanh(d/4)` (both seats' mirror), ply cap = the frozen
   engine value used by M39A/M40A source rollouts (150). Excluding
   truncated branches would censor by action consequence and corrupt
   the comparison.
3. **Continuation**: D2-v2 vs D2-v2, both seats, always.
4. **F/U architecture boundary**: exactly as the table in §4
   (encoders frozen in F; encoders trained-from-D2-init in U; policy
   scorer frozen/unused in both; single scalar A-head in both).
5. **Test split**: source-game-level, sealed before training (§8).
6. **α / FWER**: one-sided α = 0.025 per arm, Bonferroni family
   FWER = 0.05, two pre-registered hypotheses.
7. **Causal delta**: `Δ = G(s, a_model) − G(s, a_D2)` on held-out
   states, aggregated per source game, tested across games (§9).
8. **Branch provenance schema**: §6.
9. **Non-goals**: §14.
10. **Statistical unit**: the source game, never the branch (§9.2).

## 6. `run-branch`: the one new infrastructure piece

Current engine capabilities cover full games from scratch
(`run-match`), capped rollouts (`run-rollout` with
prefix/report/replay), and strict replay/prefix verification
(`verify-replay`, `verify_rollout_prefix`). M41A needs one new Rust
command with a harder-than-usual provenance contract:

```text
splendor run-branch
    --source-replay <replay.json>          # authoritative source game
    --branch-ply <k>                       # acting decision index
    --forced-action <canonical action id>  # must be in the rebuilt
                                           # legal set, exactly once
    --report-out <branch-report.json>
    --replay-out <branch-replay.json>
```

Execution flow (each step fail-closed):

```text
source replay
  → strict verify (existing referee verification)
  → rebuild full state at branch ply from the replay prefix
  → bind branch-point identity (state hash, player-view observation
    hash, legal-set hash, acting seat)
  → validate forced action ∈ authoritative legal set, exactly once
  → apply forced action
  → D2-v2 vs D2-v2 continuation (both seats; resident inference —
    performance is part of the experiment contract, §11)
  → natural terminal OR frozen ply cap with cap-return
  → publish branch report + branch replay atomically
```

**Branch report provenance schema (frozen)**:

```text
format/version
source replay SHA-256
source game id, source seed, ruleset fingerprint
branch ply / request identity, acting seat
branch-point player-view observation hash
branch-point legal-action-set hash
forced action canonical identity
D2-v2 checkpoint file SHA-256 + semantic identity
continuation policy identity (D2-v2/D2-v2)
executor identity (binary SHA-256, runtime source SHAs)
terminal/cap status, centered return for the acting seat
result hash / final-state hash
branch replay SHA-256
```

**Information boundary**: the full hidden state exists ONLY inside the
Rust simulator teacher. It may be hash-recorded in provenance. It is
NEVER part of any model input, feature, or dataset field beyond the
hashes above. Model-visible data is exactly: player-view observation,
the ordered legal set, and the candidate action.

`run-branch` is its own reviewable engineering unit: implementation is
authorized only after this design review, and it ships with
determinism tests (H0), forced-action validation tests, and
provenance-schema tests.

## 7. Phase 0 — label/runtime/discrimination preflight (hard gates)

P0 uses 128 pilot states from ≥ 32 pilot games (pilot seed namespace
9_1xx; pilot games NEVER enter the formal corpus). NO training is
allowed in P0.

### H0_BRANCH_DETERMINISM (gate)

Re-execute a frozen set of pilot branches twice, complete pipeline,
identical inputs. Require, for every re-run branch:

```text
forced action applied identically
continuation action sequence identical
terminal/cap status identical
centered return identical
final-state hash identical
canonical replay identity identical (byte-identical replay file if
serialization is canonical; otherwise semantic identity field-by-field)
```

**Any mismatch: M41A STOPs.** No K-rollout补救, no "average it out" —
if the engine is not deterministic where the code says it should be,
we explain the nondeterminism first, or the round does not proceed.

### H1a_DISCRIMINATION_DENSITY (gate)

The deterministic teacher may reveal that most states have few
distinct branch returns (Splendor is frequently "all reasonable
actions win" or "all lose"). Measure on the 128 pilot states:

```text
fraction of states with ≥ 2 distinct G values across the legal set
fraction of states with best ≠ worst
mean / median |legal set|
best-vs-second G gap distribution
best-vs-D2-action G gap distribution
tie density (fraction of legal actions sharing the best value)
terminal vs cap branch rate
```

**Pre-registered stop rule**: if fewer than 25% of pilot states have
`best ≠ worst`, M41A STOPs with
`M41A_INSUFFICIENT_ACTION_DISCRIMINATION`. The one-step game
(splendor under D2/D2 continuation) does not offer enough action
signal to learn at this probe's scale. **Dense-reward rescue (adding
final-VP / turn-count / shaped utility to manufacture action
differences) is forbidden** — if the outcome signal is insufficient,
that is a finding about the game/policy pair, not a bug to paper
over. Rescuing it requires an M41A Revision with a re-designed
target, reviewed like any design change.

### H1b_RUNTIME_AND_POWER (gate)

Measure:

```text
mean branch wall-time (resident D2-v2 continuation)
mean branches per state (≈ mean |legal set|)
projected full-corpus wall-clock (N_source_games × 3 states ×
  |L| branches), and disk
pilot game-level Δ variance (Δ = best − D2 action per state,
  averaged per game — the exact statistic of the formal gate)
```

Pre-registered budget stop rules:

```text
formal test N (games) required for 90% power at one-sided α=0.025
  against the pilot SD, targeting +300 bps game-level improvement:
      if required N > 512 source games  → STOP / redesign
if projected full branch-corpus generation > 4 hours on this machine
  → STOP / optimize the EXECUTOR first (never shrink the sample to
     fit the budget)
```

The power calculation uses the corrected M40A lesson: the design-time
SD guess is not trusted; N is derived from pilot-measured game-level
SD at α = 0.025 (not 0.05), and the MDE at that N is reported before
any corpus generation begins.

### P0 exit

P0 exits with frozen numbers for: material-pair τ (§9.4), formal
N_source_games, per-split game counts, the seed allocation, and the
confirmed runtime budget. Everything else in this document is already
frozen.

## 8. Phase 1–2 — corpus infrastructure and generation

- **P1**: implement + review `run-branch` (§6) with its tests;
  validate provenance on pilot branches; then generate the FRESH
  D2-v2 self-play source games (seed namespace 9_0xx). Source games
  are ordinary capped `run-rollout` games (D2 vs D2, ply cap 150),
  fully verified replays.
- **P2**: for each selected source state (§ below), branch EVERY
  legal action. Output per state: observation, ordered legal set,
  `G(s,a)` for all a, plus provenance per branch.
- **State selection (frozen rule)**: at most 3 acting-decision states
  per source game, at the 25% / 50% / 75% quantiles of that game's
  acting decisions for the SELECTED seat, deterministic tie-breaking
  by ply index. (One seat per game — the acting seat at the branch
  point; the seat is part of the frozen selection rule: the seat with
  more acting decisions, tie-broken to seat 0.) If P0 shows the
  quantile states are pathological (e.g. overwhelmingly tied), a
  Revision may re-specify the rule — but only via design review,
  never mid-run.
- **Splits are source-game-level and SEALED**: train / validation /
  formal-test games are disjoint from the start. Formal-test branch
  labels are generated (they must exist for P5) but stored so the
  trainer cannot read them; only the final evaluator reads them.
  Model structure, epochs, optimizer, and any checkpoint selection
  use ONLY train/validation. The pilot games (9_1xx) never appear in
  any split.

## 9. Phase 5 — the formal causal intervention (primary gate)

On the sealed formal-test games (unseen by training in any form):

For each test state `s` (same 3-states-per-game rule), with the
teacher's exhaustive branch returns already computed:

```text
a_D2   = the D2-v2 source action at s (from the source replay)
a_F    = argmax_a A_F(o, a)     (F arm; argmax over the same legal set)
a_U    = argmax_a A_U(o, a)     (U arm)

Δ_F(state) = G(s, a_F) − G(s, a_D2)
Δ_U(state) = G(s, a_U) − G(s, a_D2)
```

Every Δ is a pure one-step substitution: same reconstructed state,
same hidden world, same deterministic D2/D2 continuation, only the
action at the branch point differs. This is the intervention M40A
(and the whole M39A→M40A line) never isolated.

### 9.2 Statistical unit (frozen)

```text
Δ_game = mean(Δ(state1), Δ(state2), Δ(state3))   per source game
```

tested across games with a one-sided paired t-test per arm. Branches
are NEVER independent units; `3 states × |L| actions` per game is one
game's contribution. Report in bps (×10,000) per project convention.

### 9.3 Hypotheses and familywise control (frozen)

```text
H_F : mean(Δ_game^F) > 0     one-sided α = 0.025
H_U : mean(Δ_game^U) > 0     one-sided α = 0.025
family: Bonferroni, FWER = 0.05
```

An arm PASSES iff its one-sided **97.5%** lower bound on the
game-level mean Δ is > 0 AND the domain is complete (every scheduled
test state executed; zero missing/duplicate; zero provenance
failures; zero result-dependent reruns). "Pass whichever looks
better" is pre-registered away by the Bonferroni split.

### 9.4 Secondary/diagnostic metrics (not gates)

- **Pairwise ranking** (diagnostic, two views): over all non-tied
  pairs (`G(a) ≠ G(b)`) and over **material pairs**
  (`|G(a) − G(b)| ≥ τ`), where τ is a practical-materiality threshold
  proposed from the P0 target distribution and frozen BEFORE any F/U
  training. τ is NOT a confidence/uncertainty quantity (the branch
  teacher is deterministic; cross-game hidden-world variance is not a
  per-pair uncertainty) — it only separates "differences that matter
  in scale" from ties.
- **Top-1 regret**: `G(s, a_oracle) − G(s, a_model)` where
  `a_oracle = argmax_a G(s,a)`; reported against the D2 baseline
  regret `G(s, a_oracle) − G(s, a_D2)`. Regret weights errors by
  consequence, unlike accuracy.
- **Centered-value error**: Huber/MSE on `A_cf` (the training
  objective, reported on validation) — descriptive only.

### 9.5 Action-ablation sanity gates (fail-closed)

Both arms must degrade materially under:

```text
(a) action embedding zeroed
(b) action assignment shuffled within the legal set
```

measured by pairwise ranking / top-1 regret on validation. If an arm
performs well normally but does NOT degrade under ablation, that arm
is a **pseudo-Q** (state recognition masquerading as action value)
and FAILS regardless of its intervention result. The legal-set
centering makes this near-impossible to pass accidentally — the
ablation check is the second, independent lock.

## 10. Phase 6 — OOD diagnostic (report-only)

A small set of branch states drawn from **M07 source games** and
**league source games** (existing artifacts; no new seeds consumed in
their ranges). The same branch pipeline runs on those states
(continuation remains D2/D2). Report: pair ranking, top-1 regret,
one-step Δ vs the source policy's action. NO gate authority — the
licensed conclusion of M41A is about the D2/D2 world; OOD behavior is
context for the next round's design, not a promotion claim.

## 11. Performance is part of the experiment contract

M40A's audit lesson is institutionalized: **no M41A phase may be
authorized without a measured runtime budget**, and the counterfactual
generator is designed resident-first:

```text
persistent D2-v2 inference servers (both seats)
one reconstructed source state per worker
ALL legal-action branches of a state inside one resident process
no per-branch process spawn, no per-branch checkpoint load
```

(If H0 determinism holds, branch execution is a pure deterministic
replay-plus-continuation; target throughput ≈ decisions ×
resident-inference latency, estimated orders of magnitude below
M40A's evaluation — to be CONFIRMED by P0 measurement, never
assumed.) Executor optimization is legitimate work BEFORE formal
generation; shrinking statistics to fit a time budget is not.

## 12. Known limitations

- **No hidden-state resampling**: the engine cannot, given a public
  history, resample consistent hidden worlds; M41A therefore does NOT
  directly measure player-view hidden-state irreducible uncertainty.
  The `E[G|o]` gap is learned across games, not measured per
  observation. If F/U both fail, a determinization-based belief probe
  is a candidate future round — with its own infrastructure review.
  (The earlier draft's "similar-observation sensitivity" proxy is
  removed: similar(o1,o2) conflates observation and hidden-world
  variation.)
- **D2/D2 world only**: conclusions live inside the frozen D2-v2
  self-play world; nothing here licenses claims about M07-relative
  strength.
- **One-step probe**: Δ measures a single-action substitution; it
  does not establish that iterating the argmax (a full policy)
  improves — that is the NEXT round's question, gated on this one.
- **Ply-cap world**: `G_D2` is the terminal-or-CAP return; the probe
  measures the capped game, by frozen decision (§5.2).

## 13. Decision table (pre-registered)

```text
At least one arm passes §9.3 (lower_97.5%(Δ_game) > 0, complete
domain, ablation sanity PASS)
    → M41A_ACTION_VALUE_VALIDATED
      + F PASS & U PASS:
          REPRESENTATION_ALREADY_SUFFICIENT — M40A's target was the
          problem; next round may discuss fitted-Q / TD evaluation
          on this representation (CQL still NOT auto-authorized).
      + F PASS & U FAIL:
          ACTION_VALUE_FROZEN_REP_ONLY — representation adaptation
          overfits at this data scale; next round stays frozen-rep.
      + F FAIL & U PASS:
          REPRESENTATION_ADAPTATION_REQUIRED — route opens
          action-conditioned representation learning.
Both arms FAIL
    → M41A_COUNTERFACTUAL_ACTION_VALUE_NOT_VALIDATED
      TD/Q/CQL NOT authorized. Next step chosen from P4/P6 evidence
      (architecture expressiveness vs distribution), or STOP.

Offline metrics look good but the formal intervention FAILs
    → M41A_OFFLINE_Q_NOT_CAUSAL
      suspect teacher/distribution mismatch; TD still NOT authorized.
P0 discrimination density < 25%
    → M41A_INSUFFICIENT_ACTION_DISCRIMINATION (STOP; no shaped-reward
      rescue without a reviewed Revision).
P0 determinism FAILs
    → M41A_ENGINE_NONDETERMINISM (STOP; explain or fix the engine
      first, with its own review).
P0 power/runtime budgets exceeded
    → STOP / redesign (or executor optimization), never sample
      shrinking.
```

No promotion in any branch. M07 remains champion. No
result-dependent rerun. No gate change after observing outcomes.

## 14. Non-goals (frozen)

- No Outcome / VP / Timing / CE / value heads (the multi-head era for
  this route is closed by M40A).
- No head warm-start experiments.
- No PPO, no RL training of any kind in this round.
- No TD, no target networks, no Double-Q, no CQL, no bootstrapping.
- No promotion, no champion challenge, no Arena strength claims.
- No best-epoch/best-checkpoint selection by test metrics (test is
  sealed; selection uses train/validation only).
- Branches are never independent statistical units.
- The full hidden state never enters model inputs (hashes only).
- **Logged-action-only supervision is forbidden**: training
  `Q(s, a_behavior) ← terminal return` on the action the source
  policy happened to take is NOT counterfactual Q-learning — M41A's
  definition requires the FULL legal set branched at every selected
  state. (This is the mahjong-CE lesson written as a hard rule: the
  same state must be asked about every action, not just the one that
  occurred.)
- No adding auxiliary targets mid-round to rescue a failing gate.

## 15. Phase structure and authorization ladder

| Phase | Content | Training? | Status |
|---|---|---|---|
| P0 | determinism + discrimination + runtime + power pilot (128 pilot states, seed 9_1xx) | NO | design-authorized, blocked on review |
| P1 | `run-branch` implementation + review; fresh D2/D2 source games (9_0xx) | NO | not authorized |
| P2 | exhaustive branch corpus + provenance validation + sealed splits | NO | not authorized |
| P3 | F/U training (sealed game-level split; U encoders init from D2-v2) | YES | not authorized |
| P4 | offline held-out ranking / regret / ablation sanity | eval only | not authorized |
| P5 | F/U formal one-step causal intervention (Bonferroni α=.025) | formal gate | not authorized |
| P6 | M07/league OOD diagnostic | report-only | not authorized |

Implementation of ANY phase requires the design review to pass and
explicit phase authorization. This document, and only this document,
is the current deliverable.

## 16. What this round would establish, in one sentence each

- **If it passes**: for the first time in this project, direct
  evidence that the network can answer "does changing THIS action make
  the future better" — the object M39A/M40A never measured — plus a
  clean fork on whether the incumbent representation already suffices.
- **If it fails**: exhaustive counterfactual supervision is
  insufficient for action-value learning in this architecture/world —
  the strongest possible negative prior against jumping to TD/Q, and a
  pointer (via P4/P6) at whether expressiveness or distribution is
  the wall.
