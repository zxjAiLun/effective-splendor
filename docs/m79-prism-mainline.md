# M79 · M75 后继主线执行合同

**2026-10-14 M79 R9交付已完成（本地证据核验）。** 固定c20训练5120/5120、审计PASS、开发1023终局+原有1截断、独立评测12288/12288均按原账本；候选、父代、固定Balance参照各3072局保存回放画像。冻结竞技推荐门未通过，候选未晋级；画像DESCRIPTIVE，路线undetermined/INSUFFICIENT，不宣称风格确认。root `transfer-manifest.json` 缺失已按真实schema由冻结evaluation-plan、分片清单、逐局ledger/replay SHA构建独立派生inventory，并通过独立r37归档适配器验证；未借migration-r7清单、未改原结果、0新局。阅读报告R2、候选卡、报告索引及1440桌面/390px像素验收已完成。归档R31–R36失败及费用保留。ALL不可达，登记待同步。详见completion-r37节及delivery-manifest；本轮无新轮、发布、部署或Git提交。

**通知规则：** 仅确需用户操作或整轮交付完成时通知。R9核验收口后已按授权停用m79本轮heartbeat；未改变此前每小时频率设置。

**2026-10-13 23:38 Luna最新核验：r30主流程已于22:22:30正常结束，审计及报告PASS，训练5120局，开发1023终局+既有1截断，独立12288/12288零缺局/截断。7份报告/证据已取回并SHA一致。当前是待画像归档/视觉/R9，并非仍在审计。归档入口缺root transfer-manifest.json，须正确绑定现有评测树，不能借用migration-r7旧迁移清单。整轮暂估10月14日00:45–04:45北京，条件为清单问题及时解决；画像/归档耗时仅规划估算，非实测。证据见luna-monitor/status-eta-20261013T2338+08.json。**

**2026-10-13 21:30当前状态：训练16:42已完成5120/5120、固定c20/1108更新。r29审计18:59:27因attempt326/process-result.json缺失退出，21:25核验无活动进程；此前18:30–20:30交付估计失效。已核验原relay与migration-r8恢复回执SHA及completion.resources逐项一致，独立r30于21:29恢复原relay精确字节到缺失路径，未改completion、模型、run/ledger HEAD或重跑对局，保留旧审计失败目录。新协调PID165528/create1791898152.81，21:30实测AUDIT/RUNNING。监控仍由Luna每小时负责，当前活动入口应取r30，不能将r21历史入口/PID当作当前事实。审计未通过，尚无可靠整轮完成ETA。**

**2026-10-13 监控交接：用户指定告警与监控改由Luna子代理负责。已实际创建gpt-6-luna（medium）子代理Avicenna，agent_id=`01a134a0-a562-7932-aee0-47be31cd7e64`；现有m79 heartbeat通过应用工具改指该子代理，维持每小时一次，不新增第二份调度。原Sol目标聊天`01a12bd4-1493-7f21-b0dd-e881b8123739`已核验idle，原调度不再唤醒它。仅正常告警与监控责任交接，远端主执行链继续。Luna沿用必要用户操作/整轮交付通知规则；可自行处理的故障在原授权内接续，复杂修复向父代理回报，不等待用户重复授权。接手证据保存在`local-artifacts/prism/m79-mainline/luna-monitor/`。**

**2026-10-13 16:41更正：现有M79自动跟进已通过应用工具实际改为每小时一次，ACTIVE，配置读回一致；旧15分钟及30/45分钟空闲提醒不再适用。16:40远端实测5120/5120采样、c20最终优化进行中（日志global_step1073），尚无c20导出；PID14312/create1791868117.31与r21源码SHA一致。前两个周期最后更新至导出约124–125秒，本次c20于16:40:15封批，预计16:45前后训练交付，整轮含评测/审计/画像/报告取回与视觉预计18:30–20:30北京时间；这是估计，不是停止截止。**

**最新用户执行与通知修订（2026-10-13）：本轮持续自动推进至完整交付；正常运行、阶段推进、空闲和已自行解决的故障均不提醒。故障先在已有授权内自行核验、修复、恢复并接续，不等用户再次说“继续”。仅确实需要用户操作或整轮交付完成时通知。本要求覆盖本文历史段落及旧自动跟进提示中的30/45分钟空闲、普通失败/失联和阶段变化通知。具体执行边界与配置状态见下节。**

## 2026-10-13 最新跟进规则：自动处理，仅必要操作与整轮交付通知

- 用户授权原文：“正常运行和空闲别再提醒我，出问题你自己处理，只有需要我操作或者整轮跑完了再通知我，别又卡住等我喊继续。”本次修改仅涉及M79跟进与通知，不启动新研究局，不改变冻结科学合同。
- 现有后台跟进保持运行。每次核验执行身份和真实账本；可自行处理的执行、传输、报告故障在既有有限预算内修复并继续，必要时建立独立执行修订，保留旧来源、失败与累计消费；不能用“需要另立修订”作为等待用户重复授权的理由。
- 正常进展、阶段转换、DSW2等待/空闲（包括30/45分钟）、可自行恢复的故障只记入本轮证据，不向用户发送状态消息。辅助节点失联但主链可完成时，不要求用户重开辅助实例。需要用户操作的同一未变化阻塞只通知一次，仍继续不依赖该阻塞的工作；收到恢复信息后核验并直接接续。
- 仅在确需人工开机/连接/认证、真实资源耗尽且必须改变已授权预算等情况下，请求具体必要操作。不得为避免通知而改变科学门、无限重试、重赛已完成局，或空转保活。
- 完成终点为原训练、固定c20、原开发/独立网格、审计、画像、报告取回及校验、真实视觉检查和适用R9记录；有效负结果仍正常交付。单阶段完成不发“整轮完成”消息。ALL不可达单独保留待同步，其他交付照常推进。完整交付后一次性通知并停用本轮跟进，不启动下一轮。
- 配置状态：已尝试通过Codex automation_update更新现有m79，无新增自动化；工具返回“MCP tool call requires approval, but approval policy is never”，因此该次设置写入失败，旧自动化提示与调度保持原值。旧提示要求每次先读本文最新修订；执行者须据本节采用最新用户规则，不能继续沿用历史提醒条款。新规则已写入本轮文档和handoff，但尚未观察到下一次后台唤醒，不能宣称端到端通知抑制已经验证。跟进仍依赖Codex应用运行。

上述配置阻塞已于16:39解决：automation_update返回Updated automation，m79保持原目标聊天并ACTIVE，改为每小时一次；本机TOML读回验证通过，updated_at=1791880738551。新提示已删除旧空闲提醒并明确仅必要用户操作/整轮交付通知；后台完成本轮后停用。调度与提示落盘已验证，下一次唤醒的实际通知行为仍待运行观察。本轮主阶段由DSW进程连续自动推进，不等每小时唤醒才开始下一阶段。

本次实测与ETA证据：`local-artifacts/prism/m79-mainline/completion-r21/readback-20261013T083859Z.json`、`hourly-policy-readback.json`、`hourly-policy-eta.json`。原5120训练局全部终局，0截断/infra，c20最后优化未结束；父代及风格参照7168局已完成，余c20开发256及候选独立5120局。评测时间以同轮辅助6728局3122秒调度耗时作参考，当前主流程复用已完成分片；审计、报告、取回/视觉尚未实测全程，整轮估计包含这些不确定性和低频跟进等待。DSW2当前连接拒绝，不构成主链前置，无需用户为辅助开机。未改运行源码、局数、科学门或累计CPU额度；无日历到点停机。

**当前执行修订（2026-10-13 13:14，北京时间）：用户明确要求继续跑完，completion-r21 已于13:08恢复实际训练。最新4153/5120、c17、886更新、0截断/infra；不是等待启动。旧01:00训练/08:37全轮日历截止已被本次授权取代，原局数、CPU累计额度、种子、固定c20与科学门保留。恢复入口和证据见本文末尾“completion-r21”。下方原规划/截止均作为历史保留。**

日期：2026-10-12（北京时间）。状态：**执行方案已定，交由 Sol 完成工程绑定并执行**。规划基线：`m61-alpha-balance-ab` / `a9a0037d82b05af0c55782f6dc2c0e2e72e6f6bd`；工作树包含既有M75/M78修改，以本轮来源包而非HEAD独自代表执行来源。

## 给 Sol 的执行指令

**这是执行任务。读取本文件与 `benchmarks/m79-prism-mainline.execution-plan.json`，完成必要适配、零局预检后直接启动 M79，并推进到最终评测、画像、报告和收口。不要再询问是否开始，不要停在复述建议。** 用户已明确分工：本聊天定方案，用户将方案交给 Sol 执行。转交本合同就是本轮派工，不需要再次批准相同范围。

你可自行完成原子账本、三被测模型网格、报告与恢复入口的工程适配，建立独立部署，生成源码/环境/命令和期限绑定，使用既有DSW/DSW2与server1有限恢复设施。科学参数按本合同；通过阶段门后自动推进。ALL离线、路线未确认、某个非依赖端点缺项均不能成为“等待用户决定是否继续”的理由。不要重新规划一套路线，也不要把本计划当作可直接执行的旧M75配置：M75脚本有轮次、seed、总局数和双模型硬编码，须在M79隔离适配后运行。

当前尚不存在M79可执行控制器；补齐它属于你本轮获派的工程工作。运行命令、PID、节点和deadline必须在实际建立后报告，禁止把合同交付称为研究已启动。

## 任务边界与假设

`task_kind=experiment with necessary engineering adaptation`；`authorized_end=一次有限后继训练及完整R0–R9适用阶段`。问题是“从M75 c20再训练一段，是否进一步增强并守住旧锚点”。父候选为M75 c20，SHA `eaa1331b29599f239299b5a9037100ae042c6021b2195df3f675c2eb5bd62bf5`。本机实际权重已重新hash，路径见JSON assets.parent。

单条实用训练轨迹，目标是获得更强模型；不宣称方法跨训练seed稳定。保持网络、编码、规则、PPO与无风格奖励的核心。训练池的parent随血缘替换为M75，不把本轮增益单独归因于训练长度。完整终局、科学截断、基础设施失败分别计数。

本合同排除新一轮、版本发布、默认替换、应用部署、Git提交/推送、未经归档验证的历史删除和预算扩大。M75原科学结果与发布身份不改。

## 冻结科学参数

| 项目 | 决定 |
| --- | --- |
| 初始化 | 从精确M75权重fresh AdamW/RNG warm-start；不混称full-state resume |
| 训练 | 单seed 79010001；20周期×256=5120逻辑尝试；环境17001000–17003559，各双座 |
| 每周期 | 128 seed块，按General/M75父代/Alpha v0.2.0/Balance v0.2.1循环，每块双座；各对手总1280尝试 |
| PPO | lr 3e−5、2 passes、minibatch256、clip .2、entropy .01、GAE .95、targetKL .02、value weight .5、grad norm1、weight decay0、优势归一化；两个style权重0；其余字段逐项见JSON，沿M75 |
| 训练动作与上限 | categorical T=1；256ply；最多8科学截断，第9次停止；截断不作终局胜负训练，不补seed |
| 最终候选 | 固定第20周期完成导出c20，全部5120逻辑尝试记账；中间导出全部保留，不回选最佳点 |
| 开发曲线 | c5/10/15/20各256局，环境17040000–17040127双座，对M75父代，双方greedy；共1024，固定检查点描述，不能反馈调参 |
| 独立评测 | 共12288尝试，双方greedy，512ply，32双座seed块/分片；最多8科学截断，第9次停止新派局并报告 |
| 工程新局 | 0；以保存回放、合成账本、现有parity与崩溃恢复模拟完成验证 |

独立网格构成如下。`base`是M75，`a`是待冻结M79 c20，`style-reference`是固定Balance v0.2.0（SHA `e2914425cac49f0f2272c44379e46a43525d97ced2eaac206e8600ebf73e79c4`）。固定风格参照不进入父子竞技指标。

| 子集 | 被测模型 | 每模型数量 | 种子 |
| --- | --- | ---: | --- |
| 六共同对手 | base、a、style-reference | 3072 | Heuristic17010000、General17011000、Balance v0.1.0 17012000、Alpha v0.1.4 17013000、Beta v0.1.0 17014000、Alpha v0.1.5 17015000；各连续256 seed×双座 |
| 两个较新对手 | base、a | 1024 | Alpha v0.2.0 17020000–17020255；Balance v0.2.1 17021000–17021255；双座 |
| 直接父代 | a对base | 1024 | 17030000–17030511，双座 |

因此独立评测 `3×3072+2×1024+1024=12288`，全轮 `5120+1024+12288=18432` 逻辑尝试。已有历史数据不替代新网格基线。规划阶段扫描benchmarks未发现17001000–17040127已有数字占用；Sol需在首次采样前完成正式全局seed登记核验。若确有并发冲突，停止该绑定并报告真实冲突，不静默改种子。

## 判定与停止

主指标半平得分，纯胜率另报。先按模型身份归并双座，再以环境seed为配对单位。共同池对每个对手分别生成candidate−base配对块差值，六对手等权。bootstrap每次对各对手独立有放回抽取256个块，候选与父代使用相同块；直接父代抽512块。20,000次，PCG64/79029999，端点RNG顺序与linear分位方法见JSON。

| 判断 | 冻结要求 |
| --- | --- |
| 共同增强 | 增益点估计≥2pp，单侧校正下界>0 |
| 直接增强 | 半平点估计≥52%，单侧校正下界>50% |
| 基础保留 | 共同增益下界≥−5pp；直接半平下界≥45% |
| 较新对手保留 | Alpha v0.2.0、Balance v0.2.1各自candidate−base下界≥−3pp |
| 旧锚点保留 | Heuristic v0.3.1、Alpha v0.1.5各自candidate−base下界≥−3pp |

增强、较新对手保留、旧锚点保留分别是两个端点的family，各alpha .05，单侧下界分位.025；普通95%区间另报。不把三个family包装成一个全家族95%结论。上述全部通过，才给“下一段主线父候选推荐通过”；发布/冠军/部署另行决定。样本沿M75的实用精度，不宣称对2pp小增益或3pp等效有80%功效；未通过保留不自动断言真实退化。

缺终局或单座的端点维持INCOMPLETE，不填平局、不补赛、不换seed。给缺失半平分取0/1的最坏/最好点估计界作诊断，不把它们当真实结果或原门PASS。某端点缺项不会阻止其他有效端点、画像、报告交付。负结果、未确认和不完整结论都必须交付，不能循环加样本或停在“待决定”。若训练审计失败或没有合法c20，依赖的最终评测停止，仍交付已产生证据与失败原因。

## 描述画像与归档

父代比较回答变化方向；固定Balance v0.2.0比较回答描述性风格归类。沿用已有v020工程阈值和本人Main12/24、每投资3/每局24兑现封顶语义，政策SHA见JSON。输出购牌0–5VP、首次4–5VP时点及覆盖、Main12/24得分轨迹及窗口覆盖、早期小牌/兑现、贵族、效率、逐对手与座位。现有投影未直接提供的固定时点得分由保存回放离线抽取并测试，不追加研究局。

三模型共享完整对手块用于描述聚合，排除项明确列出；无共同完整块时保留逐对手可用结果和不足。路线允许Alpha/Beta/Balance/mixed/undetermined，证据上限DESCRIPTIVE，不升级为确认性风格。缺固定参照、风格不匹配、Beta未出现都不否决竞技价值。

归档现有入口 `scripts/prism_candidate_archive.py:199` 仍有a/base循环、M75文案、beta排除和“等待下一轮决定”固定字段。独立M79适配支持三个模型、声明网格、实际缺项与当前阶段；生成M79报告时不能留下“当前轮等待授权”陈旧文案。复用 `scripts/prism_replay_profile.py:299`，保留M75原输出字节。必须测试：SHA漂移、三模型身份、重复/缺失座位、逐对手种子、科学截断与基础设施重试区分、恢复只消费一次、原统计复算、时点覆盖与短局、报告缺项及视觉绑定。

## 节点、期限与恢复

- 最晚首次采样：**2026-10-12 12:00北京时间**。全轮有效截止为 `min(首次研究派局+30小时, 2026-10-13 18:00北京时间)`。Sol在第一局前把实际绝对截止写入launch receipt，恢复不能重置。
- 训练上限18小时/150,000 CPU秒。全轮300,000 CPU秒：训练150,000，开发与评测120,000，审计/传输/控制30,000；跨节点与所有尝试累加，不能在子任务或重启清零。
- DSW优先训练；DSW2先评base和固定风格参照，检查点到达后做开发曲线，c20审计后做候选独立评测。DSW训练/审计结束可接剩余评测分片；统一分片租约、完成账本和单写入权，绝不双派。
- 每节点评测最多8 worker，实际并发不超过cpuset；训练沿原4核资源、torch2线程和已验证worker形状；训练与DSW评测不并行。训练RSS8GiB，评测进程树RSS16GiB。
- DSW本轮目录38GiB（含训练32GiB），DSW2目录12GiB；每个磁盘另留8GiB，最低分别46/20GiB空闲。既有占用与在途数据计入容量预检；无足够容量则阻塞，不能擅删未核验历史或扩大上限。
- 若只有一个研究节点可达，容量/数值parity通过即可按相同预算串行执行，无须等另一台；若两个节点均需要你无能力完成的平台开机，报告具体节点与操作请求。SSH失败不等于机器已关机。
- 已提交完成局0重赛；科学失败0重试；每个未完成基础设施中断逻辑任务允许1次同身份恢复尝试，全轮额外物理尝试≤64，总物理上限18496。存在有效终局/科学失败的任务不能使用此重试。先核对孤儿与已落盘回执，模型更新逻辑只消费一次。
- 协调器每节点最多6次重启，传输每对象最多6次，退避10/20/40/60/120秒，每次传输重试段≤600秒且不得越总截止。全部失败与费用保留。
- 将已有持久启动入口、server1恢复检查绑定到M79独立执行；完成/截止后终止本轮恢复，不能复活M75。平台开机能力与实例启动后的任务接续分开报告。
- 等待开始、30/45分钟、失联或恢复受阻时提醒；研究等待时钟不冒充平台空闲计时。保留Codex提醒目前PAUSED设置，不擅建/恢复应用定时任务；依靠执行中Sol及既有获准监控能力报告，确无通知通道时说明。不要用无意义负载保活。

## Sol的推进顺序

1. 接单后立即核验AGENTS、handoff、任务revision、真实节点/容量/进程归属，绑定输入。旧进程未确认归属时不清锁或杀进程。ALL不可达保存pending记录，照常做本轮获派工作。
2. 实现独立M79配置、蓝图、调度、统计与三模型归档适配；相关本地/实际Linux零局检查与68输入parity通过。工程源包、依赖、binary、规则/heuristic身份、全seed网格、完整命令和恢复绑定写入R3回执。
3. R3全过直接启动。仅在获得实际PID/create_time/execution/path和第一条有效进度后，向用户报告“已启动”、实际分工、绝对截止及匹配实测速率ETA；继续推进后续授权工作。
4. 训练→最终候选审计冻结→固定开发/独立评测→保存回放画像→原统计/阅读层/候选卡→实际桌面/窄屏视觉→归档/记录/ALL或pending。已满足依赖的阶段并行，但独立结果不回流训练和选点。
5. 完成时给模型结论与任务结论，保留缺项/负结果。失败时先交付失败证据和已完成部分。只有身份无法确认、资源不足、实机不可达且需平台操作、硬失败/预算到限或范围需要扩大时，才报告具体阻塞。

## 必交件与当前规划验收

必交：c20及完整state/export/SHA；训练/恢复/尝试/资源总账；开发曲线；12288网格原结果与配对统计；父代与固定风格参照画像；JSON/HTML/完整Markdown候选卡；人类报告与Agent审计；1440桌面/390窄屏像素与交互回执；来源包及历史归档恢复索引；本记录、handoff、reports索引、ALL真实回报或pending。未跑、未读、不完整分别用NOT_RUN/UNKNOWN/INCOMPLETE。

机器合同：[execution-plan.json](../benchmarks/m79-prism-mainline.execution-plan.json)。离线审阅：[计划页](prism/m79-mainline-plan.packed.html)。**待用户决定的参数数量为0**。机器字段由Sol实测后绑定，不是再次请示项。

本聊天规划阶段只生成合同和交接文件，没有部署、模型forward或研究采样。输入权重SHA、数量/seed角色、政策绑定与计划打包验证记录在 `local-artifacts/prism/m79-mainline/plan-validation.json`。ALL读取fetch failed，规划登记待同步；不启动服务。执行任务转交后，Sol按本合同启动并完成本轮。

规划验收：`python -B local-artifacts/prism/m79-mainline/validate_plan.py` PASS，实际输入字节SHA、5120唯一训练任务、12288唯一评测任务（三模型4096/5120/3072）、角色seed互斥、现有benchmarks数字占用扫描、CPU/物理尝试/磁盘算术及链接检查通过。正式全局seed登记、远端运行身份和来源包仍由Sol在R3实测绑定；规划静态PASS不冒充运行预检PASS。HTML pack成功，8条中文句子的英文语法启发式警告为advisory；浏览器URL策略拒绝file协议预览，未绕过，计划页像素NOT_VERIFIED，非本规划交付的强制门。规划R0/R1设计与交接完成，R2–R8研究执行交给Sol；R9本地记录完成、ALL外部同步待办。


## 执行接单与机器绑定 r1

2026-10-12：用户在当前执行聊天明确派工执行M79，授权到有限训练、审计、独立评测、画像、报告、视觉及收口；不再等待启动确认。`task_kind=experiment`，`authorized_end=本合同R0–R9`，当前R2工程适配，尚未启动研究采样。禁止下一轮、发布/冠军/应用部署、Git提交推送、科学补赛或预算扩大。

实机只读探测：DSW为dsw-2230429-788c55f6c-s96gf、4核配额，持久盘剩约24.8GiB，低于训练角色46GiB预留；旧M75协调器PID48618保留，未清锁或终止。DSW2为dsw-2247412-66b9d46d95-nb9xv，实际CPU配额8核、内存28GiB，64核affinity不代表64核配额，持久NAS容量充足。server1控制机2核、盘约8GiB，仅承担小型恢复账本。证据node-*.json及runtime-*.json。

执行操作修订ROLE_RELOCATION_R1：将训练角色置于DSW2，4核affinity/torch2线程；后续阶段可在该节点串行进行，评测不超过8核实际配额。训练角色38GiB根目录/32GiB训练和独立8GiB磁盘预留随角色绑定，评测辅助角色12GiB保留为可用配额，全轮50GiB总额度、300000CPU秒和全部科学网格/门/期限不扩大。DSW不足的存储不靠删除历史解决。DSW2隔离环境splendor-m79-ppo-py312已核对torch2.6.0+cpu/numpy2.2.4/psutil7.0.0/Markdown3.7，原环境及M75源树不改；资格以实际68输入parity和R3绑定回执为准。

工程实现按独立M79蓝图、控制器、三模型评测、统计、审计、画像/归档及恢复分开。原始计划SHA与PPO不改。固定5120逻辑任务；基础设施额外物理尝试全轮最多64、每未完成身份最多1次，科学截断不进入终局训练且不补seed。13项蓝图/统计/恢复基础测试已实际通过，完整工程与Linux预检仍在进行，不以这些单测宣称R3通过。ALL最新读取fetch failed，revision UNKNOWN，执行登记待同步；不启动ALL服务。


## 实际启动与入口修订（2026-10-12 02:44 +08）

R2：本地与DSW2各40项集成测试通过；R3：68输入Rust/Python parity、724来源成员逐项SHA、确切父代/对手、真实配额/持久容量、全局已声明seed登记、持久启动与server1受限RPC全部通过，0工程研究局。独立r4源码包SHA `8b77e3df7683999f540b97c172d13564711cacf6184b933117b68be6578ebea2`；基础execution SHA `6dd124319e0e39586d97e3474cf7b8ae7849348b018232cf7c511612805c247a`。较早r1–r3工程部署未进入研究，保留以核验来源演变。

最初协调器PID18807于02:37:19启动；严格ownership nonce漏传使初始化后、首局前退出，耗3.904022 CPU秒。独立r5入口修订漏映射worker名称，首局前退出，耗0.151113 CPU秒；同一时刻另一个协调器被单writer锁拒绝，没有重复采样。r4原源码、两次失败回执及原日志完整保留。独立r6修订补nonce、worker入口和启动回执防重，零次尝试/更新的READY状态下核对模型、optimizer、RNG、progress四指纹完全一致；未改原数值核心，不重新初始化，不重置预算或截止。修订SHA `3803b476fbaef88d0feeccaaeaa1c515d2434f34a3d4ea7cac0823c0d7fb5b20`，适配器SHA `0bcfcb96e17efa7a93200a97c7e0cfd15727e8d5fdce84070ff6324894c3f98c`。全部入口启动计入原六次协调器重启上限；截至当前4条物理协调器启动回执，科学采样仅一次。

当前实际节点 `dsw-2247412-66b9d46d95-nb9xv`，持久根 `/mnt/workspace/splendor-m79-mainline-r4`；02:43:26协调器PID20370/create_time1791744206.11，命令为隔离环境Python执行 `scripts/prism_m79_revision_r6.py pipeline`，采样固定4核/Torch2线程。02:44核验首条进度5/5120终局、c1 COLLECTING、0截断/0infra abort/0更新，不能视作增强证据。首周期完成后校准含更新ETA；原有限截止保持2026-10-13 08:37:19 +08，训练18h和全轮30h不重置。

持久bootstrap及受限RPC已绑定r6；server1有限恢复服务实际PID1397143/active，Codex既有automation仍PAUSED，无新应用日程。DSW空闲辅助节点的旧M75自动启动已退休，原残留进程未被删除/强停；DSW2目前有研究工作，平台空闲计时UNKNOWN。计费/预算包含原失败和10000CPU秒保守工程准备预留。新对局和更新只按原合同推进。

当前任务R4 IN_PROGRESS；模型尚未冻结/竞技确认/发布/晋级/部署。下一已授权动作依次为完成训练、c20审计、固定开发曲线、12288独立尝试、描述画像与候选卡、证据/阅读报告、真实桌面及390窄屏像素、R9收口；不需再次确认。ALL不可达，`local-artifacts/prism/m79-mainline/all-execution-pending.json`保存真实绑定待同步。原M75全部科学结果保持。


## 用户要求停止持续监控（2026-10-12T03:01:41+08:00）

用户最新指令：“开始启动训练之后就停止监控 我要关机睡觉了”。训练已经实际启动，因此本次停止持续监控并结束本机会话，保留原有限研究授权和远端执行链。server1原监控PID1397143的argv与/proc启动ticks核验后，`prism-m79-recovery.service`已stop及disable；回读MainPID=0、ActiveState=inactive、UnitFileState=disabled。首次停止尝试因server1未装psutil在任何控制动作前失败，改用标准库完成，失败与成功回执均保留。未对训练进程执行停止或其他控制。

停止监控前最后一次真实研究快照为2026-10-12T02:58:19+08:00：DSW2节点`dsw-2247412-66b9d46d95-nb9xv`，协调PID20370/create_time1791744206.11，基础execution SHA `6dd124319e0e39586d97e3474cf7b8ae7849348b018232cf7c511612805c247a`、r6执行修订SHA `3803b476fbaef88d0feeccaaeaa1c515d2434f34a3d4ea7cac0823c0d7fb5b20`；R4 RUNNING，c1收集161/5120完整终局，0截断、0infra abort、0更新。该快照不刷新为后续实时心跳。首周期尚未结束，ETA未校准；原硬截止2026-10-13 08:37:19北京时间和CPU/资源护栏保留。

执行状态最后核验RUNNING；观测状态STOPPED_AT_USER_REQUEST；交付状态NOT_COMPLETE。远端持久协调器继续训练→审计/冻结→固定开发与独立评测→证据/阅读报告，运行不依赖本机；节点启动的一次性接续入口保留，但server1周期恢复检查与通知已停止，不能承诺中断后主动恢复或及时通知。本机画像/候选卡、实际像素视觉验收、完整历史归档和R9收口下次接续；未称本轮完成或模型增强。ALL仍不可达，更新pending记录，不另建观察器或定时任务。

证据：`local-artifacts/prism/m79-mainline/monitor-user-stop.json`、`monitor-user-stop-r1-failed.json`、`observation-latest.json`与`observations.jsonl`。


## DSW2平台自动关闭窗口适配（2026-10-12 03:15 +08）

用户在停止监控后补充：DSW2实例还有约6.5小时自动关闭。该平台期限由用户提供，本次未通过平台API核验精确时间；按约09:30北京时间记录，不再把原研究硬截止10-13 08:37当作机器可用时长。已部署09:00北京时间的一次性平台停点，预留约30分钟窗口；不是持续研究监控，server1服务回读仍MainPID0/inactive/disabled。没有修改平台关闭配置，也不自动开机。

独立操作适配`scripts/prism_m79_platform_guard.py` SHA `b65845e9449a0169509fb56607c0130661bf605f890aa76b9dafd3df442a99d4`，绑定原基础execution/r6修订、原预算全字段与用户平台窗口；未改运行中的r4/r6源码、训练核心、种子、候选规则或科学预算。DSW2实际一次性guard PID29666/create_time1791745999.95，状态ARMED_ONE_SHOT；当前持久协调PID20370保留，启动入口实测LIVE_STARTUP_OR_OWNER_KEEP，无新协调器/研究局。目录findmnt核验为/mnt/workspace上的nfs NAS，完整run模型、optimizer、RNG、cursor与已完成对局保存在该持久盘。

09:00触发后，训练阶段只在Run与物理账本锁可取得、没有未提交在途局时停止worker，保留完整已提交状态和原FAIL/CPU回执；最多等待10分钟。独立恢复入口仅在run commit、四类状态指纹、物理账本head、对应平台中断回执SHA全部一致且原截止/预算仍有效时归档该中断并接续r6，不清零资源、不重赛完成局。非训练阶段的中断保留为PLATFORM_INTERRUPTION_REQUIRES_RECONCILIATION，不冒充自动恢复已通过；无法取得安全边界会留下guard错误供接手核查。实际停点尚未发生，不能把ARMED写成已暂停或已恢复。

新增本地两项安全/漂移检查PASS、Linux三项检查PASS；Linux项实际启动并停止合成sleep进程，检验原完整CommitStore的model/optimizer/RNG/progress、cursor与尝试数保持，没有模型forward或研究局。原运行数据与预算不改。节点启动bootstrap与受限RPC绑定该独立适配，重新开机后可尝试精确接续；平台实例关闭时所有进程会停止，本机关闭不影响关机前远端执行。若开机晚于原研究截止或原训练18小时上限，则不自动延长，交付实际已完成部分。

证据：`local-artifacts/prism/m79-mainline/platform-stop-installation.json`、`platform-stop-live-owner-check.json`；远端`platform-stop/binding.json`、`armed.json`、`zero-game-validation.json`，后续`pause.json`保存真实触发结果。当前R4仍IN_PROGRESS，最终画像/视觉/历史归档/R9尚未完成，ALL继续待同步。


## 双节点开机、存储收口与恢复核查（2026-10-12T14:59:07+08:00）

用户本次明确要求查进度、同时利用已启动的DSW/DSW2、将已完成数据传至私有魔搭后清理，并说明两节点各有100G存储限制；后续补充当前实例剩7h40，按约今天22:30的平台窗口记录，精确平台关闭时间尚未API核验。前一晚停止持续监控仍保留，不擅自恢复server1轮询或Codex日程；本轮主动处理已获新授权。

实际DSW节点dsw-2230429-c69c6849c-z5m8b，初读105089261568总字节、78476673024已用、26595811328可用；当前可达且无历史研究进程。M73-r4约10.18GiB、M74约24.16GiB、M75约24.68GiB，占用主要来自未完成异地历史收口。DSW2新节点dsw-2248888-58c68c867f-7f4dt；NAS df返回共享1PiB容量，不能作为个人100G配额证据。本轮固定实际实例100G上限，工作目录与已有占用须单独核算。

M79没有当前活跃研究进程；旧实时文件停在04:40附近。独立读取最新已提交状态：run commit916e9cae489ab2cb436b33a258efd494d008597f3d46571ed7530eebae2ba95f，c2 COLLECTING，326物理尝试=325完整终局+第326局RUNNING，54更新、cursor0、未paused。完整model/optimizer/RNG/progress指纹已保存interrupted-state-r2.json；0截断/infra是最后旧进度快照，并非已核验第326局最终结论。旧09:00 guard无pause.json，不能称实际安全暂停。启动bootstrap曾KeyboardInterrupt，随后因verify先于新node登记报unqualified replacement node；普通恢复工程需独立修订，原r4/r6源字节保留。

旧外层relay最后实际CPU658.232571秒但无结束回执，原控制器会对未知中断时间保守预留至满额。已向用户提交有限计费修订：保留已测CPU并为未知区间另计10000CPU秒，继续原150000训练CPU/18小时（今天20:37）和全轮原截止；历史实际未知量仍UNKNOWN。该例外尚待明确答复，批准前不续训，不把新平台窗口当预算重置。

第一批已完成私有魔搭迁移：DSW已有完整原内容审计的M63/M70/M66三个ZIP，执行PID83173，逐原SHA核验→私有仓库上传→新鲜客户端全字节流取回SHA→删除原ZIP。completion状态PASS_ALL_THREE_ARCHIVES_PRIVATE_AND_CLEANED，约3.04GiB释放；已有模型、结果和旧完整性回执保留。必要源及M79完整状态正向DSW块盘迁移，额外存储占用计入实际磁盘；源节点启动入口已单独fence以免双派。所有进程、传输和清理以本轮JSON回执为准。

后续已授权工作：完成M73/M74/M75历史流式归档与核验后清理、保留必要模型/配置/结果/报告/恢复索引；准备DSW四核训练及DSW2八核固定base/style-reference评测，原网格/greedy/种子/候选不改。预算修订获批并且容量、状态/来源、恢复计数、parity检查通过才派局；缺c20的竞技结果不得制造。ALL本次context仍fetch failed，待同步，不启动服务。


## 2026-10-12 15:46 接续修订与真实首条辅助进度

用户已明确批准历史CPU计费例外：已测658.232571秒保留，未知区间额外10000CPU秒，历史实际未知量仍UNKNOWN；原150000训练CPU、18小时/20:37训练截止、全轮10-13 08:37截止与种子/候选规则不改。授权写入budget-authorization-r7.json。

DSW冻结源已核验，23331个状态成员/1028748552字节逐SHA迁移PASS；原NAS启动入口fence防双派。检查点唯一环境差异为内核platform字符串，其他device、线程、Python/Torch/NumPy、dtype/AMP/TF32等字段相同；独立r7适配保存原checkpoint identity，实机68输入parity PASS，完整model/optimizer/RNG/progress、run commit、54更新、326尝试与cursor0完全一致。没有重新warm-start。当前DSW仍等待历史清理后原46GiB预留，不在容量不合格时派局。

DSW2实际工作区apparent bytes52928878528，已按用户100000000000字节配额核算，辅助根12GiB+另留8GiB仍合格；NAS共享1PiB df容量不用作个人资格。独立双节点适配fbe03b6c…准备原网格base4096/style-reference3072共7168局，CPU预留40000、aux infra重试0，控制端后续只派a的5120及统一恢复缺项，避免两节点双派，120000开发/评测与300000全轮CPU不扩。

辅助首次零局入口缺PYTHONPATH已在独立启动env修正；随后两个writer共用aux-status.tmp碰撞，保留72个真实终局和50.371589 CPU秒，独立aux-r2适配d971e2ad…分开worker/guard进度文件，仅继续未派分片，已完成不重赛。实际新启动DSW2 dsw-2248888-58c68c867f-7f4dt，协调PID25367/create1791790932.76、relay25368；最新独立读取512个完成终局、8worker实际在跑、无新错误，前次失败/72局/消费保留。原未完成八片待控制端SHA导入后统一处理；不得把缺项默默跳过称7168完成。辅助运行使用22:00平台操作停止上限，原科学截止不重置。

DSW大根归档PID92443，实际小包SDK私有上传→新鲜完整SHA读回→源清理贯通PASS，已开始M75；当前24片/3221225472字节上传，整包尚未完成/未删源。归档早期--keep漏传及平台ssh/gpg agent不可dump检查故障发生在历史处理前，保留失败，独立修订仅放行实测精确平台key-agent argv，其他不可检查进程继续拒绝。归档不在有限盘生成第二全包；所有清理必须等全分片/整包/manifest新鲜读回通过，保留模型/配置/结果/报告及成员恢复索引。DSW2已结束的M75评测和M79-r1/r2/r3工程快照另起有限清理PID24965，当前还在归档，未称删除完成。

证据均在local-artifacts/prism/m79-mainline：r7-qualification-launch.json、r7-platform-qualification-launch.json、aux-evaluation-launch-r2.json、aux-progress-r2-launch.json、aux-evaluation-live.json、dsw2-full-workspace-usage.json、history-cleanup-r4-launch.json、dsw2-completed-cleanup-launch.json。11项本地定向检查PASS、8项DSW Linux适配测试PASS、3项历史归档Linux测试及真实小型SDK闭环PASS；这些不代表候选c20/竞技门完成。ALL继续待同步，server1持续监控未恢复，无新应用日程。


## 2026-10-12 16:32 历史 M74/M73 直接清理修订

用户指出 M74 约25GB、M73 约11GB仍占DSW空间，要求先传私有魔搭再删除。两者均为已结束实验，不参与M79当前训练；之前没有完成异地核验后的清理，串行等待M75的安排已改为两项直接执行。M73 PID112743/create1791793245.0，M74首次PID112742在归档前遇到/proc进程退出竞态，历史字节未删；独立r5仅容忍已退出的进程条目，其他活跃/不可检查进程规则不变，Linux五项定向检查PASS、0研究局。M74新PID115930/create1791793932.63，独立归档源SHA f9e6afef8a5e3a054ba7ad22e6f6f53a7ff1022efef1bab1efcad2430dce6d0b，原4小时操作截止不重置。

两个任务均直接流式上传到私有dataset sparxie1/test1005，不在有限盘生成第二完整包；完成全部分片、整包SHA与manifest新鲜读回后自行删除原历史大数据，并保留必要模型、配置、结果、报告。M74前缀splendor/history/splendor-m74-scaleup-r1/20261012/96c2a048ab944771a938c7e1bbbaa7f5，M73前缀splendor/history/splendor-m73-repeat-r4/20261012/dc92f591d10e4357a1520290b0c9aceb；此刻还未完成核验删除。原M75失败时已上传87片/11676942336字节，独立恢复PID110325复用原冻结成员索引并逐字节匹配既有片，保留失败与维护CPU费用，不覆盖云端旧片。证据m74-m73-direct-cleanup-launch.json、m74-cleanup-r2-launch.json和远端engineering-tests-r5.json；完成以各receipt.json cleanup PASS及实际磁盘为准。


## 2026-10-12 17:41 历史清理实际回执与训练恢复更正

M73 与 M75 的 DSW 完整历史已私有归档、核验并完成原大数据清理，分别删除原文件字节9097143788、24411989944；清理后目录实测allocated为213110784、230010880字节，只保留必要模型、配置、结果和报告。完整归档SHA、分片、manifest新鲜读回与保留清单保存m73-m75-archive-cleanup-completion.json及逐根receipt；恢复索引已追加docs/prism/history-archive-index.md。M74首次归档和读取过程遇到Linux退出中的child已释放mm但State仍R，独立r6加入/proc/stat resident页的真实测量；不以缺字段猜0。随后发现多同级目录使逐次prepend的generator链累积，独立r7改为共享一个库存游标；Linux七项定向检查（含1100同级目录）PASS。本机五项PASS、两项Linux限定跳过。M73/M75的已验证清理使用独立r7续作，每个原文件在unlink前仍逐SHA及身份检查，不重新打包、无新研究局；原失败、CPU保守计入和原墙钟均保留。M74独立r7 PID129595复用84个已上传、逐字节相同分片，目前97片/约12.90GB已全部上传，整包新鲜核验与清理仍待完成。

容量通过后首次DSW协调器PID130223于17:17启动，但训练未真正接续：在旧attempt326已发布终局、未发布completion的保护门停止，5.104135训练CPU完整保留。这一更正取代将协调器启动理解为持续采样的表述。实际原relay48636有FINISHED/returncode0/无stop_reason回执，且原report、replay、sidecar完整；独立migration-r8/repair_published_attempt326.py（SHA3c596f9b5ff221ae9aa5ede8bb4a9eaf54882d4125ed047fc4005b1bdd951814）以冻结Rust二进制审计既有数据，按原job/behavior/snapshot/argv/真实resources发布completion并仅消费原局一次。完成包SHA874f48b6baad315c4f7c82ecc444691070cd64440a84f22eff6ccfd2a65f894f；模型、optimizer、RNG指纹全部保持，仍326物理尝试/54更新/cursor0，完整终局325→326，0新采样、0重赛。原单局原config字节、终局、失败账本commit、停止回执和CPU均保留；只清除该明确恢复故障的paused/ledger failed状态，未清除其他科学失败。

修复后实际DSW协调器PID161860/create1791797180.35，relay162133；节点dsw-2230429-c69c6849c-z5m8b，基础execution6dd124319e0e39586d97e3474cf7b8ae7849348b018232cf7c511612805c247a，r7修订SHA03beba546c1fb0cb14a445eb9fcdb2d46157e3ee1e5d9f4ed2d42dd7323e2ec5。17:27:46首次真实接续核验：369/5120终局、c2/54更新、0截断/infra；后43局确实新采样。匹配DSW块盘短窗约2秒/局，剩余采样粗估2.6h，不含后续更新/审计，完整训练ETA待周期时钟，原20:37训练停止不变。持续研究监控仍按用户要求关闭；本轮清理观察不恢复server1服务或Codex日程。

DSW2辅助结果6728终局已结束，原八片部分账本和440局缺项保留，累计2313.151749 CPU秒（含前次50.371589），未称7168网格已全。results.zip 74683767字节/SHAa51e8334b5e118dd78cac2a877459952ddf5fffd990dcd7e2dc96ad6d7612aec，私有路径splendor/m79/dual-dispatch-r1/aux-r2-output；完整新鲜取回核验PASS。控制侧原SDK在Torch环境缺包的零动作错误保留；独立下载入口使用已有SDK的系统Python、导入仍使用原合格Torch环境。17:23:13原ZIP/成员/语义身份导入PASS，原aux配置和结果字节留存，仅控制侧文件路径适配；后续缺项由统一控制权恢复，CPU只记一次。DSW2旧M75清理曾在递归迭代故障后留下已完整备份的部分quarantine；独立修订PID103706按原20:40墙钟继续，先核验全部保留项和每个剩余原文件身份/SHA后删除，再处理r1/r2/r3已结束工程快照。该历史维护旧末CPU仍UNKNOWN、保守上界10000，续作另限2000CPU；与M79科学预算分栏、不重置科学预算。

R4与本轮全链交付仍IN_PROGRESS，c20/竞技门/画像/视觉/R9未完成；这些归档和恢复PASS不表示增强或晋级。ALL不可达待同步。证据包括verified-cleanup-r7-launch.json、m73-m75-archive-cleanup-completion.json、attempt326-repair-result.txt、dsw-training-restored-first-progress.json、dsw2-cleanup-r7-recovery-launch.json及远端原资源/修订回执。


## 2026-10-12T18:04:52.608881+08:00 M74/M73 历史存储任务完成

用户要求的两项大目录已完成“私有上传→全部分片与整包SHA/清单新鲜读取验证→原大数据删除”，M74/M73 `cleanup=PASS_SOURCE_CLEANED_WITH_KEEP_FILES`。再次逐个保留文件SHA和云端全部分片/manifest身份检查PASS，quarantine全部消失；M74实测229347328字节、M73实测213110784字节，两项allocated释放 36426674176字节（36.427GB）。必要模型、配置、结果、报告与唯一有效恢复索引保留；M75同类历史也已完成，三项allocated共释放 62691217408字节。副本索引另释放507321960字节。DSW验收磁盘已用17.867GB/空闲81.217GiB；训练新数据增长独立于这次历史清理。

本次历史存储授权终点已达到；本轮M79研究仍按既有有限链继续，最新研究实际核验仍是17:27:46的369局/PID161860，未把存储验收时间刷新成训练心跳。server1持续监控和Codex日程维持关闭；独立评测、画像、报告像素验收与M79 R9尚未完成，未发布/部署/提交push。ALL待同步，归档索引与完整回执已本地保存。DSW2已结束工程快照的独立维护入口继续按原20:40墙钟执行，以自己的回执为准，不用DSW完成回执代替DSW2完成证据。


### 2026-10-12 18:56：实际ETA与训练截止冲突

2026-10-12T18:56:32+08:00 M79应用户请求单次ETA核验：DSW节点dsw-2230429-c69c6849c-z5m8b，PID161860/create1791797180.35身份一致，TRAIN/RUNNING；1648/5120终局、c7、334更新、0截断/infra。18:15至18:56实际491局/41.266分钟=11.898局/分钟（含该窗更新与开销），剩3472局按此速率需4.863小时，完整训练外推23:48，后续周期仍可能更慢。原硬训练截止20:37:19保持，按当前速率不能交付完整c20；全轮ETA因此尚不可承诺。未延长预算/截止、未重启或恢复持续监控；证据local-artifacts/prism/m79-mainline/user-requested-eta-latest.json，ALL待同步。此前17:27短窗约2秒/局只含采样的粗估已被本次含更新实测取代。


### 2026-10-12 19:17：授权延长训练截止并实际切换到 r11

2026-10-12T19:17:24.827126+08:00 M79训练截止修订已实际启用：用户明确授权仅训练延长至2026-10-13 01:00北京时间；原150000训练CPU/120000评测开发CPU/30000控制审计CPU/300000全轮CPU、所有种子、5120训练逻辑局和固定c20不变，全轮原10-13 08:37:19截止不变。DSW节点dsw-2230429-c69c6849c-z5m8b，新协调PID267499/create1791803554.8，relay267517、worker267518；实测TRAIN/RUNNING，1839/5120、c8、390更新、0截断/infra。独立r11源码d803ac17…、修订88dba950…同时覆盖控制器、relay和Run准入截止，已读实际relay --wall20840.50秒并核验worker-deadline.json指向01:00。原c7 COMMITTED边界1792局/390更新、模型/optimizer/RNG/进度/物理账本全指纹不变；0重赛、旧7489.508744CPU保留，原训练累计已记18156.900585CPU，当前relay另计实时CPU。4项Linux零局测试PASS；c7缺写出的摘要/32tensor导出已由原commit精确恢复，原计时NOT_MEASURED，独立19.672344控制CPU回执待最终预算合并。DSW2 SSH连接拒绝、server1 :2223无监听，仅证明当前通道不可达；已导回6728局继续复用，剩余440 base-heuristic及5120候选独立局与1024开发局由DSW原链接续，DSW2可达后再核验分工。未重新启用持续监控；ALL context fetch failed，待同步。新证据deadline-r11-final-active-receipt.json/source.zip，完整轮次仍IN_PROGRESS，后续审计/独立/画像/报告/实际视觉与归档R9尚未交付。

本修订覆盖历史64800秒/20:37训练墙钟限制，不覆盖全轮截止。原冻结计划、run config、round-budget、r4/r6/r7源码保持原SHA。r9初次入口把relay argv误认成第二writer，首个信号前拒绝；r10 state-open遇到正常writer锁，有限只读重试仍未切换；独立r11用不持锁Run对象在SIGSTOP保护的非阻塞事务内读取最新HEAD，busy时保证SIGCONT，最终在c7完整提交边界成功。前两版来源、验证、错误输出全部保留；没有清锁或把该工程拒绝计为新增科学对局。第7条协调器启动仍在原六次重启上限内。

c7展示产物由handoff原commit `dbb56e22127a4f620227d5b9611106eb7b741c0f5b5dfb3f7fcb65dc27d7c148` 和原ledger commit恢复；weights SHA `0bf68f3ea8765bb5daf9001fd22c66e68579c9799f39845bb4e15f1a54b01223`，全32policy tensor逐一torch.equal；恢复不触碰运行HEAD、optimizer、RNG或消费游标。其19.672344CPU为独立控制回执，收口时须恰好计入一次原控制预算，不能遗失或加到训练/评测类别。

执行边界仍为本轮R0–R9；固定c20审计通过后自动接续开发曲线、原固定独立网格和报告。路线undetermined不阻塞；不发布/默认替换/部署/commit/push。当前DSW2平台运行状态UNKNOWN，SSH不可达不写关机；旧已完成辅助结果与负证据保留。已读取all-workspace且CLI读取不可达；没有启动ALL服务。


### 2026-10-12 20:18：DSW2新节点恢复、固定开发分工与空闲边界

2026-10-12T20:18:03.908053+08:00 DSW2用户手动恢复后实测新节点dsw-2250045-576f576d9c-rmtk4、8核/28GiB；恢复时无研究进程。用户再次确认空闲约1h会inactive注销，需要手动开机并重跑连接脚本；SSH连接拒绝只记通道不可达，平台注销原因需区分用户说明与平台API实测。本次用户新报7h50自动关闭（约10-13 03:54北京，非平台API核验），新辅助操作停点03:30，原M79训练01:00/全轮08:37和CPU不变。已实际派DSW2固定c5开发256逻辑局，PID3829完成255终局+1科学截断，原截断不补赛，原权重d37a9b95…；87.001791CPU与所有SHA证据导回DSW并从后续curve复用（0重赛），总外部评测CPU2400.153540。结果已私有魔搭sparxie1/test1005/splendor/m79/aux-development-r12/c5-0087176bcdec95c1完整fresh readback PASS。server1有限依赖入口PID1681017/create1791807338.04，目录/home/ubuntu/.local/state/splendor-m79-development-r16，等待真实c10/c15导出后各派固定256局并SHA导回；3项零局handoff测试PASS。DSW2现PID11532实际个人100GB全工作区容量盘点进行中，后续采样须实测20GiB余量（12GiB辅助角色+8GiB预留），共享NAS df不作个人容量。原6728辅助评测回放Rust离线审计PASS（6.036531控制CPU）已SHA导回DSW，R7完整画像尚未完成。DSW PID267499持续PPO，当前2380/5120/c10/498更新，0截断/infra。没有恢复持续研究监控或ALL自动同步；本机关闭后server1有限交付依赖能继续，但平台空闲注销/开机和SSH重连仍需人工，不把WAITING说成研究负载。ALL待同步。

当前派工范围为既有1024开发逻辑局中的c5/c10/c15各256，不新增研究样本、候选或反馈选择；c20开发仍由主链执行。主链curve遇到已导回FINISHED账本直接读取，不重赛；导入前预留每批4000CPU到原120000 evaluation_development内，导入后用真实relay累计CPU替换预留。原对手/seed/换座/模式与512ply不变。本次开发c5已出现1个科学截断，作为原开发最多8个截断预算消费保存，不能写256个有效终局。

可恢复执行源码：aux_development_r12（c5实际）、development_handoff_r16（server1有限输入/交付依赖）、aux_development_r16（c10/c15，未派局）、aux_saved_replay_audit_r15（6728已保存回放，无新局）。原r13/r15交付工程拒绝和r14缺analysis目录错误输出保留；DSW2新节点未授权server1现有公钥，修复为现有公钥带restrict项（禁转发/PTY，无私钥迁移），两端直接hostname实测PASS。c5 relay真实采样约179s完成，但外层全历史NAS递归容量扫描令最终回执延后到约761s；没有杀采样或重赛。c10/c15独立适配仅扫描本次4片，维持每片128MiB和合计512MiB上限；个人100GB完整盘点另做并作为前置门。

6728回放审计独立控制消费6.036531CPU为已保存原始回执，须与此前c7恢复19.672344CPU、容量盘点及server1交付控制成本在R9合并且恰好计费一次；当前仍PENDING_CONTROL_RECONCILIATION，不把工程递归目录等待算训练推进。已导入审计不是完成画像/路线确认，也不替代R6全候选网格。

空闲处理事实：DSW2 c5及离线审计已结束，目前容量盘点是实质工程工作，c10/c15为等待输入；检查点之间可能没有可执行研究负载。不得为避回收添加空转；输入等待本身不代表实例保持活跃。用户原停止持续监控指令仍保留，当前没有另开Codex心跳或server1研究轮询服务，有限交付依赖不是平台自动开机能力。若辅助节点后续不可达，保留真实WAITING/失联回执与已导入结果，主链按既有来源和原CPU预算完成尚未开始的开发网格；不能同时重派仍由辅助持有的在途片。


同次20:18核验的ETA补充：19:55至20:18，2199→2380（181局/22.783分钟，7.944局/分钟）；余2740局按此窗实测速率需5.748小时，完整训练外推2026-10-13T02:02:56.086037+08:00，已经晚于用户指定01:00。此为预算/墙钟风险而非训练已失败；未擅自延长截止，继续原有限训练与真实账本。证据aux-restored-training-eta.json。


### 2026-10-12 22:04：第二次DSW2失联与等待链缺口

2026-10-12T22:04:59.564138+08:00 DSW2第二次连接丢失更正：实际证据来自可达server1的保存派工日志，不是进入掉线DSW2内部。server1有限派工PID1681017在2026-10-12T21:37:06.720075+08:00首次记录2223 connection refused并退出；原等待代码先等待aux-capacity-r16.json，未获最终回执时持续返回False，没有检查容量进程已退出/超时；c10/c15无launch或import，未实际派局，c5已导回255终局+1截断不受影响。用户指出1h空闲会inactive且需手动开机/重连；本次平台内部注销原因未核验，不能以SSH失联冒充平台原因确认。未及时处理等待链/提醒是本轮执行缺口。DSW实际PPO仍RUNNING/PID267499，3140/5120/c13/662更新，0截断/infra；原01:00训练截止不变。本地独立r17容量预检及有限admission已实现：180s超时始终落终止回执，容量不足/死PID/创建时间漂移/缺最终回执立即拒绝，不无期限WAIT；4项零局单测PASS。本地修复未部署，DSW2不可达阻塞部署与辅助接续，未新开机、重连或重赛；主链按原控制器继续。证据second-dsw2-drop-dsw.json/server1.json/dsw2.json，ALL待同步。

源码：scripts/prism_m79_aux_capacity_r17.py、scripts/prism_m79_development_handoff_r17.py；本次仅离线实现/测试和已可达节点日志核验。容量盘点到底如何结束与平台inactive原因保持UNKNOWN，恢复后须读取原qualification log/receipt及实际节点身份，不能现在写PASS。新入口尚未运行，不把代码实现称已恢复派工。


### 2026-10-12 23:13：容量检查修复部署、c10实际开跑与有限通知重授权

2026-10-12T23:13:43.345655+08:00 DSW2第三次人工开机/连接后已实际派c10：新节点dsw-2250427-5644479557-dcxzm，8核/28GiB，c10协调PID26380/create1791817971.04、relay26400、4worker PID26433–26436，首条真实完成114/256局；ZERO_GAME_PREFLIGHT PASS，原c10权重/固定开发seed/greedy/换座/512ply不变。c15在2026-10-12T23:11:40.456496+08:00尚无导出，不能冒称已派；server1独立r20入口PID1734268/create1791817937.22在c10结果SHA导回后等待实际c15导出并自动派原256局，操作截止03:30不变。旧r16全NAS du1200s失败日志已取得；r18分目录180s还剩3个高文件数目录超时，FAIL回执保留；r19对余下268860个成员64线程lstat读取19.68s，结合已实测41个根和SHA验证的delete-only归档隔离目录清单上界，完整工作区保守上界54242852656B，100GB内余45757147344B，>=20GiB预留PASS。未用NAS1PiB df冒充个人100GB，也未清无关项目。r19派工曾因系统Python被verify拒绝，0新局；r20独立修订改两节点为已绑定Python3.12/Torch2.6，保留原来源/失败，不改冻结核心。7项本地零局handoff/capacity测试PASS。DSW PPO持续运行未停，最新2026-10-12T23:11:40.456496+08:003556/5120/c14/718更新、0截断/infra、PID267499。原训练CPU150000/评测开发CPU120000/全轮300000/种子/固定c20/01:00训练/08:37全轮截止不变。按用户本次明确授权重新启用仅M79有限5分钟空闲/派工失败提醒（Codex heartbeat automationId=m79，ACTIVE），发现等待/30min/45min/掉线/失败报告；提醒依赖Codex应用运行，没有自动开机或空转保活。ALL待同步。

当前可恢复来源：scripts/prism_m79_aux_development_r19.py（c10/c15 worker）、scripts/prism_m79_development_handoff_r20.py（server1有限交付入口）；r17预检超时/死亡准入保护已在本地测试，现场采用r18/r19分目录+并行元数据的独立工程修订，未覆盖旧来源。所有容量记录明确实际测量与冻结清单上界，不将保守上界冒充逐文件全量现测。预检失败即STOPPED_RETAINED_EVIDENCE且本任务通知；c15等待输入本身不构成有效负载，提醒不能阻止平台idle注销。

自动提醒根据本次用户“没有活或派工失败就及时告诉我”重新授权，范围仅此有限M79，截止08:37或任务完成后收口。已有M75自动化保持原状态，没有恢复旧server1研究watchdog。派工仍不是晋级或已完成独立确认；c10只作预注册描述开发曲线，完成结果先SHA导回，c5既有255终局+1截断继续复用，不重赛。容量盘点及入口拒绝的工程控制成本须保留记录在R9一次性合并，不清零原CPU历史。

### 2026-10-13 completion-r21：按原有限工作量恢复至完成

- `task_kind=experiment/recovery`；用户授权：“为什么要设置截止时间啊？继续给我跑完”，随后确认两台已连接并要求“继续”。`authorized_end` 为本轮训练、固定c20、原开发/独立网格、画像、报告与R9。不扩展下一轮、发布、部署或Git提交。
- 原01:00停止的直接原因已核验为 `wall_deadline`，不是科学失败或CPU耗尽。原墙钟设计把停机/恢复等待纳入可用窗口，造成未完成即停止；本修订取消过期日历准入，以剩余工作量及原累计资源额度为界。单局90秒和CPU派生的活动阶段看门狗保留，后者不计停机历史，不能再拿旧01:00/08:37判断当前DEADLINE。
- DSW最新副本 `/mnt/workspace/splendor-m79-mainline-r4` 保留4124局、c17、886更新；DSW2同名旧副本仅325局，禁止从旧副本恢复。新节点 `dsw-2230429-56d5b9bc65-vcl75` 的原Python3.12.15/Torch2.6、68输入parity、来源/输入SHA和容量检查通过。原执行SHA `6dd124319e0e39586d97e3474cf7b8ae7849348b018232cf7c511612805c247a`。
- 精确run commit `086227e12e053922470c0a9a6a9c2a1a921be936a327bd2153980dc3ead2d70d`、物理ledger commit `d4814670278ff9b2e98a6aa3d9f859e35049df785b87d49016c47a95d0f39643`，模型/optimizer/RNG/progress四指纹保存；全部4124局COMPLETE，无未归账局。原FAIL回执归档到独立revision；原source、合同、round-budget和累计资源不改。
- 恢复前累计CPU：训练40931.247062、开发/独立外部2573.017483、控制审计10053.403794秒。训练剩109068.752938秒；原150000/120000/30000、全轮300000保持。旧未测量保守收费也保留；其他历史工程消费仍按既有R9清单一次性合并，不把未知成本写零。
- 独立入口 `scripts/prism_m79_completion_r21.py` SHA `9506542c85da1fe407dbc3520f4983c8c6a1f974ae81df36663ba3a2fb04a596`，同时覆盖controller、PPO准入、评测prepare/单局准入及子分片入口，保留冻结科学代码。7项零局适配检查PASS。13:08:37协调PID14312/create1791868117.31、relay14330、worker14331实际启动；13:14:06读取4153/5120、c17/886更新、0截断/infra，真实argv含r21，relay剩余CPU绑定正确。
- 自动阶段链：train→audit→candidates→curve→evaluate→report。已有独立6728终局、开发c5=255终局+1截断、c10/c15各256终局复用；8个base-heuristic分片留下的未发布DISPATCHED尝试由原有限infra恢复政策处理，不能把已完成终局重赛。最终候选仍固定c20。
- 提前发现4个c5接收manifest使用Python3.12.13/psutil7.2.2而当前绑定3.12.15/7.0.0；独立 `scripts/prism_m79_c5_intake_r21.py` 核验原压缩包SHA、冻结来源/配置/政策/资产、256局证据hash、逐局进程与结果后，只重建派生接收manifest/ledger绑定。旧接收元数据、原辅助执行manifest和游戏字节保留。回执 `PASS_C5_INTAKE_REVALIDATED`：255终局+1截断、0新局。此为接收再验证，不冒充旧对局在新环境重跑。
- 观测：M79原heartbeat已更新为每15分钟跟进至本有限轮R9完成，移除旧UNTIL；正常进展安静，失败/完成/失联/必要行动通知。它依赖Codex应用运行；主训练与后续阶段在DSW独立进程，不依赖本地聊天持续打开。未重启旧server1恢复服务；新节点/中断须按当前源码、完整状态、实际CPU和失败证据核验，不能盲调旧ensure。r21 ensure只有一次新增启动，二次失败恢复须另立执行修订，日历截止不复活。
- DSW2当前无分配任务，13:09已告知空闲，不用空转保活；不能把c20训练拆成两个并行写入者。未使用其NAS全局df冒充用户100GB额度。DSW当前空闲约66GiB且覆盖剩余角色容量预留。
- 本地证据目录 `local-artifacts/prism/m79-mainline/completion-r21/`：时间戳readback、SHA核验12个回执、部署零局检查、原始恢复指纹与资源。完整模型竞技结论仍未评测完成；R4 IN_PROGRESS，R5–R9待主链与跟进完成。
- ETA：恢复后约5局/分钟，仅c17采集短窗；结合上一轮末段约5.2局/分钟且后续更新/审计仍需时间，训练暂估北京时间16:30–17:30，整轮暂估18:00–20:30。此为工作估计而非自动停止时刻，后续按完整周期实测更新。
- ALL `context splendor` 返回 `fetch failed`，待同步，不启动ALL服务。下一允许动作：自动推进本轮；失败时做精确诊断/有限执行修复，取回SHA核验、真实视觉验收与R9，不再询问是否开始。

### 2026-10-13 aux-finish-r22–r24：DSW2接续原440局（本节由当前执行聊天更新）

DSW2已重新分配不依赖c20的8个base-heuristic分片，原72终局保留、剩440逻辑局。入口目录为`/mnt/workspace/splendor-m79-aux-r1/execution-revisions/aux-finish-r22/`，不要再用DSW2旧mainline325局或旧r20状态判断它空闲。主DSW在TRAIN继续，资源已预留4000活动CPU+240原中断保守收费，原8个恢复key已登记主infra账本防重复派局。新容量70.83秒扫描450692成员，保守占用54,524,386,663字节，个人100GB内预留2GiB通过。

r22第一次入口因非阻塞共享retry锁并发冲突失败：原72终局不变；唯一进入监督器的尝试由原relay在`Popen`前报`launch parent died`拒绝，证明没有新增Rust游戏；6.48301CPU保留。r23串行准入后原bounded.inspect暴露旧resume把30CPU中断收费混入终局总和的问题，零新局预检拒绝。r24将每片30CPU保留在主共享外部收费（共240），shard consumed仅为逐局原process-result之和，旧ledger及错误均保留；不增加逻辑局或科学重试，仍只有原8个基础设施恢复key。当前执行脚本`prism_m79_aux_finish_r24.py`正在启动/核验；读取r24-launch.json、status.json、progress.json、resource.json最新证据，不假定启动成功。

完成后由本聊天SHA导回并运行`prism_m79_aux_import_r22.py`，完整归并前保留主节点8个未完成shard，不能主节点再重赛。辅助旧失败、接收原件、主旧72局均独立保存；自动跟进发现本节时先核对该辅助任务，避免错误提醒“无分配任务”。

**本段最终执行结果：** 2026-10-13T14:03:42.477898+08:00 DSW2原440局已跑完并SHA导入：原8个base-heuristic分片从72终局接到512终局，零截断，旧72局逐项相同、零终局重赛。原独立父代+风格参照网格现7168/7168终局、112分片FINISHED；剩5120候选独立局等c20。DSW主训练14:04实测4404/5120/c18/942更新，PID14312身份一致，0截断/infra，继续原r21自动流程。辅助13:58:17实际r24 PID23126启动，14:01游戏完成、14:02打包退出、14:03:42归并PASS；辅助新逻辑局440。实测辅助累计192.612160CPU（成功监督186.129150+首次入口失败6.483010）和原8中断240CPU保守收费均保留，共享外部CPU更新3005.629643，未清零历史。包SHA73bdf1f6a55c643e004772f1dfaaccddc950606e6bf000404d6ddbe1aa85a0b6；新8个恢复key在主总账标CONSUMED，不新增科学重试。DSW2当前这批工作已完成、无依赖c20之前的剩余原评测；空闲重新从14:02计，不沿用13点旧35分钟计时，不空转保活。ALL仍fetch failed待同步；完整M79仍IN_PROGRESS。证据local-artifacts/prism/m79-mainline/aux-finish-r22/import.json，轮次docs/m79-prism-mainline.md末节。

归并修订只变更派生接收配置/命令路径/manifest与ledger绑定，辅助原ZIP和主旧8片留在独立revision。新的8片经冻结配置、逐局证据、结果和CPU校验；主旧72终局row逐项相同。已完成数据由主r21后续dispatcher自动识别FINISHED跳过，原12,288独立网格、固定c20和科学门不变。入口并发失败与r23账本预检失败完整保留，没有以工具退出为由重置训练、预算或对局。

### 2026-10-13 c20 已完成与审计 inventory 接续修订

本次用户要求 c20 出来直接审计/评测。实测训练完成回执 PASS：5120 完整终局、0 截断/infra、c20 COMMITTED、1108 更新；精确导出 SHA `ecb5d3a3e371c743f81bccdea48afbe2e4c3bf2a40d41121817895a20d60a17b`。训练 relay 最终消费13722.761267 CPU秒，加历史总训练54654.008329秒，未重训。

现场审计失败日志 audit-16.log 表明原 auditor 要求完整 checkpoint 只有32 policy张量，实际 PPOModel 还保存4个训练用 style_head 参数；导出仍是32个策略参数。本次先读取完整状态与导出 inventory，确认32 policy键和精确4 style_head键，独立r27/r28只适配该 inventory 判断，原逐策略张量 torch.equal、optimizer32槽、行为/回放/parity及统计检查保留，原源/权重/失败不修改。r27初次入口被旧r24 SELF身份拒绝、0新局，失败按1CPU秒保守记账；r28保留旧身份验证同时路由新入口，单次启动PID122356/create1791888519.21，真实DSW节点dsw-2230429-56d5b9bc65-vcl75。r28源码SHA `da388f387bf7ff06b055b2ceeb996f8ebd19539db5b8f9f9667a2438e7d5b3ce`。本地原审计10项测试实际PASS；新审计是否通过以新实际回执为准。

授权阶段链仍 audit→candidates→curve→evaluate→report；主训练PASS自动跳过。已完成7168父代/风格终局及c5/c10/c15开发复用，固定c20候选5120独立局尚待审计通过，未宣称已经开赛或整轮完成。ALL仍待同步，报告/画像/视觉/R9尚未交付。

后续接续更正：r28遇到既有失败 audits/a 目录的 FileExistsError，实际2.945438CPU已由主账本计费；r29把该失败目录完整移入 execution-revisions/completion-r29/retained-failed-audit 后独立重开审计输出，不删除失败或改训练。实际r29 PID122839/create1791888614.3，SHA3f288dabbcc6a9100b3bfab6b66496612981e8f4716b6c88c7a942159d83f932。当前审计工作进行中，后续PASS/开赛须读取实际回执。


### 2026-10-13 completion-r30：恢复历史进程回执并接续审计

R29第326次尝试已通过completion/回放核验，失败发生在对process-result.json求SHA时。全5120个已完成目录仅326缺失该文件。原始relay `campaigns/a/control/relay/2bbf98659e9040ab94b32546c8f251d9.json`仍在，且SHA与`migration-r8/attempt326-recovery-receipt.json`绑定一致，其原始资源字典与completion.resources完全相同（PID48636，FINISHED/returncode0/stop_reason null）。r30恢复原relay精确字节，不合成新资源、不把恢复时间写成原执行时间；记录原relay/恢复回执/completion/权重及两个HEAD SHA，恢复前后不变。原audits/a完整移入独立revision，原审计FAIL及553.259871 CPU仍保留，恢复脚本实测CPU计入原控制预算。

独立入口只继承r29已有32policy+4style_head适配，所有原审计门保持；6项证据校验覆盖正常恢复、PID/返回码/运行状态/停止原因不匹配和字节SHA漂移拒绝。已实际启动并读回AUDIT/RUNNING，但不宣称审计通过。完成后主链自动走原c20开发、独立网格及报告；固定c20 SHA ecb5d3a3e371c743f81bccdea48afbe2e4c3bf2a40d41121817895a20d60a17b不变。

监控处置缺口：Luna已识别失败但此前仅写parent-audit-escalation文件，未形成实际修复接续；其直接给祖先线程发消息被工具拒绝（见luna-monitor/escalation-review.json）。后续例行执行故障由Luna在现有授权内直接诊断修复，不以写升级文件代替工作；确实缺外部证据或权限时才明确要求必要操作。当前r30由父代理启动，Luna须先读实际进程/回执避免并发恢复。ALL仍待同步。

### 2026-10-14 completion-r37：画像、归档、报告与视觉R9收口

- r30于2026-10-13 22:22:30结束主流水线，当前无M79进程；执行来源SHA `6dd124319e0e39586d97e3474cf7b8ae7849348b018232cf7c511612805c247a`。训练5120/5120、固定c20 SHA `ecb5d3a3e371c743f81bccdea48afbe2e4c3bf2a40d41121817895a20d60a17b`、审计PASS；开发曲线1023终局+原有1科学截断；独立网格12288/12288、192分片，无缺局/科学截断。没有重新派局。
- `scripts/prism_m79_archive.py`的root transfer manifest合同是path→SHA映射，归档器另校验冻结评测计划、分片manifest、逐局ledger/回放、actor与严格Rust投影。root清单缺失由独立派生inventory补足，migration-r7清单未复用。R31–R36失败均保留并计入累计资源；精确执行源码快照725/725文件SHA核验后构建Rust投影器，绑定源码归档SHA `2c4e7a17832874741586fa7c70b447a135594c484d503b9fe99d38d48e0c346f`和投影器SHA `1c605d536a4e2d05be23142ba4115c60c7445ea9400a524ec474cec50995b58f`。独立r37适配SHA `34ae5ddeaa7ef4e64b1422d0ac24dfa6934cf83f82a19448c91f8383b14f318d`通过离线归档；验证12288回放、24576 actor画像、125701 inventory成员，0新局/forward，输入结果前后SHA不变。r37消费494.586控制CPU；控制/审计累计13248.866826/30000秒。
- 失败修订账：r31缺torch（0.034 CPU）；r32三次解释器导入路径/依赖根问题（各约0.03 CPU）；r33入口FileNotFound（131.397 CPU）；r34 Rust projector构建失败（131.018 CPU）；r35离线Cargo缺`hex`（0.046 CPU）；r36 crates.io在线索引超时（0.151 CPU）。另有本机首次C编译误用zig shim的构建失败（56.774本机CPU）；切换系统gcc/g++后成功。每个失败修订、来源和费用均保留，累计控制预算已合并历史消费。
- 候选、M75父代、固定Balance v0.2.0各3072局，六共同对手覆盖完整。画像DESCRIPTIVE；路线undetermined、路线证据INSUFFICIENT，无风格确认。冻结共同竞技增强推荐门未通过，不据此推断真实退化。候选不晋级、不发布、不部署。候选JSON SHA `5483619f4e285c893a8ecbba84d81a9beb3c77210c36a616789c6ce998fd1b92`；结果SHA `50a76a85fbfef46e41d296efa23915b4f76c4fae0672151e9e6ecd960735f85a`。
- 原阅读报告有JS语法错误，另建R2阅读报告并保留原审计/结果；阅读报告、完整证据、审计、候选卡和21篇报告索引已就位。Chromium实际像素核验1440×1000与390×844；窄屏表格可横向滚动，无控制台错误且文档宽度匹配视口。响应式候选卡独立修订。最终回执绑定页面SHA及桌面/窄屏截图SHA，状态PASS_VISUAL。
- 报告：`docs/prism/m79-prism-mainline-comparison-r2.html`、`.reading.md`、`m79-prism-mainline-comparison.audit.html`、`m79-prism-mainline-evidence.md`、`m79-prism-mainline-candidate-profile-r37.{json,md,html}`。候选卡响应式版本、视觉回执及交付manifest位于`local-artifacts/prism/m79-mainline/completion-r37/`与`docs/prism/`。
- ALL当前不可达，登记待同步；本地R9证据完整。未改科学结果、训练或调度频率；无新轮、commit、push或部署。`git diff --check`通过，`git check-ignore -v handoff.md`确认handoff仍ignored。

2026-10-14本次状态复核：远端主流水线完成回执及审计/开发/独立/报告PASS，无M79活动进程。本地阅读报告、候选JSON SHA匹配；视觉回执绑定的3页面与6截图共9项SHA全部匹配。delivery-manifest原视觉回执SHA手填漏字已纠正为da4b87f101401df3770b00a28b498ec9b932f16899e6407cc08bc7b8129214f5，修改前manifest完整保留，未变更原结果或视觉证据。ALL仍待同步。

### 2026-10-14 阅读修订 r3：重写为对战结论与决策报告

用户要求“这报告做的完全看不懂，给我做一版好的”。task_kind=report；授权终点为已有证据的可读报告重写、完整双方Markdown、审计说明及桌面/窄屏视觉验收；不启动新训练/评测、重判冻结门或发布部署。R0/R7适用分析/R8/R9本地完成；ALL同步待处理。

- 新入口 `docs/prism/m79-prism-mainline-comparison-r3.html`，按“对战涨跌→未过门原因→行为变化→产物用途→完整证据”重排。首页明确对父代54.35%、共同池+1.61个百分点、启发式−5.18个百分点；保留M75主线父候选，M79留档，未晋级。8对手表支持集合筛选，画像支持父代/固定Balance切换；23组双方胜平负、座位、购牌、折扣与动作保留在展开表和Markdown中。原结果、r2、旧画像和审计不改写。
- 独立阅读适配器 `scripts/prism_m79_reading_r3.py`，绑定 `benchmarks/reports/m79-reading-r3.json` 中6项输入SHA；原已pin评测/报告代码不改。生成时复核23组计数/双方互补/座位加总、12288局网格、6项端点点估计、画像样本与公式。置信区间沿用原冻结结果，不声称重跑bootstrap或全部回放审计。0新局、0模型前向。
- 发现旧画像 `noble_coverage` 与获得贵族局数/总局数不符。新版从已审计结果的六共同对手 `candidate_metrics.games_with_nobles` 加总并核对双方座位，M79为888/3072=28.91%，M75为899/3072=29.26%，固定Balance v0.2.0为1209/3072=39.36%。独立审计说明保留旧字段与更正值；未回写原画像或重新判定路线政策。旧候选卡含原错误字段，当前报告索引改为指向本版更正后的画像。
- Chromium实际1440×1000及390×844像素检查通过，12张截图涵盖首页及5部分；筛选6/2/8组、参照切换、展开表无整页溢出、所有链接/锚点、无JS核心内容、零运行异常均通过。证据 `local-artifacts/prism/m79-mainline/report-redesign/`；页面/MD/审计/生成器与截图SHA绑定在 `docs/prism/m79-prism-mainline-comparison-r3.reading-receipt.json`。视觉辅助首次导入路径和截图相对路径两次失败已修正，最终完整检查通过，未触碰研究进程。
- 报告索引已更新。ALL CLI实测仍fetch failed，仅登记待同步，不启动服务；本轮模型结论与实验结果不变。下一允许动作是阅读新版或基于既有回放另做退步诊断；本报告任务不包含启动下一轮。

### 2026-10-14 M79 退步回放诊断与 M81 执行方案交付

用户授权：用现有回放查启发式和旧Balance退步，给下一轮可直接交给Sol执行的方案。本次 task_kind=review+design；授权终点为只读分析和执行就绪设计，不包含本会话启动新训练/评测。

- 全量核验M75/M79 × 启发式/Balance v0.1.0 × 512，共2048现有终局。绑定r37已验证缓存及原Rust投影器，严格回放、SHA、胜负和动作总数、相同状态首分歧均核验通过；12288个Main4/8/12观测的购牌可支付判断与Rust合法动作集合一致。0新局、0模型前向。只取回约19.84MB派生诊断及四份病例回放，未全量恢复历史包。
- 启发式−5.18pp、事后配对95%区间−8.79～−1.56；旧Balance−2.25pp、区间−7.32～+2.73，后者真实退步未确认。下降配对中52/59、85/95在前12步已分歧，常见为拿宝石颜色/组合变化。更多预留在涨分对手上也存在；买回更快，直接购牌达到15分机会下的非购买比例下降，不支持单纯预留惩罚或统一残局收分退化解释。训练池遗漏两对手为待受控检验的假设，未宣称因果已证实。
- 诊断阅读入口docs/prism/m79-regression-diagnostic.md；证据local-artifacts/prism/m79-mainline/regression-diagnostic/{diagnostic,summary}.json及cases/manifest.json；独立scripts/prism_m79_regression_{diagnostic,summary}.py。源数据SHA与M79原结果保持。两个支付/本人隐藏预留边界测试通过。
- M81设计与可转发Sol指令已交付：docs/m81-anchor-coverage-pilot.md、docs/prism/m81-sol-dispatch.txt。双臂从M75同权重warm-start、同新种子/数值/PPO，各5120局；A原四对手25%各，B四对手18.75%各+启发式/旧Balance各12.5%。固定B c20为候选。新独立14336局，训练+评测共24576逻辑尝试；一对训练seed，明确pilot而非跨seed稳定性结论。机器合同/完整schedule及scripts/prism_m81_plan.py --validate已PASS；缺座位、lr漂移、旧deadline三个负例被拒绝。
- 新执行不设绝对钟点或整轮elapsed-wall停止，沿用户最新要求，以有限局数/累计CPU/存储/尝试为边界。Sol须在独立运行适配器中移除旧底层截止逻辑并预检，不只改文案。持久化控制器自动串联R0-R9，第二台不可用单机串行；Luna每60分钟巡检，正常/空闲不通知，只需用户操作或全轮交付通知。未实际创建新监控或启动M81。
- DSW实测可达，4核quota，64,197,808,128字节可用；DSW2连接拒绝只表示不可达，未认定关机。此快照只用于计划，启动时重测。ALL仍fetch failed，待同步不阻塞交付。模型仍未晋级；本次无发布部署、commit/push。


## 2026-10-14 耗时与利用率补核

M79 5120训练局、20×256、1108更新；CPU两线程。启动至训练完成38h05，至主流水线报告43h45（含故障/停等）。已完整计时训练段11h07，早期中断段墙钟缺失；训练收费含10000CPU秒保守估算，不可混作实测利用率。完整段平均约1.10核/4核27.47%。两轮逐局回执复核发现容量扫描监督开销；详见 [M81成本复核](m81-anchor-coverage-pilot.md) 末节。本次不新增页面或改变研究结果。
