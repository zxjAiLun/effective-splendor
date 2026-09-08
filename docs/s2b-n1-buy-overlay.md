# S2b — n1 Buy-Overlay Confirmation (parameter-free candidate)

STATUS     = PROPOSED (design-only, authorized by the S2 closure; execution
            NOT authorized until this design passes review)
BASELINE   = d409801 (S2 closure, 2026-09-08)
OWNER-DATE = local implementation + cloud review, 2026-09-08

## Problem and evidence

### The hypothesis under test

S2 (closed at d409801) found: in 11.27% of eligible SEARCH_ACTOR
Main-phase contexts (853/7,570), the acting frozen search baseline
(n1 or M07) chose `TakeTokens` while heuristic-v1 — the S0-calibrated
primary reference — had a unique `BuyMarket` optimum. The divergence is
overwhelmingly driven by heuristic's Buy-vs-Take category prior
(900,000 base difference vs gap median 881,800), with bonus_usefulness
further favoring the buy in 851/853 cases and noble_gain in 0/853. S2
established a high-frequency, cross-opponent, simple, strict
preference gap — and explicitly did NOT establish that overriding those
decisions improves playing strength.

S2b asks exactly that question with the smallest possible candidate:

> **Does overriding ONLY those 853-shaped decisions — with a
> parameter-free rule carrying no coefficients — improve n1's playing
> strength?**

### The candidate (frozen; zero free parameters)

```text
base_action = n1(s)                       # frozen n1: 20260703 / s4 / d1 / n1

H*(s) = argmax-set of heuristic scoring   # frozen heuristic terms, seed-free
                                             # (H* is deterministic; the RNG
                                             # tie-break is NEVER invoked)

if:
    base_action is TakeTokens
    AND |H*(s)| == 1
    AND the unique H* action is BuyMarket
then:
    candidate_action = that unique BuyMarket action
else:
    candidate_action = base_action        # bit-identical to n1
```

No coefficients, no thresholds, no weights, no stage/flag conditions.
The rule is exactly the S2 nominee pattern; nothing else is tuned.

Why n1 as the carrier (S2 closure rationale): n1-vs-M07 strength is
UNRESOLVED (S0) while n1 is ~an order of magnitude cheaper (S0
telemetry); if the overlay improves n1, that is the highest-value
engineering result available. This is explicitly NOT a
StaticEvaluatorV1 weight sweep — the frozen evaluator is untouched.

## The four questions this design must pin (per the S2 closure review)

### 1. Behavioral scope (measured, not assumed)

Before any Arena, the implementation phase measures on a development
corpus exactly:

- how many n1 decisions the overlay modifies (count + rate);
- confirmation that all other decisions are **bit-identical** to n1
  (fail-closed parity: replay the same games under candidate vs n1 and
  assert identical actions wherever the trigger condition is false).

**Development corpus**: the S0 P3 replays (n1-vs-M07 games, 128
replays — n1's own mover contexts) PLUS the S0 P1 replays' n1 seats.
This is the SAME corpus family the nominee was discovered on — which is
fine for a SCOPE measurement (how often the rule fires), because scope
is a property of the rule + position distribution, not an outcome
claim. The confirmation of strength uses fresh seeds (question 3).
Expected rate from S2: ~11% of n1 Main-phase decisions; the design
does not assume a number — it measures.

### 2. No offline tuning

The candidate is the single frozen rule above. Between implementation
and Arena, NO iteration on the rule, no corpus-driven re-reading, no
threshold adjustments. If the behavioral-scope measurement reveals an
implementation bug, it is fixed and the scope re-measured (bug fix, not
tuning). Any proposed rule change reopens this design for review.

### 3. Fresh confirmation Arena (strength only)

- **Seeds**: fresh segment `5_800_192 .. 5_800_255` (64 seeds;
  immediately after the S1 segment 5_800_128..191 which was reserved
  but NOT consumed — the registry is extended and disjointness
  re-asserted; if the S1 segment is preferred for reuse instead, that
  is a design-review decision, default is the fresh segment).
- **Pairings** (2 mandatory): `candidate vs n1` and `candidate vs
  heuristic` — 64 blocks x 2 rotations = 128 matches each, 256 total.
- **M07 third pairing**: DECIDED AT DESIGN REVIEW (default: include,
  128 more matches, 384 total — the full must-not-regress set; the
  S2 closure left this open because the direct causal question is
  "does fixing n1 work", but the S0 conservative rule keeps all three
  as regression anchors).
- **Statistical protocol**: S0/S1 frozen protocol (paired-block
  bootstrap, 10,000 resamples, seed 43_200_001; 95% descriptive CI;
  98.33% joint-decision CI for the family; UNRESOLVED stands).
- **Success criterion** (frozen): the candidate must show a RESOLVED
  improvement over n1 (98.33% CI entirely above 5000 in the
  candidate-vs-n1 pairing) AND must not clearly lose to heuristic
  (no resolved heuristic win at the same level in candidate-vs-
  heuristic). Offline disagreement rates are NOT a success criterion
  and are not reported as one.

### 4. Decision table (frozen)

| Outcome (98.33% CIs) | Verdict | Decision |
|---|---|---|
| Resolved win vs n1 AND not resolved loss vs heuristic (and M07 if included) | **CONFIRMED** | Overlay becomes part of the development reference lineage; a promotion-grade evaluation may be designed separately |
| Resolved win vs n1, resolved loss vs heuristic | **SPLIT_CONFIRMATION** | Report as-is: the overlay improves the carrier but the reference gap persists; no reference change |
| UNRESOLVED vs n1 | **UNRESOLVED** | No conclusion at this budget; extra seeds are a user decision, never automatic |
| Resolved loss vs n1 | **REFUTED** | Valid negative result, sealed: the S2 nominee preference does not transfer to strength under this contract |

Cost data (per-decision telemetry, S0-style) is recorded but never
overrides strength verdicts.

## Scope and non-goals

- No StaticEvaluatorV1 changes, no search changes, no heuristic
  behavior changes (the heuristic's scoring is only READ).
- No parameter sweep of any kind; the rule is frozen before
  implementation begins.
- No M07 modification (the overlay targets n1 only).
- No new offline attribution; S2 is closed.
- No promotion / champion-title change in any outcome.
- No neural work, no depth-3+, no search engineering.

## Contracts and invariants

- Candidate behavior outside the trigger is bit-identical to n1
  (fail-closed parity in the scope measurement AND spot-checked in the
  final audit).
- H* is computed with the frozen heuristic term scoring
  (deterministic; no tie-break RNG consumption — the trigger requires
  |H*| == 1, so ties never fire the overlay).
- The trigger set is exactly the S2 nominee pattern
  (TakeTokens -> unique BuyMarket); any deviation reopens the design.
- Arena identities bind the exact agent args (candidate = n1 args +
  overlay flag; opponents = frozen S0 configs).
- Fresh-seed disjointness is asserted before any match runs.

## Implementation plan

1. Rust: `agent-determinization` gains a default-off
   `--heuristic-buy-overlay` flag (composition: run n1, compute H*,
   apply the frozen rule). Parity test: flag off == plain n1
   bit-exact; flag on changes ONLY trigger-set decisions (unit tests
   with constructed trigger/non-trigger contexts).
2. Scope measurement (development corpus): modified-decision count +
   rate; bit-identical assertion elsewhere.
3. `scripts/s2b_orchestrator.py`: fresh-seed Arena (2 or 3 pairings
   per the review decision), S0 statistical protocol, tracked result.
4. `scripts/s2b_final_audit.py`: fail-closed recheck (lineup, replay
   verification, parity spot-checks, recomputation, decision table).
5. Closure docs + handoff; S2b closure review.

## Estimated cost

- Overlay decision overhead: H* computation is ~0-cost (integer
  scoring); n1 base ~1.5 ms (S0) — candidate ≈ n1 cost.
- Scope measurement: ~7.9k n1 contexts re-decided, ~2-3 min.
- Arena 256-384 matches at ~n1+heuristic cost: by S0 precedent
  (67 s for 384 matches at similar per-decision costs) the whole
  Arena is minutes-scale; call it < 15 min including audit.
- No GPU.

## Known limitations

- The overlay fires ~11% of n1 Main-phase decisions (per S2's corpus
  family); if the true rate differs on fresh-seed games, the scope
  measurement reports it, and the Arena still measures what matters.
- 64 blocks may leave pairings UNRESOLVED (accepted standing outcome).
- A CONFIRMED result does not auto-promote anything: promotion remains
  a separate formal process; the reference lineage question is
  explicit in the decision table.
- The candidate does not address the reserve_market->take_tokens
  runner-up pattern (recorded, untested — a separate future question).

## Next authorized gate

- Cloud review of this design: (a) the frozen rule wording; (b) the
  scope-measurement corpus choice; (c) the seed segment; (d) the
  M07-third-pairing decision; (e) the decision table.
- After APPROVE: implementation per plan (flag -> parity -> scope
  measurement -> Arena -> final audit -> closure review).
