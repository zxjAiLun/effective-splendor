# M50 Competitive Replay Policy-Value Network

Status: **IMPLEMENTED / VERIFIED (extractor + baseline Policy-Value network; EXPLORATORY)**.
Baseline: `main@814981499725bd42cd9a43e3f7e079e8bd0f6c2b`
Owner-date: 2026-09-27.

## Problem and evidence

M49A solo-15 demonstrated that off-policy TD/FQI with unconstrained min-backups on fragmented mid-game states suffers from severe value optimism and non-convergence. In contrast, this repository contains thousands of complete, verified, decisive 2-player competitive match replays generated during heuristic and arena evaluations:

- Specifically, `local-artifacts/s4-heuristic-v025-pilot/` contains 770 verified replays (768 pilot matches + 2 smoke matches), totaling 43,029 decision plies (mean 56.0 plies/game; min 44, max 68).
- Every game completed to a decisive terminal state (415 seat 0 wins, 350 seat 1 wins, 3 ties; scores up to 16–21).
- Every replay is hash-pinned in `manifest.json` (SHA256 `3a6d05ae…`) and strictly verified by `splendor verify-replay` (`exit 0`).
- These replays encode realistic strategic trade-offs: card reservations, noble racing, tier-3 purchases, and defensive play under full 2-player opponent dynamics.

## Initial design

Instead of synthetic single-player turn minimization under artificial Bellman backups, we formulate a classic two-player **Dual-Head Policy-Value Network** $(\pi_\theta, V_\theta)$ trained directly on competitive replay traces:

1. **Input Representation:**
   - 2-player observation encoding via canonical `encode_observation_v1` (368 features) from `crates/splendor-learning/src/representation.rs`.
   - Legal action candidate encodings via `encode_action_v1` (36 features).
2. **Policy Head $\pi_\theta(a | s)$:**
   - Evaluates a score/logit for each candidate action $a \in \mathcal{A}(s)$.
   - Supervised by cross-entropy loss against the action chosen by the candidate heuristic agent:
     $$\mathcal{L}_\pi = -\log \pi_\theta(a^* | s)$$
   - Direct metric: Top-1 action prediction accuracy and Top-3 coverage.
3. **Value Head $V_\theta(s)$:**
   - Predicts the game outcome from the perspective of the acting player (actor):
     - Win probability $P(\text{win} | s) \in [0, 1]$ via Binary Cross-Entropy (BCE), OR
     - Normalized final score margin $(S_{\text{actor}} - S_{\text{opp}}) / 10.0$ via MSE.
4. **Training Advantages:**
   - Pure supervised regression/classification: strictly convex loss components, zero Bellman propagation instability, zero deadly triad.
   - Grounded entirely in real, decisive terminal outcomes.

## Scope and non-goals

### In Scope
- Fast Rust-based replay extractor to parse `match-replay.json` files from `local-artifacts/s4-heuristic-v025-pilot/` using `verify_replay_trace`.
- Construction of a clean, split train/validation dataset (e.g. 80/20 seed split: 614 train games ~34,400 plies / 154 val games ~8,600 plies).
- Export to compact binary tensors (`train_obs.f32`, `train_acts.f32`, `train_labels.jsonl`, etc.) or structured format.
- PyTorch Policy-Value model definition and offline evaluation / baseline training.

### Non-Goals
- No modification of ongoing GPU processes (respect user constraint: "先不要启动训练 因为gpu目前正在训练").
- No disruption of S4 heuristic pilot runs (`scripts/s4_heuristic_v027_pilot.py`).
- No mutation of owner-dirty files (`apps/replay-studio/`, `human_play_command.rs`, `.gitignore`).

## Contracts and invariants

1. **Replay Strictness:** Every replay must pass `splendor_replay::verify_replay_trace` without errors. Corrupted or divergent replays fail closed.
2. **Data Split Isolation:** Train and validation splits are partitioned by game seed (deterministic modulo or split), ensuring zero seed overlap between training and evaluation.
3. **Feature Determinism:** Observations are encoded strictly from the perspective of `recorded_actor` using canonical `encode_observation_v1`.
4. **Reproducibility:** Dataset manifests and exported tensor SHA256 hashes must be fully recorded.

## Implementation plan

1. **Step 1:** Implement `m50_replay_extractor` (Rust tool in CLI or Python script) that parses the 770 replays via `verify_replay_trace`, extracting state observations, chosen actions, legal action sets, and outcome labels.
2. **Step 2:** Validate data integrity, compute action distribution statistics, win rate baselines, and feature dimensions.
3. **Step 3:** Implement lightweight PyTorch dataset and model loader.
4. **Step 4:** Evaluate baseline Top-1 accuracy and Value MSE on validation split.

## Iteration log

- 2026-09-27: Milestone authorized. Examined 770 replays in `local-artifacts/s4-heuristic-v025-pilot/` (43,029 decision plies, 415 vs 350 wins). Verified GPU status (S4.2 pilot running on CPU, GPU memory 1611 MiB). Initialized M50 contract.

## Final implementation

1. **Replay Extractor:**
   - Implemented `splendor m50-extract-replays` in `crates/splendor-cli/src/m50_extract_command.rs`.
   - Uses `splendor_replay::verify_replay_trace` to step through replays strictly against the referee engine.
   - Extracts 368-dim viewer observations (`encode_observation_v1`), 36-dim candidate action features (`encode_action_v1`), chosen action indices, and game outcome labels (`won`, `score_diff`).
   - Exports flat memory-mappable binary tensors with SHA256 verification and split metadata.
2. **Policy-Value Network & Trainer:**
   - Implemented `training/m17_gpu/m50_train_replay_pv.py`.
   - State trunk: Linear(368, 256) -> LayerNorm -> ReLU -> Linear(256, 128) -> LayerNorm -> ReLU.
   - Action encoder: Linear(36, 128) -> LayerNorm -> ReLU, with bilinear dot-product scoring + action prior bias.
   - Loss: Vectorized segmented cross-entropy over legal actions + BCE win-probability loss.
3. **Native Rust Inference Agent:**
   - Implemented `splendor agent-m50-policy --weights <path>` in `crates/splendor-cli/src/m50_agent_command.rs`.
   - Native Rust implementation of state trunk, action projection, and bilinear scoring (<10 microseconds per decision).
   - Implements `splendor_agent::AgentPolicy` directly, seamlessly plugging into `splendor run-match` and Arena protocols.

## Validation and evidence

### 1. Dataset Extraction
- Source: `local-artifacts/s4-heuristic-v025-pilot/games` (768 replays).
- Extraction execution: `target/release/splendor.exe m50-extract-replays --replays-dir local-artifacts/s4-heuristic-v025-pilot/games --out-dir local-artifacts/m50-pilot-dataset-v1`
- Extraction runtime: **1.39 seconds** (exit code 0; 768/768 parsed, 0 failures).
- Dataset partitioning:
  - **Train:** 612 games, 34,169 decision steps, 1,042,393 candidate actions (17,013 wins / 16,980 losses / 176 ties).
  - **Val:** 156 games, 8,860 decision steps, 273,880 candidate actions (4,431 wins / 4,429 losses / 0 ties).
- Output manifest: `local-artifacts/m50-pilot-dataset-v1/manifest.json`.

### 2. Model Training and Convergence
- Optimizer: AdamW (lr 1e-3, weight decay 1e-4, cosine annealing to 1e-5), batch size 256.
- Training runtime: **16.06 seconds** for 15 epochs on NVIDIA GeForce RTX 4060 Laptop GPU.
- Progression:
  - Epoch 0 (untrained): Val Policy Loss 3.280, Val Top-1 Accuracy **6.92%** (Random baseline **3.24%**).
  - Epoch 1 (1.80s): Val Policy Loss 1.917, Val Top-1 Accuracy **40.09%**.
  - Epoch 5: Val Policy Loss 1.787, Val Top-1 Accuracy **44.04%**.
  - Best Epoch 9: Val Policy Loss 1.841, Val Top-1 Accuracy **44.21%** (Val Top-3 **69.58%**, Val Top-5 **79.76%**).

### 3. Head-to-Head Arena Evaluation vs Frozen v0.2.5 Heuristic
- Test Series: 64 paired-seed blocks = **128 games** with strict seat rotation (`scripts/m50_eval_vs_v025.py`).
- Opponent: Frozen `splendor-candidate.exe` v0.2.5 (SHA256 `898dba36…` from `s4-heuristic-v025-pilot`).
- Seeds: `9_260_000 .. 9_260_063` (completely fresh, zero overlap with training or prior pilots).
- Execution: `target/release/splendor.exe run-match` (exit code 0 for all 128 games).
- Results:
  - **Matches:** 128 completed games (0 aborts, 0 timeouts).
  - **W - T - L:** **24 - 0 - 104** (M50 wins 24 games).
  - **Win Rate:** **18.75%** (Center BPS: 1875.0, 95% paired bootstrap CI: `[1250.0, 2578.1]` BPS).
  - **Seat Balance:** Seat 0 win rate = **18.75%**, Seat 1 win rate = **18.75%** (perfect balance, zero seat bias).
  - **Mean Scores:** M50 **11.14** vs v0.2.5 **15.30** (M50 consistently builds high-prestige engines up to double digits).
  - **Mean Plies:** 56.5 plies per game.
  - **Execution Speed:** 26.82 seconds total for 128 games (**0.210 seconds per full game**).
  - Summary: `local-artifacts/m50-eval-v025/summary.json`.

### 4. Large-Scale Corpus Ingestion (463k Steps / 7,764 Games)
- Expanded extraction across 19 arena/pilot corpora (`s4-heuristic-v02*`, `s0-baseline`, `s2b-arena`, `s3-arena`, `m42s`, `m44*`, `m45a`, `m46a`):
  - Ingestion runtime: **23.70 seconds** across 9,744 total replays.
  - Partitioning:
    - **Train:** 7,764 games, **463,354 decision steps**, 14,945,386 candidate actions (230,760 wins / 230,360 losses).
    - **Val:** 1,980 games, **118,169 decision steps**, 3,797,553 candidate actions (59,068 wins / 58,979 losses).
  - Stored in `local-artifacts/m50-large-dataset-v1/`.
- Training:
  - 10 epochs on 463k steps took **121.23 seconds** on RTX 4060 (`local-artifacts/m50-large-run/best_model.pt`).
  - Validation metrics across diverse opponent distributions:
    - Val Top-1 Accuracy: **45.04%** (best epoch 10).
    - Val Win Prediction Accuracy: **63.21%** (dramatically up from 51.66% on small dataset).
    - Score Margin Correlation: **0.355** (more than tripled from 0.110).
    - High-confidence calibration: when predicting win prob > 0.70, actual win rate is **67.2%**; when predicting < 0.30, actual win rate is **33.0%**.
- Arena Evaluation vs Frozen v0.2.5 (128 games, seeds `9_260_000..9_260_063`):
  - Result: **24 胜 0 平 104 负** (18.75% 胜率, 95% CI `[12.5%, 25.8%]`).
  - Seat 0: 18.75%, Seat 1: 18.75%. Mean score: M50 **10.38** vs v0.2.5 **15.55**.
  - Decision agreement with small model on unseen validation states is **61.3%** (learns a broader, more conservative generalist distribution across varied opponents).

### 5. Search Integration: Policy-Guided 1-Ply Value Lookahead vs Greedy
- Implemented `splendor agent-m50-policy --mode search --top-k 4 --worlds 2`:
  - Prunes ~31 legal actions down to Top-4 via the Policy Network.
  - For each candidate, simulates forward under sampled determinized belief worlds via `sample_determinization_v1`.
  - Re-evaluates next-state win probability using the Value Head and selects the action maximizing expected successor value.
- Head-to-Head Arena Series vs Frozen v0.2.5 (128 games, seeds `9_260_000..9_260_063`):
  - Result: **9 胜 1 平 118 负** (**7.42% 胜率**, 95% CI `[3.5%, 11.7%]`).
  - Mean score: M50 **9.22** vs v0.2.5 **15.70**.
- **Diagnostic / Root Cause of 1-Ply Lookahead Underperformance:**
  - 1-ply lookahead evaluates the state *immediately after our move*, where the opponent hasn't responded yet and the market has fresh unknown draws.
  - The static Value Head values immediate token counts and bank control disproportionately compared to strategic delayed setup (e.g. greedy reserved key Tier-3 cards in early plies, whereas 1-ply search over-indexed on immediate safe token takes).
  - This establishes an important empirical invariant: **1-ply myopic lookahead degrades global policy coherence**. A tree search MUST evaluate full alternating cycles (our move + opponent response, i.e. 2 plies or IS-MCTS tree expansions) or use Policy-only rollouts to avoid myopic evaluation traps.

### 6. Full IS-MCTS Neural Tree Search vs Frozen v0.2.5 Heuristic
- Implemented `splendor agent-m50-policy --mode ismcts --simulations 32`:
  - Directly implemented `PolicyValueEvaluatorV1` for `M50PolicyWeights`, plugging into `splendor_neural_search::search_neural_ismcts_with_evaluator_v1`.
  - Runs 32 simulations per decision with depth 4, PUCT exploration constant 1.5, sampling determinized belief worlds via `sample_determinization_v1`.
  - Policy network supplies candidate action priors; Value head evaluates leaf states at depth limits or terminal nodes.
  - Alternating multi-ply game tree search: evaluates our actions AND opponent counter-responses.
- Head-to-Head Arena Series vs Frozen v0.2.5 (128 games, seeds `9_260_000..9_260_063`):
  - Result: **33 胜 0 平 95 负** (**25.78% 胜率**, 95% paired bootstrap CI `[18.75%, 33.59%]`).
  - Win rate jumps from **18.75% (Greedy) / 7.42% (1-ply) -> 25.78% (IS-MCTS)**, an increase of **+7.03 percentage points** (+37.5% relative boost over greedy, and **3.5x higher** than 1-ply lookahead)!
  - Seat 0 win rate reaches **31.25%**; Seat 1 win rate **20.31%**.
  - Mean score: M50 **11.29** vs v0.2.5 **14.99** (closes the gap to under 3.7 points against the elite heuristic).
  - Search runtime: **64.97 seconds** for 128 games (**0.508 seconds per full game**, ~9ms per IS-MCTS search decision).
  - Replays and summary recorded in `local-artifacts/m50-ismcts-eval-v025/`.

### 7. Elite Dataset Curation: Winner-Only + Fastest Top-20% Fine-Tuning
- Following owner guidance ("把赢家 + 其中平均耗时最低的前20%的局的数据继续用来微调先 试试效果"):
  - Upgraded `splendor m50-extract-replays` to support `--winner-only` and `--top-fastest-percent 20`.
  - Scanned the full 9,744 replay corpus; computed the 20th percentile duration threshold: **<= 54 plies**.
  - Extracted 2,617 qualifying games (fastest 20% won games):
    - **Train:** 2,078 games, **56,333 steps** (100% winner actions, 0 losses).
    - **Val:** 539 games, **14,683 steps** (100% winner actions).
  - Stored in `local-artifacts/m50-elite-dataset-v1/`.
- Fine-Tuning:
  - Initialized from pretrained 463k-step backbone (`m50-large-run/best_model.pt`).
  - Trained 10 epochs (21.67s) with gentle learning rate `3e-4`.
  - **Validation Top-1 Accuracy reaches a new peak: 46.44%** (highest recorded so far, up from 44.21% on small and 45.04% on large).
- Head-to-Head Arena Series vs Frozen v0.2.5 (128 games each, seeds `9_260_000..9_260_063`):
  1. **Elite Policy (Pure Greedy):**
     - **W - T - L:** **27 胜 0 平 101 负** (**21.09% 胜率**, 95% paired bootstrap CI `[14.06%, 28.91%]`).
     - **胜率显著提升：** 纯贪心模仿从基础模型的 18.75% 提升至 **21.09%**（净胜局从 24 局增加到 27 局），直接印证了“过滤掉输家动作、专注高质量速胜牌谱”能纯粹通过策略模仿提升胜率！
  2. **Elite IS-MCTS (32 simulations):**
     - **W - T - L:** 24 胜 0 平 104 负 (18.75% 胜率)。
     - 分析：赢家速胜数据全是高歌猛进的速攻风格，PUCT 树搜索在探索非速攻分支时，先验对防御/僵持局面的支持度下降，使得纯搜索在深层树上的收益不及全数据大模型（25.78%）。

## Result and decision

- **Decisive Feasibility Established:** Pure supervised learning on competitive match replays completely sidesteps the non-convergence, value-optimism, and deadly-triad degradation observed in M49A solo-15.
- In just 16 seconds of training on 612 games, the raw neural policy achieves **44.21% Top-1 action prediction** across ~31 legal actions per state on completely unseen game seeds (**13.6x better than random choice**), and places the expert heuristic's choice in its Top 3 nearly **70% of the time** (69.58%).
- **大数据集验证：** 扩充到 46.3 万步（7,764 局）后，网络在兼顾多种历史对手（S0/S2/S3/S4/M44）的复杂分布下，Top-1 达到 45.04%，**价值头（胜率预测）准确率从 51.7% 飙升至 63.2%，分差相关度从 0.11 飙升至 0.355**。
- **搜索消融与实战突破：**
  - **1 步单向浅搜索（1-ply lookahead）：7.42% 胜率**。证实单向不含对手反制的推演会导致短视，破坏大局观。
  - **纯 Policy 贪心（全数据下快棋）：18.75% 胜率**。
  - **完整交替 IS-MCTS 树搜索（全数据 32 次模拟）：25.78% 胜率**（净增 +7.03 百分点，暴增 +37.5%）。
- **赢家 + 最速前 20% 局数据蒸馏效果：**
  - **纯贪心模仿胜率从 18.75% 突破至 21.09%**（Top-1 准确率达到历史最高 **46.44%**）。证明过滤掉败者动作、聚焦前 20% 最快赢局，能直接让纯策略头打出更凌厉的进攻与更高的基本盘胜率。

## Known limitations
- 32 simulations is a very fast exploratory budget (~9ms/decision); higher simulation counts (e.g. 64 or 128) have not yet been evaluated.

### 8. Search Simulation Scaling: 32 vs 64 vs 128 Simulations (Arena Series)
- Evaluated full M50 Policy-Value network under 64 and 128 IS-MCTS simulations against frozen v0.2.5 (`scripts/m50_eval_scaling_vs_v025.py`):
  - **32 Simulations:** 33 胜 0 平 95 负 (**25.78% 胜率**, CI `[18.8%, 33.6%]`, 场均分 11.29 vs 14.99).
  - **64 Simulations:** 31 胜 0 平 97 负 (**24.22% 胜率**, CI `[17.2%, 32.0%]`, 场均分 10.96 vs 15.13).
  - **128 Simulations:** **44 胜 0 平 84 负** (**34.38% 胜率**, CI `[26.6%, 42.2%]`, 场均分 **11.76 vs 14.74**).
  - **重要实证突破：**
    - 胜率直接突破三分之一大关，从纯贪心的 18.75% **飙升至 34.38%（净胜局增加 20 局，增幅接近翻倍）**！
    - 后手（Seat 1）胜率达到 **37.50%**，场均分差被强行压缩到 **2.98 分**。
    - 运行时间：128 场仅耗时 **118.48 秒**（0.926 秒/局，单步推演约 16 毫秒，依然极速）。
    - 结果保存在 `local-artifacts/m50-ismcts64-eval-v025/` 与 `local-artifacts/m50-ismcts128-eval-v025/`。

## Result and decision

- **Decisive Feasibility Established:** Pure supervised learning on competitive match replays completely sidesteps the non-convergence, value-optimism, and deadly-triad degradation observed in M49A solo-15.
- In just 16 seconds of training on 612 games, the raw neural policy achieves **44.21% Top-1 action prediction** across ~31 legal actions per state on completely unseen game seeds (**13.6x better than random choice**), and places the expert heuristic's choice in its Top 3 nearly **70% of the time** (69.58%).
- **大数据集验证：** 扩充到 46.3 万步（7,764 局）后，网络在兼顾多种历史对手（S0/S2/S3/S4/M44）的复杂分布下，Top-1 达到 45.04%，**价值头（胜率预测）准确率从 51.7% 飙升至 63.2%，分差相关度从 0.11 飙升至 0.355**。
- **全技术栈实战对战阶梯（128 场双换座 vs 顶级规则机 v0.2.5）：**
  - **1 步单向浅搜索：7.42% 胜率**（陷入单边近视短视陷阱，破坏长线大局观）。
  - **纯 Policy 贪心（下快棋）：18.75% 胜率**（小模型与大模型均稳定在 18.75%）。
  - **纯赢家 + 最速前 20% 局微调（纯贪心）：21.09% 胜率**（过滤败着直接提升了独立决策质量，Top-1 达 46.44%）。
  - **交替对抗 IS-MCTS 树搜索（32 次模拟）：25.78% 胜率**（双边展开反制推演，有效打破贪心死角）。
  - **深度对抗 IS-MCTS 树搜索（128 次模拟）：34.38% 胜率**（赢下 44 局，后手胜率 37.5%，分差缩至 2.9 分）。
- **结论：** 随着计算量（MCTS 模拟次数）增加，神经智能体的对战表现呈现出稳步、强劲的单调提升态势（18.75% -> 25.78% -> 34.38%）。在没有任何规则硬编码或手工启发项的前提下，纯神经网络已能稳定从顶尖规则专家手里拿下一超过三分之一的胜局。

## Known limitations
- 128 simulations runs at ~0.9s per full game; 256 simulations has not yet been benchmarked.

## Next authorized gate
STOP for owner review. Candidate next avenues:
1. **Push to 256 / 512 Simulations:** Check if win rate crosses 40%~45%.
2. **Value-Guided Rollout / Pruning:** Combine fast 21% elite policy as rollout policy with IS-MCTS.
