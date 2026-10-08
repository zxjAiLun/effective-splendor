# M54 Prism 持续 PPO：实现、工程验证与训练推进

Status: **阶段VI ACCEPTED_MODEL_ITERATION / Prism v0.1.1；历史阶段V NOT_ACCEPTED；阶段IV CLOSED_DEVELOPMENT_ONLY_WITH_BOUNDARY_FAILURE / FAILED_SHARED_POOL_BOUNDARY；阶段III COMPLETED_DEVELOPMENT_ONLY；风格验证未完成**
Baseline: `main@bcdaca7cb33c53cc43d5dcc9e92c07be3c1aaa57`，含并行工作树改动。
Owner/date: 用户授权研究，2026-09-30。

> 授权沿革：2026-09-30批准阶段I基础设施及阶段II8局工程smoke；2026-10-01授权修复、正常试训、cloud2固定对照与混池并已完成阶段III；随后再次要求“继续训练迭代吧”，阶段IV从最终c8完整状态启动新的有界续训，仅固定开发评测。下方旧“只设计/无实现”和旧性能外推保留为历史；风格训练与独立晋级验收未完成。

## 当前实现与实际进展摘要

- **中文阅读入口**：[Prism v0.1.1 本轮评测与版本结论](prism/prism-v0.1.1-evaluation-summary.md)，包含战绩、四项验收门槛、两次验收区别、本机/cloud2速度及部署状态。

- **2026-10-02 Stage VI最终结论**：ACCEPTED_MODEL_ITERATION / Prism v0.1.1；新5,120局/512双座块完成核验，共同锚点paired+8.7158pp，直接父代59.9121%，严格四门全过=true；旧负面gate保留，未训练或部署。

- **2026-10-02最终收口**：trial-v2八轮2,048训练局/54,802决策/434新steps及attempts全部提交，AdamW累计870；四模型各512固定开发局全部完成。c8 323–4–185/63.4765625%，相对本轮父代paired +8.984375pp、95%CI[+3.515625,+14.453125]pp；仅开发证据、NOT PROMOTED。最终索引校验exit0（1,080断言/54个hash文件），详见文末 Stage IV final closeout。共享池原暂停/历史不变gate仍FAILED；用户2026-10-02澄清曾亲手解除pause，属owner-reported人工操作，不再推断自动解除缺陷。以下进行中快照均保留为历史。

- **阶段IV历史进行中快照（2026-10-01T15:11:01Z，已由文末最终收口取代）**：trial-v2已提交前5轮，1,280局/34,331决策/272次新更新；第6轮采样中，总1,505完成局/40,321接纳决策，AdamW累计708=继承436+272。资源快照正常、stderr0；新父代/c1/c4固定各512局，得分54.4922%/56.3477%/58.3008%，c4−本轮父代配对+3.8086pp、95%CI[-1.5625,+9.1797]pp，尚未确认增强。c1/c4既有68边界parity通过，cloud2等待预设c8、不新增mixed/Elo。初始化、历史中断账与实际验证范围见文末Stage IV；尚未完成八轮或最终棋力收口。
- **阶段III历史最终执行更新（2026-10-01）**：原256×8局已提交，2,048唯一job/1,024双换座seed、55,123 learner决策/110,266 plies、436 optimizer steps及436 update attempts，八个batch仅消费一次。父代/c1/c4/c8同T=1共同seed固定开发各512局得分39.2578%/44.2383%/47.3633%/54.7852%；c8−父代配对+15.5273pp、95%CI[+9.7656,+21.2891]pp。四段混池各257局已完成，pool paused/controller complete；无独立holdout/选择校正或生产晋级。首轮至最后worker结束含中断wall13,741.930s；原24k保守CPU账与补充实测3,268.672 user CPU秒分列。最新证据以tracked trial result及文末收口为准，前述进行中快照保留为历史。
- 以下五项是阶段II结束时的工程/性能观察，不是当前阻塞；三处smoke锁和重复热路径问题已由阶段III修复。
- 已实现真实Arena调度→Prism学得分布抽样→learner轨迹→胜平负驱动PPO→下一轮新策略及暂停恢复。8局是**带2次真实优化器更新的端到端工程smoke**，不是合成单测，也不是棋力benchmark或有效规模试训；产生220条决策，两次更新都改变了Policy–Value参数。
- 既有日志实测：8局游戏进程合计6.5s（均0.8125s/局）；采样、接纳、更新等两段worker合计87.187s。提交文件时间间隔显示每轮4局采样/接纳19.70/22.83s，反向更新+提交2.42/2.35s；这些间隔含操作开销，不是函数级profiling。
- 主要扩量问题是重复model/optimizer重建、status每次重载并扫描整个提交历史、submit/seal重复复算行为，以及smoke launcher强制每轮4局/一次更新。它们是当前实现的工程负担，不是PPO必然要求；下一步应精简热路径并支持多seed/正常minibatch训练。
- PPO无需先筹备固定教师训练集：Prism v0.1/heuristic v0.3.1仅作对手，每轮用当前learner采样新轨迹再更新。当前局部采样/接纳速度外推256局约21–25min、512局42–49min、1024局84–98min；不是大批实测，历史扫描会使大run更慢，不能承诺线性扩展。后续先优化再实测正常训练批。
- 旧M39A棋力失败不是当前Prism PPO的成功概率依据；可复用的是玩家链/采样概率/数值复算经验。当前Prism已有训练过的策略和value；旧D2模型表示不同，critic重新初始化，旧结果不能替代当前实验。

## Problem and evidence

用户停止 Aran 后续迭代，保留代码、权重和负结果；未启动的 C 和最终验收不再执行。新主线是 Prism 持续 PPO，目标包括可恢复学习闭环、基建/干扰/冲分/均衡的可测差异，以及风格不同前提下的棋力损失约束。最初只研究的阶段已结束；当前已实现并完成8局真实更新工程smoke，详见首页摘要与阶段II收口。

### 已核对的资产和缺口

| 资产 | 源码/记录 | 可复用与限制 |
|---|---|---|
| 规则与玩家投影 | `crates/splendor-core/src/{state,observation,events}.rs` | `FullState::legal_actions/apply/is_terminal`、`observation(viewer)`、`visible_events(log, Audience::Player(p))`；终局通过 `GameResult`/事件/报告取得。不复制规则；当前源码没有名为 `terminal_result()` 的方法 |
| Arena 与 Agent SDK | `crates/splendor-arena/src/runner.rs`、`crates/splendor-agent/src/{policy,runtime}.rs` | 进程隔离、合法动作、玩家历史、报告与回放；已有 capped runner，终局/截断/故障分开。不是 Prism PPO 采样器 |
| Prism 编码/网络 | `crates/splendor-prism/src/{encoding,inference}.rs`、`training/prism/model.py` | 实体96、动作80、H128；两层关系残差、动作条件实体读取；保持 v0.1 编码和 Policy–Value，不引入 Aran 表示 |
| Prism 数据/导出 | `training/prism/{data,io,export}.py` | ragged collator、严格 schema/权重、原子单文件写入、RNG 隔离可复用；BC dataset 没有完整 PPO 轨迹协议；单文件原子写入不等于训练事务恢复 |
| 当前训练与在线策略 | `training/prism/train.py::loss_terms`、`crates/splendor-cli/src/prism_command.rs::choose_action` | 当前仍为所有教师动作 CE + 0.5 结果 BCE；在线取最大 logit。日志中的 softmax 概率不是实际 greedy 行为的抽样概率，不能拿来当 PPO old_logp |
| 历史 PPO | `training/m17_gpu/splendor_gpu/m39a_{collect,contract,train}.py`、`crates/splendor-cli/src/m39a_command.rs` | 可参考按 `(game_index, seat)` 分轨迹、clipped loss、驻留推理/收集调度。`m39a_model.py::encode_decisions`使用旧Observation/global/action-delta布局，sidecar缺Prism所需可见历史，不可直接接96/80，更不能继承旧训练/seed身份 |
| PyO3 环境 | [architecture](architecture.md) 中 PR-08 图和说明 | 仓库 crates 清单没有 `splendor-python`；该文档描述不是已实现接口证据。新建绑定属于后续扩量选项，不是本轮可调用资产 |

Prism 的 Rust 编码接口是 `encode(&Observation, &[VisibleEvent], &[Action]) -> Result<EncodedState, String>`。历史用于 Main 计数和盲预留层级，不能只传当前 Observation 冒充等价输入。模型批输入为 `entities[B,E,96]`、`actions[B,A,80]`、`targets[B,A]` 及两个 padding mask；E≤128、A≤4096，无目标为−1。细节以 [M51接口](m51-prism-implementation-contract.md) 为准。

### 旧轮工程经验与不能外推的棋力结论

- [M39A](m39a-arena-driven-policy-value-rl.md) 的正式方案为8轮×512局、每批4次 PPO pass；GAE γ=1、λ=0.95，clip=0.2，AdamW、LR余弦1e-4→1e-5。最终为 `M39A_NO_IMPROVEMENT`，不是 PPO 从未尝试过。历史实际记录4,097 attempts / 4,095 terminal / 1 truncated / 1 infrastructure abort；不能简写为4,096局均正常终局。
- M39A G1/G2受确定性不终局及缺块影响；G3联盟得分下降86.81 bps。M07完整块上的改善是诊断，不覆盖正式失败，也不证明 PPO 家族无效。
- [M40A](m40a-predictive-critic-warmstart-ab.md) 最终 `M40A_WARM_START_NO_EFFECT`；其实际事故显示 batch=1 采样与 batch=512 行为复算产生浮点差，2,145/23,748记录超原阈值。修复是按采样批形状复算，不是事后放宽阈值。
- `m39a_contract.py::centered_returns` 对截断使用分差 shaping，且两方不互为负数；不能把它当真实胜负复制。其 `gae_for_trajectory` 只支持中间零奖励、末步 terminal_return，新的风格奖励和截断协议须另写。
- 本轮没有重验这些历史赛事或重新计算旧置信区间；上述结果来自历史记录，源码用于核对机制。M39/M40保持关闭，不重启旧实验。
- **2026-09-30汇报更正**：保留历史失败事实，不把失败当作Prism PPO会失败或需要额外审批/防护的依据。源码核实M39A actor/trunk加载D2-v2，并非全部随机初始化；旧D2 value_loss_weight=0、critic换头新初始化，表示/起点/对手/奖励不同，不能与当前已训练Policy–Value的Prism作因果对照。

## Initial design

推荐 **先正确、再提速的同步分批 PPO + 独立风格策略**：

```text
固定轮次配置/预算/对手清单
    → 冻结行为快照 θ_k
    → Arena + Prism玩家适配器 → Python驻留采样服务（实际类别抽样）
    → 逐局完整报告/回放/sidecar → 规则重验与批次封口
    → 玩家自身决策链 → outcome/style优势 → 有界PPO更新
    → 原子提交 θ_(k+1) + optimizer/RNG/数据消费游标
    → 下轮新采样；按固定频率进入开发评测
    → 冻结唯一候选组 → 独立验收（另行授权）
```

“持续”指可无限接续这一闭环的工程能力，不是无限预算，也不是边更新权重边让同一局使用不同版本。首版禁止异步旧策略队列、经验回放重复训练和多 learner 同时写同一状态。风格是训练目标的一部分，不是输出后处理。

## 初始研究范围（历史，当前实现见首页摘要）

- 最初研究期仅做设计/源码核对；随后阶段I实现PPO代码，阶段II已运行8局、登记4个seed并完成2次真实模型更新。原“本轮仅设计/不运行更新”边界已被后续授权与实际执行取代，不是当前状态。
- 不改冻结 Prism v0.1 配置、权重、首训数据和历史竞技结论；新 PPO 独立配置、optimizer、目录和身份，不能借用 v0.1 `--resume` 改数据/LR继续。
- 不继续 Aran C/最终验收，不删除历史模型，不改规则、生产默认、UI/registry、服务或现有对战池；不提交、推送或发布。
- 首个运行合同只接受经典双人；接口按玩家身份组织，为多人留边界，不宣称已支持多人训练。
- **禁用推理期 logit 偏置、动作类别加分、概率乘权、人工重排及其改名版本。** 合法动作 mask、从学得策略正常抽样不在禁令内。
- 新主线无 teacher CE、搜索动作模仿、赢家动作克隆；v0.3.1可作对手/评测锚点，不作新动作标签 oracle。

## Contracts and invariants

### 1. 信息边界和组件分工

遵守 [ADR0001](adr/0001-information-boundary.md)；Policy和所有Critic仅看到决策当时玩家可见的信息。没有全知critic。对手暗牌、牌堆顺序、seed、未来补牌、终局标签、模型/来源hash不能成为特征。

| 组件（拟议） | 输入/输出及信任边界 |
|---|---|
| coordinator | 管理预算、调度、版本、seed和事务；不把控制元数据拼进网络 |
| Rust Prism rollout adapter | 从 `DecisionContext` 的 actor Observation、截止该次决策的 visible_history、原始合法动作序列调用唯一Rust编码器；向本地推理服务发送编码和关联元数据；返回语义动作。新独立入口，不改变 `agent-prism` 当前 greedy 默认 |
| Python行为服务 | 加载不可变快照；接收有界96/80/targets，padding mask由collator产生；只给模型喂特征白名单。输出实际采样索引、所选logp、outcome value、必要style value及完整分布审计数据 |
| materializer/auditor | 比对实际执行动作、请求/座次、回放、玩家投影、编码和行为版本，形成不可变训练批。可访问裁判回放用于审计；先按当时玩家投影，绝不使用 `Audience::PostGame` 重建训练输入 |
| learner | 只读合格的玩家数据和目标；provenance与特征分结构存储，不接受任意dict自动flatten。Policy只更新本 learner 真正产生的动作 |
| evaluator | 固定模型/对手/模式/seed块；输出棋力、风格、故障与资源统计，不向learner泄漏验收集 |

回放可以含裁判seed/hash，保存在本地审计区；推理进程不接收裁判回放路径或完整状态。训练目标可使用真实终局结果，以及该玩家在后续实际观察到的公开事件形成延迟奖励；这些是标签，不得回填到早期 Observation 或网络输入。

### 2. 行为策略与 rollout 数据协议

拟议新协议 `prism-rollout-v1`，不是给 `prism-dataset-v1` 加几列后继续使用旧CE训练器。

- **批头**：run_id、cycle_id、behavior checkpoint/export SHA、代码/规则/schema身份、runtime、sampling定义、对手池清单hash、奖励定义hash、调度清单hash、预算及批次内容hash。
- **每局**：唯一job_id、attempt_id、seat→model身份、terminal/truncated/abort状态、真实GameResult（仅terminal）、报告/回放/sidecar校验值。环境seed仅裁判/调度审计保存。
- **每决策**：game_id、actor、ply/request、本玩家decision_index与Main计数、phase、behavior_id、learner_eligible；玩家输入/历史前缀引用、编码、完整有序合法动作与chosen索引/语义动作；实际 `old_logp`、`old_v_outcome`、`old_v_style`；采样RNG计数器、推理批形状；后续同玩家指针、各reward分量、terminated/truncated及边界原因。
- **存储**：复用offset ragged布局和padding校验，但轨迹/奖励/行为数据分新的明确数组；保留可审计源文件。离线重建的编码须与采样时编码一致。严格检查动作顺序、targets重映射、唯一选中动作、有限数值、链连续、重复/缺失请求。
- **实际采样**：raw logits 上 `Categorical(softmax(logits))`，固定 T=1；不使用top-k、epsilon混合或风格温度。记录的logp来自真正的抽样分布和同次forward，不是事后给greedy动作补softmax概率。
- 首版行为服务采用singleton forward；并行Arena可排队但不按到达时机动态改变推理批形状。未来批量化先独立做parity、抽样重现及数值阈值实验，再版本化批准。
- 动作抽样RNG与环境seed独立；按预先分配的job/seat/decision计数确定，不能依赖worker编号或完成顺序。记录RNG算法与状态；该计数/seed不是网络输入。
- 对手动作不能因胜利或“看起来好”进入本learner PPO样本。双方恰好都受同一冻结快照控制时，可收双方轨迹，但分别计算回报，且统计上仍属于同一局/seed块。
- 审计复算按原snapshot/runtime/批形状完成；差异超预先规定的logp/value阈值即停止，不能覆写旧概率掩盖漂移。行为数值阈值不能直接套用logit parity的1e-4。

### 3. 玩家自身时间轴、终局与优势

#### 已核对的规则事实

`state.rs::after_purchase` 在多个贵族可选时进入 `ChooseNoble`，不推进玩家；`apply_choose_noble` 才选择贵族、检查终局并推进。`Action::is_main_action` 排除贵族选择。达到15分是终局触发，不一定立即结束；引擎完成当前轮剩余座位。`TerminalReason::Stalemate` 也是规则真实终局，不等于runner超时或ply cap。

按 `(game_id, actor)` 排序得到本玩家时刻 `i=0..T_p-1`。`next(i)` 是同玩家下一决策，可能紧接着选择贵族，也可能跨越一个或多个其他玩家行动。对手行动改变下一状态，但不成为本玩家Policy训练行。若对手行动结束整局，真实结果仍送到每个learner玩家各自的最后一条决策；不能只给最后行动者奖励。

双人outcome定义为 `u_p=1/0.5/0`（胜/真实平/负），按引擎ranks判定而非仅比较分数；同分少购卡者可能获胜。非终局中间outcome reward=0，最后决策reward=`u_p`。Value表示期望计半平得分，不应称为已校准的“纯胜概率”。

对每个奖励分量 `h ∈ {outcome, style}`：

```text
δ_i^h = r_i^h + γ_i * b_i * V_old^h(next(i)) - V_old^h(i)
A_i^h = δ_i^h + γ_i * λ_i^h * c_i * A_next(i)^h
```

- 完整非终局连接：`b=c=1`；真实终局：`b=c=0`。
- 合法时间窗口切断：仅在已取得同玩家下一决策Observation时，可 `b=1,c=0` 自举，不能跨未采集片段递归GAE。首版完整局模式不启用此分支。
- 建议首版 `γ=1`，与未折扣真实结果一致；`λ`按本玩家**决策**计算，包括ChooseNoble，取值待批准。这是明确的trace粒度，不是按全局ply折扣。若将来改按Main回合折扣，必须存真实间隔，内部贵族决策不得被错误额外折扣。
- 不直接使用下一ply对手的Value，不无条件翻号。不同玩家各自的信息集不同，即使双人零和也不能把对手估值强行当作本玩家精确补值。
- 多人扩展建议使用自己的效用向量分量；候选为按真实ranks计算的平均两两得分 `sum_{q!=p}(1[rank_p<rank_q] + 0.5*1[rank_p==rank_q])/(n-1)`，不是自动等同“冠军概率”。多人目标/座次/评测另需冻结；首版收到n≠2应显式拒绝，而非默用双人公式。

#### 三种停止状态

1. **规则terminal**：使用真实GameResult，不bootstrap；Stalemate也遵循真实排名。
2. **ply cap/时间窗口truncated**：无真实胜平负。首版把确定性cap作为本批停止原因，保留完整/部分产物、不提交该批更新；不得静默删除该局换seed，或把cap比分当平/负奖励。后续要支持碎片rollout，须另有同玩家决策边界自举协议；不能在任意全局cap时对非行动玩家的临时Observation估值后冒称训练分布一致。
3. **基础设施abort/用户强停**：无比赛结果。按恢复合同保留尝试证据，只能对未完成job进行有界同身份恢复。正常暂停不结束棋局、不制造truncated标签。

完整局首版牺牲长局容错换取可审计性；不终局一旦出现，设计/预算须重新评审，不能靠丢弃难局获得“训练健康”。

### 4. PPO learner 和价值语义

- 新learner从冻结Prism v0.1权重暖启动，**新建**optimizer；旧BC优化器/20epoch计划不继承。每轮先收集θ_k的整批轨迹，old值/优势固定，再进行有限passes；完成后θ_(k+1)必须用新数据。
- Policy loss：`-mean(min(ratio*A, clip(ratio,1-ε,1+ε)*A))`，`ratio=exp(logπ_θ(a)-old_logp)`。无CE动作标签，无winner筛选；合法动作只有一个时Policy梯度自然为零，不能产生NaN entropy。
- outcome head沿用sigmoid；用新鲜真实 `u_p` 的BCE训练，保持其期望得分语义。GAE只是Policy信用分配方法，不把可能超出[0,1]的TD/GAE目标直接塞入BCE。
- 风格分支增加**训练专用独立style value head**，线性输出估计有界整局效用（输出本身不强制有界）；建议首版用实际M_z的MC目标训练MSE，style优势取γ=λ_style=1时的`M_z−V_old_style`。outcome的λ仍独立待批。累计风格指标依赖历史，当前Prism压缩表示未必是其充分状态；先用MC减少style自举偏差，但信用分配噪声仍在，不把该表示宣称为完整Markov状态。不得把outcome head改成shaped总效用后仍宣称预测棋力。
- `A=A_outcome+β_z*A_style`。奖励分量先按冻结的有界尺度定义，再合成；如做advantage标准化，在合成后按同一learner整批处理一次，记录mean/std，不逐minibatch或逐分量事后改尺度。不能通过归一化把β含义冲掉。
- 总loss为Policy + outcome-value项 + style-value项 − entropy项；共享主干意味着多任务梯度可能冲突，单独value头不是数学隔离保证。所有权重、LR、clip、λ、passes、minibatch、grad clip均须在后续配置中固定。
- β=0的均衡learner关闭style目标/头的梯度；其他策略各自有optimizer。训练专用头放独立checkpoint命名空间，导出时显式只取原Prism32键；原strict loader保持不接受未知字段。导出清单附风格定义、父代、采样模式和哈希，不向模型偷偷增加特征。
- 训练健康：finite loss/梯度、更新前ratio≈1、old/new KL、clip fraction、grad norm、value Brier/BCE/分箱校准、分阶段/座次统计、合法动作数分层entropy（n=1单列，n>1另报H/log n）。KL阈值只触发本批提前结束剩余passes或停止，不容许静默改目标/重置学习率刷过。
- 对手池变化会改变Value分布；自我对弈双方平均约50%、loss下降或变化池Elo上升均不是棋力增强证据。无此轮成功率保证。

### 5. 持续运行、预算与事务恢复

拟议产物全部位于新的 ignored `local-artifacts/prism/ppo/<run_id>/`；本轮不创建该运行目录。新配置/result应属于单独tracked benchmark合同，不能改M51结果。

```text
INIT → SNAPSHOT → COLLECTING → SEALED → UPDATING → COMMITTED → 下一轮
                         ↘ PAUSED / FAILED（保留证据）
```

| 边界 | 必须持久化的状态 | 恢复/重复处理规则 |
|---|---|---|
| INIT/SNAPSHOT | 父权重、配置/源码/runtime、optimizer初态、行为快照、完整job调度、对手清单、独立RNG状态 | 同run恢复必须全匹配；改奖励/配置/对手配比为新轮新身份，不是resume |
| COLLECTING | 每job不可变完成包（报告、replay、sidecar、hash）、尝试日志、完成清单 | 已验证完成job不重赛；缺失/中断job以相同seed、座次、行为快照、对手和action-RNG重启。未知孤儿包先校验job身份再接纳，不能双计 |
| SEALED | 固定顺序训练批、全量join/合法性审计、内容hash、trajectory索引 | 封口后禁止增删；恢复只读该批，不重新采样覆盖；truncated/行为漂移等不能被摘要忽略 |
| UPDATING | model、optimizer、scheduler状态或固定LR位置、Python/NumPy/Torch/CUDA RNG、数据排列、epoch/minibatch游标、global_step、advantage统计、active_batch与消费进度 | 只在完整optimizer-step边界提交；未完成梯度累积回到上次已提交step重算，不保存半份grad当完成。optimizer加载后核验计划LR，避免旧param_group覆盖 |
| COMMITTED | 新checkpoint/导出、对应校验、来源批次、已消费step范围、下一轮指针、budget ledger、对手池更新版本 | “模型更新”和“数据已消费”由同一提交记录宣布；无提交记录的文件是候选/孤儿，不凭文件名latest推断完成；已消费批不能再作为新cycle训练 |

实现建议：不可变文件先写同目录临时文件、flush/fsync、完成hash验证，再原子发布一个带父提交hash的commit manifest；用单writer锁保护run。checkpoint可作为完整step快照，提交记录引用它，恢复沿校验通过的提交链读取。旧 `io.py::_atomic_write` 是基础工具，不提供多文件事务。文件系统/Windows断电持久性边界需实测，不能把进程崩溃恢复宣称成任意断电零丢失。

- **暂停**：正常暂停停止派发新job，让在途局完成；learner到下一完整step提交后停。强制退出最多回滚未提交计算；不丢已提交数据/optimizer进度。首版不承诺棋局中间内存状态快照，未完成局可重启。
- **exactly-once含义**：持久化逻辑更新只提交一次；崩溃前未提交的forward/backward/对局可能物理重算。所有attempt和消耗仍进入预算，不把恢复成本藏掉。
- **失败而非猜测**：哈希不符、未知schema、断裂提交链、重复job身份冲突、行为不一致立即停；不能“尽量加载”另一个权重继续。是否回退到已知父提交需写恢复记录，不覆盖失败产物。
- **预算**：分别限制总attempt/完整局/learner决策、每批最大passes/optimizer steps、CPU/GPU时间、wall time、并发、磁盘与重试次数。派发前预留在途job的上限资源，软暂停须早于硬上限；硬上限强停按abort处理并保留预算记录。先耗尽者暂停，不自动加预算、换seed、丢长局或缩小batch继续。
- **确定性**：固定runtime/硬件和数据顺序下测试恢复一致性；跨GPU/库版本仅能另立容差/新运行身份。异步完成顺序不得改变job选择/抽样或训练排列。首次用singleton行为推理、同步更新，牺牲一些吞吐换简单可复核性。
- **资源选择**：现有8GB级GPU资料只够提出有界ragged batch/累积、CPU Arena和独立推理服务的方案，未测本闭环显存或局/秒。不用v0.1 Rust延迟或并行批次摊销时间外推PPO吞吐。性能不足才进入PyO3/原生batch adapter研究，不先重写裁判。

### 6. 对手池与非平稳性控制

训练池拟包含：冻结v0.1、冻结v0.3.1锚点、当前learner冻结副本、有限历史快照；风格阶段可加入已冻结的其他风格快照。配比、容量、更新时间及淘汰规则在每轮之前固定，整局/整批不热更新。任何历史Agent入池不意味着继续它的训练，Aran也无自动新赛事授权。

只在COMMITTED边界根据预先规则新增快照；失败/退化快照保留归档而不冒充champion。均衡基准B在同一风格cohort内冻结，不能让参照随风格训练一起漂移。开发对手集合固定且与训练池统计分开；独立验收的对手身份、采样模式和种子在候选组冻结后锁定。

## Learned styles and strength constraints

### 7. 推荐独立策略，条件策略作为后续选项

首组拟为 **均衡B、基建E、干扰D、冲分R**。先使同一闭环具备outcome-only训练能力，再从同一冻结B分支训练E/D/R；不是先把风格研究排除出本方案。B若未通过自身棋力门槛，风格实验不自动以退化B作为“均衡强度”放宽验收。

| 路线 | 取舍 |
|---|---|
| 独立完整Prism策略（首选） | 96/80输入与在线模型结构不变；每风格有独立optimizer/快照，容易测量与回滚。需多份预算，不保证学得不同 |
| 共享主干 + adapter | 节省部分参数，但共享更新可能破坏旧风格；需明确冻结/隔离梯度及新导出合同，首版不捆绑 |
| 条件化Policy/Value | 风格ID或强度作为受控偏好输入，必须训练覆盖、Value也条件化；新schema和跨语言导出。只加ID配相同胜负目标可能完全忽略ID，连续插值未训练也不保证有效 |

首版风格强度通过**训练得到的离散候选权重**表达，而非推理温度/动作概率调整。候选数量和β档位需事先批准；不无限扫描到出现一份好结果。若将来做连续条件控制，需独立验证每个区间的行为及棋力，不靠混合两份logits制造风格。

### 8. 可测指标及训练奖励的候选定义

所有行为指标按**模型身份**归并并拆座次/对手/阶段；不得把换座后的P0/P1混合直接当模型。Main回合和包含ChooseNoble的decision/ply分母分开，沿用 [统一指标标准](unified-match-metrics-standard.md) 并补协议字段。

先冻结早期窗口K、兑现观察窗H、cap/归一化常数和指标方向，再训练。下列是**候选定义，不是已批准权重或已实现统计器**：

| 风格 | 主方向/可见指标 | 可用于训练的有界效用 | 防刷与解释边界 |
|---|---|---|---|
| 均衡B | outcome-only参照；同时报告其自然行为向量 | β=0，无人工风格奖励 | “均衡”是参考角色，不保证三个指标都恰好居中，更不宣称最优 |
| 基建E | 前K个自身Main的永久折扣曲线；早期购卡在后H个Main购卡中的费用减免使用；低VP投资兑现情况 | 对早期新增bonus在后续**真实己方购卡**中的可用减免计数，逐牌/逐局封顶，再缩放[0,1] | 不奖励所有0VP卡/购卡数量。可按同色bonus获得序号q，在后买卡该色原费用≥q时记一单位费用减免适用；这是结构性折扣使用，不是“若没买该牌就会少花多少token”的因果估计 |
| 干扰D | 有公开阻断机会时的目标移除率；对下一个行动对手的可购高VP公开目标压制；机会数/兑现成本 | 动作前以对手公开tokens/bonuses确定其可购市场卡；己方buy/reserve移除其中目标时，以旧市场中最佳可立即购卡VP的下降量计分，逐目标去重/逐局封顶 | 忽略未知手牌/未来补牌；不奖励盲预留或所有reserve。旧市场减去目标的差只是公开机会压制代理；真实补牌可能反向送牌，必须另报下一公开局面机会恢复及己方成本，不能称“有效阻止对手获胜” |
| 冲分R | 固定自身Main窗口的分数曲线、达分时点、得分购卡与贵族分解 | 前K个自身Main结束后 `min(score,15)/15` 的均值（固定K分母），形成有界早期得分AUC | 早终局用终局分数补足只用于统计/终局效用，不生成虚假动作；同分少购卡规则照常。防止只挑极短败局/牺牲胜负刷VP，必须同时过棋力门槛 |

约定补充：

- ChooseNoble属于同一Main的后续决策，其奖励/计分只入账一次；自动领取与主动选择用相同事件语义。Main计数由历史真实动作构造。
- 首个风格实现建议将上述有界**整局效用M_z**放到该玩家最后决策，style中间reward=0，减少重复奖励风险；GAE仍按玩家链传播。将来若改密集增量reward，要证明与定义的整局效用一致或明确承认目标改变，不随意加正奖励循环。
- 基建未到兑现窗口、被对手结束、冲分未达目标等失败也保留；记录右删失/未兑现比例，不能只对存活到K或胜局计算主报告。窗口外不补未知事件。
- 干扰机会由**当前**可见信息确定；后续公开事件只作为延迟诊断/奖励，不能回填当前输入。无机会局的条件比率为NA，另报覆盖率和逐局无条件效用，不能把NA删掉制造高干扰率。
- 主验收至少含一个**未直接进入reward**的相关行为指标和反刷指标；不能仅以训练奖励升高证明“风格成功”。0VP购卡数、预留数量、终局未买回率单独都不足以解释意图或棋力。
- 这些目标是人工设计的**训练期偏好**，不是自动产生人格，也不保证潜在最优策略不变。仅用潜势差且保持最优策略不变的shaping，也不能保证长期形成四种不同最优风格。

### 9. 风格明显不同如何判定

风格目标、差异阈值和测试分布先固定。至少需要两个视角：

1. **固定玩家视角局面面板**：来自与训练隔离且来源合法的局面/历史；同一合法动作集上比较模型原始分布、动作特征期望。无需实际选择新的比赛动作即可做静态分析，但该面板/评测本轮也未生成或运行。不能用seed/模型名/结果标签当分类特征。
2. **完整对局行为**：同对手、同seed块双换座，报告前述指标、卡/贵族/预留结构、资源与回合数据；按对手、阶段和座次分层。静态面板可减少状态访问差异，实战则验证风格在自身轨迹中确实存在，两者不能互相替代。

E/D/R各自相对B须达到预定主方向差异，且风格间行为向量的预定距离达到下限；不能只“相对B不同”就称彼此不同。距离可采用固定参考尺度的向量距离，零方差维使用预定绝对尺度或剔除规则，不允许看结果后挑轴。差异置信下界须超过**实际有意义**的最小差异Δ_style，不只是p<0.05。辅助分类器可作诊断，但高分类准确率不代替棋力或命名风格定义。

风格阈值、参考尺度、K/H等本轮未冻结；后续可先在获批的开发数据校准，随后锁定并在独立面板/比赛验收，不在同一数据上既挑定义又报成功。

### 10. 棋力损失约束与最终决策

训练标量目标拟为 `J_z = E[u] + β_z E[M_z]`。β只控制探索折中，**不提供非劣保证**。推荐以预定少量β/检查点形成候选，然后用固定开发约束选型；不先引入未验证的复杂多智能体拉格朗日控制器。后续若用dual multiplier，其更新只能用独立开发估计、完整checkpoint保存，并仍需最终验收。

设 `S(X,Y)` 为同采样规则下对Y的计半平得分率，B为该cohort冻结均衡参考，A为固定外部对手集合。三个层次都要报告：

- **B自身强度门**：对冻结父代/外部锚点按预先规定的非劣或提升门槛验收。不能仅因B比某风格强就称B已改进。
- **共同对手非劣**：对每风格z，`D_z = Σ_a w_a[S(z,a)-S(B,a)]`。单侧置信下界≥`−δ_pool`；关键对手另设`δ_anchor`，防止平均掩盖一个方向崩溃。权重事先固定。
- **直接对战和跨风格**：至少检验 `S(z,B) ≥ 0.5−δ_B`，并对E/D/R两两双方检验 `S(z,z') ≥ 0.5−δ_cross` 的置信下界。完整4×4矩阵拆座次；如另比较 `S(z,z')−S(B,z')`，其paired差也须预定而非事后新增门槛。

跨风格容差越小，要求越苛刻；循环克制可能使整组无可行解。不能把“总体平均相近”称为每一对都等强，也不能强行保证四风格同时满足。容差不是默认沿用Aran的3pp，所有δ均待用户确认。

统计方案：以完整seed双换座块为单位配对bootstrap；比较z与B对相同锚点时，重采样共享块上的**差值**，不是比较两条独立CI是否重叠。同seed只是共同随机数设计，策略改变后补牌路径可能不同，不保证相同经历。随机策略的action-RNG/重复次数及其嵌套分块事先固定。多个风格/对手/行为门槛使用预定family的单侧同时置信界（例如Bonferroni分配α），不能逐项95%后宣称整组95%。

开发和独立验收严格分离：开发可按预定频率比较并停训，但不得反复窥看验收seed；最终冻结完整候选组、奖励、sampling、对手和门槛，做一次批准规模的验收。样本量按δ、Δ_style和配对方差/多重比较功效设计，不能假设256局或任意2,000局必然足够。CI跨50%不证明等强；非劣界未达即不满足该门，区分明显退化与精度不足。

**采样模式也属于模型身份**：首选训练和主要风格验收都使用学得分布T=1；greedy仅作为另行预定的诊断。现有v0.1竞技基线是greedy，不能直接当其sampling模式基线。若产品要greedy部署，必须重新在greedy模式验证风格/棋力，不能比赛时临时挑更有利模式。

| 最终证据 | 判定 |
|---|---|
| 工程失败/身份不符/样本缺块 | INVALID / STOP，不能报风格或棋力通过 |
| 工程通过，但无有意义风格差异 | STYLE_NOT_ESTABLISHED，即使棋力强也不满足本用户目标 |
| 风格通过，但任一规定非劣门未过 | NOT PROMOTED；保留风格–棋力折中和不确定性，不自动放宽δ |
| 风格、棋力、工程三类门均通过 | 才可向用户提出该候选组验收；不自动发布/改生产 |

## Implementation plan

以下是**待授权实施顺序**，不是本轮已实现功能：

| 阶段 | 拟交付 | 放行条件 |
|---|---|---|
| I. 接口/恢复基础设施 | 新 `training/prism/ppo/` 的contract、sampler service、learner、checkpoint/coordinator；独立Rust rollout入口；审计器 | 只用合成/既有玩家视角fixtures做测试；不动v0.1默认。实现授权须说明是否允许受控optimizer单测 |
| II. 环境集成验证 | 新身份Arena小批采样、行为复算、导出parity、fault injection | 单独批准极小工程对局预算；这是工程smoke，不是竞技提升 |
| III. 持续均衡PPO | 若干有限cycle、暂停/恢复、固定开发池和父代对照 | 数据/更新/资源预算、参数/seed/停止条件提前冻结；失败不自动进入风格训练 |
| IV. 风格cohort | 同B父代的E/D/R训练、离散强度候选、未入reward诊断指标 | 风格定义/β档位/各风格预算公平且公开；不扩大候选扫描 |
| V. 独立验收 | 冻结4策略与共同锚点、换座全矩阵、风格和非劣同时门 | 明确δ/Δ_style/置信方法/样本量；通过后另请用户决定是否部署 |

验收基础用例清单（**均待实现/运行**）：

- 玩家投影反例：只改对手暗牌/未见牌堆、保持当前合法信息集，编码与各头不变；未来事件/结果不影响过去输入；hash/seed永不进入张量。
- 轨迹手算：交替两人、同玩家Buy→ChooseNoble、对手结束游戏、自动贵族、强制Pass/Stalemate、分数相同但购卡数不同；`λ=1,γ=1`下完整终局outcome优势应为`u−V_old`。另有三人身份链反例证明不使用翻号，但首版运行拒绝三人。
- 数据/采样：合法动作重排与targets映射、单合法动作、NaN/重复/越界、错误行为hash、对手行混入、重试重复job、冻结快照复算、抽样重现与统计频率。
- PPO：更新前ratio≈1，正/负优势方向、clip边界、padding屏蔽、无teacher CE、outcome/style头语义、梯度与实际权重变化、optimizer加载后的LR一致。
- 截断/故障：cap不是draw/loss，不拼下一ply对手Value；缺包、半sidecar、损坏hash使批次不能封口；terminal无bootstrap。
- 恢复：在完成包落盘前后、封口前后、反向/optimizer.step前后、checkpoint写入/commit发布前后强制故障；与不中断同配置运行比较动作/已消费集合/步骤/RNG/模型；提交不双计。
- 风格反刷：只买无兑现0VP、无机会reserve、重复计贵族、刷回合/短败局、只统计胜局、补牌抵消阻断；标签采样/风格身份错配；所有失败局留在报告。
- 跨语言导出：保留M51边界parity并增加新learner导出/采样数据；不把style训练头混入旧32键JSON。性能单独测量，不以smoke推出吞吐结论。

## Iteration log

- 2026-09-30：用户仅授权研究；Aran C/最终验收取消后续执行；Prism持续PPO与可测风格同时进入新研究主线，logit风格层禁止。
- 初始骨架只列目标；一个只读explorer定位旧PPO/环境资产，parent核对Prism与核心回合源码。没有独立方案审阅、没有实验。
- 只读探索给出的 `event.rs`/`terminal_result()` 导航与当前源码不符；parent复核后改为 `events.rs`、`observation.rs` 和实际GameResult出口。曾读不存在的 `transition.rs` 失败，已按实际文件定位恢复，不作为外部阻塞。
- 保留M39/M40负结果，将“现有PyO3”修正为未实现规划；不照搬旧sidecar、截断分差回报和singleton/batch混用。
- 收敛为同步完整局首版、事务级恢复、独立风格策略；条件模型/PyO3/碎片rollout后置。对风格只加ID、只看reward、均值掩盖克制和无限试权重均设明确边界。

## Final implementation

**无PPO实现、无新模型或实验。** 本轮交付为本设计、M50停止追加记录、M51导航和local-only handoff。源码/规则/历史配置与权重不因本轮改变。上述新目录、schema、命令入口、统计器、恢复机制及门禁测试均为待实现合同建议。

## Validation and evidence

本轮已直接读取Prism编码/模型合同、训练loss/greedy入口、core回合/投影/终局、旧PPO GAE/截断源码与M39/M40记录；通过Glob核对crates列表。当前分支`main`、HEAD如页首；工作树存在大量并行改动，不能归为本轮产物。

- 实际命令 `git branch --show-current`、`git rev-parse HEAD`、`git status --short` 已执行；`git check-ignore -v handoff.md local-artifacts/` exit0，分别命中 `.gitignore` 的local-only规则。
- Aran当前champion记录读取自 `local-artifacts/aran-v031-goal-v1/champion.json`，指向B/97维/epoch7；本轮未据此宣称重新哈希或重验全部模型/对局。
- 实跑 `python -B "$env:PI_SCRATCH_DIR\m54_document_check.py"` **exit0**：检查完整M54、M50停止追加节、M51导航追加节的尾空白/代码围栏，10个相对链接与锚点，四份文档编辑标记、handoff当前状态、23份源码/配置/seed登记文件的hash，关键产物存在及未暂存handoff。没有执行模型。
- 检查脚本及证据位于本会话scratch `C:\Users\81489\.pi-desktop\scratch\0a801c36-dc48-44ad-8fd7-4e03b17cffad\`：`m54_document_check.py`、`m54-source-inventory.json`、`m54-document-check.json`。源码清单保存完整SHA-256；重复运行检查收口期间的稳定性，不冒充任务开始前全工作树字节快照。证据JSON随最后复查更新文档hash。
- `git diff --check -- docs/m54-prism-continuous-ppo-design.md docs/m50-competitive-replay-policy-value.md docs/m51-prism-model-line.md` **exit0**；新文件另由上述直接文本检查覆盖。此次全仓 `git diff --check` **exit0**，只有LF/CRLF提示；这不抹去先前其他轮次记录的并行文档尾空白失败，也不表示本轮修复了那些文件。
- 没有训练、采样、比赛、构建、安装或新的规则回放验证；M51既有测试和竞技结果不是本轮新增验证。

## Result and decision

**研究方案已形成，状态DESIGNED / PROPOSED；棋力改善、风格可分性与恢复可靠性均未验证。** 本轮没有外部研究阻塞。选定推荐路线不等于用户已经批准实现/算力，更不等于PPO必然成功。

Aran停止后续迭代记录见 [M50停止点](m50-competitive-replay-policy-value.md#aran-iteration-stop-20260930)。Prism v0.1保持冻结历史基线；其139–2–115、54.6875%计半平得分率和95%配对CI[48.4375%,60.546875%]不证明已经显著强于v0.3.1，也不替代未来PPO对照。

## Known limitations

- 真实结果稀疏、对手非平稳与reward hacking风险仍在；基础设施正确不保证探索有用。完整局停止门对长局苛刻，尚未测可行性。
- 公开阻断代理不是对手意图/损失的因果标签；永久折扣使用和冲分指标也只能说明定义下的行为。所有风格差异都需真实独立数据验证。
- 四风格同时显著不同且两两仅损失很小棋力可能不可达；若不可行，保留Pareto折中/负结果，交由用户决定是否改目标，不自动降低门槛。
- 未测PPO显存、吞吐、精确恢复、概率跨语言误差；没有已经可运行的Prism PPO命令。仓库规划图中的PyO3接口尚不存在。

## Next authorized gate

本轮授权仅到研究文档。下一轮可请求**仅实施阶段I基础设施和测试**，不捆绑正式训练；再单独批准工程采样与后续训练。

后续开始任何正式运行前必须确认：

1. 实施/工程测试范围，是否允许合成fixture上的optimizer单测与少量集成对局；
2. 总及分阶段/分风格的训练局数、决策数、updates、wall/GPU时间、重试/存储预算；
3. LR、clip、γ/λ、passes、minibatch、loss权重、pool配比/更新频率及选择/停止规则；
4. 风格K/H/cap、主/辅助/反刷指标、β档位、Δ_style与最多候选数；
5. 相对B、共同对手、跨风格的δ容差，以及同时置信方法、开发/验收样本量和sampling模式。

**这些参数现在均未形成可运行的冻结配置；不沿用说明性LR1e-4、20×200局或Aran的3pp作为默认授权。**

## Stage I implementation round — 2026-09-30

Status: **IMPLEMENTED / VERIFIED（限定阶段I工程门禁）**；baseline仍为页首HEAD，保留并行脏工作树。未宣称整个持续PPO/风格项目完成。

### Scope and acceptance gates

- 新增独立Prism PPO Python协议/采样服务/learner/事务恢复与coordinator，以及Rust玩家视角采样入口和严格回放审计；不改现有greedy与BC语义。
- 仅使用合成/既有fixtures运行模型与优化器工程测试；可编译隔离测试二进制，不覆盖共享生产release binary。无真实新对局/训练数据采集、无正式训练或新seed。
- 工程门禁：严格96/80输入、真实抽样logp、行为身份/轨迹join、终局与截断分离、玩家链优势、clipped PPO/双value语义、导出旧32键、暂停恢复不重消费、原子提交故障注入、旧Prism回归。
- 风格本轮实现数据/独立head与loss接口，具体K/H、reward指标提取及β/棋力门槛仍待后续冻结；不得把合成style目标测试称为学得真实风格。
- 参数由显式配置给出，不产生正式benchmark config或自动默认预算。后续Arena集成采样与竞技验收需另授权。

### Implementation log

- 启动前重读M54、M51接口和ADR0001，核对main/HEAD/worktree/ignore规则。Prism旧模块保持隔离，新增入口不接管Aran/UI/服务。
- Python首轮专项为61通过/1失败：混合JSON targets中的bool经NumPy变成整数；已在新协议入口先做严格类型检查，旧collator不改。最终回归通过，初次失败日志保留。
- Rust主体由限定范围fixer起草；会话恢复后旧委派编号不可查询，parent直接接手。一次可选只读Python审查也未收到报告；**不记录为已完成独立审阅，不重启第二轮审查**。
- Parent新增合法sidecar往返用例，复现5通过/1失败：f32序列化再转通用JSON后数值表示不逐字相同。修复为递归字段结构/类型校验，真实编码仍与规则重建的f32逐项比较；重复键在通用Value吞掉之前拒绝。合法往返、字段篡改与完整既有回放审计均已通过。
- 存储文件一次行号编辑误插（引号与方法位置）在差异检查中发现，重新读取后修复；后续AST及全部测试通过。没有删除失败日志或改参数掩盖失败。
- 修复/补强超大JSON整数、审计读入上限/超时、bool attempt、批次与快照身份、旧概率分布及初始化写入竞争；CPU测试通过。未改棋力/风格阈值，未运行新对局。

### Final implementation and deliberate limits

- 新增 `training/prism/ppo/`：严格协议、独立PPOModel/style head、不可变Behavior、loopback服务、玩家链GAE和clipped learner、内容寻址CommitStore、Run协调器、审计包装器及CLI。模块/命令/配置详情见[使用说明](../training/prism/ppo/README.md)。新Rust入口 `agent-prism-ppo` / `prism-ppo-audit`，仅在CLI main增量接线。
- Pipeline基本单元：显式配置/作业清单→冻结快照→attempt登记→既有完整回放与sidecar的严格审计接纳→批次封口→有限passes→每optimizer-step与RNG/消费游标原子提交→下一批新数据。CLI不会生成环境seed或启动Arena进程；这不是已经部署的自动自对弈训练服务。
- 完整自身玩家链包括ChooseNoble，γ=1、outcome λ显式设置；真实1/0.5/0用于outcome BCE，风格用独立MC目标与style MSE。无teacher CE/赢家筛选/logit覆盖。旧v0.1 Policy/encoder/train/export均未改，导出保留原32键。
- 首版梯度采用singleton累计到显式minibatch，而非动态padding大batch；行为推理同样singleton。这是正确性优先实现，不是已测最佳吞吐。style head重新调用共享encoder取得特征，避免改v0.1 forward；参数仍共享，梯度并非隔离保证。
- 存储首版为有界JSON批/不可变torch快照，而非大规模memmap/ragged streaming；每次恢复校验提交链，I/O随历史增长。有限测试证明逻辑更新不重复消费，不证明无限运行、断电零损失或任意GPU版本可恢复。
- **风格只实现协议/head/loss基础，不实现真实风格奖励提取器。** 协调器明确拒绝`style_beta>0`的正式campaign；低层style测试只用合成效用，不能称为已学得基建/干扰/冲分。K/H/cap/β仍未冻结。
- 作业表固定对手身份，但回放自身不能证明实际运行了哪个对手；Arena launcher及report/binary身份绑定、进程并发、CPU/GPU硬时限与每次物理采样成本核算仍是阶段II前置。现有预算控制cycle/jobs/learner决策预留、optimizer steps/attempts、操作间wall time和对象存储；不冒称已有整套硬资源调度。

### Exact validation and evidence

工程结果：[M54阶段I结果JSON](../benchmarks/m54-prism-ppo-infrastructure-v1.result.json)。本地证据 `local-artifacts/prism/ppo-infrastructure-v1/`，不是训练run；无新候选权重。`evidence.json` SHA-256 **`e33f28bf98b096cdd7b2646473d065e23f7bd444ff1ebb22778b8fba67d58c6c`**；18文件源码清单SHA **`a529401716f49719a87edcff0cdaad49f7de7650c04e89df5570a818b1dcb891`**。初始失败/各轮修复与最终日志均保留；临时优化器快照仍在会话scratch测试目录。

| 实际检查 | 结果与边界 |
|---|---|
| `python -B -m pytest -q -p no:cacheprovider training/prism/tests --basetemp "$env:PI_SCRATCH_DIR\m54-pytest-final"` | **167 passed，0 skipped，exit0**；含原98项与新69项，不是正式训练 |
| `cargo test --offline -p splendor-prism --jobs 2` | **22 passed，exit0** |
| `cargo test --offline -p splendor-cli --bin splendor prism --jobs 2` | **12 passed，2 ignored，exit0**；两个需本地fixture/服务的ignored用例由下面interop显式运行，不计作默认测试通过 |
| `python -B -m pytest -q -p no:cacheprovider training/prism/tests/test_ppo_interop.py --basetemp "$env:PI_SCRATCH_DIR\m54-interop-final"` | **3 passed，exit0**，使用格式化后最终隔离二进制；Rust合成Main/ChooseNoble决策↔Python服务、既有回放双actor审计/缺行额外行拒绝、PPO更新导出parity |
| `cargo build --offline -p splendor-cli --bin splendor --jobs 2` | **exit0**；target设为`$env:PI_SCRATCH_DIR\m54-cargo-target`，未覆盖共享production/release二进制；既有其他模块编译warning保留 |
| 新两份Rust文件 `rustfmt --check --edition 2021 --config skip_children=true …` | **exit0**，不格式化无关文件 |
| `python -B -m training.prism.ppo --help` 与 `python -B -m training.prism.ppo.service --help` | 各 **exit0** |
| 全仓 `git diff --check` | **exit0**，仅LF/CRLF提示；新未跟踪代码另经直接尾空白/AST检查 |
| 阶段I开始时保存的13文件hash复核 | **13/13不变**：原Prism模块/编码/推理/配置/结果、seed登记、v0.1权重与Aran champion记录 |

Interop环境变量及精确路径在结果JSON中；使用已有 `local-artifacts/prism/v01/smoke/games/seed-9404999/r0/match-replay.json`，未重赛。为审计测试构造的one-hot sidecar只测试规则join，不冒充真实on-policy训练数据。Python/Rust服务测试只有两个合成局面，未执行整局；不构成Arena采样验收。

Parity使用已有68个边界fixture与**合成PPO更新后的临时权重**：逐元素`atol=rtol=1e-4`通过，最大绝对logit差 **`1.6391277313232422e-7`**。不是v0.1重新训练或竞技提升证据。进程故障测试覆盖payload/commit/HEAD发布前后；优化器恢复测试覆盖反向、step及发布边界，并比对模型、AdamW状态、RNG和消费集合。

### Result, limitations and next gate

**阶段I基础设施与限定工程测试完成；无正式PPO训练、无新采样/比赛、无生产晋级。** 没有当前实施阻塞，保留Aran停止决定与所有历史负结果。未提交/推送；handoff及本地证据保持ignored。

下一步需另批**阶段II Arena接线与极小工程对局预算**：先绑定实际对手/引擎/report身份、进程期限与采样成本，再验证完整真实on-policy采样→审计→更新→恢复。该阶段通过后，才能按新合同批准持续训练；风格奖励实现与K/H/β、非劣δ及独立验收预算也仍须明确。现阶段不接受“167测试通过所以棋力增强/已学得风格/可以无人值守长期跑”的推断。

## Stage II live Arena engineering round — authorization

Status: **IMPLEMENTED / VERIFIED（授权8局工程门通过）**。用户“go ahead 初始对手只采用自己（v0.1）和heuristic v0.3.1吧”，随后明确同意8局工程闭环验证；本节优先于研究期/阶段I关于未授权新对局的历史记录。授权与预算保持原样，执行结果见下方收口。

- 两轮，每轮对冻结Prism v0.1和heuristic v0.3.1各1个新seed双换座，共4局，总8局。仅收learner轨迹；对手greedy、learner T1正常抽样。无Aran/历史池/当前learner对手副本。
- 每轮≤1 optimizer更新、总≤2；infra retry≤2、总物理attempt≤10。无额外smoke、换seed补健康局、候选扫描或正式长训。
- CPU串行，β=0；passes=1且minibatch覆盖单轮最大允许决策，显式冻结配置/seed/执行身份/硬期限。cap、身份/行为/审计失败停止并留证，abort无胜负。
- 绑定实际引擎/Agent SHA、Prism权重SHA、完整argv、规则/catalog/schema、job/attempt/seat/seed/behavior及report/replay/sidecar。完成job不重赛；中断仅同身份有限恢复。
- 门禁为真实采样→身份/规则/行为审计→更新→事务恢复；不是棋力改善、风格成功、非劣或晋级。禁止teacher CE和人工推理偏置。
- 不改规则、冻结模型、UI/registry/线上池/共享release，不停止其他进程、不提交推送。阶段I历史证据保留。

### Iteration log

- 直接复核main/HEAD/dirty工作树/ignore；HEAD仍为页首基线。本轮13份关键文件起始SHA保存于会话scratch `m54-ii-baseline.json`。
- 一次文档追加操作被误写为正文，直接回读后移除并正确追加；无代码或实验影响。接线前尚未启动真实局/更新。

### Pre-live contract freeze

- 配置`benchmarks/m54-prism-ppo-arena-v1.config.json`；工程参数主动选定而非沿用合成默认：CPU2线程，γ=1/λ=.95、LR=1e-5、clip=.2、outcome BCE权重.5、entropy权重.01、weight_decay=0、gradclip=1、targetKL=.02、old logp/value容差1e-6、β=0；全批优势标准化、passes=1/minibatch1024，单轮最多1024决策，因此完整一次更新足够。
- 两轮总8局/最多10 attempts（2次infra retry），总update attempts/steps各≤2；完整决策≤2048、含失败物理决策≤2560。每局cap256plies、wall60s/用户CPU30s；全run wall1800s/用户CPU900s，Job Object整树4GiB内存/6进程；存储2GiB由监督轮询+提交检查控制（不是文件系统硬quota）。CPU user-time与wall均硬停止；不使用GPU。
- seed9406000..9406003已直接与registry核对无重叠并预留，每seed双换座；不另加smoke。heuristic seed仅用于最高分并列时的既有tie RNG，不是从分布抽样。
- 三项冻结资产SHA直接复算一致；隔离新binary SHA `2c0aba78ab1bef8d5e8ac85223277e137a74a931c12a22a9b016706c4d8aa321`。对手描述hash与完整合同绑定，v2 submit强制completion包；报告协议实值0.5、ruleset为splendor-base-v1、seed commitment为SHA字符串，不能信只读摘要中的错误示例。
- 已执行首轮42项专项/恢复测试exit0；补成本幂等、终局缺包不得重赛、v2一次optimizer attempt后，全量195 passed/0 skipped，exit0。日志在本会话scratch，收口归档；隔离cargo build exit0。两次定位编辑错误已回读纠正，AST/回归通过，发生于live启动前。
- 下一操作按已授权合同执行第一轮4局和≤1更新；第一轮边界退出/reopen/pause-resume，再执行第二轮，不做额外真实故障注入或重复更新。

### Final implementation and iteration closeout

- 新增`training/prism/ppo/arena.py`、`execution.py`、`processes.py`及28项Arena专项测试。launcher使用既有Arena规则执行，不修改`arena_command.rs`；v2 run绑定完整执行合同，并强制接纳真实completion包。实际程序/参数、对手Hello、binary/权重SHA、job/attempt/seat/seed commitment、rules/catalog、behavior snapshot与report/replay/sidecar交叉校验；严格规则/玩家可见投影审计后才接纳learner自身轨迹。
- Windows Job Object监督本轮拥有的进程树：挂起创建→加入Job→恢复，整树内存/活动进程/用户CPU上限及kill-on-close；wall/storage轮询。物理决策在审计前计成本、发布/恢复幂等；已完成job不重赛，终局缺completion包停止。v2协调器也拒绝每轮第二次optimizer attempt，不仅依赖launcher。
- 启动前JSON身份字段一次行号误插，经回读纠正；严格配置/资产/合同preflight exit0后才启动。未发生真实运行失败、换seed、额外smoke或预算重置。
- 两轮各4局均正常终局；第一轮108条learner决策、第二轮112条，共220条/440plies。物理attempt **8/≤10**，infra retry **0/≤2**，optimizer attempts/steps **2/≤2**；无abort/truncation。seed9406000..9406003已登记consumed，75个registry区段内部无重叠。
- 第一轮提交后退出进程，真实执行pause→reopen→resume→reopen；模型、AdamW状态、RNG及消费游标签名一致，重复对局/更新拒绝。第二轮行为快照逐张量等于第一轮提交后模型；两个批次各消费一次。完成预算后`Campaign.work()`重入是no-op，新增cycle/update拒绝。未做真实optimizer crash注入或真实infra retry，相关故障路径由合成恢复测试覆盖。
- 两次真实更新的Policy–Value均不同于上一版本；导出与各自checkpoint的32键逐张量一致，禁用的style head保持初始化不变。81/220次类别抽样选择了非最高概率动作，复算动作/分布/logp/value一致；这证明正常学得分布抽样，不是人工风格覆盖。

### Validation and evidence — Stage II

冻结配置：[config](../benchmarks/m54-prism-ppo-arena-v1.config.json)，SHA **`7f4be54459d4da0054ba604e65272367461ffa2902ae77bf32652911d75cb0dc`**；结果：[result](../benchmarks/m54-prism-ppo-arena-v1.result.json)。本地完整证据`local-artifacts/prism/ppo-arena-v1/provenance/evidence.json` SHA **`36ab61cdd82f06822d6a848752db113eb55f8b6119d531b43a428a674e95234e`**，包含每局来源hash、更新前后诊断、所有日志hash与基线保留核对。source-hashes SHA **`10bf9a3b4fa4df1c8eba2b4b74204779bab2f2bcec934f1e3aa2d0548b4d10ca`**；真实恢复证据SHA **`e628df6bc932501749ed444e52b30127ba7012dbf5c3d2dd1ef7846b6d65955b`**。

| 实际命令/检查 | 结果 |
|---|---|
| `python -B -m pytest -q -p no:cacheprovider training/prism/tests --basetemp "$env:PI_SCRATCH_DIR\m54-ii-prelive-tests"` | **195 passed / 0 skipped，exit0**；五个M54 interop环境变量使用阶段I相同既有fixture/隔离test binary；日志`provenance/m54-ii-prelive-tests.log` |
| `cargo build --offline -p splendor-cli --bin splendor --jobs 2` | **exit0**；`CARGO_TARGET_DIR=$env:PI_SCRATCH_DIR\m54-cargo-target`，仅拷贝新隔离binary，不覆盖生产release |
| `cargo test --offline -p splendor-prism --jobs 2` | **22 passed，exit0** |
| `cargo test --offline -p splendor-cli --bin splendor prism --jobs 2` | **12 passed / 2 ignored，exit0**；两个opt-in用例由Python interop显式执行，不把ignored计作默认通过 |
| `python -B -m training.prism.ppo.arena --campaign local-artifacts/prism/ppo-arena-v1/campaign --contract benchmarks/m54-prism-ppo-arena-v1.config.json --stop-after-cycle` | **exit0**，第一轮4局+1更新；日志`provenance/m54-ii-cycle1.log` |
| `python -B -m training.prism.ppo.arena --campaign local-artifacts/prism/ppo-arena-v1/campaign --stop-after-cycle` | **exit0**，恢复后第二轮4局+1更新；日志`provenance/m54-ii-cycle2.log` |
| `m54_ii_recovery.py`与`m54_ii_evidence.py`的实际Python执行命令见result JSON | 各**exit0**；脚本及hash归档于`provenance/`，恢复日志/最终核对日志保留；只读二次审计与parity，无新增对局/更新 |
| 8份completion/report/replay/sidecar再次校验、8份Rust规则/玩家投影重审计 | **8/8通过**，审计shard与原接纳内容完全相同 |
| 220条行为单例复算 | **220/220通过**；logp最大漂移8.881784197001252e-16，value/完整概率最大漂移1.1102230246251565e-16 |
| 两轮真实更新导出Rust/Python parity | **176/180局面逐元素通过**；分别108/112个真实局面+每轮68边界；`atol=rtol=1e-4`，最大绝对logit差0.0001220703125/0.0001678466796875，不能忽略相对容差只用atol判失败 |
| 本轮起始关键hash/seed registry | **12/12冻结代码/config/result/权重不变**；第13项registry只追加本轮consumed区段；75区段无内部重叠 |

实际运行Python3.12.6/PyTorch2.6.0+cu124、CPU2线程、无GPU。两段受监督worker wall合计87.187s，用户CPU58.125s、kernel CPU26.4375s，各段退出时活动进程为0；证据捕获时本轮产物166,370,695bytes，低于2GiB上限。该资源数不包括后续只读审计/parity/单测，也不是正式吞吐测试。

最终训练事务ID **`6dd0c94616828f29147bd61a1f8377e3f594bc3de67ed2b340a6e9a9d3500354`**，是CommitStore状态提交，不是Git commit；Git HEAD仍为baseline。第二轮导出`local-artifacts/prism/ppo-arena-v1/campaign/cycle-2-export/weights.json` SHA **`46e45d544ebb5b1caba5802a3c12bc9e4605d2a986156a8fc148afd4e455f6b0`**，manifest标记not_promoted。

### Result and decision — Stage II

**真实Arena采样→执行身份/规则/行为审计→PPO更新→跨轮恢复工程门PASS；授权8局预算完成并停止。** 诊断战绩4胜0平4负；每个冻结对手分别2胜0平2负。样本极小且策略跨轮变化，不是固定候选竞技测量、棋力改善/等强证明、风格成功或生产晋级。未启动独立竞技验收、正式长训或风格训练。旧可选审查未收到报告，不声称独立REVIEWED。

### Known limitations and next authorized gate — Stage II

- 当前仅Windows CPU串行/singleton与可信本地文件；hash不是恶意host认证，torch快照不接受不可信来源。存储轮询不是文件系统硬quota，CPU硬门按用户CPU累计，kernel CPU另报；任意外部脚本绕过launcher不属于受监督运行合同。
- 此工程合同v2更新失败后不得自动重算以花第二次额度；真实测试覆盖正常提交边界pause/reopen/resume，实际故障注入保持合成测试。未证明断电耐久、GPU恢复、多人、长期吞吐或无限预算无人值守。
- β=0，真实风格reward提取/K/H/cap/β档、行为差异门槛、均衡/跨风格非劣δ和竞技预算仍待冻结。不以本轮8局胜负调整未来门槛。
- **当前任务无剩余实施阻塞。下一次真实采样/更新须另批新run身份、冻结配置和明确预算**；风格实现与棋力验收单独过门。保留v0.1与Aran历史，不改UI/registry/线上池/共享release；未stage/commit/push，handoff和本地产物仍ignored。

### Final publication/documentation check

- `python -B -c "import runpy;runpy.run_path('local-artifacts/prism/ppo-arena-v1/provenance/m54_ii_closeout_check.py',run_name='__main__')"` **exit0**：15份运行源码hash、12份冻结基线、8份完成包/复审hash、两轮导出hash、日志、14个文档链接、75个seed区段及结果/config/evidence一致。`git diff --check` **exit0**，Git仍为main/baseline且无暂存文件；handoff/local-artifacts ignored且未tracked。
- 只读收口证据`local-artifacts/prism/ppo-arena-v1/provenance/closeout-checks.json` SHA **`10af4524f8579826be1b5ebb531f78e64de5945939d73ec6fe5e22e1bc2adcd8`**；对应result JSON SHA **`46cb01f70216e76b43fd6b2dc9e3834e45ab01b2b3e5b5372be75c2865531ed2`**。检查脚本和日志已归档，不再只依赖会话scratch。
- 初次收口检查exit1仅因扫描到handoff历史第1732行既有尾空白；未修改无关历史，改为本轮文件/新修改handoff区段检查后exit0。失败脚本/日志保留为`provenance/*before-scope-fix*`；无运行代码、权重、门槛或预算变化。

### 2026-09-30 汇报与训练推进咨询更正

用户指出此前汇报大量罗列冻结/授权/哈希、没有解释实际工作/8局性质/时间/下一步；接受该反馈。后续先报做了什么、是否真正学到了什么、吞吐与成本、下一步；必要检查在启动/数据接纳/提交边界集中处理，不以重复证明身份或校验历史取代有效训练。

既有run耗时证据`local-artifacts/prism/ppo-arena-v1/provenance/timing-diagnostic.json`：游戏进程wall均0.8125s；每轮4局采样/接纳19.70/22.83s；封口间隔3.93/4.25s、更新前检查间隔5.10/5.75s；反向/step/提交2.42/2.35s。来自已有日志和提交文件mtime，无新对局/更新；操作间隔并非独立函数profile。按小轮整条路径机械重复4096局约12.4h，只说明现工程版过重，不能作为优化后训练预算或承诺。

**下一步建议（尚未执行）**：简化驻留Run/Behavior及重复行为复算，历史完整核对移到open/recovery；对手资产启动核对并复用。移除smoke专用每轮4局/单step限制，支持正常多seed采样和minibatch/pass，保留合法性/玩家信息边界和结果轨迹对应。先按每批256局、每对手128局/双换座、约7040条learner决策实测吞吐；minibatch256、2pass约56step/轮是首个试训建议，不再以4局/1step代替学习。先跑有统计量的outcome-only试训并定期评测；随后再加入训练期风格奖励和对应棋力测量，不加推理偏置。

M39A只作实现经验来源：旧actor加载D2（源码并非纯随机），value/aux新初始化；当前Prism v0.1为4000局教师预训练的Policy–Value、已完成256局竞技基线。旧棋力负结果与本轮4–0–4都不能判定新PPO的学习潜力。此咨询未修改训练代码或扩量执行。

### 2026-09-30 采样接纳与热路径精简实施与对照

根据用户明确要求，彻底删除对局后重复且耗时的规则重放审计、策略前向复算与状态重载：
1. **自动接纳 0 次外部子进程整局规则重放**：正常训练信任 Arena 在对局时在线执行的规则约束（合法动作约束与真实终局判定），`submit()` 直接从 sidecar 与 Arena completion 组装合法 game shard，彻底删除每次调用 `prism-ppo-audit` 独立子进程重演整局。
2. **0 次旧策略前向复算（440 次 -> 0 次）**：在 `submit()` 和 `seal()` 的 `prepare_batch()` 中删除对每条决策执行的单步 `behavior.verify(row)` 神经网络前向复算，直接提取对局时采样的真实 `value` 与 `old_logp`；同时保留结构合法性与玩家决策链有序性校验。
3. **协调器内存模型驻留与消除全历史重载**：在 `Run` 生命周期内常驻 `learner` 与 `_behavior_cache`，仅在启动或发生异常/外部 HEAD 改变时触发 `_reload()`；`CommitStore.load()` 优化为按 sequence/parent 校验元数据链，不再每次反序列化并 hash 所有历史 `.pt`。
4. **资产与路径校验优化**：增加二进制/权重哈希内存缓存，消除每局重复对数十 MB 二进制全量 SHA256；路径规范化改用 `os.path.abspath`，消除 Windows `_getfinalpathname` 缓慢系统调用；`validate_input` 消除每步生成器循环和冗余张量拼装。

**前后同机同真实数据（8局/220决策）严格对照**：
- 外部重放审计调用（`prism-ppo-audit`）：**8 次 -> 0 次（100% 消除）**
- 旧策略前向复算调用（`behavior.verify`）：**440 次 -> 0 次（100% 消除）**
- 8局接纳处理时间（Submit time）：**24.76s -> 9.77s（2.53倍加速，平均每局从 3.10s 降至 1.22s）**
- 两轮封包时间（Seal time）：**10.06s -> 5.54s（1.82倍加速）**
- 对局后总处理耗时（Submit + Seal）：**34.82s -> 15.31s（2.27倍加速，纯事后开销压降 56%）**
- 回归测试：`training/prism/tests` 全量回归 **192 passed, 3 skipped, 0 failed**，全套测试从 175s 缩短至 121s。

### 2026-10-01 常规 outcome-only 试训前复核（代码检查与实测，未启动正式训练）

Status: **REVIEWED（parent 定向源码复核）/ VERIFIED（下列工程诊断与回归）**。用户要求检查另一模型完成提速后，常规多 seed/minibatch/pass 和真实规模试训前还有哪些问题。本轮只检查现有实现、用合成轨迹复现并只读既有数据计时；未修改训练源码，未生成新对局或登记 seed，无新学习成果。基线仍为页首 HEAD。

#### 已落地和不需要重做的部分

- v2 正常接纳已不再调用外部 Rust 重放审计；`submit` 不调用 `Behavior.verify`，`seal` 使用 `prepare_batch(..., verify=False)`。Arena 在线执行动作/规则/终局，玩家轨迹顺序与结果绑定仍保留。手动审计入口和 legacy v1 路径还在，不是日常训练前置。
- Run 驻留 learner/behavior、资产 hash 缓存已落地。PPO clipped loss、同玩家 GAE、真实 ranks 对应的 outcome BCE、新 optimizer 与旧 32 键导出在本轮相关回归中通过。没有发现必须重写奖励目标/玩家时间轴的问题。
- **更正上轮 handoff 的“已彻底解决瓶颈，直接配置即可训练”**：提速范围是采样接纳，不包含解锁常规调度；更新路径和 launcher 仍有以下具体剩余问题。上轮 2.27x 数字保留为历史报告，本轮没有重做其前后对照。

#### 常规训练前必须处理

1. **三处 smoke 限制仍在，不是仅有每轮 4 局。**
   - `execution.py:87–105` 强制 `passes=1`、每轮最大决策全部装进一个 minibatch、optimizer steps/attempts 不超过轮数，以及每个对手每轮仅一个 seed 双换座。
   - `coordinator.py:322–333` 拒绝 v2 同轮第二个 optimizer attempt，即使总预算充足。
   - `arena.py:255–263` 只调用一次 `run.step()`，未到 COMMITTED 就抛错；不会循环 minibatch/pass。
   - 实际配置复现：2 pass、minibatch256、多 optimizer step、每对手两组换座 seed 分别被拒绝。合成复现直接创建 v2 Run，3条决策/minibatch2/2pass，应需4步；第1步后 `UPDATING`、cursor2/order6，第2步报 `v2 cycle optimizer attempt already spent`，而预算仍为30 steps/40 attempts。
   - 修复应支持多个完整换座 seed 块、按配置消费 permutation，更新到 passes 完成或 KL stop；保留完成局不重赛与逻辑 cursor/optimizer/RNG 一起提交。更新 attempts 与 logical steps 分开计数，未提交计算在显式剩余额度内恢复，不再用“一个 attempt/轮”替代正常恢复。

2. **每个 minibatch 仍重复处理整批，扩量后成为更新瓶颈。**
   - `Run.step` 每次读入/parse/hash 整个 JSON batch；`Learner.diagnostics` 每次校验全批并对每行做新策略前向；`Learner.step` 再校验全批后才对所选行 backward。`seal` 还做一次全批 ratio 检查。
   - 本机 CPU2线程、历史第2轮112条真实决策：完整校验中位0.11964s，全批诊断（含校验）0.30576s，读取历史4,869,648字节 batch JSON 0.09603s；临时32条 singleton 累积更新0.25326s（含全批校验）。
   - 112行复制8次的896行**性能fixture，不是新增样本**：校验0.96576s，全批诊断2.50362s。按7000行/约56步机械线性外推，单 KL 扫描即可累计约18分钟/轮；这是开销估算，非正式大批吞吐实测。
   - 最小修复：批次在 seal/open/recovery 一次校验并驻留；正常 step 只处理当前 minibatch。KL/clip/entropy 复用当前训练前向，阈值停止余下更新，必要的整批汇总放轮次边界，不在每步重扫。singleton 梯度累积正确但不是向量化 batch；先保留亦能试训，不能把配置 minibatch256 宣称为一次256行前向。

3. **存储计数优化引入小 bug。** `CommitStore._check_space` 第一次初始化 `_used_bytes` 时没加本次 `additional`。实际100字节预算接受1013字节对象，落盘1014字节，缓存仍为1。只需正确初始化/累计并在拒绝时不污染缓存；新增首写与累计写回归即可，不需要重做存储系统。现有 `test_store_budget_and_orphans` 之所以通过，是 commit 后续写 manifest/HEAD 时才挡住；不能证明首对象写入门正确。

4. **观测学习效果需补固定评测，而不是只看训练日志。** 当前 `game_complete` 有结果，optimizer step 保存 loss/entropy/grad norm，但 KL/clip 仅在 seal 初始诊断中持久化，更新中的诊断没有逐step保存；没有常规 PPO campaign 的固定开发评测闭环。记录每轮按对手/座次归并的 win/draw/loss/计半平奖励、样本量、实际更新步数、KL/clip/entropy/value loss、采样/接纳/更新耗时；父代与checkpoint在训练隔离的同一开发 seed 池上按固定频率对照。主要模式为 learner 学得 T=1 抽样，父代也应测 T=1；旧 M51 greedy 的54.6875%不是此模式的对照基线。greedy 可另列诊断，不能临时混用更好结果。

#### 后续轻量处理与非前置项

- launcher 的 `Campaign._load` 仍每次遍历 ledger 全提交链；历史8局 ledger 每次读41份 commit metadata，实测约0.00402s。现在成本小，随局数增长，改成如 Run 一样驻留/head变化时 reload 即可；目录总量轮询也仍在。不把这一小数值夸大为当前主瓶颈。
- 每 optimizer attempt 前/后仍各保存完整model/optimizer快照，当前历史快照2,777,768字节。常规预算应包含局产物及这些提交，不能复用8局/2步/2GiB/30分钟工程预算；无需先实现全套 streaming/GC 才做有限试训。
- 风格 reward、GPU/PyO3、并行Arena、动态自博弈池不是本次 outcome-only 试训前置。β=0、冻结 Prism v0.1 和 heuristic v0.3.1 池可以先开展有效学习实验。
- 建议起步批次仍为每轮256局（每对手64个seed双换座）、minibatch256、2pass、8轮，共2048局；按既有27.5条learner决策/局估算约7040条/轮、约56个logical step/轮、约448步总量，实际受局长与KL提前停止影响。此为建议配置，不是已运行结果；在上述最小修复通过后跑首个正常训练批，以它的真实耗时/奖励/更新情况继续同一次试训，不再另用8局smoke替代。

#### 本轮精确验证与证据

- `python -B -m pytest -q -p no:cacheprovider training/prism/tests --basetemp "$env:PI_SCRATCH_DIR\m54-readiness-pytest"`：**192 passed / 3 skipped，43.00s，exit0**。跳过的是明确 opt-in interop，随后单独补跑。
- 设置历史五个 M54 fixture 变量后，`python -B -m pytest -q -p no:cacheprovider training/prism/tests/test_ppo_interop.py --basetemp "$env:PI_SCRATCH_DIR\m54-readiness-interop"`：**3 passed，12.59s，exit0**；使用现有隔离 Rust binary/已有 replay/68边界fixture，无重赛/构建。
- `python -B "$env:PI_SCRATCH_DIR\m54_readiness_probe.py"`：**exit0**；四类配置拒绝、v2第二步拒绝、首写漏计和历史数据性能诊断复现。合成更新和3次历史fixture临时更新全部丢弃，未产出候选，复制fixture不作为训练语料。
- 证据归档 `local-artifacts/prism/ppo-readiness-review/{m54_readiness_probe.py,m54-readiness-probe.json,m54-readiness-probe.log,m54-readiness-pytest.log,m54-readiness-interop.log}`；JSON SHA `3ae0003df39b808667b6a22803688bd03bb8792d9d5d09675a9b342d19b773f7`。
- 当前结论：**提速已落地；常规试训尚不能仅靠改配置启动。** 本轮只读复核完成，下一步是上面有界的调度/更新热路径/计数修复及训练+开发评测配置；不增加风格或旧历史失败导致的额外门禁。

### 2026-10-01 阶段III常规 outcome-only 试训授权与开工

Status: **AUTHORIZED / IN PROGRESS**。用户明确要求自动修复、启动训练迭代，并允许在 `ssh cloud2` 进行固定棋力对照和混池。本授权取代历史8局工程smoke的扩量边界，不改变历史结果。

- 本轮范围：解除三处单seed/单step/1pass锁；batch seal/reopen一次校验与驻留；minibatch前向复用KL/clip/entropy；修复首写空间计数；256局×8轮、minibatch256、2pass、β=0的真实PPO试训。
- 初始计划：Prism v0.1暖启动、新AdamW；冻结Prism v0.1与heuristic v0.3.1 greedy对手，各64个seed双换座/轮；CPU2线程。训练局结果仅作奖励，固定开发池父代/checkpoint均T=1，混池Elo另列。正常Arena接纳不重新增加整局重放或旧策略复算。
- cloud2只读核实：worker/web存活，池暂停，累计10,854正常比赛；现有binary仅Prism greedy、无固定排局。新增独立采样入口/不可变binary及候选资产；固定换座runner隔离目录、不写混池Elo，再恢复混池。旧六模型、权重、DB历史保留。RAM约951MiB、2CPU，无Torch；使用Rust部署，不安装训练栈。
- 验收：多pass/尾minibatch/恢复与存储回归通过，实际启动首256局常规批并按同run继续，记录真实样本/steps/奖励/耗时及固定评测/混池结果；不以训练完成推断晋级。风格reward、GPU、动态自博弈池不在本轮范围。
- 此处仅记授权/开工，尚无本轮新训练或评测结果；实际配置、命令和产物在后续追加。

#### 阶段III实施与首次正常试训启动（持续运行，非完成结论）

- 已实现常规多完整换座seed块、多minibatch/多pass与pass内尾批；删除v2每轮一次attempt锁，Campaign循环更新至passes完成/KL stop，保留attempt先计费与model/AdamW/RNG/cursor一起提交。批次seal/open/recovery校验后驻留；正常step没有全批JSON读取、全批校验或全批新策略诊断。KL/clip/entropy复用minibatch更新前forward；KL>阈值时不执行该次optimizer，停止余下更新。singleton梯度累积保留，未宣称向量化256行forward。
- 采样接纳不回加事后规则重放/Behavior.verify。CommitStore首写与累计计数已修复；成功写后计净新增bytes，HEAD覆盖按差额计费，失败不污染cache。launcher ledger驻留且copy-on-write；按轮保存对手/座次奖励、样本、steps、逐步loss/KL/clip与耗时。
- 验证：定向三文件102 passed（59.78s、exit0）；完整Python200 passed/3 opt-in skipped（56.72s、exit0），再补interop3 passed（30.23s、exit0）；ledger最后小改后Arena32 passed（43.93s、exit0）。新测试覆盖v2多pass尾批、五个事务中断点恢复、驻留批次无重复读取/诊断、KL无optimizer与首写/累计/HEAD净计费。未声称独立review。
- 实际trial配置 `benchmarks/m54-prism-ppo-trial-v1.config.json`：8×256局，两个冻结greedy对手各64seed双座/轮；CPU2、新AdamW LR3e-5、clip0.2、value0.5、entropy0.01、λ0.95、minibatch256、2pass、KL0.02、β=0。训练seed9410000..9411023，共享T1开发seed9420000..9420127，登记77个区段无内部重叠；v0.1训练/权重及旧赛事不改。
- budget：2,048 jobs/2,064 attempts（16 infra retries），524,288决策上限、每局256，4,096 steps/4,160 update attempts，8h wall/24,000 aggregate user CPU秒、8GiB进程树内存、96GiB产物上限。step期望约448仅为估算；实际数由局长/KL决定。contract ID `274bc459fbf7fb0955716fe6dedf1662b4af5efa7df3a1a1033c63bcfd3612ee`。
- 首次配置脚本因scratch同名 `inspect.py` 遮蔽stdlib失败，隔离sys.path解决；未认作Torch损坏。首次工具shell内Start-Process启动监督PID3260，完成2局53决策后shell退出清理子进程，第3次attempt未publish终局。无模型更新、前2局已提交不重赛。CPU原24,000预留保留，按观察到全部进程退出前wall×20逻辑CPU的保守上界计3,822秒，剩余20,178秒，记录 `provenance/first-launch-interruption.json`。
- 已用Win32_Process.Create独立托管恢复同campaign：wrapper PID13644、监督PID22908，真实命令 `python -B -u -m training.prism.ppo.arena --campaign local-artifacts/prism/ppo-trial-v1/campaign`；恢复完成局跳过、第3次中断按full decision reservation记infra重试、同job/seed继续。启动后跨工具调用存活，已推进至attempt38；此为进行中，不是完成2048局或棋力提升。
- 产物：`local-artifacts/prism/ppo-trial-v1/{campaign,train.stdout.jsonl,train.stderr.log,background.json,provenance}`；首轮与逐轮summary/checkpoint稍后产生。fixed T1父代/checkpoint与mixed-pool部署并行中，尚无正式固定/混池新结果。

#### 2026-10-01 阶段III真实学习、T=1固定基线与混池部署

本段记录进行中快照，不将2048局计划写成完成。代码与运行检查由parent执行，不冒称独立REVIEWED；Rust/fixed-eval子任务因反复机械编辑和耗时被停止，parent读取最终文件并完成以下定向验证。

**实施与恢复合同**：新增 `agent-prism-sample`（旧greedy入口不变），f32网络/f64稳定softmax T=1，compact JSON SHA256 keyed CDF；动作seed、game_id、viewer与本玩家decision index只作抽样键，不入网络，ChooseNoble同样递增。不偏置、无greedy兜底。`scripts/prism_ppo_fixed_eval.py`以hash钉住binary/权重、同game_id与seed双换座，保存report/replay/argv和原子progress/result；完成局恢复不重赛，失败局保留并停止。补测结果写出但completion hash尚未发布的中断恢复：仅重建汇总，不新派比赛。

**自动运行**：`scripts/prism_ppo_checkpoint_publisher.py`只读已提交的32键导出，严格加载/tensor identity/文件hash核对后上传临时资产，远端hash校验→不可变文件→ready原子发布。独立托管wrapper27752/发布31000持续等待c4/c8，c1已发布。`scripts/prism_ppo_cloud2_controller.py`隔离固定评测、不写Elo；父代结果缓存一次，c1/c4/c8逐一按同128seed配对bootstrap；每轮固定完成后256局混池区间，达到门槛暂停并让单一在途局收尾。旧六模型配置、权重、ratings/history不重置，只disable更早trial候选保留其身份/history。混池恢复保存原 `mixed_start_id` 和deadline，不重新开额度；错误pause。

**cloud2部署事实**：旧引擎SHA `785fa765aa0db35b96840f975317c9a41dc23be3576b6d50038e4b58cabae77f`未替换，旧Web/worker PID272939/272940保留。初次隔离Rust构建因在途sampler缺json宏起止而失败，原log归档 `build.initial-failed.log`；parent定向测试后同步最终文件，`CARGO_BUILD_JOBS=1 cargo build --release --locked -p splendor-cli --bin splendor` exit0、12m19s。新不可变binary SHA `ed35350f27e84ffccb1735ea4f8e8626070a2aed3ad32ced632769578cbd31e2`，根 `/home/ubuntu/splendor-m54-trial-v1`，prepare监督361104/controller361405。plan原文件SHA `cc2821b2446b952ddc1e3307172b4ba01de46a6c5fc72c80c203a76b3891c3c7`；canonical plan identity是不同的 `fbd11c5d6bdb31dfa58aeec40d1614201a01a98510c246955dc9d3f364ced1fd`。128seed9420000..9420127、action_seed54010001、每模型512固定局，混池256/round、controller总deadline12h；当前8轮训练未完成，不扩预算。

**实际验证**（日志归档于 `local-artifacts/prism/ppo-trial-v1/provenance/`，命令target/basetemp在会话scratch）：

- `cargo test -p splendor-cli --bin splendor prism_sample_ --target-dir <scratch>/m54-cargo-target`：4 passed/exit0，含Python-known draw、non-ASCII compact key、determinism/equal logits/extreme logits/非法分布；`cargo build -p splendor-cli --bin splendor --target-dir ...` exit0。
- `python -B -m pytest -q -p no:cacheprovider training/prism/tests --basetemp <scratch>/m54-regular-all-final`：213 passed/3 skipped/1 failed、100.25s。失败 `test_storage_supervision_and_cpu_limit` 在同时真实训练负载下先触发8s wall；断言/资源门未放宽。单项重跑1 passed/1.69s；全套再跑 `<scratch>/m54-regular-all-retest`：214 passed/3 opt-in skipped、122.72s、exit0。
- opt-in环境指向隔离最新CLI、既有replay/boundary fixtures/v0.1权重，`pytest ... test_ppo_interop.py --basetemp <scratch>/m54-final-interop`：3 passed/33.49s、exit0；不是新比赛。
- 最后fixed-eval结果发布中断分支补测后，`pytest ... test_ppo_fixed_eval.py test_ppo_cloud2_controller.py test_ppo_checkpoint_publisher.py --basetemp <scratch>/m54-deploy-recovery-final`：15 passed/4.65s、exit0。此前14项已通过；Windows测试用硬链接chmod只读导致临时文件无法unlink，平台限定测试兼容修复后通过，Linux实际发布仍只读不可变。
- 真实c1权重在已有68边界局面Python/Rust parity通过，逐元素 `atol=rtol=1e-4`；最大绝对logit差0.00011444091796875、value差2.588218689369981e-7。前者大于atol不等于失败，因为联合relative tolerance；`provenance/c1-parity.json`含真实断言和资产hash。

**前三轮真实训练**：

| cycle | games / decisions | W–D–L / reward | steps / attempts | launch秒（含对局/接纳） | game / ingest秒（子计时，勿重复相加） | update+commit秒 |
|---|---|---|---|---|---|---|
| 1 | 256 / 6932 | 112–5–139 / 0.447265625 | 56 / 56 | 695.218 | 217.262 / 230.950 | 226.413 |
| 2 | 256 / 6869 | 116–1–139 / 0.455078125 | 54 / 54 | 798.373 | 208.287 / 241.712 | 178.036 |
| 3 | 256 / 6887 | 109–1–146 / 0.427734375 | 54 / 54 | 1038.087 | 309.845 / 254.346 | 154.377 |

全部 `passes_complete`，没有KL超阈值取消optimizer；上述是训练奖励，不是共同seed后的学习改善。逐step policy/BCE/KL/clip/entropy/grad norm、每pass尾批与seal秒以原summary/jsonl为准；grad_norm是裁剪前，不因大于1判断未裁剪。c1导出SHA `59ac05717976b4f21bb1c8b572e1ac1a60bea7a21df27eafa43bd174cf78c60c`，事务commit `4827a7789734249544df3e934a22d0ac6e9f840abbb252180f3f62b9ebaf2197`（不是Git commit）。

**T=1父代固定基线已完成**：512局正常终局/无error，两个greedy对手各256局，128seedblock双座：

| opponent | W–D–L | score rate | seed-block95%CI | seat0 / seat1 |
|---|---|---|---|---|
| heuristic-v031 | 102–0–154 | 39.84375% | [34.375%,45.703125%] | 46.09375% / 33.59375% |
| prism-v01 greedy | 99–0–157 | 38.671875% | [32.8125%,44.53125%] | 40.625% / 36.71875% |

固定父代总体201–0–311，score39.2578125%。这是开发T=1基线，不能与历史greedy54.6875%混用，也不单凭父代结果评价PPO。混池父代区间matches10855..11111，共257局，父代新身份7 `prism-v01-t1-m54`参赛69局36–0–33，Elo1500→1561.90；旧六模型正常继续结算，非清零/覆盖。pool暂停后自动c1固定评测，最近快照206/512，stderr0；candidate配对结果未完成，不宣称提高。

**结果与下一门**：IMPLEMENTED / 工程VERIFIED / 真实训练、固定对照与混池IN PROGRESS / NOT PROMOTED。继续同合同剩余轮次，自动发布c4/c8，同128seed固定开发+有界混池；保持父代和所有负结果，完整结果后才决定下一训练合同。预算内遇真实非终局/数值/identity失败时保留证据停止，不换seed刷过。tracked trial result是进行中快照，不是2048局终审。

#### 2026-10-01 c1开发对照、中断终局恢复与明确资源追加

- c1固定512局完成，heuristic-v031 117–0–139/45.703125%，prism-v01 greedy 109–1–146/42.7734375%，总体226–1–285/44.23828125%。同父代共同128seed配对Δ总体+4.98046875pp，seed-block bootstrap95%CI[+0.1953125,+9.67041015625]pp；分对手Δ+5.859375pp CI[-0.78125,+12.5]、+4.1015625pp CI[-2.34375,+10.546875]。这是预设c1开发checkpoint，未做多个checkpoint选择校正，不代表独立holdout晋级。c1混池11112..11368共257局，候选实际62局32–0–30/Elo1517.17，cloud2暂停并转等待c4。
- 真实本地wrapper/监督/worker/publisher在约07:08:30Z未知外部退出；无错误栈、无资源汇总，不能认定算法/CPU故障或工具退出原因。训练最后commit COLLECTING/c4、67局已接纳、164更新；attempt837 report正常完成、process-result exit0/active0/CPU0.203125/52plies/26 learner决策，但completion尚未发布。未重赛：parent从launch-ledger不可变父提交 `7299a268a732005271a42174f1c5251e4882e82e52193266cd8560c24152aca7`（PID3956/原argv/config），行为76211b57…和原snapshot、原report/replay/sidecar/hash重建completion，经现有verify_completion/submit接纳；26条决策加入、attempt837/steps164不变、836局累计22,535条决策。0规则重放、0Behavior.verify；失配即停的普通recover_running门未放宽。这是一次有证据人工恢复，不宣称全部任意中断点已自动化。首次脚本误取FINISHED记录中不再保留的argv/config而KeyError，写前停止；读取不可变前提交纠正，最终exit0，失败日志保留。
- 监督总CPU汇总缺失，按旧合同将剩余20,178预留全部计费，加最早3,822保守账共24,000，**并非实测用满CPU**。旧supervisor-sessions保持历史与原reservation，不清零；原额度耗尽时停止新派局。用户通过asktool明确选择“追加有限资源，继续完成原任务”，授权另加最多24,000 aggregate user CPU秒，只完成原剩余1,212局；原8h wall/8GiB/96GiB、seed/LR/pass/β=0、总2,048局和评测门全不变。独立 tracked `benchmarks/m54-prism-ppo-trial-v1.resource-supplement.json`，不重写冻结training contract。
- 新 `scripts/prism_ppo_resource_supervisor.py`在训练source identity之外，严格绑定原contract/旧成本ledger/source/run identity，保留旧CPU账，使用同worker新Windows Job Object资源额度，5秒原子持久化actual CPU；中断时snapshot actual+未观测wall×机器逻辑CPU上界，缺snapshot仍全预留，不以归零绕过。监督锁与dispatcher互斥，原wall deadline不平移。2026-10-01真实监督23228/worker4100从attempt838继续；publisher wrapper23092/5888恢复原state/c1发布身份与原deadline，cloud2旧controller保持不重开赛事额度。
- `pytest -q -p no:cacheprovider training/prism/tests/test_ppo_resource_supervisor.py --basetemp <scratch>/m54-resource-tests`：7 passed/0.52s/exit0，含actual短进程资源落盘、不清零中断账、快照gap上界、wall/storage截止、contract/成本ledger拒绝；`validate_authorization`实际返回旧CPU24000。恢复后完整 `pytest ... training/prism/tests --basetemp <scratch>/m54-post-recovery-all`：222 passed/3 opt-in skipped、67.69s、exit0；此前opt-in3 exit0保留。旧绑定source SHA `2b1997059bde2f083309ee08ff50f8ad54773a0e2ec9444c5069cc46a18fd9ee`、run identity `6951e32a8819bd37e915701fb517ebf387a411c954820554e0b2cb3525f15964`不变，原contract文件SHA `d4d29e21f6886c82af8ca787f0e339759ab48e6bd214b819e3aa6b5289436ee3`。supplement canonical identity `0f449508929fc05a8d71efb8f149edfc0e94555297a4b4e245ce3ce271741a22`，不是原contract ID。
- 补充证据：`provenance/second-launch-interruption.json`、`provenance/validation/`（真实失败+重跑logs）、`supplemental-resources.json`、`provenance/training-observation.json`、`cloud2/c1-{fixed,paired-delta,mixed-summary}`。中断前“持续运行”快照是历史，不当作当前存活证明；此后状态以原子HEAD/实际PID核实。下一步仍同run完成八轮c4/c8，不临时改seed/学习率，不因c1开发正向信号更改晋级门。

#### 2026-10-01 继续执行：c4完成、第五轮提交及result索引更正

- 继续任务时实查 `main@bcdaca7cb33c53cc43d5dcc9e92c07be3c1aaa57`，监督23228/worker4100、发布5888仍存活，未热改绑定训练源码；原source/run/contract与wall deadline保持不变。第五轮已提交256局/6,855决策、133–2–121、reward 0.5234375、54次更新，累计前五轮1,280局/34,453决策/272steps；第六轮采样中。
- c4固定512局完成：heuristic-v031 123–2–131/48.4375%，prism-v01 greedy 118–1–137/46.2890625%，总体241–3–268/47.36328125%。相同128seed块相对T=1父代的配对总体Δ+8.10546875pp，95%CI[+3.125,+13.0859375]pp；分对手Δ+8.59375pp CI[+0.78125,+16.6015625]、+7.6171875pp CI[+0.78125,+14.6484375]。这些是未校正checkpoint选择的开发证据，不是独立验收或晋级。
- c4混池matches11369..11625共257局，候选身份9实际参赛62局、30–0–32、Elo1500→1554.43；旧六模型/父代与历史不删，c1仅disabled。controller361405无error，池暂停等待c8。固定completion/result/config、delta和mixed summary已下载并逐文件核对远端SHA256，未新增比赛。
- 只读 `m54_trial_report.py`核对前五轮不可变提交、全部job/奖励计数、每pass独立permutation和尾批、AdamW step/LR、RNG/cursor、32键export tensor identity，并复算父代/c1/c4共同seed bootstrap，exit0。c4奖励256局计数包含恢复局837；原summary的game wall少1.609秒，可由原completion补为306.904秒；该局launch/ingest计时不可恢复，不能零填或把原979.791/220.737秒当全量。原summary保持不变，追加汇总修正。
- **文件索引更正**：此前文档称tracked trial result是进行中快照，但实查文件尚不存在；本次才实际创建 `benchmarks/m54-prism-ppo-trial-v1.result.json`（2026-10-01T08:33:45Z快照，1,363局/5 committed cycles，IN_PROGRESS），不能把旧索引当作先前文件已生成的证据。完整校验范围、hash及局面索引见 `local-artifacts/prism/ppo-trial-v1/provenance/trial-reconciliation.progress-1790843625.json` SHA `597dffeb00285ae23caa5879508de984ccd6da4e571be1c5c7c47cdcf2c4ed0d`；全包hash终审和c8仍待完成。
- 保留只读命令的PowerShell引号SyntaxError和远端不存在日志路径的失败；改为scratch脚本与实际布局后继续，没有写训练状态、重赛或optimizer更新。最新历史测试日志核对222 passed/3 skipped、opt-in3 passed、Rust CLI16 passed/2 ignored；这些是此前实际运行的回归，不冒称本次重新执行。
- 下一步继续同合同至第八轮，c8既有68局面parity、自动不可变发布、512固定局和有界mixed；完整证据收口前维持IN_PROGRESS / NOT PROMOTED，不自动新增训练轮或style。

## Stage III final closeout — 2026-10-01

Status: **IMPLEMENTED / VERIFIED / COMPLETED_DEVELOPMENT_ONLY / NOT PROMOTED**。本节为当前结论，优先于上方进行中快照；不回写原逐轮summary、不抹去中断或失败。baseline仍`main@bcdaca7cb33c53cc43d5dcc9e92c07be3c1aaa57`，没有把训练事务commit当Git commit。

### Final implementation and frozen scope

本次用户“继续训练迭代吧”继续同一campaign，未另开run、改LR/seed/对手/pass、追加训练局或启用style。训练与云端部署实现见前文；正常接纳继续信任Arena在线合法性与真实终局，**0事后整局规则重放、0旧策略Behavior.verify前向**。Policy/Critic信息边界、同玩家γ=1/λ=0.95 GAE（含ChooseNoble）、T=1学得分布与新AdamW合同不变，无teacher CE/人工输出覆盖。singleton梯度累积仍不是一次256行向量化forward。

原八轮已完整提交：2,048唯一job、1,024个9410000..9411023双座seed、55,123条learner决策、110,266 plies、八个唯一consumed batch、436 logical optimizer steps与436 update attempts。launch-ledger共2,049 attempts、1 infra retry；physical decisions收费55,379＝接纳55,123＋历史中断整局reservation256。恢复attempt837的真实终局未重赛，已提交optimizer未重做。八轮均`passes_complete`，无KL-stop跳过更新。

### Training reward and update health — not a paired strength delta

每轮256局；对手各128局，座次各64。奖励来自各轮不同训练seed，不能把这一列当共同seed棋力提升；第5/6轮之后奖励下降也保留。

| cycle | learner decisions | W–D–L | mean reward | steps / attempts | 每pass minibatches / 尾批行 | max pre-update minibatch KL |
|---|---:|---|---:|---|---|---:|
| 1 | 6,932 | 112–5–139 | 44.7265625% | 56 / 56 | 28 / 20 | 0.007279884 |
| 2 | 6,869 | 116–1–139 | 45.5078125% | 54 / 54 | 27 / 213 | 0.007801347 |
| 3 | 6,887 | 109–1–146 | 42.7734375% | 54 / 54 | 27 / 231 | 0.005835848 |
| 4 | 6,910 | 120–1–135 | 47.0703125% | 54 / 54 | 27 / 254 | 0.004969001 |
| 5 | 6,855 | 133–2–121 | 52.34375% | 54 / 54 | 27 / 199 | 0.006518349 |
| 6 | 6,859 | 132–2–122 | 51.953125% | 54 / 54 | 27 / 203 | 0.006335917 |
| 7 | 6,938 | 121–1–134 | 47.4609375% | 56 / 56 | 28 / 26 | 0.006285324 |
| 8 | 6,873 | 120–1–135 | 47.0703125% | 54 / 54 | 27 / 217 | 0.005288082 |

累计963–14–1071，reward970/2048＝47.36328125%。两次pass各有独立完整permutation，尾批不跨pass；所有模型/AdamW张量有限、AdamW step等于global_step且LR/weight_decay未变，Python/NumPy/Torch RNG恢复roundtrip通过。c8加权policy loss−0.006236727、outcome BCE0.567866311、entropy0.977945776、normalized entropy0.292879813、KL0.003184389、clip fraction0.038483923；这些是minibatch更新前诊断，不是棋力或critic校准验收，grad_norm仍为裁剪前值。全逐step/分座/分对手数据及哈希在`campaign/cycle-{1..8}-summary.json`与`provenance/full-final-report.json`。

### Fixed development strength — same T=1 parent and seeds

父代与预设c1/c4/c8均为学得T=1，两个冻结greedy对手、128环境seed9420000..9420127双换座、相同action seed54010001。每模型512局，累计2,048固定局；独立fixed不写SQLite/Elo。配对seed-block percentile bootstrap10,000次，seed54019999，所有delta已复算。

| model | all W–D–L / score | Δ vs T=1 parent | 95% paired Δ CI |
|---|---|---:|---|
| Parent | 201–0–311 / 39.2578125% | — | — |
| c1 | 226–1–285 / 44.23828125% | +4.98046875pp | [+0.1953125,+9.67041015625]pp |
| c4 | 241–3–268 / 47.36328125% | +8.10546875pp | [+3.125,+13.0859375]pp |
| c8 | 280–1–231 / 54.78515625% | +15.52734375pp | [+9.765625,+21.2890625]pp |

| c8 opponent | W–D–L / score | 95% score CI | paired Δ vs parent / 95% CI |
|---|---|---|---|
| heuristic-v031 greedy | 138–0–118 / 53.90625% | [47.65625%,59.765625%] | +14.0625pp / [+6.640625,+21.484375]pp |
| prism-v01 greedy | 142–1–113 / 55.6640625% | [49.21875%,62.109375%] | +16.9921875pp / [+8.203125,+25.5859375]pp |

**判定**：c8相对同模式父代存在正向开发配对信号，不是仅训练奖励变化。但对两个greedy对手各自得分率CI仍跨50%，不能声称已确认超越它们；历史v0.1 greedy54.6875%不作为当前T=1父代基线。没有独立holdout、没有checkpoint选择/多重比较校正，也没有泛化/长期单调增强保证；不临时挑seed或改晋级门，**DEVELOPMENT_ONLY_NOT_PROMOTED**。

### Mixed pool — separate diagnostic, not a fixed gate

每段整个池256局阈值后允许单一在途局收尾，实为257局；四段合计1,028新增mixed局，旧10,854历史保留，最终pool completed11,882、paused、无pending/running/error。c1/c4身份保留且disabled；旧六模型配置/权重/程序/hash与历史不变，父代与c8身份保留。区间末Elo不同对手构成/旧ratings，不能直接比较为学习delta。

| model | mixed match IDs | whole pool / candidate games | candidate W–D–L | Elo initial → interval end |
|---|---|---|---|---|
| Parent | 10855..11111 | 257 / 69 | 36–0–33 | 1500 → 1561.90 |
| c1 | 11112..11368 | 257 / 62 | 32–0–30 | 1500 → 1517.17 |
| c4 | 11369..11625 | 257 / 62 | 30–0–32 | 1500 → 1554.43 |
| c8 | 11626..11882 | 257 / 63 | 38–0–25 | 1500 → 1573.61 |

### Timings, resources and preserved gaps

本地CPU串行Arena+驻留Python/Torch服务生成轨迹并更新；cloud2是Rust release固定评测/混池，不安装训练栈、没有数据回灌。

| cycle | pure game seconds | launch/collection seconds | ingest seconds（launch子项） | seal seconds | update+commit seconds |
|---|---:|---:|---:|---:|---:|
| 1 | 217.262 | 695.218* | 230.950 | 116.422 | 226.413 |
| 2 | 208.287 | 798.373 | 241.712 | 90.414 | 178.036 |
| 3 | 309.845 | 1038.087 | 254.346 | 83.502 | 154.377 |
| 4 | 306.904（补原837的1.609） | 979.791* | 220.737* | 76.110 | 125.253 |
| 5 | 385.895 | 1184.705 | 233.877 | 76.600 | 140.953 |
| 6 | 415.386 | 1198.258 | 206.993 | 62.061 | 106.543 |
| 7 | 479.619 | 1332.407 | 210.723 | 62.511 | 127.224 |
| 8 | 687.258 | 1842.268 | 237.407 | 85.349 | 126.054 |

`*`第1轮中断/恢复额外开销未全计时；第4轮原summary的game305.295补为306.904，attempt837的launch/ingest缺失不填零。原summary保持不变。**launch已含game和ingest，不能重复相加**。第8轮采集+seal+更新2053.670秒（约34m14s、448.76局/h）；第5轮1402.258秒（约23m22s、657.23局/h）。不同阶段速度变化未做因果profiling，不能据此认定模型/硬件原因。

c8云端512固定局process wall238.596秒（0.466s/局），完成文件时间跨度423.912秒（约7m04s），mixed257总池331秒（1.288s/局）。文件时间跨度是整批观察，非函数级profiling或同工作量硬件benchmark。

原campaign start1790834525.5010874→最后worker finished1790848267.4311717，wall13,741.930秒（约3h49m02s，含中断/等待）；原wall deadline1790863325.5010874未平移。独立追加额度最终实测user CPU3,268.671875秒、kernel CPU3,998.484375秒，supervised tree active0/exit0/stop_reason null；原24,000保守中断账仍单列，不冒称实测用满或总CPU只有补充值。campaign storage24,829,217,810bytes<96GiB；8GiB Job Object限额未报告资源stop，但峰值内存未记录，不编造peak。

### Exact validation and evidence

本次验证由parent执行，不称独立REVIEWED；未热改绑定训练源码。以下命令均实际exit0，scratch缩写为本会话`$env:PI_SCRATCH_DIR`：

1. `C:\Python312\python.exe -B <scratch>\m54_trial_parity_all.py`：c8既有68边界fixture逐元素`atol=rtol=1e-4`通过，c4已有证据按权重hash保留；不生成新局。c8 max abs logit9.918212890625e-5/value2.0962982172356703e-7。
2. `C:\Python312\python.exe -B <scratch>\m54_cloud2_collect.py`：下载所有已完成固定config/result/completion、paired delta和mixed summary，逐文件remote SHA256核对，旧结果漂移即停。
3. `C:\Python312\python.exe -B <scratch>\m54_remote_verify_driver.py --final`：2,048固定report/replay hash与真实结果/aggregate复算，1,028mixed与只读SQLite记录、结果及每局两条Elo history一致；旧六模型/程序/权重和旧全局引擎hash核对，controller complete/pool paused/no pending-running-error通过。0 DB写入/0新比赛/0规则重放。
4. `C:\Python312\python.exe -B <scratch>\m54_trial_report.py --final --verify-games`：全完成包hash、sidecar→接纳shard→消耗batch逐决策关联、记录动作/logp/输入/终局标签、同玩家terminal GAE及标准化、8个batch/permutation/尾批、finite模型/AdamW/step/LR、RNG恢复roundtrip、严格32键export tensor identity、attempt/physical决策/唯一job/双座seed/资源截止与配对bootstrap复算通过；不锁活跃Run、不新派局、不复算旧策略forward。
5. `C:\Python312\python.exe -B <scratch>\m54_speed_stats.py`：只读已有计时/文件时间，八轮及c8全量速度观察exit0。初始重新分开执行`git diff --check` exit0（仅LF→CRLF警告），publisher-state路径存在正常；上次组合检查exit1未复现，具体历史失败子命令无法追溯，不误记训练失败。

此前回归222 passed/3 opt-in skipped、opt-in3 passed、Rust CLI16 passed/2 ignored沿用已实际运行日志，本次没有为文档改动再跑整套或新smoke。资源测试的首次wall失败、Rust首次build失败及恢复/路径/引号失败保留在前节与local artifacts。

证据根`local-artifacts/prism/ppo-trial-v1/`，最终hash：

| artifact | SHA256 |
|---|---|
| `campaign/cycle-8-export/weights.json` | `cb7c4fb33ac7666706213ca4138f80104dacc5151b2385b9532bfebbe82025ac` |
| c8 tensor identity（32键） | `5685b14293040fc74cf9375902deed727ab4d3603a15858b69b6d236cc52d58d` |
| c8 training transaction commit（非Git） | `184f892d12f217bd6c15b8631dd7dfe575cf3269a273ae076a582d3d07cfc1bf` |
| `provenance/trial-reconciliation.final.json` | `8862a68046bbf67eece6ce8ed68e50f139fd05de667355501bf0e21c51389d39` |
| `provenance/full-final-report.json` | `1aaf6c1238b1ad1265894649b4aa7c6c1395d35e85af57e59c57debea9edb850` |
| `cloud2/remote-evidence.final.json` | `b48250314e2d39d28af4719cdc0466f88f3c8958df37477374ccebff54f8f6bd` |
| `cloud2/controller-state.final.json` | `520f10478542d49c95eb590f2b95ef7af68d942d4e61c388fc4c7a4c4c788237` |
| `cloud2/c8-fixed/result.json` | `46f688f8da6bb433b35d45a9031c76999dcf36ada60362c88352cb992ea22c12` |
| `cloud2/c8-paired-delta.json` | `f5cc6e74084bf059eeb04febefcf5803693800398b8d429ff5769fd8c023d8c2` |
| `cloud2/c8-mixed-summary.json` | `6c0ae78320e03edb96902c44843077553cf204113f30c17df5ccd2c1250f4db2` |
| `provenance/c8-parity.json` | `7410852eb626d3dbf830b7a40e377d8e4ed7606f1596ba254e28bc93a7a1689d` |
| `supplemental-resources.json` | `823da0eb4a926554c3cdcf001b32c9dff178e0a437bf300acbf8b588fc8fc4ac` |
| `provenance/speed-observation.json` | `79f423bc434e540b0b0cda2f60d16fef0e4ff97c79e5d3bb6b70e700e7d9ef27` |

tracked result现在为最终摘要`benchmarks/m54-prism-ppo-trial-v1.result.json`；旧08:33Z进行中JSON先按SHA归档为`provenance/trial-result.progress-20261001T083345.json`（`b879754716345c9585cde1a61d91212944d7123677cc2fb203463065ccac7f72`）。此前“引用存在但文件未实际创建”的更正仍保留，不被最终文件掩盖。训练seed与共同开发seed已按实际消费更新registry。

### Result, limitations and next authorized gate

本轮原定训练、c8跨语言检查、不可变发布、共同seed开发对照及有界混池已完成且指定证据检查PASS；**不是独立棋力验收/生产晋级，也不是整个持续PPO/风格项目COMPLETE**。原父代、全部checkpoint/负结果/中断账和cloud2历史保留。资源/实现无当前阻塞；尚缺独立holdout、checkpoint选择校正及风格验收，属下一门而非补跑本轮的理由。

下一步可讨论以c8为父代的另一个有界outcome-only续训合同，或冻结c8先做独立棋力验收；需要新run identity/seed/资源上限和预设门槛，不自动新增第九轮或再开2,048局。风格β仍0、GPU/并行Arena/PyO3/动态池不自动开工。handoff与生成资产local-only ignored，未stage/commit/push；保留所有并行无关改动。

## Stage IV bounded continuation — authorized 2026-10-01

Status: **CLOSED_DEVELOPMENT_ONLY_WITH_BOUNDARY_FAILURE / training and fixed development components PASS / FAILED_SHARED_POOL_BOUNDARY / NOT PROMOTED**. Authorization-time and live progress records below are historical; final evidence is appended at the end.
Baseline remains `main@bcdaca7cb33c53cc43d5dcc9e92c07be3c1aaa57` with unrelated worktree changes preserved. After Stage III completed, the user again requested “继续训练迭代吧”. This is a new bounded continuation, not an extension or rewriting of trial-v1's completed budget/results.

### Problem, design and frozen gates

Stage III c8 showed a positive same-T=1 paired development signal (+15.52734375pp), but has no independent acceptance evidence. Continue the same outcome-only learning objective from that **final c8**, not the best retrospectively chosen checkpoint. Preserve c8's complete model, AdamW moments/step and learner Python/NumPy/Torch RNG. New action seed, job identities and environment seeds are separately frozen; old batches/jobs are not copied into the new consumable ledger.

- New run: `m54-prism-ppo-trial-v2-outcome-only`, artifacts `local-artifacts/prism/ppo-trial-v2/`; tracked live contract `benchmarks/m54-prism-ppo-trial-v2.config.json` and separate initial lineage `benchmarks/m54-prism-ppo-trial-v2.continuation.json`.
- Exactly 8 cycles × 256 games = 2,048 jobs; two unchanged frozen greedy opponents (Prism v0.1, heuristic v0.3.1), each 64 environment-seed blocks × two learner seats per cycle. New training seeds **9430000..9431023**, development seeds **9440000..9440127**; registry reserved before execution.
- Unchanged PPO: CPU/Torch2, LR3e-5/AdamW weight_decay0, gamma1/lambda0.95, minibatch256, 2 passes, clip0.2, outcome BCE weight0.5, entropy0.01, gradclip1, exact pre-update minibatch KL-stop0.02, whole-batch advantage normalization; **beta/style value weight0**. Singleton gradient accumulation remains; no teacher CE, replay training, hidden critic or inference overlay.
- New finite resource budget: 24,000 aggregate user CPU seconds, 8h wall from initialization (no recovery deadline reset), 8GiB owned process-tree memory, 96GiB retained campaign storage; at most 2,064 game attempts/16 infra retries, 524,288 accepted and 528,384 physical decision reservations. Each game wall60s/user CPU30s/256 plies; the previous run's CPU charges remain historical and are not reset/refunded.
- Engineering gate before games: synthetic tests for exact model/optimizer/RNG continuation, no inherited consumable data, changed lineage/runtime/optimizer/contract rejection, initialization recovery and finite resource accounting. Use an outer initializer/supervisor, leaving frozen `training/prism/ppo/*.py` source identity unchanged.
- Fixed development only on cloud2: c8 parent plus prescheduled new c1/c4/c8, same new 128 seeds, both seats, both frozen opponents, learned T=1 and common action seed54020001; 512 games/model, at most2,048 fixed games total, existing 10,000-sample seed-block bootstrap seed54019999. Compare new checkpoints against **c8 parent on the new development seeds**, not against the old 39.2578% parent score or an unpaired old c8 score.
- Keep cloud2 mixed pool paused for this round; no new mixed/Elo games, no old model disabling/deletion/config changes, no shared engine replacement or training-stack deployment. Fixed results do not enter Elo and do not feed training. Independent holdout/selection correction and production promotion are **not** this gate.
- Final verdict remains DEVELOPMENT_ONLY_NOT_PROMOTED, even if development delta improves. Nonterminal/identity/nonfinite/resource failure retains evidence and stops; do not change seeds/LR/passes or silently discard difficult games. No automatic ninth cycle, style/GPU/PyO3/parallel Arena/dynamic opponent pool or Aran restart.

### Iteration log

1. Directly rechecked main/HEAD, empty staging area, ignored handoff/local-artifacts, previous final atomic training HEAD and cloud2 c8 ready/controller exit0. Previous supervised PIDs are absent. The old handoff IN_PROGRESS snapshot is stale history and is being corrected, not used to restart old jobs.
2. Existing `Run.create` always makes a new AdamW. For genuine continuation, implement a one-time outer initializer that hash-binds the completed source commit/config/payload/export, validates unchanged runtime/PPO/opponents, restores full model/AdamW/RNG into a new READY commit, and starts new local counters at0 with inherited-step provenance. Normal resume uses unchanged `Run.open`; it must never import again or reset counters.
3. The existing supplemental supervisor is tied to a historical interrupted run. Reuse its tested accounting/monitor functions in a normal-contract supervisor with a fresh bounded ledger and persistent 5s snapshots; do not falsely claim another supplemental authorization or alter old resource records.

### Current implementation, evidence and next gate

At authorization recording, no new games or optimizer updates have been run. Next: finish the small initializer/supervisor and tests, freeze exact lineage/live config hashes, initialize and launch the bounded serial learner, then deploy the fixed-only cloud2 observer. Validation/progress will be appended from actual commands; Stage III frozen raw evidence and old failures remain unchanged.

### Stage IV implementation and actual launch — 2026-10-01T11:57:48Z

The authorization-time zero-game statement above is historical. The new campaign is now running, without modifying frozen learner/encoding/source identity or trial-v1 final evidence.

- `scripts/prism_ppo_continue.py`: one-time hash-bound import at the completed source boundary. Model (including the disabled training-only style head), AdamW moments/step and Python/NumPy/Torch RNG are exactly preserved in the new READY commit. Old schedules/shards/batches, consumed IDs and resource ledgers are not imported. Inherited436 steps are provenance, while new logical steps/attempts start at0. Resume validates the committed origin and uses normal recovery, never re-imports.
- `scripts/prism_ppo_campaign_supervisor.py`: normal-contract budget, not another supplemental grant; reuses the existing Job Object monitor and conservative interruption charging. Stores user/kernel CPU every5s and retains the initialization-based8h deadline on resume.
- `scripts/prism_ppo_fixed_watch.py`: stdlib fixed-only watcher for parent/c1/c4/c8; no pool/SQLite API calls or training data writes. Cached completed evaluation is reused, config/checkpoint hashes are immutable, deadline is persistent and bounded. Uses the unchanged fixed evaluator and seed-block paired bootstrap helper.
- Initialized through `C:\Python312\python.exe -B -u <session-scratch>/m54_v2_setup.py` (**exit0**). Source final training commit `184f892d12f217bd6c15b8631dd7dfe575cf3269a273ae076a582d3d07cfc1bf` remains unchanged. New identity `6f1010b4e98e12cb005b0ca21b2c645d00f8514811847405f015f5829e8d7bff`, initial import commit `b8603f29fdc540664e3f0a456a25ea27f9f3f832d269ea87f01f84f083f2c2d8`; these are training transactions, not Git commits.
- Initialization model digest `f95250e6f2a1fbbba251a93b1e8992890b1458e383997ad04dcf4ec5eb9a6e81`, optimizer digest `a0cd292691ea29d1040217221811b6e9c997a2c46ec6250f79b9f010761a4c3a`, RNG digest `0733278f1692c14d04ad193e0451102ae46e0fd3f4f0ccf2e5b58e8b65c42ef8`. Model/optimizer/RNG digests describe exact initialization equality, not new competitive strength.
- Spawned independent Windows hosts via `Win32_Process.Create` to survive tool-shell cleanup: supervisor2576/worker3100 (wrapper34576), publisher28720 (wrapper8000). Resource snapshots and logs are in `local-artifacts/prism/ppo-trial-v2/{resources.json,train.stdout.jsonl,train.stderr.log,publisher-state.json}`. Do not call `Run.open()` merely to inspect an active writer; use atomic HEAD plus read-only CommitStore.
- Cloud2 `/home/ubuntu/splendor-m54-trial-v2/start.py` actual **exit0**, watcher389487; exact source engine/opponent/weight hashes checked before start. Read-only pool baseline is paused, completed11,882, no pending/running/error; all model rows saved in `pool-baseline.json`. No model/Elo/DB/config mutations or new mixed matches, and the old global binary remains unchanged. Existing Rust release is reused without compilation or Torch deployment.
- At11:57:48Z the new run is COLLECTING cycle2 with262 completed jobs,7,005 accepted decisions,54 new optimizer steps/attempts,1 consumed batch; AdamW total490. c1 completed256 games,134–2–120,6,846 decisions,2×27 minibatches, `passes_complete`, max pre-update minibatch KL0.00710653638878877. New training reward is not same-seed strength. c1 export SHA `c68f7cf00aa922d67715a3221a2a8d1e24cab53183c86a27e038f8e6407ef8d5`, commit `ef7413725c307bda49c8e825a11d82643898525f1114758f1856319665dcc28e`; immutable cloud publication completed shortly afterward.

Validation actually executed (synthetic tests do not launch formal games):

1. Syntax AST parse for initializer/supervisor **exit0**. The initial small import edits were detected by immediate readback and corrected before execution; no games were dispatched with that malformed intermediate file.
2. `C:\Python312\python.exe -B -m pytest -q -p no:cacheprovider training/prism/tests/test_ppo_continue.py training/prism/tests/test_ppo_recovery.py training/prism/tests/test_ppo_resource_supervisor.py --basetemp <session-scratch>/m54-v2-tests-first`: **exit1**,39 passed/1 failed83.34s. New test incorrectly called nonexistent `Behavior.from_model`; fixed to the existing constructor and `prepare_batch(..., max_decisions=100, verify=False)`. This was a test API mistake, not a failed formal training run.
3. Same test set with `--basetemp <session-scratch>/m54-v2-tests-final`: **exit0**,40 passed82.55s. Covers exact import, fresh consumption/counters, source HEAD immutability, equivalent next AdamW step, lineage/config/source drift refusal, committed origin recovery and resource-gap charging without deadline reset.
4. `C:\Python312\python.exe -B -m pytest -q -p no:cacheprovider training/prism/tests/test_ppo_fixed_watch.py training/prism/tests/test_ppo_fixed_eval.py training/prism/tests/test_ppo_checkpoint_publisher.py --basetemp <session-scratch>/m54-v2-fixed-tests`: **exit0**,11 passed2.33s; fixed cache/deadline/hash refusal and no pool mutation. Logs are preserved under v2 `provenance/`.
5. `git -c core.safecrlf=false diff --check`: **exit0** when run separately; an earlier combined status command returned nonzero without a diff finding, and is not counted as a successful check. `git check-ignore -v handoff.md local-artifacts/prism/ppo-trial-v2/resources.json` confirms local-only boundaries. Git remains main/baseline with an empty staging area; no stage/commit/push.

| Frozen startup evidence | SHA256 |
|---|---|
| `benchmarks/m54-prism-ppo-trial-v2.config.json` | `ce89bc334d7cf755ac109ba2dfb048072873c80a129503a6641c5d45cb31af87` |
| `benchmarks/m54-prism-ppo-trial-v2.continuation.json` | `ad81dc3445470ef4bc68c4e2461295001476e3c0feb902fb9b1ce924901483a3` |
| `local-artifacts/prism/ppo-trial-v2/campaign/continuation-receipt.json` | `a243e3ce9681aa49db3fa78106463e2c62b0244de7d3f35c62091f448c455ea6` |
| `local-artifacts/prism/ppo-trial-v2/provenance/setup.json` | `f96afbe4db6e0172336957f101e445aa60e460c7f862dc6c02dfc98fad2c44ee` |
| `scripts/prism_ppo_continue.py` | `77d8ddbdfa47a59e792db5032a5b0d2be1214e58511ce2402a81e4cb6705f9ef` |
| `scripts/prism_ppo_campaign_supervisor.py` | `816d3982673f94de86c0a6e20b779352575d8aab98ced36e385349d4ef0bd6c5` |
| `scripts/prism_ppo_fixed_watch.py` | `30ec85460786bdc56887f7389d5f609adec2db9ceab8204c41307da58ce790de` |

Current decision: continue only the frozen8×256 serial campaign, check prescheduled c1/c4/c8 parity and fixed development deltas against the new c8 parent baseline, then reconcile the bounded run. No implementation blocker at this snapshot. Until actual completion, do not mark all2,048 new games, later checkpoints, final resource totals or strength as VERIFIED. No new mixed Elo is expected this round; the absence of a new mixed score is intentional, not an inference from fixed results.

### Stage IV c1 development result and interruption recovery — 2026-10-01T12:27Z

- `C:\Python312\python.exe -B -u <session-scratch>/m54_v2_parity.py --cycles 1` **exit0**:68 existing boundary states, atol=rtol1e-4; max absolute logit difference9.918212890625e-05 and value difference1.4331130981926066e-07. No new fixture games.
- Parent and c1 fixed evaluation each completed512 games. New c8 parent278–2–232/54.4921875%; new c1 287–3–222/56.34765625%. Paired c1−parent **+1.85546875pp,95%CI[-2.734375,+6.54296875]pp**: improvement remains unresolved. Per-opponent c1 heuristic150–1–105/58.7890625%, Prism greedy137–2–117/53.90625%; paired deltas+3.3203125pp (CI[-3.515625,+10.3515625]) and+0.390625pp (CI[-5.859375,+6.4453125]). Do not change seeds/LR/gates after this observation. Cloud watcher now waits for c4; pool remains paused, no new mixed/Elo.
- Direct recursive scp of parent artifacts timed out, without stopping cloud evaluation. Recovered by a single completed parent+c1 tar archive; SHA `6eb408bd6f421b59088ab4fd27b9c5a4e2653d438847b9f10fa1ce5b6ac6ee53` verified after transfer. Local copies under v2 `cloud2/`; duplicate copied files are evidence, not new games.
- Read-only `m54_v2_verify_progress.py` first **exit1**: verifier incorrectly sorted source games before checking `games_sha256`. Actual seal binds original schedule order; direct read proved saved hash equals that order. Corrected verifier only, retained failed log. Corrected execution **exit0**, checking1 committed cycle/256 training completion packages and1,024 fixed report/replay/game/progress hashes, own-player GAE/sidecar→shard→batch join, two saved permutations/tail batches, model/AdamW continuity and paired bootstrap. Evidence `provenance/verified-progress-1790857278.json` SHA `6635e0fe2371ed21cbae1a86d52f369090fec73eb827a5b516099dedc5fabafd`; no rules replay/old behavior forward/new games/updates.
- At12:21Z status revealed resource snapshots and training HEAD stale. Direct Win32 process scan confirmed original supervisor2576/worker3100/publisher28720 and wrappers absent, with no returncode/traceback. Cause is **UNKNOWN_EXTERNAL_PROCESS_EXIT**, not a diagnosed PPO/resource defect. Last measured aggregate user CPU1164.125s/kernel1252.125s at12:12:35Z; stopped at logical467 games/54 updates, while attempt468 already had a normal complete30-decision package and launch ledger `FINISHED_PENDING_AUDIT`. Interrupted records are preserved under `provenance/interruption-1/`.
- First recovery preflight safely aborted because a broad command-line regex matched its own PowerShell command; no worker was spawned. Narrowed check to Python/engine processes, observed all owned processes absent, then resumed same contract with independent Windows hosts. Resource supervisor conservatively settled session0 to **14753.060775756836 user CPU seconds charged**, leaving **9246.939224243164s** of the original24k limit; this is an upper-bound charge, **not measured CPU consumption**. Original8h deadline1790883166.4368386 and publisher deadline unchanged. No new resource grant/refund or source/config changes.
- Restored supervisor24444/worker31380 (wrapper31052), publisher11536 (wrapper4720). Actual recovery evidence **exit0** confirms model/AdamW/RNG unchanged, no optimizer updates/retries, attempt468 consumed exactly its original package without replay, and original commit remains in the chain. Evidence `provenance/interruption-1/evidence.json` SHA `45bd00a98d2783965c6e825e60bc52fd28e4b0c47d9d791fb932f87c486ebaa7`, completion SHA `ed355c274c3af4a55e5cc0dd7aff992e4086d8ec910a46156a7dd6f3894a6e37`. Attempt468 original game wall1.3909999999996217s is available; recovery omitted launch/ingest/game-wall fields from the normal cycle-summary ledger. Preserve raw summary; final reconciliation will append corrected game wall and explicitly unknown launch/ingest, never zero-fill.
- Read-only status observer now flags resource snapshot age>30s and returns early on stale state; this is an outer observation script, not a training source edit. At12:28Z both rounds'512 real games are sampled and cycle2 updates are starting, stderr0. Continue unchanged finite campaign using remaining resource budget; do not mark later checkpoints or final strength complete from this snapshot.

### Stage IV five-cycle progress and c4 development result — 2026-10-01T15:11:01Z

This is an actual progress snapshot, not a final verdict. The original8-cycle contract, seeds, opponents, LR and24k CPU/8h limits remain unchanged after the user's “继续”. Five cycles are committed; cycle6 is still collecting. Do not infer later completion from this table.

| Committed cycle | Games | Learner decisions | Wins–draws–losses | Training mean reward | New steps/attempts | Max pre-update KL |
|---|---:|---:|---|---:|---:|---:|
| 1 | 256 | 6,846 | 134–2–120 | 52.734375% | 54/54 | 0.00710653638878877 |
| 2 | 256 | 6,868 | 132–0–124 | 51.5625% | 54/54 | 0.008398700961846934 |
| 3 | 256 | 6,846 | 139–4–113 | 55.078125% | 54/54 | 0.0050478386095099805 |
| 4 | 256 | 6,853 | 159–2–95 | 62.5% | 54/54 | 0.006278310550396734 |
| 5 | 256 | 6,918 | 147–2–107 | 57.8125% | 56/56 | 0.007029589332849158 |

- All five stop reasons are `passes_complete`, with separate pass permutations and tails; committed totals1,280 games/34,331 decisions/272 new updates, inherited436+272=708 AdamW steps. At15:11:01Z the atomic status is COLLECTING cycle6,1,505 complete jobs/40,321 accepted decisions. Supervisor24444/worker31380/publisher11536 are directly observed alive; resource snapshot age0.824s, no errors, both training and supervisor stderr empty. These observations do not prove future uptime.
- Session1 persisted measured user CPU4687.15625s/kernel5567.265625s; session0 retains its14753.060775756836s conservative user-CPU **charge**, not measured consumption. Remaining reservation within the original24k is4559.782974243164s at this snapshot. Deadline1790883166.4368386 is unchanged; no extra authorization/refund. Peak memory is not recorded.
- c4 fixed evaluation512 games **297–3–212 / score58.30078125%**. Relative to this round's parent278–2–232/54.4921875%, same-seed paired delta **+3.80859375pp,95%CI[-1.5625,+9.1796875]pp**. Both c1 and c4 improvement intervals cross0; continue the frozen schedule without selecting a different checkpoint or changing parameters.
- c4 opponent breakdown: heuristic147–2–107/57.8125%, delta+2.34375pp CI[-5.2734375,+10.15625]; Prism greedy150–1–105/58.7890625%, delta+5.2734375pp CI[-2.734375,+13.28125]. Training reward is from different seeds each cycle and is not a paired strength delta.
- `m54_v2_parity.py --cycles 4` previously executed **exit0**,68 existing boundary fixtures, combined atol=rtol1e-4: max absolute logit difference0.0001068115234375/value2.1031272889882047e-07; absolute maximum alone is not the combined tolerance criterion. Evidence `local-artifacts/prism/ppo-trial-v2/provenance/c4-parity.json` SHA `3ad911cae81867ecd2fbf30e1973a2a9f03a8db46356ab9e0b58aa3c1d2c63c6`.
- c4 weights SHA `ab5d3ab96b867d3d996fd732060918209c2bdd6d18bf9f1c4a18cf7588c55b63`, training commit `49c18bfa3991eda48e76588d2e8d83c3bee4ac0dc2354376e4f42bfbed23c8de`; fixed result SHA `de8421ec4af3ed471799a6110faf89511ef057476f526dbff11eee2c65702ae9`. Completed c4 archive transferred with matching remote/local SHA `4eea5a2f38990c995af1c7eef8b3f2051936dbba7e4fcd87ff41edbef1281d63`; no rerun of completed evaluation.
- Prior two-cycle+parent/c1 read-only reconciliation **exit0**, `provenance/verified-progress-1790858124.json` SHA `9539b56c4509f3835803183eb83ebed25debf985b6e9a068dc687003f5153b1a`. The expanded five-cycle+parent/c1/c4 verifier's first invocation hit **TOOL_TIMEOUT** at600s with empty logs/no published result; it is not counted as PASS. Observed verifier absent, then relaunched it under an independent host with progress/exit logging; only the scratch observer changed, not training source or raw evidence. Its result will be appended when actually available.
- Direct cloud2 observation at15:10Z: watcher389487 alive, stderr0, parent/c1/c4 rounds complete, waiting_for=c8/error null.1,536 fixed games are complete and this round intentionally has0 mixed/Elo games. Final gate still requires c6–c8, c8 parity/publication/fixed comparison, resource and complete consumption/asset reconciliation; DEVELOPMENT_ONLY_NOT_PROMOTED remains the bound.

- 15:21Z observer-only iteration: the independent verifier was consuming10,442,108,928 bytes private memory while retaining `games` plus duplicated expected inputs. Terminated **only verifier32732**, after checking its executable/command identity; host preserved exit4294967295, elapsed390.859s and partial progress logs. This is not a training interruption: supervisor/worker remain alive, phaseUPDATING cycle6/global_step284, snapshot fresh/stderr0. Preserved original observer under `provenance/verify-progress-1790868083.original.py`; rewrote scratch reconciliation to retain one batch plus one game, hash original schedule order incrementally with canonical-equivalence fixtures, and compare each game's rows directly. Also freezes available exports before reading the ledger, adds per-game CPU/wall/plies checks, RNG roundtrip and export tensor identity. No training source, raw package or gate changes. New invocation remains pending until a real exit0/result is observed.
- New cloud2 read-only verification **exit0**: `remote-readonly-verify.py` confirms paused pool/11,882 completed/no other status, **all model rows including Elo/stats unchanged**, engine/opponent/parent/script and old global binary hashes unchanged, parent/c1/c4 completion/result identities match. Evidence `local-artifacts/prism/ppo-trial-v2/cloud2/remote-evidence.progress-1790867800.json`; final c8 check still pending. This check made no DB writes, new matches, compile or rules replay.

### Stage IV reconciliation PASS and cycle6 commit — 2026-10-01T15:40Z

- Bounded-memory verifier actual **exit0**,795.1515s, wrapper exit recorded under `provenance/verify-bounded-1790868320.exit.json`. It checked all1,280 committed training packages from cycles1–5 and all1,536 parent/c1/c4 fixed report/replay/game/progress records, result aggregates and10,000-sample paired bootstrap. Includes same-player terminal GAE, exact sidecar→shard→batch input/action/logp/value target join, raw advantage normalization, saved pass permutations/tails, finite model/AdamW, inherited436+272 step continuity, RNG restore roundtrip,32-tensor export identity, per-game CPU/wall/plies caps and original schedule-order streamed canonical hash equivalence. No games/updates/rules replay/old-policy forward. Evidence `provenance/verified-progress-1790869114.json` SHA `2c03c3e74c73918bd5b5e4ee989e794e03cf895779026dde600b70263f0a433c`; real exit file SHA `731c985878e414efc3d255738ba5a859bdc3ea2c301b1a426020b43679b58222`. The earlier timeout and terminated high-memory observer remain recorded, not relabeled PASS.
- Attempt468 remains the sole timing gap. Cycle2 original summary game wall309.5309999999736s, all original completions310.9219999999732s; difference1.391s is the original completed game, not another match. Missing launch/ingest still unknown. Original summary/completion unchanged.
- Cycle6 has now actually committed256 games/6,824 decisions/152–0–104, training reward59.375%,54 new steps/54 attempts, `passes_complete`. Totals1,536 sampled/committed games,41,155 learner decisions,326 new updates/AdamW762. This cycle is not yet included in the five-cycle verifier's scope. At15:39:12Z cycle7 is COLLECTING,1,596 completed games/42,756 decisions; resource fresh/stderr0. Continue same budget; later c7/c8 not complete.
- Remote progress evidence output was accidentally encoded UTF-16 by Windows PowerShell redirection. Preserved its exact bytes as `cloud2/remote-evidence.progress-1790867800.original-utf16.json`, normalized only the local copy to UTF-8 and checked JSON semantic identity. Normalized SHA `6a39b2af8b720fa2b9c7f51f27391b390bab1ad5d2665b4c8274c517baec7327`, encoding receipt `provenance/remote-output-encoding.json`. This is an evidence transport correction, not a rerun or cloud-state change.
- `m54_v2_doc_check.py` actual **exit0**:15 links/79 disjoint seed ranges, all startup hashes, main/HEAD/staging and ignored publication boundaries match; Git diff check exit0. Final-gate scratch script syntax AST PASS only; its acceptance conditions have **not yet been executed or passed**. No new tracked final result exists at this snapshot.

- 16:00Z follow-up: cache continuation self-check `m54_v2_verify_progress.py --max-cycle 5 --use-five-cycle-cache` actual **exit0**. Hash-binds the previously completed five-cycle evidence and real exit file, checks retained export/summary/result identities and recomputes fixed paired deltas; it intentionally does not rescan previously verified game bytes. Receipt `provenance/verified-progress-1790870392.json` SHA `51325d4b362ca7002d2dc7431d272c1eab21670baa9f6a3d6f53d479af21f8b2`. Final reconciliation may reuse that immutable verified scope and explicitly list it, then fully scan only new cycles6–8 and c8 fixed games. This changes observer cost, not Arena acceptance/training or the requirement that every completed package has been checked.
- Added a bounded scratch-only closeout observer that waits for the original resource-complete state, c8 parity/publication/fixed completion, then collects completed evidence and runs the new-cycle/c8 reconciliation and final budget gate. It never initializes, launches training or new games, changes DB/config or extends deadlines. No final PASS is claimed by its existence; errors persist and stop for inspection. At15:55Z training cycle7 had1,684 complete games/45,088 decisions,326 updates, fresh snapshot/stderr0; original CPU charge20739.498275756836s includes the historical conservative interrupted charge, leaving3260.501724243164s at that snapshot.

### Stage IV seventh cycle committed — 2026-10-01T16:28:29Z

Cycle7 actual256 games/6,811 decisions,153–3–100/reward60.3515625%,54 steps/54 attempts, `passes_complete`, max pre-update KL0.0050705210465107125; summary SHA `df74cf015fbfa9f506f978f7beae23e72ba2106f6b882c9caaf87c99c931f22e`. Seven committed cycles total1,792 games/47,966 decisions/380 new updates, AdamW816=436+380. Atomic state now COLLECTING cycle8,1,795 completed games/48,042 decisions; resource fresh, stderr0. Session1 persisted measured user7002.59375s/kernel7923.359375s, remaining2244.345474243164s within the original24k after the unchanged interrupted charge; no supplemental grant. Cloud watcher389487 directly alive/stderr0, waitingc8. Final training/evaluation and full gate remain pending; five-cycle evidence scope is not expanded to seven by this status observation.

### Stage IV training actually finished; evaluation still in progress — 2026-10-01T17:21Z

- All8 cycles are now COMMITTED:2,048 games/54,802 learner decisions/434 new optimizer steps and434 update attempts, AdamW total870=436+434. Cycle8 is164–0–92/reward64.0625%,6,836 decisions/54 new steps, `passes_complete`, max KL0.005969897033833833; summary SHA `bd6c6941fa5df9aff7bb1ec8163388316f3793dede6caf74c811e5d2ae6426ee`. This is real training completion, not yet full experimental/strength closeout.
- Worker completed **exit0/active0/stop_reason null** at1790875180.7884464. Resource supervisor published **complete=true/error null** at1790875219.2870831 and its wrapper also returned0. Original deadline1790883166.4368386 retained; user-CPU total **charge23107.935775756836s≤24000**, consisting of session0 conservative14753.060775756836 plus uninterrupted session1 measured8354.875s user/9669.078125s kernel. Interrupted session0 last persisted actual1164.125 user/1252.125 kernel remains separately recorded; the total charge is not actual CPU consumption.
- c8 immutable weights `a2301f0878f9c342a61b83fd45412f72ba95acfca895dafbe7ceca0360f34a85`,32-tensor identity `7d0e3c3eb2dee3cd94c2964e02391067e2c43d5ead45810e4fded7b23295a65f`, final training commit `99ef5b5fbb3e10643af9212135de085fa3cd718a1344712600f350b17fa2c6b6`. Publisher complete/error-free at1790875213.3142354; cloud2 c8 fixed evaluation has begun, no mixed/DB writes.
- First closeout observer failed at1790875214.4862955: it applied the running-snapshot age>30s check after session1 was already FINISHED/active0 but before the supervisor's33-second read-only `Run.open` finalization completed. This is a diagnosed observer timing false alarm, **not an external training interruption**. Actual supervisor/worker/publisher then exited0 normally. Retained exact failure as `provenance/closeout-observer.failed-post-worker.json` and original stderr/exit logs. Corrected scratch observer to apply stale detection only to RUNNING sessions, bound FINISHED finalization waiting to120s/original deadline, and use a separate second observer-state path. No training resume/reinitialization, source/config/budget edits, refund or replayed games/updates.

### Stage IV final cloud pool gate failure — 2026-10-01T17:37Z

c8 parity actual **exit0** on68 existing fixtures (max abs logit9.918212890625e-05/value1.7992324830018447e-07, atol=rtol1e-4); cloud fixed watcher then completed all four×512 evaluations/error null at1790876162.5074956. However, final collection **exit1** before transfer: the unmodified read-only remote verifier asserted `settings.paused=='1'` and found the shared pool no longer in the frozen startup state. Failure `provenance/closeout-m54_v2_cloud_collect-1790876167.stderr.log` is preserved. This is a real external-state boundary finding, not a transport failure and not evidence of a training/PPO or fixed-evaluator defect. Do **not** label the pool-unchanged final gate PASS or overwrite/pause another user's concurrent state. Next authorized action in this round: read-only snapshot the actual DB/model/assets differences, retrieve already completed c8 fixed artifacts without rerunning matches, finish independent training/fixed reconciliation, and report the pool-boundary gate separately as failed/unresolved. Do not change frozen gates or claim actor/cause without evidence.


## Stage IV final closeout — 2026-10-02 (Asia/Shanghai)

### Final implementation and result

The original finite trial-v2 is complete: eight cycles ×256 =2,048 unique jobs on1,024 dual-seat seeds;54,802 learner decisions/109,626 plies;434 new optimizer steps and434 attempts;AdamW total870=436 inherited+434 new. Eight unique sealed batches were consumed once. All cycles stopped with `passes_complete`; no infra retries, normal rules replays or old-policy `Behavior.verify` forwards. Exact parent model/AdamW/RNG continuation and source HEAD immutability remain verified. The compact result index is [trial-v2 result](../benchmarks/m54-prism-ppo-trial-v2.result.json); per-cycle tables and hashes are machine-bound there.

| Fixed model | Games | W–D–L | Score | Paired delta vs this round's parent (95% CI, pp) |
|---|---:|---|---:|---|
| parent | 512 | 278–2–232 | 54.4921875% | baseline |
| c1 | 512 | 287–3–222 | 56.34765625% | +1.85546875 [-2.734375,+6.54296875] |
| c4 | 512 | 297–3–212 | 58.30078125% | +3.80859375 [-1.5625,+9.1796875] |
| c8 | 512 | 323–4–185 | 63.4765625% | +8.984375 [+3.515625,+14.453125] |

All2,048 fixed games use common128 seeds9440000..9440127, both seats, two frozen greedy opponents, learned softmax T=1/action seed54020001 and paired seed-block percentile bootstrap10,000/54019999. c8 vs heuristic-v031:160–4–92/63.28125%, paired+7.8125pp CI[-0.390625,+15.625] (still crosses0); vs Prism greedy:163–0–93/63.671875%, paired+10.15625pp CI[+2.34375,+18.1640625]. Training rewards use different cycle seeds and are not paired strength deltas. This is positive development evidence with no independent holdout, checkpoint-selection correction, independent review or production acceptance.

### Resource and timing limitations

Total user CPU **charge**23,107.935775756836s≤24,000 = conservative interrupted charge14,753.060775756836 + final-session measured user8,354.875. Final-session kernel CPU9,669.078125s; persisted measured lower bounds user9,519.0/kernel10,921.203125. Complete actual CPU remains unknown across the interruption; charge is not measurement. Initialization→worker finish wall20,814.35160779953s is within the original8h deadline1790883166.4368386, unchanged on resume. Campaign storage25,894,328,153bytes≤96GiB. Training peak memory is **NOT_MEASURED**; historical observer private memory10,442,108,928bytes exceeded8GiB, so project-wide8GiB peak compliance is unverified. Worker/publisher final exit0; no active final worker processes. Attempt468 original game wall1.391s is known; launch/ingest remain unknown. Raw cycle summaries are preserved and eight timing reconciliations are in the full report.

### Shared-pool failure and owner clarification

Historical snapshot **2026-10-01T17:39:43.614418+00:00** (2026-10-02 01:39:43 Asia/Shanghai): baseline11,882 completed/paused →14,490 completed+1 running/unpaused; global new2,608 completed+1 running, ids11883..14491, first new start16:35:05Z. Elo/stats rows changed for ids1,2,3,4,5,6,7,10; model identity/config/enabled, model registrations and shared assets/global binary were unchanged at that snapshot. These are historical observations, not today's live pool state. The strict remote collection exited1 because the original paused/history/model-row invariant failed.

**Correction from the owner on2026-10-02:** the owner explicitly reported manually解除pause because they did not know the ongoing match-verification context. Current attribution is `OWNER_REPORTED_MANUAL_UNPAUSE`, from direct user testimony; exact action time is unknown and no independent audit log was checked. It is not evidence of an automatic unpause bug. Historical `UNKNOWN` remains in the immutable report/gate, with a separate hash-bound [owner clarification](../local-artifacts/prism/ppo-trial-v2/provenance/owner-pause-clarification-20261002.json). Trial-v1 used mixed-pool stages; trial-v2 itself was fixed-only. The v2 pipeline launched0 mixed games/wrote0 DB-Elo; that does not mean the shared pool launched0 global games. Extra global matches were excluded from v2 training and paired strength evidence. No pool pause/resume/rollback was performed during this closeout. The historical contract gate is not retroactively passed or relaxed.

### Validation and evidence

Existing parent-authored reconciliation `m54_v2_verify_progress.py --max-cycle 8 --use-five-cycle-cache` actually exited0/293.1988649368286s: reused hash-bound cycles1–5/1,280 training and parent/c1/c4/1,536 fixed; newly scanned cycles6–8/768 training and c8/512 fixed; combined coverage2,048+2,048. It checked completion/filehash, sidecar→shard→batch, same-player terminal GAE/normalization, saved sampling data, pass permutations/tails, model/AdamW/RNG/export identities, single-game caps and fixed aggregates/paired bootstrap. This closeout reused that verified scope instead of rescanning every game byte. No new games or optimizer updates.

Split reporter first exited1 (`KeyError: final_head`); corrected only the observation field to `verified['cycles'][-1]['export']['training_commit']`, then exited0/7.336257696151733s. Report generation exit0 is not all-original-gates PASS. Original strict reporter and all failure logs remain.

| Component gate | Verdict |
|---|---|
| training consumption/exact state | PASS |
| logical/physical CPU/wall/storage | PASS |
| c1/c4/c8 Python–Rust parity/publication (68 existing states each, atol=rtol1e-4) | PASS |
| completed fixed development | PASS |
| shared assets at historical snapshot | PASS |
| shared pool paused/rows unchanged | FAILED_STATE_DRIFT |
| training peak memory | NOT_MEASURED |
| independent strength acceptance | NOT_RUN |

Actual current command (run after corrections):

```powershell
C:\Python312\python.exe -B -u local-artifacts/prism/ppo-trial-v2/provenance/validate-result-index-20261002.py
```

**exit0,1,080 assertions,54 unique hashed files.** Scope: compact↔full/candidate mapping, all referenced evidence hashes,7 frozen startup hashes,8 cycle summaries/exports,4 fixed results/deltas/archives and parity, final run/source/ledger HEADs, final state/counters/AdamW, canonical config/lineage/source identity, schedules/dual seats,79 disjoint registry ranges and exact consumed labels (both consumed segments correctly reject reuse with exit1), resource/timing limitations, historical exit codes and failure statuses. Sandbox Python could not access existing user-site NumPy/Torch; the approved same-interpreter run used already-installed packages, without installing dependencies. New validator iterations fixed compact-cycle comparison (summary hashes are intentionally omitted), JSON→float32 tensor conversion and UTF16 historical test-log decoding; these were validator issues, no experiment artifact was changed. Local iteration logs retain the failure explanations.

| Evidence (under `local-artifacts/prism/ppo-trial-v2/`) | SHA256 |
|---|---|
| `provenance/full-final-report.json` | `fb37e5120e981e459887c7abe01cce1372a5233f4136d863379186ed3a7474e0` |
| `provenance/final-gate.json` | `05bd954da258319d47439c4efb4967c8f6726713ec2e2b313b87fd5a8969c2b8` |
| `provenance/verified-progress-1790876729.json` | `e4d24664e735bdc8317a1a5eaa127fcda70b45570457f987ead03b83b167a9e3` |
| `provenance/verify-final-1790876436.exit.json` | `9452a563ce6ea9317e5770c32f7def1e565d0c24281d716583a38ff8b7927061` |
| `cloud2/remote-actual-state.final.json` | `6ba348b28f0209405391e0e8f4d34da768b821404cd2eec0d1bdf18ee850fcb4` |
| `provenance/result-index-validation-20261002.json` | `9144c0b0d27085c88b9642b8613fb53b68b083bfdd8036469c5d0f2089b6c9dc` |

Final export `campaign/cycle-8-export/weights.json` SHA `a2301f0878f9c342a61b83fd45412f72ba95acfca895dafbe7ceca0360f34a85`; tensor identity `7d0e3c3eb2dee3cd94c2964e02391067e2c43d5ead45810e4fded7b23295a65f`,32 policy/value keys. Final training transaction `99ef5b5fbb3e10643af9212135de085fa3cd718a1344712600f350b17fa2c6b6` is not a Git commit.

### Result, decision and next authorized gate

**CLOSED_DEVELOPMENT_ONLY_WITH_BOUNDARY_FAILURE / DEVELOPMENT_ONLY_NOT_PROMOTED / overall_contract_gate=FAILED_SHARED_POOL_BOUNDARY / all_original_gates_passed=false.** Keep the positive fixed development result and failed historical shared-pool boundary separate. Owner testimony resolves the unpause attribution, not the original invariant or unknown external training-process exit. Singleton accumulation, beta0/untrained styles, no GPU/PyO3/parallel Arena/dynamic pool and memory/holdout limitations remain.

The user's continuation request authorized completing the attachment's remaining index/document closeout. That scope is now complete. Preserve artifacts and select a new finite continuation or independent holdout scope before dispatching more games; no cycle9/third campaign/pool mutation/deployment/Aran restart is implied. Git remains at the baseline, with unrelated worktree edits preserved; no stage/commit/push. Publication and navigation checks are recorded separately in the local final-document receipt.


## Stage V outcome-only model acceptance and host timing — authorized 2026-10-02

Status: **NOT_ACCEPTED**. The owner explicitly requested immediate match evaluation to decide whether final trial-v2 c8 is a formal iteration artifact and can receive a new version, plus an empirical local/cloud2 speed comparison. Trial-v2 remains historically closed; the manual shared-pool unpause is unrelated to this new strength gate.

### Problem, scope and frozen gates

Freeze exactly trial-v2 final c8 (a2301f08…) against its trial-v1 c8 parent (cb7c4fb3…), T=1/action seed54030001; no training, alternative checkpoint or parameter selection. [Acceptance contract](../benchmarks/m54-prism-v02-acceptance-v1.config.json) reserves fresh holdout9450000..9450255: two greedy anchors ×256 seeds ×2 seats ×2 models=2,048 games, plus direct c8-vs-parent256 dual-seat blocks=512, total2,560. Holdout is forbidden for future training. Separate speed seeds9460000..9460007 give32 identical candidate/anchor/seat games per host (64 physical total), excluded from acceptance.

Four preregistered one-sided gates must all pass: pooled common-anchor candidate-minus-parent lower>0; direct-duel candidate score lower>0.5; each of two anchor deltas lower≥−5pp. Use20,000 paired seed-block percentile bootstrap draws/seed54039999, family alpha0.05 with Bonferroni alpha0.0125 per lower bound; also report ordinary two-sided95% intervals. The5pp guard prevents a material anchor regression; it is specific to outcome-only version acceptance, not any pending style/noninferiority-cohort gate. Exactly one final analysis, no adaptive extension/seed replacement. Size doubles the earlier128-block development grid; precision may still be insufficient, which must be reported rather than treated as a defect or padded with extra games.

All2,560 slots must be normal terminal/hash-bound records. Maximum2,624 physical games including64 speed games,0 retries,6h wall,60s/game. Reuse stdlib fixed evaluator for match execution; its internal DEVELOPMENT_ONLY verdict is raw execution metadata. A separate frozen acceptance analyzer makes the formal gate decision, so no raw verdict is relabeled. Existing rule/Observation/Prism96-80 contracts and no inference-overlay boundary remain.

### Plan and initial evidence

1. Existing cloud2 immutable release/assets directly hash-confirmed; cloud2 exposes2 EPYC7551 vCPUs and a running shared worker. Local i7-12700H has14 cores/20 logical CPUs. Do not pause that worker or assume hardware specs prove speed.
2. Local historical release/arena binaries lack `agent-prism-sample`; build a dedicated release under ignored acceptance artifacts, retaining old binaries. Validate candidate identity and parity before speed/formal games. Compare native per-game elapsed and full evaluator wall on32 serial identical tasks; report shared-load/cross-platform limitations.
3. Choose the faster verified host once on speed alone, then finish the frozen acceptance grid (local up to4 conservative workers; cloud1), with completed-game cache and bounded deadlines. Independently verify saved records/aggregates; no new learner data or shared-pool DB/Elo.
4. If all gates pass, publish an immutable local model manifest/version `prism-v0.1.1` and update M51/M54/handoff navigation. This accepts a model iteration; production-default replacement or shared-pool deployment is not part of this authorization. Otherwise keep the candidate with exact failed/inconclusive gates. No automatic third training campaign.

### Iteration log

- Round start: branch main/HEAD bcdaca7…; staging empty, unrelated dirty worktree retained; handoff ignored. Verified candidate/parent paths and prior parity/results, new seed ranges reserved before any new match. Existing local binaries reported unrecognized `agent-prism-sample`; no game was launched by these capability probes.

- Dedicated `cargo build --release --offline -p splendor-cli --bin splendor --target-dir local-artifacts/prism/acceptance-v1/build -j 2` **exit0**, optimized build3m36s; existing warning classes retained. New binary SHA `0dd5259123f0bd8c12b3672153a6a001b3026489c14abbbd4a919fcde9665f43`. Both frozen parent/c8 match68 existing fixture Python–Rust parity at atol=rtol1e-4, no fixture games.
- `python -B -m pytest -q -p no:cacheprovider training/prism/tests/test_strength_acceptance.py training/prism/tests/test_ppo_fixed_eval.py --basetemp local-artifacts/prism/acceptance-v1/tests` **11 passed/exit0/0.85s**. Negative cases require each confidence gate, reject a favorable mean with an inconclusive lower bound, prevent pool averages hiding one anchor regression, and check seed-block resampling reproducibility.
- Speed matched all32 native game outcomes/points/ranks/plies across hosts. Cloud timing wrapper first finished32 games then exited1 on nonexistent `row.game_wall_seconds`; raw results/records were preserved. Recovered timing from original nanosecond artifact timestamps on both hosts, no repeated games. Same serial first-config→last-completed-record interval: local15.8308929s, cloud61.984013627s, **local3.9153833× faster**; includes spawning/verification/I/O/inter-game overhead, excludes compilation/SSH. Cloud full evaluator monotonic wall was not saved and remains null; local full evaluator16.109s/native commands9.311s are supplemental only. Cloud shared pool load was1.76/1.52/1.21 on2 vCPUs; it was left running, so this is observed workload speed, not an isolated hardware or all-policy benchmark.
- Selected local by timing only. Frozen10-shard plan uses4 BelowNormal match workers and the original contract-file timestamp+6h deadline; eight disjoint32-seed common-anchor shards (256 games each) plus two128-seed duel shards (256 each), total2,560. Runner is active; no holdout results inspected or interim gate/selection performed. Evidence `local-artifacts/prism/acceptance-v1/{preflight,local-parity,speed-comparison,plan}.json`.

### Current next gate

Dedicated release build and parity →32-game host speed probes →frozen2,560-game holdout and final acceptance/version decision. Actual commands, failures, hashes and results will be appended after execution.


### Stage V final validation and decision — 2026-10-02

Status: **NOT_ACCEPTED（正式晋级）/ prism-v0.1.1-rc.1候选产物已固化**. Original frozen2,560-game holdout is complete and all records are normal terminal matches. The runner exited0 after 751.699s on4 BelowNormal evaluator workers.64 speed games are separately retained; total2,624 physical matches,0 retries,0 training updates. No candidate/seed replacement or interim selection occurred.

| Common anchors total | Games | W–D–L | Score |
|---|---:|---|---:|
| parent | 1024 | 558–7–459 | 54.8340% |
| c8 | 1024 | 633–6–385 | 62.1094% |

Direct parent duel: c8 278–5–229 in512 games, score 54.7852%. Percentile bootstrap resamples256 complete environment-seed dual-seat blocks,20,000 draws with Random seed54039999. All four gates use the preregistered Bonferroni one-sided1.25% lower quantile; ordinary95% intervals are supplemental.

| Metric (delta rows are pp; duel row is score) | Mean | Two-sided95% CI | Simultaneous lower bound |
|---|---:|---|---:|
| pooled anchors delta | 7.2754% | [3.2715,11.2305]% | 2.5879% |
| direct duel score | 54.7852% | [50.5859,58.9868]% | 50.0000% |
| heuristic-v031 | 4.9805% | [-0.6836,10.5493]% | -1.5625% |
| prism-v01 | 9.5703% | [4.1992,14.9414]% | 3.4180% |

Exact gates: `{"anchor_noninferiority/heuristic-v031": true, "anchor_noninferiority/prism-v01": true, "direct_parent_superiority": false, "pooled_anchors_superiority": true}`. All strength gates passed: **false**. This accepts or rejects the single outcome-only model iteration under the frozen protocol, not all future style policies or universal opponent strength. Independent holdout means fresh unused seeds/single frozen candidate; this was the same agent's execution and verification, **not an independent reviewer**.

Actual execution and verification:

```powershell
python -B -u scripts/prism_strength_acceptance.py run --plan local-artifacts/prism/acceptance-v1/plan.json --receipt local-artifacts/prism/acceptance-v1/run-receipt.json
python -B -u scripts/prism_strength_acceptance.py analyze --contract benchmarks/m54-prism-v02-acceptance-v1.config.json --plan local-artifacts/prism/acceptance-v1/plan.json --output local-artifacts/prism/acceptance-v1/full-result.json
```

Both **exit0**. Analyzer independently reads all saved2,560 report/replay hashes, checks normal terminal identity/seed/seat/catalog/result/plies, report runtime `prism-sample`, pinned candidate/parent/runtime assets, each shard progress/completion/result binding and recomputed aggregate, then exact complete grid and bootstrap gates. This is result verification; it does not replay the whole rules engine or rerun games. Frozen contract SHA `4e849130a065958cf0694717d64a9ac33078aad5aa3f1ff43ee001eaa95f96da`; full report SHA `95015af108166995ca3aa34f061624a2a7572cb6a01bdfd0006d4a2d578f7019`; final result index SHA `570a4d2439838ca29e2fb2144e2312b768ad27d6dd6ea0bdf99ece5f2191349c`. Complete evidence/config/runner/runtime hashes are in [acceptance result](../benchmarks/m54-prism-v02-acceptance-v1.result.json). Generated replays/weights remain local-only.

Local/cloud speed:32 identical serial tasks, first match-config→last completed-record window 15.831s local vs 61.984s cloud2, local **3.915× faster**; all32 outcomes/points/ranks/plies identical. No compilation/SSH overhead included. Cloud shared pool remained active on2 vCPUs; reporting wrapper's historical timer-field error was reconciled from untouched nanosecond timestamps without additional games. Full cloud evaluator wall remains unknown. Use local for this Rust Prism evaluation workload under observed conditions; stronger search agents, different load/parallelism and training are not covered by this timing result.

Version decision: The candidate remains available as final trial-v2 c8; a failed or imprecise gate does not erase the completed training/development signal. [Versioned candidate](../benchmarks/m54-prism-v0.1.1.candidate.json) `prism-v0.1.1-rc.1` is retained at `local-artifacts/prism/v02-rc1/weights.json` with the same exact c8 hash; this is a research artifact version, not a passed acceptance gate. No official v0.1.1 promotion, extra matches or retraining.

Historical trial-v2 `FAILED_SHARED_POOL_BOUNDARY` and owner manual-unpause clarification remain intact; they do not cause this strength decision. Next authorized step: preserve and use the evaluated artifact as the next research starting point. No further training, repeated acceptance, shared-pool mutation, default replacement, commit/push or deployment was launched.


## Stage VI second-look strength confirmation — authorized 2026-10-02

Status: **AUTHORIZED / READY TO RUN**. Owner follow-up `go 启动` is handled as one additional finite match confirmation of the same frozen candidate, after the reported v1 NOT_ACCEPTED result. Baseline remains main@bcdaca7cb33c53cc43d5dcc9e92c07be3c1aaa57; staging remains empty. [New contract](../benchmarks/m54-prism-v02-acceptance-v2.config.json), SHA `8b8045da8e1f4e57e9d3d1c986e58722b8ecaafea603cc14ef61b14bb77ca154`, is frozen before dispatch.

### Problem and evidence

V1 completed2,560 games with positive common-anchor and ordinary95% direct-duel evidence, but the adjusted direct-duel lower bound was exactly50% and failed the strict>50% gate. This motivates a bounded precision check, not training, alternate weights, a relaxed gate or a claim that v1 passed. Its config, result and rc.1 manifest remain immutable and hash-pinned.

### Initial design, scope and non-goals

Use new512 environment seeds9470000..9470511, both seats:4,096 common-anchor games (parent and c8 vs two greedy anchors) plus1,024 direct-duel games =5,120. Same c8 a2301f08…, parent cb7c4fb3…, sampler T=1/action seed54030001, original optimized Rust binary/anchors. All new seeds are reserved and forbidden for training. Do not pool the old2,560 games into the new analysis. No new speed probe: use the already measured faster local host.

### Contracts and invariants

All four strength thresholds stay fixed: pooled delta lower>0, direct candidate score lower>0.5, each anchor delta lower>=-5pp, all required. Account for two evaluation looks and four lower-bound claims using nominal Bonferroni0.05/(2*4)=0.00625 lower quantile;20,000 fixed seed-block bootstrap draws/Random seed54049999. Ordinary95% CIs are supplemental; bootstrap coverage is approximate. V1 cannot pass this stricter policy because reducing its quantile cannot raise its50% direct bound. This does not retroactively alter v1's frozen result. No third look in this contract, interim gate analysis, adaptive extension or replacement seeds.

Fixed maximum5,120 physical matches/0 retries,6h campaign deadline from contract publication,60s/game,4 BelowNormal local evaluators. Completed artifacts are immutable; partial/failed games stop without respawning. This is outcome-only version acceptance, not learned-style acceptance, an independent reviewer, default/UI-roster/shared-pool deployment, DB/Elo mutation or new training.

### Implementation plan and iteration log

A separate `scripts/prism_strength_confirmation.py` preserves the v1 analyzer bytes, adds second-look/budget/previous-result/template/source pins and exact5,120-slot validation, and retains the original fixed evaluator. Twenty256-game shards use the existing SHA-pinned assets; direct-duel shards execute first, without interim selection. Final analyzer verifies saved hashes/identities/normal terminal grid and recomputes each raw aggregate before one gate decision.

Actual20 negative-policy/evaluator tests passed/exit0/0.96s; preflight exit0 checks all20 configs, runtime/weight assets, fresh exact grid, source/previous-result hashes and immutable deadline. Evidence `local-artifacts/prism/acceptance-v2/{plan,preflight}.json`. Registry has82 pairwise disjoint ranges after reservation. No match has been launched at this preregistration record.

### Final implementation, validation and evidence

Pending bounded execution and final-only analysis. Actual commands, wall/exit status, result hashes and version decision will be appended after dispatch/completion.

### Result and decision; known limitations; next authorized gate

Current version stays `prism-v0.1.1-rc.1`. Complete this one frozen5,120-game round; register `prism-v0.1.1` only if the complete grid and all stricter lower-bound gates pass. Otherwise preserve both results and stop. The sample-size choice follows observed v1 precision; new games remain independent, same candidate and finite once-only scope. No exact statistical coverage or universal strength claim. Historical trial-v2 shared-pool boundary failure and owner manual unpause remain separate. No stage/commit/push.


### Stage VI actual dispatch — 2026-10-02T07:02:06.297589+00:00

Hidden local controller PID40096, BelowNormal, actually launched at2026-10-02T07:01:38.8150912Z; launch evidence `local-artifacts/prism/acceptance-v2/launch.json`. Initial shard completion counters are observable, controller stderr0 at this snapshot. Matches use the frozen plan and original assets. No interim outcome/gate analysis; current Stage VI is **IN PROGRESS**, original READY TO RUN section is preregistration history.


### Stage VI final validation and decision — 2026-10-02

Status: **ACCEPTED_MODEL_ITERATION / Prism v0.1.1**. All5,120 new physical records are normal completed matches;20 shards exited0,0 infra retries,0 speed games and0 training updates. Local4 BelowNormal evaluators finished in1036.600s (17.28min), within the original6h deadline. No interim outcome analysis, seed/candidate substitution or budget extension occurred.

| Common anchors total | Games | W–D–L | Score |
|---|---:|---|---:|
| parent | 2048 | 1087–7–954 | 53.2471% |
| c8 | 2048 | 1264–10–774 | 61.9629% |

Direct parent duel c8: 609–9–406/1024 games, score59.9121%. Measurements use only the512 new dual-seat environment blocks; previous Stage V games are not pooled.20,000 fixed Random54049999 bootstrap draws; nominal0.05/(4 gates*2 looks)=0.00625 lower quantile. Ordinary95% CIs are supplemental; bootstrap coverage is approximate. Same-agent artifact verification is not an independent reviewer.

| Metric | Mean | Ordinary two-sided95% CI | Stricter one-sided lower |
|---|---:|---|---:|
| pooled common-anchor delta (pp) | 8.7158 | [6.0547,11.3770] | 5.3465 |
| direct parent score (%) | 59.9121 | [56.8848,62.9395] | 56.0059 |
| heuristic-v031 delta (pp) | 8.5938 | [4.6863,12.4023] | 3.5645 |
| prism-v01 delta (pp) | 8.8379 | [5.0293,12.6953] | 3.9062 |

Exact frozen gates: `{"anchor_noninferiority/heuristic-v031": true, "anchor_noninferiority/prism-v01": true, "direct_parent_superiority": true, "pooled_anchors_superiority": true}`; **all_four_strength_gates_passed=true**. Direct gate remains strictly>50%; pooled>0, each anchor>=-5pp. No third evaluation look in this contract. Stage V NOT_ACCEPTED/50% direct lower, rc.1 bytes and original training/shared-pool gate hashes remain unchanged.

Actual execution and analysis:

```powershell
python -B -u scripts/prism_strength_confirmation.py run --plan local-artifacts/prism/acceptance-v2/plan.json --receipt local-artifacts/prism/acceptance-v2/run-receipt.json
python -B -u scripts/prism_strength_confirmation.py analyze --contract benchmarks/m54-prism-v02-acceptance-v2.config.json --plan local-artifacts/prism/acceptance-v2/plan.json --output local-artifacts/prism/acceptance-v2/full-result.json
python -B -u local-artifacts/prism/acceptance-v2/finalize-confirmation.py
```

Run and analysis **exit0**. Finalization checks5,120 physical `game.json` records, all20 shard exits/times and immutable evidence before writing this section. Analyzer checks every report/replay hash, normal terminal result/identity/grid, progress/completion/result binding and fully recomputed raw shard aggregates, then all confidence gates. It did not rerun matches or replay the whole rules engine. [New result](../benchmarks/m54-prism-v02-acceptance-v2.result.json) SHA `827c621a8e1771849088624cff385fe818c149c0f8374fe5863bb70cebfa82a5`; full report SHA `acdb3f1e19b68a89d2fb8d7f9b361e82485a7d2fcc314aa1428f04adeff1ae35`; contract SHA `8b8045da8e1f4e57e9d3d1c986e58722b8ecaafea603cc14ef61b14bb77ca154`. Local evidence/config/source/runtime paths and hashes are in the result and `local-artifacts/prism/acceptance-v2/`.

Version decision: Registered [formal prism-v0.1.1](../benchmarks/m54-prism-v0.1.1.release.json), immutable local-artifacts/prism/v0.1.1/weights.json SHA a2301f08… exactly matching trial-v2 final c8. This accepts the outcome-only learned T=1 iteration. Generic sampler0.1.0 and architecture/weight format are unchanged. Original rc.1 and Stage V retain their historical unaccepted status.

Seed range9470000..9470511 is consumed/never train in result `seed_use`; registry retains the frozen preregistration reservation label for source reproducibility, and both exclude reuse. No training, third evaluation look, default/Studio/shared-pool deployment, DB-Elo mutation, Aran restart, stage/commit/push. Historical pool failure and owner manual unpause remain separate. Next gate: preserve/use the evaluated artifact; further training or production integration requires a separate explicit finite scope.


### 2026-10-02 中文阅读入口补充

用户说明 JSON 不便阅读，新增 [Prism v0.1.1 中文评测摘要](prism/prism-v0.1.1-evaluation-summary.md)，并同步 M51、模型演进表和本地 handoff 导航。摘要逐项引用已完成评测的战绩、校正下界、版本身份和既有主机测速；没有新对战、训练或版本决定。此前文档中的 AUTHORIZED / IN PROGRESS、NOT_ACCEPTED 均按所属历史阶段理解，最新阶段 VI 为 ACCEPTED_MODEL_ITERATION。顶部授权沿革末句“独立晋级验收未完成”描述阶段 IV 的历史背景，已由阶段 VI 完成验收的结论取代；历史原句保留。


## 2026-10-02 版本口径更正与详细对战表（当前）

2026-10-02 用户命名更正：本轮统一为 **Prism v0.1.1**，不另开 0.2 模型线。原名文档已保存到 ignored `local-artifacts/prism/011-docs/legacy-naming/`；冻结实验仍保留原 `v02` 文件名、内容/hash 和失败门槛。更正不改变权重、runtime 0.1.0 或权重格式；当前权重入口为 `local-artifacts/prism/v0.1.1/weights.json`。

依据 [Prism v0.1.1 完整报告](prism/prism-v0.1.1-evaluation-summary.md) 和 [详细指标](../benchmarks/m54-prism-011.match-details.json) SHA `24c1fbed8cd254a13f6bbb40153b15106576f9436520d4a540a9efc4916510dc`，本模型文档直接保留详细表。离线命令见完整报告，exit0 / 5,120 replay / 10 批，无新增对局或训练。旧 v02 路径只作冻结证据。

### 各对手完整战绩

每项对照为 512 个新环境种子、双换座共 1,024 局；总计 5,120 局。纯胜率 = 胜 / 局数，得分率 =（胜 + 0.5 × 平）/ 局数。

| 模型 | 对手 | 局数 | 胜 / 平 / 负 | 纯胜率 | 计半平得分率 | 普通 95% 配对区间 |
| --- | --- | --- | --- | --- | --- | --- |
| Prism v0.1.1 | Heuristic v0.3.1 | 1024 | 633 / 4 / 387 | 61.8164% | 62.0117% | [59.0332%, 64.9902%] |
| Prism v0.1.1 | 初代 Prism v0.1.0 | 1024 | 631 / 6 / 387 | 61.6211% | 61.9141% | [58.9844%, 64.7949%] |
| Prism v0.1.1 | 上一批 PPO 检查点（trial-v1 c8） | 1024 | 609 / 9 / 406 | 59.4727% | 59.9121% | [56.8848%, 62.9395%] |
| 上一批 PPO 检查点 | Heuristic v0.3.1 | 1024 | 545 / 4 / 475 | 53.2227% | 53.4180% | [50.4871%, 56.3477%] |
| 上一批 PPO 检查点 | 初代 Prism v0.1.0 | 1024 | 542 / 3 / 479 | 52.9297% | 53.0762% | [50.1953%, 55.9082%] |

直接父代对战区间沿用原冻结验收；其余逐对手区间是新增描述性 bootstrap（20,000 次，按双座 seed 组），不新增晋级门槛，也不代替四项严格校正下界。

### 先后手明细

| 模型 | 对手 | 本模型座位 | 局数 | 胜 / 平 / 负 | 纯胜率 | 得分率 | 局均 VP（本模型 / 对手） |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Prism v0.1.1 | Heuristic v0.3.1 | 先手 P0 | 512 | 336 / 3 / 173 | 65.6250% | 65.9180% | 14.811 / 13.295 |
| Prism v0.1.1 | Heuristic v0.3.1 | 后手 P1 | 512 | 297 / 1 / 214 | 58.0078% | 58.1055% | 14.631 / 13.744 |
| Prism v0.1.1 | 初代 Prism v0.1.0 | 先手 P0 | 512 | 320 / 2 / 190 | 62.5000% | 62.6953% | 14.600 / 13.348 |
| Prism v0.1.1 | 初代 Prism v0.1.0 | 后手 P1 | 512 | 311 / 4 / 197 | 60.7422% | 61.1328% | 14.527 / 13.281 |
| Prism v0.1.1 | 上一批 PPO 检查点（trial-v1 c8） | 先手 P0 | 512 | 306 / 7 / 199 | 59.7656% | 60.4492% | 14.545 / 13.637 |
| Prism v0.1.1 | 上一批 PPO 检查点（trial-v1 c8） | 后手 P1 | 512 | 303 / 2 / 207 | 59.1797% | 59.3750% | 14.648 / 13.602 |
| 上一批 PPO 检查点 | Heuristic v0.3.1 | 先手 P0 | 512 | 273 / 4 / 235 | 53.3203% | 53.7109% | 14.363 / 13.975 |
| 上一批 PPO 检查点 | Heuristic v0.3.1 | 后手 P1 | 512 | 272 / 0 / 240 | 53.1250% | 53.1250% | 14.307 / 13.990 |
| 上一批 PPO 检查点 | 初代 Prism v0.1.0 | 先手 P0 | 512 | 281 / 0 / 231 | 54.8828% | 54.8828% | 14.230 / 13.721 |
| 上一批 PPO 检查点 | 初代 Prism v0.1.0 | 后手 P1 | 512 | 261 / 3 / 248 | 50.9766% | 51.2695% | 14.092 / 14.037 |

### 对局节奏

| Prism v0.1.1 所在对局指标 | 对阵 Heuristic v0.3.1 | 对阵初代 Prism v0.1.0 | 对阵上一批 PPO 检查点 |
| --- | --- | --- | --- |
| 总执行步数 | 54919 | 54596 | 55224 |
| 局均执行步数 | 53.632 | 53.316 | 53.930 |
| 平均决策轮（legacy） | 26.829 | 26.671 | 26.976 |
| 最短 / 中位 / 最长决策轮 | 21 / 27.0 / 34 | 21 / 27.0 / 33 | 21 / 27.0 / 34 |
| 决策轮总体标准差 | 1.765 | 1.807 | 1.821 |
| 平均 Main 行动轮 | 26.802 | 26.646 | 26.954 |
| 终局绝对分差均值 | 3.775 | 3.981 | 3.700 |
| 终局分差 ≤2 的比例 | 35.64% | 32.52% | 34.67% |

legacy 决策轮为 `ceil(全部执行步/2)`，本玩家决策包含 `choose_noble`；它不是额外 Main 回合。Main 行动/轮另行统计。

### 购卡、折扣、贵族与预留

| 两方指标（每格：Prism v0.1.1 / 对手） | Heuristic v0.3.1 | 初代 Prism v0.1.0 | 上一批 PPO 检查点（trial-v1 c8） |
| --- | --- | --- | --- |
| 局均最终 VP | 14.721 / 13.520 | 14.563 / 13.314 | 14.597 / 13.619 |
| VP / 本玩家决策 | 0.5492 / 0.5040 | 0.5464 / 0.4993 | 0.5413 / 0.5051 |
| VP / 本玩家 Main 行动 | 0.5492 / 0.5044 | 0.5466 / 0.4997 | 0.5415 / 0.5053 |
| VP / 全局执行步 | 0.2745 / 0.2521 | 0.2732 / 0.2497 | 0.2707 / 0.2525 |
| 局均购卡数 / 永久折扣 | 12.195 / 13.337 | 12.208 / 13.294 | 12.427 / 12.591 |
| 局均贵族数 | 0.457 / 0.693 | 0.443 / 0.658 | 0.521 / 0.516 |
| 获得至少一贵族的对局比例（%） | 37.89 / 49.90 | 36.52 / 48.34 | 42.29 / 40.04 |
| 局均预留取得 | 2.170 / 2.372 | 2.232 / 1.830 | 2.513 / 2.400 |
| 局均预留买回 | 0.853 / 1.249 | 0.873 / 0.896 | 1.026 / 0.996 |
| 局均终局未买回预留 | 1.317 / 1.123 | 1.359 / 0.935 | 1.486 / 1.404 |
| 预留兑现率（%） | 39.29 / 52.66 | 39.11 / 48.93 | 40.85 / 41.50 |
| 局均 0 VP 卡 | 6.259 / 7.509 | 6.275 / 7.419 | 6.465 / 6.853 |
| 局均 1 VP 卡 | 2.082 / 2.604 | 2.036 / 2.642 | 2.180 / 2.275 |
| 局均 2 VP 卡 | 1.841 / 1.721 | 1.929 / 1.807 | 1.842 / 1.726 |
| 局均 3 VP 卡 | 0.841 / 0.794 | 0.890 / 0.778 | 0.897 / 0.867 |
| 局均 4 VP 卡 | 0.801 / 0.537 | 0.720 / 0.492 | 0.738 / 0.606 |
| 局均 5 VP 卡 | 0.372 / 0.173 | 0.358 / 0.156 | 0.305 / 0.264 |
| 局均白色永久折扣 | 2.346 / 2.667 | 2.415 / 2.610 | 2.420 / 2.545 |
| 局均蓝色永久折扣 | 2.507 / 2.581 | 2.471 / 2.648 | 2.528 / 2.499 |
| 局均绿色永久折扣 | 2.451 / 2.645 | 2.452 / 2.660 | 2.531 / 2.418 |
| 局均红色永久折扣 | 2.479 / 2.656 | 2.491 / 2.574 | 2.459 / 2.529 |
| 局均黑色永久折扣 | 2.413 / 2.788 | 2.379 / 2.801 | 2.488 / 2.600 |

兑现率使用累计买回数 / 累计预留数；终局未买回只描述保留牌，不直接等于无效预留或成功干扰。

### 七类动作的完整分布

| 动作次数及占比（每格：Prism v0.1.1 / 对手） | Heuristic v0.3.1 | 初代 Prism v0.1.0 | 上一批 PPO 检查点（trial-v1 c8） |
| --- | --- | --- | --- |
| 购市场卡 `buy_market` | 11615 (42.31%) / 12378 (45.06%) | 11607 (42.53%) / 12696 (46.50%) | 11674 (42.28%) / 11873 (43.00%) |
| 购预留卡 `buy_reserved` | 873 (3.18%) / 1279 (4.66%) | 894 (3.28%) / 917 (3.36%) | 1051 (3.81%) / 1020 (3.69%) |
| 拿筹码 `take_tokens` | 12735 (46.40%) / 11359 (41.35%) | 12498 (45.80%) / 11798 (43.21%) | 12303 (44.55%) / 12250 (44.37%) |
| 预留市场卡 `reserve_market` | 2219 (8.08%) / 2420 (8.81%) | 2283 (8.37%) / 1870 (6.85%) | 2573 (9.32%) / 2451 (8.88%) |
| 盲预留牌堆 `reserve_deck` | 3 (0.01%) / 9 (0.03%) | 3 (0.01%) / 4 (0.01%) | 0 (0.00%) / 7 (0.03%) |
| 选择贵族 `choose_noble` | 4 (0.01%) / 25 (0.09%) | 6 (0.02%) / 20 (0.07%) | 13 (0.05%) / 9 (0.03%) |
| Pass `pass` | 0 (0.00%) / 0 (0.00%) | 0 (0.00%) / 0 (0.00%) | 0 (0.00%) / 0 (0.00%) |
| 全部决策步数 | 27449 / 27470 | 27291 / 27305 | 27614 / 27610 |
| Main 行动步数 | 27445 / 27445 | 27285 / 27285 | 27601 / 27601 |

占比分母为该模型全部决策步（含 `choose_noble`）；换座后按模型身份合并，P0 不固定代表 Prism v0.1.1。零动作明确显示为 0。

### 实测耗时与缺失项

| Prism v0.1.1 所在对局指标 | 对阵 Heuristic v0.3.1 | 对阵初代 Prism v0.1.0 | 对阵上一批 PPO 检查点 |
| --- | --- | --- | --- |
| 逐局游戏进程耗时之和（秒） | 400.079 | 475.484 | 386.225 |
| 单局游戏进程均值（秒） | 0.3907 | 0.4643 | 0.3772 |
| 单局游戏进程 p95（秒） | 0.4850 | 0.6408 | 0.4379 |
| 决策 / 网络推理延迟 | NOT_MEASURED | NOT_MEASURED | NOT_MEASURED |

以上来自各局 `process-result.json.wall_seconds`，包含游戏进程内双方推理/规则执行/读写；为 4 个并发低优先级进程下的耗时。逐局耗时之和含并发重叠，不能当作整轮墙钟。整轮 5,120 局实际墙钟为 **1036.600 秒（17 分 17 秒）**，包含父代锚点局与运行调度。Arena 未保存逐决策/网络推理延迟，故显式标 NOT_MEASURED。


### 同锚点下的 Prism v0.1.1 与父代行为对照

| 同锚点行为指标（Prism v0.1.1 / 父代） | Heuristic v0.3.1 | 初代 Prism v0.1.0 |
|---|---|---|
| 局均最终 VP | 14.721 / 14.335 | 14.563 / 14.161 |
| VP / 本玩家 Main 行动 | 0.5492 / 0.5337 | 0.5466 / 0.5276 |
| 局均购卡 / 永久折扣 | 12.195 / 12.453 | 12.208 / 12.447 |
| 局均 0 VP 卡 | 6.259 / 6.603 | 6.275 / 6.608 |
| 局均 3–5 VP 卡 | 2.014 / 1.963 | 1.968 / 1.881 |
| 局均贵族 | 0.457 / 0.469 | 0.443 / 0.464 |
| 贵族覆盖率（%） | 37.89 / 37.70 | 36.52 / 37.21 |
| 局均预留取得 | 2.170 / 2.026 | 2.232 / 2.212 |
| 局均预留买回 | 0.853 / 0.884 | 0.873 / 0.902 |
| 局均终局未买回预留 | 1.317 / 1.143 | 1.359 / 1.310 |
| 预留兑现率（%） | 39.29 / 43.61 | 39.11 / 40.79 |

两模型使用同锚点/seed/座位与相同 T=1，表格是本次固定对照的描述统计；未对这些行为差异增加正式检验门槛，也不据此认定某种风格或机制。

### 下一轮方向判断：先做一个初代风格样机，继续复用 PPO

状态：**历史方向建议；后续 M55 已授权启动**。当时未采样、未选定参数；用户后来“okay 开始吧”授权一个有限冲分样机，当前参数与状态见 M55。

建议把已验收的 **Prism v0.1.1 冻结为通用基座和棋力参照**，从同一权重派生一个“冲分”初代风格模型，使用既有 PPO 闭环学习。PPO 是训练方法，风格模型是产物目标，两者可以结合。初代 Prism v0.1.0 保留作对照，不因“初代”称呼而退回较弱的训练起点；若指从零重训通用基座，当前还缺少必须重建表示的证据。

| 选项 | 现有证据与成本 | 建议 |
|---|---|---|
| 再做一批仅胜负奖励 PPO | Prism v0.1.1 的独立新 seed 验收支持有效迭代；没有证据说明继续训练无效或已到上限，但同两个对手更多训练未必增加广度 | 放在风格样机之后；若下一目标只要更强，先做有界对手广度诊断，再冻结续训方案 |
| 从 Prism v0.1.1 派生初代风格模型 | 风格目标还未落地；已有更强参照，可以分别判风格差异和棋力损失 | **优先：只做一个冲分样机**，暂不同时三风格或大规模候选扫描 |
| 从初代 Prism v0.1.0 / 随机初始化重做通用基座 | 可作研究对照，当前没有受控证据证明重训比沿用 Prism v0.1.1 更合算 | 暂缓；以具体表示缺陷、合法信息缺口或跨对手失败为重开条件 |
| 先部署、GPU/PyO3 或扩大混池 | 可改善使用或效率，不能补出可测风格；本机固定评测速度已可用 | 作为独立工程目标，暂不替代下一研究问题 |

建议形成时的源码核实：`training/prism/ppo/model.py` 已有独立训练用 style head，`learner.py` 支持胜负优势加 β×风格残差及独立 style loss；但当时 `execution.py::validate_spec` 明确拒绝 `style_beta != 0`，当时真实风格奖励提取器尚未接入。M55 已接通 run v3 的冻结奖励合同；下述原建议是决策历史。原建议为下一轮先补齐这个闭环，不能只改 β 就声称可进行风格训练。

先选冲分，因为公开得分在固定自身 Main 行动窗口中的实现速度容易定义和复核。目标可沿用 M54 原提案的固定 K 窗口归一化得分 AUC；K、归一化上限、β、训练预算、可接受棋力损失 δ 和最小风格差异须在采样前冻结；形成此建议时未预填数值，后来实际冻结值见 M55。保留真实胜负 critic；不加入推理 logit 偏置、隐藏牌/未来信息或同局未来结果作在线输入。额外风格效用改变策略权衡，需要单独验证；[奖励塑形的策略不变性原论文](https://people.eecs.berkeley.edu/~russell/papers/icml99-shaping.pdf) 的保证只适用于特定形式与假设，不能直接套到该风格目标。

建议顺序：①奖励提取/coverage/恢复和 β=0 一致性工程验证；②有限开发训练，只做一个风格、少量预先限定候选；③冻结唯一候选，用新独立 seed 同时验风格差异和相对 Prism v0.1.1 棋力约束。至少加入一个不与奖励公式重复的行为指标，并监测预留兑现/持牌占用等代价，避免只练高奖励。这轮 945/947 开头的验收 seed 已消费，不能用于训练、候选挑选或下一轮新 holdout。

本次画像仅作描述：Prism v0.1.1 对 Heuristic 的预留兑现率 39.29%，上一批 PPO 检查点 43.61%；终局未买回均值 1.317 vs 1.143。这提示后续需监测预留代价，不能证明有效干扰或 PPO 缺陷。Prism v0.1.1 也尚未通过“均衡风格”的独立验收，只是当前通用棋力参照。


文档要求已纳入 AGENTS.md §7、项目文档系统、统一指标标准。最新 [Prism v0.1.1 release](../benchmarks/m54-prism-v0.1.1.release.json)，旧结果/hash/NOT_ACCEPTED 保留。本次改名、补表、方向分析已执行；建议下一训练尚未启动。


### 离线指标补算的迭代记录

首个补算命令 exit1：将 progress 的 canonical JSON hash 误与文件字节 hash 比较，尚未进入 Rust 回放重验。按既有 `prism_ppo_fixed_eval.py` 的 canonical 序列化合同修正绑定，并对 match-config 同样处理；重跑完整 5,120 回放 / 10 批后 exit0。最终分析回执 `local-artifacts/prism/011-docs/analysis-receipt.json` 记录命令、exit0、16.937s 与各批输出；原比赛报告和冻结合同没有改写。本次代码只执行已完成回放的离线分析，不调用 Agent 或 `run-match`。


### 文档收口验证

```powershell
python -B local-artifacts/prism/011-docs/validate-closeout.py
```

**exit0 / PASS**：冻结 config/result 和原名文档档案 hash 一致；Prism v0.1.1 同权重、release/result/detail 索引绑定一致；各文档完整表格/数字/链接、下一轮 PROPOSED 状态、`git diff --check` 和 local-only 规则通过。回执 `local-artifacts/prism/011-docs/closeout-validation.json` 保存断言与文件 hash。此项是文档/产物一致性检查，不是新增棋力比赛；main/HEAD 未变，staging 空，未提交/推送。


## 2026-10-02 模型称谓与表格解释更正

文档仅使用正式 `Prism v0.1.1` 名称。当前版本 = trial-v2 最终 c8；上一批 PPO 检查点 = trial-v1 最终 c8，是当前版本再训八轮之前的起点，未单独发布正式版本。初代 Prism v0.1.0 是另一份监督训练基线。节奏表按“当前版本对阵各对手”列出整场指标，个人指标明确双方顺序。见 [继承关系图与完整报告](prism/prism-v0.1.1-evaluation-summary.md)。原简称文档已归档，冻结比赛/权重/hash 不变。


### 当前后续轮次：M55 冲分样机已授权启动

用户“okay 开始吧”已授权 [M55](m55-prism-rush-style-model.md)。以冻结 Prism v0.1.1 新建风格头/AdamW/RNG，四轮有限训练，固定最终c4，开发512局+独立2,560局，六门全部通过才登记 Prism Rush v0.1.0；无默认/共享池部署。先前 PROPOSED 方向为决策历史，当前进度与冻结合同见 M55。Prism v0.1.1 的详细对战数据和继承关系见 [完整版本报告](prism/prism-v0.1.1-evaluation-summary.md)。
