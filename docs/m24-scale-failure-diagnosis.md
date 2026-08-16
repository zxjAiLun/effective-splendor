# M24.5 Scale-Failure Diagnosis

Status: `AUTHORIZED` (Repair 1)
Parent: `M24 Training Scale Foundation` — `COMPLETE / NEGATIVE RESULT`
Diagnosis config: `benchmarks/m24-scale-failure-diagnosis-v1.json`

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

quota_rule:
  allocate 256 per source across phase x action_type x legal_bin
  base quota = floor(256 * stratum_count / source_count)
  remainder by descending fractional remainder, then ascending stratum key
  every non-empty stratum gets at least 1
  if over 256, trim from largest-quota stratum using ascending deterministic key

deterministic_selector:
  key       = sha256(diagnosis_id || information_set_hash)
  encoding  = UTF-8 concatenation
  order     = ascending
  within stratum select first quota entries

output:
  local-artifacts/m24-scale-failure-diagnosis-v1/c-selected-positions.json
  semantic hash recorded after selection
```

### D. Strength attribution

D1: existing-evidence attribution

- Slice Arena results by opening / mid / endgame and action type where possible.
- Correlate S2 vs S1 policy confidence and value error with M07 anchor delta.

D2: mandatory fixed-model search-budget sensitivity

```text
checkpoints        = S1, S2
comparison pairs   = S2 vs S1, S2 vs M07, S1 vs M07,
                     S2 vs heuristic, S1 vs heuristic
sim_budgets        = [16, 32, 64]
seeds              = 300001..300008
seat_rotations     = 2
max_depth_turns    = 1
PUCT               = 1500
catalog            = apps/replay-studio/tests/fixtures/rust-analysis-trace-v1.json
device             = cuda
timeouts           = 5000 / 10000 / 2000
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

## Decision Gate D24.5

Precedence: if more than one branch matches, decision is `INCONCLUSIVE`.

| Branch | Required evidence | Action |
| --- | --- | --- |
| Teacher/bootstrap problem | A shows S2-fresh largely redundant; C shows M07 disagreement not improved/worsened; D2 rescue false | M25 strong GPU warm-start v2 with M07 teacher corpus |
| Search bottleneck | D2 sensitivity true; rescue true or monotonic improvement across 16/32/64 | M27A fixed-model search-budget scaling |
| Representation/capacity bottleneck | B shows S2 improves on train-like shared-reference metrics but fails on M07-disagreement slices; teacher-drift false; D2 rescue false | Targeted M28 preparation |
| Inconclusive | Conflicting evidence, insufficient coverage, or no branch satisfies all predicates | One additional frozen diagnostic, not another 2048-game brute-force run |

M26 generation chaining is not authorized before a strong teacher exists.

## Deliverables

- `benchmarks/m24-scale-failure-diagnosis-v1.json` (tracked)
- This living milestone document
- Diagnostic result manifest(s) after analyses
- Decision record for D24.5

## Constraints

- No new champion.
- No promotion.
- No S3.
- No M25/M26 until D24.5.
- Heavy outputs stay under `local-artifacts/`; compact manifests are tracked.
