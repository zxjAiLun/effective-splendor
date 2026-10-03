# M59 Prism Alpha 云端续训：可读结果记录

**产物：**M59未发布最终c4已生成，四轮1,024局/216更新完成，32导出张量与已提交checkpoint一致，68边界推理PASS。云端进程在收尾触发4GiB OOM，原监督器FAILED保留；训练已停止。通过本轮验收后才固定为 Prism Alpha v0.1.2。

**竞技：NOT_RUN。风格：NOT_RUN。**训练采样不等于正式棋力比赛，当前没有新的竞技/风格估计。

完整设计、对手配比、冻结种子、门槛与身份见[M59](../m59-prism-alpha-cloud-ppo.md)。[机器记录](../../benchmarks/m59-prism-alpha-cloud-ppo.result.json)仅用于证据；人类可直接读本文件。

| 匹配父模型→最终候选 | 单位 | 父模型 | 候选 | 变化 / 区间 |
| --- | --- | --- | --- | --- |
| 共同锚点半平得分率 | %，模型本人 | NOT_RUN | NOT_RUN | NOT_RUN |
| 对父模型半平得分率 | %，候选本人 | 不适用 | NOT_RUN | NOT_RUN |
| 大牌印刷VP AUC24 | 无量纲，模型本人 | NOT_RUN | NOT_RUN | NOT_RUN |
| 局均终局VP / 自身Main速度 | VP / VP每Main，模型本人 | NOT_RUN | NOT_RUN | NOT_RUN |

方向标记 ↑/↓ 和粗体强调仅在已有实际数据后使用；高指标不自动等于更好或显著。

| 被测模型 | 固定对手 / 模式 | 开发局 / seed块 | 独立局 / seed块 | W/D/L、胜率、半平率及CI | 双座与双方完整指标 |
| --- | --- | --- | --- | --- | --- |
| M59未发布最终c4候选（T=1） | 便携Heuristic v0.2.9 / greedy | NOT_RUN（计划64 / 32） | NOT_RUN（计划512 / 256） | NOT_RUN | NOT_RUN |
| M59未发布最终c4候选（T=1） | 初代Prism v0.1.0 / greedy | NOT_RUN（计划64 / 32） | NOT_RUN（计划512 / 256） | NOT_RUN | NOT_RUN |
| M59未发布最终c4候选（T=1） | 通用Prism v0.1.1 / T=1 | NOT_RUN（计划64 / 32） | NOT_RUN（计划512 / 256） | NOT_RUN | NOT_RUN |
| M59未发布最终c4候选（T=1） | 父模型Prism Alpha v0.1.1 / T=1 | 不设开发直接组 | NOT_RUN（计划1024 / 512） | NOT_RUN | NOT_RUN |
| 父模型Prism Alpha v0.1.1（T=1） | 同三个共同对手 / 上述模式 | NOT_RUN（计划192 / 32） | NOT_RUN（计划1536 / 256） | NOT_RUN | NOT_RUN |

此表为未测计划，不填零。取得实际回放后，按对手和模式分别补完整双方VP、VP/决策与Main、全局ply速度、时长分布、0..5VP购卡、五色折扣、贵族与覆盖、预留获取/兑现/未买回/比例，以及七类动作次数/比例；按模型身份聚合，再合并物理双座。每组附双方先后手战绩、配对区间与真实clock scope/load。逐推理/决策耗时 **NOT_MEASURED**。

| gate | 冻结保留底线 | 估计 / 不确定性 | 当前结论 |
| --- | --- | --- | --- |
| strength_pool | 校正配对Δ下界≥−0.05 | NOT_RUN | NOT_RUN |
| direct_parent | 半平率校正下界≥0.45 | NOT_RUN | NOT_RUN |
| bigcard_auc24 | 大牌AUC24校正Δ下界≥−0.015 | NOT_RUN | NOT_RUN |

底线通过和增强分别判断；所有描述指标无需同时改善。具体失败意义及三门同时统计约束见里程碑。

### 训练启动快照 — 2026-10-03T06:32:54.794214+08:00

cloud1正在执行第一轮：**68/1,024局完成，0retry**，自有supervisor alive=true。这只是启动进度；最终c4尚未生成，开发/独立竞技/风格验收仍为NOT_RUN。核验、命令与精确证据见[M59启动记录](../m59-prism-alpha-cloud-ppo.md)。阶段完成后据真实回放补全对战表。

### 最新产物核对 — 2026-10-03T13:16:43.574077+08:00

训练与保存成功，进程收尾异常，两者分开记录。最终权重SHA faada9ba7f862c14f5a8ca19b5788f044aa08f550b03e1e360a04cb1f2318618；监督实际tree墙钟约47分11秒。详细原始失败与校验见[M59收尾记录](../m59-prism-alpha-cloud-ppo.md)。[四轮完整训练对战表](prism-alpha-cloud-m59-training-matches.md)含16组双方/双座位、所有经济与动作数据；被测c0..c3属于训练诊断，最终c4的正式对战仍NOT_RUN，上方计划表不改为通过。
