# M49B Off-Policy FQI Convergence Remediation

Status: **DESIGNED / PROPOSED — NOT AUTHORIZED TO EXECUTE** (owner authorized writing the
design; explicitly deferred launch because the GPU is currently training).
Baseline: `main@8149814997...` (design written on top of the M49A decline diagnosis
commits `2b54701` / `5e01286`).
Owner-date: 2026-09-26.

> Execution prerequisites (ALL required before any training starts):
> 1. Owner go-ahead on the specific arm set below.
> 2. GPU free (no other training running).
> 3. Frozen gates in this document unchanged after seeing any results.

## Problem and evidence

M49A's completed CUDA fast-iteration FQI run degrades on the frozen 64-seed
validation cohort from the selected peak iter20 (`61/64`, `J_val=37.6875`) to
iter80 (`41/64`, `J_val=61.8125`). The read-only diagnosis (docs §19; evidence
in ignored `local-artifacts/m49a-cuda-decline-diagnostics-20260926/`) established:

- **Global root-level policy shift, not a tail artifact.** All 64/64 seeds diverge
  at the first decision (`trace_iter20_vs_iter80.json` sha `cdbc4673…`, audit gate
  PASS). Failures are exclusively TurnCap (dithering), never Stalled.
- **Systematic value optimism.** Greedy min-Q (predicted cost-to-go) drifts down
  `~21 → ~17` at the root and `14.409 → 12.906` in the train backups while real
  performance worsens — the signature of minimization bias in the cost-space
  backup `y = c(a) + min_{a'} Q_target(o',a')`.
- **CUDA numerics ruled out.** TF32-off Rust-vs-CUDA target parity is FP32-exact
  (~1e-5); TF32-on noise ≤1.3e-2 is 2–3 orders below the drift and present at
  both iterations (`parity_late_checkpoints.json` sha `9651a7bd…`,
  `parity_train_and_tf32off.json` sha `3dc320a5…`).
- **OOD successor-action extrapolation is the dominant, cleanly-measured driver**
  (`probe_ood_vs_selection.json` sha `0e06cec3…`): 84.9% → 88.5% of train
  Running backups have their min-selected successor be an OOD (never-logged)
  action (val: 100%); only ~3.19% of successors are logged; restricting the min
  to in-support successors raises the backup by a clean median `0.539 → 0.712`
  and the effect grows with training. Min-selection bias is corroborated
  (two-checkpoint clip uplift `0.000 → 1.604`) but confounded by the drift and
  not cleanly isolated.
- **Structural facts.** `gamma = 1` is hard-coded (`compute_target` returns
  `step_cost + v_next` with no discount); loss is Huber (`F.smooth_l1_loss`);
  hard target refresh every 4 epochs; C2 Polyak `tau=0.05` was already **REJECTED**
  (iter40 `26/64`), so naive target smoothing is a closed path.

Root cause: the deadly triad (function approximation + bootstrapping + off-policy)
with the min operator selecting downward-biased Q on overwhelmingly unseen
successor actions, accumulated across refreshes under a non-contracting
(`gamma=1`) backup.

## Initial design

Three complementary levers, matched to the diagnosis. `1` attacks the confirmed
dominant cause (OOD extrapolation); `2` attacks the corroborated secondary cause
(min-selection bias); `3` restores contraction so residual error stops
accumulating. Naive target smoothing (Polyak) is excluded by C2.

### Lever 1 — Support-aware conservative backup (PRIMARY)

Make unseen successor actions look *expensive* so neither the label nor the
eval-time greedy argmin is dragged down by extrapolated-cheap OOD actions.

- **1a (primary form): CQL-style cost-space conservative regularizer.** Add to the
  training loss a term that penalizes Q being lower on non-dataset actions than on
  the logged dataset action for the same state. In reward-max CQL the term is
  `α·(logsumexp_a Q − Q_data)`; in our cost-min / greedy-argmin setting the
  pessimistic direction is to *raise* Q on non-dataset actions, i.e. minimize
  `α·(Q(s, a_data) − softmin_a Q(s,a))` (equivalently push `softmin_a Q` up toward
  the logged action's Q). This makes the net stop assigning spuriously-cheap
  cost-to-go to OOD actions, fixing both the label optimism AND eval-time OOD
  selection. Pre-register an `α` sweep `{0.5, 1.0, 5.0}` (coarse) and pick by the
  frozen gate, not by offline loss.
- **1b (ablation / cheap fallback): in-support-restricted bootstrap.** For Running
  transitions, take `v_next = min` over only in-support (byte-exact or
  near-neighbour to logged) successor actions. Every train Running transition has
  ≥1 in-support successor (verified), so it is well-defined. Cheap, but does NOT
  constrain Q on OOD actions at eval time, so it is an attribution ablation, not a
  standalone fix.

### Lever 2 — Clipped double-Q (SECONDARY anti-bias)

Maintain two Q networks with independent initialization. Bootstrap value uses the
pessimistic (cost-space MAX) of the two heads at the selected successor action:
`a* = argmin_{a'} min(Q1,Q2)(o',a')`, `V(o') = max(Q1(o',a*), Q2(o',a*))`.
This is the min-problem dual of clipped double-DQN and directly counters the
downward selection bias. Cost: 2× Q params + a second forward pass (modest).

### Lever 3 — Discount `gamma<1` (ORTHOGONAL stabilizer)

Change the Running backup to `y = step_cost + gamma · min_{a'} Q_target(o',a')`
with `gamma = 0.99` (pre-register `0.99`; optional arm `0.97`). Terminal targets
unchanged (reached15 → `step_cost + 0`; failure → `failure_penalty = 100`).
Episodes are ≤100 main turns, so `gamma=0.99` barely changes the optimal
turn-minimizing policy but makes the Bellman operator a `gamma`-contraction,
bounding error accumulation across refreshes.

### Pre-registered arms (attribution)

| arm | levers | purpose |
|-----|--------|---------|
| A0 | none | baseline = the completed M49A run (already have it; no re-run needed) |
| A1 | 3 only (`gamma=0.99`) | cheapest; isolate contraction effect |
| A3 | 1a (CQL `α*`) only | isolate the primary OOD lever |
| A4 | 1a + 2 + 3 | the full "123" stack (headline arm) |
| A1b | 1b only (in-support min) | optional ablation for OOD attribution |

Recommended minimal execution when authorized: **A1 first** (cheap sanity that
contraction alone helps), then **A4** (the full stack). A3 / A1b are attribution
ablations to run only if A4 succeeds and we want to apportion credit.

## Scope and non-goals

In scope: modifying the M49A FQI target math and trainer (γ, CQL penalty, second
Q head), rebuilding + hash-pinning any changed Rust target builder, unit tests,
re-running the Rust-vs-CUDA parity gate for the new backup, and evaluating with
the **unchanged** frozen selector on the **unchanged** frozen 64 val seeds.

Non-goals: no Canonical/League access, no promotion, no new seeds beyond the fixed
init `49000001`, no D2 dataset change beyond the intended refresh schedule, no
change to `EfficiencyQNet` architecture except the second head required by lever 2,
no change to the frozen evaluator/selector/val-seed set (comparability with the
M49A curve must be preserved).

## Contracts and invariants

1. **Fixed setup:** init/seed `49000001`, fixed D2 (`m49a-clean2-round2-compact`),
   80×8 epochs, hard refresh every 4, checkpoints `[10,20,30,40,50,60,70,80]`,
   frozen selector `m49a_validation_select_v1`, evaluator
   `m49a_validation_64_cap100_rng_ordinal_v1`. No changes to any of these.
2. **Fail-closed** on builder-hash / D2-hash / cache-manifest mismatch, exactly as
   the existing runtime.
3. **Numerical-parity contract:** any change to the Rust target builder (γ, or the
   in-support-restricted min) MUST keep Rust-vs-CUDA parity at TF32-off ~1e-5 and
   TF32-on within the historical 1e-3 relative tolerance. Re-run the parity gate on
   the new backup before any training is trusted.
4. **CQL sign contract:** the conservative term must *raise* (make more expensive)
   Q on non-dataset actions relative to the logged action; a unit test asserts the
   penalty gradient sign on a synthetic state (dataset action Q must not exceed
   softmin+ε after a few steps).
5. **γ contract:** discount applies ONLY to the bootstrapped `V(o')` term of Running
   transitions; terminal costs (step cost, failure penalty) are undiscounted. Unit
   test asserts `y = step_cost + gamma*min_q` for Running and unchanged terminals.
6. **Clipped double-Q contract:** two independently-initialized heads; bootstrap
   uses cost-space MAX at the min-selected action; both heads are checkpoint
   candidates but the selector still scores a single policy (define which head, or
   `min(Q1,Q2)`, is the eval policy — pre-register before running).

## Implementation plan

1. Rust: add `--gamma` (default 1.0 for back-compat) to `m49a-build-targets` and the
   `compute_target` math; optional `--in-support-mask` input path for arm A1b.
   Rebuild release, hash-pin a new frozen builder, re-verify byte-identity of the
   `gamma=1` path against the current frozen builder `edf2003c…`.
2. Python: add `gamma`, CQL `α`, and a second Q head + clipped-min bootstrap to
   `m49a_cuda_trainer.py` / `m49a_trainer.py`, all behind config flags defaulting to
   the current behavior (so A0 is bit-reproducible).
3. Unit tests: γ target math, CQL penalty sign, clipped-double bootstrap, and a
   parity test for the `gamma=1 / α=0 / single-head` degenerate = current run.
4. Parity gate: re-run `parity_late_checkpoints`-style Rust-vs-CUDA check on the new
   backup for a couple of checkpoints.
5. Execute arms in the recommended order **only after owner go + free GPU**.
6. Evaluate every arm with the frozen selector; compare the full validation curve to
   the A0 baseline curve.

## Iteration log

- 2026-09-26: Design written (this document). NOT executed — GPU busy, owner
  deferred launch. Awaiting owner go + free GPU + arm selection.

## Final implementation

_Pending authorization + execution._

## Validation and evidence

_Pending._ Will record exact commands, exit status, builder/cache hashes, the full
per-arm validation curve, and the parity re-check.

## Result and decision

_Pending._

## Known limitations

- The clean in-support uplift (~0.7 median) is modest vs the total drift (~1.5), so
  lever 1 alone may not fully close the gap; the combined A4 stack hedges across
  both mechanisms.
- Lever 2 doubles Q parameters/compute and adds an eval-policy definition choice.
- `gamma<1` slightly changes the objective (discounted turn count); acceptable at
  `0.99` for ≤100-turn episodes but recorded as a deviation from the pure
  turn-minimization objective.
- This remediation targets *convergence stability* on the fixed D2 / fixed val
  cohort; it is NOT a generalization or Canonical/League claim.

## Next authorized gate

**Frozen acceptance gate (pre-registered, do not change after seeing results):**

- **Primary (non-degradation):** with the unchanged selector on the frozen 64 val
  seeds, the selected checkpoint's `success_count ≥ 61/64` (the A0 peak) AND the
  tail must not collapse: `success_count(iter80) ≥ success_count(peak) − 3`.
  (A0 fails this badly: iter80 `41/64`, peak `61/64`, drop 20.)
- **Secondary (curve shape, diagnostic not gate):** `val_huber` must not rise
  monotonically across the last ~4 checkpoints; train-backup `v_min_all` drift and
  `argmin_OOD` fraction should not grow as in A0.
- An arm that meets the primary gate is a valid positive; one that does not is a
  valid negative (preserve it, do not re-tune on the same seeds). No promotion,
  Canonical/League, or new-seed generalization is authorized by this gate.

STOP after writing this design. Do not modify code, rebuild binaries, or start
training until the owner selects arms AND the GPU is free.
