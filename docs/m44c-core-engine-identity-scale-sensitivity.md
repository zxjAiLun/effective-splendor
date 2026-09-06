# M44C Core Engine Identity & Scale Sensitivity

```text
Milestone:      M44C
Title:          Core Engine Identity & Scale Sensitivity
Type:           evaluator scalar scale sensitivity & algebraic identity proof
Status:         PROPOSED / DRAFT_PENDING_REVIEW
Tracked Result: benchmarks/m44c-core-engine-identity-scale-sensitivity-v1.result.json (planned)
Baseline:       b3bb4c9 (M44B closure record)
Design:         DESIGN_V1 / DRAFT
Champion:       M07 (determinization-s4-d1-n2000-v1) — unchanged
Promotion:      NONE
Model Training: NONE
Weight Tuning:  NONE (pre-registered scale probe only; no search or production weight changes)

Scope:
  1. Algebraic identity proof: In standard Splendor base rules, total permanent bonuses
     B(p) and purchased-card count P(p) are identically equal to the same scalar C(p)
     on all reachable states.
  2. Equalized LOO isomorphism: Prove algebraically and bit-exact that symmetric
     weights yield bit-identical utilities and actions (no Arena needed).
  3. Scalar weight Arena calibration: Evaluate playing-strength sensitivity to W_C
     at 25%, 50%, and 88.89% of full baseline W_C = 2,250,000 (384 matches).
  4. Common-state scale audit: Evaluate action disagreement and margin shifts across
     200 balanced contexts.
  5. Vector heterogeneity descriptive audit: Quantify color-vector diversity compressed
     by scalar C and its indirect influence through F4/E2 (no evaluator changes, no Arena).

Non-goals (explicitly excluded):
  - Naive bonus-vs-purchased semantic LOO (PERMANENTLY REJECTED AS NON-IDENTIFIABLE)
  - Equalized-weight Arena (NOT AUTHORIZED; proven algebraically / bit-exact instead)
  - Vector-aware evaluator modifications or Arena in M44C (DEFERRED to M45A if justified)
  - Re-running W_C = 0 (M44B result 2,187.5 bps serves as external historical anchor)
  - Modifying M07 search parameters, sample counts, or node budgets
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

1. **Catalog Specification**: The Splendor development card catalog contains exactly 90 cards (Tier 1: 40, Tier 2: 30, Tier 3: 20). Every card definition has a mandatory, single `GemColor` bonus. There are zero cards with 0 bonuses, and zero cards with $\ge 2$ bonuses.
2. **Initial State**: At setup, every player $p$ begins with:
   $$\text{bonuses}(p) = [0, 0, 0, 0, 0] \implies B(p) = \sum_{c} \text{bonuses}_c(p) = 0$$
   $$\text{purchased}(p) = [] \implies P(p) = |\text{purchased}(p)| = 0$$
3. **Transition Semantics**: Card acquisitions occur exclusively through `BuyMarket` or `BuyReserved`. Both actions route to `apply_buy()`, which executes:
   ```text
   bonuses[def.bonus.index()] += 1
   purchased.insert(card_id)
   ```
   No game action can increase one without the other, and no game rule allows cards or bonuses to be discarded, traded, or lost.
4. **Reachable-State Theorem**:
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
Therefore, **naive bonus-vs-purchased semantic LOO is permanently rejected as non-identifiable.**

---

## The True Research Question for M44C

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
│ P0: Algebraic & Isomorphism    │ Proof of B ≡ P ≡ C and symmetric-     │
│     Closure (No Arena)         │ weight bit-exact equivalence          │
├────────────────────────────────┼───────────────────────────────────────┤
│ P1: Scalar Weight Arena        │ 3 pairings (25%, 50%, 88.89% vs FULL)  │
│     Calibration (384 matches)  │ Bonferroni-corrected 98.333% CI       │
├────────────────────────────────┼───────────────────────────────────────┤
│ P2: Common-State Scale Audit   │ Action agreement & margin breakdown   │
│     (200 contexts)             │ on balanced context sample            │
├────────────────────────────────┼───────────────────────────────────────┤
│ P3: Vector Heterogeneity Audit │ Descriptive audit of vector diversity │
│     (Descriptive diagnostic)   │ & F4/E2 variance at constant C        │
└────────────────────────────────┴───────────────────────────────────────┘
```

---

## P0 — Algebraic Identity & Equalized LOO Isomorphism (Bit-Exact)

**No Arena execution permitted for P0.** This protocol establishes algebraic truths in code and unit tests.

### P0-A: Algebraic Identity Invariant
1. **Catalog Integrity**: Assert all 90 cards in `splendor-catalog` have valid tier and exactly one bonus gem color.
2. **Transition Invariance**: Assert `B(p) == P(p)` initially and after every legal action across $\ge 256$ game states generated from 2-player, 3-player, and 4-player simulations.
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

Passing P0-B permanently closes the question: "Which feature carries more information, bonuses or card count?" by proving they produce identical decision landscapes under symmetric scaling.

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

*Historical Anchor (External, not re-run)*:
- `ENGINE_SCALE_0` ($W_C = 0$): Measured in M44B as `DROP_CORE_ENGINE`, yielding **2,187.5 bps** (97.5% CI: `[1484.4, 2968.8]`, `RESOLVED_SENSITIVE`).

### Arena Pairing Schedule

| Pairing ID | Candidate Profile | Baseline Profile | Matches | Seat 0 / Seat 1 |
| :--- | :--- | :--- | :---: | :---: |
| `PAIRING_1` | `ENGINE_SCALE_25` | `FULL` | 128 | 64 / 64 |
| `PAIRING_2` | `ENGINE_SCALE_50` | `FULL` | 128 | 64 / 64 |
| `PAIRING_3` | `ENGINE_SCALE_88` | `FULL` | 128 | 64 / 64 |
| **Total** | | | **384** | **192 / 192** |

### Execution Constants

- **Seed Segment**: Fresh segment `5_700_000 .. 5_700_063` (64 seeds, rotated over 2 seats = 128 matches per pairing).
- **Search Configuration**: Identical $n1$ shell across all arms:
  - `sample_seed = 20_260_703`
  - `sample_count = 4`
  - `max_depth_turns = 1`
  - `max_nodes = 2000`
- **Execution Engine**: `crates/splendor-cli` arena runner, strict fail-closed contract (0 aborts, 0 candidate faults, 0 unhandled panics).

### Statistical Protocol & Decision Gates

- **Family-wise Error Rate**: Controlled at $\alpha = 0.05$ across the 3 primary scale hypotheses using Bonferroni correction:
  $$\alpha_{\text{per-test}} = \frac{0.05}{3} \approx 0.01667 \implies \mathbf{98.333\%} \text{ two-sided CI}$$
- **Bootstrap Parameters**: 10,000 resamples, seed `44_290_001`, paired block unit (evaluating paired matches under matched seed and swapped seat rotation).
- **Classification Vocabulary** (Calibration-specific):
  - **`RESOLVED_WEAKER`**: Upper bound of $98.333\%$ CI $< 5{,}000$ bps.
  - **`RESOLVED_STRONGER`**: Lower bound of $98.333\%$ CI $> 5{,}000$ bps.
  - **`UNRESOLVED`**: $98.333\%$ CI crosses $5{,}000$ bps.

### Interpretation Matrix

1. **Step-Threshold Pattern** (e.g. 25% WEAKER, 50% WEAKER, 88.9% UNRESOLVED):
   - Confirms that the engine weight requires a minimum absolute threshold (between 50% and 88.9%) to guide search effectively.
   - Explains why naive `DROP_PURCHASED` appeared harmless in preliminary thinking: it only reduced $W_C$ to 88.89%, well above the collapse cliff.
2. **Broad Plateau Pattern** (e.g. 25% WEAKER, 50% UNRESOLVED, 88.9% UNRESOLVED):
   - Proves that $W_C$ has extensive coefficient robustness; any value $\ge 1.125\text{M}$ suffices to prioritize engine tempo over token liquidity.
3. **Acute Linear Sensitivity** (e.g. 88.9% WEAKER):
   - Proves that even an 11% change in $W_C$ degrades playing strength, establishing high precision in the original handcrafted coefficients.

---

## P2 — Common-State Scale Audit (Descriptive)

### Sample Construction
- Select 200 balanced decision contexts from P1 replay logs:
  - $\sim 67$ contexts from `PAIRING_1` (`ENGINE_SCALE_25 vs FULL`)
  - $\sim 67$ contexts from `PAIRING_2` (`ENGINE_SCALE_50 vs FULL`)
  - $\sim 66$ contexts from `PAIRING_3` (`ENGINE_SCALE_88 vs FULL`)
- Even ply distribution across early (plies 1–20), mid (plies 21–45), and late game (plies 46+).

### Audit Metrics (Descriptive Only)
For each audited state $s$ and each scale $w \in \{25\%, 50\%, 88.89\%\}$:
1. **Top-Action Disagreement Rate**:
   $$\text{Disagreement}(w) = \frac{1}{N} \sum_{i=1}^N \mathbb{I}\left( \text{action}_w(s_i) \neq \text{action}_{\text{full}}(s_i) \right)$$
2. **Top-1 vs Runner-up Margin Shift**:
   Measure how the score margin between the optimal action and second-best action changes as $W_C$ scales down.
3. **Engine-Pivotal Fraction**:
   Fraction of contexts where scaling $W_C$ specifically flips the choice between an engine-building action (`BuyMarket` / `BuyReserved`) and a non-engine action (`TakeTokens` / `Reserve`).

---

## P3 — Vector Heterogeneity Audit (Descriptive Diagnostic)

This protocol performs **zero evaluator modifications** and **zero Arena runs**. It is a descriptive diagnostic on reachable game states to quantify the information compressed by scalar $C(p)$, preparing the empirical foundation for a future milestone (M45A).

### Diagnostic Questions
1. **Vector Diversity given $C$**:
   For each observed value of $C \in \{1, 2, \dots, 15\}$ across the reachable corpus:
   - What is the count of distinct color vectors $\mathbf{b} = (b_W, b_U, b_G, b_R, b_K)$ such that $\sum b_i = C$?
   - What is the empirical entropy / Shannon diversity of bonus distributions observed in high-level play?
2. **Information Leakage via Existing Families**:
   For pairs of states with the exact same scalar $C(p)$ but different vectors $\mathbf{b}_1 \neq \mathbf{b}_2$:
   - How much variance exists in F4 (`affordable_card_count` and `max_affordable_prestige`)?
   - How much variance exists in E2 (`noble_progress`)?
3. **Implication**:
   If identical $C$ states exhibit high variance in F4 and E2, it confirms that color-structure information is already active in the agent via F4/E2, and any future vector-engine probe must decouple from F4/E2 to avoid multi-collinearity.

---

## Implementation Plan

1. **Rust Engine Extension (`splendor-search`)**:
   - Update `AttributionProfile` to support:
     - `EngineScale25` ($W_C = 562{,}500$)
     - `EngineScale50` ($W_C = 1{,}125{,}000$)
     - `EngineScale88` ($W_C = 2{,}000{,}000$)
     - `EqualDropBonus` ($w_b = 0, w_p = 1{,}125{,}000$)
     - `EqualDropPurchased` ($w_b = 1{,}125{,}000, w_p = 0$)
   - Keep integer arithmetic exact; no floating-point conversions.
2. **Automated P0 Tests (`crates/splendor-cli/tests/m44c_p0_semantic.rs`)**:
   - P0-A: Catalog 90-card integrity & reachable-state algebraic identity check.
   - P0-B: Equalized LOO bit-exact isomorphism check across M07 positions.
3. **Orchestrator & Audit Scripts (`scripts/`)**:
   - `scripts/m44c_orchestrator.py`: CLI driver for the 384 Arena matches.
   - `scripts/m44c_common_state_audit.py`: 200-context scale audit driver.
   - `scripts/m44c_vector_heterogeneity_audit.py`: Reachable state vector diversity diagnostic.
   - `scripts/m44c_final_audit.py`: Result aggregator generating `benchmarks/m44c-core-engine-identity-scale-sensitivity-v1.result.json`.

---

## Acceptance Gates

- [ ] **G0 (P0 Semantic Verification)**: All P0-A and P0-B unit tests pass with 0 failures. Equalized LOO isomorphism confirmed bit-exact.
- [ ] **G1 (Arena Execution Completeness)**: 384/384 matches completed across fresh seeds `5_700_000 .. 5_700_063`. 0 aborted matches, 0 candidate faults.
- [ ] **G2 (Statistical Classification)**: Each of the 3 scale arms receives a definitive Bonferroni-corrected classification (`RESOLVED_WEAKER`, `RESOLVED_STRONGER`, or `UNRESOLVED`).
- [ ] **G3 (Audit Convergence)**: Common-state audit and vector heterogeneity audit successfully extract metrics on 200 balanced contexts with 0 replay format errors.
- [ ] **G4 (Provenance Integrity)**: Tracked result artifact binds exact git commit, SHA256 of binaries, catalogs, seeds, and replay digests.

---

## Known Limitations

1. **Discretized Scale Grid**: Testing 25%, 50%, and 88.89% leaves intervals between points; it maps the coarse shape of the sensitivity curve, not a continuous derivative.
2. **Historical Anchor Distinction**: $W_C = 0$ is drawn from M44B; it cannot be pooled directly into the M44C bootstrap CI due to distinct seed segments, but serves as a qualitative asymptotic anchor.
3. **Vector Structure Out of Scope for Arena**: M44C strictly diagnoses scalar magnitude; it does not test whether a color-aware engine term improves search strength.
