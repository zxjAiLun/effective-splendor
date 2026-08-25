# M30A — M07 Teacher Target Stability Probe

```ini
MILESTONE = M30A
STATUS = COMPLETED / STOP_TEACHER_VARIANCE_ROUTE / NO_ARENA / NO_MODEL_TRAINING
BASE_COMMIT = 085233d256241b71aa5a3fe1ff1068a0a867db2b
SCOPE = Evaluate M07 search teacher target test-retest stability across sample counts (4 vs 16 samples) on 256 stratified positions to determine whether teacher target variance is the primary bottleneck preventing offline policy fitting.
DATASET = 256 stratified positions from canonical M25 materialized dataset (64 early game, 80 mid game, 112 late game).
PROBE_SETUP = Depth=1, 2000 nodes, 100,000 micros uniform floor, comparing independent seed blocks A (20260810) vs B (20260811) for sample_count=4 and sample_count=16.
OFFLINE_GATES = Stability Gate FAIL (16-sample vs 4-sample Top-1 agreement delta +2.34 pp < +8.0 pp threshold; median JSD relative reduction -19.26% < 25.0% threshold).
FIT_ATTRIBUTION = 4-sample search targets already have 76.56% repeat Top-1 agreement and low median JSD (0.0019 nats). Scaling from 4 to 16 samples increases repeat agreement only marginally from 76.56% to 78.91% (+2.34 pp) with median JSD at 0.0023 nats, proving that teacher sampling variance is not the dominant cause of the ~38.4% student fit ceiling.
DECISION = STOP_TEACHER_VARIANCE_ROUTE
ARENA = NOT_AUTHORIZED
MODEL_TRAINING = NOT_AUTHORIZED
PROMOTION = NONE
CHAMPION = M07
```

## Problem and evidence

Across the M25/M29 series:
1. Student policy distillation plateaus at **~38.4% validation Top-1** (D2: 38.42%, E: 38.47%, M29A-v2: 38.66%) and **~40.4% training Top-1**.
2. Both model width scaling (0.95M $\to$ 2.61M parameters in Exp B/E) and dynamic action-to-entity cross-attention pooling (M29A-v1/v2) yielded near-zero validation improvements ($\le 0.004\text{ nats}$ CE reduction).
3. The core hypothesis tested in **M30A** was:

> Is the ~38.4% student policy top-1 ceiling caused by stochastic variance in the 4-sample M07 imperfect-information search teacher targets? If 4-sample search targets suffer from high monte-carlo determinization variance, increasing search samples to 16 should dramatically stabilize the teacher targets (increasing repeat Top-1 agreement by $\ge 8\text{ pp}$ and reducing median Jensen-Shannon Divergence by $\ge 25\%$) and justify regenerating the entire 16,282-example dataset with 16 samples.

## Design and experimental protocol

### 1. Stratified Position Selection
- Sample 256 positions from the 256 games in the canonical M25 dataset:
  - **Early game (ply < 16)**: 64 positions (matches 0..63)
  - **Mid game (16 $\le$ ply < 36)**: 80 positions (matches 64..143)
  - **Late game (ply $\ge$ 36)**: 112 positions (matches 144..255)
- Stratification strictly mirrors the natural ply distribution of the 16,282-example corpus (25.2% early, 31.4% mid, 43.4% late).

### 2. Independent Repeat Generation
For every position $i \in [0..255]$:
- Search configuration: `max_depth_turns = 1`, `max_nodes = 2000`, `uniform_floor_micros = 100_000` (standard M25 teacher configuration).
- **Condition 1 (4 samples)**:
  - Run with Seed Block A (`sample_seed = 20260810`, `sample_count = 4`) $\to P_{4, A}$, $\text{Top1}_{4, A}$.
  - Run with Seed Block B (`sample_seed = 20260811`, `sample_count = 4`) $\to P_{4, B}$, $\text{Top1}_{4, B}$.
  - Repeat stability: Agreement $I(\text{Top1}_{4, A} == \text{Top1}_{4, B})$ and $\text{JSD}(P_{4, A} \parallel P_{4, B})$.
- **Condition 2 (16 samples)**:
  - Run with Seed Block A (`sample_seed = 20260810`, `sample_count = 16`) $\to P_{16, A}$, $\text{Top1}_{16, A}$.
  - Run with Seed Block B (`sample_seed = 20260811`, `sample_count = 16`) $\to P_{16, B}$, $\text{Top1}_{16, B}$.
  - Repeat stability: Agreement $I(\text{Top1}_{16, A} == \text{Top1}_{16, B})$ and $\text{JSD}(P_{16, A} \parallel P_{16, B})$.

### 3. Acceptance / Authorization Gates
- **Top-1 Agreement Gate**: $\text{Agreement}_{16} - \text{Agreement}_4 \ge +8.00\text{ pp}$ (+0.0800).
- **JSD Reduction Gate**: $(\text{MedianJSD}_4 - \text{MedianJSD}_{16}) / \text{MedianJSD}_4 \ge 25.0\%$.
- **Action Threshold**: If both pass $\to$ authorize M30B (16-sample full dataset rebuild and retrain); if either fails $\to$ `STOP_TEACHER_VARIANCE_ROUTE`.

## Contracts and invariants

- **No Model Training**: Probe evaluates pure search target stability without training neural networks.
- **No Arena Execution**: No arena matches authorized.
- **Exact Information Boundary**: Replay player view and visible history reconstruction match the verified runtime engine and imperfect search protocol.
- **Reproducibility**: Explicit seed blocks A (`20260810`) and B (`20260811`).

## Artifact hashes and evidence

| Artifact | Path | Content / File SHA-256 |
| --- | --- | --- |
| Probe Runner | `crates/splendor-cli/src/bin/m30a_probe.rs` | Multi-threaded Rust stability probe |
| Result Document | `benchmarks/m30a-teacher-target-stability-probe.result.json` | Full per-position and aggregate results |
| Materialized Dataset Reference | `local-artifacts/m25-generation/m25-materialized-dataset.json` | `2e15cc9d3f96c0993e3746f45c4eb24d3e1bf92f80c2b515d5f171f1e1f05907` |

## Validation and evidence

### Repeat Stability Summary (256 Stratified Positions)

| Metric | 4-Sample Search Teacher | 16-Sample Search Teacher | Delta (16 vs 4) | Preregistered Gate Target | Gate Status |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Top-1 Repeat Agreement** | 76.56% (196/256) | 78.91% (202/256) | **+2.34 pp** | $\ge +8.00\text{ pp}$ | **FAIL** |
| **Median JSD (nats)** | 0.0019 | 0.0023 | +0.0004 | $\ge 25.0\%\text{ relative reduction}$ | **FAIL** (-19.26%) |
| **Mean JSD (nats)** | 0.0381 | 0.0243 | -0.0138 (-36.2%) | — | (Tail reduction only) |
| **P25 JSD (nats)** | 0.0002 | 0.0002 | 0.0000 | — | — |
| **P75 JSD (nats)** | 0.0343 | 0.0240 | -0.0103 | — | — |

## Result and decision

1. **Gate Evaluation**:
   - Top-1 Agreement improvement was only **+2.34 pp** (from 76.56% to 78.91%), falling far short of the $\ge +8.0\text{ pp}$ requirement.
   - Median JSD was already near-zero (0.0019 nats) at 4 samples and remained virtually identical at 0.0023 nats at 16 samples (relative median reduction -19.26%, failing the $\ge 25.0\%$ requirement).
   - While 16 samples reduced the tail mean JSD (0.0381 $\to$ 0.0243), the core decision ranking remains highly consistent across independent seed blocks even at 4 samples.
2. **Scientific Conclusion**:
   - The teacher search targets are already remarkably stable at 4 samples (76.56% repeat agreement, median JSD < 0.002 nats).
   - Therefore, monte-carlo sampling variance in the search teacher is **not** the primary cause of the student policy's 38.4% validation fit plateau.
   - 4x compute scaling on teacher generation (from 4 to 16 samples) will not bridge the gap to G1 (45% Top-1 / 1000 bps).
3. **Formal Decision**:
   - **`STOP_TEACHER_VARIANCE_ROUTE`**: Do not proceed with M30B full-corpus 16-sample rebuild.
   - **Model Training**: `NOT_AUTHORIZED`.
   - **Arena Execution**: `NOT_AUTHORIZED`.
   - **Promotion**: `NONE`. M07 champion remains unchanged.
