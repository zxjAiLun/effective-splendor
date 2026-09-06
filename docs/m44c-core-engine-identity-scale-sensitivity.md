# M44C Core Engine Identity & Scale Sensitivity

```text
Milestone:      M44C
Title:          Core Engine Identity & Scale Sensitivity
Type:           evaluator scalar scale sensitivity & algebraic identity proof
Status:         DESIGN_V2 / FROZEN_BY_REVIEW (authorized for implementation)
Tracked Result: benchmarks/m44c-core-engine-identity-scale-sensitivity-v1.result.json (planned)
Baseline:       f04aedf (M44C design v1 commit)
Design:         DESIGN_V2 / FROZEN
Champion:       M07 (determinization-s4-d1-n2000-v1) — unchanged
Promotion:      NONE
Model Training: NONE
Weight Tuning:  NONE (pre-registered scale probe only; no search or production weight changes)

Mandatory Design V2 Scope:
  1. Algebraic identity closure: In standard Splendor base rules, total permanent bonuses
     B(p) and purchased-card count P(p) are identically equal to the same scalar C(p)
     on all reachable states (code/rule algebraic proof + deterministic state regression).
  2. Equalized LOO isomorphism: Prove algebraically and bit-exact that symmetric
     weights yield bit-identical utilities and actions (P0-B, no Arena).
  3. FULL scale identity: Prove bit-exact equivalence between ENGINE_SCALE_100 and
     existing AttributionProfile::FULL across frozen positions and reachable states (P0-C).
  4. Scalar weight Arena calibration: Evaluate playing-strength sensitivity to W_C
     at 25%, 50%, and 88.89% of full baseline W_C = 2,250,000 in the strict n1 shell
     (max_nodes = 1, 384 matches, Bonferroni-corrected 98.333% CI).
  5. Common-state scale audit: Evaluate action disagreement and margin shifts across
     an exact 200-context quota matrix with deterministic deduplicated sampling.
  6. Vector heterogeneity descriptive audit: Structural code fact + observational
     diversity metrics across P1 Arena-state corpus (no evaluator changes, no Arena).

Non-goals (explicitly excluded):
  - Naive bonus-vs-purchased semantic LOO (PERMANENTLY REJECTED AS NON-IDENTIFIABLE)
  - Equalized-weight Arena (NOT AUTHORIZED; proven algebraically / bit-exact instead)
  - Vector-aware evaluator modifications or Arena in M44C (DEFERRED to M45A if justified)
  - Re-running W_C = 0 (M44B result 2,187.5 bps serves as external historical anchor)
  - Modifying M07 search parameters, sample counts, or node budgets (max_nodes = 1 strict)
  - Sequential seed extensions, extra scale points, or production code refactoring
```

## Problem and Evidence

M44B established that inside the resolved-sensitive `F2_PERMANENT_ENGINE` family, playing-strength sensitivity is concentrated in `CORE_ENGINE`:
`DROP_CORE_ENGINE vs FULL` collapsed to **2,187.5 bps** (97.5% CI: `[1484.375, 2968.75]`, 28W / 0T / 100L, `RESOLVED_SENSITIVE`), whereas `DROP_NOBLE_PROGRESS vs FULL` scored **5,156.25 bps** (97.5% CI: `[4765.625, 5625.0]`, `UNRESOLVED`).

In `StaticEvaluatorV1`, `CORE_ENGINE` was historically defined with two separate terms:
$$\text{CORE\_ENGINE} = \text{total\_permanent\_bonuses} \times 2{,}000{,}000 + \text{purchased\_card\_count} \times 250{,}000$$

A naive decomposition attempt might seek to perform a Leave-One-Out (LOO) test between `total_permanent_bonuses` and `purchased_card_count`.
However, rigorous code and rule inspection reveals a fundamental algebraic barrier:
**Under the base rules of Splendor, these two features are not merely correlated; they are the exact same underlying state scalar $C(p)$ encoded twice.**

### The Algebraic Identity Invariant

1. **Catalog Specification**: The Splendor development card catalog contains exactly **90 cards** (Tier 1: 40, Tier 2: 30, Tier 3: 20). Every card definition has a mandatory, single `GemColor` bonus. There are zero cards with 0 bonuses, and zero cards with $\ge 2$ bonuses.
2. **Initial State**: At setup, every player $p$ begins with:
   $$\text{bonuses}(p) = [0, 0, 0, 0, 0] \implies B(p) = \sum_{c} \text{bonuses}_c(p) = 0$$
   $$\text{purchased}(p) = [] \implies P(p) = |\text{purchased}(p)| = 0$$
3. **Transition Semantics**: Card acquisitions occur exclusively through `BuyMarket` or `BuyReserved`. Both actions route to `apply_buy()`, which executes:
   ```text
   bonuses[def.bonus.index()] += 1
   purchased.insert(card_id)
   ```
   No game action can increase one without the other, and no game rule allows cards or bonuses to be discarded, traded, or lost.
4. **Reachable-State Invariant**:
   $$\forall s \in \mathcal{S}_{\text{reachable}}, \forall p \in \text{Players}(s): \quad B(p) \equiv P(p) \equiv C(p)$$
5. **Correlation Form**: For any sample of reachable legal states with non-zero variance $\text{Var}(C) > 0$, the Pearson correlation is identically:
   $$\rho(B, P) \equiv 1.0$$
   (If $\text{Var}(C) = 0$, Pearson correlation is undefined.)

### The Evaluator Collapse

Because $B(p) \equiv P(p) \equiv C(p)$ on all legal states:
$$\begin{aligned}
\text{CORE\_ENGINE}(p) &= B(p) \times 2{,}000{,}000 + P(p) \times 250{,}000 \\
&= C(p) \times (2{,}000{,}000 + 250{,}000) \\
&= C(p) \times 2{,}250{,}000 \\
&= C(p) \times W_C^{\text{full}}
\end{aligned}$$

### Why Naive Semantic LOO Fails Closed

Attempting to evaluate `DROP_PURCHASED` vs `DROP_BONUSES` does not isolate two distinct information streams:
- `DROP_PURCHASED`: Sets $W_C = 2{,}000{,}000$ (**88.89%** of full $W_C$).
- `DROP_BONUSES`: Sets $W_C = 250{,}000$ (**11.11%** of full $W_C$).

If `DROP_PURCHASED` maintains high playing strength while `DROP_BONUSES` drops, this does **not** prove that "bonuses contain more information than card count." It merely reflects that 88.89% of the scalar signal was retained in one case and only 11.11% in the other.
Therefore, **naive bonus-vs-purchased semantic LOO is permanently rejected as non-identifiable under current base rules and state representation.**

---

## Research Questions for M44C

Given that `CORE_ENGINE` contains exactly one scalar degree of freedom $C(p) \times W_C$:
> **How sensitive is the $n1$ search agent to the magnitude of the economic engine weight $W_C$, and where does the playing-strength degradation begin as $W_C$ is scaled down from $2{,}250{,}000$ toward $0$?**

Additionally:
> **Does the scalar $C(p)$ compress away substantial color-vector heterogeneity $\mathbf{b}(p) \in \mathbb{N}^5$, and to what extent does that hidden vector information already manifest through F4 (affordability) and E2 (nobles)?**

---

## Milestone Protocols

M44C comprises four focused, decoupled protocols:

```text
┌────────────────────────────────────────────────────────────────────────┐
│ M44C Core Engine Identity & Scale Sensitivity                          │
├────────────────────────────────┬───────────────────────────────────────┤
│ P0: Algebraic & Isomorphism    │ Code-level proof of B ≡ P ≡ C,        │
│     Closure (No Arena)         │ symmetric LOO isomorphism (P0-B),     │
│                                │ and ENGINE_SCALE_100 == FULL (P0-C)   │
├────────────────────────────────┼───────────────────────────────────────┤
│ P1: Scalar Weight Arena        │ 3 pairings (25%, 50%, 88.89% vs FULL)  │
│     Calibration (384 matches)  │ Strict n1 shell (max_nodes = 1)       │
│                                │ Bonferroni-corrected 98.333% CI       │
├────────────────────────────────┼───────────────────────────────────────┤
│ P2: Common-State Scale Audit   │ Exact 200-context quota matrix        │
│     (200 contexts)             │ Action agreement & margin breakdown   │
├────────────────────────────────┼───────────────────────────────────────┤
│ P3: Vector Heterogeneity Audit │ Structural code fact + observational  │
│     (Descriptive diagnostic)   │ diversity metrics on Arena corpus     │
└────────────────────────────────┴───────────────────────────────────────┘
```

---

## P0 — Algebraic Identity, Equalized LOO, & FULL Scale Identity (Bit-Exact)

**No Arena execution permitted for P0.** This protocol establishes algebraic truths in code and unit tests.

### P0-A: Algebraic Identity Regression
1. **Catalog Integrity**: Assert all 90 cards in `splendor-catalog` have valid tier and exactly one bonus gem color.
2. **Transition Invariance**: Assert `B(p) == P(p)` initially and after every legal action across $\ge 256$ game states generated from deterministic 2-player, 3-player, and 4-player simulations.
3. **Core Term Equivalence**: Assert $E_1(s, p) \equiv C(p) \times 2{,}250{,}000$ identically for all tested states.

### P0-B: Equalized LOO Isomorphism
Define symmetric test weights:
$$w_b^{\text{sym}} = 1{,}125{,}000, \quad w_p^{\text{sym}} = 1{,}125{,}000$$
Define two symmetric ablation profiles:
- `EQUAL_DROP_BONUS`: $0 \cdot B(p) + 1{,}125{,}000 \cdot P(p) = 1{,}125{,}000 \cdot C(p)$
- `EQUAL_DROP_PURCHASED`: $1{,}125{,}000 \cdot B(p) + 0 \cdot P(p) = 1{,}125{,}000 \cdot C(p)$

**Isomorphism Gate**:
Across:
- The 12 frozen M07 benchmark positions;
- $\ge 128$ deterministic reachable states;
- All 4 determinizations per state;

Assert:
1. Exact integer equality of root utilities:
   $$\text{utilities}_{\text{drop\_b}}(s) == \text{utilities}_{\text{drop\_p}}(s)$$
2. Exact integer equality of per-action search scores:
   $$\text{action\_scores}_{\text{drop\_b}}(s, a) == \text{action\_scores}_{\text{drop\_p}}(s, a) \quad \forall a \in \mathcal{A}_{\text{legal}}$$
3. Exact identity of the selected canonical action:
   $$\text{argmax}(a)_{\text{drop\_b}} == \text{argmax}(a)_{\text{drop\_p}}$$

Passing P0-B permanently closes the question of feature superiority under symmetric scaling.

### P0-C: FULL Scale Identity
Define `ENGINE_SCALE_100` with $W_C = 2{,}250{,}000$.
Across:
- The 12 frozen M07 benchmark positions;
- $\ge 128$ deterministic reachable states;
- All 4 determinizations per state;

Assert bit-exact equality between `ENGINE_SCALE_100` and the existing verified `AttributionProfile::FULL`:
1. Player utility vector: $\text{utilities}_{\text{scale\_100}}(s) == \text{utilities}_{\text{full}}(s)$.
2. All legal canonical action aggregate scores: $\text{action\_scores}_{\text{scale\_100}}(s, a) == \text{action\_scores}_{\text{full}}(s, a)$.
3. Selected canonical action: $\text{argmax}(a)_{\text{scale\_100}} == \text{argmax}(a)_{\text{full}}$.

**G0 Gate Requirement**: Only when P0-A, P0-B, and P0-C pass completely is the P1 Arena unlocked. In the formal Arena, `FULL` continues using the verified production `FULL` profile to eliminate extraneous control variations.

---

## P1 — Scalar Weight Arena Calibration

### Evaluator Profiles

All profiles retain the full static evaluator terms for F1 (prestige), E2 (nobles), F3 (liquidity), and F4 (convertibility). Only the scalar engine weight $W_C$ applied to $C(p)$ varies:

| Profile | $W_C$ | Ratio of Baseline | Semantic Correspondence |
| :--- | :---: | :---: | :--- |
| `ENGINE_SCALE_25` | $562{,}500$ | $25.00\%$ | Aggressive engine attenuation |
| `ENGINE_SCALE_50` | $1{,}125{,}000$ | $50.00\%$ | Half engine weight |
| `ENGINE_SCALE_88` | $2{,}000{,}000$ | $88.89\%$ | Naive `DROP_PURCHASED` weight equivalent |
| `FULL` | $2{,}250{,}000$ | $100.00\%$ | Standard frozen baseline |

*Historical Anchor (External, not re-run or pooled)*:
- `ENGINE_SCALE_0` ($W_C = 0$): Measured in M44B as `DROP_CORE_ENGINE`, yielding **2,187.5 bps** (97.5% CI: `[1484.4, 2968.8]`, `RESOLVED_SENSITIVE`).

### Arena Pairing Schedule

| Pairing ID | Candidate Profile | Baseline Profile | Matches | Seat 0 / Seat 1 |
| :--- | :--- | :--- | :---: | :---: |
| `PAIRING_1` | `ENGINE_SCALE_25` | `FULL` | 128 | 64 / 64 |
| `PAIRING_2` | `ENGINE_SCALE_50` | `FULL` | 128 | 64 / 64 |
| `PAIRING_3` | `ENGINE_SCALE_88` | `FULL` | 128 | 64 / 64 |
| **Total** | | | **384** | **192 / 192** |

### Execution Constants (Strict n1 Shell)

To ensure comparability with M44A and M44B, the execution shell is frozen strictly to:
- `sample_seed = 20_260_703`
- `sample_count = 4`
- `max_depth_turns = 1`
- `max_nodes = 1` (**strict n1 static-successor shell, NOT 2000**)
- **Seed Segment**: Fresh segment `5_700_000 .. 5_700_063` (64 seeds, rotated over 2 seats = 128 matches per pairing).
- **Execution Engine**: `crates/splendor-cli` arena runner, strict fail-closed contract (0 aborts, 0 candidate faults, 0 unhandled panics).

### Statistical Protocol & Decision Gates

- **Family-wise Error Rate**: Controlled at $\alpha = 0.05$ across the 3 primary scale hypotheses using Bonferroni correction:
  $$\alpha_{\text{per-test}} = \frac{0.05}{3} \approx 0.016667 \implies \mathbf{98.333\%} \text{ two-sided CI}$$
  Exact percentile bounds: lower $= 0.833333\%$, upper $= 99.166667\%$.
- **Bootstrap Parameters**: 10,000 resamples, seed `44_290_001`, paired block unit (evaluating paired matches under matched seed and swapped seat rotation).
- **Classification Vocabulary** (Calibration-specific):
  - **`RESOLVED_WEAKER`**: Upper bound of $98.333\%$ CI $< 5{,}000$ bps.
  - **`RESOLVED_STRONGER`**: Lower bound of $98.333\%$ CI $> 5{,}000$ bps.
  - **`UNRESOLVED`**: $98.333\%$ CI crosses $5{,}000$ bps.

### Disciplined Interpretation Matrix

1. **Bracketing Pattern** (if 25% WEAKER, 50% WEAKER, 88.9% UNRESOLVED):
   - *Licensed wording*: At the sampled calibration points, 50% is resolved weaker while 88.9% is not resolved different from FULL. This brackets a change in resolved evidence between the two sampled scales, but does not identify a mathematical threshold, cliff shape, monotonic frontier, or equivalence region.
2. **Robustness Compatibility** (if 25% WEAKER, 50% UNRESOLVED, 88.9% UNRESOLVED):
   - *Licensed wording*: No strength difference was resolved at the sampled 50% and 88.9% points. This is compatible with a broad robustness region, but does not establish behavior for unsampled intermediate or larger values.
3. **Local Scale Sensitivity** (if 88.9% WEAKER):
   - *Licensed wording*: A reduction from 2.25M to 2.0M produces a resolved strength loss under the frozen evaluator. This establishes local scale sensitivity over that tested interval, but does not establish linearity, coefficient optimality, or uniqueness of 2.25M.

---

## P2 — Common-State Scale Audit (Descriptive)

### Exact 200-Context Quota Matrix

Sampling is frozen to an exact quota matrix across pairings and game stages:

| Pairing | Early (Plies 1–20) | Mid (Plies 21–45) | Late (Plies 46+) | Total |
| :--- | :---: | :---: | :---: | :---: |
| `PAIRING_1` (`Scale25`) | 23 | 22 | 22 | 67 |
| `PAIRING_2` (`Scale50`) | 22 | 23 | 22 | 67 |
| `PAIRING_3` (`Scale88`) | 22 | 22 | 22 | 66 |
| **Total** | **67** | **67** | **66** | **200** |

### Deterministic Selection Contract
- **Eligibility Criteria**:
  1. `state.phase == Phase::Main`.
  2. Number of legal canonical actions $\ge 2$.
- **Selection Order**:
  `pairing -> stage -> seed ascending -> rotation 0 then 1 -> ply ascending -> actor`.
- **Identity & Deduplication**:
  Deduplication is performed globally across all three pairings using the authoritative identity triple:
  `observation_hash`, `visible_history_hash`, `information_set_hash`.
- **Fail-Closed Contract**:
  If any quota cell cannot be filled after traversing all replays of the pairing, the audit **fails closed**. No borrowing across cells or pairings is permitted.
- **Source Reproduction**:
  The recorded action of the source profile must be reproduced exactly: **200 / 200 exact reproduction required**.

### Audit Metrics (Descriptive Behavior Diagnostic)
For each audited context $s$ and each scale $w \in \{25\%, 50\%, 88.89\%\}$:
1. **Action Disagreement Rate vs FULL**:
   $$\text{Disagreement}(w) = \frac{1}{200} \sum_{i=1}^{200} \mathbb{I}\left( \text{action}_w(s_i) \neq \text{action}_{\text{full}}(s_i) \right)$$
2. **Top-1 vs Runner-up Margin Contribution**:
   Measure how the score margin between the top two actions is affected by $W_C$.
3. **Engine-Pivotal Behavior Label**:
   Fraction of contexts where the scale profile flips the winning action across the boundary between:
   - **Engine actions**: `BuyMarket`, `BuyReserved`.
   - **Non-engine actions**: `TakeTokens`, `ReserveMarket`, `ReserveDeck`, `Pass`.
   *Disciplinary note*: This is a descriptive behavioral tag, not evidence that a particular weight makes the agent "understand economics better".

---

## P3 — Vector Heterogeneity Audit (Descriptive Diagnostic)

### Part A: Code-Level Structural Fact
The static evaluator definition in `crates/splendor-search/src/evaluation.rs` demonstrates directly:
1. **F4 Affordability**: `player.can_afford(cost)` explicitly tests `player.bonuses[color]`.
2. **E2 Noble Progress**: Noble requirement deficits test `def.requirements[color].saturating_sub(player.bonuses[color])`.

Therefore, the 5-dimensional bonus color vector $\mathbf{b} \in \mathbb{N}^5$ **structurally enters the existing evaluator** through F4 and E2, even though `CORE_ENGINE` compresses it into the scalar sum $C$.

### Part B: Arena-State Corpus Observational Heterogeneity
- **Corpus Definition**: All unique `Phase::Main` root-actor contexts from the 384 accepted P1 replays, deduplicated by identity triple.
- **Reporting Scope**: No artificial bounds on $C$; report all observed strata $C \in \{0, 1, 2, \dots\}$.
- **Stratum Metrics**:
  For each observed $C$:
  1. Context count $N_C$.
  2. Distinct bonus-vector count $K_C$.
  3. Vector empirical frequencies $p(\mathbf{v} \mid C)$.
  4. Shannon diversity entropy:
     $$H_C = - \sum_{\mathbf{v}} p(\mathbf{v} \mid C) \log_2 p(\mathbf{v} \mid C) \quad (\text{bits})$$
  5. F4 value distribution (mean, min, max, std).
  6. E2 value distribution (mean, min, max, std).

*Strict Disciplinary Boundary*:
> At fixed scalar $C$, the observed Arena-state corpus contains multiple bonus-vector configurations, demonstrating information loss under scalar compression. F4 and E2 also vary within $C$ strata, but this observational variance is **not** attributed uniquely to bonus-vector differences because other state variables (board market, tokens, reserved cards, noble targets) co-vary simultaneously.

---

## Acceptance Gates

- [ ] **G0 (P0 Bit-Exact Verification)**: P0-A (algebraic identity regression), P0-B (equalized LOO isomorphism), and P0-C (FULL scale identity) all pass with 0 failures.
- [ ] **G1 (Arena Execution Completeness)**: 384/384 matches completed in the strict $n1$ shell (`max_nodes = 1`, seeds `5_700_000 .. 5_700_063`). 0 aborted matches, 0 candidate faults.
- [ ] **G2 (Statistical Classification)**: Each of the 3 scale arms receives a definitive Bonferroni-corrected classification (`RESOLVED_WEAKER`, `RESOLVED_STRONGER`, or `UNRESOLVED`) using $98.333\%$ bootstrap CI.
- [ ] **G3 (Deterministic P2 Quota)**: Exact 200-context matrix filled without borrowing; 200/200 source reproduction verified.
- [ ] **G4 (P3 Diagnostic Execution)**: Observational vector diversity and Shannon entropy computed across deduplicated Arena corpus with structural boundary adhered to.
- [ ] **G5 (Provenance & Artifact)**: Tracked result artifact binds exact git commit, SHA256 of binaries, catalogs, seeds, and replay digests.

---

## Known Limitations

1. **Discretized Scale Grid**: Testing 25%, 50%, and 88.89% leaves intervals between points; it maps the coarse shape of the sensitivity curve, not a continuous derivative.
2. **Historical Anchor Distinction**: $W_C = 0$ is drawn from M44B; it cannot be pooled directly into the M44C bootstrap CI due to distinct seed segments, but serves as a qualitative asymptotic anchor.
3. **Observational Vector Variance**: In-stratum F4/E2 variance reflects the whole game state, not pure vector counterfactuals.
