# Studio Player Loop v1 — League 页面与 Review 体验交付

- **Status**: IN PROGRESS；Human Live Slice C + 原 Play UX E 已 IMPLEMENTED / VERIFIED（本地），D/F 待交付。
- **Baseline**: `8093dd3b97a85c4025750993484c8d32e5d7d3fb`，2026-09-18 核验 main / live origin/main 相同、worktree clean。
- **Owner-date**: 2026-09-18；owner 重申 9/11 七项闭环，明确继续完成玩家可用页面、接入、统计与 Review 修复。
- **不是验收**：继续授权不冒充对 `7d9f603` 的独立 review，不把已有后端测试当产品整轮 ACCEPTED。

## Problem and evidence

原 [Studio League](studio-league-v1.md) 的 A–E 是自然交付顺序，后续实现切片只完成部分产品面。
核对当前代码：`/ratings` 仍为冻结研究报告；`app/page.tsx` 仅 fetch `/recent-games`（旧人机局）；
`reader.rs` 只有 leaderboard / match detail / replay，尚无个人统计与有界比赛列表 API；
`/play` 没消费 `league_completion`，固定座位且 seed 转 Number；Review 的 My decisions
在 humanSeat=null 时返回全部 frames、seat 主要来自 URL。不能称七项需求已闭环。
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
| Human Live 接入 | B IMPLEMENTED / VERIFIED `7d9f603` | C 的页面事实 + 隔离测试；真实首局由 owner 执行 |
| Play Random/First/Second、Randomize seed | IMPLEMENTED / VERIFIED 本地 | random 一次、发实际 seat；禁止 seed 静默舍入 |
| 去重复 Earlier games | IMPLEMENTED / VERIFIED 本地 | 历史入口统一 Games |
| 长期 Games 有界查询/分页 | 待实施，不取消 | 不全量向浏览器搬 42k；稳定排序、筛选、Replay 入口 |
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

## Final implementation

### C/E — IMPLEMENTED / VERIFIED（本地，未真人验收）

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
| `cargo test -p splendor-cli --test league_host_api` | exit 0，23/23，含两 seats/u64::MAX 入账与持久化 |
| `cargo test -p splendor-cli`（独立 TEMP/TMP） | exit 0，296 passed / 0 failed / 3 ignored，45 targets |
| `npm test`（build + Node suites） | exit 0，80/80（+7 Play runtime gates） |
| `node tests/human-play-browser.mjs` | exit 0，真实 Chromium / built UI + **mock Host**；非实际真人/真实 Host E2E |
| `npm run lint` | exit 0 |
| `node node_modules/typescript/bin/tsc --noEmit --incremental false` | 修复后 exit 0；之前 baseline/current 均八错误的日志仍保留 |
| `git diff --check` | exit 0 |

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

C/E IMPLEMENTED / VERIFIED（本地），整个玩家闭环仍 IN PROGRESS，不是全产品 ACCEPTED。
D/F 和真实首局保留为后续门，未以本片验收替换。

## Known limitations

真实首局验收未执行；Games/统计/F 当前仍缺交付。数据库重建必须含 live Human evidence，
不能把仅已验证 historical importer 当全量历史+live rebuild 工具；后续验收需单独核验此链。

## Next authorized gate

C/E 本地已交付；继续 D 有界读面/统计 → F Review；最后 owner 真实链路验收。
