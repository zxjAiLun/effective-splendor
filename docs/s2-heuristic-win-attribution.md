# S2 — Heuristic Win Attribution (why does heuristic-v1 beat n1/M07?)

STATUS     = REPAIR 1 EXECUTED (final review of 96a09c6 found P1:3 —
            Buy term mapping violated the frozen contract, seat
            stratification missing, nominee annotations computed on the
            wrong set; narrow repair authorized and executed 2026-09-08:
            A1 census rows NOT regenerated; term-gap pass re-run with the
            corrected mapping; exposure tables re-aggregated with
            opponent x seat stratification; nominee annotations computed
            on the exact 853 SEARCH_ACTOR take->buy occurrences; A3
            re-synthesized under the same frozen grammar/gates/ranking;
            verdict unchanged — ACTIONABLE_HYPOTHESIS_FOUND; awaiting
            closure re-review)
RESULT     = Nominee (unchanged by repair): take_tokens->buy_market on
            SEARCH_ACTOR strict divergences — 853 occurrences (11.27% of
            7,570 SEARCH_ACTOR Main contexts), 248/256 games, pooled
            game-level win delta n1 +0.169 / M07 +0.194 (gate-passing
            descriptive point estimates). Repaired nominee annotations:
            H buys tier-1 in 841/853; category_base dominates the score
            gap in 853/853 (buy prior over take); bonus_usefulness
            positive in 851/853; noble_gain positive in 0/853; score
            gap p50 881,800 [841,750, 931,600]. Seat-stratified tables
            reveal thin unexposed controls (e.g. n1|seat0: 1 unexposed
            game) — the pattern occurs in almost every game, so the
            exposure delta is NOT the candidate's main evidence; the
            frequency (11.27%) is. Heuristic preference attribution —
            not search information absence, not a validated improvement.
REVISION   = V2 2026-09-08 (frozen, 82fc400) — executed; Repair 1 per
            final review of 96a09c6. V1 = 9fa76a8.
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

### A2 — term attribution (4,063 strict divergences; REPAIRED)

Repair note: the initial execution folded buy prestige into
category_base, violating the frozen term contract; Repair 1 separates
them (category_base = bare SCORE_BUY; prestige = prestige x
BUY_PRESTIGE) with a dedicated regression asserting the exact frozen
Buy mapping beyond total parity. Corrected numbers:

Dominant separating terms: category_base 2,428; bonus_usefulness
1,029; deficit_reduction 487; cost_efficiency 52; new_target 44;
prestige 23; noble_gain 1. Category-dominated 2,428 vs
feature-dominated 1,635.

(For the record, the pre-repair numbers — category 2,451 / feature
1,612 — were computed under the wrong mapping and are superseded.)

### A3 — candidates passing all four frozen gates (3 of 14x4 patterns)

| Pattern | Rate | Games | delta n1 | delta M07 |
|---|---:|---:|---:|---:|
| **take_tokens->buy_market** (nominee) | 0.1127 (853) | 248 | +0.169 | +0.194 |
| reserve_market->take_tokens | 0.0750 (568) | 235 | +0.070 | +0.255 |
| reserve_market->take_tokens|early | 0.0532 (403) | 214 | +0.048 | +0.089 |

Frequency-first ranking (rate, then game coverage, then lexical id)
selects take_tokens->buy_market as the single S2 nominee.

Gate-4 rationale (recorded per review, for each gate-passing pattern):
take_tokens->buy_market is implementable as an n1 decision overlay that
triggers only when n1 selects TakeTokens and heuristic has a unique
BuyMarket optimum; requires no new search machinery.
reserve_market->take_tokens (runner-up) is implementable analogously
(overlay when the search reserves visible and heuristic's unique
optimum is a TakeTokens action).

### Nominee annotation (REPAIRED: computed on the exact 853 occurrences)

The pre-repair annotation mixed in REFERENCE_ACTOR rows,
counterfactual-policy rows, and non-opponent rows (3,386 pre-filter
gap rows). The repaired annotation is computed ONLY on the 853
SEARCH_ACTOR, actual-opponent, strict-divergence take_tokens->
buy_market occurrences (asserted == 853, joined to their repaired
term-gap rows):

- H buys a tier-1 card in 841/853 (tier-2 in 12).
- Stage spread: early 129 / mid 432 / late 292 — mid-concentrated but
  present throughout.
- Score gap p50 881,800 [min 841,750, max 931,600].
- Dominant separating term: category_base in 853/853 — even with
  prestige correctly separated, the buy-category prior over the
  take-category prior dominates every single gap.
- bonus_usefulness positive in 851/853; noble_gain positive in 0/853.
- Interpretation (heuristic preference attribution, frozen wording):
  when the frozen search policies choose TakeTokens, heuristic's unique
  optimum is buying a cheap tier-1 card whose bonus color is useful for
  its targets; the separating score is dominated by the category prior
  with a near-universal positive bonus_usefulness component and NO
  noble-completion component. The search baselines' static evaluator
  evidently ranks the take higher in these positions; whether
  transplanting this preference would improve THEM is the S2b question,
  NOT answered here.

### Seat-stratified exposure (repair addition)

The frozen seat stratification (omitted in the initial execution) is
now reported. Key reading: the pattern occurs in 248/256 games, so
unexposed control groups are tiny (1-8 games per stratum); e.g.
n1|seat0 has ONE unexposed game. The pooled deltas (+0.169 / +0.194)
are gate-passing descriptive point estimates over ~124/4 exposure
splits — the pattern's real evidence is its 11.27% decision frequency,
not the exposure contrast. Stratified tables are in the tracked
result.

### Tracked artifacts

- `benchmarks/s2-heuristic-win-attribution-v1.result.json` (version 2,
  Repair 1; git-blob SHA256 of the ORIGINAL execution commit 12ec3c5:
  `0a573d4697294d5e47cbcd04a5696d5486ef5d10e0db72cbaedf55d35035089a`;
  the repaired version-2 blob hash is recorded after the repair
  commit).
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
`take_tokens->buy_market`.

Repair 1 (per the final review of 96a09c6, narrow scope): Buy term
mapping fixed to the frozen contract (category_base = bare SCORE_BUY;
prestige = prestige x BUY_PRESTIGE) with a dedicated exact-mapping
regression; term-gap pass re-run (A1 census rows NOT regenerated — H*
and search actions do not depend on term decomposition); exposure
tables re-aggregated with opponent x heuristic-seat stratification;
nominee annotations recomputed on the exact 853 occurrences; A3
re-synthesized under the same frozen grammar/gates/ranking (no gate
changes). Verdict unchanged: ACTIONABLE_HYPOTHESIS_FOUND, nominee
unchanged. Workspace 775/0.

Next gate: **S2 closure re-review.** The prior review DEFERRED S2b
pending this repair (not rejected): the reviewer's stated future
preference — for the record, NOT an authorization — is a
parameter-free direct behavior candidate on n1: "if n1 selected
TakeTokens AND heuristic H* is unique AND the unique H action is
BuyMarket, then choose that BuyMarket action; else keep n1's action
exactly" — chosen because n1-vs-M07 is UNRESOLVED while n1 is much
cheaper, and explicitly NOT a StaticEvaluator weight sweep. S2b design
and implementation remain unauthorized until the closure re-review.

Still NOT authorized (unchanged): candidate implementation (S2b), new
Arena, new self-play, search engineering, evaluator behavior change,
heuristic behavior change, neural work, promotion/default-agent
change.
