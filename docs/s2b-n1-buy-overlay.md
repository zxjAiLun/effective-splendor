# S2b — n1 Buy-Overlay Confirmation (parameter-free candidate)

STATUS     = APPROVED / FROZEN (S2b DESIGN_V2 review verdict on adddbe2:
            candidate rule, n1 carrier, fresh-Arena confirmation,
            no-tuning, and heuristic-as-anchor all APPROVED; P1-1/P1-2/
            P1-3 + P2-1..3 revisions applied docs-only; the full chain —
            implementation, exhaustive fixed-context scope measurement,
            P1 identity cross-check, 256-match fresh Arena, 10k
            bootstrap, final audit, tracked result — is automatically
            authorized; S2b closure review at the end)
REVISION   = V2 2026-09-08 — review repairs: scope parity is fixed-context
            pointwise (never trajectory-replay comparison); the overlay
            flag fail-closed binds the EXACT n1 identity (20260703/s4/
            d1/n1/StaticEvaluatorV1) so the candidate cannot silently
            attach to non-n1 configs; the Arena family is TWO pairings
            only (overlay vs n1, overlay vs heuristic — M07 NOT run) with
            a 97.5% two-sided decision CI (Bonferroni for 2 comparisons)
            plus a 95% descriptive CI; "the 853 decisions" narrowed to
            "rule-shaped decisions on fresh states"; scope corpus split
            into P1 (S2 discovery overlap) vs P3 (additional development
            corpus); overhead is measured, not asserted; scope parity is
            exhaustive, not spot-checked. V1 = adddbe2.
BASELINE   = d409801 (S2 closure, 2026-09-08)
OWNER-DATE = local implementation + cloud review, 2026-09-08

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

## Authorized execution path (per DESIGN_V2 review)

1. Docs-only V2 (this document).
2. Implement the exact-n1-only overlay.
3. Exhaustive fixed-context scope measurement.
4. P1 identity-set cross-check against S2.
5. Tests / parity.
6. Fresh 256-match Arena.
7. 10k paired bootstrap (95% descriptive + 97.5% decision).
8. Final audit.
9. Tracked result.
10. Return for closure review.

Still NOT authorized: M07 pairing, rule changes, tier-1 condition,
bonus-usefulness condition, thresholds, weight tuning,
StaticEvaluator/search changes, extra seeds after UNRESOLVED,
promotion/default change.
