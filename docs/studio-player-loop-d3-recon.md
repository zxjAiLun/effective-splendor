# D3 Stats-query Recon

- **Status**: **RECON COMPLETE / 查询原型 VERIFIED**；API/index 建议 **PROPOSED，待 owner 决定**。不是 D3 实现或产品验收。
- **Baseline / date**: `857250c9252cbfc3f2c7820f0261a25ba0bfc9d9`，2026-09-19；入场 main == origin/main，worktree clean。
- **Authorization**: 仅 Q1–Q8 Recon；D3 implementation / F Review **NOT AUTHORIZED**。
- **Parent**: [Studio Player Loop v1](studio-player-loop-v1.md)。Human C/E `081c5dc`、D1 `3049642`、D2 `857250c` 均已由 owner ACCEPTED / CLOSED。

## Problem and evidence

D3 要从 ledger 提供个人统计，不能从列名猜统计定义、把 unknown 当 0，或把多组件的 participant filter fan-out 当作免费读取。
本轮先证实覆盖和 writer，再比较完整查询组合，而非先造 Profile 页面。

**最重要的发现：stats 表存在，但当前没有 writer，真实数据覆盖是 0%。**
此前“已有 derived ledger 可能能回答 VP/行动比例”是需要核实的假设，不是已经实现的事实。
本轮没有因此扫描 archive、补历史数据或编造 action 分母。

## Initial design

原计划：authority/coverage → builder/时间语义 → summary/seat/H2H/ratings/games 完整查询 → 副本 index 对照 → bounded DTO 建议。
数据快照由真实库 `mode=ro` + `PRAGMA query_only=ON` + read transaction + SQLite backup 得到；index 只在副本创建。

## Scope and non-goals

不改生产 schema/index、Reader public API、Host routes、React、Replay parser、Human completion、Elo、历史 Human 归属；不启动对局、不扫 replay archive、不动 owner 进程。
D2 malformed-200 P2 保持 deferred；vinext Link debt 留到最终人工验收前实际点击确认。
tracked 变更只有 Recon/设计记录；探针、DB 副本、完整结果在 ignored `local-artifacts/studio-league/player-loop/d3-recon/`。

## Contracts and invariants

- Recorded = participant 出现过的 **distinct match_id**；seat counts = seat appearances，不混用分母。
- Rated 与 rated W/T/L 来自 `rating_events`；与现有 leaderboard 全 100 个 participant 的五项计数逐一比对相等。
- H2H 按 distinct `(match_id, opponent_id)`；不把 self-match 当对手，不猜未归属 seat 的身份。
- Elo x-axis = **League sequence**；历史 canonical sequence 不是 calendar order。
- Games/ratings/H2H 多行返回均有硬上限；summary 不嵌入所有 games/events/gameplay rows。
- 保留历史 D1 首次 cold You HTTP **2.71s** 和旧 correlated shape 约 574ms 的证据，但本轮比较使用 repaired D1 SQL，不能把旧数当当前中位数。

## Implementation plan

1. 查真实 DDL、所有 tracked writer 引用、现有 builders 和 replay/report/occurrence 格式。
2. 选 all / You / busy / typical / event-heavy，核实计数与缺失范围。
3. 冻结完整 SQL 原型，测当前 schema、指定两列 index、追加 covering 对照；保留迭代与反例。
4. 输出下列五节；仅 owner 批准后才进入 D3 实现。

## 1. Authority map — Q2 / Q3

| UI fact | 当前 authority / 代码锚点 | 结论 |
|---|---|---|
| identity / kind / name | `participants`；Reader 每次读前复核 identity manifest 与 rating config（`reader.rs:19–52,165–205`） | 不从 URL/模型名猜身份；原型 raw SQL 不是公共读入口 |
| current Elo / provisional | `participants.current_elo` + 已验证 `studio_rating_config`；`ledger.rs:775–842` | rated=0 时才可用协议 initial=1500，明确标注 initial；threshold=20；不得在 UI 自算 Elo 更新 |
| recorded / seat counts | `match_seats`，PK `(match_id,seat)` | recorded 去重；seat0/seat1/other 加总到 appearances，可能大于 recorded |
| rated W/T/L / history | `rating_events`；`elo.rs:36–46` 胜负映射为 1/0.5/0；唯一 `(match_id,participant_id)` | 只计算 rated record；28,014 events = 14,007 eligible games ×2，本快照无 event/eligible 不一致 |
| per-match final score / rank | arena `GameResult` 或 Human verified replay result → `StudioMatchSeatV1` → `match_seats` | 最终 score 可读；不能由一个总 score 反推出各来源 VP |
| VP composition / purchase tiers / nobles / actions | `schema.rs:98–115` 只有 stats DDL；所有 tracked 可执行源码中 `match_gameplay_stats`、`tier1_vp`、`metric_integrity` 均仅此处出现 | **没有 builder、没有有效数据**；不能冻结算法或分母 |
| detail availability | `ledger.rs:475–506` ingest 直接写 `false as i64` | 当前无变成 true 的生产路径 |
| main turns | `historical_import.rs:659–680`、`human_occurrence.rs:446–466` 两条 record builder 都写 `None` | fixture 的 `Some(32)` 不是数据覆盖；当前不给平均回合数 |
| completed plies | arena outcome 的 `completed_plies`（`report.rs:93–129`）；Human 为 `replay.steps.len()`；历史 verified candidate 核对 steps | 可给 **completed games 的决策步数均值**；不是 main turns，也不是 wall-clock duration；aborted/truncated 的截断步数不进入终局均值 |
| calendar / elapsed time | `matches.played_at` 仅 2 场非空；runtime/Human occurrence 只有 `completed_at`；`ReplayStepV1` 无时间字段（`format.rs:157–183`）；`ArenaReportV1` 也没有 start/end/duration | completion timestamp 不是 duration；ingested_at/created_at、文件 mtime、session id 都不是开始时间。**v1 删除 duration，不估算** |

代码路径均相对 `crates/splendor-studio-league/src/`，replay/arena 文件分别在相应 crate 的 `src/`。
原有 [Studio League invariant 17/18](studio-league-v1.md#contracts-and-invariants) 是目标合同，不是 writer 已存在的证据；该文早期 limitation 也曾明确 no writer。

**Q2 逐项裁定：** tier1/2/3 VP、noble VP、tier purchases、nobles、take/buy/reserve 均无当前生成实现。
DDL 仅限制 `metric_integrity IN ('ok','failed')`，**没有 SQL CHECK 保证 VP 总和等于 final prestige**，也没有执行此 cross-check 的 builder。
因此“失败何时产生”“flag 何时 true”“是否统计 buy_reserved / pass / follow-up”“action-count 与 main_turn_count 的关系”全部不能从现有实现证明。
`take_tokens + buy_cards + reserve_cards == main_turn_count` **不成立为已知合同**；不在 D3 v1 提供行动比例。
未来若单独授权 builder，必须先定义 per-seat 事件归类、完整分母、per-match coverage 与 integrity 失败策略；本轮不替未来实现发明答案。

## 2. Coverage table — Q1 / Q8

### Snapshot and cohorts

真实 DB：`local-artifacts/studio-league/league.sqlite3`，99,237,888 bytes，schema=3。
Recon 前后 SHA256 均为 `3941c3059e4b3eea485158963d2619d262d7a83842a55e1921809b9fdf57baee`，size/mtime 不变。
只读 backup 的物理 SHA 为 `c55323a1a1932f3602057a8f79edfb3fc336499b2052c8c2cf40774552fd1e31`；backup 物理字节不同，不冒充源文件 hash。

| Cohort | participant_id / selection |
|---|---|
| You | `b901a2ea-645d-4c45-b4b9-407f5b6f39b7`（league_meta.local_human_participant_id） |
| Busy | `eng-bbc4b64c4bc73d54525e0ba138ff5f6a`（seat appearances 最大） |
| Typical | `eng-f92e3f58fe34c2f645f2e84cef96075b`（99 个有记录 engine，按 distinct games/id 排序取中位第 50 个，252 场；不是手选快样本） |
| Event-heavy | `eng-541b017cd03b505aaedd02d55264931b`（rating events 最大，3,043） |

| Cohort | Total matches | Completed / verified | detail=1 / stats distinct matches | integrity ok / failed rows | main_turn_count nonnull / NULL | plies nonnull / NULL | played_at nonnull | Rated |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| All | 42,523 | 42,305 / 42,305 | 0 / 0 | 0 / 0 | 0 / 42,523 | 42,523 / 0 | 2 | 14,007 |
| You | 1 | 1 / 1 | 0 / 0 | 0 / 0 | 0 / 1 | 1 / 0 | 1 | 1 |
| Busy | 18,496 | 18,496 / 18,496 | 0 / 0 | 0 / 0 | 0 / 18,496 | 18,496 / 0 | 0 | 576 |
| Typical | 252 | 250 / 250 | 0 / 0 | 0 / 0 | 0 / 252 | 252 / 0 | 0 | 250 |
| Event-heavy | 3,044 | 3,043 / 3,043 | 0 / 0 | 0 / 0 | 0 / 3,044 | 3,044 / 0 | 1 | 3,043 |

全库 100 participants，85,046 seats，628 seats 未归属；26,521 个 `(participant,match)` 占多个座位。
来源：42,522 arena_report + 1 human_play；216 aborted、2 truncated 均 replay unavailable；42,305 completed 均 ledger verification=verified。
**历史与当前 Human 都无 gameplay/main-turn 覆盖，不是只有历史缺失。** verified 是 ledger 记录，不代表本轮重新打开 archive 验证。

| Cohort | recorded | seat0 / seat1 / other | multi-seat games | H2H distinct opponents | completed ply samples / mean |
|---|---:|---:|---:|---:|---:|
| You | 1 | 1 / 0 / 0 | 0 | 1 | 1 / 50.000 |
| Busy | 18,496 | 18,208 / 18,208 / 0 | 17,920 | 9 | 18,496 / 61.685 |
| Typical | 252 | 127 / 125 / 0 | 0 | 10 | 250 / 62.488 |
| Event-heavy | 3,044 | 1,520 / 1,524 / 0 | 0 | 24 | 3,043 / 62.681 |

当前全体 H2H 最多 **24** 个对手（100 人合计 630 个 directed pairs）。busy 的大多数 recorded 是 self-match，不能将 36,416 seats 说成 36,416 场，也不能把这些 self-match 计入对手胜率。

### Zero vs unavailable

| UI fact | Authority / coverage | 0 是否有效 | missing / partial 如何展示 |
|---|---|---|---|
| recorded / seat appearances | ledger 全部 recorded；自身 seat 集合 | 有效：已知 participant 可尚无比赛 | 未知 id →404，不渲染成零场真实人物 |
| rated games / W-T-L | rating_events，全库对账一致 | 有效：有记录但未 rated 时全部为 0 | 显示 “No rated games”，胜率分母=0 时显示 `—`，不显示 0% |
| current Elo | validated config + participant cache + rated count | 不把 NULL 当数值 0 | rated=0：1500 / initial；rated>0 而 Elo NULL/非有限或 authority 不一致：refuse，不回退 1500 |
| Elo history | events；You=1，最多=3043 | 空数组代表没有 rated events | 不补画虚构的历史事件；played_at NULL 不转 epoch/今日；横轴 League sequence |
| H2H record | distinct opponent pairs + events | 对手曾对战但 unrated 时 rated W/T/L=0 有效 | unknown opponent 单列 coverage count；不造对手名字，不计 self；多玩家情况下各对手 recorded 可重叠，不要求总和=profile recorded |
| completed plies average | completed games 中非 NULL 样本 / completed games 总数 | 非空样本真实均值 0 合法 | 样本=0 → value=null/unavailable；样本不足 → partial + `n / completed`；aborted/truncated 不进平均；标 “decision plies”，非时长 |
| main turns / 平均终局回合 | 全库 NULL | 只有未来有权威样本的真实 0 才有效 | 当前 `— / not recorded`；不从 plies ÷ player_count 换算 |
| gameplay VP/actions | 0 rows；无 builder | 0 个可用样本不等于 VP=0、行动比例=0% | 当前 unavailable / no_authoritative_builder，v1 不返回这些数值。未来 partial 必须标有效样本/应有样本，不能声称全历史平均 |
| metric_integrity failed | 本库 0，合成 fixture=1 | “0 failed rows” 有效，但不证明有 valid data | failed rows 必须单列；不得混入有效 VP/action 聚合；detail flag 不能单独认证 row integrity |
| duration | 无 authority | 不适用 | 从 v1 DTO 删除，绝不取 mtime、ingested_at 或 plies 估算 |

## 3. Query plans and wall times — Q4 / Q5 / Q6

### Frozen prototype set and method

完整 SQL/参数作为**设计附件**：[studio-player-loop-d3-queries.json](studio-player-loop-d3-queries.json)。不是路由实现，也不被生产代码加载。
最终测量集 v2：

1. `profile`：materialized 自身 seat 集合 → distinct matches；一次读取 identity/recorded/rated/seat/small coverage aggregates。零数组、单行。
2. `h2h`：同一 participant 的对手 `(match_id,opponent_id)` 去重，recorded 与 rated 分开；`opponent_id ASC`，exclusive `after`，20+1 lookahead。
3. `ratings_cursor`：`participant_id=? AND league_seq<? ORDER BY league_seq DESC LIMIT 101`；含 match played_at/opponent name 两个可选元数据 join。
4. `games`：**从 `ledger.rs` 抽取真实 `GAMES_PAGE_FILTERED_SQL`**，limit=50+1，随后与生产一致的 batched seats `IN (...)` 查询。不是旧 correlated EXISTS 或仅测 header。

附加策略对照：recent200、server downsample≤200（row_number/count window 扫全 participant history，保留首尾）；不计入上述完整工作负载。
两项对照返回核心 7 个 history 字段，cursor 额外含 metadata join；不把二者耗时差全部归因于分页。

Python sqlite **3.45.3** / Windows，journal=delete、page_size=4096、cache_size=-2000、temp_store=0，未 ANALYZE、未更改缓存预算。
每 cohort × schema × query 7 次；schema 顺序轮换，`fetchall` 与 Python row materialization 计时；完整组合另用同一 connection 顺序执行并实测总时间（不是相加各 query 的中位数）。
**F=新 connection 的首次读（SQLite page cache cold），W=同 connection 立即重复。OS cache 未清；不是严格系统 cold，不是 Host HTTP/Reader revalidation/React 时延。**

### Complete workload: median milliseconds F / W

| Cohort | Current schema | Requested `(participant_id,match_id)` | Covering `(participant_id,match_id,seat)` |
|---|---:|---:|---:|
| You | **101.535 / 98.099** | **1.149 / 0.239** | **1.205 / 0.223** |
| Busy | **991.974 / 890.648** | **750.632 / 802.888** | **637.695 / 630.623** |
| Typical | 141.953 / 143.776 | 23.398 / 23.221 | 20.312 / 19.286 |
| Event-heavy | 233.175 / 240.479 | 137.185 / 130.349 | 111.972 / 108.346 |
| Nonexistent control | 60.275 / 58.357 | 0.818 / 0.099 | 0.707 / 0.115 |

You F min–max：current 94.345–117.890ms、两列 0.994–1.698ms、covering 1.054–1.801ms。
Busy F min–max：796.909–1052.880 / 672.306–903.099 / 525.022–700.306ms。
不存在 id 的组合故意仍跑完四查询作性能控制；真实 route 应在 identity lookup 后立刻 404，不发后续请求。

### Per-query: median milliseconds F / W

| Cohort / query | Current | Two-column | Covering |
|---|---:|---:|---:|
| You profile | 33.694 / 31.656 | 0.770 / 0.087 | 0.676 / 0.090 |
| You H2H | 33.172 / 32.571 | 0.469 / 0.051 | 0.418 / 0.053 |
| You ratings cursor | 0.353 / 0.039 | 0.264 / 0.031 | 0.272 / 0.033 |
| You games + seats | 33.725 / 32.098 | 0.320 / 0.067 | 0.320 / 0.077 |
| Busy profile | 460.934 / 471.137 | 343.666 / 381.868 | 232.098 / 229.131 |
| Busy H2H | 254.592 / 242.864 | 201.047 / 205.203 | 195.770 / 201.648 |
| Busy ratings cursor | 3.295 / 0.673 | 2.801 / 0.656 | 2.678 / 0.564 |
| Busy games + seats | 226.884 / 212.952 | 153.214 / 160.028 | 165.487 / 164.831 |

**EXPLAIN 关键变化：**

| Query | Current | Two-column / covering |
|---|---|---|
| profile own seats | `MATERIALIZE mine → SCAN match_seats` | `SEARCH ... participant_id=?`；两列回表取 seat，三列是 `COVERING INDEX` |
| profile matches | match_id PK searches + materialized 小集合聚合 | 不变；busy 仍需访问 18,496 个 matches；index 不是常数时间 summary |
| H2H | 一次 own-seat scan；other seat 用 match_id PK；distinct/group/order temp B-tree | own-seat 改 covering search；other PK 和去重仍在 |
| ratings | `rating_events_participant (participant_id=? AND league_seq<?)` + match/participant PK joins | 不变；无需新增 rating index |
| D1 filtered games | `LIST SUBQUERY → SCAN s`，按 match_id 找 headers，temp order by | 子查询改 covering search；busy 仍有候选集合与排序成本，不假称 index 消除了 sort |
| D1 batched seats | match_seats `(match_id,seat)` PK，至多 51 个 match ids | 不变 |

### Elo strategy comparison

| Core strategy | You events=1 F/W | Max-history events=3043 F/W（current schema） | Decision |
|---|---:|---:|---|
| cursor 100+1，含 metadata | 0.353 / 0.039ms | 2.136 / 0.494ms | **建议 v1**；可先展示最近100，再显式加载早期 |
| fixed recent200，core fields | 0.286 / 0.032ms | 1.307 / 0.483ms | bounded 但不能浏览更早；可作为 UI 默认窗口，不需要第二种 endpoint |
| server downsample≤200，core fields | 0.433 / 0.049ms | 13.274 / 12.884ms | **不推荐 v1**：扫完整 history、丢事件；当前无需引入抽样语义 |

按 cursor 逐页读完 You/Busy/Typical/Event-heavy/不存在 id，与完整事件 sequence 对比无丢失/重复；H2H 20+1 cursor 同样完整覆盖（包含24对手的跨页样本）。
UI 可以将本页 DESC 数据反转成 ASC 画线，但不得重算 Elo、按日期重新排序，或用抽样点声称完整轨迹。

## 4. Schema / index recommendation — Q6

**PROPOSED：若 owner 批准 D3，优先一个 covering `(participant_id,match_id,seat)`，不同时建两列和三列索引。**
指定的两列 candidate 已在**完整 v2 查询集**比较；结论不是只靠 rare-human 最快 probe。

- 两列副本增大 **9,637,888 bytes**；三列 **9,670,656 bytes**（约9.22MiB），仅多 **32,768 bytes**。
- rare You 两者都将重复全表扫描降到约1ms 的组合首读；busy 的主要额外收益在 profile：两列343.666ms → covering232.098ms（F 中位数）。
- covering 不保证每个查询更快：busy games 本轮165.487ms反而高于两列153.214ms；整体组合有收益，噪声/范围一并保留。
- 当前 schema 的 SQL shape 先优化后，You whole 已从原型 v0 825ms → v2 102ms；**不能用坏查询放大 index 必要性**。但 index 对 rare/typical/read amplification 的收益仍明确。
- busy full workload 即使 covering 仍约0.63s，不能称 tail latency 已解决；分离/按需 H2H 与 history，避免 dashboard fan-out。
- 本轮 **生产 DDL/meta/hash 完全未变**。现有 schema.rs 约定 DDL shape 改变要审视 schema version，stale schema 会被拒绝；若授权，需先冻结兼容/升级策略，不能把本建议变成临时生产 `CREATE INDEX`，也不能自行重跑历史 rebuild。
- 不建议为尚无 writer 的 gameplay table 增加索引；不新建 materialized profile cache；rating_events 现有 index 足够。

后续实现验收必须在实际 bundled rusqlite/Reader/Host 上重新跑真实 SQL 的 EXPLAIN/HTTP 与 serial-Host 响应预算；本轮 Python measurements 只支持方案选择，不替代该 gate。owner 尚未指定/接受 latency SLO，本轮不发明 PASS 阈值。

## 5. Proposed typed DTO / route contracts — Q7 / Q8

以下均为 **DESIGNED / PROPOSED，未添加 Rust 类型、HTTP route 或 React 页面**。

```text
GET /league/participants/:id
  one ProfileV1；无 games/events/H2H arrays
GET /league/games?participant_id=:id&limit=...&before=...
  原 D1，不另造 recent-games authority；default50/max100
GET /league/participants/:id/ratings?limit=...&before=...
  HistoryPageV1；default100/max200，league_seq DESC，exclusive < before
GET /league/participants/:id/opponents?limit=...&after=...
  OpponentPageV1；default20/max50，opponent_id ASC，exclusive > after
```

H2H 虽然现在最多24，仍单独 bounded：participant 数量没有永恒上限，busy H2H 本身约200ms；不让 summary 为一个未打开的表先付代价。
本轮 profile query 包含 raw coverage diagnostics，未来实现可映射成如下**标量** DTO，但不能把 raw integrity_ok row count 直接认证为有效统计样本：

```typescript
// Design notation only, not a shipped TS/Rust public API.
type PlyAggregateV1 = {
  availability: "available" | "partial" | "unavailable";
  value: number | null;
  observed_completed_games: number;
  total_completed_games: number;
  unit: "decision_plies";
};
type ProfileV1 = {
  participant_id: string; kind: "human" | "engine"; display_name: string;
  elo: { value: number; display_rounded: number; origin: "rated" | "initial" };
  provisional: boolean;
  recorded_games: number; rated_games: number;
  rated_wins: number; rated_ties: number; rated_losses: number;
  seats: { appearances: number; seat0: number; seat1: number; other: number };
  multi_seat_games: number; unknown_opponent_games: number;
  completed_plies: PlyAggregateV1;
  main_turns: { availability: "unavailable"; reason: "not_recorded" };
  gameplay: {
    availability: "unavailable"; reason: "no_authoritative_builder";
    detail_flagged_games: number;
    integrity_ok_seat_rows: number; integrity_failed_seat_rows: number;
  };
  // v1 不提供 duration / VP composition / action percentages。
};
type RatingPointV1 = {
  participant_id: string; league_seq: number; match_id: string;
  elo_before: number; elo_after: number; delta: number;
  opponent_id: string; opponent_name: string; played_at: number | null;
};
type HistoryPageV1 = {
  participant_id: string; points: RatingPointV1[]; // <= requested limit
  next_before_league_seq: number | null;
};
type OpponentRowV1 = {
  opponent_id: string; display_name: string;
  recorded_games: number; rated_games: number;
  rated_wins: number; rated_ties: number; rated_losses: number;
};
type OpponentPageV1 = {
  participant_id: string; opponents: OpponentRowV1[]; // <= requested limit
  next_after_opponent_id: string | null;
};
```

Envelope 建议沿现有规范分别 `format=effective-splendor-studio-league-participant / -participant-ratings / -participant-opponents`、`version=1`；payload 分别 `profile` / page fields，由 owner 冻结命名。
不存在 participant →404；存在但零 recorded/rated →合法零计数/空 history；显式非法 limit/before/after →400，不 clamp；合法请求被 Reader authority 拒绝 →503，不伪装404/空数据。
`after` 是合法、非空、bounded participant-id 字符串，比较 cursor 无需当前存在；未来实现冻结 parser 与长度规则。limit+1 决定 exact next，next 来自最后一个已返回 row；不使用 OFFSET。

Profile 聚合与 header facts 应在一次 read snapshot；跨端点不得承诺同一时刻的全局快照。
读取仍经 `StudioLeagueReaderV1` 的 authority revalidation，不能公开 raw Connection 读函数。
每个 endpoint 必须有自己的严格 envelope/row shape decoder，错误保留旧页面/游标并可重试；这不授权顺手修 D2 deferred decoder。
首次界面只请求一个 Profile，个人 games 只用一次 D1 请求；其他 tab 按需/顺序读取，不并行派发多个 participant-filter widgets。

## Iteration log

1. **v0**：六条 summary/seat/coverage/H2H/history/games 原型全部测量；You whole F=825.322ms。
   EXPLAIN 显示 coverage CTE 被展开，多次扫座位表；H2H 提前 DISTINCT 使过滤走完整 match_id PK。此结果保留，但不是最终 index 建议基线。
2. **v1**：把 profile 小聚合合并成一次 materialized own-seat 集合；追加 covering candidate，避免为每个 seat 回表。
   You whole F=432.186ms，H2H 提前 DISTINCT 仍使 no-index path 慢。全100 profiles/H2H 与 v0 比较一致。
3. **v2（最终）**：H2H own-seat 集合不提前 DISTINCT，留到 `(match,opponent)` 去重；materialized matches 仅保留必要列。
   Current You whole F=101.535ms；完整三 schema/五 cohort 对照见上。旧 v0/v1 没有删除、没有重标成最终数据。
4. **Null fixture**：内存库增加真实0步/NULL步/aborted99步/failed stats/unrated H2H/无历史/不存在 id 控制；8 项语义断言 PASS。
   `main_turn_samples` 在原型是所有 recorded 的 raw nonnull coverage，不用它冒充 completed-only average 的分母；main-turn 数值 API 当前明确不提供。

## Final implementation

**无生产实现。** 交付是本记录、tracked SQL 设计附件、local 只读结果/副本/探针。
Q1=覆盖实测；Q2=无 builder 的否定证据；Q3=无 duration authority；Q4=summary/H2H/seat 原型；Q5=有界 sequence history；Q6=完整 workload index 对照；Q7=bounded contracts；Q8=zero/unknown 明细与 fixtures。

## Validation and evidence

以下命令均从 repo root 实际执行，**exit 0**：

```text
python local-artifacts/studio-league/player-loop/d3-recon/probe.py
python local-artifacts/studio-league/player-loop/d3-recon/probe-v1.py
python local-artifacts/studio-league/player-loop/d3-recon/probe-v2.py
python local-artifacts/studio-league/player-loop/d3-recon/probe-fixtures.py
```

结果：
- 100 participant 的 recorded/rated/W/T/L 与真实 leaderboard SQL 一致；最终100 profiles/H2H 与初始正确口径一致。
- eligible/event 配对、participant+sequence 唯一性无异常；五 cohorts history/H2H 分页与全集一致。
- 最终每个 cohort ×7 repetitions，4 workload queries +2 alternatives 在三种 schema 下返回完全相同的 rows（35组对照）。
- 8项合成语义断言 PASS；这是 SQL Recon 证据，**不是公共 API 测试**。
- 真库 SHA 在三个执行阶段核对不变；未更改生产 schema version。
- 未运行 Rust/UI suites：没有任何 Rust/React/Host 实现变更，不借用旧 suite 数量宣称本轮验证。
- 收口核对：文档本地链接/anchor存在；8项本地工件SHA与记录一致；tracked SQL设计JSON与最终测量SQL结构相等（LF/CRLF物理hash分别记录）；`git diff --check` exit0；`git check-ignore -v handoff.md` 确认 `.gitignore:12:/handoff.md`，本地实验目录亦被ignore。

本地证据根：`local-artifacts/studio-league/player-loop/d3-recon/`；完整 samples/plans/rows 不发布成产品数据。

| Artifact | SHA256 |
|---|---|
| `identity.json` | `dd4536662a07ea4284719215dea348bcbb408068fcb2eb69f3182bda7b8446c5` |
| `coverage.json` | `a007bb642e119d0948629d7d530eb14bd06e887458b3fa2a1a4ac93a65364bee` |
| `v2-queries.json`（本地CRLF工件） | `5799d5a1942c4dc0a69e79d902db25ec6a683de85c8e687dd4a288afd75b5264` |
| tracked SQL design JSON（Git/LF bytes，JSON内容相等） | `6f95c1f39a1e18db51485f90c34e6434b651fed7d1426b31598c9cf55ff1313e` |
| `v2-benchmark.json` | `31e16722757830426487898a9ac8bc4bcf2f845676963de1b994170d0700b4c5` |
| `v2-plans.json` | `6344aba1e52af9203fe9e40c0559e29e13b24780c756e029ea95268062e074bb` |
| `v2-checks.json` | `de4fb7c30583bc9bead648c02c696c16de0c12f8dbd721331afc817a34626f44` |
| `fixtures.json` | `81dc0a9facb174fdb225642f003a3a2e5cfe9f6954eccbe421ee3c51930b4464` |
| `probe-v2.py` | `a289f4248af21f1c81375cd3ac9d65b80f3fb4b2808463a3a547e6b98d88d9f2` |

## Result and decision

**Recon 完成；不是 D3 ACCEPTED。** 建议 v1 仅提供已知 ledger facts、completed decision plies 与 bounded rating/H2H/games；gameplay 与 main-turn 显式 unavailable，删除 duration。
index 建议 covering 三列；两列指定 candidate 已完整比较，后续要由 owner 批准 schema/index 生命周期和真实 Host gate。

## Known limitations

- stats table 空，因此不能推断将来有数据时的 metric join 性能或 validity coverage。
- 未清 OS 文件缓存、未测真实系统 cold、未改 Host；保留2.71s历史 tail，不以毫秒 microbenchmark 否认它。
- Python sqlite 与实际 bundled rusqlite planner 可能不同；7次样本不是 p95/p99 SLA。
- 有界输出不等于 bounded CPU：busy 的聚合/排序成本仍存在；不允许多 widget fan-out。
- current_elo cache 与 ledger events 的写入一致性仍依赖既有 ledger transaction；本轮未改变或扩展 Elo 算法。
- UI 导航真实点击仍需最后人工 gate，Page.navigate 不能替代。

## Next authorized gate

**停止在 Recon。** 请 owner 决定是否冻结以上 MVP/DTO/index 建议，并另行授权 D3 implementation；F Review、gameplay builder、历史 backfill、D2 decoder repair 均未授权。
