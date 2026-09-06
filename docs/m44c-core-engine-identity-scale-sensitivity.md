# M44C Core Engine Identity & Scale Sensitivity

```text
Milestone:      M44C
Title:          Core Engine Identity & Scale Sensitivity
Type:           evaluator scalar scale sensitivity & algebraic identity proof
Status:         COMPLETED_DIAGNOSTIC / CLOSURE_PENDING_REPAIR_1_DONE
                (Closure Repair 1 executed; awaiting final closure signature)
Tracked Result: benchmarks/m44c-core-engine-identity-scale-sensitivity-v1.result.json
Baseline:       fd0211d (M44C design v2 commit)
Implementation: 58863f8 (P0/P1/P2/P3 implementation + 384-match Arena)
Repair Basis:   M44C terminal review on 58863f8
                (P1 ACCEPTED; P0 evidence / P2 / P3 repairs ordered; Arena rerun FORBIDDEN)
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

## Acceptance Gates Status

- [x] **G0 (P0 Bit-Exact Verification)**: P0-A (algebraic identity regression), P0-B (equalized LOO isomorphism), and P0-C (FULL scale identity) all pass (4/4 tests passed in `crates/splendor-cli/tests/m44c_p0_semantic.rs`; Closure Repair 1 re-bound P0-B/P0-C to the authoritative sealed M44A 12-case definitions).
- [x] **G1 (Arena Execution Completeness)**: 384/384 matches completed in the strict $n1$ shell (`max_nodes = 1`, seeds `5_700_000 .. 5_700_063`). 0 aborted matches, 0 candidate faults.
- [x] **G2 (Statistical Classification)**: Each of the 3 scale arms receives a definitive Bonferroni-corrected classification (`UNRESOLVED` for all three sampled points) using $98.333\%$ bootstrap CI.
- [x] **G3 (Deterministic P2 Quota)**: Exact 200-context matrix filled without borrowing; 200/200 source reproduction verified (100.0%). Closure Repair 1 rebuilt the audit on the authoritative identity triple with 1-based decision-ply staging and top-1/runner-up margins.
- [x] **G4 (P3 Diagnostic Execution)**: Observational vector diversity and Shannon entropy computed across the authoritative-identity-deduplicated Arena corpus (7,725 unique contexts, 21 $C$ strata) with structural boundary adhered to.
- [x] **G5 (Provenance & Artifact)**: Tracked result artifact `benchmarks/m44c-core-engine-identity-scale-sensitivity-v1.result.json` (Closure Repair 1 version, SHA256: `ef73df5aa64f3abfdd5b7a3dcec698b600fb0a073ea46f1c4cfb3314d784ca10`).

---

## Final Validation and Evidence

### 1. P0 Semantic & Bit-Exact Verification
Executed via `cargo test -p splendor-cli --test m44c_p0_semantic`:
- **P0-A (Algebraic Identity Regression)**: Verified 90-card base catalog integrity (all cards have exactly 1 bonus). Verified $B(p) \equiv P(p) \equiv C(p)$ initially and across 300 reachable states in 2p/3p/4p games. Verified $E_1(s, p) \equiv C(p) \times 2{,}250{,}000$ identically.
- **P0-B (Equalized LOO Isomorphism)**: Evaluated symmetric weights ($w_b = w_p = 1{,}125{,}000$). Verified 100% bit-exact equality of utilities, root action aggregates, and selected actions between `EqualDropBonus` and `EqualDropPurchased` across the 12 frozen M07 positions and 140 deterministic reachable states.
- **P0-C (FULL Scale Identity)**: Verified 100% bit-exact equality between `EngineScale100` ($W_C = 2{,}250{,}000$) and existing `AttributionProfile::FULL` across the 12 frozen M07 positions and 140 deterministic reachable states.
- **P0-D (Constants & Parsing)**: Verified integer constants ($562\text{k}, 1.125\text{M}, 2.0\text{M}, 2.25\text{M}$) and string parsing.

Regression tests for M44A (`m44a_p0_semantic.rs`, 6/6) and M44B (`m44b_p0_semantic.rs`, 4/4) also passed 100%.

### 2. P1 Arena Calibration Evidence (384 Physical Matches)

64 paired seed blocks (`5_700_000 .. 5_700_063`) $\times$ 2 seat rotations = 128 matches per pairing. 0 aborts, 0 candidate faults. Strict $n1$ shell (`max_nodes = 1`, `max_depth_turns = 1`, `sample_count = 4`, `sample_seed = 20_260_703`).

| Candidate Arm | Control Arm | Matches | W / T / L | Center Score (bps) | CI Level | Bootstrap CI (bps) | Formal Verdict | Seat 0 / 1 (bps) | Mean Plies |
|---|---|---:|:---:|---:|:---:|:---:|:---:|---:|---:|
| `ENGINE_SCALE_25` ($562.5\text{k}$) | `FULL` ($2.25\text{M}$) | 128 | 67 / 0 / 61 | **5,234.38** | 98.333% | [4,218.75, 6,224.61] | **UNRESOLVED** | 4687.50 / 5781.25 | 61.4 |
| `ENGINE_SCALE_50` ($1.125\text{M}$) | `FULL` ($2.25\text{M}$) | 128 | 62 / 0 / 66 | **4,843.75** | 98.333% | [4,062.50, 5,703.12] | **UNRESOLVED** | 4843.75 / 4843.75 | 61.4 |
| `ENGINE_SCALE_88` ($2.000\text{M}$) | `FULL` ($2.25\text{M}$) | 128 | 64 / 0 / 64 | **5,000.00** | 98.333% | [5,000.00, 5,000.00] | **UNRESOLVED** | 5468.75 / 4531.25 | 61.3 |

*Historical Anchor (External, M44B)*:
- `DROP_CORE_ENGINE` ($W_C = 0$): 128 matches, 28 / 0 / 100, Center: **2,187.50 bps**, 97.5% CI: `[1484.4, 2968.8]`, `RESOLVED_SENSITIVE`.

### 3. P2 Balanced Common-State Scale Audit (200 Contexts, Closure Repair 1)

Rebuilt in Closure Repair 1 with the authoritative identity triple (`observation_hash`, `visible_history_hash`, `information_set_hash` from `build_information_set_v1`, the same pipeline as `analyze-replay-player-view` source metadata), 1-based decision-ply staging (early 1–20, mid 21–45, late 46+), and top-1/runner-up margins computed from sorted root utilities with the best-equals-selected assertion.

- **Quota Matrix Fulfillment**: Exactly filled without borrowing:
  - `Scale25`: Early 23, Mid 22, Late 22 = 67
  - `Scale50`: Early 22, Mid 23, Late 22 = 67
  - `Scale88`: Early 22, Mid 22, Late 22 = 66
  - **Total**: Early 67, Mid 67, Late 66 = 200 contexts.
- **Source Action Reproduction**: **200 / 200 (100.0% PASS)** exact match with recorded replay actions (fail closed).
- **Identity Digest**: `contexts_identity_sha256 = 7e63e0653a7718d61278fe2ae5ae9369653a4bd4a45e0c350b47df9eb72784ba` (all 200 triples authoritative 64-hex, globally unique).
- **Disagreement Rates vs FULL**:
  - `ENGINE_SCALE_88 vs FULL`: **0.0%** (0 / 200 differs)
  - `ENGINE_SCALE_50 vs FULL`: **1.0%** (2 / 200 differs)
  - `ENGINE_SCALE_25 vs FULL`: **3.0%** (6 / 200 differs)
- **Engine-Pivotal Behavior Flips**:
  - `ENGINE_SCALE_88`: **0.0%** (0 / 200 flips)
  - `ENGINE_SCALE_50`: **1.0%** (2 / 200 flips)
  - `ENGINE_SCALE_25`: **3.0%** (6 / 200 flips)

*Note*: The pre-repair P2 run (VOID, diagnostic only) had used a non-authoritative identity key (`state_hash_before:actor:ply`), 0-based stage boundaries, and canonical-position margins; its 2.5% Scale25 figure is superseded by the 3.0% authoritative value.

### 4. P3 Vector Heterogeneity Audit (7,725 Arena Contexts, Closure Repair 1)

Rebuilt in Closure Repair 1 with the same authoritative identity triple for context deduplication (root-actor `Phase::Main` contexts only, across all 384 accepted replays). Corpus identity digest: `corpus_identity_sha256 = a2127c0ac078f547135cab9bede44e0004094d73a8dd021f91a681f57e50abbb`.

Scanned all 384 replays in the P1 Arena corpus across all 7,725 unique authoritative-identity decision contexts, stratified across all observed $C$ values ($C \in \{0, 1, \dots, 20\}$):

| $C$ Stratum | Context Count $N_C$ | Distinct Bonus Vectors $K_C$ | Shannon Diversity $H_C$ (bits) | F4 Mean Value | E2 Mean Value |
|---:|---:|---:|---:|---:|---:|
| **0** | 567 | 1 | 0.000 | 792,769.0 | 496,437.4 |
| **1** | 575 | 5 | 2.267 | 1,454,260.9 | 511,565.2 |
| **2** | 604 | 15 | 3.734 | 1,675,662.3 | 526,473.5 |
| **3** | 547 | 34 | 4.715 | 1,393,601.5 | 541,224.9 |
| **4** | 562 | 54 | 5.432 | 1,695,907.5 | 555,676.2 |
| **5** | 567 | 82 | 5.893 | 2,110,405.6 | 570,493.8 |
| **6** | 566 | 100 | 6.108 | 2,328,445.2 | 584,311.0 |
| **7** | 571 | 107 | 6.308 | 2,673,204.9 | 596,042.0 |
| **8** | 555 | 127 | 6.477 | 2,801,621.6 | 604,810.8 |
| **9** | 565 | 148 | 6.807 | 3,287,079.6 | 607,115.0 |
| **10** | 510 | 153 | 6.868 | 3,865,039.2 | 610,686.3 |
| **11** | 441 | 152 | 6.862 | 4,284,852.6 | 611,179.1 |
| **12** | 338 | 134 | 6.702 | 4,834,142.0 | 612,455.6 |
| **13** | 240 | 114 | 6.452 | 5,321,291.7 | 612,916.7 |
| **14** | 165 | 86 | 6.096 | 6,367,090.9 | 613,939.4 |
| **15** | 106 | 67 | 5.760 | 6,750,094.3 | 614,056.6 |
| **16** | 63 | 43 | 5.176 | 7,609,841.3 | 615,555.6 |
| **17** | 32 | 26 | 4.542 | 8,300,625.0 | 615,625.0 |
| **18** | 15 | 13 | 3.565 | 8,837,333.3 | 616,666.7 |
| **19** | 6 | 6 | 2.585 | 11,385,000.0 | 616,666.7 |
| **20** | 1 | 1 | 0.000 | 10,700,000.0 | 617,000.0 |

---

## Result and Decision

### Official Ruling
All three sampled scale points ($W_C \in \{562.5\text{k}, 1.125\text{M}, 2.000\text{M}\}$) yield statistically **`UNRESOLVED`** outcomes against `FULL` ($2.250\text{M}$) at the Bonferroni-adjusted $98.333\%$ confidence level:
$$\boxed{\textbf{ENGINE\_SCALE\_25 UNRESOLVED / ENGINE\_SCALE\_50 UNRESOLVED / ENGINE\_SCALE\_88 UNRESOLVED}}$$

### Frozen Scientific Conclusion (Closure Repair 1, reviewer-approved wording)

> M44C establishes that total permanent bonuses and purchased-card count are algebraically non-identifiable as separate scalar information sources under the current base rules: both equal the same reachable-state scalar $C$. The three preregistered positive scale points—562.5k, 1.125M and 2.0M—were all UNRESOLVED against the 2.25M FULL baseline at the adjusted 98.333% confidence level. Separately, the historical M44B zero-engine arm was resolved weaker. Together these results are compatible with substantial scale robustness above zero, but do not identify a continuous robustness plateau, threshold, cliff location, monotonic response, or coefficient optimum.

### Interpretation Notes (licensed by the evidence)
1. **Resolution of the Naive LOO Question**:
   - The bonus-vs-purchased leave-one-out question is permanently closed as non-identifiable: $B \equiv P \equiv C$ on all reachable states, so the two terms are duplicate encodings of one scalar, not distinct information sources.
   - `ENGINE_SCALE_88` ($W_C = 2{,}000{,}000$) exhibits **0.0% action disagreement** across all 200 audited contexts in P2, and every one of the 64 paired seed blocks scored exactly 5,000.00 bps (paired-block distribution: `{5000.0: 64}`, frozen in the result artifact) in P1. This shows that the naive `DROP_PURCHASED` ablation (which is algebraically $W_C: 2.25\text{M} \to 2.0\text{M}$) preserves action choices in the audited sample — it does not establish that 2.0M and FULL are the same strategy in general.
2. **Scale Points Sampled**:
   - No strength difference was resolved at the sampled 25%, 50%, and 88.9% points against `FULL`.
   - In P2, `ENGINE_SCALE_50` ($1.125\text{M}$) changed 1.0% of decisions (2 / 200), and `ENGINE_SCALE_25` ($562.5\text{k}$) changed 3.0% of decisions (6 / 200).
   - The historical M44B zero-engine arm ($W_C = 0$) was resolved weaker on its own seeds. The combination is compatible with substantial scale robustness above zero, but M44C does not locate a threshold, cliff, plateau start, or continuous robust interval, and does not test unsampled values (including values below 562.5k other than zero).
3. **P3 Vector Heterogeneity & Structural Entry**:
   - Compressing the 5-dimensional bonus vector $\mathbf{b} \in \mathbb{N}^5$ into a single scalar $C$ discards extensive information: at typical mid-game engine sizes ($C = 6..10$), the agent encounters between 100 and 153 distinct color configurations with Shannon entropy exceeding 6.8 bits.
   - The code-level structural audit confirms that $\mathbf{b}$ already enters the evaluator through F4 (affordability) and E2 (noble progress). Therefore any future explicit vector probe must account for overlap with these existing paths. This does **not** establish that scalar $C$ is sufficient — only that the color vector is not wholly absent from the current evaluator.

---

## Known Limitations

1. **Calibration Discretization**: M44C evaluated coarse scale points (25%, 50%, 88.89%) plus the historical zero point from M44B. The results are compatible with substantial scale robustness above zero, but do not identify a continuous robustness plateau, threshold, cliff location, monotonic response, or coefficient optimum, and do not test unsampled values below 562.5k other than zero.
2. **Observational Variance**: In-stratum variance of F4 and E2 across the Arena corpus reflects whole-state co-variance (market cards, player tokens, available nobles), not isolated counterfactual vector effects.
3. **Search Horizon**: All findings are established under the frozen $n1$ static-successor shell (`max_nodes = 1`).
4. **Equality Degeneration of Scale88 Arena Outcome**: The Scale88 pairing's degenerate `[5000, 5000]` CI reflects exact paired-block equality on these 64 seeds (every block scored 5,000.00 bps). This is an outcome-equality observation on this sample, not proof that the two configurations are the same strategy in general.

---

## Iteration Log (Closure Repair 1)

### 2026-09 — M44C Terminal Review on `58863f8`

The terminal review **accepted** the P1 384-match Arena (frozen; rerun FORBIDDEN) and the core algebraic conclusion, but ordered Closure Repair 1 before permanent closure:

1. **P0 authoritative corpus gap (PARTIAL)**: M44C's `frozen_m07_12_cases()` was a re-invented corpus that did not match the sealed M44A authoritative 12-case definitions (2p prefixes had 4 actions instead of 6; 4p prefixes differed in slot numbers and order). Because P0-B/P0-C claims rest on algebra plus 140 reachable-state bit-exact regressions, this was an evidence gap, not a treatment invalidation — the Arena was not voided. **Repair**: M44C's corpus was replaced byte-for-byte with the sealed M44A definitions; all 4 P0 tests re-passed on the authoritative corpus.
2. **P2 VOID (identity violation)**: The pre-repair P2 used `state_hash_before:actor:ply` as the dedup key and wrote fake identity fields (`visible_history_hash = len(events)`, `information_set_hash = "seed:ply"`), violating the DESIGN_V2-frozen authoritative identity triple and changing which 200 contexts were selected. **Repair**: rebuilt on the authoritative triple via `build_information_set_v1` (identical pipeline to `analyze-replay-player-view` source metadata), with per-player cumulative visible histories. Scale25 disagreement changed 2.5% → **3.0%** (6/200).
3. **P2 off-by-one staging**: The pre-repair code classified stages on 0-based indices (early = decisions 1–21). **Repair**: `decision_ply = zero_based_step_index + 1`, early 1–20 / mid 21–45 / late 46+.
4. **P2 margin miscalculation**: The pre-repair code read `aggregates[0] - aggregates[1]` (canonical positions), not top-1 vs runner-up. **Repair**: margins computed from sorted root utilities with ties broken by canonical order, asserting best-equals-selected.
5. **P3 PROVISIONAL → rebuilt**: Same non-authoritative dedup key. **Repair**: rebuilt on the authoritative triple (root-actor `Phase::Main` contexts only); corpus statistics regenerated (7,725 unique contexts, 21 strata, new `corpus_identity_sha256`).
6. **Final-audit hardening**: `m44c_final_audit.py` now fail-closed asserts the frozen P1 numbers, exact P2 quota matrix, 200/200 reproduction, 64-hex authoritative identities, global identity uniqueness, 1-based staging convention, P3 strata consistency, and records the Scale88 paired-block score distribution explicitly (`{5000.0: 64}`).
7. **Provenance**: `catalog_semantic_hash` was an empty string; now computed from the real catalog loader (matches M44B's authoritative value `4c90cb85...`).
8. **Documentation**: Over-strong interpretations ("broad robustness plateau", "cliff bracketed in [0, 562500)", "scalar C suffices") were replaced with the reviewer-approved frozen conclusion wording.

Non-blocking note recorded by the reviewer: the `fd0211d → 58863f8` round had reformatted the sealed `m44a_p0_semantic.rs` (+367/−85 churn). The semantics were verified unchanged; the file was not reverted (further churn was judged worse than leaving it). Future milestones must not reformat permanently closed test files.

---

## Next Authorized Gate

M44C Closure Repair 1 executed in full (P0 evidence re-bound, P2/P3 rebuilt on authoritative identities, final audit hardened, provenance completed). The 384-match P1 Arena remains frozen and accepted; no Arena rerun was performed.
Awaiting final closure signature for M44C.
Next authorized research direction (NOT YET AUTHORIZED to start):
- **M45A — Bonus-Vector Information Probe**: Investigating whether explicit color-vector representations (beyond the scalar count $C$) provide distinct, actionable playing-strength value when properly decoupled from F4 affordability and E2 noble progress.
