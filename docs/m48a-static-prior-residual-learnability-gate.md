# M48A — Static-Prior Residual Learnability Gate

```ini
MILESTONE = M48A
STATUS = DESIGN_ONLY_DRAFT / PENDING_REVIEW
SCOPE = design document only; no implementation, no training, no Arena
BASE_COMMIT = e0e4a44 (M47S permanently closed)
AUTHORIZATION = M48A DESIGN-ONLY AUTHORIZED (M47S terminal review)
IMPLEMENTATION = NOT AUTHORIZED
TRAINING = NOT AUTHORIZED
M48B_ARENA = NOT AUTHORIZED
M47S_HOLDOUT_USE_FOR_TRAINING_OR_SELECTION = FORBIDDEN
ARCHITECTURE_SWEEP = NOT AUTHORIZED (one model, one recipe)
EXTRA_RUN_AFTER_VALID_FAIL = NOT AUTHORIZED (neural evaluator research stops)
```

> **Research question.** With the StaticEvaluator kept intact and always
> providing the exact prior, can a learned residual improve over static —
> capturing part of the stable continuation-preference errors — without
> destroying static-correct decisions?
>
> $$q_{\text{corr}}(s,a) = q_1(s,a) + R_\theta(s,a)$$

## Problem and evidence

- M46A (closed, valid negative): the learned-replacement route failed — a
  357k-parameter successor representation given exact dynamics, exact
  terminals, explicit local relation primitives, and 4.2M scoring examples
  reached only 72.8% teacher-optimal-set fidelity. A neural network asked
  to re-derive the whole evaluator does not carry the n1 decision structure.
- M47S (closed, valid positive): on the frozen 2,048-root diagnostic
  holdout, n1/static and M07/n2000 continuation exhibit a dense (27.8%),
  highly budget-stable (98.9% of corrections), non-trivial (median
  normalized regret 0.46) residual action-preference target. Pairwise
  supervision is ample (4.72M teacher-strict pairs, 10.1% correction rate);
  static margins are mostly local (median normalized 0.115).

M48A therefore asks a different question from M46A: not "can a network
learn the evaluator," but "can a network learn only the evaluator's
errors, on top of an always-exact prior."

## Why this route deserves one more gate

The M47S margin shape is precisely the regime the residual hypothesis
predicts: ~90% of teacher-strict pairs are already correct under static;
~10% need correction; the corrections are mostly small local preference
flips (median normalized static margin 0.115), concentrated in specific
patterns (TakeTokens → ReserveMarket dominant, early-game concentrated)
that plausibly involve option value, denial, and reserve timing —
structure an immediate-successor scalar evaluator is poorly suited to
hand-write, but a residual might learn.

## Scope and non-goals

### In scope (design only at this stage)

- One frozen residual model, one frozen training recipe, one corpus
  contract, frozen offline gates.

### Not in scope / not authorized

- Retraining or replacing any part of StaticEvaluatorV1.
- Any Arena (M48B is a separate future authorization).
- Use of the M47S holdout for training or checkpoint selection.
- Architecture sweeps, loss sweeps, multiple runs after a valid FAIL.

## Contracts and invariants (design commitments)

### B1. StaticEvaluator is retained exactly

The final score is always `q_1(s,a) + R_θ(s,a)`. The M46A-style
replacement objective (network reconstructing the whole evaluator) must
not reappear under any framing. No production evaluator code changes.

### B2. Zero-init residual with bit-exact baseline gate

Before training, `R_θ(s,a) = 0` for every action. On a preregistered
audit corpus, the corrected action selection must be **100% bit-exact
equal** to n1/static selection. If this cannot be demonstrated:

```text
FAIL BEFORE TRAINING
```

### B3. M47S holdout is external final diagnostic only

The frozen roots (games 6,602,304–6,602,559, 2,048 roots) are a permanent
diagnostic holdout: never used for training, validation, or checkpoint
selection. M48A's training corpus reuses the **M46A train/val games**
(6,600,000–6,602,303), with offline n2000-teacher labels added; no new
self-play generation is required.

### B4. Success standard: improve over static, not reproduce n2000

The gates compare `static + residual` against `static` under the n2000
teacher:

- correction capture (fraction of static errors fixed),
- static-correct retention (fraction of static-correct decisions kept),
- overall optimal-set agreement (must improve),
- normalized regret (must decrease).

The binding constraint is **both**: fix errors AND do not destroy correct
static choices. Exact frozen thresholds will be set at design review with
the M47S distribution as prior (e.g. correction capture materially above
zero while retention stays near 100%); no threshold may be tuned after
seeing results.

### B5. One model, one recipe — terminal budget

This is the last neural-evaluator gate before a forced stop. A valid
frozen run that fails its gates ends the route:

```text
neural evaluator research = STOP
```

No M48A-v2, no attention variant, no bigger hidden, no loss sweep.

### B6. Scientific isolation: reuse the M46A trunk family

The residual network reuses the M46A successor relational trunk family
(not because M46A succeeded — it failed, but because reusing it makes the
only changed variable the presence of the static prior):

```text
M46A: R_θ must reconstruct everything        → FAILED
M48A: q_static + R_θ (prior retained)        → ?
```

If M48A learns where M46A could not, the clean conclusion is that the
strong exact prior fundamentally changes the learnability regime — not
that some new architecture happened to be better.

## Proposed experiment structure (to be frozen at design review)

### Corpus

- Reuse M46A train/val games (2,048 + 256), same root selection
  (8/game, `i_k = floor((2k+1)N/16)`), same authoritative identity
  pipeline.
- Offline labels: per-root, all canonical actions, n1 utility
  (`q_1`) and n2000 utility (`q_2000`) under the frozen shell
  (seed 20_260_703, count 4, depth 1) — the same recording contract as
  M47S.
- External final diagnostic: M47S holdout, untouched.

### Residual target (within-root, never absolute terminal probability)

Following the M47S review guidance, the training signal is a
within-root preference correction:

$$\Delta R \approx \Delta Q_{\text{champ}} - \Delta Q_{\text{static}}$$

i.e. pairwise/listwise losses on `q_1(a_i) + R_θ(a_i)` against the n2000
teacher's strict pairs — with a retention term anchoring teacher-agreeing
static pairs so correct decisions are not perturbed. Absolute terminal
win/loss regression is explicitly excluded (M43A/M46A lesson).

### Evaluation gates (directions frozen now; exact numbers at review)

On held-out roots (M46A val + M47S holdout as external):

```text
G0 bit-exact zero-init baseline (100%)
G1 correction capture improves over static (material, frozen threshold)
G2 static-correct retention ~ near-perfect (frozen threshold)
G3 overall n2000 optimal-set agreement improves vs static
G4 normalized regret decreases vs static
G5 SHIFT1-style color-binding sanity on the residual (no total-C shortcut)
```

### Execution discipline

- Single frozen run; checkpoint selection by frozen validation rule only
  (never the holdout).
- Fail-closed audits: action-set identity across budgets, identity
  digests, recomputation of every headline metric from raw records.
- One narrowly scoped implementation repair (bug/provenance/metric only)
  allowed before or during the run; nothing that changes architecture,
  corpus, thresholds, or seeds.

## Iteration log

### Design-only draft — 2026-09-07

- Created under M48A DESIGN-ONLY authorization from the M47S terminal
  review. No implementation, corpus, training, or evaluation exists.

## Validation and evidence

None yet. Design stage only.

## Result and decision

None yet.

## Known limitations and non-claims

- The n2000 teacher is a champion-continuation target, not ground truth
  (M42S: n2000-vs-n1 Arena UNRESOLVED). M48A success would establish
  learnability of the residual, not playing-strength benefit — that is
  exclusively M48B's question, if ever authorized.
- Reusing the M46A trunk family trades architectural exploration for
  scientific isolation; if the trunk itself is the bottleneck, M48A may
  fail for reasons not attributable to the residual hypothesis. This is
  an accepted, deliberate trade under the two-step terminal budget.

## Next authorized gate

Design review of this document. The review should freeze: exact gate
thresholds, the residual-target loss specification, corpus labeling
details, and the one-recipe numerics. Implementation remains NOT
AUTHORIZED until that review approves it.
