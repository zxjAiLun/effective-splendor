# S2 — Heuristic Win Attribution (why does heuristic-v1 beat n1/M07?)

STATUS     = EXECUTED (design APPROVED/FROZEN at 82fc400; A1 -> A2 -> A3
            executed 2026-09-08 with all parity gates PASS; verdict
            ACTIONABLE_HYPOTHESIS_FOUND — nominee presented for review,
            NOT implemented; awaiting S2 closure review)
RESULT     = One candidate hypothesis: on SEARCH_ACTOR contexts where the
            frozen search policies take tokens, heuristic's unique
            optimum is to BUY a tier-1 card (853 strict divergences =
            11.27% of SEARCH_ACTOR Main contexts; 248 of 256 games;
            game-level exposed-vs-unexposed H win-rate delta positive in
            both opponent strata: n1 +0.169, M07 +0.194). The separating
            score gap is category-dominated (buy category prior over
            take) with a positive bonus_usefulness feature component in
            98.7% of cases. This is heuristic PREFERENCE attribution —
            not search information absence, and not a validated
            improvement.
REVISION   = V2 2026-09-08 (frozen, 82fc400) — executed as frozen.
            V1 = 9fa76a8.
BASELINE   = 2df0fcb (S1 closure, 2026-09-08)
OWNER-DATE = local implementation + cloud review, 2026-09-08

## Problem and evidence

### Research question

S0 calibrated the field: heuristic-v1 is the primary development
reference (resolved stronger than n1 at 6640.6 bps and M07 at 6875.0
bps, 98.33% joint-decision CIs). S1 showed depth-2 continuation search
misses the local cost gate (COMPUTE_INFEASIBLE); depth-2's strength is
untested. The upstream question before any further candidate work:

> **In the real positions the weaker search baselines actually reached,
> what stable, strict, interpretable preferences does heuristic hold
> that differ from them; in which wins do those preferences appear; and
> is there ONE rule worth a separate confirmation round?**

This is heuristic PREFERENCE ATTRIBUTION — not search information
absence proof (the search/evaluator may encode the same information
with different weights or composition).

Distinct from M44/M45 evaluator micro-attribution: the target is the
measured strongest reference agent and the question is win association
on real game outcomes, not information content against teacher proxies.

### Data base

- 256 heuristic-participating S0 replays (P1 heuristic-vs-n1, P2
  heuristic-vs-M07; 128 each, both rotations) — recorded actions bind
  every mover's actual choice.
- The s1-probe context-reconstruction pattern (verified replay ->
  rebuilt state -> live frozen policy), to be wrapped in a BATCHED
  in-process census harness (read replay -> reconstruct contexts ->
  invoke frozen policies -> emit rows; no per-context subprocess —
  process startup would dominate M07's ~13 ms/decision).

## Actor roles (frozen)

Every context has an actor role:

- **REFERENCE_ACTOR**: heuristic is the mover. "What would n1/M07 have
  chosen here?" is an explanatory counterfactual.
- **SEARCH_ACTOR**: n1 or M07 is the mover. The search policy REALLY
  reached this position and chose its recorded action; heuristic
  scoring strictly prefers something else. This directly corresponds to
  a decision a future n1/M07 modification would change.

The two roles are reported in SEPARATE tables and never mixed.
Candidates come from SEARCH_ACTOR contexts only.

## Phase A1 — Disagreement census (set-aware, game-unit outcomes)

### Corpus

All eligible contexts from the 256 heuristic-participating S0 replays:
`Phase::Main`, `legal_actions >= 2`. **No occurrence dedupe** — repeated
information-set patterns across games are exactly the frequency signal
we measure. Expected scale ~15-16k contexts.

### Heuristic semantics: the score-optimal SET

heuristic's score is deterministic; its `StableRng` is consumed only on
exact-score ties, and the arena RNG stream state at a given ply cannot
be reconstructed for counterfactual movers. Therefore the census NEVER
generates a counterfactual heuristic tie-break action. Instead, per
context:

    H*(o) = { a in legal(o) : score_H(o, a) = max_b score_H(o, b) }

n1 and M07 each still produce their unique frozen action (deterministic
search; recomputation must exactly equal their recorded action on their
own mover contexts).

### Per-context record

    game_id, seed block, heuristic seat, opponent (n1 | M07),
    actor, actor_role (REFERENCE_ACTOR | SEARCH_ACTOR),
    ply, stage bin, game outcome (H win / loss / tie),
    identity triple, legal action count,
    H* (set of actions), |H*|,
    a_n1, a_M07 (the frozen search actions),
    gold_available, any_buy_legal

Stage bins are FIXED absolute ply bins (not game-length thirds):

    early = ply 1..20; mid = ply 21..45; late = ply 46+

### Set-aware disagreement classification (per search policy X in {n1, M07})

    X_IN_H*            (a_X in H*)
    X_NOT_IN_H*_UNIQUE (|H*| == 1 and a_X != the unique H action)  -> STRICT divergence
    X_NOT_IN_H*_TIE    (|H*| > 1 and a_X not in H*)

Tie rate (|H*| > 1) is reported separately so RNG tie artifacts cannot
masquerade as strategic disagreement.

### Outcome association (game unit, stratified)

Occurrence unit = context (counts, rates, transition distributions,
stage distributions). Outcome unit = GAME (Wilson interval n = games):

For a preregistered pattern P and game g: exposure_P(g) = 1 iff P
occurs at least once in g. Report the exposed-vs-unexposed H win-rate
delta, stratified:

    opponent = n1  | opponent = M07          (never pooled only)
    heuristic seat 0 | seat 1                (S0 rotated seats)

Pooled numbers may appear as descriptive extras, never alone.

### Parity gates (fail-closed)

1. On every REFERENCE_ACTOR context: `recorded_action in H*` must hold
   100%; when `|H*| == 1`, `recorded_action == the unique H action`.
2. On every SEARCH_ACTOR context: the recomputed frozen search action
   equals the recorded action, exactly (n1 and M07 separately).

## Phase A2 — Term attribution (strict divergence only)

### Term contract (frozen; exact mapping of existing internals)

Per-action `HeuristicTermScores`, additive, sharing ONE computation
helper with `score_actions` (no second formula):

    category_base        (SCORE_BUY / SCORE_TAKE / SCORE_RESERVE_VISIBLE /
                          SCORE_RESERVE_BLIND / SCORE_PASS / ChooseNoble base)
    prestige             (buy: prestige * BUY_PRESTIGE; reserve-visible:
                          prestige * RESERVE_PRESTIGE)
    noble_gain           (buy: completed-noble gain * BUY_NOBLE_GAIN)
    noble_direct         (ChooseNoble: NOBLE_DIRECT)
    bonus_usefulness     (buy/reserve-visible: bonus_useful[color] *
                          BONUS_USEFULNESS_WEIGHT)
    cost_efficiency      (buy: -total_cost * BUY_COST_EFFICIENCY)
    deficit_reduction    (take: deficit delta * TAKE_DEFICIT_REDUCTION)
    new_target           (take: newly-affordable count * TAKE_NEW_TARGET)
    return_penalty       (take/reserve: -give_back * TAKE_RETURN_PENALTY)
    gold_value           (take: gold * TAKE_GOLD_VALUE)
    reserve_proximity    (reserve-visible: -deficit * RESERVE_PROXIMITY)
    reserve_gold         (reserve-visible: +RESERVE_GOLD when gold available)
    reserve_blind_gold   (reserve-deck: +RESERVE_BLIND_GOLD when gold
                          available)
    total                (== score_actions result)

Inapplicable terms are 0. HARD GATE: sum(terms) == score_H(a) for 100%
of analyzed legal actions (asserted per action; any mismatch fails the
census).

### Gap analysis (strict divergence only)

For strict divergence (|H*| == 1, a_X != unique H action) with
h = the unique H action and s = a_X:

    delta_t = term_t(h) - term_t(s)          (signed, per term)
    sum_t delta_t = score_H(h) - score_H(s) > 0   (asserted)

Dominant separating term(s) = the maximum positive delta_t (ties kept,
never arbitrarily broken). Reported SEPARATELY:

    category_base gap
    feature subtotal (sum of all non-category terms)

because the category priors are huge (Buy 1,000,000 / Take 100,000) —
a Buy->Take transition dominated by category_base says "the categories
differ", while a feature-subtotal-dominated gap says the preference
lives inside a category. Both are results; they answer different
questions.

Attribution wording (frozen): "term T contributes strongly to
heuristic's preference in these disagreements". NEVER "search does not
see T".

## Phase A3 — Candidate synthesis (frozen grammar + ranking)

### Candidate grammar (closed)

A candidate pattern key is EXACTLY:

    (recorded search action type -> unique H action type)

optionally conjoined with ONE fixed stage bin:

    (transition) x {early | mid | late}

Market flags (gold_available, any_buy_legal) and term dominance are
ANNOTATIONS on reported patterns — they never enter pattern keys. No
other conjunctions are permitted. This forecloses post-hoc
conjunction mining.

Market flag definitions (exact):

    gold_available = bank.gold > 0
    any_buy_legal  = legal actions contain BuyMarket or BuyReserved

(noble proximity dropped: no cheap exact definition was preregistered.)

### Candidate gates (frozen hypothesis filter — not significance gates)

A pattern may become the S2 nominee ONLY if ALL hold:

1. **repeated**: >= 5% of all eligible SEARCH_ACTOR Main contexts (the
   rate is per context, occurrence unit);
2. **cross-opponent**: the pattern occurs in BOTH the n1 and the M07
   opponent strata;
3. **outcome-associated**: the game-level exposed-vs-unexposed H
   win-rate delta POINT ESTIMATE is positive in BOTH opponent strata;
4. **interpretable / implementable**: expressible as a named rule
   implementable via evaluator change or a small decision overlay —
   no new search machinery.

### Ranking (frozen, frequency-first)

If more than one pattern passes all four gates, rank by:

    1. higher SEARCH_ACTOR occurrence rate
    2. higher distinct-game coverage
    3. lexical pattern id (deterministic tie-break)

NEVER by win-delta magnitude (selecting the luckiest outcome noise on
development data). Rank 1 becomes the single S2 nominee.

### Exits (frozen)

    ACTIONABLE_HYPOTHESIS_FOUND   (exactly one nominee, presented for review)
    NO_ACTIONABLE_PATTERN         (a fully legitimate result — the 5% gate
                                   is NOT relaxed to force a candidate)

Neither exit authorizes implementation. S2b (candidate implementation
+ frozen confirmation design) is a separate review decision.

## Scope and non-goals

- No new games (100% offline analysis of existing S0 replays).
- No behavior changes to heuristic/n1/M07. The ONLY code additions:
  the additive output-only `HeuristicTermScores` accessor (parity-
  locked), and a batched in-process census harness (analysis tooling,
  not agent/search behavior).
- No candidate implementation, no Arena, no promotion, no neural, no
  search engineering, no depth 3+, no evaluator changes.
- Exploration results are descriptive; no causal claims; any future
  candidate gets its own frozen confirmation design with fresh seeds
  and preregistered gates.

## Implementation plan

1. Rust: `heuristic_term_scores(observation, actions) -> Vec<HeuristicTermScores>`
   sharing the computation with `score_actions` via one helper; hard
   additive parity gate + regression test.
2. Rust: batched census harness (CLI): read a replay, reconstruct
   eligible Main contexts, invoke the three frozen policies in-process
   (H* set via term accessor totals; n1/M07 via their policies), emit
   per-context JSONL rows including parity fields.
3. `scripts/s2_census.py`: A1 aggregation (set-aware classification,
   stratified game-level exposure win association, parity gates).
4. `scripts/s2_term_attribution.py`: A2 strict-divergence gaps.
5. A3 synthesis script + `docs/s2-heuristic-win-attribution.md`
   closure: ranked table, nominee or NO_ACTIONABLE_PATTERN, review
   request. Tracked descriptive result JSON.

## Estimated cost

Batched in-process census: ~15-16k contexts x (H ~free + n1 ~1.5 ms +
M07 ~12-14 ms) -> M07 dominates, ~4-6 min compute plus I/O; the
16k x 3 x subprocess path is explicitly rejected (startup dominates).
Engineering budget < 30 min total, no GPU, no new games.

## Known limitations

- Win association is per-game over 256 games; Wilson intervals are
  wide for rare strata — the checklist uses rate + interpretability,
  not significance.
- The census measures policy divergence on recorded positions; it
  cannot see counterfactual continuations (a candidate question).
- Game-level exposure ignores within-game repetition counts (a game
  with 12 occurrences counts once) — conservative by design.
- A passing pattern is a hypothesis for a SEPARATE confirmation round,
  not a validated improvement; S2 stops before implementation.

## Validation and evidence

### Execution — 2026-09-08 (single valid pass)

Implementation (in-scope only):
- `HeuristicTermScores` accessor: the score decomposition shares the
  computation with `score_actions` via term-level structs; buy-prestige
  stays folded into the buy category base EXACTLY as the historical
  arithmetic computed it, so totals are bit-identical. Hard parity gate
  (sum of terms == aggregate score for 100% of legal actions across
  seed-spread states) locked by regression tests; workspace 774/0.
- `splendor s2-census` batched in-process harness (no per-context
  subprocess): per replay, per eligible context — H* set (via term
  totals), both frozen search actions (recomputed), stage bin, market
  flags, winner seats. `--emit-terms` adds signed per-term gap rows at
  |H*|==1 divergences for both policies.
- `scripts/s2_census.py` (A1) and `scripts/s2_term_attribution.py`
  (A2+A3).

Parity gates (all PASS, 100%):
1. REFERENCE_ACTOR: `recorded_action in H*` — and exact-equal when
   |H*|==1 — on every heuristic-mover context.
2. SEARCH_ACTOR: recomputed frozen action == recorded action on every
   search-mover context (n1 and M07 separately).
3. Term-gap parity: sum of signed deltas == score gap > 0 on every
   strict-divergence row (4,063 rows).

### A1 — census (256 games, 15,143 Main contexts)

Role split: REFERENCE_ACTOR 7,573 / SEARCH_ACTOR 7,570. Tie rate
(|H*|>1): 749 / 667 respectively (reported so tie artifacts cannot
masquerade as disagreement).

Set-aware classification (SEARCH_ACTOR, per opponent):
- n1: X_IN_H* 1,624 / X_NOT_IN_H*_UNIQUE 1,868 / X_NOT_IN_H*_TIE 228
- M07: X_IN_H* 1,399 / X_NOT_IN_H*_UNIQUE 2,195 / X_NOT_IN_H*_TIE 256

SEARCH_ACTOR strict divergences total: 4,063. Top transitions (of
7,570 SEARCH_ACTOR contexts): take_tokens->buy_market 853 (11.27%),
buy_market->buy_market 630, reserve_market->take_tokens 568 (7.50%),
take_tokens->take_tokens 531, reserve_market->buy_market 483.

### A2 — term attribution (4,063 strict divergences)

Dominant separating terms: category_base 2,451; bonus_usefulness
1,029; deficit_reduction 487; cost_efficiency 52; new_target 44;
noble_gain 1. Category-dominated 2,451 vs feature-dominated 1,612.

### A3 — candidates passing all four frozen gates (3 of 14x4 patterns)

| Pattern | Rate | Games | delta n1 | delta M07 |
|---|---:|---:|---:|---:|
| **take_tokens->buy_market** (nominee) | 0.1127 (853) | 248 | +0.169 | +0.194 |
| reserve_market->take_tokens | 0.0750 (568) | 235 | +0.070 | +0.255 |
| reserve_market->take_tokens|early | 0.0532 (403) | 214 | +0.048 | +0.089 |

Frequency-first ranking (rate, then game coverage, then lexical id)
selects take_tokens->buy_market as the single S2 nominee.

### Nominee annotation (descriptive, not part of the pattern key)

- The H action is a BUY of a tier-1 card in 3,362/3,386 pre-filter gap
  rows (tier-2 in 24).
- Stage spread: early 540 / mid 1,806 / late 1,040 — concentrated in
  mid but present throughout.
- Score gap p50 881,800 [min 830,800, max 1,011,800] — buy-category
  prior dominated (3,386/3,386 category-dominant), with a positive
  bonus_usefulness feature component in 3,344/3,386 (98.7%); noble_gain
  positive in only 8; the take's own feature positives (deficit
  reduction, new targets) are exceeded by the category gap in every
  case.
- Interpretation (heuristic preference attribution, frozen wording):
  when the frozen search policies choose TakeTokens, heuristic's unique
  optimum is buying a cheap (mostly tier-1) card whose bonus color is
  useful for its targets. The search baselines' static evaluator
  evidently ranks the take higher in these positions; whether
  transplanting a buy-bias would improve THEM is the S2b question, NOT
  answered here.

### Tracked artifacts

- `benchmarks/s2-heuristic-win-attribution-v1.result.json` (git-blob
  SHA recorded after commit).
- Raw census rows + term-gap rows under ignored
  `local-artifacts/s2-census/` (cloud evidence boundary as in S0/S1).

## Result and decision

**Verdict: ACTIONABLE_HYPOTHESIS_FOUND.** The S2 nominee is
`take_tokens->buy_market` on SEARCH_ACTOR strict divergences. Per the
frozen contract, this authorizes NOTHING beyond presenting the
hypothesis: S2b (candidate implementation + frozen confirmation design
with fresh seeds and preregistered gates) is a separate review
decision. The two reserve_market->take_tokens patterns are recorded as
runner-ups (they pass all four gates; frequency-first ranking placed
them below the nominee).

Non-claims (frozen): this is heuristic preference attribution, not
search information absence; the deltas are game-level associations on
256 games (Wilson-wide), not causal effects; the nominee is a
hypothesis, not a validated improvement.

## Execution status and next authorized gate

Executed: (1) term accessor + parity tests; (2) batched census harness;
(3) A1 census — parity gates PASS; (4) A2 term attribution — term-gap
parity PASS; (5) A3 synthesis — ACTIONABLE_HYPOTHESIS_FOUND, nominee
`take_tokens->buy_market`; tracked result + this closure doc.

Next gate: **S2 closure review.** The review decides whether S2b (a
candidate implementing the nominee, evaluated under a frozen
confirmation design with fresh seeds and preregistered gates) is
authorized, deferred, or rejected. S2 itself implements nothing.

Still NOT authorized (unchanged): candidate implementation (S2b), new
Arena, new self-play, search engineering, evaluator behavior change,
heuristic behavior change, neural work, promotion/default-agent
change.
