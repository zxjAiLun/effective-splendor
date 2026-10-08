# M62 基建奖励与学习信号诊断

Status: VERIFIED / REVIEWED；2026-10-04；baseline `9899749188f35c838c85c5b3530049bd5dcbd105`。

**产物结论：**两份最终 c4 权重和保存数据有效；Prism Balance v0.1.1 candidate、Prism Beta v0.1.0 candidate 均未发布。本次新增诊断代码和报告，0 新对局、0 新优化器更新。

**竞技结论：**原 Control 两项保留门 PASS；Prism Beta v0.1.0 candidate 七门 3 PASS / 4 FAIL，仍为 `NOT_ACCEPTED_BUILDING_CANDIDATE`。固定对 Prism Alpha v0.1.4 半平得分率 54.9805%、校正下界 50.9766%，直接优势成立；通用锚点/对 Control 容忍底线未获确认，不是证明真实棋力退化。

**风格结论：**风格项确实改变了训练 advantage，但最终策略未形成预定的实质分化。逐笔封顶常见、utility 与投资张数高度相关，是改进奖励辨识度的依据；没有证明它们造成失败。不能再将本轮简单归因于“风格奖励没有进入训练”或“胜负完全压倒风格”。

[原交互对战页](prism-beta-v0.1.0-comparison.html) · [本报告 HTML](m62-building-reward-diagnostic.html) · [冻结完整原报告](m62-prism-beta-building-evaluation.md)。下方包含原完整双方对战表，JSON 仅作机器证据。

## 匹配的父版与候选变化

独立验收三共同锚点：Heuristic v0.3.1（greedy）、Prism v0.1.0（greedy）、Prism v0.1.1（T=1）；每模型 1,536 局 / 256 seed 块 × 双座 × 三对手。个人指标按模型身份合并座位。箭头只表示方向，不能单独表示更好或显著。


独立验收数据；所有个人指标按模型身份合并双座。

| 共同锚点等权平均 | 单位/归属 | Prism Balance v0.1.0 (T=1) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | control − 父 | Beta − control | Beta − 父 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 半平得分率 | %，模型本人 | 70.5078% | 71.8099% | 72.2005% | **↑ +1.3021 个百分点** | **↑ +0.3906 个百分点** | **↑ +1.6927 个百分点** |
| building效用 | 归一化0..1，模型本人 | 0.461507 | 0.449463 | 0.452772 | **↓ -0.012044** | **↑ +0.003309** | **↓ -0.008735** |
| 早期bonus AUC12 | 永久折扣个数，模型本人 | 1.981391 | 1.951280 | 1.969835 | **↓ -0.030111** | **↑ +0.018555** | **↓ -0.011556** |
| 终局VP | VP/局，模型本人 | 15.048828 | 15.057943 | 15.076172 | **↑ +0.009115** | **↑ +0.018229** | **↑ +0.027344** |
| 自身Main得分速度 | VP/Main，模型本人 | 0.562547 | 0.564355 | 0.564606 | **↑ +0.001808** | **↑ +0.000251** | **↑ +0.002059** |
| 永久折扣 | 个/局，模型本人 | 11.761719 | 11.563802 | 11.652344 | **↓ -0.197917** | **↑ +0.088542** | **↓ -0.109375** |
| 贵族 | 个/局，模型本人 | 0.427734 | 0.384766 | 0.435547 | **↓ -0.042969** | **↑ +0.050781** | **↑ +0.007812** |
| 终局未买回预留 | 张/局，模型本人 | 1.745443 | 1.694661 | 1.757812 | **↓ -0.050781** | **↑ +0.063151** | **↑ +0.012370** |
| Main25..32真实购卡分 | 印刷VP/局，模型本人；全局含早败 | 3.445964 | 3.429688 | 3.471354 | **↓ -0.016276** | **↑ +0.041667** | **↑ +0.025391** |


箭头仅为方向，不代表更好或显著。比例取总计数/总分母；共同锚点等权描述，direct单列。



上表为原报告冻结描述：VP/Main 行是三个锚点各自速度的等权平均，不能当成合并总 VP/总 Main；总分母口径见已纠正的原交互页。本诊断的兑现比例一律使用总投资分母。

## 诊断范围与可验证边界

保存开发 576 局与独立验收 8,704 局的双方 18,560 个 profile 全量读入；两臂各 1,024 个完整 actor 轨迹、合计 55,149 个决策重算。12,288 个原来源文件按逐局 ledger 核对哈希，Beta 的 1,024 个重算 profile 与原训练 style targets 全字段一致。八个 cycle 的重算合成 advantage 均值/标准差与原封存指标差不超过 1e-12。

cloud1 仅读取原文件：不调用 `Run.open()`，不拿 writer lock，不写 campaign/store，不启动引擎。训练提取约 209.36 秒、峰值 RSS 389.8 MiB，4 GiB 地址空间/600 秒/最多两个 CPU 的上限内；HEAD、lock、ledger 前后哈希均无漂移。评测 profile 压缩抓取的解压 SHA 与冻结 result 完全一致。本次是公式/统计诊断，没有重跑规则审计、Bootstrap、正式门或参数梯度实验。

GPT-6 Luna 审阅奖励语义并实现 profile 统计，主代理审查、修订要求、独立重跑与训练/策略面板验证。两次 Gemini 3.8 Flash High 路由均在执行前因账户兼容限制失败；未产出代码或数据。

## 投资奖励的辨识度

`use` 是后续实际购卡的原价在该颜色上达到这笔 bonus ordinal 的结构性适用次数，不是反事实节省 token，也不要求目标卡有 VP。原合同：前 12 个本人 Main 获得的 ≤1 VP 卡，统计至 Main24，每笔最多 3 use，全局最多 24，utility = credited units / 24。



| 阶段 | 本人模型（T=1） | 局 | 投资/局（张） | 总投资 | ≥1 use/投资 | ≥3 use/投资 | 原始 use units | 单笔截掉 units | 截掉/原始 | 全局截掉 units | 删失/投资 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| acceptance | Prism Balance v0.1.0 | 1536 | 3.9570 | 6078 | 99.358% | 84.715% | 25935 | 8922 | 34.401% | 0 | 0.592% |
| acceptance | Prism Beta v0.1.0 candidate（未发布） | 1536 | 3.8880 | 5972 | 99.464% | 84.444% | 25082 | 8391 | 33.454% | 0 | 0.435% |
| acceptance | Prism Balance v0.1.1 candidate（未发布） | 1536 | 3.8613 | 5931 | 99.376% | 84.337% | 24817 | 8248 | 33.235% | 0 | 0.590% |
| development | Prism Balance v0.1.0 | 192 | 3.8385 | 737 | 99.729% | 85.346% | 3213 | 1136 | 35.356% | 0 | 1.221% |
| development | Prism Beta v0.1.0 candidate（未发布） | 192 | 3.8229 | 734 | 99.319% | 85.150% | 3163 | 1105 | 34.935% | 0 | 1.090% |
| development | Prism Balance v0.1.1 candidate（未发布） | 192 | 3.8802 | 745 | 99.597% | 83.356% | 3141 | 1070 | 34.066% | 0 | 0.940% |



独立验收中 Control/Beta 约 84% 投资达到单笔封顶，约三分之一结构性 use 被截掉，全局 cap24 没有截掉任何单位。约 99% 投资至少使用一次；因此“是否兑现”在现有策略分布中已很少区分好坏。逐笔封顶确实压缩了差异，但相关性与饱和度不能证明训练失败的原因。没有全局饱和，不能将 cap24 视为本轮瓶颈。



| 阶段 | 本人模型 | utility均值 | 总体SD | min | p10 | 中位 | p90 | max | utility=0局 | 达到全局cap局 | r:投资张数 | r:AUC12 | r:Main13..24 VP | r:本人Main局长 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| acceptance | Prism Balance v0.1.0 | 0.461507 | 0.146653 | 0.0000 | 0.2500 | 0.5000 | 0.6250 | 0.8750 | 3 | 0 | 0.9493 | 0.7272 | 0.1664 | -0.0821 |
| acceptance | Prism Beta v0.1.0 candidate（未发布） | 0.452772 | 0.144922 | 0.0000 | 0.2500 | 0.4583 | 0.6250 | 0.8750 | 3 | 0 | 0.9512 | 0.7370 | 0.1739 | -0.1001 |
| acceptance | Prism Balance v0.1.1 candidate（未发布） | 0.449463 | 0.144037 | 0.0000 | 0.2500 | 0.4583 | 0.6250 | 0.8750 | 2 | 0 | 0.9536 | 0.7190 | 0.1971 | -0.1014 |
| development | Prism Balance v0.1.0 | 0.450738 | 0.150791 | 0.0833 | 0.2500 | 0.4583 | 0.6250 | 0.8333 | 0 | 0 | 0.9692 | 0.7427 | 0.1939 | -0.1151 |
| development | Prism Beta v0.1.0 candidate（未发布） | 0.446615 | 0.142154 | 0.1250 | 0.2500 | 0.4583 | 0.6250 | 0.7500 | 0 | 0 | 0.9610 | 0.7537 | 0.1393 | -0.0967 |
| development | Prism Balance v0.1.1 candidate（未发布） | 0.449436 | 0.141434 | 0.0417 | 0.2500 | 0.4583 | 0.6250 | 0.7500 | 0 | 0 | 0.9516 | 0.7189 | 0.0986 | 0.0266 |



profile 分位数采用 nearest-rank；训练与面板连续量使用线性插值分位数。SD 为总体标准差；r 为逐局 Pearson 描述相关，零方差返回 `NOT_APPLICABLE`。utility 与投资张数 r≈0.95，与 Main13..24 印刷 VP 仅约 0.17–0.20；后者不能作为“基建没有转换成胜利”的因果证明，也没有控制状态/市场/对手。



| 阶段 | 本人模型 | 首 use 覆盖投资 | 总投资 | 第三 use 覆盖投资 | 总投资 | 首 use 本人Main均值 | 第三 use 本人Main均值 | 首 use−购入Main | 第三 use−购入Main |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| acceptance | Prism Balance v0.1.0 | 6039 | 6078 | 5149 | 6078 | 10.7162 | 16.6281 | 3.2784 | 9.5605 |
| acceptance | Prism Beta v0.1.0 candidate（未发布） | 5940 | 5972 | 5043 | 5972 | 10.7448 | 16.6633 | 3.3549 | 9.6536 |
| acceptance | Prism Balance v0.1.1 candidate（未发布） | 5894 | 5931 | 5002 | 5931 | 10.7516 | 16.7459 | 3.3142 | 9.6847 |
| development | Prism Balance v0.1.0 | 735 | 737 | 629 | 737 | 10.8803 | 16.6010 | 3.3129 | 9.3609 |
| development | Prism Beta v0.1.0 candidate（未发布） | 729 | 734 | 625 | 734 | 10.8450 | 16.8768 | 3.3388 | 9.7168 |
| development | Prism Balance v0.1.1 candidate（未发布） | 742 | 745 | 621 | 745 | 10.8949 | 16.7456 | 3.3046 | 9.5395 |



时点只对实际发生相应 use 的投资计算，未发生的投资仍保留在完整总体/删失表中。独立验收中 Beta 的第三 use 比 Control 略早，首次 use 时点几乎相同；变化很小且未经独立时点验收，不能解释为稳定节奏优势。AUC12 的短局终局保持只用于描述，utility 没有补齐奖励。



| 匹配阶段 | 共同对手×seed×座位行 | Beta−Control utility | 投资/局 张 | AUC12 折扣个 | Main13..24 印刷VP | 本人Main/局 |
| --- | --- | --- | --- | --- | --- | --- |
| acceptance | 1536 | **↑ +0.003309** | **↑ +0.0267** | **↑ +0.018555** | **↓ -0.1087** | **↑ +0.0195** |
| development | 192 | **↓ -0.002821** | **↓ -0.0573** | **↓ -0.009549** | **↓ -0.3542** | **↑ +0.0365** |



## 实际训练 advantage：风格信号存在，但不能与参数梯度混称

按每个 cycle 的完整 actor 决策重算 `A = outcome_GAE + β × (utility − old_style_value)`，再用整个 batch 的均值/标准差归一化。终局 outcome 是 0/0.5/1，γ=1、λ=0.95、本人的决策时间轴。Control β=0；Beta β=0.3。由于归一化会减去整体均值，风格项的正均值不是额外全局推动力；需看中心化后的变异和变化。



| 训练模型 | cycle | 决策 | outcome GAE SD | β×residual 均值 | β×residual SD | 合成 raw 均值 | 合成 raw SD | style SD/合成SD | 相对仅outcome归一化平均绝对变化 | 中心化符号改变/决策 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.1 candidate（未发布） | 1 | 6907 | 0.288977 | 0.000000 | 0.000000 | 0.001486 | 0.288977 | 0.000% | 0.000000 | 0.000% |
| Prism Balance v0.1.1 candidate（未发布） | 2 | 6870 | 0.286547 | 0.000000 | 0.000000 | -0.006568 | 0.286547 | 0.000% | 0.000000 | 0.000% |
| Prism Balance v0.1.1 candidate（未发布） | 3 | 6871 | 0.291767 | 0.000000 | 0.000000 | -0.010228 | 0.291767 | 0.000% | 0.000000 | 0.000% |
| Prism Balance v0.1.1 candidate（未发布） | 4 | 6849 | 0.283233 | 0.000000 | 0.000000 | 0.003567 | 0.283233 | 0.000% | 0.000000 | 0.000% |
| Prism Beta v0.1.0 candidate（未发布） | 1 | 6898 | 0.278616 | 0.137360 | 0.043405 | 0.176057 | 0.280268 | 15.487% | 0.124639 | 4.813% |
| Prism Beta v0.1.0 candidate（未发布） | 2 | 6939 | 0.271770 | 0.133783 | 0.043156 | 0.097485 | 0.277836 | 15.533% | 0.125377 | 2.118% |
| Prism Beta v0.1.0 candidate（未发布） | 3 | 6900 | 0.288013 | 0.115453 | 0.043012 | 0.157442 | 0.291315 | 14.765% | 0.119878 | 4.319% |
| Prism Beta v0.1.0 candidate（未发布） | 4 | 6915 | 0.279915 | 0.093553 | 0.044547 | 0.073313 | 0.285388 | 15.609% | 0.128442 | 2.574% |



Beta 的中心化风格项约占合成 SD 的 14.8%–15.6%，归一化后平均绝对变化约 0.12，并改变 2.1%–4.8% 的决策符号。它比 outcome GAE 的变异小，但有真实非零影响；这不足以判断应把 β 提高多少，更不等于测到了梯度占比。style value MSE 还以 0.5 权重作用于共享表示，因此原 M62 的 outcome-only/Beta 对照无法将 actor reward 与辅助 critic 作用各自归因。



| 训练模型 | cycle | optimizer step | 局均utility（Control仅重算） | 局均AUC12 | 决策加权old style value | BCE未乘0.5 | style MSE未乘0.5 | sample加权KL | sample加权clip fraction | sample加权normalized entropy |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.1 candidate（未发布） | 1 | 54 | 0.442057 | 1.925456 | 0.000000 | 0.596375 | 0.000000 | 0.005407 | 0.068988 | 0.253451 |
| Prism Balance v0.1.1 candidate（未发布） | 2 | 54 | 0.458333 | 1.968750 | 0.000000 | 0.586897 | 0.000000 | 0.004481 | 0.053930 | 0.251353 |
| Prism Balance v0.1.1 candidate（未发布） | 3 | 54 | 0.443359 | 1.959961 | 0.000000 | 0.612344 | 0.000000 | 0.003674 | 0.046427 | 0.249282 |
| Prism Balance v0.1.1 candidate（未发布） | 4 | 54 | 0.432617 | 1.900391 | 0.000000 | 0.574707 | 0.000000 | 0.003862 | 0.050883 | 0.242531 |
| Prism Beta v0.1.0 candidate（未发布） | 1 | 54 | 0.459635 | 1.964193 | 0.000000 | 0.564282 | 0.222288 | 0.006007 | 0.071253 | 0.248060 |
| Prism Beta v0.1.0 candidate（未发布） | 2 | 56 | 0.468099 | 1.976888 | 0.021229 | 0.543888 | 0.204980 | 0.003176 | 0.041577 | 0.247483 |
| Prism Beta v0.1.0 candidate（未发布） | 3 | 54 | 0.444824 | 1.980469 | 0.059557 | 0.590266 | 0.149266 | 0.003958 | 0.047536 | 0.245724 |
| Prism Beta v0.1.0 candidate（未发布） | 4 | 56 | 0.435384 | 1.924805 | 0.121413 | 0.567043 | 0.096770 | 0.003496 | 0.043601 | 0.252691 |



style value 从 0 增至约 0.121，MSE 从约 0.222 降至 0.097；style critic 在学习，尚不能据此宣称校准完善。Beta 的 cycle utility/AUC 没有单调提升，这些是在不同训练局上得到的描述值。loss/KL 取历史每个 optimizer_step 按 samples 加权，未重新执行 optimizer，不据该表重挑 c4 或扩训。

## 同状态冻结策略面板

512 个已保存本人可见状态，按两臂×四 cycle×双座各 32 局；每个分组按 seed/job 排序，取首个 Main≤12 有 ≤1VP 合法购卡且有另一动作类别的机会。所有 2,048 训练局均有合格机会；面板只取前述固定子集。三个冻结导出模型在完全相同 input 上本机 CPU 单线程前向；float32 网络、float64 softmax、T=1、无动作偏置，同时记录 argmax 动作类别。



| 机会子集 | 状态 | 冻结模型 | ≤1VP buy概率质量均值 | ≥2VP buy概率质量均值 | 逐状态条件P(低VP∣buy)均值 | entropy nats | argmax低VP数 | argmax低VP/状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| all | 512 | Prism Balance v0.1.0 | 79.917% | 0.646% | 99.050% | 0.3977 | 424 | 82.812% |
| all | 512 | Prism Balance v0.1.1 candidate（未发布） | 77.939% | 0.593% | 99.035% | 0.4106 | 414 | 80.859% |
| all | 512 | Prism Beta v0.1.0 candidate（未发布） | 78.344% | 0.724% | 99.025% | 0.4224 | 415 | 81.055% |
| with_scoring_buy | 8 | Prism Balance v0.1.0 | 38.972% | 41.366% | 39.185% | 0.6678 | 3 | 37.500% |
| with_scoring_buy | 8 | Prism Balance v0.1.1 candidate（未发布） | 37.857% | 37.978% | 38.209% | 0.6045 | 3 | 37.500% |
| with_scoring_buy | 8 | Prism Beta v0.1.0 candidate（未发布） | 37.398% | 46.341% | 37.574% | 0.6323 | 3 | 37.500% |



整组 Beta−Control 的低 VP 购卡概率质量差为 **↑ +0.4045 个百分点**，argmax 低 VP 数为 415/414，父模型是 424。面板中只有 **8/512** 状态同时允许 ≥2VP 购卡；其余主要是在低 VP 买卡与拿 token/预留之间选择。约 99% 的条件 lowVP|buy 是机会集合造成的天花板，不能据此说三模型不区分牌质量。这份面板支持“早期首次购卡偏好相近”的有限结论，不能代表全部局面、未来收益、反事实 token 节省或夺走 Alpha 市场资源。



| 模型 | 本机CPU model.predict 总wall秒 | 状态 |
| --- | --- | --- |
| Prism Balance v0.1.0 | 2.5796 | 512 |
| Prism Balance v0.1.1 candidate（未发布） | 2.4140 | 512 |
| Prism Beta v0.1.0 candidate（未发布） | 2.4027 | 512 |



三模型面板总 wall 7.6875 秒。计时包含单状态 collation/Python前向；运行PyTorch 2.6.0+cu124、CPU单线程，远端训练记录运行PyTorch 2.6.0+cpu。该新离线计时不代替比赛的 decision/inference timing，后者原本未测的字段仍为 `NOT_MEASURED`；不能用它判定不同主机比赛速度。

## 下一轮单变量提议（PROPOSED / NOT_RUN）

优先继续基建 Beta 的有限研究，先修改奖励辨识度，再考虑增加轮数。保留真实后续购卡 use 条件，不直接把 AUC12 或 0VP 张数变成奖励。

建议下一次旧目标与时点目标做成两臂，**两臂都启用相同 style head/MSE、β=0.3、style_value_weight=0.5**，从同一冻结 Prism Balance v0.1.0、相同新初始化/RNG 开始；旧目标臂使用 M62 原 utility，新目标臂只改变 use 的时点权重。这比把当前 Beta 接着训练后与历史 Control 比较更能隔离此次修改。M62 c4 继续冻结作历史参照，不追加任何历史 seed。

可供下一合同审查的唯一新映射：对每笔符合原 early≤12、VP≤1 的投资，取原结构性规则下前 3 次真实 use，其本人 Main 时点 t≤24，每次记 `w(t)=(25−t)/24`；按原全局上限 24 截断总和，再除以 24。Main8/16/24 的相同 use 分别记 17/24、9/24、1/24；相同三次兑现会因更早发生而得到更高目标。未实际发生 use 仍为 0，noble 不加 Main，终局不补奖励，不读取隐藏信息。此映射未经实现/采样验证，数值尺度会随时点改变，不能声称等强或一定有效。

保留原 utility 与 AUC12 的独立描述；未来风格接受仍需预先声明实质变化和可接受代价，不能要求所有经济指标一齐提高。建议保留总体/通用锚点/直接竞争力保护，AUC12 实质目标仍以 +0.25 个折扣作为设计参照；旧 utility 的允许代价、全 family 校正、预算/种子/止损条件须在新对局之前另行冻结。原 M62 的九门完全保留，不把新 tolerance 套回原结果。

次序：先新映射合同与边界测试 → 保存轨迹上的数值范围及归一化核验（不用于证明更强）→ 固定有限 A/B 训练/独立验收合同 → 获得新采样授权后再运行。同步续训 Alpha、开 Denial 或单纯加 β 均不作为当前默认下一步。新的模型版本、训练及正式对战均 `NOT_RUN`。

## 证据与复现




| 本地材料（generated工件不发布） | SHA256 |
| --- | --- |
| `local-artifacts/prism/m62-building-research-2026-10-04/scope.json` | 64029b222325b30f6bcb98d4e51b6681fdab0a4e25507022af78a7189db1fbc8 |
| `local-artifacts/prism/m62-building-research-2026-10-04/profile-fetch-receipt.json` | d9ef13a68e5479a2b82a41f681bf3aa90d60bc0baf81c30bb714a9a98f6b3632 |
| `local-artifacts/prism/m62-building-research-2026-10-04/profile-diagnostic-final.json` | e184e3e39ebaa418e7c6ae66bfc71fc206f1aa8a01a3a0e46f5cad6f8b088c0f |
| `local-artifacts/prism/m62-building-research-2026-10-04/training-extraction-attempt1-receipt.json` | 2db8c0671bde262733ae40fb445003555b3c901d5ce971a265221e79f9f29e0c |
| `local-artifacts/prism/m62-building-research-2026-10-04/training-diagnostic-attempt1.json.gz` | 0c48710a732bf8dc9a24da456057c1bee43ea4ba1c3ea86c881b9d1d906d1862 |
| `local-artifacts/prism/m62-building-research-2026-10-04/policy-panel.json` | 3f596d51ffd46b821e65e192da939c303d626544362549c49a03ae7210728de8 |
| `scripts/prism_building_profile_diagnostic_m62.py` | f8adfd89bc26206562399e2d82ad8f7036556d648b918903f4252f817c725de8 |
| `scripts/prism_building_training_diagnostic_m62.py` | 03248d535df9074a9e6988a5b9be7ba828525b59566d8726e4f62ea5105b1186 |
| `scripts/prism_building_policy_panel_m62.py` | 749f59eb33eccd000652d360b5a05b3edaab2a4441b9edb1a1125fa135293c30 |
| `scripts/generate_m62_reward_diagnostic_report.py` | f12c5c8134ee06b9e856f911e47868b2ed8ee18fd15e26ffff8238a6e1279565 |



实际提取命令及 exit0/时钟见 training-extraction-attempt1-receipt.json；它通过SSH向cloud1执行 hash 固定的脚本 stdin，只输出gzip到本机新文件。profile与panel CLI、测试命令/exit另见 closeout-validation.json；报告的量化数据来自所列机器工件，人工解释不代替冻结验收。

## 全部逐对手 profile 诊断（双方个人指标）

此表每行是该 candidate 对 opponent group 的一个本人模型画像，role=candidate/opponent明确归属。pooled共同锚点的候选包含三个对手；对手按各自身份分开，不混成一个虚拟模型。



| 阶段 | 候选身份 | 对手组 | 本人role | 本人模型 | 局 | utility | 投资张数 | 兑现率 | 单笔封顶率 | 单笔截掉use | 全局截掉use | r utility/投资 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| acceptance | Prism Balance v0.1.0 | 三共同锚点（分别同权） | candidate | Prism Balance v0.1.0 | 1536 | 0.461507 | 6078 | 99.358% | 84.715% | 8922 | 0 | 0.9493 |
| acceptance | Prism Balance v0.1.0 | 三共同锚点（分别同权） | opponent | Heuristic v0.3.1 (greedy) | 512 | 0.520020 | 2222 | 99.820% | 89.919% | 4439 | 0 | 0.9645 |
| acceptance | Prism Balance v0.1.0 | 三共同锚点（分别同权） | opponent | Prism v0.1.1 (T=1) | 512 | 0.481283 | 2097 | 99.714% | 86.218% | 3291 | 0 | 0.9477 |
| acceptance | Prism Balance v0.1.0 | 三共同锚点（分别同权） | opponent | Prism v0.1.0 (greedy) | 512 | 0.527344 | 2261 | 99.779% | 89.518% | 4563 | 0 | 0.9557 |
| acceptance | Prism Balance v0.1.0 | Heuristic v0.3.1 (greedy) | candidate | Prism Balance v0.1.0 | 512 | 0.461426 | 2029 | 99.261% | 84.475% | 2928 | 0 | 0.9478 |
| acceptance | Prism Balance v0.1.0 | Heuristic v0.3.1 (greedy) | opponent | Heuristic v0.3.1 (greedy) | 512 | 0.520020 | 2222 | 99.820% | 89.919% | 4439 | 0 | 0.9645 |
| acceptance | Prism Balance v0.1.0 | Prism v0.1.1 (T=1) | candidate | Prism Balance v0.1.0 | 512 | 0.467285 | 2040 | 99.412% | 85.686% | 3134 | 0 | 0.9502 |
| acceptance | Prism Balance v0.1.0 | Prism v0.1.1 (T=1) | opponent | Prism v0.1.1 (T=1) | 512 | 0.481283 | 2097 | 99.714% | 86.218% | 3291 | 0 | 0.9477 |
| acceptance | Prism Balance v0.1.0 | Prism v0.1.0 (greedy) | candidate | Prism Balance v0.1.0 | 512 | 0.455811 | 2009 | 99.403% | 83.972% | 2860 | 0 | 0.9504 |
| acceptance | Prism Balance v0.1.0 | Prism v0.1.0 (greedy) | opponent | Prism v0.1.0 (greedy) | 512 | 0.527344 | 2261 | 99.779% | 89.518% | 4563 | 0 | 0.9557 |
| acceptance | Prism Beta v0.1.0 candidate（未发布） | 三共同锚点（分别同权） | candidate | Prism Beta v0.1.0 candidate（未发布） | 1536 | 0.452772 | 5972 | 99.464% | 84.444% | 8391 | 0 | 0.9512 |
| acceptance | Prism Beta v0.1.0 candidate（未发布） | 三共同锚点（分别同权） | opponent | Heuristic v0.3.1 (greedy) | 512 | 0.516439 | 2201 | 99.727% | 90.913% | 4551 | 0 | 0.9654 |
| acceptance | Prism Beta v0.1.0 candidate（未发布） | 三共同锚点（分别同权） | opponent | Prism v0.1.1 (T=1) | 512 | 0.485270 | 2114 | 99.338% | 86.566% | 3440 | 0 | 0.9546 |
| acceptance | Prism Beta v0.1.0 candidate（未发布） | 三共同锚点（分别同权） | opponent | Prism v0.1.0 (greedy) | 512 | 0.524658 | 2249 | 99.644% | 89.773% | 4673 | 0 | 0.9502 |
| acceptance | Prism Beta v0.1.0 candidate（未发布） | Prism Alpha v0.1.4 (T=1) | candidate | Prism Beta v0.1.0 candidate（未发布） | 1024 | 0.461507 | 4075 | 99.460% | 83.485% | 5616 | 0 | 0.9461 |
| acceptance | Prism Beta v0.1.0 candidate（未发布） | Prism Alpha v0.1.4 (T=1) | opponent | Prism Alpha v0.1.4 (T=1) | 1024 | 0.452352 | 3983 | 99.423% | 84.133% | 5886 | 0 | 0.9555 |
| acceptance | Prism Beta v0.1.0 candidate（未发布） | Prism Balance v0.1.0 (T=1) | candidate | Prism Beta v0.1.0 candidate（未发布） | 1024 | 0.460205 | 4052 | 99.605% | 83.835% | 5636 | 0 | 0.9504 |
| acceptance | Prism Beta v0.1.0 candidate（未发布） | Prism Balance v0.1.0 (T=1) | opponent | Prism Balance v0.1.0 (T=1) | 1024 | 0.464966 | 4090 | 99.584% | 83.814% | 5952 | 0 | 0.9477 |
| acceptance | Prism Beta v0.1.0 candidate（未发布） | Prism Balance v0.1.1 candidate（未发布；T=1） | candidate | Prism Beta v0.1.0 candidate（未发布） | 1024 | 0.454508 | 4021 | 99.527% | 82.890% | 5713 | 0 | 0.9498 |
| acceptance | Prism Beta v0.1.0 candidate（未发布） | Prism Balance v0.1.1 candidate（未发布；T=1） | opponent | Prism Balance v0.1.1 candidate（未发布；T=1） | 1024 | 0.446533 | 3949 | 99.392% | 83.414% | 5477 | 0 | 0.9484 |
| acceptance | Prism Beta v0.1.0 candidate（未发布） | Heuristic v0.3.1 (greedy) | candidate | Prism Beta v0.1.0 candidate（未发布） | 512 | 0.451497 | 2000 | 99.400% | 83.300% | 2852 | 0 | 0.9504 |
| acceptance | Prism Beta v0.1.0 candidate（未发布） | Heuristic v0.3.1 (greedy) | opponent | Heuristic v0.3.1 (greedy) | 512 | 0.516439 | 2201 | 99.727% | 90.913% | 4551 | 0 | 0.9654 |
| acceptance | Prism Beta v0.1.0 candidate（未发布） | Prism v0.1.1 (T=1) | candidate | Prism Beta v0.1.0 candidate（未发布） | 512 | 0.458659 | 2008 | 99.502% | 85.060% | 2853 | 0 | 0.9548 |
| acceptance | Prism Beta v0.1.0 candidate（未发布） | Prism v0.1.1 (T=1) | opponent | Prism v0.1.1 (T=1) | 512 | 0.485270 | 2114 | 99.338% | 86.566% | 3440 | 0 | 0.9546 |
| acceptance | Prism Beta v0.1.0 candidate（未发布） | Prism v0.1.0 (greedy) | candidate | Prism Beta v0.1.0 candidate（未发布） | 512 | 0.448161 | 1964 | 99.491% | 84.980% | 2686 | 0 | 0.9490 |
| acceptance | Prism Beta v0.1.0 candidate（未发布） | Prism v0.1.0 (greedy) | opponent | Prism v0.1.0 (greedy) | 512 | 0.524658 | 2249 | 99.644% | 89.773% | 4673 | 0 | 0.9502 |
| acceptance | Prism Balance v0.1.1 candidate（未发布） | 三共同锚点（分别同权） | candidate | Prism Balance v0.1.1 candidate（未发布） | 1536 | 0.449463 | 5931 | 99.376% | 84.337% | 8248 | 0 | 0.9536 |
| acceptance | Prism Balance v0.1.1 candidate（未发布） | 三共同锚点（分别同权） | opponent | Heuristic v0.3.1 (greedy) | 512 | 0.526611 | 2246 | 99.822% | 90.695% | 4645 | 0 | 0.9672 |
| acceptance | Prism Balance v0.1.1 candidate（未发布） | 三共同锚点（分别同权） | opponent | Prism v0.1.1 (T=1) | 512 | 0.489258 | 2124 | 99.576% | 87.006% | 3419 | 0 | 0.9535 |
| acceptance | Prism Balance v0.1.1 candidate（未发布） | 三共同锚点（分别同权） | opponent | Prism v0.1.0 (greedy) | 512 | 0.527995 | 2254 | 99.512% | 90.550% | 4571 | 0 | 0.9532 |
| acceptance | Prism Balance v0.1.1 candidate（未发布） | Prism Balance v0.1.0 (T=1) | candidate | Prism Balance v0.1.1 candidate（未发布） | 1024 | 0.452108 | 3992 | 99.599% | 83.492% | 5622 | 0 | 0.9468 |
| acceptance | Prism Balance v0.1.1 candidate（未发布） | Prism Balance v0.1.0 (T=1) | opponent | Prism Balance v0.1.0 (T=1) | 1024 | 0.464030 | 4092 | 99.462% | 83.504% | 5923 | 0 | 0.9419 |
| acceptance | Prism Balance v0.1.1 candidate（未发布） | Heuristic v0.3.1 (greedy) | candidate | Prism Balance v0.1.1 candidate（未发布） | 512 | 0.448893 | 1983 | 99.496% | 83.308% | 2775 | 0 | 0.9528 |
| acceptance | Prism Balance v0.1.1 candidate（未发布） | Heuristic v0.3.1 (greedy) | opponent | Heuristic v0.3.1 (greedy) | 512 | 0.526611 | 2246 | 99.822% | 90.695% | 4645 | 0 | 0.9672 |
| acceptance | Prism Balance v0.1.1 candidate（未发布） | Prism v0.1.1 (T=1) | candidate | Prism Balance v0.1.1 candidate（未发布） | 512 | 0.458659 | 2011 | 99.304% | 85.380% | 2847 | 0 | 0.9514 |
| acceptance | Prism Balance v0.1.1 candidate（未发布） | Prism v0.1.1 (T=1) | opponent | Prism v0.1.1 (T=1) | 512 | 0.489258 | 2124 | 99.576% | 87.006% | 3419 | 0 | 0.9535 |
| acceptance | Prism Balance v0.1.1 candidate（未发布） | Prism v0.1.0 (greedy) | candidate | Prism Balance v0.1.1 candidate（未发布） | 512 | 0.440837 | 1937 | 99.329% | 84.306% | 2626 | 0 | 0.9566 |
| acceptance | Prism Balance v0.1.1 candidate（未发布） | Prism v0.1.0 (greedy) | opponent | Prism v0.1.0 (greedy) | 512 | 0.527995 | 2254 | 99.512% | 90.550% | 4571 | 0 | 0.9532 |
| development | Prism Balance v0.1.0 | 三共同锚点（分别同权） | candidate | Prism Balance v0.1.0 | 192 | 0.450738 | 737 | 99.729% | 85.346% | 1136 | 0 | 0.9692 |
| development | Prism Balance v0.1.0 | 三共同锚点（分别同权） | opponent | Heuristic v0.3.1 (greedy) | 64 | 0.492188 | 264 | 99.242% | 90.530% | 488 | 0 | 0.9456 |
| development | Prism Balance v0.1.0 | 三共同锚点（分别同权） | opponent | Prism v0.1.1 (T=1) | 64 | 0.495443 | 270 | 99.259% | 87.407% | 412 | 0 | 0.9468 |
| development | Prism Balance v0.1.0 | 三共同锚点（分别同权） | opponent | Prism v0.1.0 (greedy) | 64 | 0.529297 | 280 | 100.000% | 92.500% | 565 | 0 | 0.9720 |
| development | Prism Balance v0.1.0 | Heuristic v0.3.1 (greedy) | candidate | Prism Balance v0.1.0 | 64 | 0.455729 | 247 | 100.000% | 86.640% | 409 | 0 | 0.9772 |
| development | Prism Balance v0.1.0 | Heuristic v0.3.1 (greedy) | opponent | Heuristic v0.3.1 (greedy) | 64 | 0.492188 | 264 | 99.242% | 90.530% | 488 | 0 | 0.9456 |
| development | Prism Balance v0.1.0 | Prism v0.1.1 (T=1) | candidate | Prism Balance v0.1.0 | 64 | 0.458984 | 251 | 99.203% | 85.657% | 380 | 0 | 0.9606 |
| development | Prism Balance v0.1.0 | Prism v0.1.1 (T=1) | opponent | Prism v0.1.1 (T=1) | 64 | 0.495443 | 270 | 99.259% | 87.407% | 412 | 0 | 0.9468 |
| development | Prism Balance v0.1.0 | Prism v0.1.0 (greedy) | candidate | Prism Balance v0.1.0 | 64 | 0.437500 | 239 | 100.000% | 83.682% | 347 | 0 | 0.9687 |
| development | Prism Balance v0.1.0 | Prism v0.1.0 (greedy) | opponent | Prism v0.1.0 (greedy) | 64 | 0.529297 | 280 | 100.000% | 92.500% | 565 | 0 | 0.9720 |
| development | Prism Beta v0.1.0 candidate（未发布） | 三共同锚点（分别同权） | candidate | Prism Beta v0.1.0 candidate（未发布） | 192 | 0.446615 | 734 | 99.319% | 85.150% | 1105 | 0 | 0.9610 |
| development | Prism Beta v0.1.0 candidate（未发布） | 三共同锚点（分别同权） | opponent | Heuristic v0.3.1 (greedy) | 64 | 0.498698 | 266 | 100.000% | 89.850% | 541 | 0 | 0.9776 |
| development | Prism Beta v0.1.0 candidate（未发布） | 三共同锚点（分别同权） | opponent | Prism v0.1.1 (T=1) | 64 | 0.484375 | 263 | 100.000% | 86.692% | 417 | 0 | 0.9590 |
| development | Prism Beta v0.1.0 candidate（未发布） | 三共同锚点（分别同权） | opponent | Prism v0.1.0 (greedy) | 64 | 0.541667 | 287 | 100.000% | 91.986% | 623 | 0 | 0.9752 |
| development | Prism Beta v0.1.0 candidate（未发布） | Heuristic v0.3.1 (greedy) | candidate | Prism Beta v0.1.0 candidate（未发布） | 64 | 0.434245 | 236 | 100.000% | 86.864% | 391 | 0 | 0.9700 |
| development | Prism Beta v0.1.0 candidate（未发布） | Heuristic v0.3.1 (greedy) | opponent | Heuristic v0.3.1 (greedy) | 64 | 0.498698 | 266 | 100.000% | 89.850% | 541 | 0 | 0.9776 |
| development | Prism Beta v0.1.0 candidate（未发布） | Prism v0.1.1 (T=1) | candidate | Prism Beta v0.1.0 candidate（未发布） | 64 | 0.452474 | 253 | 98.814% | 81.423% | 355 | 0 | 0.9465 |
| development | Prism Beta v0.1.0 candidate（未发布） | Prism v0.1.1 (T=1) | opponent | Prism v0.1.1 (T=1) | 64 | 0.484375 | 263 | 100.000% | 86.692% | 417 | 0 | 0.9590 |
| development | Prism Beta v0.1.0 candidate（未发布） | Prism v0.1.0 (greedy) | candidate | Prism Beta v0.1.0 candidate（未发布） | 64 | 0.453125 | 245 | 99.184% | 87.347% | 359 | 0 | 0.9708 |
| development | Prism Beta v0.1.0 candidate（未发布） | Prism v0.1.0 (greedy) | opponent | Prism v0.1.0 (greedy) | 64 | 0.541667 | 287 | 100.000% | 91.986% | 623 | 0 | 0.9752 |
| development | Prism Balance v0.1.1 candidate（未发布） | 三共同锚点（分别同权） | candidate | Prism Balance v0.1.1 candidate（未发布） | 192 | 0.449436 | 745 | 99.597% | 83.356% | 1070 | 0 | 0.9516 |
| development | Prism Balance v0.1.1 candidate（未发布） | 三共同锚点（分别同权） | opponent | Heuristic v0.3.1 (greedy) | 64 | 0.489583 | 261 | 100.000% | 88.889% | 489 | 0 | 0.9716 |
| development | Prism Balance v0.1.1 candidate（未发布） | 三共同锚点（分别同权） | opponent | Prism v0.1.1 (T=1) | 64 | 0.475911 | 257 | 100.000% | 88.327% | 423 | 0 | 0.9715 |
| development | Prism Balance v0.1.1 candidate（未发布） | 三共同锚点（分别同权） | opponent | Prism v0.1.0 (greedy) | 64 | 0.521484 | 277 | 99.639% | 91.336% | 554 | 0 | 0.9638 |
| development | Prism Balance v0.1.1 candidate（未发布） | Heuristic v0.3.1 (greedy) | candidate | Prism Balance v0.1.1 candidate（未发布） | 64 | 0.445964 | 244 | 99.590% | 85.246% | 380 | 0 | 0.9580 |
| development | Prism Balance v0.1.1 candidate（未发布） | Heuristic v0.3.1 (greedy) | opponent | Heuristic v0.3.1 (greedy) | 64 | 0.489583 | 261 | 100.000% | 88.889% | 489 | 0 | 0.9716 |
| development | Prism Balance v0.1.1 candidate（未发布） | Prism v0.1.1 (T=1) | candidate | Prism Balance v0.1.1 candidate（未发布） | 64 | 0.456380 | 252 | 99.206% | 84.524% | 361 | 0 | 0.9482 |
| development | Prism Balance v0.1.1 candidate（未发布） | Prism v0.1.1 (T=1) | opponent | Prism v0.1.1 (T=1) | 64 | 0.475911 | 257 | 100.000% | 88.327% | 423 | 0 | 0.9715 |
| development | Prism Balance v0.1.1 candidate（未发布） | Prism v0.1.0 (greedy) | candidate | Prism Balance v0.1.1 candidate（未发布） | 64 | 0.445964 | 249 | 100.000% | 80.321% | 329 | 0 | 0.9497 |
| development | Prism Balance v0.1.1 candidate（未发布） | Prism v0.1.0 (greedy) | opponent | Prism v0.1.0 (greedy) | 64 | 0.521484 | 277 | 99.639% | 91.336% | 554 | 0 | 0.9638 |



## 原 M62 完整对战表与原门（原文保留）

以下保存原判定及全部双方、双座、购卡、动作、节奏、时钟、身份/seed范围与来源表；上方解释边界和VP/Main口径更正优先。原报告 raw 审计与每局命令/字面seed仍保留在原SHA工件中。

## M62 Prism Beta v0.1.0 candidate / Prism Balance v0.1.1 candidate 固定评测报告

**产物：**最终c4是未发布训练候选：Prism Balance v0.1.1 candidate / Prism Beta v0.1.0 candidate；父版Prism Balance v0.1.0和固定Prism Alpha v0.1.4身份另列。审计有效性不由比赛胜率替代；候选版本名不自动表示发布/部署。

**竞技：**

| 字段 | 原始记录 |
| --- | --- |
| control_retention | PASS_RETENTION_FLOORS |
| beta_seven_gates | FAIL_BETA_GATES |
| cohort_qualified | True |
| beta_acceptance | NOT_ACCEPTED_BUILDING_CANDIDATE |


**风格：**FAIL_BUILDING_STYLE_THRESHOLDS；效用差≥0.015与非reward早期bonus AUC12差≥0.25折扣必须同时通过校正下界。

### 匹配共同锚点：父 → control → Beta

独立验收数据；所有个人指标按模型身份合并双座。

| 共同锚点等权平均 | 单位/归属 | Prism Balance v0.1.0 (T=1) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | control − 父 | Beta − control | Beta − 父 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 半平得分率 | %，模型本人 | 70.5078% | 71.8099% | 72.2005% | **↑ +1.3021 个百分点** | **↑ +0.3906 个百分点** | **↑ +1.6927 个百分点** |
| building效用 | 归一化0..1，模型本人 | 0.461507 | 0.449463 | 0.452772 | **↓ -0.012044** | **↑ +0.003309** | **↓ -0.008735** |
| 早期bonus AUC12 | 永久折扣个数，模型本人 | 1.981391 | 1.951280 | 1.969835 | **↓ -0.030111** | **↑ +0.018555** | **↓ -0.011556** |
| 终局VP | VP/局，模型本人 | 15.048828 | 15.057943 | 15.076172 | **↑ +0.009115** | **↑ +0.018229** | **↑ +0.027344** |
| 自身Main得分速度 | VP/Main，模型本人 | 0.562547 | 0.564355 | 0.564606 | **↑ +0.001808** | **↑ +0.000251** | **↑ +0.002059** |
| 永久折扣 | 个/局，模型本人 | 11.761719 | 11.563802 | 11.652344 | **↓ -0.197917** | **↑ +0.088542** | **↓ -0.109375** |
| 贵族 | 个/局，模型本人 | 0.427734 | 0.384766 | 0.435547 | **↓ -0.042969** | **↑ +0.050781** | **↑ +0.007812** |
| 终局未买回预留 | 张/局，模型本人 | 1.745443 | 1.694661 | 1.757812 | **↓ -0.050781** | **↑ +0.063151** | **↑ +0.012370** |
| Main25..32真实购卡分 | 印刷VP/局，模型本人；全局含早败 | 3.445964 | 3.429688 | 3.471354 | **↓ -0.016276** | **↑ +0.041667** | **↑ +0.025391** |


箭头仅为方向，不代表更好或显著。比例取总计数/总分母；共同锚点等权描述，direct单列。

### 九项采样前冻结门

| 门 | 目的 | 本人指标 / 单位（得分差为百分点） | 冻结阈值 | 估计 | 普通配对95% CI | 九项同时单侧下界 | 原判定 | 失败含义 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| control/strength_pool | control参照总体保留 | 相对Prism Balance v0.1.0半平得分率差 | 校正下界 ≥ -0.05 | 1.3021% | [-1.5299%, 4.1341%] | -2.3763% | **PASS** | 未能排除参照总体退步超过5个百分点 |
| control/direct_parent | control对父竞争力 | control对Prism Balance v0.1.0半平得分率 | 校正下界 ≥ 0.45 | 52.0508% | [49.1211%, 55.0293%] | 48.1497% | **PASS** | 未能确认参照对父得分率至少45% |
| beta/strength_pool | Beta总体代价控制 | Beta相对control共同锚点半平得分率差 | 校正下界 ≥ -0.05 | 0.3906% | [-2.7344%, 3.5482%] | -3.7435% | **PASS** | 未能排除Beta相对control退步超过5个百分点 |
| beta/general_anchor | 关键通用锚点保护 | Beta相对control对Prism v0.1.1半平得分率差 | 校正下界 ≥ -0.075 | -1.5625% | [-7.1289%, 4.1016%] | -8.8867% | **FAIL** | 未能排除关键对手退步超过7.5个百分点 |
| beta/direct_control | 同轮直接竞争力 | Beta对control半平得分率 | 校正下界 ≥ 0.45 | 47.9980% | [44.9219%, 51.0742%] | 43.9453% | **FAIL** | 未能确认Beta对control得分率至少45% |
| beta/direct_alpha | 大牌路线竞争力 | Beta对Prism Alpha v0.1.4半平得分率 | 校正下界 ≥ 0.45 | 54.9805% | [51.9531%, 58.0566%] | 50.9766% | **PASS** | 未能确认Beta对固定Alpha得分率至少45% |
| beta/direct_parent | 防共同退化 | Beta对Prism Balance v0.1.0半平得分率 | 校正下界 ≥ 0.45 | 51.8066% | [48.8281%, 54.8340%] | 47.9492% | **PASS** | 未能确认Beta对父得分率至少45% |
| beta/building_utility | 真实早期投资使用信号 | Beta相对control归一化效用差（0..1） | 校正下界 ≥ 0.015 | 0.003309 | [-0.003581, 0.010092] | -0.005612 | **FAIL** | 未能确认归一化效用实质差异至少0.015 |
| beta/early_bonus_auc12 | 非reward早期bonus风格信号 | Beta相对control前12Main平均永久折扣差（个） | 校正下界 ≥ 0.25 | 0.018555 | [0.004395, 0.032552] | 0.000380 | **FAIL** | 未能确认非reward指标实质差异至少0.25折扣 |


family α=0.05，**9项单侧同时下界，q=0.05/9**，20,000次配对双座seed块bootstrap，RNG62049999。共同锚点先在每个匹配seed块平均三锚点×双座；相同长度向量共享抽样索引。control须自身2门通过；Beta须7门通过且control参照合格。保留门通过不证明总体更强，也不证明等效。增强证据另按同一校正下界>0（得分差）或>.5（direct）记录；风格实质阈值仍为原门。全部9,280局完成后只做一次formal分析；0retry/0resume/不偷看/不扩样本/不挑checkpoint，失败候选与原门完整保留。

### 开发与独立方向

| 本人匹配变化 | 指标 | 单位 | 开发（描述） | 独立验收 | 方向解释 |
| --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) − Prism Balance v0.1.0 (T=1) | 半平得分率 | %，模型本人 | **↑ +7.0312 个百分点** | **↑ +1.3021 个百分点** | 同向/零变化；不合并样本 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) − Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | 半平得分率 | %，模型本人 | **↓ -5.7292 个百分点** | **↑ +0.3906 个百分点** | **方向相反；原数据保留** |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) − Prism Balance v0.1.0 (T=1) | building效用 | 归一化0..1，模型本人 | **↓ -0.001302** | **↓ -0.012044** | 同向/零变化；不合并样本 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) − Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | building效用 | 归一化0..1，模型本人 | **↓ -0.002821** | **↑ +0.003309** | **方向相反；原数据保留** |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) − Prism Balance v0.1.0 (T=1) | 早期bonus AUC12 | 永久折扣个数，模型本人 | **↑ +0.005642** | **↓ -0.030111** | **方向相反；原数据保留** |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) − Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | 早期bonus AUC12 | 永久折扣个数，模型本人 | **↓ -0.009549** | **↑ +0.018555** | **方向相反；原数据保留** |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) − Prism Balance v0.1.0 (T=1) | 终局VP | VP/局，模型本人 | **↑ +0.255208** | **↑ +0.009115** | 同向/零变化；不合并样本 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) − Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | 终局VP | VP/局，模型本人 | **↓ -0.562500** | **↑ +0.018229** | **方向相反；原数据保留** |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) − Prism Balance v0.1.0 (T=1) | 自身Main得分速度 | VP/Main，模型本人 | **↑ +0.016149** | **↑ +0.001808** | 同向/零变化；不合并样本 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) − Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | 自身Main得分速度 | VP/Main，模型本人 | **↓ -0.022005** | **↑ +0.000251** | **方向相反；原数据保留** |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) − Prism Balance v0.1.0 (T=1) | 永久折扣 | 个/局，模型本人 | **↓ -0.244792** | **↓ -0.197917** | 同向/零变化；不合并样本 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) − Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | 永久折扣 | 个/局，模型本人 | **↓ -0.005208** | **↑ +0.088542** | **方向相反；原数据保留** |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) − Prism Balance v0.1.0 (T=1) | 贵族 | 个/局，模型本人 | **↓ -0.104167** | **↓ -0.042969** | 同向/零变化；不合并样本 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) − Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | 贵族 | 个/局，模型本人 | **→ +0.000000** | **↑ +0.050781** | 同向/零变化；不合并样本 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) − Prism Balance v0.1.0 (T=1) | 终局未买回预留 | 张/局，模型本人 | **↓ -0.255208** | **↓ -0.050781** | 同向/零变化；不合并样本 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) − Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | 终局未买回预留 | 张/局，模型本人 | **↑ +0.312500** | **↑ +0.063151** | 同向/零变化；不合并样本 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) − Prism Balance v0.1.0 (T=1) | Main25..32真实购卡分 | 印刷VP/局，模型本人；全局含早败 | **↑ +0.307292** | **↓ -0.016276** | **方向相反；原数据保留** |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) − Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Main25..32真实购卡分 | 印刷VP/局，模型本人；全局含早败 | **↓ -0.177083** | **↑ +0.041667** | **方向相反；原数据保留** |


### 原验收与增强记录

| 字段 | 原始记录 |
| --- | --- |
| beta_acceptance | NOT_ACCEPTED_BUILDING_CANDIDATE |
| beta_accepted | False |
| beta_seven_gates | FAIL_BETA_GATES |
| beta_style | FAIL_BUILDING_STYLE_THRESHOLDS |
| cohort_qualified | True |
| confirmed_enhancement/beta/building_utility | False |
| confirmed_enhancement/beta/direct_alpha | True |
| confirmed_enhancement/beta/direct_control | False |
| confirmed_enhancement/beta/direct_parent | False |
| confirmed_enhancement/beta/early_bonus_auc12 | True |
| confirmed_enhancement/beta/general_anchor | False |
| confirmed_enhancement/beta/strength_pool | False |
| confirmed_enhancement/control/direct_parent | False |
| confirmed_enhancement/control/strength_pool | False |
| control_retention | PASS_RETENTION_FLOORS |


### 开发评测（仅描述）

| 被测玩家（T=1） | 固定对手 / 模式 | 局数 / 双座 seed 块 | W / D / L | 纯胜率 | 纯胜率配对95% CI | 半平得分率 | 半平得分率配对95% CI |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 64 / 32 | 42 / 0 / 22 | 65.6250% | [54.6875%, 76.5625%] | 65.6250% | [54.6875%, 76.5625%] |
| Prism Balance v0.1.0 (T=1) | Prism v0.1.1 (T=1) | 64 / 32 | 40 / 0 / 24 | 62.5000% | [51.5625%, 73.4375%] | 62.5000% | [51.5625%, 73.4375%] |
| Prism Balance v0.1.0 (T=1) | Prism v0.1.0 (greedy) | 64 / 32 | 47 / 1 / 16 | 73.4375% | [62.5000%, 84.3750%] | 74.2188% | [63.2812%, 84.3750%] |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 64 / 32 | 44 / 0 / 20 | 68.7500% | [57.8125%, 79.6875%] | 68.7500% | [57.8125%, 79.6875%] |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism v0.1.1 (T=1) | 64 / 32 | 40 / 0 / 24 | 62.5000% | [50.0000%, 75.0000%] | 62.5000% | [50.0000%, 75.0000%] |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism v0.1.0 (greedy) | 64 / 32 | 48 / 0 / 16 | 75.0000% | [62.5000%, 85.9375%] | 75.0000% | [62.5000%, 85.9375%] |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 64 / 32 | 50 / 0 / 14 | 78.1250% | [65.6250%, 89.0625%] | 78.1250% | [65.6250%, 89.0625%] |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism v0.1.1 (T=1) | 64 / 32 | 44 / 1 / 19 | 68.7500% | [54.6875%, 81.2500%] | 69.5312% | [56.2500%, 81.2500%] |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism v0.1.0 (greedy) | 64 / 32 | 48 / 1 / 15 | 75.0000% | [64.0625%, 84.3750%] | 75.7812% | [64.8438%, 85.9375%] |


#### Heuristic v0.3.1 (greedy; Hello 0.2.9)：完整双方数据

“模型”列是被测玩家；对手列注明动作模式。个人指标每格为“被测模型 / 对手”。节奏是该模型对阵该对手的整局指标。纯胜率=胜/局数，得分率=(胜+0.5平)/局数。

| 模型（T=1） | 对手 | 局数 / 双座种子数 | 胜 / 平 / 负 | 纯胜率 | 得分率 | 描述性配对95%区间 |
| --- | --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 64 / 32 | 42 / 0 / 22 | 65.6250% | 65.6250% | [54.6875%, 76.5625%] |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 64 / 32 | 44 / 0 / 20 | 68.7500% | 68.7500% | [57.8125%, 79.6875%] |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 64 / 32 | 50 / 0 / 14 | 78.1250% | 78.1250% | [65.6250%, 89.0625%] |


##### 双座明细

| 模型 | 对手 | 本模型座位 | 局数 | 胜 / 平 / 负 | 得分率 | 局均VP（模型 / 对手） |
| --- | --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 先手 P0 | 32 | 24 / 0 / 8 | 75.0000% | 15.188 / 13.250 |
| Prism Balance v0.1.0 (T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 后手 P1 | 32 | 18 / 0 / 14 | 56.2500% | 14.938 / 12.812 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 先手 P0 | 32 | 23 / 0 / 9 | 71.8750% | 15.094 / 12.031 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 后手 P1 | 32 | 21 / 0 / 11 | 65.6250% | 14.531 / 12.781 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 先手 P0 | 32 | 27 / 0 / 5 | 84.3750% | 15.500 / 11.625 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 后手 P1 | 32 | 23 / 0 / 9 | 71.8750% | 15.406 / 12.188 |


##### 对局节奏与风格

| 模型 / 对手 | 局均步数 | 决策轮：均值 / 最短 / 中位 / 最长 | 轮标准差 | Main轮均值 | 终局绝对分差 | 分差≤2 | 总VP AUC24 | 20 Main内8VP |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) / Heuristic v0.3.1 (greedy; Hello 0.2.9) | 53.359 | 26.703 / 23 / 27.0 / 31 | 1.617 | 26.656 | 3.906 | 39.06% | 0.22335 | 28.1250% |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) / Heuristic v0.3.1 (greedy; Hello 0.2.9) | 52.328 | 26.172 / 22 / 26.0 / 30 | 1.833 | 26.156 | 4.469 | 25.00% | 0.22917 | 40.6250% |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) / Heuristic v0.3.1 (greedy; Hello 0.2.9) | 52.375 | 26.188 / 20 / 27.0 / 30 | 1.657 | 26.188 | 4.672 | 23.44% | 0.23277 | 40.6250% |


总VP AUC24/20 Main列为被测玩家；短于24自身Main的AUC按终局分补足固定窗口。legacy决策轮=ceil(全动作步数/2)，含贵族选择；Main轮排除贵族选择。本表总VP/大牌轨迹是描述性指标；M62九门使用独立building画像。

##### 双方得分、购卡、折扣、贵族与预留

| 个人指标：模型 / 对手 | Prism Balance v0.1.0 (T=1) 对阵 Heuristic v0.3.1 (greedy; Hello 0.2.9) | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Heuristic v0.3.1 (greedy; Hello 0.2.9) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Heuristic v0.3.1 (greedy; Hello 0.2.9) |
| --- | --- | --- | --- |
| 局均最终VP | 15.0625 / 13.0312 | 14.8125 / 12.4062 | 15.4531 / 11.9062 |
| VP / 自身决策（含贵族选择） | 0.5647 / 0.4883 | 0.5660 / 0.4743 | 0.5901 / 0.4547 |
| VP / 自身Main | 0.5651 / 0.4889 | 0.5663 / 0.4743 | 0.5901 / 0.4547 |
| VP / 全局步数 | 0.2823 / 0.2442 | 0.2831 / 0.2371 | 0.2950 / 0.2273 |
| 局均永久折扣 / 购卡 | 11.9062 / 12.8750 | 11.5625 / 12.7969 | 11.5469 / 12.8906 |
| 局均贵族数 | 0.4375 / 0.7188 | 0.4531 / 0.6406 | 0.3750 / 0.6406 |
| 局均预留获取 | 2.9375 / 2.5625 | 2.8906 / 2.2656 | 2.5000 / 2.5625 |
| 局均预留买回 | 1.1875 / 1.4688 | 1.1875 / 1.2812 | 1.0469 / 1.3906 |
| 终局未买回预留 | 1.7500 / 1.0938 | 1.7031 / 0.9844 | 1.4531 / 1.1719 |
| 获得贵族的对局比例 | 35.938% / 53.125% | 34.375% / 45.312% | 35.938% / 54.688% |
| 预留买回 / 获取 | 40.426% / 57.317% | 41.081% / 56.552% | 41.875% / 54.268% |
| 局均购入 0 VP卡 | 5.9531 / 7.0781 | 5.5625 / 7.3125 | 5.4688 / 7.3125 |
| 局均购入 1 VP卡 | 1.7812 / 2.8750 | 2.1719 / 2.5312 | 1.9688 / 2.8281 |
| 局均购入 2 VP卡 | 2.1719 / 1.6094 | 1.8750 / 1.6875 | 1.9844 / 1.6406 |
| 局均购入 3 VP卡 | 0.7656 / 0.6406 | 0.7344 / 0.6250 | 0.6250 / 0.6719 |
| 局均购入 4 VP卡 | 0.8438 / 0.5000 | 0.7656 / 0.5000 | 0.9844 / 0.3281 |
| 局均购入 5 VP卡 | 0.3906 / 0.1719 | 0.4531 / 0.1406 | 0.5156 / 0.1094 |
| 局均 白 折扣 | 2.4531 / 2.5938 | 2.2031 / 2.6719 | 2.4531 / 2.5000 |
| 局均 蓝 折扣 | 2.2656 / 2.3750 | 2.2344 / 2.2500 | 2.0625 / 2.5469 |
| 局均 绿 折扣 | 2.5312 / 2.5938 | 2.5625 / 2.5156 | 2.3281 / 2.5781 |
| 局均 红 折扣 | 2.4062 / 2.9219 | 2.3906 / 2.7812 | 2.4688 / 2.7812 |
| 局均 黑 折扣 | 2.2500 / 2.3906 | 2.1719 / 2.5781 | 2.2344 / 2.4844 |


##### 全部七类动作

| 个人指标：模型 / 对手 | Prism Balance v0.1.0 (T=1) 对阵 Heuristic v0.3.1 (greedy; Hello 0.2.9) | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Heuristic v0.3.1 (greedy; Hello 0.2.9) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Heuristic v0.3.1 (greedy; Hello 0.2.9) |
| --- | --- | --- | --- |
| 买市场 次数 | 686 / 730 | 664 / 737 | 672 / 736 |
| 买市场 占自身全部决策 | 40.187% / 42.740% | 39.642% / 44.026% | 40.095% / 43.914% |
| 买预留 次数 | 76 / 94 | 76 / 82 | 67 / 89 |
| 买预留 占自身全部决策 | 4.452% / 5.504% | 4.537% / 4.898% | 3.998% / 5.310% |
| 取宝石 次数 | 756 / 718 | 749 / 710 | 777 / 687 |
| 取宝石 占自身全部决策 | 44.288% / 42.037% | 44.716% / 42.413% | 46.360% / 40.990% |
| 预留市场 次数 | 188 / 164 | 185 / 144 | 160 / 162 |
| 预留市场 占自身全部决策 | 11.013% / 9.602% | 11.045% / 8.602% | 9.547% / 9.666% |
| 预留牌堆 次数 | 0 / 0 | 0 / 1 | 0 / 2 |
| 预留牌堆 占自身全部决策 | 0.000% / 0.000% | 0.000% / 0.060% | 0.000% / 0.119% |
| 选贵族 次数 | 1 / 2 | 1 / 0 | 0 / 0 |
| 选贵族 占自身全部决策 | 0.059% / 0.117% | 0.060% / 0.000% | 0.000% / 0.000% |
| 跳过 次数 | 0 / 0 | 0 / 0 | 0 / 0 |
| 跳过 占自身全部决策 | 0.000% / 0.000% | 0.000% / 0.000% | 0.000% / 0.000% |


##### 实测计时

| 模型 / 对手 | 进程耗时累计s | 单局均值s | 单局P95s | 决策 / 推理延迟 |
| --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) / Heuristic v0.3.1 (greedy; Hello 0.2.9) | 12.848 | 0.2008 | 0.2909 | NOT_MEASURED / NOT_MEASURED |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) / Heuristic v0.3.1 (greedy; Hello 0.2.9) | 13.120 | 0.2050 | 0.2763 | NOT_MEASURED / NOT_MEASURED |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) / Heuristic v0.3.1 (greedy; Hello 0.2.9) | 13.273 | 0.2074 | 0.2866 | NOT_MEASURED / NOT_MEASURED |


单局时钟包括程序启动、比赛、验核和输出；累计单局秒数含并行重叠，不等于整批墙钟。未记录逐决策/推理延迟，不能填0或由单局时间推算。

#### 大牌购入时点与分段得分（双方个人指标）

| 个人指标：模型 / 对手 | Prism Balance v0.1.0 (T=1) 对阵 Heuristic v0.3.1 (greedy; Hello 0.2.9) | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Heuristic v0.3.1 (greedy; Hello 0.2.9) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Heuristic v0.3.1 (greedy; Hello 0.2.9) |
| --- | --- | --- | --- |
| 24 Main 总VP AUC（描述性；非M62奖励） | 0.2234 / 0.1832 | 0.2292 / 0.1768 | 0.2328 / 0.1707 |
| 24 Main 大牌印刷VP AUC（描述性；非M62门） | 0.0884 / 0.0571 | 0.0864 / 0.0526 | 0.0973 / 0.0479 |
| 终局3～5VP牌印刷分合计 | 7.6250 / 4.7812 | 7.5312 / 4.5781 | 8.3906 / 3.8750 |
| 前24自身Main购入3～5VP牌数 | 1.4844 / 1.0000 | 1.4062 / 0.9531 | 1.4844 / 0.8438 |
| 首张3～5VP牌 自身Main（仅买到的局） | 17.8889 / 19.0385 | 18.1774 / 19.3333 | 17.3226 / 19.3878 |
| 首张3～5VP牌 覆盖局数 / 总局数（双方） | 63/64 ; 52/64 | 62/64 ; 51/64 | 62/64 ; 49/64 |
| 首张4～5VP牌 自身Main（仅买到的局） | 19.9455 / 20.4118 | 20.8148 / 21.2581 | 20.0862 / 20.6923 |
| 首张4～5VP牌 覆盖局数 / 总局数（双方） | 55/64 ; 34/64 | 54/64 ; 31/64 | 58/64 ; 26/64 |
| 自身Main 8 后局均总VP | 0.8906 / 0.5781 | 0.7812 / 0.5000 | 0.8125 / 0.5781 |
| 自身Main 8 后局均大牌印刷VP | 0.1250 / 0.0000 | 0.0000 / 0.0000 | 0.0938 / 0.0000 |
| 自身Main 8 实际达到局数（双方） | 64 / 64 | 64 / 64 | 64 / 64 |
| 自身Main 12 后局均总VP | 2.0000 / 1.7969 | 2.2656 / 1.5625 | 2.0156 / 1.6562 |
| 自身Main 12 后局均大牌印刷VP | 0.4375 / 0.4219 | 0.5469 / 0.2656 | 0.4531 / 0.3750 |
| 自身Main 12 实际达到局数（双方） | 64 / 64 | 64 / 64 | 64 / 64 |
| 自身Main 16 后局均总VP | 3.8281 / 3.0469 | 3.8906 / 2.8594 | 4.0625 / 2.8438 |
| 自身Main 16 后局均大牌印刷VP | 1.1719 / 0.6719 | 1.1875 / 0.6406 | 1.5625 / 0.5781 |
| 自身Main 16 实际达到局数（双方） | 64 / 64 | 64 / 64 | 64 / 64 |
| 自身Main 20 后局均总VP | 6.4219 / 5.5000 | 6.7500 / 5.5469 | 7.1250 / 5.0156 |
| 自身Main 20 后局均大牌印刷VP | 2.7656 / 1.9219 | 2.7656 / 1.8438 | 3.1875 / 1.5469 |
| 自身Main 20 实际达到局数（双方） | 64 / 64 | 64 / 64 | 64 / 64 |
| 自身Main 24 后局均总VP | 11.5000 / 9.3125 | 11.2500 / 9.2969 | 11.4531 / 8.8906 |
| 自身Main 24 后局均大牌印刷VP | 5.7344 / 3.6094 | 5.3438 / 3.3438 | 5.7500 / 2.9844 |
| 自身Main 24 实际达到局数（双方） | 62 / 62 | 60 / 60 | 59 / 59 |


每格为模型 / 对手。自身Main含购卡/取宝石/预留/跳过，不含贵族选择；贵族分计入前一个Main。短局在后续固定检查点用其终局分补足，并列实际达到该Main的局数。大牌仅含购入3～5VP卡的印刷VP，排除贵族；AUC按15VP截断、固定24分母。首牌时点只对买到的局取均值，必须连同覆盖率解读，不能单凭均值认定更快。

#### 基建投资与后续兑现（双方完整画像）

| 个人指标（被测模型 / 对手） | Prism Balance v0.1.0 (T=1) 对阵 Heuristic v0.3.1 (greedy; Hello 0.2.9) | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Heuristic v0.3.1 (greedy; Hello 0.2.9) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Heuristic v0.3.1 (greedy; Hello 0.2.9) |
| --- | --- | --- | --- |
| building效用（归一化0..1，reward代理） | 0.455729 / 0.492188 | 0.434245 / 0.498698 | 0.445964 / 0.489583 |
| 早期bonus AUC12（原始永久折扣个数；非reward） | 1.950521 / 1.975260 | 1.888021 / 1.976562 | 1.911458 / 1.966146 |
| 真实折扣适用使用单位 / 局（全局cap24） | 10.937500 / 11.812500 | 10.421875 / 11.968750 | 10.703125 / 11.750000 |
| cap3/投资后、全局cap前使用单位 / 局 | 10.937500 / 11.812500 | 10.421875 / 11.968750 | 10.703125 / 11.750000 |
| 未截断真实折扣使用单位 / 局 | 17.328125 / 19.437500 | 16.531250 / 20.421875 | 16.640625 / 19.390625 |
| 前12Main真实购卡 / 局 | 4.453125 / 4.515625 | 4.328125 / 4.500000 | 4.421875 / 4.484375 |
| 早期≤1VP投资 / 局 | 3.859375 / 4.125000 | 3.687500 / 4.156250 | 3.812500 / 4.078125 |
| 兑现投资 / 局 | 3.859375 / 4.093750 | 3.687500 / 4.156250 | 3.796875 / 4.078125 |
| 未兑现投资 / 局 | 0.000000 / 0.031250 | 0.000000 / 0.000000 | 0.015625 / 0.000000 |
| 观察窗口删失投资 / 局 | 0.015625 / 0.015625 | 0.062500 / 0.031250 | 0.031250 / 0.093750 |
| 未兑现且删失投资 / 局 | 0.000000 / 0.015625 | 0.000000 / 0.000000 | 0.000000 / 0.000000 |
| Main13..24真实购卡印刷VP / 局 | 8.750000 / 6.765625 | 8.234375 / 6.796875 | 8.921875 / 6.343750 |
| Main13..24真实观察Main / 局 | 11.968750 / 11.968750 | 11.921875 / 11.921875 | 11.875000 / 11.875000 |
| Main25..32真实得分购卡印刷VP / 局 | 3.000000 / 2.312500 | 2.953125 / 2.125000 | 3.390625 / 1.984375 |
| Main25..32真实观察Main / 局 | 2.687500 / 2.687500 | 2.234375 / 2.234375 | 2.312500 / 2.312500 |
| Main25..32印刷VP / 真实观察Main（总分母） | 1.116279 / 0.860465 | 1.321678 / 0.951049 | 1.466216 / 0.858108 |
| 投资兑现 / 投资总数 | 100.0000% / 99.2424% | 100.0000% / 100.0000% | 99.5902% / 100.0000% |
| 未兑现 / 投资总数 | 0.0000% / 0.7576% | 0.0000% / 0.0000% | 0.4098% / 0.0000% |
| 删失 / 投资总数 | 0.4049% / 0.3788% | 1.6949% / 0.7519% | 0.8197% / 2.2989% |
| 短于12Main对局比例 | 0.0000% / 0.0000% | 0.0000% / 0.0000% | 0.0000% / 0.0000% |
| 未达24Main对局比例 | 3.1250% / 3.1250% | 6.2500% / 6.2500% | 7.8125% / 7.8125% |
| 未达32Main对局比例 | 100.0000% / 100.0000% | 100.0000% / 100.0000% | 100.0000% / 100.0000% |


每格是被测模型 / 对手，包含全部对局、早败和未兑现投资。奖励不padding；AUC12短局终局折扣保持仅作描述。

| 被测玩家 | 对手 | 本模型物理座位 | 局数 | 效用（模型/对手） | AUC12折扣（模型/对手） |
| --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 先手 P0 | 32 | 0.471354 / 0.493490 | 2.020833 / 1.960938 |
| Prism Balance v0.1.0 (T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 后手 P1 | 32 | 0.440104 / 0.490885 | 1.880208 / 1.989583 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 先手 P0 | 32 | 0.442708 / 0.485677 | 1.934896 / 1.927083 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 后手 P1 | 32 | 0.425781 / 0.511719 | 1.841146 / 2.026042 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 先手 P0 | 32 | 0.450521 / 0.484375 | 1.963542 / 1.963542 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 后手 P1 | 32 | 0.441406 / 0.494792 | 1.859375 / 1.968750 |


#### Prism v0.1.1 (T=1)：完整双方数据

“模型”列是被测玩家；对手列注明动作模式。个人指标每格为“被测模型 / 对手”。节奏是该模型对阵该对手的整局指标。纯胜率=胜/局数，得分率=(胜+0.5平)/局数。

| 模型（T=1） | 对手 | 局数 / 双座种子数 | 胜 / 平 / 负 | 纯胜率 | 得分率 | 描述性配对95%区间 |
| --- | --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) | Prism v0.1.1 (T=1) | 64 / 32 | 40 / 0 / 24 | 62.5000% | 62.5000% | [51.5625%, 73.4375%] |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism v0.1.1 (T=1) | 64 / 32 | 40 / 0 / 24 | 62.5000% | 62.5000% | [50.0000%, 75.0000%] |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism v0.1.1 (T=1) | 64 / 32 | 44 / 1 / 19 | 68.7500% | 69.5312% | [56.2500%, 81.2500%] |


##### 双座明细

| 模型 | 对手 | 本模型座位 | 局数 | 胜 / 平 / 负 | 得分率 | 局均VP（模型 / 对手） |
| --- | --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) | Prism v0.1.1 (T=1) | 先手 P0 | 32 | 17 / 0 / 15 | 53.1250% | 14.250 / 13.844 |
| Prism Balance v0.1.0 (T=1) | Prism v0.1.1 (T=1) | 后手 P1 | 32 | 23 / 0 / 9 | 71.8750% | 15.031 / 12.812 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism v0.1.1 (T=1) | 先手 P0 | 32 | 18 / 0 / 14 | 56.2500% | 13.625 / 13.625 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism v0.1.1 (T=1) | 后手 P1 | 32 | 22 / 0 / 10 | 68.7500% | 14.781 / 13.281 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism v0.1.1 (T=1) | 先手 P0 | 32 | 22 / 0 / 10 | 68.7500% | 15.062 / 13.250 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism v0.1.1 (T=1) | 后手 P1 | 32 | 22 / 1 / 9 | 70.3125% | 14.906 / 13.281 |


##### 对局节奏与风格

| 模型 / 对手 | 局均步数 | 决策轮：均值 / 最短 / 中位 / 最长 | 轮标准差 | Main轮均值 | 终局绝对分差 | 分差≤2 | 总VP AUC24 | 20 Main内8VP |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) / Prism v0.1.1 (T=1) | 53.406 | 26.703 / 23 / 26.5 / 31 | 1.800 | 26.703 | 3.406 | 37.50% | 0.21155 | 31.2500% |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) / Prism v0.1.1 (T=1) | 53.422 | 26.719 / 22 / 27.0 / 32 | 1.736 | 26.703 | 3.906 | 28.12% | 0.21740 | 40.6250% |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) / Prism v0.1.1 (T=1) | 52.781 | 26.391 / 21 / 26.0 / 30 | 1.925 | 26.391 | 3.812 | 28.12% | 0.22214 | 40.6250% |


总VP AUC24/20 Main列为被测玩家；短于24自身Main的AUC按终局分补足固定窗口。legacy决策轮=ceil(全动作步数/2)，含贵族选择；Main轮排除贵族选择。本表总VP/大牌轨迹是描述性指标；M62九门使用独立building画像。

##### 双方得分、购卡、折扣、贵族与预留

| 个人指标：模型 / 对手 | Prism Balance v0.1.0 (T=1) 对阵 Prism v0.1.1 (T=1) | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.1 (T=1) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.1 (T=1) |
| --- | --- | --- | --- |
| 局均最终VP | 14.6406 / 13.3281 | 14.2031 / 13.4531 | 14.9844 / 13.2656 |
| VP / 自身决策（含贵族选择） | 0.5483 / 0.4991 | 0.5319 / 0.5035 | 0.5678 / 0.5027 |
| VP / 自身Main | 0.5483 / 0.4991 | 0.5319 / 0.5038 | 0.5678 / 0.5027 |
| VP / 全局步数 | 0.2741 / 0.2496 | 0.2659 / 0.2518 | 0.2839 / 0.2513 |
| 局均永久折扣 / 购卡 | 11.9531 / 12.1250 | 11.3594 / 12.1562 | 11.7344 / 11.9688 |
| 局均贵族数 | 0.6094 / 0.3594 | 0.2656 / 0.4531 | 0.4531 / 0.4688 |
| 局均预留获取 | 3.1406 / 2.6250 | 3.3594 / 2.8125 | 2.7344 / 2.7500 |
| 局均预留买回 | 1.2812 / 0.9062 | 1.2812 / 1.1875 | 1.2344 / 1.1250 |
| 终局未买回预留 | 1.8594 / 1.7188 | 2.0781 / 1.6250 | 1.5000 / 1.6250 |
| 获得贵族的对局比例 | 53.125% / 31.250% | 25.000% / 42.188% | 35.938% / 37.500% |
| 预留买回 / 获取 | 40.796% / 34.524% | 38.140% / 42.222% | 45.143% / 40.909% |
| 局均购入 0 VP卡 | 6.0312 / 6.3750 | 5.2500 / 6.3906 | 5.5938 / 6.2812 |
| 局均购入 1 VP卡 | 2.3906 / 2.0625 | 2.3125 / 2.2656 | 2.2500 / 2.2969 |
| 局均购入 2 VP卡 | 1.6875 / 1.9375 | 1.8125 / 1.9219 | 1.9062 / 1.8438 |
| 局均购入 3 VP卡 | 0.7031 / 0.8906 | 0.8906 / 0.6406 | 0.8438 / 0.6406 |
| 局均购入 4 VP卡 | 0.7656 / 0.6562 | 0.6719 / 0.6250 | 0.6719 / 0.5781 |
| 局均购入 5 VP卡 | 0.3750 / 0.2031 | 0.4219 / 0.3125 | 0.4688 / 0.3281 |
| 局均 白 折扣 | 2.3750 / 2.4531 | 2.3125 / 2.2188 | 2.3906 / 2.2500 |
| 局均 蓝 折扣 | 2.0781 / 2.5156 | 2.0312 / 2.4219 | 2.0000 / 2.5156 |
| 局均 绿 折扣 | 2.6250 / 2.2344 | 2.3750 / 2.6406 | 2.4062 / 2.5312 |
| 局均 红 折扣 | 2.5938 / 2.5781 | 2.4688 / 2.5625 | 2.4688 / 2.5312 |
| 局均 黑 折扣 | 2.2812 / 2.3438 | 2.1719 / 2.3125 | 2.4688 / 2.1406 |


##### 全部七类动作

| 个人指标：模型 / 对手 | Prism Balance v0.1.0 (T=1) 对阵 Prism v0.1.1 (T=1) | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.1 (T=1) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.1 (T=1) |
| --- | --- | --- | --- |
| 买市场 次数 | 683 / 718 | 645 / 702 | 672 / 694 |
| 买市场 占自身全部决策 | 39.965% / 42.013% | 37.741% / 41.053% | 39.787% / 41.089% |
| 买预留 次数 | 82 / 58 | 82 / 76 | 79 / 72 |
| 买预留 占自身全部决策 | 4.798% / 3.394% | 4.798% / 4.444% | 4.677% / 4.263% |
| 取宝石 次数 | 743 / 765 | 767 / 751 | 763 / 747 |
| 取宝石 占自身全部决策 | 43.476% / 44.763% | 44.880% / 43.918% | 45.175% / 44.227% |
| 预留市场 次数 | 201 / 168 | 215 / 180 | 175 / 175 |
| 预留市场 占自身全部决策 | 11.761% / 9.830% | 12.580% / 10.526% | 10.361% / 10.361% |
| 预留牌堆 次数 | 0 / 0 | 0 / 0 | 0 / 1 |
| 预留牌堆 占自身全部决策 | 0.000% / 0.000% | 0.000% / 0.000% | 0.000% / 0.059% |
| 选贵族 次数 | 0 / 0 | 0 / 1 | 0 / 0 |
| 选贵族 占自身全部决策 | 0.000% / 0.000% | 0.000% / 0.058% | 0.000% / 0.000% |
| 跳过 次数 | 0 / 0 | 0 / 0 | 0 / 0 |
| 跳过 占自身全部决策 | 0.000% / 0.000% | 0.000% / 0.000% | 0.000% / 0.000% |


##### 实测计时

| 模型 / 对手 | 进程耗时累计s | 单局均值s | 单局P95s | 决策 / 推理延迟 |
| --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) / Prism v0.1.1 (T=1) | 21.555 | 0.3368 | 0.4513 | NOT_MEASURED / NOT_MEASURED |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) / Prism v0.1.1 (T=1) | 21.112 | 0.3299 | 0.4707 | NOT_MEASURED / NOT_MEASURED |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) / Prism v0.1.1 (T=1) | 21.224 | 0.3316 | 0.5081 | NOT_MEASURED / NOT_MEASURED |


单局时钟包括程序启动、比赛、验核和输出；累计单局秒数含并行重叠，不等于整批墙钟。未记录逐决策/推理延迟，不能填0或由单局时间推算。

#### 大牌购入时点与分段得分（双方个人指标）

| 个人指标：模型 / 对手 | Prism Balance v0.1.0 (T=1) 对阵 Prism v0.1.1 (T=1) | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.1 (T=1) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.1 (T=1) |
| --- | --- | --- | --- |
| 24 Main 总VP AUC（描述性；非M62奖励） | 0.2115 / 0.1827 | 0.2174 / 0.1863 | 0.2221 / 0.1859 |
| 24 Main 大牌印刷VP AUC（描述性；非M62门） | 0.0791 / 0.0610 | 0.0820 / 0.0546 | 0.0831 / 0.0580 |
| 终局3～5VP牌印刷分合计 | 7.0469 / 6.3125 | 7.4688 / 5.9844 | 7.5625 / 5.8750 |
| 前24自身Main购入3～5VP牌数 | 1.3750 / 1.1719 | 1.3750 / 0.9688 | 1.3750 / 1.0938 |
| 首张3～5VP牌 自身Main（仅买到的局） | 19.0484 / 19.7049 | 18.5397 / 19.9636 | 18.7778 / 19.7368 |
| 首张3～5VP牌 覆盖局数 / 总局数（双方） | 62/64 ; 61/64 | 63/64 ; 55/64 | 63/64 ; 57/64 |
| 首张4～5VP牌 自身Main（仅买到的局） | 20.8889 / 21.3409 | 20.7000 / 22.0652 | 20.5918 / 21.5319 |
| 首张4～5VP牌 覆盖局数 / 总局数（双方） | 54/64 ; 44/64 | 50/64 ; 46/64 | 49/64 ; 47/64 |
| 自身Main 8 后局均总VP | 0.7188 / 0.4844 | 0.7344 / 0.4688 | 0.8438 / 0.6250 |
| 自身Main 8 后局均大牌印刷VP | 0.0000 / 0.0000 | 0.0000 / 0.0000 | 0.0938 / 0.0000 |
| 自身Main 8 实际达到局数（双方） | 64 / 64 | 64 / 64 | 64 / 64 |
| 自身Main 12 后局均总VP | 1.8125 / 1.3594 | 1.8594 / 1.5625 | 1.9219 / 1.5156 |
| 自身Main 12 后局均大牌印刷VP | 0.2656 / 0.0938 | 0.2500 / 0.1875 | 0.3125 / 0.0938 |
| 自身Main 12 实际达到局数（双方） | 64 / 64 | 64 / 64 | 64 / 64 |
| 自身Main 16 后局均总VP | 3.4062 / 3.2656 | 3.8125 / 3.0625 | 3.8906 / 3.0312 |
| 自身Main 16 后局均大牌印刷VP | 0.8125 / 0.7500 | 1.0312 / 0.4844 | 1.1562 / 0.5938 |
| 自身Main 16 实际达到局数（双方） | 64 / 64 | 64 / 64 | 64 / 64 |
| 自身Main 20 后局均总VP | 6.5625 / 5.6250 | 6.7812 / 5.9844 | 6.8438 / 5.7031 |
| 自身Main 20 后局均大牌印刷VP | 2.9531 / 2.0938 | 2.9219 / 2.1406 | 2.8594 / 2.1875 |
| 自身Main 20 实际达到局数（双方） | 64 / 64 | 64 / 64 | 64 / 64 |
| 自身Main 24 后局均总VP | 11.1094 / 9.3906 | 10.6250 / 9.4844 | 10.9062 / 9.5312 |
| 自身Main 24 后局均大牌印刷VP | 5.3281 / 4.2031 | 5.2031 / 3.5938 | 5.1406 / 4.0938 |
| 自身Main 24 实际达到局数（双方） | 62 / 62 | 61 / 61 | 62 / 62 |


每格为模型 / 对手。自身Main含购卡/取宝石/预留/跳过，不含贵族选择；贵族分计入前一个Main。短局在后续固定检查点用其终局分补足，并列实际达到该Main的局数。大牌仅含购入3～5VP卡的印刷VP，排除贵族；AUC按15VP截断、固定24分母。首牌时点只对买到的局取均值，必须连同覆盖率解读，不能单凭均值认定更快。

#### 基建投资与后续兑现（双方完整画像）

| 个人指标（被测模型 / 对手） | Prism Balance v0.1.0 (T=1) 对阵 Prism v0.1.1 (T=1) | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.1 (T=1) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.1 (T=1) |
| --- | --- | --- | --- |
| building效用（归一化0..1，reward代理） | 0.458984 / 0.495443 | 0.452474 / 0.484375 | 0.456380 / 0.475911 |
| 早期bonus AUC12（原始永久折扣个数；非reward） | 1.904948 / 1.973958 | 1.925781 / 2.023438 | 1.919271 / 1.977865 |
| 真实折扣适用使用单位 / 局（全局cap24） | 11.015625 / 11.890625 | 10.859375 / 11.625000 | 10.953125 / 11.421875 |
| cap3/投资后、全局cap前使用单位 / 局 | 11.015625 / 11.890625 | 10.859375 / 11.625000 | 10.953125 / 11.421875 |
| 未截断真实折扣使用单位 / 局 | 16.953125 / 18.328125 | 16.406250 / 18.140625 | 16.593750 / 18.031250 |
| 前12Main真实购卡 / 局 | 4.390625 / 4.546875 | 4.406250 / 4.578125 | 4.375000 / 4.500000 |
| 早期≤1VP投资 / 局 | 3.921875 / 4.218750 | 3.953125 / 4.109375 | 3.937500 / 4.015625 |
| 兑现投资 / 局 | 3.890625 / 4.187500 | 3.906250 / 4.109375 | 3.906250 / 4.015625 |
| 未兑现投资 / 局 | 0.031250 / 0.031250 | 0.046875 / 0.000000 | 0.031250 / 0.000000 |
| 观察窗口删失投资 / 局 | 0.062500 / 0.015625 | 0.031250 / 0.046875 | 0.046875 / 0.015625 |
| 未兑现且删失投资 / 局 | 0.000000 / 0.000000 | 0.000000 / 0.000000 | 0.000000 / 0.000000 |
| Main13..24真实购卡印刷VP / 局 | 8.359375 / 7.562500 | 8.343750 / 7.265625 | 8.281250 / 7.453125 |
| Main13..24真实观察Main / 局 | 11.968750 / 11.968750 | 11.937500 / 11.937500 | 11.906250 / 11.906250 |
| Main25..32真实得分购卡印刷VP / 局 | 2.640625 / 3.328125 | 3.203125 / 3.265625 | 3.421875 / 2.890625 |
| Main25..32真实观察Main / 局 | 2.734375 / 2.734375 | 2.765625 / 2.765625 | 2.484375 / 2.484375 |
| Main25..32印刷VP / 真实观察Main（总分母） | 0.965714 / 1.217143 | 1.158192 / 1.180791 | 1.377358 / 1.163522 |
| 投资兑现 / 投资总数 | 99.2032% / 99.2593% | 98.8142% / 100.0000% | 99.2063% / 100.0000% |
| 未兑现 / 投资总数 | 0.7968% / 0.7407% | 1.1858% / 0.0000% | 0.7937% / 0.0000% |
| 删失 / 投资总数 | 1.5936% / 0.3704% | 0.7905% / 1.1407% | 1.1905% / 0.3891% |
| 短于12Main对局比例 | 0.0000% / 0.0000% | 0.0000% / 0.0000% | 0.0000% / 0.0000% |
| 未达24Main对局比例 | 3.1250% / 3.1250% | 4.6875% / 4.6875% | 3.1250% / 3.1250% |
| 未达32Main对局比例 | 100.0000% / 100.0000% | 100.0000% / 100.0000% | 100.0000% / 100.0000% |


每格是被测模型 / 对手，包含全部对局、早败和未兑现投资。奖励不padding；AUC12短局终局折扣保持仅作描述。

| 被测玩家 | 对手 | 本模型物理座位 | 局数 | 效用（模型/对手） | AUC12折扣（模型/对手） |
| --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) | Prism v0.1.1 (T=1) | 先手 P0 | 32 | 0.472656 / 0.496094 | 1.963542 / 1.984375 |
| Prism Balance v0.1.0 (T=1) | Prism v0.1.1 (T=1) | 后手 P1 | 32 | 0.445312 / 0.494792 | 1.846354 / 1.963542 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism v0.1.1 (T=1) | 先手 P0 | 32 | 0.458333 / 0.483073 | 1.937500 / 2.033854 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism v0.1.1 (T=1) | 后手 P1 | 32 | 0.446615 / 0.485677 | 1.914062 / 2.013021 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism v0.1.1 (T=1) | 先手 P0 | 32 | 0.450521 / 0.475260 | 1.927083 / 1.971354 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism v0.1.1 (T=1) | 后手 P1 | 32 | 0.462240 / 0.476562 | 1.911458 / 1.984375 |


#### Prism v0.1.0 (greedy)：完整双方数据

“模型”列是被测玩家；对手列注明动作模式。个人指标每格为“被测模型 / 对手”。节奏是该模型对阵该对手的整局指标。纯胜率=胜/局数，得分率=(胜+0.5平)/局数。

| 模型（T=1） | 对手 | 局数 / 双座种子数 | 胜 / 平 / 负 | 纯胜率 | 得分率 | 描述性配对95%区间 |
| --- | --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) | Prism v0.1.0 (greedy) | 64 / 32 | 47 / 1 / 16 | 73.4375% | 74.2188% | [63.2812%, 84.3750%] |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism v0.1.0 (greedy) | 64 / 32 | 48 / 0 / 16 | 75.0000% | 75.0000% | [62.5000%, 85.9375%] |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism v0.1.0 (greedy) | 64 / 32 | 48 / 1 / 15 | 75.0000% | 75.7812% | [64.8438%, 85.9375%] |


##### 双座明细

| 模型 | 对手 | 本模型座位 | 局数 | 胜 / 平 / 负 | 得分率 | 局均VP（模型 / 对手） |
| --- | --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) | Prism v0.1.0 (greedy) | 先手 P0 | 32 | 26 / 0 / 6 | 81.2500% | 15.562 / 12.375 |
| Prism Balance v0.1.0 (T=1) | Prism v0.1.0 (greedy) | 后手 P1 | 32 | 21 / 1 / 10 | 67.1875% | 14.969 / 13.125 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism v0.1.0 (greedy) | 先手 P0 | 32 | 26 / 0 / 6 | 81.2500% | 15.188 / 12.375 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism v0.1.0 (greedy) | 后手 P1 | 32 | 22 / 0 / 10 | 68.7500% | 14.875 / 12.812 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism v0.1.0 (greedy) | 先手 P0 | 32 | 26 / 0 / 6 | 81.2500% | 15.500 / 12.656 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism v0.1.0 (greedy) | 后手 P1 | 32 | 22 / 1 / 9 | 70.3125% | 15.094 / 13.062 |


##### 对局节奏与风格

| 模型 / 对手 | 局均步数 | 决策轮：均值 / 最短 / 中位 / 最长 | 轮标准差 | Main轮均值 | 终局绝对分差 | 分差≤2 | 总VP AUC24 | 20 Main内8VP |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) / Prism v0.1.0 (greedy) | 53.125 | 26.562 / 22 / 27.0 / 31 | 1.775 | 26.562 | 3.828 | 29.69% | 0.23568 | 48.4375% |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) / Prism v0.1.0 (greedy) | 52.531 | 26.266 / 22 / 26.0 / 32 | 1.814 | 26.266 | 4.031 | 31.25% | 0.22335 | 34.3750% |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) / Prism v0.1.0 (greedy) | 52.891 | 26.453 / 21 / 27.0 / 31 | 1.767 | 26.438 | 3.781 | 31.25% | 0.23733 | 53.1250% |


总VP AUC24/20 Main列为被测玩家；短于24自身Main的AUC按终局分补足固定窗口。legacy决策轮=ceil(全动作步数/2)，含贵族选择；Main轮排除贵族选择。本表总VP/大牌轨迹是描述性指标；M62九门使用独立building画像。

##### 双方得分、购卡、折扣、贵族与预留

| 个人指标：模型 / 对手 | Prism Balance v0.1.0 (T=1) 对阵 Prism v0.1.0 (greedy) | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.0 (greedy) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.0 (greedy) |
| --- | --- | --- | --- |
| 局均最终VP | 15.2656 / 12.7500 | 15.0312 / 12.5938 | 15.2969 / 12.8594 |
| VP / 自身决策（含贵族选择） | 0.5747 / 0.4800 | 0.5723 / 0.4795 | 0.5786 / 0.4861 |
| VP / 自身Main | 0.5747 / 0.4800 | 0.5723 / 0.4795 | 0.5786 / 0.4864 |
| VP / 全局步数 | 0.2874 / 0.2400 | 0.2861 / 0.2397 | 0.2892 / 0.2431 |
| 局均永久折扣 / 购卡 | 11.6719 / 13.4219 | 11.8594 / 13.7656 | 11.5156 / 13.2188 |
| 局均贵族数 | 0.4688 / 0.6719 | 0.4844 / 0.6875 | 0.3750 / 0.6875 |
| 局均预留获取 | 2.5938 / 2.0000 | 2.7500 / 1.5156 | 2.4531 / 1.9688 |
| 局均预留买回 | 0.9531 / 1.0469 | 1.1094 / 0.7344 | 0.9219 / 0.9844 |
| 终局未买回预留 | 1.6406 / 0.9531 | 1.6406 / 0.7812 | 1.5312 / 0.9844 |
| 获得贵族的对局比例 | 39.062% / 51.562% | 42.188% / 50.000% | 32.812% / 56.250% |
| 预留买回 / 获取 | 36.747% / 52.344% | 40.341% / 48.454% | 37.580% / 50.000% |
| 局均购入 0 VP卡 | 5.5625 / 7.2969 | 5.9375 / 7.8438 | 5.2969 / 7.3594 |
| 局均购入 1 VP卡 | 2.0625 / 3.0156 | 1.9219 / 2.9531 | 2.1250 / 2.7188 |
| 局均购入 2 VP卡 | 2.0000 / 2.0625 | 1.9375 / 1.8594 | 1.9062 / 1.9531 |
| 局均购入 3 VP卡 | 0.7656 / 0.6719 | 0.8906 / 0.6562 | 0.9062 / 0.6719 |
| 局均购入 4 VP卡 | 0.9062 / 0.2969 | 0.7500 / 0.3750 | 0.8906 / 0.4219 |
| 局均购入 5 VP卡 | 0.3750 / 0.0781 | 0.4219 / 0.0781 | 0.3906 / 0.0938 |
| 局均 白 折扣 | 2.3125 / 2.5312 | 2.2188 / 2.7656 | 2.2031 / 2.5000 |
| 局均 蓝 折扣 | 2.0625 / 2.7969 | 2.2188 / 2.6094 | 2.0156 / 2.6719 |
| 局均 绿 折扣 | 2.4375 / 2.7969 | 2.3281 / 2.8281 | 2.5156 / 2.7344 |
| 局均 红 折扣 | 2.5000 / 2.7344 | 2.7344 / 2.7812 | 2.5625 / 2.7188 |
| 局均 黑 折扣 | 2.3594 / 2.5625 | 2.3594 / 2.7812 | 2.2188 / 2.5938 |


##### 全部七类动作

| 个人指标：模型 / 对手 | Prism Balance v0.1.0 (T=1) 对阵 Prism v0.1.0 (greedy) | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.0 (greedy) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.0 (greedy) |
| --- | --- | --- | --- |
| 买市场 次数 | 686 / 792 | 688 / 834 | 678 / 783 |
| 买市场 占自身全部决策 | 40.353% / 46.588% | 40.928% / 49.613% | 40.071% / 46.249% |
| 买预留 次数 | 61 / 67 | 71 / 47 | 59 / 63 |
| 买预留 占自身全部决策 | 3.588% / 3.941% | 4.224% / 2.796% | 3.487% / 3.721% |
| 取宝石 次数 | 787 / 713 | 746 / 703 | 798 / 720 |
| 取宝石 占自身全部决策 | 46.294% / 41.941% | 44.378% / 41.820% | 47.163% / 42.528% |
| 预留市场 次数 | 166 / 128 | 176 / 95 | 157 / 125 |
| 预留市场 占自身全部决策 | 9.765% / 7.529% | 10.470% / 5.651% | 9.279% / 7.383% |
| 预留牌堆 次数 | 0 / 0 | 0 / 2 | 0 / 1 |
| 预留牌堆 占自身全部决策 | 0.000% / 0.000% | 0.000% / 0.119% | 0.000% / 0.059% |
| 选贵族 次数 | 0 / 0 | 0 / 0 | 0 / 1 |
| 选贵族 占自身全部决策 | 0.000% / 0.000% | 0.000% / 0.000% | 0.000% / 0.059% |
| 跳过 次数 | 0 / 0 | 0 / 0 | 0 / 0 |
| 跳过 占自身全部决策 | 0.000% / 0.000% | 0.000% / 0.000% | 0.000% / 0.000% |


##### 实测计时

| 模型 / 对手 | 进程耗时累计s | 单局均值s | 单局P95s | 决策 / 推理延迟 |
| --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) / Prism v0.1.0 (greedy) | 22.602 | 0.3532 | 0.5453 | NOT_MEASURED / NOT_MEASURED |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) / Prism v0.1.0 (greedy) | 22.575 | 0.3527 | 0.5341 | NOT_MEASURED / NOT_MEASURED |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) / Prism v0.1.0 (greedy) | 21.730 | 0.3395 | 0.4922 | NOT_MEASURED / NOT_MEASURED |


单局时钟包括程序启动、比赛、验核和输出；累计单局秒数含并行重叠，不等于整批墙钟。未记录逐决策/推理延迟，不能填0或由单局时间推算。

#### 大牌购入时点与分段得分（双方个人指标）

| 个人指标：模型 / 对手 | Prism Balance v0.1.0 (T=1) 对阵 Prism v0.1.0 (greedy) | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.0 (greedy) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.0 (greedy) |
| --- | --- | --- | --- |
| 24 Main 总VP AUC（描述性；非M62奖励） | 0.2357 / 0.1807 | 0.2234 / 0.1718 | 0.2373 / 0.1710 |
| 24 Main 大牌印刷VP AUC（描述性；非M62门） | 0.0978 / 0.0378 | 0.0918 / 0.0339 | 0.1009 / 0.0352 |
| 终局3～5VP牌印刷分合计 | 7.7969 / 3.5938 | 7.7812 / 3.8594 | 8.2344 / 4.1719 |
| 前24自身Main购入3～5VP牌数 | 1.4844 / 0.7812 | 1.4844 / 0.7969 | 1.6250 / 0.7812 |
| 首张3～5VP牌 自身Main（仅买到的局） | 17.6613 / 20.2609 | 17.9355 / 21.0208 | 17.6825 / 21.5000 |
| 首张3～5VP牌 覆盖局数 / 总局数（双方） | 62/64 ; 46/64 | 62/64 ; 48/64 | 63/64 ; 52/64 |
| 首张4～5VP牌 自身Main（仅买到的局） | 19.7407 / 21.7500 | 20.4464 / 22.4815 | 19.8704 / 21.5385 |
| 首张4～5VP牌 覆盖局数 / 总局数（双方） | 54/64 ; 20/64 | 56/64 ; 27/64 | 54/64 ; 26/64 |
| 自身Main 8 后局均总VP | 1.0469 / 0.6719 | 0.8750 / 0.6719 | 0.8281 / 0.7188 |
| 自身Main 8 后局均大牌印刷VP | 0.0938 / 0.0000 | 0.0469 / 0.0000 | 0.0469 / 0.0000 |
| 自身Main 8 实际达到局数（双方） | 64 / 64 | 64 / 64 | 64 / 64 |
| 自身Main 12 后局均总VP | 2.2969 / 1.7188 | 1.9219 / 1.5781 | 2.2031 / 1.4531 |
| 自身Main 12 后局均大牌印刷VP | 0.5781 / 0.0469 | 0.4062 / 0.0469 | 0.5781 / 0.0469 |
| 自身Main 12 实际达到局数（双方） | 64 / 64 | 64 / 64 | 64 / 64 |
| 自身Main 16 后局均总VP | 4.1406 / 2.9531 | 3.8750 / 2.6250 | 4.3281 / 2.5469 |
| 自身Main 16 后局均大牌印刷VP | 1.5000 / 0.2969 | 1.3125 / 0.0938 | 1.5156 / 0.1562 |
| 自身Main 16 实际达到局数（双方） | 64 / 64 | 64 / 64 | 64 / 64 |
| 自身Main 20 后局均总VP | 7.3438 / 5.4688 | 6.7812 / 5.2344 | 7.2188 / 5.2344 |
| 自身Main 20 后局均大牌印刷VP | 3.5000 / 1.5625 | 3.1719 / 1.2344 | 3.3438 / 1.2812 |
| 自身Main 20 实际达到局数（双方） | 64 / 64 | 64 / 64 | 64 / 64 |
| 自身Main 24 后局均总VP | 11.1250 / 9.4375 | 11.1094 / 9.2031 | 11.5938 / 9.0469 |
| 自身Main 24 后局均大牌印刷VP | 5.6406 / 2.6562 | 5.6250 / 2.7656 | 6.0781 / 2.7812 |
| 自身Main 24 实际达到局数（双方） | 62 / 62 | 60 / 60 | 61 / 61 |


每格为模型 / 对手。自身Main含购卡/取宝石/预留/跳过，不含贵族选择；贵族分计入前一个Main。短局在后续固定检查点用其终局分补足，并列实际达到该Main的局数。大牌仅含购入3～5VP卡的印刷VP，排除贵族；AUC按15VP截断、固定24分母。首牌时点只对买到的局取均值，必须连同覆盖率解读，不能单凭均值认定更快。

#### 基建投资与后续兑现（双方完整画像）

| 个人指标（被测模型 / 对手） | Prism Balance v0.1.0 (T=1) 对阵 Prism v0.1.0 (greedy) | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.0 (greedy) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.0 (greedy) |
| --- | --- | --- | --- |
| building效用（归一化0..1，reward代理） | 0.437500 / 0.529297 | 0.453125 / 0.541667 | 0.445964 / 0.521484 |
| 早期bonus AUC12（原始永久折扣个数；非reward） | 1.904948 / 2.085938 | 1.934896 / 2.089844 | 1.946615 / 2.072917 |
| 真实折扣适用使用单位 / 局（全局cap24） | 10.500000 / 12.703125 | 10.875000 / 13.000000 | 10.703125 / 12.515625 |
| cap3/投资后、全局cap前使用单位 / 局 | 10.500000 / 12.703125 | 10.875000 / 13.000000 | 10.703125 / 12.515625 |
| 未截断真实折扣使用单位 / 局 | 15.921875 / 21.531250 | 16.484375 / 22.734375 | 15.843750 / 21.171875 |
| 前12Main真实购卡 / 局 | 4.390625 / 4.812500 | 4.359375 / 4.890625 | 4.500000 / 4.687500 |
| 早期≤1VP投资 / 局 | 3.734375 / 4.375000 | 3.828125 / 4.484375 | 3.890625 / 4.328125 |
| 兑现投资 / 局 | 3.734375 / 4.375000 | 3.796875 / 4.484375 | 3.890625 / 4.312500 |
| 未兑现投资 / 局 | 0.000000 / 0.000000 | 0.031250 / 0.000000 | 0.000000 / 0.015625 |
| 观察窗口删失投资 / 局 | 0.062500 / 0.031250 | 0.031250 / 0.062500 | 0.031250 / 0.000000 |
| 未兑现且删失投资 / 局 | 0.000000 / 0.000000 | 0.000000 / 0.000000 | 0.000000 / 0.000000 |
| Main13..24真实购卡印刷VP / 局 | 8.218750 / 6.734375 | 8.437500 / 6.593750 | 8.875000 / 6.656250 |
| Main13..24真实观察Main / 局 | 11.953125 / 11.953125 | 11.906250 / 11.906250 | 11.906250 / 11.906250 |
| Main25..32真实得分购卡印刷VP / 局 | 3.343750 / 2.281250 | 3.218750 / 2.359375 | 3.093750 / 2.687500 |
| Main25..32真实观察Main / 局 | 2.609375 / 2.609375 | 2.359375 / 2.359375 | 2.531250 / 2.531250 |
| Main25..32印刷VP / 真实观察Main（总分母） | 1.281437 / 0.874251 | 1.364238 / 1.000000 | 1.222222 / 1.061728 |
| 投资兑现 / 投资总数 | 100.0000% / 100.0000% | 99.1837% / 100.0000% | 100.0000% / 99.6390% |
| 未兑现 / 投资总数 | 0.0000% / 0.0000% | 0.8163% / 0.0000% | 0.0000% / 0.3610% |
| 删失 / 投资总数 | 1.6736% / 0.7143% | 0.8163% / 1.3937% | 0.8032% / 0.0000% |
| 短于12Main对局比例 | 0.0000% / 0.0000% | 0.0000% / 0.0000% | 0.0000% / 0.0000% |
| 未达24Main对局比例 | 3.1250% / 3.1250% | 6.2500% / 6.2500% | 4.6875% / 4.6875% |
| 未达32Main对局比例 | 100.0000% / 100.0000% | 98.4375% / 98.4375% | 100.0000% / 100.0000% |


每格是被测模型 / 对手，包含全部对局、早败和未兑现投资。奖励不padding；AUC12短局终局折扣保持仅作描述。

| 被测玩家 | 对手 | 本模型物理座位 | 局数 | 效用（模型/对手） | AUC12折扣（模型/对手） |
| --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) | Prism v0.1.0 (greedy) | 先手 P0 | 32 | 0.464844 / 0.533854 | 2.005208 / 2.075521 |
| Prism Balance v0.1.0 (T=1) | Prism v0.1.0 (greedy) | 后手 P1 | 32 | 0.410156 / 0.524740 | 1.804688 / 2.096354 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism v0.1.0 (greedy) | 先手 P0 | 32 | 0.484375 / 0.549479 | 2.041667 / 2.085938 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism v0.1.0 (greedy) | 后手 P1 | 32 | 0.421875 / 0.533854 | 1.828125 / 2.093750 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism v0.1.0 (greedy) | 先手 P0 | 32 | 0.464844 / 0.511719 | 2.023438 / 2.065104 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism v0.1.0 (greedy) | 后手 P1 | 32 | 0.427083 / 0.531250 | 1.869792 / 2.080729 |


单局时钟含启动、比赛、验证和输出；累计单局秒含并行重叠。legacy决策轮=ceil(全plies/2)，Main排除choose_noble。每组纯胜/半平CI仅描述，不增加否决门；逐决策 / 推理 **NOT_MEASURED / NOT_MEASURED**。

| 字段 | 原始记录 |
| --- | --- |
| audit_metrics_wall_seconds | 7.717648196034133 |
| building_metrics_sha256 | b34ef201f27cbff74a0b0bc5e5da11f60703a47a91075cbc68c0dadd53699603 |
| clock_scope | stage dispatch wall and subsequent saved-replay metric wall; no per-inference clock |
| dispatch_wall_seconds | 163.10918568214402 |
| games | 576 |
| match_details_sha256 | 104091ede8d2d39807b1c28de17b7157f3af171903dee318b57105b91aca51fb |
| plan_sha256 | 953128f3d23cb60f9dac21a78190a4b804ef8bde57c2d14b6465dfebaa96aac2 |
| source_ledger_sha256 | 4ee4b37981654ad40df9e1a2e3c164292bafc3657bd27720fbc20d88a4de8153 |
| style_metrics_sha256 | 4e15065aea77ef9ce2a18a1037b9ec638b9568ab46283a4120ee2c9c6586155b |


### 独立验收

| 被测玩家（T=1） | 固定对手 / 模式 | 局数 / 双座 seed 块 | W / D / L | 纯胜率 | 纯胜率配对95% CI | 半平得分率 | 半平得分率配对95% CI |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 512 / 256 | 365 / 2 / 145 | 71.2891% | [67.3828%, 75.0000%] | 71.4844% | [67.6758%, 75.1953%] |
| Prism Balance v0.1.0 (T=1) | Prism v0.1.1 (T=1) | 512 / 256 | 338 / 3 / 171 | 66.0156% | [61.9141%, 69.9219%] | 66.3086% | [62.2070%, 70.2148%] |
| Prism Balance v0.1.0 (T=1) | Prism v0.1.0 (greedy) | 512 / 256 | 377 / 1 / 134 | 73.6328% | [69.7266%, 77.3438%] | 73.7305% | [69.9219%, 77.5391%] |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism Alpha v0.1.4 (T=1) | 1024 / 512 | 557 / 12 / 455 | 54.3945% | [51.3672%, 57.4219%] | 54.9805% | [51.9531%, 58.0566%] |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism Balance v0.1.0 (T=1) | 1024 / 512 | 523 / 15 / 486 | 51.0742% | [48.0469%, 54.1016%] | 51.8066% | [48.8281%, 54.8340%] |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | 1024 / 512 | 487 / 9 / 528 | 47.5586% | [44.4336%, 50.6836%] | 47.9980% | [44.9219%, 51.0742%] |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 512 / 256 | 387 / 2 / 123 | 75.5859% | [71.8750%, 79.2969%] | 75.7812% | [72.0703%, 79.3945%] |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism v0.1.1 (T=1) | 512 / 256 | 331 / 6 / 175 | 64.6484% | [60.5469%, 68.7500%] | 65.2344% | [61.0352%, 69.3359%] |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism v0.1.0 (greedy) | 512 / 256 | 386 / 2 / 124 | 75.3906% | [71.6797%, 79.1016%] | 75.5859% | [71.8750%, 79.2017%] |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism Balance v0.1.0 (T=1) | 1024 / 512 | 528 / 10 / 486 | 51.5625% | [48.6328%, 54.4922%] | 52.0508% | [49.1211%, 55.0293%] |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 512 / 256 | 370 / 1 / 141 | 72.2656% | [68.1641%, 76.1719%] | 72.3633% | [68.3594%, 76.2695%] |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism v0.1.1 (T=1) | 512 / 256 | 340 / 4 / 168 | 66.4062% | [62.1094%, 70.5078%] | 66.7969% | [62.5977%, 70.8008%] |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism v0.1.0 (greedy) | 512 / 256 | 390 / 1 / 121 | 76.1719% | [72.4609%, 79.6875%] | 76.2695% | [72.5586%, 79.8828%] |


#### Heuristic v0.3.1 (greedy; Hello 0.2.9)：完整双方数据

“模型”列是被测玩家；对手列注明动作模式。个人指标每格为“被测模型 / 对手”。节奏是该模型对阵该对手的整局指标。纯胜率=胜/局数，得分率=(胜+0.5平)/局数。

| 模型（T=1） | 对手 | 局数 / 双座种子数 | 胜 / 平 / 负 | 纯胜率 | 得分率 | 描述性配对95%区间 |
| --- | --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 512 / 256 | 365 / 2 / 145 | 71.2891% | 71.4844% | [67.6758%, 75.1953%] |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 512 / 256 | 387 / 2 / 123 | 75.5859% | 75.7812% | [72.0703%, 79.3945%] |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 512 / 256 | 370 / 1 / 141 | 72.2656% | 72.3633% | [68.3594%, 76.2695%] |


##### 双座明细

| 模型 | 对手 | 本模型座位 | 局数 | 胜 / 平 / 负 | 得分率 | 局均VP（模型 / 对手） |
| --- | --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 先手 P0 | 256 | 179 / 1 / 76 | 70.1172% | 15.129 / 12.828 |
| Prism Balance v0.1.0 (T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 后手 P1 | 256 | 186 / 1 / 69 | 72.8516% | 15.137 / 12.727 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 先手 P0 | 256 | 201 / 1 / 54 | 78.7109% | 15.316 / 12.312 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 后手 P1 | 256 | 186 / 1 / 69 | 72.8516% | 15.262 / 12.637 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 先手 P0 | 256 | 181 / 1 / 74 | 70.8984% | 14.988 / 12.734 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 后手 P1 | 256 | 189 / 0 / 67 | 73.8281% | 15.199 / 12.531 |


##### 对局节奏与风格

| 模型 / 对手 | 局均步数 | 决策轮：均值 / 最短 / 中位 / 最长 | 轮标准差 | Main轮均值 | 终局绝对分差 | 分差≤2 | 总VP AUC24 | 20 Main内8VP |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) / Heuristic v0.3.1 (greedy; Hello 0.2.9) | 53.248 | 26.633 / 21 / 27.0 / 32 | 1.881 | 26.615 | 4.180 | 30.08% | 0.22154 | 35.3516% |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) / Heuristic v0.3.1 (greedy; Hello 0.2.9) | 53.057 | 26.537 / 21 / 27.0 / 32 | 1.754 | 26.520 | 4.307 | 25.78% | 0.22435 | 39.4531% |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) / Heuristic v0.3.1 (greedy; Hello 0.2.9) | 52.930 | 26.475 / 21 / 27.0 / 33 | 1.809 | 26.455 | 4.164 | 31.25% | 0.22652 | 39.6484% |


总VP AUC24/20 Main列为被测玩家；短于24自身Main的AUC按终局分补足固定窗口。legacy决策轮=ceil(全动作步数/2)，含贵族选择；Main轮排除贵族选择。本表总VP/大牌轨迹是描述性指标；M62九门使用独立building画像。

##### 双方得分、购卡、折扣、贵族与预留

| 个人指标：模型 / 对手 | Prism Balance v0.1.0 (T=1) 对阵 Heuristic v0.3.1 (greedy; Hello 0.2.9) | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Heuristic v0.3.1 (greedy; Hello 0.2.9) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Heuristic v0.3.1 (greedy; Hello 0.2.9) |
| --- | --- | --- | --- |
| 局均最终VP | 15.1328 / 12.7773 | 15.2891 / 12.4746 | 15.0938 / 12.6328 |
| VP / 自身决策（含贵族选择） | 0.5685 / 0.4798 | 0.5764 / 0.4702 | 0.5705 / 0.4772 |
| VP / 自身Main | 0.5686 / 0.4801 | 0.5765 / 0.4704 | 0.5705 / 0.4775 |
| VP / 全局步数 | 0.2842 / 0.2400 | 0.2882 / 0.2351 | 0.2852 / 0.2387 |
| 局均永久折扣 / 购卡 | 11.7188 / 13.1016 | 11.6074 / 13.0352 | 11.4434 / 13.2188 |
| 局均贵族数 | 0.3926 / 0.6836 | 0.4414 / 0.6445 | 0.3203 / 0.7559 |
| 局均预留获取 | 2.6309 / 2.5117 | 2.7324 / 2.4980 | 2.5156 / 2.4902 |
| 局均预留买回 | 0.9766 / 1.3828 | 1.0859 / 1.3496 | 0.9180 / 1.3496 |
| 终局未买回预留 | 1.6543 / 1.1289 | 1.6465 / 1.1484 | 1.5977 / 1.1406 |
| 获得贵族的对局比例 | 34.375% / 48.633% | 37.695% / 46.094% | 28.516% / 55.078% |
| 预留买回 / 获取 | 37.120% / 55.054% | 39.743% / 54.027% | 36.491% / 54.196% |
| 局均购入 0 VP卡 | 5.6953 / 7.4961 | 5.6289 / 7.4141 | 5.4238 / 7.6211 |
| 局均购入 1 VP卡 | 2.0176 / 2.5527 | 1.9512 / 2.6660 | 1.9160 / 2.6934 |
| 局均购入 2 VP卡 | 1.8574 / 1.6660 | 1.8750 / 1.6660 | 1.9004 / 1.6543 |
| 局均购入 3 VP卡 | 0.8145 / 0.8281 | 0.8086 / 0.7344 | 0.8438 / 0.7461 |
| 局均购入 4 VP卡 | 0.8906 / 0.4355 | 0.8809 / 0.4336 | 0.9121 / 0.3945 |
| 局均购入 5 VP卡 | 0.4434 / 0.1230 | 0.4629 / 0.1211 | 0.4473 / 0.1094 |
| 局均 白 折扣 | 2.4004 / 2.5859 | 2.2910 / 2.5586 | 2.3242 / 2.5742 |
| 局均 蓝 折扣 | 2.2246 / 2.6777 | 2.1543 / 2.7148 | 2.1191 / 2.7109 |
| 局均 绿 折扣 | 2.3359 / 2.6992 | 2.3008 / 2.7051 | 2.3672 / 2.6523 |
| 局均 红 折扣 | 2.3652 / 2.5898 | 2.3711 / 2.5469 | 2.2695 / 2.7285 |
| 局均 黑 折扣 | 2.3926 / 2.5488 | 2.4902 / 2.5098 | 2.3633 / 2.5527 |


##### 全部七类动作

| 个人指标：模型 / 对手 | Prism Balance v0.1.0 (T=1) 对阵 Heuristic v0.3.1 (greedy; Hello 0.2.9) | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Heuristic v0.3.1 (greedy; Hello 0.2.9) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Heuristic v0.3.1 (greedy; Hello 0.2.9) |
| --- | --- | --- | --- |
| 买市场 次数 | 5500 / 6000 | 5387 / 5983 | 5389 / 6077 |
| 买市场 占自身全部决策 | 40.355% / 44.008% | 39.666% / 44.044% | 39.786% / 44.832% |
| 买预留 次数 | 500 / 708 | 556 / 691 | 470 / 691 |
| 买预留 占自身全部决策 | 3.669% / 5.193% | 4.094% / 5.087% | 3.470% / 5.098% |
| 取宝石 次数 | 6280 / 5633 | 6236 / 5625 | 6398 / 5502 |
| 取宝石 占自身全部决策 | 46.078% / 41.316% | 45.917% / 41.409% | 47.235% / 40.590% |
| 预留市场 次数 | 1346 / 1280 | 1399 / 1277 | 1288 / 1271 |
| 预留市场 占自身全部决策 | 9.876% / 9.388% | 10.301% / 9.401% | 9.509% / 9.377% |
| 预留牌堆 次数 | 1 / 6 | 0 / 2 | 0 / 4 |
| 预留牌堆 占自身全部决策 | 0.007% / 0.044% | 0.000% / 0.015% | 0.000% / 0.030% |
| 选贵族 次数 | 2 / 7 | 3 / 6 | 0 / 10 |
| 选贵族 占自身全部决策 | 0.015% / 0.051% | 0.022% / 0.044% | 0.000% / 0.074% |
| 跳过 次数 | 0 / 0 | 0 / 0 | 0 / 0 |
| 跳过 占自身全部决策 | 0.000% / 0.000% | 0.000% / 0.000% | 0.000% / 0.000% |


##### 实测计时

| 模型 / 对手 | 进程耗时累计s | 单局均值s | 单局P95s | 决策 / 推理延迟 |
| --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) / Heuristic v0.3.1 (greedy; Hello 0.2.9) | 108.099 | 0.2111 | 0.3144 | NOT_MEASURED / NOT_MEASURED |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) / Heuristic v0.3.1 (greedy; Hello 0.2.9) | 110.309 | 0.2154 | 0.3314 | NOT_MEASURED / NOT_MEASURED |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) / Heuristic v0.3.1 (greedy; Hello 0.2.9) | 110.721 | 0.2163 | 0.3316 | NOT_MEASURED / NOT_MEASURED |


单局时钟包括程序启动、比赛、验核和输出；累计单局秒数含并行重叠，不等于整批墙钟。未记录逐决策/推理延迟，不能填0或由单局时间推算。

#### 大牌购入时点与分段得分（双方个人指标）

| 个人指标：模型 / 对手 | Prism Balance v0.1.0 (T=1) 对阵 Heuristic v0.3.1 (greedy; Hello 0.2.9) | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Heuristic v0.3.1 (greedy; Hello 0.2.9) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Heuristic v0.3.1 (greedy; Hello 0.2.9) |
| --- | --- | --- | --- |
| 24 Main 总VP AUC（描述性；非M62奖励） | 0.2215 / 0.1698 | 0.2243 / 0.1675 | 0.2265 / 0.1689 |
| 24 Main 大牌印刷VP AUC（描述性；非M62门） | 0.0901 / 0.0520 | 0.0918 / 0.0476 | 0.0937 / 0.0484 |
| 终局3～5VP牌印刷分合计 | 8.2227 / 4.8418 | 8.2637 / 4.5430 | 8.4160 / 4.3633 |
| 前24自身Main购入3～5VP牌数 | 1.4727 / 0.9648 | 1.5176 / 0.8887 | 1.5703 / 0.8828 |
| 首张3～5VP牌 自身Main（仅买到的局） | 18.2440 / 19.8565 | 18.0398 / 20.0049 | 17.9960 / 19.9399 |
| 首张3～5VP牌 覆盖局数 / 总局数（双方） | 496/512 ; 439/512 | 502/512 ; 410/512 | 499/512 ; 416/512 |
| 首张4～5VP牌 自身Main（仅买到的局） | 19.9622 / 21.1639 | 20.0413 / 21.2281 | 20.0806 / 20.9685 |
| 首张4～5VP牌 覆盖局数 / 总局数（双方） | 423/512 ; 238/512 | 436/512 ; 228/512 | 434/512 ; 222/512 |
| 自身Main 8 后局均总VP | 0.7129 / 0.5137 | 0.7012 / 0.5332 | 0.7031 / 0.4961 |
| 自身Main 8 后局均大牌印刷VP | 0.0234 / 0.0312 | 0.0352 / 0.0312 | 0.0293 / 0.0332 |
| 自身Main 8 实际达到局数（双方） | 512 / 512 | 512 / 512 | 512 / 512 |
| 自身Main 12 后局均总VP | 1.9707 / 1.4355 | 1.9023 / 1.3965 | 2.0098 / 1.4082 |
| 自身Main 12 后局均大牌印刷VP | 0.4102 / 0.2480 | 0.3711 / 0.1875 | 0.4238 / 0.1914 |
| 自身Main 12 实际达到局数（双方） | 512 / 512 | 512 / 512 | 512 / 512 |
| 自身Main 16 后局均总VP | 3.8594 / 2.7812 | 3.9316 / 2.7305 | 3.8848 / 2.8086 |
| 自身Main 16 后局均大牌印刷VP | 1.2266 / 0.6543 | 1.3027 / 0.6289 | 1.2559 / 0.6719 |
| 自身Main 16 实际达到局数（双方） | 512 / 512 | 512 / 512 | 512 / 512 |
| 自身Main 20 后局均总VP | 6.8379 / 5.2363 | 6.9824 / 5.1738 | 7.0078 / 5.1934 |
| 自身Main 20 后局均大牌印刷VP | 3.0742 / 1.7539 | 3.2051 / 1.6641 | 3.2207 / 1.6191 |
| 自身Main 20 实际达到局数（双方） | 512 / 512 | 512 / 512 | 512 / 512 |
| 自身Main 24 后局均总VP | 11.0547 / 9.0527 | 11.2246 / 8.8770 | 11.3145 / 8.9766 |
| 自身Main 24 后局均大牌印刷VP | 5.6504 / 3.3652 | 5.8008 / 3.0879 | 5.9844 / 3.0742 |
| 自身Main 24 实际达到局数（双方） | 490 / 490 | 488 / 488 | 487 / 487 |


每格为模型 / 对手。自身Main含购卡/取宝石/预留/跳过，不含贵族选择；贵族分计入前一个Main。短局在后续固定检查点用其终局分补足，并列实际达到该Main的局数。大牌仅含购入3～5VP卡的印刷VP，排除贵族；AUC按15VP截断、固定24分母。首牌时点只对买到的局取均值，必须连同覆盖率解读，不能单凭均值认定更快。

#### 基建投资与后续兑现（双方完整画像）

| 个人指标（被测模型 / 对手） | Prism Balance v0.1.0 (T=1) 对阵 Heuristic v0.3.1 (greedy; Hello 0.2.9) | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Heuristic v0.3.1 (greedy; Hello 0.2.9) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Heuristic v0.3.1 (greedy; Hello 0.2.9) |
| --- | --- | --- | --- |
| building效用（归一化0..1，reward代理） | 0.461426 / 0.520020 | 0.451497 / 0.516439 | 0.448893 / 0.526611 |
| 早期bonus AUC12（原始永久折扣个数；非reward） | 1.983724 / 2.082520 | 1.977865 / 2.061686 | 1.955078 / 2.092448 |
| 真实折扣适用使用单位 / 局（全局cap24） | 11.074219 / 12.480469 | 10.835938 / 12.394531 | 10.773438 / 12.638672 |
| cap3/投资后、全局cap前使用单位 / 局 | 11.074219 / 12.480469 | 10.835938 / 12.394531 | 10.773438 / 12.638672 |
| 未截断真实折扣使用单位 / 局 | 16.792969 / 21.150391 | 16.406250 / 21.283203 | 16.193359 / 21.710938 |
| 前12Main真实购卡 / 局 | 4.501953 / 4.656250 | 4.441406 / 4.619141 | 4.431641 / 4.708984 |
| 早期≤1VP投资 / 局 | 3.962891 / 4.339844 | 3.906250 / 4.298828 | 3.873047 / 4.386719 |
| 兑现投资 / 局 | 3.933594 / 4.332031 | 3.882812 / 4.287109 | 3.853516 / 4.378906 |
| 未兑现投资 / 局 | 0.029297 / 0.007812 | 0.023438 / 0.011719 | 0.019531 / 0.007812 |
| 观察窗口删失投资 / 局 | 0.027344 / 0.021484 | 0.019531 / 0.025391 | 0.021484 / 0.021484 |
| 未兑现且删失投资 / 局 | 0.000000 / 0.000000 | 0.000000 / 0.000000 | 0.000000 / 0.001953 |
| Main13..24真实购卡印刷VP / 局 | 8.533203 / 6.650391 | 8.671875 / 6.542969 | 8.794922 / 6.542969 |
| Main13..24真实观察Main / 局 | 11.935547 / 11.935547 | 11.945312 / 11.945312 | 11.935547 / 11.935547 |
| Main25..32真实得分购卡印刷VP / 局 | 3.451172 / 2.640625 | 3.390625 / 2.601562 | 3.324219 / 2.406250 |
| Main25..32真实观察Main / 局 | 2.679688 / 2.679688 | 2.574219 / 2.574219 | 2.517578 / 2.517578 |
| Main25..32印刷VP / 真实观察Main（总分母） | 1.287901 / 0.985423 | 1.317147 / 1.010622 | 1.320403 / 0.955780 |
| 投资兑现 / 投资总数 | 99.2607% / 99.8200% | 99.4000% / 99.7274% | 99.4957% / 99.8219% |
| 未兑现 / 投资总数 | 0.7393% / 0.1800% | 0.6000% / 0.2726% | 0.5043% / 0.1781% |
| 删失 / 投资总数 | 0.6900% / 0.4950% | 0.5000% / 0.5906% | 0.5547% / 0.4898% |
| 短于12Main对局比例 | 0.0000% / 0.0000% | 0.0000% / 0.0000% | 0.0000% / 0.0000% |
| 未达24Main对局比例 | 4.2969% / 4.2969% | 4.6875% / 4.6875% | 4.8828% / 4.8828% |
| 未达32Main对局比例 | 99.6094% / 99.6094% | 99.6094% / 99.6094% | 99.6094% / 99.6094% |


每格是被测模型 / 对手，包含全部对局、早败和未兑现投资。奖励不padding；AUC12短局终局折扣保持仅作描述。

| 被测玩家 | 对手 | 本模型物理座位 | 局数 | 效用（模型/对手） | AUC12折扣（模型/对手） |
| --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 先手 P0 | 256 | 0.463053 / 0.509277 | 2.017253 / 2.041992 |
| Prism Balance v0.1.0 (T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 后手 P1 | 256 | 0.459798 / 0.530762 | 1.950195 / 2.123047 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 先手 P0 | 256 | 0.459310 / 0.509115 | 2.027018 / 2.017578 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 后手 P1 | 256 | 0.443685 / 0.523763 | 1.928711 / 2.105794 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 先手 P0 | 256 | 0.442546 / 0.523275 | 1.983724 / 2.060547 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Heuristic v0.3.1 (greedy; Hello 0.2.9) | 后手 P1 | 256 | 0.455241 / 0.529948 | 1.926432 / 2.124349 |


#### Prism v0.1.1 (T=1)：完整双方数据

“模型”列是被测玩家；对手列注明动作模式。个人指标每格为“被测模型 / 对手”。节奏是该模型对阵该对手的整局指标。纯胜率=胜/局数，得分率=(胜+0.5平)/局数。

| 模型（T=1） | 对手 | 局数 / 双座种子数 | 胜 / 平 / 负 | 纯胜率 | 得分率 | 描述性配对95%区间 |
| --- | --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) | Prism v0.1.1 (T=1) | 512 / 256 | 338 / 3 / 171 | 66.0156% | 66.3086% | [62.2070%, 70.2148%] |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism v0.1.1 (T=1) | 512 / 256 | 331 / 6 / 175 | 64.6484% | 65.2344% | [61.0352%, 69.3359%] |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism v0.1.1 (T=1) | 512 / 256 | 340 / 4 / 168 | 66.4062% | 66.7969% | [62.5977%, 70.8008%] |


##### 双座明细

| 模型 | 对手 | 本模型座位 | 局数 | 胜 / 平 / 负 | 得分率 | 局均VP（模型 / 对手） |
| --- | --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) | Prism v0.1.1 (T=1) | 先手 P0 | 256 | 175 / 3 / 78 | 68.9453% | 14.961 / 13.359 |
| Prism Balance v0.1.0 (T=1) | Prism v0.1.1 (T=1) | 后手 P1 | 256 | 163 / 0 / 93 | 63.6719% | 14.750 / 13.375 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism v0.1.1 (T=1) | 先手 P0 | 256 | 165 / 3 / 88 | 65.0391% | 14.684 / 13.125 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism v0.1.1 (T=1) | 后手 P1 | 256 | 166 / 3 / 87 | 65.4297% | 14.875 / 13.023 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism v0.1.1 (T=1) | 先手 P0 | 256 | 181 / 0 / 75 | 70.7031% | 14.848 / 13.020 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism v0.1.1 (T=1) | 后手 P1 | 256 | 159 / 4 / 93 | 62.8906% | 14.934 / 13.559 |


##### 对局节奏与风格

| 模型 / 对手 | 局均步数 | 决策轮：均值 / 最短 / 中位 / 最长 | 轮标准差 | Main轮均值 | 终局绝对分差 | 分差≤2 | 总VP AUC24 | 20 Main内8VP |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) / Prism v0.1.1 (T=1) | 54.010 | 27.012 / 22 / 27.0 / 34 | 1.809 | 26.998 | 3.844 | 34.96% | 0.20672 | 28.1250% |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) / Prism v0.1.1 (T=1) | 53.797 | 26.906 / 21 / 27.0 / 33 | 1.838 | 26.891 | 4.014 | 30.47% | 0.21155 | 34.1797% |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) / Prism v0.1.1 (T=1) | 54.039 | 27.021 / 21 / 27.0 / 34 | 1.902 | 27.018 | 3.625 | 37.50% | 0.21163 | 33.5938% |


总VP AUC24/20 Main列为被测玩家；短于24自身Main的AUC按终局分补足固定窗口。legacy决策轮=ceil(全动作步数/2)，含贵族选择；Main轮排除贵族选择。本表总VP/大牌轨迹是描述性指标；M62九门使用独立building画像。

##### 双方得分、购卡、折扣、贵族与预留

| 个人指标：模型 / 对手 | Prism Balance v0.1.0 (T=1) 对阵 Prism v0.1.1 (T=1) | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.1 (T=1) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.1 (T=1) |
| --- | --- | --- | --- |
| 局均最终VP | 14.8555 / 13.3672 | 14.7793 / 13.0742 | 14.8906 / 13.2891 |
| VP / 自身决策（含贵族选择） | 0.5501 / 0.4950 | 0.5494 / 0.4861 | 0.5511 / 0.4918 |
| VP / 自身Main | 0.5502 / 0.4951 | 0.5496 / 0.4862 | 0.5511 / 0.4919 |
| VP / 全局步数 | 0.2751 / 0.2475 | 0.2747 / 0.2430 | 0.2756 / 0.2459 |
| 局均永久折扣 / 购卡 | 11.9805 / 12.2109 | 11.7793 / 12.2168 | 11.7441 / 12.3398 |
| 局均贵族数 | 0.5098 / 0.5059 | 0.4590 / 0.4883 | 0.4609 / 0.4883 |
| 局均预留获取 | 3.0723 / 2.7422 | 3.1387 / 2.6855 | 3.0352 / 2.7715 |
| 局均预留买回 | 1.2324 / 1.2012 | 1.2188 / 1.0664 | 1.2090 / 1.1777 |
| 终局未买回预留 | 1.8398 / 1.5410 | 1.9199 / 1.6191 | 1.8262 / 1.5938 |
| 获得贵族的对局比例 | 43.164% / 41.406% | 37.891% / 41.016% | 39.062% / 40.430% |
| 预留买回 / 获取 | 40.114% / 43.803% | 38.830% / 39.709% | 39.833% / 42.495% |
| 局均购入 0 VP卡 | 6.0215 / 6.4551 | 5.9180 / 6.5000 | 5.8105 / 6.5469 |
| 局均购入 1 VP卡 | 2.1406 / 2.2773 | 1.9727 / 2.3242 | 2.0195 / 2.3711 |
| 局均购入 2 VP卡 | 1.8066 / 1.8848 | 1.8516 / 1.8164 | 1.8711 / 1.8281 |
| 局均购入 3 VP卡 | 0.8164 / 0.7930 | 0.7988 / 0.8301 | 0.8105 / 0.8125 |
| 局均购入 4 VP卡 | 0.8535 / 0.5801 | 0.8613 / 0.5684 | 0.8477 / 0.5469 |
| 局均购入 5 VP卡 | 0.3418 / 0.2207 | 0.3770 / 0.1777 | 0.3848 / 0.2344 |
| 局均 白 折扣 | 2.4277 / 2.3066 | 2.4023 / 2.3574 | 2.3770 / 2.3613 |
| 局均 蓝 折扣 | 2.2500 / 2.4141 | 2.1133 / 2.5234 | 2.0918 / 2.6387 |
| 局均 绿 折扣 | 2.4180 / 2.5195 | 2.3125 / 2.5078 | 2.4375 / 2.4336 |
| 局均 红 折扣 | 2.4160 / 2.5547 | 2.4219 / 2.4473 | 2.3652 / 2.5156 |
| 局均 黑 折扣 | 2.4688 / 2.4160 | 2.5293 / 2.3809 | 2.4727 / 2.3906 |


##### 全部七类动作

| 个人指标：模型 / 对手 | Prism Balance v0.1.0 (T=1) 对阵 Prism v0.1.1 (T=1) | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.1 (T=1) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.1 (T=1) |
| --- | --- | --- | --- |
| 买市场 次数 | 5503 / 5637 | 5407 / 5709 | 5394 / 5715 |
| 买市场 占自身全部决策 | 39.802% / 40.768% | 39.261% / 41.454% | 38.991% / 41.311% |
| 买预留 次数 | 631 / 615 | 624 / 546 | 619 / 603 |
| 买预留 占自身全部决策 | 4.564% / 4.448% | 4.531% / 3.965% | 4.474% / 4.359% |
| 取宝石 次数 | 6116 / 6167 | 6130 / 6138 | 6266 / 6096 |
| 取宝石 占自身全部决策 | 44.235% / 44.601% | 44.511% / 44.569% | 45.294% / 44.065% |
| 预留市场 次数 | 1573 / 1400 | 1607 / 1372 | 1554 / 1418 |
| 预留市场 占自身全部决策 | 11.377% / 10.125% | 11.669% / 9.962% | 11.233% / 10.250% |
| 预留牌堆 次数 | 0 / 4 | 0 / 3 | 0 / 1 |
| 预留牌堆 占自身全部决策 | 0.000% / 0.029% | 0.000% / 0.022% | 0.000% / 0.007% |
| 选贵族 次数 | 3 / 4 | 4 / 4 | 1 / 1 |
| 选贵族 占自身全部决策 | 0.022% / 0.029% | 0.029% / 0.029% | 0.007% / 0.007% |
| 跳过 次数 | 0 / 0 | 0 / 0 | 0 / 0 |
| 跳过 占自身全部决策 | 0.000% / 0.000% | 0.000% / 0.000% | 0.000% / 0.000% |


##### 实测计时

| 模型 / 对手 | 进程耗时累计s | 单局均值s | 单局P95s | 决策 / 推理延迟 |
| --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) / Prism v0.1.1 (T=1) | 179.685 | 0.3509 | 0.5077 | NOT_MEASURED / NOT_MEASURED |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) / Prism v0.1.1 (T=1) | 175.270 | 0.3423 | 0.5076 | NOT_MEASURED / NOT_MEASURED |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) / Prism v0.1.1 (T=1) | 178.275 | 0.3482 | 0.5028 | NOT_MEASURED / NOT_MEASURED |


单局时钟包括程序启动、比赛、验核和输出；累计单局秒数含并行重叠，不等于整批墙钟。未记录逐决策/推理延迟，不能填0或由单局时间推算。

#### 大牌购入时点与分段得分（双方个人指标）

| 个人指标：模型 / 对手 | Prism Balance v0.1.0 (T=1) 对阵 Prism v0.1.1 (T=1) | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.1 (T=1) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.1 (T=1) |
| --- | --- | --- | --- |
| 24 Main 总VP AUC（描述性；非M62奖励） | 0.2067 / 0.1794 | 0.2116 / 0.1775 | 0.2116 / 0.1776 |
| 24 Main 大牌印刷VP AUC（描述性；非M62门） | 0.0823 / 0.0576 | 0.0841 / 0.0566 | 0.0841 / 0.0544 |
| 终局3～5VP牌印刷分合计 | 7.5723 / 5.8027 | 7.7266 / 5.6523 | 7.7461 / 5.7969 |
| 前24自身Main购入3～5VP牌数 | 1.3809 / 1.0391 | 1.3887 / 1.0352 | 1.3789 / 1.0098 |
| 首张3～5VP牌 自身Main（仅买到的局） | 18.5766 / 19.7651 | 18.4155 / 19.6930 | 18.3745 / 20.0087 |
| 首张3～5VP牌 覆盖局数 / 总局数（双方） | 496/512 ; 464/512 | 503/512 ; 456/512 | 486/512 ; 462/512 |
| 首张4～5VP牌 自身Main（仅买到的局） | 20.3510 / 21.1281 | 20.4780 / 21.1246 | 20.1921 / 21.2656 |
| 首张4～5VP牌 覆盖局数 / 总局数（双方） | 416/512 ; 320/512 | 431/512 ; 297/512 | 406/512 ; 305/512 |
| 自身Main 8 后局均总VP | 0.6602 / 0.5527 | 0.6777 / 0.5176 | 0.7480 / 0.5488 |
| 自身Main 8 后局均大牌印刷VP | 0.0488 / 0.0352 | 0.0488 / 0.0234 | 0.0645 / 0.0430 |
| 自身Main 8 实际达到局数（双方） | 512 / 512 | 512 / 512 | 512 / 512 |
| 自身Main 12 后局均总VP | 1.7656 / 1.5117 | 1.8457 / 1.4297 | 1.8008 / 1.4883 |
| 自身Main 12 后局均大牌印刷VP | 0.3477 / 0.2148 | 0.3730 / 0.1934 | 0.2988 / 0.2051 |
| 自身Main 12 实际达到局数（双方） | 512 / 512 | 512 / 512 | 512 / 512 |
| 自身Main 16 后局均总VP | 3.5371 / 3.0898 | 3.6719 / 3.0312 | 3.6738 / 2.9316 |
| 自身Main 16 后局均大牌印刷VP | 1.1602 / 0.8027 | 1.2051 / 0.7773 | 1.1523 / 0.6309 |
| 自身Main 16 实际达到局数（双方） | 512 / 512 | 512 / 512 | 512 / 512 |
| 自身Main 20 后局均总VP | 6.3633 / 5.5137 | 6.6074 / 5.5605 | 6.6055 / 5.5000 |
| 自身Main 20 后局均大牌印刷VP | 2.8164 / 1.9102 | 2.9043 / 1.9219 | 2.9609 / 1.8691 |
| 自身Main 20 实际达到局数（双方） | 512 / 512 | 512 / 512 | 512 / 512 |
| 自身Main 24 后局均总VP | 10.5625 / 9.2129 | 10.5234 / 9.1953 | 10.5508 / 9.2949 |
| 自身Main 24 后局均大牌印刷VP | 5.1934 / 3.7812 | 5.2617 / 3.6914 | 5.2441 / 3.6602 |
| 自身Main 24 实际达到局数（双方） | 502 / 502 | 497 / 497 | 499 / 499 |


每格为模型 / 对手。自身Main含购卡/取宝石/预留/跳过，不含贵族选择；贵族分计入前一个Main。短局在后续固定检查点用其终局分补足，并列实际达到该Main的局数。大牌仅含购入3～5VP卡的印刷VP，排除贵族；AUC按15VP截断、固定24分母。首牌时点只对买到的局取均值，必须连同覆盖率解读，不能单凭均值认定更快。

#### 基建投资与后续兑现（双方完整画像）

| 个人指标（被测模型 / 对手） | Prism Balance v0.1.0 (T=1) 对阵 Prism v0.1.1 (T=1) | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.1 (T=1) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.1 (T=1) |
| --- | --- | --- | --- |
| building效用（归一化0..1，reward代理） | 0.467285 / 0.481283 | 0.458659 / 0.485270 | 0.458659 / 0.489258 |
| 早期bonus AUC12（原始永久折扣个数；非reward） | 1.973796 / 1.989746 | 1.963867 / 1.996257 | 1.944824 / 2.017415 |
| 真实折扣适用使用单位 / 局（全局cap24） | 11.214844 / 11.550781 | 11.007812 / 11.646484 | 11.007812 / 11.742188 |
| cap3/投资后、全局cap前使用单位 / 局 | 11.214844 / 11.550781 | 11.007812 / 11.646484 | 11.007812 / 11.742188 |
| 未截断真实折扣使用单位 / 局 | 17.335938 / 17.978516 | 16.580078 / 18.365234 | 16.568359 / 18.419922 |
| 前12Main真实购卡 / 局 | 4.458984 / 4.470703 | 4.431641 / 4.484375 | 4.423828 / 4.533203 |
| 早期≤1VP投资 / 局 | 3.984375 / 4.095703 | 3.921875 / 4.128906 | 3.927734 / 4.148438 |
| 兑现投资 / 局 | 3.960938 / 4.083984 | 3.902344 / 4.101562 | 3.900391 / 4.130859 |
| 未兑现投资 / 局 | 0.023438 / 0.011719 | 0.019531 / 0.027344 | 0.027344 / 0.017578 |
| 观察窗口删失投资 / 局 | 0.015625 / 0.007812 | 0.017578 / 0.019531 | 0.023438 / 0.007812 |
| 未兑现且删失投资 / 局 | 0.000000 / 0.000000 | 0.000000 / 0.000000 | 0.000000 / 0.000000 |
| Main13..24真实购卡印刷VP / 局 | 8.123047 / 7.091797 | 8.080078 / 7.121094 | 8.164062 / 7.044922 |
| Main13..24真实观察Main / 局 | 11.976562 / 11.976562 | 11.958984 / 11.958984 | 11.960938 / 11.960938 |
| Main25..32真实得分购卡印刷VP / 局 | 3.429688 / 3.232422 | 3.466797 / 3.050781 | 3.529297 / 3.273438 |
| Main25..32真实观察Main / 局 | 3.013672 / 3.013672 | 2.929688 / 2.929688 | 3.048828 / 3.048828 |
| Main25..32印刷VP / 真实观察Main（总分母） | 1.138043 / 1.072586 | 1.183333 / 1.041333 | 1.157591 / 1.073671 |
| 投资兑现 / 投资总数 | 99.4118% / 99.7139% | 99.5020% / 99.3377% | 99.3038% / 99.5763% |
| 未兑现 / 投资总数 | 0.5882% / 0.2861% | 0.4980% / 0.6623% | 0.6962% / 0.4237% |
| 删失 / 投资总数 | 0.3922% / 0.1907% | 0.4482% / 0.4730% | 0.5967% / 0.1883% |
| 短于12Main对局比例 | 0.0000% / 0.0000% | 0.0000% / 0.0000% | 0.0000% / 0.0000% |
| 未达24Main对局比例 | 1.9531% / 1.9531% | 2.9297% / 2.9297% | 2.5391% / 2.5391% |
| 未达32Main对局比例 | 98.8281% / 98.8281% | 99.4141% / 99.4141% | 98.8281% / 98.8281% |


每格是被测模型 / 对手，包含全部对局、早败和未兑现投资。奖励不padding；AUC12短局终局折扣保持仅作描述。

| 被测玩家 | 对手 | 本模型物理座位 | 局数 | 效用（模型/对手） | AUC12折扣（模型/对手） |
| --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) | Prism v0.1.1 (T=1) | 先手 P0 | 256 | 0.482747 / 0.466797 | 2.024740 / 1.916341 |
| Prism Balance v0.1.0 (T=1) | Prism v0.1.1 (T=1) | 后手 P1 | 256 | 0.451823 / 0.495768 | 1.922852 / 2.063151 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism v0.1.1 (T=1) | 先手 P0 | 256 | 0.470378 / 0.479329 | 2.008789 / 1.952474 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism v0.1.1 (T=1) | 后手 P1 | 256 | 0.446940 / 0.491211 | 1.918945 / 2.040039 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism v0.1.1 (T=1) | 先手 P0 | 256 | 0.471191 / 0.480306 | 1.991211 / 1.960938 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism v0.1.1 (T=1) | 后手 P1 | 256 | 0.446126 / 0.498210 | 1.898438 / 2.073893 |


#### Prism v0.1.0 (greedy)：完整双方数据

“模型”列是被测玩家；对手列注明动作模式。个人指标每格为“被测模型 / 对手”。节奏是该模型对阵该对手的整局指标。纯胜率=胜/局数，得分率=(胜+0.5平)/局数。

| 模型（T=1） | 对手 | 局数 / 双座种子数 | 胜 / 平 / 负 | 纯胜率 | 得分率 | 描述性配对95%区间 |
| --- | --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) | Prism v0.1.0 (greedy) | 512 / 256 | 377 / 1 / 134 | 73.6328% | 73.7305% | [69.9219%, 77.5391%] |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism v0.1.0 (greedy) | 512 / 256 | 386 / 2 / 124 | 75.3906% | 75.5859% | [71.8750%, 79.2017%] |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism v0.1.0 (greedy) | 512 / 256 | 390 / 1 / 121 | 76.1719% | 76.2695% | [72.5586%, 79.8828%] |


##### 双座明细

| 模型 | 对手 | 本模型座位 | 局数 | 胜 / 平 / 负 | 得分率 | 局均VP（模型 / 对手） |
| --- | --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) | Prism v0.1.0 (greedy) | 先手 P0 | 256 | 190 / 1 / 65 | 74.4141% | 15.156 / 12.527 |
| Prism Balance v0.1.0 (T=1) | Prism v0.1.0 (greedy) | 后手 P1 | 256 | 187 / 0 / 69 | 73.0469% | 15.160 / 12.672 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism v0.1.0 (greedy) | 先手 P0 | 256 | 194 / 2 / 60 | 76.1719% | 15.227 / 12.637 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism v0.1.0 (greedy) | 后手 P1 | 256 | 192 / 0 / 64 | 75.0000% | 15.094 / 12.477 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism v0.1.0 (greedy) | 先手 P0 | 256 | 200 / 1 / 55 | 78.3203% | 15.180 / 12.246 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism v0.1.0 (greedy) | 后手 P1 | 256 | 190 / 0 / 66 | 74.2188% | 15.199 / 12.789 |


##### 对局节奏与风格

| 模型 / 对手 | 局均步数 | 决策轮：均值 / 最短 / 中位 / 最长 | 轮标准差 | Main轮均值 | 终局绝对分差 | 分差≤2 | 总VP AUC24 | 20 Main内8VP |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) / Prism v0.1.0 (greedy) | 53.324 | 26.672 / 20 / 27.0 / 34 | 1.903 | 26.648 | 4.211 | 29.10% | 0.22142 | 38.0859% |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) / Prism v0.1.0 (greedy) | 53.434 | 26.729 / 21 / 27.0 / 33 | 1.846 | 26.705 | 4.123 | 29.10% | 0.22048 | 39.6484% |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) / Prism v0.1.0 (greedy) | 53.188 | 26.602 / 22 / 27.0 / 32 | 1.813 | 26.584 | 4.180 | 29.49% | 0.22755 | 39.0625% |


总VP AUC24/20 Main列为被测玩家；短于24自身Main的AUC按终局分补足固定窗口。legacy决策轮=ceil(全动作步数/2)，含贵族选择；Main轮排除贵族选择。本表总VP/大牌轨迹是描述性指标；M62九门使用独立building画像。

##### 双方得分、购卡、折扣、贵族与预留

| 个人指标：模型 / 对手 | Prism Balance v0.1.0 (T=1) 对阵 Prism v0.1.0 (greedy) | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.0 (greedy) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.0 (greedy) |
| --- | --- | --- | --- |
| 局均最终VP | 15.1582 / 12.5996 | 15.1602 / 12.5566 | 15.1895 / 12.5176 |
| VP / 自身决策（含贵族选择） | 0.5688 / 0.4724 | 0.5676 / 0.4699 | 0.5714 / 0.4705 |
| VP / 自身Main | 0.5688 / 0.4728 | 0.5677 / 0.4702 | 0.5714 / 0.4709 |
| VP / 全局步数 | 0.2843 / 0.2363 | 0.2837 / 0.2350 | 0.2856 / 0.2353 |
| 局均永久折扣 / 购卡 | 11.5859 / 13.3926 | 11.5703 / 13.3359 | 11.5039 / 13.3262 |
| 局均贵族数 | 0.3809 / 0.6113 | 0.4062 / 0.5781 | 0.3730 / 0.6289 |
| 局均预留获取 | 2.7012 / 1.9844 | 2.8652 / 1.9238 | 2.6602 / 1.9727 |
| 局均预留买回 | 0.9590 / 0.9883 | 1.1582 / 0.9609 | 1.0000 / 1.0215 |
| 终局未买回预留 | 1.7422 / 0.9961 | 1.7070 / 0.9629 | 1.6602 / 0.9512 |
| 获得贵族的对局比例 | 32.617% / 45.703% | 34.180% / 43.945% | 33.203% / 46.289% |
| 预留买回 / 获取 | 35.503% / 49.803% | 40.423% / 49.949% | 37.592% / 51.782% |
| 局均购入 0 VP卡 | 5.5840 / 7.6172 | 5.6016 / 7.5273 | 5.4902 / 7.5156 |
| 局均购入 1 VP卡 | 1.9258 / 2.7207 | 1.9492 / 2.7715 | 1.9473 / 2.7930 |
| 局均购入 2 VP卡 | 1.9121 / 1.7480 | 1.8496 / 1.7246 | 1.8789 / 1.7891 |
| 局均购入 3 VP卡 | 0.8262 / 0.7930 | 0.8223 / 0.7559 | 0.8359 / 0.7441 |
| 局均购入 4 VP卡 | 0.9023 / 0.3984 | 0.9121 / 0.4492 | 0.9004 / 0.3945 |
| 局均购入 5 VP卡 | 0.4355 / 0.1152 | 0.4355 / 0.1074 | 0.4512 / 0.0898 |
| 局均 白 折扣 | 2.4082 / 2.5254 | 2.3066 / 2.5918 | 2.3555 / 2.5801 |
| 局均 蓝 折扣 | 2.1836 / 2.7832 | 2.1445 / 2.8184 | 2.0840 / 2.8125 |
| 局均 绿 折扣 | 2.3945 / 2.7266 | 2.3477 / 2.7441 | 2.4746 / 2.6367 |
| 局均 红 折扣 | 2.2559 / 2.6289 | 2.3438 / 2.5684 | 2.2852 / 2.6680 |
| 局均 黑 折扣 | 2.3438 / 2.7285 | 2.4277 / 2.6133 | 2.3047 / 2.6289 |


##### 全部七类动作

| 个人指标：模型 / 对手 | Prism Balance v0.1.0 (T=1) 对阵 Prism v0.1.0 (greedy) | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.0 (greedy) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.0 (greedy) |
| --- | --- | --- | --- |
| 买市场 次数 | 5441 / 6351 | 5331 / 6336 | 5378 / 6300 |
| 买市场 占自身全部决策 | 39.875% / 46.504% | 38.981% / 46.309% | 39.512% / 46.252% |
| 买预留 次数 | 491 / 506 | 593 / 492 | 512 / 523 |
| 买预留 占自身全部决策 | 3.598% / 3.705% | 4.336% / 3.596% | 3.762% / 3.840% |
| 取宝石 次数 | 6329 / 5771 | 6282 / 5860 | 6359 / 5778 |
| 取宝石 占自身全部决策 | 46.383% / 42.257% | 45.934% / 42.830% | 46.720% / 42.420% |
| 预留市场 次数 | 1383 / 1013 | 1467 / 983 | 1362 / 1005 |
| 预留市场 占自身全部决策 | 10.136% / 7.417% | 10.727% / 7.185% | 10.007% / 7.378% |
| 预留牌堆 次数 | 0 / 3 | 0 / 2 | 0 / 5 |
| 预留牌堆 占自身全部决策 | 0.000% / 0.022% | 0.000% / 0.015% | 0.000% / 0.037% |
| 选贵族 次数 | 1 / 13 | 3 / 9 | 0 / 10 |
| 选贵族 占自身全部决策 | 0.007% / 0.095% | 0.022% / 0.066% | 0.000% / 0.073% |
| 跳过 次数 | 0 / 0 | 0 / 0 | 0 / 0 |
| 跳过 占自身全部决策 | 0.000% / 0.000% | 0.000% / 0.000% | 0.000% / 0.000% |


##### 实测计时

| 模型 / 对手 | 进程耗时累计s | 单局均值s | 单局P95s | 决策 / 推理延迟 |
| --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) / Prism v0.1.0 (greedy) | 184.623 | 0.3606 | 0.5237 | NOT_MEASURED / NOT_MEASURED |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) / Prism v0.1.0 (greedy) | 183.253 | 0.3579 | 0.5223 | NOT_MEASURED / NOT_MEASURED |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) / Prism v0.1.0 (greedy) | 182.648 | 0.3567 | 0.5412 | NOT_MEASURED / NOT_MEASURED |


单局时钟包括程序启动、比赛、验核和输出；累计单局秒数含并行重叠，不等于整批墙钟。未记录逐决策/推理延迟，不能填0或由单局时间推算。

#### 大牌购入时点与分段得分（双方个人指标）

| 个人指标：模型 / 对手 | Prism Balance v0.1.0 (T=1) 对阵 Prism v0.1.0 (greedy) | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.0 (greedy) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.0 (greedy) |
| --- | --- | --- | --- |
| 24 Main 总VP AUC（描述性；非M62奖励） | 0.2214 / 0.1642 | 0.2205 / 0.1661 | 0.2275 / 0.1629 |
| 24 Main 大牌印刷VP AUC（描述性；非M62门） | 0.0911 / 0.0433 | 0.0926 / 0.0451 | 0.0955 / 0.0403 |
| 终局3～5VP牌印刷分合计 | 8.2656 / 4.5488 | 8.2930 / 4.6016 | 8.3652 / 4.2598 |
| 前24自身Main购入3～5VP牌数 | 1.4941 / 0.8398 | 1.4941 / 0.8770 | 1.5293 / 0.8320 |
| 首张3～5VP牌 自身Main（仅买到的局） | 18.1042 / 20.3060 | 17.9345 / 20.3718 | 17.8227 / 20.6220 |
| 首张3～5VP牌 覆盖局数 / 总局数（双方） | 499/512 ; 415/512 | 504/512 ; 425/512 | 502/512 ; 418/512 |
| 首张4～5VP牌 自身Main（仅买到的局） | 20.0450 / 21.6872 | 20.2123 / 21.0644 | 20.0703 / 21.7441 |
| 首张4～5VP牌 覆盖局数 / 总局数（双方） | 444/512 ; 227/512 | 438/512 ; 233/512 | 441/512 ; 211/512 |
| 自身Main 8 后局均总VP | 0.6660 / 0.4863 | 0.7148 / 0.4805 | 0.7559 / 0.4375 |
| 自身Main 8 后局均大牌印刷VP | 0.0605 / 0.0195 | 0.0645 / 0.0176 | 0.0898 / 0.0117 |
| 自身Main 8 实际达到局数（双方） | 512 / 512 | 512 / 512 | 512 / 512 |
| 自身Main 12 后局均总VP | 1.8418 / 1.3828 | 1.9316 / 1.3965 | 2.0723 / 1.3594 |
| 自身Main 12 后局均大牌印刷VP | 0.3438 / 0.1367 | 0.4395 / 0.1543 | 0.4199 / 0.1426 |
| 自身Main 12 实际达到局数（双方） | 512 / 512 | 512 / 512 | 512 / 512 |
| 自身Main 16 后局均总VP | 3.9043 / 2.6855 | 3.8574 / 2.7305 | 4.0234 / 2.6367 |
| 自身Main 16 后局均大牌印刷VP | 1.3223 / 0.4980 | 1.3574 / 0.5430 | 1.4102 / 0.4688 |
| 自身Main 16 实际达到局数（双方） | 512 / 512 | 512 / 512 | 512 / 512 |
| 自身Main 20 后局均总VP | 6.9199 / 5.0215 | 6.7988 / 5.0488 | 6.8652 / 5.0215 |
| 自身Main 20 后局均大牌印刷VP | 3.1445 / 1.5137 | 3.1152 / 1.5059 | 3.1562 / 1.3945 |
| 自身Main 20 实际达到局数（双方） | 512 / 512 | 512 / 512 | 512 / 512 |
| 自身Main 24 后局均总VP | 11.0352 / 8.7715 | 10.9551 / 8.8691 | 11.0918 / 8.8164 |
| 自身Main 24 后局均大牌印刷VP | 5.6836 / 2.9121 | 5.6777 / 3.0918 | 5.8223 / 2.8613 |
| 自身Main 24 实际达到局数（双方） | 490 / 490 | 492 / 492 | 488 / 488 |


每格为模型 / 对手。自身Main含购卡/取宝石/预留/跳过，不含贵族选择；贵族分计入前一个Main。短局在后续固定检查点用其终局分补足，并列实际达到该Main的局数。大牌仅含购入3～5VP卡的印刷VP，排除贵族；AUC按15VP截断、固定24分母。首牌时点只对买到的局取均值，必须连同覆盖率解读，不能单凭均值认定更快。

#### 基建投资与后续兑现（双方完整画像）

| 个人指标（被测模型 / 对手） | Prism Balance v0.1.0 (T=1) 对阵 Prism v0.1.0 (greedy) | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.0 (greedy) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Prism v0.1.0 (greedy) |
| --- | --- | --- | --- |
| building效用（归一化0..1，reward代理） | 0.455811 / 0.527344 | 0.448161 / 0.524658 | 0.440837 / 0.527995 |
| 早期bonus AUC12（原始永久折扣个数；非reward） | 1.986654 / 2.108398 | 1.967773 / 2.098958 | 1.953939 / 2.109049 |
| 真实折扣适用使用单位 / 局（全局cap24） | 10.939453 / 12.656250 | 10.755859 / 12.591797 | 10.580078 / 12.671875 |
| cap3/投资后、全局cap前使用单位 / 局 | 10.939453 / 12.656250 | 10.755859 / 12.591797 | 10.580078 / 12.671875 |
| 未截断真实折扣使用单位 / 局 | 16.525391 / 21.568359 | 16.001953 / 21.718750 | 15.708984 / 21.599609 |
| 前12Main真实购卡 / 局 | 4.433594 / 4.740234 | 4.365234 / 4.722656 | 4.373047 / 4.720703 |
| 早期≤1VP投资 / 局 | 3.923828 / 4.416016 | 3.835938 / 4.392578 | 3.783203 / 4.402344 |
| 兑现投资 / 局 | 3.900391 / 4.406250 | 3.816406 / 4.376953 | 3.757812 / 4.380859 |
| 未兑现投资 / 局 | 0.023438 / 0.009766 | 0.019531 / 0.015625 | 0.025391 / 0.021484 |
| 观察窗口删失投资 / 局 | 0.027344 / 0.033203 | 0.013672 / 0.023438 | 0.023438 / 0.023438 |
| 未兑现且删失投资 / 局 | 0.001953 / 0.000000 | 0.001953 / 0.000000 | 0.000000 / 0.000000 |
| Main13..24真实购卡印刷VP / 局 | 8.712891 / 6.503906 | 8.443359 / 6.628906 | 8.562500 / 6.607422 |
| Main13..24真实观察Main / 局 | 11.921875 / 11.921875 | 11.941406 / 11.941406 | 11.931641 / 11.931641 |
| Main25..32真实得分购卡印刷VP / 局 | 3.457031 / 2.873047 | 3.556641 / 2.791016 | 3.435547 / 2.664062 |
| Main25..32真实观察Main / 局 | 2.722656 / 2.722656 | 2.759766 / 2.759766 | 2.652344 / 2.652344 |
| Main25..32印刷VP / 真实观察Main（总分母） | 1.269727 / 1.055237 | 1.288747 / 1.011323 | 1.295287 / 1.004418 |
| 投资兑现 / 投资总数 | 99.4027% / 99.7789% | 99.4908% / 99.6443% | 99.3289% / 99.5120% |
| 未兑现 / 投资总数 | 0.5973% / 0.2211% | 0.5092% / 0.3557% | 0.6711% / 0.4880% |
| 删失 / 投资总数 | 0.6969% / 0.7519% | 0.3564% / 0.5336% | 0.6195% / 0.5324% |
| 短于12Main对局比例 | 0.0000% / 0.0000% | 0.0000% / 0.0000% | 0.0000% / 0.0000% |
| 未达24Main对局比例 | 4.2969% / 4.2969% | 3.9062% / 3.9062% | 4.6875% / 4.6875% |
| 未达32Main对局比例 | 99.6094% / 99.6094% | 99.2188% / 99.2188% | 99.8047% / 99.8047% |


每格是被测模型 / 对手，包含全部对局、早败和未兑现投资。奖励不padding；AUC12短局终局折扣保持仅作描述。

| 被测玩家 | 对手 | 本模型物理座位 | 局数 | 效用（模型/对手） | AUC12折扣（模型/对手） |
| --- | --- | --- | --- | --- | --- |
| Prism Balance v0.1.0 (T=1) | Prism v0.1.0 (greedy) | 先手 P0 | 256 | 0.465007 / 0.512533 | 2.033854 / 2.059570 |
| Prism Balance v0.1.0 (T=1) | Prism v0.1.0 (greedy) | 后手 P1 | 256 | 0.446615 / 0.542155 | 1.939453 / 2.157227 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism v0.1.0 (greedy) | 先手 P0 | 256 | 0.457194 / 0.513509 | 2.012695 / 2.053711 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism v0.1.0 (greedy) | 后手 P1 | 256 | 0.439128 / 0.535807 | 1.922852 / 2.144206 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism v0.1.0 (greedy) | 先手 P0 | 256 | 0.450195 / 0.518880 | 2.010091 / 2.061523 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism v0.1.0 (greedy) | 后手 P1 | 256 | 0.431478 / 0.537109 | 1.897786 / 2.156576 |


#### Prism Alpha v0.1.4 (T=1)：完整双方数据

“模型”列是被测玩家；对手列注明动作模式。个人指标每格为“被测模型 / 对手”。节奏是该模型对阵该对手的整局指标。纯胜率=胜/局数，得分率=(胜+0.5平)/局数。

| 模型（T=1） | 对手 | 局数 / 双座种子数 | 胜 / 平 / 负 | 纯胜率 | 得分率 | 描述性配对95%区间 |
| --- | --- | --- | --- | --- | --- | --- |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism Alpha v0.1.4 (T=1) | 1024 / 512 | 557 / 12 / 455 | 54.3945% | 54.9805% | [51.9531%, 58.0566%] |


##### 双座明细

| 模型 | 对手 | 本模型座位 | 局数 | 胜 / 平 / 负 | 得分率 | 局均VP（模型 / 对手） |
| --- | --- | --- | --- | --- | --- | --- |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism Alpha v0.1.4 (T=1) | 先手 P0 | 512 | 292 / 7 / 213 | 57.7148% | 14.219 / 13.854 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism Alpha v0.1.4 (T=1) | 后手 P1 | 512 | 265 / 5 / 242 | 52.2461% | 14.266 / 13.938 |


##### 对局节奏与风格

| 模型 / 对手 | 局均步数 | 决策轮：均值 / 最短 / 中位 / 最长 | 轮标准差 | Main轮均值 | 终局绝对分差 | 分差≤2 | 总VP AUC24 | 20 Main内8VP |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) / Prism Alpha v0.1.4 (T=1) | 54.197 | 27.104 / 20 / 27.0 / 33 | 1.843 | 27.093 | 3.644 | 35.64% | 0.20028 | 28.6133% |


总VP AUC24/20 Main列为被测玩家；短于24自身Main的AUC按终局分补足固定窗口。legacy决策轮=ceil(全动作步数/2)，含贵族选择；Main轮排除贵族选择。本表总VP/大牌轨迹是描述性指标；M62九门使用独立building画像。

##### 双方得分、购卡、折扣、贵族与预留

| 个人指标：模型 / 对手 | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism Alpha v0.1.4 (T=1) |
| --- | --- |
| 局均最终VP | 14.2422 / 13.8955 |
| VP / 自身决策（含贵族选择） | 0.5255 / 0.5128 |
| VP / 自身Main | 0.5257 / 0.5129 |
| VP / 全局步数 | 0.2628 / 0.2564 |
| 局均永久折扣 / 购卡 | 11.8350 / 11.7783 |
| 局均贵族数 | 0.4648 / 0.4424 |
| 局均预留获取 | 3.4482 / 3.2344 |
| 局均预留买回 | 1.3955 / 1.2930 |
| 终局未买回预留 | 2.0527 / 1.9414 |
| 获得贵族的对局比例 | 39.551% / 37.109% |
| 预留买回 / 获取 | 40.470% / 39.976% |
| 局均购入 0 VP卡 | 5.9766 / 6.1270 |
| 局均购入 1 VP卡 | 2.2227 / 1.9961 |
| 局均购入 2 VP卡 | 1.7344 / 1.7637 |
| 局均购入 3 VP卡 | 0.7725 / 0.8408 |
| 局均购入 4 VP卡 | 0.8057 / 0.7314 |
| 局均购入 5 VP卡 | 0.3232 / 0.3193 |
| 局均 白 折扣 | 2.3848 / 2.3086 |
| 局均 蓝 折扣 | 2.1992 / 2.3076 |
| 局均 绿 折扣 | 2.3457 / 2.3975 |
| 局均 红 折扣 | 2.4600 / 2.3145 |
| 局均 黑 折扣 | 2.4453 / 2.4502 |


##### 全部七类动作

| 个人指标：模型 / 对手 | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism Alpha v0.1.4 (T=1) |
| --- | --- |
| 买市场 次数 | 10690 / 10737 |
| 买市场 占自身全部决策 | 38.521% / 38.696% |
| 买预留 次数 | 1429 / 1324 |
| 买预留 占自身全部决策 | 5.149% / 4.772% |
| 取宝石 次数 | 12093 / 12370 |
| 取宝石 占自身全部决策 | 43.577% / 44.581% |
| 预留市场 次数 | 3531 / 3312 |
| 预留市场 占自身全部决策 | 12.724% / 11.936% |
| 预留牌堆 次数 | 0 / 0 |
| 预留牌堆 占自身全部决策 | 0.000% / 0.000% |
| 选贵族 次数 | 8 / 4 |
| 选贵族 占自身全部决策 | 0.029% / 0.014% |
| 跳过 次数 | 0 / 0 |
| 跳过 占自身全部决策 | 0.000% / 0.000% |


##### 实测计时

| 模型 / 对手 | 进程耗时累计s | 单局均值s | 单局P95s | 决策 / 推理延迟 |
| --- | --- | --- | --- | --- |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) / Prism Alpha v0.1.4 (T=1) | 353.314 | 0.3450 | 0.5072 | NOT_MEASURED / NOT_MEASURED |


单局时钟包括程序启动、比赛、验核和输出；累计单局秒数含并行重叠，不等于整批墙钟。未记录逐决策/推理延迟，不能填0或由单局时间推算。

#### 大牌购入时点与分段得分（双方个人指标）

| 个人指标：模型 / 对手 | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism Alpha v0.1.4 (T=1) |
| --- | --- |
| 24 Main 总VP AUC（描述性；非M62奖励） | 0.2003 / 0.1985 |
| 24 Main 大牌印刷VP AUC（描述性；非M62门） | 0.0762 / 0.0774 |
| 终局3～5VP牌印刷分合计 | 7.1562 / 7.0449 |
| 前24自身Main购入3～5VP牌数 | 1.2246 / 1.2168 |
| 首张3～5VP牌 自身Main（仅买到的局） | 18.5857 / 18.6182 |
| 首张3～5VP牌 覆盖局数 / 总局数（双方） | 980/1024 ; 990/1024 |
| 首张4～5VP牌 自身Main（仅买到的局） | 20.6030 / 20.5278 |
| 首张4～5VP牌 覆盖局数 / 总局数（双方） | 801/1024 ; 773/1024 |
| 自身Main 8 后局均总VP | 0.6484 / 0.6553 |
| 自身Main 8 后局均大牌印刷VP | 0.0283 / 0.0596 |
| 自身Main 8 实际达到局数（双方） | 1024 / 1024 |
| 自身Main 12 后局均总VP | 1.7803 / 1.7656 |
| 自身Main 12 后局均大牌印刷VP | 0.3887 / 0.3740 |
| 自身Main 12 实际达到局数（双方） | 1024 / 1024 |
| 自身Main 16 后局均总VP | 3.4717 / 3.4951 |
| 自身Main 16 后局均大牌印刷VP | 1.1299 / 1.1836 |
| 自身Main 16 实际达到局数（双方） | 1024 / 1024 |
| 自身Main 20 后局均总VP | 6.1670 / 6.1748 |
| 自身Main 20 后局均大牌印刷VP | 2.5752 / 2.6680 |
| 自身Main 20 实际达到局数（双方） | 1024 / 1024 |
| 自身Main 24 后局均总VP | 9.8184 / 9.6455 |
| 自身Main 24 后局均大牌印刷VP | 4.5742 / 4.5459 |
| 自身Main 24 实际达到局数（双方） | 1002 / 1002 |


每格为模型 / 对手。自身Main含购卡/取宝石/预留/跳过，不含贵族选择；贵族分计入前一个Main。短局在后续固定检查点用其终局分补足，并列实际达到该Main的局数。大牌仅含购入3～5VP卡的印刷VP，排除贵族；AUC按15VP截断、固定24分母。首牌时点只对买到的局取均值，必须连同覆盖率解读，不能单凭均值认定更快。

#### 基建投资与后续兑现（双方完整画像）

| 个人指标（被测模型 / 对手） | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism Alpha v0.1.4 (T=1) |
| --- | --- |
| building效用（归一化0..1，reward代理） | 0.461507 / 0.452352 |
| 早期bonus AUC12（原始永久折扣个数；非reward） | 1.966390 / 1.942871 |
| 真实折扣适用使用单位 / 局（全局cap24） | 11.076172 / 10.856445 |
| cap3/投资后、全局cap前使用单位 / 局 | 11.076172 / 10.856445 |
| 未截断真实折扣使用单位 / 局 | 16.560547 / 16.604492 |
| 前12Main真实购卡 / 局 | 4.444336 / 4.378906 |
| 早期≤1VP投资 / 局 | 3.979492 / 3.889648 |
| 兑现投资 / 局 | 3.958008 / 3.867188 |
| 未兑现投资 / 局 | 0.021484 / 0.022461 |
| 观察窗口删失投资 / 局 | 0.016602 / 0.009766 |
| 未兑现且删失投资 / 局 | 0.000977 / 0.001953 |
| Main13..24真实购卡印刷VP / 局 | 7.440430 / 7.326172 |
| Main13..24真实观察Main / 局 | 11.968750 / 11.968750 |
| Main25..32真实得分购卡印刷VP / 局 | 3.625977 / 3.474609 |
| Main25..32真实观察Main / 局 | 3.123047 / 3.123047 |
| Main25..32印刷VP / 真实观察Main（总分母） | 1.161038 / 1.112570 |
| 投资兑现 / 投资总数 | 99.4601% / 99.4225% |
| 未兑现 / 投资总数 | 0.5399% / 0.5775% |
| 删失 / 投资总数 | 0.4172% / 0.2511% |
| 短于12Main对局比例 | 0.0000% / 0.0000% |
| 未达24Main对局比例 | 2.1484% / 2.1484% |
| 未达32Main对局比例 | 99.4141% / 99.4141% |


每格是被测模型 / 对手，包含全部对局、早败和未兑现投资。奖励不padding；AUC12短局终局折扣保持仅作描述。

| 被测玩家 | 对手 | 本模型物理座位 | 局数 | 效用（模型/对手） | AUC12折扣（模型/对手） |
| --- | --- | --- | --- | --- | --- |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism Alpha v0.1.4 (T=1) | 先手 P0 | 512 | 0.471354 / 0.440430 | 2.022786 / 1.882487 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism Alpha v0.1.4 (T=1) | 后手 P1 | 512 | 0.451660 / 0.464274 | 1.909993 / 2.003255 |


#### Prism Balance v0.1.0 (T=1)：完整双方数据

“模型”列是被测玩家；对手列注明动作模式。个人指标每格为“被测模型 / 对手”。节奏是该模型对阵该对手的整局指标。纯胜率=胜/局数，得分率=(胜+0.5平)/局数。

| 模型（T=1） | 对手 | 局数 / 双座种子数 | 胜 / 平 / 负 | 纯胜率 | 得分率 | 描述性配对95%区间 |
| --- | --- | --- | --- | --- | --- | --- |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism Balance v0.1.0 (T=1) | 1024 / 512 | 523 / 15 / 486 | 51.0742% | 51.8066% | [48.8281%, 54.8340%] |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism Balance v0.1.0 (T=1) | 1024 / 512 | 528 / 10 / 486 | 51.5625% | 52.0508% | [49.1211%, 55.0293%] |


##### 双座明细

| 模型 | 对手 | 本模型座位 | 局数 | 胜 / 平 / 负 | 得分率 | 局均VP（模型 / 对手） |
| --- | --- | --- | --- | --- | --- | --- |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism Balance v0.1.0 (T=1) | 先手 P0 | 512 | 274 / 7 / 231 | 54.1992% | 14.121 / 14.059 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism Balance v0.1.0 (T=1) | 后手 P1 | 512 | 249 / 8 / 255 | 49.4141% | 14.268 / 14.139 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism Balance v0.1.0 (T=1) | 先手 P0 | 512 | 266 / 6 / 240 | 52.5391% | 14.168 / 14.062 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism Balance v0.1.0 (T=1) | 后手 P1 | 512 | 262 / 4 / 246 | 51.5625% | 14.256 / 13.875 |


##### 对局节奏与风格

| 模型 / 对手 | 局均步数 | 决策轮：均值 / 最短 / 中位 / 最长 | 轮标准差 | Main轮均值 | 终局绝对分差 | 分差≤2 | 总VP AUC24 | 20 Main内8VP |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) / Prism Balance v0.1.0 (T=1) | 54.284 | 27.144 / 21 / 27.0 / 33 | 1.888 | 27.140 | 3.520 | 37.79% | 0.20277 | 30.3711% |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) / Prism Balance v0.1.0 (T=1) | 54.161 | 27.085 / 21 / 27.0 / 34 | 1.868 | 27.075 | 3.628 | 33.89% | 0.20173 | 26.1719% |


总VP AUC24/20 Main列为被测玩家；短于24自身Main的AUC按终局分补足固定窗口。legacy决策轮=ceil(全动作步数/2)，含贵族选择；Main轮排除贵族选择。本表总VP/大牌轨迹是描述性指标；M62九门使用独立building画像。

##### 双方得分、购卡、折扣、贵族与预留

| 个人指标：模型 / 对手 | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism Balance v0.1.0 (T=1) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Prism Balance v0.1.0 (T=1) |
| --- | --- | --- |
| 局均最终VP | 14.1943 / 14.0986 | 14.2119 / 13.9688 |
| VP / 自身决策（含贵族选择） | 0.5230 / 0.5194 | 0.5248 / 0.5158 |
| VP / 自身Main | 0.5230 / 0.5195 | 0.5249 / 0.5159 |
| VP / 全局步数 | 0.2615 / 0.2597 | 0.2624 / 0.2579 |
| 局均永久折扣 / 购卡 | 11.7041 / 11.8662 | 11.7041 / 11.8447 |
| 局均贵族数 | 0.4424 / 0.4502 | 0.4219 / 0.4629 |
| 局均预留获取 | 3.3916 / 3.2490 | 3.1865 / 3.3066 |
| 局均预留买回 | 1.3203 / 1.3047 | 1.2656 / 1.3320 |
| 终局未买回预留 | 2.0713 / 1.9443 | 1.9209 / 1.9746 |
| 获得贵族的对局比例 | 38.086% / 37.109% | 36.523% / 38.867% |
| 预留买回 / 获取 | 38.929% / 40.156% | 39.718% / 40.284% |
| 局均购入 0 VP卡 | 5.8574 / 6.0625 | 5.8135 / 6.0342 |
| 局均购入 1 VP卡 | 2.1729 / 2.0908 | 2.1592 / 2.1504 |
| 局均购入 2 VP卡 | 1.7832 / 1.8135 | 1.8125 / 1.8398 |
| 局均购入 3 VP卡 | 0.7861 / 0.8721 | 0.8467 / 0.8369 |
| 局均购入 4 VP卡 | 0.7529 / 0.7227 | 0.7393 / 0.6777 |
| 局均购入 5 VP卡 | 0.3516 / 0.3047 | 0.3330 / 0.3057 |
| 局均 白 折扣 | 2.2402 / 2.5039 | 2.3740 / 2.3887 |
| 局均 蓝 折扣 | 2.1982 / 2.3174 | 2.2168 / 2.2979 |
| 局均 绿 折扣 | 2.3857 / 2.3037 | 2.4277 / 2.2793 |
| 局均 红 折扣 | 2.4512 / 2.3252 | 2.2998 / 2.4824 |
| 局均 黑 折扣 | 2.4287 / 2.4160 | 2.3857 / 2.3965 |


##### 全部七类动作

| 个人指标：模型 / 对手 | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism Balance v0.1.0 (T=1) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Prism Balance v0.1.0 (T=1) |
| --- | --- | --- |
| 买市场 次数 | 10633 / 10815 | 10689 / 10765 |
| 买市场 占自身全部决策 | 38.259% / 38.910% | 38.548% / 38.818% |
| 买预留 次数 | 1352 / 1336 | 1296 / 1364 |
| 买预留 占自身全部决策 | 4.865% / 4.807% | 4.674% / 4.919% |
| 取宝石 次数 | 12333 / 12313 | 12477 / 12210 |
| 取宝石 占自身全部决策 | 44.376% / 44.299% | 44.996% / 44.029% |
| 预留市场 次数 | 3471 / 3326 | 3262 / 3386 |
| 预留市场 占自身全部决策 | 12.489% / 11.966% | 11.764% / 12.210% |
| 预留牌堆 次数 | 2 / 1 | 1 / 0 |
| 预留牌堆 占自身全部决策 | 0.007% / 0.004% | 0.004% / 0.000% |
| 选贵族 次数 | 1 / 4 | 4 / 7 |
| 选贵族 占自身全部决策 | 0.004% / 0.014% | 0.014% / 0.025% |
| 跳过 次数 | 0 / 0 | 0 / 0 |
| 跳过 占自身全部决策 | 0.000% / 0.000% | 0.000% / 0.000% |


##### 实测计时

| 模型 / 对手 | 进程耗时累计s | 单局均值s | 单局P95s | 决策 / 推理延迟 |
| --- | --- | --- | --- | --- |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) / Prism Balance v0.1.0 (T=1) | 354.641 | 0.3463 | 0.5281 | NOT_MEASURED / NOT_MEASURED |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) / Prism Balance v0.1.0 (T=1) | 346.871 | 0.3387 | 0.4963 | NOT_MEASURED / NOT_MEASURED |


单局时钟包括程序启动、比赛、验核和输出；累计单局秒数含并行重叠，不等于整批墙钟。未记录逐决策/推理延迟，不能填0或由单局时间推算。

#### 大牌购入时点与分段得分（双方个人指标）

| 个人指标：模型 / 对手 | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism Balance v0.1.0 (T=1) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Prism Balance v0.1.0 (T=1) |
| --- | --- | --- |
| 24 Main 总VP AUC（描述性；非M62奖励） | 0.2028 / 0.1950 | 0.2017 / 0.1957 |
| 24 Main 大牌印刷VP AUC（描述性；非M62门） | 0.0767 / 0.0741 | 0.0752 / 0.0714 |
| 终局3～5VP牌印刷分合计 | 7.1279 / 7.0303 | 7.1621 / 6.7500 |
| 前24自身Main购入3～5VP牌数 | 1.2471 / 1.2588 | 1.2490 / 1.2012 |
| 首张3～5VP牌 自身Main（仅买到的局） | 18.6051 / 18.8088 | 18.6348 / 18.8518 |
| 首张3～5VP牌 覆盖局数 / 总局数（双方） | 975/1024 ; 978/1024 | 983/1024 ; 958/1024 |
| 首张4～5VP牌 自身Main（仅买到的局） | 20.7942 / 20.7319 | 21.0691 / 20.7819 |
| 首张4～5VP牌 覆盖局数 / 总局数（双方） | 787/1024 ; 761/1024 | 782/1024 ; 729/1024 |
| 自身Main 8 后局均总VP | 0.6797 / 0.6016 | 0.6348 / 0.5801 |
| 自身Main 8 后局均大牌印刷VP | 0.0527 / 0.0479 | 0.0322 / 0.0332 |
| 自身Main 8 实际达到局数（双方） | 1024 / 1024 | 1024 / 1024 |
| 自身Main 12 后局均总VP | 1.8105 / 1.6768 | 1.8604 / 1.7275 |
| 自身Main 12 后局均大牌印刷VP | 0.3594 / 0.3262 | 0.4375 / 0.3291 |
| 自身Main 12 实际达到局数（双方） | 1024 / 1024 | 1024 / 1024 |
| 自身Main 16 后局均总VP | 3.5430 / 3.3945 | 3.5811 / 3.4082 |
| 自身Main 16 后局均大牌印刷VP | 1.0938 / 1.0342 | 1.1318 / 0.9727 |
| 自身Main 16 实际达到局数（双方） | 1024 / 1024 | 1024 / 1024 |
| 自身Main 20 后局均总VP | 6.2861 / 6.0312 | 6.2041 / 6.0625 |
| 自身Main 20 后局均大牌印刷VP | 2.6562 / 2.5020 | 2.5186 / 2.4355 |
| 自身Main 20 实际达到局数（双方） | 1024 / 1024 | 1024 / 1024 |
| 自身Main 24 后局均总VP | 9.9824 / 9.8018 | 9.8848 / 9.7949 |
| 自身Main 24 后局均大牌印刷VP | 4.6758 / 4.6426 | 4.6113 / 4.4414 |
| 自身Main 24 实际达到局数（双方） | 997 / 997 | 998 / 998 |


每格为模型 / 对手。自身Main含购卡/取宝石/预留/跳过，不含贵族选择；贵族分计入前一个Main。短局在后续固定检查点用其终局分补足，并列实际达到该Main的局数。大牌仅含购入3～5VP卡的印刷VP，排除贵族；AUC按15VP截断、固定24分母。首牌时点只对买到的局取均值，必须连同覆盖率解读，不能单凭均值认定更快。

#### 基建投资与后续兑现（双方完整画像）

| 个人指标（被测模型 / 对手） | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism Balance v0.1.0 (T=1) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) 对阵 Prism Balance v0.1.0 (T=1) |
| --- | --- | --- |
| building效用（归一化0..1，reward代理） | 0.460205 / 0.464966 | 0.452108 / 0.464030 |
| 早期bonus AUC12（原始永久折扣个数；非reward） | 1.953451 / 1.979736 | 1.938395 / 1.975179 |
| 真实折扣适用使用单位 / 局（全局cap24） | 11.044922 / 11.159180 | 10.850586 / 11.136719 |
| cap3/投资后、全局cap前使用单位 / 局 | 11.044922 / 11.159180 | 10.850586 / 11.136719 |
| 未截断真实折扣使用单位 / 局 | 16.548828 / 16.971680 | 16.340820 / 16.920898 |
| 前12Main真实购卡 / 局 | 4.427734 / 4.456055 | 4.385742 / 4.466797 |
| 早期≤1VP投资 / 局 | 3.957031 / 3.994141 | 3.898438 / 3.996094 |
| 兑现投资 / 局 | 3.941406 / 3.977539 | 3.882812 / 3.974609 |
| 未兑现投资 / 局 | 0.015625 / 0.016602 | 0.015625 / 0.021484 |
| 观察窗口删失投资 / 局 | 0.012695 / 0.024414 | 0.016602 / 0.019531 |
| 未兑现且删失投资 / 局 | 0.000000 / 0.000977 | 0.000000 / 0.000000 |
| Main13..24真实购卡印刷VP / 局 | 7.606445 / 7.585938 | 7.520508 / 7.481445 |
| Main13..24真实观察Main / 局 | 11.956055 / 11.956055 | 11.958984 / 11.958984 |
| Main25..32真实得分购卡印刷VP / 局 | 3.443359 / 3.471680 | 3.554688 / 3.365234 |
| Main25..32真实观察Main / 局 | 3.179688 / 3.179688 | 3.112305 / 3.112305 |
| Main25..32印刷VP / 真实观察Main（总分母） | 1.082924 / 1.091830 | 1.142140 / 1.081268 |
| 投资兑现 / 投资总数 | 99.6051% / 99.5844% | 99.5992% / 99.4624% |
| 未兑现 / 投资总数 | 0.3949% / 0.4156% | 0.4008% / 0.5376% |
| 删失 / 投资总数 | 0.3208% / 0.6112% | 0.4259% / 0.4888% |
| 短于12Main对局比例 | 0.0000% / 0.0000% | 0.0000% / 0.0000% |
| 未达24Main对局比例 | 2.6367% / 2.6367% | 2.5391% / 2.5391% |
| 未达32Main对局比例 | 99.1211% / 99.1211% | 99.0234% / 99.0234% |


每格是被测模型 / 对手，包含全部对局、早败和未兑现投资。奖励不padding；AUC12短局终局折扣保持仅作描述。

| 被测玩家 | 对手 | 本模型物理座位 | 局数 | 效用（模型/对手） | AUC12折扣（模型/对手） |
| --- | --- | --- | --- | --- | --- |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism Balance v0.1.0 (T=1) | 先手 P0 | 512 | 0.472900 / 0.454508 | 2.015299 / 1.929688 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism Balance v0.1.0 (T=1) | 后手 P1 | 512 | 0.447510 / 0.475423 | 1.891602 / 2.029785 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism Balance v0.1.0 (T=1) | 先手 P0 | 512 | 0.462077 / 0.453613 | 1.994954 / 1.932943 |
| Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | Prism Balance v0.1.0 (T=1) | 后手 P1 | 512 | 0.442139 / 0.474447 | 1.881836 / 2.017415 |


#### Prism Balance v0.1.1 candidate (unpublished final-c4; T=1)：完整双方数据

“模型”列是被测玩家；对手列注明动作模式。个人指标每格为“被测模型 / 对手”。节奏是该模型对阵该对手的整局指标。纯胜率=胜/局数，得分率=(胜+0.5平)/局数。

| 模型（T=1） | 对手 | 局数 / 双座种子数 | 胜 / 平 / 负 | 纯胜率 | 得分率 | 描述性配对95%区间 |
| --- | --- | --- | --- | --- | --- | --- |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | 1024 / 512 | 487 / 9 / 528 | 47.5586% | 47.9980% | [44.9219%, 51.0742%] |


##### 双座明细

| 模型 | 对手 | 本模型座位 | 局数 | 胜 / 平 / 负 | 得分率 | 局均VP（模型 / 对手） |
| --- | --- | --- | --- | --- | --- | --- |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | 先手 P0 | 512 | 244 / 4 / 264 | 48.0469% | 13.908 / 14.174 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | 后手 P1 | 512 | 243 / 5 / 264 | 47.9492% | 14.209 / 14.141 |


##### 对局节奏与风格

| 模型 / 对手 | 局均步数 | 决策轮：均值 / 最短 / 中位 / 最长 | 轮标准差 | Main轮均值 | 终局绝对分差 | 分差≤2 | 总VP AUC24 | 20 Main内8VP |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) / Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | 54.322 | 27.167 / 21 / 27.0 / 34 | 1.915 | 27.155 | 3.567 | 35.25% | 0.19849 | 25.4883% |


总VP AUC24/20 Main列为被测玩家；短于24自身Main的AUC按终局分补足固定窗口。legacy决策轮=ceil(全动作步数/2)，含贵族选择；Main轮排除贵族选择。本表总VP/大牌轨迹是描述性指标；M62九门使用独立building画像。

##### 双方得分、购卡、折扣、贵族与预留

| 个人指标：模型 / 对手 | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) |
| --- | --- |
| 局均最终VP | 14.0586 / 14.1572 |
| VP / 自身决策（含贵族选择） | 0.5176 / 0.5212 |
| VP / 自身Main | 0.5177 / 0.5213 |
| VP / 全局步数 | 0.2588 / 0.2606 |
| 局均永久折扣 / 购卡 | 11.7305 / 11.7285 |
| 局均贵族数 | 0.4482 / 0.4219 |
| 局均预留获取 | 3.5049 / 3.1592 |
| 局均预留买回 | 1.3828 / 1.2637 |
| 终局未买回预留 | 2.1221 / 1.8955 |
| 获得贵族的对局比例 | 38.086% / 35.254% |
| 预留买回 / 获取 | 39.454% / 40.000% |
| 局均购入 0 VP卡 | 5.9648 / 5.7969 |
| 局均购入 1 VP卡 | 2.0996 / 2.2080 |
| 局均购入 2 VP卡 | 1.7764 / 1.8574 |
| 局均购入 3 VP卡 | 0.8066 / 0.8223 |
| 局均购入 4 VP卡 | 0.7734 / 0.7178 |
| 局均购入 5 VP卡 | 0.3096 / 0.3262 |
| 局均 白 折扣 | 2.3047 / 2.3955 |
| 局均 蓝 折扣 | 2.1953 / 2.2520 |
| 局均 绿 折扣 | 2.2861 / 2.4072 |
| 局均 红 折扣 | 2.4541 / 2.3369 |
| 局均 黑 折扣 | 2.4902 / 2.3369 |


##### 全部七类动作

| 个人指标：模型 / 对手 | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) |
| --- | --- |
| 买市场 次数 | 10596 / 10716 |
| 买市场 占自身全部决策 | 38.100% / 38.526% |
| 买预留 次数 | 1416 / 1294 |
| 买预留 占自身全部决策 | 5.092% / 4.652% |
| 取宝石 次数 | 12206 / 12562 |
| 取宝石 占自身全部决策 | 43.889% / 45.163% |
| 预留市场 次数 | 3588 / 3234 |
| 预留市场 占自身全部决策 | 12.901% / 11.627% |
| 预留牌堆 次数 | 1 / 1 |
| 预留牌堆 占自身全部决策 | 0.004% / 0.004% |
| 选贵族 次数 | 4 / 8 |
| 选贵族 占自身全部决策 | 0.014% / 0.029% |
| 跳过 次数 | 0 / 0 |
| 跳过 占自身全部决策 | 0.000% / 0.000% |


##### 实测计时

| 模型 / 对手 | 进程耗时累计s | 单局均值s | 单局P95s | 决策 / 推理延迟 |
| --- | --- | --- | --- | --- |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) / Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | 357.032 | 0.3487 | 0.5248 | NOT_MEASURED / NOT_MEASURED |


单局时钟包括程序启动、比赛、验核和输出；累计单局秒数含并行重叠，不等于整批墙钟。未记录逐决策/推理延迟，不能填0或由单局时间推算。

#### 大牌购入时点与分段得分（双方个人指标）

| 个人指标：模型 / 对手 | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) |
| --- | --- |
| 24 Main 总VP AUC（描述性；非M62奖励） | 0.1985 / 0.2019 |
| 24 Main 大牌印刷VP AUC（描述性；非M62门） | 0.0756 / 0.0766 |
| 终局3～5VP牌印刷分合计 | 7.0615 / 6.9688 |
| 前24自身Main购入3～5VP牌数 | 1.2227 / 1.2285 |
| 首张3～5VP牌 自身Main（仅买到的局） | 18.5707 / 18.5422 |
| 首张3～5VP牌 覆盖局数 / 总局数（双方） | 976/1024 ; 972/1024 |
| 首张4～5VP牌 自身Main（仅买到的局） | 20.9699 / 20.4329 |
| 首张4～5VP牌 覆盖局数 / 总局数（双方） | 797/1024 ; 767/1024 |
| 自身Main 8 后局均总VP | 0.6377 / 0.6699 |
| 自身Main 8 后局均大牌印刷VP | 0.0547 / 0.0430 |
| 自身Main 8 实际达到局数（双方） | 1024 / 1024 |
| 自身Main 12 后局均总VP | 1.7734 / 1.8086 |
| 自身Main 12 后局均大牌印刷VP | 0.3750 / 0.3701 |
| 自身Main 12 实际达到局数（双方） | 1024 / 1024 |
| 自身Main 16 后局均总VP | 3.5439 / 3.4912 |
| 自身Main 16 后局均大牌印刷VP | 1.1631 / 1.0771 |
| 自身Main 16 实际达到局数（双方） | 1024 / 1024 |
| 自身Main 20 后局均总VP | 6.0869 / 6.2939 |
| 自身Main 20 后局均大牌印刷VP | 2.5195 / 2.7051 |
| 自身Main 20 实际达到局数（双方） | 1024 / 1024 |
| 自身Main 24 后局均总VP | 9.7080 / 9.8887 |
| 自身Main 24 后局均大牌印刷VP | 4.5488 / 4.5801 |
| 自身Main 24 实际达到局数（双方） | 996 / 996 |


每格为模型 / 对手。自身Main含购卡/取宝石/预留/跳过，不含贵族选择；贵族分计入前一个Main。短局在后续固定检查点用其终局分补足，并列实际达到该Main的局数。大牌仅含购入3～5VP卡的印刷VP，排除贵族；AUC按15VP截断、固定24分母。首牌时点只对买到的局取均值，必须连同覆盖率解读，不能单凭均值认定更快。

#### 基建投资与后续兑现（双方完整画像）

| 个人指标（被测模型 / 对手） | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) 对阵 Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) |
| --- | --- |
| building效用（归一化0..1，reward代理） | 0.454508 / 0.446533 |
| 早期bonus AUC12（原始永久折扣个数；非reward） | 1.951986 / 1.942464 |
| 真实折扣适用使用单位 / 局（全局cap24） | 10.908203 / 10.716797 |
| cap3/投资后、全局cap前使用单位 / 局 | 10.908203 / 10.716797 |
| 未截断真实折扣使用单位 / 局 | 16.487305 / 16.065430 |
| 前12Main真实购卡 / 局 | 4.404297 / 4.358398 |
| 早期≤1VP投资 / 局 | 3.926758 / 3.856445 |
| 兑现投资 / 局 | 3.908203 / 3.833008 |
| 未兑现投资 / 局 | 0.018555 / 0.023438 |
| 观察窗口删失投资 / 局 | 0.019531 / 0.021484 |
| 未兑现且删失投资 / 局 | 0.000000 / 0.000000 |
| Main13..24真实购卡印刷VP / 局 | 7.363281 / 7.552734 |
| Main13..24真实观察Main / 局 | 11.959961 / 11.959961 |
| Main25..32真实得分购卡印刷VP / 局 | 3.571289 / 3.523438 |
| Main25..32真实观察Main / 局 | 3.189453 / 3.189453 |
| Main25..32印刷VP / 真实观察Main（总分母） | 1.119718 / 1.104715 |
| 投资兑现 / 投资总数 | 99.5275% / 99.3923% |
| 未兑现 / 投资总数 | 0.4725% / 0.6077% |
| 删失 / 投资总数 | 0.4974% / 0.5571% |
| 短于12Main对局比例 | 0.0000% / 0.0000% |
| 未达24Main对局比例 | 2.7344% / 2.7344% |
| 未达32Main对局比例 | 98.7305% / 98.7305% |


每格是被测模型 / 对手，包含全部对局、早败和未兑现投资。奖励不padding；AUC12短局终局折扣保持仅作描述。

| 被测玩家 | 对手 | 本模型物理座位 | 局数 | 效用（模型/对手） | AUC12折扣（模型/对手） |
| --- | --- | --- | --- | --- | --- |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | 先手 P0 | 512 | 0.460368 / 0.436442 | 1.993652 / 1.901693 |
| Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) | 后手 P1 | 512 | 0.448649 / 0.456624 | 1.910319 / 1.983236 |


单局时钟含启动、比赛、验证和输出；累计单局秒含并行重叠。legacy决策轮=ceil(全plies/2)，Main排除choose_noble。每组纯胜/半平CI仅描述，不增加否决门；逐决策 / 推理 **NOT_MEASURED / NOT_MEASURED**。

| 字段 | 原始记录 |
| --- | --- |
| audit_metrics_wall_seconds | 124.3173749470152 |
| building_metrics_sha256 | c6275b7a000c857e8ecd96ac87b7875bb49b408a43bcc09516848378866e0381 |
| clock_scope | stage dispatch wall and subsequent saved-replay metric wall; no per-inference clock |
| dispatch_wall_seconds | 2761.2016689828597 |
| games | 8704 |
| match_details_sha256 | 2b4faaa830fe8b0775b2067db5b69b82754c1da541395df3454147372ecd20b6 |
| plan_sha256 | e13d0d892491b1917ad6587d6f79a82df79a0ae0f7b20934750358dd77f38f85 |
| source_ledger_sha256 | 3721675ee84c2deac31f2b93930e4c4733d917e5cafbc0ada420f59706b9d99d |
| style_metrics_sha256 | 001431aa60764a5fa112696994898fbacf7f55721b592bf58794473529c31045 |


### 时钟、负载和资源

| 字段 | 原始记录 |
| --- | --- |
| acceptance_policy/action_seed | 62042001 |
| acceptance_policy/anchor_total_games | 4608 |
| acceptance_policy/anchors | ["heuristic-v031", "prism-v01", "prism-general-v011"] |
| acceptance_policy/between_arms_games | 1024 |
| acceptance_policy/blocks | 256 |
| acceptance_policy/bootstrap_rng_seed | 62049999 |
| acceptance_policy/bootstrap_samples | 20000 |
| acceptance_policy/control_cohort_required | True |
| acceptance_policy/direct_alpha_games | 1024 |
| acceptance_policy/direct_blocks | 512 |
| acceptance_policy/direct_pairs/0 | ["control", "base"] |
| acceptance_policy/direct_pairs/1 | ["beta", "base"] |
| acceptance_policy/direct_pairs/2 | ["beta", "control"] |
| acceptance_policy/direct_pairs/3 | ["beta", "alpha"] |
| acceptance_policy/direct_parent_games | 2048 |
| acceptance_policy/direct_seed_end | 9641511 |
| acceptance_policy/direct_total_games | 4096 |
| acceptance_policy/enhancement_reporting | retention, confirmed enhancement, style and release verdicts separately; no gate relaxation |
| acceptance_policy/family_alpha | 0.05 |
| acceptance_policy/gates/beta/building_utility | 0.015 |
| acceptance_policy/gates/beta/direct_alpha | 0.45 |
| acceptance_policy/gates/beta/direct_control | 0.45 |
| acceptance_policy/gates/beta/direct_parent | 0.45 |
| acceptance_policy/gates/beta/early_bonus_auc12 | 0.25 |
| acceptance_policy/gates/beta/general_anchor | -0.075 |
| acceptance_policy/gates/beta/strength_pool | -0.05 |
| acceptance_policy/gates/control/direct_parent | 0.45 |
| acceptance_policy/gates/control/strength_pool | -0.05 |
| acceptance_policy/interval_sides | one-sided |
| acceptance_policy/lower_quantile | 0.005555555555555556 |
| acceptance_policy/models | ["base", "control", "beta"] |
| acceptance_policy/no_extension_or_checkpoint_selection | True |
| acceptance_policy/once_only_final_candidate | True |
| acceptance_policy/one_sided_claims | 9 |
| acceptance_policy/per_opponent_metrics | diagnostic only except frozen general_anchor gate |
| acceptance_policy/required_gates/beta | ["strength_pool", "general_anchor", "direct_control", "direct_alpha", "direct_parent", "building_utility", "early_bonus_auc12"] |
| acceptance_policy/required_gates/control | ["strength_pool", "direct_parent"] |
| acceptance_policy/seed_end | 9641255 |
| acceptance_policy/seed_start | 9641000 |
| acceptance_policy/shared_draws_for_equal_length_vectors | True |
| acceptance_policy/simultaneous_comparisons | 9 |
| acceptance_policy/total_games | 8704 |
| acceptance_policy/total_physical_budget | 11328 |
| acceptance_policy/unused_for_training | True |
| candidate_sha256/beta | 69a885b20527dda2e43fad9c00d7cc36537b45a0f5ccbaef4320001bef8836fb |
| candidate_sha256/control | 1ea1f493993f6930464baf942c0b36cb1f1db025109f458d9d42f746aba5e19f |
| clock_scope | owned service: dispatch, saved replay audits, metrics, one formal analysis |
| config_sha256 | 4f3ff90c89b017ad4b1fdb0f344b1ca84bc55ea641d5a1aee3b0bb50463eb408 |
| decision_time | NOT_MEASURED |
| elapsed_wall_seconds | 3084.9182872748934 |
| execution_sha256 | b65daae1148a1467df4d64d51a0fbf3fa62bb9a9400060d07fcc3f4666f22cfd |
| finished_at | 2026-10-04T06:05:04.792263+00:00 |
| format | m62-building-evaluation-result-v1 |
| inference_time | NOT_MEASURED |
| physical_games | 9280 |
| resources/cgroup | /sys/fs/cgroup/user.slice/user-1001.slice/user@1001.service/app.slice/prism-m62-evaluation-b65daae1.service |
| resources/cpu_seconds | 5461.311994 |
| resources/host_available_memory_bytes | 11043618816 |
| resources/memory_current_bytes | 1277861888 |
| resources/memory_events/high | 0 |
| resources/memory_events/low | 0 |
| resources/memory_events/max | 0 |
| resources/memory_events/oom | 0 |
| resources/memory_events/oom_group_kill | 0 |
| resources/memory_events/oom_kill | 0 |
| resources/memory_events/sock_throttled | 0 |
| resources/memory_peak_bytes | 1727156224 |
| resources/storage_bytes | 22654240132 |
| retries | 0 |
| started_at | 2026-10-04T05:13:36.673063+00:00 |
| status | COMPLETED_FIXED_BUILDING_EVALUATION |
| training_artifact_audit/path | /home/ubuntu/splendor-ppo-m62/training-artifact-audit.json |
| training_artifact_audit/sha256 | a6e1d53eefdab050179cccc75bd54ccc28dd1312ab2ddabba4ac2690ded3b0de |


评测服务8GiB/CPU200%/2workers/8h/40,000CPU-s/32GiB。资源账与训练各臂分开；缺失延迟NOT_MEASURED。

### 冻结身份、源码和执行合同

| 字段 | 原始记录 |
| --- | --- |
| assets/alpha/path | /home/ubuntu/splendor-ppo-m62/inputs/alpha.json |
| assets/alpha/sha256 | d3a313090bb2ccae678d3b9cf1216f0a60527ec330432c5c2dcdddd85b53b2d9 |
| assets/fixtures/path | /home/ubuntu/splendor-ppo-m62/inputs/fixtures.jsonl |
| assets/fixtures/sha256 | 81c3f01dcd0d31fcb7dc54acfd125892a2692ff13e31a996889282d35ea817c1 |
| assets/general/path | /home/ubuntu/splendor-ppo-m62/inputs/general.json |
| assets/general/sha256 | a2301f0878f9c342a61b83fd45412f72ba95acfca895dafbe7ceca0360f34a85 |
| assets/initial/path | /home/ubuntu/splendor-ppo-m62/inputs/initial.json |
| assets/initial/sha256 | 5db70b773083858b83c6e679d5641f1b78d4c5fbe34c48950cc906064f821b54 |
| assets/parent/path | /home/ubuntu/splendor-ppo-m62/inputs/parent.json |
| assets/parent/sha256 | 225daf49e8746576b1edc3508ca0454715e5454529fea53dc7dfeb9043cf01f1 |
| audit_path | /home/ubuntu/splendor-ppo-m62/training-artifact-audit.json |
| audit_sha256 | a6e1d53eefdab050179cccc75bd54ccc28dd1312ab2ddabba4ac2690ded3b0de |
| binaries/economy/path | /home/ubuntu/splendor-ppo-m57/build/release/examples/s4_batch_metrics |
| binaries/economy/sha256 | ba3f2cbe49e5839ae0b5ca220425c5e79ec901f368eabfc12bc2463c0fe265dc |
| binaries/engine/path | /home/ubuntu/splendor-ppo-m57/build/release/splendor |
| binaries/engine/sha256 | 1a13af46327650c20675994b3347047ecadd5068e701ad3808322ec8ac528d4b |
| binaries/projection/path | /home/ubuntu/splendor-ppo-m62-projection-source/projection-target/release/examples/prism_building_projection |
| binaries/projection/sha256 | a6fd9690bd687dd786f90df9cf822e4e18470c83c3dbef53e079196a7df729a1 |
| binaries/style/path | /home/ubuntu/splendor-ppo-m57/build/release/examples/prism_bigcard_metrics |
| binaries/style/sha256 | 5510f847e31981bb223147639ef1e20c1b7317b5fe2a24d12668f4293919ad5a |
| building_style/diagnostic_early_bonus_padding | held-at-terminal |
| building_style/early_max_printed_vp | 1 |
| building_style/early_window_main_actions | 12 |
| building_style/format | prism-building-style-v1 |
| building_style/global_use_cap | 24 |
| building_style/per_investment_use_cap | 3 |
| building_style/phase_semantics | choose_noble-belongs-to-preceding-main |
| building_style/redemption_horizon_main_actions | 24 |
| building_style/short_game_padding | none |
| building_style/style_reward_input | player-visible-own-purchases-and-prepurchase-bonuses |
| building_style/terminal_only | True |
| candidate_selection | fixed audited final c4; no tuning |
| candidate_sha256/beta | 69a885b20527dda2e43fad9c00d7cc36537b45a0f5ccbaef4320001bef8836fb |
| candidate_sha256/control | 1ea1f493993f6930464baf942c0b36cb1f1db025109f458d9d42f746aba5e19f |
| candidates/base/display_name | Prism Balance v0.1.0 (T=1) |
| candidates/base/path | /home/ubuntu/splendor-ppo-m62/inputs/parent.json |
| candidates/base/sha256 | 225daf49e8746576b1edc3508ca0454715e5454529fea53dc7dfeb9043cf01f1 |
| candidates/beta/display_name | Prism Beta v0.1.0 candidate (unpublished final-c4; T=1) |
| candidates/beta/path | /home/ubuntu/splendor-ppo-m62/campaigns/m62-beta-building-g0/cycle-4-export/weights.json |
| candidates/beta/sha256 | 69a885b20527dda2e43fad9c00d7cc36537b45a0f5ccbaef4320001bef8836fb |
| candidates/control/display_name | Prism Balance v0.1.1 candidate (unpublished final-c4; T=1) |
| candidates/control/path | /home/ubuntu/splendor-ppo-m62/campaigns/m62-control-building-g0/cycle-4-export/weights.json |
| candidates/control/sha256 | 1ea1f493993f6930464baf942c0b36cb1f1db025109f458d9d42f746aba5e19f |
| config_sha256 | 4f3ff90c89b017ad4b1fdb0f344b1ca84bc55ea641d5a1aee3b0bb50463eb408 |
| cpu_quota_percent | 200 |
| cpu_seconds | 40000 |
| created_at | 2026-10-04T05:12:44.103622+00:00 |
| diagnostic_bigcard_style/diagnostic_horizon_main_actions | 20 |
| diagnostic_bigcard_style/diagnostic_score_threshold | 8 |
| diagnostic_bigcard_style/format | prism-rush-style-v1 |
| diagnostic_bigcard_style/phase_semantics | choose_noble-belongs-to-preceding-main |
| diagnostic_bigcard_style/score_cap | 15 |
| diagnostic_bigcard_style/short_game_padding | terminal-prestige |
| diagnostic_bigcard_style/style_reward_input | player-visible-own-prestige-and-terminal-own-prestige |
| diagnostic_bigcard_style/terminal_only | True |
| diagnostic_bigcard_style/window_main_actions | 24 |
| evaluation/acceptance/action_seed | 62042001 |
| evaluation/acceptance/anchor_total_games | 4608 |
| evaluation/acceptance/anchors | ["heuristic-v031", "prism-v01", "prism-general-v011"] |
| evaluation/acceptance/between_arms_games | 1024 |
| evaluation/acceptance/blocks | 256 |
| evaluation/acceptance/bootstrap_rng_seed | 62049999 |
| evaluation/acceptance/bootstrap_samples | 20000 |
| evaluation/acceptance/control_cohort_required | True |
| evaluation/acceptance/direct_alpha_games | 1024 |
| evaluation/acceptance/direct_blocks | 512 |
| evaluation/acceptance/direct_pairs/0 | ["control", "base"] |
| evaluation/acceptance/direct_pairs/1 | ["beta", "base"] |
| evaluation/acceptance/direct_pairs/2 | ["beta", "control"] |
| evaluation/acceptance/direct_pairs/3 | ["beta", "alpha"] |
| evaluation/acceptance/direct_parent_games | 2048 |
| evaluation/acceptance/direct_seed_end | 9641511 |
| evaluation/acceptance/direct_total_games | 4096 |
| evaluation/acceptance/enhancement_reporting | retention, confirmed enhancement, style and release verdicts separately; no gate relaxation |
| evaluation/acceptance/family_alpha | 0.05 |
| evaluation/acceptance/gates/beta/building_utility | 0.015 |
| evaluation/acceptance/gates/beta/direct_alpha | 0.45 |
| evaluation/acceptance/gates/beta/direct_control | 0.45 |
| evaluation/acceptance/gates/beta/direct_parent | 0.45 |
| evaluation/acceptance/gates/beta/early_bonus_auc12 | 0.25 |
| evaluation/acceptance/gates/beta/general_anchor | -0.075 |
| evaluation/acceptance/gates/beta/strength_pool | -0.05 |
| evaluation/acceptance/gates/control/direct_parent | 0.45 |
| evaluation/acceptance/gates/control/strength_pool | -0.05 |
| evaluation/acceptance/interval_sides | one-sided |
| evaluation/acceptance/lower_quantile | 0.005555555555555556 |
| evaluation/acceptance/models | ["base", "control", "beta"] |
| evaluation/acceptance/no_extension_or_checkpoint_selection | True |
| evaluation/acceptance/once_only_final_candidate | True |
| evaluation/acceptance/one_sided_claims | 9 |
| evaluation/acceptance/per_opponent_metrics | diagnostic only except frozen general_anchor gate |
| evaluation/acceptance/required_gates/beta | ["strength_pool", "general_anchor", "direct_control", "direct_alpha", "direct_parent", "building_utility", "early_bonus_auc12"] |
| evaluation/acceptance/required_gates/control | ["strength_pool", "direct_parent"] |
| evaluation/acceptance/seed_end | 9641255 |
| evaluation/acceptance/seed_start | 9641000 |
| evaluation/acceptance/shared_draws_for_equal_length_vectors | True |
| evaluation/acceptance/simultaneous_comparisons | 9 |
| evaluation/acceptance/total_games | 8704 |
| evaluation/acceptance/total_physical_budget | 11328 |
| evaluation/acceptance/unused_for_training | True |
| evaluation/anchor_modes/heuristic-v031 | greedy |
| evaluation/anchor_modes/prism-general-v011 | T1, action seed 62042001 |
| evaluation/anchor_modes/prism-v01 | greedy |
| evaluation/candidate_and_parent_mode | agent-prism-sample T1, action seed 62042001 |
| evaluation/development/action_seed | 62042001 |
| evaluation/development/anchors | ["heuristic-v031", "prism-v01", "prism-general-v011"] |
| evaluation/development/blocks | 32 |
| evaluation/development/models | ["base", "control", "beta"] |
| evaluation/development/seed_end | 9636031 |
| evaluation/development/seed_start | 9636000 |
| evaluation/development/selection | descriptive only; final c4 fixed before samples; no tuning |
| evaluation/development/total_games | 576 |
| evaluation/native_path_and_sha256/path | /home/ubuntu/splendor-ppo-m57/build/release/splendor |
| evaluation/native_path_and_sha256/sha256 | 1a13af46327650c20675994b3347047ecadd5068e701ad3808322ec8ac528d4b |
| evaluation/selection | only final c4; no tuning, checkpoint selection or grid extension |
| evaluation/status | NOT_RUN |
| evaluation/total_games | 9280 |
| files//home/ubuntu/splendor-ppo-m57/build/release/examples/prism_bigcard_metrics | 5510f847e31981bb223147639ef1e20c1b7317b5fe2a24d12668f4293919ad5a |
| files//home/ubuntu/splendor-ppo-m57/build/release/examples/s4_batch_metrics | ba3f2cbe49e5839ae0b5ca220425c5e79ec901f368eabfc12bc2463c0fe265dc |
| files//home/ubuntu/splendor-ppo-m57/build/release/splendor | 1a13af46327650c20675994b3347047ecadd5068e701ad3808322ec8ac528d4b |
| files//home/ubuntu/splendor-ppo-m62-projection-source/projection-target/release/examples/prism_building_projection | a6fd9690bd687dd786f90df9cf822e4e18470c83c3dbef53e079196a7df729a1 |
| files//home/ubuntu/splendor-ppo-m62/audit-beta/checkpoint-validation.json | 6c2cb0d717e1f05a8b03a1113729934c69766150019b76c81b55083893f6e456 |
| files//home/ubuntu/splendor-ppo-m62/audit-beta/final-parity.json | 54377f3d556a08826aa6961244dbbed4d1244416e2234d195f871dceb629fa5f |
| files//home/ubuntu/splendor-ppo-m62/audit-beta/training-audit.json | d557706bb0b912de2394439a17deadb3e797bfc562838449fd37847bd2a7fe96 |
| files//home/ubuntu/splendor-ppo-m62/audit-beta/training-source-ledger.json | 852fd7d6e51f426cd16efbe6838acebacbebfe567ffcdece1fd64489f4a019b9 |
| files//home/ubuntu/splendor-ppo-m62/audit-control/checkpoint-validation.json | bac1f40b4ee88706ffc5722925f4b2650bf66231d51719c97268f079f2253d73 |
| files//home/ubuntu/splendor-ppo-m62/audit-control/final-parity.json | 2c40c96d2ecf7fa27eef5bb2e4b1575e5b4e01e5cdec75e4d68f7f09d5c32e43 |
| files//home/ubuntu/splendor-ppo-m62/audit-control/training-audit.json | daed3281b1f1a373a0c7effa67b459016920a381ec719720bbc36d489caf30bb |
| files//home/ubuntu/splendor-ppo-m62/audit-control/training-source-ledger.json | ef58d8a3ea1a2d6c490b97e3c444c932d399832ba3ca3609e0ad38fca366693b |
| files//home/ubuntu/splendor-ppo-m62/benchmarks/m62-prism-beta-building.config.json | 4f3ff90c89b017ad4b1fdb0f344b1ca84bc55ea641d5a1aee3b0bb50463eb408 |
| files//home/ubuntu/splendor-ppo-m62/benchmarks/m62-prism-beta-building.train.json | c0f98b641ea2504fa111df8e47b16bcfc1588bb155ea6e234b63b5fadaacae20 |
| files//home/ubuntu/splendor-ppo-m62/benchmarks/m62-prism-control-building.train.json | 48d58866e19e7ea064a2714afb634321139f2390f054586779631ed18b2af53b |
| files//home/ubuntu/splendor-ppo-m62/campaigns/m62-beta-building-g0/control/status.json | 1fcac4b606580c4cd30d8ee8f0b58bbf24ca49107fc538664fee129cad198375 |
| files//home/ubuntu/splendor-ppo-m62/campaigns/m62-beta-building-g0/cycle-4-export/weights.json | 69a885b20527dda2e43fad9c00d7cc36537b45a0f5ccbaef4320001bef8836fb |
| files//home/ubuntu/splendor-ppo-m62/campaigns/m62-control-building-g0/control/status.json | c87713e39eeab4d59904ba3cba397fe476a85879306a8cde977f8d0a229d5fea |
| files//home/ubuntu/splendor-ppo-m62/campaigns/m62-control-building-g0/cycle-4-export/weights.json | 1ea1f493993f6930464baf942c0b36cb1f1db025109f458d9d42f746aba5e19f |
| files//home/ubuntu/splendor-ppo-m62/crates/splendor-cli/examples/prism_building_projection.rs | ad08c55dd0cf0e22371352614db9104105b62bf92893b07450b4cb5c4ea7817b |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/anchors-0.json | 56d1c9bb5611d279d935aff86a1566aeafbd3e87c14eedaf143c1fefff71b0db |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/anchors-1.json | abb7055cebee48cce4396411b5ed613c07686c45c7235eb7f34392d3d7cf50c2 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/anchors-2.json | 4254adc775e7463950290876c560afd55048434b54eb4fae841f3f51fb5c0995 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/anchors-3.json | c4ddbbbdc2c86c8572246521cfcadf08468d43c41650700ebee6855b1a0d22ba |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/anchors-4.json | 5032a855f980d8b845af50db6c9c79e6fdd1023055bb7c35738b78eb3d79afa6 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/anchors-5.json | f53ec8d86c265ba74c737317287053f7449d984378cabb62c180afa8c68952df |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/anchors-6.json | 1ea83b928bac202bbb287359fb5857ecaa0915802549417e4845463c9c9eae25 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/anchors-7.json | e0a250ebbf9f1f5a4add3676e1fb3230eb894d4042e9650922adb180f05c3cde |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-alpha-0.json | 2fdc5cbe6af3961e17457431237bcc6b443a7c8e76be62c9775ca8c1a92c2ae8 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-alpha-1.json | ca7fb69780a4bd1c3236d1a6c444b7ce4f2efe4502b6beb45d2031d0963257e6 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-alpha-10.json | 6b60e4600888c341eb6bec942d400bcb05c6f17548b9edcb0af73352a5e75e20 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-alpha-11.json | cd2d84e34db7de673eaf6a6729ebd7aed380074bfec3f7afae1b1b45297e2ece |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-alpha-12.json | 525e6e1c4e6d9f718b6d7ff446c638908915e53ff4fae9668fc41029e205abb6 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-alpha-13.json | 0e30371766a99573fc74cb3005a9086b7b63f48e2ff3db175b9d2bba13f75508 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-alpha-14.json | e214768d310d0b23e8d87be3366ba226a0ae3e1ce52e24d461f6bc4c974cb660 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-alpha-15.json | 4d3416351730389781fdcd91b4df245b5361cb0b52dff03e80260569f1cb6fde |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-alpha-2.json | 48f19f0da4303fcca1b096a5b610c4f7f9fd6db8eb20828caeeeaa669c373d44 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-alpha-3.json | 76e59810634ee3fc50d5e047bfa47670812d0a08980adb58155c1866a29c3554 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-alpha-4.json | 0bc147bb35d33d10cb2f2af09568ecb356b5ed7e425ebdb2d517aa417d4b1e65 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-alpha-5.json | aa55d2571b1042385c9391a2c381b0b7bb06e34154eca37073086716bf0ae1a9 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-alpha-6.json | 6aa2222699e2ac685971d1e6d9bc7b84ef864c7cb488d8c358ef0ddbb50a781a |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-alpha-7.json | b87de28d00986cf3f3489f96f23a52d2c59a7edb9dab1906540b0651e23469a2 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-alpha-8.json | 847246b97184f08902e97af6c7340b518935d9735c20e22b4bd6311420715ca6 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-alpha-9.json | c0bfe2f75830cb2dece9968b6cbf57ccafb8ef06a746d94e556a852f5c12f13a |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-control-0.json | e3ed3059bf50ac639abdf5b06a267f7be485ef8bc8ba8b5a3ac764a139b6c95e |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-control-1.json | d910f40225c4b824c11c2a41e8040cf201232548e035885161c8f67be2695c63 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-control-10.json | b8c63f0faf3bcdce48f0977063d21a7e4e556cf3183f89df63375abe739712af |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-control-11.json | bcd3e88366fb9db392a433a81f1f48f28e2573b1bf6f077ab11582a218e677a6 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-control-12.json | 95045025f59ce9cb6de2a7cf97b2dd5670c58981f93560d0e3656ec14202e271 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-control-13.json | 8bd465d2763206c275431cd8e12c3498537d738a9e8c124361a56e1b12ddd175 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-control-14.json | e0a3711517a8dcdacf79b109df5aeca3872d4b331524c76c7f26ae6779e9645c |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-control-15.json | 5bf31a65e263f6b52efecb7c0693cd5a90cd37eb98ae44e654928784f6269104 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-control-2.json | 0edcb07e477b9cbb03d9be3f6e1e64ca8febda5ffcc4c753a8fb9e617025821e |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-control-3.json | 3ba562dbc7f284e31bb7937579499a676fadafc408005d76c401ce335812428b |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-control-4.json | 9048a0ffc3b4ef57614dd8cac0207ac038116b61ecc04d1bf22fceeacdd81427 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-control-5.json | 5f8a18ca82d3d2ac2a86303e7af069c592f2921652e1d7ea65673d54c65ace5c |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-control-6.json | 1b5d07ce9b7d60f865c8f72bc1353f56531a4ead4781c5ff7e5a6731b094683a |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-control-7.json | adade69e764136ca46870e488a4889513123bc862cd3a1bdc97bb38a6f546026 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-control-8.json | ac7d613ada4abe5d6e5c04aefecb1edaf6d70166baf761cc6b905fb428707e7c |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-control-9.json | 7f0b93455862ae3b9814a673c916e95eed65298d70b6b0901c21b235904101e7 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-parent-0.json | 32df3d68fcfe2118720d311acd7f1e4f8dc20ddf2ab7547de18d61de47f47119 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-parent-1.json | d0b9699d60e9c9f4306f82629650334915854297027338e1cc37c379de1f8b1c |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-parent-10.json | 19bcc6178a9a4e94cc0a9752902a4d821c2092a43560e699d30a759c24494554 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-parent-11.json | d8c36df42b723db110d94faa03256d1152f869aa43a8b93abaaf40d43906a8b7 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-parent-12.json | b629b2c7a25ad14a4c1c389dcd34828b3e3a238890d875798a9e77d6ed56a597 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-parent-13.json | 30c3efdc35a092c68dcafc756ecfe40e93abb98405877041519b1a63e9045bb6 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-parent-14.json | 43d72f767bb218b3be1bac5e06ea9a071cd9d325767d2e6199be5447c47377d1 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-parent-15.json | b02c6009bf8fae15d6651a87b2c5f3ed35a8b29359886650d001ca562c90373b |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-parent-2.json | e8971a5464bece1695dc47c24c16a7294a8461567221d9dde34eb0e0047ef7db |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-parent-3.json | 47f8188dae39965c47a0ee4630f45074148634f27ae92edb7659522ef62642d8 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-parent-4.json | 230d70697a152fc52feef1055f2153b9eceea93e5c8ae29febb2485355b53a89 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-parent-5.json | 8ddef9a08993598821f1894731e9373f2447768b5e9f17c5ed2d4d2c09cb2ab7 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-parent-6.json | 6dde7e02406ebc44cd60ea30df0a8dae867fcff48c8a4c1598bad112bf1b5bb5 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-parent-7.json | c88401c493b81d042206ca3b53696d228d81a2a96662d24368b773c86c15f8ed |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-parent-8.json | 1f92152079c1cbea0abfaa1775bf0844ca21f7fd2cc9f64ff26dfc2fc001b6cb |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/configs/direct-parent-9.json | c380b85843052c097e4aee6f45c7d54436898127537f10904d3e99ff94396114 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/acceptance/plan.json | e13d0d892491b1917ad6587d6f79a82df79a0ae0f7b20934750358dd77f38f85 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/build/release/examples/prism_bigcard_metrics.exe | 5510f847e31981bb223147639ef1e20c1b7317b5fe2a24d12668f4293919ad5a |
| files//home/ubuntu/splendor-ppo-m62/evaluation/building-style.json | dea1449c5406c6d4bece38066476b78aa530f52730a22727259259fad9fd1307 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/collector-root/local-artifacts/prism/v01/bin/s4_batch_metrics.exe | ba3f2cbe49e5839ae0b5ca220425c5e79ec901f368eabfc12bc2463c0fe265dc |
| files//home/ubuntu/splendor-ppo-m62/evaluation/development/configs/anchors-0.json | 72d6374f16736c271e71f26798d44adb42a1fd9b61979af92f9ad8980a5451c4 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/development/configs/anchors-1.json | cb3c2332e240cc6d4fb7d57066864bb1dc27689a33e1ec310b59fe5cc0a96dd6 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/development/plan.json | 953128f3d23cb60f9dac21a78190a4b804ef8bde57c2d14b6465dfebaa96aac2 |
| files//home/ubuntu/splendor-ppo-m62/evaluation/style.json | 320818f1f7fbbb826d1bf0c77bc2e57004bb97f6eb615cce961f50755a55ca6a |
| files//home/ubuntu/splendor-ppo-m62/inputs/alpha.json | d3a313090bb2ccae678d3b9cf1216f0a60527ec330432c5c2dcdddd85b53b2d9 |
| files//home/ubuntu/splendor-ppo-m62/inputs/fixtures.jsonl | 81c3f01dcd0d31fcb7dc54acfd125892a2692ff13e31a996889282d35ea817c1 |
| files//home/ubuntu/splendor-ppo-m62/inputs/general.json | a2301f0878f9c342a61b83fd45412f72ba95acfca895dafbe7ceca0360f34a85 |
| files//home/ubuntu/splendor-ppo-m62/inputs/initial.json | 5db70b773083858b83c6e679d5641f1b78d4c5fbe34c48950cc906064f821b54 |
| files//home/ubuntu/splendor-ppo-m62/inputs/parent.json | 225daf49e8746576b1edc3508ca0454715e5454529fea53dc7dfeb9043cf01f1 |
| files//home/ubuntu/splendor-ppo-m62/local-artifacts/prism/building-beta-m62/projection-build-receipt.json | 70339adaf88afe685488e2ae3947535fe3e166c252953099c5d5364ad6879f19 |
| files//home/ubuntu/splendor-ppo-m62/local-artifacts/prism/building-beta-m62/projection-smoke-output.json | 82de222b5f84d0aa725378cb51328236fd71d316d6c636b74249c45eded2bb16 |
| files//home/ubuntu/splendor-ppo-m62/local-artifacts/prism/building-beta-m62/projection-smoke-receipt.json | 04bf1e6d1748ad6f8a2f61ee53b04aa0a33bb9e2984236270759e9d720988362 |
| files//home/ubuntu/splendor-ppo-m62/local-artifacts/prism/building-beta-m62/projection-source-receipt.json | 1fd5cd61a5de47138b129f82053624bcaa4c83335215684470e0e863a2e6c08f |
| files//home/ubuntu/splendor-ppo-m62/local-artifacts/prism/building-beta-m62/projection-test-manifest.json | 5f140adc7639b62e64c16717e84edcc481f4cc9a1196a9be2f0f578b75c80e07 |
| files//home/ubuntu/splendor-ppo-m62/scripts/prism_alpha_report.py | 3db06fa0f2c0a2d741377f971be5d74282f473b72bbf5dbb8777f175887add2e |
| files//home/ubuntu/splendor-ppo-m62/scripts/prism_alpha_round.py | 5f07a8bf643839f418cd486f9313356f3358592bec8b82220bfb65d3f5ad40cb |
| files//home/ubuntu/splendor-ppo-m62/scripts/prism_balance_ab_evaluation_m61.py | d7ff23e9aec80352005b296caa6f79b0dfec5ab0e9867d910ea260cad65bbde9 |
| files//home/ubuntu/splendor-ppo-m62/scripts/prism_balance_ab_report_m61.py | 118e4b03291906659607b6698d37d8dd7dac1ac74b1bbee27cde7c9db907ce05 |
| files//home/ubuntu/splendor-ppo-m62/scripts/prism_building_audit_m62.py | 515d5a3ba93b424024b8ee575ae46d94854fb7d8ade6bcc81744bac19f31a215 |
| files//home/ubuntu/splendor-ppo-m62/scripts/prism_building_evaluation_m62.py | a863313e6eb9db629791c3c2dcca56dc046a02ecb4fdc43bc132fc3529c97b61 |
| files//home/ubuntu/splendor-ppo-m62/scripts/prism_building_metrics_m62.py | e3cb89301e6326caa6be6dd691c1e727e238bcd8e57c8cf415e2b33b441ece4a |
| files//home/ubuntu/splendor-ppo-m62/scripts/prism_building_prepare_m62.py | 1babd40782567cc9c8d29219191822ddbf36ce42260cce2452247bcd497066d6 |
| files//home/ubuntu/splendor-ppo-m62/scripts/prism_building_report_m62.py | d985875025a1ee6b0f51a97b3623054e2cd29bad693e53b6047b97f484f666ce |
| files//home/ubuntu/splendor-ppo-m62/scripts/prism_building_training_report_m62.py | 910cc13d1f805ffabae6cabb0688ba0e2a4197f9f982cf206406a42ed89d37bc |
| files//home/ubuntu/splendor-ppo-m62/scripts/prism_cloud_storage_snapshot.py | b417e62c6aa2ce56ad2968ab0ac4c952b4a954514128a6923efc272129f5eb8c |
| files//home/ubuntu/splendor-ppo-m62/scripts/prism_match_details.py | 0f7fb79de0a65e60dfcb914716c99562fa44dd7673e6c1c0ea5ee4916ba11bc4 |
| files//home/ubuntu/splendor-ppo-m62/scripts/prism_portable_report.py | 603210f2a363327d9d7a46ae0c42c0b97b38341f06a90b541627cbe4285d6286 |
| files//home/ubuntu/splendor-ppo-m62/scripts/prism_ppo_fixed_eval.py | fb6683d0f0d91d92efafef1d136545b3dabf376e014e066b19beb43fe78aeacb |
| files//home/ubuntu/splendor-ppo-m62/scripts/prism_rush_report.py | 4dd5aef6d7846d157463c1944e4628f0a43c041363c1837bde8efc79268143a5 |
| files//home/ubuntu/splendor-ppo-m62/scripts/prism_rush_round.py | 1613720a7e0f7f6f85e9926db7b9b1b641350247c19a0d495e2be702efab98d5 |
| files//home/ubuntu/splendor-ppo-m62/training-artifact-audit.json | a6e1d53eefdab050179cccc75bd54ccc28dd1312ab2ddabba4ac2690ded3b0de |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/__init__.py | 64a650d0a0cc8c8315ff9cfc743064765a56a7f8256783d4e7cbc7366bedb65a |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/cgroup_entry.py | 32474e0502d2aeffa715502153fbff73753250699383253b3129a3dfcd4d9c42 |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/common.py | 6fda3c48a32af6b214d0a256095cb28ed09409d8bad07836be9c3d28e235a4ec |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/control.py | d63a24d52cfcbb426790f0bd3f395a30a9081b4bce1c4659e2b96b8523f4efb6 |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/engine/__init__.py | 27ca54e16b13e17e76347fb3d2ecfede6097c957dd93f14601ebcb17931e0004 |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/engine/data.py | 573a11980bc26268a3c278c9a9cb28efab4501827c316039e0bf26a15dfadc98 |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/engine/export.py | 309afa200c6d22bf5c7802d2091e03098ba6a3dedb7885e4f361eaadffad75e1 |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/engine/io.py | 2b96ab284f8c4f79ef4e81c5726c4ae51b176fa56c95b546c01f6391df199e7d |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/engine/model.py | 1d39ada9f306f3ad642be43a6038704dcd371c8263ac1b9ad23a07fd237bf5cb |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/engine/parity.py | 37aabbc1f374e20886532d6f66e681b068a36ff5e499266861c385de99f9917f |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/engine/ppo/__init__.py | 987ad20304f6df104762ca1910ca53e6af5c5c82f88f1f0f1ecc42840cb2ad5a |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/engine/ppo/__main__.py | 7cb07b189d3e75a0d733184344f26eee4d0193e0ab4158538c6e4538dd27ec7a |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/engine/ppo/arena.py | 9d4157cf9df9791c61804913e07bbd50c9429a4ff1919d1a5440afbe28b8a3cb |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/engine/ppo/audit.py | 7c9280f23c15024f35b73ad6a86cade04fb224ea2e88550ab370a06439388267 |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/engine/ppo/building.py | 7b57fd996ec497b8e7332e62f8a466e4a4d04f77a883b5c768c3f59b4399d8b8 |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/engine/ppo/contract.py | 94f22a2e7f02fb2980c465020d71af3ce8352b5046d0103dddf15d46cdc460df |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/engine/ppo/coordinator.py | b90d38fa40ae03e3f34046f087a40f68e2d551b158f656a838084dbc1945be85 |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/engine/ppo/execution.py | f1c60e7546755d02625985cb50d082c4b44b1aa13f6162a61c55596e0d14a71e |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/engine/ppo/learner.py | 1942662bb7e0bb16d1ef4b436f52eb8beee656ab4e59ace4f6728af54c53879c |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/engine/ppo/model.py | eb48413f7e4c8b164133392bc4b532364752de5cfa337c399cdc9c802a514c55 |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/engine/ppo/processes.py | 50f08f1a23e750e9458ed5ac8a49128401ebc80fa3b00234b31d42430a7bac33 |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/engine/ppo/runtime.py | dc46fc770243e3284a74e4049caa102f9692c8d2c469c034dfcaf3d0e5b58ab8 |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/engine/ppo/sampling.py | c649d69debf0f5d5c2353b25443e438e2cd530cf9ca14e896b65cdc3f29f02e4 |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/engine/ppo/service.py | f524a353557af2a94f41b59534a98e327e675653a78bf8b6fc4e1f67ba2416ba |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/engine/ppo/store.py | 4b4b47ca45fad2e4a7126a6fe858d928db6121e05ad7e75a2eac9db49c9ec91d |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/engine/ppo/style.py | 99176794467a9da38ed9f87973c6d197888e2294259b1d1c2e097fefbf6bea91 |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/processes.py | e2bb5e2bcce66b501a25d2b8731d48e033c15a1182108ff53a31a35467f2fe0d |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/protocol.py | ff00386e023cb0818f786c93aafb5a0434eda1cfb1beb5e47442d74f2a78a80b |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/provision.py | adb9880b6de9e4cc08d87e01a99880dce755b34ac999fd44a4344b71adc0901a |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/rpc.py | 54a054337fc90f7ba4180c9826467daa5af13488b2031c5d142827fcb4ab66e2 |
| files//home/ubuntu/splendor-ppo-m62/training/prism_portable/worker.py | 3fcdfcb71276782fb088e6862d77172e77993c88a29f97ed6c0c702950e1202b |
| format | m62-building-evaluation-execution-v1 |
| infrastructure_retries | 0 |
| memory_bytes | 8589934592 |
| physical_games | 9280 |
| projection_source_snapshot/files/crates/splendor-cli/examples/prism_building_projection.rs | ad08c55dd0cf0e22371352614db9104105b62bf92893b07450b4cb5c4ea7817b |
| projection_source_snapshot/files/local-artifacts/prism/building-beta-m62/projection-build-receipt.json | 70339adaf88afe685488e2ae3947535fe3e166c252953099c5d5364ad6879f19 |
| projection_source_snapshot/files/local-artifacts/prism/building-beta-m62/projection-smoke-output.json | 82de222b5f84d0aa725378cb51328236fd71d316d6c636b74249c45eded2bb16 |
| projection_source_snapshot/files/local-artifacts/prism/building-beta-m62/projection-smoke-receipt.json | 04bf1e6d1748ad6f8a2f61ee53b04aa0a33bb9e2984236270759e9d720988362 |
| projection_source_snapshot/files/local-artifacts/prism/building-beta-m62/projection-source-receipt.json | 1fd5cd61a5de47138b129f82053624bcaa4c83335215684470e0e863a2e6c08f |
| projection_source_snapshot/files/local-artifacts/prism/building-beta-m62/projection-test-manifest.json | 5f140adc7639b62e64c16717e84edcc481f4cc9a1196a9be2f0f578b75c80e07 |
| source_files | ["scripts/prism_building_evaluation_m62.py", "scripts/prism_building_metrics_m62.py", "scripts/prism_building_report_m62.py", "scripts/prism_balance_ab_evaluation_m61.py", "scripts/prism_balance_ab_report_m61.py", "scripts/prism_cloud_storage_snapshot.py", "scripts/prism_alpha_round.py", "scripts/prism_ppo_fixed_eval.py", "scripts/prism_match_details.py", "scripts/prism_rush_round.py", "scripts/prism_alpha_report.py", "scripts/prism_rush_report.py", "training/prism_portable/__init__.py", "training/prism_portable/engine/__init__.py", "training/prism_portable/engine/ppo/__init__.py", "training/prism_portable/engine/ppo/building.py", "training/prism_portable/engine/ppo/contract.py", "training/prism_portable/engine/data.py", "training/prism_portable/engine/io.py"] |
| storage_bytes | 34359738368 |
| wall_seconds | 28800 |
| workers | 2 |


Heuristic v0.3.1为策略身份；Hello 0.2.9为协议常量。Prism runtime Hello不替代权重SHA。新projection只读重演保存回放，独立工具源码/binary分别pin，不将其身份伪称为旧arena。M61原合同、失败与报告保持其历史判定。

### 输入与报告来源

| 证据 | 路径 / SHA256 |
| --- | --- |
| result.json | /home/ubuntu/splendor-ppo-m62/evaluation/result.json / 4306fcff0eb53bbeca9113f58e5b05c97a9bf22d2d6e7fe67999ac563a790ede |
| execution.json | /home/ubuntu/splendor-ppo-m62/evaluation/execution.json / b65daae1148a1467df4d64d51a0fbf3fa62bb9a9400060d07fcc3f4666f22cfd |
| report source | /home/ubuntu/splendor-ppo-m62/scripts/prism_building_report_m62.py / d985875025a1ee6b0f51a97b3623054e2cd29bad693e53b6047b97f484f666ce |
| development/plan | /home/ubuntu/splendor-ppo-m62/evaluation/development/plan.json / 953128f3d23cb60f9dac21a78190a4b804ef8bde57c2d14b6465dfebaa96aac2 |
| development/source-ledger | /home/ubuntu/splendor-ppo-m62/evaluation/development/source-ledger.json / 4ee4b37981654ad40df9e1a2e3c164292bafc3657bd27720fbc20d88a4de8153 |
| development/style-metrics | /home/ubuntu/splendor-ppo-m62/evaluation/development/style-metrics.json / 4e15065aea77ef9ce2a18a1037b9ec638b9568ab46283a4120ee2c9c6586155b |
| development/building-metrics | /home/ubuntu/splendor-ppo-m62/evaluation/development/building-metrics.json / b34ef201f27cbff74a0b0bc5e5da11f60703a47a91075cbc68c0dadd53699603 |
| development/match-details | /home/ubuntu/splendor-ppo-m62/evaluation/development/match-details.json / 104091ede8d2d39807b1c28de17b7157f3af171903dee318b57105b91aca51fb |
| acceptance/plan | /home/ubuntu/splendor-ppo-m62/evaluation/acceptance/plan.json / e13d0d892491b1917ad6587d6f79a82df79a0ae0f7b20934750358dd77f38f85 |
| acceptance/source-ledger | /home/ubuntu/splendor-ppo-m62/evaluation/acceptance/source-ledger.json / 3721675ee84c2deac31f2b93930e4c4733d917e5cafbc0ada420f59706b9d99d |
| acceptance/style-metrics | /home/ubuntu/splendor-ppo-m62/evaluation/acceptance/style-metrics.json / 001431aa60764a5fa112696994898fbacf7f55721b592bf58794473529c31045 |
| acceptance/building-metrics | /home/ubuntu/splendor-ppo-m62/evaluation/acceptance/building-metrics.json / c6275b7a000c857e8ecd96ac87b7875bb49b408a43bcc09516848378866e0381 |
| acceptance/match-details | /home/ubuntu/splendor-ppo-m62/evaluation/acceptance/match-details.json / 2b4faaa830fe8b0775b2067db5b69b82754c1da541395df3454147372ecd20b6 |


### 静态策略面板与限制

固定同局面概率面板：NOT_RUN；可选诊断不增加比赛或新门。折扣适用使用是结构性代理，不能解释为反事实token节省。单训练RNG/有限固定对手/最终c4限制外推；未兑现与短局全部计入。风格可在声明竞技容忍内取舍，不要求所有经济指标改善。

