# Prism 研究执行记录模板

规范来源：[根 AGENTS.md](../../AGENTS.md) 的 `prism-research-workflow-v1`。
用途：把下面适用段落填入同一轮 `docs/mNN-*.md` 或已有合同/审计记录。**这是文档模板，不是控制器输入、可执行JSON schema或已运行实验。** 不适用字段写 `NOT_APPLICABLE + 原因`；设计期可TBD，执行所需必填项未确定则不进入R3。

## A. 任务边界卡（R0）

| 字段 | 本轮填写 |
| --- | --- |
| milestone / task_id / owner-date | TBD |
| task_kind | review / design / implementation / pilot / experiment / evaluate / report / release / deploy / status |
| authorization_source | 用户原指令、日期、允许的有限范围；不是引用旧文自动授权 |
| authorized_end | 哪一个阶段/动作及交付完成为止；例如R9但不含发布 |
| current_stage / next_allowed_action | TBD |
| baseline_branch / HEAD / worktree | 实查值、源码包/未提交范围 |
| question / hypothesis | 一句问题与可证伪预期 |
| task_acceptance | 本任务必交件与验收检查；不可把增强作为有效实验任务必须成功的条件 |
| forbidden_actions | 未授权训练、补赛、发布、默认替换、部署、commit/push等适用项 |
| planned_node / actual_node | 分开；实际节点未观察则UNKNOWN |

## B. 有限研究合同（R1）

### 身份、变化与初始化

- measured_model：已有待评测模型填写精确权重路径/SHA；尚未训练时只写预定“最终cN未发布训练检查点”和选择规则，产出后在R5补SHA，不能编造未来hash或把尚未产出当启动阻塞。
- training_parent：完整身份与SHA；它不一定是风格参照。
- initialization：fresh optimizer warm-start / full-state resume；旧optimizer/RNG/游标/预算来源。
- control：对照来源、匹配项、唯一主要变化及有意不匹配项。
- non_goals / causal_limits：不能从这轮得出什么。
- source_bundle：源码、依赖锁定、二进制、规则、schema、数值环境的路径/SHA和取回位置。

### 数据、种子与预算

| 阶段/臂 | 训练RNG seed | 环境seed范围/重叠关系 | 局数/换座块 | 用于选择候选吗 | 预算/截止 |
| --- | --- | --- | --- | --- | --- |
| 工程校准 | TBD | 与研究分离 | TBD | 否 | TBD |
| 训练臂/重复1..N | TBD | 指定配对/独立关系 | TBD | 按预设开发规则 | TBD |
| 开发评测 | TBD | 不进入独立确认 | TBD | 是/否，事先说明 | TBD |
| 独立确认 | TBD | 未用于调参/选择 | TBD | 否 | TBD |

- exploratory_seed_count及理由：默认优先至少3个；预算不足记录pilot/有限重复，不擅自扩量。
- opponent_manifest：每个对手的精确权重/模式/runtime、训练内外角色、纳入/排除原因。
- training_budget：cycle、games、decision、update/pass、minibatch、并发与线程、CPU/GPU/RSS/磁盘、墙钟/绝对deadline。
- evaluation_budget：固定网格、对手权重、同seed双座匹配、物理执行/逻辑局数、资源、超时和重试上限。
- selection_policy：固定最终cN或开发集算法、候选数、平局规则、候选冻结时刻；独立结果不得参与选择。
- retry_policy：默认研究自动重试0；若获准例外，列类型、次数、seed/权重不变、预算扣减与回执。
- stop_policy：成功结束条件、基础设施失败、数值/审计失败、预算到限、用户暂停、各自下一动作。

### 竞技判定政策

| gate_id / purpose | 主指标/单位 | 对照与cohort | 冻结阈值/方向 | 判估计或置信界 | CI/单双侧/family | 失败意味着什么 |
| --- | --- | --- | --- | --- | --- | --- |
| retention_pool | TBD | TBD | TBD | TBD | TBD | 例如保留未确认，不自动证明退化 |
| enhancement_pool | TBD | TBD | TBD | TBD | TBD | TBD |
| direct_reference | TBD | TBD | TBD | TBD | TBD | TBD |
| critical_opponents（冠军用途） | TBD | TBD | TBD | TBD | TBD | 不与池平均互相替代 |

- primary_metric：默认 `(W+0.5D)/N`；`W/N`另报。
- sample_size_rationale：最小有意义效应、容忍度、预算、配对方差/功效依据；无先验可标有界pilot，不保证必显著。
- statistics：bootstrap单位为配对seed块等明确值、次数、RNG、多重比较family与规则、普通区间和确认界分开。
- training_seed_inference：逐臂/逐seed结果、是否估计算法总体效果及方法；不将对局数当训练重复数。
- sequential_policy：默认固定样本；如有序贯设计，采样前写规则。没有则看见结果后不可加样本刷PASS。

### 风格确认政策（如适用）

`style_mode = descriptive / confirmatory`，默认descriptive。确认性政策需在其独立数据采样前冻结；事后选的指标保持descriptive。

| 路线/维度 | matched_reference | metric_id / literal_formula / horizon | direction / meaningful_delta | uncertainty / multiplicity | cross_opponent_rule | mandatory_or_diagnostic |
| --- | --- | --- | --- | --- | --- | --- |
| Alpha实际购牌 | TBD | TBD | TBD | TBD | TBD | TBD |
| Alpha时点/得分轨迹 | TBD | TBD | TBD | TBD | TBD | TBD |
| Beta实际0–1VP购牌 | 精确Balance | TBD | TBD | TBD | TBD | TBD |
| Beta兑现/贵族/效率 | 精确Balance | TBD | TBD | TBD | TBD | TBD |
| Balance正向区间/等效 | 精确参照 | TBD | TBD | TBD | TBD | TBD |

只填写本轮声称确认的路线；其他路线可做描述。必须写出指标组合如何决定通过，不允许看结果后挑其中有利的两项。缺乏确认设计不是阻塞整轮的理由，结果降为DESCRIPTIVE即可。

### 预检与交付政策

- R2_commands / expected_checks：相关测试、工程贯通、旧输入适配、故障注入、规模校准；不得伪造现有命令。
- R3_commands / identity_checks：实际程序/args/cwd/节点、parity、资源预留、归属、没有重复启动、deadline。
- backup_recovery：精确状态、日志/原回放、原字节/SHA、重渲染/取回路径。
- observer：运行地点、依赖、采样时间、失效检测、ALL上传与研究执行分离。
- output_manifest：必须文件、形成它的阶段、原始/阅读/审计层、hash与取回要求。
- R8_required_checks：统计复算/抽样范围、数值、双方归属、DOM、链接；页面布局任务默认包含桌面/窄屏真实像素。
- authorized_publication：路线建议/研究版本/冠军/目标部署/commit/push逐项是或否。

## C. 阶段执行回执（R0–R9）

每行填写状态和证据；PASS指阶段工作合格，不代表竞技或风格增强。已有合格证据可引用；不重新运行只为填表。

| stage | applicable / reason | status | 实际命令/exit/观察时刻 | artifact / sha | conclusion | next_allowed_action |
| --- | --- | --- | --- | --- | --- | --- |
| R0 | TBD | NOT_RUN | TBD | TBD | TBD | TBD |
| R1 | TBD | NOT_RUN | TBD | TBD | TBD | TBD |
| R2 | TBD | NOT_RUN | TBD | TBD | TBD | TBD |
| R3 | TBD | NOT_RUN | TBD | TBD | TBD | TBD |
| R4 | TBD | NOT_RUN | TBD | TBD | TBD | TBD |
| R5 | TBD | NOT_RUN | TBD | TBD | TBD | TBD |
| R6 | TBD | NOT_RUN | TBD | TBD | TBD | TBD |
| R7 | TBD | NOT_RUN | TBD | TBD | TBD | TBD |
| R8 | TBD | NOT_RUN | TBD | TBD | TBD | TBD |
| R9 | TBD | NOT_RUN | TBD | TBD | TBD | TBD |

状态：NOT_RUN、IN_PROGRESS、PASS、FAIL、BLOCKED、NOT_APPLICABLE。科学结论单列，不能为跳过失败写不适用。

## D. 风格画像卡（R7 / S1–S6）

| 身份字段 | 值 |
| --- | --- |
| weight_path / weight_sha256 | TBD |
| display_name / release_status | 完整型号；未发布就明确标注 |
| training_parent / parent_sha256 | TBD |
| training_objective / historical_branch | 训练事实，不当作观察结论 |
| action_mode / cohort / opponents / source_result_sha256 | TBD |
| strength_reference / style_references | 分开列；各自精确权重/模式/cohort |
| style_policy / frozen_before_sampling | 路径/SHA或DESCRIPTIVE_ONLY |

| 指标/公式/单位 | 参照值 | 候选值 | 差值 | paired_CI / coverage | 跨对手/座位变化 | 缺项与局限 |
| --- | --- | --- | --- | --- | --- | --- |
| Alpha购牌/印刷分 | TBD | TBD | TBD | TBD | TBD | TBD |
| 首张4–5VP时点与购入覆盖 | TBD | TBD | TBD | TBD | TBD | TBD |
| 固定Main得分/达分率 | TBD | TBD | TBD | TBD | TBD | TBD |
| Beta相对Balance的0–1VP数量/占比/时点 | TBD | TBD | TBD | TBD | TBD | TBD |
| 真实投资兑现 | TBD | TBD | TBD | TBD | TBD | TBD |
| 贵族/覆盖与VP/本人Main | TBD | TBD | TBD | TBD | TBD | TBD |

- evidence_level_by_route：INSUFFICIENT / DESCRIPTIVE / CONFIRMED_IN_SCOPE，逐路线说明依据；不是单一“高置信”修辞。
- proposed_route / secondary_tendencies：Alpha / Beta / Balance / mixed / undetermined；未确认时前缀“暂偏/描述性”。
- required_metric_combination：对照原政策逐项判，或明确没有确认政策。
- mechanism_claim：无 / 主动偏好 / 奖励因果 / 对手剥夺等；非“无”时附同局面机会条件诊断与覆盖，不据比赛相关性推因果。
- practical_value / tradeoffs：棋力、用途及容忍代价；风格门失败是否仍有其他用途。
- route_history：时间、旧建议、新建议、原因和证据；权重不变也保留归类修改历史。
- registration_authorized / default_promotion_authorized / deployment_targets：逐项列授权。建议路线不是这些动作的授权。

## E. 观测与异常回执

| 字段 | 值 |
| --- | --- |
| execution_id / node / pid / create_time | 精确值或UNKNOWN |
| observed_at / source / freshness | 原观察时间，不是上传时间 |
| execution_state | 实际运行/已提交停止/失败/未知，附完成回执与账本 |
| observation_state | 观察器存活/失效/过期，附实际核验 |
| delivery_state | 未产出/待取回/部分失败/已验证交付 |
| scientific_progress | 已完成局/已提交cycle/已应用更新，区别在途和attempt |
| physical_attempts / consumed_budget / deadline | 原账本，不重置 |
| failure_reason / evidence | 确认原因和猜想分开 |
| recovery_policy / authorization / new_revision | 没有授权则只读诊断，不启动 |
| scientific_state_fingerprints | 恢复前后模型、optimizer、RNG、游标；无恢复则N/A |

## F. 最终结论与R9清单

- task_verdict：done / review / blocked，按授权终点和强制交付项。
- artifact_verdict：有效/无效/待审计。
- competitive_verdict：保留、增强、退步或未确认及适用范围；原门保持。
- style_verdict：各路线证据等级、建议与历史名称的区别。
- publication_verdict：未发布/研究版本/默认晋级/哪些目标已部署；分别列。
- validation：实际命令、exit、数量、证据SHA；独立复算与原回执读取分开。
- documents：轮次记录、handoff当前索引、报告索引、ALL task/artifact同步回执。
- publication_check：diff/links、handoff ignored、敏感/生成物政策、commit/push是否获准及是否实际执行。
- remaining：具体缺项、原因、是否阻塞本任务，禁止无穷推测风险。
- next_authorized_action：如果没有则“仅建议，尚未授权”。

## 边界场景验收

这些是后续Agent必须作出的**预期行为**，不是代码已自动执行的测试。修订规程时逐项确认仍能得到唯一且不越权的动作。

| ID | 场景 | 必须得出的动作/结论 |
| --- | --- | --- |
| C01 | 用户只让review扩量瓶颈 | 只读诊断/必要零研究局验证与报告；不直接优化训练或恢复进程 |
| C02 | 用户批准整轮训练与独立评测，R3通过 | 自动推进已授权阶段至R9；不重复逐步审批，也不停在“已启动”当完成 |
| C03 | 全部有效对局完成，但增强区间跨零 | 报未确认、保留原门；报告/收口完成可done，不为显著加样本 |
| C04 | c12开发表现好，但合同只选最终c20 | 继续合同内执行并只用c20；不能换c12参加确认 |
| C05 | Beta目标失败，但实战有用、Alpha画像偏向成立 | 保留原Beta负结果；按R7建议暂偏/确认Alpha相应等级，不整体否定，不自动发布 |
| C06 | 候选比Alpha父代多买小牌，缺匹配Balance | 不能确认Beta；列缺项/描述性变化，路线不足或保留历史分支，不自动补赛 |
| C07 | Alpha/Beta差异均不显著 | 不宣称Balance或等效已证实；mixed/undetermined或暂定研究分支 |
| C08 | 已确认Alpha与Beta同时满足，没有主路线优先规则 | mixed并记录双倾向；不按字母顺序或训练目标强行挑一类 |
| C09 | 共同池均值提高，但关键对手代价超冠军合同容忍 | 不授予默认冠军；研究价值另报，不篡改总体池原PASS |
| C10 | 结果JSON已写，第二张HTML失败 | 只做hash绑定报告修订/补页，保留失败和原结果；不删结果重赛 |
| C11 | 本机观察器退出/SSH不可达，远端状态未知 | 写监测失效/不可达和最后观察时间；不判训练死、不清锁重启 |
| C12 | 自动重试预算0且已耗尽墙钟 | 保留现场并停止；恢复/扩预算需明确授权及独立revision，不能重置旧deadline |
| C13 | 用户指定发布已有研究版本，但冠军证据不足 | 身份与证据有效则完成指定研究登记并解释不足；不强制新采样，不改默认 |
| C14 | 用户只要求实现报告修复 | 代码/相关测试/文档收口即可；未授权新研究对局，不为模板字段跑训练 |
| C15 | 事后发现可解释画像的新指标 | 可只读descriptive补充；原确认门与结果保持，不追记CONFIRMED_IN_SCOPE |
| C16 | 无一局购入4–5VP牌 | 购入覆盖率0是真值；首次购入条件均值NOT_MEASURED，不填0Main |
| C17 | 用户要求新UI可读性验收，但浏览器视口不可用 | 交付已有文件和DOM证据，视觉NOT_VERIFIED，任务review/blocked；不声称完整验收 |
| C18 | 资源只够两个训练seed | 已批准则做有限重复并说明范围；不擅自加第三个，不称方法总体稳健 |
| C19 | 已有独立验收数据被用于挑选候选 | 该数据转为开发依据，不能再声称该选择的独立确认；新确认另需冻结和授权 |
| C20 | 新代码改了批形状或设备，旧parity曾PASS | 重新验证适用数值/恢复边界、绑定新运行身份，不用旧PASS或热改正在训练的M67 |
