# M24.5 Scale-Failure Diagnosis

Status: `VERIFIED` (D24.5 result pending independent review)
Parent: `M24 Training Scale Foundation` — `COMPLETE / NEGATIVE RESULT`
Diagnosis config: `benchmarks/m24-scale-failure-diagnosis-v1.json`

## Historical execution checkpoint — 2026-08-17

- A, B, and C artifacts exist locally and retain the preregistered inputs and
  metrics. D1 remains the existing-evidence summary.
- After the disk remount, the original D2 background process was gone. The
  first resumed attempt produced 12 reports with `16/16` handshake `agent_io`
  aborts because the CUDA/Python runtime environment was not restored.
- Those reports are invalid execution artifacts and must not be used as D2
  evidence. They were removed and the plans were retried with the recorded
  CUDA virtual environment and `PYTHONPATH`; the retry still aborted at
  handshake for both GPU and non-GPU pairings, including the previously
  completed S1-vs-heuristic plan.
- This checkpoint was superseded by the runtime recovery below. It is retained
  as provenance for the invalid attempt and is not scientific evidence.

## Final execution — 2026-08-17

- Repair 4 pre-registration is accepted for this diagnostic execution;
  `AUTHORIZED` remains the benchmark's execution-authorization state. Final
  diagnosis acceptance is a separate independent-review gate.
- Runtime root cause: after the remount, the literal Arena command
  `splendor` was no longer resolvable because `target/debug` was absent from
  `PATH`. No tracked source, frozen plan, checkpoint, CUDA installation, or
  scientific input used `DISK1`.
- The invalid retry reports were retained under
  `local-artifacts/m24-scale-failure-diagnosis-v1/failed-attempts/remount-path-missing/`.
  The indexed set contains 12 plans with 16/16 handshake `agent_io` aborts;
  `scientific_evidence_used` is false.
- The ignored wrapper
  `local-artifacts/m24-scale-failure-diagnosis-v1/run-m24-env.sh` explicitly
  prepends `target/debug` and the CUDA Python environment to `PATH`. Formal
  D2 reran the exact frozen realized plans without exporting `PYTHONPATH`.
- Formal D2 used the same-commit executable SHA
  `a2e0eb02ac7b475cab902e4d9f9ed153ac5428031b607d0f1c85a1e8e733aa49`.
  Afterward, the stale ignored `target/` was cleaned and rebuilt at the new
  mount; the verification executable SHA is
  `c7ce197e42195c4dc2a065c7aaf3321194a3c09abb20e92a90fc292dc7ae74d3`, with
  no embedded `DISK1` path.
- A runtime smoke and all 15 D2 evaluations completed successfully: 240/240
  matches completed, 0 aborted, 0 agent faults.

## Problem

M24-S2 showed:

- Offline fit on the fixed S1 reference subset improved.
- S2 vs S1 fresh paired Arena screen passed.
- M07 anchor regression failed at `-313 bps`, below the frozen `-200 bps` threshold.
- G4 = `FAIL`, G5 = `STOP`.

The central open question is:

> Why did more self-play data improve offline learning and S1-relative movement, while degrading relative performance against the stronger M07 champion?

## Scope

This milestone is diagnostic-only.

Allowed:

- Use existing S1/S2 datasets, checkpoints, training reports, diagnostics, Arena outputs.
- Run cheap/offline analyses.
- Run the frozen D2 search-budget sensitivity screen.
- Produce tracked diagnostic manifests and docs.

Not allowed:

- New model training.
- New self-play collection.
- S3 / M25 / M26 start before decision gate D24.5.
- Champion or promotion changes.
- Changing M24 frozen gates, thresholds, or stored results.

## Pre-registered analyses

### A. Dataset shift

Compare S1-128 vs S2-fresh-384:

- game length distribution
- legal-action count distribution
- chosen action type distribution
- policy entropy / visit entropy
- value target distribution
- duplicate observation / information-set rates
- whether S2-fresh adds novel positions or mostly repeats the M22 self-play distribution

Exact information-set overlap is descriptive only:

```text
exact_information_set_overlap =
  fraction of S2-fresh information sets already present in S1-128

expected approximately 0 because M24-S2 has
duplicate_information_set_rate = 0.0
```

This does NOT by itself imply strategic novelty.

A gate metric is 84-stratum distribution similarity:

```text
strata:
  3 phases x 7 action types x 4 legal-action bins = 84

source_1 = entire S1-128 dataset
source_2 = S2-fresh-384 dataset (S2 game_index >= 128)

p_i = S1-128 frequency in stratum i
q_i = S2-fresh-384 frequency in stratum i

total_variation_distance =
  0.5 * sum_i |p_i - q_i|

distribution_similarity =
  1 - total_variation_distance
```

### B. Shared-reference model behavior

Use the frozen S1 reference validation subset:

- dataset `b2284c6c...4053`
- game_index `% 4 == 0`
- 1,953 examples

Compare S1 and S2 checkpoints on the same positions:

- policy entropy
- policy top-1 agreement
- policy CE against self-play targets
- Value MSE / calibration
- phase and action-type sliced CE/MSE

### C. M07 disagreement — frozen position-selection contract

Source populations:

```text
s1_reference:
  S1 examples with game_index % 4 == 0

s2_fresh:
  S2 examples with game_index >= 128
```

Stratification:

```text
phase:
  opening   = ply < 20
  midgame   = 20 <= ply < 40
  endgame   = ply >= 40

action_type:
  chosen_action.type categories

legal_action_bins:
  small   = len < 10
  medium  = 10 <= len < 30
  large   = 30 <= len < 100
  huge    = len >= 100
```

Selection:

```text
sample_size   = 512
per_source    = 256
canonical_stratum_key = [phase, action_type, legal_bin]
```

Quota algorithm:

```text
stratum_count = eligible examples in that stratum within the source
source_count  = total eligible examples in that source

base_quota = floor(per_source_size * stratum_count / source_count)
remainders allocated by descending fractional remainder,
then ascending canonical stratum key

every non-empty stratum gets at least 1

trim_loop:
  while total_quota > per_source_size:
    choose stratum by:
      1. current quota descending
      2. canonical stratum key ascending
    decrement that stratum by 1
```

Deterministic selector:

```text
key       = sha256(diagnosis_id || information_set_hash)
encoding  = UTF-8 concatenation
order     = ascending
within stratum select first quota entries
```

Output:

```text
local-artifacts/m24-scale-failure-diagnosis-v1/c-selected-positions.json
semantic hash recorded after selection
```


Ranking definition:

```text
method          = Spearman rho
universe        = exact legal_actions in canonical action order
model_rank      = descending model probability
M07_rank        = descending M07 root utility
ties            = average ranks
all tied on either side = 0
action alignment = canonical legal_actions order
missing/invalid  = exclude position and record exclusion
aggregation      = mean rho over all selected positions

top1 tie-break   = first action in canonical legal_actions order
```

### D. Strength attribution

D1: existing-evidence attribution

- Slice Arena results by opening / mid / endgame and action type where possible.
- Correlate S2 vs S1 policy confidence and value error with M07 anchor delta.

D2: mandatory fixed-model search-budget sensitivity

Stage 0 — inherited accepted materialization (not a D2 mutation):

```text
S2-containing templates:
  benchmarks/m24-s2-vs-s1-v1.plan.json
  benchmarks/m24-s2-vs-m07-v1.plan.json
  benchmarks/m24-s2-vs-heuristic-v1.plan.json

placeholder:
  __M24_S2_CHECKPOINT_HASH__

formal S2 checkpoint hash:
  c43e3c239124671c77bb7436dcf79e4fe6c71b66c8008186ac68621a8ad7d5a8

materialization contract:
  benchmarks/m24-s2-arena-screen-v1.realized.json
```

Stage 1 — D2 mutations only:

```text
derived_from_plans:
  benchmarks/m24-s2-vs-s1-v1.plan.json
  benchmarks/m24-s2-vs-m07-v1.plan.json
  benchmarks/m24-s1-vs-m07-v1.plan.json
  benchmarks/m24-s2-vs-heuristic-v1.plan.json
  benchmarks/m24-s1-vs-heuristic-v1.plan.json

allowed_mutations ONLY:
  1. game_seeds: 300001..300032 -> 300001..300008
  2. neural agents --simulations -> one of {16, 32, 64}
  3. evaluation_id: append -sim{sim}

forbidden:
  all other fields must remain identical:
  sample_seed, checkpoint identity, M07 search config,
  heuristic identity, python/module root, catalog,
  PUCT/depth, timeouts, seat rotations
```

Rescue criterion:

```text
anchor_delta_m07(b) =
  center(S2,M07,b) - center(S1,M07,b)

search_rescue_condition =
  anchor_delta_m07(64) >= -200

search_sensitivity_evidence =
  anchor_delta_m07(64) - anchor_delta_m07(16) >= 100
  OR search_rescue_condition
```

## Derived booleans

```text
A_redundancy_evidence =
  distribution_similarity >= 0.70
  (84-stratum similarity between entire S1-128 and S2-fresh-384)

B_shared_ref_improvement =
  policy_ce_improvement_bps >= 50
  OR value_mse_improvement_bps >= 50

C_m07_no_improvement =
  top1_agreement_delta <= 0.005
  AND rank_correlation_delta <= 0.01
  AND disagreement_rate_delta >= -0.005

D2_rescue =
  anchor_delta_m07(64) >= -200

D2_sensitivity =
  anchor_delta_m07(64) - anchor_delta_m07(16) >= 100
  OR D2_rescue

D2_monotonic =
  delta16 <= delta32 <= delta64
  AND delta64 - delta16 >= 50

teacher_drift =
  A_redundancy_evidence
  AND C_m07_no_improvement
  AND NOT D2_rescue

representation_capacity_evidence =
  B_shared_ref_improvement
  AND NOT A_redundancy_evidence
  AND C_m07_no_improvement
  AND NOT D2_rescue
```

## Decision Gate D24.5

Precedence: if more than one branch matches, decision is `INCONCLUSIVE`.

| Branch | Predicate | Action |
| --- | --- | --- |
| Teacher/bootstrap problem | `A_redundancy_evidence AND C_m07_no_improvement AND NOT D2_rescue` | M25 strong GPU warm-start v2 with M07 teacher corpus |
| Search bottleneck | `D2_sensitivity OR D2_monotonic` | M27A fixed-model search-budget scaling |
| Representation/capacity bottleneck | `representation_capacity_evidence` | Targeted M28 preparation |
| Inconclusive | `NOT (teacher OR search OR representation) OR multiple branches true` | One additional frozen diagnostic, not another 2048-game brute-force run |

M26 generation chaining is not authorized before a strong teacher exists.

## Deliverables

- `benchmarks/m24-scale-failure-diagnosis-v1.json` (tracked)
- This living milestone document
- Diagnostic result manifest(s) after analyses
- Decision record for D24.5

## Final implementation

- Tracked compact result: `benchmarks/m24-scale-failure-diagnosis-v1.result.json`.
- Full ignored result: `local-artifacts/m24-scale-failure-diagnosis-v1/final-diagnosis.json`.
- Runtime snapshot SHA-256:
  `810b45ef38ff50e591522ef738e22a85d7dd67c60a2f329a514e5d5d72f57cd5`.
- Full final diagnosis SHA-256:
  `7854542b94b1e5ded9d00cf4a171981491b6e792294d98cc9013e7fc66593e5a`.
- The result manifest binds S1/S2 dataset and checkpoint identities, A/B/C/D1
  artifact hashes, all 15 realized plan hashes and file hashes, all 15 report
  hashes, and retained invalid-attempt provenance.

## Validation and evidence

- A: distribution similarity `0.9658682665233417`, TV `0.03413173347665832`,
  exact information-set overlap `0.0` descriptive only; `A_redundancy_evidence = true`.
- B: policy CE improvement `65.3789160561596` bps and value MSE improvement
  `344.552307094248` bps; `B_shared_ref_improvement = true`.
- C: top-1 delta `+0.01171875`, rank-correlation delta `+0.004695216948526107`,
  disagreement delta `-0.01171875`; `C_m07_no_improvement = false`.
- D1: accepted Arena evidence retains M07 anchor delta `-313` bps and
  heuristic delta `+938` bps; detailed replay phase/action slicing was not run.
- D2 M07 anchor deltas: `sim16 = -625` bps, `sim32 = +3125` bps,
  `sim64 = +1250` bps.
- D2 derived booleans: `D2_rescue = true`, `D2_sensitivity = true`,
  `D2_monotonic = false`.
- Commands passed:
  `cargo fmt --all`; `cargo test -p splendor-cli --test m24_result -- --test-threads=1`
  (9/9); `cargo test --workspace -- --skip shutdown_reaps_child`; `git diff --check`.
- The first post-remount workspace run exposed stale ignored `target/` binaries
  containing `/media/bailan/DISK1`; after `cargo clean`, the same workspace
  command passed with all non-ignored tests and the expected skipped test.

## Result and decision

The frozen D24.5 function yields exactly one substantive branch:

```text
teacher branch        = false
search branch         = true
representation branch = false
inconclusive branch   = false
outcome               = SEARCH_BOTTLENECK
recommended next      = M27A fixed-model search-budget scaling
```

`D2_rescue = true` makes both teacher/bootstrap and representation predicates
false because each requires `NOT D2_rescue`; D2 sensitivity makes search true.
The non-monotonic `16 -> 32 -> 64` curve is evidence for a search interaction,
not evidence that more simulations are monotonically better.

This is `VERIFIED` evidence, not milestone acceptance. Independent review of
the tracked manifest, source hashes, raw report bindings, and recomputation is
still required. M27A, M25, M26, and M28 remain unauthorized until that review
passes.

## Known limitations

- Each D2 pair/budget contains 8 seeds and two seat rotations, so the curve
  shape may include small-sample variance.
- D1 is an existing-evidence summary and does not contain new replay slicing.
- Heavy datasets, checkpoints, replays, and D2 reports remain local-only under
  `local-artifacts/`.

## Next authorized gate

Independent review of `benchmarks/m24-scale-failure-diagnosis-v1.result.json`
and the documented local evidence. No new training, collection, champion
change, or M27A execution is authorized before that review.

## Constraints

- No new champion.
- No promotion.
- No S3.
- No M25/M26 until D24.5.
- Heavy outputs stay under `local-artifacts/`; compact manifests are tracked.
