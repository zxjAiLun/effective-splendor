# Replay Studio — League Play 页面 v1（第一个面向玩家的纵切面 / round trip）

**Status: IMPLEMENTED (Repair 1 + close patch) — not yet re-reviewed, not accepted.**
对 `b7a29d7` 的复审：`REPAIR_REQUIRED`（P0=0 / P1=3 / P2=1）—— 四项全部在 Repair 1 关闭。
对 `50a4f3b` 的复审：原 findings **P0=0 / P1=0 / P2=0 全部关闭**；新增一条很窄的 P1
（failure panel 自己的 label）—— 由下面「Repair 1 close patch」关闭。
修订号：Repair 1 = `50a4f3b`；它的 close patch = `cf587d2`（紧随其后的一行 anchor
提交，因为一个 commit 无法包含自己的 hash）。
基线：`ea98798`（本文件的 design-only 提交；按 owner 指示保持未 amend）。
授权：owner，2026-09-15 —— `D1 YES / D2 YES / D3 YES-with-contract / D4 MODIFY / D5 YES /
D6 YES / D7 YES / D8 YES`，本轮直接实现，未开第二轮设计。
代码修订：`b7a29d7`（实现本身，已推送到 `origin/main`）。该 anchor 由紧随其后的一行
提交补记，因为提交无法包含自己的 hash；本文档描述的是修订 `b7a29d7`，而不是承载它的那次提交。
owner 方向（2026-09-15）：**停止继续拓宽后端**，做一个玩家真的能走一遍的瘦纵切面 ——
打开 Studio → 看到联赛 → 选两个已注册 agent → 开一盘 → 在同一页看到结果 → 打开这盘的回放。
统计与 Review 修复待办**不得**被顺带塞进这一刀。

## Problem and evidence（问题与证据）

以下每一条都是在本 worktree 里**直接验证**的，不是从文档推断出来的。

**后端这一半已经存在并且已经关闭。** `crates/splendor-cli/src/human_play_command.rs`
提供 Commit D/E Slice 1 加入的联赛路由：

```text
:2260  "GET"  /league/leaderboard              (200 rows / 503 no authority evidence)
:2263  "GET"  /league/matches/{match_id}
:2267  "GET"  /league/replays/{document_sha256}   -> the raw archived ReplayV1 document
:2274  "POST" /league/matches                  -> the one write entry (Commit E)
```

**面向玩家的那一半完全不存在。** 在 `apps/replay-studio/app` 与
`apps/replay-studio/tests` 上执行 `grep -rniE 'league|leaderboard|elo'`，只命中无关的卡牌
标记（`development-card`、`EmptyDevelopmentCard`）。Studio app 现有页面为 `/`（对局历史）、
`/play`（人类对 agent）、`/replay`、`/review`、`/ratings`、`/experiments`、`/advanced`
——**没有任何联赛界面**。既有 `/ratings` 页是一份**静态的 m19/m22 报告**
（`m19-rating-report.ts`、`m22-rating-report.ts`、`rating-runtime.mjs`），不是实时联赛，
因此不能拿来当榜单。

**app 与所需流程之间隔着两道具体的接缝。**

1. *「开始一盘」没有 agent 对 agent 的 UI。* `/play` 是围绕人类座位构建的：
   `POST /games {agent_id, human_seat, seed}`（`app/play/page.tsx:130`）然后
   `POST /action`（`:131`）。唯一的 agent 对 agent 写入口是 Commit E 的
   `POST /league/matches` `{occurrence_id, game_id, seed, seats[]}` —— 而它是**计分的**：
   会落账本、产生 Elo rating event、并把回放归档进官方 `league.sqlite3`/archive。
2. *「打开回放」需要一个形状适配器。* `/replay?session=` 取
   `GET /replays/{session}`（`app/replay/page.tsx:61`）并消费
   `effective-splendor-human-replay-archive` v2（`replay/page.tsx:26-45`）：`{frames[], catalog,
   replay.result, session_id, opponent, human_seat, player_count, replay_document_hash}`。
   该文档由 `build_historical_replay_archive`（`human_play_command.rs:1258`）从
   `HUMAN_PLAY_DIR/{session}.replay.json` 构建 —— 那是**人机对局**归档。联赛按文档
   SHA-256 存放的是原始 `ReplayV1`（`GET /league/replays/{sha}`），该页面渲染不了。
   同理，首页「历史」列表只包含人机对局：`recent_games()`（`:1164-1186`）枚举
   `HUMAN_PLAY_DIR/*.replay.json`，所以联赛对局永远不会出现在那里。

**这一刀必须尊重的传输层事实。** 每个页面都各自硬编码
`const API = "http://127.0.0.1:43120";`（5 份副本：`page.tsx:7`、
`experiments/page.tsx:28`、`play/page.tsx:25`、`replay/page.tsx:18`、
`review/page.tsx:130`），而 Host 的 CORS 头只允许 `http://127.0.0.1:4173`。因此 Studio
dev server 必须跑在 4173、Host 必须跑在 43120（`--port` 是 Host 的必填参数）。Host 的
accept loop 是**串行**的：一盘在跑时，`/health` 与各读路由都会被阻塞（这是 owner 在
Commit E 已接受的既有限制）。

**测试工装事实。** `npm test` = `vinext build && node --test tests/*.test.mjs`（app 内 6 个
文件、合计 2,114 行）。本仓库**没有浏览器/DOM runner，也没有 Playwright**；现有最强的 web
测试是 `rendered-html.test.mjs`（SSR HTML 断言）加上纯模块单测（`games-runtime.mjs` 等 ——
正是 Repair 1 引入的那个模式，让「真相规则可测，而不是埋在 JSX 里」）。

## Initial design（初始设计）

一个新页面、一个**追加式只读** Host 路由、一个纯模块、一个导航链接。

1. **`app/league/page.tsx`** —— 整刀都在一页里：联赛榜单表（来自
   `GET /league/leaderboard`）、开始表单（两个 agent 选择器，数据来自 `GET /agents`，
   一个 seed，一个可见的 occurrence id）、一个开始按钮、以及留在本页的结果面板。结果面板
   **分开**展示两个事实（`match_status` 与 `completion_status`）、`match_id`、Elo 变化量，
   以及一个 **Open replay** 链接。它绝不把 completion 失败显示成 match 失败。
2. **`app/league-runtime.mjs`** —— 所有决策逻辑做成纯函数，与 `games-runtime.mjs` 同一
   精神：`newOccurrenceId(now, salt)`、`validateStart(start)`（occurrence id 必须是单个
   安全 path component；2 到 4 个可重复的 registry id；seed）、
   `startRequestBody(start)`（恰好 `{occurrence_id, game_id, seed, seats}`，多一个字段都不行）、
   `describeResult(body)`（两事实措辞；已 settled 的 aborted 对局为 `not_applicable`）、
   `describeLeaderboard(rows)`（不重算、不发明字段）、`describeFailure(status, body)`。
3. **一个追加式只读 Host 路由**（见 D3）：把联赛回放渲染成既有棋盘已经理解的 archive
   形状，对**已通过校验的**归档 `ReplayV1` 原样复用 `build_historical_replay_archive`。
4. **一个导航链接**指向 `/league`。除共享 API base 的决定（D7）外，不改动其它页面。

已驳回的替代方案：另开一条不计分的执行路径（会复制 owner 刚刚合并掉的 producer）；在新棋盘里
渲染原始 `ReplayV1`（重复回放渲染器）；复用 `POST /games`（只支持人类座位，无法表达两个 agent）。

## Scope and non-goals（范围与非目标）

**范围内：** `/league` 页面；`league-runtime.mjs` 及其单测；D3 读路由（仅在获批时）；导航链接；
API base 单一来源决定（仅在获批时）；文档与 run recipe。

**明确的非目标（冻结）：** 统计/图表；Review 修复待办；重新设计既有页面；联赛*对局列表*路由；
上传/ingest；分页；删除；鉴权；worker queue、进度流或取消；批处理/调度器；多盘锦标赛；
外部 `ReplayV1` ingest；除 D3 那一条追加式路由外，对已冻结的 Commit D/E 契约的任何改动；
手工编辑 `dist/**`；打包/部署。

## Contracts and invariants（契约与不变量）

- **页面是被关闭的权威的客户端，绝不是第二个权威。** 它不算 Elo、不读数据库、不合成
  `match_id`、不判定 eligibility。
- **两个事实始终是两个事实。** `match_status`（arena）与 `completion_status`（联赛入账）
  分开渲染；`503 completed + completion failed` 必须读作「这盘确实打了，可以安全重试」，
  绝不读作失败的对局。
- **请求不能指定 program。** body 恰好四个键；`seats` 是由 Host 解析的 registry id。
  客户端无法表达 `program`/`argv`，正如 Host 无法接受它。
- **occurrence id 是身份，不是令牌。** 它展示给玩家、只 mint 一次，重试重发完全相同的
  body；重复使用同一个 id 会返回已记录的事实，绝不跑第二盘（Commit E Slice 1，已关闭）。
- **回放链接是内容寻址的。** 它携带 booking receipt 里的 archive 文档 SHA-256；
  没有任何地方从文件名重新推导。
- **呈现层的真实性。** 榜单只渲染账本自己返回的字段（`participant_id`、`display_name`、
  `elo`、`rated_games`、`recorded_games`、`rated_wins/ties/losses`、`provisional`）；
  读不出来的行显示为不可读，而不是省略或猜测。
- **dev server origin 固定 4173、Host 固定 43120**；当 Host 不存在、不可达或回答 503
  （无权威证据）时，页面必须给出明确错误。

## Implementation plan（实现计划）

1. 冻结本设计（即本文件），并在 `handoff.md` 里把本轮标记为 `DESIGNED`。
2. `app/league-runtime.mjs` + `tests/league-runtime.test.mjs`（纯逻辑；不碰 Host、不碰浏览器）。
3. `app/league/page.tsx`（如其它 route group 需要，再加 `app/league/layout.tsx`）；导航链接。
4. Host 上的 D3 读路由，配自己的 gate（仅在获批时）。
5. `tests/rendered-html.test.mjs`：`/league` 渲染其外壳与开始表单，且页头链接指向它。
6. `npm test`、`npm run lint` 以及 Rust 套件；然后在本文件写一份 **run recipe**，让 owner
   能手工走一遍 —— 那才是本轮真正的验收。

## Acceptance gates (frozen before implementation)（验收门，实现前冻结）

- **G1 —— 请求/结果真实性（单测，`node --test`，不需要 Host）。** `startRequestBody()` 的
  输出恰好含契约那四个键；`newOccurrenceId()` 的输出永远满足 Host 的规则（非空、≤128 字节、
  不是 `.`/`..`、首尾无点、`[A-Za-z0-9._-]`）；`describeResult()` 覆盖全部四种 settled 结局
  且从不合并两个事实；`describeLeaderboard()` 不发明字段。
- **G2 —— SSR 渲染。** `/league` 渲染联赛外壳、两个 agent 选择器、seed 输入、可见的
  occurrence id，以及一条明确的「这会给一场计分联赛对局记账」提示；页头链接指向 `/league`。
- **G3 —— 与 Host gate 共享的契约 fixture。** 页面发送的请求体是一份入库 fixture；JS 测试
  断言模块逐字节产出它，而既有的 Rust 联赛 gate 断言 Host 接受同一份 fixture。一个真相来源、
  两个消费者，于是「页面发的就是 Host 收的」不可能漂移。
- **G4 —— 负向对照（每一个都必须打中自己的 gate）。** (a) 在 `describeResult` 里把两个事实
  合成一句 → G1 失败；(b) 给 `startRequestBody` 加一个额外键（例如
  `handshake_timeout_ms`）→ G1 失败；(c) 让不安全的 occurrence id 通过 `validateStart`
  → G1 失败（Host 自己的拒绝已由 Commit E Slice 1 的 gate L 覆盖）。

## Iteration log（迭代日志）

追加式。只记实质性决定与偏离。

1. **先侦察再动手。** 在树内（不是从文档）验证了：四条联赛路由确实存在于
   `human_play_command.rs:2260-2282`；在 `apps/replay-studio/app` 上
   `grep -rniE 'league|leaderboard|elo'` 只命中卡牌标记；接缝在于 `/play` 是围绕人类座位
   构建的；`/replay?session=` 消费的文档形状与联赛归档持有的**不是一个**。三条全部成立。
2. **archive adapter 的那条链本身就是安全属性，不是细节。**
   `build_historical_replay_archive` 在使用前被读过：它内部调用 `verify_replay_trace`，
   并检查 `verified.positions.len() == replay.steps.len()`，所以棋盘收到的帧是从**校验过的**
   回放重建的。于是 handler 只需把一件事做对 —— 通过 `StudioLeagueReaderV1::read_replay`
   取文档、绝不从路径取 —— 其余权威性自然成立。负向对照 D 检验的正是这一点。
3. **路由顺序是承重的。** `GET /league/replays/{sha}` 由一条裸的
   `starts_with("/league/replays/")` 前缀臂匹配。新增的 `/archive` 臂必须放在它**前面**，
   否则 `"{sha}/archive"` 会被当成 content address 读走。之所以记录，是因为它的失败形态
   （`404 no archived replay at content address …/archive`）看起来像数据问题。
4. **D6 按字面无法实现，这是 owner 必须看到的偏离。** 选择器来自 `GET /agents` ——
   registry id（`gate-heuristic`）—— 而榜单行由 participant id 标识（`eng-<hash>`，
   由引擎身份派生）。两条已关闭的读路由**不共享任何 join key**，而账本里的 `display_name`
   是 participant 标签、不是 registry id。把 Elo 挂到选择器选项上就等于按显示名猜测、
   把评分归给错误的 agent —— 这是联赛的身份纪律所禁止的。所以选择器只朴素地列出 registry
   agent，Elo 由旁边的榜单表承载，页面用一句话说明。要正确收口需要在 `GET /agents` 上**加一个
   字段**（派生的 `participant_id`）—— 那是一次刻意的后端改动，本轮未被授权。记录为限制，
   而不是偷摸塞进去。
5. **这台机器上的 `python3` 是 Microsoft Store 的占位程序**（退出码 49、不打印、不生效）。
   因此负向对照 A/B/C/E 的第一轮「通过」而什么也没证明。改用真正的 `python`
   （`C:/Python312/python`）并加上硬性的 `assert anchor in source` 守卫后重跑，四条才全部
   打中各自的目标 gate。**一个不可能失败的对照不是对照** —— 而一个补丁悄悄没生效的对照，
   比没有对照更糟，因为它会报告成功。
6. **一条想当然的断言被改正，而不是绕过去。** `/league` 的 SSR 测试起初在联赛页自身断言
   `href="/league"`，但它并不链接到自己；该断言属于首页外壳测试 —— 导航链接真正所在之处。

## Repair 1 (owner review of `b7a29d7`, 2026-09-15: P0=0 / P1=3 / P2=1)

owner 确认了这一刀的主体 —— D3 的 adapter 链、D4 的身份处理、API base 去重、共享 fixture、
不能指定 program 的选择器、复用回放渲染器 —— 并发现四处很窄的**玩家面**接缝。
没有任何一处需要重新设计。

**P1-1 —— 真实的 `503 completed + completion failed` 被降格成通用 Host 故障，于是 UI
把两个事实合并了。** 页面在 `describeResult()` 之前就先按 `response.ok` 分流，而
`describeFailure(503, …)` 回答的是「Host 无法为这个联赛作答 / 不可重试」。纯模块里两事实的
正确逻辑**连同针对它的单测**都在 —— 但浏览器路径永远到不了它。这是整刀存在的意义所在的那条
不变量，所以它是本轮最严重的发现：**对一个真实路径永不调用的 helper 做单测，不是关于真实
路径的证据。**

*修法*：把 write-response 的判定搬进纯模块，成为
`classifyBookingResponse(status, body)`。是否 settled **由 body 的形状决定**
（`match_status` 与 `completion_status` 同时存在），**绝不由状态码决定**：

```text
200 completed/inserted        -> settled, result panel
200 completed/already_present -> settled, result panel (+ one leaderboard refresh)
200 aborted/not_applicable    -> settled, result panel
503 completed/failed          -> settled, result panel + "Retry the booking (same occurrence, same seed)"
400 / 409 / 500 / 503-refusal -> refusal panel (500 and transport may retry; 400/409 may not)
```

页面只消费这一份分类，而且**只在** `inserted`/`already_present` 时刷新榜单 ——
一次失败的 booking 什么都没改变，没有可刷新的东西。

**P1-2 —— `GET /league/replays/archive` 把整个 Host 打挂了。** archive 臂同时测试
`starts_with` 与 `ends_with`，然后切片 `path[16..len-8]`；该路径同时满足两个测试，
于是字节区间反转。**修之前先复现**：把断言先写出来，对着未修版本运行：

```text
thread 'main' (29528) panicked at crates\splendor-cli\src\human_play_command.rs:2328:17:
begin <= end (16 <= 15) when slicing `/league/replays/archive`
```

panic 发生在 **`main` 线程**上。本 Host 是串行 accept loop、没有 per-request panic
隔离，所以一个畸形 GET 就终结了整个产品面 —— 客户端看到 0 字节响应，进程已经没了。
（它还留下一个持有 `target/debug/splendor.exe` 的 `splendor.exe`，使下一次 build 因
Windows 共享冲突失败：提醒我们崩溃的 Host 并不总是*安静地*崩溃。）

*修法*：用剥离去解析，绝不用下标算术 ——
`strip_prefix("/league/replays/").and_then(|rest| rest.strip_suffix("/archive"))` 配
`unwrap_or_default()`。该路径现在落到空 content address，handler 回答 404；
其它畸形形状落回裸 replay 路由。`unwrap_or_default` 是有意为之、不是疏忽：
它就是为这个输入准备的落点。

**P1-3 —— 响应丢失，最需要精确重试的那一种情形，却是唯一被禁止重试的。**
`describeFailure(null, …)` 返回 `retryable: false`，于是只剩 `New match` 一个按钮 ——
而它会 mint 新的 occurrence，最坏情况是对一个可能已经发生过的尝试再跑一盘计分对局。
一个抛出的 `fetch` 无法区分「从未到达」「仍在运行」「已完成但响应丢失」。这些情况用**同一个**
body 重发都是安全的，因为 occurrence id 从一开始就被做成了身份。
*修法*：transport 分支为 `retryable: true`，文案明确说明「本浏览器不知道结果」，
并且 Retry 重发同一个 occurrence。

**P2 —— `matchId` 的类型是 `number`。** 账本的 `IngestOutcome::match_id` 是 `String`；
一个 `as` 断言掩盖了这个谎。现在为 `string | null`。

**按指示未做**：不加 D6 字段、不做统计、不动 Review、不加浏览器 harness、不扩测试矩阵。
D6 的决定维持为已被接受（见 owner 自己的更正：在浏览器里，registry id 无法映射到
Studio League 的 participant id，除非由权威侧派生字段；所以什么都不显示是对的，
发明一个 join 是错的），并且明确**不属于**本次修复。

## Repair 1 close patch (owner review of `50a4f3b`)

owner 结论：**上一轮的三个 P1 与一个 P2 全部关闭**（P0=0 / P1=0 / P2=0），
`0a1f7b9` 确认为 docs-only，并且复审接受 `classifyBookingResponse` 现在是写路径的
**真实入口**，而不是只给测试用的 helper。只剩一处非常窄的**真实性**接缝。
本补丁只关闭它、且只做这一件事：不改 Host、不加浏览器 harness、不开设计轮。

**P1（新增）—— failure panel 自己的 label 宣称了一个页面无法知道的「不存在」。**
Repair 1 修好了 transport 的**正文**（它说结果未知、要求用同一 occurrence 重试），但所有
failure panel 共用一个硬编码的 kicker：

```text
NOT BOOKED                    <- unverified, and possibly false
The response was lost...
The match outcome is unknown...
Retry the same match
```

响应丢失时，这盘完全可能已经完成 —— Arena 跑完了、completion 已入账、响应在回来的路上丢了。
于是第一行与紧贴其下的段落自相矛盾，也架空了修 P1-3 的意义：既然结果未知，面板就不许宣告
「不存在」。正文写错是一种缺陷；**标题**写错是同一种缺陷，出现在读者最信任的那个位置。

*修法*：kicker 归入分类本身，与它所标注的段落同住 runtime 模块。

```text
describeFailure(null, …)                          -> kicker "OUTCOME UNKNOWN", retryable
describeFailure(400 / 409 / 500 / 503-refusal, …) -> kicker "NOT BOOKED"
```

页面渲染 `{failure.kicker}`。`NOT BOOKED` 在仍会印出的地方是成立的：refusal 是「不存在」的
声明，而 Host 发出的每一个 refusal 都发生在 settled fact 可能形成**之前** —— 要么根本没跑
（400 / 409 / 503），要么没 settled（500）。`500` 仍然是 retryable，却不是一个歧义结果，
这恰恰说明该 label 不能从 `retryable` 反推。

**已驳回的替代方案**：`{failure.retryable ? "OUTCOME UNKNOWN" : "NOT BOOKED"}`。
`500` 是 retryable 却明确意味着「什么都没 settled」，`409` 明确却不是 retryable，
所以「可重试性」与「不存在声明」是两个独立问题；从 `retryable` 反推只会把同一种谎话
反向再写回来。

**`New match` 有意保留**在 `OUTCOME UNKNOWN` 旁边：玩家已经被告知结果未知之后，
明知地再开一盘是他的选择。要求只有一条 —— UI 不能宣称上一次尝试没有发生。

## Final implementation（最终实现）

```text
apps/replay-studio/app/api-base.mjs                          new  — the one API base constant
apps/replay-studio/app/league-runtime.mjs                    new  — the decisions, pure and testable
apps/replay-studio/app/league/page.tsx                       new  — the page (a client of the closed authority)
apps/replay-studio/app/league/layout.tsx                     new  — route metadata
apps/replay-studio/app/{page,play,replay,review,experiments}/page.tsx   API base imported, not copied
apps/replay-studio/app/replay/page.tsx                       + `?league=<sha256>` opens a league replay
apps/replay-studio/app/page.tsx                              + League nav link
apps/replay-studio/app/play/page.tsx                         + League nav link
apps/replay-studio/tests/league-runtime.test.mjs             new  — G1 (14 tests)
apps/replay-studio/tests/fixtures/league-match-request.json  new  — G3's one shared document
apps/replay-studio/tests/rendered-html.test.mjs              + G2 (2 tests)
apps/replay-studio/package.json                              + the new test file in the test script
crates/splendor-cli/src/human_play_command.rs                + league_replay_archive + its route arm
crates/splendor-cli/tests/league_host_api.rs                 + G3-Rust and D3 gates (12 -> 14)
```

已决定并实现：

- **D1（是，计分）。** 按钮是 `Start rated match`，走 `POST /league/matches`。表单在点击**之前**
  就声明：这会写入一行账本、产生 Elo 事件、归档一份回放，并且 Elo 可能变化。没有确认弹窗。
- **D2（独立页面）。** `/league` 是新页面；`/` 仍是人机对局历史，`/ratings` 仍是静态
  m19/m22 报告。导航在 `/` 与 `/play` 上各加了一个 `League` 链接；外壳未被重构。
- **D3（是，附契约）。** `GET /league/replays/{sha256}/archive` 是一个**呈现适配器**：
  `sha256 → StudioLeagueReaderV1::read_replay() → 权威证据复验 → content address 匹配 →
  deserialize ReplayV1 → build_historical_replay_archive(…, None, None) → archive-v2 JSON`。
  任何地方都不存在 `path → fs::read → builder` 链。棋盘就是既有的 `/replay` 页面，
  以 `?league=<sha256>` 抵达；联赛回放的 `session_id` 即内容 hash，且没有对手、没有人类座位，
  因此仅对人类有意义的功能（`mine` 过滤、「Review this game」）对它隐藏，而不是猜测。
- **D4（修改）。** occurrence id 是一个身份：`studio-<epoch-ms>-<4 hex>`，只 mint 一次、
  渲染出来、可复制、**不可编辑**，Retry 原样重发。pending 请求持有精确的四字段 body；
  `New match` 会 mint 下一次尝试。没有刷新恢复。
- **D5（是）。** 只有 `idle → running → completed / aborted / completion-failed / error`。
  不轮询、不显示进度、不能取消。POST 未返回期间页面不碰联赛 —— 它在 booking 返回之后
  刷新榜单一次。
- **D6（是，附下面的 join 限制）。** 选择器来自 `GET /agents`；允许重复并给出 self-match
  提示（联赛会把它记为不合格）；不在客户端推断 eligibility，也不把评分默认为 1500。
- **D7（是）。** `app/api-base.mjs` 导出该常量；既有 5 份副本改为 import 它。
- **D8（是）。** 一份入库 fixture，由 JS 模块测试断言，并由一条 Rust Host gate 原样 POST。

## Validation and evidence（验证与证据）

**仅本地执行。** 本仓库**没有 cloud CI、没有 status checks**，所以下面没有任何一项是 CI 结果；
并且**没有浏览器 runner**，所以没有任何 gate 声称玩家点过任何按钮。

```text
apps/replay-studio            npm test                              -> 61 tests, 61 pass, 0 fail (7 files; league file = 14)
apps/replay-studio            npm run lint                          -> clean
crates/splendor-cli           cargo test -p splendor-cli            -> 287 passed, 0 failed, 3 ignored (45 targets)
crates/splendor-studio-league cargo test -p splendor-studio-league  -> 86 passed, 0 failed
crates/splendor-cli           cargo test -p splendor-cli --test league_host_api -> 14 passed (8 read + 4 write + 2 page seams)
repo root                     git diff --check                      -> clean
```

那三条 ignored 是既有的、被显式忽略的 benchmark 目标
（`m05_fixed_benchmark_meets_strength_gate` 与 M30A/M32A 探针）；没有一条属于本轮范围，
本轮也没有把任何东西标成 ignored。此前对这套测试的一次记录写的是 `2 ignored`；
这个差量就在那些既有的 ignored benchmark 里，按实测记录，不加以解释性掩饰。

**负向对照（六条，均在提交前运行，并用 `/tmp` 副本 `cp` 还原）。**

| # | 对照 | 必须失败的东西 | 结果 |
|---|------|----------------|------|
| A | 在 `describeResult` 里把两个事实合成一句 | G1「a completed match whose booking failed stays two facts」 | 3 failed, exit 1 |
| B | `startRequestBody` 展开传入对象（多出的键能到达线上） | G1 fixture / 键集合测试 | 5 failed, exit 1 |
| C | `occurrenceIdError` 返回 `null`（不安全 id 被接受） | G1 的 Host 规则镜像 + 校验测试 | 5 failed, exit 1 |
| D | archive handler 按**路径**读对象，而不是经 `read_replay` | D3 gate 的 stale-league 断言 | gate failed: `left: 200, right: 503` |
| E | `retryRequest` mint 新的 occurrence id | G1「minted once and survives a retry unchanged」 | 3 failed, exit 1 |
| F | 共享 fixture 多出一个 Host 不认识的键 | G3，双侧 | JS 3 failed；Rust gate `400` —— `unknown field timeout_ms, expected one of occurrence_id, game_id, seed, seats` |

对照 D 正是 D3 契约的正当性所在：按路径读取时，那个过期联赛返回了 **200** ——
而这恰恰是 adapter 链存在要防住的失败形态。

有两条 gate 的存在是为了避免一个假声明：

- **G3 是跨语言的。** Rust gate POST 的是 fixture 文件的**字节**（不是重新序列化的结果），
  所以只在 JS 侧新增的字段会被 `deny_unknown_fields` 拒绝，而只加进 fixture 的字段会被 JS
  侧抓住。对照 F 检验的正是这一点。
- **G2 是外壳断言，不是点击。** 它证明 `/league` 能服务端渲染出外壳、计分提示、榜单标题
  以及「Preparing an occurrence id…」（该 id 在服务端不可能存在），并且页面**不渲染**任何
  被发明的评分（`/1500/` 与 `/Unrated/` 不得出现）。点击之后的一切由纯模块的测试覆盖，
  而不是由自动化的点击覆盖。

### Repair 1 validation

```text
apps/replay-studio            npm test                             -> 65 tests, 65 pass, 0 fail (was 61; +4)
apps/replay-studio            npm run lint                         -> clean
crates/splendor-cli           cargo test -p splendor-cli           -> 287 passed, 0 failed, 3 ignored (45 targets; count unchanged)
crates/splendor-studio-league cargo test -p splendor-studio-league -> 86 passed, 0 failed
crates/splendor-cli           league_host_api                      -> 14 gates (assertions added inside the existing D3 gate)
repo root                     git diff --check                     -> clean
```

malformed-path 断言**有意**放在既有的 D3 gate 里：指示是「补一个 gate … 不用扩测试矩阵」，
而被测行为就是同一条路由契约，所以 gate 计数仍是 14。

**Repair 1 的负向对照（四条，各用 `/tmp` 副本 `cp` 还原）。**

| # | 对照 | 必须失败的东西 | 结果 |
|---|------|----------------|------|
| G | 按状态码（`2xx`）而不是按 body 判定 settled | 那条 503-is-a-result 测试 | 5 failed, exit 1 |
| H | `describeFailure(null, …)` 改回 `retryable: false` | 响应丢失相关测试 | 5 failed, exit 1 |
| J | 页面改回用 `if (!response.ok)` 判定 | 源码级结构守卫 | 3 failed, exit 1 |
| I | 还原下标切片 | malformed-path 断言（Host 死亡） | gate FAILED: `a complete response has a header terminator` |

对照 J 是一条**源码级**守卫，在测试里和这里都如此标注：本仓库没有浏览器 runner，
所以本轮没有任何东西能证明玩家点过什么。它钉住的是那条让 P1-1 从绿色单测里活下来的代码行 ——
模块的测试无论页面用不用模块都会通过。写它的过程还暴露了它自身的一个缺陷：第一版匹配到了
解释性注释里的 `response.ok` 字样，所以现在检查代码前先剥掉注释。
**一条能被注释绊倒的 gate，测的不是代码。**

### Repair 1 close-patch validation

```text
apps/replay-studio   npm test        -> 67 tests, 67 pass, 0 fail (was 65; +2)
apps/replay-studio   npm run lint    -> clean
repo root            git diff --check -> clean
changed files        apps/replay-studio/app/league-runtime.mjs
                     apps/replay-studio/app/league/page.tsx
                     apps/replay-studio/tests/league-runtime.test.mjs
```

本补丁没有触碰任何 Rust 文件，所以**没有**重跑 Rust 套件：一处只限于两个
`.mjs`/`.tsx` 文件的改动不可能改变它们的结果，重跑不会增加任何关于本补丁的证据。
上一轮的 Rust 结果（287 passed / 0 failed / 3 ignored；86/86；14/14）按当时的记录继续
作为本地执行证据成立。

**close patch 的负向对照（两条，各用 `cp` 还原）。**

| # | 对照 | 必须失败的东西 | 结果 |
|---|------|----------------|------|
| 1 | transport kicker 改回 `NOT BOOKED` | 两条 kicker 断言 | 2 failed, exit 1 |
| 2 | 页面重新硬编码该 label | 页面源码 kicker 守卫 | 1 failed, exit 1 |

对照 2 是**源码级**守卫，理由与 `response.ok` 那条相同：这里没有浏览器 runner，
所以它钉住的性质是「页面不持有任何自己的真相声明」，而它无法说明已渲染面板的任何情况。

**本补丁自己的对照暴露出的一个流程缺陷，因为属于危险那一类，故予记录。**
还原对照 1 时，`cp` 指向的是**打补丁之前**取的备份，于是「还原」把修复删掉了、而不是恢复它 ——
而接下来的那次运行报出的失败看起来像「对照仍然生效」。是测试套件抓住了它
（在执行对照 2 时，两条无关的 kicker 测试同时失败），但一般规则是：
**负向对照的还原目标必须是「已打补丁」状态，而不是本轮开始前的原始文件。否则「还原过头」
与「从未还原」不可区分 —— 而你以为已还原的树，其实悄悄缺了那个修复。**
现在备份都在打完补丁之后取，并在信任任何运行之前用 `diff -q` 验证。

## Known limitations（已知限制）

- 一盘比赛会阻塞整个 Host（串行 accept loop）—— `/health` 与各读路由在对局结束前不可用。
  因此页面必须容忍慢启动，并且不得把长时间等待当成失败。
- 这一刀没有进度上报，也没有取消。
- 页面只能看到它在本浏览器会话里启动的对局（结果面板是页面状态）；联赛*对局列表*是另一块
  未被授权的后端面。
- Host 未鉴权且仅绑定回环地址；页面不携带任何凭据。
- 页面无法在刷新后恢复一次中断的尝试（没有 `sessionStorage` 桥 —— 那座桥在产品外壳那一轮被
  有意删除了）。occurrence id 被显示出来，以便手工重发。

**本轮新增（全部已接受，无一隐藏）：**

- **选择器无法显示 Elo。** D6 的 join 没有键：registry id 对 participant id（`eng-<hash>`）。
  榜单表是权威的 Elo 视图，结果面板携带刚完成这盘的权威变化量。要收口需要在
  `GET /agents` 上加一个字段 —— 那是一次刻意的、需单独授权的后端改动，不是在页面侧猜测。
- **`/league` 没有自动化的点击覆盖。** 本仓库没有浏览器 runner。可见的结果状态
  （结果面板、Retry、两事实措辞、只刷新一次榜单）由 `league-runtime.mjs` 单测加上 owner
  的手工走查覆盖；自动声称按钮可用会是假话。
- **archive adapter 每次请求都重建**（复验 + 重构）。对单盘而言正确且便宜；它有意做成无状态的，
  不是缓存。
- **页面只显示它自己启动过的对局。** 结果面板是页面状态；联赛*对局列表*是另一块未被授权的
  后端面。

## Run recipe (the acceptance walkthrough)（运行配方：验收走查）

两个进程，都在本地。

> **修订（2026-09-15，真实走查发现本配方原本跑不起来）。** 本节原先写的是
> `cargo run -p splendor-cli -- studio-host --registry private/registry.json --port 43120`，
> 这条命令有两处错，两者都在第一次真实走查中当场暴露：
>
> 1. `private/registry.json` **不存在**（`private/` 目录本身就不存在）；
> 2. 漏了 `--bin splendor`，于是 `cargo run` 直接失败：
>    ``error: `cargo run` could not determine which binary to run. Use the `--bin` option ...
>    available binaries: m30a_probe, m32a_export_sidecar, splendor``。
>
> 原文保留在上面的引用里，不改写历史。可执行的形态以本节下面的代码块为准。
> 背景与两条被证实的缺陷（真实规模 leaderboard 延迟、Host 活性）见
> `docs/studio-league-real-scale-repair.md`。

也可以直接双击 `Start Splendor Studio.cmd`：它就是把下面两条命令各开一个可见窗口，
再打开 `http://127.0.0.1:4173/league`。窗口就是日志，关掉窗口就是停掉对应进程。

```bash
# 1) the Host, on the port the page expects, with a real registry
cargo run -p splendor-cli --bin splendor -- studio-host \
  --registry benchmarks/studio-1v1.registry.json \
  --reviewer-registry benchmarks/studio-reviewers.registry.json \
  --port 43120 --project-root .

# 2) the Studio app
cd apps/replay-studio && npm run dev -- --host 127.0.0.1 --port 4173
```

1. 打开 `http://127.0.0.1:4173/league`。
2. 确认名单与榜单能加载。**Host 的状态有四态，而不是两态**（本轮修订）：
   `checking`（正在确认，页面写 “Checking Studio Host…”）、`ready`、
   **connection-refused**（Host 没在跑）、
   **listening-but-not-responding**（Host 在监听但不回应）。后两态必须与前者可区分 ——
   第一次真实走查撞上的正是第四态，而当时的配方从未描述过它。
   任何情况下，**未确认可用时页面不得写 `ready`**，也不得留下一个没有任何解释的禁用选择器。
3. 在两个座位上各选一个 agent。确认页面写着 **Rated**、且 Elo 可能变化；并且同一个 agent
   选两次时显示 self-match 提示，而不是校验错误。
4. 读取显示的 occurrence id（可复制、不可编辑）与 seed。
5. 按 **Start rated match** 并等待 —— Host 是串行的，所以页面必须停在 `running` 且不轮询，
   长时间等待不是失败。
6. 看结果：把 `match_status` 与 `completion_status` 当作两个事实读，加上 Elo 变化量。
   completion 失败必须读作「对局已完成、入账失败、可以安全重试」。
7. 确认榜单只刷新了一次，并且两位参与者的 Elo 正好按 receipt 显示的变化量移动。
8. 按 **Open replay**，然后在回放棋盘里拖动、逐手走过这盘的各个 ply。
   **这一步是本轮无法自动化的那份验收证据。**

## Result and decision（结果与决定）

`IMPLEMENTED` —— **Repair 1 与其 close patch 已应用；尚未复审，未 `ACCEPTED`。**

对 `b7a29d7` 的复审返回 `REPAIR_REQUIRED`（P0=0 / P1=3 / P2=1）；对 `50a4f3b` 的复审关闭了
全部四项并提出一条新的窄 P1。本修订已关闭每一条，各自配有一条「撤掉修复就会失败」的 gate：

| Finding | Closed by | 没有它就会失败的 gate |
|---------|-----------|----------------------------|
| P1-1：`503 completed + completion failed` 被渲染成通用 Host 故障 | `classifyBookingResponse` 按 body 形状判定 settled；页面只消费它 | 503-is-a-result 单测；`send()` 不按 `response.ok` 分流的源码级守卫 |
| P1-2：`/league/replays/archive` panic `main` 线程并杀死 Host | `strip_prefix`/`strip_suffix` 解析；畸形路径落到空 content address 并 404 | D3 gate 里的 malformed-path 断言 |
| P1-3：响应丢失是唯一禁止精确重试的情形 | transport 分支 `retryable: true`，附同一 body 的措辞 | 响应丢失相关单测 |
| P2：`matchId` 对 `String` 却标成 `number` | `string \| null` | （仅类型层；无 gate —— 见下面的证据上限） |
| **P1（新增，复审 `50a4f3b`）：failure panel 在结果未知时印出 `NOT BOOKED`** | kicker 归入分类（transport 为 `OUTCOME UNKNOWN`，refusal 为 `NOT BOOKED`），页面渲染 `{failure.kicker}` | 两条 kicker 断言；「页面不持有不存在声明」的源码级守卫 |

**证据上的诚实上限。** 这正是这里状态词必须严格的原因：

1. **没有任何 gate 证明玩家点过任何东西。** 这里没有浏览器 runner。写路径的分类与 kicker
   在模块层、并在结构上于源码层有 gate；而 `503 completed + failed` 面板与
   `OUTCOME UNKNOWN` 面板在浏览器中的真实渲染，仍只由 owner 的手工走查覆盖。
2. **P2 的类型修复没有自动化 gate。** `matchId: string | null` 由 build 期类型检查保证，
   而不是断言 —— 原来的 `number` 在运行时从未可观测（JSON 值加一个 `as` 断言），
   这恰恰是它能存活下来的原因。

相对最初授权的两项未变偏离，均已在复审中被 owner 接受：

1. **D6 的「选择器旁显示 Elo」未实现** —— 并且 owner 独立确认这是正确而非走捷径：
   在浏览器里 registry id 无法映射到 Studio League 的 `participant_id`，而能关上这个缺口的
   字段必须由 Host 从 Studio 身份权威派生，不能在客户端 hash。作为独立的授权事项延后。
2. **导航链接加在 `/` 与 `/play`** —— 不存在共享外壳组件，所以若不重构页头，
   没有别的地方可以加链接。

## Next authorized gate（下一道授权门）

owner 复审本 close patch，然后执行本文档的 8 步手工走查 —— **第 8 步，在回放棋盘里实际拖动、
逐手走过各 ply，仍是本轮无法自动化的那份验收证据**。不再有设计轮，D6 的 `GET /agents`
后续项也不作为本轮的一部分启动。验收之后：在 `docs/studio-league-v1.md` + `handoff.md`
记录关闭。
