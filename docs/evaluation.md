# 对战评测与模型交付

对战比较的是完整 Agent：权重、模型代码、动作选择方式及搜索预算共同决定参赛身份。模型使用相同规则和玩家信息边界，即可通过外部程序接口对战。

## 交付一个模型

提供推理入口、运行依赖与权重路径，并明确模型版本、动作选择方式、随机种子及计算预算。入口应在 stdin/stdout 上实现 [Agent 协议](protocol.md)。

配置使用 `program` 和 `args`，不经过 shell：

```json
{"program":"python","args":["my_agent.py","--weights","checkpoints/model.pt"]}
```

评测方可将不同参与者的程序与权重保存在自己的运行目录中。参赛者无需取得其他模型的权重、训练算法或搜索实现。

## 单局裁判

```sh
splendor run-match --config examples/match.json --report-out outputs/game.report.json --replay-out outputs/game.replay.json
```

配置字段：

| 字段 | 含义 |
|---|---|
| `game_id` | 本局标识 |
| `seed` | 裁判新局种子 |
| `handshake_timeout_ms` | 每个 Agent 的握手预算 |
| `move_timeout_ms` | 每次动作请求的时限 |
| `shutdown_grace_ms` | 进程结束宽限时间 |
| `agents` | 按座位排列的 2–4 个程序命令 |

路径相对启动裁判时的工作目录解析；程序也可由 PATH 查找。输出父目录必须存在，目标文件不能已存在。

| 结果 | 退出码 | 输出 |
|---|---|---|
| `completed` | 0 | 报告和通过校验的完整回放 |
| `aborted` | 2 | 故障报告；没有伪造回放或胜负 |
| 参数、配置或基础设施错误 | 1 | stderr 错误信息 |

报告最后发布。完整回放含裁判种子和状态信息，只在赛后使用。

```sh
splendor verify-replay --input outputs/game.replay.json
```

## 批量评测

```sh
splendor eval --plan examples/evaluation.json --out-dir outputs/evaluation
```

每个种子执行所有循环座位轮换。两名 Agent、三个种子对应六局，使双方分别先手和后手。计划支持 2–4 个不同 Agent。

输出包含 `plan.json`、`eval-report.json` 和每局报告／完整回放。读取 `records[].outcome` 区分完成与故障，读取 `agents[].by_seat` 查看座位统计。某个 Agent 故障会记入评测报告，不伪造比赛分数。

## 1v1 循环赛与 Elo

```sh
splendor rating-plan --registry examples/registry.json --config examples/rating.json --out outputs/rating-plan.json
splendor rating-run --plan outputs/rating-plan.json --out-dir outputs/rating
splendor rating-report --plan outputs/rating-plan.json --evaluation-dir outputs/rating --out outputs/recomputed-rating.json
```

registry 定义 Agent 身份和命令，rating config 定义参赛 ID、种子、时限与初始评级。`rating-report` 只复算现有记录。

`live_elo` 按固定比赛顺序更新，`official_elo` 使用批量 Bradley–Terry 拟合转换到 Elo 尺度。共享工具的示例从 1500 起算；不同参考池的绝对 Elo 不应直接比较。

若登记为 `checkpoint` 类别，现有评级格式要求提供该检查点的 `checkpoint_hash`。普通 `run-match` 与 `eval` 仅要求 Agent 命令，不要求权重转换。

## 对齐评测口径

比较双方时，固定规则、牌库、评测种子、座位轮换、动作模式和计算预算。不能把随机采样策略的结果标成 greedy，也不能混用不同搜索预算的身份。

记录自然终局、真实故障与采样截断。此处 `run-match` 和 `eval` 运行到规则终局或故障，没有配置回合上限。Rust Arena 另提供 `run_capped`；需要上限时，评测方须明确截断计分办法。训练截断不应自动变成终局奖励。

两人评测若将正常上限局计为 0.5 分，应单列上限平局、自然和棋、真实终局和故障。截断计分由调用方执行，不能把故障混入平局。

## 运行边界

Arena 不提供 OS 沙箱，也不接管模型运行依赖。仅运行受信任程序，或由评测方在独立受限环境中执行。

共享版本可以验证安装、协议和相同规则下的比赛。完整模型的棋力结论仍需专门安排的对战实验。
