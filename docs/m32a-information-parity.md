# M32A — Teacher–Student Information Parity: Belief Projection

```ini
MILESTONE = M32A
STATUS = PROPOSED / DESIGNED / UNIT_TESTED / PENDING_REVIEW
BASE_COMMIT = bda55bae30d6350bf22923da82d56a3106da09a2
SCOPE = Evaluate whether providing D2 Student with a fixed 212-dim deterministic InformationSetV1 belief projection (unseen card mask + opponent reserve slot visibility + purchased counts) closes the teacher-student information gap and breaks the 38.4% policy fit ceiling under canonical soft CE.
DATASET = Canonical M25 dataset (256 games, 16,282 examples: 12,216 train / 4,066 val), 100,000 micros uniform floor.
SIDECAR = Deterministic 212-dim belief features exported via verified Rust InformationSetV1 reconstruction from matches 0..255 (local-artifacts/m32a-belief-sidecar/m32a-belief-sidecar.json).
TRAINING = PLANNED (128 epochs, lr=3e-4 cosine, wd=1e-4, checkpoint selected strictly by validation canonical policy CE).
OFFLINE_GATES = G1 Primary Gate (Val Top-1 >= 45.00%, Val CE improvement >= 1000 bps) -> Authorize G2 only; Information Parity Signal Gate (Relative to D2 baseline: Val CE <= -0.030 nats and Top-1 delta >= +3.0 pp).
FIT_ATTRIBUTION = Tests the Information Asymmetry Hypothesis: whether M07 search teacher's root determinization relies on visible-history belief constraints that were previously omitted from the Student observation encoder.
DECISION = PENDING_REVIEW
ARENA = NOT_AUTHORIZED
MODEL_TRAINING = NOT_STARTED_PENDING_REVIEW
PROMOTION = NONE
CHAMPION = M07
```

## Problem and evidence

Across M25, M29, M30, and M31 series:
1. **Experiment D2** proved that injecting 23-dim exact post-action state transition deltas into action embeddings yielded a major fit improvement (Val CE 2.8879 $\to$ 2.8177, Top-1 31.87% $\to$ 38.42%).
2. **Experiment B & E** ruled out model width scaling (0.95M $\to$ 2.61M parameters yielded $\le 0.0020\text{ nats}$ CE reduction).
3. **M29A-v1/v2** ruled out dynamic action-to-entity cross-attention pooling (gain $\le 0.0043\text{ nats}$).
4. **M30A** proved that 4-sample teacher search targets already have 76.56% repeat agreement (median JSD 0.0019 nats), ruling out teacher sampling variance.
5. **M31A** proved that uncalibrated pairwise ranking objectives distort global softmax calibration (Val CE 2.8375, Top-1 35.91%).

Source trace into `crates/splendor-imperfect-search` and `crates/splendor-belief` revealed a fundamental information asymmetry:
- **M07 Teacher**: Takes `current_observation + visible_history` $\to$ constructs `InformationSetV1` $\to$ tracks exact card flows, opponent reserve visibility (public vs blind deck), and the canonical `unseen_cards_by_tier` partition $\to$ samples root determinizations.
- **D2 Student**: Only saw a cross-sectional 40-dim observation summary and entity slots, discarding card purchase history and opponent blind-reserve slot classifications.

The core question tested in **M32A** is:

> Does providing Student with a deterministic, non-leaking 212-dim projection of the exact `InformationSetV1` used by M07 Teacher break the student policy fitting bottleneck?

## Frozen experimental design

1. **Deterministic Belief Projection (212 Dimensions, Contract `m32a_information_set_projection_v1`)**:
   - **Part A: `unseen_card_mask` (90 dims, CardId 0..89)**:
     - Binary indicator: `1.0` if card is in `info_set.unseen_cards(tier)`, `0.0` otherwise.
   - **Part B: `reserved_knowledge` (2 players $\times$ 3 slots $\times$ 20 dims = 120 dims)**:
     - Slot status one-hot (6 dims): `empty`, `known_public`, `known_private_from_deck`, `hidden_tier_1`, `hidden_tier_2`, `hidden_tier_3`.
     - Known card attributes (14 dims): tier one-hot (3), bonus one-hot (5), prestige (1), costs (5).
     - **Invariance Rule**: For `HiddenDeck` slots and `empty` slots, card attributes are strictly **ZERO** (no hidden card identity leakage).
   - **Part C: `purchased_count` (2 dims)**:
     - Viewer and opponent purchased card counts (normalized by 20.0).
   - **Strict Negative Constraint**: Hashes (`visible_history_hash`, `information_set_hash`), seeds, and hidden card identities are never exposed to the model.

2. **Model Architecture**:
   - Base architecture: `BeliefDeltaEntityMixer` (h192/b4, 59-dim exact action deltas).
   - Global features extended from 40 to $40 + 212 = 252$ dims.
   - Total parameter count: **994,180** (953,476 base + 40,704 global linear projection weights).

3. **Dataset & Partition**:
   - Canonical M25 materialized dataset (`12,216` train / `4,066` val, `init_seed = 280229`, `shuffle_seed = 20260823`).
   - Strict 1-to-1 join by `example_index` (0..16,281) with row-level validation of `example_index`, `source_id`, `evaluation_match_index`, `ply`, `actor`, and `information_set_hash`.
   - Sidecar root metadata binds `exporter_file_sha256`, `ordered_256_replay_bundle_digest`, and `feature_contract_version = m32a_information_set_projection_v1`.

4. **Training & Checkpoint Selection**:
   - Canonical Soft-Target Cross-Entropy (10% floor, 1,000,000 micros).
   - Optimizer: AdamW lr=3e-4, wd=1e-4, 128 epochs cosine schedule.
   - Checkpoint selection strictly by **validation canonical policy CE** (`val_res["ce"]`).

## Acceptance and decision gates

1. **G1 Primary Gate**:
   - Validation Top-1 $\ge 45.00\%$ AND Validation CE improvement $\ge 1000\text{ bps}$.
   - If PASS $\to$ Authorize G2 transfer only (no direct Arena authorization).
2. **Information Parity Signal Gate**:
   - Relative to Exp D2 baseline (Val CE 2.8177, Top-1 38.42%):
     - $\Delta\text{CE} \le -0.030\text{ nats}$ (Val CE $\le 2.7877$) AND $\Delta\text{Top-1} \ge +3.0\text{ pp}$ (Top-1 $\ge 41.42\%$)
   - If PASS $\to$ Record as confirmed information parity signal for belief architecture development.
3. **Negative Result Rule**:
   - If both gates fail $\to$ `STOP_EXACT_INFORMATION_SET_PROJECTION_ROUTE`. Strictly bounded to this exact projection without overgeneralizing to all history representations.

## Contracts and invariants (Unit Tested)

- **Rust Belief Projection Verification**: `crates/splendor-cli/tests/m32a_belief_features.rs` verifies 212-dim structure, non-zero HiddenDeck status with strictly zero card attributes, and empty slot encodings.
- **Python Model Parameters**: `test_model_parameter_count` asserts parameter count equals 994,180.
- **Sidecar Integrity & Non-Leakage**: `test_sidecar_validator_integrity_and_leakage_detection` validates completeness, root metadata, feature bounds, and fail-closed detection of leaked attributes in HiddenDeck slots.
- **Real Provenance Preflight**: `test_real_provenance_preflight_for_m32a` validates 64-char dataset/catalog semantic hashes, config SHA, D2 baseline SHA, root metadata, and metadata matching across all 16,282 examples via real `preflight_m32a` invocation.

## Artifact hashes and evidence

| Artifact | Path | Content / File SHA-256 |
| --- | --- | --- |
| Benchmark Config | `benchmarks/m25-m07-search-teacher-bootstrap-v2.config.json` | `bf13f32bc5eabf1b30795230057b6af68ce14b5cd23c8f526d635e054b3ee250` |
| Dataset Reference | `local-artifacts/m25-generation/m25-materialized-dataset.json` | `2e15cc9d3f96c0993e3746f45c4eb24d3e1bf92f80c2b515d5f171f1e1f05907` |
| Dataset Semantic Hash | Exact semantic identity across 16,282 examples | `1aa7212ff070e637d0f0aeabf6eddd16e0d00fc1d5a6aa9da93e75be69975419` |
| Catalog Semantic Hash | Exact card & noble entity catalog hash | `4c90cb85d565e74af3e955df62d431174aaf5a8d4192895f95c8d21d57d78a26` |
| Baseline D2 Result | `benchmarks/m25-recovery-exp-d2.result.json` | `403e4903044dfec929c6e92713b2bb9f3e120469ab872271dc82e78f752efc38` |
| Sidecar Exporter | `crates/splendor-cli/src/bin/m32a_export_sidecar.rs` | Verified Rust InformationSetV1 Exporter |
| Preflight Guard | `training/m17_gpu/splendor_gpu/m32a_preflight.py` | Strict fail-closed sidecar & provenance validator |
| Training Script | `training/m17_gpu/splendor_gpu/m32a_train.py` | M32A GPU Training Runner (128 epochs) |
| Rust Unit Tests | `crates/splendor-cli/tests/m32a_belief_features.rs` | Belief projection unit tests (passed) |
| Python Unit Tests | `training/m17_gpu/tests/test_m32a_information_parity.py` | Model, sidecar, and preflight unit tests (passed) |
| Milestone Document | `docs/m32a-information-parity.md` | M32A Design & Contract Document |
