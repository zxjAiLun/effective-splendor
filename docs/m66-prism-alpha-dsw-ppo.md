# M66 从 Prism Alpha v0.1.5 出发的 DSW 有限 PPO

Status: IMPLEMENTED / VERIFIED / COMPLETED_FIXED_ROUND；两项竞技保留门PASS，增强NOT_CONFIRMED；候选未发布。
Baseline: `m61-alpha-balance-ab@9899749188f35c838c85c5b3530049bd5dcbd105`。
Owner/date: 2026-10-05，用户“来吧 别让dsw上算力等太久”授权继续接手建议中的有限训练。

## Problem and evidence

M65 已固定发布 Prism Alpha v0.1.5 和 Prism Beta v0.1.0，未继续训练。Alpha v0.1.5 来自 Prism Balance v0.1.0 的 M63 分支，轻微偏大牌得分；并未证明普遍强于所有参照。当前目标是以此精确权重继续一次有实际学习量的胜负 PPO，而非重做旧 Beta 风格门或替换默认模型。既有完整数据见 [Alpha v0.1.5](prism/prism-alpha-v0.1.5-evaluation-summary.md)、[M65](m65-prism-version-release.md)。

20:05 DSW 实测 4 CPU/affinity0..3、约13 GiB可用内存、低负载。PID1为tini，无systemd；cgroup v1专属目录创建返回只读文件系统，不能宣称有独占硬cgroup。现有对战venv无Torch；系统Torch2.13.0不直接作为旧PPO环境使用。

## Initial design

- 起点：Prism Alpha v0.1.5 精确32张量，SHA `3d81da745b7863b148cc3013386274f7aa7ac3f2ebdbe8a7701cc99c771edc12`。
- **新优化器 warm-start**：不是恢复 M63 全状态。模型架构、既有 PPO 数值内核不改；fresh AdamW/RNG，outcome-only，style_beta/style_value_weight均0。训练目的不预设发布路线。
- 4 cycles ×256 = **1024训练局**，仅最终c4进入验收。greedy训练对手配比：Prism v0.1.1 50%、起点Alpha v0.1.5 25%、Alpha v0.1.4 12.5%、Beta v0.1.0 12.5%。候选训练动作categorical T=1。
- **7168独立both-greedy评测局**：起点/候选各对六个共同对手512局，共6144；候选直接对起点1024局。六对手为Heuristic v0.3.1、Prism v0.1.0、Prism v0.1.1、Prism Balance v0.1.0、Prism Alpha v0.1.4、Prism Beta v0.1.0。
- 起点3072局可先用既有已验证arena运行，训练执行环境同时准备；不依据其结果调参。最终候选权重必须审计后才派发候选网格。训练与评测都不自动重试。

## Scope and non-goals

新持久目录 `/mnt/workspace/splendor-m66-alpha`；不得改 M63/M65 旧树。必要容器进程监管适配、零局parity、一次8局工程贯通、有限训练、固定评测、全量双方数据、共同阅读层与独立审计、文档/ALL实际状态均在本轮范围。无新的模型架构、自动版本发布、默认/池/Studio部署、Git提交或push。不迁移或控制其他研究任务。

## Contracts and invariants

- 合同 `benchmarks/m66-prism-alpha-dsw.config.json` 在第一局前冻结；各阶段的实际执行源码/数值环境/原生二进制另行hash绑定，必须先verify再运行，已运行源码不得修改。
- 种子：工程9700000..9700003（8局独立工程检查点、不进入研究训练）；训练9701000..9701511；共同评测9711000..9711255；直接对起点9711000..9711511。动作/运行seed见机器合同；不同用途不混样本。
- 竞技主门：六共同对手等权半平得分相对起点的配对下界≥−5个百分点；直接起点半平下界≥45%。总体增强仅在总体差值校正下界>0时声明；直接优势仅在直接下界>50%时声明。两项单侧同时bootstrap（20,000次，family α=.05，每项lower=.025），按seed块先双座、再对手等权；不同动作模式不混合。逐对手变化和区间完整呈现，不推论无过拟合。
- 风格采用相对起点与Balance的实际画像（效率、贵族、0–1VP购牌、大牌得分/时点），没有风格一票否决门。单训练实例不证明训练seed稳健性。完整报告遵守 `prism-practical-promotion-contract.md`、`prism-report-reading-contract.md`、`unified-match-metrics-standard.md`。
- 有限预算：整轮自首个评测/训练启动起6小时；研究训练最多3小时/40,000CPU秒/8GiB聚合RSS/32GiB输出；每个评测子网格最多2小时/20,000CPU秒/8GiB/16GiB。普通arena最多4workers，PPO保留2个Torch线程、当前同步采集，不假装arena速度就是PPO速度。独立进程组/身份/存活检查、父监管失联清理和预算停止须先以工程测试验证。平台cgroup非专属，RSS限制为采样软限制。
- 仅原始完成/提交账本为进度；失败保留现场并停止。不自动扩样、重新选c4、重置预算或恢复死亡训练。原M62/M63负向研究结果不改。

## Implementation plan

冻结数值/对手/种子/竞技门 → 启动固定起点对照和隔离依赖准备 → 容器监管适配与定向测试 → 68边界parity和8局工程贯通 → 冻结训练执行身份、零局预检 → 后台训练 → c4精确审计 → 固定候选greedy评测 → 阅读/审计报告及ALL收口。

## Iteration log

- 20:06：DSW新目录建立，尚无训练。首次pip使用仅PyTorch索引无法找到psutil；安装停止，记录保留。第二次通用依赖走PyPI，Torch走官方CPU索引，固定Torch2.6.0+cpu/NumPy2.2.4/psutil7.0.0/Markdown3.7。
- cgroup创建探针确认只读；本轮采用明确有界的容器监管实现，不篡改旧systemd控制器或借用平台管理员权限。

## Final implementation

容器监管适配 `scripts/prism_dsw_ppo_process.py`、冻结准备器 `scripts/prism_m66_prepare.py`、一次性训练入口 `scripts/prism_m66_train.py` 已实现。PPO numerical identity保持；运行时只绑定进程监管和只写进度包装，不改原采集/审计/优化器更新体。工程检查点不用于正式训练，不标为发布版本。

## Validation and evidence

本轮DSW8项合同/真实进程测试PASS，初始68边界parity组合容差PASS；8工程局/2更新和1024研究训练局/220更新均STOPPED_COMMITTED。最终c4精确32张量/32优化器槽/68parity/全部1024回放及来源核验PASS。独立7168局双方greedy全部完成，0自动重试。本地220抓取文件/ZIP逐文件SHA、13组实际报告DOM、14项发布/阅读/统计回归及119组既有DOM回归PASS；本地从7168逐seed/seat得分投影独立重算bootstrap与原结果完全一致。完整原始回放和PPO恢复checkpoint未下载，本地未另跑全量原回放；真实像素仍NOT_VERIFIED。

## Result and decision

COMPLETED_FIXED_ROUND。研究训练1024局/4轮/220次更新，监督墙钟2023.216s（33.72min），CPU2551.206s，RSS峰3965902848bytes（3.69GiB）；独立greedy7168局全部完成，三arena活动墙钟1261.562s（21.03min），4workers实测340.91局/min（1000局2.93min）。整轮从起点arena启动至报告完成73.51min，含依赖下载/准备/工程/训练/审计/评测/报告，不等于纯训练速度。21:31:31 +08远端报告完成；候选保留未发布，未确认普遍增强。

## Known limitations

DSW容器无systemd、无专属可写cgroup；实例停止可中断任务。完整检查点持久化不等于已验证跨实例自动恢复。真实浏览器视觉仍未验；本轮按机器数据/来源/离线交互验证报告，不越权绕过既有浏览器限制。

## Next authorized gate

本轮已完成并停止，无待补跑游戏。推荐保留最终c4作为研究参照，与精确Prism Alpha v0.1.5及Beta共同使用；不是默认替换或自动发布。进一步训练/新对手范围须新有限合同，不重置本轮预算或扩样追求增强判定。

## 2026-10-05 启动证据与迭代说明

- 合同SHA `1770d3635149f5df7b4f06630457c329604971adb98afb4c81355c93027572aa`；blueprint SHA `0bcc9d33e96624a220bf5d1441ffd13f6e9493b4fd96445332e15f5d317677f6`；训练execution SHA `c2fc25e0c94bc26a610a18c540db5433763fc548fb43cb84e9076b2f2ac623fe`。均先固定再运行；新源码未覆盖旧M63/M65。
- 第二次DSW pip下载在300秒超时，未进入训练；本地官方CPU wheel下载成功，大包SCP160秒超时后确认远端已有66,584,576bytes，SFTP reput续传成功。ZIP逐成员SHA核验后完全离线安装，Torch2.6.0+cpu/NumPy2.2.4/psutil7.0.0/Markdown3.7实际import成功。安装失败日志保留，不计为比赛重试。
- 本机8项测试中4项合同PASS、4项Linux专用skip；DSW最终环境8项全部PASS（1.821s）。初次DSW测试有两个测试管道未关闭ResourceWarning，修正测试清理后复跑PASS；不是训练缺陷或新比赛。Windows工具组合命令对成功unittest有过外层exit1呈现，本次以保存的真实子进程exit0和stderr OK为依据。
- 起点评测来源是独立新目录、已验证通用arena快照，实际3072局已经完成。未查看其胜负来调整训练合同。正式训练waits-before-start确认起点arena完结，避免同时争抢4CPU。
- 工程完成回执的嵌套 `completion.update_attempts=2` 是实际权威值；外围采集进度字段可停留在此前0。正式运行阶段应结合stdout事件/已提交cycle摘要，不将采集末尾快照当作正在更新时的实时状态。冻结运行源码保持，不事后修改其pin。
- 训练自行停在最终c4或预算/失败边界；`control/training/status.json`和逐cycle回执持续在DSW落盘。后续完整c4审计与候选评测使用另外的只读/执行身份，不直接运行旧M62/M63驱动器。

## 完成结论与完整阅读入口（2026-10-05）

**产物：固定最终c4有效、与起点不同，未发布。竞技：保留两项底线，尚未确认增强。风格：小幅混合变化，没有鲜明新路线证据。**

完整双方/座位/经济/VP0..5购牌/五色折扣/贵族/预留/七类动作/时钟表：[人类HTML](prism/m66-prism-alpha-dsw-comparison.html) / [完整人类Markdown](prism/m66-prism-alpha-dsw-comparison.reading.md)。原82表及门/哈希/运行身份：[Agent审计](prism/m66-prism-alpha-dsw-comparison.audit.html) / [原始证据MD](prism/m66-prism-alpha-dsw-evidence.md)。训练16组双方表（每cycle行为策略，候选T=1，非c4独立验收）：`local-artifacts/prism/m66-alpha-dsw/harvest/final-audit/training-report.{md,html}`。

### 独立greedy实战（指标属于候选本人）

共同对手各512局/256双座种子块；两代相同9711000..9711255，action seed66020001。直接起点1024局/512块，9711000..9711511。Score=(胜+0.5×平)/局数，pure win=胜/局数。不同历史cohort不混合。

| 对手 | 起点Prism Alpha v0.1.5 胜/平/负 | 起点半平% | M66最终c4未发布检查点 胜/平/负 | 候选纯胜% | 候选半平% | 候选−起点pp |
| --- | --- | --- | --- | --- | --- | --- |
| Heuristic v0.3.1 | 407/3/102 | 79.79 | 407/3/102 | 79.49 | 79.79 | +0.00 |
| Prism v0.1.0 | 404/3/105 | 79.20 | 414/2/96 | 80.86 | **81.05 ↑** | +1.86 |
| Prism v0.1.1 | 334/7/171 | **65.92 ↑** | 334/1/177 | 65.23 | 65.33 | −0.59 |
| Prism Balance v0.1.0 | 258/7/247 | **51.07 ↑** | 259/4/249 | 50.59 | 50.98 | −0.10 |
| Prism Alpha v0.1.4 | 270/7/235 | 53.42 | 287/7/218 | 56.05 | **56.74 ↑** | +3.32 |
| Prism Beta v0.1.0 | 253/7/252 | **50.10 ↑** | 251/3/258 | 49.02 | 49.32 | −0.78 |
| 直接起点Prism Alpha v0.1.5 | N/A | N/A | 534/8/482 | 52.15 | 52.54 | N/A |

共同对手等权半平平均：起点63.2487% → 候选**63.8672% ↑**，+0.61849pp。它不是所有对手增强：相对Alpha v0.1.4较高，对Beta/通用/Balance略低，启发式显示值相同。逐对手区间和完整双方指标见上方全文，不能据均值删除局部代价。

| 本人共同对手画像（各3072局） | 起点Prism Alpha v0.1.5 | M66最终c4未发布检查点 | 候选−起点 |
| --- | --- | --- | --- |
| VP/本人Main | 0.552641 | **0.553386 ↑** | +0.000745 |
| 贵族覆盖率% | 37.9883 | **38.5091 ↑** | +0.5208pp |
| 0–1VP购牌张/局 | **7.780599 ↑** | 7.722331 | −0.058268 |
| 3–5VP牌印刷分VP/局 | 7.527669 | **7.630859 ↑** | +0.103190 |

VP/本人Main=总终局VP/总本人Main；覆盖=至少一贵族局数/总局数；低分购牌=0和1VP牌总数/局数；大牌分=Σ(3–5VP牌张数×印刷VP)/局数。变化很小，且不能用本表声称更偏Beta；缺乏匹配Balance作为两代模型的全对手画像，不从效率代理推出风格。首张大牌时点本轮NOT_MEASURED，不补造。

### 冻结门、含义和身份

| 检验目的 | 冻结下界要求 | 估计 | 配对95%区间 | 下界 | 原判定与含义 |
| --- | --- | --- | --- | --- | --- |
| 六共同对手相对起点保留 | ≥−5pp | +0.6185pp | [−1.4160,+2.6046]pp | −1.4160pp | PASS；未确认增强（下界未>0） |
| 直接起点竞争力保留 | ≥45% | 52.5391% | [49.7070,55.2734]% | 49.7070% | PASS；未确认直接优势（下界未>50%） |

两项单侧family .05 /2，20,000 bootstrap，seed66029999，lower quantile .025；先双座seed平均，再共同对手等权。阈值/原结果不改，区间跨零/50%不证明等效或模型失败。缺风格差异不是模型整体否决。只有一个训练实例，没有训练seed重复稳健性证据。

- 候选权重SHA `d392a5d13e070173a3c80406acbe2f7028d52e3bbdc34a59864ab84f546588f8`，本地 `local-artifacts/prism/m66-alpha-dsw/harvest/campaigns/training/cycle-4-export/weights.json`；32张量manifest同目录。不是Prism Alpha v0.1.6，也未生成发布model record。
- 结果SHA `53cbbca99085ffea003de17c9b3523331e19def7bcc7f228a2ed55793e4a8bb0`，`benchmarks/m66-prism-alpha-dsw.result.json`；followup execution SHA `154cc3b27e42c047f450ed05defa3fbcfd9e8137f6caa53e98b9f9cdaee2df30`，50源pin。
- 220文件抓取ZIP SHA `0572ce800b8a72cbc37480aa054cbd0a35d1adbcf7ec173146728f62f75fc424` /4,290,046bytes；本地harvest目录原字节保持。完整原回放/恢复状态在DSW持久目录，非已全量取回。
- 本地reading spec仅改抓取路径、中文未发布名称和训练报告链接；原DSW spec/HTML/receipt保持于harvest。`scripts/prism_round_report.py`的新native-greedy适配在冻结评测之后运行，旧报告分支/旧产物不重写；14 Python、119旧DOM和13本轮DOM验证PASS。实际pixels仍NOT_VERIFIED。
- 收尾编辑曾行号错配但未部署，读取修正后AST/工程审计PASS；收尾首次部署校验用系统解释器被环境pin拒绝，0运行/0新局，换正确venv后启动。独立本地统计复查初次仅来源dict排序断言失败，explicit reference/candidate/direct排序后全部统计精确相等，原结果未改。
- 训练完成回执外围update_attempts166是采集阶段残留；嵌套completion和已提交checkpoint均220，最终正确值220。监督进程和收尾完成、PID不再作为活跃所有权；没有循环续训。

本次未提交/推送Git，未改默认/共享池/Studio。ALL连接故障及最后同步结果单独以实际回执为准，不用本页推断看板已更新。
