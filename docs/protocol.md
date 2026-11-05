# Agent 协议 v0.5

参赛 Agent 是裁判启动的独立进程。stdin 接收服务端消息，stdout 输出客户端消息；每行一个 UTF-8 JSON，发送后立即 flush。日志写 stderr。

运行时与权重格式独立。Python、Rust 或其他语言实现相同协议，即可参加同一场比赛。

## 消息顺序

```text
裁判 → hello
Agent → hello
裁判 → game_start
裁判 → event（开局及后续玩家可见事件）
裁判 → observation
裁判 → request_action
Agent → action
裁判 → action_applied / event
……
裁判 → game_end
```

`ping` 应回复 `pong`。异常用 `error` 表示。受限采样可用 `game_truncated` 结束；它没有终局胜负。

## 服务端消息

所有消息都有 `protocol_version`、`game_id` 和 `server_seq`。除 `hello` 外，还包含 `recipient_player_id`。

| 类型 | 主要字段 |
|---|---|
| `hello` | `engine_version`、`ruleset`、`catalog_version`、`ruleset_fingerprint` |
| `game_start` | `player_count`、`seed_commitment`；可选 `run_trace_id` |
| `observation` | `observation_hash`、`observation` |
| `request_action` | `request_id`、`observation_hash`、`deadline_ms`、`legal_actions`；可选 `ply` |
| `action_applied` | `actor_player_id`、`action` |
| `event` | 一个已投影的 `VisibleEvent` |
| `game_end` | `result` |
| `game_truncated` | `completed_plies`、`cap_state_hash`、`cap_scores` |
| `error` | `message` |
| `ping` | 公共元数据 |

`observation_hash` 标识本次玩家观察；动作请求必须匹配最近观察。SDK 会检查请求关联、座位和合法动作。

完整字段与类型由 `crates/splendor-protocol/src/lib.rs` 定义。固定消息样例见 `fixtures/protocol/v0.5/`。

## 客户端消息

```json
{"type":"hello","protocol_version":"0.5","game_id":"demo","agent_name":"my-model","agent_version":"1.0.0"}
{"type":"action","protocol_version":"0.5","game_id":"demo","request_id":1,"action":{"type":"reserve_deck","tier":"One"}}
{"type":"pong","protocol_version":"0.5","game_id":"demo"}
```

示例只展示消息形状；动作必须取自该请求的 `legal_actions`。客户端消息不能添加座位、server_seq、观察哈希或自定义诊断字段。裁判严格拒绝多余字段、错误类型、错误请求编号和非法动作。

## Python SDK

```python
from splendor_env import run_agent


def choose_action(decision):
    observation = decision.observation
    history = decision.visible_history
    legal_actions = decision.legal_actions
    return legal_actions[0]


result_message = run_agent(choose_action, name="my-model", version="1.0.0")
```

`Decision` 还提供 `player_id`、`game_id`、`request_id` 和 `deadline_ms`。这些字段用于运行控制，不是游戏特征。`run_agent` 返回结束消息；回调异常、非法输出和提前 EOF 使进程失败。

模型可在 `run_agent` 前加载。评测方应给握手设置足够的模型加载时间。推理时只使用当前玩家的观察、可见历史与合法动作。

## Rust SDK

实现 `splendor_agent::AgentPolicy::choose_action`，再通过 `run_agent` 启动。`DecisionContext` 包含 Observation、玩家可见历史、合法动作、请求信息和独立 RNG。随机参考入口为 `run_random_agent`。

## 信息边界

裁判拥有 `FullState`，策略拥有 `Observation`。对手暗预留身份、牌堆顺序和原始对局种子不会作为决策输入发送。事件按接收玩家投影，不能把原始 `RefereeEvent` 送给策略。

裁判回放属于赛后材料。`game_truncated` 的截断记录也只在该次运行结束时发送。结束消息中的数据不得反向用于本局先前决策。

训练环境与 Agent 输入复用同一 Observation 和 Action 结构。无需把模型导出成指定网络或某种权重格式；只需保持可运行入口遵循本协议。
