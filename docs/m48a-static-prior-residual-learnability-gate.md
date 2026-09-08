# M48A — Static-Prior Residual Learnability Gate

```ini
MILESTONE = M48A
STATUS = COMPLETED_NEGATIVE / VALID RUN FAIL — STATIC_PRIOR_RESIDUAL_NOT_VALIDATED
                (single valid run after one implementation repair; all 8 gates
                FAIL on both splits; VALIDATION_ROUTE_FAIL; per frozen terminal
                budget: neural evaluator research STOPPED)
SCOPE = full frozen contract; implementation auto-authorized after docs-only commit
BASE_COMMIT = e0e4a44 (M47S permanently closed)
DESIGN_V1 = 412d7a4 (research question / formulation / isolation accepted)
DESIGN_V2 = this document (corpus / loss / model / recipe / thresholds frozen;
            SHIFT1 demoted from gate to diagnostic per review)
IMPLEMENTATION = AUTHORIZED AFTER THIS DOCS-ONLY COMMIT
LABEL_GENERATION = AUTHORIZED AFTER THIS DOCS-ONLY COMMIT
CORPUS_AUDIT = AUTHORIZED AFTER THIS DOCS-ONLY COMMIT
SINGLE_FROZEN_TRAINING_RUN = AUTHORIZED AFTER THIS DOCS-ONLY COMMIT
VALIDATION_CHECKPOINT_SELECTION = AUTHORIZED AFTER THIS DOCS-ONLY COMMIT
INTERNAL_TEST_EVALUATION = AUTHORIZED AFTER THIS DOCS-ONLY COMMIT
M47S_HOLOUT_EVALUATION = AUTHORIZED AFTER THIS DOCS-ONLY COMMIT
TRACKED_RESULT = AUTHORIZED AFTER THIS DOCS-ONLY COMMIT
FINAL_AUDIT = AUTHORIZED AFTER THIS DOCS-ONLY COMMIT
ARENA_M48B = NOT AUTHORIZED
SECOND_TRAINING_RUN = NOT AUTHORIZED
ARCHITECTURE_CHANGE = NOT AUTHORIZED
HP_OR_LOSS_SWEEP = NOT AUTHORIZED
M48A_V2_AFTER_VALID_FAIL = NOT AUTHORIZED (neural evaluator research stops)
```

> **Research question.** With the StaticEvaluator kept intact and always
> providing the exact prior, can a learned residual improve over static —
> capturing part of the stable continuation-preference errors — without
> destroying static-correct decisions?
>
> $$q_{\text{corr}}(s,a) = q_1(s,a) + D(s)\,r_\theta(a)$$

## Problem and evidence

- M46A (closed, valid negative): the learned-replacement route failed — a
  357k-parameter successor representation given exact dynamics, exact
  terminals, explicit local relation primitives, and 4.2M scoring examples
  reached only 72.8% teacher-optimal-set fidelity. A network asked to
  re-derive the whole evaluator does not carry the n1 decision structure.
- M47S (closed, valid positive): on the frozen 2,048-root diagnostic
  holdout, n1/static and M07/n2000 continuation exhibit a dense (27.8%),
  highly budget-stable (98.9% of corrections), non-trivial (median
  normalized regret 0.46) residual action-preference target. Pairwise
  supervision is ample (4.72M teacher-strict pairs, 10.1% correction rate);
  static margins are mostly local (median normalized 0.115).

M48A asks: not "can a network learn the evaluator," but "can a network
learn only the evaluator's errors, on top of an always-exact prior."

## Formulation: root-normalized correction

To avoid training on StaticEvaluator's huge integer scale, the residual is
a **root-normalized correction**. Per root:

$$D(s)=\max\big(\max_a q_1(a)-\min_a q_1(a),\,1\big)$$

$$z_1(a)=\frac{q_1(a)-\operatorname{mean}_b q_1(b)}{D(s)}$$

The network outputs a dimensionless scalar $r_\theta(a)$; ranking uses:

$$z_{\text{corr}}(a)=z_1(a)+r_\theta(a)$$

This is exactly equivalent to $q_{\text{corr}}(a)=q_1(a)+D(s)\,r_\theta(a)$
— StaticEvaluator remains the exact prior; the network learns only the
correction relative to the current root's static preference range.

## Contracts and invariants

### B1. StaticEvaluator is retained exactly

The final score is always $q_1 + D\cdot r_\theta$. No replacement
objective, no mechanics heads, no progress reconstruction, no terminal
value loss, no absolute q2000 regression. No production code changes.

### B2. Zero-init residual with bit-exact baseline gate (G0)

The final residual head `Linear(128,1)` has weight **exactly 0** and bias
**exactly 0**; the rest of the trunk is randomly initialized under the
training seed. Before training, on ALL validation roots:

```text
every nonterminal residual scalar == exactly 0.0
every action residual             == exactly 0.0
q_corr float64                    == q1 float64 exactly
canonical selected action         == n1 action
```

all at 100%. Any failure: `FAIL_BEFORE_TRAINING`. No threshold loosening.

### B3. Corpus: four splits, no new self-play

No new games. The M46A train split is re-cut; labels are n1 + n2000 only
(M47S showed 98.95% of corrections are budget-stable, so n200/n500 are
unnecessary for training).

| Split | Games | Seeds (inclusive) | Roots | Use |
|---|---:|---|---:|---|
| Train | 1,792 | 6,600,000..6,601,791 | 14,336 | optimizer |
| Internal test | 256 | 6,601,792..6,602,047 | 2,048 | first true test (unseen at design time) |
| Validation | 256 | 6,602,048..6,602,303 | 2,048 | checkpoint selection |
| M47S external holdout | 256 | 6,602,304..6,602,559 | 2,048 | final replication |

Split by game seed BEFORE label generation. For all four splits re-verify
authoritative identity triples; because internal test is carved from the
old M46A train, re-assert ALL pairwise disjointness:

```text
train ∩ internal-test = 0    train ∩ val = 0
train ∩ M47S = 0            internal-test ∩ val = 0
internal-test ∩ M47S = 0     val ∩ M47S = 0
```

Successor semantic hashes likewise disjoint across splits. Any collision:
corpus FAIL — never delete samples after the fact.

### B4. Labels (n1 + n2000 only)

Per root, frozen shell (`sample_seed=20_260_703, sample_count=4,
depth=1`):

```text
n1:    max_nodes = 1
n2000: max_nodes = 2000
```

Recorded per root: all canonical actions, `q1(a)`, `q2000(a)`, the 4 exact
successors per action (relational features), terminal mask, root identity.
The M47S external holdout reuses the existing M47S raw records — no
recomputation.

### B5. Model: M46A trunk family, residual task only

Keep the M46A trunk (card relation MLP, noble relation MLP, player/global
MLP, SUM+MAX aggregation, 704→256→128, two residual blocks, LayerNorm)
but:

- delete mechanics heads;
- delete progress-reconstruction loss;
- do NOT load M46A checkpoints; fresh random init under the training seed;
- one residual scalar head `Linear(128,1)` with zero weight and zero bias.

Viewer-relative residual over the 4 exact successors per action:

$$u_\theta(s,p)=h_\theta(s,p)-h_\theta(s,1-p)$$

$$r_\theta(a)=\tfrac14\sum_{d=1}^{4}u_\theta(s'_{a,d},p)$$

If a determinization's successor is terminal: $u_\theta=0$ for it — the
exact terminal utility handles it; the residual never touches terminal
outcomes.

### B6. Loss: ranking residual objective (no absolute regression)

For each teacher-strict pair ($q_{2000}(a_i)\ne q_{2000}(a_j)$):

$$y_{ij}=\operatorname{sign}\big(q_{2000}(a_i)-q_{2000}(a_j)\big)$$

$$m_{ij}=y_{ij}\left[\frac{q_1(a_i)-q_1(a_j)}{D(s)}+r_i-r_j\right]$$

$$\ell_{ij}=\operatorname{softplus}(-m_{ij})$$

Pairs split into:

- **Correction pairs**: $y_{ij}\,(q_1(a_i)-q_1(a_j))\le 0$ (static tie or
  wrong direction);
- **Retention pairs**: $y_{ij}\,(q_1(a_i)-q_1(a_j))> 0$.

Total loss (group means summed, never pooled):

$$L=L_{\text{correction}}+L_{\text{retention}}+0.01\,L_{\text{anchor}}$$

$$L_{\text{anchor}}=\operatorname{mean}_a\, r_\theta(a)^2$$

Per root per epoch, at most **64 correction pairs and 64 retention pairs**
(oversampling resolved by deterministic hash
`hash(training_seed, epoch, root_identity, pair_indices)` without
replacement; fewer → use all). No hard-negative mining; no test-informed
sampling. The group-mean split exists because ~90% of strict pairs are
already static-correct — pooled averaging would make $R_\theta=0$ too
comfortable a local solution.

### B7. Training recipe (single, frozen)

```text
training seed = 48_000_001
optimizer     = AdamW, lr 1e-4, weight decay 1e-4,
                betas (0.9, 0.999), eps 1e-8
epochs        = 24
batch         = 32 roots
grad clip     = 1.0 (global norm)
dropout       = 0
scheduler     = cosine to final lr 1e-5
```

Excluded: mechanics loss, progress regression, terminal value loss,
absolute q2000 regression, action encoder, attention, pretrained M46A
weights.

### B8. Checkpoint selection (validation only)

Compute the static validation baseline first. An epoch with
`Retention_val < 99.0%` is not a normal candidate. Among candidates with
retention ≥ 99%:

```text
1. highest correction capture
2. highest overall optimal-set agreement
3. lowest mean normalized regret
4. earliest epoch
```

If no epoch of 24 reaches 99% validation retention: select the
highest-retention checkpoint for the record only, and set
`VALIDATION_ROUTE_FAIL = true` → M48A automatically FAILs. Internal test
and M47S holdout never participate in epoch selection.

### B9. PASS gates: eight checks across two splits

The selected checkpoint must pass ALL of the following on BOTH the
internal test AND the M47S external holdout:

| Gate | Definition | Threshold |
|---|---|---|
| G1 correction capture | among roots with $a_{n1}\notin A^*_{2000}$: fraction with $a_{\text{corr}}\in A^*_{2000}$ | **≥ 20%** |
| G2 retention | among roots with $a_{n1}\in A^*_{2000}$: fraction with $a_{\text{corr}}\in A^*_{2000}$ | **≥ 99.0%** |
| G3 agreement gain | $A_{\text{corr}}-A_{\text{static}}$ | **≥ +3.0 pp** |
| G4 regret reduction | $(\bar r_{\text{static}}-\bar r_{\text{corr}})/\bar r_{\text{static}}$ | **≥ 15%** |

(G2 does not require keeping the same canonical action — moving to another
teacher-optimal action in a multi-optimal set is not destruction.)

All eight (4 gates × 2 splits) pass:

```text
STATIC_PRIOR_RESIDUAL_LEARNABLE
```

Any failure:

```text
STATIC_PRIOR_RESIDUAL_NOT_VALIDATED
→ neural evaluator research = STOP
```

No M48A-v2. This is the terminal step of the two-gate budget.

### B10. SHIFT1: diagnostic only, NOT a gate

V1's G5 hard gate is REJECTED by review: the static prior already handles
F4/E2 color binding exactly, so the residual has no obligation to
re-encode it — forcing that would pull M48A back toward M46A's
replacement task. On the M47S holdout, still REPORT:

```text
true vs SHIFT1 bonus view:
  residual Δ distribution
  absolute residual response
  stratified by M45A F4-changing / E2-changing contexts
```

but with no must-change / must-have-correct-sign / must-exceed-X gates.

### B11. Scientific isolation (unchanged from V1)

M46A trunk family reused so the only changed variable is the static prior:

```text
M46A: R_θ must reconstruct everything  → FAILED
M48A: q_static + D·r_θ (prior retained) → ?
```

If M48A learns where M46A could not, the clean conclusion is that the
strong exact prior fundamentally changes the learnability regime.

## Non-claims (binding)

Even if all eight gates pass, M48A may claim only:

> static prior + learned residual shows stable offline improvement toward
> M07/n2000 continuation preferences on two frozen holdouts.

It may NOT claim "stronger than n1 in playing strength" — M42S left the
n2000-vs-n1 Arena advantage UNRESOLVED. Therefore:

```text
M48A PASS → M48B Arena worth running (not automatic promotion)
```

## Final audit requirements (fail closed, restrained)

```text
exact seed splits; root identity + successor-hash disjointness (all pairs)
n1 + n2000 exact configs; all canonical actions; all q values
M47S holdout never appears in train/val paths
G0 exact-zero prior gate
training recipe exact; 24 epochs exactly
checkpoint selection recomputed from validation
internal-test metrics recomputed from raw
M47S-holdout metrics recomputed from raw
static baseline metrics recomputed
G1/G2/G3/G4 exact on both splits
no second training run; no Arena
```

No peripheral test inflation.

## Execution sequence (auto-authorized after this commit)

```text
DESIGN_V2 docs-only commit
→ build n1/n2000 labels
→ corpus audit
→ G0 zero-init
→ one 24-epoch run
→ select by validation only
→ seal checkpoint hash
→ internal test
→ M47S holdout
→ final audit
→ result/docs/handoff
→ commit + push
→ return for final review
```

## Iteration log

### Design V1 — 2026-09-07 (`412d7a4`)

- Research question, static-prior formulation, zero-init invariant, corpus
  reuse strategy, single-run stop rule, and M46A trunk isolation all
  accepted by review.
- G5 (SHIFT1 hard gate) REJECTED by review → demoted to diagnostic.

### DESIGN_V2 frozen contract — 2026-09-07 (`c543658`)

- Review froze the complete contract in one pass: corpus re-cut (four
  splits incl. a genuinely unseen internal test carved from M46A train),
  n1+n2000-only labels, root-normalized residual formulation, trunk reuse
  with zero-init head, ranking-residual loss with correction/retention
  group means and 64+64 pair caps, single recipe (seed 48_000_001, 24
  epochs), validation-only checkpoint rule with 99% retention floor,
  G1–G4 thresholds (20% / 99% / +3pp / 15%) on BOTH internal test and M47S
  holdout, SHIFT1 as diagnostic, and the eight-check PASS semantics.
- No implementation exists yet. This revision is docs-only.

### Execution — Run 1 VOID — 2026-09-08

- Mid-run user review found three implementation defects: (1) the residual
  used the seat-0 viewpoint (`u[:,:,0]-u[:,:,1]`) instead of the frozen
  actor-viewpoint (`h(s,actor)-h(s,1-actor)`) — a contract violation that
  invalidates the run; (2) the no-candidate fallback was missing (would
  have crashed loading a nonexistent best.pt); (3) audit gaps (no
  successor-hash cross-split check for the re-cut splits; G0 only checked
  r==0 without full scoring equivalence; pair sampling used Python's
  process-seeded hash()). Run stopped at epoch 21; log preserved in
  `local-artifacts/m48a-run/run1-void/`. Run 1 VOID — not a valid run.

### Implementation repair (the one permitted) — 2026-09-08

- Actor viewpoint fixed in both training and evaluation residual paths.
- Route-fail fallback implemented: highest-retention checkpoint saved as
  `route-fail-checkpoint.pt`; when no epoch reaches the 99% floor it is
  evaluated for the record with `VALIDATION_ROUTE_FAIL = true`.
- Audit hardening: successor-state-hash disjointness re-asserted across
  the four NEW splits (1,503,060 / 220,324 / 214,700 / 222,452 unique,
  zero overlap); G0 extended to the full contract (r==0 ∧ q_corr==q1
  bitwise via the contract formula ∧ selected action == n1); pair sampling
  switched to SHA-256-derived deterministic seeds.
- Non-contractual performance repairs (user-directed GC investigation):
  removed all gc.collect() from hot loops (~213 full collections/epoch at
  ~1s each identified as the dominant cost); train pairs stored as compact
  numpy int16/int8 arrays instead of ~27.5M Python tuples (sampling parity
  verified identical: 64 roots × 4 epochs × 2 groups, selection
  bit-identical); validation batched per game; per-epoch phase timing and
  RSS tracking added. Model/batch composition/loss math/gates unchanged.
- One transient crash fixed before the valid run (pre-concatenated te_all
  indexing bug in the batched-train refactor); G0 false-fail fixed by
  checking q_corr with the contract formula (z-space round-trip loses
  precision).

### Execution — Run 2 (single valid run) — 2026-09-08

- G0 PASSED (full contract): 2048/2048 roots bitwise q-equality and
  action-equality; residual head exactly zero.
- Training: 24 epochs, seed 48_000_001; assembly 3,269,690 correction +
  24,279,127 retention pairs; phase totals data 1,044s / train 6,230s /
  val 249s.
- VALIDATION_ROUTE_FAIL: no epoch of 24 reached the 99% retention floor
  (best observed 0.854 at epoch 0, degrading to ~0.60 by late epochs). The
  highest-retention fallback checkpoint (epoch 0) was evaluated for the
  record per contract.
- All eight gates FAILED on both splits (numbers below). Verdict:
  `STATIC_PRIOR_RESIDUAL_NOT_VALIDATED`.
- Final audit: corpus manifest, G0, checkpoint-selection recomputation,
  static/corrected/gates recomputation from raw on both splits — all
  match; no Arena artifacts.

## Validation and evidence

```text
command: python scripts/m48a_generate_labels.py
result: labels complete; corpus audit PASS (identity + successor-hash
  disjoint across all 4 new splits)
command: python training/m17_gpu/m48a_train.py --device cuda
result: G0 PASS; 24/24 epochs; VALIDATION_ROUTE_FAIL; all 8 gates FAIL
command: python scripts/m48a_final_audit.py
result: ALL CHECKS PASS; tracked result written
```

- Tracked artifact:
  `benchmarks/m48a-static-prior-residual-learnability-gate-v1.result.json`
  (SHA256: `b63e9ae7b661c25a94b727572ef724da5487aef2063ef5bd97e8c97542605880`).
- Run artifacts: `local-artifacts/m48a-run/` (g0.json, label-manifest.json,
  epoch_metrics.json with phase timing, final_metrics.json,
  route-fail-checkpoint.pt, run1-void/).

## Result and decision

**Verdict: `STATIC_PRIOR_RESIDUAL_NOT_VALIDATED`.** The single valid run
failed all eight gates on both evaluation splits:

| Gate | Internal test | M47S holdout | Threshold |
|---|---:|---:|---:|
| G1 correction capture | 0.1584 | 0.1353 | ≥ 0.20 |
| G2 static-correct retention | 0.8363 | 0.8343 | ≥ 0.99 |
| G3 agreement gain | **−0.0684** | **−0.0820** | ≥ +3.0pp |
| G4 regret reduction | **−0.2053** | **−0.2020** | ≥ 15% |

(static baselines: internal test agreement 0.7041 / regret 0.1449;
M47S holdout 0.7222 / 0.1366.)

Observed facts (descriptive, no causal claims):

- The residual learned real corrections (capture 13–16%) but at a cost of
  destroying ~16% of static-correct decisions — retention never came close
  to the 99% floor in any epoch (max 0.854, degrading thereafter).
- The corrected policy is net WORSE than static on both splits: agreement
  down 6.8–8.2pp, mean normalized regret up ~20%.
- The retention loss term and 0.01 anchor did not constrain the residual
  to small, selective corrections under this frozen objective; the
  optimization steadily traded retention for capture across all 24 epochs
  (validation retention 0.854 → ~0.60 while capture 0.147 → 0.226).
- SHIFT1 diagnostic (no gates): residual response is near-zero on
  unchanged strata (median 0.0) with a small nonzero tail on F4/E2-changing
  strata (p90 ≈ 0.57–0.59, max 2.68) — the residual partially re-encodes
  color-adjacent structure, which the static prior already owns; this is
  consistent with the model learning overlapping rather than complementary
  corrections.

Per the frozen terminal budget (DESIGN_V2 B5): **neural evaluator research
= STOP.** No M48A-v2, no M48B, no architecture/HP variants. This closes
the two-gate residual budget opened after M47S: the residual target exists
(M47S, feasible and stable) but was not learnable into a net improvement
by the frozen static-prior residual model under this contract.

## Known limitations and non-claims

- The n2000 teacher is a champion-continuation target, not ground truth;
  the FAIL verdict concerns offline improvement toward n2000 preferences
  and makes no playing-strength claim in either direction.
- Reusing the M46A trunk traded architectural exploration for scientific
  isolation; the result is specific to the frozen model/recipe/loss. It
  does not prove that NO residual formulation could succeed — it proves
  this one, under the terminal budget, did not, and the budget rule
  forbids further attempts.
- Run 1's seat-0 viewpoint bug and its fix are documented; run-2 numbers
  are from the corrected implementation only.

## Next authorized gate

M48A is permanently closed. Per the M47S terminal review's budget rule,
the valid FAIL stops neural evaluator research entirely: M48A-v2, M48B,
any new neural evaluator milestone, Arena, and production changes are all
NOT AUTHORIZED. Strategy review may consider non-neural directions (e.g.
search/evaluator engineering) but no new milestone is opened by this
closure.
