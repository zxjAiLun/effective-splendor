# M15A Neural Capability Degradation Diagnostic

## Verdict

The rejected M13 agent did not fail because of a checkpoint/config mismatch,
replay reconstruction error, isolated seat bias, or a noisy promotion sample.
The strongest supported causal diagnosis is:

```text
primary cause    weak / weakly calibrated M12 Value head
secondary cause  small mixed-policy behavior-cloning corpus
amplifier        64-simulation, depth-2 search remains prior dominated
```

This is a component diagnosis, not a claim that champion-action agreement is
an optimal-policy metric. A new candidate still requires prospective matches
on new seeds.

## Bound evidence

M14B analyzed the unchanged frozen M13 evaluation with the exact accepted
checkpoint and runtime configuration:

```text
matches                              64
decision frames                    3905
candidate frames                   1955
champion frames                    1950
candidate result                 12-0-52
candidate decisions reproduced 1955 / 1955
sidecars                             64
```

The batch command first re-aggregated the evaluation report from the executed
plan and canonical records, then bound every replay by `match_index`, seed,
seat rotation, terminal result, ply count and final replay hash. The local
`diagnostic.json` content-addresses all 64 sidecars.

```text
plan hash       d6193b40d5c4c95475c0c206bd074f1b79e72f73a87dc35a58a362dc00fcf207
report hash     243653032aee2ba8fa956178769acba578b24f9dca66273a88ff1c7ad6494775
checkpoint hash 108d32fa2d0d2499ead38e99b23e42cd905644358a76d5adb7392ad43401b462
diagnostic hash de995fff20dec1a9dc0c06491fd766fe6f4470074f06f98dff696ce38e47624f
```

Generated sidecars and the full diagnostic remain under ignored
`local-artifacts/m14b-m15-diagnostic-2026-08-12/`. The small tracked result
anchor is `benchmarks/m15-neural-degradation-v1.result.json`.

## Controlled ablation

All variants retain the same player-view information set, determinization
stream, terminal values, depth, budget, PUCT arithmetic and root tie-breaking.
Only learned priors and learned leaf values change.

Agreement with the recorded action:

| Decision owner | Full | Direct Policy | Value only | Policy only | Neutral |
|---|---:|---:|---:|---:|---:|
| M13 candidate, 1,955 frames | 100.00% | 77.44% | 27.57% | 77.75% | 48.29% |
| M07 champion, 1,950 frames | 32.31% | 32.51% | 11.08% | 33.13% | 19.13% |

The candidate row is mainly a runtime reproduction and component-change
measurement: `full` is expected to reproduce the recorded M13 action. The
champion row is the useful behavioral reference. On those positions,
`policy_only` is the best neural variant, while `value_only` falls well below
even the neutral control. Adding learned Value to learned Policy reduces
champion agreement from 33.13% to 32.31% and changes 18.92% of Policy-only
choices. This is direct evidence that the current Value head is not adding a
reliably corrective signal.

## Why the Value head is the primary cause

The accepted M12 offline report already showed a weak Value margin:

```text
validation examples               996
Value MSE                      0.246707
train-prior Value MSE          0.248584
relative improvement              0.75%
```

The offline gate proved only that the head narrowly beat a constant prior. It
did not prove useful action ranking inside search. M15A now shows the missing
downstream fact: with priors neutralized, learned Value matches champion
actions only 11.08% of the time, versus 19.13% for fully neutral search.

The first dataset contains 64 two-player games and 3,956 total decisions from
both the determinization champion and the rejected M10 ISMCTS candidate. The
Policy head therefore imitates a mixture rather than a quality-filtered
teacher, while the Value head learns terminal dense rank from a small number of
correlated trajectories. That corpus was sufficient for a deterministic
baseline, not for a strong search evaluator.

## Search amplification

At the formal 64-simulation budget, M13 does not explore the whole root:

| Decision owner | Avg legal | Avg visited | Coverage | Full = top prior | Avg top-edge visits |
|---|---:|---:|---:|---:|---:|
| M13 candidate | 21.10 | 14.03 | 66.50% | 77.44% | 20.97 / 64 |
| M07 champion | 27.68 | 14.99 | 54.14% | 80.46% | 22.37 / 64 |

Full search agrees with `policy_only` on 77.75% of candidate frames and 81.08%
of champion frames. The chosen action's mean Q trails the best visited mean Q
by 0.0194 on candidate-owned positions and 0.0422 on champion-owned positions,
on a `[0, 1]` scale. This is consistent with PUCT/visit selection staying
strongly coupled to the learned prior while a noisy Value signal has too few
samples to correct it reliably.

This does not mean that increasing simulations alone is the fix. A larger
budget can make a biased Value estimate more influential. Budget/depth changes
must be tested only after the evaluator is improved, under a separately frozen
diagnostic design.

## Rejected alternative explanations

- **Runtime/config drift:** rejected by exact 1,955/1,955 M13 action
  reproduction and exact checkpoint/config binding.
- **Seat bias alone:** candidate lost from both seats (9/32 and 3/32 wins).
- **A few unlucky seeds:** 20/32 seed blocks were double losses, 12 split, and
  zero were double wins.
- **Reliability failure:** the source evaluation had zero aborts and zero
  candidate faults.
- **Provenance failure:** plan, canonical report, match slot, replay and trace
  hashes are closed before aggregation.

## M15B development order

1. Freeze new training/validation/diagnostic seed partitions. Never train or
   tune on M13's formal seeds `930000..930031`.
2. Split Policy and Value data contracts. Policy targets should identify the
   teacher and initially use champion/strong-search decisions rather than
   treating rejected-policy actions as equal imitation labels. Value training
   may retain complete outcomes but must remain source-group split.
3. Expand independent trajectories and add Value calibration by phase, seat
   and outcome. Require a predeclared material improvement over the constant
   prior, not merely `> 0`.
4. Run prospective `policy_only` versus champion matches on new diagnostic
   seeds. This tests whether removing the weak Value head improves actual play;
   retrospective action agreement alone is insufficient.
5. Train Value v2, then compare `policy_only`, `value_only`, `full`, and
   `neutral` at fixed 64 simulations. Only after component gates pass should a
   bounded budget/depth sweep be authorized.
6. Freeze a new M15 candidate and entirely new formal promotion seeds. M13
   remains rejected and the determinization champion remains unchanged.

## M15B source-aware first candidate

M15B now freezes a version-2 training contract that separates the Policy and
Value source selections without changing the accepted M12 v1 hash contract.
Policy imitation uses only decisions made by the determinization champion;
Value retains completed trajectories from both agents. Train/validation
partitioning remains source-grouped and both heads have predeclared material
offline gates.

The first deterministic run produced checkpoint semantic hash
`c5f4ae0a5e9c0dd574478a4333c69a22cfa419492680a8bd89fbfeeb577f5120`.
Its champion-only Policy NLL improved 20.20% over uniform, passing the frozen
15% gate. Value MSE improved only 2.52% over the training prior, failing the
frozen 5% gate. The gate is not lowered: this checkpoint is not a full
Policy/Value candidate.

The passed Policy component is carried into one predeclared prospective
control: `benchmarks/m15b-policy-only-diagnostic-v1.league.json` runs learned
priors with neutral non-terminal leaf values against the unchanged champion on
16 new seeds (`940000..940015`) with both seat rotations. The ablation uses a
distinct runtime identity and cannot select `full`. This 32-match screen is a
diagnostic experiment, not a promotion run; its seeds cannot later be reused
as formal M15 promotion evidence.

That screen completed once on 2026-08-12 from implementation commit `47168a4`:

```text
completed matches:              32 / 32
candidate wins / ties / losses:  4 / 0 / 28
candidate seat 0 / seat 1 wins:  1 / 3
candidate score:              1250 bps
diagnostic Hoeffding interval:   0 .. 4312 bps
seed blocks 0 / 1 / 2 wins:     13 / 2 / 1
aborts / candidate faults:       0 / 0
```

All match indices were exactly `0..31`, every Arena report was completed, all
32 replays independently verified, and the schedule plus aggregate were
recomputed from records. The local artifacts remain ignored. Their binding is
recorded in `benchmarks/m15b-policy-only-diagnostic-v1.result.json`.

This prospective result changes the causal emphasis. M15A remains correct that
the accepted M12 Value head is weak, but removing learned Value is not enough:
the new source-filtered Policy-only control still loses decisively from both
seats. Its 12.5% point score is below M13's 18.75%, although the different seed
sets and smaller sample mean those point estimates are not a paired comparison.
The defensible conclusion is that both Policy generalization and Value quality
are insufficient, with low-budget search amplifying them.

One concrete limitation is now material: the v2 source contract filters Policy
labels, but Policy and Value still share an encoder and Value examples update
that encoder. The next controlled candidate must isolate Policy representation
learning from Value gradients and use additional independent champion-teacher
trajectories. Raising simulations, lowering gates, or reusing M13/M15B
diagnostic seeds is not authorized.

## Status

```text
M14B_BATCH_ANALYSIS       IMPLEMENTED / COMPLETE
M15A_CONTROLLED_ABLATION  IMPLEMENTED / COMPLETE
M15A_DIAGNOSIS            VALUE HEAD PRIMARY / DATA SECONDARY / BUDGET AMPLIFIER
M13_STATUS                REJECTED / NOT PROMOTED
CURRENT_CHAMPION          determinization-s4-d1-n2000-v1
M15B_SOURCE_AWARE_TRAINING IMPLEMENTED
M15B_POLICY_GATE           PASS
M15B_VALUE_GATE            FAIL / NOT LOWERED
M15B_POLICY_ONLY_SCREEN    COMPLETE / FAIL (4-0-28)
M15B_FULL_CANDIDATE        NOT AUTHORIZED
M15B_NEXT                  NEW TEACHER DATA + ENCODER GRADIENT ISOLATION
M15B_TEACHER_DATA_V2       FROZEN (128 MATCHES, SEEDS 950000..950063)
M15B_TEACHER_DATA_RESULT   125 COMPLETE / 3 CHAMPION TIMEOUT / DATASET BUILT
M15B_ISOLATED_TRAINING_V2  COMPLETE / POLICY PASS / VALUE FAIL
M15B_ISOLATED_POLICY_SCREEN FROZEN (32 MATCHES, SEEDS 960000..960015)
```

## M15B second-candidate result

The isolated second checkpoint passed its Policy offline gate but failed its
Value gate. Its authorized Policy-only screen then completed all 32 matches on
the frozen `960000..960015` seeds with zero aborts and zero faults:

```text
candidate wins / ties / losses:  5 / 0 / 27
candidate seat 0 / seat 1 wins:  2 / 3
candidate score:              1562 bps
diagnostic Hoeffding interval:   0 .. 4624 bps
seed blocks 0 / 1 / 2 wins:     12 / 3 / 1
```

All 32 replays independently verified and the schedule/aggregate were
recomputed. The exact binding is tracked in
`benchmarks/m15b-isolated-policy-only-diagnostic-v2.result.json`; generated
artifacts remain local.

This closes M15B without a candidate. Doubling the same type of champion
teacher data and preventing Value loss from touching the Policy encoder raised
held-out Policy top-1 from 30.72% to 33.95%, but prospective play remained
decisively weak (5–27 versus the first screen's 4–28 on different seeds).
Therefore shared-encoder Value contamination is not a sufficient explanation,
and one-hot behavioral-cloning NLL is not a sufficient strength gate for PUCT
priors. Value supervision also failed the material gate in both attempts.

The next evidence-supported design should preserve root search distributions
(visits and/or normalized utilities) as Policy targets rather than imitating
only the selected action, and redesign Value supervision/calibration. Increasing
the search budget around the rejected heads, lowering offline gates, or running
another same-design seed screen is not authorized.

```text
M15B_STATUS                 COMPLETE / NO CANDIDATE
M15B_ISOLATED_SCREEN        COMPLETE / FAIL (5-0-27)
M15_FULL_CANDIDATE          NOT AUTHORIZED
CURRENT_CHAMPION            determinization-s4-d1-n2000-v1
NEXT                        SEARCH-DISTRIBUTION POLICY TARGETS + VALUE REDESIGN
M15C_TARGET_GENERATOR       IMPLEMENTED / FROZEN INPUTS
M15C_TARGETS                COMPLETE / 3920 / ACTION REPRODUCTION 3920-3920
M15C_SEARCH_TRAINING        COMPLETE / POLICY FAIL / VALUE FAIL
M15C_CANDIDATE              NOT AUTHORIZED
M15C_NEXT                   REPRESENTATION / CAPACITY, SAME TARGETS AND GATES
M15D_ARCHITECTURE_V2        IMPLEMENTED / H64 / POLICY-VALUE ENCODERS ISOLATED
M15D_SEARCH_TRAINING        COMPLETE / POLICY FAIL / VALUE FAIL
M15D_DIAGNOSIS              TRAIN AND VALIDATION UNDERFIT / NO GENERALIZATION GAP
M15D_CANDIDATE              NOT AUTHORIZED
M15_NEXT                    OPTIMIZATION OBJECTIVE / TARGET FACTORIZATION AUDIT
```
