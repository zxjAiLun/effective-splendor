# M60 Prism Alpha 大牌冲分续训（cloud1，8 GiB 修复版收尾）

状态：AUTHORIZED / IMPLEMENTED（合同已冻结，训练尚未启动）
基线：main@d1b2c182cb64aa0725ca61e1b86cba9bc92d8c77（含收尾修复）
负责人/日期：Zixuan Tang / 2026-10-03
授权：用户 2026-10-03 原话「继续迭代？」

## Problem and evidence

M59 四轮 cloud1 训练的 1,024 局/216 更新/最终 c4 已全部提交并独立核验
（`docs/m59-prism-alpha-cloud-ppo.md`），但原 4 GiB 训练监督器在四轮提交完成后的
收尾阶段触发 cgroup OOM：`memory.events oom=2 / oom_kill=1`，worker unit
`Result=oom-kill`、exit −9，自有 tree 峰值 4,294,995,968 bytes。失败原记录永久保留。

事后源码复核（无逐分配 profiling，不声称唯一来源）：`worker.execute` 在训练循环
结束后再次 `Run.open(root / "run")`，此时原 `campaign`（含 `campaign.run` 的
Learner、behavior 缓存、整批 batch 缓存与 state）仍存活，构成两份完整运行实例并存。
`Run.open/_reload` 自身无实例内重复加载；其加载时对已消费 batch 做完整解析校验后
保留一份缓存，属有界稳态占用，非本次重复来源。

用户在 M59 收口后要求「继续迭代？」，即沿大牌冲分方向从固定 Prism Alpha v0.1.2
继续一次有限 PPO。按既定纪律：先修复收尾重复加载并用有界工程检查验证，再冻结新
合同启动训练。

## Initial design

- 从固定 Prism Alpha v0.1.2 权重（SHA `faada9ba…`）warm start；新 AdamW/style
  head/RNG；不是 M59 checkpoint 续跑。
- 4 轮 × 256 局 = 1,024 局训练；对手配比与 M59 相同（通用 Prism v0.1.1 50%、
  Alpha 父模型 v0.1.2 25%、初代 Prism 12.5%、便携 Heuristic v0.2.9 12.5%，全部
  greedy）；PPO/style 参数与 M57/M59 逐字相同（`window_main_actions=24` 总VP代理、
  β=0.3、style-value weight 0.5、lr 3e-5 等）。
- 训练内存上限 8 GiB（用户已授权 cloud1 内存提升；M59 原 4 GiB 训练合同不改写）。
  墙钟 28,800 s / CPU 40,000 s / 存储 32 GiB / CPUQuota 200% / 0 基础设施重试，
  沿用 M57 portable 执行协议。
- 收尾修复：`worker.execute` 在最终权威 `Run.open` 前释放 `campaign` 与 launch
  ledger 引用并 `gc.collect()`；最终 open 的语义不变（仍是独立从盘重载的收尾核验）。

## Scope and non-goals

- 不改默认模型、共享池、Studio、server1；不 push 远端。
- 不重写/不改标 M59 的冻结产物、FAILED 记录、种子与门；不重放已完成对局。
- 最终只取 c4；开发局只描述，不选检查点、不改门。
- 便携 Heuristic 以 Hello 0.2.9 为准，不等价于 M56 冻结 Windows v0.3.1 教师。

## Contracts and invariants

- 冻结合同：`benchmarks/m60-prism-alpha-cloud-ppo.config.json`
  SHA `afa21fc1e588ecc80e8bab64ca08392448758d68d47544900f48b8eaa9f89c4b`；
  `benchmarks/m60-prism-alpha-cloud-ppo.train.json`
  SHA `a5e45455332a4514baac3cf3c77f5bc6a589ebe701e405b5fef7e17130d5c50d`。
- 执行包（含修复）：`local-artifacts/prism/alpha-cloud-m60/portable-package.tar.gz`
  SHA `b404dfbbc93fc629810c2c2d5196a7cbc0d68e7d9b1d639571697d946dc29ba4`；
  code identity `a2f7633e6edb51fa255f836bbda2af7ea68b24f5fd6cd5fae07cae058f69b27a`。
- **numerical identity `a6e502b5d54358b8a8c4122ddabfb11e949dc976a957335b15ad91c2c3f62c24`
  与 M59 完全一致**：`numerical_identity()` 只覆盖 `engine/`，worker 修复不触碰
  PPO 数值实现。
- 种子预留（对 REGISTRY + M56 + M57 + M59 冲突检查 PASS）：训练
  9591000..9591511，开发 9596000..9596031（永不训练），独立 9601000..9601511
  （永不训练）。运行种子 59031001；对手动作种子 通用 59031002 / 父模型 59031003；
  评测动作种子 59032001；bootstrap RNG 59039999。
- 候选名（若验收通过）：Prism Alpha v0.1.3；父模型 Prism Alpha v0.1.2；通用模型
  Prism v0.1.1 为固定对手。
- 云端根目录 `/home/ubuntu/splendor-ppo-m60`（新目录；M57/M59 目录不动）；
  原生引擎/度量工具沿用 m57 冻结构建并在 provision 时逐 SHA 核验。

## Implementation plan

1. 首局前：修复 `worker.py` 收尾重复加载并提交；冻结 M60 合同/包/回执；云端
   新目录部署 + provision（68 边界 parity）+ 六资产 host 绑定。
2. 有界工程检查：用真实 M59 已提交 run 的副本在 cloud1 上量化收尾
   `Run.open` 内存（重复实例 vs 修复后单实例），对照 4 GiB 旧上限与 8 GiB 新上限。
3. `control create/start --cycles 4` systemd 自有 cgroup 训练；监控进度/预算。
4. 四轮提交后独立审计（张量/边界/来源/守恒）；再按 M59 协议执行 384 开发局 +
   4,096 独立验收局与既定三门。

## Iteration log

- 2026-10-03：核验 cloud1 空闲（可用内存 11,668,119,552 bytes、磁盘 116 GB、
  0 运行中的 prism 单元；历史 FAILED 单元保留）。定位收尾重复实例原因并修复
  `training/prism_portable/worker.py::execute`（提交 d1b2c18）；46 项相关测试
  PASS / 1 Linux 专用 SKIP，exit 0。
- 2026-10-03：`scripts/prism_alpha_cloud_prepare_m60.py` 冻结 M60 合同。M60
  blueprint 与 M59 逐字段差异仅为：run_id/种子/job_id/环境种子(+10000)、对手键
  `alpha-parent-v011→v012`（256 处）、父模型权重哈希、内存 4→8 GiB、model_label；
  ppo/style/learner/arena/budget 结构零差异。76 项历史冻结输入 0 漂移。
- 2026-10-03：用户授权原话记录于 config `owner_authorization`（问句原样保留）。

## Final implementation

IMPLEMENTED：worker 收尾单实例化修复 + M60 冻结合同/包。云端执行与训练状态
在下方追加，不追改本冻结快照。

## Validation and evidence

冻结回执：`local-artifacts/prism/alpha-cloud-m60/freeze-receipt.json`。
训练 NOT_RUN；开发/独立竞技/风格 NOT_RUN；逐推理/逐决策时钟 NOT_MEASURED。
收尾内存探针与训练资源实测将在执行后按实测值追加。

## Result and decision

尚未训练，无竞技/风格结论。禁止从代码存在或离线指标推断 PASS/ACCEPTED。

## Known limitations

- 单候选、单训练 RNG；greedy 固定对手池；不保证变强。
- 收尾修复未做逐分配 profiling；8 GiB 上限下的真实峰值以本轮实测为准。
- ARM 浮点不保证与 Windows 逐位相同；M57 短校准速度不预测本轮耗时。
- 0 重试合同：中断后可能按原合同停止，不得换种子重赛。

## Next authorized gate

四轮提交 → 独立审计 → 按已冻结开发/独立种子执行评测与三门判定；默认/共享池/
Studio 发布由后续明确决定控制。

### 云端部署与收尾探针 — 2026-10-03（训练启动前）

cloud1 新目录 `/home/ubuntu/splendor-ppo-m60`：包/合同/权重逐 SHA 核验一致
（code identity `a2f7633e…` 与冻结回执相同）。provision 68/68 边界 parity PASS，
max abs `0.0001045727539121799` 与 M59 最终边界完全一致（数值实现未变）；六资产
host 绑定逐 digest 核验（engine `1a13af46…`、metrics `ba3f2cbe…`、parent
`faada9ba…`、general `a2301f08…`、initial `5db70b77…`、fixtures `81c3f01d…`）。
`general` 资产按标准五资产 provision 后追加并留 `inputs-amendment.json` 回执，
镜像 M59 的六资产绑定；`protocol.bind` 在 create/start 再次逐项核验。

**收尾内存探针（有界工程检查）**：对 M59 已提交 run 的只读副本（8.3 GB）在
systemd 自有 cgroup 下量化收尾 `Run.open` 的真实规模内存：

| 探针 | 形态 | MemoryMax | 结果 | cgroup 峰值 |
| --- | --- | --- | --- | --- |
| A | 修复后（单实例） | 4 GiB | PASS（exit 0） | 2,820,194,304 |
| B | 修复后（单实例） | 8 GiB | PASS（exit 0） | 2,746,114,048 |
| C | 修复前（双实例并存） | 4 GiB | **内核 OOM kill（exit 137）**，journal `Result=oom-kill` | （被杀） |

结论：修复后收尾在**原 M59 4 GiB 训练上限内即可完成**（约 2.8 GiB 峰值，余量
约 1.2 GiB），并直接在受控条件下复现了 M59 的 OOM 形态，支持重复实例诊断。
仍无逐分配 profiling；探针回执在 `local-artifacts/prism/alpha-cloud-m60/probe/`。

Hello 预检 **NOT_RUN**（两此独立调用尝试均未复现 M59 的 hello 读取 harness，
原始尝试记录保留于 `hello-preflight-attempts.json`）：blueprint 对手行及其期望
hello 字段与 M59 已验证的 1,024 局运行形状逐字一致，且冻结 arena 在每局报告中
核验 hello/seat（协议缺陷即 fatal）；风险边界如实记录，不以本项冒充已测。

### 云端真实启动 — 2026-10-03T08:47:01 UTC（16:47 +08）

`control create` 成功：campaign `m60-alpha-bigcard-g0`，ownership ACTIVE，
nonce `1b1520a97bf94298a9884789127204d1`，blueprint identity
`772907c0de2054413ffd10a88f289536b9f3e8361fbfbd68b8f4c5c27d3e757a`，code
identity `a2f7633e…`（含修复）。`control start --cycles 4` 后实测：
supervisor unit `prism-ppo-supervisor-ebc1ed306b13486baea892c9a398e0ea.service`
PID 493860 active/running；**服务 MemoryMax=8,589,934,592、slice CPUQuota=200%、
RuntimeMaxUSec=7h59min44s（原 deadline 语义，非重发 8 小时）**；slice memory
events oom/oom_kill=0。启动约 108 秒内 58 个 attempt 目录，游戏正常产出。
启动观察回执 `local-artifacts/prism/alpha-cloud-m60/startup-observation.json`。
这是第一轮训练采样，不是已完成迭代或棋力增强。

### 四轮提交完成（收尾修复后首次全程 PASS）— 2026-10-03T09:34 UTC

**TRAINING_ARTIFACT_VERIFIED / supervisor STOPPED_COMMITTED。** 四轮 1,024 局、
216 次更新、27,398 次学习决策、0 retry 全部提交；最终 c4 导出与审计完成。
**这是修复后首次完整跑通含收尾的云端 PPO**：M59 在同一路径以 cgroup OOM 终止。

| 实测项 | 结果 |
| --- | --- |
| 监督区间 / 墙钟 | 08:47:01 UTC 启动；自有 tree 墙钟 2,835.466626 s ≈ 47分15秒（M59 为 2,831.08 s 含收尾异常） |
| slice 累计 CPU / 峰值 | 3,470.803261 s / memory.peak 触及 8 GiB cap（页缓存为主；`memory.events` oom=0、oom_kill=0，max 计数 1,077 为回收成功） |
| 最终状态 | STOPPED_COMMITTED，returncode 0，stop_reason null |
| run identity / 最终 commit | `c65520e7b706252d723a85cba1101285423e584cb302d888ba2c60b13e1e1445` / `5e3d44b21f570a8bad7b9351697ef293a823aacb0b5e1cb95ed2a38d232bc4c8` |
| checkpoint 核验 | phase COMMITTED、cycle 4、216 步、1,024 attempts/jobs、4 消费批、36 AdamW slots；**32 导出 policy/value 张量与 checkpoint 逐元素一致**；different_from_parent=true |
| **最终权重 SHA** | `7f6cdbc2acdff129b0ef6a3417e79d4b8f27bf59f40be53ae2892bf00b5e1544` |
| 最终 c4 Rust/Python 边界 | 68/68 PASS，atol/rtol 1e-4，max abs `0.00012456054687959295` |
| 完整产物审计 | **PASS_TRAINING_ARTIFACT_AUDIT**：1,024 局逐 completion/replay/report/sidecar hash、16 组、32 分座 Rust manifest、0 新局/更新；审计结果 SHA `372a2c3230ea9acb7eb33e5c53900fe3c5fab6c41b512a7e600f288877658a64` |

[完整16组训练对战表](prism/prism-alpha-cloud-m60-training-matches.md)：被测为未发布
c0..c3 训练快照，不是最终 c4 或任何已发布版本的战绩；训练胜率不得代替独立验收。

### 独立评测启动 — 2026-10-03T09:47 UTC

`prism_alpha_cloud_acceptance_m60.py`（commit 42c1753，绑定 c4
`7f6cdbc2…`）prepare 成功：执行合同 SHA
`4ff390a53fc4ce62e1f9baa1edce3aa90e86dfeee2bb63ed087e1c0d9409158c`，4,480 逻辑局
（开发 2 分片 384 局 + 独立 24 分片 4,096 局），0 局预检零游戏。systemd 服务
`prism-m60-evaluation-4ff390a5.service` 实测 MemoryMax=8,589,934,592、
CPUQuota=200%（2s/s）、RuntimeMaxUSec=8h、2 并行 worker、0 retry；自有 cgroup
核验通过后开始开发局。种子/门/统计家族均为 M60 冻结值（动作种子 59032001、
bootstrap RNG 59039999、三门阈值与 M59 相同）。结果与三门判定将在完成后追加，
不从开发信号提前下结论。
