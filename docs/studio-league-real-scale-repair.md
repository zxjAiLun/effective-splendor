# Studio League — Real-Scale Walkthrough Blocker Repair

- **Status**: `IMPLEMENTED` / `VERIFIED`（本地证据；三处代码修复已落地并各有 gate）。
  **尚未 `ACCEPTED`** —— 本轮的验收证据是 owner 的 8 步手工走查，而走查在修复前的第 2 步
  就已经被真实规模的数据卡死，因此**修复后必须从第 1 步重新走**。启动器一项见「结果与决定」，
  它是本轮唯一被 owner 当场收窄口径的条目。
- **Baseline**: `c41143c`（`main` == `origin/main`，工作树干净）。本轮之前，League Play v1
  的页面、Host 读写 API、completion 权威均已 `ACCEPTED/CLOSED`。
- **Owner-authorised scope**: 事故驱动的一轮，**不是**更多 Studio League 功能。授权顺序被 owner
  固定为六步，其中前三步是必修缺陷，第四步是回归门，第五步是启动器，第六步是文档。
- **Non-goals（owner 明确排除）**: Host 线程池、独立 health 线程、async runtime、D6 的
  participant-id join、统计图表、Review 积压、鉴权、批量/监视器、Replay 渲染器、
  Commit D 的 archive 三态 P2。

## Problem and evidence（问题与证据）

### 直接症状

owner 在 `http://127.0.0.1:4173/league` 上看到：两个「选择 agent」的下拉框**点不动**，
而页面状态行写着 **`Studio Host ready`**。页面同时宣称「就绪」和「完全不可用」——两者不可能
同时为真，所以至少有一个是假的。

### 受控取证（只读；除杀掉那个卡死的 Host 外未做任何改动）

对一个全新启动的 Host（`--registry benchmarks/studio-1v1.registry.json
--reviewer-registry benchmarks/studio-reviewers.registry.json --port 43199`）逐条路由计时：

| 路由 | 结果 |
|------|------|
| `/health` | 200，**3.8 ms** |
| `/agents` | 200，13.8 ms（2145 B） |
| `/reviewers` | 200，3.1 ms（1551 B） |
| **`/league/leaderboard`** | **20 s 后 http=000、0 字节**；进程 CPU 从 0.015 s 涨到 **18.8 s**（≈ 单核 94%） |

真实库规模：`matches` **42,521** / `match_seats` **85,042** / `participants` **100** /
`rating_events` **28,010**。`match_seats` 上**没有 `participant_id` 索引**
（只有 `sqlite_autoindex_match_seats_1`）。

`EXPLAIN QUERY PLAN` 给出根因：生产 SQL 用 5 个**相关标量子查询**从 `participants` 出发，
每个参与者都要 `SCAN s`（整张 85k 行座位表）。合计约 `100 × 5 × 85k ≈ 4,200 万`次行访问。

### 两个独立缺陷，不是一个

**缺陷 A：leaderboard 查询在真实规模下病态。** 它的*正确性*没问题（下面第 1 步证明了这一点），
只是计划是 O(参与者 × 座位全表扫描 × 5)。

**缺陷 B：HTTP 边界上没有任何 socket 超时。** `grep set_read_timeout|set_write_timeout`
覆盖 `crates/splendor-cli/src/*.rs` = **0 命中**。两个 accept 循环
（`serve()` 在 `human_play_command.rs:1583`、Studio Host 循环在 `:1804`）都是
`for connection in listener.incoming()`，各自调用同一个阻塞的 `read_request`
（`BufReader::read_line`，无超时）。

因为 accept 是**串行**的，B 单独就足以让整个 Host 永久不可用。受控实验：

1. 全新 Host，`/health` **200 / 3.8 ms**；
2. 只打开一条 TCP 连接、**什么都不发**；
3. 此时 `/health` 与 `/agents` **双双超时**（8.0 s、0 字节）；
4. 那条连接一关闭，`/health` **立刻恢复 200 / 2.4 ms**。

**缺陷 C：页面在未确认 Host 可用时先写了 `ready`。** 取 owner 当时那个 dev server 的
`/league` HTML：里面有**两个 `<select disabled="">`**、状态文本 **`Studio Host ready`**、
以及 **0 处** `error-banner`。页面把一个它并不知道的事实写成了已知事实。

### 被排除的假设（查过，不是猜的）

- 「Host 没在跑」—— 它是 LISTENING 的（早先那次 `http=000` 的读数不精确，已更正）；
- HTTP keep-alive 复用 —— `respond()` 本来就发 `Connection: close`；
- 权威复验太贵 —— `identity.json` 只有 **204 字节**，sha256 用时 0.0000 s；
- SQLite 写锁 —— 现场没有 `-wal`/`-shm`。

### 诚实记录的未知

杀进程之前那一刻，那个 Host 的 CPU 已经回落到约 9% 平均，而 `/health` 仍是 000 —— 与
「空闲连接卡死」一致，但**当时究竟是哪个 socket 没被钉死**。

### 走查本身也发现了文档缺陷

运行配方的第 1 条命令**根本跑不起来**：

```
cargo run -q -p splendor-cli -- studio-host ...
error: `cargo run` could not determine which binary to run. Use the `--bin` option ...
       available binaries: m30a_probe, m32a_export_sidecar, splendor
```

而且它指向的 `private/registry.json` **不存在**（`private/` 目录本身就不存在）。
走查第 2 步只覆盖了「连接被拒」，从未覆盖**「在监听但不回应」**这一态 —— 而 owner 撞上的
正是后者。

### 启动器缺陷

`Start Splendor Studio.cmd` 用 `Start-Process ... -WindowStyle Hidden` 拉起 Host 与 UI，
但**不记录任何 PID**。`local-artifacts/studio-host/host.pid`/`ui.pid` 是 **2026-08-29** 的
陈迹（`4023272` / `4023275`，两个进程早就不存在）。结果：owner 有一个隐藏的、卡死的 Host，
却没有任何把手。

## Initial design（初始设计与口径收窄）

按 owner 的固定顺序，本轮只做六件事：

1. **修 leaderboard 查询**（最高优先级）—— 在查询本身修，**不许**用加 Host 线程来掩盖；
2. **公共 HTTP 边界加 socket deadline**（read 2 s / write 5 s）—— 一个 helper、两个 accept
   循环共用；`HOST-2` 是这个原语的附带收益，不是独立项目；
3. **修 `/league` 的就绪真相**—— 三态，未确认可用时绝不写 `ready`；
4. **加一条中型 fixture 回归门**—— 让这个缺陷以后能被抓住；
5. **把启动器降级**—— 收窄为「普通双击脚本」；
6. **运行配方与走查文档**在同一次交付里改掉。

### owner 对第 5 项的当场收窄（本轮的第二次校准）

第一版启动器我把 PID 记录、`Stop` 脚本、按 PID 停止的生命周期都设计了进去，
并且提出给 `studio-host` 加 `--pid-file`。owner 收回了：

> 你这个提醒是对的：**launcher 是 convenience，不是 infrastructure。**
> 前面为了一个「懒得输启动命令」的需求开始设计进程监管，明显跑偏了。

收窄后的口径：

- 两个进程都**可见**（不许 `-WindowStyle Hidden`）；**窗口就是日志，关窗口就是停止**；
- **不要** PID 文件、**不要** stop 脚本、**不要** `Stop Splendor Studio.cmd`（已删除）；
- **不要** PowerShell `-PassThru` / `Set-Content` / `-ExecutionPolicy Bypass`；
- 甚至「先探活、已在跑就不重复启动」也**不是必须**的：端口被占就让对应终端直接显示错误。
- 一句话：**「把我本来要手敲的两条命令敲出来。」**

## Scope and non-goals（范围与非目标）

**范围**：真实规模可用性修复（查询复杂度、socket 边界、页面真相、回归门、启动器、文档）。

**明确不做**：

- 不用并发掩盖慢查询（不加 Host 线程池、不把 `/health` 挪到独立线程、不引入 async runtime）；
- 不因为串行 Host 仍会被**真正在跑的**慢请求阻塞就重构服务器 —— 本轮只杀掉两个已被证明的
  异常源（病态 SQL、无界空闲 socket）；
- 不默认加 `match_seats(participant_id)` 索引（先测集合式查询；只有在仍有明显收益且有证据时
  才加，克制 schema 变更）；
- 性能验收**不冻结绝对毫秒值**；
- 不做 D6 的 `GET /agents` 新增字段；
- 不做统计、Review 积压、鉴权、批量、Replay 渲染器、Commit D 的 archive 三态 P2。

## Contracts and invariants（契约与不变量）

1. **榜单数字不变。** 查询重写只允许改变*代价*，不允许改变任何一个字段的值。
2. **写路径不得继承读超时。** UI 读预算只用于首屏读
   （`GET /agents`、`GET /league/leaderboard`）；**绝不**用于 `POST /league/matches` ——
   一次真实对局本来就可以跑很久，而 POST 已有 occurrence-id 歧义/重试契约，
   把读超时复制到写路径等于**人为制造 `OUTCOME UNKNOWN`**。
   **读预算分两档**（见下文 P2 修正）：普通首屏读 5 s，**leaderboard 10 s**。
3. **名单与榜单独立加载。** 榜单慢/坏，不得让 registry 选择器看起来「不存在」；
   registry 坏，也不得让联赛数据看起来坏掉。
4. **串行 accept 的限制继续成立并且继续被承认**（见非目标）。
5. **socket 超时是公共边界的性质**，不是两套实现：超时即该连接失败、记一条请求错误、
   丢弃 socket、accept 循环继续。
6. **启动器不管理生命周期**（见上）。
7. **状态词严格**：`IMPLEMENTED`/`VERIFIED` ≠ `ACCEPTED`；没有浏览器 runner，
   任何 gate 都不得声称「玩家点过按钮」。

## Implementation plan（实现计划）

| # | 工作 | 完成判据 |
|---|------|----------|
| 1 | ledger 查询改为集合式聚合 | 与旧查询在真实库上逐字段一致 + 计划中不含 per-participant 全表扫描 |
| 2 | 公共 socket deadline | 空闲连接存在时 `/health` 仍在界内返回 200，之后 Host 仍存活 |
| 3 | 页面三态就绪 | `checking` 绝不显示 `ready`；读超时 → `not responding`；选择器 pending 有解释 |
| 4 | 中型 fixture 回归门 | 语义等价 + 计划性质（代价不随参与者数增长）+ 宽松时限 |
| 5 | 启动器降级 | 两个可见窗口 + 打开 `/league`；无 PID、无 stop、无隐藏 |
| 6 | 文档 | 配方改成可执行形态；走查第 2 步扩为四态；记录走查被阻塞的经过 |

## Iteration log（迭代日志）

### 第 1 步 —— 查询重写（先取证，再改生产）

按 owner 冻结的协议：**先把当前榜单结果存为参照 → 写集合式聚合 → 在真实库上逐参与者逐字段
比对 → 确认無误后才替换生产**。

集合式版本用三个 CTE：

- `rec`：`COUNT(DISTINCT match_id)` 从 `match_seats` 按 `participant_id` 分组
  —— **不带 join**，从而保持旧语义（座位行所属的 match 缺失时仍然计入 recorded）；
- `winners`：`COUNT(*)` 从 `match_seats WHERE won = 1` 按 `match_id` 分组；
- `rat`：`match_seats JOIN matches ON rating_eligible = 1 LEFT JOIN winners`，
  算 `COUNT(*)` 与两个 `SUM(CASE ...)`（唯一胜者 → wins；多于一个胜者 → ties）；

再把三者 `LEFT JOIN` 到 `participants`，用 `COALESCE(..., 0)` 补零。

**真实库上实测**：

| | 旧（相关标量子查询） | 新（集合式 CTE） |
|---|---|---|
| 100 行耗时 | **19.723 s** | **1.104 s** |
| 逐参与者逐字段比对 | — | **100 vs 100 行，0 处不一致** |
| 查询计划 | `CORRELATED SCALAR SUBQUERY` × 5，每个参与者一次 `SCAN s` | `MATERIALIZE rec` / `MATERIALIZE rat` / `MATERIALIZE winners`，之后 `SEARCH rec/rat USING AUTOMATIC COVERING INDEX (participant_id=?) LEFT-JOIN` |

（更早一版把 `COUNT(DISTINCT seat.match_id)` 放进单个 CTE，实测 4.304 s；分解为三个 CTE 后
降到 1.104 s。）

**未加索引。** owner 的要求是先测集合式；`1.1 s` 相对 `19.7 s` 已经足够，因此不加
`match_seats(participant_id)`，避免 schema 变更。

Rust 侧的派生（`rated_losses = rated − wins − ties`、`provisional = rated < threshold`）
与排序（`elo` desc、`rated_games` desc、`display_name` asc）**保持原样** —— 重写只针对 SQL。

**生产常量**：为了让回归门能 `EXPLAIN` **真正的生产查询**而不是它的副本，
把 SQL 提为 `pub const LEADERBOARD_SQL: &str`，由 `leaderboard()` 使用，
并从 crate 根再导出（与 `leaderboard` 同一个公共面）。门若钉住一份副本，就会与它要保护的
查询漂移。

Host 级复验（真实库）：`/league/leaderboard` 现在 **200，1.09–1.22 s（热）/ 1.13 s（冷）**；
100 行；榜首 `splendor.exe:agent-s3-rollout`，Elo 1940，W/T/L = 289/0/101。

### 第 2 步 —— socket deadline

在 `human_play_command.rs` 增加唯一一个 helper：

```text
const HTTP_READ_TIMEOUT: Duration = Duration::from_secs(2);
const HTTP_WRITE_TIMEOUT: Duration = Duration::from_secs(5);
fn prepare_connection(stream: &TcpStream) -> Result<(), String>   // set_read_timeout / set_write_timeout
```

**两个** accept 循环各调用一次（`serve()` 与 Studio Host），失败时记一条请求错误并 `continue`。

现场复跑之前失败的那个实验：保持一条空闲连接，`/health` **0.41 s 200**、
`/agents` 2 ms 200、`/league/leaderboard` 1.14 s 200；Host stderr 正好记了一条
`Studio Host request error: ... (os error 10060)`。

### 第 3 步 —— 页面三态

`league-runtime.mjs` 新增：`HOST_CHECKING` / `HOST_READY` / `HOST_NOT_RESPONDING`、
`HOST_STATUS_TEXT`、`FIRST_SCREEN_READ_TIMEOUT_MS = 5000`、读结果四态
（`READ_OK` / `READ_REFUSED` / `READ_TIMED_OUT` / `READ_UNREACHABLE`）、
`describeReadFailure`、`hostStateOf`、`hostStatusText`、`describeHostBanner`。

关键语义（这是本步真正要保的性质）：

- **`checking` 压倒一切**：任何一项读数未设置都算 `checking`；
- 超时/不可达 → `not_responding`；
- **被拒绝 → `ready`**（Host 回答了，所以它活着）；
- 选择器在 `rosterRead !== READ_OK` 时禁用，并且**给出明确解释**（而不是静默 disabled）；
- `send()`（写路径）**刻意不动** —— 不加超时。

### 第 3 步 bis —— 用真实冷启动数字重校读预算（owner 在 pre-commit verdict 中提出）

第 3 步最初给两个读都用了同一个 5 s 预算，**因为当时没有真实冷路径数字**。
后来启动器 smoke 拿到了真实数据：

```text
/agents                14 ms
/league/leaderboard
  cold                  3.0 s
  warm                  ~1.0 s
```

leaderboard 已从「产品不可用」修成「可用」，但 **5 s 也只剩约 2 秒冷启动裕量**。
而吃掉这点裕量的东西在同一台开发机上都是**寻常而非异常**：
Windows Defender/火绒的实时扫描、更冷的 SQLite 文件缓存、后台编译/IO、笔记本省电模式。

因此改为**分档**，而不是继续优化 SQL（owner 明确：3 s cold / 1 s warm 对第一版已经够用，
不要再追求 <500 ms；以后 UX 真觉得慢再做缓存/增量）：

```js
readJson("/agents", 5000)                 // 普通首屏读
readJson("/league/leaderboard", 10000)    // 聚合读，取真实冷启动裕量
```

同时把 `describeReadFailure(reason, timeoutMs)` 改成**接收实际预算** ——
超时文案必须报出真正流逝的那个预算（10 s 读超时不能写成「5 秒没回应」），
否则面板就在谎报自己为何放弃。

**这条修正自身的负向对照（写了两次才咬合）**：

- 对照 A：把 `LEADERBOARD_READ_TIMEOUT_MS` 退回 5000 → 新 gate 失败（可）；
- 对照 B：只把页面改回 `describeReadFailure(reason)`（默认预算）→ **gate 竟然全过**。

对照 B 不过说明**我最初写的 gate 太弱**：它只钉了 `readJson` 的预算，
没钉住**报错文案用的预算**，于是「读用 10 s、文案写 5 s」这个谎报会漏过去。
补齐断言（要求页面把同一档预算同时穿给读与 `describeReadFailure`）后，对照 B 如实失败。

> **教训：一条 gate 要同时钉住「行为用的参数」和「描述行为的文本用的参数」——
> 否则参数被复制成两份时，两份可以不一致而无人发现。**
> 这也是一条负向对照没有失败时应当先怀疑 gate、而不是先怀疑代码的实例。

`page.tsx`：`readJson(path, timeoutMs)` 用 `AbortController`，拒绝被标为 `readKind = READ_REFUSED`；
状态模型拆成 `rosterRead`/`rosterMessage` 与 `leagueRead`/`leagueMessage`，两路独立。

### 第 3 步 ter —— 修掉 checking 首屏的「被拒绝」横幅（owner 终审 P1）

owner 对 `06f949b` 的终审：`REPAIR_REQUIRED`（P0=0 / P1=1 / P2=1），
主体（backend/SQL/socket/launcher）**PASS**，但首屏仍有一个 truthfulness 缺陷。

**缺陷**：roster banner 写成 `rosterRead === READ_OK ? null : describeHostBanner(...)`，
而初始态是 `HOST_CHECKING`。`describeHostBanner` 只认识 `READ_TIMED_OUT`/
`READ_UNREACHABLE`，**其它全部落到默认的 refusal 分支**，于是在首屏同时渲染：

```text
Checking Studio Host…
[error banner] The request was refused: .
Loading the agent roster from the Studio Host…
```

**修复前已先复现**（不靠推断）：
`describeHostBanner(HOST_CHECKING, "")` → `"The request was refused: ."`
——连那个空 message 导致的末尾 `: .` 都一模一样。

**修法**（owner 指定，不扩展模型）：页面只在**已落定失败**时创建 banner；
pending 与 success 都是「无可报告」。
让 `describeHostBanner(HOST_CHECKING)` 返回一个假 banner 的方案被否决 ——
那个函数的职责就是描述失败。

**这条与 `ready` 是同一个错误的两个方向**：先前是「未确认就宣布就绪」，
这次是「未确认就宣布失败」——两者都是**未被证据支持的关于 Host 的断言**。

### 第 3 步 quater —— `LEADERBOARD_SQL` 的公共面（owner 登记 P2 deferred）

owner 指出：`pub const LEADERBOARD_SQL` + 在 `lib.rs` 再导出，
是一个**纯粹为了 integration test 而新增的生产 public surface**，
与之前收过的那些测试逃生口同性质：查询不是消费者应该依赖的 API，
未来换 SQL shape 也不应该形成兼容义务。

**登记为 `P2 deferred — test-driven public surface`**：以后整理测试时把
`LEADERBOARD_SQL` 收回 `pub(crate)`，并把 scale gate 搬进 crate 内部的
`#[cfg(test)]` 模块。**本轮不为了这个搬 365 行测试制造 churn**
（owner 明确：不影响玩家路径正确性，不拿它阻 walkthrough）。

### 第 4 步 —— 中型 fixture 回归门

新增 `crates/splendor-studio-league/tests/leaderboard_scale.rs`，四条：

1. **代价不随参与者数增长**：在 4 人与 16 人的同一 fixture 上分别 `EXPLAIN`，
   要求对 `match_seats` 的访问次数**相同**（旧形状会随参与者增长），
   并额外断言计划中不含 `CORRELATED SCALAR SUBQUERY`；
2. **与参照查询逐字段等价**：把替换前的生产 SQL 原样保留为 `REFERENCE_SQL`，
   在同一 fixture 上比对全部字段；fixture 覆盖**已决**、**和局**（两个 `won = 1`）、
   **结算但不可评级**（recorded 计、rated 不计）三类分支，并断言这些分支真的被走到
   —— 否则「相等」只是关于空集的相等；
3. **派生行仍与原始查询一致**：`rated_losses`、`provisional` 与排序仍由 Rust 派生；
4. **宽松时限**：数量级高于实测值，只拦「灾难性」而不是校准毫秒。

**这条门在写作过程中就抓到了我自己的两个错误假设**（这正是它有效的证据）：
`current_elo` 是 REAL 而非整数；以及把「扫描次数 ≤ 1」写死是错的表述 ——
固定两次（recorded 一次、rated 一次）与参与者数无关才是真性质，于是改成**两种规模的对比**。

### 第 5 步 —— 启动器（含一次安全事故与口径收窄）

**第一版启动器被火绒（Huorong）查杀。** 这是本轮必须记录的事实：

| 检出名 | 路径 | 触发时机 |
|--------|------|----------|
| `Trojan/Veil.a` | `Start Splendor Studio.cmd` | 执行时 |
| `HEUR:TrojanDownloader/PS.NetLoader.ae` | `E:\tmp\launcher-start.ps1` | `-ExecutionPolicy Bypass -File` |

**自审结论：不是病毒，是启发式误报。** 判断依据是一个干净的对照：**旧版**启动器调用了 5 次
PowerShell，跑了几个月从未报毒；我新增的组合恰好凑齐了 loader/dropper 的行为特征：

1. `-WindowStyle Hidden`（隐藏执行）；
2. `-PassThru` 取 PID + `Set-Content` 写盘（dropper 的典型落地动作）；
3. `Invoke-WebRequest`/`Invoke-RestMethod` 与「启动可执行文件」出现在**同一个脚本**里
   （下载器形态；我这里其实只是在探测 localhost）；
4. `-ExecutionPolicy Bypass -File <临时目录>\*.ps1`（NetLoader 的标志性组合）；
5. `(Get-Command npm.cmd).Source`（运行时解析可执行路径再启动 ≈ 动态构造命令）。

> **教训：写启动脚本要避免「隐藏启动 + 取句柄写盘 + 网络动词 + 临时目录 + Bypass」这一组
> 同时出现的形态 —— 即使意图完全正当。** 启发式按行为打分，不看意图。

**后果**：`Start Splendor Studio.cmd` 被火绒独占锁住（`HipsDaemon` 持有）。
它是**已跟踪文件**，HEAD 版本完好（`git show HEAD:"Start Splendor Studio.cmd"` 可读），
改动没有丢失。

**处置（不再尝试恢复）**：火绒的隔离区无法恢复（只会提供「复制副本」），且驱动级句柄在关闭
实时监控后仍然存在（`HipsDaemon`/`HipsTray`/`HipsMain` 三个进程都在跑）——
该路径在本次开机期间已完全不可写。

**最终仓库收口（index-only，不碰被锁文件）**：

```text
D  Start Splendor Studio.cmd
A  Splendor Studio.cmd
```

也就是让这次提交在**仓库语义上**直接完成替换：
旧路径从 index 删除，`Splendor Studio.cmd` 成为仓库里**唯一的** launcher。
全程**没有读取、写入、移动或删除**那个被锁的工作区文件。
本机残留的旧实体作为 **local-only artifact** 处理（写入 `.git/info/exclude`）；
重启后删掉残留、再删掉 exclude 项。

**为何不用 `git update-index --assume-unchanged`（已被 owner 否决）**：
它只是让 Git 「先别看这个 tracked 文件」，**不等于工作树干净**，
而且这个位会长期留在 clone 里，未来真正修改/拉取该文件时非常容易坑人。
更严重的是，若只把新 launcher 加进去而不删除旧路径，
**别人新 clone 后会看到两个启动器**（旧的还是 hidden 语义）——那不应成为仓库正式状态。
所以本轮把 `assume-unchanged` 撤销，改用 index-only 删除。

**取舍已如实记录**：**本机**仍存在一个被锁的旧实体（无仓库语义、且已被 exclude），
重启后清理；这是安全软件事件的后果，不是设计意图。

**新版启动器已做真实验烟**（与双击相同的命令形式，经 `cmd /k` 启动）：
Host 就绪 **1 s**；`/health` 22 ms；`/agents` 14 ms；
**`/league/leaderboard` 冷请求 3,002 ms**（35,514 B）、热请求 **976–1,065 ms**；
返回 **100 行**，榜首 `splendor.exe:agent-s3-rollout` Elo 1940 / W-T-L 289-0-101 /
recorded 391；停掉进程后端口立即关闭（即“关窗口就是停止”）。

**证据上限（不得写成“不会再被查杀”）：** 本轮能证明的是
**「新版启动器已移除本次误报期间新增的高风险脚本形态（隐藏执行 + 取句柄写盘 + 网络动词
+ 临时目录 + Bypass），且其实际启动命令已通过 smoke」**。
因为 sandbox 里**没有直接双击执行这份 `.cmd` 文件**，所以**不声明「火绒一定不会再次检出」** ——
那是一个尚未取得的观测，不是可以写进里程碑的事实。

**收窄后的设计**（已落盘为 `Splendor Studio.cmd`）：

```bat
start "Splendor Studio Host" /D "%~dp0" cmd /k ^
  cargo run -p splendor-cli --bin splendor -- studio-host ^
  --registry benchmarks/studio-1v1.registry.json ^
  --reviewer-registry benchmarks/studio-reviewers.registry.json ^
  --port 43120 --project-root .

start "Splendor Replay Studio" /D "%~dp0apps\replay-studio" cmd /k ^
  npm run dev -- --host 127.0.0.1 --port 4173

timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:4173/league"
```

设计要点：**用 `start` 的 `/D` 开关给工作目录**，而不是在 `cmd /k "..."` 里嵌套
`cd /d "..."` —— 后者的嵌套引号是 CMD 的经典坑。保留的三件小事是必需的而不是管理性质的：
registry 存在性检查、`cargo build -p splendor-cli`、`node_modules` 缺失时 `npm install`。

## Final implementation（最终实现）

改动文件（7 个跟踪文件 + 1 个新文件）：

- `crates/splendor-studio-league/src/ledger.rs`：`LEADERBOARD_SQL` 常量 + 集合式聚合；
- `crates/splendor-studio-league/src/lib.rs`：再导出 `LEADERBOARD_SQL`；
- `crates/splendor-studio-league/tests/leaderboard_scale.rs`（新）：4 条真实规模门；
- `crates/splendor-cli/src/human_play_command.rs`：`prepare_connection` + 两个 accept 循环；
- `crates/splendor-cli/tests/league_host_api.rs`：新增 liveness gate（`http_get_within` 重构）；
- `apps/replay-studio/app/league-runtime.mjs`：三态 + 读四态 + 分类函数；
- `apps/replay-studio/app/league/page.tsx`：`AbortController` 读超时、两路独立状态、选择器解释；
- `apps/replay-studio/tests/{league-runtime,rendered-html}.test.mjs`：+5 就绪测试 + SSR 断言。

## Validation and evidence（验证与证据）

本地证据（本仓库无 CI；不声称云端状态检查）：

| 套件 | 结果 |
|------|------|
| `cargo test -p splendor-studio-league` | **90 passed / 0 failed**（含新门 4 条） |
| `cargo test -p splendor-cli` | **288 passed / 0 failed / 3 ignored**（45 targets；+1 = socket liveness gate） |
| `league_host_api` | **15** 条 gate（14 + 1） |
| `apps/replay-studio/npm test` | **73/73**（+5 就绪 +1 读预算裕量 +1 SSR 首屏真相） |
| lint | clean（8 条 `tsc` 错误是既有的、在未改动的 `experiments/page.tsx` 与 `review/page.tsx`） |

**修复后现场复验**（真实 42k 库）：

- `/health` 4.5 ms / 1.7 ms；`/league/leaderboard` **200，1.1 s**（修复前：永不返回、
  单核 100%、整个 Host 死掉）；
- 空闲连接存在时：`/health` 0.41 s 200、`/agents` 2 ms、`/league/leaderboard` 1.14 s，
  之后 Host 仍正常服务；
- 页面 SSR：`/league` 含 **`Checking Studio Host` ×1**、**`Studio Host ready` ×0**、
  `Loading the agent roster` ×1、`Loading the standings` ×1。
- **首屏真相（P1 修复后，直接读真实渲染输出，非源码正则）**：
  `Checking Studio Host…` ✓ / `Loading the agent roster…` ✓ /
  **`The request was refused` ✗（已消失）** / **`error-banner` ✗（已消失）**。
  修复前这两项都是 ✓，即那个自相矛盾的首屏。

**负向对照 1（已完成并还原）**：把生产 SQL 换回旧的相关子查询版本 ——
`scale_gate_the_production_plan_does_not_follow_the_participant_count` 失败，
失败信息正是 `CORRELATED SCALAR SUBQUERY × 6`；而**语义等价测试仍然通过**。
这恰好证明了这条门的价值：旧查询**算得对，但计划病态**。

**负向对照 2（已完成并还原）**：把 `prepare_connection` 改成 no-op（即本轮之前的状态）——
只有 `gate_silent_connection_cannot_starve_the_host` 失败，其余 14 条全过，
失败点是「空闲对端存在时 Host 必须在界内回答 `/health`」，
且整轮耗时从 2.64 s 涨到 **11.54 s** —— 正是「卡死」在时间上的样子。

**负向对照 3（已完成并还原）**：删掉 `hostStateOf` 里「checking 压倒一切」那一支 ——
`G1 readiness: checking is never reported as ready` 失败，
且失败信息就是原始缺陷本身：`actual: 'ready'` / `expected: 'checking'`。

三条对照各自只打中它自己的门（其余 gate 全部仍然通过），说明它们是精确的。
三条的还原方式均为 `cp` 自 **patched state** 的备份，并用 `diff -q` 确认逐字节相同
（上一轮的教训：对照的还原目标必须是被打补丁之后的状态，否则「还原过了头」与
「对照从未还原」不可区分）。

## Result and decision（结果与决定）

- **三处代码修复**：`IMPLEMENTED` / `VERIFIED`（本地）。查询有真实库的前后实测与逐字段比对；
  socket 有受控实验与 gate；页面有单测 + SSR 断言。**三条负向对照均已执行、各自打中自己的门、
  并从 patched state 逐字节还原。**
- **owner 的手工走查**：仍是本轮唯一能提供的验收证据，且**尚未执行**。
  修复前它**在第 2 步被阻塞**（真实规模 leaderboard 延迟 + Host 活性缺陷被发现），
  走查因此中止。**owner 指示：收掉首屏真相的 P1 后再从第 1 步重走。**
- **启动器**：第一版被安全软件查杀并锁定（见上）；收窄版已落盘为 **`Splendor Studio.cmd`**
  并做了真实验烟（cold 3.0 s / warm 1.0 s 读完整 42k 榜单，100 行）。
  **仓库收口为 `D Start Splendor Studio.cmd` + `A Splendor Studio.cmd`**（index-only，不碰被锁文件），
  新 clone 只会看到一个 launcher。本机残留实体已 exclude，无仓库语义。
- **新增跟踪文件**：本里程碑文档 + `crates/splendor-studio-league/tests/leaderboard_scale.rs`
  + `Splendor Studio.cmd`（并删除 `Start Splendor Studio.cmd`）。

## Known limitations（已知限制）

1. **串行 accept 仍在**：一个真正在跑的慢请求仍会阻塞其它请求。本轮只消灭了两个已被证明的
   异常源；把 `/health` 挪到独立线程被 owner 明确排除。
2. **没有浏览器 runner**：没有 gate 证明玩家点过任何东西；结果的可见渲染仍只由人工走查覆盖。
3. **性能门不是基准**：它断言的是**计划性质**（代价不随参与者数增长）与语义等价，
   加上一个数量级宽松的时限；它**不**冻结任何机器的毫秒值。
4. **未加索引**：`match_seats(participant_id)` 仍不存在。1.1 s 已被接受；若未来规模再涨，
   应先重新测量再决定。
5. **启动器无生命周期管理**（这是设计，不是缺陷）：进程随窗口关闭而结束，
   不记录 PID、不提供 stop 脚本。端口被占时由终端直接显示错误。
6. **本机残留一个被锁的旧启动器实体**（已从 index 删除、已 exclude，**无仓库语义**）；
   重启后应删除并把启动器名归一。新 clone 的人只会看到一个 launcher。
7. **`/league` 的读预算分两档**：普通首屏读 5 s，**leaderboard 10 s**（取真实冷启动 3 s 的裕量）；
   写路径**没有**任何 UI 超时（刻意）。
8. **D6 的 participant-id join 仍未做**，选择器仍不显示 Elo。
9. **`P2 deferred — test-driven public surface`**：`LEADERBOARD_SQL` 是一个纯粹为
   integration test 新增的生产公共面（且被 re-export 到 crate root）。
   它**不影响玩家路径正确性**，故不阻本轮；以后整理测试时收回 `pub(crate)`
   并把 scale gate 搬进 `#[cfg(test)]` 模块。

## Next authorized gate（下一道授权门）

1. owner 复审本 repair commit；
2. **从第 1 步重新执行 8 步手工走查** —— 第 8 步（在回放棋盘里实际拖动、逐手走过各 ply）
   仍是本轮无法自动化的那份验收证据；
3. 走查通过后，在 `docs/studio-league-v1.md` 与 `handoff.md` 记录关闭；
4. 重启后清理本机残留：删除被安全软件锁住的旧 `Start Splendor Studio.cmd` 实体，
   并从 `.git/info/exclude` 移除对应条目（旧路径已不在 index 里，**无需**任何 Git 命令）。
