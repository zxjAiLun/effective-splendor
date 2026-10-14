# M81：流程明显提速，补训练对手尚未解决旧锚点问题

两组训练和全部计划评测执行已结束。固定候选 B 对父代的半平得分为 **54.45%**，但增加启发式和旧 Balance 的训练占比，没有显示出预期的针对性收益。**保留 M75 作为主线父候选，M81 B 未晋级。**

## 先看三件事

- **产物已完成：** A、B 各训练 5,120 局，均产出第 20 周期检查点；14,336 次评测执行产生 14,330 个终局和 6 个截断。
- **棋力目标未达：** B 对启发式、旧 Balance 相对父代分别下降 1.66、2.64 个百分点；受截断影响的正式门还缺完整配对数据。
- **风格仍待定：** 已有回放画像可作描述；当前指标与匹配参照不足以确认 Alpha、Beta 或 Balance 风格。

## 这一轮究竟改了什么

两组都从 **M75 c20** 权重出发，重新初始化优化器。A 保留原四对手训练配比；B 把 25% 的训练份额换成启发式与旧 Balance。固定最终第 20 周期检查点作为比较对象，B 是预先指定候选。M80 是工程整理轮，不是父模型。

每组 20 个周期，每周期 256 局，共 5,120 局。PPO 每批数据训练 2 遍，小批为 256 条本人决策；A 共 1,110 次优化器更新，B 共 1,096 次。只有一组配对训练种子，结论针对本轮候选。

## 对父代：两组都占优，但正式增强结论仍缺完整终局

| 模型 | 胜 / 平 / 负 | 终局 / 计划 | 半平得分 |
| --- | --- | ---: | ---: |
| M81 A 原配比 | 567 / 10 / 444 | 1021 / 1024 | 56.02% |
| M81 B 补覆盖 | 553 / 8 / 462 | 1023 / 1024 | 54.45% |

这里的百分比按已有终局计算。A 对父代有 3 个截断，B 有 1 个，不能把上述点估计当作完整独立增强门通过。

## 对八个对手：收益集中在 Alpha，目标旧锚点没有修复

双方均 greedy。半平得分 =（胜 + 0.5 × 平）÷ 终局数；差值单位为百分点。较大的数值加粗，显示值相同时不标胜者。

| 对手 | M75 父代 | A 原配比 | B 补覆盖 | B − 父代 |
| --- | ---: | ---: | ---: | ---: |
| 启发式 v0.3.1 | **91.11%** | 88.87% | 89.45% | -1.66 |
| Prism v0.1.1 | 78.32% | 80.08% | **81.54%** | +3.22 |
| Balance v0.1.0 | **73.24%** | 71.14%＊ | 70.61% | -2.64 |
| Alpha v0.1.4 | 70.70% | 69.92% | **71.09%** | +0.39 |
| Beta v0.1.0 | 71.00% | **71.88%** | 69.73% | -1.27 |
| Alpha v0.1.5 | 68.59%＊ | 71.97% | **77.83%** | +9.24 |
| Alpha v0.2.0 | 61.23% | 61.23% | **65.04%** | +3.81 |
| Balance v0.2.1 | 65.53% | 64.65% | **65.92%** | +0.39 |

每格计划 512 局；＊为 511 个终局。全部胜平负和先后手在本页末尾的完整 Markdown 中保留。

**对照回答的问题：** B 比 A 对启发式高 0.59 个百分点，对旧 Balance 低 0.53 个百分点；对完整种子块配对后，两类目标对手的平均变化约为零。补覆盖的训练方法没有得到本轮结果支持。

**退步的统计含义：** B 相对父代，对启发式的配对 95% 差值区间为 −4.98～+1.56 个百分点，对旧 Balance 为 −7.71～+2.54。点估计下降且未通过冻结保留门，但区间跨零，尚不能断言真实棋力退化。

## 实际耗时：5,120 局从 11小时07分降到 3小时14分

| 时间花在哪里 | A：优化前完整实跑 | B：中途优化完整实跑 |
| --- | ---: | ---: |
| 游戏子进程活动，含等待出招 | 0时43分42秒 | 0时33分35秒 |
| PPO 更新阶段，含提交 | 0时39分46秒 | 0时40分05秒 |
| 外层监督额外等待 | 5时15分50秒 | 0时29分13秒 |
| 逐局启动、核验、入库、账本等 | 3时51分52秒 | 0时58分28秒 |
| 封批、导出、切换及其他 | 0时35分47秒 | 0时32分54秒 |
| 总墙钟 | 11时06分58秒 | 3时14分15秒 |

**完整实跑提速 3.43 倍，耗时减少 70.88%。** 主要节省来自外层等待和逐局管理开销；PPO 更新仍约 40 分钟。B 包含旧实现、两次优化和切换等待，且两组对手不同，因此这不是纯单变量的性能实验。

最终优化版本连续 1,792 局实跑 **0时50分40秒**。按该速率估算 5,120 局为 **2时24分45秒**，这是外推值。

更新使用 CPU。A、B 平均占用分别为 1.097 核、1.141 核，约为 4 核额度的 27.4%、28.5%；尚未实现充分并行。DSW 上 A/B 的 10,240 次评测执行耗时 45分10秒，另有 DSW2 提前完成的 4,096 次基线评测。

## 6 个截断，以及为什么没有晋级

所有计划执行都结束了，6 个对局达到 512-ply 上限而未终局：父代基线 1 个、A 4 个、B 1 个。它们不是尚在排队的比赛，也没有被填成平局。受影响的配对统计与门保持不完整；此外，已完整的旧锚点保留门也没有通过。

原报告在统计和画像保存之后，因读取计划哈希的字段错误而中断。本版直接读取已保存结果恢复展示；没有重新训练、补赛或重算冻结判门。

## 下一步判断

保留 M75 为主线父候选，M81 B 作为比较候选保存。本轮支持保留工程提速改动，不支持将“补入两个旧对手”认定为有效训练改进。下一轮优先利用现有检查点与回放缩小问题，再明确唯一训练变量；不因本轮负结果自动启动新训练。

当前已保存的回放画像覆盖 14,330 个终局，包含首次大牌时点及覆盖率、早期低分购牌与折扣兑现。固定 Main 12/24 得分、贵族覆盖和合法购牌机会不在本版原始画像中，因此不作主动偏好或因果机制结论。

## 完整表与证据

- [完整 Markdown：逐对手胜平负、双方得分、座位、画像与冻结统计](m81-results-r1.md)
- [开跑前实验设计](m81-experiment-explained.html)
- [完整轮次记录](../m81-anchor-coverage-pilot.md)

本页交付与远端私有归档分别记录；本页不声称归档或 ALL 同步已经完成。

## 完整双方胜平负

| 模型 | 对手 | 局数 | 本方胜/平/负 | 对手胜/平/负 | 本方得分 | 对手得分 |
| --- | --- | ---: | --- | --- | ---: | ---: |
| M81 A 原配比 | Alpha v0.1.4 | 512 | 354/8/150 | 150/8/354 | 69.92% | 30.08% |
| M81 A 原配比 | Balance v0.1.0 | 511 | 363/1/147 | 147/1/363 | 71.14% | 28.86% |
| M81 A 原配比 | Beta v0.1.0 | 512 | 366/4/142 | 142/4/366 | 71.88% | 28.12% |
| M81 A 原配比 | Prism v0.1.1 | 512 | 410/0/102 | 102/0/410 | 80.08% | 19.92% |
| M81 A 原配比 | 启发式 v0.3.1 | 512 | 455/0/57 | 57/0/455 | 88.87% | 11.13% |
| M81 A 原配比 | Alpha v0.2.0 | 512 | 312/3/197 | 197/3/312 | 61.23% | 38.77% |
| M81 A 原配比 | Balance v0.2.1 | 512 | 330/2/180 | 180/2/330 | 64.65% | 35.35% |
| M81 A 原配比 | M75 c20 父代 | 1021 | 567/10/444 | 444/10/567 | 56.02% | 43.98% |
| M81 A 原配比 | Alpha v0.1.5 | 512 | 367/3/142 | 142/3/367 | 71.97% | 28.03% |
| M81 B 补覆盖 | Alpha v0.1.4 | 512 | 361/6/145 | 145/6/361 | 71.09% | 28.91% |
| M81 B 补覆盖 | Balance v0.1.0 | 512 | 359/5/148 | 148/5/359 | 70.61% | 29.39% |
| M81 B 补覆盖 | Beta v0.1.0 | 512 | 355/4/153 | 153/4/355 | 69.73% | 30.27% |
| M81 B 补覆盖 | Prism v0.1.1 | 512 | 416/3/93 | 93/3/416 | 81.54% | 18.46% |
| M81 B 补覆盖 | 启发式 v0.3.1 | 512 | 458/0/54 | 54/0/458 | 89.45% | 10.55% |
| M81 B 补覆盖 | Alpha v0.2.0 | 512 | 331/4/177 | 177/4/331 | 65.04% | 34.96% |
| M81 B 补覆盖 | Balance v0.2.1 | 512 | 336/3/173 | 173/3/336 | 65.92% | 34.08% |
| M81 B 补覆盖 | M75 c20 父代 | 1023 | 553/8/462 | 462/8/553 | 54.45% | 45.55% |
| M81 B 补覆盖 | Alpha v0.1.5 | 512 | 396/5/111 | 111/5/396 | 77.83% | 22.17% |
| M75 c20 父代 | Alpha v0.1.4 | 512 | 360/4/148 | 148/4/360 | 70.70% | 29.30% |
| M75 c20 父代 | Balance v0.1.0 | 512 | 374/2/136 | 136/2/374 | 73.24% | 26.76% |
| M75 c20 父代 | Beta v0.1.0 | 512 | 361/5/146 | 146/5/361 | 71.00% | 29.00% |
| M75 c20 父代 | Prism v0.1.1 | 512 | 398/6/108 | 108/6/398 | 78.32% | 21.68% |
| M75 c20 父代 | 启发式 v0.3.1 | 512 | 466/1/45 | 45/1/466 | 91.11% | 8.89% |
| M75 c20 父代 | Alpha v0.2.0 | 512 | 310/7/195 | 195/7/310 | 61.23% | 38.77% |
| M75 c20 父代 | Balance v0.2.1 | 512 | 333/5/174 | 174/5/333 | 65.53% | 34.47% |
| M75 c20 父代 | Alpha v0.1.5 | 511 | 350/1/160 | 160/1/350 | 68.59% | 31.41% |

# M81 Anchor Coverage Evaluation

**Evaluation state:** INCOMPLETE  
**Terminal games:** 14330/14336; **missing:** 6; **ply-cap truncations:** 6

**Evaluation CPU:** 5551.186541999999 / 150000.0 seconds; unresolved reservations: 0.

## Findings

- Coverage method screen: **INCOMPLETE**.
- B mainline recommendation gates: **INCOMPLETE**.
- One paired training seed only; game-level intervals do not estimate recipe robustness across training seeds.
- A PASS is a next-mainline recommendation only. It does not authorize release, default replacement, or deployment.

## Frozen statistical endpoints

| Endpoint | Status | Estimate | Ordinary 95% CI | Family lower bound | Gates |
| --- | --- | ---: | --- | ---: | --- |
| B-A-targets | INCOMPLETE | NOT_MEASURED | NOT_MEASURED (incomplete) | NOT_MEASURED | target_gain=INCOMPLETE |
| B-A-eight-pool | INCOMPLETE | NOT_MEASURED | NOT_MEASURED (incomplete) | NOT_MEASURED | method_retention=INCOMPLETE |
| B-A-latest-alpha | COMPLETE | 3.809% | [-1.855%, 9.570%] | -2.344% | method_retention=PASS |
| B-A-latest-balance | COMPLETE | 1.270% | [-4.102%, 6.641%] | -4.590% | method_retention=FAIL |
| B-base-common | INCOMPLETE | NOT_MEASURED | NOT_MEASURED (incomplete) | NOT_MEASURED | enhancement=INCOMPLETE, retention=INCOMPLETE |
| B-parent | INCOMPLETE | NOT_MEASURED | NOT_MEASURED (incomplete) | NOT_MEASURED | enhancement=INCOMPLETE, retention=INCOMPLETE |
| B-base-heuristic | COMPLETE | -1.660% | [-4.980%, 1.562%] | -5.273% | anchor_retention=FAIL |
| B-base-balance | COMPLETE | -2.637% | [-7.715%, 2.539%] | -8.105% | anchor_retention=FAIL |
| B-base-released-alpha | INCOMPLETE | NOT_MEASURED | NOT_MEASURED (incomplete) | NOT_MEASURED | anchor_retention=INCOMPLETE |
| B-base-latest-alpha | COMPLETE | 3.809% | [-1.855%, 9.473%] | -1.855% | coverage_retention=PASS |
| B-base-latest-balance | COMPLETE | 0.391% | [-5.566%, 6.250%] | -5.566% | coverage_retention=FAIL |

## Actor versus opponent results

| Actor | Opponent | Games / planned | W / D / L | Half score | Seat 0 | Seat 1 | State |
| --- | --- | ---: | --- | ---: | --- | --- | --- |
| A | alpha | 512/512 | 354/8/150 | 69.922% | 174/5/77 | 180/3/73 | COMPLETE |
| A | balance | 511/512 | 363/1/147 | 71.135% | 182/0/73 | 181/1/74 | INCOMPLETE |
| A | beta | 512/512 | 366/4/142 | 71.875% | 185/0/71 | 181/4/71 | COMPLETE |
| A | general | 512/512 | 410/0/102 | 80.078% | 204/0/52 | 206/0/50 | COMPLETE |
| A | heuristic | 512/512 | 455/0/57 | 88.867% | 227/0/29 | 228/0/28 | COMPLETE |
| A | latest-alpha | 512/512 | 312/3/197 | 61.230% | 143/3/110 | 169/0/87 | COMPLETE |
| A | latest-balance | 512/512 | 330/2/180 | 64.648% | 172/1/83 | 158/1/97 | COMPLETE |
| A | parent | 1021/1024 | 567/10/444 | 56.024% | 296/5/209 | 271/5/235 | INCOMPLETE |
| A | released-alpha | 512/512 | 367/3/142 | 71.973% | 184/0/72 | 183/3/70 | COMPLETE |
| B | alpha | 512/512 | 361/6/145 | 71.094% | 187/3/66 | 174/3/79 | COMPLETE |
| B | balance | 512/512 | 359/5/148 | 70.605% | 184/2/70 | 175/3/78 | COMPLETE |
| B | beta | 512/512 | 355/4/153 | 69.727% | 180/2/74 | 175/2/79 | COMPLETE |
| B | general | 512/512 | 416/3/93 | 81.543% | 214/2/40 | 202/1/53 | COMPLETE |
| B | heuristic | 512/512 | 458/0/54 | 89.453% | 229/0/27 | 229/0/27 | COMPLETE |
| B | latest-alpha | 512/512 | 331/4/177 | 65.039% | 170/3/83 | 161/1/94 | COMPLETE |
| B | latest-balance | 512/512 | 336/3/173 | 65.918% | 165/2/89 | 171/1/84 | COMPLETE |
| B | parent | 1023/1024 | 553/8/462 | 54.448% | 289/5/218 | 264/3/244 | INCOMPLETE |
| B | released-alpha | 512/512 | 396/5/111 | 77.832% | 201/4/51 | 195/1/60 | COMPLETE |
| base | alpha | 512/512 | 360/4/148 | 70.703% | 192/1/63 | 168/3/85 | COMPLETE |
| base | balance | 512/512 | 374/2/136 | 73.242% | 187/2/67 | 187/0/69 | COMPLETE |
| base | beta | 512/512 | 361/5/146 | 70.996% | 188/2/66 | 173/3/80 | COMPLETE |
| base | general | 512/512 | 398/6/108 | 78.320% | 199/4/53 | 199/2/55 | COMPLETE |
| base | heuristic | 512/512 | 466/1/45 | 91.113% | 236/0/20 | 230/1/25 | COMPLETE |
| base | latest-alpha | 512/512 | 310/7/195 | 61.230% | 163/2/91 | 147/5/104 | COMPLETE |
| base | latest-balance | 512/512 | 333/5/174 | 65.527% | 165/4/87 | 168/1/87 | COMPLETE |
| base | released-alpha | 511/512 | 350/1/160 | 68.591% | 175/0/81 | 175/1/79 | INCOMPLETE |

## Behavior profile

Rust replay profile state: **PASS_RUST_REPLAY_VERIFIED**.
Purchase opportunities, first divergence, token-choice composition, noble coverage, and fixed Main 12/24 scores are NOT_MEASURED by this profile pipeline.
The measured first-large-card timing includes its purchase-game coverage; early low-VP buys and discount redemption include observed denominators.

| Candidate | Opponent | Seat | Games | First 4–5 VP purchase Main | Purchase coverage | 0–1 VP buys/game | Discount redemption rate |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A | alpha | 0 | 256 | 20.103286384976524 | 83.203% | 3.4921875 | 98.770% |
| A | alpha | 1 | 256 | 20.87214611872146 | 85.547% | 3.28125 | 99.524% |
| A | balance | 0 | 255 | 20.39814814814815 | 84.706% | 3.4980392156862745 | 99.327% |
| A | balance | 1 | 256 | 21.004901960784313 | 79.688% | 3.234375 | 99.517% |
| A | beta | 0 | 256 | 20.316037735849058 | 82.812% | 3.4296875 | 99.544% |
| A | beta | 1 | 256 | 20.206572769953052 | 83.203% | 3.29296875 | 99.170% |
| A | general | 0 | 256 | 19.809734513274336 | 88.281% | 3.42578125 | 99.088% |
| A | general | 1 | 256 | 19.90308370044053 | 88.672% | 3.3359375 | 99.063% |
| A | heuristic | 0 | 256 | 19.53813559322034 | 92.188% | 3.49609375 | 99.330% |
| A | heuristic | 1 | 256 | 19.935064935064936 | 90.234% | 3.32421875 | 99.765% |
| A | latest-alpha | 0 | 256 | 21.440594059405942 | 78.906% | 3.58203125 | 99.673% |
| A | latest-alpha | 1 | 256 | 21.62735849056604 | 82.812% | 3.296875 | 99.408% |
| A | latest-balance | 0 | 256 | 20.62686567164179 | 78.516% | 3.57421875 | 99.454% |
| A | latest-balance | 1 | 256 | 20.78640776699029 | 80.469% | 3.32421875 | 99.060% |
| A | parent | 0 | 510 | 20.90561224489796 | 76.863% | 3.727450980392157 | 99.527% |
| A | parent | 1 | 511 | 21.391959798994975 | 77.886% | 3.440313111545988 | 99.261% |
| A | released-alpha | 0 | 256 | 19.82125603864734 | 80.859% | 3.56640625 | 99.452% |
| A | released-alpha | 1 | 256 | 20.545023696682463 | 82.422% | 3.42578125 | 99.544% |
| B | alpha | 0 | 256 | 19.724444444444444 | 87.891% | 3.296875 | 99.645% |
| B | alpha | 1 | 256 | 19.668141592920353 | 88.281% | 3.08984375 | 99.747% |
| B | balance | 0 | 256 | 19.696428571428573 | 87.500% | 3.41796875 | 99.429% |
| B | balance | 1 | 256 | 20.314553990610328 | 83.203% | 3.171875 | 99.631% |
| B | beta | 0 | 256 | 20.12727272727273 | 85.938% | 3.42578125 | 99.544% |
| B | beta | 1 | 256 | 19.457943925233646 | 83.594% | 3.1875 | 99.510% |
| B | general | 0 | 256 | 19.299107142857142 | 87.500% | 3.390625 | 99.309% |
| B | general | 1 | 256 | 19.55982905982906 | 91.406% | 3.15625 | 99.010% |
| B | heuristic | 0 | 256 | 18.95633187772926 | 89.453% | 3.34765625 | 99.883% |
| B | heuristic | 1 | 256 | 19.20746887966805 | 94.141% | 3.30078125 | 99.527% |
| B | latest-alpha | 0 | 256 | 19.513513513513512 | 86.719% | 3.3984375 | 99.425% |
| B | latest-alpha | 1 | 256 | 20.06787330316742 | 86.328% | 3.109375 | 99.497% |
| B | latest-balance | 0 | 256 | 19.514285714285716 | 82.031% | 3.484375 | 99.776% |
| B | latest-balance | 1 | 256 | 19.89252336448598 | 83.594% | 3.19140625 | 99.510% |
| B | parent | 0 | 512 | 20.32587064676617 | 78.516% | 3.62890625 | 99.300% |
| B | parent | 1 | 511 | 20.745098039215687 | 79.843% | 3.4187866927592956 | 99.313% |
| B | released-alpha | 0 | 256 | 19.142857142857142 | 84.766% | 3.55078125 | 99.450% |
| B | released-alpha | 1 | 256 | 20.135964912280702 | 89.062% | 3.3828125 | 99.423% |
| base | alpha | 0 | 256 | 20.013761467889907 | 85.156% | 3.47265625 | 99.325% |
| base | alpha | 1 | 256 | 19.77511961722488 | 81.641% | 3.18359375 | 99.264% |
| base | balance | 0 | 256 | 19.941747572815533 | 80.469% | 3.51171875 | 99.778% |
| base | balance | 1 | 256 | 20.076923076923077 | 81.250% | 3.2890625 | 99.762% |
| base | beta | 0 | 256 | 20.1588785046729 | 83.594% | 3.578125 | 99.563% |
| base | beta | 1 | 256 | 19.995098039215687 | 79.688% | 3.265625 | 99.163% |
| base | general | 0 | 256 | 19.537383177570092 | 83.594% | 3.41796875 | 99.086% |
| base | general | 1 | 256 | 19.472972972972972 | 86.719% | 3.29296875 | 99.288% |
| base | heuristic | 0 | 256 | 19.536480686695278 | 91.016% | 3.46484375 | 99.324% |
| base | heuristic | 1 | 256 | 19.183760683760685 | 91.406% | 3.34765625 | 99.417% |
| base | latest-alpha | 0 | 256 | 20.13170731707317 | 80.078% | 3.6328125 | 99.462% |
| base | latest-alpha | 1 | 256 | 20.776699029126213 | 80.469% | 3.31640625 | 98.940% |
| base | latest-balance | 0 | 256 | 20.140845070422536 | 83.203% | 3.5390625 | 99.007% |
| base | latest-balance | 1 | 256 | 19.77 | 78.125% | 3.296875 | 99.408% |
| base | released-alpha | 0 | 256 | 19.75115207373272 | 84.766% | 3.61328125 | 99.459% |
| base | released-alpha | 1 | 255 | 19.86111111111111 | 84.706% | 3.5215686274509803 | 98.998% |

### VP per own Main

| Candidate | Opponent | Games | Points | Own Main actions | VP/Main |
| --- | --- | ---: | ---: | ---: | ---: |
| A | alpha | 512 | 7682 | 13724 | 0.5597493442145147 |
| A | balance | 511 | 7650 | 13704 | 0.558231173380035 |
| A | beta | 512 | 7660 | 13794 | 0.5553139045962012 |
| A | general | 512 | 7844 | 13522 | 0.5800917024108859 |
| A | heuristic | 512 | 7975 | 13364 | 0.5967524693205627 |
| A | latest-alpha | 512 | 7432 | 13896 | 0.5348301669545192 |
| A | latest-balance | 512 | 7491 | 13865 | 0.54028128380815 |
| A | parent | 1021 | 14582 | 27794 | 0.5246456069655321 |
| A | released-alpha | 512 | 7660 | 13756 | 0.5568479209072404 |
| B | alpha | 512 | 7638 | 13645 | 0.5597654818614878 |
| B | balance | 512 | 7644 | 13700 | 0.5579562043795621 |
| B | beta | 512 | 7627 | 13769 | 0.5539254847846612 |
| B | general | 512 | 7773 | 13520 | 0.5749260355029586 |
| B | heuristic | 512 | 7984 | 13347 | 0.5981868584700681 |
| B | latest-alpha | 512 | 7546 | 13811 | 0.5463760770400405 |
| B | latest-balance | 512 | 7620 | 13791 | 0.5525342614748749 |
| B | parent | 1023 | 14514 | 27797 | 0.522142677267331 |
| B | released-alpha | 512 | 7751 | 13719 | 0.5649828704716087 |
| base | alpha | 512 | 7676 | 13683 | 0.5609880874077322 |
| base | balance | 512 | 7687 | 13684 | 0.5617509500146156 |
| base | beta | 512 | 7670 | 13769 | 0.5570484421526618 |
| base | general | 512 | 7765 | 13550 | 0.5730627306273063 |
| base | heuristic | 512 | 8051 | 13296 | 0.6055204572803851 |
| base | latest-alpha | 512 | 7403 | 13865 | 0.5339343671114316 |
| base | latest-balance | 512 | 7574 | 13833 | 0.5475312658136341 |
| base | released-alpha | 511 | 7604 | 13650 | 0.557069597069597 |

## Shard ledger and missing identities

| Shard | State | Complete | Truncated | Missing | Reason |
| --- | --- | ---: | ---: | ---: | --- |
| base-heuristic-81010000 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-heuristic-81010032 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-heuristic-81010064 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-heuristic-81010096 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-heuristic-81010128 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-heuristic-81010160 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-heuristic-81010192 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-heuristic-81010224 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-general-81011000 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-general-81011032 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-general-81011064 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-general-81011096 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-general-81011128 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-general-81011160 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-general-81011192 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-general-81011224 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-balance-81012000 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-balance-81012032 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-balance-81012064 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-balance-81012096 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-balance-81012128 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-balance-81012160 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-balance-81012192 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-balance-81012224 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-alpha-81013000 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-alpha-81013032 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-alpha-81013064 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-alpha-81013096 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-alpha-81013128 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-alpha-81013160 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-alpha-81013192 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-alpha-81013224 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-beta-81014000 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-beta-81014032 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-beta-81014064 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-beta-81014096 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-beta-81014128 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-beta-81014160 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-beta-81014192 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-beta-81014224 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-released-alpha-81015000 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-released-alpha-81015032 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-released-alpha-81015064 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-released-alpha-81015096 | FINISHED | 63 | 1 | 1 | FINISHED |
| base-released-alpha-81015128 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-released-alpha-81015160 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-released-alpha-81015192 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-released-alpha-81015224 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-latest-alpha-81016000 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-latest-alpha-81016032 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-latest-alpha-81016064 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-latest-alpha-81016096 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-latest-alpha-81016128 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-latest-alpha-81016160 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-latest-alpha-81016192 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-latest-alpha-81016224 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-latest-balance-81017000 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-latest-balance-81017032 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-latest-balance-81017064 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-latest-balance-81017096 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-latest-balance-81017128 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-latest-balance-81017160 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-latest-balance-81017192 | FINISHED | 64 | 0 | 0 | FINISHED |
| base-latest-balance-81017224 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-heuristic-81010000 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-heuristic-81010032 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-heuristic-81010064 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-heuristic-81010096 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-heuristic-81010128 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-heuristic-81010160 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-heuristic-81010192 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-heuristic-81010224 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-general-81011000 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-general-81011032 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-general-81011064 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-general-81011096 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-general-81011128 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-general-81011160 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-general-81011192 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-general-81011224 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-balance-81012000 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-balance-81012032 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-balance-81012064 | FINISHED | 63 | 1 | 1 | FINISHED |
| A-balance-81012096 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-balance-81012128 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-balance-81012160 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-balance-81012192 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-balance-81012224 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-alpha-81013000 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-alpha-81013032 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-alpha-81013064 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-alpha-81013096 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-alpha-81013128 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-alpha-81013160 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-alpha-81013192 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-alpha-81013224 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-beta-81014000 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-beta-81014032 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-beta-81014064 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-beta-81014096 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-beta-81014128 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-beta-81014160 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-beta-81014192 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-beta-81014224 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-released-alpha-81015000 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-released-alpha-81015032 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-released-alpha-81015064 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-released-alpha-81015096 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-released-alpha-81015128 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-released-alpha-81015160 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-released-alpha-81015192 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-released-alpha-81015224 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-latest-alpha-81016000 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-latest-alpha-81016032 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-latest-alpha-81016064 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-latest-alpha-81016096 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-latest-alpha-81016128 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-latest-alpha-81016160 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-latest-alpha-81016192 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-latest-alpha-81016224 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-latest-balance-81017000 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-latest-balance-81017032 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-latest-balance-81017064 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-latest-balance-81017096 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-latest-balance-81017128 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-latest-balance-81017160 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-latest-balance-81017192 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-latest-balance-81017224 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-heuristic-81010000 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-heuristic-81010032 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-heuristic-81010064 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-heuristic-81010096 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-heuristic-81010128 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-heuristic-81010160 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-heuristic-81010192 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-heuristic-81010224 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-general-81011000 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-general-81011032 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-general-81011064 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-general-81011096 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-general-81011128 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-general-81011160 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-general-81011192 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-general-81011224 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-balance-81012000 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-balance-81012032 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-balance-81012064 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-balance-81012096 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-balance-81012128 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-balance-81012160 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-balance-81012192 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-balance-81012224 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-alpha-81013000 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-alpha-81013032 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-alpha-81013064 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-alpha-81013096 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-alpha-81013128 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-alpha-81013160 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-alpha-81013192 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-alpha-81013224 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-beta-81014000 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-beta-81014032 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-beta-81014064 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-beta-81014096 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-beta-81014128 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-beta-81014160 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-beta-81014192 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-beta-81014224 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-released-alpha-81015000 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-released-alpha-81015032 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-released-alpha-81015064 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-released-alpha-81015096 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-released-alpha-81015128 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-released-alpha-81015160 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-released-alpha-81015192 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-released-alpha-81015224 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-latest-alpha-81016000 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-latest-alpha-81016032 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-latest-alpha-81016064 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-latest-alpha-81016096 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-latest-alpha-81016128 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-latest-alpha-81016160 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-latest-alpha-81016192 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-latest-alpha-81016224 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-latest-balance-81017000 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-latest-balance-81017032 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-latest-balance-81017064 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-latest-balance-81017096 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-latest-balance-81017128 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-latest-balance-81017160 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-latest-balance-81017192 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-latest-balance-81017224 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-parent-81030000 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-parent-81030032 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-parent-81030064 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-parent-81030096 | FINISHED | 63 | 1 | 1 | FINISHED |
| A-parent-81030128 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-parent-81030160 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-parent-81030192 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-parent-81030224 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-parent-81030256 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-parent-81030288 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-parent-81030320 | FINISHED | 63 | 1 | 1 | FINISHED |
| A-parent-81030352 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-parent-81030384 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-parent-81030416 | FINISHED | 63 | 1 | 1 | FINISHED |
| A-parent-81030448 | FINISHED | 64 | 0 | 0 | FINISHED |
| A-parent-81030480 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-parent-81030000 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-parent-81030032 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-parent-81030064 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-parent-81030096 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-parent-81030128 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-parent-81030160 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-parent-81030192 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-parent-81030224 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-parent-81030256 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-parent-81030288 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-parent-81030320 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-parent-81030352 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-parent-81030384 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-parent-81030416 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-parent-81030448 | FINISHED | 64 | 0 | 0 | FINISHED |
| B-parent-81030480 | FINISHED | 63 | 1 | 1 | FINISHED |

Missing identities keep their original seed and seat. They receive no fabricated outcome.

## Source and result identity

Plan SHA256: `064a2e0be1b7b9958b47405268fdde905c2b7d7518820ec2fe914574a98b4858`  
Execution receipt SHA256: `04090877b102afcd52292af9dd81fcc02c84a180fc39b8abe75b845eeec46721`  
Completed row count: 14330  
Profile receipt: `PASS`

### Missing rows

| Actor | Opponent | Seed | Seat | Shard | Reason |
| --- | --- | ---: | ---: | --- | --- |
| base | released-alpha | 81015112 | 1 | base-released-alpha-81015096 | PLY_CAP_TRUNCATED |
| A | balance | 81012084 | 0 | A-balance-81012064 | PLY_CAP_TRUNCATED |
| A | parent | 81030118 | 1 | A-parent-81030096 | PLY_CAP_TRUNCATED |
| A | parent | 81030334 | 0 | A-parent-81030320 | PLY_CAP_TRUNCATED |
| A | parent | 81030426 | 0 | A-parent-81030416 | PLY_CAP_TRUNCATED |
| B | parent | 81030492 | 1 | B-parent-81030480 | PLY_CAP_TRUNCATED |
