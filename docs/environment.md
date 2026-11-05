# Python 训练环境

`SplendorEnv` 启动一个 `splendor env` 子进程，所有规则操作都由同一 Rust core 完成。Python 端仅负责请求、响应和进程生命周期。

```python
from splendor_env import SplendorEnv

with SplendorEnv("target/release/splendor") as env:
    state = env.reset(seed=42, player_count=2)
    state = env.step(state["legal_actions"][0])
    player_view = env.observe(0)
```

Windows 将二进制路径改为 `target/release/splendor.exe`。使用上下文管理器或显式调用 `close()` 关闭子进程。

## 返回字段

`reset`、`step`、`observe` 返回相同结构：

| 字段 | 含义 |
|---|---|
| `type` | 固定为 `state` |
| `env_version` | 固定为字符串 `1` |
| `current_player` | 当前行动者，零起始 |
| `observation` | 本次请求的玩家视角 |
| `legal_actions` | 当前行动者的合法动作；旁观其他座位或终局时为空 |
| `visible_history` | 从开局至今，按本次观察者投影的完整事件历史 |
| `terminated` | 是否达到规则终局 |
| `result` | 终局 `GameResult`，未终局时为 null |

`reset` 和 `step` 默认返回当前行动者视角。`observe(player_id)` 读取指定座位，不推进游戏。

选贵族可能让连续两次 `step` 属于同一玩家。不要用动作序号奇偶推断行动者，也不要把一次 `step` 当作“己方和对手各走一次”。

## 奖励与截断

环境返回真实终局结果，训练程序自行定义奖励、折扣和优化算法。训练程序可按动作数或资源限制截断采样；未终局时，`terminated` 仍为 false，`result` 仍为 null。

例如两人胜负奖励可以由 `result.winners` 推导。达到采样上限时，不应伪造同样的终局奖励；是否使用 bootstrap value 由训练算法决定。

训练管理器可以调用不同座位的 `observe`，每个策略仅接收自己的视角。公开比赛的 Agent 进程只有其座位的输入，不能调用裁判的训练环境接口。

## 错误

非法动作、无效玩家编号、无效人数或未 reset 就 step，会返回错误，Python 抛出 `ValueError`。非法动作不会推进状态。环境关闭或规则进程退出时抛出运行错误。

相同二进制、种子与语义动作序列会产生相同游戏。正式实验应固定构建、规则和牌库版本；只固定种子不足以跨任意依赖升级保证相同洗牌。

## NDJSON 环境协议 v1

每行一个 UTF-8 JSON，请求与响应同步一一对应。这与参赛 Agent 的 v0.5 协议是两个入口。

```json
{"type":"reset","player_count":2,"seed":42}
{"type":"observe","player_id":0}
{"type":"step","action":{"type":"reserve_deck","tier":"One"}}
{"type":"catalog"}
```

以上各行展示独立请求形状；动作必须取自当前状态的合法集合。失败响应为 `{"type":"error","message":"..."}`，进程继续接收下一行。关闭 stdin 会结束环境。

环境不绑定深度学习框架，不提供固定特征向量。`catalog` 用于解释牌库标识；特征编码、动作打分和训练数据格式由模型作者决定。

## 吞吐与生命周期

一次 `SplendorEnv` 对应一个持久进程，可连续 reset 多局。调用为同步操作，不要让多个线程交错使用同一个实例。并行环境使用独立实例。

完整玩家历史随状态返回，便于训练有记忆的策略。高吞吐训练可直接使用 Rust crate，或基于同一规则语义开发原生批量绑定。
