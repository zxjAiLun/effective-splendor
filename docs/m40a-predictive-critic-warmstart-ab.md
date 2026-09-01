# M40A Player-View Predictive Critic Warm-Start A/B

```text
Milestone:      M40A
Title:          Player-View Predictive Critic Warm-Start A/B
Status:         PROPOSED / REVISION_1 / PENDING_RE_REVIEW
Prior round:    M39A (COMPLETED_NEGATIVE / CLOSED — M39A_NO_IMPROVEMENT,
                final review ACCEPTED 2026-09-01)
Design review:  NEEDS_REVISION — P0 = 0, P1 = 4, P2 = 3 (2026-09-01);
                findings repaired in Revision 1 (this document)
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
B vs M07           diagnostic report: seeds 8_300_000 .. 8_300_063,
                   64 blocks × 2 rotations (128 matches), paired
                   delta interval reported, no threshold (the M39A
                   diagnostic gain is the comparison anchor)
B vs D2-v2         diagnostic report: seeds 8_400_000 .. 8_400_063,
                   64 blocks × 2 rotations, paired delta interval
                   reported, no threshold — does B drift out of the
                   initialization basin (M39A's failure signature)?
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
stratification     split is stratified by cycle (1..8), opponent bucket
                  (random/heuristic/M07/league/self-play), and
                  terminal/truncated, so validation tracks the training
                  distribution
honest sample size the 182,157 records are correlated prefixes of 4,096
                  games; the effective sample size is ~4,096. Any report
                  of offline metrics must state this; the 182k figure is
                  never to be presented as 182k independent samples
truncated games    included with §1 semantics (value MSE only)
frozen trunk       only heads update
```

**Pretraining executor contract (frozen)**:

```text
split              deterministic game-level stratified split, 80% train /
                   20% validation, stratified by cycle (1..8), opponent
                   bucket, and terminal/truncated; split RNG seed
                   frozen at 40_260_901 (new, disjoint from all other
                   ranges)
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
                     VP-diff MSE     — mean
                     timing BCE      — mean over all 6 outputs combined
                     value MSE       — mean (completed: centered return;
                                       truncated: cap-return)
                   family means, not raw head-count sums, so the 6 timing
                   outputs do not get 6× the weight of the VP-difference
                   scalar
sanity metrics     report-only, never gates, never epoch selectors:
                   headline = held-out multiclass Outcome Brier on the
                   validation games (multiclass Brier = mean over
                   validation records of the summed squared error
                   between the 3-way predicted probability vector and
                   the one-hot realized outcome; lower is better;
                   computed on completed validation games only)
                   additionally required: held-out MSE and RMSE of
                   V = p_win − p_loss against the centered target,
                   reported in TWO columns — completed games (vs the
                   realized centered return) and truncated games (vs
                   the frozen cap-return)
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
                  disjoint from every M39A range and from all M40A
                  evaluation ranges below
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
auxiliary pressure of 0.250** as three equal parts:

```text
aux coefficient per predictive family = 0.250 / 3 = 1/12 ≈ 0.083333…
total predictive aux pressure         = 3 × 1/12 = 0.250  (unchanged
                                         from M39A's single 0.250 aux)
entropy 0.010 / value 0.500 / grad clip 1.0 / wd 1e-4 — inherited
```

This normalization is deliberate: M40A must not silently become "three
times the auxiliary gradient of M39A".

**Outcome CE during PPO**: active in both arms on completed games only,
folded into the value coefficient's supervision (the value head is the
outcome head; its PPO loss is value MSE plus Outcome CE with the same
0.500 coefficient family, CE receiving weight 0.500 and MSE weight
0.500, both reduced by internal mean). Truncated games contribute value
MSE against the frozen cap-return only. Nothing about this differs
between arms.

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

**Complete M40A seed allocation (frozen; all disjoint from every M39A
range — training `4_000_000..`, G2 `5_000_000..`, G3 `5_100_000..`,
probe `5_200_000..`, sampling `7_000_000..` — and from each other)**:

```text
A/B shared training   8_000_000 .. 8_001_023   (1,024 blocks × 2 rot)
H1 evaluation         8_100_000 .. 8_100_127   (128 blocks × 2 rot)
league safeguard      8_200_000 .. 8_200_031   (32 blocks × 2 rot × 9)
vs-M07 report         8_300_000 .. 8_300_063   (64 blocks × 2 rot)
vs-D2-v2 report       8_400_000 .. 8_400_063   (64 blocks × 2 rot)
split RNG             40_260_901  (pretrain 80/20 game split)
pretrain shuffle      40_260_902
PPO trainer           40_260_830  (shared M39A value, both arms)
head initialization   20_260_829  (single draw, state_dict copied to A/B)
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
