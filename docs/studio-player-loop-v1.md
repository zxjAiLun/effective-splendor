# Studio Player Loop v1 — League 页面与 Review 体验交付

- **Status**: IN PROGRESS；**Human Live League Integration v1 已 ACCEPTED / CLOSED（closeout `081c5dc`，owner 真人现场对局验收 PASS）**；本文件剩余范围为玩家闭环的 D/F：
  - D1 bounded League Games — **ACCEPTED / CLOSED**（owner 2026-09-19 复核通过；初版 `4a20f95` 经 2026-09-19 repair 后以 `3049642` 关闭）；
  - D2 `/ratings` 产品切分 — **ACCEPTED / CLOSED（owner 复核 `857250c`）**；P0=0/P1=0/P2=1（malformed-200 truthfulness，deferred，暂不修）；
  - D3 **D3A Reader + Host API — ACCEPTED / CLOSED @ `51bad22`（owner 复核，P0=0/P1=0/P2=1 deferred）**；**D3B Profile UI — IMPLEMENTED / VERIFIED 本地（2026-09-19，待 owner 复核真实 diff）**；F Review **NOT AUTHORIZED**。
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
| 长期 Games 有界查询/分页 | **D1 ACCEPTED / CLOSED @ `3049642`** | 不全量向浏览器搬 42k；稳定 `league_seq DESC` + `league_seq < before`；严格 limit 1..100 / 非法 400；authority refusal 503；集合式 participant filter；无 schema/index 变更 |
| `/ratings` 与个人统计 | **D2 ACCEPTED / CLOSED @ `857250c`**；**D3A ACCEPTED / CLOSED @ `51bad22`**；**D3B Profile UI IMPLEMENTED / VERIFIED 本地（待 owner 复核）**（`/ratings/[participant_id]` 严格按需加载、无并发 fan-out、SVG sequence 曲线、严格解码器）；**F Review NOT YET** | 两个 rating authority 代码层不互串；无数据不造数；不做 dead link；严格 limit/cursor 校验；不改 schema v3 |
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

### 2026-09-19 — D3B Profile UI 交付（当前轮，IMPLEMENTED / VERIFIED 待 owner 复核）

owner 2026-09-19 终审接受 D3A（`51bad22`，P0=0 / P1=0 / P2=1 deferred）并授权 D3B（Profile UI）。
严格纯前端实现，0 Rust / Host / schema 修改：
- **按需加载与会话级缓存（硬性调度契约）**：
  - 页面 mount 时**仅请求 Profile**（`GET /league/participants/:id`），绝不向 ratings/opponents/games 并发 fan-out；
  - 拆分 4 个 Section：`Overview`（首屏加载）、`Games`、`Rating history`、`Opponents`；
  - 用户点开对应 tab 时才触发相应数据请求，且在页面当前生命周期内 session 缓存（来回切 tab 不重复发网络请求）；
  - 分块独立 Retry：某分块加载失败仅重试当前分块，保留已成功的分块数据。
- **真值呈现与格式化**：
  - Initial Elo：rated=0 时显示 `1500 Initial Studio Elo` 与 `No rated games yet`；rated>0 时显示当前真实 Elo 与 Provisional 标识（<20 场）；严禁前端 `elo ?? 1500` 回退；
  - Completed plies：诚实 3 态显示（`available` / `partial` / `unavailable`），unavailable 时明确渲染 `Not recorded`，绝不伪造 `0 decision plies`；
  - Main turns 与 Gameplay breakdown：按 API 返回状态显示 `Not recorded` / `Not available`，绝不估算时长或伪造 VP / 行动比例；
  - Rating history：自研轻量 SVG 折线图，x 轴明确标为 **League sequence**（单调递增账本序，绝不按 played_at 重排，不插入虚构起点）；单点参与者（如 You）真实绘制单点与参考线；列表显示 played_at（空则显示 `—`）；`Load earlier` 游标加载无重复追加；
  - Opponents：严格区分 `Recorded Games` 与 `Rated Games`（及 `Rated W–T–L`），排除 self-match，提供指向对手个人页的安全链接，`Load more` 严格使用 Host 返回的 `next_after_opponent_id`；
  - Personal Games：直接复用 D1 `GET /league/games?participant_id=:id`，无新路由。
- **严格解码器（Fail Closed）**：
  - 在 `app/participant-profile-runtime.mjs` 实现 `decodeParticipantProfile`、`decodeRatingHistoryPage`、`decodeOpponentsPage`；
  - 严格校验 envelope format、version、participant_id 一致性、字段类型、数组与 cursor 格式；
  - 遇到畸形 200 响应（如 array/non-object/mismatch）立即报 invalid 错误，绝不静默回退为空列表或初始值。
- **排行榜安全链接**：
  - `/ratings` 榜单仅为具备非空 participantId 的有效行生成指向 `/ratings/[participant_id]` 的超链接；
  - `/ratings/reports` 研究报告页不提供任何 Studio 个人页链接，保持两套评级体系彻底隔离。
- **验证通过**：
  - `npm test`：**113 passed**（7 文件 + 本轮新增 `tests/participant-profile-runtime.test.mjs` 11 项纯函数/解码/错误测试 + `tests/rendered-html.test.mjs` 个人页服务端渲染断言，0 failed）；
  - `npm run lint`：**0 errors, 0 warnings**（包含清理 `review/page.tsx` 存量 `<a href="/ratings/reports">` 链接警报）；
  - CDP 真实浏览器交互门禁 `tests/participant-profile-browser.mjs`：真实 Chromium 运行通过，实测 mount 时 Host 仅拦截到 1 次 `/league/participants/:id` 请求；点击 Opponents 产生第 2 次；切回 Overview 再切回 Opponents 仍保持 2 次（证明缓存生效）；点击 Ratings 产生第 3 次并核验 SVG League sequence 轴；点击 Games 产生第 4 次；访问不存在 ID 正确显示 404 错误；
  - 3 组负向对照（mount 并发 fan-out、malformed 200 伪造成功、容忍非 1500 initial Elo）均打中对应门禁失败并字节还原（见 `local-artifacts/studio-league/player-loop/d3b-negative-controls.json`）；
  - Rust 套件保持全绿（`splendor-studio-league` 109 项、`league_host_api` 29 项）。
- **当前状态与下一步**：D3B 已全部交付完成，等待 owner 复核真实 diff；关闭后可进入最后待交付的 F（Review 体验修复）。

### 2026-09-19 — D3A Review: REPAIR REQUIRED @ `3946f50`（owner 复核，P0=0 / P1=3 / P2=1）

owner 复核 `3946f50` 真实 diff：Reader/Host 主体架构与真库性能测试结论通过（Busy profile warm ~311ms / You ~42ms，无持续多秒退化，维持 schema v3 0 索引裁决），但指出 3 项合同缺陷需要窄 Repair：
1. **P1-1（initial Elo authority）**：未评级（rated=0）participant 当库中存在非 NULL `current_elo` 时（如 1234.0 或 NaN），旧逻辑直接返回该数值并打标 `origin: "initial"`，违背协议 initial=1500 由 rating config 唯一定义的准则。修法：rated=0 且 `current_elo` 存在但与 protocol initial 不等时，立即 fail-closed 抛错；仅当 `None` 或与 1500.0 相等时才作为合法 Initial 返回。
2. **P1-2（SQL primitives 可见性）**：`PARTICIPANT_PROFILE_SQL`、`PARTICIPANT_RATING_HISTORY_SQL`、`PARTICIPANT_OPPONENTS_SQL` 曾标记为 `pub` 且在 `lib.rs` 被 re-export，破坏了 Reader 作为唯一权威读入口的封装契约。修法：改为 `pub(crate)`，并从 `lib.rs` 的 public re-export 中彻底删除。
3. **P1-3（opponents after cursor 校验）**：Host 曾将 `?after=` 当作 `None` 静默回退为第一页，且 Reader/Host 缺乏 cursor 长度上限。修法：冻结 `OPPONENT_CURSOR_MAX_BYTES = 256`；`after` 为空字符串或超长时 Host 返回 400，Reader 返回 `Err(StudioLeagueError::Invalid)`。
4. **P2（Busy 首读时延）**：首次冷读 Busy profile 约 1.56s，主要由 SQLite 页面冷起与大集合聚合导致。此项不阻塞 D3A；前端 D3B 必须严格按需分节请求（首屏仅 Profile，用户展开后才读 H2H/Ratings），禁止并发 fan-out。

### 2026-09-19 — D3A Repair 1（当前轮，COMPLETED / VERIFIED 待 owner 复核）

- **代码修复**：
  - `crates/splendor-studio-league/src/ledger.rs`：三条 SQL 收敛为 `pub(crate)`；`participant_profile` 严格校验 rated=0 时 stored current_elo 必须等于 initial_elo（否则 fail-closed）；`participant_opponents` 引入 `OPPONENT_CURSOR_MAX_BYTES = 256` 并拒绝空字符串与超长 cursor；
  - `crates/splendor-studio-league/src/lib.rs`：移除三条 SQL 的公网导出，保留 `OPPONENT_CURSOR_MAX_BYTES`；
  - `crates/splendor-cli/src/human_play_command.rs`：Host 对 `/opponents` 的 `?after=` 进行严格校验，空串或超过 256 字节均返回 400 Bad Request；
  - 测试扩展（`participant_profile_tests.rs`、`league_host_api.rs`）：增加针对 P1-1（rated=0 存 1234.0 报错、存 1500.0 容忍）、P1-3（空 after 400/Err、>256 字节 400/Err、恰好 256 字节 200/Ok）的严格断言。
- **负向对照（Repair 1 NC1–NC3，全部通过且字节还原）**：
  - NC1 (P1-1)：改回容忍 rated=0 存放任意 current_elo ⇒ 对应 gate 立即 FAIL（exit 101）；
  - NC2 (P1-3 Host)：改回放行 `?after=` 为 None ⇒ 对应 Host gate 立即 FAIL（exit 101）；
  - NC3 (P1-3 Reader)：移除 Reader 侧超长 cursor 校验 ⇒ 对应 Reader gate 立即 FAIL（exit 101）。
- **验证通过**：
  - `splendor-studio-league`：109 tests passed（0 failed）；
  - `splendor-cli` `league_host_api`：29 tests passed（0 failed）；
  - `apps/replay-studio`：102 tests passed（0 failed）；
  - 真实 Host smoke：You profile (1530)、Busy profile (18496 games)、`?after=` (400) 运行核验通过。

### D3A Reader + Host API — 初版实现记录 @ `3946f50`（2026-09-19，已由上述 Repair 1 替代）

owner 终审接受 D3 Recon 并授权 D3A（不改 schema/index、不写 gameplay builder、不估算 duration）：
- **实现细节**：
  - `crates/splendor-studio-league/src/ledger.rs`：新增 `PARTICIPANT_PROFILE_SQL`、`PARTICIPANT_RATING_HISTORY_SQL`、`PARTICIPANT_OPPONENTS_SQL`，以及常量 `RATING_HISTORY_DEFAULT_LIMIT=100 / MAX=200`、`OPPONENTS_PAGE_DEFAULT_LIMIT=20 / MAX=50`；
  - Profile 严格契约：rated=0 返回 protocol `initial_elo=1500`（origin=`initial`），rated>0 必须存在且 finite（否则 fail-closed 抛错），严禁前端回退；暴露 `completed_plies`（decision plies 均值 + 观测样本/完成比赛数），`main_turns`（not_recorded）与 `gameplay`（no_authoritative_builder）明确 unavailable，**不暴露内部诊断字段**；
  - 游标分页严格校验：limit/before/after 超界或负数一律返回 400，不静默 clamp；对手列表排除 self-match 与未归属 seat，不伪造 Unknown 名字；
  - `StudioLeagueReaderV1` 暴露 typed 方法：`participant_profile`、`participant_rating_history`、`participant_opponents`，每次读取均先执行 `validate_authority_evidence()` 权威复验；
  - Host 路由在 `crates/splendor-cli/src/human_play_command.rs` 接入：`GET /league/participants/:id`、`GET /league/participants/:id/ratings`、`GET /league/participants/:id/opponents`，未知 participant 返回 404，请求格式返回对应 Envelope（version 1）。
- **真实库规模与 Host 耗时核查**（42,523 matches，schema v3，throwaway studio-host on 10241，7 次采样）：
  - `you_profile`：首次 751.17ms（进程冷起+打开reader），warm 中位 **42.33ms**（min 39.92ms）；
  - `busy_profile`：首次 1556.10ms，warm 中位 **311.51ms**（min 288.26ms），完全处于已知有界范围，**未出现意外多秒级退化**；
  - `you_h2h`：warm 中位 **45.43ms**；`busy_h2h`：warm 中位 **290.36ms**；
  - `event_heavy_ratings`：warm 中位 **13.72ms**；
  - `you_games`（D1 复用）：warm 中位 **49.98ms**；`busy_games`：warm 中位 **262.62ms**；
  - 未知 participant 返回 404；真实 DB SHA-256 保持 `3941c3059e4b3eea485158963d2619d262d7a83842a55e1921809b9fdf57baee`。
- **负向对照（NC1–NC3，全部通过且字节还原）**：
  - NC1：在 rating_history 移除严格 limit 校验改为 clamp ⇒ 对应门禁立即 FAIL（exit 101）；
  - NC2：在 participant_profile 允许 rated>0 缺失 current_elo 时静默回退 1500 ⇒ 对应 fail-closed 门禁立即 FAIL（exit 101）；
  - NC3：在 opponents 查询移除 `AND o.participant_id <> ?1` ⇒ 排除 self-match 门禁立即 FAIL（exit 101）。
- **测试通过**：
  - `splendor-studio-league`：109 tests passed（52 unit + 57 integration，0 failed）；
  - `splendor-cli` `league_host_api`：29 tests passed（新增 3 条 participant profile/ratings/opponents 真实 socket 门禁 + authority drift 扩展覆盖，0 failed）；
  - `apps/replay-studio`：102 tests passed（0 failed）。
- **当前状态与下一步**：D3A 已全部实现并完成真实库门禁，等待 owner 复核真实 diff；D3B（Profile UI）与 F（Review）未授权。

### D3A Reader + Host API — AUTHORIZED / IN PROGRESS（baseline `5eacfb3c44203e8fd9c6651095564271b5e3bf87`）

owner 2026-09-19 终审接受 D3 Recon（`5eacfb3`，P0=0 / P1=0 / P2=1）：
- **Index 裁决**：D3 v1 **不建 index、不改 schema version、不改 DDL**。原因：schema v3 变动牵涉版本升级/rebuild 生命周期；当前 Profile 单次查询 You ~34ms / Busy ~461ms，且 UI 采用按需分节（先 Profile，用户展开才读 H2H/Ratings），未构成破坏性阻塞。P2 冻结为已测候选，留待真实阻塞或必要 schema bump 时再议。
- **Contract 冻结**：
  - `GET /league/participants/:id`：单行 ProfileV1。identity、rating（rated=0 时 Reader 给出 initial=1500，rated>0 必须存在且 finite，严禁 UI 回退）、record、seats、completed_plies（decision_plies 均值 + 观测样本/完成比赛数）、main_turns（unavailable/not_recorded）、gameplay（unavailable/no_authoritative_builder）。**不暴露内部诊断字段**（如 failed rows / detail flagged games）。
  - `GET /league/participants/:id/ratings`：default 100 / max 200，严格校验不 clamp，`league_seq < before` 降序游标，played_at 允许 null。
  - `GET /league/participants/:id/opponents`：default 20 / max 50，严格校验不 clamp，`opponent_id > after` 升序游标，明确 recorded 与 rated 胜平负，不含 self-match，不伪造未知对手。
  - Games：完全复用 D1 `GET /league/games?participant_id=:id`，不新建个人 games 路由。
- **范围划分**：本轮仅做 **D3A（typed reader + Host API）**，由 owner 复核真实 Host 规模耗时与 diff 绿后，再授权 D3B（Profile UI）。F Review 仍未授权。

### 2026-09-19 — D1 closeout review / repair（历史轮，已 CLOSED @ `3049642`）

owner 授权由本助手判断收口及后续顺序。本轮是同一实现者复核，不冒充独立 review。
基线 `4a20f95048e4e9cfb55b1ca0f6ce1398f4d838b4`，main == origin/main，入场 clean。
**裁决：暂不收口**；以下历史记录保留，但「九项全达成」与「比 leaderboard 快即可接受」撤回。

已定位问题：
1. owner 冻结非法 limit → 400，初版却 clamp；相应负向测试保护了错误合同。
2. Host 把所有 `StudioLeagueError::Invalid` 映射成 400，混淆 request-invalid 与 authority-refused（应 503）。
3. 新 `pub league_match_page(&Connection, ...)` 暴露未重验 authority 的新读旁路，应为 crate-private。
4. 初版逐行读取 seats，且只比较 EXISTS/index/JOIN，没有验证无新 index 的集合式 participant 过滤；
   EXPLAIN gate 使用复制 SQL，甚至固定必须存在 correlated subquery，不能保护生产查询。
5. UI 读取失败后隐藏 Load more，且 malformed 200 被当成空页；没有真实浏览器分页证据。

**修复门（执行前冻结）**：恢复严格请求校验；有效请求的 reader refusal 统一 503；raw SQL 仅 crate 内；
集合式分页先选 limit+1 match 再批量联 seats，自匹配不重复、准确终止；真实 SQL 的 plan 和真实库 wall time
同时测无过滤/You/繁忙 participant/不存在 participant，不添加 schema/index。
补 fixture、Host（运行中 authority drift）、UI failure/malformed response、legacy 保留门。
真实库只读、测试独立 TEMP/TMP/target，Human completion/Elo/Review 不改。
**当前修复已达到这些门，复验全绿，D1 裁决 ACCEPTED / CLOSED**；下一主线选择独立 D2，再 D3，F 最后，不混合提交。

**2026-09-19 repair 验证结果（同一实现者复核，非独立 review）**：

- suite 复验（`CARGO_TARGET_DIR=E:\tmp\d1-repair`）：league crate 全套各目标绿（lib 47 + 集成 29/8/7/5/4/4/3/1/0），
  `league_host_api` 26/26，UI runtime 14/14、全量 94/94，tsc 0 / lint 0；
- 真实 42,523 库（sha `3941c305…ce`，`mode=ro` + `query_only`，6 次 warmup）：无过滤 best 0.05 ms（`matches_league_seq` 索引走）；
  You best/median 28.5/32.0 ms；最忙 participant（36,416 seats）166.9/178.2 ms；不存在 participant 27.1/31.4 ms；
  plan 均为 `LIST SUBQUERY` + `SCAN match_seats` + `TEMP B-TREE`；**未新增 schema/index**；
- **真实 Chromium 分页门 `tests/games-page-browser.mjs` PASS**（本地可选门，模仿 `human-play-browser.mjs`，不进 `npm test`）：
  两段区块各自渲染；Load more 按 Host 签发 cursor 翻页，调用序列恰好 `"", limit=50&before=150, limit=50&before=75 ×3`；
  500 失败保留 4 行并出现页面级 Retry、retry 重发同一 cursor；malformed 200 当错误不当空页；末端准确显示 End marker，且零页面 JS 异常；
- 负向对照（3 组修复面，全部击中目标门并字节级还原到修复后状态）：去掉 limit 严格校验
  ⇒ `the_limit_is_validated_by_the_read_surface_not_the_caller` 失败；Host 把 `Invalid` 重新映射为 400
  ⇒ `a_league_that_goes_stale_while_the_host_is_running_stops_being_served` 失败；生产 SQL 换回 correlated `EXISTS`
  ⇒ `the_unfiltered_page_is_index_driven_and_the_filter_is_a_set_driven_subquery` 失败。
  脚本与日志在 `local-artifacts/studio-league/player-loop/d1-repair-negative-controls.json` + 同名 `*.log`（含 restore sha256）；
  中间两次脚本自身失败（路径常量写法和 mutating snippet 编译失败）已记录为无效对照后重做，不作为证据。
- 收尾时发现并修掉的第二个门级缺陷：scale gate 此前 `EXPLAIN` 的是**逐字复制的 SQL**，改生产查询不会打到门。
  现把两段生产 SQL 提为 crate-private 常量（`GAMES_PAGE_ALL_SQL`/`GAMES_PAGE_FILTERED_SQL`），reader 与 gate 共享同一文本，门保护的是生产查询本体。

**裁决：D1 ACCEPTED / CLOSED（2026-09-19）**。

### D1 修复实现（2026-09-19，复验全绿）

- Reader page API 仍只通过 `StudioLeagueReaderV1` 对外；底层 `league_match_page(&Connection, ...)` 收回 `pub`，仅 crate 内测试/reader 可用。
- `limit=None` 使用默认 50；显式 `limit < 1` 或 `limit > 100` 由 Host 在 HTTP 边界返回 400，**不再 clamp**。
- `before <= 0` 由 Host 返回 400；authority/config/manifest/database 等 Reader refusal 统一走 503。
- header 查询使用 `limit + 1` 判断是否有下一页；seats 通过一个 `IN (...)` 批量查询装配，移除每行一个 seat query 的 N+1。
- participant filter 使用 `match_id IN (SELECT match_id FROM match_seats WHERE participant_id=?)` 的真实生产 SQL，避免旧 correlated `EXISTS`；无过滤路径仍走 `matches_league_seq`。
- scale gate 现在检查真实生产 SQL 的 plan：无过滤 `matches_league_seq`；过滤 `LIST SUBQUERY` / `match_seats`，且禁止 `CORRELATED SCALAR SUBQUERY`。
- authority drift gate 现在覆盖 `/league/games` 无过滤与 participant filter，两者在同一 Host 进程中均 503。
- UI malformed 200（缺少数组或 cursor 类型错误）现在是错误，不再伪装为空列表/结束；frontend runtime 新增 limit contract tests。

### 2026-09-19 — D2 /ratings 产品切分（交付时 IMPLEMENTED / VERIFIED；现已由 owner CLOSED @ `857250c`）

- **授权范围**：owner 确认 D1 收口（P0=0 / P1=0 / P2=1 participant-filter 性能留 D3），**明确仅授权 D2**；D3（个人页）与 F（Review）未授权。
- **产品切分与隔离**：
  1. `/ratings` 改为 **Studio League current leaderboard**，消费 Host `/league/leaderboard`。
     仅展示 participant、kind（Human/Engine）、current Elo、rated/recorded、W-T-L、provisional。绝不重算 Elo，绝不混入 `official_elo`。
  2. 既有研究 Rating Studio 整页**原样迁至 `/ratings/reports`**，保持 M22 默认报告、M19 切换、Batch BT、矩阵与报告上传功能与数据完全不变。
  3. 页面视觉与文案强区分：`/ratings` 新增 Authority Note 明确标注与研究报告的不同体系；各页顶栏导航明确标注 `Ratings`（联赛）与 `Research reports`（研究）。
  4. **未做个人统计页**，无 dead link；未借机改写 leaderboard 既有 1.2s 慢查询。
- **源码与运行时隔离门**：
  - 新增 `tests/ratings-authority-split.test.mjs`：静态断言 `/ratings` 与 `ratings-runtime.mjs` 绝对不包含 `m19-rating-report`、`m22-rating-report`、`official_elo` 或 research runtime；反向断言 `/ratings/reports` 与 `rating-runtime.mjs` 绝对不含任何 `/league/` 调用。
  - 新增 `tests/ratings-runtime.test.mjs`：对首局人类实操真实数据（`You` 1530 / 1-0-0 / provisional）及各类缺省场景做纯函数渲染断言。
  - 扩展 `app/league-runtime.mjs` 的 `describeLeaderboard` 支持返回 `kind` 字段，并在 `tests/league-runtime.test.mjs` 中补充断言。
  - 更新 `tests/rendered-html.test.mjs`：拆分 `/ratings`（SSR 为 loading 态，无研究词汇与虚假 Elo）与 `/ratings/reports`（原样验证）。
  - 新增 Chromium 本地门 `tests/ratings-page-browser.mjs`：验证 `/ratings` 仅打 1 次 `/league/leaderboard`，且 `/ratings/reports` 渲染、M19 切换、报告文件上传全过程产生 **0 次 league 调用**。
- **真实 Host 验证**：
  - 启动独立只读 Host 进程直连 42,523 场真实库（`mode=ro`），curl `/league/leaderboard` 验证 `You` 行字段完全吻合：
    `display_name: "You"`, `elo: 1530`, `kind: "human"`, `rated_games: 1`, `recorded_games: 1`, `rated_wins: 1`, `provisional: true`。总计 100 行（99 engine, 1 human）。
- **负向对照（3 组，全数击中并字节级还原）**：
  1. `nc-studio-page-imports-research`：向 `/ratings` 引入 M22 报告导入，`ratings-authority-split` 立即 FAIL。
  2. `nc-reports-page-reads-the-league`：向 `/ratings/reports` 注入 `/league/leaderboard` fetch，`ratings-authority-split` 立即 FAIL。
  3. `nc-kind-mapping-dropped`：破坏 `describeLeaderboard` 的 `kind` 映射，`league-runtime` 与 `ratings-runtime` 门立即 FAIL。
- **平台与环境发现**：
  - 发现 vinext 1.0.0-beta.2 存在既有缺陷：客户端点击 Next `<Link>` 会因 `RSC prefetch setup error: TypeError: f is not a function` 导致客户端路由中断（在原版首页跳转 Play 同样稳定复现，与 D2 无关）。Chromium 测试对全页刷新使用 `Page.navigate`，对 Link 则在 DOM 层面断言 `href` 存在。
  - 本轮未改动任何 Rust 文件，按惯例不重新运行 Rust 全套测试。

### 初版决策与历史记录（以下按初版 `4a20f95` 口径保留，结论须结合上面的修复更正读）

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

### D1 初版 — Bounded League Games Read（`4a20f95` 的交付形态；其中 clamp/EXISTS/逐行 seats 等已被 2026-09-19 repair 取代，以下按初版记录保留）

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

#### D1 初版真实 42,523 库实测（per-candidate probe 口径；修复后的集合式实测见上 Iteration log，未重写此处）

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

#### D1 初版负向对照（4 组，初版 `4a20f95` 的门；其中 `nc-clamp-removed` 保护的是初版的 clamp 合同，修复后该门已改为断言严格拒绝。修复面的 3 组新对照见上 Iteration log）

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
- **D1 bounded League Games：ACCEPTED / CLOSED（2026-09-19 repair round）**。初版 `4a20f95` 复核出 5 项合同缺陷
  （clamp 违约、400/503 混淆、pub 旁路、逐行 seats + 复制 SQL 的 EXPLAIN 门、UI 失败后隐藏入口/畸形 200 当空页），
  修复后全部冻结修复门复验绿（见 Iteration log）；owner 2026-09-19 委托本助手判断收口，本裁决即按委托作出。
  合同面向：typed Reader page API、Host `GET /league/games`（非法 limit/cursor 400，authority refusal 503）、
  cursor 语义（非 OFFSET）、集合式 participant filter、批量 seats 装配、Games UI 有界分页 + 失败保留 + 页面级 Retry、
  legacy games 独立区块保留、真实 Chromium 分页门、真实库 re-measure、**未改 Elo / completion / Review、未改 schema**。
- **D2 ratings product split：ACCEPTED / CLOSED @ `857250c`（owner review，2026-09-19）**；P0=0/P1=0/P2=1 deferred。
  交付完全符合 owner 最小验收门：
  - `/ratings` 呈现 Studio 榜单，`You` 行 1530 / 1-0-0 / rated 1 / recorded 1 / provisional，无 `official_elo` / M19 / M22 概念；
  - `/ratings/reports` 承接原 Rating Studio，数值完全一致，支持切 M19，支持报告文件上传，H2H 矩阵完整保留；
  - 源码级与运行时级双向隔离门通过：Studio 不 import 报告数据，Research 不请求 `/league/`；
  - 导航明确区分 `Ratings` 与 `Research reports`。
- **D3A Reader + Host API：ACCEPTED / CLOSED @ `51bad22`（owner review 2026-09-19）**。P0=0/P1=0/P2=1 deferred；三项 Repair 全部关闭（P1-1 initial Elo 伪造守卫、P1-2 三条 SQL crate-private、P1-3 opponents after cursor 双层非空与 256B 上限校验）。
- **D3B Profile UI：IMPLEMENTED / VERIFIED（2026-09-19 本地）**，待 owner 复核真实 diff。严格按需调度，首屏仅 Profile，Games/Ratings/Opponents 点开加载并 session 缓存，SVG sequence 曲线，严格解码器。
- **本片明确未做**：F Review、gameplay builder、replay backfill、duration 统计、任何 schema 变更（保持 schema v3，0 索引）。
- **保留 P2**：Busy profile/H2H 仍为数百毫秒级计算，当前依靠 UX 按需分节调度控制负载，不改 schema。

## Known limitations

1. **`participant_id` 过滤不便宜**（集合式实测：You 28–32 ms、最忙 participant 167–178 ms、不存在 27–31 ms）。
   当前未加 index；无 schema 变更。D3 之前**禁止在多个 dashboard widget 中大量并行并发使用此 filter**。
2. **vinext 1.0.0-beta.2 的客户端 `<Link>` 预取报错中断路由**：在首页或任意页面点击 Next Link 会在控制台抛出
   `RSC prefetch setup error: TypeError: f is not a function`，导致客户端跳转受阻。此为既有平台级问题（非 D2 引入），
   全页刷新与地址栏直访完全正常，浏览器测试通过 `Page.navigate` 规避，待独立评估是否升级/修复 vinext。
3. **D2 malformed-200 truthfulness**：`describeLeaderboard(body.rows)` 在 `rows` 非 array 时会落入空列表显示；owner明确deferred至共享decoder，不在D3 Recon修。
4. D3 个人统计与 F Review 待交付。数据库重建必须含 live Human evidence，
   不能把仅已验证 historical importer 当全量历史+live rebuild 工具；后续验收需单独核验此链。

## Next authorized gate

按 owner 2026-09-19 最新指示：
1. D3B Profile UI 已完成实现与本地验证（纯前端交付，按需调度、SVG League sequence 曲线、严格解码器、浏览器门禁全绿），等待 owner 复核真实 diff；
2. owner 确认 D3B 真实 diff 并关闭后，进入玩家闭环最后一项 **F Review 体验修复**（My decisions 座位鉴权、玩家状态共用且置于上方、结构化彩色行动、同配置缓存切换）；
3. 遵循独立 commit 纪律，各主线分立，不得修改 Human completion 主链。
