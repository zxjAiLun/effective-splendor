# S2b — n1 Buy-Overlay Confirmation (parameter-free candidate)

STATUS     = CLOSED / IMPROVEMENT_NOT_CONFIRMED / CANDIDATE_NOT_ADOPTED
            (final review 2026-09-09: the closure accepts UNRESOLVED vs
            n1 as the standing verdict — the 97.5% decision CI
            [3125.0, 5000.0] touches the parity line, so the comparison
            is NOT re-adjudicated with the 95% interval, and no extra
            matches are added to worsen it; the candidate is not
            adopted. P0:0 / P1:0 — four descriptive-record items
            applied docs-only, no re-run.)
RESULT     = UNRESOLVED (vs n1; point estimate favors plain n1:
            overlay 51-2-75, center 4062.5) / STRONGER_B (vs heuristic:
            40-1-87, 3164.1 [2304.7, 4062.5]). Scope: triggers 386/3,720
            (10.38%) on P1 and 401/3,956 (10.14%) on P3; exhaustive
            fixed-context parity 100%; P1 trigger identity set exactly
            equals the S2 A1 n1-side nominee set.
REVISION   = V2 2026-09-08 (frozen, ff7a4f1) — executed as frozen;
            closed 2026-09-09 with the descriptive-record items below.
            V1 = adddbe2.
BASELINE   = d409801 (S2 closure, 2026-09-08)
OWNER-DATE = local implementation + cloud review, 2026-09-08/09

## Problem and evidence

### The hypothesis under test

S2 (closed at d409801) found: in 11.27% of eligible SEARCH_ACTOR
Main-phase contexts on its corpus (853/7,570), the acting frozen search
baseline chose `TakeTokens` while heuristic-v1 — the S0-calibrated
primary reference — had a unique `BuyMarket` optimum. The divergence is
overwhelmingly driven by heuristic's Buy-vs-Take category prior, with
bonus_usefulness further favoring the buy in 851/853 cases and
noble_gain in 0/853. S2 established a high-frequency, cross-opponent,
simple, strict preference gap — and explicitly did NOT establish that
overriding those decisions improves playing strength.

S2b asks exactly that question with the smallest possible candidate:

> **Does applying the frozen `TakeTokens -> unique heuristic
> BuyMarket` rule improve n1's playing strength?**

(The rule SHAPE is frozen; the fresh Arena will encounter NEW states —
the overlay may fire more, less, or on different specific contexts
than the historical 853. The question is about the rule, not the 853
historical states.)

### The candidate (frozen; zero free parameters)

```text
base_action = n1(s)                       # EXACT frozen n1: sample_seed
                                           # 20260703 / sample_count 4 /
                                           # max_depth_turns 1 /
                                           # max_nodes 1 /
                                           # StaticEvaluatorV1

H*(s) = argmax-set of heuristic scoring   # via heuristic_term_scores
                                           # totals; NO policy RNG, NO
                                           # tie-break (the |H*|==1
                                           # trigger means ties never
                                           # fire the overlay)

if:
    base_action is TakeTokens
    AND |H*(s)| == 1
    AND the unique H* action is BuyMarket
then:
    candidate_action = that unique BuyMarket action
else:
    candidate_action = base_action        # bit-identical to n1
```

No coefficients, thresholds, weights, stage/flag/tier/bonus-usefulness/
gold/prestige conditions — even though S2 data might look supportive of
some, ALL are prohibited. This tests the S2 nominee itself.

Why n1 as the carrier (S2 closure rationale): n1-vs-M07 strength is
UNRESOLVED (S0) while n1 is ~an order of magnitude cheaper; if the
overlay improves n1, that is the highest-value engineering result
available. NOT a StaticEvaluatorV1 weight sweep — the frozen evaluator
is untouched; the heuristic's scoring is only READ.

## The four pinned questions (per the S2 closure and V2 review)

### 1. Behavioral scope (measured on fixed contexts, not trajectories)

For EVERY recorded n1 mover context in the development corpus,
independently reconstruct the exact frozen context and compute, on that
SAME context:

```text
base_n1(context)  — the frozen n1 action
H*(context)       — the heuristic score-optimal set
candidate(context)— the overlay action
```

Then assert pointwise:

```text
trigger false -> candidate_action == base_n1_action exactly
trigger true  -> base_n1 is TakeTokens AND |H*| == 1
                 AND unique H action is BuyMarket
                 AND candidate_action == that unique H action
```

This is a FIXED-CONTEXT comparison. Trajectory-replay parity (running
candidate vs n1 over whole games and comparing later plies) is
meaningless after the first intervention puts the two on different
trajectories, and is explicitly NOT used. The Arena measures the real
trajectory effect.

**Development corpus** (behavioral/implementation verification only;
never a strength criterion):

- **S0 P1 n1 mover contexts** — the n1 portion of the S2 discovery
  corpus;
- **S0 P3 n1 mover contexts** — additional historical development-scope
  corpus (P3 was NOT part of S2 discovery).

Scope outputs: trigger count + rate per corpus part; no minimum/maximum
gate (a 4% or 18% rate still runs the Arena; only a zero trigger count
conflicting with the P1 cross-check indicates an implementation bug).

**Fail-closed cross-check (implementation correctness, not tuning)**:
on the P1 n1 contexts, the overlay's trigger identity set must match —
identity-for-identity — the S2 A1 n1-side `TakeTokens -> unique H
BuyMarket` strict-divergence rows. The scope audit records the count
and an identity-set digest for both and requires equality.

### 2. No offline tuning

The candidate is the single frozen rule above. Between implementation
and Arena: no iteration, no corpus-driven re-reading, no thresholds. A
scope-measurement bug is fixed and re-measured (bug fix, not tuning);
any rule change reopens this design for review.

### 3. Fresh confirmation Arena (strength only; two pairings)

- **Seeds**: `5_800_192 .. 5_800_255` (64 blocks; fresh — the S1
  segment 5_800_128..191 is NOT reused even though Phase B never ran;
  registry extended, disjointness re-asserted fail-closed).
- **Pairings (exactly two)**:
  - P1: `overlay-candidate vs n1`
  - P2: `overlay-candidate vs heuristic`
  - 64 blocks x 2 rotations x 2 pairings = **256 matches**.
  - **M07 pairing: NOT RUN** (review decision): M07 is neither the
    carrier nor the primary reference; n1-vs-M07 is already UNRESOLVED;
    and no S2b outcome changes the reference. If the candidate performs
    well, a separate small field calibration may be designed later.
- **Statistical protocol**: paired-block bootstrap, 10,000 resamples,
  seed `43_200_001`; **95% descriptive CI** and **97.5% two-sided
  decision CI** (Bonferroni for TWO comparisons, alpha 0.05/2 = 0.025).
  UNRESOLVED stands; extra seeds are a user decision, never automatic.
- **Candidate identity binding**: the Arena config spawns the candidate
  as the EXACT n1 args plus `--heuristic-buy-overlay`; the flag itself
  fail-closes on any non-n1 config, so the candidate identity is bound
  by construction, not by display name.
- **Live trigger rate** (descriptive only): the candidate counts
  trigger_count/decision_count (cheap in-process counters surfaced via
  the existing stats sidecar); reported as the fresh-Arena trigger rate.
  NO gate on it — strength is judged by Arena outcomes only. If it were
  expensive it would be dropped (post-hoc replay recomputation is an
  acceptable alternative), but the in-process counters are already
  free.
- Offline disagreement rates are NOT a success criterion.

### 4. Decision table (frozen; no outcome changes the primary reference)

| Candidate vs n1 | Candidate vs heuristic | Verdict |
|---|---|---|
| resolved win | resolved win or UNRESOLVED | **CARRIER_IMPROVEMENT_CONFIRMED** |
| resolved win | resolved loss | **CARRIER_GAIN_ONLY** |
| UNRESOLVED | anything | **UNRESOLVED** |
| resolved loss | anything | **REFUTED** |

- CARRIER_IMPROVEMENT_CONFIRMED satisfies the frozen success
  condition: resolved improvement over n1 AND not clearly losing to
  heuristic.
- If the candidate also RESOLVED-wins vs heuristic, record
  `REFERENCE_CHALLENGE_SIGNAL = true` — and STILL no reference change
  (M07 untested; no transitivity assumed). A separate field
  calibration would be designed if a reference change is ever wanted.
- CARRIER_GAIN_ONLY is a valuable engineering result, NOT a failure
  class: the preference improves the carrier without closing the
  heuristic gap. It is never conflated with REFUTED.

## Scope and non-goals

- No StaticEvaluatorV1 changes, no search changes, no heuristic
  behavior changes (heuristic scoring is only READ).
- No parameter sweep of any kind.
- No M07 modification and no M07 pairing.
- No new offline attribution; S2 is closed.
- No promotion / champion-title / primary-reference change in ANY
  outcome.
- No neural work, no depth-3+, no search engineering.

## Contracts and invariants

- The overlay flag is valid ONLY with the exact n1 config
  (20260703 / s4 / d1 / n1 / StaticEvaluatorV1); any other combination
  is a CLI error (fail-closed candidate identity).
- Outside the trigger, candidate == n1 bit-identically (exhaustive
  fixed-context scope parity; the final audit re-runs it in full).
- H* uses `heuristic_term_scores(...).total()` directly — never
  `HeuristicAgentPolicy::choose_action` (no RNG consumption, no tie
  state; |H*| > 1 is an automatic no-op).
- The trigger is exactly the S2 nominee shape; any deviation reopens
  the design.
- Fresh-seed disjointness is asserted before any match runs.
- Decision CIs are 97.5% (two-comparison family); 95% CIs are
  descriptive only.

## Implementation plan

1. Rust: `N1BuyOverlayPolicy` wrapping `DeterminizationAgentPolicyV1`
   (exact-n1 construction enforced), applying the frozen rule via
   `heuristic_term_scores` totals; CLI `--heuristic-buy-overlay` flag
   (fail-closed on non-n1 configs); unit tests for trigger/non-trigger
   contexts, flag-off parity, and config rejection.
2. `splendor s2b-scope` batched command: per replay, per eligible
   context, emit base_n1 / H* / candidate / trigger rows for the
   development corpus.
3. `scripts/s2b_scope.py`: exhaustive pointwise parity assertions,
   trigger counts/rates, P1 identity-set cross-check vs S2 A1.
4. `scripts/s2b_orchestrator.py`: seed registry extension, 256-match
   Arena (2 pairings), bootstrap (43_200_001; 95% + 97.5%), decision
   table, live trigger-rate report.
5. `scripts/s2b_final_audit.py`: fail-closed recheck (lineup, replay
   verification, exhaustive scope parity re-run, recomputation,
   decision table, trigger cross-check digests).
6. Tracked result + docs closure + handoff; S2b closure review.

## Estimated cost

- Overlay decision overhead: H* is pure integer scoring — expected to
  be small; the ACTUAL overhead is measured during execution and
  reported (not asserted).
- Scope measurement: ~7.9k n1 contexts (P1+P3 n1 mover contexts),
  minutes.
- Arena: 256 matches at ~n1+heuristic per-decision costs — minutes-scale
  by S0 precedent (67 s for 384 matches at comparable costs).
- No GPU.

## Known limitations

- The fresh-Arena trigger rate may differ from S2's historical 11.27%
  (new trajectories); it is reported descriptively, never gated.
- 64 blocks may leave pairings UNRESOLVED (accepted standing outcome).
- CARRIER_IMPROVEMENT_CONFIRMED does not auto-promote or change the
  primary reference (REFERENCE_CHALLENGE_SIGNAL is a flag, not a
  change).
- The runner-up reserve_market->take_tokens pattern remains untested
  (a separate future question).
- M07 interactions are unmeasured this round (deliberate).

## Validation and evidence

### Execution — 2026-09-08 (single valid run)

Implementation:
- `N1BuyOverlayPolicy` (crates/splendor-determinization-agent/src/
  s2b_overlay.rs): wraps `DeterminizationAgentPolicyV1`; the constructor
  fail-closes on any config other than the EXACT frozen n1; H* is
  computed via `heuristic_term_scores().total()` (no policy RNG, no tie
  state; |H*| > 1 is an automatic no-op); trigger/decision counters are
  descriptive only.
- CLI `--heuristic-buy-overlay`: rejected for non-n1 configs (verified:
  n2000 + overlay -> explicit identity error); cannot combine with
  attribution/telemetry flags.
- `splendor s2b-scope` batched fixed-context harness + unit tests
  (config rejection, non-take no-op, wrapper-vs-plain parity on the
  same context). Workspace 778 tests / 0 failed.

### Scope measurement (exhaustive, fixed-context pointwise)

- Corpus: S0 P1 n1 mover contexts (3,720) + S0 P3 n1 mover contexts
  (3,956) = 7,676 contexts.
- Parity: 100% — every non-trigger context has candidate == base_n1 ==
  recorded action exactly; every trigger context satisfies the full
  trigger shape and candidate == the unique H buy.
- Triggers: P1 386/3,720 = **10.38%**; P3 401/3,956 = **10.14%**. The
  historical ~11% S2 rate transferred to the additional P3 corpus.
- **P1 identity cross-check: PASS** — the P1 trigger identity set
  equals the S2 A1 n1-side `TakeTokens -> unique H BuyMarket`
  strict-divergence set exactly (386 == 386; identity-set digest
  recorded in the tracked scope result). Implementation correctness is
  bound, not assumed.

### Arena (fresh seeds 5_800_192..5_800_255; 2 pairings x 64 x 2 = 256 matches)

| Pairing | W-T-L | Center | 95% CI | 97.5% decision CI | Verdict |
|---|---|---:|---|---|---|
| overlay vs n1 | 51-2-75 | 4062.5 | [3242.2, 4882.8] | **[3125.0, 5000.0]** | **UNRESOLVED** |
| overlay vs heuristic | 40-1-87 | 3164.1 | [2421.9, 3946.3] | [2304.7, 4062.5] | **STRONGER_B (heuristic)** |

Mean plies 60.5 / 58.6; total wall ~22 s.

### Decision table application (frozen)

vs n1 = UNRESOLVED -> verdict = **UNRESOLVED** (the frozen table maps
any UNRESOLVED-vs-n1 to UNRESOLVED regardless of the heuristic
pairing). reference_challenge_signal = false. Primary reference
unchanged.

### Final audit

ALL CHECKS PASS: seed disjointness; exhaustive lineup/rotation
verification from match configs (candidate bound as exact n1 args +
overlay flag; heuristic without overlay flags); 256/256 replays
verified; full recomputation of W/T/L, block scores, center, both CI
levels, verdicts, decision table; scope exhaustive parity + P1
cross-check re-run; binary identity.

### Tracked artifacts

- `benchmarks/s2b-scope-v1.result.json` (scope + parity + cross-check;
  git-blob SHA256, LF form, execution commit `79ba251`:
  `060754b085154b1d953c7fd80f09e84749fc385d12c335c181c5666260da318a`).
- `benchmarks/s2b-n1-buy-overlay-v1.result.json` (Arena + decision;
  git-blob SHA256, LF form, execution commit `79ba251`:
  `531d5ddcbf757e8aa57db8d17c8b69dd4379a0a550c7a38bb55ee86c9ac9066e`).
- Raw per-match artifacts under ignored `local-artifacts/s2b-arena/`;
  scope rows under ignored `local-artifacts/s2b-scope/` (cloud
  evidence boundary as in S0/S1/S2).

## Closure record (final review items, docs-only)

1. **Verdict standing**: UNRESOLVED vs n1 is accepted as-is. The
   97.5% interval's upper bound is exactly 5000.0 (touches parity);
   the comparison is not re-adjudicated at 95%, and no additional
   matches are run. The candidate is NOT ADOPTED: unproven benefit is
   sufficient for non-adoption.
2. **Trigger-rate provenance**: the ~10% trigger rates (P1 10.38%,
   P3 10.14%) come from the historical fixed-context scope corpus. The
   fresh Arena did NOT record a live trigger rate (the overlay's
   in-process counters were not surfaced to the orchestrator this
   round), so the rate on fresh trajectories is unmeasured.
3. **Heuristic-seed audit condition**: the final audit's heuristic
   lineup check was initially too loose (a prefix match that any seed
   value would pass). It has been tightened to exact-args equality and
   the full audit re-run: ALL CHECKS PASS. Correction of the closure
   record: heuristic participates only in the second pairing, so the
   verification covers all 256 match lineups, of which **128 are
   heuristic-seat configs** (each exactly bound to the frozen args) —
   the other 128 are overlay-vs-n1 games; the earlier "256
   heuristic-seat configs" phrasing overcounted. (Provenance note: the
   closure commit 18f798d included this audit-code hardening, so it
   was a docs seal PLUS audit hardening, not a pure docs-only change;
   the coordinator independently confirmed the configs.)
4. **Overlay overhead**: the overlay's standalone single-step overhead
   (H* scoring on top of n1) was not separately measured this round;
   the Arena wall times (~22 s for 256 matches) bound it loosely.
   Descriptive gap only; no re-run.

## Result and interpretation (frozen wording)

The frozen `TakeTokens -> unique heuristic BuyMarket` overlay did NOT
demonstrate improvement over n1 at this budget:

> In the fresh 256-match confirmation Arena, the overlay-vs-n1 pairing
> finished 51-2-75 (center 4062.5 bps) with a 97.5% decision CI of
> [3125.0, 5000.0] — the interval touches the parity line, so the
> comparison is formally UNRESOLVED, though the point estimate favors
> plain n1. The overlay is resolved weaker than heuristic (3164.1 bps
> [2304.7, 4062.5]).

Reading notes (descriptive, post-hoc):

- The overlay fired at ~10% of n1 decisions (transferring the S2
  historical rate), so the null-ish result is not a "rule never fired"
  artifact — the rule acted frequently and did not help.
- The 95% CI for overlay-vs-n1 ([3242.2, 4882.8]) sits entirely BELOW
  5000; only the widened 97.5% decision interval touches parity. A
  stronger budget would plausibly resolve this against the overlay.
- Licensed conclusion: this specific single-rule overlay is not a
  demonstrated improvement; the heuristic gap is not closed by
  transplanting the buy-preference alone. NOT licensed: "the S2
  preference gap is worthless" (one rule, one carrier, one budget) or
  anything about combined/alternative candidates.

Per the frozen contract: UNRESOLVED stands (extra seeds are a user
decision, never automatic); no reference or promotion change; S2b
closes on review.

## Execution status and next authorized gate

Executed (single valid run, 2026-09-08): docs V2 -> exact-n1-only
overlay implementation -> exhaustive scope measurement (parity 100%,
P1 cross-check exact) -> 256-match fresh Arena -> 10k bootstrap (95% +
97.5%) -> final audit ALL CHECKS PASS -> tracked results. Verdict:
UNRESOLVED (vs n1; point estimate favors plain n1) / STRONGER_B (vs
heuristic).

Closure: the final review (2026-09-09) accepted UNRESOLVED and CLOSED
S2b (IMPROVEMENT_NOT_CONFIRMED / CANDIDATE_NOT_ADOPTED). No additional
seeds; no rule changes (any change would have reopened the design).
heuristic-v1 remains the primary development reference; the M07
historical champion and all promotion state are unchanged.

Standing follow-up states (per the coordinator's direction): S2
runner-up overlay NOT continued; neural evaluator STOP unchanged;
search tail-cost optimization retained as a backup direction (not
dead, not mainline — S1's n2000 p95 exceeded the gate by only ~0.24 s
while maxima reached 28 s/132 s; any future investment would first
profile wide-branching contexts and bound root-level work, never
loosen the gate); the next mainline direction is the S3 heuristic
full-policy rollout design (design-only).

Still NOT authorized (unchanged): M07 pairing, rule changes, tier-1
condition, bonus-usefulness condition, thresholds, weight tuning,
StaticEvaluator/search changes, extra seeds after UNRESOLVED,
promotion/default change.
