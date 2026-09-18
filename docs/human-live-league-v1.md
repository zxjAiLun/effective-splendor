# Human Live League Integration v1 — 冻结设计 / Evidence Contract

- **Status**: `DESIGN ACCEPTED @ e081d55`；**Slice A ACCEPTED @ 7ce921b；Slice B ACCEPTED @ 7d9f603（P0=0/P1=0/P2=2 deferred）；Slice C IMPLEMENTED / VERIFIED 本地（真人验收未执行）**（D1–D9 与验收数字冻结）
  - Slice B owner 复审通过：registry TOCTOU、durable-first、disk-only retry、canonical-tail 全部成立；
    P2-1（RegisteredOpponent 固定 30s/1s timeout 与 Host 配置两套）与 P2-2（Database 全类=retryable）
    **DEFERRED，不在 C 修**。GitHub 无 cloud checks，296/100 等计数继续记为本地执行证据。
  - Slice C 冻结文案复核：净 UI 对齐为 `Booked` / `League booking pending` / `League booking requires repair`
    （D9 原句），非重试态 error 即正文。**无后端 response shape 变更。**
  - **设计复审**：`f6909c3` — `DESIGN_REPAIR_REQUIRED`（P0=0 / P1=3 / P2=1；主架构 ACCEPTED）。
    本文件即 **Design Repair 1** 落点：P1-1 retry 语义收窄（canonical-tail）、P1-2 冻结
    `source_document_hash` 映射、P1-3 `expected_session_id` 绑定上移到 orchestration 层、
    P2-1 handshake provenance 拆分 producer/completion 两层。详见「Iteration log」。
  - Slice A owner 复审通过（P0=0 / P1=0 / P2=2）；两项 visibility/comment P2 随 B 收口。
  - B 基线核验：`main == origin/main == 7ce921bae41a3df44f457e8469299ae208c28b0f`，clean。
    A 的实际 direct parent 是 `5ac93f5`，A-only diff 为 `5ac93f5..7ce921b`（6 files）；
    `e081d55..7ce921b` 还含独立教学提交 `527bc19` / `5ac93f5`，不可称为 A-only。
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

诚实边界（P2 明写）：完成侧只剩 `occurrence.json + replay.json`，**不可能重新证明**
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

- **Slice A（交付时记录：IMPLEMENTED / VERIFIED 本地；后获 owner ACCEPTED @ `7ce921b`）**：按 owner 划定范围只做
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

- **Slice B（2026-09-18，IMPLEMENTED / VERIFIED 本地，commit `7d9f603`，待 owner review）**：
  - 收口 A 两项 P2：`HumanCompletionContextV1` / `human_runtime_match_record()` 收为
    `pub(crate)` 并移除 root re-export；request 注释改为「携带 identity claims，但不携带
    league authority context」，不再声称请求里没有 participant id / manifest hash。
  - Host clone 已验证 selected entry，`HumanGameAuthority::freeze()` 从严格 manifest load
    取得 local human/hash，从共享 resolver 取得 exact policy；**不打开 DB**。同一 selected
    entry 传入 `RegisteredOpponent::start()`，握手成功后才把 rated authority 安装进 Session。
    移除 Host 的 `registry_path`；console 注册对手仍 load 一次，`rated=None`。
  - Human filesystem orchestration 单列为 `human_runtime_orchestration.rs`，而非挤进现有
    Arena 四件套模块；两者共用 atomic publisher 与 receipt serializer，不共享 evidence 类型。
    这是文件布局偏离，不新增 completion authority。
  - 终局保存 verified replay / terminal state 后，先原名写 legacy replay/meta，再原子、
    no-overwrite 发布 Human replay/envelope（envelope LAST），最后调 disk-only completion。
    **实际旧 meta 文件名是 `<id>.replay.meta.json`**（`with_extension("meta.json")`），
    保持 writer/reader 原约定；D8 的 `<session>.meta.json` 是早期简写，不应据此改名。
  - 修复同路径的终局错误顺序：原 recorder 已 take、IO 失败后 state 尚未保存，后续 `/state`
    可 panic；现在先持有 terminal state，legacy / occurrence publication 失败返回完成的
    `result` + `league_completion.failed`，不声称 evidence 已保存、不自动重建 evidence。
    终局通知 Agent 失败只记录日志，不能抹掉已由 recorder 确认的终局；非终局协议错误仍报错。
  - 首轮 7 条新 Host gate 全绿。补第 8 条 manifest 中途变化 gate 后，曾错误预期「恢复
    manifest 即能入账」；实测 opener 已将替换身份投影到空 DB，既有 local-human guard
    拒绝再次换人，要求 rebuild。**修正测试的错误预期，保留 production guard**：证据仍是
    开局身份、0 match / 0 events、恢复 manifest 后依然 nonretryable/rebuild required。
  - 第一次 CLI 全套在未改动的 `imperfect_search_cli` 两条 gate 失败：PID 37768 重用旧
    TEMP 产物（两文件 mtime `2026-09-17 19:58:25`），no-overwrite 正确拒绝。未删旧文件、
    未改旧 gate；每轮提供独立 TEMP/TMP 后该 target 7/7，最终整个 CLI 296/0/3 ignored。
  - 更正 A 记录中的证据强度：「计数未变」本身不能推出所有 Arena 行为未变；依据是既有
    suite 的实际 PASS 与 inspected diff。全部结果仍是本地执行，不是独立 CI。

---

## Final implementation — Slice B

生产链为：

```text
POST /games {agent_id,human_seat,seed}
→ authored human identity + selected command/policy freeze（不依赖 DB 可用）
→ exact selected entry spawn / handshake
→ Session{rated:Some(...)}
→ real actions → verified terminal replay
→ legacy replay + meta（sync + atomic no-overwrite）
→ Human replay.json → occurrence.json LAST
→ complete_persisted_human_occurrence(..., expected_session_id)
→ existing complete_human_runtime_occurrence → shared completion tail
```

`HumanOccurrenceSlot`：空目录/不存在为 Empty；只有两个普通文件且合法 Human envelope
为 Complete（replay 的内容验证归 completion）；partial、外来文件、非普通文件或检查失败
为 Ambiguous。拒绝已有 slot，不把 Arena 四件套当 Human，不把 partial 当可重跑。

API 增量：

- `HumanSessionState.league_completion` 非终局/console 为 `null`；终局为
  `{status, retryable, receipt, error}`。`POST /action` 的成功对局响应仍为 **200**，
  即使 booking 失败；客户端必须独立看 `result` 与 `league_completion`。
- 空 body `POST /games/<session_id>/league-completion` 返回
  `{session_id, league_completion}`；不要求当前 Session 存在，不依赖原 registry/Agent。
  非空 body / 不安全 id = **400**；无 durable slot = **404**；ambiguous、identity、
  policy、source conflict、canonical-tail = **409 / retryable=false**；DB/IO completion
  错误 = **503 / retryable=true**（只是允许再 offer，不保证恢复）；inserted/already_present
  = **200 / retryable=false**。`expected_session_id` 不等在打开 completion 之前拒绝。
- 成功补账更新同 ID 活跃 terminal Session 的状态；初次 Human 入账后若 reader 原先不可用，
  复用现有 reopen helper，让榜单马上可读。未添加 raw SQL、archive root 或第二评分出口。
- legacy 或 occurrence 发布失败为 `failed / retryable=false`，因为不能证明完整 durable
  evidence 存在；API 不用内存补造 envelope。`replay_ready` 仍只表示内存 replay 可读，
  **不等价于磁盘已保存**，C 的文案不得混淆。

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

### Slice B executed checks（2026-09-18，本地，非 cloud CI）

最终命令在独立 `TEMP` / `TMP` 下执行（完整环境路径写入本地 `validation.json`）：

| Command | Exit | Result |
|---|---:|---|
| `cargo check -p splendor-cli --bin splendor` | 0 | PASS |
| `cargo test -p splendor-studio-league` | 0 | **100 passed / 0 failed**，10 targets |
| `cargo test -p splendor-cli` | 0 | **296 passed / 0 failed / 3 ignored**，45 targets |
| `rustfmt --edition 2021 --config skip_children=true <8 touched Rust files>` | 0 | PASS，仅 touched files |
| `git diff --check` | 0 | PASS |

CLI 增量 **+8 Host gates**（`tests/human_league/gates.rs`，复用 `league_host_api.rs`
fixture，不增 binary target）；既有 Host 15 + Human 8 = **23/23**。覆盖：

1. 两个 human seats 各真实 `/games → /action → terminal`，1 match / 2 events、Human
   恰 1 event、Elo 非 NULL；legacy 两文件逐字节保留、旧 replay/recent API 和榜单可读；
   **在开局之前破坏磁盘 registry**仍成功，证明 Host 使用已验证快照而非 reread。
2. DB 在开局前不可用，identity 有效可开局；终局 result 正常且 evidence durable；Host
   重启、原 Agent exe 删除、registry 去掉原 entry 后仍可补账。篡改磁盘 replay 则拒绝，
   恢复原字节后 Inserted，再 offer AlreadyPresent / 0 new events。
3. **Gate H**：真实旧 Human pending → 更晚真实 Arena 入账 → 两次 retry 旧局均
   409 / failed / retryable=false / canonical+rebuild；始终 1 match / 2 events，原证据不变。
4. 非空 body、不安全 id、missing/partial/foreign/non-file slot、把合法证据复制到另一个
   session slot、同 source 改 timestamp，全部拒绝；计数不变。
5. missing / corrupt / 无 local-human manifest、unresolved policy、handshake 不匹配均
   禁止开局；客户端多带 participant/policy/runtime/command/result/replay 均 400。
6. legacy meta 路径被目录占用 / occurrence replay 已存在：终局仍可读，0 match / 0 events，
   不覆盖已有 evidence；legacy 失败时 League slot 根本未创建。
7. 对局中换 manifest：durable claims 仍为开局身份；completion 不把它归给新身份；恢复
   manifest 不绕开既有 DB identity guard（仍失败，rebuild required）。
8. console in-process 与 console registered 两条真实终局都 `league_completion=null`，
   cwd 即隔离 League 的 project root，始终 0 match / 0 events、无 occurrence。

四组**真实变异负向对照**（每组恰 1 个 targeted gate FAIL / exit 101）：去掉 requested-ID
绑定、把 Invalid 一律设 retryable、跳过 evidence publication、中途重新读取 Human 身份。
每次从 patched-state byte backup 恢复并断言字节一致，全部恢复后才跑最终全套。
这些分别证明对应的绑定/分类/持久化必要性/冻结身份门会咬住变异；**不冒充 OS 掉电测试、
全故障矩阵或独立 review**。本轮没有 UI 改动，未重跑 app suite、未进行真人验收。

Local artifact root：`local-artifacts/studio-league/hll-b/`（ignored）。

| Artifact | SHA-256 |
|---|---|
| `league-final.log` | `062efc007fc6f4d2d67ff5e2a81bc0f1602355c298503507ebf067359b16aa70` |
| `cli-final.log` | `1cb964099c3c7bd5cf2c5ba0b664a13598b099c18ecabf74982e7cf04f680dd4` |
| `negative-controls.json` | `be103ad7cf8df7ed00bdbaf0c682e25000e695108b1c188d45f404282c5adc04` |
| `validation.json` | `6124cee5c6727f355b664362efa6d9d613f0fbedb1bb1242ad8a99508f960db8` |
| `real-league-read-only-check.json` | `521cd4d2cb09a6709c0c0e047524f6965b7aceb2aea2b6728f53aa1cef9136e5` |

失败日志亦保留在同目录：`hll-b-cli-full.log`（旧 TEMP 冲突）、
`hll-b-cli-isolated-full.log`（新增 manifest 测试的错误恢复预期）、`nc-*.log`。
真实库复查使用 SQLite URI **`mode=ro` + `PRAGMA query_only=ON`**：
**42,522 matches / 28,012 events；You = 0 seats / 0 events / NULL Elo**，首局起点保留。

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

## Result and decision

2026-09-18 继续交付更新：C/E 页面已 IMPLEMENTED / VERIFIED（本地），实际改动/失败修正/测试见
[Studio Player Loop](studio-player-loop-v1.md)。真实首局尚未执行；全闭环仍未 ACCEPTED。
下述为 B 交付时的历史结论：

**Slice B IMPLEMENTED / VERIFIED（本地），待 owner review；不是整轮 ACCEPTED。**
评分/双 Engine/Human 审计已做（见下），没有以优化名义修改冻结范围。下一道门是审核 B 的
实际 narrow diff；未获 C 授权前不改 UI，也不代替 owner 打真实首局。

## Workflow audit — rating / two Engines / Human integration

本节是 owner 请求的代码与本地 gate 审计，**不是性能 benchmark，也不授权新实现**。

| Area | 已核实事实 | 处理与后续建议 |
|---|---|---|
| Elo 更新 | `ledger.rs::ingest_match_ordered` 的 IMMEDIATE transaction 原子更新比赛、两侧事件与 rating；`elo.rs::plan_pair_update` 共用 `splendor-eval` 算术，另一方 delta 为负值；相同 source+hash 先返回 AlreadyPresent | **不改 K=32 / initial=1500 或评分算法**。没有新证据说 Elo 算术是瓶颈；若调评分属于新协议/校准评估，不是本片优化。 |
| Canonical pending | 新 runtime 必须晚于 canonical tail；Gate H 实证，重复 retry 不会治好顺序问题 | B 已诚实区分 nonretryable。将来如要提供 pending 列表/人工恢复，先设计含 Human evidence 的 canonical rebuild 与备份合同；不在本片自动重算、换 timestamp 或中插。 |
| 两个 Engine 启动 | `ArenaRunner::run` 经 `spawn_agent` 为每席起独立进程；先向所有 seat 发 Hello，再设一个共同 handshake deadline；`AgentProcess` 有关闭与 Drop 回收 | 启动器两扇窗口是 **Host + UI**，不是两个 Engine 窗口。不可用「少启动一个进程」合并两席策略状态。进程池/复用仅在量到 spawn/model-load 占比后考虑，并先证明 reset/RNG/协议隔离；本片不改。 |
| Host 阻塞 | 接收循环串行；一盘 Agent-vs-Agent POST 及 completion 的 DB 等待会占住 Host | 限制仍在。不为了提速开 worker/concurrency；将来先分段测 spawn/handshake/decision/publish/ingest，再按 owner 授权优化。 |
| Human 生命周期 | 之前 registry 重读与终局 IO 状态丢失风险确实位于本片生产路径 | **B 已修**：同 entry freeze→spawn→handshake；terminal fact 在 IO 前保存；durable-first 与 disk retry。不能用显示名替代身份，不能用内存补账。 |
| Timeout 一致性 | Arena 使用 Host 的 handshake/shutdown 配置；旧 Human `RegisteredOpponent` 仍固定 handshake **30s** / shutdown grace **1s**，仅 move timeout 由参数传入 | **DEFERRED，未改行为**。可另做配置贯通的小片，须同时覆盖 console 默认行为和 Host 覆盖值；不是这次身份/证据 gate 的前置条件。 |
| 路径与旧消费者 | League 取 explicit project root；legacy human replay/recent/review 仍沿用进程 cwd 的 `local-artifacts/m20-human-play` | 有意保持兼容，launcher 本来把 cwd 指向项目。将来若统一路径，必须把所有旧 reader/writer 一起改，不能单改 publisher。 |
| `/play` 展示 | B 只增加 API booking fact；当前页面还没有 Rated/Elo/Retry 展示 | **C 仍未授权**。下一片 UI 要按 status/error 的事实渲染，不能从 retryable 推断「一定未入账」或「一定可恢复」。 |

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

2026-09-18 更新：owner 授权继续完成玩家页面与接入，C/E → D → F 的完整清单见
[Studio Player Loop](studio-player-loop-v1.md)。此为继续实施授权，不等同 B 独立 review 或整轮验收。
以下是 B 交付时的历史 next-gate 记录，已由本更新取代：

1. owner 复核 Slice B 的实际 narrow commit/diff 与本地验证证据；
2. B 通过后再由 owner 授权 **Slice C**（当前未授权）；
3. Slice C 获授权并完成后执行上面的真人验收（B 自动测试不替代人工验收）；
4. 通过后才在本文件与 `handoff.md` 记录整轮 `ACCEPTED / CLOSED`。

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
