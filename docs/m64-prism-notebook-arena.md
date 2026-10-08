# M64 DSW SSH 持久化通用对战工具

Status: IMPLEMENTED / VERIFIED（两台有限实机烟测）；模型正式验收、实际Pod重建 NOT_RUN。
Baseline: `9899749188f35c838c85c5b3530049bd5dcbd105` / branch `m61-alpha-balance-ab`；大量既有工作树改动保留。
Owner/date: Zixuan Tang / 2026-10-04–2026-10-05。

## Problem and evidence

原请求为仅有Jupyter、可git clone的多核机器提供通用模型/对手/局数工具。用户后续取消Notebook需求，授权通过`ssh dsw`和`ssh dsw2`直接部署。DSW名义4核16GB持久运行；DSW2名义8核32GB，每8h替换实例。二者持久化挂载`/mnt/workspace`，已有SSH隧道和自愈守护由用户维护。本轮不修改这套运维工程，也不将用户提供的“100%通过”表述当作本工具重建验收。

原M63执行器绑定cloud1绝对路径、systemd/cgroup与2workers，不能直接改并发或把M64烟测算进其验收。M63保持原FAILED_STOPPED_NO_RETRY与R1 VERIFIED_ZERO_GAMES，576开发+9,728独立对局尚未重启。

## Initial design

独立通用runner复用固定双座协议及Rust回放验核/完整经济指标；按affinity、逻辑CPU数及可见cgroup祖先quota的最小值限制并发。8核预留2核，每worker计算库线程1。后台进程与SSH/Jupyter会话分离，无systemd、root守护或torch依赖。配置、来源、二进制/模型SHA、固定网格、回放、进度及Markdown/HTML持久保存。

工具验证门是网格/漂移/资源/所有权/失败不重跑测试，以及两台新目录的有限真实双座对局、规则验核、双方守恒和可读完整表。它不是棋力门。Notebook界面及Windows原生实战验证因SSH转向DEFERRED；Windows仅执行Python合同测试，原生Linux构建在WSL进行。

## Scope and non-goals

实现通用开发对战、资源检查、SHA绑定、后台启动/状态/停止/恢复、双方表与归档抓取。两机分别8局，最多16次工程执行，不扩充正式实验；两机相同8个逻辑键不合并成16局棋力样本。不训练PPO、不发布模型、不改M63门/权重/种子，不迁移正式验收，不改默认/池/Studio，不提交或push。源码和模型均有未发布资产，clone旧HEAD不能取得本轮所有实现，已用明确源码/模型包部署。

## Contracts and invariants

- 每candidate/opponent/seed恰好双座各一次；按模型身份汇总，物理P0不恒为候选。比率从总计数/分母计算；固定描述性bootstrap20,000次、RNG64049999，不构成验收门。
- prepare只绑定和验证，0对局；新目录不得覆盖。候选sample=T=1，对手sample或greedy；所有模型同catalog。配置/源码/依赖/资产漂移停止。
- 每shard只派发一次，先持久记录DISPATCHED再启动。完整回执绑定progress及每局report/replay/game/process-result/match-config。失败/半成品保留且0自动重试。
- stop停止新派发并排空在途shard后STOPPED_SAFE；可续未派发部分。force/信号/预算失败终止自有子树，FAILED_PARTIAL_NO_RETRY。recover只在旧runner已死时验核完整但未记账的shard；任何派发半成品均拒绝自动重开。
- 所有者绑定PID/create_time/容器cgroup与PID1创建时间/随机token。启动锁内二次检查避免同目录并发双启动。只管理自有任务，不杀Notebook/隧道/其它进程。
- 累计活动墙钟和CPU预算跨安全停止不重置；进程树RSS与存储是采样软预算，不能宣称专属cgroup硬隔离。实例寿命按PID1创建时间，不能按宿主uptime；DSW2按8h预留45min，prepare/start拒绝超出剩余安全窗口的预算。安全恢复到新Pod后按同冻结寿命规则计算当前实例deadline，不重跑中断局。

## Implementation plan

1. 通用runner、资源及所有权约束、后台生命周期和轻量依赖。
2. SSH CLI、独立持久化目录、原生工具兼容和来源绑定。
3. 完整双方指标、模式/座位/CI/时钟/来源表及HTML。
4. 合同测试、两台有限烟测、来源抓取/数值验核、操作文档及handoff收口。

## Iteration log

- 2026-10-04：用户指定通用工具，保持M63原合同。本地target/release/splendor.exe是旧构建，不能仅按文件名认为支持Prism。
- SSH转向：实机均cgroup v1；DSW2 affinity64、逻辑8、quota8、有效内存28GiB，必须避免按64开workers。默认DSW3路、DSW2 6路；两机无Rust，Python分别3.12.13/3.11.11。
- 初次部署：固定依赖/profile成功，但从cloud1取到的M57 ELF machine183（ARM）在DSW x86_64的version入口Exec format error。两台0局，原字节、失败回执保持。新增ELF架构预检。
- 下载/构建：DSW2 Rust镜像下载慢，仅终止自有构建树并留日志。WSL默认cc包装器不支持Rust triple，改显式GCC；Ubuntu24构建引擎需要GLIBC2.39，不适用于DSW的2.35。改Zig目标glibc2.31链接；一次临时shell脚本CRLF错误及60秒子进程监控超时保留，修为LF并用可持续的exec会话。最终release构建exit0；原未通过路径未运行游戏。
- 来源命名：当前开发heuristic的命令兼容版本不是固定Heuristic v0.3.1发布身份，烟测明确标为Heuristic development snapshot（agent-heuristic-v02，greedy），不偷换对手版本。
- 2026-10-05：两台smoke-v5各8局全部完成，规则验核、经济守恒、14表/机通过，0对局重试。两机逐局终局行完全一致；归档与16份逐局来源本地hash/终局/数值复核通过。
- 收口：v5未使用的new_games遗留字段仍为0，实际以completed_games=8/逐局回执为准，原状态保持。当前v6补丁移除该冗余字段；30检查与两台零局prepare/verify通过。v5实际源码保存在runtime-snapshot与完整归档，未来核验可用原源码。

## Final implementation

| 模块 | 职责 |
| --- | --- |
| scripts/prism_notebook_arena.py | v1/v2配额、双座shards、资源预算、背景执行、source/asset/owner binding、stop/recover/archive |
| scripts/prism_dsw_arena.py | profile/prepare/start/status/stop/recover/verify/archive；模型/对手/种子/预算请求入口 |
| scripts/prism_notebook_report.py | Rust规则重建、模型身份归并、完整双方表、配对CI、匹配基线方向与MD/HTML |
| scripts/prism_notebook_bundle.py | 源码/模型包SHA、完整成员清单、路径约束与防覆盖 |
| scripts/prism_dsw_bootstrap.sh / prism_dsw_manage.sh | 自有持久化venv；ABI检查、固定版本轻量依赖与SSH调用 |
| training/prism_portable/tests/test_dsw_arena.py | 30合同/配额/漂移/所有权/恢复/配对统计/运输检查 |

历史notebook文件名保留，Notebook界面DEFERRED，不是部署前置条件。操作说明：[DSW SSH操作](prism/notebook-arena-operations.md)。新导出依赖固定numpy2.2.4/psutil7.0.0/Markdown3.8。

| 部署 | 路径 | 实测资源 | 默认workers |
| --- | --- | --- | --- |
| ssh dsw | /mnt/workspace/splendor-dsw | 4核，15.35GiB有效内存 | 3 |
| ssh dsw2 | /mnt/workspace/splendor-dsw2 | quota8核，28GiB有效内存；affinity64 | 6 |

最终native引擎SHA `6ecf85de6e83bf2fa38e259b11167a6c6f685fa4ddb4cd875acfb089cb56ea8f`（ELF62，max required GLIBC2.30）；metrics SHA `39c630d5e0a9e0611ca4ec8c8b2e4a78817bf971c7bdc7446b614035aedbcb37`（max required GLIBC2.34）。本机Rust1.94.1，engine Zig linker指定glibc2.31，metrics GCC；当前308份Rust/Cargo输入对最初源码包0漂移。源码包SHA `d80b879217584edc2b82702bd366a4bed14fe816afde27124de9e6e249e7aeca`，Python后续修订逐包另记，不混同HEAD或新构建。

## Validation and evidence

- `C:\Python312\python.exe -B -m unittest training.prism_portable.tests.test_dsw_arena -q`：30测试exit0；覆盖cgroup v1/v2祖先配额、8/64CPU、28GiB内存、网格重复/缺座、文件/依赖/源码/plan漂移、双启动锁、PID/实例变化、完整未记账恢复、半成品禁跑、CI纯胜/半平区分与运输路径/SHA。
- WSL `cargo build --locked --release -p splendor-cli --bin splendor --example s4_batch_metrics -j 6` 显式GCC构建完成；engine随后 `cargo rustc --locked --release -p splendor-cli --bin splendor -- -C linker=.../native-linker-zig.sh` 成功exit0（38.04秒该次增量步骤）。目标机两台 `bin/splendor version` exit0；原生实际run-match与回放tool全部exit0。
- 两机smoke-v5：各8局/4shards/两候选/一个开发对手/每对手2双座种子，seeds64000000/64000001，action_seed64010001；4GiB软RSS/15min活动墙钟/1CPUh/2GiB存储。DSW2同时启用8h−45min寿命门。
- DSW总活动墙钟3.468655秒，观测RSS和峰值140.42MiB；DSW2为5.567016秒/181.60MiB。包括离线回放与报告，排除构建、下载和SSH；DSW2只有4shards，未用满6并发。这是工程烟测，不是吞吐校准。
- 完整抓取校验 `local-artifacts/prism/dsw-m64/fetch-and-report-validation.json` PASS：两zipSHA、6冻结Python源/机、每局终局与全部artifact hashes、双方卡/VP/折扣/动作守恒、完整双座网格、两机终局行一致；30表合并阅读件。
- v6两机零局prepare/verify均exit0：runs/zero-preflight-v6为PREPARED_ZERO_GAMES，未start；不增加比赛。两个smoke runner均已死，下载慢的自有编译树已停止。
- 可读烟测全文：[Markdown](prism/m64-dsw-arena-smoke.md) / [HTML](prism/m64-dsw-arena-smoke.html)，所有模型/对手个人、物理双座、整局及来源表均保留。基线是Prism Balance v0.1.0已登记实验模型；M63 Beta c4明确为未发布训练检查点。

| 本地ignored证据 | 内容 |
| --- | --- |
| local-artifacts/prism/dsw-m64/*deployment-v1.json | 初次ARM故障、0局；依赖/profile实机回执 |
| native-build-launch.json / native-build-stop.json / wsl-native-build-v*.log | 镜像下载停止、cc失败与本地构建历史 |
| native-x86-v5-receipt.json / native-link-v5-exit.txt | 最终原生字节/构建/GLIBC/exit0 |
| dsw-smoke-v5.zip / dsw2-smoke-v5.zip | 两台完整结果/回放/配置/实际runtime-snapshot；归档SHA见阅读件 |
| fetch-and-report-validation.json / unit-tests-and-source-v6.json | 本地hash/终局/数值核验与源码/测试回执 |
| *overlay-v*.json / *preflight-v6.json | 精确部署修订来源、移除遗留字段后的零局核验 |

## Result and decision

双DSW通用SSH对战执行链IMPLEMENTED / VERIFIED；已部署可用，Notebook取消需求由同一轮记录承接。本文工程烟测门通过，不授予模型晋级、风格或正式验收PASS。两机重复测量数据不能扩大棋力样本；完整数据见30表阅读件。不修改M63原失败记录，原正式评测仍0局。

## Known limitations

实际8h Pod替换/平台关机、自动启动钩子、跨Pod恢复实机尚NOT_RUN；仅实现并测试实例身份与恢复判据。后台独立不能阻止平台回收；派发半成品不会自动补跑。停止/恢复安全性主要由合同测试覆盖，烟测验证自然完成路径。资源是采样软限额；未知推理/决策延迟NOT_MEASURED。名义32GB不等于实际可用32GiB。小烟测无法排名DSW与DSW2批量速度。当前版本未提交/push，旧Git clone不包含该源码与ignored模型。

## Next authorized gate

后续通用任务直接调度两台自有目录，先profile、固定模型/对手/种子/有界预算并prepare再start；DSW2优先有限对战分片，DSW适合需持续在线任务。实际跨Pod/吞吐校准另立有限工程范围。M63 R1正式执行仍需独立授权原评测修订，不由通用SSH部署推断；不自动开启PPO。

## 2026-10-05 01:35 排程估算与链路观察（只读）

用户询问睡前验收时间。按完整576开发+9,728独立=10,304局、迁移后假设DSW3路/DSW2 6路，运行阶段含统计/阅读报告粗估DSW40–70分钟（排程留90分钟）、DSW2 25–50分钟（留60分钟）。基线是M62 cloud1 3,084.918秒/9,280局，再按容量粗缩放并留负载/报告余量；不是两台正式吞吐实测，8局烟测不能证明该预测。正式迁移准备/运行时校准未完成，准备时间另计；未据估计放宽原M63 cloud1/200%资源或启动任何新局。

北京时间01:35只读SSH：DSW可达、load1m约0.08、可用13.53GiB；DSW2两次exit255，跳转均Connection refused。只证明本次SSH链路不可达，不能判定DSW2实例死亡或隧道根因；没有重启/修改隧道。今晚优先安排DSW；DSW2预算以恢复可达为前提。历史双机烟测PASS保持，当前不能把DSW2称为立即可调度。证据local-artifacts/prism/dsw-m64/acceptance-eta-{resource-probe,dsw2-recheck,planning}.json。

## 2026-10-05 DSW2停机补充与正式任务去向

用户补充DSW2约1小时无操作会自动停止；01:35 SSH拒绝连接的观察保留，停机原因属于用户提供的环境说明，并未修改其自动停机或隧道配置。当前正式M63任务已按用户选择在持久化DSW独立root以R2启动，M64烟测仍为开发/基础设施证据，不转化为正式验收。见[M63 R2](m63-prism-beta-timed-building.md)及[可读进度](prism/m63-dsw-evaluation-status.html)。

## 2026-10-05 对战吞吐反馈与满核校准 — AUTHORIZED / 用户延期到明天

用户要求所有后续时间报告必须同时给出实际并发配置、每分钟物理局数和每1,000局分钟，区分实测吞吐/理论推算/最终统计与报告耗时。用户希望充分使用4核DSW，并实测接近极限后选择稳定均衡配置；明确要求明天再测，今晚不改变M63 R2冻结执行或新增性能诊断局。

2026-10-05 02:37只读核对：M63 R2仍有3个worker、3 CPU affinity，原执行SHA不变、owner生存、重试0。开发576完成、独立3,501完成，总4,077/10,304。与02:19:40独立1,041局相比，1,040.115秒新增2,460局，实际**141.907物理局/min，1,000局7.047分钟**。这是含分片启动、对战及保存文件的独立验收窗口，排除末尾全量回放统计和报告；不使用单局process时钟的倒数替代campaign吞吐。

| 配置 / 证据 | 有效CPU / workers | 物理局/min | 1,000物理局 | 状态 |
| --- | --- | --- | --- | --- |
| 当前M63 R2窗口 | 3 / 3 | **141.907** | **7.047分钟** | MEASURED |
| 全4核简单线性推算 | 4 / 4 | 189.210 | 5.285分钟 | NOT_MEASURED；仅乘4/3 |
| 4/5/6workers稳定最佳值 | 4 / 待测 | NOT_MEASURED | NOT_MEASURED | 明天诊断校准 |

8GiB是预算上限，当前对战观察进程树RSS峰234,684,416bytes≈0.219GiB；它是RSS求和，共享页可能重复计数，非独占cgroup实际内存且不含尚未开始的最终统计峰。现有配置没有用全部4核；增加内存上限不会自动提高对战速度。短时CPU采样省略临时短命进程，只作下界，load average不作为CPU利用率。

明天独立基准计划：固定模型/对手/模式/seed，3/4/5/6workers都允许全4核，库线程1，每配置256物理局、两次重复，最多2,048次诊断物理执行/1h/8GiB聚合RSS/0自动比赛重试；同逻辑对局跨配置重复用于性能复现，不计作更多棋力样本。记录分段时钟、CPU、RSS、失败、主机响应/内存余量、动作/终局一致性（忽略时钟/路径），选吞吐位于最快5%内且稳定的配置；不能假定4或6workers一定最好。采样前另冻诊断输入和预算，结果NOT_RUN，当前0校准新增局。

证据`local-artifacts/prism/m63-dsw-r2/{throughput-observation-5,throughput-summary}.json`；[可读进度/吞吐表](prism/m63-dsw-evaluation-status.html)。ALL工作台已按实测运行位置DSW同步M63进度、报告和明天planned校准任务；Agent心跳只是本次观察，结束交互后不持续生成，不能将ALL控制器采样SSH超时解读为此实测任务死亡。未改变SSH隧道、正式权重/seed/十门/资源/原失败。

ALL校准工作项ID：`9a7dbf5d-88ce-4280-8716-5963d8d6788e`（planned，DSW，用户延期到明天）。本次最新执行观察02:44:14仍在ACCEPTANCE_RUNNING，独立记账4,647/9,728，原执行及owner绑定有效；ALL记录的是该实际观察，不把节点采样超时当作进程停止。


## 2026-10-05 greedy candidate compatibility

Generic SSH/Notebook arena now accepts explicitly declared greedy candidates, via `validate_arena_config`. Saved config and effective argv both retain `agent-prism`. Descriptor/path/seed/asset validation is reused from the frozen sample-only evaluator; that evaluator and frozen M63 runtime files are unchanged. The generic completed-shard checker also uses this adapter. 32 arena tests pass, including greedy completed-receipt verification and unchanged legacy sample-only rejection.

M63 report supplement used a separate `/mnt/workspace/splendor-m63-greedy-report-r3` snapshot, three workers, 8GiB observed tree budget; original M63 remains untouched. Completion/audit failure revealed one missed sample-only call site; original failed status and plan are retained, 46 completed games reused and two aborted games manually restarted. The generic runner still refuses automatic partial-shard respawn. This was an owned explicit repair, not a generic retry-policy weakening. The sequential launcher also exited prematurely on a transient STOPPED_SAFE state; its arena remained running, and a separate watcher awaited verified common completion before starting the direct grid. No simultaneous six-worker run occurred.

Performance calibration across 3/4/5/6 workers is still NOT_RUN. The greedy supplement's throughput is not a replacement for that task because workload/mode/clock scope differ.

## M65执行中的M64满核校准完成 / 2026-10-05

既定3/4/5/6路×两次×256局已完成，2048执行、256独立逻辑对局，逐局动作/结果一致；0自动重试。正常采用4路，校准325局/min、1000局3.08min；最快6路334局/min。完整速度/时钟/RSS见[校准报告](prism/m64-dsw-throughput-calibration.md)。34工程合同测试PASS。旧NOT_RUN记录保留作历史，本节覆盖当前状态。
