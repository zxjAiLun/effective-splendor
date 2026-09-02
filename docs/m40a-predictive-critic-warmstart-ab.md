# M40A Player-View Predictive Critic Warm-Start A/B

```text
Milestone:      M40A
Title:          Player-View Predictive Critic Warm-Start A/B
Status:         DESIGN_FROZEN / IMPLEMENTATION_AUTHORIZED
Prior round:    M39A (COMPLETED_NEGATIVE / CLOSED — M39A_NO_IMPROVEMENT,
                final review ACCEPTED 2026-09-01)
Design review:  NEEDS_REVISION — P0 = 0, P1 = 4, P2 = 3 (2026-09-01);
                repaired in Revision 1 (772fd4c)
Rev 1 re-review: NEEDS_REVISION — P0 = 0, P1 = 2, P2 = 2 (2026-09-01);
                repaired in Revision 2 (09fd8ec)
Rev 2 final re-review: APPROVED — P0 = 0, P1 = 0, P2 = 0 (2026-09-01);
                design review CLOSED; implementation authorized
Design SHA:     09fd8ec
Baseline:       current main at draft time (7165f71)
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
    Value MSE      (V(s) − centered return), computed over every RETAINED
                   player-view state: self-play games contribute both
                   seats (both are learner-controlled); external-opponent
                   games contribute the learner seat only. Opponent-seat
                   states are never retained.
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
statistical unit   paired seed block
seed blocks        128  (seeds 8_100_000 .. 8_100_127)
rotations          2 per seed block
pairing            B vs A (identical seeds, identical rotations,
                   identical seat assignment)
block score        10_000 × mean(two-rotation scores) per arm
delta_i            score(B_i) − score(A_i)
test               one-sided 95% paired Student-t on the 128 deltas,
                   df = 127, critical value 1.656940343542 (frozen,
                   identical to M39A G2)
H1_PASS            lower_95(delta) > 0  AND  256/256 matches completed
                   AND  zero aborts / faults / non-terminations
```

This is the cleanest single instrument for the warm-start question. It
**cannot by itself** declare the route successful: B could overfit to
beating A.

**Project gates (route-level; the decision table uses H1 + the league
safeguard together)**:

```text
league safeguard   statistical unit = cross-opponent seed aggregate
                   (M39A G3 convention, shared-seed schedule)
                   seeds 8_200_000 .. 8_200_031 (32 blocks)
                   both A and B run the same 9-opponent M39A league set,
                   32 blocks × 2 rotations per pairing per arm
                   (9 × 32 × 2 = 576 matches per arm; 1,152 across both)
                   for each seed block i: delta_i = mean over the 9
                   opponents of (score(B) − score(A)) on that block's
                   two rotations, equally weighted
                   test: one-sided 95% Student-t UPPER bound on the 32
                   aggregates, df = 31, critical value 1.695518782546
                   (frozen, identical to M39A G3 diagnostic)
                   league_FAIL iff upper_95 < 0 (significant evidence B
                   is weaker than A); otherwise league_PASS
                   NOTE: this is "no significant evidence B is weaker",
                   a route safeguard — NOT a formal zero-margin
                   non-inferiority claim
B vs M07           anchor diagnostic (report-only): seeds
                   8_300_000 .. 8_300_063, 64 blocks × 2 rotations
                   (128 matches; B only — no second arm is run). For
                   block i: score_i = 10_000 × mean(B's two-rotation
                   match scores), delta_i = score_i − 5_000 (positive =
                   B's win direction above the 50% anchor). Report the
                   mean delta and a TWO-SIDED 95% Student-t interval
                   over the 64 block deltas, df = 63, frozen critical
                   value 1.998340542521. No threshold; no decision-table
                   effect. (The M39A diagnostic gain is the comparison
                   anchor.)
B vs D2-v2         anchor diagnostic (report-only): seeds
                   8_400_000 .. 8_400_063, 64 blocks × 2 rotations,
                   B only, identical statistic (score_i − 5_000,
                   two-sided 95% t, df = 63, 1.998340542521). Does B
                   drift out of the initialization basin (M39A's
                   failure signature)? Report-only, no threshold.
```

Total formal Arena ≈ 1,664 matches — deliberately the same order as
M39A's formal evaluation; the 8 → 4 cycle reduction must not thin the
causal measurement (96 blocks would give ≈78% power at a true +10 pp
effect versus ≈88% at 128, per the frozen M39A power table).

**Checkpoint selection (frozen)**: all formal M40A gates evaluate the
**cycle-4 final** A and B checkpoints only. Cycles 1–3 are diagnostics
with no selection weight. No best-cycle selection, no result-dependent
rerun (M39A's winner's-curse rule, inherited verbatim).

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
VP-difference head E[clamp((VP_self − VP_opp)/15, −1, +1)]
                   (scalar, linear, trained with MSE; the M39A
                   normalization — the raw difference is a
                   presentation-only diagnostic, never the training
                   target; auxiliary)                        (1)
timing heads       P(self finishes within 2/4/8 own decision turns),
                   P(opp finishes within 2/4/8 own decision turns)
                   (six Bernoulli probabilities, sigmoid outputs)    (6)
```

- The `outcome` head doubles as the PPO value source (§1).
- The VP-distribution heads, VP-difference head, and timing heads are
  **auxiliary**: they are active in **both arms** during PPO (labels are
  derivable post-game from the replay; the M39A sidecar/materializer
  pipeline already provides the data), with the coefficients frozen in
  the PPO contract below.
- **VP support**: `k ∈ 0..30` (31 bins; the M39A observed maximum was
  22, so the support carries margin). A realized label `> 30` fails
  closed — **never silently clamp** — and aborts the dataset build.
- **Timing semantics (off-by-one frozen)**: `k = 2/4/8` counts the acting
  player's **own decision turns**, and **the tagged state's pending
  decision IS own-turn #1**. That is: `P(finish within k own decisions)`
  is true iff the player reaches 15 VP on or before their k-th decision
  from the tagged state (the decision about to be made counts as the
  first). Consequences, which the implementation must pin with unit
  tests:
  - **finish on the current decision**: if the action chosen at the
    tagged state itself completes 15 VP (a purchase that crosses the
    threshold), then the finish is within k=2 (and 4, and 8) — all three
    horizons are true;
  - **finish on the next own turn**: if the player cannot finish now but
    the opponent's reply leaves them a finishing purchase on their next
    decision, the finish is within k=2 but not within a hypothetical
    k=1;
  - **opponent next-turn finish**: the opponent-side heads use the same
    convention from the opponent's own next pending decision — the
    opponent's pending decision (one ply after the tagged one) is their
    turn #1.
  Global plies are never used as the timing unit.
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
stratification     COMPLETED games (4,095 of them) are split 80/20 at
                  game level, stratified by cycle (1..8) and opponent
                  bucket (random/heuristic/M07/league/self-play). The
                  terminal/truncated dimension is NOT a stratification
                  axis: M39A's formal data contains exactly ONE
                  truncated game (cycle-6 game 2785), which cannot be
                  split across train and validation without game-level
                  leakage. See the frozen truncation rule below.
honest sample size the 182,157 records are correlated prefixes of 4,096
                  games; the effective sample size is ~4,096. Any report
                  of offline metrics must state this; the 182k figure is
                  never to be presented as 182k independent samples
truncation rule    game 2785 (the single truncated game) is FORCED into
                  TRAIN and never appears in validation. Rationale: B
                  must have actually seen frozen cap-return supervision
                  at least once — otherwise M40A would claim truncation
                  pretraining support while never having trained on a
                  truncated state. Its records contribute VALUE MSE ONLY
                  (against the frozen cap-return); NO Outcome CE, no
                  final-VP CE, no VP-difference MSE, no timing BCE is
                  fabricated from the censored game.
frozen trunk       only heads update
```

**Deterministic stratified split rule (frozen)**: within each
`(cycle, opponent-bucket)` stratum of completed games, games are sorted
by ascending `game_index`; the validation quota is `round(0.20 ×
stratum_size)` computed with banker's rounding; the validation set is
selected by a deterministic stride — starting at index `floor(stratum_
size / 2)` and stepping by `ceil(1 / 0.20) = 5` positions in the sorted
list, wrapping once, until the quota is filled. Two compliant
implementations therefore select **the same validation games**. The
split RNG seed `40_260_901` is retained as the contract's identity
field (the rule above is fully deterministic and needs no draw, but the
seed pins the contract against silent re-specification).

**Validation truncated metrics**: held-out truncated V MSE/RMSE is
reported as `N/A` with `validation_truncated_games = 0` — never
computed from training data, never fabricated. Completed validation
metrics remain mandatory.

**Pretraining executor contract (frozen)**:

```text
split              deterministic game-level stratified split per the
                   frozen rule above: 80% train / 20% validation over the
                   4,095 completed games, stratified by cycle and
                   opponent bucket; the single truncated game (2785) is
                   forced into train; split identity seed 40_260_901
arm construction   A and B are created from ONE frozen head
                   initialization: a single torch.Generator seeded
                   20_260_829 (the M39A head-init seed) draws the head
                   weights once; the state_dict is COPIED to both arms.
                   The arms are never independently re-initialized.
B-only pretrain    trunk + policy head FROZEN (requires_grad False);
                   prediction heads only
optimizer          AdamW, lr = 3e-4, weight decay = 1e-4,
                   betas = (0.9, 0.999), eps = 1e-8, amsgrad = off,
                   foreach = off, fused = off — same flag set as the
                   M39A trainer
batch              512 records (padded tensors permitted; the logical
                   batch unit is the record)
epochs             exactly 16 — no early stopping, no best-epoch
                   selection; the epoch-16 head state is what B carries
                   into PPO
shuffle            deterministic per-epoch index permutation keyed on
                   (pretrain_seed, epoch), pretrain_seed frozen at
                   40_260_902
grad clipping      clip_grad_norm_ over the trainable (head) parameters
                   jointly, max_norm = 1.0
initializer        the head initializers are the M39A frozen semantics:
                   nn.init.kaiming_uniform_(weight, a=sqrt(5)) +
                   zeros_(bias) — i.e. fresh nn.Linear construction under
                   the seeded generator, exactly as M39A §5.3 defines
loss reduction     every predictive family is reduced by its INTERNAL
                   MEAN over the batch before summation:
                     outcome CE      — completed records only, mean
                     VP-dist CE      — mean over both heads combined
                     VP-diff MSE     — mean, target =
                                      clamp((VP_self − VP_opp) / 15,
                                            −1, +1)
                                      (the M39A normalization, inherited
                                      verbatim: raw VP-difference error
                                      reaches 5–15 and would dominate
                                      CE/BCE by orders of magnitude)
                     timing BCE      — mean over all 6 outputs combined
                     value MSE       — mean (completed: centered return;
                                       truncated: cap-return)
                   family means, not raw head-count sums, so the 6 timing
                     outputs do not get 6× the weight of the VP-difference
                     scalar
truncated masking  truncated records contribute VALUE MSE ONLY. They are
                   masked from: outcome CE, VP-distribution CE,
                   VP-difference MSE, and timing BCE — no label is
                   fabricated from the censored game
sanity metrics     report-only, never gates, never epoch selectors:
                   headline = held-out multiclass Outcome Brier on the
                   validation games (multiclass Brier = mean over
                   validation records of the summed squared error
                   between the 3-way predicted probability vector and
                   the one-hot realized outcome; lower is better;
                   computed on completed validation games only)
                   additionally required: held-out MSE and RMSE of
                   V = p_win − p_loss, reported in TWO columns —
                   completed games (vs the realized centered return)
                   and truncated games (vs the frozen cap-return); the
                   truncated column is reported as `N/A` with
                   `validation_truncated_games = 0` per the frozen
                   truncation rule (never computed from training data)
```

## A/B PPO contract (both arms identical)

Everything except the head-initialization history is shared and frozen.
**The two arms are a common-random-number pair by construction**: they
collect on the **same** seed blocks, the **same** rotations, the **same**
cycle-local bucket assignment and opponent schedule — the arms diverge
only through the policy behaviour the warm-start treatment induces.
Training-data randomness is thereby not a second treatment.

```text
policy init        M25-D2-v2 actor (unchanged from M39A)
collection         4 cycles × 512 games per arm, M39A §3.3 cycle-local
                  schedule, capped run-rollout entry (150-ply cap),
                  resident inference server
training seeds     SHARED by A and B: seeds 8_000_000 .. 8_001_023
                  (1,024 two-rotation blocks = 2,048 games per arm;
                  the same block list is replayed by both arms —
                  divergence comes only from policy behaviour)
                  disjoint from every M39A Arena/collection range and
                  from all M40A evaluation ranges below
trainer            M39A §5.3 execution contract verbatim (minibatch 512,
                  4 epochs, AdamW, betas (0.9, 0.999), eps 1e-8, wd
                  1e-4, joint grad-norm clip 1.0, entropy coefficient
                  0.010, value coefficient 0.500), with the cosine
                  schedule recomputed for 4 cycles and frozen here:
                    lr(c) = 1e-5 + 4.5e-5 · (1 + cos(π(c−1)/3))
                    c=1: 1.000000e-4  c=2: 7.750000e-05
                    c=3: 3.250000e-05  c=4: 1.000000e-05
                  one trainer_seed per arm? NO — one shared trainer_seed
                  40_260_830 (the M39A value): both arms shuffle
                  identically, keeping the PPO update stream paired
                  wherever the data streams coincide
arm B pretrain     per the frozen pretraining contract above (heads
                  only, 16 epochs, epoch-16 state carried into PPO)
evaluation         the four frozen contracts of §3, on the cycle-4
                  final checkpoints only
```

**PPO auxiliary coefficients (frozen)**: the three predictive families
new to PPO — VP-distribution, VP-difference, timing — are active in
**both arms** throughout PPO, each family reduced by its internal mean
(pretraining convention carried over), and sharing the **M39A total
predictive auxiliary coefficient budget of 0.250** as three equal parts:

```text
aux coefficient per predictive family = 0.250 / 3 = 1/12 ≈ 0.083333…
total predictive aux coefficient budget = 3 × 1/12 = 0.250 (the
                                          coefficient budget matches
                                          M39A's single 0.250 aux
                                          coefficient)
entropy 0.010 / value 0.500 / grad clip 1.0 / wd 1e-4 — inherited
```

The wording is deliberately "coefficient budget", not "gradient
pressure": equal coefficients do not mathematically guarantee equal
gradient magnitudes across differently-scaled families. The target
scales are made comparable by construction instead — the VP-difference
target uses the M39A normalization `clamp(ΔVP/15, −1, +1)` (identical
semantics in offline pretraining and online PPO; completed games use
final VP; truncated games are masked from this family), and the
VP-distribution and timing targets are probabilistic by construction.

**Outcome CE during PPO**: active in both arms on completed games only,
folded into the value coefficient's supervision (the value head is the
outcome head; its PPO loss is value MSE plus Outcome CE with the same
0.500 coefficient family, CE receiving weight 0.500 and MSE weight
0.500, both reduced by internal mean). Truncated games contribute value
MSE against the frozen cap-return only, and are masked from Outcome CE,
VP-distribution CE, VP-difference MSE, and timing BCE. Nothing about
this differs between arms.

**Checkpoint selection**: cycle-4 final checkpoints only (see §3); the
collection reports cycles 1–3 as a diagnostic learning curve with no
selection weight.

Cycles are reduced 8 → 4 deliberately: the M39A learning curve showed the
M07-relative diagnostic gain appearing early; a shorter schedule halves
the cost of the causal question and keeps cycle-8-style long-horizon
drift out of scope.

## Decision table (frozen)

```text
H1 pass + league-safeguard pass            -> M40A_WARM_START_CONFIRMED:
                                             predictive critic pretraining
                                             is the credited mechanism;
                                             M40B (Q/TD/CQL) is the
                                             designed next step
H1 pass + league-safeguard fail            -> M40A_IMPROVES_VS_A_ONLY:
                                             warm start overfits to the
                                             control arm; route warning
H1 fail                                    -> M40A_WARM_START_NO_EFFECT
                                             (valid negative; the licensed
                                             conclusion is the narrow one
                                             from §2 — head-only warm
                                             start on frozen D2 features
                                             did not help; predictive
                                             objectives are NOT thereby
                                             refuted)
any formal non-termination in evaluation   -> that measurement fails
                                             closed (recorded, no rerun)
evaluation checkpoints                     -> cycle-4 finals only;
                                             cycles 1–3 diagnostic, no
                                             re-selection
```

No gate change after observing outcomes; no result-oriented rerun; no
promotion. M07 remains champion regardless. The vs-M07 and vs-D2-v2
reports carry no threshold and never override the decision table.

## Lean iteration protocol (per the round authorization)

One design → one review → implementation with module tests → run offline
pretraining and both arms' 4-cycle experiments → review the Arena result.
No multi-round prereg document churn: this document is the whole design;
reviews append verdicts; discrepancies of fact are fixed in place with a
logged amendment note, as in M39A's incident/amendment practice.

Reuse (already reviewed machinery, re-linked not re-specified): resident
inference server, capped `run-rollout`, Rust materializer with join
validation, paired gate evaluator, provenance ledger discipline.

**Complete M40A seed allocation (frozen)**: the five Arena/collection
seed ranges are disjoint from every M39A Arena/collection/sampling range
(training `4_000_000..`, G2 `5_000_000..`, G3 `5_100_000..`, probe
`5_200_000..`, sampling `7_000_000..`) and from each other. The two
RNG-namespace seeds at the bottom are **intentionally inherited** from
M39A — they are generator namespaces, not fresh Arena seed ranges, and
their reuse is part of the contract (the PPO trainer namespace is shared
so both arms shuffle identically; the head-init namespace reproduces the
M39A initialization semantics):

```text
A/B shared training   8_000_000 .. 8_001_023   (1,024 blocks × 2 rot)
H1 evaluation         8_100_000 .. 8_100_127   (128 blocks × 2 rot)
league safeguard      8_200_000 .. 8_200_031   (32 blocks × 2 rot × 9)
vs-M07 report         8_300_000 .. 8_300_063   (64 blocks × 2 rot)
vs-D2-v2 report       8_400_000 .. 8_400_063   (64 blocks × 2 rot)
split RNG             40_260_901  (pretrain split identity; new)
pretrain shuffle      40_260_902  (new)
PPO trainer           40_260_830  (INTENTIONALLY INHERITED from M39A;
                                   shared RNG namespace, both arms)
head initialization   20_260_829  (INTENTIONALLY INHERITED from M39A;
                                   single draw, state_dict copied to A/B)
```

## Resolved design-review items (2026-09-01, adjudicated by the reviewer)

The four open items of the draft were adjudicated directly by the design
review and are now frozen:

1. **VP support = `0..30`** (not shrunk to 0..25): the extra 5 logits per
   VP head cost almost nothing and give the online-PPO support a safe
   margin. A realized label `> 30` fails closed — never clamp.
2. **Timing horizons = `2/4/8` own decisions** (not 1/3/6): 1-turn labels
   are too sparse and terminal-nearby; 2/4/8 spans short/mid/far credit
   signals.
3. **Pretrain sanity headline = held-out multiclass Outcome Brier**,
   report-only — with the mandatory companion: held-out `V = p_win −
   p_loss` MSE/RMSE reported in separate completed/truncated columns.
   No sanity metric selects epochs or alters the formal run.
4. **H1 = 128 blocks × 2 rotations** (not 96): per the frozen M39A power
   table, 96 blocks give ≈78.4% power at a true +10 pp effect versus
   ≈87.9% at 128; the primary causal gate is not thinned to save 64
   matches.

## Design review — findings and disposition

Review of draft `7165f71`, 2026-09-01. Verdict **`NEEDS_REVISION —
P0 = 0, P1 = 4, P2 = 3`**. The three core design points (V definition,
truncation semantics, head-only warm-start boundary) were accepted; the
repairs below are this revision.

| # | Severity | Finding | Disposition (where repaired) |
|---|---|---|---|
| P1-1 | P1 | A/B training on disjoint seed ranges contradicts "only difference is warm-start": training-sample randomness is a second treatment | Training seeds are now **shared common-random-number blocks** `8_000_000..8_001_023` (1,024 blocks × 2 rotations = 2,048 games/arm); shared trainer seed; all disjoint-range wording removed | §A/B PPO contract |
| P1-2 | P1 | Pretraining not an executable contract (no numbers for LR/epochs/split/batch/optimizer/reduction) | Full executor contract frozen: 80/20 stratified game split with seed `40_260_901`; single copied head state_dict (never re-initialized); AdamW 3e-4/wd 1e-4/betas/eps/flags; batch 512; exactly 16 epochs, no early stopping; deterministic shuffle seed `40_260_902`; grad clip 1.0; family-mean reductions; M39A initializer semantics | §Offline pretraining data contract |
| P1-3 | P1 | Gate statistics underspecified ("one-sided 95%" without unit; "not significantly weaker" undefined) | All four evaluation contracts frozen with statistical units, seed ranges, block counts, df, and frozen critical values (H1: 128 blocks, df=127, `1.656940343542`; league: 32 cross-opponent aggregates, df=31, `1.695518782546`, upper-bound rule, explicitly NOT a non-inferiority claim; M07/D2-v2: 64×2 report-only) | §3 |
| P1-4 | P1 | Checkpoint selection not frozen | Cycle-4 finals only; cycles 1–3 diagnostics; no best-cycle selection, no result-dependent rerun | §3 + decision table |
| P2-1 | P2 | "Value MSE, both seats" ambiguous vs learner-seat-only data contract | Rewritten as **retained-player-view** semantics: self-play contributes both seats; external-opponent games retain the learner seat only | §1 |
| P2-2 | P2 | Timing own-turn semantics had an off-by-one | Frozen: the tagged state's pending decision **is** own-turn #1; terminal-on-current-action, next-own-turn, and opponent-next-turn cases enumerated as mandatory unit tests | §Predictive head set |
| P2-3 | P2 | VP-bin out-of-range behavior and Brier reduction undefined | `>30` fails closed (never clamp); multiclass Brier defined exactly (summed squared error vs one-hot, completed validation games only); V MSE/RMSE split completed/truncated | §Predictive head set + pretrain sanity |

Delivery-clarification recorded: `handoff.md` is a **local-only, gitignored
working file** (`.gitignore:12`); statements about "updating handoff" refer
to the local working copy and never to repository contents.

---

## Revision 2 — findings and disposition

Re-review of Revision 1 (`772fd4c`), 2026-09-01. Verdict
**`NEEDS_REVISION — P0 = 0, P1 = 2, P2 = 2`**. The previous review's
P1=4/P2=3 findings are all CLOSED (CRN training, 128-block H1, league
statistical unit, cycle-4-only, timing off-by-one, VP overflow, pretrain
executor). This revision is a final contract repair on two executor
boundary conditions and two reporting contracts — not a redesign.

| # | Severity | Finding | Disposition | Where |
|---|---|---|---|---|
| P1-1 | P1 | The 80/20 terminal-stratified split is unsatisfiable on real M39A data: the formal run contains exactly ONE truncated game (cycle-6 game 2785), which cannot be both game-level-leak-free and present in both train and validation; the mandatory truncated validation metric could be undefined | Game 2785 is **forced into TRAIN** (B must have seen frozen cap-return supervision at least once); the 4,095 completed games are split 80/20 stratified by cycle × opponent bucket only; truncated records are masked from every predictive family except value MSE; held-out truncated V MSE/RMSE reports `N/A` with `validation_truncated_games = 0` (never computed from training data); a fully deterministic per-stratum rounding/order rule (banker's-rounded quota, sorted by game_index, stride-5 selection from the midpoint) is frozen so two implementations select the same validation games | §Offline pretraining data contract |
| P1-2 | P1 | VP-difference loss on the raw difference (error scale 5–15) would dominate CE/BCE by orders of magnitude; `1/12`-per-family coefficients do not make the gradient scales comparable | Target redefined as the M39A normalization **`clamp((VP_self − VP_opp)/15, −1, +1)`** — identical semantics in offline pretraining and online PPO; scalar linear head + MSE; truncated games masked from this family; raw VP-difference is presentation-only, never the training target. Wording changed from "total auxiliary pressure" to **"total predictive auxiliary coefficient budget"** (equal coefficients are not a claim of equal gradient magnitudes) | §Predictive head set + pretrain loss + PPO aux |
| P2-1 | P2 | "B vs M07 / B vs D2-v2 paired delta interval" is not executable: only B's 64×2 matches are run, with no second arm to define the delta | Both diagnostics redefined as **anchor statistics**: `score_i = 10_000 × mean(B's two-rotation scores)`, `delta_i = score_i − 5_000`; report mean delta and a **two-sided 95% Student-t interval**, df = 63, frozen critical value `1.998340542521`; no threshold, no decision-table effect, no additional matches. The ambiguous "paired delta interval" phrasing is removed | §3 |
| P2-2 | P2 | The seed table claimed "all disjoint from every M39A range" while the same table intentionally reuses M39A's `40_260_830` (trainer) and `20_260_829` (head init) | Prose corrected: the five **Arena/collection seed ranges** are disjoint from every M39A Arena/collection/sampling range and from each other; the two **RNG-namespace seeds** are intentionally inherited from M39A (shared trainer namespace keeps both arms' shuffles paired; head-init namespace reproduces M39A's initialization semantics) and are labelled as inherited in the table | §Lean iteration protocol (seed table) + §A/B PPO contract |

All prior frozen decisions are retained unchanged.

---

## Revision 2 final re-review — APPROVED (2026-09-01)

Verdict **`APPROVED — P0 = 0, P1 = 0, P2 = 0`**. All four Revision 2
findings verified closed against `09fd8ec` (singleton truncation, VP
scale, anchor statistics, seed namespaces). Design review is **CLOSED**;
implementation is authorized.

One non-blocking arithmetic note (recorded here for the implementer, not
a document change): the deterministic per-stratum split rule yields
**823** completed validation games (7 cycles × 103 + cycle-6's 102, the
league stratum of cycle 6 having lost game 2785 from the completed pool),
hence 3,272 completed training games + the 1 forced truncated training
game = 3,273 training games; 3,273 + 823 = 4,096. Earlier delivery-report
approximations (`~3,276 / 819`) are not part of this document and must
not be used as implementation assertions — the frozen algorithm is the
sole authority, and the implementation tests pin the exact cardinalities.

Implementation scope, gates, and provenance requirements are as specified
in the authorizing review (recorded in the project handoff): predictive
heads, replay/materializer label extension with mandatory timing and
fail-closed tests, the frozen split with exact cardinality assertions,
B-only pretraining, the CRN PPO path, the four evaluation statistics, and
provenance binding design SHA `09fd8ec`. No frozen experimental constant
changes. Formal pretraining/PPO/Arena execution remains gated on
implementation review.

---

## Implementation iteration log

### 2026-09-02 — implementation preflight re-review verdict

Re-review of HEAD `555e373` (the B warm-start/pretrain/PPO-parent repair
commit): **`NEEDS_FIX — P0 = 0, P1 = 3, P2 = 1`**, formal run NOT yet
authorized. The training side (B warm-start entry, offline pretrain
provenance, PPO parent resolution) was **APPROVED** and frozen for this
round; the four findings were all in the formal evaluator:

- **P1-1 invalid relative imports** in the non-dry `evaluate` path
  (`from .m39a_collect ...` / `from .m40a_gates ...` from a top-level
  orchestrator) — would crash the real executor at the first H1 match
  while `--dry-run` hid it.
- **P1-2 no physical seat rotation** — `arm = spec["arms"][seat]` with a
  constant `("candidate", "baseline")` arms tuple meant r0/r1 were the
  same deterministic lineup; anchors/league hardcoded the arm at seat 0;
  result attribution hardcoded candidate=seat0. The ledger labels were
  legal while the physics was wrong.
- **P1-3 no M39A-grade resume/provenance** — existing
  `arena-report.json` was blindly trusted; config-only slots could wedge
  `_atomic_json`; ledgers existed only in memory; no run-manifest bound
  checkpoint/plan/schedule identity.
- **P2-1 `--device` not threaded** through anchor/league opponent
  construction (hardcoded `cuda`).

### 2026-09-02 — evaluator-only repair (this commit)

Scope fence: model / labels / losses / frozen split / materializer /
server identity / PPO trainer / CRN schedule / gate statistics and the
8 enriched offline batches are all untouched. Evaluator-only changes:

- New `training/m17_gpu/splendor_gpu/m40a_evaluator.py`: the single
  formal evaluation executor.
  - **Canonical physical rotation**: `rotated_agents(primary, secondary,
    rotation)` — r0 `[primary, secondary]`, r1 `[secondary, primary]`,
    `primary_seat = rotation`. H1 primary = B (candidate), secondary =
    A (baseline); M07/D2 anchors primary = B; league primary = the
    evaluated arm. Result attribution reads the primary outcome from
    seat `rotation`. Sidecar filenames follow the ACTUAL seat occupied
    by the M40A arm. Opponent action seed (`20_261_000 + seed`) is
    shared across paired rotations and A/B league arms per the CRN
    contract.
  - **Run manifest before execution** binding design SHA `09fd8ec`, plan
    hash, schedule hash, A/B cycle-4 file+semantic hashes, the four
    exact formal seed families, and executor identity (orchestrator +
    runtime source SHA-256s). Resume with a different identity fails
    closed.
  - **Resume provenance** (`_rebuild_slot`): existing reports are never
    blindly trusted — exact frozen config comparison (per-seat argv
    with the dynamic server port normalized to a loopback/dynamic-port
    contract), report format/game_id/player_count, seed commitment
    recomputation, per-seat agent identity (M40A arms by semantic hash,
    M07/m35a by frozen identities), outcome status, strict
    `verify-replay` referee verification, replay seed/fingerprint/
    result/`replay_final_hash` binding, and M40A sidecar
    arm/checkpoint/game_id binding per seat.
  - **Deterministic config-only recovery**: a config-only interrupted
    slot's stale config is rewritten and re-executed; replay/sidecar
    remains without a report fail closed (partial artifacts preserved
    for diagnosis). Deterministic non-termination fails the measurement
    closed (M40A has NO exempted slot).
  - **Persisted canonical ledgers** (`h1/league/m07/d2-ledger.json`)
    with EXACT identity-set validation (missing / duplicate /
    out-of-domain / extra rows all rejected; H1 additionally requires
    complementary perspective pairs), and the four ledger hashes bound
    into `m40a-final-evaluation.json` before the frozen gate statistics
    are called (statistics themselves unchanged).
  - `--device` fully threaded (no hardcoded `cuda` in opponent
    construction); `--smoke` runs the authorized non-formal scope (H1
    r0+r1 through the real servers) on smoke-only seed namespace
    `8_900_000` with a separate out-root and no gate statistics.
- `training/m17_gpu/m40a_run.py`: the invalid relative imports and the
  old in-file match builders are gone; `cmd_evaluate` now drives the
  evaluator; `REPO_ROOT` added for runtime-source hashing. The logical
  schedule and its hash are UNCHANGED (`a0a38563…`).

**Validation evidence (all executed)**:

- `pytest training/m17_gpu/tests/test_m40a_evaluator.py
  training/m17_gpu/tests/test_m40a_orchestrator.py` — 39/39 passed
  (33 new evaluator contract tests: rotation contracts for H1/anchors/
  league, non-dry path through the real helpers, same-identity resume
  rebuild, fail-closed on checkpoint/seed/rotation/lineup/sidecar/
  report tampering and manifest drift, config-only recovery,
  partial-artifact rejection, ledger identity-set rejections, ledger
  hash content-addressing, dry-run count re-assertion, schedule-hash
  stability).
- Full Python regression from repo root: 286 passed / 7 failed — the 7
  failures reproduce identically on the unmodified baseline (stash
  verified): `test_compute_repair*` (hardware sensor environment) and
  `test_m39a_ledger*` (frozen exe SHA vs locally rebuilt binary);
  unrelated to this patch.
- `cargo fmt --all -- --check` exit 0; `cargo clippy --all-targets`
  exit 0; `cargo test --release` all suites ok, 0 failed.
- `evaluate --dry-run`: schedule hash `a0a38563
  ad308053c8068d29c763bb73d43e7274b9ab2898d429ca0bbad75eab` (unchanged),
  H1 256 / league 1152 / M07 128 / D2 128 / total 1664.
- Non-formal smoke (`evaluate --smoke --device cuda`, seed `8_900_000`):
  r0 config seats `[B, A]`, r1 `[A, B]`; report agent identities and
  sidecar filenames follow the swapped seats; with `winners=[1]`, r0
  candidate(B)@seat0 = loss and r1 candidate(B)@seat1 = win — the
  attribution follows the physical seat swap. No formal 8_1xx/8_2xx/
  8_3xx/8_4xx seed was consumed.
- Smoke resume: a second `--smoke` run rebuilt both slots through the
  full provenance chain and reproduced the H1 ledger hash bit-for-bit
  (`f41192fa…`). Adversarial resume checks: tampered winners rejected
  (report/replay result mismatch), drifted B checkpoint rejected,
  modified orchestrator source rejected at the run-manifest gate.

The 8 enriched offline batches were NOT regenerated; they remain valid
inputs (materialization untouched).
