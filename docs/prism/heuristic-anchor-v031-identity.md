# Heuristic 锚点身份更正：M59/M60 的「portable v0.2.9」即 Heuristic v0.3.1 策略

状态：VERIFIED（源码/二进制身份链核对，0 新局）/ 更正记录
负责人/日期：Zixuan Tang / 2026-10-03
授权：用户原话「v0.2.9启发式不是一个合格的对手 把v0.3.1的数据补上 并且后续用默认v031替代029」

## 触发与结论

用户指出 v0.2.9 启发式不是合格对手、要求补 v0.3.1 数据并在后续轮次以 v0.3.1
默认替代 v0.2.9。核查后的事实是：**M59/M60 训练与评测中的锚点对手
`heuristic-portable-v029` 运行的策略就是 Heuristic v0.3.1（S4.11 五层等价重构，
policy identity `handwritten-heuristic-v031`）**；"0.2.9" 只是该 agent 的协议
Hello 版本常量（`crates/splendor-agent/src/heuristic_v02.rs` 门面注释原文：
"Development-command compatibility only, NOT a frozen binary identity"）。
因此 v0.3.1 数据**已经存在**于 M59/M60 的开发与独立验收表中，本更正将其按正确
策略身份重新归属；未跑任何新对局（0 局），不重跑、不改变任何已冻结结果。

## 证据链（每步独立可核）

1. **v0.3.1 的源码身份**：`docs/s4-heuristic-v02-design.md` S4.11「五层重构」
   （2026-09-28）记载最终源码 SHA-256 表（7 份文件，未提交身份）；同文档明确
   该重构为「等价拆分」，`HeuristicAgentPolicyV02` 行为在拆分前后等价。
2. **当前工作树 = v0.3.1 源码**：7 份文件逐一重算 SHA-256 全部一致
   （heuristic_v02.rs `316c2576…`、position `82f81507…`、projection `58bca2e5…`、
   targets `27a65502…`、economy `ee9efebb…`、competition `b96614df…`、
   tests `7961c11e…`）。
3. **M57 冻结快照 = 当前工作树**：`local-artifacts/prism/portable-m57/rust-source.json`
   的 305 文件清单在 M60 合同冻结时再次核对 0 漂移；M57/M59/M60 记录内嵌同一批
   哈希（`benchmarks/m57-prism-portable-ppo.result.json`、
   `benchmarks/m59-prism-alpha-cloud-ppo.config.json`、
   `benchmarks/m60-prism-alpha-cloud-ppo.config.json`）。
4. **cloud1 引擎 = 该快照的构建产物**：本次在新目录
   `cloud1:/home/ubuntu/splendor-ppo-m60/heuristic-v031/source`（同源码 tar 包）
   用 cargo 1.93.1 重建 `--bin splendor`，产物 SHA-256
   `1a13af46327650c20675994b3347047ecadd5068e701ad3808322ec8ac528d4b`，
   与 M57 起在 cloud1 使用的冻结引擎 `/home/ubuntu/splendor-ppo-m57/build/release/splendor`
   **逐字节相同**（确定性构建；同源码同工具链）。
5. **M59/M60 锚点行**：对手描述为 `agent-heuristic-v02 --seed 20260926`、期望
   Hello `splendor-cli-heuristic-v02 / 0.2.9`，引擎即上述 1a13af46。故其策略为
   v0.3.1；Hello 0.2.9 是协议兼容常量，与 Studio 注册表一致
   （`benchmarks/studio-1v1.registry.json` 中 v0.3.0/v0.3.1 条目的
   runtime_version 也都是 0.2.9）。
6. **跨平台等价**：评分全部为 i64 整数运算，无浮点，同源码的 Windows pilot
   二进制（`local-artifacts/s4-heuristic-v031-pilot/splendor-candidate.exe`）与
   ARM 引擎在同一 catalog 下行为确定性一致。

## 历史记录更正（追加，不改写）

- M56 检查点曾写「Portable heuristic v0.2.9 不是 Windows Heuristic v0.3.1」：
  该推断以 Hello 版本身份为准，**在策略层面不成立**——两者是同一份 v0.3.1 源码
  的不同平台构建。原记录保留，以此节更正为准。
- M59/M60 报告中的对手显示名「便携 Heuristic v0.2.9（greedy）」按当时冻结字节
  保留不改；其策略身份按本节更正为 Heuristic v0.3.1。
- M60 可读报告 SHA（`b98c4808…`）与版本身份绑定不受影响（未重生成、未改字节）。

## 更正后的锚点数据（即 v0.3.1 数据，无需补跑）

被测均为对应轮次的固定最终候选与父模型（T=1，动作种子按各轮冻结合同）；
对手本表统一正名为 **Heuristic v0.3.1（greedy，tie seed 20260926）**：

| 轮次 | 被测 | 对手（更正后） | W / D / L | 局数 | 半平得分率 |
| --- | --- | --- | ---: | ---: | ---: |
| M59 独立验收 | Prism Alpha v0.1.2 | Heuristic v0.3.1 | 357 / 4 / 151 | 512 | 70.1172% |
| M59 独立验收 | Prism Alpha v0.1.1 父模型 | Heuristic v0.3.1 | 338 / 2 / 172 | 512 | 66.2109% |
| M60 独立验收 | Prism Alpha v0.1.3 | Heuristic v0.3.1 | 371 / 1 / 140 | 512 | 72.5586% |
| M60 独立验收 | Prism Alpha v0.1.2 父模型 | Heuristic v0.3.1 | 352 / 2 / 158 | 512 | 68.9453% |

完整双方表、经济、贵族、预留、七类动作与双座分解仍在原报告
（[M60](prism-alpha-cloud-m60-evaluation.md) /
[M59](prism-alpha-cloud-m59-evaluation.md)）对应对手小节，按本节更正名称阅读。

## 强度定位（描述，非新测）

Heuristic v0.3.1 对 S3 Rollout 先/后手得分率 81.25%/71.875%（S4 记录），是
手写基线中的最强代。Prism 各代对它的成绩（62.0% → 65.82% → 70.12% → 72.56%）
是版本进步的连贯轨迹，不存在「锚点过弱导致虚高」的证据；跨代数字不可作配对
因果解释。

## 后续轮次的默认对手决定（M61+ 起生效）

- 训练/评测合同中的启发式对手行更名为 **`heuristic-v031`**（显示名
  「Heuristic v0.3.1（greedy）」），并绑定：引擎二进制 SHA、上表 7 份源码哈希、
  Hello `splendor-cli-heuristic-v02 / 0.2.9`（协议常量，注明不是策略身份）。
- 不需要新引擎：cloud1 现有冻结引擎 1a13af46 即 v0.3.1；任何新构建须逐字节
  可复现或重新冻结身份。
- 本决定的依据是身份链证据而非新对战；若后续更换启发式策略（如 v0.3.2c 两层
  推演），按既有纪律另立身份、另冻种子与合同。
- 本更正 0 新局、0 训练、0 部署变更；默认模型/共享池/Studio 均未改。
