# M40A Player-View Predictive Critic Warm-Start A/B

```text
Milestone:      M40A
Title:          Player-View Predictive Critic Warm-Start A/B
Status:         PROPOSED / DRAFT_PENDING_REVIEW
Prior round:    M39A (COMPLETED_NEGATIVE / CLOSED — M39A_NO_IMPROVEMENT,
                final review ACCEPTED 2026-09-01)
Design review:  user pre-draft decisions 2026-09-01 (three frozen points below)
Baseline:       current main at draft time
Champion:       M07 (determinization-s4-d1-n2000-v1) — unchanged
Promotion:      NONE (this round does not seek promotion)
```

## Problem and motivation

M39A's negative result decomposed into: a **diagnostic** +5.3 pp gain vs
M07 (127 complete G2 blocks) alongside a **formal** league regression
(−86.81 bps aggregate; the worst single deficit was against the round's
own initialization, D2-v2, at −937.5 bps). The carried-forward hypothesis:
with a single terminal outcome label per ~45-decision game, the critic is
the credit-assignment bottleneck — outcome-only returns are too sparse to
tell "front-loaded resource building" from "slow drift out of the
initialization's basin".

This round tests the **shortest discriminating step**: does a critic whose
predictive heads are **pre-trained offline** on M39A's own game data
improve PPO's credit assignment, versus an **identical architecture with
identical random initialization** that goes straight into PPO?

Explicitly informed by the Mortal experience (author-reported: PPO
actor-critic never improved; several auxiliary tasks showed no clear
benefit), this round does **not** assume auxiliary prediction helps. It
measures the one variable Mortal never isolated: warm-starting the
prediction heads on frozen features, under an otherwise identical PPO
contract.

Non-goals (deferred to a possible M40B, only if H1 passes):

- No `Q(observation, action)`, no TD targets, no target networks, no
  double Q, no CQL conservative penalty.
- No change to the environment reward, the return definition, or the
  policy architecture.
- No opponent modeling beyond the existing viewer-relative heads.

## The three frozen design points

### 1. PPO value definition and truncation handling

The outcome head emits a distribution over the centered-outcome alphabet:

```text
outcome head output:  [p_loss, p_draw, p_win]        (3-way softmax)
V(s)                  = p_win − p_loss               ∈ [−1, +1]
```

`V` defined this way is exactly the expectation of M39A's centered return
`{−1, 0, +1}`, so the existing GAE/advantage machinery carries over
unchanged. Training signals per game class:

```text
completed game:
    Outcome CE     against the realized W/D/L label
    Value MSE      (V(s) − centered return), both seats
truncated game:
    NO Outcome CE  — a capped game has no true W/D/L label and must not be
                     fabricated into one
    Value MSE only, against the frozen cap-return
                   −0.5 ± 0.5·tanh(ΔVP_cap / 4)   (M39A §5.2, unchanged)
```

### 2. Frozen boundary between pretraining and online PPO

Both arms start from **one and the same set of random head weights**
(drawn from a single frozen generator seed):

```text
A = shared random heads ────────────────► PPO (4 cycles × 512 games)
B = shared random heads → offline predictive pretraining → PPO (same)
```

- Offline pretraining (B only) updates **the prediction heads only**; the
  shared trunk and the policy head are frozen. This is deliberate: the
  question is whether head-only warm start on D2-frozen features helps,
  not whether fine-tuning features helps.
- Entering PPO, **both arms unfreeze the trunk** and train with identical
  losses, learning rates, schedules, and auxiliary weights. There is no
  separate "pretrain then freeze head" arm.
- Therefore the **only** difference between A and B is whether the heads
  received offline pretraining. If the experiment fails, the licensed
  conclusion is narrowly: *"head-only warm start on the frozen D2
  representation did not improve PPO under this contract"* — not
  "predictive objectives are useless".

### 3. Hypothesis gate vs project gates (separated)

**H1 — the causal hypothesis gate (primary)**:

```text
B vs A direct paired measurement (identical seeds, rotations,
opponent schedule): one-sided 95% paired lower bound > 0.
```

This is the cleanest single instrument for the warm-start question. It
**cannot by itself** declare the route successful: B could overfit to
beating A.

**Project gates (route-level, all reported; the decision table uses H1 +
the league/D2 gates together)**:

```text
B vs A            paired lower bound > 0            (H1, causal)
B vs league       not significantly weaker than A   (prevents
                  "beat A, regress vs everyone else")
B vs M07          direction + interval reported     (no threshold; the
                  M39A diagnostic gain is the comparison anchor)
B vs D2-v2        reported: does B drift out of the initialization
                  basin (M39A's failure signature)?
```

Deterministic non-termination handling: the known `D2-v2 vs M07 /
seed 5_000_029 r0` non-termination is **historical evidence, not a shared
baseline slot** — M40A's A and B arms each run their own fresh paired
measurements against M07 with new seed ranges. Any new non-termination in
any formal measurement fails that measurement closed, per the standing
M35A/M39A convention.

## Predictive head set (architecture frozen)

All heads read the (frozen-during-pretraining) shared state embedding and
are player-view-only:

```text
outcome head       [p_loss, p_draw, p_win]                          (3)
final-VP heads     P(self final VP = k), P(opp final VP = k),
                   k ∈ 0..30 (two 31-way softmaxes)                 (62)
VP-difference head E[final VP difference]  (scalar, linear,
                   trained with MSE against the realized
                   difference; auxiliary)                             (1)
timing heads       P(self finishes within 2/4/8 own decision turns),
                   P(opp finishes within 2/4/8 own decision turns)
                   (six Bernoulli probabilities, sigmoid outputs)    (6)
```

- The `outcome` head doubles as the PPO value source (§1).
- The VP-distribution heads, VP-difference head, and timing heads are
  **auxiliary**: they are active in **both arms** during PPO (labels are
  derivable post-game from the replay; the M39A sidecar/materializer
  pipeline already provides the data), with one frozen coefficient each.
- `k = 2/4/8` counts **the acting player's own decision turns** from the
  tagged state, not global plies. A player who has just moved does not
  get their own next move counted at global-ply distance 2.
- Label provenance (all automatic, no hand-written strategy knowledge):
  outcome and final VP from the report; VP trajectories and finish
  events from the materializer's per-ply prestige reconstruction.

## Offline pretraining data contract

```text
source data        M39A formal run, cycles 1–8: all learner-seat
                  player-view states = 182,157 records (self-play games
                  contribute both seats; opponent-seat states are
                  excluded — they are M07/league-policy visitation
                  distributions, not learner-policy ones)
split unit         GAME-level only. No prefix of a game may appear in
                  both train and validation (prefix leakage is the
                  failure mode this rule exists to prevent)
stratification     split is stratified by cycle (1..8), opponent bucket
                  (random/heuristic/M07/league/self-play), and
                  terminal/truncated, so validation tracks the training
                  distribution
honest sample size the 182,157 records are correlated prefixes of 4,096
                  games; the effective sample size is ~4,096. Any report
                  of offline metrics must state this; the 182k figure is
                  never to be presented as 182k independent samples
truncated games    included with §1 semantics (value MSE only)
pretrain objective sum of: outcome CE (completed only), VP-distribution
                  CE (both heads), VP-difference MSE, timing BCE (6),
                  value MSE (completed: centered return; truncated:
                  cap-return)
frozen trunk       only heads update
```

## A/B PPO contract (both arms identical)

Everything except the head-initialization history is shared and frozen:

```text
policy init        M25-D2-v2 actor (unchanged from M39A)
collection         4 cycles × 512 games per arm, M39A §3.3 cycle-local
                  schedule, capped run-rollout entry (150-ply cap),
                  resident inference server
seeds              per-arm frozen ranges, disjoint from each other and
                  from all M39A ranges; A and B collect on DIFFERENT
                  seeds (independent rollouts) but are EVALUATED on
                  identical seeds/rotations/opponents
trainer            M39A §5.3 execution contract verbatim (minibatch 512,
                  4 epochs, AdamW), with the cosine schedule recomputed
                  for 4 cycles and frozen here:
                    lr(c) = 1e-5 + 4.5e-5 · (1 + cos(π(c−1)/3))
                    c=1: 1.000000e-4  c=2: 7.750000e-05
                    c=3: 3.250000e-05  c=4: 1.000000e-05
                  identical aux coefficients in both arms
arm B pretrain     as §2: heads only, frozen trunk, its own frozen LR
                  and epoch budget, validated on the held-out game split
evaluation         paired A vs B (H1), plus the project-gate table
```

Cycles are reduced 8 → 4 deliberately: the M39A learning curve showed the
M07-relative diagnostic gain appearing early; a shorter schedule halves
the cost of the causal question and keeps cycle-8-style long-horizon
drift out of scope.

## Decision table (frozen)

```text
H1 pass + league-gate pass                -> M40A_WARM_START_CONFIRMED:
                                             predictive critic pretraining
                                             is the credited mechanism;
                                             M40B (Q/TD/CQL) is the
                                             designed next step
H1 pass + league-gate fail                -> M40A_IMPROVES_VS_A_ONLY:
                                             warm start overfits to the
                                             control arm; route warning
H1 fail                                   -> M40A_WARM_START_NO_EFFECT
                                             (valid negative; the licensed
                                             conclusion is the narrow one
                                             from §2 — head-only warm
                                             start on frozen D2 features
                                             did not help; predictive
                                             objectives are NOT thereby
                                             refuted)
any formal non-termination in evaluation  -> that measurement fails
                                             closed (recorded, no rerun)
```

No gate change after observing outcomes; no result-oriented rerun; no
promotion. M07 remains champion regardless.

## Lean iteration protocol (per the round authorization)

One design → one review → implementation with module tests → run offline
pretraining and both arms' 4-cycle experiments → review the Arena result.
No multi-round prereg document churn: this document is the whole design;
reviews append verdicts; discrepancies of fact are fixed in place with a
logged amendment note, as in M39A's incident/amendment practice.

Reuse (already reviewed machinery, re-linked not re-specified): resident
inference server, capped `run-rollout`, Rust materializer with join
validation, paired gate evaluator, provenance ledger discipline. All new
seed ranges are disjoint from every M39A range.

## Open items for the design review

1. VP-distribution support `k ∈ 0..30` — 31 bins cover the observed
   maximum (22 in M39A) with margin; confirm or shrink to 0..25.
2. Timing horizon choice `k = 2/4/8` own-turns — confirm these three
   horizons, or substitute 1/3/6 for finer near-term threat resolution.
3. Pretrain validation metric for the "pretraining worked offline" sanity
   check: proposed = validation Brier score on held-out games for the
   outcome head only (report, not gate).
4. Exact evaluation seed counts for the four project-gate measurements
   (proposed: A-vs-B 96 blocks × 2 rotations; league and M07 and D2-v2
   measurements sized per M39A G2/G3 conventions but at reduced scale
   appropriate to a 4-cycle round).
