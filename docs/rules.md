# 规则与数据

规则由 `splendor-core` 唯一定义。训练、推理和评测应复用该实现，避免各自重写规则。

## 基础版规则

- 支持 2–4 人；发展卡分三级，每级市场四张。
- 2/3/4 人时，每种普通宝石供应分别为 4/5/7；金色供应为 5。
- 持有宝石上限为 10，预留卡上限为 3；初始贵族数为人数加一。
- 拿不同颜色、拿同色两枚、购买、预留和退币是否合法，以 `legal_actions` 为准。
- 预留拿金后的退币与该次预留构成一个原子动作。
- 同时满足多个贵族时，使用一次 `choose_noble` 决策。
- 达到 15 VP 后完成当前轮，使每位玩家拥有相同的主动作次数。
- VP 相同时，购买发展卡较少者优先；仍相同则共享名次。
- 只有不存在其他主动作时才能 `pass`。连续一整轮强制 pass 触发僵局终局。

`GameResult.ranks` 从 0 开始，最优名次为 0；`winners` 列出所有赢家。`reason` 为 `prestige_threshold` 或 `stalemate`。

## 牌库标识

`splendor catalog` 或 `env.catalog()` 输出规则参数和全部牌库定义。

| 表示 | 含义 |
|---|---|
| `CardId` | 0–89 的发展卡整数标识 |
| `NobleId` | 基础贵族 0–9；公开局面还可携带额外贵族定义 |
| `tier` | JSON 字符串 `One`、`Two`、`Three` |
| 市场数组层号 | 0、1、2，依次对应三个 tier |
| 费用与折扣数组 | W/U/G/R/K，JSON 顺序为 White/Blue/Green/Red/Black |
| 宝石对象 | `white/blue/green/red/black/gold` 六个整数字段 |
| `slot` | 当前市场层或本人预留列表中的零起始位置 |

不要把 CardId 当作市场位置，也不要把模型动作编号当作协议动作。最稳妥的输出是原样返回一个 `legal_actions` 元素。

## 玩家观察

`Observation` 包含 `viewer`、`ruleset_fingerprint`、`public` 和 `private`。

`public` 提供当前玩家、阶段、银行、市场、牌堆余量、贵族、所有玩家的公开资源与购买记录，以及终轮状态。对手暗预留只体现为数量和公开事件，不包含牌面身份。

`private.reserved` 提供该玩家的预留卡、槽位、级别与预留来源。本人暗预留可见，其他玩家不可见。`public.extra_nobles` 是可选字段；为空时省略，存在时提供基础牌库之外的公开贵族定义。

## 动作

| `type` | 参数 |
|---|---|
| `take_tokens` | `take`、`return` 宝石对象 |
| `buy_market` | `tier`、`slot` |
| `buy_reserved` | `slot` |
| `reserve_market` | `tier`、`slot`、`return` |
| `reserve_deck` | `tier`、`return` |
| `choose_noble` | `noble` |
| `pass` | 无 |

`return` 缺省为零宝石。拿币和预留可能因不同退币组合出现多个合法动作；这些是不同选择。

## Rust 使用

```rust
use splendor_core::{FullState, GameConfig};

let (mut state, setup) = FullState::new(GameConfig::default())?;
let observation = state.observation(state.current_player);
let legal = state.legal_actions();
let step = state.apply(legal[0])?;
```

`FullState` 与原始 `RefereeEvent` 属于环境／裁判。策略输入使用 `Observation` 与 `visible_events(..., Audience::Player(...))`。Agent SDK 自动提供这些投影。

标准训练环境从基础版新局开始。额外贵族与局面快照字段属于核心数据类型；Python `reset` 不提供外部局面导入。
