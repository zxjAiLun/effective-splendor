# M61 Prism Alpha 与 Balance 同父 PPO 对照

状态：VERIFIED / COMPLETED；两臂均通过五项冻结底线门槛（PASS_RETENTION_FLOORS）；A/B 路线对决判定为 INCONCLUSIVE；不触发版本发布或登记
基线：`9899749188f35c838c85c5b3530049bd5dcbd105`；开发分支 `m61-alpha-balance-ab`
负责人/日期：Zixuan Tang / 2026-10-03
授权：用户确认两臂共同从 Prism Alpha v0.1.3 出发后，原话「okay let go」。两臂均已完成云端有限训练、独立只读审计、8,256局独立双盲评测与完整双方对战报告。

## Problem and evidence

Prism Alpha v0.1.3 的 M60 独立评测通过三项冻结保留门。共同锚点半平得分率相对 Prism Alpha v0.1.2 增加 4.4596 个百分点，校正下界 +1.2370 个百分点；大牌印刷 VP AUC24 增加 0.004881，校正下界 +0.001449。直接父模型得分率 53.1738%，校正下界 49.8047%，未确认直接优势。

[M60 完整双方对战表](prism/prism-alpha-cloud-m60-evaluation.md)和[版本身份](../benchmarks/m60-prism-alpha-v0.1.3.model.json)为既有结果记录。本轮不重复该结果、不修改原门或种子。Heuristic 锚点以[源码/二进制身份更正](prism/heuristic-anchor-v031-identity.md)为准：策略为 Heuristic v0.3.1，协议 Hello 常量仍为 0.2.9。

Alpha 的训练辅助目标仍是前24次自身 Main 的公开总 VP 曲线，并非直接按购买4/5 VP牌奖励。继续相同 PPO 与关闭辅助目标哪个更有效，目前没有同起点对照证据。新 Balance 仅指 outcome-only 训练候选；继承 Alpha 策略，不宣称天然均衡或已通过均衡风格验收。

## Initial design

从固定 Prism Alpha v0.1.3 推理权重建立两个新 run。父权重 SHA-256：`7f6cdbc2acdff129b0ef6a3417e79d4b8f27bf59f40be53ae2892bf00b5e1544`。

| 训练候选（均未发布，NOT_RUN） | 起点 | 唯一实验处理 | 固定预算 |
| --- | --- | --- | --- |
| M61 Alpha 未发布最终 c4 候选 | Prism Alpha v0.1.3 | style_beta=0.3；style_value_weight=0.5 | 4轮×256局=1,024局 |
| M61 Balance 未发布最终 c4 候选 | Prism Alpha v0.1.3 | style_beta=0；style_value_weight=0 | 4轮×256局=1,024局 |

两臂其余 PPO 参数、训练初始 policy/value、对手配比、环境种子、座位与运行 RNG 相同；新 AdamW/RNG，从推理权重新建，不继承旧优化器。run/job 身份不同。不同策略产生不同轨迹，共用 RNG 不代表轨迹相同，也不代替多训练种子重复。

每臂训练：通用 Prism v0.1.1 greedy 512局、固定父模型 Prism Alpha v0.1.3 greedy 256局、初代 Prism v0.1.0 greedy 128局、Heuristic v0.3.1 greedy 128局。共享冻结旧原生引擎与度量工具。每臂串行运行，资源不叠加。

## Scope and non-goals

- 只训练两个有限候选，均只取最终 c4；开发局只描述，不选检查点、不调参数。
- 不建立基建/干扰 Beta，不改在线推理结构。
- 不自动替换默认、共享池、Studio 或公网模型；不 push。
- 历史失败、冻结源码和产物不改写；无关工作区变化不触碰。
- 每局零基础设施重试；失败不换种子，不延长独立样本。
- 关闭辅助目标不能证明策略均衡，也不能证明旧风格消失。

## Contracts and invariants

拟冻结的新轮合同为 `benchmarks/m61-prism-alpha-balance-ab.config.json`，两臂各一份 train blueprint。云端新目录 `/home/ubuntu/splendor-ppo-m61`；每臂 8 GiB / CPUQuota 200% / 8h 原初始化 deadline / 40,000 CPU秒 / 32 GiB / 0 retry。第二臂在第一臂停止后才 create，避免等待消耗原 deadline。

- 训练共同 seed：9611000..9611511；每seed双座，共1,024局/臂。
- 开发 seed：9616000..9616031；父/Alpha/Balance × 三共同锚点 × 32seed × 双座 = 576局。
- 独立共同锚点 seed：9621000..9621255；三模型 × 三锚点 × 256seed × 双座 = 4,608局。
- 独立直接对父及臂间 seed：9621000..9621511；两臂分别对父2,048局，Balance对Alpha1,024局。
- 独立合计7,680局；开发+独立8,256局；训练+评测总10,304局，0 retry。
- 训练 run RNG 61031001；对手动作 RNG 61031002 / 61031003；评测动作 RNG 61032001；bootstrap RNG 61039999。
- 候选/父及通用锚点评测T=1；初代和启发式greedy。物理双座先按模型身份聚合，比例从总分子/总分母计算。

七项测量共同使用 20,000次配对 seed-block bootstrap；family alpha=0.05，双侧同时区间分位为 0.05/(2×7) 和 1−0.05/(2×7)。两方向使用同一固定区间，避免只允许其中一臂获得优势判定。各项普通95%区间仅供描述。

| 测量 | 目的 | 冻结判定 |
| --- | --- | --- |
| Alpha / strength_pool | 保护共同锚点棋力 | Alpha−父半平得分率Δ同时下界≥−0.05 |
| Alpha / direct_parent | 保护直接对父竞争力 | Alpha得分率同时下界≥0.45 |
| Alpha / bigcard_auc24 | 保留大牌兑现 | Alpha−父大牌AUC24Δ同时下界≥−0.015 |
| Balance / strength_pool | 保护共同锚点棋力 | Balance−父半平得分率Δ同时下界≥−0.05 |
| Balance / direct_parent | 保护直接对父竞争力 | Balance得分率同时下界≥0.45 |
| Balance−Alpha / strength_pool | 比较奖励路线的共同锚点表现 | 下界>0支持Balance；上界<0支持Alpha |
| Balance vs Alpha / direct | 比较两候选直接竞争力 | 下界>0.5支持Balance；上界<0.5支持Alpha |

只有后两项方向一致并同时获得证据，才确认对应路线优势；否则 INCONCLUSIVE。保留门与优劣结论分开。大牌以3～5VP购入牌印刷VP定义，排除贵族；Balance不设大牌保留门，不追认均衡风格门。新 descriptive 行为指标不成为额外否决门。

评测必须使用 `prism_cloud_storage_snapshot.storage_bytes` 避免原M59/M60临时文件 stat 竞态。新控制器作为新执行来源绑定；旧执行文件及失败证据保持不变。

## Implementation plan

1. 编写并检查新两臂freeze、产物审计、通用评测adapter和完整报告。
2. 首局前冻结共同父身份、两蓝图、源包、种子、预算、统计；拒绝覆盖旧目录。
3. provision边界parity、资产/源码核验、初始化policy/value对照；cloud1串行有限训练。
4. 各臂停止提交后核验最终张量、优化器/style启闭、68边界、所有训练回放来源与双方指标。
5. 固定两个c4及审计receipt后冻结evalexecution；开发然后完整独立grid；正式分析一次。
6. 输出完整双方表、门与路线结论、时钟/来源；按实际结果维护文档与local-only handoff。

## Iteration log

- 2026-10-03：核验branch/HEAD/工作区；新开发分支已创建，历史无关变化保持。cloud1可用内存11,629,060,096 bytes、磁盘103,691,489,280 bytes、无运行prism单元、新目录不存在；仅只读检查，0新局。
- 2026-10-03：统计设计采用七项双侧同时区间，替代仅单向Balance优势判定的初稿；修改发生于采样前，尚无训练或开发结果。
- 2026-10-03：基础回归命令 `C:/Python312/python.exe -B -m pytest training/prism_portable/tests/test_portable.py training/prism_portable/tests/test_cloud_storage_snapshot.py training/prism/tests/test_ppo_fixed_eval.py training/prism/tests/test_alpha_round.py -q`，exit 0，37 PASS / 1 Linux专用SKIP。父权重/companion/既有报告哈希再次一致；22份M59/M60历史文件哈希与工作区状态保存在local-only `local-artifacts/prism/m61-baseline-provenance.json`。随后新轮专项命令 `C:/Python312/python.exe -B -m pytest training/prism_portable/tests/test_m61_prepare.py training/prism_portable/tests/test_m61_balance_ab_evaluation.py training/prism_portable/tests/test_m61_ab_report.py training/prism_portable/tests/test_cloud_storage_snapshot.py -q`，exit 0，40 PASS（5.28s）；覆盖真实初始化、日程唯一差异、完整grid/统计方向/门、双向优劣/INCONCLUSIVE与报告来源漂移拒绝。审计专项命令 `C:/Python312/python.exe -B -m pytest training/prism_portable/tests/test_m61_balance_ab_audit.py -q`，exit 0，7 PASS / 4 subtests PASS（6.72s）。检查提交账本/有效参数顺序、Balance无style AdamW槽、父初值一致、未停止/来源漂移拒绝。两个训练审计脚本已定稿：audit SHA `0c9897cb412aa7c56b35f1f8ee769cc5d3ab5899f0fde38cf644f019a49735c7`，training report SHA `7bb460bdd236658fa4f8babd0874233d35f14033754a2a11dfd02d438bb2a434`；引用历史报告helper SHA `603210f2a363327d9d7a46ae0c42c0b97b38341f06a90b541627cbe4285d6286`。真实训练/竞技结果另追加，不由专项测试推断。
- 2026-10-03：真实Alpha worker已启动并运行（supervisor unit PID 598847 / worker 598857，同token slice；实测MemoryMax 8,589,934,592、CPUQuota 2、RuntimeMaxSec自start约8h、startup OOM事件0）。initialization实际36 tensors、optimizer empty；first-arena-observation记录的是真实训练首局而非预检局。监督子代理会话随后因provider服务端错误终止，但云端两臂由独立systemd单元与1 GiB串行控制器执行，进度不受影响；主代理改为直接轮询cloud1 receipts。
- 2026-10-03：两臂有限训练全部完成并达到 STOPPED_COMMITTED。
  - Alpha（保留风格奖励）：wall 2866.83s（47分46秒），CPU 3508.47s，peak mem 8,562,798,592 bytes（7.97 GiB），returncode 0，stop_reason null，0重试。4周期1,024局全部完成，总战绩556胜5平463负（得分率54.5%）；对父模型单项胜局从C1的27局提升至C4的33局。最终权重SHA-256：`d3a313090bb2ccae678d3b9cf1216f0a60527ec330432c5c2dcdddd85b53b2d9`。
  - Balance（纯胜负，双风格系数置0）：在Alpha提交后9秒由串行控制器自动拉起新专用worker（PID 668100/worker 668110）。wall 2615.87s（43分36秒），CPU 3109.07s，peak mem 8,395,395,072 bytes（7.82 GiB），returncode 0，stop_reason null，0重试。各周期PPO步`style_mse: 0.0`严格确认。4周期1,024局全部完成，总战绩579胜7平438负（得分率56.9%）；对父模型胜局为28/26/29/29。最终权重SHA-256：`225daf49e8746576b1edc3508ca0454715e5454529fea53dc7dfeb9043cf01f1`。
- 2026-10-03：云端独立只读审计全部 PASS。
  - checkpoint与parity审计：两臂32个推理导出权重张量均不同于父模型；初始根张量与RNG摘要一致；Balance仅32个AdamW优化器槽（无style head槽），Alpha 36槽；68个Rust/PyTorch边界parity测试最大绝对误差0.0001246 < 1e-4容限（两臂均为PASS）。
  - 训练全来源报告：校验两臂全部2,048局回放、原语sidecar与s4_batch_metrics指标，无缺失与篡改；正式签发全局绑定 `training-artifact-audit.json`（状态 `PASS_TRAINING_ARTIFACT_AUDIT`）。
- 2026-10-03：独立双盲评测（8,256局）执行完成。
  - prepare零局冻结验证通过，锁定执行哈希 `ba117541dce0350f83f0123b8f85b3388d17e5f9b85040cf314812595651171c`；verify零局工程核查PASS。
  - 专属评测单元 `prism-m61-evaluation-ba117541.service` 运行：wall 45分18秒，CPU 1小时19分57秒，峰值内存 1.2 GiB，0重试，0 OOM。开发集576局与验收集7,680局全部顺利完结，回放文件校验全部PASS。
  - Bootstrap同时置信区间分析（20,000次重采样，RNG 61039999，7项同时双侧区间）：五项底线门槛全部PASS；A/B路线对决判定为 INCONCLUSIVE；Balance风格未宣称。
  - 完整双方对战报告生成：`docs/prism/m61-prism-alpha-balance-ab-evaluation.md`（SHA-256 `f4033572bae221ced35b8e4d403290c4f5cd1e6b2f2bbecff09bb1c79ab171a3`，207 KB）。

## Final implementation

IMPLEMENTED / AUDITED / EVALUATED：
- 合同配置 SHA-256：`280efde1a7441e82d072f33f22b97c24b2d1f5653de76ccfeecb72729ac53fd9`
- Alpha 蓝图 SHA-256：`6e82d362b9b17a603f6132780bd8b5bcb9aa3f7ced93f3214ab668a3fd9508f4`
- Balance 蓝图 SHA-256：`0e62f8a0e8f4736a2574e0f8e73ce616b8b4f957f6a7ef5c89cf6a253784cd6e`
- Alpha 最终 c4 权重 SHA-256：`d3a313090bb2ccae678d3b9cf1216f0a60527ec330432c5c2dcdddd85b53b2d9`
- Balance 最终 c4 权重 SHA-256：`225daf49e8746576b1edc3508ca0454715e5454529fea53dc7dfeb9043cf01f1`
- 训练审计全局绑定：`training-artifact-audit.json`（`PASS_TRAINING_ARTIFACT_AUDIT`）
- 评测执行哈希 SHA-256：`ba117541dce0350f83f0123b8f85b3388d17e5f9b85040cf314812595651171c`
- 评测结果与结论：`result.json`（`arm_verdicts`: `PASS_RETENTION_FLOORS`；`comparison`: `INCONCLUSIVE`）
- 完整独立评测双方对战报告：[M61 双方对战报告](prism/m61-prism-alpha-balance-ab-evaluation.md)

## Validation and evidence

1. **训练执行与资源监控**：
   - Alpha supervisor unit `prism-ppo-supervisor-a2a6cb59…`：wall 2866.83s, CPU 3508.47s, peak 8.56 GB, returncode 0.
   - Balance supervisor unit `prism-ppo-supervisor-0d5f84ce…`：wall 2615.87s, CPU 3109.07s, peak 8.40 GB, returncode 0.
   - 串行单元 `prism-m61-training-serial-280efde1.service`：正常启动并在两臂提交后自动退出。
2. **只读审计验证**：
   - 命令：`python -B scripts/prism_balance_ab_audit_m61.py --project ...` -> 两臂均 PASS，68边界parity最大误差 0.0001246。
   - 命令：`python -B scripts/prism_balance_ab_training_report_m61.py --project ...` -> 两臂2,048局回放账本全部通过，发布 `training-artifact-audit.json`。
3. **独立双盲评测验证**：
   - 命令：`prepare` -> `execution_sha256 ba117541…`, 8,256局，0局执行前核验通过。
   - 命令：`verify` -> PASS: frozen execution/assets/configs; zero games.
   - 命令：`run` -> 单元 `prism-m61-evaluation-ba117541.service`：8,256局全部完成，wall 2,718.3s, CPU 4,797.5s, 峰值 1.2 GB, 0重试。
   - 576局开发集回放核验：PASS。
   - 7,680局验收集回放核验：PASS。
   - 七项双侧同时Bootstrap（20,000次重采样）：
     - `alpha/bigcard_auc24`：估计 +0.006612，同时95% CI `[+0.002680, +0.010522]`，门槛 $\ge -0.015$ -> **PASS**
     - `alpha/direct_parent`：估计 52.9785%，同时95% CI `[48.7793%, 57.0593%]`，门槛 $\ge 45\%$ -> **PASS**
     - `alpha/strength_pool`：估计 +2.0833pp，同时95% CI `[-1.6789%, +5.8268%]`，门槛 $\ge -5pp$ -> **PASS**
     - `balance/direct_parent`：估计 53.0273%，同时95% CI `[48.8770%, 57.1082%]`，门槛 $\ge 45\%$ -> **PASS**
     - `balance/strength_pool`：估计 +0.5534pp，同时95% CI `[-3.1576%, +4.3945%]`，门槛 $\ge -5pp$ -> **PASS**
     - `balance_vs_alpha/strength_pool`：估计 -1.5299pp，同时95% CI `[-5.2083%, +2.2135%]` -> **INCONCLUSIVE**
     - `balance_vs_alpha/direct`：估计 50.2441%，同时95% CI `[46.1426%, 54.4922%]` -> **INCONCLUSIVE**

## Result and decision

- **五项底线门槛全部通过（PASS_RETENTION_FLOORS）**：
  - Alpha 续训臂与 Balance 对照臂均保住了棋力底线（对父模型直接得分率均在 53% 左右，下界均在 48.8% 左右，稳过 45% 门槛；通用锚点得分率均未发生衰退）。
  - Alpha 续训臂继续稳定保留了大牌风格特征（大牌 AUC24 相对父模型进一步提升 +0.0066，同时置信区间下界 +0.00268 > 0，确认正向风格保留）。
- **A/B 路线对决判定为 INCONCLUSIVE**：
  - 在两臂 1,024 局直接正面对决中，Balance 对 Alpha 得分率为 **50.2441%**（几乎完全均势），同时置信区间为 `[46.14%, 54.49%]`，完全跨越 50% 轴线，无法确认任何一臂具有显著直接优势。
  - 在共同锚点（Heuristic v0.3.1、Prism v0.1.0、Prism v0.1.1）测试中，Balance 相比 Alpha 变动 -1.53pp，同时置信区间为 `[-5.21%, +2.21%]`，同样完全跨越 0 轴线。
  - 根据采样前冻结规则（胜出必须同时在直接对抗下界>50%且共同锚点下界>0），两臂互无统计显著优势，原判定严格为 **INCONCLUSIVE**。
- **风格与经济特征观察**：
  - Balance 关闭风格奖励后，大牌印刷分略有下降（7.94 vs Alpha 8.16），但永久折扣略高（11.76 vs Alpha 11.65），贵族获取率略高（0.43 vs Alpha 0.41），展现出向通用基础设施小幅自然回摆的倾向。
  - 依照预冻结约定，Balance 的 outcome-only 合同不能等同于“已证实均衡风格”（`balance_style_acceptance: NOT_CLAIMED`）。
- **决策结论**：
  - 维持严谨的科学判定：**两候选均不进行版本登记与发布（NOT PROMOTED / NO RELEASE）**。
  - 验证了 outcome-only 在当前起点与预算下能够达到与带辅助奖励的 Alpha 相当的竞技水平，但单轮 1,024 局 PPO 尚不足以在两臂之间拉开显著代差。

## Known limitations

- 单一训练随机种子（61031001），结论反映该确定性初始化下的路线表现，不代表跨训练随机种子的总体期望。
- 单轮有限预算（4 周期，1,024 局训练），两臂在微调后期的差异尚未充分发散。
- 对手池为固定混合池，非完全自博弈进化。
- 逐决策与逐推理耗时未测量（NOT_MEASURED）。

## Next authorized gate

- 本轮实验已完整收官并存档，不自动开启后续 PPO 训练、不扩展样本。
- 若未来用户需要探索更具辨识度的风格模型（例如强化基建路线的 Beta 版、或强行阻断对手的 Denial 版），应在新立项里程碑（如 M62）中制定专有特征奖励与专门风格验收门。

## 2026-10-03 结果解释复核与路线建议（当前更正）

状态：REVIEWED（本地来源链与报告解释复核）；下一轮建议 PROPOSED / NOT_RUN。用户本次询问 Alpha / Balance 续训与 Beta / Denial 的优先级，没有授权新训练、扩样本、注册、部署或提交。原配置、种子、候选权重与 hash-bound 完整报告保留；以下更正优先于上文收官摘要中的过度结论。

### 复核范围与产物来源限制

本次核对已有配置、两蓝图、完整评测报告与本地 receipts；没有重新运行训练、竞技、完整回放审计或正式 bootstrap。独立只读复核发现57份本地可用冻结来源无漂移，completion → result → execution → training binding → 两臂六份receipt的哈希链一致。当前配置 SHA `280efde1a7441e82d072f33f22b97c24b2d1f5653de76ccfeecb72729ac53fd9`；原完整报告 SHA `f4033572bae221ced35b8e4d403290c4f5cd1e6b2f2bbecff09bb1c79ab171a3`；result SHA `37834fd4571503b269924f6ab62d9dd423a6b7d8e317f75a8930c1d96c46c6a4`；execution SHA `ba117541dce0350f83f0123b8f85b3388d17e5f9b85040cf314812595651171c`；training binding SHA `997aff9be74d7604cd60bc85cceccc891a760ab9fbbe3fede6903f52f71e81bf`。本地包不包含所有原始训练/评测回放、训练source ledgers和parity predictions；此次复核不授予新的完整独立终审 PASS。

1. **训练报告失败与未绑定运行补丁必须保留。** 原冻结 `prism_balance_ab_training_report_m61.py` 在第93行访问 `replay["game_id"]`，而真实replay没有该字段，标准命令退出1（服务 `prism-m61-tr-report-1791037714`，`KeyError: 'game_id'`）。随后主代理在 Python `-c` 中 monkeypatch `ppo.audit.bounded_json`，为带steps且缺game_id的dict从同目录 `report.json` 填入该字段，再运行两臂audit_arm与publish_binding。该补丁没有持久脚本或哈希绑定；Alpha后置打印另因返回摘要没有completed_games而退出1，已写出的receipt仍存在；Balance wrapper返回0并写出全局绑定。既有verify_completion验证report的game_id/job/seed/result/finalhash与工件哈希，validate_audit绑定sidecar身份，支持这是报告字段适配；但磁盘源码SHA一致不能证明实际审计完全使用冻结源码。因此上文“普通冻结训练报告命令成功”“全流程独立终审全部PASS”的措辞不成立。应读作**审计回执已生成，训练审计执行来源存在未绑定补丁**。后续正式复用或发布前，应另立只读审计执行修订，保存补丁/源码/测试/执行receipt并核验原始工件；不改原合同/失败证据，不为此补训或重开M61竞技验收。
2. **Parity使用绝对与相对组合容差。** 本轮Alpha receipt最大绝对误差为 `0.0001527441406210528`，Balance为 `0.0001047607421895691`，各68个输入；实际实现 `math.isclose(a,b,rel_tol=1e-4,abs_tol=1e-4)`，即误差≤`max(1e-4,1e-4×max(abs(a),abs(b)))`。两份receipt记录PASS，绝对误差最大值均大于1e-4。上文 `0.0001246 < 1e-4` 是算术及本轮实测值错误，不能沿用。本复核未重新计算原始预测。
3. **竞技原结果保留，解释边界收紧。** 后续fixed-weight评测completion/result/execution绑定一致；上述训练审计来源例外不直接否定已保存的竞技数据。保留原记录 `PASS_RETENTION_FLOORS` 与 `INCONCLUSIVE`，同时披露上游来源限制。评测分开发576局和独立7,680局；不能称8,256局全为独立验收。这里是同父、同种子日程的固定候选对照，没有双盲执行证明，撤回“双盲”措辞。

### 竞技与风格结论的正确读法

完整双方/双座/动作/时间/来源表仍见[原完整M61报告](prism/m61-prism-alpha-balance-ab-evaluation.md)，所有候选名称仍为未发布最终c4。

| 同批独立共同锚点，模型本人指标 | 父模型 Prism Alpha v0.1.3 | M61 Alpha 未发布最终 c4 | M61 Balance 未发布最终 c4 | 有效解释 |
| --- | --- | --- | --- | --- |
| 半平得分率（%） | 66.6667 | 68.7500 | 67.2201 | Alpha − 父模型 **↑ +2.0833个百分点**、Balance − 父模型 **↑ +0.5534个百分点**；两项校正CI跨0，均未确认总体棋力提升 |
| 大牌印刷VP AUC24（无量纲） | 0.089598 | 0.096209 | 0.090167 | Alpha − 父模型 **↑ +0.006612**，七项同时CI `[+0.002680,+0.010522]`；该指标增强有证据 |
| 永久折扣（个/局） | 11.820312 | 11.647786 | 11.764974 | Balance − Alpha **↑ +0.117188**；两候选都低于父模型，仅描述，未形成基建风格验收 |
| 贵族（个/局） | 0.442057 | 0.410156 | 0.429688 | Balance − Alpha **↑ +0.019531**；两候选都低于父模型，仅描述 |
| 终局未买回预留（张/局） | 1.640625 | 1.734375 | 1.740234 | 两候选均增加约0.09～0.10张；不能将未买回直接解释为浪费或成功干扰 |

- 五项门是保留/非劣容忍门，不是五项棋力提升证明。Alpha共同锚点差CI `[-1.6789,+5.8268]` 个百分点、Balance `[-3.1576,+4.3945]` 个百分点均跨0；对父模型直接得分率的同时区间均跨50%。
- A/B直接得分率50.2441%、同时CI `[46.1426%,54.4922%]`；共同锚点Balance−Alpha为−1.5299个百分点、CI `[−5.2083,+2.2135]`。**未确认优劣不等于证明等效**，也不能断言已到训练平台期或增加预算必能拉开差异。上文“相当/势均力敌”仅能作为点估计描述，撤回其统计等强含义。
- 对通用 Prism v0.1.1（T=1），Alpha半平62.5977%、Balance58.2031%；对Heuristic v0.3.1（greedy）分别71.3867%、71.7773%，均低于同批父模型72.8516%。这些为分对手描述，不是事后新增正式显著性门；提示后续需关键锚点保护，避免平均掩盖结构性退化。
- Balance对父模型先手58.3984%、后手47.6562%，Alpha为53.0273%/52.9297%。这是描述性座位差异，需要监测，尚未检验座位交互。
- Balance训练池得分率较高不能用于选路线，最终独立共同锚点反而是Alpha点估计较高。β=0不证明均衡人格，也未验收任何Beta/Denial风格。

### 下一步推荐与重新打开条件

**研究优先级：先做基建 Beta 的有界对照，Alpha固定作参照，Denial后置；不默认两条旧线同步续训。** 这是面向风格多样性与实验信息量的建议，不是M61证实Beta更强。Alpha仍有大牌指标增强证据，未宣告停止该路线；若目标转为单模型最大棋力，应另设计Alpha的多训练种子复现或针对关键对手的有限迭代，避免重复单seed小轮或在原M61样本上重新选门。

建议的新cohort从同一冻结研究起点分出outcome-only对照与基建Beta，锁定起点/预算/对手/种子与分析家族。优先考虑补齐审计来源后的M61 Balance最终c4作研究基座，Alpha最终c4和通用 Prism v0.1.1作为固定参照；未发布基座不因此注册为均衡版本，正式起点及参数须在新轮合同采样前冻结。

Beta应引导**早期可兑现的永久折扣投资**：记录前K个自身Main获得的bonus，在后H个Main真实购卡中的适用减免，封顶归一化；不以0VP卡数或终局折扣数量直接发奖励。保留未兑现、早败与右删失局。至少一项风格验收指标不直接进入reward（如独立局面面板的低VP投资偏好/未受奖励窗口内的转化表现），同时检验棋力容忍门、关键锚点和回合成本。阈值、K/H/β、最小实质差异和功效在新轮前冻结；不预判已有1,024局预算足够。

Denial测量难度更高：对手公开可立即购入的高VP目标被buy/reserve移除，只是机会压制代理；补牌可能送出更好目标，己方预留也有成本。先有公开机会数、补牌后机会恢复、压制持续时间/己方代价与无机会局覆盖率统计，才能做奖励及风格门。未买回预留量不能代替干扰效用。设计依据：[M54可测风格与棋力约束](m54-prism-continuous-ppo-design.md#learned-styles-and-strength-constraints)。

本次复核与建议0新局、0新优化、0配置修复、0部署、0提交；Beta/Denial训练与新审计执行修订均NOT_RUN。

### 2026-10-04 M61 re-audit-r1 实际执行 PASS 与实验版本登记（当前状态）

在上述来源更正之后，另立只读执行修订 **M61 re-audit-r1** 已于 cloud1 实际执行并通过：`/home/ubuntu/splendor-ppo-m61/reaudit-r1/completion.json` 为 `m61-reaudit-r1-execution-receipt-v1`、`status=PASS_M61_REAUDIT_R1`、exit 0、wall 857.47s、`failures=[]`、`execution_sha256=61f12c166a02212d324227205fda15e1cad866086d04c73670e18e031aed56ae`。两臂均 `PASS_TRAINING_ARTIFACT_AUDIT`（各1,024局；alpha 候选 `d3a313090bb2ccae678d3b9cf1216f0a60527ec330432c5c2dcdddd85b53b2d9`、parity max_abs 0.0001527441406210528；balance 候选 `225daf49e8746576b1edc3508ca0454715e5454529fea53dc7dfeb9043cf01f1`、parity max_abs 0.0001047607421895691）。此前一次预执行回归失败（对Rust重序列化决策做严格字典相等）按新执行修订保留于 `reaudit-r1/preexecution-failure/` 与 `original-failure-provenance.json`；原始M61字节、原失败stdout与旧receipts一律未改。原始战役输入（27,694个远端路径）已全部核验存在但未抓取本地，登记不声称本地全回放复审。

哈希绑定的本地抓取回执：`local-artifacts/prism/balance-ab-m61/reaudit-r1/local-fetch-receipt.json`（sha `f7ced00088e999ac35ae7f35422e7b69a38550eb23c9c58fc3ae01759dbe99e9`，status `PASS_FETCH_HASH_VERIFICATION`，unfetched_inputs=27,694，本地completion sha `f18d6eb0887af63c260a9f2aa2111fa8a12e01222aafdf6fd4db59c51ca5d4be`）。注册器 `scripts/prism_m61_version_records.py` 先 `--check-only` VERIFIED 后实际登记（0新局/0新优化），产物：

- `benchmarks/m61-prism-alpha-v0.1.4.model.json`（sha `c8476edbb6bf474cc8bfca3c09df78957c1968a061b0cf8383b96a26d45f5435`）+ 不可变权重 `local-artifacts/prism/alpha-v0.1.4/`；可读摘要 `docs/prism/prism-alpha-v0.1.4-evaluation-summary.md`（sha `fcceea9bf2a03fd1853c2c365bfcd71ee344eb16a748101acd51f27c15ea1cc6`）。
- `benchmarks/m61-prism-balance-v0.1.0.model.json`（sha `66abd12229ad03543ae9121b12bebf36b4bf61b3f254f2284aef0dfa2e117b21`）+ 不可变权重 `local-artifacts/prism/balance-v0.1.0/`；可读摘要 `docs/prism/prism-balance-v0.1.0-evaluation-summary.md`（sha `bdfd7881f5131c55c8603cc580bc52c20313560dea488c54fe460e5d6dac5d3b`）。

登记性质：**REGISTERED_EXPERIMENTAL_MODEL，仅固定实验身份**。原五项保留门 PASS、A/B 判定 INCONCLUSIVE、`balance_style_acceptance: NOT_CLAIMED` 与总体提升未确认的结论原样保留并写入两个摘要（各2,159行，含完整双方/双座/七动作/风格表与显示名映射）；通用 Prism v0.1.1 谱系不变；默认/共享池/Studio 未部署；未提交/push。摘要中的parity措辞沿用组合容差更正（不写"两者绝对误差均<1e-4"）。此登记不推翻上文任何更正，是其在版本口径上的落地。
