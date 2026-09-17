# Human Live League Integration v1 — 冻结设计 / Evidence Contract

- **Status**: `DESIGNED` / `AUTHORIZED`（设计冻结；**Slice A 已 IMPLEMENTED / VERIFIED 本地，待 owner 复审**；D1–D9 与验收数字冻结）
  - **设计复审**：`f6909c3` — `DESIGN_REPAIR_REQUIRED`（P0=0 / P1=3 / P2=1；主架构 ACCEPTED）。
    本文件即 **Design Repair 1** 落点：P1-1 retry 语义收窄（canonical-tail）、P1-2 冻结
    `source_document_hash` 映射、P1-3 `expected_session_id` 绑定上移到 orchestration 层、
    P2-1 handshake provenance 拆分 producer/completion 两层。详见「Iteration log」。
  - Slice A **已 IMPLEMENTED / VERIFIED（本地）**，见「Iteration log」；Slice B / C 仍未授权。
- **Baseline**: `dba11dd`（`main == origin/main`，工作树干净）。前一轮
  League Play Page v1 / Real-Scale Walkthrough Repair 已 `ACCEPTED / CLOSED`
  （`38292a1` 裁决 + `dba11dd` 关闭记录）。
- **Recon**: `ACCEPTED`（见文末「Recon 回执」；owner 在 Recon 之上做了两处修正，已并入 D4 与 D2）
- **Owner-date**: 2026-09-16，product owner。
- **Round type**: product milestone（人类主权 Elo 的第一个产品纵切），不是棋力研究。

---

## Problem and evidence

上一轮关闭时留下的、由真实数据库证明的 starting state：

```text
participants
  participant_id = b901a2ea-645d-4c45-b4b9-407f5b6f39b7
  kind           = human
  display_name   = You
  current_elo    = NULL

该 participant 的 match_seats   = 0
该 participant 的 rating_events = 0
```

同时 Agent-vs-Agent 天梯已经真实运行：全库 `42,522` 场比赛 / `28,012` 条 Elo 事件
（`58d35011…` 那场是走查验收的落盘证据）。

也就是说：**人类身份模型已经持久化（`identity.json` + `identity_manifest`），但
"人类亲自下场打一盘排位"这条链从未存在。** `/play` 的终局今天只有：

```text
ReplayV1
human meta { session_id, opponent(display label), human_seat }
```

然后写进 `local-artifacts/m20-human-play/`。没有 ArenaReport，没有 Arena match-config。

**本轮最重要的边界**：绝不为接 League 而伪造 ArenaReport / ArenaConfig / 任何
"看起来像 Arena" 的证据。

---

## Initial design（owner 冻结的 D1–D9）

### D1 · Product scope

只接这一条链：

```text
Studio Host browser /play
+ registered agent
+ local human profile
→ rated Studio League match
```

- console `human-play --opponent s3/heuristic/m07`（`Opponent::InProcess`）**继续保持
  standalone / casual**，绝不因为共用 `Session` 就自动入 League。
- 现有 `/play` HTTP 本身就只能选 registry agent（`NewGameRequest{agent_id, human_seat, seed}`，
  `new_game()` 校验 `agent_id ∈ registry`），因此**不需要** Rated/Casual toggle。
- 开局前页面明确显示：

```text
Rated Studio League match
Your Elo may change.
```

### D2 · Freeze identity at game start（含 owner 对 Recon 的修正 2）

`POST /games` 请求体**保持原样**：

```text
agent_id
human_seat
seed
```

**不新增**：`participant_id` / `policy_key` / `runtime_name` / `command`。
这些一律不能由浏览器提供。

Host 创建 session 时完成两件事：

```text
identity.json
→ validate
→ local_human = { participant_id, display_name }
→ manifest_hash

Host 内存中的 RatingRegistryV1
→ selected RatedAgentV1
→ shared policy resolver(program, args)
→ Resolved(policy_key)
```

**Degradation 分成两个不同故障，不可混为一谈（owner 修正）：**

```text
identity authority valid
+ opponent identity/policy valid
+ league DB / completion unavailable
→ 允许开局；终局后 durable pending，可重试     （"记账系统暂时不可用"）

identity authority invalid / missing
OR opponent policy unresolved
→ rated game 在开始前 fail closed，不创建 session（"连这盘属于谁都无法证明"）
```

**TOCTOU 修正（Recon Q1 判断成立）**：`build_registered_session()` 今天仍把
`registry_path + agent_id` 传进 `RegisteredOpponent::start()` 再去磁盘重读 registry。
本刀改为：

```text
Host 选择并 clone 已验证 registry entry
→ RegisteredOpponent::start(selected entry)
→ handshake
→ Session 保留这份 frozen opponent evidence
```

### D3 · Occurrence ID == Session ID

```text
occurrence_id == session_id == human-<seed>-<human_seat>-<pid>-<session_number>
```

不再生成第二个 ID。Ledger：

```text
source_kind     = "human_play"
source_identity = "runtime:<session_id>"
```

**不要**写 `runtime:human:<session_id>`：session id 本身已是 `human-*`，
`source_kind=human_play` 提供生产者 namespace，额外套层没有信息增益。
保留 `runtime:` 前缀是为了继续使用现有 live-occurrence 的 canonical-tail 约束。

### D4 · HumanRuntimeOccurrenceV1（格式冻结，含 owner 对 Recon 的修正 1）

新 durable envelope 属于 `splendor-studio-league`，不是 CLI 私有 JSON。

```text
format  = effective-splendor-human-runtime-occurrence
version = 1

occurrence_id
completed_at
seed
human_seat
replay_sha256

human:
  participant_id
  display_name
  identity_manifest_hash

opponent:
  registry_id
  agent_id
  display_name
  runtime_name
  runtime_version
  program
  args
  policy_key
```

字段来源约束：

- `participant_id / display_name / manifest_hash` ← 开局时已验证的 identity manifest；
- `runtime_name / runtime_version` ← **成功握手所验证的** registry entry；
- `program / args` ← 实际 selected registry command 的快照；
- `policy_key` ← 开局时 shared resolver 的结果；
- completion 时**必须用 raw `program/args` 重新解析一次，并要求结果 == envelope 中的
  `policy_key`**，使 durable evidence 以后不能被静默重新解释。
- `seed` ← 终局 verified `ReplayV1.seed`（不给 `Session` 加字段；当前 Session 确实不
  保存 seed，但终局一定持有并验证 replay）。

**Evidence hash** 沿用现有 runtime hash 原则（独立 domain separator + format/version +
全部 envelope 字段 + 固定顺序 + length-prefixed fields）。**不能只 hash replay。**
现有 Arena runtime 正是因为"同 occurrence id 下改了 replay/config/completed_at 也必须冲突"
才采用 complete-evidence hash（`runtime_occurrence_evidence_hash()`，
`historical_import.rs:409`，domain `RUNTIME_OCCURRENCE_EVIDENCE_DOMAIN`）。

**Shared resolver（owner 修正 1，否决"构造单座位假 match-config JSON"）**：

不把 Human producer 伪装成"有 Arena config"。把现有私有
`resolve_seat_identity()`（`agent_configuration.rs:164`）提炼为一个**真正共享的
production resolver**：

```text
resolve_policy_identity(program, args) -> SeatConfigurationIdentityV1
```

让 Arena config parser 与 Human producer 走同一份 `program + args → policy identity`
规则（同一 `classify_switch()` 冻结词表、同一 fail-closed 语义）。
Current policy key 的真正逻辑只存在于这一处。

### D5 · Durable evidence 放现有 League occurrence root

```text
StudioLeaguePathsV1::occurrence_dir(session_id)   # paths.rs:176
```

它本来就是 per-occurrence evidence slot，**不是 Arena 专属目录**。

```text
Human slot:  <occurrence_dir>/replay.json + <occurrence_dir>/occurrence.json
Arena slot:  config.json + replay.json + report.json + occurrence.json
```

**共享 occurrence 根，分 schema 与 evidence set。**

CLI 侧新增自己的 `HumanOccurrenceEvidence` / `HumanOccurrenceSlot`，只认识三态：

```text
Empty
Complete(replay + valid human occurrence)
Ambiguous
```

**不复用**现有 Arena `OccurrenceEvidence` 四文件类型——那个类型与 slot classifier
明确假设 `config/report/replay/occurrence` 四件套。

附带 fail-closed 性质：Arena 路径若误开 human slot，会看到"缺 config/report 的
partial evidence"而拒绝，不可能把它当 Arena occurrence。

### D6 · Completion Outlet 向下抽通用尾段

现状：

```text
complete_runtime_occurrence()
  runtime_match_record → archive_replay → bind_archived_replay → ingest_match → match_receipt
```

冻结为：

```text
complete_runtime_occurrence()
    → runtime_match_record()        # Arena-specific
    → complete_verified_record()    # private generic tail

complete_human_runtime_occurrence()
    → human_runtime_match_record()  # Human-specific
    → complete_verified_record()    # same private tail
```

- `complete_verified_record()` 必须 crate-private/private；
- 不导出 `rusqlite::Connection`；
- 不让 caller 选择 replay archive root（root 仍来自 opaque `CompletionLeagueV1`）；
- 不允许外部直接塞一个构造好的 `StudioMatchRecordV1`。

对外 API：

```rust
pub fn complete_human_runtime_occurrence(
    league: &mut CompletionLeagueV1,
    request: &HumanCompletionRequestV1<'_>,
) -> Result<CompletionOutcomeV1>
```

request 只能携带 Human occurrence evidence + replay bytes。

### D7 · Human builder 的 fail-closed 校验清单

`human_runtime_match_record()` 的校验按**职责层**拆成两栏（P2）：

**Producer-time invariants**（开局定证据；completion 无法也不应重证）：

```text
RegisteredOpponent::start() 必须先通过握手校验：
  agent_name    == selected.runtime_name
  agent_version == selected.runtime_version
只有握手成功后，Session 才保存 frozen opponent evidence，
并允许终局生成 HumanRuntimeOccurrenceV1。
```

**Completion-time re-verifiable invariants**（仅凭磁盘 occurrence + replay 即可重证）
逐项 fail closed：

```text
human occurrence format/version 正确
replay bytes SHA == occurrence.replay_sha256
verify_replay(replay) PASS
replay.player_count == 2
replay.seed == occurrence.seed
human_seat ∈ {0,1}
replay 是合法 terminal game

occurrence.human.participant_id
    == CompletionLeagueV1 内 local_human_participant()
occurrence.human.identity_manifest_hash
    == 当前 league 的 stored identity manifest hash

resolve_policy_identity(program, args)
    == occurrence.opponent.policy_key

opponent runtime_name / runtime_version 非空
occurrence evidence hash 自洽
```

訁诚实边界（P2 明写）：完成侧只剩 `occurrence.json + replay.json`，**不可能重新证明**
“runtime_name/version 真的来自一次成功握手”——没有 handshake transcript。
Completion **不**重新读 registry、**不**重新握手；“来自成功握手”是受信 Host producer
对 occurrence envelope 的 durable attestation。这与 Arena 路径的信任模型一致。

> `occurrence_id == expected session id` **不在**本清单：builder 拿不到 requested id。
> 该绑定属于 orchestration 层，见 D8「persisted-evidence orchestration 绑定」。

两个 seat：

```text
Human seat:  participant_id = Some(local human UUID)
             identity       = None
             display_name   = occurrence human display name

Engine seat: participant_id  = None
             identity        = Some(runtime_name / runtime_version)
             policy_identity = Resolved(policy_key)
             display_name    = registered display name
```

Ledger 天然支持这种混合：显式 `participant_id` 优先（Human），engine 走 exact
policy key 解析（`ledger.rs:426-449`）。**不改 participant model，不给 Human 伪造
EngineIdentity。**

Record（P1-2 冻结，**全部强制**）：

```text
source_kind          = "human_play"
source_identity      = "runtime:<session_id>"
source_document_hash = human_runtime_occurrence_evidence_hash(occurrence)
played_at            = occurrence.completed_at
status               = completed
diagnostic           = false
```

ReplayBinding 同时冻结：

```text
document_hash = occurrence.replay_sha256
final_hash    = verified ReplayV1 final-state hash
verification  = Verified
```

随后 generic tail（`complete_verified_record()`）只负责 archive + bind archived
path / storage。

`source_document_hash` 必须是**整个 occurrence envelope 的 complete-evidence hash**
（与新函数 `human_runtime_occurrence_evidence_hash()`——Slice A 内实现，冻结命名——
与现有 runtime 路径同原则），**不是** replay 的 SHA-256。理由与 Arena 路径相同：
同一 occurrence id 下换 replay / completed_at / 对手证据必须表现为 Conflict，
不能被吞成 AlreadyPresent。**不允许实现者临场改用 replay sha。**

score / rank / won 全部来自 verified ReplayV1 terminal result。

### D8 · 终局顺序与 Retry

原有人机产物**必须继续存在**（现有 `/play` recent games / replay / reviews 都依赖）：

```text
local-artifacts/m20-human-play/
  <session>.replay.json
  <session>.meta.json
```

终局顺序：

```text
Replay terminal + verify
↓
原有 human replay/meta 持久化
↓
publish Human occurrence evidence
    replay.json
    occurrence.json LAST（作为 commit marker）
↓
re-read durable evidence from disk
↓
complete_human_runtime_occurrence()
```

沿用 Agent producer 最重要的纪律：

> **Completion 永远从刚 durable 的磁盘 evidence 重读，而不是拿内存里的
> "我觉得刚才发生了什么"。**

现有 Agent orchestration 正是靠这一点保证 retry 不 rerun
（`complete_persisted_occurrence()`）。

失败态（P1-1 收窄后的精确语义）：

```text
durable completion failure
→ evidence survives
→ game NEVER reruns
→ retry MAY be attempted

但 retryable ≠ guaranteed eventual insertion。
```

Retry：

```text
POST /games/<session_id>/league-completion     # body 为空
```

只能：

```text
找到该 session 的 Human occurrence slot
→ 重读 occurrence + replay
→ verify
→ offer completion
```

**绝不能重跑游戏，也不能从 HTTP body 接收新 result / participant / seed / evidence。**

幂等与冲突：

```text
同一 evidence 第二次 offer → AlreadyPresent，0 new rating events
同一 occurrence_id + 改变过的 evidence → Conflict
```

**Persisted-evidence orchestration 绑定（P1-3）**：

Slice B / CLI orchestration 镜像 Arena 的现有分层：

```text
complete_persisted_human_occurrence(evidence, paths, expected_session_id)
  → 解析 occurrence.json
  → occurrence.occurrence_id != expected_session_id ⇒ Conflict
  → 通过后才调用 complete_human_runtime_occurrence(occurrence, replay_bytes)
```

`complete_human_runtime_occurrence()` 不接收、也不需要 `expected_session_id`：
completion crate 不认识 HTTP route。理由与 Arena 一致（`complete_persisted_occurrence()`
的同名检查）：**内部自洽不等于“它就是你请求的那个 occurrence”**——这个分层挡住
“把 B 的 slot 里自洽的 occurrence 挪进 A 的目录、A 的 route 也接受”。

**Canonical-tail（P1-1，必须如实暴露给 UI）**：

ledger 对所有 `runtime:` occurrence 强制 canonical-tail guard（`ledger.rs:343-384`）：
incoming key `(played_at, source_kind, source_identity)` 不晚于当前 tail 时**拒绝插入**，
报错原文即 “rebuild the derived database from the occurrence evidence”——
它**不会**靠反复 Retry 收敛成 Inserted，而是需要 canonical rebuild。

现实序列：

```text
t1: Human A 完赛，evidence durable，DB 暂时失败，未入账
t2: 另一场 runtime match 完赛并入账
retry A → A.played_at 早于 ledger tail → canonical-tail rejection
```

此时（D9 的 `retryable: true | false` 本就覆盖，UI schema 不扩）：

```text
league_completion.status    = failed
league_completion.retryable = false
league_completion.error     = canonical order / rebuild required
```

v1 **不**为消灭该 limitation 改 ledger 支持中插，也不实现自动 rebuild。

（`IngestOutcome::{Inserted{rating_events}, AlreadyPresent{match_id}}`，`ledger.rs:158`）

### D9 · HTTP / UI 两事实模型

`HumanSessionState` 增加可选字段 `league_completion`（非终局可为 `null`）：

```text
league_completion:
  status    = inserted | already_present | failed
  retryable = true | false
  receipt   = ...
  error     = ...
```

`result`（人机局结果）与 `league_completion`（入账结果）**仍是两个事实**。
必须允许这种渲染：

```text
VICTORY

League booking pending
The match is finished and its evidence is saved.
Retry booking
```

**绝不能写成 `match failed`**——League DB 锁住不会把打完的人机局变回"没发生"。

UI 只改 `/play`：开局区固定 Rated 提示；终局区在原有 Victory/Defeat、Replay、Review
下方增加 Elo/booking 区。**不改 `/league` Agent-v-Agent 页面。**

---

## Iteration log

- **Design Repair 1（docs-only）**：owner 对 `f6909c3` 裁
  `DESIGN_REPAIR_REQUIRED`（P0=0 / P1=3 / P2=1，主架构 ACCEPTED，Slice A 暂缓）。
  本版仅修订文档，未动 D1–D6 主架构、未动代码：
  - **P1-1**（最重要）：durable pending 的 retry 语义收窄 —— evidence 存活、对局永不重跑、
    retry 可以尝试，但 **retryable ≠ 保证最终插入**。撞 ledger canonical-tail guard
    （`ledger.rs:343-384`，生产代码事实）时收敛为
    `status=failed / retryable=false / error=canonical order / rebuild required`。
    D9 的 `retryable` 布尔已够用，UI schema 不扩。v1 不为消灭此 limitation 去改 ledger
    支持中插、不做自动 rebuild。新增负向 Gate H。
  - **P1-2**：D7 Record 合同补死 `source_document_hash =
    human_runtime_occurrence_evidence_hash(occurrence)`（沿用 runtime 路径
    `runtime_occurrence_evidence_hash()` 先例，`historical_import.rs:293/409`）并冻结
    ReplayBinding 三项；禁止临场改用 replay sha。
  - **P1-3**：`occurrence_id == requested/session id` 从 Slice A builder 清单移到
    orchestration 合同 `complete_persisted_human_occurrence(..., expected_session_id)`
    （镜像 Arena `complete_persisted_occurrence()` 的同一分层，
    `runtime_orchestration.rs:300-327`）；Slice A 的 completion crate 不认识 HTTP route。
  - **P2**：D7 把 handshake provenance 拆成 producer-time invariants 与
    completion-time re-verifiable invariants；明确 completion 不重读 registry、不重新握手，
    “来自成功握手”是 Host producer 对 envelope 的 durable attestation。
  - **裁决**：`e081d55 — DESIGN ACCEPTED`；`Slice A AUTHORIZED`（P0=0 / P1=0）。

- **Slice A（当前版本，IMPLEMENTED / VERIFIED 本地）**：按 owner 划定范围只做
  completion/evidence 四件，未碰 Host producer / 磁盘 retry / UI / 路由：
  - **A1 共享 resolver**：`agent_configuration.rs` 新增 **公共**
    `resolve_policy_identity(program, args)`，把原私有 `resolve_seat_identity()` 的全部逻辑
    搬过去（同一 `classify_switch()` 词表、同一 fail-closed 语义、program 仍归约为末段），
    `parse_match_configuration()` 改为**委派**它。**未造任何 synthetic Arena config**。
    回归门 `the_shared_resolver_matches_the_arena_parser_for_every_command_shape`：对 8 种
    command 形状（含 `-m` 模块、`--runtime-name`、未分类 switch、无 entry point）
    断言两条路径产生**逐字段相等**的 `SeatConfigurationIdentityV1`。
  - **A2 Human occurrence**：新文件 `crates/splendor-studio-league/src/human_occurrence.rs`
    —— `HumanRuntimeOccurrenceV1`（format `effective-splendor-human-runtime-occurrence` v1）、
    `HumanOccurrenceHumanV1` / `HumanOccurrenceOpponentV1`、`parse_human_runtime_occurrence()`、
    `human_runtime_occurrence_evidence_hash()`（独立 domain separator + 固定顺序 +
    length-prefix，**覆盖全部字段**，包括 `args` 逐项与 `format`/`version`）、
    `human_runtime_match_record()`、`HumanCompletionContextV1`。本片**不含** filesystem
    slot / publish / retry（属 Slice B）。
  - **A3 builder fail-closed**：单一实现 `human_runtime_match_record()`，逐项拒收：
    replay SHA ≠ envelope、replay 严格验证失败、非 2 人局、seed ≠ envelope、
    human_seat ∉ {0,1}、无 winner、league 无 local human、human participant 不匹配、
    manifest hash 不匹配、opponent command 重解析后 policy key 不一致、command 不可归因。
    seat 形状：human = `participant_id Some(local human)` + `identity None` +
    `policy_identity NoConfigEvidence`；engine = `identity Some(runtime_name/version)` +
    `policy_identity Resolved(policy_key)` + `participant_id None`。**未改 participant model**。
  - **A4 通用尾段**：`completion.rs` 私有 `complete_verified_record(league, record, replay_bytes)`
    （archive → bind → `ingest_match` → `match_receipt`），`complete_runtime_occurrence()` 与
    新增 `complete_human_runtime_occurrence(league, &HumanCompletionRequestV1)` 都只做各自的
    verified-record builder 后调它。`HumanCompletionRequestV1` 只携带 envelope + replay bytes +
    provenance label；human participant / manifest hash **由 outlet 从 league 读出**，
    request 不能指定。`Connection` 仍未导出，archive root 仍来自 opaque session。
  - **验证（本地；无 cloud CI）**：`splendor-studio-league` **100 passed / 0 failed**
    （原 90，+2 resolver +8 human gates）；`splendor-cli` **288 passed / 0 failed / 3 ignored**
    （45 targets，**计数未变** ⇒ 旧 Arena completion 行为未变）；`rustfmt --edition 2021`
    五个改动文件全 OK；`git diff --check` clean。
  - **两组负向对照（均从**已打补丁**状态 `cp` 还原、`diff -q` 验证字节一致）**：
    ① 让 Arena 路径从共享 resolver **分叉** → 等价性门 + 6 条既有 resolver 门 FAIL（4 passed / 7 failed）；
    ② 让 human 路径把 `source_document_hash` 改成 replay sha（即丢掉 complete-evidence 身份）
    → `the_same_human_occurrence_is_idempotent_and_changed_evidence_conflicts` 与
    `a_rated_human_match_rates_both_seats_exactly_once` FAIL（6 passed / 2 failed）。
  - **未做（按 owner 划定）**：`human_play_command.rs` 终局 publish、`HumanOccurrenceEvidence`
    filesystem 类型、`HumanOccurrenceSlot`、retry 路由、`RegisteredOpponent` TOCTOU wiring、
    `HumanSessionState.league_completion`、`/play` UI、Host vertical gate、Gate H 编排 seam。
    （A1 的共享 resolver 已为 Slice B 的 `RegisteredOpponent` 冻结身份就绪，但 Session freezing 属 B。）

---

## Scope and non-goals

**In scope**：D1–D9 全部（shared resolver、Human occurrence/builder、generic completion
tail、Host producer/retry wiring、/play rated+result UI、targeted gates、本文档）。

**Non-goals（继续冻结，不许顺手碰）**：

```text
P2 LEADERBOARD_SQL 收回 pub(crate)
Replay 页面 P0/P1 名字显示
历史 human backfill（尤其不许把过去 m20-human-play 的局导进 League）
casual / rated mode 体系
Host concurrency / socket deadline
/league Agent-vs-Agent 路径
旧 42,522 场重新迁移
Review 系统
```

`You = 0 matches / 0 Elo` 是本刀**珍贵的 clean starting state**，历史回填会毁掉它。

---

## Contracts and invariants

1. 浏览器永远不能直接指定 participant / policy / runtime / command。
2. Human participant id 只来自 `identity.json` + league 的 local human 绑定。
3. Arena 与 Human 共用一个 `program+args → policy identity` resolver，不写第二套。
4. `source_identity` 保留 `runtime:` 前缀（live occurrence canonical-tail 约束）。
5. occurrence.json 最后写（commit marker）；completion 只从磁盘重读。
6. Retry 无 body、不重跑；AlreadyPresent 不产生新事件；改 evidence = Conflict。
7. Completion authority 不新增出口：archive root、ledger 写入、`ingest_match` 均不变。
8. 人机局结果与人账结果是两个事实，UI 不得互相冒充。

## Implementation plan（owner 授权的切片顺序）

```text
Slice A: shared policy resolver + Human occurrence/builder + generic completion tail
Slice B: Host durable producer / retry wiring
Slice C: /play result / rated UI + vertical acceptance
```

一个切片一个窄 commit；不把 UI、producer、completion 糊成一个巨型 commit。

预计最小文件范围（Recon 未发现反例）：

```text
crates/splendor-studio-league/src/agent_configuration.rs   # shared resolver 提炼
crates/splendor-studio-league/src/completion.rs            # 通用尾段 + human 入口
crates/splendor-studio-league/src/human_occurrence.rs      # 新 envelope / builder
crates/splendor-cli/src/human_play_command.rs              # Host session evidence + retry
crates/splendor-cli/src/runtime_orchestration.rs           # Human producer 纪律（新增类型）
apps/replay-studio/app/play/page.tsx                       # rated + result/booking UI
targeted tests
```

## Validation and evidence

### 自动 Gates（不搞第二个大测试工程，不生成 42k fixture，不需要 browser runner）

```text
A. shared policy resolver:
   Arena parser 与 direct program/args resolver 对同一 command 得到完全相同的 policy key

B. human builder:
   human seat = 0 / 1 都映射到同一个 manifest human participant；
   engine seat 映射到 frozen policy participant

C. rated ingest:
   1 match
   total rating_events +2
   human rating_events +1
   engine rating_events +1
   human current_elo NULL → Some(...)

D. identity fail-closed:
   missing / mismatched local human
   changed manifest hash
   unresolved engine policy
   都不能进入 rated ledger

E. retry:
   同一 durable occurrence offer 两次
   → 1 match / 2 events total，第二次 AlreadyPresent

F. collision:
   same occurrence_id + changed durable evidence → conflict

G. Host vertical gate:
   POST /games → play to terminal
   → old m20 replay/meta still exist
   → human occurrence slot exists
   → Studio League row exists
   → exact human UUID appears in match_seats

H. canonical-tail fail-closed（P1-1 负向；落 Slice B 或现有 ledger tests 均可）:
   older human occurrence durable
   → later runtime occurrence inserted
   → retry older human
   → fail closed（canonical-tail rejection）
   → 不产生重复 match 行、不产生新 rating events
```

### 最终人工验收数字（真实库，精确）

当前：

```text
You: match_seats = 0, rating_events = 0, current_elo = NULL
```

第一场真正 Human rated match 完成后必须精确变成：

```text
human match_seats:     0 → 1
human rating_events:   0 → 1
total matches:         +1
total rating_events:   +2
human current_elo:     NULL → real Elo
```

**表述更正（owner 明确）**：之前"产生属于你的首批 2 条 Elo 事件"是错的。
一盘 1v1 是 **Human 自己 +1、Opponent +1、全局 +2**；ledger 强制 eligible 1v1
exactly 2 events。

人工还要确认：

```text
/play 开局前明确 Rated
→ 真人完整打一盘
→ Victory / Defeat 正常
→ Elo receipt 显示
→ /league 出现 You 的真实 Elo / 1 rated game
→ 旧 /play replay 仍能打开
→ League archived replay 也能打开
```

---

## Known limitations

1. **只覆盖 Studio Host browser /play**：console casual 路径本就没有 League 语义，
   也永不回填。
2. **Human 身份仍以本机 `identity.json` 为准**：不是账号系统、无鉴权、无多用户。
   这与既有 Agent registry 的本机信任模型一致。
3. **Replay 页面仍然显示 P0/P1**：本刀不改 Replay UX（已在上一轮记为 backlog）。
4. **League DB 暂时不可用时允许开局**：这类局变成 durable pending，靠 retry 收敛，
   不保证"开局即入账"。
5. **`You` 的第一场 Elo 会非常稀疏**（provisional 阈值 20 场），不代表棋力结论。
6. **pending occurrence 的收敛边界（P1-1）**：pending 的 human occurrence 若在其后
   已有更晚 canonical runtime occurrence 入账，旧 occurrence retry 会 fail closed，
   需要 canonical rebuild；v1 不实现自动中插或自动重算 Elo。

## Next authorized gate

1. owner 复核本 design-only commit；
2. 授权后按 **Slice A → B → C** 实现，每片一个窄 commit；
3. Slice C 完成后执行上面的人工验收数字与 8 项人工确认；
4. 通过后在本文件与 `handoff.md` 记录 `ACCEPTED / CLOSED`。

---

## Recon 回执（Q1–Q7，文件 + 函数 + 数据流）

| # | 结论 | 关键位置 |
|---|---|---|
| Q1 | `RegisteredOpponent::start()` 握手强校验 `agent_name==runtime_name && agent_version==runtime_version`，但 struct 只留 `display_name`；`agent_id/command/runtime_name/runtime_version` 全丢 | `human_play_command.rs:83/97/534` |
| Q2 | `Session` 无 seed 字段；seed 只拼在 `session.id` 字符串里；权威来源是终局 verified `ReplayV1.seed` | `human_play_command.rs:534/1736`；`splendor-replay/src/format.rs:177` |
| Q3 | meta.json 只有 2 个读者（recent-games、historical_replay），均 `Value::get()` Option 读取；但 console InProcess 局写同目录同格式 → 必须建独立 occurrence 文档 | `human_play_command.rs:1207/1247/612` |
| Q4 | canonical resolver = `parse_match_configuration()` → 私有 `resolve_seat_identity()` → `AgentPolicyIdentityV1::key()`；registry 4 条 argv 全部通过冻结词表 | `agent_configuration.rs:124/164/50` |
| Q5 | `CompletionLeagueV1{conn, replay_root}` 全私有；open 时已 `sync_identity_manifest()`；`local_human_participant(conn)` 在同 crate 可调用 | `completion.rs:101/117`；`participant.rs:273` |
| Q6 | 5 段中 2–5 段通用；`runtime_orchestration.rs` 可复用的是"先落盘、磁盘重读、retry 不 rerun"的纪律，不是类型 | `completion.rs:178`；`runtime_orchestration.rs:237/300` |
| Q7 | 终局经 `POST /action` 返回 `HumanSessionState`；UI 挂载点 `app/play/page.tsx:167`(result) 与 `:182`(start panel)；/play 无 casual 分支（强制 registry agent） | `human_play_command.rs:506/2343`；`app/play/page.tsx` |

owner 对 Recon 的两处修正（已并入正文）：

1. **Q4 否决"构造单座位假 match-config JSON"** → 改为提炼共享 production resolver
   （见 D4）。
2. **Q7 的 degradation 拆成两个故障**（league 不可用可开局 vs identity authority
   不可用禁止开局）（见 D2）。
