# Splendor / Prism 项目专属 Agent 研究规程

云端方向规划先读 [CLOUD_PLANNING.md](CLOUD_PLANNING.md) 的当前事实与证据边界；根 `handoff.md` 和 `local-artifacts/` 为本地文件，Git中的研究快照不代表当前机器执行状态。

生效：2026-10-06；版本：`prism-research-workflow-v1`；来源：用户明确要求固化推荐研发与风格归类流程。
适用：本仓库的研发、实验、评测、报告、模型登记和部署。**先按本规程确定任务终点，再执行；不得凭历史标题或个人习惯补充研究步骤。**

## 0. 规则优先级与使用方法

- 本节到“原有文档合同”之前是当前操作规程；下方原有文档/报告要求继续有效。发生项目内措辞冲突时，以当前规程及用户较新的明确指令为准，不覆盖系统/开发者约束。
- 已冻结运行继续遵守其原配置、数值环境、种子、预算和判定门。本规程**不追溯修改 M67 或历史结果**；新规则用于新轮及独立报告/执行修订。
- “应做”不等于“已授权启动”。用户已批准的完整有限流程，阶段门通过后自动推进，不逐步重复请示；超出授权终点或改变冻结科学合同才补充授权。
- 下方旧文中的“本轮 Prism v0.1.1”仅为历史命名更正；新轮必须用其精确身份登记中的完整型号，不能统一套用旧型号。
- 模板：[研究执行记录](docs/templates/prism-research-record.md)。将适用字段填入该轮文档/既有 JSON，不为每个步骤另建重复文档。模板不是可执行控制器或已实现的 schema validator。
- 配套：[信息/架构边界](docs/architecture.md)、[Prism 数值接口](docs/m51-prism-implementation-contract.md)、[实战晋级合同](docs/prism-practical-promotion-contract.md)、[指标标准](docs/unified-match-metrics-standard.md)、[阅读合同](docs/prism-report-reading-contract.md)、[文档系统](docs/project-documentation-system.md)。按任务读取关联部分，合同历史修订从最新有效节解释。

## 1. 接手必做：先确定事实和任务边界

1. 读取本文件、`handoff.md` 顶部当前索引、活动里程碑和本轮合同；核验 branch/HEAD/index/worktree。只读已有文件不证明远端仍在运行。
2. 对正式输入核验权重/配置/执行来源及 SHA；区分源码工作树、部署快照、已发布权重。不要用未提交的 HEAD 冒充完整来源。
3. 加载 `all-workspace`，读取 Splendor 的任务 revision 和项目约束。复用匹配任务，否则创建当前范围的任务；同步不构成新训练授权。
4. 在轮次记录写明：`task_kind`、用户授权来源、`authorized_end`、当前阶段、必交产物、禁止动作、下一允许动作。开工告知用户一次；仅对无法安全判断的范围提出具体问题。
5. 涉及运行控制前，核对实际 node/PID/create_time/execution identity、最新提交与完成回执。旧标题、过期心跳、SSH不可达均不能代替状态核验。

### 任务终点表（未被用户明确扩大时的默认范围）

| 用户任务 / task_kind | 应执行到哪里 | 不自动包含 |
| --- | --- | --- |
| review / 评审、诊断、看现状 | R0 + 必要只读分析/零研究局验证 + R8适用报告 + R9收口 | 改训练实现、补赛、启动/恢复训练、改模型身份 |
| design / 设计方案 | R0–R1设计稿 + R9；参数未定写TBD，状态DESIGNED | R2实现或任何新采样 |
| implementation / 实现或修复 | R0–R2 + 针对性测试 + R8适用报告 + R9 | 正式训练/验收；端到端工程局须在已授权有限验证预算内 |
| pilot / 小试、看看效果 | R0–R4 + R5产物审计 + 预先约定的开发评测 + R7画像 + R8–R9 | 独立确认、正式晋级、因结果不显著继续加训 |
| experiment / 已批准“训练并评测这一轮” | R0–R9的适用阶段；冻结最终候选、独立确认、完整报告都不能只做一半 | 下一轮、自动发布、默认替换、池/Studio部署 |
| evaluate / 评测已有模型 | R0–R3适用预检 + R5身份核验 + R6–R9 | 训练、换权重、按评测结果重新挑候选 |
| report / 重写报告、补画像 | 只读已有结果，R7适用分析 + R8–R9 | 新对局、改旧门、覆盖冻结原结果；缺数据如实列缺项 |
| release / 发布指定研究版本 | R0 + R5/R6/R7既有证据检查 + R8–R9与第8节登记 | 额外采样、默认冠军、应用部署、Git push |
| deploy / 默认替换、上线 | 第8节指定目标的授权、验收、回滚与实机检查 + R9 | 其他目标、重训、自动扩大上线范围 |
| status / 只查进度、取回结果 | 核实身份/回执、只读取回并校验、报告当前状态；按实际取回范围收口 | 清锁、重试研究、延长截止、重启观察器或机器 |

“继续”在上下文唯一时继承最近一次明确任务；已完成/已耗尽的旧预算不会自动复活。用户明确授权新轮或恢复，可建立新有限合同/修订再执行；不能把新授权误读成永远不能续做，也不能解释成无限循环。已有产物可凭绑定证据满足前序门，不强迫重训或重复评测。

## 2. 唯一阶段链：输入、产物、出门条件

`R0 定界 → R1 冻结研究合同 → R2 工程就绪 → R3 零局预检 → R4 有界探索/训练 → R5 候选冻结与审计 → R6 独立实战确认 → R7 行为画像/路线 → R8 报告交付 → R9 项目收口`

每阶段记录 `NOT_RUN / IN_PROGRESS / PASS / FAIL / BLOCKED / NOT_APPLICABLE`、证据路径、判定原因和下一动作。`NOT_APPLICABLE`必须说明任务为何不需要该阶段，不能用于豁免失败。R7可在数据不足时输出“证据不足”而完成分析阶段，不等于风格确认。

阶段PASS表示该阶段工作与证据合格，不表示模型增强。有效的R6负结果仍进入R7–R9；身份无效、缺局或强制审计失败才阻塞对应判定，其他安全的诊断/报告照常完成。

`FROZEN`表示采样前合同/身份锁定，**不等于ACCEPTED**；`ACCEPTED`只对声明的验收对象使用。数据`NOT_RUN`须确知尚未执行，已执行但缺项用`INCOMPLETE`，未读取/不可达用`UNKNOWN`；不要互换。阶段记录与这些数据/模型结论分栏。

| 阶段 | 必交内容 | 进入下一阶段的条件 / 不满足时 |
| --- | --- | --- |
| R0 定界 | 上述任务边界、基线、输入与当前状态 | 范围可执行；不明授权只阻塞对应动作，继续可做的只读工作 |
| R1 合同 | 第3节全部适用字段；假设、对照、预算、种子、选择规则、指标/门/统计与停止规则 | 第一局研究采样前冻结；设计稿可以TBD，正式运行合同不能留可执行必填项TBD |
| R2 工程 | 相关单测/集成检查、schema贯通、恢复/报告故障检查、来源快照；新规模的资源校准 | 确认规则/数值/计数/恢复边界；工程局与研究局分开、各有预算。失败先修工程，不拿正式局调试 |
| R3 零局预检 | 本地/远端源码与依赖/权重/规则/schema身份、parity、资源预留、目录/进程归属、deadline、重试策略、完整命令 | 所有强制预检PASS且已授权；0新局。缺输入或容量不足先停止，不以“启动后再检查”替代 |
| R4 探索/训练 | 预定训练seed各臂完整账本、KL/熵/裁剪/梯度/损失、阶段时钟与资源、实际进度 | 到预算或预设停止点结束；失败保留。不以训练胜率、loss或单个检查点走势宣称竞技增强 |
| R5 候选冻结 | 按预先规则选定的精确权重及SHA、父代、完整state/export核对、训练审计、候选清单 | 独立评测第一局前冻结候选；最终cN合同不许换成中间最优。审计失败不进入竞技判定 |
| R6 独立确认 | 固定双方模式/对手/换座seed的完整网格、失败账本、原始结果、配对统计、每项门的估计/区间/结论 | 完整且审计合格才判门；不足记NOT_RUN/INCOMPLETE或未确认，不自动补样本。开发与独立数据分开 |
| R7 风格归类 | 第6节画像卡，分开写竞技价值、目标风格是否实现、实际路线与证据等级 | 按决策表给出可复核结论，包括混合/不足；不为贴标签追加训练或把风格失败改成竞技失败 |
| R8 交付 | 冻结证据、人类HTML/完整Markdown、Agent审计、结果绑定spec/receipt；数值/链接/交互及要求的视觉检查 | 完成任务声明的交付检查；页面生成不等于视觉PASS。可先交证据，缺强制验收时仍为review/blocked |
| R9 收口 | 核验产物、两层记录、ALL结果与证据、剩余事项和授权终点；Git/publication检查 | 所有本任务强制项完成才done；负结果可完成任务，长期研究/模型不因此晋级 |

## 3. R1必须填写的研究合同

- **问题与因果边界**：一句主要问题、可证伪假设、主要变化、非目标；分清棋力研究、风格研究、系统性能研究。多因素一起变更时不归因于单一因素。
- **初始化**：精确父权重/来源、`fresh optimizer warm-start`或`full-state resume`；后者须包含模型、优化器、RNG、数据消费游标和预算账。不得混称续训。
- **对照**：同父、同预算/环境/种子设计；有意不同的项逐项标出。增加预算不是同预算重复；性能优化不直接算棋力改进。
- **训练/开发/独立确认**：分别冻结seed范围、数量、是否换座、角色；独立确认的seed不得参与调参或候选选择。匹配对照可共享环境seed，须明确；不同训练seed的模型分报，比赛局数不能当训练重复数。
- **默认探索设计**：新训练方法比较优先计划至少3个独立训练seed；预算只允许1–2个时明确为pilot/有限重复，不超预算凑数量，也不宣称总体稳健。已批准的其他重复设计保持；3个同样不自动证明普适有效。
- **采样预算**：各臂局数/决策/周期/更新/pass、开发与验收网格、并发、CPU/GPU/RSS/磁盘、墙钟及绝对截止、工程与重试预算。无该轮明确允许时，研究执行自动重试为0；读取/传输重试独立计。
- **候选选择**：固定最终检查点或开发集选择算法、候选数、平局规则；独立结果不能反馈挑选。“选最好seed”只能按预注册开发规则，其他训练臂结果仍公开。
- **竞技统计**：主指标默认半平得分，纯胜率另报；冻结参考模型、共同池权重、直接对战、最小有意义增益/保留容忍、估计或置信界阈值、单双侧、family/multiplicity、bootstrap单位/次数/RNG、样本量依据。
- **覆盖面**：列出父代、现任相关路线代表、匹配Balance和至少一个非Prism锚点的纳入/排除原因；精确身份去重。默认冠军评审还须列关键对手退步容忍规则及训练外覆盖；只有已知池则结论限于该池，不能声称泛化已证明。
- **风格**：默认`descriptive`，只有该轮明确研究风格确认时才设`confirmatory`。两者都写参照/指标/公式/时间窗；确认性另填方向/实际差值门/跨对手一致性并在采样前冻结。描述性画像不设事后“原验收PASS”，不为了完整标签强制新采样。
- **执行与交付**：源码/依赖/二进制/规则身份、输出清单、审计与报告命令、备份/恢复入口、观测负责人、R8强制检查、成功/失败停止条件、获准终点。

参数没有通用固定局数或通用“+X%”门。Agent应在已授权范围内提出并冻结可解释值；如果选择将改变预算/目标/容忍度而授权不明，询问该项。不能把“每个Agent不用猜”变成盲目复用旧轮参数。

## 4. R2–R5工程、扩量与信息边界

- 规则由Rust核心决定，策略/critic只见玩家投影；seed、暗牌、未来信息、来源hash不进特征。裁判回放仅用于离线审计。遵守原禁止推理期人工logit偏置/重排约束。
- 保持冻结行为快照、真实采样old_logp、玩家自己的决策链、单writer和逻辑更新只消费一次；完整局、截断、基础设施abort分开，不丢长局换seed。
- 胜负value语义保持期望半平得分；终局BCE与GAE优势是可用组合，不凭“不是TD目标”判错。改奖励/critic语义须新合同。
- 改网络、编码、设备、批形状或库版本必须运行相应parity/输入边界/导出与恢复验证，绑定新运行身份；不能热改冻结执行。微批梯度近似不是任意精度逐字相等。
- 新规模/存储/并发变更先测：采集、推理、审计、序列化、落盘、更新、统计/渲染的分段时钟；真实并发/配额/线程、RSS峰、累计文件数与字节。用多个历史长度检查全量账本/目录扫描增长。
- ETA用匹配负载的实测速率和增长趋势，列准备/运行/审计/取回范围与不确定性；不从8局烟测、GPU利用率或总周期时间推断纯推理吞吐。
- 容量预检包含已有占用、在途预留、checkpoint、回放和报告；超额先拒绝。优化存储须保留原字节可重建、预算/尝试追踪与崩溃恢复，不靠删历史掩盖成本。
- 源码hash还需对应可取回源码/依赖快照；脏工作树可用精确源包绑定，不强制为启动混合提交用户改动。
- 相关测试包括正常贯通、身份漂移拒绝、缺失/重复对局、恢复后计数/科学状态、部分报告/传输失败。按变更范围选择，不要求每次文案修改跑全库训练。

## 5. R6竞技判断：先有效，再判断价值

1. 先验证产物与网格：权重/模式/seed/座次/数量/终局/失败/来源一致。无效数据不能进入“棋力退步”解释。
2. 双方greedy为人类报告默认；训练sampling、开发与独立验收分开。对手greedy不代表候选greedy；模式来自实际命令/plan。
3. 按模型身份聚合后，先同seed双座配对，再按冻结权重合并对手；率用分子分母总和，不能无权平均子组百分比。保留逐对手和先后手结果。
4. 分别判定“竞争力保留”“增强”“实际增益是否够用”。CI跨0/50%是增强未确认；保留门未过不自动证明退化；未显著不同不等于等效。
5. 同时报共同池、直接父代/代表版本、关键对手代价。平均通过不代表每个对手保留；不要求所有描述性指标都改善。
6. 多seed分报；算法层结论需训练seed层的不确定性，不能把同一检查点的海量局当独立训练样本。预设“每臂都通过”和总体效果估计是不同主张。
7. 一轮结论可以是保留参照、进入下一次开发、专门路线有用、未确认或拒绝。不得循环追加样本直到显著；序贯规则须采样前批准，事后追加只能另立研究，不伪装原确认集。

## 6. R7风格归类的确定流程

**六种事实分开保存：权重身份、训练血缘、训练目标、行为画像、路线建议、发布/冠军资格。研究分支名不是观察结果。** 旧 `route` 字段/版本名保持，不静默迁移含义。

### 必须按顺序执行 S1–S6

| 步骤 | 必做与停止条件 |
| --- | --- |
| S1 身份/模式 | 绑定精确候选权重、结果及模式；不混合不同checkpoint。无效输入停止，已有历史发布名不重命名 |
| S2 匹配参照 | 分开列训练父代与风格参照；Beta以精确Balance为参照，Alpha列Balance及现任Alpha（可取得时）。同对手/模式/seed cohort匹配；缺参照标缺项，不用跨cohort差值冒充匹配结果 |
| S3 描述画像 | 按下表计算双方/候选-参照绝对值与差值，给分母、覆盖率、逐对手与座位；不可得指标NOT_MEASURED，不填0 |
| S4 证据分级 | 根据下面的等级规则给每条路线结论；在看到结果后新选指标只能是descriptive。确认等级需冻结风格政策与独立匹配证据 |
| S5 路线决策 | 按下方决策表选择Alpha/Beta/Balance/mixed/undetermined，允许次要倾向；没有充分区分就保留暂定或不足，不强行三选一 |
| S6 身份记录 | 完成模板画像卡：参照、证据、证据等级、route_history、实际价值与局限。只写路线建议，不自动登记新版本/默认冠军 |

| 画像维度 | 必须观察的指标组 | 不能单独作为风格证明 |
| --- | --- | --- |
| Alpha 大牌冲分 | 3–5VP购牌/印刷分，首张4–5VP购入时点**及覆盖率**，固定Main时点得分/达分比例；相对参照的效率与贵族代价 | 一次大牌购买、总分更高、少买0VP牌、胜率更高 |
| Beta 基建 | 相对匹配Balance的0–1VP购牌数量/占比与时点，后续真实投资兑现，贵族覆盖/数量和VP/本人Main | 折扣总量、reward utility/AUC上涨、买卡多或游戏更长 |
| Balance / 混合 | 同时展示大牌、小牌、兑现、贵族、效率与逐对手；明确预先定义的平衡区间或没有单一突出方向 | 非Alpha且非Beta、差异不显著、只有outcome-only训练目标 |

共同公式：`半平得分=(W+0.5D)/N`；`纯胜率=W/N`；`VP/Main=Σ本人最终VP/Σ本人Main`；`低VP占比=Σ0–1VP购牌数/Σ全部购牌数`；`贵族覆盖=有贵族局数/N`；`大牌印刷分/局=Σ(3–5VP牌数×印刷VP)/N`。首次大牌时点仅在实际购入局求均值，同时报购入局数/N；无购入则NOT_MEASURED而非0。跨组按实际分母合并，贵族选择不新增Main；具体时点定义沿用阅读合同。

**证据等级及路线决策：**

- `INSUFFICIENT`：缺有效匹配参照/必要指标/关键时间窗，或当前误差无法支持方向；路线为undetermined，或保留历史研究分支并注明行为未定。
- `DESCRIPTIVE`：来源与匹配有效、实际画像可读；仅点估计、事后指标或变化未过确认门。可建议“暂偏Alpha/Beta”或mixed；不能写“风格已证实”。
- `CONFIRMED_IN_SCOPE`：采样前冻结该路线主指标、实际效应阈值、配对区间/多重比较及跨对手一致性规则，独立证据全部达到规定组合；范围仅限该参照/模式/对手集合，不是普适标签。
- Alpha/Beta确认政策至少含**实际购牌行为**和**时点/兑现/得分轨迹**两个不同维度，不能只挑两个相关reward代理。冻结哪几项必须通过、哪些仅诊断，不能要求所有指标都正向。
- 确认性Balance必须有正向的平衡定义与预先设定的等效/区间规则，并以区间落入范围为依据；不能以“不显著”代替等效。没有该设计时可保留Balance研究分支，但行为等级不升级。
- 只有Alpha政策达到 → Alpha；只有Beta达到 → Beta；仅Balance正向政策达到 → Balance。任意多条路线政策同时达到或方向冲突时，仅使用采样前冻结的主路线规则；没有该规则则mixed。都未确认时按描述证据标暂定/mixed/undetermined。不得暗设Alpha优先级，也不因Beta失败就转Balance。
- 风格目标失败不阻止有竞技价值的候选进入另一条路线评审。反之，风格确认不能免除其用途对应的竞争底线。
- 购牌行为可能受机会与对手影响。声称“主动偏好/奖励机制/被对手剥夺”等机制时，必须补同局面合法机会条件诊断与覆盖；因果归因还须有受控对照，不能仅靠条件相关性。只描述比赛结果时不强制扩大分析。优先用保存回放，数据不足就限制主张，不自动采新局。

## 7. R8报告做到哪一步

- 新竞技轮先生成冻结证据，再用 `scripts/prism_round_report.py` 和结果hash绑定的 `benchmarks/reports/*-reading.json` 生成阅读层。schema变化用独立验证适配器；不改已pin evaluator和原结果。
- 人类报告先列**产物、竞技、风格**三结论，说明问题/血缘/改动/代价/下一步；默认双方greedy，完整双方Markdown表必须保留，采样历史与Agent审计另页。
- 必须显示每个共同对手的父代/参照/候选，缺记录NOT_RUN；单位、正负变化、较大数值高亮与实际有利方向分开，展示值持平无胜者标记；附可见计算公式。
- Agent审计保存原门及失败含义、来源hash/配置/运行/回放/时钟、原始完整证据。不得将技术细节塞回人类主阅读页。
- 校验结果身份/数量/统计复算范围、双方座位与分母、显示值、缺项、链接、DOM交互。新/改页面布局还检查真实桌面和窄屏像素；工具不可用写NOT_VERIFIED，不以DOM或“已生成”冒充视觉验收。
- R1声明的强制检查未过，整体交付维持review/blocked；若视觉不是该任务强制项，可交报告并明确局限，但不得称视觉通过。新UI/可读性改版默认要求实际像素验收。
- 报告故障只恢复报告，比赛故障按原预算；统计结果不可变。重渲染写新revision并绑定原结果hash，保留原页面/receipt；没有安全入口先做隔离适配，不删除结果后重跑比赛。
- `docs/prism/reports.html` 更新新交付轮。只读评审/文档任务没有新对战数据，不制造空模型结果或强行重跑全量对战表。

## 8. 发布、冠军与部署分四个动作

| 动作 | 必须具备 | 不能推导 |
| --- | --- | --- |
| 路线建议 | R7画像卡与精确权重 | 正式型号或发布 |
| 固定研究版本登记 | 用户指定/已授权发布、R5身份有效、可读既有实战/不足与历史负结果、版本/父代/companion绑定 | 最强、风格确认、默认冠军；用户可发布有局限研究版本，不改旧判定 |
| 默认/冠军晋级 | 对应授权、预先冻结的代表对手/关键退步容忍/总体提升与独立评测政策通过 | 已部署到任何应用；单一胜父或均值通过不够替代该政策 |
| 池/Studio/服务部署 | 指定目标的明确授权、精确发布包、兼容/健康检查、回滚方案及部署后实机证据 | 其他目标上线、Git push或机器关机 |

允许直接完成已授权的指定研究版本发布并解释局限，不强迫补训补赛。缺冠军证据只阻塞冠军声明/默认动作，不否决研究版本价值。Git commit/push单独按当前授权和publication规则执行，禁止为“收口”自动提交用户其他工作。

## 9. 异常、恢复和观测统一处理

- 分别保存 `execution_state`、`observation_state`、`delivery_state`，均附原始observed_at/node/execution/PID身份及证据。计划节点不是实际节点。
- 状态只在同execution内比较：已校验完成回执/提交账本优先于旧进度；新鲜匹配的实际进程用于运行判断。相互矛盾则UNKNOWN并调查，不用文件mtime或ALL标题单独决定重启。
- SSH失败=当前不可达；观察器退出=监控失效；都不证明训练失败。ALL上传失败记录待同步，不得触发研究重跑。报告原采样时间，禁止旧快照刷新成新心跳。
- 正常暂停按控制器安全边界提交。故障保留现场、物理attempt与预算，先核对孤儿进程/产物，已完成job不重赛。已授权重试政策内可恢复；禁止自行清锁、重置deadline、换seed或扩大重试。
- 资源/平台恢复改变须单独execution revision、保留原失败与源码、核算已消耗预算；完整resume验证模型/optimizer/RNG/游标不变。只载权重是warm-start，不冒充resume。
- 已pin源码不原地修补以制造PASS；新适配器绑定原输入及修订来源。修复无效实现后的结果用独立revision，不能悄悄覆盖原结果。
- 运行期间按ALL规则续租/真实心跳；会话结束不等于持续监控。交付写清实际观察器所在节点、依赖、最后核验与自动取回是否真的工作。

## 10. R9完成清单与措辞

- 核对任务授权终点、所有必交件/阶段状态及证据；文件存在≠审计PASS，训练结束≠评测完成，统计完成≠报告交付，报告交付≠版本发布。
- 原科学负结果完整有效时，实验任务可以done且模型NOT_PROMOTED。缺强制证据/确认/报告仍review或blocked，不能用“本次会话结束”关闭整个任务。
- 更新一个连贯轮次文档及紧凑handoff当前索引，旧事实只追加更正；当前记录明确后续哪些已授权。模板、建议与待实现能力标清，不声称控制器已支持它们。
- 检查链接、数值/状态一致性、`git diff --check`；提交前 `git check-ignore -v handoff.md`。handoff永不stage/commit/push，生成/敏感产物遵从publication策略。
- ALL读取最新revision后登记真实产物并回报；409重新读取、保留用户更新。同步失败在最终答复写明，不能声称已同步。
- 最终回复写：完成了什么、实际检查及结果、模型/任务分别的结论、剩余阻塞、下一允许动作。不要列无穷推测阻塞；相关检查通过且范围完成即停止。

**执行示例与自检：**[模板的边界场景](docs/templates/prism-research-record.md#边界场景验收)。流程变更历史与本次验证：[M68研究规程](docs/m68-prism-research-workflow.md)。

---

## 原有文档合同（保留；以上规程补充操作边界）

# Agent Documentation Contract

## Report reading layer (owner requirement, 2026-10-05)

Every new Prism evaluation round must deliver a conclusion-first reading report
in addition to its complete evidence report. Follow
`docs/prism-report-reading-contract.md` and use `scripts/prism_round_report.py`
with a round-specific, result-hash-bound `benchmarks/reports/*-reading.json` spec.
Explain the question, model lineage, artifact/competitive/style verdicts, changes,
failure meaning, and next-step recommendation in plain language. Do not present
internal verdict enums or many wide tables as the main reading path. The reading
layer follows the frozen evaluator/report step; do not edit already-pinned code
or rewrite original results to enable it. If a new result schema differs, add a
verified adapter to this common reading layer. Preserve full Markdown tables,
original HTML, original gates and identities; missing timings stay NOT_MEASURED.
Keep `docs/prism/reports.html` current with delivered rounds.

## Practical promotion and style assignment (owner requirement, 2026-10-05)

Follow `docs/prism-practical-promotion-contract.md`. Competitive match evidence
is the primary basis for promotion; Alpha (large-card scoring), Balance, and Beta
(more building than a matched Balance reference) are observed routes, not labels
fixed by the training objective. Missing a style research target must not be an
automatic veto of the whole model. Consider useful candidates on another route,
check performance across representative opponents and preserve uncertainties.
Keep old frozen gates/results as historical research evidence, separate from a
new owner-directed practical review. Bind any route alias to the exact weights;
do not silently register a released version or imply that provisional Balance
assignment proves a balanced style. Show practical value and current route first,
and place superseded research-contract verdicts in clearly labeled history.

This repository uses a two-layer project record. Every agent that performs a
non-trivial design, implementation, evaluation, release, or review task must
maintain both layers when applicable.

## 1. Read before acting

Before planning or changing the project:

1. Read this file.
2. Read the root `handoff.md` when it exists.
3. Read the active milestone document under `docs/` and the architecture or
   contract documents it links to.
4. Verify the current branch, `HEAD`, worktree state, and relevant artifacts.

Do not treat documentation as proof of current code or external state. Verify
cheap, drift-prone facts directly.

## 2. The two documentation layers

### `handoff.md`: current project truth and navigation

`handoff.md` is the compact, continuously maintained project index. It answers:

- Where is the project now?
- What is implemented, verified, accepted, rejected, frozen, or blocked?
- What evidence anchors each milestone?
- What constraints and known limitations still apply?
- What is the next authorized step?

Update it after a milestone implementation, independent review, acceptance or
freeze, formal evaluation, important contract change, material failure, or
change to the next-step order. Keep historical evidence; append corrections
instead of silently rewriting an old result.

Repository-specific publication rule: the root `handoff.md` is local-only and
ignored. Never stage, commit, or push it. Verify this with
`git check-ignore -v handoff.md` before staging a completed round.

### `docs/mNN-*.md`: one living record per major round

Create or maintain one tracked document for each major milestone or coherent
development round. Use a stable name such as `docs/m24-gpu-review.md`.

The milestone document records the full reasoning arc:

1. original problem and observed evidence;
2. initial design, scope, non-goals, and acceptance gates;
3. implementation contract and information/security boundaries;
4. material iterations, failed attempts, deviations, and why they changed;
5. final implementation and exact validation evidence;
6. result, limitations, decision, and next authorized gate.

Do not create a new milestone document for every trivial commit. Small changes
belong in the active round's iteration log and the handoff changelog. Create a
standalone daily/incident document only when the work is independently useful
and cannot be understood as part of the active milestone.

## 3. Status vocabulary is evidence-bound

Use these states precisely:

- `PROPOSED` / `DESIGNED`: written plan only.
- `AUTHORIZED`: scope approved; implementation may start.
- `IMPLEMENTED`: code exists; this does not imply verification or acceptance.
- `VERIFIED` / `PASS`: named checks were actually run and passed.
- `REVIEWED`: an explicit review occurred; list findings and reviewer scope.
- `ACCEPTED` / `FROZEN`: the milestone's declared acceptance gate passed.
- `REJECTED` / `NOT PROMOTED`: a valid experiment completed but failed its gate.
- `DEFERRED`: intentionally postponed with a reopen condition.
- `BLOCKED`: cannot proceed without named external input or authority.

Never infer `PASS`, `ACCEPTED`, `PROMOTED`, or `COMPLETE` from code existence,
offline metrics, a smoke test, or an agent's delivery summary. Preserve valid
negative results; do not change seeds, gates, or labels after seeing outcomes.

## 4. Evidence and provenance rules

Documentation claims must point to the strongest available evidence:

- exact commit/tag when it exists;
- exact commands and exit status for validation;
- tracked config/result paths and content hashes for formal experiments;
- local artifact paths for generated datasets, checkpoints, logs, and replays;
- explicit distinction between implementation smoke, offline diagnostics,
  competitive measurement, independent review, and promotion/acceptance.

Never invent a future commit hash or record a command as run when it was not.
Machine-verifiable contracts belong in code/JSON/tests; docs explain their
meaning and decision history rather than replacing them.

## 5. Milestone lifecycle

At round start:

1. Create/update the milestone document with baseline commit, problem,
   evidence, scope, non-goals, invariants, plan, and frozen gates.
2. Update `handoff.md` only enough to mark the round authorized/in progress.

During development:

1. Record material decisions and deviations in an append-only iteration log.
2. Preserve failed experiments and explain what they ruled out.
3. Keep generated or sensitive artifacts within the repository's publication
   policy; do not publish them merely because their summary is tracked.

At round completion:

1. Reconcile the milestone document against actual code and artifacts.
2. Record validation commands/results, evidence hashes, findings, limitations,
   and the precise verdict.
3. Update the handoff snapshot, milestone table, next step, artifact index, and
   changelog.
4. Check links, status consistency, `git diff --check`, and publication rules.
5. Commit tracked milestone docs with the implementation. Keep local-only
   handoff and generated artifacts out of Git.

## 6. Required milestone document outline

Every new major-round document should normally contain:

```text
# MNN Title
Status / baseline / owner-date block
## Problem and evidence
## Initial design
## Scope and non-goals
## Contracts and invariants
## Implementation plan
## Iteration log
## Final implementation
## Validation and evidence
## Result and decision
## Known limitations
## Next authorized gate
```

See `docs/project-documentation-system.md` for reusable templates and examples.

## 7. Required readable model match tables (effective 2026-10-02)

Owner requirement: every subsequent model result, release, and evolution document
must contain detailed Markdown match tables for that model. JSON remains the
machine evidence; a JSON link or a win-rate-only summary does not satisfy this
requirement. Design/interface documents for an untested model must explicitly say
`NOT_RUN` and link its result record when one exists.

Each evaluated model/version must show, per opponent and action mode:

- games and seed blocks, wins/draws/losses, pure win rate, half-draw score rate,
  paired confidence intervals, and physical first/second-seat breakdowns;
- both players' final VP, scoring velocity, game-duration distribution, purchased
  cards by VP 0..5, permanent discounts by color, nobles and noble coverage;
- both players' reserve acquisition, purchase, terminal unbought cards and
  redemption rate, plus all seven action counts and percentages;
- observed game/campaign timings with clock scope and load; unavailable decision
  or inference timings must be `NOT_MEASURED`, never zero or inferred;
- frozen opponent/model/runtime identities, seeds, config/result/replay provenance,
  source hashes, and the precise development/acceptance/diagnostic verdict.

Follow `docs/unified-match-metrics-standard.md`. When seats are exchanged,
aggregate by model identity before combining seats: physical P0 is not always the
candidate. Compute ratios from summed counts/denominators, preserve failed gates,
and distinguish new descriptive metrics from the original frozen acceptance tests.
Use the owner's canonical model version (this round: `Prism v0.1.1`); keep old
frozen experiment filenames/hashes as provenance with an explicit naming correction.

Human-facing documentation must spell the full model version, e.g. `Prism v0.1.1`. Conversational dotless shorthand is not a documentation model name. Every match table must state the measured model, opponent and whether its metric belongs to one player or the whole match. An unpublished training checkpoint must be labeled as such, never mistaken for a released version.

Start model reports with the artifact, competitive and style conclusions separately.
Before the full tables, show a compact matched baseline-to-candidate comparison
with units, signed changes, bold emphasis and up/down markers. Separate development
from independent acceptance data. Optional color views must include text markers;
a higher metric is not automatically better or statistically significant.
For every gate show its purpose, frozen threshold, estimate, uncertainty and
specific failure meaning. A style model may trade strength or economy within a
declared tolerance: do not require all descriptive metrics to improve. Preserve
the original verdict and all detailed tables when adding a clearer interpretation.

### Owner report correction (2026-10-05, current precedence)

- Human reports default to both-greedy matches. A greedy opponent does not make a sampled candidate greedy. Keep historical sampling in a separate page; include it by exception only after matched competitive evidence supports the sampling mode.
- Show current and reference generation against every common opponent side by side. Clearly name the reference and display missing records as NOT_RUN. Never pool different action modes or seed cohorts.
- Highlight/bold the side with the larger displayed value in every two-player/version comparison; use a distinct marker for a practical advantage (including lower losses/unbought reserves) versus descriptive magnitude. Display ties without a winner marker.
- Building profiles prioritize scoring efficiency, noble coverage and 0–1 VP purchase behavior relative to Balance. Discount utility, discount totals and reward proxies alone do not establish small-card preference. Supply a literal formula for computed metrics that remain visible.
- Keep hashes, runtime/config/replay manifests, raw research verdicts, thresholds and statistical tutorials in a separate Agent audit report. The human HTML/Markdown must contain readable detailed match tables and direct conclusions. Full technical evidence and original gates remain intact in the audit layer; do not simply collapse them within the human page.
