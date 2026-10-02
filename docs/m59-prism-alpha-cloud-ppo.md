# M59 Prism Alpha：cloud1 大牌冲分 PPO 续训

Status: **AUTHORIZED / FROZEN_BEFORE_FIRST_GAME**；训练启动核验见下方追加记录。开发与独立验收 **NOT_RUN**。
Baseline: main@ba7cb1958daeccbe5391d6bd769c677d50ac3f94；保留其他任务的未提交改动。
Owner/date: 用户“在云端现在启动迭代训练”，2026-10-03（北京时间）。

**产物结论：**从固定 **Prism Alpha v0.1.1** 推理权重创建新 PPO 训练线，继承 policy/value；新 AdamW、style head 和 RNG。没有使用 M57 工程校准检查点。最终 c4 在验收前称为 **M59 未发布训练候选**，预留验收后的版本名 **Prism Alpha v0.1.2**。

**竞技结论：NOT_RUN。**训练完成和工程检查不能代替开发评测、独立验收或证明增强。

**风格结论：NOT_RUN。**本轮沿大牌冲分方向，维持原 24 Main 总分代理和 β0.3；能否保护或增强大牌兑现由新的独立样本判断。

## Problem and evidence

M56 固定 Prism Alpha v0.1.1 已完成四轮训练并通过三项保留门，大牌印刷 VP AUC24 有增强证据；总体棋力和直接父模型增强没有统计确认。[原完整双方表](prism/prism-alpha-v0.1.1-evaluation-summary.md)保持原判定。

[M57](m57-prism-portable-ppo.md)验证了 Windows/Linux ARM 的启动、终止、完整状态跨机恢复；同32局小规模任务，当前负载下 cloud1 71.862秒、本机150.437秒。此速度不外推为本轮1,024局必然耗时。当前 cloud1 两个CPU、可用约10.8GiB内存，适合承担本有限训练。

## Initial design

保持风格代理和 PPO 参数，增加两个固定训练对手：通用 Prism v0.1.1 与父模型 Prism Alpha v0.1.1。对手全部 greedy，学习器按实际学得策略 T=1 采样。较新模型不等于其 greedy 模式已经测得更强；该配比是研究设计。

新环境种子、最终 c4 选择、三个保留门与资源总额在首局前固定。开发只描述最终候选，不能选中间检查点、调整奖励、重抽种子或扩大预算。

## Scope and non-goals

当前动作是在 cloud1 启动一次 **4轮 × 256局 = 1,024局** PPO。资源上限：创建起8小时墙钟、40,000累计CPU秒、4GiB自有进程树内存、32GiB retained campaign存储、2CPU线程/200% CPU quota、0基础设施重试。到原始截止或预算用尽即停止并保留失败证据。恢复/换机保留原 deadline 和消耗。

仅最终 c4 进入后续固定384局开发和4,096局独立验收；这些评测目前 **NOT_RUN**，本次启动器只执行训练。通过后再固化 Prism Alpha v0.1.2 身份。默认模型、Studio注册、共享池、历史模型和旧负结果均维持现有状态。

## Contracts and invariants

[冻结配置](../benchmarks/m59-prism-alpha-cloud-ppo.config.json) SHA **cab7dde789ffc96c20f6b22b8acb58ae3c1d48477f9b388bf19867d0ddb2f3ac**；[便携训练计划](../benchmarks/m59-prism-alpha-cloud-ppo.train.json) SHA **32cc86fe7e6b5bf9a1cf602064547a10e8703f638134c1c002af8630fd4f4377**。遵循 [M54 PPO合同](m54-prism-continuous-ppo-design.md)、[M51接口](m51-prism-implementation-contract.md)、[详细指标标准](unified-match-metrics-standard.md)及[M57操作说明](prism/portable-ppo-operations.md)。

| 训练模型 / 固定对手 | 学习器 / 对手模式 | 每轮局数 / 环境seed块 | 全轮局数 | 身份 |
| --- | --- | --- | --- | --- |
| M59未发布学习器 / 通用 Prism v0.1.1 | T=1 / greedy | 128 / 64 | 512（50%） | a2301f0878f9c342a61b83fd45412f72ba95acfca895dafbe7ceca0360f34a85 |
| M59未发布学习器 / 父模型 Prism Alpha v0.1.1 | T=1 / greedy | 64 / 32 | 256（25%） | d57ebe2407b5d061ae890f3d2586924754e0d2d8e502e1f3f32d12c1fc9af4ff |
| M59未发布学习器 / 初代 Prism v0.1.0 | T=1 / greedy | 32 / 16 | 128（12.5%） | 5db70b773083858b83c6e679d5641f1b78d4c5fbe34c48950cc906064f821b54 |
| M59未发布学习器 / 便携 Heuristic v0.2.9 | T=1 / greedy | 32 / 16 | 128（12.5%） | ARM main binary与Hello绑定，见下文 |

父模型含义：本轮开始时的固定 Prism Alpha v0.1.1；候选是在它基础上再学习四轮。通用 Prism v0.1.1 是另一个模型家族，不是本轮父模型。

| 合同 | 首局前固定值 |
| --- | --- |
| 奖励 | 前24次自身Main的 min(公开自身VP,15)/15 平均；短局按终局分补足；贵族选择归前一个Main |
| PPO | LR3e-5、β0.3、style value weight0.5、2 passes、minibatch256、clip0.2、KL0.02、entropy0.01、γ1/GAE λ0.95；float32 CPU2、无AMP/TF32 |
| 训练种子 / RNG | 9590000..9590511，各双座一次；训练action/RNG seed59010001；各对手参数见train JSON |
| 开发种子 | 9595000..9595031；父模型/候选各三共同对手×32块×双座=384局 |
| 独立种子 | 9600000..9600255共同锚点；9600000..9600511直接父模型；共享prefix为匹配布局，均未训练 |
| 评测模式 | 父模型/候选T=1；共同初代与便携Heuristic为greedy，通用Prism v0.1.1为T=1；sample action seed59020001 |
| 独立统计 | 20,000次seed块bootstrap，RNG59029999；三门family α0.05，单侧lower quantile0.05/3 |
| 中间检查点 | 不发布、不作为最终选择；只评最终c4 |
| 数值源身份 | a6e502b5d54358b8a8c4122ddabfb11e949dc976a957335b15ad91c2c3f62c24，与M57相同 |
| 当前控制包身份 | 9f5dd4829024de8b6a5215ebb963651186504ab35459f1c7509133a624fc4749 |
| ARM原生身份 | /home/ubuntu/splendor-ppo-m57/build/release/splendor；SHA 1a13af46327650c20675994b3347047ecadd5068e701ad3808322ec8ac528d4b |
| ARM经济指标程序 | s4_batch_metrics SHA ba3f2cbe49e5839ae0b5ca220425c5e79ec901f368eabfc12bc2463c0fe265dc |

Heuristic Hello是 splendor-cli-heuristic-v02 / 0.2.9；这不是M56固定Windows Heuristic v0.3.1二进制。同本轮原生程序评父模型和候选才构成匹配比较，不能将变化归因于“只改变对手配比”。Rust源快照沿用M57的305文件，逐文件hash在冻结配置中；旧76项冻结输入在首局前hash通过。

### 三个保留门与增强判定

| 门 / 目的 | 冻结阈值 | 估计 / 不确定性 | 失败具体含义 |
| --- | --- | --- | --- |
| strength_pool / 保护总体半平得分率 | 共同锚点配对Δ校正下界≥−0.05（−5个百分点） | NOT_RUN | 新样本不足以保证退化在许可范围；不自动等于模型完全不可用 |
| direct_parent / 保护对Alpha父模型能力 | 对父模型半平得分率校正下界≥0.45 | NOT_RUN | 未达到45%保留底线；CI精度不足与确定退化须分别解释 |
| bigcard_auc24 / 保留大牌兑现画像 | 3～5VP购卡印刷VP累计AUC24配对Δ校正下界≥−0.015 | NOT_RUN | 不能确认大牌目标在声明容忍量内；贵族不计入本风格量 |

三门均过表示可保留迭代产物，**不要求所有描述指标变好**。同校正下界分别>0、>0.5、>0才支持对应竞技/直接/风格增强。个别对手胜率、经济与动作数据为诊断，没有另加硬门。

## Implementation plan

1. 首局前固定合同、种子和来源；验证父模型导入、68固定边界输入、真实Hello与进程预算。
2. 独立cloud1目录与systemd用户cgroup执行四轮；循环按冻结计划结束，不无限续训。
3. 最终c4冻结导出并核验32张量及68边界；之后按上述新种子执行开发/独立验收。
4. 生成双方完整Markdown表和匹配父模型→候选变化，按门给出保留/增强/失败判定。

## Iteration log

- 2026-10-03：用户明确授权云端启动。首局前核对cloud1资源、固定权重、原76项输入与新的种子范围。
- 2026-10-03：为8小时有限合同，将Linux supervisor的固定RuntimeMaxSec=7200改为原resource-ledger deadline的剩余秒数；已过期启动在发布STARTING前拒绝。PPO数值实现不变；M57旧目录/已测包和性能结果保留。
- 2026-10-03：本机测试22 PASS/1 Linux专用SKIP，exit0；ARM测试与启动实测待追加。

## Final implementation

IMPLEMENTED：training/prism_portable/control.py 支持按原deadline有界云端启动；scripts/prism_alpha_cloud_prepare.py只允许首次冻结M59、核对来源和旧种子，重复准备会拒绝覆盖。专属目录 /home/ubuntu/splendor-ppo-m59，完整状态/任务/预算通过M57控制协议保存。

## Validation and evidence

启动/实时回执归档到 local-artifacts/prism/alpha-cloud-m59；机器状态见[本轮状态记录](../benchmarks/m59-prism-alpha-cloud-ppo.result.json)，可读评测见[结果记录](prism/prism-alpha-cloud-m59-evaluation.md)。上述链接的文件在启动前建立，不能把NOT_RUN误作已测结果。

详细对战、配对CI、双座、双方VP/速度/时长、购卡0..5VP、五色折扣、贵族、预留全生命周期、七类动作、时钟负载和来源将在阶段结果记录中按完整标准输出。逐推理/逐决策时钟 **NOT_MEASURED**。

## Result and decision

采样前：训练NOT_RUN；竞技/风格NOT_RUN；候选未发布。启动后追加真实状态与进度，不追改本冻结快照。

## Known limitations

只有一个候选与一次训练RNG，greedy固定对手池有限；不保证变强。公开总VP代理也奖励小牌和贵族，大牌画像须独立验证。M57短校准不预测长轮准确耗时。ARM浮点更新不保证同Windows逐位相同。0基础设施重试表示中断后可能按原合同停止，不能换种子重赛冲淡失败。

## Next authorized gate

完成本有限四轮并固定最终c4；以已固定的开发/独立样本评测后给出结论和完整表格。正式默认/共享池/Studio替换由后续明确发布决定控制。

### 首局前合同核对修正

开发评测三锚点ID沿用了M56旧名称，现改成已声明的M59便携运行身份；0新局，种子/门槛/训练计划不变。原配置SHA 4f5139db0386a6760e8883e4de1bb7e0f2b7f0b004b0b7f37edb401064afa65d保留于local-artifacts/prism/alpha-cloud-m59/preflight-config-v1.json；[修正回执](../benchmarks/m59-prism-alpha-cloud-ppo.preflight-amendment.json)。当前配置SHA cab7dde789ffc96c20f6b22b8acb58ae3c1d48477f9b388bf19867d0ddb2f3ac。

### 云端真实启动核验 — 2026-10-03T06:32:54.794214+08:00

**TRAINING_RUNNING**：cloud1自有supervisor PID 382840，systemd ActiveState=active/SubState=running；SSH退出后继续执行。当前快照 68/1,024局已完成，另1局进行中；retry0、ledger_failed=false。这是第一轮训练采样，不是已完成迭代/棋力增强。

| 启动检查 | 实测证据 | 结论 |
| --- | --- | --- |
| ARM/Python推理边界 | 68/68，math.isclose atol/rtol1e-4，max abs0.0001091748 | PASS |
| 完整云端控制测试 | 23 passed /0.96秒，exit0；包含长deadline与到期拒绝 | PASS |
| 父权重初始化 | 32 policy/value张量逐元素精确继承；AdamW slots0、step0、cycle0 | PASS |
| 四个对手真实Hello | 通用/父模型/初代/Heuristic均与冻结描述匹配；handshake后有意EOF，0局 | PASS |
| 本机M59迁移目标 | 独立local-root已provision，68边界PASS；新general资产绑定通过 | PASS（0局，未迁移） |
| 原墙钟执行 | RuntimeMaxUSec=7h59min12s，未重新给足8h | PASS |
| 内存范围 | cgroup MemoryMax4GiB，快照peak约574.8MiB | 已测自有slice；非逐推理时钟 |

绑定合同 SHA efc38465ddff645902cf1939fff4a4a689c11899fae4638f6c74e7b22fbf8c3a；启动账本commit 92ec4ae93b0b328702fb4ee5352b9e1bf02f9bde9461ac63afbe07df0954c226。完整回执索引和hash见机器结果，原始回执在local-artifacts/prism/alpha-cloud-m59；原nonce/运行参数不公开到服务。

### 查看与停止本轮

~~~powershell
$alphaProfiles = "local-artifacts/prism/alpha-cloud-m59/profiles.json"
$alphaCampaign = "/home/ubuntu/splendor-ppo-m59/campaigns/m59-alpha-bigcard-g0"
C:\Python312\python.exe -B scripts/prism_portable_control.py --profiles $alphaProfiles --host cloud1 status --campaign $alphaCampaign
C:\Python312\python.exe -B scripts/prism_portable_control.py --profiles $alphaProfiles --host cloud1 stop --campaign $alphaCampaign --mode boundary
~~~

正常换机先等 STOPPED_BOUNDARY，再按[M57交接操作](prism/portable-ppo-operations.md)使用此M59 profiles进行transfer。当前云端owner独占，不能同时在本机开同一条线。0retry合同保留，强制中断不保证剩余局可继续；正常采用提交边界停止。
