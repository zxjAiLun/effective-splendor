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
