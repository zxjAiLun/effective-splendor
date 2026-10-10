# 云端规划入口 · Prism / Splendor

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
