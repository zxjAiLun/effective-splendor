# M65 Prism Beta v0.1.0 与 Prism Alpha v0.1.5 发布

历史模型清单补充：[截至2026-10-05晚的六固定模型与M66参照](prism/model-catalog-2026-10-05.html) / [完整证据Markdown](prism/model-catalog-2026-10-05.md)。本清单不改变M65冻结发布及原判定；2026-10-07用户要求同步ALL和项目记忆，0新局。

Status: IMPLEMENTED / VERIFIED / RELEASED_EXPERIMENTAL_MODELS (2026-10-05)
Baseline: `9899749188f35c838c85c5b3530049bd5dcbd105`, branch `m61-alpha-balance-ab`.

## Problem and evidence

Owner requested using idle DSW compute and identified M62 Beta and M63 Alpha as the two unpublished artifacts. Live SSH: four CPUs, affinity0..3, load1m0.13, about13GiB available RAM, no active Splendor job. M63 greedy evidence is complete; M62 lacks representative greedy coverage.

## Initial design

Run the authorized M64 finite speed calibration, then a frozen2560-game both-greedy release-support grid for M62 Beta and its Balance reference. Publish exact existing weights as **Prism Beta v0.1.0** and **Prism Alpha v0.1.5**. Owner-directed artifact release is separate from old style research acceptance and default-champion replacement.

## Scope and non-goals

Check/materialize both exports, bind lineage/evidence, deliver readable HTML/Markdown and complete audit, update model records/index. No new PPO, checkpoint selection, extension, changed old weights/results/gates, automatic game retry, default replacement or pool deployment. DSW2 is not used.

## Contracts and invariants

- Beta: M62 final Beta c4, SHA256 `69a885b20527dda2e43fad9c00d7cc36537b45a0f5ccbaef4320001bef8836fb`; parent Prism Balance v0.1.0.
- Alpha: M63 original Beta-arm final c4, SHA256 `3d81da745b7863b148cc3013386274f7aa7ac3f2ebdbe8a7701cc99c771edc12`; parent Prism Balance v0.1.0, not Alpha v0.1.4 continuation.
- `benchmarks/m65-prism-version-release.config.json` freezes models/seeds/modes/budgets/source hashes before dispatch. Release common pool: M62 candidate and Balance reference each versus Heuristic v0.3.1, Prism v0.1.0, Prism v0.1.1, Prism Alpha v0.1.4 (2048 games); direct Beta versus Balance/new Alpha256 each. Seeds9691000..9691127, both seats, greedy; action seed65020001.
- Speed calibration repeats256 logical greedy games with3/4/5/6workers twice:2048 executions, seeds9681000..9681127, action seed65010001. Repeated runs do not enlarge competitive samples. Explicit calibration-only oversubscription: measured4CPUs, at most6workers/256games/1h/8GiB per configuration; normal arena still respects CPU allocation.
- New owned tree `/mnt/workspace/splendor-m65-release`; old M63/R3 trees untouched. Queue2h ceiling, calibration1h; memory8GiB sampled process-tree limit; zero automatic retries.
- Prefer stable ordinary-allocation configuration within5% of measured fastest, otherwise fastest measured3/4worker option.5/6worker speed is recorded without inventing more CPU cores.
- Release does not certify universal strength improvement. Preserve opponent losses and uncertainties; formal old gates remain history.

## Implementation plan

Test explicit calibration bounds; freeze/deploy queue; run finite jobs; harvest exact evidence/full tables; check version/tensor/manifest identity; register versions; render common reading layer with result/weight binding; reconcile handoff/dashboard.

## Iteration log

- 2026-10-05: owner clarified M62 Beta and M63 Alpha, not M63 control. ALL unavailable; started existing service with `Start-All.ps1 -NoBrowser` and refreshed context. Added narrowly bounded calibration opt-in;34 arena tests pass before deployment.

## Final implementation

Completed finite queue: `scripts/prism_dsw_release_queue.py`; calibration opt-in: `scripts/prism_notebook_arena.py`; exact-identity publisher: `scripts/prism_model_release.py`. Both fixed versions are registered and exported. Result-bound reading specs and the common report layer deliver human HTML/Markdown separately from the Agent audit. Exact files, decisions and checks are recorded in the closeout below.

## Validation and evidence

Before dispatch, executed `C:\Python312\python.exe -B -m unittest training.prism_portable.tests.test_dsw_arena -q`:34 tests, exit0. Tests cover default oversubscription rejection, explicit measured-four-core opt-in, scope ceilings and changed CPU capacity. Queue Python compilation exit0. Release-support was `NOT_RUN` at initial freeze and is now completed with 2560 games; see the closeout checks and [report index](prism/reports.html).

## Result and decision

Owner-authorized fixed research versions are released as **Prism Beta v0.1.0** and **Prism Alpha v0.1.5**. This decision is separate from the unchanged historical Beta research gates and default-champion replacement. Calibration and all fresh release-support matches completed; no additional PPO was run.

## Known limitations

RSS guards are observed soft limits. Platform inactivity shutdown may stop jobs. Actual post-change report pixels remain unverified; offline DOM has no layout. Partial shards never automatically respawn.

## Next authorized gate

This finite queue and version release are complete. Recommended next research: a bounded Alpha-route continuation from Prism Alpha v0.1.5 with representative fixed both-greedy comparisons. A new training budget/configuration must be defined before dispatch; no open-ended job is running merely to occupy CPUs.

## M65 closeout / owner-authorized release / 2026-10-05

**产物：两份固定研究版本已发布。竞技：实战有取舍，没有宣称全面增强。风格：Alpha略偏大牌冲分；Beta研究分支名保留，实际画像偏混合，更突出基建尚未建立。**

| Version | Origin | Training parent | Current scope |
| --- | --- | --- | --- |
| Prism Beta v0.1.0 | M62 Beta final c4 | Prism Balance v0.1.0 | Released fixed research/comparison version; stronger building identity not established |
| Prism Alpha v0.1.5 | M63 original Beta-target final c4 | Prism Balance v0.1.0 | Released Alpha-route checkpoint; not continuation of Prism Alpha v0.1.4 |

M64 speed calibration completed2048 executions and verified action/outcome equality over the same256 logical games. Production4workers reaches97.28% of fastest6worker throughput. M65 release-support completed2560 fresh greedy games (2048 common plus256 direct parent plus256 direct new Alpha),0 automatic retries. Entire queue847.884s (14.13min), including sequential preparation/diagnostic comparisons; release arenas alone438.00s approximately (clock in result is exact). No new PPO or model selection.

### Competitive release-support: M62 fixed version, both-greedy

Every row256 games /128 two-seat blocks, seeds9691000..9691127, action seed65020001. All rates belong to the named candidate model against that opponent. Score = (wins + half draws)/games.

| Opponent | Prism Beta v0.1.0 W/D/L | Pure win | Half-draw score | Balance parent's score vs same opponent | Change |
| --- | --- | --- | --- | --- | --- |
| Heuristic v0.3.1 | 194/1/61 | 75.78% | 75.98% | **76.76% ↑** | -0.78pp |
| Prism v0.1.0 | 200/1/55 | 78.13% | 78.32% | **78.91% ↑** | -0.59pp |
| Prism v0.1.1 | 162/2/92 | 63.28% | **63.67% ↑** | 62.89% | +0.78pp |
| Prism Alpha v0.1.4 | 126/5/125 | 49.22% | **50.20% ↑** | 49.02% | +1.17pp |
| Direct Prism Balance v0.1.0 | 118/4/134 | 46.09% | 46.88% | NOT_APPLICABLE | NOT_APPLICABLE |
| Direct Prism Alpha v0.1.5 | 112/1/143 | 43.75% | 43.95% | NOT_RUN | NOT_APPLICABLE |

Direct W/D/L has been checked against the saved result. Across four common opponents, equal mean Beta67.04102%, parent66.89453% (+0.14648pp), descriptive only. Own VP/Main0.552019→0.556369; noble coverage36.13281→33.98438%;0–1VP cards7.972656→7.717773/game;3–5VP printed score7.429688→7.835938 VP/game. This is mixed/scoring-leaning behavior, not demonstrated stronger small-card building. Retain Beta as an explicitly qualified research reference, not a new strongest/default model. Alpha's complementary new direct Beta score is56.0546875% (143/1/112), a separate seed cohort from its earlier2816-game report.

### Publication and evidence

Records: `benchmarks/m65-prism-beta-v0.1.0.model.json`, `benchmarks/m65-prism-alpha-v0.1.5.model.json`. Installed exports: `local-artifacts/prism/beta-v0.1.0/weights.json`, `local-artifacts/prism/alpha-v0.1.5/weights.json`. Exactly32 finite float32 tensor bytes match their original companion manifests, including shape, per-tensor SHA and manifest aggregate SHA. Original `not_promoted` export provenance stays historical; current owner release status lives in the separate model record.

Input/receipt: `benchmarks/m65-prism-version-release.publication.json`, `local-artifacts/prism/m65-release/publication-receipt.json`. Publisher validates both originals/configs/parent/audits/greedy modes/completion and every destination before mutation; version collisions reject. Initial publication preflight found a nested `origin.arm`/top-level-arm schema mismatch, wrote no model destination, and was corrected before publication. No match was rerun. ALL run reporting initially used wrong API fields, was rejected, then corrected to `id/state/phase`; no runtime operation was duplicated.

Fresh greedy evidence: `local-artifacts/prism/m65-release/harvest/release-evaluation/{common,direct-parent,direct-new-alpha}`. Harvest verified106 file hashes and ZIP SHA `270432513306702b9e731a04d8023f92436e55e28c2e81b2d7196abd53093680`. Native full rule replay verification occurred on DSW; local checks verified harvested bytes, model identities and projections, without claiming another independent local rerun of every replay. Remote source root persists `/mnt/workspace/splendor-m65-release`. Calibration and release seed cohorts are disjoint; old results/configs/weights remain unchanged.

Reading: [M65 two-version release](prism/m65-prism-version-release-comparison.html), [Beta full human tables](prism/prism-beta-v0.1.0-evaluation-summary.md), [Alpha full human tables](prism/prism-alpha-v0.1.5-evaluation-summary.md), [speed calibration](prism/m64-dsw-throughput-calibration.html). Round-specific `benchmarks/reports/m65-reading.json` binds the immutable M62 historical research/audit anchor plus every M65 result/plan/config; only new both-greedy data supplies its main numeric views. M62/M63 human report specs now bind actual release records/exports, with old research and superseded aliases preserved separately. No original gate was changed to PASS. The M65 summary result is `benchmarks/m65-prism-version-release.result.json`.

### Verification / limitations / next gate

Actually run, exit0:34 arena contract tests;11 combined publication/report Python checks (4 publication +7 reader);119 human DOM groups (31 greedy),66 historical audit DOM groups; JavaScript syntax. Publication tests validate exact tensor content, reject rehashed corrupt manifests, require owner scope, check two-version materialization and collision refusal. Reader checks release record/result/weight/name bindings. Actual browser pixels remain NOT_VERIFIED; no browser workaround. Git publication, default replacement, pool deployment and Studio deployment are separate and were not performed.

Final local closeout: `C:\Python312\python.exe -B local-artifacts/prism/m65-release/verify_closeout.py`, exit0. Receipt `local-artifacts/prism/m65-release/validation.json` verifies both releases/32 tensors,106 harvested files, all four reading receipts and original evidence pins, index links, model ZIP exact bytes, corrected direct W/D/L, unchanged branch/HEAD/empty Git index and `git diff --check`. Earlier passing tests are recorded separately from these final hash checks; no test or match was repeated to improve an outcome. The model package is `local-artifacts/prism/m65-release/prism-m65-released-models.zip`, with `bundle-receipt.json`.

ALL closeout: `local-artifacts/prism/m65-release/sync_all_closeout.py`, exit0; M65 task `21ef4c65-4ac9-4960-880b-a7ec3d347cee` and M64 calibration task `9a7dbf5d-88ce-4280-8716-5963d8d6788e` are done,12 actual JSON/Markdown/HTML artifacts registered, actual DSW queue state completed/PID null. Receipt: `local-artifacts/prism/m65-release/all-closeout-receipt.json`. The broader report UI visual review is not inferred complete from these task states.

Current decision: RELEASED_EXPERIMENTAL_MODEL by explicit owner practical publication. No claim of formal old Beta research acceptance, universally stronger successor or default champion. Further research can start from Prism Alpha v0.1.5 with a finite campaign and frozen representative greedy comparisons; Beta remains a useful fixed comparator with honest mixed-style qualifications. This finite DSW queue finished; no perpetual worker or new PPO campaign is silently left running.

## 2026-10-05 项目接手核验（PI-Desktop；0 新局）

Status: VERIFIED_TAKEOVER。用户本轮只要求根据接手文档了解项目链路并接手；不是新 PPO、重复发布或部署授权。接手基线仍为 `m61-alpha-balance-ab@9899749188f35c838c85c5b3530049bd5dcbd105`。本次自查由主代理完成，非新的独立竞技审查。

### 当前链路与继续入口

1. **规则、信息边界与回放**：`crates/splendor-core` 是规则与终局唯一依据；Agent 只看 Observation / VisibleEvent / 合法动作，不读取裁判 FullState。`splendor-arena` 派发对局，`splendor-replay` 校验保存回放。
2. **Prism 模型与 CLI**：`crates/splendor-prism/{src/encoding.rs,src/inference.rs}` 与 `training/prism` 分别实现 Rust 推理和 Python 模型/导出；独立于 Aran。`crates/splendor-cli/src/main.rs` 分开路由 `agent-prism`（greedy）、`agent-prism-sample` 与 `agent-prism-ppo`，不能根据对手模式猜候选模式。
3. **有界 PPO**：`training/prism_portable/{control.py,worker.py,protocol.py}` 管理进程、原预算与单写者交接；`engine/ppo/{arena.py,coordinator.py,learner.py,store.py}` 负责采集、更新和 model/optimizer/RNG/账本提交。`Run.create` 从权重 warm-start 建新优化器；`Run.open` 读取已提交完整状态，二者不能混称恢复。旧操作指南的版本与预算属于 M57 历史，不是本次新合同。
4. **评测、发布、报告**：轮次脚本与 `scripts/prism_notebook_arena.py` 执行固定种子/换座网格；`prism_dsw_release_queue.py` 的 M65 有限队列已完成；`prism_model_release.py` 只在明确授权下绑定精确权重版本。`prism_round_report.py` + 轮次 reading spec + `prism_human_report.py` 在冻结结果之后输出人类阅读页，Agent 审计另页；不更改原研究门。
5. **应用与看板**：`apps/replay-studio`、Studio Host / registries、共享池是单独部署链；M65 不代表它们已更新。ALL 任务/运行/产物记录用于同步实际状态，计划节点不启动进程。

### 本次实际验证

- 只读执行旧 `verify_closeout.py` 的第 1–119 行断言（执行前校验整文件 SHA），不执行其历史回执构造/覆写；额外核验两个模型的父权重和 companion SHA。两版各 32 个 finite float32 张量、106 个抓取文件、三组共 2560 局已保存评测、校准语义摘要、四轮阅读来源/输出、索引链接与 ZIP CRC/逐文件字节一致性均 PASS。原 `validation.json`、发布回执及版本记录字节保持。
- 实际重跑 `C:\Python312\python.exe -B -m unittest scripts.tests.test_prism_model_release scripts.tests.test_prism_round_report -q`：11 tests，exit 0。发布测试写入会话临时目录，不重跑生产发布器。未重跑历史 arena/DOM 测试、全仓库构建、比赛、训练或完整原始回放。
- 19:40（Asia/Shanghai）只读 SSH 查询 `/mnt/workspace/splendor-m65-release`：`COMPLETED`，2048 校准执行 + 2560 发布支持局、0 新训练/0 自动重试；5 个队列/配置/结果文件 SHA 与本地抓取相同。旧 owner PID 已不存在，未发现使用该自有目录的活动进程；可见 CPU 4、affinity 0..3、load1 约 0.12。这不是所有主机/研究任务的进程普查，也不是持久监控。
- 接手前 Git 为 45 个 tracked 修改、304 个 untracked 条目（normal 模式会折叠目录），暂存区为空；检查前后状态不变，`git diff --check` exit 0。`handoff.md` 与 `local-artifacts/` 继续 ignored。不重置、不暂存、不提交、不推送。

### 接手证据与状态边界

本次独立回执位于 `local-artifacts/prism/m65-takeover-81c2df41/`：

| 文件 | SHA256 |
| --- | --- |
| `local-verification.json` | `26c619a7d297ddae389288fab81519bf0761e5f6c0451bff6f55e8898ff289e6` |
| `remote-verification.json` | `7fead01585e3bb84790bc2679d9c3d65b55ab57af9195d0ecdd3441774a6175d` |
| `context-verification.json` | `8f1771860b749888156ba64727ce414396877220d553f6b0b912c5255ee62015` |

ALL 快照确认 `M65 发布M62 Beta与M63 Alpha，DSW校准及greedy实战补齐`、`M64 DSW对战满核与均衡配置校准（用户要求明天）` 均 done；`Prism每轮报告逻辑重写：结论优先、对战与风格解释、按需详细数据` 仍 review。自动项目摘要曾拾取历史 M63 RUNNING 标题，不能覆盖已完成回执；本次 handoff 追加明确 M65 当前标题，不删除旧快照。本次接手另记任务 `51de4e67-d39d-4bdb-ae5a-53af1d77a958`，不重开旧发布任务。

结论与下一步不变：Prism Beta v0.1.0 为混合/偏得分的固定研究参照，Prism Alpha v0.1.5 是由 Prism Balance v0.1.0 分支的轻度大牌冲分起点，非 Prism Alpha v0.1.4 续训。完整实战数据沿用本节上方链接，不新增或混合统计样本。真实浏览器像素/窄屏布局仍 NOT_VERIFIED；新 PPO 仍仅建议，须先明确有限预算、种子/对手、停止条件及新优化器或全状态恢复语义，另测 PPO 资源需求，不能用 arena 吞吐代替。旧 M62/M63 driver 失败与 M65 校准总时限执行边界保留，未来复用须新执行修订。

## 2026-10-07 历史模型目录同步（截至2026-10-05晚；0新局）

任务类型report/sync；用户明确要求将给定模型清单同步ALL与项目记忆。授权终点为只读核验、历史快照登记和memory扩展note；不改冻结权重/结果/研究门，不训练/评测/发布/部署/提交推送，也不把旧清单替换当前M67状态。R0身份范围PASS，R1–R6新研究阶段NOT_APPLICABLE；R7只读解释历史画像，R8历史清单交付，R9本任务同步收口。

七份权重SHA/32张量结构和26条W/D/L aggregate算术核验PASS；result/plan/source绑定和本地HTML/Markdown链接PASS，未复算bootstrap或重审原回放。六固定模型为General v0.1.1/v0.1.0、Alpha v0.1.5/v0.1.4、Balance v0.1.0、Beta v0.1.0；另存M66未发布c4完整SHA。General正式T=1迭代验收不自动证明跨家族最强/默认冠军；Balance均衡NOT_CLAIMED；Beta 54.98%属于旧T=1采样而50.20%属于M65 greedy。Alpha v0.1.5对Beta的M63 greedy48.63%与M65 greedy56.05%均保留。用户提供旧Alpha对战上界53.42%未取得绑定来源，记UNKNOWN，不构造区间。

交付：[历史HTML](prism/model-catalog-2026-10-05.html)、[完整MD](prism/model-catalog-2026-10-05.md)、[机器目录](../benchmarks/prism-model-catalog-2026-10-05.json)。七个原身份记录和目录/页面共9个ALL产物登记成功，回执`local-artifacts/prism/model-catalog-20261005/all-registration-receipts.json`；核验`verification.json`/`delivery-check.json`。项目记忆仅写一个`C:/Users/81489/.codex/memories/extensions/ad_hoc/notes/20261007T234834+0800-splendor-prism-model-catalog.md`更新note，未编辑MEMORY.md或原记忆。git diff --check exit0；handoff ignored，index为空；页面CLI零写作警告，像素/DOM交互NOT_VERIFIED（静态目录未设强制视觉门）。模型原身份不变，本次同步任务可done；下一允许读取该历史目录，新研究/部署须按相应任务授权。