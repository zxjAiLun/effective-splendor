"""M40A frozen constants: the single source of truth for every number
the design document (docs/m40a-predictive-critic-warmstart-ab.md,
design SHA 09fd8ec) froze.

Any change here is an amendment under the design review contract, not an
implementation detail.
"""

from __future__ import annotations

# --- Identity -----------------------------------------------------------
DESIGN_SHA = "09fd8ec"
PLAN_FORMAT = "effective-splendor-m40a-plan"
PLAN_VERSION = 1

# --- Head architecture --------------------------------------------------
VP_BINS = 31                    # k ∈ 0..30; label > 30 fails closed
VP_MAX = 30
VP_DIFF_NORMALIZER = 15.0       # clamp((VP_self − VP_opp)/15, −1, +1)
TIMING_HORIZONS = (2, 4, 8)     # own decision turns; pending decision = #1

# --- Offline pretraining ------------------------------------------------
SPLIT_IDENTITY_SEED = 40_260_901
PRETRAIN_SHUFFLE_SEED = 40_260_902
HEAD_INIT_SEED = 20_260_829     # INTENTIONALLY INHERITED from M39A
PRETRAIN_LR = 3e-4
PRETRAIN_WEIGHT_DECAY = 1e-4
PRETRAIN_EPOCHS = 16
PRETRAIN_BATCH = 512
PRETRAIN_GRAD_CLIP = 1.0
VALIDATION_FRACTION = 0.20
SPLIT_STRIDE = 5                # ceil(1 / 0.20)

FORCED_TRAIN_GAME = 2785        # the single truncated game

# --- PPO (M39A inheritance + 4-cycle recomputation) ---------------------
PPO_TRAINER_SEED = 40_260_830   # INTENTIONALLY INHERITED; shared by A and B
PPO_MINIBATCH = 512
PPO_EPOCHS_PER_CYCLE = 4
PPO_CYCLES = 4
PPO_GAMES_PER_CYCLE = 512
ENTROPY_COEFFICIENT = 0.010
VALUE_COEFFICIENT = 0.500
WEIGHT_DECAY = 1e-4
GRAD_CLIP_NORM = 1.0
PPO_CLIP_EPSILON = 0.2
GAE_LAMBDA = 0.95
ADVANTAGE_EPSILON = 1e-8
LR_WAYPOINTS = [
    1.000000e-04,
    7.750000e-05,
    3.250000e-05,
    1.000000e-05,
]
# Predictive auxiliary families: coefficient budget 0.250 split three ways.
AUX_FAMILY_COEFFICIENT = 0.250 / 3.0     # 1/12 each
AUX_FAMILY_COUNT = 3
AUX_COEFFICIENT_BUDGET = 0.250

# --- Collection / evaluation seeds (fresh Arena/collection ranges) ------
TRAINING_SEED_BASE = 8_000_000           # 8_000_000..8_001_023 shared A/B
TRAINING_SEED_BLOCKS = 1_024
H1_SEED_BASE = 8_100_000                 # 128 blocks × 2 rotations
H1_SEED_BLOCKS = 128
LEAGUE_SEED_BASE = 8_200_000             # 32 blocks × 2 rotations × 9 opponents
LEAGUE_SEED_BLOCKS = 32
M07_SEED_BASE = 8_300_000                # 64 blocks × 2 rotations (B only)
M07_SEED_BLOCKS = 64
D2_SEED_BASE = 8_400_000                 # 64 blocks × 2 rotations (B only)
D2_SEED_BLOCKS = 64

# --- Frozen statistics ---------------------------------------------------
H1_CRITICAL_DF127 = 1.656940343542       # one-sided 95%, df = 127
LEAGUE_CRITICAL_DF31 = 1.695518782546    # one-sided 95%, df = 31
ANCHOR_CRITICAL_DF63 = 1.998340542521    # two-sided 95%, df = 63

# --- Frozen dataset cardinalities (derived by the frozen split rule) ----
COMPLETED_GAMES = 4_095
VALIDATION_COMPLETED_GAMES = 823
TRAINING_COMPLETED_GAMES = 3_272
TRAINING_TRUNCATED_GAMES = 1
TRAINING_TOTAL_GAMES = 3_273

LEAGUE_ORDER = [
    "M24-S2",
    "M25-D2-v2",
    "M28A",
    "M28B",
    "M29A-v2",
    "M31A",
    "M32A",
    "M33A",
    "M34A",
]
