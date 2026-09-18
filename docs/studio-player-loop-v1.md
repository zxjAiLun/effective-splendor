# Studio Player Loop v1 — League 页面与 Review 体验交付

- **Status**: IN PROGRESS；**Human Live League Integration v1 已 ACCEPTED / CLOSED（closeout `081c5dc`，owner 真人现场对局验收 PASS）**；本文件剩余范围为玩家闭环的 D/F：
  - D1 bounded League Games — **AUTHORIZED / IMPLEMENTED / VERIFIED（本地 + 真实 42,523 库）**；
  - D2 `/ratings` 产品语义切换 — NOT YET；D3 participant profile/stats — NOT YET；F Review — NOT YET。
- **Baseline**（本轮 D1 起点）：`081c5dc61f2efd94b3f931b4e73f8d4c1883ff3f`，2026-09-18 核验 main / live origin/main 相同、worktree clean。
  下方旧的 `8093dd3` / “Slice C IMPLEMENTED / VERIFIED local” 表述（C/E 未验收时期的快照）已由本条取代。
- **Owner-date**: 2026-09-18；owner 重申 9/11 七项闭环，明确继续完成玩家可用页面、接入、统计与 Review 修复；并**明确只授权下一轮做 D1**（D2/D3/F 待 D1 看过真实 diff 后再议）。
- **不是验收**：继续授权不冒充对 `7d9f603` 的独立 review，不把已有后端测试当产品整轮 ACCEPTED。

## Problem and evidence

原 [Studio League](studio-league-v1.md) 的 A–E 是自然交付顺序，后续实现切片只完成部分产品面。
核对当日代码（**D1 交付前**）：`/ratings` 仍为冻结研究报告；`app/page.tsx` 仅 fetch `/recent-games`（旧人机局）；
`reader.rs` 只有 leaderboard / match detail / replay，尚无个人统计与有界比赛列表 API（**D1 已补后者**）；
`/play` 曾未消费 `league_completion`、固定座位且 seed 转 Number（**C/E 已修**）；Review 的 My decisions
在 humanSeat=null 时返回全部 frames、seat 主要来自 URL（**F 待做**）。不能称七项需求已闭环。
历史 inventory 48,050 是候选记录而非最终唯一比赛；保留最终迁移及 42,522 库的已有裁决，不重跑迁移。

## Initial design

沿用长期 League / shared completion authority，不另建 League。顺序为：
1. Human Live C + E：Rated 提示、终局两事实、按 participant 身份展示 Studio Elo、同局 disk retry；
   随机座位/seed、实际参数可见，去掉 Earlier games 重复块。
2. D：有界 League Games + `/ratings` 排行榜 / 个人页 / 统计；研究报告迁 `/ratings/reports`，保留原数值与入口。
3. F：Review 导航/元数据座位/shared player 状态布局/结构化彩色行动/缓存切换。
不要求 F 等历史导入，不再以旧切片的“不做 UI/统计/分页/Review”永久冻结原需求。

## Scope and non-goals

| 项目 | 当前证据 / 状态 | 完成门 |
|---|---|---|
| 稳定 Participant / 双人 Elo / 历史账本 | 已有核心与迁移；不重开 | 保持既有幂等、身份、canonical-order 门 |
| Human Live 接入 | **ACCEPTED / CLOSED**（2026-09-18） | owner 现场真实对局走通 PASS；session `human-9921689750950880821-0-37548-1`，match `c20e1f3b...`，You 1500.0 → 1529.8 (+29.8) |
| Play Random/First/Second、Randomize seed | IMPLEMENTED / VERIFIED 本地 | random 一次、发实际 seat；禁止 seed 静默舍入 |
| 去重复 Earlier games | IMPLEMENTED / VERIFIED 本地 | 历史入口统一 Games |
| 长期 Games 有界查询/分页 | **D1 IMPLEMENTED / VERIFIED**：typed Reader page API + Host `GET /league/games` + cursor 语义 + UI 有界列表 + 8 项 ledger gate / 3 项 Host gate / 真实库 evidence | 不全量向浏览器搬 42k；稳定 `league_seq DESC` + `league_seq < before`；**实测**：无过滤首页 8.8 ms，`participant_id` 过滤 574 ms，**二者均快于既有 `/league/leaderboard`（1247 ms）** ⇒ 无 evidence 要求加 index，**未改 schema** |
| `/ratings` 与个人统计 | 待实施，不取消 | rated W/T/L、scope、H2H/座位/曲线/得分/行为；无数据不造数 |
| Review My decisions | 待实施，不取消 | 从 meta 获 seat；未知禁 My；按钮/键盘同一 actor 过滤 |
| 玩家状态共用且棋盘上方 | 待实施，不取消 | Play/Replay/Review 三处一致，保留隐藏信息界限 |
| 彩色行动 | 待实施，不取消 | 结构化 action、实际/推荐共用、数量/卡片/可访问标签 |
| Review 缓存与切换 | 待实施，不取消 | 完整同配置缓存不启动任务；切换保留 ply/view/filter |
| S3→M07 组件复用 | 须先验证输入/config/effective seed/result type | 不承诺零计算、不改旧 M07 语义；缺完整分数明确补算 |
| 人类历史认领 | DEFERRED 至明确认领合同 | 绝不静默 backfill，不毁首局起点 |

非目标：研究评分重算/新 Arena 棋力实验/Host 并发/自动 canonical rebuild/账户系统/删除数据/任意上传。
分页现已获本轮需求授权；旧 no-pagination 仅保留为当时切片的历史范围。

## Contracts and invariants

- 沿用 [Human Live D1–D9](human-live-league-v1.md)，浏览器创建请求仍恰好 agent_id/human_seat/seed。
- 不将 completed + booking failure 渲染为 match failed；retryable 不能证明没入账或保证最终可入账。
- seed 输入采用十进制文本，校验 unsigned u64；请求保留 JSON numeric literal（不经 Number）。
  Host snapshot 新增十进制 `seed` string 供恢复后展示；从 `FullState.seed` 读取，不从 session id 猜。
- Elo 只显示 receipt 值；经 match detail 验证 match_id/source_identity，再以 seat→participant_id join。
  详情读取失败不会把已成功的 booking 变成失败，也不猜 event 顺序或 display_name。
- UI transport 失败只报未知；不能自动重发动作/创建新对局。人工刷新 GET /state 恢复事实。
- 不跨 session 套用 retry 响应；retry 只向原 session POST 空 body，无 result/seed/identity 参数。
- 后续统计用真实 main_turn_count，VP 按 tier1+tier2+tier3+noble 与终局相等，缺数据显示缺失；
  historical canonical sequence 不是日历 chronology；多人不套双人 Elo。

## Implementation plan

本轮先实现 C/E（小片：Play runtime module + rendered panel + page wiring + Host seed 展示字段 + gates）。
之后逐片实现 D/F 并更新上表，不因 C/E 通过就宣布七项完成。每片跟踪实际测试证据和剩余项。

## Iteration log

- 2026-09-18：核验 baseline 并恢复完整交付表；原 Slice C/Review/pagination 的未授权限制被本次
  owner 指示按此顺序更新。B 的实现与验证历史保留，不虚构独立 review。
- C/E 设计：receipt 只有 participant id、不含 seat；选择复用 GET /league/matches/:id 的 typed
  detail 来 join，不扩 registry identity 不按 Elo 数组下标推断。额外读取失败只降级标签。
- **D1 决策 1（owner 定调）**：cursor pagination，**不用 OFFSET**。`league_seq` 是 pagination/order
  authority，`played_at` 只是页面显示时间；前端不得按 `played_at` 自行重排。默认 50 / 上限 100，
  非法 cursor/limit → 400。
- **D1 决策 2（owner 定调）**：D1 只解决“42k 怎么安全读”，**不加 H2H/VP/action stats**，
  列表行不是 `MatchDetailV1 × 50`。
- **D1 决策 3（owner 定调）**：Games 主列表改以 Studio League 为主数据源，但
  **不删旧数据源**；legacy `/recent-games` 保留为独立的 LOCAL / LEGACY 区块，
  不为“页面看起来统一”静默认领旧 Human 历史。
- **D1 决策 4（owner 定调）**：**先量再决定是否加 index**，不为“分页需要性能”预先开 schema/schema index。
  实测结论见下 `Validation and evidence`：无过滤路径走 `matches_league_seq` 索引，`participant_id`
  过滤是 per-candidate seat probe，**但二者都快于既有的 `/league/leaderboard`** ⇒ **本片未改 schema、未加 index**。
- **D1 实测过程中的一处自我修正**：初次冷读取到 `participant_id=<You>` 为 2.71 s，据此一度倾向“需要加 index”。
  随后在同一 Host 上做多次 warm/cold 对比：`/league/leaderboard`（既有、生产已在用）best **1246.8 ms**,
  而 D1 的过滤 best **574.1 ms**、无过滤 **8.8 ms**。即新读面比既有accepted 路由更快，
  “因分页而加 index”的 evidence 不成立。**结论按修正后的口径记录，不放大小样本里的首读数。**

## Final implementation

### D1 — Bounded League Games Read — IMPLEMENTED / VERIFIED（本地 + 真实 42,523 库）

**Reader API**（`crates/splendor-studio-league/src/ledger.rs`，SQL 仍在 league crate，不进 CLI）：

```rust
LeagueMatchPageRequestV1 { limit: Option<u32>, before_league_seq: Option<i64>, participant_id: Option<String> }
LeagueMatchPageV1       { matches: Vec<LeagueMatchListRowV1>, next_before_league_seq: Option<i64> }
GAMES_PAGE_DEFAULT_LIMIT = 50 / GAMES_PAGE_MAX_LIMIT = 100
```

- 顺序冻结 `ORDER BY league_seq DESC`，下一页 `WHERE league_seq < before`（**exclusive**）。
- `limit` 由**读面自己 clamp** 到 `1..=100`，不是由调用方保证：`?limit=10000` 实测返回 100 行。
- `before <= 0` 是调用方错误，**拒绝而非回答空页**（`league_seq` 从 1 起，回答“空”会冒充“账本读完了”）。
- 下一页 cursor 由**实际返回的末行**派生；返回不足 limit 即无 cursor，避免无限空页尾追。
- 列表行是 `LeagueMatchListRowV1`（league_seq / played_at / source_kind / status / rating_eligible + frozen reason /
  replay_document_sha256 / replay_archived / seats{seat,participant_id,display_name,score,rank,won}），
  **故意不是 `MatchDetailV1`**：列表页不搬运 50 份完整 detail，且行里**不含 rating_events**（Elo 归榜单与 match detail）。
- `StudioLeagueReaderV1::league_match_page()` 与其它 read 一样**先重验 authority evidence**（rating config + identity manifest），
  所以 league 变 stale 时分页同样 503，不会降级成一个还能翻页的旧列表。

**Host 路由**（`GET /league/games`）：

```text
GET /league/games?limit=50
GET /league/games?before=<league_seq>&limit=50
GET /league/games?participant_id=<id>&limit=50
```

- Host 是 presenter：解析 query → 冻结 request，排序/过滤/clamp 全在 ledger。**Host 里没有 SQL。**
- 新增 `LeagueRead::Invalid` ⇒ **400**（`before=0` / `before=-1` / `before=abc` / `limit=xyz` / 空 `participant_id`）。
  这与 404（league 回答了“没有该资源”）和 503（league 不能回答）分开——owner 要求的三家分类。
- **UI**：`apps/replay-studio/app/page.tsx` 现在渲染两个**明确分开**的区块：
  `STUDIO LEAGUE GAMES`（有界分页列表，滚轮向下 Load more，只用 Host 返回的 cursor）
  与 `LOCAL / LEGACY GAMES`（旧 `/recent-games`，未删、未合并）。
  纯函数与新增减 mod：`app/games-page-runtime.mjs`（不改既有的 legacy `games-runtime.mjs`，两者是两个 authority）。
- 行里的胜负/比分只来自记录的 seats；**不声称哪一席是“你”**（本地 human 的 participant id 不在行内）。
  replay 链接仅在 ledger 同时记录 content address 且 `replay_archived` 为真时给出，否则说明原因而非给 404 链接。

### C/E — ACCEPTED / CLOSED（2026-09-18，真人现场实操全绿走通）

- 2026-09-18：owner 本人通过浏览器（`http://127.0.0.1:4173/play`）现场打完首场真实 Rated 对局，
  session `human-9921689750950880821-0-37548-1`，17 – 6 击败 S3 Rollout，Booking 面板如实呈现 `Booked`、
  `You: 1500.0 → 1529.8 (+29.8)`，`Opponent: 1953.4 → 1923.6 (-29.8)`。
- 真实库通过 `mode=ro` + `PRAGMA query_only=ON` 复核：
  - `total_matches`: `42,522 → 42,523` (+1)
  - `total_rating_events`: `28,012 → 28,014` (+2)
  - `You`：seats `0 → 1`，rating_events `0 → 1`，current_elo `NULL → 1529.808`（榜单 `1530`，provisional: true）。
  - match `c20e1f3b1c649c24ca59ffa30a6053c66b749a5c72d5fd10a03964790070eceb`，replay `ed567bff...`。
  - 三处 replay 文件（legacy m20、occurrence slot、archive 根 fanout）物理字节完全一致。
  - `StudioLeagueReaderV1` 榜单、match_detail、read_replay 均能成功解析。
- [Human Live League Integration v1](human-live-league-v1.md) 里程碑正式 **ACCEPTED / CLOSED**。

冻结文案（owner 确认 D1–D9，三种终态原文）：
- booked: `Booked`（`STUDIO LEAGUE` kicker）
- retryable failure: `League booking pending` + `The match is finished and its evidence is saved. Retry re-offers that saved evidence; it never replays the match and does not guarantee insertion.`
- non-retryable: `League booking requires repair` + `<error>` 作为 body，**无 Retry 按钮**。
delta `33d21b3` 仅为此文案对齐，不改 Host shape。


- `app/human-play-runtime.mjs` 是 Play 正在消费的 request/两事实/retry/seat→participant join 实现。
  `humanStartBody` 只输出三个冻结字段；u64 使用校验后的 JSON number literal，不更改 Host 输入类型。
- `HumanBookingPanel` 消费 B 的 receipt，插入/已存在/失败/未知分别呈现；raw receipt 可展开，
  Replay 与 League 链接复用旧入口。只有 match detail 通过 ID/source 绑定且两席/事件一一对应才显示 You/Opponent Elo。
  当前 Elo 与本局历史事件明确区分，不重新算期望分、不按显示名配对。
- Play 默认 Random，开局时 resolve 一次；Randomize seed、十进制手填、实际 seat+seed 展示；删 Earlier games，
  Games 导航保留；平局显示 DRAW；开局/行动 transport 丢失后禁止盲目重发并提供 GET /state 检查。
- Human snapshot 增加顶层 string seed（含 u64::MAX）；**不**加入 observation/action_history/Agent input。
- 类型卫生：8 个既有 tsc 错误逐字复现后补 JS→TS 边界（typed filter、Timeline generic、summary nullable JSDoc、
  Review kind-local rows/Q null 展示）。没有改 Review 导航、缓存、算法；F 依然待做。

## Validation and evidence

本地执行，非 CI，artifact root `local-artifacts/studio-league/player-loop/`（ignored）。

| Command | Result |
|---|---|
| `cargo test -p splendor-cli --test league_host_api` | exit 0，**26/26**（原 23，+3 Host games gates） |
| `cargo test -p splendor-studio-league` | exit 0，**108 passed / 0 failed**（原 100，+8 `tests/games_page.rs`） |
| `cargo test -p splendor-cli`（独立 TEMP/TMP） | exit 0，**299 passed / 0 failed / 3 ignored，45 targets**（原 296） |
| `npm test`（build + Node suites） | exit 0，**93/93**（原 80，+13 `games-page-runtime`） |
| `npm run lint` | exit 0 |
| `npx tsc --noEmit` | exit 0（本轮 page.tsx 新增一处 implicit any 已补 typed row/result 形状） |
| `git diff --check` | exit 0；`rustfmt --edition 2021` 仅 touched files |
| `node tests/human-play-browser.mjs` | exit 0，真实 Chromium / built UI + **mock Host**；非实际真人/真实 Host E2E |

#### D1 真实 42,523 库实测（`local-artifacts/studio-league/league.sqlite3`，全程 `mode=ro` + `PRAGMA query_only=ON`）

owner 要求：“一直 set-based query + real DB evidence；只有 evidence 证明需要 index，再单独加。”
先量后决，证据如下（`local-artifacts/studio-league/player-loop/` 与 DB identity 见下）。

**真实 Host HTTP 多次读（同一进程，同一真实库，7 次取 best/median）**：

| request | best | median |
|---|---|---|
| `GET /league/games?limit=50`（无过滤） | **8.8 ms** | 20.7 ms |
| `GET /league/games?limit=100`（无过滤） | 14.6 ms | 25.6 ms |
| `GET /league/games?participant_id=<You>` | 574.1 ms | 594.0 ms |
| `GET /league/leaderboard`（**既有、生产在用**） | **1246.8 ms** | 1315.2 ms |

**结论：本片未改 schema、未加 index。** 理由不是“够快”，而是相对比较：

- 无过滤路径由既有 `matches_league_seq` 索引驱动（`EXPLAIN QUERY PLAN`：`SEARCH m USING INDEX matches_league_seq (league_seq<?)`），
  这也是 Games UI 实际走的路径，比既有 leaderboard 快约 **140×**；
- `participant_id` 过滤**确实**是 per-candidate seat probe（`CORRELATED SCALAR SUBQUERY` + `(match_id,seat)` PK 查找），
  代价随“该 participant 有多稀有”上升——You 只有 1 盘 ⇒ 走遍 42,523 个候选；最忙 engine 有 36,416 seats ⇒ 立刻命中、0.32 ms。
  **但它（574 ms）仍比既有 leaderboard（1247 ms）快约 2×**，所以没有 evidence 支持“为了分页先加 index”。
- 已在**副本**（real DB 全程只读，未写）上量化了一个候选 index 的实际收益：
  `match_seats(participant_id, match_id)` ⇒ per-candidate 变成 covering-index probe，You 从 440 ms → 88.7 ms（5.0×）。
  **但 88.7 ms 仍慢**，因为外层仍要一路向下走 42,523 个 candidate；即“index 修的是内层查找，不是外层遍历”。
  相应验证了另一种 `match_seats`-driven join 形状：You 快到 0.04 ms，但最忙 engine 反而 174.8 ms（需 temp B-tree 排序），
  **两种形状谁快恰好反过来，没有一个占优** ⇒ 不当场猜，留作有编号的后续供给 owner 决定。
- 因此 D1 如实记录：`participant_id` 过滤**不是便宜操作**；是否为此添加 schema/index 应随 D3（个人页）一并决策，
  而不是在 D1 为了“分页看起来需要”而预先加。

**DB identity（供后续 drift 检查用）**：
sha256 `3941c3059e4b3eea485158963d2619d262d7a83842a55e1921809b9fdf57baee`，99,237,888 bytes；
schema_version 3；42,523 matches / 85,046 match_seats / 28,014 rating_events / 100 participants。
证据文件（ignored artifact root）：`real-query-plan.txt`、`real-query-plan-index-candidate.txt`、
`real-query-plan-index-measured.txt`、`real-query-plan-join-shape.txt`、`real-http-starvation.txt`、`real-host-first-page.txt`。

#### D1 负向对照（4 组，全部击中目标 gate 并按 patched-state 字节级还原）

`local-artifacts/studio-league/player-loop/d1-negative-controls.json` + 各 `nc-*.log`：

| control | 变异 | 击中 gate |
|---|---|---|
| `nc-cursor-inclusive` | `league_seq < ?1` → `<=` | `the_cursor_partitions_the_ledger_exactly_once` |
| `nc-clamp-removed` | 去掉 `.clamp(1, GAMES_PAGE_MAX_LIMIT)` | `the_limit_is_clamped_by_the_read_surface_not_the_caller` |
| `nc-cursor-zero-accepted` | 非正 cursor 从 Err 改为接受 | `an_impossible_cursor_is_refused_rather_than_answered_empty` |
| `nc-js-offset-pagination` | `nextGamesQuery` 丢掉 cursor 只留 limit | `the next query is built from the Host cursor` |

还原后 `restore_sha256` 与工作树逐字节一致（`ledger.rs` `691236ff…`、`games-page-runtime.mjs` `b6864a92…`），
且还原后再跑：ledger gates 8 passed / 0 failed，JS 13 pass / 0 fail。

Chromium 实际点按钮：u64::MAX 精确 request → Second seat 显示 → VICTORY+booking failed →
transport unknown → 409 canonical 拒绝且无 Retry；另一次操作 → AlreadyPresent + You/Opponent 正确 Elo。
HTTP mocks 不会证明 Host 实现正确，后者由 Rust real-socket gates 单独支持；不合称真人全链验收。
脚本使用本地已有 Chromium、随机 UI port、独立 profile，退出只停止自身子进程；未下载 browser。
首个默认小 viewport 截图未覆盖 panel，改 1440px 且 scrollIntoView 后检查截图；不声明移动端布局已验收。

三组负向变异：seed 经 Number 舍入 / Elo 按 seat 下标拿 event / 所有 failure 都 retryable；
分别引发 1/1/2 个目标测试失败；每组 patched-state byte restore SHA256 相同，随后全套复绿。

重要失败与修正：
- 第一次 lint 抓一处 test 字符串冗余转义，已修。
- 第一次全量 CLI 抓两条旧 blanket `no seed anywhere` 断言；按本轮实际 seed 展示合同更新为
  顶层 decimal seed、**observation/history 继续无 seed，整个 snapshot 无 decks**。不删信息边界 gate。
- 独立 tsc 初次新增 panel row any 一处已修；baseline 八错误用 `git archive 8093dd3` 隔离源码复算，
  未修前 current 与 baseline 诊断 hash 完全相同。随后小范围类型修正，最终 tsc 0。

证据 hash：
- `validation.json`: `75a152d5d096393d57345b34e9d9bcc31ed791f654c70775742b444230ecd5e3`（Rust 全套+首批最终 UI runs）。
- `negative-controls.json`: `ae1c4f383e77eae66c7477c55a39554185c7ad4f7d1e4d8c89fa9d2f83cccd96`。
- `types-baseline.log` 与修前 `types-current.log`: `cbaa97d1a3ef6fa16705cc720cae989f90f981ab90a3fafe7b4267e0cfbd4782`。
- 最新后续类型修正验证：`types-fixed.log`、`lint-fixed.log`、`ui-fixed.log`；browser evidence `browser.json` / `play-booking.png`。
- 真实库 mode=ro/query_only 复查：42,522 matches / 28,012 events；You 0 seats / 0 events / NULL Elo。

## Result and decision

- C/E **ACCEPTED / CLOSED**（人类首局现场实战走通，Human Live League Integration v1 整体关闭 @ `081c5dc`）。
- **D1 bounded League Games：IMPLEMENTED / VERIFIED**（本地 gates + 真实 42,523 库实测），**待 owner 复核真实 diff**。
  交付符合 owner 列的 9 项：typed Reader page API、Host `GET /league/games`、cursor 语义（非 OFFSET）、
  participant filter、Games UI 改用有界 API、legacy games 不丢且明确分区、fixture 分页 gates、
  真实库 query plan + wall time、**未改 Elo / completion / Review**。
- **本片明确未做**（owner 定点）：D2 `/ratings` 切换、D3 个人统计、F Review、任何 schema/index 变更、
  任何 rating/completion 主链改动。
- **遗留一个已量化的开放议题**（不冒充已决）：`participant_id` 过滤的形状选择，见上表与“两种形状谁快反过来”。

## Known limitations

1. **`participant_id` 过滤不便宜**，且代价随 participant 稀有度上升（You 仅 1 盘 ⇒ 全表走才算一页）。
   当前未加 index；相对既有 leaderboard 仍更快，故未越线改动 schema。若将来要上个人页高频过滤，须重开此议题。
2. **未走浏览器 E2E 验证 Games UI 的真实渲染**：本片 D1 evidence 是 Rust real-socket Host gates +
   Node 单测 + 真实 Host 的 HTTP 直读；UI 在浏览器里的实际外观仍待 owner 手工走查（与 Review 如同此理）。
3. D2/D3/F 与统计仍缺交付。数据库重建必须含 live Human evidence，
   不能把仅已验证 historical importer 当全量历史+live rebuild 工具；后续验收需单独核验此链。

## Next authorized gate

owner 指示：**只授权 D1**；D2 / D3 / F 在看过 D1 真实 diff 之后由 owner 决定。
因此本轮下一道门就是：

1. **owner 复核 D1 的真实 diff**（ledger/reader/lib + Host handler + page.tsx + games-page-runtime.mjs + 两组新测试文件）；
2. owner 决定是否（a）D1 这样算收口，（b）是否把 participant_id 过滤的 index/形状改动加进 D1，还是留到 D3，（c）D2 是否随下一刀一起接 UI；
3. D1 通过后由 owner 授权 **D2**（`/ratings` → Studio League 排行榜，`/ratings/reports` 保留研究报告原样）→ D3 → F。

同时遵守 owner 约束：本轮之外不得修改 Human completion 主链，除非出现真实回归 evidence。
