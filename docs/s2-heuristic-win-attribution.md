# S2 — Heuristic Win Attribution (why does heuristic-v1 beat n1/M07?)

STATUS     = PROPOSED (design-only, authorized by the S1 closure; execution
            NOT authorized until this design passes review)
BASELINE   = 2df0fcb (S1 closure, 2026-09-08)
OWNER-DATE = local implementation + cloud review, 2026-09-08

## Problem and evidence

### Research question

S0 calibrated the field: heuristic-v1 is the primary development
reference (resolved stronger than n1 at 6640.6 bps and M07 at 6875.0
bps, 98.33% joint-decision CIs). S1 showed depth-2 continuation search
misses the local cost gate (COMPUTE_INFEASIBLE) — depth-2's strength is
untested. The upstream question before ANY further candidate work is:

> **Why does heuristic stably beat n1/M07? On which decision classes
> does it actually win?**

This is deliberately NOT a rerun of M44/M45 evaluator micro-attribution.
Those rounds attributed static-evaluator information content on
engine-generated contexts against teacher proxies. S2 targets a
measured, strongest reference agent and asks a win-prediction question
on real game outcomes.

### What the evidence base already contains

- 384 S0 verified replays, of which **256 have heuristic participating**
  (P1: heuristic-vs-n1, P2: heuristic-vs-M07; 128 each, both rotations).
  Recorded actions include heuristic's actual choices AND n1/M07's
  actual choices in their seats.
- Per-context reconstruction machinery (S1's `s1-probe` pattern):
  any frozen policy can be re-run on any verified replay context with
  in-process timing and (for search agents) depth diagnostics.
- The heuristic's scoring function is pure-integer, term-decomposable
  code (`crates/splendor-agent/src/heuristic.rs`), currently exposing
  only the aggregate score — a small additive accessor can expose
  per-term contributions.

## Initial design

### Phase A1 — Disagreement census (exploration, development-set framing)

**Corpus**: all decision contexts from the 256 heuristic-participating
S0 replays where the mover was heuristic, n1, or M07, restricted to
`Phase::Main` with `>= 2` legal actions (same eligibility rule as S1;
sub-phases excluded). Expected scale: ~15–16k contexts.

**Method** (offline, deterministic, no new games):
1. For every context, compute the choices of all three frozen policies:
   heuristic (seed 20260812), n1 (20260703/s4/d1/n1), M07
   (20260703/s4/d1/n2000). Each policy's choice is recomputed on the
   context — for contexts where that policy was the recorded mover,
   the recomputation must equal the recorded action (fail-closed
   parity check; ties broken by the frozen tie-break rule are part of
   the policy).
2. Classify each context by:
   - **agreement set**: which of {H, n1, M07} agree on one action
     (e.g. H-alone, H+n1-vs-M07, all-differ, all-agree);
   - **action-type transition**: when the mover's recorded action
     differs from another policy's would-be action, the ordered pair
     (recorded_type -> would_be_type) — e.g. BuyMarket -> TakeTokens;
   - **game stage**: early/mid/late thirds by ply;
   - **market context flags**: gold available, viewer can buy now,
     noble proximity (cheap to compute from the observation).
3. **Win-correlation**: for heuristic-mover contexts, group by
   disagreement class and compare heuristic's eventual match win rate
   in games where the disagreement occurred vs games where all three
   policies agreed. Report per-class: count, win-rate delta, and a
   permutation-free summary (Wilson score intervals — descriptive, no
   significance gate in Phase A1).

### Phase A2 — Heuristic term attribution (exploration, same corpus)

For the contexts where heuristic's choice differs from BOTH search
policies (the "H-alone" class, expected to be the informative subset):

1. Expose per-term scoring contributions via an additive accessor on
   the heuristic (per-action term vector: category base, prestige,
   noble-gain, cost-efficiency, deficit-reduction, bonus-usefulness
   components, etc. — exactly the terms already computed internally;
   no behavior change, output-only).
2. For each such context, report which terms separate the heuristic's
   chosen action from the search policies' would-be action (term-level
   argmax decomposition of the score gap).
3. Aggregate: the distribution of dominant separating terms across the
   H-alone class, by stage.

### Phase A3 — Candidate-worthiness synthesis (no implementation)

The output of S2 is a **ranked table of recurring, interpretable,
outcome-correlated decision patterns** where heuristic's choice
diverges from the search family, each with:

- occurrence count and rate (per-class and per-stage),
- the term decomposition (what heuristic "sees" that the static
  evaluator-driven search does not),
- observed correlation with heuristic's wins (descriptive,
  Wilson-bounded),
- a hand-written mechanistic hypothesis (one paragraph each),
- and a candidate-worthiness checklist verdict.

The candidate-worthiness checklist (frozen here):
- **repeated**: >= 5% of heuristic-mover Main-phase contexts in the
  class;
- **interpretable**: the separating terms reduce to a named, quotable
  decision rule;
- **outcome-correlated**: the class's win-rate delta point estimate is
  positive (descriptive only — no causal claim);
- **implementable as a candidate**: expressible as a change to n1/M07's
  evaluation or a small decision overlay WITHOUT new search machinery.

S2's deliverable is at most ONE candidate hypothesis (the top-ranked
pattern passing all four checks) presented for review — **S2 does not
implement the candidate.** Whether to authorize an S2b implementation
is a separate review decision.

### Statistical framing (exploration, not confirmation)

Per the 2026-09-08 experiment-organization ruling: this round is
**development-set exploration with frozen method**. No strength claims,
no significance gates, no Arena. Wilson score intervals are reported
for transparency; "correlation" never becomes "causes". Any future
candidate that emerges gets its own frozen confirmation design (fresh
seeds, preregistered gates) before any strength claim.

## Scope and non-goals

- No new games (100% offline analysis of existing S0 replays).
- No changes to heuristic/n1/M07 behavior. The ONLY code addition is
  an output-only per-term accessor on the heuristic (additive,
  parity-locked like S1's diagnostics) and analysis scripts.
- No candidate implementation, no Arena, no promotion.
- No neural work; no search engineering; no depth-3+.
- No evaluator changes.

## Contracts and invariants

- Recomputed-choice parity: on every context, a policy recomputation
  must equal that policy's recorded action when it was the mover
  (fail-closed audit; the S0 replays bind this).
- All three policies run with their exact frozen configs (heuristic
  20260812; search 20260703/s4/d1/n{1,2000}).
- The eligibility rule, classification taxonomy, term decomposition,
  and candidate-worthiness checklist are frozen in this document
  BEFORE any census output is seen.
- Exploration results are labeled descriptive; no post-hoc promotion
  of any pattern to "the reason heuristic wins".

## Implementation plan

1. Rust: additive `heuristic_term_scores(observation, actions) ->
   Vec<TermScores>` accessor (output-only; `score_actions` internals
   refactored to share the computation; existing behavior
   bit-identical, parity-locked by test).
2. `scripts/s2_census.py`: corpus extraction (256 replays x Main-phase
   contexts), three-policy recomputation via the s1-probe pattern
   (heuristic needs a small probe path too — reuse the same command
   shape), disagreement classification, win correlation, tracked
   intermediate result (local + compact tracked summary).
3. `scripts/s2_term_attribution.py`: H-alone class term decomposition.
4. `docs/s2-heuristic-win-attribution.md` closure: ranked pattern
   table + at most one candidate hypothesis + review request.

## Estimated cost

- ~15–16k contexts x 3 policy recomputations; heuristic ~0 cost, n1
  ~1.5 ms, M07 ~12–14 ms per decision (S0-measured) → M07 dominates:
  ~16k x ~13 ms ≈ 3.5 min; total well under 30 min including I/O.
- No GPU, no Arena, no new games.

## Known limitations

- Win-correlation is per-game aggregation over a small corpus (256
  games); Wilson intervals will be wide for rare classes — that is
  why the checklist uses rate + interpretability, not significance.
- The census measures POLICY divergence on recorded positions; it
  cannot see counterfactual game continuations (that is a candidate
  question, not an attribution question).
- Heuristic's tie-break RNG consumes entropy only on exact-score ties;
  recomputation must replicate the recorded stream (the S0 replay
  binds this — parity check will catch any drift).
- A pattern passing the checklist is a hypothesis, not a validated
  improvement; S2 explicitly stops before implementation.

## Next authorized gate

- Cloud review of this design (corpus, taxonomy, term decomposition,
  checklist, and the no-implementation boundary).
- After APPROVE: Phase A1 census → A2 attribution → A3 synthesis →
  S2 closure review with the ranked table and (at most) one candidate
  hypothesis.
