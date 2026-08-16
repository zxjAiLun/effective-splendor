# M24.5 Scale-Failure Diagnosis

Status: `AUTHORIZED`
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
- Run fixed-model search-budget sensitivity if needed.
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

- game_index `% 4 == 0`
- 1,953 examples

Compare S1 and S2 checkpoints on the same positions:

- policy entropy
- policy top-1 agreement
- policy CE against self-play targets
- Value MSE / calibration
- phase and action-type sliced CE/MSE

### C. M07 disagreement

This is the key diagnostic.

- Freeze a stratified position set from S1/S2 corpus.
- Run M07 root analysis on those positions.
- Measure S1/S2 policy vs M07:
  - top-1 action agreement
  - ranking agreement / rank correlation
  - disagreement rates
- Determine whether S2 moved closer to or farther from M07.

Expected strong conclusion if:

```text
S2 fits M22/self-play targets better
+
M07 disagreement does not improve or worsens
+
more search does not rescue
```

=> bottleneck is teacher/data distribution, not data quantity alone.

### D. Strength attribution

Connect Arena failure to concrete behavioral patterns:

- Slice Arena results by opening / mid / endgame and action type where possible.
- Correlate S2 vs S1 policy confidence and value error with M07 anchor delta.
- Optionally run fixed-model search-budget sensitivity:
  - sims 16 / 32 / 64
  - small frozen pair screen
  - no training

This helps decide whether the network improved but the search budget failed to use it.

## Decision Gate D24.5

| Finding | Next action |
| --- | --- |
| Teacher/bootstrap problem | M25: strong GPU warm-start v2 with M07 teacher corpus |
| Search bottleneck | M27A: fixed-model search-budget scaling |
| Representation/capacity bottleneck | Targeted M28 preparation |
| Inconclusive | One additional frozen diagnostic, not another 2048-game brute-force run |

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
