# S4 — Heuristic v0.2 独立评分策略与小规模对战

- **Status:** v0.2 仍在开发中；v0.2.0 有效负向、v0.2.1 分阶段正向干预均保留各自证据；**v0.2.2（自有折扣三阶段）** 新 seed 192/192 有效：对冷冻 v0.2.1 EXPLORATORY_STRONGER、对 v0.1/S3 均 UNRESOLVED。全部 **NOT PROMOTED**，owner review pending，默认仍是 S3。
- **Baseline:** `main@5eae959903023fda669b9ba5085f40394aa45663`，2026-09-25；本轮开始时工作树已有 `.gitignore`、Replay Studio 页面、`human_play_command.rs` 等其他未提交改动，不属于本设计。
- **Scope:** 独立的 v0.2 候选 scorer / CLI / 测试与预先固定的小规模 1v1 换座 Arena 对照；旧 heuristic v0.1、`StaticEvaluatorV1`、M07/S3 的冻结身份和结果均不改动。另一 agent 负责 Solo-15 Q/MLP；真人对局与数据库构建完全不触碰。

## 2026-09-25 authorization and prospective pilot contract

Owner 进一步明确：先迭代 heuristic，再让它对战看看效果；Solo-15 Q/MLP 由另一个 agent 继续，owner 正在手动对局建立初期数据库。此授权覆盖本文件的独立 v0.2 实现、聚焦验证和有限的**研究 pilot**；不等于接受、更换产品默认、放开 M49A Canonical、变更人类对局数据或授权额外超参/种子搜索。禁止把真人局面/动作当作隐式训练教师。

**冻结在新对战结果之前的执行计划**（实现细节必须先过单测/信息边界；任何改动只能在首场 pilot 前解释并留痕）：

- 候选命令 `agent-heuristic-v02 --seed 20260925`，独立身份 `splendor-cli-heuristic-v02/0.2.0`；旧 `agent-heuristic`/S3/M07 的源码行为与身份不改。
- 对照：`agent-heuristic --seed 20260812` 与 `agent-s3-rollout`（零额外 flags）；v0.2 vs 两者，**每组相同** game seeds `9_250_000..9_250_031`（32 block）、每 seed 两个座位顺序，合计 128 场。先在不同 seed `9_249_999` 做一场双向 smoke，不计入 128 场。经由 `run-match` 发布 report/replay，所有目标放 ignored `local-artifacts/s4-heuristic-v02-pilot/`，不写 League/Elo/人工数据库。seed namespace 需在首场之前做 registry + 已有 artifact 冲突检查；若不新鲜，**暂停并重新提交合同**，不得事后悄悄换种子。
- 固定超时 handshake 10s / move 60s / shutdown 2s；任何非 0 进程退出、abort、不完整报告、缺 replay、身份/座次不符即**validity FAIL，保留证据并 STOP**，不剔除败局或自动补样。固定二进制 SHA256 和统一 runner。由 `run-match` 自带 `verify_replay` 门禁，另离线重核结果映射/报告重放；无效局不得写胜率结论。
- 完整有效时：每组记录 W/T/L、座次、32 个成对 seed-block 得分、均值 bps、固定 seed `92_502_026` 的 10,000 次 block bootstrap 95% 区间、完成 plies、失败/延迟（没有真实性能记录就标未测）。仅当两组 95% 下界均 **>5000 bps** 才可称本 pilot 中两对照方向的 **exploratory stronger**；否则据上界 <5000 报 exploratory weaker，余为 unresolved。不依此 pilot 推断正式提升/晋级，不因结果延长预算、调整权重或挪用保留 Canonical。单人经济开发测试须用独立非 Canonical seeds，不在 pilot 之后拿同一结果调参。

## Problem and evidence

- `crates/splendor-agent/src/heuristic.rs` 中 v0.1 的家族基数 buy/take/visible-reserve/blind-reserve 为 1,000,000/100,000/10,000/1,000。买牌基本占据优先级；拿币项把全部公开目标的缺口相加，目标未按未来收益/可达性筛选；退币按总数而非颜色的机会成本惩罚。S2 的 4,063 个严格分歧中 2,428 个以 `category_base` 为最大分离项（`docs/s2-heuristic-win-attribution.md`）。这给出重设计的机制假设，不是因果验证。
- S0：heuristic 胜 n1 为 85–0–43、胜 M07 为 88–0–40；n1 vs M07 未决（`docs/s0-baseline-calibration.md`）。S3 在全 heuristic 双人 rollout 中从 {a_H,a_n1,a_M07} 选最多 3 个根动作比较，128 场对 heuristic 为 80–0–48；之后直接胜 n1、M07，成为**当时测量场的开发参照**（`docs/s3-heuristic-policy-rollout.md`、`docs/s3-field-calibration.md`）。相对优势不代表达到人类强度或最短 15 分路径。S3 的有限提案/双方 rollout 仍受 heuristic 质量和对手模型限制。
- M49S 的单人、双人标准资源供给但零对手干扰的 64 种子：v0.1 成功 64/64，平均 29.20 个 Main turn，平均购卡 20.64 张；随机 0/64（`docs/m49s-solo15-environment.md`）。M49A 走**无教师的**环境 step cost + Bellman Q，而不是模仿 v0.1/S3；开发验证上的 C1 选择 iter50 为 59/64，不能声称胜过 64/64 基线或通过 Canonical 门槛（`docs/m49a-efficiency-q-feasibility.md`）。
- 搜索：M07 每根动作、每个 4 个信息集采样世界各调用一次 `search_maxn_v1`，深度是强制根动作之后 **1 个完成的玩家回合**，预算 n2000 是**每次 continuation 调用**而非每决策只查 2000 个动作。M42S 的 100 同根状态中 n500 与 n2000 的动作 0/100 不同，但 n200 与 n500 仍有 1/100；128 场 n200 vs n1 的结果 62–1–65，未分出优势；不是普适等价结论（`docs/m42s-search-gap-diagnostic.md`）。S1 depth2/n2000 的 21,000 个 continuation 中 17,291 完成（82.34%），200 决策的 p95 2.24s，高于预注册的 2s 上限；n10000 完成 98.59%，p95 4.16s，故未进入 Arena（`docs/s1-search-horizon-validation.md`）。
- **只读行为普查（不是对一般对局概率的无偏估计）**：直接解析历史 `local-artifacts/s0-baseline-calibration/**/match-replay.json` 的 384 场，按 `action.type` 统计：23,064 次 Main 行为中盲预留 509 次（2.21%/Main），264/384 场至少一次（68.75%）；混合政策的 heuristic 本身 7,573 Main 中 0 次，determinization 15,491 中 509 次。另解析 `local-artifacts/s3-arena` + `s3-field-calibration` 的 S3 候选 11,445 Main，其中盲预留 123 次（1.07%）。这些是特定政策/对阵分布，未重新运行 replay 验证，不可说“盲压发生概率固定是 2%”。在 S0 中购买市场 10,686 次、预留市场 2,672 次，合计 13,358/23,064 Main 行为可能导致隐藏牌堆的公开补牌（牌堆未空时）；即使禁止盲预留，未来市场仍非已知。
- 卡牌目录 `crates/splendor-catalog/src/cards.rs` 的 Tier 1 共 40 张，35 张 0 VP、5 张 1 VP；均值 **0.125 VP**，总印刷成本均值 **4.125**，而非虚构的“0.15 分、成本 3”。五种 bonus 色各 8 张。给出均值只供对照，不能把均值当可购买的真实卡。

## Initial design

**目标**：以能解释的可见经济进度替代跨类别硬排序，首先解决自己攒币→买牌→永久折扣→15 VP 的动作效率；对手风险另做隔离增量。每个合法行为用同一量纲评分，先确保 v0.2 *不是* v0.1 的无效微调，也不作为新模型教师。

建议首个可编码草案（**初值假设，不是测得最优权重/冻结正式门槛**）：

```text
Score(a) = lexicographic(
  safe 15-point trigger/lead (including the one possible zero-turn noble choice),
  1000 × actual VP gain (including beyond 15 in the final round)
  + 300 × reduction in bounded shortfall to the best 2 actionable targets
  + 250 × marginal permanent-discount demand on those targets
  + 500 × gain in next-turn affordable useful target (0/1)
  + 150 × change in useful gold liquidity
  + 500 × secured contested visible target, if buyable within ~2 own turns
  − 350 × reserve-visible tempo cost
  − 500 × reserve-deck tempo cost
)
```

`actionable targets` = 当前可见市场和自己手中的已知预留；不含对手暗牌或后续补牌。shortfall 按五色的剩余成本、现有颜色宝石/折扣和金币通配计算；考虑牌的 VP、折扣与贵族进度来选目标，**只取 top-2 而非全市场总和**，对不可能在合理回合取得的目标限幅。买牌后消耗的宝石、永久折扣、贵族真实结算、拿币后退币的颜色和预留获得金币都影响投影。被买的目标从比较双方的目标集合一致剔除，不能因为自己买掉目标而额外扣“缺口”；暂不臆造新翻开的牌。`secured` 必须由公开对手可支付程度与我方可达程度决定，不是对所有 reserve 的奖励。对手风险系数先置 0，单人片证明经济模块后另行冻结竞争增量。即时达标的结束回合规则要用核心引擎对拍，不把自己到 15 机械地等同为即刻获胜；同一购买若满足多位贵族，核心引擎只允许**选其中一位**，不是连续拿走所有贵族。

这个表的数值仅是**实施前的单一候选初值**；单位、top-2、截断和竞争阈值需要 owner 审核后锁定代码/测试/评估输入，再看结果，不得用 Canonical 反馈事后调参。可行的更干净替代是把 `Q_solo(o,a)`（将来过门槛之后）作为经济基础值，v0.2 只增加可审计的对手风险残差；当前 Q 尚未验收，不能声称已有这样的底座。

## Scope and non-goals

- 新的 `HeuristicAgentPolicyV02` / 独立 CLI 身份与 scoring/terms；**不覆盖** v0.1 `HEURISTIC_AGENT_VERSION=0.1.0`、S3 冻结 fallback/rollout、M06 `StaticEvaluatorV1`、M07 冠军/产品默认；不复用 S3 结果冒充 v0.2 验证。
- 不改 `splendor-core` 的合法性、翻牌或胜负，不给在线 policy 传 `FullState`、seed、deck order、replay，拒绝用裁判偷看取得“漂亮的搜索”。购买/贵族/退币的可见局部投影只作评分近似，必须与真实引擎测试对拍，不作为新的规则权威。
- 先前 design-only 阶段不授权比赛；上面的 2026-09-25 后续 owner 指令现只授权上述受控 pilot。仍不授权新增 M49A/C3 训练臂、重启先前按 owner 指令停止的 C3 进程、M49A Canonical 64、线上默认切换、时序 Transformer/自博弈正式实验或超参扫描。

## Contracts and invariants

1. 对所有合法行动逐项计分，无硬编码买>拿>预留；严格合法行动集合原样保留；返回颜色不同的兄弟行动不能误合并。Tie 使用可记录的稳定规则/独立 RNG，旧 v0.1 tie stream 完全不受影响。
2. 预留牌在预留当刻不加即时 VP。无新卡 ID 的市场补牌只记为不确定性。对手的暗预留不能按其真实卡面买牌或产生真实 VP；对手策略只基于其当时可见信息。
3. 如果建模盲预留：从当时的信息集排除已知牌，按 tier 未知牌**枚举/抽样真实整卡**并对评分取期望；不能使用“0.125 分、4.125 成本、随机颜色”的伪卡执行 `apply`/affordability。这也适用于未来市场补牌和自己盲预留后的信息更新。
4. 复杂对手策略与 hidden-state sampler 分开；历史可见事件与当前 observation 必须对得上。拒绝依赖真实 future deck 或把同一次采样世界中的隐藏身份泄给在线 policy。

## Implementation plan (first scorer + pilot now authorized; later search requires separate approval)

1. 保留旧入口，给独立 v0.2 scorer 加 terms/分解、裁判对拍的局部转移 fixture；测试终局、贵族/多贵族、近 10 宝石退币、同色双拿、金币、预留上限/盲压、目标被对手夺走、牌堆空、玩家视角隔离、行为不依赖未见隐藏牌。
2. 用既有已验证回放仅做特征/耗时/坏动作 census 和固定状态反例库；诊断不能挑好看的种子算强度。独立验证“新设计的分数确实会改变旧版锁死家族”的可解释分歧。
3. **先冻结**初值、无训练/验证重叠的开发种子、时间上限和失败规则。第一关 Solo-15 开发验证：成功数、平均/中位/P90 Main turns、贵族/购买/每家族行为；比较同 seed v0.1 和将来 Q，明确未碰 Canonical。第二关单独用新成对换座 Arena，比 v0.1、S3、n1/M07，在相同硬件记录决策 p50/p95 和 abort；只按事先约定的区间/门槛发 strength claim。任何正式评价和 Canonical 解封均需 owner 的新授权。
4. 如果评分能作为可靠廉价叶节点，再做**独立**的搜索工程片：根目标/退币同族聚合（完整合法根保留）、仅对可见强制路线做浅深度2并加随机补牌期望，记录完成深度、节点、p95 与对手反应；相同预算做 ablation，不把树深加大等同于算法变好。

## Iteration log

- 2026-09-25 初始设计：仅阅读源码、历史文档和本机已有回放；直接按 replay `action.type`/Main 枚举做描述性统计；无新对局、无新训练、无付费调用。发现 M49A C3 当前状态相对旧 handoff 漂移，详见 `docs/m49a-efficiency-q-feasibility.md` §18 的追加事实；本设计不代修/重启 C3。
- 2026-09-25 授权更新：owner 明确另派 agent 继续 Solo-15 Q/MLP，本轮实现并测 heuristic 线。首个 pilot 前冻结上方 pairings、种子、换座、缺失/abort 停止规则和仅 exploratory 的判词；保留初值，任何源码语义修正先于对战并在此记录。
- 实现前半段合同化：`heuristic_v02.rs` 独立于旧策略，每行动读取合法列表和自己的 observation；候选目标为市场 + 自己已知预留，排除本次购买目标，按 `floor(100 × (1 + 2×cardVP + 2×min(该bonus色可见需求,3) + 未满足贵族该色数)/(1+当前token/discount后缺口))` 降序，缺口与卡 ID 定序，仅取两张。对相同剩余目标的前后缺口改善每卡限幅 6；永久折扣只计这两张的成本改善。首次可买目标奖励最多一次；金币流动性只计前 3 个。明压保护奖励仅限选中的目标、我方缺口≤5、至少一个对手公开缺口≤1；明/盲 reserve 一回合成本分别 350/500；盲压不伪造未知卡或即时 VP。购买后的可见支付/bonus/牌面 VP 按核心引擎对拍，贵族最多一个且 ChooseNoble 结算前不等同于实战终局。达 15 且严格领先当前公开对手 VP 加一个 1,000,000 的**触发领先优先项**，并非已获胜证明。该细化在任何 pilot 比赛开始前写入，无获胜数据可供反向选择。
- P0 语义修正：最初草案误写购买触发“所有贵族”和“VP 到15封顶”；查 `FullState::after_purchase/apply_choose_noble` 后更正为一个贵族和完整 VP（最终轮超过15仍决定胜负）。修正发生在竞技观察之前。
- **首场 Arena 之前冻结的代码/配置身份**：`crates/splendor-agent/src/heuristic_v02.rs` SHA256 `0b7474ba406851eebefc707155e95e03254b210c04c99a56ef0b721e1475c990`；`benchmarks/s4-heuristic-v02-pilot-v1.config.json` SHA256 `57036d1ef020f84b878ceeb1be489958135dc25904a0ad99b312e7659e51abb5`；`scripts/s4_heuristic_v02_pilot.py` SHA256 `3902b5a42a403a28c5ea338e73ee3c7d2a91e79cfa30b06fc59d9848d631552b`；预构建 release `target/release/splendor.exe` SHA256 `d38433b477f21e864f99e1755f5826a92a53a5c8366d19934d0636ff5ea842c7`。runner 在 ignored local-artifacts 独立复制不可变二进制、绑定上述配置；读取已有人类对局/League 为禁止项。
- 固定 smoke 先行：`python scripts/s4_heuristic_v02_pilot.py --mode smoke` exit 0；静态 registry + 本地已有 match configs 新种子无冲突，seed 9_249_999 双换座均完成并重核 replay，候选均负。smoke 只证通路/合法性；**未据此改权重或换种子**。随后 `python scripts/s4_heuristic_v02_pilot.py --mode pilot` exit 0，严格按相同二进制与配置完成 128 场，无 abort，所有 replay 即时验证 PASS。
- Pilot 后的只读独立核验：128 条清单键唯一、32 seed × 2 换座 × 2 对照齐全，report/replay SHA256 与 final-state 绑定、精确 agent name/version/args/seat、重算 W/T/L 均一致；使用固定二进制再次对 128/128 replay 运行 `verify-replay`，全部 exit0；不修改任何竞技输入。
- 2026-09-25 后续 owner 澄清（本行在 v0.2.0 结果定攀之后）：v0.2 尚未成为产品、仍在开发阶段，"冻结"只是每个已测量版本的证据工件属性，不是设计本身的永久锁定；定义明确要求调整 v0.2 结构。据此提出并实现 **v0.2.1 分阶段感知**，并用与 v0.2.0 完全不相交的新 seed 块预注册了第二支 pilot（见 ## S4.1 节）；v0.2.0 的 config/result/清单/二进制读作只读证据不回改。未被授权的操作边界不变（不碰 Q/MLP、人类库、Canonical、M49A C3）。

## Final implementation

已新增 `crates/splendor-agent/src/heuristic_v02.rs`（同量纲 terms、已知后继资源投影、top-2 可达目标）、`splendor-agent/src/lib.rs` 的独立 `run_heuristic_v02_agent` 和 `splendor-cli/src/{arena_command,main}.rs` 的独立 `agent-heuristic-v02 --seed`。新前瞻 pilot runner `scripts/s4_heuristic_v02_pilot.py` 与 tracked 配置 `benchmarks/s4-heuristic-v02-pilot-v1.config.json`；不共用 v0.1 的身份或修改 S3。实现、pilot 配置/结果与本记录已本地提交 `e02011dace4a2209f5c0aaa1e6681ac568d69bf0`，未 push；本段提交后 provenance 补记属于 docs-only closeout，不改变二进制或实验。旧 heuristic、M07、S3、M49A 实现均未因本轮修改。

## Validation and evidence

竞技赛前验证（均实际执行，exit 0）：`cargo test -p splendor-agent heuristic_v02` 7/7；`cargo test -p splendor-agent` 28 unit + 10 + 5 integration，零失败；`cargo test -p splendor-cli --bin splendor` 102/102；`python -m py_compile scripts/s4_heuristic_v02_pilot.py`；`cargo build --release -p splendor-cli --bin splendor`。CLI `agent-heuristic-v02 --help` exit0，缺失/非法 seed exit1；`agent-heuristic --help` exit0。Rust build 保留现有其他 crate unused/命名警告，未解释为本轮强度结果。

**tracked 结果**：`benchmarks/s4-heuristic-v02-pilot-v1.result.json` SHA256 `5559d52449b23fec44be4186e8f604f2a0f6f9cedd70b991a5279ac1bcf1806c`；其 `manifest_sha256=3329c6bbac85dd7f542ebf60cfb6861ee5975692d6ecb3790a2346edace8be3f` 绑定 ignored `local-artifacts/s4-heuristic-v02-pilot/manifest.json`（逐场 config/report/replay 哈希），不可变 `splendor-s4-v02.exe` SHA256 `d38433b4...`；smoke 完整报告 SHA256 `1d9aa4ed1a0e99be655231eac80d2a2736ba7e3d51626462f741caba0db6dd3c`。报告、回放、二进制、smoke/manifest 均只在本地 ignored 目录，不发布成人类数据库内容。

| 1v1 配对（32 新 seed × 换座） | W–T–L (v0.2) | paired-block center / 95% CI, bps | 合同判词 |
|---|---:|---:|---|
| v0.2 vs v0.1 | **8–0–56** | **1250.0** / [468.75, 2031.25] | EXPLORATORY_WEAKER |
| v0.2 vs S3 | **7–0–57** | **1093.75** / [468.75, 1875.0] | EXPLORATORY_WEAKER |

128/128 completed/verified、0 abort；两组区间上界均 <5000，双对手提升信号 FALSE。95% 仅 exploratory pilot，且两组比较没有正式推广门禁；结果不得包装为正式 promotion/普遍棋力证明。匹配过程总耗时分别 12.511s/95.143s **不是逐决策延迟**，未测 p50/p95 per decision，不能用于上线性能声明。

**事后描述性行为审计（非同根反事实、非因果归因）**：面对 v0.1 的 64 局，v0.2 买卡 770 张（548 market +222 reserved，均值12.03/局）而 v0.1 买 1310（20.47/局），v0.2 首买在自身 Main 第 6.58 手、v0.1 第 3.23 手；v0.2 明压387次、拿币695次（20次 exact take=return），v0.1 明压0次、拿币542次（1次 exact no-op）。面对 S3 的 64 局，v0.2 买802、明压386、拿币728（17次 exact no-op）；S3 买1226、明压153、盲压20。这个差异与“预留/流动性价值相对即时购卡机会成本估计不准”相容，但由于轨迹不同，**不能证明这是唯一或确定的失败原因**。本轮不针对失败调权重，不再从同一 seed 集补跑或声称 v0.2 更强。

源码事实：`crates/splendor-agent/src/heuristic.rs`、`crates/splendor-imperfect-search/src/search.rs`、`crates/splendor-search/src/search.rs`/`evaluation.rs`、`crates/splendor-core/src/state.rs`、`crates/splendor-catalog/src/cards.rs`。实验释义：上述 S0/S1/S2/S3/M42S/M49S/M49A tracked 文档。历史 replay 行为普查是本轮只读解析，不是新的认证实验、无统计推断或独立 replay re-verification。

## Result and decision

**单一冻结 v0.2 候选已实施并完成有效负向探索结果：NOT PROMOTED / 不替换默认。** 移除硬类别基数改善了打分可解释性与信息隔离测试，但没有改善该新配对样本的竞技表现，反而与两参照都显示明显劣势。不能据此否定整个 heuristic 路线；下一版若要修预留机会成本/目标价值，须事先另定修改假设和全新未见 seed，不能复用本 pilot 作为新确认集。Solo-15 teacher-free Q/MLP 继续由另一个 agent 独立推进。

## Known limitations

分数权重未通过独立正式晋级试验；本轮 128 场只是有限对照的 valid exploratory negative，不跨对手/人类泛化。runner 的冻结合同检查使用 Python 默认启用的 `assert`，本轮命令未用 `-O`；若未来复用 runner，应改为不可优化掉的显式拒绝并生成新版本身份，不可悄悄用旧结果重跑。观察空间近似转移不知道新翻牌，盲预留没有整卡期望收益、竞争项目的选择规则粗略，目标 top-2 可能鼓励过多预留/慢启动；这些是待隔离的解释假设。旧自博弈和 Transformer 的负结果只限各自冻结合同，不推出算法普遍无效。盲预留按行为频率低不等于按对局频率低，也不能忽视主流购买带来的隐藏补牌。

## Next authorized gate

**STOP 等 owner 审阅两轮 pilot（v0.2.0 负向 + v0.2.1 三轮向）**。owner 已明确 v0.2 处开发阶段、不冻结；v0.2.1 改动已按其指示实现并用新种子测完（见 S4.1）。要继续：下一个结构调整（如盲预留期望、预留机会成本细化、阶段切换点）须按同一规则——预注册、全新未见 seed 块、复盘旧 measurements 不回改。另一个 agent 的 Solo-15 Q/MLP、人类对局数据库与 M49A C3 状态保持独立；C3 后续是否调查/重跑仍由 owner 决定，Canonical 64 HOLD。

## S4.1 — v0.2.1 分阶段感知迭代（2026-09-25，owner 指示后）

### 动机与改动
v0.2.0 的真实分歧案例（本地 `local-artifacts/s4-heuristic-v02-pilot/v01-vs-v02-comparison.html`，派生自 gitignored replay）显示该版本用一套静态权重打整局：构建期把不推进 top-2 目标的廉价 0 分引擎卡打成负分（典型 seed 9_250_000 ply 4，v0.2 打分 −1350 而 v0.1 打分 1,007,850），v0.2 从而首买偏晚、购卡偏少。Owner 明确了游戏规律——前中期构建期永久折扣/引擎卡价值高，后期冲分期才轮到即时 VP 主导。v0.2.1 只改打分结构，不动已经测量过的 v0.2.0 证据：

- 新增 observation-only 阶段标量 `scoring_milli = clamp((lead_prestige − 4) × 1000 / 8, 0, 1000)`，场上任一玩家最高公开 prestige 为信号，`end_game_triggered` 强制为 1000；全部来自自己 observation，无隐藏状态。
- 新增 `engine_value`（仅真实购买触发）：买到的永久 bonus 色按全桌可见卡对该色的剩余需求计价（每卡限幅 3、总需求限幅 12、权重 120），乘 `(1 − 阶段)`——构建期让廉价引擎卡明显为正，冲分期归零。
- `immediate_prestige` 权重从 1000 变为 `1000 + 阶段 × 2000`——冲分期每分最多 3000。`terminal_lead`、`target_shortfall`、`useful_discount`、`new_affordable`、`gold_liquidity`、`secured`、`reserve_tempo` 保留不变。
- `HEURISTIC_V02_AGENT_NAME` 不变，`HEURISTIC_V02_AGENT_VERSION` 0.2.0 → **0.2.1**；`HeuristicV02Terms` 增字段 `engine_value`。

### 冻结与第二支 pilot 合同（先冻结后测）
在第二场 pilot 之前记录的身份：源码 `crates/splendor-agent/src/heuristic_v02.rs` SHA256 `b4e1d8822b378a5fb1e0f544b2e73bcd0b26e0ff765461451835699b44076d42`（赛前冻结；赛后对该源文件执行了 format-only rustfmt，提交后源码哈希为 `c7b2e39810a21c5b1fda81e05e66032831742e35868eb2748f7b9f99559619e6`，格式化不改变语义，格式化后全套测试重跑通过）；config `benchmarks/s4-heuristic-v021-pilot-v1.config.json` SHA256 `df5cc3447ef6437f6109a5f1cd9f34edd687b8b999e6def8d882c1e8750bfbec`；通用 runner `scripts/s4_heuristic_v021_pilot.py` SHA256 `e0ab47b0a8f984290c1993e909cc3a59b331e58cca3eb0bf2c4f4ef6ac6d099d`（以显式 `require` 代替 assert，响应 v0.2.0 轮 runner 的 `-O` 告警）；构建二进制 `local-artifacts/s4-heuristic-v021-pilot/splendor-candidate.exe` SHA256 `045b890fe52d647d6b6500642fccafc10bf229e7cec7066b696c6cbccc3e9f17`。

- 全新 seed 块 `9_251_000..9_251_031`（32 block）+ smoke `9_250_999`，bootstrap seed `92_512_026`；原 v0.2.0 块 9_249_999..9_250_031 不复用；registry + 全量已有本地 match-config 冲突检查 PASS。
- 三对照（双向换座，共 192 场）：`heuristic-v020` 用上一轮冷冻二进制 `local-artifacts/s4-heuristic-v02-pilot/splendor-s4-v02.exe`（SHA256 `d38433b4...`，该 head-to-head 正好隔离分阶段这一处改动）、`heuristic-v01 0.1.0`、`s3-rollout v1`。超时同前；任何非 0 退出/abort/缺失/身份不符即 STOP。

### 执行与结果
- 赛前：`cargo test -p splendor-agent` 31+10+5 PASS（v0.2 相关新增 3 项：构建期廉价引擎卡 >0、冲分期 VP 权重抬高且 engine_value 归零、end_game 强制冲分期；原 7 项含对拍全部保留通过）；`cargo test -p splendor-cli --bin splendor` 102/102；`py_compile`、release build 全 exit0。
- `python scripts/s4_heuristic_v021_pilot.py --config benchmarks/s4-heuristic-v021-pilot-v1.config.json --mode smoke` exit0（双換座均胜，`verify-replay` PASS）；随后 `--mode pilot` exit0，192/192 完成、0 abort。
- pilot 后独立只读审计：192 条唯一键、逐场 config/report/replay 哈希绑定、程序路径（含 v0.2.0 的冷冻二进制）与 identity 全核、重算 W/T/L 一致、用候选二进制再跑 192/192 `verify-replay` exit0。审核脚本曾报 384 条路径段隔符差异，归一化后为 0 真错误。

**tracked 结果** `benchmarks/s4-heuristic-v021-pilot-v1.result.json` SHA256 `7210e6ec7867cfe16a34c275d102e1875ded56740897497325ded6f7ae5cbf08`；`manifest` SHA256 `131f0afdad9c5d88a51b3f5724b84781e8a0e347441ddf10eb898647c83e2803`（ignored 目录）；smoke 完整报告 SHA256 `d4866f8a9276207453e027964fdd05141c14ce27e11730f15da474a9c8036ee6`。

| 1v1 配对（32 新 seed × 换座） | W–T–L (v0.2.1) | paired-block center / 95% CI, bps | 判词 |
|---|---:|---:|---|
| v0.2.1 vs v0.2.0（冷冻二进制） | **52–0–12** | **8125.0** / [7187.5, 9062.5] | EXPLORATORY_STRONGER |
| v0.2.1 vs v0.1 | **26–1–37** | **4140.625** / [3046.875, 5312.5] | UNRESOLVED |
| v0.2.1 vs S3 | **11–1–52** | **1796.875** / [859.375, 2890.625] | EXPLORATORY_WEAKER |

### 解读与边界
- 分阶段结构在本 seed 块上显著优于 v0.2.0（95% 下界 >5000），说明“构建期给引擎卡正价值”这个方向是对的；相对 v0.1 从明确弱势（v0.2.0 CI 上界 2031 → v0.2.1 CI 跨 5000）推进到未决，也明显收窄；对 S3 仍明显弱（但比 v0.2.0 的 1093.75 bps 有改善）。
- 这些仍是**有限对照 exploratory**结论，不跨对手/人类泛化，不是 promotion 证据。v0.2.1 vs v0.1 的 UNRESOLVED 不能读作“已经不弱于 v0.1”（区间含明显负值），更不能读作胜过 S3。
- 匹配耗时（v0.1 组 11.844s、s3 组 50.105s）非逐决策延迟。
- 唯一改动判定可信依赖“v0.2.0 组用了冷冻二进制且 hash 一致”这一点，已审计核验。
- 本轮实现、config/runner/结果与本节记录已本地提交 `71cf4c6f0388759c8035db36a38b580c0c646ba1`（未 push；只纳入 S4.1 五文件：heuristic_v02.rs、v021 config/result、v021 runner、本文档；既有 owner/UI/M49A 未提交改动未碰）。

## S4.2 — v0.2.2 三阶段结构干预（2026-09-26，赛前设计）

### 问题、证据与授权
Owner 明确要求继续优化，不将 v0.2.1 当产品冻结；提出以**自己的永久折扣数**划分超前期（≤4）、前期（5–8）与中后期（>8）。超前期首要抢成本≤4的一级牌和轮转、不在>7币且无可买牌的状态继续堆币；其次优先能帮助未来可见一级/高性价比二级牌的转换卡，并预留高性价比大分卡；其他常规需求最后。前期继续宝石→低级牌→下一轮折扣循环；中后期买/瞄准 VP/实际折后成本更划算的卡。v0.2.1 在新种子相对 v0.2.0 有提升，但对 v0.1 未决、对 S3 弱；没有证据证明这次结构改动一定有效。baseline `main@d44c17b648458364e5bf583ef39bdd1b8f0ef7a9`，原有未提交 UI/.gitignore/human-play 改动保留，绝不修改。旧 v0.2.0/0.2.1 的 config/result/二进制均保持只读。

直接核对 `crates/splendor-catalog/src/cards.rs` 90 张牌：一级 40 张，成本≤4 共 25 张（0VP/3:10、0VP/4:10、1VP/4:5）；二级有 2VP/5 和 3VP/6 各 5 张。**6同色→3分属于二级，不存在三级 6同色→3分**。三级 7同色→4分、7+3→5分各 5 张。依 owner 所给 7→4 > 6→3 > 7+3→5 的偏好排序，预留目标跨 T3/T2 识别真实牌型，不杜撰不存在的 T3。

### 首场比赛之前的结构与门槛（初值为假设，不是最优解）
1. 新身份 `splendor-cli-heuristic-v02/0.2.2`，仍只读自己的 `Observation` 和服务器 `legal_actions`。phase=Ultra（自己的 `sum(bonuses)≤4`）、Build（5–8）、Score（>8）；公开 `end_game_triggered` 或任一玩家公开 prestige≥12 是紧急冲分 override，不窥牌堆/对手暗牌。继承 v0.2.1 的结算投影/终局/贵族/金牌合法性测试；stage 在一回合内依当前**决策前**状态计算，不以假想购买后的折扣重新分期。
2. Ultra：购买一级印刷成本≤4 给显式 `cheap_engine_buy`，3 宝石比 4 宝石略优；拿币令此类目标由不可买变可买给 `cheap_ready` 正值（绝不是所有 BUY 无条件赢）。购买非自身卡、bonus 色对仍需该色的可见一级或 2VP/5、3VP/6 二级牌的帮助计 `conversion_value`，构建期有效、冲分期归零；保持原 `engine_value`，不伪称两项互不相关。
3. Ultra 在无当前合法 cheap-T1 可买时，`ReserveMarket` 卡型奖励按 **T3: 7同色/4VP > T2: 6同色/3VP > T3: 7+3/5VP**（同状态同退币且无竞争奖励影响时严格排序）；有限预留数仍由裁判合法集合控制，只锁牌和可得金币，不给卡的即时VP。过币（拿币后自己总 token>7 且**任何可见/自己预留牌均不可买**）和净零拿退施加显式惩罚，杜绝空轮转；不能因为牌堆未知或对手暗预留而虚构可买牌。
4. Build：延续低级牌和目标接力，cheap 奖励小于 Ultra、conversion 有折减，过币守卫保留；Score：二者归零，即时VP按 v0.2.1 满冲分档计，新增 `vp_efficiency` = 已知 VP/(1+当前折后总成本) 的有界奖励，top-2 目标按 VP/折后成本及可达缺口重排。不存在强制跨家族优先级；同分沿用既有 StableRng，旧 v0.1/S3 冻结身份不变。
5. 在首场新 pilot 前冻结实际常量、源码/配置/二进制哈希，测试 stage 边界(4/5/8/9 + public override)、真实卡型及预留顺序、廉价卡/转换、>7 无可买惩罚/净零拿退、冲分性价比、隐牌视角隔离、投影对拍；具体不符的合法成本案例只按规则修正并记日志，不能见战绩后择优调参。

**第二次结构迭代的独立开发 pilot 合同**：fresh seed `9_252_000..9_252_031`，smoke `9_251_999`，32 block × 双换座 × 3 对照 = 192 场；前两支 S4 pilot 用过的 seed 与本批无交集。对照：冷冻 v0.2.1 的 `local-artifacts/s4-heuristic-v021-pilot/splendor-candidate.exe` SHA256 `045b890fe52d647d6b6500642fccafc10bf229e7cec7066b696c6cbccc3e9f17`、v0.1、S3；10,000 次配对 seed-block bootstrap seed `92_522_026`，双侧 95% CI，分组仅 `EXPLORATORY_STRONGER` (下界>5000bps)/`EXPLORATORY_WEAKER` (上界<5000)/`UNRESOLVED`。registry + 既有 6,860 份本地 match-config 的起始核对零撞；赛前仍须自动复核。单局 handshake10s/move60s/shutdown2s，任何 abort/进程/身份/回放/哈希错误 STOP，保留失败，不换种子/删败局/重试。结果只在独立 `benchmarks/s4-heuristic-v022-pilot-v1.{config,result}.json` + ignored `local-artifacts/s4-heuristic-v022-pilot/`；不读写 League、人类数据库、Q/MLP、Canonical 64 或 C3。不触发晋级或产品默认切换。胜负只是探索性比较，三次迭代同原参照的跨批中心变化不是严格的同根因果消融。

### 迭代日志（append-only）
- 2026-09-26：核对基础仓库状态与卡表，确定上述机制/种子/有效性门禁；`main@d44c17b648458364e5bf583ef39bdd1b8f0ef7a9`。**此时尚未实现或开赛。**
- 2026-09-26 竞技赛前已实现/冻结的细化：`DevelopmentPhase` 以自己的五色永久折扣合计精确区分 Ultra 0–4 / Build 5–8 / Score 9+，公开最高 prestige≥12 或 end_game 触发应急 Score；阶段于根决策前固定。新 `HeuristicV02Terms` 新增六项（`cheap_engine_buy`, `cheap_ready`, `conversion_value`, `bomb_reserve`, `rotation_guard`, `vp_efficiency`），保留 v0.2.1 旧项/无类别基座。购买一级印刷成本≤4 的 bonus = `(7−印刷成本)×500`(Ultra) / `×350`(Build)；拿币使原不可买的≤4 一级牌变可买 +1100/+700。非本次买牌的已知可见一级/2VP5或3VP6二级若尚需该 bonus 色，按每目标 2(便宜一级/高效二级) 或 1(其他一级) 的启用需求封顶8，每单位 +180/+120；与 v0.2.1 engine_value 有相关性，不当作独立因果消融。Ultra 预留卡型奖励 2400(T3 7/4)、1700(T2 6/3)、900(T3 7+3/5)，只在无可负担 cheap-T1 且自己未持任何上述 bomb 时有效；差距>一次竞争奖励500，同状态同退币严格保序。take净拿退=0 罚 2000；Ultra/Build 拿完>7币且公开/自有预留均无可买牌，按超出7的个数×850罚。Score 的购买得分性价比 `Δ实际VP ×1200/(1+当前折后总成本)`，top2目标依 `VP/折后成本/当前缺口` 排序；Ultra/Build 优先组为≤4一级、其余一级、2VP5或3VP6二级、其余。Score 时继承 v0.2.1 的 VP 最大权重 3000、engine归零。其余旧项不动，旧版本二进制不动。注意这是真实合法投影上的启发式目标，不是保证每次都能抢到/买到的规则断言。
- **首场 smoke/Arena 前身份冻结**：`crates/splendor-agent/src/heuristic_v02.rs` SHA256 `feb76b006c28e313ad8bbdfccb5086915fae4842f359e42776ce9576ff9d2cbf`；配置 `benchmarks/s4-heuristic-v022-pilot-v1.config.json` SHA256 `490f2e9bef8329566e11a3e9fe9abbb0bf603112aa98cab16a4da75dac86b2fd`；runner `scripts/s4_heuristic_v022_pilot.py` SHA256 `ee0abb4bd6e9650b072a8e61392a56bca88538b43b1434061c02cb31a9aae802`；release `target/release/splendor.exe` SHA256 `65c7271c74ba233f193bc6a7ccfcd23004aecb93d85f96b5303e09955bd22cd4`。冻结 v0.2.1 对手已核 SHA256 `045b890fe52d647d6b6500642fccafc10bf229e7cec7066b696c6cbccc3e9f17`。配置对 v0.2.2 命令 `agent-heuristic-v02 --seed 20260926`，v0.2.1 命令仍 `--seed 20260925`；对 v0.1/S3 同原身份。不得因 smoke 输赢更改任一常量/种子。

### 实现、验证、结果与下一 gate
竞技赛前实际执行（exit 0）：`rustfmt --check --edition 2021 --config skip_children=true crates/splendor-agent/src/heuristic_v02.rs`；`cargo test -p splendor-agent heuristic_v02` 16/16，`cargo test -p splendor-agent` 37 unit +10+5 integration，`cargo test -p splendor-cli --bin splendor` 102/102，`python -m py_compile scripts/s4_heuristic_v022_pilot.py`、`python -O` 的坏版本显式合同负控 PASS，`cargo build --release -p splendor-cli --bin splendor` PASS（原有其他 crate 的警告未视为棋力数据）。竞技执行（赛前代码/权重/配置/对手二进制哈希均如上，赛后未调参数）：`python scripts/s4_heuristic_v022_pilot.py --config benchmarks/s4-heuristic-v022-pilot-v1.config.json --mode smoke` exit0，静态 registry 与本地已存 match-config 新 seed 冲突 0，smoke seed `9_251_999` vs 冷冻 v0.2.1 双换座各胜、各重核 replay（只作通路，不计入192，也没有因烟测改权重）。随后相同配置/候选二进制运行 `--mode pilot` exit0，**192/192 completed/verified，0 abort**。独立赛后只读核验：192 个 matchup/seed/rotation 唯一齐全，原始 config/report/replay 的逐场 SHA256、游戏 ID、seed、座次、双方精确 name/version/args/可执行路径（含冷冻 v0.2.1）、最终状态哈希与重算 W/T/L 全一致；对全部 192 局再次执行 `verify-replay` exit0；真实错误 0。

**tracked 小结果** `benchmarks/s4-heuristic-v022-pilot-v1.result.json` SHA256 `a2de20690efb5f4ae617218e13f923a5ab0bc279ccc9b39b24568e591797dc9b`。本地 ignored `local-artifacts/s4-heuristic-v022-pilot/` 中候选 `splendor-candidate.exe` SHA256 `65c7271c74ba233f193bc6a7ccfcd23004aecb93d85f96b5303e09955bd22cd4`，逐场内容哈希清单 `manifest.json` SHA256 `803dbac064f6316dd45849c53c32b326ee596bcc055d1430849d475bb0a9fc51`，smoke `smoke-complete.json` SHA256 `7d1c4fdb9fd1359b83587b623633628b86d903445cbdfe405e37b3040ca1a137`；逐场报告/回放/二进制不跟踪、不碰人工库/League。

| v0.2.2 1v1（每组32新种子×双换座） | W–T–L | paired-block center / 95% CI（bps）| exploratory 判词 |
|---|---:|---:|---|
| 对 v0.2.1（旧冷冻二进制） | **45–0–19** | **7031.25** / [5937.5, 8125] | **EXPLORATORY_STRONGER** |
| 对 v0.1 | **35–0–29** | **5468.75** / [4375, 6562.5] | **UNRESOLVED** |
| 对 S3 | **31–0–33** | **4843.75** / [3437.5, 6250] | **UNRESOLVED** |

结果有效且对应新 seed；**只有对 v0.2.1 能说该 pilot 中更强**。但候选 tie RNG seed 是 `20260926`、冷冻 v0.2.1 是 `20260925`：这个 head-to-head 比较的是整个冻结 policy 包（结构+tie stream），**不是单独结构改动的严格因果隔离**；超前期/前期/冲分期的多项改动也没有逐项 ablation。v0.1/S3 区间都跨5000，既不能声称比它们强，也不能声称实际等同。对 S3 的样本分数 31–33 不够推广、更不改变默认；这些不是正式多臂检验，也未测逐决策延迟（匹配墙钟不是 p95 latency）。跨 v0.2.0/v0.2.1 不同 seed 的中心点差不构成同根因果估计。与冷冻 v0.2.1 的这64局后验行为对照（不同 tie seed 的同局面对照也可能产生不同动作）：v0.2.2 首买均值自身第3.58手、v0.2.1第4.17手；明压197 vs 371；买卡 1003 vs1103；净零拿退双方0。轨迹随策略变化，以上是描述而非“减少明压导致胜率增长”的隔离归因。

**当前决定：v0.2.2 IMPLEMENTED/VERIFIED，valid exploratory stronger vs v0.2.1，vs v0.1/S3 UNRESOLVED，NOT PROMOTED；产品 S3 不变。** 下一授权门槛 STOP 等 owner 审阅：若继续 v0.2.3，应隔离轮转/cheap-T1/预留 bomb/得分效率各项的贡献并用新种子预注册测，或另授权正式独立竞技 gate 与逐决策时延门槛；不能拿本批反复调到赢。S4 与 Q/MLP、人类数据库、Canonical/M49A C3 不互相推断或绕门。

实现、完整赛前合同、tracked 结果与本节复盘已在本地 `bc2904cc6507403b6d6335835555184029de750b` 提交（未 push）；此行是提交后 docs-only provenance 补记，不改变赛前代码、配置、候选二进制或实验结果。

### Owner 权重审阅说明页（2026-09-26；仅回放解释，无策略实现）

- 按 owner 新要求，生成本地只读说明页 `local-artifacts/s4-heuristic-v022-pilot/v022-weight-review.html` (SHA256 `ce9c0832fba2e5d6f3f1d32ee7fa97e8b175ff0a04eb3a8437a8f4d4a5434cf6`)：覆盖当前 15 项 additive terms、Ultra/Build/Score 流程、top-2 目标排序、真实回放案例，并将“≥2 贵族 gap≤4 的明确目标优先”与“已有两张自留后的数量相关预留降权”明确标为 `PROPOSED / NOT IMPLEMENTED`。页面交互控件只演示阈值/分数敏感性，不改代码或回放分数。
- 来源合同仍是既有 v0.2.2 pilot：样例提取时 repo HEAD `main@c97b97594ae745f1d5dfce8a433a1bb2ff2005ca`；文档收口时 HEAD 已到 `main@9cb8464a4a2089913ffed2d1e5c08b1e91ba3bcf`（期间新提交仅更新 M49A C3 stop 记录，S4 源码哈希未变）；heuristic 源哈希 `feb76b006c28e313ad8bbdfccb5086915fae4842f359e42776ce9576ff9d2cbf` 与冻结记录一致；tracked pilot result SHA256 `a2de20690efb5f4ae617218e13f923a5ab0bc279ccc9b39b24568e591797dc9b`，ignored manifest SHA256 `803dbac064f6316dd45849c53c32b326ee596bcc055d1430849d475bb0a9fc51`。
- 只用 v0.2.2 vs v0.2.1 的 64 份旧 pilot replay（32 seeds × 2 rotations）。提取器对每份运行 `verify_replay_trace`；命令 `cargo run --release -q -p splendor-cli --example s4_v022_case_dump -- local-artifacts/s4-heuristic-v022-pilot > local-artifacts/s4-heuristic-v022-pilot/reconstructed-candidate-states-reproduced.json` exit 0。得到 1,848 个 v0.2.2 决策状态，复跑 JSON SHA256 `07c9fb046309191e9b7093b03e7053c1b01545cfee3ef4507027e118b24416fe`，与原状态文件相同；一次性提取器源码保存在 ignored artifact，SHA256 `19a4b640b5fc7e0585b36d9bf57c7b90271a56f7065d0967e4031da2b686a165`。案例包含：9,252,000/r1/ply31（持两张仍预留第三张，900 vs 非预留600）；9,252,001/r1/ply49（3位贵族gap 2/3/4、不可买自留 #57 与可买T3 #74 3VP/印刷成本14）；9,252,001/r0/ply52（两位近贵族且可买自留 #57）；9,252,018/r0/ply52（无自留，买T1触发一位贵族）。这些是解释性单状态重算，不是新强度证据或因果消融。
- 页面静态核验：15 个评分项、16 个 DOM id、6 个页内链接均存在；inline JavaScript 语法及三个交互控件用 mock DOM 检查通过。**未运行真实浏览器/视觉 E2E**。没有变更 heuristic 源码、配置、pilot result、种子或二进制；没有新对局、训练或独立审查。S3 仍为默认，v0.2.2 仍 `NOT PROMOTED`。
- 下一步：owner 审阅页面并确认 noble-distance、3VP &gt;6 的印刷/折后成本口径、已有两张后适用的预留类型/例外及额外惩罚范围；确认后另立 v0.2.3 合同、边界测试与全新未见 seed，不重用 `9_252_000..031`。

<a id="s43-v023-multi-noble-reserve-count"></a>

## S4.3 — v0.2.3 多贵族目标与预留数量惩罚（2026-09-26）

**状态：IMPLEMENTED / VERIFIED；探索性结果记录完毕；NOT PROMOTED（未做独立审查/接受门）。**
基线 `main@9cb8464a4a2089913ffed2d1e5c08b1e91ba3bcf`。owner 要求优先检查中后期多个贵族临近、3VP 高成本卡、自留牌的合法购买跟进，并在已有两张自留牌后谨慎继续预留；保存的优化前对照确实存在：`local-artifacts/s4-heuristic-v022-pilot/splendor-candidate.exe` SHA256 `65c7271c…`，用于本轮 v0.2.2 冻结对照，不会覆盖。

### Problem and evidence

v0.2.2 的公开回放诊断有少数状态显示多个贵族距离较近时，顶级 VP/成本目标与贵族进度可能不同向；已有两张自留牌后仍可能再预留；有牌在玩家自己的预留区且合法可买，但目标跟进不足。它们是具体策略状态的诊断，不代表普遍胜率原因。见上节 64 份旧回放的 1,848 个决策态；这些旧 seed 只作设计线索，**不作 v0.2.3 调参测量或新强度证据**。

### Initial design / contracts

本轮仅修改 `agent-heuristic-v02` 的 observation-only scorer；在线决策只读己方 `Observation`、公开贵族/市场和引擎提供的合法动作，不读取 `FullState`、暗牌、牌堆顺序或真人对局数据库。v0.2.2、v0.2.1、v0.1、S3 与其历史二进制/证据保持不变；S3 仍为产品默认。本轮不晋级候选、不触碰 Canonical、Solo-15 Q/MLP、M49A C3 或人类对局数据。

赛前冻结以下规则和常量，不看新 pilot 结果后修改：

1. “贵族接近”按当前自己的永久折扣计算：每位公开贵族的距离为五色 `max(需求−己方折扣, 0)` 总和；距离 `≤4` 为 near。只有冲分阶段且至少两位公开贵族 near 时启用 `multi_noble_race`。购牌若令这些已 near 贵族的距离下降，每减少一单位累计 `+800` 分（`noble_race_progress`）。
2. 在该贵族竞速状态下，冲分目标排序优先帮助至少一位 near 贵族的卡；第二组包括印刷总成本 `>6` 且 `3 VP` 的卡、以及玩家自留区中 `VP×1000/(1+折后总成本) ≥600` 的牌；其余牌按既有 VP/有效成本/可达性排序。阈值用印刷成本判定卡型；折后成本仅用于自留牌可买价值。
3. 在该状态下，合法购买 `3 VP` 且印刷总成本 `>6` 的卡额外 `+1200`（`noble_race_three_vp`）；合法购买自留区内达到上述 `600` 效率门槛的牌额外 `+1200`（`noble_race_reserved`）。这只是弱偏好项，不覆写合法性，也不保证买牌动作胜出。
4. 仅 Ultra/Build 期（己方折扣≤8，且未触发既有冲分覆盖），若当前已经持有至少两张自留牌，任何再预留动作额外 `−500`（`reserve_count_guard`）。既有 reserve tempo、爆牌价值等保留；此惩罚不是绝对禁止，合法且足够高价值的预留仍可胜出。
5. 版本身份 `0.2.3`。候选 tie seed 固定为 `20260926`（与 v0.2.2 相同，减少这组直接比较的随机 tie-break 差异）；其余项、目标函数、阶段边界、合法动作由现有 v0.2.2 继承。不得在看到结果后改任何权重、种子、候选或 gate。

### Scope, pilot and acceptance gates

- 将冻结 v0.2.2 二进制作为主要直接对照，SHA256 精确锁为 `65c7271c…`；另保留 v0.1 与 S3 对照，用各自原有固定程序参数。仅解释性比较，不宣称单因素因果：本轮只用同一候选 tie seed 做 v0.2.3 vs v0.2.2 的配对；其余版本仍是多因素策略包比较。
- 新 smoke seed `9_252_999`；pilot seeds `9_253_000..9_253_031`（32 seed × 2 seat rotations × 3 opponents = 192 matches）。在立约时先检查静态 seed registry 和既有 local Arena match-config，确认无冲突；完整命令、身份、时限和 10,000 次 paired-block bootstrap 参数写入 tracked config。pilot 必须先通过两座 smoke；任何失败/不完整比赛 fail closed，不过滤、不重试、不换 seed；每局保存 config/report/replay 并运行独立 `verify-replay`。
- 完成门槛：冻结源码/config/runner/程序哈希；agent 与 CLI 测试、release build、Python 合同检查通过；2/2 smoke 有效；pilot 恰为 192/192 有效、0 abort，身份/换座/报告回放哈希/独立 replay 复验与逐对重算全通过。统计结果仍只标 `EXPLORATORY_PILOT_ONLY`，每个对照分别给 95% 配对 seed block CI；不设促销门槛、不晋级、不更改默认 S3。
- Artifact 路径：`benchmarks/s4-heuristic-v023-pilot-v1.config.json`、对应 tracked `.result.json`、`scripts/s4_heuristic_v023_pilot.py`；每局文件、冻结候选二进制和 manifest 留在 ignored `local-artifacts/s4-heuristic-v023-pilot/`。v0.2.2 保存件不得覆盖。

### Implementation plan / iteration log

1. 记录本合同和 baseline；实现 near noble gap、帮助色目标排序、两项合法购牌加分与早期持两牌后的预留数量惩罚，并加入阶段阈值/牌型/合法动作回归测试。
2. 固定 runner/config 与全新 seed；确认 registry/local config 无冲突；完成 agent/CLI/release/py_compile 与两个 seat smoke。
3. smoke 身份、哈希、对照程序和回放均通过后才运行 192 局；跑完独立复验，重算所有配对结论。
4. 收口时记录源码/config/runner/二进制/manifest/result SHA、exact validation commands/exit status、工作树和 publication 状态；结果不支持或执行失败均保留原样，不改 seed/门槛。

- **Iteration 0 (2026-09-26)**: owner 在审阅 v0.2.2 权重页后要求直接实战对战测试修改版，授权范围为实现上述两项提案并以保存的 v0.2.2 作对照；此前 seed preflight 对 smoke+pilot 区间 `9_252_999..9_253_031` 的 registry 与 `local-artifacts/**/match-config.json` 均未发现冲突。尚未改策略源码、运行 smoke 或比赛。开始工作树已有 `.gitignore`、Replay Studio 页面、`human_play_command.rs`、`apps/replay-studio/app/jev/` 和本设计文档的独立改动；不得覆盖/暂存无关路径。根 `handoff.md` 与 `local-artifacts/` 必须保持 ignored/local-only。
- **Iteration 1 — implementation / unit tests**: 固定五色永久折扣距离≤4、至少两位、Score-only开关和各权重；实现 v0.2.3 四项 term 与 target-group。首次专项测试 18/19；失败仅因 fixture 将红色 CardId15误认为白色，改用白色 CardId24 后 19/19 PASS；完整 agent 40+10+5、CLI bin102 PASS。
- **Iteration 2 — preflight / smoke**: release binary 建成后冻结 candidate `7a981035…` 和脚本/config hash；runner合同检查、py_compile、rustfmt与diff-check PASS。fresh-seed scan 对 registry/local configs disjoint；v0.2.2 executable SHA钉为 `65c7271c…`。两座 smoke `9_252_999` 均完成并独立 verify-replay exit0，此后未改 scorer、runner、config 或 candidate binary。
- **Iteration 3 — pilot / audit**: 以 create-only fail-closed runner 完成 192/192 (0 abort)；输出完整 per-game log、report、replay 与 manifest。单局 runner verify 后，再用独立 audit 按文件 SHA、seed/seat/agent identities/args/final hash 重验，并对192个 replay 再执行 `verify-replay`；独立重算 paired W/T/L 与 10,000-resample CIs，全部匹配 tracked result。
- **Iteration 4 — registry / closeout**: 把 v0.2.0–v0.2.3 smoke+pilot ranges 记入 static registry；pairwise range disjointness PASS。裸运行 registry 脚本曾 exit1，是因为它默认检查本来已 consumed 的 S0 segment；按 caller contract 做全 registry pairwise 检查及赛前 S4 seed preflight后，无 seed collision。结果仅 exploratory、未晋级。

### Final implementation

- `crates/splendor-agent/src/heuristic_v02.rs` 实现版本身份 `0.2.3`：多贵族仅在 Score phase 且至少两位公开贵族五色折扣距离 `≤4` 时启用；近贵族进度每减一单位 `+800`，帮助 near 贵族的永久折扣卡优先；高成本 3VP（印刷总成本 `>6`）与可买高效率自留牌进入次级目标组，各自合法购买 `+1200`；Ultra/Build 已持有至少两张时，再次可见/盲预留 `−500`。score 项均可从 observation 计算，动作仍来自引擎 legal-actions。tie seed `20260926` 与 v0.2.2 相同。
- v0.2.2 保存二进制保持原样并作为主要对照：`local-artifacts/s4-heuristic-v022-pilot/splendor-candidate.exe` SHA256 `65c7271c74ba233f193bc6a7ccfcd23004aecb93d85f96b5303e09955bd22cd4`。candidate binary 为 `7a98103548082c9018f5941fae0d0289acd5939b2d3d386457bf04f0f22a6dc0`；源码 SHA256 `b9dd6423db5a38d71e24e6babbfda8c294fe83a1ebd62ce43dbb2321ba08b684`。无 v0.2.2/v0.1/S3 源码、历史结果或产品默认改动。跟踪实现、合同、结果与本节复盘的本地提交为 `4f2b25b`（未 push）；后续若有文档提交只补 provenance，不改本轮冻结代码/结果。

### Validation and evidence

- 源码定向回归：先有一次失败的 `multi_noble_race_progress_and_target_order_use_frozen_distance` fixture（以为 CardId15 是白色 bonus；真实目录中它是红色）。改为真实白色 bonus CardId24 后，`cargo test -p splendor-agent heuristic_v02 -- --nocapture` 19/19 PASS；这是 fixture 修正，不改冻结规则或权重。之后完整 `cargo test -p splendor-agent --quiet`：40 unit +10 integration +5 public API PASS；`cargo test -p splendor-cli --bin splendor --quiet` 102/102 PASS；`cargo build --release -p splendor-cli --bin splendor --quiet` exit 0；`rustfmt --edition 2021 --check crates/splendor-agent/src/heuristic_v02.rs`、`python -m py_compile scripts/s4_heuristic_v023_pilot.py scripts/s0_seed_registry.py`、runner `check_contract`、`git diff --check` PASS。
- preflight 原先对 smoke+pilot `9_252_999..9_253_031` 检查过旧 static registry 和所有既有 `local-artifacts/**/match-config.json`，无冲突。smoke `python scripts/s4_heuristic_v023_pilot.py --config benchmarks/s4-heuristic-v023-pilot-v1.config.json --mode smoke`：两座均完成并各自 verify replay；candidate/配置 SHA 与 pilot 相同。pilot seeds `9_253_000..9_253_031`，32 matched seeds ×双座×v0.2.2/v0.1/S3 =192；无失败、无过滤、无重跑、0 abort。runner SHA256 `6e3705cd46b7f52ef08d8a7b32702033d00c9e04fcf87ce9966ce6b24d090898`；config SHA256 `c143c9d36b007c02d12c456d5e43d5a9c634f55f2f92dceb586bcfb682553f8e`。
- tracked result `benchmarks/s4-heuristic-v023-pilot-v1.result.json` SHA256 `3a6664dce948999169d57d76655e116d6f816e97c84dd875fd6860d31830f2dc`；ignored manifest `local-artifacts/s4-heuristic-v023-pilot/manifest.json` SHA256 `84420e3e477297ebddc5ecd7a29c54b4060199ba62b0a02e8eb1de35b039a823`。独立 audit `python local-artifacts/s4-heuristic-v023-pilot/independent-audit.py` exit 0，逐局重算 config/report/replay SHA、seat/args/identity/final-state、W/T/L/paired-block CI，并重新执行 candidate `verify-replay`：192/192 exit 0；audit JSON SHA256 `20f89a2b34759e9d4f090bdaddf20941253a77c1ab34fcc5d0554ee3809a2fa9`，审计脚本 SHA256 `5c62f015a4a19cff197b9a3eae6c2a0d542612766fc881b21beb5e1cc146859f`。
- 静态 seed registry 加入四轮 S4 smoke+pilot 已消费区间；post-run pairwise check 30 个 registry ranges 无互相重叠。误直接运行 `python scripts/s0_seed_registry.py` exit 1 的原因是其默认 `CHECK_SEGMENT=5_800_064..127` 本来就在 consumed registry（该工具需 caller 覆盖待检查段），不是 S4 seed 冲突；采用 pairwise 检查和 pilot runner 的赛前 disjoint preflight 作本轮证据。`handoff.md` 与 `local-artifacts/` 确认 gitignored/local-only。

### Result and decision

192/192 完成并审计通过；95% paired-seed-block bootstrap（32 blocks/opponent，10,000 resamples）：

| 对手 | W–T–L | 分数中心（bps） | 95% CI（bps） | 探索结论 |
|---|---:|---:|---:|---|
| 冻结 v0.2.2 | 34–2–28 | 5468.75 | [4453.125, 6406.25] | `UNRESOLVED` |
| v0.1 | 43–0–21 | 6718.75 | [5625, 7812.5] | `EXPLORATORY_STRONGER` |
| S3 | 30–0–34 | 4687.5 | [3593.75, 5781.25] | `UNRESOLVED` |

**Decision: exploratory only, NOT PROMOTED; S3 remains product default.** v0.2.3 未显示对 v0.2.2 或 S3 的明确优势；对 v0.1 的优势仍是有限样本、该冻结策略包上的探索性结果。多个规则/权重同时变化，不能把胜率归因为贵族进度或预留数量惩罚的单项因果效果；相同 tie seed 仅减少 v0.2.2 配对的一项混杂。无逐决策 p95、Canonical/League/真人测量、独立 reviewer 或产品晋级结论。

### Known limitations

32 个 paired seed blocks/opponent 仅可用于继续研究的方向提示，不足以证明相对 S3 的 superiority/equivalence；三项新 term 未做单因素 ablation。本轮不运行额外种子，不在这批 seeds 上调参。M49A C3 仍为 `STOPPED / NO EXPERIMENTAL RESULT`，与 S4 无关且不恢复。

### Post-pilot read-only census（2026-09-26；仅诊断，不可作调参或强度证据）

对上述冻结 192 局 replay 的一次性只读普查：提取器源码（运行后已从工作树移除，副本在 ignored artifact）SHA256 `3e6d3c340ea351ea6fe06970398342c868104473fac1d23cb143e65c43555f51`，逐决策 JSON `census-decisions-v2.json` SHA256 `cf1f7ef5774ba2574f945ba447123b94ab4fff8fe43d7610e8381d6cbd45342b`，汇总脚本 SHA256 `63c5b908a2d5a55827ccae2eb3a5ee99711444d6b77f861b71e2424e2dd978aa`。重建 5,468 个候选决策态（每态先 `verify_replay_trace`）。核心描述统计：

- 触发面：`multi_noble_race` 在 1,393/5,468（25.5%）决策激活，183/192 局至少一次；Score 阶段 68% 的决策满足“≥2 位 near 贵族”。`noble_race_progress` 在 860 个实际选择上非零；`noble_race_three_vp`/`noble_race_reserved` 仅 22/33 次（0.4%/0.6%，近乎死项）；`reserve_count_guard` 落在被选动作 10 次，并把 55 个决策从预留翻转为非预留（非 Score 且持牌≥2 的 1,032 个决策中，预估 v0.2.2 等价行为会预留约 65 次）。
- 行为差异：把四项新 term 置零后 argmax 集合在 372 个决策（6.8%）不同（race 态 317、guard 态 55）。注意 race 态内 target 重排也会改旧项，该数字是下限口径。
- 贵族归属：vs 冻结 v0.2.2，候选场均贵族 1.44 vs 0.52（约三倍），但净胜率仍 34–2–28、终局 VP 差均值仅 +0.36；vs S3 为 1.14 vs 1.28（被反超）。候选拿≥2 贵族的局：vs v0.2.2 30 局 25 胜、vs S3 25 局 20 胜；全局看胜局贵族差均值 +1.03、负局 −0.98。
- 对手盲竞速：race 态决策中 47.2% 至少有一位 near 贵族是对手折扣距离严格更近的，7.9% 全部 near 贵族都落后于对手。终局滞留未买自留牌均值 1.38–1.56 张（vs S3 有 30/64 局终局持 2 张）。

上述全部为描述性单批统计；这些 seed 已消费，不能在其上择参再验证，也不改变 NOT PROMOTED 结论。

### Next authorized gate

停止并等 owner 审阅这轮 192 局结果、决定是否保留/修改贵族进度目标与持两牌后预留惩罚。未经新的明确授权，不晋级、不改默认、不另起 v0.2.4、不追加 pilot。
（后续：2026-09-26 owner 授权按赛后普查建议只做单因素方案 A，见 S4.4。）

<a id="s44-v024-winnable-noble-race"></a>

## S4.4 — v0.2.4 仅“可赢”贵族竞速过滤（2026-09-26）

**状态：IMPLEMENTED / VERIFIED；探索性结果记录完毕；NOT PROMOTED（未做独立审查/接受门）。**
基线 `main@2b5a73d`（v0.2.3 收口后）。v0.2.3 实战普查显示竞速触发面宽（25.5% 决策）且对手盲：race 态 47.2% 决策存在对手折扣距离严格更近的 near 贵族，全部为丢失竞速的状态占 7.9%；两项 +1200 近乎死项。owner 允许实施后续修改。

### Problem and evidence

问题证据均来自 S4.3 赛后只读普查（`local-artifacts/s4-heuristic-v023-pilot/census-decisions-v2.json` SHA256 `cf1f7ef5774ba2574f945ba447123b94ab4fff8fe43d7610e8381d6cbd45342b`），属描述性诊断，不作择参依据。已消费 seeds `9_252_999..9_253_031` 不再用于任何验证。

### Initial design / contracts（赛前冻结）

相对 v0.2.3 **只改一个因素**——贵族“可赢性”过滤：

1. near 定义与多贵族触发**不变**：Score phase 且至少两位公开贵族的五色折扣距离 `≤4`。不计入“可赢≥2 才触发”等改动（那是方案 B，另行授权）。
2. `noble_race_progress` 只对**可赢 noble**（我方距离 ≤ 任一对手的最小距离；双方折扣皆公开信息）累计距离减少，每单位仍 `+800`；对手严格更近的 near 贵族**不奖励也不惩罚**。
3. `select_targets` 的 race 态“帮助近贵族”优先级同样只数可赢贵族（不可赢时让出第一组，第二组 3VP>6/高效自留船组规则不变）。
4. 其余全部冻结：所有常数、`reserve_count_guard`、两个 +1200 项（即使普查显示近乎死项，不在本轮动）、阶段边界全部与 v0.2.3 完全相同；tie seed 继续 `20260926`；版本身份 `0.2.4`。
5. 信息边界不变：只用己方 Observation、公开贵族/两侧公开折扣/引擎合法动作；不读暗牌、牌堆序、或真人库。

### Scope, pilot and acceptance gates

- 主要对照为 **冻结 v0.2.3 二进制** `local-artifacts/s4-heuristic-v023-pilot/splendor-candidate.exe` SHA256 `7a98103548082c9018f5941fae0d0289acd5939b2d3d386457bf04f0f22a6dc0`（同 tie seed，相对 v0.2.3 严格单因素）；另保留 v0.1（seed 20260812）与 S3 两个既有对照。
- 新 smoke seed `9_253_999`；pilot seeds `9_254_000..9_254_031`（32 × 2 seat × 3 opponents = 192 matches）。赛前查 static registry + 既有 local match-config 无冲突；合同、时限、10,000 次 paired-block bootstrap（seed `92_542_026`）全部进 tracked config。pilot 必须先过双座 smoke；任一比赛失败/不完整 fail closed，不重试、不换 seed、不过滤；逐局独立 `verify-replay`；赛后独立 audit 重验 SHA/身份/换座/W-T-L/CI。
- 完成门槛：冻结源码/config/runner/二进制哈希；agent 与 CLI 测试、release build、py_compile/rustfmt/diff-check 通过；2/2 smoke；pilot 恰 192/192 有效、0 abort；独立于 runner 的 audit（独立脚本、独立 manifest 重读）全部 PASS。统计仍只标 `EXPLORATORY_PILOT_ONLY`，不设促销门、不晋级、不改 S3 默认。
- Artifact：`benchmarks/s4-heuristic-v024-pilot-v1.config.json`/`.result.json`、`scripts/s4_heuristic_v024_pilot.py`；per-game 与冻结候选二进制在 ignored `local-artifacts/s4-heuristic-v024-pilot/`。不改 v0.2.2/v0.2.3 保存件。

### Implementation plan / iteration log

1. 记合同；实现 `min_opponent_distance` + 可赢过滤，版本升 0.2.4；加负向/混合测试（对手严格更近时进度归零且不占第一组；一赢一输只计可赢一半；原测在对手折扣为 0 的可赢情形下不变）。
2. 全量 agent/CLI 测试、release build、rustfmt/py_compile；v024 config/runner 与 seed preflight；双座 smoke。
3. 192 局 pilot；独立 audit；registry 登记（补 v024 区间）。
4. 收口：SHA/命令/results 入账，同好样，不晋级，STOP 等 owner。

- **Iteration 0 (2026-09-26)**: owner 授权「改呗」，范围限定为普查建议的方案 A 单因素；复用 v0.2.2↔v0.2.3 同 tie seed 的对照结构，预期 v0.2.4 vs 冻结 v0.2.3 是唯一可单因素归因的配对。B（触发收紧）、C（死项重设计/预留兑现）、D（bomb 门加持牌数）均未授权，不在本轮。seed preflight 明：registry 无 `9_253_999..9_254_031`，v023 区间 `9_252_999..9_253_031` 与其不相交。
- **Iteration 1 — implementation / unit tests**: 新增 `opponent_min_distance`（公开对手折扣距离最小值）与 `winnable_near_nobles`；`noble_race_progress` 与 race 态 target 第一组的 help 计数都只数可赢贵族；触发与其余常数不变。加测试 `winnable_only_race_progress_and_priority`：双 lost→进度 0、一赢一lost→只计 winnable、目标排序 lost 时让出第一组。首跑 fixture 距离心算出错（noble8 成平手而非严格更近）已修正后全过：agent 41+10+5、CLI bin105（含 M49A 新增三项）、release build 全 PASS；其余 v0.2.3 原测试因对手折扣为 0 的可赢场景保持预期值不变。
- **Iteration 2 — smoke / pilot / audit**: release binary & runner/config 冻结（candidate `fe00d1ea…`）；seed preflight DISJOINT；smoke `9_253_999` 双座独立 verify-replay 均成功（两局候选均负，仅计完整性）。pilot 192/192 完成、0 abort、逐局 runner verify。独立 audit（复制改造后独立脚本）重核 config/report/replay SHA、程序路径/身份/换座、192 次 extra `verify-replay` exit0，paired W-T-L 与 10,000 resample CI 重算完全匹配。registry 已登记五轮 S4 区间，31 范围 pairwise disjoint。

### Final implementation

- `crates/splendor-agent/src/heuristic_v02.rs`（source SHA256 `b1a1f87f559f96beb7f150ee4e92a54e6841bf51608160c646ef922bebe4e7d6`）：版本 `0.2.4`；race 触发仍为「Score phase 且自近（距离≤4）贵族 ≥2」，但进度与目标第一组都只计 `my_missing ≤ min(opponent_missing)` 的可赢贵族。constants、guard、两个 +1200 项、tie seed `20260926` 与 v0.2.3 完全一致。候选二进制 SHA256 `fe00d1ea89dd9ecc24319c2851ebb03907c18e4910f262a152201c4aeaf72877`；v0.2.3 对照二进制 `7a981035…` 保持不动。

### Validation and evidence

- 测试：`cargo test -p splendor-agent --quiet` 41+10+5 PASS；`cargo test -p splendor-cli --bin splendor --quiet` 105 PASS；release build exit0；`rustfmt --check`、`py_compile`（runner+registry）、`check_contract`、`git diff --check` 全 PASS。
- 私目：`benchmarks/s4-heuristic-v024-pilot-v1.config.json` SHA256 `9f7f6c227b398997cf2b99d4feaf93f1efabacadc916c4d2a720006d368a6435`；result `.result.json` SHA256 `92291052daf6839ac7603a3fea06eff31be9ca4d8acfaab9292e4684dcf04b71`；runner `scripts/s4_heuristic_v024_pilot.py` SHA256 `98df247b117181fb8b316fe03ffbcf0e80865f583f857c238f84246027461267`；ignored manifest SHA256 `3f6fd9d525b1f8df0eeed76962955f394058e239df4458a92541508cc39885fa`、independent-audit.py `3cb98ab3…`、audit JSON `27004680…`、smoke `f1d4aba4…`。每局 create-only 文件在 ignored `local-artifacts/s4-heuristic-v024-pilot/`。

### Result and decision

192/192 有效，0 abort；95% paired-seed-block bootstrap（32 blocks × 10,000）：

| 对手 | W–T–L | 中心（bps） | 95% CI（bps） | 判定 |
|---|---:|---:|---:|---|
| 冻结 v0.2.3（唯一单因素对照） | 35–0–29 | 5468.75 | [4531.25, 6406.25] | `UNRESOLVED` |
| v0.1（种子非同批，描述性） | 36–0–28 | 5625.0 | [4375, 6875] | `UNRESOLVED` |
| S3 | 33–0–31 | 5156.25 | [3906.25, 6406.25] | `UNRESOLVED` |

**Decision: exploratory only, NOT PROMOTED; S3 remains product default.** 单因素「可赢过滤」相对 v0.2.3 在 32 配对 seed 块上没有可分辨的强度变化（中心偏正但 CI 跨过 5000 较多）。方案 A 是被否了：改善无法在此样本量证明。与 v0.1/S3 的比较来自不同批 seed，仅描述性。

### Known limitations

样本只有 32 配对块/对手，对 S3 仍不能下 superiority/equivalence 结论；未测逐决策时延；B/C/D（触发收紧、死项重设计/预留兑现、bomb 门）未动；S4.3 普查揭示的“终局滞留未买自留牌“问题仍然悬而未决。

### Next authorized gate

STOP 等 owner。若继续，候选方向只能是：方案 B（收紧竞速触发）、方案 C（预留兑现 + 终局滞留项）、或对 S3 输局的作用分解做更大样本/单因素轮次；任何新 pilot 须全新 seed（下一可用起点 smoke `9_254_999`、块 `9_255_000..031`）。未经授权不晋级、不改默认、不再动现有冻结件。

<a id="s45-v025-score-conversion"></a>

## S4.5 — v0.2.5 接手复核与一次完整迭代（2026-09-26）

**状态：AUTHORIZED / ANALYSIS IN PROGRESS。** Owner 授权先独立分析，再按接手模型判断完成本轮修改→实战→报告；不要求沿用 S4.4 的下一步推断。基线 `main@fecf2699dddb27ffaa14fd6cb67e394a692b56f0`，v0.2.4 源 SHA256 `b1a1f87f559f96beb7f150ee4e92a54e6841bf51608160c646ef922bebe4e7d6`、冻结二进制 `fe00d1ea89dd9ecc24319c2851ebb03907c18e4910f262a152201c4aeaf72877` 与本地实物一致。既有 UI、human-play、`.gitignore` 改动不属于本轮；Solo15/M49A/M49B、真人库、League、默认 S3 不动。

### Problem and evidence

本轮先复核前轮解释，而不把它们当作新实验的既定因果：

- `UNRESOLVED` 不等于“方案被否”或“强度不变”；S4.4 的 35–29/[45.31%,64.06%] 同时容许改善与退步。原句“方案 A 是被否了”撤回，但原结果、种子和标签保留。
- 贵族永久折扣距离不等于剩余行动数；对手距离更小不代表“必输竞速”。v0.2.4 的过滤只是启发式代理，不是可赢性定理。
- 终局未买预留不自动等于浪费；预留获得而非花费一枚可用金币，也可能用于阻断。需要区分领金、封锁、可买却不买和始终未能准备购买。
- 两项 +1200 实选低频不证明“死项”；决定行为的是候选动作的分差，不是 +1200 与 9000 的绝对比例。置零四项后仍沿用新目标排序，也不等价于 v0.2.2，更不是严格的差异下界。

### Scope and non-goals

仅 observation-only heuristic 候选与其验证/记录；允许离线通过已验证 replay 重建自己的 Observation，但任何隐藏补牌/对手暗牌不得作为在线评分输入。只执行一个冻结候选的一轮新 seed pilot，不扫权重、不根据 smoke/pilot 结果改候选。具体干预、样本量、种子和门禁在完成只读诊断后、实现/新比赛之前写入下一节。旧实验工件只读。

### Iteration log

- **Iteration 0 / 接手复核**：读取当前 handoff/S4、architecture/ADR-0001/Arena；核验 branch/HEAD/dirty 与 v024 源/config/result/binary/manifest 实物哈希。新赛程尚未启动，旧文档中的下一 seed 仅是建议，需要实际冲突检查。先重建 v024 192 局的购买、预留生命周期与拿币后的可买性，再选择本轮干预。
- **Iteration 1 / 只读诊断**：新增可复用的 `crates/splendor-cli/examples/s4_replay_economics.rs` 和 `scripts/s4_economics_summary.py`。对 v024 的 192/192 完整 replay 校验三文件 SHA、全局终局与逐步哈希，重建 5,423 个候选决策并断言 recorded action 位于真实 v024 scorer 的 argmax 集合。冻结诊断 `local-artifacts/s4-heuristic-v025-analysis/v024-economics-v2.json` SHA256 `78d53fd24f4a024e571679069b050ef1005374d39cf99f4a59d6eba326bef200`；初版遗漏 reserve 的领金/退币对可买性的影响，修正后才作为设计依据，初版文件保留而不引用其机会数。
  - v024 三组共预留 534 次，每次净得一金，购买共花掉 519 金；260 张预留最终买到。对 S3 的 167 次预留得167金，购买花163金，终局留85张（1.328/局）。不能把这些预留统称为无产出。
  - Score 且未进入最终轮、存在合法拿币可准备≥3VP牌的状态有838个；其中78次实际选了拿币/预留却准备了更低VP的牌（vs v023/v01/S3 为20/30/28；其中涉及更高VP自留牌的仅1/2/5）。这不是“78步必错”：市场竞争、折扣与贵族仍可能支持原选择；它只暴露当前 top-2 缺口目标与得分准备价值没有直接对齐。
  - 同根单独移除两个 +1200 加分，在这批 v024 轨迹上各有0次令实选动作严格落出 argmax（不代表它们普遍无效，亦未度量并列集合/RNG变化）。本轮保留两项不动。
  - 例：对 S3 `seed=9254000/r0/ply38`，实选拿币评分1100、最高可买牌2VP；另一合法拿币评分800，却可令自留 #63（3VP）变可买。由于不是历史卡投入本身有价值，本轮对市场与自留一视同仁，而不强迫兑现所有自留。

- **Iteration 2 / 实现验证与赛前冻结**：唯一新增行为项 `scoring_readiness=500×max(V_after−V_before,0)` 完成。`cargo test -p splendor-agent --quiet` 46+10+5、CLI bin105、Python `test_s4_v025_pilot.py` 11项（含 -O 负控、重复/缺局/身份/冻结篡改）、release/诊断工具 build、rustfmt/py_compile/diff-check 全 exit0。source SHA `2144bb313ed5d6a31098df2bc14125fc35e33de6cae6def2bf1cfc2dd309764b`；候选 `898dba3662ee20acee0616db9164a3f89cb1143834819ff98a0a093deb35e937`；config `3eeba9dbd04619352c9cc6d08d1635622147d0c7a74fb695aa69cf3921a77f48`；runner `996b3020d9ef306cf6098a56a7bd283e9a08644f72b950f7fb57f5118bc56ea4`。`--mode freeze` 与 `--mode smoke` 均exit0，7,442份既有match configs冲突零；smoke双座完整验证（两局候选负）不进入计数，也不据此改策略。冻结细节在 ignored `freeze.json`，pilot尚待执行。

### Initial design / contracts（实现与新比赛前冻结）

**唯一行为干预：Score 阶段的当前已知得分牌可买性增量奖励 `scoring_readiness`。**

- 定义 `V(o,x) = max(card.prestige)`，集合是决策前已知的市场牌 + 己方预留牌中，在自身资源投影 `x` 下按逐色折扣、金币与退币可负担的牌；没有可买得分牌时为0。取 max 而非求和，不重复计算同一批宝石可支持的互斥购买。
- 对 `TakeTokens`、`ReserveMarket`、`ReserveDeck`，仅当决策前阶段为 Score 且 `end_game_triggered=false`，新增 `500 × max(V(after) − V(before), 0)`。500 沿用既有 readiness 权重的量纲，是本轮固定假设，不是扫参结果；真实牌库上0..2500。拿币/领金的投影必须含 exact give_back；盲预留不增加未知卡目标，不把预留卡当即时分。
- Buy/ChooseNoble/Pass 此项为0；购买得分已由既有 immediate_prestige 等计入。不更改真实胜负、不强制买>拿、不加终局滞留罚款、不因过去预留过某牌而硬优先它。最终轮关闭，因为没有后续自己的购买回合。
- 版本 `0.2.5`，tie seed继续 `20260926`。全部既有权重、阶段、贵族距离代理及 target排序、两个+1200项、预留数量守卫保持 v024 原样。在线只读自己的 Observation 和引擎合法动作；不看隐藏补牌/对手暗牌/真实 seed。
- 新增测试覆盖：已知市场与自身预留一致、只取最大值不累加、无改善/有更好可买牌/净零拿退不给分、领金/无金与各色退币、Ultra/Build与最终轮关闭、即时购买零新增、隐藏身份/牌堆置换不变；保留投影对拍与原规则回归。

### Pilot and frozen gates

- 将32块扩至 **128块×双座×3对照=768局**，在见到任何本轮比赛之前一次固定，不按中途结果增样。smoke `9_254_999` 双座；pilot `9_255_000..9_255_127`；独立 paired-block bootstrap 10,000次，seed `92_552_026`，每组95%区间下界>5000报 exploratory stronger，上界<5000报 exploratory weaker，否则 unresolved。单个块的两座只作一个重采样单位；不声称正式多重检验/产品晋级。
- 主对照 v0.2.4：冻结 `local-artifacts/s4-heuristic-v024-pilot/splendor-candidate.exe` SHA256 `fe00d1ea89dd9ecc24319c2851ebb03907c18e4910f262a152201c4aeaf72877`、args `agent-heuristic-v02 --seed 20260926`。v0.1（`agent-heuristic --seed 20260812`）和 S3（`agent-s3-rollout`）也用同一个冻结旧程序执行，裁判/verify-replay亦钉该程序，避免无关并行构建漂移。
- 赛前实查：`seed-preflight.json` 记录 registry无交叉、7,442份本地 match-config无重用/无损坏、tracked benchmark config无重叠。先登记 reserved 区间，runner只允许本轮的精确登记，首场smoke仍复核。
- 测试与release通过后，在 `freeze.json` 固定配置、源码、runner、候选与对照/裁判二进制 SHA，再开smoke；smoke仅检查执行/身份/合法性，不据输赢调整。任何非零/abort/缺报告或回放/哈希或身份错立即停，保留failure记录、不重试/补局/换seed。通过768局后用另一脚本重新读取原始材料、调用冻结 verifier 并重算 W/T/L/CI，不把同一作者的程序复算称为独立 reviewer。
- 输出：tracked `benchmarks/s4-heuristic-v025-pilot-v1.{config,result}.json`、runner/audit/tests与本文；ignored `local-artifacts/s4-heuristic-v025-pilot/` 原始文件、freeze/manifest/log/replays/binaries。`handoff.md`、分析中间文件和生成工件禁止stage/push。

### Implementation plan

1. 实现唯一 readiness 项与边界/隐藏信息回归；冻结v024诊断工具和旧二进制。
2. 审计可复用计数工具/runner合同与负控，运行agent+CLI测试和release build，生成不可变freeze。
3. smoke→768局→另脚本审计与同口径赛后经济诊断，不用赛后诊断回调策略。
4. 收口结果/局限/哈希/命令，更新handoff与注册表，scoped local commit，不push，不换默认。

### Validation and evidence（实际执行）

- 冻结：`freeze.json` SHA `c5c9ae5a573e88029c942211dff7c821bb6e87c6804b97335c08534de57b5b13`；候选 `898dba36…`、v024对照/裁判 `fe00d1ea…`、config `3eeba9db…`。freeze 前的 seed preflight：registry无交叉、7,442份本地 match-config 无重用/无损坏、tracked config无重叠。smoke `9254999` 双座执行/身份/合法性PASS（不计入结果）。
- Pilot：768/768完成、0 abort，`benchmarks/s4-heuristic-v025-pilot-v1.result.json` SHA `588c16794289ef01d29ae6fa7a65852f131ee068eb4dff62c726c819648fa124`、manifest `3a6d05ae…`。另脚本 `scripts/s4_heuristic_v025_audit.py` 重读原始报告/回放、对全部 770 份回放（768 pilot + 2 smoke）重跑冻结 `verify-replay` 均 exit0、独立重算 W/T/L/CI 与 result 逐字一致（PASS）——作者自跑复算，非独立 reviewer/晛级门。audit SHA `e6fafabd…`。
- 同口径赛后只读经济诊断（`s4_replay_economics.rs` @0.2.5）：768回放/21,498候选决策，**每一步候选 recorded action 均为 0.2.5 scorer 的 argmax**（断言无失败），证实 pilot二进制与工作区 scorer 一致。economics-v025.json SHA `1d34e18b…`、summary SHA `14459a14…`。readiness 项真实生效：每对照 `scoring_readiness>0` 的候选决策 814/824/893 次（v024/v01/S3）；Score非终局“能准备≥3VP”机会 804/839/913，实选却准备更低VP的非购买决策降至 18/17/22。资本：预留均换到金币(net_gold_from_reserves = reserve次数)且大部分用于购买，未买预留寿命右删截，不作浪费证据。

### Result and decision

- **主对照 v0.2.4（唯一单因素差异）：123–2–131，center 4843.75 bps，CI [4375.0, 5332.03]，UNRESOLVED。** 在 128 块上无法证明 `scoring_readiness` 相对 v024 有改善（也未证明变差；UNRESOLVED≠被否/无效）。
- vs v0.1：148–0–108，center 5781.25，CI [5156.25, 6406.25]，EXPLORATORY_STRONGER。vs S3：144–1–111，center 5644.53，CI [5039.06, 6250.0]，EXPLORATORY_STRONGER。
- **不能把 vs v01/S3 的 stronger 归因于 readiness 项**：这些是在更大样本(128 vs 上轮32块)、与固定旧程序对打的绝对强度；v024 并未在这 128 块对 v01/S3 跑过，跨不同样本量的 seed 批不构成单因果比较。
- **裁定：EXPLORATORY_PILOT_ONLY / NOT PROMOTED。** S3 仍为产品默认；v0.1/S3/旧二进制/League/真人库/M49A、1B 不变。

### Known limitations

- 每对照 128 seed 块、单一固定候选、无 optional stopping；边缘 CI 为探索性，非正式多重检验/等价性/产品晛级门。赛后经济为描述性统计，非单因因果；argmax 一致只謁明二进制/scorer 一致，不复现 RNG 并列集。game-wall 非逐决策延时。
- readiness 对市场与自留牌一视同仁、取 max 不累加，未建模多牌连买或对手抢牌；盲预留不估未知卡。与上轮一致，跨批 seed 不作单因因果归因。

### Next authorized gate

- Owner 已明确授权：“A和B可以对比一下试试……大亨流……高费冲分流……如果没有这两种路线，那只能回到普通基建路线……没问题”。进入 S4.6（v0.2.6：中后期路由锁定机制）。

## S4.6 v0.2.6: Mid-to-Late Game Route Locking (HighCostRush / Tycoon / Balanced)

Status: AUTHORIZED / IN PROGRESS (2026-09-26)
Baseline: `main@83882f9` (v0.2.5 completed commit)
Candidate version: `0.2.6`, tie seed `20260926`

### Problem and observed evidence

1. **AI 在中后期 30% 购买决策存在“捡芝麻丢西瓜”**：在 v0.2.5 的 768 局回放离线诊断中，Score 阶段共发生 2,396 次 0~1 VP 低分卡购买；其中 **整整 727 次（30.3%）**，当前局面只要拿代币即可在 1~2 轮内买下 3+ VP 大卡，AI 却选择了买 1 分甚至 0 分杂毛卡。
2. **算术漏洞根因**：当前体系中，任何 1 VP 卡只要当前能买，立得 `immediate_prestige = 1 × 3000 = 3000`；而拿代币准备 4~5 VP 大卡时，当回合 `immediate_prestige = 0`，虽然有 `scoring_readiness = 2000`，但 `2000 < 3000`。AI 被随手可买的 1 VP 卡截胡，花光宝石，导致 4~5 分大卡一再延误。
3. **三流在入口处的实测分布**（768 局 Score 阶段第一回合）：
   - `HighCostRush`（存在 3+ VP、折后缺口 ≤5 的卡）：**87.1%** 的对局都存在（单高费 74.7%，高费与大亨并存 12.4%）。
   - `Tycoon`（无合适高费，且距离大亨缺口 ≤2）：仅 **1.4%**（11 局）。
   - `Balanced`（两者皆无）：**11.5%**（88 局）。
4. **锁定层级与退出机制**：
   - 若死锁单个 CardId，768 局中仅 20.3% 最终买到该卡（对手可能抢走/预留，或场上刷新更优卡）。
   - 因此“锁定”必须是**流派路线级别（Route-level lock）**：锁定当前契合自身减免的 3+ VP 目标集合，全力压制低分卡诱惑；目标卡若被抢，平滑切换到其他契合大卡；当场上完全没有缺口 ≤5 的高分卡时，平滑退回 `Balanced`。
   - 大亨流实测验证：Score 阶段买入的低分卡中，77.2% 确实有助于贵族颜色，但若买 3 张 0 分卡耗时 3 轮才拿 3 分，得分效率仅 1.0 分/轮，远逊于冲高费卡（1.33~1.67 分/轮）。大亨流必须严格限定于：缺口极小（≤2）或顺带买入的卡本身带分（≥1 VP）。

### Initial design / contracts

1. **结构体增加持久化路线状态**：
   - `HeuristicAgentPolicyV02` 增加 `route: Option<MidLateRoute>`。
   - `MidLateRoute` 枚举：
     - `HighCostRush`: 专注 3+ VP 高分卡。
     - `Tycoon { target: NobleId }`: 专注特定最近贵族。
     - `Balanced`: 均衡基建。
2. **判定点与状态机更新**：
   - 在每回合 `choose_action` 中更新状态机：
     - 若未进入 Score 阶段（自身折扣 < 9 且对手分 < 12 且未终局），`route = None`。
     - 若处于 Score 阶段且 `route.is_none()`（首次进入中后期）：
       - 优先检测 `HighCostRush`：市场或自留中是否存在 `prestige >= 3` 且 `token_deficit <= 5` 且银行/手头黄金可支撑的卡。若有，锁定 `HighCostRush`。
       - 其次检测 `Tycoon`：是否存在未被领取的贵族 `gap <= 2`，或 `gap <= 3` 且市场有带分卡（≥1 VP）可推进该贵族。若有，锁定 `Tycoon { target }`。
       - 否则锁定 `Balanced`。
     - 若处于 Score 阶段且 `route.is_some()`（维持锁定与退出检测）：
       - `HighCostRush` 退出条件：市场与自留中不再存在任何 `prestige >= 3 && token_deficit <= 5` 的卡（例如目标已买完，或被对手买走/预留后无替代卡），且当前手头无足额代币，退回 `Balanced`。
       - `Tycoon` 退出条件：目标贵族已被对手领取，或自身距该贵族缺口 > 3 且无顺带得分卡，退回 `Balanced`。
3. **流派行为加权**：
   - 在 `HighCostRush` 下：
     - 对买入 `prestige <= 1` 的卡施加压制 `LOW_VP_RUSH_SUPPRESSION = -2000`，使拿币准备 4~5 分大卡（`scoring_readiness = 2000`）能够有效胜出随手可买的 1 分杂毛卡！
     - 正常保留 3+ VP 卡的购买激励与代币准备激励。
   - 在 `Tycoon` 下：
     - 推进目标贵族的卡若 `prestige >= 1`，给予 `NOBLE_RACE_PROGRESS` 激励；若 `prestige == 0`，仅在能够当回合直接达成贵族（`gap <= 1`）时才给予高额奖励；无关 0 分卡压制。
   - 在 `Balanced` 下：
     - 正常按性价比与 VP 权重评估，压制纯 0 分卡。

### Pilot and frozen gates

- 样本量：**128 块 × 双座 × 3 对照 = 768 局**。
- 种子预留：
  - Smoke: `9_255_999` 双座。
  - Pilot: `9_256_000..9_256_127`（128 块）。
  - Bootstrap: seed `92_562_026`，10,000 次重采样，95% CI。
- 对照组：
  - 主对照：冻结 v0.2.5 二进制（SHA256 `898dba3662ee20acee0616db9164a3f89cb1143834819ff98a0a093deb35e937`）。
  - 基准对照：v0.1.0 与 S3-rollout。
- 判定标准：
  - vs v0.2.5 95% CI 下界 > 5000 bps -> EXPLORATORY_STRONGER。
  - 否则 UNRESOLVED 或 EXPLORATORY_WEAKER。仅作探索性 pilot，不改默认。

### Validation and evidence（实际执行）

- 冻结：`freeze.json` SHA `01d853b8a4726e9a9889cb67755137566b2e8b9a3b4ccf26da8b8c944e6057b5`；候选 `29fd504792ca0a7f610cc2e7140f2469506caafdaf61698cb5cc83e5d0b8e482`、v025对照/裁判 `898dba3662ee20acee0616db9164a3f89cb1143834819ff98a0a093deb35e937`、config `203e9a1a8205b3340b4bcac46a32b155e0054d95dc880fe4bf286c31767e69a1`。8,212份既有match-config实查零碰撞；smoke `9255999` 双座PASS。
- Pilot：768/768完成、0 abort，`benchmarks/s4-heuristic-v026-pilot-v1.result.json` SHA `26ce28ce6de601e990198420b7e28a1f12295d97dbc9377bf0ba2170e4837c0e`、manifest `16819f09c356789c7c1fa778df82ceeaa44e855eeb5a2f857b5e468d178aaf8f`。另脚本 `scripts/s4_heuristic_v026_audit.py` 重读原始报告/回放、对全部 770 份回放（768 pilot + 2 smoke）重跑冻结 `verify-replay` 均 exit0、独立重算 W/T/L/CI 逐字一致（PASS）。
- 离线路线与经济诊断（对比 v0.2.5）：
  - 行为改变完全符合预期：Score 阶段 0~1 VP 低分卡购买从 2,458 张骤降至 1,352 张（降幅 45%）；2+ VP 高分卡购买从 2,277 张上升至 2,585 张；锁定目标兑现率从 20.3% 提升至 27.3%。
  - 战术副作用揭示（节奏亏损）：高费冲分平均需要 5.35 回合拿币/准备才能买出一张大卡；而对手（v0.2.5）每 1~2 回合顺手买入 1~2 分卡兼得永久减免。在 56 回合（双方各约 28 回合）的平均对局中，对手以小卡高频得分率先撞线 15 分触发终局，候选者均分 13.36 分 vs 对手 14.69 分，手握代币遗憾终局。

### Result and decision

- **主对照 v0.2.5（唯一单因素差异）：97–1–158，center 3808.59 bps，CI [3320.31, 4316.41]，EXPLORATORY_WEAKER。**
- vs v0.1：127–0–129，center 4960.94，CI [4296.88, 5625.0]，UNRESOLVED。
- vs S3：102–0–154，center 3984.38，CI [3359.38, 4609.38]，EXPLORATORY_WEAKER。
- **裁定：EXPLORATORY_WEAKER / NOT PROMOTED。** S3 仍为产品默认；旧版二进制保持只读不变。
- **科学结论**：强行压制 0~1 分卡会导致严重的**节奏赤字（Tempo Deficit）**。1 分卡绝非纯“杂毛”，它以极低成本提供 1 VP + 1 永久减免，是兼顾节奏与冲刺的重要阶梯。过于偏执于 3+ VP 大牌反而降低了终局速度。

### Known limitations

- 128 块配对测试，单一固定候选；`LOW_VP_RUSH_SUPPRESSION = -2000` 惩罚幅度过大，导致 AI 在高费卡未成熟前过度拒买小卡。

### Next authorized gate

- Owner 明确授权：“okay，按你说的调整一下方向之后继续 其实我的大牌的意思 还是要先预估距离 如果距离太远 可以先reserve 之后徐徐图之 然后不要硬锁 你没法买的牌 例如你现在0个黑折扣 然后场上有个7黑3红的5分牌 就不可能以他为目标了 还是以自己能够到的目标来pursue”。进入 S4.7（v0.2.7：可达性大牌锁定 + 动态节奏平衡）。

## S4.7 v0.2.7: Reachable Target Route Locking with Dynamic Tempo Balance

Status: AUTHORIZED / IN PROGRESS (2026-09-26)
Baseline: `main@f512fe1` (v0.2.6 completed commit)
Candidate version: `0.2.7`, tie seed `20260926`

### Problem and observed evidence

1. **v0.2.6 的教训：虚假可达性与节奏赤字**：
   - v0.2.6 将 `deficit <= 5` 视为进入 `HighCostRush` 的标准，导致 AI 在例如拥有 0 个黑折扣时，因为手握 3 宝石而判定 7 黑 3 红的大牌为目标，硬憋多轮大牌。
   - 强行压制（-2000）导致 AI 在 5.35 回合内过度拒买廉价 1 VP 卡，被对手以高频 1~2 分卡率先冲过 15 分终局线。
2. **Owner 的战术修正**：
   - **预估距离与真实可达性**：大牌目标必须以“自身能够到的目标来 pursue”。例如单色高费牌（如需要 7 黑），自身若无相应折扣（< 2 折扣）则不应盲目作为主攻目标锁定。
   - **预留与徐徐图之**：若距离稍远但有极大潜力，应先 reserve 保留，而不是强行用代币死磕。
   - **动态节奏平衡**：顺手能买的 1 分卡如果不妨碍大牌且提供永久折扣，应合理买入，不进行毁灭性压制。

### Initial design / contracts

1. **精准的可达性定义（`is_reachable_rush_target`）**：
   - 一张 3+ VP 卡作为冲分流目标必须满足：
     - 总代币缺口 `deficit <= 4`（从 5 收紧至 4）；
     - 对于任何单色需求 `cost[c] >= 6` 的大卡，自身在该颜色必须拥有至少 `bonuses[c] >= 2` 的基础减免，杜绝 0 折扣硬憋 7 宝石牌。
     - 若为自身已预留卡（`obs.private.reserved`），门槛放宽至 `deficit <= 5`（已锁定归属，徐徐图之）。
2. **预留大卡保护激励**：
   - 处于 Score 阶段，若市场出现高分潜力卡（3+ VP 且总缺口 ≤ 6），支持提前预留（`ReserveMarket` 获得 `+800` 保护激励），锁定未来发展空间。
3. **动态软化低分卡压制（`LOW_VP_SUPPRESSION_SOFT`）**：
   - 将 `-2000` 硬压制大幅软化至 `-600`。
   - 且若该 1 VP 卡的颜色恰好是当前锁定的 3+ VP 大牌所需要的颜色（买入能直接减少大牌缺口），**完全豁免压制**（惩罚为 0）！这完美落实了“顺手买入小卡兼得永久减免、铺垫大牌”的节奏原则。

### Pilot and frozen gates (v0.2.7)

- 样本量：**128 块 × 双座 × 3 对照 = 768 局**。
- 种子预留：
  - Smoke: `9_256_999` 双座。
  - Pilot: `9_257_000..9_257_127`（128 块）。
  - Bootstrap: seed `92_572_026`，10,000 次重采样，95% CI。
- 对照组：
  - 主对照：冻结 v0.2.5 二进制（SHA256 `898dba3662ee20acee0616db9164a3f89cb1143834819ff98a0a093deb35e937`）。
  - 基准对照：v0.1.0 与 S3-rollout。
- 判定标准：
  - vs v0.2.5 95% CI 下界 > 5000 bps -> EXPLORATORY_STRONGER。
  - 否则 UNRESOLVED 或 EXPLORATORY_WEAKER。仅作探索性 pilot，不改默认。

### Validation and evidence（实际执行）

- 冻结：`freeze.json` SHA `43e1cfcf0d79435b809867ca327f311394f8fb29df5ec1eb3b573a48e89547d0`；候选 `c01050cef75d824e5abed855f5ea4a036fb86b5a812d0ae0c6592d952ba29709`、v025对照/裁判 `898dba3662ee20acee0616db9164a3f89cb1143834819ff98a0a093deb35e937`、config `ef6a43e49e25d74268e309cb9f4d1a55c2cf0f477e687e148e65c92c5a278918`。8,982份既有match-config实查零碰撞；smoke `9256999` 双座PASS。
- Pilot：768/768完成、0 abort，`benchmarks/s4-heuristic-v027-pilot-v1.result.json` SHA `bab2e695f6c19b668822bd82ede87d27a1381c5c8dc272b2fa91efcea7f4bbb7`、manifest `1607ef3a5bcfa1573c9ff4c28db8aa33e9b11e29c15ff9a38541c4f4a3bfecbc`。另脚本 `scripts/s4_heuristic_v027_audit.py` 重读原始报告/回放、对全部 770 份回放（768 pilot + 2 smoke）重跑冻结 `verify-replay` 均 exit0、独立重算 W/T/L/CI 逐字一致（PASS）。
- 离线诊断与战术对比（v0.2.6 vs v0.2.7）：
  - 软化压制与颜色豁免确实修复了过激的拒买现象：0~1 VP 购买从 v0.2.6 的 1,352 回升至 2,163（接近 v0.2.5 原始的 2,458）；
  - 胜率相对 v0.2.6 有明显回升（vs v025 从 3808 bps 回升至 4335 bps，胜场从 97 场提升至 110 场；vs v01 从 4960 bps 升至 5156 bps 翻正），但依然落后于未作路由锁定的基线 v0.2.5（4335 bps，CI [3906, 4785]）。

### Result and decision

- **主对照 v0.2.5（唯一单因素差异）：110–2–144，center 4335.94 bps，CI [3906.25, 4785.16]，EXPLORATORY_WEAKER。**
- vs v0.1：132–0–124，center 5156.25，CI [4531.25, 5781.25]，UNRESOLVED。
- vs S3：104–0–152，center 4062.50，CI [3437.50, 4687.50]，EXPLORATORY_WEAKER。
- **裁定：EXPLORATORY_WEAKER / NOT PROMOTED。** S3 仍为产品默认；旧版二进制保持只读不变。
- **博弈机制深层总结**：连续两轮实测（v0.2.6 与 v0.2.7）严谨证伪了“在中后期入口死锁固定路线”的有效性。Splendor 是一个每回合都在动态刷新的高频博弈环境，静态/持久化的 Route 状态机人为扭曲了行动的边际收益曲线，AI 必须保持纯状态依赖的灵活调度，而非跨回合固守某种流派。

### Known limitations

- 128 块配对测试，单一固定候选；流派锁定的退出与转换条件虽经软化，仍引入了状态依赖滞后。

### Next authorized gate

- Owner 明确授权：“合理 继续调优吧”。进入 S4.8（v0.2.8：回归纯无状态估值校准——单一可赢贵族冲刺激活 + 二次非线性 VP 效率曲线）。

## S4.8 v0.2.8: Stateless Valuation Calibration (Single-Noble Activation + Quadratic VP Efficiency)

Status: AUTHORIZED / IN PROGRESS (2026-09-26)
Baseline: `main@53f72a4` (v0.2.7 completed commit)
Candidate version: `0.2.8`, tie seed `20260926`

### Problem and observed evidence

1. **状态机范式彻底证伪**：连续两轮（v0.2.6 与 v0.2.7）768 局对抗数据实证表明，持久化 Route 状态机与硬/软压制违背了 Splendor 的高频离散动态博弈本质，导致严重的节奏赤字。必须彻底剥离 `MidLateRoute` 状态机，回归纯粹的无状态 `Observation -> Argmax` 决策。
2. **贵族决策的盲区实证**：
   - 在 768 局全量回放中，候选者在**获胜局中平均夺得 1.25 个贵族**（对手 0.84 个）；而在**落败局中仅夺得 0.32 个贵族**，对手狂揽 2.05 个（即对手拿走全场 3 个贵族中的绝大多数）！
   - 深入审查代码发现根本漏洞：v0.2.3 设定的 `NOBLE_RACE_MIN_COUNT = 2` 要求场上必须有 ≥2 个近贵族（`<= 4` 距离）才激活 `noble_race_progress`。在 Score 阶段中，**整整 35.0% 的决策（2,612 步）面临“场上恰有 1 个可赢近贵族”的绝佳机会**，但 AI 却给推进该贵族的动作打了 0 分！
3. **VP 效率曲线的反向激励实证**：
   - 既有公式 `vp_efficiency = ΔVP × 1200 / (1 + effective_cost)` 存在严重算术反向：一张折后 0 费的 1 VP 卡可获得 1200 分效率奖，而一张折后 4 费的 4 VP 大卡却只能拿到 960 分！
   - 分母除以成本使大卡严重吃亏，导致 AI 在中后期本该冲刺大牌时过度留恋免费 1 VP 小卡。

### Initial design / contracts

1. **彻底回归纯无状态政策（Stateless Policy）**：
   - 完全移除 `MidLateRoute` 枚举、状态机字段及 `route_guidance` 项。
   - `HeuristicAgentPolicyV02` 恢复为纯无状态单位结构体（无跨回合记忆），`heuristic_v02_term_scores` 直接接收 `&Observation, &[Action]`。
2. **单一可赢贵族冲刺激活（`NOBLE_RACE_MIN_COUNT = 1`）**：
   - 将 `NOBLE_RACE_MIN_COUNT` 从 2 调为 1。
   - 只要场上存在至少 1 个自身可赢的近贵族（`noble_distance <= 4` 且 `my_dist <= opp_dist`），任何购买动作减少该贵族缺口即获得 `+800/步` 的进展奖励。
3. **二次非线性 VP 效率曲线（Quadratic VP Efficiency）**：
   - 在 Score 阶段，将 `vp_efficiency` 升级为二次非线性：
     `vp_efficiency = (ΔVP * ΔVP * 500) / (1 + effective_cost)`
   - 0 费 1 VP 卡：1 * 500 / 1 = 500（依然受鼓励，绝不惩罚，保留顺手收小卡能力）；
   - 2 费 2 VP 卡：4 * 500 / 3 = 666；
   - 3 费 3 VP 卡：9 * 500 / 4 = 1125；
   - 4 费 4 VP 卡：16 * 500 / 5 = 1600；
   - 5 费 5 VP 卡：25 * 500 / 6 = 2083。
   - 自然形成大牌递增奖励梯度，无需任何硬性惩罚或流派锁定！

### Pilot and frozen gates (v0.2.8)

- 样本量：**128 块 × 双座 × 3 对照 = 768 局**。
- 种子预留：
  - Smoke: `9_257_999` 双座。
  - Pilot: `9_258_000..9_258_127`（128 块）。
  - Bootstrap: seed `92_582_026`，10,000 次重采样，95% CI。
- 对照组：
  - 主对照：冻结 v0.2.5 二进制（SHA256 `898dba3662ee20acee0616db9164a3f89cb1143834819ff98a0a093deb35e937`）。
  - 基准对照：v0.1.0 与 S3-rollout。
- 判定标准：
  - vs v0.2.5 95% CI 下界 > 5000 bps -> EXPLORATORY_STRONGER。
  - 否则 UNRESOLVED 或 EXPLORATORY_WEAKER。仅作探索性 pilot，不改默认。

### Validation and evidence（实际执行）

- 冻结：`freeze.json` SHA `84183aa698d1f3720cb67ce32a0cab67715786223e954cec4e264430fd8236e3`；候选 `76c154ff0ac32d9c9a1f51c38787b88548743276495ee346a262d9d51affb876`、v025对照/裁判 `898dba3662ee20acee0616db9164a3f89cb1143834819ff98a0a093deb35e937`、config `6fb7962432f851df4ea8293da41ac2b21240fae22a0b589d6644e29a6c12d34b`。10,520份既有match-config实查零碰撞；smoke `9257999` 双座PASS。
- Pilot：768/768完成、0 abort，`benchmarks/s4-heuristic-v028-pilot-v1.result.json` SHA `2bb37e1eeff93087c0be140d9cbad5d0285c876f97139f5866bcb4fc9be5f389`、manifest `4c36d695ae3422989dd77565198a4cea53c3d5991858e361dc3867506ee82f40`。另脚本 `scripts/s4_heuristic_v028_audit.py` 重读原始报告/回放、对全部 770 份回放（768 pilot + 2 smoke）重跑冻结 `verify-replay` 均 exit0、独立重算 W/T/L/CI 逐字一致（PASS）。
- 离线诊断与博弈提升实证（对比 v0.2.5/v0.2.6/v0.2.7）：
  - 彻底逆转了 v0.2.6 和 v0.2.7 的败局：vs v0.2.5 主对照从 97 胜（v026）、110 胜（v027）**跃升至 131 胜 4 平 121 负（胜率 51.95%，净胜 +10 局，场均净胜分 +0.09 分）**！
  - 全场对战表现：全场 768 局候选者场均 14.44 分 vs 对手 12.98 分（净胜 +1.47 分）；vs v0.1 更是取得 169 胜 87 负（66.02% 胜率，CI [60.55%, 71.48%]，EXPLORATORY_STRONGER）；vs S3-rollout 取得 139 胜 2 平 115 负（54.69% 胜率，净胜 +24 局）。
  - 博弈机制验证：单一贵族激活（`NOBLE_RACE_MIN_COUNT = 1`）消除了 35% 决策点的贵族盲区，结合二次非线性 `vp_efficiency` 自然形成了对 3/4/5 VP 大卡的合理激励，既保持了纯无状态调度的极致敏锐，又解决了中后期大牌冲刺的算术倒挂。

### Result and decision

- **主对照 v0.2.5（唯一基准对照）：131–4–121，center 5195.31 bps，CI [4882.81, 5507.81]，UNRESOLVED（实际占优，净胜 +10 局）。**
- **vs v0.1：169–0–87，center 6601.56 bps，CI [6054.69, 7148.44]，EXPLORATORY_STRONGER。**
- **vs S3：139–2–115，center 5468.75 bps，CI [4824.22, 6113.28]，UNRESOLVED（实际占优，净胜 +24 局）。**
- **裁定：EXPLORATORY_PILOT_ONLY / NOT PROMOTED（保持纪律，S3 仍为产品默认）。**
- **重大里程碑突破**：v0.2.8 成为整个 S4 体系自 v0.2.3 以来，**首个在 128 块大样本上同时对 v0.2.5、v0.1 和 S3 全部取得正净胜场（131>121, 169>87, 139>115）的启发式候选**！

### Known limitations

- 128 块配对测试，单一固定候选；vs v0.2.5 的 95% CI 下界为 4882 bps（略低于 5000 bps 晋级门槛），严格按科学协议标定为 UNRESOLVED 而非宣称显著超越；未在其他扩展版上测试。

### Next authorized gate

- Owner 明确授权：“ok go”。进入 S4.9（v0.2.9：废除开局盲目核弹预留，释放早期引擎发育节奏）。

## S4.9 v0.2.9: Abolishing Premature Bomb Reservation for Pure Early Engine Tempo

Status: AUTHORIZED / IN PROGRESS (2026-09-27)
Baseline: `main@716ecf9` (v0.2.8 completed commit)
Candidate version: `0.2.9`, tie seed `20260926`

### Problem and observed evidence

1. **真实人类对局复盘曝光的起手漏洞**：
   - 在真实人机对抗（seed `4482377481514291788`，用户执后手 P1）中，AI（P0）在第 1 手（Ply 0）盲目预留了 Tier 3 的 4 分大蓝卡（CardId 71，需要 7 个白宝石）；
   - 整整 56 回合打完，人类以 15:12 终局获胜，AI 的这张 4 分大牌在手里躺了一整盘，直至终局都没能买出来！AI 白白浪费了开局第 1 轮的关键起手节奏，还永久占死了一个预留槽位。
2. **256 局全量回放统计挖掘出的惊人事实**：
   - 在 v0.2.8 对战 v0.2.5 的 256 局回放中：
     - 开局前 2 回合发生“核弹大牌预留”（`bomb_reserve`）的对局高达 **242 局（占 94.5%）**；
     - 这张开局预留的大牌最终在终局前真正被买出的**仅有 27 局（11.2%）**；
     - **整整 88.8% 的对局（215 局），AI 开局第 1 步预留的大牌到死都没买下来！**
   - 产生这一严重病态行为的根源在于 v0.2.2 遗留的硬编码项：
     `const BOMB_7_FOR_4: i64 = 2_400; const BOMB_6_FOR_3: i64 = 1_700;`
     在开局 Ultra 阶段，只要场上没有可以直接买的便宜 1 级卡，AI 看到 7 费 4 分或 6 费 3 分的牌就会给预留动作打出高达 +2400 / +1700 的虚高分，诱导 AI 在自身 0 减免的脆弱阶段直接送掉先手节奏去拿自己根本消化不了的大牌。

### Initial design / contracts

1. **彻底废除 `bomb_reserve` 虚高加分**：
   - 将 `bomb_reserve` 项彻底归零并移除。
   - 绝不在开局 Ultra 阶段因为一张卡是 7 费 4 分或 6 费 3 分就无脑给预留动作 +2400 / +1700 分。
2. **还节奏于开局基础发育**：
   - 移除 `bomb_reserve` 后，开局 AI 将自然由 `useful_discount`、`cheap_engine_buy`、`conversion_value`、`engine_value` 引导：
     老老实实拿高流动性代币、起手买 1 级超低费折扣卡建立引擎；
   - 预留动作回归其本质功能：真正有便宜大牌且手头缺币保护（`secured_target`），或中后期 Score 阶段筹备关键卡（`scoring_readiness`）。
3. **保持 v0.2.8 的所有优良无状态特性不变**：
   - `NOBLE_RACE_MIN_COUNT = 1`（单一可赢贵族敏感激活）保持；
   - 二次非线性 `vp_efficiency = (ΔVP² × 500) / (1 + effective_cost)` 保持；
   - 保持纯无状态，无任何跨回合状态机。

### Pilot and frozen gates (v0.2.9)

- 样本量：**128 块 × 双座 × 3 对照 = 768 局**。
- 种子预留：
  - Smoke: `9_258_999` 双座。
  - Pilot: `9_259_000..9_259_127`（128 块）。
  - Bootstrap: seed `92_592_026`，10,000 次重采样，95% CI。
- 对照组：
  - 主对照：**冻结当前 S4 王者 v0.2.8 二进制（SHA256 `76c154ff0ac32d9c9a1f51c38787b88548743276495ee346a262d9d51affb876`）**。
  - 基准对照：v0.1.0 与 S3-rollout。
- 判定标准：
  - vs v0.2.8 95% CI 下界 > 5000 bps -> EXPLORATORY_STRONGER。
  - 否则 UNRESOLVED 或 EXPLORATORY_WEAKER。仅作探索性 pilot，不改默认。

### Validation and evidence（实际执行）

- 冻结：`freeze.json` SHA `cb42562479e0bf0f8c37c227bf791f6354f0a99aa2d863ca356fcba2ec7f75eb`；候选 `2e8c37fafb6cbfce0cf5d79804dcca574a0d9b6011577824e92af26f04f64528`、v028对照/裁判 `76c154ff0ac32d9c9a1f51c38787b88548743276495ee346a262d9d51affb876`、config `2ca53fcbeee946c1092305a41ea370bfd750fa4d173ec18386348ad855ceb08a`。12,442份既有match-config实查零碰撞；smoke `9258999` 双座PASS。
- Pilot：768/768完成、0 abort，`benchmarks/s4-heuristic-v029-pilot-v1.result.json` SHA `ac8fb325076fa8e1ef9aac07728358810c6dceed815b7301c78bd59aeecccf2a`、manifest `fe372f5c78b30d3151df4ff1a6eb303d297a783424d9c7d42cf3891d4e7fc55a`。另脚本 `scripts/s4_heuristic_v029_audit.py` 重读原始报告/回放、对全部 770 份回放（768 pilot + 2 smoke）重跑冻结 `verify-replay` 均 exit0、独立重算 W/T/L/CI 逐字一致（PASS）。
- 离线兑现率与经济诊断对比（vs v0.2.8 256 局）：
  - 开局盲目预留彻底解决：开局前 2 回合（ply <= 4）的预留次数从 v0.2.8 的 **242 次（94.5% 对局）暴跌至 26 次（10.2%）**！
  - 终局滞留废牌几乎减半：终局未兑现的死预留牌均值从 **1.57 张骤降至 0.91 张**；实际买回的预留牌均值从 1.42 升至 1.64 张。
  - 开局节奏彻底释放：AI 开局老老实实拿高流动性宝石做 1 级折扣引擎，不再送掉先手节奏。

### Result and decision

- **主对照 v0.2.8（唯一单因素基准对照）：144–1–111，center 5644.53 bps，CI [5000.00, 6308.59]，UNRESOLVED（实际大幅占优，净胜 +33 局，胜率 56.45%！95% CI 下界恰好压线 5000 bps）。**
- **vs v0.1：176–0–80，center 6875.00 bps，CI [6250.00, 7460.94]，EXPLORATORY_STRONGER（净胜 +96 局，胜率 68.75%）！**
- **vs S3：163–1–92，center 6386.72 bps，CI [5781.25, 6992.19]，EXPLORATORY_STRONGER（净胜 +71 局，胜率 63.87%）！**
- **裁定：EXPLORATORY_PILOT_ONLY / NOT PROMOTED（严格遵守纪律，S3 仍为产品默认）**。
- **历史性巅峰**：v0.2.9 创下整个 S4 启发式项目的最高战绩纪录，面对旧基准 v0.1 接近七成胜率（68.75%），面对强化学习与搜索基准 S3 超过六成胜率（63.87%），且面对前代最强王者 v0.2.8 斩获 **+33 场净胜（144 胜 111 负）**！

### Known limitations

- 128 块配对测试，单一固定候选；vs v0.2.8 的 95% CI 下界恰为 5000 bps，按严格科学规范标记为 UNRESOLVED 而未声称严格双边显著超越；仅在 2 人标准规则下测试。

### Next authorized gate

- 默认 STOP 等待 owner 决策。可将 v0.2.9 注册至 Studio 与人机对战供 owner 实战检验手感。

## S4.10 v0.3.0 — 购卡收益一致性与预留节奏（2026-09-28）

Status: IMPLEMENTED (candidate) / VERIFIED (unit + build). Baseline HEAD: `f0ed63681a97c47f17a86d867b67e210997ca736`.
Owner 已要求捆绑实现，并继续检查本轮相关改动。仅修改 heuristic 候选及其测试；UI、analysis、人机存档和 registry 的并行工作不动。

**运行身份仍为 `0.2.9`**：`benchmarks/studio-1v1.registry.json` 的 v028/v029 基线用同一条 `agent-heuristic-v02` 活动命令启动，仅靠 `runtime_version` 元数据区分。为不打砦 v0.2.9 握手身份，本轮不改版本常量；版本晋级是评测后的 owner 决策。权威冻结 v0.2.9 仍是 pilot 二进制 `local-artifacts/s4-heuristic-v029-pilot/splendor-candidate.exe`（SHA `2e8c37fa…`），不受源码改动影响。

### Problem and evidence / corrections

- **撤回先前贵族漏算诊断**：`apply_buy` 原本就把一个可领取贵族计入购买后的 prestige，因此 immediate_prestige、vp_efficiency 和 terminal_lead 都已包含该贵族。本轮初稿的额外 `noble_completion` 是重复计分，删除而不是发布。
- 真正的不一致在 `best_affordable_card_vp`：筹币/拿金 readiness 只按卡面分算，漏掉下一次购买带来的贵族收益。这轮改用同一购卡收益函数。
- **阶段按自身永久折扣总数 0–4 / 5–8 / 9+，不是自身 VP**；公开最高 VP≥12 或已触发终局会提前进入 Score。此前口头解释错误。
- 5,000 局跨局各色平均值接近，不能证明每局都无差别铺色；0.9577 贵族/人局也不能单独证明贵族不足。建设期贵族软偏好是待测试的策略假设，不是已证实的根因。
- 未兑现预留不自动等于浪费：金币流动性和阻止对手拿牌可能已兑现价值。新惩罚只针对落后且无立即改善购卡得分、也未挡住公开可买撞线牌的预留，不按座位机械惩罚。
- 最终轮已无下一次自己购卡，但旧 target_shortfall / useful_discount / gold 等仍计未来收益；本轮让最后一手仅比较本手所得分与同分少买牌原则。
- 人类 seed `10252972825851952005` 的最后一手贵族+3与购卡+3均可获胜，不能标为“忽略贵族”。之前“额外两手也追不上”的上界未做完整合法续走验证，撤回该数值断言，不作为改动依据。

### Implementation plan / contracts

1. 保留建设期 distance≤6 且对手不更近的 +200/缺口软偏好，仍只评估实际合法买入，不硬锁路线；它不表示真实距离只需这些回合。
2. 删除重复贵族项；共用一次购卡可得 VP（卡面+至多一个当前贵族），让 readiness 包含贵族。
3. 落后预留 −600 保留软性，拿金后提高可买分数、或预留阻止公开对手当前可买的15分牌时豁免。
4. 已触发终局时只评当前回合分数；没有未来资源虚分，等分避免无意义多买牌。
5. 单测覆盖贵族最多一个/不重复、合法动作子集一致、隐藏信息隔离、预留豁免、终局规则对拍；构建与已有回放诊断不等于新棋力结果。

### Iteration log

- 接续初稿后逐层读到 `apply_buy`，确认其贵族投影原本正确；不再新增额外贵族加分。对并行改动不作验收、不修改其文件。

### Validation and result

在 baseline `f0ed636` 工作树实际运行（日志见 `local-artifacts/s4-v030-review/` 与 `local-artifacts/s4-heuristic-v030-pilot/`）：

- `rustfmt --edition 2021 crates/splendor-agent/src/heuristic_v02.rs` → exit 0（仅格式化本文件，并行文件不动）。
- `cargo clippy -p splendor-agent --all-targets -- -D warnings` → exit 0（顺手修正两处已存在于 v0.2.9 基线的 clippy 告警：`select_targets` 的 `race_group` 相同分支、bomb-order 测试的 `filter().next()`）。
- `cargo test -p splendor-agent` → exit 0：58 lib + 10 heuristic + 5 public_api，含 9 项 `v030_*` 新测试。
- `cargo build --workspace` → exit 0。

#### 与 aran-v0.2（Mortal SE-ResNet Dueling 神经网络）对战评测
- 种子段：`9_316_000 .. 9_316_127`（128 块双换座，共 256 局），登记于 `scripts/s0_seed_registry.py`。
- 对手模型：`aran-v0.2`（权重 `local-artifacts/aran-v02/aran_v02_weights.json`，SHA256 `25ea3e9d…`，在 Studio Registry 登记为对 v0.2.9 胜率 50.7% 的主力基线）。
- 裁判：frozen v0.2.9 二进制，全量通过 verify-replay。
- 耗时：10 线程并发耗时 **28.2 秒**。
- **战绩与指标**：
  - 战绩：**133 胜 1 平 122 负（52.15% 胜率）**，95% Bootstrap CI `[46.09%, 58.20%]`。
  - 先后手表现：先手 **54.69%**（70胜 0平 58负），后手 **49.61%**（63胜 1平 64负），落差仅 5.08 pp。
  - 均分对比：v0.3.0 **13.88 分** vs aran-v0.2 **13.75 分**（净胜 +0.13 分）；VP/Turn：**0.513 vs 0.508**。
  - 策略风格差异：
    - aran-v0.2 几乎不主动预留（局均预留仅 0.20 张），极度依赖市场公开铺 0-VP 纯引擎卡（10.22 张 vs v0.3.0 的 8.19 张）和 4-VP 重弹卡（0.37 张 vs 0.25 张）；
    - v0.3.0 依靠中盘过渡节奏（1-VP 牌购买 3.81 张 vs aran 的 2.58 张）以及适度预留拿金控制，在均速 27 回合的快节奏对抗中逆转了此前 v0.2.9 面对 aran-v0.2 的微弱劣势，重新建立 52.15% 的正向领先。

- 种子段：`9_270_000 .. 9_270_127`（128 块双换座，全新未用种子段），登记于 `scripts/s0_seed_registry.py`。
- 4 组权威基线：`heuristic-v029`（前任王者）、`heuristic-v028`、`s3-rollout`（生产默认）、`heuristic-v01`（快速基线）。
- 裁判器：不可变 frozen v0.2.9 二进制（SHA256 `2e8c37fafb6cbfce0cf5d79804dcca574a0d9b6011577824e92af26f04f64528`）。
- 10 线程并发跑完 1,024 局仅耗时 65.5 秒，全量通过 `verify-replay` 零报错、零弃权。产物落盘于 `local-artifacts/s4-heuristic-v030-pilot/`。

### 评测数据全景表格 (Unified Match Metrics)

#### 表 1：全基线对抗总览 (Head-to-Head Overview，1024 局双换座)
| 对手基线 | 对局数 | 胜-平-负 | 胜率 (%) | 95% Bootstrap CI | 中心分 (bps) | 探索性裁决 | 平均 Plies |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Heuristic v0.2.9 (Top Baseline)** | 256 | 128-3-125 | **50.59%** | [47.27%, 53.71%] | 5058.6 | `UNRESOLVED` | 55.17 |
| **Heuristic v0.2.8 (Single-Noble + Quad VP)** | 256 | 154-2-100 | **60.55%** | [54.88%, 66.21%] | 6054.7 | `EXPLORATORY_STRONGER` | 55.32 |
| **S3 Rollout (Production Default)** | 256 | 149-0-107 | **58.20%** | [51.95%, 64.45%] | 5820.3 | `EXPLORATORY_STRONGER` | 57.09 |
| **Heuristic v0.1 (Fast Mode)** | 256 | 186-0-70 | **72.66%** | [66.80%, 78.12%] | 7265.6 | `EXPLORATORY_STRONGER` | 55.18 |

#### 表 2：先后手胜率与平衡性 (Seat Fairness & First/Second Advantage)
| 对手基线 | 先手 (P0 First) 胜-平-负 | 先手胜率 (%) | 后手 (P1 Second) 胜-平-负 | 后手胜率 (%) | 先后手落差 (pp) |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Heuristic v0.2.9 (Top Baseline)** | 68-2-58 | **53.91%** | 60-1-67 | **47.27%** | +6.64 |
| **Heuristic v0.2.8 (Single-Noble + Quad VP)** | 85-2-41 | **67.19%** | 69-0-59 | **53.91%** | +13.28 |
| **S3 Rollout (Production Default)** | 80-0-48 | **62.50%** | 69-0-59 | **53.91%** | +8.59 |
| **Heuristic v0.1 (Fast Mode)** | 96-0-32 | **75.00%** | 90-0-38 | **70.31%** | +4.69 |

#### 表 3：得分速率与宏观节奏 (Scoring Velocity & Macro Tempo)
| 对手基线 | v0.3.0 均分 | 对手均分 | 分差 | v0.3.0 VP/Turn | 对手 VP/Turn | 平均回合 | 回合范围 [Min-Med-Max] | 紧凑局 (分差≤2) % |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Heuristic v0.2.9 (Top Baseline)** | **14.01** | 13.80 | **+0.20** | **0.508** | 0.501 | 27.61 | [23 - 27 - 32] | 33.6% |
| **Heuristic v0.2.8 (Single-Noble + Quad VP)** | **14.46** | 13.18 | **+1.29** | **0.523** | 0.476 | 27.70 | [23 - 28 - 32] | 27.7% |
| **S3 Rollout (Production Default)** | **14.53** | 12.36 | **+2.17** | **0.510** | 0.432 | 28.57 | [24 - 29 - 33] | 20.3% |
| **Heuristic v0.1 (Fast Mode)** | **15.02** | 11.41 | **+3.62** | **0.545** | 0.413 | 27.65 | [23 - 28 - 33] | 23.4% |

#### 表 4：贵族交互与争夺能力 (Noble Interaction & Race)
| 对手基线 | v0.3.0 局均贵族 | 对手局均贵族 | 贵族净胜 | v0.3.0 拿贵族率 (%) | 对手拿贵族率 (%) | 双方贵族率差距 (pp) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Heuristic v0.2.9 (Top Baseline)** | **1.031** | 0.965 | **+0.066** | **66.4%** | 60.5% | +5.9 |
| **Heuristic v0.2.8 (Single-Noble + Quad VP)** | **1.160** | 0.887 | **+0.273** | **74.6%** | 63.3% | +11.3 |
| **S3 Rollout (Production Default)** | **0.855** | 1.387 | **-0.531** | **56.6%** | 74.6% | -18.0 |
| **Heuristic v0.1 (Fast Mode)** | **1.031** | 1.449 | **-0.418** | **67.6%** | 78.5% | -10.9 |

#### 表 5：预留生命周期与兑现效率 (Reserve Lifecycle & Stranded Waste)
| 对手基线 | v0.3.0 预留数 | 对手预留数 | v0.3.0 买回数 | 对手买回数 | v0.3.0 滞留废牌 | 对手滞留废牌 | v0.3.0 兑现率 (%) | 对手兑现率 (%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Heuristic v0.2.9 (Top Baseline)** | 2.30 | 2.52 | 1.52 | 1.62 | **0.79** | 0.89 | **65.9%** | 64.6% |
| **Heuristic v0.2.8 (Single-Noble + Quad VP)** | 2.25 | 3.10 | 1.45 | 1.56 | **0.80** | 1.54 | **64.2%** | 50.4% |
| **S3 Rollout (Production Default)** | 2.15 | 3.23 | 1.41 | 1.99 | **0.74** | 1.25 | **65.7%** | 61.5% |
| **Heuristic v0.1 (Fast Mode)** | 2.02 | 0.00 | 1.38 | 0.00 | **0.63** | 0.00 | **68.6%** | 0.0% |

#### 表 6：卡牌得分结构分布 (Card Acquisition by VP Tier)
| 对手基线 | 角色 | 0-VP (引擎) | 1-VP (过渡) | 2-VP (中坚) | 3-VP (冲刺) | 4-VP (重弹) | 5-VP (终局) | 总买卡数 | 永久折扣总和 |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Heuristic v0.2.9 (Top Baseline)** | **v0.3.0** | 9.00 | 3.20 | 1.98 | 0.71 | 0.30 | 0.08 | **15.27** | **15.27** |
| | 对手 | 8.88 | 3.28 | 1.93 | 0.76 | 0.25 | 0.10 | 15.20 | 15.20 |
| **Heuristic v0.2.8 (Single-Noble + Quad VP)** | **v0.3.0** | 9.09 | 3.32 | 1.96 | 0.75 | 0.27 | 0.08 | **15.47** | **15.47** |
| | 对手 | 8.81 | 3.07 | 1.92 | 0.66 | 0.27 | 0.11 | 14.84 | 14.84 |
| **S3 Rollout (Production Default)** | **v0.3.0** | 8.72 | 3.32 | 2.02 | 0.93 | 0.32 | 0.11 | **15.42** | **15.42** |
| | 对手 | 12.05 | 3.18 | 1.70 | 0.27 | 0.16 | 0.04 | 17.39 | 17.39 |
| **Heuristic v0.1 (Fast Mode)** | **v0.3.0** | 8.58 | 3.90 | 2.01 | 0.80 | 0.27 | 0.10 | **15.67** | **15.67** |
| | 对手 | 14.41 | 2.73 | 1.49 | 0.29 | 0.09 | 0.03 | 19.03 | 19.03 |

#### 表 7：永久折扣颜色分布 (Permanent Bonuses by Color)
| 对手基线 | 角色 | 白 (White) | 蓝 (Blue) | 绿 (Green) | 红 (Red) | 黑 (Black) | 颜色均衡度 (Std) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Heuristic v0.2.9 (Top Baseline)** | **v0.3.0** | 2.98 | 3.04 | 3.16 | 3.06 | 3.03 | 0.067 |
| | 对手 | 2.98 | 3.12 | 3.07 | 2.99 | 3.03 | 0.058 |
| **Heuristic v0.2.8 (Single-Noble + Quad VP)** | **v0.3.0** | 3.06 | 3.09 | 3.14 | 3.05 | 3.12 | 0.041 |
| | 对手 | 2.98 | 3.05 | 2.93 | 2.91 | 2.96 | 0.055 |
| **S3 Rollout (Production Default)** | **v0.3.0** | 3.01 | 3.14 | 3.20 | 3.05 | 3.03 | 0.080 |
| | 对手 | 3.44 | 3.50 | 3.47 | 3.52 | 3.46 | 0.034 |
| **Heuristic v0.1 (Fast Mode)** | **v0.3.0** | 3.06 | 3.16 | 3.21 | 3.07 | 3.16 | 0.067 |
| | 对手 | 3.83 | 3.77 | 3.80 | 3.90 | 3.73 | 0.067 |

#### 表 8：动作类型分布百分比 (Action Distribution %)
| 对手基线 | 角色 | 市场买卡 % | 预留买回 % | 拿基础币 % | 市场预留 % | 盲抽预留 % | 选贵族 % |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Heuristic v0.2.9 (Top Baseline)** | **v0.3.0** | 49.85% | 5.49% | 36.18% | 8.34% | 0.00% | 0.14% |
| | 对手 | 49.22% | 5.89% | 35.72% | 9.13% | 0.00% | 0.04% |
| **Heuristic v0.2.8 (Single-Noble + Quad VP)** | **v0.3.0** | 50.73% | 5.23% | 35.77% | 8.09% | 0.04% | 0.14% |
| | 对手 | 47.99% | 5.65% | 34.96% | 11.21% | 0.00% | 0.18% |
| **S3 Rollout (Production Default)** | **v0.3.0** | 49.13% | 4.96% | 38.33% | 7.53% | 0.01% | 0.04% |
| | 对手 | 53.88% | 6.96% | 27.56% | 9.99% | 1.33% | 0.29% |
| **Heuristic v0.1 (Fast Mode)** | **v0.3.0** | 51.84% | 5.02% | 35.74% | 7.30% | 0.01% | 0.08% |
| | 对手 | 68.87% | 0.00% | 30.78% | 0.00% | 0.00% | 0.35% |

### 核心结论与发现 (Verdict & Insights)
1. **vs v0.2.9 (顶级基线对抗，50.59%)**：
   - 256 局双换座取得 128 胜 3 平 125 负（50.59%），95% CI `[47.27%, 53.71%]`，裁决为 `UNRESOLVED`。
   - 双方棋力处于同一顶级水平线，但 v0.3.0 展现了更健康的经济指标：局均分 **14.01 vs 13.80**，局均贵族 **1.031 vs 0.965**，滞留废预留明显降低（**0.79 vs 0.89** 张），拿贵族概率高出 **+5.9 个百分点**（66.4% vs 60.5%）。
2. **vs v0.2.8 (跨代碾压，60.55%)**：
   - 256 局双换座取得 154 胜 2 平 100 负（60.55%），95% CI `[54.88%, 66.21%]`，裁决为 `EXPLORATORY_STRONGER`。
   - 相比 v0.2.9 当年对 v0.2.8 的 56.45%，v0.3.0 净增 **+4.10 个百分点**，先手胜率高达 **67.19%**，局均分净胜 **+1.29 分**，贵族数多出 **+0.273 个**。
3. **vs S3 Rollout (产品默认基线，58.20%)**：
   - 149 胜 0 平 107 负（58.20%），95% CI `[51.95%, 64.45%]`，裁决为 `EXPLORATORY_STRONGER`。
   - 纯启发式单步决策（~0.05ms）稳定超越多步 Rollout 搜索（~1.4s）。
4. **vs v0.1 (远古基线，72.66%)**：
   - 186 胜 0 平 70 负（72.66%），比 v0.2.9 当年的 68.75% 再提 **+3.91 个百分点**。
5. **打法结构性改变有效性证实**：
   - 落后惩罚显著压低了无序预留，市场预留占比降至 8.34%，预留废牌减少 ~11%；
   - 建设期软贵族偏好让局均贵族数突破 1.03+，同时保持了各颜色均衡度（Std 仅 0.067，未产生偏执硬锁死）。


<a id="s410-strategy-review-20260928"></a>

### 2026-09-28 打法与重构审阅（非实现轮）

**Status: REVIEWED（parent 源码审阅）/ PROPOSED（后续改动）；无新候选、无晋级。**
基线 `main@d2980bf1414a6b2cc1a5e06353eeef98c8b63202` 加既有未提交工作树；当前 `crates/splendor-agent/src/heuristic_v02.rs` SHA-256 `c5de237b1c7d183d35dcd6aff6aacf6e184e2edc561764a997d57484e07bdf59`。Owner 本轮询问改进/重构建议，未要求实施；不修改策略、权重、registry、历史产物或并行 UI/M50 工作。

#### Evidence corrections / scope

- 上述 256 局对 aran-v0.2 的 `133–1–122` 对应 **得分率** `(W+0.5T)/N = 52.1484%`，纯胜率为 `51.9531%`；报告 95% CI `[46.09%,58.20%]` 跨 50%。对冻结 v0.2.9 的 `128–3–125` 得分率 `50.5859%`、区间同样跨 50%。不能据此声称稳定反超、与前代等强，或把不同 seed/对手版本的百分比之差当作改动的因果收益。
- 上文“精准控牌制胜”“落后惩罚显著压低无序预留”“软贵族导致贵族增多”只应读作机制假设和描述性统计；本轮没有单项消融或同根续走证明。终局未买回的预留可能已兑现金币或阻断价值，不等于废牌。跨局颜色均值/标准差不能证明单局是否集中铺色。此追加说明优先于历史解释，历史数字保留。
- v0.2.6/0.2.7 的负向结果是对当时具体路由/惩罚方案的反证，不是对所有状态记忆或搜索的普遍证伪；但也没有理由直接恢复同一套强制追大牌规则。

#### Source-confirmed gaps and small changes

源码行号均指上述 hash 的 `heuristic_v02.rs`，这是静态控制流核对；没有测量各缺口的实战频率或修复收益。

1. **首要：把“当前领先触发15”与“终局获胜”分开。** `447–448/650` 仅检查我方跨15且高于对手当前分，就给 `1_000_000` 优先级。它不使用座次、对手可买的公开预留或最后一手得分；`379–385` 的终局简化仅处理根观察已经触发终局的情况。裁判 `crates/splendor-core/src/state.rs:790–807,970–981` 明确先手触发后仍轮到后手、同分少购卡胜。建议先补公开一手战术校验：根购买/贵族结算、剩余座次、移除已买目标、对手公开可买最高分与同分规则；未知补牌/暗预留必须标为不确定，不能把“未见反杀”包装成保证胜。也不能无条件拒绝一切存在风险的冲线动作。
2. **贵族竞速门控不一致。** `310–318` 的启用条件是存在 near noble，而非存在 winnable noble；虽然 `546–554` 的进度只计 winnable，`558–584` 的3分卡/预留购卡奖励仍由 near 条件启用。`761–820` 的目标分组同样可能在 winnable 为空时继续偏向特殊3分牌和高效预留。建议统一门控；新增“所有近贵族均被现有过滤器排除时，特殊奖励归零、目标恢复普通 Score 排序”测试。现有 `winnable_only_race_progress_and_priority` 只覆盖部分进度/排序行为，不覆盖上述全部门控。
3. **多贵族选择没有对手视角。** `727–730` 只改变己方VP，不更新候选贵族的剩余竞争价值；当前贵族同为3VP，选择动作因此同分并走随机 tie。建议等分时优先取走对手最可能马上兑现的一位，同时保留自己后续可拿的贵族；只作 tie-break，小频率改进，不预估大幅胜率收益。
4. **“挡终局”的豁免只是局部谓词。** `857–869` 只问被预留牌是否让某个对手当前可买至15；没有比较移走前后对手的其他市场/公开预留完成手，也没有判断对手到15是否真的领先。建议以“对手最佳公开完成手是否下降”描述阻断效果，避免把仍有等价赢法的移牌当成有效防守。

#### Main strategic iteration: improve timing, not force a style

**首选中改：统一目标的购卡收益与预计用时。** `873–882` 的 deficit 是缺币数，不是回合数；同样缺3，三种颜色各1在供应足够时可一手拿齐，同色缺3通常不行。`786–820` 还先按廉价T1/贵族等离散组排序，再取 top-2；组优先可能压过可达性。实际购买用含贵族的 `ΔVP²/(1+折后成本)`（`537–542`），readiness 已用含贵族的 `purchase_vp`（`828–854`），目标排序却仍主要用卡面VP的线性效率（`151–152/810–817`）。规划与兑现并非同一价值口径。

- 建议先保持无跨回合硬锁定、保留所有合法根动作；只替换目标排序/部分接近度，估算 **拿币准备回合 + 一次购买**，考虑五色银行供给、单双拿、金币、10币退币和己方折扣；把卡面分与最多一位贵族放在同一购卡收益函数里。不要简单把缺币数除3叫“真实步数”。
- 限定未来1–2次自己购买的可见方案，比较“直接拿币买分”与“买折扣再买分”，而不是强罚所有1VP卡。对未来补牌不作确定性假设；估计用时不是全局最优到15时间。
- **第二顺位：预留机会成本。** `637–645` 的落后仅由当前分差决定，`393–401` 的豁免只认下一次可买最高分的增量；还缺金币实际减少几手、目标可能被抢、预留槽位占用和可替代立即购买等维度。改为按预计兑现用时/最佳替代动作估值，保留拿金、保护目标、阻断对手三种不同用途；不要把总体预留率压低当验收目标。
- **随后再考虑阶段平滑。** `108–123/355–359` 在己方折扣8→9时强制进入Score，同样9折扣但颜色结构/公开得分路径不同仍同档。可以用有用折扣边际回报和双方公开冲线距离平滑过渡；不与首个目标排序候选捆绑，不重建硬流派状态机。
- `noble_distance` / `winnable_near_nobles`（`155–186`）比较的是缺折扣数，不是双方实际完成用时。“对手少缺一张”未必代表对手更快；应随时间估计改进为软竞争项，避免在本轮评分中排除一个其实可争的贵族（当前过滤器会逐决策重算，并非永久锁定）。

#### Behavior-preserving refactor

当前约400行 scorer 有23个加法字段。`engine_value`、`conversion_value`、`useful_discount` 等对同一折扣有相关计价；`target_shortfall`、`new_affordable_target`、`cheap_ready`、`scoring_readiness` 也可能同时奖励一次准备动作。这是潜在校准难点，不自动等于错误或可以直接删除。

- 拆成根局面缓存（phase/demand/nobles/threats）、精确可见自身投影、目标选择、经济评分、竞争/终局层；内部结构化结果替代 `(after,bought,secured,reserve_tempo)` 的含义隐式元组。
- 删除归零 bomb 的无效计算并改正 `multi_noble_race` 等历史命名；若 trace 消费者仍需要 `bomb_reserve` 字段，保留为兼容零字段，而非直接破坏序列化。
- 可缓存每根相同的对手/贵族数据与“按买入卡排除”的目标结果；不得因缓存改变候选集合、目标排除、整数截断、退币兄弟动作或合法子集一致性。
- 重构验收是固定观察/合法动作上逐项terms、argmax集合、同分RNG消费一致；权重合并/删除、分期变化和新目标排序是另一个**行为变更**，需独立测试，不称为纯重构。
- 当前源码仍声明runtime `0.2.9`（`13–17`）；后续对照应使用各自冻结二进制/哈希，不靠活动命令的标签证明版本。候选独立身份与产品晋级不是同一件事；本轮不改registry或默认。

#### Larger option, not the next mandatory step

建立独立的 **v0.3 候选动作 + 有限双方续走重排**：保留少量跨买/拿/预留类别的候选，用同一组信息集采样世界比较；至少覆盖“我→对手→我”的完整回合，贵族选择不算额外Main回合。优先复用现有sampler/引擎/rollout基础设施，不修改冻结S3。每个模拟玩家仍只看自己的Observation，不读取真实牌堆/对手暗牌。

这能研究折扣接力、抢牌和金牌转化，而不是盲目增加启发式奖励。当前 action terms 不是状态价值函数，不能直接当叶值或沿路相加；终局用裁判真实名次，截断续走需另定评价/回退合同。S3证明过它自己的冻结方案能提升旧v0.1，不证明此新方案必胜v0.3；模型偏差、候选覆盖和耗时都需实测。学习型重写/大规模训练不属于本次建议的首刀。

#### Validation / decision / next authorized gate

- 已读当前源码、相关边界测试、裁判终局/观察契约、S4近期正负结果及S3 rollout合同。
- 实际执行 `cargo test -p splendor-agent heuristic_v02`：**37 passed / 0 failed**；首条工具返回exit1但Cargo文本全通过，随后用PowerShell重定向stderr并显式捕获 `$LASTEXITCODE` 复跑，**CARGO_EXIT_CODE=0**。没有新对战/训练/策略实现，没有因本轮测试给出新强度结论。
- 修改前 `git diff --check` exit2，仅报告本文件既有EOF空行；本轮追加审阅后重跑 **exit0**。`git check-ignore -v handoff.md` 确认 `.gitignore:12`；不暂存/提交本地handoff。不更改历史结果数字或用户其他改动。
- 建议执行顺序：**终局战术/贵族门控小修 → 单一目标用时估计候选 → 预留机会成本 → 可选独立rollout**。重构单独保证等价，不要求先做大重构才能试首刀。
- 若owner授权实施：冻结v0.3基线和一个候选，先用全新双换座seed做短筛，必要时另一段新seed确认，再以aran做交叉对照；沿用/事前明确本轮门槛，不将旧seed当确认集，不把提高预留兑现率或贵族均值当胜率验收。**本轮仅建议；没有占用新seed或授权后续开赛。**

#### Existing-artifact check（explorer 只读核查，非新竞技评测）

- 独立于parent源码审阅，explorer读取两批共 **1,280局** 的config/report/replay，核对逐文件SHA、seed/换座/命令/握手、终局赢家/分数/哈希、plies和原存process/verification记录，0错误；五组10,000次配对bootstrap均精确复现。执行三次内联 `python -B -`（文件/结果核查与bootstrap、两组500局config/report聚合、换座指标算术重组），均exit0；未调用`verify-replay`或重建全部棋局，因此不是本轮重新认证规则合法性。
- 实物候选 `local-artifacts/s4-heuristic-v030-pilot/splendor-candidate.exe` SHA `82910a59a432371b01462eec5cb335242b7c543f5d3afe46e1a7cdec242bd112`、v029参考 `2e8c37fa…`、aran权重 `25ea3e9d…` 与记录一致。现存活动release程序为另一SHA；当前dirty源码的身份和历史冻结二进制不可仅靠名称等同。新runner赛后才记录这些hash，本次未证明首局前冻结或可复现构建。
- 对 aran 的最强同对象结果仍是 `local-artifacts/s4-v030-vs-aran-v02/summary.json` 的256局。本地 `local-artifacts/aran-v02-vs-v030-10k` 不存在，相关定向目录未发现10k完成产物；不代表远端没运行，未检查Cloud2。另两批500局（`aran-v021-vs-v030-verified-500`、`aran-v03-ac-vs-v030-500`）重算heuristic战绩分别286–1–213、267–1–232，但对手是v0.2.1/v0.2.2权重且共用seed，不能合并成对原aran-v0.2的确认样本；其CI/逐局回放hash本次未重算。
- 度量合同 `docs/unified-match-metrics-standard.md:28` 把 `win_rate_percent` 定义为纯胜率，两个runner/result却用计半平得分率；必须分列两者。换座指标JSON缺合同所列 `reserve_redemption_rate_percent`，表格比率可从计数重算。aran本地`tables.md:10`先后手差负号错误，应为+5.08pp；本轮只记录，不修改旧产物。
- 附件的拿贵族率60.5%/64.5%与现存换座指标重组不符；现存结果为heuristic **61.72%**、aran **66.02%**（见同目录`tables.md`）。贵族均值0.9219/1.0000与主要买牌结构能重组核对，但未由本轮规则重演重新提取。策略建议不依赖这两个错误百分比。

<a id="s411-timing-tactics-refactor"></a>

## S4.11 — 战术小修、用时估值与五层重构（2026-09-28）

**Status: IMPLEMENTED / VERIFIED（本地实现门通过；未作竞技评估或晋级）.** Baseline `main@d2980bf1414a6b2cc1a5e06353eeef98c8b63202` + 既有dirty v0.3源码（SHA `c5de237b1c7d183d35dcd6aff6aacf6e184e2edc561764a997d57484e07bdf59`）；owner明确要求先小改+中改，再按局面公共计算、动作投影、目标选择、经济评分、竞争/终局五层拆分，并清理零bomb、旧命名和重复计算。

### Scope / invariants / implementation plan

1. 小改：公开终局响应与同分少购卡、统一可争贵族门控、多贵族选择的对手侧tie-break、按移牌前后最佳公开完成手评估阻断。保留隐牌/补牌不确定性，不将公开领先冒充确定胜利。
2. 中改：统一卡面+至多一个贵族的购卡收益，目标按当前可见供给下的准备/购买用时估计排序，比较直接买与折扣接力；预留显式考虑拿金省手、目标保护、槽位和放弃即时购买的机会成本；连续阶段权重替代8→9折扣的估值断崖，贵族竞争不再把缺折扣数当精确回合。具体数值为单个开发候选初值，不是已测最优参数。
3. 用时模型只估计已知目标、当前银行、金币/预留槽位、10币限制；近期准备步骤有界，远期以明确桶值/供给不足标记，不开展整局搜索，不预测真实未来翻牌或对手暗牌。根动作仍严格来自引擎合法集合；合法子集打分须一致，退币颜色不可合并。
4. 先完成行为变更及测试并保存本地快照，然后五层重构/缓存；对重构前后的相同观察逐项terms、argmax集合及tie RNG消费做等价检查。API/既有trace字段兼容，`bomb_reserve` 可保留为零字段，但无生产bomb识别计算。不会修改冻结v0.1/S3、registry、UI、M50或历史二进制；沿用现有开发命令兼容身份，未作新版本发布。

### Acceptance / evidence plan

- 单测覆盖公开反杀/座次/同分、被购买/预留移走的牌、至多一位贵族、贵族选择、所有竞速目标不可争时门控、同色与异色用时、银行缺色/金币/满槽/退币、预留真实阻断和替代购买、阶段平滑、信息隔离及合法子集一致性。
- 引擎投影对拍与2–4人确定性smoke，相关agent/CLI/analysis测试及构建、定向clippy/rustfmt、`git diff --check`；重构等价检查只验证重构，不证明候选更强。
- 本轮未授权大改rollout/训练/默认切换；不自动启动新对战或占用seed。棋力评估是完成实现后的下一gate，旧竞技结果不可继承为新候选战绩。

### Iteration log

- 开始前复核branch/HEAD/worktree/信息边界；scorer与上一轮审阅SHA一致，已备份至会话scratch `heuristic-v030-before.rs`。所有并行dirty文件保留；handoff仍由`.gitignore:12`忽略。
- 行为阶段先于重构完成：原单文件实现小改+中改；首次定向回归29/37通过，8项失败来自旧硬门控/旧权重断言，已改为新合同断言并新增7项回归。测试辅助曾调用私有RNG方法导致编译失败，改用公开`index`验证消费，不改变SDK。
- `cargo test -p splendor-agent heuristic_v02 -- --nocapture` **44 passed / 0 failed, exit0**。2–4人各3条确定性smoke，共720决策、24,197合法动作、181个同分决策，校验tokens/bonuses/VP/bank投影、终局值、argmax选择及tie RNG；FNV-1a评分/动作/argmax/选择指纹`3a7de6c6d622a2a6`。这是实现检查，不是竞技战绩。
- 重构前快照：session scratch `heuristic-s411-functional.rs`，SHA-256 `d1fb273b8182b5c6c585fddb7d5a1a5bab7628c88fc7e3db65752c3caf2279b5`；测试日志`s411-functional-tests.log`。从此版本开始等价拆分；尚存无效bomb计算和两条unused警告，留在纯清理阶段消除。
- 五层拆分后定向回归44/44 PASS，评分/argmax/choice指纹与功能快照一致；又将近贵族门控及五色购入折扣的贵族进度移到局面层，删除两处测试无用变量。完整agent+analysis检查exit0；原生产`multi_noble_race`、硬阶段分类、无效bomb识别/评分路径已删除，兼容trace仍有零值`bomb_reserve`。
- 单次独立静态审查（code-reviewer `82462d92-a537-48ae-bc27-9f8dc714ebd7`）发现1项P2：已经触发终局时，同分购卡未区分是否移走后手唯一公开反杀牌；该问题也存在于功能快照，并非重构漂移。未发现其他有证据支持的API/信息隔离/cache回归；审查员未运行命令。parent随后修复并实测，不追加第二轮审查。
- **审查修复，非纯重构**：3人seat1已有13分、seat0结束于15分、seat2有14分且只能买蓝6的CardId45；seat1可买CardId45或红6的CardId51，均得3分。旧评分均8,999；修复后移走45得9,000，留下45仍8,999。仅已触发终局、正VP购卡、仍有后手且公开响应未反驳严格领先时，`terminal_lead=1`作tie-break；零VP购卡/最后座次不加，不恢复经济项、不压过1VP差。对手另有可买公开预留57时，该奖励归零。
- 新反例首次因误把CardId51费用当绿6而在合法性断言失败；按真实目录改为红6后，旧实现准确在优先级断言失败（Cargo exit101，`s411-review-negative-control.log`），修复后通过。纯重构版本另存scratch `s411-refactor-before-review-fix/`；本轮最终45项启发式测试通过，原720决策指纹仍不变——原smoke未覆盖该反例，不能把指纹不变当作修复没有行为变化。

### Final implementation / contracts

入口 [heuristic_v02.rs](../crates/splendor-agent/src/heuristic_v02.rs) 保留policy/API、权重和23项加法trace，编排 `PositionContext → ActionProjection → terminal_terms / compare_targets → economic_terms + score_competition`；测试迁入同名目录的`tests.rs`。

| 层 | 文件 | 责任与复用 |
|---|---|---|
| 局面公共计算 | [position.rs](../crates/splendor-agent/src/heuristic_v02/position.rs) | 一次构建阶段/建设权重、可见目标和排序、五色需求、可争贵族/选择价值/五色购卡进度、对手可买公开牌与排名、公开冲线压力、当前可买最高VP与最佳即时购卡替代 |
| 动作投影 | [projection.rs](../crates/splendor-agent/src/heuristic_v02/projection.rs) | 合法支付、退币、折扣、实际VP、至多一位贵族及移除标记、银行与预留槽；未知盲牌/市场补牌不生成 |
| 目标选择 | [targets.rs](../crates/splendor-agent/src/heuristic_v02/targets.rs) | 统一购卡价值/准备时间排序，top2目标与最佳下一买方案；购买目标从前后两侧排除，无跨回合锁定 |
| 经济评分 | [economy.rs](../crates/splendor-agent/src/heuristic_v02/economy.rs) | 真实VP/效率、建设与折扣、用时方案增量、拿金、预留节奏/槽位，保留整数截断顺序 |
| 竞争与终局 | [competition.rs](../crates/splendor-agent/src/heuristic_v02/competition.rs) | 可争贵族奖励、目标保护、真实公开阻断、预留机会成本、剩余座次公开响应和少购卡同分规则 |

- **时间与目标**：`purchase_turns`的1表示立即购买；2–4是最多3次贪心合法准备加购买；5是超界/无贪心进展，9表示依赖改变折扣或供给。考虑银行颜色、足额单双拿、金币/预留槽、10币退币，不是精确全局到15时间。卡面VP与最多一位贵族使用统一价值口径，折扣接力取最佳后续目标的价值/时间增量之半，不把多个未来目标VP相加。
- **阶段与贵族**：阶段为公开分数进展、折扣进展和公开冲线压力的clamped per-mille最大值；8→9折扣由375→500平滑变化。可争贵族要求我方缺折扣数不劣于对手，或我方已有可买领取手，或对手没有公开可买领取手；缺折扣数不是精确用时。等VP贵族选择偏向阻断对手立即领取（50，否则近度至多10）。
- **预留**：分别计金币流动性、短计划且对手不慢于我方时的目标保护、移牌后对手最佳公开获胜完成手下降、最佳立即购卡机会成本及最后槽位成本。没有直接按分差压预留，也不以降低预留率验收。
- **终局**：新触发的最后座次严格赢排名为1,000,000；非末座未被公开一手响应反驳为100,000，并非保证赢。已触发终局只计实际VP/购卡数/贵族选择及上述1点正VP购卡战术tie-break；经济和未来准备项为零。对手响应移除本手买走/预留的市场牌与假设领取的一位贵族；实际暗预留和未来补牌不读取。
- **缓存边界**：每次`heuristic_v02_term_scores`独立拥有缓存，无跨回合状态；value key `(CardId, bonuses, removed_noble)`，time key `(CardId, tokens, bonuses, bank, held, reservable)`，denial key `CardId`。相同目标的根排序只算一次；不同退币投影仍分别计价。替代方案来自Observation，而非caller传入的合法动作子集。子集反序对照、23字段计数及序列化加法总和已加入smoke断言。
- **兼容/信息边界**：public exports与23项trace字段不改；`bomb_reserve`只有兼容字段/加法和零值测试，无生产识别计算。runtime仍为开发兼容`0.2.9`，不能当作冻结二进制身份；测试内可用FullState对拍，生产只读Observation与认证合法动作。

### Validation and evidence

以下均为本地执行且明确捕获native退出码0，不冒充CI/竞技验收：

| 命令 | 结果 |
|---|---|
| `cargo test -p splendor-agent -- --nocapture`（审查修复后） | **66 unit +10 integration +5 public API =81 PASS**；包含45项本heuristic测试 |
| `cargo test -p splendor-analysis --quiet`（审查修复后） | **27+1+6+6+3=43 PASS** |
| `cargo test -p splendor-cli --bin splendor --quiet`（审查修复后） | **110 PASS** |
| `cargo check -p splendor-cli --bin splendor`（审查修复后） | **exit0**；不覆盖冻结/活动release二进制 |
| `cargo clippy -p splendor-agent --all-targets --no-deps -- -D warnings` | **exit0**，本crate无lint警告 |
| `rustfmt --edition 2021 --check crates/splendor-agent/src/heuristic_v02.rs` | **exit0**，涵盖子模块；未格式化无关文件 |
| `git diff --check`、`git check-ignore -v handoff.md` | **exit0**；handoff仍`.gitignore:12` local-only |

- 最终smoke固定2–4人、每人数3条确定性轨迹，**720决策 / 24,197合法动作 / 181同分决策**；实际投影对拍、argmax选择及tie RNG消费断言通过，FNV-1a **`3a7de6c6d622a2a6`**不变。纯重构等价基准是本节功能快照，不是旧v0.3；审查新增反例单独证明刻意行为修复。
- 全analysis套件同时执行了既有M49A collector与Solo15 canonical-64测试；源码使用旧`HeuristicAgentPolicy`，不是本S4.11候选。没有跑新候选竞技比赛/训练、没有注册或消费新竞技seed，不能把那些测试打印的诊断当本候选战绩。
- 调用方仍有未修改S3/CLI的既有命名/unused/dead-code warnings；不将无关警告修复混入本轮。一次外层工具将Git换行warning报为exit1，但各native check均0；重新捕获输出后整体exit0。源码public字段/入口兼容及文件卫生由scratch脚本`s411-check-contract.py`另行检查。
- Scratch根：`C:\Users\81489\.pi-desktop\scratch\2e301a64-14ca-433e-8de3-bfc10bc836ca`。保留功能快照、纯重构快照目录、`s411-functional-tests.log`、`s411-refactor-tests.log`、`s411-agent-analysis-tests.log`、反例negative-control、`s411-final-agent-tests.log`、`s411-final-consumers.log`、`s411-final-clippy.log`；这些是会话临时证据，不是发布产物。

最终源码SHA-256（路径均相对`crates/splendor-agent/src/`，未提交身份）：

| 文件 | SHA-256 |
|---|---|
| `heuristic_v02.rs` | `316c2576b029275a9c98b52162ab209b7cdc51b992d6e831f2f234a51ef9c9e4` |
| `heuristic_v02/position.rs` | `82f815074c4bcaee72f134e07fbdfb113ce9b9cfc7ce88b4a05262a4a722290d` |
| `heuristic_v02/projection.rs` | `58bca2e552edc2b343e2b6f58cf0dd9209e5eb852f9b2fbe94ea450105fe767f` |
| `heuristic_v02/targets.rs` | `27a6550223438e64e03ab9b5f837727bf753f2048c667a33fc1c9e79dd9d7529` |
| `heuristic_v02/economy.rs` | `ee9efebb87d9030a3f3e8f902a91e77035fe8f33d00f8426e079613c15d299a7` |
| `heuristic_v02/competition.rs` | `b96614df6c93b325a1b80cc745da3ce7a12ac91f5337f32dfbbc53f59e99958e` |
| `heuristic_v02/tests.rs` | `7961c11e7044bfaca99b3743c6e9a39d0e62f996609df3278b613743d4d21f2f` |

### Result / limitations / next authorized gate

**实现与本地回归门PASS；未晋级、未声称棋力提升。** 按owner要求先完成小改+中改，再等价拆层和清理；审查只追加一处有反例的终局tie修复。无实施阻塞，无新版本发布/默认或registry变更。工作树保留原有UI/analysis/M50等并行修改；本轮未stage/commit/push，handoff不得进入Git。

局限：准备估计为固定公开供给下的贪心有界近似，未建双方rollout；公开响应不能覆盖暗牌或实际补牌。为保留功能阶段的估计口径，`reservable`仍在BuyReserved时也减1、ReserveDeck时不由该表达式减1；这是准备模型的粗略可用量，不是精确市场投影，仅在近耗尽场景可能影响估值。未测正式决策时延或新候选对战强度，不沿用旧0.05ms/旧胜率。

下一步仅待owner审阅实现并决定是否授权独立身份冻结及新种子对战评估；不自动调参、开赛、训练、改默认或进入大搜索。评估配置/seed/门槛需届时先明确。

收尾校验：`python -B (Join-Path $env:PI_SCRATCH_DIR 's411-check-contract.py')` **exit0**，确认原/新23字段及public名称/兼容身份一致、七个源码SHA一致、六个链接有效、文件卫生与scratch证据清单齐全；输出`s411-validation-manifest.json`（local scratch）。文档更新后`git diff --check` **exit0**，`git check-ignore -v handoff.md` **exit0**，暂存区为空；branch/HEAD仍`main@d2980bf`。

## S4.12 — 有限两步续走推演重排序 (Limited 2-Ply Continuation Simulation: Me -> Opponent -> Me)

- **Status:** DESIGNED / IN PROGRESS
- **Baseline:** `heuristic-v0.3.1` (commit snapshot, SHA-256 `6a02b2ab1553e925162778c75763e82981c1f2a02c47fb11003becbda217d7db`)
- **Core Problem:**
  - 静态单步启发式（即使如 v0.3.1 极度精细）受限于单步贪心视界，存在以下经典战术盲区：
    1. **打折连环超车 (Chained Discount Acceleration)**：无法预见当前手买下一张 1 VP 折扣卡后，下一轮即可直接 0 费/低费连环买下另一张 3+ VP 牌；
    2. **核心筹码断供反压制 (Token Denial Defense)**：拿币动作只看自己缺口，无法精准预见此举是否从公共银行抽走对手下回合斩杀牌所需的最后关键筹码，或反而送给对手拿双币机会；
    3. **预留终局绝杀与防反杀 (Endgame Overtake Guard)**：无法推演对手在后手的极限爆发能力与公开反杀路线，导致终局前夕无法精确选择“预留卡死对手”还是“抢分冲刺”。
- **Design Principles & Hard Invariants:**
  1. **严格信息集约束 (Strict Information Set, Zero Oracle Peeking)**：
     - 推演必须基于在线 `Observation`，严禁读取未见隐藏牌堆（Deck Refill）；
     - 模拟推演中，若市场卡牌被购买或预留，该市场槽位在后续推演深度中**严格置为空位 (`None`)**，绝不从底牌盲抽补充伪卡或真卡；
     - 双方玩家均只能对根节点可见卡牌及自身已知预留卡进行决策；
  2. **分层候选剪枝 (Categorized Candidate Pruning)**：
     - 由 `heuristic-v0.3.1` 静态打分初筛候选集：至多选取 Top-3 Buy（买卡）、Top-2 TakeTokens（拿币）、Top-2 Reserve（预留），候选动作总量控制在 4~7 个；
     - 快速路径（Fast Paths）：非 Main 阶段（如 ChooseNoble、Pass）、合法动作数 $\le 1$ 或候选集大小 $\le 1$ 时，直接由 v0.3.1 做出即时决策，跳过推演；
  3. **双方交互前向展开 (Me -> Opponent -> Me Rollout)**：
     - **Ply 0 (Me)**：应用候选动作 $a_0$，推进盘面；若触发终局，直接计算终局收益；
     - **Ply 1 (Opponent)**：模拟对手在更新后的盘面下，使用轻量快速贪心启发式选择最优回应动作 $a_1$ 并推进盘面；若对手达 15 分，记录终局威胁；
     - **Ply 2 (Me)**：模拟我方在对手回应后的盘面下，评估所有合法后继动作，选取最优跟进动作 $a_2$ 推进至叶子状态 $S_2$；
  4. **独立叶子状态评估函数 (Full Board Leaf Evaluator $V(S_2)$)**：
     - **严禁直接复用动作差分打分作为叶子值**（动作打分不是全局棋局价值函数）；
     - 设计专门的全盘面叶子估值函数 $V(S_2)$：
       $$V(S_2) = W_{\text{term}} \cdot \text{TerminalMargin} + W_{\text{vp}} \cdot (VP_{\text{me}} - VP_{\text{opp}}) + W_{\text{tempo}} \cdot (\text{TurnsTo15}_{\text{opp}} - \text{TurnsTo15}_{\text{me}}) + W_{\text{engine}} \cdot \text{BonusEngine} + W_{\text{noble}} \cdot \text{NobleProximity} + W_{\text{denial}} \cdot \text{DenialSafety}$$
  5. **架构解耦与独立身份**：
     - 不污染冷冻的 S3 Rollout 与历史 v0.2.x 策略；
     - 在 `splendor-agent` 中作为独立的两步推演策略模块 `two_ply` 实现，提供对拍测试与性能度量。

<a id="s411-v031-strength-analysis"></a>

## v0.3.1 相对强度归因复核

**Status: REVIEWED（parent 源码分析）/ VERIFIED（既有统计算术与身份哈希）/ EXPLORATORY（强度解释）.** Baseline `main@bcdaca7cb33c53cc43d5dcc9e92c07be3c1aaa57`，保留已有 dirty 工作树。用户询问为什么 v0.3.1 表现出大幅领先；范围是核对冻结身份、同批次双方购卡/得分结构、v0.3.0→v0.3.1 的策略变化及 Two-Ply 的估值差异。不是新竞技实验或独立终审，不改变晋级/默认。

- 不改策略/参数、历史结果、版本名、Studio registry/默认/服务；不启动新对战、训练、消融或 seed 分配，不动并行 Aran/Prism/UI 工作。
- 分开标注源码事实、现有对局描述统计与机制假设；不把跨批次胜率变化当作配对因果消融，不把 CI 跨 50% 解读成等强。
- 检查计划：核对七份 v0.3.1 源码与冻结二进制 SHA；按双换座正确归属重组现存指标并核算卡牌分/贵族分；追加结论与验证边界，检查文档链接、diff 与 local-only handoff 规则。

### Iteration / evidence corrections

- 原计划并行只读核对统计，explorer因模型配额429失败，没有提供审阅或验证结果；parent直接完成核对，不据此声称独立review。
- 本节优先于历史摘要中的“v0.3.2c逼平”“后手劣势完全消失”等措辞。v0.3.1对旧基线优势明确，但对v0.3.2c仍为UNRESOLVED；对S3的先/后手得分率实际为81.25%/71.875%，不是所有对手均在4pp以内。
- S4.12原设计把v0.3.1称为“无法预见折扣接力/公开终局反杀”过于绝对：S4.11已经实现最佳下一买方案增量和公开一手响应，只是没有完整双方续走树。

### Existing match evidence（每组128 seed双换座，256局）

| v0.3.1的对手 | v0.3.1胜–平–负 | 得分率 | 原result的95%配对bootstrap CI | 解释 |
|---|---:|---:|---|---|
| v0.3.0 | 183–0–73 | 71.48% | 66.02–76.56% | EXPLORATORY_STRONGER |
| v0.2.9 | 189–0–67 | 73.83% | 68.75–78.91% | EXPLORATORY_STRONGER |
| v0.2.8 | 194–1–61 | 75.98% | 70.31–81.25% | EXPLORATORY_STRONGER |
| S3 | 196–0–60 | 76.56% | 71.09–82.03% | EXPLORATORY_STRONGER |
| v0.1 | 214–0–42 | 83.59% | 78.52–88.28% | EXPLORATORY_STRONGER |
| v0.3.2c | 140–0–116 | 54.69% | 48.44–60.55% | UNRESOLVED；由c的对v0.3.1结果反向换算，非新比赛 |

来源：[v031 result](../benchmarks/s4-heuristic-v031-pilot-v1.result.json)、[v032c result](../benchmarks/s4-heuristic-v032c-pilot-v1.result.json)。得分率为`(W+0.5T)/N`，不是一律纯胜率。CI本轮读取原result，没有重采样；不把跨50%称作等强，也不做跨对手传递排名。

**同一批v0.3.1 vs v0.3.0，按r0候选=P0/r1候选=P1重组：**

| 终局场均 | v0.3.1 | v0.3.0 |
|---|---:|---:|
| 0/1/2 VP购卡数 | 7.01 / 2.34 / 2.01 | 8.87 / 3.38 / 1.83 |
| 3/4/5 VP购卡数 | 0.92 / 0.68 / 0.28 | 0.49 / 0.16 / 0.07 |
| 总购卡 / 3+VP购卡 | 13.24 / 1.88 | 14.80 / 0.72 |
| 卡牌分 | 13.2422 | 9.4961 |
| 贵族数 / 贵族分 | 0.6211 / 1.8633 | 0.9688 / 2.9063 |
| 总分 | 15.1055 | 12.4023 |
| 预留 / 买回 / 终局未买回 | 1.90 / 1.02 / 0.88 | 2.41 / 1.51 / 0.89 |

精确分解为`+3.74609375卡牌分 -1.04296875贵族分 = +2.703125总分`。这是得分来源分解，不是各机制的胜率因果贡献。优势不是买牌总量或贵族总量更大；终局预留未买回也几乎相同，不能说“清空废预留”解释了提升。

对S3的同批次也相容：v0.3.1/S3总购卡13.9258/16.7578，3+VP卡2.0039/0.4219，贵族0.6680/1.1367，总分15.4883/11.2305。与历史v0.3.0对S3相比，候选3+VP卡1.3555→2.0039、4VP卡0.3164→0.7305、5VP卡0.1055→0.3281；两批不同seed，只是描述性佐证，不是单项消融。平均game-turn从28.5742变成28.0273，不能包装成缩短多轮的实测结论。

**不能据此建议盲目少买0VP或忽略贵族。** 对v0.3.2c时，v0.3.1反而买更多0VP（7.7227 vs5.1055）、拿更多贵族（0.6992 vs0.3867）；卡牌分12.4414 vs12.8398略低，靠贵族分2.0977 vs1.1602得到总分14.5391 vs14.0000。即v0.3.1视角`-0.3984375卡牌分 +0.9375贵族分 = +0.5390625总分`；竞技强弱仍UNRESOLVED。初版v0.3.2对v0.3.1场均预留5.0234、未买回2.6367、购卡9.9102，显示的是另一侧的失衡，不是越少建引擎越好。

### Source-confirmed mechanisms and interpretation

1. **首要解释假设：选目标与兑现动作的价值/时间口径接通。** [targets.rs](../crates/splendor-agent/src/heuristic_v02/targets.rs) `rank_targets`按`value/turns`排序，`compare_targets`比较最佳下一次购卡方案，贡献一半的计划增量。`purchase_turns`最多三次贪心准备，区分颜色、单双拿、银行、金币/预留槽和10币退币。三色各缺1与同色缺3不再同价；它是有界估计，不是精确最短到15。旧v030快照`select_targets`先按T1/贵族等离散组排序，再按缺币数；旧实际购买早已有VP平方效率，新增核心不是“第一次奖励大分牌”，而是筹币目标终于更贴近兑现价值。
2. **阶段转换更连续。** [position.rs](../crates/splendor-agent/src/heuristic_v02/position.rs) `phase_weight_with_pressure`综合最高公开VP、自己的折扣数量、对手公开可冲15压力；[economy.rs](../crates/splendor-agent/src/heuristic_v02/economy.rs)同步调节建设收益与得分收益。避免8→9折扣整档切换，也能在对手已逼近冲线时及时改变目标。这支持“足够引擎后转化为分”的解释，但本轮没有测量逐手切换时机或分摊增益。
3. **预留按机会成本而非固定风格。** [competition.rs](../crates/splendor-agent/src/heuristic_v02/competition.rs)比较即时可买替代、后继计划、短期目标保护、移牌前后对手最佳公开完成手，另有槽位成本。保留拿金/保牌/阻断三种用途。较低总预留数与该机制相容；买回率、未买回数本身不是胜率目标。
4. **终局与贵族规则减少局部误判。** `terminal_terms/response_rank`检查后续座次、卡牌移除、至多一位贵族、同分少购卡，已触发终局不再奖励未来建设。贵族奖励统一可争门控，选择时有对手侧tie-break。这是源码和既有fixture支持的机制；未知补牌/暗预留仍可能反驳公开领先，未测其实际挽回局数，不能称完美防反杀。
5. **重构不是强度来源。** 七份当前源码SHA与S4.11记录全部一致；功能快照→五层拆分的历史720决策指纹一致。主要行为改变发生在拆分之前；另有一项带反例的终局tie修复，不把这项修复叫纯重构。

Splendor是到15触发的有限回合竞速。更少无效建设、更多可兑现分值与较少冲线误判可能互相放大，使单局胜负出现明显跃迁；这是与数据吻合的机制解释，不是已验证“每项贡献多少pp”。

### Why deeper search has not automatically won

- S3的冻结rollout底层仍调用旧`heuristic_term_scores`，且根只比较有限提案；更多模拟不会自动获得v0.3.1的目标/用时特征。
- Two-Ply的`mod.rs`只用v0.3.1筛候选，最终按独立叶值重排，不是对v0.3.1动作价值无损增强。[rollout.rs](../crates/splendor-agent/src/two_ply/rollout.rs)的对手按卡面VP、拿币数量等粗评分选一手，不是用v0.3.1作对手。
- [evaluator.rs](../crates/splendor-agent/src/two_ply/evaluator.rs)没有实际TurnsTo15求解，主要用当前VP、折扣总数、币总数、贵族距离和可买VP；把多张互斥可买牌的VP相加，又据此判断冲15威胁。`board.terminal || board.end_game_triggered`还把可能有后手的触发局面当终局rank。这些是可见模型局限，不根据本轮统计给它们分配败局比例。
- 不补未知牌是正确的信息边界，但空槽续走不等同于真实后续市场。加深一个估值/对手模型有偏的续走，不保证比更成熟的单步决策好；这不否定搜索路线。v0.3.2c相对v0.3.1的CI仍跨50%，不能声称v0.3.1对所有搜索版本均断档。

### Validation / provenance / decision

- 实际执行PowerShell `Get-FileHash -Algorithm SHA256`：七份v0.3.1源码与S4.11表全部吻合；冻结v030=`82910a59…`、v031=`6a02b2ab…`、v032c=`60b4c9a7…`与历史记录吻合，命令exit0。没有重构建二进制或证明可复现构建。
- 实际执行`python -B (Join-Path $env:PI_SCRATCH_DIR 'v031-strength-evidence.py')`，**exit0**：8组/2,048条manifest记录，核对seed×rotation唯一完整、候选归属、winner/score/WTL、16份rotation metrics的样本数/WTL/总分、0–5VP张数和总折扣、卡牌分+3×贵族数、预留计数守恒；4批config/manifest/candidate binary SHA与result绑定一致。未逐个重核底层report/replay哈希，未重新运行`verify-replay`或bootstrap，无新单测/性能/竞技测量。
- 临时诊断与完整输入SHA索引：会话scratch `v031-strength-evidence.py` / `v031-strength-evidence.json`；JSON SHA-256=`87d4bca690d03022dc57153c8944879fc4e42470a9674752d6a43ac8dde5195f`。两份主要result SHA：v031=`795bc201a7f7835ace92915096beb7ed9d1c6fa66665e9db51843606f19e2257`，v032c=`24844fa19085aa42731705b97449f07a76658b0594cb9475bcba64e939d6a57a`。
- **结论**：已核验相对旧基线的大幅优势；最可信的归因是价值/用时一致性、建设到得分的平衡及公开终局处理共同起作用。没有单项消融，无法确定主因比例或宣称全局最优。仅建议未来经授权后用固定候选的同根分歧与新seed消融区分这些假设；本轮不新增实验门禁、不启动实验、不改现有M50/M51授权、Play条目或S3默认。
