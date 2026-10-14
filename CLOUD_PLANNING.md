# 云端规划入口 · Prism / Splendor

2026-10-11执行快照：M74 c20已登记Prism Balance v0.2.3，精确SHA `e16bfe0d30168d6ef7ceb067ca4357900f1c09e09d35f5759832dd3d6a9258ad`；M75从它出发，原单条5120训练尝试/20周期、1024开发及9216独立greedy网格正在执行。用户另行授权恢复并双机分工；16:19+08实际DSW训练3909尝试（3908终局+1截断）/c16/828更新，原训练worker21761，后续handoff调度48618；DSW2基线21392/8worker/983终局。此处只是有时间绑定的快照，Git不证明后续机器状态或增强。父代4096独立尝试放DSW2，候选5120留DSW；固定finalc20、科学网格与门不变，最终审计/冻结/汇合/结论尚未完成。当前来源与实际worker覆盖入口见[M75记录](docs/m75-prism-continuation.md)、[r2恢复](benchmarks/m75-prism-continuation.recovery-r2.json)、[双节点政策](benchmarks/m75-prism-continuation.dual-node-r3.json)、[真实worker绑定](benchmarks/m75-prism-continuation.dispatch-handoff-r1.json)。历史全包留私有魔搭按需取用；本轮必要输入/基线证据也经魔搭传入/汇回，不默认全量落本机。云端规划任务仍只做方向判断，不能从这条本机启动授权推导其自行开新轮或发布部署；下方保留原规划入口和历史证据。

更新：2026-10-08。用途：用户让云端仓库负责方向判断和下一轮规划。本次授权同步 Git 上下文；**不启动训练、评测、发布或部署**。规划稿可以提出新方案，不能把本地 M73 建议当成用户已经批准的研究合同。

## 先读什么

1. [当前研究规程](AGENTS.md)：任务终点、R0–R9、风格 S1–S6、固定版本/冠军/部署分开。
2. 本页：当前事实、已知限制、需要判断的问题和数据可得性。
3. [固定版本与 B 基线](docs/prism/prism-v020-fixed-models.md)、[注册表](benchmarks/prism-v020-model-registry.json)。
4. [历史模型画像与分布](docs/prism/style-atlas-2026-10-08.html)、[完整双方表](docs/prism/style-atlas-2026-10-08.md)、[历史统计](docs/prism/style-history-2026-10-08.md)。
5. [M70 结果记录](docs/m70-prism-b-continuation.md)、[M67 结果与修订](docs/m67-prism-alpha-repeat.md)、[长局诊断](docs/prism/m67-loop-implications-2026-10-07.md)。
6. [M73 设计建议](docs/m73-prism-v020-experiment-design.md)：DESIGNED，有 TBD，执行未授权。

历史记录按时间追加。M72 早期“尚未发布”“Beta候选B”等说法是发布前历史，**当前身份以本页及固定注册表为准**。旧结果中的 unpublished 原检查点名称保留，以精确 SHA 对应当前发布名，不重写历史门。

## 当前三个固定版本

|固定型号|原检查点|父代|权重SHA256|
|---|---|---|---|
|Prism Alpha v0.2.0|M67 A-c20|Alpha v0.1.5|`db3e2da279d777485c4dbb3d8d2ff78ddb106d231d5c75b58bc783e4fb66acb5`|
|Prism Balance v0.2.0|M67 B-c20|Alpha v0.1.5|`e2914425cac49f0f2272c44379e46a43525d97ced2eaac206e8600ebf73e79c4`|
|Prism Balance v0.2.1|M70 c4|Balance v0.2.0|`f4a9a628a9a0a376a84b2bc0f3b002e652bde42d4e1e4b3170a1830e3b14238a`|

用户已指定 **A走大牌/Alpha，B为Balance数据基线，M70为其Balance后继**。A/B原来是两个训练seed的身份，实际画像确有差异；训练臂名不预先证明风格。Beta v0.2.0未分配。B的Balance路线是指定研究身份，均衡行为尚未统计确认。没有默认替换或任何应用部署。

## 竞技事实与限制

|轮次|已有证据|不能越过的限制|
|---|---|---|
|M54|旧 General/Prism 的开发与验收负结果保留|共享池边界失败不能抹掉；发布不证明原方法验收通过|
|M61–M65|旧Balance/Beta/Alpha、原采样与后来greedy数据|各seed/mode/cohort分组，不拼接成统一胜率|
|M66|1,024局训练，7,168局确认|增强未确认；最终c4不改选中间模型|
|M67 B|5,120局训练；40,000局确认完整；共同池约+6.32pp，直接父代半平57.93%，原四项竞技门通过|只限冻结对手/模式；不能据此证明训练方法总体稳健|
|M67 A|5,120局训练；39,995局确认；直接父代约60.49%，共同池完整配对点估计约+7.64pp|五个缺项保留；共同池正式门未完成，两臂重复增强未确认|
|M70|从B fresh AdamW/RNG warm-start；1,024局训练/218更新；最终c4；7,168局独立greedy完整|单训练seed；共同池增强通过，直接增强未确认，总体增强未确认|

M70共同池相对B增益 **+2.8971pp，配对95%区间[+0.7650,+5.0944]pp**；直接B半平 **52.4414%，区间[49.7559,55.1270]%**。来源：[原结果](benchmarks/m70-prism-b-continuation.result.json)、[原合同](benchmarks/m70-prism-b-continuation.config.json)、[人类报告](docs/prism/m70-prism-b-continuation-comparison.reading.md)。注册Balance v0.2.1不改变这些门。

M67全网格109,995/110,000：未完成项是数据缺项，不填平局、不重新换seed、不改写成完整。原result及后来缺项审计分别保留，读[M69更正](docs/m69-prism-evaluation-failure-isolation.md)。

## 画像证据有什么

当前历史统计覆盖14个神经权重身份、16个cohort中的54份模型画像，另有逐对手与座位明细。M70 B与c4的逐局分布各3,072局。数据来自保存结果/回放，没有为统计补新局。

- [当前汇总JSON](benchmarks/prism-style-delivery-2026-10-08.json)、[早期历史JSON](benchmarks/prism-style-history-2026-10-08.json)、[逐局/模型分布JSON](benchmarks/prism-style-distributions-2026-10-08.json)。
- [B指定数据基线](benchmarks/prism-balance-data-baseline-v0.2.0.json)：三个独立cohort的参照，不能合成全球风格分布。
- [0–5VP购牌、贵族、效率与时钟完整表](docs/prism/style-atlas-2026-10-08.md)。0–5VP是印刷分；宝石费用和实体牌层级是不同概念。
- [Excel与24张图](outputs/01a11805-prism-style/Prism-模型画像与分组柱状图.xlsx)、[历史画像CSV](outputs/01a11805-prism-style/prism-historical-profiles.csv)、[分布观测CSV](outputs/01a11805-prism-style/prism-distribution-observations.csv)。这些是分析报表，非训练数据集。

A与B的差异有描述性证据，但相对彼此的小牌/贵族差值不等于Beta相对匹配Balance的确认。M70与B在同一cohort里：VP/Main约.5519→.5579，贵族覆盖41.11%→37.89%，低VP牌7.970→7.666/局，大牌印刷分7.615→7.931/局，表现出向大牌方向移动的描述倾向。发布路线与观测画像分开保存。

新候选的重要缺项：首张4–5VP的本人Main及覆盖、固定Main得分、早期0–1VP投资与后续真实兑现。低VP买得多不能单独证明基建；不显著不能证明均衡。现有区间分类器是事后描述政策，不是独立确认门，输出允许mixed/undetermined。

## 系统与停滞问题

[M71](docs/m71-prism-bounded-evaluation.md)实现有界评测、完整截断前缀/计数、一次写入与零自动重试等证据保全。已完成本地48项测试的记录不代表Linux实机已经验收，更不代表模型学会推进。M70没有把该修复热改入冻结执行。

已有9999步事故和定向检查显示合法购买机会存在。Main计数输入解释某些局部排名交叉，不能证明整体循环成因或纳什均衡。不能简单丢弃长局、补seed、填平局或推理期加人工偏置。若修改策略、编码或奖励，要独立有限受控合同。

## 架构与源码阅读入口

- [信息与架构边界](docs/architecture.md)、[M51数值合同](docs/m51-prism-implementation-contract.md)、[统一指标](docs/unified-match-metrics-standard.md)。规则由Rust核心决定，网络只接收玩家投影。
- [Rust Prism编码与推理](crates/splendor-prism/src/lib.rs)、[训练Python](training/prism/README.md)、[portable训练协调器](training/prism_portable/engine/ppo/coordinator.py)。
- [M70运行实现](scripts/prism_m70_run.py)、[M67](scripts/prism_m67_run.py)、[评测有界外壳](scripts/prism_bounded_eval.py)、[历史统计](scripts/prism_style_history.py)、[分类器](scripts/prism_style_atlas.py)。
- [实战晋级](docs/prism-practical-promotion-contract.md)、[阅读合同](docs/prism-report-reading-contract.md)、[轮次模板](docs/templates/prism-research-record.md)。

同步源码用于审阅当前研究实现，**不是M67/M70冻结执行包的重新认证**。旧实验的实际执行source/runtime/config SHA在原合同与结果中；完整不可变部署包在本地证据目录。未完成的Studio、M50及启发式业务代码修改不混入此提交；当前源码不能反过来代表历史执行。

## 云端需要判断的方向

请先判断：现阶段主要瓶颈是训练收益重复性、风格可区分性、长期局推进，还是资源/评测规模？根据现有证据排序，并说明每项建议能回答哪个问题。

本地[M73](docs/m73-prism-v020-experiment-design.md)已按用户贴回云端建议修订为cloud-review-r2：最低测量与Linux有界入口验收，再从固定B做三seed×1,024训练/19,456评测的有限重复估计；之后优先旧池/新池同预算对照，再研究风格。六端点增强全过不再是研究继续的唯一条件；2pp/52%/−3pp保留为模型资格的待冻结建议。近似直接端点功效约27%，不是精确或联合功效。seed/资源/精度/截止TBD，执行未授权；本次本地修订尚未新提交/推送，原发布清单只描述e0018fd提交。

云端规划应交付：优先顺序与理由、固定父代和同预算对照、有限预算/种子角色、候选选择、竞技及风格统计、停止条件、待补证据。可以改写M73建议，但需保留旧结果和否定证据。确认性风格政策必须在新采样前冻结，三个seed也不自动证明普适稳定性。

## 云端拿不到什么，以及核验范围

根`handoff.md`和`local-artifacts/`按发布策略不进Git。完整权重/optimizer/RNG/checkpoint、逐步回放/sidecar、远端执行源码包、原始训练数据、机器凭据和本地ALL回执未上传；只发布固定身份、原合同/聚合结果、画像统计、研究源码和可阅读报告。

因此云端可独立核验Git里JSON算术、SHA身份记录之间的一致性、画像分布和科学解释；**不能仅凭此仓库宣称重跑过原始比赛、验证了原始权重字节或完整回放**。原文中的本地路径仍作溯源标识，缺失不是零值或原实验未运行。若后续需要原始证据另行提出精确清单与传递范围，不能自动采样替代。

本地ALL旧心跳不证明机器仍在运行。M70完成来自已取回的完成回执/结果；本次未重新探测远端进程。云端没有本机ALL连接时注明不可用与待同步，不能编造心跳或以快照控制执行。

M72最新页面像素NOT_VERIFIED；旧history-r3页面的像素通过不能代替新版。M73页面像素未验证且非设计任务强制项。Git同步只检查发布内容，不重新升级视觉或研究验收。

本同步的文件清单与Git字节SHA见[发布清单](benchmarks/prism-cloud-planning-manifest-2026-10-08.json)。根文件和local-artifacts缺失属于明确发布边界。云端规划不要依赖本地handoff才能理解当前结论。


### 2026-10-11 18:49+08 M75调度r4快照

2026-10-11 18:49+08 后续评测重新分配r4已实际RUNNING：用户明确要求评测交DSW2、保留DSW训练。DSW新协调93803/create1791715613.28，原训练relay21760/worker21761不变；旧r3协调48618仅暂停防重复后续派局。当前4668/5120物理=4667终局+1截断、c19/992更新，无stop_reason。DSW2协调102954/create1791715630.95，8实际评测worker，已读297完成开发局（逐分片原子/全局非原子快照）；先固定c5/10/15共768开发，c20在DSW审计冻结后自动接256开发和5120独立，既有4096父代基线复用。1024/9216固定网格、模式/seed/门/最终c20/总CPU/截止不变；开发前三点提前仅描述，不反馈训练。两节点独立有限私有魔搭传输/调度，不依赖本机；传输上传最多6次，研究0重试。7+7+7零局检查/347原pin/host/runtime/PID预检PASS；实际新对局证明接续开跑。预计训练20:15–20:45，完整评测/报告22:00–23:00，建议23:00查看；02:50:30为原停止上限。证据eval-handoff-r4/launch-closeout.json，scripts/prism_m75_eval_handoff.py、benchmarks/m75-prism-continuation.eval-handoff-r4.json。M75实验R4 IN_PROGRESS/最终棋力未评测；本次分配启动范围完成，ALL待同步，无下一轮/发布部署/提交推送。
此为研究事实快照，不代表读取时仍运行；云端方向规划不扩大现有5120/1024/9216有限研究授权。


### 2026-10-11 20:26+08 DSW2替换恢复快照

2026-10-11 20:26+08 DSW2实例替换恢复r5已实际RUNNING：旧节点dsw-2246104…变为dsw-2246854…，原协调102954消失，原19:54 WAIT_FINAL-INPUT已存证；768开发早已全部完成/0截断，4096基线保留。新的wait-resume-r5 PID4335/create1791721579.66已核验实际存活/新鲜WAIT_FINAL-INPUT心跳，等待DSW c20后继续原256开发+5120候选，未重打已完成局。新节点347 pin/八核原runtime与12完整分片逐原字节/配置/网格验核PASS；本地及节点各4项针对性恢复回归PASS。原CPU385.750827秒计入，原r4来源/政策不变，r5独立SHA1ebe6f4c…c3236/policy e76e8894…d49e4。DSW原训练relay21760/worker21761及协调93803不控制不回退，当前5112/5120物理=5111正常+1保留截断，c20/1046更新，仍采集/stop_reason=null，盘25.89GiB。实例重建具体平台原因UNKNOWN；原脱离SSH进程不能跨实例替换自动复活，当前已从成功阶段守卫恢复，未声称实现平台级自启动。完整结果暂估22–23点/23点查看，截止02:50:30不变。证据wait-resume-r5/launch-closeout.json；scripts/prism_m75_wait_resume.py、benchmarks/m75-prism-continuation.wait-resume-r5.json。ALL fetch failed待同步，原实验IN_PROGRESS/最终棋力未评测，无下一轮/发布部署/提交推送。
仅历史执行快照；运行事实须读回对应node/PID/receipt，不能将此页当在线心跳。


### 2026-10-11 21:21+08 M75恢复与提醒执行快照

2026-10-11 21:21+08 M75 自动恢复/提醒已部署：DSW持久启动钩子与DSW2持久启动钩子接endpoint-v2/r8；server1 systemd服务enabled/Linger=yes、每60秒恢复核对，凭据仅稳定进程内存缓存；Codex heartbeat m75 ACTIVE/5分钟，首次等待、30/45分钟、失联/受阻主动提醒。14+3零局回归PASS，实际自动拉起DSW协调/已完成账本保持；整实例未重启测试，当前评测保留。DSW训练5120物理=5119终局+1截断/c20/1102更新及审计PASS，权重eaa1331b…62bf5；PID137439/create1791724376.17当前WAIT_EVALUATION-OUTPUT（空闲，已通知）。DSW2 PID14475/create1791724186.68，开发1024/1024无截断，候选独立808/5120已读正常局、8 worker；4096基线保留4095正常+1截断。原科学合同/截止02:50:30不变，完成局0重赛，未完成基础设施中断局最多恢复1次，协调6次上限/节点；失败修订及费用全部留存。完整结果预计22–23点，棋力仍未完成确认。记录docs/m75-prism-continuation.md，回执reboot-resume-r8/launch-closeout.json；ALL待同步。无下一轮/发布/部署/Git提交推送。

这是有时间戳的执行快照；云端规划须重新核对实际节点/PID/receipt。恢复与提醒只覆盖当前有限M75，不构成下一轮训练授权。

### M75 r9 双节点分片执行快照（2026-10-11T21:56:06.691937+08:00）

2026-10-11T21:56:06.691937+08:00 M75 r9分配已执行：候选4096旧局保留；DSW接5片320局/4worker，已完成0截断并魔搭SHA导入；DSW2接11片704局/8worker，PID60152/create1791726809.08，总候选4770/5120、0截断。对局约22:00，完整审计/归并报告预计22:20–22:45北京时间，原02:50:30截止/预算/c20不变。旧回放重验造成派发等待，独立ordering-v2让旧验证与新局并行；v3防止恢复时重复加DSW费用。两次零局启动目录错误及控制交接原始记录保留，完成局0重赛，5定向测试PASS。server1自动恢复启用；Codex提醒当前PAUSED，沿用开关，ALL待同步。证据local-artifacts/prism/m75-continuation/split-eval-r9/launch-closeout.json；详情docs/m75-prism-continuation.md，无下一轮/发布部署/提交push。
本节为执行快照；必须核验实时进程，不据此启动或重复游戏。

### M75 本轮执行完成快照（2026-10-11T23:30:00.351302+08:00）

2026-10-11T23:30:00.351302+08:00 M75最终交付只读核验：DSW在22:41:11完成RESULTS_AND_REPORTS_READY，DSW2在22:39:46完成私有魔搭57,033成员/66,594,425字节归并包交付。17对手双方pair/9215正常终局Rust回放规则审计PASS，1个旧基线cap保留；报告阶段PASS。16件必要模型/结果/报告/回执7,459,478字节取回并逐件SHA验证，原报告及统计未改；本机17组WDL/score、JSON-HTML payload、spec/result/contract/MD/HTML SHA、链接检查PASS，与上一读取直接56.10%/CI[53.13,59.03]、覆盖+11.62/+13.18pp一致。正式型号未登记、路线未定、共同配对门INCOMPLETE。报告docs/prism/m75-prism-continuation-comparison.html；索引已更新。两机无活跃研究，交付后等待约48.8/50.3分钟，DSW2一小时回收提醒已告知；平台空闲计时UNKNOWN。页面像素NOT_VERIFIED，不冒称视觉通过；ALL fetch failed待同步，Codex提醒PAUSED保留。0新局/0控制/无下一轮/发布部署/提交push。证据local-artifacts/prism/m75-continuation/report-delivery-r9/readback.json。

此快照不授权下一轮；云端规划请使用最终result/spec和docs执行记录，缺项与旧门保留。
