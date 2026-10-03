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
