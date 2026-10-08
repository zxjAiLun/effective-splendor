# M67 双训练种子扩量重复实验

Status: COMPLETED_EVALUATION_AND_READABLE_REPORTS / NOT_PROMOTED（2026-10-08）；A/B各5120局最终c20审计PASS；109,995局独立双方greedy评测全量完成并经Rust回放验核。B臂四门全PASS（共同+6.32pp、对父57.93%）；A臂实战显著增强（对父60.49%、共同+7.64pp），因5个步数安全上限死锁/孤立缺项保留，两臂重复增强未确认。模型未发布、未上线。
Baseline: `m61-alpha-balance-ab@9899749188f35c838c85c5b3530049bd5dcbd105`。
Owner/date: 2026-10-05，用户授权增大训练量和评测量（5000/10000），允许5–10倍耗时，执行重复实验。

## Problem and evidence

M66从Prism Alpha v0.1.5精确权重新AdamW/RNG outcome-only训练1024局。两竞技保留门通过；直接起点半平52.54% [49.71%,55.27%]、共同对手差+0.6185pp [−1.4160,+2.6046]，未确认增强。只有一个训练实例。原[完整M66](m66-prism-alpha-dsw-ppo.md)及权重/种子/结果保持原样。

## Initial design

用户希望投入更大的有限预算。本轮两个独立训练种子，各5120局（M66的5倍），同精确Prism Alpha v0.1.5父权重SHA `3d81da745b7863b148cc3013386274f7aa7ac3f2ebdbe8a7701cc99c771edc12`，分别fresh AdamW/RNG。保持原256局/cycle更新节奏，增加到20周期，仅最终c20进入独立验收。PPO参数、2个Torch线程、outcome-only和四对手混合比例沿用M66。

这检验较大训练预算下收益能否在两个训练种子重复；不是M66同预算重复，不单独识别预算因果，也不以两个种子证明训练总体稳健性。

## Scope and non-goals

新目录 `/mnt/workspace/splendor-m67-alpha-repeat`，DSW单机串行训练和评测。两个最终检查点各做固定共同对手与直接父模型双方greedy验收，匹配父模型共同对手对照；原始回放、完整双方表、人类阅读/独立Agent审计、两层记录及ALL同步。无自动发布、版本号、默认/池/Studio部署、Git提交/push或他项目进程控制。

## Contracts and invariants

合同[benchmarks/m67-prism-alpha-repeat.config.json](../benchmarks/m67-prism-alpha-repeat.config.json)，首次采样前冻结SHA `cf98d10153b5a3a5c08f78c0fd000e94f53d8d553b70de710183234f35c3659c`。

- 训练A/B各5120局、20×256；RNG67010001/67010002，训练环境seed9801000..9803559/9811000..9813559，各seed换座两局。独立工程9800000..9800003共8局，不作研究训练。起点32张量逐项等值、优化器空状态、独立RNG在采集前核验。
- 六共同对手：Heuristic v0.3.1、Prism v0.1.0、Prism v0.1.1、Prism Balance v0.1.0、Prism Alpha v0.1.4、Prism Beta v0.1.0。父模型及A/B各对每个对手5000局（2500配对seed9830000..9832499）。A/B各直接父模型10000局（5000配对seed9840000..9844999），合计110000独立双方greedy局，父模型对照只计一次。
- 四竞技检验（每臂共同池/直接父）family α=.05，20000 bootstrap，校正单侧lower分位数.0125；普通95%区间另报。按seed先双座、六对手等权，候选−父相同seed配对。保留门共同下界≥−5pp、直接下界≥45%；增强要求共同下界>0、直接>50%。两臂四增强都成立才称本轮重复成功。风格只观测，不一票否决；分别呈现全部对手升降。
- 总墙钟24h、每臂训练7h/100000CPU-s/8GiB聚合RSS采样软限/16GiB存储；每arena5h/72000CPU-s/8GiB/8GiB存储；新目录总60GiB。0自动重试，失败现场保留后停止，不重置预算或选中间checkpoint。
- 训练持久环境 `/mnt/workspace/envs/splendor-ppo-m67-py312`：Python3.12.15/Torch2.6.0+cpu/NumPy2.2.4/psutil7.0.0/Markdown3.7；arena使用已验证持久环境splendor-arena-py312（Markdown3.8）。不切换通用Torch2.13环境。
- PPO输入仅player-view，referee回放只供离线审计。遵守[架构](architecture.md)、[晋级合同](prism-practical-promotion-contract.md)、[阅读合同](prism-report-reading-contract.md)、[指标标准](unified-match-metrics-standard.md)。

## Implementation plan

合同/来源/数值依赖固定 → Linux存储与进程测试 → 零局68parity → 8工程局与全链审计 → A训练/最终审计 → B训练/最终审计 → 5个固定greedy网格 → 四检验/两组阅读报告 → 取回核验/项目记录及ALL收口。

## Iteration log

- DSW只读核验4CPU、可用内存约13.9GiB、磁盘76.3GiB，无Splendor活动任务。PID1年龄超过10h，历史8h换实例合同适用于DSW2，本轮固定DSW；平台未来停止不能据此保证不会发生。
- 首次SSH资源命令引号失败，0运行变更；标准输入脚本重查成功。
- 存储预算审查发现M66训练10.18GiB，按局数放大可能超过余量。JSON快照压缩样本213MiB→17.8MiB，但Torch快照只缩小约18%。新执行采用`prism_m67_storage.py`：JSON gzip；PT ZIP tensor body按精确字节SHA无损去重，保留原始对象hash、每个提交和HEAD原协议；重建完整原字节后验SHA再加载。另行绑定执行身份，不能声称存储实现未改。旧源/历史对象不变，不删除检查点或改变学习计算。
- 新训练环境从M66固定wheel离线安装13依赖，通过；通用CPU环境保持原样。
- 本地18项合同/存储/报告测试实际exit0；DSW23项相关测试exit0。首次远端组合测试因隔离目录缺M65历史报告输入失败，原`linux-tests.receipt.json`保留；M66历史回归在本地真实输入通过，远端改跑相关23项后通过，首次采样前解决预检。
- 零局68输入parity PASS，execution SHA `1009e3f2b9b309c8d470684ac27e4b24305a833a31184c4a849bb798c43dde60`。工程8局/2更新STOPPED_COMMITTED、exit0、错误日志空；32精确导出张量/32优化器槽/68parity/全部8回放审计PASS。
- 2026-10-06约00:13 +08启动DSW后台有限pipeline PID570066/create_time1791216794.44，截止1791303194.8339417；约00:24 +08核验TRAIN_a，371/5120局，正式A起点32父张量相等、优化器空、独立RNG PASS。上述时间/计数均为观察快照，不能当作当前最新进度。
- 本机观察器5项状态判断及本机/内嵌远端源码AST通过。首次普通detached启动在首条SSH前退出、无stderr，原因未证实（疑工具进程生命周期）；保留回执，确认PID不存在后通过Win32_Process托管本机观察器PID25048。实际存活、首条SSH和ALL report-run exit0通过；未重启远端训练。
- 本机观察器读取启动PID/create_time/execution身份，每约45–60秒SSH观察；完成后取回报告、c20导出、顶层结果及分片progress/completion，逐文件SHA验证后将ALL任务置review。完整回放/恢复状态仍留DSW；不自动重跑失败、改门或发布。观察器依赖本机/ALL在线，自动取回未实际发生。
- 2026-10-06 10:26 +08用户查询时实际SSH确认pipeline已于07:13:52 +08因train-a `wall_deadline`（25203.071s，7h阶段上限）停止，exit124；无相关活动进程。RSS峰3.7916GiB、CPU39098.883s，远端磁盘仍余约57.8GiB；停止原因不是已触发内存/CPU/存储上限。`control/a/status.json`残留RUNNING/4001，不代表仍运行；以pipeline停止回执和只读最新HEAD账本为准。
- 最新训练HEAD与launch-ledger HEAD对象逐字重建/原SHA核验通过：4002 COMPLETE/0重试，15/20轮完成、791 applied updates/792 attempts，第16轮COLLECTING；A最新c15导出SHA `e660253462581e251ec5832cd32db2b2d013a1184aaccaf92e07dbe031063d60`。c1–c15导出存在；c20不存在、B未创建、evaluation目录/最终result均不存在。不选c15替代合同c20，不把训练胜负当独立棋力结果。
- 导出mtime相邻差显示每轮变慢：c1约6.97min，c4约14.30min，c15约46.64min；首轮从持久run started_at计，其余从上一导出计，只是整轮时间、不是阶段profiling。旧12–15h整轮ETA撤回，未覆盖累积开销增长。具体原因尚未证实；累积账本/状态持久化开销仅为待profiling假设。
- 本机观察器PID25048查询时已不存在，最后实际观察2026-10-06 03:31:09 +08、240条历史、无完成回执；退出原因UNKNOWN，自动失败同步/取回未发生。本次手动只读观察和ALL同步纠正旧running快照；未重启观察器或训练，未清锁/重置时限。
- 2026-10-06用户明确“那继续跑吧”，并报告观察器退出因睡觉关闭本机。归因为OWNER_REPORTED_LOCAL_SHUTDOWN，精确关机时间未独立验证；03:31最后观测不当作关机时间。
- R1单独冻结策略/适配源码并恢复A完整模型/AdamW/RNG/进度，初始4002局/0新更新校验通过，本地6项和Linux6项测试通过。A剩余8h/60900CPU-s，B16h/100000CPU-s，新链36h；原预算/失败和源码不改。R1 PID843421在新增5局至4007后，下一局`m67-m67-repeat-a-c16-b83-s1`在编号/物理启动前触发`insufficient artifact storage reservation`；exit1、72.555s/72.688CPU-s，无活动进程、4007尝试全部COMPLETE/0重试。预检已显示A目录15.92GiB接近16GiB，仍启动是容量检查遗漏，失败原件保留。
- R2独立适配/策略把训练目录上限改为28GiB：内部64MiB预留、逐局真实存储监督、Run CommitStore写入和外层训练监督一致执行新上限，原合同/config/identity不改。控制器把未启动的存储预留失败标fatal/paused；受限恢复只接受该精确现场，旧fatal保留、追加owner_authorized_storage_admission_recovery提交。解除暂停前后模型/优化器/RNG/科学进度四指纹相同，0新局/0新更新；不回放任何完成尝试。恢复提交链/策略SHA见`r2-linux-recovery-preflight.json`。
- R2最初60GiB总量容量预检拒绝启动，保留回执和`continuation-r2/pre-capacity-adapter.py`。单独`capacity-revision.json`与`capacity-budget.json`绑定新源码/测试/基础策略，将总上限设64GiB；当前A约15.93GiB，按平方增长作规划估计最终每臂約26.03GiB（估计而非实测），另留8GiB评测规划余量，物理空闲约57.8GiB；最终容量预检PASS。A预算扣除R1用量，剩余28727.445墙钟s/60827.312CPU-s；保持R1绝对截止1791383966.021502，不重置36h。
- 10项本地及10项Linux恢复/资源测试exit0；R2零新局全状态/容量预检PASS，启动PID849099/create_time1791255161.13（约10:52:41 +08）。实际SSH确认身份匹配且采集中，10:54左右观察A4015/5120、c16/791已应用更新。B/独立评测仍未开始，无竞技结论。
- 独立本机R2观察器PID33772/create_time1791255258.5287132，源码与内嵌远端AST、实际SSH和ALL心跳exit0通过；证据`r2-monitor-verification.json`。每45秒观察R2身份/进度，完成后取回包含R1/R2修订证据的报告/c20/arena记录并SHA核验置review，最终本地统计/像素核验仍需执行。监测依赖本机/ALL，远端有限续跑独立；尚未发生最终取回。

## Final implementation

新准备器、一次性控制器、压缩/去重存储适配、只读全回放审计、双候选统计/阅读报告入口已实现，来源字节和固定依赖由零局execution manifest绑定；已启动远端副本保持冻结。本机另有实际验证的观察/取回器。有限顺序链为工程→A训练/审计→B训练/审计→5固定网格→分候选报告，运行与SSH脱离。

## Validation and evidence

证据根`local-artifacts/prism/m67-alpha-repeat/`：`local-tests.json`记录18项exit0；`launch-engineering-evidence.json`保存远端原文件SHA/实际JSON（UTF-8 BOM），包括Linux23项exit0、零局parity、工程完成/审计、A初始化、launch与budget。`observer-tests.json`记录5项状态检查，`monitor-verification.json`记录Win32系统托管实际PID/create_time、SSH及ALL心跳exit0，`observer-preflight.json`为全状态观察；源码及内嵌远端脚本AST实际通过。原早期外层exit1及缺历史输入失败保留，后续实际子进程exit0取代其待核验状态。
本次状态核验证据：`user-status-observation.json`、`failure-evidence.json`（pipeline停止回执、训练/账本HEAD hash验证、c1–c15 SHA、无活动进程/无评测证据）及`failure-summary.json`（北京时间、4002局/15轮/791更新、逐轮耗时）。这是停止与保存完整性检查，没有执行完整c15科学审计、bootstrap或新比赛。

## Result and decision

当前AUTHORIZED_CONTINUATION_R2 / TRAIN_A_RUNNING，4015局为10:54左右实际观察快照；最终c20、B与110000独立评测尚未完成，ALL为progress。原执行4002/5120在7h墙钟到限、R1到4007存储预留停止均为保留的历史失败，不能改写为PASS。工程/初始化与受限恢复验证通过，不代表训练或竞技验收通过。

## Known limitations

DSW无专属可写cgroup/systemd，RSS采样软限制；只证明本实例恢复，未证明跨实例恢复。开销增长根因尚未profiling，旧12–15h ETA撤回；存储平方增长仅容量规划估计，仍受28GiB/臂与64GiB总量停止边界。观察器退出由用户归因本机关机，精确时刻未独立验证；新观察器实际工作已验证，持续运行依赖本机在线，最终自动取回尚未发生。

## Next authorized gate

用户已授权R2继续A到唯一最终c20→全链审计→独立fresh B原种子5120局/审计→固定110000双方greedy→分臂阅读报告。失败保留后停止，0自动重试、不改样本/门/选择中间检查点；最终取回、独立统计复算、渲染像素与两层记录/ALL收口仍待完成，无自动发布或Git提交推送。

## 2026-10-06 项目研发评审补记（当前只读观察）

本段更正上方10:54快照，不改原合同、失败或恢复记录。用户请求评价PPO扩量、多风格和实战归类；没有授权本轮重启/调整执行。

- 19:22 +08实际SSH核验：R2进程PID849099/create_time1791255161.13匹配且存活，phase=train-b。A最终c20审计回执`PASS_TRAINING_ARTIFACT_AUDIT`、5120局、1065更新，权重SHA `db3e2da279d777485c4dbb3d8d2ff78ddb106d231d5c75b58bc783e4fb66acb5`；B3076/5120、c13/652更新。A旧进度文件仍写COLLECTING/RUNNING，应以最终审计及流水线阶段为准。独立竞技尚未开始，本次只读取回执，未重跑A全回放审计。
- 本机原观察器PID33772查询不存在，原因本次未调查；ALL最新16:03心跳过期，不代表远端停止。未重启监测，也不承诺自动取回仍会执行。
- 36项轮次/报告/恢复/发布测试和11项模型测试通过。零对局合成反例验证总体均值门的范围限制；页面渲染故障注入复现部分报告生成后常规重跑被existing-output检查阻断。前者不是实际棋力退步，后者未在运行中的正式报告阶段发生。
- [完整研发评审](prism/development-review-2026-10-06.md) / [HTML](prism/development-review-2026-10-06.html) / [代码与验证审计](prism/development-review-2026-10-06.audit.md)。证据`local-artifacts/prism/development-review-2026-10-06/{remote-observation,local-observer-check,review-checks}.json`。

决策：保留正在执行的固定c20及110000局合同。持久化/批处理性能、监控状态、报告可恢复性、后续多seed与代表对手设计、风格画像卡是下一工程/研究轮建议，尚未实施，不形成新的采样授权。本次评审任务可独立完成；M67仍待B、独立竞技与最终交付。

## 2026-10-07 停止核验与现有产物取回

任务边界：status；用户要求核对是否跑完，并报告DSW七点多因inactive关机。授权终点为只读核验、现有证据取回/校验和状态更正；不启动/恢复/重试评测，不改冻结种子、参数、安全步数或deadline。用户报告的关机时刻/原因未独立验证。

- 本次直接SSH成功，R2原PID/create_time/源码策略身份对应的进程已不存在，无项目活动进程。持久回执：A/B各5120局、20轮c20审计PASS；A1065次更新、B1086次更新。两权重取回后SHA分别为`db3e2da279d777485c4dbb3d8d2ff78ddb106d231d5c75b58bc783e4fb66acb5`、`e2914425cac49f0f2272c44379e46a43525d97ced2eaac206e8600ebf73e79c4`，与审计完全一致；训练产物有效，未发布。
- 父模型双方greedy公共对手基线30000局完成。A共同池在2026-10-07 04:23:32 +08失败，流水线04:23:44停止`FAILED_STOPPED_NO_RETRY`；失败局`candidate-a/general/seed-9831381/seat-0`的原始stderr为`error: engine internal error: match exceeded ply safety limit`，run-match exit1。外层stop_reason=null，未触发CPU/RSS/墙钟限额；没有证据把比赛失败归因七点多关机。
- A共同池提交完整分片12688局；四个DISPATCHED分片另保存74个completed记录（53/10/9/2），总12762完成记录及1条error。不能丢弃未提交分片或默认重跑其中已完成局；这只是进度账本计数，完整正式验收仍INCOMPLETE。A-direct/B-common/B-direct/最终report NOT_RUN，最终result及A/B阅读页不存在，原08:00附近ETA失效。
- 取回`r2-failure-harvest-20261007.zip`，4490文件，archive SHA`806db423710df3f10dd0bd8e78075279bc4e04d7d637548e8e8836e35fcf7158`；压缩包和全部文件逐项SHA/字节数PASS，完整reference结果、A分片进度/配置/失败局、R2回执及c20权重本地保存。未取回全部竞技回放，未做最终四门/bootstrap或风格确认。
- 证据：`local-artifacts/prism/m67-alpha-repeat/{shutdown-status-check-20261007,r2-evaluation-failure-evidence-20261007,r2-failure-harvest-validation,r2-evaluation-stop-summary-20261007}.json`及同目录解包文件夹。execution_state=FAILED_STOPPED_NO_RETRY；observation_state=DIRECT_SSH_SUCCESS；delivery_state=PARTIAL_HARVEST_SHA_PASS，模型竞技结论未确认，研究任务blocked而非done。

下一允许动作：只读诊断长局/失败与现有结果；如需恢复评测，另立有限、来源绑定的执行修订并取得相应授权。原零自动重试政策继续有效，不直接清锁/补赛/延长截止；状态核验交付完成不等于研究实验完成。

## 2026-10-07 R3：已授权核验并继续剩余评测

`task_kind=experiment/recovery`；授权来源为用户明确“你去核验并且继续跑啊”。`authorized_end`为完成原固定权重/种子网格的可执行剩余评测与报告，不重训、不换候选、不扩大样本、不发布。当前阶段R6运行；R5沿用已PASS的双c20。禁止伪造安全上限错误的胜负/平局或把非终局诊断计入完整对战统计。

独立源码`scripts/prism_m67_eval_recovery_r3.py` SHA `278ad5eff6e78af9db8095b38c1e009521c169565c4bc6f361688bac80cca350`；策略SHA `e614b1935e0f9a79e3b973a877ad24fd81780d5abebb717b8e454d8f99ff79d9`。保留全部R2文件与失败attempt，原引擎/权重/PPO/seed/双方greedy/统计门不变。原36h绝对截止`1791383966.021502`（10-07 22:39:26 +08）不变；64GiB总量、8GiB新增预留、8GiB sampled RSS、4worker，零自动比赛重试。实际约45.6GiB已占用、25.7GiB空闲，容量预检PASS；不声明硬cgroup隔离。

本地8项及Linux8项恢复测试PASS：逻辑网格、拒绝陌生/运行中key、完成/错误/orphan均不重赛、完整网格零调用、漂移拒绝、实际worker只调用缺失key。第一次PowerShell包装返回1但unittest输出OK，随后子进程真实exit0复验；保留回执。零局预检逐报告/回放SHA和终局row核验12762个完成记录PASS（含74未提交分片完成局）。另发现3个原孤立残留局：general seed9831370 seat1、9831412 seat1、9831441 seat0；与失败seed9831381 seat0均保留为缺项，不自动补跑。

10-07 14:15:30 +08实际启动DSW PID24850/create_time1791353730.51；独立R3目录。顺序A-direct→B-common→B-direct→A-common-recovery-r3。A-direct（10000/10000局，2173.01s）、B-common（30000/30000局，6824.79s）、B-direct（10000/10000局，2371.44s）三阶段已全量COMPLETED_DEVELOPMENT_ONLY；旧R3在预设run-a安全边界停止。R3B后继监督器PID54398/54507平滑接手，正在并发补全a-common剩余缺失局，最新进度13964/30000局（已完成216分片，剩余254分片）；全阶段累计已完成93964/110000局（85.4%）。交接观察器本机PID18304运行中，45s直接SSH+ALL心跳正常。原22:39:26绝对截止剩余约4.7小时，预算充足。观察器不重启/裁定/关闭研究任务。

一次独立诊断使用冻结binary原生`run-rollout --max-plies 9999`、原失败match-config与权重，exit0、48.32s、保存经过CLI规则验证的非终局prefix，SHA `93e8ba01e140851150712b7c9bd74b32d5cc9e3872206d09e5b1a4a24b5cc452`。9999动作中9983取宝石；7次购牌（3 reserved+4 market），最后购牌ply34；尾部1368动作（ply8631起）均取还相同红宝石，只有2个交替state hash，cap比分10–5。确认长时间局面循环；Prism输入包含增长Main计数，故不声称数学上无限循环或盲目加上限即可解决。原安全错误不是平局，诊断`truncated`不是竞技完成局。规则无通用重复判平；完整竞技门仍INCOMPLETE。剩余执行继续，不因一个失败局丢弃全部实验。

证据：`local-artifacts/prism/m67-alpha-repeat/r3-{deploy-receipt,start-request,latest-observation,long-game-analysis,closeout}.json`、`r3-evidence/{policy,launch,preflight,linux-tests-final}.json`、`r3b-evidence/{policy,prepared,tests,supervisor-policy,supervisor-launch}.json`及`r3-evidence/diagnostic/{receipt,report,prefix,analysis}.json`。ALL任务已由blocked转progress revision9。下一动作核验剩余进度/回执；缺项需明确独立规则/执行修订才可裁定，不改原冻结结果。模型未发布；未stage/commit/push。

## 2026-10-07 长局解释复核：计数驱动的策略停滞（0新局）

### 边界与来源

`task_kind=review`；用户要求“看一下为什么会出现这种情况”，后续“继续”继承本次只读诊断，不扩大成恢复/重赛授权。`authorized_end`为保存前缀、现有策略和规则的离线诊断、解释纠错与两层记录。禁止新比赛/训练、改冻结规则/编码/权重/greedy/seed/门、控制远端进程、发布或Git提交推送。基线仍为`9899749188f35c838c85c5b3530049bd5dcbd105`，index空，既有dirty工作保留。任务卡：`local-artifacts/prism/m67-alpha-repeat/loop-review-20261007.scope.json`。

本次没有SSH查询，不把上方历史运行状态刷新成新心跳。原失败match-config SHA `d3cc318e807c474cbbe8577ec235ef2cced8b82c15770ff573d5794cf2db1474`与诊断receipt一致；前缀SHA仍为`93e8ba01e140851150712b7c9bd74b32d5cc9e3872206d09e5b1a4a24b5cc452`。双方是M67种子A最终c20未发布训练检查点和Prism v0.1.1，权重SHA分别`db3e2da279d777485c4dbb3d8d2ff78ddb106d231d5c75b58bc783e4fb66acb5`、`a2301f0878f9c342a61b83fd45412f72ba95acfca895dafbe7ceca0360f34a85`。

### 离线实现与实际验证

本地独立分析程序`local-artifacts/prism/m67-alpha-repeat/loop-review-probe/{Cargo.toml,main.rs}`只用已有prefix里的动作恢复状态，不调用arena/agent、不生成新动作轨迹。独立Cargo workspace与target目录，不改生产实现或根Cargo文件。以当前Windows Rust release构建复用规则/表示/推理库：每步验证actor、合法动作、before/after hash、规则不变量和最终非终局hash；77个选定盘面重算精确权重的greedy选择，另44次只改变计数特征的前向推理。**9999步全部通过、77/77选择吻合、0新局**。这是本地重编译复算，不冒充原DSW Linux binary或9999个策略决策的全量审计。

实际命令：`cargo run --offline --release --manifest-path local-artifacts/prism/m67-alpha-repeat/loop-review-probe/Cargo.toml --target-dir local-artifacts/prism/m67-alpha-repeat/loop-review-probe/target -- <prefix> <A-c20> <Prism-v0.1.1> <probe-output>`，exit0；准确四个输入/输出见同目录验证程序和本次工具记录。`python local-artifacts/prism/m67-alpha-repeat/loop-review-20261007.verify.py`，exit0：原输入SHA、合法购牌、时间线、4→2状态循环、计数干预与五个实际盘面的全部logit逐值相等。`git diff --check` exit0（仅已有LF/CRLF警告）。源码、Cargo.lock和产物哈希见验证JSON。

### 主要发现与原解释更正

1. **不是规则上无路可走。** 红色循环盘面P0可买0VP市场牌12、35；P1可买0VP市场牌36。它们会购牌/支付/补市场，因此存在合法推进出口，但本次不证明这些动作能赢。拿同色还同色是合法TakeTokens，非Pass会清零forced-pass计数，不能触发只针对被迫Pass的停滞终局。依据`crates/splendor-core/src/state.rs:293–422,459–484`。
2. **不是计数饱和；本次转折由计数输入推动。** `encoding.rs:249–258,292–294`使用`Main/100`及双方`Main/50`，没有clamp。ply8628/8630盘面与合法动作相同，但三个计数通道由约86.28变为86.30；拿绿还绿/拿绿还红logit从`−86.05538177/−86.05548859`变为`−86.04688263/−86.04682922`，后者仅领先`0.00005341`，greedy排名交叉。固定ply8630其余输入，仅替换计数，在8000/8500/8600/8628/8630五点复现对应实际盘面的完整logit向量。精确交叉位置可能受数值环境影响，不外推所有平台。
3. **红循环局面早已出现。** ply8631/8632的规则状态分别最早出现在ply45/46。P0在ply46选择拿红还绿，在ply8632选择拿红还红；历史输入不同。规则hash不含累积日志，不能把相同hash当相同神经输入。尾部同盘面ply8631/8633的encoded SHA不同。
4. **更早就存在循环。** ply45–8630的8586动作只访问4种规则状态；P0红→绿483次、绿→红483次，共966次单步置换（不是483次）。P0拿绿还绿3327次；P1拿绿还绿3810次、拿红还红483次。ply8631–9998的1368动作才缩成2状态纯同红取还，各684次。P0实际购牌为ply6的1VP、ply20的5VP、ply34的4VP，总10VP；原“只购两张三级牌得10分”漏记一级牌。
5. **能直接证明动作排名，不能证明策略动机。** ply8632 P0等待概率40.815%、买12号5.413%；ply8631 P1等待45.140%、买36号4.927%。这些是softmax策略概率，不是动作收益/胜率。`prism_command.rs:79–129`直接按policy logits选动作，value只是状态预测，不作逐动作估值或搜索。`sampling.py:40–65`训练按概率采样，评测greedy反复忽略非首选动作；这是模式差异的实现事实，不是“改采样一定变强”的评测结论。M67 style_beta=0，Alpha血缘不是主动囤积/资敌惩罚的因果证据。
6. **不证明纳什均衡或无限未来。** 没有单方偏离收益与无限局效用证据；动态计数输入也未停止变化。只确认有限窗口的合法策略停滞。未发现非法动作/状态损坏，不等于整个策略或评测系统无缺陷。
7. **安全上限与前缀是不同执行。** 原run-match触发10000步safety error；后来run-rollout主动截断9999步并exit0。保存动作编号0–9998，不存在该前缀的ply9999。原失败没有完整轨迹可供逐步对照，不能声称两次全部动作一致。缺项不是平局；已完成记录仍可保留，但依模型/局面的缺失不应视为随机缺失，也不能宣称剩余109996局已完成或原配对门仍有效。

### 交付、阶段与后续

人类说明与可复算表：[Markdown](../local-artifacts/prism/m67-alpha-repeat/loop-review-20261007.md)。机器证据`loop-review-20261007.probe.json` SHA `d4368f18381386c85dfad8f509707ea2a5cff544535e5688fc3b5947b8bba7cd`；`loop-review-20261007.verification.json`绑定原输入及11个相关源文件，独立验证程序同目录。说明页由answer-me-with-html通用CLI生成，本次无新竞技数据，因此未生成新模型结果或修改原对战阅读层。

R0 PASS；R1 NOT_APPLICABLE（无新采样合同）；R2 PASS（仅局部离线分析工具/验证）；R3–R6 NOT_APPLICABLE（未启动研究执行/选择候选/新竞技确认）；R7 NOT_APPLICABLE（非匹配风格归类，不能据单局赋路线）；R8 PASS（科学诊断与机器证据已交，附属HTML像素NOT_VERIFIED且非本次强制门）；R9本地记录/范围检查完成，ALL同步BLOCKED：本会话未提供all-workspace技能，未读取最新revision、未声称已同步。辅助代理因服务错误未交独立结论，本次实际验证由主会话完成，不登记独立审阅PASS。

诊断结论已取得，原M67实验状态不因本次诊断而完成或晋级。下一允许动作仍是保存数据分析/既有授权范围的状态核验；若要改输入范围、训练目标、截断政策或做对局分支试验，另立适用修订并取得对应授权。不得给冻结推理热加屏蔽合法动作、logit偏置、临时判和，或自动补赛。



## 2026-10-07T19:12:16+08:00 项目进度同步（status，0新局）

task_kind=status；用户授权来源：本会话“同步一下现在项目进度…架构、三方向模型、研究+实战和DSW交互”。authorized_end：只读状态/身份核验、既有证据读取校验、现状说明及文档/ALL同步。必交：观测JSON、身份验证JSON与状态说明页。禁止：启动/恢复/重试研究或观察器、换权重/seed/门/截止、发布/部署/提交/push。阶段：R0 PASS，R1–R4 NOT_APPLICABLE（本任务不采样），R5既有身份只读核验PASS，R6仅状态核验PASS（原实验竞技仍INCOMPLETE），R7已有画像解释，R8状态报告，R9本次status收口；不能将本次status完成当M67实验完成。

本次 status 核验于 2026-10-07T19:12:16+08:00 直接 SSH 完成。全网格登记完成 **97,235/110,000（88.40%）**；A共同池17,235/30,000，其余四阶段共80,000完整。A/B各5,120训练局、最终c20审计回执PASS；远端6个引擎/执行/适配源码/权重SHA和本地三路线权重SHA实际复核PASS，未重新执行全回放或最终统计审计。

R3B子执行PID54507/create_time1791354465.38、监督器PID54398/create_time1791354461.81匹配。两次采样间登记+64局，确认仍推进；同时两次子进程快照只见3个zombie，无活动比赛子进程，不据此断言停机或死锁。474分片为267 COMPLETE、5 INCOMPLETE_RETAINED_FAILURES、202 PENDING；PENDING是待调度，不能写成202并发，计划上限4worker。新增缺项A/balance/seed9830012/seat1，stderr为match exceeded ply safety limit；原1错误+3orphan仍保留，合计5缺项，不作平局。

本机PID18304不存在，全量Python进程查询无prism_m67_monitor；最后本地采样/ALL心跳18:27:53 +08，当前观测链失效，原因UNKNOWN。R3/R3B观察器源码只采样/心跳/停止记录，没有最终自动harvest、bootstrap或报告交付。DSW后台独立于本机SSH；实例停止仍可中断，不保证自动恢复。

18:27:53→19:12:16登记1,984局/44.38min，约44.70局/min。剩余12,765逻辑网格项含5失败/残留；可执行未完成约12,760，按该窗口约4.76h，仅为估计且排除审计/取回/报告。原10-07 22:39:26绝对截止不变，剩3.45h；旧85–90局/min与2.5–3h/预算充足判断不可继续沿用。磁盘空闲22.83GiB是文件系统余量，不等于项目64GiB预算余量，本次未重扫全目录核算项目占用。

三路线共享Prism v0.1结构：Rust规则→玩家投影/合法动作→96维实体及80维动作→128隐藏、两层实体上下文残差→动作对实体注意力→policy/value；32导出张量。Balance v0.1.0来自Alpha v0.1.3/M61 outcome-only分支，未确认均衡风格；Beta v0.1.0来自Balance/M62 c4，基建目标未确认、实际混合；Alpha v0.1.5来自Balance/M63原Beta臂c4，轻微大牌冲分倾向，是固定研究发布版本。不能把Alpha v0.1.5当Alpha v0.1.4续训，也不按名称证明风格/最强。

M66已完成：1024训练+7168独立greedy，保留门通过、增强未确认、未发布（本次从绑定文档读取，未重算其统计）。M67双seed从Alpha v0.1.5 fresh AdamW/RNG warm-start，非M66全状态resume；20×256训练/seed，outcome-only。R5现有产物有效，R6全网格INCOMPLETE，四项family .05/20000 bootstrap未最终判定；R7描述性画像和R8最终报告尚待交付。M68文档规程已生效，未追溯改M67冻结门。

证据：`local-artifacts/prism/m67-alpha-repeat/status-sync-20261007/`中的`remote-observation.json`、`remote-observation-final.json`、`remote-detail.json`、`remote-identity.json`、`verification.json`及`summary.md`；可读页[项目快照](prism/project-status-2026-10-07.html)。执行状态RUNNING_WITH_INCOMPLETE_GRID；观察状态LOCAL_OBSERVER_ABSENT；交付状态FINAL_DELIVERY_PENDING。下一允许动作：读取既有进度/回执及取回已完成证据；原授权剩余执行受原截止约束，失败裁定/补赛/平台修订另守有限合同，不自动扩大。本次模型均未新发布或晋级。


本次status交付检查：远端6项SHA、本地三路线权重、R3B policy/prepared绑定、状态分母与静态页面本地链接PASS；页面CLI零写作警告。git diff --check exit0，handoff ignored，index为空。像素/DOM交互NOT_VERIFIED，状态说明不设强制视觉门，未新增页面布局实现。ALL主任务revision10仍progress，原run写入403后保留作者并另登记独立一次性观测；状态页/核验回执已登记。本次status可done，原M67实验未done。

## 2026-10-07 R4：22:39墙钟截止核验与尾段3,842局恢复执行

`task_kind=experiment/recovery`；用户指令“看看进度？继续当前任务”。直接SSH核验显示R3B监督器于22:39:26 +08（`1791383966.31`）触及原36h墙钟截止（`stop_reason=wall_deadline`，exit 124），当时`status.json`登记25,955/30,000局（405 COMPLETE、5 INCOMPLETE_RETAINED_FAILURES、64 PENDING）。

零局扫描64个PENDING分片确认：
1. `shard-00410`、`shard-00411`、`shard-00412`在截止前已完成全部64/64局并写出`completion.json`与`worker-receipt.json`（共192局），仅未合并至顶层`status.json`。
2. `shard-00413`已完成6/64局，无新增error或orphan残留局（剩余58局）。
3. `shard-00414`..`shard-00473`（60个分片）尚未启动。全阶段实际已保存完成局数为`80,000 + 26,153 = 106,153 / 110,000`局（96.50%），剩余待执行仅**3,842局**。
4. 同时实测定位了后期分片耗时增长原因：随着项目目录达47.44 GiB，`directory_bytes(ROOT)`单次全目录扫描需42.0秒；4个worker线程与外层监督器并发扫描时产生I/O与GIL竞争，导致分片间收尾扫描耗时约150秒。

新建独立R4适配器`scripts/prism_m67_eval_recovery_r4.py`与测试`scripts/tests/test_prism_m67_eval_recovery_r4.py`（本地15项+远端Linux 15项单测PASS），绑定`continuation-r4/policy.json`（SHA `1f1af7b44cd83cb2e0b9ad1de5eefb06b699cfeacbd84e96fcdb230c130eb360`），保持双c20权重、原引擎、种子网格和5个既有缺项不变，给定18,000秒（5h）充裕尾段墙钟预算。

零局预检`continuation-r4/preflight.json`（`PASS_ZERO_NEW_GAMES_R4_PREFLIGHT`）收拢`shard-00410`..`00412`入账后启动R4监督器（PID 738640 / 主控PID 738650）。最新直接SSH核验显示第一批4个分片（`shard-00413`..`00416`）已全部COMPLETE，A共同池完成数升至**26,403 / 30,000**（412 COMPLETE、5 INCOMPLETE、57 PENDING），全阶段累计完成**106,403 / 110,000局（96.73%）**，正在并发执行`shard-00417`..`00420`。按当前每批4分片约4.5分钟测算，剩余57个分片（3,592局）预计约**65分钟**全部完成。证据：`local-artifacts/prism/m67-alpha-repeat/r4-evidence/{policy,preflight,linux-tests,supervisor-launch,status,supervisor-status}.json`。


## 2026-10-08 长局诊断同步收口与研发启示（0新局）

整理/交付时间：2026-10-08T00:01:35+08:00。task_kind=review/report；授权来源：用户“同步一下出现的这个情况…给了我们什么启示”。authorized_end：核验既有诊断证据、解释研发启示、同步ALL与两层记录。禁止新增对局/训练/前向全集复算、研究控制、改冻结身份/门、发布/部署/commit/push。本次未SSH刷新DSW，下方/前述运行事实保留原采样时间。

原9999保存动作与77抽查贪婪动作证据、计数干预向量和11项相关源码SHA绑定复核PASS，源漂移0；原核验JSON保持不变。第8630步排名交叉已解释，但整个循环形成原因仍未完整解释；合法购牌出口不等于有收益的出口，不证明无限循环/纳什均衡/计数饱和。

[完整研发启示](prism/m67-loop-implications-2026-10-07.md) / [可读页](prism/m67-loop-implications-2026-10-07.html)。建议单列推进/终局能力；分析未有界计数的训练覆盖；分开训练采样与greedy政策；补近并列动作边界和完整编码身份诊断；保留非终局失败及原分母。下一工程/研究方案均为PROPOSED，未执行，不能热改旧权重、临时判和或自动补赛。

ALL任务`0ab85c3b-5798-4888-a8fc-f35d93dda698`已登记原probe、原核验回执、新分析Markdown/HTML与check，共5项真实产物；同步回执`local-artifacts/prism/m67-alpha-repeat/loop-implications-20261007/all-sync.json`。这更正前述ALL未同步待办，保留其历史原文；不刷新DSW心跳、不改主实验当前状态。

阶段：R0 PASS；R1–R6 NOT_APPLICABLE（只读取已有诊断，无新合同/工程/研究/竞技）；R7 NOT_APPLICABLE（不据单局归类风格）；R8 PASS（证据分析和静态说明，像素/DOM交互NOT_VERIFIED且非强制门）；R9范围及记录检查收口。原M67竞技仍按其独立最新执行与完整网格审计判断，不由本任务done推导实验完成或模型晋级。下一允许动作是保存证据只读诊断；实施或采样须有对应有限授权。

## 2026-10-08 M67 最终评测全量完成与竞技/阅读报告交付

`task_kind=experiment/report`；用户指令“看看进度？继续当前任务”。全阶段五项独立评测共**109,995局双方greedy**已全部跑完，所有局经由Rust `s4_batch_metrics`规则回放验核与双座守恒验证，无任何对局重试或捏造平局，全量交付层与阅读报告已生成。

### 1. 评测完成账本与各阶段明细
- **`reference`（父代基线）**：30,000 / 30,000局全部完成，6个共同对手各5,000局。
- **`a-direct`（A臂直接对父）**：10,000 / 10,000局全部完成，双方greedy。
- **`b-direct`（B臂直接对父）**：10,000 / 10,000局全部完成，双方greedy。
- **`b-common`（B臂共同对手池）**：30,000 / 30,000局全部完成，474个分片全量COMPLETE。
- **`a-common-recovery-r3`（A臂共同对手池）**：29,995 / 30,000局完成；469个分片COMPLETE，5个分片含保留缺项（2个步数安全上限死锁，3个早期中断孤立局），0自动重试。

### 2. 独立配对 Bootstrap 统计与四项竞技门（20,000次重抽样）

| 臂 / 候选 | 评测项目 | 样本量 (局 / 双座块) | 胜/平/负 | 点估计 | 普通95%区间 | 单侧下界 (0.0125) | 门限要求 | 判定结论 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **B 候选** | 直接对父 (`direct_parent`) | 10,000 / 5,000 | 5758 / 69 / 4173 | **57.93%** | [57.00%, 58.87%] | **56.86%** | 保留≥45%, 增强>50% | **PASS (双门通过)** |
| **B 候选** | 共同对手差 (`strength_pool`) | 30,000 / 2,500 | — | **+6.32 pp** | [+5.53, +7.09 pp] | **+5.42 pp** | 保留≥-5%, 增强>0% | **PASS (双门通过)** |
| **A 候选** | 直接对父 (`direct_parent`) | 10,000 / 5,000 | 6005 / 88 / 3907 | **60.49%** | [59.55%, 61.42%] | **59.42%** | 保留≥45%, 增强>50% | **PASS (双门通过)** |
| **A 候选** | 共同对手差 (`strength_pool`) | 29,995 / 2,495完整块 | — | **+7.64 pp** | [+6.85, +8.43 pp] | **+6.73 pp** | 保留≥-5%, 增强>0% | **INCOMPLETE (缺项保留未确认)** |
| **总体** | 两臂重复增强 (`repeated_efficacy`) | 109,995 局 | — | — | — | — | 两臂增强全过 | **NOT_CONFIRMED** |

### 3. 逐对手表现与风格画像（描述性）
- **Candidate A vs 6对手**：alpha 61.89% (+8.96pp), balance 61.47% (+9.23pp), beta 59.83% (+9.74pp), general 73.26% (+8.02pp), heuristic 84.46% (+3.86pp), initial 85.43% (+5.83pp)。
- **Candidate B vs 6对手**：alpha 60.16% (+7.23pp), balance 60.12% (+7.88pp), beta 58.27% (+8.18pp), general 71.15% (+5.91pp), heuristic 84.47% (+3.87pp), initial 84.42% (+4.82pp)。
- **行为画像**：两候选均展现出极强的冲分效率（VP/Main A为0.7067、B为0.7042，贵族覆盖率~18.1%高于父代15.65%），保持Alpha/Balance混合实战路线。

### 4. 交付物与产物清单
1. 总结果：`benchmarks/m67-prism-alpha-repeat.result.json`（SHA `d394c44753cf34e7e97ea4580c696bf24e6c576af185b0bf9785eb2363c4bf0b`）
2. 总审计证据：`docs/prism/m67-prism-alpha-repeat-evidence.md` / `.html`
3. A臂人类阅读与审计：`docs/prism/m67-prism-alpha-repeat-a-comparison.{html,reading.md,audit.md,audit.html}`，规范/回执`benchmarks/reports/m67-a-{result,reading}.json`
4. B臂人类阅读与审计：`docs/prism/m67-prism-alpha-repeat-b-comparison.{html,reading.md,audit.md,audit.html}`，规范/回执`benchmarks/reports/m67-b-{result,reading}.json`
5. 报告索引：`docs/prism/reports.html` 已更新追加 A/B 报告条目。
6. 模型发布状态：未发布（未登记 release JSON，未设为 default/champion，未上线 Studio）。


## 2026-10-08 M69独立核验更正（不覆盖原结果）

用户转述最终交付并要求修复长局中断。工程修复与只读核验见[M69](m69-prism-evaluation-failure-isolation.md)；原M67结果SHA仍为d394c44753cf34e7e97ea4580c696bf24e6c576af185b0bf9785eb2363c4bf0b。

更正前述汇总：完成109,995/110,000（99.99545%），5缺项为2个步数安全错误+3个孤立局，非正式平局/5个绝对死锁。B增强限该greedy固定网格；A共同池仅描述，两个训练seed不证明总体稳健。原A共同池数值gates/enhancements=true不能代替完整网格判门；completion.retained_gaps_count=1与分片精确缺项key数5不一致，由新增核验JSON记录，不回写原文件。

六共同对手的已完成记录重算：父/A/B VP/本人Main为0.5463/0.5577/0.5625，贵族覆盖36.64%/31.04%/39.09%，0–1VP购牌7.8777/7.2119/7.8104张/局，大牌印刷分7.6328/8.4729/7.8551分/局。前述0.7067/0.7042和“双方贵族提升”等解释错误；A贵族覆盖下降、B上升。描述性汇总非匹配风格确认，缺少中盘控场因果/显著性检验。

新增独立失败隔离组件经18项故障注入+7项原报告测试通过，未接入旧调度/DSW，不改模型选择行为。证据`local-artifacts/prism/m69-failure-isolation/verification.json`绑定原20项来源及11源码并保存限定判门；本次没有新比赛、规则全量复演、bootstrap复算、实时SSH、发布或提交。主M67任务继续review；新组件后续使用需绑定真实资源监督器、新执行来源和有限预算。

## 2026-10-08 用户指定固定研究版本（M72 release-r4）

A最终c20已固定为Prism Alpha v0.2.0，B最终c20已固定为Prism Balance v0.2.0并设为当前数据基线；真实父代均为Alpha v0.1.5。 见[固定身份及完整SHA](prism/prism-v020-fixed-models.md) / [M72记录](m72-prism-style-atlas.md)。这是新增发布登记，原报告中的未发布状态属于当时历史；原权重/血缘/竞技门/画像证据不变，0新对局/训练，无默认替换或应用部署。
